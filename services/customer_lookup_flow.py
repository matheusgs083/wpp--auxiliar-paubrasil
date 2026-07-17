from __future__ import annotations

import base64
import io
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from bot_api.commercial_scope import (
    extract_scope_input_tokens,
    format_dc_scope,
    format_filial_scope,
    format_gv_scope,
    format_scope_list,
    format_sector_scope,
    normalize_dc_scope_input,
    normalize_filial_scope_input,
    normalize_numeric_code,
    normalize_gv_scope_input,
    normalize_sector_scope_input,
    normalize_stored_scope_value,
    split_scope_pair,
)
from bot_api.models import IncomingMessage, InteractiveOption, MediaAttachment, OutgoingMessage
from bot_api.security.access_control import (
    AccessControl,
    AccessDecision,
    ROLE_ADMIN,
    ROLE_DIRETOR_COMERCIAL,
    ROLE_FINANCEIRO,
    ROLE_GERENTE_VENDAS,
    ROLE_VENDEDOR,
)
from bot_api.services.dclientes_query_service import (
    DClienteRecord,
    DClientesManagementSummary,
    DClientesQueryService,
    VisitSellerSummary,
)
from bot_api.services.clientes_score_query_service import ClienteScoreRecord, ClientesScoreQueryService
from bot_api.services.comodatos_query_service import (
    ComodatoClientSummary,
    ComodatoRecord,
    ComodatosQueryService,
)
from bot_api.services.filial_labels import DEFAULT_FILIAL_LABELS, FILIAL_LABELS, set_filial_labels
from bot_api.services.critica_rn_query_service import (
    CriticaPdfCurrentImportRequiredError,
    CriticaRnQueryService,
    CriticaRnRecord,
    CriticaRnSummary,
)
from bot_api.services.giro_query_service import (
    GiroClientRecord,
    GiroFilialSummary,
    GiroManagementSummary,
    GiroQueryService,
    GiroSellerSummary,
    GiroScopeSummary,
    GiroZeroBaseRecord,
)
from bot_api.services.documentacao_pendente_query_service import (
    DocumentacaoPendenteClientRecord,
    DocumentacaoPendenteFilialSummary,
    DocumentacaoPendenteQueryService,
    DocumentacaoPendenteScopeSummary,
)
from bot_api.services.flows.access_policy_flow import AccessPolicyFlow
from bot_api.services.flows.admin_access_flow import AdminAccessFlow
from bot_api.services.flows.critica_flow import CriticaFlow
from bot_api.services.flows.customer_router import CustomerRouter
from bot_api.services.flows.finance_flow import FinanceFlow
from bot_api.services.flows.main_menu_flow import MainMenuFlow
from bot_api.services.flows.navigation_flow import NavigationFlow
from bot_api.services.flows.recolha_flow import RecolhaFlow
from bot_api.services.flows.search_flow import SearchFlow
from bot_api.services.prazo_limite_query_service import (
    PrazoLimiteClientRecord,
    PrazoLimiteEntryRecord,
    PrazoLimiteQueryService,
)
from bot_api.services.boletos_query_service import BoletosQueryService
from bot_api.services.recolha_request_service import RecolhaRequestRecord, RecolhaRequestService
from bot_api.integrations.payip_client import PayipError, PayipMfaRequired
from bot_api.services.payip_payments_service import DEFAULT_PAYMENT_AMOUNT_TOLERANCE, PayipPaymentsService
from bot_api.services.inadimplencia_query_service import (
    InadimplenciaClientSummary,
    InadimplenciaFinanceManagementSummary,
    InadimplenciaFinanceSellerSummary,
    InadimplenciaQueryService,
    InadimplenciaRecord,
    InadimplenciaVisitAlert,
    InadimplenciaVisitRiskSummary,
)

MENU_SEARCH = "menu:buscar_cliente"
MENU_INADIMPLENCIA = "menu:inadimplencia"
MENU_COMODATOS = "menu:comodatos"
MENU_GIRO = "menu:giro"
MENU_DOCUMENTACAO = "menu:documentacao"
MENU_RECOLHA = "menu:recolha"
MENU_SELLER_FINANCEIRO = "menu:seller_financeiro"
MENU_CRITICA = "menu:critica"
MENU_VISIT_DAY = "menu:visitas_do_dia"
MENU_FINANCEIRO = "menu:financeiro"
MENU_GV_SUMMARY = "menu:gv_summary"
MENU_MANAGER = "menu:gerente_vendas"
MENU_SELLER_SUMMARY = "menu:seller_summary"
MENU_SELLER_RISK = "menu:seller_risk"
SELLER_FINANCE_ACTION_RECOLHA = "seller_finance:recolha"
SELLER_FINANCE_ACTION_BOLETO = "seller_finance:boleto"
SEARCH_BY_REGISTRATION = "search:cadastro"
SEARCH_BY_FANTASIA = "search:fantasia"
SEARCH_BY_DOCUMENT = "search:documento"
SEARCH_BY_INADIMPLENTES_BASE = "search:inadimplentes_base"
SEARCH_BY_VISIT_DAY = "search:visit_day"
SEARCH_BY_GIRO_ZERO_BASE = "search:giro_zero_base"
MENU_ADMIN_ACCESS = "menu:admin_access"

ADMIN_ACTION_CREATE = "admin:action:create"
ADMIN_ACTION_UPDATE = "admin:action:update"
ADMIN_ACTION_LIST = "admin:action:list"
ADMIN_ACTION_RENAME = "admin:action:rename"
ADMIN_ACTION_SUMMARY = "admin:action:summary"
ADMIN_ACTION_HEALTH = "admin:action:health"
ADMIN_ACTION_CHECK = "admin:action:check"

ADMIN_ROLE_VENDEDOR = "admin:role:vendedor"
ADMIN_ROLE_GERENTE_VENDAS = "admin:role:gerente_vendas"
ADMIN_ROLE_GESTOR = "admin:role:gestor"
ADMIN_ROLE_ADMIN = "admin:role:admin"
ADMIN_ROLE_FINANCEIRO = "admin:role:financeiro"
ADMIN_ROLE_DIRETOR_COMERCIAL = "admin:role:diretor_comercial"

ADMIN_CONFIRM = "admin:confirm"
ADMIN_CANCEL = "admin:cancel"

FINANCE_ACTION_SUMMARY = "finance:action:summary"
FINANCE_ACTION_LIST = "finance:action:list"
FINANCE_ACTION_TOP = "finance:action:top"
FINANCE_ACTION_UPCOMING = "finance:action:upcoming"
FINANCE_ACTION_VISIT_RISK = "finance:action:visit_risk"
FINANCE_ACTION_GV_SUMMARY = "finance:action:gv_summary"
FINANCE_ACTION_GIRO = "finance:action:giro"
FINANCE_ACTION_PRAZO_LIMITE = "finance:action:prazo_limite"
FINANCE_ACTION_PAYIP = "finance:action:payip"
FINANCE_ACTION_RECOLHAS = "finance:action:recolhas"
PAYIP_ACTION_STATUS = "payip:action:status"
PAYIP_ACTION_TEST_LOGIN = "payip:action:test_login"
PAYIP_ACTION_SEARCH_INVOICE = "payip:action:search_invoice"
PAYIP_ACTION_PENDING_CLIENT = "payip:action:pending_client"
PAYIP_ACTION_CLIENT = "payip:action:client"
PAYIP_ACTION_CREATE_CHARGE = "payip:action:create_charge"
PAYIP_ACTION_CREATE_CLIENT = "payip:action:create_client"
PAYIP_ACTION_STATEMENT = "payip:action:statement"
PAYIP_ACTION_AMOUNT_DAY = "payip:action:amount_day"
PAYIP_ACTION_VALIDATE_DAY = "payip:action:validate_day"
PAYIP_ACTION_IMPORT_BATCH = "payip:action:import_batch"
PAYIP_ACTION_ROUTES = "payip:action:routes"
REPEAT_SEARCH_REGISTRATION = "repeat:search:registration"
REPEAT_SEARCH_DOCUMENT = "repeat:search:document"
REPEAT_SEARCH_NAME = "repeat:search:name"
REPEAT_PAYIP_INVOICE = "repeat:payip:invoice"
REPEAT_PAYIP_PENDING_CLIENT = "repeat:payip:pending_client"
REPEAT_PAYIP_CLIENT = "repeat:payip:client"
REPEAT_PAYIP_CREATE_CHARGE = "repeat:payip:create_charge"
REPEAT_PAYIP_CREATE_CLIENT = "repeat:payip:create_client"
REPEAT_PAYIP_STATEMENT = "repeat:payip:statement"
REPEAT_PAYIP_AMOUNT_DAY = "repeat:payip:amount_day"
REPEAT_PAYIP_VALIDATE_DAY = "repeat:payip:validate_day"
REPEAT_PAYIP_IMPORT_BATCH = "repeat:payip:import_batch"
REPEAT_PAYIP_ROUTES = "repeat:payip:routes"

FINANCE_SUMMARY_TOTAL = "finance:summary:total"
FINANCE_SUMMARY_BY_FILIAL = "finance:summary:by_filial"
FINANCE_SUMMARY_BY_GV = "finance:summary:by_gv"
FINANCE_SUMMARY_BY_SELLER = "finance:summary:by_seller"
FINANCE_SUMMARY_DOCUMENTACAO_BY_FILIAL = "finance:summary:documentacao_by_filial"

FINANCE_DUE_IN_TWO_DAYS = "finance:due:in_two_days"
FINANCE_DUE_TOMORROW = "finance:due:tomorrow"
FINANCE_DUE_TODAY = "finance:due:today"
FINANCE_DUE_OVERDUE = "finance:due:overdue"
MANAGER_SUMMARY_TOTAL = "manager:summary:total"
MANAGER_SUMMARY_BY_FILIAL = "manager:summary:by_filial"
MANAGER_ACTION_LIST = "manager:action:list"
MANAGER_ACTION_UPCOMING = "manager:action:upcoming"
MANAGER_ACTION_VISIT_RISK = "manager:action:visit_risk"
MANAGER_ACTION_BY_SELLER = "manager:action:by_seller"
MANAGER_ACTION_GIRO = "manager:action:giro"
DIRECTOR_SUMMARY_TOTAL = "director:summary:total"
DIRECTOR_SUMMARY_BY_REVENDA = "director:summary:by_revenda"
DIRECTOR_ACTION_RANKING = "director:action:ranking"
DIRECTOR_ACTION_VISIT_RISK = "director:action:visit_risk"
DIRECTOR_ACTION_TOP_DEBTORS = "director:action:top_debtors"
DIRECTOR_ACTION_BY_FILIAL = "director:action:by_filial"
DIRECTOR_ACTION_GIRO = "director:action:giro"

GIRO_MODE_TOTAL = "giro:mode:total"
GIRO_MODE_BY_FILIAL = "giro:mode:by_filial"
GIRO_MODE_BY_GV = "giro:mode:by_gv"

CLARIFY_SUMMARY_FINANCE = "clarify:summary:finance"
CLARIFY_SUMMARY_MANAGER = "clarify:summary:manager"
CLARIFY_SUMMARY_DIRECTOR = "clarify:summary:director"
CLARIFY_SUMMARY_SELLER = "clarify:summary:seller"
CLARIFY_TODAY_FINANCE_DUE = "clarify:today:finance:due"
CLARIFY_TODAY_FINANCE_RISK = "clarify:today:finance:risk"
CLARIFY_TODAY_MANAGER_VISITS = "clarify:today:manager:visits"
CLARIFY_TODAY_MANAGER_RISK = "clarify:today:manager:risk"
CLARIFY_TODAY_DIRECTOR_VISITS = "clarify:today:director:visits"
CLARIFY_TODAY_DIRECTOR_RISK = "clarify:today:director:risk"
CLARIFY_TODAY_SELLER_VISITS = "clarify:today:seller:visits"
CLARIFY_TODAY_SELLER_RISK = "clarify:today:seller:risk"
CLARIFY_GIRO_CLIENT = "clarify:giro:client"
CLARIFY_GIRO_FINANCE_TOTAL = "clarify:giro:finance:total"
CLARIFY_GIRO_FINANCE_BY_FILIAL = "clarify:giro:finance:by_filial"
CLARIFY_GIRO_FINANCE_BY_GV = "clarify:giro:finance:by_gv"
CLARIFY_GIRO_MANAGER_TOTAL = "clarify:giro:manager:total"
CLARIFY_GIRO_MANAGER_BY_FILIAL = "clarify:giro:manager:by_filial"
CLARIFY_GIRO_DIRECTOR_BY_GV = "clarify:giro:director:by_gv"
CLARIFY_GIRO_DIRECTOR_BY_FILIAL = "clarify:giro:director:by_filial"
CLARIFY_SCOPE_INADIMPLENCIA_LIST = "clarify:scope:inadimplencia:list"
CLARIFY_LAST_CLIENT_RECORD = "clarify:client:last_record"

FANTASIA_PICK_PREFIX = "fantasia:pick:"
INADIMPLENCIA_CLIENT_PICK_PREFIX = "inadclient:pick:"
INADIMPLENCIA_PAGE_NEXT = "inadclient:page:next"
INADIMPLENCIA_PAGE_PREV = "inadclient:page:prev"
FINANCE_VISIT_RISK_PICK_PREFIX = "finance:visit_risk:pick:"
VISIT_DAY_PICK_PREFIX = "visitday:pick:"
VISIT_SELLER_PICK_PREFIX = "visitseller:pick:"
GIRO_VISIT_GV_PICK_PREFIX = "girovisitgv:pick:"
GIRO_VISIT_SELLER_PICK_PREFIX = "girovisitseller:pick:"
DOCUMENTACAO_VISIT_GV_PICK_PREFIX = "docvisitgv:pick:"
DOCUMENTACAO_VISIT_SELLER_PICK_PREFIX = "docvisitseller:pick:"
INADIMPLENCIA_HEADER_PREFIX = "inadimplencia:header:"
INADIMPLENCIA_SCOPE_LIST_PREFIX = "inadimplencia:scope:"
INADIMPLENCIA_PAGE_SIZE = 20
INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL = "finance_base_total"
INADIMPLENCIA_CONTEXT_SCOPE_BASE = "scope_base"
INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS = "director_top_debtors"
MENU_BACK_COMMANDS = frozenset({"a", "ant", "anterior"})
PAGE_NEXT_COMMANDS = frozenset({"p", "prox", "proximo", "prxx"})

