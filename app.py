from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import shutil
from threading import Lock
from typing import Any

import psycopg
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from bot_api.config import get_settings
from bot_api.db import close_all_connection_pools
from bot_api.integrations.evolution_client import EvolutionClient, EvolutionConfig, extract_incoming_message
from bot_api.integrations.meta_cloud_client import MetaCloudClient, MetaCloudConfig
from bot_api.integrations.meta_cloud_client import (
    extract_incoming_message as extract_meta_cloud_incoming_message,
)
from bot_api.integrations.meta_cloud_client import verify_webhook_token as verify_meta_cloud_webhook_token
from bot_api.security.access_control import AccessControl
from bot_api.security.security_monitor import SecurityMonitor
from bot_api.services.customer_lookup_flow import CustomerLookupFlow
from bot_api.services.comodatos_import_service import ComodatosImportService
from bot_api.services.comodatos_query_service import ComodatosQueryService
from bot_api.services.dclientes_import_service import DClientesImportService
from bot_api.services.dclientes_query_service import DClientesQueryService
from bot_api.services.dsetores_import_service import DSetoresImportService
from bot_api.services.giro_import_service import GiroImportService
from bot_api.services.giro_query_service import GiroQueryService
from bot_api.services.inadimplencia_import_service import InadimplenciaImportService
from bot_api.services.inadimplencia_query_service import InadimplenciaQueryService

settings = get_settings()
dclientes_query_service = DClientesQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
inadimplencia_query_service = InadimplenciaQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
comodatos_query_service = ComodatosQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
giro_query_service = GiroQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
dsetores_import_service = DSetoresImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
dclientes_import_service = DClientesImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
inadimplencia_import_service = InadimplenciaImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
comodatos_import_service = ComodatosImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
giro_import_service = GiroImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
evolution_client = EvolutionClient(
    EvolutionConfig(
        base_url=settings.evolution_base_url,
        api_key=settings.evolution_api_key,
        instance=settings.evolution_instance,
        send_path=settings.evolution_send_path,
        list_path=settings.evolution_list_path,
        buttons_path=settings.evolution_buttons_path,
        timeout_seconds=settings.evolution_timeout_seconds,
    )
)
meta_cloud_client = MetaCloudClient(
    MetaCloudConfig(
        enabled=settings.meta_cloud_enabled,
        api_version=settings.meta_cloud_api_version,
        phone_number_id=settings.meta_cloud_phone_number_id,
        access_token=settings.meta_cloud_access_token,
        verify_token=settings.meta_cloud_verify_token,
    )
)
access_control = AccessControl(
    enabled=settings.access_control_enabled,
    database_url=settings.access_database_url,
    schema=settings.access_db_schema,
    public_enabled=settings.access_public_enabled,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
security_monitor = SecurityMonitor(
    enabled=settings.security_audit_enabled,
    database_url=settings.access_database_url,
    schema=settings.access_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
    default_cooldown_minutes=settings.denied_reply_cooldown_minutes,
    unregistered_cooldown_minutes=settings.denied_unregistered_reply_cooldown_minutes,
)
lookup_flow = CustomerLookupFlow(
    query_service=dclientes_query_service,
    inadimplencia_service=inadimplencia_query_service,
    comodatos_service=comodatos_query_service,
    giro_service=giro_query_service,
    access_control=access_control,
)
webhook_executor = ThreadPoolExecutor(
    max_workers=settings.webhook_worker_threads,
    thread_name_prefix="webhook-worker",
)

app = FastAPI(title="Customer Lookup Bot API", version="1.0.0")
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent
ADMIN_IMPORT_PANEL_TEMPLATE = PROJECT_ROOT / "templates" / "admin_import_panel.html"
ADMIN_IMPORT_RUNTIME_ROOT = (
    Path("/tmp/bot_api_admin_imports") if Path("/tmp").exists() else PROJECT_ROOT / "exports" / "admin_import_uploads"
)
ADMIN_IMPORT_DATASETS: dict[str, dict[str, Any]] = {
    "dsetores": {
        "label": "dSetores",
        "default_path": PROJECT_ROOT / "data" / "dSetores" / "dSetores.csv",
        "service": dsetores_import_service,
        "upload_mode": "single",
        "accept_extensions": ".csv",
        "validate_method": "validate_csv",
        "summarize_method": "summarize_csv",
        "import_method": "import_csv",
    },
    "dclientes": {
        "label": "dClientes",
        "default_path": PROJECT_ROOT / "data" / "dClientes" / "dClientes.csv",
        "service": dclientes_import_service,
        "upload_mode": "single",
        "accept_extensions": ".csv",
        "validate_method": "validate_csv",
        "summarize_method": "summarize_csv",
        "import_method": "import_csv",
    },
    "inadimplencia": {
        "label": "Inadimplencia",
        "default_path": PROJECT_ROOT / "data" / "Inadimplencia",
        "service": inadimplencia_import_service,
        "upload_mode": "multiple",
        "accept_extensions": ".csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "comodatos": {
        "label": "Comodatos",
        "default_path": PROJECT_ROOT / "data" / "Comodatos",
        "service": comodatos_import_service,
        "upload_mode": "multiple",
        "accept_extensions": ".csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "giro": {
        "label": "Giro",
        "default_path": PROJECT_ROOT / "data" / "Giro" / "giro.xlsx",
        "service": giro_import_service,
        "upload_mode": "single",
        "accept_extensions": ".xlsx,.xlsm,.xls",
        "validate_method": "validate_workbook",
        "summarize_method": "summarize_workbook",
        "import_method": "import_workbook",
    },
}
admin_import_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="admin-import")
admin_import_lock = Lock()
admin_import_state: dict[str, Any] = {
    "running": False,
    "current_job_id": "",
    "current_dataset": "",
    "started_at": "",
    "reference_date": "",
    "last_job": {},
}


