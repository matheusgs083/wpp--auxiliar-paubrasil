from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field


class AdminPanelLoginRequest(BaseModel):
    token: str | None = None
    username: str | None = None
    password: str | None = None


class AdminPanelChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)


class AdminPanelUserCreateRequest(BaseModel):
    username: str
    display_name: str = ""
    is_admin: bool = False
    is_active: bool = True
    filiais: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)


class AdminPanelUserUpdateRequest(BaseModel):
    display_name: str = ""
    is_admin: bool = False
    is_active: bool = True
    filiais: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)


def create_admin_panel_router(
    *,
    admin_panel_context_from_session_cookie: Callable[[Request], dict[str, Any] | None],
    load_admin_login_html: Callable[[], str],
    load_admin_change_password_html: Callable[[], str],
    load_admin_import_panel_html: Callable[[], str],
    check_admin_panel_login_rate_limit: Callable[[Request], None],
    admin_panel_context_from_token: Callable[[str | None], dict[str, Any] | None],
    admin_panel_context_from_credentials: Callable[[str | None, str | None], dict[str, Any] | None],
    record_admin_panel_login_failure: Callable[[Request], None],
    clear_admin_panel_login_failures: Callable[[Request], None],
    set_admin_panel_session_cookie: Callable[[Response, Request, dict[str, Any]], None],
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    panel_context_mode: Callable[[dict[str, Any] | None], str],
    panel_context_can_access_feature: Callable[[dict[str, Any] | None, str], bool],
    admin_panel_user_service: Any,
    record_security_event: Callable[..., None],
    session_cookie_name: str,
    session_ttl_seconds: int,
) -> APIRouter:
    router = APIRouter()
    admin_panel_csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    def no_store_html(content: str) -> HTMLResponse:
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Robots-Tag": "noindex, nofollow",
                "Content-Security-Policy": admin_panel_csp,
            },
        )

    def no_store_redirect(url: str) -> RedirectResponse:
        return RedirectResponse(
            url=url,
            status_code=303,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @router.get("/admin/login", response_class=HTMLResponse)
    def admin_login(request: Request) -> Response:
        context = admin_panel_context_from_session_cookie(request)
        if context and bool(context.get("must_change_password")):
            return no_store_redirect("/admin/change-password")
        if context:
            return no_store_redirect("/admin/imports")
        return no_store_html(load_admin_login_html())

    @router.get("/admin/change-password", response_class=HTMLResponse)
    def admin_change_password(request: Request) -> Response:
        context = admin_panel_context_from_session_cookie(request)
        if not context:
            return no_store_redirect("/admin/login")
        if str(context.get("auth_type") or "") != "user":
            return no_store_redirect("/admin/imports")
        return no_store_html(load_admin_change_password_html())

    @router.post("/api/admin/panel/login")
    def api_admin_panel_login(
        request: Request,
        response: Response,
        payload: AdminPanelLoginRequest,
    ) -> dict[str, Any]:
        check_admin_panel_login_rate_limit(request)
        login_with_user = bool(str(payload.username or "").strip() or str(payload.password or "").strip())
        context = (
            admin_panel_context_from_credentials(payload.username, payload.password)
            if login_with_user
            else admin_panel_context_from_token(payload.token)
        )
        if not context:
            record_admin_panel_login_failure(request)
            record_security_event(
                request,
                channel="api",
                event_type="admin_panel_login",
                decision="denied",
                reason="invalid_panel_credentials" if login_with_user else "invalid_panel_token",
            )
            raise HTTPException(status_code=401, detail="Login invalido.")
        clear_admin_panel_login_failures(request)
        set_admin_panel_session_cookie(response, request, context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_login",
            decision="allowed",
            reason="panel_user" if context.get("auth_type") == "user" else str(context.get("mode") or "admin"),
        )
        return {
            "ok": True,
            "mode": str(context.get("mode") or "admin"),
            "is_admin": bool(context.get("is_admin")),
            "username": str(context.get("username") or ""),
            "filiais": list(context.get("filiais", ())),
            "requires_password_change": bool(context.get("must_change_password")),
            "expires_in": session_ttl_seconds,
        }

    @router.post("/api/admin/panel/change-password")
    def api_admin_panel_change_password(
        request: Request,
        response: Response,
        payload: AdminPanelChangePasswordRequest,
    ) -> dict[str, Any]:
        context = admin_panel_context_from_session_cookie(request)
        if not context or str(context.get("auth_type") or "") != "user":
            raise HTTPException(status_code=401, detail="Sessao invalida.")
        try:
            updated_context = admin_panel_user_service.change_password(
                user_id=int(context.get("user_id") or 0),
                current_password=payload.current_password,
                new_password=payload.new_password,
            )
        except ValueError as exc:
            record_security_event(
                request,
                channel="api",
                event_type="admin_panel_change_password",
                decision="denied",
                reason="invalid_password_change",
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        set_admin_panel_session_cookie(response, request, updated_context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_change_password",
            decision="allowed",
            reason=str(updated_context.get("username") or updated_context.get("user_id") or ""),
        )
        return {"ok": True, "requires_password_change": False}

    @router.post("/api/admin/panel/logout")
    def api_admin_panel_logout(request: Request, response: Response) -> dict[str, Any]:
        context = admin_panel_context_from_session_cookie(request)
        response.delete_cookie(session_cookie_name, path="/", samesite="strict")
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_logout",
            decision="allowed" if context else "ignored",
            reason=str((context or {}).get("username") or (context or {}).get("mode") or "anonymous"),
        )
        return {"ok": True}

    @router.get("/admin", response_class=HTMLResponse)
    @router.get("/admin/operations", response_class=HTMLResponse)
    @router.get("/admin/imports", response_class=HTMLResponse)
    @router.get("/admin/reports", response_class=HTMLResponse)
    @router.get("/admin/payip", response_class=HTMLResponse)
    @router.get("/admin/promax", response_class=HTMLResponse)
    @router.get("/admin/power-bi", response_class=HTMLResponse)
    @router.get("/admin/tables", response_class=HTMLResponse)
    @router.get("/admin/critica", response_class=HTMLResponse)
    @router.get("/admin/recolhas", response_class=HTMLResponse)
    @router.get("/admin/giro-recolha", response_class=HTMLResponse)
    @router.get("/admin/usage", response_class=HTMLResponse)
    def admin_import_panel(request: Request) -> Response:
        context = admin_panel_context_from_session_cookie(request)
        if not context:
            return no_store_redirect("/admin/login")
        if bool(context.get("must_change_password")):
            return no_store_redirect("/admin/change-password")
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
        features = list(context.get("features", ()))
        can_operations = is_admin or is_finance or panel_context_can_access_feature(context, "operations")
        can_reports = is_admin or is_finance or panel_context_can_access_feature(context, "reports")
        can_critica = is_admin or is_finance or is_critica or panel_context_can_access_feature(context, "critica")
        return {
            "ok": True,
            "mode": mode,
            "is_admin": is_admin,
            "user_id": int(context.get("user_id") or 0),
            "username": str(context.get("username") or ""),
            "display_name": str(context.get("display_name") or ""),
            "features": features,
            "must_change_password": bool(context.get("must_change_password")),
            "filiais": list(context.get("filiais", ())),
            "can_manage_access": is_admin,
            "can_operations": can_operations,
            "can_reports": can_reports,
            "can_view_usage": is_admin or panel_context_can_access_feature(context, "usage"),
            "can_broadcast": can_operations,
            "can_import": can_reports,
            "can_import_critica": can_critica,
            "can_manage_recolhas": is_admin or is_finance or panel_context_can_access_feature(context, "recolhas"),
            "can_payip": is_admin or is_finance or panel_context_can_access_feature(context, "payip"),
            "can_view_giro": is_admin or is_finance or panel_context_can_access_feature(context, "giro"),
            "can_view_critica": can_critica,
            "can_manage_promax": is_admin or panel_context_can_access_feature(context, "promax"),
        }

    def require_panel_admin(
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
        if not bool(context.get("is_admin")):
            raise HTTPException(status_code=403, detail="Apenas administrador pode gerenciar usuarios do painel.")
        return context

    @router.get("/api/admin/panel/users")
    def api_admin_panel_users(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_panel_admin(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        users = admin_panel_user_service.list_users()
        record_security_event(request, channel="api", event_type="admin_panel_list_users", decision="allowed")
        return {"ok": True, "total": len(users), "users": users}

    @router.post("/api/admin/panel/users")
    def api_admin_panel_user_create(
        request: Request,
        payload: AdminPanelUserCreateRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_panel_admin(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            result = admin_panel_user_service.create_user(
                username=payload.username,
                display_name=payload.display_name,
                is_admin=payload.is_admin,
                features=payload.features,
                filiais=payload.filiais,
                is_active=payload.is_active,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_create_user",
            decision="allowed",
            reason=result["user"].get("username"),
        )
        return {"ok": True, **result}

    @router.patch("/api/admin/panel/users/{user_id}")
    def api_admin_panel_user_update(
        request: Request,
        user_id: int,
        payload: AdminPanelUserUpdateRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_admin(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        if int(context.get("user_id") or 0) == int(user_id) and (not payload.is_admin or not payload.is_active):
            raise HTTPException(status_code=400, detail="Nao remova o proprio acesso admin por esta tela.")
        try:
            user = admin_panel_user_service.update_user(
                user_id=user_id,
                display_name=payload.display_name,
                is_admin=payload.is_admin,
                features=payload.features,
                filiais=payload.filiais,
                is_active=payload.is_active,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_update_user",
            decision="allowed",
            reason=user.get("username"),
        )
        return {"ok": True, "user": user}

    @router.post("/api/admin/panel/users/{user_id}/reset-password")
    def api_admin_panel_user_reset_password(
        request: Request,
        user_id: int,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_admin(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        if int(context.get("user_id") or 0) == int(user_id):
            raise HTTPException(status_code=400, detail="Use a troca de senha para alterar sua propria senha.")
        try:
            result = admin_panel_user_service.reset_password(user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_reset_user_password",
            decision="allowed",
            reason=result["user"].get("username"),
        )
        return {"ok": True, **result}

    @router.delete("/api/admin/panel/users/{user_id}")
    def api_admin_panel_user_delete(
        request: Request,
        user_id: int,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_panel_admin(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        if int(context.get("user_id") or 0) == int(user_id):
            raise HTTPException(status_code=400, detail="Nao apague o proprio usuario admin por esta tela.")
        try:
            user = admin_panel_user_service.delete_user(user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_panel_delete_user",
            decision="allowed",
            reason=user.get("username"),
        )
        return {"ok": True, "user": user}

    return router
