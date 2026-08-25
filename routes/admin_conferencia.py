from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field


class ConferenciaCountsRequest(BaseModel):
    counts: list[dict[str, Any]] = Field(default_factory=list)


def create_admin_conferencia_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    panel_context_can_access_feature: Callable[[dict[str, Any] | None, str], bool],
    list_conferencia_mapas: Callable[..., dict[str, Any]],
    list_conferencia_garrafeiras: Callable[..., dict[str, Any]],
    get_conferencia_mapa: Callable[..., dict[str, Any]],
    save_conferencia_counts: Callable[..., dict[str, Any]],
    search_conferencia_products: Callable[..., dict[str, Any]],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def require_conferencia_context(
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
        require_admin_panel_feature(context, "conferencia")
        return context

    def can_reveal_totals(context: dict[str, Any] | None) -> bool:
        mode = str((context or {}).get("mode") or "").strip().lower()
        return bool((context or {}).get("is_admin")) or mode == "financeiro"

    @router.get("/api/admin/conferencia/mapas")
    def api_admin_conferencia_mapas(
        request: Request,
        data: str,
        filial: str = "",
        search: str = "",
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_conferencia_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            payload = list_conferencia_mapas(
                data=data,
                filial=filial,
                search=search,
                context=context,
                reveal_totals=can_reveal_totals(context),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_conferencia_list",
            decision="allowed",
            reason=f"data={data}; filial={filial or '*'}",
        )
        return payload

    @router.get("/api/admin/conferencia/garrafeiras")
    def api_admin_conferencia_garrafeiras(
        request: Request,
        data: str,
        filial: str = "",
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_conferencia_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        if not can_reveal_totals(context):
            raise HTTPException(status_code=403, detail="Consolidado liberado apenas para financeiro.")
        try:
            payload = list_conferencia_garrafeiras(
                data=data,
                filial=filial,
                context=context,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_conferencia_garrafeiras",
            decision="allowed",
            reason=f"data={data}; filial={filial or '*'}",
        )
        return payload

    @router.get("/api/admin/conferencia/produtos")
    def api_admin_conferencia_products(
        request: Request,
        search: str = "",
        limit: int = 20,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_conferencia_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        payload = search_conferencia_products(search=search, limit=limit, context=context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_conferencia_product_search",
            decision="allowed",
            reason=f"search={search[:40]}",
        )
        return payload

    @router.get("/api/admin/conferencia/mapas/{mapa_id}")
    def api_admin_conferencia_mapa_detail(
        mapa_id: int,
        request: Request,
        search: str = "",
        grupo: str = "",
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_conferencia_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            payload = get_conferencia_mapa(
                mapa_id,
                context=context,
                reveal_totals=can_reveal_totals(context),
                item_search=search,
                grupo=grupo,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_conferencia_detail",
            decision="allowed",
            reason=f"mapa_id={mapa_id}",
        )
        return payload

    @router.post("/api/admin/conferencia/mapas/{mapa_id}/contagens")
    def api_admin_conferencia_save_counts(
        mapa_id: int,
        payload: ConferenciaCountsRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_conferencia_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            result = save_conferencia_counts(mapa_id, counts=payload.counts, context=context)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_conferencia_save",
            decision="allowed",
            reason=f"mapa_id={mapa_id}; rows={len(payload.counts)}",
        )
        return result

    return router
