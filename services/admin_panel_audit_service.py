from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
import csv
import io
import json
import re
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from psycopg import sql
from psycopg.rows import dict_row

from bot_api.db import get_connection_pool


SENSITIVE_KEY_RE = re.compile(r"(password|senha|token|authorization|api[_-]?key|secret|mfa|totp|cookie)", re.I)
MAX_METADATA_TEXT = 300


class AdminPanelAuditService:
    def __init__(
        self,
        *,
        database_url: str,
        schema: str,
        connect_timeout_seconds: float,
        bootstrap_database_url: str | None = None,
    ) -> None:
        self.database_url = str(database_url or "").strip()
        self.bootstrap_database_url = str(bootstrap_database_url or "").strip() or self.database_url
        self.schema = _clean_identifier(schema, "bot_access")
        self.connect_timeout_seconds = float(connect_timeout_seconds or 3)
        self._pool = None
        self._bootstrap_pool = None

    def ensure_schema(self) -> bool:
        with self._bootstrap_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (self.schema,))
                if cur.fetchone() is None:
                    cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.admin_panel_audit_log (
                            id BIGSERIAL PRIMARY KEY,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            user_id BIGINT,
                            username TEXT NOT NULL DEFAULT '',
                            display_name TEXT NOT NULL DEFAULT '',
                            mode TEXT NOT NULL DEFAULT '',
                            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                            filiais TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                            ip_address TEXT NOT NULL DEFAULT '',
                            user_agent TEXT NOT NULL DEFAULT '',
                            method TEXT NOT NULL DEFAULT '',
                            path TEXT NOT NULL DEFAULT '',
                            module TEXT NOT NULL DEFAULT '',
                            action TEXT NOT NULL DEFAULT '',
                            target_type TEXT NOT NULL DEFAULT '',
                            target_id TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL DEFAULT 'success',
                            metadata JSONB NOT NULL DEFAULT '{{}}'::JSONB
                        )
                        """
                    ).format(sql.Identifier(self.schema))
                )
                for index_name, index_sql in (
                    ("admin_panel_audit_log_created_idx", "created_at DESC"),
                    ("admin_panel_audit_log_username_idx", "username, created_at DESC"),
                    ("admin_panel_audit_log_module_idx", "module, created_at DESC"),
                    ("admin_panel_audit_log_action_idx", "action, created_at DESC"),
                    ("admin_panel_audit_log_status_idx", "status, created_at DESC"),
                ):
                    cur.execute(
                        sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.admin_panel_audit_log ({})").format(
                            sql.Identifier(index_name),
                            sql.Identifier(self.schema),
                            sql.SQL(index_sql),
                        )
                    )
                runtime_user = self._runtime_database_user()
                if runtime_user:
                    cur.execute(
                        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(runtime_user),
                        )
                    )
                    cur.execute(
                        sql.SQL("GRANT SELECT, INSERT ON {}.admin_panel_audit_log TO {}").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(runtime_user),
                        )
                    )
                    cur.execute(
                        sql.SQL("GRANT USAGE, SELECT ON SEQUENCE {}.admin_panel_audit_log_id_seq TO {}").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(runtime_user),
                        )
                    )
            conn.commit()
        return True

    def record(
        self,
        *,
        request: Request,
        context: dict[str, Any] | None,
        module: str,
        action: str,
        target_type: str = "",
        target_id: str = "",
        status: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.database_url:
            return
        clean_context = context or {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.admin_panel_audit_log (
                            user_id, username, display_name, mode, is_admin, filiais,
                            ip_address, user_agent, method, path, module, action,
                            target_type, target_id, status, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::JSONB)
                        """
                    ).format(sql.Identifier(self.schema)),
                    (
                        _safe_int(clean_context.get("user_id")),
                        _limit_text(clean_context.get("username"), 120),
                        _limit_text(clean_context.get("display_name"), 180),
                        _limit_text(clean_context.get("mode"), 80),
                        bool(clean_context.get("is_admin")),
                        _normalize_filiais(clean_context.get("filiais")),
                        _request_ip(request),
                        _limit_text(request.headers.get("user-agent"), 500),
                        _limit_text(request.method, 16),
                        _limit_text(request.url.path, 300),
                        _limit_text(module, 80),
                        _limit_text(action, 120),
                        _limit_text(target_type, 80),
                        _limit_text(target_id, 180),
                        _limit_text(status, 40) or "success",
                        json.dumps(_sanitize_metadata(metadata or {}), ensure_ascii=False),
                    ),
                )
            conn.commit()

    def list_actions(
        self,
        *,
        date_from: Any = None,
        date_to: Any = None,
        username: str | None = None,
        module: str | None = None,
        action: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        start_at, end_at, start_date, end_date = _resolve_window(date_from=date_from, date_to=date_to)
        clean_limit = max(1, min(int(limit or 200), 1000))
        where = [sql.SQL("created_at >= %s"), sql.SQL("created_at < %s")]
        params: list[Any] = [start_at, end_at]
        for column, raw_value in (
            ("username", username),
            ("module", module),
            ("action", action),
            ("status", status),
        ):
            value = str(raw_value or "").strip()
            if value:
                where.append(sql.SQL("{} ILIKE %s").format(sql.Identifier(column)))
                params.append(f"%{value}%")
        where_sql = sql.SQL(" AND ").join(where)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT COUNT(*) AS total
                        FROM {}.admin_panel_audit_log
                        WHERE {}
                        """
                    ).format(sql.Identifier(self.schema), where_sql),
                    params,
                )
                total = int((cur.fetchone() or {}).get("total") or 0)
                cur.execute(
                    sql.SQL(
                        """
                        SELECT id, created_at, username, display_name, mode, is_admin, filiais,
                               ip_address, method, path, module, action, target_type, target_id,
                               status, metadata
                        FROM {}.admin_panel_audit_log
                        WHERE {}
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                        """
                    ).format(sql.Identifier(self.schema), where_sql),
                    [*params, clean_limit],
                )
                rows = [_serialize_row(row) for row in cur.fetchall()]
        return {
            "ok": True,
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
            "total": total,
            "limit": clean_limit,
            "actions": rows,
        }

    def build_csv(self, payload: dict[str, Any]) -> str:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Data", "Usuario", "Nome", "Perfil", "Filiais", "Modulo", "Acao", "Alvo", "Status", "IP", "Caminho"])
        for row in payload.get("actions") or []:
            target = " ".join(part for part in [str(row.get("target_type") or ""), str(row.get("target_id") or "")] if part)
            writer.writerow(
                [
                    row.get("created_at_local") or row.get("created_at") or "",
                    row.get("username") or "",
                    row.get("display_name") or "",
                    row.get("mode") or "",
                    ", ".join(row.get("filiais") or []),
                    row.get("module") or "",
                    row.get("action") or "",
                    target,
                    row.get("status") or "",
                    row.get("ip_address") or "",
                    row.get("path") or "",
                ]
            )
        return "\ufeff" + output.getvalue()

    @contextmanager
    def _connect(self, *, row_factory: Any = None):
        if not self.database_url:
            raise HTTPException(status_code=503, detail="Auditoria do painel nao configurada.")
        if self._pool is None:
            self._pool = get_connection_pool(
                self.database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
                min_size=1,
                max_size=4,
            )
        with self._pool.connection() as conn:
            if row_factory is not None:
                conn.row_factory = row_factory
            yield conn

    @contextmanager
    def _bootstrap_connect(self):
        if not self.bootstrap_database_url:
            raise HTTPException(status_code=503, detail="Auditoria do painel nao configurada.")
        if self._bootstrap_pool is None:
            self._bootstrap_pool = get_connection_pool(
                self.bootstrap_database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
                min_size=1,
                max_size=2,
            )
        with self._bootstrap_pool.connection() as conn:
            yield conn

    def _runtime_database_user(self) -> str | None:
        parsed = urlparse(self.database_url)
        return parsed.username or None


def _clean_identifier(value: str, default: str) -> str:
    raw = str(value or "").strip()
    return raw if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw) else default


def _safe_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed or None


def _limit_text(value: Any, max_len: int) -> str:
    return str(value or "").strip()[:max_len]


def _normalize_filiais(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _request_ip(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:80]
    return str(getattr(request.client, "host", "") or "")[:80]


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if SENSITIVE_KEY_RE.search(text_key):
                clean[text_key] = "[removido]"
            else:
                clean[text_key] = _sanitize_metadata(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [_sanitize_metadata(item) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return value[:MAX_METADATA_TEXT]
        return value
    return str(value)[:MAX_METADATA_TEXT]


def _parse_date(value: Any, *, field_name: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} deve estar no formato YYYY-MM-DD.") from exc


def _resolve_window(*, date_from: Any, date_to: Any) -> tuple[datetime, datetime, date, date]:
    local_tz = ZoneInfo("America/Fortaleza")
    today = datetime.now(local_tz).date()
    start_date = _parse_date(date_from, field_name="date_from")
    end_date = _parse_date(date_to, field_name="date_to")
    if start_date is None and end_date is None:
        end_date = today
        start_date = today - timedelta(days=6)
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date
    if start_date is None or end_date is None:
        raise HTTPException(status_code=400, detail="Informe um periodo valido.")
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="date_from nao pode ser maior que date_to.")
    if (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Periodo maximo de 366 dias.")
    return (
        datetime.combine(start_date, datetime.min.time(), tzinfo=local_tz),
        datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=local_tz),
        start_date,
        end_date,
    )


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    created_at = row.get("created_at")
    local_value = ""
    if isinstance(created_at, datetime):
        local_value = created_at.astimezone(ZoneInfo("America/Fortaleza")).strftime("%d/%m/%Y %H:%M")
        created_value = created_at.isoformat()
    else:
        created_value = str(created_at or "")
    return {
        "id": int(row.get("id") or 0),
        "created_at": created_value,
        "created_at_local": local_value,
        "username": str(row.get("username") or ""),
        "display_name": str(row.get("display_name") or ""),
        "mode": str(row.get("mode") or ""),
        "is_admin": bool(row.get("is_admin")),
        "filiais": list(row.get("filiais") or []),
        "ip_address": str(row.get("ip_address") or ""),
        "method": str(row.get("method") or ""),
        "path": str(row.get("path") or ""),
        "module": str(row.get("module") or ""),
        "action": str(row.get("action") or ""),
        "target_type": str(row.get("target_type") or ""),
        "target_id": str(row.get("target_id") or ""),
        "status": str(row.get("status") or ""),
        "metadata": row.get("metadata") or {},
    }
