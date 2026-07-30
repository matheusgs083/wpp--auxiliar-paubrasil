from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import json
import logging
import re
import secrets
import shutil
import time

import psycopg
from fastapi import HTTPException, UploadFile

from bot_api.services.admin_import_job_service import AdminImportLockBusy

ADMIN_IMPORT_MAX_WORKERS = 3
ADMIN_IMPORT_HISTORY_RETENTION_DAYS = 3
ADMIN_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
ADMIN_BOLETOS_DATASET_PREFIX = "boletos_bradesco_op_"
ADMIN_IMPORT_LOCAL_TIMEZONE = timezone(timedelta(hours=-3), name="America/Fortaleza")
admin_import_executor = ThreadPoolExecutor(max_workers=ADMIN_IMPORT_MAX_WORKERS, thread_name_prefix="admin-import")
admin_import_lock = Lock()
admin_import_maintenance_lock = Lock()
admin_import_state: dict[str, Any] = {
    "running": False,
    "current_job_id": "",
    "current_dataset": "",
    "started_at": "",
    "reference_date": "",
    "current_jobs": {},
    "last_job": {},
}

logger = logging.getLogger(__name__)
settings: Any = None
ADMIN_IMPORT_DATASETS: dict[str, dict[str, Any]] = {}
ADMIN_IMPORT_RUNTIME_ROOT: Path = Path("/tmp/bot_api_admin_imports")
ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS: set[str] = set()
admin_import_job_service: Any = None
dclientes_import_service: Any = None
giro_import_service: Any = None
critica_rn_import_service: Any = None
critica_operacao_admin_service: Any = None
_clear_critica_runtime_cache: Any = None
_queue_critica_pdf_prebuild: Any = None
_snapshot_critica_pdf_prebuild_state: Any = None
_panel_context_allowed_import_datasets: Any = None
_refresh_filial_labels_runtime: Any = None


def configure(**deps: Any) -> None:
    globals().update(deps)


def shutdown() -> None:
    admin_import_executor.shutdown(wait=False, cancel_futures=False)
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


def _clear_critica_runtime_cache() -> None:
    try:
        critica_rn_query_service.clear_cache()
    except Exception:
        logger.exception("Falha ao limpar cache runtime da critica RN")


def _prebuild_critica_pdf_reports() -> dict[str, Any]:
    try:
        return critica_rn_pdf_prebuild_service.warm_pdf_reports()
    except Exception as exc:
        logger.exception("Falha ao pre-gerar PDFs da critica RN")
        return {"ok": False, "error": str(exc)}


def _new_critica_pdf_prebuild_job_id() -> str:
    return f"critica-pdf-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def _snapshot_critica_pdf_prebuild_state() -> dict[str, Any]:
    with critica_pdf_prebuild_lock:
        return _serialize_admin_import_value(dict(critica_pdf_prebuild_state))


def _critica_pdf_prebuild_worker(job_id: str, reason: str) -> None:
    current_job_id = job_id
    current_reason = reason
    while True:
        started_at = datetime.now(timezone.utc).isoformat()
        with critica_pdf_prebuild_lock:
            critica_pdf_prebuild_state["running"] = True
            critica_pdf_prebuild_state["current_job_id"] = current_job_id
            critica_pdf_prebuild_state["current_reason"] = current_reason
            critica_pdf_prebuild_state["started_at"] = started_at
            critica_pdf_prebuild_state["finished_at"] = ""
            critica_pdf_prebuild_state["last_error"] = ""

        result = _prebuild_critica_pdf_reports()
        finished_at = datetime.now(timezone.utc).isoformat()
        error = ""
        if not result.get("ok"):
            error = str(result.get("error") or "; ".join(result.get("errors") or []) or "Falha ao pre-gerar PDFs.")

        with critica_pdf_prebuild_lock:
            critica_pdf_prebuild_state["finished_at"] = finished_at
            critica_pdf_prebuild_state["last_result"] = _serialize_admin_import_value(result)
            critica_pdf_prebuild_state["last_error"] = error
            if critica_pdf_prebuild_state.get("pending"):
                current_job_id = _new_critica_pdf_prebuild_job_id()
                current_reason = str(critica_pdf_prebuild_state.get("current_reason") or current_reason)
                critica_pdf_prebuild_state["pending"] = False
                critica_pdf_prebuild_state["current_job_id"] = current_job_id
                continue
            critica_pdf_prebuild_state["running"] = False
            critica_pdf_prebuild_state["current_job_id"] = ""
            critica_pdf_prebuild_state["current_reason"] = ""
            return


