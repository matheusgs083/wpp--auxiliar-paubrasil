from __future__ import annotations

import unittest
from threading import RLock
from types import SimpleNamespace

from bot_api.services.health_service import HealthPayloadBuilder


class FakeStatusService:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def status(self) -> dict[str, object]:
        return dict(self.payload)


def base_report_status() -> dict[str, object]:
    return {
        "database_configured": True,
        "schema": "reports",
        "ready": True,
        "latest_view_exists": True,
        "last_error": "",
    }


class HealthPayloadBuilderTest(unittest.TestCase):
    def test_build_includes_evolution_and_webhook_runtime_observability(self) -> None:
        settings = SimpleNamespace(
            api_auth_enabled=True,
            api_auth_tokens=("token",),
            api_require_admin_for_number=True,
            admin_api_token="admin",
            verify_token="webhook",
            meta_cloud_enabled=False,
            meta_cloud_verify_token="",
            webhook_worker_threads=4,
            access_control_enabled=True,
            denied_reply_cooldown_minutes=10,
            denied_unregistered_reply_cooldown_minutes=60,
        )
        access_status = {
            "database_configured": True,
            "schema": "bot_access",
            "ready": True,
            "public_enabled": False,
            "connect_timeout_seconds": 3,
            "last_error": "",
        }
        security_status = {"enabled": True, "ready": True, "last_error": ""}
        evolution_status = {"enabled": True, "ready": True, "state": "open", "last_error": ""}
        webhook_snapshot = {"received": 3, "queued": 3, "delivery_errors": 1, "queue_depth": 0}

        builder = HealthPayloadBuilder(
            settings=settings,
            access_control=FakeStatusService(access_status),
            security_monitor=FakeStatusService(security_status),
            dclientes_query_service=FakeStatusService({**base_report_status(), "inadimplencia_view_exists": True, "comodatos_view_exists": True}),
            clientes_score_query_service=FakeStatusService(base_report_status()),
            inadimplencia_query_service=FakeStatusService({**base_report_status(), "dclientes_view_exists": True}),
            comodatos_query_service=FakeStatusService({**base_report_status(), "dclientes_view_exists": True}),
            giro_query_service=FakeStatusService(base_report_status()),
            evolution_client=SimpleNamespace(status=lambda: evolution_status),
            meta_cloud_client=SimpleNamespace(enabled=False),
            webhook_runtime=SimpleNamespace(snapshot=lambda: webhook_snapshot),
            daily_route_broadcast_lock=RLock(),
            daily_route_broadcast_status={"enabled": False},
        )

        payload = builder.build()

        self.assertEqual(payload["evolution"], evolution_status)
        self.assertEqual(payload["webhook_runtime"], webhook_snapshot)
        self.assertEqual(payload["webhook_worker_threads"], 4)


if __name__ == "__main__":
    unittest.main()
