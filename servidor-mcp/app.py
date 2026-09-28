import sys
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from crypto_state import seal_state, unseal_state
from regras import (
    SALAS, SALAS_POR_ID, RESERVAS,
    validar_politica_e_intervalo, obter_conflitos,
    calcular_alternativas, criar_reserva,
)

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = BASE_DIR / "dados"


def _versao_politica() -> str:
    txt = (DADOS_DIR / "politica-de-uso.md").read_text(encoding="utf-8")
    return txt.splitlines()[0].replace("versao:", "").strip()


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


def _complete(req_id, payload: dict):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "resultType": "complete",
            "structuredContent": payload,
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        },
    }


def _is_error(req_id, message: str):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "resultType": "complete",
            "isError": True,
            "content": [{"type": "text", "text": message}],
        },
    }


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

    # Validação obrigatória da spec MCP v2
    proto_ver = meta.get("io.modelcontextprotocol/protocolVersion")
    client_caps = meta.get("io.modelcontextprotocol/clientCapabilities")

    if not proto_ver or client_caps is None:
        return jsonrpc_error(
            -32602,
            "Request sem io.modelcontextprotocol/protocolVersion ou clientCapabilities no _meta",
            req_id=req_id,
            status_code=400,
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
                    "text": content,
                }
            ]
        },
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
                    "inputSchema": {"type": "object", "properties": {}},
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
                                        "recursos": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["id", "nome", "capacidade", "recursos"],
                                },
                            }
                        },
                        "required": ["salas"],
                    },
                },
                {
                    "name": "consultar_disponibilidade",
                    "description": "Consulta se uma sala esta livre em determinado intervalo e lista conflitos",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "sala": {"type": "string"},
                            "inicio": {"type": "string"},
                            "fim": {"type": "string"},
                        },
                        "required": ["sala", "inicio", "fim"],
                    },
                },
                {
                    "name": "reservar_sala",
                    "description": "Cria uma reserva de sala, com MRTR se houver conflito",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "sala": {"type": "string"},
                            "inicio": {"type": "string"},
                            "fim": {"type": "string"},
                            "responsavel": {"type": "string"},
                        },
                        "required": ["sala", "inicio", "fim", "responsavel"],
                    },
                },
            ]
        },
    }


def handle_tools_call(req_id: any, params: dict, client_caps: dict):
    tool_name = params.get("name")
    args = params.get("arguments", {}) or {}

    if tool_name == "listar_salas":
        payload = {"salas": SALAS}
        return _complete(req_id, payload)

    elif tool_name == "consultar_disponibilidade":
        sala = args.get("sala")
        inicio = args.get("inicio")
        fim = args.get("fim")

        valido, msg_erro, dt_inicio, dt_fim = validar_politica_e_intervalo(sala, inicio, fim)
        if not valido:
            return _is_error(req_id, msg_erro)

        conflitos = obter_conflitos(sala, dt_inicio, dt_fim)
        disponivel = len(conflitos) == 0
        resultado = {
            "disponivel": disponivel,
            "sala": sala,
            "inicio": inicio,
            "fim": fim,
            "conflitos": conflitos,
        }
        return _complete(req_id, resultado)

    elif tool_name == "reservar_sala":
        return handle_reservar_sala(req_id, params, args, client_caps)

    # Tool inexistente: -32602 conforme spec
    return jsonrpc_error(-32602, f"Tool inexistente: {tool_name}", req_id=req_id)