def _queue_critica_pdf_prebuild(reason: str) -> dict[str, Any]:
    queued_at = datetime.now(timezone.utc).isoformat()
    clean_reason = str(reason or "import").strip() or "import"
    with critica_pdf_prebuild_lock:
        if critica_pdf_prebuild_state.get("running"):
            critica_pdf_prebuild_state["pending"] = True
            critica_pdf_prebuild_state["queued_at"] = queued_at
            critica_pdf_prebuild_state["current_reason"] = clean_reason
            return {
                "ok": True,
                "queued": True,
                "running": True,
                "pending": True,
                "reason": clean_reason,
                "message": "Pre-geracao de PDFs ja estava em andamento; nova rodada marcada para o final.",
            }
        job_id = _new_critica_pdf_prebuild_job_id()
        critica_pdf_prebuild_state["running"] = True
        critica_pdf_prebuild_state["pending"] = False
        critica_pdf_prebuild_state["current_job_id"] = job_id
        critica_pdf_prebuild_state["current_reason"] = clean_reason
        critica_pdf_prebuild_state["queued_at"] = queued_at
        critica_pdf_prebuild_state["started_at"] = ""
        critica_pdf_prebuild_state["finished_at"] = ""
        critica_pdf_prebuild_state["last_error"] = ""

    try:
        critica_pdf_prebuild_executor.submit(_critica_pdf_prebuild_worker, job_id, clean_reason)
    except Exception as exc:
        with critica_pdf_prebuild_lock:
            critica_pdf_prebuild_state["running"] = False
            critica_pdf_prebuild_state["pending"] = False
            critica_pdf_prebuild_state["current_job_id"] = ""
            critica_pdf_prebuild_state["last_error"] = str(exc)
        logger.exception("Falha ao enfileirar pre-geracao de PDFs da critica")
        return {"ok": False, "queued": False, "error": str(exc)}
    return {
        "ok": True,
        "queued": True,
        "running": False,
        "pending": False,
        "job_id": job_id,
        "reason": clean_reason,
    }


def _new_admin_import_job_id(dataset: str, action: str) -> str:
    clean_dataset = _normalize_admin_import_dataset(dataset)
    clean_action = str(action or "job").strip().lower() or "job"
    return f"{clean_action}-{clean_dataset}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def _admin_import_conflict_group(dataset: str) -> str:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    if normalized_dataset in ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS or normalized_dataset.startswith("critica_op_"):
        return "critica_pipeline"
    return normalized_dataset


def _admin_import_lock_keys(dataset: str, action: str) -> list[str]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    clean_action = str(action or "").strip().lower()
    keys = [f"admin-source:{normalized_dataset}"]
    if clean_action == "import":
        keys.append(f"admin-import:{_admin_import_conflict_group(normalized_dataset)}")
    return keys


def _admin_import_actor(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    mode = str(context.get("mode") or "").strip() or "admin"
    if bool(context.get("is_admin")):
        return "admin"
    filiais = ",".join(str(filial).strip() for filial in context.get("filiais", ()) if str(filial).strip())
    return f"{mode}:{filiais}" if filiais else mode


def _parse_admin_upload_reference_date(value: Any) -> date | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ADMIN_IMPORT_LOCAL_TIMEZONE)
        return parsed.date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw_value[:10])
    except ValueError:
        return None


def _admin_upload_reference_date(dataset: str) -> date | None:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    manifest = _read_admin_upload_manifest(normalized_dataset) or {}
    manifest_date = _parse_admin_upload_reference_date(manifest.get("activated_at"))
    if manifest_date:
        return manifest_date
    source_path = _dataset_runtime_upload_path(normalized_dataset)
    if source_path.exists():
        return datetime.fromtimestamp(source_path.stat().st_mtime, tz=ADMIN_IMPORT_LOCAL_TIMEZONE).date()
    return None


def _resolve_admin_import_reference_date(dataset: str, reference_date: str | None = None) -> str:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    upload_date = _admin_upload_reference_date(normalized_dataset)
    if upload_date:
        return upload_date.isoformat()
    return str(reference_date or "").strip()


def _active_admin_import_job(lock_keys: list[str]) -> dict[str, Any] | None:
    try:
        return admin_import_job_service.find_active_job(lock_keys)
    except Exception as exc:
        logger.warning("Falha ao consultar jobs administrativos ativos: %s", exc)
        return None


def _admin_import_busy_message(active_job: dict[str, Any] | None, *, fallback_dataset: str) -> str:
    if active_job:
        label = str(active_job.get("dataset_label") or active_job.get("dataset") or fallback_dataset)
        action = "upload" if str(active_job.get("action") or "") == "upload" else "importacao"
        return f"Ja existe {action} em andamento para {label}. Aguarde finalizar antes de continuar."
    return f"Ja existe uma operacao administrativa em andamento para {fallback_dataset}."