class DeniedReplyThrottle:
    def __init__(
        self,
        default_cooldown_minutes: int,
        unregistered_cooldown_minutes: int,
    ) -> None:
        self.default_cooldown = timedelta(minutes=max(int(default_cooldown_minutes), 1))
        self.unregistered_cooldown = timedelta(minutes=max(int(unregistered_cooldown_minutes), 1))
        self._cleanup_window = max(self.default_cooldown, self.unregistered_cooldown) * 2
        self._last_reply_at: dict[str, datetime] = {}
        self._lock = Lock()

    def should_send(self, number: str, reason: str) -> bool:
        normalized_number = str(number or "").strip()
        if not normalized_number:
            return False

        now = datetime.now(timezone.utc)
        cooldown = self.unregistered_cooldown if reason == "number_not_registered" else self.default_cooldown
        with self._lock:
            self._cleanup_locked(now)
            last_reply_at = self._last_reply_at.get(normalized_number)
            if last_reply_at is not None and now - last_reply_at < cooldown:
                return False
            self._last_reply_at[normalized_number] = now
            return True

    def cooldown_minutes_for(self, reason: str) -> int:
        cooldown = self.unregistered_cooldown if reason == "number_not_registered" else self.default_cooldown
        return max(1, int(cooldown.total_seconds() // 60))

    def _cleanup_locked(self, now: datetime) -> None:
        expired_numbers = [
            number
            for number, last_reply_at in self._last_reply_at.items()
            if now - last_reply_at >= self._cleanup_window
        ]
        for number in expired_numbers:
            self._last_reply_at.pop(number, None)


denied_reply_throttle = DeniedReplyThrottle(
    default_cooldown_minutes=settings.denied_reply_cooldown_minutes,
    unregistered_cooldown_minutes=settings.denied_unregistered_reply_cooldown_minutes,
)


class AccessUserUpsertRequest(BaseModel):
    phone_number: str
    name: str | None = None
    is_active: bool = True
    roles: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    gv_vdes: list[str] = Field(default_factory=list)


class AccessRoleUpsertRequest(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class AdminImportActionRequest(BaseModel):
    dataset: str
    reference_date: str | None = None


def _require_admin_token(x_admin_token: str | None, request: Request | None = None) -> None:
    expected_token = settings.admin_api_token.strip()
    if not expected_token:
        if request is not None:
            _record_security_event(
                request,
                channel="api",
                event_type="admin_auth",
                decision="misconfigured",
                reason="admin_token_not_configured",
            )
        raise HTTPException(status_code=503, detail="Rotas administrativas indisponiveis.")

    provided_token = str(x_admin_token or "").strip()
    if provided_token and secrets.compare_digest(provided_token, expected_token):
        if request is not None:
            _record_security_event(
                request,
                channel="api",
                event_type="admin_auth",
                decision="allowed",
            )
        return

    if request is not None:
        _record_security_event(
            request,
            channel="api",
            event_type="admin_auth",
            decision="denied",
            reason="invalid_admin_token",
        )
    raise HTTPException(status_code=401, detail="Admin token invalido.")


def _request_metadata(request: Request, **extra: Any) -> dict[str, Any]:
    metadata = {
        "method": request.method,
        "client_host": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
        "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
    }
    metadata.update({key: value for key, value in extra.items() if value is not None and value != ""})
    return metadata


def _record_security_event(
    request: Request,
    *,
    channel: str,
    event_type: str,
    decision: str,
    phone_number: str | None = None,
    area: str | None = None,
    reason: str | None = None,
    **extra: Any,
) -> None:
    security_monitor.record_event(
        channel=channel,
        path=request.url.path,
        event_type=event_type,
        decision=decision,
        phone_number=phone_number,
        area=area,
        reason=reason,
        metadata=_request_metadata(request, **extra),
    )


def _record_security_event_for_path(
    *,
    path: str,
    metadata: dict[str, Any],
    channel: str,
    event_type: str,
    decision: str,
    phone_number: str | None = None,
    area: str | None = None,
    reason: str | None = None,
    **extra: Any,
) -> None:
    combined_metadata = dict(metadata)
    combined_metadata.update({key: value for key, value in extra.items() if value is not None and value != ""})
    security_monitor.record_event(
        channel=channel,
        path=path,
        event_type=event_type,
        decision=decision,
        phone_number=phone_number,
        area=area,
        reason=reason,
        metadata=combined_metadata,
    )


def _should_send_denied_reply(number: str, reason: str) -> bool:
    persisted_decision = security_monitor.should_send_denied_reply(number=number, reason=reason)
    if persisted_decision is not None:
        return persisted_decision
    return denied_reply_throttle.should_send(number=number, reason=reason)


def _extract_bearer_token(authorization: str | None) -> str:
    raw_value = str(authorization or "").strip()
    if not raw_value:
        return ""
    parts = raw_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _token_matches(candidate: str, expected_values: tuple[str, ...]) -> bool:
    cleaned_candidate = str(candidate or "").strip()
    if not cleaned_candidate:
        return False
    return any(secrets.compare_digest(cleaned_candidate, expected) for expected in expected_values if expected)


def _require_api_auth(
    request: Request,
    authorization: str | None,
    x_api_token: str | None,
) -> None:
    if not settings.api_auth_enabled:
        return

    provided_tokens = []
    bearer_token = _extract_bearer_token(authorization)
    if bearer_token:
        provided_tokens.append(bearer_token)
    if x_api_token and x_api_token.strip():
        provided_tokens.append(x_api_token.strip())

    valid_tokens = tuple(settings.api_auth_tokens)
    if not valid_tokens:
        _record_security_event(
            request,
            channel="api",
            event_type="api_auth",
            decision="misconfigured",
            reason="api_auth_without_tokens",
        )
        raise HTTPException(status_code=503, detail="Autenticacao da API habilitada, mas sem token configurado.")
    if any(_token_matches(candidate, valid_tokens) for candidate in provided_tokens):
        _record_security_event(
            request,
            channel="api",
            event_type="api_auth",
            decision="allowed",
        )
        return

    _record_security_event(
        request,
        channel="api",
        event_type="api_auth",
        decision="denied",
        reason="invalid_or_missing_api_token",
    )
    raise HTTPException(status_code=401, detail="Token da API invalido ou ausente.")


def _require_admin_scope_for_number_routes(
    request: Request,
    x_admin_token: str | None,
) -> None:
    if not settings.api_require_admin_for_number:
        return
    _require_admin_token(x_admin_token, request=request)


def _require_webhook_token(request: Request, x_bot_token: str | None, payload: dict[str, Any] | None = None) -> None:
    expected_token = settings.verify_token.strip()
    evolution_payload_key = str((payload or {}).get("apikey") or "").strip()
    evolution_webhook_api_keys = tuple(candidate for candidate in settings.evolution_webhook_api_keys if candidate)

    if expected_token and x_bot_token and secrets.compare_digest(x_bot_token.strip(), expected_token):
        _record_security_event(
            request,
            channel="webhook",
            event_type="webhook_auth",
            decision="allowed",
            reason="x_bot_token",
        )
        return

    if evolution_payload_key and _token_matches(evolution_payload_key, evolution_webhook_api_keys):
        _record_security_event(
            request,
            channel="webhook",
            event_type="webhook_auth",
            decision="allowed",
            reason="webhook_apikey",
        )
        return

    if not expected_token and not evolution_webhook_api_keys:
        _record_security_event(
            request,
            channel="webhook",
            event_type="webhook_auth",
            decision="misconfigured",
            reason="webhook_auth_not_configured",
        )
        raise HTTPException(status_code=503, detail="Webhook indisponivel.")

    _record_security_event(
        request,
        channel="webhook",
        event_type="webhook_auth",
        decision="denied",
        reason="invalid_or_missing_x_bot_token",
    )
    raise HTTPException(status_code=401, detail="Nao autorizado.")


def _access_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _normalize_admin_import_dataset(dataset: str) -> str:
    normalized = str(dataset or "").strip().lower()
    if normalized not in ADMIN_IMPORT_DATASETS:
        allowed = ", ".join(sorted(ADMIN_IMPORT_DATASETS))
        raise HTTPException(status_code=400, detail=f"Dataset invalido. Use {allowed}.")
    return normalized


def _serialize_admin_import_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_admin_import_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_admin_import_value(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_admin_import_value(item) for item in value]
    return value


def _run_admin_import_validation(dataset: str) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    config = ADMIN_IMPORT_DATASETS[normalized_dataset]
    source_path = _resolve_admin_import_source_path(normalized_dataset)
    service = config["service"]
    validation = getattr(service, str(config["validate_method"]))(source_path)
    summary = getattr(service, str(config["summarize_method"]))(source_path)

    return {
        "dataset": normalized_dataset,
        "label": config["label"],
        "default_path": str(source_path),
        "accept_extensions": str(config.get("accept_extensions") or ""),
        "validation": _serialize_admin_import_value(validation.to_dict()),
        "summary": _serialize_admin_import_value(summary.to_dict()),
    }


def _run_admin_import(dataset: str, reference_date: str | None = None) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    config = ADMIN_IMPORT_DATASETS[normalized_dataset]
    source_path = _resolve_admin_import_source_path(normalized_dataset)
    service = config["service"]
    batch_date = date.fromisoformat(reference_date) if str(reference_date or "").strip() else None

    validation_payload = _run_admin_import_validation(normalized_dataset)
    validation_errors = int(validation_payload["validation"].get("error_count") or 0)
    if validation_errors:
        raise HTTPException(status_code=400, detail="A validacao encontrou erros. Corrija o arquivo antes de importar.")

    getattr(service, str(config["validate_method"]))(source_path).ensure_valid()

    if normalized_dataset == "dsetores":
        result = getattr(service, str(config["import_method"]))(source_path, reference_date=batch_date)
        refresh_result = dclientes_import_service.refresh_latest_view()
        return {
            "dataset": normalized_dataset,
            "label": config["label"],
            "default_path": str(source_path),
            "accept_extensions": str(config.get("accept_extensions") or ""),
            "validation": validation_payload["validation"],
            "summary": validation_payload["summary"],
            "import_result": _serialize_admin_import_value(result),
            "post_actions": {"refresh_dclientes_view": _serialize_admin_import_value(refresh_result)},
        }
    result = getattr(service, str(config["import_method"]))(source_path, reference_date=batch_date)
    return {
        "dataset": normalized_dataset,
        "label": config["label"],
        "default_path": str(source_path),
        "accept_extensions": str(config.get("accept_extensions") or ""),
        "validation": validation_payload["validation"],
        "summary": validation_payload["summary"],
        "import_result": _serialize_admin_import_value(result),
    }


def _snapshot_admin_import_state() -> dict[str, Any]:
    with admin_import_lock:
        return _serialize_admin_import_value(
            {
                "running": bool(admin_import_state["running"]),
                "current_job_id": str(admin_import_state["current_job_id"] or ""),
                "current_dataset": str(admin_import_state["current_dataset"] or ""),
                "started_at": str(admin_import_state["started_at"] or ""),
                "reference_date": str(admin_import_state["reference_date"] or ""),
                "last_job": dict(admin_import_state.get("last_job") or {}),
            }
        )


def _format_admin_import_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, str):
            return detail
        return str(detail)
    return str(error)


def _finish_admin_import_job(
    *,
    job_id: str,
    dataset: str,
    started_at: str,
    reference_date: str,
    status: str,
    result: dict[str, Any] | None,
    error: str,
) -> None:
    finished_at = datetime.now(timezone.utc).isoformat()
    with admin_import_lock:
        if admin_import_state["current_job_id"] == job_id:
            admin_import_state["running"] = False
            admin_import_state["current_job_id"] = ""
            admin_import_state["current_dataset"] = ""
            admin_import_state["started_at"] = ""
            admin_import_state["reference_date"] = ""
        admin_import_state["last_job"] = {
            "job_id": job_id,
            "dataset": dataset,
            "label": ADMIN_IMPORT_DATASETS.get(dataset, {}).get("label", dataset),
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "reference_date": reference_date,
            "error": error,
            "result": _serialize_admin_import_value(result) if result is not None else None,
        }


def _admin_import_worker(job_id: str, dataset: str, reference_date: str) -> None:
    started_at = _snapshot_admin_import_state().get("started_at", "")
    try:
        result = _run_admin_import(dataset, reference_date=reference_date or None)
    except Exception as exc:
        logger.exception("Falha ao importar dataset %s pelo painel admin.", dataset)
        _finish_admin_import_job(
            job_id=job_id,
            dataset=dataset,
            started_at=str(started_at),
            reference_date=reference_date,
            status="failed",
            result=None,
            error=_format_admin_import_error(exc),
        )
        return

    _finish_admin_import_job(
        job_id=job_id,
        dataset=dataset,
        started_at=str(started_at),
        reference_date=reference_date,
        status="completed",
        result=result,
        error="",
    )


def _queue_admin_import(dataset: str, reference_date: str | None = None) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    clean_reference_date = str(reference_date or "").strip()
    started_at = datetime.now(timezone.utc).isoformat()
    job_id = f"{normalized_dataset}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"

    with admin_import_lock:
        if admin_import_state["running"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ja existe uma importacao em andamento para "
                    f"{admin_import_state['current_dataset'] or 'outro dataset'}."
                ),
            )
        admin_import_state["running"] = True
        admin_import_state["current_job_id"] = job_id
        admin_import_state["current_dataset"] = normalized_dataset
        admin_import_state["started_at"] = started_at
        admin_import_state["reference_date"] = clean_reference_date

    try:
        admin_import_executor.submit(_admin_import_worker, job_id, normalized_dataset, clean_reference_date)
    except Exception:
        with admin_import_lock:
            admin_import_state["running"] = False
            admin_import_state["current_job_id"] = ""
            admin_import_state["current_dataset"] = ""
            admin_import_state["started_at"] = ""
            admin_import_state["reference_date"] = ""
        raise

    return {
        "job_id": job_id,
        "dataset": normalized_dataset,
        "label": ADMIN_IMPORT_DATASETS[normalized_dataset]["label"],
        "reference_date": clean_reference_date,
        "state": _snapshot_admin_import_state(),
    }


def _sanitize_uploaded_filename(dataset: str, filename: str) -> str:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    allowed_extensions = {
        item.strip().lower()
        for item in str(ADMIN_IMPORT_DATASETS[normalized_dataset].get("accept_extensions") or "").split(",")
        if item.strip()
    }
    clean_name = Path(str(filename or "")).name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Arquivo invalido para upload.")
    suffix = Path(clean_name).suffix.lower()
    if allowed_extensions and suffix not in allowed_extensions:
        extension_text = ", ".join(sorted(allowed_extensions))
        raise HTTPException(status_code=400, detail=f"Extensao invalida. Use: {extension_text}.")
    return clean_name


def _dataset_runtime_upload_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    default_path = Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])
    runtime_dir = ADMIN_IMPORT_RUNTIME_ROOT / normalized_dataset
    if ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"] == "single":
        return runtime_dir / default_path.name
    return runtime_dir


