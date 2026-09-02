from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock, RLock
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile

from bot_api.db import close_all_connection_pools
from bot_api.services import (
    admin_broadcast_service,
    admin_critica_dashboard_service,
    admin_imports_runtime,
    admin_usage_service,
)
from bot_api.services.admin_broadcast_config import build_admin_broadcast_config
from bot_api.services.admin_financeiro_service import AdminFinanceiroService
from bot_api.services.admin_import_config import ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS, build_admin_import_datasets
from bot_api.services.admin_templates import AdminTemplateLoader
from bot_api.services.app_lifecycle import register_app_lifecycle
from bot_api.services.admin_panel_session_service import AdminPanelSessionService
from bot_api.services.admin_panel_user_service import AdminPanelUserService
from bot_api.services.admin_payip_batch_service import AdminPayipBatchService
from bot_api.services.admin_recolhas_service import AdminRecolhasService
from bot_api.services.boletos_pdf_import_service import BoletosPdfImportService
from bot_api.services.critica_operacao_import_service import CriticaOperacaoImportService
from bot_api.services.critica_rn_query_service import CriticaPdfCurrentImportRequiredError
from bot_api.services.estoque_020304_service import Estoque020304ImportService
from bot_api.services.relatorio_031120_import_service import Relatorio031120ImportService
from bot_api.services.filial_labels import set_filial_labels
from bot_api.services.health_service import HealthPayloadBuilder
from bot_api.services.promax_catalog_service import DEFAULT_PROMAX_CATALOG, PromaxCatalogService
from bot_api.services.promax_scheduler import PromaxScheduler
from bot_api.services.webhook_runtime import WebhookRuntime
from bot_api.security.http_auth import HttpAuthDependencies
from bot_api.routes.register import register_routes


