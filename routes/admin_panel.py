from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel


class AdminPanelLoginRequest(BaseModel):
    token: str


def create_admin_panel_router(
    *,
    admin_panel_context_from_session_cookie: Callable[[Request], dict[str, Any] | None],
    load_admin_login_html: Callable[[], str],
    load_admin_import_panel_html: Callable[[], str],
    check_admin_panel_login_rate_limit: Callable[[Request], None],
    admin_panel_context_from_token: Callable[[str | None], dict[str, Any] | None],
    record_admin_panel_login_failure: Callable[[Request], None],
    clear_admin_panel_login_failures: Callable[[Request], None],
    set_admin_panel_session_cookie: Callable[[Response, Request, dict[str, Any]], None],
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    panel_context_mode: Callable[[dict[str, Any] | None], str],
    record_security_event: Callable[..., None],
    session_cookie_name: str,
    session_ttl_seconds: int,
) -> APIRouter:
    router = APIRouter()

    def no_store_html(content: str) -> HTMLResponse:
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @router.get("/admin/login", response_class=HTMLResponse)
    def admin_login(request: Request) -> Response:
        if admin_panel_context_from_session_cookie(request):
            return RedirectResponse(url="/admin/imports", status_code=303)
        return no_store_html(load_admin_login_html())

    @router.post("/api/admin/panel/login")
    def api_admin_panel_login(
        request: Request,
        response: Response,
        payload: AdminPanelLoginRequest,
    ) -> dict[str, Any]:
        check_admin_panel_login_rate_limit(request)
        context = admin_panel_context_from_token(payload.token)
        if not context:
            record_admin_panel_login_failure(request)
            record_security_event(
                request,
                channel="api",
                event_type="admin_panel_login",
                decision="denied",
                reason="invalid_panel_token",
            )
            raise HTTPException(status_code=401, detail="Token invalido.")
        clear_admin_panel_login_failures(request)
        set_admin_panel_session_cookie(response, request, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_login",
            decision="allowed",
            reason=str(context.get("mode") or "admin"),
        )
        return {
            "ok": True,
            "mode": str(context.get("mode") or "admin"),
            "is_admin": bool(context.get("is_admin")),
            "filiais": list(context.get("filiais", ())),
            "expires_in": session_ttl_seconds,
        }

    @router.post("/api/admin/panel/logout")
    def api_admin_panel_logout(request: Request, response: Response) -> dict[str, Any]:
        response.delete_cookie(session_cookie_name, path="/")
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_logout",
            decision="allowed",
        )
        return {"ok": True}

    @router.get("/admin", response_class=HTMLResponse)
    @router.get("/admin/operations", response_class=HTMLResponse)
    @router.get("/admin/imports", response_class=HTMLResponse)
    @router.get("/admin/reports", response_class=HTMLResponse)
    @router.get("/admin/promax", response_class=HTMLResponse)
    @router.get("/admin/power-bi", response_class=HTMLResponse)
    @router.get("/admin/tables", response_class=HTMLResponse)
    @router.get("/admin/critica", response_class=HTMLResponse)
    @router.get("/admin/recolhas", response_class=HTMLResponse)
    @router.get("/admin/giro-recolha", response_class=HTMLResponse)
    @router.get("/admin/usage", response_class=HTMLResponse)
    def admin_import_panel(request: Request) -> Response:
        if not admin_panel_context_from_session_cookie(request):
            return RedirectResponse(url="/admin/login", status_code=303)
        return no_store_html(load_admin_import_panel_html())

    @router.get("/api/admin/panel/session")
    def api_admin_panel_session(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        mode = panel_context_mode(context) or "admin"
        is_admin = bool(context.get("is_admin"))
        is_finance = mode == "financeiro" and not is_admin
        is_critica = mode == "critica" and not is_admin
        return {
            "ok": True,
            "mode": mode,
            "is_admin": is_admin,
            "filiais": list(context.get("filiais", ())),
            "can_manage_access": is_admin,
            "can_view_usage": is_admin,
            "can_broadcast": is_admin or is_finance,
            "can_import": is_admin or is_finance,
            "can_import_critica": is_admin or is_finance or is_critica,
            "can_manage_recolhas": is_admin or is_finance,
            "can_view_giro": is_admin or is_finance,
            "can_view_critica": is_admin or is_finance or is_critica,
        }

    return router
