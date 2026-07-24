from __future__ import annotations

import base64
import io
import re
from typing import Any

from pypdf import PdfReader, PdfWriter


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class CustomerRouter:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def handle_locked(self, incoming: IncomingMessage, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        expired_session = self._peek_expired_session(incoming.sender)
        self._cleanup_sessions()
        session = self.sessions.get(incoming.sender, flow.LookupSession())
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        text = (incoming.text or '').strip()
        normalized = flow._normalize_choice(text)
        if normalized in {'menu', 'inicio', 'iniciar', 'start', 'oi', 'ola'}:
            self._reset_session(incoming.sender)
            return self._build_main_menu(decision)
        if normalized in {'voltar', 'cancelar', 'sair'}:
            self._reset_session(incoming.sender)
            return self._build_main_menu(decision)
        if expired_session is not None and flow._looks_like_contextual_follow_up(normalized):
            return self._build_expired_session_prompt(previous_step=expired_session.step)
        if session.step.startswith('admin_'):
            return self.admin_access_flow._handle_admin_session(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if session.step.startswith('recolha_'):
            return self.recolha_flow.handle_session(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if session.step.startswith('finance_'):
            return self.finance_flow.handle_session(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if session.step == 'seller_finance_select_action':
            selected_option = flow._select_interactive_option(text=text, normalized=normalized, options=flow._build_seller_finance_menu_response().options)
            if selected_option is None:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                return flow._build_seller_finance_menu_response(invalid_selection=True)
            if selected_option.option_id == flow.SELLER_FINANCE_ACTION_RECOLHA:
                return self._open_recolha_request(sender=incoming.sender, session=session, text='', normalized='', decision=decision)
            if selected_option.option_id == flow.SELLER_FINANCE_ACTION_BOLETO:
                return self._open_boleto_registration_prompt(sender=incoming.sender, session=session)
            return flow._build_seller_finance_menu_response(invalid_selection=True)
        if session.step == 'awaiting_boleto_registration':
            return self._handle_boleto_registration_input(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if session.step == 'awaiting_critica_action':
            readiness_error = self.critica_flow.ensure_ready(decision)
            if readiness_error is not None:
                return readiness_error
            selected_option = flow._select_interactive_option(text=text, normalized=normalized, options=flow._build_critica_menu_response().options)
            if selected_option is not None:
                return self.critica_flow.handle_command(sender=incoming.sender, session=session, text=selected_option.option_id, normalized=flow._normalize_choice(selected_option.option_id), decision=decision)
            if flow._looks_like_critica_command(normalized):
                return self.critica_flow.handle_command(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            menu = flow._build_critica_menu_response()
            return flow.OutgoingMessage(kind=menu.kind, title=menu.title, text=f'Nao entendi essa opcao.\n\n{menu.text}', footer=menu.footer, button_text=menu.button_text, options=menu.options)
        if session.step == 'awaiting_intent_clarification':
            selected_option = flow._select_interactive_option(text=text, normalized=normalized, options=session.clarification_options)
            if selected_option is None:
                self.sessions[incoming.sender] = session
                return self._build_intent_clarification_menu(session=session, invalid_selection=True)
            return self._run_intent_clarification_option(sender=incoming.sender, session=session, decision=decision, option_id=selected_option.option_id)
        if session.step == 'awaiting_boleto_selection':
            return self._handle_boleto_selection(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if flow._is_back_menu_command(normalized):
            if session.step == 'awaiting_post_result_navigation':
                resumed_response = self._resume_post_result_navigation(sender=incoming.sender, session=session, decision=decision)
                if resumed_response is not None:
                    return resumed_response
            back_response = self._handle_menu_back_navigation(sender=incoming.sender, session=session, decision=decision)
            if back_response is not None:
                return back_response
        if session.step == 'awaiting_post_result_navigation' and normalized:
            if flow._is_repeat_query_command(normalized):
                return self._repeat_post_result_navigation(sender=incoming.sender, session=session, decision=decision)
            payip_pix_selection = flow._parse_payip_pix_selection(normalized)
            if payip_pix_selection is not None and session.payip_pix_payloads:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                return flow._build_payip_pix_code_response(session.payip_pix_payloads, selection=payip_pix_selection, payip_payments_service=self.payip_payments_service)
            if flow._looks_like_critica_command(normalized):
                return self.critica_flow.handle_command(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
            estoque_response = self._maybe_handle_estoque_command(sender=incoming.sender, text=text, normalized=normalized, decision=decision)
            if estoque_response is not None:
                return estoque_response
            payip_response = self.finance_flow.payip_flow.handle_post_result_request(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
            if payip_response is not None:
                return payip_response
            recolha_response = self.recolha_flow.handle_post_result_request(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
            if recolha_response is not None:
                return recolha_response
            self.sessions[incoming.sender] = session
            return flow.OutgoingMessage(text='Para continuar desse ponto, envie A ou ANT.\nPara copiar um PIX retornado pela PayIP e receber o PDF, envie PIX 1.\nSe preferir voltar ao inicio, envie MENU.')
        if session.step == 'awaiting_search_mode':
            readiness_error = self._ensure_search_context_ready(session.search_context, decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            conversational_response = self._maybe_handle_search_mode_conversation(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
            if conversational_response is not None:
                return conversational_response
            selected_option = flow._select_interactive_option(text=text, normalized=normalized, options=self._build_search_menu(search_context=session.search_context, decision=decision).options)
            if selected_option is not None:
                return self._run_search_menu_option(sender=incoming.sender, session=session, decision=decision, option_id=selected_option.option_id)
            if normalized in {flow.SEARCH_BY_REGISTRATION, '1', 'filial', 'cadastro', 'filial e cod pdv', 'filial e codigo pdv', 'filial e nb', 'nb'}:
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                session.step = 'awaiting_filial'
                session.filial = ''
                session.fantasia_query = ''
                session.fantasia_results = ()
                session.inadimplencia_client_summaries = ()
                session.inadimplencia_total_available = 0
                session.inadimplencia_list_context = ''
                session.inadimplencia_page = 1
                session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
                session.comodato_client_summaries = ()
                session.selected_visit_day = ''
                session.visit_day_options = ()
                session.visit_seller_summaries = ()
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                return flow.OutgoingMessage(text=flow._build_filial_prompt(session.search_context))
            if normalized in {flow.SEARCH_BY_FANTASIA, '2', 'fantasia', 'nome fantasia', 'nome_fantasia'}:
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                session.step = 'awaiting_fantasia'
                session.filial = ''
                session.fantasia_query = ''
                session.fantasia_results = ()
                session.inadimplencia_client_summaries = ()
                session.inadimplencia_total_available = 0
                session.inadimplencia_list_context = ''
                session.inadimplencia_page = 1
                session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
                session.comodato_client_summaries = ()
                session.selected_visit_day = ''
                session.visit_day_options = ()
                session.visit_seller_summaries = ()
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                if session.search_context == 'inadimplencia':
                    return flow.OutgoingMessage(text='Digite parte do nome do cliente para ver os titulos em aberto.')
                if session.search_context == 'comodato':
                    return flow.OutgoingMessage(text='Digite parte do nome do cliente para ver os comodatos pendentes.')
                if session.search_context == 'giro':
                    return flow.OutgoingMessage(text='Digite parte do nome do cliente para ver os dados de giro.')
                if session.search_context == 'documentacao':
                    return flow.OutgoingMessage(text='Digite parte do nome do cliente para ver a documentacao pendente.')
                if session.search_context == 'prazo_limite':
                    return flow.OutgoingMessage(text='Digite parte do nome do cliente para consultar prazo e limite.')
                return flow.OutgoingMessage(text='Digite parte do nome do cliente.\nVou procurar e mostrar uma lista para voce escolher.')
            if normalized in {flow.SEARCH_BY_DOCUMENT, '3', 'cpf', 'cnpj', 'cpf cnpj', 'cpf/cnpj', 'documento'}:
                access_error = None
                if session.search_context in {'inadimplencia', 'comodato', 'documentacao', 'prazo_limite'}:
                    access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                session.step = 'awaiting_document'
                session.filial = ''
                session.fantasia_query = ''
                session.fantasia_results = ()
                session.inadimplencia_client_summaries = ()
                session.inadimplencia_total_available = 0
                session.inadimplencia_list_context = ''
                session.inadimplencia_page = 1
                session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
                session.comodato_client_summaries = ()
                session.selected_visit_day = ''
                session.visit_day_options = ()
                session.visit_seller_summaries = ()
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                if session.search_context == 'inadimplencia':
                    return flow.OutgoingMessage(text='Digite o CPF ou CNPJ do cliente para consultar a inadimplencia.')
                if session.search_context == 'comodato':
                    return flow.OutgoingMessage(text='Digite o CPF ou CNPJ do cliente para consultar os comodatos pendentes.')
                if session.search_context == 'giro':
                    return flow.OutgoingMessage(text='Digite o CPF ou CNPJ do cliente para consultar o giro.')
                if session.search_context == 'documentacao':
                    return flow.OutgoingMessage(text='Digite o CPF ou CNPJ do cliente para consultar a documentacao pendente.')
                if session.search_context == 'prazo_limite':
                    return flow.OutgoingMessage(text='Digite o CPF ou CNPJ do cliente para consultar prazo e limite.')
                return flow.OutgoingMessage(text='Digite o CPF ou CNPJ do cliente.\nVou buscar pelo documento cadastrado, sem limitar por setor.')
            if session.search_context == 'giro' and normalized in {flow.SEARCH_BY_VISIT_DAY, '4', 'resumo por dia', 'dia de visita', 'visita', 'rota', 'oportunidade do giro', 'giro por dia', 'clientes com caixa', 'clientes com caixa do dia', 'giro cliente por cliente', 'giro clientes do dia'}:
                return self._open_giro_visit_day_conversation(sender=incoming.sender, session=session, decision=decision)
            if session.search_context == 'giro' and normalized in {flow.SEARCH_BY_GIRO_ZERO_BASE, '5', 'giro zero', 'giro zero da base', 'clientes com giro zero', 'mostrar giro zero', 'ver giro zero'}:
                return self._with_post_result_navigation(incoming.sender, session, self._build_giro_zero_base_response(decision), return_menu='search_menu')
            if session.search_context == 'documentacao' and normalized in {flow.SEARCH_BY_VISIT_DAY, '4', 'documentacao por dia', 'documentacao do dia', 'pendencia por dia', 'documentos por dia', 'documentacao segunda', 'documentacao terca', 'documentacao quarta', 'documentacao quinta', 'documentacao sexta', 'documentacao sabado', 'documentacao domingo'}:
                return self._open_documentacao_visit_day_conversation(sender=incoming.sender, session=session, decision=decision)
            if session.search_context == 'inadimplencia' and normalized in {flow.SEARCH_BY_INADIMPLENTES_BASE, 'inadimplentes da base', 'mostrar inadimplentes', 'ver inadimplentes', 'lista de inadimplentes'}:
                access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
                if access_error is not None:
                    self.sessions[incoming.sender] = session
                    return access_error
                return self._open_inadimplencia_summary_selection(sender=incoming.sender, session=session, decision=decision, order_by='total_pendente', header_text=f'Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.', empty_text='No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\nSe quiser tentar outra consulta, envie MENU.', page=1, page_size=flow.INADIMPLENCIA_PAGE_SIZE, list_context=flow.INADIMPLENCIA_CONTEXT_SCOPE_BASE)
            if session.search_context == 'inadimplencia':
                due_bucket = flow._parse_finance_due_bucket(normalized)
                if due_bucket in {'tomorrow', 'in_two_days'}:
                    return self._run_scoped_inadimplencia_due_bucket(sender=incoming.sender, session=session, decision=decision, due_bucket=due_bucket)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context=session.search_context, decision=decision, invalid_selection=True)
        recolha_response = self.recolha_flow.handle_idle_request(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if recolha_response is not None:
            return recolha_response
        if flow._looks_like_critica_command(normalized):
            return self.critica_flow.handle_command(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        estoque_response = self._maybe_handle_estoque_command(sender=incoming.sender, text=text, normalized=normalized, decision=decision)
        if estoque_response is not None:
            return estoque_response
        boleto_response = self._maybe_handle_boleto_command(sender=incoming.sender, text=text, normalized=normalized, decision=decision)
        if boleto_response is not None:
            return boleto_response
        if session.step == 'idle' and self._looks_like_idle_direct_registration_lookup(text=text, normalized=normalized):
            direct_lookup = flow._parse_direct_registration_lookup(text)
            if direct_lookup is not None:
                access_error = self._ensure_scoped_lookup_access(decision, search_context='cliente')
                if access_error is not None:
                    return access_error
                return self._run_repeatable_registration_lookup(sender=incoming.sender, session=session, decision=decision, search_context='cliente', filial=direct_lookup[0], cod_pdv=direct_lookup[1])
        conversational_response = self._maybe_handle_idle_conversation(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if conversational_response is not None:
            return conversational_response
        if session.step == 'idle' and (self._is_vendedor(decision) or self._is_armazem(decision)):
            selected_main_option = flow._select_interactive_option(text=text, normalized=normalized, options=self._build_main_menu(decision).options)
            if selected_main_option is not None:
                return self._run_intent_clarification_option(sender=incoming.sender, session=session, decision=decision, option_id=selected_main_option.option_id)
        main_menu_shortcuts = self._main_menu_shortcuts(decision)
        summary_option_id = self._main_menu_summary_option_id(decision)
        search_shortcut = main_menu_shortcuts.get(flow.MENU_SEARCH, '')
        inadimplencia_shortcut = main_menu_shortcuts.get(flow.MENU_INADIMPLENCIA, '')
        giro_shortcut = main_menu_shortcuts.get(flow.MENU_GIRO, '')
        documentacao_shortcut = main_menu_shortcuts.get(flow.MENU_DOCUMENTACAO, '')
        recolha_shortcut = main_menu_shortcuts.get(flow.MENU_RECOLHA, '')
        seller_financeiro_shortcut = main_menu_shortcuts.get(flow.MENU_SELLER_FINANCEIRO, '')
        visit_day_shortcut = main_menu_shortcuts.get(flow.MENU_VISIT_DAY, '')
        comodatos_shortcut = main_menu_shortcuts.get(flow.MENU_COMODATOS, '')
        summary_shortcut = main_menu_shortcuts.get(summary_option_id, '') if summary_option_id else ''
        seller_summary_shortcut = main_menu_shortcuts.get(flow.MENU_SELLER_SUMMARY, '')
        seller_risk_shortcut = main_menu_shortcuts.get(flow.MENU_SELLER_RISK, '')
        critica_shortcut = main_menu_shortcuts.get(flow.MENU_CRITICA, '')
        financeiro_shortcut = main_menu_shortcuts.get(flow.MENU_FINANCEIRO, '')
        armazem_shortcut = main_menu_shortcuts.get(flow.MENU_ARMAZEM, '')
        admin_shortcut = main_menu_shortcuts.get(flow.MENU_ADMIN_ACCESS, '')
        if normalized == flow.MENU_INADIMPLENCIA or (session.step == 'idle' and normalized in {value for value in {inadimplencia_shortcut, 'inadimplencia', 'inadimpl?ncia', 'inadimplente', 'devedor', 'cobranca', 'cobranca da carteira', 'cobranca da gerencia', 'cobran?a'} if value}):
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = 'awaiting_search_mode'
            session.search_context = 'inadimplencia'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(session, intent='search_inadimplencia', search_context='inadimplencia')
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context='inadimplencia', decision=decision)
        if normalized == flow.MENU_GIRO or (session.step == 'idle' and normalized in {value for value in {giro_shortcut, 'giro', 'menu giro', 'consultar giro', 'giro da gerencia'} if value}):
            readiness_error = self._ensure_search_context_ready('giro', decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = 'awaiting_search_mode'
            session.search_context = 'giro'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(session, intent='search_giro', search_context='giro')
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context='giro', decision=decision)
        if normalized == flow.MENU_DOCUMENTACAO or (session.step == 'idle' and normalized in {value for value in {documentacao_shortcut, 'documentacao', 'documentacao pendente', 'documentos pendentes', 'pendencia documental', 'documentos faltando'} if value}):
            readiness_error = self._ensure_search_context_ready('documentacao', decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = 'awaiting_search_mode'
            session.search_context = 'documentacao'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(session, intent='search_documentacao', search_context='documentacao')
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context='documentacao', decision=decision)
        if normalized == flow.MENU_RECOLHA or (session.step == 'idle' and normalized in {value for value in {recolha_shortcut, 'recolha', 'recolhas', 'solicitar recolha', 'solicitacao de recolha', 'pedido de recolha'} if value}):
            management_request = flow._parse_recolha_management_request(normalized)
            if management_request is not None:
                action, identifier = management_request
                if action == 'clear' and (not self._can_clear_recolhas(decision)):
                    return flow.OutgoingMessage(text='A limpeza geral de recolhas esta liberada apenas para admin, gerencia, diretoria ou financeiro sem restricao de filial.')
                if action == 'clear':
                    return self._open_recolha_clear_confirmation(sender=incoming.sender, session=session)
                if not self._can_view_recolhas(decision):
                    return flow.OutgoingMessage(text='Voce nao tem acesso ao gerenciamento de recolhas.')
                return self._open_recolha_delete_confirmation(sender=incoming.sender, session=session, identifier=identifier, decision=decision)
            if self._can_view_recolhas(decision) and flow._looks_like_recolha_list_request(normalized):
                return self._with_post_result_navigation(incoming.sender, session, self._build_recolhas_finance_response(request_text=normalized, sender=incoming.sender, decision=decision), return_menu='main')
            if not self._can_request_recolha(decision):
                return flow.OutgoingMessage(text='A solicitacao de recolha esta liberada para vendedor, GV e financeiro.\nSe voce for do financeiro, envie RECOLHAS para ver as solicitacoes.')
            return self._open_recolha_request(sender=incoming.sender, session=session, text=text, normalized=normalized, decision=decision)
        if normalized == flow.MENU_SELLER_FINANCEIRO or (session.step == 'idle' and (self._is_vendedor(decision) or self._is_gerente_vendas(decision)) and normalized in {value for value in {seller_financeiro_shortcut, 'financeiro', 'menu financeiro', 'financeiro vendedor', 'financeiro gv'} if value}):
            session.step = 'seller_finance_select_action'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return flow._build_seller_finance_menu_response()
        if normalized == flow.MENU_FINANCEIRO or (session.step == 'idle' and normalized in {value for value in {financeiro_shortcut, 'financeiro', 'financeiro menu', 'menu financeiro'} if value} and self._can_use_finance_menu(decision)):
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = 'finance_select_action'
            session.search_context = 'inadimplencia'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            session.finance_gv_options = ()
            session.summary_filial_options = ()
            session.visit_risk_day_options = ()
            session.visit_risk_summaries = ()
            session.selected_visit_risk_token = ''
            session.selected_visit_risk_label = ''
            self._remember_last_context(session, intent='finance_menu', search_context='inadimplencia')
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_finance_menu()
        if normalized == flow.MENU_VISIT_DAY or (session.step == 'idle' and normalized in {value for value in {visit_day_shortcut, 'visitas do dia', 'rota do dia', 'rota', 'visitas', 'dia de visita', 'dia de visita do vde'} if value} and self._can_use_visit_menu(decision)):
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            raw_visit_days = self.query_service.list_visit_days(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
            visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
            if not visit_days:
                self._reset_session(incoming.sender)
                return flow.OutgoingMessage(text='Nao encontrei dias de visita disponiveis para voce no momento.\nSe quiser fazer outra consulta, envie MENU.')
            session.step = 'awaiting_visit_day_selection'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.comodato_client_summaries = ()
            session.selected_visit_day = ''
            session.visit_day_options = tuple(visit_days)
            session.visit_seller_summaries = ()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)
        if normalized in {flow.MENU_GV_SUMMARY, flow.MENU_MANAGER} or (session.step == 'idle' and normalized in {value for value in {summary_shortcut, 'gerencia', 'menu gerencia', 'painel da gerencia', 'painel gerencia', 'gerente de vendas', 'menu gerente', 'resumo do gv', 'resumo gv', 'meu gv', 'meu resumo', 'resumo da gerencia', 'resumo dos gerentes', 'gerentes de vendas'} if value} and self._can_use_gv_summary_menu(decision)):
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            if self._is_gerente_vendas(decision):
                return self._open_manager_summary_menu(sender=incoming.sender, session=session)
            if self._is_diretor_comercial(decision):
                return self._open_director_summary_menu(sender=incoming.sender, session=session)
            self._reset_session(incoming.sender)
            return self._build_gv_summary_response(decision, title='Resumo da Gerencia')
        if normalized == flow.MENU_SELLER_SUMMARY or (session.step == 'idle' and normalized in {value for value in {seller_summary_shortcut, 'carteira', 'resumo da carteira', 'resumo carteira', 'minha carteira', 'meu resumo'} if value} and self._can_use_seller_summary_menu(decision)):
            access_error = self._ensure_scoped_lookup_access(decision, search_context='cliente')
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            return self._with_post_result_navigation(incoming.sender, session, self._build_seller_summary_response(decision), return_menu='main')
        if normalized == flow.MENU_SELLER_RISK or (session.step == 'idle' and normalized in {value for value in {seller_risk_shortcut, 'risco da rota', 'risco da carteira', 'clientes com risco hoje', 'risco hoje', 'rota com risco', 'clientes da rota com risco'} if value} and self._can_use_seller_risk_menu(decision)):
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
            return self._with_post_result_navigation(incoming.sender, session, self._build_seller_risk_response(decision), return_menu='main')
        if normalized == flow.MENU_CRITICA or (session.step == 'idle' and (self._is_vendedor(decision) or self._is_gerente_vendas(decision)) and normalized in {value for value in {critica_shortcut, 'critica', 'critica rn', 'menu critica'} if value}):
            readiness_error = self.critica_flow.ensure_ready(decision)
            if readiness_error is not None:
                return readiness_error
            session.step = 'awaiting_critica_action'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return flow._build_critica_menu_response()
        if normalized == flow.MENU_COMODATOS or (session.step == 'idle' and normalized in {value for value in {comodatos_shortcut, 'comodato', 'comodatos', 'pendencia de comodato', 'pendencias de comodato'} if value}):
            readiness_error = self._ensure_search_context_ready('comodato', decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
            session.step = 'awaiting_search_mode'
            session.search_context = 'comodato'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(session, intent='search_comodato', search_context='comodato')
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context='comodato', decision=decision)
        if normalized == flow.MENU_ADMIN_ACCESS or (session.step == 'idle' and normalized in {value for value in {admin_shortcut, '0', 'admin', 'administrador', 'cadastro_usuario'} if value}):
            return self.admin_access_flow.open_menu(sender=incoming.sender, session=session, decision=decision)
        if session.step in {'awaiting_filial', 'awaiting_cod_pdv', 'awaiting_fantasia', 'awaiting_fantasia_selection', 'awaiting_inadimplencia_client_selection', 'awaiting_comodato_client_selection', 'awaiting_visit_day_selection', 'visit_select_gv', 'awaiting_giro_visit_day_selection', 'awaiting_visit_seller_selection'}:
            access_error = None
            if session.step in {'awaiting_visit_day_selection', 'visit_select_gv', 'awaiting_visit_seller_selection'}:
                access_error = self._ensure_scoped_lookup_access(decision, search_context='cliente')
            elif session.search_context in {'inadimplencia', 'comodato'} or session.step != 'awaiting_fantasia_selection':
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self._reset_session(incoming.sender)
                return access_error
        if session.step == 'awaiting_document':
            readiness_error = self._ensure_search_context_ready(session.search_context, decision=decision)
            if readiness_error is not None:
                self._reset_session(incoming.sender)
                return readiness_error
        if session.step == 'awaiting_filial':
            direct_lookup = flow._parse_direct_registration_lookup(text)
            if direct_lookup is not None:
                return self._run_repeatable_registration_lookup(sender=incoming.sender, session=session, decision=decision, search_context=session.search_context, filial=direct_lookup[0], cod_pdv=direct_lookup[1])
            filial = flow._normalize_filial(text)
            if not filial:
                self.sessions[incoming.sender] = session
                return flow.OutgoingMessage(text=f'Nao reconheci essa filial.\n{flow._build_filial_prompt(session.search_context)}')
            session.step = 'awaiting_cod_pdv'
            session.filial = filial
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return flow.OutgoingMessage(text=f'Perfeito. Voce escolheu a revenda {flow._format_filial_label(filial)}.\nAgora me envie {flow._lookup_code_label(session.search_context)}. Se preferir, pode mandar assim: 3 6643.')
        if session.step == 'awaiting_cod_pdv':
            direct_lookup = flow._parse_direct_registration_lookup(text)
            if direct_lookup is not None:
                return self._run_repeatable_registration_lookup(sender=incoming.sender, session=session, decision=decision, search_context=session.search_context, filial=direct_lookup[0], cod_pdv=direct_lookup[1])
            cod_pdv = flow._normalize_cod_pdv(text)
            if not cod_pdv:
                self.sessions[incoming.sender] = session
                return flow.OutgoingMessage(text=f'Me envie {flow._lookup_code_label(session.search_context)} ou os dois juntos, por exemplo: 3 6643.')
            return self._run_repeatable_registration_lookup(sender=incoming.sender, session=session, decision=decision, search_context=session.search_context, filial=session.filial, cod_pdv=cod_pdv)
        if session.step == 'awaiting_fantasia':
            return self._run_name_search(sender=incoming.sender, session=session, decision=decision, query_text=text)
        if session.step == 'awaiting_fantasia_selection':
            selected_record = flow._select_fantasia_record(text=text, normalized=normalized, records=session.fantasia_results)
            if selected_record is None:
                self.sessions[incoming.sender] = session
                return self._build_fantasia_results_menu(query_text=session.fantasia_query, records=list(session.fantasia_results), search_context=session.search_context, invalid_selection=True)
            self._remember_last_context(session, intent=f'{session.search_context}_client', search_context=session.search_context, query_text=session.fantasia_query, client_filial=selected_record.filial, client_cod_pdv=selected_record.cod_pdv, client_name=selected_record.nome_fantasia or selected_record.razao_social)
            if session.search_context == 'giro':
                records = self.giro_service.search_by_registration(filial=selected_record.filial, cod_pdv=selected_record.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
                criteria = f"nome fantasia contendo '{session.fantasia_query}' | revenda {selected_record.filial} | NB {selected_record.cod_pdv}"
                if not records:
                    historical_response = self._build_giro_historical_fallback_response(decision=decision, filial=selected_record.filial, cod_pdv=selected_record.cod_pdv, criteria=criteria)
                    if historical_response is not None:
                        return self._with_post_result_navigation(incoming.sender, session, historical_response, return_menu='search_results')
                return self._with_post_result_navigation(incoming.sender, session, self._build_giro_response(records, criteria=criteria, scope_restricted=not self._has_unrestricted_lookup_access(decision)), return_menu='search_results')
            if session.search_context == 'documentacao':
                records = self.documentacao_pendente_service.search_by_registration(filial=selected_record.filial, cod_pdv=selected_record.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
                return self._with_post_result_navigation(incoming.sender, session, self._build_documentacao_pendente_response(records, criteria=f"nome fantasia contendo '{session.fantasia_query}' | revenda {selected_record.filial} | NB {selected_record.cod_pdv}", scope_restricted=not self._has_unrestricted_lookup_access(decision)), return_menu='search_results')
            if session.search_context == 'prazo_limite':
                records = self.prazo_limite_service.search_by_registration(filial=selected_record.filial, cod_pdv=selected_record.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
                return self._with_post_result_navigation(incoming.sender, session, self._build_prazo_limite_response(records, criteria=f"nome fantasia contendo '{session.fantasia_query}' | revenda {selected_record.filial} | NB {selected_record.cod_pdv}", decision=decision, scope_restricted=not self._has_unrestricted_lookup_access(decision)), return_menu='search_results')
            return self._with_post_result_navigation(incoming.sender, session, self._build_single_record_response(record=selected_record, criteria=f"nome fantasia contendo '{session.fantasia_query}'", decision=decision), return_menu='search_results')
        if session.step == 'awaiting_inadimplencia_client_selection':
            page_action = flow._parse_inadimplencia_page_action(normalized, session.inadimplencia_page_size)
            if session.inadimplencia_list_context in {flow.INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL, flow.INADIMPLENCIA_CONTEXT_SCOPE_BASE, flow.INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS} and page_action:
                total_pages = flow._compute_page_count(total_items=session.inadimplencia_total_available, page_size=session.inadimplencia_page_size)
                target_page = session.inadimplencia_page
                if page_action == 'next':
                    target_page = min(session.inadimplencia_page + 1, total_pages)
                elif page_action == 'prev':
                    target_page = max(session.inadimplencia_page - 1, 1)
                if target_page != session.inadimplencia_page:
                    if session.inadimplencia_list_context == flow.INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL:
                        header_text = flow._extract_inadimplencia_custom_header(session.fantasia_query) or 'Esses sao os clientes inadimplentes da base total.'
                        empty_text = 'No momento, nao encontrei clientes inadimplentes na base total.\nEscolha outra opcao ou envie MENU.'
                    elif session.inadimplencia_list_context == flow.INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS:
                        header_text = flow._extract_inadimplencia_custom_header(session.fantasia_query) or 'Esses sao os maiores devedores da sua diretoria.'
                        empty_text = 'No momento, nao encontrei clientes inadimplentes na sua diretoria.\nEscolha outra opcao ou envie MENU.'
                    else:
                        scope_label = flow._extract_inadimplencia_scope_label(session.fantasia_query) or self._inadimplencia_scope_label(decision)
                        header_text = flow._extract_inadimplencia_custom_header(session.fantasia_query) or f'Esses sao os clientes inadimplentes da {scope_label}.'
                        empty_text = 'No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\nEscolha outra opcao ou envie MENU.'
                    return self._open_inadimplencia_summary_selection(sender=incoming.sender, session=session, decision=decision, order_by='total_pendente', header_text=header_text, empty_text=empty_text, page=target_page, page_size=session.inadimplencia_page_size, list_context=session.inadimplencia_list_context, known_total_clients=session.inadimplencia_total_available)
                navigation_notice = 'Voce ja esta na ultima pagina.' if page_action == 'next' else 'Voce ja esta na primeira pagina.'
                self.sessions[incoming.sender] = session
                return self._build_inadimplencia_client_menu(query_text=session.fantasia_query, summaries=list(session.inadimplencia_client_summaries), total_available=session.inadimplencia_total_available, page=session.inadimplencia_page if session.inadimplencia_list_context else None, page_size=session.inadimplencia_page_size, list_context=session.inadimplencia_list_context, navigation_notice=navigation_notice)
            selected_summary = flow._select_inadimplencia_client_summary(text=text, normalized=normalized, summaries=session.inadimplencia_client_summaries)
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_inadimplencia_client_menu(query_text=session.fantasia_query, summaries=list(session.inadimplencia_client_summaries), total_available=session.inadimplencia_total_available, page=session.inadimplencia_page if session.inadimplencia_list_context else None, page_size=session.inadimplencia_page_size, list_context=session.inadimplencia_list_context, invalid_selection=True)
            self._remember_last_context(session, intent='inadimplencia_client', search_context='inadimplencia', query_text=session.fantasia_query, client_filial=selected_summary.filial, client_cod_pdv=selected_summary.cod_pdv, client_name=selected_summary.nome)
            records = self.inadimplencia_service.search_by_registration(filial=selected_summary.filial, cod_pdv=selected_summary.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
            return self._with_post_result_navigation(incoming.sender, session, self._build_inadimplencia_response(records, f'cliente {selected_summary.nome} | revenda {selected_summary.filial} | NB {selected_summary.cod_pdv}', compact=session.inadimplencia_list_context == flow.INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS), return_menu='inadimplencia_client_results')
        if session.step == 'awaiting_comodato_client_selection':
            selected_summary = flow._select_comodato_client_summary(text=text, normalized=normalized, summaries=session.comodato_client_summaries)
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_comodato_client_menu(query_text=session.fantasia_query, summaries=list(session.comodato_client_summaries), invalid_selection=True)
            self._remember_last_context(session, intent='comodato_client', search_context='comodato', query_text=session.fantasia_query, client_filial=selected_summary.filial, client_cod_pdv=selected_summary.cod_pdv, client_name=selected_summary.nome)
            records = self.comodatos_service.search_by_registration(filial=selected_summary.filial, cod_pdv=selected_summary.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
            return self._with_post_result_navigation(incoming.sender, session, self._build_comodato_response(records, f'cliente {selected_summary.nome} | revenda {selected_summary.filial} | NB {selected_summary.cod_pdv}'), return_menu='comodato_client_results')
        if session.step == 'awaiting_document':
            return self._run_document_lookup(sender=incoming.sender, session=session, decision=decision, document=text)
        if session.step == 'awaiting_visit_day_selection':
            selected_visit_day = self._select_visit_day_option(text=text, normalized=normalized, visit_days=session.visit_day_options, description='Ver clientes desse dia')
            if selected_visit_day is None:
                self.sessions[incoming.sender] = session
                return self._build_visit_day_menu(decision=decision, visit_days=list(session.visit_day_options), invalid_selection=True)
            return self._apply_visit_day_selection(sender=incoming.sender, session=session, decision=decision, selected_visit_day=selected_visit_day)
        if session.step == 'visit_select_gv':
            selected_gv = flow._select_finance_gv_option(text=text, normalized=normalized, gv_options=session.finance_gv_options)
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_visit_day_gv_menu(visit_day=session.selected_visit_day, visit_summaries=list(session.visit_group_summaries), gv_options=list(session.finance_gv_options), invalid_selection=True)
            filtered_summaries = [summary for summary in session.visit_group_summaries if (flow.normalize_stored_scope_value(summary.manager_code) or flow.normalize_stored_scope_value(summary.seller_code)) == flow.normalize_stored_scope_value(selected_gv)]
            if not filtered_summaries:
                self.sessions[incoming.sender] = session
                return self._build_grouped_visit_day_gv_menu(visit_day=session.selected_visit_day, visit_summaries=list(session.visit_group_summaries), gv_options=list(session.finance_gv_options), invalid_selection=True)
            session.step = 'awaiting_visit_seller_selection'
            session.visit_seller_summaries = tuple(filtered_summaries)
            session.selected_visit_gv = selected_gv
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_grouped_visit_day_sector_menu(visit_day=session.selected_visit_day, gv_code=selected_gv, visit_summaries=filtered_summaries)
        if session.step == 'awaiting_inadimplencia_visit_day_selection':
            selected_visit_day = self._select_visit_day_option(text=text, normalized=normalized, visit_days=session.visit_day_options, description='Ver a rota com risco financeiro desse dia')
            if selected_visit_day is None:
                self.sessions[incoming.sender] = session
                return self._build_inadimplencia_visit_day_menu(visit_days=list(session.visit_day_options), invalid_selection=True)
            return self._apply_inadimplencia_visit_day_selection(sender=incoming.sender, session=session, decision=decision, selected_visit_day=selected_visit_day)
        if session.step == 'awaiting_giro_visit_day_selection':
            selected_visit_day = self._select_visit_day_option(text=text, normalized=normalized, visit_days=session.visit_day_options, description='Ver resumo e clientes com caixa desse dia')
            if selected_visit_day is None:
                self.sessions[incoming.sender] = session
                return self._build_giro_visit_day_menu(visit_days=list(session.visit_day_options), invalid_selection=True)
            return self._apply_giro_visit_day_selection(sender=incoming.sender, session=session, decision=decision, selected_visit_day=selected_visit_day)
        if session.step == 'awaiting_documentacao_visit_day_selection':
            selected_visit_day = self._select_visit_day_option(text=text, normalized=normalized, visit_days=session.visit_day_options, description='Ver resumo e clientes com pendencia documental desse dia')
            if selected_visit_day is None:
                return self._build_documentacao_visit_day_menu(visit_days=list(session.visit_day_options), invalid_selection=True)
            return self._apply_documentacao_visit_day_selection(sender=incoming.sender, session=session, decision=decision, selected_visit_day=selected_visit_day)
        if session.step == 'giro_select_visit_gv':
            selected_gv = flow._select_giro_visit_gv_option(text=text, normalized=normalized, gv_options=session.finance_gv_options)
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_giro_visit_gv_menu(summary_text=session.giro_visit_summary_text, gv_options=list(session.finance_gv_options), sector_summaries=list(session.giro_visit_sector_summaries), invalid_selection=True)
            session.step = 'giro_select_visit_sector'
            session.selected_giro_visit_gv = selected_gv
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_grouped_giro_visit_sector_menu(summary_text=session.giro_visit_summary_text, gv_code=selected_gv, sector_summaries=list(session.giro_visit_sector_summaries))
        if session.step == 'giro_select_visit_sector':
            selected_sector = flow._select_giro_visit_sector_summary(text=text, normalized=normalized, summaries=session.giro_visit_sector_summaries, gv_code=session.selected_giro_visit_gv)
            if selected_sector is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_giro_visit_sector_menu(summary_text=session.giro_visit_summary_text, gv_code=session.selected_giro_visit_gv, sector_summaries=list(session.giro_visit_sector_summaries), invalid_selection=True)
            return self._with_post_result_navigation(incoming.sender, session, self._build_grouped_giro_visit_sector_response(decision=decision, visit_day=session.selected_visit_day, sector_summary=selected_sector), return_menu='giro_visit_sector')
        if session.step == 'documentacao_select_visit_gv':
            selected_gv = flow._select_documentacao_visit_gv_option(text=text, normalized=normalized, gv_options=session.finance_gv_options)
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_documentacao_visit_gv_menu(summary_text=session.documentacao_visit_summary_text, gv_options=list(session.finance_gv_options), sector_summaries=list(session.documentacao_visit_sector_summaries), invalid_selection=True)
            session.step = 'documentacao_select_visit_sector'
            session.selected_documentacao_visit_gv = selected_gv
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_grouped_documentacao_visit_sector_menu(gv_code=selected_gv, sector_summaries=list(session.documentacao_visit_sector_summaries))
        if session.step == 'documentacao_select_visit_sector':
            selected_sector = flow._select_documentacao_visit_sector_summary(text=text, normalized=normalized, summaries=session.documentacao_visit_sector_summaries, gv_code=session.selected_documentacao_visit_gv)
            if selected_sector is None:
                self.sessions[incoming.sender] = session
                return self._build_grouped_documentacao_visit_sector_menu(gv_code=session.selected_documentacao_visit_gv, sector_summaries=list(session.documentacao_visit_sector_summaries), invalid_selection=True)
            return self._with_post_result_navigation(incoming.sender, session, self._build_grouped_documentacao_visit_sector_response(visit_day=session.selected_visit_day, sector_summary=selected_sector, records=list(session.documentacao_visit_records)), return_menu='documentacao_visit_sector')
        if session.step == 'awaiting_visit_seller_selection':
            selected_summary = flow._select_visit_seller_summary(text=text, normalized=normalized, summaries=session.visit_seller_summaries)
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                if session.selected_visit_gv:
                    return self._build_grouped_visit_day_sector_menu(visit_day=session.selected_visit_day, gv_code=session.selected_visit_gv, visit_summaries=list(session.visit_seller_summaries), invalid_selection=True)
                return self._build_visit_day_manager_menu(session.selected_visit_day, list(session.visit_seller_summaries), invalid_selection=True)
            records = self.query_service.list_clients_by_visit_day_and_seller(visit_day=session.selected_visit_day, seller_code=selected_summary.seller_code, manager_code='' if selected_summary.manager_code == '-' else selected_summary.manager_code, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=80)
            financial_alerts, alerts_note = self._load_visit_day_financial_alerts(decision=decision, visit_day=session.selected_visit_day, seller_code=selected_summary.seller_code, manager_code='' if selected_summary.manager_code == '-' else selected_summary.manager_code)
            return self._with_post_result_navigation(incoming.sender, session, self._build_visit_day_seller_clients_response(visit_day=session.selected_visit_day, summary=selected_summary, records=records, decision=decision, financial_alerts=financial_alerts, alerts_note=alerts_note), return_menu='visit_day_seller')
        if session.step == 'awaiting_gv_summary_selection':
            selected_gv = flow._select_finance_gv_option(text=text, normalized=normalized, gv_options=session.finance_gv_options)
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_director_gv_summary_menu(gv_options=list(session.finance_gv_options), invalid_selection=True)
            self._reset_session(incoming.sender)
            return self._build_gv_summary_response(decision=decision, gv_vdes_override=(selected_gv,), title=f'Resumo do gerente {flow._format_gv_scope_label(selected_gv)}')
        if session.step == 'awaiting_manager_summary_mode':
            manager_action = flow._parse_manager_summary_action(normalized)
            if manager_action == 'total':
                return self._with_post_result_navigation(incoming.sender, session, self._build_gv_summary_response(decision=decision, title='Resumo Total da Gerencia'), return_menu='manager_summary')
            if manager_action == 'by_filial':
                return self._open_manager_filial_summary_selection(sender=incoming.sender, session=session, decision=decision)
            if manager_action == 'list':
                return self._open_inadimplencia_summary_selection(sender=incoming.sender, session=session, decision=decision, order_by='total_pendente', header_text='Esses sao os clientes inadimplentes da sua gerencia.', empty_text='No momento, nao encontrei clientes inadimplentes na sua gerencia.\nEscolha outra opcao ou envie MENU.', page=1, page_size=flow.INADIMPLENCIA_PAGE_SIZE, list_context=flow.INADIMPLENCIA_CONTEXT_SCOPE_BASE)
            if manager_action == 'upcoming':
                session.step = 'awaiting_manager_due_bucket'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_manager_due_menu()
            if manager_action == 'visit_risk':
                return self._open_manager_visit_risk_day_selection(sender=incoming.sender, session=session, decision=decision)
            if manager_action == 'by_seller':
                return self._open_manager_seller_summary_selection(sender=incoming.sender, session=session, decision=decision)
            if manager_action == 'giro':
                session.step = 'manager_select_giro_mode'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_manager_giro_menu()
            self.sessions[incoming.sender] = session
            return self._build_manager_summary_menu(invalid_selection=True)
        if session.step == 'awaiting_manager_filial_selection':
            selected_filial = flow._select_filial_option(text=text, normalized=normalized, filial_options=session.summary_filial_options)
            if selected_filial is None:
                self.sessions[incoming.sender] = session
                return self._build_manager_filial_summary_menu(filial_options=list(session.summary_filial_options), invalid_selection=True)
            selected_scope_keys = flow._filter_scope_codes_by_filial(decision.gv_vdes, selected_filial)
            return self._with_post_result_navigation(incoming.sender, session, self._build_gv_summary_response(decision=decision, gv_vdes_override=selected_scope_keys, title=f'Resumo da Gerencia | {flow._format_filial_label(selected_filial)}'), return_menu='manager_filial')
        if session.step == 'awaiting_manager_due_bucket':
            due_bucket = flow._parse_finance_due_bucket(normalized)
            if not due_bucket:
                self.sessions[incoming.sender] = session
                return self._build_manager_due_menu(invalid_selection=True)
            bucket_meta = {'in_two_days': {'header': 'Esses sao os clientes da sua gerencia que vencem em 2 dias.', 'empty': 'Nao encontrei clientes com vencimento em 2 dias na sua gerencia.\nEscolha outra faixa ou envie MENU.'}, 'tomorrow': {'header': 'Esses sao os clientes da sua gerencia que vencem amanha.', 'empty': 'Nao encontrei clientes com vencimento para amanha na sua gerencia.\nEscolha outra faixa ou envie MENU.'}, 'today': {'header': 'Esses sao os clientes da sua gerencia que vencem hoje.', 'empty': 'Nao encontrei clientes com vencimento hoje na sua gerencia.\nEscolha outra faixa ou envie MENU.'}, 'overdue': {'header': 'Esses sao os clientes da sua gerencia que ja estao vencidos.', 'empty': 'Nao encontrei clientes vencidos na sua gerencia.\nEscolha outra faixa ou envie MENU.'}}[due_bucket]
            return self._open_inadimplencia_summary_selection(sender=incoming.sender, session=session, decision=decision, order_by='total_pendente', due_bucket=due_bucket, header_text=bucket_meta['header'], empty_text=bucket_meta['empty'])
        if session.step == 'manager_select_visit_risk_day':
            selected_visit_risk_day = flow._select_visit_day(text=text, normalized=normalized, visit_days=session.visit_risk_day_options)
            if selected_visit_risk_day is None:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_day_menu(visit_days=list(session.visit_risk_day_options), menu_title='Risco da Rota', header_prompt='Escolha o dia da semana para ver o risco da rota da gerencia.', invalid_selection=True)
            visit_day_token = flow._visit_day_token_from_label(selected_visit_risk_day)
            if not visit_day_token:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_day_menu(visit_days=list(session.visit_risk_day_options), menu_title='Risco da Rota', header_prompt='Escolha o dia da semana para ver o risco da rota da gerencia.', invalid_selection=True)
            return self._open_manager_visit_risk_selection(sender=incoming.sender, session=session, decision=decision, visit_day_token=visit_day_token, visit_day_label=selected_visit_risk_day)
        if session.step == 'manager_select_visit_risk_gv':
            selected_gv = flow._select_finance_gv_option(text=text, normalized=normalized, gv_options=session.finance_gv_options)
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_gv_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), gv_options=list(session.finance_gv_options), summaries=list(session.visit_risk_summaries), menu_title='Risco da Rota', day_header_prefix='Risco da rota', invalid_selection=True)
            filtered_summaries = [summary for summary in session.visit_risk_summaries if flow.normalize_stored_scope_value(summary.manager_code) == flow.normalize_stored_scope_value(selected_gv)]
            if not filtered_summaries:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_gv_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), gv_options=list(session.finance_gv_options), summaries=list(session.visit_risk_summaries), menu_title='Risco da Rota', day_header_prefix='Risco da rota', invalid_selection=True)
            session.step = 'manager_select_visit_risk_sector'
            session.visit_risk_summaries = tuple(filtered_summaries)
            session.selected_visit_risk_gv = selected_gv
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_finance_visit_risk_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), summaries=filtered_summaries, menu_title='Risco da Rota', day_header_prefix='Risco da rota')
        if session.step == 'manager_select_visit_risk_sector':
            selected_summary = flow._select_finance_visit_risk_summary(text=text, normalized=normalized, summaries=session.visit_risk_summaries)
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_finance_visit_risk_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), summaries=list(session.visit_risk_summaries), menu_title='Risco da Rota', day_header_prefix='Risco da rota', invalid_selection=True)
            return self._with_post_result_navigation(incoming.sender, session, self._build_finance_visit_risk_sector_response(decision=decision, summary=selected_summary, visit_day_token=session.selected_visit_risk_token or flow._current_visit_day_token(), visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label()), return_menu='manager_visit_risk_sector')
        if session.step == 'awaiting_manager_seller_summary_selection':
            selected_summary = flow._select_visit_seller_summary(text=text, normalized=normalized, summaries=session.visit_seller_summaries)
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_manager_seller_summary_menu(seller_summaries=list(session.visit_seller_summaries), invalid_selection=True)
            return self._with_post_result_navigation(incoming.sender, session, self._build_manager_seller_summary_response(decision=decision, summary=selected_summary), return_menu='manager_seller')
        if session.step == 'manager_select_giro_mode':
            giro_mode = flow._parse_giro_mode(normalized)
            if giro_mode not in {'total', 'by_filial'}:
                self.sessions[incoming.sender] = session
                return self._build_manager_giro_menu(invalid_selection=True)
            if giro_mode == 'total':
                return self._with_post_result_navigation(incoming.sender, session, self._build_giro_total_response(decision, title='Resumo de Giro | Gerencia'), return_menu='manager_giro_menu')
            return self._with_post_result_navigation(incoming.sender, session, self._build_giro_by_filial_response(decision, title='Giro por Filial | Gerencia'), return_menu='manager_giro_menu')
        if session.step == 'awaiting_director_summary_mode':
            director_action = flow._parse_director_summary_action(normalized)
            if director_action == 'total':
                return self._with_post_result_navigation(incoming.sender, session, self._build_director_total_summary_response(decision), return_menu='director_summary')
            if director_action == 'by_revenda':
                return self._open_director_gv_summary_selection(sender=incoming.sender, session=session, decision=decision)
            if director_action == 'ranking':
                return self._with_post_result_navigation(incoming.sender, session, self._build_director_manager_ranking_response(decision), return_menu='director_summary')
            if director_action == 'visit_risk':
                return self._open_director_visit_risk_day_selection(sender=incoming.sender, session=session, decision=decision)
            if director_action == 'top_debtors':
                return self._open_inadimplencia_summary_selection(sender=incoming.sender, session=session, decision=decision, order_by='total_pendente', header_text='Esses sao os maiores devedores da sua diretoria.', empty_text='No momento, nao encontrei clientes inadimplentes na sua diretoria.\nEscolha outra opcao ou envie MENU.', page=1, page_size=flow.INADIMPLENCIA_PAGE_SIZE, list_context=flow.INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS)
            if director_action == 'by_filial':
                return self._with_post_result_navigation(incoming.sender, session, self._build_director_filial_summary_response(decision), return_menu='director_summary')
            if director_action == 'giro':
                session.step = 'director_select_giro_mode'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[incoming.sender] = session
                return self._build_director_giro_menu()
            self.sessions[incoming.sender] = session
            return self._build_director_summary_menu(invalid_selection=True)
        if session.step == 'director_select_visit_risk_day':
            selected_visit_risk_day = flow._select_visit_day(text=text, normalized=normalized, visit_days=session.visit_risk_day_options)
            if selected_visit_risk_day is None:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_day_menu(visit_days=list(session.visit_risk_day_options), invalid_selection=True)
            visit_day_token = flow._visit_day_token_from_label(selected_visit_risk_day)
            if not visit_day_token:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_day_menu(visit_days=list(session.visit_risk_day_options), invalid_selection=True)
            return self._open_director_visit_risk_gv_selection(sender=incoming.sender, session=session, decision=decision, visit_day_token=visit_day_token, visit_day_label=selected_visit_risk_day)
        if session.step == 'director_select_visit_risk_gv':
            selected_gv = flow._select_finance_gv_option(text=text, normalized=normalized, gv_options=session.finance_gv_options)
            if selected_gv is None:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_gv_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), gv_options=list(session.finance_gv_options), seller_summaries=list(session.visit_risk_summaries), invalid_selection=True)
            filtered_summaries = [summary for summary in session.visit_risk_summaries if flow.normalize_stored_scope_value(summary.manager_code) == flow.normalize_stored_scope_value(selected_gv)]
            if not filtered_summaries:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_gv_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), gv_options=list(session.finance_gv_options), seller_summaries=list(session.visit_risk_summaries), invalid_selection=True)
            session.step = 'director_select_visit_risk_sector'
            session.finance_gv_options = ()
            session.visit_risk_summaries = tuple(filtered_summaries)
            session.selected_visit_risk_gv = selected_gv
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_director_visit_risk_sector_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), summaries=filtered_summaries)
        if session.step == 'director_select_visit_risk_sector':
            selected_summary = flow._select_finance_visit_risk_summary(text=text, normalized=normalized, summaries=session.visit_risk_summaries)
            if selected_summary is None:
                self.sessions[incoming.sender] = session
                return self._build_director_visit_risk_sector_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), summaries=list(session.visit_risk_summaries), invalid_selection=True)
            return self._with_post_result_navigation(incoming.sender, session, self._build_director_visit_risk_sector_response(decision=decision, summary=selected_summary, visit_day_token=session.selected_visit_risk_token or flow._current_visit_day_token(), visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label()), return_menu='director_visit_risk_sector')
        if session.step == 'director_select_giro_mode':
            giro_mode = flow._parse_giro_mode(normalized)
            if giro_mode not in {'by_gv', 'by_filial'}:
                self.sessions[incoming.sender] = session
                return self._build_director_giro_menu(invalid_selection=True)
            if giro_mode == 'by_gv':
                return self._with_post_result_navigation(incoming.sender, session, self._build_giro_by_gv_response(decision, title='Giro por GV | Diretoria'), return_menu='director_giro_menu')
            return self._with_post_result_navigation(incoming.sender, session, self._build_giro_by_filial_response(decision, title='Giro por Filial | Diretoria'), return_menu='director_giro_menu')
        direct_lookup = flow._parse_direct_registration_lookup(text)
        if direct_lookup is not None:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='cliente')
            if access_error is not None:
                return access_error
            return self._run_repeatable_registration_lookup(sender=incoming.sender, session=session, decision=decision, search_context='cliente', filial=direct_lookup[0], cod_pdv=direct_lookup[1])
        direct_document = flow._normalize_document(text)
        if direct_document:
            readiness_error = self._ensure_search_context_ready('cliente', decision=decision)
            if readiness_error is not None:
                return readiness_error
            session.search_context = 'cliente'
            return self._run_document_lookup(sender=incoming.sender, session=session, decision=decision, document=direct_document)
        if normalized in {value for value in {flow.MENU_SEARCH, search_shortcut, 'buscar cliente', 'buscar'} if value}:
            readiness_error = self._ensure_search_context_ready('cliente', decision=decision)
            if readiness_error is not None:
                return readiness_error
            session.step = 'awaiting_search_mode'
            session.search_context = 'cliente'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
            session.comodato_client_summaries = ()
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.visit_seller_summaries = ()
            self._remember_last_context(session, intent='search_cliente', search_context='cliente')
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[incoming.sender] = session
            return self._build_search_menu(search_context='cliente', decision=decision)
        if normalized == flow.MENU_ARMAZEM or (
            session.step == 'idle'
            and (self._is_diretor_comercial(decision) or self._is_armazem(decision))
            and normalized in {value for value in {armazem_shortcut, 'menu armazem'} if value}
        ):
            return self._with_post_result_navigation(
                incoming.sender,
                session,
                self._run_estoque_020304_lookup(
                    filial='',
                    product_code='',
                    wants_pdf=False,
                    decision=decision,
                ),
                return_menu='main',
            )
        return self._build_main_menu(decision, invalid_selection=bool(normalized))

    def _maybe_handle_estoque_command(
        self,
        *,
        sender: str,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        if re.match(r"^(?:estoque|armazem)(?:\s|$)", str(normalized or "")) is None:
            return None
        session = self.sessions.get(sender, flow.LookupSession())
        numbers = re.findall(r"\d+", str(text or normalized or ""))
        filial = flow.normalize_numeric_code(numbers[0]) if numbers else ""
        product_code = flow.normalize_numeric_code(numbers[1]) if len(numbers) >= 2 else ""
        wants_pdf = bool(re.search(r"\bpdf\b", str(normalized or text or ""), flags=re.IGNORECASE))
        intent = "estoque_pdf" if wants_pdf else "estoque_product" if product_code else "estoque_menu"
        self._remember_last_context(session, intent=intent, search_context="estoque")
        outgoing = self._run_estoque_020304_lookup(
            filial=filial,
            product_code=product_code,
            wants_pdf=wants_pdf,
            decision=decision,
        )
        return self._with_post_result_navigation(
            sender,
            session,
            outgoing,
            return_menu="main",
        )

    def _run_estoque_020304_lookup(
        self,
        *,
        filial: str,
        product_code: str = "",
        wants_pdf: bool = False,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not filial:
            return flow.OutgoingMessage(
                text=(
                    "Estoque\n\n"
                    "Informe a filial e o codigo do produto.\n"
                    "Exemplo: estoque 3 13203\n"
                    "Tambem aceito: armazem 3 13203\n\n"
                    "Para receber o PDF completo, envie: estoque 3 pdf"
                )
            )
        if not (
            self._is_admin(decision)
            or self._is_vendedor(decision)
            or self._is_gerente_vendas(decision)
            or self._is_diretor_comercial(decision)
            or self._is_financeiro(decision)
            or self._is_armazem(decision)
        ):
            return flow.OutgoingMessage(
                text="Estoque\n\nEssa consulta esta liberada apenas para vendedores, gerentes de vendas, diretores comerciais, financeiro e armazem."
            )
        allowed_filiais = self._allowed_estoque_filiais(decision)
        if allowed_filiais is not None and filial not in allowed_filiais:
            return flow.OutgoingMessage(
                text=(
                    "Estoque\n\n"
                    f"Voce nao tem acesso ao estoque da filial {filial}.\n"
                    "Confira a filial ou solicite ajuste de acesso ao responsavel."
                )
            )

        estoque_service = getattr(self, "estoque_020304_service", None)
        if estoque_service is None:
            return flow.OutgoingMessage(text="A consulta de estoque ainda nao esta configurada.")
        status = estoque_service.status()
        if not status.get("ready"):
            return flow.OutgoingMessage(
                text=(
                    "Estoque\n\n"
                    "A base de estoque 020304 ainda nao foi importada.\n"
                    "Execute ou importe a rotina 020304_BOT no painel."
                )
            )
        if not wants_pdf and not product_code:
            return flow.OutgoingMessage(
                text=(
                    "Estoque\n\n"
                    "Informe o codigo do produto para consultar a quantidade.\n"
                    f"Exemplo: estoque {filial} 13203\n\n"
                    f"Para receber o PDF completo, envie: estoque {filial} pdf"
                )
            )
        if not wants_pdf:
            if status.get("items_available") is False:
                return flow.OutgoingMessage(
                    text=(
                        "Estoque\n\n"
                        "A base atual de estoque ainda nao tem consulta por produto.\n"
                        "Reimporte a rotina 020304_BOT para liberar essa busca."
                    )
                )
            try:
                record = estoque_service.get_product_stock(filial=filial, product_code=product_code)
            except Exception:
                flow.logger.exception(
                    "Falha ao consultar produto no estoque 020304",
                    extra={"filial": filial, "product_code": product_code},
                )
                return flow.OutgoingMessage(
                    text="Nao consegui consultar o estoque agora.\nTente novamente em instantes."
                )
            if record is None:
                return flow.OutgoingMessage(
                    text=(
                        "Estoque\n\n"
                        f"Nao encontrei o produto {product_code} na filial {filial}.\n"
                        f"Confira o codigo ou envie estoque {filial} pdf para ver o relatorio completo."
                    )
                )
            updated_label = self._format_estoque_datetime(getattr(record, "updated_at", None))
            filial_label = f"{record.filial} - {record.filial_nome}".strip(" -")
            text_lines = [
                "Estoque 020304",
                "",
                f"*Filial:* {filial_label or filial}",
                f"*Atualizado em:* {updated_label}",
                f"*Produto:* {record.codigo} - {record.descricao or '-'}",
                f"*Unidade:* {record.unidade or '-'}",
                "",
                "*Quantidade:*",
                f"- Disponivel: {self._format_estoque_quantity(record.disponivel)}",
                f"- Saidas: {self._format_estoque_quantity(record.saidas)}",
            ]
            if getattr(record, "linhas_encontradas", 1) > 1:
                text_lines.append(f"- Linhas encontradas: {record.linhas_encontradas}")
            return flow.OutgoingMessage(text="\n".join(text_lines))

        try:
            record = estoque_service.get_pdf_report(filial=filial)
        except Exception:
            flow.logger.exception("Falha ao consultar PDF de estoque 020304", extra={"filial": filial})
            return flow.OutgoingMessage(text="Nao consegui consultar o estoque agora.\nTente novamente em instantes.")
        if record is None or not getattr(record, "pdf_bytes", b""):
            return flow.OutgoingMessage(
                text=(
                    "Estoque\n\n"
                    f"Nao encontrei PDF de estoque importado para a filial {filial}.\n"
                    "Confira se a rotina 020304_BOT dessa filial ja foi importada."
                )
            )

        updated_label = self._format_estoque_datetime(getattr(record, "updated_at", None))
        filial_label = f"{record.filial} - {record.filial_nome}".strip(" -")
        text_lines = [
            "Estoque 020304",
            "",
            f"*Filial:* {filial_label or filial}",
            f"*Atualizado em:* {updated_label}",
            f"*Produtos:* {record.total_rows}",
            "",
            "Enviei o PDF em anexo.",
        ]
        filename = f"estoque-020304-filial-{record.filial or filial}.pdf"
        return flow.OutgoingMessage(
            kind="media",
            text="\n".join(text_lines),
            media_url=flow._build_pdf_data_url(record.pdf_bytes),
            media_type="document",
            media_caption=f"Estoque 020304 | Filial {record.filial or filial}",
            media_filename=filename,
        )

    def _format_estoque_quantity(self, value: Any) -> str:
        try:
            amount = int(value or 0)
        except (TypeError, ValueError):
            amount = 0
        return f"{amount:,}".replace(",", ".")

    def _format_estoque_datetime(self, value: Any) -> str:
        flow = _customer_flow_module()
        if value is None:
            return "-"
        parsed = value
        if isinstance(value, str):
            try:
                parsed = flow.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return value
        if not hasattr(parsed, "strftime"):
            return "-"
        if getattr(parsed, "tzinfo", None) is None:
            parsed = parsed.replace(tzinfo=flow.timezone.utc)
        return parsed.astimezone(flow.LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M")

    def _allowed_estoque_filiais(self, decision: AccessDecision) -> set[str] | None:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return None
        if self._is_financeiro(decision):
            allowed_filiais = flow._recolha_allowed_filiais_from_decision(decision)
            return allowed_filiais or None
        if self._is_armazem(decision):
            allowed_filiais = flow._recolha_allowed_filiais_from_decision(decision)
            return allowed_filiais or set()

        filial_codes: list[str] = []
        for code in flow.partition_filial_scopes(decision.sectors):
            filial_codes.append(code)
        for code in flow.partition_filial_scopes(decision.gv_vdes):
            filial_codes.append(code)
        for scope in tuple(decision.sectors or ()) + tuple(decision.gv_vdes or ()):
            pair = flow.split_scope_pair(scope)
            if pair:
                filial_codes.append(pair[0])

        return {flow.normalize_numeric_code(code) for code in filial_codes if flow.normalize_numeric_code(code)}

    def _open_boleto_registration_prompt(self, *, sender: str, session: LookupSession) -> OutgoingMessage:
        flow = _customer_flow_module()
        session.step = "awaiting_boleto_registration"
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return flow.OutgoingMessage(
            text=(
                "Solicitar Boleto\n\n"
                "Informe revenda e NB do cliente.\n"
                "Exemplo: 3 11305"
            )
        )

    def _handle_boleto_registration_input(
        self,
        *,
        sender: str,
        session: LookupSession,
        text: str,
        normalized: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        flow = _customer_flow_module()
        parsed = self._parse_boleto_registration_command(text=text, normalized=normalized)
        if parsed is None:
            parsed = flow._parse_direct_registration_lookup(text)
        if parsed is None:
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(
                text=(
                    "Nao entendi a revenda e o NB.\n"
                    "Envie nesse formato: 3 11305"
                )
            )
        filial, cod_pdv = parsed
        return self._run_boleto_registration_lookup(
            sender=sender,
            session=session,
            filial=filial,
            cod_pdv=cod_pdv,
            decision=decision,
        )

    def _maybe_handle_boleto_command(self, *, sender: str, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        parsed = self._parse_boleto_registration_command(text=text, normalized=normalized)
        if parsed is None:
            return None
        filial, cod_pdv = parsed
        session = self.sessions.get(sender, flow.LookupSession())
        return self._run_boleto_registration_lookup(
            sender=sender,
            session=session,
            filial=filial,
            cod_pdv=cod_pdv,
            decision=decision,
        )

    def _run_boleto_registration_lookup(
        self,
        *,
        sender: str,
        session: LookupSession,
        filial: str,
        cod_pdv: str,
        decision: AccessDecision,
    ) -> OutgoingMessage:
        flow = _customer_flow_module()
        boletos_service = getattr(self, "boletos_service", None)
        if boletos_service is None:
            return flow.OutgoingMessage(text="A consulta de boletos ainda nao esta configurada.\nSe quiser fazer outra consulta, envie MENU.")
        status = boletos_service.status()
        if not status.get("ready"):
            return flow.OutgoingMessage(text="A base de boletos ainda nao foi importada no painel admin.\nAssim que o PDF for validado e importado, eu consigo enviar normalmente.")
        allowed_sectors = None if self._has_unrestricted_lookup_access(decision) else self._allowed_sectors(decision)
        allowed_gv_vdes = None if self._has_unrestricted_lookup_access(decision) else self._allowed_gv_vdes(decision)
        try:
            records = boletos_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=20,
                include_pdf=False,
            )
        except Exception:
            flow.logger.exception("Falha ao consultar boleto", extra={"filial": filial, "cod_pdv": cod_pdv})
            return flow.OutgoingMessage(text="Nao consegui consultar esse boleto agora.\nTente novamente em instantes.")
        if not records:
            unrestricted_records = []
            try:
                if allowed_sectors is not None or allowed_gv_vdes is not None:
                    unrestricted_records = boletos_service.search_by_registration(
                        filial=filial,
                        cod_pdv=cod_pdv,
                        allowed_sectors=None,
                        allowed_gv_vdes=None,
                        limit=1,
                        include_pdf=False,
                    )
            except Exception:
                unrestricted_records = []
            if unrestricted_records:
                return flow.OutgoingMessage(text=f"Encontrei boleto para revenda {filial} e NB {cod_pdv}, mas ele nao esta dentro do seu acesso.\nSe quiser tentar outro cliente, envie boleto revenda NB.")
            return flow.OutgoingMessage(text=f"Nao ha boleto importado para revenda {filial} e NB {cod_pdv}.\nConfira se o PDF correto dessa operacao foi importado no painel ou tente outro cliente.")
        if len(records) > 1:
            session = self.sessions.get(sender, flow.LookupSession())
            session.step = "awaiting_boleto_selection"
            session.boleto_filial = filial
            session.boleto_cod_pdv = cod_pdv
            session.boleto_option_count = len(records)
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._format_boleto_selection_message(filial=filial, cod_pdv=cod_pdv, records=records)
        try:
            records_with_pdf = boletos_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=1,
                include_pdf=True,
            )
        except Exception:
            flow.logger.exception("Falha ao carregar PDF do boleto", extra={"filial": filial, "cod_pdv": cod_pdv})
            return flow.OutgoingMessage(text="Encontrei o boleto, mas nao consegui gerar o PDF agora.\nTente novamente em instantes.")
        if not records_with_pdf:
            return flow.OutgoingMessage(text="Essa lista de boletos mudou. Envie boleto revenda NB novamente para atualizar a consulta.")
        return self._build_boleto_media_response(record=records_with_pdf[0], requested_filial=filial, requested_cod_pdv=cod_pdv)

    def _handle_boleto_selection(self, *, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        option_text = str(normalized or text or "").strip()
        selection_kind, selected_index = self._parse_boleto_selection_option(option_text)
        if not selection_kind:
            return self._repeat_boleto_selection(session=session, decision=decision, invalid=True)
        if selection_kind == "single" and (selected_index is None or selected_index < 0 or selected_index >= int(session.boleto_option_count or 0)):
            return self._repeat_boleto_selection(session=session, decision=decision, invalid=True)
        boletos_service = getattr(self, "boletos_service", None)
        if boletos_service is None:
            self._reset_session(sender)
            return flow.OutgoingMessage(text="A consulta de boletos ainda nao esta configurada.\nSe quiser fazer outra consulta, envie MENU.")
        allowed_sectors = None if self._has_unrestricted_lookup_access(decision) else self._allowed_sectors(decision)
        allowed_gv_vdes = None if self._has_unrestricted_lookup_access(decision) else self._allowed_gv_vdes(decision)
        try:
            records = boletos_service.search_by_registration(
                filial=session.boleto_filial,
                cod_pdv=session.boleto_cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=20,
                include_pdf=True,
            )
        except Exception:
            flow.logger.exception("Falha ao consultar boleto selecionado", extra={"filial": session.boleto_filial, "cod_pdv": session.boleto_cod_pdv})
            self._reset_session(sender)
            return flow.OutgoingMessage(text="Nao consegui consultar esse boleto agora.\nTente novamente em instantes.")
        if selection_kind == "all_merged":
            self._reset_session(sender)
            return self._build_boleto_merged_media_response(
                records=records,
                requested_filial=session.boleto_filial,
                requested_cod_pdv=session.boleto_cod_pdv,
            )
        if selection_kind == "all_separate":
            self._reset_session(sender)
            return self._build_boleto_separate_media_response(
                records=records,
                requested_filial=session.boleto_filial,
                requested_cod_pdv=session.boleto_cod_pdv,
            )
        if selected_index is None or selected_index >= len(records):
            self._reset_session(sender)
            return flow.OutgoingMessage(text="Essa lista de boletos mudou. Envie boleto revenda NB novamente para atualizar a consulta.")
        record = records[selected_index]
        self._reset_session(sender)
        return self._build_boleto_media_response(record=record, requested_filial=session.boleto_filial, requested_cod_pdv=session.boleto_cod_pdv)

    def _repeat_boleto_selection(self, *, session: LookupSession, decision: AccessDecision, invalid: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        boletos_service = getattr(self, "boletos_service", None)
        if boletos_service is None:
            return flow.OutgoingMessage(text="A consulta de boletos ainda nao esta configurada.\nSe quiser fazer outra consulta, envie MENU.")
        allowed_sectors = None if self._has_unrestricted_lookup_access(decision) else self._allowed_sectors(decision)
        allowed_gv_vdes = None if self._has_unrestricted_lookup_access(decision) else self._allowed_gv_vdes(decision)
        records = boletos_service.search_by_registration(
            filial=session.boleto_filial,
            cod_pdv=session.boleto_cod_pdv,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=20,
            include_pdf=False,
        )
        prefix = "Opcao invalida.\n\n" if invalid else ""
        return self._format_boleto_selection_message(
            filial=session.boleto_filial,
            cod_pdv=session.boleto_cod_pdv,
            records=records,
            prefix=prefix,
        )

    def _format_boleto_selection_message(self, *, filial: str, cod_pdv: str, records: list[Any], prefix: str = "") -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = [
            f"{prefix}Boletos encontrados",
            "",
            f"*Revenda:* {filial} | *NB:* {cod_pdv}",
            f"*Total:* {len(records)} boleto(s)",
            "",
        ]
        for index, record in enumerate(records, start=1):
            due_label = record.vencimento.strftime("%d/%m") if record.vencimento else "-"
            nf_label = getattr(record, "nota_fiscal", "") or "-"
            value_label = self._format_boleto_money(record.valor_centavos)
            lines.append(f"{index} - NF {nf_label} | Venc {due_label} | {value_label}")
        lines.extend(
            [
                "",
                "Responda com:",
                "- numero do boleto para receber apenas um",
                "- TODOS JUNTOS para receber um unico PDF",
                "- TODOS SEPARADOS para receber um PDF por boleto",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_boleto_media_response(self, *, record: Any, requested_filial: str, requested_cod_pdv: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        encoded_pdf = base64.b64encode(record.pdf_bytes).decode("ascii")
        due_label = record.vencimento.strftime("%d/%m/%Y") if record.vencimento else "-"
        document_date_label = record.data_documento.strftime("%d/%m/%Y") if getattr(record, "data_documento", None) else "-"
        value_label = self._format_boleto_money(record.valor_centavos)
        text_lines = [
            "Boleto encontrado",
            "",
            f"*Revenda:* {record.filial or requested_filial} | *NB:* {record.cod_pdv or requested_cod_pdv}",
            f"*Cliente:* {record.pagador or '-'}",
            f"*Setor:* {record.setor or '-'} | *GV:* {record.gv or '-'}",
            f"*Mapa:* {getattr(record, 'mapa', '') or '-'} | *NF:* {getattr(record, 'nota_fiscal', '') or '-'}",
            f"*Data doc.:* {document_date_label}",
            f"*Vencimento:* {due_label}",
            f"*Valor:* {value_label}",
            f"*Nosso numero:* {record.nosso_numero or '-'}",
            "",
            "Estou enviando o PDF em anexo.",
        ]
        return flow.OutgoingMessage(
            kind="media",
            text="\n".join(text_lines),
            media_url=f"data:application/pdf;base64,{encoded_pdf}",
            media_type="document",
            media_caption=f"Boleto NB {record.cod_pdv or requested_cod_pdv}",
            media_filename=f"boleto-{record.filial or requested_filial}-{record.cod_pdv or requested_cod_pdv}.pdf",
        )

    def _build_boleto_merged_media_response(self, *, records: list[Any], requested_filial: str, requested_cod_pdv: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        pdf_bytes = self._merge_boleto_pdf_bytes(records)
        if not pdf_bytes:
            return flow.OutgoingMessage(text="Encontrei os boletos, mas nao consegui gerar os PDFs agora.\nTente novamente em instantes.")
        encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
        total_value = sum(int(getattr(record, "valor_centavos", 0) or 0) for record in records)
        text_lines = [
            "Boletos encontrados",
            "",
            f"*Revenda:* {requested_filial} | *NB:* {requested_cod_pdv}",
            f"*Total:* {len(records)} boleto(s)",
            f"*Valor total:* {self._format_boleto_money(total_value)}",
            "",
            "Estou enviando todos os boletos juntos em um unico PDF.",
        ]
        return flow.OutgoingMessage(
            kind="media",
            text="\n".join(text_lines),
            media_url=f"data:application/pdf;base64,{encoded_pdf}",
            media_type="document",
            media_caption=f"Boletos NB {requested_cod_pdv}",
            media_filename=f"boletos-{requested_filial}-{requested_cod_pdv}.pdf",
        )

    def _build_boleto_separate_media_response(self, *, records: list[Any], requested_filial: str, requested_cod_pdv: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        attachments = []
        for index, record in enumerate(records, start=1):
            pdf_bytes = bytes(getattr(record, "pdf_bytes", b"") or b"")
            if not pdf_bytes:
                continue
            nf_label = str(getattr(record, "nota_fiscal", "") or index)
            encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
            attachments.append(
                flow.MediaAttachment(
                    media_url=f"data:application/pdf;base64,{encoded_pdf}",
                    media_type="document",
                    media_caption=f"Boleto {index} NB {record.cod_pdv or requested_cod_pdv} NF {nf_label}",
                    media_filename=f"boleto-{record.filial or requested_filial}-{record.cod_pdv or requested_cod_pdv}-nf-{nf_label}.pdf",
                )
            )
        if not attachments:
            return flow.OutgoingMessage(text="Encontrei os boletos, mas nao consegui gerar os PDFs agora.\nTente novamente em instantes.")
        total_value = sum(int(getattr(record, "valor_centavos", 0) or 0) for record in records)
        text_lines = [
            "Boletos encontrados",
            "",
            f"*Revenda:* {requested_filial} | *NB:* {requested_cod_pdv}",
            f"*Total:* {len(attachments)} boleto(s)",
            f"*Valor total:* {self._format_boleto_money(total_value)}",
            "",
            "Estou enviando todos os boletos separadamente.",
        ]
        first = attachments[0]
        return flow.OutgoingMessage(
            kind="media",
            text="\n".join(text_lines),
            media_url=first.media_url,
            media_type=first.media_type,
            media_caption=first.media_caption,
            media_filename=first.media_filename,
            extra_media=tuple(attachments[1:]),
        )

    def _merge_boleto_pdf_bytes(self, records: list[Any]) -> bytes:
        writer = PdfWriter()
        for record in records:
            pdf_bytes = bytes(getattr(record, "pdf_bytes", b"") or b"")
            if not pdf_bytes:
                continue
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
        if len(writer.pages) == 0:
            return b""
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def _parse_boleto_selection_option(self, value: str) -> tuple[str, int | None]:
        normalized = str(value or "").strip().lower()
        if normalized in {"0", "todos", "todos juntos", "junto", "juntos", "pdf unico", "unico", "unica", "todos em um", "todos em 1"}:
            return "all_merged", None
        if normalized in {"00", "todos separados", "separados", "separado", "individual", "individuais", "um por um", "cada um"}:
            return "all_separate", None
        if re.fullmatch(r"\d{1,2}", normalized):
            return "single", int(normalized) - 1
        return "", None

    def _parse_boleto_registration_command(self, *, text: str, normalized: str) -> tuple[str, str] | None:
        value = str(normalized or text or "").strip().lower()
        if not value.startswith("boleto"):
            return None
        numbers = [item for item in re.findall(r"\d+", value)]
        if len(numbers) < 2:
            return None
        return numbers[0], numbers[1]

    def _format_boleto_money(self, cents: int) -> str:
        amount = max(int(cents or 0), 0) / 100
        return f"R$ {amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def _looks_like_idle_direct_registration_lookup(self, *, text: str, normalized: str) -> bool:
        flow = _customer_flow_module()
        value = str(normalized or text or "").strip().lower()
        if flow._parse_payip_action(value) in {"validate_day", "import_batch", "routes"}:
            return False
        numbers = re.findall(r"\d+", value)
        if len(numbers) != 2:
            return False
        if re.fullmatch(r"\d{1,4}\D+\d{2,}", value):
            return True
        return bool(
            re.fullmatch(
                r"(?:revenda|filial)\D*\d{1,4}\D*(?:nb|cod(?:igo)?\s*pdv)\D*\d{2,}",
                value,
            )
        )

    def _maybe_handle_idle_conversation(self, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        if session.step != 'idle':
            return None
        if flow._looks_like_plain_numeric_choice(normalized):
            return None
        admin_response = self.admin_access_flow.handle_idle_request(sender=sender, session=session, text=text, normalized=normalized, decision=decision)
        if admin_response is not None:
            return admin_response
        low_confidence_response = self._maybe_handle_idle_low_confidence_request(sender=sender, session=session, normalized=normalized, decision=decision)
        if low_confidence_response is not None:
            return low_confidence_response
        if self._can_use_finance_menu(decision) and flow._looks_like_finance_request(normalized):
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_menu', search_context='inadimplencia')
            self.sessions[sender] = session
            request = flow._parse_hybrid_finance_request(normalized)
            if not request.action and (not request.clarify_today):
                return self._build_finance_menu()
            return self.finance_flow.handle_session(sender=sender, session=session, text=text, normalized=normalized, decision=decision)
        if self._can_use_visit_menu(decision) and flow._looks_like_visit_day_request(normalized):
            requested_day_label = flow._extract_requested_visit_day_label(normalized)
            return self._open_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=requested_day_label)
        search_context = flow._detect_explicit_search_context(normalized)
        if not search_context:
            return None
        readiness_error = self._ensure_search_context_ready(search_context, decision=decision)
        if readiness_error is not None:
            self._reset_session(sender)
            return readiness_error
        self._prepare_search_session(session, search_context=search_context)
        self.sessions[sender] = session
        request = flow._parse_hybrid_search_request(text=text, normalized_text=normalized, search_context=search_context, allow_contextless_query=False)
        if request is None:
            return self._build_search_menu(search_context=search_context, decision=decision)
        return self._maybe_handle_search_mode_conversation(sender=sender, session=session, text=text, normalized=normalized, decision=decision)
