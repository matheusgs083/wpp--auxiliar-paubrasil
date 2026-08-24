from __future__ import annotations

from typing import Any

from fastapi import FastAPI


def register_app_lifecycle(
    app: FastAPI,
    *,
    settings: Any,
    logger: Any,
    access_control: Any,
    security_monitor: Any,
    run_admin_import_maintenance: Any,
    start_daily_route_broadcast_scheduler: Any,
    stop_daily_route_broadcast_scheduler: Any,
    admin_imports_runtime: Any,
    admin_panel_user_service: Any,
    admin_financeiro_service: Any,
    conferencia_service: Any,
    critica_pdf_prebuild_executor: Any,
    admin_broadcast_executor: Any,
    admin_payip_batch_service: Any,
    webhook_executor: Any,
    promax_jobs_service: Any,
    promax_scheduler: Any,
    close_connection_pools: Any,
) -> None:
    @app.on_event("startup")
    def startup() -> None:
        if settings.access_control_enabled:
            ready = access_control.initialize()
            if not ready:
                logger.warning("RBAC Postgres indisponivel no startup: %s", access_control.status().get("last_error"))
        if settings.security_audit_enabled:
            ready = security_monitor.initialize()
            if not ready:
                logger.warning("Auditoria de seguranca indisponivel no startup: %s", security_monitor.status().get("last_error"))
        try:
            admin_panel_user_service.ensure_schema()
        except Exception as exc:
            logger.warning("Usuarios do painel indisponiveis no startup: %s", exc)
        try:
            admin_financeiro_service.ensure_schema()
        except Exception as exc:
            logger.warning("Fechamento financeiro indisponivel no startup: %s", exc)
        try:
            conferencia_service.ensure_schema()
        except Exception as exc:
            logger.warning("Conferencia indisponivel no startup: %s", exc)
        maintenance_result = run_admin_import_maintenance(force_stale=True)
        if not maintenance_result.get("ok"):
            logger.warning("Manutencao de imports indisponivel no startup: %s", maintenance_result.get("error"))
        try:
            promax_jobs_service.ensure_schema()
            promax_scheduler.start()
        except Exception as exc:
            logger.warning("Promax Admin indisponivel no startup: %s", exc)
        start_daily_route_broadcast_scheduler()

    @app.on_event("shutdown")
    def shutdown() -> None:
        promax_scheduler.stop()
        stop_daily_route_broadcast_scheduler()
        security_monitor.shutdown()
        admin_imports_runtime.shutdown()
        critica_pdf_prebuild_executor.shutdown(wait=False, cancel_futures=False)
        admin_broadcast_executor.shutdown(wait=False, cancel_futures=False)
        admin_payip_batch_service.shutdown()
        webhook_executor.shutdown(wait=True, cancel_futures=False)
        close_connection_pools()
