"""
Agente A2A — porta 7300.

Por dentro: cliente MCP puro (FastAPI + httpx), sem SDK de LLM.
Por fora:   Agent Card + endpoint /a2a com SendMessage e GetTask.

Máquina de estados de Task:
  SUBMITTED → WORKING → COMPLETED | FAILED | INPUT_REQUIRED
  INPUT_REQUIRED → COMPLETED | CANCELED (via retry)
"""
import sys
import re
import uuid
import json
import httpx
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse

# Permite substituir em testes: agente.app.AsyncClientFactory = MockClass
AsyncClientFactory = httpx.AsyncClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_event()
    yield


app = FastAPI(lifespan=lifespan)

MCP_URL = "http://localhost:7301/mcp"

# ── Estado em memória ──────────────────────────────────────────────────────────
# taskId → Task object (formato A2A wire)
TASKS: Dict[str, Dict[str, Any]] = {}
# taskId → contexto de pausa: requestState + elicit_key + alternativas
PAUSED: Dict[str, Dict[str, Any]] = {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_message_id() -> str:
    return f"msg-{uuid.uuid4().hex[:12]}"


def agent_message(text: str, task_id: str, context_id: str) -> dict:
    return {
        "messageId": make_message_id(),
        "role": "ROLE_AGENT",
        "parts": [{"text": text}],
        "taskId": task_id,
        "contextId": context_id,
    }


def make_task(task_id: str, context_id: str, state: str, user_msg: dict, status_msg: dict) -> dict:
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": state,
            "message": status_msg,
        },
        "history": [user_msg, status_msg],
        "artifacts": [],
    }


def jsonrpc_error(req_id, code: int, message: str, status: int = 400):
    return JSONResponse(
        status_code=status,
        content={"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
    )


# ── Cliente MCP ────────────────────────────────────────────────────────────────

async def call_mcp(
    method: str,
    params: dict,
    traceparent: Optional[str] = None,
    name_header: Optional[str] = None,
) -> dict:
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}},
    }
    if traceparent:
        meta["traceparent"] = traceparent

    params_with_meta = {**params, "_meta": meta}
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if name_header:
        headers["Mcp-Name"] = name_header
    if traceparent:
        headers["traceparent"] = traceparent

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),  # ID único por request — obrigatório na spec
        "method": method,
        "params": params_with_meta,
    }

    async with AsyncClientFactory() as client:
        resp = await client.post(MCP_URL, json=payload, headers=headers, timeout=10.0)
        return resp.json()


# ── Startup: handshake com MCP ─────────────────────────────────────────────────

async def startup_event():
    try:
        # tools/list antes de qualquer tools/call (exigência do enunciado)
        await call_mcp("tools/list", {})
        # resources/read da política — confirma que o MCP está operacional
        await call_mcp("resources/read", {"uri": "politica://uso"}, name_header="politica://uso")
        sys.stderr.write("[AGENTE] Handshake MCP concluido.\n")
    except Exception as e:
        sys.stderr.write(f"[AGENTE] Falha no handshake MCP: {e}\n")


# ── Agent Card ─────────────────────────────────────────────────────────────────

@app.get("/.well-known/agent-card.json")
async def get_agent_card():
    """
    Estrutura fiel ao wire format exemplos/wire/07-a2a-agent-card.json.
    Campos obrigatórios para o validador:
      - supportedInterfaces[].protocolBinding = "JSONRPC"
      - supportedInterfaces[].protocolVersion começa com "1.0"
      - supportedInterfaces[].url
      - skills[].id = "reservar-sala"
    """
    return {
        "name": "Central de Salas",
        "description": "Reserva salas de reuniao da Hill Valley Tech.",
        "provider": {
            "organization": "Hill Valley Tech",
            "url": "https://hillvalley.example",
        },
        "version": "1.0.0",
        "supportedInterfaces": [
            {
                "url": "http://localhost:7300/a2a",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "reservar-sala",
                "name": "Reservar sala",
                "description": "Reserva uma sala em um intervalo. Se houver conflito, pergunta qual alternativa usar.",
                "tags": ["salas", "agenda"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
                "examples": [
                    "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
                ],
            }
        ],
    }


# ── Endpoint A2A ───────────────────────────────────────────────────────────────

@app.post("/a2a")
async def handle_a2a(request: Request, traceparent: Optional[str] = Header(None)):
    try:
        body = await request.json()
    except Exception:
        return jsonrpc_error(None, -32700, "Parse error")

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {}) or {}

    if method == "GetTask":
        return handle_get_task(req_id, params)
    elif method == "SendMessage":
        return await handle_send_message(req_id, params, traceparent)

    return jsonrpc_error(req_id, -32601, "Metodo desconhecido")