def _resolve_admin_import_source_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    runtime_path = _dataset_runtime_upload_path(normalized_dataset)
    if runtime_path.exists():
        return runtime_path
    return Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])


def _replace_single_upload_source(dataset: str, files: list[UploadFile]) -> list[dict[str, Any]]:
    if len(files) != 1:
        raise HTTPException(status_code=400, detail="Esse dataset aceita exatamente um arquivo por vez.")

    target_path = _dataset_runtime_upload_path(dataset)
    upload = files[0]
    _sanitize_uploaded_filename(dataset, upload.filename or "")
    temp_path = target_path.with_name(f"{target_path.name}.uploading")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)
        temp_path.replace(target_path)
    finally:
        upload.file.close()

    return [
        {
            "saved_as": str(target_path),
            "uploaded_name": str(upload.filename or ""),
            "size_bytes": int(target_path.stat().st_size),
        }
    ]


def _replace_multiple_upload_source(dataset: str, files: list[UploadFile]) -> list[dict[str, Any]]:
    if not files:
        raise HTTPException(status_code=400, detail="Selecione pelo menos um arquivo para upload.")

    target_dir = _dataset_runtime_upload_path(dataset)
    temp_dir = target_dir.with_name(f"{target_dir.name}__uploading")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    try:
        for upload in files:
            safe_name = _sanitize_uploaded_filename(dataset, upload.filename or "")
            if safe_name in seen_names:
                raise HTTPException(status_code=400, detail=f"Arquivo repetido no upload: {safe_name}")
            seen_names.add(safe_name)
            temp_path = temp_dir / safe_name
            try:
                with temp_path.open("wb") as buffer:
                    shutil.copyfileobj(upload.file, buffer)
            finally:
                upload.file.close()
            saved_files.append(
                {
                    "saved_as": str(temp_path),
                    "uploaded_name": str(upload.filename or ""),
                    "size_bytes": int(temp_path.stat().st_size),
                }
            )

        if target_dir.exists():
            shutil.rmtree(target_dir)
        temp_dir.replace(target_dir)
        for item in saved_files:
            item["saved_as"] = str(target_dir / Path(item["saved_as"]).name)
        return saved_files
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def _store_admin_import_uploads(dataset: str, files: list[UploadFile]) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    upload_mode = ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"]
    if upload_mode == "single":
        stored_files = _replace_single_upload_source(normalized_dataset, files)
    else:
        stored_files = _replace_multiple_upload_source(normalized_dataset, files)

    validation_result = _run_admin_import_validation(normalized_dataset)
    return {
        "dataset": normalized_dataset,
        "label": ADMIN_IMPORT_DATASETS[normalized_dataset]["label"],
        "default_path": str(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"]),
        "active_source_path": str(_resolve_admin_import_source_path(normalized_dataset)),
        "upload_mode": upload_mode,
        "stored_files": stored_files,
        "validation": validation_result["validation"],
        "summary": validation_result["summary"],
    }


def _list_admin_import_status() -> dict[str, Any]:
    dataset_rows: dict[str, dict[str, Any]] = {}
    query = """
        SELECT dataset_name, id, source_file, file_hash, reference_date, total_rows, imported_at
        FROM (
            SELECT
                dataset_name,
                id,
                source_file,
                file_hash,
                reference_date,
                total_rows,
                imported_at,
                ROW_NUMBER() OVER (PARTITION BY dataset_name ORDER BY imported_at DESC, id DESC) AS rn
            FROM reports.import_batches
            WHERE dataset_name = ANY(%s)
        ) latest
        WHERE rn = 1
    """
    with psycopg.connect(settings.reports_runtime_database_url, connect_timeout=int(settings.access_database_timeout_seconds)) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (list(ADMIN_IMPORT_DATASETS.keys()),))
            for dataset_name, batch_id, source_file, file_hash, reference_date, total_rows, imported_at in cur.fetchall():
                dataset_rows[str(dataset_name)] = {
                    "batch_id": int(batch_id),
                    "source_file": str(source_file or ""),
                    "file_hash": str(file_hash or ""),
                    "reference_date": _serialize_admin_import_value(reference_date),
                    "total_rows": int(total_rows or 0),
                    "imported_at": _serialize_admin_import_value(imported_at),
                }

    items: list[dict[str, Any]] = []
    for dataset_name, config in ADMIN_IMPORT_DATASETS.items():
        default_path = Path(config["default_path"])
        runtime_path = _dataset_runtime_upload_path(dataset_name)
        active_source_path = _resolve_admin_import_source_path(dataset_name)
        items.append(
            {
                "dataset": dataset_name,
                "label": config["label"],
                "default_path": str(default_path),
                "active_source_path": str(active_source_path),
                "source_exists": active_source_path.exists(),
                "using_uploaded_source": runtime_path.exists(),
                "upload_mode": str(config.get("upload_mode") or "single"),
                "accept_extensions": str(config.get("accept_extensions") or ""),
                "last_import": dataset_rows.get(dataset_name),
            }
        )

    state_snapshot = _snapshot_admin_import_state()
    state_snapshot["items"] = items
    return state_snapshot


