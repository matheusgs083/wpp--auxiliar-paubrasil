from __future__ import annotations

import logging
import unittest
from typing import Any
from unittest.mock import patch

from bot_api.services.promax_scheduler import PromaxScheduler


class FakeMaintenanceService:
    def __init__(self) -> None:
        self.enqueue_calls: list[int] = []
        self.reaper_calls: list[int] = []

    def enqueue_due_schedules(self, *, limit: int = 50) -> list[object]:
        self.enqueue_calls.append(limit)
        return [object(), object()]

    def reap_expired_leases(self, *, limit: int = 100) -> int:
        self.reaper_calls.append(limit)
        return 3


class FailingEnqueueMaintenanceService(FakeMaintenanceService):
    def enqueue_due_schedules(self, *, limit: int = 50) -> list[object]:
        self.enqueue_calls.append(limit)
        raise RuntimeError("enqueue failed")


class FakeThread:
    def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.alive = False
        self.join_timeouts: list[float] = []

    def start(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        if timeout is not None:
            self.join_timeouts.append(timeout)
        self.alive = False


class PromaxSchedulerTests(unittest.TestCase):
    def test_run_once_only_enqueues_due_schedules_and_reaps_leases(self) -> None:
        service = FakeMaintenanceService()
        scheduler = PromaxScheduler(
            service,
            enqueue_limit=12,
            reaper_limit=34,
        )

        result = scheduler.run_once()

        self.assertEqual(result.enqueued_jobs, 2)
        self.assertEqual(result.reaped_jobs, 3)
        self.assertEqual(service.enqueue_calls, [12])
        self.assertEqual(service.reaper_calls, [34])

    def test_start_and_stop_are_idempotent_and_use_daemon_thread(self) -> None:
        service = FakeMaintenanceService()
        created_threads: list[FakeThread] = []

        def make_thread(**kwargs: Any) -> FakeThread:
            thread = FakeThread(**kwargs)
            created_threads.append(thread)
            return thread

        with patch("bot_api.services.promax_scheduler.Thread", side_effect=make_thread):
            scheduler = PromaxScheduler(service, thread_name="promax-maintenance-test")

            self.assertTrue(scheduler.start())
            self.assertFalse(scheduler.start())
            self.assertTrue(scheduler.is_running)
            self.assertEqual(len(created_threads), 1)
            self.assertEqual(created_threads[0].name, "promax-maintenance-test")
            self.assertTrue(created_threads[0].daemon)

            self.assertTrue(scheduler.stop(timeout=1.5))
            self.assertFalse(scheduler.is_running)
            self.assertEqual(created_threads[0].join_timeouts, [1.5])
            self.assertTrue(scheduler.stop())

    def test_enqueue_failure_does_not_prevent_reaper(self) -> None:
        service = FailingEnqueueMaintenanceService()
        logger = logging.getLogger("test_promax_scheduler_failure")
        logger.disabled = True
        scheduler = PromaxScheduler(service, logger=logger)

        result = scheduler.run_once()

        self.assertEqual(result.enqueued_jobs, 0)
        self.assertEqual(result.reaped_jobs, 3)
        self.assertEqual(service.enqueue_calls, [50])
        self.assertEqual(service.reaper_calls, [100])

    def test_constructor_rejects_invalid_intervals_and_limits(self) -> None:
        service = FakeMaintenanceService()
        invalid_arguments = (
            {"enqueue_interval_seconds": 0},
            {"reaper_interval_seconds": -1},
            {"enqueue_limit": 0},
            {"reaper_limit": 0},
        )

        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    PromaxScheduler(service, **arguments)


if __name__ == "__main__":
    unittest.main()
