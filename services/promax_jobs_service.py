from __future__ import annotations

from calendar import monthrange
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from threading import RLock
from typing import Any, Iterator, Literal, Mapping, Sequence, TypedDict, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot_api.db import get_connection_pool
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


DEFAULT_SCHEMA = "promax"
DEFAULT_CONCURRENCY_KEY = "promax"
DEFAULT_TIMEZONE = "America/Fortaleza"

JobStatus = Literal[
    "pending",
    "running",
    "success",
    "partial_success",
    "failed",
    "cancel_requested",
    "cancelled",
]
ScheduleType = Literal["daily", "weekly", "monthly"]

JOB_STATUSES: tuple[JobStatus, ...] = (
    "pending",
    "running",
    "success",
    "partial_success",
    "failed",
    "cancel_requested",
    "cancelled",
)
ACTIVE_JOB_STATUSES: tuple[JobStatus, ...] = ("running", "cancel_requested")
TERMINAL_JOB_STATUSES: tuple[JobStatus, ...] = (
    "success",
    "partial_success",
    "failed",
    "cancelled",
)
WORKER_TERMINAL_STATUSES: tuple[JobStatus, ...] = TERMINAL_JOB_STATUSES
SCHEDULE_TYPES: tuple[ScheduleType, ...] = ("daily", "weekly", "monthly")
LOG_LEVELS = ("debug", "info", "warning", "error")

JOBS_TABLE = "jobs"
JOB_LOGS_TABLE = "job_logs"
SCHEDULES_TABLE = "schedules"
WORKER_HEARTBEATS_TABLE = "worker_heartbeats"
QUEUE_STATE_TABLE = "queue_state"


class JobRecord(TypedDict):
    id: str
    job_type: str
    payload: dict[str, Any]
    status: JobStatus
    priority: int
    concurrency_key: str
    idempotency_key: str | None
    source_schedule_id: str | None
    scheduled_for: str | None
    available_at: str
    attempt_count: int
    lease_token: str | None
    leased_by: str | None
    lease_expires_at: str | None
    heartbeat_at: str | None
    cancel_requested_at: str | None
    cancel_requested_by: str | None
    cancel_reason: str
    result: dict[str, Any] | None
    error: str
    failure_reason: str
    needs_review: bool
    created_by: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str


class JobLogRecord(TypedDict):
    id: int
    job_id: str
    level: str
    message: str
    data: dict[str, Any]
    worker_id: str | None
    lease_token: str | None
    created_at: str


class JobDetails(TypedDict):
    job: JobRecord
    logs: list[JobLogRecord]


class ScheduleRecord(TypedDict):
    id: str
    name: str
    job_type: str
    payload: dict[str, Any]
    schedule_type: ScheduleType
    timezone: str
    time_of_day: str
    weekday: int | None
    day_of_month: int | None
    enabled: bool
    next_run_at: str
    last_enqueued_for: str | None
    created_by: str
    created_at: str
    updated_at: str


class QueueStateRecord(TypedDict):
    paused: bool
    pause_reason: str
    paused_by: str | None
    paused_at: str | None
    revision: int
    updated_at: str


class HeartbeatResult(TypedDict):
    job_id: str
    status: JobStatus
    cancel_requested: bool
    lease_expires_at: str
    heartbeat_at: str


@dataclass(frozen=True)
class ScheduleDefinition:
    schedule_type: ScheduleType
    time_of_day: time
    timezone: str
    weekday: int | None = None
    day_of_month: int | None = None


class LeaseLostError(RuntimeError):
    """Raised when a worker tries to mutate a job without its current lease."""


class _Unset:
    pass


_UNSET = _Unset()