def handle_get_task(req_id, params: dict):
    task_id = params.get("id")
    task = TASKS.get(task_id)
    if not task:
        return jsonrpc_error(req_id, -32602, f"Task nao encontrada: {task_id}", status=404)
    return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}


async def handle_send_message(req_id, params: dict, traceparent: Optional[str]):
    message = params.get("message", {})
    task_id = message.get("taskId") or params.get("taskId")

    # Extrai texto da mensagem
    text = ""
    for part in message.get("parts", []):
        if "text" in part:
            text = part["text"].strip()
            break

    # ── CONTINUAÇÃO de Task existente ──────────────────────────────────────────
    if task_id:
        return await handle_continuation(req_id, task_id, message, text, traceparent)

    # ── NOVA Task ──────────────────────────────────────────────────────────────
    return await handle_new_task(req_id, message, text, traceparent)


async def handle_new_task(req_id, user_message: dict, text: str, traceparent: Optional[str]):
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    context_id = f"ctx-{uuid.uuid4().hex[:12]}"

    # Parse do comando: reservar sala=<id> inicio=<iso> fim=<iso> responsavel=<nome>
    padrao = r"reservar\s+sala=(\S+)\s+inicio=(\S+)\s+fim=(\S+)\s+responsavel=(\S+)"
    match = re.match(padrao, text)

    if not match:
        status_msg = agent_message("Comando invalido", task_id, context_id)
        task = make_task(task_id, context_id, "TASK_STATE_FAILED", user_message, status_msg)
        TASKS[task_id] = task
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}

    sala, inicio, fim, responsavel = match.groups()

    # Chama MCP — propagando traceparent
    mcp_res = await call_mcp(
        "tools/call",
        {"name": "reservar_sala", "arguments": {"sala": sala, "inicio": inicio, "fim": fim, "responsavel": responsavel}},
        traceparent=traceparent,
        name_header="reservar_sala",
    )
    result = mcp_res.get("result", {})

    # ── Erro de execução da tool (isError) ──
    if result.get("isError"):
        msg_erro = (result.get("content") or [{}])[0].get("text", "Erro na execucao da tool")
        status_msg = agent_message(msg_erro, task_id, context_id)
        task = make_task(task_id, context_id, "TASK_STATE_FAILED", user_message, status_msg)
        TASKS[task_id] = task
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}

    # ── input_required: conflito detectado ──
    if result.get("resultType") == "input_required":
        input_requests = result.get("inputRequests", {})
        elicit_key = next(iter(input_requests), None)
        elicit_params = (input_requests.get(elicit_key) or {}).get("params", {})
        alternativas = (
            elicit_params.get("requestedSchema", {})
            .get("properties", {})
            .get("sala", {})
            .get("enum", [])
        )

        # Guarda contexto de pausa — requestState NUNCA vai para a resposta A2A
        PAUSED[task_id] = {
            "requestState": result.get("requestState"),
            "key": elicit_key,
            "alternativas": alternativas,
        }

        alt_str = ", ".join(alternativas)
        status_msg = agent_message(f"alternativas: {alt_str}", task_id, context_id)
        task = make_task(task_id, context_id, "TASK_STATE_INPUT_REQUIRED", user_message, status_msg)
        TASKS[task_id] = task
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}

    # ── complete: reserva criada diretamente ──
    if result.get("resultType") == "complete":
        struct = result.get("structuredContent", {})
        status_msg = agent_message(
            f"Reserva {struct.get('reserva', '')} confirmada na {struct.get('sala', '')}.",
            task_id, context_id,
        )
        task = make_task(task_id, context_id, "TASK_STATE_COMPLETED", user_message, status_msg)
        task["artifacts"] = [
            {
                "artifactId": f"art-{uuid.uuid4().hex[:12]}",
                "name": "reserva",
                "parts": [{"text": json.dumps(struct, ensure_ascii=False, separators=(",", ":"))}],
            }
        ]
        TASKS[task_id] = task
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}

    # Fallback: estado desconhecido
    status_msg = agent_message("Resposta inesperada do MCP", task_id, context_id)
    task = make_task(task_id, context_id, "TASK_STATE_FAILED", user_message, status_msg)
    TASKS[task_id] = task
    return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}


