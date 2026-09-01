from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from datetime import date
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from .promax_client import normalize_status


LineCallback = Callable[[str, str], None]
TickCallback = Callable[[], None]
ControlCallback = Callable[[], bool]
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class PromaxRunnerConfigurationError(ValueError):
    """Invalid local Promax driver configuration."""


@dataclass(frozen=True)
class PromaxRunnerConfig:
    driver_dir: Path
    python_executable: Path
    heartbeat_interval_seconds: float = 15.0
    control_interval_seconds: float = 5.0

    @classmethod
    def from_values(
        cls,
        *,
        driver_dir: str | os.PathLike[str],
        python_executable: str | os.PathLike[str],
        heartbeat_interval_seconds: float = 15.0,
        control_interval_seconds: float = 5.0,
    ) -> PromaxRunnerConfig:
        driver_path = Path(driver_dir).expanduser().resolve()
        python_path = Path(python_executable).expanduser().resolve()
        config = cls(
            driver_dir=driver_path,
            python_executable=python_path,
            heartbeat_interval_seconds=float(heartbeat_interval_seconds),
            control_interval_seconds=float(control_interval_seconds),
        )
        config.validate()
        return config

    @property
    def cli_path(self) -> Path:
        return self.driver_dir / "cli.py"

    def validate(self) -> None:
        if not self.driver_dir.is_dir():
            raise PromaxRunnerConfigurationError(
                f"PROMAX_DRIVER_DIR is not a directory: {self.driver_dir}"
            )
        if not self.cli_path.is_file():
            raise PromaxRunnerConfigurationError(f"Promax cli.py was not found: {self.cli_path}")
        if not self.python_executable.is_file():
            raise PromaxRunnerConfigurationError(
                f"PROMAX_PYTHON is not a file: {self.python_executable}"
            )
        if self.heartbeat_interval_seconds <= 0:
            raise PromaxRunnerConfigurationError("Heartbeat interval must be positive.")
        if self.control_interval_seconds <= 0:
            raise PromaxRunnerConfigurationError("Control interval must be positive.")


@dataclass(frozen=True)
class PromaxRunResult:
    status: str
    return_code: int
    child_pid: int
    cancelled: bool = False
    stopped: bool = False
    error: str | None = None
    message: str | None = None
    details: dict[str, Any] | None = None


