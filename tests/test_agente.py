"""
Testes unitários para o Agente A2A (Passo 6).
Estratégia: TestClient como CONTEXT MANAGER força o lifespan/startup.
O mock é injetado antes do `with TestClient(app) as client`.
Cobre checks 21-35 do validador.
"""
import unittest
import os
import json
import uuid

os.environ.setdefault("REQUEST_STATE_SECRET", "a" * 64)

import httpx

DIA = "2026-11-03"


def h(hora: str) -> str:
    return f"{DIA}T{hora}:00-03:00"


# ── Respostas MCP pré-fabricadas ───────────────────────────────────────────────

def _tools_list():
    return {"jsonrpc": "2.0", "id": "x", "result": {"tools": [
        {"name": "reservar_sala", "inputSchema": {"type": "object"}},
    ]}}


def _policy():
    return {"jsonrpc": "2.0", "id": "x", "result": {
        "contents": [{"uri": "politica://uso", "text": "versao: 2026-11-01\nTexto."}]
    }}


def _reserva_completa(sala="sala-aquario"):
    return {"jsonrpc": "2.0", "id": "x", "result": {
        "resultType": "complete",
        "structuredContent": {
            "reserva": "res-0001", "reservado": True, "sala": sala,
            "inicio": h("09:00"), "fim": h("10:00"),
            "responsavel": "Doc", "politica": "2026-11-01"
        },
        "content": [{"type": "text", "text": "{}"}]
    }}


def _input_required(alternativas=("sala-fusca", "sala-mirante"), token="TOKEN-SECRETO"):
    return {"jsonrpc": "2.0", "id": "x", "result": {
        "resultType": "input_required",
        "inputRequests": {
            "req-elicit-1": {
                "method": "elicitation/create",
                "params": {
                    "mode": "form",
                    "message": "Sala ocupada.",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {"sala": {"type": "string", "enum": list(alternativas)}},
                        "required": ["sala"]
                    }
                }
            }
        },
        "requestState": token
    }}


def _is_error(msg="Sala inexistente: sala-delorean"):
    return {"jsonrpc": "2.0", "id": "x", "result": {
        "resultType": "complete", "isError": True,
        "content": [{"type": "text", "text": msg}]
    }}


def _retry_completo(sala="sala-fusca"):
    return {"jsonrpc": "2.0", "id": "x", "result": {
        "resultType": "complete",
        "structuredContent": {
            "reserva": "res-0002", "reservado": True, "sala": sala,
            "inicio": h("14:00"), "fim": h("15:00"),
            "responsavel": "Marty", "politica": "2026-11-01"
        },
        "content": [{"type": "text", "text": "{}"}]
    }}


def _decline_ok():
    return {"jsonrpc": "2.0", "id": "x", "result": {
        "resultType": "complete",
        "structuredContent": {"reservado": False, "motivo": "Recusado"},
        "content": [{"type": "text", "text": "{}"}]
    }}


# ── Context manager: injeta mock + executa lifespan via `with` ────────────────

def make_mock_factory(responses: list):
    """Cria um mock de httpx.AsyncClient que serve respostas em sequência."""
    call_idx = [0]

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            idx = call_idx[0]
            call_idx[0] += 1
            body = responses[idx] if idx < len(responses) else {"jsonrpc": "2.0", "id": "x", "result": {}}
            return httpx.Response(200, json=body)

    return MockAsyncClient


class AgentTestCase(unittest.TestCase):
    """
    Base para testes do agente. Subclasses definem `self.responses`.
    O `setUp` injeta o mock e abre o TestClient com o lifespan ativo.
    """
    responses: list = []

    def setUp(self):
        import importlib
        import agente.app as m
        importlib.reload(m)
        m.AsyncClientFactory = make_mock_factory(self.responses)
        self._app_module = m

        from fastapi.testclient import TestClient
        self._tc = TestClient(m.app)
        self._cm = self._tc.__enter__()
        self.client = self._cm

    def tearDown(self):
        try:
            self._tc.__exit__(None, None, None)
        except Exception:
            pass

    def send(self, texto, task_id=None, traceparent=None):
        msg = {"messageId": f"msg-{uuid.uuid4().hex[:8]}", "role": "ROLE_USER",
               "parts": [{"text": texto}]}
        if task_id:
            msg["taskId"] = task_id
        headers = {}
        if traceparent:
            headers["traceparent"] = traceparent
        return self.client.post("/a2a", json={
            "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "SendMessage",
            "params": {"message": msg}
        }, headers=headers)


