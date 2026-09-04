from __future__ import annotations

import base64
import json
import os
import socket
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_ROOT = "/api/internal/promax/worker"
_TEMPORARY_HTTP_STATUSES = {408, 425, 429}


class PromaxClientError(RuntimeError):
    """Base error raised by the Promax worker API client."""


class PromaxApiUnavailable(PromaxClientError):
    """Temporary network or server failure that can be retried."""


class PromaxApiError(PromaxClientError):
    """Non-retryable response returned by the Promax worker API."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Promax API returned HTTP {status_code}: {detail}")


def normalize_status(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "success": "success",
        "successful": "success",
        "succeeded": "success",
        "completed": "success",
        "complete": "success",
        "done": "success",
        "ok": "success",
        "partial": "partial_success",
        "partial_success": "partial_success",
        "failure": "failed",
        "failed": "failed",
        "error": "failed",
        "erro": "failed",
        "cancel": "cancelled",
        "canceled": "cancelled",
        "cancelled": "cancelled",
        "cancel_requested": "cancelled",
        "aborted": "cancelled",
        "stop": "stopped",
        "stopped": "stopped",
        "terminated": "stopped",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported Promax final status: {value!r}") from exc


class PromaxClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        worker_id: str,
        pid: int | None = None,
        lease_seconds: int = 120,
        timeout_seconds: float = 10.0,
        boleto_import_timeout_seconds: float = 900.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.token = str(token or "").strip()
        self.worker_id = str(worker_id or "").strip()
        self.pid = int(pid if pid is not None else os.getpid())
        self.lease_seconds = int(lease_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.boleto_import_timeout_seconds = float(boleto_import_timeout_seconds)
        self._opener = opener
        self._validate()

    def heartbeat(
        self,
        *,
        status: str = "idle",
        job_id: str | None = None,
        version: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        del version
        heartbeat_details = dict(details or {})
        normalized_status = str(status or "").strip().lower()
        clean_job_id = str(job_id or "").strip() or None
        if normalized_status not in {"idle", "running"}:
            raise ValueError("Promax worker heartbeat status must be idle or running.")
        if normalized_status == "running" and clean_job_id is None:
            raise ValueError("Promax running heartbeat requires job_id.")
        return self._request(
            "POST",
            "/api/internal/promax/heartbeat",
            {
                "worker_id": self.worker_id,
                "pid": self.pid,
                "version": str(heartbeat_details.get("version") or "1"),
                "details": {
                    **heartbeat_details,
                    "hostname": str(heartbeat_details.get("hostname") or socket.gethostname()),
                    "status": normalized_status,
                    "job_id": clean_job_id,
                },
            },
        )

    def claim(self) -> dict[str, Any] | None:
        payload = self._request(
            "POST",
            "/api/internal/promax/next-job/claim",
            {
                "worker_id": self.worker_id,
                "pid": self.pid,
                "lease_seconds": self.lease_seconds,
            },
        )
        job = payload.get("job")
        if job is None:
            return None
        if not isinstance(job, Mapping):
            raise PromaxClientError("Promax claim response contains an invalid job.")
        return dict(job)

    def heartbeat_job(self, job_id: str, lease_token: str) -> dict[str, Any]:
        clean_job_id = _path_identifier(job_id)
        return self._request(
            "POST",
            f"/api/internal/promax/jobs/{clean_job_id}/heartbeat",
            {
                "worker_id": self.worker_id,
                "pid": self.pid,
                "lease_token": _path_identifier(lease_token),
                "lease_seconds": self.lease_seconds,
            },
        )

    def log(
        self,
        job_id: str,
        lease_token: str,
        message: str,
        *,
        level: str = "info",
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_message = str(message or "").rstrip("\r\n")
        if not clean_message:
            raise ValueError("Promax log message must not be empty.")
        if len(clean_message) > 8000:
            raise ValueError("Promax log message exceeds 8000 characters.")
        log_data = dict(data or {})
        stream = str(log_data.get("stream") or "").strip().lower()
        if stream not in {"stdout", "stderr"}:
            stream = "stderr" if str(level or "").strip().lower() == "error" else "stdout"
        return self._request(
            "POST",
            f"/api/internal/promax/jobs/{_path_identifier(job_id)}/log",
            {
                "worker_id": self.worker_id,
                "lease_token": _path_identifier(lease_token),
                "level": "error" if stream == "stderr" else str(level or "info").lower(),
                "message": clean_message,
                "data": {"stream": stream},
            },
        )

    def control(self, job_id: str) -> dict[str, Any]:
        query = urlencode(
            {
                "worker_id": self.worker_id,
                "job_id": _path_identifier(job_id),
            }
        )
        return self._request(
            "GET",
            f"/api/internal/promax/control?{query}",
        )

    def finish(
        self,
        job_id: str,
        lease_token: str,
        *,
        status: object,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        normalized_status = normalize_status(status)
        api_status = "cancelled" if normalized_status == "stopped" else normalized_status
        clean_error = str(error or "").strip() or None
        if api_status == "failed" and clean_error is None:
            clean_error = "Promax process failed without an error message."
        finish_result = dict(result or {})
        raw_exit_code = finish_result.get("exit_code", finish_result.get("return_code"))
        exit_code = int(raw_exit_code) if raw_exit_code is not None else None
        return self._request(
            "POST",
            f"/api/internal/promax/jobs/{_path_identifier(job_id)}/finish",
            {
                "worker_id": self.worker_id,
                "pid": self.pid,
                "lease_token": _path_identifier(lease_token),
                "status": api_status,
                "result": {
                    **finish_result,
                    "exit_code": exit_code,
                },
                "error": clean_error[:8000] if clean_error else "",
            },
        )

    def import_boleto_pdf(
        self,
        *,
        job_id: str,
        lease_token: str,
        filial: str,
        filename: str,
        pdf_bytes: bytes,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        if not pdf_bytes:
            raise ValueError("PDF bytes must not be empty.")
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "job_id": _path_identifier(job_id),
            "lease_token": _path_identifier(lease_token),
            "filial": str(filial or "").strip(),
            "filename": str(filename or "").strip(),
            "file_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        }
        if reference_date:
            payload["reference_date"] = str(reference_date)
        return self._request(
            "POST",
            "/api/internal/promax/boletos/import",
            payload,
            timeout_seconds=self.boleto_import_timeout_seconds,
        )

    def import_inadimplencia_csvs(
        self,
        *,
        job_id: str,
        lease_token: str,
        files: Mapping[str, bytes],
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        if not files:
            raise ValueError("CSV files must not be empty.")
        payload_files: list[dict[str, str]] = []
        for filename, file_bytes in files.items():
            if not file_bytes:
                raise ValueError(f"CSV file {filename!r} must not be empty.")
            payload_files.append(
                {
                    "filename": str(filename or "").strip(),
                    "file_base64": base64.b64encode(file_bytes).decode("ascii"),
                }
            )
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "job_id": _path_identifier(job_id),
            "lease_token": _path_identifier(lease_token),
            "files": payload_files,
        }
        if reference_date:
            payload["reference_date"] = str(reference_date)
        return self._request(
            "POST",
            "/api/internal/promax/inadimplencia/import",
            payload,
            timeout_seconds=self.boleto_import_timeout_seconds,
        )

    def import_estoque_020304_csv(
        self,
        *,
        job_id: str,
        lease_token: str,
        filial: str,
        filename: str,
        csv_bytes: bytes,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        if not csv_bytes:
            raise ValueError("CSV bytes must not be empty.")
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "job_id": _path_identifier(job_id),
            "lease_token": _path_identifier(lease_token),
            "filial": str(filial or "").strip(),
            "filename": str(filename or "").strip(),
            "file_base64": base64.b64encode(csv_bytes).decode("ascii"),
        }
        if reference_date:
            payload["reference_date"] = str(reference_date)
        return self._request(
            "POST",
            "/api/internal/promax/estoque/import",
            payload,
            timeout_seconds=self.boleto_import_timeout_seconds,
        )

    def import_relatorio_031120_csv(
        self,
        *,
        job_id: str,
        lease_token: str,
        filial: str,
        filename: str,
        csv_bytes: bytes,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        if not csv_bytes:
            raise ValueError("CSV bytes must not be empty.")
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "job_id": _path_identifier(job_id),
            "lease_token": _path_identifier(lease_token),
            "filial": str(filial or "").strip(),
            "filename": str(filename or "").strip(),
            "file_base64": base64.b64encode(csv_bytes).decode("ascii"),
        }
        if reference_date:
            payload["reference_date"] = str(reference_date)
        return self._request(
            "POST",
            "/api/internal/promax/031120/import",
            payload,
            timeout_seconds=self.boleto_import_timeout_seconds,
        )

    def import_relatorio_03114902_csv(
        self,
        *,
        job_id: str,
        lease_token: str,
        filial: str,
        filename: str,
        csv_bytes: bytes,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        if not csv_bytes:
            raise ValueError("CSV bytes must not be empty.")
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "job_id": _path_identifier(job_id),
            "lease_token": _path_identifier(lease_token),
            "filial": str(filial or "").strip(),
            "filename": str(filename or "").strip(),
            "file_base64": base64.b64encode(csv_bytes).decode("ascii"),
        }
        if reference_date:
            payload["reference_date"] = str(reference_date)
        return self._request(
            "POST",
            "/api/internal/promax/03114902/import",
            payload,
            timeout_seconds=self.boleto_import_timeout_seconds,
        )

    def import_comodatos_csvs(
        self,
        *,
        job_id: str,
        lease_token: str,
        files: Mapping[str, bytes],
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        return self._import_csv_batch(
            path="/api/internal/promax/comodatos/import",
            job_id=job_id,
            lease_token=lease_token,
            files=files,
            reference_date=reference_date,
        )

    def import_dclientes_csv(
        self,
        *,
        job_id: str,
        lease_token: str,
        filename: str,
        csv_bytes: bytes,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        return self._import_csv_batch(
            path="/api/internal/promax/dclientes/import",
            job_id=job_id,
            lease_token=lease_token,
            files={filename: csv_bytes},
            reference_date=reference_date,
        )

    def import_documentacao_csvs(
        self,
        *,
        job_id: str,
        lease_token: str,
        files: Mapping[str, bytes],
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        return self._import_csv_batch(
            path="/api/internal/promax/documentacao/import",
            job_id=job_id,
            lease_token=lease_token,
            files=files,
            reference_date=reference_date,
        )

    def import_dmateriais_csv(
        self,
        *,
        job_id: str,
        lease_token: str,
        filename: str,
        csv_bytes: bytes,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        return self._import_csv_batch(
            path="/api/internal/promax/dmateriais/import",
            job_id=job_id,
            lease_token=lease_token,
            files={filename: csv_bytes},
            reference_date=reference_date,
        )

    def import_critica_csvs(
        self,
        *,
        job_id: str,
        lease_token: str,
        files: Mapping[str, bytes],
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        return self._import_csv_batch(
            path="/api/internal/promax/critica/import",
            job_id=job_id,
            lease_token=lease_token,
            files=files,
            reference_date=reference_date,
        )

    def sync_financeiro_fechamento_mapa(
        self,
        *,
        job_id: str,
        lease_token: str,
        data: str,
        filial: str,
        mapa: str,
        result: Mapping[str, Any],
        sync_scope: str = "all",
    ) -> dict[str, Any]:
        del lease_token
        return self._request(
            "POST",
            "/api/internal/promax/financeiro/fechamento-mapa",
            {
                "worker_id": self.worker_id,
                "job_id": _path_identifier(job_id),
                "data": str(data or "").strip(),
                "filial": str(filial or "").strip(),
                "mapa": str(mapa or "").strip(),
                "result": dict(result or {}),
                "sync_scope": str(sync_scope or "all").strip(),
            },
            timeout_seconds=self.boleto_import_timeout_seconds,
        )

    def _import_csv_batch(
        self,
        *,
        path: str,
        job_id: str,
        lease_token: str,
        files: Mapping[str, bytes],
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        if not files:
            raise ValueError("CSV files must not be empty.")
        payload_files: list[dict[str, str]] = []
        for filename, file_bytes in files.items():
            if not file_bytes:
                raise ValueError(f"CSV file {filename!r} must not be empty.")
            payload_files.append(
                {
                    "filename": str(filename or "").strip(),
                    "file_base64": base64.b64encode(file_bytes).decode("ascii"),
                }
            )
        payload: dict[str, Any] = {
            "worker_id": self.worker_id,
            "job_id": _path_identifier(job_id),
            "lease_token": _path_identifier(lease_token),
            "files": payload_files,
        }
        if reference_date:
            payload["reference_date"] = str(reference_date)
        return self._request(
            "POST",
            path,
            payload,
            timeout_seconds=self.boleto_import_timeout_seconds,
        )

    def _validate(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("PROMAX_API_BASE_URL must start with http:// or https://.")
        if not self.token:
            raise ValueError("PROMAX_WORKER_TOKEN is required.")
        if not self.worker_id or len(self.worker_id) > 120:
            raise ValueError("PROMAX_WORKER_ID must contain between 1 and 120 characters.")
        if self.pid <= 0:
            raise ValueError("Worker PID must be positive.")
        if not 15 <= self.lease_seconds <= 3600:
            raise ValueError("PROMAX_WORKER_LEASE_SECONDS must be between 15 and 3600.")
        if self.timeout_seconds <= 0:
            raise ValueError("PROMAX_WORKER_HTTP_TIMEOUT_SECONDS must be positive.")
        if self.boleto_import_timeout_seconds <= 0:
            raise ValueError("PROMAX_WORKER_BOLETO_IMPORT_TIMEOUT_SECONDS must be positive.")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {
            "Accept": "application/json",
            "x-promax-worker-token": self.token,
        }
        if payload is not None:
            data = json.dumps(dict(payload), ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        request_timeout = self.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        try:
            response = self._opener(request, timeout=request_timeout)
            try:
                raw_body = response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as exc:
            detail = _http_error_detail(exc)
            if exc.code in _TEMPORARY_HTTP_STATUSES or exc.code >= 500:
                raise PromaxApiUnavailable(f"Promax API temporarily unavailable (HTTP {exc.code}): {detail}") from exc
            raise PromaxApiError(exc.code, detail) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise PromaxApiUnavailable(f"Could not reach Promax API: {exc}") from exc

        if not raw_body:
            return {}
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PromaxClientError("Promax API returned invalid JSON.") from exc
        if not isinstance(decoded, Mapping):
            raise PromaxClientError("Promax API response must be a JSON object.")
        return dict(decoded)


def _path_identifier(value: object) -> str:
    identifier = str(value or "").strip()
    if not identifier or any(character in identifier for character in ("/", "\\", "?", "#")):
        raise ValueError("Invalid Promax job identifier.")
    return identifier


def _http_error_detail(error: HTTPError) -> str:
    try:
        raw_body = error.read()
    except OSError:
        raw_body = b""
    if raw_body:
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
            if isinstance(decoded, Mapping):
                return str(decoded.get("detail") or decoded.get("error") or decoded)[:1000]
            return str(decoded)[:1000]
        except (UnicodeDecodeError, json.JSONDecodeError):
            return raw_body.decode("utf-8", errors="replace")[:1000]
    return str(error.reason or "request failed")[:1000]
