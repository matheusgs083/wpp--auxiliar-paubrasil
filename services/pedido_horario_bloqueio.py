"""Horário em que a digitação de novos pedidos pelo painel é encerrada.

O gerencial define um horário (HH:MM, hora de Patos). A partir dele, vendedores
não enviam novos pedidos até a virada do dia; à 00:00 a digitação volta a abrir.
Horário vazio significa sem bloqueio.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
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


def normalizar_horario_abertura(valor: Any) -> str:
    texto = str(valor or "").strip()
    if not texto:
        return ""
    if len(texto) == 4 and texto[1] == ":":
        texto = f"0{texto}"
    if not _FORMATO_HORARIO.fullmatch(texto):
        raise ValueError("Informe o horário de abertura no formato HH:MM.")
    return texto


def validar_janela(horario_abertura: str, horario_bloqueio: str) -> tuple[str, str]:
    abertura = normalizar_horario_abertura(horario_abertura)
    fechamento = normalizar_horario_bloqueio(horario_bloqueio)
    if abertura and fechamento and abertura >= fechamento:
        raise ValueError("O horário de abertura deve ser anterior ao horário de bloqueio.")
    return abertura, fechamento


def situacao_bloqueio(horario_bloqueio: str, agora: datetime | None = None, *, horario_abertura: str = "") -> dict[str, Any]:
    """Diz se a digitação está encerrada agora e quanto falta para encerrar."""
    abertura, horario = validar_janela(horario_abertura, horario_bloqueio)
    if not horario and not abertura:
        return {"horario_abertura": "", "horario_bloqueio": "", "bloqueado": False, "segundos_ate_bloqueio": None, "segundos_ate_alteracao": None, "mensagem": ""}

    momento = (agora or datetime.now(FUSO_PEDIDOS)).astimezone(FUSO_PEDIDOS)
    hora_abre, minuto_abre = (int(parte) for parte in (abertura or "00:00").split(":"))
    abre = datetime.combine(momento.date(), time(hora_abre, minuto_abre), tzinfo=FUSO_PEDIDOS)
    corte = datetime.combine(momento.date(), time(*map(int, horario.split(":"))), tzinfo=FUSO_PEDIDOS) if horario else None

    if momento < abre:
        return {"horario_abertura": abertura, "horario_bloqueio": horario, "bloqueado": True, "segundos_ate_bloqueio": None, "segundos_ate_alteracao": int((abre - momento).total_seconds()), "mensagem": f"A digitação de novos pedidos abre hoje às {abertura}."}

    if corte is not None and momento >= corte:
        return {
            "horario_bloqueio": horario,
            "horario_abertura": abertura,
            "bloqueado": True,
            "segundos_ate_bloqueio": None,
            "segundos_ate_alteracao": int((abre + timedelta(days=1) - momento).total_seconds()),
            "mensagem": f"A digitação de novos pedidos foi encerrada às {horario}. Ela volta a abrir amanhã, às {abertura or '00:00'}.",
        }
    return {
        "horario_bloqueio": horario,
        "horario_abertura": abertura,
        "bloqueado": False,
        "segundos_ate_bloqueio": int((corte - momento).total_seconds()) if corte else None,
        "segundos_ate_alteracao": int((corte - momento).total_seconds()) if corte else int((datetime.combine(momento.date() + timedelta(days=1), time.min, tzinfo=FUSO_PEDIDOS) - momento).total_seconds()),
        "mensagem": f"Novos pedidos podem ser enviados até as {horario} de hoje." if horario else f"A digitação abre diariamente às {abertura}.",
    }