# ── Check 21-23: Agent Card ────────────────────────────────────────────────────

class TestAgentCard(AgentTestCase):
    responses = [_tools_list(), _policy()]

    def test_card_200_json(self):
        resp = self.client.get("/.well-known/agent-card.json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), dict)
        self.assertIn("name", resp.json())

    def test_card_supported_interfaces_jsonrpc_1_0(self):
        card = self.client.get("/.well-known/agent-card.json").json()
        interfaces = card.get("supportedInterfaces", [])
        ok = any(
            str(i.get("protocolBinding", "")).upper().startswith("JSONRPC")
            and i.get("url")
            and str(i.get("protocolVersion", "")).startswith("1.0")
            for i in interfaces
        )
        self.assertTrue(ok, f"Interfaces sem JSONRPC 1.0: {interfaces}")

    def test_card_skill_reservar_sala(self):
        card = self.client.get("/.well-known/agent-card.json").json()
        ids = {s.get("id") for s in card.get("skills", [])}
        self.assertIn("reservar-sala", ids)


# ── Check 24-26: sala livre → COMPLETED + artifact + GetTask ─────────────────

class TestSalaLivre(AgentTestCase):
    # startup (2) + 1 tools/call para reserva direta
    responses = [_tools_list(), _policy(), _reserva_completa("sala-porao")]

    def test_sala_livre_completa_task(self):
        resp = self.send(f"reservar sala=sala-porao inicio={h('09:00')} fim={h('10:00')} responsavel=Doc")
        task = resp.json()["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertTrue(task.get("id"))
        self.assertTrue(task.get("contextId"))

    def test_artifact_nome_reserva_e_politica(self):
        resp = self.send(f"reservar sala=sala-porao inicio={h('09:00')} fim={h('10:00')} responsavel=Doc")
        task = resp.json()["result"]["task"]
        arts = task.get("artifacts", [])
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0]["name"], "reserva")
        body = json.loads(arts[0]["parts"][0]["text"])
        self.assertEqual(body["politica"], "2026-11-01")
        self.assertEqual(body["sala"], "sala-porao")

    def test_get_task_retorna_contextid_e_estado(self):
        resp = self.send(f"reservar sala=sala-porao inicio={h('09:00')} fim={h('10:00')} responsavel=Doc")
        task_id = resp.json()["result"]["task"]["id"]

        get_resp = self.client.post("/a2a", json={
            "jsonrpc": "2.0", "id": 2, "method": "GetTask",
            "params": {"id": task_id}
        })
        t = get_resp.json()["result"]["task"]
        self.assertEqual(t["id"], task_id)
        self.assertTrue(t.get("contextId"))
        self.assertEqual(t["status"]["state"], "TASK_STATE_COMPLETED")


# ── Check 27-29: conflito → INPUT_REQUIRED, enum, escolha errada ──────────────

class TestConflitoInputRequired(AgentTestCase):
    # startup (2) + input_required (1); escolha inválida não chama MCP
    responses = [_tools_list(), _policy(), _input_required()]

    def test_conflito_pausa_em_input_required(self):
        resp = self.send(f"reservar sala=sala-garagem inicio={h('14:00')} fim={h('15:00')} responsavel=Marty")
        task = resp.json()["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_INPUT_REQUIRED")

    def test_conflito_lista_alternativas_no_status(self):
        resp = self.send(f"reservar sala=sala-garagem inicio={h('14:00')} fim={h('15:00')} responsavel=Marty")
        task = resp.json()["result"]["task"]
        msg_text = task["status"]["message"]["parts"][0]["text"]
        self.assertIn("alternativas: sala-fusca, sala-mirante", msg_text)

    def test_request_state_nao_vaza_na_resposta(self):
        resp = self.send(f"reservar sala=sala-garagem inicio={h('14:00')} fim={h('15:00')} responsavel=Marty")
        self.assertNotIn("TOKEN-SECRETO", resp.text)