class PromaxRunner:
    def __init__(
        self,
        config: PromaxRunnerConfig,
        *,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
        taskkill_runner: Callable[..., Any] = subprocess.run,
        platform: str = os.name,
    ) -> None:
        config.validate()
        self.config = config
        self._popen_factory = popen_factory
        self._monotonic = monotonic
        self._taskkill_runner = taskkill_runner
        self._platform = platform

    def build_command(self, job: Mapping[str, Any]) -> list[str]:
        payload = job.get("payload")
        if not isinstance(payload, Mapping):
            payload = job
        job_type = str(job.get("job_type") or "").strip()
        operation = str(payload.get("operation") or "").strip()
        job_id = str(job.get("id") or job.get("job_id") or "").strip()
        normalized_job_kind = _normalize_job_kind(operation or job_type)
        if job_type == "reprocess_publication" or operation == "reprocess_publication":
            if job_type != "reprocess_publication" or operation != "reprocess_publication":
                raise ValueError("Invalid Promax publication reprocessing job.")
            command = [
                str(self.config.python_executable),
                str(self.config.cli_path),
                "reprocessar-publicacao",
            ]
            if job_id:
                command.extend(["--job-id", job_id])
            return command

        if normalized_job_kind in {"fechamento_mapa", "mapa_fechamento"}:
            mapa = str(payload.get("mapa") or payload.get("map") or "").strip()
            if not mapa:
                raise ValueError("Promax fechamento-mapa job requires payload.mapa.")
            command = [
                str(self.config.python_executable),
                str(self.config.cli_path),
                "fechamento-mapa",
                "--mapa",
                mapa,
            ]
            ponto_apoio = str(payload.get("ponto_apoio") or payload.get("pontoApoio") or "").strip()
            if ponto_apoio and ponto_apoio != "0":
                command.extend(["--ponto-apoio", ponto_apoio])
            km_atual = str(payload.get("km_atual") or payload.get("kmAtual") or payload.get("km") or "").strip()
            if km_atual:
                command.extend(["--km-atual", km_atual])
            km_inicial = str(payload.get("km_inicial") or payload.get("kmInicial") or "").strip()
            if km_inicial:
                command.extend(["--km-inicial", km_inicial])
            km_prev = str(payload.get("km_prev") or payload.get("kmPrev") or payload.get("km_previsto") or payload.get("kmPrevisto") or "").strip()
            if km_prev:
                command.extend(["--km-prev", km_prev])
            unidade = str(payload.get("unit") or payload.get("unidade") or "").strip()
            units = _identifier_list(payload.get("units"), field_name="units")
            if not unidade and units:
                unidade = units[0]
            if unidade:
                command.extend(["--unidade", unidade])
            modo = str(payload.get("modo") or payload.get("mode") or "").strip().lower()
            if modo:
                if modo not in {"completo", "fisico", "financeiro"}:
                    raise ValueError("Promax fechamento-mapa modo must be completo, fisico or financeiro.")
                command.extend(["--modo", modo])
            if payload.get("save") is False or payload.get("salvar") is False:
                command.append("--nao-salvar")
            if payload.get("sessoes_separadas") is True or payload.get("separate_sessions") is True:
                command.append("--sessoes-separadas")
            if payload.get("fechar_ao_falhar") is True or payload.get("close_on_failure") is True:
                command.append("--fechar-ao-falhar")
            if job_id:
                command.extend(["--job-id", job_id])
            return command

        is_fechamento_reports_job = _is_botzapfechamento_job(payload, job_type, operation)
        clean_profile = (
            "botzapfechamento"
            if is_fechamento_reports_job
            else str(
                payload.get("profile")
                or payload.get("perfil")
                or payload.get("category")
                or job.get("job_type")
                or ""
            ).strip()
        )
        if not _IDENTIFIER_PATTERN.fullmatch(clean_profile):
            raise ValueError(f"Invalid Promax profile identifier: {clean_profile!r}.")

        entrypoint_command = "fechamento" if is_fechamento_reports_job else "relatorios"
        command = [
            str(self.config.python_executable),
            str(self.config.cli_path),
            entrypoint_command,
            "--perfil",
            clean_profile,
        ]
        send_dates = payload.get("send_dates", False)
        if not isinstance(send_dates, bool):
            raise ValueError("Promax send_dates flag must be boolean.")
        if send_dates:
            for field, option in (("start_date", "--data-inicial"), ("end_date", "--data-final")):
                raw_value = str(payload.get(field) or "").strip()
                if raw_value:
                    date.fromisoformat(raw_value)
                    command.extend([option, raw_value])

        routines = _payload_routines_for_profile(payload, clean_profile)
        if routines:
            command.extend(["--rotinas", *routines])

        units = _identifier_list(payload.get("units"), field_name="units")
        for unit in units:
            command.extend(["--unidade", unit])

        publish = payload.get("publish", True)
        if not isinstance(publish, bool):
            raise ValueError("Promax publish flag must be boolean.")
        command.append("--publicar" if publish else "--somente-baixar")

        if job_id:
            command.extend(["--job-id", job_id])

        download_workers = payload.get("download_workers")
        if download_workers is not None:
            normalized_workers = int(download_workers)
            if not 1 <= normalized_workers <= 8:
                raise ValueError("Promax download_workers must be between 1 and 8.")
            command.extend(["--download-workers", str(normalized_workers)])
        return command

    def run(
        self,
        job: Mapping[str, Any],
        *,
        on_line: LineCallback,
        heartbeat: TickCallback,
        cancel_requested: ControlCallback,
        stop_requested: ControlCallback | None = None,
    ) -> PromaxRunResult:
        command = self.build_command(job)
        on_line("stdout", f"Comando Promax: {subprocess.list2cmdline(command)}")
        process = self._popen_factory(
            command,
            cwd=str(self.config.driver_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
        )
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("Promax subprocess did not expose stdout and stderr.")

        output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        readers = (
            _start_reader("stdout", process.stdout, output_queue),
            _start_reader("stderr", process.stderr, output_queue),
        )
        open_streams = len(readers)
        child_pid = int(process.pid)
        cancelled = False
        stopped = False
        termination_requested = False
        last_stderr = ""
        result_message = ""
        result_details: dict[str, Any] = {}
        now = self._monotonic()
        next_heartbeat = now
        next_control = now

        while process.poll() is None or open_streams:
            now = self._monotonic()
            if process.poll() is None and now >= next_heartbeat:
                heartbeat()
                next_heartbeat = now + self.config.heartbeat_interval_seconds

            if process.poll() is None and now >= next_control:
                should_stop = bool(stop_requested and stop_requested())
                should_cancel = bool(cancel_requested())
                if (should_stop or should_cancel) and not termination_requested:
                    termination_requested = True
                    stopped = should_stop
                    cancelled = should_cancel and not should_stop
                    terminate_process_tree(
                        child_pid,
                        platform=self._platform,
                        run=self._taskkill_runner,
                    )
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        try:
                            process.kill()
                        except Exception:
                            pass
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            on_line(
                                "stderr",
                                "Subprocesso Promax nao encerrou apos taskkill/process.kill; finalizando job como cancelado.",
                            )
                            break
                next_control = now + self.config.control_interval_seconds

            try:
                stream, line = output_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                open_streams -= 1
                continue
            if stream == "stderr":
                last_stderr = line
            result_event = _parse_job_result_event(line) if stream == "stdout" else None
            if result_event is not None:
                result_message = str(result_event.get("message") or "").strip()
                result_details = {
                    key: value
                    for key, value in result_event.items()
                    if key not in {"event", "message"}
                }
                if result_message:
                    on_line("stdout", f"Resumo final: {result_message}")
                continue
            on_line(stream, line)

        for reader in readers:
            reader.join(timeout=1)
        return_code = int(process.wait())
        if stopped:
            status = "stopped"
        elif cancelled:
            status = "cancelled"
        elif return_code == 0:
            status = "success"
        elif return_code == 10:
            status = "partial_success"
        else:
            status = "failed"
        error = None
        if status == "failed":
            error = (
                last_stderr
                or result_message
                or f"Promax process exited with code {return_code}."
            )
        if not result_message:
            result_message = {
                "success": "Execucao Promax concluida com sucesso.",
                "partial_success": "Execucao Promax concluida com pendencias; consulte os logs.",
                "cancelled": "Execucao Promax cancelada.",
                "stopped": "Worker Promax interrompido.",
                "failed": error or "Execucao Promax falhou.",
            }[status]
        return PromaxRunResult(
            status=normalize_status(status),
            return_code=return_code,
            child_pid=child_pid,
            cancelled=cancelled,
            stopped=stopped,
            error=error,
            message=result_message,
            details=result_details,
        )


def terminate_process_tree(
    pid: int,
    *,
    platform: str = os.name,
    run: Callable[..., Any] = subprocess.run,
) -> None:
    clean_pid = int(pid)
    if clean_pid <= 0:
        raise ValueError("Subprocess PID must be positive.")
    if platform != "nt":
        raise RuntimeError("Promax process-tree cancellation is supported only on Windows.")
    run(
        ["taskkill", "/PID", str(clean_pid), "/T", "/F"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        shell=False,
    )


def _start_reader(
    stream_name: str,
    stream: TextIO,
    output_queue: queue.Queue[tuple[str, str | None]],
) -> threading.Thread:
    def read_lines() -> None:
        try:
            for raw_line in iter(stream.readline, ""):
                output_queue.put((stream_name, raw_line.rstrip("\r\n")))
        finally:
            stream.close()
            output_queue.put((stream_name, None))

    thread = threading.Thread(
        target=read_lines,
        name=f"promax-{stream_name}-reader",
        daemon=True,
    )
    thread.start()
    return thread


def _parse_job_result_event(line: str) -> dict[str, Any] | None:
    clean_line = str(line or "").strip()
    if not clean_line.startswith("{"):
        return None
    try:
        payload = json.loads(clean_line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("event") != "promax_job_result":
        return None
    return payload


def _normalize_job_kind(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _is_botzapfechamento_job(payload: Mapping[str, Any], job_type: object, operation: object) -> bool:
    direct_values = (
        job_type,
        operation,
        payload.get("category"),
        payload.get("profile"),
        payload.get("perfil"),
    )
    if any(str(value or "").strip().lower() == "botzapfechamento" for value in direct_values):
        return True

    groups = payload.get("groups")
    if not isinstance(groups, Sequence) or isinstance(groups, (str, bytes, bytearray)):
        return False
    return any(
        isinstance(group, Mapping)
        and str(group.get("category") or "").strip().lower() == "botzapfechamento"
        for group in groups
    )


def _identifier_list(value: object, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"Promax {field_name} must be a list.")
    normalized: list[str] = []
    for raw_item in value:
        item = str(raw_item or "").strip()
        if not _IDENTIFIER_PATTERN.fullmatch(item):
            raise ValueError(f"Promax {field_name} contains an invalid identifier.")
        if item not in normalized:
            normalized.append(item)
    return normalized


def _payload_routines_for_profile(payload: Mapping[str, Any], profile: str) -> list[str]:
    routines = _identifier_list(payload.get("routines"), field_name="routines")
    if routines:
        return routines

    groups = payload.get("groups")
    if groups is None:
        return []
    if not isinstance(groups, Sequence) or isinstance(groups, (str, bytes, bytearray)):
        raise ValueError("Promax groups must be a list.")

    selected: list[str] = []
    clean_profile = str(profile or "").strip()
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, Mapping):
            raise ValueError("Promax groups must contain objects.")
        category = str(group.get("category") or "").strip()
        if category and category != clean_profile:
            continue
        for routine in _identifier_list(group.get("routines"), field_name=f"groups[{index}].routines"):
            if routine not in selected:
                selected.append(routine)
    return selected
