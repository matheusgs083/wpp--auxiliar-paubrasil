from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Event, RLock, Thread, current_thread
from time import monotonic
from typing import Protocol


class PromaxMaintenanceService(Protocol):
    def enqueue_due_schedules(self, *, limit: int = 50) -> list[object]: ...

    def reap_expired_leases(self, *, limit: int = 100) -> int: ...


@dataclass(frozen=True)
class SchedulerRunResult:
    enqueued_jobs: int
    reaped_jobs: int


class PromaxScheduler:
    """Maintains the Promax queue without executing Promax jobs."""

    def __init__(
        self,
        service: PromaxMaintenanceService,
        *,
        enqueue_interval_seconds: float = 30.0,
        reaper_interval_seconds: float = 60.0,
        enqueue_limit: int = 50,
        reaper_limit: int = 100,
        thread_name: str = "promax-scheduler",
        logger: logging.Logger | None = None,
    ) -> None:
        if enqueue_interval_seconds <= 0:
            raise ValueError("enqueue_interval_seconds deve ser maior que zero.")
        if reaper_interval_seconds <= 0:
            raise ValueError("reaper_interval_seconds deve ser maior que zero.")
        if enqueue_limit < 1 or reaper_limit < 1:
            raise ValueError("Os limites do scheduler devem ser maiores que zero.")

        self.service = service
        self.enqueue_interval_seconds = float(enqueue_interval_seconds)
        self.reaper_interval_seconds = float(reaper_interval_seconds)
        self.enqueue_limit = int(enqueue_limit)
        self.reaper_limit = int(reaper_limit)
        self.thread_name = str(thread_name or "promax-scheduler")
        self.logger = logger or logging.getLogger(__name__)

        self._stop_event = Event()
        self._state_lock = RLock()
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            thread = Thread(target=self._run_loop, name=self.thread_name, daemon=True)
            self._thread = thread
            thread.start()
            return True

    def stop(self, *, timeout: float = 5.0) -> bool:
        if timeout < 0:
            raise ValueError("timeout nao pode ser negativo.")
        self._stop_event.set()
        with self._state_lock:
            thread = self._thread
        if thread is None:
            return True
        if thread is not current_thread() and thread.is_alive():
            thread.join(timeout=timeout)
        stopped = not thread.is_alive()
        if stopped:
            with self._state_lock:
                if self._thread is thread:
                    self._thread = None
        return stopped

    def run_once(self) -> SchedulerRunResult:
        return SchedulerRunResult(
            enqueued_jobs=self._enqueue_due_schedules(),
            reaped_jobs=self._reap_expired_leases(),
        )

    def _run_loop(self) -> None:
        next_enqueue = 0.0
        next_reaper = 0.0
        try:
            while not self._stop_event.is_set():
                now = monotonic()
                if now >= next_enqueue:
                    self._enqueue_due_schedules()
                    next_enqueue = monotonic() + self.enqueue_interval_seconds
                if self._stop_event.is_set():
                    break
                now = monotonic()
                if now >= next_reaper:
                    self._reap_expired_leases()
                    next_reaper = monotonic() + self.reaper_interval_seconds

                wait_seconds = max(
                    min(next_enqueue, next_reaper) - monotonic(),
                    0.01,
                )
                self._stop_event.wait(wait_seconds)
        finally:
            with self._state_lock:
                if self._thread is current_thread():
                    self._thread = None

    def _enqueue_due_schedules(self) -> int:
        try:
            jobs = self.service.enqueue_due_schedules(limit=self.enqueue_limit)
            return len(jobs)
        except Exception:
            self.logger.exception("Falha ao enfileirar agendas Promax vencidas.")
            return 0

    def _reap_expired_leases(self) -> int:
        try:
            return int(self.service.reap_expired_leases(limit=self.reaper_limit))
        except Exception:
            self.logger.exception("Falha ao encerrar leases Promax expirados.")
            return 0
