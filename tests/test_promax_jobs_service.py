from __future__ import annotations

import unittest
from datetime import UTC, datetime, time
from typing import Any

from bot_api.services.promax_jobs_service import (
    DEFAULT_SCHEMA,
    LeaseLostError,
    PromaxJobsService,
    _schedule_idempotency_key,
    calculate_next_run,
    validate_schedule_definition,
)


class FakeCursor:
    def __init__(
        self,
        *,
        fetchone_values: list[dict[str, Any] | None] | None = None,
        fetchall_values: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.executions: list[tuple[Any, Any]] = []
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: Any, params: Any = None) -> None:
        self.executions.append((query, params))

    def fetchone(self) -> dict[str, Any] | None:
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.fetchall_values.pop(0) if self.fetchall_values else []


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor
        self.commits = 0

    def cursor(self, **_kwargs: Any) -> FakeCursor:
        return self.fake_cursor

    def commit(self) -> None:
        self.commits += 1


class FakeConnectionContext:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, *_args: Any) -> None:
        return None


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.fake_connection = connection

    def connection(self) -> FakeConnectionContext:
        return FakeConnectionContext(self.fake_connection)


def query_text(query: Any) -> str:
    return query.as_string(None) if hasattr(query, "as_string") else str(query)


class PromaxScheduleCalculationTests(unittest.TestCase):
    def test_daily_next_run_uses_schedule_timezone(self) -> None:
        definition = validate_schedule_definition(
            schedule_type="daily",
            time_of_day="09:00",
            timezone_name="America/Fortaleza",
        )

        before_local_time = calculate_next_run(
            definition,
            after=datetime(2026, 7, 18, 11, 0, tzinfo=UTC),
        )
        after_local_time = calculate_next_run(
            definition,
            after=datetime(2026, 7, 18, 13, 0, tzinfo=UTC),
        )

        self.assertEqual(before_local_time, datetime(2026, 7, 18, 12, 0, tzinfo=UTC))
        self.assertEqual(after_local_time, datetime(2026, 7, 19, 12, 0, tzinfo=UTC))

    def test_weekly_next_run_uses_monday_zero_convention(self) -> None:
        definition = validate_schedule_definition(
            schedule_type="weekly",
            time_of_day=time(8, 30),
            timezone_name="America/Fortaleza",
            weekday=0,
        )

        result = calculate_next_run(
            definition,
            after=datetime(2026, 7, 17, 18, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 20, 11, 30, tzinfo=UTC))

    def test_monthly_day_is_clamped_to_last_day_of_short_month(self) -> None:
        definition = validate_schedule_definition(
            schedule_type="monthly",
            time_of_day="10:00",
            timezone_name="America/Fortaleza",
            day_of_month=31,
        )

        february = calculate_next_run(
            definition,
            after=datetime(2026, 2, 1, 0, 0, tzinfo=UTC),
        )
        march = calculate_next_run(
            definition,
            after=datetime(2026, 2, 28, 13, 0, tzinfo=UTC),
        )

        self.assertEqual(february, datetime(2026, 2, 28, 13, 0, tzinfo=UTC))
        self.assertEqual(march, datetime(2026, 3, 31, 13, 0, tzinfo=UTC))

    def test_schedule_validation_rejects_incompatible_fields(self) -> None:
        invalid_cases = (
            {
                "schedule_type": "weekly",
                "time_of_day": "08:00",
                "weekday": None,
            },
            {
                "schedule_type": "monthly",
                "time_of_day": "08:00",
                "day_of_month": 0,
            },
            {
                "schedule_type": "daily",
                "time_of_day": "08:00",
                "weekday": 1,
            },
            {
                "schedule_type": "daily",
                "time_of_day": "25:00",
            },
            {
                "schedule_type": "daily",
                "time_of_day": "08:00",
                "timezone_name": "Timezone/Inexistente",
            },
        )

        for case in invalid_cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    validate_schedule_definition(**case)

    def test_next_run_rejects_naive_reference_datetime(self) -> None:
        definition = validate_schedule_definition(
            schedule_type="daily",
            time_of_day="08:00",
        )

        with self.assertRaisesRegex(ValueError, "timezone"):
            calculate_next_run(definition, after=datetime(2026, 7, 18, 8, 0))

    def test_schedule_idempotency_key_normalizes_equivalent_instants(self) -> None:
        schedule_id = "8cc06d03-1b8f-4e8f-b1d0-2c49d77d37a2"

        utc_key = _schedule_idempotency_key(
            schedule_id,
            datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        )
        local_key = _schedule_idempotency_key(
            schedule_id,
            datetime.fromisoformat("2026-07-18T09:00:00-03:00"),
        )

        self.assertEqual(utc_key, local_key)


