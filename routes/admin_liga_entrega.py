
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field


class LigaEntregaExpurgoRequest(BaseModel):
    tipo: str = Field(..., description="devolucao, km, tml ou dispersao")
    competencia: str = Field(..., description="AAAA-MM")
    filial: str = ""
    data: str = ""
    mapa: str = ""
    cliente: str = ""
    motivo: str = ""
    observacao: str = ""
    active: bool = True


def create_admin_liga_entrega_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    liga_entrega_expurgo_service: Any,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def require_liga_context(
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
        require_admin_panel_feature(context, "reports")
        return context

    def actor_from_context(context: dict[str, Any] | None) -> str:
        if not context:
            return ""
        if context.get("is_admin"):
            return "admin"
        mode = str(context.get("mode") or "").strip()
        user_id = str(context.get("user_id") or context.get("phone") or "").strip()
        return f"{mode}:{user_id}" if user_id else mode

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
            module="liga_entrega",
            action=action,
            target_type="expurgo",
            target_id=target_id,
            metadata=metadata or {},
        )

    @router.get("/api/admin/liga-entrega/expurgos")
    def api_admin_liga_entrega_expurgos(
        request: Request,
        competencia: str | None = Query(default=None),
        tipo: str | None = Query(default=None),
        active_only: bool = Query(default=True),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            result = liga_entrega_expurgo_service.list_expurgos(
                competencia=competencia,
                tipo=tipo,
                active_only=active_only,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_liga_expurgos_list", decision="allowed", reason=f"total={result.get('total')}")
        return {"ok": True, **result}

    @router.post("/api/admin/liga-entrega/expurgos")
    def api_admin_liga_entrega_expurgo_upsert(
        request: Request,
        payload: LigaEntregaExpurgoRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            item = liga_entrega_expurgo_service.upsert_expurgo(
                payload.model_dump(),
                actor=actor_from_context(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_liga_expurgo_upsert", decision="allowed", reason=str(item.get("id") or ""))
        record_panel_action(request, context, action="salvar_expurgo", target_id=str(item.get("id") or ""), metadata={"tipo": item.get("tipo"), "competencia": item.get("competencia")})
        return {"ok": True, "item": item}

    @router.delete("/api/admin/liga-entrega/expurgos/{expurgo_id}")
    def api_admin_liga_entrega_expurgo_delete(
        expurgo_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            item = liga_entrega_expurgo_service.delete_expurgo(expurgo_id, actor=actor_from_context(context))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_liga_expurgo_delete", decision="allowed", reason=str(item.get("id") or expurgo_id))
        record_panel_action(request, context, action="remover_expurgo", target_id=str(item.get("id") or expurgo_id), metadata={"tipo": item.get("tipo"), "competencia": item.get("competencia")})
        return {"ok": True, "item": item}

    return router
