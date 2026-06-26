from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from bot_api.routes.admin_registry import build_admin_route_registrars
from bot_api.routes.public_registry import build_public_route_registrars

RouteRegistrar = Callable[[FastAPI], None]


def build_route_registrars(deps: dict[str, Any]) -> tuple[RouteRegistrar, ...]:
    public_registrars = build_public_route_registrars(deps)
    admin_registrars = build_admin_route_registrars(deps)
    return (
        public_registrars[0],
        *admin_registrars[:4],
        public_registrars[1],
        *admin_registrars[4:],
        public_registrars[2],
    )