def _run_admin_import_validation(dataset: str, source_path_override: Path | None = None) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    config = ADMIN_IMPORT_DATASETS[normalized_dataset]
    source_path = source_path_override or _resolve_admin_import_source_path(normalized_dataset)
    service = config["service"]
    validation = getattr(service, str(config["validate_method"]))(source_path)
    if normalized_dataset == "dclientes":
        summary = getattr(service, str(config["summarize_method"]))(source_path, validate=False)
    else:
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
    clean_reference_date = _resolve_admin_import_reference_date(normalized_dataset, reference_date)
    batch_date = date.fromisoformat(clean_reference_date) if clean_reference_date else None

    validation_payload = _run_admin_import_validation(normalized_dataset)
    validation_errors = int(validation_payload["validation"].get("error_count") or 0)
    if validation_errors:
        raise HTTPException(status_code=400, detail="A validacao encontrou erros. Corrija o arquivo antes de importar.")

    if normalized_dataset == "dsetores":
        result = getattr(service, str(config["import_method"]))(source_path, reference_date=batch_date)
        refresh_result = dclientes_import_service.refresh_latest_view()
        giro_refresh_result = giro_import_service.refresh_latest_view()
        critica_refresh_result = critica_rn_import_service.refresh_latest_view()
        critica_operacao_refresh_result = critica_operacao_admin_service.refresh_latest_view()
        _clear_critica_runtime_cache()
        prebuild_result = _queue_critica_pdf_prebuild(normalized_dataset)
        return {
            "dataset": normalized_dataset,
            "label": config["label"],
            "default_path": str(source_path),
            "accept_extensions": str(config.get("accept_extensions") or ""),
            "validation": validation_payload["validation"],
            "summary": validation_payload["summary"],
            "import_result": _serialize_admin_import_value(result),
            "post_actions": {
                "refresh_dclientes_view": _serialize_admin_import_value(refresh_result),
                "refresh_giro_view": _serialize_admin_import_value(giro_refresh_result),
                "refresh_critica_rn_view": _serialize_admin_import_value(critica_refresh_result),
                "refresh_critica_operacao_view": _serialize_admin_import_value(critica_operacao_refresh_result),
                "prebuild_critica_pdf_reports": _serialize_admin_import_value(prebuild_result),
            },
        }
    if normalized_dataset == "dclientes":
        result = getattr(service, str(config["import_method"]))(
            source_path,
            reference_date=batch_date,
            summary=validation_payload["summary"],
        )
    else:
        result = getattr(service, str(config["import_method"]))(source_path, reference_date=batch_date)
    post_actions: dict[str, Any] = {}
    if normalized_dataset == "drevendas" and callable(_refresh_filial_labels_runtime):
        post_actions["refresh_filial_labels"] = _serialize_admin_import_value(_refresh_filial_labels_runtime())
    if normalized_dataset == "dprecos":
        post_actions["refresh_critica_rn_view"] = _serialize_admin_import_value(critica_rn_import_service.refresh_latest_view())
        post_actions["refresh_critica_operacao_view"] = _serialize_admin_import_value(
            critica_operacao_admin_service.refresh_latest_view()
        )
    if normalized_dataset in {
        "critica_rn",
        "dclientes",
        "doperacoes",
        "dprecos",
    } or normalized_dataset.startswith("critica_op_"):
        _clear_critica_runtime_cache()
        post_actions["prebuild_critica_pdf_reports"] = _serialize_admin_import_value(
            _queue_critica_pdf_prebuild(normalized_dataset)
        )
    response_payload = {
        "dataset": normalized_dataset,
        "label": config["label"],
        "default_path": str(source_path),
        "accept_extensions": str(config.get("accept_extensions") or ""),
        "validation": validation_payload["validation"],
        "summary": validation_payload["summary"],
        "import_result": _serialize_admin_import_value(result),
    }
    if post_actions:
        response_payload["post_actions"] = post_actions
    return response_payload


