import json
from datetime import datetime
from pathlib import Path
from typing import Tuple, Dict, Any, List

BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = BASE_DIR / "dados"


def carregar_salas() -> List[Dict[str, Any]]:
    path = DADOS_DIR / "salas.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_reservas_iniciais() -> List[Dict[str, Any]]:
    path = DADOS_DIR / "reservas.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


SALAS = carregar_salas()
SALAS_POR_ID = {s["id"]: s for s in SALAS}

# Estado em memória das reservas (inicializado com reservas.json)
RESERVAS: List[Dict[str, Any]] = carregar_reservas_iniciais()
CONTADOR_RESERVA = len(RESERVAS) + 1


def validar_politica_e_intervalo(
    sala_id: str, inicio_str: str, fim_str: str
) -> Tuple[bool, str | None, datetime | None, datetime | None]:
    """
    Aplica as validações exatas com as mensagens exigidas pelo enunciado.
    Retorna (valido, mensagem_erro, dt_inicio, dt_fim).
    """
    if sala_id not in SALAS_POR_ID:
        return False, f"Sala inexistente: {sala_id}", None, None

    try:
        dt_inicio = datetime.fromisoformat(inicio_str)
        dt_fim = datetime.fromisoformat(fim_str)
    except Exception:
        return False, "Intervalo invalido: formato ISO8601 esperado", None, None

    # Intervalo invertido ou vazio
    if dt_fim <= dt_inicio:
        return False, "Intervalo invalido: fim deve ser posterior a inicio", None, None

    # Duração máxima de 2 horas (7200 segundos)
    duracao_segundos = (dt_fim - dt_inicio).total_seconds()
    if duracao_segundos > 7200:
        return False, "Duracao acima do limite: a politica permite no maximo 2 horas", None, None

    # Janela de uso: 08:00 às 20:00 no horário local especificado
    # .hour retorna a hora já com o offset embutido no datetime com tzinfo
    hora_inicio = dt_inicio.hour * 60 + dt_inicio.minute
    hora_fim = dt_fim.hour * 60 + dt_fim.minute

    if hora_inicio < 8 * 60 or hora_fim > 20 * 60:
        return False, "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00", None, None

    return True, None, dt_inicio, dt_fim


def obter_conflitos(
    sala_id: str, dt_inicio: datetime, dt_fim: datetime
) -> List[Dict[str, Any]]:
    """Identifica reservas sobrepostas para a sala no intervalo informado."""
    conflitos = []
    for res in RESERVAS:
        if res["sala"] != sala_id:
            continue
        res_inicio = datetime.fromisoformat(res["inicio"])
        res_fim = datetime.fromisoformat(res["fim"])

        # Há sobreposição se: max(inicio1, inicio2) < min(fim1, fim2)
        if max(dt_inicio, res_inicio) < min(dt_fim, res_fim):
            conflitos.append(res)
    return conflitos
