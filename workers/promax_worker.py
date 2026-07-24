from __future__ import annotations

import logging
import os
import re
import socket
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from .promax_client import PromaxApiUnavailable, PromaxClient, PromaxClientError, normalize_status
from .promax_catalog import discover_report_catalog
from .promax_runner import (
    PromaxRunResult,
    PromaxRunner,
    PromaxRunnerConfig,
    PromaxRunnerConfigurationError,
)


LOGGER = logging.getLogger("promax-worker")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SENSITIVE_LOG_PATTERN = re.compile(
    r"(?i)\b(password|senha|token|authorization|api[_-]?key|secret)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_LOG_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_PROMAX_030206_UNIT_FILIAL_DEFAULTS = {
    "0640001": "1",
    "0640002": "2",
    "2210003": "3",
    "2210004": "4",
    "3480005": "5",
    "3610006": "6",
    "3610007": "7",
    "3610008": "8",
}


@dataclass(frozen=True)
class WorkerConfig:
    api_url: str
    token: str
    worker_id: str
    driver_dir: str
    python_executable: str
    lease_seconds: int = 120
    http_timeout_seconds: float = 10.0
    heartbeat_interval_seconds: float = 15.0
    control_interval_seconds: float = 5.0
    poll_interval_seconds: float = 5.0
    backoff_initial_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    boleto_import_timeout_seconds: float = 120.0
    visual_lock_enabled: bool = True
    visual_lock_file: str = ""

    @classmethod
    def from_env(cls) -> WorkerConfig:
        default_driver_dir = PROJECT_ROOT.parent / "promax-web-driver"
        configured_driver_dir = Path(
            os.environ.get("PROMAX_DRIVER_DIR") or default_driver_dir
        ).expanduser()
        default_python = configured_driver_dir / "venv" / "Scripts" / "python.exe"
        if not default_python.is_file():
            default_python = configured_driver_dir / ".venv" / "Scripts" / "python.exe"
        api_url = (
            os.environ.get("PROMAX_API_BASE_URL")
            or os.environ.get("PROMAX_API_URL")
            or os.environ.get("PROMAX_WORKER_API_URL")
            or "http://127.0.0.1:8080"
        )
        boleto_import_timeout_seconds = _env_float(
            "PROMAX_WORKER_BOLETO_IMPORT_TIMEOUT_SECONDS",
            300.0,
        )
        lease_seconds = _env_int("PROMAX_WORKER_LEASE_SECONDS", 120)
        lease_seconds = max(lease_seconds, min(int(boleto_import_timeout_seconds) + 60, 3600))
        return cls(
            api_url=api_url,
            token=os.environ.get("PROMAX_WORKER_TOKEN", ""),
            worker_id=os.environ.get("PROMAX_WORKER_ID", socket.gethostname()),
            driver_dir=str(configured_driver_dir),
            python_executable=os.environ.get("PROMAX_PYTHON", str(default_python)),
            lease_seconds=lease_seconds,
            http_timeout_seconds=_env_float("PROMAX_WORKER_HTTP_TIMEOUT_SECONDS", 10.0),
            heartbeat_interval_seconds=_env_float("PROMAX_WORKER_HEARTBEAT_SECONDS", 15.0),
            control_interval_seconds=_env_float("PROMAX_WORKER_CONTROL_SECONDS", 5.0),
            poll_interval_seconds=_env_float("PROMAX_WORKER_POLL_SECONDS", 5.0),
            backoff_initial_seconds=_env_float("PROMAX_WORKER_BACKOFF_INITIAL_SECONDS", 2.0),
            backoff_max_seconds=_env_float("PROMAX_WORKER_BACKOFF_MAX_SECONDS", 60.0),
            boleto_import_timeout_seconds=boleto_import_timeout_seconds,
            visual_lock_enabled=_env_bool("PROMAX_VISUAL_LOCK_ENABLED", True),
            visual_lock_file=os.environ.get("PROMAX_VISUAL_LOCK_FILE", ""),
        )

    def validate(self) -> None:
        if self.lease_seconds < 15 or self.lease_seconds > 3600:
            raise ValueError("PROMAX_WORKER_LEASE_SECONDS must be between 15 and 3600.")
        if self.boleto_import_timeout_seconds <= 0:
            raise ValueError("PROMAX_WORKER_BOLETO_IMPORT_TIMEOUT_SECONDS must be positive.")
        if self.boleto_import_timeout_seconds > self.lease_seconds:
            raise ValueError(
                "PROMAX_WORKER_BOLETO_IMPORT_TIMEOUT_SECONDS must not exceed the active job lease."
            )
        if self.poll_interval_seconds <= 0:
            raise ValueError("PROMAX_WORKER_POLL_SECONDS must be positive.")
        if self.backoff_initial_seconds <= 0:
            raise ValueError("PROMAX_WORKER_BACKOFF_INITIAL_SECONDS must be positive.")
        if self.backoff_max_seconds < self.backoff_initial_seconds:
            raise ValueError(
                "PROMAX_WORKER_BACKOFF_MAX_SECONDS must be at least the initial backoff."
            )


class VisualAutomationLock(Protocol):
    def acquire(self, metadata: Mapping[str, Any] | None = None) -> bool:
        ...

    def release(self) -> None:
        ...


