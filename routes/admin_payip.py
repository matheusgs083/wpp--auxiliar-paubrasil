from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel


class AdminPayipBatchRequest(BaseModel):
    raw_text: str
    use_default_rate: bool = True
    use_default_interest: bool = True
    include_nb: bool = False
    include_nf: bool = False
    mfa_code: str = ""


class AdminPayipPromaxImportRequest(BaseModel):
    filial: str
    start_date: str
    end_date: str
    mfa_code: str = ""
    auto_create_clients: bool = False


def create_admin_payip_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    preview_payip_batch: Callable[[AdminPayipBatchRequest, dict[str, Any] | None], dict[str, Any]],
    queue_payip_batch: Callable[[AdminPayipBatchRequest, dict[str, Any] | None], dict[str, Any]],
    snapshot_payip_batch: Callable[..., dict[str, Any]],
    export_payip_batch_csv: Callable[..., tuple[bytes, str]],
    payip_batch_pdf_bytes: Callable[..., tuple[bytes, str]],
    validate_payip_promax_import: Callable[[AdminPayipPromaxImportRequest, dict[str, Any] | None], dict[str, Any]],
    run_payip_promax_import: Callable[[AdminPayipPromaxImportRequest, dict[str, Any] | None], dict[str, Any]],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def require_payip_context(
        *,
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
        x_admin_token: str | None,
    ) -> dict[str, Any]:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "payip")
        return context

    @router.get("/api/admin/payip/batch/status")
    def api_admin_payip_batch_status(
        request: Request,
        job_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        payload = snapshot_payip_batch(job_id=job_id)
        record_security_event(request, channel="api", event_type="admin_payip_batch_status", decision="allowed")
        return {"ok": True, **payload}

    @router.post("/api/admin/payip/batch/preview")
    def api_admin_payip_batch_preview(
        request: Request,
        payload: AdminPayipBatchRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = preview_payip_batch(payload, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_batch_preview",
            decision="allowed",
            reason=f"total={result.get('total')}",
        )
        return {"ok": True, **result}

    @router.post("/api/admin/payip/batch/run", status_code=202)
    def api_admin_payip_batch_run(
        request: Request,
        payload: AdminPayipBatchRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = queue_payip_batch(payload, context)
        job = result.get("job") if isinstance(result, dict) else {}
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_batch_run",
            decision="allowed",
            reason=f"job_id={job.get('job_id') if isinstance(job, dict) else ''}",
        )
        return {"ok": True, "queued": True, **result}

    @router.post("/api/admin/payip/import/validate")
    def api_admin_payip_import_validate(
        request: Request,
        payload: AdminPayipPromaxImportRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = validate_payip_promax_import(payload, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_import_validate",
            decision="allowed",
            reason=f"filial={payload.filial};items={result.get('items_count')};missing={len(result.get('missing_client_codes') or [])}",
        )
        return {"ok": True, **result}

    @router.post("/api/admin/payip/import/run")
    def api_admin_payip_import_run(
        request: Request,
        payload: AdminPayipPromaxImportRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = run_payip_promax_import(payload, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_import_run",
            decision="allowed",
            reason=f"filial={payload.filial};items={result.get('items_count')};created={len((result.get('client_creation') or {}).get('created') or [])}",
        )
        return {"ok": True, **result}

    @router.get("/api/admin/payip/batch/result")
    def api_admin_payip_batch_result(
        request: Request,
        job_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        payload = snapshot_payip_batch(job_id=job_id)
        record_security_event(request, channel="api", event_type="admin_payip_batch_result", decision="allowed")
        return {"ok": True, **payload}

    @router.get("/api/admin/payip/batch/pdf/{item_id}")
    def api_admin_payip_batch_pdf(
        request: Request,
        item_id: str,
        job_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        pdf_bytes, filename = payip_batch_pdf_bytes(item_id, job_id=job_id)
        record_security_event(request, channel="api", event_type="admin_payip_batch_pdf", decision="allowed", reason=item_id)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/api/admin/payip/batch/export.csv")
    def api_admin_payip_batch_export(
        request: Request,
        job_id: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        csv_bytes, filename = export_payip_batch_csv(job_id=job_id)
        record_security_event(request, channel="api", event_type="admin_payip_batch_export", decision="allowed")
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
