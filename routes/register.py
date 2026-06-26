from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from bot_api.routes.registry import build_route_registrars


def register_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    for register in build_route_registrars(deps):
        register(app)
