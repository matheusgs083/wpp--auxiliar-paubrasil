from __future__ import annotations

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
from bot_api.services.admin_import_config import ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS, build_admin_import_datasets
from bot_api.services.admin_templates import AdminTemplateLoader
from bot_api.services.app_lifecycle import register_app_lifecycle
from bot_api.services.customer_lookup_flow import FILIAL_LABELS
from bot_api.services.admin_panel_session_service import AdminPanelSessionService
from bot_api.services.admin_payip_batch_service import AdminPayipBatchService
from bot_api.services.admin_recolhas_service import AdminRecolhasService
from bot_api.services.critica_rn_query_service import CriticaPdfCurrentImportRequiredError
from bot_api.services.health_service import HealthPayloadBuilder
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
    dclientes_query_service = services.dclientes_query_service
    clientes_score_query_service = services.clientes_score_query_service
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
    dcondicoes_import_service = services.dcondicoes_import_service
    dprodutos_import_service = services.dprodutos_import_service
    produto_cestas_import_service = services.produto_cestas_import_service
    dclientes_import_service = services.dclientes_import_service
    clientes_score_import_service = services.clientes_score_import_service
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
    lookup_flow = services.lookup_flow
    webhook_executor = ThreadPoolExecutor(
        max_workers=settings.webhook_worker_threads,
        thread_name_prefix="webhook-worker",
    )

    PROJECT_ROOT = project_root
    ADMIN_IMPORT_PANEL_TEMPLATE = PROJECT_ROOT / "templates" / "admin_import_panel.html"
    ADMIN_LOGIN_TEMPLATE = PROJECT_ROOT / "templates" / "admin_login.html"
    ADMIN_IMPORT_RUNTIME_ROOT = (
        Path("/tmp/bot_api_admin_imports") if Path("/tmp").exists() else PROJECT_ROOT / "exports" / "admin_import_uploads"
    )
    ADMIN_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
    ADMIN_PANEL_SESSION_COOKIE = "bot_admin_session"
    ADMIN_PANEL_SESSION_TTL_SECONDS = 12 * 60 * 60
    ADMIN_PANEL_LOGIN_WINDOW_SECONDS = 5 * 60
    ADMIN_PANEL_LOGIN_MAX_FAILURES = 10
    admin_panel_session_service = AdminPanelSessionService(
        admin_api_token=settings.admin_api_token,
        verify_token=settings.verify_token,
        api_auth_tokens=settings.api_auth_tokens,
        finance_panel_tokens=settings.finance_panel_tokens,
        critica_panel_tokens=settings.critica_panel_tokens,
        session_cookie_name=ADMIN_PANEL_SESSION_COOKIE,
        session_ttl_seconds=ADMIN_PANEL_SESSION_TTL_SECONDS,
        login_window_seconds=ADMIN_PANEL_LOGIN_WINDOW_SECONDS,
        login_max_failures=ADMIN_PANEL_LOGIN_MAX_FAILURES,
    )


    ADMIN_IMPORT_DATASETS = build_admin_import_datasets(
        project_root=PROJECT_ROOT,
        services=services,
        filial_labels=FILIAL_LABELS,
    )
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
        critica_rn_import_service=critica_rn_import_service,
        critica_operacao_admin_service=critica_operacao_admin_service,
        critica_rn_query_service=critica_rn_query_service,
        critica_rn_pdf_prebuild_service=critica_rn_pdf_prebuild_service,
        critica_pdf_prebuild_executor=critica_pdf_prebuild_executor,
        critica_pdf_prebuild_lock=critica_pdf_prebuild_lock,
        critica_pdf_prebuild_state=critica_pdf_prebuild_state,
        _panel_context_allowed_import_datasets=_panel_context_allowed_import_datasets,
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
        filial_labels=FILIAL_LABELS,
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
        panel_context_has_all_filiais=_panel_context_has_all_filiais,
        logger=logger,
    )
    _preview_payip_batch = admin_payip_batch_service.preview
    _queue_payip_batch = admin_payip_batch_service.queue
    _snapshot_payip_batch = admin_payip_batch_service.snapshot
    _export_payip_batch_csv = admin_payip_batch_service.export_csv
    _payip_batch_pdf_bytes = admin_payip_batch_service.pdf_bytes


    admin_template_loader = AdminTemplateLoader(
        import_panel_template=ADMIN_IMPORT_PANEL_TEMPLATE,
        login_template=ADMIN_LOGIN_TEMPLATE,
        api_auth_enabled=settings.api_auth_enabled,
    )
    _load_admin_import_panel_html = admin_template_loader.load_import_panel_html
    _load_admin_login_html = admin_template_loader.load_login_html

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
        critica_pdf_prebuild_executor=critica_pdf_prebuild_executor,
        admin_broadcast_executor=admin_broadcast_executor,
        admin_payip_batch_service=admin_payip_batch_service,
        webhook_executor=webhook_executor,
        close_connection_pools=close_all_connection_pools,
    )

    health_payload_builder = HealthPayloadBuilder(
        settings=settings,
        access_control=access_control,
        security_monitor=security_monitor,
        dclientes_query_service=dclientes_query_service,
        clientes_score_query_service=clientes_score_query_service,
        inadimplencia_query_service=inadimplencia_query_service,
        comodatos_query_service=comodatos_query_service,
        giro_query_service=giro_query_service,
        meta_cloud_client=meta_cloud_client,
        daily_route_broadcast_lock=daily_route_broadcast_lock,
        daily_route_broadcast_status=daily_route_broadcast_status,
    )
    _build_detailed_health_payload = health_payload_builder.build

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


    register_routes(
        app,
        deps={
            "settings": settings,
            "meta_cloud_client": meta_cloud_client,
            "access_control": access_control,
            "dclientes_query_service": dclientes_query_service,
            "inadimplencia_query_service": inadimplencia_query_service,
            "comodatos_query_service": comodatos_query_service,
            "build_detailed_health_payload": _build_detailed_health_payload,
            "access_call": _access_call,
            "require_admin_api_auth": _require_admin_api_auth,
            "record_security_event": _record_security_event,
            "require_admin_panel_auth": _require_admin_panel_auth,
            "require_admin_panel_feature": _require_admin_panel_feature,
            "require_admin_panel_import_dataset": _require_admin_panel_import_dataset,
            "require_api_auth": _require_api_auth,
            "require_admin_scope_for_number_routes": _require_admin_scope_for_number_routes,
            "decision_has_unrestricted_lookup_access": _decision_has_unrestricted_lookup_access,
            "admin_panel_context_from_session_cookie": _admin_panel_context_from_session_cookie,
            "admin_panel_context_from_token": _admin_panel_context_from_token,
            "check_admin_panel_login_rate_limit": _check_admin_panel_login_rate_limit,
            "record_admin_panel_login_failure": _record_admin_panel_login_failure,
            "clear_admin_panel_login_failures": _clear_admin_panel_login_failures,
            "set_admin_panel_session_cookie": _set_admin_panel_session_cookie,
            "panel_context_mode": _panel_context_mode,
            "admin_panel_session_cookie": ADMIN_PANEL_SESSION_COOKIE,
            "admin_panel_session_ttl_seconds": ADMIN_PANEL_SESSION_TTL_SECONDS,
            "load_admin_login_html": _load_admin_login_html,
            "load_admin_import_panel_html": _load_admin_import_panel_html,
            "list_admin_import_status": _list_admin_import_status,
            "filter_admin_import_status_for_context": _filter_admin_import_status_for_context,
            "list_admin_import_history": _list_admin_import_history,
            "filter_admin_import_history_for_context": _filter_admin_import_history_for_context,
            "run_admin_import_validation": _run_admin_import_validation,
            "queue_admin_import": _queue_admin_import,
            "store_admin_import_uploads": _store_admin_import_uploads,
            "build_admin_giro_recolha_dashboard": _build_admin_giro_recolha_dashboard,
            "build_admin_giro_recolha_filter_options": _build_admin_giro_recolha_filter_options,
            "build_admin_giro_recolha_routes": _build_admin_giro_recolha_routes,
            "parse_admin_critica_date": _parse_admin_critica_date,
            "build_admin_critica_dashboard": _build_admin_critica_dashboard,
            "build_admin_critica_sector_pdf_response": _build_admin_critica_sector_pdf_response,
            "list_admin_recolhas": _list_admin_recolhas,
            "update_admin_recolhas_bulk": _update_admin_recolhas_bulk,
            "import_admin_recolhas_csv": _import_admin_recolhas_csv,
            "export_admin_recolhas_csv": _export_admin_recolhas_csv,
            "update_admin_recolha": _update_admin_recolha,
            "delete_admin_recolha": _delete_admin_recolha,
            "preview_payip_batch": _preview_payip_batch,
            "queue_payip_batch": _queue_payip_batch,
            "snapshot_payip_batch": _snapshot_payip_batch,
            "export_payip_batch_csv": _export_payip_batch_csv,
            "payip_batch_pdf_bytes": _payip_batch_pdf_bytes,
            "list_admin_evolution_usage": _list_admin_evolution_usage,
            "build_evolution_usage_avg_report_csv": _build_evolution_usage_avg_report_csv,
            "build_evolution_function_usage_report_csv": _build_evolution_function_usage_report_csv,
            "list_admin_broadcast_options": _list_admin_broadcast_options,
            "snapshot_admin_broadcast_state": _snapshot_admin_broadcast_state,
            "build_admin_broadcast_payload": _build_admin_broadcast_payload,
            "queue_admin_broadcast": _queue_admin_broadcast,
            "require_webhook_token": _require_webhook_token,
            "require_meta_cloud_signature": _require_meta_cloud_signature,
            "queue_incoming_webhook": _queue_incoming_webhook,
        },
    )

    return None
