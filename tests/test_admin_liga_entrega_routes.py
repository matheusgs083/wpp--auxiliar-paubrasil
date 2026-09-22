
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_liga_entrega import create_admin_liga_entrega_router
from bot_api.services.liga_entrega_expurgo_service import LigaEntregaExpurgoService
from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore


class AdminLigaEntregaRoutesTest(unittest.TestCase):
    def make_client(self) -> tuple[TestClient, list[dict[str, Any]]]:
        self.tmp = TemporaryDirectory()
        events: list[dict[str, Any]] = []

        def record_security_event(_request: Any, **kwargs: Any) -> None:
            events.append(kwargs)

        app = FastAPI()
        app.include_router(
            create_admin_liga_entrega_router(
                require_admin_panel_auth=lambda **_kwargs: {"mode": "admin", "is_admin": True},
                require_admin_panel_feature=lambda _context, _feature: None,
                liga_entrega_expurgo_service=LigaEntregaExpurgoService(Path(self.tmp.name) / "expurgos.json"),
                liga_entrega_report_store=LigaEntregaReportStore(Path(self.tmp.name) / "reports"),
                record_security_event=record_security_event,
                record_admin_panel_action=lambda **_kwargs: None,
            )
        )
        return TestClient(app), events

    def tearDown(self) -> None:
        tmp = getattr(self, "tmp", None)
        if tmp is not None:
            tmp.cleanup()


    def test_list_relatorios_reports_latest_stored_batches(self) -> None:
        client, events = self.make_client()
        store = LigaEntregaReportStore(Path(self.tmp.name) / "reports")
        store.store_batch(
            routine="030805_LIGA",
            files={"PATOS_21_09.csv": b"rota;valor\n1;10\n"},
            reference_date="2026-09-22",
        )

        response = client.get("/api/admin/liga-entrega/relatorios")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["summary"]["loaded"], 1)
        item = next(item for item in payload["items"] if item["routine"] == "030805_LIGA")
        self.assertTrue(item["loaded"])
        self.assertEqual(item["manifest"]["file_count"], 1)
        missing = next(item for item in payload["items"] if item["routine"] == "031120_BOT")
        self.assertFalse(missing["loaded"])
        self.assertEqual(events[-1]["event_type"], "admin_liga_relatorios_list")

    def test_upsert_list_and_delete_expurgo(self) -> None:
        client, events = self.make_client()

        response = client.post(
            "/api/admin/liga-entrega/expurgos",
            json={
                "tipo": "km",
                "competencia": "2026-09",
                "filial": "PATOS",
                "data": "2026-09-22",
                "mapa": "12345",
                "motivo": "km digitado errado",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        item_id = response.json()["item"]["id"]

        listed = client.get("/api/admin/liga-entrega/expurgos", params={"competencia": "2026-09"})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)

        deleted = client.delete(f"/api/admin/liga-entrega/expurgos/{item_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(deleted.json()["item"]["active"])
        self.assertEqual([event["event_type"] for event in events], ["admin_liga_expurgo_upsert", "admin_liga_expurgos_list", "admin_liga_expurgo_delete"])


if __name__ == "__main__":
    unittest.main()
