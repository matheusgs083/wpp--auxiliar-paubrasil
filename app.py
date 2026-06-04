from __future__ import annotations

import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import time
import unicodedata
from uuid import uuid4
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import shutil
from threading import Event, Lock, RLock, Thread
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

from bot_api.config import get_settings
from bot_api.commercial_scope import normalize_numeric_code, split_scope_pair
from bot_api.db import close_all_connection_pools
from bot_api.integrations.evolution_client import EvolutionClient, EvolutionConfig, extract_incoming_message
from bot_api.integrations.meta_cloud_client import MetaCloudClient, MetaCloudConfig
from bot_api.integrations.meta_cloud_client import (
    extract_incoming_message as extract_meta_cloud_incoming_message,
)
from bot_api.integrations.meta_cloud_client import verify_webhook_token as verify_meta_cloud_webhook_token
from bot_api.models import IncomingMessage
from bot_api.security.access_control import AccessControl
from bot_api.security.security_monitor import SecurityMonitor
from bot_api.services.customer_lookup_flow import CustomerLookupFlow, FILIAL_LABELS
from bot_api.services.admin_import_job_service import AdminImportJobService, AdminImportLockBusy
from bot_api.services.comodatos_import_service import ComodatosImportService
from bot_api.services.comodatos_query_service import ComodatosQueryService
from bot_api.services.critica_operacao_import_service import CriticaOperacaoImportService
from bot_api.services.critica_rn_import_service import CriticaRnImportService
from bot_api.services.critica_rn_query_service import CriticaRnQueryService
from bot_api.services.dclientes_import_service import DClientesImportService
from bot_api.services.dclientes_query_service import DClientesQueryService
from bot_api.services.doperacoes_import_service import DOperacoesImportService
from bot_api.services.dprecos_import_service import DPrecosImportService
from bot_api.services.dprodutos_import_service import DProdutosImportService
from bot_api.services.dsetores_import_service import DSetoresImportService
from bot_api.services.giro_import_service import GiroImportService
from bot_api.services.giro_query_service import GiroQueryService
from bot_api.services.inadimplencia_import_service import InadimplenciaImportService
from bot_api.services.inadimplencia_query_service import InadimplenciaQueryService
from bot_api.services.documentacao_pendente_import_service import DocumentacaoPendenteImportService
from bot_api.services.documentacao_pendente_query_service import DocumentacaoPendenteQueryService
from bot_api.services.payip_payments_service import build_payip_payments_service
from bot_api.services.prazo_limite_import_service import PrazoLimiteImportService
from bot_api.services.prazo_limite_query_service import PrazoLimiteQueryService
from bot_api.services.produto_cestas_import_service import ProdutoCestasImportService
from bot_api.services.recolha_request_service import RecolhaRequestService

