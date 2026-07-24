from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class NavigationFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def _handle_menu_back_navigation(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        if session.step == 'awaiting_post_result_navigation':
            return self._resume_post_result_navigation(sender=sender, session=session, decision=decision)
        if session.step in {'awaiting_filial', 'awaiting_cod_pdv', 'awaiting_fantasia', 'awaiting_document', 'awaiting_fantasia_selection', 'awaiting_comodato_client_selection'}:
            session.step = 'awaiting_search_mode'
            session.filial = ''
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.comodato_client_summaries = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context=session.search_context, decision=decision)
        if session.step == 'awaiting_inadimplencia_client_selection':
            session.step = 'awaiting_search_mode'
            session.fantasia_query = ''
            session.fantasia_results = ()
            session.inadimplencia_client_summaries = ()
            session.inadimplencia_total_available = 0
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context='inadimplencia', decision=decision)
        if session.step == 'awaiting_inadimplencia_visit_day_selection':
            session.step = 'awaiting_search_mode'
            session.return_menu = ''
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context='inadimplencia', decision=decision)
        if session.step in {'awaiting_search_mode', 'awaiting_visit_day_selection'}:
            self._reset_session(sender)
            return self._build_main_menu(decision)
        if session.step == 'visit_select_gv':
            session.step = 'awaiting_visit_day_selection'
            session.visit_group_summaries = ()
            session.visit_seller_summaries = ()
            session.finance_gv_options = ()
            session.selected_visit_gv = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                self._reset_session(sender)
                return self._build_main_menu(decision)
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)
        if session.step == 'awaiting_giro_visit_day_selection':
            session.step = 'awaiting_search_mode'
            session.return_menu = ''
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context='giro', decision=decision)
        if session.step == 'awaiting_documentacao_visit_day_selection':
            session.step = 'awaiting_search_mode'
            session.return_menu = ''
            session.selected_visit_day = ''
            session.visit_day_options = ()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context='documentacao', decision=decision)
        if session.step == 'giro_select_visit_gv':
            session.step = 'awaiting_giro_visit_day_selection'
            session.finance_gv_options = ()
            session.giro_visit_sector_summaries = ()
            session.giro_visit_summary_text = ''
            session.selected_giro_visit_gv = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_giro_visit_day_menu(visit_days=list(session.visit_day_options))
        if session.step == 'giro_select_visit_sector':
            session.step = 'giro_select_visit_gv'
            session.selected_giro_visit_gv = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_giro_visit_gv_menu(summary_text=session.giro_visit_summary_text, gv_options=list(session.finance_gv_options), sector_summaries=list(session.giro_visit_sector_summaries))
        if session.step == 'documentacao_select_visit_gv':
            session.step = 'awaiting_documentacao_visit_day_selection'
            session.finance_gv_options = ()
            session.documentacao_visit_sector_summaries = ()
            session.documentacao_visit_records = ()
            session.documentacao_visit_summary_text = ''
            session.selected_documentacao_visit_gv = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_documentacao_visit_day_menu(visit_days=list(session.visit_day_options))
        if session.step == 'documentacao_select_visit_sector':
            if len(session.finance_gv_options) > 1:
                session.step = 'documentacao_select_visit_gv'
                session.selected_documentacao_visit_gv = ''
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_grouped_documentacao_visit_gv_menu(summary_text=session.documentacao_visit_summary_text, gv_options=list(session.finance_gv_options), sector_summaries=list(session.documentacao_visit_sector_summaries))
            session.step = 'awaiting_documentacao_visit_day_selection'
            session.finance_gv_options = ()
            session.documentacao_visit_sector_summaries = ()
            session.documentacao_visit_records = ()
            session.documentacao_visit_summary_text = ''
            session.selected_documentacao_visit_gv = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_documentacao_visit_day_menu(visit_days=list(session.visit_day_options))
        if session.step == 'awaiting_intent_clarification':
            self._reset_session(sender)
            return self._build_main_menu(decision)
        if session.step == 'awaiting_visit_seller_selection':
            if session.selected_visit_gv and len(session.finance_gv_options) > 1:
                session.step = 'visit_select_gv'
                session.visit_seller_summaries = ()
                session.selected_visit_gv = ''
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_grouped_visit_day_gv_menu(visit_day=session.selected_visit_day, visit_summaries=list(session.visit_group_summaries), gv_options=list(session.finance_gv_options))
            session.step = 'awaiting_visit_day_selection'
            session.visit_seller_summaries = ()
            session.visit_group_summaries = ()
            session.finance_gv_options = ()
            session.selected_visit_gv = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                try:
                    raw_visit_days = self.query_service.list_visit_days(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
                    visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
                except RuntimeError:
                    self._reset_session(sender)
                    return self._build_main_menu(decision)
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)
        if session.step == 'awaiting_manager_summary_mode':
            self._reset_session(sender)
            return self._build_main_menu(decision)
        if session.step in {'awaiting_manager_filial_selection', 'awaiting_manager_due_bucket', 'manager_select_visit_risk_day', 'awaiting_manager_seller_summary_selection', 'manager_select_giro_mode'}:
            return self._open_manager_summary_menu(sender=sender, session=session)
        if session.step == 'manager_select_visit_risk_gv':
            return self._open_manager_visit_risk_day_selection(sender=sender, session=session, decision=decision)
        if session.step == 'manager_select_visit_risk_sector':
            if session.selected_visit_risk_gv and len(session.finance_gv_options) > 1:
                return self._open_manager_visit_risk_selection(sender=sender, session=session, decision=decision, visit_day_token=session.selected_visit_risk_token or flow._current_visit_day_token(), visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label())
            return self._open_manager_visit_risk_day_selection(sender=sender, session=session, decision=decision)
        if session.step in {'awaiting_director_summary_mode', 'awaiting_gv_summary_selection'}:
            if session.step == 'awaiting_gv_summary_selection':
                return self._open_director_summary_menu(sender=sender, session=session)
            self._reset_session(sender)
            return self._build_main_menu(decision)
        if session.step == 'director_select_giro_mode':
            return self._open_director_summary_menu(sender=sender, session=session)
        if session.step == 'director_select_visit_risk_day':
            return self._open_director_summary_menu(sender=sender, session=session)
        if session.step == 'director_select_visit_risk_gv':
            return self._open_director_visit_risk_day_selection(sender=sender, session=session, decision=decision)
        if session.step == 'director_select_visit_risk_sector':
            return self._open_director_visit_risk_gv_selection(sender=sender, session=session, decision=decision, visit_day_token=session.selected_visit_risk_token or flow._current_visit_day_token(), visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label())
        if session.step == 'finance_select_visit_risk_gv':
            return self._open_finance_visit_risk_day_selection(sender=sender, session=session, decision=decision)
        if session.step == 'finance_select_visit_risk_sector':
            if session.selected_visit_risk_gv and len(session.finance_gv_options) > 1:
                return self._open_finance_visit_risk_selection(sender=sender, session=session, decision=decision, visit_day_token=session.selected_visit_risk_token or flow._current_visit_day_token(), visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label())
            return self._open_finance_visit_risk_day_selection(sender=sender, session=session, decision=decision)
        return None

    def _resume_post_result_navigation(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        return_menu = session.return_menu
        session.repeat_action = ''
        if not return_menu:
            self._reset_session(sender)
            return self._build_main_menu(decision)
        if return_menu == 'main':
            self._reset_session(sender)
            return self._build_main_menu(decision)
        if return_menu == 'search_menu':
            session.step = 'awaiting_search_mode'
            session.return_menu = ''
            session.filial = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_search_menu(search_context=session.search_context, decision=decision)
        if return_menu == 'search_results':
            session.step = 'awaiting_fantasia_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if not session.fantasia_results:
                return self._build_search_menu(search_context=session.search_context, decision=decision)
            return self._build_fantasia_results_menu(query_text=session.fantasia_query, records=list(session.fantasia_results), search_context=session.search_context)
        if return_menu == 'inadimplencia_client_results':
            session.step = 'awaiting_inadimplencia_client_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if not session.inadimplencia_client_summaries:
                return self._build_search_menu(search_context='inadimplencia', decision=decision)
            return self._build_inadimplencia_client_menu(query_text=session.fantasia_query, summaries=list(session.inadimplencia_client_summaries), total_available=session.inadimplencia_total_available, page=session.inadimplencia_page if session.inadimplencia_list_context else None, page_size=session.inadimplencia_page_size, list_context=session.inadimplencia_list_context)
        if return_menu == 'comodato_client_results':
            session.step = 'awaiting_comodato_client_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if not session.comodato_client_summaries:
                return self._build_search_menu(search_context='comodato', decision=decision)
            return self._build_comodato_client_menu(query_text=session.fantasia_query, summaries=list(session.comodato_client_summaries))
        if return_menu == 'visit_day_menu':
            session.step = 'awaiting_visit_day_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_main_menu(decision)
            return self._build_visit_day_menu(decision=decision, visit_days=visit_days)
        if return_menu == 'giro_visit_day_menu':
            session.step = 'awaiting_giro_visit_day_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_search_menu(search_context='giro', decision=decision)
            return self._build_giro_visit_day_menu(visit_days=visit_days)
        if return_menu == 'documentacao_visit_day_menu':
            session.step = 'awaiting_documentacao_visit_day_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_search_menu(search_context='documentacao', decision=decision)
            return self._build_documentacao_visit_day_menu(visit_days=visit_days)
        if return_menu == 'giro_visit_sector':
            session.step = 'giro_select_visit_sector'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_giro_visit_sector_menu(summary_text=session.giro_visit_summary_text, gv_code=session.selected_giro_visit_gv, sector_summaries=list(session.giro_visit_sector_summaries))
        if return_menu == 'documentacao_visit_sector':
            session.step = 'documentacao_select_visit_sector'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_documentacao_visit_sector_menu(gv_code=session.selected_documentacao_visit_gv, sector_summaries=list(session.documentacao_visit_sector_summaries))
        if return_menu == 'inadimplencia_visit_day_menu':
            session.step = 'awaiting_inadimplencia_visit_day_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            visit_days = list(session.visit_day_options)
            if not visit_days:
                return self._build_search_menu(search_context='inadimplencia', decision=decision)
            return self._build_inadimplencia_visit_day_menu(visit_days=visit_days)
        if return_menu == 'visit_day_seller':
            session.step = 'awaiting_visit_seller_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if not session.visit_seller_summaries:
                return self._build_visit_day_menu(decision=decision, visit_days=list(session.visit_day_options))
            if session.selected_visit_gv:
                return self._build_grouped_visit_day_sector_menu(visit_day=session.selected_visit_day, gv_code=session.selected_visit_gv, visit_summaries=list(session.visit_seller_summaries))
            return self._build_visit_day_manager_menu(visit_day=session.selected_visit_day, visit_summaries=list(session.visit_seller_summaries))
        if return_menu == 'finance_menu':
            session.step = 'finance_select_action'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_menu()
        if return_menu == 'finance_summary_menu':
            session.step = 'finance_select_summary_mode'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_summary_menu()
        if return_menu == 'finance_gv_summary':
            session.step = 'finance_select_gv_summary'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_gv_summary_menu(gv_options=list(session.finance_gv_options))
        if return_menu == 'finance_giro_menu':
            session.step = 'finance_select_giro_mode'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_giro_menu()
        if return_menu == 'finance_payip_menu':
            session.step = 'finance_payip_menu'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_menu()
        if return_menu == 'finance_visit_risk_sector':
            session.step = 'finance_select_visit_risk_sector'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), summaries=list(session.visit_risk_summaries))
        if return_menu == 'manager_summary':
            return self._open_manager_summary_menu(sender=sender, session=session)
        if return_menu == 'manager_filial':
            session.step = 'awaiting_manager_filial_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_manager_filial_summary_menu(filial_options=list(session.summary_filial_options))
        if return_menu == 'manager_seller':
            session.step = 'awaiting_manager_seller_summary_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_manager_seller_summary_menu(seller_summaries=list(session.visit_seller_summaries))
        if return_menu == 'manager_giro_menu':
            session.step = 'manager_select_giro_mode'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_manager_giro_menu()
        if return_menu == 'manager_visit_risk_sector':
            session.step = 'manager_select_visit_risk_sector'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), summaries=list(session.visit_risk_summaries))
        if return_menu == 'director_summary':
            return self._open_director_summary_menu(sender=sender, session=session)
        if return_menu == 'director_gv_summary':
            session.step = 'awaiting_gv_summary_selection'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_director_gv_summary_menu(gv_options=list(session.finance_gv_options))
        if return_menu == 'director_giro_menu':
            session.step = 'director_select_giro_mode'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_director_giro_menu()
        if return_menu == 'director_visit_risk_sector':
            session.step = 'director_select_visit_risk_sector'
            session.return_menu = ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_director_visit_risk_sector_menu(visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(), summaries=list(session.visit_risk_summaries))
        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _repeat_post_result_navigation(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        repeat_action = session.repeat_action
        if repeat_action:
            session.return_menu = ''
            session.repeat_action = ''
        if repeat_action == flow.REPEAT_SEARCH_REGISTRATION:
            return self._activate_search_mode(sender, session, search_mode='registration')
        if repeat_action == flow.REPEAT_SEARCH_DOCUMENT:
            return self._activate_search_mode(sender, session, search_mode='document')
        if repeat_action == flow.REPEAT_SEARCH_NAME:
            return self._activate_search_mode(sender, session, search_mode='name')
        if repeat_action == flow.REPEAT_PAYIP_INVOICE:
            session.step = 'finance_payip_awaiting_invoice'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_invoice_prompt()
        if repeat_action in {flow.REPEAT_PAYIP_PENDING_CLIENT, flow.REPEAT_PAYIP_CLIENT}:
            pending_only = repeat_action == flow.REPEAT_PAYIP_PENDING_CLIENT
            session.step = 'finance_payip_awaiting_client_code'
            session.payip_pending_status = 'PENDING' if pending_only else ''
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(pending_only=pending_only)
        if repeat_action == flow.REPEAT_PAYIP_CREATE_CHARGE:
            session.step = 'finance_payip_charge_awaiting_client'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_client_prompt()
        if repeat_action == flow.REPEAT_PAYIP_CREATE_CLIENT:
            session.step = 'finance_payip_create_client_awaiting_registration'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self.finance_flow.payip_flow._build_payip_create_client_prompt()
        if repeat_action == flow.REPEAT_PAYIP_STATEMENT:
            session.step = 'finance_payip_statement_awaiting_period'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_statement_prompt()
        if repeat_action == flow.REPEAT_PAYIP_AMOUNT_DAY:
            session.step = 'finance_payip_amount_day_awaiting_query'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_amount_day_prompt()
        if repeat_action == flow.REPEAT_PAYIP_VALIDATE_DAY:
            session.step = 'finance_payip_validate_day_awaiting_query'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self.finance_flow.payip_flow._build_payip_validate_day_prompt()
        if repeat_action == flow.REPEAT_PAYIP_IMPORT_BATCH:
            session.step = 'finance_payip_import_batch_awaiting_period'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self.finance_flow.payip_flow._build_payip_import_batch_prompt()
        return self._resume_post_result_navigation(sender=sender, session=session, decision=decision)

    def _store_post_result_navigation(self, sender: str, session: LookupSession, *, return_menu: str, repeat_action: str='') -> None:
        flow = _customer_flow_module()
        if not repeat_action and return_menu == 'search_menu':
            if session.step in {'awaiting_fantasia', 'awaiting_fantasia_selection'}:
                repeat_action = flow.REPEAT_SEARCH_NAME
        session.step = 'awaiting_post_result_navigation'
        session.return_menu = return_menu
        session.repeat_action = repeat_action
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session

    def _with_post_result_navigation(self, sender: str, session: LookupSession, outgoing: OutgoingMessage, *, return_menu: str, repeat_action: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        self._store_post_result_navigation(sender, session, return_menu=return_menu, repeat_action=repeat_action)
        if outgoing.kind != 'text':
            return outgoing
        normalized_text = flow._normalize_choice(outgoing.text)
        hint = flow._result_hint_text(allow_back=True)
        if flow._normalize_choice(hint) in normalized_text:
            return outgoing
        text = flow._strip_result_hint(outgoing.text)
        if text:
            text = f'{text}\n\n{hint}'
        else:
            text = hint
        return flow.OutgoingMessage(text=text, kind=outgoing.kind, title=outgoing.title, footer=outgoing.footer, button_text=outgoing.button_text, options=outgoing.options)

    def _build_expired_session_prompt(self, *, previous_step: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        _ = previous_step
        return flow.OutgoingMessage(text='A conversa anterior expirou e eu perdi o contexto.\nMe diga novamente o que voce quer, por exemplo: cliente, inadimplencia, giro, visitas ou financeiro.\nSe preferir, envie MENU.')

    def _clear_clarification_state(self, session: LookupSession) -> None:
        flow = _customer_flow_module()
        session.clarification_title = ''
        session.clarification_prompt = ''
        session.clarification_footer = ''
        session.clarification_options = ()

    def _remember_last_context(self, session: LookupSession, *, intent: str | None=None, search_context: str | None=None, query_text: str | None=None, client_filial: str | None=None, client_cod_pdv: str | None=None, client_name: str | None=None, visit_day: str | None=None) -> None:
        flow = _customer_flow_module()
        if intent:
            session.last_intent = intent
        if search_context:
            session.last_search_context = search_context
        if query_text is not None:
            session.last_query_text = ' '.join(str(query_text or '').strip().split())
        if client_filial:
            session.last_client_filial = client_filial
        if client_cod_pdv:
            session.last_client_cod_pdv = client_cod_pdv
        if client_name:
            session.last_client_name = ' '.join(str(client_name or '').strip().split())
        if visit_day:
            session.last_visit_day = visit_day
        session.last_context_updated_at = flow.datetime.now(flow.timezone.utc)

    def _has_recent_last_context(self, session: LookupSession) -> bool:
        flow = _customer_flow_module()
        if session.last_context_updated_at is None:
            return False
        return flow.datetime.now(flow.timezone.utc) - session.last_context_updated_at <= min(self.session_ttl, flow.timedelta(minutes=10))

    def _decision_scope_cache_key(self, decision: AccessDecision, *extra: Any) -> tuple[Any, ...]:
        flow = _customer_flow_module()
        return (tuple(sorted((str(role) for role in decision.roles))), tuple(sorted((str(sector) for sector in decision.sectors))), tuple(sorted((str(scope) for scope in decision.gv_vdes))), *extra)

    def _get_cached_response(self, cache_key: tuple[Any, ...]) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        cached = self._response_cache.get(cache_key)
        if cached is None:
            return None
        cached_at, outgoing = cached
        if flow.datetime.now(flow.timezone.utc) - cached_at > self.response_cache_ttl:
            self._response_cache.pop(cache_key, None)
            return None
        return outgoing

    def _store_cached_response(self, cache_key: tuple[Any, ...], outgoing: OutgoingMessage) -> OutgoingMessage:
        flow = _customer_flow_module()
        normalized_text = flow._normalize_choice(outgoing.text)
        if outgoing.kind == 'text' and (not normalized_text.startswith('nao consegui')):
            self._response_cache[cache_key] = (flow.datetime.now(flow.timezone.utc), outgoing)
        return outgoing

    def _build_base_clarification_options(self, session: LookupSession, decision: AccessDecision) -> list[InteractiveOption]:
        flow = _customer_flow_module()
        options: list[flow.InteractiveOption] = []
        if self._has_area_access(decision, 'inadimplencia'):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_SCOPE_INADIMPLENCIA_LIST, title='Inadimplentes da Base', description='Ver a lista de clientes inadimplentes'))
        for option in self._build_summary_clarification_options(decision):
            if option.option_id not in {item.option_id for item in options}:
                options.append(option)
        recent_intent = session.last_intent if self._has_recent_last_context(session) else ''
        if self._can_use_finance_menu(decision):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_GIRO_FINANCE_TOTAL, title='Giro da Base', description='Ver o giro consolidado da base total'))
        elif recent_intent.startswith('manager') or self._is_gerente_vendas(decision):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_GIRO_MANAGER_TOTAL, title='Giro da Gerencia', description='Ver o giro consolidado do seu GV'))
        elif recent_intent.startswith('director') or self._is_diretor_comercial(decision):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_GIRO_DIRECTOR_BY_GV, title='Giro dos Gerentes', description='Ver o giro agrupado por GV'))
        return options

    def _build_intent_clarification_menu(self, *, session: LookupSession, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        prompt = session.clarification_prompt or 'Me confirme qual caminho voce quer seguir.'
        if invalid_selection:
            prompt = flow._invalid_option_text(prompt)
        return flow.OutgoingMessage(kind='menu', title=session.clarification_title or 'Me confirma uma coisa', text=prompt, footer=session.clarification_footer or 'Use A ou ANT para voltar, ou MENU para ir ao inicio.', button_text='Escolher', options=session.clarification_options)

    def _open_intent_clarification(self, sender: str, session: LookupSession, *, title: str, prompt: str, options: list[InteractiveOption], footer: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        normalized_options = tuple((flow.InteractiveOption(option_id=option.option_id, title=option.title, description=option.description, shortcut=option.shortcut or str(index)) for index, option in enumerate(options, start=1)))
        session.step = 'awaiting_intent_clarification'
        session.return_menu = ''
        session.clarification_title = title
        session.clarification_prompt = prompt
        session.clarification_footer = footer or 'Use A ou ANT para voltar, ou MENU para ir ao inicio.'
        session.clarification_options = normalized_options
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_intent_clarification_menu(session=session)

    def _build_summary_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        flow = _customer_flow_module()
        options: list[flow.InteractiveOption] = []
        if self._can_use_finance_menu(decision):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_SUMMARY_FINANCE, title='Resumo Financeiro', description='Ver o painel da base total'))
        if self._is_gerente_vendas(decision) and self._can_use_gv_summary_menu(decision):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_SUMMARY_MANAGER, title='Resumo Total da Gerencia', description='Ver o consolidado do seu GV'))
        if self._is_diretor_comercial(decision) and self._can_use_gv_summary_menu(decision):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_SUMMARY_DIRECTOR, title='Resumo Total da Diretoria', description='Ver o consolidado da diretoria'))
        if self._can_use_seller_summary_menu(decision):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_SUMMARY_SELLER, title='Resumo da Carteira', description='Ver o resumo da sua carteira'))
        return options

    def _build_today_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        flow = _customer_flow_module()
        current_day_label = flow._current_visit_day_label()
        options: list[flow.InteractiveOption] = []
        if self._can_use_finance_menu(decision):
            options.extend((flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_FINANCE_DUE, title='Vencimentos de Hoje', description='Ver quem vence hoje na base total'), flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_FINANCE_RISK, title='Visitas com Risco Hoje', description=f'Ver risco financeiro em {current_day_label}')))
        if self._is_gerente_vendas(decision) and self._can_use_visit_menu(decision):
            options.extend((flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_MANAGER_VISITS, title='Visitas de Hoje da Gerencia', description=f'Ver a rota de {current_day_label} da gerencia'), flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_MANAGER_RISK, title='Risco Hoje da Gerencia', description=f'Ver os setores com risco em {current_day_label}')))
        if self._is_diretor_comercial(decision) and self._can_use_visit_menu(decision):
            options.extend((flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_DIRECTOR_VISITS, title='Visitas de Hoje da Diretoria', description=f'Ver a rota de {current_day_label} da diretoria'), flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_DIRECTOR_RISK, title='Risco Hoje da Diretoria', description=f'Ver risco por GV em {current_day_label}')))
        if self._can_use_seller_summary_menu(decision):
            options.extend((flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_SELLER_VISITS, title='Visitas de Hoje', description=f'Ver a sua rota de {current_day_label}'), flow.InteractiveOption(option_id=flow.CLARIFY_TODAY_SELLER_RISK, title='Risco Hoje da Carteira', description=f'Ver os clientes com risco em {current_day_label}')))
        return options

    def _build_giro_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        flow = _customer_flow_module()
        return self.finance_flow._build_giro_clarification_options(decision=decision)

    def _maybe_handle_idle_low_confidence_request(self, sender: str, session: LookupSession, normalized: str, decision: AccessDecision) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        tokens = flow._normalized_tokens(normalized)
        if self._can_use_finance_menu(decision) and flow._looks_like_finance_request(normalized):
            return None
        if flow._looks_like_client_short_request(normalized):
            if self._has_recent_last_context(session) and normalized in {'esse cliente', 'desse cliente', 'cliente atual'} and session.last_client_filial and session.last_client_cod_pdv:
                return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=flow.CLARIFY_LAST_CLIENT_RECORD)
            options = self._build_client_clarification_options(session, decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=options[0].option_id)
            if len(options) > 1:
                return self._open_intent_clarification(sender=sender, session=session, title='Cliente', prompt='Quando voce diz cliente, qual consulta voce quer abrir?', options=options)
        if flow._looks_like_list_short_request(normalized):
            if self._has_recent_last_context(session):
                if session.last_search_context == 'inadimplencia' or session.last_intent in {'inadimplencia_list', 'finance_summary', 'manager_summary', 'director_summary', 'seller_summary'}:
                    return self._open_scope_inadimplencia_list(sender=sender, session=session, decision=decision)
                if session.last_intent == 'visit_day' and self._can_use_visit_menu(decision):
                    return self._open_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=session.last_visit_day or flow._current_visit_day_label())
            options = self._build_list_clarification_options(decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=options[0].option_id)
            if len(options) > 1:
                return self._open_intent_clarification(sender=sender, session=session, title='Lista', prompt='Qual lista voce quer ver agora?', options=options)
        if flow._looks_like_base_short_request(normalized):
            options = self._build_base_clarification_options(session, decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=options[0].option_id)
            if len(options) > 1:
                return self._open_intent_clarification(sender=sender, session=session, title='Base', prompt='Quando voce diz base, qual visao voce quer abrir?', options=options)
        if self._can_use_finance_menu(decision) and (not self._can_use_gv_summary_menu(decision)) and {'resumo'} & tokens and {'gv'} & tokens:
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            return self._open_finance_gv_summary_selection(sender=sender, session=session, decision=decision)
        if flow._looks_like_summary_short_request(normalized):
            options = self._build_summary_clarification_options(decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=options[0].option_id)
            if len(options) > 1:
                return self._open_intent_clarification(sender=sender, session=session, title='Resumo', prompt='Quando voce diz resumo, qual deles voce quer ver?', options=options)
        if flow._looks_like_today_short_request(normalized):
            options = self._build_today_clarification_options(decision)
            if len(options) == 1:
                return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=options[0].option_id)
            if len(options) > 1:
                return self._open_intent_clarification(sender=sender, session=session, title='Hoje', prompt='Quando voce diz hoje, qual consulta voce quer abrir?', options=options)
        if flow._looks_like_today_risk_short_request(normalized):
            options = [option for option in self._build_today_clarification_options(decision) if option.option_id.endswith(':risk')]
            if len(options) == 1:
                return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=options[0].option_id)
            if len(options) > 1:
                return self._open_intent_clarification(sender=sender, session=session, title='Risco Hoje', prompt='Voce quer ver o risco de hoje em qual escopo?', options=options)
        if 'giro' in tokens:
            requested_visit_day_label = flow._extract_requested_visit_day_label(normalized)
            if requested_visit_day_label:
                readiness_error = self._ensure_search_context_ready('giro', decision=decision)
                if readiness_error is not None:
                    self._reset_session(sender)
                    return readiness_error
                self._prepare_search_session(session, search_context='giro')
                return self._open_giro_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=requested_visit_day_label)
            options = self._build_giro_clarification_options(decision)
            requested_giro_mode = flow._parse_giro_mode(normalized)
            if requested_giro_mode:
                matching_options = [option for option in options if option.option_id.endswith(f':{requested_giro_mode}')]
                if len(matching_options) == 1:
                    return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=matching_options[0].option_id)
                if len(matching_options) > 1:
                    return self._open_intent_clarification(sender=sender, session=session, title='Giro', prompt='Voce quer ver esse giro em qual escopo?', options=matching_options)
            if flow._looks_like_giro_short_request(normalized):
                if len(options) == 1:
                    return self._run_intent_clarification_option(sender=sender, session=session, decision=decision, option_id=options[0].option_id)
                if len(options) > 1:
                    return self._open_intent_clarification(sender=sender, session=session, title='Giro', prompt='Quando voce diz giro, qual caminho voce quer seguir?', options=options)
        return None

    def _run_intent_clarification_option(self, sender: str, session: LookupSession, decision: AccessDecision, *, option_id: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        self._clear_clarification_state(session)
        if option_id == flow.CLARIFY_LAST_CLIENT_RECORD:
            if not (session.last_client_filial and session.last_client_cod_pdv):
                self._reset_session(sender)
                return self._build_main_menu(decision)
            readiness_error = self._ensure_search_context_ready('cliente', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._remember_last_context(session, intent='search_cliente', search_context='cliente')
            return self._with_post_result_navigation(sender, session, self._run_registration_lookup(decision=decision, search_context='cliente', filial=session.last_client_filial, cod_pdv=session.last_client_cod_pdv), return_menu='main', repeat_action=flow.REPEAT_SEARCH_REGISTRATION)
        if option_id == flow.CLARIFY_SCOPE_INADIMPLENCIA_LIST:
            return self._open_scope_inadimplencia_list(sender=sender, session=session, decision=decision)
        if option_id == flow.MENU_SEARCH:
            readiness_error = self._ensure_search_context_ready('cliente', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(sender=sender, session=session, search_context='cliente', decision=decision)
        if option_id == flow.MENU_ARMAZEM:
            self._remember_last_context(session, intent='estoque_menu', search_context='estoque')
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._run_estoque_020304_lookup(filial='', product_code='', wants_pdf=False, decision=decision)
        if option_id == flow.MENU_INADIMPLENCIA:
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(sender=sender, session=session, search_context='inadimplencia', decision=decision)
        if option_id == flow.MENU_GIRO:
            readiness_error = self._ensure_search_context_ready('giro', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(sender=sender, session=session, search_context='giro', decision=decision)
        if option_id == flow.MENU_DOCUMENTACAO:
            readiness_error = self._ensure_search_context_ready('documentacao', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(sender=sender, session=session, search_context='documentacao', decision=decision)
        if option_id == flow.MENU_RECOLHA:
            return self._open_recolha_request(sender=sender, session=session, text='', normalized='', decision=decision)
        if option_id == flow.MENU_SELLER_FINANCEIRO:
            session.step = 'seller_finance_select_action'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow._build_seller_finance_menu_response()
        if option_id == flow.MENU_CRITICA:
            readiness_error = self.critica_flow.ensure_ready(decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            session.step = 'awaiting_critica_action'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow._build_critica_menu_response()
        if option_id == flow.MENU_COMODATOS:
            readiness_error = self._ensure_search_context_ready('comodato', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(sender=sender, session=session, search_context='comodato', decision=decision)
        if option_id == flow.MENU_VISIT_DAY:
            return self._open_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=session.last_visit_day)
        if option_id == flow.MENU_SELLER_SUMMARY:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='cliente')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='seller_summary', search_context='cliente')
            return self._with_post_result_navigation(sender, session, self._build_seller_summary_response(decision), return_menu='main')
        if option_id == flow.MENU_SELLER_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='seller_risk_today', search_context='inadimplencia', visit_day=flow._current_visit_day_label())
            return self._with_post_result_navigation(sender, session, self._build_seller_risk_response(decision), return_menu='main')
        if option_id == flow.MENU_FINANCEIRO:
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_menu', search_context='inadimplencia')
            self.sessions[sender] = session
            return self._build_finance_menu()
        if option_id == flow.CLARIFY_SUMMARY_FINANCE:
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_summary', search_context='inadimplencia')
            return self._with_post_result_navigation(sender, session, self._build_finance_summary_response(decision), return_menu='finance_menu')
        if option_id == flow.CLARIFY_SUMMARY_MANAGER:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='manager_summary', search_context='inadimplencia')
            return self._with_post_result_navigation(sender, session, self._build_gv_summary_response(decision=decision, title='Resumo Total da Gerencia'), return_menu='manager_summary')
        if option_id == flow.CLARIFY_SUMMARY_DIRECTOR:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='director_summary', search_context='inadimplencia')
            return self._with_post_result_navigation(sender, session, self._build_director_total_summary_response(decision), return_menu='director_summary')
        if option_id == flow.CLARIFY_SUMMARY_SELLER:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='cliente')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='seller_summary', search_context='cliente')
            return self._with_post_result_navigation(sender, session, self._build_seller_summary_response(decision), return_menu='main')
        if option_id == flow.CLARIFY_TODAY_FINANCE_DUE:
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_due_today', search_context='inadimplencia')
            return self._run_finance_due_bucket(sender=sender, session=session, decision=decision, due_bucket='today')
        if option_id == flow.CLARIFY_TODAY_FINANCE_RISK:
            readiness_error = self._ensure_search_context_ready('inadimplencia', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_risk_today', search_context='inadimplencia', visit_day=flow._current_visit_day_label())
            return self._open_finance_visit_risk_selection(sender=sender, session=session, decision=decision, visit_day_token=flow._current_visit_day_token(), visit_day_label=flow._current_visit_day_label())
        if option_id == flow.CLARIFY_TODAY_MANAGER_VISITS:
            self._remember_last_context(session, intent='visit_day', search_context='cliente', visit_day=flow._current_visit_day_label())
            return self._open_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=flow._current_visit_day_label())
        if option_id == flow.CLARIFY_TODAY_MANAGER_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='manager_risk_today', search_context='inadimplencia', visit_day=flow._current_visit_day_label())
            return self._open_manager_visit_risk_selection(sender=sender, session=session, decision=decision, visit_day_token=flow._current_visit_day_token(), visit_day_label=flow._current_visit_day_label())
        if option_id == flow.CLARIFY_TODAY_DIRECTOR_VISITS:
            self._remember_last_context(session, intent='visit_day', search_context='cliente', visit_day=flow._current_visit_day_label())
            return self._open_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=flow._current_visit_day_label())
        if option_id == flow.CLARIFY_TODAY_DIRECTOR_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='director_risk_today', search_context='inadimplencia', visit_day=flow._current_visit_day_label())
            return self._open_director_visit_risk_gv_selection(sender=sender, session=session, decision=decision, visit_day_token=flow._current_visit_day_token(), visit_day_label=flow._current_visit_day_label())
        if option_id == flow.CLARIFY_TODAY_SELLER_VISITS:
            self._remember_last_context(session, intent='visit_day', search_context='cliente', visit_day=flow._current_visit_day_label())
            return self._open_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=flow._current_visit_day_label())
        if option_id == flow.CLARIFY_TODAY_SELLER_RISK:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self._reset_session(sender)
                return access_error
            self._remember_last_context(session, intent='seller_risk_today', search_context='inadimplencia', visit_day=flow._current_visit_day_label())
            return self._with_post_result_navigation(sender, session, self._build_seller_risk_response(decision), return_menu='main')
        if option_id == flow.CLARIFY_GIRO_CLIENT:
            readiness_error = self._ensure_search_context_ready('giro', decision=decision)
            if readiness_error is not None:
                self._reset_session(sender)
                return readiness_error
            return self._open_search_context(sender=sender, session=session, search_context='giro', decision=decision)
        if option_id == flow.CLARIFY_GIRO_FINANCE_TOTAL:
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_giro_total', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_total_response(decision, title='Resumo de Giro | Base Total'), return_menu='finance_giro_menu')
        if option_id == flow.CLARIFY_GIRO_FINANCE_BY_FILIAL:
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_giro_by_filial', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_by_filial_response(decision, title='Giro por Filial | Base Total'), return_menu='finance_giro_menu')
        if option_id == flow.CLARIFY_GIRO_FINANCE_BY_GV:
            self._prepare_finance_session(session)
            self._remember_last_context(session, intent='finance_giro_by_gv', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_by_gv_response(decision, title='Giro por GV | Base Total'), return_menu='finance_giro_menu')
        if option_id == flow.CLARIFY_GIRO_MANAGER_TOTAL:
            self._remember_last_context(session, intent='manager_giro_total', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_total_response(decision, title='Resumo de Giro | Gerencia'), return_menu='manager_giro_menu')
        if option_id == flow.CLARIFY_GIRO_MANAGER_BY_FILIAL:
            self._remember_last_context(session, intent='manager_giro_by_filial', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_by_filial_response(decision, title='Giro por Filial | Gerencia'), return_menu='manager_giro_menu')
        if option_id == flow.CLARIFY_GIRO_DIRECTOR_BY_GV:
            self._remember_last_context(session, intent='director_giro_by_gv', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_by_gv_response(decision, title='Giro por GV | Diretoria'), return_menu='director_giro_menu')
        if option_id == flow.CLARIFY_GIRO_DIRECTOR_BY_FILIAL:
            self._remember_last_context(session, intent='director_giro_by_filial', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_by_filial_response(decision, title='Giro por Filial | Diretoria'), return_menu='director_giro_menu')
        self._reset_session(sender)
        return self._build_main_menu(decision)
