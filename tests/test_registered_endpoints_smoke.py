from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from bot_api.routes.register import register_routes


@dataclass
class EndpointCase:
    method: str
    path: str
    expected_status: int = 200
    kwargs: dict[str, Any] | None = None


class FakeDecision:
    allowed = True
    reason = "ok"
    normalized_number = "5583999990001"
    area = "cliente"
    roles = ("admin",)
    sectors: tuple[str, ...] = ()
    gv_vdes: tuple[str, ...] = ()


class FakeRecord:
    def to_dict(self) -> dict[str, Any]:
        return {"filial": "3", "cod_pdv": "123", "fantasia": "Cliente Teste"}


class FakeAccessControl:
    def authorize(self, *, area: str = "cliente", **_kwargs: Any) -> FakeDecision:
        decision = FakeDecision()
        decision.area = area
        return decision

    def list_users(self) -> list[dict[str, Any]]:
        return [{"phone_number": "5583999990001", "name": "Admin"}]

    def upsert_user(self, **kwargs: Any) -> dict[str, Any]:
        return {"phone_number": kwargs.get("phone_number", "5583999990001")}

    def delete_user(self, *, phone_number: str) -> dict[str, Any]:
        return {"phone_number": phone_number}

    def list_roles(self) -> list[dict[str, Any]]:
        return [{"name": "admin"}]

    def list_permissions(self) -> list[dict[str, Any]]:
        return [{"name": "access.manage"}]

    def upsert_role(self, **kwargs: Any) -> dict[str, Any]:
        return {"name": kwargs.get("role_name", "admin")}

    def seed_defaults(self) -> dict[str, Any]:
        return {"ok": True}


class FakeQueryService:
    def search_by_registration(self, **_kwargs: Any) -> list[FakeRecord]:
        return [FakeRecord()]

    def search_by_fantasia(self, **_kwargs: Any) -> list[FakeRecord]:
        return [FakeRecord()]

    def search_by_name(self, **_kwargs: Any) -> list[FakeRecord]:
        return [FakeRecord()]

    def search_by_document(self, **_kwargs: Any) -> list[FakeRecord]:
        return [FakeRecord()]