logger = logging.getLogger(__name__)
settings = get_settings()
admin_import_job_service = AdminImportJobService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
dclientes_query_service = DClientesQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
inadimplencia_query_service = InadimplenciaQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
comodatos_query_service = ComodatosQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
giro_query_service = GiroQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
critica_rn_query_service = CriticaRnQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
critica_rn_pdf_prebuild_service = CriticaRnQueryService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
documentacao_pendente_query_service = DocumentacaoPendenteQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
prazo_limite_query_service = PrazoLimiteQueryService(
    database_url=settings.reports_runtime_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
dsetores_import_service = DSetoresImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
dprecos_import_service = DPrecosImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
doperacoes_import_service = DOperacoesImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
dprodutos_import_service = DProdutosImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
produto_cestas_import_service = ProdutoCestasImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
dclientes_import_service = DClientesImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
inadimplencia_import_service = InadimplenciaImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
comodatos_import_service = ComodatosImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
giro_import_service = GiroImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
critica_rn_import_service = CriticaRnImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
critica_operacao_import_services = {
    filial_code: CriticaOperacaoImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        dataset_name=f"critica_op_{filial_code}",
        expected_filial=filial_code,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    for filial_code in sorted(FILIAL_LABELS, key=int)
}
critica_operacao_admin_service = critica_operacao_import_services[sorted(FILIAL_LABELS, key=int)[0]]
documentacao_pendente_import_service = DocumentacaoPendenteImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
prazo_limite_import_service = PrazoLimiteImportService(
    database_url=settings.reports_database_url,
    schema=settings.reports_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
recolha_request_service = RecolhaRequestService(
    Path(__file__).resolve().parent / "exports" / "recolhas" / "solicitacoes_recolha.csv"
)
evolution_client = EvolutionClient(
    EvolutionConfig(
        base_url=settings.evolution_base_url,
        api_key=settings.evolution_api_key,
        instance=settings.evolution_instance,
        send_path=settings.evolution_send_path,
        list_path=settings.evolution_list_path,
        buttons_path=settings.evolution_buttons_path,
        media_path=settings.evolution_media_path,
        timeout_seconds=settings.evolution_timeout_seconds,
    )
)
meta_cloud_client = MetaCloudClient(
    MetaCloudConfig(
        enabled=settings.meta_cloud_enabled,
        api_version=settings.meta_cloud_api_version,
        phone_number_id=settings.meta_cloud_phone_number_id,
        access_token=settings.meta_cloud_access_token,
        verify_token=settings.meta_cloud_verify_token,
    )
)
access_control = AccessControl(
    enabled=settings.access_control_enabled,
    database_url=settings.access_database_url,
    schema=settings.access_db_schema,
    public_enabled=settings.access_public_enabled,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
)
security_monitor = SecurityMonitor(
    enabled=settings.security_audit_enabled,
    database_url=settings.access_database_url,
    schema=settings.access_db_schema,
    connect_timeout_seconds=settings.access_database_timeout_seconds,
    default_cooldown_minutes=settings.denied_reply_cooldown_minutes,
    unregistered_cooldown_minutes=settings.denied_unregistered_reply_cooldown_minutes,
)
payip_payments_service = None
if (
    settings.payip_base_url
    and settings.payip_client_id
    and settings.payip_username
    and settings.payip_password
    and (settings.payip_company_id or settings.payip_company_ids)
):
    try:
        payip_payments_service = build_payip_payments_service(settings)
    except RuntimeError as exc:
        logger.warning("PayIP nao inicializada: %s", exc)
lookup_flow = CustomerLookupFlow(
    query_service=dclientes_query_service,
    inadimplencia_service=inadimplencia_query_service,
    comodatos_service=comodatos_query_service,
    giro_service=giro_query_service,
    critica_rn_service=critica_rn_query_service,
    documentacao_pendente_service=documentacao_pendente_query_service,
    prazo_limite_service=prazo_limite_query_service,
    payip_payments_service=payip_payments_service,
    recolha_request_service=recolha_request_service,
    access_control=access_control,
)
webhook_executor = ThreadPoolExecutor(
    max_workers=settings.webhook_worker_threads,
    thread_name_prefix="webhook-worker",
)

app = FastAPI(
    title="Customer Lookup Bot API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
PROJECT_ROOT = Path(__file__).resolve().parent
ADMIN_IMPORT_PANEL_TEMPLATE = PROJECT_ROOT / "templates" / "admin_import_panel.html"
ADMIN_IMPORT_RUNTIME_ROOT = (
    Path("/tmp/bot_api_admin_imports") if Path("/tmp").exists() else PROJECT_ROOT / "exports" / "admin_import_uploads"
)
ADMIN_UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
ADMIN_BROADCAST_SEND_DELAY_SECONDS = 1.0
ADMIN_PANEL_SESSION_COOKIE = "bot_admin_session"
ADMIN_PANEL_SESSION_TTL_SECONDS = 12 * 60 * 60
ADMIN_PANEL_LOGIN_WINDOW_SECONDS = 5 * 60
ADMIN_PANEL_LOGIN_MAX_FAILURES = 10
admin_panel_login_lock = Lock()
admin_panel_login_failures: dict[str, list[float]] = {}


@app.middleware("http")
async def add_security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


ADMIN_IMPORT_DATASETS: dict[str, dict[str, Any]] = {
    "dsetores": {
        "label": "dSetores",
        "default_path": PROJECT_ROOT / "data" / "dSetores" / "dSetores.csv",
        "service": dsetores_import_service,
        "upload_mode": "single",
        "accept_extensions": ".csv",
        "validate_method": "validate_csv",
        "summarize_method": "summarize_csv",
        "import_method": "import_csv",
    },
    "dprecos": {
        "label": "DPrecos",
        "default_path": PROJECT_ROOT / "data" / "dPrecos" / "DPrecos.xlsx",
        "service": dprecos_import_service,
        "upload_mode": "single",
        "accept_extensions": ".xlsx,.xlsm,.csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "doperacoes": {
        "label": "dOperacoes",
        "default_path": PROJECT_ROOT / "data" / "dOperacoes" / "dOperacoes.csv",
        "service": doperacoes_import_service,
        "upload_mode": "single",
        "accept_extensions": ".csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "dprodutos": {
        "label": "dProdutos",
        "default_path": PROJECT_ROOT / "data" / "dProdutos" / "01.11.CSV",
        "allow_default_source": False,
        "service": dprodutos_import_service,
        "upload_mode": "single",
        "accept_extensions": ".csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "produto_cestas": {
        "label": "Cesta de Produtos",
        "default_path": PROJECT_ROOT / "data" / "dProdutos" / "Cesta de Produtos.xlsx",
        "allow_default_source": False,
        "service": produto_cestas_import_service,
        "upload_mode": "single",
        "accept_extensions": ".xlsx,.xlsm,.csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "dclientes": {
        "label": "dClientes",
        "default_path": PROJECT_ROOT / "data" / "dClientes" / "dClientes.csv",
        "service": dclientes_import_service,
        "upload_mode": "single",
        "accept_extensions": ".csv",
        "validate_method": "validate_csv",
        "summarize_method": "summarize_csv",
        "import_method": "import_csv",
    },
    "inadimplencia": {
        "label": "Inadimplencia",
        "default_path": PROJECT_ROOT / "data" / "Inadimplencia",
        "allow_default_source": False,
        "service": inadimplencia_import_service,
        "upload_mode": "multiple",
        "accept_extensions": ".csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "comodatos": {
        "label": "Comodatos",
        "default_path": PROJECT_ROOT / "data" / "Comodatos",
        "service": comodatos_import_service,
        "upload_mode": "multiple",
        "accept_extensions": ".csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "giro": {
        "label": "Giro de Vasilhame",
        "default_path": PROJECT_ROOT / "data" / "Giro" / "giro.xlsx",
        "service": giro_import_service,
        "upload_mode": "single",
        "accept_extensions": ".xlsx,.xlsm,.xls",
        "validate_method": "validate_workbook",
        "summarize_method": "summarize_workbook",
        "import_method": "import_workbook",
    },
    **{
        f"critica_op_{filial_code}": {
            "label": f"Critica Operacao {filial_code} - {FILIAL_LABELS[filial_code]}",
            "default_path": PROJECT_ROOT / "data" / "Critica" / f"critica_operacao_{filial_code}.csv",
            "allow_default_source": False,
            "service": critica_operacao_import_services[filial_code],
            "upload_mode": "single",
            "accept_extensions": ".csv",
            "validate_method": "validate_source",
            "summarize_method": "summarize_source",
            "import_method": "import_source",
        }
        for filial_code in sorted(FILIAL_LABELS, key=int)
    },
    "critica_rn": {
        "label": "Critica RN",
        "default_path": PROJECT_ROOT / "data" / "CriticaRN" / "critica_rn.xlsx",
        "allow_default_source": False,
        "service": critica_rn_import_service,
        "upload_mode": "single",
        "accept_extensions": ".xlsx,.xlsm,.csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "documentacao_pendente": {
        "label": "Documentacao Pendente",
        "default_path": PROJECT_ROOT / "data" / "DocumentacaoPendente" / "documentacao_pendente.csv",
        "service": documentacao_pendente_import_service,
        "upload_mode": "single",
        "accept_extensions": ".csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
    "prazo_limite": {
        "label": "Prazo e Limite",
        "default_path": PROJECT_ROOT / "data" / "PrazoLimite" / "prazo_limite.xlsx",
        "service": prazo_limite_import_service,
        "upload_mode": "single",
        "accept_extensions": ".xlsx,.xlsm,.xls,.csv",
        "validate_method": "validate_source",
        "summarize_method": "summarize_source",
        "import_method": "import_source",
    },
}
ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS = {"critica_rn", "dclientes", "doperacoes", "dprecos", "dsetores"}
ADMIN_IMPORT_MAX_WORKERS = 3
ADMIN_IMPORT_HISTORY_RETENTION_DAYS = 3
admin_import_executor = ThreadPoolExecutor(max_workers=ADMIN_IMPORT_MAX_WORKERS, thread_name_prefix="admin-import")
admin_import_lock = Lock()
admin_import_maintenance_lock = Lock()
admin_import_state: dict[str, Any] = {
    "running": False,
    "current_job_id": "",
    "current_dataset": "",
    "started_at": "",
    "reference_date": "",
    "current_jobs": {},
    "last_job": {},
}
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
ADMIN_BROADCAST_ACTIONS: dict[str, dict[str, Any]] = {
    "rota_dia": {
        "label": "Rota do dia",
        "description": "Envia os clientes da rota do dia para cada usuario.",
        "shortcut": "rota hoje",
        "shortcut_template": "rota {day}",
        "area": "cliente",
        "supports_day": True,
    },
    "inad_hoje": {
        "label": "Inad por dia",
        "description": "Executa o atalho de risco/cobranca da rota escolhida para cada usuario.",
        "shortcut": "inad hoje",
        "shortcut_template": "inad {day}",
        "area": "inadimplencia",
        "supports_day": True,
    },
    "giro_hoje": {
        "label": "Giro por dia",
        "description": "Executa o atalho de giro da rota escolhida para cada usuario.",
        "shortcut": "giro hoje",
        "shortcut_template": "giro {day}",
        "area": "cliente",
        "supports_day": True,
    },
    "inad_base": {
        "label": "Inad da base",
        "description": "Executa o atalho de inadimplentes da base/carteira para cada usuario.",
        "shortcut": "inadimplentes da base",
        "area": "inadimplencia",
        "supports_day": False,
    },
    "giro_zero_base": {
        "label": "Giro zero da base",
        "description": "Executa o atalho de clientes com giro zero da base/carteira para cada usuario.",
        "shortcut": "giro zero da base",
        "area": "cliente",
        "supports_day": False,
    },
}
ADMIN_BROADCAST_DAY_OPTIONS: dict[str, dict[str, str]] = {
    "hoje": {"label": "Hoje", "token": "hoje"},
    "segunda": {"label": "Segunda", "token": "segunda"},
    "terca": {"label": "Terca", "token": "terca"},
    "quarta": {"label": "Quarta", "token": "quarta"},
    "quinta": {"label": "Quinta", "token": "quinta"},
    "sexta": {"label": "Sexta", "token": "sexta"},
    "sabado": {"label": "Sabado", "token": "sabado"},
    "domingo": {"label": "Domingo", "token": "domingo"},
}
ADMIN_BROADCAST_TARGET_MODES: dict[str, dict[str, str]] = {
    "filial": {"label": "Todos da filial"},
    "specific": {"label": "Numero especifico"},
}
ADMIN_BROADCAST_AUDIENCES: dict[str, dict[str, str]] = {
    "vendedor": {
        "label": "Vendedores (RN)",
        "role": "vendedor",
        "role_label": "RN",
        "empty_message": "Nenhum vendedor/RN ativo encontrado para essa filial.",
    },
    "gerente_vendas": {
        "label": "GVs",
        "role": "gerente_vendas",
        "role_label": "GV",
        "empty_message": "Nenhum GV ativo encontrado para essa filial.",
    },
}
admin_broadcast_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="admin-broadcast")
admin_broadcast_lock = Lock()
admin_broadcast_state: dict[str, Any] = {
    "running": False,
    "current_job_id": "",
    "current_filial": "",
    "current_action": "",
    "current_day": "",
    "current_target_mode": "",
    "current_target_audience": "",
    "current_shortcut": "",
    "started_at": "",
    "total": 0,
    "sent": 0,
    "failed": 0,
    "skipped": 0,
    "last_job": {},
}
daily_route_broadcast_lock = RLock()
daily_route_broadcast_stop_event = Event()
daily_route_broadcast_thread: Thread | None = None
daily_route_broadcast_status: dict[str, Any] = {
    "enabled": bool(settings.daily_route_broadcast_enabled),
    "running": False,
    "last_checked_at": "",
    "last_run_date": "",
    "last_run": {},
    "last_error": "",
}

class DeniedReplyThrottle:
    def __init__(
        self,
        default_cooldown_minutes: int,
        unregistered_cooldown_minutes: int,
    ) -> None:
        self.default_cooldown = timedelta(minutes=max(int(default_cooldown_minutes), 1))
        self.unregistered_cooldown = timedelta(minutes=max(int(unregistered_cooldown_minutes), 1))
        self._cleanup_window = max(self.default_cooldown, self.unregistered_cooldown) * 2
        self._last_reply_at: dict[str, datetime] = {}
        self._lock = Lock()

    def should_send(self, number: str, reason: str) -> bool:
        normalized_number = str(number or "").strip()
        if not normalized_number:
            return False

        now = datetime.now(timezone.utc)
        cooldown = self.unregistered_cooldown if reason == "number_not_registered" else self.default_cooldown
        with self._lock:
            self._cleanup_locked(now)
            last_reply_at = self._last_reply_at.get(normalized_number)
            if last_reply_at is not None and now - last_reply_at < cooldown:
                return False
            self._last_reply_at[normalized_number] = now
            return True

    def cooldown_minutes_for(self, reason: str) -> int:
        cooldown = self.unregistered_cooldown if reason == "number_not_registered" else self.default_cooldown
        return max(1, int(cooldown.total_seconds() // 60))

    def _cleanup_locked(self, now: datetime) -> None:
        expired_numbers = [
            number
            for number, last_reply_at in self._last_reply_at.items()
            if now - last_reply_at >= self._cleanup_window
        ]
        for number in expired_numbers:
            self._last_reply_at.pop(number, None)


denied_reply_throttle = DeniedReplyThrottle(
    default_cooldown_minutes=settings.denied_reply_cooldown_minutes,
    unregistered_cooldown_minutes=settings.denied_unregistered_reply_cooldown_minutes,
)


class AccessUserUpsertRequest(BaseModel):
    phone_number: str
    name: str | None = None
    is_active: bool = True
    roles: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    gv_vdes: list[str] = Field(default_factory=list)


class AccessUserBulkUpsertRequest(BaseModel):
    users: list[AccessUserUpsertRequest] = Field(default_factory=list)
    continue_on_error: bool = True


class AccessRoleUpsertRequest(BaseModel):
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)


class AdminImportActionRequest(BaseModel):
    dataset: str
    reference_date: str | None = None


class AdminPanelLoginRequest(BaseModel):
    token: str


class AdminBroadcastRequest(BaseModel):
    filial: str
    action: str
    day: str = "hoje"
    target_mode: str = "filial"
    target_audience: str = "vendedor"
    target_number: str = ""
    selected_numbers: list[str] = Field(default_factory=list)


class AdminRecolhaUpdateRequest(BaseModel):
    lancado_faturista: str | None = None
    motorista_faturista: str | None = None
    placa_faturista: str | None = None
    mapa_faturista: str | None = None
    status_caixa_noturno: str | None = None
    motivo_caixa_noturno: str | None = None


class AdminRecolhaBulkUpdateRequest(AdminRecolhaUpdateRequest):
    ids: list[str] = Field(default_factory=list)


def _base64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _admin_panel_session_secret() -> bytes:
    seeds = [settings.admin_api_token.strip(), settings.verify_token.strip(), *(settings.api_auth_tokens or ())]
    secret_seed = next((seed for seed in seeds if seed), "")
    if not secret_seed:
        raise HTTPException(status_code=503, detail="Sessao do painel indisponivel.")
    return hashlib.sha256(f"bot-admin-panel-session-v1:{secret_seed}".encode("utf-8")).digest()


def _admin_panel_context_from_token(token: str | None) -> dict[str, Any] | None:
    provided_token = str(token or "").strip()
    if not provided_token:
        return None
    if _admin_token_matches(provided_token):
        return {"mode": "admin", "is_admin": True, "filiais": ()}
    finance_filiais = _finance_panel_token_filiais(provided_token)
    if finance_filiais:
        return {"mode": "financeiro", "is_admin": False, "filiais": finance_filiais}
    return None


def _serialize_admin_panel_session(context: dict[str, Any]) -> str:
    now = int(time.time())
    payload = {
        "mode": str(context.get("mode") or "admin"),
        "is_admin": bool(context.get("is_admin")),
        "filiais": [str(filial).strip() for filial in context.get("filiais", ()) if str(filial).strip()],
        "iat": now,
        "exp": now + ADMIN_PANEL_SESSION_TTL_SECONDS,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _base64url_encode(payload_bytes)
    signature = hmac.new(_admin_panel_session_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def _deserialize_admin_panel_session(raw_cookie: str | None) -> dict[str, Any] | None:
    raw_value = str(raw_cookie or "").strip()
    if "." not in raw_value:
        return None
    encoded_payload, encoded_signature = raw_value.split(".", 1)
    if not encoded_payload or not encoded_signature:
        return None
    expected_signature = hmac.new(
        _admin_panel_session_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        provided_signature = _base64url_decode(encoded_signature)
        payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not secrets.compare_digest(provided_signature, expected_signature):
        return None
    if not isinstance(payload, dict) or int(payload.get("exp") or 0) < int(time.time()):
        return None
    mode = str(payload.get("mode") or "").strip().lower()
    is_admin = bool(payload.get("is_admin"))
    filiais = tuple(str(filial).strip() for filial in payload.get("filiais", []) if str(filial).strip())
    if is_admin and mode == "admin":
        return {"mode": "admin", "is_admin": True, "filiais": ()}
    if mode == "financeiro" and filiais:
        return {"mode": "financeiro", "is_admin": False, "filiais": filiais}
    return None


def _admin_panel_context_from_session_cookie(request: Request) -> dict[str, Any] | None:
    return _deserialize_admin_panel_session(request.cookies.get(ADMIN_PANEL_SESSION_COOKIE))


def _request_uses_https(request: Request) -> bool:
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def _set_admin_panel_session_cookie(response: Response, request: Request, context: dict[str, Any]) -> None:
    response.set_cookie(
        key=ADMIN_PANEL_SESSION_COOKIE,
        value=_serialize_admin_panel_session(context),
        max_age=ADMIN_PANEL_SESSION_TTL_SECONDS,
        httponly=True,
        secure=_request_uses_https(request),
        samesite="lax",
        path="/",
    )


def _admin_panel_login_key(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return forwarded_for or (request.client.host if request.client else "unknown")


def _check_admin_panel_login_rate_limit(request: Request) -> None:
    key = _admin_panel_login_key(request)
    now = time.time()
    cutoff = now - ADMIN_PANEL_LOGIN_WINDOW_SECONDS
    with admin_panel_login_lock:
        failures = [ts for ts in admin_panel_login_failures.get(key, []) if ts >= cutoff]
        admin_panel_login_failures[key] = failures
        if len(failures) >= ADMIN_PANEL_LOGIN_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="Muitas tentativas de login. Aguarde alguns minutos.")


def _record_admin_panel_login_failure(request: Request) -> None:
    key = _admin_panel_login_key(request)
    now = time.time()
    cutoff = now - ADMIN_PANEL_LOGIN_WINDOW_SECONDS
    with admin_panel_login_lock:
        failures = [ts for ts in admin_panel_login_failures.get(key, []) if ts >= cutoff]
        failures.append(now)
        admin_panel_login_failures[key] = failures


def _clear_admin_panel_login_failures(request: Request) -> None:
    key = _admin_panel_login_key(request)
    with admin_panel_login_lock:
        admin_panel_login_failures.pop(key, None)


def _require_admin_token(x_admin_token: str | None, request: Request | None = None) -> None:
    expected_token = settings.admin_api_token.strip()
    if not expected_token:
        if request is not None:
            _record_security_event(
                request,
                channel="api",
                event_type="admin_auth",
                decision="misconfigured",
                reason="admin_token_not_configured",
            )
        raise HTTPException(status_code=503, detail="Rotas administrativas indisponiveis.")

    provided_token = str(x_admin_token or "").strip()
    if provided_token and secrets.compare_digest(provided_token, expected_token):
        if request is not None:
            _record_security_event(
                request,
                channel="api",
                event_type="admin_auth",
                decision="allowed",
            )
        return

    if request is not None:
        _record_security_event(
            request,
            channel="api",
            event_type="admin_auth",
            decision="denied",
            reason="invalid_admin_token",
        )
    raise HTTPException(status_code=401, detail="Admin token invalido.")


def _request_metadata(request: Request, **extra: Any) -> dict[str, Any]:
    metadata = {
        "method": request.method,
        "client_host": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
        "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
    }
    metadata.update({key: value for key, value in extra.items() if value is not None and value != ""})
    return metadata


def _record_security_event(
    request: Request,
    *,
    channel: str,
    event_type: str,
    decision: str,
    phone_number: str | None = None,
    area: str | None = None,
    reason: str | None = None,
    **extra: Any,
) -> None:
    security_monitor.record_event(
        channel=channel,
        path=request.url.path,
        event_type=event_type,
        decision=decision,
        phone_number=phone_number,
        area=area,
        reason=reason,
        metadata=_request_metadata(request, **extra),
    )


def _record_security_event_for_path(
    *,
    path: str,
    metadata: dict[str, Any],
    channel: str,
    event_type: str,
    decision: str,
    phone_number: str | None = None,
    area: str | None = None,
    reason: str | None = None,
    **extra: Any,
) -> None:
    combined_metadata = dict(metadata)
    combined_metadata.update({key: value for key, value in extra.items() if value is not None and value != ""})
    security_monitor.record_event(
        channel=channel,
        path=path,
        event_type=event_type,
        decision=decision,
        phone_number=phone_number,
        area=area,
        reason=reason,
        metadata=combined_metadata,
    )


def _should_send_denied_reply(number: str, reason: str) -> bool:
    persisted_decision = security_monitor.should_send_denied_reply(number=number, reason=reason)
    if persisted_decision is not None:
        return persisted_decision
    return denied_reply_throttle.should_send(number=number, reason=reason)


def _extract_bearer_token(authorization: str | None) -> str:
    raw_value = str(authorization or "").strip()
    if not raw_value:
        return ""
    parts = raw_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _token_matches(candidate: str, expected_values: tuple[str, ...]) -> bool:
    cleaned_candidate = str(candidate or "").strip()
    if not cleaned_candidate:
        return False
    return any(secrets.compare_digest(cleaned_candidate, expected) for expected in expected_values if expected)


def _require_api_auth(
    request: Request,
    authorization: str | None,
    x_api_token: str | None,
) -> None:
    if not settings.api_auth_enabled:
        return

    provided_tokens = []
    bearer_token = _extract_bearer_token(authorization)
    if bearer_token:
        provided_tokens.append(bearer_token)
    if x_api_token and x_api_token.strip():
        provided_tokens.append(x_api_token.strip())

    valid_tokens = tuple(settings.api_auth_tokens)
    if not valid_tokens:
        _record_security_event(
            request,
            channel="api",
            event_type="api_auth",
            decision="misconfigured",
            reason="api_auth_without_tokens",
        )
        raise HTTPException(status_code=503, detail="Autenticacao da API habilitada, mas sem token configurado.")
    if any(_token_matches(candidate, valid_tokens) for candidate in provided_tokens):
        _record_security_event(
            request,
            channel="api",
            event_type="api_auth",
            decision="allowed",
        )
        return

    _record_security_event(
        request,
        channel="api",
        event_type="api_auth",
        decision="denied",
        reason="invalid_or_missing_api_token",
    )
    raise HTTPException(status_code=401, detail="Token da API invalido ou ausente.")


def _admin_token_matches(x_admin_token: str | None) -> bool:
    expected_token = settings.admin_api_token.strip()
    provided_token = str(x_admin_token or "").strip()
    return bool(expected_token and provided_token and secrets.compare_digest(provided_token, expected_token))


def _finance_panel_token_filiais(x_admin_token: str | None) -> tuple[str, ...]:
    provided_token = str(x_admin_token or "").strip()
    if not provided_token:
        return ()
    for expected_token, filiais in settings.finance_panel_tokens:
        if expected_token and secrets.compare_digest(provided_token, expected_token):
            return tuple(str(filial).strip() for filial in filiais if str(filial).strip())
    return ()


def _require_admin_panel_auth(
    request: Request,
    authorization: str | None,
    x_api_token: str | None,
    x_admin_token: str | None,
) -> dict[str, Any]:
    header_context = _admin_panel_context_from_token(x_admin_token)
    if header_context:
        _record_security_event(
            request,
            channel="api",
            event_type="admin_panel_auth",
            decision="allowed",
            reason="admin_token" if header_context.get("is_admin") else "finance_token",
        )
        return header_context

    session_context = _admin_panel_context_from_session_cookie(request)
    if session_context:
        _record_security_event(
            request,
            channel="api",
            event_type="admin_panel_auth",
            decision="allowed",
            reason="panel_session",
        )
        return session_context

    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)
    return {"mode": "admin", "is_admin": True, "filiais": ()}


def _require_admin_api_auth(
    request: Request,
    authorization: str | None,
    x_api_token: str | None,
    x_admin_token: str | None,
) -> None:
    if _admin_token_matches(x_admin_token):
        _record_security_event(
            request,
            channel="api",
            event_type="admin_auth",
            decision="allowed",
            reason="admin_token_for_admin_api",
        )
        return
    session_context = _admin_panel_context_from_session_cookie(request)
    if session_context and session_context.get("is_admin"):
        _record_security_event(
            request,
            channel="api",
            event_type="admin_auth",
            decision="allowed",
            reason="admin_session_for_admin_api",
        )
        return
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_token(x_admin_token, request=request)


def _require_admin_scope_for_number_routes(
    request: Request,
    x_admin_token: str | None,
) -> None:
    if not settings.api_require_admin_for_number:
        return
    session_context = _admin_panel_context_from_session_cookie(request)
    if session_context and session_context.get("is_admin"):
        return
    _require_admin_token(x_admin_token, request=request)


def _decision_has_unrestricted_lookup_access(decision: Any) -> bool:
    roles = {str(role or "").strip().lower() for role in getattr(decision, "roles", ())}
    if "admin" in roles:
        return True
    return "financeiro" in roles and not getattr(decision, "sectors", ()) and not getattr(decision, "gv_vdes", ())


def _require_webhook_token(request: Request, x_bot_token: str | None, payload: dict[str, Any] | None = None) -> None:
    expected_token = settings.verify_token.strip()
    evolution_payload_key = str((payload or {}).get("apikey") or "").strip()
    evolution_webhook_api_keys = [candidate for candidate in settings.evolution_webhook_api_keys if candidate]
    if settings.evolution_webhook_allow_api_key_fallback and settings.evolution_api_key.strip():
        evolution_webhook_api_keys.append(settings.evolution_api_key.strip())
    accepted_evolution_keys = tuple(dict.fromkeys(evolution_webhook_api_keys))

    if expected_token and x_bot_token and secrets.compare_digest(x_bot_token.strip(), expected_token):
        _record_security_event(
            request,
            channel="webhook",
            event_type="webhook_auth",
            decision="allowed",
            reason="x_bot_token",
        )
        return

    if evolution_payload_key and _token_matches(evolution_payload_key, accepted_evolution_keys):
        _record_security_event(
            request,
            channel="webhook",
            event_type="webhook_auth",
            decision="allowed",
            reason="webhook_apikey",
        )
        return

    if not expected_token and not accepted_evolution_keys:
        _record_security_event(
            request,
            channel="webhook",
            event_type="webhook_auth",
            decision="misconfigured",
            reason="webhook_auth_not_configured",
        )
        raise HTTPException(status_code=503, detail="Webhook indisponivel.")

    _record_security_event(
        request,
        channel="webhook",
        event_type="webhook_auth",
        decision="denied",
        reason="invalid_or_missing_webhook_token",
    )
    raise HTTPException(status_code=401, detail="Nao autorizado.")


def _require_meta_cloud_signature(
    request: Request,
    *,
    raw_body: bytes,
    x_hub_signature_256: str | None,
) -> None:
    app_secret = settings.meta_cloud_app_secret.strip()
    if not app_secret:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="meta_signature",
            decision="misconfigured",
            reason="meta_app_secret_missing",
        )
        raise HTTPException(status_code=503, detail="Webhook Meta indisponivel.")

    provided = str(x_hub_signature_256 or "").strip()
    if not provided.startswith("sha256="):
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="meta_signature",
            decision="denied",
            reason="missing_or_invalid_signature_header",
        )
        raise HTTPException(status_code=401, detail="Assinatura Meta invalida ou ausente.")

    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="meta_signature",
            decision="denied",
            reason="signature_mismatch",
        )
        raise HTTPException(status_code=401, detail="Assinatura Meta invalida ou ausente.")

    _record_security_event(
        request,
        channel="meta_webhook",
        event_type="meta_signature",
        decision="allowed",
        reason="x_hub_signature_256",
    )


def _access_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _normalize_admin_import_dataset(dataset: str) -> str:
    normalized = str(dataset or "").strip().lower()
    if normalized not in ADMIN_IMPORT_DATASETS:
        allowed = ", ".join(sorted(ADMIN_IMPORT_DATASETS))
        raise HTTPException(status_code=400, detail=f"Dataset invalido. Use {allowed}.")
    return normalized


def _serialize_admin_import_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_admin_import_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_admin_import_value(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_admin_import_value(item) for item in value]
    return value


def _clear_critica_runtime_cache() -> None:
    try:
        critica_rn_query_service.clear_cache()
    except Exception:
        logger.exception("Falha ao limpar cache runtime da critica RN")


def _prebuild_critica_pdf_reports() -> dict[str, Any]:
    try:
        return critica_rn_pdf_prebuild_service.warm_pdf_reports()
    except Exception as exc:
        logger.exception("Falha ao pre-gerar PDFs da critica RN")
        return {"ok": False, "error": str(exc)}


def _new_critica_pdf_prebuild_job_id() -> str:
    return f"critica-pdf-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def _snapshot_critica_pdf_prebuild_state() -> dict[str, Any]:
    with critica_pdf_prebuild_lock:
        return _serialize_admin_import_value(dict(critica_pdf_prebuild_state))


def _critica_pdf_prebuild_worker(job_id: str, reason: str) -> None:
    current_job_id = job_id
    current_reason = reason
    while True:
        started_at = datetime.now(timezone.utc).isoformat()
        with critica_pdf_prebuild_lock:
            critica_pdf_prebuild_state["running"] = True
            critica_pdf_prebuild_state["current_job_id"] = current_job_id
            critica_pdf_prebuild_state["current_reason"] = current_reason
            critica_pdf_prebuild_state["started_at"] = started_at
            critica_pdf_prebuild_state["finished_at"] = ""
            critica_pdf_prebuild_state["last_error"] = ""

        result = _prebuild_critica_pdf_reports()
        finished_at = datetime.now(timezone.utc).isoformat()
        error = ""
        if not result.get("ok"):
            error = str(result.get("error") or "; ".join(result.get("errors") or []) or "Falha ao pre-gerar PDFs.")

        with critica_pdf_prebuild_lock:
            critica_pdf_prebuild_state["finished_at"] = finished_at
            critica_pdf_prebuild_state["last_result"] = _serialize_admin_import_value(result)
            critica_pdf_prebuild_state["last_error"] = error
            if critica_pdf_prebuild_state.get("pending"):
                current_job_id = _new_critica_pdf_prebuild_job_id()
                current_reason = str(critica_pdf_prebuild_state.get("current_reason") or current_reason)
                critica_pdf_prebuild_state["pending"] = False
                critica_pdf_prebuild_state["current_job_id"] = current_job_id
                continue
            critica_pdf_prebuild_state["running"] = False
            critica_pdf_prebuild_state["current_job_id"] = ""
            critica_pdf_prebuild_state["current_reason"] = ""
            return


def _queue_critica_pdf_prebuild(reason: str) -> dict[str, Any]:
    queued_at = datetime.now(timezone.utc).isoformat()
    clean_reason = str(reason or "import").strip() or "import"
    with critica_pdf_prebuild_lock:
        if critica_pdf_prebuild_state.get("running"):
            critica_pdf_prebuild_state["pending"] = True
            critica_pdf_prebuild_state["queued_at"] = queued_at
            critica_pdf_prebuild_state["current_reason"] = clean_reason
            return {
                "ok": True,
                "queued": True,
                "running": True,
                "pending": True,
                "reason": clean_reason,
                "message": "Pre-geracao de PDFs ja estava em andamento; nova rodada marcada para o final.",
            }
        job_id = _new_critica_pdf_prebuild_job_id()
        critica_pdf_prebuild_state["running"] = True
        critica_pdf_prebuild_state["pending"] = False
        critica_pdf_prebuild_state["current_job_id"] = job_id
        critica_pdf_prebuild_state["current_reason"] = clean_reason
        critica_pdf_prebuild_state["queued_at"] = queued_at
        critica_pdf_prebuild_state["started_at"] = ""
        critica_pdf_prebuild_state["finished_at"] = ""
        critica_pdf_prebuild_state["last_error"] = ""

    try:
        critica_pdf_prebuild_executor.submit(_critica_pdf_prebuild_worker, job_id, clean_reason)
    except Exception as exc:
        with critica_pdf_prebuild_lock:
            critica_pdf_prebuild_state["running"] = False
            critica_pdf_prebuild_state["pending"] = False
            critica_pdf_prebuild_state["current_job_id"] = ""
            critica_pdf_prebuild_state["last_error"] = str(exc)
        logger.exception("Falha ao enfileirar pre-geracao de PDFs da critica")
        return {"ok": False, "queued": False, "error": str(exc)}
    return {
        "ok": True,
        "queued": True,
        "running": False,
        "pending": False,
        "job_id": job_id,
        "reason": clean_reason,
    }


def _new_admin_import_job_id(dataset: str, action: str) -> str:
    clean_dataset = _normalize_admin_import_dataset(dataset)
    clean_action = str(action or "job").strip().lower() or "job"
    return f"{clean_action}-{clean_dataset}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def _admin_import_conflict_group(dataset: str) -> str:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    if normalized_dataset in ADMIN_IMPORT_CRITICA_PIPELINE_DATASETS or normalized_dataset.startswith("critica_op_"):
        return "critica_pipeline"
    return normalized_dataset


def _admin_import_lock_keys(dataset: str, action: str) -> list[str]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    clean_action = str(action or "").strip().lower()
    keys = [f"admin-source:{normalized_dataset}"]
    if clean_action == "import":
        keys.append(f"admin-import:{_admin_import_conflict_group(normalized_dataset)}")
    return keys


def _admin_import_actor(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    mode = str(context.get("mode") or "").strip() or "admin"
    if bool(context.get("is_admin")):
        return "admin"
    filiais = ",".join(str(filial).strip() for filial in context.get("filiais", ()) if str(filial).strip())
    return f"{mode}:{filiais}" if filiais else mode


def _active_admin_import_job(lock_keys: list[str]) -> dict[str, Any] | None:
    try:
        return admin_import_job_service.find_active_job(lock_keys)
    except Exception as exc:
        logger.warning("Falha ao consultar jobs administrativos ativos: %s", exc)
        return None


def _admin_import_busy_message(active_job: dict[str, Any] | None, *, fallback_dataset: str) -> str:
    if active_job:
        label = str(active_job.get("dataset_label") or active_job.get("dataset") or fallback_dataset)
        action = "upload" if str(active_job.get("action") or "") == "upload" else "importacao"
        return f"Ja existe {action} em andamento para {label}. Aguarde finalizar antes de continuar."
    return f"Ja existe uma operacao administrativa em andamento para {fallback_dataset}."


def _run_admin_import_validation(dataset: str, source_path_override: Path | None = None) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    config = ADMIN_IMPORT_DATASETS[normalized_dataset]
    source_path = source_path_override or _resolve_admin_import_source_path(normalized_dataset)
    service = config["service"]
    validation = getattr(service, str(config["validate_method"]))(source_path)
    if normalized_dataset == "dclientes":
        summary = getattr(service, str(config["summarize_method"]))(source_path, validate=False)
    else:
        summary = getattr(service, str(config["summarize_method"]))(source_path)

    return {
        "dataset": normalized_dataset,
        "label": config["label"],
        "default_path": str(source_path),
        "accept_extensions": str(config.get("accept_extensions") or ""),
        "validation": _serialize_admin_import_value(validation.to_dict()),
        "summary": _serialize_admin_import_value(summary.to_dict()),
    }


def _run_admin_import(dataset: str, reference_date: str | None = None) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    config = ADMIN_IMPORT_DATASETS[normalized_dataset]
    source_path = _resolve_admin_import_source_path(normalized_dataset)
    service = config["service"]
    batch_date = date.fromisoformat(reference_date) if str(reference_date or "").strip() else None

    validation_payload = _run_admin_import_validation(normalized_dataset)
    validation_errors = int(validation_payload["validation"].get("error_count") or 0)
    if validation_errors:
        raise HTTPException(status_code=400, detail="A validacao encontrou erros. Corrija o arquivo antes de importar.")

    if normalized_dataset == "dsetores":
        result = getattr(service, str(config["import_method"]))(source_path, reference_date=batch_date)
        refresh_result = dclientes_import_service.refresh_latest_view()
        critica_refresh_result = critica_rn_import_service.refresh_latest_view()
        critica_operacao_refresh_result = critica_operacao_admin_service.refresh_latest_view()
        _clear_critica_runtime_cache()
        prebuild_result = _queue_critica_pdf_prebuild(normalized_dataset)
        return {
            "dataset": normalized_dataset,
            "label": config["label"],
            "default_path": str(source_path),
            "accept_extensions": str(config.get("accept_extensions") or ""),
            "validation": validation_payload["validation"],
            "summary": validation_payload["summary"],
            "import_result": _serialize_admin_import_value(result),
            "post_actions": {
                "refresh_dclientes_view": _serialize_admin_import_value(refresh_result),
                "refresh_critica_rn_view": _serialize_admin_import_value(critica_refresh_result),
                "refresh_critica_operacao_view": _serialize_admin_import_value(critica_operacao_refresh_result),
                "prebuild_critica_pdf_reports": _serialize_admin_import_value(prebuild_result),
            },
        }
    if normalized_dataset == "dclientes":
        result = getattr(service, str(config["import_method"]))(
            source_path,
            reference_date=batch_date,
            summary=validation_payload["summary"],
        )
    else:
        result = getattr(service, str(config["import_method"]))(source_path, reference_date=batch_date)
    post_actions: dict[str, Any] = {}
    if normalized_dataset == "dprecos":
        post_actions["refresh_critica_rn_view"] = _serialize_admin_import_value(critica_rn_import_service.refresh_latest_view())
        post_actions["refresh_critica_operacao_view"] = _serialize_admin_import_value(
            critica_operacao_admin_service.refresh_latest_view()
        )
    if normalized_dataset in {
        "critica_rn",
        "dclientes",
        "doperacoes",
        "dprecos",
    } or normalized_dataset.startswith("critica_op_"):
        _clear_critica_runtime_cache()
        post_actions["prebuild_critica_pdf_reports"] = _serialize_admin_import_value(
            _queue_critica_pdf_prebuild(normalized_dataset)
        )
    response_payload = {
        "dataset": normalized_dataset,
        "label": config["label"],
        "default_path": str(source_path),
        "accept_extensions": str(config.get("accept_extensions") or ""),
        "validation": validation_payload["validation"],
        "summary": validation_payload["summary"],
        "import_result": _serialize_admin_import_value(result),
    }
    if post_actions:
        response_payload["post_actions"] = post_actions
    return response_payload


def _snapshot_admin_import_state() -> dict[str, Any]:
    with admin_import_lock:
        current_jobs = dict(admin_import_state.get("current_jobs") or {})
        first_job = next(iter(current_jobs.values()), {})
        return _serialize_admin_import_value(
            {
                "running": bool(current_jobs),
                "current_job_id": str(first_job.get("job_id") or ""),
                "current_dataset": str(first_job.get("dataset") or ""),
                "started_at": str(first_job.get("started_at") or ""),
                "reference_date": str(first_job.get("reference_date") or ""),
                "current_jobs": list(current_jobs.values()),
                "last_job": dict(admin_import_state.get("last_job") or {}),
            }
        )


def _format_admin_import_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, str):
            return detail
        return str(detail)
    return str(error)


def _finish_admin_import_job(
    *,
    job_id: str,
    dataset: str,
    started_at: str,
    reference_date: str,
    status: str,
    result: dict[str, Any] | None,
    error: str,
) -> None:
    finished_at = datetime.now(timezone.utc).isoformat()
    try:
        admin_import_job_service.finish_job(
            job_id=job_id,
            status=status,
            result=_serialize_admin_import_value(result) if result is not None else None,
            error=error,
        )
    except Exception:
        logger.exception("Falha ao atualizar job administrativo %s no banco.", job_id)
    with admin_import_lock:
        current_jobs = admin_import_state.setdefault("current_jobs", {})
        if isinstance(current_jobs, dict):
            current_jobs.pop(job_id, None)
        first_job = next(iter((current_jobs or {}).values()), {}) if isinstance(current_jobs, dict) else {}
        admin_import_state["running"] = bool(current_jobs)
        admin_import_state["current_job_id"] = str(first_job.get("job_id") or "")
        admin_import_state["current_dataset"] = str(first_job.get("dataset") or "")
        admin_import_state["started_at"] = str(first_job.get("started_at") or "")
        admin_import_state["reference_date"] = str(first_job.get("reference_date") or "")
        admin_import_state["last_job"] = {
            "job_id": job_id,
            "dataset": dataset,
            "label": ADMIN_IMPORT_DATASETS.get(dataset, {}).get("label", dataset),
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "reference_date": reference_date,
            "error": error,
            "result": _serialize_admin_import_value(result) if result is not None else None,
        }
    _run_admin_import_maintenance(force_stale=False)


def _admin_import_worker(job_id: str, dataset: str, reference_date: str, started_at: str) -> None:
    try:
        try:
            admin_import_job_service.start_job(job_id)
        except Exception:
            logger.exception("Falha ao marcar job administrativo %s como running.", job_id)
        lock_keys = _admin_import_lock_keys(dataset, "import")
        with admin_import_job_service.operation_lock(lock_keys):
            result = _run_admin_import(dataset, reference_date=reference_date or None)
    except AdminImportLockBusy as exc:
        logger.warning("Importacao %s bloqueada por lock ativo: %s", job_id, exc.lock_key)
        _finish_admin_import_job(
            job_id=job_id,
            dataset=dataset,
            started_at=str(started_at),
            reference_date=reference_date,
            status="blocked",
            result=None,
            error=_admin_import_busy_message(None, fallback_dataset=dataset),
        )
        return
    except Exception as exc:
        logger.exception("Falha ao importar dataset %s pelo painel admin.", dataset)
        _finish_admin_import_job(
            job_id=job_id,
            dataset=dataset,
            started_at=str(started_at),
            reference_date=reference_date,
            status="failed",
            result=None,
            error=_format_admin_import_error(exc),
        )
        return

    _finish_admin_import_job(
        job_id=job_id,
        dataset=dataset,
        started_at=str(started_at),
        reference_date=reference_date,
        status="completed",
        result=result,
        error="",
    )


def _queue_admin_import(
    dataset: str,
    reference_date: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    clean_reference_date = str(reference_date or "").strip()
    started_at = datetime.now(timezone.utc).isoformat()
    job_id = _new_admin_import_job_id(normalized_dataset, "import")
    lock_keys = _admin_import_lock_keys(normalized_dataset, "import")
    active_job = _active_admin_import_job(lock_keys)
    if active_job:
        raise HTTPException(
            status_code=409,
            detail=_admin_import_busy_message(active_job, fallback_dataset=normalized_dataset),
        )

    with admin_import_lock:
        try:
            source_path = str(_resolve_admin_import_source_path(normalized_dataset))
        except Exception:
            source_path = ""
        try:
            admin_import_job_service.create_job(
                job_id=job_id,
                action="import",
                dataset_name=normalized_dataset,
                dataset_label=str(ADMIN_IMPORT_DATASETS[normalized_dataset]["label"]),
                lock_keys=lock_keys,
                reference_date=date.fromisoformat(clean_reference_date) if clean_reference_date else None,
                source_path=source_path,
                created_by=_admin_import_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Falha ao criar job administrativo de importacao.")
            raise HTTPException(status_code=503, detail="Nao foi possivel registrar a importacao no banco.") from exc
        current_jobs = admin_import_state.setdefault("current_jobs", {})
        if not isinstance(current_jobs, dict):
            current_jobs = {}
            admin_import_state["current_jobs"] = current_jobs
        current_jobs[job_id] = {
            "job_id": job_id,
            "dataset": normalized_dataset,
            "label": ADMIN_IMPORT_DATASETS[normalized_dataset]["label"],
            "started_at": started_at,
            "reference_date": clean_reference_date,
        }
        admin_import_state["running"] = True
        admin_import_state["current_job_id"] = job_id
        admin_import_state["current_dataset"] = normalized_dataset
        admin_import_state["started_at"] = started_at
        admin_import_state["reference_date"] = clean_reference_date

    try:
        admin_import_executor.submit(_admin_import_worker, job_id, normalized_dataset, clean_reference_date, started_at)
    except Exception:
        with admin_import_lock:
            current_jobs = admin_import_state.setdefault("current_jobs", {})
            if isinstance(current_jobs, dict):
                current_jobs.pop(job_id, None)
            first_job = next(iter((current_jobs or {}).values()), {}) if isinstance(current_jobs, dict) else {}
            admin_import_state["running"] = bool(current_jobs)
            admin_import_state["current_job_id"] = str(first_job.get("job_id") or "")
            admin_import_state["current_dataset"] = str(first_job.get("dataset") or "")
            admin_import_state["started_at"] = str(first_job.get("started_at") or "")
            admin_import_state["reference_date"] = str(first_job.get("reference_date") or "")
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="failed", error="Falha ao enviar job para fila.")
        except Exception:
            logger.exception("Falha ao marcar job administrativo %s como failed.", job_id)
        raise

    return {
        "job_id": job_id,
        "dataset": normalized_dataset,
        "label": ADMIN_IMPORT_DATASETS[normalized_dataset]["label"],
        "reference_date": clean_reference_date,
        "state": _snapshot_admin_import_state(),
    }


def _sanitize_uploaded_filename(dataset: str, filename: str) -> str:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    allowed_extensions = {
        item.strip().lower()
        for item in str(ADMIN_IMPORT_DATASETS[normalized_dataset].get("accept_extensions") or "").split(",")
        if item.strip()
    }
    clean_name = Path(str(filename or "")).name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Arquivo invalido para upload.")
    suffix = Path(clean_name).suffix.lower()
    if allowed_extensions and suffix not in allowed_extensions:
        extension_text = ", ".join(sorted(allowed_extensions))
        raise HTTPException(status_code=400, detail=f"Extensao invalida. Use: {extension_text}.")
    return clean_name


def _dataset_runtime_upload_path(dataset: str) -> Path:
    active_path = _active_admin_upload_source_path(dataset)
    if active_path is not None:
        return active_path
    return _legacy_dataset_runtime_upload_path(dataset)


def _dataset_runtime_root(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    return ADMIN_IMPORT_RUNTIME_ROOT / normalized_dataset


def _legacy_dataset_runtime_upload_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    default_path = Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])
    runtime_dir = _dataset_runtime_root(normalized_dataset)
    if ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"] == "single":
        return runtime_dir / default_path.name
    return runtime_dir


def _dataset_active_upload_manifest_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    return _dataset_runtime_root(normalized_dataset) / "active.json"


def _dataset_upload_version_path(dataset: str, job_id: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    default_path = Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])
    clean_job_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(job_id or "").strip()) or secrets.token_hex(8)
    version_root = _dataset_runtime_root(normalized_dataset) / "versions" / clean_job_id
    if ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"] == "single":
        return version_root / default_path.name
    return version_root


def _read_admin_upload_manifest(dataset: str) -> dict[str, Any] | None:
    manifest_path = _dataset_active_upload_manifest_path(dataset)
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Manifesto de upload invalido para %s: %s", dataset, manifest_path)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _active_admin_upload_source_path(dataset: str) -> Path | None:
    payload = _read_admin_upload_manifest(dataset)
    if not payload:
        return None
    source_path = Path(str(payload.get("source_path") or ""))
    if source_path.exists():
        return source_path
    return None


def _activate_admin_upload_version(
    dataset: str,
    *,
    source_path: Path,
    stored_files: list[dict[str, Any]],
    job_id: str,
) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    manifest_path = _dataset_active_upload_manifest_path(normalized_dataset)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset": normalized_dataset,
        "job_id": str(job_id or ""),
        "source_path": str(source_path),
        "stored_files": _serialize_admin_import_value(stored_files),
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    temp_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    temp_path.replace(manifest_path)
    return manifest


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
    except OSError:
        return False
    return child_resolved == parent_resolved or parent_resolved in child_resolved.parents


def _active_admin_upload_protected_paths() -> set[Path]:
    protected: set[Path] = set()
    for dataset_name in ADMIN_IMPORT_DATASETS:
        active_path = _active_admin_upload_source_path(dataset_name)
        if active_path is None:
            continue
        try:
            resolved = active_path.resolve()
        except OSError:
            continue
        protected.add(resolved)
        for parent in resolved.parents:
            if _path_is_within(parent, ADMIN_IMPORT_RUNTIME_ROOT):
                protected.add(parent)
            else:
                break
    return protected


def _prune_admin_upload_versions(keep_days: int = ADMIN_IMPORT_HISTORY_RETENTION_DAYS) -> dict[str, Any]:
    retention_days = max(int(keep_days), 1)
    cutoff_timestamp = time.time() - (retention_days * 24 * 60 * 60)
    root = ADMIN_IMPORT_RUNTIME_ROOT
    if not root.exists():
        return {"ok": True, "deleted": 0, "kept_active": 0, "retention_days": retention_days}
    protected_paths = _active_admin_upload_protected_paths()
    deleted = 0
    kept_active = 0
    errors: list[str] = []

    for dataset_name in ADMIN_IMPORT_DATASETS:
        versions_dir = _dataset_runtime_root(dataset_name) / "versions"
        if not versions_dir.exists() or not versions_dir.is_dir():
            continue
        try:
            candidates = list(versions_dir.iterdir())
        except OSError as exc:
            errors.append(f"{versions_dir}: {exc}")
            continue
        for candidate in candidates:
            try:
                candidate_resolved = candidate.resolve()
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            if not _path_is_within(candidate_resolved, root):
                errors.append(f"{candidate}: fora do diretorio de uploads")
                continue
            if candidate_resolved in protected_paths:
                kept_active += 1
                continue
            try:
                candidate_mtime = candidate.stat().st_mtime
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            if candidate_mtime >= cutoff_timestamp:
                continue
            try:
                if candidate.is_dir():
                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
                deleted += 1
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")

    return {
        "ok": not errors,
        "deleted": deleted,
        "kept_active": kept_active,
        "retention_days": retention_days,
        "errors": errors[:10],
    }


def _run_admin_import_maintenance(*, force_stale: bool = False) -> dict[str, Any]:
    if not admin_import_maintenance_lock.acquire(blocking=False):
        return {"ok": True, "skipped": "maintenance_already_running"}
    try:
        stale_count = 0
        if force_stale:
            stale_count = admin_import_job_service.mark_active_jobs_stale()
        deleted_jobs = admin_import_job_service.prune_old_jobs(keep_days=ADMIN_IMPORT_HISTORY_RETENTION_DAYS)
        deleted_versions = _prune_admin_upload_versions(keep_days=ADMIN_IMPORT_HISTORY_RETENTION_DAYS)
        if force_stale:
            with admin_import_lock:
                admin_import_state["running"] = False
                admin_import_state["current_job_id"] = ""
                admin_import_state["current_dataset"] = ""
                admin_import_state["started_at"] = ""
                admin_import_state["reference_date"] = ""
                admin_import_state["current_jobs"] = {}
        return {
            "ok": True,
            "stale_jobs": stale_count,
            "deleted_jobs": deleted_jobs,
            "upload_versions": deleted_versions,
            "retention_days": ADMIN_IMPORT_HISTORY_RETENTION_DAYS,
        }
    except Exception as exc:
        logger.exception("Falha na manutencao de imports administrativos")
        return {"ok": False, "error": str(exc)}
    finally:
        admin_import_maintenance_lock.release()


def _admin_import_allows_default_source(dataset: str) -> bool:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    return bool(ADMIN_IMPORT_DATASETS[normalized_dataset].get("allow_default_source", True))


def _resolve_admin_import_source_path(dataset: str) -> Path:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    runtime_path = _dataset_runtime_upload_path(normalized_dataset)
    if runtime_path.exists():
        return runtime_path
    if not _admin_import_allows_default_source(normalized_dataset):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{ADMIN_IMPORT_DATASETS[normalized_dataset]['label']} exige upload ativo pelo painel. "
                "A pasta data e apenas base de teste e nao sera usada para importacao."
            ),
        )
    return Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])