def _list_admin_import_history(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    history: list[dict[str, Any]] = []
    query = """
        SELECT dataset_name, id, source_file, file_hash, reference_date, total_rows, imported_at
        FROM reports.import_batches
        WHERE dataset_name = ANY(%s)
        ORDER BY imported_at DESC, id DESC
        LIMIT %s
    """
    with psycopg.connect(settings.reports_runtime_database_url, connect_timeout=int(settings.access_database_timeout_seconds)) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (list(ADMIN_IMPORT_DATASETS.keys()), safe_limit))
            for dataset_name, batch_id, source_file, file_hash, reference_date, total_rows, imported_at in cur.fetchall():
                history.append(
                    {
                        "dataset": str(dataset_name),
                        "label": ADMIN_IMPORT_DATASETS.get(str(dataset_name), {}).get("label", str(dataset_name)),
                        "batch_id": int(batch_id),
                        "source_file": str(source_file or ""),
                        "file_hash": str(file_hash or ""),
                        "reference_date": _serialize_admin_import_value(reference_date),
                        "total_rows": int(total_rows or 0),
                        "imported_at": _serialize_admin_import_value(imported_at),
                    }
                )
    return {"total": len(history), "history": history}


def _load_admin_import_panel_html() -> str:
    if ADMIN_IMPORT_PANEL_TEMPLATE.exists():
        return ADMIN_IMPORT_PANEL_TEMPLATE.read_text(encoding="utf-8").replace(
            "__API_AUTH_ENABLED__",
            "true" if settings.api_auth_enabled else "false",
        )
    return "<html><body><h1>Painel indisponivel</h1></body></html>"


