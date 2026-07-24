from __future__ import annotations

import unittest

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from bot_api.services.admin_panel_session_service import AdminPanelSessionService
from bot_api.services.admin_panel_user_service import AdminPanelUserService


class FakePanelUserService:
    def authenticate(self, *, username: str, password: str) -> dict[str, object] | None:
        if username == "apr" and password == "Senha#123456":
            return {
                "auth_type": "user",
                "user_id": 42,
                "username": "apr",
                "display_name": "APR",
                "password_version": 1,
                "mode": "usuario",
                "is_admin": False,
                "filiais": ("3",),
                "features": ("payip", "critica"),
                "must_change_password": True,
            }
        return None

    def context_for_session(self, *, user_id: int, password_version: int) -> dict[str, object] | None:
        if user_id == 42 and password_version == 1:
            return {
                "auth_type": "user",
                "user_id": 42,
                "username": "apr",
                "display_name": "APR",
                "password_version": 1,
                "mode": "usuario",
                "is_admin": False,
                "filiais": ("3",),
                "features": ("payip", "critica"),
                "must_change_password": True,
            }
        return None


class AdminPanelSessionServiceTest(unittest.TestCase):
    def make_service(self) -> AdminPanelSessionService:
        return AdminPanelSessionService(
            admin_api_token="admin-token",
            session_secret="session-secret",
            verify_token="verify-token",
            api_auth_tokens=("api-token",),
            finance_panel_tokens=(("finance-token", ("3", "5")),),
            critica_panel_tokens=(("critica-token", ("7",)),),
            session_cookie_name="bot_admin_session",
            session_ttl_seconds=3600,
            login_window_seconds=300,
            login_max_failures=2,
        )

    def make_user_service(self) -> AdminPanelSessionService:
        return AdminPanelSessionService(
            admin_api_token="admin-token",
            session_secret="session-secret",
            verify_token="verify-token",
            api_auth_tokens=("api-token",),
            finance_panel_tokens=(("finance-token", ("3", "5")),),
            critica_panel_tokens=(("critica-token", ("7",)),),
            session_cookie_name="bot_admin_session",
            session_ttl_seconds=3600,
            login_window_seconds=300,
            login_max_failures=2,
            panel_user_service=FakePanelUserService(),
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

        armazem = {"mode": "user", "is_admin": False, "features": ("armazem",), "filiais": ("3",)}
        self.assertTrue(service.panel_context_can_access_feature(armazem, "armazem"))
        self.assertTrue(service.panel_context_can_access_feature(armazem, "estoque"))
        self.assertFalse(service.panel_context_can_access_feature(armazem, "payip"))

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
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", response.headers["set-cookie"].lower())

        response = client.get("/check")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mode": "financeiro", "is_admin": False, "filiais": ["3"]})

    def test_session_secret_does_not_fallback_to_api_or_webhook_tokens(self) -> None:
        service = AdminPanelSessionService(
            admin_api_token="",
            session_secret="",
            verify_token="verify-token",
            api_auth_tokens=("api-token",),
            finance_panel_tokens=(("finance-token", ("3",)),),
            critica_panel_tokens=(),
            session_cookie_name="bot_admin_session",
            session_ttl_seconds=3600,
            login_window_seconds=300,
            login_max_failures=2,
        )

        app = FastAPI()

        @app.get("/set")
        def set_cookie(request: Request, response: Response) -> dict[str, bool]:
            service.set_session_cookie(
                response,
                request,
                {"mode": "financeiro", "is_admin": False, "filiais": ("3",)},
            )
            return {"ok": True}

        response = TestClient(app).get("/set")
        self.assertEqual(response.status_code, 503)

    def test_login_rate_limit_key_ignores_untrusted_forwarded_for(self) -> None:
        service = self.make_service()
        app = FastAPI()

        @app.get("/key")
        def login_key(request: Request) -> dict[str, str]:
            return {"key": service._login_key(request)}

        response = TestClient(app).get("/key", headers={"X-Forwarded-For": "203.0.113.10"})

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["key"], "203.0.113.10")

    def test_user_session_rehydrates_from_user_service_and_features(self) -> None:
        service = self.make_user_service()
        context = service.context_from_credentials("apr", "Senha#123456")
        self.assertIsNotNone(context)
        self.assertTrue(service.panel_context_can_access_feature(context, "payip"))
        self.assertTrue(service.panel_context_can_access_feature(context, "critica_import"))
        self.assertFalse(service.panel_context_can_access_feature(context, "recolhas"))

        app = FastAPI()

        @app.get("/set")
        def set_cookie(request: Request, response: Response) -> dict[str, bool]:
            service.set_session_cookie(response, request, context or {})
            return {"ok": True}

        @app.get("/check")
        def check_cookie(request: Request) -> dict[str, object]:
            return service.context_from_session_cookie(request) or {}

        client = TestClient(app)
        self.assertEqual(client.get("/set").status_code, 200)
        response = client.get("/check")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "apr")
        self.assertEqual(response.json()["features"], ["payip", "critica"])
        self.assertTrue(response.json()["must_change_password"])

    def test_password_hash_policy_uses_random_salt_and_constant_verification(self) -> None:
        password = "SenhaForte#123"
        first_hash = AdminPanelUserService.hash_password(password)
        second_hash = AdminPanelUserService.hash_password(password)

        self.assertNotEqual(first_hash, second_hash)
        self.assertTrue(AdminPanelUserService.verify_password(password, first_hash))
        self.assertFalse(AdminPanelUserService.verify_password("senha-errada", first_hash))
        AdminPanelUserService.validate_new_password("12345678")
        AdminPanelUserService.validate_new_password("senhasim")
        with self.assertRaises(ValueError):
            AdminPanelUserService.validate_new_password("curta")

    def test_temporary_password_uses_eight_readable_characters(self) -> None:
        password = AdminPanelUserService.generate_temporary_password()

        self.assertEqual(len(password), 8)
        self.assertFalse(any(char in password for char in "O0Il1o"))
        AdminPanelUserService.validate_new_password(password)

    def test_panel_username_preserves_uppercase_and_rejects_invalid_values(self) -> None:
        service = AdminPanelUserService(
            database_url="postgresql://user:pass@localhost/db",
            schema="bot_access",
            connect_timeout_seconds=3,
        )

        self.assertEqual(service._normalize_username("APR.Patos"), "APR.Patos")
        self.assertEqual(service._normalize_username("  GV-SUME  "), "GV-SUME")
        self.assertEqual(service._normalize_username("APR.PATOS", for_login=True), "APR.PATOS")
        with self.assertRaises(ValueError):
            service._normalize_username("ab")


if __name__ == "__main__":
    unittest.main()
