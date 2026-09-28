import unittest
import os
from fastapi.testclient import TestClient
from servidor_mcp.app import app

class TestMCPServer(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Ensure the secret env var is set (required by other modules, though not used here)
        os.environ.setdefault("REQUEST_STATE_SECRET", "0" * 64)  # 32 bytes hex
        # Load expected policy content
        from pathlib import Path
        base_dir = Path(__file__).resolve().parents[2]
        self.policy_path = base_dir / "dados" / "politica-de-uso.md"
        self.policy_content = self.policy_path.read_text(encoding="utf-8")

    def test_missing_meta_returns_error(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "politica://uso"}
        }
        response = self.client.post("/mcp", json=payload)
        self.assertEqual(response.status_code, 400)
        json_resp = response.json()
        self.assertEqual(json_resp["error"]["code"], -32602)
        self.assertIn("protocolVersion", json_resp["error"]["message"])

    def test_invalid_uri_returns_error(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {
                "uri": "outro://uri",
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {}
                }
            }
        }
        response = self.client.post("/mcp", json=payload)
        self.assertEqual(response.status_code, 400)
        json_resp = response.json()
        self.assertEqual(json_resp["error"]["code"], -3262 if False else -32602)  # ensure -32602
        self.assertIn("Resource URI desconhecida", json_resp["error"]["message"])

    def test_successful_read_returns_policy(self):
        payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {
                "uri": "politica://uso",
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {}
                }
            }
        }
        response = self.client.post("/mcp", json=payload)
        self.assertEqual(response.status_code, 200)
        json_resp = response.json()
        self.assertIn("result", json_resp)
        contents = json_resp["result"]["contents"]
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["uri"], "politica://uso")
        self.assertEqual(contents[0]["mimeType"], "text/markdown")
        self.assertEqual(contents[0]["text"], self.policy_content)

    def test_traceparent_logged_to_stderr(self):
        # Capture stderr output
        import sys
        from io import StringIO
        captured = StringIO()
        sys_stderr_original = sys.stderr
        sys.stderr = captured
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/read",
                "params": {
                    "uri": "politica://uso",
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                        "traceparent": "00-abcdef1234567890abcdef1234567890-abcdef1234567890-01"
                    }
                }
            }
            self.client.post("/mcp", json=payload)
        finally:
            sys.stderr = sys_stderr_original
        log_output = captured.getvalue()
        self.assertIn("traceparent=00-abcdef1234567890", log_output)
        self.assertIn("method=resources/read", log_output)
        self.assertIn("id=4", log_output)

if __name__ == '__main__':
    unittest.main()
