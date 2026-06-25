from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import csv
import io
import re
from typing import Any
import unicodedata
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from fastapi import HTTPException

from bot_api.services import admin_imports_runtime

settings: Any = None
security_monitor: Any = None


def configure(**deps: Any) -> None:
    globals().update(deps)


_serialize_admin_import_value = admin_imports_runtime._serialize_admin_import_value

def _to_positive_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _parse_usage_date(value: Any, *, field_name: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} deve estar no formato YYYY-MM-DD.") from exc


def _resolve_usage_function_window(
    *,
    days: int,
    date_from: Any = None,
    date_to: Any = None,
) -> tuple[datetime, datetime, date, date]:
    local_tz = ZoneInfo("America/Fortaleza")
    today = datetime.now(local_tz).date()
    start_date = _parse_usage_date(date_from, field_name="date_from")
    end_date = _parse_usage_date(date_to, field_name="date_to")
    if start_date is None and end_date is None:
        end_date = today
        start_date = today - timedelta(days=max(1, days) - 1)
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date
    if start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="Informe um periodo valido.")
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="date_from nao pode ser maior que date_to.")
    if (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Periodo maximo para funcoes e de 366 dias.")
    start_at = datetime.combine(start_date, datetime.min.time(), tzinfo=local_tz)
    end_at = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=local_tz)
    return start_at, end_at, start_date, end_date


EVOLUTION_USAGE_FEATURE_LABELS: dict[str, str] = {
    "cliente": "Clientes",
    "inadimplencia": "Inadimplencia",
    "comodato": "Comodatos",
    "giro": "Giro",
    "documentacao": "Documentacao",
    "prazo_limite": "Prazo e Limite",
    "critica": "Critica",
    "recolha": "Recolhas",
    "payip": "PayIP",
    "visitas": "Visitas",
    "admin_access": "Acessos",
}


def _normalize_usage_tracking_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    return " ".join(text.split())


def _normalize_usage_tracking_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) in {10, 11} and not digits.startswith("55"):
        digits = f"55{digits}"
    if digits.startswith("55") and len(digits) == 13 and digits[4:5] == "9":
        digits = digits[:4] + digits[5:]
    return digits


def _snapshot_lookup_flow_session(session: Any) -> dict[str, str]:
    if session is None:
        return {}
    return {
        "step": str(getattr(session, "step", "") or "").strip(),
        "search_context": str(getattr(session, "search_context", "") or "").strip(),
        "last_intent": str(getattr(session, "last_intent", "") or "").strip(),
        "last_search_context": str(getattr(session, "last_search_context", "") or "").strip(),
        "payip_pending_action": str(getattr(session, "payip_pending_action", "") or "").strip(),
    }


def _infer_usage_feature_from_intent(intent: str) -> str | None:
    normalized_intent = str(intent or "").strip().lower()
    if not normalized_intent:
        return None
    if normalized_intent.startswith(("search_cliente", "cliente_", "client_")):
        return "cliente"
    if normalized_intent.startswith(("search_inadimplencia", "inadimplencia_", "finance_", "manager_", "director_", "seller_")):
        return "inadimplencia"
    if normalized_intent.startswith(("search_comodato", "comodato_")):
        return "comodato"
    if normalized_intent.startswith(("search_giro", "giro_")):
        return "giro"
    if normalized_intent.startswith(("search_documentacao", "documentacao_")):
        return "documentacao"
    if normalized_intent.startswith(("search_prazo_limite", "prazo_limite_")):
        return "prazo_limite"
    if normalized_intent.startswith("visit_"):
        return "visitas"
    if normalized_intent.startswith("admin:"):
        return "admin_access"
    return None


def _infer_usage_feature_from_context(search_context: str) -> str | None:
    normalized_context = str(search_context or "").strip().lower()
    if normalized_context in {"cliente", "inadimplencia", "comodato", "giro", "documentacao", "prazo_limite"}:
        return normalized_context
    return None


