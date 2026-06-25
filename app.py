from __future__ import annotations

from bot_api import app_factory as _app_factory

app = _app_factory.app
create_app = _app_factory.create_app

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> object:
    return getattr(_app_factory, name)