def _admin_import_source_status(dataset: str) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    runtime_path = _dataset_runtime_upload_path(normalized_dataset)
    legacy_runtime_path = _legacy_dataset_runtime_upload_path(normalized_dataset)
    manifest = _read_admin_upload_manifest(normalized_dataset) or {}
    default_path = Path(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"])
    allow_default = _admin_import_allows_default_source(normalized_dataset)
    if runtime_path.exists():
        active_source_path = runtime_path
        source_exists = True
        using_uploaded_source = True
    elif allow_default:
        active_source_path = default_path
        source_exists = default_path.exists()
        using_uploaded_source = False
    else:
        active_source_path = runtime_path
        source_exists = False
        using_uploaded_source = False
    return {
        "default_path": str(default_path),
        "active_source_path": str(active_source_path),
        "source_exists": source_exists,
        "using_uploaded_source": using_uploaded_source,
        "versioned_upload": bool(manifest),
        "legacy_upload_path": str(legacy_runtime_path),
        "active_upload_job_id": str(manifest.get("job_id") or ""),
        "active_upload_activated_at": str(manifest.get("activated_at") or ""),
        "requires_upload": not allow_default,
    }


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


def _replace_single_upload_source(
    dataset: str,
    files: list[UploadFile],
    target_path: Path | None = None,
) -> list[dict[str, Any]]:
    if len(files) != 1:
        raise HTTPException(status_code=400, detail="Esse dataset aceita exatamente um arquivo por vez.")

    target_path = target_path or _legacy_dataset_runtime_upload_path(dataset)
    upload = files[0]
    _sanitize_uploaded_filename(dataset, upload.filename or "")
    temp_path = target_path.with_name(f"{target_path.name}.uploading")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with temp_path.open("wb") as buffer:
            _copy_upload_with_limit(upload, buffer)
        temp_path.replace(target_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        upload.file.close()

    return [
        {
            "saved_as": str(target_path),
            "uploaded_name": str(upload.filename or ""),
            "size_bytes": int(target_path.stat().st_size),
        }
    ]


def _replace_multiple_upload_source(
    dataset: str,
    files: list[UploadFile],
    target_dir: Path | None = None,
) -> list[dict[str, Any]]:
    if not files:
        raise HTTPException(status_code=400, detail="Selecione pelo menos um arquivo para upload.")

    target_dir = target_dir or _legacy_dataset_runtime_upload_path(dataset)
    temp_dir = target_dir.with_name(f"{target_dir.name}__uploading")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    try:
        for upload in files:
            safe_name = _sanitize_uploaded_filename(dataset, upload.filename or "")
            if safe_name in seen_names:
                raise HTTPException(status_code=400, detail=f"Arquivo repetido no upload: {safe_name}")
            seen_names.add(safe_name)
            temp_path = temp_dir / safe_name
            try:
                with temp_path.open("wb") as buffer:
                    _copy_upload_with_limit(upload, buffer)
            finally:
                upload.file.close()
            saved_files.append(
                {
                    "saved_as": str(temp_path),
                    "uploaded_name": str(upload.filename or ""),
                    "size_bytes": int(temp_path.stat().st_size),
                }
            )

        if target_dir.exists():
            shutil.rmtree(target_dir)
        temp_dir.replace(target_dir)
        for item in saved_files:
            item["saved_as"] = str(target_dir / Path(item["saved_as"]).name)
        return saved_files
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def _close_admin_upload_files(files: list[UploadFile]) -> None:
    for upload in files:
        try:
            upload.file.close()
        except Exception:
            pass


def _store_admin_import_uploads(
    dataset: str,
    files: list[UploadFile],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_dataset = _normalize_admin_import_dataset(dataset)
    if len(files) > settings.admin_upload_max_file_count:
        _close_admin_upload_files(files)
        raise HTTPException(
            status_code=413,
            detail=f"Upload permite no maximo {settings.admin_upload_max_file_count} arquivo(s) por requisicao.",
        )
    file_names = [str(upload.filename or "") for upload in files]
    lock_keys = _admin_import_lock_keys(normalized_dataset, "upload")
    active_job = _active_admin_import_job(lock_keys)
    if active_job:
        _close_admin_upload_files(files)
        raise HTTPException(
            status_code=409,
            detail=_admin_import_busy_message(active_job, fallback_dataset=normalized_dataset),
        )

    job_id = _new_admin_import_job_id(normalized_dataset, "upload")
    upload_mode = ADMIN_IMPORT_DATASETS[normalized_dataset]["upload_mode"]
    version_source_path = _dataset_upload_version_path(normalized_dataset, job_id)
    try:
        admin_import_job_service.create_job(
            job_id=job_id,
            action="upload",
            dataset_name=normalized_dataset,
            dataset_label=str(ADMIN_IMPORT_DATASETS[normalized_dataset]["label"]),
            lock_keys=lock_keys,
            source_path=str(version_source_path),
            file_names=file_names,
            created_by=_admin_import_actor(context),
            metadata={"upload_mode": upload_mode},
        )
        admin_import_job_service.start_job(job_id)
        with admin_import_job_service.operation_lock(lock_keys):
            if upload_mode == "single":
                stored_files = _replace_single_upload_source(normalized_dataset, files, target_path=version_source_path)
            else:
                stored_files = _replace_multiple_upload_source(normalized_dataset, files, target_dir=version_source_path)

            validation_result = _run_admin_import_validation(normalized_dataset, source_path_override=version_source_path)
            validation_errors = int(validation_result["validation"].get("error_count") or 0)
            if validation_errors:
                raise HTTPException(
                    status_code=400,
                    detail="A validacao encontrou erros. A versao enviada foi salva, mas nao foi ativada.",
                )
            active_manifest = _activate_admin_upload_version(
                normalized_dataset,
                source_path=version_source_path,
                stored_files=stored_files,
                job_id=job_id,
            )
            result = {
                "job_id": job_id,
                "dataset": normalized_dataset,
                "label": ADMIN_IMPORT_DATASETS[normalized_dataset]["label"],
                "default_path": str(ADMIN_IMPORT_DATASETS[normalized_dataset]["default_path"]),
                "active_source_path": str(_resolve_admin_import_source_path(normalized_dataset)),
                "upload_mode": upload_mode,
                "stored_files": stored_files,
                "active_upload": active_manifest,
                "validation": validation_result["validation"],
                "summary": validation_result["summary"],
            }
        admin_import_job_service.finish_job(
            job_id=job_id,
            status="completed",
            result=_serialize_admin_import_value(result),
            error="",
        )
        _run_admin_import_maintenance(force_stale=False)
        return result
    except AdminImportLockBusy as exc:
        _close_admin_upload_files(files)
        error = _admin_import_busy_message(None, fallback_dataset=normalized_dataset)
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="blocked", error=error)
            _run_admin_import_maintenance(force_stale=False)
        except Exception:
            logger.exception("Falha ao marcar upload administrativo %s como blocked.", job_id)
        raise HTTPException(status_code=409, detail=error) from exc
    except HTTPException as exc:
        _close_admin_upload_files(files)
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="failed", error=_format_admin_import_error(exc))
            _run_admin_import_maintenance(force_stale=False)
        except Exception:
            logger.exception("Falha ao marcar upload administrativo %s como failed.", job_id)
        raise
    except Exception as exc:
        _close_admin_upload_files(files)
        try:
            admin_import_job_service.finish_job(job_id=job_id, status="failed", error=_format_admin_import_error(exc))
            _run_admin_import_maintenance(force_stale=False)
        except Exception:
            logger.exception("Falha ao marcar upload administrativo %s como failed.", job_id)
        raise


def _list_admin_import_status() -> dict[str, Any]:
    dataset_rows: dict[str, dict[str, Any]] = {}
    database_error = ""
    query = """
        SELECT dataset_name, id, source_file, file_hash, reference_date, total_rows, imported_at
        FROM (
            SELECT
                dataset_name,
                id,
                source_file,
                file_hash,
                reference_date,
                total_rows,
                imported_at,
                ROW_NUMBER() OVER (PARTITION BY dataset_name ORDER BY imported_at DESC, id DESC) AS rn
            FROM reports.import_batches
            WHERE dataset_name = ANY(%s)
        ) latest
        WHERE rn = 1
    """
    try:
        with psycopg.connect(settings.reports_runtime_database_url, connect_timeout=int(settings.access_database_timeout_seconds)) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (list(ADMIN_IMPORT_DATASETS.keys()),))
                for dataset_name, batch_id, source_file, file_hash, reference_date, total_rows, imported_at in cur.fetchall():
                    dataset_rows[str(dataset_name)] = {
                        "batch_id": int(batch_id),
                        "source_file": str(source_file or ""),
                        "file_hash": str(file_hash or ""),
                        "reference_date": _serialize_admin_import_value(reference_date),
                        "total_rows": int(total_rows or 0),
                        "imported_at": _serialize_admin_import_value(imported_at),
                    }
    except Exception as exc:
        database_error = str(exc)
        logger.warning("Falha ao consultar status das importacoes no banco: %s", exc)

    items: list[dict[str, Any]] = []
    for dataset_name, config in ADMIN_IMPORT_DATASETS.items():
        runtime_path = _dataset_runtime_upload_path(dataset_name)
        source_status = _admin_import_source_status(dataset_name)
        items.append(
            {
                "dataset": dataset_name,
                "label": config["label"],
                "default_path": source_status["default_path"],
                "active_source_path": source_status["active_source_path"],
                "source_exists": bool(source_status["source_exists"]),
                "using_uploaded_source": runtime_path.exists(),
                "requires_upload": bool(source_status["requires_upload"]),
                "upload_mode": str(config.get("upload_mode") or "single"),
                "accept_extensions": str(config.get("accept_extensions") or ""),
                "last_import": dataset_rows.get(dataset_name),
            }
        )

    state_snapshot = _snapshot_admin_import_state()
    state_snapshot["items"] = items
    state_snapshot["database_error"] = database_error
    state_snapshot["critica_pdf_prebuild"] = _snapshot_critica_pdf_prebuild_state()
    try:
        state_snapshot["jobs"] = _serialize_admin_import_value(admin_import_job_service.list_recent_jobs(limit=10))
        state_snapshot["jobs_error"] = ""
    except Exception as exc:
        logger.warning("Falha ao consultar jobs administrativos recentes: %s", exc)
        state_snapshot["jobs"] = []
        state_snapshot["jobs_error"] = str(exc)
    return state_snapshot


def _list_admin_import_history(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit), 100))
    history: list[dict[str, Any]] = []
    database_error = ""
    query = """
        SELECT dataset_name, id, source_file, file_hash, reference_date, total_rows, imported_at
        FROM reports.import_batches
        WHERE dataset_name = ANY(%s)
          AND imported_at >= NOW() - (%s::int * INTERVAL '1 day')
        ORDER BY imported_at DESC, id DESC
        LIMIT %s
    """
    try:
        with psycopg.connect(settings.reports_runtime_database_url, connect_timeout=int(settings.access_database_timeout_seconds)) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (list(ADMIN_IMPORT_DATASETS.keys()), ADMIN_IMPORT_HISTORY_RETENTION_DAYS, safe_limit))
                for dataset_name, batch_id, source_file, file_hash, reference_date, total_rows, imported_at in cur.fetchall():
                    history.append(
                        {
                            "dataset": str(dataset_name),
                            "label": ADMIN_IMPORT_DATASETS.get(str(dataset_name), {}).get("label", str(dataset_name)),
                            "batch_id": int(batch_id),
                            "source_file": str(source_file or ""),
                            "file_hash": str(file_hash or ""),
                            "reference_date": _serialize_admin_import_value(reference_date),
                            "total_rows": int(total_rows or 0),
                            "imported_at": _serialize_admin_import_value(imported_at),
                        }
                    )
    except Exception as exc:
        database_error = str(exc)
        logger.warning("Falha ao consultar historico de importacoes no banco: %s", exc)
    jobs: list[dict[str, Any]] = []
    jobs_error = ""
    try:
        jobs = _serialize_admin_import_value(admin_import_job_service.list_recent_jobs(limit=safe_limit))
    except Exception as exc:
        jobs_error = str(exc)
        logger.warning("Falha ao consultar historico de jobs administrativos: %s", exc)
    return {
        "total": len(history),
        "history": history,
        "jobs": jobs,
        "jobs_error": jobs_error,
        "database_error": database_error,
    }


def _normalize_recolha_status(value: str | None) -> str:
    normalized = " ".join(
        str(value or "")
        .strip()
        .replace("Ã£", "ã")
        .replace("Ã§", "ç")
        .split()
    )
    comparable = "".join(
        char
        for char in unicodedata.normalize("NFD", normalized.lower())
        if unicodedata.category(char) != "Mn"
    )
    if comparable in {"ok", "sim", "s", "lancado"}:
        return "Ok"
    if comparable in {"nok", "nao", "n", "nao lancado"}:
        return "Nok"
    if comparable == "recolhido":
        return "Recolhido"
    if comparable in {"nao recolhido", "nao-recolhido"}:
        return "Não Recolhido"
    return normalized


def _extract_recolha_comodato_number(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    labeled_match = re.search(
        r"\b(?:comodato|pedido|numero|nro|num)\s*[:#-]?\s*([A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*)",
        raw,
        flags=re.IGNORECASE,
    )
    if labeled_match:
        return normalize_numeric_code(labeled_match.group(1))

    if re.fullmatch(r"[A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*", raw):
        return normalize_numeric_code(raw)

    leading_match = re.match(
        r"^\s*([A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*)\s*(?:[|;/,]|-\s+)",
        raw,
    )
    if leading_match:
        return normalize_numeric_code(leading_match.group(1))

    return ""


def _build_recolha_baixa_validation_map(records: list[Any]) -> dict[str, dict[str, Any]]:
    validation: dict[str, dict[str, Any]] = {}
    candidates: list[tuple[str, str, str, str]] = []
    checked_at = datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec="seconds")

    for record in records:
        record_id = str(getattr(record, "id", "") or "")
        status = _normalize_recolha_status(getattr(record, "status_caixa_noturno", ""))
        if status != "Recolhido":
            validation[record_id] = {
                "status": "aguardando",
                "label": "Aguardando fechamento",
                "checked_at": checked_at,
            }
            continue
        filial = _recolha_record_filial(record)
        nb = normalize_numeric_code(getattr(record, "nb", "") or "")
        comodato_number = _extract_recolha_comodato_number(getattr(record, "comodato", "") or "")
        if not filial or not nb or not comodato_number:
            validation[record_id] = {
                "status": "sem_numero",
                "label": "Sem numero para validar",
                "checked_at": checked_at,
            }
            continue
        candidates.append((record_id, filial, nb, comodato_number))

    if not candidates:
        return validation

    try:
        pending_keys = comodatos_query_service.pending_comodato_keys_for_clients(
            [(filial, nb) for _, filial, nb, _ in candidates]
        )
    except Exception as exc:
        logger.warning("Falha ao validar baixa de recolhas na base de comodatos: %s", exc)
        for record_id, _, _, _ in candidates:
            validation[record_id] = {
                "status": "erro",
                "label": "Validacao indisponivel",
                "checked_at": checked_at,
            }
        return validation

    for record_id, filial, nb, comodato_number in candidates:
        if (filial, nb, comodato_number) in pending_keys:
            validation[record_id] = {
                "status": "pendente",
                "label": "Ainda consta na base",
                "checked_at": checked_at,
            }
        else:
            validation[record_id] = {
                "status": "baixado",
                "label": "Baixado na base",
                "checked_at": checked_at,
            }
    return validation


def _resolve_recolha_solicitante_nome(record: Any, cache: dict[str, str] | None = None) -> str:
    saved_name = str(getattr(record, "solicitante_nome", "") or "").strip()
    if saved_name:
        return saved_name
    raw_solicitante = str(getattr(record, "solicitante", "") or "").strip()
    if not raw_solicitante:
        return ""
    cache_key = "".join(char for char in raw_solicitante if char.isdigit()) or raw_solicitante
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    try:
        user = access_control.get_user(raw_solicitante)
    except Exception:
        user = None
    resolved_name = str((user or {}).get("name") or "").strip()
    if cache is not None:
        cache[cache_key] = resolved_name
    return resolved_name


def _serialize_recolha_request(
    record: Any,
    baixa_validation: dict[str, Any] | None = None,
    requester_name_cache: dict[str, str] | None = None,
) -> dict[str, Any]:
    comodato = str(record.comodato or "")
    return {
        "id": str(record.id or ""),
        "criado_em": str(record.criado_em or ""),
        "criado_em_iso": _recolha_created_at_iso(str(record.criado_em or "")),
        "filial": _recolha_record_filial(record),
        "solicitante": str(record.solicitante or ""),
        "solicitante_nome": _resolve_recolha_solicitante_nome(record, requester_name_cache),
        "revenda": str(record.revenda or ""),
        "data": str(record.data or ""),
        "setor": str(record.setor or ""),
        "cidade": str(record.cidade or ""),
        "rn": str(record.rn or ""),
        "nb": str(record.nb or ""),
        "comodato": comodato,
        "comodato_numero": _extract_recolha_comodato_number(comodato),
        "obs": str(record.obs or ""),
        "lancado_faturista": str(record.lancado_faturista or ""),
        "motorista_faturista": str(record.motorista_faturista or ""),
        "placa_faturista": str(record.placa_faturista or ""),
        "mapa_faturista": str(record.mapa_faturista or ""),
        "status_caixa_noturno": str(record.status_caixa_noturno or ""),
        "motivo_caixa_noturno": str(record.motivo_caixa_noturno or ""),
        "baixa_validacao": baixa_validation or {},
    }


