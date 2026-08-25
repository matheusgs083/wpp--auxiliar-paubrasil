from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from bot_api.routes.admin_access import create_admin_access_router
from bot_api.routes.admin_broadcast import create_admin_broadcast_router
from bot_api.routes.admin_conferencia import create_admin_conferencia_router
from bot_api.routes.admin_critica import create_admin_critica_router
from bot_api.routes.admin_financeiro import create_admin_financeiro_router
from bot_api.routes.admin_giro import create_admin_giro_router
from bot_api.routes.admin_imports import create_admin_imports_router
from bot_api.routes.admin_panel import create_admin_panel_router
from bot_api.routes.admin_payip import create_admin_payip_router
from bot_api.routes.admin_promax import create_admin_promax_router
from bot_api.routes.admin_recolhas import create_admin_recolhas_router
from bot_api.routes.admin_usage import create_admin_usage_router

RouteRegistrar = Callable[[FastAPI], None]


def build_admin_route_registrars(deps: dict[str, Any]) -> tuple[RouteRegistrar, ...]:
    return (
        lambda app: _register_admin_access_routes(app, deps=deps),
        lambda app: _register_admin_import_routes(app, deps=deps),
        lambda app: _register_admin_giro_routes(app, deps=deps),
        lambda app: _register_admin_critica_routes(app, deps=deps),
        lambda app: _register_admin_panel_routes(app, deps=deps),
        lambda app: _register_admin_recolha_routes(app, deps=deps),
        lambda app: _register_admin_financeiro_routes(app, deps=deps),
        lambda app: _register_admin_conferencia_routes(app, deps=deps),
        lambda app: _register_admin_payip_routes(app, deps=deps),
        lambda app: _register_admin_usage_routes(app, deps=deps),
        lambda app: _register_admin_broadcast_routes(app, deps=deps),
        lambda app: _register_admin_promax_routes(app, deps=deps),
    )


