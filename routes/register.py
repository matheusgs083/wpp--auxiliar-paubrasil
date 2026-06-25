from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from bot_api.routes.admin_access import create_admin_access_router
from bot_api.routes.admin_broadcast import create_admin_broadcast_router
from bot_api.routes.admin_critica import create_admin_critica_router
from bot_api.routes.admin_giro import create_admin_giro_router
from bot_api.routes.admin_imports import create_admin_imports_router
from bot_api.routes.admin_panel import create_admin_panel_router
from bot_api.routes.admin_payip import create_admin_payip_router
from bot_api.routes.admin_recolhas import create_admin_recolhas_router
from bot_api.routes.admin_usage import create_admin_usage_router
from bot_api.routes.health import create_health_router
from bot_api.routes.public_queries import create_public_queries_router
from bot_api.routes.webhooks import create_webhooks_router


def register_routes(app: FastAPI, *, deps: dict[str, Any]) -> None:
    app.include_router(
        create_health_router(
            build_detailed_health_payload=deps["build_detailed_health_payload"],
            require_admin_api_auth=deps["require_admin_api_auth"],
        )
    )
    app.include_router(
        create_admin_access_router(
            access_control=deps["access_control"],
            access_call=deps["access_call"],
            require_admin_api_auth=deps["require_admin_api_auth"],
            record_security_event=deps["record_security_event"],
        )
    )
    app.include_router(
        create_admin_imports_router(
            access_call=deps["access_call"],
            require_admin_panel_auth=deps["require_admin_panel_auth"],
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
    app.include_router(
        create_public_queries_router(
            access_control=deps["access_control"],
            dclientes_query_service=deps["dclientes_query_service"],
            inadimplencia_query_service=deps["inadimplencia_query_service"],
            comodatos_query_service=deps["comodatos_query_service"],
            require_api_auth=deps["require_api_auth"],
            require_admin_scope_for_number_routes=deps["require_admin_scope_for_number_routes"],
            decision_has_unrestricted_lookup_access=deps["decision_has_unrestricted_lookup_access"],
            record_security_event=deps["record_security_event"],
        )
    )
    app.include_router(
        create_admin_panel_router(
            admin_panel_context_from_session_cookie=deps["admin_panel_context_from_session_cookie"],
            load_admin_login_html=deps["load_admin_login_html"],
            load_admin_import_panel_html=deps["load_admin_import_panel_html"],
            check_admin_panel_login_rate_limit=deps["check_admin_panel_login_rate_limit"],
            admin_panel_context_from_token=deps["admin_panel_context_from_token"],
            record_admin_panel_login_failure=deps["record_admin_panel_login_failure"],
            clear_admin_panel_login_failures=deps["clear_admin_panel_login_failures"],
            set_admin_panel_session_cookie=deps["set_admin_panel_session_cookie"],
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            panel_context_mode=deps["panel_context_mode"],
            record_security_event=deps["record_security_event"],
            session_cookie_name=deps["admin_panel_session_cookie"],
            session_ttl_seconds=deps["admin_panel_session_ttl_seconds"],
        )
    )
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
    app.include_router(
        create_admin_payip_router(
            require_admin_panel_auth=deps["require_admin_panel_auth"],
            require_admin_panel_feature=deps["require_admin_panel_feature"],
            preview_payip_batch=deps["preview_payip_batch"],
            queue_payip_batch=deps["queue_payip_batch"],
            snapshot_payip_batch=deps["snapshot_payip_batch"],
            export_payip_batch_csv=deps["export_payip_batch_csv"],
            payip_batch_pdf_bytes=deps["payip_batch_pdf_bytes"],
            record_security_event=deps["record_security_event"],
        )
    )
    app.include_router(
        create_admin_usage_router(
            require_admin_api_auth=deps["require_admin_api_auth"],
            list_admin_evolution_usage=deps["list_admin_evolution_usage"],
            build_evolution_usage_avg_report_csv=deps["build_evolution_usage_avg_report_csv"],
            build_evolution_function_usage_report_csv=deps["build_evolution_function_usage_report_csv"],
            record_security_event=deps["record_security_event"],
        )
    )
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
    app.include_router(
        create_webhooks_router(
            settings=deps["settings"],
            meta_cloud_client=deps["meta_cloud_client"],
            require_webhook_token=deps["require_webhook_token"],
            require_meta_cloud_signature=deps["require_meta_cloud_signature"],
            queue_incoming_webhook=deps["queue_incoming_webhook"],
            record_security_event=deps["record_security_event"],
        )
    )
