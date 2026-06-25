from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from bot_api.routes.admin_critica import create_admin_critica_router
from bot_api.routes.admin_giro import create_admin_giro_router


class AdminDashboardRoutesTest(unittest.TestCase):
    def test_giro_dashboard_calls_builder_and_records_event(self) -> None:
        events: list[dict[str, Any]] = []
        builder_calls: list[dict[str, Any]] = []

        def build_dashboard(_context: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            builder_calls.append(kwargs)
            return {"total": 2, "records": []}

        app = FastAPI()
        app.include_router(
            create_admin_giro_router(
                require_admin_panel_auth=lambda **_kwargs: {"mode": "admin", "is_admin": True},
                require_admin_panel_feature=lambda _context, feature: None,
                build_admin_giro_recolha_dashboard=build_dashboard,
                build_admin_giro_recolha_filter_options=lambda _context, **_kwargs: {"options": {}},
                build_admin_giro_recolha_routes=lambda _context, **_kwargs: {"total": 0, "routes": []},
                record_security_event=lambda _request, **kwargs: events.append(kwargs),
            )
        )

        response = TestClient(app).get("/api/admin/giro/recolha-dashboard?limit=50&zero_only=true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(builder_calls[0]["limit"], 50)
        self.assertTrue(builder_calls[0]["zero_only"])
        self.assertEqual(events[0]["event_type"], "admin_giro_recolha_dashboard")

    def test_critica_pdf_uses_parsed_date_and_returns_response(self) -> None:
        pdf_calls: list[dict[str, Any]] = []

        def build_pdf(_context: dict[str, Any], **kwargs: Any) -> Response:
            pdf_calls.append(kwargs)
            return Response(content=b"PDF", media_type="application/pdf")

        app = FastAPI()
        app.include_router(
            create_admin_critica_router(
                require_admin_panel_auth=lambda **_kwargs: {"mode": "admin", "is_admin": True},
                require_admin_panel_feature=lambda _context, feature: None,
                parse_admin_critica_date=lambda value: date.fromisoformat(value or "2026-06-12"),
                build_admin_critica_dashboard=lambda _context, **_kwargs: {"total": 0, "records": []},
                build_admin_critica_sector_pdf_response=build_pdf,
                record_security_event=lambda _request, **_kwargs: None,
            )
        )

        response = TestClient(app).get("/api/admin/critica/pdf?operation=3&sector=3-107&date=2026-06-12")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"PDF")
        self.assertEqual(pdf_calls[0]["target_date"], date(2026, 6, 12))
        self.assertEqual(pdf_calls[0]["operation"], "3")
        self.assertEqual(pdf_calls[0]["sector"], "3-107")


if __name__ == "__main__":
    unittest.main()
