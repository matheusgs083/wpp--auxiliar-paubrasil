from __future__ import annotations

import secrets
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.routes.admin_promax import create_admin_promax_router


class FakePromaxService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _call(self, operation: str, *args: Any, return_value: Any, **kwargs: Any) -> Any:
        self.calls.append((operation, args, kwargs))
        return return_value

    def enqueue_job(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("enqueue_job", return_value={"id": "job-1", **kwargs}, **kwargs)

    def enqueue_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call(
            "enqueue_jobs",
            return_value=[
                {
                    "id": f"job-{index}",
                    "job_type": item["job_type"],
                    "payload": item["payload"],
                }
                for index, item in enumerate(kwargs["items"], start=1)
            ],
            **kwargs,
        )

    def list_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
        status = (kwargs.get("statuses") or ["pending"])[0]
        return self._call(
            "list_jobs",
            return_value=[
                {
                    "id": "job-1",
                    "status": status,
                    "job_type": "reports",
                    "leased_by": "worker-1",
                }
            ],
            **kwargs,
        )

    def get_job(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "get_job",
            job_id,
            return_value={
                "id": job_id,
                "job_type": "reports",
                "leased_by": "worker-1",
                "lease_token": "lease-token",
                "logs": [{"id": 1, "message": "started"}] if kwargs.get("include_logs") else [],
            },
            **kwargs,
        )

    def list_job_logs(self, job_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call(
            "list_job_logs",
            job_id,
            return_value=[{"id": 1, "message": "started"}],
            **kwargs,
        )

    def cancel_job(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "cancel_job",
            job_id,
            return_value={"id": job_id, "status": "cancel_requested"},
            **kwargs,
        )

    def request_cancel_job(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "request_cancel_job",
            job_id,
            return_value={"id": job_id, "status": "cancel_requested"},
            **kwargs,
        )

    def pause_queue(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("pause_queue", return_value={"paused": True}, **kwargs)

    def resume_queue(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("resume_queue", return_value={"paused": False}, **kwargs)

    def clear_pending_jobs(self, **kwargs: Any) -> int:
        return self._call("clear_pending_jobs", return_value=2, **kwargs)

    def get_queue_state(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("get_queue_state", return_value={"paused": False}, **kwargs)

    def list_worker_heartbeats(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call(
            "list_worker_heartbeats",
            return_value=[{"worker_id": "worker-1", "online": True}],
            **kwargs,
        )

    def create_schedule(self, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "create_schedule",
            return_value={"id": "schedule-1", **kwargs},
            **kwargs,
        )

    def create_schedule_chain(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call(
            "create_schedule_chain",
            return_value=[
                {"id": f"schedule-{index}", **dict(item)}
                for index, item in enumerate(kwargs["items"], start=1)
            ],
            **kwargs,
        )

    def list_schedules(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call(
            "list_schedules",
            return_value=[{"id": "schedule-1"}],
            **kwargs,
        )

    def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._call("get_schedule", schedule_id, return_value={"id": schedule_id})

    def update_schedule(self, schedule_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "update_schedule",
            schedule_id,
            return_value={"id": schedule_id, **kwargs},
            **kwargs,
        )

    def delete_schedule(self, schedule_id: str) -> bool:
        return self._call(
            "delete_schedule",
            schedule_id,
            return_value=True,
        )

    def claim_next_job(self, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "claim_next_job",
            return_value={"id": "job-1", "lease_token": "lease-token"},
            **kwargs,
        )

    def heartbeat_worker(self, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "heartbeat_worker",
            return_value={"worker_id": kwargs["worker_id"], "online": True},
            **kwargs,
        )

    def register_worker_heartbeat(self, **kwargs: Any) -> None:
        self._call("register_worker_heartbeat", return_value=None, **kwargs)

    def heartbeat_job(self, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "heartbeat_job",
            return_value={"job_id": kwargs["job_id"], "lease_seconds": kwargs["lease_seconds"]},
            **kwargs,
        )

    def append_job_log(self, **kwargs: Any) -> dict[str, Any]:
        return self._call("append_job_log", return_value={"log_id": 7}, **kwargs)

    def finish_job(self, **kwargs: Any) -> dict[str, Any]:
        return self._call(
            "finish_job",
            return_value={"job_id": kwargs["job_id"], "status": kwargs["status"]},
            **kwargs,
        )


class AdminPromaxRoutesTests(unittest.TestCase):
    context = {"mode": "admin", "is_admin": True, "filiais": ()}
    worker_headers = {"x-promax-worker-token": "worker-secret"}

    @staticmethod
    def job_payload() -> dict[str, Any]:
        return {
            "category": "reports",
            "routines": ["030237", "150501"],
            "units": ["030117", "030118"],
            "start_date": "2026-07-01",
            "end_date": "2026-07-18",
            "send_dates": False,
            "publish": False,
        }

    @classmethod
    def schedule_payload(cls) -> dict[str, Any]:
        return {
            **cls.job_payload(),
            "name": "Daily reports",
            "schedule_type": "daily",
            "time_of_day": "06:00:00",
            "timezone": "America/Fortaleza",
            "enabled": True,
        }

    @classmethod
    def job_batch_payload(cls) -> dict[str, Any]:
        job = cls.job_payload()
        return {
            "groups": [
                {"category": job["category"], "routines": job["routines"]},
            ],
            "units": job["units"],
            "start_date": job["start_date"],
            "end_date": job["end_date"],
            "send_dates": job["send_dates"],
            "publish": job["publish"],
        }

    def make_client(
        self,
        *,
        worker_token: str | None = "worker-secret",
        auth_status: int | None = None,
        allow_feature: bool = True,
        is_admin: bool = True,
        catalog_value: Any | None = None,
    ) -> tuple[
        TestClient,
        FakePromaxService,
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        service = FakePromaxService()
        events: list[dict[str, Any]] = []
        auth_calls: list[dict[str, Any]] = []
        feature_calls: list[tuple[dict[str, Any] | None, str]] = []

        def require_auth(**kwargs: Any) -> dict[str, Any]:
            auth_calls.append(kwargs)
            if auth_status is not None:
                raise HTTPException(status_code=auth_status, detail="auth denied")
            return {**self.context, "is_admin": is_admin}

        def require_feature(context: dict[str, Any] | None, feature: str) -> None:
            feature_calls.append((context, feature))
            if not allow_feature:
                raise HTTPException(status_code=403, detail="feature denied")

        app = FastAPI()
        app.state.promax_feature_calls = feature_calls
        catalog_source = (
            catalog_value
            if catalog_value is not None
            else {
                "reports": {
                    "routines": ["030237", "150501"],
                    "units": ["030117", "030118"],
                }
            }
        )
        app.include_router(
            create_admin_promax_router(
                service=service,
                catalog=lambda: catalog_source,
                worker_token=worker_token,
                require_admin_panel_auth=require_auth,
                require_admin_panel_feature=require_feature,
                record_security_event=lambda _request, **kwargs: events.append(kwargs),
            )
        )
        return TestClient(app), service, events, auth_calls

    def test_admin_routes_use_documented_service_contract_and_admin_auth(self) -> None:
        client, service, events, auth_calls = self.make_client()
        headers = {
            "authorization": "Bearer api-token",
            "x-api-token": "api-token",
            "x-admin-token": "admin-token",
        }

        requests = [
            ("get", "/api/admin/promax/catalog", None, 200),
            ("post", "/api/admin/promax/jobs", self.job_payload(), 202),
            (
                "get",
                "/api/admin/promax/jobs?status=pending&category=reports&created_from=2026-07-18&created_to=2026-07-19&limit=25",
                None,
                200,
            ),
            ("get", "/api/admin/promax/jobs/job-1", None, 200),
            ("get", "/api/admin/promax/jobs/job-1/logs?limit=50&after_id=0", None, 200),
            ("post", "/api/admin/promax/jobs/job-1/cancel", None, 200),
            ("post", "/api/admin/promax/jobs/job-1/stop", None, 200),
            ("post", "/api/admin/promax/queue/pause", None, 200),
            ("post", "/api/admin/promax/queue/resume", None, 200),
            ("delete", "/api/admin/promax/queue/pending", None, 200),
            ("get", "/api/admin/promax/worker/status", None, 200),
            ("post", "/api/admin/promax/schedules", self.schedule_payload(), 201),
            ("get", "/api/admin/promax/schedules?limit=20", None, 200),
            ("get", "/api/admin/promax/schedules/schedule-1", None, 200),
            ("patch", "/api/admin/promax/schedules/schedule-1", {"enabled": False}, 200),
            ("delete", "/api/admin/promax/schedules/schedule-1", None, 200),
        ]

        for method, path, payload, expected_status in requests:
            with self.subTest(method=method, path=path):
                response = client.request(method, path, headers=headers, json=payload)
                self.assertEqual(response.status_code, expected_status, response.text)
                self.assertTrue(response.json()["ok"])

        self.assertEqual(
            [name for name, _args, _kwargs in service.calls],
            [
                "enqueue_job",
                "list_jobs",
                "get_job",
                "list_job_logs",
                "cancel_job",
                "cancel_job",
                "pause_queue",
                "resume_queue",
                "clear_pending_jobs",
                "get_queue_state",
                "list_jobs",
                "list_worker_heartbeats",
                "create_schedule",
                "list_schedules",
                "get_schedule",
                "update_schedule",
                "delete_schedule",
            ],
        )
        self.assertEqual(len(auth_calls), len(requests))
        self.assertEqual(
            [feature for _context, feature in client.app.state.promax_feature_calls],
            ["promax"] * len(requests),
        )
        self.assertEqual(auth_calls[0]["authorization"], "Bearer api-token")
        self.assertEqual(auth_calls[0]["x_api_token"], "api-token")
        self.assertEqual(auth_calls[0]["x_admin_token"], "admin-token")
        self.assertEqual(len([event for event in events if event["decision"] == "allowed"]), len(requests))

        create_payload = service.calls[0][2]["payload"]
        self.assertEqual(create_payload["start_date"], "2026-07-01")
        self.assertIs(create_payload["send_dates"], False)
        self.assertIs(create_payload["publish"], False)
        list_kwargs = service.calls[1][2]
        self.assertEqual(list_kwargs["limit"], 500)
        self.assertEqual(list_kwargs["statuses"], ["pending"])
        self.assertEqual(
            list_kwargs["created_from"],
            datetime(2026, 7, 18, 3, 0, tzinfo=UTC),
        )
        self.assertEqual(
            list_kwargs["created_before"],
            datetime(2026, 7, 20, 3, 0, tzinfo=UTC),
        )

    def test_admin_authentication_failure_stops_before_service(self) -> None:
        client, service, _events, auth_calls = self.make_client(auth_status=401)

        response = client.get("/api/admin/promax/worker/status")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(auth_calls), 1)
        self.assertEqual(service.calls, [])

    def test_job_batch_enqueues_all_groups_in_selected_order(self) -> None:
        catalog = {
            "reports": {
                "routines": ["030237", "150501"],
                "units": ["030117", "030118"],
            },
            "financeiro": {
                "routines": ["120601"],
                "units": ["030117", "030118"],
            },
        }
        client, service, events, _auth_calls = self.make_client(catalog_value=catalog)
        payload = {
            **self.job_batch_payload(),
            "groups": [
                {"category": "reports", "routines": ["150501"]},
                {"category": "financeiro", "routines": ["120601"]},
            ],
        }

        response = client.post("/api/admin/promax/jobs/batch", json=payload)

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(len(response.json()["jobs"]), 2)
        self.assertEqual(service.calls[0][0], "enqueue_jobs")
        items = service.calls[0][2]["items"]
        self.assertEqual([item["job_type"] for item in items], ["reports", "financeiro"])
        self.assertEqual(items[0]["payload"]["routines"], ["150501"])
        self.assertEqual(items[1]["payload"]["routines"], ["120601"])
        self.assertEqual(items[1]["payload"]["units"], ["030117", "030118"])
        self.assertIs(items[1]["payload"]["send_dates"], False)
        self.assertEqual(events[-1]["event_type"], "admin_promax_job_batch_create")

    def test_job_batch_rejects_duplicate_or_unknown_groups(self) -> None:
        duplicate = self.job_batch_payload()
        duplicate["groups"] = [duplicate["groups"][0], duplicate["groups"][0]]
        client, service, _events, _auth_calls = self.make_client()

        response = client.post("/api/admin/promax/jobs/batch", json=duplicate)

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(service.calls, [])

        unknown = self.job_batch_payload()
        unknown["groups"] = [{"category": "desconhecido", "routines": ["030237"]}]
        response = client.post("/api/admin/promax/jobs/batch", json=unknown)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(service.calls, [])

    def test_admin_rbac_failure_stops_before_service(self) -> None:
        client, service, _events, auth_calls = self.make_client(allow_feature=False)

        response = client.post("/api/admin/promax/jobs", json=self.job_payload())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(auth_calls), 1)
        self.assertEqual(service.calls, [])
        self.assertEqual(client.app.state.promax_feature_calls, [(self.context, "promax")])

    def test_job_payload_and_query_limits_are_validated(self) -> None:
        invalid_payloads = [
            {**self.job_payload(), "category": "Bad category"},
            {**self.job_payload(), "routines": []},
            {**self.job_payload(), "routines": ["030237", "030237"]},
            {**self.job_payload(), "start_date": "2026-07-19", "end_date": "2026-07-18"},
            {**self.job_payload(), "start_date": "2025-01-01", "end_date": "2026-07-18"},
            {**self.job_payload(), "send_dates": "true"},
            {**self.job_payload(), "publish": "true"},
            {**self.job_payload(), "routines": [f"r{index}" for index in range(51)]},
            {**self.job_payload(), "units": [f"u{index}" for index in range(101)]},
            {**self.job_payload(), "unexpected": True},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                client, service, _events, _auth_calls = self.make_client()
                response = client.post("/api/admin/promax/jobs", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(service.calls, [])

        client, service, _events, _auth_calls = self.make_client()
        response = client.get("/api/admin/promax/jobs?limit=201")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.calls, [])

        response = client.get(
            "/api/admin/promax/jobs?created_from=2026-07-19&created_to=2026-07-18"
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.calls, [])

    def test_finance_context_is_denied_even_if_generic_feature_check_allows(self) -> None:
        client, service, events, auth_calls = self.make_client(
            allow_feature=True,
            is_admin=False,
        )

        response = client.get("/api/admin/promax/worker/status")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(auth_calls), 1)
        self.assertEqual(service.calls, [])
        self.assertEqual(events[-1]["event_type"], "admin_promax_rbac")
        self.assertEqual(events[-1]["reason"], "admin_required")

    def test_job_selection_must_exist_in_injected_catalog(self) -> None:
        invalid_payloads = [
            {**self.job_payload(), "category": "finance"},
            {**self.job_payload(), "routines": ["030237", "999999"]},
            {**self.job_payload(), "units": ["030117", "999999"]},
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                client, service, _events, _auth_calls = self.make_client()
                response = client.post("/api/admin/promax/jobs", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(service.calls, [])

        client, service, _events, _auth_calls = self.make_client(catalog_value=["invalid"])
        response = client.post("/api/admin/promax/jobs", json=self.job_payload())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(service.calls, [])

    def test_category_without_units_accepts_empty_units(self) -> None:
        client, service, _events, _auth_calls = self.make_client(
            catalog_value={
                "categories": {
                    "fluxo_caixa": {
                        "routines": [{"id": "140506"}],
                        "units": [],
                    }
                }
            }
        )

        response = client.post(
            "/api/admin/promax/jobs",
            json={
                "category": "fluxo_caixa",
                "routines": ["140506"],
                "units": [],
                "start_date": "2026-07-01",
                "end_date": "2026-07-18",
                "publish": True,
            },
        )

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(service.calls[0][0], "enqueue_job")
        self.assertEqual(service.calls[0][2]["payload"]["units"], [])

    def test_reprocess_publications_enqueues_dedicated_maintenance_job(self) -> None:
        client, service, events, _auth_calls = self.make_client()

        response = client.post("/api/admin/promax/publications/reprocess")

        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(
            [name for name, _args, _kwargs in service.calls],
            ["list_jobs", "enqueue_job"],
        )
        list_kwargs = service.calls[0][2]
        self.assertEqual(
            list_kwargs["statuses"],
            ["pending", "running", "cancel_requested"],
        )
        enqueue_kwargs = service.calls[1][2]
        self.assertEqual(enqueue_kwargs["job_type"], "reprocess_publication")
        self.assertEqual(
            enqueue_kwargs["payload"],
            {"operation": "reprocess_publication"},
        )
        self.assertEqual(enqueue_kwargs["priority"], 50)
        self.assertEqual(events[-1]["event_type"], "admin_promax_publication_reprocess")

    def test_schedule_payload_requires_valid_timing_and_nonempty_patch(self) -> None:
        client, service, _events, _auth_calls = self.make_client()

        invalid_create = client.post(
            "/api/admin/promax/schedules",
            json={**self.schedule_payload(), "schedule_type": "weekly"},
        )
        empty_update = client.patch("/api/admin/promax/schedules/schedule-1", json={})

        self.assertEqual(invalid_create.status_code, 422)
        self.assertEqual(empty_update.status_code, 422)
        self.assertEqual(service.calls, [])

        invalid_selection_update = client.patch(
            "/api/admin/promax/schedules/schedule-1",
            json={"routines": ["030237"]},
        )
        self.assertEqual(invalid_selection_update.status_code, 422)
        self.assertEqual(service.calls, [])

    def test_schedule_chain_validates_and_creates_groups_in_order(self) -> None:
        catalog = {
            "reports": {
                "routines": ["030237"],
                "units": ["0640001", "2210003"],
            },
            "obz": {
                "routines": ["0512"],
                "units": ["0640001", "2210003"],
            },
        }
        client, service, events, _auth_calls = self.make_client(catalog_value=catalog)
        trigger_id = "8cc06d03-1b8f-4e8f-b1d0-2c49d77d37a2"

        response = client.post(
            "/api/admin/promax/schedule-chains",
            json={
                "name": "Fechamento diario",
                "groups": [
                    {"category": "reports", "routines": ["030237"]},
                    {"category": "obz", "routines": ["0512"]},
                ],
                "units": ["0640001", "2210003"],
                "start_date": "2026-07-18",
                "end_date": "2026-07-18",
                "send_dates": True,
                "publish": True,
                "schedule_type": "daily",
                "time_of_day": "06:00:00",
                "timezone": "America/Fortaleza",
                "trigger_after_schedule_id": trigger_id,
                "enabled": True,
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(len(response.json()["schedules"]), 2)
        self.assertEqual([call[0] for call in service.calls], ["create_schedule_chain"])
        kwargs = service.calls[0][2]
        self.assertEqual([item["job_type"] for item in kwargs["items"]], ["reports", "obz"])
        self.assertEqual(kwargs["items"][0]["payload"]["units"], ["0640001", "2210003"])
        self.assertIs(kwargs["items"][0]["payload"]["send_dates"], True)
        self.assertEqual(kwargs["trigger_after_schedule_id"], trigger_id)
        self.assertEqual(events[-1]["event_type"], "admin_promax_schedule_chain_create")

    def test_schedule_chain_rejects_unknown_group_before_writing(self) -> None:
        client, service, _events, _auth_calls = self.make_client()

        response = client.post(
            "/api/admin/promax/schedule-chains",
            json={
                "name": "Agenda invalida",
                "groups": [{"category": "obz", "routines": ["0512"]}],
                "units": [],
                "start_date": "2026-07-18",
                "end_date": "2026-07-18",
                "publish": True,
                "schedule_type": "daily",
                "time_of_day": "06:00:00",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(service.calls, [])

    def test_internal_routes_use_worker_contract_and_compare_digest(self) -> None:
        client, service, events, _auth_calls = self.make_client()

        with patch(
            "bot_api.routes.admin_promax.compare_digest",
            wraps=secrets.compare_digest,
        ) as secure_compare:
            responses = [
                client.post(
                    "/api/internal/promax/next-job/claim",
                    headers=self.worker_headers,
                    json={"worker_id": "worker-1", "pid": 4321, "lease_seconds": 180},
                ),
                client.post(
                    "/api/internal/promax/heartbeat",
                    headers=self.worker_headers,
                    json={"worker_id": "worker-1", "pid": 4321, "version": "1.0", "details": {"queue": 0}},
                ),
                client.post(
                    "/api/internal/promax/jobs/job-1/heartbeat",
                    headers=self.worker_headers,
                    json={
                        "worker_id": "worker-1",
                        "pid": 4321,
                        "lease_token": "lease-token",
                        "lease_seconds": 240,
                    },
                ),
                client.post(
                    "/api/internal/promax/jobs/job-1/log",
                    headers=self.worker_headers,
                    json={
                        "worker_id": "worker-1",
                        "lease_token": "lease-token",
                        "level": "WARNING",
                        "message": "retrying",
                        "data": {"attempt": 2},
                    },
                ),
                client.post(
                    "/api/internal/promax/jobs/job-1/finish",
                    headers=self.worker_headers,
                    json={
                        "worker_id": "worker-1",
                        "pid": 4321,
                        "lease_token": "lease-token",
                        "status": "failed",
                        "error": "report failed",
                    },
                ),
                client.get(
                    "/api/internal/promax/control?worker_id=worker-1&job_id=job-1",
                    headers=self.worker_headers,
                ),
            ]

        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["ok"])

        self.assertEqual(secure_compare.call_count, len(responses))
        secure_compare.assert_any_call("worker-secret", "worker-secret")
        self.assertEqual(
            [name for name, _args, _kwargs in service.calls],
            [
                "claim_next_job",
                "register_worker_heartbeat",
                "heartbeat_job",
                "append_job_log",
                "finish_job",
                "get_queue_state",
                "list_jobs",
            ],
        )
        self.assertEqual(service.calls[2][2]["worker_metadata"]["pid"], 4321)
        self.assertEqual(service.calls[2][2]["lease_seconds"], 240)
        self.assertEqual(service.calls[3][2]["level"], "warning")
        self.assertTrue(responses[-1].json()["cancel_requested"])
        worker_auth_events = [event for event in events if event["event_type"] == "promax_worker_auth"]
        self.assertEqual(len(worker_auth_events), len(responses))
        self.assertTrue(all(event["decision"] == "allowed" for event in worker_auth_events))

    def test_worker_client_compatibility_routes_map_to_service_contract(self) -> None:
        client, service, _events, _auth_calls = self.make_client()
        requests = [
            (
                "/api/internal/promax/worker/claim",
                {"worker_id": "worker-1"},
            ),
            (
                "/api/internal/promax/worker/heartbeat",
                {
                    "worker_id": "worker-1",
                    "hostname": "host-1",
                    "status": "idle",
                    "job_id": None,
                },
            ),
            (
                "/api/internal/promax/worker/heartbeat",
                {
                    "worker_id": "worker-1",
                    "hostname": "host-1",
                    "status": "running",
                    "job_id": "job-1",
                },
            ),
            (
                "/api/internal/promax/worker/log",
                {
                    "worker_id": "worker-1",
                    "job_id": "job-1",
                    "stream": "stderr",
                    "message": "failed line",
                },
            ),
            (
                "/api/internal/promax/worker/control",
                {"worker_id": "worker-1", "job_id": "job-1"},
            ),
            (
                "/api/internal/promax/worker/finish",
                {
                    "worker_id": "worker-1",
                    "job_id": "job-1",
                    "status": "failed",
                    "exit_code": 1,
                    "error": "driver failed",
                },
            ),
        ]

        for path, payload in requests:
            with self.subTest(path=path, payload=payload):
                response = client.post(path, headers=self.worker_headers, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["ok"])

        self.assertEqual(
            [name for name, _args, _kwargs in service.calls],
            [
                "claim_next_job",
                "register_worker_heartbeat",
                "get_job",
                "heartbeat_job",
                "get_job",
                "append_job_log",
                "get_queue_state",
                "list_jobs",
                "get_job",
                "finish_job",
            ],
        )
        self.assertNotIn("pid", service.calls[0][2])
        self.assertEqual(service.calls[5][2]["level"], "error")
        self.assertEqual(service.calls[9][2]["result"], {"exit_code": 1})

    def test_internal_token_not_configured_returns_503(self) -> None:
        for configured_token in (None, "", "   "):
            with self.subTest(configured_token=configured_token):
                client, service, events, _auth_calls = self.make_client(
                    worker_token=configured_token
                )
                response = client.get(
                    "/api/internal/promax/control?worker_id=worker-1",
                    headers=self.worker_headers,
                )

                self.assertEqual(response.status_code, 503)
                self.assertEqual(service.calls, [])
                self.assertEqual(events[-1]["reason"], "worker_token_not_configured")

    def test_internal_missing_or_invalid_token_returns_401(self) -> None:
        for headers, reason in (
            ({}, "worker_token_missing"),
            ({"x-promax-worker-token": "wrong"}, "worker_token_invalid"),
        ):
            with self.subTest(reason=reason):
                client, service, events, _auth_calls = self.make_client()
                response = client.get(
                    "/api/internal/promax/control?worker_id=worker-1",
                    headers=headers,
                )

                self.assertEqual(response.status_code, 401)
                self.assertEqual(service.calls, [])
                self.assertEqual(events[-1]["decision"], "denied")
                self.assertEqual(events[-1]["reason"], reason)

    def test_internal_payload_limits_are_validated_before_service(self) -> None:
        cases = [
            (
                "/api/internal/promax/next-job/claim",
                {"worker_id": "worker-1", "pid": 4321, "lease_seconds": 14},
            ),
            (
                "/api/internal/promax/jobs/job-1/heartbeat",
                {"worker_id": "worker-1", "pid": 0, "lease_seconds": 120},
            ),
            (
                "/api/internal/promax/jobs/job-1/log",
                {"worker_id": "worker-1", "level": "info", "message": "x" * 8001},
            ),
            (
                "/api/internal/promax/jobs/job-1/finish",
                {"worker_id": "worker-1", "pid": 4321, "status": "failed"},
            ),
        ]

        for path, payload in cases:
            with self.subTest(path=path):
                client, service, _events, _auth_calls = self.make_client()
                response = client.post(path, headers=self.worker_headers, json=payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
