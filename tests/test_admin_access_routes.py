from __future__ import annotations

import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_access import create_admin_access_router


class FakeAccessControl:
    def __init__(self) -> None:
        self.users = [
            {
                "phone_number": "5583999990001",
                "name": "Teste",
                "roles": ["vendedor"],
                "sectors": ["3-107"],
                "gv_vdes": [],
            }
        ]

    def list_users(self) -> list[dict[str, Any]]:
        return list(self.users)

    def upsert_user(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("phone_number") == "erro":
            raise ValueError("Telefone invalido.")
        return dict(kwargs)

    def delete_user(self, *, phone_number: str) -> dict[str, Any]:
        return {"phone_number": phone_number, "deleted": True}

    def list_roles(self) -> list[dict[str, Any]]:
        return [{"name": "admin", "permissions": ["*"]}]

    def list_permissions(self) -> list[dict[str, Any]]:
        return [{"name": "cliente"}]

    def upsert_role(self, **kwargs: Any) -> dict[str, Any]:
        return dict(kwargs)

    def seed_defaults(self) -> dict[str, Any]:
        return {"ok": True}


class AdminAccessRoutesTest(unittest.TestCase):
    def make_client(self) -> tuple[TestClient, list[dict[str, Any]], list[dict[str, Any]]]:
        auth_calls: list[dict[str, Any]] = []
        security_events: list[dict[str, Any]] = []

        def require_admin_api_auth(**kwargs: Any) -> None:
            auth_calls.append(kwargs)

        def record_security_event(_request: Any, **kwargs: Any) -> None:
            security_events.append(kwargs)

        app = FastAPI()
        app.include_router(
            create_admin_access_router(
                access_control=FakeAccessControl(),  # type: ignore[arg-type]
                access_call=lambda func, *args, **kwargs: func(*args, **kwargs),
                require_admin_api_auth=require_admin_api_auth,
                record_security_event=record_security_event,
            )
        )
        return TestClient(app), auth_calls, security_events

    def test_list_users_requires_auth_and_records_event(self) -> None:
        client, auth_calls, security_events = self.make_client()

        response = client.get(
            "/api/admin/access/users",
            headers={"Authorization": "Bearer api", "x-api-token": "api", "x-admin-token": "admin"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(len(auth_calls), 1)
        self.assertEqual(auth_calls[0]["authorization"], "Bearer api")
        self.assertEqual(security_events[0]["event_type"], "admin_list_users")

    def test_bulk_upsert_reports_partial_errors(self) -> None:
        client, _auth_calls, security_events = self.make_client()

        response = client.post(
            "/api/admin/access/users/bulk",
            json={
                "users": [
                    {"phone_number": "5583999990002", "roles": ["vendedor"], "sectors": ["3-108"]},
                    {"phone_number": "erro", "roles": ["vendedor"], "sectors": ["3-109"]},
                ],
                "continue_on_error": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["total_saved"], 1)
        self.assertEqual(payload["total_failed"], 1)
        self.assertEqual(security_events[0]["event_type"], "admin_bulk_upsert_users")
        self.assertEqual(security_events[0]["decision"], "partial")


if __name__ == "__main__":
    unittest.main()
