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
from bot_api.services.flows.critica_flow import CriticaFlow
from bot_api.services.flows.finance_flow import FinanceFlow
from bot_api.services.prazo_limite_query_service import (
    PrazoLimiteClientRecord,
    PrazoLimiteEntryRecord,
    PrazoLimiteQueryService,
)
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
MENU_VISIT_DAY = "menu:visitas_do_dia"
MENU_FINANCEIRO = "menu:financeiro"
MENU_GV_SUMMARY = "menu:gv_summary"
MENU_MANAGER = "menu:gerente_vendas"
MENU_SELLER_SUMMARY = "menu:seller_summary"
MENU_SELLER_RISK = "menu:seller_risk"
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
PAYIP_ACTION_STATEMENT = "payip:action:statement"
PAYIP_ACTION_AMOUNT_DAY = "payip:action:amount_day"
REPEAT_SEARCH_REGISTRATION = "repeat:search:registration"
REPEAT_SEARCH_DOCUMENT = "repeat:search:document"
REPEAT_SEARCH_NAME = "repeat:search:name"
REPEAT_PAYIP_INVOICE = "repeat:payip:invoice"
REPEAT_PAYIP_PENDING_CLIENT = "repeat:payip:pending_client"
REPEAT_PAYIP_CLIENT = "repeat:payip:client"
REPEAT_PAYIP_CREATE_CHARGE = "repeat:payip:create_charge"
REPEAT_PAYIP_STATEMENT = "repeat:payip:statement"
REPEAT_PAYIP_AMOUNT_DAY = "repeat:payip:amount_day"

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

FILIAL_LABELS = {
    "1": "Sousa",
    "2": "Itaporanga",
    "3": "Patos",
    "4": "Sume",
    "5": "Guarabira",
    "6": "Brumado",
    "7": "Barra",
    "8": "Cacule",
}
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
        self.finance_flow = FinanceFlow(self)
        self.critica_flow = CriticaFlow(self)

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
        expired_session = self._peek_expired_session(incoming.sender)
        self._cleanup_sessions()

        session = self.sessions.get(incoming.sender, LookupSession())
        session.updated_at = datetime.now(timezone.utc)

        text = (incoming.text or "").strip()
        normalized = _normalize_choice(text)

        if normalized in {"menu", "inicio", "iniciar", "start", "oi", "ola"}:
            self._reset_session(incoming.sender)
            return self._build_main_menu(decision)

        if normalized in {"voltar", "cancelar", "sair"}:
            self._reset_session(incoming.sender)
            return self._build_main_menu(decision)

        if expired_session is not None and _looks_like_contextual_follow_up(normalized):
            return self._build_expired_session_prompt(previous_step=expired_session.step)

        if session.step.startswith("admin_"):
            return self._handle_admin_session(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if session.step.startswith("recolha_"):
            return self._handle_recolha_session(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if session.step.startswith("finance_"):
            return self.finance_flow.handle_session(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if session.step == "awaiting_critica_action":
            readiness_error = self.critica_flow.ensure_ready(decision)
            if readiness_error is not None:
                return readiness_error
            selected_option = _select_interactive_option(
                text=text,
                normalized=normalized,
                options=_build_critica_menu_response().options,
            )
            if selected_option is not None:
                return self.critica_flow.handle_command(
                    sender=incoming.sender,
                    session=session,
                    text=selected_option.option_id,
                    normalized=_normalize_choice(selected_option.option_id),
                    decision=decision,
                )
            if _looks_like_critica_command(normalized):
                return self.critica_flow.handle_command(
                    sender=incoming.sender,
                    session=session,
                    text=text,
                    normalized=normalized,
                    decision=decision,
                )
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            menu = _build_critica_menu_response()
            return OutgoingMessage(
                kind=menu.kind,
                title=menu.title,
                text=f"Nao entendi essa opcao.\n\n{menu.text}",
                footer=menu.footer,
                button_text=menu.button_text,
                options=menu.options,
            )

        if session.step == "awaiting_intent_clarification":
            selected_option = _select_interactive_option(
                text=text,
                normalized=normalized,
                options=session.clarification_options,
            )
            if selected_option is None:
                self.sessions[incoming.sender] = session
                return self._build_intent_clarification_menu(session=session, invalid_selection=True)
            return self._run_intent_clarification_option(
                sender=incoming.sender,
                session=session,
                decision=decision,
                option_id=selected_option.option_id,
            )

        if _is_back_menu_command(normalized):
            if session.step == "awaiting_post_result_navigation":
                resumed_response = self._resume_post_result_navigation(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
                if resumed_response is not None:
                    return resumed_response
            back_response = self._handle_menu_back_navigation(
                sender=incoming.sender,
                session=session,
                decision=decision,
            )
            if back_response is not None:
                return back_response

        if session.step == "awaiting_post_result_navigation" and normalized:
            if _is_repeat_query_command(normalized):
                return self._repeat_post_result_navigation(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            payip_pix_selection = _parse_payip_pix_selection(normalized)
            if payip_pix_selection is not None and session.payip_pix_payloads:
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return _build_payip_pix_code_response(
                    session.payip_pix_payloads,
                    selection=payip_pix_selection,
                    payip_payments_service=self.payip_payments_service,
                )
            if _looks_like_critica_command(normalized):
                return self.critica_flow.handle_command(
                    sender=incoming.sender,
                    session=session,
                    text=text,
                    normalized=normalized,
                    decision=decision,
                )
            if self._can_update_recolhas(decision) and _looks_like_recolha_update_request(normalized):
                update_request = _parse_recolha_finance_update_request(text=text, normalized=normalized)
                if update_request is not None:
                    identifier, updates = update_request
                    return self._build_recolha_update_response(
                        self._update_recolha_for_decision(
                            identifier=identifier,
                            updates=updates,
                            sender=incoming.sender,
                            decision=decision,
                        ),
                        identifier=identifier,
                    )
            if _looks_like_recolha_request(normalized):
                management_request = _parse_recolha_management_request(normalized)
                if management_request is not None:
                    action, identifier = management_request
                    if action == "clear" and not self._can_clear_recolhas(decision):
                        return OutgoingMessage(
                            text="A limpeza geral de recolhas esta liberada apenas para admin, gerencia, diretoria ou financeiro sem restricao de filial."
                        )
                    if action == "clear":
                        return self._open_recolha_clear_confirmation(sender=incoming.sender, session=session)
                    if not self._can_view_recolhas(decision):
                        return OutgoingMessage(
                            text="Voce nao tem acesso ao gerenciamento de recolhas."
                        )
                    return self._open_recolha_delete_confirmation(
                        sender=incoming.sender,
                        session=session,
                        identifier=identifier,
                        decision=decision,
                    )
                if self._can_update_recolhas(decision):
                    update_request = _parse_recolha_finance_update_request(text=text, normalized=normalized)
                    if update_request is not None:
                        identifier, updates = update_request
                        return self._build_recolha_update_response(
                            self._update_recolha_for_decision(
                                identifier=identifier,
                                updates=updates,
                                sender=incoming.sender,
                                decision=decision,
                            ),
                            identifier=identifier,
                        )
                if self._can_view_recolhas(decision) and _looks_like_recolha_list_request(normalized):
                    return self._with_post_result_navigation(
                        incoming.sender,
                        session,
                        self._build_recolhas_finance_response(
                            request_text=normalized,
                            sender=incoming.sender,
                            decision=decision,
                        ),
                        return_menu="main",
                    )
                if not self._can_request_recolha(decision):
                    return OutgoingMessage(
                        text=(
                            "A solicitacao de recolha esta liberada para vendedor e financeiro.\n"
                            "Se voce for do financeiro, envie RECOLHAS para ver as solicitacoes."
                        )
                    )
                return self._open_recolha_request(
                    sender=incoming.sender,
                    session=session,
                    text=text,
                    normalized=normalized,
                    decision=decision,
                )
            self.sessions[incoming.sender] = session
            return OutgoingMessage(
                text=(
                    "Para continuar desse ponto, envie A ou ANT.\n"
                    "Para copiar um PIX retornado pela PayIP e receber o PDF, envie PIX 1.\n"
                    "Se preferir voltar ao inicio, envie MENU."
                )
            )

        if session.step == "awaiting_search_mode":
            readiness_error = self._ensure_search_context_ready(session.search_context, decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            conversational_response = self._maybe_handle_search_mode_conversation(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )
            if conversational_response is not None:
                return conversational_response
            selected_option = _select_interactive_option(
                text=text,
                normalized=normalized,
                options=self._build_search_menu(
                    search_context=session.search_context,
                    decision=decision,
                ).options,
            )
            if selected_option is not None:
                return self._run_search_menu_option(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                    option_id=selected_option.option_id,
                )
            if normalized in {
                SEARCH_BY_REGISTRATION,
                "1",
                "filial",
                "cadastro",
                "filial e cod pdv",
                "filial e codigo pdv",
                "filial e nb",
                "nb",
            }:
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                session.step = "awaiting_filial"
                session.filial = ""
                session.fantasia_query = ""
                session.fantasia_results = ()
                session.inadimplencia_client_summaries = ()
                session.inadimplencia_total_available = 0
                session.inadimplencia_list_context = ""
                session.inadimplencia_page = 1
                session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
                session.comodato_client_summaries = ()
                session.selected_visit_day = ""
                session.visit_day_options = ()
                session.visit_seller_summaries = ()
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return OutgoingMessage(text=_build_filial_prompt(session.search_context))
            if normalized in {
                SEARCH_BY_FANTASIA,
                "2",
                "fantasia",
                "nome fantasia",
                "nome_fantasia",
            }:
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                session.step = "awaiting_fantasia"
                session.filial = ""
                session.fantasia_query = ""
                session.fantasia_results = ()
                session.inadimplencia_client_summaries = ()
                session.inadimplencia_total_available = 0
                session.inadimplencia_list_context = ""
                session.inadimplencia_page = 1
                session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
                session.comodato_client_summaries = ()
                session.selected_visit_day = ""
                session.visit_day_options = ()
                session.visit_seller_summaries = ()
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                if session.search_context == "inadimplencia":
                    return OutgoingMessage(text="Digite parte do nome do cliente para ver os titulos em aberto.")
                if session.search_context == "comodato":
                    return OutgoingMessage(text="Digite parte do nome do cliente para ver os comodatos pendentes.")
                if session.search_context == "giro":
                    return OutgoingMessage(text="Digite parte do nome do cliente para ver os dados de giro.")
                if session.search_context == "documentacao":
                    return OutgoingMessage(text="Digite parte do nome do cliente para ver a documentacao pendente.")
                if session.search_context == "prazo_limite":
                    return OutgoingMessage(text="Digite parte do nome do cliente para consultar prazo e limite.")
                return OutgoingMessage(
                    text=(
                        "Digite parte do nome do cliente.\n"
                        "Vou procurar e mostrar uma lista para voce escolher."
                    )
                )
            if normalized in {
                SEARCH_BY_DOCUMENT,
                "3",
                "cpf",
                "cnpj",
                "cpf cnpj",
                "cpf/cnpj",
                "documento",
            }:
                access_error = None
                if session.search_context in {"inadimplencia", "comodato", "documentacao", "prazo_limite"}:
                    access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                session.step = "awaiting_document"
                session.filial = ""
                session.fantasia_query = ""
                session.fantasia_results = ()
                session.inadimplencia_client_summaries = ()
                session.inadimplencia_total_available = 0
                session.inadimplencia_list_context = ""
                session.inadimplencia_page = 1
                session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
                session.comodato_client_summaries = ()
                session.selected_visit_day = ""
                session.visit_day_options = ()
                session.visit_seller_summaries = ()
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                if session.search_context == "inadimplencia":
                    return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar a inadimplencia.")
                if session.search_context == "comodato":
                    return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar os comodatos pendentes.")
                if session.search_context == "giro":
                    return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar o giro.")
                if session.search_context == "documentacao":
                    return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar a documentacao pendente.")
                if session.search_context == "prazo_limite":
                    return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar prazo e limite.")
                return OutgoingMessage(
                    text=(
                        "Digite o CPF ou CNPJ do cliente.\n"
                        "Vou buscar pelo documento cadastrado, sem limitar por setor."
                    )
                )
            if session.search_context == "giro" and normalized in {
                SEARCH_BY_VISIT_DAY,
                "4",
                "resumo por dia",
                "dia de visita",
                "visita",
                "rota",
                "oportunidade do giro",
                "giro por dia",
                "clientes com caixa",
                "clientes com caixa do dia",
                "giro cliente por cliente",
                "giro clientes do dia",
            }:
                return self._open_giro_visit_day_conversation(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            if session.search_context == "giro" and normalized in {
                SEARCH_BY_GIRO_ZERO_BASE,
                "5",
                "giro zero",
                "giro zero da base",
                "clientes com giro zero",
                "mostrar giro zero",
                "ver giro zero",
            }:
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_giro_zero_base_response(decision),
                    return_menu="search_menu",
                )
            if session.search_context == "documentacao" and normalized in {
                SEARCH_BY_VISIT_DAY,
                "4",
                "documentacao por dia",
                "documentacao do dia",
                "pendencia por dia",
                "documentos por dia",
                "documentacao segunda",
                "documentacao terca",
                "documentacao quarta",
                "documentacao quinta",
                "documentacao sexta",
                "documentacao sabado",
                "documentacao domingo",
            }:
                return self._open_documentacao_visit_day_conversation(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            if session.search_context == "inadimplencia" and normalized in {
                SEARCH_BY_INADIMPLENTES_BASE,
                "inadimplentes da base",
                "mostrar inadimplentes",
                "ver inadimplentes",
                "lista de inadimplentes",
            }:
                access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                return self._open_inadimplencia_summary_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                    order_by="total_pendente",
                    header_text=f"Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.",
                    empty_text=(
                        "No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\n"
                        "Se quiser tentar outra consulta, envie MENU."
                    ),
                    page=1,
                    page_size=INADIMPLENCIA_PAGE_SIZE,
                    list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
                )
            if session.search_context == "inadimplencia":
                due_bucket = _parse_finance_due_bucket(normalized)
                if due_bucket in {"tomorrow", "in_two_days"}:
                    return self._run_scoped_inadimplencia_due_bucket(
                        sender=incoming.sender,
                        session=session,
                        decision=decision,
                        due_bucket=due_bucket,
                    )
            self.sessions[incoming.sender] = session
            return self._build_search_menu(
                search_context=session.search_context,
                decision=decision,
                invalid_selection=True,
            )

        if session.step == "idle" and self._can_update_recolhas(decision) and _looks_like_recolha_update_request(normalized):
            update_request = _parse_recolha_finance_update_request(text=text, normalized=normalized)
            if update_request is not None:
                identifier, updates = update_request
                return self._build_recolha_update_response(
                    self._update_recolha_for_decision(
                        identifier=identifier,
                        updates=updates,
                        sender=incoming.sender,
                        decision=decision,
                    ),
                    identifier=identifier,
                )

        if session.step == "idle" and _looks_like_recolha_request(normalized):
            management_request = _parse_recolha_management_request(normalized)
            if management_request is not None:
                action, identifier = management_request
                if action == "clear" and not self._can_clear_recolhas(decision):
                    return OutgoingMessage(
                        text=(
                            "A limpeza geral de recolhas esta liberada apenas para admin, gerencia, diretoria ou financeiro sem restricao de filial."
                        )
                    )
                if action == "clear":
                    return self._open_recolha_clear_confirmation(sender=incoming.sender, session=session)
                if not self._can_view_recolhas(decision):
                    return OutgoingMessage(
                        text="Voce nao tem acesso ao gerenciamento de recolhas."
                    )
                return self._open_recolha_delete_confirmation(
                    sender=incoming.sender,
                    session=session,
                    identifier=identifier,
                    decision=decision,
                )
            if self._can_update_recolhas(decision):
                update_request = _parse_recolha_finance_update_request(text=text, normalized=normalized)
                if update_request is not None:
                    identifier, updates = update_request
                    return self._build_recolha_update_response(
                        self._update_recolha_for_decision(
                            identifier=identifier,
                            updates=updates,
                            sender=incoming.sender,
                            decision=decision,
                        ),
                        identifier=identifier,
                    )
            if self._can_view_recolhas(decision) and _looks_like_recolha_list_request(normalized):
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_recolhas_finance_response(
                        request_text=normalized,
                        sender=incoming.sender,
                        decision=decision,
                    ),
                    return_menu="main",
                )
            if not self._can_request_recolha(decision):
                return OutgoingMessage(
                    text=(
                        "A solicitacao de recolha esta liberada para vendedor e financeiro.\n"
                        "Se voce for do financeiro, envie RECOLHAS para ver as solicitacoes."
                    )
                )
            return self._open_recolha_request(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if _looks_like_critica_command(normalized):
            return self.critica_flow.handle_command(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        conversational_response = self._maybe_handle_idle_conversation(
            sender=incoming.sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )
        if conversational_response is not None:
            return conversational_response

        if session.step == "idle" and self._is_vendedor(decision):
            selected_main_option = _select_interactive_option(
                text=text,
                normalized=normalized,
                options=self._build_main_menu(decision).options,
            )
            if selected_main_option is not None:
                return self._run_intent_clarification_option(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                    option_id=selected_main_option.option_id,
                )

        main_menu_shortcuts = self._main_menu_shortcuts(decision)
        summary_option_id = self._main_menu_summary_option_id(decision)
        search_shortcut = main_menu_shortcuts.get(MENU_SEARCH, "")
        inadimplencia_shortcut = main_menu_shortcuts.get(MENU_INADIMPLENCIA, "")
        giro_shortcut = main_menu_shortcuts.get(MENU_GIRO, "")
        documentacao_shortcut = main_menu_shortcuts.get(MENU_DOCUMENTACAO, "")
        recolha_shortcut = main_menu_shortcuts.get(MENU_RECOLHA, "")
        visit_day_shortcut = main_menu_shortcuts.get(MENU_VISIT_DAY, "")
        comodatos_shortcut = main_menu_shortcuts.get(MENU_COMODATOS, "")
        summary_shortcut = main_menu_shortcuts.get(summary_option_id, "") if summary_option_id else ""
        seller_summary_shortcut = main_menu_shortcuts.get(MENU_SELLER_SUMMARY, "")
        seller_risk_shortcut = main_menu_shortcuts.get(MENU_SELLER_RISK, "")
        financeiro_shortcut = main_menu_shortcuts.get(MENU_FINANCEIRO, "")
        admin_shortcut = main_menu_shortcuts.get(MENU_ADMIN_ACCESS, "")

        if normalized == MENU_INADIMPLENCIA or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    inadimplencia_shortcut,
                    "inadimplencia",
                    "inadimpl?ncia",
                    "inadimplente",
                    "devedor",
                    "cobranca",
                    "cobranca da carteira",
                    "cobranca da gerencia",
                    "cobran?a",
                }
                if value
            }
        ):
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = "awaiting_search_mode"
            session.search_context = "inadimplencia"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(
                session,
                intent="search_inadimplencia",
                search_context="inadimplencia",
            )
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="inadimplencia", decision=decision)

        if normalized == MENU_GIRO or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {giro_shortcut, "giro", "menu giro", "consultar giro", "giro da gerencia"}
                if value
            }
        ):
            readiness_error = self._ensure_search_context_ready("giro", decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = "awaiting_search_mode"
            session.search_context = "giro"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(
                session,
                intent="search_giro",
                search_context="giro",
            )
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="giro", decision=decision)

        if normalized == MENU_DOCUMENTACAO or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    documentacao_shortcut,
                    "documentacao",
                    "documentacao pendente",
                    "documentos pendentes",
                    "pendencia documental",
                    "documentos faltando",
                }
                if value
            }
        ):
            readiness_error = self._ensure_search_context_ready("documentacao", decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = "awaiting_search_mode"
            session.search_context = "documentacao"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(
                session,
                intent="search_documentacao",
                search_context="documentacao",
            )
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="documentacao", decision=decision)

        if normalized == MENU_RECOLHA or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    recolha_shortcut,
                    "recolha",
                    "recolhas",
                    "solicitar recolha",
                    "solicitacao de recolha",
                    "pedido de recolha",
                }
                if value
            }
        ):
            management_request = _parse_recolha_management_request(normalized)
            if management_request is not None:
                action, identifier = management_request
                if action == "clear" and not self._can_clear_recolhas(decision):
                    return OutgoingMessage(
                        text=(
                            "A limpeza geral de recolhas esta liberada apenas para admin, gerencia, diretoria ou financeiro sem restricao de filial."
                        )
                    )
                if action == "clear":
                    return self._open_recolha_clear_confirmation(sender=incoming.sender, session=session)
                if not self._can_view_recolhas(decision):
                    return OutgoingMessage(
                        text="Voce nao tem acesso ao gerenciamento de recolhas."
                    )
                return self._open_recolha_delete_confirmation(
                    sender=incoming.sender,
                    session=session,
                    identifier=identifier,
                    decision=decision,
                )
            if self._can_view_recolhas(decision) and _looks_like_recolha_list_request(normalized):
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_recolhas_finance_response(
                        request_text=normalized,
                        sender=incoming.sender,
                        decision=decision,
                    ),
                    return_menu="main",
                )
            if not self._can_request_recolha(decision):
                return OutgoingMessage(
                    text=(
                        "A solicitacao de recolha esta liberada para vendedor e financeiro.\n"
                        "Se voce for do financeiro, envie RECOLHAS para ver as solicitacoes."
                    )
                )
            return self._open_recolha_request(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if normalized == MENU_FINANCEIRO or (
            session.step == "idle"
            and normalized in {value for value in {financeiro_shortcut, "financeiro", "financeiro menu", "menu financeiro"} if value}
            and self._can_use_finance_menu(decision)
        ):
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = "finance_select_action"
            session.search_context = "inadimplencia"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            session.finance_gv_options = ()
            session.summary_filial_options = ()
            session.visit_risk_day_options = ()
            session.visit_risk_summaries = ()
            session.selected_visit_risk_token = ""
            session.selected_visit_risk_label = ""
            self._remember_last_context(
                session,
                intent="finance_menu",
                search_context="inadimplencia",
            )
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_finance_menu()

        if normalized == MENU_VISIT_DAY or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    visit_day_shortcut,
                    "visitas do dia",
                    "rota do dia",
                    "rota",
                    "visitas",
                    "dia de visita",
                    "dia de visita do vde",
                }
                if value
            }
            and self._can_use_visit_menu(decision)
        ):
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
            visit_days = _normalize_visit_day_menu_values(raw_visit_days)
            if not visit_days:
                self._reset_session(incoming.sender)
                return OutgoingMessage(
                    text=(
                        "Nao encontrei dias de visita disponiveis para voce no momento.\n"
                        "Se quiser fazer outra consulta, envie MENU."
                    )
                )
            session.step = "awaiting_visit_day_selection"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.comodato_client_summaries = ()
            session.selected_visit_day = ""
            session.visit_day_options = tuple(visit_days)
            session.visit_seller_summaries = ()
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)

        if normalized in {MENU_GV_SUMMARY, MENU_MANAGER} or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    summary_shortcut,
                    "gerencia",
                    "menu gerencia",
                    "painel da gerencia",
                    "painel gerencia",
                    "gerente de vendas",
                    "menu gerente",
                    "resumo do gv",
                    "resumo gv",
                    "meu gv",
                    "meu resumo",
                    "resumo da gerencia",
                    "resumo dos gerentes",
                    "gerentes de vendas",
                }
                if value
            }
            and self._can_use_gv_summary_menu(decision)
        ):
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            if self._is_gerente_vendas(decision):
                return self._open_manager_summary_menu(
                    sender=incoming.sender,
                    session=session,
                )
            if self._is_diretor_comercial(decision):
                return self._open_director_summary_menu(
                    sender=incoming.sender,
                    session=session,
                )
            self._reset_session(incoming.sender)
            return self._build_gv_summary_response(
                decision,
                title="Resumo da Gerencia",
            )

        if normalized == MENU_SELLER_SUMMARY or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    seller_summary_shortcut,
                    "carteira",
                    "resumo da carteira",
                    "resumo carteira",
                    "minha carteira",
                    "meu resumo",
                }
                if value
            }
            and self._can_use_seller_summary_menu(decision)
        ):
            access_error = self._ensure_scoped_lookup_access(decision, search_context="cliente")
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_seller_summary_response(decision),
                return_menu="main",
            )

        if normalized == MENU_SELLER_RISK or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    seller_risk_shortcut,
                    "risco da rota",
                    "risco da carteira",
                    "clientes com risco hoje",
                    "risco hoje",
                    "rota com risco",
                    "clientes da rota com risco",
                }
                if value
            }
            and self._can_use_seller_risk_menu(decision)
        ):
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_seller_risk_response(decision),
                return_menu="main",
            )

        if normalized == MENU_COMODATOS or (
            session.step == "idle"
            and normalized
            in {
                value
                for value in {
                    comodatos_shortcut,
                    "comodato",
                    "comodatos",
                    "pendencia de comodato",
                    "pendencias de comodato",
                }
                if value
            }
        ):
            readiness_error = self._ensure_search_context_ready("comodato", decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = "awaiting_search_mode"
            session.search_context = "comodato"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(
                session,
                intent="search_comodato",
                search_context="comodato",
            )
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="comodato", decision=decision)

        if normalized == MENU_ADMIN_ACCESS or (
            session.step == "idle"
            and normalized in {value for value in {admin_shortcut, "0", "admin", "administrador", "cadastro_usuario"} if value}
        ):
            if not self._is_admin(decision):
                return OutgoingMessage(
                    text=(
                        "Essa opcao esta disponivel apenas para administradores.\n"
                        "Se quiser, envie MENU para voltar."
                    )
                )
            if not self.access_control.enabled:
                return OutgoingMessage(
                    text="No momento, o cadastro de usuarios pelo WhatsApp nao esta disponivel."
                )
            session = LookupSession(step="admin_select_action")
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_admin_action_menu()

        if session.step in {
            "awaiting_filial",
            "awaiting_cod_pdv",
            "awaiting_fantasia",
            "awaiting_fantasia_selection",
            "awaiting_inadimplencia_client_selection",
            "awaiting_comodato_client_selection",
            "awaiting_visit_day_selection",
            "visit_select_gv",
            "awaiting_giro_visit_day_selection",
            "awaiting_visit_seller_selection",
        }:
            access_error = None
            if session.step in {"awaiting_visit_day_selection", "visit_select_gv", "awaiting_visit_seller_selection"}:
                access_error = self._ensure_scoped_lookup_access(decision, search_context="cliente")
            elif session.search_context in {"inadimplencia", "comodato"} or session.step != "awaiting_fantasia_selection":
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error

        if session.step == "awaiting_document":
            readiness_error = self._ensure_search_context_ready(session.search_context, decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error

        if session.step == "awaiting_filial":
            direct_lookup = _parse_direct_registration_lookup(text)
            if direct_lookup is not None:
                return self._run_repeatable_registration_lookup(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                    search_context=session.search_context,
                    filial=direct_lookup[0],
                    cod_pdv=direct_lookup[1],
                )
            filial = _normalize_filial(text)
            if not filial:
                self.sessions[incoming.sender] = session
                return OutgoingMessage(text=f"Nao reconheci essa filial.\n{_build_filial_prompt(session.search_context)}")
            session.step = "awaiting_cod_pdv"
            session.filial = filial
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return OutgoingMessage(
                text=(
                    f"Perfeito. Voce escolheu a revenda {_format_filial_label(filial)}.\n"
                    f"Agora me envie {_lookup_code_label(session.search_context)}. "
                    "Se preferir, pode mandar assim: 3 6643."
                )
            )

        if session.step == "awaiting_cod_pdv":
            direct_lookup = _parse_direct_registration_lookup(text)
            if direct_lookup is not None:
                return self._run_repeatable_registration_lookup(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                    search_context=session.search_context,
                    filial=direct_lookup[0],
                    cod_pdv=direct_lookup[1],
                )
            cod_pdv = _normalize_cod_pdv(text)
            if not cod_pdv:
                self.sessions[incoming.sender] = session
                return OutgoingMessage(
                    text=f"Me envie {_lookup_code_label(session.search_context)} ou os dois juntos, por exemplo: 3 6643."
                )
            return self._run_repeatable_registration_lookup(
                sender=incoming.sender,
                session=session,
                decision=decision,
                search_context=session.search_context,
                filial=session.filial,
                cod_pdv=cod_pdv,
            )

        if session.step == "awaiting_fantasia":
            return self._run_name_search(
                sender=incoming.sender,
                session=session,
                decision=decision,
                query_text=text,
            )

        if session.step == "awaiting_fantasia_selection":
            selected_record = _select_fantasia_record(text=text, normalized=normalized, records=session.fantasia_results)
            if selected_record is None:
                self.sessions[incoming.sender] = session
                return self._build_fantasia_results_menu(
                    query_text=session.fantasia_query,
                    records=list(session.fantasia_results),
                    search_context=session.search_context,
                    invalid_selection=True,
                )
            self._remember_last_context(
                session,
                intent=f"{session.search_context}_client",
                search_context=session.search_context,
                query_text=session.fantasia_query,
                client_filial=selected_record.filial,
                client_cod_pdv=selected_record.cod_pdv,
                client_name=selected_record.nome_fantasia or selected_record.razao_social,
            )
            if session.search_context == "giro":
                records = self.giro_service.search_by_registration(
                    filial=selected_record.filial,
                    cod_pdv=selected_record.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                criteria = (
                    f"nome fantasia contendo '{session.fantasia_query}'"
                    f" | revenda {selected_record.filial} | NB {selected_record.cod_pdv}"
                )
                if not records:
                    historical_response = self._build_giro_historical_fallback_response(
                        decision=decision,
                        filial=selected_record.filial,
                        cod_pdv=selected_record.cod_pdv,
                        criteria=criteria,
                    )
                    if historical_response is not None:
                        return self._with_post_result_navigation(
                            incoming.sender,
                            session,
                            historical_response,
                            return_menu="search_results",
                        )
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_giro_response(
                        records,
                        criteria=criteria,
                        scope_restricted=not self._has_unrestricted_lookup_access(decision),
                    ),
                    return_menu="search_results",
                )
            if session.search_context == "documentacao":
                records = self.documentacao_pendente_service.search_by_registration(
                    filial=selected_record.filial,
                    cod_pdv=selected_record.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_documentacao_pendente_response(
                        records,
                        criteria=(
                            f"nome fantasia contendo '{session.fantasia_query}'"
                            f" | revenda {selected_record.filial} | NB {selected_record.cod_pdv}"
                        ),
                        scope_restricted=not self._has_unrestricted_lookup_access(decision),
                    ),
                    return_menu="search_results",
                )
            if session.search_context == "prazo_limite":
                records = self.prazo_limite_service.search_by_registration(
                    filial=selected_record.filial,
                    cod_pdv=selected_record.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_prazo_limite_response(
                        records,
                        criteria=(
                            f"nome fantasia contendo '{session.fantasia_query}'"
                            f" | revenda {selected_record.filial} | NB {selected_record.cod_pdv}"
                        ),
                        decision=decision,
                        scope_restricted=not self._has_unrestricted_lookup_access(decision),
                    ),
                    return_menu="search_results",
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_single_record_response(
                    record=selected_record,
                    criteria=f"nome fantasia contendo '{session.fantasia_query}'",
                    decision=decision,
                ),
                return_menu="search_results",
            )

        if session.step == "awaiting_inadimplencia_client_selection":
            page_action = _parse_inadimplencia_page_action(normalized, session.inadimplencia_page_size)
            if session.inadimplencia_list_context in {
                INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL,
                INADIMPLENCIA_CONTEXT_SCOPE_BASE,
                INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS,
            } and page_action:
                total_pages = _compute_page_count(
                    total_items=session.inadimplencia_total_available,
                    page_size=session.inadimplencia_page_size,
                )
                target_page = session.inadimplencia_page
                if page_action == "next":
                    target_page = min(session.inadimplencia_page + 1, total_pages)
                elif page_action == "prev":
                    target_page = max(session.inadimplencia_page - 1, 1)

                if target_page != session.inadimplencia_page:
                    if session.inadimplencia_list_context == INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL:
                        header_text = _extract_inadimplencia_custom_header(session.fantasia_query) or "Esses sao os clientes inadimplentes da base total."
                        empty_text = (
                            "No momento, nao encontrei clientes inadimplentes na base total.\n"
                            "Escolha outra opcao ou envie MENU."
                        )
                    elif session.inadimplencia_list_context == INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS:
                        header_text = _extract_inadimplencia_custom_header(session.fantasia_query) or "Esses sao os maiores devedores da sua diretoria."
                        empty_text = (
                            "No momento, nao encontrei clientes inadimplentes na sua diretoria.\n"
                            "Escolha outra opcao ou envie MENU."
                        )
                    else:
                        scope_label = _extract_inadimplencia_scope_label(session.fantasia_query) or self._inadimplencia_scope_label(decision)
                        header_text = _extract_inadimplencia_custom_header(session.fantasia_query) or f"Esses sao os clientes inadimplentes da {scope_label}."
                        empty_text = (
                            "No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\n"
                            "Escolha outra opcao ou envie MENU."
                        )
                    return self._open_inadimplencia_summary_selection(
                        sender=incoming.sender,
                        session=session,
                        decision=decision,
                        order_by="total_pendente",
                        header_text=header_text,
                        empty_text=empty_text,
                        page=target_page,
                        page_size=session.inadimplencia_page_size,
                        list_context=session.inadimplencia_list_context,
                        known_total_clients=session.inadimplencia_total_available,
                    )
                navigation_notice = (
                    "Voce ja esta na ultima pagina."
                    if page_action == "next"
                    else "Voce ja esta na primeira pagina."
                )
                self.sessions[incoming.sender] = session
                return self._build_inadimplencia_client_menu(
                    query_text=session.fantasia_query,
                    summaries=list(session.inadimplencia_client_summaries),
                    total_available=session.inadimplencia_total_available,
                    page=session.inadimplencia_page if session.inadimplencia_list_context else None,
                    page_size=session.inadimplencia_page_size,
                    list_context=session.inadimplencia_list_context,
                    navigation_notice=navigation_notice,
                )

            selected_summary = _select_inadimplencia_client_summary(
                text=text,
                normalized=normalized,
                summaries=session.inadimplencia_client_summaries,
            )
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_inadimplencia_client_menu(
                    query_text=session.fantasia_query,
                    summaries=list(session.inadimplencia_client_summaries),
                    total_available=session.inadimplencia_total_available,
                    page=session.inadimplencia_page if session.inadimplencia_list_context else None,
                    page_size=session.inadimplencia_page_size,
                    list_context=session.inadimplencia_list_context,
                    invalid_selection=True,
                )
            self._remember_last_context(
                session,
                intent="inadimplencia_client",
                search_context="inadimplencia",
                query_text=session.fantasia_query,
                client_filial=selected_summary.filial,
                client_cod_pdv=selected_summary.cod_pdv,
                client_name=selected_summary.nome,
            )
            records = self.inadimplencia_service.search_by_registration(
                filial=selected_summary.filial,
                cod_pdv=selected_summary.cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_inadimplencia_response(
                    records,
                    f"cliente {selected_summary.nome} | revenda {selected_summary.filial} | NB {selected_summary.cod_pdv}",
                    compact=session.inadimplencia_list_context == INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS,
                ),
                return_menu="inadimplencia_client_results",
            )

        if session.step == "awaiting_comodato_client_selection":
            selected_summary = _select_comodato_client_summary(
                text=text,
                normalized=normalized,
                summaries=session.comodato_client_summaries,
            )
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_comodato_client_menu(
                    query_text=session.fantasia_query,
                    summaries=list(session.comodato_client_summaries),
                    invalid_selection=True,
                )
            self._remember_last_context(
                session,
                intent="comodato_client",
                search_context="comodato",
                query_text=session.fantasia_query,
                client_filial=selected_summary.filial,
                client_cod_pdv=selected_summary.cod_pdv,
                client_name=selected_summary.nome,
            )
            records = self.comodatos_service.search_by_registration(
                filial=selected_summary.filial,
                cod_pdv=selected_summary.cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_comodato_response(
                    records,
                    f"cliente {selected_summary.nome} | revenda {selected_summary.filial} | NB {selected_summary.cod_pdv}",
                ),
                return_menu="comodato_client_results",
            )

        if session.step == "awaiting_document":
            return self._run_document_lookup(
                sender=incoming.sender,
                session=session,
                decision=decision,
                document=text,
            )

        if session.step == "awaiting_visit_day_selection":
            selected_visit_day = self._select_visit_day_option(
                text=text,
                normalized=normalized,
                visit_days=session.visit_day_options,
                description="Ver clientes desse dia",
            )
            if selected_visit_day is None:
                self.sessions[incoming.sender] = session
                return self._build_visit_day_menu(
                    decision=decision,
                    visit_days=list(session.visit_day_options),
                    invalid_selection=True,
                )
            return self._apply_visit_day_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                selected_visit_day=selected_visit_day,
            )

        if session.step == "visit_select_gv":
            selected_gv = _select_finance_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_visit_day_gv_menu(
                    visit_day=session.selected_visit_day,
                    visit_summaries=list(session.visit_group_summaries),
                    gv_options=list(session.finance_gv_options),
                    invalid_selection=True,
                )
            filtered_summaries = [
                summary
                for summary in session.visit_group_summaries
                if (normalize_stored_scope_value(summary.manager_code) or normalize_stored_scope_value(summary.seller_code))
                == normalize_stored_scope_value(selected_gv)
            ]
            if not filtered_summaries:
                self.sessions[incoming.sender] = session
                return self._build_grouped_visit_day_gv_menu(
                    visit_day=session.selected_visit_day,
                    visit_summaries=list(session.visit_group_summaries),
                    gv_options=list(session.finance_gv_options),
                    invalid_selection=True,
                )
            session.step = "awaiting_visit_seller_selection"
            session.visit_seller_summaries = tuple(filtered_summaries)
            session.selected_visit_gv = selected_gv
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_grouped_visit_day_sector_menu(
                visit_day=session.selected_visit_day,
                gv_code=selected_gv,
                visit_summaries=filtered_summaries,
            )

        if session.step == "awaiting_inadimplencia_visit_day_selection":
            selected_visit_day = self._select_visit_day_option(
                text=text,
                normalized=normalized,
                visit_days=session.visit_day_options,
                description="Ver a rota com risco financeiro desse dia",
            )
            if selected_visit_day is None:
                self.sessions[incoming.sender] = session
                return self._build_inadimplencia_visit_day_menu(
                    visit_days=list(session.visit_day_options),
                    invalid_selection=True,
                )
            return self._apply_inadimplencia_visit_day_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                selected_visit_day=selected_visit_day,
            )

        if session.step == "awaiting_giro_visit_day_selection":
            selected_visit_day = self._select_visit_day_option(
                text=text,
                normalized=normalized,
                visit_days=session.visit_day_options,
                description="Ver resumo e clientes com caixa desse dia",
            )
            if selected_visit_day is None:
                self.sessions[incoming.sender] = session
                return self._build_giro_visit_day_menu(
                    visit_days=list(session.visit_day_options),
                    invalid_selection=True,
                )
            return self._apply_giro_visit_day_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                selected_visit_day=selected_visit_day,
            )
        if session.step == "awaiting_documentacao_visit_day_selection":
            selected_visit_day = self._select_visit_day_option(
                text=text,
                normalized=normalized,
                visit_days=session.visit_day_options,
                description="Ver resumo e clientes com pendencia documental desse dia",
            )
            if selected_visit_day is None:
                return self._build_documentacao_visit_day_menu(
                    visit_days=list(session.visit_day_options),
                    invalid_selection=True,
                )
            return self._apply_documentacao_visit_day_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                selected_visit_day=selected_visit_day,
            )

        if session.step == "giro_select_visit_gv":
            selected_gv = _select_giro_visit_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_giro_visit_gv_menu(
                    summary_text=session.giro_visit_summary_text,
                    gv_options=list(session.finance_gv_options),
                    sector_summaries=list(session.giro_visit_sector_summaries),
                    invalid_selection=True,
                )
            session.step = "giro_select_visit_sector"
            session.selected_giro_visit_gv = selected_gv
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_grouped_giro_visit_sector_menu(
                summary_text=session.giro_visit_summary_text,
                gv_code=selected_gv,
                sector_summaries=list(session.giro_visit_sector_summaries),
            )

        if session.step == "giro_select_visit_sector":
            selected_sector = _select_giro_visit_sector_summary(
                text=text,
                normalized=normalized,
                summaries=session.giro_visit_sector_summaries,
                gv_code=session.selected_giro_visit_gv,
            )
            if selected_sector is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_giro_visit_sector_menu(
                    summary_text=session.giro_visit_summary_text,
                    gv_code=session.selected_giro_visit_gv,
                    sector_summaries=list(session.giro_visit_sector_summaries),
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_grouped_giro_visit_sector_response(
                    decision=decision,
                    visit_day=session.selected_visit_day,
                    sector_summary=selected_sector,
                ),
                return_menu="giro_visit_sector",
            )

        if session.step == "documentacao_select_visit_gv":
            selected_gv = _select_documentacao_visit_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_documentacao_visit_gv_menu(
                    summary_text=session.documentacao_visit_summary_text,
                    gv_options=list(session.finance_gv_options),
                    sector_summaries=list(session.documentacao_visit_sector_summaries),
                    invalid_selection=True,
                )
            session.step = "documentacao_select_visit_sector"
            session.selected_documentacao_visit_gv = selected_gv
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_grouped_documentacao_visit_sector_menu(
                gv_code=selected_gv,
                sector_summaries=list(session.documentacao_visit_sector_summaries),
            )

        if session.step == "documentacao_select_visit_sector":
            selected_sector = _select_documentacao_visit_sector_summary(
                text=text,
                normalized=normalized,
                summaries=session.documentacao_visit_sector_summaries,
                gv_code=session.selected_documentacao_visit_gv,
            )
            if selected_sector is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_documentacao_visit_sector_menu(
                    gv_code=session.selected_documentacao_visit_gv,
                    sector_summaries=list(session.documentacao_visit_sector_summaries),
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_grouped_documentacao_visit_sector_response(
                    visit_day=session.selected_visit_day,
                    sector_summary=selected_sector,
                    records=list(session.documentacao_visit_records),
                ),
                return_menu="documentacao_visit_sector",
            )

        if session.step == "awaiting_visit_seller_selection":
            selected_summary = _select_visit_seller_summary(
                text=text,
                normalized=normalized,
                summaries=session.visit_seller_summaries,
            )
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                if session.selected_visit_gv:
                    return self._build_grouped_visit_day_sector_menu(
                        visit_day=session.selected_visit_day,
                        gv_code=session.selected_visit_gv,
                        visit_summaries=list(session.visit_seller_summaries),
                        invalid_selection=True,
                    )
                return self._build_visit_day_manager_menu(
                    session.selected_visit_day,
                    list(session.visit_seller_summaries),
                    invalid_selection=True,
                )
            records = self.query_service.list_clients_by_visit_day_and_seller(
                visit_day=session.selected_visit_day,
                seller_code=selected_summary.seller_code,
                manager_code="" if selected_summary.manager_code == "-" else selected_summary.manager_code,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=80,
            )
            financial_alerts, alerts_note = self._load_visit_day_financial_alerts(
                decision=decision,
                visit_day=session.selected_visit_day,
                seller_code=selected_summary.seller_code,
                manager_code="" if selected_summary.manager_code == "-" else selected_summary.manager_code,
            )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_visit_day_seller_clients_response(
                    visit_day=session.selected_visit_day,
                    summary=selected_summary,
                    records=records,
                    decision=decision,
                    financial_alerts=financial_alerts,
                    alerts_note=alerts_note,
                ),
                return_menu="visit_day_seller",
            )

        if session.step == "awaiting_gv_summary_selection":
            selected_gv = _select_finance_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_director_gv_summary_menu(
                    gv_options=list(session.finance_gv_options),
                    invalid_selection=True,
                )
            self._reset_session(incoming.sender)
            return self._build_gv_summary_response(
                decision=decision,
                gv_vdes_override=(selected_gv,),
                title=f"Resumo do gerente {_format_gv_scope_label(selected_gv)}",
            )

        if session.step == "awaiting_manager_summary_mode":
            manager_action = _parse_manager_summary_action(normalized)
            if manager_action == "total":
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_gv_summary_response(
                        decision=decision,
                        title="Resumo Total da Gerencia",
                    ),
                    return_menu="manager_summary",
                )
            if manager_action == "by_filial":
                return self._open_manager_filial_summary_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            if manager_action == "list":
                return self._open_inadimplencia_summary_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                    order_by="total_pendente",
                    header_text="Esses sao os clientes inadimplentes da sua gerencia.",
                    empty_text=(
                        "No momento, nao encontrei clientes inadimplentes na sua gerencia.\n"
                        "Escolha outra opcao ou envie MENU."
                    ),
                    page=1,
                    page_size=INADIMPLENCIA_PAGE_SIZE,
                    list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
                )
            if manager_action == "upcoming":
                session.step = "awaiting_manager_due_bucket"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_manager_due_menu()
            if manager_action == "visit_risk":
                return self._open_manager_visit_risk_day_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            if manager_action == "by_seller":
                return self._open_manager_seller_summary_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            if manager_action == "giro":
                session.step = "manager_select_giro_mode"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_manager_giro_menu()
            self.sessions[incoming.sender] = session
            return self._build_manager_summary_menu(invalid_selection=True)

        if session.step == "awaiting_manager_filial_selection":
            selected_filial = _select_filial_option(
                text=text,
                normalized=normalized,
                filial_options=session.summary_filial_options,
            )
            if selected_filial is None:
                self.sessions[incoming.sender] = session
                return self._build_manager_filial_summary_menu(
                    filial_options=list(session.summary_filial_options),
                    invalid_selection=True,
                )
            selected_scope_keys = _filter_scope_codes_by_filial(decision.gv_vdes, selected_filial)
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_gv_summary_response(
                    decision=decision,
                    gv_vdes_override=selected_scope_keys,
                    title=f"Resumo da Gerencia | {_format_filial_label(selected_filial)}",
                ),
                return_menu="manager_filial",
            )

        if session.step == "awaiting_manager_due_bucket":
            due_bucket = _parse_finance_due_bucket(normalized)
            if not due_bucket:
                self.sessions[incoming.sender] = session
                return self._build_manager_due_menu(invalid_selection=True)

            bucket_meta = {
                "in_two_days": {
                    "header": "Esses sao os clientes da sua gerencia que vencem em 2 dias.",
                    "empty": (
                        "Nao encontrei clientes com vencimento em 2 dias na sua gerencia.\n"
                        "Escolha outra faixa ou envie MENU."
                    ),
                },
                "tomorrow": {
                    "header": "Esses sao os clientes da sua gerencia que vencem amanha.",
                    "empty": (
                        "Nao encontrei clientes com vencimento para amanha na sua gerencia.\n"
                        "Escolha outra faixa ou envie MENU."
                    ),
                },
                "today": {
                    "header": "Esses sao os clientes da sua gerencia que vencem hoje.",
                    "empty": (
                        "Nao encontrei clientes com vencimento hoje na sua gerencia.\n"
                        "Escolha outra faixa ou envie MENU."
                    ),
                },
                "overdue": {
                    "header": "Esses sao os clientes da sua gerencia que ja estao vencidos.",
                    "empty": (
                        "Nao encontrei clientes vencidos na sua gerencia.\n"
                        "Escolha outra faixa ou envie MENU."
                    ),
                },
            }[due_bucket]
            return self._open_inadimplencia_summary_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                order_by="total_pendente",
                due_bucket=due_bucket,
                header_text=bucket_meta["header"],
                empty_text=bucket_meta["empty"],
            )

        if session.step == "manager_select_visit_risk_day":
            selected_visit_risk_day = _select_visit_day(
                text=text,
                normalized=normalized,
                visit_days=session.visit_risk_day_options,
            )
            if selected_visit_risk_day is None:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    menu_title="Risco da Rota",
                    header_prompt="Escolha o dia da semana para ver o risco da rota da gerencia.",
                    invalid_selection=True,
                )
            visit_day_token = _visit_day_token_from_label(selected_visit_risk_day)
            if not visit_day_token:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    menu_title="Risco da Rota",
                    header_prompt="Escolha o dia da semana para ver o risco da rota da gerencia.",
                    invalid_selection=True,
                )
            return self._open_manager_visit_risk_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                visit_day_token=visit_day_token,
                visit_day_label=selected_visit_risk_day,
            )

        if session.step == "manager_select_visit_risk_gv":
            selected_gv = _select_finance_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    summaries=list(session.visit_risk_summaries),
                    menu_title="Risco da Rota",
                    day_header_prefix="Risco da rota",
                    invalid_selection=True,
                )
            filtered_summaries = [
                summary
                for summary in session.visit_risk_summaries
                if normalize_stored_scope_value(summary.manager_code) == normalize_stored_scope_value(selected_gv)
            ]
            if not filtered_summaries:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    summaries=list(session.visit_risk_summaries),
                    menu_title="Risco da Rota",
                    day_header_prefix="Risco da rota",
                    invalid_selection=True,
                )
            session.step = "manager_select_visit_risk_sector"
            session.visit_risk_summaries = tuple(filtered_summaries)
            session.selected_visit_risk_gv = selected_gv
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_finance_visit_risk_menu(
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                summaries=filtered_summaries,
                menu_title="Risco da Rota",
                day_header_prefix="Risco da rota",
            )

        if session.step == "manager_select_visit_risk_sector":
            selected_summary = _select_finance_visit_risk_summary(
                text=text,
                normalized=normalized,
                summaries=session.visit_risk_summaries,
            )
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    summaries=list(session.visit_risk_summaries),
                    menu_title="Risco da Rota",
                    day_header_prefix="Risco da rota",
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_finance_visit_risk_sector_response(
                    decision=decision,
                    summary=selected_summary,
                    visit_day_token=session.selected_visit_risk_token or _current_visit_day_token(),
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                ),
                return_menu="manager_visit_risk_sector",
            )

        if session.step == "awaiting_manager_seller_summary_selection":
            selected_summary = _select_visit_seller_summary(
                text=text,
                normalized=normalized,
                summaries=session.visit_seller_summaries,
            )
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_manager_seller_summary_menu(
                    seller_summaries=list(session.visit_seller_summaries),
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_manager_seller_summary_response(
                    decision=decision,
                    summary=selected_summary,
                ),
                return_menu="manager_seller",
            )

        if session.step == "manager_select_giro_mode":
            giro_mode = _parse_giro_mode(normalized)
            if giro_mode not in {"total", "by_filial"}:
                self.sessions[incoming.sender] = session
                return self._build_manager_giro_menu(invalid_selection=True)
            if giro_mode == "total":
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_giro_total_response(
                        decision,
                        title="Resumo de Giro | Gerencia",
                    ),
                    return_menu="manager_giro_menu",
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_giro_by_filial_response(
                    decision,
                    title="Giro por Filial | Gerencia",
                ),
                return_menu="manager_giro_menu",
            )

        if session.step == "awaiting_director_summary_mode":
            director_action = _parse_director_summary_action(normalized)
            if director_action == "total":
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_director_total_summary_response(decision),
                    return_menu="director_summary",
                )
            if director_action == "by_revenda":
                return self._open_director_gv_summary_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            if director_action == "ranking":
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_director_manager_ranking_response(decision),
                    return_menu="director_summary",
                )
            if director_action == "visit_risk":
                return self._open_director_visit_risk_day_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                )
            if director_action == "top_debtors":
                return self._open_inadimplencia_summary_selection(
                    sender=incoming.sender,
                    session=session,
                    decision=decision,
                    order_by="total_pendente",
                    header_text="Esses sao os maiores devedores da sua diretoria.",
                    empty_text=(
                        "No momento, nao encontrei clientes inadimplentes na sua diretoria.\n"
                        "Escolha outra opcao ou envie MENU."
                    ),
                    page=1,
                    page_size=INADIMPLENCIA_PAGE_SIZE,
                    list_context=INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS,
                )
            if director_action == "by_filial":
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_director_filial_summary_response(decision),
                    return_menu="director_summary",
                )
            if director_action == "giro":
                session.step = "director_select_giro_mode"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_director_giro_menu()
            self.sessions[incoming.sender] = session
            return self._build_director_summary_menu(invalid_selection=True)

        if session.step == "director_select_visit_risk_day":
            selected_visit_risk_day = _select_visit_day(
                text=text,
                normalized=normalized,
                visit_days=session.visit_risk_day_options,
            )
            if selected_visit_risk_day is None:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    invalid_selection=True,
                )
            visit_day_token = _visit_day_token_from_label(selected_visit_risk_day)
            if not visit_day_token:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    invalid_selection=True,
                )
            return self._open_director_visit_risk_gv_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                visit_day_token=visit_day_token,
                visit_day_label=selected_visit_risk_day,
            )

        if session.step == "director_select_visit_risk_gv":
            selected_gv = _select_finance_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    seller_summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )

            filtered_summaries = [
                summary
                for summary in session.visit_risk_summaries
                if normalize_stored_scope_value(summary.manager_code) == normalize_stored_scope_value(selected_gv)
            ]
            if not filtered_summaries:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    seller_summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )

            session.step = "director_select_visit_risk_sector"
            session.finance_gv_options = ()
            session.visit_risk_summaries = tuple(filtered_summaries)
            session.selected_visit_risk_gv = selected_gv
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_director_visit_risk_sector_menu(
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                summaries=filtered_summaries,
            )

        if session.step == "director_select_visit_risk_sector":
            selected_summary = _select_finance_visit_risk_summary(
                text=text,
                normalized=normalized,
                summaries=session.visit_risk_summaries,
            )
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_sector_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_director_visit_risk_sector_response(
                    decision=decision,
                    summary=selected_summary,
                    visit_day_token=session.selected_visit_risk_token or _current_visit_day_token(),
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                ),
                return_menu="director_visit_risk_sector",
            )

        if session.step == "director_select_giro_mode":
            giro_mode = _parse_giro_mode(normalized)
            if giro_mode not in {"by_gv", "by_filial"}:
                self.sessions[incoming.sender] = session
                return self._build_director_giro_menu(invalid_selection=True)
            if giro_mode == "by_gv":
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_giro_by_gv_response(
                        decision,
                        title="Giro por GV | Diretoria",
                    ),
                    return_menu="director_giro_menu",
                )
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._build_giro_by_filial_response(
                    decision,
                    title="Giro por Filial | Diretoria",
                ),
                return_menu="director_giro_menu",
            )

        direct_lookup = _parse_direct_registration_lookup(text)
        if direct_lookup is not None:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="cliente")
            if access_error is not None:
                return access_error
            return self._run_repeatable_registration_lookup(
                sender=incoming.sender,
                session=session,
                decision=decision,
                search_context="cliente",
                filial=direct_lookup[0],
                cod_pdv=direct_lookup[1],
            )

        direct_document = _normalize_document(text)
        if direct_document:
            readiness_error = self._ensure_search_context_ready("cliente", decision=decision)
            if readiness_error is not None:
                return readiness_error
            session.search_context = "cliente"
            return self._run_document_lookup(
                sender=incoming.sender,
                session=session,
                decision=decision,
                document=direct_document,
            )

        if normalized in {value for value in {MENU_SEARCH, search_shortcut, "buscar cliente", "buscar"} if value}:
            readiness_error = self._ensure_search_context_ready("cliente", decision=decision)
            if readiness_error is not None:
                return readiness_error
            session.step = "awaiting_search_mode"
            session.search_context = "cliente"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(
                session,
                intent="search_cliente",
                search_context="cliente",
            )
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="cliente", decision=decision)

        return self._build_main_menu(decision, invalid_selection=bool(normalized))

    def _handle_menu_back_navigation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        if session.step == "awaiting_post_result_navigation":
            return self._resume_post_result_navigation(sender=sender, session=session, decision=decision)

        if session.step in {
            "awaiting_filial",
            "awaiting_cod_pdv",
            "awaiting_fantasia",
            "awaiting_document",
            "awaiting_fantasia_selection",
            "awaiting_comodato_client_selection",
        }:
            session.step = "awaiting_search_mode"
            session.filial = ""
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.comodato_client_summaries = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context=session.search_context, decision=decision)

        if session.step == "awaiting_inadimplencia_client_selection":
            session.step = "awaiting_search_mode"
            session.fantasia_query = ""
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context="inadimplencia", decision=decision)

        if session.step == "awaiting_inadimplencia_visit_day_selection":
            session.step = "awaiting_search_mode"
            session.return_menu = ""
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context="inadimplencia", decision=decision)

        if session.step in {"awaiting_search_mode", "awaiting_visit_day_selection"}:
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if session.step == "visit_select_gv":
            session.step = "awaiting_visit_day_selection"
            session.visit_group_summaries = ()
            session.visit_seller_summaries = ()
            session.finance_gv_options = ()
            session.selected_visit_gv = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                self._reset_session(sender)
                return self._build_main_menu(decision)
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)

        if session.step == "awaiting_giro_visit_day_selection":
            session.step = "awaiting_search_mode"
            session.return_menu = ""
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context="giro", decision=decision)

        if session.step == "awaiting_documentacao_visit_day_selection":
            session.step = "awaiting_search_mode"
            session.return_menu = ""
            session.selected_visit_day = ""
            session.visit_day_options = ()
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context="documentacao", decision=decision)

        if session.step == "giro_select_visit_gv":
            session.step = "awaiting_giro_visit_day_selection"
            session.finance_gv_options = ()
            session.giro_visit_sector_summaries = ()
            session.giro_visit_summary_text = ""
            session.selected_giro_visit_gv = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_giro_visit_day_menu(visit_days=list(session.visit_day_options))

        if session.step == "giro_select_visit_sector":
            session.step = "giro_select_visit_gv"
            session.selected_giro_visit_gv = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_giro_visit_gv_menu(
                summary_text=session.giro_visit_summary_text,
                gv_options=list(session.finance_gv_options),
                sector_summaries=list(session.giro_visit_sector_summaries),
            )

        if session.step == "documentacao_select_visit_gv":
            session.step = "awaiting_documentacao_visit_day_selection"
            session.finance_gv_options = ()
            session.documentacao_visit_sector_summaries = ()
            session.documentacao_visit_records = ()
            session.documentacao_visit_summary_text = ""
            session.selected_documentacao_visit_gv = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_documentacao_visit_day_menu(visit_days=list(session.visit_day_options))

        if session.step == "documentacao_select_visit_sector":
            if len(session.finance_gv_options) > 1:
                session.step = "documentacao_select_visit_gv"
                session.selected_documentacao_visit_gv = ""
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_grouped_documentacao_visit_gv_menu(
                    summary_text=session.documentacao_visit_summary_text,
                    gv_options=list(session.finance_gv_options),
                    sector_summaries=list(session.documentacao_visit_sector_summaries),
                )
            session.step = "awaiting_documentacao_visit_day_selection"
            session.finance_gv_options = ()
            session.documentacao_visit_sector_summaries = ()
            session.documentacao_visit_records = ()
            session.documentacao_visit_summary_text = ""
            session.selected_documentacao_visit_gv = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_documentacao_visit_day_menu(visit_days=list(session.visit_day_options))

        if session.step == "awaiting_intent_clarification":
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if session.step == "awaiting_visit_seller_selection":
            if session.selected_visit_gv and len(session.finance_gv_options) > 1:
                session.step = "visit_select_gv"
                session.visit_seller_summaries = ()
                session.selected_visit_gv = ""
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_grouped_visit_day_gv_menu(
                    visit_day=session.selected_visit_day,
                    visit_summaries=list(session.visit_group_summaries),
                    gv_options=list(session.finance_gv_options),
                )
            session.step = "awaiting_visit_day_selection"
            session.visit_seller_summaries = ()
            session.visit_group_summaries = ()
            session.finance_gv_options = ()
            session.selected_visit_gv = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                try:
                    raw_visit_days = self.query_service.list_visit_days(
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                        limit=10,
                    )
                    visit_days = _normalize_visit_day_menu_values(raw_visit_days)
                except RuntimeError:
                    self._reset_session(sender)
                    return self._build_main_menu(decision)
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)

        if session.step == "awaiting_manager_summary_mode":
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if session.step in {
            "awaiting_manager_filial_selection",
            "awaiting_manager_due_bucket",
            "manager_select_visit_risk_day",
            "awaiting_manager_seller_summary_selection",
            "manager_select_giro_mode",
        }:
            return self._open_manager_summary_menu(sender=sender, session=session)

        if session.step == "manager_select_visit_risk_gv":
            return self._open_manager_visit_risk_day_selection(
                sender=sender,
                session=session,
                decision=decision,
            )

        if session.step == "manager_select_visit_risk_sector":
            if session.selected_visit_risk_gv and len(session.finance_gv_options) > 1:
                return self._open_manager_visit_risk_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    visit_day_token=session.selected_visit_risk_token or _current_visit_day_token(),
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                )
            return self._open_manager_visit_risk_day_selection(
                sender=sender,
                session=session,
                decision=decision,
            )

        if session.step in {"awaiting_director_summary_mode", "awaiting_gv_summary_selection"}:
            if session.step == "awaiting_gv_summary_selection":
                return self._open_director_summary_menu(sender=sender, session=session)
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if session.step == "director_select_giro_mode":
            return self._open_director_summary_menu(sender=sender, session=session)

        if session.step == "director_select_visit_risk_day":
            return self._open_director_summary_menu(sender=sender, session=session)

        if session.step == "director_select_visit_risk_gv":
            return self._open_director_visit_risk_day_selection(
                sender=sender,
                session=session,
                decision=decision,
            )

        if session.step == "director_select_visit_risk_sector":
            return self._open_director_visit_risk_gv_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=session.selected_visit_risk_token or _current_visit_day_token(),
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
            )

        if session.step == "finance_select_visit_risk_gv":
            return self._open_finance_visit_risk_day_selection(
                sender=sender,
                session=session,
                decision=decision,
            )

        if session.step == "finance_select_visit_risk_sector":
            if session.selected_visit_risk_gv and len(session.finance_gv_options) > 1:
                return self._open_finance_visit_risk_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    visit_day_token=session.selected_visit_risk_token or _current_visit_day_token(),
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                )
            return self._open_finance_visit_risk_day_selection(
                sender=sender,
                session=session,
                decision=decision,
            )

        return None

    def _resume_post_result_navigation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        return_menu = session.return_menu
        session.repeat_action = ""
        if not return_menu:
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if return_menu == "main":
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if return_menu == "search_menu":
            session.step = "awaiting_search_mode"
            session.return_menu = ""
            session.filial = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context=session.search_context, decision=decision)

        if return_menu == "search_results":
            session.step = "awaiting_fantasia_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if not session.fantasia_results:
                return self._build_search_menu(search_context=session.search_context, decision=decision)
            return self._build_fantasia_results_menu(
                query_text=session.fantasia_query,
                records=list(session.fantasia_results),
                search_context=session.search_context,
            )

        if return_menu == "inadimplencia_client_results":
            session.step = "awaiting_inadimplencia_client_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if not session.inadimplencia_client_summaries:
                return self._build_search_menu(search_context="inadimplencia", decision=decision)
            return self._build_inadimplencia_client_menu(
                query_text=session.fantasia_query,
                summaries=list(session.inadimplencia_client_summaries),
                total_available=session.inadimplencia_total_available,
                page=session.inadimplencia_page if session.inadimplencia_list_context else None,
                page_size=session.inadimplencia_page_size,
                list_context=session.inadimplencia_list_context,
            )

        if return_menu == "comodato_client_results":
            session.step = "awaiting_comodato_client_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if not session.comodato_client_summaries:
                return self._build_search_menu(search_context="comodato", decision=decision)
            return self._build_comodato_client_menu(
                query_text=session.fantasia_query,
                summaries=list(session.comodato_client_summaries),
            )

        if return_menu == "visit_day_menu":
            session.step = "awaiting_visit_day_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_main_menu(decision)
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)

        if return_menu == "giro_visit_day_menu":
            session.step = "awaiting_giro_visit_day_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_search_menu(search_context="giro", decision=decision)
            return self._build_giro_visit_day_menu(visit_days=visit_days)

        if return_menu == "documentacao_visit_day_menu":
            session.step = "awaiting_documentacao_visit_day_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_search_menu(search_context="documentacao", decision=decision)
            return self._build_documentacao_visit_day_menu(visit_days=visit_days)

        if return_menu == "giro_visit_sector":
            session.step = "giro_select_visit_sector"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_giro_visit_sector_menu(
                summary_text=session.giro_visit_summary_text,
                gv_code=session.selected_giro_visit_gv,
                sector_summaries=list(session.giro_visit_sector_summaries),
            )

        if return_menu == "documentacao_visit_sector":
            session.step = "documentacao_select_visit_sector"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_documentacao_visit_sector_menu(
                gv_code=session.selected_documentacao_visit_gv,
                sector_summaries=list(session.documentacao_visit_sector_summaries),
            )

        if return_menu == "inadimplencia_visit_day_menu":
            session.step = "awaiting_inadimplencia_visit_day_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_search_menu(search_context="inadimplencia", decision=decision)
            return self._build_inadimplencia_visit_day_menu(visit_days=visit_days)

        if return_menu == "visit_day_seller":
            session.step = "awaiting_visit_seller_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if not session.visit_seller_summaries:
                return self._build_visit_day_menu(decision=decision, visit_days=list(session.visit_day_options))
            if session.selected_visit_gv:
                return self._build_grouped_visit_day_sector_menu(
                    visit_day=session.selected_visit_day,
                    gv_code=session.selected_visit_gv,
                    visit_summaries=list(session.visit_seller_summaries),
                )
            return self._build_visit_day_manager_menu(
                visit_day=session.selected_visit_day,
                visit_summaries=list(session.visit_seller_summaries),
            )

        if return_menu == "finance_menu":
            session.step = "finance_select_action"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_menu()

        if return_menu == "finance_summary_menu":
            session.step = "finance_select_summary_mode"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_summary_menu()

        if return_menu == "finance_gv_summary":
            session.step = "finance_select_gv_summary"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_gv_summary_menu(gv_options=list(session.finance_gv_options))

        if return_menu == "finance_giro_menu":
            session.step = "finance_select_giro_mode"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_giro_menu()

        if return_menu == "finance_payip_menu":
            session.step = "finance_payip_menu"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_menu()

        if return_menu == "finance_visit_risk_sector":
            session.step = "finance_select_visit_risk_sector"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_menu(
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                summaries=list(session.visit_risk_summaries),
            )

        if return_menu == "manager_summary":
            return self._open_manager_summary_menu(sender=sender, session=session)

        if return_menu == "manager_filial":
            session.step = "awaiting_manager_filial_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_manager_filial_summary_menu(filial_options=list(session.summary_filial_options))

        if return_menu == "manager_seller":
            session.step = "awaiting_manager_seller_summary_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_manager_seller_summary_menu(seller_summaries=list(session.visit_seller_summaries))

        if return_menu == "manager_giro_menu":
            session.step = "manager_select_giro_mode"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_manager_giro_menu()

        if return_menu == "manager_visit_risk_sector":
            session.step = "manager_select_visit_risk_sector"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_menu(
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                summaries=list(session.visit_risk_summaries),
            )

        if return_menu == "director_summary":
            return self._open_director_summary_menu(sender=sender, session=session)

        if return_menu == "director_gv_summary":
            session.step = "awaiting_gv_summary_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_director_gv_summary_menu(gv_options=list(session.finance_gv_options))

        if return_menu == "director_giro_menu":
            session.step = "director_select_giro_mode"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_director_giro_menu()

        if return_menu == "director_visit_risk_sector":
            session.step = "director_select_visit_risk_sector"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_director_visit_risk_sector_menu(
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                summaries=list(session.visit_risk_summaries),
            )

        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _repeat_post_result_navigation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        repeat_action = session.repeat_action
        if repeat_action:
            session.return_menu = ""
            session.repeat_action = ""

        if repeat_action == REPEAT_SEARCH_REGISTRATION:
            return self._activate_search_mode(sender, session, search_mode="registration")
        if repeat_action == REPEAT_SEARCH_DOCUMENT:
            return self._activate_search_mode(sender, session, search_mode="document")
        if repeat_action == REPEAT_SEARCH_NAME:
            return self._activate_search_mode(sender, session, search_mode="name")
        if repeat_action == REPEAT_PAYIP_INVOICE:
            session.step = "finance_payip_awaiting_invoice"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_invoice_prompt()
        if repeat_action in {REPEAT_PAYIP_PENDING_CLIENT, REPEAT_PAYIP_CLIENT}:
            pending_only = repeat_action == REPEAT_PAYIP_PENDING_CLIENT
            session.step = "finance_payip_awaiting_client_code"
            session.payip_pending_status = "PENDING" if pending_only else ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(pending_only=pending_only)
        if repeat_action == REPEAT_PAYIP_CREATE_CHARGE:
            session.step = "finance_payip_charge_awaiting_client"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_client_prompt()
        if repeat_action == REPEAT_PAYIP_STATEMENT:
            session.step = "finance_payip_statement_awaiting_period"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_statement_prompt()
        if repeat_action == REPEAT_PAYIP_AMOUNT_DAY:
            session.step = "finance_payip_amount_day_awaiting_query"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_amount_day_prompt()

        return self._resume_post_result_navigation(sender=sender, session=session, decision=decision)

    def _store_post_result_navigation(
        self,
        sender: str,
        session: LookupSession,
        *,
        return_menu: str,
        repeat_action: str = "",
    ) -> None:
        if not repeat_action and return_menu == "search_menu":
            if session.step in {"awaiting_fantasia", "awaiting_fantasia_selection"}:
                repeat_action = REPEAT_SEARCH_NAME
        session.step = "awaiting_post_result_navigation"
        session.return_menu = return_menu
        session.repeat_action = repeat_action
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session

    def _with_post_result_navigation(
        self,
        sender: str,
        session: LookupSession,
        outgoing: OutgoingMessage,
        *,
        return_menu: str,
        repeat_action: str = "",
    ) -> OutgoingMessage:
        self._store_post_result_navigation(
            sender,
            session,
            return_menu=return_menu,
            repeat_action=repeat_action,
        )
        if outgoing.kind != "text":
            return outgoing

        normalized_text = _normalize_choice(outgoing.text)
        hint = _result_hint_text(allow_back=True)
        if _normalize_choice(hint) in normalized_text:
            return outgoing
        text = _strip_result_hint(outgoing.text)
        if text:
            text = f"{text}\n\n{hint}"
        else:
            text = hint
        return OutgoingMessage(
            text=text,
            kind=outgoing.kind,
            title=outgoing.title,
            footer=outgoing.footer,
            button_text=outgoing.button_text,
            options=outgoing.options,
        )

    def _prepare_search_session(self, session: LookupSession, *, search_context: str) -> None:
        session.step = "awaiting_search_mode"
        session.search_context = search_context
        self._clear_clarification_state(session)
        session.filial = ""
        session.fantasia_query = ""
        session.fantasia_results = ()
        session.inadimplencia_client_summaries = ()
        session.inadimplencia_total_available = 0
        session.inadimplencia_list_context = ""
        session.inadimplencia_page = 1
        session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
        session.comodato_client_summaries = ()
        session.selected_visit_day = ""
        session.visit_day_options = ()
        session.visit_seller_summaries = ()
        session.visit_group_summaries = ()
        session.selected_visit_gv = ""
        session.giro_visit_sector_summaries = ()
        session.giro_visit_summary_text = ""
        session.selected_giro_visit_gv = ""
        session.selected_visit_risk_gv = ""
        session.updated_at = datetime.now(timezone.utc)

    def _open_search_context(
        self,
        sender: str,
        session: LookupSession,
        *,
        search_context: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        self._prepare_search_session(session, search_context=search_context)
        self._remember_last_context(
            session,
            intent=f"search_{search_context}",
            search_context=search_context,
        )
        self.sessions[sender] = session
        return self._build_search_menu(search_context=search_context, decision=decision)

    def _run_search_menu_option(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        option_id: str,
    ) -> OutgoingMessage:
        if option_id == SEARCH_BY_REGISTRATION:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._activate_search_mode(sender, session, search_mode="registration")

        if option_id == SEARCH_BY_FANTASIA:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._activate_search_mode(sender, session, search_mode="name")

        if option_id == SEARCH_BY_DOCUMENT:
            access_error = None
            if session.search_context in {"cliente", "giro", "inadimplencia", "comodato", "documentacao", "prazo_limite"}:
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._activate_search_mode(sender, session, search_mode="document")

        if option_id == SEARCH_BY_INADIMPLENTES_BASE and session.search_context == "inadimplencia":
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._open_inadimplencia_summary_selection(
                sender=sender,
                session=session,
                decision=decision,
                order_by="total_pendente",
                header_text=f"Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.",
                empty_text=(
                    "No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\n"
                    "Se quiser tentar outra consulta, envie MENU."
                ),
                page=1,
                page_size=INADIMPLENCIA_PAGE_SIZE,
                list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
            )

        if option_id in {FINANCE_DUE_TOMORROW, FINANCE_DUE_IN_TWO_DAYS} and session.search_context == "inadimplencia":
            due_bucket = "tomorrow" if option_id == FINANCE_DUE_TOMORROW else "in_two_days"
            return self._run_scoped_inadimplencia_due_bucket(
                sender=sender,
                session=session,
                decision=decision,
                due_bucket=due_bucket,
            )

        if option_id == SEARCH_BY_VISIT_DAY:
            if session.search_context == "giro":
                return self._open_giro_visit_day_conversation(
                    sender=sender,
                    session=session,
                    decision=decision,
                )
            if session.search_context == "inadimplencia":
                return self._open_inadimplencia_visit_day_conversation(
                    sender=sender,
                    session=session,
                    decision=decision,
                )
            if session.search_context == "documentacao":
                return self._open_documentacao_visit_day_conversation(
                    sender=sender,
                    session=session,
                    decision=decision,
                )

        if option_id == SEARCH_BY_GIRO_ZERO_BASE and session.search_context == "giro":
            self._remember_last_context(
                session,
                intent="giro_zero_base",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_zero_base_response(decision),
                return_menu="search_menu",
            )

        self.sessions[sender] = session
        return self._build_search_menu(
            search_context=session.search_context,
            decision=decision,
            invalid_selection=True,
        )

    def _activate_search_mode(
        self,
        sender: str,
        session: LookupSession,
        *,
        search_mode: str,
    ) -> OutgoingMessage:
        session.filial = ""
        session.fantasia_query = ""
        session.fantasia_results = ()
        session.inadimplencia_client_summaries = ()
        session.inadimplencia_total_available = 0
        session.inadimplencia_list_context = ""
        session.inadimplencia_page = 1
        session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
        session.comodato_client_summaries = ()
        session.selected_visit_day = ""
        session.visit_day_options = ()
        session.visit_seller_summaries = ()
        if search_mode == "registration":
            session.step = "awaiting_filial"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return OutgoingMessage(text=_build_filial_prompt(session.search_context))
        if search_mode == "document":
            session.step = "awaiting_document"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if session.search_context == "inadimplencia":
                return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar a inadimplencia.")
            if session.search_context == "comodato":
                return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar os comodatos pendentes.")
            if session.search_context == "giro":
                return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar o giro.")
            if session.search_context == "documentacao":
                return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar a documentacao pendente.")
            if session.search_context == "prazo_limite":
                return OutgoingMessage(text="Digite o CPF ou CNPJ do cliente para consultar prazo e limite.")
            return OutgoingMessage(
                text=(
                    "Digite o CPF ou CNPJ do cliente.\n"
                    "Vou respeitar o mesmo acesso comercial liberado para o seu numero."
                )
            )
        session.step = "awaiting_fantasia"
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        if session.search_context == "inadimplencia":
            return OutgoingMessage(text="Digite parte do nome do cliente para ver os titulos em aberto.")
        if session.search_context == "comodato":
            return OutgoingMessage(text="Digite parte do nome do cliente para ver os comodatos pendentes.")
        if session.search_context == "giro":
            return OutgoingMessage(text="Digite parte do nome do cliente para ver os dados de giro.")
        if session.search_context == "documentacao":
            return OutgoingMessage(text="Digite parte do nome do cliente para ver a documentacao pendente.")
        if session.search_context == "prazo_limite":
            return OutgoingMessage(text="Digite parte do nome do cliente para consultar prazo e limite.")
        return OutgoingMessage(
            text=(
                "Digite parte do nome do cliente.\n"
                "Vou procurar e mostrar uma lista para voce escolher."
            )
        )

    def _run_name_search(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        query_text: str,
    ) -> OutgoingMessage:
        cleaned_query = " ".join(str(query_text or "").strip().split())
        if len(cleaned_query) < 3:
            self.sessions[sender] = session
            return OutgoingMessage(text="Digite pelo menos 3 letras do nome do cliente.")
        self._remember_last_context(
            session,
            intent=f"search_{session.search_context}",
            search_context=session.search_context,
            query_text=cleaned_query,
        )
        if session.search_context == "inadimplencia":
            summaries = self.inadimplencia_service.search_client_summaries_by_name(
                query_text=cleaned_query,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=20,
            )
            if not summaries:
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return OutgoingMessage(
                    text=(
                        f"Nao encontrei cliente com '{cleaned_query}' na inadimplencia.\n"
                        "Pode me enviar outro trecho ou, se preferir, digite MENU."
                    )
                )
            if len(summaries) == 1:
                summary = summaries[0]
                self._remember_last_context(
                    session,
                    intent="inadimplencia_client",
                    search_context="inadimplencia",
                    client_filial=summary.filial,
                    client_cod_pdv=summary.cod_pdv,
                    client_name=summary.nome,
                )
                records = self.inadimplencia_service.search_by_registration(
                    filial=summary.filial,
                    cod_pdv=summary.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=50,
                )
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_inadimplencia_response(
                        records,
                        f"cliente {summary.nome} | revenda {summary.filial} | NB {summary.cod_pdv}",
                    ),
                    return_menu="search_menu",
                )
            session.step = "awaiting_inadimplencia_client_selection"
            session.fantasia_query = cleaned_query
            session.inadimplencia_client_summaries = tuple(summaries)
            session.inadimplencia_total_available = len(summaries)
            session.inadimplencia_list_context = ""
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_inadimplencia_client_menu(query_text=cleaned_query, summaries=summaries)
        if session.search_context == "comodato":
            summaries = self.comodatos_service.search_client_summaries_by_name(
                query_text=cleaned_query,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=20,
            )
            if not summaries:
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return OutgoingMessage(
                    text=(
                        f"Nao encontrei cliente com '{cleaned_query}' nos comodatos pendentes.\n"
                        "Pode me enviar outro trecho ou, se preferir, digite MENU."
                    )
                )
            if len(summaries) == 1:
                summary = summaries[0]
                self._remember_last_context(
                    session,
                    intent="comodato_client",
                    search_context="comodato",
                    client_filial=summary.filial,
                    client_cod_pdv=summary.cod_pdv,
                    client_name=summary.nome,
                )
                records = self.comodatos_service.search_by_registration(
                    filial=summary.filial,
                    cod_pdv=summary.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=50,
                )
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_comodato_response(
                        records,
                        f"cliente {summary.nome} | revenda {summary.filial} | NB {summary.cod_pdv}",
                    ),
                    return_menu="search_menu",
                )
            session.step = "awaiting_comodato_client_selection"
            session.fantasia_query = cleaned_query
            session.comodato_client_summaries = tuple(summaries)
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_comodato_client_menu(query_text=cleaned_query, summaries=summaries)
        records = self.query_service.search_by_fantasia(
            query_text=cleaned_query,
            allowed_sectors=self._allowed_sectors(decision),
            allowed_gv_vdes=self._allowed_gv_vdes(decision),
            limit=10,
        )
        if not records:
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return OutgoingMessage(
                text=(
                    f"Nao encontrei cliente com '{cleaned_query}' no nome.\n"
                    "Pode me enviar outro trecho ou, se preferir, digite MENU."
                )
            )
        if len(records) == 1:
            record = records[0]
            self._remember_last_context(
                session,
                intent=f"{session.search_context}_client",
                search_context=session.search_context,
                client_filial=record.filial,
                client_cod_pdv=record.cod_pdv,
                client_name=record.nome_fantasia or record.razao_social,
            )
            if session.search_context == "giro":
                giro_records = self.giro_service.search_by_registration(
                    filial=record.filial,
                    cod_pdv=record.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                criteria = (
                    f"nome fantasia contendo '{cleaned_query}'"
                    f" | revenda {record.filial} | NB {record.cod_pdv}"
                )
                if not giro_records:
                    historical_response = self._build_giro_historical_fallback_response(
                        decision=decision,
                        filial=record.filial,
                        cod_pdv=record.cod_pdv,
                        criteria=criteria,
                    )
                    if historical_response is not None:
                        return self._with_post_result_navigation(
                            sender,
                            session,
                            historical_response,
                            return_menu="search_menu",
                        )
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_giro_response(
                        giro_records,
                        criteria=criteria,
                        scope_restricted=not self._has_unrestricted_lookup_access(decision),
                    ),
                    return_menu="search_menu",
                )
            if session.search_context == "documentacao":
                documentacao_records = self.documentacao_pendente_service.search_by_registration(
                    filial=record.filial,
                    cod_pdv=record.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_documentacao_pendente_response(
                        documentacao_records,
                        criteria=(
                            f"nome fantasia contendo '{cleaned_query}'"
                            f" | revenda {record.filial} | NB {record.cod_pdv}"
                        ),
                        scope_restricted=not self._has_unrestricted_lookup_access(decision),
                    ),
                    return_menu="search_menu",
                )
            if session.search_context == "prazo_limite":
                prazo_limite_records = self.prazo_limite_service.search_by_registration(
                    filial=record.filial,
                    cod_pdv=record.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                if not prazo_limite_records:
                    return OutgoingMessage(
                        text=(
                            f"Encontrei o cadastro para '{record.nome_fantasia or record.razao_social or cleaned_query}', "
                            f"mas ele nao apareceu no ultimo relatorio de prazo e limite importado.\n"
                            "Se quiser tentar outra busca, envie MENU."
                        )
                    )
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_prazo_limite_response(
                        prazo_limite_records,
                        criteria=(
                            f"nome fantasia contendo '{cleaned_query}'"
                            f" | revenda {record.filial} | NB {record.cod_pdv}"
                        ),
                        decision=decision,
                        scope_restricted=not self._has_unrestricted_lookup_access(decision),
                    ),
                    return_menu="search_menu",
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_single_record_response(
                    record=record,
                    criteria=f"nome fantasia contendo '{cleaned_query}'",
                    decision=decision,
                ),
                return_menu="search_menu",
            )
        session.step = "awaiting_fantasia_selection"
        session.fantasia_query = cleaned_query
        session.fantasia_results = tuple(records)
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_fantasia_results_menu(
            query_text=cleaned_query,
            records=records,
            search_context=session.search_context,
        )

    def _run_document_lookup(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        document: str,
        return_menu: str = "search_menu",
    ) -> OutgoingMessage:
        normalized_document = _normalize_document(document)
        if not normalized_document:
            self.sessions[sender] = session
            return OutgoingMessage(text="Digite um CPF ou CNPJ valido, com 11 ou 14 numeros.")
        if session.search_context == "inadimplencia":
            records = self.inadimplencia_service.search_by_document(
                document=normalized_document,
                allowed_sectors=None,
                allowed_gv_vdes=None,
                limit=50,
            )
            if records:
                self._remember_last_context(
                    session,
                    intent="inadimplencia_document",
                    search_context="inadimplencia",
                    client_filial=records[0].filial,
                    client_cod_pdv=records[0].cod_pdv,
                    client_name=records[0].nome,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_inadimplencia_response(records, f"CPF/CNPJ {normalized_document}"),
                return_menu=return_menu,
                repeat_action=REPEAT_SEARCH_DOCUMENT,
            )
        if session.search_context == "comodato":
            records = self.comodatos_service.search_by_document(
                document=normalized_document,
                allowed_sectors=None,
                allowed_gv_vdes=None,
                limit=50,
            )
            if records:
                self._remember_last_context(
                    session,
                    intent="comodato_document",
                    search_context="comodato",
                    client_filial=records[0].filial,
                    client_cod_pdv=records[0].cod_pdv,
                    client_name=records[0].nome,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_comodato_response(records, f"CPF/CNPJ {normalized_document}"),
                return_menu=return_menu,
                repeat_action=REPEAT_SEARCH_DOCUMENT,
            )
        if session.search_context == "giro":
            records = self._search_giro_by_document(normalized_document)
            if records:
                self._remember_last_context(
                    session,
                    intent="giro_document",
                    search_context="giro",
                    client_filial=records[0].filial,
                    client_cod_pdv=records[0].cod_pdv,
                    client_name=records[0].nome,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_response(
                    records,
                    f"CPF/CNPJ {normalized_document}",
                    scope_restricted=False,
                ),
                return_menu=return_menu,
                repeat_action=REPEAT_SEARCH_DOCUMENT,
            )
        if session.search_context == "documentacao":
            base_records = self.query_service.search_by_document(
                document=normalized_document,
                allowed_sectors=None,
                allowed_gv_vdes=None,
                limit=50,
            )
            documentacao_records: list[DocumentacaoPendenteClientRecord] = []
            for base_record in base_records:
                documentacao_records.extend(
                    self.documentacao_pendente_service.search_by_registration(
                        filial=base_record.filial,
                        cod_pdv=base_record.cod_pdv,
                        allowed_sectors=None,
                        allowed_gv_vdes=None,
                        limit=5,
                    )
                )
            if documentacao_records:
                self._remember_last_context(
                    session,
                    intent="documentacao_document",
                    search_context="documentacao",
                    client_filial=documentacao_records[0].filial,
                    client_cod_pdv=documentacao_records[0].cod_pdv,
                    client_name=documentacao_records[0].nome,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_documentacao_pendente_response(
                    documentacao_records,
                    f"CPF/CNPJ {normalized_document}",
                    scope_restricted=False,
                ),
                return_menu=return_menu,
                repeat_action=REPEAT_SEARCH_DOCUMENT,
            )
        if session.search_context == "prazo_limite":
            prazo_limite_records = self.prazo_limite_service.search_by_document(
                document=normalized_document,
                allowed_sectors=None,
                allowed_gv_vdes=None,
                limit=50,
            )
            if prazo_limite_records:
                self._remember_last_context(
                    session,
                    intent="prazo_limite_document",
                    search_context="prazo_limite",
                    client_filial=prazo_limite_records[0].filial,
                    client_cod_pdv=prazo_limite_records[0].cod_pdv,
                    client_name=prazo_limite_records[0].nome,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_prazo_limite_response(
                    prazo_limite_records,
                    f"CPF/CNPJ {normalized_document}",
                    decision=decision,
                    scope_restricted=False,
                ),
                return_menu=return_menu,
                repeat_action=REPEAT_SEARCH_DOCUMENT,
            )
        records = self.query_service.search_by_document(
            document=normalized_document,
            allowed_sectors=None,
            allowed_gv_vdes=None,
            limit=20,
        )
        if records:
            self._remember_last_context(
                session,
                intent="cliente_document",
                search_context="cliente",
                client_filial=records[0].filial,
                client_cod_pdv=records[0].cod_pdv,
                client_name=records[0].nome_fantasia or records[0].razao_social,
            )
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_search_response(
                records,
                f"CPF/CNPJ {normalized_document}",
                decision=decision,
                scope_restricted=False,
            ),
            return_menu=return_menu,
            repeat_action=REPEAT_SEARCH_DOCUMENT,
        )

    def _apply_visit_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        selected_visit_day: str,
    ) -> OutgoingMessage:
        self._remember_last_context(
            session,
            intent="visit_day",
            search_context="cliente",
            visit_day=selected_visit_day,
        )
        if self._uses_grouped_visit_flow(decision):
            visit_summaries = self._load_visit_day_seller_summaries(
                decision=decision,
                visit_day=selected_visit_day,
                limit=1000,
            )
            if not visit_summaries:
                return OutgoingMessage(
                    text=(
                        f"Nao encontrei visitas para o dia '{_format_visit_day_label(selected_visit_day)}'.\n"
                        "Se quiser tentar de novo, envie MENU."
                    )
                )
            gv_options = sorted(
                {
                    normalize_stored_scope_value(summary.manager_code)
                    or normalize_stored_scope_value(summary.seller_code)
                    for summary in visit_summaries
                    if normalize_stored_scope_value(summary.manager_code)
                    or normalize_stored_scope_value(summary.seller_code)
                },
                key=_sort_scope_code,
            )
            if len(gv_options) > 1:
                return self._open_grouped_visit_day_selection(
                    sender=sender,
                    session=session,
                    selected_visit_day=selected_visit_day,
                    visit_summaries=visit_summaries,
                    gv_options=gv_options,
                )
            if len(visit_summaries) == 1:
                selected_summary = visit_summaries[0]
                records = self.query_service.list_clients_by_visit_day_and_seller(
                    visit_day=selected_visit_day,
                    seller_code=selected_summary.seller_code,
                    manager_code="" if selected_summary.manager_code == "-" else selected_summary.manager_code,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=80,
                )
                financial_alerts, alerts_note = self._load_visit_day_financial_alerts(
                    decision=decision,
                    visit_day=selected_visit_day,
                    seller_code=selected_summary.seller_code,
                    manager_code="" if selected_summary.manager_code == "-" else selected_summary.manager_code,
                )
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_visit_day_seller_clients_response(
                        visit_day=selected_visit_day,
                        summary=selected_summary,
                        records=records,
                        decision=decision,
                        financial_alerts=financial_alerts,
                        alerts_note=alerts_note,
                    ),
                    return_menu="visit_day_menu",
                )
            selected_gv = gv_options[0] if gv_options else ""
            session.step = "awaiting_visit_seller_selection"
            session.selected_visit_day = selected_visit_day
            session.visit_group_summaries = tuple(visit_summaries)
            session.visit_seller_summaries = tuple(visit_summaries)
            session.finance_gv_options = tuple(gv_options)
            session.selected_visit_gv = selected_gv
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_visit_day_sector_menu(
                visit_day=selected_visit_day,
                gv_code=selected_gv,
                visit_summaries=visit_summaries,
            )
        records = self.query_service.list_clients_by_visit_day(
            visit_day=selected_visit_day,
            allowed_sectors=self._allowed_sectors(decision),
            allowed_gv_vdes=self._allowed_gv_vdes(decision),
            limit=80,
        )
        financial_alerts, alerts_note = self._load_visit_day_financial_alerts(
            decision=decision,
            visit_day=selected_visit_day,
        )
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_visit_day_clients_response(
                selected_visit_day,
                records,
                decision,
                financial_alerts=financial_alerts,
                alerts_note=alerts_note,
            ),
            return_menu="visit_day_menu",
        )

    def _open_grouped_visit_day_selection(
        self,
        *,
        sender: str,
        session: LookupSession,
        selected_visit_day: str,
        visit_summaries: list[VisitSellerSummary],
        gv_options: list[str],
    ) -> OutgoingMessage:
        session.step = "visit_select_gv"
        session.selected_visit_day = selected_visit_day
        session.visit_group_summaries = tuple(visit_summaries)
        session.visit_seller_summaries = ()
        session.finance_gv_options = tuple(gv_options)
        session.selected_visit_gv = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_grouped_visit_day_gv_menu(
            visit_day=selected_visit_day,
            visit_summaries=visit_summaries,
            gv_options=gv_options,
        )

    def _build_grouped_visit_day_gv_menu(
        self,
        *,
        visit_day: str,
        visit_summaries: list[VisitSellerSummary],
        gv_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        grouped: dict[str, list[VisitSellerSummary]] = {}
        for summary in visit_summaries:
            group_key = normalize_stored_scope_value(summary.manager_code) or normalize_stored_scope_value(summary.seller_code)
            grouped.setdefault(group_key, []).append(summary)

        lines = [f"Visitas de '{visit_day_label}'"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(
            f"GVs na rota: {len(gv_options)} | Setores: {len(visit_summaries)} | "
            f"Visitas: {sum(int(summary.visit_count or 0) for summary in visit_summaries)}"
        )
        lines.append("")
        lines.append("Escolha o GV para ver os setores da rota.")
        return OutgoingMessage(
            kind="menu",
            title="Visitas por GV",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro setores e visitas daquele GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"visitgv:pick:{index}",
                    title=_format_visit_manager_summary_label(gv_code),
                    description=(
                        f"{len(grouped.get(gv_code, []))} setor(es) | "
                        f"{sum(int(item.visit_count or 0) for item in grouped.get(gv_code, []))} visita(s)"
                    ),
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_grouped_visit_day_sector_menu(
        self,
        *,
        visit_day: str,
        gv_code: str,
        visit_summaries: list[VisitSellerSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        normalized_gv_code = normalize_stored_scope_value(gv_code)
        grouped_items = [
            summary
            for summary in visit_summaries
            if (normalize_stored_scope_value(summary.manager_code) or normalize_stored_scope_value(summary.seller_code))
            == normalized_gv_code
        ]
        lines = [f"Visitas de '{visit_day_label}'"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(_format_visit_manager_summary_label(normalized_gv_code))
        lines.append(
            f"Setores na rota: {len(grouped_items)} | "
            f"Visitas: {sum(int(item.visit_count or 0) for item in grouped_items)}"
        )
        lines.append("")
        lines.append("Escolha o setor para ver os clientes da rota.")
        return OutgoingMessage(
            kind="menu",
            title="Visitas por Setor",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro as visitas do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{VISIT_SELLER_PICK_PREFIX}{index}",
                    title=_format_sector_scope_label(item.seller_code),
                    description=f"{int(item.visit_count or 0)} visita(s)",
                    shortcut=str(index),
                )
                for index, item in enumerate(grouped_items, start=1)
            ),
        )

    def _apply_inadimplencia_visit_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        selected_visit_day: str,
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(selected_visit_day)
        visit_day_token = _visit_day_token_from_label(selected_visit_day)
        self._remember_last_context(
            session,
            intent="inadimplencia_visit_day",
            search_context="inadimplencia",
            visit_day=visit_day_label,
        )

        if self._can_use_finance_menu(decision):
            return self._open_finance_visit_risk_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=visit_day_token,
                visit_day_label=visit_day_label,
            )
        if self._is_diretor_comercial(decision):
            return self._open_director_visit_risk_gv_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=visit_day_token,
                visit_day_label=visit_day_label,
            )
        if self._is_gerente_vendas(decision):
            return self._open_manager_visit_risk_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=visit_day_token,
                visit_day_label=visit_day_label,
            )
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_seller_visit_day_risk_response(
                decision=decision,
                visit_day=selected_visit_day,
                visit_day_label=visit_day_label,
            ),
            return_menu="inadimplencia_visit_day_menu",
        )

    def _apply_giro_visit_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        selected_visit_day: str,
    ) -> OutgoingMessage:
        self._remember_last_context(
            session,
            intent="giro_visit_day",
            search_context="giro",
            visit_day=selected_visit_day,
        )
        summary = self._safe_giro_scope_summary_by_visit_day(decision, visit_day=selected_visit_day)
        if summary is None:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao consegui montar a oportunidade de giro por dia agora.\n"
                    "Tente novamente em instantes."
                )
            )
        try:
            records = self.query_service.list_clients_by_visit_day(
                visit_day=selected_visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=5000 if self._uses_grouped_giro_visit_flow(decision) or self._has_unrestricted_lookup_access(decision) else 200,
            )
        except RuntimeError:
            records = []
        session.selected_visit_day = selected_visit_day
        if self._is_gerente_vendas(decision):
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_visit_day_response(
                    visit_day=selected_visit_day,
                    decision=decision,
                    summary=summary,
                    records=records,
                ),
                return_menu="giro_visit_day_menu",
            )
        if self._uses_grouped_giro_visit_flow(decision):
            return self._open_grouped_giro_visit_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day=selected_visit_day,
                summary=summary,
                records=records,
            )
        response_builder = (
            self._build_finance_giro_visit_day_response
            if self._has_unrestricted_lookup_access(decision)
            else self._build_giro_visit_day_response
        )
        return self._with_post_result_navigation(
            sender,
            session,
            response_builder(
                visit_day=selected_visit_day,
                decision=decision,
                summary=summary,
                records=records,
            ),
            return_menu="giro_visit_day_menu",
        )

    def _apply_documentacao_visit_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        selected_visit_day: str,
    ) -> OutgoingMessage:
        self._remember_last_context(
            session,
            intent="documentacao_visit_day",
            search_context="documentacao",
            visit_day=selected_visit_day,
        )
        try:
            summary = self.documentacao_pendente_service.get_scope_summary_by_visit_day(
                visit_day=selected_visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            records = self.documentacao_pendente_service.list_pending_by_visit_day(
                visit_day=selected_visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=5000 if self._has_unrestricted_lookup_access(decision) or self._uses_grouped_visit_flow(decision) else 300,
            )
        except RuntimeError:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao consegui montar a documentacao pendente por dia agora.\n"
                    "Tente novamente em instantes."
                )
            )
        session.selected_visit_day = selected_visit_day
        if records and (self._has_unrestricted_lookup_access(decision) or self._uses_grouped_visit_flow(decision)):
            return self._open_grouped_documentacao_visit_selection(
                sender=sender,
                session=session,
                visit_day=selected_visit_day,
                summary=summary,
                records=records,
            )
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_documentacao_visit_day_response(
                visit_day=selected_visit_day,
                decision=decision,
                summary=summary,
                records=records,
            ),
            return_menu="documentacao_visit_day_menu",
        )

    def _open_grouped_documentacao_visit_selection(
        self,
        *,
        sender: str,
        session: LookupSession,
        visit_day: str,
        summary: DocumentacaoPendenteScopeSummary,
        records: list[DocumentacaoPendenteClientRecord],
    ) -> OutgoingMessage:
        summary_text = self._build_documentacao_visit_day_header_text(
            visit_day=visit_day,
            summary=summary,
            records=records,
        )
        sector_summaries = self._summarize_documentacao_visit_sectors(records)
        gv_options = sorted(
            {
                normalize_stored_scope_value(item.manager_code) or normalize_stored_scope_value(item.seller_code)
                for item in sector_summaries
                if normalize_stored_scope_value(item.manager_code) or normalize_stored_scope_value(item.seller_code)
            },
            key=_sort_scope_code,
        )

        session.selected_visit_day = visit_day
        session.finance_gv_options = tuple(gv_options)
        session.documentacao_visit_sector_summaries = tuple(sector_summaries)
        session.documentacao_visit_records = tuple(records)
        session.documentacao_visit_summary_text = summary_text
        session.selected_documentacao_visit_gv = ""
        session.updated_at = datetime.now(timezone.utc)

        if len(gv_options) == 1:
            session.step = "documentacao_select_visit_sector"
            session.selected_documentacao_visit_gv = gv_options[0]
            self.sessions[sender] = session
            return self._build_grouped_documentacao_visit_sector_menu(
                gv_code=gv_options[0],
                sector_summaries=sector_summaries,
            )

        session.step = "documentacao_select_visit_gv"
        self.sessions[sender] = session
        return self._build_grouped_documentacao_visit_gv_menu(
            summary_text=summary_text,
            gv_options=gv_options,
            sector_summaries=sector_summaries,
        )

    def _build_documentacao_visit_day_header_text(
        self,
        *,
        visit_day: str,
        summary: DocumentacaoPendenteScopeSummary,
        records: list[DocumentacaoPendenteClientRecord],
    ) -> str:
        visit_day_label = _format_visit_day_label(visit_day)
        lines = [f"Documentacao pendente em {visit_day_label}:", ""]
        lines.append(f"Clientes monitorados: {summary.monitored_client_count}")
        lines.append(f"Clientes com pendencia: {summary.pending_client_count}")
        lines.append(f"Documentos faltando: {summary.pending_document_count}")
        lines.append(
            "Resumo pendente: "
            f"CS {summary.contrato_social_pendentes} | "
            f"CPF {summary.cpf_pendentes} | "
            f"RG {summary.rg_pendentes} | "
            f"CR {summary.comprovante_residencia_pendentes} | "
            f"FAC {summary.fachada_pendentes} | "
            f"FC {summary.ficha_cadastro_pendentes}"
        )
        lines.append(f"Documentacao atualizada em: {summary.planilha_atualizada_em or '-'}")
        if records:
            lines.append("")
            lines.append(
                f"Clientes com pendencia: {len(records)} | "
                f"Documentos faltando: {sum(int(record.pending_count or 0) for record in records)}"
            )
        return "\n".join(lines)

    def _summarize_documentacao_visit_sectors(
        self,
        records: list[DocumentacaoPendenteClientRecord],
    ) -> list[DocumentacaoVisitSectorSummary]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            seller_code = normalize_stored_scope_value(record.seller_code)
            manager_code = normalize_stored_scope_value(record.manager_code)
            key = (manager_code, seller_code)
            bucket = grouped.setdefault(
                key,
                {
                    "manager_code": manager_code,
                    "seller_code": seller_code,
                    "client_count": 0,
                    "pending_document_count": 0,
                },
            )
            bucket["client_count"] += 1
            bucket["pending_document_count"] += int(record.pending_count or 0)
        return [
            DocumentacaoVisitSectorSummary(
                seller_code=item["seller_code"],
                manager_code=item["manager_code"],
                client_count=int(item["client_count"]),
                pending_document_count=int(item["pending_document_count"]),
            )
            for item in sorted(grouped.values(), key=lambda item: (_sort_scope_code(item["manager_code"] or item["seller_code"]), _sort_scope_code(item["seller_code"])))
        ]

    def _build_grouped_documentacao_visit_gv_menu(
        self,
        *,
        summary_text: str,
        gv_options: list[str],
        sector_summaries: list[DocumentacaoVisitSectorSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        lines = [summary_text, ""]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
            lines.insert(1, "")
        grouped: dict[str, list[DocumentacaoVisitSectorSummary]] = {}
        for summary_item in sector_summaries:
            group_key = normalize_stored_scope_value(summary_item.manager_code) or normalize_stored_scope_value(summary_item.seller_code)
            grouped.setdefault(group_key, []).append(summary_item)

        lines.append(f"GVs com pendencia documental: {len(gv_options)}")
        lines.append("")
        lines.append("Escolha o GV para ver os setores com pendencia.")
        return OutgoingMessage(
            kind="menu",
            title="Documentacao por Dia",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro setores, clientes e documentos faltando. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{DOCUMENTACAO_VISIT_GV_PICK_PREFIX}{index}",
                    title=_format_visit_manager_summary_label(gv_code),
                    description=(
                        f"{len(grouped.get(gv_code, []))} setor(es) | "
                        f"{sum(item.client_count for item in grouped.get(gv_code, []))} cliente(s) | "
                        f"{sum(item.pending_document_count for item in grouped.get(gv_code, []))} doc(s)"
                    ),
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_grouped_documentacao_visit_sector_menu(
        self,
        *,
        gv_code: str,
        sector_summaries: list[DocumentacaoVisitSectorSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        normalized_gv_code = normalize_stored_scope_value(gv_code)
        grouped_items = [
            item
            for item in sector_summaries
            if (normalize_stored_scope_value(item.manager_code) or normalize_stored_scope_value(item.seller_code))
            == normalized_gv_code
        ]
        lines = []
        if invalid_selection:
            lines.append("Nao entendi essa opcao.")
            lines.append("")
        lines.append(_format_visit_manager_summary_label(normalized_gv_code))
        lines.append(
            f"Setores com pendencia: {len(grouped_items)} | "
            f"Clientes com pendencia: {sum(item.client_count for item in grouped_items)} | "
            f"Documentos faltando: {sum(item.pending_document_count for item in grouped_items)}"
        )
        lines.append("")
        lines.append("Escolha o setor para ver os clientes com documentacao pendente.")
        return OutgoingMessage(
            kind="menu",
            title="Documentacao por Setor",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro clientes e documentos faltando do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{DOCUMENTACAO_VISIT_SELLER_PICK_PREFIX}{index}",
                    title=_format_sector_scope_label(item.seller_code),
                    description=f"{item.client_count} cliente(s) | {item.pending_document_count} doc(s)",
                    shortcut=str(index),
                )
                for index, item in enumerate(grouped_items, start=1)
            ),
        )

    def _build_grouped_documentacao_visit_sector_response(
        self,
        *,
        visit_day: str,
        sector_summary: DocumentacaoVisitSectorSummary,
        records: list[DocumentacaoPendenteClientRecord],
    ) -> OutgoingMessage:
        normalized_seller_code = normalize_stored_scope_value(sector_summary.seller_code)
        filtered_records = sorted(
            [
                record
                for record in records
                if normalize_stored_scope_value(record.seller_code) == normalized_seller_code
            ],
            key=lambda item: (_sort_numeric_text(item.cod_pdv), str(item.nome or "").lower()),
        )
        visit_day_label = _format_visit_day_label(visit_day)
        lines = [
            f"Documentacao pendente em {visit_day_label}:",
            "",
            f"{_format_visit_manager_summary_label(sector_summary.manager_code, sector_summary.seller_code)} | "
            f"Setor {(split_scope_pair(sector_summary.seller_code) or ('', '-'))[1]}",
            f"Clientes com pendencia: {len(filtered_records)} | "
            f"Documentos faltando: {sum(int(record.pending_count or 0) for record in filtered_records)}",
            "",
            "Clientes com documentacao pendente:",
        ]
        if not filtered_records:
            lines.append("Nenhum cliente com documentacao pendente nesse setor.")
            return OutgoingMessage(text="\n".join(lines))

        for index, record in enumerate(filtered_records, start=1):
            lines.append(
                f"{index}. Codigo {record.cod_pdv} | {record.nome or '-'} | "
                f"Pendencias {record.pending_count} | Falta: {_format_documentacao_pending_docs(record.pending_docs)}"
            )
        return OutgoingMessage(text="\n".join(lines))

    def _build_giro_visit_day_header_text(
        self,
        *,
        visit_day: str,
        summary: GiroScopeSummary,
        opportunities: list[GiroVisitOpportunity],
        giro_updated_at: str,
    ) -> str:
        visit_day_label = _format_visit_day_label(visit_day)
        total_caixas = (
            summary.litrinho_monitored_count
            + summary.inteira_monitored_count
            + summary.litrao_monitored_count
        )
        total_ok = (
            summary.litrinho_ok_count
            + summary.inteira_ok_count
            + summary.litrao_ok_count
        )
        total_gap = _sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )
        lines = [f"Oportunidade de giro em {visit_day_label}:", "Tipo: Giro de Vasilhame", ""]
        lines.append(f"Clientes monitorados: {summary.client_count}")
        lines.append(f"Caixas na rota: {_format_quantity(total_caixas)}")
        lines.append(f"Caixas OK: {_format_quantity(total_ok)}")
        lines.append(f"Caixas faltando para bater o giro: {total_gap}")
        self._append_giro_summary_lines(lines, summary, compact=False)
        lines.append("")
        lines.append(
            f"Clientes com oportunidade: {len(opportunities)} | "
            f"Caixas com giro: {_sum_formatted_amounts(*(item.total_caixas for item in opportunities)) if opportunities else '0'} | "
            f"Faltam: {_sum_formatted_amounts(*(item.gap_caixas for item in opportunities)) if opportunities else '0'}"
        )
        if giro_updated_at:
            lines.append(f"Giro atualizado em: {giro_updated_at}")
        return "\n".join(lines)

    def _collect_giro_visit_day_opportunities(
        self,
        *,
        visit_day: str,
        decision: AccessDecision,
        records: list[DClienteRecord],
    ) -> tuple[list[GiroVisitOpportunity], str]:
        giro_summaries, giro_updated_at = self._build_visit_day_giro_summaries(decision, records)
        try:
            seller_summaries = self.query_service.list_visit_day_seller_summaries(
                visit_day=visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=1000,
            )
        except RuntimeError:
            seller_summaries = []

        manager_by_seller = {
            normalize_stored_scope_value(summary_item.seller_code): normalize_stored_scope_value(summary_item.manager_code)
            for summary_item in seller_summaries
            if normalize_stored_scope_value(summary_item.seller_code)
        }

        opportunities: list[GiroVisitOpportunity] = []
        for record in records:
            client_summary = giro_summaries.get((_normalize_filial(record.filial), _normalize_cod_pdv(record.cod_pdv)))
            if client_summary is None:
                continue
            setor_code, total_caixas, gap_caixas, gap_detail = client_summary
            if not _is_positive_quantity(total_caixas) or not _is_positive_quantity(gap_caixas):
                continue
            seller_code = normalize_stored_scope_value(f"{_normalize_filial(record.filial)}_{setor_code}")
            opportunities.append(
                GiroVisitOpportunity(
                    manager_code=manager_by_seller.get(seller_code, ""),
                    seller_code=seller_code,
                    setor_code=setor_code or "-",
                    cod_pdv=str(record.cod_pdv or "").strip(),
                    client_name=record.nome_fantasia or record.razao_social or "-",
                    total_caixas=total_caixas,
                    gap_caixas=gap_caixas,
                    gap_detail=gap_detail,
                )
            )

        opportunities.sort(
            key=lambda item: (
                _sort_scope_code(item.manager_code or item.seller_code),
                _sort_scope_code(item.seller_code),
                _sort_numeric_text(item.cod_pdv),
                str(item.client_name or "").lower(),
            )
        )
        return opportunities, giro_updated_at

    def _summarize_giro_visit_sectors(
        self,
        opportunities: list[GiroVisitOpportunity],
    ) -> list[GiroVisitSectorSummary]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for item in opportunities:
            key = (normalize_stored_scope_value(item.manager_code), normalize_stored_scope_value(item.seller_code))
            bucket = grouped.setdefault(
                key,
                {
                    "seller_code": normalize_stored_scope_value(item.seller_code),
                    "manager_code": normalize_stored_scope_value(item.manager_code),
                    "client_count": 0,
                    "caixas": [],
                    "gaps": [],
                },
            )
            bucket["client_count"] += 1
            bucket["caixas"].append(item.total_caixas)
            bucket["gaps"].append(item.gap_caixas)

        return [
            GiroVisitSectorSummary(
                seller_code=str(bucket["seller_code"]),
                manager_code=str(bucket["manager_code"]),
                client_count=int(bucket["client_count"]),
                total_caixas=_sum_formatted_amounts(*bucket["caixas"]),
                total_gap=_sum_formatted_amounts(*bucket["gaps"]),
            )
            for _key, bucket in sorted(
                grouped.items(),
                key=lambda item: (
                    _sort_scope_code(item[0][0] or item[0][1]),
                    _sort_scope_code(item[0][1]),
                ),
            )
        ]

    def _open_grouped_giro_visit_selection(
        self,
        *,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        visit_day: str,
        summary: GiroScopeSummary,
        records: list[DClienteRecord],
    ) -> OutgoingMessage:
        opportunities, giro_updated_at = self._collect_giro_visit_day_opportunities(
            visit_day=visit_day,
            decision=decision,
            records=records,
        )
        summary_text = self._build_giro_visit_day_header_text(
            visit_day=visit_day,
            summary=summary,
            opportunities=opportunities,
            giro_updated_at=giro_updated_at,
        )
        if not opportunities:
            return self._with_post_result_navigation(
                sender,
                session,
                OutgoingMessage(text=f"{summary_text}\n\nNenhum cliente com oportunidade de giro nesse dia."),
                return_menu="giro_visit_day_menu",
            )

        sector_summaries = self._summarize_giro_visit_sectors(opportunities)
        gv_options = sorted(
            {
                normalize_stored_scope_value(summary_item.manager_code) or normalize_stored_scope_value(summary_item.seller_code)
                for summary_item in sector_summaries
                if normalize_stored_scope_value(summary_item.manager_code) or normalize_stored_scope_value(summary_item.seller_code)
            },
            key=_sort_scope_code,
        )

        session.selected_visit_day = visit_day
        session.finance_gv_options = tuple(gv_options)
        session.giro_visit_sector_summaries = tuple(sector_summaries)
        session.giro_visit_summary_text = summary_text
        session.selected_giro_visit_gv = ""
        session.updated_at = datetime.now(timezone.utc)

        if len(gv_options) == 1:
            session.step = "giro_select_visit_sector"
            session.selected_giro_visit_gv = gv_options[0]
            self.sessions[sender] = session
            return self._build_grouped_giro_visit_sector_menu(
                summary_text=summary_text,
                gv_code=gv_options[0],
                sector_summaries=sector_summaries,
            )

        session.step = "giro_select_visit_gv"
        self.sessions[sender] = session
        return self._build_grouped_giro_visit_gv_menu(
            summary_text=summary_text,
            gv_options=gv_options,
            sector_summaries=sector_summaries,
        )

    def _build_grouped_giro_visit_gv_menu(
        self,
        *,
        summary_text: str,
        gv_options: list[str],
        sector_summaries: list[GiroVisitSectorSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        lines = [summary_text, ""]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
            lines.insert(1, "")
        grouped: dict[str, list[GiroVisitSectorSummary]] = {}
        for summary in sector_summaries:
            group_key = normalize_stored_scope_value(summary.manager_code) or normalize_stored_scope_value(summary.seller_code)
            grouped.setdefault(group_key, []).append(summary)

        lines.append(f"GVs com oportunidade: {len(gv_options)}")
        lines.append("")
        lines.append("Escolha o GV para ver os setores com oportunidade.")
        return OutgoingMessage(
            kind="menu",
            title="Giro por Dia",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro setores, clientes, caixas e faltam daquele GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{GIRO_VISIT_GV_PICK_PREFIX}{index}",
                    title=_format_visit_manager_summary_label(gv_code),
                    description=(
                        f"{len(grouped.get(gv_code, []))} setor(es) | "
                        f"{sum(item.client_count for item in grouped.get(gv_code, []))} cliente(s) | "
                        f"Caixas {_sum_formatted_amounts(*(item.total_caixas for item in grouped.get(gv_code, []))) if grouped.get(gv_code, []) else '0'} | "
                        f"Faltam {_sum_formatted_amounts(*(item.total_gap for item in grouped.get(gv_code, []))) if grouped.get(gv_code, []) else '0'}"
                    ),
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_grouped_giro_visit_sector_menu(
        self,
        *,
        summary_text: str,
        gv_code: str,
        sector_summaries: list[GiroVisitSectorSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        normalized_gv_code = normalize_stored_scope_value(gv_code)
        grouped_items = [
            item
            for item in sector_summaries
            if (normalize_stored_scope_value(item.manager_code) or normalize_stored_scope_value(item.seller_code))
            == normalized_gv_code
        ]
        lines = []
        if invalid_selection:
            lines.append("Nao entendi essa opcao.")
            lines.append("")
        lines.append(_format_visit_manager_summary_label(normalized_gv_code))
        lines.append(
            f"Setores com oportunidade: {len(grouped_items)} | "
            f"Clientes com oportunidade: {sum(item.client_count for item in grouped_items)} | "
            f"Caixas {_sum_formatted_amounts(*(item.total_caixas for item in grouped_items)) if grouped_items else '0'} | "
            f"Faltam {_sum_formatted_amounts(*(item.total_gap for item in grouped_items)) if grouped_items else '0'}"
        )
        lines.append("")
        lines.append("Escolha o setor para ver os clientes com oportunidade.")
        return OutgoingMessage(
            kind="menu",
            title="Giro por Setor",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro clientes, caixas e faltam do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{GIRO_VISIT_SELLER_PICK_PREFIX}{index}",
                    title=_format_sector_scope_label(item.seller_code),
                    description=(
                        f"{item.client_count} cliente(s) | Caixas {item.total_caixas} | Faltam {item.total_gap}"
                    ),
                    shortcut=str(index),
                )
                for index, item in enumerate(grouped_items, start=1)
            ),
        )

    def _build_grouped_giro_visit_sector_response(
        self,
        *,
        decision: AccessDecision,
        visit_day: str,
        sector_summary: GiroVisitSectorSummary,
    ) -> OutgoingMessage:
        try:
            records = self.query_service.list_clients_by_visit_day_and_seller(
                visit_day=visit_day,
                seller_code=sector_summary.seller_code,
                manager_code=sector_summary.manager_code,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=5000,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir os clientes com oportunidade desse setor agora.\n"
                    "Tente novamente em instantes."
                )
            )

        opportunities, giro_updated_at = self._collect_giro_visit_day_opportunities(
            visit_day=visit_day,
            decision=decision,
            records=records,
        )
        filtered_opportunities = [
            item
            for item in opportunities
            if normalize_stored_scope_value(item.seller_code) == normalize_stored_scope_value(sector_summary.seller_code)
        ]
        visit_day_label = _format_visit_day_label(visit_day)
        lines = [
            f"Oportunidade de giro em {visit_day_label}:",
            "Tipo: Giro de Vasilhame",
            "",
            f"{_format_visit_manager_summary_label(sector_summary.manager_code, sector_summary.seller_code)} | "
            f"Setor {(split_scope_pair(sector_summary.seller_code) or ('', '-'))[1]}",
            f"Clientes com oportunidade: {len(filtered_opportunities)} | "
            f"Caixas com giro: {_sum_formatted_amounts(*(item.total_caixas for item in filtered_opportunities)) if filtered_opportunities else '0'} | "
            f"Faltam: {_sum_formatted_amounts(*(item.gap_caixas for item in filtered_opportunities)) if filtered_opportunities else '0'}",
        ]
        if giro_updated_at:
            lines.append(f"Giro atualizado em: {giro_updated_at}")
        lines.append("")
        lines.append("Clientes com oportunidade de giro:")
        if not filtered_opportunities:
            lines.append("Nenhum cliente com oportunidade de giro nesse setor.")
            return OutgoingMessage(text="\n".join(lines))

        for index, item in enumerate(filtered_opportunities, start=1):
            _append_giro_client_block(
                lines,
                index=index,
                client_name=item.client_name,
                cod_pdv=item.cod_pdv,
                total_caixas=item.total_caixas,
                gap_caixas=item.gap_caixas,
                gap_detail=item.gap_detail,
            )
        return OutgoingMessage(text="\n".join(lines))

    def _open_inadimplencia_visit_day_conversation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        requested_day_label: str = "",
    ) -> OutgoingMessage:
        access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
        if access_error is not None:
            self._reset_session(sender)
            return access_error
        try:
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
        except RuntimeError:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir os dias da inadimplencia agora.\n"
                    "Tente novamente em instantes."
                )
            )
        visit_days = _normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao encontrei dias de visita disponiveis para consultar a inadimplencia.\n"
                    "Se quiser fazer outra consulta, envie MENU."
                )
            )

        self._prepare_search_session(session, search_context="inadimplencia")
        session.step = "awaiting_inadimplencia_visit_day_selection"
        session.visit_day_options = tuple(visit_days)
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session

        if not requested_day_label and len(visit_days) == 1:
            return self._apply_inadimplencia_visit_day_selection(
                sender=sender,
                session=session,
                decision=decision,
                selected_visit_day=visit_days[0],
            )
        if requested_day_label:
            selected_visit_day = _match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_inadimplencia_visit_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    selected_visit_day=selected_visit_day,
                )
        return self._build_inadimplencia_visit_day_menu(visit_days=visit_days)

    def _open_giro_visit_day_conversation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        requested_day_label: str = "",
    ) -> OutgoingMessage:
        access_error = self._ensure_scoped_lookup_access(decision, search_context="giro")
        if access_error is not None:
            self.sessions[sender] = session
            return access_error
        try:
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
        except RuntimeError:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao consegui carregar os dias de visita do seu giro agora.\n"
                    "Tente novamente em instantes."
                )
            )
        visit_days = _normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao encontrei dias de visita disponiveis para consultar o giro.\n"
                    "Se quiser tentar outra consulta, envie MENU."
                )
            )
        session.step = "awaiting_giro_visit_day_selection"
        session.search_context = "giro"
        session.selected_visit_day = ""
        session.visit_day_options = tuple(visit_days)
        self._remember_last_context(
            session,
            intent="giro_visit_day",
            search_context="giro",
            visit_day=requested_day_label or session.last_visit_day or _format_visit_day_label(visit_days[0]),
        )
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        if not requested_day_label and len(visit_days) == 1:
            return self._apply_giro_visit_day_selection(
                sender=sender,
                session=session,
                decision=decision,
                selected_visit_day=visit_days[0],
            )
        if requested_day_label:
            selected_visit_day = _match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_giro_visit_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    selected_visit_day=selected_visit_day,
                )
        return self._build_giro_visit_day_menu(visit_days=visit_days)

    def _open_documentacao_visit_day_conversation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        requested_day_label: str = "",
    ) -> OutgoingMessage:
        access_error = self._ensure_scoped_lookup_access(decision, search_context="documentacao")
        if access_error is not None:
            self.sessions[sender] = session
            return access_error
        try:
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
        except RuntimeError:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao consegui carregar os dias de visita da documentacao agora.\n"
                    "Tente novamente em instantes."
                )
            )

        visit_days = _normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao encontrei dias de visita disponiveis para consultar a documentacao pendente.\n"
                    "Se quiser fazer outra consulta, envie MENU."
                )
            )

        self._prepare_search_session(session, search_context="documentacao")
        session.step = "awaiting_documentacao_visit_day_selection"
        session.visit_day_options = tuple(visit_days)
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session

        if not requested_day_label and len(visit_days) == 1:
            return self._apply_documentacao_visit_day_selection(
                sender=sender,
                session=session,
                decision=decision,
                selected_visit_day=visit_days[0],
            )
        if requested_day_label:
            selected_visit_day = _match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_documentacao_visit_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    selected_visit_day=selected_visit_day,
                )
        return self._build_documentacao_visit_day_menu(visit_days=visit_days)

    def _open_visit_day_conversation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        requested_day_label: str = "",
    ) -> OutgoingMessage:
        access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
        if access_error is not None:
            self._reset_session(sender)
            return access_error
        raw_visit_days = self.query_service.list_visit_days(
            allowed_sectors=self._allowed_sectors(decision),
            allowed_gv_vdes=self._allowed_gv_vdes(decision),
            limit=10,
        )
        visit_days = _normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "Nao encontrei dias de visita disponiveis para voce no momento.\n"
                    "Se quiser fazer outra consulta, envie MENU."
                )
            )
        self._prepare_search_session(session, search_context=session.search_context or "cliente")
        session.step = "awaiting_visit_day_selection"
        session.visit_day_options = tuple(visit_days)
        self._remember_last_context(
            session,
            intent="visit_day",
            search_context="cliente",
            visit_day=requested_day_label or session.last_visit_day or _current_visit_day_label(),
        )
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        if not requested_day_label and len(visit_days) == 1:
            return self._apply_visit_day_selection(
                sender=sender,
                session=session,
                decision=decision,
                selected_visit_day=visit_days[0],
            )
        if requested_day_label:
            selected_visit_day = _match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_visit_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    selected_visit_day=selected_visit_day,
                )
        return self._build_visit_day_menu(decision=decision, visit_days=visit_days)

    def _prepare_finance_session(self, session: LookupSession) -> None:
        session.step = "finance_select_action"
        session.search_context = "inadimplencia"
        self._clear_clarification_state(session)
        session.filial = ""
        session.fantasia_query = ""
        session.fantasia_results = ()
        session.inadimplencia_client_summaries = ()
        session.inadimplencia_total_available = 0
        session.inadimplencia_list_context = ""
        session.inadimplencia_page = 1
        session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
        session.comodato_client_summaries = ()
        session.selected_visit_day = ""
        session.visit_day_options = ()
        session.visit_seller_summaries = ()
        session.visit_group_summaries = ()
        session.selected_visit_gv = ""
        session.finance_gv_options = ()
        session.summary_filial_options = ()
        session.visit_risk_day_options = ()
        session.visit_risk_summaries = ()
        session.selected_visit_risk_gv = ""
        session.selected_visit_risk_token = ""
        session.selected_visit_risk_label = ""
        session.payip_pending_action = ""
        session.payip_pending_invoice = ""
        session.payip_pending_client_code = ""
        session.payip_pending_filial = ""
        session.payip_pending_status = ""
        session.payip_pending_date_start = ""
        session.payip_pending_date_end = ""
        session.payip_pending_amount = ""
        session.payip_pending_day = ""
        session.payip_pending_tolerance = ""
        session.payip_pix_payloads = ()
        session.payip_charge_filial = ""
        session.payip_charge_client_code = ""
        session.payip_charge_external_id = ""
        session.payip_charge_client_name = ""
        session.payip_charge_tax_payer_id = ""
        session.payip_charge_invoice = ""
        session.payip_charge_amount = ""
        session.payip_charge_due_date = ""
        session.payip_charge_rate_amount = ""
        session.payip_charge_interest_perc = ""
        session.updated_at = datetime.now(timezone.utc)

    def _build_finance_today_clarification(self) -> OutgoingMessage:
        return OutgoingMessage(
            text=(
                "Quando voce diz 'financeiro de hoje', eu posso te mostrar:\n"
                "1. Vencimentos de hoje\n"
                "2. Visitas com risco hoje\n"
                "3. Resumo financeiro\n"
                "Me responda com o numero ou com a opcao."
            )
        )

    def _build_expired_session_prompt(self, *, previous_step: str) -> OutgoingMessage:
        _ = previous_step
        return OutgoingMessage(
            text=(
                "A conversa anterior expirou e eu perdi o contexto.\n"
                "Me diga novamente o que voce quer, por exemplo: cliente, inadimplencia, giro, visitas ou financeiro.\n"
                "Se preferir, envie MENU."
            )
        )

    def _clear_clarification_state(self, session: LookupSession) -> None:
        session.clarification_title = ""
        session.clarification_prompt = ""
        session.clarification_footer = ""
        session.clarification_options = ()

    def _remember_last_context(
        self,
        session: LookupSession,
        *,
        intent: str | None = None,
        search_context: str | None = None,
        query_text: str | None = None,
        client_filial: str | None = None,
        client_cod_pdv: str | None = None,
        client_name: str | None = None,
        visit_day: str | None = None,
    ) -> None:
        if intent:
            session.last_intent = intent
        if search_context:
            session.last_search_context = search_context
        if query_text is not None:
            session.last_query_text = " ".join(str(query_text or "").strip().split())
        if client_filial:
            session.last_client_filial = client_filial
        if client_cod_pdv:
            session.last_client_cod_pdv = client_cod_pdv
        if client_name:
            session.last_client_name = " ".join(str(client_name or "").strip().split())
        if visit_day:
            session.last_visit_day = visit_day
        session.last_context_updated_at = datetime.now(timezone.utc)

    def _has_recent_last_context(self, session: LookupSession) -> bool:
        if session.last_context_updated_at is None:
            return False
        return datetime.now(timezone.utc) - session.last_context_updated_at <= min(
            self.session_ttl,
            timedelta(minutes=10),
        )

    def _decision_scope_cache_key(self, decision: AccessDecision, *extra: Any) -> tuple[Any, ...]:
        return (
            tuple(sorted(str(role) for role in decision.roles)),
            tuple(sorted(str(sector) for sector in decision.sectors)),
            tuple(sorted(str(scope) for scope in decision.gv_vdes)),
            *extra,
        )

    def _get_cached_response(self, cache_key: tuple[Any, ...]) -> OutgoingMessage | None:
        cached = self._response_cache.get(cache_key)
        if cached is None:
            return None
        cached_at, outgoing = cached
        if datetime.now(timezone.utc) - cached_at > self.response_cache_ttl:
            self._response_cache.pop(cache_key, None)
            return None
        return outgoing

    def _store_cached_response(
        self,
        cache_key: tuple[Any, ...],
        outgoing: OutgoingMessage,
    ) -> OutgoingMessage:
        normalized_text = _normalize_choice(outgoing.text)
        if outgoing.kind == "text" and not normalized_text.startswith("nao consegui"):
            self._response_cache[cache_key] = (datetime.now(timezone.utc), outgoing)
        return outgoing

    def _open_scope_inadimplencia_list(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
        if access_error is not None:
            self._reset_session(sender)
            return access_error
        self._remember_last_context(
            session,
            intent="inadimplencia_list",
            search_context="inadimplencia",
        )
        return self._open_inadimplencia_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
            order_by="total_pendente",
            header_text=f"Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.",
            empty_text=(
                "No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\n"
                "Se quiser tentar outra consulta, envie MENU."
            ),
            page=1,
            page_size=INADIMPLENCIA_PAGE_SIZE,
            list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
        )

    def _build_client_clarification_options(
        self,
        session: LookupSession,
        decision: AccessDecision,
    ) -> list[InteractiveOption]:
        options: list[InteractiveOption] = []
        if (
            self._has_recent_last_context(session)
            and session.last_client_filial
            and session.last_client_cod_pdv
            and self._has_area_access(decision, "cliente")
        ):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_LAST_CLIENT_RECORD,
                    title=f"Reabrir {session.last_client_name or 'o ultimo cliente'}",
                    description=(
                        f"Revenda {session.last_client_filial} | NB {session.last_client_cod_pdv}"
                    ),
                )
            )
        if self._has_area_access(decision, "cliente"):
            options.append(
                InteractiveOption(
                    option_id=MENU_SEARCH,
                    title="Buscar Cadastro",
                    description="Consultar os dados do cliente",
                )
            )
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_GIRO_CLIENT,
                    title="Giro por Cliente",
                    description="Buscar giro por nome, CPF ou NB",
                )
            )
        if self._has_area_access(decision, "inadimplencia"):
            options.append(
                InteractiveOption(
                    option_id=MENU_INADIMPLENCIA,
                    title="Inadimplencia do Cliente",
                    description="Consultar titulos em aberto",
                )
            )
        if self._has_area_access(decision, "comodato"):
            options.append(
                InteractiveOption(
                    option_id=MENU_COMODATOS,
                    title="Comodatos do Cliente",
                    description="Consultar pendencias de comodato",
                )
            )
        return options

    def _build_list_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        options: list[InteractiveOption] = []
        if self._has_area_access(decision, "inadimplencia"):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_SCOPE_INADIMPLENCIA_LIST,
                    title="Lista de Inadimplentes",
                    description="Ver os clientes inadimplentes da sua base",
                )
            )
        if self._can_use_visit_menu(decision) and self._has_area_access(decision, "cliente"):
            options.append(
                InteractiveOption(
                    option_id=MENU_VISIT_DAY,
                    title="Visitas do Dia",
                    description="Ver a lista de visitas programadas",
                )
            )
        return options

    def _build_base_clarification_options(
        self,
        session: LookupSession,
        decision: AccessDecision,
    ) -> list[InteractiveOption]:
        options: list[InteractiveOption] = []
        if self._has_area_access(decision, "inadimplencia"):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_SCOPE_INADIMPLENCIA_LIST,
                    title="Inadimplentes da Base",
                    description="Ver a lista de clientes inadimplentes",
                )
            )
        for option in self._build_summary_clarification_options(decision):
            if option.option_id not in {item.option_id for item in options}:
                options.append(option)

        recent_intent = session.last_intent if self._has_recent_last_context(session) else ""
        if self._can_use_finance_menu(decision):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_GIRO_FINANCE_TOTAL,
                    title="Giro da Base",
                    description="Ver o giro consolidado da base total",
                )
            )
        elif recent_intent.startswith("manager") or self._is_gerente_vendas(decision):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_GIRO_MANAGER_TOTAL,
                    title="Giro da Gerencia",
                    description="Ver o giro consolidado do seu GV",
                )
            )
        elif recent_intent.startswith("director") or self._is_diretor_comercial(decision):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_GIRO_DIRECTOR_BY_GV,
                    title="Giro dos Gerentes",
                    description="Ver o giro agrupado por GV",
                )
            )
        return options

    def _build_intent_clarification_menu(
        self,
        *,
        session: LookupSession,
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        prompt = session.clarification_prompt or "Me confirme qual caminho voce quer seguir."
        if invalid_selection:
            prompt = _invalid_option_text(prompt)
        return OutgoingMessage(
            kind="menu",
            title=session.clarification_title or "Me confirma uma coisa",
            text=prompt,
            footer=session.clarification_footer or "Use A ou ANT para voltar, ou MENU para ir ao inicio.",
            button_text="Escolher",
            options=session.clarification_options,
        )

    def _open_intent_clarification(
        self,
        sender: str,
        session: LookupSession,
        *,
        title: str,
        prompt: str,
        options: list[InteractiveOption],
        footer: str = "",
    ) -> OutgoingMessage:
        normalized_options = tuple(
            InteractiveOption(
                option_id=option.option_id,
                title=option.title,
                description=option.description,
                shortcut=option.shortcut or str(index),
            )
            for index, option in enumerate(options, start=1)
        )
        session.step = "awaiting_intent_clarification"
        session.return_menu = ""
        session.clarification_title = title
        session.clarification_prompt = prompt
        session.clarification_footer = footer or "Use A ou ANT para voltar, ou MENU para ir ao inicio."
        session.clarification_options = normalized_options
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_intent_clarification_menu(session=session)

    def _build_summary_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        options: list[InteractiveOption] = []
        if self._can_use_finance_menu(decision):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_SUMMARY_FINANCE,
                    title="Resumo Financeiro",
                    description="Ver o painel da base total",
                )
            )
        if self._is_gerente_vendas(decision) and self._can_use_gv_summary_menu(decision):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_SUMMARY_MANAGER,
                    title="Resumo Total da Gerencia",
                    description="Ver o consolidado do seu GV",
                )
            )
        if self._is_diretor_comercial(decision) and self._can_use_gv_summary_menu(decision):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_SUMMARY_DIRECTOR,
                    title="Resumo Total da Diretoria",
                    description="Ver o consolidado da diretoria",
                )
            )
        if self._can_use_seller_summary_menu(decision):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_SUMMARY_SELLER,
                    title="Resumo da Carteira",
                    description="Ver o resumo da sua carteira",
                )
            )
        return options

    def _build_today_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        current_day_label = _current_visit_day_label()
        options: list[InteractiveOption] = []
        if self._can_use_finance_menu(decision):
            options.extend(
                (
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_FINANCE_DUE,
                        title="Vencimentos de Hoje",
                        description="Ver quem vence hoje na base total",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_FINANCE_RISK,
                        title="Visitas com Risco Hoje",
                        description=f"Ver risco financeiro em {current_day_label}",
                    ),
                )
            )
        if self._is_gerente_vendas(decision) and self._can_use_visit_menu(decision):
            options.extend(
                (
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_MANAGER_VISITS,
                        title="Visitas de Hoje da Gerencia",
                        description=f"Ver a rota de {current_day_label} da gerencia",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_MANAGER_RISK,
                        title="Risco Hoje da Gerencia",
                        description=f"Ver os setores com risco em {current_day_label}",
                    ),
                )
            )
        if self._is_diretor_comercial(decision) and self._can_use_visit_menu(decision):
            options.extend(
                (
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_DIRECTOR_VISITS,
                        title="Visitas de Hoje da Diretoria",
                        description=f"Ver a rota de {current_day_label} da diretoria",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_DIRECTOR_RISK,
                        title="Risco Hoje da Diretoria",
                        description=f"Ver risco por GV em {current_day_label}",
                    ),
                )
            )
        if self._can_use_seller_summary_menu(decision):
            options.extend(
                (
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_SELLER_VISITS,
                        title="Visitas de Hoje",
                        description=f"Ver a sua rota de {current_day_label}",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_TODAY_SELLER_RISK,
                        title="Risco Hoje da Carteira",
                        description=f"Ver os clientes com risco em {current_day_label}",
                    ),
                )
            )
        return options

    def _build_giro_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        options: list[InteractiveOption] = []
        if self._has_area_access(decision, "cliente"):
            options.append(
                InteractiveOption(
                    option_id=CLARIFY_GIRO_CLIENT,
                    title="Giro por Cliente",
                    description="Buscar por CPF, nome ou filial e NB",
                )
            )
        if self._can_use_finance_menu(decision):
            options.extend(
                (
                    InteractiveOption(
                        option_id=CLARIFY_GIRO_FINANCE_TOTAL,
                        title="Giro Total da Base",
                        description="Ver o consolidado da base total",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_GIRO_FINANCE_BY_FILIAL,
                        title="Giro por Filial da Base",
                        description="Separar o giro por revenda",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_GIRO_FINANCE_BY_GV,
                        title="Giro por GV da Base",
                        description="Separar o giro por chave filial-GV",
                    ),
                )
            )
        if self._is_gerente_vendas(decision):
            options.extend(
                (
                    InteractiveOption(
                        option_id=CLARIFY_GIRO_MANAGER_TOTAL,
                        title="Giro Total da Gerencia",
                        description="Ver o consolidado do seu GV",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_GIRO_MANAGER_BY_FILIAL,
                        title="Giro por Filial da Gerencia",
                        description="Separar o giro da gerencia por revenda",
                    ),
                )
            )
        if self._is_diretor_comercial(decision):
            options.extend(
                (
                    InteractiveOption(
                        option_id=CLARIFY_GIRO_DIRECTOR_BY_GV,
                        title="Giro por GV da Diretoria",
                        description="Consolidar o giro por GV",
                    ),
                    InteractiveOption(
                        option_id=CLARIFY_GIRO_DIRECTOR_BY_FILIAL,
                        title="Giro por Filial da Diretoria",
                        description="Consolidar o giro por revenda",
                    ),
                )
            )
        return options

    def _maybe_handle_idle_low_confidence_request(
        self,
        sender: str,
        session: LookupSession,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        tokens = _normalized_tokens(normalized)

        if self._can_use_finance_menu(decision) and _looks_like_finance_request(normalized):
            return None

        if _looks_like_client_short_request(normalized):
            if (
                self._has_recent_last_context(session)
                and normalized in {"esse cliente", "desse cliente", "cliente atual"}
                and session.last_client_filial
                and session.last_client_cod_pdv
            ):
                return self._run_intent_clarification_option(
                    sender=sender,
                    session=session,
                    decision=decision,
                    option_id=CLARIFY_LAST_CLIENT_RECORD,
                )
            options = self._build_client_clarification_options(session, decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(
                    sender=sender,
                    session=session,
                    decision=decision,
                    option_id=options[0].option_id,
                )
            if len(options) > 1:
                return self._open_intent_clarification(
                    sender=sender,
                    session=session,
                    title="Cliente",
                    prompt="Quando voce diz cliente, qual consulta voce quer abrir?",
                    options=options,
                )

        if _looks_like_list_short_request(normalized):
            if self._has_recent_last_context(session):
                if session.last_search_context == "inadimplencia" or session.last_intent in {
                    "inadimplencia_list",
                    "finance_summary",
                    "manager_summary",
                    "director_summary",
                    "seller_summary",
                }:
                    return self._open_scope_inadimplencia_list(
                        sender=sender,
                        session=session,
                        decision=decision,
                    )
                if session.last_intent == "visit_day" and self._can_use_visit_menu(decision):
                    return self._open_visit_day_conversation(
                        sender=sender,
                        session=session,
                        decision=decision,
                        requested_day_label=session.last_visit_day or _current_visit_day_label(),
                    )
            options = self._build_list_clarification_options(decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(
                    sender=sender,
                    session=session,
                    decision=decision,
                    option_id=options[0].option_id,
                )
            if len(options) > 1:
                return self._open_intent_clarification(
                    sender=sender,
                    session=session,
                    title="Lista",
                    prompt="Qual lista voce quer ver agora?",
                    options=options,
                )

        if _looks_like_base_short_request(normalized):
            options = self._build_base_clarification_options(session, decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(
                    sender=sender,
                    session=session,
                    decision=decision,
                    option_id=options[0].option_id,
                )
            if len(options) > 1:
                return self._open_intent_clarification(
                    sender=sender,
                    session=session,
                    title="Base",
                    prompt="Quando voce diz base, qual visao voce quer abrir?",
                    options=options,
                )

        if (
            self._can_use_finance_menu(decision)
            and not self._can_use_gv_summary_menu(decision)
            and {"resumo"} & tokens
            and {"gv"} & tokens
        ):
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            return self._open_finance_gv_summary_selection(
                sender=sender,
                session=session,
                decision=decision,
            )

        if _looks_like_summary_short_request(normalized):
            options = self._build_summary_clarification_options(decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(
                    sender=sender,
                    session=session,
                    decision=decision,
                    option_id=options[0].option_id,
                )
            if len(options) > 1:
                return self._open_intent_clarification(
                    sender=sender,
                    session=session,
                    title="Resumo",
                    prompt="Quando voce diz resumo, qual deles voce quer ver?",
                    options=options,
                )

        if _looks_like_today_short_request(normalized):
            options = self._build_today_clarification_options(decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(
                    sender=sender,
                    session=session,
                    decision=decision,
                    option_id=options[0].option_id,
                )
            if len(options) > 1:
                return self._open_intent_clarification(
                    sender=sender,
                    session=session,
                    title="Hoje",
                    prompt="Quando voce diz hoje, qual consulta voce quer abrir?",
                    options=options,
                )

        if _looks_like_today_risk_short_request(normalized):
            options = [
                option
                for option in self._build_today_clarification_options(decision)
                if option.option_id.endswith(":risk")
            ]
            if len(options) == 1:
                return self._run_intent_clarification_option(
                    sender=sender,
                    session=session,
                    decision=decision,
                    option_id=options[0].option_id,
                )
            if len(options) > 1:
                return self._open_intent_clarification(
                    sender=sender,
                    session=session,
                    title="Risco Hoje",
                    prompt="Voce quer ver o risco de hoje em qual escopo?",
                    options=options,
                )

        if "giro" in tokens:
            requested_visit_day_label = _extract_requested_visit_day_label(normalized)
            if requested_visit_day_label:
                readiness_error = self._ensure_search_context_ready("giro", decision=decision)
                if readiness_error is not None:
                    self._reset_session(sender)
                    return readiness_error
                self._prepare_search_session(session, search_context="giro")
                return self._open_giro_visit_day_conversation(
                    sender=sender,
                    session=session,
                    decision=decision,
                    requested_day_label=requested_visit_day_label,
                )
            options = self._build_giro_clarification_options(decision)
            requested_giro_mode = _parse_giro_mode(normalized)
            if requested_giro_mode:
                matching_options = [
                    option
                    for option in options
                    if option.option_id.endswith(f":{requested_giro_mode}")
                ]
                if len(matching_options) == 1:
                    return self._run_intent_clarification_option(
                        sender=sender,
                        session=session,
                        decision=decision,
                        option_id=matching_options[0].option_id,
                    )
                if len(matching_options) > 1:
                    return self._open_intent_clarification(
                        sender=sender,
                        session=session,
                        title="Giro",
                        prompt="Voce quer ver esse giro em qual escopo?",
                        options=matching_options,
                    )
            if _looks_like_giro_short_request(normalized):
                if len(options) == 1:
                    return self._run_intent_clarification_option(
                        sender=sender,
                        session=session,
                        decision=decision,
                        option_id=options[0].option_id,
                    )
                if len(options) > 1:
                    return self._open_intent_clarification(
                        sender=sender,
                        session=session,
                        title="Giro",
                        prompt="Quando voce diz giro, qual caminho voce quer seguir?",
                        options=options,
                    )

        return None

    def _run_intent_clarification_option(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        option_id: str,
    ) -> OutgoingMessage:
        self._clear_clarification_state(session)

        if option_id == CLARIFY_LAST_CLIENT_RECORD:
            if not (session.last_client_filial and session.last_client_cod_pdv):
                self._reset_session(sender)
                return self._build_main_menu(decision)
            readiness_error = self._ensure_search_context_ready("cliente", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._remember_last_context(
                session,
                intent="search_cliente",
                search_context="cliente",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._run_registration_lookup(
                    decision=decision,
                    search_context="cliente",
                    filial=session.last_client_filial,
                    cod_pdv=session.last_client_cod_pdv,
                ),
                return_menu="main",
                repeat_action=REPEAT_SEARCH_REGISTRATION,
            )

        if option_id == CLARIFY_SCOPE_INADIMPLENCIA_LIST:
            return self._open_scope_inadimplencia_list(
                sender=sender,
                session=session,
                decision=decision,
            )

        if option_id == MENU_SEARCH:
            readiness_error = self._ensure_search_context_ready("cliente", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(
                sender=sender,
                session=session,
                search_context="cliente",
                decision=decision,
            )

        if option_id == MENU_INADIMPLENCIA:
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(
                sender=sender,
                session=session,
                search_context="inadimplencia",
                decision=decision,
            )

        if option_id == MENU_GIRO:
            readiness_error = self._ensure_search_context_ready("giro", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(
                sender=sender,
                session=session,
                search_context="giro",
                decision=decision,
            )

        if option_id == MENU_DOCUMENTACAO:
            readiness_error = self._ensure_search_context_ready("documentacao", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(
                sender=sender,
                session=session,
                search_context="documentacao",
                decision=decision,
            )

        if option_id == MENU_RECOLHA:
            return self._open_recolha_request(
                sender=sender,
                session=session,
                text="",
                normalized="",
                decision=decision,
            )

        if option_id == MENU_COMODATOS:
            readiness_error = self._ensure_search_context_ready("comodato", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(
                sender=sender,
                session=session,
                search_context="comodato",
                decision=decision,
            )

        if option_id == MENU_VISIT_DAY:
            return self._open_visit_day_conversation(
                sender=sender,
                session=session,
                decision=decision,
                requested_day_label=session.last_visit_day,
            )

        if option_id == MENU_SELLER_SUMMARY:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="cliente")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="seller_summary",
                search_context="cliente",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_seller_summary_response(decision),
                return_menu="main",
            )

        if option_id == MENU_SELLER_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="seller_risk_today",
                search_context="inadimplencia",
                visit_day=_current_visit_day_label(),
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_seller_risk_response(decision),
                return_menu="main",
            )

        if option_id == MENU_FINANCEIRO:
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_menu",
                search_context="inadimplencia",
            )
            self.sessions[sender] = session
            return self._build_finance_menu()

        if option_id == CLARIFY_SUMMARY_FINANCE:
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_summary",
                search_context="inadimplencia",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_summary_response(decision),
                return_menu="finance_menu",
            )

        if option_id == CLARIFY_SUMMARY_MANAGER:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="manager_summary",
                search_context="inadimplencia",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_gv_summary_response(
                    decision=decision,
                    title="Resumo Total da Gerencia",
                ),
                return_menu="manager_summary",
            )

        if option_id == CLARIFY_SUMMARY_DIRECTOR:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="director_summary",
                search_context="inadimplencia",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_director_total_summary_response(decision),
                return_menu="director_summary",
            )

        if option_id == CLARIFY_SUMMARY_SELLER:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="cliente")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="seller_summary",
                search_context="cliente",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_seller_summary_response(decision),
                return_menu="main",
            )

        if option_id == CLARIFY_TODAY_FINANCE_DUE:
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_due_today",
                search_context="inadimplencia",
            )
            return self._run_finance_due_bucket(
                sender=sender,
                session=session,
                decision=decision,
                due_bucket="today",
            )

        if option_id == CLARIFY_TODAY_FINANCE_RISK:
            readiness_error = self._ensure_search_context_ready("inadimplencia", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_risk_today",
                search_context="inadimplencia",
                visit_day=_current_visit_day_label(),
            )
            return self._open_finance_visit_risk_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=_current_visit_day_token(),
                visit_day_label=_current_visit_day_label(),
            )

        if option_id == CLARIFY_TODAY_MANAGER_VISITS:
            self._remember_last_context(
                session,
                intent="visit_day",
                search_context="cliente",
                visit_day=_current_visit_day_label(),
            )
            return self._open_visit_day_conversation(
                sender=sender,
                session=session,
                decision=decision,
                requested_day_label=_current_visit_day_label(),
            )

        if option_id == CLARIFY_TODAY_MANAGER_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="manager_risk_today",
                search_context="inadimplencia",
                visit_day=_current_visit_day_label(),
            )
            return self._open_manager_visit_risk_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=_current_visit_day_token(),
                visit_day_label=_current_visit_day_label(),
            )

        if option_id == CLARIFY_TODAY_DIRECTOR_VISITS:
            self._remember_last_context(
                session,
                intent="visit_day",
                search_context="cliente",
                visit_day=_current_visit_day_label(),
            )
            return self._open_visit_day_conversation(
                sender=sender,
                session=session,
                decision=decision,
                requested_day_label=_current_visit_day_label(),
            )

        if option_id == CLARIFY_TODAY_DIRECTOR_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="director_risk_today",
                search_context="inadimplencia",
                visit_day=_current_visit_day_label(),
            )
            return self._open_director_visit_risk_gv_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=_current_visit_day_token(),
                visit_day_label=_current_visit_day_label(),
            )

        if option_id == CLARIFY_TODAY_SELLER_VISITS:
            self._remember_last_context(
                session,
                intent="visit_day",
                search_context="cliente",
                visit_day=_current_visit_day_label(),
            )
            return self._open_visit_day_conversation(
                sender=sender,
                session=session,
                decision=decision,
                requested_day_label=_current_visit_day_label(),
            )

        if option_id == CLARIFY_TODAY_SELLER_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(
                session,
                intent="seller_risk_today",
                search_context="inadimplencia",
                visit_day=_current_visit_day_label(),
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_seller_risk_response(decision),
                return_menu="main",
            )

        if option_id == CLARIFY_GIRO_CLIENT:
            readiness_error = self._ensure_search_context_ready("giro", decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(
                sender=sender,
                session=session,
                search_context="giro",
                decision=decision,
            )

        if option_id == CLARIFY_GIRO_FINANCE_TOTAL:
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_giro_total",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_total_response(
                    decision,
                    title="Resumo de Giro | Base Total",
                ),
                return_menu="finance_giro_menu",
            )

        if option_id == CLARIFY_GIRO_FINANCE_BY_FILIAL:
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_giro_by_filial",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_by_filial_response(
                    decision,
                    title="Giro por Filial | Base Total",
                ),
                return_menu="finance_giro_menu",
            )

        if option_id == CLARIFY_GIRO_FINANCE_BY_GV:
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_giro_by_gv",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_by_gv_response(
                    decision,
                    title="Giro por GV | Base Total",
                ),
                return_menu="finance_giro_menu",
            )

        if option_id == CLARIFY_GIRO_MANAGER_TOTAL:
            self._remember_last_context(
                session,
                intent="manager_giro_total",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_total_response(
                    decision,
                    title="Resumo de Giro | Gerencia",
                ),
                return_menu="manager_giro_menu",
            )

        if option_id == CLARIFY_GIRO_MANAGER_BY_FILIAL:
            self._remember_last_context(
                session,
                intent="manager_giro_by_filial",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_by_filial_response(
                    decision,
                    title="Giro por Filial | Gerencia",
                ),
                return_menu="manager_giro_menu",
            )

        if option_id == CLARIFY_GIRO_DIRECTOR_BY_GV:
            self._remember_last_context(
                session,
                intent="director_giro_by_gv",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_by_gv_response(
                    decision,
                    title="Giro por GV | Diretoria",
                ),
                return_menu="director_giro_menu",
            )

        if option_id == CLARIFY_GIRO_DIRECTOR_BY_FILIAL:
            self._remember_last_context(
                session,
                intent="director_giro_by_filial",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_by_filial_response(
                    decision,
                    title="Giro por Filial | Diretoria",
                ),
                return_menu="director_giro_menu",
            )

        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _run_finance_due_bucket(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        due_bucket: str,
    ) -> OutgoingMessage:
        bucket_meta = {
            "in_two_days": {
                "header": "Esses sao os clientes que vencem em 2 dias na base total.",
                "empty": (
                    "Nao encontrei clientes com vencimento em 2 dias na base total.\n"
                    "Escolha outra faixa ou envie MENU."
                ),
            },
            "tomorrow": {
                "header": "Esses sao os clientes que vencem amanha na base total.",
                "empty": (
                    "Nao encontrei clientes com vencimento para amanha na base total.\n"
                    "Escolha outra faixa ou envie MENU."
                ),
            },
            "today": {
                "header": "Esses sao os clientes que vencem hoje na base total.",
                "empty": (
                    "Nao encontrei clientes com vencimento hoje na base total.\n"
                    "Escolha outra faixa ou envie MENU."
                ),
            },
            "overdue": {
                "header": "Esses sao os clientes que ja estao vencidos na base total.",
                "empty": (
                    "Nao encontrei clientes vencidos na base total.\n"
                    "Escolha outra faixa ou envie MENU."
                ),
            },
        }[due_bucket]
        return self._open_inadimplencia_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
            order_by="total_pendente",
            due_bucket=due_bucket,
            header_text=bucket_meta["header"],
            empty_text=bucket_meta["empty"],
        )

    def _run_scoped_inadimplencia_due_bucket(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        due_bucket: str,
    ) -> OutgoingMessage:
        access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
        if access_error is not None:
            self.sessions[sender] = session
            return access_error

        scope_label = self._inadimplencia_scope_label(decision)
        bucket_meta = {
            "in_two_days": {
                "header": f"Esses sao os clientes que vencem em 2 dias da {scope_label}.",
                "empty": (
                    f"Nao encontrei clientes com vencimento em 2 dias na {scope_label}.\n"
                    "Escolha outra faixa ou envie MENU."
                ),
            },
            "tomorrow": {
                "header": f"Esses sao os clientes que vencem amanha da {scope_label}.",
                "empty": (
                    f"Nao encontrei clientes com vencimento para amanha na {scope_label}.\n"
                    "Escolha outra faixa ou envie MENU."
                ),
            },
        }[due_bucket]
        return self._open_inadimplencia_summary_selection(
            sender=sender,
            session=session,
            decision=decision,
            order_by="total_pendente",
            due_bucket=due_bucket,
            header_text=bucket_meta["header"],
            empty_text=bucket_meta["empty"],
            list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
        )

    def _open_finance_summary_menu(
        self,
        *,
        sender: str,
        session: LookupSession,
    ) -> OutgoingMessage:
        session.step = "finance_select_summary_mode"
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_summary_menu()

    def _run_finance_summary_mode(
        self,
        *,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        summary_mode: str,
    ) -> OutgoingMessage:
        if summary_mode == "total":
            self._remember_last_context(
                session,
                intent="finance_summary_total",
                search_context="inadimplencia",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_summary_response(decision),
                return_menu="finance_summary_menu",
            )

        if summary_mode == "by_filial":
            self._remember_last_context(
                session,
                intent="finance_summary_by_filial",
                search_context="inadimplencia",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_summary_by_filial_response(decision),
                return_menu="finance_summary_menu",
            )

        if summary_mode == "by_gv":
            self._remember_last_context(
                session,
                intent="finance_summary_by_gv",
                search_context="inadimplencia",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_summary_by_gv_response(decision),
                return_menu="finance_summary_menu",
            )

        if summary_mode == "by_seller":
            self._remember_last_context(
                session,
                intent="finance_summary_by_seller",
                search_context="inadimplencia",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_summary_by_seller_response(decision),
                return_menu="finance_summary_menu",
            )

        if summary_mode == "documentacao_by_filial":
            self._remember_last_context(
                session,
                intent="finance_summary_documentacao_by_filial",
                search_context="documentacao",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_documentacao_by_filial_response(decision),
                return_menu="finance_summary_menu",
            )

        self.sessions[sender] = session
        return self._build_finance_summary_menu(invalid_selection=True)

    def _maybe_handle_search_mode_conversation(
        self,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        request = _parse_hybrid_search_request(
            text=text,
            normalized_text=normalized,
            search_context=session.search_context,
            allow_contextless_query=True,
        )
        if request is None:
            return None
        if request.open_base_list:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._open_inadimplencia_summary_selection(
                sender=sender,
                session=session,
                decision=decision,
                order_by="total_pendente",
                header_text=f"Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.",
                empty_text=(
                    "No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\n"
                    "Se quiser tentar outra consulta, envie MENU."
                ),
                page=1,
                page_size=INADIMPLENCIA_PAGE_SIZE,
                list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
            )
        if request.open_giro_zero_base_list:
            access_error = self._ensure_scoped_lookup_access(decision, search_context="giro")
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            self._remember_last_context(
                session,
                intent="giro_zero_base",
                search_context="giro",
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_zero_base_response(decision),
                return_menu="search_menu",
            )
        if request.search_mode in {"registration", "fantasia"} or request.query_text:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
        elif request.search_mode == "document" and session.search_context in {
            "cliente",
            "giro",
            "inadimplencia",
            "comodato",
            "documentacao",
            "prazo_limite",
        }:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
        if request.filial and request.cod_pdv:
            return self._run_repeatable_registration_lookup(
                sender=sender,
                session=session,
                decision=decision,
                search_context=session.search_context,
                filial=request.filial,
                cod_pdv=request.cod_pdv,
            )
        if request.document:
            return self._run_document_lookup(
                sender=sender,
                session=session,
                decision=decision,
                document=request.document,
            )
        if request.visit_day_label:
            if session.search_context == "giro":
                return self._open_giro_visit_day_conversation(
                    sender=sender,
                    session=session,
                    decision=decision,
                    requested_day_label=request.visit_day_label,
                )
            if session.search_context == "inadimplencia":
                return self._open_inadimplencia_visit_day_conversation(
                    sender=sender,
                    session=session,
                    decision=decision,
                    requested_day_label=request.visit_day_label,
                )
            if session.search_context == "documentacao":
                return self._open_documentacao_visit_day_conversation(
                    sender=sender,
                    session=session,
                    decision=decision,
                    requested_day_label=request.visit_day_label,
                )
        if request.query_text:
            return self._run_name_search(
                sender=sender,
                session=session,
                decision=decision,
                query_text=request.query_text,
            )
        if request.search_mode:
            return self._activate_search_mode(sender=sender, session=session, search_mode=request.search_mode)
        return None

    def _maybe_handle_idle_conversation(
        self,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        if session.step != "idle":
            return None
        if _looks_like_plain_numeric_choice(normalized):
            return None
        if self._is_admin(decision):
            admin_check_match = re.match(
                r"^(?:validar acesso|checar acesso|conferir acesso)\s+(.+)$",
                normalized,
            )
            if admin_check_match:
                phone_number = _normalize_phone_number(admin_check_match.group(1))
                if not phone_number:
                    return OutgoingMessage(text="Me envie o telefone com DDI para validar o acesso.")
                try:
                    user = self.access_control.get_user(phone_number)
                except RuntimeError:
                    self._reset_session(sender)
                    return OutgoingMessage(
                        text=(
                            "Nao consegui validar esse acesso agora.\n"
                            "Tente novamente em instantes."
                        )
                    )
                self._reset_session(sender)
                return self._build_admin_access_check_response(phone_number, user)

            admin_action = _parse_admin_action(normalized)
            if admin_action and not _looks_like_plain_numeric_choice(normalized):
                if not self.access_control.enabled:
                    return OutgoingMessage(
                        text="No momento, o cadastro de usuarios pelo WhatsApp nao esta disponivel."
                    )
                admin_session = LookupSession(step="admin_select_action")
                admin_session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = admin_session
                return self._handle_admin_session(
                    sender=sender,
                    session=admin_session,
                    text=text,
                    normalized=normalized,
                    decision=decision,
                )

        low_confidence_response = self._maybe_handle_idle_low_confidence_request(
            sender=sender,
            session=session,
            normalized=normalized,
            decision=decision,
        )
        if low_confidence_response is not None:
            return low_confidence_response

        if self._can_use_finance_menu(decision) and _looks_like_finance_request(normalized):
            self._prepare_finance_session(session)
            self._remember_last_context(
                session,
                intent="finance_menu",
                search_context="inadimplencia",
            )
            self.sessions[sender] = session
            request = _parse_hybrid_finance_request(normalized)
            if not request.action and not request.clarify_today:
                return self._build_finance_menu()
            return self.finance_flow.handle_session(
                sender=sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if self._can_use_visit_menu(decision) and _looks_like_visit_day_request(normalized):
            requested_day_label = _extract_requested_visit_day_label(normalized)
            return self._open_visit_day_conversation(
                sender=sender,
                session=session,
                decision=decision,
                requested_day_label=requested_day_label,
            )

        search_context = _detect_explicit_search_context(normalized)
        if not search_context:
            return None
        readiness_error = self._ensure_search_context_ready(search_context, decision=decision)
        if readiness_error is not None:
            self._reset_session(sender)
            return readiness_error
        self._prepare_search_session(session, search_context=search_context)
        self.sessions[sender] = session
        request = _parse_hybrid_search_request(
            text=text,
            normalized_text=normalized,
            search_context=search_context,
            allow_contextless_query=False,
        )
        if request is None:
            return self._build_search_menu(search_context=search_context, decision=decision)
        return self._maybe_handle_search_mode_conversation(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _open_recolha_request(
        self,
        *,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        if not self._can_request_recolha(decision):
            self._reset_session(sender)
            return OutgoingMessage(
                text=(
                    "A solicitacao de recolha esta liberada para vendedor e financeiro.\n"
                    "Se voce for do financeiro, envie RECOLHAS para ver as solicitacoes."
                )
            )

        text = self._contextualize_recolha_request_text(session=session, text=text)
        self._clear_recolha_state(session)
        inline_request = _parse_recolha_inline_request(text)
        if inline_request is not None:
            client_ref, comodato, obs = inline_request
            client_error = self._apply_recolha_client_reference(session, decision=decision, client_ref=client_ref)
            if client_error is not None:
                session.step = "recolha_awaiting_client"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return client_error
            if comodato:
                session.recolha_comodato = _resolve_recolha_comodato_selection(session=session, text=comodato)
            if obs:
                session.recolha_obs = obs
            if session.recolha_comodato:
                session.step = "recolha_confirm"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_recolha_confirmation(session=session)
            session.step = "recolha_awaiting_comodato"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_comodato_prompt(session=session)

        session.step = "recolha_awaiting_client"
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_recolha_client_prompt()

    def _contextualize_recolha_request_text(self, *, session: LookupSession, text: str) -> str:
        if not (
            self._has_recent_last_context(session)
            and session.last_search_context == "comodato"
            and session.last_client_filial
            and session.last_client_cod_pdv
        ):
            return text

        raw = str(text or "").strip()
        if not raw:
            return text
        normalized = _normalize_choice(raw)
        if not _looks_like_recolha_request(normalized):
            return text

        payload = _recolha_request_payload(raw)
        if not payload:
            return f"recolha {session.last_client_filial} {session.last_client_cod_pdv}"

        normalized_payload = _normalize_choice(payload)
        if (
            normalized_payload in {"todos", "tudo", "total", "recolha total", "todos os comodatos", "recolher todos"}
            or normalized_payload.startswith(("todos ", "tudo ", "total ", "recolha total "))
            or _looks_like_recolha_numeric_selection(normalized_payload)
        ):
            return f"recolha {session.last_client_filial} {session.last_client_cod_pdv} | {payload}"
        return text

    def _handle_recolha_session(
        self,
        *,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        if session.step in {"recolha_delete_confirm", "recolha_clear_confirm"}:
            if normalized in {"cancelar", "sair", "voltar"}:
                self._reset_session(sender)
                return OutgoingMessage(text="Operacao cancelada.\nSe quiser voltar ao inicio, envie MENU.")
            if session.step == "recolha_delete_confirm":
                if not self._can_view_recolhas(decision):
                    self._reset_session(sender)
                    return OutgoingMessage(text="Voce nao tem acesso ao gerenciamento de recolhas.")
                if normalized in {"confirmar remover", "confirmar apagar", "confirmar exclusao", "confirmar excluir"}:
                    deleted = self._delete_recolha_for_decision(
                        identifier=session.recolha_pending_identifier,
                        sender=sender,
                        decision=decision,
                    )
                    self._reset_session(sender)
                    return self._build_recolha_deleted_response(
                        deleted,
                        identifier=session.recolha_pending_identifier,
                    )
                self.sessions[sender] = session
                return self._build_recolha_delete_confirmation(
                    self._find_recolha_for_decision(
                        identifier=session.recolha_pending_identifier,
                        sender=sender,
                        decision=decision,
                    ),
                    identifier=session.recolha_pending_identifier,
                    invalid_selection=True,
                )
            if not self._can_clear_recolhas(decision):
                self._reset_session(sender)
                return OutgoingMessage(text="Esse fluxo de limpeza geral e exclusivo do admin, gerencial ou financeiro sem restricao de filial.")
            if normalized == "confirmar limpar":
                deleted_count = self.recolha_request_service.clear_requests()
                self._reset_session(sender)
                return OutgoingMessage(
                    text=(
                        "Limpeza de Recolhas\n\n"
                        f"*Resultado:*\n- {deleted_count} solicitacao(oes) removida(s).\n\n"
                        "O CSV de recolhas ficou apenas com o cabecalho."
                    )
                )
            self.sessions[sender] = session
            return self._build_recolha_clear_confirmation(invalid_selection=True)

        if not self._can_request_recolha(decision):
            self._reset_session(sender)
            return OutgoingMessage(text="Esse fluxo de recolha esta liberado para vendedor e financeiro.")
        if normalized in {"editar", "recomecar", "reiniciar"}:
            self._clear_recolha_state(session)
            session.step = "recolha_awaiting_client"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_client_prompt()

        if session.step == "recolha_awaiting_client":
            selected_record = _select_recolha_client_option(text=text, options=session.recolha_client_options)
            if selected_record is not None:
                self._apply_recolha_client_record(session, record=selected_record, decision=decision)
                session.step = "recolha_awaiting_comodato"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_recolha_comodato_prompt(session=session)
            client_error = self._apply_recolha_client_reference(session, decision=decision, client_ref=text)
            if client_error is not None:
                self.sessions[sender] = session
                return client_error
            session.step = "recolha_awaiting_comodato"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_comodato_prompt(session=session)

        if session.step == "recolha_awaiting_comodato":
            comodato = _resolve_recolha_comodato_selection(session=session, text=text)
            if not comodato:
                self.sessions[sender] = session
                return self._build_recolha_comodato_prompt(session=session, invalid_selection=True)
            session.recolha_comodato = comodato
            session.step = "recolha_awaiting_obs"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_obs_prompt()

        if session.step == "recolha_awaiting_obs":
            session.recolha_obs = "" if normalized in {"sem obs", "sem observacao", "nao", "n"} else _clean_recolha_text(text)
            session.step = "recolha_confirm"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_confirmation(session=session)

        if session.step == "recolha_confirm":
            if normalized in {"confirmar", "confirma", "confirmo", "sim", "s", "ok"}:
                records = self.recolha_request_service.create_requests(
                    solicitante=decision.normalized_number or sender,
                    solicitante_nome=self._recolha_requester_name(sender=sender, decision=decision),
                    revenda=session.recolha_revenda,
                    data=datetime.now(LOCAL_TIMEZONE).strftime("%d/%m/%Y"),
                    setor=session.recolha_setor,
                    cidade=session.recolha_cidade,
                    rn=session.recolha_rn,
                    nb=session.recolha_nb,
                    comodato=session.recolha_comodato,
                    obs=session.recolha_obs,
                    created_at=datetime.now(LOCAL_TIMEZONE),
                )
                self._reset_session(sender)
                return self._build_recolha_created_response(records=records, cliente=session.recolha_cliente)
            self.sessions[sender] = session
            return self._build_recolha_confirmation(session=session, invalid_selection=True)

        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _clear_recolha_state(self, session: LookupSession) -> None:
        session.recolha_filial = ""
        session.recolha_nb = ""
        session.recolha_cliente = ""
        session.recolha_client_options = ()
        session.recolha_revenda = ""
        session.recolha_setor = ""
        session.recolha_cidade = ""
        session.recolha_rn = ""
        session.recolha_comodato = ""
        session.recolha_comodato_options = ()
        session.recolha_obs = ""
        session.recolha_pending_action = ""
        session.recolha_pending_identifier = ""

    def _apply_recolha_client_reference(
        self,
        session: LookupSession,
        *,
        decision: AccessDecision,
        client_ref: str,
    ) -> OutgoingMessage | None:
        filial, cod_pdv = _resolve_recolha_registration_input(client_ref, decision=decision)
        if not filial or not cod_pdv:
            return self._apply_recolha_client_name_reference(session, decision=decision, query_text=client_ref)
        try:
            records = self.query_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except (RuntimeError, ValueError):
            records = []
        records = self._filter_recolha_client_records_by_scope(records, decision=decision)
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei o cliente {filial} {cod_pdv} dentro da sua base.\n"
                    "Confira a filial/NB e envie novamente."
                )
            )
        self._apply_recolha_client_record(session, record=records[0], decision=decision)
        return None

    def _apply_recolha_client_name_reference(
        self,
        session: LookupSession,
        *,
        decision: AccessDecision,
        query_text: str,
    ) -> OutgoingMessage | None:
        cleaned_query = _clean_recolha_text(query_text)
        if not cleaned_query or _normalize_choice(cleaned_query) in {"recolha", "recolhas"}:
            return OutgoingMessage(
                text=(
                    "Nao consegui identificar o cliente para a recolha.\n"
                    "Envie o NB, o nome do cliente, ou filial e NB. Exemplo: 3 9845."
                )
            )
        try:
            records = self.query_service.search_by_fantasia(
                query_text=cleaned_query,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
        except (RuntimeError, ValueError, AttributeError):
            records = []
        records = self._filter_recolha_client_records_by_scope(records, decision=decision)
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei cliente com '{cleaned_query}' dentro da sua base.\n"
                    "Tente pelo NB ou envie MENU."
                )
            )
        if len(records) == 1:
            self._apply_recolha_client_record(session, record=records[0], decision=decision)
            return None
        session.recolha_client_options = tuple(records[:10])
        return self._build_recolha_client_selection_prompt(cleaned_query, records=list(session.recolha_client_options))

    def _apply_recolha_client_record(
        self,
        session: LookupSession,
        *,
        record: DClienteRecord,
        decision: AccessDecision,
    ) -> None:
        session.recolha_filial = record.filial
        session.recolha_nb = record.cod_pdv
        session.recolha_cliente = record.nome_fantasia or record.razao_social or f"NB {record.cod_pdv}"
        session.recolha_client_options = ()
        session.recolha_revenda = FILIAL_LABELS.get(_normalize_filial(record.filial), record.filial)
        session.recolha_setor = record.vendedor or _scope_last_code((decision.sectors or ("",))[0] if decision.sectors else "")
        session.recolha_cidade = record.cidade
        session.recolha_rn = session.recolha_setor
        session.recolha_comodato_options = tuple(
            self._fetch_recolha_comodato_options(
                filial=record.filial,
                cod_pdv=record.cod_pdv,
                decision=decision,
            )
        )

    def _filter_recolha_client_records_by_scope(
        self,
        records: list[DClienteRecord],
        *,
        decision: AccessDecision,
    ) -> list[DClienteRecord]:
        if self._has_unrestricted_lookup_access(decision):
            return list(records)
        allowed_sector_pairs = {
            normalize_stored_scope_value(value)
            for value in decision.sectors
            if normalize_stored_scope_value(value)
        }
        if not allowed_sector_pairs:
            return list(records)
        filtered: list[DClienteRecord] = []
        for record in records:
            record_pair = normalize_stored_scope_value(f"{record.filial}_{record.vendedor}")
            if record_pair in allowed_sector_pairs:
                filtered.append(record)
        return filtered

    def _fetch_recolha_comodato_options(
        self,
        *,
        filial: str,
        cod_pdv: str,
        decision: AccessDecision,
    ) -> list[ComodatoRecord]:
        try:
            return self.comodatos_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=1000,
            )
        except (RuntimeError, ValueError):
            return []

    def _build_recolha_client_prompt(self) -> OutgoingMessage:
        return OutgoingMessage(
            text=(
                "Solicitacao de Recolha\n\n"
                "*Cliente:*\n"
                "- Envie o NB ou parte do nome do cliente.\n"
                "- Se precisar, envie filial e NB: 3 9845.\n\n"
                "Atalho em uma mensagem:\n"
                "recolha 9845 todos"
            )
        )

    def _build_recolha_client_selection_prompt(
        self,
        query_text: str,
        *,
        records: list[DClienteRecord],
    ) -> OutgoingMessage:
        lines = [
            "Solicitacao de Recolha",
            "",
            f"Encontrei {len(records)} cliente(s) com '{query_text}'.",
            "Escolha o cliente pelo numero:",
        ]
        for index, record in enumerate(records, start=1):
            lines.append(
                f"{index}. {record.nome_fantasia or record.razao_social or '-'} | "
                f"Revenda {record.filial or '-'} | NB {record.cod_pdv or '-'} | Setor {record.vendedor or '-'}"
            )
        return OutgoingMessage(text="\n".join(lines))

    def _build_recolha_comodato_prompt(
        self,
        *,
        session: LookupSession,
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        first_line = "O que deve ser recolhido?"
        if invalid_selection:
            first_line = "Nao entendi o que deve ser recolhido."
        return OutgoingMessage(
            text=(
                "Solicitacao de Recolha\n\n"
                f"*Cliente:*\n"
                f"- Nome: {session.recolha_cliente or '-'}\n"
                f"- Revenda: {session.recolha_filial or '-'} | NB: {session.recolha_nb or '-'} | Setor: {session.recolha_setor or '-'}\n\n"
                + self._build_recolha_comodato_options_text(first_line, session=session)
            )
        )

    def _build_recolha_comodato_options_text(self, first_line: str, *, session: LookupSession) -> str:
        records = list(session.recolha_comodato_options or ())
        if not records:
            return (
                f"*Comodato:*\n"
                f"- {first_line}\n"
                "- Nao encontrei comodatos pendentes listados para esse cliente.\n"
                "- Digite manualmente, por exemplo: RECOLHA TOTAL, 30 cx de litrinho, freezer, mesas, oasis."
            )

        lines = ["*Comodatos pendentes:*", f"- {first_line}"]
        for index, record in enumerate(records, start=1):
            lines.append(f"{index}. {_format_recolha_comodato_option(record)}")
        lines.extend(
            [
                "",
                "*Como escolher:*",
                "- Envie TODOS para recolher todos os comodatos listados.",
                "- Envie 1 para selecionar um comodato.",
                "- Envie 1,3 para selecionar varios.",
                "- Ou digite manualmente o que deve recolher.",
            ]
        )
        return "\n".join(lines)

    def _build_recolha_obs_prompt(self) -> OutgoingMessage:
        return OutgoingMessage(
            text=(
                "Solicitacao de Recolha\n\n"
                "*Observacao:*\n"
                "- Envie alguma orientacao para o financeiro/faturista.\n"
                "- Se nao tiver, envie SEM OBS."
            )
        )

    def _build_recolha_confirmation(
        self,
        *,
        session: LookupSession,
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        lines = ["Solicitacao de Recolha", ""]
        if invalid_selection:
            lines.extend(["Envie CONFIRMAR para registrar, EDITAR para recomeçar ou CANCELAR para sair.", ""])
        lines.extend(
            [
                f"Cliente: {session.recolha_cliente or '-'}",
                f"Revenda: {session.recolha_filial or '-'} | NB: {session.recolha_nb or '-'} | Setor: {session.recolha_setor or '-'}",
                "",
                "*Pedido:*",
                f"- Comodato: {session.recolha_comodato or '-'}",
                f"- OBS.: {session.recolha_obs or '-'}",
                "",
                "Envie CONFIRMAR para registrar.",
                "Envie EDITAR para recomeçar ou CANCELAR para sair.",
            ]
        )
        return OutgoingMessage(text="\n".join(lines))

    def _build_recolha_created_response(
        self,
        *,
        records: list[RecolhaRequestRecord],
        cliente: str,
    ) -> OutgoingMessage:
        record = records[0] if records else None
        if record is None:
            return OutgoingMessage(
                text=(
                    "Solicitacao de Recolha\n\n"
                    "Nao consegui registrar a solicitacao agora.\n"
                    "Tente novamente em instantes."
                )
            )
        item_lines = []
        for index, item in enumerate(records, start=1):
            item_lines.append(f"{index}. ID {item.id} | {item.comodato or '-'}")
        return OutgoingMessage(
            text=(
                "Solicitacao de Recolha registrada\n\n"
                f"Cliente: {cliente or '-'}\n"
                f"Revenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}\n\n"
                "*Pedido:*\n"
                f"- Comodato(s): {len(records)}\n"
                f"- OBS.: {record.obs or '-'}\n"
                f"- Status inicial: {record.status_caixa_noturno}\n\n"
                "*Itens gerados:*\n"
                + "\n".join(item_lines)
                + "\n\n"
                "O financeiro ja consegue ver essa solicitacao em RECOLHAS.\n"
                "O CSV ja esta atualizado para copia/importacao."
            )
        )

    def _open_recolha_delete_confirmation(
        self,
        *,
        sender: str,
        session: LookupSession,
        identifier: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        record = self._find_recolha_for_decision(
            identifier=identifier,
            sender=sender,
            decision=decision,
        )
        session.step = "recolha_delete_confirm"
        session.recolha_pending_action = "delete"
        session.recolha_pending_identifier = identifier
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_recolha_delete_confirmation(record, identifier=identifier)

    def _open_recolha_clear_confirmation(
        self,
        *,
        sender: str,
        session: LookupSession,
    ) -> OutgoingMessage:
        session.step = "recolha_clear_confirm"
        session.recolha_pending_action = "clear"
        session.recolha_pending_identifier = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_recolha_clear_confirmation()

    def _build_recolha_delete_confirmation(
        self,
        record: RecolhaRequestRecord | None,
        *,
        identifier: str,
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        if record is None:
            return OutgoingMessage(
                text=(
                    "Remover Recolha\n\n"
                    f"Nao encontrei solicitacao para '{identifier}'.\n"
                    "Use RECOLHAS para conferir os IDs/NBs."
                )
            )
        lines = ["Remover Recolha", ""]
        if invalid_selection:
            lines.extend(["Para remover, envie exatamente CONFIRMAR REMOVER.", ""])
        lines.extend(
            [
                "*Solicitacao encontrada:*",
                f"- ID: {record.id or '-'}",
                f"- Revenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}",
                f"- Comodato: {record.comodato or '-'}",
                f"- Status: {record.status_caixa_noturno or '-'}",
                "",
                "Envie CONFIRMAR REMOVER para apagar essa solicitacao.",
                "Envie CANCELAR para sair.",
            ]
        )
        return OutgoingMessage(text="\n".join(lines))

    def _build_recolha_clear_confirmation(self, *, invalid_selection: bool = False) -> OutgoingMessage:
        lines = ["Limpar Recolhas", ""]
        if invalid_selection:
            lines.extend(["Para limpar tudo, envie exatamente CONFIRMAR LIMPAR.", ""])
        lines.extend(
            [
                "*Atencao:*",
                "- Isso remove todas as solicitacoes do CSV de recolhas.",
                "- O arquivo ficara apenas com o cabecalho.",
                "",
                "Envie CONFIRMAR LIMPAR para continuar.",
                "Envie CANCELAR para sair.",
            ]
        )
        return OutgoingMessage(text="\n".join(lines))

    def _build_recolha_deleted_response(
        self,
        record: RecolhaRequestRecord | None,
        *,
        identifier: str,
    ) -> OutgoingMessage:
        if record is None:
            return OutgoingMessage(
                text=(
                    "Remover Recolha\n\n"
                    f"Nao encontrei solicitacao para '{identifier}'.\n"
                    "Nada foi removido."
                )
            )
        return OutgoingMessage(
            text=(
                "Remover Recolha\n\n"
                "*Removida:*\n"
                f"- ID: {record.id or '-'}\n"
                f"- Revenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}\n"
                f"- Comodato: {record.comodato or '-'}\n\n"
                "CSV atualizado."
            )
        )

    def _build_recolha_update_response(
        self,
        record: RecolhaRequestRecord | None,
        *,
        identifier: str,
    ) -> OutgoingMessage:
        if record is None:
            return OutgoingMessage(
                text=(
                    "Atualizacao de Recolha\n\n"
                    f"Nao encontrei solicitacao de recolha para '{identifier}'.\n"
                    "Use RECOLHAS para conferir as solicitacoes abertas."
                )
            )
        return OutgoingMessage(
            text=(
                "Atualizacao de Recolha\n\n"
                "*Solicitacao:*\n"
                f"- Revenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}\n"
                f"- Comodato: {record.comodato or '-'}\n\n"
                "*Faturista/Caixa:*\n"
                f"- Lancado: {record.lancado_faturista or '-'}\n"
                f"- Motorista: {record.motorista_faturista or '-'}\n"
                f"- Placa: {record.placa_faturista or '-'}\n"
                f"- Mapa: {record.mapa_faturista or '-'}\n"
                f"- Status: {record.status_caixa_noturno or '-'}\n"
                f"- Motivo: {record.motivo_caixa_noturno or '-'}\n\n"
                "CSV atualizado."
            )
        )

    def _recolha_requester_keys(self, *, sender: str, decision: AccessDecision) -> set[str]:
        keys: set[str] = set()
        for value in (decision.normalized_number, sender):
            normalized = _normalize_phone_number(value)
            if normalized:
                keys.add(normalized)
            digits = "".join(char for char in str(value or "") if char.isdigit())
            if digits:
                keys.add(digits)
        return keys

    def _recolha_requester_name(self, *, sender: str, decision: AccessDecision) -> str:
        for value in (decision.normalized_number, sender):
            try:
                user = self.access_control.get_user(value)
            except Exception:
                user = None
            name = str((user or {}).get("name") or "").strip()
            if name:
                return name
        return ""

    def _recolha_identity_keys(self, value: str) -> set[str]:
        keys: set[str] = set()
        normalized = _normalize_phone_number(value)
        if normalized:
            keys.add(normalized)
        digits = "".join(char for char in str(value or "") if char.isdigit())
        if digits:
            keys.add(digits)
        return keys

    def _recolha_record_visible_for_decision(
        self,
        record: RecolhaRequestRecord,
        *,
        sender: str,
        decision: AccessDecision,
    ) -> bool:
        if self._is_admin(decision):
            return True
        if self._is_financeiro(decision):
            allowed_filiais = _recolha_allowed_filiais_from_decision(decision)
            if not allowed_filiais:
                return True
            record_filial = _recolha_record_filial_code(record)
            return bool(record_filial and record_filial in allowed_filiais)
        if self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision):
            return True
        requester_keys = self._recolha_requester_keys(sender=sender, decision=decision)
        solicitante_keys = self._recolha_identity_keys(record.solicitante)
        return bool(requester_keys & solicitante_keys)

    def _filter_recolha_records_for_decision(
        self,
        records: list[RecolhaRequestRecord],
        *,
        sender: str,
        decision: AccessDecision,
    ) -> list[RecolhaRequestRecord]:
        return [
            record
            for record in records
            if self._recolha_record_visible_for_decision(record, sender=sender, decision=decision)
        ]

    def _find_recolha_for_decision(
        self,
        *,
        identifier: str,
        sender: str,
        decision: AccessDecision,
    ) -> RecolhaRequestRecord | None:
        normalized_identifier = str(identifier or "").strip().lower()
        if not normalized_identifier:
            return None
        try:
            records = self.recolha_request_service.list_requests(limit=500)
        except OSError:
            return None
        for record in records:
            if not _recolha_record_matches_identifier(record, normalized_identifier):
                continue
            if self._recolha_record_visible_for_decision(record, sender=sender, decision=decision):
                return record
        return None

    def _update_recolha_for_decision(
        self,
        *,
        identifier: str,
        updates: dict[str, str],
        sender: str,
        decision: AccessDecision,
    ) -> RecolhaRequestRecord | None:
        record = self._find_recolha_for_decision(identifier=identifier, sender=sender, decision=decision)
        if record is None:
            return None
        return self.recolha_request_service.update_latest(identifier=record.id or identifier, updates=updates)

    def _delete_recolha_for_decision(
        self,
        *,
        identifier: str,
        sender: str,
        decision: AccessDecision,
    ) -> RecolhaRequestRecord | None:
        record = self._find_recolha_for_decision(identifier=identifier, sender=sender, decision=decision)
        if record is None:
            return None
        return self.recolha_request_service.delete_latest(identifier=record.id or identifier)

    def _build_recolhas_finance_response(
        self,
        request_text: str = "",
        *,
        sender: str = "",
        decision: AccessDecision,
    ) -> OutgoingMessage:
        try:
            all_records = self.recolha_request_service.list_all_requests()
        except OSError:
            return OutgoingMessage(
                text=(
                    "Solicitacoes de Recolha\n\n"
                    "No momento, nao consegui acessar o arquivo de recolhas.\n"
                    "Tente novamente em instantes."
                )
            )

        visible_records = self._filter_recolha_records_for_decision(
            all_records,
            sender=sender,
            decision=decision,
        )
        total = len(visible_records)
        if not visible_records:
            return OutgoingMessage(
                text=(
                    "Solicitacoes de Recolha\n\n"
                    "*Resumo:*\n"
                    "- Total visivel: 0\n\n"
                    "Nenhuma solicitacao de recolha encontrada para o seu acesso."
                )
            )
        base_filters = _parse_recolha_request_filters(request_text, default_open=False)
        if base_filters.invalid_reason:
            return OutgoingMessage(
                text=(
                    "Solicitacoes de Recolha\n\n"
                    f"{base_filters.invalid_reason}\n\n"
                    "*Exemplos validos:*\n"
                    "- RECOLHAS HOJE\n"
                    "- RECOLHAS ONTEM\n"
                    "- RECOLHAS SEMANA\n"
                    "- RECOLHAS 19/05/2026\n"
                    "- RECOLHAS 19/05/2026 A 22/05/2026"
                )
            )
        default_open = not base_filters.explicit_period and not base_filters.explicit_status
        request_filters = _parse_recolha_request_filters(request_text, default_open=default_open)
        filtered_records = _filter_recolha_records_for_request(
            visible_records,
            request_text,
            default_open=default_open,
        )
        csv_bytes = self.recolha_request_service.export_csv_bytes(filtered_records)
        if _recolha_request_is_summary(request_text):
            return self._build_recolhas_summary_response(
                records=filtered_records,
                total=total,
                csv_bytes=csv_bytes,
                request_filters=request_filters,
            )
        records = filtered_records[:30]
        if not records:
            return OutgoingMessage(
                text=(
                    "Solicitacoes de Recolha\n\n"
                    "Nao encontrei solicitacoes para esse filtro.\n"
                    f"- Periodo: {request_filters.period_label}\n"
                    f"- Status: {request_filters.status_label}\n\n"
                    "Use RECOLHAS para pendencias abertas, RECOLHAS HOJE para o dia ou RECOLHAS HISTORICO para tudo."
                )
            )

        lines = [
            "Solicitacoes de Recolha",
            "",
            "*Resumo:*",
            f"- Total visivel: {total}",
            f"- No filtro: {len(filtered_records)}",
            f"- Periodo: {request_filters.period_label}",
            f"- Status: {request_filters.status_label}",
            f"- Mostrando ultimas: {len(records)}",
            "",
            "*Ultimas solicitacoes:*",
        ]
        for index, record in enumerate(records, start=1):
            lines.extend(
                [
                    "",
                    f"{index}) Revenda {record.revenda or '-'} | Setor {record.setor or '-'} | NB {record.nb or '-'}",
                    f"- Data: {record.data or '-'}",
                    f"- RN: {record.rn or '-'}",
                    f"- Cidade: {record.cidade or '-'}",
                    f"- Comodato: {record.comodato or '-'}",
                    f"- Lancado: {record.lancado_faturista or '-'}",
                    f"- Status: {record.status_caixa_noturno or '-'}",
                ]
            )
            if record.motorista_faturista or record.placa_faturista or record.mapa_faturista:
                lines.append(
                    f"- Motorista/Placa/Mapa: {record.motorista_faturista or '-'} | "
                    f"{record.placa_faturista or '-'} | {record.mapa_faturista or '-'}"
                )
            if record.motivo_caixa_noturno:
                lines.append(f"- Motivo: {record.motivo_caixa_noturno}")
            if record.obs:
                lines.append(f"- OBS.: {record.obs}")

        lines.extend(
            [
                "",
                "*Atualizacao rapida:*",
                "- Faturista: FATURISTA 9845 LANCADO MOTORISTA Joao PLACA ABC1234 MAPA 88",
                "- Caixa: CAIXA 9845 RECOLHIDO",
                "- Caixa pendente: CAIXA 9845 NAO RECOLHIDO MOTIVO cliente fechado",
                "- Cancelar: CANCELAR RECOLHA 9845",
                "",
                "CSV anexado no mesmo padrao da planilha de recolhas.",
            ]
        )
        return OutgoingMessage(
            text="\n".join(lines),
            kind="media",
            media_url=_build_csv_data_url(csv_bytes),
            media_type="document",
            media_caption="Solicitacoes de recolha CSV",
            media_filename="solicitacoes_recolha.csv",
        )

    def _build_recolhas_summary_response(
        self,
        *,
        records: list[RecolhaRequestRecord],
        total: int,
        csv_bytes: bytes,
        request_filters: RecolhaRequestFilters | None = None,
    ) -> OutgoingMessage:
        summary = _summarize_recolha_records(records)
        filters = request_filters or RecolhaRequestFilters()
        lines = [
            "Resumo de Recolhas",
            "",
            "*Base:*",
            f"- Total visivel: {total}",
            f"- No filtro: {len(records)}",
            f"- Periodo: {filters.period_label}",
            f"- Status: {filters.status_label}",
            f"- Abertas: {summary['abertas']}",
            f"- Lancadas: {summary['lancadas']}",
            f"- Recolhidas: {summary['recolhidas']}",
            f"- Nao recolhidas: {summary['nao_recolhidas']}",
            "",
            "*Por filial:*",
        ]
        for key, count in summary["por_filial"]:
            lines.append(f"- {key}: {count}")
        lines.append("")
        lines.append("*Por setor:*")
        for key, count in summary["por_setor"]:
            lines.append(f"- {key}: {count}")
        lines.extend(["", "CSV anexado no mesmo padrao da planilha de recolhas."])
        return OutgoingMessage(
            text="\n".join(lines),
            kind="media",
            media_url=_build_csv_data_url(csv_bytes),
            media_type="document",
            media_caption="Solicitacoes de recolha CSV",
            media_filename="solicitacoes_recolha.csv",
        )

    def _handle_admin_session(
        self,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        if not self._is_admin(decision):
            self._reset_session(sender)
            return OutgoingMessage(
                text="Esse menu e exclusivo do administrador.\nSe quiser voltar, envie MENU."
            )

        if _is_back_menu_command(normalized) and session.step == "admin_select_action":
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if session.step == "admin_select_action":
            action = _parse_admin_action(normalized)
            if not action:
                self.sessions[sender] = session
                return self._build_admin_action_menu(invalid_selection=True)
            if action == "summary":
                try:
                    users = self.access_control.list_users()
                except RuntimeError:
                    self._reset_session(sender)
                    return OutgoingMessage(
                        text=(
                            "Nao consegui montar o resumo administrativo agora.\n"
                            "Tente novamente em instantes."
                        )
                    )
                self._reset_session(sender)
                return self._build_admin_summary_response(users)
            if action == "health":
                self._reset_session(sender)
                return self._build_admin_health_response()
            if action == "list":
                try:
                    users = self.access_control.list_users()
                except RuntimeError:
                    self._reset_session(sender)
                    return OutgoingMessage(
                        text=(
                            "Nao consegui listar os usuarios agora.\n"
                            "Tente novamente em instantes."
                        )
                    )
                self._reset_session(sender)
                return self._build_admin_users_list_response(users)
            session.admin_action = action
            session.step = "admin_awaiting_phone"
            session.target_phone = ""
            session.current_name = ""
            session.target_name = ""
            session.target_role = ""
            session.target_sectors = ()
            session.target_gv_vdes = ()
            session.current_roles = ()
            session.current_sectors = ()
            session.current_gv_vdes = ()
            session.current_is_active = True
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if action == "create":
                return OutgoingMessage(
                    text=(
                        "Vamos cadastrar um novo usuario.\n"
                        "Me envie o numero com DDI.\n"
                        "Pode mandar com espacos, + ou traco que eu ajusto aqui.\n"
                        "Exemplo: +55 83 99196-4911"
                    )
                )
            if action == "rename":
                return OutgoingMessage(
                    text=(
                        "Vamos alterar o nome de um usuario que ja existe.\n"
                        "Me envie o numero com DDI.\n"
                        "Pode mandar com espacos, + ou traco que eu ajusto aqui.\n"
                        "Exemplo: +55 83 99196-4911"
                    )
                )
            if action == "check":
                return OutgoingMessage(
                    text=(
                        "Vamos validar o acesso de um numero.\n"
                        "Me envie o telefone com DDI.\n"
                        "Pode mandar com espacos, + ou traco que eu ajusto aqui.\n"
                        "Exemplo: +55 83 99196-4911"
                    )
                )
            return OutgoingMessage(
                text=(
                    "Vamos alterar um usuario que ja existe.\n"
                    "Me envie o numero com DDI.\n"
                    "Pode mandar com espacos, + ou traco que eu ajusto aqui.\n"
                    "Exemplo: +55 83 99196-4911"
                )
            )

        if session.step == "admin_awaiting_phone":
            phone_number = _normalize_phone_number(text)
            if len(phone_number) < 10:
                self.sessions[sender] = session
                return OutgoingMessage(
                    text=(
                        "Nao consegui entender esse numero.\n"
                        "Me envie o telefone com DDI.\n"
                        "Pode mandar com espacos, + ou traco que eu ajusto aqui.\n"
                        "Exemplo: +55 83 99196-4911"
                    )
                )
            try:
                existing_user = self.access_control.get_user(phone_number)
            except (RuntimeError, ValueError):
                self._reset_session(sender)
                return OutgoingMessage(
                    text=(
                        "Nao consegui consultar esse numero agora.\n"
                        "Tente novamente em instantes."
                    )
                )

            if session.admin_action == "create" and existing_user is not None:
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return OutgoingMessage(
                    text=(
                        "Esse numero ja esta cadastrado.\n"
                        "Voce pode escolher 'Alterar acesso' ou enviar outro numero."
                    )
                )

            if session.admin_action in {"update", "rename"} and existing_user is None:
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return OutgoingMessage(
                    text=(
                        "Nao encontrei esse numero no cadastro.\n"
                        "Envie outro numero ou digite MENU para voltar."
                    )
                )

            session.target_phone = phone_number
            session.current_name = str(existing_user.get("name") or "") if existing_user else ""
            session.target_name = session.current_name
            session.current_roles = tuple(str(item) for item in existing_user.get("roles", [])) if existing_user else ()
            session.current_sectors = tuple(str(item) for item in existing_user.get("sectors", [])) if existing_user else ()
            session.current_gv_vdes = tuple(str(item) for item in existing_user.get("gv_vdes", [])) if existing_user else ()
            session.current_is_active = bool(existing_user.get("is_active")) if existing_user else False
            session.target_role = ""
            session.target_sectors = ()
            session.target_gv_vdes = ()
            if session.admin_action == "check":
                self._reset_session(sender)
                return self._build_admin_access_check_response(phone_number=phone_number, user=existing_user)
            session.step = "admin_awaiting_name" if session.admin_action in {"create", "rename"} else "admin_awaiting_role"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if session.admin_action == "create":
                return OutgoingMessage(
                    text=(
                        f"Numero recebido: {phone_number}\n"
                        "Agora me envie o nome desse usuario.\n"
                        "Se preferir deixar sem nome, envie PULAR."
                    )
                )
            if session.admin_action == "rename":
                return OutgoingMessage(
                    text=(
                        f"Numero recebido: {phone_number}\n"
                        f"Nome atual: {session.current_name or '-'}\n"
                        "Agora me envie o novo nome desse usuario.\n"
                        "Se preferir deixar sem nome, envie PULAR."
                    )
                )
            return self._build_role_menu(phone_number=phone_number, session=session)

        if session.step == "admin_awaiting_name":
            if normalized in {"pular", "sem nome", "nao informar", "nao_informar"}:
                session.target_name = ""
            else:
                target_name = _normalize_admin_name(text)
                if not target_name:
                    self.sessions[sender] = session
                    return OutgoingMessage(
                        text=(
                            "Nao consegui entender o nome.\n"
                            "Me envie o nome do usuario ou digite PULAR."
                        )
                    )
                session.target_name = target_name
            session.step = "admin_confirming" if session.admin_action == "rename" else "admin_awaiting_role"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if session.admin_action == "rename":
                return self._build_admin_confirmation(session)
            return self._build_role_menu(phone_number=session.target_phone, session=session)

        if session.step == "admin_awaiting_role":
            role_name = _parse_admin_role(normalized)
            if not role_name:
                self.sessions[sender] = session
                return self._build_role_menu(phone_number=session.target_phone, session=session, invalid_selection=True)
            session.target_role = role_name
            session.target_sectors = ()
            session.target_gv_vdes = ()
            if role_name == ROLE_ADMIN:
                session.step = "admin_confirming"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_admin_confirmation(session)
            session.step = "admin_awaiting_scope"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return OutgoingMessage(text=self._build_scope_prompt(role_name))

        if session.step == "admin_awaiting_scope":
            scope_codes, scope_error = self._resolve_admin_scope_codes(
                text=text,
                role_name=session.target_role,
            )
            if scope_error is not None:
                self.sessions[sender] = session
                return OutgoingMessage(text=scope_error)
            if session.target_role == ROLE_VENDEDOR:
                session.target_sectors = tuple(scope_codes)
                session.target_gv_vdes = ()
            elif session.target_role == ROLE_FINANCEIRO:
                session.target_sectors = tuple(scope_codes)
                session.target_gv_vdes = ()
            elif session.target_role in {ROLE_GERENTE_VENDAS, ROLE_DIRETOR_COMERCIAL}:
                session.target_sectors = ()
                session.target_gv_vdes = tuple(scope_codes)
            session.step = "admin_confirming"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_admin_confirmation(session)

        if session.step == "admin_confirming":
            if normalized in {ADMIN_CONFIRM, "1", "confirmar", "salvar"}:
                try:
                    user = self.access_control.upsert_user(
                        phone_number=session.target_phone,
                        name=session.target_name or None,
                        is_active=True,
                        roles=list(session.current_roles) if session.admin_action == "rename" else [session.target_role],
                        sectors=list(session.current_sectors) if session.admin_action == "rename" else list(session.target_sectors),
                        gv_vdes=list(session.current_gv_vdes) if session.admin_action == "rename" else list(session.target_gv_vdes),
                    )
                except ValueError as exc:
                    self._reset_session(sender)
                    return OutgoingMessage(
                        text=(
                            f"{str(exc).strip()}\n"
                            "Se quiser tentar novamente, envie MENU."
                        )
                    )
                except RuntimeError:
                    self._reset_session(sender)
                    return OutgoingMessage(
                        text=(
                            "Nao consegui salvar agora.\n"
                            "Tente novamente em instantes."
                        )
                    )
                action_text = (
                    "Cadastro concluido"
                    if session.admin_action == "create"
                    else "Nome atualizado"
                    if session.admin_action == "rename"
                    else "Alteracao concluida"
                )
                self._reset_session(sender)
                scope_text = self._format_user_access_label(
                    roles=tuple(str(item) for item in user.get("roles", [])),
                    sectors=tuple(str(item) for item in user.get("sectors", [])),
                    gv_vdes=tuple(str(item) for item in user.get("gv_vdes", [])),
                )
                return OutgoingMessage(
                    text=(
                        f"{action_text} com sucesso.\n"
                        f"Nome: {user['name'] or '-'}\n"
                        f"Numero: {user['phone_number']}\n"
                        f"Cargo: {self._display_role(user['roles'][0]) if user['roles'] else '-'}\n"
                        f"Acesso: {scope_text}\n"
                        "Se quiser continuar, envie MENU."
                    )
                )
            if normalized in {ADMIN_CANCEL, "2", "cancelar"}:
                self._reset_session(sender)
                return self._build_main_menu(decision)
            self.sessions[sender] = session
            return self._build_admin_confirmation(session)

        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _handle_finance_session_impl(
        self,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        if not self._can_use_finance_menu(decision):
            self._reset_session(sender)
            return OutgoingMessage(
                text="Esse menu e exclusivo do financeiro e da administracao.\nSe quiser voltar, envie MENU."
            )

        if _is_back_menu_command(normalized):
            if session.step == "finance_select_action":
                self._reset_session(sender)
                return self._build_main_menu(decision)
            payip_back_response = self.finance_flow.payip_flow.handle_back_command(
                sender=sender,
                session=session,
            )
            if payip_back_response is not None:
                return payip_back_response
            if session.step in {
                "finance_select_summary_mode",
                "finance_clarify_today",
                "finance_select_due_bucket",
                "finance_select_visit_risk_day",
                "finance_select_gv_summary",
                "finance_select_giro_mode",
                "finance_payip_menu",
            }:
                session.step = "finance_select_action"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_finance_menu()
            if session.step == "finance_select_visit_risk_sector":
                return self._open_finance_visit_risk_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                )

        if session.step == "finance_clarify_today":
            clarification_action = _parse_finance_today_clarification(normalized)
            if not clarification_action:
                self.sessions[sender] = session
                return self._build_finance_today_clarification()
            if clarification_action == "summary":
                return self._open_finance_summary_menu(sender=sender, session=session)
            if clarification_action == "visit_risk":
                return self._open_finance_visit_risk_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    visit_day_token=_current_visit_day_token(),
                    visit_day_label=_current_visit_day_label(),
                )
            return self._run_finance_due_bucket(
                sender=sender,
                session=session,
                decision=decision,
                due_bucket="today",
            )

        payip_response = self.finance_flow.payip_flow.handle_session_if_applicable(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )
        if payip_response is not None:
            return payip_response

        if session.step == "finance_select_action":
            request = _parse_hybrid_finance_request(normalized)
            action = request.action
            if request.clarify_today:
                session.step = "finance_clarify_today"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_finance_today_clarification()
            if not action:
                self.sessions[sender] = session
                return self._build_finance_menu(invalid_selection=True)

            if action == "summary":
                if request.summary_mode:
                    return self._run_finance_summary_mode(
                        sender=sender,
                        session=session,
                        decision=decision,
                        summary_mode=request.summary_mode,
                    )
                return self._open_finance_summary_menu(sender=sender, session=session)

            if action == "list":
                return self._open_inadimplencia_summary_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    order_by="name",
                    header_text="Esses sao os clientes inadimplentes da base total (ordem alfabetica).",
                    empty_text=(
                        "No momento, nao encontrei clientes inadimplentes na base total.\n"
                        "Escolha outra opcao ou envie MENU."
                    ),
                    page=1,
                    page_size=INADIMPLENCIA_PAGE_SIZE,
                    list_context=INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL,
                )

            if action == "top":
                return self._open_inadimplencia_summary_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    order_by="total_pendente",
                    header_text="Esses sao os maiores devedores da base total.",
                    empty_text=(
                        "No momento, nao encontrei clientes inadimplentes na base total.\n"
                        "Escolha outra opcao ou envie MENU."
                    ),
                )

            if action == "visit_risk":
                if request.visit_day_label:
                    return self._open_finance_visit_risk_selection(
                        sender=sender,
                        session=session,
                        decision=decision,
                        visit_day_token=_visit_day_token_from_label(request.visit_day_label),
                        visit_day_label=request.visit_day_label,
                    )
                return self._open_finance_visit_risk_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                )

            if action == "gv_summary":
                return self._open_finance_gv_summary_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                )
            if action == "giro":
                if request.visit_day_label:
                    return self._open_giro_visit_day_conversation(
                        sender=sender,
                        session=session,
                        decision=decision,
                        requested_day_label=request.visit_day_label,
                    )
                if request.giro_mode == "total":
                    return self._with_post_result_navigation(
                        sender,
                        session,
                        self._build_giro_total_response(
                            decision,
                            title="Resumo de Giro | Base Total",
                        ),
                        return_menu="finance_giro_menu",
                    )
                if request.giro_mode == "by_filial":
                    return self._with_post_result_navigation(
                        sender,
                        session,
                        self._build_giro_by_filial_response(
                            decision,
                            title="Giro por Filial | Base Total",
                        ),
                        return_menu="finance_giro_menu",
                    )
                if request.giro_mode == "by_gv":
                    return self._with_post_result_navigation(
                        sender,
                        session,
                        self._build_giro_by_gv_response(
                            decision,
                            title="Giro por GV | Base Total",
                        ),
                        return_menu="finance_giro_menu",
                    )
                session.step = "finance_select_giro_mode"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_finance_giro_menu()

            if action == "prazo_limite":
                readiness_error = self._ensure_search_context_ready("prazo_limite", decision=decision)
                if readiness_error is not None:
                    self._reset_session(sender)
                    return readiness_error
                if request.document:
                    self._prepare_search_session(session, search_context="prazo_limite")
                    self._remember_last_context(
                        session,
                        intent="search_prazo_limite",
                        search_context="prazo_limite",
                    )
                    self.sessions[sender] = session
                    return self._run_document_lookup(
                        sender=sender,
                        session=session,
                        decision=decision,
                        document=request.document,
                        return_menu="finance_menu",
                    )
                if request.filial and request.cod_pdv:
                    self._prepare_search_session(session, search_context="prazo_limite")
                    self._remember_last_context(
                        session,
                        intent="search_prazo_limite",
                        search_context="prazo_limite",
                    )
                    self.sessions[sender] = session
                    return self._run_repeatable_registration_lookup(
                        sender=sender,
                        session=session,
                        decision=decision,
                        search_context="prazo_limite",
                        filial=request.filial,
                        cod_pdv=request.cod_pdv,
                        return_menu="finance_menu",
                    )
                if request.query_text:
                    self._prepare_search_session(session, search_context="prazo_limite")
                    self._remember_last_context(
                        session,
                        intent="search_prazo_limite",
                        search_context="prazo_limite",
                    )
                    self.sessions[sender] = session
                    return self._run_name_search(
                        sender=sender,
                        session=session,
                        decision=decision,
                        query_text=request.query_text,
                    )
                return self._open_search_context(
                    sender=sender,
                    session=session,
                    search_context="prazo_limite",
                    decision=decision,
                )

            if action == "recolhas":
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_recolhas_finance_response(
                        request_text=normalized,
                        sender=sender,
                        decision=decision,
                    ),
                    return_menu="finance_menu",
                )

            if action == "payip":
                return self.finance_flow.payip_flow.handle_finance_action(
                    sender=sender,
                    session=session,
                    text=text,
                    normalized=normalized,
                    decision=decision,
                )

            if request.due_bucket:
                return self._run_finance_due_bucket(
                    sender=sender,
                    session=session,
                    decision=decision,
                    due_bucket=request.due_bucket,
                )
            session.step = "finance_select_due_bucket"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_due_menu()

        if session.step == "finance_select_summary_mode":
            summary_mode = _parse_finance_summary_mode(normalized)
            if not summary_mode:
                self.sessions[sender] = session
                return self._build_finance_summary_menu(invalid_selection=True)
            return self._run_finance_summary_mode(
                sender=sender,
                session=session,
                decision=decision,
                summary_mode=summary_mode,
            )

        if session.step == "finance_select_due_bucket":
            due_bucket = _parse_finance_due_bucket(normalized)
            if not due_bucket:
                self.sessions[sender] = session
                return self._build_finance_due_menu(invalid_selection=True)
            return self._run_finance_due_bucket(
                sender=sender,
                session=session,
                decision=decision,
                due_bucket=due_bucket,
            )

        if session.step == "finance_select_visit_risk_day":
            selected_visit_risk_day = _select_visit_day(
                text=text,
                normalized=normalized,
                visit_days=session.visit_risk_day_options,
            )
            if selected_visit_risk_day is None:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    invalid_selection=True,
                )
            visit_day_token = _visit_day_token_from_label(selected_visit_risk_day)
            if not visit_day_token:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    invalid_selection=True,
                )
            return self._open_finance_visit_risk_selection(
                sender=sender,
                session=session,
                decision=decision,
                visit_day_token=visit_day_token,
                visit_day_label=selected_visit_risk_day,
            )

        if session.step == "finance_select_visit_risk_gv":
            selected_gv = _select_finance_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )
            filtered_summaries = [
                summary
                for summary in session.visit_risk_summaries
                if normalize_stored_scope_value(summary.manager_code) == normalize_stored_scope_value(selected_gv)
            ]
            if not filtered_summaries:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )
            session.step = "finance_select_visit_risk_sector"
            session.visit_risk_summaries = tuple(filtered_summaries)
            session.selected_visit_risk_gv = selected_gv
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_menu(
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                summaries=filtered_summaries,
            )

        if session.step == "finance_select_visit_risk_sector":
            selected_summary = _select_finance_visit_risk_summary(
                text=text,
                normalized=normalized,
                summaries=session.visit_risk_summaries,
            )
            if selected_summary is None:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_visit_risk_sector_response(
                    decision=decision,
                    summary=selected_summary,
                    visit_day_token=session.selected_visit_risk_token or _current_visit_day_token(),
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                ),
                return_menu="finance_visit_risk_sector",
            )

        if session.step == "finance_select_gv_summary":
            selected_gv = _select_finance_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[sender] = session
                return self._build_finance_gv_summary_menu(
                    gv_options=list(session.finance_gv_options),
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_gv_summary_response(
                    decision=decision,
                    gv_vdes_override=(selected_gv,),
                    title=f"Resumo de {_format_gv_scope_label(selected_gv)}",
                ),
                return_menu="finance_gv_summary",
            )

        if session.step == "finance_select_giro_mode":
            giro_mode = _parse_giro_mode(normalized)
            if not giro_mode:
                self.sessions[sender] = session
                return self._build_finance_giro_menu(invalid_selection=True)

            if giro_mode == "total":
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_giro_total_response(
                        decision,
                        title="Resumo de Giro | Base Total",
                    ),
                    return_menu="finance_giro_menu",
                )
            if giro_mode == "by_filial":
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_giro_by_filial_response(
                        decision,
                        title="Giro por Filial | Base Total",
                    ),
                    return_menu="finance_giro_menu",
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_giro_by_gv_response(
                    decision,
                    title="Giro por GV | Base Total",
                ),
                return_menu="finance_giro_menu",
            )

        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _open_inadimplencia_summary_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        order_by: str,
        header_text: str,
        empty_text: str,
        due_bucket: str | None = None,
        page: int = 1,
        page_size: int = INADIMPLENCIA_PAGE_SIZE,
        list_context: str = "",
        known_total_clients: int | None = None,
    ) -> OutgoingMessage:
        total_clients = (
            max(int(known_total_clients), 0)
            if known_total_clients is not None
            else self.inadimplencia_service.count_clients_in_scope(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                due_bucket=due_bucket,
            )
        )
        current_page = max(int(page), 1)
        page_limit = max(int(page_size), 1)
        summaries = self.inadimplencia_service.list_client_summaries_in_scope(
            allowed_sectors=self._allowed_sectors(decision),
            allowed_gv_vdes=self._allowed_gv_vdes(decision),
            limit=page_limit,
            offset=(current_page - 1) * page_limit,
            order_by=order_by,
            due_bucket=due_bucket,
        )
        if not summaries:
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return OutgoingMessage(text=empty_text)

        if len(summaries) == 1 and total_clients <= 1:
            summary = summaries[0]
            return_menu = "search_menu"
            if self._can_use_finance_menu(decision):
                return_menu = "finance_menu"
            elif self._is_gerente_vendas(decision):
                return_menu = "manager_summary"
            elif self._is_diretor_comercial(decision):
                return_menu = "director_summary"
            self._remember_last_context(
                session,
                intent="inadimplencia_client",
                search_context="inadimplencia",
                query_text=header_text,
                client_filial=summary.filial,
                client_cod_pdv=summary.cod_pdv,
                client_name=summary.nome,
            )
            records = self.inadimplencia_service.search_by_registration(
                filial=summary.filial,
                cod_pdv=summary.cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_inadimplencia_response(
                    records,
                    f"cliente {summary.nome} | revenda {summary.filial} | NB {summary.cod_pdv}",
                    compact=list_context == INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS,
                ),
                return_menu=return_menu,
            )

        session.step = "awaiting_inadimplencia_client_selection"
        session.search_context = "inadimplencia"
        session.fantasia_query = _encode_inadimplencia_header(header_text)
        session.inadimplencia_client_summaries = tuple(summaries)
        session.inadimplencia_total_available = total_clients
        session.inadimplencia_list_context = list_context
        session.inadimplencia_page = current_page
        session.inadimplencia_page_size = page_limit
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_inadimplencia_client_menu(
            query_text=session.fantasia_query,
            summaries=summaries,
            total_available=total_clients,
            page=current_page if list_context else None,
            page_size=page_limit,
            list_context=list_context,
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
        return ROLE_ADMIN in decision.roles

    def _is_financeiro(self, decision: AccessDecision) -> bool:
        if self._is_admin(decision):
            return False
        return ROLE_FINANCEIRO in decision.roles

    def _is_vendedor(self, decision: AccessDecision) -> bool:
        if self._is_admin(decision):
            return False
        return ROLE_VENDEDOR in decision.roles

    def _is_gerente_vendas(self, decision: AccessDecision) -> bool:
        if self._is_admin(decision):
            return False
        return ROLE_GERENTE_VENDAS in decision.roles

    def _is_diretor_comercial(self, decision: AccessDecision) -> bool:
        if self._is_admin(decision):
            return False
        return ROLE_DIRETOR_COMERCIAL in decision.roles

    def _can_use_finance_menu(self, decision: AccessDecision) -> bool:
        return self._is_admin(decision) or self._is_financeiro(decision)

    def _can_request_recolha(self, decision: AccessDecision) -> bool:
        return self._is_vendedor(decision) or self._can_use_finance_menu(decision)

    def _can_view_recolhas(self, decision: AccessDecision) -> bool:
        return (
            self._can_request_recolha(decision)
            or self._is_gerente_vendas(decision)
            or self._is_diretor_comercial(decision)
        )

    def _can_use_critica(self, decision: AccessDecision) -> bool:
        return self._is_vendedor(decision) or self._is_gerente_vendas(decision)

    def _can_update_recolhas(self, decision: AccessDecision) -> bool:
        return self._can_use_finance_menu(decision)

    def _can_clear_recolhas(self, decision: AccessDecision) -> bool:
        return (
            self._is_admin(decision)
            or (self._is_financeiro(decision) and not _recolha_allowed_filiais_from_decision(decision))
            or self._is_gerente_vendas(decision)
            or self._is_diretor_comercial(decision)
        )

    def _can_manage_recolhas(self, decision: AccessDecision) -> bool:
        return self._can_clear_recolhas(decision)

    def _can_use_payip_menu(self, decision: AccessDecision) -> bool:
        return self._can_use_finance_menu(decision) and self._has_area_access(decision, "payip")

    def _has_unrestricted_lookup_access(self, decision: AccessDecision) -> bool:
        if self._is_admin(decision):
            return True
        return self._is_financeiro(decision) and not decision.sectors and not decision.gv_vdes

    def _uses_grouped_visit_flow(self, decision: AccessDecision) -> bool:
        return self._is_financeiro(decision) or self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)

    def _uses_grouped_giro_visit_flow(self, decision: AccessDecision) -> bool:
        return (
            self._has_unrestricted_lookup_access(decision)
            or self._is_financeiro(decision)
            or self._is_gerente_vendas(decision)
            or self._is_diretor_comercial(decision)
        )

    def _can_access_sectors(self, decision: AccessDecision) -> bool:
        if self._has_unrestricted_lookup_access(decision):
            return True
        return bool(decision.sectors or decision.gv_vdes)

    def _allowed_sectors(self, decision: AccessDecision) -> list[str] | None:
        if self._has_unrestricted_lookup_access(decision):
            return None
        return list(decision.sectors)

    def _allowed_gv_vdes(self, decision: AccessDecision) -> list[str] | None:
        if self._has_unrestricted_lookup_access(decision):
            return None
        return list(decision.gv_vdes)

    def _can_use_visit_menu(self, decision: AccessDecision) -> bool:
        if self._is_admin(decision):
            return False
        return self._uses_grouped_visit_flow(decision) or self._is_vendedor(decision)

    def _can_use_gv_summary_menu(self, decision: AccessDecision) -> bool:
        return (self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)) and self._can_access_sectors(decision)

    def _can_use_seller_summary_menu(self, decision: AccessDecision) -> bool:
        return self._is_vendedor(decision) and self._can_access_sectors(decision)

    def _can_use_seller_risk_menu(self, decision: AccessDecision) -> bool:
        return self._is_vendedor(decision) and self._can_access_sectors(decision)

    def _decision_for_area(self, decision: AccessDecision, area: str) -> AccessDecision:
        normalized_area = _normalize_choice(area) or "cliente"
        if not decision.normalized_number or not self.access_control.enabled:
            return decision
        if decision.area == normalized_area and decision.allowed:
            return decision
        return self.access_control.authorize(phone_number=decision.normalized_number, area=normalized_area)

    def _has_area_access(self, decision: AccessDecision, area: str) -> bool:
        return self._decision_for_area(decision, area).allowed

    def _build_area_access_denied_response(self, area: str) -> OutgoingMessage:
        if area == "inadimplencia":
            return OutgoingMessage(
                text=(
                    "Seu numero ainda nao tem acesso a essa consulta de inadimplencia.\n"
                    "Peca a liberacao ao responsavel e tente novamente."
                )
            )
        if area == "comodato":
            return OutgoingMessage(
                text=(
                    "Seu numero ainda nao tem acesso a essa consulta de comodatos.\n"
                    "Peca a liberacao ao responsavel e tente novamente."
                )
            )
        return OutgoingMessage(
            text=(
                "Seu numero ainda nao tem acesso a essa consulta.\n"
                "Peca a liberacao ao responsavel e tente novamente."
            )
        )

    def _ensure_search_context_ready(
        self,
        search_context: str,
        decision: AccessDecision | None = None,
    ) -> OutgoingMessage | None:
        if decision is not None:
            area_map = {
                "comodato": "comodato",
                "inadimplencia": "inadimplencia",
                "giro": "cliente",
                "documentacao": "cliente",
                "prazo_limite": "cliente",
            }
            area = area_map.get(search_context, search_context)
            area_decision = self._decision_for_area(decision, area)
            if not area_decision.allowed:
                return self._build_area_access_denied_response(area)

        if search_context == "inadimplencia":
            status = self.inadimplencia_service.status()
            if not status["ready"]:
                return OutgoingMessage(
                    text=(
                        "No momento, eu nao consegui acessar a base de inadimplencia.\n"
                        "Tente novamente daqui a pouco."
                    )
                )
            return None
        if search_context == "comodato":
            status = self.comodatos_service.status()
            if not status["ready"]:
                return OutgoingMessage(
                    text=(
                        "No momento, eu nao consegui acessar a base de comodatos.\n"
                        "Tente novamente daqui a pouco."
                    )
                )
            return None
        if search_context == "giro":
            status = self.giro_service.status()
            if not status["ready"]:
                return OutgoingMessage(
                    text=(
                        "No momento, eu nao consegui acessar a base de giro.\n"
                        "Tente novamente daqui a pouco."
                    )
                )
            return None
        if search_context == "documentacao":
            status = self.documentacao_pendente_service.status()
            if not status["ready"]:
                last_error = str(status.get("last_error") or "").strip().lower()
                if "ainda nao foi importada" in last_error:
                    return OutgoingMessage(
                        text=(
                            "A base de documentacao pendente ainda nao foi importada no painel admin.\n"
                            "Assim que o arquivo for validado e importado, eu consigo consultar normalmente."
                        )
                    )
                return OutgoingMessage(
                    text=(
                        "No momento, eu nao consegui acessar a base de documentacao pendente.\n"
                        "Tente novamente daqui a pouco."
                    )
                )
            return None
        if search_context == "prazo_limite":
            status = self.prazo_limite_service.status()
            if not status["ready"]:
                last_error = str(status.get("last_error") or "").strip().lower()
                if "ainda nao foi importada" in last_error:
                    return OutgoingMessage(
                        text=(
                            "A base de prazo e limite ainda nao foi importada no painel admin.\n"
                            "Assim que o arquivo for validado e importado, eu consigo consultar normalmente."
                        )
                    )
                return OutgoingMessage(
                    text=(
                        "No momento, eu nao consegui acessar a base de prazo e limite.\n"
                        "Tente novamente daqui a pouco."
                    )
                )
            return None

        status = self.query_service.status()
        if not status["ready"]:
            return OutgoingMessage(
                text=(
                    "No momento, eu nao consegui acessar a base de clientes.\n"
                    "Tente novamente daqui a pouco."
                )
            )
        return None

    def _ensure_scoped_lookup_access(self, decision: AccessDecision, search_context: str) -> OutgoingMessage | None:
        status_error = self._ensure_search_context_ready(search_context, decision=decision)
        if status_error is not None:
            return status_error
        if not self._can_access_sectors(decision):
            if search_context == "inadimplencia":
                return OutgoingMessage(
                    text=(
                        "Seu numero ainda nao esta liberado com um escopo comercial para consultar a inadimplencia.\n"
                        "Peca esse ajuste ao responsavel e tente novamente."
                    )
                )
            if search_context == "comodato":
                return OutgoingMessage(
                    text=(
                        "Seu numero ainda nao esta liberado com um escopo comercial para consultar os comodatos.\n"
                        "Peca esse ajuste ao responsavel e tente novamente."
                    )
                )
            if search_context == "giro":
                return OutgoingMessage(
                    text=(
                        "Seu numero ainda nao esta liberado com um escopo comercial para consultar o giro.\n"
                        "Peca esse ajuste ao responsavel e tente novamente."
                    )
                )
            if search_context == "documentacao":
                return OutgoingMessage(
                    text=(
                        "Seu numero ainda nao esta liberado com um escopo comercial para consultar a documentacao pendente.\n"
                        "Peca esse ajuste ao responsavel e tente novamente."
                    )
                )
            if search_context == "prazo_limite":
                return OutgoingMessage(
                    text=(
                        "Seu numero ainda nao esta liberado para consultar prazo e limite.\n"
                        "Peca esse ajuste ao responsavel e tente novamente."
                    )
                )
            return OutgoingMessage(
                text=(
                    "Seu numero ainda nao esta liberado com um escopo comercial para esse tipo de consulta.\n"
                    "Para buscar por filial, codigo, nome ou visitas do dia, peca esse ajuste ao responsavel.\n"
                    "Se preferir, voce pode consultar por CPF ou CNPJ."
                )
            )
        return None

    def _main_menu_summary_option_id(self, decision: AccessDecision) -> str:
        if not self._can_use_gv_summary_menu(decision):
            return ""
        if self._is_gerente_vendas(decision):
            return MENU_MANAGER
        return MENU_GV_SUMMARY

    def _main_menu_option_ids(self, decision: AccessDecision) -> list[str]:
        option_ids: list[str] = []
        can_use_cliente = self._has_area_access(decision, "cliente")
        can_use_inadimplencia = self._has_area_access(decision, "inadimplencia")
        can_use_comodato = self._has_area_access(decision, "comodato")
        can_use_documentacao = can_use_cliente
        can_use_visit_menu = self._can_use_visit_menu(decision) and can_use_cliente
        can_use_finance_menu = self._can_use_finance_menu(decision) and can_use_inadimplencia
        can_use_seller_summary_menu = self._can_use_seller_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_risk_menu = self._can_use_seller_risk_menu(decision) and can_use_inadimplencia

        summary_option_id = self._main_menu_summary_option_id(decision)
        if self._is_vendedor(decision):
            if can_use_visit_menu:
                option_ids.append(MENU_VISIT_DAY)
            if can_use_seller_risk_menu:
                option_ids.append(MENU_SELLER_RISK)
            if can_use_cliente:
                option_ids.append(MENU_GIRO)
            if can_use_documentacao:
                option_ids.append(MENU_DOCUMENTACAO)
            if can_use_cliente:
                option_ids.append(MENU_SEARCH)
            if can_use_inadimplencia:
                option_ids.append(MENU_INADIMPLENCIA)
            if can_use_comodato:
                option_ids.append(MENU_COMODATOS)
            if can_use_cliente:
                option_ids.append(MENU_RECOLHA)
            if can_use_seller_summary_menu:
                option_ids.append(MENU_SELLER_SUMMARY)
        else:
            if self._is_gerente_vendas(decision):
                if summary_option_id:
                    option_ids.append(summary_option_id)
                if can_use_visit_menu:
                    option_ids.append(MENU_VISIT_DAY)
                if can_use_inadimplencia:
                    option_ids.append(MENU_INADIMPLENCIA)
                if can_use_cliente:
                    option_ids.append(MENU_GIRO)
                if can_use_documentacao:
                    option_ids.append(MENU_DOCUMENTACAO)
                if can_use_cliente:
                    option_ids.append(MENU_SEARCH)
                if can_use_comodato:
                    option_ids.append(MENU_COMODATOS)
            elif self._is_diretor_comercial(decision):
                if summary_option_id:
                    option_ids.append(summary_option_id)
                if can_use_visit_menu:
                    option_ids.append(MENU_VISIT_DAY)
                if can_use_inadimplencia:
                    option_ids.append(MENU_INADIMPLENCIA)
                if can_use_cliente:
                    option_ids.append(MENU_GIRO)
                if can_use_documentacao:
                    option_ids.append(MENU_DOCUMENTACAO)
                if can_use_cliente:
                    option_ids.append(MENU_SEARCH)
                if can_use_comodato:
                    option_ids.append(MENU_COMODATOS)
            else:
                if can_use_cliente:
                    option_ids.append(MENU_SEARCH)
                if can_use_inadimplencia:
                    option_ids.append(MENU_INADIMPLENCIA)
                if can_use_cliente:
                    option_ids.append(MENU_GIRO)
                if can_use_documentacao:
                    option_ids.append(MENU_DOCUMENTACAO)
                if can_use_visit_menu:
                    option_ids.append(MENU_VISIT_DAY)
                if can_use_comodato:
                    option_ids.append(MENU_COMODATOS)
                if summary_option_id:
                    option_ids.append(summary_option_id)
                if can_use_seller_summary_menu:
                    option_ids.append(MENU_SELLER_SUMMARY)
                    if can_use_seller_risk_menu:
                        option_ids.append(MENU_SELLER_RISK)
                if can_use_finance_menu:
                    option_ids.append(MENU_FINANCEIRO)

        if self._is_admin(decision):
            option_ids.append(MENU_ADMIN_ACCESS)

        return option_ids

    def _main_menu_shortcuts(self, decision: AccessDecision) -> dict[str, str]:
        option_ids = self._main_menu_option_ids(decision)
        return {option_id: str(index) for index, option_id in enumerate(option_ids, start=1)}

    def _build_main_menu(self, decision: AccessDecision, invalid_selection: bool = False) -> OutgoingMessage:
        can_use_cliente = self._has_area_access(decision, "cliente")
        can_use_inadimplencia = self._has_area_access(decision, "inadimplencia")
        can_use_comodato = self._has_area_access(decision, "comodato")
        can_use_giro = can_use_cliente
        can_use_documentacao = can_use_cliente
        can_use_visit_menu = self._can_use_visit_menu(decision) and can_use_cliente
        can_use_finance_menu = self._can_use_finance_menu(decision) and can_use_inadimplencia
        can_use_gv_summary_menu = self._can_use_gv_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_summary_menu = self._can_use_seller_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_risk_menu = self._can_use_seller_risk_menu(decision) and can_use_inadimplencia
        shortcut_map = self._main_menu_shortcuts(decision)
        option_ids = self._main_menu_option_ids(decision)
        summary_option_id = self._main_menu_summary_option_id(decision)

        option_specs: dict[str, InteractiveOption] = {}
        if can_use_cliente:
            option_specs[MENU_SEARCH] = InteractiveOption(
                option_id=MENU_SEARCH,
                title="Buscar Cliente",
                description="Encontrar um cliente da sua base",
                shortcut=shortcut_map.get(MENU_SEARCH, ""),
            )
        if can_use_inadimplencia:
            inad_title = "Titulos em Aberto"
            inad_description = "Ver vencidos e proximos vencimentos"
            if self._is_vendedor(decision):
                inad_title = "Cobranca da Carteira"
                inad_description = "Ver inadimplentes e proximos vencimentos da sua base"
            elif self._is_gerente_vendas(decision):
                inad_title = "Cobranca da Gerencia"
                inad_description = "Ver inadimplentes e proximos vencimentos do GV"
            elif self._is_diretor_comercial(decision):
                inad_title = "Cobranca"
                inad_description = "Ver inadimplentes e proximos vencimentos"
            option_specs[MENU_INADIMPLENCIA] = InteractiveOption(
                option_id=MENU_INADIMPLENCIA,
                title=inad_title,
                description=inad_description,
                shortcut=shortcut_map.get(MENU_INADIMPLENCIA, ""),
            )
        if can_use_giro:
            giro_title = "Risco de Giro"
            giro_description = "Ver oportunidades de caixa por dia"
            if self._is_vendedor(decision):
                giro_title = "Giro"
                giro_description = "Ver oportunidades de caixa por dia"
            elif self._is_gerente_vendas(decision):
                giro_title = "Giro da Gerencia"
                giro_description = "Ver oportunidades de caixa por dia no GV"
            elif self._is_diretor_comercial(decision):
                giro_title = "Giro"
                giro_description = "Ver oportunidades de caixa por dia"
            option_specs[MENU_GIRO] = InteractiveOption(
                option_id=MENU_GIRO,
                title=giro_title,
                description=giro_description,
                shortcut=shortcut_map.get(MENU_GIRO, ""),
            )
        if can_use_documentacao:
            option_specs[MENU_DOCUMENTACAO] = InteractiveOption(
                option_id=MENU_DOCUMENTACAO,
                title="Documentacao Pendente",
                description="Ver documentos faltando por cliente e por dia",
                shortcut=shortcut_map.get(MENU_DOCUMENTACAO, ""),
            )
        if self._is_vendedor(decision) and can_use_cliente:
            option_specs[MENU_RECOLHA] = InteractiveOption(
                option_id=MENU_RECOLHA,
                title="Solicitar Recolha",
                description="Registrar pedido de recolha para o financeiro",
                shortcut=shortcut_map.get(MENU_RECOLHA, ""),
            )
        footer = "Responda com o numero ou com o nome da opcao."
        if can_use_visit_menu:
            visit_title = "Rota do Dia"
            visit_description = "Ver os clientes da rota de hoje"
            if self._is_gerente_vendas(decision):
                visit_description = "Ver a rota do dia por setor"
            elif self._is_diretor_comercial(decision):
                visit_description = "Ver a rota do dia por GV e setor"
            option_specs[MENU_VISIT_DAY] = InteractiveOption(
                option_id=MENU_VISIT_DAY,
                title=visit_title,
                description=visit_description,
                shortcut=shortcut_map.get(MENU_VISIT_DAY, ""),
            )
        if can_use_comodato:
            option_specs[MENU_COMODATOS] = InteractiveOption(
                option_id=MENU_COMODATOS,
                title="Comodatos",
                description="Ver pendencias de comodato",
                shortcut=shortcut_map.get(MENU_COMODATOS, ""),
            )
        if can_use_gv_summary_menu:
            summary_title = "Resumo da Gerencia"
            summary_description = "Ver um resumo rapido do seu GV"
            summary_footer = "Responda com o numero ou com o nome da opcao."
            if self._is_diretor_comercial(decision):
                summary_title = "Diretoria"
                summary_description = "Risco, cobranca, GVs, filiais e giro"
                summary_footer = (
                    "Responda com o numero ou com o nome da opcao. "
                    "Use esse menu como rotina da diretoria: diretoria, rota, cobranca, giro, cliente e comodatos."
                )
            elif self._is_gerente_vendas(decision):
                summary_title = "Gerencia"
                summary_description = "Painel consolidado da gerencia: risco, vencimentos, equipe, filiais e resumo"
                summary_footer = (
                    "Responda com o numero ou com o nome da opcao. "
                    "Atalhos uteis: gerencia, rota segunda, inad segunda, giro segunda, vencimentos e equipe."
                )
            option_specs[summary_option_id] = InteractiveOption(
                option_id=summary_option_id,
                title=summary_title,
                description=summary_description,
                shortcut=shortcut_map.get(summary_option_id, ""),
            )
            footer = summary_footer
        if can_use_seller_summary_menu:
            option_specs[MENU_SELLER_SUMMARY] = InteractiveOption(
                option_id=MENU_SELLER_SUMMARY,
                title="Carteira",
                description="Ver base, rota, risco e giro da sua carteira",
                shortcut=shortcut_map.get(MENU_SELLER_SUMMARY, ""),
            )
            if can_use_seller_risk_menu:
                option_specs[MENU_SELLER_RISK] = InteractiveOption(
                    option_id=MENU_SELLER_RISK,
                    title="Risco da Rota",
                    description="Ver clientes da rota com atraso ou vencimento",
                    shortcut=shortcut_map.get(MENU_SELLER_RISK, ""),
                )
            footer = (
                "Responda com o numero ou com o nome da opcao. "
                "Atalhos uteis: rota segunda, giro quinta, inad hoje, 3 6643 e inad santa maria."
            )
        if can_use_finance_menu:
            option_specs[MENU_FINANCEIRO] = InteractiveOption(
                option_id=MENU_FINANCEIRO,
                title="Financeiro",
                description="Ver resumo e cobrancas",
                shortcut=shortcut_map.get(MENU_FINANCEIRO, ""),
            )
            footer = "Responda com o numero ou com o nome da opcao."
        if self._is_admin(decision):
            option_specs[MENU_ADMIN_ACCESS] = InteractiveOption(
                option_id=MENU_ADMIN_ACCESS,
                title="Admin",
                description="Cadastrar ou ajustar acessos",
                shortcut=shortcut_map.get(MENU_ADMIN_ACCESS, ""),
            )
            if self._can_use_finance_menu(decision):
                footer = "Responda com o numero ou com o nome da opcao."
            else:
                footer = "Responda com o numero ou com o nome da opcao."
        options = [option_specs[option_id] for option_id in option_ids if option_id in option_specs]
        text = "Escolha o que voce quer acompanhar agora."
        if invalid_selection:
            text = _invalid_option_text("Escolha uma opcao do menu.")
        if not options:
            if not decision.allowed:
                text = (
                    "Seu numero ainda nao esta cadastrado para usar o bot.\n"
                    "Peca a liberacao ao responsavel e tente novamente."
                )
            else:
                text = (
                    "Seu numero esta ativo, mas ainda nao encontrei menus liberados para ele.\n"
                    "Peca a liberacao ao responsavel e tente novamente."
                )
        return OutgoingMessage(
            kind="menu",
            title="Consultas",
            text=text,
            footer=footer,
            button_text="Ver opcoes",
            options=tuple(options),
        )

    def _build_search_menu(
        self,
        search_context: str,
        decision: AccessDecision | None = None,
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        context_label_map = {
            "cliente": "o cliente",
            "inadimplencia": "a inadimplencia",
            "comodato": "os comodatos pendentes",
            "giro": "o giro",
            "documentacao": "a documentacao pendente",
            "prazo_limite": "prazo e limite",
        }
        context_label = context_label_map.get(search_context, "a consulta")
        if search_context == "inadimplencia" and decision is not None and self._is_vendedor(decision):
            context_label = "a cobranca da carteira"
        if search_context == "inadimplencia" and decision is not None and self._is_gerente_vendas(decision):
            context_label = "a cobranca da gerencia"
        registration_title = "Filial e codigo" if search_context == "cliente" else "Filial e NB"
        registration_description = (
            "Voce pode mandar filial e codigo juntos"
            if search_context == "cliente"
            else "Voce pode mandar filial e NB juntos"
        )
        text = f"Como voce quer procurar {context_label}?"
        if invalid_selection:
            text = _invalid_option_text(f"Me diga como voce quer procurar {context_label}.")
        if search_context == "inadimplencia":
            base_summary = self._build_inadimplencia_base_summary(decision)
            if base_summary:
                text = f"{base_summary}\n\n{text}"
        options = [
            InteractiveOption(
                option_id=SEARCH_BY_REGISTRATION,
                title=registration_title,
                description=registration_description,
                shortcut="1",
            ),
            InteractiveOption(
                option_id=SEARCH_BY_FANTASIA,
                title="Nome do cliente",
                description="Buscar por parte do nome",
                shortcut="2",
            ),
            InteractiveOption(
                option_id=SEARCH_BY_DOCUMENT,
                title="CPF ou CNPJ",
                description="Buscar pelo documento",
                shortcut="3",
            ),
        ]
        if search_context == "inadimplencia":
            next_shortcut = 4
            if decision is not None and self._can_access_sectors(decision):
                options.append(
                    InteractiveOption(
                        option_id=SEARCH_BY_VISIT_DAY,
                        title="Risco por dia",
                        description="Consultar a rota com risco financeiro pelo dia",
                        shortcut=str(next_shortcut),
                    )
                )
                next_shortcut += 1
            if decision is not None and self._is_vendedor(decision):
                options.append(
                    InteractiveOption(
                        option_id=FINANCE_DUE_TOMORROW,
                        title="Vence amanha",
                        description="Clientes com vencimento para amanha",
                        shortcut=str(next_shortcut),
                    )
                )
                next_shortcut += 1
                options.append(
                    InteractiveOption(
                        option_id=FINANCE_DUE_IN_TWO_DAYS,
                        title="Vence em 2 dias",
                        description="Clientes que vencem em 2 dias",
                        shortcut=str(next_shortcut),
                    )
                )
                next_shortcut += 1
            options.append(
                InteractiveOption(
                    option_id=SEARCH_BY_INADIMPLENTES_BASE,
                    title="Ver inadimplentes",
                    description="Mostrar os clientes da sua base",
                    shortcut=str(next_shortcut),
                )
            )
        elif search_context == "giro" and decision is not None and self._can_access_sectors(decision):
            options.append(
                InteractiveOption(
                    option_id=SEARCH_BY_VISIT_DAY,
                    title="Giro por dia",
                    description="Resumo de vasilhame e clientes com caixa na mesma mensagem",
                    shortcut="4",
                )
            )
            options.append(
                InteractiveOption(
                    option_id=SEARCH_BY_GIRO_ZERO_BASE,
                    title="Giro Zero da Base",
                    description="Clientes com giro zero",
                    shortcut="5",
                )
            )
        elif search_context == "documentacao" and decision is not None and self._can_access_sectors(decision):
            options.append(
                InteractiveOption(
                    option_id=SEARCH_BY_VISIT_DAY,
                    title="Pendencia por dia",
                    description="Resumo documental e clientes pendentes da rota",
                    shortcut="4",
                )
            )
        footer = "Se quiser voltar ao inicio, envie A, ANT ou MENU."
        if search_context == "cliente":
            footer = (
                "Atalho rapido: envie filial + codigo juntos, por exemplo: 3 6643. "
                "Se quiser voltar ao inicio, envie A, ANT ou MENU."
            )
        if search_context == "inadimplencia" and decision is not None and self._can_access_sectors(decision):
            footer = (
                "Voce pode buscar um cliente ou pedir um dia, por exemplo: inad segunda ou inad santa maria. "
                "Se quiser voltar ao inicio, envie A, ANT ou MENU."
            )
        if search_context == "giro" and decision is not None and self._can_access_sectors(decision):
            text = f"{text}\n\nObs.: nesse menu, giro significa giro de vasilhame."
            footer = (
                "Voce pode buscar um cliente, pedir um dia ou abrir giro zero da base. "
                "Exemplos: giro segunda, giro zero ou giro espeto do paulo. "
                "Se quiser voltar ao inicio, envie A, ANT ou MENU."
            )
        if search_context == "documentacao" and decision is not None and self._can_access_sectors(decision):
            footer = (
                "Voce pode buscar um cliente ou pedir um dia, por exemplo: documentacao segunda ou documentacao bar central. "
                "Se quiser voltar ao inicio, envie A, ANT ou MENU."
            )
        if search_context == "prazo_limite":
            footer = (
                "Voce pode buscar por filial e NB, por nome ou por documento. "
                "Exemplos: 3 9845, bar central ou 12345678901. "
                "Se quiser voltar ao inicio, envie A, ANT ou MENU."
            )
        return OutgoingMessage(
            kind="menu",
            title={
                "cliente": "Buscar Cliente",
                "inadimplencia": (
                    "Cobranca da Carteira"
                    if decision is not None and self._is_vendedor(decision)
                    else (
                        "Cobranca da Gerencia"
                        if decision is not None and self._is_gerente_vendas(decision)
                        else "Consultar Inadimplencia"
                    )
                ),
                "comodato": "Consultar Comodatos",
                "giro": "Consultar Giro",
                "documentacao": "Documentacao Pendente",
                "prazo_limite": "Prazo e Limite",
            }.get(search_context, "Consultar"),
            text=text,
            footer=footer,
            button_text="Escolher",
            options=tuple(options),
        )

    def _build_inadimplencia_base_summary(self, decision: AccessDecision | None) -> str:
        if decision is None:
            return ""
        if not self._has_unrestricted_lookup_access(decision) and not self._can_access_sectors(decision):
            return ""

        allowed_sectors = self._allowed_sectors(decision)
        allowed_gv_vdes = self._allowed_gv_vdes(decision)
        try:
            summary = self.inadimplencia_service.get_finance_summary(
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
            )
        except RuntimeError:
            return ""

        if self._has_unrestricted_lookup_access(decision):
            scope_label = "base total"
        elif self._is_vendedor(decision):
            scope_label = "carteira"
        else:
            scope_label = "sua base"
        lines = [
            f"Cobranca da {scope_label}: {summary.client_count} inadimplentes | R$ {summary.total_pendente}",
            f"Vence amanha: {summary.due_tomorrow_count} cliente(s) | R$ {summary.due_tomorrow_total}",
            f"Vence em 2 dias: {summary.due_in_two_days_count} cliente(s) | R$ {summary.due_in_two_days_total}",
        ]
        return "\n".join(lines)

    def _inadimplencia_scope_label(self, decision: AccessDecision) -> str:
        if self._has_unrestricted_lookup_access(decision):
            return "base total"
        return "sua base"

    def _build_finance_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "O que voce deseja acompanhar no financeiro?"
        if invalid_selection:
            text = _invalid_option_text("O que voce deseja acompanhar no financeiro?")
        return OutgoingMessage(
            kind="menu",
            title="Financeiro",
            text=text,
            footer=(
                "Fluxo rapido: cobranca, vencimentos, risco da rota, resumo, giro, recolhas e prazo/limite. "
                "Atalhos uteis: inad segunda, risco quinta, giro segunda, recolhas, resumo por gv e prazo e limite. "
                "Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=FINANCE_ACTION_SUMMARY,
                    title="Resumo Organizado",
                    description="Total, revenda, GV e setor",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_LIST,
                    title="Cobranca da Base",
                    description="Lista geral em ordem alfabetica",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_TOP,
                    title="Maiores Devedores",
                    description="Ordenar pelos maiores valores",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_UPCOMING,
                    title="Vencimentos Proximos",
                    description="Separar por 2, 1, 0 dias e vencidos",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_VISIT_RISK,
                    title="Risco da Rota",
                    description="Escolher o dia e ver GVs e setores com risco",
                    shortcut="5",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_GV_SUMMARY,
                    title="Resumo por GV",
                    description="Abrir o resumo de uma chave filial-GV",
                    shortcut="6",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_GIRO,
                    title="Giro",
                    description="Abrir o submenu de giro",
                    shortcut="7",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_PRAZO_LIMITE,
                    title="Prazo e Limite",
                    description="Cruzar documentos com a base de liberacao",
                    shortcut="8",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_PAYIP,
                    title="Pagamentos PayIP",
                    description="Validar sessao e consultar pagamentos",
                    shortcut="9",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_RECOLHAS,
                    title="Solicitacoes de Recolha",
                    description="Ver pedidos enviados pelos vendedores",
                    shortcut="10",
                ),
            ),
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
        text = "Qual faixa voce quer consultar?"
        if invalid_selection:
            text = _invalid_option_text("Qual faixa voce quer consultar?")
        return OutgoingMessage(
            kind="menu",
            title="Vencimentos Proximos",
            text=text,
            footer="Escolha a faixa desejada. Use A ou ANT para voltar, ou MENU para ir ao inicio.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=FINANCE_DUE_IN_TWO_DAYS,
                    title="Vence em 2 dias",
                    description="Clientes que vencem em 2 dias",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=FINANCE_DUE_TOMORROW,
                    title="Vence amanha",
                    description="Clientes com vencimento para amanha",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=FINANCE_DUE_TODAY,
                    title="Vence hoje",
                    description="Clientes que vencem hoje",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=FINANCE_DUE_OVERDUE,
                    title="Ja vencidos",
                    description="Clientes que ja estao inadimplentes",
                    shortcut="4",
                ),
            ),
        )

    def _build_manager_due_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "Qual faixa voce quer consultar na sua gerencia?"
        if invalid_selection:
            text = _invalid_option_text("Qual faixa voce quer consultar na sua gerencia?")
        return OutgoingMessage(
            kind="menu",
            title="Vencimentos Proximos",
            text=text,
            footer="Eu separo por 2 dias, amanha, hoje e vencidos. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=FINANCE_DUE_IN_TWO_DAYS,
                    title="Vence em 2 dias",
                    description="Clientes que vencem em 2 dias",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=FINANCE_DUE_TOMORROW,
                    title="Vence amanha",
                    description="Clientes que vencem amanha",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=FINANCE_DUE_TODAY,
                    title="Vence hoje",
                    description="Clientes que vencem hoje",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=FINANCE_DUE_OVERDUE,
                    title="Ja vencidos",
                    description="Clientes que ja estao vencidos",
                    shortcut="4",
                ),
            ),
        )

    def _build_finance_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "Como voce quer consultar o giro da base?"
        if invalid_selection:
            text = _invalid_option_text("Como voce quer consultar o giro da base?")
        return OutgoingMessage(
            kind="menu",
            title="Giro",
            text=text,
            footer="Voce pode ver total, por filial ou por GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=GIRO_MODE_TOTAL,
                    title="Resumo Total",
                    description="Ver o consolidado da base",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=GIRO_MODE_BY_FILIAL,
                    title="Por Filial",
                    description="Ver o giro separado por revenda",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=GIRO_MODE_BY_GV,
                    title="Por GV",
                    description="Ver o giro separado por chave filial-GV",
                    shortcut="3",
                ),
            ),
        )

    def _build_manager_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "Como voce quer consultar o giro da sua gerencia?"
        if invalid_selection:
            text = _invalid_option_text("Como voce quer consultar o giro da sua gerencia?")
        return OutgoingMessage(
            kind="menu",
            title="Giro da Gerencia",
            text=text,
            footer="Voce pode ver o total da gerencia ou por filial. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=GIRO_MODE_TOTAL,
                    title="Resumo Total",
                    description="Ver o consolidado do seu GV",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=GIRO_MODE_BY_FILIAL,
                    title="Por Filial",
                    description="Ver o giro da gerencia por revenda",
                    shortcut="2",
                ),
            ),
        )

    def _build_director_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "Como voce quer consultar o giro da diretoria?"
        if invalid_selection:
            text = _invalid_option_text("Como voce quer consultar o giro da diretoria?")
        return OutgoingMessage(
            kind="menu",
            title="Giro da Diretoria",
            text=text,
            footer="Voce pode ver por GV ou por filial. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=GIRO_MODE_BY_GV,
                    title="Por GV",
                    description="Consolidar por gerente",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=GIRO_MODE_BY_FILIAL,
                    title="Por Filial",
                    description="Consolidar por revenda",
                    shortcut="2",
                ),
            ),
        )

    def _build_giro_total_response(
        self,
        decision: AccessDecision,
        *,
        title: str,
        gv_vdes_override: tuple[str, ...] | None = None,
    ) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(
            decision,
            "giro",
            "total",
            title,
            tuple(gv_vdes_override or ()),
        )
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        giro_summary = self._safe_giro_scope_summary(decision, gv_vdes_override=gv_vdes_override)
        if giro_summary is None:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo de giro agora.\n"
                    "Tente novamente em instantes."
                )
            )

        lines = [title, ""]
        self._append_giro_summary_lines(lines, giro_summary, compact=False)
        lines.append("")
        lines.append(f"Atualizado em: {giro_summary.planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_giro_zero_base_response(self, decision: AccessDecision) -> OutgoingMessage:
        records = self._safe_giro_zero_base_records(decision)
        if records is None:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o giro zero da base agora.\n"
                    "Tente novamente em instantes."
                )
            )

        scope_label = "base total" if self._has_unrestricted_lookup_access(decision) else "sua base"
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nenhum cliente com giro zero encontrado na {scope_label}.\n"
                    "Regra usada: cliente com caixas na base e faltam caixas = caixas * 2.\n"
                    f"\n{_result_hint_text()}"
                )
            )

        ordered_records = sorted(
            records,
            key=lambda item: (
                _sort_numeric_text(item.filial),
                _sort_numeric_text(item.setor),
                _sort_numeric_text(item.cod_pdv),
            ),
        )
        total_caixas = _sum_formatted_amounts(*(record.total_caixas for record in ordered_records))
        total_faltam = _sum_formatted_amounts(*(record.gap_caixas for record in ordered_records))
        updated_at = next(
            (record.planilha_atualizada_em for record in ordered_records if record.planilha_atualizada_em and record.planilha_atualizada_em != "-"),
            "-",
        )

        lines = [
            "Giro Zero da Base (Vasilhame)",
            "Regra: faltam caixas = caixas * 2",
            "",
            f"Escopo: {scope_label}",
            f"Clientes: {len(ordered_records)} | Caixas: {total_caixas} | Faltam: {total_faltam}",
            f"Giro atualizado em: {updated_at}",
            "",
            "Clientes com giro zero:",
        ]

        current_filial = ""
        current_setor = ""
        for index, record in enumerate(ordered_records, start=1):
            filial = _normalize_filial(record.filial)
            setor = normalize_stored_scope_value(record.setor)
            cod_pdv = _normalize_cod_pdv(record.cod_pdv)
            client_name = (record.nome or "-").strip()
            total_caixas_cliente = _format_quantity(record.total_caixas)
            gap_caixas_cliente = _format_quantity(record.gap_caixas)
            gap_detail = _format_giro_gap_detail(record)
            if filial != current_filial:
                if lines and lines[-1]:
                    lines.append("")
                lines.append(f"Filial {filial or '-'}")
                current_filial = filial
                current_setor = ""
            if setor != current_setor:
                lines.append(f"Setor {setor or '-'}")
                current_setor = setor
            _append_giro_client_block(
                lines,
                index=index,
                client_name=client_name,
                cod_pdv=cod_pdv,
                total_caixas=total_caixas_cliente,
                gap_caixas=gap_caixas_cliente,
                gap_detail=gap_detail,
            )

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_documentacao_pendente_response(
        self,
        records: list[DocumentacaoPendenteClientRecord],
        criteria: str,
        scope_restricted: bool = True,
    ) -> OutgoingMessage:
        if not records:
            scope_note = "dentro do acesso liberado para o seu numero" if scope_restricted else "na base importada"
            return OutgoingMessage(
                text=(
                    f"Nao encontrei documentacao pendente para {criteria} {scope_note}.\n"
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        ordered_records = sorted(
            records,
            key=lambda item: (
                _sort_numeric_text(item.filial),
                _sort_numeric_text(item.setor),
                _sort_numeric_text(item.cod_pdv),
            ),
        )
        lines = [f"Encontrei {len(ordered_records)} registro(s) de documentacao pendente para {criteria}."]
        for index, record in enumerate(ordered_records, start=1):
            lines.append("")
            lines.append(f"{index}. *Cliente:* {record.nome or '-'}")
            lines.append(f"*Revenda:* {record.filial or '-'} | *NB:* {record.cod_pdv or '-'} | *Setor:* {record.setor or '-'}")
            lines.append(
                f"*Resumo:* {record.pending_count} documento(s) pendente(s) | Falta: {_format_documentacao_pending_docs(record.pending_docs)}"
            )
            lines.append(
                f"*Status:* Contrato Social {record.contrato_social} | Cpf {record.cpf} | Rg {record.rg}"
            )
            lines.append(
                f"*Status 2:* Comprovante de residencia {record.comprovante_residencia} | Fachada {record.fachada} | Ficha de Cadastro {record.ficha_cadastro}"
            )
            lines.append(f"*Atualizado em:* {record.planilha_atualizada_em or '-'}")

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_prazo_limite_response(
        self,
        records: list[PrazoLimiteClientRecord],
        criteria: str,
        *,
        decision: AccessDecision,
        scope_restricted: bool = True,
    ) -> OutgoingMessage:
        if not records:
            scope_note = "dentro do acesso liberado para o seu numero" if scope_restricted else "na base importada"
            return OutgoingMessage(
                text=(
                    f"Nao encontrei prazo e limite para {criteria} {scope_note}.\n"
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        ordered_records = sorted(
            records,
            key=lambda item: (
                _sort_numeric_text(item.filial),
                _sort_numeric_text(item.setor),
                _sort_numeric_text(item.cod_pdv),
            ),
        )
        lines = ["Analise Financeira"]
        if len(ordered_records) > 1:
            lines.extend(["", f"Encontrei {len(ordered_records)} cliente(s) para {criteria}."])
        for index, record in enumerate(ordered_records, start=1):
            score_record = self._safe_cliente_score_by_registration(
                filial=record.filial,
                cod_pdv=record.cod_pdv,
            )
            inadimplencia_records = self._safe_inadimplencia_registration_records(
                decision=decision,
                filial=record.filial,
                cod_pdv=record.cod_pdv,
                scope_restricted=scope_restricted,
            )
            giro_records = self._safe_giro_registration_records(
                decision=decision,
                filial=record.filial,
                cod_pdv=record.cod_pdv,
                scope_restricted=scope_restricted,
            )
            lines.append("")
            prefix = f"{index}) " if len(ordered_records) > 1 else ""
            lines.append(f"{prefix}Cliente: {record.nome or '-'}")
            score_prefix = f"*Score: {score_record.score} |* " if score_record is not None and score_record.score else ""
            lines.append(
                f"{score_prefix}Revenda: {record.filial or '-'} | NB: {record.cod_pdv or '-'} | Setor: {record.setor or '-'}"
            )
            lines.append(
                f"RN: {_scope_last_code(record.seller_code or record.setor)} | "
                f"GV: {_scope_last_code(record.manager_code)}"
            )
            cpf_label, cnpj_label = _format_documento_identity(getattr(record, "documento", ""))
            lines.append(f"CPF: {cpf_label} | CNPJ: {cnpj_label}")
            lines.append("")
            lines.append("*Prazo e Limite:*")
            lines.append(f"- Prazo atual: {_summarize_prazo_limite_field(record.entries, 'prazo_atual')}")
            lines.append(f"- Cond. pag.: {_summarize_prazo_limite_field(record.entries, 'cond_pag_atual')}")
            lines.append(f"- Limite total: {_summarize_prazo_limite_field(record.entries, 'limite_total')}")
            lines.append(f"- Pag. em atraso: {_summarize_prazo_limite_field(record.entries, 'percentual_pag_atraso')}")
            self._append_cliente_score_lines(lines, score_record)
            lines.append("")
            lines.append("*Faturamento:*")
            for entry in record.entries:
                pedido_label = _format_entry_pedido_label(entry, media_label="Media por pedido")
                if not pedido_label:
                    pedido_label = f"Pedidos: 0 | Media por pedido: R$ 0,00"
                lines.append(f"- {entry.kpi}: {entry.faturamento_com_pdv} | {pedido_label}")
            lines.append("")
            lines.append("*Inadimplencia:*")
            self._append_financial_analysis_inadimplencia_lines(lines, inadimplencia_records)
            lines.append("")
            self._append_financial_analysis_documentacao_lines(
                lines,
                decision=decision,
                filial=record.filial,
                cod_pdv=record.cod_pdv,
                scope_restricted=scope_restricted,
            )
            lines.append("")
            self._append_financial_analysis_giro_lines(lines, giro_records)
            lines.append("")
            lines.append(f"Atualizado em: {_format_display_date(record.planilha_atualizada_em or '-')}")

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _safe_inadimplencia_registration_records(
        self,
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
        scope_restricted: bool = True,
    ) -> list[InadimplenciaRecord] | None:
        try:
            return self.inadimplencia_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision) if scope_restricted else None,
                allowed_gv_vdes=self._allowed_gv_vdes(decision) if scope_restricted else None,
                limit=100,
            )
        except (RuntimeError, ValueError):
            return None

    def _safe_giro_registration_records(
        self,
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
        scope_restricted: bool = True,
    ) -> list[GiroClientRecord] | None:
        try:
            return self.giro_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision) if scope_restricted else None,
                allowed_gv_vdes=self._allowed_gv_vdes(decision) if scope_restricted else None,
                limit=20,
            )
        except (RuntimeError, ValueError):
            return None

    def _append_financial_analysis_inadimplencia_lines(
        self,
        lines: list[str],
        records: list[InadimplenciaRecord] | None,
    ) -> None:
        if records is None:
            lines.append("- Total vencido: -")
            lines.append("- Titulos em aberto: -")
            return
        total_pendente = _sum_money_values(record.valor_pendente for record in records)
        lines.append(f"- Total vencido: {_format_inadimplencia_money(total_pendente)}")
        lines.append(f"- Titulos em aberto: {len(records)}")

    def _append_financial_analysis_documentacao_lines(
        self,
        lines: list[str],
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
        scope_restricted: bool = True,
    ) -> None:
        lines.append("*Documentacao:*")
        documentacao_record = self._safe_documentacao_registration_record(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
            scope_restricted=scope_restricted,
        )
        if documentacao_record is None:
            lines.append("- Sem registro na base importada")
            return
        cpf_rg_status = _merge_document_status(documentacao_record.cpf, documentacao_record.rg)
        lines.append(f"- Contrato Social: {documentacao_record.contrato_social or '-'}")
        lines.append(f"- Cpf/Rg: {cpf_rg_status}")
        lines.append(f"- Comprovante residencia: {documentacao_record.comprovante_residencia or '-'}")
        lines.append(f"- Fachada: {documentacao_record.fachada or '-'}")

    def _append_financial_analysis_giro_lines(
        self,
        lines: list[str],
        records: list[GiroClientRecord] | None,
    ) -> None:
        lines.append("*Giro de Vasilhame:*")
        if records is None:
            lines.append("- Base de giro indisponivel")
            return
        if not records:
            lines.append("- Sem registro no giro importado")
            return

        total_caixas = _format_quantity(
            _sum_formatted_amounts(
                *[
                    value
                    for record in records
                    for value in (record.total_litrinho, record.total_inteira, record.total_litrao)
                ]
            )
        )
        caixas_ok = _format_quantity(
            _sum_formatted_amounts(
                *[
                    value
                    for record in records
                    for value in (record.real_litrinho, record.real_inteira, record.real_litrao)
                ]
            )
        )
        caixas_faltando = _format_quantity(
            _sum_formatted_amounts(
                *[
                    value
                    for record in records
                    for value in (record.gap_litrinho, record.gap_inteira, record.gap_litrao)
                ]
            )
        )
        gap_detail = _format_giro_records_gap_detail(records)
        lines.append(f"- Caixas na base: {total_caixas}")
        lines.append(f"- Caixas OK: {caixas_ok}")
        lines.append(f"- Faltam: {caixas_faltando}")
        if gap_detail:
            lines.append(f"- Falta: {gap_detail}")

    def _build_documentacao_visit_day_response(
        self,
        *,
        visit_day: str,
        decision: AccessDecision,
        summary: DocumentacaoPendenteScopeSummary,
        records: list[DocumentacaoPendenteClientRecord],
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        lines = [f"Documentacao pendente em {visit_day_label}:", ""]
        lines.append(f"Clientes monitorados: {summary.monitored_client_count}")
        lines.append(f"Clientes com pendencia: {summary.pending_client_count}")
        lines.append(f"Documentos faltando: {summary.pending_document_count}")
        lines.append(
            "Resumo pendente: "
            f"CS {summary.contrato_social_pendentes} | "
            f"CPF {summary.cpf_pendentes} | "
            f"RG {summary.rg_pendentes} | "
            f"CR {summary.comprovante_residencia_pendentes} | "
            f"FAC {summary.fachada_pendentes} | "
            f"FC {summary.ficha_cadastro_pendentes}"
        )
        lines.append(f"Documentacao atualizada em: {summary.planilha_atualizada_em or '-'}")

        if not records:
            lines.append("")
            lines.append("Nenhum cliente com documentacao pendente nessa rota.")
            lines.append("")
            lines.append(_result_hint_text())
            return OutgoingMessage(text="\n".join(lines))

        ordered_records = sorted(
            records,
            key=lambda item: (
                _sort_scope_code(item.manager_code or item.seller_code),
                _sort_scope_code(item.seller_code),
                _sort_numeric_text(item.cod_pdv),
                str(item.nome or "").lower(),
            ),
        )
        lines.append("")
        lines.append(
            f"Clientes com pendencia: {len(ordered_records)} | Documentos faltando: {sum(int(record.pending_count or 0) for record in ordered_records)}"
        )
        lines.append("")
        lines.append("Clientes com documentacao pendente:")

        current_manager = ""
        current_seller = ""
        for index, record in enumerate(ordered_records, start=1):
            manager_code = normalize_stored_scope_value(record.manager_code)
            seller_code = normalize_stored_scope_value(record.seller_code)
            if self._has_unrestricted_lookup_access(decision) and manager_code and manager_code != current_manager:
                lines.append(f"{_format_gv_scope_label(manager_code)}")
                current_manager = manager_code
                current_seller = ""
            if seller_code and seller_code != current_seller:
                lines.append(f"Setor {_format_sector_scope_label(seller_code)}")
                current_seller = seller_code
            lines.append(
                f"{index}. Codigo {record.cod_pdv} | {record.nome or '-'} | "
                f"Pendencias {record.pending_count} | Falta: {_format_documentacao_pending_docs(record.pending_docs)}"
            )

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_giro_visit_day_response(
        self,
        *,
        visit_day: str,
        decision: AccessDecision,
        summary: GiroScopeSummary,
        records: list[DClienteRecord],
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        total_caixas = (
            summary.litrinho_monitored_count
            + summary.inteira_monitored_count
            + summary.litrao_monitored_count
        )
        total_ok = (
            summary.litrinho_ok_count
            + summary.inteira_ok_count
            + summary.litrao_ok_count
        )
        total_gap = _sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )
        lines = [f"Oportunidade de giro em {visit_day_label}:", "Tipo: Giro de Vasilhame", ""]
        lines.append(f"Clientes monitorados: {summary.client_count}")
        lines.append(f"Caixas na rota: {_format_quantity(total_caixas)}")
        lines.append(f"Caixas OK: {_format_quantity(total_ok)}")
        lines.append(f"Caixas faltando para bater o giro: {total_gap}")
        self._append_giro_summary_lines(lines, summary, compact=False)

        giro_summaries, giro_updated_at = self._build_visit_day_giro_summaries(decision, records)
        manager_by_seller: dict[str, str] = {}
        include_manager_breakdown = self._uses_grouped_visit_flow(decision) and not self._is_gerente_vendas(decision)
        if include_manager_breakdown:
            try:
                seller_summaries = self.query_service.list_visit_day_seller_summaries(
                    visit_day=visit_day,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=1000,
                )
            except RuntimeError:
                seller_summaries = []
            manager_by_seller = {
                normalize_stored_scope_value(summary_item.seller_code): normalize_stored_scope_value(summary_item.manager_code)
                for summary_item in seller_summaries
                if normalize_stored_scope_value(summary_item.seller_code)
            }

        clients_with_opportunity: list[tuple[str, str, str, str, str, str, str, str]] = []
        total_caixas_values: list[str] = []
        total_gap_values: list[str] = []
        for record in records:
            client_name = record.nome_fantasia or record.razao_social or "-"
            client_summary = giro_summaries.get((_normalize_filial(record.filial), _normalize_cod_pdv(record.cod_pdv)))
            if client_summary is None:
                continue
            setor_code, total_caixas, gap_caixas, gap_detail = client_summary
            if not _is_positive_quantity(total_caixas) or not _is_positive_quantity(gap_caixas):
                continue
            seller_code = normalize_stored_scope_value(f"{_normalize_filial(record.filial)}_{setor_code}")
            manager_code = manager_by_seller.get(seller_code, "")
            total_caixas_values.append(total_caixas)
            total_gap_values.append(gap_caixas)
            clients_with_opportunity.append(
                (
                    manager_code,
                    seller_code,
                    setor_code or "-",
                    str(record.cod_pdv or "").strip(),
                    client_name,
                    total_caixas,
                    gap_caixas,
                    gap_detail,
                )
            )

        clients_with_opportunity.sort(
            key=lambda item: (
                _sort_scope_code(item[0] or item[1]),
                _sort_scope_code(item[1]),
                _sort_numeric_text(item[3]),
                str(item[4] or "").lower(),
            )
        )

        lines.append("")
        lines.append(
            f"Clientes com oportunidade: {len(clients_with_opportunity)} | "
            f"Caixas com giro: {_sum_formatted_amounts(*total_caixas_values) if total_caixas_values else '0'} | "
            f"Faltam: {_sum_formatted_amounts(*total_gap_values) if total_gap_values else '0'}"
        )
        if giro_updated_at:
            lines.append(f"Giro atualizado em: {giro_updated_at}")
        if include_manager_breakdown and manager_by_seller and clients_with_opportunity:
            _append_giro_visit_day_gv_summary_lines(lines, clients_with_opportunity)
        lines.append("")
        lines.append("Clientes com oportunidade de giro:")
        if clients_with_opportunity:
            current_sector = ""
            current_manager = ""
            for index, (manager_code, seller_code, setor_code, cod_pdv, client_name, total_caixas, gap_caixas, gap_detail) in enumerate(
                clients_with_opportunity,
                start=1,
            ):
                if manager_code and manager_code != current_manager:
                    if current_manager:
                        lines.append("")
                    lines.append(f"*{_format_gv_scope_label(manager_code)}*")
                    current_manager = manager_code
                    current_sector = ""
                if setor_code != current_sector:
                    if current_sector:
                        lines.append("")
                    lines.append(f"*Setor {setor_code or '-'}*")
                    current_sector = setor_code
                _append_giro_client_block(
                    lines,
                    index=index,
                    client_name=client_name,
                    cod_pdv=cod_pdv,
                    total_caixas=total_caixas,
                    gap_caixas=gap_caixas,
                    gap_detail=gap_detail,
                )
        else:
            lines.append("Nenhum cliente com oportunidade de giro nesse dia.")
        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_finance_giro_visit_day_response(
        self,
        *,
        visit_day: str,
        decision: AccessDecision,
        summary: GiroScopeSummary,
        records: list[DClienteRecord],
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        total_caixas = (
            summary.litrinho_monitored_count
            + summary.inteira_monitored_count
            + summary.litrao_monitored_count
        )
        total_ok = (
            summary.litrinho_ok_count
            + summary.inteira_ok_count
            + summary.litrao_ok_count
        )
        total_gap = _sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )
        lines = [f"Oportunidade de giro em {visit_day_label}:", "Tipo: Giro de Vasilhame", ""]
        lines.append(f"Clientes monitorados: {summary.client_count}")
        lines.append(f"Caixas na rota: {_format_quantity(total_caixas)}")
        lines.append(f"Caixas OK: {_format_quantity(total_ok)}")
        lines.append(f"Caixas faltando para bater o giro: {total_gap}")
        self._append_giro_summary_lines(lines, summary, compact=False)

        giro_summaries, giro_updated_at = self._build_visit_day_giro_summaries(decision, records)
        try:
            seller_summaries = self.query_service.list_visit_day_seller_summaries(
                visit_day=visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=1000,
            )
        except RuntimeError:
            seller_summaries = []

        manager_by_seller = {
            normalize_stored_scope_value(summary_item.seller_code): normalize_stored_scope_value(summary_item.manager_code)
            for summary_item in seller_summaries
            if normalize_stored_scope_value(summary_item.seller_code)
        }

        clients_with_opportunity: list[tuple[str, str, str, str, str, str, str]] = []
        total_caixas_values: list[str] = []
        total_gap_values: list[str] = []
        for record in records:
            client_summary = giro_summaries.get((_normalize_filial(record.filial), _normalize_cod_pdv(record.cod_pdv)))
            if client_summary is None:
                continue
            setor_code, total_caixas_cliente, gap_caixas_cliente, gap_detail = client_summary
            if not _is_positive_quantity(total_caixas_cliente) or not _is_positive_quantity(gap_caixas_cliente):
                continue
            seller_code = normalize_stored_scope_value(f"{_normalize_filial(record.filial)}_{setor_code}")
            if not seller_code:
                continue
            manager_code = manager_by_seller.get(seller_code, "")
            total_caixas_values.append(total_caixas_cliente)
            total_gap_values.append(gap_caixas_cliente)
            clients_with_opportunity.append(
                (
                    manager_code,
                    seller_code,
                    setor_code or "-",
                    str(record.cod_pdv or "").strip(),
                    record.nome_fantasia or record.razao_social or "-",
                    total_caixas_cliente,
                    gap_caixas_cliente,
                    gap_detail,
                )
            )

        clients_with_opportunity.sort(
            key=lambda item: (
                _sort_scope_code(item[0] or f"{split_scope_pair(item[1])[0]}_999999" if split_scope_pair(item[1]) else item[1]),
                _sort_scope_code(item[1]),
                _sort_numeric_text(item[3]),
                str(item[4] or "").lower(),
            )
        )

        lines.append("")
        lines.append(
            f"Clientes com oportunidade: {len(clients_with_opportunity)} | "
            f"Caixas com giro: {_sum_formatted_amounts(*total_caixas_values) if total_caixas_values else '0'} | "
            f"Faltam: {_sum_formatted_amounts(*total_gap_values) if total_gap_values else '0'}"
        )
        if giro_updated_at:
            lines.append(f"Giro atualizado em: {giro_updated_at}")
        _append_giro_visit_day_gv_summary_lines(lines, clients_with_opportunity)
        lines.append("")
        lines.append("Clientes com oportunidade de giro:")
        if not clients_with_opportunity:
            lines.append("Nenhum cliente com oportunidade de giro nesse dia.")
            lines.append("")
            lines.append(_result_hint_text())
            return OutgoingMessage(text="\n".join(lines))

        current_manager = ""
        current_seller = ""
        for index, (manager_code, seller_code, setor_code, cod_pdv, client_name, total_caixas_cliente, gap_caixas_cliente, gap_detail) in enumerate(
            clients_with_opportunity,
            start=1,
        ):
            manager_code = str(manager_code or "")
            if manager_code != current_manager:
                if current_manager:
                    lines.append("")
                if manager_code:
                    lines.append(f"*{_format_gv_scope_label(manager_code)}*")
                else:
                    filial_code, _ = split_scope_pair(seller_code) or ("", "")
                    lines.append(f"*{_format_filial_label(filial_code)}*")
                current_manager = manager_code
                current_seller = ""
            if seller_code != current_seller:
                lines.append(f"*Setor {setor_code or '-'}*")
                current_seller = seller_code
            _append_giro_client_block(
                lines,
                index=index,
                client_name=client_name,
                cod_pdv=cod_pdv,
                total_caixas=total_caixas_cliente,
                gap_caixas=gap_caixas_cliente,
                gap_detail=gap_detail,
            )

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_giro_by_filial_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "giro", "by_filial", title)
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        summaries = self._safe_giro_summary_by_filial(decision)
        gv_summaries = self._safe_giro_summary_by_gv(decision)
        seller_summaries = self._safe_giro_summary_by_seller(decision)
        if not summaries:
            return OutgoingMessage(
                text=(
                    "Nao encontrei dados de giro por filial para esse escopo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        gv_by_filial = self._group_giro_management_summaries_by_filial(gv_summaries)
        seller_by_manager = self._group_giro_seller_summaries_by_manager(seller_summaries)
        lines = [title]
        for summary in sorted(summaries, key=lambda item: _sort_numeric_text(item.filial)):
            lines.append("")
            lines.append(f"*{_format_filial_label(summary.filial)}*")
            self._append_giro_summary_lines(lines, summary, compact=True, show_details=True)
            filial_gv_summaries = sorted(
                gv_by_filial.get(summary.filial, []),
                key=lambda item: _sort_scope_code(item.manager_code),
            )
            if filial_gv_summaries:
                lines.append("GVs do giro:")
                for gv_summary in filial_gv_summaries:
                    gv_seller_count = len(seller_by_manager.get(gv_summary.manager_code, []))
                    lines.append(
                        self._format_giro_total_scope_line(
                            gv_summary,
                            label=_format_gv_scope_label(gv_summary.manager_code),
                            child_count_label="Setores",
                            child_count=gv_seller_count,
                        )
                    )
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_giro_by_gv_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "giro", "by_gv", title)
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        summaries = self._safe_giro_summary_by_gv(decision)
        seller_summaries = self._safe_giro_summary_by_seller(decision)
        if not summaries:
            return OutgoingMessage(
                text=(
                    "Nao encontrei dados de giro por GV para esse escopo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        def _gv_sort_key(value: str) -> tuple[int, str]:
            pair = split_scope_pair(value) or ("", value)
            return _sort_numeric_text(pair[1] or pair[0] or value)

        seller_by_manager = self._group_giro_seller_summaries_by_manager(seller_summaries)
        lines = [title]
        for summary in sorted(summaries, key=lambda item: _gv_sort_key(item.manager_code)):
            lines.append("")
            lines.append(f"*{_format_gv_scope_label(summary.manager_code)}*")
            self._append_giro_summary_lines(lines, summary, compact=True, show_details=True)
            gv_seller_summaries = sorted(
                seller_by_manager.get(summary.manager_code, []),
                key=lambda item: _sort_scope_code(item.seller_code),
            )
            if gv_seller_summaries:
                lines.append("Setores do GV:")
                for seller_summary in gv_seller_summaries:
                    lines.append(
                        self._format_giro_total_scope_line(
                            seller_summary,
                            label=_format_sector_scope_label(seller_summary.seller_code),
                        )
                    )
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _safe_giro_scope_summary(
        self,
        decision: AccessDecision,
        gv_vdes_override: tuple[str, ...] | None = None,
    ) -> GiroScopeSummary | None:
        allowed_gv_vdes = gv_vdes_override if gv_vdes_override is not None else self._allowed_gv_vdes(decision)
        try:
            return self.giro_service.get_scope_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=list(allowed_gv_vdes) if allowed_gv_vdes is not None else None,
            )
        except RuntimeError:
            return None

    def _safe_giro_scope_summary_by_visit_day(
        self,
        decision: AccessDecision,
        *,
        visit_day: str,
    ) -> GiroScopeSummary | None:
        visit_day_token = _visit_day_token_from_label(visit_day) or visit_day
        try:
            return self.giro_service.get_scope_summary_by_visit_day(
                visit_day=visit_day_token,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except (RuntimeError, ValueError):
            return None

    def _safe_giro_scope_summary_for_seller(
        self,
        decision: AccessDecision,
        seller_code: str,
        manager_code: str,
    ) -> GiroScopeSummary | None:
        try:
            return self.giro_service.get_scope_summary_for_seller(
                seller_code=seller_code,
                manager_code=manager_code,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return None

    def _safe_giro_summary_by_filial(self, decision: AccessDecision) -> list[GiroFilialSummary]:
        try:
            return self.giro_service.list_summary_by_filial(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return []

    def _safe_giro_summary_by_gv(self, decision: AccessDecision) -> list[GiroManagementSummary]:
        try:
            return self.giro_service.list_summary_by_gv(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return []

    def _safe_giro_summary_by_seller(self, decision: AccessDecision) -> list[GiroSellerSummary]:
        try:
            return self.giro_service.list_summary_by_seller(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return []

    def _safe_giro_zero_base_records(self, decision: AccessDecision) -> list[GiroZeroBaseRecord] | None:
        try:
            return self.giro_service.list_giro_zero_base(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=2000,
            )
        except RuntimeError:
            return None

    def _safe_giro_history_by_registration(
        self,
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
    ) -> list[GiroClientRecord]:
        search_history = getattr(self.giro_service, "search_history_by_registration", None)
        if not callable(search_history):
            return []
        try:
            return search_history(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=1,
            )
        except (RuntimeError, ValueError):
            return []

    def _build_giro_historical_fallback_response(
        self,
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
        criteria: str,
    ) -> OutgoingMessage | None:
        historical_records = self._safe_giro_history_by_registration(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
        )
        if not historical_records:
            return None

        historical_response = self._build_giro_response(
            historical_records,
            criteria=f"{criteria} no historico",
            scope_restricted=False,
        )
        latest_date = historical_records[0].planilha_atualizada_em or "-"
        return OutgoingMessage(
            text=(
                "Esse cliente existe no cadastro, mas nao veio no lote ativo do giro de vasilhame.\n"
                f"Ultimo giro historico encontrado: {latest_date}.\n\n"
                f"{historical_response.text}"
            )
        )

    def _append_giro_summary_lines(
        self,
        lines: list[str],
        summary: GiroScopeSummary | None,
        *,
        compact: bool,
        show_details: bool = False,
    ) -> None:
        if summary is None:
            return

        total_monitored = (
            summary.litrinho_monitored_count
            + summary.inteira_monitored_count
            + summary.litrao_monitored_count
        )
        total_ok = (
            summary.litrinho_ok_count
            + summary.inteira_ok_count
            + summary.litrao_ok_count
        )
        if not show_details:
            lines.append(
                "Resumo OK: "
                f"Litrinho {_format_percent_ratio(summary.litrinho_ok_count, summary.litrinho_monitored_count)} | "
                f"Inteira {_format_percent_ratio(summary.inteira_ok_count, summary.inteira_monitored_count)} | "
                f"Litrao {_format_percent_ratio(summary.litrao_ok_count, summary.litrao_monitored_count)} | "
                f"Total {_format_percent_ratio(total_ok, total_monitored)}"
            )
            return

        total_zero = (
            summary.litrinho_zero_count
            + summary.inteira_zero_count
            + summary.litrao_zero_count
        )
        total_gap = _sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )
        lines.append(
            f"Litrinho: Total {_format_quantity(summary.litrinho_monitored_count)} | "
            f"Caixas OK {_format_quantity(summary.litrinho_ok_count)} | "
            f"% Giro OK {_format_percent_ratio(summary.litrinho_ok_count, summary.litrinho_monitored_count)} | "
            f"Gap {summary.litrinho_gap_total} | "
            f"Giro Zero {_format_quantity(summary.litrinho_zero_count)}"
        )
        lines.append(
            f"Inteira: Total {_format_quantity(summary.inteira_monitored_count)} | "
            f"Caixas OK {_format_quantity(summary.inteira_ok_count)} | "
            f"% Giro OK {_format_percent_ratio(summary.inteira_ok_count, summary.inteira_monitored_count)} | "
            f"Gap {summary.inteira_gap_total} | "
            f"Giro Zero {_format_quantity(summary.inteira_zero_count)}"
        )
        lines.append(
            f"Litrao: Total {_format_quantity(summary.litrao_monitored_count)} | "
            f"Caixas OK {_format_quantity(summary.litrao_ok_count)} | "
            f"% Giro OK {_format_percent_ratio(summary.litrao_ok_count, summary.litrao_monitored_count)} | "
            f"Gap {summary.litrao_gap_total} | "
            f"Giro Zero {_format_quantity(summary.litrao_zero_count)}"
        )
        lines.append(
            f"Total: Total {_format_quantity(total_monitored)} | "
            f"Caixas OK {_format_quantity(total_ok)} | "
            f"% Giro OK {_format_percent_ratio(total_ok, total_monitored)} | "
            f"Gap {total_gap} | "
            f"Giro Zero {_format_quantity(total_zero)}"
        )

    def _format_giro_total_scope_line(
        self,
        summary: GiroScopeSummary | None,
        *,
        label: str,
        child_count_label: str = "",
        child_count: int | None = None,
    ) -> str:
        if summary is None:
            return label

        total_monitored = (
            summary.litrinho_monitored_count
            + summary.inteira_monitored_count
            + summary.litrao_monitored_count
        )
        total_ok = (
            summary.litrinho_ok_count
            + summary.inteira_ok_count
            + summary.litrao_ok_count
        )
        total_zero = (
            summary.litrinho_zero_count
            + summary.inteira_zero_count
            + summary.litrao_zero_count
        )
        total_gap = _sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )

        segments = [label]
        if child_count_label and child_count is not None:
            segments.append(f"{child_count_label} {child_count}")
        segments.extend(
            [
                f"Total {_format_quantity(total_monitored)}",
                f"Caixas OK {_format_quantity(total_ok)}",
                f"% Giro OK {_format_percent_ratio(total_ok, total_monitored)}",
                f"Gap {total_gap}",
                f"Giro Zero {_format_quantity(total_zero)}",
            ]
        )
        return " | ".join(segments)

    def _format_scope_update_line(
        self,
        *,
        client_updated: str | None,
        inad_updated: str | None,
        giro_updated: str | None,
    ) -> str:
        return (
            "Atualizado: "
            f"Clientes {(client_updated or '-') or '-'} | "
            f"Inadimplencia {(inad_updated or '-') or '-'} | "
            f"Giro {(giro_updated or '-') or '-'}"
        )

    def _format_due_compact_line(
        self,
        *,
        today_count: int,
        today_total: str,
        tomorrow_count: int,
        tomorrow_total: str,
        two_days_count: int,
        two_days_total: str,
    ) -> str:
        return (
            "Vencimentos: "
            f"Hoje {today_count} (R$ {today_total}) | "
            f"Amanha {tomorrow_count} (R$ {tomorrow_total}) | "
            f"2 dias {two_days_count} (R$ {two_days_total})"
        )

    def _group_giro_management_summaries_by_filial(
        self,
        summaries: list[GiroManagementSummary],
    ) -> dict[str, list[GiroManagementSummary]]:
        grouped: dict[str, list[GiroManagementSummary]] = {}
        for summary in summaries:
            filial, _ = split_scope_pair(summary.manager_code) or ("", "")
            filial_code = normalize_stored_scope_value(filial)
            if not filial_code:
                continue
            grouped.setdefault(filial_code, []).append(summary)
        return grouped

    def _group_giro_seller_summaries_by_manager(
        self,
        summaries: list[GiroSellerSummary],
    ) -> dict[str, list[GiroSellerSummary]]:
        grouped: dict[str, list[GiroSellerSummary]] = {}
        for summary in summaries:
            manager_code = normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped.setdefault(manager_code, []).append(summary)
        return grouped

    def _build_finance_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "finance")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summary = self.query_service.get_scope_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            total_summary = self.inadimplencia_service.get_finance_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo financeiro agora.\n"
                    "Tente novamente em instantes."
                )
            )
        total_giro_summary = self._safe_giro_scope_summary(decision)
        lines = ["Resumo Financeiro | Base Total", ""]
        lines.append(f"*Clientes na base:* {client_summary.client_count}")
        lines.append(f"*Setores na base:* {client_summary.seller_count}")
        lines.append(f"*Clientes inadimplentes:* {total_summary.client_count}")
        lines.append(f"*Valor total pendente:* R$ {total_summary.total_pendente}")
        lines.append(f"*Ja vencidos:* {total_summary.overdue_count} cliente(s) | R$ {total_summary.overdue_total}")
        lines.append(f"*Vence hoje:* {total_summary.due_today_count} cliente(s) | R$ {total_summary.due_today_total}")
        lines.append(f"*Vence amanha:* {total_summary.due_tomorrow_count} cliente(s) | R$ {total_summary.due_tomorrow_total}")
        lines.append(f"*Vence em 2 dias:* {total_summary.due_in_two_days_count} cliente(s) | R$ {total_summary.due_in_two_days_total}")
        self._append_giro_summary_lines(lines, total_giro_summary, compact=False)
        lines.append("")
        lines.append(
            "Atualizado em:"
            f"\nClientes: {client_summary.planilha_atualizada_em or '-'}"
            f"\nInadimplencia: {total_summary.planilha_atualizada_em or '-'}"
            f"\nGiro: {(total_giro_summary.planilha_atualizada_em if total_giro_summary else '-') or '-'}"
        )

        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_finance_summary_by_filial_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "finance_by_filial")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summaries = self.query_service.list_scope_summary_by_filial(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summaries = self.inadimplencia_service.list_finance_summary_by_filial(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo por revenda agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summaries = self._safe_giro_summary_by_filial(decision)
        giro_gv_summaries = self._safe_giro_summary_by_gv(decision)
        giro_seller_summaries = self._safe_giro_summary_by_seller(decision)

        client_by_filial = {summary.filial: summary for summary in client_summaries}
        inad_by_filial = {summary.filial: summary for summary in inad_summaries}
        giro_by_filial = {summary.filial: summary for summary in giro_summaries}
        giro_gv_by_filial = self._group_giro_management_summaries_by_filial(giro_gv_summaries)
        giro_seller_by_manager = self._group_giro_seller_summaries_by_manager(giro_seller_summaries)
        filial_codes = sorted(set(client_by_filial) | set(inad_by_filial) | set(giro_by_filial), key=_sort_numeric_text)
        if not filial_codes:
            return OutgoingMessage(
                text=(
                    "Nao encontrei revendas disponiveis para esse resumo agora.\n"
                    f"{_result_hint_text()}"
                )
            )

        lines = ["Resumo Financeiro por Revenda"]
        for filial in filial_codes:
            client_summary = client_by_filial.get(filial)
            inad_summary = inad_by_filial.get(filial)
            giro_summary = giro_by_filial.get(filial)
            lines.append("")
            lines.append(f"*{_format_filial_label(filial)}*")
            lines.append(f"Clientes na base: {client_summary.client_count if client_summary else 0}")
            lines.append(
                f"GVs na base: {client_summary.manager_count if client_summary else 0} | "
                f"Setores na base: {client_summary.seller_count if client_summary else 0}"
            )
            lines.append(
                f"Clientes inadimplentes: {inad_summary.client_count if inad_summary else 0} | "
                f"R$ {inad_summary.total_pendente if inad_summary else '0,00'}"
            )
            lines.append(
                f"Ja vencidos: {inad_summary.overdue_count if inad_summary else 0} | "
                f"R$ {inad_summary.overdue_total if inad_summary else '0,00'}"
            )
            lines.append(
                f"Vence hoje: {inad_summary.due_today_count if inad_summary else 0} | "
                f"R$ {inad_summary.due_today_total if inad_summary else '0,00'}"
            )
            self._append_giro_summary_lines(lines, giro_summary, compact=True, show_details=True)
            filial_gv_summaries = sorted(
                giro_gv_by_filial.get(filial, []),
                key=lambda item: _sort_scope_code(item.manager_code),
            )
            if filial_gv_summaries:
                lines.append("GVs do giro:")
                for gv_summary in filial_gv_summaries:
                    gv_seller_count = len(giro_seller_by_manager.get(gv_summary.manager_code, []))
                    lines.append(
                        self._format_giro_total_scope_line(
                            gv_summary,
                            label=_format_gv_scope_label(gv_summary.manager_code),
                            child_count_label="Setores",
                            child_count=gv_seller_count,
                        )
                    )
            lines.append(
                "Atualizado: "
                f"Clientes {(client_summary.planilha_atualizada_em if client_summary else '-') or '-'} | "
                f"Inadimplencia {(getattr(inad_summary, 'planilha_atualizada_em', '-') if inad_summary else '-') or '-'} | "
                f"Giro {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}"
            )

        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_finance_documentacao_by_filial_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "finance_documentacao_by_filial")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            summaries = self.documentacao_pendente_service.list_summary_by_filial(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo de documentacao escaneada agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not summaries:
            return OutgoingMessage(
                text=(
                    "Nao encontrei clientes ativos para resumir a documentacao escaneada por revenda.\n"
                    f"{_result_hint_text()}"
                )
            )

        total_active = sum(summary.active_client_count for summary in summaries)
        total_scanned = sum(summary.scanned_client_count for summary in summaries)
        total_ok = sum(summary.ok_client_count for summary in summaries)
        total_pending = sum(summary.pending_client_count for summary in summaries)
        total_missing_scan = sum(summary.missing_scan_count for summary in summaries)

        lines = ["Documentacao Escaneada por Revenda", ""]
        lines.append(f"Clientes ativos: {total_active}")
        lines.append(
            f"Escaneados: {total_scanned} | OK: {total_ok} | "
            f"Pendentes: {total_pending} | Sem escanear: {total_missing_scan}"
        )
        lines.append(f"% OK da base ativa: {_format_percent_ratio(total_ok, total_active)}")

        for summary in summaries:
            lines.append("")
            lines.append(f"*{_format_filial_label(summary.filial)}*")
            lines.append(
                f"Ativos: {summary.active_client_count} | Escaneados: {summary.scanned_client_count}"
            )
            lines.append(
                f"OK: {summary.ok_client_count} | Pendentes: {summary.pending_client_count} | "
                f"Sem escanear: {summary.missing_scan_count}"
            )
            lines.append(f"% OK: {_format_percent_ratio(summary.ok_client_count, summary.active_client_count)}")
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")

        lines.append("")
        lines.append("Regra: cliente OK somente quando todos os documentos estao como OK.")
        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_finance_summary_by_gv_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "finance_by_gv")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summaries = self.query_service.list_scope_summary_by_gv(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summaries = self.inadimplencia_service.list_finance_summary_by_gv(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo por GV agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summaries = self._safe_giro_summary_by_gv(decision)
        giro_seller_summaries = self._safe_giro_summary_by_seller(decision)

        client_by_gv = {summary.manager_code: summary for summary in client_summaries}
        inad_by_gv = {summary.manager_code: summary for summary in inad_summaries}
        giro_by_gv = {summary.manager_code: summary for summary in giro_summaries}
        giro_seller_by_manager = self._group_giro_seller_summaries_by_manager(giro_seller_summaries)
        manager_codes = sorted(set(client_by_gv) | set(inad_by_gv) | set(giro_by_gv), key=_sort_scope_code)
        if not manager_codes:
            return OutgoingMessage(
                text=(
                    "Nao encontrei GVs disponiveis para esse resumo agora.\n"
                    f"{_result_hint_text()}"
                )
            )

        lines = ["Resumo Financeiro por GV"]
        for manager_code in manager_codes:
            client_summary = client_by_gv.get(manager_code)
            inad_summary = inad_by_gv.get(manager_code)
            giro_summary = giro_by_gv.get(manager_code)
            lines.append("")
            lines.append(f"*{_format_gv_scope_label(manager_code)}*")
            lines.append(f"Clientes na base: {client_summary.client_count if client_summary else 0}")
            lines.append(f"Setores na base: {client_summary.seller_count if client_summary else 0}")
            lines.append(
                f"Clientes inadimplentes: {inad_summary.client_count if inad_summary else 0} | "
                f"R$ {inad_summary.total_pendente if inad_summary else '0,00'}"
            )
            lines.append(
                f"Ja vencidos: {inad_summary.overdue_count if inad_summary else 0} | "
                f"R$ {inad_summary.overdue_total if inad_summary else '0,00'}"
            )
            lines.append(
                f"Vence hoje: {inad_summary.due_today_count if inad_summary else 0} | "
                f"R$ {inad_summary.due_today_total if inad_summary else '0,00'}"
            )
            self._append_giro_summary_lines(lines, giro_summary, compact=True, show_details=True)
            gv_seller_summaries = sorted(
                giro_seller_by_manager.get(manager_code, []),
                key=lambda item: _sort_scope_code(item.seller_code),
            )
            if gv_seller_summaries:
                lines.append("Setores do giro:")
                for seller_summary in gv_seller_summaries:
                    lines.append(
                        self._format_giro_total_scope_line(
                            seller_summary,
                            label=_format_sector_scope_label(seller_summary.seller_code),
                        )
                    )
            lines.append(
                "Atualizado: "
                f"Clientes {(client_summary.planilha_atualizada_em if client_summary else '-') or '-'} | "
                f"Inadimplencia {(getattr(inad_summary, 'planilha_atualizada_em', '-') if inad_summary else '-') or '-'} | "
                f"Giro {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}"
            )

        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_finance_summary_by_seller_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "finance_by_seller")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            seller_summaries = self.query_service.list_seller_base_summaries(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=250,
            )
            client_summary = self.query_service.get_scope_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summaries = self.inadimplencia_service.list_finance_summary_by_seller(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo por setor agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summaries = self._safe_giro_summary_by_seller(decision)

        seller_by_code = {summary.seller_code: summary for summary in seller_summaries}
        inad_by_seller = {summary.seller_code: summary for summary in inad_summaries}
        giro_by_seller = {summary.seller_code: summary for summary in giro_summaries}
        seller_codes = sorted(set(seller_by_code) | set(inad_by_seller) | set(giro_by_seller), key=_sort_scope_code)
        if not seller_codes:
            return OutgoingMessage(
                text=(
                    "Nao encontrei setores disponiveis para esse resumo agora.\n"
                    f"{_result_hint_text()}"
                )
            )

        lines = ["Resumo Financeiro por Setor"]
        current_manager = ""
        for seller_code in seller_codes:
            seller_summary = seller_by_code.get(seller_code)
            inad_summary = inad_by_seller.get(seller_code)
            giro_summary = giro_by_seller.get(seller_code)
            manager_code = ""
            if seller_summary is not None:
                manager_code = seller_summary.manager_code
            elif inad_summary is not None:
                manager_code = inad_summary.manager_code
            elif giro_summary is not None:
                manager_code = giro_summary.manager_code
            if manager_code != current_manager:
                lines.append("")
                lines.append(f"*{_format_gv_scope_label(manager_code) if manager_code else 'Sem GV'}*")
                current_manager = manager_code
            lines.append(f"{_format_sector_scope_label(seller_code)}")
            lines.append(f"Clientes na base: {seller_summary.visit_count if seller_summary else 0}")
            lines.append(
                f"Inadimplentes: {inad_summary.client_count if inad_summary else 0} | "
                f"R$ {inad_summary.total_pendente if inad_summary else '0,00'}"
            )
            lines.append(
                f"Ja vencidos: {inad_summary.overdue_count if inad_summary else 0} | "
                f"R$ {inad_summary.overdue_total if inad_summary else '0,00'}"
            )
            lines.append(
                f"Vence hoje: {inad_summary.due_today_count if inad_summary else 0} | "
                f"R$ {inad_summary.due_today_total if inad_summary else '0,00'}"
            )
            self._append_giro_summary_lines(lines, giro_summary, compact=True)
            lines.append("")

        lines.append(
            "Atualizado em:"
            f"\nClientes: {client_summary.planilha_atualizada_em or '-'}"
            f"\nInadimplencia: {next((item.planilha_atualizada_em for item in inad_summaries if item.planilha_atualizada_em), '-') or '-'}"
            f"\nGiro: {next((item.planilha_atualizada_em for item in giro_summaries if item.planilha_atualizada_em), '-') or '-'}"
        )
        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_gv_summary_response(
        self,
        decision: AccessDecision,
        gv_vdes_override: tuple[str, ...] | None = None,
        title: str | None = None,
    ) -> OutgoingMessage:
        selected_gv_vdes = tuple(gv_vdes_override or decision.gv_vdes)
        cache_key = self._decision_scope_cache_key(
            decision,
            "summary",
            "gv",
            selected_gv_vdes,
            title or "",
        )
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summary = self.query_service.get_scope_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=list(selected_gv_vdes),
            )
            inad_summary = self.inadimplencia_service.get_finance_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=list(selected_gv_vdes),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar esse resumo agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summary = self._safe_giro_scope_summary(decision, gv_vdes_override=selected_gv_vdes)

        scope_role = ROLE_DIRETOR_COMERCIAL if any(str(value).startswith("dc:") for value in selected_gv_vdes) else ROLE_GERENTE_VENDAS
        gv_label = _format_gv_vdes(selected_gv_vdes, role_name=scope_role)
        lines = [title or f"Resumo de {gv_label}"]
        if gv_label and (len(selected_gv_vdes) > 1 or scope_role == ROLE_DIRETOR_COMERCIAL):
            lines.append(f"*Base consultada:* {gv_label}")
        lines.append("")
        if scope_role == ROLE_DIRETOR_COMERCIAL:
            lines.append(f"Base: {client_summary.client_count} clientes | {client_summary.seller_count} setores")
            lines.append(
                f"Cobranca: {inad_summary.client_count} inadimplentes | "
                f"R$ {inad_summary.total_pendente} | Ja vencidos {inad_summary.overdue_count}"
            )
            lines.append(
                self._format_due_compact_line(
                    today_count=inad_summary.due_today_count,
                    today_total=inad_summary.due_today_total,
                    tomorrow_count=inad_summary.due_tomorrow_count,
                    tomorrow_total=inad_summary.due_tomorrow_total,
                    two_days_count=inad_summary.due_in_two_days_count,
                    two_days_total=inad_summary.due_in_two_days_total,
                )
            )
            self._append_giro_summary_lines(lines, giro_summary, compact=True)
            lines.append(
                self._format_scope_update_line(
                    client_updated=client_summary.planilha_atualizada_em,
                    inad_updated=inad_summary.planilha_atualizada_em,
                    giro_updated=giro_summary.planilha_atualizada_em if giro_summary else "-",
                )
            )
        else:
            lines.append(f"*Clientes na base:* {client_summary.client_count}")
            lines.append(f"*Setores na base:* {client_summary.seller_count}")
            lines.append(f"*Clientes inadimplentes:* {inad_summary.client_count}")
            lines.append(f"*Valor total pendente:* R$ {inad_summary.total_pendente}")
            lines.append(f"*Ja vencidos:* {inad_summary.overdue_count} cliente(s) | R$ {inad_summary.overdue_total}")
            lines.append(f"*Vence hoje:* {inad_summary.due_today_count} cliente(s) | R$ {inad_summary.due_today_total}")
            lines.append(f"*Vence amanha:* {inad_summary.due_tomorrow_count} cliente(s) | R$ {inad_summary.due_tomorrow_total}")
            lines.append(f"*Vence em 2 dias:* {inad_summary.due_in_two_days_count} cliente(s) | R$ {inad_summary.due_in_two_days_total}")
            self._append_giro_summary_lines(lines, giro_summary, compact=False)
            lines.append("")
            lines.append(
                "Atualizado em:"
                f"\nClientes: {client_summary.planilha_atualizada_em or '-'}"
                f"\nInadimplencia: {inad_summary.planilha_atualizada_em or '-'}"
                f"\nGiro: {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}"
            )
        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_director_total_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "director_total")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summaries = self.query_service.list_scope_summary_by_gv(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summaries = self.inadimplencia_service.list_finance_summary_by_gv(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo da diretoria agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not client_summaries and not inad_summaries:
            return OutgoingMessage(
                text=(
                    "Nao encontrei GVs disponiveis para esse resumo agora.\n"
                    f"{_result_hint_text()}"
                )
            )
        giro_summaries = self._safe_giro_summary_by_gv(decision)

        grouped_clients: dict[str, list[DClientesManagementSummary]] = {}
        for summary in client_summaries:
            manager_code = normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped_clients.setdefault(manager_code, []).append(summary)

        grouped_inad: dict[str, list[InadimplenciaFinanceManagementSummary]] = {}
        for summary in inad_summaries:
            manager_code = normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped_inad.setdefault(manager_code, []).append(summary)

        grouped_giro: dict[str, list[GiroManagementSummary]] = {}
        for summary in giro_summaries:
            manager_code = normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped_giro.setdefault(manager_code, []).append(summary)

        ordered_gvs = sorted(set(grouped_clients) | set(grouped_inad) | set(grouped_giro), key=_sort_scope_code)
        lines = ["Diretoria | Resumo Total"]
        lines.append(f"*GVs na base:* {len(ordered_gvs)}")

        for manager_code in ordered_gvs:
            client_group = grouped_clients.get(manager_code, [])
            inad_group = grouped_inad.get(manager_code, [])
            giro_summary = _aggregate_giro_scope_summaries(grouped_giro.get(manager_code, []))
            lines.append("")
            lines.append(f"*{_format_gv_scope_label(manager_code)}*")
            lines.append(
                f"Base: {sum(item.client_count for item in client_group)} clientes | "
                f"{sum(item.seller_count for item in client_group)} setores"
            )
            lines.append(
                f"Inadimplentes: {sum(item.client_count for item in inad_group)}"
                f" | R$ {_sum_money_values(item.total_pendente for item in inad_group)}"
                f" | Ja vencidos {sum(item.overdue_count for item in inad_group)}"
            )
            lines.append(
                self._format_due_compact_line(
                    today_count=sum(item.due_today_count for item in inad_group),
                    today_total=_sum_money_values(item.due_today_total for item in inad_group),
                    tomorrow_count=sum(item.due_tomorrow_count for item in inad_group),
                    tomorrow_total=_sum_money_values(item.due_tomorrow_total for item in inad_group),
                    two_days_count=sum(item.due_in_two_days_count for item in inad_group),
                    two_days_total=_sum_money_values(item.due_in_two_days_total for item in inad_group),
                )
            )
            self._append_giro_summary_lines(lines, giro_summary, compact=True)
            client_updated = next((item.planilha_atualizada_em for item in client_group if item.planilha_atualizada_em), "-")
            inad_updated = next((item.planilha_atualizada_em for item in inad_group if item.planilha_atualizada_em), "-")
            giro_updated = giro_summary.planilha_atualizada_em if giro_summary else "-"
            lines.append(
                self._format_scope_update_line(
                    client_updated=client_updated,
                    inad_updated=inad_updated,
                    giro_updated=giro_updated,
                )
            )

        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_director_manager_ranking_response(self, decision: AccessDecision) -> OutgoingMessage:
        try:
            client_summaries = self.query_service.list_scope_summary_by_gv(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summaries = self.inadimplencia_service.list_finance_summary_by_gv(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o ranking dos gerentes agora.\n"
                    "Tente novamente em instantes."
                )
            )

        risk_today_by_gv: dict[str, tuple[int, str]] = {}
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        if current_visit_day:
            visit_day_token = _visit_day_token_from_label(current_visit_day)
            if visit_day_token:
                try:
                    risk_summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                        visit_day_token=visit_day_token,
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                        limit=200,
                    )
                    grouped_risk: dict[str, list[InadimplenciaVisitRiskSummary]] = {}
                    for summary in risk_summaries:
                        grouped_risk.setdefault(summary.manager_code, []).append(summary)
                    for manager_code, summaries in grouped_risk.items():
                        risk_today_by_gv[manager_code] = (
                            sum(item.client_count for item in summaries),
                            _sum_money_values(item.total_pendente for item in summaries),
                        )
                except RuntimeError:
                    risk_today_by_gv = {}

        client_by_gv = {summary.manager_code: summary for summary in client_summaries}
        inad_by_gv = {summary.manager_code: summary for summary in inad_summaries}
        manager_codes = sorted(
            set(client_by_gv) | set(inad_by_gv) | set(risk_today_by_gv),
            key=lambda value: (
                _money_sort_key(inad_by_gv.get(value).total_pendente if inad_by_gv.get(value) else "0,00"),
                value,
            ),
            reverse=True,
        )
        if not manager_codes:
            return OutgoingMessage(
                text=(
                    "Nao encontrei gerentes disponiveis para esse ranking agora.\n"
                    f"{_result_hint_text()}"
                )
            )

        lines = ["Diretoria | Ranking dos GVs"]
        if current_visit_day:
            lines.append(f"*Risco de hoje considerado:* {current_visit_day}")
        lines.append("")
        for index, manager_code in enumerate(manager_codes, start=1):
            client_summary = client_by_gv.get(manager_code)
            inad_summary = inad_by_gv.get(manager_code)
            risk_today = risk_today_by_gv.get(manager_code, (0, "0,00"))
            lines.append(
                f"{index}. {_format_gv_scope_label(manager_code)} | "
                f"R$ {inad_summary.total_pendente if inad_summary else '0,00'}"
            )
            lines.append(
                f"Base {client_summary.client_count if client_summary else 0} clientes | "
                f"{client_summary.seller_count if client_summary else 0} setores | "
                f"Inadimplentes {inad_summary.client_count if inad_summary else 0} | "
                f"Risco hoje {risk_today[0]} cliente(s) | R$ {risk_today[1]}"
            )
            lines.append("")

        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_director_filial_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "director_filial")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summaries = self.query_service.list_scope_summary_by_filial(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summaries = self.inadimplencia_service.list_finance_summary_by_filial(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo por filial agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summaries = self._safe_giro_summary_by_filial(decision)

        risk_today_by_filial: dict[str, tuple[int, str]] = {}
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        if current_visit_day:
            visit_day_token = _visit_day_token_from_label(current_visit_day)
            if visit_day_token:
                try:
                    risk_summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                        visit_day_token=visit_day_token,
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                        limit=250,
                    )
                    grouped_risk: dict[str, list[InadimplenciaVisitRiskSummary]] = {}
                    for summary in risk_summaries:
                        filial, _ = split_scope_pair(summary.seller_code) or ("", "")
                        if not filial:
                            continue
                        grouped_risk.setdefault(filial, []).append(summary)
                    for filial, summaries in grouped_risk.items():
                        risk_today_by_filial[filial] = (
                            sum(item.client_count for item in summaries),
                            _sum_money_values(item.total_pendente for item in summaries),
                        )
                except RuntimeError:
                    risk_today_by_filial = {}

        client_by_filial = {summary.filial: summary for summary in client_summaries}
        inad_by_filial = {summary.filial: summary for summary in inad_summaries}
        giro_by_filial = {summary.filial: summary for summary in giro_summaries}
        filial_codes = sorted(
            set(client_by_filial) | set(inad_by_filial) | set(risk_today_by_filial) | set(giro_by_filial),
            key=_sort_numeric_text,
        )
        if not filial_codes:
            return OutgoingMessage(
                text=(
                    "Nao encontrei filiais disponiveis para esse resumo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        lines = ["Diretoria | Filiais"]
        if current_visit_day:
            lines.append(f"*Risco de hoje considerado:* {current_visit_day}")
        for filial in filial_codes:
            client_summary = client_by_filial.get(filial)
            inad_summary = inad_by_filial.get(filial)
            giro_summary = giro_by_filial.get(filial)
            risk_today = risk_today_by_filial.get(filial, (0, "0,00"))
            lines.append("")
            lines.append(f"*{_format_filial_label(filial)}*")
            lines.append(
                f"Base: {client_summary.client_count if client_summary else 0} clientes | "
                f"{client_summary.manager_count if client_summary else 0} GVs | "
                f"{client_summary.seller_count if client_summary else 0} setores"
            )
            lines.append(
                f"Inadimplentes: {inad_summary.client_count if inad_summary else 0} | "
                f"R$ {inad_summary.total_pendente if inad_summary else '0,00'}"
            )
            lines.append(
                self._format_due_compact_line(
                    today_count=inad_summary.due_today_count if inad_summary else 0,
                    today_total=inad_summary.due_today_total if inad_summary else "0,00",
                    tomorrow_count=inad_summary.due_tomorrow_count if inad_summary else 0,
                    tomorrow_total=inad_summary.due_tomorrow_total if inad_summary else "0,00",
                    two_days_count=inad_summary.due_in_two_days_count if inad_summary else 0,
                    two_days_total=inad_summary.due_in_two_days_total if inad_summary else "0,00",
                )
            )
            lines.append(f"Risco de hoje: {risk_today[0]} cliente(s) | R$ {risk_today[1]}")
            self._append_giro_summary_lines(lines, giro_summary, compact=True)
            lines.append(
                self._format_scope_update_line(
                    client_updated=client_summary.planilha_atualizada_em if client_summary else "-",
                    inad_updated=getattr(inad_summary, "planilha_atualizada_em", "-") if inad_summary else "-",
                    giro_updated=giro_summary.planilha_atualizada_em if giro_summary else "-",
                )
            )

        lines.append("")
        lines.append(_result_hint_text())
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_seller_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(decision, "summary", "seller")
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summary = self.query_service.get_scope_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summary = self.inadimplencia_service.get_finance_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo da sua carteira agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summary = self._safe_giro_scope_summary(decision)

        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        current_visit_label = (
            _format_visit_day_label(current_visit_day)
            if current_visit_day
            else _current_visit_day_label().title()
        )
        visit_count = 0
        risk_alerts: list[InadimplenciaVisitAlert] = []
        risk_note = ""
        if current_visit_day:
            try:
                visit_clients = self.query_service.list_clients_by_visit_day(
                    visit_day=current_visit_day,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=200,
                )
                risk_alerts = self.inadimplencia_service.list_upcoming_by_visit_day(
                    visit_day=current_visit_day,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=200,
                )
                visit_count = len(visit_clients)
            except RuntimeError:
                risk_note = "Nao consegui consultar o risco da rota agora."
        else:
            risk_note = "Nao encontrei visitas programadas para hoje na sua carteira."

        risk_today_alerts = [alert for alert in risk_alerts if alert.nearest_days_to_due <= 0]
        lines = ["Carteira de Hoje", ""]
        lines.append(f"Base: {client_summary.client_count} clientes | {client_summary.seller_count} setor(es)")
        lines.append(f"Cobranca da carteira: {inad_summary.client_count} inadimplentes | R$ {inad_summary.total_pendente}")
        lines.append(f"Ja vencidos: {inad_summary.overdue_count} cliente(s) | R$ {inad_summary.overdue_total}")
        lines.append(f"Vence hoje: {inad_summary.due_today_count} cliente(s) | R$ {inad_summary.due_today_total}")
        lines.append(f"Vence amanha: {inad_summary.due_tomorrow_count} cliente(s) | R$ {inad_summary.due_tomorrow_total}")
        lines.append(f"Vence em 2 dias: {inad_summary.due_in_two_days_count} cliente(s) | R$ {inad_summary.due_in_two_days_total}")
        self._append_giro_summary_lines(lines, giro_summary, compact=False)
        lines.append("")
        lines.append(f"*Rota de hoje ({current_visit_label}):* {visit_count} visita(s)")
        if risk_note:
            lines.append(risk_note)
        else:
            lines.append(
                f"Risco da rota: {len(risk_today_alerts)} cliente(s) | "
                f"R$ {_sum_money_values(alert.total_pendente for alert in risk_today_alerts)}"
            )
        lines.append("")
        lines.append(
            "Atualizado em:"
            f"\nClientes: {client_summary.planilha_atualizada_em or '-'}"
            f"\nInadimplencia: {inad_summary.planilha_atualizada_em or '-'}"
            f"\nGiro: {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}"
        )
        lines.append("")
        lines.append("Se quiser continuar, envie MENU.")
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _build_seller_risk_response(self, decision: AccessDecision) -> OutgoingMessage:
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        current_visit_label = (
            _format_visit_day_label(current_visit_day)
            if current_visit_day
            else _current_visit_day_label().title()
        )
        if not current_visit_day:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei visitas programadas para hoje ({current_visit_label}) na sua carteira.\n"
                    f"{_result_hint_text()}"
                )
            )
        return self._build_seller_visit_day_risk_response(
            decision=decision,
            visit_day=current_visit_day,
            visit_day_label=current_visit_label,
            current_day_only=True,
        )

    def _build_seller_visit_day_risk_response(
        self,
        *,
        decision: AccessDecision,
        visit_day: str,
        visit_day_label: str,
        current_day_only: bool = False,
    ) -> OutgoingMessage:
        try:
            visit_clients = self.query_service.list_clients_by_visit_day(
                visit_day=visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=200,
            )
            alerts = self.inadimplencia_service.list_upcoming_by_visit_day(
                visit_day=visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=200,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui consultar o risco da sua rota agora.\n"
                    "Tente novamente em instantes."
                )
            )

        relevant_alerts = [alert for alert in alerts if alert.nearest_days_to_due <= 0] if current_day_only else list(alerts)
        title = f"Risco da Rota em {visit_day_label}"
        summary_label = "Clientes com risco"
        empty_text = (
            "Nao encontrei clientes da sua rota vencendo hoje ou ja inadimplentes."
            if current_day_only
            else f"Nao encontrei clientes da sua rota com vencimento proximo ou inadimplencia em '{visit_day_label}'."
        )
        lines = [
            title,
            f"Visitas na rota: {len(visit_clients)}",
            f"{summary_label}: {len(relevant_alerts)} | R$ {_sum_money_values(alert.total_pendente for alert in relevant_alerts)}",
            f"Planilha atualizada em: {(alerts[0].planilha_atualizada_em if alerts else '-') or '-'}",
        ]
        if not relevant_alerts:
            lines.append("")
            lines.append(empty_text)
            return OutgoingMessage(text="\n".join(lines))

        overdue = [alert for alert in relevant_alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in relevant_alerts if alert.nearest_days_to_due == 0]
        due_tomorrow = [alert for alert in relevant_alerts if alert.nearest_days_to_due == 1]
        due_in_two_days = [alert for alert in relevant_alerts if alert.nearest_days_to_due == 2]
        lines.append("")
        self._append_visit_financial_group(lines, "Ja inadimplentes", overdue)
        self._append_visit_financial_group(lines, "Vence hoje", due_today)
        if not current_day_only:
            self._append_visit_financial_group(lines, "Vence amanha", due_tomorrow)
            self._append_visit_financial_group(lines, "Vence em 2 dias", due_in_two_days)
        return OutgoingMessage(text="\n".join(lines))

    def _resolve_current_scope_visit_day_label(self, decision: AccessDecision) -> str:
        try:
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
            visit_days = _normalize_visit_day_menu_values(raw_visit_days)
        except RuntimeError:
            return ""

        current_token = _current_visit_day_token()
        for visit_day in visit_days:
            if _visit_day_token_from_label(visit_day) == current_token:
                return visit_day
        return ""

    def _open_finance_gv_summary_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        try:
            gv_options = self.query_service.list_gv_vdes(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir a lista de GVs agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not gv_options:
            return OutgoingMessage(
                text=(
                    "Nao encontrei GVs disponiveis para esse resumo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        if len(gv_options) == 1:
            selected_gv = gv_options[0]
            self._remember_last_context(
                session,
                intent="finance_gv_summary",
                search_context="inadimplencia",
                query_text=selected_gv,
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_gv_summary_response(
                    decision=decision,
                    gv_vdes_override=(selected_gv,),
                    title=f"Resumo do GV {_format_gv_scope_label(selected_gv)}",
                ),
                return_menu="finance_menu",
            )

        session.step = "finance_select_gv_summary"
        session.finance_gv_options = tuple(gv_options)
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_gv_summary_menu(gv_options=gv_options)

    def _open_director_summary_menu(
        self,
        sender: str,
        session: LookupSession,
    ) -> OutgoingMessage:
        self._clear_clarification_state(session)
        self._remember_last_context(session, intent="director_summary", search_context="inadimplencia")
        session.step = "awaiting_director_summary_mode"
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_director_summary_menu()

    def _open_director_visit_risk_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        visit_days = [label for _, label in VISIT_DAY_CHOICES]

        session.step = "director_select_visit_risk_day"
        session.visit_risk_day_options = tuple(visit_days)
        session.visit_risk_summaries = ()
        session.finance_gv_options = ()
        session.selected_visit_risk_gv = ""
        session.selected_visit_risk_token = ""
        session.selected_visit_risk_label = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_director_visit_risk_day_menu(visit_days=visit_days)

    def _build_director_visit_risk_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = "Escolha o dia da semana para ver o risco da rota da diretoria."
        if invalid_selection:
            header = _invalid_option_text("Escolha o dia da semana para ver o risco da rota da diretoria.")
        return OutgoingMessage(
            kind="menu",
            title="Diretoria | Risco da Rota",
            text=header,
            footer="Depois eu mostro os GVs com risco, os setores e, em seguida, os clientes. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{VISIT_DAY_PICK_PREFIX}{index}",
                    title=visit_day,
                    description="Ver GVs, setores e clientes com risco",
                    shortcut=str(index),
                )
                for index, visit_day in enumerate(visit_days, start=1)
            ),
        )

    def _open_manager_summary_menu(
        self,
        sender: str,
        session: LookupSession,
    ) -> OutgoingMessage:
        self._clear_clarification_state(session)
        self._remember_last_context(session, intent="manager_summary", search_context="inadimplencia")
        session.step = "awaiting_manager_summary_mode"
        session.summary_filial_options = ()
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_manager_summary_menu()

    def _build_manager_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "O que voce quer acompanhar na sua gerencia?"
        if invalid_selection:
            text = _invalid_option_text("O que voce quer acompanhar na sua gerencia?")
        return OutgoingMessage(
            kind="menu",
            title="Gerencia",
            text=text,
            footer=(
                "Nesse painel ficam as visoes consolidadas da gerencia. "
                "Para acao direta, use no menu principal: cobranca da gerencia e giro da gerencia. "
                "Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=MANAGER_ACTION_VISIT_RISK,
                    title="Risco da Rota",
                    description="Ver setores da rota com risco financeiro",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_UPCOMING,
                    title="Vencimentos",
                    description="Ver quem vence em 2, 1 e 0 dias",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_LIST,
                    title="Cobranca Consolidada",
                    description="Listar os clientes inadimplentes do GV",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_BY_SELLER,
                    title="Equipe",
                    description="Escolher um setor da equipe para ver o resumo",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=MANAGER_SUMMARY_BY_FILIAL,
                    title="Filiais",
                    description="Escolher a revenda para detalhar",
                    shortcut="5",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_GIRO,
                    title="Giro Consolidado",
                    description="Abrir o resumo de giro consolidado do GV",
                    shortcut="6",
                ),
                InteractiveOption(
                    option_id=MANAGER_SUMMARY_TOTAL,
                    title="Resumo Total",
                    description="Ver toda a base do seu GV",
                    shortcut="7",
                ),
            ),
        )

    def _build_finance_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "Como voce quer acompanhar o resumo financeiro?"
        if invalid_selection:
            text = _invalid_option_text("Como voce quer acompanhar o resumo financeiro?")
        return OutgoingMessage(
            kind="menu",
            title="Resumo Financeiro",
            text=text,
            footer="Voce pode ver o total, por revenda, por GV, por setor ou a documentacao escaneada por revenda. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=FINANCE_SUMMARY_TOTAL,
                    title="Resumo Total",
                    description="Ver o consolidado geral da base",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=FINANCE_SUMMARY_BY_FILIAL,
                    title="Por Revenda",
                    description="Organizar o financeiro por filial",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=FINANCE_SUMMARY_BY_GV,
                    title="Por GV",
                    description="Organizar o financeiro por chave filial-GV",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=FINANCE_SUMMARY_BY_SELLER,
                    title="Por Setor",
                    description="Organizar o financeiro por chave filial-setor",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=FINANCE_SUMMARY_DOCUMENTACAO_BY_FILIAL,
                    title="Doc Escaneada",
                    description="Resumo documental por revenda com clientes ativos",
                    shortcut="5",
                ),
            ),
        )

    def _open_manager_filial_summary_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        filial_options = _extract_filial_options_from_scope_codes(decision.gv_vdes)
        if not filial_options:
            return OutgoingMessage(
                text=(
                    "Nao encontrei filiais disponiveis para esse resumo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        if len(filial_options) == 1:
            selected_filial = filial_options[0]
            selected_scope_keys = _filter_scope_codes_by_filial(decision.gv_vdes, selected_filial)
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_gv_summary_response(
                    decision=decision,
                    gv_vdes_override=selected_scope_keys,
                    title=f"Resumo da Gerencia | {_format_filial_label(selected_filial)}",
                ),
                return_menu="manager_summary",
            )

        session.step = "awaiting_manager_filial_selection"
        session.summary_filial_options = tuple(filial_options)
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_manager_filial_summary_menu(filial_options=filial_options)

    def _build_manager_filial_summary_menu(
        self,
        filial_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        text = "Escolha a filial que voce quer resumir."
        if invalid_selection:
            text = _invalid_option_text("Escolha a filial que voce quer resumir.")
        return OutgoingMessage(
            kind="menu",
            title="Resumo por Filial",
            text=text,
            footer="Depois eu mostro o resumo da sua gerencia nessa revenda. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"manager:filial:{index}",
                    title=_format_filial_label(filial),
                    description="Ver resumo dessa filial",
                    shortcut=str(index),
                )
                for index, filial in enumerate(filial_options, start=1)
            ),
        )

    def _open_manager_seller_summary_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        try:
            seller_summaries = self.query_service.list_seller_base_summaries(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=120,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir a lista dos vendedores agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not seller_summaries:
            return OutgoingMessage(
                text=(
                    "Nao encontrei vendedores disponiveis para esse resumo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        if len(seller_summaries) == 1:
            summary = seller_summaries[0]
            self._remember_last_context(
                session,
                intent="manager_seller_summary",
                search_context="inadimplencia",
                query_text=summary.seller_code,
            )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_manager_seller_summary_response(
                    decision=decision,
                    summary=summary,
                ),
                return_menu="manager_summary",
            )

        session.step = "awaiting_manager_seller_summary_selection"
        session.visit_seller_summaries = tuple(seller_summaries)
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_manager_seller_summary_menu(seller_summaries)

    def _build_manager_seller_summary_menu(
        self,
        seller_summaries: list[VisitSellerSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        text = "Escolha o vendedor que voce quer resumir."
        if invalid_selection:
            text = _invalid_option_text("Escolha o vendedor que voce quer resumir.")
        return OutgoingMessage(
            kind="menu",
            title="Resumo por Vendedor",
            text=text,
            footer="Cada linha mostra o setor, o GV e a quantidade de clientes na base. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"manager:seller:{index}",
                    title=_format_sector_scope_label(summary.seller_code),
                    description=f"{_format_gv_scope_label(summary.manager_code)} | {summary.visit_count} cliente(s) na base",
                    shortcut=str(index),
                )
                for index, summary in enumerate(seller_summaries, start=1)
            ),
        )

    def _build_manager_seller_summary_response(
        self,
        decision: AccessDecision,
        summary: VisitSellerSummary,
    ) -> OutgoingMessage:
        cache_key = self._decision_scope_cache_key(
            decision,
            "summary",
            "manager_seller",
            summary.seller_code,
            summary.manager_code,
        )
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summary = self.query_service.get_scope_summary_for_seller(
                seller_code=summary.seller_code,
                manager_code=summary.manager_code,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            inad_summary = self.inadimplencia_service.get_finance_summary_for_seller(
                seller_code=summary.seller_code,
                manager_code=summary.manager_code,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar esse resumo do vendedor agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summary = self._safe_giro_scope_summary_for_seller(
            decision,
            seller_code=summary.seller_code,
            manager_code=summary.manager_code,
        )

        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        visit_count = 0
        risk_today_alerts: list[InadimplenciaVisitAlert] = []
        if current_visit_day:
            try:
                visit_records = self.query_service.list_clients_by_visit_day_and_seller(
                    visit_day=current_visit_day,
                    seller_code=summary.seller_code,
                    manager_code=summary.manager_code,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=200,
                )
                risk_today_alerts = self.inadimplencia_service.list_visit_day_risk_alerts_by_seller(
                    visit_day_token=_visit_day_token_from_label(current_visit_day),
                    seller_code=summary.seller_code,
                    manager_code=summary.manager_code,
                    visit_day_values=[current_visit_day],
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=200,
                )
                visit_count = len(visit_records)
            except RuntimeError:
                pass

        lines = [f"Resumo do vendedor {_format_sector_scope_label(summary.seller_code)}", ""]
        lines.append(f"*Gerencia:* {_format_gv_scope_label(summary.manager_code)}")
        lines.append(f"*Clientes na base:* {client_summary.client_count}")
        lines.append(f"*Clientes inadimplentes:* {inad_summary.client_count}")
        lines.append(f"*Valor total pendente:* R$ {inad_summary.total_pendente}")
        lines.append(f"*Ja vencidos:* {inad_summary.overdue_count} cliente(s) | R$ {inad_summary.overdue_total}")
        lines.append(f"*Vence hoje:* {inad_summary.due_today_count} cliente(s) | R$ {inad_summary.due_today_total}")
        lines.append(f"*Vence amanha:* {inad_summary.due_tomorrow_count} cliente(s) | R$ {inad_summary.due_tomorrow_total}")
        lines.append(f"*Vence em 2 dias:* {inad_summary.due_in_two_days_count} cliente(s) | R$ {inad_summary.due_in_two_days_total}")
        self._append_giro_summary_lines(lines, giro_summary, compact=False)
        lines.append("")
        lines.append(f"*Visitas de hoje:* {visit_count}")
        lines.append(
            f"*Clientes com risco hoje:* {len([alert for alert in risk_today_alerts if alert.nearest_days_to_due <= 0])}"
            f" | R$ {_sum_money_values(alert.total_pendente for alert in risk_today_alerts if alert.nearest_days_to_due <= 0)}"
        )
        lines.append("")
        lines.append(
            "Atualizado em:"
            f"\nClientes: {client_summary.planilha_atualizada_em or '-'}"
            f"\nInadimplencia: {inad_summary.planilha_atualizada_em or '-'}"
            f"\nGiro: {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}"
        )
        lines.append("")
        lines.append("Se quiser continuar, envie MENU.")
        return self._store_cached_response(cache_key, OutgoingMessage(text="\n".join(lines)))

    def _open_manager_visit_risk_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        try:
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
            visit_days = _normalize_visit_day_menu_values(raw_visit_days)
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir os dias de visita agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not visit_days:
            return OutgoingMessage(
                text=(
                    "Nao encontrei visitas disponiveis para esse risco agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        session.step = "manager_select_visit_risk_day"
        session.visit_risk_day_options = tuple(visit_days)
        session.visit_risk_summaries = ()
        session.finance_gv_options = ()
        session.selected_visit_risk_gv = ""
        session.selected_visit_risk_token = ""
        session.selected_visit_risk_label = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_day_menu(
            visit_days=visit_days,
            menu_title="Risco da Rota",
            header_prompt="Escolha o dia da semana para ver o risco da rota da gerencia.",
        )

    def _open_manager_visit_risk_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        visit_day_token: str,
        visit_day_label: str,
    ) -> OutgoingMessage:
        try:
            summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                visit_day_token=visit_day_token,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=120,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui consultar as visitas com risco agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not summaries:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei setores com risco em '{visit_day_label}'.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        gv_options = sorted(
            {
                normalize_stored_scope_value(summary.manager_code)
                for summary in summaries
                if normalize_stored_scope_value(summary.manager_code)
            },
            key=_sort_scope_code,
        )
        if len(gv_options) > 1:
            session.step = "manager_select_visit_risk_gv"
            session.visit_risk_day_options = ()
            session.finance_gv_options = tuple(gv_options)
            session.visit_risk_summaries = tuple(summaries)
            session.selected_visit_risk_gv = ""
            session.selected_visit_risk_token = visit_day_token
            session.selected_visit_risk_label = visit_day_label
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_gv_menu(
                visit_day_label=visit_day_label,
                gv_options=gv_options,
                summaries=summaries,
                menu_title="Risco da Rota",
                day_header_prefix="Risco da rota",
            )

        session.step = "manager_select_visit_risk_sector"
        session.visit_risk_day_options = ()
        session.visit_risk_summaries = tuple(summaries)
        session.finance_gv_options = tuple(gv_options)
        session.selected_visit_risk_gv = gv_options[0] if gv_options else ""
        session.selected_visit_risk_token = visit_day_token
        session.selected_visit_risk_label = visit_day_label
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_menu(
            visit_day_label=visit_day_label,
            summaries=summaries,
            menu_title="Risco da Rota",
            day_header_prefix="Risco da rota",
        )

    def _build_director_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "Escolha a visao da diretoria que voce quer abrir agora."
        if invalid_selection:
            text = _invalid_option_text("Escolha uma opcao da diretoria.")
        return OutgoingMessage(
            kind="menu",
            title="Diretoria",
            text=text,
            footer="Use esse menu como rotina da diretoria: risco da rota, cobranca, GVs, filiais, giro, ranking e resumo total. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_VISIT_RISK,
                    title="Risco da Rota",
                    description="Ver risco financeiro por GV, setor e clientes",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_TOP_DEBTORS,
                    title="Cobranca",
                    description="Listar os maiores devedores da diretoria",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_SUMMARY_BY_REVENDA,
                    title="GVs",
                    description="Abrir um GV da diretoria",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_BY_FILIAL,
                    title="Filiais",
                    description="Consolidar a diretoria por revenda",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_GIRO,
                    title="Giro",
                    description="Abrir o submenu de giro da diretoria",
                    shortcut="5",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_RANKING,
                    title="Ranking dos GVs",
                    description="Ordenar os GVs pelo maior valor pendente",
                    shortcut="6",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_SUMMARY_TOTAL,
                    title="Resumo Total",
                    description="Ver a base completa da diretoria",
                    shortcut="7",
                ),
            ),
        )

    def _build_finance_gv_summary_menu(
        self,
        gv_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        text = "Escolha a chave filial-GV que voce quer resumir."
        if invalid_selection:
            text = _invalid_option_text("Escolha a chave filial-GV que voce quer resumir.")
        return OutgoingMessage(
            kind="menu",
            title="Resumo por GV",
            text=text,
            footer="Depois eu mostro o resumo comercial e de inadimplencia desse GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"finance:gv_summary:{index}",
                    title=_format_gv_scope_label(gv_code),
                    description="Ver resumo desse GV",
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _open_director_gv_summary_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        try:
            gv_options = self.query_service.list_gv_vdes(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir a lista dos gerentes agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not gv_options:
            return OutgoingMessage(
                text=(
                    "Nao encontrei gerentes de vendas disponiveis para esse resumo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        if len(gv_options) == 1:
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_gv_summary_response(
                    decision=decision,
                    gv_vdes_override=(gv_options[0],),
                    title=f"Resumo do GV {_format_gv_scope_label(gv_options[0])}",
                ),
                return_menu="director_summary",
            )

        session.step = "awaiting_gv_summary_selection"
        session.finance_gv_options = tuple(gv_options)
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_director_gv_summary_menu(gv_options=gv_options)

    def _open_director_visit_risk_gv_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        *,
        visit_day_token: str,
        visit_day_label: str,
    ) -> OutgoingMessage:
        try:
            summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                visit_day_token=visit_day_token,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=250,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui consultar as visitas com risco agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not summaries:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei GVs com risco em '{visit_day_label}'.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        gv_options = sorted(
            {
                normalize_stored_scope_value(summary.manager_code)
                for summary in summaries
                if normalize_stored_scope_value(summary.manager_code)
            },
            key=_sort_numeric_text,
        )
        if not gv_options:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei GVs com risco em '{visit_day_label}'.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        session.step = "director_select_visit_risk_gv"
        session.finance_gv_options = tuple(gv_options)
        session.visit_risk_summaries = tuple(summaries)
        session.selected_visit_risk_gv = ""
        session.selected_visit_risk_token = visit_day_token
        session.selected_visit_risk_label = visit_day_label
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_director_visit_risk_gv_menu(
            visit_day_label=visit_day_label,
            gv_options=gv_options,
            seller_summaries=summaries,
        )

    def _build_director_visit_risk_gv_menu(
        self,
        visit_day_label: str,
        gv_options: list[str],
        seller_summaries: list[InadimplenciaVisitRiskSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        grouped: dict[str, list[InadimplenciaVisitRiskSummary]] = {}
        for summary in seller_summaries:
            manager_code = normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped.setdefault(manager_code, []).append(summary)

        total_clients = sum(summary.client_count for summary in seller_summaries)
        total_pendente = _sum_money_values(summary.total_pendente for summary in seller_summaries)
        total_sectors = len(seller_summaries)
        lines = [f"Diretoria | Risco da Rota em {visit_day_label}"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(
            f"GVs com risco: {len(gv_options)} | Setores com risco: {total_sectors} | "
            f"Clientes com risco: {total_clients} | R$ {total_pendente}"
        )
        lines.append(f"Atualizado: {seller_summaries[0].planilha_atualizada_em or '-'}")
        lines.append("Escolha o GV para ver os setores com risco.")
        return OutgoingMessage(
            kind="menu",
            title="Diretoria | Risco da Rota",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro setores, clientes e valor por GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"director:visit_risk:gv:{index}",
                    title=_format_gv_scope_label(gv_code),
                    description=(
                        f"{len(grouped.get(gv_code, []))} setor(es) | "
                        f"{sum(item.client_count for item in grouped.get(gv_code, []))} cliente(s) | "
                        f"R$ {_sum_money_values(item.total_pendente for item in grouped.get(gv_code, []))}"
                    ),
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_director_visit_risk_sector_menu(
        self,
        visit_day_label: str,
        summaries: list[InadimplenciaVisitRiskSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        total_clients = sum(summary.client_count for summary in summaries)
        total_pendente = _sum_money_values(summary.total_pendente for summary in summaries)
        gv_label = _format_gv_scope_label(summaries[0].manager_code) if summaries else "-"
        lines = [f"Diretoria | Risco da Rota em {visit_day_label}"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(f"{gv_label}")
        lines.append(
            f"Setores com risco: {len(summaries)} | Clientes com risco: {total_clients} | "
            f"R$ {total_pendente}"
        )
        lines.append(f"Atualizado: {(summaries[0].planilha_atualizada_em if summaries else '-') or '-'}")
        lines.append("Escolha o setor para ver os clientes com risco.")
        return OutgoingMessage(
            kind="menu",
            title="Diretoria | Risco da Rota",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro clientes e valor do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{FINANCE_VISIT_RISK_PICK_PREFIX}{summary.seller_code}:{summary.manager_code}",
                    title=_format_sector_scope_label(summary.seller_code),
                    description=f"{summary.client_count} cliente(s) | R$ {summary.total_pendente}",
                    shortcut=str(index),
                )
                for index, summary in enumerate(summaries, start=1)
            ),
        )

    def _build_director_visit_risk_sector_response(
        self,
        decision: AccessDecision,
        summary: InadimplenciaVisitRiskSummary,
        visit_day_token: str,
        visit_day_label: str,
    ) -> OutgoingMessage:
        try:
            alerts = self.inadimplencia_service.list_visit_day_risk_alerts_by_seller(
                visit_day_token=visit_day_token,
                seller_code=summary.seller_code,
                manager_code=summary.manager_code,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=120,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir os clientes desse setor agora.\n"
                    "Tente novamente em instantes."
                )
            )

        lines = [
            f"Diretoria | Risco da Rota em {visit_day_label}",
            f"{_format_gv_scope_label(summary.manager_code)} | Setor {str(summary.seller_code).split('_')[-1]}",
            f"Clientes com risco: {summary.client_count} | R$ {summary.total_pendente}",
            f"Atualizado: {(alerts[0].planilha_atualizada_em if alerts else summary.planilha_atualizada_em) or '-'}",
        ]
        if not alerts:
            lines.append("Nao encontrei clientes com risco para esse setor agora.")
            lines.append("")
            lines.append(_result_hint_text(allow_back=True))
            return OutgoingMessage(text="\n".join(lines))

        overdue = [alert for alert in alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in alerts if alert.nearest_days_to_due == 0]
        lines.append("")
        self._append_visit_financial_group(lines, "Ja vencidos", overdue)
        self._append_visit_financial_group(lines, "Vence hoje", due_today)
        lines.append("")
        lines.append(_result_hint_text(allow_back=True))
        return OutgoingMessage(text="\n".join(lines))

    def _build_director_gv_summary_menu(
        self,
        gv_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        text = "Escolha o GV que voce quer abrir."
        if invalid_selection:
            text = _invalid_option_text("Escolha o GV que voce quer abrir.")
        return OutgoingMessage(
            kind="menu",
            title="GVs da Diretoria",
            text=text,
            footer="Cada opcao representa uma chave Filial | GV dentro da sua diretoria. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"director:gv_summary:{index}",
                    title=_format_gv_scope_label(gv_code),
                    description="Ver resumo desse gerente",
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
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
        try:
            summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                visit_day_token=visit_day_token,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=120,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui montar o risco financeiro desse dia agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not summaries:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei setores com visitas e risco financeiro em '{visit_day_label}'.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        gv_options = sorted(
            {
                normalize_stored_scope_value(summary.manager_code)
                for summary in summaries
                if normalize_stored_scope_value(summary.manager_code)
            },
            key=_sort_scope_code,
        )
        if len(gv_options) > 1:
            session.step = "finance_select_visit_risk_gv"
            session.visit_risk_day_options = ()
            session.finance_gv_options = tuple(gv_options)
            session.visit_risk_summaries = tuple(summaries)
            session.selected_visit_risk_gv = ""
            session.selected_visit_risk_token = visit_day_token
            session.selected_visit_risk_label = visit_day_label
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_gv_menu(
                visit_day_label=visit_day_label,
                gv_options=gv_options,
                summaries=summaries,
            )

        session.step = "finance_select_visit_risk_sector"
        session.visit_risk_day_options = ()
        session.visit_risk_summaries = tuple(summaries)
        session.finance_gv_options = tuple(gv_options)
        session.selected_visit_risk_gv = gv_options[0] if gv_options else ""
        session.selected_visit_risk_token = visit_day_token
        session.selected_visit_risk_label = visit_day_label
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_menu(visit_day_label=visit_day_label, summaries=summaries)

    def _open_finance_visit_risk_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        try:
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir os dias de risco da rota agora.\n"
                    "Tente novamente em instantes."
                )
            )
        visit_days = _normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            return OutgoingMessage(
                text=(
                    "Nao encontrei dias de visita disponiveis para risco da rota.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        session.step = "finance_select_visit_risk_day"
        session.visit_risk_day_options = tuple(visit_days)
        session.visit_risk_summaries = ()
        session.finance_gv_options = ()
        session.selected_visit_risk_gv = ""
        session.selected_visit_risk_token = ""
        session.selected_visit_risk_label = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_day_menu(visit_days=visit_days)

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
        total_clients = sum(summary.client_count for summary in summaries)
        total_pendente = _sum_money_values(summary.total_pendente for summary in summaries)
        grouped: dict[str, list[InadimplenciaVisitRiskSummary]] = {}
        for summary in summaries:
            manager_code = normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped.setdefault(manager_code, []).append(summary)

        lines = [f"{day_header_prefix} em {visit_day_label}:"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(
            f"GVs com risco: {len(gv_options)} | Setores com risco: {len(summaries)} | "
            f"Clientes com risco: {total_clients} | R$ {total_pendente}"
        )
        lines.append(f"Planilha atualizada em: {summaries[0].planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append("Escolha o GV para ver os setores com risco.")
        return OutgoingMessage(
            kind="menu",
            title=menu_title,
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro setores, clientes e valor por GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"finance:visit_risk:gv:{index}",
                    title=_format_gv_scope_label(gv_code),
                    description=(
                        f"{len(grouped.get(gv_code, []))} setor(es) | "
                        f"{sum(item.client_count for item in grouped.get(gv_code, []))} cliente(s) | "
                        f"R$ {_sum_money_values(item.total_pendente for item in grouped.get(gv_code, []))}"
                    ),
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_finance_visit_risk_day_menu(
        self,
        visit_days: list[str],
        menu_title: str = "Risco da Rota",
        header_prompt: str = "Escolha o dia da semana para ver o risco da rota.",
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = header_prompt
        if invalid_selection:
            header = _invalid_option_text(header_prompt)
        return OutgoingMessage(
            kind="menu",
            title=menu_title,
            text=header,
            footer=(
                "Depois eu mostro o resumo dos GVs, o detalhe por setor e, em seguida, os clientes. "
                "Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{VISIT_DAY_PICK_PREFIX}{index}",
                    title=_format_visit_day_label(visit_day),
                    description="Ver setores e clientes com risco",
                    shortcut=str(index),
                )
                for index, visit_day in enumerate(visit_days, start=1)
            ),
        )

    def _build_finance_visit_risk_menu(
        self,
        visit_day_label: str,
        summaries: list[InadimplenciaVisitRiskSummary],
        menu_title: str = "Risco da Rota",
        day_header_prefix: str = "Risco da rota",
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        total_clients = sum(summary.client_count for summary in summaries)
        total_pendente = _sum_money_values(summary.total_pendente for summary in summaries)
        lines = [f"{day_header_prefix} em {visit_day_label}:"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(f"*Setores com risco:* {len(summaries)}")
        lines.append(f"*Clientes com risco nesse dia:* {total_clients} | R$ {total_pendente}")
        lines.append(f"*Planilha atualizada em:* {summaries[0].planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append("Detalhe por setor: escolha o setor para ver os clientes com risco.")
        return OutgoingMessage(
            kind="menu",
            title=menu_title,
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro o GV, a quantidade e o valor do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{FINANCE_VISIT_RISK_PICK_PREFIX}{summary.seller_code}:{summary.manager_code}",
                    title=_format_sector_scope_label(summary.seller_code),
                    description=(
                        f"{_format_gv_scope_label(summary.manager_code)} | {summary.client_count} cliente(s) | "
                        f"R$ {summary.total_pendente}"
                    ),
                    shortcut=str(index),
                )
                for index, summary in enumerate(summaries, start=1)
            ),
        )

    def _build_finance_visit_risk_sector_response(
        self,
        decision: AccessDecision,
        summary: InadimplenciaVisitRiskSummary,
        visit_day_token: str,
        visit_day_label: str,
    ) -> OutgoingMessage:
        try:
            alerts = self.inadimplencia_service.list_visit_day_risk_alerts_by_seller(
                visit_day_token=visit_day_token,
                seller_code=summary.seller_code,
                manager_code=summary.manager_code,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=120,
            )
        except RuntimeError:
            return OutgoingMessage(
                text=(
                    "Nao consegui abrir os clientes desse setor agora.\n"
                    "Tente novamente em instantes."
                )
            )

        lines = [
            f"Clientes de {_format_sector_scope_label(summary.seller_code)} com risco financeiro em {visit_day_label}:",
            f"{_format_gv_scope_label(summary.manager_code)} | {summary.client_count} cliente(s) com risco | R$ {summary.total_pendente}",
            f"Planilha atualizada em: {(alerts[0].planilha_atualizada_em if alerts else summary.planilha_atualizada_em) or '-'}",
        ]
        if not alerts:
            lines.append("Nao encontrei clientes com risco para esse setor agora.")
            lines.append("")
            lines.append("Se quiser continuar, envie MENU.")
            return OutgoingMessage(text="\n".join(lines))

        overdue = [alert for alert in alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in alerts if alert.nearest_days_to_due == 0]
        lines.append("")
        self._append_visit_financial_group(lines, "Ja inadimplentes", overdue)
        self._append_visit_financial_group(lines, "Vence hoje", due_today)
        lines.append("")
        lines.append("Se quiser continuar, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_admin_action_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "O que voce deseja fazer?"
        if invalid_selection:
            text = _invalid_option_text("O que voce deseja fazer?")
        return OutgoingMessage(
            kind="menu",
            title="Acessos",
            text=text,
            footer="Cada usuario deve ter um unico cargo. Vendedor usa filial-setor. Gerente de Vendas usa filial-GV. Diretor Comercial usa filial-DC. Financeiro e admin nao usam escopo comercial.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=ADMIN_ACTION_CREATE,
                    title="Cadastrar usuario",
                    description="Adicionar um novo numero",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=ADMIN_ACTION_UPDATE,
                    title="Alterar acesso",
                    description="Mudar o acesso de um numero",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=ADMIN_ACTION_LIST,
                    title="Listar usuarios",
                    description="Ver numeros e cargos",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=ADMIN_ACTION_RENAME,
                    title="Alterar nome",
                    description="Atualizar o nome de um numero",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=ADMIN_ACTION_SUMMARY,
                    title="Resumo Operacional",
                    description="Ver cargos e usuarios ativos",
                    shortcut="5",
                ),
                InteractiveOption(
                    option_id=ADMIN_ACTION_HEALTH,
                    title="Saude do Sistema",
                    description="Ver o status das bases e acessos",
                    shortcut="6",
                ),
                InteractiveOption(
                    option_id=ADMIN_ACTION_CHECK,
                    title="Validar Acesso",
                    description="Conferir o acesso de um numero",
                    shortcut="7",
                ),
            ),
        )

    def _build_admin_summary_response(self, users: list[dict[str, Any]]) -> OutgoingMessage:
        total_users = len(users)
        active_users = sum(1 for user in users if bool(user.get("is_active")))
        inactive_users = total_users - active_users
        role_totals = {
            ROLE_ADMIN: 0,
            ROLE_FINANCEIRO: 0,
            ROLE_GERENTE_VENDAS: 0,
            ROLE_DIRETOR_COMERCIAL: 0,
            ROLE_VENDEDOR: 0,
        }
        out_of_policy = 0
        for user in users:
            roles = [str(item) for item in user.get("roles", []) if str(item).strip()]
            sectors = [str(item) for item in user.get("sectors", []) if str(item).strip()]
            gv_vdes = [str(item) for item in user.get("gv_vdes", []) if str(item).strip()]
            for role_name in roles:
                if role_name in role_totals:
                    role_totals[role_name] += 1
            if len(roles) != 1:
                out_of_policy += 1
                continue
            role_name = roles[0]
            has_invalid_sector_scope = any(not normalize_sector_scope_input(value) for value in sectors)
            has_invalid_filial_scope = any(not normalize_filial_scope_input(value) for value in sectors)
            has_invalid_gv_scope = any(not normalize_gv_scope_input(value) for value in gv_vdes)
            has_invalid_dc_scope = any(not normalize_dc_scope_input(value) for value in gv_vdes)
            if role_name == ROLE_ADMIN and (sectors or gv_vdes):
                out_of_policy += 1
            elif role_name == ROLE_FINANCEIRO and (gv_vdes or not sectors or has_invalid_filial_scope):
                out_of_policy += 1
            elif role_name == ROLE_GERENTE_VENDAS and (sectors or not gv_vdes or has_invalid_gv_scope):
                out_of_policy += 1
            elif role_name == ROLE_DIRETOR_COMERCIAL and (sectors or not gv_vdes or has_invalid_dc_scope):
                out_of_policy += 1
            elif role_name == ROLE_VENDEDOR and (gv_vdes or not sectors or has_invalid_sector_scope):
                out_of_policy += 1

        lines = [
            "Resumo operacional",
            "",
            f"*Usuarios cadastrados:* {total_users}",
            f"*Usuarios ativos:* {active_users}",
            f"*Usuarios inativos:* {inactive_users}",
            "",
            f"*Admins:* {role_totals[ROLE_ADMIN]}",
            f"*Financeiro:* {role_totals[ROLE_FINANCEIRO]}",
            f"*Gerentes de Vendas:* {role_totals[ROLE_GERENTE_VENDAS]}",
            f"*Diretores Comerciais:* {role_totals[ROLE_DIRETOR_COMERCIAL]}",
            f"*Vendedores:* {role_totals[ROLE_VENDEDOR]}",
            "",
            f"*Cadastros fora da politica atual:* {out_of_policy}",
            "",
            "Se quiser continuar, envie MENU.",
        ]
        return OutgoingMessage(text="\n".join(lines))

    def _build_admin_health_response(self) -> OutgoingMessage:
        access_status = self.access_control.status()
        clients_status = self.query_service.status()
        inad_status = self.inadimplencia_service.status()
        comod_status = self.comodatos_service.status()

        lines = [
            "Saude do sistema",
            "",
            f"*RBAC:* {_format_health_status(access_status.get('ready', False))}",
            f"*Base de clientes:* {_format_health_status(clients_status.get('ready', False))}",
            f"*Inadimplencia:* {_format_health_status(inad_status.get('ready', False))}",
            f"*Comodatos:* {_format_health_status(comod_status.get('ready', False))}",
        ]

        errors = [
            ("RBAC", access_status.get("last_error")),
            ("Clientes", clients_status.get("last_error")),
            ("Inadimplencia", inad_status.get("last_error")),
            ("Comodatos", comod_status.get("last_error")),
        ]
        visible_errors = [(label, str(message).strip()) for label, message in errors if str(message or "").strip()]
        if visible_errors:
            lines.append("")
            lines.append("Detalhes:")
            for label, message in visible_errors:
                lines.append(f"{label}: {message}")

        lines.append("")
        lines.append("Se quiser continuar, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_admin_access_check_response(
        self,
        phone_number: str,
        user: dict[str, Any] | None,
    ) -> OutgoingMessage:
        client_decision = self.access_control.authorize(phone_number=phone_number, area="cliente")
        inad_decision = self.access_control.authorize(phone_number=phone_number, area="inadimplencia")
        comodato_decision = self.access_control.authorize(phone_number=phone_number, area="comodato")

        roles = tuple(str(item) for item in (user or {}).get("roles", []))
        sectors = tuple(str(item) for item in (user or {}).get("sectors", []))
        gv_vdes = tuple(str(item) for item in (user or {}).get("gv_vdes", []))
        active_label = "Sim" if bool((user or {}).get("is_active")) else "Nao"
        lines = [
            "Validacao de acesso",
            "",
            f"Numero: {phone_number}",
            f"Nome: {str((user or {}).get('name') or '-').strip() or '-'}",
        ]
        if user is None:
            lines.append("Cadastro: numero nao encontrado")
        else:
            lines.append(f"Ativo: {active_label}")
            lines.append(f"Cargo: {_format_roles(roles)}")
            lines.append(f"Acesso comercial: {self._format_user_access_label(roles, sectors, gv_vdes)}")

        lines.append("")
        lines.append(f"Cliente: {_format_access_decision_label(client_decision)}")
        lines.append(f"Inadimplencia: {_format_access_decision_label(inad_decision)}")
        lines.append(f"Comodatos: {_format_access_decision_label(comodato_decision)}")
        lines.append(
            f"Visitas do dia: {'liberado' if self._can_use_visit_menu(client_decision) else 'bloqueado'}"
        )
        lines.append(
            f"Menu financeiro: {'liberado' if self._can_use_finance_menu(client_decision) else 'bloqueado'}"
        )
        lines.append(
            f"Menu admin: {'liberado' if self._is_admin(client_decision) else 'bloqueado'}"
        )
        lines.append("")
        lines.append("Se quiser continuar, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_role_menu(
        self,
        phone_number: str,
        session: LookupSession,
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        lines = []
        if session.admin_action == "update":
            lines.append(f"Encontrei este numero: {phone_number}")
            lines.append(f"Nome atual: {session.current_name or '-'}")
            lines.append(f"Cargo atual: {_format_roles(session.current_roles)}")
            if ROLE_FINANCEIRO in session.current_roles:
                lines.append(f"Filiais atuais: {_format_finance_filiais(session.current_sectors)}")
            else:
                lines.append(f"Setor atual: {_format_sectors(session.current_sectors)}")
            lines.append(f"Escopo atual de gestao: {_format_gv_vdes(session.current_gv_vdes, role_name=_primary_role(session.current_roles))}")
        else:
            lines.append(f"Numero recebido: {phone_number}")
            lines.append(f"Nome: {session.target_name or '-'}")
        if invalid_selection:
            lines.append("Nao entendi essa opcao.")
        lines.append("Escolha o cargo desse usuario.")
        return OutgoingMessage(
            kind="menu",
            title="Cargo do Usuario",
            text="\n".join(lines),
            footer="Escolha um unico cargo. Vendedor usa filial-setor. GV usa filial-GV. DC usa filial-DC. Financeiro usa apenas filiais. Admin tem acesso total.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=ADMIN_ROLE_VENDEDOR,
                    title="Vendedor",
                    description="Consulta clientes da propria chave filial-setor",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=ADMIN_ROLE_GERENTE_VENDAS,
                    title="Gerente de Vendas",
                    description="Consulta a base do proprio GV em todas as revendas",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=ADMIN_ROLE_ADMIN,
                    title="Admin",
                    description="Acesso completo",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=ADMIN_ROLE_FINANCEIRO,
                    title="Financeiro",
                    description="Consulta as filiais liberadas",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=ADMIN_ROLE_DIRETOR_COMERCIAL,
                    title="Diretor Comercial",
                    description="Acompanha todos os gerentes sob responsabilidade",
                    shortcut="5",
                ),
            ),
        )

    def _build_admin_confirmation(self, session: LookupSession) -> OutgoingMessage:
        if session.admin_action == "create":
            action_title = "Confirmar Cadastro"
            action_label = "Cadastrar usuario"
        elif session.admin_action == "rename":
            action_title = "Confirmar Nome"
            action_label = "Alterar nome"
        else:
            action_title = "Confirmar Alteracao"
            action_label = "Alterar acesso"
        lines = [
            f"Acao: {action_label}",
            f"Numero: {session.target_phone}",
        ]
        if session.admin_action == "rename":
            lines.append(f"Nome atual: {session.current_name or '-'}")
            lines.append(f"Novo nome: {session.target_name or '-'}")
            lines.append(f"Cargo atual: {_format_roles(session.current_roles)}")
            lines.append(f"Acesso atual: {self._format_user_access_label(session.current_roles, session.current_sectors, session.current_gv_vdes)}")
        else:
            lines.append(f"Nome: {session.target_name or '-'}")
        if session.admin_action != "rename" and (session.current_roles or session.current_sectors or session.current_gv_vdes):
            lines.append(f"Cargo atual: {_format_roles(session.current_roles)}")
            if ROLE_FINANCEIRO in session.current_roles:
                lines.append(f"Filiais atuais: {_format_finance_filiais(session.current_sectors)}")
            else:
                lines.append(f"Setor atual: {_format_sectors(session.current_sectors)}")
            lines.append(
                f"Escopo atual de gestao: {_format_gv_vdes(session.current_gv_vdes, role_name=_primary_role(session.current_roles))}"
            )
        if session.admin_action != "rename":
            lines.append(f"Novo cargo: {self._display_role(session.target_role)}")
            if session.target_role == ROLE_VENDEDOR:
                lines.append(f"Novo setor: {_format_sectors(session.target_sectors)}")
            elif session.target_role == ROLE_GERENTE_VENDAS:
                lines.append(f"Novo acesso por GV: {_format_gv_vdes(session.target_gv_vdes, role_name=ROLE_GERENTE_VENDAS)}")
            elif session.target_role == ROLE_DIRETOR_COMERCIAL:
                lines.append(
                    f"Novos DCs sob responsabilidade: {_format_gv_vdes(session.target_gv_vdes, role_name=ROLE_DIRETOR_COMERCIAL)}"
                )
            elif session.target_role == ROLE_FINANCEIRO:
                lines.append(f"Novas filiais: {_format_finance_filiais(session.target_sectors)}")
            else:
                lines.append("Novo acesso: acesso completo")
        lines.append("")
        lines.append("Se estiver tudo certo, confirme.")
        return OutgoingMessage(
            kind="menu",
            title=action_title,
            text="\n".join(lines),
            footer="Escolha Confirmar para salvar.",
            button_text="Revisar",
            options=(
                InteractiveOption(
                    option_id=ADMIN_CONFIRM,
                    title="Confirmar",
                    description="Salvar alteracoes",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=ADMIN_CANCEL,
                    title="Cancelar",
                    description="Voltar sem salvar",
                    shortcut="2",
                ),
            ),
        )

    def _build_admin_users_list_response(self, users: list[dict[str, Any]]) -> OutgoingMessage:
        if not users:
            return OutgoingMessage(
                text=(
                    "Nao encontrei usuarios cadastrados.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        visible_users = users[:50]
        lines = [f"Usuarios cadastrados: {len(users)}"]
        if len(users) > len(visible_users):
            lines.append(f"Mostrando os primeiros {len(visible_users)}.")

        for index, user in enumerate(visible_users, start=1):
            name = str(user.get("name") or "").strip() or "Sem nome"
            phone_number = str(user.get("phone_number") or "-")
            is_active = bool(user.get("is_active"))
            roles = tuple(str(item) for item in user.get("roles", []))
            sectors = tuple(str(item) for item in user.get("sectors", []))
            gv_vdes = tuple(str(item) for item in user.get("gv_vdes", []))
            role_label = ", ".join(self._display_role(role_name) for role_name in roles) if roles else "-"
            access_label = self._format_user_access_label(roles=roles, sectors=sectors, gv_vdes=gv_vdes)
            lines.append(f"{index}. {name} | {phone_number}")
            lines.append(f"Cargo: {role_label} | Ativo: {'Sim' if is_active else 'Nao'} | Acesso: {access_label}")

        lines.append("")
        lines.append("Se quiser continuar, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_fantasia_results_menu(
        self,
        query_text: str,
        records: list[DClienteRecord],
        search_context: str = "cliente",
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header_context_map = {
            "cliente": f"Encontrei {len(records)} cliente(s) com '{query_text}'.",
            "inadimplencia": f"Encontrei {len(records)} cliente(s) com '{query_text}' na inadimplencia.",
            "comodato": f"Encontrei {len(records)} cliente(s) com '{query_text}' nos comodatos pendentes.",
            "giro": f"Encontrei {len(records)} cliente(s) com '{query_text}' na base de giro de vasilhame.",
            "documentacao": f"Encontrei {len(records)} cliente(s) com '{query_text}' na base de documentacao pendente.",
            "prazo_limite": f"Encontrei {len(records)} cliente(s) com '{query_text}' na base de prazo e limite.",
        }
        header = header_context_map.get(search_context, f"Encontrei {len(records)} cliente(s) com '{query_text}'.")
        if invalid_selection:
            header = f"Nao entendi essa opcao.\n{header}"
        detail_prompt_map = {
            "cliente": "Escolha um cliente para ver os detalhes.",
            "inadimplencia": "Escolha um cliente para ver os titulos em aberto.",
            "comodato": "Escolha um cliente para ver os comodatos pendentes.",
            "giro": "Escolha um cliente para ver os dados de giro de vasilhame.",
            "documentacao": "Escolha um cliente para ver a documentacao pendente.",
            "prazo_limite": "Escolha um cliente para ver prazo, limite e documentacao.",
        }
        text = f"{header}\n{detail_prompt_map.get(search_context, 'Escolha um cliente para ver os detalhes.')}"
        title_map = {
            "cliente": "Resultados da Busca",
            "inadimplencia": "Resultados de Inadimplencia",
            "comodato": "Resultados de Comodatos",
            "giro": "Resultados de Giro",
            "documentacao": "Resultados de Documentacao",
            "prazo_limite": "Resultados de Prazo e Limite",
        }
        code_label = "Codigo do PDV" if search_context == "cliente" else "NB"
        return OutgoingMessage(
            kind="menu",
            title=title_map.get(search_context, "Resultados da Busca"),
            text=text,
            footer=f"A lista mostra {code_label.lower()}, revenda e nome do cliente. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{FANTASIA_PICK_PREFIX}{index}",
                    title=record.nome_fantasia or record.razao_social or f"Cliente {index}",
                    description=f"{code_label} {record.cod_pdv} | Revenda {record.filial}",
                )
                for index, record in enumerate(records, start=1)
            ),
        )

    def _build_inadimplencia_client_menu(
        self,
        query_text: str,
        summaries: list[InadimplenciaClientSummary],
        total_available: int | None = None,
        page: int | None = None,
        page_size: int = INADIMPLENCIA_PAGE_SIZE,
        list_context: str = "",
        invalid_selection: bool = False,
        navigation_notice: str = "",
    ) -> OutgoingMessage:
        custom_header = _extract_inadimplencia_custom_header(query_text)
        scope_label = _extract_inadimplencia_scope_label(query_text)
        director_compact = list_context == INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS
        if custom_header:
            header = custom_header
        elif scope_label:
            header = f"Esses sao os clientes inadimplentes da {scope_label}."
        elif director_compact:
            header = "Diretoria | Cobranca"
        else:
            header = f"Encontrei {len(summaries)} cliente(s) com '{query_text}' na inadimplencia."
        if navigation_notice:
            header = f"{navigation_notice}\n{header}"
        if invalid_selection:
            header = f"Nao entendi essa opcao.\n{header}"
        lines = [header]
        paginated = page is not None and total_available is not None and total_available > page_size
        if paginated:
            total_pages = _compute_page_count(total_items=total_available, page_size=page_size)
            current_page = min(max(page or 1, 1), total_pages)
            start_index = ((current_page - 1) * page_size) + 1
            end_index = start_index + len(summaries) - 1
            if director_compact:
                lines.append(f"Pagina {current_page} de {total_pages} | Clientes {start_index}-{end_index} de {total_available}")
            else:
                lines.append(f"Pagina {current_page} de {total_pages}.")
                lines.append(f"Mostrando clientes {start_index} a {end_index} de {total_available}.")
        elif (custom_header or scope_label) and total_available and total_available > len(summaries):
            lines.append(f"Estou mostrando os primeiros {len(summaries)} de {total_available} cliente(s).")
        if director_compact:
            lines.append(f"Clientes na lista: {len(summaries)}")
            lines.append("Escolha o cliente para ver os titulos.")
        else:
            lines.append("Escolha o cliente certo para ver os titulos pendentes.")
        text = "\n".join(lines)
        options: list[InteractiveOption] = [
            InteractiveOption(
                option_id=(
                    f"{INADIMPLENCIA_CLIENT_PICK_PREFIX}{summary.filial}:{summary.cod_pdv}"
                    if paginated
                    else f"{FANTASIA_PICK_PREFIX}{index}"
                ),
                title=summary.nome or f"Cliente {index}",
                description=(
                    f"NB {summary.cod_pdv} | Revenda {summary.filial} | "
                    f"{summary.title_count} titulo(s) | R$ {summary.total_pendente}"
                ),
                shortcut=str(index),
            )
            for index, summary in enumerate(summaries, start=1)
        ]
        if paginated:
            total_pages = _compute_page_count(total_items=total_available or 0, page_size=page_size)
            current_page = min(max(page or 1, 1), total_pages)
            next_shortcut, prev_shortcut = _inadimplencia_page_shortcuts(page_size)
            if current_page > 1:
                options.append(
                    InteractiveOption(
                        option_id=INADIMPLENCIA_PAGE_PREV,
                        title="Pagina anterior",
                        description=f"Voltar para a pagina {current_page - 1}",
                        shortcut=prev_shortcut,
                    )
                )
            if current_page < total_pages:
                options.append(
                    InteractiveOption(
                        option_id=INADIMPLENCIA_PAGE_NEXT,
                        title="Proxima pagina",
                        description=f"Ir para a pagina {current_page + 1}",
                        shortcut=next_shortcut,
                    )
                )
        return OutgoingMessage(
            kind="menu",
            title="Diretoria | Cobranca" if director_compact else "Clientes Encontrados",
            text=text,
            footer=(
                f"{'Escolha o cliente para ver os titulos.' if director_compact else 'Primeiro voce escolhe o cliente. Depois eu mostro os titulos.'}"
                f"{' Use ' + _inadimplencia_page_shortcuts_label(page_size, page, total_available) if paginated else ' Use A ou ANT para voltar.'}"
            ),
            button_text="Escolher",
            options=tuple(options),
        )

    def _build_comodato_client_menu(
        self,
        query_text: str,
        summaries: list[ComodatoClientSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = f"Encontrei {len(summaries)} cliente(s) com '{query_text}' nos comodatos pendentes."
        if invalid_selection:
            header = f"Nao entendi essa opcao.\n{header}"
        text = f"{header}\nEscolha o cliente certo para ver os comodatos pendentes."
        return OutgoingMessage(
            kind="menu",
            title="Clientes Encontrados",
            text=text,
            footer="Primeiro voce escolhe o cliente. Depois eu mostro os comodatos pendentes. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{FANTASIA_PICK_PREFIX}{index}",
                    title=summary.nome or f"Cliente {index}",
                    description=(
                        f"NB {summary.cod_pdv} | Revenda {summary.filial} | "
                        f"{summary.comodato_count} comodato(s) | {summary.total_material} material(is)"
                    ),
                )
                for index, summary in enumerate(summaries, start=1)
            ),
        )

    def _build_visit_day_options(
        self,
        visit_days: list[str] | tuple[str, ...],
        *,
        description: str,
    ) -> tuple[InteractiveOption, ...]:
        ordered_visit_days = _normalize_visit_day_menu_values(visit_days)
        return tuple(
            InteractiveOption(
                option_id=f"{VISIT_DAY_PICK_PREFIX}{index}",
                title=_format_visit_day_label(visit_day),
                description=description,
                shortcut=str(index),
            )
            for index, visit_day in enumerate(ordered_visit_days, start=1)
        )

    def _select_visit_day_option(
        self,
        *,
        text: str,
        normalized: str,
        visit_days: tuple[str, ...],
        description: str,
    ) -> str | None:
        ordered_visit_days = tuple(_normalize_visit_day_menu_values(visit_days))
        selected_option = _select_interactive_option(
            text=text,
            normalized=normalized,
            options=self._build_visit_day_options(
                ordered_visit_days,
                description=description,
            ),
        )
        if selected_option is None:
            return None

        raw_index = selected_option.option_id.removeprefix(VISIT_DAY_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(ordered_visit_days):
                return ordered_visit_days[selected_index - 1]
        return None

    def _build_visit_day_menu(
        self,
        decision: AccessDecision,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = "Escolha o dia que voce quer consultar."
        if invalid_selection:
            header = _invalid_option_text("Escolha o dia que voce quer consultar.")
        footer = "Depois eu mostro o resumo dos GVs e, logo abaixo, o detalhe por setor."
        if not self._uses_grouped_visit_flow(decision):
            footer = "Depois eu mostro os clientes desse dia."
        return OutgoingMessage(
            kind="menu",
            title="Visitas do Dia",
            text=header,
            footer=f"{'Depois eu mostro o proximo nivel de detalhe da rota.' if self._uses_grouped_visit_flow(decision) else footer} Use A ou ANT para voltar.",
            button_text="Escolher",
            options=self._build_visit_day_options(visit_days, description="Ver clientes desse dia"),
        )

    def _build_giro_visit_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = "Qual dia voce quer consultar no giro?"
        if invalid_selection:
            header = _invalid_option_text("Escolha um dia para consultar o giro.")
        return OutgoingMessage(
            kind="menu",
            title="Giro por Dia",
            text=header,
            footer=(
                "Eu vou mostrar o resumo do dia e, depois, o proximo nivel de detalhe. "
                "Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=self._build_visit_day_options(visit_days, description="Ver resumo e clientes com caixa desse dia"),
        )

    def _build_inadimplencia_visit_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = "Qual dia voce quer consultar na inadimplencia?"
        if invalid_selection:
            header = _invalid_option_text("Escolha um dia para consultar a inadimplencia.")
        return OutgoingMessage(
            kind="menu",
            title="Inadimplencia por Dia",
            text=header,
            footer=(
                "Eu vou mostrar o resumo do dia e depois o proximo nivel de detalhe com os clientes em risco "
                "financeiro. Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=self._build_visit_day_options(
                visit_days,
                description="Ver a rota com risco financeiro desse dia",
            ),
        )

    def _build_documentacao_visit_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = "Qual dia voce quer consultar na documentacao pendente?"
        if invalid_selection:
            header = _invalid_option_text("Escolha um dia para consultar a documentacao pendente.")
        return OutgoingMessage(
            kind="menu",
            title="Documentacao por Dia",
            text=header,
            footer=(
                "Eu vou mostrar o resumo documental do dia e, logo abaixo, os clientes com pendencia. "
                "Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=self._build_visit_day_options(
                visit_days,
                description="Ver resumo e clientes com pendencia documental desse dia",
            ),
        )

    def _build_visit_day_manager_menu(
        self,
        visit_day: str,
        visit_summaries: list[VisitSellerSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        if not visit_summaries:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei visitas para o dia '{visit_day_label}'.\n"
                    "Se quiser tentar de novo, envie MENU."
                )
            )

        lines = [f"Visitas de '{visit_day_label}'"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(
            f"GVs na rota: {len({normalize_stored_scope_value(summary.manager_code) or normalize_stored_scope_value(summary.seller_code) for summary in visit_summaries})} | "
            f"Setores: {len(visit_summaries)} | "
            f"Visitas: {sum(int(summary.visit_count or 0) for summary in visit_summaries)}"
        )
        lines.append("Detalhe por setor: escolha o setor.")
        return OutgoingMessage(
            kind="menu",
            title="Visitas por Setor",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro o GV e a quantidade de visitas do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{VISIT_SELLER_PICK_PREFIX}{index}",
                    title=_format_sector_scope_label(summary.seller_code),
                    description=f"{_format_gv_scope_label(summary.manager_code)} | {summary.visit_count} visita(s)",
                    shortcut=str(index),
                )
                for index, summary in enumerate(visit_summaries, start=1)
            ),
        )

    def _build_single_record_response(
        self,
        record: DClienteRecord,
        criteria: str,
        *,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        lines = ["Cliente", ""]
        self._append_cliente_detail_lines(lines, record=record, decision=decision)
        lines.append("")
        lines.append(_result_hint_text(allow_back=False))
        return OutgoingMessage(text="\n".join(lines))

    def _build_search_response(
        self,
        records: list[DClienteRecord],
        criteria: str,
        *,
        decision: AccessDecision,
        scope_restricted: bool = True,
    ) -> OutgoingMessage:
        if not records:
            message = f"Nao encontrei cliente para {criteria}"
            if scope_restricted:
                message = f"{message} dentro do acesso liberado para o seu numero"
            return OutgoingMessage(
                text=(
                    f"{message}.\n"
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        lines = ["Cliente" if len(records) == 1 else f"Clientes encontrados: {len(records)}"]
        lines.append(f"Consulta: {criteria}")
        for index, record in enumerate(records, start=1):
            lines.append("")
            self._append_cliente_detail_lines(
                lines,
                record=record,
                decision=decision,
                index=index if len(records) > 1 else None,
                scope_restricted=scope_restricted,
            )

        lines.append("")
        lines.append(_result_hint_text(allow_back=False))
        return OutgoingMessage(text="\n".join(lines))

    def _append_cliente_detail_lines(
        self,
        lines: list[str],
        *,
        record: DClienteRecord,
        decision: AccessDecision,
        index: int | None = None,
        scope_restricted: bool = True,
    ) -> None:
        name = record.nome_fantasia or record.razao_social or "-"
        score_record = self._safe_cliente_score_record(record)
        title = f"*{name}*"
        if index is not None:
            title = f"{index}) {title}"
        lines.append(title)
        score_prefix = f"*Score: {score_record.score} |* " if score_record is not None and score_record.score else ""
        lines.append(f"{score_prefix}NB: {record.cod_pdv or '-'} | Revenda: {record.filial or '-'} | Setor: {record.vendedor or '-'}")
        lines.append("")
        lines.append("*Cadastro:*")
        lines.append(f"Razao social: {record.razao_social or '-'}")
        lines.append(f"Fantasia: {record.nome_fantasia or '-'}")
        lines.append(f"Telefone: {record.telefone or '-'}")
        lines.append(f"Situacao: {record.status or '-'}")
        lines.append(f"Cidade: {record.cidade or '-'}")
        lines.append("")
        lines.append("*Rota:*")
        lines.append(f"Dia de visita: {_format_cliente_visit_day(record.dia_visita)}")
        lines.append(f"Vendedor/Setor: {record.vendedor or '-'}")
        lines.append("")
        lines.append("*Financeiro:*")
        lines.append(f"Cond. pag.: {record.cond_pag_atual or '-'}")
        lines.append(f"Limite: {_format_currency_brl(record.limite_credito)}")
        lines.append(f"Total pendente: {_format_currency_brl(record.total_pendente)}")
        self._append_cliente_score_lines(lines, score_record)
        lines.append("")
        lines.append("*Pendencias:*")
        lines.append(f"Comodatos: {record.total_comodatos_pendentes}")
        self._append_documentacao_cliente_lines(
            lines,
            decision=decision,
            record=record,
            scope_restricted=scope_restricted,
        )
        lines.append("")
        lines.append(f"*Atualizado em:* {_format_display_date(record.ultima_atualizacao_tabela or '-')}")

    def _safe_cliente_score_record(self, record: DClienteRecord) -> ClienteScoreRecord | None:
        return self._safe_cliente_score_by_registration(
            filial=record.filial,
            cod_pdv=record.cod_pdv,
        )

    def _safe_cliente_score_by_registration(self, *, filial: str, cod_pdv: str) -> ClienteScoreRecord | None:
        self._cliente_score_last_lookup_available = False
        if not self._cliente_score_service_ready():
            return None
        try:
            record = self.clientes_score_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
            )
        except Exception:
            return None
        self._cliente_score_last_lookup_available = True
        return record

    def _cliente_score_service_ready(self) -> bool:
        if self.clientes_score_service is None:
            return False
        try:
            status = self.clientes_score_service.status()
        except Exception:
            return False
        return bool(status.get("ready"))

    def _append_cliente_score_lines(self, lines: list[str], score_record: ClienteScoreRecord | None) -> None:
        if not self._cliente_score_service_ready():
            return
        if score_record is None:
            if not self._cliente_score_last_lookup_available:
                return
            lines.append("*Score:* Cliente sem registro no relatorio de score.")
            return
        lines.append(f"*Recebido (historico):* {_format_currency_brl(score_record.recebido_historico)}")
        lines.append(f"*Titulos pagos:* {score_record.titulos_historico}")
        lines.append(f"*% com atraso >3d:* {_format_percent_value(score_record.pct_atraso_historico)}")
        lines.append(f"*Maior atraso:* {_format_days_count(score_record.maior_atraso_dias)}")
        lines.append(f"*Pagos com +30d:* {score_record.vezes_mais_30d}")
        lines.append(f"*Tarifa paga:* {_format_currency_brl(score_record.tarifa_paga)}")
        lines.append(f"*Juros pagos:* {_format_currency_brl_compact(score_record.juros_pagos)}")

    def _append_documentacao_cliente_lines(
        self,
        lines: list[str],
        *,
        decision: AccessDecision,
        record: DClienteRecord,
        scope_restricted: bool = True,
    ) -> None:
        documentacao_record = self._safe_documentacao_cliente_record(
            decision=decision,
            record=record,
            scope_restricted=scope_restricted,
        )
        if documentacao_record is None:
            return
        lines.append("*Documentacao:*")
        for label, value in (
            ("Contrato Social", documentacao_record.contrato_social),
            ("Cpf", documentacao_record.cpf),
            ("Rg", documentacao_record.rg),
            ("Comprovante de residencia", documentacao_record.comprovante_residencia),
            ("Fachada", documentacao_record.fachada),
            ("Ficha de Cadastro", documentacao_record.ficha_cadastro),
        ):
            lines.append(f"- {label}: {value or '-'}")

    def _safe_documentacao_cliente_record(
        self,
        *,
        decision: AccessDecision,
        record: DClienteRecord,
        scope_restricted: bool = True,
    ) -> DocumentacaoPendenteClientRecord | None:
        return self._safe_documentacao_registration_record(
            decision=decision,
            filial=record.filial,
            cod_pdv=record.cod_pdv,
            scope_restricted=scope_restricted,
        )

    def _safe_documentacao_registration_record(
        self,
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
        scope_restricted: bool = True,
    ) -> DocumentacaoPendenteClientRecord | None:
        try:
            status = self.documentacao_pendente_service.status()
        except Exception:
            return None
        if not status.get("ready"):
            return None
        try:
            records = self.documentacao_pendente_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision) if scope_restricted else None,
                allowed_gv_vdes=self._allowed_gv_vdes(decision) if scope_restricted else None,
                limit=1,
            )
        except RuntimeError:
            return None
        return records[0] if records else None

    def _append_documentacao_snapshot_lines(
        self,
        lines: list[str],
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
    ) -> None:
        try:
            status_payload = self.documentacao_pendente_service.status()
        except Exception:
            status_payload = {"ready": False}
        documentacao_record = self._safe_documentacao_registration_record(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
        )
        if documentacao_record is None:
            if status_payload.get("ready"):
                lines.append("*Documentacao:* Sem registro na base importada")
            else:
                lines.append("*Documentacao:* Base nao importada ou indisponivel")
            return
        lines.append(
            f"*Documentacao:* Contrato Social {documentacao_record.contrato_social} | "
            f"Cpf {documentacao_record.cpf} | Rg {documentacao_record.rg}"
        )
        lines.append(
            f"*Documentacao 2:* Comprovante de residencia {documentacao_record.comprovante_residencia} | "
            f"Fachada {documentacao_record.fachada} | Ficha de Cadastro {documentacao_record.ficha_cadastro}"
        )

    def _append_documentacao_snapshot_detail_lines(
        self,
        lines: list[str],
        *,
        decision: AccessDecision,
        filial: str,
        cod_pdv: str,
    ) -> None:
        try:
            status_payload = self.documentacao_pendente_service.status()
        except Exception:
            status_payload = {"ready": False}
        documentacao_record = self._safe_documentacao_registration_record(
            decision=decision,
            filial=filial,
            cod_pdv=cod_pdv,
        )
        if documentacao_record is None:
            if status_payload.get("ready"):
                lines.append("*Documentacao:* Sem registro na base importada")
            else:
                lines.append("*Documentacao:* Base nao importada ou indisponivel")
            return

        lines.append("*Documentacao:*")
        for label, value in (
            ("Contrato Social", documentacao_record.contrato_social),
            ("Cpf", documentacao_record.cpf),
            ("Rg", documentacao_record.rg),
            ("Comprovante de residencia", documentacao_record.comprovante_residencia),
            ("Fachada", documentacao_record.fachada),
            ("Ficha de Cadastro", documentacao_record.ficha_cadastro),
        ):
            lines.append(f"- {label}: {value or '-'}")

    def _run_repeatable_registration_lookup(
        self,
        *,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
        search_context: str,
        filial: str,
        cod_pdv: str,
        return_menu: str = "search_menu",
    ) -> OutgoingMessage:
        self._remember_last_context(
            session,
            intent=f"{search_context}_client",
            search_context=search_context,
            client_filial=filial,
            client_cod_pdv=cod_pdv,
        )
        return self._with_post_result_navigation(
            sender,
            session,
            self._run_registration_lookup(
                decision=decision,
                search_context=search_context,
                filial=filial,
                cod_pdv=cod_pdv,
            ),
            return_menu=return_menu,
            repeat_action=REPEAT_SEARCH_REGISTRATION,
        )

    def _run_registration_lookup(
        self,
        decision: AccessDecision,
        search_context: str,
        filial: str,
        cod_pdv: str,
    ) -> OutgoingMessage:
        if search_context == "inadimplencia":
            records = self.inadimplencia_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
            return self._build_inadimplencia_response(records, f"revenda {filial} e NB {cod_pdv}")
        if search_context == "comodato":
            records = self.comodatos_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
            return self._build_comodato_response(records, f"revenda {filial} e NB {cod_pdv}")
        if search_context == "giro":
            records = self.giro_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=20,
            )
            if not records:
                try:
                    matching_base = self.query_service.search_by_registration(
                        filial=filial,
                        cod_pdv=cod_pdv,
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    )
                except RuntimeError:
                    matching_base = []
                if matching_base:
                    historical_response = self._build_giro_historical_fallback_response(
                        decision=decision,
                        filial=filial,
                        cod_pdv=cod_pdv,
                        criteria=f"revenda {filial} e NB {cod_pdv}",
                    )
                    if historical_response is not None:
                        return historical_response
                    return OutgoingMessage(
                        text=(
                            f"Encontrei o cadastro para revenda {filial} e NB {cod_pdv}, "
                            "mas ele nao apareceu no ultimo relatorio de giro importado.\n"
                            "Se quiser tentar outra busca, envie MENU."
                        )
                    )
            return self._build_giro_response(
                records,
                f"revenda {filial} e NB {cod_pdv}",
                scope_restricted=not self._has_unrestricted_lookup_access(decision),
            )
        if search_context == "documentacao":
            records = self.documentacao_pendente_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=20,
            )
            return self._build_documentacao_pendente_response(
                records,
                f"revenda {filial} e NB {cod_pdv}",
                scope_restricted=not self._has_unrestricted_lookup_access(decision),
            )
        if search_context == "prazo_limite":
            records = self.prazo_limite_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
            if not records:
                try:
                    matching_base = self.query_service.search_by_registration(
                        filial=filial,
                        cod_pdv=cod_pdv,
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    )
                except RuntimeError:
                    matching_base = []
                if matching_base:
                    return OutgoingMessage(
                        text=(
                            f"Encontrei o cadastro para revenda {filial} e NB {cod_pdv}, "
                            "mas ele nao apareceu no ultimo relatorio de prazo e limite importado.\n"
                            "Se quiser tentar outra busca, envie MENU."
                        )
                    )
            return self._build_prazo_limite_response(
                records,
                f"revenda {filial} e NB {cod_pdv}",
                decision=decision,
                scope_restricted=not self._has_unrestricted_lookup_access(decision),
            )

        records = self.query_service.search_by_registration(
            filial=filial,
            cod_pdv=cod_pdv,
            allowed_sectors=self._allowed_sectors(decision),
            allowed_gv_vdes=self._allowed_gv_vdes(decision),
        )
        return self._build_search_response(
            records,
            f"revenda {filial} e Cod PDV {cod_pdv}",
            decision=decision,
        )

    def _search_giro_by_document(
        self,
        normalized_document: str,
    ) -> list[GiroClientRecord]:
        client_records = self.query_service.search_by_document(
            document=normalized_document,
            allowed_sectors=None,
            allowed_gv_vdes=None,
            limit=20,
        )
        unique_keys: set[tuple[str, str]] = set()
        giro_records: list[GiroClientRecord] = []
        for client in client_records:
            filial = _normalize_filial(client.filial)
            cod_pdv = _normalize_cod_pdv(client.cod_pdv)
            if not filial or not cod_pdv:
                continue
            key = (filial, cod_pdv)
            if key in unique_keys:
                continue
            unique_keys.add(key)
            giro_records.extend(
                self.giro_service.search_by_registration(
                    filial=filial,
                    cod_pdv=cod_pdv,
                    allowed_sectors=None,
                    allowed_gv_vdes=None,
                    limit=5,
                )
            )
        return sorted(giro_records, key=lambda item: (_sort_numeric_text(item.filial), _sort_numeric_text(item.cod_pdv)))

    def _build_inadimplencia_response(
        self,
        records: list[InadimplenciaRecord],
        criteria: str,
        *,
        compact: bool = False,
    ) -> OutgoingMessage:
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei titulos em aberto para {criteria} dentro do acesso liberado para o seu numero.\n"
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        total_pendente = _sum_money_values(record.valor_pendente for record in records)
        total_atrasado = _sum_money_values(
            record.valor_corrigido or record.valor_pendente
            for record in records
            if _inadimplencia_days_value(record.dias) is not None and _inadimplencia_days_value(record.dias) < 0
        )
        first = records[0]
        lines = [
            "Diretoria | Cobranca" if compact else "Inadimplencia",
            "",
            f"*{first.nome or '-'}*",
            f"- Revenda: {first.filial or '-'}",
            f"- NB: {first.cod_pdv or '-'}",
            "",
            "*Resumo:*",
            f"- Titulos: {len(records)}",
            f"- Total pendente: {_format_inadimplencia_money(total_pendente)}",
            f"- Total atrasado: {_format_inadimplencia_money(total_atrasado)}",
            f"- {_format_inadimplencia_summary_timing_label(records)}",
            f"- Atualizado em: {_format_display_date(first.planilha_atualizada_em or '-')}",
            "",
            "*Titulos:*",
        ]

        for index, record in enumerate(records, start=1):
            lines.append("")
            lines.append(f"{index}) {_format_inadimplencia_timing_label(record.dias).capitalize()}")
            lines.append(f"- NF: {record.nota_fiscal or '-'}")
            lines.append(f"- Vencimento: {_format_display_date(record.data_vencimento or '-')}")
            if not compact:
                lines.append(f"- Emissao: {_format_display_date(record.data_emissao or '-')}")
            lines.append(f"- Valor: {_format_inadimplencia_money(record.valor_corrigido or record.valor_pendente)}")

        lines.append("")
        lines.append(_result_hint_text(allow_back=compact))
        return OutgoingMessage(text="\n".join(lines))

    def _build_comodato_response(
        self,
        records: list[ComodatoRecord],
        criteria: str,
    ) -> OutgoingMessage:
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei comodatos pendentes para {criteria} dentro do acesso liberado para o seu numero.\n"
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        unique_comodatos = {
            _normalize_cod_pdv(record.nro_comodato)
            for record in records
            if _normalize_cod_pdv(record.nro_comodato)
        }
        lines = [f"Encontrei {len(unique_comodatos) or len(records)} comodato(s) pendente(s) para {criteria}."]
        lines.append(f"*Planilha atualizada em:* {records[0].planilha_atualizada_em or '-'}")
        lines.append(f"*Materiais pendentes:* {len(records)}")
        for index, record in enumerate(records, start=1):
            lines.append("")
            lines.append(f"{index}. *Numero do Comodato:* {record.nro_comodato or '-'}")
            lines.append(f"*Material:* {record.material or '-'}")
            lines.append(f"*Sub Tipo Material:* {record.sub_tipo_material or '-'}")
            lines.append(f"*Saldo:* {record.saldo or '0'}")

        lines.append("")
        lines.append("*Atalho para recolha:*")
        lines.append("- Envie RECOLHA para abrir a solicitacao desse cliente.")
        lines.append("- Envie RECOLHA TODOS para pedir a recolha de todos os comodatos.")
        lines.append("- Envie RECOLHA 1,3 para pedir itens especificos da lista.")
        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_giro_response(
        self,
        records: list[GiroClientRecord],
        criteria: str,
        scope_restricted: bool = True,
    ) -> OutgoingMessage:
        if not records:
            scope_note = "dentro do acesso liberado para o seu numero" if scope_restricted else "no relatorio de giro importado"
            return OutgoingMessage(
                text=(
                    f"Nao encontrei dados de giro para {criteria} {scope_note}.\n"
                    "Obs.: esse giro e de vasilhame.\n"
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        lines = [f"Encontrei {len(records)} registro(s) de giro para {criteria}."]
        lines.append("*Tipo de giro:* Vasilhame")
        lines.append(f"*Planilha atualizada em:* {records[0].planilha_atualizada_em or '-'}")
        for index, record in enumerate(records, start=1):
            total_caixas = _format_quantity(
                _sum_formatted_amounts(
                    record.total_litrinho,
                    record.total_inteira,
                    record.total_litrao,
                )
            )
            caixas_faltando = _format_quantity(
                _sum_formatted_amounts(
                    record.gap_litrinho,
                    record.gap_inteira,
                    record.gap_litrao,
                )
            )
            gap_detail = _format_giro_gap_detail(record)
            lines.append("")
            lines.append(f"{index}. *{record.nome or '-'}* | Cod {record.cod_pdv or '-'}")
            lines.append(f"*Revenda:* {_format_filial_label(record.filial)} | *Setor:* {record.setor or '-'}")
            lines.append(f"*Base:* {total_caixas} | *Falta:* {caixas_faltando}")
            if gap_detail:
                lines.append(f"*Tipo:* {gap_detail}")
            lines.append(
                "Litrinho: "
                f"Base {_format_quantity(record.total_litrinho)} | "
                f"Faltam {_format_quantity(record.gap_litrinho)} | "
                f"Status {record.giro_litrinho}"
            )
            lines.append(
                "Inteira: "
                f"Base {_format_quantity(record.total_inteira)} | "
                f"Faltam {_format_quantity(record.gap_inteira)} | "
                f"Status {record.giro_inteira}"
            )
            lines.append(
                "Litrao: "
                f"Base {_format_quantity(record.total_litrao)} | "
                f"Faltam {_format_quantity(record.gap_litrao)} | "
                f"Status {record.giro_litrao}"
            )

        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_visit_day_clients_response(
        self,
        visit_day: str,
        records: list[DClienteRecord],
        decision: AccessDecision,
        financial_alerts: list[InadimplenciaVisitAlert],
        alerts_note: str,
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei clientes para o dia '{visit_day_label}'.\n"
                    "Se quiser tentar outra consulta, envie MENU."
                )
            )

        visit_summaries = self._load_visit_day_seller_summaries(decision, visit_day)
        lines = [f"Rota em {visit_day_label}"]
        lines.append(
            f"Setores na rota: {len(visit_summaries)} | Visitas: {len(records)}"
            if visit_summaries
            else f"Visitas: {len(records)}"
        )
        lines.append(f"Atualizado em: {records[0].ultima_atualizacao_tabela or '-'}")
        lines.append("")
        for index, record in enumerate(records, start=1):
            client_name = record.nome_fantasia or record.razao_social or "-"
            lines.append(f"{index}. {client_name} | Cod {record.cod_pdv} | Setor {record.vendedor or '-'}")
        self._append_visit_financial_section(lines, financial_alerts, alerts_note)
        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _load_visit_day_seller_summaries(
        self,
        decision: AccessDecision,
        visit_day: str,
        *,
        limit: int = 1000,
    ) -> list[VisitSellerSummary]:
        try:
            return self.query_service.list_visit_day_seller_summaries(
                visit_day=visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=limit,
            )
        except RuntimeError:
            return []

    def _build_visit_day_seller_clients_response(
        self,
        visit_day: str,
        summary: VisitSellerSummary,
        records: list[DClienteRecord],
        decision: AccessDecision,
        financial_alerts: list[InadimplenciaVisitAlert],
        alerts_note: str,
    ) -> OutgoingMessage:
        visit_day_label = _format_visit_day_label(visit_day)
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei visitas para {_format_sector_scope_label(summary.seller_code)} no dia '{visit_day_label}'.\n"
                    f"{_format_gv_scope_label(summary.manager_code)} | Total no resumo: {summary.visit_count} visita(s)\n"
                    "Se quiser tentar outra consulta, envie MENU."
                )
            )

        lines = [
            f"Clientes de {_format_sector_scope_label(summary.seller_code)} no dia '{visit_day_label}':",
            f"{_format_gv_scope_label(summary.manager_code)} | {summary.visit_count} visita(s)",
            f"Atualizado em: {records[0].ultima_atualizacao_tabela or '-'}",
        ]
        for index, record in enumerate(records, start=1):
            client_name = record.nome_fantasia or record.razao_social or "-"
            lines.append(f"{index}. {client_name} | Cod {record.cod_pdv}")
        self._append_visit_financial_section(lines, financial_alerts, alerts_note)
        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_visit_day_giro_summaries(
        self,
        decision: AccessDecision,
        records: list[DClienteRecord],
    ) -> tuple[dict[tuple[str, str], tuple[str, str, str, str]], str]:
        status = self.giro_service.status()
        if not status["ready"]:
            return {}, ""

        summaries: dict[tuple[str, str], tuple[str, str, str, str]] = {}
        updated_at = ""
        for record in records:
            filial = _normalize_filial(record.filial)
            cod_pdv = _normalize_cod_pdv(record.cod_pdv)
            if not filial or not cod_pdv:
                continue
            key = (filial, cod_pdv)
            if key in summaries:
                continue
            try:
                giro_records = self.giro_service.search_by_registration(
                    filial=filial,
                    cod_pdv=cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=1,
                )
            except RuntimeError:
                continue
            if not giro_records:
                continue
            giro_record = giro_records[0]
            total_caixas = _format_quantity(
                _sum_formatted_amounts(
                    giro_record.total_litrinho,
                    giro_record.total_inteira,
                    giro_record.total_litrao,
                )
            )
            gap_caixas = _format_quantity(
                _sum_formatted_amounts(
                    giro_record.gap_litrinho,
                    giro_record.gap_inteira,
                    giro_record.gap_litrao,
                )
            )
            gap_detail = _format_giro_gap_detail(giro_record)
            summaries[key] = (giro_record.setor or "", total_caixas, gap_caixas, gap_detail)
            updated_at = updated_at or (giro_record.planilha_atualizada_em or "")
        return summaries, updated_at

    def _load_visit_day_financial_alerts(
        self,
        decision: AccessDecision,
        visit_day: str,
        seller_code: str = "",
        manager_code: str = "",
    ) -> tuple[list[InadimplenciaVisitAlert], str]:
        status = self.inadimplencia_service.status()
        if not status["ready"]:
            return [], "Nao consegui consultar os boletos agora."
        try:
            alerts = self.inadimplencia_service.list_upcoming_by_visit_day(
                visit_day=visit_day,
                seller_code=seller_code or None,
                manager_code=manager_code or None,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=80,
            )
        except Exception:
            logger.exception(
                "Falha ao consultar boletos por dia de visita",
                extra={
                    "visit_day": visit_day,
                    "seller_code": seller_code,
                    "manager_code": manager_code,
                    "roles": list(decision.roles),
                },
            )
            return [], "Nao consegui consultar os boletos agora."
        return alerts, ""

    def _append_visit_financial_section(
        self,
        lines: list[str],
        alerts: list[InadimplenciaVisitAlert],
        alerts_note: str,
    ) -> None:
        lines.append("")
        lines.append("*Atencao Financeira desse dia:*")
        if alerts_note:
            lines.append(alerts_note)
            return
        if not alerts:
            lines.append("Nenhum cliente dessa rota esta vencendo em 2, 1, 0 dias ou ja inadimplente.")
            return

        lines.append(f"Planilha atualizada em: {alerts[0].planilha_atualizada_em or '-'}")
        overdue = [alert for alert in alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in alerts if alert.nearest_days_to_due == 0]
        due_tomorrow = [alert for alert in alerts if alert.nearest_days_to_due == 1]
        due_in_two_days = [alert for alert in alerts if alert.nearest_days_to_due == 2]

        self._append_visit_financial_group(lines, "Ja inadimplentes", overdue)
        self._append_visit_financial_group(lines, "Vence hoje", due_today)
        self._append_visit_financial_group(lines, "Vence amanha", due_tomorrow)
        self._append_visit_financial_group(lines, "Vence em 2 dias", due_in_two_days)

    def _append_visit_financial_group(
        self,
        lines: list[str],
        label: str,
        alerts: list[InadimplenciaVisitAlert],
    ) -> None:
        if not alerts:
            return
        lines.append(
            f"{label}: {len(alerts)} cliente(s) | "
            f"R$ {_sum_money_values(alert.total_pendente for alert in alerts)}"
        )
        for index, alert in enumerate(alerts, start=1):
            lines.append(
                f"{index}. Codigo {alert.cod_pdv} | {alert.nome or '-'} | "
                f"{alert.title_count} titulo(s) | R$ {alert.total_pendente} | "
                f"{_format_visit_financial_status(alert.nearest_days_to_due)}"
            )

    def _display_role(self, role_name: str) -> str:
        return {
            ROLE_VENDEDOR: "Vendedor",
            ROLE_GERENTE_VENDAS: "Gerente de Vendas",
            ROLE_DIRETOR_COMERCIAL: "Diretor Comercial",
            ROLE_ADMIN: "Admin",
            ROLE_FINANCEIRO: "Financeiro",
        }.get(role_name, role_name.title())

    def _build_scope_prompt(self, role_name: str) -> str:
        if role_name == ROLE_GERENTE_VENDAS:
            return (
                f"Cargo {self._display_role(role_name)} selecionado.\n"
                "Agora me envie o numero do GV ou varios numeros separados por virgula.\n"
                "Exemplo: 2 ou 2,5"
            )
        if role_name == ROLE_DIRETOR_COMERCIAL:
            return (
                f"Cargo {self._display_role(role_name)} selecionado.\n"
                "Agora me envie a chave filial-DC ou varias chaves separadas por virgula.\n"
                "Exemplo: 3-1 ou 3-1,4-1"
            )
        if role_name == ROLE_FINANCEIRO:
            return (
                f"Cargo {self._display_role(role_name)} selecionado.\n"
                "Agora me envie a filial ou varias filiais separadas por virgula.\n"
                "Exemplo: 3 ou 3,4"
            )
        return (
            f"Cargo {self._display_role(role_name)} selecionado.\n"
            "Agora me envie a chave filial-setor ou as chaves separadas por virgula.\n"
            "Exemplo: 1-206 ou 1-206,3-107"
        )

    def _build_scope_retry_prompt(self, role_name: str) -> str:
        if role_name == ROLE_GERENTE_VENDAS:
            return (
                "Para esse cargo, preciso de pelo menos um numero de GV valido.\n"
                "Envie nesse formato: 2 ou 2,5"
            )
        if role_name == ROLE_DIRETOR_COMERCIAL:
            return (
                "Para esse cargo, preciso de pelo menos uma chave filial-DC valida.\n"
                "Envie nesse formato: 3-1 ou 3-1,4-1"
            )
        if role_name == ROLE_FINANCEIRO:
            return (
                "Para esse cargo, preciso de pelo menos uma filial valida.\n"
                "Envie nesse formato: 3 ou 3,4"
            )
        return (
            "Para esse cargo, preciso de pelo menos uma chave filial-setor valida.\n"
            "Envie nesse formato: 1-206 ou 1-206,3-107"
        )

    def _build_scope_not_found_prompt(self, role_name: str, codes: list[str]) -> str:
        joined_codes = ", ".join(codes) if codes else "-"
        if role_name == ROLE_GERENTE_VENDAS:
            return (
                f"Nao encontrei base para o(s) GV(s): {joined_codes}.\n"
                "Confira os numeros e envie novamente.\n"
                "Exemplo: 2 ou 2,5"
            )
        if role_name == ROLE_DIRETOR_COMERCIAL:
            joined_codes = _format_gv_vdes(tuple(codes), role_name=ROLE_DIRETOR_COMERCIAL) if codes else "-"
            return (
                f"Nao encontrei base para o(s) diretor(es): {joined_codes}.\n"
                "Confira as chaves e envie novamente.\n"
                "Exemplo: 3-1 ou 3-1,4-1"
            )
        if role_name == ROLE_FINANCEIRO:
            return self._build_scope_retry_prompt(role_name)
        return self._build_scope_retry_prompt(role_name)

    def _resolve_admin_scope_codes(self, text: str, role_name: str) -> tuple[list[str], str | None]:
        if role_name == ROLE_VENDEDOR:
            scope_codes = _parse_scope_code_list(text, role_name)
            if not scope_codes:
                return [], self._build_scope_retry_prompt(role_name)
            return scope_codes, None
        if role_name == ROLE_FINANCEIRO:
            scope_codes = _parse_scope_code_list(text, role_name)
            if not scope_codes:
                return [], self._build_scope_retry_prompt(role_name)
            return scope_codes, None
        if role_name == ROLE_DIRETOR_COMERCIAL:
            scope_codes = _parse_scope_code_list(text, role_name)
            if not scope_codes:
                return [], self._build_scope_retry_prompt(role_name)
            try:
                matching_gvs = self.query_service.list_gv_vdes(
                    allowed_gv_vdes=scope_codes,
                    limit=1,
                )
            except RuntimeError:
                return [], "Nao consegui consultar a base agora.\nTente novamente em instantes."
            if not matching_gvs:
                return [], self._build_scope_not_found_prompt(role_name, scope_codes)
            return scope_codes, None

        base_codes = _parse_management_scope_code_list(text)
        if not base_codes:
            return [], self._build_scope_retry_prompt(role_name)

        try:
            if role_name == ROLE_GERENTE_VENDAS:
                scope_codes = self.query_service.expand_gv_scope_codes(base_codes)
            else:
                return [], self._build_scope_retry_prompt(role_name)
        except RuntimeError:
            return [], "Nao consegui consultar a base agora.\nTente novamente em instantes."

        if not scope_codes:
            return [], self._build_scope_not_found_prompt(role_name, base_codes)
        return scope_codes, None

    def _format_user_access_label(
        self,
        roles: tuple[str, ...],
        sectors: tuple[str, ...],
        gv_vdes: tuple[str, ...],
    ) -> str:
        if ROLE_ADMIN in roles:
            return "acesso total"
        if ROLE_FINANCEIRO in roles:
            return f"Filiais liberadas: {_format_finance_filiais(sectors)}"
        if ROLE_DIRETOR_COMERCIAL in roles:
            return f"DCs sob responsabilidade: {_format_gv_vdes(gv_vdes, role_name=ROLE_DIRETOR_COMERCIAL)}"
        if ROLE_GERENTE_VENDAS in roles:
            return f"GVs liberados: {_format_gv_vdes(gv_vdes, role_name=ROLE_GERENTE_VENDAS)}"
        if ROLE_VENDEDOR in roles:
            return f"Setores liberados: {_format_sectors(sectors)}"
        return "-"

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
            r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
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
            r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
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
    if {"emitir", "criar", "gerar", "nova", "novo"} & tokens and {"cobranca", "cobrancas"} & tokens:
        return "create_charge"
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