def _recolha_status_bucket(record: Any) -> str:
    status = _normalize_recolha_status(getattr(record, "status_caixa_noturno", ""))
    lancado = _normalize_recolha_status(getattr(record, "lancado_faturista", ""))
    comparable_status = "".join(
        char for char in unicodedata.normalize("NFD", status.lower()) if unicodedata.category(char) != "Mn"
    )
    if comparable_status == "recolhido":
        return "recolhidas"
    if comparable_status == "nao recolhido":
        return "nao_recolhidas"
    if lancado == "Ok":
        return "lancadas"
    return "abertas"


def _recolha_created_at_iso(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return ""


def _normalize_label_key(value: str) -> str:
    text = "".join(
        char for char in unicodedata.normalize("NFD", str(value or "").strip().lower())
        if unicodedata.category(char) != "Mn"
    )
    return "".join(char for char in text if char.isalnum())


def _recolha_record_filial(record: Any) -> str:
    raw_revenda = str(getattr(record, "revenda", "") or "").strip()
    direct_code = normalize_numeric_code(raw_revenda)
    if direct_code:
        return direct_code
    label_map = {_normalize_label_key(label): code for code, label in FILIAL_LABELS.items()}
    return label_map.get(_normalize_label_key(raw_revenda), "")


def _panel_context_allows_recolha(context: dict[str, Any] | None, record: Any) -> bool:
    if not context or bool(context.get("is_admin")):
        return True
    allowed_filiais = {str(filial).strip() for filial in context.get("filiais", ()) if str(filial).strip()}
    record_filial = _recolha_record_filial(record)
    return bool(record_filial and record_filial in allowed_filiais)


def _panel_context_allowed_report_scopes(context: dict[str, Any] | None) -> tuple[list[str] | None, list[str] | None]:
    if not context or bool(context.get("is_admin")):
        return None, None
    allowed_filiais = [str(filial).strip() for filial in context.get("filiais", ()) if str(filial).strip()]
    return allowed_filiais, None


def _parse_localized_decimal(value: Any) -> Decimal:
    raw = str(value or "").strip()
    if not raw:
        return Decimal("0")
    raw = raw.replace("R$", "").replace("+", "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _sum_localized_decimal(values: Any) -> Decimal:
    return sum((_parse_localized_decimal(value) for value in values), Decimal("0"))


def _format_decimal_br(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _format_box_total(value: Decimal) -> str:
    return str(int(value.to_integral_value()))


CRITICA_DASHBOARD_PROBLEM_LABELS = {
    "ocorrencia": "Ocorrencia do relatorio",
    "pedido_duplicado": "Pedido duplicado",
    "produto_duplicado": "Produto duplicado no pedido",
    "preco": "Preco divergente",
    "sem_dprecos": "Produto sem DPrecos",
    "pedido_acima_media": "Pedido acima da media",
    "inadimplente": "Cliente inadimplente",
    "multipack": "Multipack fora da segmentacao",
    "mapa_buffer": "Mapa 1 / buffer",
    "mapa_fora": "Mapa fora do vendedor",
    "condicao": "Cond. pag. divergente",
    "limite": "Estouro de limite",
    "outros": "Outros problemas",
}


def _format_money_br(value: Decimal) -> str:
    return f"R$ {_format_decimal_br(value)}"


def _parse_admin_critica_date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data da critica invalida. Use AAAA-MM-DD.") from exc


def _normalize_admin_filter_values(values: str | list[str] | None) -> set[str]:
    if values is None:
        return set()
    raw_values = values if isinstance(values, list) else [values]
    normalized: set[str] = set()
    for value in raw_values:
        for part in str(value or "").split(","):
            text = part.strip()
            if text:
                normalized.add(text)
    return normalized


def _normalize_search_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").strip().lower())
    ascii_only = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", ascii_only).strip()


def _critica_record_problem_keys(record: Any) -> set[str]:
    labels = tuple(str(label or "").strip() for label in getattr(record, "problemas", ()) if str(label or "").strip())
    normalized_labels = _normalize_search_text(" ".join(labels))
    keys: set[str] = set()
    if str(getattr(record, "critica_text", "") or "").strip() or str(getattr(record, "ocorrencia_1", "") or "").strip() or str(getattr(record, "ocorrencia_2", "") or "").strip():
        keys.add("ocorrencia")
    if bool(getattr(record, "pedido_cliente_duplicado", False)) or "possivel pedido duplicado" in normalized_labels:
        keys.add("pedido_duplicado")
    if bool(getattr(record, "pedido_produto_duplicado", False)) or "produto repetido" in normalized_labels:
        keys.add("produto_duplicado")
    if "produto sem referencia" in normalized_labels or "sem dprecos" in normalized_labels:
        keys.add("sem_dprecos")
    if "preco" in normalized_labels and "sem dprecos" not in normalized_labels and "sem referencia" not in normalized_labels:
        keys.add("preco")
    if bool(getattr(record, "order_above_average", False)) or "acima da media" in normalized_labels:
        keys.add("pedido_acima_media")
    if _parse_localized_decimal(getattr(record, "inad_total_vencido", "0")) > 0 or "vencido em aberto" in normalized_labels:
        keys.add("inadimplente")
    if bool(getattr(record, "multipack_item", False)) and not bool(getattr(record, "multipack_allowed", True)):
        keys.add("multipack")
    map_status = str(getattr(record, "map_status", "") or "").strip().lower()
    if map_status == "buffer" or "mapa 1" in normalized_labels or "buffer" in normalized_labels:
        keys.add("mapa_buffer")
    if map_status == "fora" or "fora do mapa" in normalized_labels:
        keys.add("mapa_fora")
    if bool(getattr(record, "cond_divergente", False)) or "condicao de pagamento" in normalized_labels:
        keys.add("condicao")
    if _parse_localized_decimal(getattr(record, "limit_exceeded_amount", "0")) > 0 or "ultrapassa o limite" in normalized_labels:
        keys.add("limite")
    if labels and not keys:
        keys.add("outros")
    return keys


def _critica_order_rows_from_records(records: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for index, record in enumerate(records):
        filial = str(getattr(record, "filial", "") or "").strip()
        pedido = str(getattr(record, "pedido", "") or "").strip() or f"sem-pedido-{index}"
        key = (filial, pedido)
        problem_keys = _critica_record_problem_keys(record)
        problem_labels = [
            str(label or "").strip()
            for label in getattr(record, "problemas", ())
            if str(label or "").strip()
        ]
        entry = grouped.setdefault(
            key,
            {
                "filial": filial,
                "pedido": pedido,
                "data_pedido": _serialize_admin_import_value(getattr(record, "data_pedido", None)),
                "operation_name": str(getattr(record, "operation_name", "") or "").strip(),
                "movement_operation_name": str(getattr(record, "movement_operation_name", "") or "").strip(),
                "setor": str(getattr(record, "setor", "") or "").strip(),
                "seller": str(getattr(record, "seller_code", "") or getattr(record, "vendedor_codigo", "") or "").strip(),
                "manager": str(getattr(record, "manager_code", "") or getattr(record, "codigo_gv", "") or "").strip(),
                "cod_pdv": str(getattr(record, "cod_pdv", "") or "").strip(),
                "nome_pdv": str(getattr(record, "nome_pdv", "") or "").strip(),
                "cidade": str(getattr(record, "client_cidade", "") or "").strip(),
                "bairro": str(getattr(record, "client_bairro", "") or "").strip(),
                "origem": str(getattr(record, "origem_pedido", "") or "").strip(),
                "status_pedido": str(getattr(record, "status_pedido", "") or "").strip(),
                "total_pedido_decimal": Decimal("0"),
                "item_count": 0,
                "problem_item_count": 0,
                "problem_keys": set(),
                "problem_labels": [],
                "problem_products": [],
                "inad_total_vencido_decimal": Decimal("0"),
                "limit_exceeded_decimal": Decimal("0"),
                "avg_order_value_decimal": Decimal("0"),
                "hectolitros_decimal": Decimal("0"),
                "nab_tt_hectolitros_decimal": Decimal("0"),
                "high_end_hectolitros_decimal": Decimal("0"),
                "cerveja_tt_hectolitros_decimal": Decimal("0"),
                "refri_zero_hectolitros_decimal": Decimal("0"),
                "cerveja_rgb_hectolitros_decimal": Decimal("0"),
                "cerveja_ow_hectolitros_decimal": Decimal("0"),
                "marketplace_tt_hectolitros_decimal": Decimal("0"),
                "search_text_parts": [],
            },
        )
        total_pedido = _parse_localized_decimal(getattr(record, "total_pedido", "0"))
        if total_pedido:
            entry["total_pedido_decimal"] = total_pedido
        entry["item_count"] += 1
        if problem_keys:
            entry["problem_item_count"] += 1
        entry["problem_keys"].update(problem_keys)
        entry["problem_labels"].extend(problem_labels)
        if problem_keys:
            product = " ".join(
                str(value or "").strip()
                for value in (getattr(record, "produto_codigo", ""), getattr(record, "produto_descricao", ""))
                if str(value or "").strip()
            )
            if product:
                entry["problem_products"].append(product)
        entry["inad_total_vencido_decimal"] = max(
            entry["inad_total_vencido_decimal"],
            _parse_localized_decimal(getattr(record, "inad_total_vencido", "0")),
        )
        entry["limit_exceeded_decimal"] = max(
            entry["limit_exceeded_decimal"],
            _parse_localized_decimal(getattr(record, "limit_exceeded_amount", "0")),
        )
        entry["avg_order_value_decimal"] = max(
            entry["avg_order_value_decimal"],
            _parse_localized_decimal(getattr(record, "avg_order_value_3m", "0")),
        )
        item_hectolitros = _parse_localized_decimal(getattr(record, "hectolitros", "0"))
        entry["hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_nab_tt", False)):
            entry["nab_tt_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_high_end", False)):
            entry["high_end_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_cerveja_tt", False)):
            entry["cerveja_tt_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_refri_zero", False)):
            entry["refri_zero_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_cerveja_rgb", False)):
            entry["cerveja_rgb_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_cerveja_ow", False)):
            entry["cerveja_ow_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_marketplace_tt", False)):
            entry["marketplace_tt_hectolitros_decimal"] += item_hectolitros
        entry["search_text_parts"].extend(
            [
                filial,
                pedido,
                entry["operation_name"],
                entry["movement_operation_name"],
                entry["setor"],
                entry["seller"],
                entry["manager"],
                entry["cod_pdv"],
                entry["nome_pdv"],
                entry["cidade"],
                entry["bairro"],
                entry["origem"],
                " ".join(problem_labels),
            ]
        )

    rows: list[dict[str, Any]] = []
    for entry in grouped.values():
        labels = _dedupe_texts(entry["problem_labels"])
        products = _dedupe_texts(entry["problem_products"])
        problem_keys = sorted(entry["problem_keys"], key=lambda key: CRITICA_DASHBOARD_PROBLEM_LABELS.get(key, key))
        total_pedido = entry["total_pedido_decimal"]
        rows.append(
            {
                "filial": entry["filial"],
                "pedido": entry["pedido"],
                "data_pedido": entry["data_pedido"],
                "operation_name": entry["operation_name"],
                "movement_operation_name": entry["movement_operation_name"],
                "setor": entry["setor"],
                "seller": entry["seller"],
                "manager": entry["manager"],
                "cod_pdv": entry["cod_pdv"],
                "nome_pdv": entry["nome_pdv"],
                "cidade": entry["cidade"],
                "bairro": entry["bairro"],
                "origem": entry["origem"],
                "status_pedido": entry["status_pedido"],
                "total_pedido": _format_money_br(total_pedido),
                "total_pedido_value": str(total_pedido),
                "item_count": int(entry["item_count"]),
                "problem_item_count": int(entry["problem_item_count"]),
                "problem_keys": problem_keys,
                "problem_labels": labels,
                "problem_products": products[:6],
                "problem_count": len(problem_keys),
                "inad_total_vencido": _format_money_br(entry["inad_total_vencido_decimal"]),
                "limit_exceeded_amount": _format_money_br(entry["limit_exceeded_decimal"]),
                "avg_order_value": _format_money_br(entry["avg_order_value_decimal"]),
                "hectolitros": _format_decimal_br(entry["hectolitros_decimal"]),
                "hectolitros_value": str(entry["hectolitros_decimal"]),
                "nab_tt_hectolitros_value": str(entry["nab_tt_hectolitros_decimal"]),
                "high_end_hectolitros_value": str(entry["high_end_hectolitros_decimal"]),
                "cerveja_tt_hectolitros_value": str(entry["cerveja_tt_hectolitros_decimal"]),
                "refri_zero_hectolitros_value": str(entry["refri_zero_hectolitros_decimal"]),
                "cerveja_rgb_hectolitros_value": str(entry["cerveja_rgb_hectolitros_decimal"]),
                "cerveja_ow_hectolitros_value": str(entry["cerveja_ow_hectolitros_decimal"]),
                "marketplace_tt_hectolitros_value": str(entry["marketplace_tt_hectolitros_decimal"]),
                "search_text": _normalize_search_text(" ".join(entry["search_text_parts"])),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["problem_count"] else 1,
            -int(row["problem_count"]),
            -_parse_localized_decimal(row["total_pedido_value"]),
            _sort_numeric_text(row["filial"]),
            _sort_numeric_text(row["pedido"]),
        )
    )
    return rows


def _dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = _normalize_search_text(text)
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _sort_numeric_text(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    return (int(text), text) if text.isdigit() else (999999, text)


def _critica_order_matches_filters(
    row: dict[str, Any],
    *,
    operation: set[str],
    sector: set[str],
    seller: set[str],
    manager: set[str],
    city: set[str],
    district: set[str],
    origin: set[str],
    problem: set[str],
    search: str,
    only_problems: bool,
) -> bool:
    if only_problems and not row.get("problem_keys"):
        return False
    if operation and str(row.get("filial") or "").strip() not in operation:
        return False
    if sector and str(row.get("setor") or "").strip() not in sector:
        return False
    if seller and str(row.get("seller") or "").strip() not in seller:
        return False
    if manager and str(row.get("manager") or "").strip() not in manager:
        return False
    if city and str(row.get("cidade") or "").strip() not in city:
        return False
    if district and str(row.get("bairro") or "").strip() not in district:
        return False
    if origin and str(row.get("origem") or "").strip() not in origin:
        return False
    if problem and not (set(row.get("problem_keys") or []) & problem):
        return False
    if search and search not in str(row.get("search_text") or ""):
        return False
    return True


def _critica_option_items(
    rows: list[dict[str, Any]],
    *,
    value_key: str,
    label_factory: Any | None = None,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for row in rows:
        value = str(row.get(value_key) or "").strip()
        if not value:
            continue
        counts[value] += 1
        labels.setdefault(value, label_factory(row, value) if label_factory else value)
    return [
        {"value": value, "label": labels.get(value, value), "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (_sort_numeric_text(item[0]), labels.get(item[0], item[0])))
    ]


def _critica_problem_option_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key in row.get("problem_keys") or []:
            counts[str(key)] += 1
    return [
        {"value": key, "label": CRITICA_DASHBOARD_PROBLEM_LABELS.get(key, key), "count": counts[key]}
        for key in sorted(counts, key=lambda item: (-counts[item], CRITICA_DASHBOARD_PROBLEM_LABELS.get(item, item)))
    ]


def _critica_dashboard_options(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "operations": _critica_option_items(
            rows,
            value_key="filial",
            label_factory=lambda row, value: f"{value} - {row.get('operation_name') or FILIAL_LABELS.get(value, '')}".strip(" -"),
        ),
        "sectors": _critica_option_items(rows, value_key="setor"),
        "sellers": _critica_option_items(rows, value_key="seller"),
        "managers": _critica_option_items(rows, value_key="manager"),
        "cities": _critica_option_items(rows, value_key="cidade"),
        "districts": _critica_option_items(rows, value_key="bairro"),
        "origins": _critica_option_items(rows, value_key="origem"),
        "problems": _critica_problem_option_items(rows),
    }


def _critica_dashboard_slicer_options(
    all_rows: list[dict[str, Any]],
    filters: dict[str, Any],
    *,
    only_problems: bool,
) -> dict[str, list[dict[str, Any]]]:
    def rows_for(omit: str) -> list[dict[str, Any]]:
        return [
            row
            for row in all_rows
            if _critica_order_matches_filters(
                row,
                operation=set() if omit == "operation" else filters["operation"],
                sector=set() if omit == "sector" else filters["sector"],
                seller=set() if omit == "seller" else filters["seller"],
                manager=set() if omit == "manager" else filters["manager"],
                city=set() if omit == "city" else filters["city"],
                district=set() if omit == "district" else filters["district"],
                origin=set() if omit == "origin" else filters["origin"],
                problem=set() if omit == "problem" else filters["problem"],
                search=filters["search"],
                only_problems=only_problems,
            )
        ]

    return {
        "operations": _critica_option_items(
            rows_for("operation"),
            value_key="filial",
            label_factory=lambda row, value: f"{value} - {row.get('operation_name') or FILIAL_LABELS.get(value, '')}".strip(" -"),
        ),
        "sectors": _critica_option_items(rows_for("sector"), value_key="setor"),
        "sellers": _critica_option_items(rows_for("seller"), value_key="seller"),
        "managers": _critica_option_items(rows_for("manager"), value_key="manager"),
        "cities": _critica_option_items(rows_for("city"), value_key="cidade"),
        "districts": _critica_option_items(rows_for("district"), value_key="bairro"),
        "origins": _critica_option_items(rows_for("origin"), value_key="origem"),
        "problems": _critica_problem_option_items(rows_for("problem")),
    }


def _critica_problem_rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key in row.get("problem_keys") or []:
            counts[str(key)] += 1
    return [
        {"key": key, "label": CRITICA_DASHBOARD_PROBLEM_LABELS.get(key, key), "orders": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], CRITICA_DASHBOARD_PROBLEM_LABELS.get(item[0], item[0])))
    ]


def _critica_group_rank(rows: list[dict[str, Any]], *, key: str, label: str, limit: int = 8) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip() or "-"
        entry = grouped.setdefault(value, {"value": value, "label": value, "orders": 0, "problem_orders": 0, "total_decimal": Decimal("0")})
        entry["orders"] += 1
        if row.get("problem_keys"):
            entry["problem_orders"] += 1
        entry["total_decimal"] += _parse_localized_decimal(row.get("total_pedido_value"))
    ranked = sorted(grouped.values(), key=lambda item: (-int(item["problem_orders"]), -item["total_decimal"], item["label"]))[:limit]
    return [
        {
            "value": item["value"],
            "label": f"{label} {item['label']}" if label else item["label"],
            "orders": item["orders"],
            "problem_orders": item["problem_orders"],
            "total": _format_money_br(item["total_decimal"]),
        }
        for item in ranked
    ]


def _critica_client_rank(rows: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("filial") or ""), str(row.get("cod_pdv") or ""))
        entry = grouped.setdefault(
            key,
            {
                "filial": row.get("filial") or "",
                "cod_pdv": row.get("cod_pdv") or "",
                "nome_pdv": row.get("nome_pdv") or "-",
                "orders": 0,
                "problem_orders": 0,
                "total_decimal": Decimal("0"),
            },
        )
        entry["orders"] += 1
        if row.get("problem_keys"):
            entry["problem_orders"] += 1
        entry["total_decimal"] += _parse_localized_decimal(row.get("total_pedido_value"))
    ranked = sorted(grouped.values(), key=lambda item: (-int(item["problem_orders"]), -item["total_decimal"], item["nome_pdv"]))[:limit]
    return [
        {
            "filial": item["filial"],
            "cod_pdv": item["cod_pdv"],
            "label": item["nome_pdv"],
            "orders": item["orders"],
            "problem_orders": item["problem_orders"],
            "total": _format_money_br(item["total_decimal"]),
        }
        for item in ranked
    ]