def configure_app_runtime(
    *,
    app: FastAPI,
    settings: Any,
    services: Any,
    project_root: Path,
    logger: Any,
) -> None:
    admin_import_job_service = services.admin_import_job_service
    promax_jobs_service = services.promax_jobs_service
    promax_scheduler = PromaxScheduler(
        promax_jobs_service,
        enqueue_interval_seconds=settings.promax_scheduler_interval_seconds,
        reaper_interval_seconds=settings.promax_scheduler_interval_seconds,
    )
    promax_catalog_service = PromaxCatalogService(
        jobs_service=promax_jobs_service,
        fallback_catalog=DEFAULT_PROMAX_CATALOG,
    )
    PROMAX_CATALOG = promax_catalog_service.get_catalog
    dclientes_query_service = services.dclientes_query_service
    inadimplencia_query_service = services.inadimplencia_query_service
    comodatos_query_service = services.comodatos_query_service
    giro_query_service = services.giro_query_service
    critica_rn_query_service = services.critica_rn_query_service
    critica_rn_pdf_prebuild_service = services.critica_rn_pdf_prebuild_service
    documentacao_pendente_query_service = services.documentacao_pendente_query_service
    prazo_limite_query_service = services.prazo_limite_query_service
    dsetores_import_service = services.dsetores_import_service
    dprecos_import_service = services.dprecos_import_service
    doperacoes_import_service = services.doperacoes_import_service
    drevendas_import_service = services.drevendas_import_service
    dcondicoes_import_service = services.dcondicoes_import_service
    dprodutos_import_service = services.dprodutos_import_service
    dmateriais_import_service = services.dmateriais_import_service
    produto_cestas_import_service = services.produto_cestas_import_service
    dclientes_import_service = services.dclientes_import_service
    inadimplencia_import_service = services.inadimplencia_import_service
    comodatos_import_service = services.comodatos_import_service
    giro_import_service = services.giro_import_service
    critica_rn_import_service = services.critica_rn_import_service
    critica_operacao_import_services = services.critica_operacao_import_services
    critica_operacao_admin_service = services.critica_operacao_admin_service
    documentacao_pendente_import_service = services.documentacao_pendente_import_service
    prazo_limite_import_service = services.prazo_limite_import_service
    recolha_request_service = services.recolha_request_service
    evolution_client = services.evolution_client
    meta_cloud_client = services.meta_cloud_client
    access_control = services.access_control
    security_monitor = services.security_monitor
    payip_payments_service = services.payip_payments_service
    protestos_service = services.protestos_service
    lookup_flow = services.lookup_flow
    webhook_executor = ThreadPoolExecutor(
        max_workers=settings.webhook_worker_threads,
        thread_name_prefix="webhook-worker",
    )

    PROJECT_ROOT = project_root
    ADMIN_IMPORT_PANEL_TEMPLATE = PROJECT_ROOT / "templates" / "admin_import_panel.html"
    ADMIN_LOGIN_TEMPLATE = PROJECT_ROOT / "templates" / "admin_login.html"
    ADMIN_CHANGE_PASSWORD_TEMPLATE = PROJECT_ROOT / "templates" / "admin_change_password.html"
    ADMIN_IMPORT_RUNTIME_ROOT = (
        Path("/tmp/bot_api_admin_imports") if Path("/tmp").exists() else PROJECT_ROOT / "exports" / "admin_import_uploads"
    )
    ADMIN_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
    ADMIN_PANEL_SESSION_COOKIE = "bot_admin_session"
    ADMIN_PANEL_SESSION_TTL_SECONDS = 12 * 60 * 60
    ADMIN_PANEL_LOGIN_WINDOW_SECONDS = 5 * 60
    ADMIN_PANEL_LOGIN_MAX_FAILURES = 10
    admin_panel_user_service = AdminPanelUserService(
        database_url=settings.access_database_url,
        schema=settings.access_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
        bootstrap_database_url=settings.reports_database_url,
    )
    admin_panel_session_service = AdminPanelSessionService(
        admin_api_token=settings.admin_api_token,
        session_secret=settings.admin_panel_session_secret,
        verify_token=settings.verify_token,
        api_auth_tokens=settings.api_auth_tokens,
        finance_panel_tokens=settings.finance_panel_tokens,
        critica_panel_tokens=settings.critica_panel_tokens,
        session_cookie_name=ADMIN_PANEL_SESSION_COOKIE,
        session_ttl_seconds=ADMIN_PANEL_SESSION_TTL_SECONDS,
        login_window_seconds=ADMIN_PANEL_LOGIN_WINDOW_SECONDS,
        login_max_failures=ADMIN_PANEL_LOGIN_MAX_FAILURES,
        panel_user_service=admin_panel_user_service,
    )


    ADMIN_IMPORT_DATASETS = build_admin_import_datasets(
        project_root=PROJECT_ROOT,
        services=services,
        filial_labels=services.filial_labels,
    )

    def _refresh_filial_labels_runtime() -> dict[str, Any]:
        latest_labels = services.drevendas_import_service.latest_labels()
        if latest_labels:
            services.filial_labels.clear()
            services.filial_labels.update(latest_labels)
            set_filial_labels(latest_labels)
            for filial_code in sorted(latest_labels, key=int):
                if filial_code not in services.boletos_pdf_import_services:
                    services.boletos_pdf_import_services[filial_code] = BoletosPdfImportService(
                        database_url=settings.reports_database_url,
                        schema=settings.reports_db_schema,
                        dataset_name=f"boletos_bradesco_op_{filial_code}",
                        expected_filial=filial_code,
                        connect_timeout_seconds=settings.access_database_timeout_seconds,
                    )
                if filial_code not in services.estoque_020304_import_services:
                    services.estoque_020304_import_services[filial_code] = Estoque020304ImportService(
                        database_url=settings.reports_database_url,
                        schema=settings.reports_db_schema,
                        dataset_name=f"estoque_020304_op_{filial_code}",
                        expected_filial=filial_code,
                        filial_nome=latest_labels[filial_code],
                        connect_timeout_seconds=settings.access_database_timeout_seconds,
                    )
                if filial_code not in services.relatorio_031120_import_services:
                    services.relatorio_031120_import_services[filial_code] = Relatorio031120ImportService(
                        database_url=settings.reports_database_url,
                        schema=settings.reports_db_schema,
                        dataset_name=f"relatorio_031120_op_{filial_code}",
                        expected_filial=filial_code,
                        filial_nome=latest_labels[filial_code],
                        connect_timeout_seconds=settings.access_database_timeout_seconds,
                    )
                if filial_code not in services.critica_operacao_import_services:
                    services.critica_operacao_import_services[filial_code] = CriticaOperacaoImportService(
                        database_url=settings.reports_database_url,
                        schema=settings.reports_db_schema,
                        dataset_name=f"critica_op_{filial_code}",
                        expected_filial=filial_code,
                        connect_timeout_seconds=settings.access_database_timeout_seconds,
                    )
            refreshed_datasets = build_admin_import_datasets(
                project_root=PROJECT_ROOT,
                services=services,
                filial_labels=services.filial_labels,
            )
            ADMIN_IMPORT_DATASETS.clear()
            ADMIN_IMPORT_DATASETS.update(refreshed_datasets)
        return {"ok": bool(latest_labels), "total": len(latest_labels), "datasets": len(ADMIN_IMPORT_DATASETS)}

    critica_pdf_prebuild_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="critica-pdf-prebuild")
    critica_pdf_prebuild_lock = Lock()
    critica_pdf_prebuild_state: dict[str, Any] = {
        "running": False,
        "pending": False,
        "current_job_id": "",
        "current_reason": "",
        "queued_at": "",
        "started_at": "",
        "finished_at": "",
        "last_result": {},
        "last_error": "",
    }
    admin_broadcast_config = build_admin_broadcast_config(
        daily_route_broadcast_enabled=settings.daily_route_broadcast_enabled,
    )
    ADMIN_BROADCAST_ACTIONS = admin_broadcast_config.actions
    ADMIN_BROADCAST_DAY_OPTIONS = admin_broadcast_config.day_options
    ADMIN_BROADCAST_TARGET_MODES = admin_broadcast_config.target_modes
    ADMIN_BROADCAST_AUDIENCES = admin_broadcast_config.audiences
    ADMIN_BROADCAST_SEND_DELAY_SECONDS = admin_broadcast_config.send_delay_seconds
    admin_broadcast_state = admin_broadcast_config.state
    daily_route_broadcast_status = admin_broadcast_config.daily_route_status
    admin_broadcast_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="admin-broadcast")
    admin_broadcast_lock = Lock()
    daily_route_broadcast_lock = RLock()
    daily_route_broadcast_stop_event = Event()

    auth_deps = HttpAuthDependencies(
        settings=settings,
        security_monitor=security_monitor,
        admin_panel_session_service=admin_panel_session_service,
        admin_import_datasets=ADMIN_IMPORT_DATASETS,
        normalize_admin_import_dataset=lambda dataset: admin_imports_runtime._normalize_admin_import_dataset(dataset),
    )
    auth_deps.add_security_middleware(app)

    _admin_panel_context_from_token = admin_panel_session_service.context_from_token
    _admin_panel_context_from_credentials = admin_panel_session_service.context_from_credentials
    _admin_panel_context_from_session_cookie = admin_panel_session_service.context_from_session_cookie
    _set_admin_panel_session_cookie = admin_panel_session_service.set_session_cookie
    _check_admin_panel_login_rate_limit = admin_panel_session_service.check_login_rate_limit
    _record_admin_panel_login_failure = admin_panel_session_service.record_login_failure
    _clear_admin_panel_login_failures = admin_panel_session_service.clear_login_failures
    _admin_token_matches = admin_panel_session_service.admin_token_matches
    _finance_panel_token_filiais = admin_panel_session_service.finance_panel_token_filiais
    _critica_panel_token_filiais = admin_panel_session_service.critica_panel_token_filiais
    _panel_context_mode = admin_panel_session_service.panel_context_mode
    _panel_context_has_all_filiais = admin_panel_session_service.panel_context_has_all_filiais
    _panel_context_is_critica_only = admin_panel_session_service.panel_context_is_critica_only
    _panel_context_can_access_feature = admin_panel_session_service.panel_context_can_access_feature
    _require_admin_panel_feature = admin_panel_session_service.require_feature
    _request_metadata = auth_deps.request_metadata
    _record_security_event = auth_deps.record_security_event
    _record_security_event_for_path = auth_deps.record_security_event_for_path
    _should_send_denied_reply = auth_deps.should_send_denied_reply
    _require_admin_token = auth_deps.require_admin_token
    _require_api_auth = auth_deps.require_api_auth
    _panel_context_allowed_import_datasets = auth_deps.panel_context_allowed_import_datasets
    _require_admin_panel_import_dataset = auth_deps.require_admin_panel_import_dataset
    _require_admin_panel_auth = auth_deps.require_admin_panel_auth
    _require_admin_api_auth = auth_deps.require_admin_api_auth
    _require_admin_scope_for_number_routes = auth_deps.require_admin_scope_for_number_routes
    _decision_has_unrestricted_lookup_access = auth_deps.decision_has_unrestricted_lookup_access
    _require_webhook_token = auth_deps.require_webhook_token
    _require_meta_cloud_signature = auth_deps.require_meta_cloud_signature


    def _access_call(func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


    admin_imports_runtime.configure(
        logger=logger,
        settings=settings,
        ADMIN_IMPORT_DATASETS=ADMIN_IMPORT_DATASETS,
        ADMIN_IMPORT_RUNTIME_ROOT=ADMIN_IMPORT_RUNTIME_ROOT,
        ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS=ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS,
        admin_import_job_service=admin_import_job_service,
        dclientes_import_service=dclientes_import_service,
        giro_import_service=giro_import_service,
        critica_rn_import_service=critica_rn_import_service,
        critica_operacao_admin_service=critica_operacao_admin_service,
        critica_rn_query_service=critica_rn_query_service,
        critica_rn_pdf_prebuild_service=critica_rn_pdf_prebuild_service,
        critica_pdf_prebuild_executor=critica_pdf_prebuild_executor,
        critica_pdf_prebuild_lock=critica_pdf_prebuild_lock,
        critica_pdf_prebuild_state=critica_pdf_prebuild_state,
        _panel_context_allowed_import_datasets=_panel_context_allowed_import_datasets,
        _refresh_filial_labels_runtime=_refresh_filial_labels_runtime,
    )
    _normalize_admin_import_dataset = admin_imports_runtime._normalize_admin_import_dataset
    _run_admin_import_validation = admin_imports_runtime._run_admin_import_validation
    _queue_admin_import = admin_imports_runtime._queue_admin_import
    _run_admin_import_maintenance = admin_imports_runtime._run_admin_import_maintenance
    _store_admin_import_uploads = admin_imports_runtime._store_admin_import_uploads
    _list_admin_import_status = admin_imports_runtime._list_admin_import_status
    _list_admin_import_history = admin_imports_runtime._list_admin_import_history
    _filter_admin_import_status_for_context = admin_imports_runtime._filter_admin_import_status_for_context
    _filter_admin_import_history_for_context = admin_imports_runtime._filter_admin_import_history_for_context
    _clear_critica_runtime_cache = admin_imports_runtime._clear_critica_runtime_cache
    _queue_critica_pdf_prebuild = admin_imports_runtime._queue_critica_pdf_prebuild
    _snapshot_critica_pdf_prebuild_state = admin_imports_runtime._snapshot_critica_pdf_prebuild_state
    _serialize_admin_import_value = admin_imports_runtime._serialize_admin_import_value


    def _copy_upload_with_limit(upload: UploadFile, buffer: Any) -> int:
        max_bytes = settings.admin_upload_max_file_size_mb * 1024 * 1024
        total_bytes = 0
        while True:
            chunk = upload.file.read(ADMIN_UPLOAD_CHUNK_SIZE_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            if max_bytes > 0 and total_bytes > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Arquivo excede o limite de {settings.admin_upload_max_file_size_mb} MB.",
                )
            buffer.write(chunk)
        return total_bytes


    admin_recolhas_service = AdminRecolhasService(
        recolha_request_service=recolha_request_service,
        giro_query_service=giro_query_service,
        comodatos_query_service=comodatos_query_service,
        access_control=access_control,
        filial_labels=services.filial_labels,
        panel_context_has_all_filiais=_panel_context_has_all_filiais,
        panel_context_is_critica_only=_panel_context_is_critica_only,
        copy_upload_with_limit=_copy_upload_with_limit,
        logger=logger,
    )
    _build_admin_giro_recolha_dashboard = admin_recolhas_service.build_giro_recolha_dashboard
    _build_admin_giro_recolha_filter_options = admin_recolhas_service.build_giro_recolha_filter_options
    _build_admin_giro_recolha_routes = admin_recolhas_service.build_giro_recolha_routes
    _list_admin_recolhas = admin_recolhas_service.list_recolhas
    _export_admin_recolhas_csv = admin_recolhas_service.export_recolhas_csv
    _update_admin_recolha = admin_recolhas_service.update_recolha
    _update_admin_recolhas_bulk = admin_recolhas_service.update_recolhas_bulk
    _import_admin_recolhas_csv = admin_recolhas_service.import_recolhas_csv
    _delete_admin_recolha = admin_recolhas_service.delete_recolha

    admin_financeiro_service = AdminFinanceiroService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
        filial_labels=services.filial_labels,
    )
    _list_financeiro_caixa = admin_financeiro_service.list_caixa
    _upsert_financeiro_mapa = admin_financeiro_service.upsert_mapa
    _export_financeiro_caixa_pdf = admin_financeiro_service.export_caixa_pdf
    _sync_financeiro_fechamento_promax = admin_financeiro_service.sync_fechamento_promax
    _resolve_financeiro_fechamento_km = admin_financeiro_service.resolve_fechamento_km
    _delete_financeiro_mapa = admin_financeiro_service.delete_mapa
    conferencia_service = services.conferencia_service
    _sync_conferencia_fechamento_promax = conferencia_service.sync_from_promax
    _list_conferencia_mapas = conferencia_service.list_mapas
    _list_conferencia_garrafeiras = conferencia_service.list_garrafeira_consolidado
    _create_conferencia_mapa = conferencia_service.create_manual_mapa
    _get_conferencia_mapa = conferencia_service.get_mapa
    _save_conferencia_counts = conferencia_service.save_counts
    _search_conferencia_products = conferencia_service.search_products
    _list_admin_protestos = protestos_service.list_dashboard
    _update_admin_protesto = protestos_service.update_title
    _upload_admin_protesto_document = protestos_service.upload_document
    _download_admin_protesto_document = protestos_service.download_document


    def _panel_context_allowed_report_scopes(context: dict[str, Any] | None) -> tuple[list[str] | None, list[str] | None]:
        if not context or bool(context.get("is_admin")):
            return None, None
        if _panel_context_has_all_filiais(context):
            return None, None
        allowed_filiais = [
            str(filial).strip()
            for filial in context.get("filiais", ())
            if str(filial).strip() and str(filial).strip() != "*"
        ]
        return allowed_filiais, None

    admin_critica_dashboard_service.configure(
        critica_rn_query_service=critica_rn_query_service,
        _panel_context_allowed_report_scopes=_panel_context_allowed_report_scopes,
    )
    _parse_admin_critica_date = admin_critica_dashboard_service._parse_admin_critica_date
    _build_admin_critica_dashboard = admin_critica_dashboard_service._build_admin_critica_dashboard
    _build_admin_critica_sector_pdf_response = admin_critica_dashboard_service._build_admin_critica_sector_pdf_response


    admin_usage_service.configure(settings=settings, security_monitor=security_monitor)
    _snapshot_lookup_flow_session = admin_usage_service._snapshot_lookup_flow_session
    _infer_evolution_usage_feature = admin_usage_service._infer_evolution_usage_feature
    _list_admin_evolution_usage = admin_usage_service._list_admin_evolution_usage
    _build_evolution_usage_avg_report_csv = admin_usage_service._build_evolution_usage_avg_report_csv
    _build_evolution_function_usage_report_csv = admin_usage_service._build_evolution_function_usage_report_csv

    admin_panel_audit_service = services.admin_panel_audit_service

    def _record_admin_panel_action(**kwargs: Any) -> None:
        try:
            admin_panel_audit_service.record(**kwargs)
        except Exception as exc:
            logger.warning("Falha ao registrar auditoria do painel: %s", exc)

    _list_admin_panel_audit_actions = admin_panel_audit_service.list_actions
    _build_admin_panel_audit_report_csv = admin_panel_audit_service.build_csv


    admin_broadcast_service.configure(
        settings=settings,
        PROJECT_ROOT=PROJECT_ROOT,
        access_control=access_control,
        evolution_client=evolution_client,
        lookup_flow=lookup_flow,
        logger=logger,
        _access_call=_access_call,
        ADMIN_BROADCAST_ACTIONS=ADMIN_BROADCAST_ACTIONS,
        ADMIN_BROADCAST_DAY_OPTIONS=ADMIN_BROADCAST_DAY_OPTIONS,
        ADMIN_BROADCAST_TARGET_MODES=ADMIN_BROADCAST_TARGET_MODES,
        ADMIN_BROADCAST_AUDIENCES=ADMIN_BROADCAST_AUDIENCES,
        ADMIN_BROADCAST_SEND_DELAY_SECONDS=ADMIN_BROADCAST_SEND_DELAY_SECONDS,
        admin_broadcast_executor=admin_broadcast_executor,
        admin_broadcast_lock=admin_broadcast_lock,
        admin_broadcast_state=admin_broadcast_state,
        daily_route_broadcast_lock=daily_route_broadcast_lock,
        daily_route_broadcast_stop_event=daily_route_broadcast_stop_event,
        daily_route_broadcast_status=daily_route_broadcast_status,
    )
    _list_admin_broadcast_options = admin_broadcast_service._list_admin_broadcast_options
    _snapshot_admin_broadcast_state = admin_broadcast_service._snapshot_admin_broadcast_state
    _build_admin_broadcast_payload = admin_broadcast_service._build_admin_broadcast_payload
    _queue_admin_broadcast = admin_broadcast_service._queue_admin_broadcast
    _start_daily_route_broadcast_scheduler = admin_broadcast_service._start_daily_route_broadcast_scheduler
    _stop_daily_route_broadcast_scheduler = admin_broadcast_service._stop_daily_route_broadcast_scheduler


    admin_payip_batch_service = AdminPayipBatchService(
        payip_payments_service=payip_payments_service,
        dclientes_query_service=dclientes_query_service,
        panel_context_has_all_filiais=_panel_context_has_all_filiais,
        logger=logger,
    )
    _preview_payip_batch = admin_payip_batch_service.preview
    _queue_payip_batch = admin_payip_batch_service.queue
    _snapshot_payip_batch = admin_payip_batch_service.snapshot
    _export_payip_batch_csv = admin_payip_batch_service.export_csv
    _payip_batch_pdf_bytes = admin_payip_batch_service.pdf_bytes
    _validate_payip_promax_import = admin_payip_batch_service.validate_promax_import
    _create_payip_promax_import_clients = admin_payip_batch_service.create_promax_import_clients
    _run_payip_promax_import = admin_payip_batch_service.run_promax_import
    _list_payip_generated_batches = admin_payip_batch_service.generated_batches
    _payip_generated_batch_process = admin_payip_batch_service.generated_batch_process
    _payip_generated_batch_file_bytes = admin_payip_batch_service.generated_batch_file


    admin_template_loader = AdminTemplateLoader(
        import_panel_template=ADMIN_IMPORT_PANEL_TEMPLATE,
        login_template=ADMIN_LOGIN_TEMPLATE,
        change_password_template=ADMIN_CHANGE_PASSWORD_TEMPLATE,
        api_auth_enabled=settings.api_auth_enabled,
    )
    _load_admin_import_panel_html = admin_template_loader.load_import_panel_html
    _load_admin_login_html = admin_template_loader.load_login_html
    _load_admin_change_password_html = admin_template_loader.load_change_password_html

    register_app_lifecycle(
        app,
        settings=settings,
        logger=logger,
        access_control=access_control,
        security_monitor=security_monitor,
        run_admin_import_maintenance=_run_admin_import_maintenance,
        start_daily_route_broadcast_scheduler=_start_daily_route_broadcast_scheduler,
        stop_daily_route_broadcast_scheduler=_stop_daily_route_broadcast_scheduler,
        admin_imports_runtime=admin_imports_runtime,
        admin_panel_user_service=admin_panel_user_service,
        admin_panel_audit_service=admin_panel_audit_service,
        admin_financeiro_service=admin_financeiro_service,
        conferencia_service=conferencia_service,
        protestos_service=protestos_service,
        critica_pdf_prebuild_executor=critica_pdf_prebuild_executor,
        admin_broadcast_executor=admin_broadcast_executor,
        admin_payip_batch_service=admin_payip_batch_service,
        webhook_executor=webhook_executor,
        promax_jobs_service=promax_jobs_service,
        promax_scheduler=promax_scheduler,
        close_connection_pools=close_all_connection_pools,
    )

    webhook_runtime = WebhookRuntime(
        settings=settings,
        logger=logger,
        access_control=access_control,
        lookup_flow=lookup_flow,
        evolution_client=evolution_client,
        meta_cloud_client=meta_cloud_client,
        webhook_executor=webhook_executor,
        request_metadata=_request_metadata,
        record_security_event=_record_security_event,
        record_security_event_for_path=_record_security_event_for_path,
        should_send_denied_reply=_should_send_denied_reply,
        denied_reply_cooldown_minutes_for=auth_deps.denied_reply_cooldown_minutes_for,
        snapshot_lookup_flow_session=_snapshot_lookup_flow_session,
        infer_evolution_usage_feature=_infer_evolution_usage_feature,
    )
    _queue_incoming_webhook = webhook_runtime.queue_incoming_webhook

    health_payload_builder = HealthPayloadBuilder(
        settings=settings,
        access_control=access_control,
        security_monitor=security_monitor,
        dclientes_query_service=dclientes_query_service,
        inadimplencia_query_service=inadimplencia_query_service,
        comodatos_query_service=comodatos_query_service,
        giro_query_service=giro_query_service,
        evolution_client=evolution_client,
        meta_cloud_client=meta_cloud_client,
        webhook_runtime=webhook_runtime,
        daily_route_broadcast_lock=daily_route_broadcast_lock,
        daily_route_broadcast_status=daily_route_broadcast_status,
    )
    _build_detailed_health_payload = health_payload_builder.build

    def _after_critica_operacao_auto_import(reason: str) -> dict[str, Any]:
        refresh_result = critica_operacao_admin_service.refresh_latest_view()
        _clear_critica_runtime_cache()
        prebuild_result = _queue_critica_pdf_prebuild(str(reason or "030111_BOT"))
        return {
            "refresh_critica_operacao_view": _serialize_admin_import_value(refresh_result),
            "prebuild_critica_pdf_reports": _serialize_admin_import_value(prebuild_result),
        }


    register_routes(app, deps=_build_route_dependencies(locals()))

    return None


