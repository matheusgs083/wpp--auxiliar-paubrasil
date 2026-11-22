"""Horário em que a digitação de novos pedidos pelo painel é encerrada.

O gerencial define um horário (HH:MM, hora de Patos). A partir dele, vendedores
não enviam novos pedidos até a virada do dia; à 00:00 a digitação volta a abrir.
Horário vazio significa sem bloqueio.
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

FUSO_PEDIDOS = ZoneInfo("America/Fortaleza")

_FORMATO_HORARIO = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def normalizar_horario_bloqueio(valor: Any) -> str:
    """Devolve "" (sem bloqueio) ou o horário no formato HH:MM."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    if len(texto) == 4 and texto[1] == ":":
        texto = f"0{texto}"
    if not _FORMATO_HORARIO.match(texto):
        raise ValueError("Informe o horário de bloqueio no formato HH:MM, por exemplo 17:30.")
    if texto == "00:00":
        raise ValueError("Use um horário depois de 00:00, ou deixe vazio para não bloquear.")
    return texto


def situacao_bloqueio(horario_bloqueio: str, agora: datetime | None = None) -> dict[str, Any]:
    """Diz se a digitação está encerrada agora e quanto falta para encerrar."""
    horario = normalizar_horario_bloqueio(horario_bloqueio)
    if not horario:
        return {"horario_bloqueio": "", "bloqueado": False, "segundos_ate_bloqueio": None, "mensagem": ""}

    momento = (agora or datetime.now(FUSO_PEDIDOS)).astimezone(FUSO_PEDIDOS)
    hora, minuto = (int(parte) for parte in horario.split(":"))
    corte = datetime.combine(momento.date(), time(hora, minuto), tzinfo=FUSO_PEDIDOS)

    if momento >= corte:
        return {
            "horario_bloqueio": horario,
            "bloqueado": True,
            "segundos_ate_bloqueio": None,
            "mensagem": f"A digitação de novos pedidos foi encerrada às {horario}. Ela volta a abrir amanhã, à 00:00.",
        }
    return {
        "horario_bloqueio": horario,
        "bloqueado": False,
        "segundos_ate_bloqueio": int((corte - momento).total_seconds()),
        "mensagem": f"Novos pedidos podem ser enviados até as {horario} de hoje.",
    }