@app.on_event("startup")
def startup() -> None:
    if settings.access_control_enabled:
        ready = access_control.initialize()
        if not ready:
            logger.warning("RBAC Postgres indisponivel no startup: %s", access_control.status().get("last_error"))
    if settings.security_audit_enabled:
        ready = security_monitor.initialize()
        if not ready:
            logger.warning("Auditoria de seguranca indisponivel no startup: %s", security_monitor.status().get("last_error"))


@app.on_event("shutdown")
def shutdown() -> None:
    security_monitor.shutdown()
    admin_import_executor.shutdown(wait=False, cancel_futures=False)
    webhook_executor.shutdown(wait=True, cancel_futures=False)
    close_all_connection_pools()


def _build_detailed_health_payload() -> dict[str, Any]:
    access_status = access_control.status()
    security_status = security_monitor.status()
    reports_status = dclientes_query_service.status()
    inadimplencia_status = inadimplencia_query_service.status()
    comodatos_status = comodatos_query_service.status()
    giro_status = giro_query_service.status()
    return {
        "ok": True,
        "api_auth_enabled": settings.api_auth_enabled,
        "api_auth_token_count": len(settings.api_auth_tokens),
        "api_require_admin_for_number": settings.api_require_admin_for_number,
        "admin_token_configured": bool(settings.admin_api_token.strip()),
        "webhook_auth_required": True,
        "webhook_token_configured": bool(settings.verify_token.strip()),
        "meta_cloud_enabled": settings.meta_cloud_enabled,
        "meta_cloud_ready": meta_cloud_client.enabled,
        "meta_cloud_verify_token_configured": bool(settings.meta_cloud_verify_token.strip()),
        "webhook_worker_threads": settings.webhook_worker_threads,
        "security_audit_enabled": security_status["enabled"],
        "security_audit_ready": security_status["ready"],
        "security_audit_last_error": security_status["last_error"],
        "access_control_enabled": settings.access_control_enabled,
        "access_database_configured": access_status["database_configured"],
        "access_db_schema": access_status["schema"],
        "access_db_ready": access_status["ready"],
        "access_public_enabled": access_status["public_enabled"],
        "access_connect_timeout_seconds": access_status["connect_timeout_seconds"],
        "access_last_error": access_status["last_error"],
        "denied_reply_cooldown_minutes": settings.denied_reply_cooldown_minutes,
        "denied_unregistered_reply_cooldown_minutes": settings.denied_unregistered_reply_cooldown_minutes,
        "reports_database_configured": reports_status["database_configured"],
        "reports_db_schema": reports_status["schema"],
        "reports_db_ready": reports_status["ready"],
        "reports_latest_view_exists": reports_status["latest_view_exists"],
        "reports_inadimplencia_view_exists": reports_status.get("inadimplencia_view_exists", False),
        "reports_comodatos_view_exists": reports_status.get("comodatos_view_exists", False),
        "reports_last_error": reports_status["last_error"],
        "inadimplencia_ready": inadimplencia_status["ready"],
        "inadimplencia_latest_view_exists": inadimplencia_status["latest_view_exists"],
        "inadimplencia_dclientes_view_exists": inadimplencia_status["dclientes_view_exists"],
        "inadimplencia_last_error": inadimplencia_status["last_error"],
        "comodatos_ready": comodatos_status["ready"],
        "comodatos_latest_view_exists": comodatos_status["latest_view_exists"],
        "comodatos_dclientes_view_exists": comodatos_status["dclientes_view_exists"],
        "comodatos_last_error": comodatos_status["last_error"],
        "giro_ready": giro_status["ready"],
        "giro_latest_view_exists": giro_status["latest_view_exists"],
        "giro_last_error": giro_status["last_error"],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "bot_api",
        "meta_cloud_enabled": settings.meta_cloud_enabled,
        "meta_cloud_ready": meta_cloud_client.enabled,
    }


