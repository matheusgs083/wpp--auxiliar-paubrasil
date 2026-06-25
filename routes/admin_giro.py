from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request


def create_admin_giro_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    build_admin_giro_recolha_dashboard: Callable[..., dict[str, Any]],
    build_admin_giro_recolha_filter_options: Callable[..., dict[str, Any]],
    build_admin_giro_recolha_routes: Callable[..., dict[str, Any]],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def require_giro_context(
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
        require_admin_panel_feature(context, "giro")
        return context

    @router.get("/api/admin/giro/recolha-dashboard")
    def api_admin_giro_recolha_dashboard(
        request: Request,
        limit: int = Query(default=200, ge=1, le=1000),
        min_gap: str = Query(default="1"),
        operation: list[str] | None = Query(default=None),
        city: list[str] | None = Query(default=None),
        district: list[str] | None = Query(default=None),
        seller: list[str] | None = Query(default=None),
        manager: list[str] | None = Query(default=None),
        visit_day: list[str] | None = Query(default=None),
        zero_only: bool = Query(default=False),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_giro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            payload = build_admin_giro_recolha_dashboard(
                context,
                limit=limit,
                min_gap=min_gap,
                operation=operation,
                city=city,
                district=district,
                seller=seller,
                manager=manager,
                visit_day=visit_day,
                zero_only=zero_only,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_giro_recolha_dashboard",
            decision="allowed",
            reason=f"total={payload.get('total')}",
        )
        return {"ok": True, **payload}

    @router.get("/api/admin/giro/recolha-filter-options")
    def api_admin_giro_recolha_filter_options(
        request: Request,
        min_gap: str = Query(default="1"),
        operation: list[str] | None = Query(default=None),
        city: list[str] | None = Query(default=None),
        district: list[str] | None = Query(default=None),
        seller: list[str] | None = Query(default=None),
        manager: list[str] | None = Query(default=None),
        visit_day: list[str] | None = Query(default=None),
        zero_only: bool = Query(default=False),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_giro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            payload = build_admin_giro_recolha_filter_options(
                context,
                min_gap=min_gap,
                operation=operation,
                city=city,
                district=district,
                seller=seller,
                manager=manager,
                visit_day=visit_day,
                zero_only=zero_only,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True, **payload}

    @router.get("/api/admin/giro/recolha-routes")
    def api_admin_giro_recolha_routes(
        request: Request,
        limit: int = Query(default=500, ge=1, le=1000),
        min_gap: str = Query(default="1"),
        operation: list[str] | None = Query(default=None),
        city: list[str] | None = Query(default=None),
        district: list[str] | None = Query(default=None),
        seller: list[str] | None = Query(default=None),
        manager: list[str] | None = Query(default=None),
        visit_day: list[str] | None = Query(default=None),
        zero_only: bool = Query(default=False),
        max_route_size: int = Query(default=12, ge=1, le=50),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_giro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            payload = build_admin_giro_recolha_routes(
                context,
                limit=limit,
                min_gap=min_gap,
                operation=operation,
                city=city,
                district=district,
                seller=seller,
                manager=manager,
                visit_day=visit_day,
                zero_only=zero_only,
                max_route_size=max_route_size,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_giro_recolha_routes",
            decision="allowed",
            reason=f"total={payload.get('total')}",
        )
        return {"ok": True, **payload}

    return router
