import sys
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# Caminho para a pasta de dados do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = BASE_DIR / "dados"

def log_stderr(method: str | None, req_id: any, traceparent: str | None):
    """Exigência do enunciado: registrar método, id e traceparent em sys.stderr."""
    tp_str = f" traceparent={traceparent}" if traceparent else ""
    sys.stderr.write(f"[MCP] method={method} id={req_id}{tp_str}\n")
    sys.stderr.flush()

def jsonrpc_error(code: int, message: str, req_id: any = None, data: dict = None, status_code: int = 400):
    """Gera envelopes de erro JSON-RPC 2.0 com o status HTTP correspondente."""
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return JSONResponse(
        status_code=status_code,
        content={"jsonrpc": "2.0", "id": req_id, "error": err}
    )

@app.post("/mcp")
async def handle_mcp(request: Request):
    try:
        body = await request.json()
    except Exception:
        return jsonrpc_error(-32700, "Parse error", status_code=400)

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {}) or {}
    meta = params.get("_meta", {}) or {}

    # Extrai traceparent do _meta ou dos cabeçalhos HTTP
    traceparent = meta.get("traceparent") or request.headers.get("traceparent")
    log_stderr(method, req_id, traceparent)

    # Validação obrigatória da spec MCP v2: todo request deve conter version e capabilities no _meta
    proto_ver = meta.get("io.modelcontextprotocol/protocolVersion")
    client_caps = meta.get("io.modelcontextprotocol/clientCapabilities")

    if not proto_ver or client_caps is None:
        return jsonrpc_error(
            -32602,
            "Request sem io.modelcontextprotocol/protocolVersion ou clientCapabilities no _meta",
            req_id=req_id,
            status_code=400
        )

    # Roteamento dos métodos
    if method == "resources/read":
        return handle_resources_read(req_id, params)
    
    # Próximos métodos a serem adicionados no Passo 4 e 5:
    # elif method == "tools/list": ...
    # elif method == "tools/call": ...

    return jsonrpc_error(-32601, f"Metodo nao suportado: {method}", req_id=req_id, status_code=400)

def handle_resources_read(req_id: any, params: dict):
    uri = params.get("uri")
    if uri != "politica://uso":
        # A spec proíbe contents vazio: URI desconhecida deve retornar -32602
        return jsonrpc_error(-32602, f"Resource URI desconhecida: {uri}", req_id=req_id, status_code=400)

    politica_path = DADOS_DIR / "politica-de-uso.md"
    if not politica_path.exists():
        return jsonrpc_error(-32603, "Arquivo politica-de-uso.md nao encontrado", req_id=req_id, status_code=500)

    content = politica_path.read_text(encoding="utf-8")
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "contents": [
                {
                    "uri": "politica://uso",
                    "mimeType": "text/markdown",
                    "text": content
                }
            ]
        }
    }
