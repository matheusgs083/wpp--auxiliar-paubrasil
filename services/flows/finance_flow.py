from __future__ import annotations

from typing import Any

from bot_api.services.flows.payip_flow import PayipFlow


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class FinanceFlow:
    def __init__(self, context: Any) -> None:
        self.context = context
        self.payip_flow = PayipFlow(context)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def prepare_session(self, session: Any) -> None:
        flow = _customer_flow_module()
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
        session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
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
        session.updated_at = flow.datetime.now(flow.timezone.utc)

    def handle_session(
        self,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        flow = _customer_flow_module()
        if not self._can_use_finance_menu(decision):
            self._reset_session(sender)
            return flow.OutgoingMessage(
                text="Esse menu e exclusivo do financeiro e da administracao.\nSe quiser voltar, envie MENU."
            )

        if flow._is_back_menu_command(normalized):
            if session.step == "finance_select_action":
                self._reset_session(sender)
                return self._build_main_menu(decision)
            payip_back_response = self.payip_flow.handle_back_command(
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
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_finance_menu()
            if session.step == "finance_select_visit_risk_sector":
                return self._open_finance_visit_risk_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                )

        if session.step == "finance_clarify_today":
            clarification_action = flow._parse_finance_today_clarification(normalized)
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
                    visit_day_token=flow._current_visit_day_token(),
                    visit_day_label=flow._current_visit_day_label(),
                )
            return self._run_finance_due_bucket(
                sender=sender,
                session=session,
                decision=decision,
                due_bucket="today",
            )

        payip_response = self.payip_flow.handle_session_if_applicable(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )
        if payip_response is not None:
            return payip_response

        if session.step == "finance_select_action":
            request = flow._parse_hybrid_finance_request(normalized)
            action = request.action
            if request.clarify_today:
                session.step = "finance_clarify_today"
                session.updated_at = flow.datetime.now(flow.timezone.utc)
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
                    page_size=flow.INADIMPLENCIA_PAGE_SIZE,
                    list_context=flow.INADIMPLENCIA_CONTEXT_FINANCE_BASE_TOTAL,
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
                        visit_day_token=flow._visit_day_token_from_label(request.visit_day_label),
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
                session.updated_at = flow.datetime.now(flow.timezone.utc)
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
                return self.payip_flow.handle_finance_action(
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
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_due_menu()

        if session.step == "finance_select_summary_mode":
            summary_mode = flow._parse_finance_summary_mode(normalized)
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
            due_bucket = flow._parse_finance_due_bucket(normalized)
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
            selected_visit_risk_day = flow._select_visit_day(
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
            visit_day_token = flow._visit_day_token_from_label(selected_visit_risk_day)
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
            selected_gv = flow._select_finance_gv_option(
                text=text,
                normalized=normalized,
                gv_options=session.finance_gv_options,
            )
            if selected_gv is None:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )
            filtered_summaries = [
                summary
                for summary in session.visit_risk_summaries
                if flow.normalize_stored_scope_value(summary.manager_code) == flow.normalize_stored_scope_value(selected_gv)
            ]
            if not filtered_summaries:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_gv_menu(
                    visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(),
                    gv_options=list(session.finance_gv_options),
                    summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )
            session.step = "finance_select_visit_risk_sector"
            session.visit_risk_summaries = tuple(filtered_summaries)
            session.selected_visit_risk_gv = selected_gv
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_menu(
                visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(),
                summaries=filtered_summaries,
            )

        if session.step == "finance_select_visit_risk_sector":
            selected_summary = flow._select_finance_visit_risk_summary(
                text=text,
                normalized=normalized,
                summaries=session.visit_risk_summaries,
            )
            if selected_summary is None:
                self.sessions[sender] = session
                return self._build_finance_visit_risk_menu(
                    visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(),
                    summaries=list(session.visit_risk_summaries),
                    invalid_selection=True,
                )
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_finance_visit_risk_sector_response(
                    decision=decision,
                    summary=selected_summary,
                    visit_day_token=session.selected_visit_risk_token or flow._current_visit_day_token(),
                    visit_day_label=session.selected_visit_risk_label or flow._current_visit_day_label(),
                ),
                return_menu="finance_visit_risk_sector",
            )

        if session.step == "finance_select_gv_summary":
            selected_gv = flow._select_finance_gv_option(
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
                    title=f"Resumo de {flow._format_gv_scope_label(selected_gv)}",
                ),
                return_menu="finance_gv_summary",
            )

        if session.step == "finance_select_giro_mode":
            giro_mode = flow._parse_giro_mode(normalized)
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

    def _handle_back_command(
        self,
        *,
        sender: str,
        session: Any,
        normalized: str,
        decision: Any,
    ) -> Any | None:
        flow = _customer_flow_module()
        if not flow._is_back_menu_command(normalized):
            return None

        if session.step == "finance_select_action":
            self.context._reset_session(sender)
            return self.context._build_main_menu(decision)
        payip_back_response = self.payip_flow.handle_back_command(sender=sender, session=session)
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
            return self._set_step_and_return(
                sender=sender,
                session=session,
                step="finance_select_action",
                response=self.context._build_finance_menu(),
            )
        if session.step == "finance_select_visit_risk_sector":
            return self.context._open_finance_visit_risk_day_selection(
                sender=sender,
                session=session,
                decision=decision,
            )
        return None

    def _set_step_and_return(self, *, sender: str, session: Any, step: str, response: Any) -> Any:
        flow = _customer_flow_module()
        session.step = step
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.context.sessions[sender] = session
        return response

    def _build_giro_visit_day_header_text(
        self,
        *,
        visit_day: str,
        summary: flow.GiroScopeSummary,
        opportunities: list[flow.GiroVisitOpportunity],
        giro_updated_at: str,
    ) -> str:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
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
        total_gap = flow._sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )
        lines = [f"Oportunidade de giro em {visit_day_label}:", "Tipo: Giro de Vasilhame", ""]
        lines.append(f"Clientes monitorados: {summary.client_count}")
        lines.append(f"Caixas na rota: {flow._format_quantity(total_caixas)}")
        lines.append(f"Caixas OK: {flow._format_quantity(total_ok)}")
        lines.append(f"Caixas faltando para bater o giro: {total_gap}")
        self._append_giro_summary_lines(lines, summary, compact=False)
        lines.append("")
        lines.append(
            f"Clientes com oportunidade: {len(opportunities)} | "
            f"Caixas com giro: {flow._sum_formatted_amounts(*(item.total_caixas for item in opportunities)) if opportunities else '0'} | "
            f"Faltam: {flow._sum_formatted_amounts(*(item.gap_caixas for item in opportunities)) if opportunities else '0'}"
        )
        if giro_updated_at:
            lines.append(f"Giro atualizado em: {giro_updated_at}")
        return "\n".join(lines)

    def _open_giro_visit_day_conversation(
        self,
        sender: str,
        session: flow.LookupSession,
        decision: flow.AccessDecision,
        *,
        requested_day_label: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui carregar os dias de visita do seu giro agora.\n"
                    "Tente novamente em instantes."
                )
            )
        visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return flow.OutgoingMessage(
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
            visit_day=requested_day_label or session.last_visit_day or flow._format_visit_day_label(visit_days[0]),
        )
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        if not requested_day_label and len(visit_days) == 1:
            return self._apply_giro_visit_day_selection(
                sender=sender,
                session=session,
                decision=decision,
                selected_visit_day=visit_days[0],
            )
        if requested_day_label:
            selected_visit_day = flow._match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_giro_visit_day_selection(
                    sender=sender,
                    session=session,
                    decision=decision,
                    selected_visit_day=selected_visit_day,
                )
        return self._build_giro_visit_day_menu(visit_days=visit_days)

    def _build_finance_today_clarification(self) -> OutgoingMessage:
        flow = _customer_flow_module()
        return flow.OutgoingMessage(
            text=(
                "Quando voce diz 'financeiro de hoje', eu posso te mostrar:\n"
                "1. Vencimentos de hoje\n"
                "2. Visitas com risco hoje\n"
                "3. Resumo financeiro\n"
                "Me responda com o numero ou com a opcao."
            )
        )

    def _build_giro_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        flow = _customer_flow_module()
        options: list[flow.InteractiveOption] = []
        if self._has_area_access(decision, "cliente"):
            options.append(
                flow.InteractiveOption(
                    option_id=flow.CLARIFY_GIRO_CLIENT,
                    title="Giro por Cliente",
                    description="Buscar por CPF, nome ou filial e NB",
                )
            )
        if self._can_use_finance_menu(decision):
            options.extend(
                (
                    flow.InteractiveOption(
                        option_id=flow.CLARIFY_GIRO_FINANCE_TOTAL,
                        title="Giro Total da Base",
                        description="Ver o consolidado da base total",
                    ),
                    flow.InteractiveOption(
                        option_id=flow.CLARIFY_GIRO_FINANCE_BY_FILIAL,
                        title="Giro por Filial da Base",
                        description="Separar o giro por revenda",
                    ),
                    flow.InteractiveOption(
                        option_id=flow.CLARIFY_GIRO_FINANCE_BY_GV,
                        title="Giro por GV da Base",
                        description="Separar o giro por chave filial-GV",
                    ),
                )
            )
        if self._is_gerente_vendas(decision):
            options.extend(
                (
                    flow.InteractiveOption(
                        option_id=flow.CLARIFY_GIRO_MANAGER_TOTAL,
                        title="Giro Total da Gerencia",
                        description="Ver o consolidado do seu GV",
                    ),
                    flow.InteractiveOption(
                        option_id=flow.CLARIFY_GIRO_MANAGER_BY_FILIAL,
                        title="Giro por Filial da Gerencia",
                        description="Separar o giro da gerencia por revenda",
                    ),
                )
            )
        if self._is_diretor_comercial(decision):
            options.extend(
                (
                    flow.InteractiveOption(
                        option_id=flow.CLARIFY_GIRO_DIRECTOR_BY_GV,
                        title="Giro por GV da Diretoria",
                        description="Consolidar o giro por GV",
                    ),
                    flow.InteractiveOption(
                        option_id=flow.CLARIFY_GIRO_DIRECTOR_BY_FILIAL,
                        title="Giro por Filial da Diretoria",
                        description="Consolidar o giro por revenda",
                    ),
                )
            )
        return options

    def _run_finance_due_bucket(
        self,
        sender: str,
        session: flow.LookupSession,
        decision: flow.AccessDecision,
        *,
        due_bucket: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
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

    def _open_finance_summary_menu(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        session.step = "finance_select_summary_mode"
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_summary_menu()

    def _run_finance_summary_mode(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        decision: flow.AccessDecision,
        summary_mode: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
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

    def _build_finance_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "O que voce deseja acompanhar no financeiro?"
        if invalid_selection:
            text = flow._invalid_option_text("O que voce deseja acompanhar no financeiro?")
        return flow.OutgoingMessage(
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
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_SUMMARY,
                    title="Resumo Organizado",
                    description="Total, revenda, GV e setor",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_LIST,
                    title="Cobranca da Base",
                    description="Lista geral em ordem alfabetica",
                    shortcut="2",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_TOP,
                    title="Maiores Devedores",
                    description="Ordenar pelos maiores valores",
                    shortcut="3",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_UPCOMING,
                    title="Vencimentos Proximos",
                    description="Separar por 2, 1, 0 dias e vencidos",
                    shortcut="4",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_VISIT_RISK,
                    title="Risco da Rota",
                    description="Escolher o dia e ver GVs e setores com risco",
                    shortcut="5",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_GV_SUMMARY,
                    title="Resumo por GV",
                    description="Abrir o resumo de uma chave filial-GV",
                    shortcut="6",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_GIRO,
                    title="Giro",
                    description="Abrir o submenu de giro",
                    shortcut="7",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_PRAZO_LIMITE,
                    title="Prazo e Limite",
                    description="Cruzar documentos com a base de liberacao",
                    shortcut="8",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_PAYIP,
                    title="Pagamentos PayIP",
                    description="Validar sessao e consultar pagamentos",
                    shortcut="9",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_ACTION_RECOLHAS,
                    title="Solicitacoes de Recolha",
                    description="Ver pedidos enviados pelos vendedores",
                    shortcut="10",
                ),
            ),
        )

    def _build_finance_due_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "Qual faixa voce quer consultar?"
        if invalid_selection:
            text = flow._invalid_option_text("Qual faixa voce quer consultar?")
        return flow.OutgoingMessage(
            kind="menu",
            title="Vencimentos Proximos",
            text=text,
            footer="Escolha a faixa desejada. Use A ou ANT para voltar, ou MENU para ir ao inicio.",
            button_text="Escolher",
            options=(
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_IN_TWO_DAYS,
                    title="Vence em 2 dias",
                    description="Clientes que vencem em 2 dias",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_TOMORROW,
                    title="Vence amanha",
                    description="Clientes com vencimento para amanha",
                    shortcut="2",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_TODAY,
                    title="Vence hoje",
                    description="Clientes que vencem hoje",
                    shortcut="3",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_OVERDUE,
                    title="Ja vencidos",
                    description="Clientes que ja estao inadimplentes",
                    shortcut="4",
                ),
            ),
        )

    def _build_manager_due_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "Qual faixa voce quer consultar na sua gerencia?"
        if invalid_selection:
            text = flow._invalid_option_text("Qual faixa voce quer consultar na sua gerencia?")
        return flow.OutgoingMessage(
            kind="menu",
            title="Vencimentos Proximos",
            text=text,
            footer="Eu separo por 2 dias, amanha, hoje e vencidos. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_IN_TWO_DAYS,
                    title="Vence em 2 dias",
                    description="Clientes que vencem em 2 dias",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_TOMORROW,
                    title="Vence amanha",
                    description="Clientes que vencem amanha",
                    shortcut="2",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_TODAY,
                    title="Vence hoje",
                    description="Clientes que vencem hoje",
                    shortcut="3",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_DUE_OVERDUE,
                    title="Ja vencidos",
                    description="Clientes que ja estao vencidos",
                    shortcut="4",
                ),
            ),
        )

    def _build_finance_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "Como voce quer consultar o giro da base?"
        if invalid_selection:
            text = flow._invalid_option_text("Como voce quer consultar o giro da base?")
        return flow.OutgoingMessage(
            kind="menu",
            title="Giro",
            text=text,
            footer="Voce pode ver total, por filial ou por GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                flow.InteractiveOption(
                    option_id=flow.GIRO_MODE_TOTAL,
                    title="Resumo Total",
                    description="Ver o consolidado da base",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.GIRO_MODE_BY_FILIAL,
                    title="Por Filial",
                    description="Ver o giro separado por revenda",
                    shortcut="2",
                ),
                flow.InteractiveOption(
                    option_id=flow.GIRO_MODE_BY_GV,
                    title="Por GV",
                    description="Ver o giro separado por chave filial-GV",
                    shortcut="3",
                ),
            ),
        )

    def _build_manager_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "Como voce quer consultar o giro da sua gerencia?"
        if invalid_selection:
            text = flow._invalid_option_text("Como voce quer consultar o giro da sua gerencia?")
        return flow.OutgoingMessage(
            kind="menu",
            title="Giro da Gerencia",
            text=text,
            footer="Voce pode ver o total da gerencia ou por filial. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                flow.InteractiveOption(
                    option_id=flow.GIRO_MODE_TOTAL,
                    title="Resumo Total",
                    description="Ver o consolidado do seu GV",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.GIRO_MODE_BY_FILIAL,
                    title="Por Filial",
                    description="Ver o giro da gerencia por revenda",
                    shortcut="2",
                ),
            ),
        )

    def _build_director_giro_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "Como voce quer consultar o giro da diretoria?"
        if invalid_selection:
            text = flow._invalid_option_text("Como voce quer consultar o giro da diretoria?")
        return flow.OutgoingMessage(
            kind="menu",
            title="Giro da Diretoria",
            text=text,
            footer="Voce pode ver por GV ou por filial. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                flow.InteractiveOption(
                    option_id=flow.GIRO_MODE_BY_GV,
                    title="Por GV",
                    description="Consolidar por gerente",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.GIRO_MODE_BY_FILIAL,
                    title="Por Filial",
                    description="Consolidar por revenda",
                    shortcut="2",
                ),
            ),
        )

    def _build_giro_total_response(
        self,
        decision: flow.AccessDecision,
        *,
        title: str,
        gv_vdes_override: tuple[str, ...] | None = None,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
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
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_giro_zero_base_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        records = self._safe_giro_zero_base_records(decision)
        if records is None:
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui montar o giro zero da base agora.\n"
                    "Tente novamente em instantes."
                )
            )

        scope_label = "base total" if self._has_unrestricted_lookup_access(decision) else "sua base"
        if not records:
            return flow.OutgoingMessage(
                text=(
                    f"Nenhum cliente com giro zero encontrado na {scope_label}.\n"
                    "Regra usada: cliente com caixas na base e faltam caixas = caixas * 2.\n"
                    f"\n{flow._result_hint_text()}"
                )
            )

        ordered_records = sorted(
            records,
            key=lambda item: (
                flow._sort_numeric_text(item.filial),
                flow._sort_numeric_text(item.setor),
                flow._sort_numeric_text(item.cod_pdv),
            ),
        )
        total_caixas = flow._sum_formatted_amounts(*(record.total_caixas for record in ordered_records))
        total_faltam = flow._sum_formatted_amounts(*(record.gap_caixas for record in ordered_records))
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
            filial = flow._normalize_filial(record.filial)
            setor = flow.normalize_stored_scope_value(record.setor)
            cod_pdv = flow._normalize_cod_pdv(record.cod_pdv)
            client_name = (record.nome or "-").strip()
            total_caixas_cliente = flow._format_quantity(record.total_caixas)
            gap_caixas_cliente = flow._format_quantity(record.gap_caixas)
            gap_detail = flow._format_giro_gap_detail(record)
            if filial != current_filial:
                if lines and lines[-1]:
                    lines.append("")
                lines.append(f"Filial {filial or '-'}")
                current_filial = filial
                current_setor = ""
            if setor != current_setor:
                lines.append(f"Setor {setor or '-'}")
                current_setor = setor
            flow._append_giro_client_block(
                lines,
                index=index,
                client_name=client_name,
                cod_pdv=cod_pdv,
                total_caixas=total_caixas_cliente,
                gap_caixas=gap_caixas_cliente,
                gap_detail=gap_detail,
            )

        lines.append("")
        lines.append(flow._result_hint_text())
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_giro_visit_day_response(
        self,
        *,
        visit_day: str,
        decision: flow.AccessDecision,
        summary: flow.GiroScopeSummary,
        records: list[flow.DClienteRecord],
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
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
        total_gap = flow._sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )
        lines = [f"Oportunidade de giro em {visit_day_label}:", "Tipo: Giro de Vasilhame", ""]
        lines.append(f"Clientes monitorados: {summary.client_count}")
        lines.append(f"Caixas na rota: {flow._format_quantity(total_caixas)}")
        lines.append(f"Caixas OK: {flow._format_quantity(total_ok)}")
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
                flow.normalize_stored_scope_value(summary_item.seller_code): flow.normalize_stored_scope_value(summary_item.manager_code)
                for summary_item in seller_summaries
                if flow.normalize_stored_scope_value(summary_item.seller_code)
            }

        clients_with_opportunity: list[tuple[str, str, str, str, str, str, str, str]] = []
        total_caixas_values: list[str] = []
        total_gap_values: list[str] = []
        for record in records:
            client_name = record.nome_fantasia or record.razao_social or "-"
            client_summary = giro_summaries.get((flow._normalize_filial(record.filial), flow._normalize_cod_pdv(record.cod_pdv)))
            if client_summary is None:
                continue
            setor_code, total_caixas, gap_caixas, gap_detail = client_summary
            if not flow._is_positive_quantity(total_caixas) or not flow._is_positive_quantity(gap_caixas):
                continue
            seller_code = flow.normalize_stored_scope_value(f"{flow._normalize_filial(record.filial)}_{setor_code}")
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
                flow._sort_scope_code(item[0] or item[1]),
                flow._sort_scope_code(item[1]),
                flow._sort_numeric_text(item[3]),
                str(item[4] or "").lower(),
            )
        )

        lines.append("")
        lines.append(
            f"Clientes com oportunidade: {len(clients_with_opportunity)} | "
            f"Caixas com giro: {flow._sum_formatted_amounts(*total_caixas_values) if total_caixas_values else '0'} | "
            f"Faltam: {flow._sum_formatted_amounts(*total_gap_values) if total_gap_values else '0'}"
        )
        if giro_updated_at:
            lines.append(f"Giro atualizado em: {giro_updated_at}")
        if include_manager_breakdown and manager_by_seller and clients_with_opportunity:
            flow._append_giro_visit_day_gv_summary_lines(lines, clients_with_opportunity)
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
                    lines.append(f"*{flow._format_gv_scope_label(manager_code)}*")
                    current_manager = manager_code
                    current_sector = ""
                if setor_code != current_sector:
                    if current_sector:
                        lines.append("")
                    lines.append(f"*Setor {setor_code or '-'}*")
                    current_sector = setor_code
                flow._append_giro_client_block(
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
        lines.append(flow._result_hint_text())
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_finance_giro_visit_day_response(
        self,
        *,
        visit_day: str,
        decision: flow.AccessDecision,
        summary: flow.GiroScopeSummary,
        records: list[flow.DClienteRecord],
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
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
        total_gap = flow._sum_formatted_amounts(
            summary.litrinho_gap_total,
            summary.inteira_gap_total,
            summary.litrao_gap_total,
        )
        lines = [f"Oportunidade de giro em {visit_day_label}:", "Tipo: Giro de Vasilhame", ""]
        lines.append(f"Clientes monitorados: {summary.client_count}")
        lines.append(f"Caixas na rota: {flow._format_quantity(total_caixas)}")
        lines.append(f"Caixas OK: {flow._format_quantity(total_ok)}")
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
            flow.normalize_stored_scope_value(summary_item.seller_code): flow.normalize_stored_scope_value(summary_item.manager_code)
            for summary_item in seller_summaries
            if flow.normalize_stored_scope_value(summary_item.seller_code)
        }

        clients_with_opportunity: list[tuple[str, str, str, str, str, str, str]] = []
        total_caixas_values: list[str] = []
        total_gap_values: list[str] = []
        for record in records:
            client_summary = giro_summaries.get((flow._normalize_filial(record.filial), flow._normalize_cod_pdv(record.cod_pdv)))
            if client_summary is None:
                continue
            setor_code, total_caixas_cliente, gap_caixas_cliente, gap_detail = client_summary
            if not flow._is_positive_quantity(total_caixas_cliente) or not flow._is_positive_quantity(gap_caixas_cliente):
                continue
            seller_code = flow.normalize_stored_scope_value(f"{flow._normalize_filial(record.filial)}_{setor_code}")
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
                flow._sort_scope_code(item[0] or f"{flow.split_scope_pair(item[1])[0]}_999999" if flow.split_scope_pair(item[1]) else item[1]),
                flow._sort_scope_code(item[1]),
                flow._sort_numeric_text(item[3]),
                str(item[4] or "").lower(),
            )
        )

        lines.append("")
        lines.append(
            f"Clientes com oportunidade: {len(clients_with_opportunity)} | "
            f"Caixas com giro: {flow._sum_formatted_amounts(*total_caixas_values) if total_caixas_values else '0'} | "
            f"Faltam: {flow._sum_formatted_amounts(*total_gap_values) if total_gap_values else '0'}"
        )
        if giro_updated_at:
            lines.append(f"Giro atualizado em: {giro_updated_at}")
        flow._append_giro_visit_day_gv_summary_lines(lines, clients_with_opportunity)
        lines.append("")
        lines.append("Clientes com oportunidade de giro:")
        if not clients_with_opportunity:
            lines.append("Nenhum cliente com oportunidade de giro nesse dia.")
            lines.append("")
            lines.append(flow._result_hint_text())
            return flow.OutgoingMessage(text="\n".join(lines))

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
                    lines.append(f"*{flow._format_gv_scope_label(manager_code)}*")
                else:
                    filial_code, _ = flow.split_scope_pair(seller_code) or ("", "")
                    lines.append(f"*{flow._format_filial_label(filial_code)}*")
                current_manager = manager_code
                current_seller = ""
            if seller_code != current_seller:
                lines.append(f"*Setor {setor_code or '-'}*")
                current_seller = seller_code
            flow._append_giro_client_block(
                lines,
                index=index,
                client_name=client_name,
                cod_pdv=cod_pdv,
                total_caixas=total_caixas_cliente,
                gap_caixas=gap_caixas_cliente,
                gap_detail=gap_detail,
            )

        lines.append("")
        lines.append(flow._result_hint_text())
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_giro_by_filial_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        cache_key = self._decision_scope_cache_key(decision, "giro", "by_filial", title)
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        summaries = self._safe_giro_summary_by_filial(decision)
        gv_summaries = self._safe_giro_summary_by_gv(decision)
        seller_summaries = self._safe_giro_summary_by_seller(decision)
        if not summaries:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei dados de giro por filial para esse escopo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        gv_by_filial = self._group_giro_management_summaries_by_filial(gv_summaries)
        seller_by_manager = self._group_giro_seller_summaries_by_manager(seller_summaries)
        lines = [title]
        for summary in sorted(summaries, key=lambda item: flow._sort_numeric_text(item.filial)):
            lines.append("")
            lines.append(f"*{flow._format_filial_label(summary.filial)}*")
            self._append_giro_summary_lines(lines, summary, compact=True, show_details=True)
            filial_gv_summaries = sorted(
                gv_by_filial.get(summary.filial, []),
                key=lambda item: flow._sort_scope_code(item.manager_code),
            )
            if filial_gv_summaries:
                lines.append("GVs do giro:")
                for gv_summary in filial_gv_summaries:
                    gv_seller_count = len(seller_by_manager.get(gv_summary.manager_code, []))
                    lines.append(
                        self._format_giro_total_scope_line(
                            gv_summary,
                            label=flow._format_gv_scope_label(gv_summary.manager_code),
                            child_count_label="Setores",
                            child_count=gv_seller_count,
                        )
                    )
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_giro_by_gv_response(self, decision: AccessDecision, *, title: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        cache_key = self._decision_scope_cache_key(decision, "giro", "by_gv", title)
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        summaries = self._safe_giro_summary_by_gv(decision)
        seller_summaries = self._safe_giro_summary_by_seller(decision)
        if not summaries:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei dados de giro por GV para esse escopo agora.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        def _gv_sort_key(value: str) -> tuple[int, str]:
            pair = flow.split_scope_pair(value) or ("", value)
            return flow._sort_numeric_text(pair[1] or pair[0] or value)

        seller_by_manager = self._group_giro_seller_summaries_by_manager(seller_summaries)
        lines = [title]
        for summary in sorted(summaries, key=lambda item: _gv_sort_key(item.manager_code)):
            lines.append("")
            lines.append(f"*{flow._format_gv_scope_label(summary.manager_code)}*")
            self._append_giro_summary_lines(lines, summary, compact=True, show_details=True)
            gv_seller_summaries = sorted(
                seller_by_manager.get(summary.manager_code, []),
                key=lambda item: flow._sort_scope_code(item.seller_code),
            )
            if gv_seller_summaries:
                lines.append("Setores do GV:")
                for seller_summary in gv_seller_summaries:
                    lines.append(
                        self._format_giro_total_scope_line(
                            seller_summary,
                            label=flow._format_sector_scope_label(seller_summary.seller_code),
                        )
                    )
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_giro_historical_fallback_response(
        self,
        *,
        decision: flow.AccessDecision,
        filial: str,
        cod_pdv: str,
        criteria: str,
    ) -> flow.OutgoingMessage | None:
        flow = _customer_flow_module()
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
        return flow.OutgoingMessage(
            text=(
                "Esse cliente existe no cadastro, mas nao veio no lote ativo do giro de vasilhame.\n"
                f"Ultimo giro historico encontrado: {latest_date}.\n\n"
                f"{historical_response.text}"
            )
        )

    def _build_finance_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
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
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_finance_summary_by_filial_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
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
        filial_codes = sorted(set(client_by_filial) | set(inad_by_filial) | set(giro_by_filial), key=flow._sort_numeric_text)
        if not filial_codes:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei revendas disponiveis para esse resumo agora.\n"
                    f"{flow._result_hint_text()}"
                )
            )

        lines = ["Resumo Financeiro por Revenda"]
        for filial in filial_codes:
            client_summary = client_by_filial.get(filial)
            inad_summary = inad_by_filial.get(filial)
            giro_summary = giro_by_filial.get(filial)
            lines.append("")
            lines.append(f"*{flow._format_filial_label(filial)}*")
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
                key=lambda item: flow._sort_scope_code(item.manager_code),
            )
            if filial_gv_summaries:
                lines.append("GVs do giro:")
                for gv_summary in filial_gv_summaries:
                    gv_seller_count = len(giro_seller_by_manager.get(gv_summary.manager_code, []))
                    lines.append(
                        self._format_giro_total_scope_line(
                            gv_summary,
                            label=flow._format_gv_scope_label(gv_summary.manager_code),
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
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_finance_documentacao_by_filial_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo de documentacao escaneada agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not summaries:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei clientes ativos para resumir a documentacao escaneada por revenda.\n"
                    f"{flow._result_hint_text()}"
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
        lines.append(f"% OK da base ativa: {flow._format_percent_ratio(total_ok, total_active)}")

        for summary in summaries:
            lines.append("")
            lines.append(f"*{flow._format_filial_label(summary.filial)}*")
            lines.append(
                f"Ativos: {summary.active_client_count} | Escaneados: {summary.scanned_client_count}"
            )
            lines.append(
                f"OK: {summary.ok_client_count} | Pendentes: {summary.pending_client_count} | "
                f"Sem escanear: {summary.missing_scan_count}"
            )
            lines.append(f"% OK: {flow._format_percent_ratio(summary.ok_client_count, summary.active_client_count)}")
            lines.append(f"Atualizado: {summary.planilha_atualizada_em or '-'}")

        lines.append("")
        lines.append("Regra: cliente OK somente quando todos os documentos estao como OK.")
        lines.append("")
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_finance_summary_by_gv_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
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
        manager_codes = sorted(set(client_by_gv) | set(inad_by_gv) | set(giro_by_gv), key=flow._sort_scope_code)
        if not manager_codes:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei GVs disponiveis para esse resumo agora.\n"
                    f"{flow._result_hint_text()}"
                )
            )

        lines = ["Resumo Financeiro por GV"]
        for manager_code in manager_codes:
            client_summary = client_by_gv.get(manager_code)
            inad_summary = inad_by_gv.get(manager_code)
            giro_summary = giro_by_gv.get(manager_code)
            lines.append("")
            lines.append(f"*{flow._format_gv_scope_label(manager_code)}*")
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
                key=lambda item: flow._sort_scope_code(item.seller_code),
            )
            if gv_seller_summaries:
                lines.append("Setores do giro:")
                for seller_summary in gv_seller_summaries:
                    lines.append(
                        self._format_giro_total_scope_line(
                            seller_summary,
                            label=flow._format_sector_scope_label(seller_summary.seller_code),
                        )
                    )
            lines.append(
                "Atualizado: "
                f"Clientes {(client_summary.planilha_atualizada_em if client_summary else '-') or '-'} | "
                f"Inadimplencia {(getattr(inad_summary, 'planilha_atualizada_em', '-') if inad_summary else '-') or '-'} | "
                f"Giro {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}"
            )

        lines.append("")
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_finance_summary_by_seller_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo por setor agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summaries = self._safe_giro_summary_by_seller(decision)

        seller_by_code = {summary.seller_code: summary for summary in seller_summaries}
        inad_by_seller = {summary.seller_code: summary for summary in inad_summaries}
        giro_by_seller = {summary.seller_code: summary for summary in giro_summaries}
        seller_codes = sorted(set(seller_by_code) | set(inad_by_seller) | set(giro_by_seller), key=flow._sort_scope_code)
        if not seller_codes:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei setores disponiveis para esse resumo agora.\n"
                    f"{flow._result_hint_text()}"
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
                lines.append(f"*{flow._format_gv_scope_label(manager_code) if manager_code else 'Sem GV'}*")
                current_manager = manager_code
            lines.append(f"{flow._format_sector_scope_label(seller_code)}")
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
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_director_total_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo da diretoria agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not client_summaries and not inad_summaries:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei GVs disponiveis para esse resumo agora.\n"
                    f"{flow._result_hint_text()}"
                )
            )
        giro_summaries = self._safe_giro_summary_by_gv(decision)

        grouped_clients: dict[str, list[flow.DClientesManagementSummary]] = {}
        for summary in client_summaries:
            manager_code = flow.normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped_clients.setdefault(manager_code, []).append(summary)

        grouped_inad: dict[str, list[flow.InadimplenciaFinanceManagementSummary]] = {}
        for summary in inad_summaries:
            manager_code = flow.normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped_inad.setdefault(manager_code, []).append(summary)

        grouped_giro: dict[str, list[flow.GiroManagementSummary]] = {}
        for summary in giro_summaries:
            manager_code = flow.normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped_giro.setdefault(manager_code, []).append(summary)

        ordered_gvs = sorted(set(grouped_clients) | set(grouped_inad) | set(grouped_giro), key=flow._sort_scope_code)
        lines = ["Diretoria | Resumo Total"]
        lines.append(f"*GVs na base:* {len(ordered_gvs)}")

        for manager_code in ordered_gvs:
            client_group = grouped_clients.get(manager_code, [])
            inad_group = grouped_inad.get(manager_code, [])
            giro_summary = flow._aggregate_giro_scope_summaries(grouped_giro.get(manager_code, []))
            lines.append("")
            lines.append(f"*{flow._format_gv_scope_label(manager_code)}*")
            lines.append(
                f"Base: {sum(item.client_count for item in client_group)} clientes | "
                f"{sum(item.seller_count for item in client_group)} setores"
            )
            lines.append(
                f"Inadimplentes: {sum(item.client_count for item in inad_group)}"
                f" | R$ {flow._sum_money_values(item.total_pendente for item in inad_group)}"
                f" | Ja vencidos {sum(item.overdue_count for item in inad_group)}"
            )
            lines.append(
                self._format_due_compact_line(
                    today_count=sum(item.due_today_count for item in inad_group),
                    today_total=flow._sum_money_values(item.due_today_total for item in inad_group),
                    tomorrow_count=sum(item.due_tomorrow_count for item in inad_group),
                    tomorrow_total=flow._sum_money_values(item.due_tomorrow_total for item in inad_group),
                    two_days_count=sum(item.due_in_two_days_count for item in inad_group),
                    two_days_total=flow._sum_money_values(item.due_in_two_days_total for item in inad_group),
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
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_director_manager_ranking_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui montar o ranking dos gerentes agora.\n"
                    "Tente novamente em instantes."
                )
            )

        risk_today_by_gv: dict[str, tuple[int, str]] = {}
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        if current_visit_day:
            visit_day_token = flow._visit_day_token_from_label(current_visit_day)
            if visit_day_token:
                try:
                    risk_summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                        visit_day_token=visit_day_token,
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                        limit=200,
                    )
                    grouped_risk: dict[str, list[flow.InadimplenciaVisitRiskSummary]] = {}
                    for summary in risk_summaries:
                        grouped_risk.setdefault(summary.manager_code, []).append(summary)
                    for manager_code, summaries in grouped_risk.items():
                        risk_today_by_gv[manager_code] = (
                            sum(item.client_count for item in summaries),
                            flow._sum_money_values(item.total_pendente for item in summaries),
                        )
                except RuntimeError:
                    risk_today_by_gv = {}

        client_by_gv = {summary.manager_code: summary for summary in client_summaries}
        inad_by_gv = {summary.manager_code: summary for summary in inad_summaries}
        manager_codes = sorted(
            set(client_by_gv) | set(inad_by_gv) | set(risk_today_by_gv),
            key=lambda value: (
                flow._money_sort_key(inad_by_gv.get(value).total_pendente if inad_by_gv.get(value) else "0,00"),
                value,
            ),
            reverse=True,
        )
        if not manager_codes:
            return flow.OutgoingMessage(
                text=(
                    "Nao encontrei gerentes disponiveis para esse ranking agora.\n"
                    f"{flow._result_hint_text()}"
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
                f"{index}. {flow._format_gv_scope_label(manager_code)} | "
                f"R$ {inad_summary.total_pendente if inad_summary else '0,00'}"
            )
            lines.append(
                f"Base {client_summary.client_count if client_summary else 0} clientes | "
                f"{client_summary.seller_count if client_summary else 0} setores | "
                f"Inadimplentes {inad_summary.client_count if inad_summary else 0} | "
                f"Risco hoje {risk_today[0]} cliente(s) | R$ {risk_today[1]}"
            )
            lines.append("")

        lines.append(flow._result_hint_text())
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_director_filial_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui montar o resumo por filial agora.\n"
                    "Tente novamente em instantes."
                )
            )
        giro_summaries = self._safe_giro_summary_by_filial(decision)

        risk_today_by_filial: dict[str, tuple[int, str]] = {}
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        if current_visit_day:
            visit_day_token = flow._visit_day_token_from_label(current_visit_day)
            if visit_day_token:
                try:
                    risk_summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                        visit_day_token=visit_day_token,
                        allowed_sectors=self._allowed_sectors(decision),
                        allowed_gv_vdes=self._allowed_gv_vdes(decision),
                        limit=250,
                    )
                    grouped_risk: dict[str, list[flow.InadimplenciaVisitRiskSummary]] = {}
                    for summary in risk_summaries:
                        filial, _ = flow.split_scope_pair(summary.seller_code) or ("", "")
                        if not filial:
                            continue
                        grouped_risk.setdefault(filial, []).append(summary)
                    for filial, summaries in grouped_risk.items():
                        risk_today_by_filial[filial] = (
                            sum(item.client_count for item in summaries),
                            flow._sum_money_values(item.total_pendente for item in summaries),
                        )
                except RuntimeError:
                    risk_today_by_filial = {}

        client_by_filial = {summary.filial: summary for summary in client_summaries}
        inad_by_filial = {summary.filial: summary for summary in inad_summaries}
        giro_by_filial = {summary.filial: summary for summary in giro_summaries}
        filial_codes = sorted(
            set(client_by_filial) | set(inad_by_filial) | set(risk_today_by_filial) | set(giro_by_filial),
            key=flow._sort_numeric_text,
        )
        if not filial_codes:
            return flow.OutgoingMessage(
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
            lines.append(f"*{flow._format_filial_label(filial)}*")
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
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _open_finance_gv_summary_selection(
        self,
        sender: str,
        session: flow.LookupSession,
        decision: flow.AccessDecision,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        try:
            gv_options = self.query_service.list_gv_vdes(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50,
            )
        except RuntimeError:
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui abrir a lista de GVs agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not gv_options:
            return flow.OutgoingMessage(
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
                    title=f"Resumo do GV {flow._format_gv_scope_label(selected_gv)}",
                ),
                return_menu="finance_menu",
            )

        session.step = "finance_select_gv_summary"
        session.finance_gv_options = tuple(gv_options)
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_gv_summary_menu(gv_options=gv_options)

    def _build_director_visit_risk_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        header = "Escolha o dia da semana para ver o risco da rota da diretoria."
        if invalid_selection:
            header = flow._invalid_option_text("Escolha o dia da semana para ver o risco da rota da diretoria.")
        return flow.OutgoingMessage(
            kind="menu",
            title="Diretoria | Risco da Rota",
            text=header,
            footer="Depois eu mostro os GVs com risco, os setores e, em seguida, os clientes. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"{flow.VISIT_DAY_PICK_PREFIX}{index}",
                    title=visit_day,
                    description="Ver GVs, setores e clientes com risco",
                    shortcut=str(index),
                )
                for index, visit_day in enumerate(visit_days, start=1)
            ),
        )

    def _build_manager_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "O que voce quer acompanhar na sua gerencia?"
        if invalid_selection:
            text = flow._invalid_option_text("O que voce quer acompanhar na sua gerencia?")
        return flow.OutgoingMessage(
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
                flow.InteractiveOption(
                    option_id=flow.MANAGER_ACTION_VISIT_RISK,
                    title="Risco da Rota",
                    description="Ver setores da rota com risco financeiro",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.MANAGER_ACTION_UPCOMING,
                    title="Vencimentos",
                    description="Ver quem vence em 2, 1 e 0 dias",
                    shortcut="2",
                ),
                flow.InteractiveOption(
                    option_id=flow.MANAGER_ACTION_LIST,
                    title="Cobranca Consolidada",
                    description="Listar os clientes inadimplentes do GV",
                    shortcut="3",
                ),
                flow.InteractiveOption(
                    option_id=flow.MANAGER_ACTION_BY_SELLER,
                    title="Equipe",
                    description="Escolher um setor da equipe para ver o resumo",
                    shortcut="4",
                ),
                flow.InteractiveOption(
                    option_id=flow.MANAGER_SUMMARY_BY_FILIAL,
                    title="Filiais",
                    description="Escolher a revenda para detalhar",
                    shortcut="5",
                ),
                flow.InteractiveOption(
                    option_id=flow.MANAGER_ACTION_GIRO,
                    title="Giro Consolidado",
                    description="Abrir o resumo de giro consolidado do GV",
                    shortcut="6",
                ),
                flow.InteractiveOption(
                    option_id=flow.MANAGER_SUMMARY_TOTAL,
                    title="Resumo Total",
                    description="Ver toda a base do seu GV",
                    shortcut="7",
                ),
            ),
        )

    def _build_finance_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "Como voce quer acompanhar o resumo financeiro?"
        if invalid_selection:
            text = flow._invalid_option_text("Como voce quer acompanhar o resumo financeiro?")
        return flow.OutgoingMessage(
            kind="menu",
            title="Resumo Financeiro",
            text=text,
            footer="Voce pode ver o total, por revenda, por GV, por setor ou a documentacao escaneada por revenda. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                flow.InteractiveOption(
                    option_id=flow.FINANCE_SUMMARY_TOTAL,
                    title="Resumo Total",
                    description="Ver o consolidado geral da base",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_SUMMARY_BY_FILIAL,
                    title="Por Revenda",
                    description="Organizar o financeiro por filial",
                    shortcut="2",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_SUMMARY_BY_GV,
                    title="Por GV",
                    description="Organizar o financeiro por chave filial-GV",
                    shortcut="3",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_SUMMARY_BY_SELLER,
                    title="Por Setor",
                    description="Organizar o financeiro por chave filial-setor",
                    shortcut="4",
                ),
                flow.InteractiveOption(
                    option_id=flow.FINANCE_SUMMARY_DOCUMENTACAO_BY_FILIAL,
                    title="Doc Escaneada",
                    description="Resumo documental por revenda com clientes ativos",
                    shortcut="5",
                ),
            ),
        )

    def _build_manager_filial_summary_menu(
        self,
        filial_options: list[str],
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        text = "Escolha a filial que voce quer resumir."
        if invalid_selection:
            text = flow._invalid_option_text("Escolha a filial que voce quer resumir.")
        return flow.OutgoingMessage(
            kind="menu",
            title="Resumo por Filial",
            text=text,
            footer="Depois eu mostro o resumo da sua gerencia nessa revenda. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"manager:filial:{index}",
                    title=flow._format_filial_label(filial),
                    description="Ver resumo dessa filial",
                    shortcut=str(index),
                )
                for index, filial in enumerate(filial_options, start=1)
            ),
        )

    def _build_manager_seller_summary_menu(
        self,
        seller_summaries: list[flow.VisitSellerSummary],
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        text = "Escolha o vendedor que voce quer resumir."
        if invalid_selection:
            text = flow._invalid_option_text("Escolha o vendedor que voce quer resumir.")
        return flow.OutgoingMessage(
            kind="menu",
            title="Resumo por Vendedor",
            text=text,
            footer="Cada linha mostra o setor, o GV e a quantidade de clientes na base. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"manager:seller:{index}",
                    title=flow._format_sector_scope_label(summary.seller_code),
                    description=f"{flow._format_gv_scope_label(summary.manager_code)} | {summary.visit_count} cliente(s) na base",
                    shortcut=str(index),
                )
                for index, summary in enumerate(seller_summaries, start=1)
            ),
        )

    def _build_manager_seller_summary_response(
        self,
        decision: flow.AccessDecision,
        summary: flow.VisitSellerSummary,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
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
        risk_today_alerts: list[flow.InadimplenciaVisitAlert] = []
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
                    visit_day_token=flow._visit_day_token_from_label(current_visit_day),
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

        lines = [f"Resumo do vendedor {flow._format_sector_scope_label(summary.seller_code)}", ""]
        lines.append(f"*Gerencia:* {flow._format_gv_scope_label(summary.manager_code)}")
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
            f" | R$ {flow._sum_money_values(alert.total_pendente for alert in risk_today_alerts if alert.nearest_days_to_due <= 0)}"
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
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text="\n".join(lines)))

    def _build_director_summary_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "Escolha a visao da diretoria que voce quer abrir agora."
        if invalid_selection:
            text = flow._invalid_option_text("Escolha uma opcao da diretoria.")
        return flow.OutgoingMessage(
            kind="menu",
            title="Diretoria",
            text=text,
            footer="Use esse menu como rotina da diretoria: risco da rota, cobranca, GVs, filiais, giro, ranking e resumo total. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=(
                flow.InteractiveOption(
                    option_id=flow.DIRECTOR_ACTION_VISIT_RISK,
                    title="Risco da Rota",
                    description="Ver risco financeiro por GV, setor e clientes",
                    shortcut="1",
                ),
                flow.InteractiveOption(
                    option_id=flow.DIRECTOR_ACTION_TOP_DEBTORS,
                    title="Cobranca",
                    description="Listar os maiores devedores da diretoria",
                    shortcut="2",
                ),
                flow.InteractiveOption(
                    option_id=flow.DIRECTOR_SUMMARY_BY_REVENDA,
                    title="GVs",
                    description="Abrir um GV da diretoria",
                    shortcut="3",
                ),
                flow.InteractiveOption(
                    option_id=flow.DIRECTOR_ACTION_BY_FILIAL,
                    title="Filiais",
                    description="Consolidar a diretoria por revenda",
                    shortcut="4",
                ),
                flow.InteractiveOption(
                    option_id=flow.DIRECTOR_ACTION_GIRO,
                    title="Giro",
                    description="Abrir o submenu de giro da diretoria",
                    shortcut="5",
                ),
                flow.InteractiveOption(
                    option_id=flow.DIRECTOR_ACTION_RANKING,
                    title="Ranking dos GVs",
                    description="Ordenar os GVs pelo maior valor pendente",
                    shortcut="6",
                ),
                flow.InteractiveOption(
                    option_id=flow.DIRECTOR_SUMMARY_TOTAL,
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
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        text = "Escolha a chave filial-GV que voce quer resumir."
        if invalid_selection:
            text = flow._invalid_option_text("Escolha a chave filial-GV que voce quer resumir.")
        return flow.OutgoingMessage(
            kind="menu",
            title="Resumo por GV",
            text=text,
            footer="Depois eu mostro o resumo comercial e de inadimplencia desse GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"finance:gv_summary:{index}",
                    title=flow._format_gv_scope_label(gv_code),
                    description="Ver resumo desse GV",
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_director_visit_risk_gv_menu(
        self,
        visit_day_label: str,
        gv_options: list[str],
        seller_summaries: list[flow.InadimplenciaVisitRiskSummary],
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        grouped: dict[str, list[flow.InadimplenciaVisitRiskSummary]] = {}
        for summary in seller_summaries:
            manager_code = flow.normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped.setdefault(manager_code, []).append(summary)

        total_clients = sum(summary.client_count for summary in seller_summaries)
        total_pendente = flow._sum_money_values(summary.total_pendente for summary in seller_summaries)
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
        return flow.OutgoingMessage(
            kind="menu",
            title="Diretoria | Risco da Rota",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro setores, clientes e valor por GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"director:visit_risk:gv:{index}",
                    title=flow._format_gv_scope_label(gv_code),
                    description=(
                        f"{len(grouped.get(gv_code, []))} setor(es) | "
                        f"{sum(item.client_count for item in grouped.get(gv_code, []))} cliente(s) | "
                        f"R$ {flow._sum_money_values(item.total_pendente for item in grouped.get(gv_code, []))}"
                    ),
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _build_director_visit_risk_sector_menu(
        self,
        visit_day_label: str,
        summaries: list[flow.InadimplenciaVisitRiskSummary],
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        total_clients = sum(summary.client_count for summary in summaries)
        total_pendente = flow._sum_money_values(summary.total_pendente for summary in summaries)
        gv_label = flow._format_gv_scope_label(summaries[0].manager_code) if summaries else "-"
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
        return flow.OutgoingMessage(
            kind="menu",
            title="Diretoria | Risco da Rota",
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro clientes e valor do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"{flow.FINANCE_VISIT_RISK_PICK_PREFIX}{summary.seller_code}:{summary.manager_code}",
                    title=flow._format_sector_scope_label(summary.seller_code),
                    description=f"{summary.client_count} cliente(s) | R$ {summary.total_pendente}",
                    shortcut=str(index),
                )
                for index, summary in enumerate(summaries, start=1)
            ),
        )

    def _build_director_visit_risk_sector_response(
        self,
        decision: flow.AccessDecision,
        summary: flow.InadimplenciaVisitRiskSummary,
        visit_day_token: str,
        visit_day_label: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui abrir os clientes desse setor agora.\n"
                    "Tente novamente em instantes."
                )
            )

        lines = [
            f"Diretoria | Risco da Rota em {visit_day_label}",
            f"{flow._format_gv_scope_label(summary.manager_code)} | Setor {str(summary.seller_code).split('_')[-1]}",
            f"Clientes com risco: {summary.client_count} | R$ {summary.total_pendente}",
            f"Atualizado: {(alerts[0].planilha_atualizada_em if alerts else summary.planilha_atualizada_em) or '-'}",
        ]
        if not alerts:
            lines.append("Nao encontrei clientes com risco para esse setor agora.")
            lines.append("")
            lines.append(flow._result_hint_text(allow_back=True))
            return flow.OutgoingMessage(text="\n".join(lines))

        overdue = [alert for alert in alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in alerts if alert.nearest_days_to_due == 0]
        lines.append("")
        self._append_visit_financial_group(lines, "Ja vencidos", overdue)
        self._append_visit_financial_group(lines, "Vence hoje", due_today)
        lines.append("")
        lines.append(flow._result_hint_text(allow_back=True))
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_director_gv_summary_menu(
        self,
        gv_options: list[str],
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        text = "Escolha o GV que voce quer abrir."
        if invalid_selection:
            text = flow._invalid_option_text("Escolha o GV que voce quer abrir.")
        return flow.OutgoingMessage(
            kind="menu",
            title="GVs da Diretoria",
            text=text,
            footer="Cada opcao representa uma chave Filial | GV dentro da sua diretoria. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"director:gv_summary:{index}",
                    title=flow._format_gv_scope_label(gv_code),
                    description="Ver resumo desse gerente",
                    shortcut=str(index),
                )
                for index, gv_code in enumerate(gv_options, start=1)
            ),
        )

    def _open_finance_visit_risk_selection(
        self,
        sender: str,
        session: flow.LookupSession,
        decision: flow.AccessDecision,
        *,
        visit_day_token: str,
        visit_day_label: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        try:
            summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(
                visit_day_token=visit_day_token,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=120,
            )
        except RuntimeError:
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui montar o risco financeiro desse dia agora.\n"
                    "Tente novamente em instantes."
                )
            )

        if not summaries:
            return flow.OutgoingMessage(
                text=(
                    f"Nao encontrei setores com visitas e risco financeiro em '{visit_day_label}'.\n"
                    "Se quiser continuar, envie MENU."
                )
            )

        gv_options = sorted(
            {
                flow.normalize_stored_scope_value(summary.manager_code)
                for summary in summaries
                if flow.normalize_stored_scope_value(summary.manager_code)
            },
            key=flow._sort_scope_code,
        )
        if len(gv_options) > 1:
            session.step = "finance_select_visit_risk_gv"
            session.visit_risk_day_options = ()
            session.finance_gv_options = tuple(gv_options)
            session.visit_risk_summaries = tuple(summaries)
            session.selected_visit_risk_gv = ""
            session.selected_visit_risk_token = visit_day_token
            session.selected_visit_risk_label = visit_day_label
            session.updated_at = flow.datetime.now(flow.timezone.utc)
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
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_menu(visit_day_label=visit_day_label, summaries=summaries)

    def _open_finance_visit_risk_day_selection(
        self,
        sender: str,
        session: flow.LookupSession,
        decision: flow.AccessDecision,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        try:
            raw_visit_days = self.query_service.list_visit_days(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=10,
            )
        except RuntimeError:
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui abrir os dias de risco da rota agora.\n"
                    "Tente novamente em instantes."
                )
            )
        visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            return flow.OutgoingMessage(
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
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_day_menu(visit_days=visit_days)

    def _build_finance_visit_risk_gv_menu(
        self,
        *,
        visit_day_label: str,
        gv_options: list[str],
        summaries: list[flow.InadimplenciaVisitRiskSummary],
        menu_title: str = "Risco da Rota",
        day_header_prefix: str = "Risco da rota",
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        total_clients = sum(summary.client_count for summary in summaries)
        total_pendente = flow._sum_money_values(summary.total_pendente for summary in summaries)
        grouped: dict[str, list[flow.InadimplenciaVisitRiskSummary]] = {}
        for summary in summaries:
            manager_code = flow.normalize_stored_scope_value(summary.manager_code)
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
        return flow.OutgoingMessage(
            kind="menu",
            title=menu_title,
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro setores, clientes e valor por GV. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"finance:visit_risk:gv:{index}",
                    title=flow._format_gv_scope_label(gv_code),
                    description=(
                        f"{len(grouped.get(gv_code, []))} setor(es) | "
                        f"{sum(item.client_count for item in grouped.get(gv_code, []))} cliente(s) | "
                        f"R$ {flow._sum_money_values(item.total_pendente for item in grouped.get(gv_code, []))}"
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
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        header = header_prompt
        if invalid_selection:
            header = flow._invalid_option_text(header_prompt)
        return flow.OutgoingMessage(
            kind="menu",
            title=menu_title,
            text=header,
            footer=(
                "Depois eu mostro o resumo dos GVs, o detalhe por setor e, em seguida, os clientes. "
                "Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"{flow.VISIT_DAY_PICK_PREFIX}{index}",
                    title=flow._format_visit_day_label(visit_day),
                    description="Ver setores e clientes com risco",
                    shortcut=str(index),
                )
                for index, visit_day in enumerate(visit_days, start=1)
            ),
        )

    def _build_finance_visit_risk_menu(
        self,
        visit_day_label: str,
        summaries: list[flow.InadimplenciaVisitRiskSummary],
        menu_title: str = "Risco da Rota",
        day_header_prefix: str = "Risco da rota",
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        total_clients = sum(summary.client_count for summary in summaries)
        total_pendente = flow._sum_money_values(summary.total_pendente for summary in summaries)
        lines = [f"{day_header_prefix} em {visit_day_label}:"]
        if invalid_selection:
            lines.insert(0, "Nao entendi essa opcao.")
        lines.append(f"*Setores com risco:* {len(summaries)}")
        lines.append(f"*Clientes com risco nesse dia:* {total_clients} | R$ {total_pendente}")
        lines.append(f"*Planilha atualizada em:* {summaries[0].planilha_atualizada_em or '-'}")
        lines.append("")
        lines.append("Detalhe por setor: escolha o setor para ver os clientes com risco.")
        return flow.OutgoingMessage(
            kind="menu",
            title=menu_title,
            text="\n".join(lines),
            footer="Na descricao de cada opcao eu mostro o GV, a quantidade e o valor do setor. Use A ou ANT para voltar.",
            button_text="Escolher",
            options=tuple(
                flow.InteractiveOption(
                    option_id=f"{flow.FINANCE_VISIT_RISK_PICK_PREFIX}{summary.seller_code}:{summary.manager_code}",
                    title=flow._format_sector_scope_label(summary.seller_code),
                    description=(
                        f"{flow._format_gv_scope_label(summary.manager_code)} | {summary.client_count} cliente(s) | "
                        f"R$ {summary.total_pendente}"
                    ),
                    shortcut=str(index),
                )
                for index, summary in enumerate(summaries, start=1)
            ),
        )

    def _build_finance_visit_risk_sector_response(
        self,
        decision: flow.AccessDecision,
        summary: flow.InadimplenciaVisitRiskSummary,
        visit_day_token: str,
        visit_day_label: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
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
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui abrir os clientes desse setor agora.\n"
                    "Tente novamente em instantes."
                )
            )

        lines = [
            f"Clientes de {flow._format_sector_scope_label(summary.seller_code)} com risco financeiro em {visit_day_label}:",
            f"{flow._format_gv_scope_label(summary.manager_code)} | {summary.client_count} cliente(s) com risco | R$ {summary.total_pendente}",
            f"Planilha atualizada em: {(alerts[0].planilha_atualizada_em if alerts else summary.planilha_atualizada_em) or '-'}",
        ]
        if not alerts:
            lines.append("Nao encontrei clientes com risco para esse setor agora.")
            lines.append("")
            lines.append("Se quiser continuar, envie MENU.")
            return flow.OutgoingMessage(text="\n".join(lines))

        overdue = [alert for alert in alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in alerts if alert.nearest_days_to_due == 0]
        lines.append("")
        self._append_visit_financial_group(lines, "Ja inadimplentes", overdue)
        self._append_visit_financial_group(lines, "Vence hoje", due_today)
        lines.append("")
        lines.append("Se quiser continuar, envie MENU.")
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_giro_visit_day_menu(
        self,
        visit_days: list[str],
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        header = "Qual dia voce quer consultar no giro?"
        if invalid_selection:
            header = flow._invalid_option_text("Escolha um dia para consultar o giro.")
        return flow.OutgoingMessage(
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

    def _build_giro_response(
        self,
        records: list[flow.GiroClientRecord],
        criteria: str,
        scope_restricted: bool = True,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        if not records:
            scope_note = "dentro do acesso liberado para o seu numero" if scope_restricted else "no relatorio de giro importado"
            return flow.OutgoingMessage(
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
            total_caixas = flow._format_quantity(
                flow._sum_formatted_amounts(
                    record.total_litrinho,
                    record.total_inteira,
                    record.total_litrao,
                )
            )
            caixas_faltando = flow._format_quantity(
                flow._sum_formatted_amounts(
                    record.gap_litrinho,
                    record.gap_inteira,
                    record.gap_litrao,
                )
            )
            gap_detail = flow._format_giro_gap_detail(record)
            lines.append("")
            lines.append(f"{index}. *{record.nome or '-'}* | Cod {record.cod_pdv or '-'}")
            lines.append(f"*Revenda:* {flow._format_filial_label(record.filial)} | *Setor:* {record.setor or '-'}")
            lines.append(f"*Base:* {total_caixas} | *Falta:* {caixas_faltando}")
            if gap_detail:
                lines.append(f"*Tipo:* {gap_detail}")
            lines.append(
                "Litrinho: "
                f"Base {flow._format_quantity(record.total_litrinho)} | "
                f"Faltam {flow._format_quantity(record.gap_litrinho)} | "
                f"Status {record.giro_litrinho}"
            )
            lines.append(
                "Inteira: "
                f"Base {flow._format_quantity(record.total_inteira)} | "
                f"Faltam {flow._format_quantity(record.gap_inteira)} | "
                f"Status {record.giro_inteira}"
            )
            lines.append(
                "Litrao: "
                f"Base {flow._format_quantity(record.total_litrao)} | "
                f"Faltam {flow._format_quantity(record.gap_litrao)} | "
                f"Status {record.giro_litrao}"
            )

        lines.append("")
        lines.append("Se quiser fazer outra consulta, envie MENU.")
        return flow.OutgoingMessage(text="\n".join(lines))

    def _safe_giro_scope_summary(self, decision: AccessDecision, gv_vdes_override: tuple[str, ...] | None=None) -> GiroScopeSummary | None:
        flow = _customer_flow_module()
        allowed_gv_vdes = gv_vdes_override if gv_vdes_override is not None else self._allowed_gv_vdes(decision)
        try:
            return self.giro_service.get_scope_summary(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=list(allowed_gv_vdes) if allowed_gv_vdes is not None else None)
        except RuntimeError:
            return None

    def _safe_giro_scope_summary_by_visit_day(self, decision: AccessDecision, *, visit_day: str) -> GiroScopeSummary | None:
        flow = _customer_flow_module()
        visit_day_token = flow._visit_day_token_from_label(visit_day) or visit_day
        try:
            return self.giro_service.get_scope_summary_by_visit_day(visit_day=visit_day_token, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        except (RuntimeError, ValueError):
            return None

    def _safe_giro_scope_summary_for_seller(self, decision: AccessDecision, seller_code: str, manager_code: str) -> GiroScopeSummary | None:
        flow = _customer_flow_module()
        try:
            return self.giro_service.get_scope_summary_for_seller(seller_code=seller_code, manager_code=manager_code, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        except RuntimeError:
            return None

    def _safe_giro_summary_by_filial(self, decision: AccessDecision) -> list[GiroFilialSummary]:
        flow = _customer_flow_module()
        try:
            return self.giro_service.list_summary_by_filial(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        except RuntimeError:
            return []

    def _safe_giro_summary_by_gv(self, decision: AccessDecision) -> list[GiroManagementSummary]:
        flow = _customer_flow_module()
        try:
            return self.giro_service.list_summary_by_gv(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        except RuntimeError:
            return []

    def _safe_giro_summary_by_seller(self, decision: AccessDecision) -> list[GiroSellerSummary]:
        flow = _customer_flow_module()
        try:
            return self.giro_service.list_summary_by_seller(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        except RuntimeError:
            return []

    def _safe_giro_zero_base_records(self, decision: AccessDecision) -> list[GiroZeroBaseRecord] | None:
        flow = _customer_flow_module()
        try:
            return self.giro_service.list_giro_zero_base(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=2000)
        except RuntimeError:
            return None

    def _safe_giro_history_by_registration(self, *, decision: AccessDecision, filial: str, cod_pdv: str) -> list[GiroClientRecord]:
        flow = _customer_flow_module()
        search_history = getattr(self.giro_service, 'search_history_by_registration', None)
        if not callable(search_history):
            return []
        try:
            return search_history(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=1)
        except (RuntimeError, ValueError):
            return []

    def _append_giro_summary_lines(self, lines: list[str], summary: GiroScopeSummary | None, *, compact: bool, show_details: bool=False) -> None:
        flow = _customer_flow_module()
        if summary is None:
            return
        total_monitored = summary.litrinho_monitored_count + summary.inteira_monitored_count + summary.litrao_monitored_count
        total_ok = summary.litrinho_ok_count + summary.inteira_ok_count + summary.litrao_ok_count
        if not show_details:
            lines.append(f'Resumo OK: Litrinho {flow._format_percent_ratio(summary.litrinho_ok_count, summary.litrinho_monitored_count)} | Inteira {flow._format_percent_ratio(summary.inteira_ok_count, summary.inteira_monitored_count)} | Litrao {flow._format_percent_ratio(summary.litrao_ok_count, summary.litrao_monitored_count)} | Total {flow._format_percent_ratio(total_ok, total_monitored)}')
            return
        total_zero = summary.litrinho_zero_count + summary.inteira_zero_count + summary.litrao_zero_count
        total_gap = flow._sum_formatted_amounts(summary.litrinho_gap_total, summary.inteira_gap_total, summary.litrao_gap_total)
        lines.append(f'Litrinho: Total {flow._format_quantity(summary.litrinho_monitored_count)} | Caixas OK {flow._format_quantity(summary.litrinho_ok_count)} | % Giro OK {flow._format_percent_ratio(summary.litrinho_ok_count, summary.litrinho_monitored_count)} | Gap {summary.litrinho_gap_total} | Giro Zero {flow._format_quantity(summary.litrinho_zero_count)}')
        lines.append(f'Inteira: Total {flow._format_quantity(summary.inteira_monitored_count)} | Caixas OK {flow._format_quantity(summary.inteira_ok_count)} | % Giro OK {flow._format_percent_ratio(summary.inteira_ok_count, summary.inteira_monitored_count)} | Gap {summary.inteira_gap_total} | Giro Zero {flow._format_quantity(summary.inteira_zero_count)}')
        lines.append(f'Litrao: Total {flow._format_quantity(summary.litrao_monitored_count)} | Caixas OK {flow._format_quantity(summary.litrao_ok_count)} | % Giro OK {flow._format_percent_ratio(summary.litrao_ok_count, summary.litrao_monitored_count)} | Gap {summary.litrao_gap_total} | Giro Zero {flow._format_quantity(summary.litrao_zero_count)}')
        lines.append(f'Total: Total {flow._format_quantity(total_monitored)} | Caixas OK {flow._format_quantity(total_ok)} | % Giro OK {flow._format_percent_ratio(total_ok, total_monitored)} | Gap {total_gap} | Giro Zero {flow._format_quantity(total_zero)}')

    def _format_giro_total_scope_line(self, summary: GiroScopeSummary | None, *, label: str, child_count_label: str='', child_count: int | None=None) -> str:
        flow = _customer_flow_module()
        if summary is None:
            return label
        total_monitored = summary.litrinho_monitored_count + summary.inteira_monitored_count + summary.litrao_monitored_count
        total_ok = summary.litrinho_ok_count + summary.inteira_ok_count + summary.litrao_ok_count
        total_zero = summary.litrinho_zero_count + summary.inteira_zero_count + summary.litrao_zero_count
        total_gap = flow._sum_formatted_amounts(summary.litrinho_gap_total, summary.inteira_gap_total, summary.litrao_gap_total)
        segments = [label]
        if child_count_label and child_count is not None:
            segments.append(f'{child_count_label} {child_count}')
        segments.extend([f'Total {flow._format_quantity(total_monitored)}', f'Caixas OK {flow._format_quantity(total_ok)}', f'% Giro OK {flow._format_percent_ratio(total_ok, total_monitored)}', f'Gap {total_gap}', f'Giro Zero {flow._format_quantity(total_zero)}'])
        return ' | '.join(segments)

    def _format_scope_update_line(self, *, client_updated: str | None, inad_updated: str | None, giro_updated: str | None) -> str:
        flow = _customer_flow_module()
        return f"Atualizado: Clientes {(client_updated or '-') or '-'} | Inadimplencia {(inad_updated or '-') or '-'} | Giro {(giro_updated or '-') or '-'}"

    def _format_due_compact_line(self, *, today_count: int, today_total: str, tomorrow_count: int, tomorrow_total: str, two_days_count: int, two_days_total: str) -> str:
        flow = _customer_flow_module()
        return f'Vencimentos: Hoje {today_count} (R$ {today_total}) | Amanha {tomorrow_count} (R$ {tomorrow_total}) | 2 dias {two_days_count} (R$ {two_days_total})'

    def _group_giro_management_summaries_by_filial(self, summaries: list[GiroManagementSummary]) -> dict[str, list[GiroManagementSummary]]:
        flow = _customer_flow_module()
        grouped: dict[str, list[flow.GiroManagementSummary]] = {}
        for summary in summaries:
            filial, _ = flow.split_scope_pair(summary.manager_code) or ('', '')
            filial_code = flow.normalize_stored_scope_value(filial)
            if not filial_code:
                continue
            grouped.setdefault(filial_code, []).append(summary)
        return grouped

    def _group_giro_seller_summaries_by_manager(self, summaries: list[GiroSellerSummary]) -> dict[str, list[GiroSellerSummary]]:
        flow = _customer_flow_module()
        grouped: dict[str, list[flow.GiroSellerSummary]] = {}
        for summary in summaries:
            manager_code = flow.normalize_stored_scope_value(summary.manager_code)
            if not manager_code:
                continue
            grouped.setdefault(manager_code, []).append(summary)
        return grouped

    def _build_gv_summary_response(self, decision: AccessDecision, gv_vdes_override: tuple[str, ...] | None=None, title: str | None=None) -> OutgoingMessage:
        flow = _customer_flow_module()
        selected_gv_vdes = tuple(gv_vdes_override or decision.gv_vdes)
        cache_key = self._decision_scope_cache_key(decision, 'summary', 'gv', selected_gv_vdes, title or '')
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summary = self.query_service.get_scope_summary(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=list(selected_gv_vdes))
            inad_summary = self.inadimplencia_service.get_finance_summary(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=list(selected_gv_vdes))
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui montar esse resumo agora.\nTente novamente em instantes.')
        giro_summary = self._safe_giro_scope_summary(decision, gv_vdes_override=selected_gv_vdes)
        scope_role = flow.ROLE_DIRETOR_COMERCIAL if any((str(value).startswith('dc:') for value in selected_gv_vdes)) else flow.ROLE_GERENTE_VENDAS
        gv_label = flow._format_gv_vdes(selected_gv_vdes, role_name=scope_role)
        lines = [title or f'Resumo de {gv_label}']
        if gv_label and (len(selected_gv_vdes) > 1 or scope_role == flow.ROLE_DIRETOR_COMERCIAL):
            lines.append(f'*Base consultada:* {gv_label}')
        lines.append('')
        if scope_role == flow.ROLE_DIRETOR_COMERCIAL:
            lines.append(f'Base: {client_summary.client_count} clientes | {client_summary.seller_count} setores')
            lines.append(f'Cobranca: {inad_summary.client_count} inadimplentes | R$ {inad_summary.total_pendente} | Ja vencidos {inad_summary.overdue_count}')
            lines.append(self._format_due_compact_line(today_count=inad_summary.due_today_count, today_total=inad_summary.due_today_total, tomorrow_count=inad_summary.due_tomorrow_count, tomorrow_total=inad_summary.due_tomorrow_total, two_days_count=inad_summary.due_in_two_days_count, two_days_total=inad_summary.due_in_two_days_total))
            self._append_giro_summary_lines(lines, giro_summary, compact=True)
            lines.append(self._format_scope_update_line(client_updated=client_summary.planilha_atualizada_em, inad_updated=inad_summary.planilha_atualizada_em, giro_updated=giro_summary.planilha_atualizada_em if giro_summary else '-'))
        else:
            lines.append(f'*Clientes na base:* {client_summary.client_count}')
            lines.append(f'*Setores na base:* {client_summary.seller_count}')
            lines.append(f'*Clientes inadimplentes:* {inad_summary.client_count}')
            lines.append(f'*Valor total pendente:* R$ {inad_summary.total_pendente}')
            lines.append(f'*Ja vencidos:* {inad_summary.overdue_count} cliente(s) | R$ {inad_summary.overdue_total}')
            lines.append(f'*Vence hoje:* {inad_summary.due_today_count} cliente(s) | R$ {inad_summary.due_today_total}')
            lines.append(f'*Vence amanha:* {inad_summary.due_tomorrow_count} cliente(s) | R$ {inad_summary.due_tomorrow_total}')
            lines.append(f'*Vence em 2 dias:* {inad_summary.due_in_two_days_count} cliente(s) | R$ {inad_summary.due_in_two_days_total}')
            self._append_giro_summary_lines(lines, giro_summary, compact=False)
            lines.append('')
            lines.append(f"Atualizado em:\nClientes: {client_summary.planilha_atualizada_em or '-'}\nInadimplencia: {inad_summary.planilha_atualizada_em or '-'}\nGiro: {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}")
        lines.append('')
        lines.append(flow._result_hint_text())
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text='\n'.join(lines)))

    def _build_seller_summary_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        cache_key = self._decision_scope_cache_key(decision, 'summary', 'seller')
        cached = self._get_cached_response(cache_key)
        if cached is not None:
            return cached
        try:
            client_summary = self.query_service.get_scope_summary(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
            inad_summary = self.inadimplencia_service.get_finance_summary(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui montar o resumo da sua carteira agora.\nTente novamente em instantes.')
        giro_summary = self._safe_giro_scope_summary(decision)
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        current_visit_label = flow._format_visit_day_label(current_visit_day) if current_visit_day else flow._current_visit_day_label().title()
        visit_count = 0
        risk_alerts: list[flow.InadimplenciaVisitAlert] = []
        risk_note = ''
        if current_visit_day:
            try:
                visit_clients = self.query_service.list_clients_by_visit_day(visit_day=current_visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=200)
                risk_alerts = self.inadimplencia_service.list_upcoming_by_visit_day(visit_day=current_visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=200)
                visit_count = len(visit_clients)
            except RuntimeError:
                risk_note = 'Nao consegui consultar o risco da rota agora.'
        else:
            risk_note = 'Nao encontrei visitas programadas para hoje na sua carteira.'
        risk_today_alerts = [alert for alert in risk_alerts if alert.nearest_days_to_due <= 0]
        lines = ['Carteira de Hoje', '']
        lines.append(f'Base: {client_summary.client_count} clientes | {client_summary.seller_count} setor(es)')
        lines.append(f'Cobranca da carteira: {inad_summary.client_count} inadimplentes | R$ {inad_summary.total_pendente}')
        lines.append(f'Ja vencidos: {inad_summary.overdue_count} cliente(s) | R$ {inad_summary.overdue_total}')
        lines.append(f'Vence hoje: {inad_summary.due_today_count} cliente(s) | R$ {inad_summary.due_today_total}')
        lines.append(f'Vence amanha: {inad_summary.due_tomorrow_count} cliente(s) | R$ {inad_summary.due_tomorrow_total}')
        lines.append(f'Vence em 2 dias: {inad_summary.due_in_two_days_count} cliente(s) | R$ {inad_summary.due_in_two_days_total}')
        self._append_giro_summary_lines(lines, giro_summary, compact=False)
        lines.append('')
        lines.append(f'*Rota de hoje ({current_visit_label}):* {visit_count} visita(s)')
        if risk_note:
            lines.append(risk_note)
        else:
            lines.append(f'Risco da rota: {len(risk_today_alerts)} cliente(s) | R$ {flow._sum_money_values((alert.total_pendente for alert in risk_today_alerts))}')
        lines.append('')
        lines.append(f"Atualizado em:\nClientes: {client_summary.planilha_atualizada_em or '-'}\nInadimplencia: {inad_summary.planilha_atualizada_em or '-'}\nGiro: {(giro_summary.planilha_atualizada_em if giro_summary else '-') or '-'}")
        lines.append('')
        lines.append('Se quiser continuar, envie MENU.')
        return self._store_cached_response(cache_key, flow.OutgoingMessage(text='\n'.join(lines)))

    def _build_seller_risk_response(self, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        current_visit_day = self._resolve_current_scope_visit_day_label(decision)
        current_visit_label = flow._format_visit_day_label(current_visit_day) if current_visit_day else flow._current_visit_day_label().title()
        if not current_visit_day:
            return flow.OutgoingMessage(text=f'Nao encontrei visitas programadas para hoje ({current_visit_label}) na sua carteira.\n{flow._result_hint_text()}')
        return self._build_seller_visit_day_risk_response(decision=decision, visit_day=current_visit_day, visit_day_label=current_visit_label, current_day_only=True)

    def _build_seller_visit_day_risk_response(self, *, decision: AccessDecision, visit_day: str, visit_day_label: str, current_day_only: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            visit_clients = self.query_service.list_clients_by_visit_day(visit_day=visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=200)
            alerts = self.inadimplencia_service.list_upcoming_by_visit_day(visit_day=visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=200)
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui consultar o risco da sua rota agora.\nTente novamente em instantes.')
        relevant_alerts = [alert for alert in alerts if alert.nearest_days_to_due <= 0] if current_day_only else list(alerts)
        title = f'Risco da Rota em {visit_day_label}'
        summary_label = 'Clientes com risco'
        empty_text = 'Nao encontrei clientes da sua rota vencendo hoje ou ja inadimplentes.' if current_day_only else f"Nao encontrei clientes da sua rota com vencimento proximo ou inadimplencia em '{visit_day_label}'."
        lines = [title, f'Visitas na rota: {len(visit_clients)}', f'{summary_label}: {len(relevant_alerts)} | R$ {flow._sum_money_values((alert.total_pendente for alert in relevant_alerts))}', f"Planilha atualizada em: {(alerts[0].planilha_atualizada_em if alerts else '-') or '-'}"]
        if not relevant_alerts:
            lines.append('')
            lines.append(empty_text)
            return flow.OutgoingMessage(text='\n'.join(lines))
        overdue = [alert for alert in relevant_alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in relevant_alerts if alert.nearest_days_to_due == 0]
        due_tomorrow = [alert for alert in relevant_alerts if alert.nearest_days_to_due == 1]
        due_in_two_days = [alert for alert in relevant_alerts if alert.nearest_days_to_due == 2]
        lines.append('')
        self._append_visit_financial_group(lines, 'Ja inadimplentes', overdue)
        self._append_visit_financial_group(lines, 'Vence hoje', due_today)
        if not current_day_only:
            self._append_visit_financial_group(lines, 'Vence amanha', due_tomorrow)
            self._append_visit_financial_group(lines, 'Vence em 2 dias', due_in_two_days)
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _resolve_current_scope_visit_day_label(self, decision: AccessDecision) -> str:
        flow = _customer_flow_module()
        try:
            raw_visit_days = self.query_service.list_visit_days(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
            visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
        except RuntimeError:
            return ''
        current_token = flow._current_visit_day_token()
        for visit_day in visit_days:
            if flow._visit_day_token_from_label(visit_day) == current_token:
                return visit_day
        return ''

    def _open_director_summary_menu(self, sender: str, session: LookupSession) -> OutgoingMessage:
        flow = _customer_flow_module()
        self._clear_clarification_state(session)
        self._remember_last_context(session, intent='director_summary', search_context='inadimplencia')
        session.step = 'awaiting_director_summary_mode'
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_director_summary_menu()

    def _open_director_visit_risk_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_days = [label for _, label in flow.VISIT_DAY_CHOICES]
        session.step = 'director_select_visit_risk_day'
        session.visit_risk_day_options = tuple(visit_days)
        session.visit_risk_summaries = ()
        session.finance_gv_options = ()
        session.selected_visit_risk_gv = ''
        session.selected_visit_risk_token = ''
        session.selected_visit_risk_label = ''
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_director_visit_risk_day_menu(visit_days=visit_days)

    def _open_manager_summary_menu(self, sender: str, session: LookupSession) -> OutgoingMessage:
        flow = _customer_flow_module()
        self._clear_clarification_state(session)
        self._remember_last_context(session, intent='manager_summary', search_context='inadimplencia')
        session.step = 'awaiting_manager_summary_mode'
        session.summary_filial_options = ()
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_manager_summary_menu()

    def _open_manager_filial_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        filial_options = flow._extract_filial_options_from_scope_codes(decision.gv_vdes)
        if not filial_options:
            return flow.OutgoingMessage(text='Nao encontrei filiais disponiveis para esse resumo agora.\nSe quiser continuar, envie MENU.')
        if len(filial_options) == 1:
            selected_filial = filial_options[0]
            selected_scope_keys = flow._filter_scope_codes_by_filial(decision.gv_vdes, selected_filial)
            return self._with_post_result_navigation(sender, session, self._build_gv_summary_response(decision=decision, gv_vdes_override=selected_scope_keys, title=f'Resumo da Gerencia | {flow._format_filial_label(selected_filial)}'), return_menu='manager_summary')
        session.step = 'awaiting_manager_filial_selection'
        session.summary_filial_options = tuple(filial_options)
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_manager_filial_summary_menu(filial_options=filial_options)

    def _open_manager_seller_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            seller_summaries = self.query_service.list_seller_base_summaries(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=120)
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui abrir a lista dos vendedores agora.\nTente novamente em instantes.')
        if not seller_summaries:
            return flow.OutgoingMessage(text='Nao encontrei vendedores disponiveis para esse resumo agora.\nSe quiser continuar, envie MENU.')
        if len(seller_summaries) == 1:
            summary = seller_summaries[0]
            self._remember_last_context(session, intent='manager_seller_summary', search_context='inadimplencia', query_text=summary.seller_code)
            return self._with_post_result_navigation(sender, session, self._build_manager_seller_summary_response(decision=decision, summary=summary), return_menu='manager_summary')
        session.step = 'awaiting_manager_seller_summary_selection'
        session.visit_seller_summaries = tuple(seller_summaries)
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_manager_seller_summary_menu(seller_summaries)

    def _open_manager_visit_risk_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            raw_visit_days = self.query_service.list_visit_days(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
            visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui abrir os dias de visita agora.\nTente novamente em instantes.')
        if not visit_days:
            return flow.OutgoingMessage(text='Nao encontrei visitas disponiveis para esse risco agora.\nSe quiser continuar, envie MENU.')
        session.step = 'manager_select_visit_risk_day'
        session.visit_risk_day_options = tuple(visit_days)
        session.visit_risk_summaries = ()
        session.finance_gv_options = ()
        session.selected_visit_risk_gv = ''
        session.selected_visit_risk_token = ''
        session.selected_visit_risk_label = ''
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_day_menu(visit_days=visit_days, menu_title='Risco da Rota', header_prompt='Escolha o dia da semana para ver o risco da rota da gerencia.')

    def _open_manager_visit_risk_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, visit_day_token: str, visit_day_label: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(visit_day_token=visit_day_token, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=120)
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui consultar as visitas com risco agora.\nTente novamente em instantes.')
        if not summaries:
            return flow.OutgoingMessage(text=f"Nao encontrei setores com risco em '{visit_day_label}'.\nSe quiser continuar, envie MENU.")
        gv_options = sorted({flow.normalize_stored_scope_value(summary.manager_code) for summary in summaries if flow.normalize_stored_scope_value(summary.manager_code)}, key=flow._sort_scope_code)
        if len(gv_options) > 1:
            session.step = 'manager_select_visit_risk_gv'
            session.visit_risk_day_options = ()
            session.finance_gv_options = tuple(gv_options)
            session.visit_risk_summaries = tuple(summaries)
            session.selected_visit_risk_gv = ''
            session.selected_visit_risk_token = visit_day_token
            session.selected_visit_risk_label = visit_day_label
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_finance_visit_risk_gv_menu(visit_day_label=visit_day_label, gv_options=gv_options, summaries=summaries, menu_title='Risco da Rota', day_header_prefix='Risco da rota')
        session.step = 'manager_select_visit_risk_sector'
        session.visit_risk_day_options = ()
        session.visit_risk_summaries = tuple(summaries)
        session.finance_gv_options = tuple(gv_options)
        session.selected_visit_risk_gv = gv_options[0] if gv_options else ''
        session.selected_visit_risk_token = visit_day_token
        session.selected_visit_risk_label = visit_day_label
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_finance_visit_risk_menu(visit_day_label=visit_day_label, summaries=summaries, menu_title='Risco da Rota', day_header_prefix='Risco da rota')

    def _open_director_gv_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            gv_options = self.query_service.list_gv_vdes(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui abrir a lista dos gerentes agora.\nTente novamente em instantes.')
        if not gv_options:
            return flow.OutgoingMessage(text='Nao encontrei gerentes de vendas disponiveis para esse resumo agora.\nSe quiser continuar, envie MENU.')
        if len(gv_options) == 1:
            return self._with_post_result_navigation(sender, session, self._build_gv_summary_response(decision=decision, gv_vdes_override=(gv_options[0],), title=f'Resumo do GV {flow._format_gv_scope_label(gv_options[0])}'), return_menu='director_summary')
        session.step = 'awaiting_gv_summary_selection'
        session.finance_gv_options = tuple(gv_options)
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_director_gv_summary_menu(gv_options=gv_options)

    def _open_director_visit_risk_gv_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, visit_day_token: str, visit_day_label: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            summaries = self.inadimplencia_service.list_visit_day_risk_by_seller(visit_day_token=visit_day_token, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=250)
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui consultar as visitas com risco agora.\nTente novamente em instantes.')
        if not summaries:
            return flow.OutgoingMessage(text=f"Nao encontrei GVs com risco em '{visit_day_label}'.\nSe quiser continuar, envie MENU.")
        gv_options = sorted({flow.normalize_stored_scope_value(summary.manager_code) for summary in summaries if flow.normalize_stored_scope_value(summary.manager_code)}, key=flow._sort_numeric_text)
        if not gv_options:
            return flow.OutgoingMessage(text=f"Nao encontrei GVs com risco em '{visit_day_label}'.\nSe quiser continuar, envie MENU.")
        session.step = 'director_select_visit_risk_gv'
        session.finance_gv_options = tuple(gv_options)
        session.visit_risk_summaries = tuple(summaries)
        session.selected_visit_risk_gv = ''
        session.selected_visit_risk_token = visit_day_token
        session.selected_visit_risk_label = visit_day_label
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_director_visit_risk_gv_menu(visit_day_label=visit_day_label, gv_options=gv_options, seller_summaries=summaries)