LOCAL_TIMEZONE = timezone(timedelta(hours=-3))
VISIT_DAY_CHOICES = (
    ("SEG/", "Segunda"),
    ("TER/", "Terca"),
    ("QUA/", "Quarta"),
    ("QUI/", "Quinta"),
    ("SEX/", "Sexta"),
    ("SAB/", "Sabado"),
    ("DOM/", "Domingo"),
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PayipPixPayload:
    label: str
    pix_code: str
    qr_image: str = ""
    payment_id: str = ""
    filial: str = ""
    company_id: str = ""


@dataclass
class LookupSession:
    step: str = "idle"
    search_context: str = "cliente"
    return_menu: str = ""
    repeat_action: str = ""
    filial: str = ""
    target_phone: str = ""
    current_name: str = ""
    target_name: str = ""
    target_role: str = ""
    target_sectors: tuple[str, ...] = ()
    target_gv_vdes: tuple[str, ...] = ()
    current_roles: tuple[str, ...] = ()
    current_sectors: tuple[str, ...] = ()
    current_gv_vdes: tuple[str, ...] = ()
    admin_action: str = ""
    current_is_active: bool = True
    fantasia_query: str = ""
    fantasia_results: tuple[DClienteRecord, ...] = ()
    inadimplencia_client_summaries: tuple[InadimplenciaClientSummary, ...] = ()
    inadimplencia_total_available: int = 0
    inadimplencia_list_context: str = ""
    inadimplencia_page: int = 1
    inadimplencia_page_size: int = INADIMPLENCIA_PAGE_SIZE
    comodato_client_summaries: tuple[ComodatoClientSummary, ...] = ()
    selected_visit_day: str = ""
    visit_day_options: tuple[str, ...] = ()
    visit_seller_summaries: tuple[VisitSellerSummary, ...] = ()
    visit_group_summaries: tuple[VisitSellerSummary, ...] = ()
    selected_visit_gv: str = ""
    finance_gv_options: tuple[str, ...] = ()
    summary_filial_options: tuple[str, ...] = ()
    giro_visit_sector_summaries: tuple[GiroVisitSectorSummary, ...] = ()
    giro_visit_summary_text: str = ""
    selected_giro_visit_gv: str = ""
    documentacao_visit_sector_summaries: tuple[DocumentacaoVisitSectorSummary, ...] = ()
    documentacao_visit_records: tuple[DocumentacaoPendenteClientRecord, ...] = ()
    documentacao_visit_summary_text: str = ""
    selected_documentacao_visit_gv: str = ""
    visit_risk_day_options: tuple[str, ...] = ()
    visit_risk_summaries: tuple[InadimplenciaVisitRiskSummary, ...] = ()
    selected_visit_risk_gv: str = ""
    selected_visit_risk_token: str = ""
    selected_visit_risk_label: str = ""
    boleto_filial: str = ""
    boleto_cod_pdv: str = ""
    boleto_option_count: int = 0
    clarification_title: str = ""
    clarification_prompt: str = ""
    clarification_footer: str = ""
    clarification_options: tuple[InteractiveOption, ...] = ()
    last_intent: str = ""
    last_search_context: str = ""
    last_query_text: str = ""
    last_client_filial: str = ""
    last_client_cod_pdv: str = ""
    last_client_name: str = ""
    last_visit_day: str = ""
    last_context_updated_at: datetime | None = None
    payip_pending_action: str = ""
    payip_pending_invoice: str = ""
    payip_pending_client_code: str = ""
    payip_pending_filial: str = ""
    payip_pending_status: str = ""
    payip_pending_date_start: str = ""
    payip_pending_date_end: str = ""
    payip_pending_amount: str = ""
    payip_pending_day: str = ""
    payip_pending_tolerance: str = ""
    payip_import_missing_client_codes: tuple[str, ...] = ()
    payip_pix_payloads: tuple[PayipPixPayload, ...] = ()
    payip_charge_filial: str = ""
    payip_charge_client_code: str = ""
    payip_charge_external_id: str = ""
    payip_charge_client_name: str = ""
    payip_charge_tax_payer_id: str = ""
    payip_charge_invoice: str = ""
    payip_charge_amount: str = ""
    payip_charge_due_date: str = ""
    payip_charge_rate_amount: str = ""
    payip_charge_interest_perc: str = ""
    recolha_filial: str = ""
    recolha_nb: str = ""
    recolha_cliente: str = ""
    recolha_client_options: tuple[DClienteRecord, ...] = ()
    recolha_revenda: str = ""
    recolha_setor: str = ""
    recolha_cidade: str = ""
    recolha_rn: str = ""
    recolha_comodato: str = ""
    recolha_comodato_options: tuple[ComodatoRecord, ...] = ()
    recolha_obs: str = ""
    recolha_pending_action: str = ""
    recolha_pending_identifier: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class HybridSearchRequest:
    search_mode: str = ""
    query_text: str = ""
    document: str = ""
    filial: str = ""
    cod_pdv: str = ""
    open_base_list: bool = False
    open_giro_zero_base_list: bool = False
    visit_day_label: str = ""


@dataclass(frozen=True)
class HybridFinanceRequest:
    action: str = ""
    due_bucket: str = ""
    visit_day_label: str = ""
    giro_mode: str = ""
    summary_mode: str = ""
    query_text: str = ""
    document: str = ""
    filial: str = ""
    cod_pdv: str = ""
    clarify_today: bool = False


@dataclass(frozen=True)
class GiroVisitOpportunity:
    manager_code: str
    seller_code: str
    setor_code: str
    cod_pdv: str
    client_name: str
    total_caixas: str
    gap_caixas: str
    gap_detail: str


@dataclass(frozen=True)
class GiroVisitSectorSummary:
    seller_code: str
    manager_code: str
    client_count: int
    total_caixas: str
    total_gap: str


@dataclass(frozen=True)
class DocumentacaoVisitSectorSummary:
    seller_code: str
    manager_code: str
    client_count: int
    pending_document_count: int


class CustomerLookupFlow:
    def __init__(
        self,
        query_service: DClientesQueryService,
        inadimplencia_service: InadimplenciaQueryService,
        comodatos_service: ComodatosQueryService,
        giro_service: GiroQueryService,
        documentacao_pendente_service: DocumentacaoPendenteQueryService,
        prazo_limite_service: PrazoLimiteQueryService,
        access_control: AccessControl,
        boletos_service: BoletosQueryService | None = None,
        payip_payments_service: PayipPaymentsService | None = None,
        recolha_request_service: RecolhaRequestService | None = None,
        critica_rn_service: CriticaRnQueryService | None = None,
        clientes_score_service: ClientesScoreQueryService | None = None,
        session_ttl_minutes: int = 20,
    ) -> None:
        self.query_service = query_service
        self.inadimplencia_service = inadimplencia_service
        self.comodatos_service = comodatos_service
        self.giro_service = giro_service
        self.documentacao_pendente_service = documentacao_pendente_service
        self.prazo_limite_service = prazo_limite_service
        self.boletos_service = boletos_service
        self.payip_payments_service = payip_payments_service
        self.critica_rn_service = critica_rn_service
        self.clientes_score_service = clientes_score_service
        self._cliente_score_last_lookup_available = False
        self.recolha_request_service = recolha_request_service or RecolhaRequestService(
            Path("exports") / "recolhas" / "solicitacoes_recolha.csv"
        )
        self.access_control = access_control
        self.session_ttl = timedelta(minutes=max(session_ttl_minutes, 5))
        self.response_cache_ttl = timedelta(seconds=45)
        self.sessions: dict[str, LookupSession] = {}
        self._response_cache: dict[tuple[Any, ...], tuple[datetime, OutgoingMessage]] = {}
        self._lock = RLock()
        self.access_policy_flow = AccessPolicyFlow(self)
        self.admin_access_flow = AdminAccessFlow(self)
        self.finance_flow = FinanceFlow(self)
        self.critica_flow = CriticaFlow(self)
        self.recolha_flow = RecolhaFlow(self)
        self.search_flow = SearchFlow(self)
        self.navigation_flow = NavigationFlow(self)
        self.main_menu_flow = MainMenuFlow(self)
        self.customer_router = CustomerRouter(self)

    def _peek_expired_session(self, sender: str) -> LookupSession | None:
        session = self.sessions.get(sender)
        if session is None:
            return None
        if datetime.now(timezone.utc) - session.updated_at > self.session_ttl:
            return session
        return None

    def handle(self, incoming: IncomingMessage, decision: AccessDecision) -> OutgoingMessage:
        with self._lock:
            return self._handle_locked(incoming, decision)

    def _handle_locked(self, incoming: IncomingMessage, decision: AccessDecision) -> OutgoingMessage:
        return self.customer_router.handle_locked(incoming, decision)

    def _handle_menu_back_navigation(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage | None:
        return self.navigation_flow._handle_menu_back_navigation(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _resume_post_result_navigation(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage | None:
        return self.navigation_flow._resume_post_result_navigation(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _repeat_post_result_navigation(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        return self.navigation_flow._repeat_post_result_navigation(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _store_post_result_navigation(self, sender: str, session: LookupSession, *, return_menu: str, repeat_action: str = '') -> None:
        return self.navigation_flow._store_post_result_navigation(
            sender=sender,
            session=session,
            return_menu=return_menu,
            repeat_action=repeat_action,
        )

    def _with_post_result_navigation(self, sender: str, session: LookupSession, outgoing: OutgoingMessage, *, return_menu: str, repeat_action: str = '') -> OutgoingMessage:
        return self.navigation_flow._with_post_result_navigation(
            sender=sender,
            session=session,
            outgoing=outgoing,
            return_menu=return_menu,
            repeat_action=repeat_action,
        )

    def _prepare_search_session(self, session: LookupSession, *, search_context: str) -> None:
        return self.search_flow._prepare_search_session(
            session=session,
            search_context=search_context,
        )

    def _open_search_context(self, sender: str, session: LookupSession, *, search_context: str, decision: AccessDecision) -> OutgoingMessage:
        return self.search_flow._open_search_context(
            sender=sender,
            session=session,
            search_context=search_context,
            decision=decision,
        )

    def _run_search_menu_option(self, sender: str, session: LookupSession, decision: AccessDecision, *, option_id: str) -> OutgoingMessage:
        return self.search_flow._run_search_menu_option(
            sender=sender,
            session=session,
            decision=decision,
            option_id=option_id,
        )

    def _activate_search_mode(self, sender: str, session: LookupSession, *, search_mode: str) -> OutgoingMessage:
        return self.search_flow._activate_search_mode(
            sender=sender,
            session=session,
            search_mode=search_mode,
        )

    def _run_name_search(self, sender: str, session: LookupSession, decision: AccessDecision, *, query_text: str) -> OutgoingMessage:
        return self.search_flow._run_name_search(
            sender=sender,
            session=session,
            decision=decision,
            query_text=query_text,
        )

    def _run_document_lookup(self, sender: str, session: LookupSession, decision: AccessDecision, *, document: str, return_menu: str = 'search_menu') -> OutgoingMessage:
        return self.search_flow._run_document_lookup(
            sender=sender,
            session=session,
            decision=decision,
            document=document,
            return_menu=return_menu,
        )

    def _apply_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        return self.search_flow._apply_visit_day_selection(
            sender=sender,
            session=session,
            decision=decision,
            selected_visit_day=selected_visit_day,
        )

    def _open_grouped_visit_day_selection(self, *, sender: str, session: LookupSession, selected_visit_day: str, visit_summaries: list[VisitSellerSummary], gv_options: list[str]) -> OutgoingMessage:
        return self.search_flow._open_grouped_visit_day_selection(
            sender=sender,
            session=session,
            selected_visit_day=selected_visit_day,
            visit_summaries=visit_summaries,
            gv_options=gv_options,
        )

    def _build_grouped_visit_day_gv_menu(self, *, visit_day: str, visit_summaries: list[VisitSellerSummary], gv_options: list[str], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_grouped_visit_day_gv_menu(
            visit_day=visit_day,
            visit_summaries=visit_summaries,
            gv_options=gv_options,
            invalid_selection=invalid_selection,
        )

    def _build_grouped_visit_day_sector_menu(self, *, visit_day: str, gv_code: str, visit_summaries: list[VisitSellerSummary], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_grouped_visit_day_sector_menu(
            visit_day=visit_day,
            gv_code=gv_code,
            visit_summaries=visit_summaries,
            invalid_selection=invalid_selection,
        )

    def _apply_inadimplencia_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        return self.search_flow._apply_inadimplencia_visit_day_selection(
            sender=sender,
            session=session,
            decision=decision,
            selected_visit_day=selected_visit_day,
        )

    def _apply_giro_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        return self.search_flow._apply_giro_visit_day_selection(
            sender=sender,
            session=session,
            decision=decision,
            selected_visit_day=selected_visit_day,
        )

    def _apply_documentacao_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        return self.search_flow._apply_documentacao_visit_day_selection(
            sender=sender,
            session=session,
            decision=decision,
            selected_visit_day=selected_visit_day,
        )

    def _open_grouped_documentacao_visit_selection(self, *, sender: str, session: LookupSession, visit_day: str, summary: DocumentacaoPendenteScopeSummary, records: list[DocumentacaoPendenteClientRecord]) -> OutgoingMessage:
        return self.search_flow._open_grouped_documentacao_visit_selection(
            sender=sender,
            session=session,
            visit_day=visit_day,
            summary=summary,
            records=records,
        )

    def _build_documentacao_visit_day_header_text(self, *, visit_day: str, summary: DocumentacaoPendenteScopeSummary, records: list[DocumentacaoPendenteClientRecord]) -> str:
        return self.search_flow._build_documentacao_visit_day_header_text(
            visit_day=visit_day,
            summary=summary,
            records=records,
        )

    def _summarize_documentacao_visit_sectors(self, records: list[DocumentacaoPendenteClientRecord]) -> list[DocumentacaoVisitSectorSummary]:
        return self.search_flow._summarize_documentacao_visit_sectors(
            records=records,
        )

    def _build_grouped_documentacao_visit_gv_menu(self, *, summary_text: str, gv_options: list[str], sector_summaries: list[DocumentacaoVisitSectorSummary], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_grouped_documentacao_visit_gv_menu(
            summary_text=summary_text,
            gv_options=gv_options,
            sector_summaries=sector_summaries,
            invalid_selection=invalid_selection,
        )

    def _build_grouped_documentacao_visit_sector_menu(self, *, gv_code: str, sector_summaries: list[DocumentacaoVisitSectorSummary], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_grouped_documentacao_visit_sector_menu(
            gv_code=gv_code,
            sector_summaries=sector_summaries,
            invalid_selection=invalid_selection,
        )

    def _build_grouped_documentacao_visit_sector_response(self, *, visit_day: str, sector_summary: DocumentacaoVisitSectorSummary, records: list[DocumentacaoPendenteClientRecord]) -> OutgoingMessage:
        return self.search_flow._build_grouped_documentacao_visit_sector_response(
            visit_day=visit_day,
            sector_summary=sector_summary,
            records=records,
        )

    def _build_giro_visit_day_header_text(self, *, visit_day: str, summary: GiroScopeSummary, opportunities: list[GiroVisitOpportunity], giro_updated_at: str) -> str:
        return self.search_flow._build_giro_visit_day_header_text(
            visit_day=visit_day,
            summary=summary,
            opportunities=opportunities,
            giro_updated_at=giro_updated_at,
        )


    def _collect_giro_visit_day_opportunities(self, *, visit_day: str, decision: AccessDecision, records: list[DClienteRecord]) -> tuple[list[GiroVisitOpportunity], str]:
        return self.search_flow._collect_giro_visit_day_opportunities(
            visit_day=visit_day,
            decision=decision,
            records=records,
        )

    def _summarize_giro_visit_sectors(self, opportunities: list[GiroVisitOpportunity]) -> list[GiroVisitSectorSummary]:
        return self.search_flow._summarize_giro_visit_sectors(
            opportunities=opportunities,
        )

    def _open_grouped_giro_visit_selection(self, *, sender: str, session: LookupSession, decision: AccessDecision, visit_day: str, summary: GiroScopeSummary, records: list[DClienteRecord]) -> OutgoingMessage:
        return self.search_flow._open_grouped_giro_visit_selection(
            sender=sender,
            session=session,
            decision=decision,
            visit_day=visit_day,
            summary=summary,
            records=records,
        )

    def _build_grouped_giro_visit_gv_menu(self, *, summary_text: str, gv_options: list[str], sector_summaries: list[GiroVisitSectorSummary], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_grouped_giro_visit_gv_menu(
            summary_text=summary_text,
            gv_options=gv_options,
            sector_summaries=sector_summaries,
            invalid_selection=invalid_selection,
        )

    def _build_grouped_giro_visit_sector_menu(self, *, summary_text: str, gv_code: str, sector_summaries: list[GiroVisitSectorSummary], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_grouped_giro_visit_sector_menu(
            summary_text=summary_text,
            gv_code=gv_code,
            sector_summaries=sector_summaries,
            invalid_selection=invalid_selection,
        )

    def _build_grouped_giro_visit_sector_response(self, *, decision: AccessDecision, visit_day: str, sector_summary: GiroVisitSectorSummary) -> OutgoingMessage:
        return self.search_flow._build_grouped_giro_visit_sector_response(
            decision=decision,
            visit_day=visit_day,
            sector_summary=sector_summary,
        )

    def _open_inadimplencia_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str = '') -> OutgoingMessage:
        return self.search_flow._open_inadimplencia_visit_day_conversation(
            sender=sender,
            session=session,
            decision=decision,
            requested_day_label=requested_day_label,
        )

    def _open_giro_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str = '') -> OutgoingMessage:
        return self.search_flow._open_giro_visit_day_conversation(
            sender=sender,
            session=session,
            decision=decision,
            requested_day_label=requested_day_label,
        )


    def _open_documentacao_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str = '') -> OutgoingMessage:
        return self.search_flow._open_documentacao_visit_day_conversation(
            sender=sender,
            session=session,
            decision=decision,
            requested_day_label=requested_day_label,
        )

    def _open_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str = '') -> OutgoingMessage:
        return self.search_flow._open_visit_day_conversation(
            sender=sender,
            session=session,
            decision=decision,
            requested_day_label=requested_day_label,
        )

    def _prepare_finance_session(self, session: LookupSession) -> None:
        return self.finance_flow.prepare_session(session)

    def _build_finance_today_clarification(self) -> OutgoingMessage:
        return self.finance_flow._build_finance_today_clarification()


    def _build_expired_session_prompt(self, *, previous_step: str) -> OutgoingMessage:
        return self.navigation_flow._build_expired_session_prompt(
            previous_step=previous_step,
        )

    def _clear_clarification_state(self, session: LookupSession) -> None:
        return self.navigation_flow._clear_clarification_state(
            session=session,
        )

    def _remember_last_context(self, session: LookupSession, *, intent: str | None = None, search_context: str | None = None, query_text: str | None = None, client_filial: str | None = None, client_cod_pdv: str | None = None, client_name: str | None = None, visit_day: str | None = None) -> None:
        return self.navigation_flow._remember_last_context(
            session=session,
            intent=intent,
            search_context=search_context,
            query_text=query_text,
            client_filial=client_filial,
            client_cod_pdv=client_cod_pdv,
            client_name=client_name,
            visit_day=visit_day,
        )

    def _has_recent_last_context(self, session: LookupSession) -> bool:
        return self.navigation_flow._has_recent_last_context(
            session=session,
        )

    def _decision_scope_cache_key(self, decision: AccessDecision, *extra: Any) -> tuple[Any, ...]:
        return self.navigation_flow._decision_scope_cache_key(decision, *extra)

    def _get_cached_response(self, cache_key: tuple[Any, ...]) -> OutgoingMessage | None:
        return self.navigation_flow._get_cached_response(
            cache_key=cache_key,
        )

    def _store_cached_response(self, cache_key: tuple[Any, ...], outgoing: OutgoingMessage) -> OutgoingMessage:
        return self.navigation_flow._store_cached_response(
            cache_key=cache_key,
            outgoing=outgoing,
        )

    def _open_scope_inadimplencia_list(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        return self.search_flow._open_scope_inadimplencia_list(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _build_client_clarification_options(self, session: LookupSession, decision: AccessDecision) -> list[InteractiveOption]:
        return self.search_flow._build_client_clarification_options(
            session=session,
            decision=decision,
        )

    def _build_list_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        return self.search_flow._build_list_clarification_options(
            decision=decision,
        )

    def _build_base_clarification_options(self, session: LookupSession, decision: AccessDecision) -> list[InteractiveOption]:
        return self.navigation_flow._build_base_clarification_options(
            session=session,
            decision=decision,
        )

    def _build_intent_clarification_menu(self, *, session: LookupSession, invalid_selection: bool = False) -> OutgoingMessage:
        return self.navigation_flow._build_intent_clarification_menu(
            session=session,
            invalid_selection=invalid_selection,
        )

    def _open_intent_clarification(self, sender: str, session: LookupSession, *, title: str, prompt: str, options: list[InteractiveOption], footer: str = '') -> OutgoingMessage:
        return self.navigation_flow._open_intent_clarification(
            sender=sender,
            session=session,
            title=title,
            prompt=prompt,
            options=options,
            footer=footer,
        )

    def _build_summary_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        return self.navigation_flow._build_summary_clarification_options(
            decision=decision,
        )

    def _build_today_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        return self.navigation_flow._build_today_clarification_options(
            decision=decision,
        )

    def _build_giro_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        return self.navigation_flow._build_giro_clarification_options(
            decision=decision,
        )


    def _maybe_handle_idle_low_confidence_request(self, sender: str, session: LookupSession, normalized: str, decision: AccessDecision) -> OutgoingMessage | None:
        return self.navigation_flow._maybe_handle_idle_low_confidence_request(
            sender=sender,
            session=session,
            normalized=normalized,
            decision=decision,
        )

    def _run_intent_clarification_option(self, sender: str, session: LookupSession, decision: AccessDecision, *, option_id: str) -> OutgoingMessage:
        return self.navigation_flow._run_intent_clarification_option(
            sender=sender,
            session=session,
            decision=decision,
            option_id=option_id,
        )

    def _run_finance_due_bucket(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        due_bucket: str,
    ) -> OutgoingMessage:
        return self.finance_flow._run_finance_due_bucket(
            sender=sender,
            session=session,
            decision=decision,
            due_bucket=due_bucket,
        )


    def _run_scoped_inadimplencia_due_bucket(self, sender: str, session: LookupSession, decision: AccessDecision, *, due_bucket: str) -> OutgoingMessage:
        return self.search_flow._run_scoped_inadimplencia_due_bucket(
            sender=sender,
            session=session,
            decision=decision,
            due_bucket=due_bucket,
        )

    def _open_finance_summary_menu(
        self,
        *,
        sender: str,
        session: LookupSession,
    ) -> OutgoingMessage:
        return self.finance_flow._open_finance_summary_menu(
            sender=sender,
            session=session,
        )


    def _run_finance_summary_mode(
        self,
        *,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        summary_mode: str,
    ) -> OutgoingMessage:
        return self.finance_flow._run_finance_summary_mode(
            sender=sender,
            session=session,
            decision=decision,
            summary_mode=summary_mode,
        )


    def _maybe_handle_search_mode_conversation(self, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage | None:
        return self.search_flow._maybe_handle_search_mode_conversation(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _maybe_handle_idle_conversation(
        self,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        return self.customer_router._maybe_handle_idle_conversation(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _open_recolha_request(self, *, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage:
        return self.recolha_flow._open_recolha_request(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _contextualize_recolha_request_text(self, *, session: LookupSession, text: str) -> str:
        return self.recolha_flow._contextualize_recolha_request_text(
            session=session,
            text=text,
        )

    def _handle_recolha_session(self, *, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage:
        return self.recolha_flow._handle_recolha_session(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _clear_recolha_state(self, session: LookupSession) -> None:
        return self.recolha_flow._clear_recolha_state(
            session=session,
        )

    def _apply_recolha_client_reference(self, session: LookupSession, *, decision: AccessDecision, client_ref: str) -> OutgoingMessage | None:
        return self.recolha_flow._apply_recolha_client_reference(
            session=session,
            decision=decision,
            client_ref=client_ref,
        )

    def _apply_recolha_client_name_reference(self, session: LookupSession, *, decision: AccessDecision, query_text: str) -> OutgoingMessage | None:
        return self.recolha_flow._apply_recolha_client_name_reference(
            session=session,
            decision=decision,
            query_text=query_text,
        )

    def _apply_recolha_client_record(self, session: LookupSession, *, record: DClienteRecord, decision: AccessDecision) -> None:
        return self.recolha_flow._apply_recolha_client_record(
            session=session,
            record=record,
            decision=decision,
        )

    def _filter_recolha_client_records_by_scope(self, records: list[DClienteRecord], *, decision: AccessDecision) -> list[DClienteRecord]:
        return self.recolha_flow._filter_recolha_client_records_by_scope(
            records=records,
            decision=decision,
        )

    def _fetch_recolha_comodato_options(self, *, filial: str, cod_pdv: str, decision: AccessDecision) -> list[ComodatoRecord]:
        return self.recolha_flow._fetch_recolha_comodato_options(
            filial=filial,
            cod_pdv=cod_pdv,
            decision=decision,
        )

    def _build_recolha_client_prompt(self) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_client_prompt()

    def _build_recolha_client_selection_prompt(self, query_text: str, *, records: list[DClienteRecord]) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_client_selection_prompt(
            query_text=query_text,
            records=records,
        )

    def _build_recolha_comodato_prompt(self, *, session: LookupSession, invalid_selection: bool = False) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_comodato_prompt(
            session=session,
            invalid_selection=invalid_selection,
        )

    def _build_recolha_comodato_options_text(self, first_line: str, *, session: LookupSession) -> str:
        return self.recolha_flow._build_recolha_comodato_options_text(
            first_line=first_line,
            session=session,
        )

    def _build_recolha_obs_prompt(self) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_obs_prompt()

    def _build_recolha_confirmation(self, *, session: LookupSession, invalid_selection: bool = False) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_confirmation(
            session=session,
            invalid_selection=invalid_selection,
        )

    def _build_recolha_created_response(self, *, records: list[RecolhaRequestRecord], cliente: str) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_created_response(
            records=records,
            cliente=cliente,
        )

    def _open_recolha_delete_confirmation(self, *, sender: str, session: LookupSession, identifier: str, decision: AccessDecision) -> OutgoingMessage:
        return self.recolha_flow._open_recolha_delete_confirmation(
            sender=sender,
            session=session,
            identifier=identifier,
            decision=decision,
        )

    def _open_recolha_clear_confirmation(self, *, sender: str, session: LookupSession) -> OutgoingMessage:
        return self.recolha_flow._open_recolha_clear_confirmation(
            sender=sender,
            session=session,
        )

    def _build_recolha_delete_confirmation(self, record: RecolhaRequestRecord | None, *, identifier: str, invalid_selection: bool = False) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_delete_confirmation(
            record=record,
            identifier=identifier,
            invalid_selection=invalid_selection,
        )

    def _build_recolha_clear_confirmation(self, *, invalid_selection: bool = False) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_clear_confirmation(
            invalid_selection=invalid_selection,
        )

    def _build_recolha_deleted_response(self, record: RecolhaRequestRecord | None, *, identifier: str) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_deleted_response(
            record=record,
            identifier=identifier,
        )

    def _build_recolha_update_response(self, record: RecolhaRequestRecord | None, *, identifier: str) -> OutgoingMessage:
        return self.recolha_flow._build_recolha_update_response(
            record=record,
            identifier=identifier,
        )

    def _recolha_requester_keys(self, *, sender: str, decision: AccessDecision) -> set[str]:
        return self.recolha_flow._recolha_requester_keys(
            sender=sender,
            decision=decision,
        )

    def _recolha_requester_name(self, *, sender: str, decision: AccessDecision) -> str:
        return self.recolha_flow._recolha_requester_name(
            sender=sender,
            decision=decision,
        )

    def _recolha_identity_keys(self, value: str) -> set[str]:
        return self.recolha_flow._recolha_identity_keys(
            value=value,
        )

    def _recolha_record_visible_for_decision(self, record: RecolhaRequestRecord, *, sender: str, decision: AccessDecision) -> bool:
        return self.recolha_flow._recolha_record_visible_for_decision(
            record=record,
            sender=sender,
            decision=decision,
        )

    def _filter_recolha_records_for_decision(self, records: list[RecolhaRequestRecord], *, sender: str, decision: AccessDecision) -> list[RecolhaRequestRecord]:
        return self.recolha_flow._filter_recolha_records_for_decision(
            records=records,
            sender=sender,
            decision=decision,
        )

    def _find_recolha_for_decision(self, *, identifier: str, sender: str, decision: AccessDecision) -> RecolhaRequestRecord | None:
        return self.recolha_flow._find_recolha_for_decision(
            identifier=identifier,
            sender=sender,
            decision=decision,
        )

    def _update_recolha_for_decision(self, *, identifier: str, updates: dict[str, str], sender: str, decision: AccessDecision) -> RecolhaRequestRecord | None:
        return self.recolha_flow._update_recolha_for_decision(
            identifier=identifier,
            updates=updates,
            sender=sender,
            decision=decision,
        )

    def _delete_recolha_for_decision(self, *, identifier: str, sender: str, decision: AccessDecision) -> RecolhaRequestRecord | None:
        return self.recolha_flow._delete_recolha_for_decision(
            identifier=identifier,
            sender=sender,
            decision=decision,
        )

    def _build_recolhas_finance_response(self, request_text: str = '', *, sender: str = '', decision: AccessDecision) -> OutgoingMessage:
        return self.recolha_flow._build_recolhas_finance_response(
            request_text=request_text,
            sender=sender,
            decision=decision,
        )

    def _build_recolhas_summary_response(self, *, records: list[RecolhaRequestRecord], total: int, csv_bytes: bytes, request_filters: RecolhaRequestFilters | None = None) -> OutgoingMessage:
        return self.recolha_flow._build_recolhas_summary_response(
            records=records,
            total=total,
            csv_bytes=csv_bytes,
            request_filters=request_filters,
        )

    def _handle_admin_session(self, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage:
        return self.admin_access_flow._handle_admin_session(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _handle_finance_session_impl(
        self,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.finance_flow.handle_session(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _open_inadimplencia_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, order_by: str, header_text: str, empty_text: str, due_bucket: str | None = None, page: int = 1, page_size: int = INADIMPLENCIA_PAGE_SIZE, list_context: str = '', known_total_clients: int | None = None) -> OutgoingMessage:
        return self.search_flow._open_inadimplencia_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
            order_by=order_by,
            header_text=header_text,
            empty_text=empty_text,
            due_bucket=due_bucket,
            page=page,
            page_size=page_size,
            list_context=list_context,
            known_total_clients=known_total_clients,
        )

    def _handle_critica_command_impl(
        self,
        *,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.critica_flow.handle_command(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _ensure_critica_rn_ready(self, decision: AccessDecision) -> OutgoingMessage | None:
        return self.critica_flow.ensure_ready(decision)

    def _build_critica_summary_response(
        self,
        *,
        target_date: date,
        decision: AccessDecision,
        title: str,
        footer_lines: tuple[str, ...] = (),
    ) -> OutgoingMessage:
        return self.critica_flow._build_critica_summary_response(
            target_date=target_date,
            decision=decision,
            title=title,
            footer_lines=footer_lines,
        )

    def _build_critica_problems_response(
        self,
        *,
        target_date: date,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.critica_flow._build_critica_problems_response(
            target_date=target_date,
            decision=decision,
        )

    def _build_critica_nb_response(
        self,
        *,
        filial: str,
        cod_pdv: str,
        target_date: date | None,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.critica_flow._build_critica_nb_response(
            filial=filial,
            cod_pdv=cod_pdv,
            target_date=target_date,
            decision=decision,
        )

    def _build_critica_pdf_response(
        self,
        *,
        target_date: date,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.critica_flow._build_critica_pdf_response(
            target_date=target_date,
            decision=decision,
        )

    def _build_critica_gv_summary_pdf_response(
        self,
        *,
        target_date: date | None,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.critica_flow._build_critica_gv_summary_pdf_response(
            target_date=target_date,
            decision=decision,
        )

    def _critica_gv_summary_allowed_gv_vdes(self, decision: AccessDecision) -> list[str] | None:
        return self.critica_flow._critica_gv_summary_allowed_gv_vdes(decision)

    def _build_critica_nb_pdf_response(
        self,
        *,
        filial: str,
        cod_pdv: str,
        target_date: date | None,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.critica_flow._build_critica_nb_pdf_response(
            filial=filial,
            cod_pdv=cod_pdv,
            target_date=target_date,
            decision=decision,
        )

    def _build_critica_sector_pdf_response(
        self,
        *,
        target_date: date,
        normalized_text: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.critica_flow._build_critica_sector_pdf_response(
            target_date=target_date,
            normalized_text=normalized_text,
            decision=decision,
        )

    def _resolve_critica_pdf_sector_scope(
        self,
        *,
        target_date: date,
        normalized_text: str,
        decision: AccessDecision,
    ) -> tuple[str, str]:
        return self.critica_flow._resolve_critica_pdf_sector_scope(
            target_date=target_date,
            normalized_text=normalized_text,
            decision=decision,
        )

    def _build_empty_critica_response(self, *, target_date: date, decision: AccessDecision) -> OutgoingMessage:
        return self.critica_flow._build_empty_critica_response(
            target_date=target_date,
            decision=decision,
        )

    def _is_admin(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._is_admin(
            decision=decision,
        )

    def _is_financeiro(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._is_financeiro(
            decision=decision,
        )

    def _is_vendedor(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._is_vendedor(
            decision=decision,
        )

    def _is_gerente_vendas(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._is_gerente_vendas(
            decision=decision,
        )

    def _is_diretor_comercial(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._is_diretor_comercial(
            decision=decision,
        )

    def _can_use_finance_menu(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_use_finance_menu(
            decision=decision,
        )

    def _can_request_recolha(self, decision: AccessDecision) -> bool:
        return self.recolha_flow._can_request_recolha(
            decision=decision,
        )

    def _can_view_recolhas(self, decision: AccessDecision) -> bool:
        return self.recolha_flow._can_view_recolhas(
            decision=decision,
        )

    def _can_use_critica(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_use_critica(
            decision=decision,
        )

    def _can_update_recolhas(self, decision: AccessDecision) -> bool:
        return self.recolha_flow._can_update_recolhas(
            decision=decision,
        )

    def _can_clear_recolhas(self, decision: AccessDecision) -> bool:
        return self.recolha_flow._can_clear_recolhas(
            decision=decision,
        )

    def _can_manage_recolhas(self, decision: AccessDecision) -> bool:
        return self.recolha_flow._can_manage_recolhas(
            decision=decision,
        )

    def _can_use_payip_menu(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_use_payip_menu(
            decision=decision,
        )

    def _has_unrestricted_lookup_access(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._has_unrestricted_lookup_access(
            decision=decision,
        )

    def _uses_grouped_visit_flow(self, decision: AccessDecision) -> bool:
        return self.search_flow._uses_grouped_visit_flow(
            decision=decision,
        )

    def _uses_grouped_giro_visit_flow(self, decision: AccessDecision) -> bool:
        return self.search_flow._uses_grouped_giro_visit_flow(
            decision=decision,
        )

    def _can_access_sectors(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_access_sectors(
            decision=decision,
        )

    def _allowed_sectors(self, decision: AccessDecision) -> list[str] | None:
        return self.access_policy_flow._allowed_sectors(
            decision=decision,
        )

    def _allowed_gv_vdes(self, decision: AccessDecision) -> list[str] | None:
        return self.access_policy_flow._allowed_gv_vdes(
            decision=decision,
        )

    def _can_use_visit_menu(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_use_visit_menu(
            decision=decision,
        )

    def _can_use_gv_summary_menu(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_use_gv_summary_menu(
            decision=decision,
        )

    def _can_use_seller_summary_menu(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_use_seller_summary_menu(
            decision=decision,
        )

    def _can_use_seller_risk_menu(self, decision: AccessDecision) -> bool:
        return self.access_policy_flow._can_use_seller_risk_menu(
            decision=decision,
        )

    def _decision_for_area(self, decision: AccessDecision, area: str) -> AccessDecision:
        return self.access_policy_flow._decision_for_area(
            decision=decision,
            area=area,
        )

    def _has_area_access(self, decision: AccessDecision, area: str) -> bool:
        return self.access_policy_flow._has_area_access(
            decision=decision,
            area=area,
        )

    def _build_area_access_denied_response(self, area: str) -> OutgoingMessage:
        return self.access_policy_flow._build_area_access_denied_response(
            area=area,
        )

    def _ensure_search_context_ready(self, search_context: str, decision: AccessDecision | None = None) -> OutgoingMessage | None:
        return self.search_flow._ensure_search_context_ready(
            search_context=search_context,
            decision=decision,
        )

    def _ensure_scoped_lookup_access(self, decision: AccessDecision, search_context: str) -> OutgoingMessage | None:
        return self.access_policy_flow._ensure_scoped_lookup_access(
            decision=decision,
            search_context=search_context,
        )

    def _main_menu_summary_option_id(self, decision: AccessDecision) -> str:
        return self.main_menu_flow._main_menu_summary_option_id(
            decision=decision,
        )

    def _main_menu_option_ids(self, decision: AccessDecision) -> list[str]:
        return self.main_menu_flow._main_menu_option_ids(
            decision=decision,
        )

    def _main_menu_shortcuts(self, decision: AccessDecision) -> dict[str, str]:
        return self.main_menu_flow._main_menu_shortcuts(
            decision=decision,
        )

    def _build_main_menu(self, decision: AccessDecision, invalid_selection: bool = False) -> OutgoingMessage:
        return self.main_menu_flow._build_main_menu(
            decision=decision,
            invalid_selection=invalid_selection,
        )

    def _build_search_menu(self, search_context: str, decision: AccessDecision | None = None, invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_search_menu(
            search_context=search_context,
            decision=decision,
            invalid_selection=invalid_selection,
        )

    def _build_inadimplencia_base_summary(self, decision: AccessDecision | None) -> str:
        return self.search_flow._build_inadimplencia_base_summary(
            decision=decision,
        )

    def _inadimplencia_scope_label(self, decision: AccessDecision) -> str:
        return self.search_flow._inadimplencia_scope_label(
            decision=decision,
        )

    def _build_finance_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_finance_menu(
            invalid_selection=invalid_selection,
        )


    def _build_payip_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_menu(invalid_selection=invalid_selection)

    def _build_payip_status_response(self) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_status_response()

    def _run_payip_login_test(
        self,
        *,
        sender: str,
        session: LookupSession,
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_login_test(
            sender=sender,
            session=session,
            mfa_code=mfa_code,
        )

    def _build_payip_mfa_prompt(
        self,
        *,
        invalid_selection: bool = False,
        detail: str = "",
        context: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_mfa_prompt(
            invalid_selection=invalid_selection,
            detail=detail,
            context=context,
        )

    def _build_payip_login_test_response(self, *, mfa_code: str = "") -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_login_test_response(mfa_code=mfa_code)

    def _build_payip_invoice_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_invoice_prompt(invalid_selection=invalid_selection)

    def _payip_filial_hint(self) -> str:
        return self.finance_flow.payip_flow._payip_filial_hint()

    def _build_payip_client_code_prompt(
        self,
        invalid_selection: bool = False,
        *,
        pending_only: bool | None = True,
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_client_code_prompt(
            invalid_selection=invalid_selection,
            pending_only=pending_only,
        )

    def _build_payip_client_filter_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_client_filter_prompt(invalid_selection=invalid_selection)

    def _build_payip_charge_client_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_charge_client_prompt(invalid_selection=invalid_selection)

    def _build_payip_statement_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_statement_prompt(invalid_selection=invalid_selection)

    def _build_payip_amount_day_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_amount_day_prompt(invalid_selection=invalid_selection)

    def _run_payip_amount_day_search(
        self,
        *,
        sender: str,
        session: LookupSession,
        filial: str,
        amount: Decimal | str | int | float | None,
        day: date | str | None,
        tolerance: Decimal | str | int | float | None = None,
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_amount_day_search(
            sender=sender,
            session=session,
            filial=filial,
            amount=amount,
            day=day,
            tolerance=tolerance,
            mfa_code=mfa_code,
        )

    def _run_payip_statement_resume(
        self,
        *,
        sender: str,
        session: LookupSession,
        filial: str,
        date_start: date | str | None = None,
        date_end: date | str | None = None,
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_statement_resume(
            sender=sender,
            session=session,
            filial=filial,
            date_start=date_start,
            date_end=date_end,
            mfa_code=mfa_code,
        )

    def _load_payip_statement_exports(
        self,
        *,
        filial: str,
        date_start: date,
        date_end: date,
    ) -> tuple[bytes, bytes, tuple[str, ...]]:
        return self.finance_flow.payip_flow._load_payip_statement_exports(
            filial=filial,
            date_start=date_start,
            date_end=date_end,
        )

    def _build_payip_charge_lookup_error(
        self,
        *,
        filial: str,
        client_code: str,
        error_text: str,
        mfa_was_validated: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_charge_lookup_error(
            filial=filial,
            client_code=client_code,
            error_text=error_text,
            mfa_was_validated=mfa_was_validated,
        )

    def _build_payip_charge_amount_prompt(
        self,
        *,
        session: LookupSession,
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_charge_amount_prompt(
            session=session,
            invalid_selection=invalid_selection,
        )

    def _build_payip_charge_due_date_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_charge_due_date_prompt(invalid_selection=invalid_selection)

    def _build_payip_charge_confirmation(
        self,
        *,
        session: LookupSession,
        invalid_selection: bool = False,
        detail: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_charge_confirmation(
            session=session,
            invalid_selection=invalid_selection,
            detail=detail,
        )

    def _run_payip_charge_client_lookup(
        self,
        *,
        sender: str,
        session: LookupSession,
        client_code: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_charge_client_lookup(
            sender=sender,
            session=session,
            client_code=client_code,
            filial=filial,
            mfa_code=mfa_code,
        )

    def _run_payip_charge_create(
        self,
        *,
        sender: str,
        session: LookupSession,
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_charge_create(
            sender=sender,
            session=session,
            mfa_code=mfa_code,
        )

    def _build_payip_charge_create_error_response(
        self,
        *,
        session: LookupSession,
        error_text: str,
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_charge_create_error_response(
            session=session,
            error_text=error_text,
        )

    def _build_payip_charge_post_create_response(
        self,
        *,
        session: LookupSession,
        payment: dict[str, Any],
        title: str,
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_charge_post_create_response(
            session=session,
            payment=payment,
            title=title,
        )

    def _run_payip_invoice_search(
        self,
        *,
        sender: str,
        session: LookupSession,
        invoice: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_invoice_search(
            sender=sender,
            session=session,
            invoice=invoice,
            filial=filial,
            mfa_code=mfa_code,
        )

    def _run_payip_pending_client_search(
        self,
        *,
        sender: str,
        session: LookupSession,
        client_code: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_pending_client_search(
            sender=sender,
            session=session,
            client_code=client_code,
            filial=filial,
            mfa_code=mfa_code,
        )

    def _run_payip_client_search(
        self,
        *,
        sender: str,
        session: LookupSession,
        client_code: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_client_search(
            sender=sender,
            session=session,
            client_code=client_code,
            filial=filial,
            mfa_code=mfa_code,
        )

    def _run_payip_search(
        self,
        *,
        sender: str,
        session: LookupSession,
        action: str,
        filial: str,
        invoice: str = "",
        client_code: str = "",
        status: str = "",
        mfa_code: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._run_payip_search(
            sender=sender,
            session=session,
            action=action,
            filial=filial,
            invoice=invoice,
            client_code=client_code,
            status=status,
            mfa_code=mfa_code,
        )

    def _open_payip_client_filter_or_search(
        self,
        *,
        sender: str,
        session: LookupSession,
        client_code: str,
        filial: str = "",
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._open_payip_client_filter_or_search(
            sender=sender,
            session=session,
            client_code=client_code,
            filial=filial,
        )

    def _load_payip_payments_page(
        self,
        *,
        page: int,
        page_size: int,
        status: str = "",
        client_code: str = "",
        invoice: str = "",
        search: str = "",
        due_date_start: str = "",
        due_date_end: str = "",
        created_at_start: str = "",
        created_at_end: str = "",
        filial: str = "",
        mfa_code: str = "",
    ) -> Any:
        return self.finance_flow.payip_flow._load_payip_payments_page(
            page=page,
            page_size=page_size,
            status=status,
            client_code=client_code,
            invoice=invoice,
            search=search,
            due_date_start=due_date_start,
            due_date_end=due_date_end,
            created_at_start=created_at_start,
            created_at_end=created_at_end,
            filial=filial,
            mfa_code=mfa_code,
        )

    def _build_payip_payments_response(
        self,
        *,
        title: str,
        page: Any,
        criteria: str,
        empty_text: str,
    ) -> OutgoingMessage:
        return self.finance_flow.payip_flow._build_payip_payments_response(
            title=title,
            page=page,
            criteria=criteria,
            empty_text=empty_text,
        )

    def _build_finance_due_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_finance_due_menu(
            invalid_selection=invalid_selection,
        )


    def _build_manager_due_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_manager_due_menu(
            invalid_selection=invalid_selection,
        )


    def _build_finance_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_finance_giro_menu(
            invalid_selection=invalid_selection,
        )


    def _build_manager_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_manager_giro_menu(
            invalid_selection=invalid_selection,
        )


    def _build_director_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_director_giro_menu(
            invalid_selection=invalid_selection,
        )


    def _build_giro_total_response(
        self,
        decision: AccessDecision,
        *,
        title: str,
        gv_vdes_override: tuple[str, ...] | None = None,
    ) -> OutgoingMessage:
        return self.finance_flow._build_giro_total_response(
            decision=decision,
            title=title,
            gv_vdes_override=gv_vdes_override,
        )


    def _build_giro_zero_base_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_giro_zero_base_response(
            decision=decision,
        )


    def _build_documentacao_pendente_response(self, records: list[DocumentacaoPendenteClientRecord], criteria: str, scope_restricted: bool = True) -> OutgoingMessage:
        return self.search_flow._build_documentacao_pendente_response(
            records=records,
            criteria=criteria,
            scope_restricted=scope_restricted,
        )

    def _build_prazo_limite_response(self, records: list[PrazoLimiteClientRecord], criteria: str, *, decision: AccessDecision, scope_restricted: bool = True) -> OutgoingMessage:
        return self.search_flow._build_prazo_limite_response(
            records=records,
            criteria=criteria,
            decision=decision,
            scope_restricted=scope_restricted,
        )

    def _safe_inadimplencia_registration_records(self, *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool = True) -> list[InadimplenciaRecord] | None:
        return self.search_flow._safe_inadimplencia_registration_records(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
            scope_restricted=scope_restricted,
        )

    def _safe_giro_registration_records(self, *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool = True) -> list[GiroClientRecord] | None:
        return self.search_flow._safe_giro_registration_records(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
            scope_restricted=scope_restricted,
        )

    def _append_financial_analysis_inadimplencia_lines(self, lines: list[str], records: list[InadimplenciaRecord] | None) -> None:
        return self.search_flow._append_financial_analysis_inadimplencia_lines(
            lines=lines,
            records=records,
        )

    def _append_financial_analysis_documentacao_lines(self, lines: list[str], *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool = True) -> None:
        return self.search_flow._append_financial_analysis_documentacao_lines(
            lines=lines,
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
            scope_restricted=scope_restricted,
        )

    def _append_financial_analysis_giro_lines(self, lines: list[str], records: list[GiroClientRecord] | None) -> None:
        return self.search_flow._append_financial_analysis_giro_lines(
            lines=lines,
            records=records,
        )

    def _build_documentacao_visit_day_response(self, *, visit_day: str, decision: AccessDecision, summary: DocumentacaoPendenteScopeSummary, records: list[DocumentacaoPendenteClientRecord]) -> OutgoingMessage:
        return self.search_flow._build_documentacao_visit_day_response(
            visit_day=visit_day,
            decision=decision,
            summary=summary,
            records=records,
        )

    def _build_giro_visit_day_response(
        self,
        *,
        visit_day: str,
        decision: AccessDecision,
        summary: GiroScopeSummary,
        records: list[DClienteRecord],
    ) -> OutgoingMessage:
        return self.finance_flow._build_giro_visit_day_response(
            visit_day=visit_day,
            decision=decision,
            summary=summary,
            records=records,
        )


    def _build_finance_giro_visit_day_response(
        self,
        *,
        visit_day: str,
        decision: AccessDecision,
        summary: GiroScopeSummary,
        records: list[DClienteRecord],
    ) -> OutgoingMessage:
        return self.finance_flow._build_finance_giro_visit_day_response(
            visit_day=visit_day,
            decision=decision,
            summary=summary,
            records=records,
        )


    def _build_giro_by_filial_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        return self.finance_flow._build_giro_by_filial_response(
            decision=decision,
            title=title,
        )


    def _build_giro_by_gv_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        return self.finance_flow._build_giro_by_gv_response(
            decision=decision,
            title=title,
        )


    def _safe_giro_scope_summary(self, decision: AccessDecision, gv_vdes_override: tuple[str, ...] | None = None) -> GiroScopeSummary | None:
        return self.finance_flow._safe_giro_scope_summary(
            decision=decision,
            gv_vdes_override=gv_vdes_override,
        )

    def _safe_giro_scope_summary_by_visit_day(self, decision: AccessDecision, *, visit_day: str) -> GiroScopeSummary | None:
        return self.finance_flow._safe_giro_scope_summary_by_visit_day(
            decision=decision,
            visit_day=visit_day,
        )

    def _safe_giro_scope_summary_for_seller(self, decision: AccessDecision, seller_code: str, manager_code: str) -> GiroScopeSummary | None:
        return self.finance_flow._safe_giro_scope_summary_for_seller(
            decision=decision,
            seller_code=seller_code,
            manager_code=manager_code,
        )

    def _safe_giro_summary_by_filial(self, decision: AccessDecision) -> list[GiroFilialSummary]:
        return self.finance_flow._safe_giro_summary_by_filial(
            decision=decision,
        )

    def _safe_giro_summary_by_gv(self, decision: AccessDecision) -> list[GiroManagementSummary]:
        return self.finance_flow._safe_giro_summary_by_gv(
            decision=decision,
        )

    def _safe_giro_summary_by_seller(self, decision: AccessDecision) -> list[GiroSellerSummary]:
        return self.finance_flow._safe_giro_summary_by_seller(
            decision=decision,
        )

    def _safe_giro_zero_base_records(self, decision: AccessDecision) -> list[GiroZeroBaseRecord] | None:
        return self.finance_flow._safe_giro_zero_base_records(
            decision=decision,
        )

    def _safe_giro_history_by_registration(self, *, decision: AccessDecision, filial: str, cod_pdv: str) -> list[GiroClientRecord]:
        return self.finance_flow._safe_giro_history_by_registration(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
        )

    def _build_giro_historical_fallback_response(
        self,
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
        criteria: str,
    ) -> OutgoingMessage | None:
        return self.finance_flow._build_giro_historical_fallback_response(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
            criteria=criteria,
        )


    def _append_giro_summary_lines(self, lines: list[str], summary: GiroScopeSummary | None, *, compact: bool, show_details: bool = False) -> None:
        return self.finance_flow._append_giro_summary_lines(
            lines=lines,
            summary=summary,
            compact=compact,
            show_details=show_details,
        )

    def _format_giro_total_scope_line(self, summary: GiroScopeSummary | None, *, label: str, child_count_label: str = '', child_count: int | None = None) -> str:
        return self.finance_flow._format_giro_total_scope_line(
            summary=summary,
            label=label,
            child_count_label=child_count_label,
            child_count=child_count,
        )

    def _format_scope_update_line(self, *, client_updated: str | None, inad_updated: str | None, giro_updated: str | None) -> str:
        return self.finance_flow._format_scope_update_line(
            client_updated=client_updated,
            inad_updated=inad_updated,
            giro_updated=giro_updated,
        )

    def _format_due_compact_line(self, *, today_count: int, today_total: str, tomorrow_count: int, tomorrow_total: str, two_days_count: int, two_days_total: str) -> str:
        return self.finance_flow._format_due_compact_line(
            today_count=today_count,
            today_total=today_total,
            tomorrow_count=tomorrow_count,
            tomorrow_total=tomorrow_total,
            two_days_count=two_days_count,
            two_days_total=two_days_total,
        )

    def _group_giro_management_summaries_by_filial(self, summaries: list[GiroManagementSummary]) -> dict[str, list[GiroManagementSummary]]:
        return self.finance_flow._group_giro_management_summaries_by_filial(
            summaries=summaries,
        )

    def _group_giro_seller_summaries_by_manager(self, summaries: list[GiroSellerSummary]) -> dict[str, list[GiroSellerSummary]]:
        return self.finance_flow._group_giro_seller_summaries_by_manager(
            summaries=summaries,
        )

    def _build_finance_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_finance_summary_response(
            decision=decision,
        )


    def _build_finance_summary_by_filial_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_finance_summary_by_filial_response(
            decision=decision,
        )


    def _build_finance_documentacao_by_filial_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_finance_documentacao_by_filial_response(
            decision=decision,
        )


    def _build_finance_summary_by_gv_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_finance_summary_by_gv_response(
            decision=decision,
        )


    def _build_finance_summary_by_seller_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_finance_summary_by_seller_response(
            decision=decision,
        )


    def _build_gv_summary_response(self, decision: AccessDecision, gv_vdes_override: tuple[str, ...] | None = None, title: str | None = None) -> OutgoingMessage:
        return self.finance_flow._build_gv_summary_response(
            decision=decision,
            gv_vdes_override=gv_vdes_override,
            title=title,
        )

    def _build_director_total_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_director_total_summary_response(
            decision=decision,
        )


    def _build_director_manager_ranking_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_director_manager_ranking_response(
            decision=decision,
        )


    def _build_director_filial_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_director_filial_summary_response(
            decision=decision,
        )


    def _build_seller_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_seller_summary_response(
            decision=decision,
        )

    def _build_seller_risk_response(self, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._build_seller_risk_response(
            decision=decision,
        )

    def _build_seller_visit_day_risk_response(self, *, decision: AccessDecision, visit_day: str, visit_day_label: str, current_day_only: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_seller_visit_day_risk_response(
            decision=decision,
            visit_day=visit_day,
            visit_day_label=visit_day_label,
            current_day_only=current_day_only,
        )

    def _resolve_current_scope_visit_day_label(self, decision: AccessDecision) -> str:
        return self.finance_flow._resolve_current_scope_visit_day_label(
            decision=decision,
        )

    def _open_finance_gv_summary_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.finance_flow._open_finance_gv_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
        )


    def _open_director_summary_menu(self, sender: str, session: LookupSession) -> OutgoingMessage:
        return self.finance_flow._open_director_summary_menu(
            sender=sender,
            session=session,
        )

    def _open_director_visit_risk_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._open_director_visit_risk_day_selection(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _build_director_visit_risk_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_director_visit_risk_day_menu(
            visit_days=visit_days,
            invalid_selection=invalid_selection,
        )


    def _open_manager_summary_menu(self, sender: str, session: LookupSession) -> OutgoingMessage:
        return self.finance_flow._open_manager_summary_menu(
            sender=sender,
            session=session,
        )

    def _build_manager_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_manager_summary_menu(
            invalid_selection=invalid_selection,
        )


    def _build_finance_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_finance_summary_menu(
            invalid_selection=invalid_selection,
        )


    def _open_manager_filial_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._open_manager_filial_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _build_manager_filial_summary_menu(
        self,
        filial_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_manager_filial_summary_menu(
            filial_options=filial_options,
            invalid_selection=invalid_selection,
        )


    def _open_manager_seller_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._open_manager_seller_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _build_manager_seller_summary_menu(
        self,
        seller_summaries: list[VisitSellerSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_manager_seller_summary_menu(
            seller_summaries=seller_summaries,
            invalid_selection=invalid_selection,
        )


    def _build_manager_seller_summary_response(
        self,
        decision: AccessDecision,
        summary: VisitSellerSummary,
    ) -> OutgoingMessage:
        return self.finance_flow._build_manager_seller_summary_response(
            decision=decision,
            summary=summary,
        )


    def _open_manager_visit_risk_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._open_manager_visit_risk_day_selection(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _open_manager_visit_risk_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, visit_day_token: str, visit_day_label: str) -> OutgoingMessage:
        return self.finance_flow._open_manager_visit_risk_selection(
            sender=sender,
            session=session,
            decision=decision,
            visit_day_token=visit_day_token,
            visit_day_label=visit_day_label,
        )

    def _build_director_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.finance_flow._build_director_summary_menu(
            invalid_selection=invalid_selection,
        )


    def _build_finance_gv_summary_menu(
        self,
        gv_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_finance_gv_summary_menu(
            gv_options=gv_options,
            invalid_selection=invalid_selection,
        )


    def _open_director_gv_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        return self.finance_flow._open_director_gv_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
        )

    def _open_director_visit_risk_gv_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, visit_day_token: str, visit_day_label: str) -> OutgoingMessage:
        return self.finance_flow._open_director_visit_risk_gv_selection(
            sender=sender,
            session=session,
            decision=decision,
            visit_day_token=visit_day_token,
            visit_day_label=visit_day_label,
        )

    def _build_director_visit_risk_gv_menu(
        self,
        visit_day_label: str,
        gv_options: list[str],
        seller_summaries: list[InadimplenciaVisitRiskSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_director_visit_risk_gv_menu(
            visit_day_label=visit_day_label,
            gv_options=gv_options,
            seller_summaries=seller_summaries,
            invalid_selection=invalid_selection,
        )


    def _build_director_visit_risk_sector_menu(
        self,
        visit_day_label: str,
        summaries: list[InadimplenciaVisitRiskSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_director_visit_risk_sector_menu(
            visit_day_label=visit_day_label,
            summaries=summaries,
            invalid_selection=invalid_selection,
        )


    def _build_director_visit_risk_sector_response(
        self,
        decision: AccessDecision,
        summary: InadimplenciaVisitRiskSummary,
        visit_day_token: str,
        visit_day_label: str,
    ) -> OutgoingMessage:
        return self.finance_flow._build_director_visit_risk_sector_response(
            decision=decision,
            summary=summary,
            visit_day_token=visit_day_token,
            visit_day_label=visit_day_label,
        )


    def _build_director_gv_summary_menu(
        self,
        gv_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_director_gv_summary_menu(
            gv_options=gv_options,
            invalid_selection=invalid_selection,
        )


    def _open_finance_visit_risk_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        visit_day_token: str,
        visit_day_label: str,
    ) -> OutgoingMessage:
        return self.finance_flow._open_finance_visit_risk_selection(
            sender=sender,
            session=session,
            decision=decision,
            visit_day_token=visit_day_token,
            visit_day_label=visit_day_label,
        )


    def _open_finance_visit_risk_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        return self.finance_flow._open_finance_visit_risk_day_selection(
            sender=sender,
            session=session,
            decision=decision,
        )


    def _build_finance_visit_risk_gv_menu(
        self,
        *,
        visit_day_label: str,
        gv_options: list[str],
        summaries: list[InadimplenciaVisitRiskSummary],
        menu_title: str = "Risco da Rota",
        day_header_prefix: str = "Risco da rota",
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_finance_visit_risk_gv_menu(
            visit_day_label=visit_day_label,
            gv_options=gv_options,
            summaries=summaries,
            menu_title=menu_title,
            day_header_prefix=day_header_prefix,
            invalid_selection=invalid_selection,
        )


    def _build_finance_visit_risk_day_menu(
        self,
        visit_days: list[str],
        menu_title: str = "Risco da Rota",
        header_prompt: str = "Escolha o dia da semana para ver o risco da rota.",
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_finance_visit_risk_day_menu(
            visit_days=visit_days,
            menu_title=menu_title,
            header_prompt=header_prompt,
            invalid_selection=invalid_selection,
        )


    def _build_finance_visit_risk_menu(
        self,
        visit_day_label: str,
        summaries: list[InadimplenciaVisitRiskSummary],
        menu_title: str = "Risco da Rota",
        day_header_prefix: str = "Risco da rota",
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        return self.finance_flow._build_finance_visit_risk_menu(
            visit_day_label=visit_day_label,
            summaries=summaries,
            menu_title=menu_title,
            day_header_prefix=day_header_prefix,
            invalid_selection=invalid_selection,
        )


    def _build_finance_visit_risk_sector_response(
        self,
        decision: AccessDecision,
        summary: InadimplenciaVisitRiskSummary,
        visit_day_token: str,
        visit_day_label: str,
    ) -> OutgoingMessage:
        return self.finance_flow._build_finance_visit_risk_sector_response(
            decision=decision,
            summary=summary,
            visit_day_token=visit_day_token,
            visit_day_label=visit_day_label,
        )


    def _build_admin_action_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        return self.admin_access_flow._build_admin_action_menu(
            invalid_selection=invalid_selection,
        )

    def _build_admin_summary_response(self, users: list[dict[str, Any]]) -> OutgoingMessage:
        return self.admin_access_flow._build_admin_summary_response(
            users=users,
        )

    def _build_admin_health_response(self) -> OutgoingMessage:
        return self.admin_access_flow._build_admin_health_response()

    def _build_admin_access_check_response(self, phone_number: str, user: dict[str, Any] | None) -> OutgoingMessage:
        return self.admin_access_flow._build_admin_access_check_response(
            phone_number=phone_number,
            user=user,
        )

    def _build_role_menu(self, phone_number: str, session: LookupSession, invalid_selection: bool = False) -> OutgoingMessage:
        return self.admin_access_flow._build_role_menu(
            phone_number=phone_number,
            session=session,
            invalid_selection=invalid_selection,
        )

    def _build_admin_confirmation(self, session: LookupSession) -> OutgoingMessage:
        return self.admin_access_flow._build_admin_confirmation(
            session=session,
        )

    def _build_admin_users_list_response(self, users: list[dict[str, Any]]) -> OutgoingMessage:
        return self.admin_access_flow._build_admin_users_list_response(
            users=users,
        )

    def _build_fantasia_results_menu(self, query_text: str, records: list[DClienteRecord], search_context: str = 'cliente', invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_fantasia_results_menu(
            query_text=query_text,
            records=records,
            search_context=search_context,
            invalid_selection=invalid_selection,
        )

    def _build_inadimplencia_client_menu(self, query_text: str, summaries: list[InadimplenciaClientSummary], total_available: int | None = None, page: int | None = None, page_size: int = INADIMPLENCIA_PAGE_SIZE, list_context: str = '', invalid_selection: bool = False, navigation_notice: str = '') -> OutgoingMessage:
        return self.search_flow._build_inadimplencia_client_menu(
            query_text=query_text,
            summaries=summaries,
            total_available=total_available,
            page=page,
            page_size=page_size,
            list_context=list_context,
            invalid_selection=invalid_selection,
            navigation_notice=navigation_notice,
        )

    def _build_comodato_client_menu(self, query_text: str, summaries: list[ComodatoClientSummary], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_comodato_client_menu(
            query_text=query_text,
            summaries=summaries,
            invalid_selection=invalid_selection,
        )

    def _build_visit_day_options(self, visit_days: list[str] | tuple[str, ...], *, description: str) -> tuple[InteractiveOption, ...]:
        return self.search_flow._build_visit_day_options(
            visit_days=visit_days,
            description=description,
        )

    def _select_visit_day_option(self, *, text: str, normalized: str, visit_days: tuple[str, ...], description: str) -> str | None:
        return self.search_flow._select_visit_day_option(
            text=text,
            normalized=normalized,
            visit_days=visit_days,
            description=description,
        )

    def _build_visit_day_menu(self, decision: AccessDecision, visit_days: list[str], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_visit_day_menu(
            decision=decision,
            visit_days=visit_days,
            invalid_selection=invalid_selection,
        )

    def _build_giro_visit_day_menu(self, visit_days: list[str], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_giro_visit_day_menu(
            visit_days=visit_days,
            invalid_selection=invalid_selection,
        )


    def _build_inadimplencia_visit_day_menu(self, visit_days: list[str], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_inadimplencia_visit_day_menu(
            visit_days=visit_days,
            invalid_selection=invalid_selection,
        )

    def _build_documentacao_visit_day_menu(self, visit_days: list[str], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_documentacao_visit_day_menu(
            visit_days=visit_days,
            invalid_selection=invalid_selection,
        )

    def _build_visit_day_manager_menu(self, visit_day: str, visit_summaries: list[VisitSellerSummary], invalid_selection: bool = False) -> OutgoingMessage:
        return self.search_flow._build_visit_day_manager_menu(
            visit_day=visit_day,
            visit_summaries=visit_summaries,
            invalid_selection=invalid_selection,
        )

    def _build_single_record_response(self, record: DClienteRecord, criteria: str, *, decision: AccessDecision) -> OutgoingMessage:
        return self.search_flow._build_single_record_response(
            record=record,
            criteria=criteria,
            decision=decision,
        )

    def _build_search_response(self, records: list[DClienteRecord], criteria: str, *, decision: AccessDecision, scope_restricted: bool = True) -> OutgoingMessage:
        return self.search_flow._build_search_response(
            records=records,
            criteria=criteria,
            decision=decision,
            scope_restricted=scope_restricted,
        )

    def _append_cliente_detail_lines(self, lines: list[str], *, record: DClienteRecord, decision: AccessDecision, index: int | None = None, scope_restricted: bool = True) -> None:
        return self.search_flow._append_cliente_detail_lines(
            lines=lines,
            record=record,
            decision=decision,
            index=index,
            scope_restricted=scope_restricted,
        )

    def _safe_cliente_score_record(self, record: DClienteRecord) -> ClienteScoreRecord | None:
        return self.search_flow._safe_cliente_score_record(
            record=record,
        )

    def _safe_cliente_score_by_registration(self, *, filial: str, cod_pdv: str) -> ClienteScoreRecord | None:
        return self.search_flow._safe_cliente_score_by_registration(
            filial=filial,
            cod_pdv=cod_pdv,
        )

    def _cliente_score_service_ready(self) -> bool:
        return self.search_flow._cliente_score_service_ready()

    def _append_cliente_score_lines(self, lines: list[str], score_record: ClienteScoreRecord | None) -> None:
        return self.search_flow._append_cliente_score_lines(
            lines=lines,
            score_record=score_record,
        )

    def _append_documentacao_cliente_lines(self, lines: list[str], *, decision: AccessDecision, record: DClienteRecord, scope_restricted: bool = True) -> None:
        return self.search_flow._append_documentacao_cliente_lines(
            lines=lines,
            decision=decision,
            record=record,
            scope_restricted=scope_restricted,
        )

    def _safe_documentacao_cliente_record(self, *, decision: AccessDecision, record: DClienteRecord, scope_restricted: bool = True) -> DocumentacaoPendenteClientRecord | None:
        return self.search_flow._safe_documentacao_cliente_record(
            decision=decision,
            record=record,
            scope_restricted=scope_restricted,
        )

    def _safe_documentacao_registration_record(self, *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool = True) -> DocumentacaoPendenteClientRecord | None:
        return self.search_flow._safe_documentacao_registration_record(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
            scope_restricted=scope_restricted,
        )

    def _append_documentacao_snapshot_lines(self, lines: list[str], *, decision: AccessDecision, filial: str, cod_pdv: str) -> None:
        return self.search_flow._append_documentacao_snapshot_lines(
            lines=lines,
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
        )

    def _append_documentacao_snapshot_detail_lines(self, lines: list[str], *, decision: AccessDecision, filial: str, cod_pdv: str) -> None:
        return self.search_flow._append_documentacao_snapshot_detail_lines(
            lines=lines,
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
        )

    def _run_repeatable_registration_lookup(self, *, sender: str, session: LookupSession, decision: AccessDecision, search_context: str, filial: str, cod_pdv: str, return_menu: str = 'search_menu') -> OutgoingMessage:
        return self.search_flow._run_repeatable_registration_lookup(
            sender=sender,
            session=session,
            decision=decision,
            search_context=search_context,
            filial=filial,
            cod_pdv=cod_pdv,
            return_menu=return_menu,
        )

    def _run_registration_lookup(self, decision: AccessDecision, search_context: str, filial: str, cod_pdv: str) -> OutgoingMessage:
        return self.search_flow._run_registration_lookup(
            decision=decision,
            search_context=search_context,
            filial=filial,
            cod_pdv=cod_pdv,
        )

    def _search_giro_by_document(self, normalized_document: str) -> list[GiroClientRecord]:
        return self.search_flow._search_giro_by_document(
            normalized_document=normalized_document,
        )

    def _build_inadimplencia_response(self, records: list[InadimplenciaRecord], criteria: str, *, compact: bool = False) -> OutgoingMessage:
        return self.search_flow._build_inadimplencia_response(
            records=records,
            criteria=criteria,
            compact=compact,
        )

    def _build_comodato_response(self, records: list[ComodatoRecord], criteria: str) -> OutgoingMessage:
        return self.search_flow._build_comodato_response(
            records=records,
            criteria=criteria,
        )

    def _build_giro_response(self, records: list[GiroClientRecord], criteria: str, scope_restricted: bool = True) -> OutgoingMessage:
        return self.search_flow._build_giro_response(
            records=records,
            criteria=criteria,
            scope_restricted=scope_restricted,
        )


    def _build_visit_day_clients_response(self, visit_day: str, records: list[DClienteRecord], decision: AccessDecision, financial_alerts: list[InadimplenciaVisitAlert], alerts_note: str) -> OutgoingMessage:
        return self.search_flow._build_visit_day_clients_response(
            visit_day=visit_day,
            records=records,
            decision=decision,
            financial_alerts=financial_alerts,
            alerts_note=alerts_note,
        )

    def _load_visit_day_seller_summaries(self, decision: AccessDecision, visit_day: str, *, limit: int = 1000) -> list[VisitSellerSummary]:
        return self.search_flow._load_visit_day_seller_summaries(
            decision=decision,
            visit_day=visit_day,
            limit=limit,
        )

    def _build_visit_day_seller_clients_response(self, visit_day: str, summary: VisitSellerSummary, records: list[DClienteRecord], decision: AccessDecision, financial_alerts: list[InadimplenciaVisitAlert], alerts_note: str) -> OutgoingMessage:
        return self.search_flow._build_visit_day_seller_clients_response(
            visit_day=visit_day,
            summary=summary,
            records=records,
            decision=decision,
            financial_alerts=financial_alerts,
            alerts_note=alerts_note,
        )

    def _build_visit_day_giro_summaries(self, decision: AccessDecision, records: list[DClienteRecord]) -> tuple[dict[tuple[str, str], tuple[str, str, str, str]], str]:
        return self.search_flow._build_visit_day_giro_summaries(
            decision=decision,
            records=records,
        )

    def _load_visit_day_financial_alerts(self, decision: AccessDecision, visit_day: str, seller_code: str = '', manager_code: str = '') -> tuple[list[InadimplenciaVisitAlert], str]:
        return self.search_flow._load_visit_day_financial_alerts(
            decision=decision,
            visit_day=visit_day,
            seller_code=seller_code,
            manager_code=manager_code,
        )

    def _append_visit_financial_section(self, lines: list[str], alerts: list[InadimplenciaVisitAlert], alerts_note: str) -> None:
        return self.search_flow._append_visit_financial_section(
            lines=lines,
            alerts=alerts,
            alerts_note=alerts_note,
        )

    def _append_visit_financial_group(self, lines: list[str], label: str, alerts: list[InadimplenciaVisitAlert]) -> None:
        return self.search_flow._append_visit_financial_group(
            lines=lines,
            label=label,
            alerts=alerts,
        )

    def _display_role(self, role_name: str) -> str:
        return self.admin_access_flow._display_role(
            role_name=role_name,
        )

    def _build_scope_prompt(self, role_name: str) -> str:
        return self.admin_access_flow._build_scope_prompt(
            role_name=role_name,
        )

    def _build_scope_retry_prompt(self, role_name: str) -> str:
        return self.admin_access_flow._build_scope_retry_prompt(
            role_name=role_name,
        )

    def _build_scope_not_found_prompt(self, role_name: str, codes: list[str]) -> str:
        return self.admin_access_flow._build_scope_not_found_prompt(
            role_name=role_name,
            codes=codes,
        )

    def _resolve_admin_scope_codes(self, text: str, role_name: str) -> tuple[list[str], str | None]:
        return self.admin_access_flow._resolve_admin_scope_codes(
            text=text,
            role_name=role_name,
        )

    def _format_user_access_label(self, roles: tuple[str, ...], sectors: tuple[str, ...], gv_vdes: tuple[str, ...]) -> str:
        return self.admin_access_flow._format_user_access_label(
            roles=roles,
            sectors=sectors,
            gv_vdes=gv_vdes,
        )

    def _reset_session(self, sender: str) -> None:
        existing = self.sessions.get(sender)
        if existing is None:
            self.sessions.pop(sender, None)
            return
        preserved = LookupSession(
            last_intent=existing.last_intent,
            last_search_context=existing.last_search_context,
            last_query_text=existing.last_query_text,
            last_client_filial=existing.last_client_filial,
            last_client_cod_pdv=existing.last_client_cod_pdv,
            last_client_name=existing.last_client_name,
            last_visit_day=existing.last_visit_day,
            last_context_updated_at=existing.last_context_updated_at,
            updated_at=datetime.now(timezone.utc),
        )
        self.sessions[sender] = preserved

    def _cleanup_sessions(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            sender
            for sender, session in self.sessions.items()
            if now - session.updated_at > self.session_ttl
        ]
        for sender in expired:
            self.sessions.pop(sender, None)
        expired_cache_keys = [
            cache_key
            for cache_key, (cached_at, _) in self._response_cache.items()
            if now - cached_at > self.response_cache_ttl
        ]
        for cache_key in expired_cache_keys:
            self._response_cache.pop(cache_key, None)


def _invalid_option_text(prompt: str) -> str:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return "Nao entendi essa opcao."
    return f"Nao entendi essa opcao.\n{prompt_text}"


def _format_yes_no(value: bool) -> str:
    return "Sim" if value else "Nao"


def _format_optional_count(value: int | None) -> str:
    return str(value) if value is not None else "-"


def _short_error_text(value: str, limit: int = 280) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned or "-"
    return f"{cleaned[:limit]}..."


def _is_payip_company_forbidden_error(value: str) -> bool:
    normalized = _normalize_choice(value)
    return (
        "empresa nao encontrada" in normalized
        or "http 403" in normalized
        or "forbidden" in normalized
    )


def _is_payip_pdf_not_ready_error(value: str) -> bool:
    normalized = _normalize_choice(value)
    return (
        "arquivo ainda nao foi criado" in normalized
        or "tente novamente" in normalized
    )


def _parse_payip_amount_day_query(
    text: str,
) -> tuple[str, Decimal | None, date | None, Decimal | None, bool]:
    raw = str(text or "").strip()
    if not raw:
        return "", None, None, None, False

    date_matches = list(
        re.finditer(
            r"(?<!\d)(\d{8}|\d{6}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
            raw,
        )
    )
    parsed_dates = [_parse_payip_statement_date_token(match.group(1)) for match in date_matches]
    invalid_date = any(item is None for item in parsed_dates)
    valid_dates = [item for item in parsed_dates if item is not None]
    if len(valid_dates) > 1:
        invalid_date = True

    text_without_dates = raw
    for match in reversed(date_matches):
        text_without_dates = text_without_dates[: match.start()] + " " + text_without_dates[match.end() :]

    normalized = _normalize_choice(text_without_dates)
    tokens = _normalized_tokens(normalized)
    if not valid_dates:
        today = datetime.now(LOCAL_TIMEZONE).date()
        if "hoje" in tokens:
            valid_dates = [today]
        elif "ontem" in tokens:
            valid_dates = [today - timedelta(days=1)]

    filial = _extract_payip_filial_query(text_without_dates)
    if not filial:
        for number in re.findall(r"\b\d{1,2}\b", text_without_dates):
            candidate = _normalize_filial(number)
            if candidate in FILIAL_LABELS:
                filial = candidate
                break

    amount_text = text_without_dates
    tolerance, tolerance_match, invalid_tolerance = _extract_payip_amount_day_tolerance(amount_text)
    if tolerance_match is not None:
        amount_text = amount_text[: tolerance_match.start()] + " " + amount_text[tolerance_match.end() :]
    if filial:
        amount_text = re.sub(
            rf"\b(?:filial|revenda)?\s*0*{re.escape(filial)}\b",
            " ",
            amount_text,
            count=1,
            flags=re.IGNORECASE,
        )
    amount_text = re.sub(
        r"\b(?:payip|valor|dia|pagamento|pagamentos|pago|pagos|paga|pagas|cobrancas?|buscar|busca|por|do|da|de|na|no|filial|revenda)\b",
        " ",
        amount_text,
        flags=re.IGNORECASE,
    )
    amount = _extract_payip_amount_search_value(amount_text)
    return (
        filial,
        amount,
        valid_dates[0] if len(valid_dates) == 1 else None,
        tolerance,
        invalid_date or invalid_tolerance,
    )


def _extract_payip_amount_day_tolerance(
    text: str,
) -> tuple[Decimal | None, re.Match[str] | None, bool]:
    match = re.search(
        r"\b(?:tolerancia|tol|margem)\s*(?:de|:|=)?\s*(R\$\s*)?(-?\d+(?:[.,]\d{1,2})?)",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None, None, False
    tolerance = _parse_decimal_text(match.group(2))
    return tolerance, match, tolerance is None or tolerance < 0


def _extract_payip_amount_search_value(text: str) -> Decimal | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    matches = [
        match.group(0).strip()
        for match in re.finditer(
            r"(?:R\$\s*)?\d{1,3}(?:\.\d{3})+,\d{1,2}|(?:R\$\s*)?\d+[,.]\d{1,2}|(?:R\$\s*)?\b\d+\b",
            raw,
            flags=re.IGNORECASE,
        )
    ]
    preferred = [item for item in matches if "r$" in item.lower() or "," in item or "." in item]
    for candidate in preferred + matches:
        amount = _parse_decimal_text(candidate)
        if amount is not None:
            return amount
    return None


def _parse_payip_statement_query(text: str) -> tuple[str, date | None, date | None, bool]:
    raw = str(text or "").strip()
    if not raw:
        return "", None, None, False

    date_matches = list(
        re.finditer(
            r"(?<!\d)(\d{8}|\d{6}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
            raw,
        )
    )
    parsed_dates = [_parse_payip_statement_date_token(match.group(1)) for match in date_matches]
    invalid_date = any(item is None for item in parsed_dates)
    valid_dates = [item for item in parsed_dates if item is not None]
    if len(valid_dates) == 1 or len(valid_dates) > 2:
        invalid_date = True

    text_without_dates = raw
    for match in reversed(date_matches):
        text_without_dates = text_without_dates[: match.start()] + " " + text_without_dates[match.end() :]

    filial = _extract_payip_filial_query(text_without_dates)
    if not filial:
        for number in re.findall(r"\b\d{1,2}\b", text_without_dates):
            candidate = _normalize_filial(number)
            if candidate in FILIAL_LABELS:
                filial = candidate
                break

    if len(valid_dates) == 2:
        return filial, valid_dates[0], valid_dates[1], invalid_date
    return filial, None, None, invalid_date


def _normalize_payip_statement_period(
    *,
    date_start: date | str | None,
    date_end: date | str | None,
) -> tuple[date, date, bool]:
    today = datetime.now(LOCAL_TIMEZONE).date()
    parsed_start = _coerce_payip_statement_date(date_start)
    parsed_end = _coerce_payip_statement_date(date_end)
    if parsed_start is None and parsed_end is None:
        parsed_start = today.replace(day=1)
        parsed_end = today
    elif parsed_start is None or parsed_end is None:
        return today.replace(day=1), today, True

    invalid = parsed_start > parsed_end or parsed_end > today
    return parsed_start, parsed_end, invalid


def _coerce_payip_statement_date(value: date | str | None) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    return _parse_payip_statement_date_token(text)


def _parse_payip_statement_date_token(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        compact = re.fullmatch(r"(\d{2})(\d{2})(\d{2}|\d{4})", text)
        if compact:
            day = int(compact.group(1))
            month = int(compact.group(2))
            year_text = compact.group(3)
            year = 2000 + int(year_text) if len(year_text) == 2 else int(year_text)
            return date(year, month, day)
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", text)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year_text = match.group(3)
            if year_text is None:
                year = datetime.now(LOCAL_TIMEZONE).date().year
            elif len(year_text) == 2:
                year = 2000 + int(year_text)
            else:
                year = int(year_text)
            return date(year, month, day)
    except ValueError:
        return None
    return None


def _extract_mfa_code(text: str) -> str:
    raw = str(text or "").strip()
    exact_digits = "".join(char for char in raw if char.isdigit())
    if len(exact_digits) == 6:
        return exact_digits
    match = re.search(r"\b(\d{6})\b", raw)
    return match.group(1) if match else ""


def _extract_payip_invoice_query(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    pair = _extract_payip_filial_value_pair(raw)
    if pair and len(pair[1]) >= 4:
        return pair[1]

    normalized = _normalize_choice(raw)
    explicit_invoice = bool(
        re.search(r"\b(?:nota\s+fiscal|nota|nf|nfe|invoice)\b", normalized)
    )
    numbers = re.findall(r"\d+", raw)
    if explicit_invoice and numbers:
        return max(numbers, key=len).strip()

    explicit_match = re.search(
        r"\b(?:nota\s+fiscal|nota|nf|nfe|invoice)\b\D*([a-z0-9][a-z0-9._-]{1,40})",
        normalized,
    )
    if explicit_match:
        candidate = explicit_match.group(1).strip("._-")
        if re.search(r"\d", candidate):
            return candidate

    if re.fullmatch(r"\d{4,}", raw):
        return raw
    return ""


def _extract_payip_client_code_query(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""

    pair = _extract_payip_filial_value_pair(raw)
    if pair:
        return _normalize_cod_pdv(pair[1])

    numbers = re.findall(r"\d+", raw)
    if not numbers:
        return ""

    normalized = _normalize_choice(raw)
    tokens = _normalized_tokens(normalized)
    explicit_client_code = bool(
        {"nb", "cliente", "client", "clientcode", "codigo", "cod", "pdv"} & tokens
    )
    if explicit_client_code:
        return _normalize_cod_pdv(numbers[-1])
    if re.fullmatch(r"\d{1,5}", raw):
        return _normalize_cod_pdv(raw)
    return ""


def _extract_payip_filial_query(text: str) -> str:
    pair = _extract_payip_filial_value_pair(text)
    if pair:
        return pair[0]

    normalized = _normalize_choice(text)
    filial_match = re.search(r"\b(?:filial|revenda)\s*(\d{1,2})\b", normalized)
    if filial_match:
        return _normalize_filial(filial_match.group(1))
    return ""


def _extract_payip_filial_value_pair(text: str) -> tuple[str, str] | None:
    raw = str(text or "").strip()
    numbers = re.findall(r"\d+", raw)
    if len(numbers) < 2:
        return None
    first = _normalize_filial(numbers[0])
    if first not in FILIAL_LABELS:
        return None
    return first, numbers[1]


def _resolve_payip_filial(filial: str) -> str:
    normalized_filial = _normalize_filial(filial)
    if normalized_filial:
        return normalized_filial
    return ""


def _extract_payip_pix_payloads(
    items: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    filial: str = "",
    company_id: str = "",
) -> tuple[PayipPixPayload, ...]:
    payloads: list[PayipPixPayload] = []
    for payment in items:
        if not isinstance(payment, dict):
            continue
        pix_code = _payip_text(_payip_value(payment, "qrCodePixCashin", "emv"))
        if not pix_code or pix_code == "-":
            continue
        invoice = _payip_text(_payip_value(payment, "invoice"))
        qr_image = _payip_text(_payip_value(payment, "qrCodePixCashin", "linkImage"))
        payment_id = _payip_text(_payip_value(payment, "id"))
        payment_company_id = str(
            _payip_value(payment, "company", "companyId")
            or _payip_value(payment, "companyId")
            or company_id
            or ""
        ).strip()
        label_parts = []
        if invoice and invoice != "-":
            label_parts.append(f"NF {invoice}")
        label = " | ".join(label_parts) or "Pagamento PayIP"
        payloads.append(
            PayipPixPayload(
                label=label,
                pix_code=pix_code,
                qr_image=qr_image if qr_image != "-" else "",
                payment_id=payment_id if payment_id != "-" else "",
                filial=filial,
                company_id=payment_company_id,
            )
        )
        if len(payloads) >= 5:
            break
    return tuple(payloads)


def _select_payip_created_payment_items(
    items: tuple[dict[str, Any], ...],
    *,
    payment: dict[str, Any],
    session: LookupSession,
) -> tuple[dict[str, Any], ...]:
    created_id = _payip_clean_text(_payip_value(payment, "id"))
    if created_id:
        exact_id = [item for item in items if _payip_clean_text(_payip_value(item, "id")) == created_id]
        if exact_id:
            return tuple(exact_id[:1])

    created_external_id = _payip_clean_text(_payip_value(payment, "externalId")) or session.payip_charge_external_id
    if created_external_id:
        exact_external = [
            item
            for item in items
            if _payip_clean_text(_payip_value(item, "externalId")) == created_external_id
        ]
        if exact_external:
            return tuple(exact_external[:1])

    target_tax_payer = _normalize_document(session.payip_charge_tax_payer_id)
    target_due_date = str(session.payip_charge_due_date or "").strip()
    target_amount = _parse_decimal_text(session.payip_charge_amount)
    matching_context: list[dict[str, Any]] = []
    for item in items:
        item_tax_payer = _normalize_document(
            str(
                _payip_value(item, "client", "taxPayerId")
                or _payip_value(item, "taxPayerId")
                or ""
            )
        )
        item_due_date = str(_payip_value(item, "dueDate") or "").strip()
        item_amount = _parse_decimal_text(
            _payip_value(item, "amount")
            or _payip_value(item, "amountDetails", "amount")
        )
        if target_tax_payer and item_tax_payer != target_tax_payer:
            continue
        if target_due_date and not item_due_date.startswith(target_due_date):
            continue
        if target_amount is not None and item_amount is not None and item_amount != target_amount:
            continue
        matching_context.append(item)
    if matching_context:
        return tuple(matching_context[:1])
    if len(items) == 1:
        return items
    return ()


def _payip_clean_text(value: Any) -> str:
    text = _payip_text(value)
    return "" if text == "-" else text


def _parse_payip_pix_selection(normalized_text: str) -> int | None:
    text = str(normalized_text or "").strip()
    match = re.search(r"\b(?:pix|codigo pix|copiar pix|copia pix|copia e cola)\s*(\d{1,2})?\b", text)
    if not match:
        return None
    raw_index = match.group(1) or "1"
    try:
        return max(int(raw_index), 1)
    except ValueError:
        return 1


def _parse_payip_client_filter(normalized_text: str) -> str:
    text = str(normalized_text or "").strip()
    tokens = _normalized_tokens(text)
    if text in {
        "1",
        "pendente",
        "pendentes",
        "somente pendentes",
        "so pendentes",
        "apenas pendentes",
        "pending",
    }:
        return "pending"
    if {"pendente", "pendentes", "pending"} & tokens:
        return "pending"
    if text in {
        "2",
        "todos",
        "todos os status",
        "todos status",
        "todo",
        "geral",
        "all",
    }:
        return "all"
    if {"todos", "todo", "all", "geral"} & tokens:
        return "all"
    return ""


def _parse_payip_charge_amount(text: str) -> Decimal | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    return _parse_decimal_text(raw)


def _parse_payip_charge_due_date(text: str) -> date | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    normalized = _normalize_choice(raw)
    today = datetime.now(LOCAL_TIMEZONE).date()
    if normalized == "hoje":
        return today
    if normalized in {"amanha", "amanha"}:
        return today + timedelta(days=1)

    digits = re.findall(r"\d+", raw)
    if len(digits) == 3:
        first, second, third = digits
        try:
            if len(first) == 4:
                return date(int(first), int(second), int(third))
            year = int(third)
            if len(third) == 2:
                year += 2000
            return date(year, int(second), int(first))
        except ValueError:
            return None
    if re.fullmatch(r"\d{8}", raw):
        try:
            return date(int(raw[4:]), int(raw[2:4]), int(raw[:2]))
        except ValueError:
            return None
    return None


def _parse_payip_charge_adjustment(text: str) -> tuple[str, Decimal | str] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    normalized = _normalize_choice(raw)
    tokens = _normalized_tokens(normalized)

    if "taxa" in tokens:
        if {"padrao", "default"} & tokens:
            return "rate", Decimal("3.92")
        if normalized.startswith("sem taxa"):
            return "rate", Decimal("0")
        amount = _extract_decimal_from_text(raw)
        if amount is None or amount < 0:
            return None
        return "rate", amount

    if "juros" in tokens or "juro" in tokens:
        if {"padrao", "default"} & tokens:
            return "interest", Decimal("10")
        if normalized.startswith(("sem juros", "sem juro")):
            return "interest", Decimal("0")
        amount = _extract_decimal_from_text(raw)
        if amount is None or amount < 0:
            return None
        return "interest", amount

    if {"vencimento", "venc", "data"} & tokens:
        cleaned = re.sub(r"\b(?:vencimento|venc|data|para|em)\b", " ", raw, flags=re.IGNORECASE)
        cleaned = " ".join(cleaned.split())
        if cleaned:
            return "due_date", cleaned

    if {"nf", "nfe", "nota", "fiscal", "invoice"} & tokens:
        if normalized.startswith(("sem nf", "sem nota", "sem nfe", "sem invoice")):
            return "invoice", ""
        invoice = _extract_payip_invoice_query(raw)
        if invoice:
            return "invoice", invoice

    if {"nb", "externalid", "erp", "identificador"} & tokens:
        if normalized.startswith(("sem nb", "sem externalid", "sem erp", "sem identificador")):
            return "external_id", ""
        external_id = _extract_payip_external_id_adjustment(raw)
        if external_id:
            return "external_id", external_id
    return None


def _extract_decimal_from_text(text: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(text or ""))
    if not match:
        return None
    return _parse_decimal_text(match.group(0))


def _extract_payip_external_id_adjustment(text: str) -> str:
    normalized = _normalize_choice(text)
    match = re.search(r"\b(?:nb|externalid|erp|identificador)\b\D*([a-z0-9][a-z0-9._-]{0,40})", normalized)
    if match:
        candidate = match.group(1).strip("._-")
        if candidate and re.search(r"\d", candidate):
            return candidate
    numbers = re.findall(r"\d+", str(text or ""))
    return numbers[-1] if numbers else ""


def _parse_iso_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _decimal_cache_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _payip_charge_rate_amount(session: LookupSession) -> Decimal:
    parsed = _parse_decimal_text(session.payip_charge_rate_amount)
    if parsed is None:
        return Decimal("3.92")
    return max(parsed, Decimal("0"))


def _payip_charge_interest_perc(session: LookupSession) -> Decimal:
    parsed = _parse_decimal_text(session.payip_charge_interest_perc)
    if parsed is None:
        return Decimal("10")
    return max(parsed, Decimal("0"))


def _format_decimal_percent(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if normalized == normalized.to_integral_value():
        return f"{int(normalized)}%"
    text = f"{normalized:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text}%"


def _payip_charge_title(filial: str) -> str:
    normalized_filial = _normalize_filial(filial)
    filial_name = FILIAL_LABELS.get(normalized_filial) or normalized_filial
    return f"Fatura revenda Pau Brasil - {filial_name}"


def _format_tax_payer_id(value: str) -> str:
    digits = _normalize_document(value)
    if len(digits) == 11:
        return _format_cpf(digits)
    if len(digits) == 14:
        return _format_cnpj(digits)
    return str(value or "-").strip() or "-"


def _payip_search_label(
    action: str,
    invoice: str = "",
    client_code: str = "",
    *,
    filial: str = "",
    status: str = "",
) -> str:
    suffix = f" | Revenda: {_format_filial_label(filial)}" if filial else ""
    if action == "invoice":
        return f"NF {invoice}{suffix}"
    if action == "pending_client" or status == "PENDING":
        return f"NB {client_code} pendentes{suffix}"
    if action == "client":
        return f"NB {client_code} todos os status{suffix}"
    return f"PayIP{suffix}"


def _payip_response_labels(
    *,
    action: str,
    filial: str,
    invoice: str = "",
    client_code: str = "",
    status: str = "",
) -> tuple[str, str, str]:
    filial_label = _format_filial_label(filial)
    if action == "invoice":
        return (
            f"PayIP | Nota Fiscal {invoice}",
            f"Revenda: {filial_label} | Filtro: invoice={invoice}",
            f"Nao encontrei pagamentos para a nota fiscal {invoice} nessa revenda.",
        )
    if action == "pending_client" or status == "PENDING":
        return (
            f"PayIP | Pendentes NB {client_code}",
            f"Revenda: {filial_label} | Filtro: status=PENDING | clientCode={client_code}",
            f"Nao encontrei pagamentos pendentes para o NB {client_code} nessa revenda.",
        )
    return (
        f"PayIP | Pagamentos NB {client_code}",
        f"Revenda: {filial_label} | Filtro: clientCode={client_code}",
        f"Nao encontrei pagamentos para o NB {client_code} nessa revenda.",
    )


def _payip_post_create_search_criteria(*, client_code: str, due_date: str, created_at: str) -> str:
    parts = ["status=PENDING"]
    if client_code:
        parts.append(f"clientCode={client_code}")
    if due_date:
        parts.append(f"dueDate={due_date}")
    if created_at:
        parts.append(f"createdAt={created_at}")
    return " | ".join(parts)


def _build_payip_statement_resume_response(
    resume: Any,
    *,
    filial: str = "",
    date_start: str = "",
    date_end: str = "",
    pdf_bytes: bytes = b"",
    xlsx_bytes: bytes = b"",
    export_errors: tuple[str, ...] = (),
) -> OutgoingMessage:
    raw = getattr(resume, "raw", resume)
    filial = str(getattr(resume, "filial", "") or filial or "").strip()
    date_start = str(getattr(resume, "date_start", "") or date_start or "").strip()
    date_end = str(getattr(resume, "date_end", "") or date_end or "").strip()

    lines = [
        "PayIP | Extrato",
        "",
        f"Revenda: {_format_filial_label(filial)}" if filial else "Revenda: -",
    ]
    if date_start or date_end:
        lines.append(f"Periodo: {_format_display_date(date_start)} a {_format_display_date(date_end)}")

    fields = _format_payip_statement_resume_fields(raw)
    if fields:
        lines.append("")
        lines.extend(fields)
    else:
        lines.extend(
            [
                "",
                "Consulta realizada, mas a PayIP nao retornou campos de resumo reconheciveis.",
            ]
        )

    if pdf_bytes or xlsx_bytes or export_errors:
        lines.append("")
        if pdf_bytes and xlsx_bytes:
            lines.append("Arquivos: PDF e XLSX anexados.")
        elif pdf_bytes:
            lines.append("Arquivos: PDF anexado.")
        elif xlsx_bytes:
            lines.append("Arquivos: XLSX anexado.")
        if export_errors:
            lines.append("Falha ao gerar arquivo:")
            lines.extend(f"- {item}" for item in export_errors)

    lines.append("")
    lines.append(_result_hint_text(allow_back=True))
    return _build_payip_statement_media_response(
        text="\n".join(lines),
        resume=resume,
        pdf_bytes=pdf_bytes,
        xlsx_bytes=xlsx_bytes,
    )


def _build_payip_statement_media_response(
    *,
    text: str,
    resume: Any,
    pdf_bytes: bytes,
    xlsx_bytes: bytes,
) -> OutgoingMessage:
    attachments: list[MediaAttachment] = []
    filename_base = _payip_statement_filename_base(resume)
    if pdf_bytes:
        attachments.append(
            MediaAttachment(
                media_url=_build_pdf_data_url(pdf_bytes),
                media_type="document",
                media_caption="Extrato PayIP PDF",
                media_filename=f"{filename_base}.pdf",
            )
        )
    if xlsx_bytes:
        attachments.append(
            MediaAttachment(
                media_url=_build_xlsx_data_url(xlsx_bytes),
                media_type="document",
                media_caption="Extrato PayIP XLSX",
                media_filename=f"{filename_base}.xlsx",
            )
        )
    attachments = [attachment for attachment in attachments if attachment.media_url]
    if not attachments:
        return OutgoingMessage(text=text)
    first = attachments[0]
    return OutgoingMessage(
        text=text,
        kind="media",
        media_url=first.media_url,
        media_type=first.media_type,
        media_caption=first.media_caption,
        media_filename=first.media_filename,
        extra_media=tuple(attachments[1:]),
    )


def _build_critica_pdf_media_response(
    *,
    text: str,
    main_pdf_bytes: bytes,
    main_caption: str,
    main_filename: str,
    summary_pdf_bytes: bytes,
    summary_caption: str,
    summary_filename: str,
) -> OutgoingMessage:
    attachments: list[MediaAttachment] = []
    if main_pdf_bytes:
        attachments.append(
            MediaAttachment(
                media_url=_build_pdf_data_url(main_pdf_bytes),
                media_type="document",
                media_caption=main_caption,
                media_filename=main_filename,
            )
        )
    if summary_pdf_bytes:
        attachments.append(
            MediaAttachment(
                media_url=_build_pdf_data_url(summary_pdf_bytes),
                media_type="document",
                media_caption=summary_caption,
                media_filename=summary_filename,
            )
        )
    attachments = [attachment for attachment in attachments if attachment.media_url]
    if not attachments:
        return OutgoingMessage(text=text)
    first = attachments[0]
    return OutgoingMessage(
        text=text,
        kind="media",
        media_url=first.media_url,
        media_type=first.media_type,
        media_caption=first.media_caption,
        media_filename=first.media_filename,
        extra_media=tuple(attachments[1:]),
    )


def _payip_statement_filename_base(resume: Any) -> str:
    filial = str(getattr(resume, "filial", "") or "payip").strip()
    date_start = str(getattr(resume, "date_start", "") or "").strip()
    date_end = str(getattr(resume, "date_end", "") or "").strip()
    raw = f"payip-extrato-{filial}-{date_start}-a-{date_end}"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower()
    return safe or "payip-extrato"


def _format_payip_statement_resume_fields(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        text = _payip_text(raw)
        if text in {"", "-", "None", "null"}:
            return []
        return [text[:900]] if text else []

    rows: list[str] = []
    seen: set[str] = set()
    for path, key, value in _iter_payip_statement_scalar_fields(raw):
        label = _payip_statement_field_label(path, key)
        if not label or label in seen:
            continue
        formatted = _format_payip_statement_value(key, value)
        if formatted in {"", "-"}:
            continue
        rows.append(f"{label}: {formatted}")
        seen.add(label)
        if len(rows) >= 20:
            break
    return rows


def _iter_payip_statement_scalar_fields(
    value: Any,
    *,
    prefix: tuple[str, ...] = (),
) -> list[tuple[tuple[str, ...], str, Any]]:
    rows: list[tuple[tuple[str, ...], str, Any]] = []
    if not isinstance(value, dict):
        return rows
    for key, item in value.items():
        key_text = str(key or "").strip()
        if not key_text or _is_hidden_payip_statement_key(key_text):
            continue
        if isinstance(item, dict):
            rows.extend(_iter_payip_statement_scalar_fields(item, prefix=prefix + (key_text,)))
            continue
        if isinstance(item, list):
            if item and all(not isinstance(child, (dict, list)) for child in item):
                rows.append((prefix, key_text, ", ".join(_payip_text(child) for child in item if _payip_text(child))))
            continue
        rows.append((prefix, key_text, item))
    return rows


def _is_hidden_payip_statement_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in {
        "id",
        "uuid",
        "companyid",
        "paymentid",
        "accountid",
        "walletid",
        "session",
        "token",
        "total",
    }


def _payip_statement_field_label(path: tuple[str, ...], key: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    labels = {
        "currentbalance": "Saldo atual",
        "balance": "Saldo",
        "initialbalance": "Saldo inicial",
        "previousbalance": "Saldo anterior",
        "finalbalance": "Saldo final",
        "availablebalance": "Saldo disponivel",
        "blockedbalance": "Saldo bloqueado",
        "totalcredit": "Entrada",
        "totalcredits": "Entrada",
        "totalcredt": "Entrada",
        "totalcredts": "Entrada",
        "credit": "Entrada",
        "credits": "Entrada",
        "totaldebit": "Movimentacao",
        "totaldebits": "Movimentacao",
        "debit": "Movimentacao",
        "debits": "Movimentacao",
        "totalinput": "Entrada",
        "input": "Entrada",
        "totaloutput": "Movimentacao",
        "output": "Movimentacao",
        "amountinput": "Entrada",
        "amountoutput": "Movimentacao",
        "movementcount": "Movimentos",
        "movements": "Movimentos",
        "totalmovements": "Movimentos",
        "date": "Data",
        "datestart": "Data inicial",
        "dateend": "Data final",
    }
    base_label = labels.get(normalized) or _humanize_payip_statement_key(key)
    if path:
        path_label = " / ".join(_humanize_payip_statement_key(item) for item in path if item)
        if path_label:
            return f"{path_label} - {base_label}"
    return base_label


def _humanize_payip_statement_key(key: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", str(key or ""))
    spaced = re.sub(r"[_\-.]+", " ", spaced)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    if not spaced:
        return ""
    words = {
        "amount": "valor",
        "total": "total",
        "balance": "saldo",
        "credit": "entrada",
        "debit": "saida",
        "input": "entrada",
        "output": "saida",
        "count": "quantidade",
    }
    translated = " ".join(words.get(part.lower(), part) for part in spaced.split())
    return translated[:1].upper() + translated[1:]


def _format_payip_statement_value(key: str, value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return _format_yes_no(value)
    if _looks_like_payip_money_field(key, value):
        return _format_currency_brl(value)
    if isinstance(value, (int, float, Decimal)):
        return _format_quantity(value)
    text = _payip_text(value)
    parsed_date = _parse_payip_datetime(text)
    if parsed_date is not None and re.search(r"\d{4}-\d{2}-\d{2}", text):
        return parsed_date.astimezone(LOCAL_TIMEZONE).strftime("%d/%m/%Y")
    return text


def _looks_like_payip_money_field(key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if _parse_decimal_text(value) is None:
        return False
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(
        part in normalized
        for part in (
            "amount",
            "balance",
            "value",
            "valor",
            "credit",
            "debit",
            "input",
            "output",
            "total",
        )
    ) and "count" not in normalized and "quantity" not in normalized


def _build_payip_pix_code_response(
    payloads: tuple[PayipPixPayload, ...] | tuple[tuple[str, str, str], ...],
    *,
    selection: int,
    payip_payments_service: PayipPaymentsService | None = None,
    pdf_attempts: int = 1,
    pdf_retry_delay_seconds: float = 0.0,
) -> OutgoingMessage:
    index = selection - 1
    if index < 0 or index >= len(payloads):
        return OutgoingMessage(
            text=(
                f"Nao encontrei PIX {selection} nessa consulta.\n"
                f"Envie PIX 1 ate PIX {len(payloads)}.\n"
                "Para voltar, envie A ou ANT."
            )
        )
    payload = _coerce_payip_pix_payload(payloads[index])
    label = payload.label
    pix_code = payload.pix_code
    pdf_detail = ""
    if payip_payments_service is not None and payload.payment_id:
        attempts = max(int(pdf_attempts or 1), 1)
        for attempt in range(1, attempts + 1):
            try:
                pdf_bytes = payip_payments_service.invoice_report_pdf(
                    filial=payload.filial,
                    company_id=payload.company_id,
                    payment_ids=[payload.payment_id],
                )
                pdf_url = _build_pdf_data_url(pdf_bytes)
                if pdf_url:
                    return OutgoingMessage(
                        text=pix_code,
                        kind="media",
                        media_url=pdf_url,
                        media_type="document",
                        media_caption=f"PDF cobranca PayIP | {label}",
                        media_filename=_payip_pdf_filename(payload),
                    )
            except (PayipError, RuntimeError) as exc:
                pdf_detail = _short_error_text(str(exc))
                if (
                    attempt < attempts
                    and pdf_retry_delay_seconds > 0
                    and _is_payip_pdf_not_ready_error(str(exc))
                ):
                    time.sleep(pdf_retry_delay_seconds)
                    continue
                break

    if pdf_detail:
        return OutgoingMessage(
            text=(
                f"{pix_code}\n\n"
                "Nao consegui gerar o PDF da cobranca agora.\n"
                f"Detalhe: {pdf_detail}\n"
                "Aguarde alguns segundos e envie PIX 1 para tentar novamente."
            )
        )

    qr_image = payload.qr_image or _generate_pix_qr_data_url(pix_code)
    if qr_image:
        return OutgoingMessage(
            text=pix_code,
            kind="media",
            media_url=qr_image,
            media_type="image",
            media_caption=f"QR Code PIX | {label}",
            media_filename="payip-qrcode.png",
        )
    return OutgoingMessage(text=pix_code)


def _coerce_payip_pix_payload(value: Any) -> PayipPixPayload:
    if isinstance(value, PayipPixPayload):
        return value
    if isinstance(value, tuple):
        label = str(value[0] if len(value) > 0 else "Pagamento PayIP").strip() or "Pagamento PayIP"
        pix_code = str(value[1] if len(value) > 1 else "").strip()
        qr_image = str(value[2] if len(value) > 2 else "").strip()
        return PayipPixPayload(label=label, pix_code=pix_code, qr_image=qr_image)
    return PayipPixPayload(label="Pagamento PayIP", pix_code=str(value or "").strip())


def _build_pdf_data_url(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        return ""
    encoded = base64.b64encode(pdf_bytes).decode("ascii")
    return f"data:application/pdf;base64,{encoded}"


def _build_xlsx_data_url(xlsx_bytes: bytes) -> str:
    if not xlsx_bytes:
        return ""
    encoded = base64.b64encode(xlsx_bytes).decode("ascii")
    return "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + encoded


def _build_csv_data_url(csv_bytes: bytes) -> str:
    if not csv_bytes:
        return ""
    encoded = base64.b64encode(csv_bytes).decode("ascii")
    return f"data:text/csv;base64,{encoded}"


def _payip_pdf_filename(payload: PayipPixPayload) -> str:
    raw = payload.payment_id or payload.label or "cobranca"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-").lower()
    return f"payip-cobranca-{safe or 'documento'}.pdf"


def _generate_pix_qr_data_url(pix_code: str) -> str:
    value = str(pix_code or "").strip()
    if not value:
        return ""
    try:
        import qrcode
    except ImportError:
        return ""

    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _build_payip_charge_created_search_response(
    *,
    payment: dict[str, Any],
    title: str,
    filial: str,
    fallback_client_name: str,
    fallback_client_code: str,
    used_search: bool,
    search_criteria: str,
    search_error: str = "",
) -> OutgoingMessage:
    pix_code = _payip_clean_text(_payip_value(payment, "qrCodePixCashin", "emv"))
    lines = ["Cobranca PayIP emitida com sucesso"]
    if pix_code:
        lines.extend(["", "PIX copia e cola:", pix_code])

    lines.extend(["", "Busca da cobranca emitida:"])
    if used_search:
        lines.append(search_criteria)
    elif search_error:
        lines.append("A cobranca foi emitida, mas a busca PayIP pos-emissao falhou.")
        lines.append(f"Detalhe: {search_error}")
    else:
        lines.append("A busca PayIP pos-emissao ainda nao retornou essa cobranca; usando os dados da emissao.")
    lines.append("")
    lines.extend(
        _format_payip_payment_block_for_charge_created(
            payment,
            fallback_filial=filial,
            fallback_client_name=fallback_client_name,
            fallback_client_code=fallback_client_code,
        )
    )
    if pix_code:
        lines.extend(
            [
                "",
                "Para receber o PDF da cobranca, envie PIX 1.",
                "Se a PayIP responder que o arquivo ainda nao foi criado, aguarde alguns segundos e envie PIX 1 novamente.",
            ]
        )
    return OutgoingMessage(text="\n".join(lines))


def _format_payip_payment_block_for_charge_created(
    payment: dict[str, Any],
    *,
    fallback_filial: str,
    fallback_client_name: str,
    fallback_client_code: str,
) -> list[str]:
    if _payip_clean_text(_payip_value(payment, "client", "name")) or _payip_clean_text(_payip_value(payment, "title")):
        return _format_payip_payment_block(payment)
    client_name = fallback_client_name or "-"
    client_code = fallback_client_code or "-"
    due_date = _format_payip_date(_payip_value(payment, "dueDate"))
    amount_total = _format_currency_brl(
        _payip_value(payment, "amountDetails", "amountTotal") or _payip_value(payment, "amount")
    )
    status = _format_payip_status(payment)
    return [
        f"Revenda: {_format_filial_label(fallback_filial)}",
        f"Cliente: {client_name} | NB {client_code}",
        f"Status: {status}",
        f"Valor: {amount_total}",
        f"Vencimento: {due_date}",
    ]


def _build_payip_charge_created_response(
    *,
    payment: dict[str, Any],
    fallback_filial: str,
    fallback_client_name: str,
    fallback_client_code: str,
) -> OutgoingMessage:
    client_name = _payip_text(
        _payip_value(payment, "client", "fantasyName")
        or _payip_value(payment, "client", "name")
        or fallback_client_name
    )
    client_code = _payip_text(_payip_value(payment, "client", "code") or fallback_client_code)
    due_date = _format_payip_date(_payip_value(payment, "dueDate"))
    amount_total = _format_currency_brl(
        _payip_value(payment, "amountDetails", "amountTotal") or _payip_value(payment, "amount")
    )
    status = _format_payip_status(payment)
    pix_code = _payip_text(_payip_value(payment, "qrCodePixCashin", "emv"))
    lines = [
        "Cobranca PayIP emitida com sucesso",
        "",
        f"Revenda: {_format_filial_label(fallback_filial)}",
        f"Cliente: {client_name}",
        f"NB: {client_code}",
        f"Status: {status}",
        f"Valor total: {amount_total}",
        f"Vencimento: {due_date}",
    ]
    if pix_code and pix_code != "-":
        lines.extend(
            [
                "",
                "PIX copia e cola:",
                pix_code,
                "",
                "Para receber o PIX novamente em mensagem separada, envie PIX 1.",
            ]
        )
    return OutgoingMessage(text="\n".join(lines))


def _format_payip_payment_block(payment: dict[str, Any], *, index: int | None = None) -> list[str]:
    lines: list[str] = []
    if index is not None:
        lines.append(f"{index}) Pagamento")

    invoice = _payip_text(_payip_value(payment, "invoice"))
    created_at = _format_payip_datetime(_payip_value(payment, "createdAt"))
    paid_date = _format_payip_datetime(_payip_value(payment, "paidDate"))
    due_date = _format_payip_date(_payip_value(payment, "dueDate"))
    client_code = _payip_text(_payip_value(payment, "client", "code"))
    client_name = _payip_text(
        _payip_value(payment, "client", "fantasyName")
        or _payip_value(payment, "client", "name")
    )
    amount = _format_currency_brl(_payip_value(payment, "amount"))
    amount_paid = _format_currency_brl(_payip_value(payment, "amountPaid"))
    payment_label = _format_payip_payment_method(payment)

    lines.append(f"Nota Fiscal: {invoice}")
    lines.append(f"Cliente: {client_name} | NB {client_code}")
    lines.append(f"Emissao: {created_at} | Vencimento: {due_date}")
    if paid_date and paid_date != "-":
        lines.append(f"Pagamento confirmado em: {paid_date}")
    lines.append(f"Status: {_format_payip_status(payment)}")
    lines.append(f"Valor: {amount} | Pago: {amount_paid}")
    lines.append(f"Pagamento: {payment_label}")
    pix_code = _payip_text(_payip_value(payment, "qrCodePixCashin", "emv"))
    if pix_code and pix_code != "-":
        pix_index = index or 1
        lines.append(f"PIX: envie PIX {pix_index} para receber copia e cola e PDF.")
    return lines


def _format_payip_payment_method(payment: dict[str, Any]) -> str:
    values = (
        _payip_text(_payip_value(payment, "paymentShape", "name")),
        _payip_text(_payip_value(payment, "paymentMethod", "name")),
        _payip_text(_payip_value(payment, "howWasitPaid")),
    )
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value == "-":
            continue
        normalized = _normalize_choice(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        labels.append(value)
    return " | ".join(labels) if labels else "-"


def _format_payip_status(payment: dict[str, Any]) -> str:
    qr_status = _payip_text(_payip_value(payment, "qrCodePixCashin", "statusPayment")).upper()
    apply_status = _payip_text(_payip_value(payment, "statusPaymentApply")).upper()
    raw_status = _payip_text(_payip_value(payment, "status")).upper()
    amount = _parse_decimal_text(_payip_value(payment, "amount"))
    amount_paid = _parse_decimal_text(_payip_value(payment, "amountPaid"))
    paid_date = _payip_text(_payip_value(payment, "paidDate"))

    if qr_status == "PAID" or apply_status == "CONFIRMED":
        return "PAGO"
    if amount is not None and amount_paid is not None and amount > 0 and amount_paid >= amount:
        return "PAGO"
    if paid_date and paid_date != "-":
        return "PAGO"

    for candidate in (apply_status, qr_status, raw_status):
        if not candidate or candidate == "-":
            continue
        status_map = {
            "PENDING": "PENDENTE",
            "PAID": "PAGO",
            "CONFIRMED": "CONFIRMADO",
            "CANCELED": "CANCELADO",
            "CANCELLED": "CANCELADO",
            "EXPIRED": "EXPIRADO",
            "RETURNED": "RETORNADO",
        }
        return status_map.get(candidate, candidate)
    return "-"


def _format_payip_date(value: Any) -> str:
    parsed = _parse_payip_datetime(value)
    if parsed is None:
        return _payip_text(value)
    return parsed.strftime("%d/%m/%Y")


def _format_payip_datetime(value: Any) -> str:
    parsed = _parse_payip_datetime(value)
    if parsed is None:
        return _payip_text(value)
    return parsed.strftime("%d/%m/%Y %H:%M")


def _parse_payip_datetime(value: Any) -> datetime | None:
    text = _payip_text(value)
    if not text or text == "-":
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            parsed = datetime.fromisoformat(text)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE)


def _payip_value(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _payip_text(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, dict):
        for key in ("number", "code", "id", "name", "value", "slug"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                return _payip_text(candidate)
        return "-"
    if isinstance(value, list):
        formatted = [_payip_text(item) for item in value]
        formatted = [item for item in formatted if item and item != "-"]
        return ", ".join(formatted) if formatted else "-"
    text = str(value).strip()
    return text if text else "-"


def _result_hint_text(*, allow_back: bool = False) -> str:
    if allow_back:
        return (
            "Quer fazer outra consulta do mesmo tipo? Envie SIM.\n"
            "Se quiser voltar, envie A ou ANT.\n"
            "Se preferir comecar de novo, envie MENU."
        )
    return (
        "Quer fazer outra consulta do mesmo tipo? Envie SIM.\n"
        "Se preferir comecar de novo, envie MENU."
    )


def _strip_result_hint(text: str) -> str:
    value = str(text or "").strip()
    for hint in (
        _result_hint_text(allow_back=True),
        _result_hint_text(allow_back=False),
        "Se quiser fazer outra consulta, envie MENU.",
        "Se quiser tentar outra consulta, envie MENU.",
        "Se quiser continuar, envie MENU.",
        "Se quiser voltar, envie A ou ANT.\nSe preferir começar de novo, envie MENU.",
        "Se quiser voltar, envie A ou ANT.\nSe preferir, envie MENU.",
    ):
        if value.endswith(hint):
            value = value[: -len(hint)].rstrip()
            value = value.rstrip("\n").rstrip()
    return value


def _normalize_choice(text: str) -> str:
    value = str(text or "").strip().lower()
    value = "".join(
        char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn"
    )
    value = re.sub(r"\s+", " ", value)
    return value


def _is_repeat_query_command(normalized_text: str) -> bool:
    return normalized_text in {
        "sim",
        "s",
        "nova",
        "nova consulta",
        "outra consulta",
        "consultar novamente",
        "repetir consulta",
    }


def _payip_repeat_action(action: str) -> str:
    return {
        "invoice": REPEAT_PAYIP_INVOICE,
        "pending_client": REPEAT_PAYIP_PENDING_CLIENT,
        "client": REPEAT_PAYIP_CLIENT,
    }.get(str(action or "").strip(), "")


def _normalize_filial(text: str) -> str:
    digits = "".join(char for char in str(text or "") if char.isdigit())
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _normalize_cod_pdv(text: str) -> str:
    digits = "".join(char for char in str(text or "") if char.isdigit())
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _looks_like_critica_command(normalized_text: str) -> bool:
    text = str(normalized_text or "").strip()
    return text == "critica" or text.startswith("critica ") or text.startswith("critica:")


def _parse_critica_action(normalized_text: str) -> str:
    text = str(normalized_text or "").strip()
    tokens = set(text.replace(":", " ").split())
    if text in {"critica", "critica rn", "critica pedidos", "critica pedido", "menu critica"}:
        return "menu"
    if "nb" in tokens or "pdv" in tokens:
        return "nb"
    if tokens & {"pdf", "completo", "completa", "relatorio"}:
        return "pdf"
    if tokens & {"problema", "problemas", "possivel", "possiveis", "divergencia", "divergencias"}:
        return "problems"
    _parsed_date, date_was_explicit = _parse_critica_target_date(text)
    filial, cod_pdv = _parse_critica_nb_query(text)
    if cod_pdv and (filial or not date_was_explicit):
        return "nb"
    return "summary"


def _critica_wants_pdf(normalized_text: str) -> bool:
    tokens = set(str(normalized_text or "").replace(":", " ").split())
    return bool(tokens & {"pdf", "completo", "completa", "relatorio"})


def _critica_wants_gv_summary_pdf(normalized_text: str) -> bool:
    tokens = set(str(normalized_text or "").replace(":", " ").split())
    return bool(tokens & {"gv", "gerencial", "gerente"}) and bool(tokens & {"pdf", "relatorio"})


def _parse_critica_sector_query(normalized_text: str) -> tuple[str, str]:
    text = _strip_critica_date_tokens(normalized_text)
    text = re.sub(
        r"\b(?:critica|rn|setor|hoje|ontem|pdf|completo|completa|relatorio|problema|problemas|nb|pdv|cliente|pedido|pedidos)\b",
        " ",
        text,
    )
    explicit_scope = ""
    loose_sector_code = ""
    for token in extract_scope_input_tokens(text):
        normalized_scope = normalize_sector_scope_input(token)
        if normalized_scope:
            explicit_scope = normalized_scope
            break
        normalized_code = normalize_numeric_code(token)
        if normalized_code and not loose_sector_code:
            loose_sector_code = normalized_code
    return explicit_scope, loose_sector_code


def _parse_critica_target_date(normalized_text: str) -> tuple[date | None, bool]:
    text = str(normalized_text or "").strip()
    tokens = set(text.replace(":", " ").split())
    if "hoje" in tokens:
        return datetime.now(LOCAL_TIMEZONE).date(), True
    if "ontem" in tokens:
        return datetime.now(LOCAL_TIMEZONE).date() - timedelta(days=1), True
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b", text)
    if date_match:
        parsed = _parse_payip_statement_date_token(date_match.group(1))
        if parsed is not None:
            return parsed, True
    return None, False


def _parse_critica_nb_query(normalized_text: str) -> tuple[str, str]:
    text = _strip_critica_date_tokens(normalized_text)
    text = re.sub(
        r"\b(?:critica|rn|nb|pdv|cliente|pedido|pedidos|hoje|ontem|problema|problemas|possivel|possiveis|pdf|completo|completa|relatorio)\b",
        " ",
        text,
    )
    numbers = [normalize_numeric_code(item) for item in re.findall(r"\d+", text)]
    numbers = [item for item in numbers if item]
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    if len(numbers) == 1:
        return "", numbers[0]
    return "", ""


def _strip_critica_date_tokens(normalized_text: str) -> str:
    text = str(normalized_text or "")
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", " ", text)
    return text


def _build_critica_menu_response() -> OutgoingMessage:
    return OutgoingMessage(
        kind="menu",
        title="Critica RN",
        text=(
            "Critica RN\n\n"
            "Resumo rapido por mensagem:\n"
            "- critica hoje\n"
            "\n"
            "PDFs sob demanda:\n"
            "- critica pdf\n"
            "- critica pdf gv\n"
            "- critica pdf setor 400\n"
            "- critica nb pdf 3 18008\n\n"
            "Tambem aceito data. Exemplo: critica pdf 02/06/2026."
        ),
        footer="Escolha uma opcao ou envie o atalho completo.",
        options=(
            InteractiveOption(
                option_id="critica hoje",
                title="Critica hoje",
                description="Resumo dos pedidos do dia",
                shortcut="1",
            ),
            InteractiveOption(
                option_id="critica pdf",
                title="PDF geral",
                description="Consolidado da sua base",
                shortcut="2",
            ),
            InteractiveOption(
                option_id="critica pdf setor",
                title="PDF por setor",
                description="Informe o setor depois",
                shortcut="3",
            ),
            InteractiveOption(
                option_id="critica nb pdf",
                title="PDF por NB",
                description="Informe revenda e NB",
                shortcut="4",
            ),
        ),
    )


def _build_seller_finance_menu_response(invalid_selection: bool = False) -> OutgoingMessage:
    text = "O que voce quer solicitar?"
    if invalid_selection:
        text = _invalid_option_text("Escolha uma opcao do financeiro.")
    return OutgoingMessage(
        kind="menu",
        title="Financeiro",
        text=text,
        footer="Use A ou ANT para voltar, ou MENU para ir ao inicio.",
        button_text="Escolher",
        options=(
            InteractiveOption(
                option_id=SELLER_FINANCE_ACTION_RECOLHA,
                title="Solicitar Recolha",
                description="Registrar pedido de recolha",
                shortcut="1",
            ),
            InteractiveOption(
                option_id=SELLER_FINANCE_ACTION_BOLETO,
                title="Solicitar Boleto",
                description="Receber boleto por revenda e NB",
                shortcut="2",
            ),
        ),
    )


def _format_critica_operation_name(record: CriticaRnRecord) -> str:
    operation_name = str(record.operation_name or record.filial or "").strip()
    movement_name = str(record.movement_operation_name or "").strip()
    if operation_name and movement_name:
        return f"{operation_name} | {movement_name}"
    return operation_name or movement_name or "-"


def _format_critica_problem_block(record: CriticaRnRecord, *, index: int) -> list[str]:
    problem_text = "; ".join(record.problemas) or "OK"
    produto = f"{record.produto_codigo} - {record.produto_descricao or '-'}"
    return [
        f"{index}) Pedido {record.pedido} | Operacao {_format_critica_operation_name(record)} | Revenda {record.filial} | NB {record.cod_pdv} | Setor {record.setor or '-'}",
        record.nome_pdv or "-",
        f"Total pedido: {_format_currency_brl(record.total_pedido)} | Status: {record.status_pedido or '-'}",
        f"Produto: {_truncate_text(produto, 80)}",
        f"Qtd: {_format_quantity(record.quantidade)} {record.unid_venda} | Preco: {_format_currency_brl(record.preco_unitario)}",
        f"Problema: {problem_text}",
    ]


def _format_critica_item_line(record: CriticaRnRecord) -> str:
    produto = f"{record.produto_codigo} {record.produto_descricao or ''}".strip()
    status = "; ".join(record.problemas) if record.problemas else "OK"
    return (
        f"- {_truncate_text(produto, 54)} | "
        f"{_format_quantity(record.quantidade)} {record.unid_venda} | "
        f"{_format_currency_brl(record.preco_unitario)} | Total {_format_currency_brl(record.total_pedido)} | {status}"
    )


def _truncate_text(value: str, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _normalize_document(text: str) -> str:
    digits = "".join(char for char in str(text or "") if char.isdigit())
    if len(digits) not in {11, 14}:
        return ""
    return digits


def _normalize_phone_number(text: str) -> str:
    digits = "".join(char for char in str(text or "") if char.isdigit())
    if len(digits) in {10, 11} and not digits.startswith("55"):
        return f"55{digits}"
    return digits


def _normalize_admin_name(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _parse_admin_action(normalized_text: str) -> str:
    if normalized_text in {ADMIN_ACTION_CREATE, "1", "cadastrar", "cadastrar usuario", "novo usuario"}:
        return "create"
    if normalized_text in {ADMIN_ACTION_UPDATE, "2", "alterar", "alterar cargo", "alterar cargo/setor", "alterar cargo/acesso"}:
        return "update"
    if normalized_text in {ADMIN_ACTION_LIST, "3", "listar", "listar usuarios", "listar usuarios e cargos"}:
        return "list"
    if normalized_text in {ADMIN_ACTION_RENAME, "4", "alterar nome", "editar nome", "mudar nome"}:
        return "rename"
    if normalized_text in {ADMIN_ACTION_SUMMARY, "5", "resumo operacional", "resumo admin", "resumo administrativo"}:
        return "summary"
    if normalized_text in {ADMIN_ACTION_HEALTH, "6", "saude do sistema", "saude", "status do sistema"}:
        return "health"
    if normalized_text in {ADMIN_ACTION_CHECK, "7", "validar acesso", "checar acesso", "conferir acesso"}:
        return "check"
    return ""


def _looks_like_recolha_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if {"recolha", "recolhas"} & tokens:
        return True
    return normalized_text in {
        MENU_RECOLHA,
        "solicitacao recolha",
        "solicitacao de recolha",
        "solicitacoes recolha",
        "solicitacoes de recolha",
        "pedido recolha",
        "pedido de recolha",
        "pedidos recolha",
        "pedidos de recolha",
        "solicitar recolha",
        "pedir recolha",
    }


def _looks_like_recolha_list_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if normalized_text in {
        "recolhas",
        "ver recolhas",
        "listar recolhas",
        "solicitacoes de recolha",
        "pedidos de recolha",
    }:
        return True
    if "recolhas" in tokens and (
        re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)", normalized_text)
        or {"hoje", "ontem", "semana", "semanal", "mes", "mensal", "todas", "todos", "historico", "recolhida", "recolhidas", "recolhido", "lancada", "lancadas", "faturista"} & tokens
    ):
        return True
    return bool(
        {"recolha", "recolhas"} & tokens
        and {
            "ver",
            "listar",
            "solicitacoes",
            "pedidos",
            "aberta",
            "abertas",
            "pendente",
            "pendentes",
            "filial",
            "revenda",
            "setor",
            "rn",
            "resumo",
            "painel",
        }
        & tokens
    )


def _looks_like_recolha_update_request(normalized_text: str) -> bool:
    normalized = _normalize_choice(normalized_text)
    if normalized.startswith("recolhas "):
        return False
    return bool(re.match(r"^(?:recolha|faturista|caixa)\s+[a-z0-9_-]+\s+.+$", normalized))


def _parse_recolha_inline_request(text: str) -> tuple[str, str, str] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    normalized = _normalize_choice(raw)
    if not _looks_like_recolha_request(normalized):
        return None
    payload = _recolha_request_payload(raw)
    if not payload or _normalize_choice(payload) in {"recolha", "recolhas"}:
        return None

    parts = [_clean_recolha_text(part) for part in re.split(r"\s*[|;]\s*", payload)]
    parts = [part for part in parts if part]
    if len(parts) >= 2:
        return parts[0], parts[1], " | ".join(parts[2:])

    match = re.match(
        r"^\s*((?:(?:filial|revenda)\s*)?\d{1,4}\D+(?:(?:nb|cod(?:igo)?(?:\s+pdv)?)\D*)?\d{2,}|(?:(?:nb|cod(?:igo)?(?:\s+pdv)?)\D*)?\d{2,})(?:\s+(.+))?$",
        payload,
        flags=re.I,
    )
    if not match:
        return _clean_recolha_text(payload), "", ""
    client_ref = _clean_recolha_text(match.group(1))
    comodato, obs = _split_recolha_inline_comodato_and_obs(match.group(2) or "")
    return client_ref, comodato, obs


def _recolha_request_payload(text: str) -> str:
    return re.sub(
        r"^(?:quero\s+)?(?:(?:solicitar|pedir|abrir)\s+)?(?:(?:pedido|solicitacao)\s+de\s+)?recolhas?\b[:\s-]*",
        "",
        str(text or "").strip(),
        flags=re.I,
    ).strip()


def _clean_recolha_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _split_recolha_inline_comodato_and_obs(text: str) -> tuple[str, str]:
    cleaned = _clean_recolha_text(text)
    if not cleaned:
        return "", ""
    normalized = _normalize_choice(cleaned)
    if normalized.startswith("recolha total "):
        return "recolha total", cleaned[len("recolha total ") :].strip()
    first_token_match = re.match(r"^(todos|tudo|total)\b(?:\s+(.+))?$", normalized)
    if first_token_match:
        return first_token_match.group(1), _clean_recolha_text(cleaned[len(first_token_match.group(1)) :])
    numeric_selection = re.match(r"^(\d+(?:\s*(?:,|/|;|\+| e |\s)\s*\d+)*)(?:\s+(.+))?$", normalized)
    if numeric_selection:
        selection = numeric_selection.group(1)
        obs = cleaned[len(numeric_selection.group(1)) :].strip()
        return selection, obs
    return cleaned, ""


def _select_recolha_client_option(text: str, *, options: tuple[DClienteRecord, ...]) -> DClienteRecord | None:
    if not options:
        return None
    normalized = _normalize_choice(text)
    if not re.fullmatch(r"\d+", normalized):
        return None
    index = int(normalized)
    if index < 1 or index > len(options):
        return None
    return options[index - 1]


def _resolve_recolha_comodato_selection(*, session: LookupSession, text: str) -> str:
    cleaned = _clean_recolha_text(text)
    if not cleaned:
        return ""
    records = list(session.recolha_comodato_options or ())
    if not records:
        return cleaned

    normalized = _normalize_choice(cleaned)
    if normalized in {"todos", "tudo", "total", "recolha total", "todos os comodatos", "recolher todos"}:
        return _format_recolha_comodato_selection(records)

    if _looks_like_recolha_numeric_selection(normalized):
        selected_records: list[ComodatoRecord] = []
        seen_indexes: set[int] = set()
        for raw_index in re.findall(r"\d+", normalized):
            index = int(raw_index)
            if index < 1 or index > len(records):
                return ""
            if index in seen_indexes:
                continue
            seen_indexes.add(index)
            selected_records.append(records[index - 1])
        return _format_recolha_comodato_selection(selected_records)

    return cleaned


def _looks_like_recolha_numeric_selection(normalized_text: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\s*(?:,|/|;|\+| e |\s)\s*\d+)*", str(normalized_text or "").strip()))


def _format_recolha_comodato_selection(records: list[ComodatoRecord]) -> str:
    formatted = [_format_recolha_comodato_option(record) for record in records]
    return " | ".join(formatted)


def _format_recolha_comodato_option(record: ComodatoRecord) -> str:
    parts = []
    if str(record.nro_comodato or "").strip():
        parts.append(f"Comodato {record.nro_comodato}")
    material = str(record.material or "").strip()
    sub_tipo = str(record.sub_tipo_material or "").strip()
    if material and sub_tipo and _normalize_choice(material) != _normalize_choice(sub_tipo):
        parts.append(f"{material} - {sub_tipo}")
    elif material:
        parts.append(material)
    elif sub_tipo:
        parts.append(sub_tipo)
    saldo = str(record.saldo or "").strip()
    if saldo:
        parts.append(f"Saldo {saldo}")
    return " | ".join(parts) or "Comodato sem detalhe"


def _resolve_recolha_registration_input(
    client_ref: str,
    *,
    decision: AccessDecision,
) -> tuple[str, str]:
    direct = _parse_direct_registration_lookup(client_ref)
    if direct:
        return direct

    normalized = _normalize_choice(client_ref)
    cod_pdv_match = re.search(r"(?:nb|cod(?:igo)?(?: pdv)?)\D*(\d{2,})\b", normalized)
    if cod_pdv_match:
        cod_pdv = _normalize_cod_pdv(cod_pdv_match.group(1))
    else:
        digits = re.findall(r"\d+", normalized)
        cod_pdv = _normalize_cod_pdv(digits[0]) if len(digits) == 1 else ""
    if not cod_pdv:
        return "", ""

    filial = _single_filial_from_decision(decision)
    return filial, cod_pdv


def _single_filial_from_decision(decision: AccessDecision) -> str:
    filiais: list[str] = []
    seen: set[str] = set()
    for scope_value in tuple(decision.sectors or ()) + tuple(decision.gv_vdes or ()):
        pair = split_scope_pair(normalize_stored_scope_value(scope_value))
        if not pair or not pair[0]:
            continue
        filial = _normalize_filial(pair[0])
        if filial and filial not in seen:
            seen.add(filial)
            filiais.append(filial)
    return filiais[0] if len(filiais) == 1 else ""


def _parse_recolha_finance_update_request(
    *,
    text: str,
    normalized: str,
) -> tuple[str, dict[str, str]] | None:
    if normalized.startswith("recolhas "):
        return None
    match = re.match(r"^(?:recolha|faturista|caixa)\s+([a-z0-9_-]+)\s+(.+)$", normalized)
    if not match:
        return None
    identifier = match.group(1).strip()
    action = match.group(2).strip()
    updates: dict[str, str] = {}

    if "nao lancado" in action or "nao lançado" in action:
        updates["lancado_faturista"] = "Nok"
    elif "lancado" in action or "lançado" in action:
        updates["lancado_faturista"] = "Ok"

    if "nao recolhido" in action or "não recolhido" in action:
        updates["status_caixa_noturno"] = "Não Recolhido"
        motivo = _extract_recolha_label_value(text, "motivo")
        if motivo:
            updates["motivo_caixa_noturno"] = motivo
    elif "recolhido" in action:
        updates["status_caixa_noturno"] = "Recolhido"
        updates["motivo_caixa_noturno"] = ""

    motorista = _extract_recolha_label_value(text, "motorista", stop_labels=("placa", "mapa", "motivo"))
    placa = _extract_recolha_label_value(text, "placa", stop_labels=("motorista", "mapa", "motivo"))
    mapa = _extract_recolha_label_value(text, "mapa", stop_labels=("motorista", "placa", "motivo"))
    if motorista:
        updates["motorista_faturista"] = motorista
    if placa:
        updates["placa_faturista"] = placa
    if mapa:
        updates["mapa_faturista"] = mapa

    if not updates:
        return None
    return identifier, updates


def _parse_recolha_management_request(normalized: str) -> tuple[str, str] | None:
    normalized_text = _normalize_choice(normalized)
    if normalized_text in {
        "limpar recolhas",
        "recolhas limpar",
        "zerar recolhas",
        "apagar recolhas",
        "excluir recolhas",
    }:
        return "clear", ""
    match = re.match(
        r"^(?:remover|apagar|excluir|deletar|cancelar)\s+recolha\s+([a-z0-9_-]+)$",
        normalized_text,
    )
    if match:
        return "delete", match.group(1)
    match = re.match(
        r"^recolha\s+([a-z0-9_-]+)\s+(?:remover|apagar|excluir|deletar|cancelar)$",
        normalized_text,
    )
    if match:
        return "delete", match.group(1)
    match = re.match(r"^cancelar\s+([a-z0-9_-]+)$", normalized_text)
    if match:
        return "delete", match.group(1)
    return None


def _recolha_record_matches_identifier(record: RecolhaRequestRecord, identifier: str) -> bool:
    normalized_identifier = str(identifier or "").strip().lower()
    if not normalized_identifier:
        return False
    pair = split_scope_pair(normalized_identifier)
    if pair:
        return _recolha_record_filial_code(record) == _normalize_filial(pair[0]) and _normalize_cod_pdv(record.nb) == _normalize_cod_pdv(pair[1])
    normalized_id = str(record.id or "").strip().lower()
    normalized_nb = str(record.nb or "").strip().lower()
    if normalized_id:
        if normalized_id == normalized_identifier:
            return True
        if "-" not in normalized_id and normalized_id.startswith(normalized_identifier):
            return True
    return bool(
        normalized_nb and normalized_nb == normalized_identifier
    )


def _extract_recolha_label_value(
    text: str,
    label: str,
    *,
    stop_labels: tuple[str, ...] = (),
) -> str:
    raw = str(text or "").strip()
    normalized = _normalize_choice(raw)
    label_match = re.search(rf"\b{re.escape(label)}\b", normalized)
    if not label_match:
        return ""
    start = label_match.end()
    end = len(normalized)
    for stop_label in stop_labels:
        stop_match = re.search(rf"\b{re.escape(stop_label)}\b", normalized[start:])
        if stop_match:
            end = min(end, start + stop_match.start())
    return _clean_recolha_text(raw[start:end])


@dataclass(frozen=True)
class RecolhaRequestFilters:
    date_start: date | None = None
    date_end: date | None = None
    period_label: str = "Todo o historico"
    explicit_period: bool = False
    status_mode: str = ""
    status_label: str = "Todos os status"
    explicit_status: bool = False
    invalid_reason: str = ""


def _recolha_allowed_filiais_from_decision(decision: AccessDecision) -> set[str]:
    filiais: set[str] = set()
    if not decision:
        return filiais
    for value in tuple(decision.sectors or ()) + tuple(decision.gv_vdes or ()):
        raw = str(value or "").strip()
        normalized_filial_scope = normalize_filial_scope_input(raw)
        if normalized_filial_scope.startswith("filial:"):
            code = _normalize_filial(normalized_filial_scope[len("filial:") :])
            if code:
                filiais.add(code)
            continue
        pair = split_scope_pair(normalize_stored_scope_value(raw))
        if pair and pair[0]:
            filiais.add(_normalize_filial(pair[0]))
            continue
        code = _normalize_filial(raw)
        if code:
            filiais.add(code)
    return filiais


def _recolha_record_filial_code(record: RecolhaRequestRecord) -> str:
    raw = str(record.revenda or "").strip()
    direct = _normalize_filial(raw)
    if direct:
        return direct
    normalized_raw = _normalize_choice(raw)
    for filial, label in FILIAL_LABELS.items():
        if normalized_raw == _normalize_choice(label):
            return filial
    return ""


def _parse_recolha_record_date(record: RecolhaRequestRecord) -> date | None:
    for value in (record.criado_em, record.data):
        text = str(value or "").strip()
        if not text:
            continue
        match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)", text)
        if not match:
            continue
        parsed = _parse_payip_statement_date_token(match.group(1))
        if parsed is not None:
            return parsed
    return None


def _parse_recolha_request_filters(request_text: str, *, default_open: bool = False) -> RecolhaRequestFilters:
    raw = str(request_text or "").strip()
    normalized = _normalize_choice(raw)
    tokens = _normalized_tokens(normalized)
    today = datetime.now(LOCAL_TIMEZONE).date()

    date_matches = list(
        re.finditer(
            r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
            raw,
        )
    )
    parsed_dates = [_parse_payip_statement_date_token(match.group(1)) for match in date_matches]
    valid_dates = [item for item in parsed_dates if item is not None]
    if any(item is None for item in parsed_dates) or len(valid_dates) > 2:
        return RecolhaRequestFilters(invalid_reason="Data invalida. Use hoje, ontem, semana, mes ou dd/mm/aaaa.")

    date_start: date | None = None
    date_end: date | None = None
    period_label = "Todo o historico"
    explicit_period = False
    if len(valid_dates) == 2:
        date_start, date_end = valid_dates
        explicit_period = True
        period_label = f"{date_start.strftime('%d/%m/%Y')} ate {date_end.strftime('%d/%m/%Y')}"
    elif len(valid_dates) == 1:
        date_start = date_end = valid_dates[0]
        explicit_period = True
        period_label = date_start.strftime("%d/%m/%Y")
    elif "hoje" in tokens:
        date_start = date_end = today
        explicit_period = True
        period_label = "Hoje"
    elif "ontem" in tokens:
        date_start = date_end = today - timedelta(days=1)
        explicit_period = True
        period_label = "Ontem"
    elif "semana" in tokens or "semanal" in tokens:
        date_start = today - timedelta(days=6)
        date_end = today
        explicit_period = True
        period_label = "Ultimos 7 dias"
    elif "mes" in tokens or "mensal" in tokens:
        date_start = today.replace(day=1)
        date_end = today
        explicit_period = True
        period_label = "Mes atual"
    elif {"todas", "todos", "historico", "histórico"} & tokens:
        explicit_period = True
        period_label = "Todo o historico"

    if date_start and date_end and date_start > date_end:
        return RecolhaRequestFilters(invalid_reason="Periodo invalido. A data inicial nao pode ser maior que a final.")

    status_mode = ""
    status_label = "Todos os status"
    explicit_status = False
    if {"aberta", "abertas", "pendente", "pendentes"} & tokens:
        status_mode = "abertas"
        status_label = "Pendentes/abertas"
        explicit_status = True
    elif "lancada" in tokens or "lancadas" in tokens or "faturista" in tokens:
        status_mode = "lancadas"
        status_label = "Lancadas pelo faturista"
        explicit_status = True
    elif ("nao" in tokens or "não" in tokens) and ("recolhida" in tokens or "recolhidas" in tokens or "recolhido" in tokens):
        status_mode = "nao_recolhidas"
        status_label = "Nao recolhidas"
        explicit_status = True
    elif "recolhida" in tokens or "recolhidas" in tokens or "recolhido" in tokens:
        status_mode = "recolhidas"
        status_label = "Recolhidas"
        explicit_status = True
    elif default_open:
        status_mode = "abertas"
        status_label = "Pendentes/abertas"

    return RecolhaRequestFilters(
        date_start=date_start,
        date_end=date_end,
        period_label=period_label,
        explicit_period=explicit_period,
        status_mode=status_mode,
        status_label=status_label,
        explicit_status=explicit_status,
    )


def _filter_recolha_records_for_request(
    records: list[RecolhaRequestRecord],
    request_text: str,
    *,
    default_open: bool = False,
) -> list[RecolhaRequestRecord]:
    normalized = _normalize_choice(request_text)
    tokens = _normalized_tokens(normalized)
    filtered = list(records)

    filters = _parse_recolha_request_filters(request_text, default_open=default_open)
    if filters.invalid_reason:
        return []

    if filters.date_start and filters.date_end:
        filtered = [
            record
            for record in filtered
            if (record_date := _parse_recolha_record_date(record)) is not None
            and filters.date_start <= record_date <= filters.date_end
        ]

    if filters.status_mode == "abertas":
        filtered = [record for record in filtered if _normalize_choice(record.status_caixa_noturno) != "recolhido"]
    elif filters.status_mode == "recolhidas":
        filtered = [record for record in filtered if _normalize_choice(record.status_caixa_noturno) == "recolhido"]
    elif filters.status_mode == "nao_recolhidas":
        filtered = [record for record in filtered if _normalize_choice(record.status_caixa_noturno) != "recolhido"]
    elif filters.status_mode == "lancadas":
        filtered = [record for record in filtered if _normalize_choice(record.lancado_faturista) == "ok"]

    filial_match = re.search(r"\b(?:filial|revenda)\D*(\d+)\b", normalized)
    if filial_match:
        filial = _normalize_filial(filial_match.group(1))
        filtered = [record for record in filtered if _recolha_record_filial_code(record) == filial]

    setor_match = re.search(r"\b(?:setor|rn)\D*(\d+)\b", normalized)
    if setor_match:
        setor = _normalize_cod_pdv(setor_match.group(1))
        filtered = [
            record
            for record in filtered
            if _normalize_cod_pdv(record.setor) == setor or _normalize_cod_pdv(record.rn) == setor
        ]

    return filtered


def _recolha_request_is_summary(request_text: str) -> bool:
    tokens = _normalized_tokens(_normalize_choice(request_text))
    return bool({"resumo", "painel"} & tokens)


def _summarize_recolha_records(records: list[RecolhaRequestRecord]) -> dict[str, Any]:
    por_filial: dict[str, int] = {}
    por_setor: dict[str, int] = {}
    abertas = 0
    lancadas = 0
    recolhidas = 0
    nao_recolhidas = 0
    for record in records:
        status = _normalize_choice(record.status_caixa_noturno)
        lancado = _normalize_choice(record.lancado_faturista)
        if status == "recolhido":
            recolhidas += 1
        else:
            abertas += 1
            nao_recolhidas += 1
        if lancado == "ok":
            lancadas += 1
        filial = record.revenda or "-"
        setor = record.setor or record.rn or "-"
        por_filial[filial] = por_filial.get(filial, 0) + 1
        por_setor[setor] = por_setor.get(setor, 0) + 1
    return {
        "abertas": abertas,
        "lancadas": lancadas,
        "recolhidas": recolhidas,
        "nao_recolhidas": nao_recolhidas,
        "por_filial": sorted(por_filial.items(), key=lambda item: _sort_scope_code(item[0])),
        "por_setor": sorted(por_setor.items(), key=lambda item: _sort_scope_code(item[0])),
    }


def _parse_finance_action(normalized_text: str) -> str:
    normalized_tokens = _normalized_tokens(normalized_text)
    if _normalize_document(normalized_text) and {"cpf", "cnpj", "documento"} & normalized_tokens:
        return "prazo_limite"
    numeric_choice_match = re.match(r"^0*(10|[1-9])(?:[^0-9].*)?$", normalized_text)
    if numeric_choice_match:
        return {
            "1": "summary",
            "2": "list",
            "3": "top",
            "4": "upcoming",
            "5": "visit_risk",
            "6": "gv_summary",
            "7": "giro",
            "8": "prazo_limite",
            "9": "payip",
            "10": "recolhas",
        }[numeric_choice_match.group(1)]
    if normalized_text in {
        FINANCE_ACTION_SUMMARY,
        "1",
        "resumo financeiro",
        "resumo",
        "resumo por gv",
        "resumo por filial",
        "resumo por setor",
        "resumo organizado",
    }:
        return "summary"
    if normalized_text in {
        FINANCE_ACTION_LIST,
        "2",
        "ver inadimplentes",
        "inadimplentes",
        "cobranca",
        "cobrancas",
        "cobranca da base",
    }:
        return "list"
    if normalized_text in {FINANCE_ACTION_TOP, "3", "maiores devedores", "maiores valores"}:
        return "top"
    if normalized_text in {FINANCE_ACTION_UPCOMING, "4", "vencimentos proximos", "vencimentos próximos"}:
        return "upcoming"
    if normalized_text in {
        FINANCE_ACTION_VISIT_RISK,
        "5",
        "risco da rota",
        "risco da rota de hoje",
        "visita com risco",
        "visita com riscos",
        "visitas com risco",
        "visitas com riscos",
        "visitas do dia com risco",
        "visitas do dia com riscos",
        "risco financeiro das visitas",
        "risco nas visitas",
    }:
        return "visit_risk"
    if normalized_text in {
        FINANCE_ACTION_GV_SUMMARY,
        "6",
        "escolher gv",
    }:
        return "gv_summary"
    if normalized_text in {
        FINANCE_ACTION_GIRO,
        "7",
        "giro",
        "submenu giro",
        "resumo de giro",
    }:
        return "giro"
    if normalized_text in {
        FINANCE_ACTION_PRAZO_LIMITE,
        "8",
        "prazo e limite",
        "prazo limite",
        "limite e prazo",
        "liberacao de prazo e limite",
        "liberacao prazo e limite",
        "validacao de prazo e limite",
        "consulta de prazo e limite",
    }:
        return "prazo_limite"
    if normalized_text in {
        FINANCE_ACTION_RECOLHAS,
        "10",
        "recolhas",
        "recolha",
        "solicitacoes de recolha",
        "solicitacao de recolha",
        "pedidos de recolha",
        "pedido de recolha",
    }:
        return "recolhas"
    if _looks_like_recolha_list_request(normalized_text):
        return "recolhas"
    if re.match(r"^(analise|analisar)\b", normalized_text):
        return "prazo_limite"
    if normalized_text.startswith(("5", "05", "o5")) and (
        {"visita", "visitas"} & normalized_tokens or {"risco", "riscos"} & normalized_tokens
    ):
        return "visit_risk"
    if {"visita", "visitas"} & normalized_tokens and {"risco", "riscos"} & normalized_tokens:
        return "visit_risk"
    if {"risco", "riscos"} & normalized_tokens and (
        {"rota", "rotas"} & normalized_tokens or bool(_extract_requested_visit_day_label(normalized_text))
    ):
        return "visit_risk"
    if {"vencimento", "vencimentos", "vencido", "vencidos", "atrasado", "atrasados", "vence"} & normalized_tokens:
        return "upcoming"
    if {"maiores"} & normalized_tokens and {"devedor", "devedores"} & normalized_tokens:
        return "top"
    if {"inadimplente", "inadimplentes", "cobranca", "cobrancas"} & normalized_tokens:
        return "list"
    if {"resumo", "painel"} & normalized_tokens and {"financeiro"} & normalized_tokens:
        return "summary"
    if {"prazo", "limite"} <= normalized_tokens or ({"prazo", "limite"} & normalized_tokens and {"liberacao", "validacao"} & normalized_tokens):
        return "prazo_limite"
    if {"extrato", "movimentacao", "movimentacoes", "movimentos"} & normalized_tokens:
        return "payip"
    if normalized_text in {
        FINANCE_ACTION_PAYIP,
        "9",
        "payip",
        "pagamentos payip",
        "pagamento payip",
        "login payip",
        "teste payip",
        "testar payip",
        "testar login payip",
    }:
        return "payip"
    if "payip" in normalized_tokens:
        return "payip"
    return ""


def _parse_payip_action(normalized_text: str) -> str:
    if re.match(r"^(?:rotas?|mapas?)\b", normalized_text):
        return "routes"
    if normalized_text in {
        PAYIP_ACTION_ROUTES,
        "11",
        "rotas",
        "rota payip",
        "rotas payip",
        "mapas",
        "mapas em progresso",
        "rotas em progresso",
    }:
        return "routes"
    if re.search(r"\b(?:importar|importacao|importar cobrancas|validar importacao|automatizada)\b", normalized_text) and re.search(
        r"(?<!\d)(?:\d{8}|\d{6}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
        normalized_text,
    ):
        return "import_batch"
    if normalized_text in {
        PAYIP_ACTION_IMPORT_BATCH,
        "9",
        "importar cobrancas",
        "importar cobranca",
        "importacao automatizada",
        "importacao de cobrancas",
        "importacao cobrancas",
        "validar importacao",
        "validar importacao automatizada",
        "cobranca automatizada",
        "cobrancas automatizadas",
    }:
        return "import_batch"
    if re.search(r"\b(?:validar|conferir)\b", normalized_text) and re.search(
        r"(?<!\d)(?:\d{8}|\d{6}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
        normalized_text,
    ):
        return "validate_day"
    if normalized_text in {
        PAYIP_ACTION_VALIDATE_DAY,
        "8",
        "validar",
        "validar data",
        "validar payip",
        "validar cobrancas",
        "validar cobranca",
        "conferir data",
        "conferir cobrancas",
        "conferir cobranca",
        "cobrancas por data",
        "cobranca por data",
    }:
        return "validate_day"
    if normalized_text in {
        PAYIP_ACTION_STATEMENT,
        "6",
        "extrato",
        "extrato payip",
        "consultar extrato",
        "consulta extrato",
        "resumo extrato",
        "movimentacoes",
        "movimentacoes payip",
        "movimentos",
        "movimentos payip",
    }:
        return "statement"
    if normalized_text in {
        PAYIP_ACTION_AMOUNT_DAY,
        "7",
        "valor e dia",
        "valor por dia",
        "buscar valor dia",
        "buscar valor por dia",
        "buscar por valor e dia",
        "cobrancas por valor",
        "cobranca por valor",
        "cobrancas por valor e dia",
        "cobranca por valor e dia",
    }:
        return "amount_day"
    if normalized_text in {
        PAYIP_ACTION_CREATE_CLIENT,
        "10",
        "criar cliente payip",
        "cadastrar cliente payip",
        "cadastro cliente payip",
        "incluir cliente payip",
    }:
        return "create_client"
    if normalized_text in {
        PAYIP_ACTION_CREATE_CHARGE,
        "5",
        "emitir cobranca",
        "emitir cobrança",
        "criar cobranca",
        "criar cobrança",
        "nova cobranca",
        "nova cobrança",
        "gerar cobranca",
        "gerar cobrança",
        "cobranca nova",
        "cobrança nova",
    }:
        return "create_charge"
    if normalized_text in {
        PAYIP_ACTION_STATUS,
        "4",
        "diagnostico",
        "diagnostico payip",
        "status",
        "status da sessao",
        "sessao",
        "tokens",
        "cache",
    }:
        return "status"
    if normalized_text in {
        PAYIP_ACTION_TEST_LOGIN,
        "testar login",
        "login",
        "teste login",
        "testar",
        "pagamentos",
        "consultar pagamentos",
        "listar pagamentos",
    }:
        return "test_login"
    if normalized_text in {
        PAYIP_ACTION_SEARCH_INVOICE,
        "1",
        "buscar nota fiscal",
        "nota fiscal",
        "nf",
        "nfe",
        "invoice",
    }:
        return "invoice"
    if normalized_text in {
        PAYIP_ACTION_PENDING_CLIENT,
        "pendentes por nb",
        "pendente por nb",
        "nb pendente",
        "cliente pendente",
        "client code",
        "clientcode",
        "codigo do cliente",
        "codigo cliente",
    }:
        return "pending_client"
    if normalized_text in {
        PAYIP_ACTION_CLIENT,
        "2",
        "todos por nb",
        "buscar por nb",
        "nb",
        "pagamentos por nb",
        "buscar por nb",
        "consultar por nb",
        "cliente",
        "client code todos",
        "codigo do cliente todos",
    }:
        return "client"
    if normalized_text in {
        "3",
        "pix",
        "pix da ultima consulta",
        "ultimo pix",
        "copiar pix",
        "copia e cola",
    }:
        return "pix"
    tokens = _normalized_tokens(normalized_text)
    if {"nf", "nfe", "nota", "fiscal", "invoice"} & tokens:
        return "invoice"
    if {"nb", "cliente", "client", "clientcode", "codigo", "cod", "pdv"} & tokens and (
        {"pendente", "pendentes", "pending"} & tokens
    ):
        return "pending_client"
    if {"nb", "cliente", "client", "clientcode", "codigo", "cod", "pdv"} & tokens and (
        {"todos", "todo", "buscar", "consultar"} & tokens
    ):
        return "client"
    if "valor" in tokens and (
        {"dia", "pagamento", "pagamentos", "pago", "pagos", "paga", "pagas", "cobranca", "cobrancas"} & tokens
    ):
        return "amount_day"
    if {"rota", "rotas", "mapa", "mapas"} & tokens:
        return "routes"
    if {"validar", "conferir"} & tokens and {"data", "dia", "cobranca", "cobrancas", "payip"} & tokens:
        return "validate_day"
    if {"importar", "importacao", "automatizada"} & tokens and {"cobranca", "cobrancas", "payip"} & tokens:
        return "import_batch"
    if {"emitir", "criar", "gerar", "nova", "novo"} & tokens and {"cobranca", "cobrancas"} & tokens:
        return "create_charge"
    if {"criar", "cadastrar", "cadastro", "incluir"} & tokens and {"cliente", "payip"} <= tokens:
        return "create_client"
    if {"extrato", "movimentacao", "movimentacoes", "movimentos"} & tokens:
        return "statement"
    if {"status", "sessao", "cache", "token", "tokens"} & tokens:
        return "status"
    if {"login", "teste", "testar", "pagamentos", "pagamento"} & tokens:
        return "test_login"
    return ""


def _parse_finance_due_bucket(normalized_text: str) -> str:
    normalized_tokens = _normalized_tokens(normalized_text)
    if normalized_text in {FINANCE_DUE_IN_TWO_DAYS, "1", "vence em 2 dias", "2 dias"}:
        return "in_two_days"
    if normalized_text in {FINANCE_DUE_TOMORROW, "2", "vence amanha", "amanha"}:
        return "tomorrow"
    if normalized_text in {FINANCE_DUE_TODAY, "3", "vence hoje", "hoje"}:
        return "today"
    if normalized_text in {FINANCE_DUE_OVERDUE, "4", "ja vencidos", "já vencidos", "vencidos", "inadimplentes"}:
        return "overdue"
    if "hoje" in normalized_tokens:
        return "today"
    if "amanha" in normalized_tokens:
        return "tomorrow"
    if {"vencido", "vencidos", "atrasado", "atrasados"} & normalized_tokens:
        return "overdue"
    if {"2", "dois"} & normalized_tokens and "dias" in normalized_tokens:
        return "in_two_days"
    return ""


def _parse_finance_summary_mode(normalized_text: str) -> str:
    if normalized_text in {FINANCE_SUMMARY_TOTAL, "1", "total", "resumo total", "base total"}:
        return "total"
    if normalized_text in {
        FINANCE_SUMMARY_BY_FILIAL,
        "2",
        "por filial",
        "por revenda",
        "filial",
        "revenda",
        "revendas",
    }:
        return "by_filial"
    if normalized_text in {
        FINANCE_SUMMARY_BY_GV,
        "3",
        "por gv",
        "gv",
        "gerente",
        "gerencia",
    }:
        return "by_gv"
    if normalized_text in {
        FINANCE_SUMMARY_BY_SELLER,
        "4",
        "por setor",
        "setor",
        "setores",
    }:
        return "by_seller"
    if normalized_text in {
        FINANCE_SUMMARY_DOCUMENTACAO_BY_FILIAL,
        "5",
        "documentacao por filial",
        "documentacao por revenda",
        "doc escaneada",
        "documentacao escaneada",
        "resumo documentacao",
    }:
        return "documentacao_by_filial"
    normalized_tokens = _normalized_tokens(normalized_text)
    if {"documentacao", "documentos", "escaneada", "escaneado"} & normalized_tokens and {"filial", "revenda", "revendas", "filiais"} & normalized_tokens:
        return "documentacao_by_filial"
    return ""


def _parse_director_summary_action(normalized_text: str) -> str:
    normalized_tokens = _normalized_tokens(normalized_text)
    if normalized_text in {
        "1",
        DIRECTOR_ACTION_VISIT_RISK,
        "risco da rota",
        "visitas com risco",
        "risco das visitas",
        "visitas com risco por gerente",
    }:
        return "visit_risk"
    if normalized_text in {
        "2",
        DIRECTOR_ACTION_TOP_DEBTORS,
        "cobranca",
        "maiores devedores",
        "devedores",
        "top devedores",
        "titulos em aberto",
    }:
        return "top_debtors"
    if normalized_text in {
        DIRECTOR_SUMMARY_BY_REVENDA,
        "3",
        "por gv",
        "gvs",
        "gerentes",
        "por gerente",
        "escolher gv",
    }:
        return "by_revenda"
    if normalized_text in {
        "4",
        DIRECTOR_ACTION_BY_FILIAL,
        "resumo por filial",
        "por filial",
        "filial",
        "filiais",
        "por revenda",
        "revendas",
    }:
        return "by_filial"
    if normalized_text in {
        "5",
        DIRECTOR_ACTION_GIRO,
        "giro",
        "submenu giro",
        "giro da diretoria",
    }:
        return "giro"
    if normalized_text in {
        "6",
        DIRECTOR_ACTION_RANKING,
        "ranking dos gerentes",
        "ranking",
        "ranking dos gvs",
        "ranking da diretoria",
    }:
        return "ranking"
    if normalized_text in {
        "7",
        DIRECTOR_SUMMARY_TOTAL,
        "resumo total",
        "total",
        "resumo da diretoria",
        "diretoria",
        "resumo geral",
    }:
        return "total"
    if {"visita", "visitas"} & normalized_tokens and {"risco", "riscos"} & normalized_tokens:
        return "visit_risk"
    if {"gv", "gvs", "gerente", "gerentes"} & normalized_tokens:
        return "by_revenda"
    if {"filial", "filiais", "revenda", "revendas"} & normalized_tokens:
        return "by_filial"
    if {"cobranca"} & normalized_tokens:
        return "top_debtors"
    if {"giro"} & normalized_tokens:
        return "giro"
    if {"ranking"} & normalized_tokens:
        return "ranking"
    if {"maiores"} & normalized_tokens and {"devedor", "devedores"} & normalized_tokens:
        return "top_debtors"
    if {"resumo"} & normalized_tokens and {"diretoria", "total"} & normalized_tokens:
        return "total"
    return ""


def _parse_manager_summary_action(normalized_text: str) -> str:
    normalized_tokens = _normalized_tokens(normalized_text)
    if normalized_text in {
        MANAGER_ACTION_VISIT_RISK,
        "1",
        "risco da rota",
        "visitas com risco",
        "risco das visitas",
        "visitas com risco da gerencia",
    }:
        return "visit_risk"
    if normalized_text in {
        MANAGER_ACTION_UPCOMING,
        "2",
        "vencimentos",
        "vencimentos proximos",
        "proximos vencimentos",
    }:
        return "upcoming"
    if normalized_text in {
        MANAGER_ACTION_LIST,
        "3",
        "cobranca",
        "cobranca consolidada",
        "cobranca da gerencia",
        "inadimplentes",
        "inadimplentes da gerencia",
        "clientes inadimplentes",
    }:
        return "list"
    if normalized_text in {
        MANAGER_ACTION_BY_SELLER,
        "4",
        "equipe",
        "por vendedor",
        "resumo por vendedor",
        "vendedor",
    }:
        return "by_seller"
    if normalized_text in {
        MANAGER_SUMMARY_BY_FILIAL,
        "5",
        "filiais",
        "por filial",
        "ver por filial",
        "escolher filial",
        "por revenda",
    }:
        return "by_filial"
    if normalized_text in {
        MANAGER_ACTION_GIRO,
        "6",
        "giro",
        "submenu giro",
        "giro consolidado",
        "giro da gerencia",
    }:
        return "giro"
    if normalized_text in {
        MANAGER_SUMMARY_TOTAL,
        "7",
        "resumo total",
        "total",
        "resumo da gerencia",
        "resumo do gv",
    }:
        return "total"
    if {"visita", "visitas"} & normalized_tokens and {"risco", "riscos"} & normalized_tokens:
        return "visit_risk"
    if {"vencimento", "vencimentos", "vence"} & normalized_tokens:
        return "upcoming"
    if {"inadimplente", "inadimplentes", "cobranca", "cobrancas"} & normalized_tokens:
        return "list"
    if {"vendedor", "vendedores", "equipe"} & normalized_tokens:
        return "by_seller"
    if {"filial", "filiais", "revenda", "revendas"} & normalized_tokens:
        return "by_filial"
    if {"giro"} & normalized_tokens:
        return "giro"
    if {"resumo"} & normalized_tokens and {"gerencia", "gv", "total"} & normalized_tokens:
        return "total"
    return ""


def _parse_giro_mode(normalized_text: str) -> str:
    normalized_tokens = _normalized_tokens(normalized_text)
    if normalized_text in {GIRO_MODE_TOTAL, "1", "total", "resumo total", "consolidado"}:
        return "total"
    if normalized_text in {GIRO_MODE_BY_FILIAL, "2", "por filial", "filial", "revenda"}:
        return "by_filial"
    if normalized_text in {GIRO_MODE_BY_GV, "3", "por gv", "gv", "gerente"}:
        return "by_gv"
    if {"filial", "revenda"} & normalized_tokens:
        return "by_filial"
    if {"gv", "gerente"} & normalized_tokens:
        return "by_gv"
    if {"total", "consolidado", "geral"} & normalized_tokens:
        return "total"
    return ""


def _is_back_menu_command(normalized_text: str) -> bool:
    return normalized_text in MENU_BACK_COMMANDS


def _is_prev_page_command(normalized_text: str) -> bool:
    return normalized_text in {
        INADIMPLENCIA_PAGE_PREV,
        "anterior",
        "pagina anterior",
        "pag anterior",
    }


def _is_next_page_command(normalized_text: str) -> bool:
    return normalized_text in {
        INADIMPLENCIA_PAGE_NEXT,
        *PAGE_NEXT_COMMANDS,
        "proxima pagina",
        "proxima",
        "proximo",
        "proxima pagina de clientes",
        "pagina seguinte",
    }


def _uses_inadimplencia_page_navigation(session: LookupSession) -> bool:
    return (
        session.step == "awaiting_inadimplencia_client_selection"
        and session.inadimplencia_list_context in {
            INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL,
            INADIMPLENCIA_CONTEXT_SCOPE_BASE,
        }
        and session.inadimplencia_total_available > session.inadimplencia_page_size
    )


def _inadimplencia_page_shortcuts(page_size: int) -> tuple[str, str]:
    _ = page_size
    return "PROX", "ANTERIOR"


def _inadimplencia_page_shortcuts_label(
    page_size: int,
    page: int | None,
    total_available: int | None,
) -> str:
    if page is None or not total_available or total_available <= page_size:
        return ""

    total_pages = _compute_page_count(total_items=total_available, page_size=page_size)
    current_page = min(max(page, 1), total_pages)
    labels: list[str] = []
    if current_page > 1:
        labels.append("ANTERIOR para a pagina anterior")
    if current_page < total_pages:
        labels.append("PROX, PROXIMA ou PRXX para a proxima pagina")
    return " e ".join(labels)


def _parse_inadimplencia_page_action(normalized_text: str, page_size: int | None = None) -> str:
    _ = page_size
    if _is_prev_page_command(normalized_text):
        return "prev"
    if _is_next_page_command(normalized_text):
        return "next"
    return ""


def _parse_admin_role(normalized_text: str) -> str:
    if normalized_text in {ADMIN_ROLE_VENDEDOR, "1", "vendedor"}:
        return ROLE_VENDEDOR
    if normalized_text in {
        ADMIN_ROLE_GERENTE_VENDAS,
        ADMIN_ROLE_GESTOR,
        "2",
        "gestor",
        "gerente",
        "gerente de vendas",
        "gerente_vendas",
    }:
        return ROLE_GERENTE_VENDAS
    if normalized_text in {ADMIN_ROLE_ADMIN, "3", "admin", "administrador"}:
        return ROLE_ADMIN
    if normalized_text in {ADMIN_ROLE_FINANCEIRO, "4", "financeiro"}:
        return ROLE_FINANCEIRO
    if normalized_text in {
        ADMIN_ROLE_DIRETOR_COMERCIAL,
        "5",
        "diretor",
        "diretor comercial",
        "diretor_comercial",
    }:
        return ROLE_DIRETOR_COMERCIAL
    return ""


def _parse_scope_code_list(text: str, role_name: str) -> list[str]:
    scopes: list[str] = []
    seen: set[str] = set()
    for token in extract_scope_input_tokens(text):
        if role_name == ROLE_VENDEDOR:
            normalized = normalize_sector_scope_input(token)
        elif role_name == ROLE_FINANCEIRO:
            normalized = normalize_filial_scope_input(token)
        elif role_name == ROLE_DIRETOR_COMERCIAL:
            normalized = normalize_stored_scope_value(f"dc:{token}")
        else:
            normalized = normalize_gv_scope_input(token)
        if not normalized or normalized == "0" or normalized in seen:
            continue
        seen.add(normalized)
        scopes.append(normalized)
    return scopes


def _parse_management_scope_code_list(text: str) -> list[str]:
    if re.search(r"\d+\s*[-/:\\|]\s*\d+", str(text or "")):
        return []

    codes: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"\d+", str(text or "")):
        normalized = normalize_numeric_code(token)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        codes.append(normalized)
    return codes


def _parse_direct_registration_lookup(text: str) -> tuple[str, str] | None:
    normalized_text = _normalize_choice(text)

    direct_pair = re.search(r"\b(\d{1,4})\D+(\d{2,})\b", normalized_text)
    if direct_pair:
        return _normalize_filial(direct_pair.group(1)), _normalize_cod_pdv(direct_pair.group(2))

    labeled = re.search(
        r"(?:revenda|filial)\D*(\d{1,4}).*?(?:nb|cod(?:igo)?\s*pdv)\D*(\d{2,})",
        normalized_text,
        flags=re.I,
    )
    if labeled:
        return _normalize_filial(labeled.group(1)), _normalize_cod_pdv(labeled.group(2))
    return None


def _parse_hybrid_search_request(
    *,
    text: str,
    normalized_text: str,
    search_context: str,
    allow_contextless_query: bool,
) -> HybridSearchRequest | None:
    if not normalized_text or _looks_like_plain_numeric_choice(normalized_text):
        return None

    normalized_tokens = _normalized_tokens(normalized_text)

    if search_context == "inadimplencia" and (
        normalized_text in {
            SEARCH_BY_INADIMPLENTES_BASE,
            "inadimplentes da base",
            "mostrar inadimplentes",
            "ver inadimplentes",
            "lista de inadimplentes",
            "clientes inadimplentes",
        }
        or (
            "base" in normalized_tokens
            and normalized_tokens & {"inadimplencia", "inadimplente", "inadimplentes"}
        )
    ):
        return HybridSearchRequest(open_base_list=True)

    if search_context == "giro" and (
        normalized_text in {
            SEARCH_BY_GIRO_ZERO_BASE,
            "giro zero",
            "giro zero da base",
            "clientes com giro zero",
            "mostrar giro zero",
            "ver giro zero",
        }
        or (
            "base" in normalized_tokens
            and "giro" in normalized_tokens
            and "zero" in normalized_tokens
        )
    ):
        return HybridSearchRequest(open_giro_zero_base_list=True)

    document = _normalize_document(text)
    if document:
        return HybridSearchRequest(search_mode="document", document=document)

    direct_lookup = _parse_direct_registration_lookup(text)
    if direct_lookup is not None:
        return HybridSearchRequest(
            search_mode="registration",
            filial=direct_lookup[0],
            cod_pdv=direct_lookup[1],
        )

    if _looks_like_document_mode_request(normalized_text):
        return HybridSearchRequest(search_mode="document")

    if _looks_like_registration_mode_request(normalized_text):
        return HybridSearchRequest(search_mode="registration")

    query_text = _extract_hybrid_search_query(
        normalized_text=normalized_text,
        search_context=search_context,
        allow_contextless_query=allow_contextless_query,
    )
    visit_day_label = _resolve_hybrid_visit_day_label(
        normalized_text=normalized_text,
        search_context=search_context,
        query_text=query_text,
    )
    if visit_day_label:
        return HybridSearchRequest(visit_day_label=visit_day_label)
    if query_text:
        return HybridSearchRequest(search_mode="fantasia", query_text=query_text)

    if _looks_like_name_mode_request(normalized_text):
        return HybridSearchRequest(search_mode="fantasia")
    return None


def _parse_hybrid_finance_request(normalized_text: str) -> HybridFinanceRequest:
    tokens = _normalized_tokens(normalized_text)
    action = _parse_finance_action(normalized_text)
    due_bucket = _parse_finance_due_bucket(normalized_text)
    requested_day_label = _extract_requested_visit_day_label(normalized_text)
    visit_day_label = ""
    giro_mode = ""
    summary_mode = ""
    query_text = ""
    document = ""

    if not action:
        if "financeiro" in tokens and due_bucket == "today" and not (
            {"vencimento", "vencimentos", "vencido", "vencidos"} & tokens
            or ({"visita", "visitas"} & tokens and {"risco", "riscos"} & tokens)
            or {"resumo"} & tokens
        ):
            return HybridFinanceRequest(clarify_today=True, due_bucket=due_bucket)
        if {"vencimento", "vencimentos", "vencido", "vencidos", "atrasado", "atrasados", "vence"} & tokens:
            action = "upcoming"
        elif {"visita", "visitas"} & tokens and {"risco", "riscos"} & tokens:
            action = "visit_risk"
        elif {"maiores"} & tokens and {"devedor", "devedores"} & tokens:
            action = "top"
        elif {"inadimplente", "inadimplentes", "cobranca", "cobrancas"} & tokens:
            action = "list"
        elif {"resumo", "painel"} & tokens:
            action = "summary"
        elif "financeiro" in tokens and {"filial", "filiais", "revenda", "revendas", "gv", "gerente", "gerencia", "setor", "setores"} & tokens:
            action = "summary"
        elif "giro" in tokens:
            action = "giro"
        elif {"prazo", "limite"} <= tokens or ({"prazo", "limite"} & tokens and {"liberacao", "validacao"} & tokens):
            action = "prazo_limite"
        elif {"extrato", "movimentacao", "movimentacoes", "movimentos"} & tokens:
            action = "payip"
        elif _parse_payip_action(normalized_text) in {"validate_day", "import_batch", "routes"}:
            action = "payip"

    if action == "prazo_limite":
        document = _normalize_document(normalized_text)
        direct_lookup = _parse_direct_registration_lookup(normalized_text) if not document else None
        if direct_lookup is not None:
            return HybridFinanceRequest(
                action=action,
                due_bucket=due_bucket,
                filial=direct_lookup[0],
                cod_pdv=direct_lookup[1],
            )
        query_text = (
            _extract_hybrid_search_query(
                normalized_text=normalized_text,
                search_context="prazo_limite",
                allow_contextless_query=False,
            )
            if not document
            else ""
        )

    if action == "visit_risk":
        visit_day_label = requested_day_label

    if action == "summary":
        if {"documentacao", "documentos", "escaneada", "escaneado"} & tokens and {"filial", "filiais", "revenda", "revendas"} & tokens:
            summary_mode = "documentacao_by_filial"
        elif {"filial", "filiais", "revenda", "revendas"} & tokens:
            summary_mode = "by_filial"
        elif {"gv", "gerente", "gerencia"} & tokens:
            summary_mode = "by_gv"
        elif {"setor", "setores"} & tokens:
            summary_mode = "by_seller"
        elif {"resumo", "painel"} & tokens:
            summary_mode = "total"

    if action == "giro" or ("giro" in tokens and "financeiro" in tokens):
        if {"filial", "revenda"} & tokens:
            giro_mode = "by_filial"
        elif {"gv", "gerente"} & tokens:
            giro_mode = "by_gv"
        elif {"total", "consolidado", "geral"} & tokens:
            giro_mode = "total"
        if requested_day_label:
            visit_day_label = requested_day_label

    return HybridFinanceRequest(
        action=action,
        due_bucket=due_bucket,
        visit_day_label=visit_day_label,
        giro_mode=giro_mode,
        summary_mode=summary_mode,
        query_text=query_text,
        document=document,
        filial="",
        cod_pdv="",
    )


def _parse_finance_today_clarification(normalized_text: str) -> str:
    if normalized_text in {"1", "vencimentos", "vencimento", "vence hoje", "vencimentos de hoje"}:
        return "upcoming"
    if normalized_text in {
        "2",
        "visitas com risco",
        "visita com risco",
        "risco hoje",
        "visitas com risco hoje",
    }:
        return "visit_risk"
    if normalized_text in {"3", "resumo", "resumo financeiro", "painel"}:
        return "summary"
    return ""


def _detect_explicit_search_context(normalized_text: str) -> str:
    tokens = _normalized_tokens(normalized_text)
    if (
        re.match(r"^(analise|analisar)\b", normalized_text)
        or {"prazo", "limite"} <= tokens
        or ({"prazo", "limite"} & tokens and {"liberacao", "validacao"} & tokens)
    ):
        return "prazo_limite"
    if tokens & {"inadimplencia", "inadimplente", "inadimplentes", "cobranca", "cobrancas"} or "titulos em aberto" in normalized_text:
        return "inadimplencia"
    if tokens & {"comodato", "comodatos"}:
        return "comodato"
    if tokens & {"documentacao", "documentos"} or "documentacao pendente" in normalized_text or "documentos pendentes" in normalized_text:
        return "documentacao"
    if "giro" in tokens:
        return "giro"
    if _looks_like_explicit_client_lookup_request(normalized_text):
        return "cliente"
    return ""


def _looks_like_finance_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if _looks_like_explicit_client_lookup_request(normalized_text):
        return False
    if {"gerencia", "gerente", "diretoria", "diretor", "carteira", "vendedor"} & tokens and "financeiro" not in tokens:
        return False
    if _normalize_document(normalized_text) and {"cpf", "cnpj", "documento"} & tokens:
        return True
    if {"documentacao", "documentos", "escaneada", "escaneado"} & tokens and (
        {"resumo", "painel", "filial", "filiais", "revenda", "revendas"} & tokens
    ):
        return True
    if re.match(r"^(analise|analisar)\b", normalized_text):
        return True
    if "financeiro" in tokens:
        return True
    if {"vencimento", "vencimentos", "vencido", "vencidos", "atrasado", "atrasados"} & tokens:
        return True
    if {"maiores"} & tokens and {"devedor", "devedores"} & tokens:
        return True
    if {"visita", "visitas"} & tokens and {"risco", "riscos"} & tokens:
        return True
    if {"prazo", "limite"} <= tokens or ({"prazo", "limite"} & tokens and {"liberacao", "validacao"} & tokens):
        return True
    if {"payip", "extrato", "movimentacao", "movimentacoes", "movimentos"} & tokens:
        return True
    if _parse_payip_action(normalized_text) in {"validate_day", "import_batch", "routes"}:
        return True
    return False


def _looks_like_explicit_client_lookup_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    return (
        "buscar cliente" in normalized_text
        or "cadastro do cliente" in normalized_text
        or (
            "cliente" in tokens
            and bool(tokens & {"buscar", "busca", "consultar", "consulta", "procurar", "dados", "cadastro", "ver", "mostrar", "mostra"})
        )
    )


def _looks_like_visit_day_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if not ({"visita", "visitas", "rota", "rotas"} & tokens or "dia de visita" in normalized_text):
        return False
    if {"risco", "riscos", "financeiro", "financeira"} & tokens:
        return False
    return True


def _looks_like_plain_numeric_choice(normalized_text: str) -> bool:
    return bool(re.fullmatch(r"0*\d+", normalized_text))


def _looks_like_contextual_follow_up(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    if _looks_like_plain_numeric_choice(normalized_text):
        return True
    if normalized_text in {
        *MENU_BACK_COMMANDS,
        *PAGE_NEXT_COMMANDS,
        "anterior",
        "pagina anterior",
        "proxima",
        "proximo",
        "proxima pagina",
        "pagina seguinte",
        "cpf",
        "cnpj",
        "documento",
        "nome",
        "fantasia",
        "filial",
        "codigo",
        "cod",
        "nb",
        "cliente",
        "clientes",
        "lista",
        "base",
        "inadimplencia",
        "comodato",
        "giro",
        "hoje",
        "amanha",
    }:
        return True
    tokens = _normalized_tokens(normalized_text)
    if len(tokens) <= 2 and tokens <= {"cpf", "cnpj", "documento", "nome", "fantasia", "filial", "codigo", "cod", "nb"}:
        return True
    return False


def _looks_like_summary_short_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if not ({"resumo", "painel"} & tokens):
        return False
    if {"financeiro", "gv", "gerencia", "gerente", "diretoria", "diretor", "carteira", "vendedor"} & tokens:
        return False
    return len(tokens) <= 3


def _looks_like_today_short_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if "hoje" not in tokens:
        return False
    return tokens <= {"hoje", "de"}


def _looks_like_today_risk_short_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    return "hoje" in tokens and bool({"risco", "riscos"} & tokens) and len(tokens) <= 4


def _looks_like_giro_short_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if "giro" not in tokens:
        return False
    if {
        "cpf",
        "cnpj",
        "documento",
        "nome",
        "fantasia",
        "cliente",
        "filial",
        "revenda",
        "codigo",
        "cod",
        "nb",
        "gv",
        "gerente",
        "total",
        "consolidado",
        "geral",
    } & tokens:
        return False
    return len(tokens) <= 3


def _looks_like_list_short_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if not ({"lista", "listar"} & tokens):
        return False
    if {"inadimplencia", "inadimplentes", "visita", "visitas", "cliente", "clientes", "comodato", "comodatos"} & tokens:
        return False
    return len(tokens) <= 3


def _looks_like_base_short_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if "base" not in tokens:
        return False
    if {"inadimplencia", "inadimplentes", "financeiro", "giro", "resumo", "cliente", "clientes"} & tokens:
        return False
    return len(tokens) <= 3


def _looks_like_client_short_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    if not ({"cliente", "clientes"} & tokens):
        return False
    if {"buscar", "busca", "consultar", "consulta", "procurar", "dados", "cadastro", "ver", "mostrar", "mostra"} & tokens:
        return False
    return len(tokens) <= 3 or normalized_text in {"esse cliente", "desse cliente", "cliente atual"}


def _looks_like_document_mode_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    return bool({"cpf", "cnpj", "documento"} & tokens)


def _looks_like_registration_mode_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    return bool({"filial", "nb"} & tokens or "codigo" in tokens or "cod" in tokens)


def _looks_like_name_mode_request(normalized_text: str) -> bool:
    tokens = _normalized_tokens(normalized_text)
    return bool({"nome", "fantasia"} & tokens or "nome do cliente" in normalized_text)


def _extract_hybrid_search_query(
    *,
    normalized_text: str,
    search_context: str,
    allow_contextless_query: bool,
) -> str:
    contextual_query = _extract_contextual_query_from_phrase(
        normalized_text=normalized_text,
        search_context=search_context,
    )
    if contextual_query:
        return contextual_query

    cleaned = _strip_hybrid_prefixes(
        normalized_text,
        (
            "oi",
            "ola",
            "quero ver",
            "quero consultar",
            "quero buscar",
            "quero",
            "me mostra",
            "mostrar",
            "ver",
            "consultar",
            "consulta",
            "buscar",
            "procuro",
            "procurar",
            "abrir",
            "acessar",
            "ir para",
        ),
    )
    cleaned = _strip_hybrid_prefixes(cleaned, _hybrid_search_context_prefixes(search_context))
    cleaned = _strip_hybrid_prefixes(
        cleaned,
        (
            "por nome",
            "nome do cliente",
            "nome fantasia",
            "por cliente",
            "do cliente",
            "da cliente",
            "cliente",
        ),
    )
    cleaned = _strip_single_leading_connector(cleaned)
    if not cleaned:
        return ""
    if not allow_contextless_query and cleaned == normalized_text:
        return ""
    query_tokens = _normalized_tokens(cleaned)
    if not query_tokens:
        return ""
    if query_tokens <= {
        "menu",
        "inicio",
        "buscar",
        "consulta",
        "consultar",
        "cliente",
        "clientes",
        "inadimplencia",
        "inadimplente",
        "inadimplentes",
        "comodato",
        "comodatos",
        "documentacao",
        "documentos",
        "giro",
        "cpf",
        "cnpj",
        "documento",
        "filial",
        "codigo",
        "cod",
        "nb",
        "financeiro",
        "visita",
        "visitas",
        "hoje",
        "amanha",
    }:
        return ""
    if not re.search(r"[a-z]", cleaned):
        return ""
    return cleaned


def _extract_requested_visit_day_label(normalized_text: str) -> str:
    tokens = _normalized_tokens(normalized_text)
    if "hoje" in tokens:
        return _current_visit_day_label()
    if re.search(r"\bdo dia\b", normalized_text) and (
        tokens
        & {
            "giro",
            "visita",
            "visitas",
            "rota",
            "rotas",
            "inadimplencia",
            "inadimplente",
            "inadimplentes",
            "cobranca",
            "cobrancas",
            "financeiro",
            "documentacao",
            "documentos",
            "titulo",
            "titulos",
        }
    ):
        return _current_visit_day_label()
    for token, label in VISIT_DAY_CHOICES:
        normalized_label = _normalize_choice(label)
        if normalized_label in normalized_text or token.rstrip("/").lower() in tokens:
            return label
    return ""


def _resolve_hybrid_visit_day_label(
    *,
    normalized_text: str,
    search_context: str,
    query_text: str,
) -> str:
    if search_context not in {"giro", "inadimplencia", "documentacao"}:
        return ""

    visit_day_label = _extract_requested_visit_day_label(normalized_text)
    if not visit_day_label:
        return ""

    normalized_query = _normalize_choice(query_text)
    normalized_day_label = _normalize_choice(visit_day_label)
    tokens = _normalized_tokens(normalized_text)

    if re.search(r"\bdo dia\b", normalized_text) or "hoje" in tokens:
        return visit_day_label
    if normalized_query in {"", normalized_day_label}:
        return visit_day_label
    if search_context == "giro" and tokens & {"visita", "visitas", "rota", "rotas"}:
        return visit_day_label
    if search_context == "inadimplencia" and tokens & {"risco", "riscos", "financeiro", "rota", "rotas"}:
        return visit_day_label
    if search_context == "documentacao" and tokens & {"documentacao", "documentos", "pendencia", "pendencias", "rota", "rotas"}:
        return visit_day_label
    return ""


def _match_requested_visit_day(requested_day_label: str, visit_days: tuple[str, ...]) -> str:
    normalized_requested = _normalize_choice(requested_day_label)
    requested_token = _visit_day_token_from_label(requested_day_label)
    for visit_day in visit_days:
        if _normalize_choice(visit_day) == normalized_requested:
            return visit_day
        if _normalize_choice(_format_visit_day_label(visit_day)) == normalized_requested:
            return visit_day
        if requested_token and _visit_day_token_from_label(visit_day) == requested_token:
            return visit_day
    return ""


def _normalized_tokens(normalized_text: str) -> set[str]:
    raw_tokens = {
        token
        for token in re.sub(r"[^a-z0-9]+", " ", str(normalized_text or "")).split()
        if token
    }
    expanded_tokens: set[str] = set(raw_tokens)
    for token in raw_tokens:
        expanded_tokens.update(_expand_semantic_token(token))
    return expanded_tokens


def _expand_semantic_token(token: str) -> set[str]:
    value = str(token or "").strip().lower()
    if not value:
        return set()

    expanded = {value}
    if _matches_token_family(value, ("inad", "inadimpl")):
        expanded.update({"inadimplencia", "inadimplente", "inadimplentes"})
    if _matches_token_family(value, ("cobr", "cobran")):
        expanded.update({"cobranca", "cobrancas"})
    if _matches_token_family(value, ("comod",)):
        expanded.update({"comodato", "comodatos"})
    if _matches_token_family(value, ("docum", "document")):
        expanded.update({"documentacao", "documentos"})
    if _matches_token_family(value, ("finan", "finance")):
        expanded.add("financeiro")
    if _matches_token_family(value, ("visit",)):
        expanded.update({"visita", "visitas"})
    return expanded


def _matches_token_family(token: str, prefixes: tuple[str, ...]) -> bool:
    value = str(token or "").strip().lower()
    if len(value) < 4:
        return False
    return any(value.startswith(prefix) for prefix in prefixes)


def _extract_contextual_query_from_phrase(*, normalized_text: str, search_context: str) -> str:
    verbs_pattern = (
        r"(?:quero ver|quero consultar|quero buscar|me mostra|mostrar|ver|consultar|consulta|buscar|procuro|procurar|abrir|acessar|ir para|analise|analisar)"
    )
    context_pattern = {
        "inadimplencia": r"(?:inad(?:impl(?:encia|ente|entes)?)?|titulos em aberto|titulos|cobr(?:anca|ancas)?)",
        "comodato": r"(?:comod(?:ato|atos)?|comodatos pendentes)",
        "documentacao": r"(?:document(?:acao|acoes|al|ais)?|documentos(?: pendentes)?)",
        "prazo_limite": r"(?:prazo(?: e)? limite|limite(?: e)? prazo|liberacao de prazo e limite|validacao de prazo e limite)",
        "giro": r"(?:giro|dados de giro|consultar giro)",
        "cliente": r"(?:cliente|buscar cliente|cadastro do cliente|dados do cliente)",
    }.get(search_context, "")
    if not context_pattern:
        return ""

    patterns = (
        rf"^(?:{verbs_pattern})\s+(?:a\s+|o\s+|os\s+|as\s+)?(?:{context_pattern})\s+(?:da|do|de)\s+(.+)$",
        rf"^(?:{context_pattern})\s+(?:da|do|de)\s+(.+)$",
        r"^(?:por nome|nome do cliente|nome fantasia)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized_text)
        if not match:
            continue
        candidate = _strip_single_leading_connector(match.group(1))
        if candidate and re.search(r"[a-z]", candidate):
            return candidate
    return ""


def _strip_hybrid_prefixes(text: str, prefixes: tuple[str, ...]) -> str:
    value = str(text or "").strip()
    changed = True
    while value and changed:
        changed = False
        for prefix in prefixes:
            candidate = prefix.strip()
            if not candidate:
                continue
            if value == candidate:
                value = ""
                changed = True
                break
            if value.startswith(f"{candidate} "):
                value = value[len(candidate) :].strip()
                changed = True
                break
    return value


def _strip_single_leading_connector(text: str) -> str:
    value = str(text or "").strip()
    for connector in ("da", "do", "de", "na", "no", "pela", "pelo", "sobre"):
        if value.startswith(f"{connector} "):
            return value[len(connector) :].strip()
    return value


def _hybrid_search_context_prefixes(search_context: str) -> tuple[str, ...]:
    if search_context == "inadimplencia":
        return (
            "inad",
            "inadimpl",
            "inadimplencia",
            "inadimplente",
            "inadimplentes",
            "titulos em aberto",
            "titulos",
            "cobranca",
            "cobrancas",
        )
    if search_context == "comodato":
        return (
            "comod",
            "comodato",
            "comodatos",
            "comodatos pendentes",
        )
    if search_context == "documentacao":
        return (
            "documentacao",
            "documentacao pendente",
            "documentos",
            "documentos pendentes",
        )
    if search_context == "prazo_limite":
        return (
            "analise",
            "analisar",
            "prazo e limite",
            "prazo limite",
            "limite e prazo",
            "liberacao de prazo e limite",
            "validacao de prazo e limite",
        )
    if search_context == "giro":
        return (
            "giro",
            "dados de giro",
            "consultar giro",
        )
    return (
        "buscar cliente",
        "cliente",
        "cadastro do cliente",
        "dados do cliente",
    )


def _select_unique_text_candidate(normalized_text: str, candidates: list[tuple[tuple[str, ...], Any]]) -> Any | None:
    cleaned = _normalize_choice(normalized_text)
    if not cleaned or _looks_like_plain_numeric_choice(cleaned):
        return None

    cleaned_tokens = _normalized_tokens(cleaned)
    exact_matches: list[Any] = []
    prefix_matches: list[Any] = []
    contains_matches: list[Any] = []
    token_matches: list[Any] = []

    for labels, candidate in candidates:
        normalized_labels = [label for label in (_normalize_choice(value) for value in labels) if label]
        if not normalized_labels:
            continue
        if cleaned in normalized_labels:
            exact_matches.append(candidate)
            continue
        if len(cleaned) >= 3 and any(label.startswith(cleaned) or cleaned.startswith(label) for label in normalized_labels):
            prefix_matches.append(candidate)
            continue
        if len(cleaned) >= 4 and any(cleaned in label for label in normalized_labels):
            contains_matches.append(candidate)
            continue
        if cleaned_tokens and any(cleaned_tokens <= _normalized_tokens(label) for label in normalized_labels):
            token_matches.append(candidate)

    for match_group in (exact_matches, prefix_matches, contains_matches, token_matches):
        unique_matches = _dedupe_candidates(match_group)
        if len(unique_matches) == 1:
            return unique_matches[0]
    return None


def _dedupe_candidates(values: list[Any]) -> list[Any]:
    unique_values: list[Any] = []
    seen: set[int] = set()
    for value in values:
        marker = id(value)
        if marker in seen:
            continue
        seen.add(marker)
        unique_values.append(value)
    return unique_values


def _select_interactive_option(
    text: str,
    normalized: str,
    options: tuple[InteractiveOption, ...],
) -> InteractiveOption | None:
    if not options:
        return None

    if text in {option.option_id for option in options}:
        for option in options:
            if option.option_id == text:
                return option

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(options):
            return options[selected_index - 1]
        for option in options:
            if option.shortcut and text_digits == "".join(char for char in option.shortcut if char.isdigit()):
                return option

    for option in options:
        if normalized == _normalize_choice(option.option_id):
            return option
        if option.shortcut and normalized == _normalize_choice(option.shortcut):
            return option
        if normalized == _normalize_choice(option.title):
            return option

    selected_option = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    option.title,
                    option.description,
                    option.shortcut,
                ),
                option,
            )
            for option in options
        ],
    )
    if selected_option is not None:
        return selected_option

    return None


def _select_fantasia_record(
    text: str,
    normalized: str,
    records: tuple[DClienteRecord, ...],
) -> DClienteRecord | None:
    if not records:
        return None

    if normalized.startswith(FANTASIA_PICK_PREFIX):
        raw_index = normalized.removeprefix(FANTASIA_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(records):
                return records[selected_index - 1]

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(records):
            return records[selected_index - 1]

        exact_code_matches = [record for record in records if _normalize_cod_pdv(record.cod_pdv) == _normalize_cod_pdv(text)]
        if len(exact_code_matches) == 1:
            return exact_code_matches[0]

    selected_record = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    record.nome_fantasia or "",
                    record.razao_social or "",
                    f"codigo {record.cod_pdv}",
                    f"nb {record.cod_pdv}",
                ),
                record,
            )
            for record in records
        ],
    )
    if selected_record is not None:
        return selected_record

    return None


def _select_inadimplencia_client_summary(
    text: str,
    normalized: str,
    summaries: tuple[InadimplenciaClientSummary, ...],
) -> InadimplenciaClientSummary | None:
    if not summaries:
        return None

    if normalized.startswith(INADIMPLENCIA_CLIENT_PICK_PREFIX):
        raw_key = normalized.removeprefix(INADIMPLENCIA_CLIENT_PICK_PREFIX)
        for summary in summaries:
            summary_key = f"{_normalize_filial(summary.filial)}:{_normalize_cod_pdv(summary.cod_pdv)}"
            if summary_key == raw_key:
                return summary

    if normalized.startswith(FANTASIA_PICK_PREFIX):
        raw_index = normalized.removeprefix(FANTASIA_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(summaries):
                return summaries[selected_index - 1]

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(summaries):
            return summaries[selected_index - 1]

        exact_code_matches = [summary for summary in summaries if _normalize_cod_pdv(summary.cod_pdv) == _normalize_cod_pdv(text)]
        if len(exact_code_matches) == 1:
            return exact_code_matches[0]

    selected_summary = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    summary.nome or "",
                    f"nb {summary.cod_pdv}",
                    f"codigo {summary.cod_pdv}",
                ),
                summary,
            )
            for summary in summaries
        ],
    )
    if selected_summary is not None:
        return selected_summary

    return None


def _select_comodato_client_summary(
    text: str,
    normalized: str,
    summaries: tuple[ComodatoClientSummary, ...],
) -> ComodatoClientSummary | None:
    if not summaries:
        return None

    if normalized.startswith(FANTASIA_PICK_PREFIX):
        raw_index = normalized.removeprefix(FANTASIA_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(summaries):
                return summaries[selected_index - 1]

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(summaries):
            return summaries[selected_index - 1]

        exact_code_matches = [summary for summary in summaries if _normalize_cod_pdv(summary.cod_pdv) == _normalize_cod_pdv(text)]
        if len(exact_code_matches) == 1:
            return exact_code_matches[0]

    selected_summary = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    summary.nome or "",
                    f"nb {summary.cod_pdv}",
                    f"codigo {summary.cod_pdv}",
                ),
                summary,
            )
            for summary in summaries
        ],
    )
    if selected_summary is not None:
        return selected_summary

    return None


def _select_visit_day(
    text: str,
    normalized: str,
    visit_days: tuple[str, ...],
) -> str | None:
    if not visit_days:
        return None

    if normalized.startswith(VISIT_DAY_PICK_PREFIX):
        raw_index = normalized.removeprefix(VISIT_DAY_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(visit_days):
                return visit_days[selected_index - 1]

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(visit_days):
            return visit_days[selected_index - 1]

    for visit_day in visit_days:
        if _normalize_choice(visit_day) == normalized:
            return visit_day

    requested_day_label = _extract_requested_visit_day_label(normalized)
    if requested_day_label:
        matched_visit_day = _match_requested_visit_day(requested_day_label, visit_days)
        if matched_visit_day:
            return matched_visit_day

    return None


def _select_visit_seller_summary(
    text: str,
    normalized: str,
    summaries: tuple[VisitSellerSummary, ...],
) -> VisitSellerSummary | None:
    if not summaries:
        return None

    if normalized.startswith(VISIT_SELLER_PICK_PREFIX):
        raw_index = normalized.removeprefix(VISIT_SELLER_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(summaries):
                return summaries[selected_index - 1]

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(summaries):
            return summaries[selected_index - 1]

    normalized_scope = normalize_stored_scope_value(text)
    if normalized_scope:
        exact_matches = [summary for summary in summaries if normalize_stored_scope_value(summary.seller_code) == normalized_scope]
        if len(exact_matches) == 1:
            return exact_matches[0]

    for summary in summaries:
        if _normalize_choice(summary.seller_code) == normalized or _normalize_choice(_format_sector_scope_label(summary.seller_code)) == normalized:
            return summary

    selected_summary = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    summary.seller_code,
                    _format_sector_scope_label(summary.seller_code),
                    summary.manager_code,
                    _format_gv_scope_label(summary.manager_code),
                ),
                summary,
            )
            for summary in summaries
        ],
    )
    if selected_summary is not None:
        return selected_summary

    return None


def _select_finance_visit_risk_summary(
    text: str,
    normalized: str,
    summaries: tuple[InadimplenciaVisitRiskSummary, ...],
) -> InadimplenciaVisitRiskSummary | None:
    if not summaries:
        return None

    if normalized.startswith(FINANCE_VISIT_RISK_PICK_PREFIX):
        raw_key = normalized.removeprefix(FINANCE_VISIT_RISK_PICK_PREFIX)
        for summary in summaries:
            summary_key = f"{normalize_stored_scope_value(summary.seller_code)}:{normalize_stored_scope_value(summary.manager_code)}"
            if summary_key == raw_key:
                return summary

    normalized_scope = normalize_stored_scope_value(text)
    if normalized_scope:
        seller_matches = [summary for summary in summaries if normalize_stored_scope_value(summary.seller_code) == normalized_scope]
        if len(seller_matches) == 1:
            return seller_matches[0]
    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(summaries):
            return summaries[selected_index - 1]

    for summary in summaries:
        if _normalize_choice(_format_sector_scope_label(summary.seller_code)) == normalized:
            return summary

    selected_summary = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    _format_sector_scope_label(summary.seller_code),
                    summary.seller_code,
                    _format_gv_scope_label(summary.manager_code),
                    summary.manager_code,
                ),
                summary,
            )
            for summary in summaries
        ],
    )
    if selected_summary is not None:
        return selected_summary

    return None


def _select_finance_gv_option(
    text: str,
    normalized: str,
    gv_options: tuple[str, ...],
) -> str | None:
    if not gv_options:
        return None

    digits = "".join(char for char in text if char.isdigit())
    normalized_digits = digits.lstrip("0") or "0" if digits else ""
    normalized_scope = normalize_stored_scope_value(text)
    if normalized_scope:
        exact_matches = [gv_code for gv_code in gv_options if normalize_stored_scope_value(gv_code) == normalized_scope]
        if len(exact_matches) == 1:
            return exact_matches[0]
    if normalized_digits:
        exact_matches = [gv_code for gv_code in gv_options if (normalize_numeric_code(gv_code) or "0") == normalized_digits]
        if len(exact_matches) == 1:
            return exact_matches[0]
        selected_index = int(normalized_digits)
        if 1 <= selected_index <= len(gv_options):
            return gv_options[selected_index - 1]

    for gv_code in gv_options:
        if _normalize_choice(_format_gv_scope_label(gv_code)) == normalized:
            return gv_code

    selected_gv = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    gv_code,
                    _format_gv_scope_label(gv_code),
                ),
                gv_code,
            )
            for gv_code in gv_options
        ],
    )
    if selected_gv is not None:
        return selected_gv

    return None


def _select_giro_visit_gv_option(
    text: str,
    normalized: str,
    gv_options: tuple[str, ...],
) -> str | None:
    if not gv_options:
        return None

    if normalized.startswith(GIRO_VISIT_GV_PICK_PREFIX):
        raw_index = normalized.removeprefix(GIRO_VISIT_GV_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(gv_options):
                return gv_options[selected_index - 1]

    return _select_finance_gv_option(text=text, normalized=normalized, gv_options=gv_options)


def _select_giro_visit_sector_summary(
    text: str,
    normalized: str,
    summaries: tuple[GiroVisitSectorSummary, ...],
    gv_code: str,
) -> GiroVisitSectorSummary | None:
    if not summaries:
        return None

    filtered = [
        summary
        for summary in summaries
        if (normalize_stored_scope_value(summary.manager_code) or normalize_stored_scope_value(summary.seller_code))
        == normalize_stored_scope_value(gv_code)
    ]
    if not filtered:
        return None

    if normalized.startswith(GIRO_VISIT_SELLER_PICK_PREFIX):
        raw_index = normalized.removeprefix(GIRO_VISIT_SELLER_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(filtered):
                return filtered[selected_index - 1]

    normalized_scope = normalize_stored_scope_value(text)
    if normalized_scope:
        exact_matches = [
            summary for summary in filtered if normalize_stored_scope_value(summary.seller_code) == normalized_scope
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(filtered):
            return filtered[selected_index - 1]

    for summary in filtered:
        if _normalize_choice(_format_sector_scope_label(summary.seller_code)) == normalized:
            return summary

    selected_summary = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    summary.seller_code,
                    _format_sector_scope_label(summary.seller_code),
                ),
                summary,
            )
            for summary in filtered
        ],
    )
    if selected_summary is not None:
        return selected_summary

    return None


def _select_documentacao_visit_gv_option(
    text: str,
    normalized: str,
    gv_options: tuple[str, ...],
) -> str | None:
    if not gv_options:
        return None

    if normalized.startswith(DOCUMENTACAO_VISIT_GV_PICK_PREFIX):
        raw_index = normalized.removeprefix(DOCUMENTACAO_VISIT_GV_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(gv_options):
                return gv_options[selected_index - 1]

    return _select_finance_gv_option(text=text, normalized=normalized, gv_options=gv_options)


def _select_documentacao_visit_sector_summary(
    text: str,
    normalized: str,
    summaries: tuple[DocumentacaoVisitSectorSummary, ...],
    gv_code: str,
) -> DocumentacaoVisitSectorSummary | None:
    if not summaries:
        return None

    filtered = [
        summary
        for summary in summaries
        if (normalize_stored_scope_value(summary.manager_code) or normalize_stored_scope_value(summary.seller_code))
        == normalize_stored_scope_value(gv_code)
    ]
    if not filtered:
        return None

    if normalized.startswith(DOCUMENTACAO_VISIT_SELLER_PICK_PREFIX):
        raw_index = normalized.removeprefix(DOCUMENTACAO_VISIT_SELLER_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(filtered):
                return filtered[selected_index - 1]

    normalized_scope = normalize_stored_scope_value(text)
    if normalized_scope:
        exact_matches = [
            summary for summary in filtered if normalize_stored_scope_value(summary.seller_code) == normalized_scope
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]

    text_digits = "".join(char for char in text if char.isdigit())
    if text_digits.isdigit():
        selected_index = int(text_digits)
        if 1 <= selected_index <= len(filtered):
            return filtered[selected_index - 1]

    for summary in filtered:
        if _normalize_choice(_format_sector_scope_label(summary.seller_code)) == normalized:
            return summary

    selected_summary = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    summary.seller_code,
                    _format_sector_scope_label(summary.seller_code),
                ),
                summary,
            )
            for summary in filtered
        ],
    )
    if selected_summary is not None:
        return selected_summary

    return None


def _select_filial_option(
    text: str,
    normalized: str,
    filial_options: tuple[str, ...],
) -> str | None:
    if not filial_options:
        return None

    normalized_filial = _normalize_filial(text)
    if normalized_filial:
        exact_matches = [filial for filial in filial_options if _normalize_filial(filial) == normalized_filial]
        if len(exact_matches) == 1:
            return exact_matches[0]
        selected_index = int(normalized_filial)
        if 1 <= selected_index <= len(filial_options):
            return filial_options[selected_index - 1]

    for filial in filial_options:
        if _normalize_choice(_format_filial_label(filial)) == normalized:
            return filial

    selected_filial = _select_unique_text_candidate(
        normalized,
        [
            (
                (
                    filial,
                    _format_filial_label(filial),
                ),
                filial,
            )
            for filial in filial_options
        ],
    )
    if selected_filial is not None:
        return selected_filial

    return None


def _format_roles(roles: tuple[str, ...]) -> str:
    if not roles:
        return "nenhum"
    role_labels = {
        ROLE_ADMIN: "Admin",
        ROLE_FINANCEIRO: "Financeiro",
        ROLE_GERENTE_VENDAS: "Gerente de Vendas",
        ROLE_DIRETOR_COMERCIAL: "Diretor Comercial",
        ROLE_VENDEDOR: "Vendedor",
    }
    return ", ".join(role_labels.get(role, role.title()) for role in roles)


def _format_health_status(ready: bool) -> str:
    return "ok" if ready else "indisponivel"


def _format_access_decision_label(decision: AccessDecision) -> str:
    return "liberado" if decision.allowed else f"bloqueado ({decision.reason})"


def _format_sectors(sectors: tuple[str, ...]) -> str:
    return format_scope_list(sectors, format_sector_scope)


def _format_finance_filiais(filiais: tuple[str, ...]) -> str:
    return format_scope_list(filiais, format_filial_scope)


def _format_gv_vdes(gv_vdes: tuple[str, ...], role_name: str | None = None) -> str:
    if role_name == ROLE_DIRETOR_COMERCIAL and any(str(value).startswith("dc:") for value in gv_vdes):
        return _format_grouped_management_scopes(gv_vdes, code_label="DC")
    if role_name == ROLE_GERENTE_VENDAS:
        return _format_grouped_management_scopes(gv_vdes, code_label="GV")
    if any(str(value).startswith("dc:") for value in gv_vdes):
        return format_scope_list(gv_vdes, format_dc_scope)
    return format_scope_list(gv_vdes, format_gv_scope)


def _format_sector_scope_label(value: str) -> str:
    return format_sector_scope(value)


def _format_gv_scope_label(value: str) -> str:
    return format_gv_scope(value)


def _format_visit_manager_summary_label(manager_code: str, seller_code: str = "") -> str:
    normalized_manager_code = normalize_stored_scope_value(manager_code)
    if normalized_manager_code:
        return _format_gv_scope_label(normalized_manager_code)
    pair = split_scope_pair(normalize_stored_scope_value(seller_code))
    if pair:
        return _format_filial_label(pair[0])
    return "-"


def _sort_numeric_text(value: str) -> tuple[int, str]:
    normalized = normalize_numeric_code(value)
    if normalized:
        return (0, f"{int(normalized):08d}")
    return (1, str(value or ""))


def _sort_scope_code(value: str) -> tuple[tuple[int, str], tuple[int, str], str]:
    pair = split_scope_pair(value)
    if pair:
        return (_sort_numeric_text(pair[0]), _sort_numeric_text(pair[1]), str(value or ""))
    return (_sort_numeric_text(""), _sort_numeric_text(str(value or "")), str(value or ""))


def _append_visit_day_gv_summary_lines(lines: list[str], summaries: list[VisitSellerSummary]) -> None:
    grouped: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        seller_code = normalize_stored_scope_value(summary.seller_code)
        manager_code = normalize_stored_scope_value(summary.manager_code)
        group_key = manager_code or seller_code or "-"
        bucket = grouped.setdefault(
            group_key,
            {
                "label": _format_visit_manager_summary_label(manager_code, seller_code),
                "sort_value": manager_code or seller_code or "-",
                "sectors": set(),
                "visit_count": 0,
            },
        )
        if seller_code:
            bucket["sectors"].add(seller_code)
        bucket["visit_count"] += int(summary.visit_count or 0)

    if not grouped:
        return

    lines.append("Resumo dos GVs:")
    for bucket in sorted(grouped.values(), key=lambda item: _sort_scope_code(str(item["sort_value"]))):
        lines.append(
            f"- {bucket['label']}: {len(bucket['sectors'])} setor(es) | {bucket['visit_count']} visita(s)"
        )


def _append_visit_risk_gv_summary_lines(
    lines: list[str],
    summaries: list[InadimplenciaVisitRiskSummary],
) -> None:
    grouped: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        seller_code = normalize_stored_scope_value(summary.seller_code)
        manager_code = normalize_stored_scope_value(summary.manager_code)
        group_key = manager_code or seller_code or "-"
        bucket = grouped.setdefault(
            group_key,
            {
                "label": _format_visit_manager_summary_label(manager_code, seller_code),
                "sort_value": manager_code or seller_code or "-",
                "sectors": set(),
                "client_count": 0,
                "totals": [],
            },
        )
        if seller_code:
            bucket["sectors"].add(seller_code)
        bucket["client_count"] += int(summary.client_count or 0)
        bucket["totals"].append(summary.total_pendente)

    if not grouped:
        return

    lines.append("Resumo dos GVs:")
    for bucket in sorted(grouped.values(), key=lambda item: _sort_scope_code(str(item["sort_value"]))):
        lines.append(
            f"- {bucket['label']}: {len(bucket['sectors'])} setor(es) | "
            f"{bucket['client_count']} cliente(s) | R$ {_sum_money_values(bucket['totals'])}"
        )


def _append_giro_visit_day_gv_summary_lines(
    lines: list[str],
    clients_with_opportunity: list[tuple[str, str, str, str, str, str, str, str]]
) -> None:
    grouped: dict[str, dict[str, Any]] = {}
    for manager_code, seller_code, _setor_code, _cod_pdv, _client_name, total_caixas, gap_caixas, _gap_detail in clients_with_opportunity:
        normalized_manager_code = normalize_stored_scope_value(manager_code)
        normalized_seller_code = normalize_stored_scope_value(seller_code)
        group_key = normalized_manager_code or normalized_seller_code or "-"
        bucket = grouped.setdefault(
            group_key,
            {
                "label": _format_visit_manager_summary_label(normalized_manager_code, normalized_seller_code),
                "sort_value": normalized_manager_code or normalized_seller_code or "-",
                "sectors": set(),
                "client_count": 0,
                "caixas": [],
                "faltam": [],
            },
        )
        if normalized_seller_code:
            bucket["sectors"].add(normalized_seller_code)
        bucket["client_count"] += 1
        bucket["caixas"].append(total_caixas)
        bucket["faltam"].append(gap_caixas)

    if not grouped:
        return

    lines.append("Resumo dos GVs:")
    for bucket in sorted(grouped.values(), key=lambda item: _sort_scope_code(str(item["sort_value"]))):
        lines.append(
            f"- {bucket['label']}: {len(bucket['sectors'])} setor(es) | "
            f"{bucket['client_count']} cliente(s) | "
            f"Caixas {_sum_formatted_amounts(*bucket['caixas'])} | "
            f"Faltam {_sum_formatted_amounts(*bucket['faltam'])}"
        )


def _format_grouped_management_scopes(values: tuple[str, ...], code_label: str) -> str:
    grouped: dict[str, list[str]] = {}
    for raw_value in values:
        normalized = normalize_stored_scope_value(raw_value)
        pair = split_scope_pair(normalized)
        if not pair:
            continue
        filial, code = pair
        grouped.setdefault(code, [])
        if filial not in grouped[code]:
            grouped[code].append(filial)

    if not grouped:
        formatter = format_dc_scope if code_label == "DC" else format_gv_scope
        return format_scope_list(values, formatter)

    items: list[str] = []
    for code in sorted(grouped, key=_sort_numeric_text):
        revendas = sorted(grouped[code], key=_sort_numeric_text)
        revenda_label = "Revenda" if len(revendas) == 1 else "Revendas"
        items.append(f"{code_label} {code} | {revenda_label} {', '.join(revendas)}")
    return ", ".join(items)


def _extract_filial_options_from_scope_codes(values: tuple[str, ...]) -> list[str]:
    filiais: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        pair = split_scope_pair(raw_value)
        if not pair:
            continue
        filial = pair[0]
        if filial in seen:
            continue
        seen.add(filial)
        filiais.append(filial)
    return sorted(filiais, key=_sort_numeric_text)


def _filter_scope_codes_by_filial(values: tuple[str, ...], filial: str) -> tuple[str, ...]:
    selected_filial = _normalize_filial(filial)
    filtered: list[str] = []
    for raw_value in values:
        pair = split_scope_pair(raw_value)
        if not pair or pair[0] != selected_filial:
            continue
        filtered.append(raw_value)
    return tuple(filtered)


def _primary_role(roles: tuple[str, ...]) -> str:
    return roles[0] if roles else ""


def _format_visit_financial_status(days_to_due: int) -> str:
    if days_to_due < 0:
        overdue_days = abs(days_to_due)
        return f"inadimplente ha {overdue_days} dia(s)"
    if days_to_due == 0:
        return "vence hoje"
    if days_to_due == 1:
        return "vence amanha"
    if days_to_due == 2:
        return "vence em 2 dias"
    return f"vence em {days_to_due} dia(s)"


def _encode_inadimplencia_header(header_text: str) -> str:
    return f"{INADIMPLENCIA_HEADER_PREFIX}{str(header_text or '').strip()}"


def _extract_inadimplencia_custom_header(query_text: str) -> str:
    text = str(query_text or "")
    if text.startswith(INADIMPLENCIA_HEADER_PREFIX):
        return text[len(INADIMPLENCIA_HEADER_PREFIX):].strip()
    return ""


def _extract_inadimplencia_scope_label(query_text: str) -> str:
    text = str(query_text or "")
    if text.startswith(INADIMPLENCIA_SCOPE_LIST_PREFIX):
        return text[len(INADIMPLENCIA_SCOPE_LIST_PREFIX):].strip()
    return ""


def _compute_page_count(total_items: int, page_size: int) -> int:
    normalized_total = max(int(total_items), 0)
    normalized_page_size = max(int(page_size), 1)
    if normalized_total == 0:
        return 1
    return ((normalized_total - 1) // normalized_page_size) + 1


def _extract_visit_day_labels(visit_days: list[str] | tuple[str, ...]) -> list[str]:
    available_labels: list[str] = []
    seen: set[str] = set()
    raw_values = [str(value or "").upper() for value in visit_days]
    for token, label in VISIT_DAY_CHOICES:
        if any(token in raw_value for raw_value in raw_values) and label not in seen:
            seen.add(label)
            available_labels.append(label)
    return available_labels


def _extract_visit_day_tokens(visit_days: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    for value in visit_days:
        normalized_value = _clean_visit_day_value(value)
        if not normalized_value:
            continue
        direct_token = _visit_day_token_from_label(normalized_value)
        if direct_token:
            seen.add(direct_token)
            continue
        raw_value = normalized_value.upper()
        for token, _label in VISIT_DAY_CHOICES:
            if token in raw_value:
                seen.add(token)
    return [token for token, _label in VISIT_DAY_CHOICES if token in seen]


def _normalize_visit_day_menu_values(visit_days: list[str] | tuple[str, ...]) -> list[str]:
    extracted_tokens = _extract_visit_day_tokens(visit_days)
    if extracted_tokens:
        return extracted_tokens
    return _ordered_visit_day_values(visit_days)


def _format_visit_day_label(visit_day: str) -> str:
    requested_token = _visit_day_token_from_label(visit_day)
    if requested_token:
        for token, label in VISIT_DAY_CHOICES:
            if token == requested_token:
                return label
    cleaned_value = _clean_visit_day_value(visit_day)
    if not cleaned_value:
        return ""
    return cleaned_value[:1].upper() + cleaned_value[1:]


def _format_cliente_visit_day(visit_day: str) -> str:
    tokens = _extract_visit_day_tokens([visit_day])
    if tokens:
        return ", ".join(_format_visit_day_label(token) for token in tokens)
    formatted = _format_visit_day_label(visit_day)
    return formatted or "-"


def _ordered_visit_day_values(visit_days: list[str] | tuple[str, ...]) -> list[str]:
    cleaned_values: list[str] = []
    seen_cleaned: set[str] = set()
    for value in visit_days:
        cleaned_value = _clean_visit_day_value(value)
        if not cleaned_value or cleaned_value in seen_cleaned:
            continue
        seen_cleaned.add(cleaned_value)
        cleaned_values.append(cleaned_value)

    ordered_values: list[str] = []
    seen_ordered: set[str] = set()
    for token, _label in VISIT_DAY_CHOICES:
        for value in cleaned_values:
            if value in seen_ordered:
                continue
            if _visit_day_token_from_label(value) == token or token in value.upper():
                seen_ordered.add(value)
                ordered_values.append(value)

    for value in cleaned_values:
        if value not in seen_ordered:
            ordered_values.append(value)
    return ordered_values


def _visit_day_token_from_label(label: str) -> str:
    normalized_label = _normalize_choice(label)
    for token, current_label in VISIT_DAY_CHOICES:
        if _normalize_choice(current_label) == normalized_label or _normalize_choice(token) == normalized_label:
            return token
    return ""


def _visit_day_values_for_token(
    raw_visit_days: list[str] | tuple[str, ...],
    visit_day_token: str,
) -> list[str]:
    normalized_token = _visit_day_token_from_label(visit_day_token) or _clean_visit_day_value(visit_day_token).upper()
    if not normalized_token:
        return []

    exact_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_visit_days:
        normalized_value = _clean_visit_day_value(raw_value)
        if not normalized_value:
            continue
        if normalized_token in normalized_value.upper() and normalized_value not in seen:
            seen.add(normalized_value)
            exact_values.append(normalized_value)

    if exact_values:
        return exact_values
    return [normalized_token]


def _clean_visit_day_value(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _current_visit_day_token(reference: datetime | None = None) -> str:
    current = reference.astimezone(LOCAL_TIMEZONE) if reference is not None else datetime.now(LOCAL_TIMEZONE)
    return {
        0: "SEG/",
        1: "TER/",
        2: "QUA/",
        3: "QUI/",
        4: "SEX/",
        5: "SAB/",
        6: "DOM/",
    }[current.weekday()]


def _current_visit_day_label(reference: datetime | None = None) -> str:
    current = reference.astimezone(LOCAL_TIMEZONE) if reference is not None else datetime.now(LOCAL_TIMEZONE)
    return {
        0: "segunda",
        1: "terca",
        2: "quarta",
        3: "quinta",
        4: "sexta",
        5: "sabado",
        6: "domingo",
    }[current.weekday()]


def _format_filial_label(filial: str) -> str:
    normalized_filial = _normalize_filial(filial)
    filial_name = FILIAL_LABELS.get(normalized_filial)
    if filial_name:
        return f"{normalized_filial} - {filial_name}"
    return normalized_filial or str(filial or "").strip()


def _lookup_code_label(search_context: str) -> str:
    return "o codigo do PDV" if search_context == "cliente" else "o NB"


def _sum_money_values(values: list[str] | tuple[str, ...] | Any) -> str:
    total = Decimal("0")
    for value in values:
        numeric = _parse_decimal_text(value)
        if numeric is None:
            continue
        total += numeric
    return f"{total:.2f}".replace(".", ",")


def _format_percent_ratio(numerator: int, denominator: int) -> str:
    base = max(int(denominator or 0), 0)
    value = max(int(numerator or 0), 0)
    if base <= 0:
        return "0,0%"
    ratio = (Decimal(value) * Decimal("100")) / Decimal(base)
    return f"{ratio:.1f}%".replace(".", ",")


def _format_display_date(value: str) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        year, month, day = text.split("-")
        return f"{day}/{month}/{year}"
    return text


def _format_inadimplencia_money(value: Decimal | str | int | float | None) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-"
    if text.upper().startswith("R$"):
        return text
    return _format_currency_brl(value)


def _format_inadimplencia_days_label(value: Decimal | str | int | float | None) -> str:
    amount = _inadimplencia_days_value(value)
    if amount is None:
        return "-"
    return _format_inadimplencia_days_amount(amount)


def _format_inadimplencia_days_amount(amount: Decimal) -> str:
    if amount == amount.to_integral_value():
        days = int(amount)
        return "1 dia" if days == 1 else f"{days} dias"
    formatted = format(amount.normalize(), "f").rstrip("0").rstrip(".")
    return f"{formatted.replace('.', ',')} dias"


def _format_inadimplencia_timing_label(value: Decimal | str | int | float | None) -> str:
    amount = _inadimplencia_days_value(value)
    if amount is None:
        return "-"
    if amount < 0:
        return f"vencido ha {_format_inadimplencia_days_amount(abs(amount))}"
    if amount == 0:
        return "vence hoje"
    return f"vence em {_format_inadimplencia_days_amount(amount)}"


def _inadimplencia_days_value(value: Decimal | str | int | float | None) -> Decimal | None:
    return _parse_decimal_text(value)


def _format_inadimplencia_summary_timing_label(records: list[InadimplenciaRecord]) -> str:
    max_overdue: Decimal | None = None
    nearest_due: Decimal | None = None
    for record in records:
        amount = _inadimplencia_days_value(record.dias)
        if amount is None:
            continue
        if amount < 0:
            overdue_days = abs(amount)
            if max_overdue is None or overdue_days > max_overdue:
                max_overdue = overdue_days
        elif nearest_due is None or amount < nearest_due:
            nearest_due = amount
    if max_overdue is not None:
        return f"Maior atraso: {_format_inadimplencia_days_amount(max_overdue)}"
    if nearest_due is not None:
        return f"Proximo vencimento: {_format_inadimplencia_timing_label(nearest_due)}"
    return "Situacao: -"


def _format_prazo_percent(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return "-"
    if "%" in raw:
        normalized = raw.replace(".", ",")
        if normalized.endswith(",0%"):
            return normalized.replace(",0%", "%")
        return normalized
    amount = _parse_decimal_text(raw)
    if amount is None:
        return raw
    if amount <= Decimal("1"):
        amount *= Decimal("100")
    formatted = f"{amount:.1f}".replace(".", ",")
    if formatted.endswith(",0"):
        formatted = formatted[:-2]
    return f"{formatted}%"


def _format_currency_brl(value: Decimal | str | int | float | None) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return "R$ 0,00"
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    formatted = f"{quantized:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _format_currency_brl_compact(value: Decimal | str | int | float | None) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return "R$ 0,00"
    if abs(amount) >= Decimal("1000000"):
        compact = (amount / Decimal("1000000")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"R$ {str(compact).replace('.', ',')} mi"
    return _format_currency_brl(amount)


def _format_percent_value(value: Decimal | str | int | float | None) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return "0,00%"
    formatted = f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}".replace(".", ",")
    return f"{formatted}%"


def _format_days_count(value: int | str | Decimal | None) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return "0 dias"
    days = int(amount)
    return "1 dia" if days == 1 else f"{days} dias"


def _format_weekly_pedido_value(value: Decimal | str | int | float | None) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return "R$ 0,00"
    weekly_amount = amount / Decimal("4")
    return _format_currency_brl(weekly_amount)


def _format_pedido_quantity_localized(value: Decimal | str | int | float | None) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return "0"
    if amount == amount.to_integral_value():
        return str(int(amount))
    normalized = format(amount.normalize(), "f")
    normalized = normalized.rstrip("0").rstrip(".") or "0"
    return normalized.replace(".", ",")


def _format_entry_pedido_label(entry: PrazoLimiteEntryRecord, *, media_label: str = "Media mensal") -> str:
    pedidos = _parse_decimal_text(getattr(entry, "pedidos", ""))
    if pedidos is None or pedidos <= 0:
        return ""
    faturamento = _parse_decimal_text(getattr(entry, "faturamento_com_pdv", ""))
    if faturamento is None:
        return f"Pedidos: {_format_pedido_quantity_localized(pedidos)}"
    media_mensal = faturamento / pedidos
    return (
        f"Pedidos: {_format_pedido_quantity_localized(pedidos)} | "
        f"{media_label}: {_format_currency_brl(media_mensal)}"
    )


def _summarize_prazo_limite_field(entries: tuple[PrazoLimiteEntryRecord, ...], field_name: str) -> str:
    values: list[str] = []
    for entry in entries:
        raw_value = str(getattr(entry, field_name, "") or "-").strip() or "-"
        value = _format_prazo_percent(raw_value) if field_name == "percentual_pag_atraso" else raw_value
        if value not in values:
            values.append(value)
    if not values:
        return "-"
    if len(values) == 1:
        return values[0]
    detailed_values = []
    for entry in entries:
        raw_value = str(getattr(entry, field_name, "") or "-").strip() or "-"
        value = _format_prazo_percent(raw_value) if field_name == "percentual_pag_atraso" else raw_value
        detailed_values.append(f"{entry.kpi} {value}")
    return " | ".join(detailed_values)


def _format_quantity(value: int | str | Decimal) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return str(value or "0")
    if amount == amount.to_integral_value():
        return str(int(amount))
    normalized = format(amount.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") or "0"


def _format_weight_quantity(value: int | str | Decimal) -> str:
    amount = _parse_decimal_text(value)
    if amount is None:
        return str(value or "0")
    return f"{amount.quantize(Decimal('0.01')):.2f}".replace(".", ",")


def _sum_formatted_amounts(*values: str) -> str:
    total = Decimal("0")
    for value in values:
        numeric = _parse_decimal_text(value)
        if numeric is None:
            continue
        total += numeric
    return _format_quantity(total)


def _is_positive_quantity(value: int | str | Decimal) -> bool:
    amount = _parse_decimal_text(value)
    if amount is None:
        return False
    return amount > 0


def _append_giro_client_block(
    lines: list[str],
    *,
    index: int,
    client_name: str,
    cod_pdv: str,
    total_caixas: str,
    gap_caixas: str,
    gap_detail: str = "",
    setor_code: str = "",
) -> None:
    if lines and lines[-1]:
        lines.append("")
    lines.append(f"{index}) {client_name or '-'} | Cod {cod_pdv or '-'}")
    if setor_code:
        lines.append(f"Setor: {setor_code}")
    lines.append(f"Base: {total_caixas} | Falta: {gap_caixas}")
    if gap_detail:
        lines.append(f"Tipo: {gap_detail}")


def _format_giro_gap_detail(record: GiroClientRecord) -> str:
    gap_parts: list[str] = []
    gap_litrinho = getattr(record, "gap_litrinho", "0")
    gap_inteira = getattr(record, "gap_inteira", "0")
    gap_litrao = getattr(record, "gap_litrao", "0")
    if _is_positive_quantity(gap_litrinho):
        gap_parts.append(f"Litrinho {_format_quantity(gap_litrinho)}")
    if _is_positive_quantity(gap_inteira):
        gap_parts.append(f"Inteira {_format_quantity(gap_inteira)}")
    if _is_positive_quantity(gap_litrao):
        gap_parts.append(f"Litrao {_format_quantity(gap_litrao)}")
    return ", ".join(gap_parts)


def _format_giro_records_gap_detail(records: list[GiroClientRecord]) -> str:
    gap_litrinho = Decimal("0")
    gap_inteira = Decimal("0")
    gap_litrao = Decimal("0")
    for record in records:
        gap_litrinho += _parse_decimal_text(getattr(record, "gap_litrinho", "0")) or Decimal("0")
        gap_inteira += _parse_decimal_text(getattr(record, "gap_inteira", "0")) or Decimal("0")
        gap_litrao += _parse_decimal_text(getattr(record, "gap_litrao", "0")) or Decimal("0")
    parts: list[str] = []
    if gap_litrinho > 0:
        parts.append(f"Litrinho {_format_quantity(gap_litrinho)}")
    if gap_inteira > 0:
        parts.append(f"Inteira {_format_quantity(gap_inteira)}")
    if gap_litrao > 0:
        parts.append(f"Litrao {_format_quantity(gap_litrao)}")
    return " | ".join(parts)


def _format_documentacao_pending_docs(pending_docs: tuple[str, ...] | list[str]) -> str:
    labels = {
        "contrato_social": "Contrato Social",
        "cpf": "Cpf",
        "rg": "Rg",
        "comprovante_residencia": "Comprovante de residencia",
        "fachada": "Fachada",
        "ficha_cadastro": "Ficha de Cadastro",
    }
    formatted: list[str] = []
    seen: set[str] = set()
    for raw_doc in pending_docs:
        normalized = str(raw_doc or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        formatted.append(labels.get(normalized, str(raw_doc).strip()))
    return ", ".join(formatted) if formatted else "-"


def _format_documento_identity(documento: str) -> tuple[str, str]:
    normalized = _normalize_document(str(documento or ""))
    if len(normalized) == 11:
        return (_format_cpf(normalized), "-")
    if len(normalized) == 14:
        return ("-", _format_cnpj(normalized))
    return ("-", "-")


def _format_cpf(value: str) -> str:
    digits = _normalize_document(value)
    if len(digits) != 11:
        return str(value or "-").strip() or "-"
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def _format_cnpj(value: str) -> str:
    digits = _normalize_document(value)
    if len(digits) != 14:
        return str(value or "-").strip() or "-"
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def _scope_last_code(value: str) -> str:
    normalized = normalize_stored_scope_value(str(value or ""))
    pair = split_scope_pair(normalized)
    if pair:
        return pair[1] or "-"
    return normalized or "-"


def _merge_document_status(*values: str) -> str:
    statuses = [str(value or "").strip() for value in values if str(value or "").strip()]
    if not statuses:
        return "-"
    if any(_is_ok_status(value) for value in statuses):
        return "OK"
    if any(value.lower() == "nok" for value in statuses):
        return "Nok"
    return statuses[0]


def _is_ok_status(value: str) -> bool:
    return str(value or "").strip().lower() == "ok"


def _aggregate_giro_scope_summaries(summaries: list[GiroScopeSummary]) -> GiroScopeSummary | None:
    if not summaries:
        return None

    def _sum_int(field_name: str) -> int:
        return sum(int(getattr(summary, field_name) or 0) for summary in summaries)

    def _sum_gap(field_name: str) -> str:
        total = Decimal("0")
        for summary in summaries:
            raw = str(getattr(summary, field_name) or "").strip()
            if not raw:
                continue
            normalized = raw.replace(".", "").replace(",", ".")
            try:
                total += Decimal(normalized)
            except (InvalidOperation, ValueError):
                continue
        return _format_quantity(total)

    planilha_atualizada_em = next(
        (summary.planilha_atualizada_em for summary in summaries if summary.planilha_atualizada_em and summary.planilha_atualizada_em != "-"),
        "-",
    )
    return GiroScopeSummary(
        client_count=_sum_int("client_count"),
        attention_count=_sum_int("attention_count"),
        zero_count=_sum_int("zero_count"),
        litrinho_monitored_count=_sum_int("litrinho_monitored_count"),
        litrinho_ok_count=_sum_int("litrinho_ok_count"),
        litrinho_nok_count=_sum_int("litrinho_nok_count"),
        litrinho_zero_count=_sum_int("litrinho_zero_count"),
        litrinho_gap_total=_sum_gap("litrinho_gap_total"),
        inteira_monitored_count=_sum_int("inteira_monitored_count"),
        inteira_ok_count=_sum_int("inteira_ok_count"),
        inteira_nok_count=_sum_int("inteira_nok_count"),
        inteira_zero_count=_sum_int("inteira_zero_count"),
        inteira_gap_total=_sum_gap("inteira_gap_total"),
        litrao_monitored_count=_sum_int("litrao_monitored_count"),
        litrao_ok_count=_sum_int("litrao_ok_count"),
        litrao_nok_count=_sum_int("litrao_nok_count"),
        litrao_zero_count=_sum_int("litrao_zero_count"),
        litrao_gap_total=_sum_gap("litrao_gap_total"),
        planilha_atualizada_em=planilha_atualizada_em,
    )


def _money_sort_key(value: str) -> Decimal:
    amount = _parse_decimal_text(value)
    if amount is None:
        return Decimal("0")
    return amount


def _parse_decimal_text(value: int | float | str | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    raw = str(value).strip()
    if not raw:
        return None

    cleaned = (
        raw.replace("R$", "")
        .replace("r$", "")
        .replace("%", "")
        .replace(" ", "")
        .replace("+", "")
    )
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _build_filial_prompt(search_context: str) -> str:
    code_label = "codigo do PDV" if search_context == "cliente" else "NB"
    intro_map = {
        "cliente": "Informe a revenda/filial do cliente.",
        "inadimplencia": "Informe a revenda/filial para consultar a inadimplencia.",
        "comodato": "Informe a revenda/filial para consultar os comodatos.",
        "giro": "Informe a revenda/filial para consultar o giro.",
        "documentacao": "Informe a revenda/filial para consultar a documentacao pendente.",
        "prazo_limite": "Informe a revenda/filial para consultar prazo e limite.",
    }
    lines = [
        intro_map.get(search_context, "Informe a revenda/filial do cliente."),
        f"Se quiser ser mais rapido, pode mandar filial e {code_label} juntos.",
        "Exemplo: 3 6643",
        "",
    ]
    for filial_code in sorted(FILIAL_LABELS, key=int):
        lines.append(f"{filial_code} - {FILIAL_LABELS[filial_code]}")
    return "\n".join(lines)
