"""
Testes unitários para o Passo 5: reservar_sala (MRTR completo).
Cobre todos os cenários verificados pelo validador nas checks 9-20.
"""
import unittest
import os

os.environ.setdefault("REQUEST_STATE_SECRET", "a" * 64)

from fastapi.testclient import TestClient
from app import app

DIA = "2026-11-03"
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}},
}
META_SEM_ELICITATION = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def h(hora: str) -> str:
    return f"{DIA}T{hora}:00-03:00"


class TestReservarSala(unittest.TestCase):
    def setUp(self):
        # Recria o estado em memória antes de cada teste importando o módulo limpo
        import importlib
        import regras
        importlib.reload(regras)
        import app as app_module
        importlib.reload(app_module)
        self.client = TestClient(app_module.app)
        self.meta = META
        self.meta_sem_elicitation = META_SEM_ELICITATION

    def _reservar(self, sala, inicio, fim, responsavel="Teste", meta=None):
        return self.client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "reservar_sala",
                "arguments": {"sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel},
                "_meta": meta or self.meta,
            },
        })

    def _retomar(self, chave, resposta_usuario, request_state):
        return self.client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "reservar_sala",
                "arguments": {},
                "inputResponses": {chave: resposta_usuario},
                "requestState": request_state,
                "_meta": self.meta,
            },
        })

    # ── Check 9: sala inexistente ─────────────────────────────────────────────
    def test_sala_inexistente(self):
        resp = self._reservar("sala-delorean", h("09:00"), h("10:00"))
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Sala inexistente: sala-delorean", result["content"][0]["text"])

    # ── Check 10: fora da janela ──────────────────────────────────────────────
    def test_fora_da_janela(self):
        resp = self._reservar("sala-aquario", h("07:00"), h("08:00"))
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("08:00 e 20:00", result["content"][0]["text"])

    # ── Check 11: duração acima de 2h ─────────────────────────────────────────
    def test_duracao_acima_limite(self):
        resp = self._reservar("sala-aquario", h("09:00"), h("12:00"))
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("maximo 2 horas", result["content"][0]["text"])

    # ── Check 12: intervalo invertido ─────────────────────────────────────────
    def test_intervalo_invertido(self):
        resp = self._reservar("sala-aquario", h("10:00"), h("09:00"))
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("fim deve ser posterior a inicio", result["content"][0]["text"])

    # ── Reserva imediata (sem conflito) ───────────────────────────────────────
    def test_reserva_imediata_sem_conflito(self):
        resp = self._reservar("sala-aquario", h("09:00"), h("10:00"))
        result = resp.json()["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertFalse(result.get("isError", False))
        sc = result["structuredContent"]
        self.assertTrue(sc["reservado"])
        self.assertEqual(sc["sala"], "sala-aquario")
        self.assertIn("politica", sc)

    # ── Check 13: conflito → input_required com requestState ─────────────────
    def test_conflito_gera_input_required(self):
        # sala-garagem tem reserva 14h-15h nos dados iniciais
        resp = self._reservar("sala-garagem", h("14:00"), h("15:00"))
        result = resp.json()["result"]
        self.assertEqual(result["resultType"], "input_required")
        self.assertIn("inputRequests", result)
        self.assertEqual(len(result["inputRequests"]), 1)
        self.assertIn("requestState", result)

    # ── Check 14: alternativas na ordem certa (enum) ──────────────────────────
    def test_alternativas_ordem_correta(self):
        # sala-garagem cap=12, sala-fusca cap=12, sala-mirante cap=20
        # sala-fusca < sala-mirante alfabeticamente → [sala-fusca, sala-mirante]
        resp = self._reservar("sala-garagem", h("14:00"), h("15:00"))
        result = resp.json()["result"]
        chave = next(iter(result["inputRequests"]))
        schema = result["inputRequests"][chave]["params"]["requestedSchema"]
        enum = schema["properties"]["sala"]["enum"]
        self.assertEqual(enum, ["sala-fusca", "sala-mirante"])
        self.assertEqual(result["inputRequests"][chave]["params"]["mode"], "form")

    # ── Check 15: sem capability → -32021 ────────────────────────────────────
    def test_sem_capability_elicitation_retorna_32021(self):
        resp = self._reservar("sala-garagem", h("14:00"), h("15:00"), meta=self.meta_sem_elicitation)
        self.assertEqual(resp.status_code, 400)
        err = resp.json()["error"]
        self.assertEqual(err["code"], -32021)
        self.assertIn("requiredCapabilities", err["data"])

    # ── Check 16: retry aceitar conclui reserva ───────────────────────────────
    def test_retry_aceitar_conclui_reserva(self):
        # Primeiro cria conflito na sala-fusca 16h-17h para forçar MRTR
        self._reservar("sala-fusca", h("16:00"), h("17:00"))
        # Tenta novamente (conflito)
        resp = self._reservar("sala-fusca", h("16:00"), h("17:00"))
        result = resp.json()["result"]
        self.assertEqual(result["resultType"], "input_required")
        chave = next(iter(result["inputRequests"]))
        rs = result["requestState"]

        # Obtém enum de alternativas oferecidas
        enum = result["inputRequests"][chave]["params"]["requestedSchema"]["properties"]["sala"]["enum"]
        sala_escolhida = enum[0]  # escolhe a primeira alternativa válida

        resp2 = self._retomar(chave, {"action": "accept", "content": {"sala": sala_escolhida}}, rs)
        result2 = resp2.json()["result"]
        self.assertEqual(result2["resultType"], "complete")
        self.assertFalse(result2.get("isError", False))
        self.assertEqual(result2["structuredContent"]["sala"], sala_escolhida)

    # ── Check 17: requestState adulterado → -32602 ───────────────────────────
    def test_request_state_adulterado_rejeitado(self):
        resp = self._reservar("sala-garagem", h("14:00"), h("15:00"))
        result = resp.json()["result"]
        chave = next(iter(result["inputRequests"]))
        rs = result["requestState"]

        adulterado = rs[:-6] + ("AAAAAA" if not rs.endswith("AAAAAA") else "BBBBBB")
        resp2 = self._retomar(chave, {"action": "accept", "content": {"sala": "sala-fusca"}}, adulterado)
        err = resp2.json().get("error", {})
        self.assertEqual(err.get("code"), -32602)

    # ── Check 18: argumentos adulterados no retry não tomam efeito ───────────
    def test_argumentos_adulterados_no_retry_nao_tomam_efeito(self):
        resp = self._reservar("sala-garagem", h("14:00"), h("15:00"), responsavel="Doc")
        result = resp.json()["result"]
        chave = next(iter(result["inputRequests"]))
        rs = result["requestState"]
        enum = result["inputRequests"][chave]["params"]["requestedSchema"]["properties"]["sala"]["enum"]

        # Retry com sala e responsável adulterados
        resp2 = self.client.post("/mcp", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "reservar_sala",
                "arguments": {"sala": "sala-mirante", "inicio": h("13:00"), "fim": h("14:00"), "responsavel": "Biff"},
                "inputResponses": {chave: {"action": "accept", "content": {"sala": enum[0]}}},
                "requestState": rs,
                "_meta": self.meta,
            },
        })
        dados = (resp2.json().get("result") or {}).get("structuredContent") or {}
        # Deve usar horários do token selado (14:00-15:00, Doc), não os adulterados
        if dados:
            self.assertEqual(dados.get("inicio"), h("14:00"))
            self.assertEqual(dados.get("responsavel"), "Doc")

    # ── Check 19: recusa termina com reservado=False sem isError ──────────────
    def test_recusa_termina_sem_reservar(self):
        resp = self._reservar("sala-garagem", h("14:00"), h("15:00"))
        result = resp.json()["result"]
        chave = next(iter(result["inputRequests"]))
        rs = result["requestState"]

        resp2 = self._retomar(chave, {"action": "decline"}, rs)
        result2 = resp2.json()["result"]
        self.assertEqual(result2["resultType"], "complete")
        self.assertFalse(result2.get("isError", False))
        self.assertFalse(result2["structuredContent"]["reservado"])

    # ── Check 20: conflito sem alternativas → isError com mensagem exata ──────
    def test_sem_alternativas_disponíveis(self):
        # Ocupa todas as salas com capacidade >= sala-mirante (cap=20)
        # sala-mirante é a maior, sem alternativas de capacidade >= 20 exceto ela mesma
        self._reservar("sala-mirante", h("11:00"), h("12:00"))
        resp = self._reservar("sala-mirante", h("11:00"), h("12:00"))
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Sem alternativas disponiveis no intervalo", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