def _snapshot_admin_import_state() -> dict[str, Any]:
    with admin_import_lock:
        current_jobs = dict(admin_import_state.get("current_jobs") or {})
        first_job = next(iter(current_jobs.values()), {})
        return _serialize_admin_import_value(
            {
                "running": bool(current_jobs),
                "current_job_id": str(first_job.get("job_id") or ""),
                "current_dataset": str(first_job.get("dataset") or ""),
                "started_at": str(first_job.get("started_at") or ""),
                "reference_date": str(first_job.get("reference_date") or ""),
                "current_jobs": list(current_jobs.values()),
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
    try:
        admin_import_job_service.finish_job(
            job_id=job_id,
            status=status,
            result=_serialize_admin_import_value(result) if result is not None else None,
            error=error,
        )
    except Exception:
        logger.exception("Falha ao atualizar job administrativo %s no banco.", job_id)
    with admin_import_lock:
        current_jobs = admin_import_state.setdefault("current_jobs", {})
        if isinstance(current_jobs, dict):
            current_jobs.pop(job_id, None)
        first_job = next(iter((current_jobs or {}).values()), {}) if isinstance(current_jobs, dict) else {}
        admin_import_state["running"] = bool(current_jobs)
        admin_import_state["current_job_id"] = str(first_job.get("job_id") or "")
        admin_import_state["current_dataset"] = str(first_job.get("dataset") or "")
        admin_import_state["started_at"] = str(first_job.get("started_at") or "")
        admin_import_state["reference_date"] = str(first_job.get("reference_date") or "")
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
    _run_admin_import_maintenance(force_stale=False)


def _admin_import_worker(job_id: str, dataset: str, reference_date: str, started_at: str) -> None:
    try:
        try:
            admin_import_job_service.start_job(job_id)
        except Exception:
            logger.exception("Falha ao marcar job administrativo %s como running.", job_id)
        lock_keys = _admin_import_lock_keys(dataset, "import")
        with admin_import_job_service.operation_lock(lock_keys):
            result = _run_admin_import(dataset, reference_date=reference_date or None)
    except AdminImportLockBusy as exc:
        logger.warning("Importacao %s bloqueada por lock ativo: %s", job_id, exc.lock_key)
        _finish_admin_import_job(
            job_id=job_id,
            dataset=dataset,
            started_at=str(started_at),
            reference_date=reference_date,
            status="blocked",
            result=None,
            error=_admin_import_busy_message(None, fallback_dataset=dataset),
        )
        return
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


def _queue_admin_import(
    dataset: str,
    reference_date: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    clean_reference_date = _resolve_admin_import_reference_date(normalized_dataset, reference_date)
    started_at = datetime.now(timezone.utc).isoformat()
    job_id = _new_admin_import_job_id(normalized_dataset, "import")
    lock_keys = _admin_import_lock_keys(normalized_dataset, "import")
    active_job = _active_admin_import_job(lock_keys)
    if active_job:
        raise HTTPException(
            status_code=409,
            detail=_admin_import_busy_message(active_job, fallback_dataset=normalized_dataset),
        )

    with admin_import_lock:
        try:
            source_path = str(_resolve_admin_import_source_path(normalized_dataset))
        except Exception:
            source_path = ""
        try:
            admin_import_job_service.create_job(
                job_id=job_id,
                action="import",
                dataset_name=normalized_dataset,
                dataset_label=str(ADMIN_IMPORT_DATASETS[normalized_dataset]["label"]),
                lock_keys=lock_keys,
                reference_date=date.fromisoformat(clean_reference_date) if clean_reference_date else None,
                source_path=source_path,
                created_by=_admin_import_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Falha ao criar job administrativo de importacao.")
            raise HTTPException(status_code=503, detail="Nao foi possivel registrar a importacao no banco.") from exc
        current_jobs = admin_import_state.setdefault("current_jobs", {})
        if not isinstance(current_jobs, dict):
            current_jobs = {}
            admin_import_state["current_jobs"] = current_jobs
        current_jobs[job_id] = {
            "job_id": job_id,
            "dataset": normalized_dataset,
            "label": ADMIN_IMPORT_DATASETS[normalized_dataset]["label"],
            "started_at": started_at,
            "reference_date": clean_reference_date,
        }
        admin_import_state["running"] = True
        admin_import_state["current_job_id"] = job_id
        admin_import_state["current_dataset"] = normalized_dataset
        admin_import_state["started_at"] = started_at
        admin_import_state["reference_date"] = clean_reference_date

    try:
        admin_import_executor.submit(_admin_import_worker, job_id, normalized_dataset, clean_reference_date, started_at)
    except Exception:
        with admin_import_lock:
            current_jobs = admin_import_state.setdefault("current_jobs", {})
            if isinstance(current_jobs, dict):
                current_jobs.pop(job_id, None)
            first_job = next(iter((current_jobs or {}).values()), {}) if isinstance(current_jobs, dict) else {}
            admin_import_state["running"] = bool(current_jobs)
            admin_import_state["current_job_id"] = str(first_job.get("job_id") or "")
            admin_import_state["current_dataset"] = str(first_job.get("dataset") or "")
            admin_import_state["started_at"] = str(first_job.get("started_at") or "")
            admin_import_state["reference_date"] = str(first_job.get("reference_date") or "")
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="failed", error="Falha ao enviar job para fila.")
        except Exception:
            logger.exception("Falha ao marcar job administrativo %s como failed.", job_id)
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
    active_path = _active_admin_upload_source_path(dataset)
    if active_path is not None:
        return active_path
    return _legacy_dataset_runtime_upload_path(dataset)


def _dataset_runtime_root(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    return ADMIN_IMPORT_RUNTIME_ROOT / normalized_dataset


def _legacy_dataset_runtime_upload_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    default_path = Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])
    runtime_dir = _dataset_runtime_root(normalized_dataset)
    if ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"] == "single":
        return runtime_dir / default_path.name
    return runtime_dir


def _dataset_active_upload_manifest_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    return _dataset_runtime_root(normalized_dataset) / "active.json"


def _dataset_upload_version_path(dataset: str, job_id: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    default_path = Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])
    clean_job_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(job_id or "").strip()) or secrets.token_hex(8)
    version_root = _dataset_runtime_root(normalized_dataset) / "versions" / clean_job_id
    if ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"] == "single":
        return version_root / default_path.name
    return version_root