def _infer_evolution_usage_feature(
    *,
    incoming_text: str,
    requested_area: str,
    session_before: dict[str, str],
    session_after: dict[str, str],
) -> tuple[str | None, str]:
    normalized_text = _normalize_usage_tracking_text(incoming_text)
    combined_steps = " ".join(
        part for part in (
            session_before.get("step", ""),
            session_after.get("step", ""),
        ) if part
    ).lower()
    combined_intents = " ".join(
        part for part in (
            session_after.get("last_intent", ""),
            session_before.get("last_intent", ""),
        ) if part
    ).lower()
    combined_contexts = (
        session_after.get("last_search_context")
        or session_after.get("search_context")
        or session_before.get("last_search_context")
        or session_before.get("search_context")
        or ""
    ).lower()

    feature_code: str | None = None
    if "critica" in normalized_text or "critica" in combined_steps or "critica" in combined_intents:
        feature_code = "critica"
    elif "recolh" in normalized_text or "recolha" in combined_steps or "recolha" in combined_intents:
        feature_code = "recolha"
    elif (
        "payip" in normalized_text
        or normalized_text.startswith("pix ")
        or session_before.get("payip_pending_action")
        or session_after.get("payip_pending_action")
    ):
        feature_code = "payip"
    else:
        feature_code = _infer_usage_feature_from_intent(combined_intents)
        if feature_code is None:
            feature_code = _infer_usage_feature_from_context(combined_contexts)
        if feature_code is None and requested_area in EVOLUTION_USAGE_FEATURE_LABELS:
            feature_code = requested_area

    detail_parts = []
    if session_after.get("last_intent"):
        detail_parts.append(f"intent={session_after['last_intent']}")
    elif session_before.get("last_intent"):
        detail_parts.append(f"intent={session_before['last_intent']}")
    if combined_contexts:
        detail_parts.append(f"contexto={combined_contexts}")
    if session_after.get("step"):
        detail_parts.append(f"etapa={session_after['step']}")
    elif session_before.get("step"):
        detail_parts.append(f"etapa={session_before['step']}")
    return feature_code, ";".join(detail_parts[:3])


