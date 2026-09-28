import sys
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from regras import SALAS, SALAS_POR_ID, RESERVAS, validar_politica_e_intervalo, obter_conflitos

app = FastAPI()

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
    elif method == "tools/list":
        return handle_tools_list(req_id)
    elif method == "tools/call":
        return handle_tools_call(req_id, params, client_caps)

    return jsonrpc_error(-32601, f"Metodo nao suportado: {method}", req_id=req_id, status_code=400)


def handle_resources_read(req_id: any, params: dict):
    uri = params.get("uri")
    if uri != "politica://uso":
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


def handle_tools_list(req_id: any):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "tools": [
                {
                    "name": "listar_salas",
                    "description": "Lista todas as salas cadastradas e seus atributos",
                    "inputSchema": {
                        "type": "object",
                        "properties": {}
                    },
                    "outputSchema": {
                        "type": "object",
                        "properties": {
                            "salas": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "nome": {"type": "string"},
                                        "capacidade": {"type": "integer"},
                                        "recursos": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["id", "nome", "capacidade", "recursos"]
                                }
                            }
                        },
                        "required": ["salas"]
                    }
                },
                {
                    "name": "consultar_disponibilidade",
                    "description": "Consulta se uma sala esta livre em determinado intervalo e lista conflitos",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "sala": {"type": "string"},
                            "inicio": {"type": "string"},
                            "fim": {"type": "string"}
                        },
                        "required": ["sala", "inicio", "fim"]
                    }
                },
                {
                    "name": "reservar_sala",
                    "description": "Cria uma reserva de sala",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "sala": {"type": "string"},
                            "inicio": {"type": "string"},
                            "fim": {"type": "string"},
                            "responsavel": {"type": "string"}
                        },
                        "required": ["sala", "inicio", "fim", "responsavel"]
                    }
                }
            ]
        }
    }


def handle_tools_call(req_id: any, params: dict, client_caps: dict):
    tool_name = params.get("name")
    args = params.get("arguments", {}) or {}

    if tool_name == "listar_salas":
        payload = {"salas": SALAS}
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resultType": "complete",
                "structuredContent": payload,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=False)
                    }
                ]
            }
        }

    elif tool_name == "consultar_disponibilidade":
        sala = args.get("sala")
        inicio = args.get("inicio")
        fim = args.get("fim")

        valido, msg_erro, dt_inicio, dt_fim = validar_politica_e_intervalo(sala, inicio, fim)
        if not valido:
            # Erro de execução da tool: isError: True dentro de complete
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resultType": "complete",
                    "isError": True,
                    "content": [{"type": "text", "text": msg_erro}]
                }
            }

        conflitos = obter_conflitos(sala, dt_inicio, dt_fim)
        disponivel = len(conflitos) == 0
        resultado = {
            "disponivel": disponivel,
            "sala": sala,
            "inicio": inicio,
            "fim": fim,
            "conflitos": conflitos
        }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resultType": "complete",
                "structuredContent": resultado,
                "content": [{"type": "text", "text": json.dumps(resultado, ensure_ascii=False)}]
            }
        }

    elif tool_name == "reservar_sala":
        # Será completado no Passo 5 (onde entra o HMAC requestState e a reserva em si)
        return jsonrpc_error(-32601, "reservar_sala sera implementado no Passo 5", req_id=req_id)

    # Tool inexistente: conforme o enunciado, -32602 é aceito
    return jsonrpc_error(-32602, f"Tool inexistente: {tool_name}", req_id=req_id)

