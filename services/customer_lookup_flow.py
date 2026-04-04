from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any

from bot_api.commercial_scope import (
    extract_scope_input_tokens,
    format_dc_scope,
    format_gv_scope,
    format_scope_list,
    format_sector_scope,
    normalize_dc_scope_input,
    normalize_numeric_code,
    normalize_gv_scope_input,
    normalize_sector_scope_input,
    normalize_stored_scope_value,
    split_scope_pair,
)
from bot_api.models import IncomingMessage, InteractiveOption, OutgoingMessage
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
from bot_api.services.comodatos_query_service import (
    ComodatoClientSummary,
    ComodatoRecord,
    ComodatosQueryService,
)
from bot_api.services.giro_query_service import (
    GiroClientRecord,
    GiroFilialSummary,
    GiroManagementSummary,
    GiroQueryService,
    GiroScopeSummary,
)
from bot_api.services.inadimplencia_query_service import (
    InadimplenciaClientSummary,
    InadimplenciaFinanceManagementSummary,
    InadimplenciaQueryService,
    InadimplenciaRecord,
    InadimplenciaVisitAlert,
    InadimplenciaVisitRiskSummary,
)

MENU_SEARCH = "menu:buscar_cliente"
MENU_INADIMPLENCIA = "menu:inadimplencia"
MENU_COMODATOS = "menu:comodatos"
MENU_GIRO = "menu:giro"
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

FANTASIA_PICK_PREFIX = "fantasia:pick:"
INADIMPLENCIA_CLIENT_PICK_PREFIX = "inadclient:pick:"
INADIMPLENCIA_PAGE_NEXT = "inadclient:page:next"
INADIMPLENCIA_PAGE_PREV = "inadclient:page:prev"
FINANCE_VISIT_RISK_PICK_PREFIX = "finance:visit_risk:pick:"
VISIT_DAY_PICK_PREFIX = "visitday:pick:"
VISIT_SELLER_PICK_PREFIX = "visitseller:pick:"
INADIMPLENCIA_HEADER_PREFIX = "inadimplencia:header:"
INADIMPLENCIA_SCOPE_LIST_PREFIX = "inadimplencia:scope:"
INADIMPLENCIA_PAGE_SIZE = 20
INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL = "finance_base_total"
INADIMPLENCIA_CONTEXT_SCOPE_BASE = "scope_base"
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