def _read_admin_upload_manifest(dataset: str) -> dict[str, Any] | None:
    manifest_path = _dataset_active_upload_manifest_path(dataset)
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Manifesto de upload invalido para %s: %s", dataset, manifest_path)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _active_admin_upload_source_path(dataset: str) -> Path | None:
    payload = _read_admin_upload_manifest(dataset)
    if not payload:
        return None
    source_path = Path(str(payload.get("source_path") or ""))
    if source_path.exists():
        return source_path
    return None


def _activate_admin_upload_version(
    dataset: str,
    *,
    source_path: Path,
    stored_files: list[dict[str, Any]],
    job_id: str,
) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    manifest_path = _dataset_active_upload_manifest_path(normalized_dataset)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset": normalized_dataset,
        "job_id": str(job_id or ""),
        "source_path": str(source_path),
        "stored_files": _serialize_admin_import_value(stored_files),
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    temp_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    temp_path.replace(manifest_path)
    return manifest


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
    except OSError:
        return False
    return child_resolved == parent_resolved or parent_resolved in child_resolved.parents


def _active_admin_upload_protected_paths() -> set[Path]:
    protected: set[Path] = set()
    for dataset_name in ADMIN_IMPORT_DATASETS:
        active_path = _active_admin_upload_source_path(dataset_name)
        if active_path is None:
            continue
        try:
            resolved = active_path.resolve()
        except OSError:
            continue
        protected.add(resolved)
        for parent in resolved.parents:
            if _path_is_within(parent, ADMIN_IMPORT_RUNTIME_ROOT):
                protected.add(parent)
            else:
                break
    return protected


def _prune_admin_upload_versions(keep_days: int = ADMIN_IMPORT_HISTORY_RETENTION_DAYS) -> dict[str, Any]:
    retention_days = max(int(keep_days), 1)
    cutoff_timestamp = time.time() - (retention_days * 24 * 60 * 60)
    root = ADMIN_IMPORT_RUNTIME_ROOT
    if not root.exists():
        return {"ok": True, "deleted": 0, "kept_active": 0, "retention_days": retention_days}
    protected_paths = _active_admin_upload_protected_paths()
    deleted = 0
    kept_active = 0
    errors: list[str] = []

    for dataset_name in ADMIN_IMPORT_DATASETS:
        versions_dir = _dataset_runtime_root(dataset_name) / "versions"
        if not versions_dir.exists() or not versions_dir.is_dir():
            continue
        try:
            candidates = list(versions_dir.iterdir())
        except OSError as exc:
            errors.append(f"{versions_dir}: {exc}")
            continue
        for candidate in candidates:
            try:
                candidate_resolved = candidate.resolve()
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            if not _path_is_within(candidate_resolved, root):
                errors.append(f"{candidate}: fora do diretorio de uploads")
                continue
            if candidate_resolved in protected_paths:
                kept_active += 1
                continue
            try:
                candidate_mtime = candidate.stat().st_mtime
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            if candidate_mtime >= cutoff_timestamp:
                continue
            try:
                if candidate.is_dir():
                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
                deleted += 1
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")

    return {
        "ok": not errors,
        "deleted": deleted,
        "kept_active": kept_active,
        "retention_days": retention_days,
        "errors": errors[:10],
    }


