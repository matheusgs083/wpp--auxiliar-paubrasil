from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, Request


def create_health_router(
    *,
    build_detailed_health_payload: Callable[[], dict[str, Any]],
    require_admin_api_auth: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "bot_api",
        }

    @router.get("/api/admin/health")
    def api_admin_health(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_admin_api_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        return build_detailed_health_payload()

    return router
