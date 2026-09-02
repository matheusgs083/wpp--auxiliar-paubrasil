from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, Field


class AdminPayipBatchRequest(BaseModel):
    raw_text: str
    use_default_rate: bool = True
    use_default_interest: bool = True
    include_nb: bool = False
    include_nf: bool = False
    auto_create_clients: bool = False
    mfa_code: str = ""


class AdminPayipPromaxImportRequest(BaseModel):
    filial: str
    start_date: str
    end_date: str
    mfa_code: str = ""
    auto_create_clients: bool = False


class AdminPayipPromaxCreateClientsRequest(BaseModel):
    filial: str
    start_date: str = ""
    end_date: str = ""
    missing_client_codes: list[str] = Field(default_factory=list)
    mfa_code: str = ""


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
    create_payip_promax_import_clients: Callable[[AdminPayipPromaxCreateClientsRequest, dict[str, Any] | None], dict[str, Any]],
    run_payip_promax_import: Callable[[AdminPayipPromaxImportRequest, dict[str, Any] | None], dict[str, Any]],
    list_payip_generated_batches: Callable[..., dict[str, Any]],
    payip_generated_batch_process: Callable[..., dict[str, Any]],
    payip_generated_batch_file_bytes: Callable[..., tuple[bytes, str, str]],
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
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

    def record_panel_action(
        request: Request,
        context: dict[str, Any] | None,
        *,
        action: str,
        target_type: str = "",
        target_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if record_admin_panel_action is None:
            return
        record_admin_panel_action(
            request=request,
            context=context,
            module="payip",
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
        )

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

    @router.get("/api/admin/payip/generated-batches")
    def api_admin_payip_generated_batches(
        request: Request,
        filial: str = Query(default=""),
        page_size: int = Query(default=50, ge=1, le=200),
        mfa_code: str = Query(default=""),
        x_payip_mfa_code: str | None = Header(default=None),
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
        payload = list_payip_generated_batches(
            filial=filial,
            context=context,
            page_size=page_size,
            mfa_code=x_payip_mfa_code or mfa_code,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_generated_batches",
            decision="allowed",
            reason=f"filial={filial};items={payload.get('items_count')}",
        )
        record_panel_action(request, context, action="listar_lotes", target_type="filial", target_id=filial, metadata={"items": payload.get("items_count")})
        return {"ok": True, **payload}

    @router.post("/api/admin/payip/generated-batches/{batch_id}/process")
    def api_admin_payip_generated_batch_process(
        request: Request,
        batch_id: str,
        filial: str = Query(default=""),
        kind: str = Query(default=""),
        mfa_code: str = Query(default=""),
        x_payip_mfa_code: str | None = Header(default=None),
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
        payload = payip_generated_batch_process(
            filial=filial,
            batch_id=batch_id,
            kind=kind,
            context=context,
            mfa_code=x_payip_mfa_code or mfa_code,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_generated_batch_process",
            decision="allowed",
            reason=f"filial={filial};batch={batch_id};kind={kind}",
        )
        record_panel_action(
            request,
            context,
            action="gerar_arquivo_lote",
            target_type="lote",
            target_id=batch_id,
            metadata={"filial": filial, "kind": kind},
        )
        return {"ok": True, **payload}

    @router.get("/api/admin/payip/generated-batches/{batch_id}/pdf")
    def api_admin_payip_generated_batch_file(
        request: Request,
        batch_id: str,
        filial: str = Query(default=""),
        kind: str = Query(default=""),
        mfa_code: str = Query(default=""),
        x_payip_mfa_code: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        context = require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        file_bytes, filename, media_type = payip_generated_batch_file_bytes(
            filial=filial,
            batch_id=batch_id,
            kind=kind,
            context=context,
            mfa_code=x_payip_mfa_code or mfa_code,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_generated_batch_file",
            decision="allowed",
            reason=f"filial={filial};batch={batch_id};kind={kind}",
        )
        record_panel_action(
            request,
            context,
            action="baixar_arquivo_lote",
            target_type="lote",
            target_id=batch_id,
            metadata={"filial": filial, "kind": kind, "filename": filename},
        )
        return Response(
            content=file_bytes,
            media_type=media_type or "application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

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
        record_panel_action(request, context, action="validar_lote_manual", metadata={"total": result.get("total"), "items": result.get("items_count")})
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
        record_panel_action(
            request,
            context,
            action="gerar_cobrancas_lote_manual",
            target_type="job",
            target_id=str(job.get("job_id") if isinstance(job, dict) else ""),
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
        record_panel_action(
            request,
            context,
            action="validar_importacao_automatica",
            target_type="filial",
            target_id=payload.filial,
            metadata={"start_date": payload.start_date, "end_date": payload.end_date, "items": result.get("items_count"), "missing": len(result.get("missing_client_codes") or [])},
        )
        return {"ok": True, **result}

    @router.post("/api/admin/payip/import/create-clients")
    def api_admin_payip_import_create_clients(
        request: Request,
        payload: AdminPayipPromaxCreateClientsRequest,
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
        result = create_payip_promax_import_clients(payload, context)
        creation = result.get("client_creation") if isinstance(result, dict) else {}
        record_security_event(
            request,
            channel="api",
            event_type="admin_payip_import_create_clients",
            decision="allowed",
            reason=f"filial={payload.filial};created={len((creation or {}).get('created') or [])};failed={len((creation or {}).get('failed') or [])}",
        )
        record_panel_action(
            request,
            context,
            action="criar_clientes_faltantes",
            target_type="filial",
            target_id=payload.filial,
            metadata={"start_date": payload.start_date, "end_date": payload.end_date, "requested": len(payload.missing_client_codes), "created": len((creation or {}).get("created") or []), "failed": len((creation or {}).get("failed") or [])},
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
        record_panel_action(
            request,
            context,
            action="confirmar_importacao_automatica",
            target_type="filial",
            target_id=payload.filial,
            metadata={"start_date": payload.start_date, "end_date": payload.end_date, "items": result.get("items_count")},
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
        context = require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        pdf_bytes, filename = payip_batch_pdf_bytes(item_id, job_id=job_id)
        record_security_event(request, channel="api", event_type="admin_payip_batch_pdf", decision="allowed", reason=item_id)
        record_panel_action(request, context, action="baixar_pdf_cobranca", target_type="item", target_id=item_id, metadata={"job_id": job_id, "filename": filename})
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
        context = require_payip_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        csv_bytes, filename = export_payip_batch_csv(job_id=job_id)
        record_security_event(request, channel="api", event_type="admin_payip_batch_export", decision="allowed")
        record_panel_action(request, context, action="exportar_lote_manual_csv", target_type="job", target_id=str(job_id or ""), metadata={"filename": filename})
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