def _critica_dashboard_recommendations(problem_rank: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    rank_by_key = {item["key"]: int(item.get("orders") or 0) for item in problem_rank}
    recommendations: list[dict[str, str]] = []
    if rank_by_key.get("limite", 0) or rank_by_key.get("condicao", 0):
        recommendations.append(
            {
                "title": "Validar credito antes de faturar",
                "detail": "Priorize pedidos com estouro de limite ou condicao divergente, principalmente quando a operacao for 51.",
            }
        )
    if rank_by_key.get("pedido_duplicado", 0) or rank_by_key.get("produto_duplicado", 0):
        recommendations.append(
            {
                "title": "Conferir duplicidades por cliente",
                "detail": "Compare pedidos do mesmo NB em datas proximas e confirme se nao houve redigitacao do mesmo mix.",
            }
        )
    if rank_by_key.get("preco", 0) or rank_by_key.get("sem_dprecos", 0):
        recommendations.append(
            {
                "title": "Tratar preco e cadastro de produto",
                "detail": "Separe divergencias de preco real de produto sem DPrecos para evitar retrabalho na critica manual.",
            }
        )
    if rank_by_key.get("mapa_buffer", 0) or rank_by_key.get("mapa_fora", 0):
        recommendations.append(
            {
                "title": "Revisar origem do pedido",
                "detail": "Pedidos em buffer ou fora do mapa indicam falha de digitacao, rota ou setor e devem ser cobrados com o responsavel.",
            }
        )
    if rank_by_key.get("inadimplente", 0):
        recommendations.append(
            {
                "title": "Cruzar critica com cobranca",
                "detail": "Clientes inadimplentes com pedido novo devem ir para validacao comercial antes de seguir o fluxo normal.",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "title": "Sem concentracao critica nos filtros",
                "detail": "Use filtros por operacao, setor ou problema para encontrar bolsões especificos de erro.",
            }
        )
    if len(rows) > 300:
        recommendations.append(
            {
                "title": "Quebrar a fila de trabalho",
                "detail": "Para operacao grande, filtre por setor ou GV e trate primeiro os pedidos com maior valor total.",
            }
        )
    return recommendations[:5]


def _build_admin_critica_dashboard(
    context: dict[str, Any] | None = None,
    *,
    target_date: date | None = None,
    limit: int = 200,
    operation: str | list[str] | None = None,
    sector: str | list[str] | None = None,
    seller: str | list[str] | None = None,
    manager: str | list[str] | None = None,
    city: str | list[str] | None = None,
    district: str | list[str] | None = None,
    origin: str | list[str] | None = None,
    problem: str | list[str] | None = None,
    search: str = "",
    only_problems: bool = True,
) -> dict[str, Any]:
    allowed_sectors, allowed_gv_vdes = _panel_context_allowed_report_scopes(context)
    effective_date = target_date or critica_rn_query_service.latest_date(
        allowed_sectors=allowed_sectors,
        allowed_gv_vdes=allowed_gv_vdes,
    )
    if effective_date is None:
        return {
            "total": 0,
            "limit": limit,
            "summary": {
                "data_pedido": "",
                "pedidos": 0,
                "pedidos_com_problema": 0,
                "clientes": 0,
                "itens": 0,
                "valor_total": "R$ 0,00",
                "taxa_problema": "0,0%",
            },
            "options": _critica_dashboard_options([]),
            "rankings": {"problems": [], "operations": [], "sectors": [], "clients": []},
            "recommendations": _critica_dashboard_recommendations([], []),
            "orders": [],
        }
    data = critica_rn_query_service.get_report_data(
        target_date=effective_date,
        allowed_sectors=allowed_sectors,
        allowed_gv_vdes=allowed_gv_vdes,
        limit=50000,
    )
    all_rows = _critica_order_rows_from_records(data.records)
    filters = {
        "operation": _normalize_admin_filter_values(operation),
        "sector": _normalize_admin_filter_values(sector),
        "seller": _normalize_admin_filter_values(seller),
        "manager": _normalize_admin_filter_values(manager),
        "city": _normalize_admin_filter_values(city),
        "district": _normalize_admin_filter_values(district),
        "origin": _normalize_admin_filter_values(origin),
        "problem": _normalize_admin_filter_values(problem),
        "search": _normalize_search_text(search),
    }
    filtered_rows = [
        row
        for row in all_rows
        if _critica_order_matches_filters(
            row,
            operation=filters["operation"],
            sector=filters["sector"],
            seller=filters["seller"],
            manager=filters["manager"],
            city=filters["city"],
            district=filters["district"],
            origin=filters["origin"],
            problem=filters["problem"],
            search=filters["search"],
            only_problems=only_problems,
        )
    ]
    total_value = sum((_parse_localized_decimal(row.get("total_pedido_value")) for row in filtered_rows), Decimal("0"))
    total_hectolitros = sum((_parse_localized_decimal(row.get("hectolitros_value")) for row in filtered_rows), Decimal("0"))
    nab_tt_hectolitros = sum((_parse_localized_decimal(row.get("nab_tt_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    high_end_hectolitros = sum((_parse_localized_decimal(row.get("high_end_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    cerveja_tt_hectolitros = sum((_parse_localized_decimal(row.get("cerveja_tt_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    refri_zero_hectolitros = sum((_parse_localized_decimal(row.get("refri_zero_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    cerveja_rgb_hectolitros = sum((_parse_localized_decimal(row.get("cerveja_rgb_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    cerveja_ow_hectolitros = sum((_parse_localized_decimal(row.get("cerveja_ow_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    marketplace_tt_hectolitros = sum((_parse_localized_decimal(row.get("marketplace_tt_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    problem_orders = sum(1 for row in filtered_rows if row.get("problem_keys"))
    client_count = len({(row.get("filial"), row.get("cod_pdv")) for row in filtered_rows if row.get("filial") and row.get("cod_pdv")})
    problem_rank = _critica_problem_rank(filtered_rows)
    safe_limit = max(1, min(int(limit or 200), 1000))
    return {
        "total": len(filtered_rows),
        "limit": safe_limit,
        "summary": {
            "data_pedido": effective_date.isoformat(),
            "planilha_atualizada_em": data.summary.planilha_atualizada_em,
            "pedidos": len(filtered_rows),
            "pedidos_base": len(all_rows),
            "pedidos_com_problema": problem_orders,
            "clientes": client_count,
            "itens": sum(int(row.get("item_count") or 0) for row in filtered_rows),
            "valor_total": _format_money_br(total_value),
            "total_hectolitros": _format_decimal_br(total_hectolitros),
            "nab_tt_hectolitros": _format_decimal_br(nab_tt_hectolitros),
            "high_end_hectolitros": _format_decimal_br(high_end_hectolitros),
            "cerveja_tt_hectolitros": _format_decimal_br(cerveja_tt_hectolitros),
            "refri_zero_hectolitros": _format_decimal_br(refri_zero_hectolitros),
            "cerveja_rgb_hectolitros": _format_decimal_br(cerveja_rgb_hectolitros),
            "cerveja_ow_hectolitros": _format_decimal_br(cerveja_ow_hectolitros),
            "marketplace_tt_hectolitros": _format_decimal_br(marketplace_tt_hectolitros),
            "ticket_medio": _format_money_br(total_value / Decimal(len(filtered_rows))) if filtered_rows else "R$ 0,00",
            "taxa_problema": _format_decimal_br((Decimal(problem_orders) / Decimal(len(filtered_rows)) * Decimal("100")) if filtered_rows else Decimal("0")) + "%",
            "maior_problema": problem_rank[0]["label"] if problem_rank else "-",
        },
        "options": _critica_dashboard_slicer_options(all_rows, filters, only_problems=only_problems),
        "rankings": {
            "problems": problem_rank[:12],
            "operations": _critica_group_rank(filtered_rows, key="filial", label="Operacao", limit=8),
            "sectors": _critica_group_rank(filtered_rows, key="setor", label="Setor", limit=8),
            "clients": _critica_client_rank(filtered_rows, limit=8),
        },
        "recommendations": _critica_dashboard_recommendations(problem_rank, filtered_rows),
        "orders": filtered_rows[:safe_limit],
    }


def _build_admin_giro_recolha_dashboard(
    context: dict[str, Any] | None = None,
    *,
    limit: int = 200,
    min_gap: str = "1",
    operation: str | list[str] | None = None,
    city: str | list[str] | None = None,
    district: str | list[str] | None = None,
    seller: str | list[str] | None = None,
    manager: str | list[str] | None = None,
    visit_day: str | list[str] | None = None,
    zero_only: bool = False,
) -> dict[str, Any]:
    allowed_sectors, allowed_gv_vdes = _panel_context_allowed_report_scopes(context)
    records = giro_query_service.list_recolha_opportunities(
        allowed_sectors=allowed_sectors,
        allowed_gv_vdes=allowed_gv_vdes,
        limit=limit,
        min_gap=min_gap,
        operation=operation,
        city=city,
        district=district,
        seller=seller,
        manager=manager,
        visit_day=visit_day,
        zero_only=zero_only,
    )
    rows = [record.to_dict() for record in records]
    total_gap = _sum_localized_decimal(row.get("gap_caixas") for row in rows)
    zero_clients = sum(
        1
        for row in rows
        if str(row.get("giro_litrinho") or "") == "ZERO"
        or str(row.get("giro_inteira") or "") == "ZERO"
        or str(row.get("giro_litrao") or "") == "ZERO"
    )
    return {
        "total": len(rows),
        "limit": limit,
        "min_gap": str(min_gap or "1"),
        "summary": {
            "clientes": len(rows),
            "clientes_zero": zero_clients,
            "gap_total": _format_box_total(total_gap),
            "maior_gap": rows[0].get("gap_caixas", "0") if rows else "0",
        },
        "records": rows,
    }


def _build_admin_giro_recolha_filter_options(
    context: dict[str, Any] | None = None,
    *,
    min_gap: str = "1",
    operation: str | list[str] | None = None,
    city: str | list[str] | None = None,
    district: str | list[str] | None = None,
    seller: str | list[str] | None = None,
    manager: str | list[str] | None = None,
    visit_day: str | list[str] | None = None,
    zero_only: bool = False,
) -> dict[str, Any]:
    allowed_sectors, allowed_gv_vdes = _panel_context_allowed_report_scopes(context)
    options = giro_query_service.list_recolha_filter_options(
        allowed_sectors=allowed_sectors,
        allowed_gv_vdes=allowed_gv_vdes,
        min_gap=min_gap,
        operation=operation,
        city=city,
        district=district,
        seller=seller,
        manager=manager,
        visit_day=visit_day,
        zero_only=zero_only,
    )
    return {"options": options}


def _route_day_sort_key(value: str) -> tuple[int, str]:
    normalized = str(value or "").upper()
    order = {
        "SEG": 1,
        "TER": 2,
        "QUA": 3,
        "QUI": 4,
        "SEX": 5,
        "SAB": 6,
        "DOM": 7,
    }
    for token, index in order.items():
        if token in normalized:
            return index, normalized
    return 99, normalized


def _build_admin_giro_recolha_routes(
    context: dict[str, Any] | None = None,
    *,
    limit: int = 500,
    min_gap: str = "1",
    operation: str | list[str] | None = None,
    city: str | list[str] | None = None,
    district: str | list[str] | None = None,
    seller: str | list[str] | None = None,
    manager: str | list[str] | None = None,
    visit_day: str | list[str] | None = None,
    zero_only: bool = False,
    max_route_size: int = 12,
) -> dict[str, Any]:
    allowed_sectors, allowed_gv_vdes = _panel_context_allowed_report_scopes(context)
    records = giro_query_service.list_recolha_opportunities(
        allowed_sectors=allowed_sectors,
        allowed_gv_vdes=allowed_gv_vdes,
        limit=limit,
        min_gap=min_gap,
        operation=operation,
        city=city,
        district=district,
        seller=seller,
        manager=manager,
        visit_day=visit_day,
        zero_only=zero_only,
    )
    rows = [record.to_dict() for record in records]
    max_size = max(1, min(int(max_route_size or 12), 50))

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("filial") or "").strip() or "Sem operacao",
            str(row.get("visit_day") or "").strip() or "Sem dia de visita",
            str(row.get("cidade") or "").strip() or "Sem cidade",
        )
        grouped.setdefault(key, []).append(row)

    routes: list[dict[str, Any]] = []
    sequence = 1
    for key in sorted(grouped, key=lambda item: (item[0], _route_day_sort_key(item[1]), item[2])):
        items = sorted(
            grouped[key],
            key=lambda row: (
                str(row.get("bairro") or ""),
                -_parse_localized_decimal(row.get("gap_caixas")),
                -_parse_localized_decimal(row.get("media_faturamento_pedido")),
                str(row.get("nome") or ""),
            ),
        )
        for start in range(0, len(items), max_size):
            chunk = items[start : start + max_size]
            total_gap = _sum_localized_decimal(row.get("gap_caixas") for row in chunk)
            total_boxes = _sum_localized_decimal(row.get("total_caixas") for row in chunk)
            total_revenue = _sum_localized_decimal(row.get("faturamento_total") for row in chunk)
            sellers = sorted({str(row.get("seller_code") or row.get("setor") or "").strip() for row in chunk if str(row.get("seller_code") or row.get("setor") or "").strip()})
            managers = sorted({str(row.get("manager_code") or "").strip() for row in chunk if str(row.get("manager_code") or "").strip()})
            neighborhoods = sorted({str(row.get("bairro") or "").strip() for row in chunk if str(row.get("bairro") or "").strip()})
            route_rows = []
            for index, row in enumerate(chunk, start=1):
                route_rows.append(
                    {
                        "sequence": index,
                        "filial": row.get("filial"),
                        "cod_pdv": row.get("cod_pdv"),
                        "nome": row.get("nome"),
                        "cidade": row.get("cidade"),
                        "bairro": row.get("bairro"),
                        "visit_day": row.get("visit_day"),
                        "total_caixas": row.get("total_caixas"),
                        "real_caixas": row.get("real_caixas"),
                        "gap_caixas": row.get("gap_caixas"),
                        "gap_litrinho": row.get("gap_litrinho"),
                        "gap_inteira": row.get("gap_inteira"),
                        "gap_litrao": row.get("gap_litrao"),
                        "giro_litrinho": row.get("giro_litrinho"),
                        "giro_inteira": row.get("giro_inteira"),
                        "giro_litrao": row.get("giro_litrao"),
                        "media_faturamento_pedido": row.get("media_faturamento_pedido"),
                        "faturamento_total": row.get("faturamento_total"),
                        "seller": row.get("seller_code") or row.get("setor"),
                        "manager": row.get("manager_code"),
                        "command": f"recolha {row.get('filial') or ''} {row.get('cod_pdv') or ''}".strip(),
                    }
                )
            routes.append(
                {
                    "id": f"R{sequence:03d}",
                    "operation": key[0],
                    "seller": sellers[0] if len(sellers) == 1 else ("Varios" if sellers else "-"),
                    "sellers": sellers,
                    "manager": managers[0] if len(managers) == 1 else ("Varios" if managers else "-"),
                    "managers": managers,
                    "visit_day": key[1],
                    "city": key[2],
                    "neighborhoods": neighborhoods,
                    "neighborhood_sequence": " -> ".join(neighborhoods),
                    "pdvs": len(chunk),
                    "total_caixas": _format_box_total(total_boxes),
                    "gap_total": _format_box_total(total_gap),
                    "faturamento_total": f"R$ {_format_decimal_br(total_revenue)}",
                    "items": route_rows,
                }
            )
            sequence += 1

    routes.sort(key=lambda route: (_route_day_sort_key(route.get("visit_day", "")), route.get("operation", ""), route.get("city", ""), str(route.get("neighborhood_sequence") or ""), -_parse_localized_decimal(route.get("gap_total"))))
    for index, route in enumerate(routes, start=1):
        route["id"] = f"R{index:03d}"
    return {
        "total": len(routes),
        "summary": {
            "rotas": len(routes),
            "pdvs": len(rows),
            "gap_total": _format_box_total(_sum_localized_decimal(row.get("gap_caixas") for row in rows)),
            "total_caixas": _format_box_total(_sum_localized_decimal(row.get("total_caixas") for row in rows)),
            "max_pdvs_por_rota": max_size,
        },
        "routes": routes,
    }


def _list_admin_recolhas(context: dict[str, Any] | None = None) -> dict[str, Any]:
    recolha_request_service.normalize_grouped_comodato_requests()
    records = recolha_request_service.list_all_requests()
    records = [record for record in records if _panel_context_allows_recolha(context, record)]
    baixa_validation_map = _build_recolha_baixa_validation_map(records)
    requester_name_cache: dict[str, str] = {}
    grouped: dict[str, dict[str, Any]] = {}
    for record in records:
        revenda = str(record.revenda or "").strip() or "Sem operacao"
        bucket = grouped.setdefault(
            revenda,
            {
                "revenda": revenda,
                "total": 0,
                "abertas": 0,
                "lancadas": 0,
                "recolhidas": 0,
                "nao_recolhidas": 0,
                "records": [],
            },
        )
        bucket["total"] += 1
        bucket[_recolha_status_bucket(record)] += 1
        bucket["records"].append(
            _serialize_recolha_request(
                record,
                baixa_validation_map.get(str(record.id or "")),
                requester_name_cache=requester_name_cache,
            )
        )

    operations = sorted(grouped.values(), key=lambda item: str(item["revenda"]).lower())
    return {"total": len(records), "operations": operations}


def _parse_admin_recolha_export_date(value: str | None, *, label: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} invalida. Use AAAA-MM-DD.") from exc


def _recolha_record_created_date(record: Any) -> date | None:
    iso = _recolha_created_at_iso(str(getattr(record, "criado_em", "") or ""))
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        return None


def _export_admin_recolhas_csv(
    context: dict[str, Any] | None = None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[bytes, int, str]:
    recolha_request_service.normalize_grouped_comodato_requests()
    start = _parse_admin_recolha_export_date(start_date, label="Data inicial")
    end = _parse_admin_recolha_export_date(end_date, label="Data final")
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="Periodo invalido. A data inicial nao pode ser maior que a final.")

    records = recolha_request_service.list_all_requests()
    records = [record for record in records if _panel_context_allows_recolha(context, record)]
    if start or end:
        filtered_records = []
        for record in records:
            created_date = _recolha_record_created_date(record)
            if created_date is None:
                continue
            if start and created_date < start:
                continue
            if end and created_date > end:
                continue
            filtered_records.append(record)
        records = filtered_records

    csv_bytes = recolha_request_service.export_csv_bytes(records, include_meta=True)
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"relatorio_recolhas_{generated_at}.csv"
    return csv_bytes, len(records), filename


def _update_admin_recolha(
    recolha_id: str,
    payload: AdminRecolhaUpdateRequest,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identifier = str(recolha_id or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="ID da recolha nao informado.")
    current_record = recolha_request_service.find_latest(identifier=identifier)
    if current_record is None:
        raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
    if not _panel_context_allows_recolha(context, current_record):
        raise HTTPException(status_code=403, detail="Recolha fora das filiais liberadas para este financeiro.")

    updates: dict[str, str] = {}
    if payload.lancado_faturista is not None:
        status = _normalize_recolha_status(payload.lancado_faturista)
        updates["lancado_faturista"] = "Ok" if status == "Ok" else "Nok"
    for field_name in ("motorista_faturista", "placa_faturista", "mapa_faturista", "motivo_caixa_noturno"):
        value = getattr(payload, field_name)
        if value is not None:
            updates[field_name] = str(value or "").strip()
    if payload.status_caixa_noturno is not None:
        status = _normalize_recolha_status(payload.status_caixa_noturno)
        updates["status_caixa_noturno"] = status or "Não Recolhido"
        if status == "Recolhido" and payload.motivo_caixa_noturno is None:
            updates["motivo_caixa_noturno"] = ""

    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo de recolha informado para atualizar.")

    record = recolha_request_service.update_latest(identifier=identifier, updates=updates)
    if record is None:
        raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
    return {"record": _serialize_recolha_request(record)}


def _update_admin_recolhas_bulk(
    payload: AdminRecolhaBulkUpdateRequest,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ids: list[str] = []
    seen: set[str] = set()
    for raw_id in payload.ids:
        item = str(raw_id or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ids.append(item)
    if not ids:
        raise HTTPException(status_code=400, detail="Nenhuma recolha selecionada para atualizar.")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="Atualizacao em lote limitada a 500 recolhas por vez.")

    single_payload = AdminRecolhaUpdateRequest(
        lancado_faturista=payload.lancado_faturista,
        motorista_faturista=payload.motorista_faturista,
        placa_faturista=payload.placa_faturista,
        mapa_faturista=payload.mapa_faturista,
        status_caixa_noturno=payload.status_caixa_noturno,
        motivo_caixa_noturno=payload.motivo_caixa_noturno,
    )
    updated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for recolha_id in ids:
        try:
            result = _update_admin_recolha(recolha_id, single_payload, context)
            updated.append(result["record"])
        except HTTPException as exc:
            errors.append({"id": recolha_id, "status_code": exc.status_code, "detail": exc.detail})
    return {"updated": len(updated), "errors": errors, "records": updated}


def _import_admin_recolhas_csv(upload: UploadFile, context: dict[str, Any] | None = None) -> dict[str, Any]:
    filename = str(upload.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Envie um arquivo CSV de recolhas.")
    buffer = io.BytesIO()
    try:
        _copy_upload_with_limit(upload, buffer)
    except HTTPException:
        raise
    finally:
        upload.file.close()

    replace_filter = None if (context is None or bool(context.get("is_admin"))) else (
        lambda record: _panel_context_allows_recolha(context, record)
    )
    try:
        result = recolha_request_service.import_csv_bytes(buffer.getvalue(), replace_filter=replace_filter)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    recolha_request_service.normalize_grouped_comodato_requests()
    return {
        **result,
        "filename": filename,
        "mode": "replace_all" if replace_filter is None else "replace_allowed_filiais",
    }


def _delete_admin_recolha(recolha_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    identifier = str(recolha_id or "").strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="ID da recolha nao informado.")
    current_record = recolha_request_service.find_latest(identifier=identifier)
    if current_record is None:
        raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
    if not _panel_context_allows_recolha(context, current_record):
        raise HTTPException(status_code=403, detail="Recolha fora das filiais liberadas para este financeiro.")

    deleted = recolha_request_service.delete_latest(identifier=identifier)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
    return {"record": _serialize_recolha_request(deleted)}


def _to_positive_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _list_admin_evolution_usage(
    *,
    days: int = 7,
    top_limit: int = 10,
    recent_limit: int = 20,
) -> dict[str, Any]:
    safe_days = _to_positive_int(days, default=7, minimum=1, maximum=30)
    safe_top_limit = _to_positive_int(top_limit, default=10, minimum=1, maximum=5000)
    safe_recent_limit = _to_positive_int(recent_limit, default=20, minimum=5, maximum=50)
    series_days = max(0, safe_days - 1)

    if not settings.access_database_url.strip():
        raise HTTPException(status_code=503, detail="ACCESS_DATABASE_URL nao configurada para o dashboard de uso.")

    audit_schema = str(settings.access_db_schema or "bot_access").strip() or "bot_access"
    audit_table = sql.Identifier(audit_schema, "security_audit_log")
    users_table = sql.Identifier(audit_schema, "users")

    summary_query = sql.SQL(
        """
        SELECT
            COUNT(*) AS total_events,
            COUNT(*) FILTER (WHERE event_type = 'queue' AND decision = 'accepted') AS total_messages,
            COUNT(DISTINCT phone_number) FILTER (WHERE event_type = 'queue' AND decision = 'accepted') AS unique_numbers,
            COUNT(*) FILTER (WHERE event_type = 'processing' AND decision = 'allowed') AS processed_ok,
            COUNT(*) FILTER (WHERE event_type = 'rbac_access' AND decision = 'denied') AS blocked_rbac,
            COUNT(*) FILTER (WHERE event_type = 'processing' AND decision = 'error') AS processing_errors,
            COUNT(*) FILTER (WHERE event_type = 'delivery' AND decision = 'error') AS delivery_errors,
            COUNT(*) FILTER (WHERE event_type = 'queue' AND decision = 'error') AS queue_errors,
            COUNT(*) FILTER (WHERE event_type = 'denied_reply' AND decision = 'sent') AS denied_reply_sent,
            COUNT(*) FILTER (WHERE event_type = 'denied_reply' AND decision = 'suppressed') AS denied_reply_suppressed
        FROM {}
        WHERE channel = 'webhook'
          AND path = '/webhook/evolution'
          AND created_at >= (NOW() - make_interval(days => %s))
        """
    ).format(audit_table)

    daily_query = sql.SQL(
        """
        SELECT
            day::date,
            COUNT(log.id) FILTER (WHERE log.event_type = 'queue' AND log.decision = 'accepted') AS messages,
            COUNT(DISTINCT log.phone_number) FILTER (WHERE log.event_type = 'queue' AND log.decision = 'accepted') AS unique_numbers,
            COUNT(log.id) FILTER (WHERE log.event_type = 'processing' AND log.decision = 'allowed') AS processed_ok,
            COUNT(log.id) FILTER (WHERE log.event_type = 'rbac_access' AND log.decision = 'denied') AS blocked_rbac
        FROM generate_series(
            (CURRENT_DATE - (%s * INTERVAL '1 day'))::date,
            CURRENT_DATE::date,
            INTERVAL '1 day'
        ) AS day
        LEFT JOIN {} AS log
          ON log.created_at >= day::timestamp
         AND log.created_at < (day::timestamp + INTERVAL '1 day')
         AND log.channel = 'webhook'
         AND log.path = '/webhook/evolution'
        GROUP BY day
        ORDER BY day
        """
    ).format(audit_table)

    hourly_query = sql.SQL(
        """
        SELECT
            hour_bucket,
            COUNT(log.id) FILTER (WHERE log.event_type = 'queue' AND log.decision = 'accepted') AS messages
        FROM generate_series(
            date_trunc('hour', NOW()) - INTERVAL '23 hour',
            date_trunc('hour', NOW()),
            INTERVAL '1 hour'
        ) AS hour_bucket
        LEFT JOIN {} AS log
          ON log.created_at >= hour_bucket
         AND log.created_at < (hour_bucket + INTERVAL '1 hour')
         AND log.channel = 'webhook'
         AND log.path = '/webhook/evolution'
        GROUP BY hour_bucket
        ORDER BY hour_bucket
        """
    ).format(audit_table)

    top_numbers_query = sql.SQL(
        """
        WITH ranked_events AS (
            SELECT
                CASE
                    WHEN normalized_candidate = '' THEN 'sem_numero'
                    ELSE normalized_candidate
                END AS normalized_phone,
                MAX(NULLIF(BTRIM(raw_phone), '')) AS sample_phone,
                COUNT(*) AS total_events,
                COUNT(*) FILTER (WHERE event_type = 'queue' AND decision = 'accepted') AS messages,
                COUNT(*) FILTER (WHERE event_type = 'processing' AND decision = 'allowed') AS processed_ok,
                COUNT(*) FILTER (WHERE event_type = 'rbac_access' AND decision = 'denied') AS blocked_rbac
            FROM (
                SELECT
                    log.phone_number AS raw_phone,
                    log.event_type,
                    log.decision,
                    CASE
                        WHEN normalized_base = '' THEN ''
                        WHEN LEFT(normalized_base, 2) = '55'
                         AND LENGTH(normalized_base) = 13
                         AND SUBSTRING(normalized_base, 5, 1) = '9'
                        THEN LEFT(normalized_base, 4) || SUBSTRING(normalized_base, 6)
                        ELSE normalized_base
                    END AS normalized_candidate
                FROM (
                    SELECT
                        phone_number,
                        event_type,
                        decision,
                        CASE
                            WHEN LENGTH(raw_digits) IN (10, 11) AND LEFT(raw_digits, 2) <> '55'
                            THEN '55' || raw_digits
                            ELSE raw_digits
                        END AS normalized_base
                    FROM (
                        SELECT
                            phone_number,
                            event_type,
                            decision,
                            REGEXP_REPLACE(COALESCE(phone_number, ''), '\\D+', '', 'g') AS raw_digits
                        FROM {}
                        WHERE channel = 'webhook'
                          AND path = '/webhook/evolution'
                          AND created_at >= (NOW() - make_interval(days => %s))
                    ) AS base_events
                ) AS log
            ) AS normalized_events
            GROUP BY 1
            HAVING COUNT(*) > 0
            ORDER BY messages DESC, total_events DESC, normalized_phone ASC
            LIMIT %s
        )
        SELECT
            ranked_events.normalized_phone,
            COALESCE(NULLIF(BTRIM(user_name.name), ''), ranked_events.normalized_phone) AS display_name,
            COALESCE(NULLIF(BTRIM(user_name.phone_number), ''), ranked_events.sample_phone, ranked_events.normalized_phone) AS display_phone,
            ranked_events.total_events,
            ranked_events.messages,
            ranked_events.processed_ok,
            ranked_events.blocked_rbac
        FROM ranked_events
        LEFT JOIN LATERAL (
            SELECT usr.name, usr.phone_number
            FROM {} AS usr
            CROSS JOIN LATERAL (
                SELECT REGEXP_REPLACE(COALESCE(usr.phone_number, ''), '\\D+', '', 'g') AS digits
            ) AS digits_src
            CROSS JOIN LATERAL (
                SELECT CASE
                    WHEN LENGTH(digits_src.digits) IN (10, 11) AND LEFT(digits_src.digits, 2) <> '55'
                    THEN '55' || digits_src.digits
                    ELSE digits_src.digits
                END AS base_phone
            ) AS base_src
            WHERE (
                CASE
                    WHEN LEFT(base_src.base_phone, 2) = '55'
                     AND LENGTH(base_src.base_phone) = 13
                     AND SUBSTRING(base_src.base_phone, 5, 1) = '9'
                    THEN LEFT(base_src.base_phone, 4) || SUBSTRING(base_src.base_phone, 6)
                    ELSE base_src.base_phone
                END
            ) = ranked_events.normalized_phone
            ORDER BY usr.updated_at DESC, usr.id DESC
            LIMIT 1
        ) AS user_name ON TRUE
        ORDER BY ranked_events.messages DESC, ranked_events.total_events DESC, ranked_events.normalized_phone ASC
        """
    ).format(audit_table, users_table)

    breakdown_query = sql.SQL(
        """
        SELECT event_type, decision, COUNT(*) AS total
        FROM {}
        WHERE channel = 'webhook'
          AND path = '/webhook/evolution'
          AND created_at >= (NOW() - make_interval(days => %s))
        GROUP BY event_type, decision
        ORDER BY total DESC, event_type ASC, decision ASC
        LIMIT 30
        """
    ).format(audit_table)

    recent_events_query = sql.SQL(
        """
        SELECT created_at, event_type, decision, phone_number, area, reason
        FROM {}
        WHERE channel = 'webhook'
          AND path = '/webhook/evolution'
        ORDER BY created_at DESC
        LIMIT %s
        """
    ).format(audit_table)

    try:
        with psycopg.connect(
            settings.access_database_url,
            connect_timeout=int(settings.access_database_timeout_seconds),
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(summary_query, (safe_days,))
                summary_row = cur.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

                cur.execute(daily_query, (series_days,))
                daily_rows = cur.fetchall()

                cur.execute(hourly_query)
                hourly_rows = cur.fetchall()

                cur.execute(top_numbers_query, (safe_days, safe_top_limit))
                top_rows = cur.fetchall()

                cur.execute(breakdown_query, (safe_days,))
                breakdown_rows = cur.fetchall()

                cur.execute(recent_events_query, (safe_recent_limit,))
                recent_rows = cur.fetchall()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Falha ao consultar uso do Evolution: {exc}") from exc

    (
        total_events,
        total_messages,
        unique_numbers,
        processed_ok,
        blocked_rbac,
        processing_errors,
        delivery_errors,
        queue_errors,
        denied_reply_sent,
        denied_reply_suppressed,
    ) = summary_row

    summary = {
        "total_events": int(total_events or 0),
        "total_messages": int(total_messages or 0),
        "unique_numbers": int(unique_numbers or 0),
        "processed_ok": int(processed_ok or 0),
        "blocked_rbac": int(blocked_rbac or 0),
        "processing_errors": int(processing_errors or 0),
        "delivery_errors": int(delivery_errors or 0),
        "queue_errors": int(queue_errors or 0),
        "total_errors": int((processing_errors or 0) + (delivery_errors or 0) + (queue_errors or 0)),
        "denied_reply_sent": int(denied_reply_sent or 0),
        "denied_reply_suppressed": int(denied_reply_suppressed or 0),
    }

    daily_messages: list[dict[str, Any]] = []
    for day_value, messages, daily_unique, daily_processed, daily_blocked in daily_rows:
        daily_messages.append(
            {
                "date": _serialize_admin_import_value(day_value),
                "messages": int(messages or 0),
                "unique_numbers": int(daily_unique or 0),
                "processed_ok": int(daily_processed or 0),
                "blocked_rbac": int(daily_blocked or 0),
            }
        )

    hourly_messages: list[dict[str, Any]] = []
    for hour_bucket, messages in hourly_rows:
        hourly_messages.append(
            {
                "hour": _serialize_admin_import_value(hour_bucket),
                "messages": int(messages or 0),
            }
        )

    top_numbers: list[dict[str, Any]] = []
    for (
        normalized_phone,
        display_name,
        display_phone,
        total_number_events,
        messages,
        number_processed,
        number_blocked,
    ) in top_rows:
        normalized_phone_text = str(normalized_phone or "sem_numero")
        display_phone_text = str(display_phone or normalized_phone_text)
        top_numbers.append(
            {
                "phone_number": display_phone_text,
                "normalized_phone": normalized_phone_text,
                "display_name": str(display_name or normalized_phone_text),
                "total_events": int(total_number_events or 0),
                "messages": int(messages or 0),
                "processed_ok": int(number_processed or 0),
                "blocked_rbac": int(number_blocked or 0),
            }
        )

    event_breakdown: list[dict[str, Any]] = []
    for event_type, decision, total in breakdown_rows:
        event_breakdown.append(
            {
                "event_type": str(event_type or ""),
                "decision": str(decision or ""),
                "total": int(total or 0),
            }
        )

    recent_events: list[dict[str, Any]] = []
    for created_at, event_type, decision, phone_number, area, reason in recent_rows:
        recent_events.append(
            {
                "created_at": _serialize_admin_import_value(created_at),
                "event_type": str(event_type or ""),
                "decision": str(decision or ""),
                "phone_number": str(phone_number or ""),
                "area": str(area or ""),
                "reason": str(reason or ""),
            }
        )

    return {
        "ok": True,
        "source": "evolution",
        "path": "/webhook/evolution",
        "window_days": safe_days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "daily_messages": daily_messages,
        "hourly_messages_24h": hourly_messages,
        "top_numbers": top_numbers,
        "event_breakdown": event_breakdown,
        "recent_events": recent_events,
        "audit_enabled": bool(settings.security_audit_enabled),
        "audit_ready": bool(security_monitor.status().get("ready")),
    }


def _build_evolution_usage_avg_report_csv(payload: dict[str, Any]) -> str:
    window_days = max(1, int(payload.get("window_days") or 1))
    top_numbers = payload.get("top_numbers") if isinstance(payload, dict) else None
    rows = top_numbers if isinstance(top_numbers, list) else []

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["nome", "media_msg_por_dia"])

    for item in rows:
        if not isinstance(item, dict):
            continue
        display_name = str(
            item.get("display_name")
            or item.get("normalized_phone")
            or item.get("phone_number")
            or "sem_nome"
        ).strip()
        messages = int(item.get("messages") or 0)
        average_per_day = messages / window_days
        writer.writerow([display_name, f"{average_per_day:.2f}".replace(".", ",")])

    return "\ufeff" + buffer.getvalue()


def _normalize_admin_broadcast_filial(value: Any) -> str:
    normalized = normalize_numeric_code(str(value or ""))
    if not normalized:
        raise HTTPException(status_code=400, detail="Informe uma filial valida para o disparo.")
    return normalized


def _panel_context_allowed_broadcast_filiais(context: dict[str, Any] | None) -> set[str] | None:
    if not context or bool(context.get("is_admin")):
        return None
    allowed: set[str] = set()
    for filial in context.get("filiais", ()) or ():
        normalized = normalize_numeric_code(str(filial or ""))
        if normalized:
            allowed.add(normalized)
    return allowed


def _require_panel_context_broadcast_filial(context: dict[str, Any] | None, filial: Any) -> str:
    normalized_filial = _normalize_admin_broadcast_filial(filial)
    allowed_filiais = _panel_context_allowed_broadcast_filiais(context)
    if allowed_filiais is not None and normalized_filial not in allowed_filiais:
        raise HTTPException(status_code=403, detail="Filial fora do escopo liberado para este financeiro.")
    return normalized_filial


def _normalize_admin_broadcast_text(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(ascii_only.replace("_", " ").replace("-", " ").split())


def _normalize_admin_broadcast_action(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in ADMIN_BROADCAST_ACTIONS:
        allowed = ", ".join(sorted(ADMIN_BROADCAST_ACTIONS))
        raise HTTPException(status_code=400, detail=f"Acao de disparo invalida. Use {allowed}.")
    return normalized


def _normalize_admin_broadcast_day(value: Any) -> str:
    normalized = _normalize_admin_broadcast_text(value) or "hoje"
    aliases = {
        "seg": "segunda",
        "segunda feira": "segunda",
        "ter": "terca",
        "terca feira": "terca",
        "qua": "quarta",
        "quarta feira": "quarta",
        "qui": "quinta",
        "quinta feira": "quinta",
        "sex": "sexta",
        "sexta feira": "sexta",
        "sab": "sabado",
        "dom": "domingo",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ADMIN_BROADCAST_DAY_OPTIONS:
        allowed = ", ".join(item["label"] for item in ADMIN_BROADCAST_DAY_OPTIONS.values())
        raise HTTPException(status_code=400, detail=f"Dia de disparo invalido. Use {allowed}.")
    return normalized


def _normalize_admin_broadcast_target_mode(value: Any) -> str:
    normalized = _normalize_admin_broadcast_text(value) or "filial"
    aliases = {
        "todos": "filial",
        "todos da filial": "filial",
        "filial": "filial",
        "numero": "specific",
        "numero especifico": "specific",
        "specific": "specific",
        "teste": "specific",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ADMIN_BROADCAST_TARGET_MODES:
        raise HTTPException(status_code=400, detail="Destino invalido para o disparo.")
    return normalized


def _normalize_admin_broadcast_audience(value: Any) -> str:
    normalized = _normalize_admin_broadcast_text(value) or "vendedor"
    aliases = {
        "rn": "vendedor",
        "rns": "vendedor",
        "vendedor": "vendedor",
        "vendedores": "vendedor",
        "gerente": "gerente_vendas",
        "gerentes": "gerente_vendas",
        "gerente vendas": "gerente_vendas",
        "gerente de vendas": "gerente_vendas",
        "gerentes de vendas": "gerente_vendas",
        "gerente_vendas": "gerente_vendas",
        "gv": "gerente_vendas",
        "gvs": "gerente_vendas",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in ADMIN_BROADCAST_AUDIENCES:
        raise HTTPException(status_code=400, detail="Perfil de disparo invalido. Use vendedores ou GVs.")
    return normalized


def _build_admin_broadcast_shortcut(action: str, day: str) -> str:
    action_data = ADMIN_BROADCAST_ACTIONS[action]
    if bool(action_data.get("supports_day")):
        day_token = ADMIN_BROADCAST_DAY_OPTIONS[day]["token"]
        return str(action_data.get("shortcut_template") or action_data["shortcut"]).format(day=day_token)
    return str(action_data["shortcut"])


def _scope_filial(value: Any) -> str:
    pair = split_scope_pair(str(value or ""))
    return pair[0] if pair else ""


def _user_broadcast_filiais(user: dict[str, Any], audience: str | None = None) -> set[str]:
    roles = {str(role or "").strip().lower() for role in user.get("roles") or []}
    filiais: set[str] = set()
    if (audience in {None, "vendedor"}) and "vendedor" in roles:
        for sector in user.get("sectors") or []:
            filial = _scope_filial(sector)
            if filial:
                filiais.add(filial)
    if (audience in {None, "gerente_vendas"}) and "gerente_vendas" in roles:
        for gv_vde in user.get("gv_vdes") or []:
            raw = str(gv_vde or "").strip().lower()
            if raw.startswith("dc:"):
                continue
            filial = _scope_filial(raw)
            if filial:
                filiais.add(filial)
    return filiais


def _is_admin_broadcast_user(user: dict[str, Any]) -> bool:
    if user.get("is_active") is False:
        return False
    roles = {str(role or "").strip().lower() for role in user.get("roles") or []}
    return bool(roles & {"vendedor", "gerente_vendas"})


def _user_matches_admin_broadcast_audience(user: dict[str, Any], audience: str) -> bool:
    roles = {str(role or "").strip().lower() for role in user.get("roles") or []}
    return str(ADMIN_BROADCAST_AUDIENCES[audience]["role"]) in roles


def _admin_broadcast_user_label(user: dict[str, Any]) -> str:
    name = str(user.get("name") or "").strip()
    phone_number = str(user.get("phone_number") or "").strip()
    return name or phone_number or "sem_nome"


def _admin_broadcast_user_role_label(user: dict[str, Any]) -> str:
    roles = [str(role or "").strip().lower() for role in user.get("roles") or []]
    if "admin" in roles:
        return "ADMIN"
    if "financeiro" in roles:
        return "FIN"
    if "diretor_comercial" in roles:
        return "DC"
    if "gerente_vendas" in roles:
        return "GV"
    if "vendedor" in roles:
        return "RN"
    return ", ".join(roles) or "-"


def _admin_broadcast_comparable_number(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        return f"{digits[:4]}{digits[5:]}"
    return digits


def _list_admin_broadcast_recipients(filial: str, audience: str) -> list[dict[str, Any]]:
    normalized_filial = _normalize_admin_broadcast_filial(filial)
    normalized_audience = _normalize_admin_broadcast_audience(audience)
    users = _access_call(access_control.list_users)
    recipients: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    for user in users:
        if not isinstance(user, dict) or not _is_admin_broadcast_user(user):
            continue
        if not _user_matches_admin_broadcast_audience(user, normalized_audience):
            continue
        if normalized_filial not in _user_broadcast_filiais(user, normalized_audience):
            continue
        phone_number = str(user.get("phone_number") or "").strip()
        comparable_number = _admin_broadcast_comparable_number(phone_number)
        if not comparable_number or comparable_number in seen_numbers:
            continue
        seen_numbers.add(comparable_number)
        recipients.append(
            {
                "phone_number": phone_number,
                "name": _admin_broadcast_user_label(user),
                "role": _admin_broadcast_user_role_label(user),
                "roles": list(user.get("roles") or []),
                "sectors": list(user.get("sectors") or []),
                "gv_vdes": list(user.get("gv_vdes") or []),
            }
        )
    recipients.sort(key=lambda item: (str(item.get("role") or ""), str(item.get("name") or ""), str(item.get("phone_number") or "")))
    return recipients


def _filter_admin_broadcast_selected_recipients(
    recipients: list[dict[str, Any]],
    selected_numbers: list[str] | tuple[str, ...] | None,
    *,
    require_selection: bool,
) -> list[dict[str, Any]]:
    selected = {
        comparable
        for comparable in (_admin_broadcast_comparable_number(item) for item in selected_numbers or [])
        if comparable
    }
    if require_selection and not selected:
        raise HTTPException(status_code=400, detail="Selecione ao menos um destinatario para o disparo.")
    if not selected:
        return recipients

    filtered = [
        recipient
        for recipient in recipients
        if _admin_broadcast_comparable_number(recipient.get("phone_number")) in selected
    ]
    if require_selection and not filtered:
        raise HTTPException(status_code=400, detail="Nenhum destinatario selecionado continua elegivel para esse disparo.")
    return filtered


def _get_admin_broadcast_specific_recipient(target_number: str) -> list[dict[str, Any]]:
    number = str(target_number or "").strip()
    if not number:
        raise HTTPException(status_code=400, detail="Informe o numero especifico para teste.")
    user = _access_call(access_control.get_user, number)
    if not user:
        raise HTTPException(status_code=404, detail="Numero especifico nao encontrado no RBAC.")
    if user.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Numero especifico esta inativo no RBAC.")
    phone_number = str(user.get("phone_number") or number).strip()
    if not phone_number:
        raise HTTPException(status_code=400, detail="Numero especifico invalido.")
    return [
        {
            "phone_number": phone_number,
            "name": _admin_broadcast_user_label(user),
            "role": _admin_broadcast_user_role_label(user),
            "roles": list(user.get("roles") or []),
            "sectors": list(user.get("sectors") or []),
            "gv_vdes": list(user.get("gv_vdes") or []),
            "test_target": True,
        }
    ]


def _list_admin_broadcast_filiais(context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    allowed_filiais = _panel_context_allowed_broadcast_filiais(context)
    users = _access_call(access_control.list_users)
    stats: dict[str, dict[str, Any]] = {}
    for user in users:
        if not isinstance(user, dict) or not _is_admin_broadcast_user(user):
            continue
        for audience in ADMIN_BROADCAST_AUDIENCES:
            if not _user_matches_admin_broadcast_audience(user, audience):
                continue
            for filial in _user_broadcast_filiais(user, audience):
                if allowed_filiais is not None and filial not in allowed_filiais:
                    continue
                item = stats.setdefault(
                    filial,
                    {"filial": filial, "total": 0, "vendedor": 0, "gerente_vendas": 0},
                )
                item["total"] += 1
                item[audience] += 1
    return sorted(
        stats.values(),
        key=lambda item: int(item["filial"]) if str(item["filial"]).isdigit() else str(item["filial"]),
    )


def _list_admin_broadcast_audiences() -> list[dict[str, str]]:
    return [
        {
            "id": audience_id,
            "label": data["label"],
            "role_label": data["role_label"],
        }
        for audience_id, data in ADMIN_BROADCAST_AUDIENCES.items()
    ]


def _list_admin_broadcast_options(context: dict[str, Any] | None = None) -> dict[str, Any]:
    actions = [
        {
            "id": action_id,
            "label": data["label"],
            "description": data["description"],
            "shortcut": data["shortcut"],
            "supports_day": bool(data.get("supports_day")),
        }
        for action_id, data in ADMIN_BROADCAST_ACTIONS.items()
    ]
    days = [{"id": day_id, **data} for day_id, data in ADMIN_BROADCAST_DAY_OPTIONS.items()]
    target_modes = [{"id": mode_id, **data} for mode_id, data in ADMIN_BROADCAST_TARGET_MODES.items()]
    return {
        "actions": actions,
        "days": days,
        "target_modes": target_modes,
        "target_audiences": _list_admin_broadcast_audiences(),
        "filiais": _list_admin_broadcast_filiais(context),
        "status": _snapshot_admin_broadcast_state(context),
    }


def _snapshot_admin_broadcast_state(context: dict[str, Any] | None = None) -> dict[str, Any]:
    with admin_broadcast_lock:
        payload = {
            "running": bool(admin_broadcast_state["running"]),
            "current_job_id": str(admin_broadcast_state["current_job_id"] or ""),
            "current_filial": str(admin_broadcast_state["current_filial"] or ""),
            "current_action": str(admin_broadcast_state["current_action"] or ""),
            "current_day": str(admin_broadcast_state["current_day"] or ""),
            "current_target_mode": str(admin_broadcast_state["current_target_mode"] or ""),
            "current_target_audience": str(admin_broadcast_state["current_target_audience"] or ""),
            "current_shortcut": str(admin_broadcast_state["current_shortcut"] or ""),
            "started_at": str(admin_broadcast_state["started_at"] or ""),
            "total": int(admin_broadcast_state.get("total") or 0),
            "sent": int(admin_broadcast_state.get("sent") or 0),
            "failed": int(admin_broadcast_state.get("failed") or 0),
            "skipped": int(admin_broadcast_state.get("skipped") or 0),
            "last_job": dict(admin_broadcast_state.get("last_job") or {}),
        }
    allowed_filiais = _panel_context_allowed_broadcast_filiais(context)
    if allowed_filiais is None:
        return payload

    current_filial = str(payload.get("current_filial") or "")
    if current_filial and current_filial not in allowed_filiais:
        payload.update(
            {
                "running": False,
                "current_job_id": "",
                "current_filial": "",
                "current_action": "",
                "current_day": "",
                "current_target_mode": "",
                "current_target_audience": "",
                "current_shortcut": "",
                "started_at": "",
                "total": 0,
                "sent": 0,
                "failed": 0,
                "skipped": 0,
            }
        )

    last_job = payload.get("last_job") or {}
    last_filial = str(last_job.get("filial") or "") if isinstance(last_job, dict) else ""
    if last_filial and last_filial not in allowed_filiais:
        payload["last_job"] = {}
    return payload


def _build_admin_broadcast_payload(
    *,
    filial: str,
    action: str,
    day: str,
    target_mode: str,
    target_audience: str,
    target_number: str = "",
    selected_numbers: list[str] | tuple[str, ...] | None = None,
    require_selection: bool = False,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_filial = _require_panel_context_broadcast_filial(context, filial)
    normalized_action = _normalize_admin_broadcast_action(action)
    normalized_day = _normalize_admin_broadcast_day(day)
    normalized_target_mode = _normalize_admin_broadcast_target_mode(target_mode)
    normalized_target_audience = _normalize_admin_broadcast_audience(target_audience)
    recipients = (
        _list_admin_broadcast_recipients(normalized_filial, normalized_target_audience)
        if normalized_target_mode == "filial"
        else _get_admin_broadcast_specific_recipient(target_number)
    )
    if normalized_target_mode == "specific" and _panel_context_allowed_broadcast_filiais(context) is not None:
        recipients = [
            recipient
            for recipient in recipients
            if normalized_filial in _user_broadcast_filiais(recipient, normalized_target_audience)
        ]
        if not recipients:
            raise HTTPException(status_code=403, detail="Numero especifico fora da filial/perfil liberado para este financeiro.")
    recipients = _filter_admin_broadcast_selected_recipients(
        recipients,
        selected_numbers,
        require_selection=require_selection,
    )
    shortcut = _build_admin_broadcast_shortcut(normalized_action, normalized_day)
    action_data = ADMIN_BROADCAST_ACTIONS[normalized_action]
    if normalized_target_mode == "specific" and recipients:
        decision = access_control.authorize(
            phone_number=str(recipients[0].get("phone_number") or target_number),
            area=str(action_data.get("area") or "cliente"),
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Numero especifico sem permissao para esse disparo: {decision.reason or 'access_denied'}.",
            )
    day_label = ADMIN_BROADCAST_DAY_OPTIONS[normalized_day]["label"] if bool(action_data.get("supports_day")) else "Nao se aplica"
    normalized_target_number = str(recipients[0].get("phone_number") or target_number).strip() if normalized_target_mode == "specific" and recipients else ""
    return {
        "filial": normalized_filial,
        "action": normalized_action,
        "action_label": action_data["label"],
        "day": normalized_day,
        "day_label": day_label,
        "target_mode": normalized_target_mode,
        "target_mode_label": ADMIN_BROADCAST_TARGET_MODES[normalized_target_mode]["label"],
        "target_audience": normalized_target_audience,
        "target_audience_label": ADMIN_BROADCAST_AUDIENCES[normalized_target_audience]["label"],
        "target_number": normalized_target_number,
        "shortcut": shortcut,
        "supports_day": bool(action_data.get("supports_day")),
        "recipients": recipients,
        "total": len(recipients),
    }


def _queue_admin_broadcast(
    filial: str,
    action: str,
    day: str,
    target_mode: str,
    target_audience: str,
    target_number: str = "",
    selected_numbers: list[str] | tuple[str, ...] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _build_admin_broadcast_payload(
        filial=filial,
        action=action,
        day=day,
        target_mode=target_mode,
        target_audience=target_audience,
        target_number=target_number,
        selected_numbers=selected_numbers,
        require_selection=True,
        context=context,
    )
    normalized_filial = payload["filial"]
    normalized_action = payload["action"]
    normalized_day = payload["day"]
    normalized_target_mode = payload["target_mode"]
    normalized_target_audience = payload["target_audience"]
    recipients = payload["recipients"]
    shortcut = payload["shortcut"]
    if not recipients:
        empty_message = ADMIN_BROADCAST_AUDIENCES[normalized_target_audience]["empty_message"]
        raise HTTPException(status_code=400, detail=empty_message)

    job_id = str(uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    with admin_broadcast_lock:
        if admin_broadcast_state["running"]:
            raise HTTPException(status_code=409, detail="Ja existe um disparo em andamento.")
        admin_broadcast_state.update(
            {
                "running": True,
                "current_job_id": job_id,
                "current_filial": normalized_filial,
                "current_action": normalized_action,
                "current_day": normalized_day,
                "current_target_mode": normalized_target_mode,
                "current_target_audience": normalized_target_audience,
                "current_shortcut": shortcut,
                "started_at": started_at,
                "total": len(recipients),
                "sent": 0,
                "failed": 0,
                "skipped": 0,
            }
        )

    try:
        admin_broadcast_executor.submit(
            _admin_broadcast_worker,
            job_id,
            normalized_filial,
            normalized_action,
            normalized_day,
            normalized_target_mode,
            normalized_target_audience,
            shortcut,
            recipients,
        )
    except Exception:
        with admin_broadcast_lock:
            admin_broadcast_state["running"] = False
            admin_broadcast_state["current_job_id"] = ""
            admin_broadcast_state["current_filial"] = ""
            admin_broadcast_state["current_action"] = ""
            admin_broadcast_state["current_day"] = ""
            admin_broadcast_state["current_target_mode"] = ""
            admin_broadcast_state["current_target_audience"] = ""
            admin_broadcast_state["current_shortcut"] = ""
            admin_broadcast_state["started_at"] = ""
        raise

    return {"job_id": job_id, **payload}


def _admin_broadcast_worker(
    job_id: str,
    filial: str,
    action: str,
    day: str,
    target_mode: str,
    target_audience: str,
    shortcut: str,
    recipients: list[dict[str, Any]],
) -> None:
    action_data = ADMIN_BROADCAST_ACTIONS[action]
    area = action_data.get("area") or "cliente"
    results: list[dict[str, Any]] = []
    sent = failed = skipped = 0

    for index, recipient in enumerate(recipients, start=1):
        phone_number = str(recipient.get("phone_number") or "").strip()
        result = {
            "phone_number": phone_number,
            "name": recipient.get("name") or phone_number,
            "role": recipient.get("role") or "",
            "status": "skipped",
            "error": "",
        }
        try:
            decision = access_control.authorize(phone_number=phone_number, area=area)
            if not decision.allowed:
                skipped += 1
                result["error"] = decision.reason or "access_denied"
            else:
                reset_incoming = IncomingMessage(sender=phone_number, text="menu", channel="evolution", message_id=f"admin-broadcast:{job_id}:reset")
                lookup_flow.handle(incoming=reset_incoming, decision=decision)
                incoming = IncomingMessage(sender=phone_number, text=shortcut, channel="evolution", message_id=f"admin-broadcast:{job_id}")
                outgoing = lookup_flow.handle(incoming=incoming, decision=decision)
                evolution_client.send(number=phone_number, message=outgoing)
                sent += 1
                result["status"] = "sent"
        except Exception as exc:
            failed += 1
            result["status"] = "failed"
            result["error"] = str(exc)
            logger.exception("Falha no disparo admin %s para %s: %s", job_id, phone_number, exc)

        results.append(result)
        with admin_broadcast_lock:
            if admin_broadcast_state["current_job_id"] == job_id:
                admin_broadcast_state["sent"] = sent
                admin_broadcast_state["failed"] = failed
                admin_broadcast_state["skipped"] = skipped

        if index < len(recipients) and ADMIN_BROADCAST_SEND_DELAY_SECONDS > 0:
            time.sleep(ADMIN_BROADCAST_SEND_DELAY_SECONDS)

    finished_at = datetime.now(timezone.utc).isoformat()
    with admin_broadcast_lock:
        if admin_broadcast_state["current_job_id"] == job_id:
            admin_broadcast_state["running"] = False
            admin_broadcast_state["current_job_id"] = ""
            admin_broadcast_state["current_filial"] = ""
            admin_broadcast_state["current_action"] = ""
            admin_broadcast_state["current_day"] = ""
            admin_broadcast_state["current_target_mode"] = ""
            admin_broadcast_state["current_target_audience"] = ""
            admin_broadcast_state["current_shortcut"] = ""
            admin_broadcast_state["started_at"] = ""
        admin_broadcast_state["last_job"] = {
            "job_id": job_id,
            "filial": filial,
            "action": action,
            "action_label": action_data["label"],
            "day": day,
            "day_label": ADMIN_BROADCAST_DAY_OPTIONS[day]["label"] if bool(action_data.get("supports_day")) else "Nao se aplica",
            "target_mode": target_mode,
            "target_mode_label": ADMIN_BROADCAST_TARGET_MODES[target_mode]["label"],
            "target_audience": target_audience,
            "target_audience_label": ADMIN_BROADCAST_AUDIENCES[target_audience]["label"],
            "shortcut": shortcut,
            "total": len(recipients),
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "finished_at": finished_at,
            "results": results[-50:],
        }


def _daily_route_state_path() -> Path:
    raw_path = Path(settings.daily_route_broadcast_state_file or "exports/scheduled_messages/daily_route_state.json")
    return raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path


def _load_daily_route_state() -> dict[str, Any]:
    path = _daily_route_state_path()
    if not path.exists():
        return {"runs": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Falha ao ler estado do envio diario de rota: %s", exc)
        return {"runs": {}}
    if not isinstance(payload, dict):
        return {"runs": {}}
    runs = payload.get("runs")
    if not isinstance(runs, dict):
        payload["runs"] = {}
    return payload


def _write_daily_route_state(state: dict[str, Any]) -> None:
    path = _daily_route_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _prune_daily_route_state(state: dict[str, Any], keep_days: int = 45) -> None:
    runs = state.setdefault("runs", {})
    if not isinstance(runs, dict):
        state["runs"] = {}
        return
    keys = sorted(str(key) for key in runs.keys())
    for key in keys[:-max(1, keep_days)]:
        runs.pop(key, None)


def _daily_route_timezone() -> Any:
    timezone_name = settings.daily_route_broadcast_timezone or "America/Fortaleza"
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        logger.warning("Timezone invalido para envio diario de rota: %s", timezone_name)
        return timezone(timedelta(hours=-3), name="America/Fortaleza")


def _daily_route_schedule_time() -> tuple[int, int]:
    raw_value = str(settings.daily_route_broadcast_time or "07:00").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw_value)
    if not match:
        logger.warning("Horario invalido para envio diario de rota: %s. Usando 07:00.", raw_value)
        return 7, 0
    hour = max(0, min(int(match.group(1)), 23))
    minute = max(0, min(int(match.group(2)), 59))
    return hour, minute


def _daily_route_now() -> datetime:
    return datetime.now(_daily_route_timezone())


def _should_run_daily_route_broadcast(now: datetime, state: dict[str, Any]) -> bool:
    if now.weekday() >= 5:
        return False
    hour, minute = _daily_route_schedule_time()
    target_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < target_at:
        return False
    run_date = now.date().isoformat()
    run_payload = (state.get("runs") or {}).get(run_date)
    return not (isinstance(run_payload, dict) and run_payload.get("status") == "completed")


def _daily_route_audiences() -> tuple[str, ...]:
    raw_audiences = settings.daily_route_broadcast_audiences or ("vendedor",)
    normalized: list[str] = []
    seen: set[str] = set()
    for audience in raw_audiences:
        try:
            item = _normalize_admin_broadcast_audience(audience)
        except HTTPException:
            logger.warning("Publico invalido no envio diario de rota: %s", audience)
            continue
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return tuple(normalized or ["vendedor"])


def _list_daily_route_recipients() -> list[dict[str, Any]]:
    audiences = set(_daily_route_audiences())
    users = _access_call(access_control.list_users)
    recipients: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    for user in users:
        if not isinstance(user, dict) or not _is_admin_broadcast_user(user):
            continue
        if not any(_user_matches_admin_broadcast_audience(user, audience) for audience in audiences):
            continue
        phone_number = str(user.get("phone_number") or "").strip()
        comparable_number = _admin_broadcast_comparable_number(phone_number)
        if not comparable_number or comparable_number in seen_numbers:
            continue
        seen_numbers.add(comparable_number)
        recipients.append(
            {
                "phone_number": phone_number,
                "name": _admin_broadcast_user_label(user),
                "role": _admin_broadcast_user_role_label(user),
                "roles": list(user.get("roles") or []),
                "sectors": list(user.get("sectors") or []),
                "gv_vdes": list(user.get("gv_vdes") or []),
            }
        )
    recipients.sort(key=lambda item: (str(item.get("role") or ""), str(item.get("name") or ""), str(item.get("phone_number") or "")))
    return recipients


def _daily_route_run_record(state: dict[str, Any], run_date: str, now: datetime, shortcut: str) -> dict[str, Any]:
    runs = state.setdefault("runs", {})
    if not isinstance(runs, dict):
        state["runs"] = {}
        runs = state["runs"]
    record = runs.setdefault(
        run_date,
        {
            "status": "running",
            "started_at": now.isoformat(),
            "finished_at": "",
            "shortcut": shortcut,
            "audiences": list(_daily_route_audiences()),
            "total": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "sent_numbers": [],
            "failed_numbers": [],
            "skipped_numbers": [],
            "results": [],
        },
    )
    if not isinstance(record, dict):
        record = {}
        runs[run_date] = record
    record["status"] = "running"
    record.setdefault("started_at", now.isoformat())
    record["shortcut"] = shortcut
    record["audiences"] = list(_daily_route_audiences())
    record.setdefault("sent_numbers", [])
    record.setdefault("failed_numbers", [])
    record.setdefault("skipped_numbers", [])
    record.setdefault("results", [])
    return record


def _daily_route_update_status(**updates: Any) -> None:
    with daily_route_broadcast_lock:
        daily_route_broadcast_status.update(updates)


def _daily_route_status_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(record.get("status") or ""),
        "started_at": str(record.get("started_at") or ""),
        "finished_at": str(record.get("finished_at") or ""),
        "shortcut": str(record.get("shortcut") or ""),
        "audiences": list(record.get("audiences") or []),
        "total": int(record.get("total") or 0),
        "sent": int(record.get("sent") or 0),
        "failed": int(record.get("failed") or 0),
        "skipped": int(record.get("skipped") or 0),
    }


def _run_daily_route_broadcast_if_due() -> bool:
    if not settings.daily_route_broadcast_enabled:
        return False
    if not evolution_client.enabled:
        _daily_route_update_status(last_error="Evolution nao configurada para envio.")
        return False

    now = _daily_route_now()
    state = _load_daily_route_state()
    _daily_route_update_status(last_checked_at=now.isoformat())
    if not _should_run_daily_route_broadcast(now, state):
        run_date = now.date().isoformat()
        run_payload = (state.get("runs") or {}).get(run_date)
        if isinstance(run_payload, dict):
            _daily_route_update_status(last_run_date=run_date, last_run=_daily_route_status_summary(run_payload))
        return False

    if not daily_route_broadcast_lock.acquire(blocking=False):
        return False
    try:
        daily_route_broadcast_status["running"] = True
        daily_route_broadcast_status["last_error"] = ""
        run_date = now.date().isoformat()
        shortcut = _build_admin_broadcast_shortcut("rota_dia", "hoje")
        recipients = _list_daily_route_recipients()
        state = _load_daily_route_state()
        record = _daily_route_run_record(state, run_date, now, shortcut)
        record["total"] = len(recipients)
        _prune_daily_route_state(state)
        _write_daily_route_state(state)

        sent_numbers = {str(item) for item in record.get("sent_numbers") or [] if str(item).strip()}
        skipped_numbers = {str(item) for item in record.get("skipped_numbers") or [] if str(item).strip()}
        failed_numbers: set[str] = set()
        sent = len(sent_numbers)
        skipped = len(skipped_numbers)
        failed = 0
        results = list(record.get("results") or [])

        for index, recipient in enumerate(recipients, start=1):
            phone_number = str(recipient.get("phone_number") or "").strip()
            comparable_number = _admin_broadcast_comparable_number(phone_number)
            if not comparable_number or comparable_number in sent_numbers or comparable_number in skipped_numbers:
                continue
            result = {
                "phone_number": phone_number,
                "name": recipient.get("name") or phone_number,
                "role": recipient.get("role") or "",
                "status": "skipped",
                "error": "",
            }
            try:
                decision = access_control.authorize(phone_number=phone_number, area="cliente")
                if not decision.allowed:
                    skipped_numbers.add(comparable_number)
                    skipped += 1
                    result["error"] = decision.reason or "access_denied"
                else:
                    reset_incoming = IncomingMessage(
                        sender=phone_number,
                        text="menu",
                        channel="evolution",
                        message_id=f"daily-route:{run_date}:{comparable_number}:reset",
                    )
                    lookup_flow.handle(incoming=reset_incoming, decision=decision)
                    incoming = IncomingMessage(
                        sender=phone_number,
                        text=shortcut,
                        channel="evolution",
                        message_id=f"daily-route:{run_date}:{comparable_number}",
                    )
                    outgoing = lookup_flow.handle(incoming=incoming, decision=decision)
                    evolution_client.send(number=phone_number, message=outgoing)
                    sent_numbers.add(comparable_number)
                    sent += 1
                    result["status"] = "sent"
                result["error"] = str(result.get("error") or "")
            except Exception as exc:
                failed_numbers.add(comparable_number)
                failed += 1
                result["status"] = "failed"
                result["error"] = str(exc)
                logger.exception("Falha no envio diario da rota para %s: %s", phone_number, exc)

            results.append(result)
            record.update(
                {
                    "status": "running",
                    "sent": sent,
                    "failed": failed,
                    "skipped": skipped,
                    "sent_numbers": sorted(sent_numbers),
                    "failed_numbers": sorted(failed_numbers),
                    "skipped_numbers": sorted(skipped_numbers),
                    "results": results[-100:],
                }
            )
            _write_daily_route_state(state)
            _daily_route_update_status(last_run_date=run_date, last_run=_daily_route_status_summary(record))

            if index < len(recipients) and ADMIN_BROADCAST_SEND_DELAY_SECONDS > 0:
                time.sleep(ADMIN_BROADCAST_SEND_DELAY_SECONDS)

        finished_at = _daily_route_now().isoformat()
        record.update(
            {
                "status": "completed",
                "finished_at": finished_at,
                "sent": sent,
                "failed": failed,
                "skipped": skipped,
                "sent_numbers": sorted(sent_numbers),
                "failed_numbers": sorted(failed_numbers),
                "skipped_numbers": sorted(skipped_numbers),
                "results": results[-100:],
            }
        )
        _write_daily_route_state(state)
        _daily_route_update_status(
            running=False,
            last_run_date=run_date,
            last_run=_daily_route_status_summary(record),
            last_error="",
        )
        logger.info(
            "Envio diario da rota concluido: data=%s total=%s enviados=%s falhas=%s ignorados=%s",
            run_date,
            len(recipients),
            sent,
            failed,
            skipped,
        )
        return True
    except Exception as exc:
        _daily_route_update_status(running=False, last_error=str(exc))
        logger.exception("Falha no agendamento diario da rota: %s", exc)
        return False
    finally:
        daily_route_broadcast_status["running"] = False
        daily_route_broadcast_lock.release()


def _daily_route_broadcast_loop() -> None:
    initial_delay = settings.daily_route_broadcast_initial_delay_seconds
    if initial_delay and daily_route_broadcast_stop_event.wait(initial_delay):
        return
    while not daily_route_broadcast_stop_event.is_set():
        _run_daily_route_broadcast_if_due()
        interval = settings.daily_route_broadcast_check_interval_seconds
        if daily_route_broadcast_stop_event.wait(interval):
            return


def _start_daily_route_broadcast_scheduler() -> None:
    global daily_route_broadcast_thread
    if not settings.daily_route_broadcast_enabled:
        logger.info("Envio diario da rota desabilitado.")
        return
    if daily_route_broadcast_thread and daily_route_broadcast_thread.is_alive():
        return
    daily_route_broadcast_stop_event.clear()
    daily_route_broadcast_thread = Thread(
        target=_daily_route_broadcast_loop,
        name="daily-route-broadcast",
        daemon=True,
    )
    daily_route_broadcast_thread.start()
    logger.info(
        "Envio diario da rota agendado para %s (%s).",
        settings.daily_route_broadcast_time,
        settings.daily_route_broadcast_timezone,
    )


def _stop_daily_route_broadcast_scheduler() -> None:
    daily_route_broadcast_stop_event.set()
    thread = daily_route_broadcast_thread
    if thread and thread.is_alive():
        thread.join(timeout=5)


def _load_admin_import_panel_html() -> str:
    if ADMIN_IMPORT_PANEL_TEMPLATE.exists():
        return ADMIN_IMPORT_PANEL_TEMPLATE.read_text(encoding="utf-8").replace(
            "__API_AUTH_ENABLED__",
            "true" if settings.api_auth_enabled else "false",
        )
    return "<html><body><h1>Painel indisponivel</h1></body></html>"


def _load_admin_login_html() -> str:
    return """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Central Pau Brasil - Login</title>
  <style>
    :root {
      --bg: #060d1b;
      --panel: rgba(11, 18, 32, 0.92);
      --line: rgba(148, 163, 184, 0.24);
      --text: #e2e8f0;
      --muted: #94a3b8;
      --brand: #60a5fa;
      --danger: #fca5a5;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Inter, Segoe UI, system-ui, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 18% 12%, rgba(96, 165, 250, 0.22), transparent 28%),
        radial-gradient(circle at 88% 8%, rgba(37, 99, 235, 0.24), transparent 30%),
        var(--bg);
      padding: 24px;
    }
    .card {
      width: min(460px, 100%);
      border: 1px solid var(--line);
      border-radius: 26px;
      background: linear-gradient(145deg, rgba(15, 23, 42, 0.96), rgba(8, 15, 30, 0.94));
      box-shadow: 0 24px 70px rgba(2, 8, 23, 0.55);
      padding: 30px;
    }
    .brand { display: flex; align-items: center; gap: 14px; margin-bottom: 26px; }
    .mark {
      width: 52px;
      height: 52px;
      border-radius: 16px;
      display: grid;
      place-items: center;
      font-weight: 900;
      font-size: 26px;
      color: white;
      background: linear-gradient(135deg, #0f2c63, #2563eb);
      border: 1px solid rgba(255,255,255,0.14);
    }
    .brand strong { display: block; letter-spacing: .08em; font-size: 14px; }
    .brand span { color: var(--muted); font-size: 13px; }
    h1 { font-size: 28px; line-height: 1.1; margin: 0 0 10px; }
    p { margin: 0 0 22px; color: var(--muted); }
    label { display: block; margin-bottom: 8px; font-weight: 700; }
    input {
      width: 100%;
      border: 1px solid var(--line);
      background: #0b1220;
      color: var(--text);
      border-radius: 14px;
      padding: 14px 15px;
      font-size: 16px;
      outline: none;
    }
    input:focus { border-color: var(--brand); box-shadow: 0 0 0 4px rgba(96,165,250,.14); }
    button {
      width: 100%;
      margin-top: 16px;
      border: 0;
      border-radius: 14px;
      padding: 14px 16px;
      font-weight: 800;
      color: white;
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      cursor: pointer;
    }
    button:disabled { opacity: .68; cursor: wait; }
    .error { min-height: 22px; margin-top: 12px; color: var(--danger); font-size: 14px; }
    .note { margin-top: 18px; font-size: 13px; color: var(--muted); }
  </style>
</head>
<body>
  <main class="card">
    <div class="brand">
      <div class="mark">P</div>
      <div><strong>PAU BRASIL</strong><span>Central administrativa</span></div>
    </div>
    <h1>Entrar no painel</h1>
    <p>Use o token admin ou o token financeiro da sua operação.</p>
    <form id="loginForm">
      <label for="token">Token de acesso</label>
      <input id="token" name="token" type="password" autocomplete="off" autofocus required>
      <button id="submitBtn" type="submit">Entrar</button>
      <div id="error" class="error" role="alert"></div>
    </form>
    <div class="note">A sessão expira automaticamente. Não compartilhe esse acesso fora da rede autorizada.</div>
  </main>
  <script>
    const form = document.getElementById("loginForm");
    const token = document.getElementById("token");
    const errorBox = document.getElementById("error");
    const submitBtn = document.getElementById("submitBtn");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorBox.textContent = "";
      submitBtn.disabled = true;
      submitBtn.textContent = "Validando...";
      try {
        const response = await fetch("/api/admin/panel/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: token.value.trim() })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || "Token invalido.");
        window.location.assign("/admin/imports");
      } catch (error) {
        errorBox.textContent = error.message || "Falha no login.";
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Entrar";
      }
    });
  </script>
</body>
</html>
""".strip()


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
    maintenance_result = _run_admin_import_maintenance(force_stale=True)
    if not maintenance_result.get("ok"):
        logger.warning("Manutencao de imports indisponivel no startup: %s", maintenance_result.get("error"))
    _start_daily_route_broadcast_scheduler()


@app.on_event("shutdown")
def shutdown() -> None:
    _stop_daily_route_broadcast_scheduler()
    security_monitor.shutdown()
    admin_import_executor.shutdown(wait=False, cancel_futures=False)
    critica_pdf_prebuild_executor.shutdown(wait=False, cancel_futures=False)
    admin_broadcast_executor.shutdown(wait=False, cancel_futures=False)
    webhook_executor.shutdown(wait=True, cancel_futures=False)
    close_all_connection_pools()


def _build_detailed_health_payload() -> dict[str, Any]:
    access_status = access_control.status()
    security_status = security_monitor.status()
    reports_status = dclientes_query_service.status()
    inadimplencia_status = inadimplencia_query_service.status()
    comodatos_status = comodatos_query_service.status()
    giro_status = giro_query_service.status()
    with daily_route_broadcast_lock:
        daily_route_status = dict(daily_route_broadcast_status)
    return {
        "ok": True,
        "api_auth_enabled": settings.api_auth_enabled,
        "api_auth_token_count": len(settings.api_auth_tokens),
        "api_require_admin_for_number": settings.api_require_admin_for_number,
        "admin_token_configured": bool(settings.admin_api_token.strip()),
        "webhook_auth_required": True,
        "webhook_token_configured": bool(settings.verify_token.strip()),
        "meta_cloud_enabled": settings.meta_cloud_enabled,
        "meta_cloud_ready": meta_cloud_client.enabled,
        "meta_cloud_verify_token_configured": bool(settings.meta_cloud_verify_token.strip()),
        "webhook_worker_threads": settings.webhook_worker_threads,
        "security_audit_enabled": security_status["enabled"],
        "security_audit_ready": security_status["ready"],
        "security_audit_last_error": security_status["last_error"],
        "access_control_enabled": settings.access_control_enabled,
        "access_database_configured": access_status["database_configured"],
        "access_db_schema": access_status["schema"],
        "access_db_ready": access_status["ready"],
        "access_public_enabled": access_status["public_enabled"],
        "access_connect_timeout_seconds": access_status["connect_timeout_seconds"],
        "access_last_error": access_status["last_error"],
        "denied_reply_cooldown_minutes": settings.denied_reply_cooldown_minutes,
        "denied_unregistered_reply_cooldown_minutes": settings.denied_unregistered_reply_cooldown_minutes,
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


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "bot_api",
    }


@app.get("/api/admin/health")
def api_admin_health(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    return _build_detailed_health_payload()


def _process_webhook_message(
    *,
    incoming: Any,
    requested_area: str,
    path: str,
    metadata: dict[str, Any],
) -> None:
    decision = access_control.authorize(phone_number=incoming.sender, area=requested_area)
    if not decision.allowed:
        _record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason=decision.reason,
        )
        blocked_text = (
            "Seu numero ainda nao tem acesso a essa consulta.\n"
            "Se precisar, fale com o responsavel para liberar o seu acesso."
        )
        blocked_reply_sent = _should_send_denied_reply(
            number=decision.normalized_number or incoming.sender,
            reason=decision.reason,
        )
        _record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="denied_reply",
            decision="sent" if blocked_reply_sent else "suppressed",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason=decision.reason,
        )
        if blocked_reply_sent:
            _send_text_reply(incoming=incoming, text=blocked_text)
        if blocked_reply_sent:
            logger.info(
                "Resposta de bloqueio enviada para %s (%s); proxima resposta em %s minuto(s).",
                decision.normalized_number or incoming.sender,
                decision.reason,
                denied_reply_throttle.cooldown_minutes_for(decision.reason),
            )
        else:
            logger.info(
                "Resposta de bloqueio suprimida para %s (%s).",
                decision.normalized_number or incoming.sender,
                decision.reason,
            )
        return

    try:
        outgoing = lookup_flow.handle(incoming=incoming, decision=decision)
    except Exception as exc:
        _record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="processing",
            decision="error",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason="processing_error",
        )
        logger.exception("Falha no processamento da mensagem: %s", exc)
        error_text = "Tive um problema para atender sua mensagem agora.\nTente novamente em instantes."
        _send_text_reply(incoming=incoming, text=error_text)
        return

    _record_security_event_for_path(
        path=path,
        metadata=metadata,
        channel="webhook",
        event_type="processing",
        decision="allowed",
        phone_number=decision.normalized_number or incoming.sender,
        area=requested_area,
        reason=outgoing.kind,
    )
    try:
        _send_outgoing_reply(incoming=incoming, outgoing=outgoing)
    except Exception as exc:
        _record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="delivery",
            decision="error",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason="delivery_error",
        )
        logger.exception("Falha ao enviar resposta pela Evolution/Meta: %s", exc)


def _send_text_reply(*, incoming: Any, text: str) -> None:
    channel = getattr(incoming, "channel", "evolution")
    if channel == "meta_cloud":
        if meta_cloud_client.enabled:
            meta_cloud_client.send_text(number=incoming.sender, text=text)
        return
    if evolution_client.enabled:
        evolution_client.send_text(number=incoming.sender, text=text)


def _send_outgoing_reply(*, incoming: Any, outgoing: Any) -> None:
    channel = getattr(incoming, "channel", "evolution")
    if channel == "meta_cloud":
        if meta_cloud_client.enabled:
            meta_text = outgoing.text
            if getattr(outgoing, "media_url", ""):
                caption = str(getattr(outgoing, "media_caption", "") or "QR Code").strip()
                meta_text = f"{meta_text}\n\n{caption}: {outgoing.media_url}".strip()
            meta_cloud_client.send_text(number=incoming.sender, text=meta_text)
        return
    if evolution_client.enabled:
        evolution_client.send(number=incoming.sender, message=outgoing)


def _queue_incoming_webhook(
    *,
    request: Request,
    incoming: Any,
    requested_area: str,
    event_type_prefix: str = "webhook",
) -> dict[str, Any]:
    try:
        webhook_executor.submit(
            _process_webhook_message,
            incoming=incoming,
            requested_area=requested_area,
            path=request.url.path,
            metadata=_request_metadata(request, message_id=incoming.message_id),
        )
    except Exception as exc:
        _record_security_event(
            request,
            channel=event_type_prefix,
            event_type="queue",
            decision="error",
            phone_number=incoming.sender,
            area=requested_area,
            reason="queue_submit_failed",
        )
        logger.exception("Falha ao enfileirar processamento do webhook: %s", exc)
        return {
            "received": True,
            "handled": False,
            "intent": "queue_error",
            "message_id": incoming.message_id,
        }
    _record_security_event(
        request,
        channel=event_type_prefix,
        event_type="queue",
        decision="accepted",
        phone_number=incoming.sender,
        area=requested_area,
        reason="queued",
    )
    return {
        "received": True,
        "handled": True,
        "intent": "queued",
        "queued": True,
        "message_id": incoming.message_id,
    }


@app.get("/api/client-search")
def api_client_search(
    request: Request,
    q: str,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    if not q.strip():
        raise HTTPException(status_code=400, detail="Parametro q e obrigatorio.")
    _record_security_event(
        request,
        channel="api",
        event_type="client_search",
        decision="deprecated",
        reason="legacy_route_disabled",
    )
    return {
        "handled": False,
        "intent": "legacy_route_disabled",
        "reply": "Essa rota antiga foi desativada. Use /api/dclientes/search ou o fluxo principal do bot.",
    }


@app.get("/api/dclientes/search")
def api_dclientes_search(
    request: Request,
    number: str,
    filial: str | None = None,
    cod_pdv: str | None = None,
    fantasia: str | None = None,
    documento: str | None = None,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area="cliente")
    if not decision.allowed:
        _record_security_event(
            request,
            channel="api",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number,
            area=decision.area,
            reason=decision.reason,
        )
        raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")

    unrestricted_lookup = _decision_has_unrestricted_lookup_access(decision)
    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    try:
        if documento and documento.strip():
            records = dclientes_query_service.search_by_document(
                document=documento,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=20,
            )
        elif filial and cod_pdv:
            if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
                raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")
            records = dclientes_query_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
            )
        elif fantasia and fantasia.strip():
            if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
                raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")
            records = dclientes_query_service.search_by_fantasia(
                query_text=fantasia,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=5,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar no dClientes.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _record_security_event(
        request,
        channel="api",
        event_type="customer_query",
        decision="allowed",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason="success",
        result_count=len(records),
    )
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }


@app.get("/api/inadimplencia/search")
def api_inadimplencia_search(
    request: Request,
    number: str,
    filial: str | None = None,
    cod_pdv: str | None = None,
    fantasia: str | None = None,
    documento: str | None = None,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area="inadimplencia")
    if not decision.allowed:
        _record_security_event(
            request,
            channel="api",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number,
            area=decision.area,
            reason=decision.reason,
        )
        raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")

    unrestricted_lookup = _decision_has_unrestricted_lookup_access(decision)
    if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
        raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")

    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    try:
        if filial and cod_pdv:
            records = inadimplencia_query_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif fantasia and fantasia.strip():
            records = inadimplencia_query_service.search_by_name(
                query_text=fantasia,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif documento and documento.strip():
            records = inadimplencia_query_service.search_by_document(
                document=documento,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar na inadimplencia.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _record_security_event(
        request,
        channel="api",
        event_type="inadimplencia_query",
        decision="allowed",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason="success",
        result_count=len(records),
    )
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }


@app.get("/api/comodatos/search")
def api_comodatos_search(
    request: Request,
    number: str,
    filial: str | None = None,
    cod_pdv: str | None = None,
    fantasia: str | None = None,
    documento: str | None = None,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area="comodato")
    if not decision.allowed:
        _record_security_event(
            request,
            channel="api",
            event_type="rbac_access",
            decision="denied",
            phone_number=decision.normalized_number,
            area=decision.area,
            reason=decision.reason,
        )
        raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")

    unrestricted_lookup = _decision_has_unrestricted_lookup_access(decision)
    if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
        raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")

    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    try:
        if filial and cod_pdv:
            records = comodatos_query_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif fantasia and fantasia.strip():
            records = comodatos_query_service.search_by_name(
                query_text=fantasia,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif documento and documento.strip():
            records = comodatos_query_service.search_by_document(
                document=documento,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar nos comodatos.",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _record_security_event(
        request,
        channel="api",
        event_type="comodatos_query",
        decision="allowed",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason="success",
        result_count=len(records),
    )
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }


@app.get("/api/access/check")
def api_access_check(
    request: Request,
    number: str,
    area: str = "conhecimento",
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
    _require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)
    decision = access_control.authorize(phone_number=number, area=area)
    _record_security_event(
        request,
        channel="api",
        event_type="access_check",
        decision="allowed" if decision.allowed else "denied",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason=decision.reason,
    )
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "normalized_number": decision.normalized_number,
        "area": decision.area,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
    }


@app.get("/api/admin/access/users")
def api_admin_access_users(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    users = _access_call(access_control.list_users)
    _record_security_event(request, channel="api", event_type="admin_list_users", decision="allowed", reason="success")
    return {"total": len(users), "users": users}


@app.post("/api/admin/access/users")
def api_admin_access_users_upsert(
    request: Request,
    payload: AccessUserUpsertRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    user = _access_call(
        access_control.upsert_user,
        phone_number=payload.phone_number,
        name=payload.name,
        is_active=payload.is_active,
        roles=payload.roles,
        sectors=payload.sectors,
        gv_vdes=payload.gv_vdes,
    )
    _record_security_event(
        request,
        channel="api",
        event_type="admin_upsert_user",
        decision="allowed",
        phone_number=user.get("phone_number"),
        reason="success",
    )
    return {"ok": True, "user": user}


@app.post("/api/admin/access/users/bulk")
def api_admin_access_users_bulk_upsert(
    request: Request,
    payload: AccessUserBulkUpsertRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )

    users_payload = list(payload.users or [])
    if not users_payload:
        raise HTTPException(status_code=400, detail="Informe ao menos um cadastro para o lote.")
    if len(users_payload) > 500:
        raise HTTPException(status_code=400, detail="O lote permite no maximo 500 cadastros por envio.")

    saved_users: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(users_payload, start=1):
        try:
            user = access_control.upsert_user(
                phone_number=item.phone_number,
                name=item.name,
                is_active=item.is_active,
                roles=item.roles,
                sectors=item.sectors,
                gv_vdes=item.gv_vdes,
            )
            saved_users.append({"line": index, "user": user})
        except ValueError as exc:
            errors.append(
                {
                    "line": index,
                    "phone_number": str(item.phone_number or "").strip(),
                    "error": str(exc),
                }
            )
            if not payload.continue_on_error:
                raise HTTPException(status_code=400, detail=f"Linha {index}: {exc}") from exc
        except RuntimeError as exc:
            errors.append(
                {
                    "line": index,
                    "phone_number": str(item.phone_number or "").strip(),
                    "error": str(exc),
                }
            )
            if not payload.continue_on_error:
                raise HTTPException(status_code=503, detail=f"Linha {index}: {exc}") from exc

    decision = "allowed" if not errors else ("partial" if saved_users else "failed")
    _record_security_event(
        request,
        channel="api",
        event_type="admin_bulk_upsert_users",
        decision=decision,
        reason=f"saved={len(saved_users)} errors={len(errors)}",
    )
    return {
        "ok": not errors,
        "total_received": len(users_payload),
        "total_saved": len(saved_users),
        "total_failed": len(errors),
        "saved": saved_users,
        "errors": errors,
    }


@app.delete("/api/admin/access/users/{phone_number}")
def api_admin_access_users_delete(
    request: Request,
    phone_number: str,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    user = _access_call(access_control.delete_user, phone_number=phone_number)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_delete_user",
        decision="allowed",
        phone_number=user.get("phone_number"),
        reason="success",
    )
    return {"ok": True, "user": user}


@app.get("/api/admin/access/roles")
def api_admin_access_roles(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    roles = _access_call(access_control.list_roles)
    _record_security_event(request, channel="api", event_type="admin_list_roles", decision="allowed", reason="success")
    return {"total": len(roles), "roles": roles}


@app.get("/api/admin/access/permissions")
def api_admin_access_permissions(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    permissions = _access_call(access_control.list_permissions)
    _record_security_event(request, channel="api", event_type="admin_list_permissions", decision="allowed", reason="success")
    return {"total": len(permissions), "permissions": permissions}


@app.post("/api/admin/access/roles")
def api_admin_access_roles_upsert(
    request: Request,
    payload: AccessRoleUpsertRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    role = _access_call(
        access_control.upsert_role,
        role_name=payload.name,
        description=payload.description,
        permissions=payload.permissions,
    )
    _record_security_event(
        request,
        channel="api",
        event_type="admin_upsert_role",
        decision="allowed",
        reason=role.get("name"),
    )
    return {"ok": True, "role": role}


@app.post("/api/admin/access/seed")
def api_admin_access_seed(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _access_call(access_control.seed_defaults)
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("reason", "Falha ao inicializar RBAC."))
    _record_security_event(request, channel="api", event_type="admin_seed", decision="allowed", reason="success")
    return result


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request) -> Response:
    if _admin_panel_context_from_session_cookie(request):
        return RedirectResponse(url="/admin/imports", status_code=303)
    return HTMLResponse(content=_load_admin_login_html())


@app.post("/api/admin/panel/login")
def api_admin_panel_login(
    request: Request,
    response: Response,
    payload: AdminPanelLoginRequest,
) -> dict[str, Any]:
    _check_admin_panel_login_rate_limit(request)
    context = _admin_panel_context_from_token(payload.token)
    if not context:
        _record_admin_panel_login_failure(request)
        _record_security_event(
            request,
            channel="api",
            event_type="admin_panel_login",
            decision="denied",
            reason="invalid_panel_token",
        )
        raise HTTPException(status_code=401, detail="Token invalido.")
    _clear_admin_panel_login_failures(request)
    _set_admin_panel_session_cookie(response, request, context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_panel_login",
        decision="allowed",
        reason=str(context.get("mode") or "admin"),
    )
    return {
        "ok": True,
        "mode": str(context.get("mode") or "admin"),
        "is_admin": bool(context.get("is_admin")),
        "filiais": list(context.get("filiais", ())),
        "expires_in": ADMIN_PANEL_SESSION_TTL_SECONDS,
    }


@app.post("/api/admin/panel/logout")
def api_admin_panel_logout(request: Request, response: Response) -> dict[str, Any]:
    response.delete_cookie(ADMIN_PANEL_SESSION_COOKIE, path="/")
    _record_security_event(
        request,
        channel="api",
        event_type="admin_panel_logout",
        decision="allowed",
    )
    return {"ok": True}


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/imports", response_class=HTMLResponse)
def admin_import_panel(request: Request) -> Response:
    if not _admin_panel_context_from_session_cookie(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return HTMLResponse(content=_load_admin_import_panel_html())


@app.get("/api/admin/panel/session")
def api_admin_panel_session(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    return {
        "ok": True,
        "mode": str(context.get("mode") or "admin"),
        "is_admin": bool(context.get("is_admin")),
        "filiais": list(context.get("filiais", ())),
        "can_manage_access": bool(context.get("is_admin")),
        "can_view_usage": bool(context.get("is_admin")),
        "can_broadcast": bool(context.get("is_admin") or context.get("mode") == "financeiro"),
        "can_import": True,
        "can_manage_recolhas": True,
    }


@app.get("/api/admin/imports/status")
def api_admin_imports_status(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    payload = _list_admin_import_status()
    _record_security_event(request, channel="api", event_type="admin_import_status", decision="allowed", reason="success")
    return payload


@app.get("/api/admin/imports/history")
def api_admin_imports_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    payload = _list_admin_import_history(limit=limit)
    _record_security_event(request, channel="api", event_type="admin_import_history", decision="allowed", reason="success")
    return payload


@app.post("/api/admin/imports/validate")
def api_admin_imports_validate(
    request: Request,
    payload: AdminImportActionRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _access_call(_run_admin_import_validation, payload.dataset)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_import_validate",
        decision="allowed",
        reason=result.get("dataset"),
    )
    return {"ok": True, **result}


@app.post("/api/admin/imports/run", status_code=202)
def api_admin_imports_run(
    request: Request,
    payload: AdminImportActionRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _queue_admin_import(payload.dataset, reference_date=payload.reference_date, context=context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_import_run",
        decision="allowed",
        reason=result.get("dataset"),
    )
    return {"ok": True, "queued": True, **result}


@app.post("/api/admin/imports/upload")
def api_admin_imports_upload(
    request: Request,
    dataset: str = Form(...),
    files: list[UploadFile] = File(...),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _access_call(_store_admin_import_uploads, dataset, files, context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_import_upload",
        decision="allowed",
        reason=result.get("dataset"),
    )
    return {"ok": True, **result}


@app.get("/api/admin/recolhas")
def api_admin_recolhas(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    payload = _list_admin_recolhas(context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_recolhas_list",
        decision="allowed",
        reason=f"total={payload.get('total')}",
    )
    return {"ok": True, **payload}


@app.get("/api/admin/giro/recolha-dashboard")
def api_admin_giro_recolha_dashboard(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
    min_gap: str = Query(default="1"),
    operation: list[str] | None = Query(default=None),
    city: list[str] | None = Query(default=None),
    district: list[str] | None = Query(default=None),
    seller: list[str] | None = Query(default=None),
    manager: list[str] | None = Query(default=None),
    visit_day: list[str] | None = Query(default=None),
    zero_only: bool = Query(default=False),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    try:
        payload = _build_admin_giro_recolha_dashboard(
            context,
            limit=limit,
            min_gap=min_gap,
            operation=operation,
            city=city,
            district=district,
            seller=seller,
            manager=manager,
            visit_day=visit_day,
            zero_only=zero_only,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _record_security_event(
        request,
        channel="api",
        event_type="admin_giro_recolha_dashboard",
        decision="allowed",
        reason=f"total={payload.get('total')}",
    )
    return {"ok": True, **payload}


@app.get("/api/admin/giro/recolha-filter-options")
def api_admin_giro_recolha_filter_options(
    request: Request,
    min_gap: str = Query(default="1"),
    operation: list[str] | None = Query(default=None),
    city: list[str] | None = Query(default=None),
    district: list[str] | None = Query(default=None),
    seller: list[str] | None = Query(default=None),
    manager: list[str] | None = Query(default=None),
    visit_day: list[str] | None = Query(default=None),
    zero_only: bool = Query(default=False),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    try:
        payload = _build_admin_giro_recolha_filter_options(
            context,
            min_gap=min_gap,
            operation=operation,
            city=city,
            district=district,
            seller=seller,
            manager=manager,
            visit_day=visit_day,
            zero_only=zero_only,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, **payload}


@app.get("/api/admin/critica/dashboard")
def api_admin_critica_dashboard(
    request: Request,
    date_value: str | None = Query(default=None, alias="date"),
    limit: int = Query(default=200, ge=1, le=1000),
    operation: list[str] | None = Query(default=None),
    sector: list[str] | None = Query(default=None),
    seller: list[str] | None = Query(default=None),
    manager: list[str] | None = Query(default=None),
    city: list[str] | None = Query(default=None),
    district: list[str] | None = Query(default=None),
    origin: list[str] | None = Query(default=None),
    problem: list[str] | None = Query(default=None),
    search: str = Query(default=""),
    only_problems: bool = Query(default=True),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    try:
        payload = _build_admin_critica_dashboard(
            context,
            target_date=_parse_admin_critica_date(date_value),
            limit=limit,
            operation=operation,
            sector=sector,
            seller=seller,
            manager=manager,
            city=city,
            district=district,
            origin=origin,
            problem=problem,
            search=search,
            only_problems=only_problems,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _record_security_event(
        request,
        channel="api",
        event_type="admin_critica_dashboard",
        decision="allowed",
        reason=f"total={payload.get('total')}",
    )
    return {"ok": True, **payload}


@app.get("/api/admin/giro/recolha-routes")
def api_admin_giro_recolha_routes(
    request: Request,
    limit: int = Query(default=500, ge=1, le=1000),
    min_gap: str = Query(default="1"),
    operation: list[str] | None = Query(default=None),
    city: list[str] | None = Query(default=None),
    district: list[str] | None = Query(default=None),
    seller: list[str] | None = Query(default=None),
    manager: list[str] | None = Query(default=None),
    visit_day: list[str] | None = Query(default=None),
    zero_only: bool = Query(default=False),
    max_route_size: int = Query(default=12, ge=1, le=50),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    try:
        payload = _build_admin_giro_recolha_routes(
            context,
            limit=limit,
            min_gap=min_gap,
            operation=operation,
            city=city,
            district=district,
            seller=seller,
            manager=manager,
            visit_day=visit_day,
            zero_only=zero_only,
            max_route_size=max_route_size,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _record_security_event(
        request,
        channel="api",
        event_type="admin_giro_recolha_routes",
        decision="allowed",
        reason=f"total={payload.get('total')}",
    )
    return {"ok": True, **payload}


@app.patch("/api/admin/recolhas/bulk")
def api_admin_recolhas_bulk_update(
    request: Request,
    payload: AdminRecolhaBulkUpdateRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _update_admin_recolhas_bulk(payload, context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_recolha_bulk_update",
        decision="allowed",
        reason=f"updated={result.get('updated')};errors={len(result.get('errors') or [])}",
    )
    return {"ok": True, **result}


@app.post("/api/admin/recolhas/import")
def api_admin_recolhas_import(
    request: Request,
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _import_admin_recolhas_csv(file, context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_recolha_import",
        decision="allowed",
        reason=f"imported={result.get('imported')};skipped={result.get('skipped')}",
    )
    return {"ok": True, **result}


@app.get("/api/admin/recolhas/export")
def api_admin_recolhas_export(
    request: Request,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> Response:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    csv_bytes, total, filename = _export_admin_recolhas_csv(
        context,
        start_date=start_date,
        end_date=end_date,
    )
    _record_security_event(
        request,
        channel="api",
        event_type="admin_recolha_export",
        decision="allowed",
        reason=f"total={total}",
    )
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.patch("/api/admin/recolhas/{recolha_id}")
def api_admin_recolhas_update(
    request: Request,
    recolha_id: str,
    payload: AdminRecolhaUpdateRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _update_admin_recolha(recolha_id, payload, context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_recolha_update",
        decision="allowed",
        reason=str(recolha_id or ""),
    )
    return {"ok": True, **result}


@app.delete("/api/admin/recolhas/{recolha_id}")
def api_admin_recolhas_delete(
    request: Request,
    recolha_id: str,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _delete_admin_recolha(recolha_id, context)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_recolha_delete",
        decision="allowed",
        reason=str(recolha_id or ""),
    )
    return {"ok": True, **result}


@app.get("/api/admin/usage/evolution")
def api_admin_usage_evolution(
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    payload = _list_admin_evolution_usage(days=days)
    _record_security_event(
        request,
        channel="api",
        event_type="admin_usage_evolution",
        decision="allowed",
        reason=f"days={payload.get('window_days')}",
    )
    return payload


@app.get("/api/admin/usage/evolution/report", response_class=PlainTextResponse)
def api_admin_usage_evolution_report(
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=2000, ge=1, le=5000),
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> PlainTextResponse:
    _require_admin_api_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    payload = _list_admin_evolution_usage(days=days, top_limit=limit, recent_limit=5)
    csv_content = _build_evolution_usage_avg_report_csv(payload)
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"relatorio_media_msg_por_dia_{payload.get('window_days', days)}d_{generated_at}.csv"
    _record_security_event(
        request,
        channel="api",
        event_type="admin_usage_evolution_report",
        decision="allowed",
        reason=f"days={payload.get('window_days')};limit={limit}",
    )
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/admin/broadcast/options")
def api_admin_broadcast_options(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    payload = _list_admin_broadcast_options(context)
    _record_security_event(request, channel="api", event_type="admin_broadcast_options", decision="allowed")
    return {"ok": True, **payload}


@app.get("/api/admin/broadcast/status")
def api_admin_broadcast_status(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    _record_security_event(request, channel="api", event_type="admin_broadcast_status", decision="allowed")
    return {"ok": True, **_snapshot_admin_broadcast_state(context)}


@app.post("/api/admin/broadcast/preview")
def api_admin_broadcast_preview(
    request: Request,
    payload: AdminBroadcastRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _build_admin_broadcast_payload(
        filial=payload.filial,
        action=payload.action,
        day=payload.day,
        target_mode=payload.target_mode,
        target_audience=payload.target_audience,
        target_number=payload.target_number,
        selected_numbers=payload.selected_numbers,
        require_selection=False,
        context=context,
    )
    _record_security_event(
        request,
        channel="api",
        event_type="admin_broadcast_preview",
        decision="allowed",
        reason=(
            f"filial={result['filial']};action={result['action']};"
            f"day={result['day']};target_mode={result['target_mode']};"
            f"target_audience={result['target_audience']};total={result['total']}"
        ),
    )
    return {"ok": True, **result}


@app.post("/api/admin/broadcast/run", status_code=202)
def api_admin_broadcast_run(
    request: Request,
    payload: AdminBroadcastRequest,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    context = _require_admin_panel_auth(
        request=request,
        authorization=authorization,
        x_api_token=x_api_token,
        x_admin_token=x_admin_token,
    )
    result = _queue_admin_broadcast(
        payload.filial,
        payload.action,
        payload.day,
        payload.target_mode,
        payload.target_audience,
        payload.target_number,
        payload.selected_numbers,
        context,
    )
    _record_security_event(
        request,
        channel="api",
        event_type="admin_broadcast_run",
        decision="allowed",
        reason=(
            f"filial={result['filial']};action={result['action']};"
            f"day={result['day']};target_mode={result['target_mode']};"
            f"target_audience={result['target_audience']};total={result['total']}"
        ),
    )
    return {"ok": True, "queued": True, **result}


@app.post("/webhook/evolution")
def webhook_evolution(
    request: Request,
    payload: dict[str, Any],
    x_bot_token: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_webhook_token(request=request, x_bot_token=x_bot_token, payload=payload)

    incoming = extract_incoming_message(payload)
    if incoming is None:
        _record_security_event(request, channel="webhook", event_type="incoming_event", decision="ignored", reason="non_processable")
        return {"received": True, "handled": False, "reason": "evento nao processavel"}

    requested_area = "cliente"
    return _queue_incoming_webhook(request=request, incoming=incoming, requested_area=requested_area, event_type_prefix="webhook")


@app.get("/webhook/meta", response_class=PlainTextResponse)
def webhook_meta_verify(
    request: Request,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> str:
    challenge = verify_meta_cloud_webhook_token(
        mode=hub_mode,
        verify_token=hub_verify_token,
        challenge=hub_challenge,
        config=meta_cloud_client.config,
        shared_token=settings.verify_token.strip(),
    )
    if challenge is None:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="meta_verify",
            decision="denied",
            reason="invalid_verify_token",
        )
        raise HTTPException(status_code=403, detail="Token de verificacao invalido.")
    _record_security_event(
        request,
        channel="meta_webhook",
        event_type="meta_verify",
        decision="allowed",
        reason="verify_token",
    )
    return challenge


@app.post("/webhook/meta")
async def webhook_meta(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, Any]:
    if not settings.meta_cloud_enabled:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="incoming_event",
            decision="ignored",
            reason="meta_cloud_disabled",
        )
        return {"received": True, "handled": False, "reason": "meta_cloud_disabled"}

    raw_body = await request.body()
    _require_meta_cloud_signature(
        request,
        raw_body=raw_body,
        x_hub_signature_256=x_hub_signature_256,
    )
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="incoming_event",
            decision="denied",
            reason="invalid_json",
        )
        raise HTTPException(status_code=400, detail="Payload JSON invalido.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload JSON invalido.")

    incoming = extract_meta_cloud_incoming_message(payload)
    if incoming is None:
        _record_security_event(
            request,
            channel="meta_webhook",
            event_type="incoming_event",
            decision="ignored",
            reason="non_processable",
        )
        return {"received": True, "handled": False, "reason": "evento nao processavel"}

    requested_area = "cliente"
    return _queue_incoming_webhook(
        request=request,
        incoming=incoming,
        requested_area=requested_area,
        event_type_prefix="meta_webhook",
    )