class FakePromaxJobsService:
    job = {
        "id": "job-1",
        "job_type": "fluxo_caixa",
        "payload": {"category": "fluxo_caixa"},
        "status": "running",
        "leased_by": "worker-1",
        "lease_token": "lease-1",
    }
    schedule = {
        "id": "schedule-1",
        "name": "Fluxo diario",
        "enabled": True,
    }

    def enqueue_job(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.job)

    def enqueue_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                **self.job,
                "id": f"job-{index}",
                "job_type": str(item.get("job_type") or ""),
                "payload": dict(item.get("payload") or {}),
            }
            for index, item in enumerate(kwargs.get("items") or [], start=1)
        ]

    def list_jobs(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def get_job(self, _job_id: str) -> dict[str, Any]:
        return dict(self.job)

    def list_job_logs(self, _job_id: str, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def cancel_job(self, _job_id: str, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.job)

    def pause_queue(self, **_kwargs: Any) -> dict[str, Any]:
        return {"paused": True}

    def resume_queue(self, **_kwargs: Any) -> dict[str, Any]:
        return {"paused": False}

    def clear_pending_jobs(self, **_kwargs: Any) -> dict[str, Any]:
        return {"cleared": 0}

    def get_queue_state(self) -> dict[str, Any]:
        return {"paused": False}

    def list_worker_heartbeats(self) -> list[dict[str, Any]]:
        return []

    def create_schedule(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.schedule)

    def create_schedule_chain(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [dict(self.schedule)]

    def list_schedules(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [dict(self.schedule)]

    def get_schedule(self, _schedule_id: str) -> dict[str, Any]:
        return dict(self.schedule)

    def update_schedule(self, _schedule_id: str, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.schedule)

    def delete_schedule(self, _schedule_id: str) -> dict[str, Any]:
        return {"deleted": True}

    def claim_next_job(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.job)

    def register_worker_heartbeat(self, **_kwargs: Any) -> None:
        return None

    def heartbeat_job(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.job)

    def append_job_log(self, **_kwargs: Any) -> dict[str, Any]:
        return {"id": 1}

    def finish_job(self, **_kwargs: Any) -> dict[str, Any]:
        return dict(self.job)


class RegisteredEndpointsSmokeTest(unittest.TestCase):
    def make_client(self) -> TestClient:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        register_routes(app, deps=self.make_deps())
        return TestClient(app, follow_redirects=False)

    def make_deps(self) -> dict[str, Any]:
        context = {"mode": "admin", "is_admin": True, "filiais": ()}

        def build_broadcast_payload(**kwargs: Any) -> dict[str, Any]:
            return {
                "filial": kwargs["filial"],
                "action": kwargs["action"],
                "day": kwargs["day"],
                "target_mode": kwargs["target_mode"],
                "target_audience": kwargs["target_audience"],
                "total": 1,
            }

        return {
            "settings": SimpleNamespace(
                meta_cloud_enabled=False,
                verify_token="verify",
                promax_worker_token="worker-token",
            ),
            "meta_cloud_client": SimpleNamespace(config=SimpleNamespace(verify_token="verify")),
            "access_control": FakeAccessControl(),
            "dclientes_query_service": FakeQueryService(),
            "inadimplencia_query_service": FakeQueryService(),
            "comodatos_query_service": FakeQueryService(),
            "build_detailed_health_payload": lambda: {"ok": True, "detailed": True},
            "access_call": lambda func, *args, **kwargs: func(*args, **kwargs),
            "require_admin_api_auth": lambda **_kwargs: None,
            "record_security_event": lambda _request, **_kwargs: None,
            "require_admin_panel_auth": lambda **_kwargs: dict(context),
            "require_admin_panel_feature": lambda _context, _feature: None,
            "require_admin_panel_import_dataset": lambda _context, dataset: str(dataset),
            "require_api_auth": lambda **_kwargs: None,
            "require_admin_scope_for_number_routes": lambda **_kwargs: None,
            "decision_has_unrestricted_lookup_access": lambda _decision: True,
            "admin_panel_context_from_session_cookie": lambda _request: None,
            "admin_panel_context_from_token": lambda token: dict(context) if token == "valid-token" else None,
            "check_admin_panel_login_rate_limit": lambda _request: None,
            "record_admin_panel_login_failure": lambda _request: None,
            "clear_admin_panel_login_failures": lambda _request: None,
            "set_admin_panel_session_cookie": lambda _response, _request, _context: None,
            "panel_context_mode": lambda panel_context: str((panel_context or {}).get("mode") or "admin"),
            "admin_panel_session_cookie": "bot_admin_session",
            "admin_panel_session_ttl_seconds": 3600,
            "load_admin_login_html": lambda: "<html>login</html>",
            "load_admin_import_panel_html": lambda: "<html>imports</html>",
            "list_admin_import_status": lambda: {"datasets": {}},
            "filter_admin_import_status_for_context": lambda payload, _context: payload,
            "list_admin_import_history": lambda **_kwargs: {"items": [], "total": 0},
            "filter_admin_import_history_for_context": lambda payload, _context: payload,
            "run_admin_import_validation": lambda dataset: {"dataset": dataset, "valid": True},
            "queue_admin_import": lambda dataset, **_kwargs: {"dataset": dataset, "job_id": "job-1"},
            "store_admin_import_uploads": lambda dataset, _files, _context: {"dataset": dataset, "stored": 1},
            "build_admin_giro_recolha_dashboard": lambda _context, **_kwargs: {"total": 0, "items": []},
            "build_admin_giro_recolha_filter_options": lambda _context, **_kwargs: {"options": {}},
            "build_admin_giro_recolha_routes": lambda _context, **_kwargs: {"total": 0, "routes": []},
            "parse_admin_critica_date": lambda _value: None,
            "build_admin_critica_dashboard": lambda _context, **_kwargs: {"total": 0, "items": []},
            "build_admin_critica_sector_pdf_response": lambda _context, **_kwargs: Response(
                content=b"%PDF-1.4\n",
                media_type="application/pdf",
            ),
            "list_admin_recolhas": lambda _context: {"total": 0, "items": []},
            "update_admin_recolhas_bulk": lambda _payload, _context: {"updated": 1, "errors": []},
            "import_admin_recolhas_csv": lambda _file, _context: {"imported": 1, "skipped": 0},
            "export_admin_recolhas_csv": lambda _context, **_kwargs: (b"id\n", 0, "recolhas.csv"),
            "update_admin_recolha": lambda recolha_id, _payload, _context: {"id": recolha_id, "updated": True},
            "delete_admin_recolha": lambda recolha_id, _context: {"id": recolha_id, "deleted": True},
            "preview_payip_batch": lambda _payload, _context: {"total": 1, "items": []},
            "queue_payip_batch": lambda _payload, _context: {"job": {"job_id": "payip-1"}},
            "snapshot_payip_batch": lambda **_kwargs: {"running": False, "job": {}},
            "export_payip_batch_csv": lambda **_kwargs: (b"id\n", "payip.csv"),
            "payip_batch_pdf_bytes": lambda item_id, **_kwargs: (b"%PDF-1.4\n", f"{item_id}.pdf"),
            "validate_payip_promax_import": lambda _payload, _context: {
                "items_count": 1,
                "missing_client_codes": [],
            },
            "run_payip_promax_import": lambda _payload, _context: {
                "items_count": 1,
                "client_creation": {"created": []},
            },
            "promax_jobs_service": FakePromaxJobsService(),
            "promax_catalog": {
                "categories": {
                    "fluxo_caixa": {
                        "routines": ["140506", "120606"],
                        "units": [],
                    }
                }
            },
            "list_admin_evolution_usage": lambda **kwargs: {
                "window_days": kwargs.get("days", 7),
                "function_date_from": "2026-06-01",
                "function_date_to": "2026-06-25",
            },
            "build_evolution_usage_avg_report_csv": lambda payload: f"days\n{payload['window_days']}\n",
            "build_evolution_function_usage_report_csv": lambda _payload, **_kwargs: "feature,total\n",
            "list_admin_broadcast_options": lambda _context: {"filiais": ["3"], "actions": []},
            "snapshot_admin_broadcast_state": lambda _context: {"running": False},
            "build_admin_broadcast_payload": build_broadcast_payload,
            "queue_admin_broadcast": lambda filial, action, day, target_mode, target_audience, *_args: {
                "filial": filial,
                "action": action,
                "day": day,
                "target_mode": target_mode,
                "target_audience": target_audience,
                "total": 1,
            },
            "require_webhook_token": lambda **_kwargs: None,
            "require_meta_cloud_signature": lambda **_kwargs: None,
            "queue_incoming_webhook": lambda **_kwargs: {"received": True, "handled": True, "queued": True},
        }

    def endpoint_cases(self) -> list[EndpointCase]:
        user_payload = {"phone_number": "5583999990001", "name": "Admin", "roles": ["admin"]}
        role_payload = {"name": "admin", "permissions": ["access.manage"]}
        import_payload = {"dataset": "dclientes"}
        recolha_payload = {"status_caixa_noturno": "lancado"}
        payip_payload = {"raw_text": "5583999990001;100,00"}
        payip_import_payload = {
            "filial": "3",
            "start_date": "2026-07-18",
            "end_date": "2026-07-18",
        }
        promax_job_payload = {
            "category": "fluxo_caixa",
            "routines": ["140506", "120606"],
            "units": [],
            "start_date": "2026-07-18",
            "end_date": "2026-07-18",
            "send_dates": False,
            "publish": True,
        }
        promax_schedule_payload = {
            **promax_job_payload,
            "name": "Fluxo diario",
            "schedule_type": "daily",
            "time_of_day": "06:00:00",
            "timezone": "America/Fortaleza",
            "enabled": True,
        }
        promax_job_batch_payload = {
            "groups": [
                {
                    "category": promax_job_payload["category"],
                    "routines": promax_job_payload["routines"],
                }
            ],
            "units": promax_job_payload["units"],
            "start_date": promax_job_payload["start_date"],
            "end_date": promax_job_payload["end_date"],
            "send_dates": promax_job_payload["send_dates"],
            "publish": promax_job_payload["publish"],
        }
        promax_schedule_chain_payload = {
            "name": "Fluxo encadeado",
            "groups": [
                {
                    "category": promax_job_payload["category"],
                    "routines": promax_job_payload["routines"],
                }
            ],
            "units": promax_job_payload["units"],
            "start_date": promax_job_payload["start_date"],
            "end_date": promax_job_payload["end_date"],
            "send_dates": promax_job_payload["send_dates"],
            "publish": promax_job_payload["publish"],
            "schedule_type": "daily",
            "time_of_day": "06:00:00",
            "timezone": "America/Fortaleza",
            "enabled": True,
        }
        worker_headers = {"x-promax-worker-token": "worker-token"}
        broadcast_payload = {"filial": "3", "action": "rota_dia"}
        csv_file = {"file": ("recolhas.csv", b"id\n1\n", "text/csv")}
        upload_files = {"files": ("dclientes.csv", b"col\n1\n", "text/csv")}
        return [
            EndpointCase("GET", "/health"),
            EndpointCase("GET", "/api/admin/health"),
            EndpointCase("GET", "/api/admin/access/users"),
            EndpointCase("POST", "/api/admin/access/users", kwargs={"json": user_payload}),
            EndpointCase("POST", "/api/admin/access/users/bulk", kwargs={"json": {"users": [user_payload]}}),
            EndpointCase("DELETE", "/api/admin/access/users/5583999990001"),
            EndpointCase("GET", "/api/admin/access/roles"),
            EndpointCase("GET", "/api/admin/access/permissions"),
            EndpointCase("POST", "/api/admin/access/roles", kwargs={"json": role_payload}),
            EndpointCase("POST", "/api/admin/access/seed"),
            EndpointCase("GET", "/api/admin/imports/status"),
            EndpointCase("GET", "/api/admin/imports/history"),
            EndpointCase("POST", "/api/admin/imports/validate", kwargs={"json": import_payload}),
            EndpointCase("POST", "/api/admin/imports/run", expected_status=202, kwargs={"json": import_payload}),
            EndpointCase("POST", "/api/admin/imports/upload", kwargs={"data": {"dataset": "dclientes"}, "files": upload_files}),
            EndpointCase("GET", "/api/admin/giro/recolha-dashboard"),
            EndpointCase("GET", "/api/admin/giro/recolha-filter-options"),
            EndpointCase("GET", "/api/admin/giro/recolha-routes"),
            EndpointCase("GET", "/api/admin/critica/dashboard"),
            EndpointCase("GET", "/api/admin/critica/pdf?operation=3&sector=3-107"),
            EndpointCase("GET", "/api/client-search?q=cliente"),
            EndpointCase("GET", "/api/dclientes/search?number=5583999990001&filial=3&cod_pdv=123"),
            EndpointCase("GET", "/api/inadimplencia/search?number=5583999990001&filial=3&cod_pdv=123"),
            EndpointCase("GET", "/api/comodatos/search?number=5583999990001&filial=3&cod_pdv=123"),
            EndpointCase("GET", "/api/access/check?number=5583999990001&area=cliente"),
            EndpointCase("GET", "/admin/login"),
            EndpointCase("POST", "/api/admin/panel/login", kwargs={"json": {"token": "valid-token"}}),
            EndpointCase("POST", "/api/admin/panel/logout"),
            EndpointCase("GET", "/admin/imports", expected_status=303),
            EndpointCase("GET", "/admin", expected_status=303),
            EndpointCase("GET", "/admin/operations", expected_status=303),
            EndpointCase("GET", "/admin/reports", expected_status=303),
            EndpointCase("GET", "/admin/power-bi", expected_status=303),
            EndpointCase("GET", "/admin/tables", expected_status=303),
            EndpointCase("GET", "/admin/critica", expected_status=303),
            EndpointCase("GET", "/admin/recolhas", expected_status=303),
            EndpointCase("GET", "/admin/giro-recolha", expected_status=303),
            EndpointCase("GET", "/admin/usage", expected_status=303),
            EndpointCase("GET", "/admin/promax", expected_status=303),
            EndpointCase("GET", "/api/admin/panel/session"),
            EndpointCase("GET", "/api/admin/recolhas"),
            EndpointCase("PATCH", "/api/admin/recolhas/bulk", kwargs={"json": {"ids": ["rec-1"], **recolha_payload}}),
            EndpointCase("POST", "/api/admin/recolhas/import", kwargs={"files": csv_file}),
            EndpointCase("GET", "/api/admin/recolhas/export"),
            EndpointCase("PATCH", "/api/admin/recolhas/rec-1", kwargs={"json": recolha_payload}),
            EndpointCase("DELETE", "/api/admin/recolhas/rec-1"),
            EndpointCase("GET", "/api/admin/payip/batch/status"),
            EndpointCase("POST", "/api/admin/payip/batch/preview", kwargs={"json": payip_payload}),
            EndpointCase("POST", "/api/admin/payip/batch/run", expected_status=202, kwargs={"json": payip_payload}),
            EndpointCase("GET", "/api/admin/payip/batch/result"),
            EndpointCase("GET", "/api/admin/payip/batch/pdf/item-1"),
            EndpointCase("GET", "/api/admin/payip/batch/export.csv"),
            EndpointCase("POST", "/api/admin/payip/import/validate", kwargs={"json": payip_import_payload}),
            EndpointCase("POST", "/api/admin/payip/import/run", kwargs={"json": payip_import_payload}),
            EndpointCase("GET", "/api/admin/promax/catalog"),
            EndpointCase(
                "POST",
                "/api/admin/promax/jobs",
                expected_status=202,
                kwargs={"json": promax_job_payload},
            ),
            EndpointCase(
                "POST",
                "/api/admin/promax/jobs/batch",
                expected_status=202,
                kwargs={"json": promax_job_batch_payload},
            ),
            EndpointCase("GET", "/api/admin/promax/jobs"),
            EndpointCase("POST", "/api/admin/promax/publications/reprocess", expected_status=202),
            EndpointCase("GET", "/api/admin/promax/jobs/job-1"),
            EndpointCase("GET", "/api/admin/promax/jobs/job-1/logs"),
            EndpointCase("POST", "/api/admin/promax/jobs/job-1/cancel"),
            EndpointCase("POST", "/api/admin/promax/jobs/job-1/stop"),
            EndpointCase("POST", "/api/admin/promax/queue/pause"),
            EndpointCase("POST", "/api/admin/promax/queue/resume"),
            EndpointCase("DELETE", "/api/admin/promax/queue/pending"),
            EndpointCase("GET", "/api/admin/promax/worker/status"),
            EndpointCase(
                "POST",
                "/api/admin/promax/schedules",
                expected_status=201,
                kwargs={"json": promax_schedule_payload},
            ),
            EndpointCase(
                "POST",
                "/api/admin/promax/schedule-chains",
                expected_status=201,
                kwargs={"json": promax_schedule_chain_payload},
            ),
            EndpointCase("GET", "/api/admin/promax/schedules"),
            EndpointCase("GET", "/api/admin/promax/schedules/schedule-1"),
            EndpointCase(
                "PATCH",
                "/api/admin/promax/schedules/schedule-1",
                kwargs={"json": {"name": "Fluxo diario atualizado"}},
            ),
            EndpointCase("DELETE", "/api/admin/promax/schedules/schedule-1"),
            EndpointCase(
                "POST",
                "/api/internal/promax/next-job/claim",
                kwargs={
                    "headers": worker_headers,
                    "json": {"worker_id": "worker-1", "pid": 100, "lease_seconds": 120},
                },
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/heartbeat",
                kwargs={
                    "headers": worker_headers,
                    "json": {"worker_id": "worker-1", "pid": 100},
                },
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/jobs/job-1/heartbeat",
                kwargs={
                    "headers": worker_headers,
                    "json": {
                        "worker_id": "worker-1",
                        "pid": 100,
                        "lease_token": "lease-1",
                    },
                },
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/jobs/job-1/log",
                kwargs={
                    "headers": worker_headers,
                    "json": {
                        "worker_id": "worker-1",
                        "lease_token": "lease-1",
                        "message": "linha",
                    },
                },
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/jobs/job-1/finish",
                kwargs={
                    "headers": worker_headers,
                    "json": {
                        "worker_id": "worker-1",
                        "pid": 100,
                        "lease_token": "lease-1",
                        "status": "success",
                    },
                },
            ),
            EndpointCase(
                "GET",
                "/api/internal/promax/control?worker_id=worker-1",
                kwargs={"headers": worker_headers},
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/worker/claim",
                kwargs={"headers": worker_headers, "json": {"worker_id": "worker-1"}},
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/worker/heartbeat",
                kwargs={
                    "headers": worker_headers,
                    "json": {
                        "worker_id": "worker-1",
                        "hostname": "host-1",
                        "status": "running",
                        "job_id": "job-1",
                    },
                },
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/worker/log",
                kwargs={
                    "headers": worker_headers,
                    "json": {
                        "worker_id": "worker-1",
                        "job_id": "job-1",
                        "stream": "stdout",
                        "message": "linha",
                    },
                },
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/worker/control",
                kwargs={
                    "headers": worker_headers,
                    "json": {"worker_id": "worker-1", "job_id": "job-1"},
                },
            ),
            EndpointCase(
                "POST",
                "/api/internal/promax/worker/finish",
                kwargs={
                    "headers": worker_headers,
                    "json": {
                        "worker_id": "worker-1",
                        "job_id": "job-1",
                        "status": "succeeded",
                        "exit_code": 0,
                    },
                },
            ),
            EndpointCase("GET", "/api/admin/usage/evolution"),
            EndpointCase("GET", "/api/admin/usage/evolution/report"),
            EndpointCase("GET", "/api/admin/usage/evolution/functions/report"),
            EndpointCase("GET", "/api/admin/broadcast/options"),
            EndpointCase("GET", "/api/admin/broadcast/status"),
            EndpointCase("POST", "/api/admin/broadcast/preview", kwargs={"json": broadcast_payload}),
            EndpointCase("POST", "/api/admin/broadcast/run", expected_status=202, kwargs={"json": broadcast_payload}),
            EndpointCase("POST", "/webhook/evolution", kwargs={"json": {}}),
            EndpointCase("GET", "/webhook/meta?hub.mode=subscribe&hub.verify_token=verify&hub.challenge=abc"),
            EndpointCase("POST", "/webhook/meta", kwargs={"json": {}}),
        ]

    def test_every_registered_endpoint_has_a_smoke_case(self) -> None:
        client = self.make_client()
        route_keys = {
            (method, route.path)
            for route in client.app.routes
            for method in getattr(route, "methods", set())
            if method not in {"HEAD", "OPTIONS"}
        }
        case_keys = {(case.method, self.route_path_for_case(case.path)) for case in self.endpoint_cases()}

        self.assertEqual(route_keys, case_keys)

    @staticmethod
    def route_path_for_case(path: str) -> str:
        route_path = path.split("?", 1)[0]
        return {
            "/api/admin/access/users/5583999990001": "/api/admin/access/users/{phone_number}",
            "/api/admin/recolhas/rec-1": "/api/admin/recolhas/{recolha_id}",
            "/api/admin/payip/batch/pdf/item-1": "/api/admin/payip/batch/pdf/{item_id}",
            "/api/admin/promax/jobs/job-1": "/api/admin/promax/jobs/{job_id}",
            "/api/admin/promax/jobs/job-1/logs": "/api/admin/promax/jobs/{job_id}/logs",
            "/api/admin/promax/jobs/job-1/cancel": "/api/admin/promax/jobs/{job_id}/cancel",
            "/api/admin/promax/jobs/job-1/stop": "/api/admin/promax/jobs/{job_id}/stop",
            "/api/admin/promax/schedules/schedule-1": "/api/admin/promax/schedules/{schedule_id}",
            "/api/internal/promax/jobs/job-1/heartbeat": "/api/internal/promax/jobs/{job_id}/heartbeat",
            "/api/internal/promax/jobs/job-1/log": "/api/internal/promax/jobs/{job_id}/log",
            "/api/internal/promax/jobs/job-1/finish": "/api/internal/promax/jobs/{job_id}/finish",
        }.get(route_path, route_path)

    def test_all_registered_endpoints_smoke(self) -> None:
        client = self.make_client()
        for case in self.endpoint_cases():
            with self.subTest(method=case.method, path=case.path):
                response = client.request(case.method, case.path, **(case.kwargs or {}))
                self.assertEqual(response.status_code, case.expected_status, response.text)


if __name__ == "__main__":
    unittest.main()
