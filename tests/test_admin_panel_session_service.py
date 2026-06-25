from __future__ import annotations

import unittest

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from bot_api.services.admin_panel_session_service import AdminPanelSessionService


class AdminPanelSessionServiceTest(unittest.TestCase):
    def make_service(self) -> AdminPanelSessionService:
        return AdminPanelSessionService(
            admin_api_token="admin-token",
            verify_token="verify-token",
            api_auth_tokens=("api-token",),
            finance_panel_tokens=(("finance-token", ("3", "5")),),
            critica_panel_tokens=(("critica-token", ("7",)),),
            session_cookie_name="bot_admin_session",
            session_ttl_seconds=3600,
            login_window_seconds=300,
            login_max_failures=2,
        )

    def test_context_from_token_resolves_admin_finance_and_critica(self) -> None:
        service = self.make_service()

        self.assertEqual(service.context_from_token("admin-token"), {"mode": "admin", "is_admin": True, "filiais": ()})
        self.assertEqual(
            service.context_from_token("finance-token"),
            {"mode": "financeiro", "is_admin": False, "filiais": ("3", "5")},
        )
        self.assertEqual(
            service.context_from_token("critica-token"),
            {"mode": "critica", "is_admin": False, "filiais": ("7",)},
        )
        self.assertIsNone(service.context_from_token("invalid"))

    def test_feature_rules_match_panel_modes(self) -> None:
        service = self.make_service()
        finance = {"mode": "financeiro", "is_admin": False, "filiais": ("3",)}
        critica = {"mode": "critica", "is_admin": False, "filiais": ("7",)}

        self.assertTrue(service.panel_context_can_access_feature(finance, "broadcast"))
        self.assertFalse(service.panel_context_can_access_feature(finance, "usage"))
        self.assertTrue(service.panel_context_can_access_feature(critica, "critica"))
        self.assertFalse(service.panel_context_can_access_feature(critica, "recolhas"))

    def test_signed_cookie_roundtrip_preserves_context(self) -> None:
        service = self.make_service()
        app = FastAPI()

        @app.get("/set")
        def set_cookie(request: Request, response: Response) -> dict[str, bool]:
            service.set_session_cookie(
                response,
                request,
                {"mode": "financeiro", "is_admin": False, "filiais": ("3",)},
            )
            return {"ok": True}

        @app.get("/check")
        def check_cookie(request: Request) -> dict[str, object]:
            return service.context_from_session_cookie(request) or {}

        client = TestClient(app)

        response = client.get("/set")
        self.assertEqual(response.status_code, 200)

        response = client.get("/check")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mode": "financeiro", "is_admin": False, "filiais": ["3"]})


if __name__ == "__main__":
    unittest.main()
