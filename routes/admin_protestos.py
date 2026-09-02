from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field


class AdminProtestoUpdateRequest(BaseModel):
    status: str = Field(default="em_acompanhamento", max_length=40)
    observacao: str = Field(default="", max_length=2000)


def create_admin_protestos_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    list_admin_protestos: Callable[..., dict[str, Any]],
    update_admin_protesto: Callable[..., dict[str, Any]],
    upload_admin_protesto_document: Callable[..., dict[str, Any]],
    download_admin_protesto_document: Callable[..., tuple[bytes, str]],
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def require_protestos_context(
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
        require_admin_panel_feature(context, "protestos")
        return context

    def record_panel_action(
        request: Request,
        context: dict[str, Any] | None,
        *,
        action: str,
        target_type: str = "titulo",
        target_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if record_admin_panel_action is None:
            return
        record_admin_panel_action(
            request=request,
            context=context,
            module="protestos",
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
        )

    @router.get("/api/admin/protestos")
    def api_admin_protestos_list(
        request: Request,
        filial: str = Query(default=""),
        search: str = Query(default=""),
        status: str = Query(default=""),
        title_date_from: str = Query(default=""),
        title_date_to: str = Query(default=""),
        protest_date_from: str = Query(default=""),
        protest_date_to: str = Query(default=""),
        limit: int = Query(default=300, ge=1, le=1000),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_protestos_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            payload = list_admin_protestos(
                context=context,
                filial=filial,
                search=search,
                status=status,
                title_date_from=title_date_from,
                title_date_to=title_date_to,
                protest_date_from=protest_date_from,
                protest_date_to=protest_date_to,
                limit=limit,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_protestos_list",
            decision="allowed",
            reason=f"filial={filial or '*'};status={status or '*'}",
        )
        record_panel_action(
            request,
            context,
            action="consultar",
            target_type="filtros",
            metadata={
                "filial": filial,
                "status": status,
                "search": search,
                "title_date_from": title_date_from,
                "title_date_to": title_date_to,
                "protest_date_from": protest_date_from,
                "protest_date_to": protest_date_to,
                "result_count": len(payload.get("titles") or []),
            },
        )
        return payload

    @router.patch("/api/admin/protestos/{titulo_key}")
    def api_admin_protestos_update(
        titulo_key: str,
        payload: AdminProtestoUpdateRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_protestos_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            result = update_admin_protesto(
                titulo_key=titulo_key,
                payload=payload.model_dump(),
                context=context,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_protestos_update", decision="allowed")
        record_panel_action(
            request,
            context,
            action="atualizar",
            target_id=titulo_key,
            metadata={"status": payload.status},
        )
        return result

    @router.post("/api/admin/protestos/{titulo_key}/documentos/{kind}")
    def api_admin_protestos_upload(
        titulo_key: str,
        kind: str,
        request: Request,
        file: UploadFile = File(...),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_protestos_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            result = upload_admin_protesto_document(
                titulo_key=titulo_key,
                kind=kind,
                upload=file,
                context=context,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_protestos_upload",
            decision="allowed",
            reason=f"kind={kind}",
        )
        record_panel_action(
            request,
            context,
            action=f"upload_{kind}",
            target_id=titulo_key,
            metadata={"filename": file.filename or ""},
        )
        return result

    @router.get("/api/admin/protestos/{titulo_key}/documentos/{kind}")
    def api_admin_protestos_download(
        titulo_key: str,
        kind: str,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        context = require_protestos_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            file_bytes, filename = download_admin_protesto_document(
                titulo_key=titulo_key,
                kind=kind,
                context=context,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_protestos_download",
            decision="allowed",
            reason=f"kind={kind}",
        )
        record_panel_action(
            request,
            context,
            action=f"baixar_{kind}",
            target_id=titulo_key,
            metadata={"filename": filename},
        )
        return Response(
            content=file_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