@app.get("/api/admin/health")
def api_admin_health(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    return _build_detailed_health_payload()


def _process_webhook_message(
    *,
    incoming: Any,
    requested_area: str,
    path: str,
    metadata: dict[str, Any],
) -> None:
    decision = access_control.authorize(phone_number=incoming.sender, area=requested_area)
    if not decision.allowed:
        _record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason=decision.reason,
        )
        blocked_text = (
            "Seu numero ainda nao tem acesso a essa consulta.\n"
            "Se precisar, fale com o responsavel para liberar o seu acesso."
        )
        blocked_reply_sent = _should_send_denied_reply(
            number=decision.normalized_number or incoming.sender,
            reason=decision.reason,
        )
        _record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="denied_reply",
            decision="sent" if blocked_reply_sent else "suppressed",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason=decision.reason,
        )
        if blocked_reply_sent:
            _send_text_reply(incoming=incoming, text=blocked_text)
        if blocked_reply_sent:
            logger.info(
                "Resposta de bloqueio enviada para %s (%s); proxima resposta em %s minuto(s).",
                decision.normalized_number or incoming.sender,
                decision.reason,
                denied_reply_throttle.cooldown_minutes_for(decision.reason),
            )
        else:
            logger.info(
                "Resposta de bloqueio suprimida para %s (%s).",
                decision.normalized_number or incoming.sender,
                decision.reason,
            )
        return

    try:
        outgoing = lookup_flow.handle(incoming=incoming, decision=decision)
    except Exception as exc:
        _record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="processing",
            decision="error",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason="processing_error",
        )
        logger.exception("Falha no processamento da mensagem: %s", exc)
        error_text = "Tive um problema para atender sua mensagem agora.\nTente novamente em instantes."
        _send_text_reply(incoming=incoming, text=error_text)
        return

    _record_security_event_for_path(
        path=path,
        metadata=metadata,
        channel="webhook",
        event_type="processing",
        decision="allowed",
        phone_number=decision.normalized_number or incoming.sender,
        area=requested_area,
        reason=outgoing.kind,
    )
    _send_outgoing_reply(incoming=incoming, outgoing=outgoing)


def _send_text_reply(*, incoming: Any, text: str) -> None:
    channel = getattr(incoming, "channel", "evolution")
    if channel == "meta_cloud":
        if meta_cloud_client.enabled:
            meta_cloud_client.send_text(number=incoming.sender, text=text)
        return
    if evolution_client.enabled:
        evolution_client.send_text(number=incoming.sender, text=text)


