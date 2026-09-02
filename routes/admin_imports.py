from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from pydantic import BaseModel


class AdminImportActionRequest(BaseModel):
    dataset: str
    reference_date: str | None = None


def create_admin_imports_router(
    *,
    access_call: Callable[..., Any],
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    require_admin_panel_import_dataset: Callable[[dict[str, Any] | None, str], str],
    list_admin_import_status: Callable[[], dict[str, Any]],
    filter_admin_import_status_for_context: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]],
    list_admin_import_history: Callable[..., dict[str, Any]],
    filter_admin_import_history_for_context: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]],
    run_admin_import_validation: Callable[..., dict[str, Any]],
    queue_admin_import: Callable[..., dict[str, Any]],
    store_admin_import_uploads: Callable[..., dict[str, Any]],
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def require_panel_auth(
        *,
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
        x_admin_token: str | None,
    ) -> dict[str, Any]:
        return require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )

    def record_panel_action(
        request: Request,
        context: dict[str, Any] | None,
        *,
        action: str,
        target_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if record_admin_panel_action is None:
            return
        record_admin_panel_action(
            request=request,
            context=context,
            module="relatorios",
            action=action,
            target_type="dataset",
            target_id=target_id,
            metadata=metadata or {},
        )

    @router.get("/api/admin/imports/status")
    def api_admin_imports_status(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "import_status")
        payload = list_admin_import_status()
        payload = filter_admin_import_status_for_context(payload, context)
        record_security_event(request, channel="api", event_type="admin_import_status", decision="allowed", reason="success")
        return payload

    @router.get("/api/admin/imports/history")
    def api_admin_imports_history(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "import_status")
        payload = list_admin_import_history(limit=limit)
        payload = filter_admin_import_history_for_context(payload, context)
        record_security_event(request, channel="api", event_type="admin_import_history", decision="allowed", reason="success")
        return payload

    @router.post("/api/admin/imports/validate")
    def api_admin_imports_validate(
        request: Request,
        payload: AdminImportActionRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        normalized_dataset = require_admin_panel_import_dataset(context, payload.dataset)
        result = access_call(run_admin_import_validation, normalized_dataset)
        record_security_event(
            request,
            channel="api",
            event_type="admin_import_validate",
            decision="allowed",
            reason=result.get("dataset"),
        )
        record_panel_action(request, context, action="validar", target_id=str(result.get("dataset") or normalized_dataset))
        return {"ok": True, **result}

    @router.post("/api/admin/imports/run", status_code=202)
    def api_admin_imports_run(
        request: Request,
        payload: AdminImportActionRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        normalized_dataset = require_admin_panel_import_dataset(context, payload.dataset)
        result = queue_admin_import(normalized_dataset, reference_date=payload.reference_date, context=context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_import_run",
            decision="allowed",
            reason=result.get("dataset"),
        )
        record_panel_action(
            request,
            context,
            action="importar",
            target_id=str(result.get("dataset") or normalized_dataset),
            metadata={"reference_date": payload.reference_date, "job_id": result.get("job_id")},
        )
        return {"ok": True, "queued": True, **result}

    @router.post("/api/admin/imports/upload")
    def api_admin_imports_upload(
        request: Request,
        dataset: str = Form(...),
        files: list[UploadFile] = File(...),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        normalized_dataset = require_admin_panel_import_dataset(context, dataset)
        result = access_call(store_admin_import_uploads, normalized_dataset, files, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_import_upload",
            decision="allowed",
            reason=result.get("dataset"),
        )
        record_panel_action(
            request,
            context,
            action="upload",
            target_id=str(result.get("dataset") or normalized_dataset),
            metadata={"files": len(files), "reference_date": result.get("reference_date")},
        )
        return {"ok": True, **result}

    return router