def _run_admin_import_maintenance(*, force_stale: bool = False) -> dict[str, Any]:
    if not admin_import_maintenance_lock.acquire(blocking=False):
        return {"ok": True, "skipped": "maintenance_already_running"}
    try:
        stale_count = 0
        if force_stale:
            stale_count = admin_import_job_service.mark_active_jobs_stale()
        deleted_jobs = admin_import_job_service.prune_old_jobs(keep_days=ADMIN_IMPORT_HISTORY_RETENTION_DAYS)
        deleted_versions = _prune_admin_upload_versions(keep_days=ADMIN_IMPORT_HISTORY_RETENTION_DAYS)
        if force_stale:
            with admin_import_lock:
                admin_import_state["running"] = False
                admin_import_state["current_job_id"] = ""
                admin_import_state["current_dataset"] = ""
                admin_import_state["started_at"] = ""
                admin_import_state["reference_date"] = ""
                admin_import_state["current_jobs"] = {}
        return {
            "ok": True,
            "stale_jobs": stale_count,
            "deleted_jobs": deleted_jobs,
            "upload_versions": deleted_versions,
            "retention_days": ADMIN_IMPORT_HISTORY_RETENTION_DAYS,
        }
    except Exception as exc:
        logger.exception("Falha na manutencao de imports administrativos")
        return {"ok": False, "error": str(exc)}
    finally:
        admin_import_maintenance_lock.release()


def _admin_import_allows_default_source(dataset: str) -> bool:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    return bool(ADMIN_IMPORT_DATASETS[normalized_dataset].get("allow_default_source", True))


def _resolve_admin_import_source_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    runtime_path = _dataset_runtime_upload_path(normalized_dataset)
    if runtime_path.exists():
        return runtime_path
    if not _admin_import_allows_default_source(normalized_dataset):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{ADMIN_IMPORT_DATASETS[normalized_dataset]['label']} exige upload ativo pelo painel. "
                "A pasta data e apenas base de teste e nao sera usada para importacao."
            ),
        )
    return Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])


def _admin_import_source_status(dataset: str) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    runtime_path = _dataset_runtime_upload_path(normalized_dataset)
    legacy_runtime_path = _legacy_dataset_runtime_upload_path(normalized_dataset)
    manifest = _read_admin_upload_manifest(normalized_dataset) or {}
    default_path = Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])
    allow_default = _admin_import_allows_default_source(normalized_dataset)
    if runtime_path.exists():
        active_source_path = runtime_path
        source_exists = True
        using_uploaded_source = True
    elif allow_default:
        active_source_path = default_path
        source_exists = default_path.exists()
        using_uploaded_source = False
    else:
        active_source_path = runtime_path
        source_exists = False
        using_uploaded_source = False
    return {
        "default_path": str(default_path),
        "active_source_path": str(active_source_path),
        "source_exists": source_exists,
        "using_uploaded_source": using_uploaded_source,
        "versioned_upload": bool(manifest),
        "legacy_upload_path": str(legacy_runtime_path),
        "active_upload_job_id": str(manifest.get("job_id") or ""),
        "active_upload_activated_at": str(manifest.get("activated_at") or ""),
        "requires_upload": not allow_default,
    }



def _copy_upload_with_limit(upload: UploadFile, buffer: Any) -> int:
    max_bytes = settings.admin_upload_max_file_size_mb * 1024 * 1024
    total_bytes = 0
    while True:
        chunk = upload.file.read(ADMIN_UPLOAD_CHUNK_SIZE_BYTES)
        if not chunk:
            break
        total_bytes += len(chunk)
        if max_bytes > 0 and total_bytes > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Arquivo excede o limite de {settings.admin_upload_max_file_size_mb} MB.",
            )
        buffer.write(chunk)
    return total_bytes
