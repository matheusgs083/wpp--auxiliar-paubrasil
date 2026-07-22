from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.routes.admin_payip import create_admin_payip_router


class AdminPayipRoutesTests(unittest.TestCase):
    def make_client(self, *, allow_feature: bool = True) -> TestClient:
        app = FastAPI()

        def require_feature(_context: dict[str, Any] | None, _feature: str) -> None:
            if not allow_feature:
                raise HTTPException(status_code=403, detail="negado")

        app.include_router(
            create_admin_payip_router(
                require_admin_panel_auth=lambda **_kwargs: {"is_admin": True},
                require_admin_panel_feature=require_feature,
                preview_payip_batch=lambda payload, context: {"total": 1, "items": [{"filial": "3", "nb": "16883"}]},
                queue_payip_batch=lambda payload, context: {"state": {"running": True}, "job": {"job_id": "job-1", "total": 1}},
                snapshot_payip_batch=lambda **_kwargs: {"state": {"running": False}, "job": {"job_id": "job-1", "results": []}},
                export_payip_batch_csv=lambda **_kwargs: (b"linha;status\n", "payip.csv"),
                payip_batch_pdf_bytes=lambda item_id, **_kwargs: (b"%PDF-route", f"{item_id}.pdf"),
                validate_payip_promax_import=lambda payload, context: {"items_count": 1, "items": [{"clientCode": "19167"}], "missing_client_codes": []},
                create_payip_promax_import_clients=lambda payload, context: {
                    "items_count": 1,
                    "items": [{"clientCode": "19167"}],
                    "missing_client_codes": [],
                    "client_creation": {"created": list(payload.missing_client_codes), "not_found": [], "failed": []},
                },
                run_payip_promax_import=lambda payload, context: {"items_count": 1, "items": [{"clientCode": "19167"}], "missing_client_codes": [], "imported": True},
                record_security_event=lambda *_args, **_kwargs: None,
            )
        )
        return TestClient(app)

    def test_preview_route_returns_batch_payload(self) -> None:
        client = self.make_client()
        response = client.post(
            "/api/admin/payip/batch/preview",
            json={"raw_text": "filial;nb;valor;vencimento\n3;16883;10;2026-12-31"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)

    def test_run_route_queues_job(self) -> None:
        client = self.make_client()
        response = client.post(
            "/api/admin/payip/batch/run",
            json={"raw_text": "filial;nb;valor;vencimento\n3;16883;10;2026-12-31"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["queued"])
        self.assertEqual(response.json()["job"]["job_id"], "job-1")

    def test_pdf_route_returns_pdf(self) -> None:
        client = self.make_client()
        response = client.get("/api/admin/payip/batch/pdf/item-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_promax_import_validate_route_returns_payload(self) -> None:
        client = self.make_client()
        response = client.post(
            "/api/admin/payip/import/validate",
            json={"filial": "3", "start_date": "2026-07-07", "end_date": "2026-07-07"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items_count"], 1)

    def test_promax_import_create_clients_route_returns_payload(self) -> None:
        client = self.make_client()
        response = client.post(
            "/api/admin/payip/import/create-clients",
            json={
                "filial": "3",
                "start_date": "2026-07-07",
                "end_date": "2026-07-07",
                "missing_client_codes": ["19167"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["client_creation"]["created"], ["19167"])

    def test_promax_import_run_route_returns_payload(self) -> None:
        client = self.make_client()
        response = client.post(
            "/api/admin/payip/import/run",
            json={"filial": "3", "start_date": "2026-07-07", "end_date": "2026-07-07", "mfa_code": "123456"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["imported"])


if __name__ == "__main__":
    unittest.main()
