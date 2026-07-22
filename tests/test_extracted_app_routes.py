from __future__ import annotations

import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_broadcast import create_admin_broadcast_router
from bot_api.routes.admin_panel import create_admin_panel_router
from bot_api.routes.admin_recolhas import create_admin_recolhas_router
from bot_api.routes.admin_usage import create_admin_usage_router
from bot_api.routes.public_queries import create_public_queries_router


class FakeDecision:
    allowed = True
    reason = "ok"
    normalized_number = "5583999990001"
    area = "cliente"
    roles = ("vendedor",)
    sectors = ("3-107",)
    gv_vdes: tuple[str, ...] = ()


class FakeAccessControl:
    def authorize(self, **kwargs: Any) -> FakeDecision:
        decision = FakeDecision()
        decision.area = kwargs.get("area", "cliente")
        return decision


class FakeAdminPanelUserService:
    def list_users(self) -> list[dict[str, Any]]:
        return [{"id": 1, "username": "admin", "features": ["operations"], "is_admin": True}]

    def create_user(self, **_kwargs: Any) -> dict[str, Any]:
        return {"user": {"id": 2, "username": "novo"}, "temporary_password": "TempSenha#1234"}

    def update_user(self, *, user_id: int, **_kwargs: Any) -> dict[str, Any]:
        return {"id": user_id, "username": "admin"}

    def reset_password(self, *, user_id: int) -> dict[str, Any]:
        return {"user": {"id": user_id, "username": "admin"}, "temporary_password": "TempSenha#5678"}


