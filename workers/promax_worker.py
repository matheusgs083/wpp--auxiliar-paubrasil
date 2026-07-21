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
from pathlib import Path
from typing import Any, BinaryIO

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


class PromaxWorker:
    def __init__(
        self,
        *,
        config: WorkerConfig,
        client: PromaxClient,
        runner: PromaxRunner,
        catalog_provider: Callable[[], Mapping[str, Any]] | None = None,
        stop_event: threading.Event | None = None,
        logger: logging.Logger = LOGGER,
    ) -> None:
        config.validate()
        self.config = config
        self.client = client
        self.runner = runner
        self.catalog_provider = catalog_provider
        self.stop_event = stop_event or threading.Event()
        self.logger = logger
        self._pending_logs: deque[tuple[str, str, str, str, dict[str, Any]]] = deque(maxlen=2000)
        self._next_log_retry_at = 0.0
        self._last_worker_heartbeat = 0.0

    def run_forever(self) -> None:
        backoff = self.config.backoff_initial_seconds
        while not self.stop_event.is_set():
            try:
                self._heartbeat_worker(force=False)
                job = self.client.claim()
                backoff = self.config.backoff_initial_seconds
            except PromaxApiUnavailable as exc:
                self.logger.warning("Promax API indisponivel: %s", exc)
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, self.config.backoff_max_seconds)
                continue
            except PromaxClientError as exc:
                self.logger.error("Falha permanente na API do worker: %s", exc)
                self.stop_event.wait(self.config.backoff_max_seconds)
                continue

            if job is None:
                self.stop_event.wait(self.config.poll_interval_seconds)
                continue
            self._run_claimed_job(job)

    def run_once(self) -> bool:
        self._heartbeat_worker(force=True)
        job = self.client.claim()
        if job is None:
            return False
        self._run_claimed_job(job)
        return True

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

    def _heartbeat_worker(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_worker_heartbeat < self.config.heartbeat_interval_seconds:
            return
        details: dict[str, Any] = {}
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
        boleto_import_attempted = False
        while True:
            try:
                self._flush_logs()
                if not boleto_import_attempted:
                    self._import_030206_boletos_if_needed(job, job_id, lease_token, result)
                    boleto_import_attempted = True
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
        routines = _string_list(payload.get("routines"))
        if "030206_BOT" not in routines:
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


def _promax_030206_publication_dir(result_details: Mapping[str, Any] | None) -> Path | None:
    metadata = result_details.get("metadata") if isinstance(result_details, Mapping) else None
    publication_mapping = metadata.get("publication_mapping") if isinstance(metadata, Mapping) else None
    if isinstance(publication_mapping, Mapping):
        for source, destination in publication_mapping.items():
            source_text = str(source or "")
            if Path(source_text).name.casefold() == "030206 bot":
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
    if os.name != "nt":
        return open(os.devnull, "rb")
    import msvcrt

    configured_path = os.environ.get("PROMAX_WORKER_LOCK_FILE", "").strip()
    lock_path = (
        Path(configured_path)
        if configured_path
        else Path(tempfile.gettempdir()) / "bot_api_promax_worker.lock"
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


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


def redact_log_message(message: str) -> str:
    redacted = _BEARER_LOG_PATTERN.sub("Bearer [REDACTED]", str(message or ""))
    return _SENSITIVE_LOG_PATTERN.sub(r"\1\2[REDACTED]", redacted)


if __name__ == "__main__":
    raise SystemExit(main())