def _list_admin_evolution_usage(
    *,
    days: int = 7,
    top_limit: int = 10,
    recent_limit: int = 20,
    function_date_from: Any = None,
    function_date_to: Any = None,
) -> dict[str, Any]:
    safe_days = _to_positive_int(days, default=7, minimum=1, maximum=30)
    safe_top_limit = _to_positive_int(top_limit, default=10, minimum=1, maximum=5000)
    safe_recent_limit = _to_positive_int(recent_limit, default=20, minimum=5, maximum=50)
    series_days = max(0, safe_days - 1)
    feature_start_at, feature_end_at, feature_start_date, feature_end_date = _resolve_usage_function_window(
        days=safe_days,
        date_from=function_date_from,
        date_to=function_date_to,
    )

    if not settings.access_database_url.strip():
        raise HTTPException(status_code=503, detail="ACCESS_DATABASE_URL nao configurada para o dashboard de uso.")

    audit_schema = str(settings.access_db_schema or "bot_access").strip() or "bot_access"
    audit_table = sql.Identifier(audit_schema, "security_audit_log")
    users_table = sql.Identifier(audit_schema, "users")

    summary_query = sql.SQL(
        """
        SELECT
            COUNT(*) AS total_events,
            COUNT(*) FILTER (WHERE event_type = 'queue' AND decision = 'accepted') AS total_messages,
            COUNT(DISTINCT phone_number) FILTER (WHERE event_type = 'queue' AND decision = 'accepted') AS unique_numbers,
            COUNT(*) FILTER (WHERE event_type = 'processing' AND decision = 'allowed') AS processed_ok,
            COUNT(*) FILTER (WHERE event_type = 'rbac_access' AND decision = 'denied') AS blocked_rbac,
            COUNT(*) FILTER (WHERE event_type = 'processing' AND decision = 'error') AS processing_errors,
            COUNT(*) FILTER (WHERE event_type = 'delivery' AND decision = 'error') AS delivery_errors,
            COUNT(*) FILTER (WHERE event_type = 'queue' AND decision = 'error') AS queue_errors,
            COUNT(*) FILTER (WHERE event_type = 'denied_reply' AND decision = 'sent') AS denied_reply_sent,
            COUNT(*) FILTER (WHERE event_type = 'denied_reply' AND decision = 'suppressed') AS denied_reply_suppressed
        FROM {}
        WHERE channel = 'webhook'
          AND path = '/webhook/evolution'
          AND created_at >= (NOW() - make_interval(days => %s))
        """
    ).format(audit_table)

    daily_query = sql.SQL(
        """
        SELECT
            day::date,
            COUNT(log.id) FILTER (WHERE log.event_type = 'queue' AND log.decision = 'accepted') AS messages,
            COUNT(DISTINCT log.phone_number) FILTER (WHERE log.event_type = 'queue' AND log.decision = 'accepted') AS unique_numbers,
            COUNT(log.id) FILTER (WHERE log.event_type = 'processing' AND log.decision = 'allowed') AS processed_ok,
            COUNT(log.id) FILTER (WHERE log.event_type = 'rbac_access' AND log.decision = 'denied') AS blocked_rbac
        FROM generate_series(
            (CURRENT_DATE - (%s * INTERVAL '1 day'))::date,
            CURRENT_DATE::date,
            INTERVAL '1 day'
        ) AS day
        LEFT JOIN {} AS log
          ON log.created_at >= day::timestamp
         AND log.created_at < (day::timestamp + INTERVAL '1 day')
         AND log.channel = 'webhook'
         AND log.path = '/webhook/evolution'
        GROUP BY day
        ORDER BY day
        """
    ).format(audit_table)

    hourly_query = sql.SQL(
        """
        SELECT
            hour_bucket,
            COUNT(log.id) FILTER (WHERE log.event_type = 'queue' AND log.decision = 'accepted') AS messages
        FROM generate_series(
            date_trunc('hour', NOW()) - INTERVAL '23 hour',
            date_trunc('hour', NOW()),
            INTERVAL '1 hour'
        ) AS hour_bucket
        LEFT JOIN {} AS log
          ON log.created_at >= hour_bucket
         AND log.created_at < (hour_bucket + INTERVAL '1 hour')
         AND log.channel = 'webhook'
         AND log.path = '/webhook/evolution'
        GROUP BY hour_bucket
        ORDER BY hour_bucket
        """
    ).format(audit_table)

    top_numbers_query = sql.SQL(
        """
        WITH ranked_events AS (
            SELECT
                CASE
                    WHEN normalized_candidate = '' THEN 'sem_numero'
                    ELSE normalized_candidate
                END AS normalized_phone,
                MAX(NULLIF(BTRIM(raw_phone), '')) AS sample_phone,
                COUNT(*) AS total_events,
                COUNT(*) FILTER (WHERE event_type = 'queue' AND decision = 'accepted') AS messages,
                COUNT(*) FILTER (WHERE event_type = 'processing' AND decision = 'allowed') AS processed_ok,
                COUNT(*) FILTER (WHERE event_type = 'rbac_access' AND decision = 'denied') AS blocked_rbac
            FROM (
                SELECT
                    log.phone_number AS raw_phone,
                    log.event_type,
                    log.decision,
                    CASE
                        WHEN normalized_base = '' THEN ''
                        WHEN LEFT(normalized_base, 2) = '55'
                         AND LENGTH(normalized_base) = 13
                         AND SUBSTRING(normalized_base, 5, 1) = '9'
                        THEN LEFT(normalized_base, 4) || SUBSTRING(normalized_base, 6)
                        ELSE normalized_base
                    END AS normalized_candidate
                FROM (
                    SELECT
                        phone_number,
                        event_type,
                        decision,
                        CASE
                            WHEN LENGTH(raw_digits) IN (10, 11) AND LEFT(raw_digits, 2) <> '55'
                            THEN '55' || raw_digits
                            ELSE raw_digits
                        END AS normalized_base
                    FROM (
                        SELECT
                            phone_number,
                            event_type,
                            decision,
                            REGEXP_REPLACE(COALESCE(phone_number, ''), '\\D+', '', 'g') AS raw_digits
                        FROM {}
                        WHERE channel = 'webhook'
                          AND path = '/webhook/evolution'
                          AND created_at >= (NOW() - make_interval(days => %s))
                    ) AS base_events
                ) AS log
            ) AS normalized_events
            GROUP BY 1
            HAVING COUNT(*) > 0
            ORDER BY messages DESC, total_events DESC, normalized_phone ASC
            LIMIT %s
        )
        SELECT
            ranked_events.normalized_phone,
            COALESCE(NULLIF(BTRIM(user_name.name), ''), ranked_events.normalized_phone) AS display_name,
            COALESCE(NULLIF(BTRIM(user_name.phone_number), ''), ranked_events.sample_phone, ranked_events.normalized_phone) AS display_phone,
            ranked_events.total_events,
            ranked_events.messages,
            ranked_events.processed_ok,
            ranked_events.blocked_rbac
        FROM ranked_events
        LEFT JOIN LATERAL (
            SELECT usr.name, usr.phone_number
            FROM {} AS usr
            CROSS JOIN LATERAL (
                SELECT REGEXP_REPLACE(COALESCE(usr.phone_number, ''), '\\D+', '', 'g') AS digits
            ) AS digits_src
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN LENGTH(digits_src.digits) IN (10, 11) AND LEFT(digits_src.digits, 2) <> '55'
                    THEN '55' || digits_src.digits
                    ELSE digits_src.digits
                END AS base_phone
            ) AS base_src
            WHERE (
                CASE
                    WHEN LEFT(base_src.base_phone, 2) = '55'
                     AND LENGTH(base_src.base_phone) = 13
                     AND SUBSTRING(base_src.base_phone, 5, 1) = '9'
                    THEN LEFT(base_src.base_phone, 4) || SUBSTRING(base_src.base_phone, 6)
                    ELSE base_src.base_phone
                END
            ) = ranked_events.normalized_phone
            ORDER BY usr.updated_at DESC, usr.id DESC
            LIMIT 1
        ) AS user_name ON TRUE
        ORDER BY ranked_events.messages DESC, ranked_events.total_events DESC, ranked_events.normalized_phone ASC
        """
    ).format(audit_table, users_table)

    breakdown_query = sql.SQL(
        """
        SELECT event_type, decision, COUNT(*) AS total
        FROM {}
        WHERE channel = 'webhook'
          AND path = '/webhook/evolution'
          AND created_at >= (NOW() - make_interval(days => %s))
        GROUP BY event_type, decision
        ORDER BY total DESC, event_type ASC, decision ASC
        LIMIT 30
        """
    ).format(audit_table)

    recent_events_query = sql.SQL(
        """
        SELECT created_at, event_type, decision, phone_number, area, reason
        FROM {}
        WHERE channel = 'webhook'
          AND path = '/webhook/evolution'
        ORDER BY created_at DESC
        LIMIT %s
        """
    ).format(audit_table)

    feature_usage_query = sql.SQL(
        """
        SELECT phone_number, area, COUNT(*) AS total, MAX(created_at) AS last_seen
        FROM {}
        WHERE channel = 'webhook'
          AND path = '/webhook/evolution'
          AND event_type = 'feature_usage'
          AND decision = 'viewed'
          AND created_at >= %s
          AND created_at < %s
          AND COALESCE(area, '') <> ''
        GROUP BY phone_number, area
        ORDER BY COUNT(*) DESC, MAX(created_at) DESC
        """
    ).format(audit_table)

    users_lookup_query = sql.SQL(
        """
        SELECT phone_number, name
        FROM {}
        ORDER BY updated_at DESC, id DESC
        """
    ).format(users_table)

    try:
        with psycopg.connect(
            settings.access_database_url,
            connect_timeout=int(settings.access_database_timeout_seconds),
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(summary_query, (safe_days,))
                summary_row = cur.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

                cur.execute(daily_query, (series_days,))
                daily_rows = cur.fetchall()

                cur.execute(hourly_query)
                hourly_rows = cur.fetchall()

                cur.execute(top_numbers_query, (safe_days, safe_top_limit))
                top_rows = cur.fetchall()

                cur.execute(breakdown_query, (safe_days,))
                breakdown_rows = cur.fetchall()

                cur.execute(recent_events_query, (safe_recent_limit,))
                recent_rows = cur.fetchall()

                cur.execute(feature_usage_query, (feature_start_at, feature_end_at))
                feature_usage_rows = cur.fetchall()

                cur.execute(users_lookup_query)
                users_lookup_rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Falha ao consultar uso do Evolution: {exc}") from exc

    (
        total_events,
        total_messages,
        unique_numbers,
        processed_ok,
        blocked_rbac,
        processing_errors,
        delivery_errors,
        queue_errors,
        denied_reply_sent,
        denied_reply_suppressed,
    ) = summary_row

    summary = {
        "total_events": int(total_events or 0),
        "total_messages": int(total_messages or 0),
        "unique_numbers": int(unique_numbers or 0),
        "processed_ok": int(processed_ok or 0),
        "blocked_rbac": int(blocked_rbac or 0),
        "processing_errors": int(processing_errors or 0),
        "delivery_errors": int(delivery_errors or 0),
        "queue_errors": int(queue_errors or 0),
        "total_errors": int((processing_errors or 0) + (delivery_errors or 0) + (queue_errors or 0)),
        "denied_reply_sent": int(denied_reply_sent or 0),
        "denied_reply_suppressed": int(denied_reply_suppressed or 0),
    }

    daily_messages: list[dict[str, Any]] = []
    for day_value, messages, daily_unique, daily_processed, daily_blocked in daily_rows:
        daily_messages.append(
            {
                "date": _serialize_admin_import_value(day_value),
                "messages": int(messages or 0),
                "unique_numbers": int(daily_unique or 0),
                "processed_ok": int(daily_processed or 0),
                "blocked_rbac": int(daily_blocked or 0),
            }
        )

    hourly_messages: list[dict[str, Any]] = []
    for hour_bucket, messages in hourly_rows:
        hourly_messages.append(
            {
                "hour": _serialize_admin_import_value(hour_bucket),
                "messages": int(messages or 0),
            }
        )

    top_numbers: list[dict[str, Any]] = []
    for (
        normalized_phone,
        display_name,
        display_phone,
        total_number_events,
        messages,
        number_processed,
        number_blocked,
    ) in top_rows:
        normalized_phone_text = str(normalized_phone or "sem_numero")
        display_phone_text = str(display_phone or normalized_phone_text)
        top_numbers.append(
            {
                "phone_number": display_phone_text,
                "normalized_phone": normalized_phone_text,
                "display_name": str(display_name or normalized_phone_text),
                "total_events": int(total_number_events or 0),
                "messages": int(messages or 0),
                "processed_ok": int(number_processed or 0),
                "blocked_rbac": int(number_blocked or 0),
            }
        )

    event_breakdown: list[dict[str, Any]] = []
    for event_type, decision, total in breakdown_rows:
        event_breakdown.append(
            {
                "event_type": str(event_type or ""),
                "decision": str(decision or ""),
                "total": int(total or 0),
            }
        )

    recent_events: list[dict[str, Any]] = []
    for created_at, event_type, decision, phone_number, area, reason in recent_rows:
        recent_events.append(
            {
                "created_at": _serialize_admin_import_value(created_at),
                "event_type": str(event_type or ""),
                "decision": str(decision or ""),
                "phone_number": str(phone_number or ""),
                "area": str(area or ""),
                "reason": str(reason or ""),
            }
        )

    user_names_by_phone: dict[str, dict[str, str]] = {}
    for user_phone, user_name in users_lookup_rows:
        normalized_phone = _normalize_usage_tracking_phone(user_phone)
        if not normalized_phone or normalized_phone in user_names_by_phone:
            continue
        user_names_by_phone[normalized_phone] = {
            "display_name": str(user_name or normalized_phone).strip() or normalized_phone,
            "display_phone": str(user_phone or normalized_phone).strip() or normalized_phone,
        }

    feature_summary_map: dict[str, dict[str, Any]] = {}
    number_function_map: dict[str, dict[str, Any]] = {}
    tracked_total = 0

    for raw_phone, raw_feature_code, raw_total, raw_last_seen in feature_usage_rows:
        feature_code = str(raw_feature_code or "").strip().lower()
        if feature_code not in EVOLUTION_USAGE_FEATURE_LABELS:
            continue
        total = int(raw_total or 0)
        if total <= 0:
            continue
        normalized_phone = _normalize_usage_tracking_phone(raw_phone)
        if not normalized_phone:
            normalized_phone = "sem_numero"
        tracked_total += total

        feature_entry = feature_summary_map.setdefault(
            feature_code,
            {
                "feature_code": feature_code,
                "label": EVOLUTION_USAGE_FEATURE_LABELS[feature_code],
                "total": 0,
                "numbers": set(),
                "last_seen": None,
            },
        )
        feature_entry["total"] += total
        feature_entry["numbers"].add(normalized_phone)
        if raw_last_seen and (feature_entry["last_seen"] is None or raw_last_seen > feature_entry["last_seen"]):
            feature_entry["last_seen"] = raw_last_seen

        user_display = user_names_by_phone.get(
            normalized_phone,
            {
                "display_name": str(raw_phone or normalized_phone).strip() or normalized_phone,
                "display_phone": str(raw_phone or normalized_phone).strip() or normalized_phone,
            },
        )
        number_entry = number_function_map.setdefault(
            normalized_phone,
            {
                "phone_number": user_display["display_phone"],
                "normalized_phone": normalized_phone,
                "display_name": user_display["display_name"],
                "total": 0,
                "last_seen": None,
                "features": {},
            },
        )
        number_entry["total"] += total
        if raw_last_seen and (number_entry["last_seen"] is None or raw_last_seen > number_entry["last_seen"]):
            number_entry["last_seen"] = raw_last_seen
        feature_counter = number_entry["features"].setdefault(
            feature_code,
            {
                "feature_code": feature_code,
                "label": EVOLUTION_USAGE_FEATURE_LABELS[feature_code],
                "total": 0,
            },
        )
        feature_counter["total"] += total

    function_summary = [
        {
            "feature_code": item["feature_code"],
            "label": item["label"],
            "total": int(item["total"]),
            "unique_numbers": len(item["numbers"]),
            "last_seen": _serialize_admin_import_value(item["last_seen"]) if item["last_seen"] else "",
        }
        for item in feature_summary_map.values()
    ]
    function_summary.sort(key=lambda item: (-int(item["total"]), item["label"]))

    number_function_usage: list[dict[str, Any]] = []
    for item in number_function_map.values():
        features = list(item["features"].values())
        features.sort(key=lambda feature: (-int(feature["total"]), feature["label"]))
        top_feature = features[0] if features else None
        number_function_usage.append(
            {
                "phone_number": item["phone_number"],
                "normalized_phone": item["normalized_phone"],
                "display_name": item["display_name"],
                "total": int(item["total"]),
                "unique_functions": len(features),
                "top_feature_code": str(top_feature["feature_code"]) if top_feature else "",
                "top_feature_label": str(top_feature["label"]) if top_feature else "",
                "last_seen": _serialize_admin_import_value(item["last_seen"]) if item["last_seen"] else "",
                "features": [
                    {
                        "feature_code": str(feature["feature_code"]),
                        "label": str(feature["label"]),
                        "total": int(feature["total"]),
                    }
                    for feature in features
                ],
            }
        )
    number_function_usage.sort(key=lambda item: (-int(item["total"]), item["display_name"]))
    number_function_usage = number_function_usage[:safe_top_limit]

    top_feature = function_summary[0] if function_summary else None
    function_usage_summary = {
        "tracked_interactions": tracked_total,
        "tracked_users": len(number_function_map),
        "functions_used": len(function_summary),
        "top_function_label": str(top_feature["label"]) if top_feature else "-",
        "top_function_total": int(top_feature["total"]) if top_feature else 0,
        "date_from": feature_start_date.isoformat(),
        "date_to": feature_end_date.isoformat(),
    }

    return {
        "ok": True,
        "source": "evolution",
        "path": "/webhook/evolution",
        "window_days": safe_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "daily_messages": daily_messages,
        "hourly_messages_24h": hourly_messages,
        "top_numbers": top_numbers,
        "event_breakdown": event_breakdown,
        "recent_events": recent_events,
        "function_usage_summary": function_usage_summary,
        "function_date_from": feature_start_date.isoformat(),
        "function_date_to": feature_end_date.isoformat(),
        "function_summary": function_summary,
        "number_function_usage": number_function_usage,
        "audit_enabled": bool(settings.security_audit_enabled),
        "audit_ready": bool(security_monitor.status().get("ready")),
    }


def _build_evolution_usage_avg_report_csv(payload: dict[str, Any]) -> str:
    window_days = max(1, int(payload.get("window_days") or 1))
    top_numbers = payload.get("top_numbers") if isinstance(payload, dict) else None
    rows = top_numbers if isinstance(top_numbers, list) else []

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["nome", "media_msg_por_dia"])

    for item in rows:
        if not isinstance(item, dict):
            continue
        display_name = str(
            item.get("display_name")
            or item.get("normalized_phone")
            or item.get("phone_number")
            or "sem_nome"
        ).strip()
        messages = int(item.get("messages") or 0)
        average_per_day = messages / window_days
        writer.writerow([display_name, f"{average_per_day:.2f}".replace(".", ",")])

    return "\ufeff" + buffer.getvalue()