def _replace_single_upload_source(
    dataset: str,
    files: list[UploadFile],
    target_path: Path | None = None,
) -> list[dict[str, Any]]:
    if len(files) != 1:
        raise HTTPException(status_code=400, detail="Esse dataset aceita exatamente um arquivo por vez.")

    target_path = target_path or _legacy_dataset_runtime_upload_path(dataset)
    upload = files[0]
    _sanitize_uploaded_filename(dataset, upload.filename or "")
    temp_path = target_path.with_name(f"{target_path.name}.uploading")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with temp_path.open("wb") as buffer:
            _copy_upload_with_limit(upload, buffer)
        temp_path.replace(target_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        upload.file.close()

    return [
        {
            "saved_as": str(target_path),
            "uploaded_name": str(upload.filename or ""),
            "size_bytes": int(target_path.stat().st_size),
        }
    ]


def _replace_multiple_upload_source(
    dataset: str,
    files: list[UploadFile],
    target_dir: Path | None = None,
) -> list[dict[str, Any]]:
    if not files:
        raise HTTPException(status_code=400, detail="Selecione pelo menos um arquivo para upload.")

    target_dir = target_dir or _legacy_dataset_runtime_upload_path(dataset)
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
                    _copy_upload_with_limit(upload, buffer)
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


def _close_admin_upload_files(files: list[UploadFile]) -> None:
    for upload in files:
        try:
            upload.file.close()
        except Exception:
            pass


def _store_admin_import_uploads(
    dataset: str,
    files: list[UploadFile],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    if len(files) > settings.admin_upload_max_file_count:
        _close_admin_upload_files(files)
        raise HTTPException(
            status_code=413,
            detail=f"Upload permite no maximo {settings.admin_upload_max_file_count} arquivo(s) por requisicao.",
        )
    file_names = [str(upload.filename or "") for upload in files]
    lock_keys = _admin_import_lock_keys(normalized_dataset, "upload")
    active_job = _active_admin_import_job(lock_keys)
    if active_job:
        _close_admin_upload_files(files)
        raise HTTPException(
            status_code=409,
            detail=_admin_import_busy_message(active_job, fallback_dataset=normalized_dataset),
        )

    job_id = _new_admin_import_job_id(normalized_dataset, "upload")
    upload_mode = ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"]
    version_source_path = _dataset_upload_version_path(normalized_dataset, job_id)
    try:
        admin_import_job_service.create_job(
            job_id=job_id,
            action="upload",
            dataset_name=normalized_dataset,
            dataset_label=str(ADMIN_IMPORT_DATASETS[normalized_dataset]["label"]),
            lock_keys=lock_keys,
            source_path=str(version_source_path),
            file_names=file_names,
            created_by=_admin_import_actor(context),
            metadata={"upload_mode": upload_mode},
        )
        admin_import_job_service.start_job(job_id)
        with admin_import_job_service.operation_lock(lock_keys):
            if upload_mode == "single":
                stored_files = _replace_single_upload_source(normalized_dataset, files, target_path=version_source_path)
            else:
                stored_files = _replace_multiple_upload_source(normalized_dataset, files, target_dir=version_source_path)

            validation_result = _run_admin_import_validation(normalized_dataset, source_path_override=version_source_path)
            validation_errors = int(validation_result["validation"].get("error_count") or 0)
            if validation_errors:
                raise HTTPException(
                    status_code=400,
                    detail="A validacao encontrou erros. A versao enviada foi salva, mas nao foi ativada.",
                )
            active_manifest = _activate_admin_upload_version(
                normalized_dataset,
                source_path=version_source_path,
                stored_files=stored_files,
                job_id=job_id,
            )
            result = {
                "job_id": job_id,
                "dataset": normalized_dataset,
                "label": ADMIN_IMPORT_DATASETS[normalized_dataset]["label"],
                "default_path": str(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"]),
                "active_source_path": str(_resolve_admin_import_source_path(normalized_dataset)),
                "upload_mode": upload_mode,
                "stored_files": stored_files,
                "active_upload": active_manifest,
                "validation": validation_result["validation"],
                "summary": validation_result["summary"],
            }
        admin_import_job_service.finish_job(
            job_id=job_id,
            status="completed",
            result=_serialize_admin_import_value(result),
            error="",
        )
        _run_admin_import_maintenance(force_stale=False)
        return result
    except AdminImportLockBusy as exc:
        _close_admin_upload_files(files)
        error = _admin_import_busy_message(None, fallback_dataset=normalized_dataset)
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="blocked", error=error)
            _run_admin_import_maintenance(force_stale=False)
        except Exception:
            logger.exception("Falha ao marcar upload administrativo %s como blocked.", job_id)
        raise HTTPException(status_code=409, detail=error) from exc
    except HTTPException as exc:
        _close_admin_upload_files(files)
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="failed", error=_format_admin_import_error(exc))
            _run_admin_import_maintenance(force_stale=False)
        except Exception:
            logger.exception("Falha ao marcar upload administrativo %s como failed.", job_id)
        raise
    except Exception as exc:
        _close_admin_upload_files(files)
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="failed", error=_format_admin_import_error(exc))
            _run_admin_import_maintenance(force_stale=False)
        except Exception:
            logger.exception("Falha ao marcar upload administrativo %s como failed.", job_id)
        raise


