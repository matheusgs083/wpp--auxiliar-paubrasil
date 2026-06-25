from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from threading import RLock
from typing import Any, Iterator

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


ADMIN_IMPORT_JOBS_TABLE = "admin_import_jobs"
ACTIVE_JOB_STATUSES = ("queued", "running")
DEFAULT_HISTORY_RETENTION_DAYS = 3


class AdminImportLockBusy(RuntimeError):
    def __init__(self, lock_key: str) -> None:
        super().__init__(f"Operacao administrativa em andamento para {lock_key}.")
        self.lock_key = lock_key


class AdminImportJobService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "").strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._maintenance_lock = RLock()

    def create_job(
        self,
        *,
        job_id: str,
        action: str,
        dataset_name: str,
        dataset_label: str = "",
        lock_keys: list[str] | tuple[str, ...] = (),
        reference_date: date | None = None,
        source_path: str = "",
        file_names: list[str] | tuple[str, ...] = (),
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.{} (
                            job_id,
                            action,
                            dataset_name,
                            dataset_label,
                            lock_keys,
                            status,
                            reference_date,
                            source_path,
                            file_names,
                            created_by,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s)
                        RETURNING *
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                    (
                        job_id,
                        _clean_token(action, max_length=32),
                        _clean_token(dataset_name, max_length=80),
                        str(dataset_label or ""),
                        Jsonb(_clean_lock_keys(lock_keys)),
                        reference_date,
                        str(source_path or ""),
                        Jsonb([str(name or "") for name in file_names if str(name or "").strip()]),
                        str(created_by or ""),
                        Jsonb(metadata or {}),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return _job_row_to_dict(row)

    def start_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.{}
                        SET
                            status = 'running',
                            started_at = COALESCE(started_at, NOW()),
                            updated_at = NOW()
                        WHERE job_id = %s
                        RETURNING *
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                    (job_id,),
                )
                row = cur.fetchone()
            conn.commit()
        return _job_row_to_dict(row) if row else None

    def finish_job(
        self,
        *,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any] | None:
        normalized_status = _clean_token(status, max_length=32) or "failed"
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.{}
                        SET
                            status = %s,
                            result_json = %s,
                            error = %s,
                            finished_at = COALESCE(finished_at, NOW()),
                            updated_at = NOW()
                        WHERE job_id = %s
                        RETURNING *
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                    (normalized_status, Jsonb(result) if result is not None else None, str(error or ""), job_id),
                )
                row = cur.fetchone()
            conn.commit()
        return _job_row_to_dict(row) if row else None

    def find_active_job(self, lock_keys: list[str] | tuple[str, ...]) -> dict[str, Any] | None:
        clean_keys = _clean_lock_keys(lock_keys)
        if not clean_keys:
            return None
        with self._connect() as conn:
            self.ensure_schema(conn)
            self.mark_stale_jobs(conn=conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT *
                        FROM {}.{}
                        WHERE status = ANY(%s)
                          AND EXISTS (
                              SELECT 1
                              FROM jsonb_array_elements_text(lock_keys) AS active_lock(lock_key)
                              WHERE active_lock.lock_key = ANY(%s)
                          )
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                    (list(ACTIVE_JOB_STATUSES), clean_keys),
                )
                row = cur.fetchone()
            conn.commit()
        return _job_row_to_dict(row) if row else None

    def list_recent_jobs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._maintenance_lock:
            with self._connect() as conn:
                self.ensure_schema(conn)
                self.mark_stale_jobs(conn=conn)
                self.prune_old_jobs(conn=conn)
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        sql.SQL(
                            """
                            SELECT *
                            FROM {}.{}
                            ORDER BY created_at DESC
                            LIMIT %s
                            """
                        ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                        (safe_limit,),
                    )
                    rows = cur.fetchall()
                conn.commit()
        return [_job_row_to_dict(row) for row in rows]

    def mark_active_jobs_stale(
        self,
        *,
        reason: str = "Job ficou aberto apos reinicio do bot e foi liberado automaticamente.",
    ) -> int:
        with self._maintenance_lock:
            with self._connect() as conn:
                self.ensure_schema(conn)
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {}.{}
                            SET
                                status = 'stale',
                                error = CASE
                                    WHEN error = '' THEN %s
                                    ELSE error
                                END,
                                finished_at = COALESCE(finished_at, NOW()),
                                updated_at = NOW()
                            WHERE status = ANY(%s)
                            RETURNING job_id
                            """
                        ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                        (str(reason or ""), list(ACTIVE_JOB_STATUSES)),
                    )
                    rows = cur.fetchall()
                conn.commit()
        return len(rows)

    def mark_stale_jobs(self, *, conn: psycopg.Connection[Any] | None = None, stale_after_minutes: int = 360) -> int:
        with self._maintenance_lock:
            close_conn = conn is None
            active_conn = conn or self._connect()
            try:
                self.ensure_schema(active_conn)
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(int(stale_after_minutes), 30))
                with active_conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {}.{}
                            SET
                                status = 'stale',
                                error = CASE
                                    WHEN error = '' THEN 'Job ficou aberto por tempo excessivo e foi marcado como antigo.'
                                    ELSE error
                                END,
                                finished_at = COALESCE(finished_at, NOW()),
                                updated_at = NOW()
                            WHERE status = ANY(%s)
                              AND updated_at < %s
                            RETURNING job_id
                            """
                        ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                        (list(ACTIVE_JOB_STATUSES), cutoff),
                    )
                    rows = cur.fetchall()
                if close_conn:
                    active_conn.commit()
                return len(rows)
            finally:
                if close_conn:
                    active_conn.close()

    def prune_old_jobs(
        self,
        *,
        conn: psycopg.Connection[Any] | None = None,
        keep_days: int = DEFAULT_HISTORY_RETENTION_DAYS,
    ) -> int:
        with self._maintenance_lock:
            close_conn = conn is None
            active_conn = conn or self._connect()
            try:
                self.ensure_schema(active_conn)
                cutoff = datetime.now(timezone.utc) - timedelta(days=max(int(keep_days), 1))
                with active_conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        sql.SQL(
                            """
                            DELETE FROM {}.{}
                            WHERE status <> ALL(%s)
                              AND COALESCE(finished_at, updated_at, created_at) < %s
                            RETURNING job_id
                            """
                        ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE)),
                        (list(ACTIVE_JOB_STATUSES), cutoff),
                    )
                    rows = cur.fetchall()
                if close_conn:
                    active_conn.commit()
                return len(rows)
            finally:
                if close_conn:
                    active_conn.close()

    @contextmanager
    def operation_lock(self, lock_keys: list[str] | tuple[str, ...]) -> Iterator[list[str]]:
        clean_keys = _clean_lock_keys(lock_keys)
        if not clean_keys:
            yield []
            return

        conn = self._connect()
        acquired: list[str] = []
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                for lock_key in clean_keys:
                    cur.execute("SELECT pg_try_advisory_lock(%s)", (_advisory_lock_id(lock_key),))
                    row = cur.fetchone()
                    if not row or not bool(row[0]):
                        raise AdminImportLockBusy(lock_key)
                    acquired.append(lock_key)
            yield acquired
        finally:
            if acquired:
                with conn.cursor() as cur:
                    for lock_key in reversed(acquired):
                        cur.execute("SELECT pg_advisory_unlock(%s)", (_advisory_lock_id(lock_key),))
            conn.close()

    def ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.{} (
                        job_id TEXT PRIMARY KEY,
                        action VARCHAR(32) NOT NULL,
                        dataset_name VARCHAR(80) NOT NULL,
                        dataset_label TEXT NOT NULL DEFAULT '',
                        lock_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
                        status VARCHAR(32) NOT NULL,
                        reference_date DATE,
                        source_path TEXT NOT NULL DEFAULT '',
                        file_names JSONB NOT NULL DEFAULT '[]'::jsonb,
                        created_by TEXT NOT NULL DEFAULT '',
                        metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        result_json JSONB,
                        error TEXT NOT NULL DEFAULT '',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        started_at TIMESTAMPTZ,
                        finished_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS admin_import_jobs_status_idx ON {}.{} (status, updated_at DESC)"
                ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS admin_import_jobs_dataset_idx ON {}.{} (dataset_name, created_at DESC)"
                ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS admin_import_jobs_lock_keys_idx ON {}.{} USING GIN (lock_keys)"
                ).format(sql.Identifier(self.schema), sql.Identifier(ADMIN_IMPORT_JOBS_TABLE))
            )

    def _connect(self) -> psycopg.Connection[Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)