def _build_evolution_function_usage_report_csv(payload: dict[str, Any], feature_code: str | None = None) -> str:
    rows = payload.get("number_function_usage") if isinstance(payload, dict) else None
    number_rows = rows if isinstance(rows, list) else []
    selected_feature = str(feature_code or "").strip()

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "nome",
            "numero",
            "funcao",
            "interacoes_funcao",
            "interacoes_usuario",
            "funcoes_usuario",
            "ultima_interacao",
        ]
    )

    for item in number_rows:
        if not isinstance(item, dict):
            continue
        display_name = str(item.get("display_name") or item.get("normalized_phone") or "").strip()
        phone_number = str(item.get("phone_number") or item.get("normalized_phone") or "").strip()
        user_total = int(item.get("total") or 0)
        unique_functions = int(item.get("unique_functions") or 0)
        last_seen = str(item.get("last_seen") or "").strip()
        features = item.get("features") if isinstance(item.get("features"), list) else []
        if selected_feature:
            features = [
                feature
                for feature in features
                if isinstance(feature, dict) and str(feature.get("feature_code") or "").strip() == selected_feature
            ]
        if not features:
            if selected_feature:
                continue
            writer.writerow([display_name, phone_number, "", 0, user_total, unique_functions, last_seen])
            continue
        if selected_feature:
            user_total = sum(int(feature.get("total") or 0) for feature in features if isinstance(feature, dict))
            unique_functions = len(features)
        for feature in features:
            if not isinstance(feature, dict):
                continue
            writer.writerow(
                [
                    display_name,
                    phone_number,
                    str(feature.get("label") or feature.get("feature_code") or "").strip(),
                    int(feature.get("total") or 0),
                    user_total,
                    unique_functions,
                    last_seen,
                ]
            )

    return "\ufeff" + buffer.getvalue()