class PromaxSqlContractTests(unittest.TestCase):
    def make_service(
        self,
        cursor: FakeCursor,
        *,
        schema: str = DEFAULT_SCHEMA,
        schema_ready: bool = True,
    ) -> tuple[PromaxJobsService, FakeConnection]:
        connection = FakeConnection(cursor)
        service = PromaxJobsService(
            "postgresql://unused",
            schema=schema,
            pool=FakePool(connection),  # type: ignore[arg-type]
        )
        service._schema_ready = schema_ready
        return service, connection

    def test_schema_contract_creates_all_tables_and_active_job_uniqueness(self) -> None:
        cursor = FakeCursor()
        service, connection = self.make_service(
            cursor,
            schema="promax_test",
            schema_ready=False,
        )

        service.ensure_schema()

        ddl = "\n".join(query_text(query) for query, _params in cursor.executions)
        for table_name in ("jobs", "job_logs", "schedules", "worker_heartbeats", "queue_state"):
            self.assertIn(f'"promax_test"."{table_name}"', ddl)
        self.assertIn("CREATE UNIQUE INDEX", ddl)
        self.assertIn("status IN ('running', 'cancel_requested')", ddl)
        self.assertIn("needs_review BOOLEAN", ddl)
        self.assertIn("promax_jobs_schedule_occurrence_idx", ddl)
        self.assertIn("promax_job_logs_append_only", ddl)
        self.assertIn("BEFORE UPDATE OR DELETE", ddl)
        self.assertIn("pg_advisory_xact_lock", ddl)
        self.assertEqual(connection.commits, 1)

    def test_claim_is_atomic_skip_locked_and_assigns_lease_token(self) -> None:
        cursor = FakeCursor(fetchone_values=[None])
        service, _connection = self.make_service(cursor)

        claimed = service.claim_next_job(worker_id="worker-1", lease_seconds=45)

        self.assertIsNone(claimed)
        statement = query_text(cursor.executions[0][0])
        self.assertIn("FOR UPDATE OF q, j SKIP LOCKED", statement)
        self.assertIn("UPDATE \"promax\".\"jobs\" AS j", statement)
        self.assertIn("lease_token = %s", statement)
        self.assertIn("active_job.status IN ('running', 'cancel_requested')", statement)
        self.assertEqual(cursor.executions[0][1][0], "promax")
        self.assertEqual(cursor.executions[0][1][-1], 45)

    def test_heartbeat_fences_wrong_or_expired_lease(self) -> None:
        cursor = FakeCursor(fetchone_values=[None])
        service, _connection = self.make_service(cursor)

        with self.assertRaises(LeaseLostError):
            service.heartbeat_job(
                job_id="1d42b4cf-b851-48b8-888e-2a33cc6f5608",
                lease_token="9a31bdf4-8672-4747-9acc-132ad046d5a4",
                worker_id="worker-1",
            )

        statement = query_text(cursor.executions[0][0])
        self.assertIn("lease_token = %s", statement)
        self.assertIn("leased_by = %s", statement)
        self.assertIn("lease_expires_at > NOW()", statement)

    def test_reaper_marks_expired_jobs_failed_without_requeue(self) -> None:
        cursor = FakeCursor(fetchall_values=[[]])
        service, _connection = self.make_service(cursor)

        reaped = service.reap_expired_leases()

        self.assertEqual(reaped, 0)
        statement = query_text(cursor.executions[0][0])
        self.assertIn("FOR UPDATE SKIP LOCKED", statement)
        self.assertIn("status = 'failed'", statement)
        self.assertIn("needs_review = TRUE", statement)
        self.assertIn("failure_reason = 'lease_expired'", statement)
        self.assertIn("nao sera reexecutado automaticamente", statement)
        self.assertNotIn("status = 'pending'", statement)


if __name__ == "__main__":
    unittest.main()