def validate_schedule_definition(
    *,
    schedule_type: str,
    time_of_day: str | time,
    timezone_name: str = DEFAULT_TIMEZONE,
    weekday: int | None = None,
    day_of_month: int | None = None,
) -> ScheduleDefinition:
    normalized_type = str(schedule_type or "").strip().lower()
    if normalized_type not in SCHEDULE_TYPES:
        raise ValueError("schedule_type deve ser daily, weekly ou monthly.")

    parsed_time = _parse_time(time_of_day)
    normalized_timezone = str(timezone_name or "").strip()
    if not normalized_timezone:
        raise ValueError("timezone e obrigatorio.")
    try:
        ZoneInfo(normalized_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Timezone invalido: {normalized_timezone}.") from exc

    if normalized_type == "daily":
        if weekday is not None or day_of_month is not None:
            raise ValueError("Agenda daily nao aceita weekday ou day_of_month.")
    elif normalized_type == "weekly":
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise ValueError("Agenda weekly exige weekday entre 0 (segunda) e 6 (domingo).")
        if day_of_month is not None:
            raise ValueError("Agenda weekly nao aceita day_of_month.")
    else:
        if isinstance(day_of_month, bool) or not isinstance(day_of_month, int) or not 1 <= day_of_month <= 31:
            raise ValueError("Agenda monthly exige day_of_month entre 1 e 31.")
        if weekday is not None:
            raise ValueError("Agenda monthly nao aceita weekday.")

    return ScheduleDefinition(
        schedule_type=cast(ScheduleType, normalized_type),
        time_of_day=parsed_time,
        timezone=normalized_timezone,
        weekday=weekday,
        day_of_month=day_of_month,
    )


def calculate_next_run(
    definition: ScheduleDefinition,
    *,
    after: datetime,
) -> datetime:
    """Return the first scheduled instant strictly after ``after`` in UTC."""
    after_utc = _aware_utc(after, field_name="after")
    timezone = ZoneInfo(definition.timezone)
    local_after = after_utc.astimezone(timezone)

    if definition.schedule_type == "daily":
        candidate_date = local_after.date()
        candidate = _local_datetime(candidate_date, definition.time_of_day, timezone)
        if candidate <= local_after:
            candidate = _local_datetime(candidate_date + timedelta(days=1), definition.time_of_day, timezone)
        return candidate.astimezone(UTC)

    if definition.schedule_type == "weekly":
        assert definition.weekday is not None
        days_ahead = (definition.weekday - local_after.weekday()) % 7
        candidate_date = local_after.date() + timedelta(days=days_ahead)
        candidate = _local_datetime(candidate_date, definition.time_of_day, timezone)
        if candidate <= local_after:
            candidate = _local_datetime(candidate_date + timedelta(days=7), definition.time_of_day, timezone)
        return candidate.astimezone(UTC)

    assert definition.day_of_month is not None
    year = local_after.year
    month = local_after.month
    candidate_date = _monthly_date(year, month, definition.day_of_month)
    candidate = _local_datetime(candidate_date, definition.time_of_day, timezone)
    if candidate <= local_after:
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
        candidate_date = _monthly_date(year, month, definition.day_of_month)
        candidate = _local_datetime(candidate_date, definition.time_of_day, timezone)
    return candidate.astimezone(UTC)


class PromaxJobsService:
    def __init__(
        self,
        database_url: str,
        *,
        schema: str = DEFAULT_SCHEMA,
        connect_timeout_seconds: float = 3.0,
        pool: ConnectionPool[Any] | None = None,
    ) -> None:
        self.database_url = str(database_url or "").strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = pool
        self._pool_lock = RLock()
        self._schema_lock = RLock()
        self._schema_ready = False

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)

    def enqueue_job(
        self,
        *,
        job_type: str,
        payload: Mapping[str, Any] | None = None,
        priority: int = 0,
        concurrency_key: str = DEFAULT_CONCURRENCY_KEY,
        idempotency_key: str | None = None,
        available_at: datetime | None = None,
        source_schedule_id: str | UUID | None = None,
        scheduled_for: datetime | None = None,
        created_by: str = "",
    ) -> JobRecord:
        clean_job_type = _required_text(job_type, field_name="job_type", max_length=120)
        clean_concurrency_key = _required_text(
            concurrency_key,
            field_name="concurrency_key",
            max_length=120,
        )
        clean_idempotency_key = _optional_text(idempotency_key, max_length=300)
        normalized_available_at = _aware_utc(available_at or datetime.now(UTC), field_name="available_at")
        normalized_scheduled_for = (
            _aware_utc(scheduled_for, field_name="scheduled_for") if scheduled_for is not None else None
        )
        normalized_schedule_id = _uuid_text(source_schedule_id, field_name="source_schedule_id", allow_none=True)
        job_id = str(uuid4())

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {schema}.{jobs} (
                            id, job_type, payload, status, priority, concurrency_key,
                            idempotency_key, source_schedule_id, scheduled_for,
                            available_at, created_by
                        )
                        VALUES (
                            %s, %s, %s, 'pending', %s, %s,
                            %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING *
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (
                        job_id,
                        clean_job_type,
                        Jsonb(dict(payload or {})),
                        int(priority),
                        clean_concurrency_key,
                        clean_idempotency_key,
                        normalized_schedule_id,
                        normalized_scheduled_for,
                        normalized_available_at,
                        str(created_by or "").strip(),
                    ),
                )
                row = cur.fetchone()
                if row is None and clean_idempotency_key is not None:
                    cur.execute(
                        sql.SQL(
                            "SELECT * FROM {schema}.{jobs} WHERE idempotency_key = %s"
                        ).format(
                            schema=sql.Identifier(self.schema),
                            jobs=sql.Identifier(JOBS_TABLE),
                        ),
                        (clean_idempotency_key,),
                    )
                    row = cur.fetchone()
                if row is None:
                    raise RuntimeError("Nao foi possivel enfileirar o job Promax.")
                if str(row["id"]) == job_id:
                    self._append_log_cursor(
                        cur,
                        job_id=job_id,
                        level="info",
                        message="Job enfileirado.",
                        data={"created_by": str(created_by or "").strip()},
                    )
        return _job_record(row)

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 120,
        concurrency_key: str = DEFAULT_CONCURRENCY_KEY,
    ) -> JobRecord | None:
        clean_worker_id = _required_text(worker_id, field_name="worker_id", max_length=160)
        clean_concurrency_key = _required_text(
            concurrency_key,
            field_name="concurrency_key",
            max_length=120,
        )
        normalized_lease_seconds = _lease_seconds(lease_seconds)
        lease_token = str(uuid4())

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        WITH candidate AS (
                            SELECT j.id
                            FROM {schema}.{queue_state} AS q
                            JOIN {schema}.{jobs} AS j
                              ON j.status = 'pending'
                             AND j.available_at <= NOW()
                             AND j.concurrency_key = %s
                            WHERE q.singleton = TRUE
                              AND q.paused = FALSE
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM {schema}.{jobs} AS active_job
                                  WHERE active_job.concurrency_key = j.concurrency_key
                                    AND active_job.status IN ('running', 'cancel_requested')
                              )
                            ORDER BY j.priority DESC, j.available_at, j.created_at, j.id
                            FOR UPDATE OF q, j SKIP LOCKED
                            LIMIT 1
                        )
                        UPDATE {schema}.{jobs} AS j
                        SET
                            status = 'running',
                            lease_token = %s,
                            leased_by = %s,
                            lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                            heartbeat_at = NOW(),
                            started_at = COALESCE(j.started_at, NOW()),
                            attempt_count = j.attempt_count + 1,
                            updated_at = NOW()
                        FROM candidate
                        WHERE j.id = candidate.id
                        RETURNING j.*
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        queue_state=sql.Identifier(QUEUE_STATE_TABLE),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (clean_concurrency_key, lease_token, clean_worker_id, normalized_lease_seconds),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                self._upsert_worker_cursor(
                    cur,
                    worker_id=clean_worker_id,
                    current_job_id=str(row["id"]),
                    lease_token=lease_token,
                    metadata={},
                )
                self._append_log_cursor(
                    cur,
                    job_id=str(row["id"]),
                    level="info",
                    message="Job reivindicado pelo worker.",
                    data={"lease_seconds": normalized_lease_seconds},
                    worker_id=clean_worker_id,
                    lease_token=lease_token,
                )
        return _job_record(row)

    def heartbeat_job(
        self,
        *,
        job_id: str | UUID,
        lease_token: str | UUID,
        worker_id: str,
        lease_seconds: int = 120,
        worker_metadata: Mapping[str, Any] | None = None,
    ) -> HeartbeatResult:
        normalized_job_id = _uuid_text(job_id, field_name="job_id")
        normalized_lease_token = _uuid_text(lease_token, field_name="lease_token")
        clean_worker_id = _required_text(worker_id, field_name="worker_id", max_length=160)
        normalized_lease_seconds = _lease_seconds(lease_seconds)

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {schema}.{jobs}
                        SET
                            heartbeat_at = NOW(),
                            lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                            updated_at = NOW()
                        WHERE id = %s
                          AND lease_token = %s
                          AND leased_by = %s
                          AND status IN ('running', 'cancel_requested')
                          AND lease_expires_at > NOW()
                        RETURNING id, status, lease_expires_at, heartbeat_at
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (
                        normalized_lease_seconds,
                        normalized_job_id,
                        normalized_lease_token,
                        clean_worker_id,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    raise LeaseLostError(f"Lease invalido ou expirado para o job {normalized_job_id}.")
                self._upsert_worker_cursor(
                    cur,
                    worker_id=clean_worker_id,
                    current_job_id=normalized_job_id,
                    lease_token=normalized_lease_token,
                    metadata=dict(worker_metadata or {}),
                )
        status = cast(JobStatus, str(row["status"]))
        return {
            "job_id": str(row["id"]),
            "status": status,
            "cancel_requested": status == "cancel_requested",
            "lease_expires_at": _iso_required(row["lease_expires_at"]),
            "heartbeat_at": _iso_required(row["heartbeat_at"]),
        }

    def finish_job(
        self,
        *,
        job_id: str | UUID,
        lease_token: str | UUID,
        worker_id: str,
        status: JobStatus,
        result: Mapping[str, Any] | None = None,
        error: str = "",
    ) -> JobRecord:
        normalized_job_id = _uuid_text(job_id, field_name="job_id")
        normalized_lease_token = _uuid_text(lease_token, field_name="lease_token")
        clean_worker_id = _required_text(worker_id, field_name="worker_id", max_length=160)
        normalized_status = _job_status(status)
        if normalized_status not in WORKER_TERMINAL_STATUSES:
            raise ValueError("status final deve ser success, partial_success, failed ou cancelled.")

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {schema}.{jobs}
                        SET
                            status = %s,
                            result = %s,
                            error = %s,
                            finished_at = NOW(),
                            lease_token = NULL,
                            leased_by = NULL,
                            lease_expires_at = NULL,
                            heartbeat_at = NULL,
                            updated_at = NOW()
                        WHERE id = %s
                          AND lease_token = %s
                          AND leased_by = %s
                          AND status IN ('running', 'cancel_requested')
                          AND lease_expires_at > NOW()
                        RETURNING *
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (
                        normalized_status,
                        Jsonb(dict(result)) if result is not None else None,
                        str(error or ""),
                        normalized_job_id,
                        normalized_lease_token,
                        clean_worker_id,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    raise LeaseLostError(f"Lease invalido ou expirado para o job {normalized_job_id}.")
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {schema}.{worker_heartbeats}
                        SET current_job_id = NULL, lease_token = NULL, heartbeat_at = NOW()
                        WHERE worker_id = %s
                          AND current_job_id = %s
                          AND lease_token = %s
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        worker_heartbeats=sql.Identifier(WORKER_HEARTBEATS_TABLE),
                    ),
                    (clean_worker_id, normalized_job_id, normalized_lease_token),
                )
                self._append_log_cursor(
                    cur,
                    job_id=normalized_job_id,
                    level="error" if normalized_status == "failed" else "info",
                    message=f"Job finalizado como {normalized_status}.",
                    data={"error": str(error or "")} if error else {},
                    worker_id=clean_worker_id,
                    lease_token=normalized_lease_token,
                )
        return _job_record(row)

    def append_job_log(
        self,
        *,
        job_id: str | UUID,
        level: str,
        message: str,
        data: Mapping[str, Any] | None = None,
        worker_id: str | None = None,
        lease_token: str | UUID | None = None,
    ) -> JobLogRecord | None:
        normalized_job_id = _uuid_text(job_id, field_name="job_id")
        normalized_level = str(level or "").strip().lower()
        if normalized_level not in LOG_LEVELS:
            raise ValueError(f"level deve ser um de: {', '.join(LOG_LEVELS)}.")
        clean_message = _required_text(message, field_name="message", max_length=10_000)
        normalized_worker_id = _optional_text(worker_id, max_length=160)
        normalized_lease_token = _uuid_text(lease_token, field_name="lease_token", allow_none=True)
        if normalized_lease_token is not None and normalized_worker_id is None:
            raise ValueError("worker_id e obrigatorio quando lease_token for informado.")

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                if normalized_lease_token is None:
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {schema}.{job_logs} (
                                job_id, level, message, data, worker_id, lease_token
                            )
                            SELECT id, %s, %s, %s, %s, NULL
                            FROM {schema}.{jobs}
                            WHERE id = %s
                            RETURNING *
                            """
                        ).format(
                            schema=sql.Identifier(self.schema),
                            job_logs=sql.Identifier(JOB_LOGS_TABLE),
                            jobs=sql.Identifier(JOBS_TABLE),
                        ),
                        (
                            normalized_level,
                            clean_message,
                            Jsonb(dict(data or {})),
                            normalized_worker_id,
                            normalized_job_id,
                        ),
                    )
                else:
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {schema}.{job_logs} (
                                job_id, level, message, data, worker_id, lease_token
                            )
                            SELECT id, %s, %s, %s, %s, %s
                            FROM {schema}.{jobs}
                            WHERE id = %s
                              AND status IN ('running', 'cancel_requested')
                              AND leased_by = %s
                              AND lease_token = %s
                              AND lease_expires_at > NOW()
                            RETURNING *
                            """
                        ).format(
                            schema=sql.Identifier(self.schema),
                            job_logs=sql.Identifier(JOB_LOGS_TABLE),
                            jobs=sql.Identifier(JOBS_TABLE),
                        ),
                        (
                            normalized_level,
                            clean_message,
                            Jsonb(dict(data or {})),
                            normalized_worker_id,
                            normalized_lease_token,
                            normalized_job_id,
                            normalized_worker_id,
                            normalized_lease_token,
                        ),
                    )
                row = cur.fetchone()
                if row is None and normalized_lease_token is not None:
                    raise LeaseLostError(f"Lease invalido ou expirado para o job {normalized_job_id}.")
        return _job_log_record(row) if row else None

    def cancel_job(
        self,
        job_id: str | UUID,
        *,
        requested_by: str = "",
        reason: str = "",
    ) -> JobRecord | None:
        normalized_job_id = _uuid_text(job_id, field_name="job_id")
        clean_requested_by = str(requested_by or "").strip()
        clean_reason = str(reason or "").strip()

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT * FROM {schema}.{jobs} WHERE id = %s FOR UPDATE"
                    ).format(
                        schema=sql.Identifier(self.schema),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (normalized_job_id,),
                )
                current = cur.fetchone()
                if current is None:
                    return None
                current_status = str(current["status"])
                if current_status == "pending":
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {schema}.{jobs}
                            SET
                                status = 'cancelled',
                                cancel_requested_at = NOW(),
                                cancel_requested_by = %s,
                                cancel_reason = %s,
                                finished_at = NOW(),
                                updated_at = NOW()
                            WHERE id = %s
                            RETURNING *
                            """
                        ).format(
                            schema=sql.Identifier(self.schema),
                            jobs=sql.Identifier(JOBS_TABLE),
                        ),
                        (clean_requested_by, clean_reason, normalized_job_id),
                    )
                    row = cur.fetchone()
                    log_message = "Job pendente cancelado."
                elif current_status == "running":
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {schema}.{jobs}
                            SET
                                status = 'cancel_requested',
                                cancel_requested_at = NOW(),
                                cancel_requested_by = %s,
                                cancel_reason = %s,
                                updated_at = NOW()
                            WHERE id = %s
                            RETURNING *
                            """
                        ).format(
                            schema=sql.Identifier(self.schema),
                            jobs=sql.Identifier(JOBS_TABLE),
                        ),
                        (clean_requested_by, clean_reason, normalized_job_id),
                    )
                    row = cur.fetchone()
                    log_message = "Cancelamento solicitado ao worker."
                else:
                    return _job_record(current)
                self._append_log_cursor(
                    cur,
                    job_id=normalized_job_id,
                    level="warning",
                    message=log_message,
                    data={"requested_by": clean_requested_by, "reason": clean_reason},
                )
        return _job_record(row)

    def clear_pending_jobs(
        self,
        *,
        requested_by: str = "",
        reason: str = "Fila pendente limpa.",
        concurrency_key: str | None = None,
    ) -> int:
        clean_key = _optional_text(concurrency_key, max_length=120)
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                query = sql.SQL(
                    """
                    UPDATE {schema}.{jobs}
                    SET
                        status = 'cancelled',
                        cancel_requested_at = NOW(),
                        cancel_requested_by = %s,
                        cancel_reason = %s,
                        finished_at = NOW(),
                        updated_at = NOW()
                    WHERE status = 'pending'
                    """
                ).format(
                    schema=sql.Identifier(self.schema),
                    jobs=sql.Identifier(JOBS_TABLE),
                )
                params: list[Any] = [str(requested_by or "").strip(), str(reason or "").strip()]
                if clean_key is not None:
                    query += sql.SQL(" AND concurrency_key = %s")
                    params.append(clean_key)
                query += sql.SQL(" RETURNING id")
                cur.execute(query, params)
                rows = cur.fetchall()
                for row in rows:
                    self._append_log_cursor(
                        cur,
                        job_id=str(row["id"]),
                        level="warning",
                        message="Job pendente cancelado durante limpeza da fila.",
                        data={
                            "requested_by": str(requested_by or "").strip(),
                            "reason": str(reason or "").strip(),
                        },
                    )
        return len(rows)

    def pause_queue(self, *, reason: str = "", paused_by: str = "") -> QueueStateRecord:
        return self._set_queue_paused(paused=True, reason=reason, actor=paused_by)

    def resume_queue(self, *, resumed_by: str = "") -> QueueStateRecord:
        return self._set_queue_paused(paused=False, reason="", actor=resumed_by)

    def get_queue_state(self) -> QueueStateRecord:
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT * FROM {schema}.{queue_state} WHERE singleton = TRUE"
                    ).format(
                        schema=sql.Identifier(self.schema),
                        queue_state=sql.Identifier(QUEUE_STATE_TABLE),
                    )
                )
                row = cur.fetchone()
        if row is None:
            raise RuntimeError("Estado da fila Promax nao encontrado.")
        return _queue_state_record(row)

    def list_jobs(
        self,
        *,
        statuses: Sequence[JobStatus] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[JobRecord]:
        normalized_statuses = [_job_status(status) for status in statuses] if statuses else []
        safe_limit = _bounded_limit(limit, maximum=500)
        safe_offset = max(int(offset), 0)
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                query = sql.SQL("SELECT * FROM {schema}.{jobs}").format(
                    schema=sql.Identifier(self.schema),
                    jobs=sql.Identifier(JOBS_TABLE),
                )
                params: list[Any] = []
                if normalized_statuses:
                    query += sql.SQL(" WHERE status = ANY(%s)")
                    params.append(normalized_statuses)
                query += sql.SQL(" ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s")
                params.extend((safe_limit, safe_offset))
                cur.execute(query, params)
                rows = cur.fetchall()
        return [_job_record(row) for row in rows]

    def get_job(self, job_id: str | UUID) -> JobRecord | None:
        normalized_job_id = _uuid_text(job_id, field_name="job_id")
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {schema}.{jobs} WHERE id = %s").format(
                        schema=sql.Identifier(self.schema),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (normalized_job_id,),
                )
                row = cur.fetchone()
        return _job_record(row) if row else None

    def get_job_details(
        self,
        job_id: str | UUID,
        *,
        log_limit: int = 500,
    ) -> JobDetails | None:
        normalized_job_id = _uuid_text(job_id, field_name="job_id")
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {schema}.{jobs} WHERE id = %s").format(
                        schema=sql.Identifier(self.schema),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (normalized_job_id,),
                )
                job = cur.fetchone()
                if job is None:
                    return None
                cur.execute(
                    sql.SQL(
                        """
                        SELECT *
                        FROM {schema}.{job_logs}
                        WHERE job_id = %s
                        ORDER BY id
                        LIMIT %s
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        job_logs=sql.Identifier(JOB_LOGS_TABLE),
                    ),
                    (normalized_job_id, _bounded_limit(log_limit, maximum=5_000)),
                )
                logs = cur.fetchall()
        return {
            "job": _job_record(job),
            "logs": [_job_log_record(row) for row in logs],
        }

    def list_job_logs(
        self,
        job_id: str | UUID,
        *,
        limit: int = 500,
        after_id: int = 0,
    ) -> list[JobLogRecord]:
        normalized_job_id = _uuid_text(job_id, field_name="job_id")
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT *
                        FROM {schema}.{job_logs}
                        WHERE job_id = %s
                          AND id > %s
                        ORDER BY id
                        LIMIT %s
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        job_logs=sql.Identifier(JOB_LOGS_TABLE),
                    ),
                    (normalized_job_id, max(int(after_id), 0), _bounded_limit(limit, maximum=5_000)),
                )
                rows = cur.fetchall()
        return [_job_log_record(row) for row in rows]

    def create_schedule(
        self,
        *,
        name: str,
        job_type: str,
        payload: Mapping[str, Any] | None = None,
        schedule_type: str,
        time_of_day: str | time,
        timezone_name: str = DEFAULT_TIMEZONE,
        weekday: int | None = None,
        day_of_month: int | None = None,
        enabled: bool = True,
        created_by: str = "",
        now: datetime | None = None,
    ) -> ScheduleRecord:
        clean_name = _required_text(name, field_name="name", max_length=160)
        clean_job_type = _required_text(job_type, field_name="job_type", max_length=120)
        definition = validate_schedule_definition(
            schedule_type=schedule_type,
            time_of_day=time_of_day,
            timezone_name=timezone_name,
            weekday=weekday,
            day_of_month=day_of_month,
        )
        normalized_now = _aware_utc(now or datetime.now(UTC), field_name="now")
        next_run_at = calculate_next_run(definition, after=normalized_now)
        schedule_id = str(uuid4())

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {schema}.{schedules} (
                            id, name, job_type, payload, schedule_type, timezone,
                            time_of_day, weekday, day_of_month, enabled,
                            next_run_at, created_by
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    ),
                    (
                        schedule_id,
                        clean_name,
                        clean_job_type,
                        Jsonb(dict(payload or {})),
                        definition.schedule_type,
                        definition.timezone,
                        definition.time_of_day,
                        definition.weekday,
                        definition.day_of_month,
                        bool(enabled),
                        next_run_at,
                        str(created_by or "").strip(),
                    ),
                )
                row = cur.fetchone()
        if row is None:
            raise RuntimeError("Nao foi possivel criar a agenda Promax.")
        return _schedule_record(row)

    def update_schedule(
        self,
        schedule_id: str | UUID,
        *,
        name: str | None = None,
        job_type: str | None = None,
        payload: Mapping[str, Any] | None = None,
        schedule_type: str | None = None,
        time_of_day: str | time | None = None,
        timezone_name: str | None = None,
        weekday: int | None | object = _UNSET,
        day_of_month: int | None | object = _UNSET,
        enabled: bool | None = None,
        now: datetime | None = None,
    ) -> ScheduleRecord | None:
        normalized_schedule_id = _uuid_text(schedule_id, field_name="schedule_id")
        normalized_now = _aware_utc(now or datetime.now(UTC), field_name="now")

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT * FROM {schema}.{schedules} WHERE id = %s FOR UPDATE"
                    ).format(
                        schema=sql.Identifier(self.schema),
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    ),
                    (normalized_schedule_id,),
                )
                current = cur.fetchone()
                if current is None:
                    return None

                merged_weekday = current["weekday"] if weekday is _UNSET else weekday
                merged_day_of_month = current["day_of_month"] if day_of_month is _UNSET else day_of_month
                definition = validate_schedule_definition(
                    schedule_type=schedule_type if schedule_type is not None else str(current["schedule_type"]),
                    time_of_day=time_of_day if time_of_day is not None else current["time_of_day"],
                    timezone_name=timezone_name if timezone_name is not None else str(current["timezone"]),
                    weekday=cast(int | None, merged_weekday),
                    day_of_month=cast(int | None, merged_day_of_month),
                )
                clean_name = (
                    _required_text(name, field_name="name", max_length=160)
                    if name is not None
                    else str(current["name"])
                )
                clean_job_type = (
                    _required_text(job_type, field_name="job_type", max_length=120)
                    if job_type is not None
                    else str(current["job_type"])
                )
                merged_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
                recurrence_changed = any(
                    (
                        definition.schedule_type != str(current["schedule_type"]),
                        definition.time_of_day != current["time_of_day"],
                        definition.timezone != str(current["timezone"]),
                        definition.weekday != current["weekday"],
                        definition.day_of_month != current["day_of_month"],
                    )
                )
                reenabled = merged_enabled and not bool(current["enabled"])
                next_run_at = (
                    calculate_next_run(definition, after=normalized_now)
                    if recurrence_changed or reenabled
                    else current["next_run_at"]
                )

                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {schema}.{schedules}
                        SET
                            name = %s,
                            job_type = %s,
                            payload = %s,
                            schedule_type = %s,
                            timezone = %s,
                            time_of_day = %s,
                            weekday = %s,
                            day_of_month = %s,
                            enabled = %s,
                            next_run_at = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    ),
                    (
                        clean_name,
                        clean_job_type,
                        Jsonb(dict(payload)) if payload is not None else Jsonb(dict(current["payload"] or {})),
                        definition.schedule_type,
                        definition.timezone,
                        definition.time_of_day,
                        definition.weekday,
                        definition.day_of_month,
                        merged_enabled,
                        next_run_at,
                        normalized_schedule_id,
                    ),
                )
                row = cur.fetchone()
        return _schedule_record(row) if row else None

    def delete_schedule(self, schedule_id: str | UUID) -> bool:
        normalized_schedule_id = _uuid_text(schedule_id, field_name="schedule_id")
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {schema}.{schedules} WHERE id = %s RETURNING id"
                    ).format(
                        schema=sql.Identifier(self.schema),
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    ),
                    (normalized_schedule_id,),
                )
                row = cur.fetchone()
        return row is not None

    def get_schedule(self, schedule_id: str | UUID) -> ScheduleRecord | None:
        normalized_schedule_id = _uuid_text(schedule_id, field_name="schedule_id")
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {schema}.{schedules} WHERE id = %s").format(
                        schema=sql.Identifier(self.schema),
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    ),
                    (normalized_schedule_id,),
                )
                row = cur.fetchone()
        return _schedule_record(row) if row else None

    def list_schedules(self, *, include_disabled: bool = True) -> list[ScheduleRecord]:
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                query = sql.SQL("SELECT * FROM {schema}.{schedules}").format(
                    schema=sql.Identifier(self.schema),
                    schedules=sql.Identifier(SCHEDULES_TABLE),
                )
                if not include_disabled:
                    query += sql.SQL(" WHERE enabled = TRUE")
                query += sql.SQL(" ORDER BY name, id")
                cur.execute(query)
                rows = cur.fetchall()
        return [_schedule_record(row) for row in rows]

    def enqueue_due_schedules(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[JobRecord]:
        normalized_now = _aware_utc(now or datetime.now(UTC), field_name="now")
        safe_limit = _bounded_limit(limit, maximum=500)
        enqueued: list[JobRecord] = []

        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT *
                        FROM {schema}.{schedules}
                        WHERE enabled = TRUE
                          AND next_run_at <= %s
                        ORDER BY next_run_at, id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %s
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    ),
                    (normalized_now, safe_limit),
                )
                due_schedules = cur.fetchall()
                for schedule in due_schedules:
                    scheduled_for = _aware_utc(schedule["next_run_at"], field_name="next_run_at")
                    schedule_id = str(schedule["id"])
                    idempotency_key = _schedule_idempotency_key(schedule_id, scheduled_for)
                    job_id = str(uuid4())
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {schema}.{jobs} (
                                id, job_type, payload, status, priority, concurrency_key,
                                idempotency_key, source_schedule_id, scheduled_for,
                                available_at, created_by
                            )
                            VALUES (
                                %s, %s, %s, 'pending', 0, %s,
                                %s, %s, %s, %s, %s
                            )
                            ON CONFLICT (idempotency_key) DO NOTHING
                            RETURNING *
                            """
                        ).format(
                            schema=sql.Identifier(self.schema),
                            jobs=sql.Identifier(JOBS_TABLE),
                        ),
                        (
                            job_id,
                            str(schedule["job_type"]),
                            Jsonb(dict(schedule["payload"] or {})),
                            DEFAULT_CONCURRENCY_KEY,
                            idempotency_key,
                            schedule_id,
                            scheduled_for,
                            normalized_now,
                            f"schedule:{schedule_id}",
                        ),
                    )
                    job = cur.fetchone()
                    inserted = job is not None
                    if job is None:
                        cur.execute(
                            sql.SQL(
                                "SELECT * FROM {schema}.{jobs} WHERE idempotency_key = %s"
                            ).format(
                                schema=sql.Identifier(self.schema),
                                jobs=sql.Identifier(JOBS_TABLE),
                            ),
                            (idempotency_key,),
                        )
                        job = cur.fetchone()
                    if job is None:
                        raise RuntimeError(f"Job da agenda {schedule_id} nao foi encontrado apos enqueue.")

                    definition = _schedule_definition_from_row(schedule)
                    next_run_at = calculate_next_run(
                        definition,
                        after=max(normalized_now, scheduled_for),
                    )
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {schema}.{schedules}
                            SET
                                last_enqueued_for = %s,
                                next_run_at = %s,
                                updated_at = NOW()
                            WHERE id = %s
                            """
                        ).format(
                            schema=sql.Identifier(self.schema),
                            schedules=sql.Identifier(SCHEDULES_TABLE),
                        ),
                        (scheduled_for, next_run_at, schedule_id),
                    )
                    if inserted:
                        self._append_log_cursor(
                            cur,
                            job_id=job_id,
                            level="info",
                            message="Job criado por agenda.",
                            data={
                                "schedule_id": schedule_id,
                                "scheduled_for": scheduled_for.isoformat(),
                            },
                        )
                    enqueued.append(_job_record(job))
        return enqueued

    def reap_expired_leases(self, *, limit: int = 100) -> int:
        safe_limit = _bounded_limit(limit, maximum=1_000)
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        WITH expired AS (
                            SELECT id, lease_token, leased_by
                            FROM {schema}.{jobs}
                            WHERE status IN ('running', 'cancel_requested')
                              AND lease_expires_at <= NOW()
                            ORDER BY lease_expires_at, id
                            FOR UPDATE SKIP LOCKED
                            LIMIT %s
                        )
                        UPDATE {schema}.{jobs} AS j
                        SET
                            status = 'failed',
                            needs_review = TRUE,
                            failure_reason = 'lease_expired',
                            error = CASE
                                WHEN j.error = '' THEN 'Lease expirado; job nao sera reexecutado automaticamente.'
                                ELSE j.error
                            END,
                            finished_at = NOW(),
                            lease_token = NULL,
                            leased_by = NULL,
                            lease_expires_at = NULL,
                            heartbeat_at = NULL,
                            updated_at = NOW()
                        FROM expired
                        WHERE j.id = expired.id
                          AND j.lease_token = expired.lease_token
                          AND j.status IN ('running', 'cancel_requested')
                          AND j.lease_expires_at <= NOW()
                        RETURNING j.id, expired.leased_by AS leased_by, expired.lease_token
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    (safe_limit,),
                )
                expired_rows = cur.fetchall()
                for row in expired_rows:
                    self._append_log_cursor(
                        cur,
                        job_id=str(row["id"]),
                        level="error",
                        message="Lease expirado; job encerrado sem reexecucao automatica.",
                        data={},
                        worker_id=str(row["leased_by"] or "") or None,
                        lease_token=str(row["lease_token"]) if row["lease_token"] else None,
                    )
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {schema}.{worker_heartbeats}
                            SET current_job_id = NULL, lease_token = NULL
                            WHERE current_job_id = %s
                              AND lease_token = %s
                            """
                        ).format(
                            schema=sql.Identifier(self.schema),
                            worker_heartbeats=sql.Identifier(WORKER_HEARTBEATS_TABLE),
                        ),
                        (str(row["id"]), str(row["lease_token"])),
                    )
        return len(expired_rows)

    def register_worker_heartbeat(
        self,
        *,
        worker_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        clean_worker_id = _required_text(worker_id, field_name="worker_id", max_length=160)
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                self._touch_worker_cursor(
                    cur,
                    worker_id=clean_worker_id,
                    metadata=dict(metadata or {}),
                )

    def list_worker_heartbeats(
        self,
        *,
        online_within_seconds: int = 90,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_online_seconds = max(15, min(int(online_within_seconds), 3600))
        normalized_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT
                            worker_id,
                            current_job_id,
                            metadata,
                            started_at,
                            heartbeat_at,
                            heartbeat_at >= NOW() - (%s * INTERVAL '1 second') AS online
                        FROM {schema}.{worker_heartbeats}
                        ORDER BY heartbeat_at DESC, worker_id
                        LIMIT %s
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        worker_heartbeats=sql.Identifier(WORKER_HEARTBEATS_TABLE),
                    ),
                    (normalized_online_seconds, normalized_limit),
                )
                rows = cur.fetchall()
        return [
            {
                "worker_id": str(row["worker_id"]),
                "current_job_id": (
                    str(row["current_job_id"]) if row["current_job_id"] is not None else None
                ),
                "metadata": dict(row["metadata"] or {}),
                "started_at": _iso_required(row["started_at"]),
                "heartbeat_at": _iso_required(row["heartbeat_at"]),
                "online": bool(row["online"]),
            }
            for row in rows
        ]

    def _set_queue_paused(self, *, paused: bool, reason: str, actor: str) -> QueueStateRecord:
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {schema}.{queue_state}
                        SET
                            paused = %s,
                            pause_reason = %s,
                            paused_by = %s,
                            paused_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                            revision = revision + 1,
                            updated_at = NOW()
                        WHERE singleton = TRUE
                        RETURNING *
                        """
                    ).format(
                        schema=sql.Identifier(self.schema),
                        queue_state=sql.Identifier(QUEUE_STATE_TABLE),
                    ),
                    (
                        paused,
                        str(reason or "").strip() if paused else "",
                        str(actor or "").strip() or None,
                        paused,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            raise RuntimeError("Estado da fila Promax nao encontrado.")
        return _queue_state_record(row)

    def _ensure_schema(self, conn: Any) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            schema = sql.Identifier(self.schema)
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")
                cur.execute("SET LOCAL statement_timeout = '60s'")
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"promax_jobs_schema:{self.schema}",),
                )
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {schema}.{queue_state} (
                            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
                            paused BOOLEAN NOT NULL DEFAULT FALSE,
                            pause_reason TEXT NOT NULL DEFAULT '',
                            paused_by TEXT,
                            paused_at TIMESTAMPTZ,
                            revision BIGINT NOT NULL DEFAULT 0,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(
                        schema=schema,
                        queue_state=sql.Identifier(QUEUE_STATE_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {schema}.{queue_state} (singleton)
                        VALUES (TRUE)
                        ON CONFLICT (singleton) DO NOTHING
                        """
                    ).format(
                        schema=schema,
                        queue_state=sql.Identifier(QUEUE_STATE_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {schema}.{schedules} (
                            id UUID PRIMARY KEY,
                            name VARCHAR(160) NOT NULL,
                            job_type VARCHAR(120) NOT NULL,
                            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            schedule_type VARCHAR(16) NOT NULL
                                CHECK (schedule_type IN ('daily', 'weekly', 'monthly')),
                            timezone VARCHAR(120) NOT NULL,
                            time_of_day TIME NOT NULL,
                            weekday SMALLINT,
                            day_of_month SMALLINT,
                            enabled BOOLEAN NOT NULL DEFAULT TRUE,
                            next_run_at TIMESTAMPTZ NOT NULL,
                            last_enqueued_for TIMESTAMPTZ,
                            created_by TEXT NOT NULL DEFAULT '',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            CHECK (
                                (schedule_type = 'daily' AND weekday IS NULL AND day_of_month IS NULL)
                                OR (
                                    schedule_type = 'weekly'
                                    AND weekday BETWEEN 0 AND 6
                                    AND day_of_month IS NULL
                                )
                                OR (
                                    schedule_type = 'monthly'
                                    AND weekday IS NULL
                                    AND day_of_month BETWEEN 1 AND 31
                                )
                            )
                        )
                        """
                    ).format(
                        schema=schema,
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {schema}.{jobs} (
                            id UUID PRIMARY KEY,
                            job_type VARCHAR(120) NOT NULL,
                            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            status VARCHAR(32) NOT NULL DEFAULT 'pending'
                                CHECK (
                                    status IN (
                                        'pending', 'running', 'success', 'partial_success',
                                        'failed', 'cancel_requested', 'cancelled'
                                    )
                                ),
                            priority INTEGER NOT NULL DEFAULT 0,
                            concurrency_key VARCHAR(120) NOT NULL DEFAULT 'promax',
                            idempotency_key VARCHAR(300) UNIQUE,
                            source_schedule_id UUID
                                REFERENCES {schema}.{schedules}(id) ON DELETE SET NULL,
                            scheduled_for TIMESTAMPTZ,
                            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
                            lease_token UUID,
                            leased_by VARCHAR(160),
                            lease_expires_at TIMESTAMPTZ,
                            heartbeat_at TIMESTAMPTZ,
                            cancel_requested_at TIMESTAMPTZ,
                            cancel_requested_by TEXT,
                            cancel_reason TEXT NOT NULL DEFAULT '',
                            result JSONB,
                            error TEXT NOT NULL DEFAULT '',
                            failure_reason VARCHAR(80) NOT NULL DEFAULT '',
                            needs_review BOOLEAN NOT NULL DEFAULT FALSE,
                            created_by TEXT NOT NULL DEFAULT '',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            started_at TIMESTAMPTZ,
                            finished_at TIMESTAMPTZ,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            CHECK (
                                status NOT IN ('running', 'cancel_requested')
                                OR (
                                    lease_token IS NOT NULL
                                    AND leased_by IS NOT NULL
                                    AND lease_expires_at IS NOT NULL
                                )
                            )
                        )
                        """
                    ).format(
                        schema=schema,
                        jobs=sql.Identifier(JOBS_TABLE),
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {schema}.{job_logs} (
                            id BIGSERIAL PRIMARY KEY,
                            job_id UUID NOT NULL REFERENCES {schema}.{jobs}(id) ON DELETE RESTRICT,
                            level VARCHAR(16) NOT NULL
                                CHECK (level IN ('debug', 'info', 'warning', 'error')),
                            message TEXT NOT NULL,
                            data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            worker_id VARCHAR(160),
                            lease_token UUID,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(
                        schema=schema,
                        job_logs=sql.Identifier(JOB_LOGS_TABLE),
                        jobs=sql.Identifier(JOBS_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {schema}.{worker_heartbeats} (
                            worker_id VARCHAR(160) PRIMARY KEY,
                            current_job_id UUID REFERENCES {schema}.{jobs}(id) ON DELETE SET NULL,
                            lease_token UUID,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(
                        schema=schema,
                        worker_heartbeats=sql.Identifier(WORKER_HEARTBEATS_TABLE),
                        jobs=sql.Identifier(JOBS_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        "ALTER TABLE {schema}.{jobs} "
                        "ADD COLUMN IF NOT EXISTS failure_reason VARCHAR(80) NOT NULL DEFAULT ''"
                    ).format(
                        schema=schema,
                        jobs=sql.Identifier(JOBS_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        "ALTER TABLE {schema}.{jobs} "
                        "ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT FALSE"
                    ).format(
                        schema=schema,
                        jobs=sql.Identifier(JOBS_TABLE),
                    )
                )
                statements = (
                    sql.SQL(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS {index}
                        ON {schema}.{jobs} (concurrency_key)
                        WHERE status IN ('running', 'cancel_requested')
                        """
                    ).format(
                        index=sql.Identifier("promax_jobs_one_active_per_key_idx"),
                        schema=schema,
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {index}
                        ON {schema}.{jobs} (status, concurrency_key, priority DESC, available_at, created_at)
                        """
                    ).format(
                        index=sql.Identifier("promax_jobs_claim_idx"),
                        schema=schema,
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {index}
                        ON {schema}.{jobs} (lease_expires_at)
                        WHERE status IN ('running', 'cancel_requested')
                        """
                    ).format(
                        index=sql.Identifier("promax_jobs_expired_lease_idx"),
                        schema=schema,
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {index}
                        ON {schema}.{job_logs} (job_id, id)
                        """
                    ).format(
                        index=sql.Identifier("promax_job_logs_job_idx"),
                        schema=schema,
                        job_logs=sql.Identifier(JOB_LOGS_TABLE),
                    ),
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {index}
                        ON {schema}.{schedules} (next_run_at)
                        WHERE enabled = TRUE
                        """
                    ).format(
                        index=sql.Identifier("promax_schedules_due_idx"),
                        schema=schema,
                        schedules=sql.Identifier(SCHEDULES_TABLE),
                    ),
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {index}
                        ON {schema}.{worker_heartbeats} (heartbeat_at)
                        """
                    ).format(
                        index=sql.Identifier("promax_worker_heartbeats_at_idx"),
                        schema=schema,
                        worker_heartbeats=sql.Identifier(WORKER_HEARTBEATS_TABLE),
                    ),
                    sql.SQL(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS {index}
                        ON {schema}.{jobs} (source_schedule_id, scheduled_for)
                        WHERE source_schedule_id IS NOT NULL AND scheduled_for IS NOT NULL
                        """
                    ).format(
                        index=sql.Identifier("promax_jobs_schedule_occurrence_idx"),
                        schema=schema,
                        jobs=sql.Identifier(JOBS_TABLE),
                    ),
                )
                for statement in statements:
                    cur.execute(statement)
                function_name = sql.Identifier("reject_job_log_mutation")
                trigger_name = sql.Identifier("promax_job_logs_append_only")
                cur.execute(
                    sql.SQL(
                        """
                        CREATE OR REPLACE FUNCTION {schema}.{function_name}()
                        RETURNS trigger
                        LANGUAGE plpgsql
                        AS $$
                        BEGIN
                            RAISE EXCEPTION 'job_logs is append-only';
                        END;
                        $$
                        """
                    ).format(
                        schema=schema,
                        function_name=function_name,
                    )
                )
                cur.execute(
                    sql.SQL(
                        "DROP TRIGGER IF EXISTS {trigger_name} "
                        "ON {schema}.{job_logs}"
                    ).format(
                        trigger_name=trigger_name,
                        schema=schema,
                        job_logs=sql.Identifier(JOB_LOGS_TABLE),
                    )
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TRIGGER {trigger_name}
                        BEFORE UPDATE OR DELETE ON {schema}.{job_logs}
                        FOR EACH ROW
                        EXECUTE FUNCTION {schema}.{function_name}()
                        """
                    ).format(
                        trigger_name=trigger_name,
                        schema=schema,
                        job_logs=sql.Identifier(JOB_LOGS_TABLE),
                        function_name=function_name,
                    )
                )
            conn.commit()
            self._schema_ready = True

    def _append_log_cursor(
        self,
        cur: Any,
        *,
        job_id: str,
        level: str,
        message: str,
        data: Mapping[str, Any],
        worker_id: str | None = None,
        lease_token: str | None = None,
    ) -> None:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {schema}.{job_logs} (
                    job_id, level, message, data, worker_id, lease_token
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """
            ).format(
                schema=sql.Identifier(self.schema),
                job_logs=sql.Identifier(JOB_LOGS_TABLE),
            ),
            (
                job_id,
                level,
                message,
                Jsonb(dict(data)),
                worker_id,
                lease_token,
            ),
        )

    def _upsert_worker_cursor(
        self,
        cur: Any,
        *,
        worker_id: str,
        current_job_id: str | None,
        lease_token: str | None,
        metadata: Mapping[str, Any],
    ) -> None:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {schema}.{worker_heartbeats} (
                    worker_id, current_job_id, lease_token, metadata
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (worker_id) DO UPDATE
                SET
                    current_job_id = EXCLUDED.current_job_id,
                    lease_token = EXCLUDED.lease_token,
                    metadata = EXCLUDED.metadata,
                    heartbeat_at = NOW()
                """
            ).format(
                schema=sql.Identifier(self.schema),
                worker_heartbeats=sql.Identifier(WORKER_HEARTBEATS_TABLE),
            ),
            (worker_id, current_job_id, lease_token, Jsonb(dict(metadata))),
        )

    def _touch_worker_cursor(
        self,
        cur: Any,
        *,
        worker_id: str,
        metadata: Mapping[str, Any],
    ) -> None:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {schema}.{worker_heartbeats} (
                    worker_id, metadata
                )
                VALUES (%s, %s)
                ON CONFLICT (worker_id) DO UPDATE
                SET
                    metadata = EXCLUDED.metadata,
                    heartbeat_at = NOW()
                """
            ).format(
                schema=sql.Identifier(self.schema),
                worker_heartbeats=sql.Identifier(WORKER_HEARTBEATS_TABLE),
            ),
            (worker_id, Jsonb(dict(metadata))),
        )

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self._pool is None:
            with self._pool_lock:
                if self._pool is None:
                    self._pool = get_connection_pool(
                        self.database_url,
                        connect_timeout_seconds=self.connect_timeout_seconds,
                    )
        with self._pool.connection() as conn:
            yield conn


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise ValueError("time_of_day deve ser um horario local sem timezone.")
        return value.replace(microsecond=0)
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("time_of_day e obrigatorio.")
    try:
        parsed = time.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("time_of_day deve usar o formato HH:MM ou HH:MM:SS.") from exc
    if parsed.tzinfo is not None:
        raise ValueError("time_of_day deve ser um horario local sem timezone.")
    return parsed.replace(microsecond=0)


def _local_datetime(local_date: date, local_time: time, timezone: ZoneInfo) -> datetime:
    candidate = datetime.combine(local_date, local_time, tzinfo=timezone)
    round_trip = candidate.astimezone(UTC).astimezone(timezone)
    expected_wall_time = local_time.replace(tzinfo=None)
    if round_trip.date() != local_date or round_trip.time().replace(tzinfo=None) != expected_wall_time:
        return round_trip
    return candidate


def _monthly_date(year: int, month: int, requested_day: int) -> date:
    return date(year, month, min(requested_day, monthrange(year, month)[1]))


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} deve ser datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} deve possuir timezone.")
    return value.astimezone(UTC)


def _normalize_schema(value: str) -> str:
    normalized = str(value or "").strip() or DEFAULT_SCHEMA
    if "\x00" in normalized:
        raise ValueError("schema invalido.")
    return normalized


def _required_text(value: Any, *, field_name: str, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} e obrigatorio.")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} excede {max_length} caracteres.")
    return normalized


def _optional_text(value: Any, *, max_length: int) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"Valor excede {max_length} caracteres.")
    return normalized


def _uuid_text(value: Any, *, field_name: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{field_name} deve ser um UUID valido.") from exc


def _lease_seconds(value: int) -> int:
    normalized = int(value)
    if not 1 <= normalized <= 86_400:
        raise ValueError("lease_seconds deve estar entre 1 e 86400.")
    return normalized


def _bounded_limit(value: int, *, maximum: int) -> int:
    normalized = int(value)
    if normalized < 1:
        raise ValueError("limit deve ser maior que zero.")
    return min(normalized, maximum)


def _job_status(value: str) -> JobStatus:
    normalized = str(value or "").strip().lower()
    if normalized not in JOB_STATUSES:
        raise ValueError(f"Status de job invalido: {value}.")
    return cast(JobStatus, normalized)


def _schedule_idempotency_key(schedule_id: str, scheduled_for: datetime) -> str:
    instant = _aware_utc(scheduled_for, field_name="scheduled_for")
    return f"schedule:{schedule_id}:{instant.isoformat(timespec='seconds')}"


def _schedule_definition_from_row(row: Mapping[str, Any]) -> ScheduleDefinition:
    return validate_schedule_definition(
        schedule_type=str(row["schedule_type"]),
        time_of_day=row["time_of_day"],
        timezone_name=str(row["timezone"]),
        weekday=row.get("weekday"),
        day_of_month=row.get("day_of_month"),
    )


def _job_record(row: Mapping[str, Any]) -> JobRecord:
    return {
        "id": str(row["id"]),
        "job_type": str(row["job_type"]),
        "payload": dict(row.get("payload") or {}),
        "status": _job_status(str(row["status"])),
        "priority": int(row.get("priority") or 0),
        "concurrency_key": str(row.get("concurrency_key") or ""),
        "idempotency_key": str(row["idempotency_key"]) if row.get("idempotency_key") else None,
        "source_schedule_id": str(row["source_schedule_id"]) if row.get("source_schedule_id") else None,
        "scheduled_for": _iso(row.get("scheduled_for")),
        "available_at": _iso_required(row["available_at"]),
        "attempt_count": int(row.get("attempt_count") or 0),
        "lease_token": str(row["lease_token"]) if row.get("lease_token") else None,
        "leased_by": str(row["leased_by"]) if row.get("leased_by") else None,
        "lease_expires_at": _iso(row.get("lease_expires_at")),
        "heartbeat_at": _iso(row.get("heartbeat_at")),
        "cancel_requested_at": _iso(row.get("cancel_requested_at")),
        "cancel_requested_by": (
            str(row["cancel_requested_by"]) if row.get("cancel_requested_by") else None
        ),
        "cancel_reason": str(row.get("cancel_reason") or ""),
        "result": dict(row["result"]) if row.get("result") is not None else None,
        "error": str(row.get("error") or ""),
        "failure_reason": str(row.get("failure_reason") or ""),
        "needs_review": bool(row.get("needs_review")),
        "created_by": str(row.get("created_by") or ""),
        "created_at": _iso_required(row["created_at"]),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
        "updated_at": _iso_required(row["updated_at"]),
    }


def _job_log_record(row: Mapping[str, Any]) -> JobLogRecord:
    return {
        "id": int(row["id"]),
        "job_id": str(row["job_id"]),
        "level": str(row["level"]),
        "message": str(row["message"]),
        "data": dict(row.get("data") or {}),
        "worker_id": str(row["worker_id"]) if row.get("worker_id") else None,
        "lease_token": str(row["lease_token"]) if row.get("lease_token") else None,
        "created_at": _iso_required(row["created_at"]),
    }


def _schedule_record(row: Mapping[str, Any]) -> ScheduleRecord:
    schedule_time = row["time_of_day"]
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "job_type": str(row["job_type"]),
        "payload": dict(row.get("payload") or {}),
        "schedule_type": cast(ScheduleType, str(row["schedule_type"])),
        "timezone": str(row["timezone"]),
        "time_of_day": (
            schedule_time.isoformat(timespec="seconds")
            if isinstance(schedule_time, time)
            else str(schedule_time)
        ),
        "weekday": int(row["weekday"]) if row.get("weekday") is not None else None,
        "day_of_month": int(row["day_of_month"]) if row.get("day_of_month") is not None else None,
        "enabled": bool(row["enabled"]),
        "next_run_at": _iso_required(row["next_run_at"]),
        "last_enqueued_for": _iso(row.get("last_enqueued_for")),
        "created_by": str(row.get("created_by") or ""),
        "created_at": _iso_required(row["created_at"]),
        "updated_at": _iso_required(row["updated_at"]),
    }


def _queue_state_record(row: Mapping[str, Any]) -> QueueStateRecord:
    return {
        "paused": bool(row["paused"]),
        "pause_reason": str(row.get("pause_reason") or ""),
        "paused_by": str(row["paused_by"]) if row.get("paused_by") else None,
        "paused_at": _iso(row.get("paused_at")),
        "revision": int(row.get("revision") or 0),
        "updated_at": _iso_required(row["updated_at"]),
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(UTC)
        return value.isoformat()
    return str(value)


def _iso_required(value: Any) -> str:
    serialized = _iso(value)
    if serialized is None:
        raise ValueError("Timestamp obrigatorio ausente.")
    return serialized
