from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field


class AdminBroadcastRequest(BaseModel):
    filial: str
    action: str
    day: str = "hoje"
    target_mode: str = "filial"
    target_audience: str = "vendedor"
    target_number: str = ""
    selected_numbers: list[str] = Field(default_factory=list)


def create_admin_broadcast_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    list_admin_broadcast_options: Callable[[dict[str, Any] | None], dict[str, Any]],
    snapshot_admin_broadcast_state: Callable[[dict[str, Any] | None], dict[str, Any]],
    build_admin_broadcast_payload: Callable[..., dict[str, Any]],
    queue_admin_broadcast: Callable[..., dict[str, Any]],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def require_broadcast_context(
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
        require_admin_panel_feature(context, "broadcast")
        return context

    @router.get("/api/admin/broadcast/options")
    def api_admin_broadcast_options(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_broadcast_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        payload = list_admin_broadcast_options(context)
        record_security_event(request, channel="api", event_type="admin_broadcast_options", decision="allowed")
        return {"ok": True, **payload}

    @router.get("/api/admin/broadcast/status")
    def api_admin_broadcast_status(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_broadcast_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        record_security_event(request, channel="api", event_type="admin_broadcast_status", decision="allowed")
        return {"ok": True, **snapshot_admin_broadcast_state(context)}

    @router.post("/api/admin/broadcast/preview")
    def api_admin_broadcast_preview(
        request: Request,
        payload: AdminBroadcastRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_broadcast_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = build_admin_broadcast_payload(
            filial=payload.filial,
            action=payload.action,
            day=payload.day,
            target_mode=payload.target_mode,
            target_audience=payload.target_audience,
            target_number=payload.target_number,
            selected_numbers=payload.selected_numbers,
            require_selection=False,
            context=context,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_broadcast_preview",
            decision="allowed",
            reason=(
                f"filial={result['filial']};action={result['action']};"
                f"day={result['day']};target_mode={result['target_mode']};"
                f"target_audience={result['target_audience']};total={result['total']}"
            ),
        )
        return {"ok": True, **result}

    @router.post("/api/admin/broadcast/run", status_code=202)
    def api_admin_broadcast_run(
        request: Request,
        payload: AdminBroadcastRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_broadcast_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = queue_admin_broadcast(
            payload.filial,
            payload.action,
            payload.day,
            payload.target_mode,
            payload.target_audience,
            payload.target_number,
            payload.selected_numbers,
            context,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_broadcast_run",
            decision="allowed",
            reason=(
                f"filial={result['filial']};action={result['action']};"
                f"day={result['day']};target_mode={result['target_mode']};"
                f"target_audience={result['target_audience']};total={result['total']}"
            ),
        )
        return {"ok": True, "queued": True, **result}

    return router