class TestEscolhaForaEnum(AgentTestCase):
    # startup (2) + input_required (1); escolha inválida não chama MCP
    responses = [_tools_list(), _policy(), _input_required()]

    def test_escolha_fora_enum_mantem_input_required(self):
        resp1 = self.send(f"reservar sala=sala-garagem inicio={h('14:00')} fim={h('15:00')} responsavel=Marty")
        task_id = resp1.json()["result"]["task"]["id"]

        resp2 = self.send("escolha=sala-aquario", task_id=task_id)
        task2 = resp2.json()["result"]["task"]
        self.assertEqual(task2["status"]["state"], "TASK_STATE_INPUT_REQUIRED")


# ── Check 30: aceita → COMPLETED na sala escolhida ───────────────────────────

class TestAceitar(AgentTestCase):
    responses = [_tools_list(), _policy(),
                 _input_required(["sala-fusca", "sala-mirante"]),
                 _retry_completo("sala-fusca")]

    def test_aceitar_conclui_na_sala_escolhida(self):
        resp1 = self.send(f"reservar sala=sala-garagem inicio={h('14:00')} fim={h('15:00')} responsavel=Marty")
        task_id = resp1.json()["result"]["task"]["id"]

        resp2 = self.send("escolha=sala-fusca", task_id=task_id)
        task2 = resp2.json()["result"]["task"]
        self.assertEqual(task2["status"]["state"], "TASK_STATE_COMPLETED")
        body = json.loads(task2["artifacts"][0]["parts"][0]["text"])
        self.assertEqual(body["sala"], "sala-fusca")


# ── Check 31: SendMessage em Task terminal → erro ────────────────────────────

class TestTaskTerminal(AgentTestCase):
    responses = [_tools_list(), _policy(), _reserva_completa("sala-porao")]

    def test_mensagem_em_task_terminal_retorna_erro(self):
        resp1 = self.send(f"reservar sala=sala-porao inicio={h('09:00')} fim={h('10:00')} responsavel=Doc")
        task_id = resp1.json()["result"]["task"]["id"]

        resp2 = self.send("escolha=sala-mirante", task_id=task_id)
        self.assertIn("error", resp2.json())


# ── Check 32: recusa → CANCELED ──────────────────────────────────────────────

class TestRecusa(AgentTestCase):
    responses = [_tools_list(), _policy(), _input_required(), _decline_ok()]

    def test_recusa_cancela_task(self):
        resp1 = self.send(f"reservar sala=sala-garagem inicio={h('14:00')} fim={h('15:00')} responsavel=Marty")
        task_id = resp1.json()["result"]["task"]["id"]

        resp2 = self.send("escolha=recusar", task_id=task_id)
        task2 = resp2.json()["result"]["task"]
        self.assertEqual(task2["status"]["state"], "TASK_STATE_CANCELED")


# ── Check 35: sala inexistente → FAILED com mensagem exata ───────────────────

class TestSalaInexistente(AgentTestCase):
    responses = [_tools_list(), _policy(), _is_error("Sala inexistente: sala-delorean")]

    def test_sala_inexistente_gera_failed(self):
        resp = self.send(f"reservar sala=sala-delorean inicio={h('09:00')} fim={h('10:00')} responsavel=Doc")
        task = resp.json()["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_FAILED")
        msg = task["status"]["message"]["parts"][0]["text"]
        self.assertIn("Sala inexistente: sala-delorean", msg)


if __name__ == "__main__":
    unittest.main()
