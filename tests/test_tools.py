import unittest
import os
import json

os.environ.setdefault("REQUEST_STATE_SECRET", "0" * 64)

from fastapi.testclient import TestClient

# PYTHONPATH=servidor-mcp deve estar ativo para o import funcionar
from app import app

META_VALIDO = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {}
}

def post_mcp(client, method, extra_params=None):
    params = {"_meta": META_VALIDO}
    if extra_params:
        params.update(extra_params)
    return client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    })


class TestToolsList(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_tools_list_retorna_tres_tools(self):
        resp = post_mcp(self.client, "tools/list")
        self.assertEqual(resp.status_code, 200)
        tools = resp.json()["result"]["tools"]
        nomes = [t["name"] for t in tools]
        self.assertIn("listar_salas", nomes)
        self.assertIn("consultar_disponibilidade", nomes)
        self.assertIn("reservar_sala", nomes)

    def test_tools_list_schemas_presentes(self):
        resp = post_mcp(self.client, "tools/list")
        tools = {t["name"]: t for t in resp.json()["result"]["tools"]}
        # listar_salas tem inputSchema e outputSchema
        self.assertIn("inputSchema", tools["listar_salas"])
        self.assertIn("outputSchema", tools["listar_salas"])
        # consultar_disponibilidade tem campos obrigatórios no inputSchema
        required = tools["consultar_disponibilidade"]["inputSchema"]["required"]
        self.assertIn("sala", required)
        self.assertIn("inicio", required)
        self.assertIn("fim", required)
        # reservar_sala exige responsavel
        required_res = tools["reservar_sala"]["inputSchema"]["required"]
        self.assertIn("responsavel", required_res)


class TestListarSalas(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_listar_salas_retorna_cinco_salas(self):
        resp = post_mcp(self.client, "tools/call", {"name": "listar_salas", "arguments": {}})
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["result"]
        self.assertEqual(result["resultType"], "complete")
        salas = result["structuredContent"]["salas"]
        self.assertEqual(len(salas), 5)

    def test_listar_salas_contem_campos_obrigatorios(self):
        resp = post_mcp(self.client, "tools/call", {"name": "listar_salas", "arguments": {}})
        salas = resp.json()["result"]["structuredContent"]["salas"]
        for sala in salas:
            self.assertIn("id", sala)
            self.assertIn("nome", sala)
            self.assertIn("capacidade", sala)
            self.assertIn("recursos", sala)

    def test_listar_salas_retorna_texto_plano(self):
        resp = post_mcp(self.client, "tools/call", {"name": "listar_salas", "arguments": {}})
        content = resp.json()["result"]["content"]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")
        # Deve ser JSON serializável
        parsed = json.loads(content[0]["text"])
        self.assertIn("salas", parsed)


class TestConsultarDisponibilidade(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _call(self, sala, inicio, fim):
        return post_mcp(self.client, "tools/call", {
            "name": "consultar_disponibilidade",
            "arguments": {"sala": sala, "inicio": inicio, "fim": fim}
        })

    def test_sala_inexistente(self):
        resp = self._call("sala-nao-existe", "2026-11-03T14:00:00-03:00", "2026-11-03T15:00:00-03:00")
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["content"][0]["text"], "Sala inexistente: sala-nao-existe")

    def test_intervalo_invertido(self):
        resp = self._call("sala-aquario", "2026-11-03T15:00:00-03:00", "2026-11-03T14:00:00-03:00")
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("fim deve ser posterior a inicio", result["content"][0]["text"])

    def test_duracao_acima_do_limite(self):
        resp = self._call("sala-aquario", "2026-11-03T09:00:00-03:00", "2026-11-03T11:01:00-03:00")
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("maximo 2 horas", result["content"][0]["text"])

    def test_fora_da_janela_antes_das_8h(self):
        resp = self._call("sala-aquario", "2026-11-03T07:00:00-03:00", "2026-11-03T08:00:00-03:00")
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("08:00 e 20:00", result["content"][0]["text"])

    def test_fora_da_janela_apos_20h(self):
        resp = self._call("sala-aquario", "2026-11-03T19:30:00-03:00", "2026-11-03T20:01:00-03:00")
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("08:00 e 20:00", result["content"][0]["text"])

    def test_disponivel_sem_conflito(self):
        # sala-aquario não tem reservas em reservas.json
        resp = self._call("sala-aquario", "2026-11-03T10:00:00-03:00", "2026-11-03T11:00:00-03:00")
        result = resp.json()["result"]
        self.assertNotIn("isError", result)
        self.assertTrue(result["structuredContent"]["disponivel"])
        self.assertEqual(result["structuredContent"]["conflitos"], [])

    def test_indisponivel_com_conflito(self):
        # sala-garagem tem reserva de 14h–15h em reservas.json
        resp = self._call("sala-garagem", "2026-11-03T14:30:00-03:00", "2026-11-03T15:30:00-03:00")
        result = resp.json()["result"]
        self.assertNotIn("isError", result)
        self.assertFalse(result["structuredContent"]["disponivel"])
        self.assertGreater(len(result["structuredContent"]["conflitos"]), 0)

    def test_tool_inexistente(self):
        resp = post_mcp(self.client, "tools/call", {"name": "ferramenta_desconhecida", "arguments": {}})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
