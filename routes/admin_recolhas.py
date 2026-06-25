from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, File, Header, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field


class AdminRecolhaUpdateRequest(BaseModel):
    lancado_faturista: str | None = None
    motorista_faturista: str | None = None
    placa_faturista: str | None = None
    mapa_faturista: str | None = None
    status_caixa_noturno: str | None = None
    motivo_caixa_noturno: str | None = None


class AdminRecolhaBulkUpdateRequest(AdminRecolhaUpdateRequest):
    ids: list[str] = Field(default_factory=list)


def create_admin_recolhas_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    list_admin_recolhas: Callable[[dict[str, Any] | None], dict[str, Any]],
    update_admin_recolhas_bulk: Callable[[AdminRecolhaBulkUpdateRequest, dict[str, Any] | None], dict[str, Any]],
    import_admin_recolhas_csv: Callable[[UploadFile, dict[str, Any] | None], dict[str, Any]],
    export_admin_recolhas_csv: Callable[..., tuple[bytes, int, str]],
    update_admin_recolha: Callable[[str, AdminRecolhaUpdateRequest, dict[str, Any] | None], dict[str, Any]],
    delete_admin_recolha: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def require_recolhas_context(
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
        require_admin_panel_feature(context, "recolhas")
        return context

    @router.get("/api/admin/recolhas")
    def api_admin_recolhas(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_recolhas_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        payload = list_admin_recolhas(context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_recolhas_list",
            decision="allowed",
            reason=f"total={payload.get('total')}",
        )
        return {"ok": True, **payload}

    @router.patch("/api/admin/recolhas/bulk")
    def api_admin_recolhas_bulk_update(
        request: Request,
        payload: AdminRecolhaBulkUpdateRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_recolhas_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = update_admin_recolhas_bulk(payload, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_recolha_bulk_update",
            decision="allowed",
            reason=f"updated={result.get('updated')};errors={len(result.get('errors') or [])}",
        )
        return {"ok": True, **result}

    @router.post("/api/admin/recolhas/import")
    def api_admin_recolhas_import(
        request: Request,
        file: UploadFile = File(...),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_recolhas_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = import_admin_recolhas_csv(file, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_recolha_import",
            decision="allowed",
            reason=f"imported={result.get('imported')};skipped={result.get('skipped')}",
        )
        return {"ok": True, **result}

    @router.get("/api/admin/recolhas/export")
    def api_admin_recolhas_export(
        request: Request,
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        context = require_recolhas_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        csv_bytes, total, filename = export_admin_recolhas_csv(
            context,
            start_date=start_date,
            end_date=end_date,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_recolha_export",
            decision="allowed",
            reason=f"total={total}",
        )
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.patch("/api/admin/recolhas/{recolha_id}")
    def api_admin_recolhas_update(
        request: Request,
        recolha_id: str,
        payload: AdminRecolhaUpdateRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_recolhas_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = update_admin_recolha(recolha_id, payload, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_recolha_update",
            decision="allowed",
            reason=str(recolha_id or ""),
        )
        return {"ok": True, **result}

    @router.delete("/api/admin/recolhas/{recolha_id}")
    def api_admin_recolhas_delete(
        request: Request,
        recolha_id: str,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_recolhas_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = delete_admin_recolha(recolha_id, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_recolha_delete",
            decision="allowed",
            reason=str(recolha_id or ""),
        )
        return {"ok": True, **result}

    return router
