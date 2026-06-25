from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from threading import Thread
from typing import Any
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from bot_api.commercial_scope import normalize_numeric_code, normalize_stored_scope_value, split_scope_pair
from bot_api.models import IncomingMessage

settings: Any = None
PROJECT_ROOT: Path | None = None
access_control: Any = None
evolution_client: Any = None
lookup_flow: Any = None
logger: Any = None
_access_call: Any = None
ADMIN_BROADCAST_ACTIONS: dict[str, dict[str, Any]] = {}
ADMIN_BROADCAST_DAY_OPTIONS: dict[str, dict[str, str]] = {}
ADMIN_BROADCAST_TARGET_MODES: dict[str, dict[str, str]] = {}
ADMIN_BROADCAST_AUDIENCES: dict[str, dict[str, str]] = {}
ADMIN_BROADCAST_SEND_DELAY_SECONDS = 1.0
admin_broadcast_executor: Any = None
admin_broadcast_lock: Any = None
admin_broadcast_state: dict[str, Any] = {}
daily_route_broadcast_lock: Any = None
daily_route_broadcast_stop_event: Any = None
daily_route_broadcast_status: dict[str, Any] = {}
daily_route_broadcast_thread: Thread | None = None


def configure(**deps: Any) -> None:
    globals().update(deps)

def _normalize_admin_broadcast_filial(value: Any) -> str:
    normalized = normalize_numeric_code(str(value or ""))
    if not normalized:
        raise HTTPException(status_code=400, detail="Informe uma filial valida para o disparo.")
    return normalized


def _panel_context_allowed_broadcast_filiais(context: dict[str, Any] | None) -> set[str] | None:
    if not context or bool(context.get("is_admin")):
        return None
    allowed: set[str] = set()
    for filial in context.get("filiais", ()) or ():
        normalized = normalize_numeric_code(str(filial or ""))
        if normalized:
            allowed.add(normalized)
    return allowed


def _require_panel_context_broadcast_filial(context: dict[str, Any] | None, filial: Any) -> str:
    normalized_filial = _normalize_admin_broadcast_filial(filial)
    allowed_filiais = _panel_context_allowed_broadcast_filiais(context)
    if allowed_filiais is not None and normalized_filial not in allowed_filiais:
        raise HTTPException(status_code=403, detail="Filial fora do escopo liberado para este financeiro.")
    return normalized_filial