def _build_route_dependencies(runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "settings": runtime["settings"],
        "meta_cloud_client": runtime["meta_cloud_client"],
        "access_control": runtime["access_control"],
        "dclientes_query_service": runtime["dclientes_query_service"],
        "inadimplencia_query_service": runtime["inadimplencia_query_service"],
        "comodatos_query_service": runtime["comodatos_query_service"],
        "build_detailed_health_payload": runtime["_build_detailed_health_payload"],
        "access_call": runtime["_access_call"],
        "require_admin_api_auth": runtime["_require_admin_api_auth"],
        "record_security_event": runtime["_record_security_event"],
        "require_admin_panel_auth": runtime["_require_admin_panel_auth"],
        "require_admin_panel_feature": runtime["_require_admin_panel_feature"],
        "require_admin_panel_import_dataset": runtime["_require_admin_panel_import_dataset"],
        "require_api_auth": runtime["_require_api_auth"],
        "require_admin_scope_for_number_routes": runtime["_require_admin_scope_for_number_routes"],
        "decision_has_unrestricted_lookup_access": runtime["_decision_has_unrestricted_lookup_access"],
        "admin_panel_context_from_session_cookie": runtime["_admin_panel_context_from_session_cookie"],
        "admin_panel_context_from_token": runtime["_admin_panel_context_from_token"],
        "admin_panel_context_from_credentials": runtime["_admin_panel_context_from_credentials"],
        "panel_context_can_access_feature": runtime["_panel_context_can_access_feature"],
        "admin_panel_user_service": runtime["admin_panel_user_service"],
        "record_admin_panel_action": runtime["_record_admin_panel_action"],
        "check_admin_panel_login_rate_limit": runtime["_check_admin_panel_login_rate_limit"],
        "record_admin_panel_login_failure": runtime["_record_admin_panel_login_failure"],
        "clear_admin_panel_login_failures": runtime["_clear_admin_panel_login_failures"],
        "set_admin_panel_session_cookie": runtime["_set_admin_panel_session_cookie"],
        "panel_context_mode": runtime["_panel_context_mode"],
        "admin_panel_session_cookie": runtime["ADMIN_PANEL_SESSION_COOKIE"],
        "admin_panel_session_ttl_seconds": runtime["ADMIN_PANEL_SESSION_TTL_SECONDS"],
        "load_admin_login_html": runtime["_load_admin_login_html"],
        "load_admin_change_password_html": runtime["_load_admin_change_password_html"],
        "load_admin_import_panel_html": runtime["_load_admin_import_panel_html"],
        "list_admin_import_status": runtime["_list_admin_import_status"],
        "filter_admin_import_status_for_context": runtime["_filter_admin_import_status_for_context"],
        "list_admin_import_history": runtime["_list_admin_import_history"],
        "filter_admin_import_history_for_context": runtime["_filter_admin_import_history_for_context"],
        "run_admin_import_validation": runtime["_run_admin_import_validation"],
        "queue_admin_import": runtime["_queue_admin_import"],
        "store_admin_import_uploads": runtime["_store_admin_import_uploads"],
        "build_admin_giro_recolha_dashboard": runtime["_build_admin_giro_recolha_dashboard"],
        "build_admin_giro_recolha_filter_options": runtime["_build_admin_giro_recolha_filter_options"],
        "build_admin_giro_recolha_routes": runtime["_build_admin_giro_recolha_routes"],
        "parse_admin_critica_date": runtime["_parse_admin_critica_date"],
        "build_admin_critica_dashboard": runtime["_build_admin_critica_dashboard"],
        "build_admin_critica_sector_pdf_response": runtime["_build_admin_critica_sector_pdf_response"],
        "list_admin_recolhas": runtime["_list_admin_recolhas"],
        "update_admin_recolhas_bulk": runtime["_update_admin_recolhas_bulk"],
        "import_admin_recolhas_csv": runtime["_import_admin_recolhas_csv"],
        "export_admin_recolhas_csv": runtime["_export_admin_recolhas_csv"],
        "update_admin_recolha": runtime["_update_admin_recolha"],
        "delete_admin_recolha": runtime["_delete_admin_recolha"],
        "list_financeiro_caixa": runtime["_list_financeiro_caixa"],
        "upsert_financeiro_mapa": runtime["_upsert_financeiro_mapa"],
        "export_financeiro_caixa_pdf": runtime["_export_financeiro_caixa_pdf"],
        "sync_financeiro_fechamento_promax": runtime["_sync_financeiro_fechamento_promax"],
        "resolve_financeiro_fechamento_km": runtime["_resolve_financeiro_fechamento_km"],
        "sync_conferencia_fechamento_promax": runtime["_sync_conferencia_fechamento_promax"],
        "list_conferencia_mapas": runtime["_list_conferencia_mapas"],
        "list_conferencia_garrafeiras": runtime["_list_conferencia_garrafeiras"],
        "create_conferencia_mapa": runtime["_create_conferencia_mapa"],
        "get_conferencia_mapa": runtime["_get_conferencia_mapa"],
        "save_conferencia_counts": runtime["_save_conferencia_counts"],
        "search_conferencia_products": runtime["_search_conferencia_products"],
        "list_admin_protestos": runtime["_list_admin_protestos"],
        "update_admin_protesto": runtime["_update_admin_protesto"],
        "upload_admin_protesto_document": runtime["_upload_admin_protesto_document"],
        "download_admin_protesto_document": runtime["_download_admin_protesto_document"],
        "enqueue_promax_job": runtime["promax_jobs_service"].enqueue_job,
        "delete_financeiro_mapa": runtime["_delete_financeiro_mapa"],
        "preview_payip_batch": runtime["_preview_payip_batch"],
        "queue_payip_batch": runtime["_queue_payip_batch"],
        "snapshot_payip_batch": runtime["_snapshot_payip_batch"],
        "export_payip_batch_csv": runtime["_export_payip_batch_csv"],
        "payip_batch_pdf_bytes": runtime["_payip_batch_pdf_bytes"],
        "validate_payip_promax_import": runtime["_validate_payip_promax_import"],
        "create_payip_promax_import_clients": runtime["_create_payip_promax_import_clients"],
        "run_payip_promax_import": runtime["_run_payip_promax_import"],
        "list_payip_generated_batches": runtime["_list_payip_generated_batches"],
        "payip_generated_batch_process": runtime["_payip_generated_batch_process"],
        "payip_generated_batch_file_bytes": runtime["_payip_generated_batch_file_bytes"],
        "list_admin_evolution_usage": runtime["_list_admin_evolution_usage"],
        "build_evolution_usage_avg_report_csv": runtime["_build_evolution_usage_avg_report_csv"],
        "build_evolution_function_usage_report_csv": runtime["_build_evolution_function_usage_report_csv"],
        "list_admin_panel_audit_actions": runtime["_list_admin_panel_audit_actions"],
        "build_admin_panel_audit_report_csv": runtime["_build_admin_panel_audit_report_csv"],
        "list_admin_broadcast_options": runtime["_list_admin_broadcast_options"],
        "snapshot_admin_broadcast_state": runtime["_snapshot_admin_broadcast_state"],
        "build_admin_broadcast_payload": runtime["_build_admin_broadcast_payload"],
        "queue_admin_broadcast": runtime["_queue_admin_broadcast"],
        "promax_jobs_service": runtime["promax_jobs_service"],
        "promax_catalog": runtime["PROMAX_CATALOG"],
        "boletos_pdf_import_services": runtime["services"].boletos_pdf_import_services,
        "estoque_020304_import_services": runtime["services"].estoque_020304_import_services,
        "relatorio_031120_import_services": runtime["services"].relatorio_031120_import_services,
        "relatorio_03114902_import_service": runtime["services"].relatorio_03114902_import_service,
        "inadimplencia_import_service": runtime["services"].inadimplencia_import_service,
        "comodatos_import_service": runtime["services"].comodatos_import_service,
        "dclientes_import_service": runtime["services"].dclientes_import_service,
        "dmateriais_import_service": runtime["services"].dmateriais_import_service,
        "documentacao_pendente_import_service": runtime["services"].documentacao_pendente_import_service,
        "critica_operacao_import_services": runtime["services"].critica_operacao_import_services,
        "after_critica_operacao_import": runtime["_after_critica_operacao_auto_import"],
        "require_webhook_token": runtime["_require_webhook_token"],
        "require_meta_cloud_signature": runtime["_require_meta_cloud_signature"],
        "queue_incoming_webhook": runtime["_queue_incoming_webhook"],
    }
