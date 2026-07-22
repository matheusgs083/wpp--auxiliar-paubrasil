from __future__ import annotations

import unittest
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_imports import create_admin_imports_router


class AdminImportsRoutesTest(unittest.TestCase):
    def make_client(self) -> tuple[TestClient, list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []

        def record_security_event(_request: Any, **kwargs: Any) -> None:
            events.append(kwargs)

        app = FastAPI()
        app.include_router(
            create_admin_imports_router(
                access_call=lambda func, *args, **kwargs: func(*args, **kwargs),
                require_admin_panel_auth=lambda **_kwargs: {"mode": "admin", "is_admin": True},
                require_admin_panel_feature=lambda _context, _feature: None,
                require_admin_panel_import_dataset=lambda _context, dataset: f"normalized_{dataset}",
                list_admin_import_status=lambda: {"items": [{"dataset": "dclientes"}]},
                filter_admin_import_status_for_context=lambda payload, _context: {**payload, "filtered": True},
                list_admin_import_history=lambda **_kwargs: {"jobs": []},
                filter_admin_import_history_for_context=lambda payload, _context: payload,
                run_admin_import_validation=lambda dataset: {"dataset": dataset, "valid": True},
                queue_admin_import=lambda dataset, **kwargs: {"dataset": dataset, "reference_date": kwargs.get("reference_date")},
                store_admin_import_uploads=lambda dataset, *_args: {"dataset": dataset, "total_files": 1},
                record_security_event=record_security_event,
            )
        )
        return TestClient(app), events

    def test_status_returns_filtered_payload(self) -> None:
        client, events = self.make_client()

        response = client.get("/api/admin/imports/status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["filtered"])
        self.assertEqual(events[0]["event_type"], "admin_import_status")

    def test_run_normalizes_dataset_and_queues(self) -> None:
        client, events = self.make_client()

        response = client.post(
            "/api/admin/imports/run",
            json={"dataset": "dclientes", "reference_date": "2026-06-12"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["dataset"], "normalized_dclientes")
        self.assertTrue(response.json()["queued"])
        self.assertEqual(events[0]["event_type"], "admin_import_run")


if __name__ == "__main__":
    unittest.main()
