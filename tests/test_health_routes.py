from __future__ import annotations

import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.health import create_health_router


class HealthRoutesTest(unittest.TestCase):
    def test_public_health_response(self) -> None:
        app = FastAPI()
        app.include_router(
            create_health_router(
                build_detailed_health_payload=lambda: {"ok": True, "detail": "admin"},
                require_admin_api_auth=lambda **_kwargs: None,
            )
        )

        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "service": "bot_api"})

    def test_admin_health_uses_auth_and_detailed_payload(self) -> None:
        calls: list[dict[str, Any]] = []

        def require_admin_api_auth(**kwargs: Any) -> None:
            calls.append(kwargs)

        app = FastAPI()
        app.include_router(
            create_health_router(
                build_detailed_health_payload=lambda: {"ok": True, "detail": "admin"},
                require_admin_api_auth=require_admin_api_auth,
            )
        )

        response = TestClient(app).get(
            "/api/admin/health",
            headers={"Authorization": "Bearer api-token", "x-api-token": "api-token", "x-admin-token": "admin-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "detail": "admin"})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["authorization"], "Bearer api-token")
        self.assertEqual(calls[0]["x_api_token"], "api-token")
        self.assertEqual(calls[0]["x_admin_token"], "admin-token")


if __name__ == "__main__":
    unittest.main()
