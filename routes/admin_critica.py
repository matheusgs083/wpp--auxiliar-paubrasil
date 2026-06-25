from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response


def create_admin_critica_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    parse_admin_critica_date: Callable[[str | None], date | None],
    build_admin_critica_dashboard: Callable[..., dict[str, Any]],
    build_admin_critica_sector_pdf_response: Callable[..., Response],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def require_critica_context(
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
        require_admin_panel_feature(context, "critica")
        return context

    @router.get("/api/admin/critica/dashboard")
    def api_admin_critica_dashboard(
        request: Request,
        date_value: str | None = Query(default=None, alias="date"),
        limit: int = Query(default=200, ge=1, le=1000),
        operation: list[str] | None = Query(default=None),
        sector: list[str] | None = Query(default=None),
        seller: list[str] | None = Query(default=None),
        manager: list[str] | None = Query(default=None),
        city: list[str] | None = Query(default=None),
        district: list[str] | None = Query(default=None),
        origin: list[str] | None = Query(default=None),
        problem: list[str] | None = Query(default=None),
        search: str = Query(default=""),
        only_problems: bool = Query(default=True),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_critica_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            payload = build_admin_critica_dashboard(
                context,
                target_date=parse_admin_critica_date(date_value),
                limit=limit,
                operation=operation,
                sector=sector,
                seller=seller,
                manager=manager,
                city=city,
                district=district,
                origin=origin,
                problem=problem,
                search=search,
                only_problems=only_problems,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_critica_dashboard",
            decision="allowed",
            reason=f"total={payload.get('total')}",
        )
        return {"ok": True, **payload}

    @router.get("/api/admin/critica/pdf")
    def api_admin_critica_pdf(
        request: Request,
        operation: str = Query(default=""),
        sector: str = Query(default=""),
        date_value: str | None = Query(default=None, alias="date"),
        summary_only: bool = Query(default=False),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        context = require_critica_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        response = build_admin_critica_sector_pdf_response(
            context,
            operation=operation,
            sector=sector,
            target_date=parse_admin_critica_date(date_value),
            summary_only=summary_only,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_critica_pdf",
            decision="allowed",
            reason=f"{operation}/{sector}|summary={int(bool(summary_only))}",
        )
        return response

    return router