@dataclass
class LookupSession:
    step: str = "idle"
    search_context: str = "cliente"
    return_menu: str = ""
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
    finance_gv_options: tuple[str, ...] = ()
    summary_filial_options: tuple[str, ...] = ()
    visit_risk_day_options: tuple[str, ...] = ()
    visit_risk_summaries: tuple[InadimplenciaVisitRiskSummary, ...] = ()
    selected_visit_risk_token: str = ""
    selected_visit_risk_label: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CustomerLookupFlow:
    def __init__(
        self,
        query_service: DClientesQueryService,
        inadimplencia_service: InadimplenciaQueryService,
        comodatos_service: ComodatosQueryService,
        giro_service: GiroQueryService,
        access_control: AccessControl,
        session_ttl_minutes: int = 20,
    ) -> None:
        self.query_service = query_service
        self.inadimplencia_service = inadimplencia_service
        self.comodatos_service = comodatos_service
        self.giro_service = giro_service
        self.access_control = access_control
        self.session_ttl = timedelta(minutes=max(session_ttl_minutes, 5))
        self.sessions: dict[str, LookupSession] = {}
        self._lock = RLock()

    def handle(self, incoming: IncomingMessage, decision: AccessDecision) -> OutgoingMessage:
        with self._lock:
            return self._handle_locked(incoming, decision)

    def _handle_locked(self, incoming: IncomingMessage, decision: AccessDecision) -> OutgoingMessage:
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

        if session.step.startswith("admin_"):
            return self._handle_admin_session(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if session.step.startswith("finance_"):
            return self._handle_finance_session(
                sender=incoming.sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )

        if _is_back_menu_command(normalized) and not _uses_inadimplencia_page_navigation(session):
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
            self._reset_session(incoming.sender)
            session = LookupSession()
            session.updated_at = datetime.now(timezone.utc)

        if session.step == "awaiting_search_mode":
            readiness_error = self._ensure_search_context_ready(session.search_context, decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
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
                if session.search_context in {"inadimplencia", "comodato"}:
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
                return OutgoingMessage(
                    text=(
                        "Digite o CPF ou CNPJ do cliente.\n"
                        "Nessa busca, voce pode consultar sem depender de setor ou GV."
                    )
                )
            if session.search_context == "inadimplencia" and normalized in {
                SEARCH_BY_INADIMPLENTES_BASE,
                "4",
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
            self.sessions[incoming.sender] = session
            return self._build_search_menu(
                search_context=session.search_context,
                decision=decision,
                invalid_selection=True,
            )

        if normalized == MENU_INADIMPLENCIA or (
            session.step == "idle"
            and normalized in {"2", "inadimplencia", "inadimplência", "inadimplente", "devedor", "cobranca", "cobrança"}
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
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="inadimplencia", decision=decision)

        giro_numeric_shortcut = (
            "5"
            if not (self._can_use_gv_summary_menu(decision) or self._can_use_seller_summary_menu(decision))
            else "8"
        )
        giro_numeric_aliases = {giro_numeric_shortcut}
        if giro_numeric_shortcut == "5":
            giro_numeric_aliases.add("8")
        if normalized == MENU_GIRO or (
            session.step == "idle"
            and normalized in {*giro_numeric_aliases, "giro", "menu giro", "consultar giro"}
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
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="giro", decision=decision)

        if normalized == MENU_FINANCEIRO or (
            session.step == "idle"
            and normalized in {"4", "financeiro", "financeiro menu", "menu financeiro"}
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
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_finance_menu()

        if normalized == MENU_VISIT_DAY or (
            session.step == "idle"
            and normalized in {"3", "visitas do dia", "visitas", "dia de visita", "dia de visita do vde"}
            and self._can_use_visit_menu(decision)
        ):
            access_error = self._ensure_scoped_lookup_access(decision, search_context="inadimplencia")
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
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
            and normalized in {
                "5",
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
            and normalized in {"5", "resumo da carteira", "resumo carteira", "minha carteira", "meu resumo"}
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
            and normalized in {
                "6",
                "risco da carteira",
                "clientes com risco hoje",
                "risco hoje",
                "rota com risco",
                "clientes da rota com risco",
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
            and (
                normalized in {"comodato", "comodatos", "pendencia de comodato", "pendencias de comodato"}
                or (normalized == "3" and not self._can_use_visit_menu(decision))
                or (normalized == "4" and self._can_use_visit_menu(decision))
            )
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
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context="comodato", decision=decision)

        if normalized == MENU_ADMIN_ACCESS or (
            session.step == "idle"
            and normalized in {"0", "admin", "administrador", "cadastro_usuario"}
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
            "awaiting_visit_seller_selection",
        }:
            access_error = None
            if session.step in {"awaiting_visit_day_selection", "awaiting_visit_seller_selection"}:
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
                self._reset_session(incoming.sender)
                return self._run_registration_lookup(
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
                self._reset_session(incoming.sender)
                return self._run_registration_lookup(
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
            self._reset_session(incoming.sender)
            return self._run_registration_lookup(
                decision=decision,
                search_context=session.search_context,
                filial=session.filial,
                cod_pdv=cod_pdv,
            )

        if session.step == "awaiting_fantasia":
            query_text = text.strip()
            if len(query_text) < 3:
                self.sessions[incoming.sender] = session
                return OutgoingMessage(text="Digite pelo menos 3 letras do nome do cliente.")
            if session.search_context == "inadimplencia":
                summaries = self.inadimplencia_service.search_client_summaries_by_name(
                    query_text=query_text,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                if not summaries:
                    session.updated_at = datetime.now(timezone.utc)
                    self.sessions[incoming.sender] = session
                    return OutgoingMessage(
                        text=(
                            f"Nao encontrei cliente com '{query_text}' na inadimplencia.\n"
                            "Pode me enviar outro trecho ou, se preferir, digite MENU."
                        )
                    )
                session.step = "awaiting_inadimplencia_client_selection"
                session.fantasia_query = query_text
                session.inadimplencia_client_summaries = tuple(summaries)
                session.inadimplencia_total_available = len(summaries)
                session.inadimplencia_list_context = ""
                session.inadimplencia_page = 1
                session.inadimplencia_page_size = INADIMPLENCIA_PAGE_SIZE
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_inadimplencia_client_menu(query_text=query_text, summaries=summaries)
            if session.search_context == "comodato":
                summaries = self.comodatos_service.search_client_summaries_by_name(
                    query_text=query_text,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                if not summaries:
                    session.updated_at = datetime.now(timezone.utc)
                    self.sessions[incoming.sender] = session
                    return OutgoingMessage(
                        text=(
                            f"Nao encontrei cliente com '{query_text}' nos comodatos pendentes.\n"
                            "Pode me enviar outro trecho ou, se preferir, digite MENU."
                        )
                    )
                session.step = "awaiting_comodato_client_selection"
                session.fantasia_query = query_text
                session.comodato_client_summaries = tuple(summaries)
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_comodato_client_menu(query_text=query_text, summaries=summaries)
            records = self.query_service.search_by_fantasia(
                query_text=query_text,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
            if not records:
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return OutgoingMessage(
                    text=(
                        f"Nao encontrei cliente com '{query_text}' no nome.\n"
                        "Pode me enviar outro trecho ou, se preferir, digite MENU."
                    )
                )
            session.step = "awaiting_fantasia_selection"
            session.fantasia_query = query_text
            session.fantasia_results = tuple(records)
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_fantasia_results_menu(query_text=query_text, records=records)

        if session.step == "awaiting_fantasia_selection":
            selected_record = _select_fantasia_record(text=text, normalized=normalized, records=session.fantasia_results)
            if selected_record is None:
                self.sessions[incoming.sender] = session
                return self._build_fantasia_results_menu(
                    query_text=session.fantasia_query,
                    records=list(session.fantasia_results),
                    invalid_selection=True,
                )
            if session.search_context == "giro":
                records = self.giro_service.search_by_registration(
                    filial=selected_record.filial,
                    cod_pdv=selected_record.cod_pdv,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=20,
                )
                return self._with_post_result_navigation(
                    incoming.sender,
                    session,
                    self._build_giro_response(
                        records,
                        criteria=(
                            f"nome fantasia contendo '{session.fantasia_query}'"
                            f" | revenda {selected_record.filial} | NB {selected_record.cod_pdv}"
                        ),
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
                ),
                return_menu="search_results",
            )

        if session.step == "awaiting_inadimplencia_client_selection":
            page_action = _parse_inadimplencia_page_action(normalized, session.inadimplencia_page_size)
            if session.inadimplencia_list_context in {
                INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL,
                INADIMPLENCIA_CONTEXT_SCOPE_BASE,
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
                    invalid_selection=True,
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
            normalized_document = _normalize_document(text)
            if not normalized_document:
                self.sessions[incoming.sender] = session
                return OutgoingMessage(text="Digite um CPF ou CNPJ valido, com 11 ou 14 numeros.")
            if session.search_context == "inadimplencia":
                records = self.inadimplencia_service.search_by_document(
                    document=normalized_document,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=50,
                )
                self._reset_session(incoming.sender)
                return self._build_inadimplencia_response(records, f"CPF/CNPJ {normalized_document}")
            if session.search_context == "comodato":
                records = self.comodatos_service.search_by_document(
                    document=normalized_document,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=50,
                )
                self._reset_session(incoming.sender)
                return self._build_comodato_response(records, f"CPF/CNPJ {normalized_document}")
            if session.search_context == "giro":
                records = self._search_giro_by_document(decision, normalized_document)
                self._reset_session(incoming.sender)
                return self._build_giro_response(
                    records,
                    f"CPF/CNPJ {normalized_document}",
                    scope_restricted=False,
                )
            records = self.query_service.search_by_document(
                document=normalized_document,
                limit=20,
            )
            self._reset_session(incoming.sender)
            return self._build_search_response(
                records,
                f"CPF/CNPJ {normalized_document}",
                scope_restricted=False,
            )

        if session.step == "awaiting_visit_day_selection":
            selected_visit_day = _select_visit_day(
                text=text,
                normalized=normalized,
                visit_days=session.visit_day_options,
            )
            if selected_visit_day is None:
                self.sessions[incoming.sender] = session
                return self._build_visit_day_menu(
                    decision=decision,
                    visit_days=list(session.visit_day_options),
                    invalid_selection=True,
                )
            if self._uses_grouped_visit_flow(decision):
                visit_summaries = self.query_service.list_visit_day_seller_summaries(
                    visit_day=selected_visit_day,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=100,
                )
                session.step = "awaiting_visit_seller_selection"
                session.selected_visit_day = selected_visit_day
                session.visit_seller_summaries = tuple(visit_summaries)
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_visit_day_manager_menu(selected_visit_day, visit_summaries)
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
                incoming.sender,
                session,
                self._build_visit_day_clients_response(
                    selected_visit_day,
                    records,
                    financial_alerts=financial_alerts,
                    alerts_note=alerts_note,
                ),
                return_menu="visit_day_menu",
            )

        if session.step == "awaiting_visit_seller_selection":
            selected_summary = _select_visit_seller_summary(
                text=text,
                normalized=normalized,
                summaries=session.visit_seller_summaries,
            )
            if selected_summary is None:
                self.sessions[incoming.sender] = session
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
                    invalid_selection=True,
                )
            visit_day_token = _visit_day_token_from_label(selected_visit_risk_day)
            if not visit_day_token:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    invalid_selection=True,
                )
            return self._open_manager_visit_risk_selection(
                sender=incoming.sender,
                session=session,
                decision=decision,
                visit_day_token=visit_day_token,
                visit_day_label=selected_visit_risk_day,
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
                    list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
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
                return self._build_finance_visit_risk_day_menu(
                    visit_days=list(session.visit_risk_day_options),
                    invalid_selection=True,
                )
            visit_day_token = _visit_day_token_from_label(selected_visit_risk_day)
            if not visit_day_token:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_day_menu(
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
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_finance_visit_risk_menu(
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
                return self._build_finance_visit_risk_menu(
                    visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                    summaries=list(session.visit_risk_summaries),
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
            return self._run_registration_lookup(
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
            records = self.query_service.search_by_document(
                document=direct_document,
                limit=20,
            )
            return self._build_search_response(
                records,
                f"CPF/CNPJ {direct_document}",
                scope_restricted=False,
            )

        if normalized in {MENU_SEARCH, "1", "buscar cliente", "buscar"}:
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

        if session.step == "awaiting_inadimplencia_client_selection" and not _uses_inadimplencia_page_navigation(session):
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

        if session.step in {"awaiting_search_mode", "awaiting_visit_day_selection"}:
            self._reset_session(sender)
            return self._build_main_menu(decision)

        if session.step == "awaiting_visit_seller_selection":
            session.step = "awaiting_visit_day_selection"
            session.visit_seller_summaries = ()
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                try:
                    visit_days = self.query_service.list_visit_days(
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                        limit=10,
                    )
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

        if session.step == "manager_select_visit_risk_sector":
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

        return None

    def _resume_post_result_navigation(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        return_menu = session.return_menu
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

        if return_menu == "visit_day_seller":
            session.step = "awaiting_visit_seller_selection"
            session.return_menu = ""
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            if not session.visit_seller_summaries:
                return self._build_visit_day_menu(decision=decision, visit_days=list(session.visit_day_options))
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
            return self._build_finance_visit_risk_menu(
                visit_day_label=session.selected_visit_risk_label or _current_visit_day_label(),
                summaries=list(session.visit_risk_summaries),
            )

        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _store_post_result_navigation(
        self,
        sender: str,
        session: LookupSession,
        *,
        return_menu: str,
    ) -> None:
        session.step = "awaiting_post_result_navigation"
        session.return_menu = return_menu
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session

    def _with_post_result_navigation(
        self,
        sender: str,
        session: LookupSession,
        outgoing: OutgoingMessage,
        *,
        return_menu: str,
    ) -> OutgoingMessage:
        self._store_post_result_navigation(sender, session, return_menu=return_menu)
        if outgoing.kind != "text":
            return outgoing

        normalized_text = _normalize_choice(outgoing.text)
        hint = _result_hint_text(allow_back=True)
        if "envie a ou ant" in normalized_text:
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
            if role_name in {ROLE_ADMIN, ROLE_FINANCEIRO}:
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

    def _handle_finance_session(
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
            if session.step in {
                "finance_select_due_bucket",
                "finance_select_visit_risk_day",
                "finance_select_gv_summary",
                "finance_select_giro_mode",
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

        if session.step == "finance_select_action":
            action = _parse_finance_action(normalized)
            if not action:
                self.sessions[sender] = session
                return self._build_finance_menu(invalid_selection=True)

            if action == "summary":
                return self._with_post_result_navigation(
                    sender,
                    session,
                    self._build_finance_summary_response(decision),
                    return_menu="finance_menu",
                )

            if action == "list":
                return self._open_inadimplencia_summary_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    order_by="total_pendente",
                    header_text="Esses sao os clientes inadimplentes da base total.",
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
                session.step = "finance_select_giro_mode"
                session.updated_at = datetime.now(timezone.utc)
                self.sessions[sender] = session
                return self._build_finance_giro_menu()

            session.step = "finance_select_due_bucket"
            session.updated_at = datetime.now(timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_due_menu()

        if session.step == "finance_select_due_bucket":
            due_bucket = _parse_finance_due_bucket(normalized)
            if not due_bucket:
                self.sessions[sender] = session
                return self._build_finance_due_menu(invalid_selection=True)

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

    def _has_unrestricted_lookup_access(self, decision: AccessDecision) -> bool:
        return self._is_admin(decision) or self._is_financeiro(decision)

    def _uses_grouped_visit_flow(self, decision: AccessDecision) -> bool:
        return self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)

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
            return OutgoingMessage(
                text=(
                    "Seu numero ainda nao esta liberado com um escopo comercial para esse tipo de consulta.\n"
                    "Para buscar por filial, codigo, nome ou visitas do dia, peca esse ajuste ao responsavel.\n"
                    "Se preferir, voce pode consultar por CPF ou CNPJ."
                )
            )
        return None

    def _build_main_menu(self, decision: AccessDecision, invalid_selection: bool = False) -> OutgoingMessage:
        can_use_cliente = self._has_area_access(decision, "cliente")
        can_use_inadimplencia = self._has_area_access(decision, "inadimplencia")
        can_use_comodato = self._has_area_access(decision, "comodato")
        can_use_giro = can_use_cliente
        can_use_visit_menu = self._can_use_visit_menu(decision) and can_use_cliente
        can_use_finance_menu = self._can_use_finance_menu(decision) and can_use_inadimplencia
        can_use_gv_summary_menu = self._can_use_gv_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_summary_menu = self._can_use_seller_summary_menu(decision) and can_use_inadimplencia
        can_use_seller_risk_menu = self._can_use_seller_risk_menu(decision) and can_use_inadimplencia
        giro_shortcut = "5" if not (can_use_gv_summary_menu or can_use_seller_summary_menu) else "8"

        options: list[InteractiveOption] = []
        if can_use_cliente:
            options.append(
                InteractiveOption(
                    option_id=MENU_SEARCH,
                    title="Buscar Cliente",
                    description="Consultar clientes",
                    shortcut="1",
                )
            )
        if can_use_inadimplencia:
            options.append(
                InteractiveOption(
                    option_id=MENU_INADIMPLENCIA,
                    title="Inadimplencia",
                    description="Ver titulos em aberto",
                    shortcut="2",
                )
            )
        if can_use_giro:
            options.append(
                InteractiveOption(
                    option_id=MENU_GIRO,
                    title="Giro",
                    description="Consultar giro por cliente",
                    shortcut=giro_shortcut,
                )
            )
        footer = "Escolha como voce quer consultar."
        if can_use_visit_menu:
            options.append(
                InteractiveOption(
                    option_id=MENU_VISIT_DAY,
                    title="Visitas do Dia",
                    description="Ver visitas programadas",
                    shortcut="3",
                )
            )
        if can_use_comodato:
            options.append(
                InteractiveOption(
                    option_id=MENU_COMODATOS,
                    title="Comodatos",
                    description="Ver comodatos pendentes",
                    shortcut="4" if can_use_visit_menu else "3",
                )
            )
        if can_use_visit_menu and can_use_comodato:
            footer = "Voce tambem pode consultar as visitas do dia e os comodatos pendentes."
        elif can_use_visit_menu:
            footer = "Voce tambem pode consultar as visitas do dia."
        elif can_use_comodato:
            footer = "Voce tambem pode consultar os comodatos pendentes."
        if can_use_gv_summary_menu:
            summary_title = "Resumo da Gerencia"
            summary_description = "Ver um resumo rapido do seu GV"
            summary_footer = "Voce tambem pode consultar as visitas do dia, os comodatos pendentes e o resumo da sua gerencia."
            summary_option_id = MENU_GV_SUMMARY
            if self._is_diretor_comercial(decision):
                summary_title = "Resumo dos Gerentes"
                summary_description = "Ver o total e detalhar por revenda"
                summary_footer = "Voce tambem pode consultar as visitas do dia, os comodatos pendentes e o resumo total ou por revenda dos seus gerentes."
            elif self._is_gerente_vendas(decision):
                summary_title = "Gerente de Vendas"
                summary_description = "Resumo total ou por filial"
                summary_footer = "Voce tambem pode consultar as visitas do dia, os comodatos pendentes e o menu do gerente de vendas."
                summary_option_id = MENU_MANAGER
            options.append(
                InteractiveOption(
                    option_id=summary_option_id,
                    title=summary_title,
                    description=summary_description,
                    shortcut="5",
                )
            )
            footer = summary_footer
        if can_use_seller_summary_menu:
            options.append(
                InteractiveOption(
                    option_id=MENU_SELLER_SUMMARY,
                    title="Resumo da Carteira",
                    description="Ver um resumo rapido da sua base",
                    shortcut="5",
                )
            )
            if can_use_seller_risk_menu:
                options.append(
                    InteractiveOption(
                        option_id=MENU_SELLER_RISK,
                        title="Risco de Hoje",
                        description="Ver clientes da rota com risco hoje",
                        shortcut="6",
                    )
                )
            footer = "Voce tambem pode consultar as visitas do dia, os comodatos pendentes e o risco da sua rota."
        if can_use_finance_menu:
            options.append(
                InteractiveOption(
                    option_id=MENU_FINANCEIRO,
                    title="Financeiro",
                    description="Ver resumo e cobrancas",
                    shortcut="4",
                )
            )
            footer = "Voce tambem pode consultar os comodatos pendentes e acompanhar o financeiro."
        if self._is_admin(decision):
            options.append(
                InteractiveOption(
                    option_id=MENU_ADMIN_ACCESS,
                    title="Admin",
                    description="Cadastrar ou ajustar acessos",
                    shortcut="0",
                )
            )
            if self._can_use_finance_menu(decision):
                footer = "Como administrador, voce tambem pode acompanhar o financeiro e cuidar dos acessos."
            else:
                footer = "Como administrador, voce tambem pode cuidar dos acessos."
        text = "O que voce deseja fazer?"
        if invalid_selection:
            text = _invalid_option_text("Escolha uma opcao do menu.")
        if not options:
            text = "Seu numero esta ativo, mas ainda nao encontrei menus liberados para ele.\nPeca a liberacao ao responsavel e tente novamente."
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
        }
        context_label = context_label_map.get(search_context, "a consulta")
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
            options.append(
                InteractiveOption(
                    option_id=SEARCH_BY_INADIMPLENTES_BASE,
                    title="Ver inadimplentes",
                    description="Mostrar os clientes da sua base",
                    shortcut="4",
                )
            )
        footer = "Se quiser voltar ao inicio, envie A, ANT ou MENU."
        return OutgoingMessage(
            kind="menu",
            title={
                "cliente": "Buscar Cliente",
                "inadimplencia": "Consultar Inadimplencia",
                "comodato": "Consultar Comodatos",
                "giro": "Consultar Giro",
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

        try:
            client_count = self.inadimplencia_service.count_clients_in_scope(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except RuntimeError:
            return ""

        if self._has_unrestricted_lookup_access(decision):
            return f"Inadimplentes da base total: {client_count} cliente(s)."
        return f"Inadimplentes da sua base: {client_count} cliente(s)."

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
            footer="Voce pode ver resumo, lista, maiores valores, vencimentos, risco de visitas e submenu de giro. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=FINANCE_ACTION_SUMMARY,
                    title="Resumo Financeiro",
                    description="Ver um painel rapido da base",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_LIST,
                    title="Ver Inadimplentes",
                    description="Listar os clientes em aberto",
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
                    title="Visitas com Riscos",
                    description="Escolher o dia e ver os setores com risco",
                    shortcut="5",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_GV_SUMMARY,
                    title="Resumo por GV",
                    description="Escolher a chave filial-GV e ver o resumo",
                    shortcut="6",
                ),
                InteractiveOption(
                    option_id=FINANCE_ACTION_GIRO,
                    title="Giro",
                    description="Abrir o submenu de giro",
                    shortcut="7",
                ),
            ),
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
        return OutgoingMessage(text="\n".join(lines))

    def _build_giro_by_filial_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        summaries = self._safe_giro_summary_by_filial(decision)
        if not summaries:
            return OutgoingMessage(
                text=(
                    "Nao encontrei dados de giro por filial para esse escopo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        lines = [title]
        for summary in sorted(summaries, key=lambda item: _sort_numeric_text(item.filial)):
            lines.append("")
            lines.append(f"*{_format_filial_label(summary.filial)}*")
            self._append_giro_summary_lines(lines, summary, compact=True)
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_giro_by_gv_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        summaries = self._safe_giro_summary_by_gv(decision)
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

        lines = [title]
        for summary in sorted(summaries, key=lambda item: _gv_sort_key(item.manager_code)):
            lines.append("")
            lines.append(f"*{_format_gv_scope_label(summary.manager_code)}*")
            self._append_giro_summary_lines(lines, summary, compact=True)
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

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

    def _append_giro_summary_lines(
        self,
        lines: list[str],
        summary: GiroScopeSummary | None,
        *,
        compact: bool,
    ) -> None:
        if summary is None:
            return

        attention_pct = _format_percent_ratio(summary.attention_count, summary.client_count)
        zero_pct = _format_percent_ratio(summary.zero_count, summary.client_count)
        lines.append(
            f"*Giro:* {summary.client_count} PDV(s) | "
            f"Atencao: {summary.attention_count} ({attention_pct}) | "
            f"Zero: {summary.zero_count} ({zero_pct})"
        )
        litrinho_risk_pct = _format_percent_ratio(
            summary.litrinho_nok_count + summary.litrinho_zero_count,
            summary.litrinho_monitored_count,
        )
        inteira_risk_pct = _format_percent_ratio(
            summary.inteira_nok_count + summary.inteira_zero_count,
            summary.inteira_monitored_count,
        )
        litrao_risk_pct = _format_percent_ratio(
            summary.litrao_nok_count + summary.litrao_zero_count,
            summary.litrao_monitored_count,
        )
        if compact:
            lines.append(
                "Risco por familia: "
                f"Litrinho {litrinho_risk_pct} | "
                f"Inteira {inteira_risk_pct} | "
                f"Litrao {litrao_risk_pct}"
            )
            lines.append(
                "Gaps: "
                f"Litrinho {summary.litrinho_gap_total} | "
                f"Inteira {summary.inteira_gap_total} | "
                f"Litrao {summary.litrao_gap_total}"
            )
            return

        litrinho_ok_pct = _format_percent_ratio(summary.litrinho_ok_count, summary.litrinho_monitored_count)
        litrinho_nok_pct = _format_percent_ratio(summary.litrinho_nok_count, summary.litrinho_monitored_count)
        litrinho_zero_pct = _format_percent_ratio(summary.litrinho_zero_count, summary.litrinho_monitored_count)
        lines.append(
            "Litrinho: "
            f"{summary.litrinho_monitored_count} monitorado(s) | "
            f"OK {summary.litrinho_ok_count} ({litrinho_ok_pct}) | "
            f"NOK {summary.litrinho_nok_count} ({litrinho_nok_pct}) | "
            f"Zero {summary.litrinho_zero_count} ({litrinho_zero_pct}) | "
            f"Gap {summary.litrinho_gap_total}"
        )
        inteira_ok_pct = _format_percent_ratio(summary.inteira_ok_count, summary.inteira_monitored_count)
        inteira_nok_pct = _format_percent_ratio(summary.inteira_nok_count, summary.inteira_monitored_count)
        inteira_zero_pct = _format_percent_ratio(summary.inteira_zero_count, summary.inteira_monitored_count)
        lines.append(
            "Inteira: "
            f"{summary.inteira_monitored_count} monitorado(s) | "
            f"OK {summary.inteira_ok_count} ({inteira_ok_pct}) | "
            f"NOK {summary.inteira_nok_count} ({inteira_nok_pct}) | "
            f"Zero {summary.inteira_zero_count} ({inteira_zero_pct}) | "
            f"Gap {summary.inteira_gap_total}"
        )
        litrao_ok_pct = _format_percent_ratio(summary.litrao_ok_count, summary.litrao_monitored_count)
        litrao_nok_pct = _format_percent_ratio(summary.litrao_nok_count, summary.litrao_monitored_count)
        litrao_zero_pct = _format_percent_ratio(summary.litrao_zero_count, summary.litrao_monitored_count)
        lines.append(
            "Litrao: "
            f"{summary.litrao_monitored_count} monitorado(s) | "
            f"OK {summary.litrao_ok_count} ({litrao_ok_pct}) | "
            f"NOK {summary.litrao_nok_count} ({litrao_nok_pct}) | "
            f"Zero {summary.litrao_zero_count} ({litrao_zero_pct}) | "
            f"Gap {summary.litrao_gap_total}"
        )

    def _build_finance_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        try:
            total_summary = self.inadimplencia_service.get_finance_summary(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            filial_summaries = self.inadimplencia_service.list_finance_summary_by_filial(
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
        filial_giro_summaries = self._safe_giro_summary_by_filial(decision)
        giro_by_filial = {summary.filial: summary for summary in filial_giro_summaries}

        lines = ["Resumo financeiro por filial"]
        lines.append(f"*Base total:* {total_summary.client_count} cliente(s) | R$ {total_summary.total_pendente}")
        lines.append(f"*Ja vencidos:* {total_summary.overdue_count} cliente(s) | R$ {total_summary.overdue_total}")
        lines.append(f"*Vence hoje:* {total_summary.due_today_count} cliente(s) | R$ {total_summary.due_today_total}")
        lines.append(f"*Vence amanha:* {total_summary.due_tomorrow_count} cliente(s) | R$ {total_summary.due_tomorrow_total}")
        lines.append(f"*Vence em 2 dias:* {total_summary.due_in_two_days_count} cliente(s) | R$ {total_summary.due_in_two_days_total}")
        self._append_giro_summary_lines(lines, total_giro_summary, compact=True)
        lines.append(f"*Planilha atualizada em:* {total_summary.planilha_atualizada_em or '-'}")

        for filial_summary in filial_summaries:
            lines.append("")
            lines.append(f"*{_format_filial_label(filial_summary.filial)}*")
            lines.append(f"Clientes inadimplentes: {filial_summary.client_count} | R$ {filial_summary.total_pendente}")
            lines.append(f"Ja vencidos: {filial_summary.overdue_count} | R$ {filial_summary.overdue_total}")
            lines.append(f"Vence hoje: {filial_summary.due_today_count} | R$ {filial_summary.due_today_total}")
            lines.append(f"Vence amanha: {filial_summary.due_tomorrow_count} | R$ {filial_summary.due_tomorrow_total}")
            lines.append(f"Vence em 2 dias: {filial_summary.due_in_two_days_count} | R$ {filial_summary.due_in_two_days_total}")
            self._append_giro_summary_lines(lines, giro_by_filial.get(filial_summary.filial), compact=True)

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_gv_summary_response(
        self,
        decision: AccessDecision,
        gv_vdes_override: tuple[str, ...] | None = None,
        title: str | None = None,
    ) -> OutgoingMessage:
        selected_gv_vdes = tuple(gv_vdes_override or decision.gv_vdes)
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
        return OutgoingMessage(text="\n".join(lines))

    def _build_director_total_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
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
            _, gv_code = split_scope_pair(summary.manager_code) or ("", "")
            if not gv_code:
                continue
            grouped_clients.setdefault(gv_code, []).append(summary)

        grouped_inad: dict[str, list[InadimplenciaFinanceManagementSummary]] = {}
        for summary in inad_summaries:
            _, gv_code = split_scope_pair(summary.manager_code) or ("", "")
            if not gv_code:
                continue
            grouped_inad.setdefault(gv_code, []).append(summary)

        grouped_giro: dict[str, list[GiroManagementSummary]] = {}
        for summary in giro_summaries:
            _, gv_code = split_scope_pair(summary.manager_code) or ("", "")
            if not gv_code:
                continue
            grouped_giro.setdefault(gv_code, []).append(summary)

        ordered_gvs = sorted(set(grouped_clients) | set(grouped_inad) | set(grouped_giro), key=_sort_numeric_text)
        lines = ["Resumo Total da Diretoria Comercial"]
        lines.append(f"*GVs na base:* {len(ordered_gvs)}")

        for gv_code in ordered_gvs:
            client_group = grouped_clients.get(gv_code, [])
            inad_group = grouped_inad.get(gv_code, [])
            giro_summary = _aggregate_giro_scope_summaries(grouped_giro.get(gv_code, []))
            lines.append("")
            lines.append(f"*GV {gv_code}*")
            lines.append(f"Clientes na base: {sum(item.client_count for item in client_group)}")
            lines.append(f"Setores na base: {sum(item.seller_count for item in client_group)}")
            lines.append(
                f"Clientes inadimplentes: {sum(item.client_count for item in inad_group)}"
                f" | R$ {_sum_money_values(item.total_pendente for item in inad_group)}"
            )
            lines.append(
                f"Ja vencidos: {sum(item.overdue_count for item in inad_group)}"
                f" | R$ {_sum_money_values(item.overdue_total for item in inad_group)}"
            )
            lines.append(
                f"Vence hoje: {sum(item.due_today_count for item in inad_group)}"
                f" | R$ {_sum_money_values(item.due_today_total for item in inad_group)}"
            )
            lines.append(
                f"Vence amanha: {sum(item.due_tomorrow_count for item in inad_group)}"
                f" | R$ {_sum_money_values(item.due_tomorrow_total for item in inad_group)}"
            )
            lines.append(
                f"Vence em 2 dias: {sum(item.due_in_two_days_count for item in inad_group)}"
                f" | R$ {_sum_money_values(item.due_in_two_days_total for item in inad_group)}"
            )
            self._append_giro_summary_lines(lines, giro_summary, compact=True)
            client_updated = next((item.planilha_atualizada_em for item in client_group if item.planilha_atualizada_em), "-")
            inad_updated = next((item.planilha_atualizada_em for item in inad_group if item.planilha_atualizada_em), "-")
            giro_updated = giro_summary.planilha_atualizada_em if giro_summary else "-"
            lines.append(f"Atualizado: Clientes {client_updated} | Inadimplencia {inad_updated} | Giro {giro_updated}")

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

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

        lines = ["Ranking dos Gerentes"]
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
                f"Inadimplentes: {inad_summary.client_count if inad_summary else 0} | "
                f"Clientes na base: {client_summary.client_count if client_summary else 0} | "
                f"Setores: {client_summary.seller_count if client_summary else 0}"
            )
            lines.append(
                f"Risco de hoje: {risk_today[0]} cliente(s) | R$ {risk_today[1]}"
            )
            lines.append("")

        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_director_filial_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
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

        lines = ["Resumo por Filial da Diretoria"]
        if current_visit_day:
            lines.append(f"*Risco de hoje considerado:* {current_visit_day}")
        for filial in filial_codes:
            client_summary = client_by_filial.get(filial)
            inad_summary = inad_by_filial.get(filial)
            giro_summary = giro_by_filial.get(filial)
            risk_today = risk_today_by_filial.get(filial, (0, "0,00"))
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
                f"Vence hoje: {inad_summary.due_today_count if inad_summary else 0} | "
                f"R$ {inad_summary.due_today_total if inad_summary else '0,00'}"
            )
            lines.append(
                f"Visitas com risco hoje: {risk_today[0]} | R$ {risk_today[1]}"
            )
            self._append_giro_summary_lines(lines, giro_summary, compact=True)
            client_updated = client_summary.planilha_atualizada_em if client_summary else "-"
            giro_updated = giro_summary.planilha_atualizada_em if giro_summary else "-"
            lines.append(f"Atualizado: Clientes {client_updated} | Giro {giro_updated}")

        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _build_seller_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
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
        current_visit_label = current_visit_day or _current_visit_day_label()
        visit_count = 0
        risk_alerts: list[InadimplenciaVisitAlert] = []
        risk_note = ""
        if current_visit_day:
            try:
                visit_clients = self.query_service.list_clients_by_visit_day(
                    current_visit_day,
                    allowed_sectors=self._allowed_sectors(decision),
                    allowed_gv_vdes=self._allowed_gv_vdes(decision),
                    limit=200,
                )
                risk_alerts = self.inadimplencia_service.list_upcoming_by_visit_day(
                    current_visit_day,
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
        lines = ["Resumo da sua carteira", ""]
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
        lines.append(f"*Rota de hoje ({current_visit_label}):* {visit_count} visita(s)")
        if risk_note:
            lines.append(risk_note)
        else:
            lines.append(
                f"*Clientes com risco hoje:* {len(risk_today_alerts)} cliente(s) | "
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
        return OutgoingMessage(text="\n".join(lines))

    def _build_seller_risk_response(self, decision: AccessDecision) -> OutgoingMessage:
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        current_visit_label = current_visit_day or _current_visit_day_label()
        if not current_visit_day:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei visitas programadas para hoje ({current_visit_label}) na sua carteira.\n"
                    f"{_result_hint_text()}"
                )
            )

        try:
            visit_clients = self.query_service.list_clients_by_visit_day(
                current_visit_day,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=200,
            )
            alerts = self.inadimplencia_service.list_upcoming_by_visit_day(
                current_visit_day,
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

        risk_today_alerts = [alert for alert in alerts if alert.nearest_days_to_due <= 0]
        lines = [
            f"Clientes da sua rota com risco hoje ({current_visit_label})",
            f"Visitas programadas: {len(visit_clients)}",
            f"Clientes com risco hoje: {len(risk_today_alerts)} | R$ {_sum_money_values(alert.total_pendente for alert in risk_today_alerts)}",
            f"Planilha atualizada em: {(alerts[0].planilha_atualizada_em if alerts else '-') or '-'}",
        ]
        if not risk_today_alerts:
            lines.append("")
            lines.append("Nao encontrei clientes da sua rota vencendo hoje ou ja inadimplentes.")
            lines.append("")
            lines.append(_result_hint_text())
            return OutgoingMessage(text="\n".join(lines))

        overdue = [alert for alert in risk_today_alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in risk_today_alerts if alert.nearest_days_to_due == 0]
        lines.append("")
        self._append_visit_financial_group(lines, "Ja inadimplentes", overdue)
        self._append_visit_financial_group(lines, "Vence hoje", due_today)
        lines.append("")
        lines.append(_result_hint_text())
        return OutgoingMessage(text="\n".join(lines))

    def _resolve_current_scope_visit_day_label(self, decision: AccessDecision) -> str:
        try:
            visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
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
        session.selected_visit_risk_token = ""
        session.selected_visit_risk_label = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_day_menu(visit_days=visit_days)

    def _open_manager_summary_menu(
        self,
        sender: str,
        session: LookupSession,
    ) -> OutgoingMessage:
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
            title="Gerente de Vendas",
            text=text,
            footer="Esse menu junta os atalhos principais da sua gerencia, incluindo submenu de giro. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=MANAGER_SUMMARY_TOTAL,
                    title="Resumo Total",
                    description="Ver toda a base do seu GV",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=MANAGER_SUMMARY_BY_FILIAL,
                    title="Por Filial",
                    description="Escolher a revenda para detalhar",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_LIST,
                    title="Inadimplentes",
                    description="Listar os clientes da gerencia",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_UPCOMING,
                    title="Vencimentos",
                    description="Ver proximos vencimentos da base",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_VISIT_RISK,
                    title="Visitas com Risco",
                    description="Ver setores da rota com risco financeiro",
                    shortcut="5",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_BY_SELLER,
                    title="Por Vendedor",
                    description="Escolher um setor para ver o resumo",
                    shortcut="6",
                ),
                InteractiveOption(
                    option_id=MANAGER_ACTION_GIRO,
                    title="Giro",
                    description="Abrir o submenu de giro da gerencia",
                    shortcut="7",
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
        return OutgoingMessage(text="\n".join(lines))

    def _open_manager_visit_risk_day_selection(
        self,
        sender: str,
        session: LookupSession,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        try:
            visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
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
        session.selected_visit_risk_token = ""
        session.selected_visit_risk_label = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_day_menu(visit_days=visit_days)

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

        session.step = "manager_select_visit_risk_sector"
        session.visit_risk_day_options = ()
        session.visit_risk_summaries = tuple(summaries)
        session.selected_visit_risk_token = visit_day_token
        session.selected_visit_risk_label = visit_day_label
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_menu(visit_day_label=visit_day_label, summaries=summaries)

    def _build_director_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        text = "Como voce quer ver esse resumo?"
        if invalid_selection:
            text = _invalid_option_text("Como voce quer ver esse resumo?")
        return OutgoingMessage(
            kind="menu",
            title="Resumo dos Gerentes",
            text=text,
            footer="Voce pode ver total, ranking, risco, maiores devedores, consolidado por filial e submenu de giro. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                InteractiveOption(
                    option_id=DIRECTOR_SUMMARY_TOTAL,
                    title="Resumo Total",
                    description="Ver a base completa da diretoria",
                    shortcut="1",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_SUMMARY_BY_REVENDA,
                    title="Por Revenda",
                    description="Escolher uma revenda/GV para detalhar",
                    shortcut="2",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_RANKING,
                    title="Ranking dos Gerentes",
                    description="Ordenar os GVs pelo maior valor pendente",
                    shortcut="3",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_VISIT_RISK,
                    title="Visitas com Risco",
                    description="Ver risco por gerente, setor e clientes",
                    shortcut="4",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_TOP_DEBTORS,
                    title="Maiores Devedores",
                    description="Listar os maiores devedores da diretoria",
                    shortcut="5",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_BY_FILIAL,
                    title="Resumo por Filial",
                    description="Consolidar a diretoria por revenda",
                    shortcut="6",
                ),
                InteractiveOption(
                    option_id=DIRECTOR_ACTION_GIRO,
                    title="Giro",
                    description="Abrir o submenu de giro da diretoria",
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
                    title=f"Resumo do gerente {_format_gv_scope_label(gv_options[0])}",
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

        lines = [f"Visitas com risco em {visit_day_label}:"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(f"*GVs com risco:* {len(gv_options)}")
        lines.append("Escolha o gerente para ver os setores com risco.")
        return OutgoingMessage(
            kind="menu",
            title="Visitas com Risco",
            text="\n".join(lines),
            footer="Depois eu mostro os setores da gerencia e, em seguida, os clientes. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"director:visit_risk:gv:{index}",
                    title=_format_gv_scope_label(gv_code),
                    description=(
                        f"{sum(item.client_count for item in grouped.get(gv_code, []))} cliente(s) com risco | "
                        f"R$ {_sum_money_values(item.total_pendente for item in grouped.get(gv_code, []))}"
                    ),
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_director_gv_summary_menu(
        self,
        gv_options: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        text = "Escolha o gerente de vendas que voce quer resumir."
        if invalid_selection:
            text = _invalid_option_text("Escolha o gerente de vendas que voce quer resumir.")
        return OutgoingMessage(
            kind="menu",
            title="Resumo dos Gerentes",
            text=text,
            footer="Cada opcao representa uma revenda dentro da base dos seus gerentes. Use A ou ANT para voltar.",
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

        session.step = "finance_select_visit_risk_sector"
        session.visit_risk_day_options = ()
        session.visit_risk_summaries = tuple(summaries)
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
        visit_days = [label for _, label in VISIT_DAY_CHOICES]

        session.step = "finance_select_visit_risk_day"
        session.visit_risk_day_options = tuple(visit_days)
        session.visit_risk_summaries = ()
        session.selected_visit_risk_token = ""
        session.selected_visit_risk_label = ""
        session.updated_at = datetime.now(timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_day_menu(visit_days=visit_days)

    def _build_finance_visit_risk_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = "Escolha o dia da semana para ver as rotas com risco financeiro."
        if invalid_selection:
            header = _invalid_option_text("Escolha o dia da semana para ver as rotas com risco financeiro.")
        return OutgoingMessage(
            kind="menu",
            title="Visitas com Risco",
            text=header,
            footer="Depois eu mostro os setores com risco desse dia e, em seguida, os clientes. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{VISIT_DAY_PICK_PREFIX}{index}",
                    title=visit_day,
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
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        total_clients = sum(summary.client_count for summary in summaries)
        total_pendente = _sum_money_values(summary.total_pendente for summary in summaries)
        lines = [f"Visitas com risco financeiro em {visit_day_label}:"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(f"*Setores com risco:* {len(summaries)}")
        lines.append(f"*Clientes com risco nesse dia:* {total_clients} | R$ {total_pendente}")
        lines.append(f"*Planilha atualizada em:* {summaries[0].planilha_atualizada_em or '-'}")
        lines.append("Escolha o setor para ver os clientes com risco.")
        return OutgoingMessage(
            kind="menu",
            title="Visitas com Risco",
            text="\n".join(lines),
            footer="No titulo aparece a chave filial-setor. Na descricao, voce ve a chave filial-GV, a quantidade e o valor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{FINANCE_VISIT_RISK_PICK_PREFIX}{summary.seller_code}:{summary.manager_code}",
                    title=_format_sector_scope_label(summary.seller_code),
                    description=(
                        f"{_format_gv_scope_label(summary.manager_code)} | {summary.client_count} visita(s) | "
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
            f"{_format_gv_scope_label(summary.manager_code)} | {summary.client_count} visita(s) com risco | R$ {summary.total_pendente}",
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
            has_invalid_gv_scope = any(not normalize_gv_scope_input(value) for value in gv_vdes)
            has_invalid_dc_scope = any(not normalize_dc_scope_input(value) for value in gv_vdes)
            if role_name in {ROLE_ADMIN, ROLE_FINANCEIRO} and (sectors or gv_vdes):
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
            footer="Escolha um unico cargo. Vendedor usa filial-setor. Gerente de Vendas usa filial-GV. Diretor Comercial usa filial-DC. Financeiro e admin nao usam escopo comercial.",
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
                    description="Consulta sem limite de setor ou GV",
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
                lines.append("Novo acesso: consulta sem limite de setor ou GV")
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
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = f"Encontrei {len(records)} cliente(s) com '{query_text}'."
        if invalid_selection:
            header = f"Nao entendi essa opcao.\n{header}"
        text = f"{header}\nEscolha um cliente para ver os detalhes."
        return OutgoingMessage(
            kind="menu",
            title="Resultados da Busca",
            text=text,
            footer="A lista mostra o codigo do PDV e o nome do cliente. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{FANTASIA_PICK_PREFIX}{index}",
                    title=record.nome_fantasia or record.razao_social or f"Cliente {index}",
                    description=f"Codigo {record.cod_pdv} | Revenda {record.filial}",
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
        invalid_selection: bool = False,
        navigation_notice: str = "",
    ) -> OutgoingMessage:
        custom_header = _extract_inadimplencia_custom_header(query_text)
        scope_label = _extract_inadimplencia_scope_label(query_text)
        if custom_header:
            header = custom_header
        elif scope_label:
            header = f"Esses sao os clientes inadimplentes da {scope_label}."
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
            lines.append(f"Pagina {current_page} de {total_pages}.")
            lines.append(f"Mostrando clientes {start_index} a {end_index} de {total_available}.")
        elif (custom_header or scope_label) and total_available and total_available > len(summaries):
            lines.append(f"Estou mostrando os primeiros {len(summaries)} de {total_available} cliente(s).")
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
            title="Clientes Encontrados",
            text=text,
            footer=(
                f"Primeiro voce escolhe o cliente. Depois eu mostro os titulos."
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
    

    def _build_visit_day_menu(
        self,
        decision: AccessDecision,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        header = "Escolha o dia que voce quer consultar."
        if invalid_selection:
            header = _invalid_option_text("Escolha o dia que voce quer consultar.")
        footer = "Depois voce escolhe o setor para ver as visitas."
        if not self._uses_grouped_visit_flow(decision):
            footer = "Depois eu mostro os clientes desse dia."
        return OutgoingMessage(
            kind="menu",
            title="Visitas do Dia",
            text=header,
            footer=f"{footer} Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                InteractiveOption(
                    option_id=f"{VISIT_DAY_PICK_PREFIX}{index}",
                    title=visit_day,
                    description="Ver clientes desse dia",
                    shortcut=str(index),
                )
                for index, visit_day in enumerate(visit_days, start=1)
            ),
        )

    def _build_visit_day_manager_menu(
        self,
        visit_day: str,
        visit_summaries: list[VisitSellerSummary],
        invalid_selection: bool = False,
    ) -> OutgoingMessage:
        if not visit_summaries:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei visitas para o dia '{visit_day}'.\n"
                    "Se quiser tentar de novo, envie MENU."
                )
            )

        header = f"Essas sao as visitas de '{visit_day}'. Escolha o setor."
        if invalid_selection:
            header = f"Nao entendi essa opcao.\n{header}"
        return OutgoingMessage(
            kind="menu",
            title="Visitas por Setor",
            text=header,
            footer="No titulo aparece a chave filial-setor. Na descricao, voce ve a chave filial-GV e a quantidade de visitas. Use A ou ANT para voltar.",
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

    def _build_single_record_response(self, record: DClienteRecord, criteria: str) -> OutgoingMessage:
        lines = [f"Encontrei este cliente para {criteria}."]
        lines.append("")
        lines.append(f"*Razao Social:* {record.razao_social or '-'}")
        lines.append(f"*Fantasia:* {record.nome_fantasia or '-'}")
        lines.append(f"*Telefone:* {record.telefone or '-'}")
        lines.append(f"*Cond Pag Atual:* {record.cond_pag_atual or '-'}")
        lines.append(f"*Limite de Credito:* {record.limite_credito or '-'}")
        lines.append(f"*Dia de Visita:* {record.dia_visita or '-'}")
        lines.append(f"*Setor/Vendedor:* {record.vendedor or '-'}")
        lines.append(f"*Situacao:* {record.status or '-'}")
        lines.append(f"*Cidade:* {record.cidade or '-'}")
        lines.append(f"*Revenda:* {record.filial or '-'}")
        lines.append(f"*Codigo do PDV:* {record.cod_pdv or '-'}")
        lines.append(f"*Total Pendente:* {record.total_pendente or '0,00'}")
        lines.append(f"*Comodatos Pendentes:* {record.total_comodatos_pendentes}")
        lines.append(f"*Atualizado em:* {record.ultima_atualizacao_tabela or '-'}")
        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_search_response(
        self,
        records: list[DClienteRecord],
        criteria: str,
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

        lines = [f"Encontrei {len(records)} cliente(s) para {criteria}."]
        for index, record in enumerate(records, start=1):
            lines.append("")
            lines.append(f"{index}. *Razao Social:* {record.razao_social or '-'}")
            lines.append(f"*Fantasia:* {record.nome_fantasia or '-'}")
            lines.append(f"*Telefone:* {record.telefone or '-'}")
            lines.append(f"*Cond Pag Atual:* {record.cond_pag_atual or '-'}")
            lines.append(f"*Limite de Credito:* {record.limite_credito or '-'}")
            lines.append(f"*Dia de Visita:* {record.dia_visita or '-'}")
            lines.append(f"*Setor/Vendedor:* {record.vendedor or '-'}")
            lines.append(f"*Situacao:* {record.status or '-'}")
            lines.append(f"*Cidade:* {record.cidade or '-'}")
            lines.append(f"*Revenda:* {record.filial or '-'}")
            lines.append(f"*Codigo do PDV:* {record.cod_pdv or '-'}")
            lines.append(f"*Total Pendente:* {record.total_pendente or '0,00'}")
            lines.append(f"*Comodatos Pendentes:* {record.total_comodatos_pendentes}")
            lines.append(f"*Atualizado em:* {record.ultima_atualizacao_tabela or '-'}")

        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

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

        records = self.query_service.search_by_registration(
            filial=filial,
            cod_pdv=cod_pdv,
            allowed_sectors=self._allowed_sectors(decision),
            allowed_gv_vdes=self._allowed_gv_vdes(decision),
        )
        return self._build_search_response(records, f"revenda {filial} e Cod PDV {cod_pdv}")

    def _search_giro_by_document(
        self,
        decision: AccessDecision,
        normalized_document: str,
    ) -> list[GiroClientRecord]:
        _ = decision
        client_records = self.query_service.search_by_document(
            document=normalized_document,
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
    ) -> OutgoingMessage:
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei titulos em aberto para {criteria} dentro do acesso liberado para o seu numero.\n"
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        total_pendente = _sum_money_values(record.valor_pendente for record in records)
        lines = [f"Encontrei {len(records)} titulo(s) em aberto para {criteria}."]
        lines.append(f"*Planilha atualizada em:* {records[0].planilha_atualizada_em or '-'}")
        for index, record in enumerate(records, start=1):
            lines.append("")
            lines.append(f"{index}. *NB:* {record.cod_pdv or '-'}")
            lines.append(f"*Nome:* {record.nome or '-'}")
            lines.append(f"*Data de Emissao:* {record.data_emissao or '-'}")
            lines.append(f"*Data de Vencimento:* {record.data_vencimento or '-'}")
            lines.append(f"*Valor Original:* {record.valor_original or '-'}")
            lines.append(f"*Valor Corrigido:* {record.valor_corrigido or '-'}")
            lines.append(f"*Dias:* {record.dias or '-'}")

        lines.append("")
        lines.append(f"*Total Pendente:* {total_pendente}")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
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
                    "Se quiser tentar outra busca, envie MENU."
                )
            )

        lines = [f"Encontrei {len(records)} registro(s) de giro para {criteria}."]
        lines.append(f"*Planilha atualizada em:* {records[0].planilha_atualizada_em or '-'}")
        for index, record in enumerate(records, start=1):
            lines.append("")
            lines.append(f"{index}. *Cliente:* {record.nome or '-'}")
            lines.append(f"*NB:* {record.cod_pdv or '-'}")
            lines.append(f"*Revenda:* {_format_filial_label(record.filial)}")
            lines.append(f"*Setor:* {record.setor or '-'}")
            lines.append(
                "Litrinho: "
                f"Total {record.total_litrinho} | "
                f"Real {record.real_litrinho} | "
                f"Gap {record.gap_litrinho} | "
                f"Status {record.giro_litrinho}"
            )
            lines.append(
                "Inteira: "
                f"Total {record.total_inteira} | "
                f"Real {record.real_inteira} | "
                f"Gap {record.gap_inteira} | "
                f"Status {record.giro_inteira}"
            )
            lines.append(
                "Litrao: "
                f"Total {record.total_litrao} | "
                f"Real {record.real_litrao} | "
                f"Gap {record.gap_litrao} | "
                f"Status {record.giro_litrao}"
            )

        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_visit_day_clients_response(
        self,
        visit_day: str,
        records: list[DClienteRecord],
        financial_alerts: list[InadimplenciaVisitAlert],
        alerts_note: str,
    ) -> OutgoingMessage:
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei clientes para o dia '{visit_day}'.\n"
                    "Se quiser tentar outra consulta, envie MENU."
                )
            )

        lines = [f"Clientes com visita em '{visit_day}':"]
        lines.append(f"Atualizado em: {records[0].ultima_atualizacao_tabela or '-'}")
        for index, record in enumerate(records, start=1):
            client_name = record.nome_fantasia or record.razao_social or "-"
            lines.append(f"{index}. Codigo {record.cod_pdv} | {client_name}")
        self._append_visit_financial_section(lines, financial_alerts, alerts_note)
        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

    def _build_visit_day_seller_clients_response(
        self,
        visit_day: str,
        summary: VisitSellerSummary,
        records: list[DClienteRecord],
        financial_alerts: list[InadimplenciaVisitAlert],
        alerts_note: str,
    ) -> OutgoingMessage:
        if not records:
            return OutgoingMessage(
                text=(
                    f"Nao encontrei visitas para {_format_sector_scope_label(summary.seller_code)} no dia '{visit_day}'.\n"
                    f"{_format_gv_scope_label(summary.manager_code)} | Total no resumo: {summary.visit_count} visita(s)\n"
                    "Se quiser tentar outra consulta, envie MENU."
                )
            )

        lines = [
            f"Clientes de {_format_sector_scope_label(summary.seller_code)} no dia '{visit_day}':",
            f"{_format_gv_scope_label(summary.manager_code)} | {summary.visit_count} visita(s)",
            f"Atualizado em: {records[0].ultima_atualizacao_tabela or '-'}",
        ]
        for index, record in enumerate(records, start=1):
            client_name = record.nome_fantasia or record.razao_social or "-"
            lines.append(f"{index}. Codigo {record.cod_pdv} | {client_name}")
        self._append_visit_financial_section(lines, financial_alerts, alerts_note)
        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return OutgoingMessage(text="\n".join(lines))

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
        lines.append(f"{label}: {len(alerts)} cliente(s)")
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
                "Agora me envie o numero do diretor comercial ou varios numeros separados por virgula.\n"
                "Exemplo: 1 ou 1,3"
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
                "Para esse cargo, preciso de pelo menos um numero de diretor comercial valido.\n"
                "Envie nesse formato: 1 ou 1,3"
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
            return (
                f"Nao encontrei base para o(s) diretor(es): {joined_codes}.\n"
                "Confira os numeros e envie novamente.\n"
                "Exemplo: 1 ou 1,3"
            )
        return self._build_scope_retry_prompt(role_name)

    def _resolve_admin_scope_codes(self, text: str, role_name: str) -> tuple[list[str], str | None]:
        if role_name == ROLE_VENDEDOR:
            scope_codes = _parse_scope_code_list(text, role_name)
            if not scope_codes:
                return [], self._build_scope_retry_prompt(role_name)
            return scope_codes, None

        base_codes = _parse_management_scope_code_list(text)
        if not base_codes:
            return [], self._build_scope_retry_prompt(role_name)

        try:
            if role_name == ROLE_GERENTE_VENDAS:
                scope_codes = self.query_service.expand_gv_scope_codes(base_codes)
            elif role_name == ROLE_DIRETOR_COMERCIAL:
                scope_codes = self.query_service.expand_dc_scope_codes(base_codes)
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
            return "sem filtro comercial"
        if ROLE_DIRETOR_COMERCIAL in roles:
            return f"DCs sob responsabilidade: {_format_gv_vdes(gv_vdes, role_name=ROLE_DIRETOR_COMERCIAL)}"
        if ROLE_GERENTE_VENDAS in roles:
            return f"GVs liberados: {_format_gv_vdes(gv_vdes, role_name=ROLE_GERENTE_VENDAS)}"
        if ROLE_VENDEDOR in roles:
            return f"Setores liberados: {_format_sectors(sectors)}"
        return "-"

    def _reset_session(self, sender: str) -> None:
        self.sessions.pop(sender, None)

    def _cleanup_sessions(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            sender
            for sender, session in self.sessions.items()
            if now - session.updated_at > self.session_ttl
        ]
        for sender in expired:
            self.sessions.pop(sender, None)


def _invalid_option_text(prompt: str) -> str:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return "Nao entendi essa opcao."
    return f"Nao entendi essa opcao.\n{prompt_text}"


def _result_hint_text(*, allow_back: bool = False) -> str:
    if allow_back:
        return "Se quiser voltar, envie A ou ANT.\nSe preferir começar de novo, envie MENU."
    return "Se quiser fazer outra consulta, envie MENU."


def _strip_result_hint(text: str) -> str:
    value = str(text or "").strip()
    for hint in (
        _result_hint_text(allow_back=True),
        _result_hint_text(allow_back=False),
        "Se quiser continuar, envie MENU.",
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


def _parse_finance_action(normalized_text: str) -> str:
    normalized_tokens = {
        token
        for token in re.sub(r"[^a-z0-9]+", " ", normalized_text).split()
        if token
    }
    numeric_choice_match = re.match(r"^0*([1-7])(?:[^0-9].*)?$", normalized_text)
    if numeric_choice_match:
        return {
            "1": "summary",
            "2": "list",
            "3": "top",
            "4": "upcoming",
            "5": "visit_risk",
            "6": "gv_summary",
            "7": "giro",
        }[numeric_choice_match.group(1)]
    if normalized_text in {FINANCE_ACTION_SUMMARY, "1", "resumo financeiro", "resumo"}:
        return "summary"
    if normalized_text in {FINANCE_ACTION_LIST, "2", "ver inadimplentes", "inadimplentes"}:
        return "list"
    if normalized_text in {FINANCE_ACTION_TOP, "3", "maiores devedores", "maiores valores"}:
        return "top"
    if normalized_text in {FINANCE_ACTION_UPCOMING, "4", "vencimentos proximos", "vencimentos próximos"}:
        return "upcoming"
    if normalized_text in {
        FINANCE_ACTION_VISIT_RISK,
        "5",
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
        "resumo por gv",
        "resumo do gv",
        "resumo gv",
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
    if normalized_text.startswith(("5", "05", "o5")) and (
        {"visita", "visitas"} & normalized_tokens or {"risco", "riscos"} & normalized_tokens
    ):
        return "visit_risk"
    if {"visita", "visitas"} & normalized_tokens and {"risco", "riscos"} & normalized_tokens:
        return "visit_risk"
    if {"resumo"} & normalized_tokens and {"gv"} & normalized_tokens:
        return "gv_summary"
    return ""


def _parse_finance_due_bucket(normalized_text: str) -> str:
    if normalized_text in {FINANCE_DUE_IN_TWO_DAYS, "1", "vence em 2 dias", "2 dias"}:
        return "in_two_days"
    if normalized_text in {FINANCE_DUE_TOMORROW, "2", "vence amanha", "amanha"}:
        return "tomorrow"
    if normalized_text in {FINANCE_DUE_TODAY, "3", "vence hoje", "hoje"}:
        return "today"
    if normalized_text in {FINANCE_DUE_OVERDUE, "4", "ja vencidos", "já vencidos", "vencidos", "inadimplentes"}:
        return "overdue"
    return ""


def _parse_director_summary_action(normalized_text: str) -> str:
    if normalized_text in {
        DIRECTOR_SUMMARY_TOTAL,
        "1",
        "resumo total",
        "total",
        "resumo da diretoria",
    }:
        return "total"
    if normalized_text in {
        DIRECTOR_SUMMARY_BY_REVENDA,
        "2",
        "por revenda",
        "ver por revenda",
        "por gerente",
        "escolher revenda",
    }:
        return "by_revenda"
    if normalized_text in {
        DIRECTOR_ACTION_RANKING,
        "3",
        "ranking dos gerentes",
        "ranking",
        "ranking dos gvs",
    }:
        return "ranking"
    if normalized_text in {
        DIRECTOR_ACTION_VISIT_RISK,
        "4",
        "visitas com risco",
        "risco das visitas",
        "visitas com risco por gerente",
    }:
        return "visit_risk"
    if normalized_text in {
        DIRECTOR_ACTION_TOP_DEBTORS,
        "5",
        "maiores devedores",
        "devedores",
        "top devedores",
    }:
        return "top_debtors"
    if normalized_text in {
        DIRECTOR_ACTION_BY_FILIAL,
        "6",
        "resumo por filial",
        "por filial",
        "filial",
    }:
        return "by_filial"
    if normalized_text in {
        DIRECTOR_ACTION_GIRO,
        "7",
        "giro",
        "submenu giro",
        "giro da diretoria",
    }:
        return "giro"
    return ""


def _parse_manager_summary_action(normalized_text: str) -> str:
    if normalized_text in {
        MANAGER_SUMMARY_TOTAL,
        "1",
        "resumo total",
        "total",
        "resumo da gerencia",
        "resumo do gv",
    }:
        return "total"
    if normalized_text in {
        MANAGER_SUMMARY_BY_FILIAL,
        "2",
        "por filial",
        "ver por filial",
        "escolher filial",
        "por revenda",
    }:
        return "by_filial"
    if normalized_text in {
        MANAGER_ACTION_LIST,
        "3",
        "inadimplentes",
        "inadimplentes da gerencia",
        "clientes inadimplentes",
    }:
        return "list"
    if normalized_text in {
        MANAGER_ACTION_UPCOMING,
        "4",
        "vencimentos",
        "vencimentos proximos",
        "proximos vencimentos",
    }:
        return "upcoming"
    if normalized_text in {
        MANAGER_ACTION_VISIT_RISK,
        "5",
        "visitas com risco",
        "risco das visitas",
        "visitas com risco da gerencia",
    }:
        return "visit_risk"
    if normalized_text in {
        MANAGER_ACTION_BY_SELLER,
        "6",
        "por vendedor",
        "resumo por vendedor",
        "vendedor",
    }:
        return "by_seller"
    if normalized_text in {
        MANAGER_ACTION_GIRO,
        "7",
        "giro",
        "submenu giro",
        "giro da gerencia",
    }:
        return "giro"
    return ""


def _parse_giro_mode(normalized_text: str) -> str:
    if normalized_text in {GIRO_MODE_TOTAL, "1", "total", "resumo total", "consolidado"}:
        return "total"
    if normalized_text in {GIRO_MODE_BY_FILIAL, "2", "por filial", "filial", "revenda"}:
        return "by_filial"
    if normalized_text in {GIRO_MODE_BY_GV, "3", "por gv", "gv", "gerente"}:
        return "by_gv"
    return ""


def _is_back_menu_command(normalized_text: str) -> bool:
    return normalized_text in MENU_BACK_COMMANDS


def _is_prev_page_command(normalized_text: str) -> bool:
    return normalized_text in {
        INADIMPLENCIA_PAGE_PREV,
        *MENU_BACK_COMMANDS,
        "pagina anterior",
    }


def _is_next_page_command(normalized_text: str) -> bool:
    return normalized_text in {
        INADIMPLENCIA_PAGE_NEXT,
        *PAGE_NEXT_COMMANDS,
        "proxima pagina",
        "proxima",
        "proximo",
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
    return "P", "A"


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
        labels.append("A ou ANT para a pagina anterior")
    if current_page < total_pages:
        labels.append("P, PROX ou PRXX para a proxima pagina")
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


def _sort_numeric_text(value: str) -> tuple[int, str]:
    normalized = normalize_numeric_code(value)
    if normalized:
        return (0, f"{int(normalized):08d}")
    return (1, str(value or ""))


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
        raw = str(value or "").strip()
        if not raw:
            continue
        normalized = raw.replace(".", "").replace(",", ".")
        try:
            total += Decimal(normalized)
        except (InvalidOperation, ValueError):
            continue
    return f"{total:.2f}".replace(".", ",")


def _format_percent_ratio(numerator: int, denominator: int) -> str:
    base = max(int(denominator or 0), 0)
    value = max(int(numerator or 0), 0)
    if base <= 0:
        return "0,0%"
    ratio = (Decimal(value) * Decimal("100")) / Decimal(base)
    return f"{ratio:.1f}%".replace(".", ",")


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
        return f"{total:.2f}".replace(".", ",")

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
    raw = str(value or "").strip()
    if not raw:
        return Decimal("0")
    normalized = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _build_filial_prompt(search_context: str) -> str:
    code_label = "codigo do PDV" if search_context == "cliente" else "NB"
    lines = [
        "Informe a revenda/filial do cliente.",
        f"Se quiser ser mais rapido, pode mandar filial e {code_label} juntos.",
        "Exemplo: 3 6643",
        "",
    ]
    for filial_code in sorted(FILIAL_LABELS, key=int):
        lines.append(f"{filial_code} - {FILIAL_LABELS[filial_code]}")
    return "\n".join(lines)