def _send_outgoing_reply(*, incoming: Any, outgoing: Any) -> None:
    channel = getattr(incoming, "channel", "evolution")
    if channel == "meta_cloud":
        if meta_cloud_client.enabled:
            meta_cloud_client.send_text(number=incoming.sender, text=outgoing.text)
        return
    if evolution_client.enabled:
        evolution_client.send(number=incoming.sender, message=outgoing)


def _queue_incoming_webhook(
    *,
    request: Request,
    incoming: Any,
    requested_area: str,
    event_type_prefix: str = "webhook",
) -> dict[str, Any]:
    try:
        webhook_executor.submit(
            _process_webhook_message,
            incoming=incoming,
            requested_area=requested_area,
            path=request.url.path,
            metadata=_request_metadata(request, message_id=incoming.message_id),
        )
    except Exception as exc:
        _record_security_event(
            request,
            channel=event_type_prefix,
            event_type="queue",
            decision="error",
            phone_number=incoming.sender,
            area=requested_area,
            reason="queue_submit_failed",
        )
        logger.exception("Falha ao enfileirar processamento do webhook: %s", exc)
        return {
            "received": True,
            "handled": False,
            "intent": "queue_error",
            "message_id": incoming.message_id,
        }
    _record_security_event(
        request,
        channel=event_type_prefix,
        event_type="queue",
        decision="accepted",
        phone_number=incoming.sender,
        area=requested_area,
        reason="queued",
    )
    return {
        "received": True,
        "handled": True,
        "intent": "queued",
        "queued": True,
        "message_id": incoming.message_id,
    }


@app.get("/api/client-search")
def api_client_search(
    request: Request,
    q: str,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    if not q.strip():
        raise HTTPException(status_code=400, detail="Parametro q e obrigatorio.")
    _record_security_event(
        request,
        channel="api",
        event_type="client_search",
        decision="deprecated",
        reason="legacy_route_disabled",
    )
    return {
        "handled": False,
        "intent": "legacy_route_disabled",
        "reply": "Essa rota antiga foi desativada. Use /api/dclientes/search ou o fluxo principal do bot.",
    }


@app.get("/api/dclientes/search")
def api_dclientes_search(
    request: Request,
    number: str,
    filial: str | None = None,
    cod_pdv: str | None = None,
    fantasia: str | None = None,
    documento: str | None = None,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area="cliente")
    if not decision.allowed:
        _record_security_event(
            request,
            channel="api",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number,
            area=decision.area,
            reason=decision.reason,
        )
        raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")

    unrestricted_lookup = any(role in {"admin", "financeiro"} for role in decision.roles)
    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    try:
        if documento and documento.strip():
            records = dclientes_query_service.search_by_document(
                document=documento,
                limit=20,
            )
        elif filial and cod_pdv:
            if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
                raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")
            records = dclientes_query_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
            )
        elif fantasia and fantasia.strip():
            if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
                raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")
            records = dclientes_query_service.search_by_fantasia(
                query_text=fantasia,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=5,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar no dClientes.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _record_security_event(
        request,
        channel="api",
        event_type="customer_query",
        decision="allowed",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason="success",
        result_count=len(records),
    )
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }


