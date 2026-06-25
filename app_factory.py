from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from bot_api.config import get_settings
from bot_api.services.app_runtime import configure_app_runtime
from bot_api.services.container import build_app_services

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent
settings = get_settings()
services = build_app_services(settings, project_root=PROJECT_ROOT, logger=logger)

app = FastAPI(
    title="Customer Lookup Bot API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_runtime_exports = configure_app_runtime(
    app=app,
    settings=settings,
    services=services,
    project_root=PROJECT_ROOT,
    logger=logger,
)
globals().update(_runtime_exports)


def create_app() -> FastAPI:
    return app
