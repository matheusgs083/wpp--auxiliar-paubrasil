from __future__ import annotations

import unittest
from datetime import UTC, datetime, time
from typing import Any

from bot_api.services.promax_jobs_service import (
    DEFAULT_SCHEMA,
    LeaseLostError,
    PromaxJobsService,
    _schedule_idempotency_key,
    _schedule_trigger_idempotency_key,
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

    def test_schedule_trigger_idempotency_key_uses_both_ids(self) -> None:
        schedule_id = "8cc06d03-1b8f-4e8f-b1d0-2c49d77d37a2"
        parent_job_id = "1d42b4cf-b851-48b8-888e-2a33cc6f5608"

        self.assertEqual(
            _schedule_trigger_idempotency_key(schedule_id, parent_job_id),
            f"schedule-trigger:{schedule_id}:{parent_job_id}",
        )


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
        self.assertIn("trigger_after_schedule_id", ddl)
        self.assertIn("triggered_by_job_id", ddl)
        self.assertIn("promax_jobs_schedule_trigger_idx", ddl)
        self.assertIn("promax_jobs_open_schedule_idx", ddl)
        self.assertIn("promax_jobs_created_at_idx", ddl)
        self.assertIn("promax_job_logs_append_only", ddl)
        self.assertIn("BEFORE UPDATE OR DELETE", ddl)
        self.assertIn("pg_advisory_xact_lock", ddl)
        self.assertEqual(connection.commits, 1)

    def test_schedule_enqueue_separates_timed_and_completion_triggers(self) -> None:
        cursor = FakeCursor(fetchall_values=[[], []])
        service, _connection = self.make_service(cursor)

        jobs = service.enqueue_due_schedules(
            now=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
            limit=20,
        )

        self.assertEqual(jobs, [])
        statements = [query_text(query) for query, _params in cursor.executions]
        self.assertIn("trigger_after_schedule_id IS NULL", statements[0])
        self.assertIn("open_job.source_schedule_id = due.id", statements[0])
        self.assertIn("open_job.status IN ('pending', 'running', 'cancel_requested')", statements[0])
        self.assertIn("JOIN LATERAL", statements[1])
        self.assertIn("parent.status IN ('success', 'partial_success')", statements[1])
        self.assertIn("triggered.triggered_by_job_id = parent.id", statements[1])
        self.assertIn("open_child_job.source_schedule_id = child.id", statements[1])
        self.assertIn("open_child_job.status IN ('pending', 'running', 'cancel_requested')", statements[1])

    def test_enqueue_jobs_uses_one_transaction_and_preserves_batch_order(self) -> None:
        created_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
        cursor = FakeCursor(
            fetchone_values=[
                {
                    "id": "job-1",
                    "job_type": "adf",
                    "payload": {"routines": ["030237"]},
                    "status": "pending",
                    "available_at": created_at,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
                {
                    "id": "job-2",
                    "job_type": "obz",
                    "payload": {"routines": ["0512"]},
                    "status": "pending",
                    "available_at": created_at,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            ]
        )
        service, _connection = self.make_service(cursor)

        jobs = service.enqueue_jobs(
            items=[
                {"job_type": "adf", "payload": {"routines": ["030237"]}},
                {"job_type": "obz", "payload": {"routines": ["0512"]}},
            ],
            created_by="admin",
            available_at=created_at,
        )

        self.assertEqual([job["job_type"] for job in jobs], ["adf", "obz"])
        self.assertEqual(len(cursor.executions), 2)
        first_params = cursor.executions[0][1]
        second_params = cursor.executions[1][1]
        self.assertEqual(first_params[1], "adf")
        self.assertEqual(second_params[1], "obz")
        self.assertLess(first_params[8], second_params[8])
        self.assertEqual(first_params[9], "admin")
        self.assertEqual(second_params[9], "admin")

    def test_enqueue_jobs_rejects_an_empty_or_oversized_batch(self) -> None:
        service, _connection = self.make_service(FakeCursor())

        with self.assertRaisesRegex(ValueError, "entre 1 e 50"):
            service.enqueue_jobs(items=[])
        with self.assertRaisesRegex(ValueError, "entre 1 e 50"):
            service.enqueue_jobs(
                items=[{"job_type": f"group-{index}"} for index in range(51)]
            )

    def test_enqueue_schedule_now_preserves_schedule_next_run(self) -> None:
        now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
        schedule_id = "8cc06d03-1b8f-4e8f-b1d0-2c49d77d37a2"
        cursor = FakeCursor(
            fetchone_values=[
                {
                    "id": schedule_id,
                    "job_type": "bot_zap",
                    "payload": {"category": "bot_zap", "routines": ["120601_BOT"]},
                },
                {
                    "id": "job-1",
                    "job_type": "bot_zap",
                    "payload": {"category": "bot_zap", "routines": ["120601_BOT"]},
                    "status": "pending",
                    "priority": 20,
                    "concurrency_key": "promax",
                    "idempotency_key": f"manual-schedule:{schedule_id}:2026-07-18T12:00:00+00:00",
                    "source_schedule_id": schedule_id,
                    "scheduled_for": now,
                    "available_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            ]
        )
        service, _connection = self.make_service(cursor)

        job = service.enqueue_schedule_now(schedule_id, requested_by="admin", now=now)

        self.assertIsNotNone(job)
        self.assertEqual(job["source_schedule_id"], schedule_id)
        select_statement = query_text(cursor.executions[0][0])
        insert_statement = query_text(cursor.executions[1][0])
        self.assertIn("FROM \"promax\".\"schedules\" WHERE id = %s", select_statement)
        self.assertIn("INSERT INTO \"promax\".\"jobs\"", insert_statement)
        self.assertNotIn("UPDATE \"promax\".\"schedules\"", insert_statement)
        insert_params = cursor.executions[1][1]
        self.assertEqual(insert_params[1], "bot_zap")
        self.assertEqual(insert_params[3], 20)
        self.assertTrue(str(insert_params[5]).startswith(f"manual-schedule:{schedule_id}:"))
        self.assertEqual(insert_params[6], schedule_id)
        self.assertEqual(insert_params[7], now)
        self.assertEqual(insert_params[9], "admin")

    def test_list_jobs_filters_status_and_created_at_bounds(self) -> None:
        cursor = FakeCursor(fetchall_values=[[]])
        service, _connection = self.make_service(cursor)
        created_from = datetime(2026, 7, 18, 3, 0, tzinfo=UTC)
        created_before = datetime(2026, 7, 20, 3, 0, tzinfo=UTC)

        jobs = service.list_jobs(
            statuses=["success"],
            created_from=created_from,
            created_before=created_before,
            limit=25,
        )

        self.assertEqual(jobs, [])
        statement = query_text(cursor.executions[0][0])
        self.assertIn("status = ANY(%s)", statement)
        self.assertIn("created_at >= %s", statement)
        self.assertIn("created_at < %s", statement)
        self.assertEqual(
            cursor.executions[0][1],
            [["success"], created_from, created_before, 25, 0],
        )

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

    def test_heartbeat_preserves_worker_catalog_metadata(self) -> None:
        now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
        cursor = FakeCursor(
            fetchone_values=[
                {
                    "id": "1d42b4cf-b851-48b8-888e-2a33cc6f5608",
                    "status": "running",
                    "lease_expires_at": now,
                    "heartbeat_at": now,
                }
            ]
        )
        service, _connection = self.make_service(cursor)

        service.heartbeat_job(
            job_id="1d42b4cf-b851-48b8-888e-2a33cc6f5608",
            lease_token="9a31bdf4-8672-4747-9acc-132ad046d5a4",
            worker_id="worker-1",
            worker_metadata={"pid": 4321},
        )

        worker_statement = query_text(cursor.executions[1][0])
        self.assertIn(
            'metadata = "worker_heartbeats".metadata || EXCLUDED.metadata',
            worker_statement,
        )

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
