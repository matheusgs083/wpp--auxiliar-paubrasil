from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Any


@dataclass(frozen=True)
class SecurityMonitorStatus:
    enabled: bool
    ready: bool
    schema: str
    database_configured: bool
    last_error: str
    connect_timeout_seconds: float
    queued_events: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "ready": self.ready,
            "schema": self.schema,
            "database_configured": self.database_configured,
            "last_error": self.last_error,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "queued_events": self.queued_events,
        }


class SecurityMonitor:
    def __init__(
        self,
        enabled: bool,
        database_url: str,
        schema: str,
        connect_timeout_seconds: float = 3.0,
        default_cooldown_minutes: int = 360,
        unregistered_cooldown_minutes: int = 720,
    ) -> None:
        self.enabled = enabled
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self.default_cooldown = timedelta(minutes=max(int(default_cooldown_minutes), 1))
        self.unregistered_cooldown = timedelta(minutes=max(int(unregistered_cooldown_minutes), 1))
        self._initialized = False
        self._last_error = ""
        self._queue: deque[dict[str, Any]] = deque()
        self._queue_lock = Lock()
        self._queue_signal = Event()
        self._stop_signal = Event()
        self._worker: Thread | None = None
        self._flush_batch_size = 100
        self._flush_interval_seconds = 1.0
        self._max_queue_size = 2000

    def initialize(self) -> bool:
        if not self.enabled:
            self._initialized = True
            self._last_error = ""
            return True
        if not self.database_url:
            self._initialized = False
            self._last_error = "ACCESS_DATABASE_URL nao configurada para auditoria."
            return False
        if self._initialized:
            self._start_worker()
            return True

        try:
            psycopg, _, _ = _psycopg_modules()
            with psycopg.connect(
                self.database_url,
                autocommit=False,
                connect_timeout=int(self.connect_timeout_seconds),
            ) as conn:
                if not self._has_required_tables(conn):
                    self._bootstrap_schema(conn)
                conn.commit()
            self._initialized = True
            self._last_error = ""
            self._start_worker()
            return True
        except Exception as exc:
            self._initialized = False
            self._last_error = _format_bootstrap_error(exc, schema=self.schema, context="Auditoria de seguranca")
            return False

    def shutdown(self) -> None:
        self._stop_signal.set()
        self._queue_signal.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=max(self.connect_timeout_seconds * 2, 5.0))

    def status(self) -> dict[str, Any]:
        ready = self._ensure_ready()
        return SecurityMonitorStatus(
            enabled=self.enabled,
            ready=ready,
            schema=self.schema,
            database_configured=bool(self.database_url),
            last_error=self._last_error,
            connect_timeout_seconds=self.connect_timeout_seconds,
            queued_events=self._queue_size(),
        ).to_dict()

    def record_event(
        self,
        *,
        channel: str,
        path: str,
        event_type: str,
        decision: str,
        phone_number: str | None = None,
        area: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        if not self._ensure_ready():
            return

        event = {
            "channel": str(channel or "").strip() or "unknown",
            "path": str(path or "").strip() or "/",
            "event_type": str(event_type or "").strip() or "unknown",
            "decision": str(decision or "").strip() or "unknown",
            "phone_number": _normalize_number(phone_number or "") or None,
            "area": str(area or "").strip() or None,
            "reason": str(reason or "").strip() or None,
            "metadata": metadata or {},
        }
        with self._queue_lock:
            if len(self._queue) >= self._max_queue_size:
                self._queue.popleft()
                self._last_error = "Fila de auditoria cheia; evento mais antigo descartado."
            self._queue.append(event)
        self._queue_signal.set()

    def should_send_denied_reply(self, number: str, reason: str) -> bool | None:
        if not self.enabled:
            return None
        if not self._ensure_ready():
            return None

        normalized_number = _normalize_number(number)
        if not normalized_number:
            return False

        now = datetime.now(timezone.utc)
        cooldown = self.unregistered_cooldown if reason == "number_not_registered" else self.default_cooldown

        try:
            psycopg, sql, dict_row = _psycopg_modules(with_dict_row=True)
            select_query = sql.SQL(
                """
                SELECT phone_number, last_reply_at
                FROM {}.denied_reply_state
                WHERE phone_number = %s
                FOR UPDATE
                """
            ).format(sql.Identifier(self.schema))
            upsert_query = sql.SQL(
                """
                INSERT INTO {}.denied_reply_state (phone_number, last_reason, last_reply_at, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (phone_number)
                DO UPDATE SET
                    last_reason = EXCLUDED.last_reason,
                    last_reply_at = EXCLUDED.last_reply_at,
                    updated_at = NOW()
                """
            ).format(sql.Identifier(self.schema))

            with psycopg.connect(
                self.database_url,
                autocommit=False,
                connect_timeout=int(self.connect_timeout_seconds),
                row_factory=dict_row,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute(select_query, (normalized_number,))
                    row = cur.fetchone()
                    if row is not None and now - row["last_reply_at"] < cooldown:
                        conn.rollback()
                        return False
                    cur.execute(upsert_query, (normalized_number, str(reason or "").strip() or "unknown", now))
                conn.commit()
            self._last_error = ""
            return True
        except Exception as exc:
            self._initialized = False
            self._last_error = str(exc)
            return None

    def _ensure_ready(self) -> bool:
        if self._initialized:
            self._start_worker()
            return True
        return self.initialize()

    def _start_worker(self) -> None:
        if not self.enabled:
            return
        worker = self._worker
        if worker is not None and worker.is_alive():
            return
        self._stop_signal.clear()
        self._worker = Thread(target=self._worker_loop, name="security-audit-writer", daemon=True)
        self._worker.start()

    def _worker_loop(self) -> None:
        while not self._stop_signal.is_set():
            self._queue_signal.wait(timeout=self._flush_interval_seconds)
            self._queue_signal.clear()
            self._flush_once()

        while self._flush_once():
            pass

    def _flush_once(self) -> bool:
        batch = self._pop_batch()
        if not batch:
            return False

        try:
            psycopg, sql, Jsonb = _psycopg_modules()
            query = sql.SQL(
                """
                INSERT INTO {}.security_audit_log (
                    channel,
                    path,
                    event_type,
                    decision,
                    phone_number,
                    area,
                    reason,
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
            ).format(sql.Identifier(self.schema))
            rows = [
                (
                    event["channel"],
                    event["path"],
                    event["event_type"],
                    event["decision"],
                    event["phone_number"],
                    event["area"],
                    event["reason"],
                    Jsonb(event["metadata"]),
                )
                for event in batch
            ]
            with psycopg.connect(
                self.database_url,
                autocommit=False,
                connect_timeout=int(self.connect_timeout_seconds),
            ) as conn:
                with conn.cursor() as cur:
                    cur.executemany(query, rows)
                conn.commit()
            self._last_error = ""
            return self._queue_size() > 0
        except Exception as exc:
            self._initialized = False
            self._last_error = str(exc)
            self._requeue_batch(batch)
            return False

    def _pop_batch(self) -> list[dict[str, Any]]:
        with self._queue_lock:
            batch: list[dict[str, Any]] = []
            while self._queue and len(batch) < self._flush_batch_size:
                batch.append(self._queue.popleft())
            return batch

    def _requeue_batch(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return
        with self._queue_lock:
            for event in reversed(batch):
                self._queue.appendleft(event)
        self._queue_signal.set()

    def _queue_size(self) -> int:
        with self._queue_lock:
            return len(self._queue)

    def _has_required_tables(self, conn: Any) -> bool:
        required_tables = ("security_audit_log", "denied_reply_state")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (self.schema, list(required_tables)),
            )
            found_tables = {str(row[0]) for row in cur.fetchall()}
        return all(table_name in found_tables for table_name in required_tables)

    def _bootstrap_schema(self, conn: Any) -> None:
        _, sql, _ = _psycopg_modules()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.security_audit_log (
                        id BIGSERIAL PRIMARY KEY,
                        channel VARCHAR(40) NOT NULL,
                        path TEXT NOT NULL,
                        event_type VARCHAR(80) NOT NULL,
                        decision VARCHAR(40) NOT NULL,
                        phone_number VARCHAR(32),
                        area VARCHAR(80),
                        reason VARCHAR(120),
                        metadata JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.denied_reply_state (
                        phone_number VARCHAR(32) PRIMARY KEY,
                        last_reason VARCHAR(120) NOT NULL,
                        last_reply_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS security_audit_log_created_idx ON {}.security_audit_log (created_at DESC)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS security_audit_log_phone_idx ON {}.security_audit_log (phone_number, created_at DESC)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS security_audit_log_path_idx ON {}.security_audit_log (channel, path, created_at DESC)"
                ).format(sql.Identifier(self.schema))
            )


def _normalize_schema(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", str(value or "").strip())
    return cleaned or "bot_access"


def _normalize_number(raw_number: str) -> str:
    digits = re.sub(r"\D+", "", str(raw_number or ""))
    if len(digits) in {10, 11} and not digits.startswith("55"):
        digits = f"55{digits}"
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        return f"{digits[:4]}{digits[5:]}"
    return digits


def _format_bootstrap_error(exc: Exception, *, schema: str, context: str) -> str:
    message = str(exc)
    if "permission denied" in message.lower():
        return (
            f"{context} indisponivel: o usuario atual nao pode criar ou alterar objetos em {schema}. "
            f"Deixe o schema bootstrapado antes do startup. Erro original: {message}"
        )
    return message


def _psycopg_modules(with_dict_row: bool = False) -> tuple[Any, Any, Any]:
    try:
        import psycopg
        from psycopg import sql
        from psycopg.types.json import Jsonb
        if with_dict_row:
            from psycopg.rows import dict_row

            return psycopg, sql, dict_row
        return psycopg, sql, Jsonb
    except ImportError as exc:
        raise RuntimeError("Dependencia psycopg ausente. Rode: pip install -r requirements.txt") from exc