def _advisory_lock_id(lock_key: str) -> int:
    digest = hashlib.sha256(str(lock_key or "").encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _clean_lock_keys(lock_keys: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    clean_keys: list[str] = []
    for item in lock_keys:
        key = str(item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        clean_keys.append(key)
    return clean_keys


def _clean_token(value: str, *, max_length: int) -> str:
    cleaned = "_".join(str(value or "").strip().lower().split())
    if len(cleaned) > max_length:
        return cleaned[:max_length]
    return cleaned


def _normalize_schema(schema: str) -> str:
    cleaned = str(schema or "").strip()
    if not cleaned:
        return "reports"
    return cleaned


def _job_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(row.get("job_id") or ""),
        "action": str(row.get("action") or ""),
        "dataset": str(row.get("dataset_name") or ""),
        "dataset_name": str(row.get("dataset_name") or ""),
        "dataset_label": str(row.get("dataset_label") or ""),
        "lock_keys": list(row.get("lock_keys") or []),
        "status": str(row.get("status") or ""),
        "reference_date": _serialize_value(row.get("reference_date")),
        "source_path": str(row.get("source_path") or ""),
        "file_names": list(row.get("file_names") or []),
        "created_by": str(row.get("created_by") or ""),
        "metadata": dict(row.get("metadata") or {}),
        "result": row.get("result_json"),
        "error": str(row.get("error") or ""),
        "created_at": _serialize_value(row.get("created_at")),
        "started_at": _serialize_value(row.get("started_at")),
        "finished_at": _serialize_value(row.get("finished_at")),
        "updated_at": _serialize_value(row.get("updated_at")),
    }


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