class PromaxVisualAutomationLock:
    def __init__(self, *, path: str = "", enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self.path = _resolve_lock_path(path, filename="promax_visual.lock")
        self._handle: BinaryIO | None = None

    def acquire(self, metadata: Mapping[str, Any] | None = None) -> bool:
        if not self.enabled:
            return True
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if not _try_lock_first_byte(handle):
            handle.close()
            return False
        self._handle = handle
        self._write_metadata(metadata)
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            handle.seek(0)
            _unlock_first_byte(handle)
        finally:
            handle.close()

    def _write_metadata(self, metadata: Mapping[str, Any] | None) -> None:
        if self._handle is None:
            return
        payload = {
            "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **dict(metadata or {}),
        }
        text = (str(payload) + "\n").encode("utf-8", errors="replace")
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(text or b"0")
        self._handle.flush()
        self._handle.seek(0)


class PromaxWorker:
    def __init__(
        self,
        *,
        config: WorkerConfig,
        client: PromaxClient,
        runner: PromaxRunner,
        catalog_provider: Callable[[], Mapping[str, Any]] | None = None,
        visual_lock: VisualAutomationLock | None = None,
        stop_event: threading.Event | None = None,
        logger: logging.Logger = LOGGER,
    ) -> None:
        config.validate()
        self.config = config
        self.client = client
        self.runner = runner
        self.catalog_provider = catalog_provider
        self.visual_lock = visual_lock or PromaxVisualAutomationLock(
            path=config.visual_lock_file,
            enabled=config.visual_lock_enabled,
        )
        self.stop_event = stop_event or threading.Event()
        self.logger = logger
        self._pending_logs: deque[tuple[str, str, str, str, dict[str, Any]]] = deque(maxlen=2000)
        self._next_log_retry_at = 0.0
        self._last_worker_heartbeat = 0.0
        self._last_visual_lock_wait_log = 0.0

    def run_forever(self) -> None:
        backoff = self.config.backoff_initial_seconds
        while not self.stop_event.is_set():
            if not self._acquire_visual_lock_for_claim():
                self.stop_event.wait(self.config.poll_interval_seconds)
                continue
            try:
                self._heartbeat_worker(force=False)
                job = self.client.claim()
                backoff = self.config.backoff_initial_seconds
            except PromaxApiUnavailable as exc:
                self._release_visual_lock()
                self.logger.warning("Promax API indisponivel: %s", exc)
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, self.config.backoff_max_seconds)
                continue
            except PromaxClientError as exc:
                self._release_visual_lock()
                self.logger.error("Falha permanente na API do worker: %s", exc)
                self.stop_event.wait(self.config.backoff_max_seconds)
                continue
            except Exception:
                self._release_visual_lock()
                raise

            if job is None:
                self._release_visual_lock()
                self.stop_event.wait(self.config.poll_interval_seconds)
                continue
            try:
                self._run_claimed_job(job)
            finally:
                self._release_visual_lock()

    def run_once(self) -> bool:
        if not self._acquire_visual_lock_for_claim():
            return False
        self._heartbeat_worker(force=True)
        try:
            job = self.client.claim()
            if job is None:
                return False
            self._run_claimed_job(job)
            return True
        finally:
            self._release_visual_lock()

    def _acquire_visual_lock_for_claim(self) -> bool:
        metadata = {
            "worker_id": self.config.worker_id,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "phase": "claim",
        }
        try:
            acquired = self.visual_lock.acquire(metadata)
        except OSError as exc:
            self.logger.warning("Nao consegui criar trava local Promax; worker aguardara: %s", exc)
            return False
        if acquired:
            return True
        now = time.monotonic()
        if now - self._last_visual_lock_wait_log >= 60:
            self.logger.info("Automacao Promax visual ja esta em uso nesta maquina; aguardando liberar.")
            self._heartbeat_visual_lock_wait()
            self._last_visual_lock_wait_log = now
        return False

    def _release_visual_lock(self) -> None:
        try:
            self.visual_lock.release()
        except OSError as exc:
            self.logger.warning("Falha ao liberar trava local Promax: %s", exc)

    def _heartbeat_visual_lock_wait(self) -> None:
        lock_path = getattr(self.visual_lock, "path", "")
        try:
            self._heartbeat_worker(
                force=True,
                extra_details={
                    "visual_lock": {
                        "state": "busy",
                        "path": str(lock_path) if lock_path else "",
                    }
                },
            )
        except PromaxClientError as exc:
            self.logger.debug("Heartbeat de espera da trava visual rejeitado: %s", exc)

    def _run_claimed_job(self, job: Mapping[str, Any]) -> None:
        job_id = _job_id(job)
        lease_token = _job_lease_token(job)
        self.logger.info("Executando job Promax %s.", job_id)
        try:
            result = self.runner.run(
                job,
                on_line=lambda stream, line: self._send_log(
                    job_id,
                    lease_token,
                    line,
                    "error" if stream == "stderr" else "info",
                    {"stream": stream},
                ),
                heartbeat=lambda: self._heartbeat_active_job(job_id, lease_token),
                cancel_requested=lambda: self._control_requested(job_id, "cancel_requested"),
                stop_requested=lambda: self.stop_event.is_set(),
            )
        except (OSError, RuntimeError, ValueError, PromaxRunnerConfigurationError) as exc:
            self.logger.exception("Falha ao executar job Promax %s.", job_id)
            result = PromaxRunResult(
                status="failed",
                return_code=-1,
                child_pid=0,
                error=str(exc),
                message=f"Falha ao iniciar a execucao Promax: {exc}",
            )

        final_level = (
            "error"
            if result.status == "failed"
            else "warning"
            if result.status == "partial_success"
            else "info"
        )
        self._send_log(
            job_id,
            lease_token,
            f"Resultado final: {result.message or result.status}",
            final_level,
            {
                "event": "job_result",
                "status": result.status,
                "return_code": result.return_code,
            },
        )
        self._finish_with_retry(job, job_id, lease_token, result)
        self.logger.info("Job Promax %s finalizado com status %s.", job_id, result.status)

    def _heartbeat_active_job(self, job_id: str, lease_token: str) -> None:
        try:
            self._flush_logs()
            self.client.heartbeat_job(job_id, lease_token)
        except PromaxApiUnavailable as exc:
            self.logger.warning("Heartbeat temporariamente indisponivel para job %s: %s", job_id, exc)
        except PromaxClientError as exc:
            self.logger.error("Heartbeat rejeitado para job %s: %s", job_id, exc)

    def _heartbeat_worker(self, *, force: bool, extra_details: Mapping[str, Any] | None = None) -> None:
        now = time.monotonic()
        if not force and now - self._last_worker_heartbeat < self.config.heartbeat_interval_seconds:
            return
        details: dict[str, Any] = dict(extra_details or {})
        if self.catalog_provider is not None:
            try:
                details["catalog"] = dict(self.catalog_provider())
            except (OSError, SyntaxError, ValueError) as exc:
                self.logger.warning("Catalogo dinamico Promax indisponivel: %s", exc)
        self.client.heartbeat(status="idle", details=details)
        self._last_worker_heartbeat = now

    def _control_requested(self, job_id: str, key: str) -> bool:
        try:
            payload = self.client.control(job_id)
        except PromaxApiUnavailable as exc:
            self.logger.warning("Controle temporariamente indisponivel para job %s: %s", job_id, exc)
            return False
        except PromaxClientError as exc:
            self.logger.error("Controle rejeitado para job %s: %s", job_id, exc)
            return False
        return _control_flag(payload, key=key, job_id=job_id)

    def _send_log(
        self,
        job_id: str,
        lease_token: str,
        message: str,
        level: str,
        data: Mapping[str, Any],
    ) -> None:
        clean_message = redact_log_message(str(message or "").rstrip("\r\n")) or " "
        for offset in range(0, len(clean_message), 8000):
            self._send_log_entry(
                job_id,
                lease_token,
                clean_message[offset : offset + 8000],
                level,
                data,
            )

    def _send_log_entry(
        self,
        job_id: str,
        lease_token: str,
        message: str,
        level: str,
        data: Mapping[str, Any],
    ) -> None:
        clean_message = str(message)
        if not clean_message:
            return
        entry = (job_id, lease_token, clean_message, level, dict(data))
        if self._pending_logs and time.monotonic() < self._next_log_retry_at:
            self._pending_logs.append(entry)
            return
        try:
            self._flush_logs()
            self.client.log(job_id, lease_token, clean_message, level=level, data=data)
        except PromaxApiUnavailable:
            self._pending_logs.append(entry)
            self._next_log_retry_at = time.monotonic() + self.config.backoff_initial_seconds
        except PromaxClientError as exc:
            self.logger.error("Log rejeitado para job %s: %s", job_id, exc)

    def _flush_logs(self) -> None:
        while self._pending_logs:
            job_id, lease_token, message, level, data = self._pending_logs[0]
            try:
                self.client.log(job_id, lease_token, message, level=level, data=data)
            except PromaxApiUnavailable:
                raise
            except PromaxClientError as exc:
                self.logger.error("Log pendente rejeitado para job %s: %s", job_id, exc)
            self._pending_logs.popleft()
        self._next_log_retry_at = 0.0

    def _finish_with_retry(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
    ) -> None:
        backoff = self.config.backoff_initial_seconds
        post_import_attempted = False
        while True:
            try:
                self._flush_logs()
                if not post_import_attempted:
                    self._import_030206_boletos_if_needed(job, job_id, lease_token, result)
                    self._import_020304_estoque_if_needed(job, job_id, lease_token, result)
                    self._import_120601_inadimplencia_if_needed(job, job_id, lease_token, result)
                    self._import_020220_comodatos_if_needed(job, job_id, lease_token, result)
                    self._import_0105070402_dclientes_if_needed(job, job_id, lease_token, result)
                    self._import_030111_critica_if_needed(job, job_id, lease_token, result)
                    post_import_attempted = True
                self.client.finish(
                    job_id,
                    lease_token,
                    status=result.status,
                    result={
                        **dict(result.details or {}),
                        "return_code": result.return_code,
                        "child_pid": result.child_pid or None,
                        "message": result.message or "",
                    },
                    error=result.error,
                )
                return
            except PromaxApiUnavailable as exc:
                self.logger.warning("API indisponivel ao finalizar job %s: %s", job_id, exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, self.config.backoff_max_seconds)
            except PromaxClientError as exc:
                self.logger.error("Finalizacao rejeitada para job %s: %s", job_id, exc)
                return

    def _import_030206_boletos_if_needed(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
    ) -> None:
        if normalize_status(result.status) not in {"success", "partial_success"}:
            return
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        if not _routine_selected(payload, "030206_BOT"):
            return
        if payload.get("publish", True) is False:
            return

        requested_units = _string_list(payload.get("units"))
        unit_filial_map = _promax_030206_unit_filial_map()
        source_dir = _promax_030206_publication_dir(result.details)
        if source_dir is None:
            self._send_log(
                job_id,
                lease_token,
                (
                    "Importacao automatica 030206 ignorada: o driver nao informou "
                    "a pasta publicada em metadata.publication_mapping."
                ),
                "warning",
                {"event": "promax_030206_auto_import_missing_publication_mapping"},
            )
            return
        if not source_dir.is_dir():
            self._send_log(
                job_id,
                lease_token,
                f"Importacao automatica 030206 ignorada: pasta nao encontrada {source_dir}",
                "warning",
                {"event": "promax_030206_auto_import_missing_dir", "source_dir": str(source_dir)},
            )
            return
        units = requested_units or [
            match.group(1)
            for pdf_path in source_dir.glob("03,02,06_*.pdf")
            if (match := re.fullmatch(r"03,02,06_([A-Za-z0-9_.-]+)\.pdf", pdf_path.name))
        ]

        imported = 0
        missing: list[str] = []
        failed: list[str] = []
        for unit in units:
            filial = unit_filial_map.get(unit)
            if not filial:
                continue
            pdf_path = source_dir / f"03,02,06_{unit}.pdf"
            if not pdf_path.is_file():
                missing.append(unit)
                continue
            try:
                self._heartbeat_active_job(job_id, lease_token)
                response = self.client.import_boleto_pdf(
                    job_id=job_id,
                    lease_token=lease_token,
                    filial=filial,
                    filename=pdf_path.name,
                    pdf_bytes=pdf_path.read_bytes(),
                    reference_date=str(payload.get("end_date") or payload.get("start_date") or "") or None,
                )
                self._heartbeat_active_job(job_id, lease_token)
                result_payload = response.get("result") if isinstance(response, Mapping) else None
                imported += 1
                self._send_log(
                    job_id,
                    lease_token,
                    (
                        "Boletos 030206 importados automaticamente para filial "
                        f"{filial}: {pdf_path.name}"
                    ),
                    "info",
                    {
                        "event": "promax_030206_auto_import_uploaded",
                        "filial": filial,
                        "unit": unit,
                        "filename": pdf_path.name,
                        "result": result_payload if isinstance(result_payload, Mapping) else {},
                    },
                )
            except (OSError, PromaxClientError, ValueError) as exc:
                failed.append(unit)
                self._send_log(
                    job_id,
                    lease_token,
                    f"Falha na importacao automatica 030206 da unidade {unit}: {exc}",
                    "error",
                    {"event": "promax_030206_auto_import_failed", "unit": unit, "filial": filial},
                )

        if missing:
            self._send_log(
                job_id,
                lease_token,
                "Importacao automatica 030206 sem PDF para unidade(s): " + ", ".join(missing),
                "warning",
                {"event": "promax_030206_auto_import_missing_files", "units": missing},
            )
        self._send_log(
            job_id,
            lease_token,
            f"Importacao automatica 030206 finalizada: {imported} arquivo(s), {len(failed)} falha(s).",
            "info" if not failed else "warning",
            {
                "event": "promax_030206_auto_import_summary",
                "imported": imported,
                "failed_units": failed,
                "missing_units": missing,
            },
        )

    def _import_020304_estoque_if_needed(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
    ) -> None:
        if normalize_status(result.status) not in {"success", "partial_success"}:
            return
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        if not _routine_selected(payload, "020304_BOT"):
            return
        if payload.get("publish", True) is False:
            return

        requested_units = _string_list(payload.get("units"))
        unit_filial_map = _promax_020304_unit_filial_map()
        source_dir = _promax_publication_dir(result.details, "020304 bot")
        if source_dir is None:
            self._send_log(
                job_id,
                lease_token,
                (
                    "Importacao automatica 020304_BOT ignorada: o driver nao informou "
                    "a pasta publicada em metadata.publication_mapping."
                ),
                "warning",
                {"event": "promax_020304_auto_import_missing_publication_mapping"},
            )
            return
        if not source_dir.is_dir():
            self._send_log(
                job_id,
                lease_token,
                f"Importacao automatica 020304_BOT ignorada: pasta nao encontrada {source_dir}",
                "warning",
                {"event": "promax_020304_auto_import_missing_dir", "source_dir": str(source_dir)},
            )
            return

        if requested_units:
            units = requested_units
        else:
            units = _discover_promax_units_from_files(source_dir, unit_filial_map=unit_filial_map, suffix=".csv")

        imported = 0
        missing: list[str] = []
        failed: list[str] = []
        for unit in units:
            filial = unit_filial_map.get(unit)
            if not filial:
                continue
            csv_path = _find_promax_020304_csv(source_dir, unit)
            if csv_path is None:
                missing.append(unit)
                continue
            try:
                self._heartbeat_active_job(job_id, lease_token)
                response = self.client.import_estoque_020304_csv(
                    job_id=job_id,
                    lease_token=lease_token,
                    filial=filial,
                    filename=csv_path.name,
                    csv_bytes=csv_path.read_bytes(),
                    reference_date=str(payload.get("end_date") or payload.get("start_date") or "") or None,
                )
                self._heartbeat_active_job(job_id, lease_token)
                result_payload = response.get("result") if isinstance(response, Mapping) else None
                imported += 1
                self._send_log(
                    job_id,
                    lease_token,
                    f"Estoque 020304_BOT importado automaticamente para filial {filial}: {csv_path.name}",
                    "info",
                    {
                        "event": "promax_020304_auto_import_uploaded",
                        "filial": filial,
                        "unit": unit,
                        "filename": csv_path.name,
                        "result": result_payload if isinstance(result_payload, Mapping) else {},
                    },
                )
            except (OSError, PromaxClientError, ValueError) as exc:
                failed.append(unit)
                self._send_log(
                    job_id,
                    lease_token,
                    f"Falha na importacao automatica 020304_BOT da unidade {unit}: {exc}",
                    "error",
                    {"event": "promax_020304_auto_import_failed", "unit": unit, "filial": filial},
                )

        if missing:
            self._send_log(
                job_id,
                lease_token,
                "Importacao automatica 020304_BOT sem CSV para unidade(s): " + ", ".join(missing),
                "warning",
                {"event": "promax_020304_auto_import_missing_files", "units": missing},
            )
        self._send_log(
            job_id,
            lease_token,
            f"Importacao automatica 020304_BOT finalizada: {imported} arquivo(s), {len(failed)} falha(s).",
            "info" if not failed else "warning",
            {
                "event": "promax_020304_auto_import_summary",
                "imported": imported,
                "failed_units": failed,
                "missing_units": missing,
            },
        )

    def _import_120601_inadimplencia_if_needed(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
    ) -> None:
        if normalize_status(result.status) not in {"success", "partial_success"}:
            return
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        if not _routine_selected(payload, "120601_BOT"):
            return
        if payload.get("publish", True) is False:
            return

        source_dir = _promax_publication_dir(result.details, "120601 bot")
        if source_dir is None:
            self._send_log(
                job_id,
                lease_token,
                (
                    "Importacao automatica 120601_BOT ignorada: o driver nao informou "
                    "a pasta publicada em metadata.publication_mapping."
                ),
                "warning",
                {"event": "promax_120601_auto_import_missing_publication_mapping"},
            )
            return
        if not source_dir.is_dir():
            self._send_log(
                job_id,
                lease_token,
                f"Importacao automatica 120601_BOT ignorada: pasta nao encontrada {source_dir}",
                "warning",
                {"event": "promax_120601_auto_import_missing_dir", "source_dir": str(source_dir)},
            )
            return

        csv_paths = sorted(
            path
            for path in source_dir.glob("*.csv")
            if path.is_file() and not path.name.startswith(".")
        )
        if not csv_paths:
            self._send_log(
                job_id,
                lease_token,
                f"Importacao automatica 120601_BOT ignorada: nenhum CSV encontrado em {source_dir}",
                "warning",
                {"event": "promax_120601_auto_import_no_files", "source_dir": str(source_dir)},
            )
            return

        try:
            self._heartbeat_active_job(job_id, lease_token)
            response = self.client.import_inadimplencia_csvs(
                job_id=job_id,
                lease_token=lease_token,
                files={path.name: path.read_bytes() for path in csv_paths},
                reference_date=str(payload.get("end_date") or payload.get("start_date") or "") or None,
            )
            self._heartbeat_active_job(job_id, lease_token)
            result_payload = response.get("result") if isinstance(response, Mapping) else None
            rows = result_payload.get("rows") if isinstance(result_payload, Mapping) else None
            batch_id = result_payload.get("batch_id") if isinstance(result_payload, Mapping) else None
            self._send_log(
                job_id,
                lease_token,
                (
                    "Inadimplencia 120601_BOT importada automaticamente: "
                    f"{len(csv_paths)} arquivo(s), {rows or 0} linha(s)."
                ),
                "info",
                {
                    "event": "promax_120601_auto_import_success",
                    "file_count": len(csv_paths),
                    "files": [path.name for path in csv_paths],
                    "rows": rows,
                    "batch_id": batch_id,
                },
            )
        except (OSError, PromaxClientError, ValueError) as exc:
            self._send_log(
                job_id,
                lease_token,
                f"Falha na importacao automatica 120601_BOT: {exc}",
                "error",
                {"event": "promax_120601_auto_import_failed", "file_count": len(csv_paths)},
            )

    def _import_020220_comodatos_if_needed(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
    ) -> None:
        self._import_csv_folder_if_needed(
            job,
            job_id,
            lease_token,
            result,
            routine_id="020220_BOT",
            folder_name="020220 bot",
            label="Comodatos 020220_BOT",
            event_prefix="promax_020220_auto_import",
            importer=lambda files, reference_date: self.client.import_comodatos_csvs(
                job_id=job_id,
                lease_token=lease_token,
                files=files,
                reference_date=reference_date,
            ),
        )

    def _import_0105070402_dclientes_if_needed(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
    ) -> None:
        def import_dclientes(files: Mapping[str, bytes], reference_date: str | None) -> dict[str, Any]:
            filename, file_bytes = next(iter(files.items()))
            return self.client.import_dclientes_csv(
                job_id=job_id,
                lease_token=lease_token,
                filename=filename,
                csv_bytes=file_bytes,
                reference_date=reference_date,
            )

        self._import_csv_folder_if_needed(
            job,
            job_id,
            lease_token,
            result,
            routine_id="0105070402_BOT",
            folder_name="0105070402 bot",
            label="dClientes 0105070402_BOT",
            event_prefix="promax_0105070402_auto_import",
            importer=import_dclientes,
            single_latest_file=True,
        )

    def _import_030111_critica_if_needed(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
    ) -> None:
        if normalize_status(result.status) not in {"success", "partial_success"}:
            return
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        if not _routine_selected(payload, "030111_BOT"):
            return
        if payload.get("publish", True) is False:
            return

        requested_units = _string_list(payload.get("units"))
        unit_filial_map = _promax_020304_unit_filial_map()
        source_dir = _promax_publication_dir(result.details, "030111 bot")
        if source_dir is None:
            self._send_log(
                job_id,
                lease_token,
                (
                    "Importacao automatica 030111_BOT ignorada: o driver nao informou "
                    "a pasta publicada em metadata.publication_mapping."
                ),
                "warning",
                {"event": "promax_030111_auto_import_missing_publication_mapping"},
            )
            return
        if not source_dir.is_dir():
            self._send_log(
                job_id,
                lease_token,
                f"Importacao automatica 030111_BOT ignorada: pasta nao encontrada {source_dir}",
                "warning",
                {"event": "promax_030111_auto_import_missing_dir", "source_dir": str(source_dir)},
            )
            return

        units = requested_units or _discover_promax_units_from_files(
            source_dir,
            unit_filial_map=unit_filial_map,
            suffix=".csv",
        )

        imported = 0
        missing: list[str] = []
        failed: list[str] = []
        for unit in units:
            filial = unit_filial_map.get(unit)
            if not filial:
                continue
            csv_path = _find_promax_csv_by_unit(
                source_dir,
                unit,
                preferred_tokens=("030111", "30111", "critica"),
            )
            if csv_path is None:
                missing.append(unit)
                continue
            try:
                reference_date = str(payload.get("end_date") or payload.get("start_date") or "") or None
                self._heartbeat_active_job(job_id, lease_token)
                response = self.client.import_critica_csvs(
                    job_id=job_id,
                    lease_token=lease_token,
                    files={csv_path.name: csv_path.read_bytes()},
                    reference_date=reference_date,
                )
                self._heartbeat_active_job(job_id, lease_token)
                result_payload = response.get("result") if isinstance(response, Mapping) else None
                imported += 1
                self._send_log(
                    job_id,
                    lease_token,
                    f"Critica 030111_BOT importada automaticamente para filial {filial}: {csv_path.name}",
                    "info",
                    {
                        "event": "promax_030111_auto_import_uploaded",
                        "filial": filial,
                        "unit": unit,
                        "filename": csv_path.name,
                        "result": result_payload if isinstance(result_payload, Mapping) else {},
                    },
                )
            except (OSError, PromaxClientError, ValueError) as exc:
                failed.append(unit)
                self._send_log(
                    job_id,
                    lease_token,
                    f"Falha na importacao automatica 030111_BOT da unidade {unit}: {exc}",
                    "error",
                    {"event": "promax_030111_auto_import_failed", "unit": unit, "filial": filial},
                )

        if missing:
            self._send_log(
                job_id,
                lease_token,
                "Importacao automatica 030111_BOT sem CSV para unidade(s): " + ", ".join(missing),
                "warning",
                {"event": "promax_030111_auto_import_missing_files", "units": missing},
            )
        self._send_log(
            job_id,
            lease_token,
            f"Importacao automatica 030111_BOT finalizada: {imported} arquivo(s), {len(failed)} falha(s).",
            "info" if not failed else "warning",
            {
                "event": "promax_030111_auto_import_summary",
                "imported": imported,
                "failed_units": failed,
                "missing_units": missing,
            },
        )

    def _import_csv_folder_if_needed(
        self,
        job: Mapping[str, Any],
        job_id: str,
        lease_token: str,
        result: PromaxRunResult,
        *,
        routine_id: str,
        folder_name: str,
        label: str,
        event_prefix: str,
        importer: Callable[[Mapping[str, bytes], str | None], Mapping[str, Any]],
        single_latest_file: bool = False,
    ) -> None:
        if normalize_status(result.status) not in {"success", "partial_success"}:
            return
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            payload = {}
        if not _routine_selected(payload, routine_id):
            return
        if payload.get("publish", True) is False:
            return

        source_dir = _promax_publication_dir(result.details, folder_name)
        if source_dir is None:
            self._send_log(
                job_id,
                lease_token,
                (
                    f"Importacao automatica {routine_id} ignorada: o driver nao informou "
                    "a pasta publicada em metadata.publication_mapping."
                ),
                "warning",
                {"event": f"{event_prefix}_missing_publication_mapping"},
            )
            return
        if not source_dir.is_dir():
            self._send_log(
                job_id,
                lease_token,
                f"Importacao automatica {routine_id} ignorada: pasta nao encontrada {source_dir}",
                "warning",
                {"event": f"{event_prefix}_missing_dir", "source_dir": str(source_dir)},
            )
            return

        csv_paths = sorted(
            (path for path in source_dir.glob("*.csv") if path.is_file() and not path.name.startswith(".")),
            key=lambda path: (path.stat().st_mtime, path.name),
        )
        if single_latest_file and csv_paths:
            csv_paths = [csv_paths[-1]]
        if not csv_paths:
            self._send_log(
                job_id,
                lease_token,
                f"Importacao automatica {routine_id} ignorada: nenhum CSV encontrado em {source_dir}",
                "warning",
                {"event": f"{event_prefix}_no_files", "source_dir": str(source_dir)},
            )
            return

        try:
            reference_date = str(payload.get("end_date") or payload.get("start_date") or "") or None
            self._heartbeat_active_job(job_id, lease_token)
            response = importer({path.name: path.read_bytes() for path in csv_paths}, reference_date)
            self._heartbeat_active_job(job_id, lease_token)
            result_payload = response.get("result") if isinstance(response, Mapping) else None
            rows = result_payload.get("rows") if isinstance(result_payload, Mapping) else None
            batch_id = result_payload.get("batch_id") if isinstance(result_payload, Mapping) else None
            self._send_log(
                job_id,
                lease_token,
                f"{label} importado automaticamente: {len(csv_paths)} arquivo(s), {rows or 0} linha(s).",
                "info",
                {
                    "event": f"{event_prefix}_success",
                    "file_count": len(csv_paths),
                    "files": [path.name for path in csv_paths],
                    "rows": rows,
                    "batch_id": batch_id,
                },
            )
        except (OSError, PromaxClientError, ValueError) as exc:
            self._send_log(
                job_id,
                lease_token,
                f"Falha na importacao automatica {routine_id}: {exc}",
                "error",
                {"event": f"{event_prefix}_failed", "file_count": len(csv_paths)},
            )