def _list_admin_import_status() -> dict[str, Any]:
    dataset_rows: dict[str, dict[str, Any]] = {}
    database_error = ""
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
    try:
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
    except Exception as exc:
        database_error = str(exc)
        logger.warning("Falha ao consultar status das importacoes no banco: %s", exc)

    items: list[dict[str, Any]] = []
    for dataset_name, config in ADMIN_IMPORT_DATASETS.items():
        runtime_path = _dataset_runtime_upload_path(dataset_name)
        source_status = _admin_import_source_status(dataset_name)
        items.append(
            {
                "dataset": dataset_name,
                "label": config["label"],
                "default_path": source_status["default_path"],
                "active_source_path": source_status["active_source_path"],
                "source_exists": bool(source_status["source_exists"]),
                "using_uploaded_source": runtime_path.exists(),
                "requires_upload": bool(source_status["requires_upload"]),
                "upload_mode": str(config.get("upload_mode") or "single"),
                "accept_extensions": str(config.get("accept_extensions") or ""),
                "active_upload_activated_at": source_status.get("active_upload_activated_at", ""),
                "last_import": dataset_rows.get(dataset_name),
            }
        )

    state_snapshot = _snapshot_admin_import_state()
    state_snapshot["items"] = items
    state_snapshot["database_error"] = database_error
    state_snapshot["critica_pdf_prebuild"] = _snapshot_critica_pdf_prebuild_state()
    try:
        state_snapshot["jobs"] = _serialize_admin_import_value(admin_import_job_service.list_recent_jobs(limit=10))
        state_snapshot["jobs_error"] = ""
    except Exception as exc:
        logger.warning("Falha ao consultar jobs administrativos recentes: %s", exc)
        state_snapshot["jobs"] = []
        state_snapshot["jobs_error"] = str(exc)
    return state_snapshot


def _list_admin_import_history(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    history: list[dict[str, Any]] = []
    database_error = ""
    query = """
        SELECT dataset_name, id, source_file, file_hash, reference_date, total_rows, imported_at
        FROM reports.import_batches
        WHERE dataset_name = ANY(%s)
          AND imported_at >= NOW() - (%s::int * INTERVAL '1 day')
        ORDER BY imported_at DESC, id DESC
        LIMIT %s
    """
    try:
        with psycopg.connect(settings.reports_runtime_database_url, connect_timeout=int(settings.access_database_timeout_seconds)) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (list(ADMIN_IMPORT_DATASETS.keys()), ADMIN_IMPORT_HISTORY_RETENTION_DAYS, safe_limit))
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
    except Exception as exc:
        database_error = str(exc)
        logger.warning("Falha ao consultar historico de importacoes no banco: %s", exc)
    jobs: list[dict[str, Any]] = []
    jobs_error = ""
    try:
        jobs = _serialize_admin_import_value(admin_import_job_service.list_recent_jobs(limit=safe_limit))
    except Exception as exc:
        jobs_error = str(exc)
        logger.warning("Falha ao consultar historico de jobs administrativos: %s", exc)
    return {
        "total": len(history),
        "history": history,
        "jobs": jobs,
        "jobs_error": jobs_error,
        "database_error": database_error,
    }


def _panel_context_visible_import_datasets(context: dict[str, Any] | None) -> set[str] | None:
    return _panel_context_allowed_import_datasets(context)


def _admin_import_payload_dataset(payload: dict[str, Any]) -> str:
    return str(payload.get("dataset") or payload.get("dataset_name") or "").strip()


def _filter_admin_import_status_for_context(
    payload: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    visible_datasets = _panel_context_visible_import_datasets(context)
    if visible_datasets is None:
        return payload
    filtered = dict(payload)
    filtered_items = [
        item
        for item in payload.get("items", [])
        if isinstance(item, dict) and _admin_import_payload_dataset(item) in visible_datasets
    ]
    filtered_current_jobs = [
        job
        for job in payload.get("current_jobs", [])
        if isinstance(job, dict) and _admin_import_payload_dataset(job) in visible_datasets
    ]
    filtered_jobs = [
        job
        for job in payload.get("jobs", [])
        if isinstance(job, dict) and _admin_import_payload_dataset(job) in visible_datasets
    ]
    first_job = filtered_current_jobs[0] if filtered_current_jobs else {}
    last_job = payload.get("last_job") if isinstance(payload.get("last_job"), dict) else {}
    if _admin_import_payload_dataset(last_job) not in visible_datasets:
        last_job = {}
    filtered.update(
        {
            "running": bool(filtered_current_jobs),
            "current_job_id": str(first_job.get("job_id") or ""),
            "current_dataset": str(first_job.get("dataset") or ""),
            "started_at": str(first_job.get("started_at") or ""),
            "reference_date": str(first_job.get("reference_date") or ""),
            "current_jobs": filtered_current_jobs,
            "items": filtered_items,
            "jobs": filtered_jobs,
            "last_job": last_job,
        }
    )
    return filtered


def _filter_admin_import_history_for_context(
    payload: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    visible_datasets = _panel_context_visible_import_datasets(context)
    if visible_datasets is None:
        return payload
    filtered = dict(payload)
    history = [
        item
        for item in payload.get("history", [])
        if isinstance(item, dict) and _admin_import_payload_dataset(item) in visible_datasets
    ]
    jobs = [
        item
        for item in payload.get("jobs", [])
        if isinstance(item, dict) and _admin_import_payload_dataset(item) in visible_datasets
    ]
    filtered.update({"total": len(history), "history": history, "jobs": jobs})
    return filtered



