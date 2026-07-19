from __future__ import annotations

from threading import RLock
from typing import Any


class HealthPayloadBuilder:
    def __init__(
        self,
        *,
        settings: Any,
        access_control: Any,
        security_monitor: Any,
        dclientes_query_service: Any,
        inadimplencia_query_service: Any,
        comodatos_query_service: Any,
        giro_query_service: Any,
        evolution_client: Any,
        meta_cloud_client: Any,
        webhook_runtime: Any,
        daily_route_broadcast_lock: RLock,
        daily_route_broadcast_status: dict[str, Any],
    ) -> None:
        self.settings = settings
        self.access_control = access_control
        self.security_monitor = security_monitor
        self.dclientes_query_service = dclientes_query_service
        self.inadimplencia_query_service = inadimplencia_query_service
        self.comodatos_query_service = comodatos_query_service
        self.giro_query_service = giro_query_service
        self.evolution_client = evolution_client
        self.meta_cloud_client = meta_cloud_client
        self.webhook_runtime = webhook_runtime
        self.daily_route_broadcast_lock = daily_route_broadcast_lock
        self.daily_route_broadcast_status = daily_route_broadcast_status

    def build(self) -> dict[str, Any]:
        access_status = self.access_control.status()
        security_status = self.security_monitor.status()
        reports_status = self.dclientes_query_service.status()
        inadimplencia_status = self.inadimplencia_query_service.status()
        comodatos_status = self.comodatos_query_service.status()
        giro_status = self.giro_query_service.status()
        evolution_status = self.evolution_client.status()
        webhook_status = self.webhook_runtime.snapshot()
        with self.daily_route_broadcast_lock:
            daily_route_status = dict(self.daily_route_broadcast_status)
        return {
            "ok": True,
            "api_auth_enabled": self.settings.api_auth_enabled,
            "api_auth_token_count": len(self.settings.api_auth_tokens),
            "api_require_admin_for_number": self.settings.api_require_admin_for_number,
            "admin_token_configured": bool(self.settings.admin_api_token.strip()),
            "webhook_auth_required": True,
            "webhook_token_configured": bool(self.settings.verify_token.strip()),
            "webhook_runtime": webhook_status,
            "evolution": evolution_status,
            "meta_cloud_enabled": self.settings.meta_cloud_enabled,
            "meta_cloud_ready": self.meta_cloud_client.enabled,
            "meta_cloud_verify_token_configured": bool(self.settings.meta_cloud_verify_token.strip()),
            "webhook_worker_threads": self.settings.webhook_worker_threads,
            "security_audit_enabled": security_status["enabled"],
            "security_audit_ready": security_status["ready"],
            "security_audit_last_error": security_status["last_error"],
            "access_control_enabled": self.settings.access_control_enabled,
            "access_database_configured": access_status["database_configured"],
            "access_db_schema": access_status["schema"],
            "access_db_ready": access_status["ready"],
            "access_public_enabled": access_status["public_enabled"],
            "access_connect_timeout_seconds": access_status["connect_timeout_seconds"],
            "access_last_error": access_status["last_error"],
            "denied_reply_cooldown_minutes": self.settings.denied_reply_cooldown_minutes,
            "denied_unregistered_reply_cooldown_minutes": self.settings.denied_unregistered_reply_cooldown_minutes,
            "reports_database_configured": reports_status["database_configured"],
            "reports_db_schema": reports_status["schema"],
            "reports_db_ready": reports_status["ready"],
            "reports_latest_view_exists": reports_status["latest_view_exists"],
            "reports_inadimplencia_view_exists": reports_status.get("inadimplencia_view_exists", False),
            "reports_comodatos_view_exists": reports_status.get("comodatos_view_exists", False),
            "reports_last_error": reports_status["last_error"],
            "inadimplencia_ready": inadimplencia_status["ready"],
            "inadimplencia_latest_view_exists": inadimplencia_status["latest_view_exists"],
            "inadimplencia_dclientes_view_exists": inadimplencia_status["dclientes_view_exists"],
            "inadimplencia_last_error": inadimplencia_status["last_error"],
            "comodatos_ready": comodatos_status["ready"],
            "comodatos_latest_view_exists": comodatos_status["latest_view_exists"],
            "comodatos_dclientes_view_exists": comodatos_status["dclientes_view_exists"],
            "comodatos_last_error": comodatos_status["last_error"],
            "giro_ready": giro_status["ready"],
            "giro_latest_view_exists": giro_status["latest_view_exists"],
            "giro_last_error": giro_status["last_error"],
            "daily_route_broadcast": daily_route_status,
        }