def build_worker(config: WorkerConfig) -> PromaxWorker:
    config.validate()
    client = PromaxClient(
        base_url=config.api_url,
        token=config.token,
        worker_id=config.worker_id,
        lease_seconds=config.lease_seconds,
        timeout_seconds=config.http_timeout_seconds,
        boleto_import_timeout_seconds=config.boleto_import_timeout_seconds,
    )
    runner_config = PromaxRunnerConfig.from_values(
        driver_dir=config.driver_dir,
        python_executable=config.python_executable,
        heartbeat_interval_seconds=config.heartbeat_interval_seconds,
        control_interval_seconds=config.control_interval_seconds,
    )
    return PromaxWorker(
        config=config,
        client=client,
        runner=PromaxRunner(runner_config),
        catalog_provider=lambda: discover_report_catalog(config.driver_dir),
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _routine_selected(payload: Mapping[str, Any], routine_id: str) -> bool:
    routines = _string_list(payload.get("routines"))
    if not routines:
        return False

    target = _normalize_routine_id(routine_id)
    target_base = target.removesuffix("_BOT")
    accepted = {target}
    if target_base:
        accepted.add(target_base)
        accepted.add(f"{target_base}_BOT")

    return any(_normalize_routine_id(routine) in accepted for routine in routines)


def _normalize_routine_id(value: Any) -> str:
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _promax_030206_unit_filial_map() -> dict[str, str]:
    mapping = dict(_PROMAX_030206_UNIT_FILIAL_DEFAULTS)
    raw_value = os.environ.get("PROMAX_030206_UNIT_FILIAL_MAP", "")
    for chunk in raw_value.split(","):
        if ":" not in chunk:
            continue
        unit, filial = (part.strip() for part in chunk.split(":", 1))
        if unit and filial:
            mapping[unit] = filial
    return mapping


def _promax_020304_unit_filial_map() -> dict[str, str]:
    mapping = dict(_PROMAX_030206_UNIT_FILIAL_DEFAULTS)
    for env_name in ("PROMAX_UNIT_FILIAL_MAP", "PROMAX_020304_UNIT_FILIAL_MAP"):
        raw_value = os.environ.get(env_name, "")
        for chunk in raw_value.split(","):
            if ":" not in chunk:
                continue
            unit, filial = (part.strip() for part in chunk.split(":", 1))
            if unit and filial:
                mapping[unit] = filial
    return mapping


def _promax_030206_publication_dir(result_details: Mapping[str, Any] | None) -> Path | None:
    return _promax_publication_dir(result_details, "030206 bot")


def _discover_promax_units_from_files(source_dir: Path, *, unit_filial_map: Mapping[str, str], suffix: str) -> list[str]:
    units: list[str] = []
    seen: set[str] = set()
    suffix_text = str(suffix or "").casefold()
    for path in sorted(source_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.name.startswith(".") or path.suffix.casefold() != suffix_text:
            continue
        name = path.name
        for unit in unit_filial_map:
            if unit in name and unit not in seen:
                seen.add(unit)
                units.append(unit)
                break
    return units


def _find_promax_020304_csv(source_dir: Path, unit: str) -> Path | None:
    return _find_promax_csv_by_unit(
        source_dir,
        unit,
        preferred_tokens=("020304", "20304", "estoque"),
    )


def _find_promax_csv_by_unit(
    source_dir: Path,
    unit: str,
    *,
    preferred_tokens: Sequence[str] = (),
) -> Path | None:
    unit_text = str(unit or "").strip()
    if not unit_text:
        return None
    tokens = tuple(str(token or "").casefold() for token in preferred_tokens if str(token or "").strip())
    candidates = [
        path
        for path in source_dir.glob("*.csv")
        if path.is_file() and not path.name.startswith(".") and unit_text in path.name
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda path: (
            _promax_filename_score(path.name, preferred_tokens=tokens),
            path.stat().st_mtime,
            path.name,
        ),
    )[-1]


def _promax_filename_score(name: str, *, preferred_tokens: Sequence[str] = ()) -> int:
    normalized = str(name or "").casefold().replace(".", "").replace(",", "").replace("_", "")
    if any(token and token in normalized for token in preferred_tokens):
        return 3
    return 1


def _promax_publication_dir(result_details: Mapping[str, Any] | None, folder_name: str) -> Path | None:
    metadata = result_details.get("metadata") if isinstance(result_details, Mapping) else None
    publication_mapping = metadata.get("publication_mapping") if isinstance(metadata, Mapping) else None
    if isinstance(publication_mapping, Mapping):
        for source, destination in publication_mapping.items():
            source_text = str(source or "")
            if Path(source_text).name.casefold() == folder_name.casefold():
                destination_text = str(destination or "").strip()
                if destination_text:
                    return Path(destination_text)
    return None


def load_project_env(project_root: Path = PROJECT_ROOT) -> Path | None:
    configured_path = os.environ.get("BOT_ENV_FILE", ".env").strip() or ".env"
    env_path = Path(configured_path).expanduser()
    if not env_path.is_absolute():
        env_path = project_root / env_path
    if not env_path.is_file():
        return None

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].lstrip()
        name, value = line.split("=", 1)
        name = name.strip()
        if not _ENV_NAME_PATTERN.fullmatch(name):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(name, value)
    return env_path


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("PROMAX_WORKER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    load_project_env()
    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        LOGGER.info("Outro worker Promax ja esta em execucao.")
        return 0
    try:
        worker = build_worker(WorkerConfig.from_env())
    except (OSError, ValueError) as exc:
        LOGGER.error("Configuracao invalida do worker Promax: %s", exc)
        return 2

    try:
        worker.run_forever()
    except KeyboardInterrupt:
        LOGGER.info("Worker Promax interrompido.")
    return 0


def acquire_single_instance_lock() -> BinaryIO | None:
    configured_path = os.environ.get("PROMAX_WORKER_LOCK_FILE", "").strip()
    lock_path = _resolve_lock_path(configured_path, filename="promax_worker.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if not _try_lock_first_byte(handle):
        handle.close()
        return None
    return handle


def _resolve_lock_path(configured_path: str, *, filename: str) -> Path:
    if configured_path.strip():
        return Path(configured_path).expanduser()
    candidates: list[Path] = []
    for env_name in ("PROGRAMDATA", "LOCALAPPDATA"):
        base = os.environ.get(env_name, "").strip()
        if base:
            candidates.append(Path(base) / "bot_api" / "locks" / filename)
    candidates.append(Path(tempfile.gettempdir()) / f"bot_api_{filename}")
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path(tempfile.gettempdir()) / f"bot_api_{filename}"


def _try_lock_first_byte(handle: BinaryIO) -> bool:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock_first_byte(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _job_id(job: Mapping[str, Any]) -> str:
    value = job.get("job_id") or job.get("id")
    job_id = str(value or "").strip()
    if not job_id:
        raise ValueError("Claimed Promax job does not contain job_id.")
    return job_id


def _job_profile(job: Mapping[str, Any]) -> str:
    candidates: list[object] = [
        job.get("profile"),
        job.get("perfil"),
        job.get("profile_path"),
        job.get("perfil_path"),
        job.get("category"),
    ]
    payload = job.get("payload")
    if isinstance(payload, Mapping):
        candidates.extend(
            [
                payload.get("profile"),
                payload.get("perfil"),
                payload.get("profile_path"),
                payload.get("perfil_path"),
                payload.get("category"),
            ]
        )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    raise ValueError("Claimed Promax job does not contain a profile.")


def _job_lease_token(job: Mapping[str, Any]) -> str:
    lease_token = str(job.get("lease_token") or "").strip()
    if not lease_token:
        raise ValueError("Claimed Promax job does not contain lease_token.")
    return lease_token


def _control_flag(payload: Mapping[str, Any], *, key: str, job_id: str) -> bool:
    if key == "cancel_requested":
        stop_job_ids = payload.get("stop_job_ids")
        if isinstance(stop_job_ids, (list, tuple, set, frozenset)):
            if job_id in {str(value or "").strip() for value in stop_job_ids}:
                return True

    candidates: list[Mapping[str, Any]] = [payload]
    nested_control = payload.get("control")
    if isinstance(nested_control, Mapping):
        candidates.append(nested_control)
        stop_job_ids = nested_control.get("stop_job_ids")
        if key == "cancel_requested" and isinstance(
            stop_job_ids,
            (list, tuple, set, frozenset),
        ):
            if job_id in {str(value or "").strip() for value in stop_job_ids}:
                return True
    active_job = payload.get("job") or payload.get("active_job")
    if isinstance(active_job, Mapping):
        candidates.append(active_job)

    for candidate in candidates:
        candidate_job_id = str(candidate.get("job_id") or candidate.get("id") or "").strip()
        if candidate_job_id and candidate_job_id != job_id:
            continue
        if candidate.get(key) is True:
            return True
    return False


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _env_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric.") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "sim", "on"}:
        return True
    if normalized in {"0", "false", "no", "nao", "não", "off"}:
        return False
    raise ValueError(f"{name} must be boolean.")


def redact_log_message(message: str) -> str:
    redacted = _BEARER_LOG_PATTERN.sub("Bearer [REDACTED]", str(message or ""))
    return _SENSITIVE_LOG_PATTERN.sub(r"\1\2[REDACTED]", redacted)


if __name__ == "__main__":
    raise SystemExit(main())
