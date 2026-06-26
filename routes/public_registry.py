from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from bot_api.routes.health import create_health_router
from bot_api.routes.public_queries import create_public_queries_router
from bot_api.routes.webhooks import create_webhooks_router

RouteRegistrar = Callable[[FastAPI], None]


def build_public_route_registrars(deps: dict[str, Any]) -> tuple[RouteRegistrar, ...]:
    return (
        lambda app: _register_health_routes(app, deps=deps),
        lambda app: _register_public_query_routes(app, deps=deps),
        lambda app: _register_webhook_routes(app, deps=deps),
    )


def _register_health_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_health_router(
            build_detailed_health_payload=deps["build_detailed_health_payload"],
            require_admin_api_auth=deps["require_admin_api_auth"],
        )
    )


def _register_public_query_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_public_queries_router(
            access_control=deps["access_control"],
            dclientes_query_service=deps["dclientes_query_service"],
            inadimplencia_query_service=deps["inadimplencia_query_service"],
            comodatos_query_service=deps["comodatos_query_service"],
            require_api_auth=deps["require_api_auth"],
            require_admin_scope_for_number_routes=deps["require_admin_scope_for_number_routes"],
            decision_has_unrestricted_lookup_access=deps["decision_has_unrestricted_lookup_access"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_webhook_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_webhooks_router(
            settings=deps["settings"],
            meta_cloud_client=deps["meta_cloud_client"],
            require_webhook_token=deps["require_webhook_token"],
            require_meta_cloud_signature=deps["require_meta_cloud_signature"],
            queue_incoming_webhook=deps["queue_incoming_webhook"],
            record_security_event=deps["record_security_event"],
        )
    )