@app.get("/api/inadimplencia/search")
def api_inadimplencia_search(
    request: Request,
    number: str,
    filial: str | None = None,
    cod_pdv: str | None = None,
    fantasia: str | None = None,
    documento: str | None = None,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area="inadimplencia")
    if not decision.allowed:
        _record_security_event(
            request,
            channel="api",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number,
            area=decision.area,
            reason=decision.reason,
        )
        raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")

    unrestricted_lookup = any(role in {"admin", "financeiro"} for role in decision.roles)
    if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
        raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")

    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    try:
        if filial and cod_pdv:
            records = inadimplencia_query_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif fantasia and fantasia.strip():
            records = inadimplencia_query_service.search_by_name(
                query_text=fantasia,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif documento and documento.strip():
            records = inadimplencia_query_service.search_by_document(
                document=documento,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar na inadimplencia.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _record_security_event(
        request,
        channel="api",
        event_type="inadimplencia_query",
        decision="allowed",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason="success",
        result_count=len(records),
    )
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }


@app.get("/api/comodatos/search")
def api_comodatos_search(
    request: Request,
    number: str,
    filial: str | None = None,
    cod_pdv: str | None = None,
    fantasia: str | None = None,
    documento: str | None = None,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area="comodato")
    if not decision.allowed:
        _record_security_event(
            request,
            channel="api",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number,
            area=decision.area,
            reason=decision.reason,
        )
        raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")

    unrestricted_lookup = any(role in {"admin", "financeiro"} for role in decision.roles)
    if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
        raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")

    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    try:
        if filial and cod_pdv:
            records = comodatos_query_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif fantasia and fantasia.strip():
            records = comodatos_query_service.search_by_name(
                query_text=fantasia,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif documento and documento.strip():
            records = comodatos_query_service.search_by_document(
                document=documento,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar nos comodatos.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _record_security_event(
        request,
        channel="api",
        event_type="comodatos_query",
        decision="allowed",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason="success",
        result_count=len(records),
    )
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }


@app.get("/api/access/check")
def api_access_check(
    request: Request,
    number: str,
    area: str = "conhecimento",
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area=area)
    _record_security_event(
        request,
        channel="api",
        event_type="access_check",
        decision="allowed" if decision.allowed else "denied",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason=decision.reason,
    )
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "normalized_number": decision.normalized_number,
        "area": decision.area,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
    }


@app.get("/api/admin/access/users")
def api_admin_access_users(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    users = _access_call(access_control.list_users)
    _record_security_event(request, channel="api", event_type="admin_list_users", decision="allowed", reason="success")
    return {"total": len(users), "users": users}


@app.post("/api/admin/access/users")
def api_admin_access_users_upsert(
    request: Request,
    payload: AccessUserUpsertRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    user = _access_call(
        access_control.upsert_user,
        phone_number=payload.phone_number,
        name=payload.name,
        is_active=payload.is_active,
        roles=payload.roles,
        sectors=payload.sectors,
        gv_vdes=payload.gv_vdes,
    )
    _record_security_event(
        request,
        channel="api",
        event_type="admin_upsert_user",
        decision="allowed",
        phone_number=user.get("phone_number"),
        reason="success",
    )
    return {"ok": True, "user": user}


@app.get("/api/admin/access/roles")
def api_admin_access_roles(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    roles = _access_call(access_control.list_roles)
    _record_security_event(request, channel="api", event_type="admin_list_roles", decision="allowed", reason="success")
    return {"total": len(roles), "roles": roles}


@app.get("/api/admin/access/permissions")
def api_admin_access_permissions(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    permissions = _access_call(access_control.list_permissions)
    _record_security_event(request, channel="api", event_type="admin_list_permissions", decision="allowed", reason="success")
    return {"total": len(permissions), "permissions": permissions}


@app.post("/api/admin/access/roles")
def api_admin_access_roles_upsert(
    request: Request,
    payload: AccessRoleUpsertRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    role = _access_call(
        access_control.upsert_role,
        role_name=payload.name,
        description=payload.description,
        permissions=payload.permissions,
    )
    _record_security_event(
        request,
        channel="api",
        event_type="admin_upsert_role",
        decision="allowed",
        reason=role.get("name"),
    )
    return {"ok": True, "role": role}


@app.post("/api/admin/access/seed")
def api_admin_access_seed(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    result = _access_call(access_control.seed_defaults)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("reason", "Falha ao inicializar RBAC."))
    _record_security_event(request, channel="api", event_type="admin_seed", decision="allowed", reason="success")
    return result


@app.get("/admin/imports", response_class=HTMLResponse)
def admin_import_panel() -> HTMLResponse:
    return HTMLResponse(content=_load_admin_import_panel_html())


@app.get("/api/admin/imports/status")
def api_admin_imports_status(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    payload = _list_admin_import_status()
    _record_security_event(request, channel="api", event_type="admin_import_status", decision="allowed", reason="success")
    return payload


@app.get("/api/admin/imports/history")
def api_admin_imports_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    payload = _list_admin_import_history(limit=limit)
    _record_security_event(request, channel="api", event_type="admin_import_history", decision="allowed", reason="success")
    return payload


@app.post("/api/admin/imports/validate")
def api_admin_imports_validate(
    request: Request,
    payload: AdminImportActionRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    result = _run_admin_import_validation(payload.dataset)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_import_validate",
        decision="allowed",
        reason=result.get("dataset"),
    )
    return {"ok": True, **result}


@app.post("/api/admin/imports/run", status_code=202)
def api_admin_imports_run(
    request: Request,
    payload: AdminImportActionRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    result = _queue_admin_import(payload.dataset, reference_date=payload.reference_date)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_import_run",
        decision="allowed",
        reason=result.get("dataset"),
    )
    return {"ok": True, "queued": True, **result}


@app.post("/api/admin/imports/upload")
def api_admin_imports_upload(
    request: Request,
    dataset: str = Form(...),
    files: list[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    result = _store_admin_import_uploads(dataset, files)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_import_upload",
        decision="allowed",
        reason=result.get("dataset"),
    )
    return {"ok": True, **result}


@app.post("/webhook/evolution")
def webhook_evolution(
    request: Request,
    payload: dict[str, Any],
    x_bot_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_webhook_token(request=request, x_bot_token=x_bot_token, payload=payload)

    incoming = extract_incoming_message(payload)
    if incoming is None:
        _record_security_event(request, channel="webhook", event_type="incoming_event", decision="ignored", reason="non_processable")
        return {"received": True, "handled": False, "reason": "evento nao processavel"}

    requested_area = "cliente"
    return _queue_incoming_webhook(request=request, incoming=incoming, requested_area=requested_area, event_type_prefix="webhook")


@app.get("/webhook/meta", response_class=PlainTextResponse)
def webhook_meta_verify(
    request: Request,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> str:
    challenge = verify_meta_cloud_webhook_token(
        mode=hub_mode,
        verify_token=hub_verify_token,
        challenge=hub_challenge,
        config=meta_cloud_client.config,
        shared_token=settings.verify_token.strip(),
    )
    if challenge is None:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="meta_verify",
            decision="denied",
            reason="invalid_verify_token",
        )
        raise HTTPException(status_code=403, detail="Token de verificacao invalido.")
    _record_security_event(
        request,
        channel="meta_webhook",
        event_type="meta_verify",
        decision="allowed",
        reason="verify_token",
    )
    return challenge


@app.post("/webhook/meta")
def webhook_meta(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not settings.meta_cloud_enabled:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="incoming_event",
            decision="ignored",
            reason="meta_cloud_disabled",
        )
        return {"received": True, "handled": False, "reason": "meta_cloud_disabled"}

    incoming = extract_meta_cloud_incoming_message(payload)
    if incoming is None:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="incoming_event",
            decision="ignored",
            reason="non_processable",
        )
        return {"received": True, "handled": False, "reason": "evento nao processavel"}

    requested_area = "cliente"
    return _queue_incoming_webhook(
        request=request,
        incoming=incoming,
        requested_area=requested_area,
        event_type_prefix="meta_webhook",
    )