def _normalize_admin_broadcast_text(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(ascii_only.replace("_", " ").replace("-", " ").split())


def _normalize_admin_broadcast_action(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in ADMIN_BROADCAST_ACTIONS:
        allowed = ", ".join(sorted(ADMIN_BROADCAST_ACTIONS))
        raise HTTPException(status_code=400, detail=f"Acao de disparo invalida. Use {allowed}.")
    return normalized


def _normalize_admin_broadcast_day(value: Any) -> str:
    normalized = _normalize_admin_broadcast_text(value) or "hoje"
    aliases = {
        "seg": "segunda",
        "segunda feira": "segunda",
        "ter": "terca",
        "terca feira": "terca",
        "qua": "quarta",
        "quarta feira": "quarta",
        "qui": "quinta",
        "quinta feira": "quinta",
        "sex": "sexta",
        "sexta feira": "sexta",
        "sab": "sabado",
        "dom": "domingo",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ADMIN_BROADCAST_DAY_OPTIONS:
        allowed = ", ".join(item["label"] for item in ADMIN_BROADCAST_DAY_OPTIONS.values())
        raise HTTPException(status_code=400, detail=f"Dia de disparo invalido. Use {allowed}.")
    return normalized


def _normalize_admin_broadcast_target_mode(value: Any) -> str:
    normalized = _normalize_admin_broadcast_text(value) or "filial"
    aliases = {
        "todos": "filial",
        "todos da filial": "filial",
        "filial": "filial",
        "numero": "specific",
        "numero especifico": "specific",
        "specific": "specific",
        "teste": "specific",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ADMIN_BROADCAST_TARGET_MODES:
        raise HTTPException(status_code=400, detail="Destino invalido para o disparo.")
    return normalized


def _normalize_admin_broadcast_audience(value: Any) -> str:
    normalized = _normalize_admin_broadcast_text(value) or "vendedor"
    aliases = {
        "rn": "vendedor",
        "rns": "vendedor",
        "vendedor": "vendedor",
        "vendedores": "vendedor",
        "gerente": "gerente_vendas",
        "gerentes": "gerente_vendas",
        "gerente vendas": "gerente_vendas",
        "gerente de vendas": "gerente_vendas",
        "gerentes de vendas": "gerente_vendas",
        "gerente_vendas": "gerente_vendas",
        "gv": "gerente_vendas",
        "gvs": "gerente_vendas",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ADMIN_BROADCAST_AUDIENCES:
        raise HTTPException(status_code=400, detail="Perfil de disparo invalido. Use vendedores ou GVs.")
    return normalized


def _build_admin_broadcast_shortcut(action: str, day: str) -> str:
    action_data = ADMIN_BROADCAST_ACTIONS[action]
    if bool(action_data.get("supports_day")):
        day_token = ADMIN_BROADCAST_DAY_OPTIONS[day]["token"]
        return str(action_data.get("shortcut_template") or action_data["shortcut"]).format(day=day_token)
    return str(action_data["shortcut"])


def _admin_broadcast_action_allowed_for_audience(action: str, audience: str) -> bool:
    action_data = ADMIN_BROADCAST_ACTIONS[action]
    allowed_audiences = action_data.get("target_audiences")
    if not allowed_audiences:
        return True
    return str(audience or "").strip() in {str(item or "").strip() for item in allowed_audiences}


def _scope_filial(value: Any) -> str:
    pair = split_scope_pair(str(value or ""))
    return pair[0] if pair else ""


def _scope_setor(value: Any) -> str:
    pair = split_scope_pair(str(value or ""))
    return pair[1] if pair else ""


def _admin_broadcast_scope_sort_key(value: Any) -> tuple[int, int, str]:
    pair = split_scope_pair(str(value or ""))
    if pair:
        filial, setor = pair
        filial_number = int(filial) if filial.isdigit() else 999999
        setor_number = int(setor) if setor.isdigit() else 999999
        return filial_number, setor_number, str(value or "")
    return 999999, 999999, str(value or "")


def _user_broadcast_filiais(user: dict[str, Any], audience: str | None = None) -> set[str]:
    roles = {str(role or "").strip().lower() for role in user.get("roles") or []}
    filiais: set[str] = set()
    if (audience in {None, "vendedor"}) and "vendedor" in roles:
        for sector in user.get("sectors") or []:
            filial = _scope_filial(sector)
            if filial:
                filiais.add(filial)
    if (audience in {None, "gerente_vendas"}) and "gerente_vendas" in roles:
        for gv_vde in user.get("gv_vdes") or []:
            raw = str(gv_vde or "").strip().lower()
            if raw.startswith("dc:"):
                continue
            filial = _scope_filial(raw)
            if filial:
                filiais.add(filial)
    return filiais


def _recipient_broadcast_sector_scopes(recipient: dict[str, Any], filial: str) -> list[str]:
    normalized_filial = _normalize_admin_broadcast_filial(filial)
    scopes: list[str] = []
    seen: set[str] = set()
    for sector in recipient.get("sectors") or []:
        raw_scope = normalize_stored_scope_value(str(sector or ""))
        if not raw_scope or _scope_filial(raw_scope) != normalized_filial:
            continue
        setor = _scope_setor(raw_scope)
        if not setor:
            continue
        scope = f"{normalized_filial}_{setor}"
        if scope in seen:
            continue
        seen.add(scope)
        scopes.append(scope)
    scopes.sort(key=_admin_broadcast_scope_sort_key)
    return scopes


def _build_admin_broadcast_recipient_shortcut(
    *,
    action: str,
    day: str,
    filial: str,
    recipient: dict[str, Any],
    default_shortcut: str,
) -> str:
    action_data = ADMIN_BROADCAST_ACTIONS[action]
    if action_data.get("per_recipient_shortcut") != "critica_sector_pdf":
        return default_shortcut
    scopes = _recipient_broadcast_sector_scopes(recipient, filial)
    if len(scopes) == 1:
        filial_code, setor_code = split_scope_pair(scopes[0]) or (filial, "")
        return f"critica pdf setor {filial_code}/{setor_code}"
    if len(scopes) > 1:
        return "critica pdf"
    raise HTTPException(status_code=400, detail="Vendedor sem setor cadastrado para a operacao escolhida.")


def _is_admin_broadcast_user(user: dict[str, Any]) -> bool:
    if user.get("is_active") is False:
        return False
    roles = {str(role or "").strip().lower() for role in user.get("roles") or []}
    return bool(roles & {"vendedor", "gerente_vendas"})


def _user_matches_admin_broadcast_audience(user: dict[str, Any], audience: str) -> bool:
    roles = {str(role or "").strip().lower() for role in user.get("roles") or []}
    return str(ADMIN_BROADCAST_AUDIENCES[audience]["role"]) in roles


def _admin_broadcast_user_label(user: dict[str, Any]) -> str:
    name = str(user.get("name") or "").strip()
    phone_number = str(user.get("phone_number") or "").strip()
    return name or phone_number or "sem_nome"


def _admin_broadcast_user_role_label(user: dict[str, Any]) -> str:
    roles = [str(role or "").strip().lower() for role in user.get("roles") or []]
    if "admin" in roles:
        return "ADMIN"
    if "financeiro" in roles:
        return "FIN"
    if "diretor_comercial" in roles:
        return "DC"
    if "gerente_vendas" in roles:
        return "GV"
    if "vendedor" in roles:
        return "RN"
    return ", ".join(roles) or "-"


def _admin_broadcast_comparable_number(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        return f"{digits[:4]}{digits[5:]}"
    return digits


def _list_admin_broadcast_recipients(filial: str, audience: str) -> list[dict[str, Any]]:
    normalized_filial = _normalize_admin_broadcast_filial(filial)
    normalized_audience = _normalize_admin_broadcast_audience(audience)
    users = _access_call(access_control.list_users)
    recipients: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    for user in users:
        if not isinstance(user, dict) or not _is_admin_broadcast_user(user):
            continue
        if not _user_matches_admin_broadcast_audience(user, normalized_audience):
            continue
        if normalized_filial not in _user_broadcast_filiais(user, normalized_audience):
            continue
        phone_number = str(user.get("phone_number") or "").strip()
        comparable_number = _admin_broadcast_comparable_number(phone_number)
        if not comparable_number or comparable_number in seen_numbers:
            continue
        seen_numbers.add(comparable_number)
        recipients.append(
            {
                "phone_number": phone_number,
                "name": _admin_broadcast_user_label(user),
                "role": _admin_broadcast_user_role_label(user),
                "roles": list(user.get("roles") or []),
                "sectors": list(user.get("sectors") or []),
                "gv_vdes": list(user.get("gv_vdes") or []),
            }
        )
    recipients.sort(key=lambda item: (str(item.get("role") or ""), str(item.get("name") or ""), str(item.get("phone_number") or "")))
    return recipients


def _filter_admin_broadcast_selected_recipients(
    recipients: list[dict[str, Any]],
    selected_numbers: list[str] | tuple[str, ...] | None,
    *,
    require_selection: bool,
) -> list[dict[str, Any]]:
    selected = {
        comparable
        for comparable in (_admin_broadcast_comparable_number(item) for item in selected_numbers or [])
        if comparable
    }
    if require_selection and not selected:
        raise HTTPException(status_code=400, detail="Selecione ao menos um destinatario para o disparo.")
    if not selected:
        return recipients

    filtered = [
        recipient
        for recipient in recipients
        if _admin_broadcast_comparable_number(recipient.get("phone_number")) in selected
    ]
    if require_selection and not filtered:
        raise HTTPException(status_code=400, detail="Nenhum destinatario selecionado continua elegivel para esse disparo.")
    return filtered


def _get_admin_broadcast_specific_recipient(target_number: str) -> list[dict[str, Any]]:
    number = str(target_number or "").strip()
    if not number:
        raise HTTPException(status_code=400, detail="Informe o numero especifico para teste.")
    user = _access_call(access_control.get_user, number)
    if not user:
        raise HTTPException(status_code=404, detail="Numero especifico nao encontrado no RBAC.")
    if user.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Numero especifico esta inativo no RBAC.")
    phone_number = str(user.get("phone_number") or number).strip()
    if not phone_number:
        raise HTTPException(status_code=400, detail="Numero especifico invalido.")
    return [
        {
            "phone_number": phone_number,
            "name": _admin_broadcast_user_label(user),
            "role": _admin_broadcast_user_role_label(user),
            "roles": list(user.get("roles") or []),
            "sectors": list(user.get("sectors") or []),
            "gv_vdes": list(user.get("gv_vdes") or []),
            "test_target": True,
        }
    ]


def _list_admin_broadcast_filiais(context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    allowed_filiais = _panel_context_allowed_broadcast_filiais(context)
    users = _access_call(access_control.list_users)
    stats: dict[str, dict[str, Any]] = {}
    for user in users:
        if not isinstance(user, dict) or not _is_admin_broadcast_user(user):
            continue
        for audience in ADMIN_BROADCAST_AUDIENCES:
            if not _user_matches_admin_broadcast_audience(user, audience):
                continue
            for filial in _user_broadcast_filiais(user, audience):
                if allowed_filiais is not None and filial not in allowed_filiais:
                    continue
                item = stats.setdefault(
                    filial,
                    {"filial": filial, "total": 0, "vendedor": 0, "gerente_vendas": 0},
                )
                item["total"] += 1
                item[audience] += 1
    return sorted(
        stats.values(),
        key=lambda item: int(item["filial"]) if str(item["filial"]).isdigit() else str(item["filial"]),
    )


def _list_admin_broadcast_audiences() -> list[dict[str, str]]:
    return [
        {
            "id": audience_id,
            "label": data["label"],
            "role_label": data["role_label"],
        }
        for audience_id, data in ADMIN_BROADCAST_AUDIENCES.items()
    ]


def _list_admin_broadcast_options(context: dict[str, Any] | None = None) -> dict[str, Any]:
    actions = [
        {
            "id": action_id,
            "label": data["label"],
            "description": data["description"],
            "shortcut": data["shortcut"],
            "supports_day": bool(data.get("supports_day")),
            "target_audiences": list(data.get("target_audiences") or []),
        }
        for action_id, data in ADMIN_BROADCAST_ACTIONS.items()
    ]
    days = [{"id": day_id, **data} for day_id, data in ADMIN_BROADCAST_DAY_OPTIONS.items()]
    target_modes = [{"id": mode_id, **data} for mode_id, data in ADMIN_BROADCAST_TARGET_MODES.items()]
    return {
        "actions": actions,
        "days": days,
        "target_modes": target_modes,
        "target_audiences": _list_admin_broadcast_audiences(),
        "filiais": _list_admin_broadcast_filiais(context),
        "status": _snapshot_admin_broadcast_state(context),
    }


def _snapshot_admin_broadcast_state(context: dict[str, Any] | None = None) -> dict[str, Any]:
    with admin_broadcast_lock:
        payload = {
            "running": bool(admin_broadcast_state["running"]),
            "current_job_id": str(admin_broadcast_state["current_job_id"] or ""),
            "current_filial": str(admin_broadcast_state["current_filial"] or ""),
            "current_action": str(admin_broadcast_state["current_action"] or ""),
            "current_day": str(admin_broadcast_state["current_day"] or ""),
            "current_target_mode": str(admin_broadcast_state["current_target_mode"] or ""),
            "current_target_audience": str(admin_broadcast_state["current_target_audience"] or ""),
            "current_shortcut": str(admin_broadcast_state["current_shortcut"] or ""),
            "started_at": str(admin_broadcast_state["started_at"] or ""),
            "total": int(admin_broadcast_state.get("total") or 0),
            "sent": int(admin_broadcast_state.get("sent") or 0),
            "failed": int(admin_broadcast_state.get("failed") or 0),
            "skipped": int(admin_broadcast_state.get("skipped") or 0),
            "last_job": dict(admin_broadcast_state.get("last_job") or {}),
        }
    allowed_filiais = _panel_context_allowed_broadcast_filiais(context)
    if allowed_filiais is None:
        return payload

    current_filial = str(payload.get("current_filial") or "")
    if current_filial and current_filial not in allowed_filiais:
        payload.update(
            {
                "running": False,
                "current_job_id": "",
                "current_filial": "",
                "current_action": "",
                "current_day": "",
                "current_target_mode": "",
                "current_target_audience": "",
                "current_shortcut": "",
                "started_at": "",
                "total": 0,
                "sent": 0,
                "failed": 0,
                "skipped": 0,
            }
        )

    last_job = payload.get("last_job") or {}
    last_filial = str(last_job.get("filial") or "") if isinstance(last_job, dict) else ""
    if last_filial and last_filial not in allowed_filiais:
        payload["last_job"] = {}
    return payload


def _build_admin_broadcast_payload(
    *,
    filial: str,
    action: str,
    day: str,
    target_mode: str,
    target_audience: str,
    target_number: str = "",
    selected_numbers: list[str] | tuple[str, ...] | None = None,
    require_selection: bool = False,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_filial = _require_panel_context_broadcast_filial(context, filial)
    normalized_action = _normalize_admin_broadcast_action(action)
    normalized_day = _normalize_admin_broadcast_day(day)
    normalized_target_mode = _normalize_admin_broadcast_target_mode(target_mode)
    normalized_target_audience = _normalize_admin_broadcast_audience(target_audience)
    if not _admin_broadcast_action_allowed_for_audience(normalized_action, normalized_target_audience):
        raise HTTPException(status_code=400, detail="Essa mensagem nao esta liberada para o perfil escolhido.")
    recipients = (
        _list_admin_broadcast_recipients(normalized_filial, normalized_target_audience)
        if normalized_target_mode == "filial"
        else _get_admin_broadcast_specific_recipient(target_number)
    )
    if normalized_target_mode == "specific" and _panel_context_allowed_broadcast_filiais(context) is not None:
        recipients = [
            recipient
            for recipient in recipients
            if normalized_filial in _user_broadcast_filiais(recipient, normalized_target_audience)
        ]
        if not recipients:
            raise HTTPException(status_code=403, detail="Numero especifico fora da filial/perfil liberado para este financeiro.")
    recipients = _filter_admin_broadcast_selected_recipients(
        recipients,
        selected_numbers,
        require_selection=require_selection,
    )
    shortcut = _build_admin_broadcast_shortcut(normalized_action, normalized_day)
    for recipient in recipients:
        recipient["shortcut"] = _build_admin_broadcast_recipient_shortcut(
            action=normalized_action,
            day=normalized_day,
            filial=normalized_filial,
            recipient=recipient,
            default_shortcut=shortcut,
        )
    action_data = ADMIN_BROADCAST_ACTIONS[normalized_action]
    if normalized_target_mode == "specific" and recipients:
        decision = access_control.authorize(
            phone_number=str(recipients[0].get("phone_number") or target_number),
            area=str(action_data.get("area") or "cliente"),
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Numero especifico sem permissao para esse disparo: {decision.reason or 'access_denied'}.",
            )
    day_label = ADMIN_BROADCAST_DAY_OPTIONS[normalized_day]["label"] if bool(action_data.get("supports_day")) else "Nao se aplica"
    normalized_target_number = str(recipients[0].get("phone_number") or target_number).strip() if normalized_target_mode == "specific" and recipients else ""
    return {
        "filial": normalized_filial,
        "action": normalized_action,
        "action_label": action_data["label"],
        "day": normalized_day,
        "day_label": day_label,
        "target_mode": normalized_target_mode,
        "target_mode_label": ADMIN_BROADCAST_TARGET_MODES[normalized_target_mode]["label"],
        "target_audience": normalized_target_audience,
        "target_audience_label": ADMIN_BROADCAST_AUDIENCES[normalized_target_audience]["label"],
        "target_number": normalized_target_number,
        "shortcut": shortcut,
        "supports_day": bool(action_data.get("supports_day")),
        "recipients": recipients,
        "total": len(recipients),
    }


def _queue_admin_broadcast(
    filial: str,
    action: str,
    day: str,
    target_mode: str,
    target_audience: str,
    target_number: str = "",
    selected_numbers: list[str] | tuple[str, ...] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _build_admin_broadcast_payload(
        filial=filial,
        action=action,
        day=day,
        target_mode=target_mode,
        target_audience=target_audience,
        target_number=target_number,
        selected_numbers=selected_numbers,
        require_selection=True,
        context=context,
    )
    normalized_filial = payload["filial"]
    normalized_action = payload["action"]
    normalized_day = payload["day"]
    normalized_target_mode = payload["target_mode"]
    normalized_target_audience = payload["target_audience"]
    recipients = payload["recipients"]
    shortcut = payload["shortcut"]
    if not recipients:
        empty_message = ADMIN_BROADCAST_AUDIENCES[normalized_target_audience]["empty_message"]
        raise HTTPException(status_code=400, detail=empty_message)

    job_id = str(uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    with admin_broadcast_lock:
        if admin_broadcast_state["running"]:
            raise HTTPException(status_code=409, detail="Ja existe um disparo em andamento.")
        admin_broadcast_state.update(
            {
                "running": True,
                "current_job_id": job_id,
                "current_filial": normalized_filial,
                "current_action": normalized_action,
                "current_day": normalized_day,
                "current_target_mode": normalized_target_mode,
                "current_target_audience": normalized_target_audience,
                "current_shortcut": shortcut,
                "started_at": started_at,
                "total": len(recipients),
                "sent": 0,
                "failed": 0,
                "skipped": 0,
            }
        )

    try:
        admin_broadcast_executor.submit(
            _admin_broadcast_worker,
            job_id,
            normalized_filial,
            normalized_action,
            normalized_day,
            normalized_target_mode,
            normalized_target_audience,
            shortcut,
            recipients,
        )
    except Exception:
        with admin_broadcast_lock:
            admin_broadcast_state["running"] = False
            admin_broadcast_state["current_job_id"] = ""
            admin_broadcast_state["current_filial"] = ""
            admin_broadcast_state["current_action"] = ""
            admin_broadcast_state["current_day"] = ""
            admin_broadcast_state["current_target_mode"] = ""
            admin_broadcast_state["current_target_audience"] = ""
            admin_broadcast_state["current_shortcut"] = ""
            admin_broadcast_state["started_at"] = ""
        raise

    return {"job_id": job_id, **payload}


def _admin_broadcast_worker(
    job_id: str,
    filial: str,
    action: str,
    day: str,
    target_mode: str,
    target_audience: str,
    shortcut: str,
    recipients: list[dict[str, Any]],
) -> None:
    action_data = ADMIN_BROADCAST_ACTIONS[action]
    area = action_data.get("area") or "cliente"
    results: list[dict[str, Any]] = []
    sent = failed = skipped = 0

    for index, recipient in enumerate(recipients, start=1):
        phone_number = str(recipient.get("phone_number") or "").strip()
        result = {
            "phone_number": phone_number,
            "name": recipient.get("name") or phone_number,
            "role": recipient.get("role") or "",
            "status": "skipped",
            "error": "",
        }
        try:
            recipient_shortcut = str(recipient.get("shortcut") or shortcut or "").strip()
            if not recipient_shortcut:
                skipped += 1
                result["error"] = "shortcut_vazio"
            else:
                decision = access_control.authorize(phone_number=phone_number, area=area)
                if not decision.allowed:
                    skipped += 1
                    result["error"] = decision.reason or "access_denied"
                else:
                    reset_incoming = IncomingMessage(sender=phone_number, text="menu", channel="evolution", message_id=f"admin-broadcast:{job_id}:reset")
                    lookup_flow.handle(incoming=reset_incoming, decision=decision)
                    incoming = IncomingMessage(sender=phone_number, text=recipient_shortcut, channel="evolution", message_id=f"admin-broadcast:{job_id}")
                    outgoing = lookup_flow.handle(incoming=incoming, decision=decision)
                    evolution_client.send(number=phone_number, message=outgoing)
                    sent += 1
                    result["status"] = "sent"
                    result["shortcut"] = recipient_shortcut
        except Exception as exc:
            failed += 1
            result["status"] = "failed"
            result["error"] = str(exc)
            logger.exception("Falha no disparo admin %s para %s: %s", job_id, phone_number, exc)

        results.append(result)
        with admin_broadcast_lock:
            if admin_broadcast_state["current_job_id"] == job_id:
                admin_broadcast_state["sent"] = sent
                admin_broadcast_state["failed"] = failed
                admin_broadcast_state["skipped"] = skipped

        if index < len(recipients) and ADMIN_BROADCAST_SEND_DELAY_SECONDS > 0:
            time.sleep(ADMIN_BROADCAST_SEND_DELAY_SECONDS)

    finished_at = datetime.now(timezone.utc).isoformat()
    with admin_broadcast_lock:
        if admin_broadcast_state["current_job_id"] == job_id:
            admin_broadcast_state["running"] = False
            admin_broadcast_state["current_job_id"] = ""
            admin_broadcast_state["current_filial"] = ""
            admin_broadcast_state["current_action"] = ""
            admin_broadcast_state["current_day"] = ""
            admin_broadcast_state["current_target_mode"] = ""
            admin_broadcast_state["current_target_audience"] = ""
            admin_broadcast_state["current_shortcut"] = ""
            admin_broadcast_state["started_at"] = ""
        admin_broadcast_state["last_job"] = {
            "job_id": job_id,
            "filial": filial,
            "action": action,
            "action_label": action_data["label"],
            "day": day,
            "day_label": ADMIN_BROADCAST_DAY_OPTIONS[day]["label"] if bool(action_data.get("supports_day")) else "Nao se aplica",
            "target_mode": target_mode,
            "target_mode_label": ADMIN_BROADCAST_TARGET_MODES[target_mode]["label"],
            "target_audience": target_audience,
            "target_audience_label": ADMIN_BROADCAST_AUDIENCES[target_audience]["label"],
            "shortcut": shortcut,
            "total": len(recipients),
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "finished_at": finished_at,
            "results": results[-50:],
        }


def _daily_route_state_path() -> Path:
    raw_path = Path(settings.daily_route_broadcast_state_file or "exports/scheduled_messages/daily_route_state.json")
    return raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path


def _load_daily_route_state() -> dict[str, Any]:
    path = _daily_route_state_path()
    if not path.exists():
        return {"runs": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Falha ao ler estado do envio diario de rota: %s", exc)
        return {"runs": {}}
    if not isinstance(payload, dict):
        return {"runs": {}}
    runs = payload.get("runs")
    if not isinstance(runs, dict):
        payload["runs"] = {}
    return payload


def _write_daily_route_state(state: dict[str, Any]) -> None:
    path = _daily_route_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _prune_daily_route_state(state: dict[str, Any], keep_days: int = 45) -> None:
    runs = state.setdefault("runs", {})
    if not isinstance(runs, dict):
        state["runs"] = {}
        return
    keys = sorted(str(key) for key in runs.keys())
    for key in keys[:-max(1, keep_days)]:
        runs.pop(key, None)


def _daily_route_timezone() -> Any:
    timezone_name = settings.daily_route_broadcast_timezone or "America/Fortaleza"
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        logger.warning("Timezone invalido para envio diario de rota: %s", timezone_name)
        return timezone(timedelta(hours=-3), name="America/Fortaleza")


def _daily_route_schedule_time() -> tuple[int, int]:
    raw_value = str(settings.daily_route_broadcast_time or "07:00").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw_value)
    if not match:
        logger.warning("Horario invalido para envio diario de rota: %s. Usando 07:00.", raw_value)
        return 7, 0
    hour = max(0, min(int(match.group(1)), 23))
    minute = max(0, min(int(match.group(2)), 59))
    return hour, minute


def _daily_route_now() -> datetime:
    return datetime.now(_daily_route_timezone())


def _should_run_daily_route_broadcast(now: datetime, state: dict[str, Any]) -> bool:
    if now.weekday() >= 5:
        return False
    hour, minute = _daily_route_schedule_time()
    target_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < target_at:
        return False
    run_date = now.date().isoformat()
    run_payload = (state.get("runs") or {}).get(run_date)
    return not (isinstance(run_payload, dict) and run_payload.get("status") == "completed")


def _daily_route_audiences() -> tuple[str, ...]:
    raw_audiences = settings.daily_route_broadcast_audiences or ("vendedor",)
    normalized: list[str] = []
    seen: set[str] = set()
    for audience in raw_audiences:
        try:
            item = _normalize_admin_broadcast_audience(audience)
        except HTTPException:
            logger.warning("Publico invalido no envio diario de rota: %s", audience)
            continue
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return tuple(normalized or ["vendedor"])


def _list_daily_route_recipients() -> list[dict[str, Any]]:
    audiences = set(_daily_route_audiences())
    users = _access_call(access_control.list_users)
    recipients: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    for user in users:
        if not isinstance(user, dict) or not _is_admin_broadcast_user(user):
            continue
        if not any(_user_matches_admin_broadcast_audience(user, audience) for audience in audiences):
            continue
        phone_number = str(user.get("phone_number") or "").strip()
        comparable_number = _admin_broadcast_comparable_number(phone_number)
        if not comparable_number or comparable_number in seen_numbers:
            continue
        seen_numbers.add(comparable_number)
        recipients.append(
            {
                "phone_number": phone_number,
                "name": _admin_broadcast_user_label(user),
                "role": _admin_broadcast_user_role_label(user),
                "roles": list(user.get("roles") or []),
                "sectors": list(user.get("sectors") or []),
                "gv_vdes": list(user.get("gv_vdes") or []),
            }
        )
    recipients.sort(key=lambda item: (str(item.get("role") or ""), str(item.get("name") or ""), str(item.get("phone_number") or "")))
    return recipients


def _daily_route_run_record(state: dict[str, Any], run_date: str, now: datetime, shortcut: str) -> dict[str, Any]:
    runs = state.setdefault("runs", {})
    if not isinstance(runs, dict):
        state["runs"] = {}
        runs = state["runs"]
    record = runs.setdefault(
        run_date,
        {
            "status": "running",
            "started_at": now.isoformat(),
            "finished_at": "",
            "shortcut": shortcut,
            "audiences": list(_daily_route_audiences()),
            "total": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "sent_numbers": [],
            "failed_numbers": [],
            "skipped_numbers": [],
            "results": [],
        },
    )
    if not isinstance(record, dict):
        record = {}
        runs[run_date] = record
    record["status"] = "running"
    record.setdefault("started_at", now.isoformat())
    record["shortcut"] = shortcut
    record["audiences"] = list(_daily_route_audiences())
    record.setdefault("sent_numbers", [])
    record.setdefault("failed_numbers", [])
    record.setdefault("skipped_numbers", [])
    record.setdefault("results", [])
    return record


def _daily_route_update_status(**updates: Any) -> None:
    with daily_route_broadcast_lock:
        daily_route_broadcast_status.update(updates)


def _daily_route_status_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(record.get("status") or ""),
        "started_at": str(record.get("started_at") or ""),
        "finished_at": str(record.get("finished_at") or ""),
        "shortcut": str(record.get("shortcut") or ""),
        "audiences": list(record.get("audiences") or []),
        "total": int(record.get("total") or 0),
        "sent": int(record.get("sent") or 0),
        "failed": int(record.get("failed") or 0),
        "skipped": int(record.get("skipped") or 0),
    }


def _run_daily_route_broadcast_if_due() -> bool:
    if not settings.daily_route_broadcast_enabled:
        return False
    if not evolution_client.enabled:
        _daily_route_update_status(last_error="Evolution nao configurada para envio.")
        return False

    now = _daily_route_now()
    state = _load_daily_route_state()
    _daily_route_update_status(last_checked_at=now.isoformat())
    if not _should_run_daily_route_broadcast(now, state):
        run_date = now.date().isoformat()
        run_payload = (state.get("runs") or {}).get(run_date)
        if isinstance(run_payload, dict):
            _daily_route_update_status(last_run_date=run_date, last_run=_daily_route_status_summary(run_payload))
        return False

    if not daily_route_broadcast_lock.acquire(blocking=False):
        return False
    try:
        daily_route_broadcast_status["running"] = True
        daily_route_broadcast_status["last_error"] = ""
        run_date = now.date().isoformat()
        shortcut = _build_admin_broadcast_shortcut("rota_dia", "hoje")
        recipients = _list_daily_route_recipients()
        state = _load_daily_route_state()
        record = _daily_route_run_record(state, run_date, now, shortcut)
        record["total"] = len(recipients)
        _prune_daily_route_state(state)
        _write_daily_route_state(state)

        sent_numbers = {str(item) for item in record.get("sent_numbers") or [] if str(item).strip()}
        skipped_numbers = {str(item) for item in record.get("skipped_numbers") or [] if str(item).strip()}
        failed_numbers: set[str] = set()
        sent = len(sent_numbers)
        skipped = len(skipped_numbers)
        failed = 0
        results = list(record.get("results") or [])

        for index, recipient in enumerate(recipients, start=1):
            phone_number = str(recipient.get("phone_number") or "").strip()
            comparable_number = _admin_broadcast_comparable_number(phone_number)
            if not comparable_number or comparable_number in sent_numbers or comparable_number in skipped_numbers:
                continue
            result = {
                "phone_number": phone_number,
                "name": recipient.get("name") or phone_number,
                "role": recipient.get("role") or "",
                "status": "skipped",
                "error": "",
            }
            try:
                decision = access_control.authorize(phone_number=phone_number, area="cliente")
                if not decision.allowed:
                    skipped_numbers.add(comparable_number)
                    skipped += 1
                    result["error"] = decision.reason or "access_denied"
                else:
                    reset_incoming = IncomingMessage(
                        sender=phone_number,
                        text="menu",
                        channel="evolution",
                        message_id=f"daily-route:{run_date}:{comparable_number}:reset",
                    )
                    lookup_flow.handle(incoming=reset_incoming, decision=decision)
                    incoming = IncomingMessage(
                        sender=phone_number,
                        text=shortcut,
                        channel="evolution",
                        message_id=f"daily-route:{run_date}:{comparable_number}",
                    )
                    outgoing = lookup_flow.handle(incoming=incoming, decision=decision)
                    evolution_client.send(number=phone_number, message=outgoing)
                    sent_numbers.add(comparable_number)
                    sent += 1
                    result["status"] = "sent"
                result["error"] = str(result.get("error") or "")
            except Exception as exc:
                failed_numbers.add(comparable_number)
                failed += 1
                result["status"] = "failed"
                result["error"] = str(exc)
                logger.exception("Falha no envio diario da rota para %s: %s", phone_number, exc)

            results.append(result)
            record.update(
                {
                    "status": "running",
                    "sent": sent,
                    "failed": failed,
                    "skipped": skipped,
                    "sent_numbers": sorted(sent_numbers),
                    "failed_numbers": sorted(failed_numbers),
                    "skipped_numbers": sorted(skipped_numbers),
                    "results": results[-100:],
                }
            )
            _write_daily_route_state(state)
            _daily_route_update_status(last_run_date=run_date, last_run=_daily_route_status_summary(record))

            if index < len(recipients) and ADMIN_BROADCAST_SEND_DELAY_SECONDS > 0:
                time.sleep(ADMIN_BROADCAST_SEND_DELAY_SECONDS)

        finished_at = _daily_route_now().isoformat()
        record.update(
            {
                "status": "completed",
                "finished_at": finished_at,
                "sent": sent,
                "failed": failed,
                "skipped": skipped,
                "sent_numbers": sorted(sent_numbers),
                "failed_numbers": sorted(failed_numbers),
                "skipped_numbers": sorted(skipped_numbers),
                "results": results[-100:],
            }
        )
        _write_daily_route_state(state)
        _daily_route_update_status(
            running=False,
            last_run_date=run_date,
            last_run=_daily_route_status_summary(record),
            last_error="",
        )
        logger.info(
            "Envio diario da rota concluido: data=%s total=%s enviados=%s falhas=%s ignorados=%s",
            run_date,
            len(recipients),
            sent,
            failed,
            skipped,
        )
        return True
    except Exception as exc:
        _daily_route_update_status(running=False, last_error=str(exc))
        logger.exception("Falha no agendamento diario da rota: %s", exc)
        return False
    finally:
        daily_route_broadcast_status["running"] = False
        daily_route_broadcast_lock.release()


def _daily_route_broadcast_loop() -> None:
    initial_delay = settings.daily_route_broadcast_initial_delay_seconds
    if initial_delay and daily_route_broadcast_stop_event.wait(initial_delay):
        return
    while not daily_route_broadcast_stop_event.is_set():
        _run_daily_route_broadcast_if_due()
        interval = settings.daily_route_broadcast_check_interval_seconds
        if daily_route_broadcast_stop_event.wait(interval):
            return


def _start_daily_route_broadcast_scheduler() -> None:
    global daily_route_broadcast_thread
    if not settings.daily_route_broadcast_enabled:
        logger.info("Envio diario da rota desabilitado.")
        return
    if daily_route_broadcast_thread and daily_route_broadcast_thread.is_alive():
        return
    daily_route_broadcast_stop_event.clear()
    daily_route_broadcast_thread = Thread(
        target=_daily_route_broadcast_loop,
        name="daily-route-broadcast",
        daemon=True,
    )
    daily_route_broadcast_thread.start()
    logger.info(
        "Envio diario da rota agendado para %s (%s).",
        settings.daily_route_broadcast_time,
        settings.daily_route_broadcast_timezone,
    )


def _stop_daily_route_broadcast_scheduler() -> None:
    daily_route_broadcast_stop_event.set()
    thread = daily_route_broadcast_thread
    if thread and thread.is_alive():
        thread.join(timeout=5)