def handle_reservar_sala(req_id: any, params: dict, args: dict, client_caps: dict):
    input_responses = params.get("inputResponses")
    request_state = params.get("requestState")

    # ── CASO A: RETRY (cliente responde à elicitation) ────────────────────────
    if input_responses and request_state:
        valido, payload_ou_erro = unseal_state(request_state)
        if not valido:
            return jsonrpc_error(-32602, f"requestState invalido: {payload_ou_erro}", req_id=req_id)

        dados_selados = payload_ou_erro
        response_key = next(iter(input_responses))
        user_response = input_responses[response_key]
        action = user_response.get("action", "accept")

        if action in ("decline", "cancel"):
            return _complete(req_id, {"reservado": False, "motivo": "Usuario recusou as alternativas oferecidas"})

        # accept: usa sala da resposta do cliente, mas horários/responsável do token selado
        conteudo_resposta = user_response.get("content", {})
        sala_escolhida = conteudo_resposta.get("sala")

        # Valida que sala_escolhida está no enum que foi oferecido (segurança)
        alternativas_seladas = dados_selados.get("alternativas", [])
        if sala_escolhida not in alternativas_seladas:
            # Sala fora do enum oferecido → mantém input_required
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resultType": "input_required",
                    "inputRequests": {
                        f"req-{req_id}-elicit": {
                            "method": "elicitation/create",
                            "params": {
                                "mode": "form",
                                "message": "Escolha invalida. Selecione uma das alternativas disponíveis.",
                                "requestedSchema": {
                                    "type": "object",
                                    "properties": {
                                        "sala": {"type": "string", "enum": alternativas_seladas}
                                    },
                                    "required": ["sala"],
                                },
                            },
                        }
                    },
                    "requestState": request_state,
                },
            }

        # Cria reserva usando exclusivamente dados do token selado
        nova_res = criar_reserva(
            sala_escolhida,
            dados_selados["inicio"],
            dados_selados["fim"],
            dados_selados["responsavel"],
        )
        resultado = {
            "reserva": nova_res["id"],
            "reservado": True,
            "sala": nova_res["sala"],
            "inicio": nova_res["inicio"],
            "fim": nova_res["fim"],
            "responsavel": nova_res["responsavel"],
            "politica": _versao_politica(),
        }
        return _complete(req_id, resultado)

    # ── CASO B: CHAMADA INICIAL ────────────────────────────────────────────────
    sala = args.get("sala")
    inicio = args.get("inicio")
    fim = args.get("fim")
    responsavel = args.get("responsavel")

    valido, msg_erro, dt_inicio, dt_fim = validar_politica_e_intervalo(sala, inicio, fim)
    if not valido:
        return _is_error(req_id, msg_erro)

    conflitos = obter_conflitos(sala, dt_inicio, dt_fim)

    # Sem conflito: reserva imediata
    if not conflitos:
        nova_res = criar_reserva(sala, inicio, fim, responsavel)
        resultado = {
            "reserva": nova_res["id"],
            "reservado": True,
            "sala": nova_res["sala"],
            "inicio": nova_res["inicio"],
            "fim": nova_res["fim"],
            "responsavel": nova_res["responsavel"],
            "politica": _versao_politica(),
        }
        return _complete(req_id, resultado)

    # CONFLITO: verifica capability de elicitation
    elicitation_caps = client_caps.get("elicitation", {})
    if not isinstance(elicitation_caps, dict) or "form" not in elicitation_caps:
        return jsonrpc_error(
            -32021,
            "Client does not support required capability: elicitation/form",
            req_id=req_id,
            data={"requiredCapabilities": ["elicitation.form"]},
            status_code=400,
        )

    # Calcula alternativas
    alternativas = calcular_alternativas(sala, dt_inicio, dt_fim)
    if not alternativas:
        return _is_error(req_id, "Sem alternativas disponiveis no intervalo")

    # Sela estado original + lista de alternativas válidas (para validação no retry)
    estado_original = {
        "sala_original": sala,
        "inicio": inicio,
        "fim": fim,
        "responsavel": responsavel,
        "alternativas": alternativas,
    }
    token_estado = seal_state(estado_original)

    req_id_elicitation = f"req-{req_id}-elicit"
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "resultType": "input_required",
            "inputRequests": {
                req_id_elicitation: {
                    "method": "elicitation/create",
                    "params": {
                        "mode": "form",
                        "message": "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa.",
                        "requestedSchema": {
                            "type": "object",
                            "properties": {
                                "sala": {"type": "string", "enum": alternativas}
                            },
                            "required": ["sala"],
                        },
                    },
                }
            },
            "requestState": token_estado,
        },
    }