async def handle_continuation(req_id, task_id: str, user_message: dict, text: str, traceparent: Optional[str]):
    task = TASKS.get(task_id)
    if not task:
        return jsonrpc_error(req_id, -32602, f"Task nao encontrada: {task_id}", status=404)

    state = (task.get("status") or {}).get("state", "")
    context_id = task.get("contextId", "")

    # Rejeita SendMessage em Task terminal (check 31)
    if state in ("TASK_STATE_COMPLETED", "TASK_STATE_CANCELED", "TASK_STATE_FAILED"):
        return jsonrpc_error(req_id, -32602, f"Task {task_id} esta em estado terminal: {state}")

    # Adiciona mensagem do usuário ao histórico
    task["history"].append(user_message)

    m = re.match(r"^escolha=(.+)$", text)
    if not m:
        status_msg = agent_message("Formato invalido. Use: escolha=<id> ou escolha=recusar", task_id, context_id)
        task["history"].append(status_msg)
        task["status"]["message"] = status_msg
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}

    escolha = m.group(1).strip()
    paused = PAUSED.get(task_id, {})
    req_state = paused.get("requestState")
    elicit_key = paused.get("key")
    alternativas = paused.get("alternativas", [])

    # ── Recusa ──
    if escolha == "recusar":
        await call_mcp(
            "tools/call",
            {
                "name": "reservar_sala",
                "arguments": {},
                "inputResponses": {elicit_key: {"action": "decline"}},
                "requestState": req_state,
            },
            traceparent=traceparent,
            name_header="reservar_sala",
        )
        status_msg = agent_message("Reserva cancelada pelo usuario.", task_id, context_id)
        task["history"].append(status_msg)
        task["status"] = {"state": "TASK_STATE_CANCELED", "message": status_msg}
        PAUSED.pop(task_id, None)
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}

    # ── Escolha fora do enum: mantém INPUT_REQUIRED ──
    if escolha not in alternativas:
        alt_str = ", ".join(alternativas)
        status_msg = agent_message(f"alternativas: {alt_str}", task_id, context_id)
        task["history"].append(status_msg)
        task["status"]["message"] = status_msg
        # estado permanece TASK_STATE_INPUT_REQUIRED
        return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}

    # ── Aceita: envia retry para o MCP com sala escolhida ──
    mcp_res = await call_mcp(
        "tools/call",
        {
            "name": "reservar_sala",
            "arguments": {},
            "inputResponses": {elicit_key: {"action": "accept", "content": {"sala": escolha}}},
            "requestState": req_state,
        },
        traceparent=traceparent,
        name_header="reservar_sala",
    )
    result = mcp_res.get("result", {})
    struct = result.get("structuredContent", {})

    status_msg = agent_message(
        f"Reserva {struct.get('reserva', '')} confirmada na {struct.get('sala', '')}.",
        task_id, context_id,
    )
    task["history"].append(status_msg)
    task["status"] = {"state": "TASK_STATE_COMPLETED", "message": status_msg}
    task["artifacts"] = [
        {
            "artifactId": f"art-{uuid.uuid4().hex[:12]}",
            "name": "reserva",
            "parts": [{"text": json.dumps(struct, ensure_ascii=False, separators=(",", ":"))}],
        }
    ]
    PAUSED.pop(task_id, None)
    return {"jsonrpc": "2.0", "id": req_id, "result": {"task": task}}