class ExtractedAppRoutesTest(unittest.TestCase):
    def _admin_panel_test_app(self, session_context: dict[str, Any] | None) -> FastAPI:
        app = FastAPI()
        app.include_router(
            create_admin_panel_router(
                admin_panel_context_from_session_cookie=lambda _request: session_context,
                load_admin_login_html=lambda: "<html>login</html>",
                load_admin_change_password_html=lambda: "<html>change</html>",
                load_admin_import_panel_html=lambda: "<html>panel</html>",
                check_admin_panel_login_rate_limit=lambda _request: None,
                admin_panel_context_from_token=lambda _token: {"mode": "admin", "is_admin": True, "filiais": []},
                admin_panel_context_from_credentials=lambda _username, _password: {"mode": "admin", "is_admin": True, "filiais": []},
                record_admin_panel_login_failure=lambda _request: None,
                clear_admin_panel_login_failures=lambda _request: None,
                set_admin_panel_session_cookie=lambda _response, _request, _context: None,
                require_admin_panel_auth=lambda **_kwargs: {"mode": "financeiro", "is_admin": False, "filiais": ["3"]},
                panel_context_mode=lambda context: str(context.get("mode") or "admin"),
                panel_context_can_access_feature=lambda _context, _feature: True,
                admin_panel_user_service=FakeAdminPanelUserService(),
                record_security_event=lambda _request, **_kwargs: None,
                session_cookie_name="bot_admin_session",
                session_ttl_seconds=3600,
            )
        )
        return app

    def test_public_access_check_delegates_auth_and_audit(self) -> None:
        auth_calls: list[dict[str, Any]] = []
        scope_calls: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        app = FastAPI()
        app.include_router(
            create_public_queries_router(
                access_control=FakeAccessControl(),
                dclientes_query_service=None,
                inadimplencia_query_service=None,
                comodatos_query_service=None,
                require_api_auth=lambda **kwargs: auth_calls.append(kwargs),
                require_admin_scope_for_number_routes=lambda **kwargs: scope_calls.append(kwargs),
                decision_has_unrestricted_lookup_access=lambda _decision: False,
                record_security_event=lambda _request, **kwargs: events.append(kwargs),
            )
        )

        response = TestClient(app).get("/api/access/check?number=5583999990001&area=cliente")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["allowed"])
        self.assertEqual(auth_calls[0]["request"].url.path, "/api/access/check")
        self.assertEqual(scope_calls[0]["request"].url.path, "/api/access/check")
        self.assertEqual(events[0]["event_type"], "access_check")

    def test_admin_panel_pages_share_panel_without_losing_legacy_routes(self) -> None:
        client = TestClient(self._admin_panel_test_app({"is_admin": True}))

        for path in (
            "/admin",
            "/admin/imports",
            "/admin/operations",
            "/admin/payip",
            "/admin/tables",
            "/admin/critica",
            "/admin/recolhas",
            "/admin/giro-recolha",
            "/admin/usage",
        ):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, "<html>panel</html>")

    def test_admin_panel_pages_redirect_to_login_without_session(self) -> None:
        client = TestClient(self._admin_panel_test_app(None), follow_redirects=False)

        for path in (
            "/admin/operations",
            "/admin/payip",
            "/admin/tables",
            "/admin/critica",
            "/admin/recolhas",
            "/admin/giro-recolha",
            "/admin/usage",
        ):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_panel_session_keeps_capability_flags(self) -> None:
        response = TestClient(self._admin_panel_test_app({"is_admin": True})).get("/api/admin/panel/session")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["can_broadcast"])
        self.assertTrue(payload["can_import"])
        self.assertTrue(payload["can_manage_recolhas"])
        self.assertTrue(payload["can_payip"])
        self.assertFalse(payload["can_manage_access"])

    def test_admin_recolhas_bulk_uses_feature_gate_and_update_service(self) -> None:
        features: list[str] = []
        updates: list[dict[str, Any]] = []

        def update_bulk(payload: Any, context: dict[str, Any] | None) -> dict[str, Any]:
            updates.append({"payload": payload, "context": context})
            return {"updated": 1, "errors": []}

        app = FastAPI()
        app.include_router(
            create_admin_recolhas_router(
                require_admin_panel_auth=lambda **_kwargs: {"mode": "financeiro", "is_admin": False},
                require_admin_panel_feature=lambda _context, feature: features.append(feature),
                list_admin_recolhas=lambda _context: {"total": 0, "items": []},
                update_admin_recolhas_bulk=update_bulk,
                import_admin_recolhas_csv=lambda _file, _context: {"imported": 0, "skipped": 0},
                export_admin_recolhas_csv=lambda _context, **_kwargs: (b"id\n", 0, "recolhas.csv"),
                update_admin_recolha=lambda _id, _payload, _context: {"updated": True},
                delete_admin_recolha=lambda _id, _context: {"deleted": True},
                record_security_event=lambda _request, **_kwargs: None,
            )
        )

        response = TestClient(app).patch(
            "/api/admin/recolhas/bulk",
            json={"ids": ["abc"], "status_caixa_noturno": "lancado"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(features, ["recolhas"])
        self.assertEqual(updates[0]["payload"].ids, ["abc"])
        self.assertEqual(response.json()["updated"], 1)

    def test_admin_usage_report_returns_csv_attachment(self) -> None:
        app = FastAPI()
        app.include_router(
            create_admin_usage_router(
                require_admin_panel_auth=lambda **_kwargs: {"mode": "admin", "is_admin": True},
                require_admin_panel_feature=lambda _context, _feature: None,
                list_admin_evolution_usage=lambda **kwargs: {"window_days": kwargs["days"]},
                build_evolution_usage_avg_report_csv=lambda payload: f"days\n{payload['window_days']}\n",
                build_evolution_function_usage_report_csv=lambda _payload, **_kwargs: "feature\n",
                record_security_event=lambda _request, **_kwargs: None,
            )
        )

        response = TestClient(app).get("/api/admin/usage/evolution/report?days=3")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "days\n3\n")
        self.assertIn("attachment", response.headers["content-disposition"])

    def test_admin_broadcast_preview_builds_payload_with_context(self) -> None:
        calls: list[dict[str, Any]] = []

        def build_payload(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {
                "filial": kwargs["filial"],
                "action": kwargs["action"],
                "day": kwargs["day"],
                "target_mode": kwargs["target_mode"],
                "target_audience": kwargs["target_audience"],
                "total": 1,
            }

        app = FastAPI()
        app.include_router(
            create_admin_broadcast_router(
                require_admin_panel_auth=lambda **_kwargs: {"mode": "admin", "is_admin": True},
                require_admin_panel_feature=lambda _context, _feature: None,
                list_admin_broadcast_options=lambda _context: {"filiais": ["3"]},
                snapshot_admin_broadcast_state=lambda _context: {"running": False},
                build_admin_broadcast_payload=build_payload,
                queue_admin_broadcast=lambda *_args: {"filial": "3", "action": "rota", "day": "hoje", "target_mode": "filial", "target_audience": "vendedor", "total": 1},
                record_security_event=lambda _request, **_kwargs: None,
            )
        )

        response = TestClient(app).post(
            "/api/admin/broadcast/preview",
            json={"filial": "3", "action": "rota", "selected_numbers": ["5583999990001"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertFalse(calls[0]["require_selection"])
        self.assertEqual(calls[0]["selected_numbers"], ["5583999990001"])


if __name__ == "__main__":
    unittest.main()