def _register_admin_access_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_access_router(
            access_control=deps["access_control"],
            access_call=deps["access_call"],
            require_admin_api_auth=deps["require_admin_api_auth"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_import_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_imports_router(
            access_call=deps["access_call"],
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            require_admin_panel_import_dataset=deps["require_admin_panel_import_dataset"],
            list_admin_import_status=deps["list_admin_import_status"],
            filter_admin_import_status_for_context=deps["filter_admin_import_status_for_context"],
            list_admin_import_history=deps["list_admin_import_history"],
            filter_admin_import_history_for_context=deps["filter_admin_import_history_for_context"],
            run_admin_import_validation=deps["run_admin_import_validation"],
            queue_admin_import=deps["queue_admin_import"],
            store_admin_import_uploads=deps["store_admin_import_uploads"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_giro_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_giro_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            build_admin_giro_recolha_dashboard=deps["build_admin_giro_recolha_dashboard"],
            build_admin_giro_recolha_filter_options=deps["build_admin_giro_recolha_filter_options"],
            build_admin_giro_recolha_routes=deps["build_admin_giro_recolha_routes"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_critica_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_critica_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            parse_admin_critica_date=deps["parse_admin_critica_date"],
            build_admin_critica_dashboard=deps["build_admin_critica_dashboard"],
            build_admin_critica_sector_pdf_response=deps["build_admin_critica_sector_pdf_response"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_panel_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_panel_router(
            admin_panel_context_from_session_cookie=deps["admin_panel_context_from_session_cookie"],
            load_admin_login_html=deps["load_admin_login_html"],
            load_admin_change_password_html=deps["load_admin_change_password_html"],
            load_admin_import_panel_html=deps["load_admin_import_panel_html"],
            check_admin_panel_login_rate_limit=deps["check_admin_panel_login_rate_limit"],
            admin_panel_context_from_token=deps["admin_panel_context_from_token"],
            admin_panel_context_from_credentials=deps["admin_panel_context_from_credentials"],
            record_admin_panel_login_failure=deps["record_admin_panel_login_failure"],
            clear_admin_panel_login_failures=deps["clear_admin_panel_login_failures"],
            set_admin_panel_session_cookie=deps["set_admin_panel_session_cookie"],
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            panel_context_mode=deps["panel_context_mode"],
            panel_context_can_access_feature=deps["panel_context_can_access_feature"],
            admin_panel_user_service=deps["admin_panel_user_service"],
            record_security_event=deps["record_security_event"],
            session_cookie_name=deps["admin_panel_session_cookie"],
            session_ttl_seconds=deps["admin_panel_session_ttl_seconds"],
        )
    )


def _register_admin_recolha_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_recolhas_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            list_admin_recolhas=deps["list_admin_recolhas"],
            update_admin_recolhas_bulk=deps["update_admin_recolhas_bulk"],
            import_admin_recolhas_csv=deps["import_admin_recolhas_csv"],
            export_admin_recolhas_csv=deps["export_admin_recolhas_csv"],
            update_admin_recolha=deps["update_admin_recolha"],
            delete_admin_recolha=deps["delete_admin_recolha"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_financeiro_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_financeiro_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            list_financeiro_caixa=deps["list_financeiro_caixa"],
            upsert_financeiro_mapa=deps["upsert_financeiro_mapa"],
            export_financeiro_caixa_pdf=deps["export_financeiro_caixa_pdf"],
            sync_financeiro_fechamento_promax=deps["sync_financeiro_fechamento_promax"],
            sync_conferencia_fechamento_promax=deps["sync_conferencia_fechamento_promax"],
            resolve_financeiro_fechamento_km=deps["resolve_financeiro_fechamento_km"],
            relatorio_031120_import_services=deps["relatorio_031120_import_services"],
            enqueue_promax_job=deps["enqueue_promax_job"],
            get_promax_job=deps["promax_jobs_service"].get_job,
            list_promax_job_logs=deps["promax_jobs_service"].list_job_logs,
            list_promax_worker_heartbeats=deps["promax_jobs_service"].list_worker_heartbeats,
            delete_financeiro_mapa=deps["delete_financeiro_mapa"],
            worker_token=deps["settings"].promax_worker_token,
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_conferencia_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_conferencia_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            panel_context_can_access_feature=deps["panel_context_can_access_feature"],
            list_conferencia_mapas=deps["list_conferencia_mapas"],
            list_conferencia_garrafeiras=deps["list_conferencia_garrafeiras"],
            get_conferencia_mapa=deps["get_conferencia_mapa"],
            save_conferencia_counts=deps["save_conferencia_counts"],
            search_conferencia_products=deps["search_conferencia_products"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_payip_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_payip_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            preview_payip_batch=deps["preview_payip_batch"],
            queue_payip_batch=deps["queue_payip_batch"],
            snapshot_payip_batch=deps["snapshot_payip_batch"],
            export_payip_batch_csv=deps["export_payip_batch_csv"],
            payip_batch_pdf_bytes=deps["payip_batch_pdf_bytes"],
            validate_payip_promax_import=deps["validate_payip_promax_import"],
            create_payip_promax_import_clients=deps["create_payip_promax_import_clients"],
            run_payip_promax_import=deps["run_payip_promax_import"],
            list_payip_generated_batches=deps["list_payip_generated_batches"],
            payip_generated_batch_process=deps["payip_generated_batch_process"],
            payip_generated_batch_file_bytes=deps["payip_generated_batch_file_bytes"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_usage_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_usage_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            list_admin_evolution_usage=deps["list_admin_evolution_usage"],
            build_evolution_usage_avg_report_csv=deps["build_evolution_usage_avg_report_csv"],
            build_evolution_function_usage_report_csv=deps["build_evolution_function_usage_report_csv"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_broadcast_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_broadcast_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            list_admin_broadcast_options=deps["list_admin_broadcast_options"],
            snapshot_admin_broadcast_state=deps["snapshot_admin_broadcast_state"],
            build_admin_broadcast_payload=deps["build_admin_broadcast_payload"],
            queue_admin_broadcast=deps["queue_admin_broadcast"],
            record_security_event=deps["record_security_event"],
        )
    )


def _register_admin_promax_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_admin_promax_router(
            service=deps["promax_jobs_service"],
            catalog=deps["promax_catalog"],
            worker_token=deps["settings"].promax_worker_token,
            boletos_pdf_import_services=deps["boletos_pdf_import_services"],
            estoque_020304_import_services=deps["estoque_020304_import_services"],
            relatorio_031120_import_services=deps["relatorio_031120_import_services"],
            relatorio_03114902_import_service=deps["relatorio_03114902_import_service"],
            inadimplencia_import_service=deps["inadimplencia_import_service"],
            comodatos_import_service=deps["comodatos_import_service"],
            dclientes_import_service=deps["dclientes_import_service"],
            dmateriais_import_service=deps["dmateriais_import_service"],
            documentacao_pendente_import_service=deps["documentacao_pendente_import_service"],
            critica_operacao_import_services=deps["critica_operacao_import_services"],
            after_critica_operacao_import=deps["after_critica_operacao_import"],
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            record_security_event=deps["record_security_event"],
        )
    )
