from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class SearchFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def _prepare_search_session(self, session: LookupSession, *, search_context: str) -> None:
        flow = _customer_flow_module()
        session.step = 'awaiting_search_mode'
        session.search_context = search_context
        self._clear_clarification_state(session)
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
        session.visit_group_summaries = ()
        session.selected_visit_gv = ''
        session.giro_visit_sector_summaries = ()
        session.giro_visit_summary_text = ''
        session.selected_giro_visit_gv = ''
        session.selected_visit_risk_gv = ''
        session.updated_at = flow.datetime.now(flow.timezone.utc)

    def _open_search_context(self, sender: str, session: LookupSession, *, search_context: str, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        self._prepare_search_session(session, search_context=search_context)
        self._remember_last_context(session, intent=f'search_{search_context}', search_context=search_context)
        self.sessions[sender] = session
        return self._build_search_menu(search_context=search_context, decision=decision)

    def _run_search_menu_option(self, sender: str, session: LookupSession, decision: AccessDecision, *, option_id: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        if option_id == flow.SEARCH_BY_REGISTRATION:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._activate_search_mode(sender, session, search_mode='registration')
        if option_id == flow.SEARCH_BY_FANTASIA:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._activate_search_mode(sender, session, search_mode='name')
        if option_id == flow.SEARCH_BY_DOCUMENT:
            access_error = None
            if session.search_context in {'cliente', 'giro', 'inadimplencia', 'comodato', 'documentacao', 'prazo_limite'}:
                access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._activate_search_mode(sender, session, search_mode='document')
        if option_id == flow.SEARCH_BY_INADIMPLENTES_BASE and session.search_context == 'inadimplencia':
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._open_inadimplencia_summary_selection(sender=sender, session=session, decision=decision, order_by='total_pendente', header_text=f'Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.', empty_text='No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\nSe quiser tentar outra consulta, envie MENU.', page=1, page_size=flow.INADIMPLENCIA_PAGE_SIZE, list_context=flow.INADIMPLENCIA_CONTEXT_SCOPE_BASE)
        if option_id in {flow.FINANCE_DUE_TOMORROW, flow.FINANCE_DUE_IN_TWO_DAYS} and session.search_context == 'inadimplencia':
            due_bucket = 'tomorrow' if option_id == flow.FINANCE_DUE_TOMORROW else 'in_two_days'
            return self._run_scoped_inadimplencia_due_bucket(sender=sender, session=session, decision=decision, due_bucket=due_bucket)
        if option_id == flow.SEARCH_BY_VISIT_DAY:
            if session.search_context == 'giro':
                return self._open_giro_visit_day_conversation(sender=sender, session=session, decision=decision)
            if session.search_context == 'inadimplencia':
                return self._open_inadimplencia_visit_day_conversation(sender=sender, session=session, decision=decision)
            if session.search_context == 'documentacao':
                return self._open_documentacao_visit_day_conversation(sender=sender, session=session, decision=decision)
        if option_id == flow.SEARCH_BY_GIRO_ZERO_BASE and session.search_context == 'giro':
            self._remember_last_context(session, intent='giro_zero_base', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_zero_base_response(decision), return_menu='search_menu')
        self.sessions[sender] = session
        return self._build_search_menu(search_context=session.search_context, decision=decision, invalid_selection=True)

    def _activate_search_mode(self, sender: str, session: LookupSession, *, search_mode: str) -> OutgoingMessage:
        flow = _customer_flow_module()
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
        if search_mode == 'registration':
            session.step = 'awaiting_filial'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(text=flow._build_filial_prompt(session.search_context))
        if search_mode == 'document':
            session.step = 'awaiting_document'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
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
            return flow.OutgoingMessage(text='Digite o CPF ou CNPJ do cliente.\nVou respeitar o mesmo acesso comercial liberado para o seu numero.')
        session.step = 'awaiting_fantasia'
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
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

    def _run_name_search(self, sender: str, session: LookupSession, decision: AccessDecision, *, query_text: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        cleaned_query = ' '.join(str(query_text or '').strip().split())
        if len(cleaned_query) < 3:
            self.sessions[sender] = session
            return flow.OutgoingMessage(text='Digite pelo menos 3 letras do nome do cliente.')
        self._remember_last_context(session, intent=f'search_{session.search_context}', search_context=session.search_context, query_text=cleaned_query)
        if session.search_context == 'inadimplencia':
            summaries = self.inadimplencia_service.search_client_summaries_by_name(query_text=cleaned_query, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
            if not summaries:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return flow.OutgoingMessage(text=f"Nao encontrei cliente com '{cleaned_query}' na inadimplencia.\nPode me enviar outro trecho ou, se preferir, digite MENU.")
            if len(summaries) == 1:
                summary = summaries[0]
                self._remember_last_context(session, intent='inadimplencia_client', search_context='inadimplencia', client_filial=summary.filial, client_cod_pdv=summary.cod_pdv, client_name=summary.nome)
                records = self.inadimplencia_service.search_by_registration(filial=summary.filial, cod_pdv=summary.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
                return self._with_post_result_navigation(sender, session, self._build_inadimplencia_response(records, f'cliente {summary.nome} | revenda {summary.filial} | NB {summary.cod_pdv}'), return_menu='search_menu')
            session.step = 'awaiting_inadimplencia_client_selection'
            session.fantasia_query = cleaned_query
            session.inadimplencia_client_summaries = tuple(summaries)
            session.inadimplencia_total_available = len(summaries)
            session.inadimplencia_list_context = ''
            session.inadimplencia_page = 1
            session.inadimplencia_page_size = flow.INADIMPLENCIA_PAGE_SIZE
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_inadimplencia_client_menu(query_text=cleaned_query, summaries=summaries)
        if session.search_context == 'comodato':
            summaries = self.comodatos_service.search_client_summaries_by_name(query_text=cleaned_query, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
            if not summaries:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return flow.OutgoingMessage(text=f"Nao encontrei cliente com '{cleaned_query}' nos comodatos pendentes.\nPode me enviar outro trecho ou, se preferir, digite MENU.")
            if len(summaries) == 1:
                summary = summaries[0]
                self._remember_last_context(session, intent='comodato_client', search_context='comodato', client_filial=summary.filial, client_cod_pdv=summary.cod_pdv, client_name=summary.nome)
                records = self.comodatos_service.search_by_registration(filial=summary.filial, cod_pdv=summary.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
                return self._with_post_result_navigation(sender, session, self._build_comodato_response(records, f'cliente {summary.nome} | revenda {summary.filial} | NB {summary.cod_pdv}'), return_menu='search_menu')
            session.step = 'awaiting_comodato_client_selection'
            session.fantasia_query = cleaned_query
            session.comodato_client_summaries = tuple(summaries)
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_comodato_client_menu(query_text=cleaned_query, summaries=summaries)
        records = self.query_service.search_by_fantasia(query_text=cleaned_query, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
        if not records:
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(text=f"Nao encontrei cliente com '{cleaned_query}' no nome.\nPode me enviar outro trecho ou, se preferir, digite MENU.")
        if len(records) == 1:
            record = records[0]
            self._remember_last_context(session, intent=f'{session.search_context}_client', search_context=session.search_context, client_filial=record.filial, client_cod_pdv=record.cod_pdv, client_name=record.nome_fantasia or record.razao_social)
            if session.search_context == 'giro':
                giro_records = self.giro_service.search_by_registration(filial=record.filial, cod_pdv=record.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
                criteria = f"nome fantasia contendo '{cleaned_query}' | revenda {record.filial} | NB {record.cod_pdv}"
                if not giro_records:
                    historical_response = self._build_giro_historical_fallback_response(decision=decision, filial=record.filial, cod_pdv=record.cod_pdv, criteria=criteria)
                    if historical_response is not None:
                        return self._with_post_result_navigation(sender, session, historical_response, return_menu='search_menu')
                return self._with_post_result_navigation(sender, session, self._build_giro_response(giro_records, criteria=criteria, scope_restricted=not self._has_unrestricted_lookup_access(decision)), return_menu='search_menu')
            if session.search_context == 'documentacao':
                documentacao_records = self.documentacao_pendente_service.search_by_registration(filial=record.filial, cod_pdv=record.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
                return self._with_post_result_navigation(sender, session, self._build_documentacao_pendente_response(documentacao_records, criteria=f"nome fantasia contendo '{cleaned_query}' | revenda {record.filial} | NB {record.cod_pdv}", scope_restricted=not self._has_unrestricted_lookup_access(decision)), return_menu='search_menu')
            if session.search_context == 'prazo_limite':
                prazo_limite_records = self.prazo_limite_service.search_by_registration(filial=record.filial, cod_pdv=record.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
                if not prazo_limite_records:
                    return flow.OutgoingMessage(text=f"Encontrei o cadastro para '{record.nome_fantasia or record.razao_social or cleaned_query}', mas ele nao apareceu no ultimo relatorio de prazo e limite importado.\nSe quiser tentar outra busca, envie MENU.")
                return self._with_post_result_navigation(sender, session, self._build_prazo_limite_response(prazo_limite_records, criteria=f"nome fantasia contendo '{cleaned_query}' | revenda {record.filial} | NB {record.cod_pdv}", decision=decision, scope_restricted=not self._has_unrestricted_lookup_access(decision)), return_menu='search_menu')
            return self._with_post_result_navigation(sender, session, self._build_single_record_response(record=record, criteria=f"nome fantasia contendo '{cleaned_query}'", decision=decision), return_menu='search_menu')
        session.step = 'awaiting_fantasia_selection'
        session.fantasia_query = cleaned_query
        session.fantasia_results = tuple(records)
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_fantasia_results_menu(query_text=cleaned_query, records=records, search_context=session.search_context)

    def _run_document_lookup(self, sender: str, session: LookupSession, decision: AccessDecision, *, document: str, return_menu: str='search_menu') -> OutgoingMessage:
        flow = _customer_flow_module()
        normalized_document = flow._normalize_document(document)
        if not normalized_document:
            self.sessions[sender] = session
            return flow.OutgoingMessage(text='Digite um CPF ou CNPJ valido, com 11 ou 14 numeros.')
        if session.search_context == 'inadimplencia':
            records = self.inadimplencia_service.search_by_document(document=normalized_document, allowed_sectors=None, allowed_gv_vdes=None, limit=50)
            if records:
                self._remember_last_context(session, intent='inadimplencia_document', search_context='inadimplencia', client_filial=records[0].filial, client_cod_pdv=records[0].cod_pdv, client_name=records[0].nome)
            return self._with_post_result_navigation(sender, session, self._build_inadimplencia_response(records, f'CPF/CNPJ {normalized_document}'), return_menu=return_menu, repeat_action=flow.REPEAT_SEARCH_DOCUMENT)
        if session.search_context == 'comodato':
            records = self.comodatos_service.search_by_document(document=normalized_document, allowed_sectors=None, allowed_gv_vdes=None, limit=50)
            if records:
                self._remember_last_context(session, intent='comodato_document', search_context='comodato', client_filial=records[0].filial, client_cod_pdv=records[0].cod_pdv, client_name=records[0].nome)
            return self._with_post_result_navigation(sender, session, self._build_comodato_response(records, f'CPF/CNPJ {normalized_document}'), return_menu=return_menu, repeat_action=flow.REPEAT_SEARCH_DOCUMENT)
        if session.search_context == 'giro':
            records = self._search_giro_by_document(normalized_document)
            if records:
                self._remember_last_context(session, intent='giro_document', search_context='giro', client_filial=records[0].filial, client_cod_pdv=records[0].cod_pdv, client_name=records[0].nome)
            return self._with_post_result_navigation(sender, session, self._build_giro_response(records, f'CPF/CNPJ {normalized_document}', scope_restricted=False), return_menu=return_menu, repeat_action=flow.REPEAT_SEARCH_DOCUMENT)
        if session.search_context == 'documentacao':
            base_records = self.query_service.search_by_document(document=normalized_document, allowed_sectors=None, allowed_gv_vdes=None, limit=50)
            documentacao_records: list[flow.DocumentacaoPendenteClientRecord] = []
            for base_record in base_records:
                documentacao_records.extend(self.documentacao_pendente_service.search_by_registration(filial=base_record.filial, cod_pdv=base_record.cod_pdv, allowed_sectors=None, allowed_gv_vdes=None, limit=5))
            if documentacao_records:
                self._remember_last_context(session, intent='documentacao_document', search_context='documentacao', client_filial=documentacao_records[0].filial, client_cod_pdv=documentacao_records[0].cod_pdv, client_name=documentacao_records[0].nome)
            return self._with_post_result_navigation(sender, session, self._build_documentacao_pendente_response(documentacao_records, f'CPF/CNPJ {normalized_document}', scope_restricted=False), return_menu=return_menu, repeat_action=flow.REPEAT_SEARCH_DOCUMENT)
        if session.search_context == 'prazo_limite':
            prazo_limite_records = self.prazo_limite_service.search_by_document(document=normalized_document, allowed_sectors=None, allowed_gv_vdes=None, limit=50)
            if prazo_limite_records:
                self._remember_last_context(session, intent='prazo_limite_document', search_context='prazo_limite', client_filial=prazo_limite_records[0].filial, client_cod_pdv=prazo_limite_records[0].cod_pdv, client_name=prazo_limite_records[0].nome)
            return self._with_post_result_navigation(sender, session, self._build_prazo_limite_response(prazo_limite_records, f'CPF/CNPJ {normalized_document}', decision=decision, scope_restricted=False), return_menu=return_menu, repeat_action=flow.REPEAT_SEARCH_DOCUMENT)
        records = self.query_service.search_by_document(document=normalized_document, allowed_sectors=None, allowed_gv_vdes=None, limit=20)
        if records:
            self._remember_last_context(session, intent='cliente_document', search_context='cliente', client_filial=records[0].filial, client_cod_pdv=records[0].cod_pdv, client_name=records[0].nome_fantasia or records[0].razao_social)
        return self._with_post_result_navigation(sender, session, self._build_search_response(records, f'CPF/CNPJ {normalized_document}', decision=decision, scope_restricted=False), return_menu=return_menu, repeat_action=flow.REPEAT_SEARCH_DOCUMENT)

    def _apply_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        self._remember_last_context(session, intent='visit_day', search_context='cliente', visit_day=selected_visit_day)
        if self._uses_grouped_visit_flow(decision):
            visit_summaries = self._load_visit_day_seller_summaries(decision=decision, visit_day=selected_visit_day, limit=1000)
            if not visit_summaries:
                return flow.OutgoingMessage(text=f"Nao encontrei visitas para o dia '{flow._format_visit_day_label(selected_visit_day)}'.\nSe quiser tentar de novo, envie MENU.")
            gv_options = sorted({flow.normalize_stored_scope_value(summary.manager_code) or flow.normalize_stored_scope_value(summary.seller_code) for summary in visit_summaries if flow.normalize_stored_scope_value(summary.manager_code) or flow.normalize_stored_scope_value(summary.seller_code)}, key=flow._sort_scope_code)
            if len(gv_options) > 1:
                return self._open_grouped_visit_day_selection(sender=sender, session=session, selected_visit_day=selected_visit_day, visit_summaries=visit_summaries, gv_options=gv_options)
            if len(visit_summaries) == 1:
                selected_summary = visit_summaries[0]
                records = self.query_service.list_clients_by_visit_day_and_seller(visit_day=selected_visit_day, seller_code=selected_summary.seller_code, manager_code='' if selected_summary.manager_code == '-' else selected_summary.manager_code, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=80)
                financial_alerts, alerts_note = self._load_visit_day_financial_alerts(decision=decision, visit_day=selected_visit_day, seller_code=selected_summary.seller_code, manager_code='' if selected_summary.manager_code == '-' else selected_summary.manager_code)
                return self._with_post_result_navigation(sender, session, self._build_visit_day_seller_clients_response(visit_day=selected_visit_day, summary=selected_summary, records=records, decision=decision, financial_alerts=financial_alerts, alerts_note=alerts_note), return_menu='visit_day_menu')
            selected_gv = gv_options[0] if gv_options else ''
            session.step = 'awaiting_visit_seller_selection'
            session.selected_visit_day = selected_visit_day
            session.visit_group_summaries = tuple(visit_summaries)
            session.visit_seller_summaries = tuple(visit_summaries)
            session.finance_gv_options = tuple(gv_options)
            session.selected_visit_gv = selected_gv
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_grouped_visit_day_sector_menu(visit_day=selected_visit_day, gv_code=selected_gv, visit_summaries=visit_summaries)
        records = self.query_service.list_clients_by_visit_day(visit_day=selected_visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=80)
        financial_alerts, alerts_note = self._load_visit_day_financial_alerts(decision=decision, visit_day=selected_visit_day)
        return self._with_post_result_navigation(sender, session, self._build_visit_day_clients_response(selected_visit_day, records, decision, financial_alerts=financial_alerts, alerts_note=alerts_note), return_menu='visit_day_menu')

    def _open_grouped_visit_day_selection(self, *, sender: str, session: LookupSession, selected_visit_day: str, visit_summaries: list[VisitSellerSummary], gv_options: list[str]) -> OutgoingMessage:
        flow = _customer_flow_module()
        session.step = 'visit_select_gv'
        session.selected_visit_day = selected_visit_day
        session.visit_group_summaries = tuple(visit_summaries)
        session.visit_seller_summaries = ()
        session.finance_gv_options = tuple(gv_options)
        session.selected_visit_gv = ''
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_grouped_visit_day_gv_menu(visit_day=selected_visit_day, visit_summaries=visit_summaries, gv_options=gv_options)

    def _build_grouped_visit_day_gv_menu(self, *, visit_day: str, visit_summaries: list[VisitSellerSummary], gv_options: list[str], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
        grouped: dict[str, list[flow.VisitSellerSummary]] = {}
        for summary in visit_summaries:
            group_key = flow.normalize_stored_scope_value(summary.manager_code) or flow.normalize_stored_scope_value(summary.seller_code)
            grouped.setdefault(group_key, []).append(summary)
        lines = [f"Visitas de '{visit_day_label}'"]
        if invalid_selection:
            lines.insert(0, 'Nao entendi essa opcao.')
        lines.append(f'GVs na rota: {len(gv_options)} | Setores: {len(visit_summaries)} | Visitas: {sum((int(summary.visit_count or 0) for summary in visit_summaries))}')
        lines.append('')
        lines.append('Escolha o GV para ver os setores da rota.')
        return flow.OutgoingMessage(kind='menu', title='Visitas por GV', text='\n'.join(lines), footer='Na descricao de cada opcao eu mostro setores e visitas daquele GV. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'visitgv:pick:{index}', title=flow._format_visit_manager_summary_label(gv_code), description=f'{len(grouped.get(gv_code, []))} setor(es) | {sum((int(item.visit_count or 0) for item in grouped.get(gv_code, [])))} visita(s)', shortcut=str(index)) for index, gv_code in enumerate(gv_options, start=1))))

    def _build_grouped_visit_day_sector_menu(self, *, visit_day: str, gv_code: str, visit_summaries: list[VisitSellerSummary], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
        normalized_gv_code = flow.normalize_stored_scope_value(gv_code)
        grouped_items = [summary for summary in visit_summaries if (flow.normalize_stored_scope_value(summary.manager_code) or flow.normalize_stored_scope_value(summary.seller_code)) == normalized_gv_code]
        lines = [f"Visitas de '{visit_day_label}'"]
        if invalid_selection:
            lines.insert(0, 'Nao entendi essa opcao.')
        lines.append(flow._format_visit_manager_summary_label(normalized_gv_code))
        lines.append(f'Setores na rota: {len(grouped_items)} | Visitas: {sum((int(item.visit_count or 0) for item in grouped_items))}')
        lines.append('')
        lines.append('Escolha o setor para ver os clientes da rota.')
        return flow.OutgoingMessage(kind='menu', title='Visitas por Setor', text='\n'.join(lines), footer='Na descricao de cada opcao eu mostro as visitas do setor. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.VISIT_SELLER_PICK_PREFIX}{index}', title=flow._format_sector_scope_label(item.seller_code), description=f'{int(item.visit_count or 0)} visita(s)', shortcut=str(index)) for index, item in enumerate(grouped_items, start=1))))

    def _apply_inadimplencia_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(selected_visit_day)
        visit_day_token = flow._visit_day_token_from_label(selected_visit_day)
        self._remember_last_context(session, intent='inadimplencia_visit_day', search_context='inadimplencia', visit_day=visit_day_label)
        if self._can_use_finance_menu(decision):
            return self._open_finance_visit_risk_selection(sender=sender, session=session, decision=decision, visit_day_token=visit_day_token, visit_day_label=visit_day_label)
        if self._is_diretor_comercial(decision):
            return self._open_director_visit_risk_gv_selection(sender=sender, session=session, decision=decision, visit_day_token=visit_day_token, visit_day_label=visit_day_label)
        if self._is_gerente_vendas(decision):
            return self._open_manager_visit_risk_selection(sender=sender, session=session, decision=decision, visit_day_token=visit_day_token, visit_day_label=visit_day_label)
        return self._with_post_result_navigation(sender, session, self._build_seller_visit_day_risk_response(decision=decision, visit_day=selected_visit_day, visit_day_label=visit_day_label), return_menu='inadimplencia_visit_day_menu')

    def _apply_giro_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        self._remember_last_context(session, intent='giro_visit_day', search_context='giro', visit_day=selected_visit_day)
        summary = self._safe_giro_scope_summary_by_visit_day(decision, visit_day=selected_visit_day)
        if summary is None:
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Nao consegui montar a oportunidade de giro por dia agora.\nTente novamente em instantes.')
        try:
            records = self.query_service.list_clients_by_visit_day(visit_day=selected_visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=5000 if self._uses_grouped_giro_visit_flow(decision) or self._has_unrestricted_lookup_access(decision) else 200)
        except RuntimeError:
            records = []
        session.selected_visit_day = selected_visit_day
        if self._is_gerente_vendas(decision):
            return self._with_post_result_navigation(sender, session, self._build_giro_visit_day_response(visit_day=selected_visit_day, decision=decision, summary=summary, records=records), return_menu='giro_visit_day_menu')
        if self._uses_grouped_giro_visit_flow(decision):
            return self._open_grouped_giro_visit_selection(sender=sender, session=session, decision=decision, visit_day=selected_visit_day, summary=summary, records=records)
        response_builder = self._build_finance_giro_visit_day_response if self._has_unrestricted_lookup_access(decision) else self._build_giro_visit_day_response
        return self._with_post_result_navigation(sender, session, response_builder(visit_day=selected_visit_day, decision=decision, summary=summary, records=records), return_menu='giro_visit_day_menu')

    def _apply_documentacao_visit_day_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, selected_visit_day: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        self._remember_last_context(session, intent='documentacao_visit_day', search_context='documentacao', visit_day=selected_visit_day)
        try:
            summary = self.documentacao_pendente_service.get_scope_summary_by_visit_day(visit_day=selected_visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
            records = self.documentacao_pendente_service.list_pending_by_visit_day(visit_day=selected_visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=5000 if self._has_unrestricted_lookup_access(decision) or self._uses_grouped_visit_flow(decision) else 300)
        except RuntimeError:
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Nao consegui montar a documentacao pendente por dia agora.\nTente novamente em instantes.')
        session.selected_visit_day = selected_visit_day
        if records and (self._has_unrestricted_lookup_access(decision) or self._uses_grouped_visit_flow(decision)):
            return self._open_grouped_documentacao_visit_selection(sender=sender, session=session, visit_day=selected_visit_day, summary=summary, records=records)
        return self._with_post_result_navigation(sender, session, self._build_documentacao_visit_day_response(visit_day=selected_visit_day, decision=decision, summary=summary, records=records), return_menu='documentacao_visit_day_menu')

    def _open_grouped_documentacao_visit_selection(self, *, sender: str, session: LookupSession, visit_day: str, summary: DocumentacaoPendenteScopeSummary, records: list[DocumentacaoPendenteClientRecord]) -> OutgoingMessage:
        flow = _customer_flow_module()
        summary_text = self._build_documentacao_visit_day_header_text(visit_day=visit_day, summary=summary, records=records)
        sector_summaries = self._summarize_documentacao_visit_sectors(records)
        gv_options = sorted({flow.normalize_stored_scope_value(item.manager_code) or flow.normalize_stored_scope_value(item.seller_code) for item in sector_summaries if flow.normalize_stored_scope_value(item.manager_code) or flow.normalize_stored_scope_value(item.seller_code)}, key=flow._sort_scope_code)
        session.selected_visit_day = visit_day
        session.finance_gv_options = tuple(gv_options)
        session.documentacao_visit_sector_summaries = tuple(sector_summaries)
        session.documentacao_visit_records = tuple(records)
        session.documentacao_visit_summary_text = summary_text
        session.selected_documentacao_visit_gv = ''
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        if len(gv_options) == 1:
            session.step = 'documentacao_select_visit_sector'
            session.selected_documentacao_visit_gv = gv_options[0]
            self.sessions[sender] = session
            return self._build_grouped_documentacao_visit_sector_menu(gv_code=gv_options[0], sector_summaries=sector_summaries)
        session.step = 'documentacao_select_visit_gv'
        self.sessions[sender] = session
        return self._build_grouped_documentacao_visit_gv_menu(summary_text=summary_text, gv_options=gv_options, sector_summaries=sector_summaries)

    def _build_documentacao_visit_day_header_text(self, *, visit_day: str, summary: DocumentacaoPendenteScopeSummary, records: list[DocumentacaoPendenteClientRecord]) -> str:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
        lines = [f'Documentacao pendente em {visit_day_label}:', '']
        lines.append(f'Clientes monitorados: {summary.monitored_client_count}')
        lines.append(f'Clientes com pendencia: {summary.pending_client_count}')
        lines.append(f'Documentos faltando: {summary.pending_document_count}')
        lines.append(f'Resumo pendente: CS {summary.contrato_social_pendentes} | CPF {summary.cpf_pendentes} | RG {summary.rg_pendentes} | CR {summary.comprovante_residencia_pendentes} | FAC {summary.fachada_pendentes} | FC {summary.ficha_cadastro_pendentes}')
        lines.append(f"Documentacao atualizada em: {summary.planilha_atualizada_em or '-'}")
        if records:
            lines.append('')
            lines.append(f'Clientes com pendencia: {len(records)} | Documentos faltando: {sum((int(record.pending_count or 0) for record in records))}')
        return '\n'.join(lines)

    def _summarize_documentacao_visit_sectors(self, records: list[DocumentacaoPendenteClientRecord]) -> list[DocumentacaoVisitSectorSummary]:
        flow = _customer_flow_module()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for record in records:
            seller_code = flow.normalize_stored_scope_value(record.seller_code)
            manager_code = flow.normalize_stored_scope_value(record.manager_code)
            key = (manager_code, seller_code)
            bucket = grouped.setdefault(key, {'manager_code': manager_code, 'seller_code': seller_code, 'client_count': 0, 'pending_document_count': 0})
            bucket['client_count'] += 1
            bucket['pending_document_count'] += int(record.pending_count or 0)
        return [flow.DocumentacaoVisitSectorSummary(seller_code=item['seller_code'], manager_code=item['manager_code'], client_count=int(item['client_count']), pending_document_count=int(item['pending_document_count'])) for item in sorted(grouped.values(), key=lambda item: (flow._sort_scope_code(item['manager_code'] or item['seller_code']), flow._sort_scope_code(item['seller_code'])))]

    def _build_grouped_documentacao_visit_gv_menu(self, *, summary_text: str, gv_options: list[str], sector_summaries: list[DocumentacaoVisitSectorSummary], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = [summary_text, '']
        if invalid_selection:
            lines.insert(0, 'Nao entendi essa opcao.')
            lines.insert(1, '')
        grouped: dict[str, list[flow.DocumentacaoVisitSectorSummary]] = {}
        for summary_item in sector_summaries:
            group_key = flow.normalize_stored_scope_value(summary_item.manager_code) or flow.normalize_stored_scope_value(summary_item.seller_code)
            grouped.setdefault(group_key, []).append(summary_item)
        lines.append(f'GVs com pendencia documental: {len(gv_options)}')
        lines.append('')
        lines.append('Escolha o GV para ver os setores com pendencia.')
        return flow.OutgoingMessage(kind='menu', title='Documentacao por Dia', text='\n'.join(lines), footer='Na descricao de cada opcao eu mostro setores, clientes e documentos faltando. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.DOCUMENTACAO_VISIT_GV_PICK_PREFIX}{index}', title=flow._format_visit_manager_summary_label(gv_code), description=f'{len(grouped.get(gv_code, []))} setor(es) | {sum((item.client_count for item in grouped.get(gv_code, [])))} cliente(s) | {sum((item.pending_document_count for item in grouped.get(gv_code, [])))} doc(s)', shortcut=str(index)) for index, gv_code in enumerate(gv_options, start=1))))

    def _build_grouped_documentacao_visit_sector_menu(self, *, gv_code: str, sector_summaries: list[DocumentacaoVisitSectorSummary], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        normalized_gv_code = flow.normalize_stored_scope_value(gv_code)
        grouped_items = [item for item in sector_summaries if (flow.normalize_stored_scope_value(item.manager_code) or flow.normalize_stored_scope_value(item.seller_code)) == normalized_gv_code]
        lines = []
        if invalid_selection:
            lines.append('Nao entendi essa opcao.')
            lines.append('')
        lines.append(flow._format_visit_manager_summary_label(normalized_gv_code))
        lines.append(f'Setores com pendencia: {len(grouped_items)} | Clientes com pendencia: {sum((item.client_count for item in grouped_items))} | Documentos faltando: {sum((item.pending_document_count for item in grouped_items))}')
        lines.append('')
        lines.append('Escolha o setor para ver os clientes com documentacao pendente.')
        return flow.OutgoingMessage(kind='menu', title='Documentacao por Setor', text='\n'.join(lines), footer='Na descricao de cada opcao eu mostro clientes e documentos faltando do setor. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.DOCUMENTACAO_VISIT_SELLER_PICK_PREFIX}{index}', title=flow._format_sector_scope_label(item.seller_code), description=f'{item.client_count} cliente(s) | {item.pending_document_count} doc(s)', shortcut=str(index)) for index, item in enumerate(grouped_items, start=1))))

    def _build_grouped_documentacao_visit_sector_response(self, *, visit_day: str, sector_summary: DocumentacaoVisitSectorSummary, records: list[DocumentacaoPendenteClientRecord]) -> OutgoingMessage:
        flow = _customer_flow_module()
        normalized_seller_code = flow.normalize_stored_scope_value(sector_summary.seller_code)
        filtered_records = sorted([record for record in records if flow.normalize_stored_scope_value(record.seller_code) == normalized_seller_code], key=lambda item: (flow._sort_numeric_text(item.cod_pdv), str(item.nome or '').lower()))
        visit_day_label = flow._format_visit_day_label(visit_day)
        lines = [f'Documentacao pendente em {visit_day_label}:', '', f"{flow._format_visit_manager_summary_label(sector_summary.manager_code, sector_summary.seller_code)} | Setor {(flow.split_scope_pair(sector_summary.seller_code) or ('', '-'))[1]}", f'Clientes com pendencia: {len(filtered_records)} | Documentos faltando: {sum((int(record.pending_count or 0) for record in filtered_records))}', '', 'Clientes com documentacao pendente:']
        if not filtered_records:
            lines.append('Nenhum cliente com documentacao pendente nesse setor.')
            return flow.OutgoingMessage(text='\n'.join(lines))
        for index, record in enumerate(filtered_records, start=1):
            lines.append(f"{index}. Codigo {record.cod_pdv} | {record.nome or '-'} | Pendencias {record.pending_count} | Falta: {flow._format_documentacao_pending_docs(record.pending_docs)}")
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_giro_visit_day_header_text(self, *, visit_day: str, summary: GiroScopeSummary, opportunities: list[GiroVisitOpportunity], giro_updated_at: str) -> str:
        flow = _customer_flow_module()
        return self.finance_flow._build_giro_visit_day_header_text(visit_day=visit_day, summary=summary, opportunities=opportunities, giro_updated_at=giro_updated_at)

    def _collect_giro_visit_day_opportunities(self, *, visit_day: str, decision: AccessDecision, records: list[DClienteRecord]) -> tuple[list[GiroVisitOpportunity], str]:
        flow = _customer_flow_module()
        giro_summaries, giro_updated_at = self._build_visit_day_giro_summaries(decision, records)
        try:
            seller_summaries = self.query_service.list_visit_day_seller_summaries(visit_day=visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=1000)
        except RuntimeError:
            seller_summaries = []
        manager_by_seller = {flow.normalize_stored_scope_value(summary_item.seller_code): flow.normalize_stored_scope_value(summary_item.manager_code) for summary_item in seller_summaries if flow.normalize_stored_scope_value(summary_item.seller_code)}
        opportunities: list[flow.GiroVisitOpportunity] = []
        for record in records:
            client_summary = giro_summaries.get((flow._normalize_filial(record.filial), flow._normalize_cod_pdv(record.cod_pdv)))
            if client_summary is None:
                continue
            setor_code, total_caixas, gap_caixas, gap_detail = client_summary
            if not flow._is_positive_quantity(total_caixas) or not flow._is_positive_quantity(gap_caixas):
                continue
            seller_code = flow.normalize_stored_scope_value(f'{flow._normalize_filial(record.filial)}_{setor_code}')
            opportunities.append(flow.GiroVisitOpportunity(manager_code=manager_by_seller.get(seller_code, ''), seller_code=seller_code, setor_code=setor_code or '-', cod_pdv=str(record.cod_pdv or '').strip(), client_name=record.nome_fantasia or record.razao_social or '-', total_caixas=total_caixas, gap_caixas=gap_caixas, gap_detail=gap_detail))
        opportunities.sort(key=lambda item: (flow._sort_scope_code(item.manager_code or item.seller_code), flow._sort_scope_code(item.seller_code), flow._sort_numeric_text(item.cod_pdv), str(item.client_name or '').lower()))
        return (opportunities, giro_updated_at)

    def _summarize_giro_visit_sectors(self, opportunities: list[GiroVisitOpportunity]) -> list[GiroVisitSectorSummary]:
        flow = _customer_flow_module()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for item in opportunities:
            key = (flow.normalize_stored_scope_value(item.manager_code), flow.normalize_stored_scope_value(item.seller_code))
            bucket = grouped.setdefault(key, {'seller_code': flow.normalize_stored_scope_value(item.seller_code), 'manager_code': flow.normalize_stored_scope_value(item.manager_code), 'client_count': 0, 'caixas': [], 'gaps': []})
            bucket['client_count'] += 1
            bucket['caixas'].append(item.total_caixas)
            bucket['gaps'].append(item.gap_caixas)
        return [flow.GiroVisitSectorSummary(seller_code=str(bucket['seller_code']), manager_code=str(bucket['manager_code']), client_count=int(bucket['client_count']), total_caixas=flow._sum_formatted_amounts(*bucket['caixas']), total_gap=flow._sum_formatted_amounts(*bucket['gaps'])) for _key, bucket in sorted(grouped.items(), key=lambda item: (flow._sort_scope_code(item[0][0] or item[0][1]), flow._sort_scope_code(item[0][1])))]

    def _open_grouped_giro_visit_selection(self, *, sender: str, session: LookupSession, decision: AccessDecision, visit_day: str, summary: GiroScopeSummary, records: list[DClienteRecord]) -> OutgoingMessage:
        flow = _customer_flow_module()
        opportunities, giro_updated_at = self._collect_giro_visit_day_opportunities(visit_day=visit_day, decision=decision, records=records)
        summary_text = self._build_giro_visit_day_header_text(visit_day=visit_day, summary=summary, opportunities=opportunities, giro_updated_at=giro_updated_at)
        if not opportunities:
            return self._with_post_result_navigation(sender, session, flow.OutgoingMessage(text=f'{summary_text}\n\nNenhum cliente com oportunidade de giro nesse dia.'), return_menu='giro_visit_day_menu')
        sector_summaries = self._summarize_giro_visit_sectors(opportunities)
        gv_options = sorted({flow.normalize_stored_scope_value(summary_item.manager_code) or flow.normalize_stored_scope_value(summary_item.seller_code) for summary_item in sector_summaries if flow.normalize_stored_scope_value(summary_item.manager_code) or flow.normalize_stored_scope_value(summary_item.seller_code)}, key=flow._sort_scope_code)
        session.selected_visit_day = visit_day
        session.finance_gv_options = tuple(gv_options)
        session.giro_visit_sector_summaries = tuple(sector_summaries)
        session.giro_visit_summary_text = summary_text
        session.selected_giro_visit_gv = ''
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        if len(gv_options) == 1:
            session.step = 'giro_select_visit_sector'
            session.selected_giro_visit_gv = gv_options[0]
            self.sessions[sender] = session
            return self._build_grouped_giro_visit_sector_menu(summary_text=summary_text, gv_code=gv_options[0], sector_summaries=sector_summaries)
        session.step = 'giro_select_visit_gv'
        self.sessions[sender] = session
        return self._build_grouped_giro_visit_gv_menu(summary_text=summary_text, gv_options=gv_options, sector_summaries=sector_summaries)

    def _build_grouped_giro_visit_gv_menu(self, *, summary_text: str, gv_options: list[str], sector_summaries: list[GiroVisitSectorSummary], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = [summary_text, '']
        if invalid_selection:
            lines.insert(0, 'Nao entendi essa opcao.')
            lines.insert(1, '')
        grouped: dict[str, list[flow.GiroVisitSectorSummary]] = {}
        for summary in sector_summaries:
            group_key = flow.normalize_stored_scope_value(summary.manager_code) or flow.normalize_stored_scope_value(summary.seller_code)
            grouped.setdefault(group_key, []).append(summary)
        lines.append(f'GVs com oportunidade: {len(gv_options)}')
        lines.append('')
        lines.append('Escolha o GV para ver os setores com oportunidade.')
        return flow.OutgoingMessage(kind='menu', title='Giro por Dia', text='\n'.join(lines), footer='Na descricao de cada opcao eu mostro setores, clientes, caixas e faltam daquele GV. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.GIRO_VISIT_GV_PICK_PREFIX}{index}', title=flow._format_visit_manager_summary_label(gv_code), description=f"{len(grouped.get(gv_code, []))} setor(es) | {sum((item.client_count for item in grouped.get(gv_code, [])))} cliente(s) | Caixas {(flow._sum_formatted_amounts(*(item.total_caixas for item in grouped.get(gv_code, []))) if grouped.get(gv_code, []) else '0')} | Faltam {(flow._sum_formatted_amounts(*(item.total_gap for item in grouped.get(gv_code, []))) if grouped.get(gv_code, []) else '0')}", shortcut=str(index)) for index, gv_code in enumerate(gv_options, start=1))))

    def _build_grouped_giro_visit_sector_menu(self, *, summary_text: str, gv_code: str, sector_summaries: list[GiroVisitSectorSummary], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        normalized_gv_code = flow.normalize_stored_scope_value(gv_code)
        grouped_items = [item for item in sector_summaries if (flow.normalize_stored_scope_value(item.manager_code) or flow.normalize_stored_scope_value(item.seller_code)) == normalized_gv_code]
        lines = []
        if invalid_selection:
            lines.append('Nao entendi essa opcao.')
            lines.append('')
        lines.append(flow._format_visit_manager_summary_label(normalized_gv_code))
        lines.append(f"Setores com oportunidade: {len(grouped_items)} | Clientes com oportunidade: {sum((item.client_count for item in grouped_items))} | Caixas {(flow._sum_formatted_amounts(*(item.total_caixas for item in grouped_items)) if grouped_items else '0')} | Faltam {(flow._sum_formatted_amounts(*(item.total_gap for item in grouped_items)) if grouped_items else '0')}")
        lines.append('')
        lines.append('Escolha o setor para ver os clientes com oportunidade.')
        return flow.OutgoingMessage(kind='menu', title='Giro por Setor', text='\n'.join(lines), footer='Na descricao de cada opcao eu mostro clientes, caixas e faltam do setor. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.GIRO_VISIT_SELLER_PICK_PREFIX}{index}', title=flow._format_sector_scope_label(item.seller_code), description=f'{item.client_count} cliente(s) | Caixas {item.total_caixas} | Faltam {item.total_gap}', shortcut=str(index)) for index, item in enumerate(grouped_items, start=1))))

    def _build_grouped_giro_visit_sector_response(self, *, decision: AccessDecision, visit_day: str, sector_summary: GiroVisitSectorSummary) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            records = self.query_service.list_clients_by_visit_day_and_seller(visit_day=visit_day, seller_code=sector_summary.seller_code, manager_code=sector_summary.manager_code, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=5000)
        except RuntimeError:
            return flow.OutgoingMessage(text='Nao consegui abrir os clientes com oportunidade desse setor agora.\nTente novamente em instantes.')
        opportunities, giro_updated_at = self._collect_giro_visit_day_opportunities(visit_day=visit_day, decision=decision, records=records)
        filtered_opportunities = [item for item in opportunities if flow.normalize_stored_scope_value(item.seller_code) == flow.normalize_stored_scope_value(sector_summary.seller_code)]
        visit_day_label = flow._format_visit_day_label(visit_day)
        lines = [f'Oportunidade de giro em {visit_day_label}:', 'Tipo: Giro de Vasilhame', '', f"{flow._format_visit_manager_summary_label(sector_summary.manager_code, sector_summary.seller_code)} | Setor {(flow.split_scope_pair(sector_summary.seller_code) or ('', '-'))[1]}", f"Clientes com oportunidade: {len(filtered_opportunities)} | Caixas com giro: {(flow._sum_formatted_amounts(*(item.total_caixas for item in filtered_opportunities)) if filtered_opportunities else '0')} | Faltam: {(flow._sum_formatted_amounts(*(item.gap_caixas for item in filtered_opportunities)) if filtered_opportunities else '0')}"]
        if giro_updated_at:
            lines.append(f'Giro atualizado em: {giro_updated_at}')
        lines.append('')
        lines.append('Clientes com oportunidade de giro:')
        if not filtered_opportunities:
            lines.append('Nenhum cliente com oportunidade de giro nesse setor.')
            return flow.OutgoingMessage(text='\n'.join(lines))
        for index, item in enumerate(filtered_opportunities, start=1):
            flow._append_giro_client_block(lines, index=index, client_name=item.client_name, cod_pdv=item.cod_pdv, total_caixas=item.total_caixas, gap_caixas=item.gap_caixas, gap_detail=item.gap_detail)
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _open_inadimplencia_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
        if access_error is not None:
            self._reset_session(sender)
            return access_error
        try:
            raw_visit_days = self.query_service.list_visit_days(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
        except RuntimeError:
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Nao consegui abrir os dias da inadimplencia agora.\nTente novamente em instantes.')
        visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Nao encontrei dias de visita disponiveis para consultar a inadimplencia.\nSe quiser fazer outra consulta, envie MENU.')
        self._prepare_search_session(session, search_context='inadimplencia')
        session.step = 'awaiting_inadimplencia_visit_day_selection'
        session.visit_day_options = tuple(visit_days)
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        if not requested_day_label and len(visit_days) == 1:
            return self._apply_inadimplencia_visit_day_selection(sender=sender, session=session, decision=decision, selected_visit_day=visit_days[0])
        if requested_day_label:
            selected_visit_day = flow._match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_inadimplencia_visit_day_selection(sender=sender, session=session, decision=decision, selected_visit_day=selected_visit_day)
        return self._build_inadimplencia_visit_day_menu(visit_days=visit_days)

    def _open_giro_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        return self.finance_flow._open_giro_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=requested_day_label)

    def _open_documentacao_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        access_error = self._ensure_scoped_lookup_access(decision, search_context='documentacao')
        if access_error is not None:
            self.sessions[sender] = session
            return access_error
        try:
            raw_visit_days = self.query_service.list_visit_days(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
        except RuntimeError:
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Nao consegui carregar os dias de visita da documentacao agora.\nTente novamente em instantes.')
        visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Nao encontrei dias de visita disponiveis para consultar a documentacao pendente.\nSe quiser fazer outra consulta, envie MENU.')
        self._prepare_search_session(session, search_context='documentacao')
        session.step = 'awaiting_documentacao_visit_day_selection'
        session.visit_day_options = tuple(visit_days)
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        if not requested_day_label and len(visit_days) == 1:
            return self._apply_documentacao_visit_day_selection(sender=sender, session=session, decision=decision, selected_visit_day=visit_days[0])
        if requested_day_label:
            selected_visit_day = flow._match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_documentacao_visit_day_selection(sender=sender, session=session, decision=decision, selected_visit_day=selected_visit_day)
        return self._build_documentacao_visit_day_menu(visit_days=visit_days)

    def _open_visit_day_conversation(self, sender: str, session: LookupSession, decision: AccessDecision, *, requested_day_label: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
        if access_error is not None:
            self._reset_session(sender)
            return access_error
        raw_visit_days = self.query_service.list_visit_days(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
        visit_days = flow._normalize_visit_day_menu_values(raw_visit_days)
        if not visit_days:
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Nao encontrei dias de visita disponiveis para voce no momento.\nSe quiser fazer outra consulta, envie MENU.')
        self._prepare_search_session(session, search_context=session.search_context or 'cliente')
        session.step = 'awaiting_visit_day_selection'
        session.visit_day_options = tuple(visit_days)
        self._remember_last_context(session, intent='visit_day', search_context='cliente', visit_day=requested_day_label or session.last_visit_day or flow._current_visit_day_label())
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        if not requested_day_label and len(visit_days) == 1:
            return self._apply_visit_day_selection(sender=sender, session=session, decision=decision, selected_visit_day=visit_days[0])
        if requested_day_label:
            selected_visit_day = flow._match_requested_visit_day(requested_day_label, tuple(visit_days))
            if selected_visit_day:
                return self._apply_visit_day_selection(sender=sender, session=session, decision=decision, selected_visit_day=selected_visit_day)
        return self._build_visit_day_menu(decision=decision, visit_days=visit_days)

    def _open_scope_inadimplencia_list(self, sender: str, session: LookupSession, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
        if access_error is not None:
            self._reset_session(sender)
            return access_error
        self._remember_last_context(session, intent='inadimplencia_list', search_context='inadimplencia')
        return self._open_inadimplencia_summary_selection(sender=sender, session=session, decision=decision, order_by='total_pendente', header_text=f'Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.', empty_text='No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\nSe quiser tentar outra consulta, envie MENU.', page=1, page_size=flow.INADIMPLENCIA_PAGE_SIZE, list_context=flow.INADIMPLENCIA_CONTEXT_SCOPE_BASE)

    def _build_client_clarification_options(self, session: LookupSession, decision: AccessDecision) -> list[InteractiveOption]:
        flow = _customer_flow_module()
        options: list[flow.InteractiveOption] = []
        if self._has_recent_last_context(session) and session.last_client_filial and session.last_client_cod_pdv and self._has_area_access(decision, 'cliente'):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_LAST_CLIENT_RECORD, title=f"Reabrir {session.last_client_name or 'o ultimo cliente'}", description=f'Revenda {session.last_client_filial} | NB {session.last_client_cod_pdv}'))
        if self._has_area_access(decision, 'cliente'):
            options.append(flow.InteractiveOption(option_id=flow.MENU_SEARCH, title='Buscar Cadastro', description='Consultar os dados do cliente'))
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_GIRO_CLIENT, title='Giro por Cliente', description='Buscar giro por nome, CPF ou NB'))
        if self._has_area_access(decision, 'inadimplencia'):
            options.append(flow.InteractiveOption(option_id=flow.MENU_INADIMPLENCIA, title='Inadimplencia do Cliente', description='Consultar titulos em aberto'))
        if self._has_area_access(decision, 'comodato'):
            options.append(flow.InteractiveOption(option_id=flow.MENU_COMODATOS, title='Comodatos do Cliente', description='Consultar pendencias de comodato'))
        return options

    def _build_list_clarification_options(self, decision: AccessDecision) -> list[InteractiveOption]:
        flow = _customer_flow_module()
        options: list[flow.InteractiveOption] = []
        if self._has_area_access(decision, 'inadimplencia'):
            options.append(flow.InteractiveOption(option_id=flow.CLARIFY_SCOPE_INADIMPLENCIA_LIST, title='Lista de Inadimplentes', description='Ver os clientes inadimplentes da sua base'))
        if self._can_use_visit_menu(decision) and self._has_area_access(decision, 'cliente'):
            options.append(flow.InteractiveOption(option_id=flow.MENU_VISIT_DAY, title='Visitas do Dia', description='Ver a lista de visitas programadas'))
        return options

    def _run_scoped_inadimplencia_due_bucket(self, sender: str, session: LookupSession, decision: AccessDecision, *, due_bucket: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
        if access_error is not None:
            self.sessions[sender] = session
            return access_error
        scope_label = self._inadimplencia_scope_label(decision)
        bucket_meta = {'in_two_days': {'header': f'Esses sao os clientes que vencem em 2 dias da {scope_label}.', 'empty': f'Nao encontrei clientes com vencimento em 2 dias na {scope_label}.\nEscolha outra faixa ou envie MENU.'}, 'tomorrow': {'header': f'Esses sao os clientes que vencem amanha da {scope_label}.', 'empty': f'Nao encontrei clientes com vencimento para amanha na {scope_label}.\nEscolha outra faixa ou envie MENU.'}}[due_bucket]
        return self._open_inadimplencia_summary_selection(sender=sender, session=session, decision=decision, order_by='total_pendente', due_bucket=due_bucket, header_text=bucket_meta['header'], empty_text=bucket_meta['empty'], list_context=flow.INADIMPLENCIA_CONTEXT_SCOPE_BASE)

    def _maybe_handle_search_mode_conversation(self, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        request = flow._parse_hybrid_search_request(text=text, normalized_text=normalized, search_context=session.search_context, allow_contextless_query=True)
        if request is None:
            return None
        if request.open_base_list:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='inadimplencia')
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            return self._open_inadimplencia_summary_selection(sender=sender, session=session, decision=decision, order_by='total_pendente', header_text=f'Esses sao os clientes inadimplentes da {self._inadimplencia_scope_label(decision)}.', empty_text='No momento, nao encontrei clientes inadimplentes dentro do seu acesso.\nSe quiser tentar outra consulta, envie MENU.', page=1, page_size=flow.INADIMPLENCIA_PAGE_SIZE, list_context=flow.INADIMPLENCIA_CONTEXT_SCOPE_BASE)
        if request.open_giro_zero_base_list:
            access_error = self._ensure_scoped_lookup_access(decision, search_context='giro')
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
            self._remember_last_context(session, intent='giro_zero_base', search_context='giro')
            return self._with_post_result_navigation(sender, session, self._build_giro_zero_base_response(decision), return_menu='search_menu')
        if request.search_mode in {'registration', 'fantasia'} or request.query_text:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
        elif request.search_mode == 'document' and session.search_context in {'cliente', 'giro', 'inadimplencia', 'comodato', 'documentacao', 'prazo_limite'}:
            access_error = self._ensure_scoped_lookup_access(decision, search_context=session.search_context)
            if access_error is not None:
                self.sessions[sender] = session
                return access_error
        if request.filial and request.cod_pdv:
            return self._run_repeatable_registration_lookup(sender=sender, session=session, decision=decision, search_context=session.search_context, filial=request.filial, cod_pdv=request.cod_pdv)
        if request.document:
            return self._run_document_lookup(sender=sender, session=session, decision=decision, document=request.document)
        if request.visit_day_label:
            if session.search_context == 'giro':
                return self._open_giro_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=request.visit_day_label)
            if session.search_context == 'inadimplencia':
                return self._open_inadimplencia_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=request.visit_day_label)
            if session.search_context == 'documentacao':
                return self._open_documentacao_visit_day_conversation(sender=sender, session=session, decision=decision, requested_day_label=request.visit_day_label)
        if request.query_text:
            return self._run_name_search(sender=sender, session=session, decision=decision, query_text=request.query_text)
        if request.search_mode:
            return self._activate_search_mode(sender=sender, session=session, search_mode=request.search_mode)
        return None

    def _open_inadimplencia_summary_selection(self, sender: str, session: LookupSession, decision: AccessDecision, *, order_by: str, header_text: str, empty_text: str, due_bucket: str | None=None, page: int=1, page_size: int | None=None, list_context: str='', known_total_clients: int | None=None) -> OutgoingMessage:
        flow = _customer_flow_module()
        page_size = flow.INADIMPLENCIA_PAGE_SIZE if page_size is None else page_size
        total_clients = max(int(known_total_clients), 0) if known_total_clients is not None else self.inadimplencia_service.count_clients_in_scope(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), due_bucket=due_bucket)
        current_page = max(int(page), 1)
        page_limit = max(int(page_size), 1)
        summaries = self.inadimplencia_service.list_client_summaries_in_scope(allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=page_limit, offset=(current_page - 1) * page_limit, order_by=order_by, due_bucket=due_bucket)
        if not summaries:
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(text=empty_text)
        if len(summaries) == 1 and total_clients <= 1:
            summary = summaries[0]
            return_menu = 'search_menu'
            if self._can_use_finance_menu(decision):
                return_menu = 'finance_menu'
            elif self._is_gerente_vendas(decision):
                return_menu = 'manager_summary'
            elif self._is_diretor_comercial(decision):
                return_menu = 'director_summary'
            self._remember_last_context(session, intent='inadimplencia_client', search_context='inadimplencia', query_text=header_text, client_filial=summary.filial, client_cod_pdv=summary.cod_pdv, client_name=summary.nome)
            records = self.inadimplencia_service.search_by_registration(filial=summary.filial, cod_pdv=summary.cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
            return self._with_post_result_navigation(sender, session, self._build_inadimplencia_response(records, f'cliente {summary.nome} | revenda {summary.filial} | NB {summary.cod_pdv}', compact=list_context == flow.INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS), return_menu=return_menu)
        session.step = 'awaiting_inadimplencia_client_selection'
        session.search_context = 'inadimplencia'
        session.fantasia_query = flow._encode_inadimplencia_header(header_text)
        session.inadimplencia_client_summaries = tuple(summaries)
        session.inadimplencia_total_available = total_clients
        session.inadimplencia_list_context = list_context
        session.inadimplencia_page = current_page
        session.inadimplencia_page_size = page_limit
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_inadimplencia_client_menu(query_text=session.fantasia_query, summaries=summaries, total_available=total_clients, page=current_page if list_context else None, page_size=page_limit, list_context=list_context)

    def _uses_grouped_visit_flow(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._is_financeiro(decision) or self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)

    def _uses_grouped_giro_visit_flow(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._has_unrestricted_lookup_access(decision) or self._is_financeiro(decision) or self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)

    def _ensure_search_context_ready(self, search_context: str, decision: AccessDecision | None=None) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        if decision is not None:
            if self._is_armazem(decision) and search_context != 'cliente':
                return flow.OutgoingMessage(
                    text=(
                        "Esse acesso de armazem esta liberado apenas para buscar clientes e consultar estoque.\n"
                        "Use cliente, estoque ou armazem."
                    )
                )
            area_map = {'comodato': 'comodato', 'inadimplencia': 'inadimplencia', 'giro': 'cliente', 'documentacao': 'cliente', 'prazo_limite': 'cliente'}
            area = area_map.get(search_context, search_context)
            area_decision = self._decision_for_area(decision, area)
            if not area_decision.allowed:
                return self._build_area_access_denied_response(area)
        if search_context == 'inadimplencia':
            status = self.inadimplencia_service.status()
            if not status['ready']:
                return flow.OutgoingMessage(text='No momento, eu nao consegui acessar a base de inadimplencia.\nTente novamente daqui a pouco.')
            return None
        if search_context == 'comodato':
            status = self.comodatos_service.status()
            if not status['ready']:
                return flow.OutgoingMessage(text='No momento, eu nao consegui acessar a base de comodatos.\nTente novamente daqui a pouco.')
            return None
        if search_context == 'giro':
            status = self.giro_service.status()
            if not status['ready']:
                return flow.OutgoingMessage(text='No momento, eu nao consegui acessar a base de giro.\nTente novamente daqui a pouco.')
            return None
        if search_context == 'documentacao':
            status = self.documentacao_pendente_service.status()
            if not status['ready']:
                last_error = str(status.get('last_error') or '').strip().lower()
                if 'ainda nao foi importada' in last_error:
                    return flow.OutgoingMessage(text='A base de documentacao pendente ainda nao foi importada no painel admin.\nAssim que o arquivo for validado e importado, eu consigo consultar normalmente.')
                return flow.OutgoingMessage(text='No momento, eu nao consegui acessar a base de documentacao pendente.\nTente novamente daqui a pouco.')
            return None
        if search_context == 'prazo_limite':
            status = self.prazo_limite_service.status()
            if not status['ready']:
                last_error = str(status.get('last_error') or '').strip().lower()
                if 'ainda nao foi importada' in last_error:
                    return flow.OutgoingMessage(text='A base de prazo e limite ainda nao foi importada no painel admin.\nAssim que o arquivo for validado e importado, eu consigo consultar normalmente.')
                return flow.OutgoingMessage(text='No momento, eu nao consegui acessar a base de prazo e limite.\nTente novamente daqui a pouco.')
            return None
        status = self.query_service.status()
        if not status['ready']:
            return flow.OutgoingMessage(text='No momento, eu nao consegui acessar a base de clientes.\nTente novamente daqui a pouco.')
        return None

    def _build_search_menu(self, search_context: str, decision: AccessDecision | None=None, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        context_label_map = {'cliente': 'o cliente', 'inadimplencia': 'a inadimplencia', 'comodato': 'os comodatos pendentes', 'giro': 'o giro', 'documentacao': 'a documentacao pendente', 'prazo_limite': 'prazo e limite'}
        context_label = context_label_map.get(search_context, 'a consulta')
        if search_context == 'inadimplencia' and decision is not None and self._is_vendedor(decision):
            context_label = 'a cobranca da carteira'
        if search_context == 'inadimplencia' and decision is not None and self._is_gerente_vendas(decision):
            context_label = 'a cobranca da gerencia'
        registration_title = 'Filial e codigo' if search_context == 'cliente' else 'Filial e NB'
        registration_description = 'Voce pode mandar filial e codigo juntos' if search_context == 'cliente' else 'Voce pode mandar filial e NB juntos'
        text = f'Como voce quer procurar {context_label}?'
        if invalid_selection:
            text = flow._invalid_option_text(f'Me diga como voce quer procurar {context_label}.')
        if search_context == 'inadimplencia':
            base_summary = self._build_inadimplencia_base_summary(decision)
            if base_summary:
                text = f'{base_summary}\n\n{text}'
        options = [flow.InteractiveOption(option_id=flow.SEARCH_BY_REGISTRATION, title=registration_title, description=registration_description, shortcut='1'), flow.InteractiveOption(option_id=flow.SEARCH_BY_FANTASIA, title='Nome do cliente', description='Buscar por parte do nome', shortcut='2'), flow.InteractiveOption(option_id=flow.SEARCH_BY_DOCUMENT, title='CPF ou CNPJ', description='Buscar pelo documento', shortcut='3')]
        if search_context == 'inadimplencia':
            next_shortcut = 4
            if decision is not None and self._can_access_sectors(decision):
                options.append(flow.InteractiveOption(option_id=flow.SEARCH_BY_VISIT_DAY, title='Risco por dia', description='Consultar a rota com risco financeiro pelo dia', shortcut=str(next_shortcut)))
                next_shortcut += 1
            if decision is not None and self._is_vendedor(decision):
                options.append(flow.InteractiveOption(option_id=flow.FINANCE_DUE_TOMORROW, title='Vence amanha', description='Clientes com vencimento para amanha', shortcut=str(next_shortcut)))
                next_shortcut += 1
                options.append(flow.InteractiveOption(option_id=flow.FINANCE_DUE_IN_TWO_DAYS, title='Vence em 2 dias', description='Clientes que vencem em 2 dias', shortcut=str(next_shortcut)))
                next_shortcut += 1
            options.append(flow.InteractiveOption(option_id=flow.SEARCH_BY_INADIMPLENTES_BASE, title='Ver inadimplentes', description='Mostrar os clientes da sua base', shortcut=str(next_shortcut)))
        elif search_context == 'giro' and decision is not None and self._can_access_sectors(decision):
            options.append(flow.InteractiveOption(option_id=flow.SEARCH_BY_VISIT_DAY, title='Giro por dia', description='Resumo de vasilhame e clientes com caixa na mesma mensagem', shortcut='4'))
            options.append(flow.InteractiveOption(option_id=flow.SEARCH_BY_GIRO_ZERO_BASE, title='Giro Zero da Base', description='Clientes com giro zero', shortcut='5'))
        elif search_context == 'documentacao' and decision is not None and self._can_access_sectors(decision):
            options.append(flow.InteractiveOption(option_id=flow.SEARCH_BY_VISIT_DAY, title='Pendencia por dia', description='Resumo documental e clientes pendentes da rota', shortcut='4'))
        footer = 'Se quiser voltar ao inicio, envie A, ANT ou MENU.'
        if search_context == 'cliente':
            footer = 'Atalho rapido: envie filial + codigo juntos, por exemplo: 3 6643. Se quiser voltar ao inicio, envie A, ANT ou MENU.'
        if search_context == 'inadimplencia' and decision is not None and self._can_access_sectors(decision):
            footer = 'Voce pode buscar um cliente ou pedir um dia, por exemplo: inad segunda ou inad santa maria. Se quiser voltar ao inicio, envie A, ANT ou MENU.'
        if search_context == 'giro' and decision is not None and self._can_access_sectors(decision):
            text = f'{text}\n\nObs.: nesse menu, giro significa giro de vasilhame.'
            footer = 'Voce pode buscar um cliente, pedir um dia ou abrir giro zero da base. Exemplos: giro segunda, giro zero ou giro espeto do paulo. Se quiser voltar ao inicio, envie A, ANT ou MENU.'
        if search_context == 'documentacao' and decision is not None and self._can_access_sectors(decision):
            footer = 'Voce pode buscar um cliente ou pedir um dia, por exemplo: documentacao segunda ou documentacao bar central. Se quiser voltar ao inicio, envie A, ANT ou MENU.'
        if search_context == 'prazo_limite':
            footer = 'Voce pode buscar por filial e NB, por nome ou por documento. Exemplos: 3 9845, bar central ou 12345678901. Se quiser voltar ao inicio, envie A, ANT ou MENU.'
        return flow.OutgoingMessage(kind='menu', title={'cliente': 'Buscar Cliente', 'inadimplencia': 'Cobranca da Carteira' if decision is not None and self._is_vendedor(decision) else 'Cobranca da Gerencia' if decision is not None and self._is_gerente_vendas(decision) else 'Consultar Inadimplencia', 'comodato': 'Consultar Comodatos', 'giro': 'Consultar Giro', 'documentacao': 'Documentacao Pendente', 'prazo_limite': 'Prazo e Limite'}.get(search_context, 'Consultar'), text=text, footer=footer, button_text='Escolher', options=tuple(options))

    def _build_inadimplencia_base_summary(self, decision: AccessDecision | None) -> str:
        flow = _customer_flow_module()
        if decision is None:
            return ''
        if not self._has_unrestricted_lookup_access(decision) and (not self._can_access_sectors(decision)):
            return ''
        allowed_sectors = self._allowed_sectors(decision)
        allowed_gv_vdes = self._allowed_gv_vdes(decision)
        try:
            summary = self.inadimplencia_service.get_finance_summary(allowed_sectors=allowed_sectors, allowed_gv_vdes=allowed_gv_vdes)
        except RuntimeError:
            return ''
        if self._has_unrestricted_lookup_access(decision):
            scope_label = 'base total'
        elif self._is_vendedor(decision):
            scope_label = 'carteira'
        else:
            scope_label = 'sua base'
        lines = [f'Cobranca da {scope_label}: {summary.client_count} inadimplentes | R$ {summary.total_pendente}', f'Vence amanha: {summary.due_tomorrow_count} cliente(s) | R$ {summary.due_tomorrow_total}', f'Vence em 2 dias: {summary.due_in_two_days_count} cliente(s) | R$ {summary.due_in_two_days_total}']
        return '\n'.join(lines)

    def _inadimplencia_scope_label(self, decision: AccessDecision) -> str:
        flow = _customer_flow_module()
        if self._has_unrestricted_lookup_access(decision):
            return 'base total'
        return 'sua base'

    def _build_documentacao_pendente_response(self, records: list[DocumentacaoPendenteClientRecord], criteria: str, scope_restricted: bool=True) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not records:
            scope_note = 'dentro do acesso liberado para o seu numero' if scope_restricted else 'na base importada'
            return flow.OutgoingMessage(text=f'Nao encontrei documentacao pendente para {criteria} {scope_note}.\nSe quiser tentar outra busca, envie MENU.')
        ordered_records = sorted(records, key=lambda item: (flow._sort_numeric_text(item.filial), flow._sort_numeric_text(item.setor), flow._sort_numeric_text(item.cod_pdv)))
        lines = [f'Encontrei {len(ordered_records)} registro(s) de documentacao pendente para {criteria}.']
        for index, record in enumerate(ordered_records, start=1):
            lines.append('')
            lines.append(f"{index}. *Cliente:* {record.nome or '-'}")
            lines.append(f"*Revenda:* {record.filial or '-'} | *NB:* {record.cod_pdv or '-'} | *Setor:* {record.setor or '-'}")
            lines.append(f'*Resumo:* {record.pending_count} documento(s) pendente(s) | Falta: {flow._format_documentacao_pending_docs(record.pending_docs)}')
            lines.append(f'*Status:* Contrato Social {record.contrato_social} | Cpf {record.cpf} | Rg {record.rg}')
            lines.append(f'*Status 2:* Comprovante de residencia {record.comprovante_residencia} | Fachada {record.fachada} | Ficha de Cadastro {record.ficha_cadastro}')
            lines.append(f"*Atualizado em:* {record.planilha_atualizada_em or '-'}")
        lines.append('')
        lines.append(flow._result_hint_text())
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_prazo_limite_response(self, records: list[PrazoLimiteClientRecord], criteria: str, *, decision: AccessDecision, scope_restricted: bool=True) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not records:
            scope_note = 'dentro do acesso liberado para o seu numero' if scope_restricted else 'na base importada'
            return flow.OutgoingMessage(text=f'Nao encontrei prazo e limite para {criteria} {scope_note}.\nSe quiser tentar outra busca, envie MENU.')
        ordered_records = sorted(records, key=lambda item: (flow._sort_numeric_text(item.filial), flow._sort_numeric_text(item.setor), flow._sort_numeric_text(item.cod_pdv)))
        lines = ['Analise Financeira']
        if len(ordered_records) > 1:
            lines.extend(['', f'Encontrei {len(ordered_records)} cliente(s) para {criteria}.'])
        for index, record in enumerate(ordered_records, start=1):
            inadimplencia_records = self._safe_inadimplencia_registration_records(decision=decision, filial=record.filial, cod_pdv=record.cod_pdv, scope_restricted=scope_restricted)
            giro_records = self._safe_giro_registration_records(decision=decision, filial=record.filial, cod_pdv=record.cod_pdv, scope_restricted=scope_restricted)
            lines.append('')
            prefix = f'{index}) ' if len(ordered_records) > 1 else ''
            lines.append(f"{prefix}Cliente: {record.nome or '-'}")
            lines.append(f"Revenda: {record.filial or '-'} | NB: {record.cod_pdv or '-'} | Setor: {record.setor or '-'}")
            lines.append(f'RN: {flow._scope_last_code(record.seller_code or record.setor)} | GV: {flow._scope_last_code(record.manager_code)}')
            cpf_label, cnpj_label = flow._format_documento_identity(getattr(record, 'documento', ''))
            lines.append(f'CPF: {cpf_label} | CNPJ: {cnpj_label}')
            lines.append('')
            lines.append('*Prazo e Limite:*')
            lines.append(f"- Prazo atual: {flow._summarize_prazo_limite_field(record.entries, 'prazo_atual')}")
            lines.append(f"- Cond. pag.: {flow._summarize_prazo_limite_field(record.entries, 'cond_pag_atual')}")
            lines.append(f"- Limite total: {flow._summarize_prazo_limite_field(record.entries, 'limite_total')}")
            lines.append(f"- Pag. em atraso: {flow._summarize_prazo_limite_field(record.entries, 'percentual_pag_atraso')}")
            lines.append('')
            lines.append('*Faturamento:*')
            for entry in record.entries:
                pedido_label = flow._format_entry_pedido_label(entry, media_label='Media por pedido')
                if not pedido_label:
                    pedido_label = f'Pedidos: 0 | Media por pedido: R$ 0,00'
                lines.append(f'- {entry.kpi}: {entry.faturamento_com_pdv} | {pedido_label}')
            lines.append('')
            lines.append('*Inadimplencia:*')
            self._append_financial_analysis_inadimplencia_lines(lines, inadimplencia_records)
            lines.append('')
            self._append_financial_analysis_documentacao_lines(lines, decision=decision, filial=record.filial, cod_pdv=record.cod_pdv, scope_restricted=scope_restricted)
            lines.append('')
            self._append_financial_analysis_giro_lines(lines, giro_records)
            lines.append('')
            lines.append(f"Atualizado em: {flow._format_display_date(record.planilha_atualizada_em or '-')}")
        lines.append('')
        lines.append(flow._result_hint_text())
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _safe_inadimplencia_registration_records(self, *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool=True) -> list[InadimplenciaRecord] | None:
        flow = _customer_flow_module()
        try:
            return self.inadimplencia_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision) if scope_restricted else None, allowed_gv_vdes=self._allowed_gv_vdes(decision) if scope_restricted else None, limit=100)
        except (RuntimeError, ValueError):
            return None

    def _safe_giro_registration_records(self, *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool=True) -> list[GiroClientRecord] | None:
        flow = _customer_flow_module()
        try:
            return self.giro_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision) if scope_restricted else None, allowed_gv_vdes=self._allowed_gv_vdes(decision) if scope_restricted else None, limit=20)
        except (RuntimeError, ValueError):
            return None

    def _append_financial_analysis_inadimplencia_lines(self, lines: list[str], records: list[InadimplenciaRecord] | None) -> None:
        flow = _customer_flow_module()
        if records is None:
            lines.append('- Total vencido: -')
            lines.append('- Titulos em aberto: -')
            return
        total_pendente = flow._sum_money_values((record.valor_pendente for record in records))
        lines.append(f'- Total vencido: {flow._format_inadimplencia_money(total_pendente)}')
        lines.append(f'- Titulos em aberto: {len(records)}')

    def _append_financial_analysis_documentacao_lines(self, lines: list[str], *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool=True) -> None:
        flow = _customer_flow_module()
        lines.append('*Documentacao:*')
        documentacao_record = self._safe_documentacao_registration_record(decision=decision, filial=filial, cod_pdv=cod_pdv, scope_restricted=scope_restricted)
        if documentacao_record is None:
            lines.append('- Sem registro na base importada')
            return
        cpf_rg_status = flow._merge_document_status(documentacao_record.cpf, documentacao_record.rg)
        lines.append(f"- Contrato Social: {documentacao_record.contrato_social or '-'}")
        lines.append(f'- Cpf/Rg: {cpf_rg_status}')
        lines.append(f"- Comprovante residencia: {documentacao_record.comprovante_residencia or '-'}")
        lines.append(f"- Fachada: {documentacao_record.fachada or '-'}")

    def _append_financial_analysis_giro_lines(self, lines: list[str], records: list[GiroClientRecord] | None) -> None:
        flow = _customer_flow_module()
        lines.append('*Giro de Vasilhame:*')
        if records is None:
            lines.append('- Base de giro indisponivel')
            return
        if not records:
            lines.append('- Sem registro no giro importado')
            return
        total_caixas = flow._format_quantity(flow._sum_formatted_amounts(*[value for record in records for value in (record.total_litrinho, record.total_inteira, record.total_litrao)]))
        caixas_ok = flow._format_quantity(flow._sum_formatted_amounts(*[value for record in records for value in (record.real_litrinho, record.real_inteira, record.real_litrao)]))
        caixas_faltando = flow._format_quantity(flow._sum_formatted_amounts(*[value for record in records for value in (record.gap_litrinho, record.gap_inteira, record.gap_litrao)]))
        gap_detail = flow._format_giro_records_gap_detail(records)
        lines.append(f'- Caixas na base: {total_caixas}')
        lines.append(f'- Caixas OK: {caixas_ok}')
        lines.append(f'- Faltam: {caixas_faltando}')
        if gap_detail:
            lines.append(f'- Falta: {gap_detail}')

    def _build_documentacao_visit_day_response(self, *, visit_day: str, decision: AccessDecision, summary: DocumentacaoPendenteScopeSummary, records: list[DocumentacaoPendenteClientRecord]) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
        lines = [f'Documentacao pendente em {visit_day_label}:', '']
        lines.append(f'Clientes monitorados: {summary.monitored_client_count}')
        lines.append(f'Clientes com pendencia: {summary.pending_client_count}')
        lines.append(f'Documentos faltando: {summary.pending_document_count}')
        lines.append(f'Resumo pendente: CS {summary.contrato_social_pendentes} | CPF {summary.cpf_pendentes} | RG {summary.rg_pendentes} | CR {summary.comprovante_residencia_pendentes} | FAC {summary.fachada_pendentes} | FC {summary.ficha_cadastro_pendentes}')
        lines.append(f"Documentacao atualizada em: {summary.planilha_atualizada_em or '-'}")
        if not records:
            lines.append('')
            lines.append('Nenhum cliente com documentacao pendente nessa rota.')
            lines.append('')
            lines.append(flow._result_hint_text())
            return flow.OutgoingMessage(text='\n'.join(lines))
        ordered_records = sorted(records, key=lambda item: (flow._sort_scope_code(item.manager_code or item.seller_code), flow._sort_scope_code(item.seller_code), flow._sort_numeric_text(item.cod_pdv), str(item.nome or '').lower()))
        lines.append('')
        lines.append(f'Clientes com pendencia: {len(ordered_records)} | Documentos faltando: {sum((int(record.pending_count or 0) for record in ordered_records))}')
        lines.append('')
        lines.append('Clientes com documentacao pendente:')
        current_manager = ''
        current_seller = ''
        for index, record in enumerate(ordered_records, start=1):
            manager_code = flow.normalize_stored_scope_value(record.manager_code)
            seller_code = flow.normalize_stored_scope_value(record.seller_code)
            if self._has_unrestricted_lookup_access(decision) and manager_code and (manager_code != current_manager):
                lines.append(f'{flow._format_gv_scope_label(manager_code)}')
                current_manager = manager_code
                current_seller = ''
            if seller_code and seller_code != current_seller:
                lines.append(f'Setor {flow._format_sector_scope_label(seller_code)}')
                current_seller = seller_code
            lines.append(f"{index}. Codigo {record.cod_pdv} | {record.nome or '-'} | Pendencias {record.pending_count} | Falta: {flow._format_documentacao_pending_docs(record.pending_docs)}")
        lines.append('')
        lines.append(flow._result_hint_text())
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_fantasia_results_menu(self, query_text: str, records: list[DClienteRecord], search_context: str='cliente', invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        header_context_map = {'cliente': f"Encontrei {len(records)} cliente(s) com '{query_text}'.", 'inadimplencia': f"Encontrei {len(records)} cliente(s) com '{query_text}' na inadimplencia.", 'comodato': f"Encontrei {len(records)} cliente(s) com '{query_text}' nos comodatos pendentes.", 'giro': f"Encontrei {len(records)} cliente(s) com '{query_text}' na base de giro de vasilhame.", 'documentacao': f"Encontrei {len(records)} cliente(s) com '{query_text}' na base de documentacao pendente.", 'prazo_limite': f"Encontrei {len(records)} cliente(s) com '{query_text}' na base de prazo e limite."}
        header = header_context_map.get(search_context, f"Encontrei {len(records)} cliente(s) com '{query_text}'.")
        if invalid_selection:
            header = f'Nao entendi essa opcao.\n{header}'
        detail_prompt_map = {'cliente': 'Escolha um cliente para ver os detalhes.', 'inadimplencia': 'Escolha um cliente para ver os titulos em aberto.', 'comodato': 'Escolha um cliente para ver os comodatos pendentes.', 'giro': 'Escolha um cliente para ver os dados de giro de vasilhame.', 'documentacao': 'Escolha um cliente para ver a documentacao pendente.', 'prazo_limite': 'Escolha um cliente para ver prazo, limite e documentacao.'}
        text = f"{header}\n{detail_prompt_map.get(search_context, 'Escolha um cliente para ver os detalhes.')}"
        title_map = {'cliente': 'Resultados da Busca', 'inadimplencia': 'Resultados de Inadimplencia', 'comodato': 'Resultados de Comodatos', 'giro': 'Resultados de Giro', 'documentacao': 'Resultados de Documentacao', 'prazo_limite': 'Resultados de Prazo e Limite'}
        code_label = 'Codigo do PDV' if search_context == 'cliente' else 'NB'
        return flow.OutgoingMessage(kind='menu', title=title_map.get(search_context, 'Resultados da Busca'), text=text, footer=f'A lista mostra {code_label.lower()}, revenda e nome do cliente. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.FANTASIA_PICK_PREFIX}{index}', title=record.nome_fantasia or record.razao_social or f'Cliente {index}', description=f'{code_label} {record.cod_pdv} | Revenda {record.filial}') for index, record in enumerate(records, start=1))))

    def _build_inadimplencia_client_menu(self, query_text: str, summaries: list[InadimplenciaClientSummary], total_available: int | None=None, page: int | None=None, page_size: int | None=None, list_context: str='', invalid_selection: bool=False, navigation_notice: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        page_size = flow.INADIMPLENCIA_PAGE_SIZE if page_size is None else page_size
        custom_header = flow._extract_inadimplencia_custom_header(query_text)
        scope_label = flow._extract_inadimplencia_scope_label(query_text)
        director_compact = list_context == flow.INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS
        if custom_header:
            header = custom_header
        elif scope_label:
            header = f'Esses sao os clientes inadimplentes da {scope_label}.'
        elif director_compact:
            header = 'Diretoria | Cobranca'
        else:
            header = f"Encontrei {len(summaries)} cliente(s) com '{query_text}' na inadimplencia."
        if navigation_notice:
            header = f'{navigation_notice}\n{header}'
        if invalid_selection:
            header = f'Nao entendi essa opcao.\n{header}'
        lines = [header]
        paginated = page is not None and total_available is not None and (total_available > page_size)
        if paginated:
            total_pages = flow._compute_page_count(total_items=total_available, page_size=page_size)
            current_page = min(max(page or 1, 1), total_pages)
            start_index = (current_page - 1) * page_size + 1
            end_index = start_index + len(summaries) - 1
            if director_compact:
                lines.append(f'Pagina {current_page} de {total_pages} | Clientes {start_index}-{end_index} de {total_available}')
            else:
                lines.append(f'Pagina {current_page} de {total_pages}.')
                lines.append(f'Mostrando clientes {start_index} a {end_index} de {total_available}.')
        elif (custom_header or scope_label) and total_available and (total_available > len(summaries)):
            lines.append(f'Estou mostrando os primeiros {len(summaries)} de {total_available} cliente(s).')
        if director_compact:
            lines.append(f'Clientes na lista: {len(summaries)}')
            lines.append('Escolha o cliente para ver os titulos.')
        else:
            lines.append('Escolha o cliente certo para ver os titulos pendentes.')
        text = '\n'.join(lines)
        options: list[flow.InteractiveOption] = [flow.InteractiveOption(option_id=f'{flow.INADIMPLENCIA_CLIENT_PICK_PREFIX}{summary.filial}:{summary.cod_pdv}' if paginated else f'{flow.FANTASIA_PICK_PREFIX}{index}', title=summary.nome or f'Cliente {index}', description=f'NB {summary.cod_pdv} | Revenda {summary.filial} | {summary.title_count} titulo(s) | R$ {summary.total_pendente}', shortcut=str(index)) for index, summary in enumerate(summaries, start=1)]
        if paginated:
            total_pages = flow._compute_page_count(total_items=total_available or 0, page_size=page_size)
            current_page = min(max(page or 1, 1), total_pages)
            next_shortcut, prev_shortcut = flow._inadimplencia_page_shortcuts(page_size)
            if current_page > 1:
                options.append(flow.InteractiveOption(option_id=flow.INADIMPLENCIA_PAGE_PREV, title='Pagina anterior', description=f'Voltar para a pagina {current_page - 1}', shortcut=prev_shortcut))
            if current_page < total_pages:
                options.append(flow.InteractiveOption(option_id=flow.INADIMPLENCIA_PAGE_NEXT, title='Proxima pagina', description=f'Ir para a pagina {current_page + 1}', shortcut=next_shortcut))
        return flow.OutgoingMessage(kind='menu', title='Diretoria | Cobranca' if director_compact else 'Clientes Encontrados', text=text, footer=f"{('Escolha o cliente para ver os titulos.' if director_compact else 'Primeiro voce escolhe o cliente. Depois eu mostro os titulos.')}{(' Use ' + flow._inadimplencia_page_shortcuts_label(page_size, page, total_available) if paginated else ' Use A ou ANT para voltar.')}", button_text='Escolher', options=tuple(options))

    def _build_comodato_client_menu(self, query_text: str, summaries: list[ComodatoClientSummary], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        header = f"Encontrei {len(summaries)} cliente(s) com '{query_text}' nos comodatos pendentes."
        if invalid_selection:
            header = f'Nao entendi essa opcao.\n{header}'
        text = f'{header}\nEscolha o cliente certo para ver os comodatos pendentes.'
        return flow.OutgoingMessage(kind='menu', title='Clientes Encontrados', text=text, footer='Primeiro voce escolhe o cliente. Depois eu mostro os comodatos pendentes. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.FANTASIA_PICK_PREFIX}{index}', title=summary.nome or f'Cliente {index}', description=f'NB {summary.cod_pdv} | Revenda {summary.filial} | {summary.comodato_count} comodato(s) | {summary.total_material} material(is)') for index, summary in enumerate(summaries, start=1))))

    def _build_visit_day_options(self, visit_days: list[str] | tuple[str, ...], *, description: str) -> tuple[InteractiveOption, ...]:
        flow = _customer_flow_module()
        ordered_visit_days = flow._normalize_visit_day_menu_values(visit_days)
        return tuple((flow.InteractiveOption(option_id=f'{flow.VISIT_DAY_PICK_PREFIX}{index}', title=flow._format_visit_day_label(visit_day), description=description, shortcut=str(index)) for index, visit_day in enumerate(ordered_visit_days, start=1)))

    def _select_visit_day_option(self, *, text: str, normalized: str, visit_days: tuple[str, ...], description: str) -> str | None:
        flow = _customer_flow_module()
        ordered_visit_days = tuple(flow._normalize_visit_day_menu_values(visit_days))
        selected_option = flow._select_interactive_option(text=text, normalized=normalized, options=self._build_visit_day_options(ordered_visit_days, description=description))
        if selected_option is None:
            return None
        raw_index = selected_option.option_id.removeprefix(flow.VISIT_DAY_PICK_PREFIX)
        if raw_index.isdigit():
            selected_index = int(raw_index)
            if 1 <= selected_index <= len(ordered_visit_days):
                return ordered_visit_days[selected_index - 1]
        return None

    def _build_visit_day_menu(self, decision: AccessDecision, visit_days: list[str], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        header = 'Escolha o dia que voce quer consultar.'
        if invalid_selection:
            header = flow._invalid_option_text('Escolha o dia que voce quer consultar.')
        footer = 'Depois eu mostro o resumo dos GVs e, logo abaixo, o detalhe por setor.'
        if not self._uses_grouped_visit_flow(decision):
            footer = 'Depois eu mostro os clientes desse dia.'
        return flow.OutgoingMessage(kind='menu', title='Visitas do Dia', text=header, footer=f"{('Depois eu mostro o proximo nivel de detalhe da rota.' if self._uses_grouped_visit_flow(decision) else footer)} Use A ou ANT para voltar.", button_text='Escolher', options=self._build_visit_day_options(visit_days, description='Ver clientes desse dia'))

    def _build_giro_visit_day_menu(self, visit_days: list[str], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        return self.finance_flow._build_giro_visit_day_menu(visit_days=visit_days, invalid_selection=invalid_selection)

    def _build_inadimplencia_visit_day_menu(self, visit_days: list[str], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        header = 'Qual dia voce quer consultar na inadimplencia?'
        if invalid_selection:
            header = flow._invalid_option_text('Escolha um dia para consultar a inadimplencia.')
        return flow.OutgoingMessage(kind='menu', title='Inadimplencia por Dia', text=header, footer='Eu vou mostrar o resumo do dia e depois o proximo nivel de detalhe com os clientes em risco financeiro. Use A ou ANT para voltar.', button_text='Escolher', options=self._build_visit_day_options(visit_days, description='Ver a rota com risco financeiro desse dia'))

    def _build_documentacao_visit_day_menu(self, visit_days: list[str], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        header = 'Qual dia voce quer consultar na documentacao pendente?'
        if invalid_selection:
            header = flow._invalid_option_text('Escolha um dia para consultar a documentacao pendente.')
        return flow.OutgoingMessage(kind='menu', title='Documentacao por Dia', text=header, footer='Eu vou mostrar o resumo documental do dia e, logo abaixo, os clientes com pendencia. Use A ou ANT para voltar.', button_text='Escolher', options=self._build_visit_day_options(visit_days, description='Ver resumo e clientes com pendencia documental desse dia'))

    def _build_visit_day_manager_menu(self, visit_day: str, visit_summaries: list[VisitSellerSummary], invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
        if not visit_summaries:
            return flow.OutgoingMessage(text=f"Nao encontrei visitas para o dia '{visit_day_label}'.\nSe quiser tentar de novo, envie MENU.")
        lines = [f"Visitas de '{visit_day_label}'"]
        if invalid_selection:
            lines.insert(0, 'Nao entendi essa opcao.')
        lines.append(f'GVs na rota: {len({flow.normalize_stored_scope_value(summary.manager_code) or flow.normalize_stored_scope_value(summary.seller_code) for summary in visit_summaries})} | Setores: {len(visit_summaries)} | Visitas: {sum((int(summary.visit_count or 0) for summary in visit_summaries))}')
        lines.append('Detalhe por setor: escolha o setor.')
        return flow.OutgoingMessage(kind='menu', title='Visitas por Setor', text='\n'.join(lines), footer='Na descricao de cada opcao eu mostro o GV e a quantidade de visitas do setor. Use A ou ANT para voltar.', button_text='Escolher', options=tuple((flow.InteractiveOption(option_id=f'{flow.VISIT_SELLER_PICK_PREFIX}{index}', title=flow._format_sector_scope_label(summary.seller_code), description=f'{flow._format_gv_scope_label(summary.manager_code)} | {summary.visit_count} visita(s)', shortcut=str(index)) for index, summary in enumerate(visit_summaries, start=1))))

    def _build_single_record_response(self, record: DClienteRecord, criteria: str, *, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = ['Cliente', '']
        self._append_cliente_detail_lines(lines, record=record, decision=decision)
        lines.append('')
        lines.append(flow._result_hint_text(allow_back=False))
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_search_response(self, records: list[DClienteRecord], criteria: str, *, decision: AccessDecision, scope_restricted: bool=True) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not records:
            message = f'Nao encontrei cliente para {criteria}'
            if scope_restricted:
                message = f'{message} dentro do acesso liberado para o seu numero'
            return flow.OutgoingMessage(text=f'{message}.\nSe quiser tentar outra busca, envie MENU.')
        lines = ['Cliente' if len(records) == 1 else f'Clientes encontrados: {len(records)}']
        lines.append(f'Consulta: {criteria}')
        for index, record in enumerate(records, start=1):
            lines.append('')
            self._append_cliente_detail_lines(lines, record=record, decision=decision, index=index if len(records) > 1 else None, scope_restricted=scope_restricted)
        lines.append('')
        lines.append(flow._result_hint_text(allow_back=False))
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _append_cliente_detail_lines(self, lines: list[str], *, record: DClienteRecord, decision: AccessDecision, index: int | None=None, scope_restricted: bool=True) -> None:
        flow = _customer_flow_module()
        name = record.nome_fantasia or record.razao_social or '-'
        title = f'*{name}*'
        if index is not None:
            title = f'{index}) {title}'
        lines.append(title)
        lines.append(f"NB: {record.cod_pdv or '-'} | Revenda: {record.filial or '-'} | Setor: {record.vendedor or '-'}")
        lines.append('')
        lines.append('*Cadastro:*')
        lines.append(f"Razao social: {record.razao_social or '-'}")
        lines.append(f"Fantasia: {record.nome_fantasia or '-'}")
        lines.append(f"Telefone: {record.telefone or '-'}")
        lines.append(f"Situacao: {record.status or '-'}")
        lines.append(f"Cidade: {record.cidade or '-'}")
        lines.append('')
        lines.append('*Rota:*')
        lines.append(f'Dia de visita: {flow._format_cliente_visit_day(record.dia_visita)}')
        lines.append(f"Vendedor/Setor: {record.vendedor or '-'}")
        lines.append('')
        lines.append('*Financeiro:*')
        lines.append(f"Cond. pag.: {record.cond_pag_atual or '-'}")
        lines.append(f'Limite: {flow._format_currency_brl(record.limite_credito)}')
        lines.append(f'Total pendente: {flow._format_currency_brl(record.total_pendente)}')
        lines.append('')
        lines.append('*Pendencias:*')
        lines.append(f'Comodatos: {record.total_comodatos_pendentes}')
        self._append_documentacao_cliente_lines(lines, decision=decision, record=record, scope_restricted=scope_restricted)
        lines.append('')
        lines.append(f"*Atualizado em:* {flow._format_display_date(record.ultima_atualizacao_tabela or '-')}")

    def _append_documentacao_cliente_lines(self, lines: list[str], *, decision: AccessDecision, record: DClienteRecord, scope_restricted: bool=True) -> None:
        flow = _customer_flow_module()
        documentacao_record = self._safe_documentacao_cliente_record(decision=decision, record=record, scope_restricted=scope_restricted)
        if documentacao_record is None:
            return
        lines.append('*Documentacao:*')
        for label, value in (('Contrato Social', documentacao_record.contrato_social), ('Cpf', documentacao_record.cpf), ('Rg', documentacao_record.rg), ('Comprovante de residencia', documentacao_record.comprovante_residencia), ('Fachada', documentacao_record.fachada), ('Ficha de Cadastro', documentacao_record.ficha_cadastro)):
            lines.append(f"- {label}: {value or '-'}")

    def _safe_documentacao_cliente_record(self, *, decision: AccessDecision, record: DClienteRecord, scope_restricted: bool=True) -> DocumentacaoPendenteClientRecord | None:
        flow = _customer_flow_module()
        return self._safe_documentacao_registration_record(decision=decision, filial=record.filial, cod_pdv=record.cod_pdv, scope_restricted=scope_restricted)

    def _safe_documentacao_registration_record(self, *, decision: AccessDecision, filial: str, cod_pdv: str, scope_restricted: bool=True) -> DocumentacaoPendenteClientRecord | None:
        flow = _customer_flow_module()
        try:
            status = self.documentacao_pendente_service.status()
        except Exception:
            return None
        if not status.get('ready'):
            return None
        try:
            records = self.documentacao_pendente_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision) if scope_restricted else None, allowed_gv_vdes=self._allowed_gv_vdes(decision) if scope_restricted else None, limit=1)
        except RuntimeError:
            return None
        return records[0] if records else None

    def _append_documentacao_snapshot_lines(self, lines: list[str], *, decision: AccessDecision, filial: str, cod_pdv: str) -> None:
        flow = _customer_flow_module()
        try:
            status_payload = self.documentacao_pendente_service.status()
        except Exception:
            status_payload = {'ready': False}
        documentacao_record = self._safe_documentacao_registration_record(decision=decision, filial=filial, cod_pdv=cod_pdv)
        if documentacao_record is None:
            if status_payload.get('ready'):
                lines.append('*Documentacao:* Sem registro na base importada')
            else:
                lines.append('*Documentacao:* Base nao importada ou indisponivel')
            return
        lines.append(f'*Documentacao:* Contrato Social {documentacao_record.contrato_social} | Cpf {documentacao_record.cpf} | Rg {documentacao_record.rg}')
        lines.append(f'*Documentacao 2:* Comprovante de residencia {documentacao_record.comprovante_residencia} | Fachada {documentacao_record.fachada} | Ficha de Cadastro {documentacao_record.ficha_cadastro}')

    def _append_documentacao_snapshot_detail_lines(self, lines: list[str], *, decision: AccessDecision, filial: str, cod_pdv: str) -> None:
        flow = _customer_flow_module()
        try:
            status_payload = self.documentacao_pendente_service.status()
        except Exception:
            status_payload = {'ready': False}
        documentacao_record = self._safe_documentacao_registration_record(decision=decision, filial=filial, cod_pdv=cod_pdv)
        if documentacao_record is None:
            if status_payload.get('ready'):
                lines.append('*Documentacao:* Sem registro na base importada')
            else:
                lines.append('*Documentacao:* Base nao importada ou indisponivel')
            return
        lines.append('*Documentacao:*')
        for label, value in (('Contrato Social', documentacao_record.contrato_social), ('Cpf', documentacao_record.cpf), ('Rg', documentacao_record.rg), ('Comprovante de residencia', documentacao_record.comprovante_residencia), ('Fachada', documentacao_record.fachada), ('Ficha de Cadastro', documentacao_record.ficha_cadastro)):
            lines.append(f"- {label}: {value or '-'}")

    def _run_repeatable_registration_lookup(self, *, sender: str, session: LookupSession, decision: AccessDecision, search_context: str, filial: str, cod_pdv: str, return_menu: str='search_menu') -> OutgoingMessage:
        flow = _customer_flow_module()
        self._remember_last_context(session, intent=f'{search_context}_client', search_context=search_context, client_filial=filial, client_cod_pdv=cod_pdv)
        return self._with_post_result_navigation(sender, session, self._run_registration_lookup(decision=decision, search_context=search_context, filial=filial, cod_pdv=cod_pdv), return_menu=return_menu, repeat_action=flow.REPEAT_SEARCH_REGISTRATION)

    def _run_registration_lookup(self, decision: AccessDecision, search_context: str, filial: str, cod_pdv: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        if search_context == 'inadimplencia':
            records = self.inadimplencia_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
            return self._build_inadimplencia_response(records, f'revenda {filial} e NB {cod_pdv}')
        if search_context == 'comodato':
            records = self.comodatos_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
            return self._build_comodato_response(records, f'revenda {filial} e NB {cod_pdv}')
        if search_context == 'giro':
            records = self.giro_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
            if not records:
                try:
                    matching_base = self.query_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
                except RuntimeError:
                    matching_base = []
                if matching_base:
                    historical_response = self._build_giro_historical_fallback_response(decision=decision, filial=filial, cod_pdv=cod_pdv, criteria=f'revenda {filial} e NB {cod_pdv}')
                    if historical_response is not None:
                        return historical_response
                    return flow.OutgoingMessage(text=f'Encontrei o cadastro para revenda {filial} e NB {cod_pdv}, mas ele nao apareceu no ultimo relatorio de giro importado.\nSe quiser tentar outra busca, envie MENU.')
            return self._build_giro_response(records, f'revenda {filial} e NB {cod_pdv}', scope_restricted=not self._has_unrestricted_lookup_access(decision))
        if search_context == 'documentacao':
            records = self.documentacao_pendente_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=20)
            return self._build_documentacao_pendente_response(records, f'revenda {filial} e NB {cod_pdv}', scope_restricted=not self._has_unrestricted_lookup_access(decision))
        if search_context == 'prazo_limite':
            records = self.prazo_limite_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=50)
            if not records:
                try:
                    matching_base = self.query_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
                except RuntimeError:
                    matching_base = []
                if matching_base:
                    return flow.OutgoingMessage(text=f'Encontrei o cadastro para revenda {filial} e NB {cod_pdv}, mas ele nao apareceu no ultimo relatorio de prazo e limite importado.\nSe quiser tentar outra busca, envie MENU.')
            return self._build_prazo_limite_response(records, f'revenda {filial} e NB {cod_pdv}', decision=decision, scope_restricted=not self._has_unrestricted_lookup_access(decision))
        records = self.query_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        return self._build_search_response(records, f'revenda {filial} e Cod PDV {cod_pdv}', decision=decision)

    def _search_giro_by_document(self, normalized_document: str) -> list[GiroClientRecord]:
        flow = _customer_flow_module()
        client_records = self.query_service.search_by_document(document=normalized_document, allowed_sectors=None, allowed_gv_vdes=None, limit=20)
        unique_keys: set[tuple[str, str]] = set()
        giro_records: list[flow.GiroClientRecord] = []
        for client in client_records:
            filial = flow._normalize_filial(client.filial)
            cod_pdv = flow._normalize_cod_pdv(client.cod_pdv)
            if not filial or not cod_pdv:
                continue
            key = (filial, cod_pdv)
            if key in unique_keys:
                continue
            unique_keys.add(key)
            giro_records.extend(self.giro_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=None, allowed_gv_vdes=None, limit=5))
        return sorted(giro_records, key=lambda item: (flow._sort_numeric_text(item.filial), flow._sort_numeric_text(item.cod_pdv)))

    def _build_inadimplencia_response(self, records: list[InadimplenciaRecord], criteria: str, *, compact: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not records:
            return flow.OutgoingMessage(text=f'Nao encontrei titulos em aberto para {criteria} dentro do acesso liberado para o seu numero.\nSe quiser tentar outra busca, envie MENU.')
        total_pendente = flow._sum_money_values((record.valor_pendente for record in records))
        total_atrasado = flow._sum_money_values((record.valor_corrigido or record.valor_pendente for record in records if flow._inadimplencia_days_value(record.dias) is not None and flow._inadimplencia_days_value(record.dias) < 0))
        first = records[0]
        lines = ['Diretoria | Cobranca' if compact else 'Inadimplencia', '', f"*{first.nome or '-'}*", f"- Revenda: {first.filial or '-'}", f"- NB: {first.cod_pdv or '-'}", '', '*Resumo:*', f'- Titulos: {len(records)}', f'- Total pendente: {flow._format_inadimplencia_money(total_pendente)}', f'- Total atrasado: {flow._format_inadimplencia_money(total_atrasado)}', f'- {flow._format_inadimplencia_summary_timing_label(records)}', f"- Atualizado em: {flow._format_display_date(first.planilha_atualizada_em or '-')}", '', '*Titulos:*']
        for index, record in enumerate(records, start=1):
            lines.append('')
            lines.append(f'{index}) {flow._format_inadimplencia_timing_label(record.dias).capitalize()}')
            lines.append(f"- NF: {record.nota_fiscal or '-'}")
            lines.append(f"- Vencimento: {flow._format_display_date(record.data_vencimento or '-')}")
            if not compact:
                lines.append(f"- Emissao: {flow._format_display_date(record.data_emissao or '-')}")
            lines.append(f'- Valor: {flow._format_inadimplencia_money(record.valor_corrigido or record.valor_pendente)}')
        lines.append('')
        lines.append(flow._result_hint_text(allow_back=compact))
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_comodato_response(self, records: list[ComodatoRecord], criteria: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not records:
            return flow.OutgoingMessage(text=f'Nao encontrei comodatos pendentes para {criteria} dentro do acesso liberado para o seu numero.\nSe quiser tentar outra busca, envie MENU.')
        unique_comodatos = {flow._normalize_cod_pdv(record.nro_comodato) for record in records if flow._normalize_cod_pdv(record.nro_comodato)}
        lines = [f'Encontrei {len(unique_comodatos) or len(records)} comodato(s) pendente(s) para {criteria}.']
        lines.append(f"*Planilha atualizada em:* {records[0].planilha_atualizada_em or '-'}")
        lines.append(f'*Materiais pendentes:* {len(records)}')
        for index, record in enumerate(records, start=1):
            lines.append('')
            lines.append(f"{index}. *Numero do Comodato:* {record.nro_comodato or '-'}")
            lines.append(f"*Material:* {record.material or '-'}")
            lines.append(f"*Sub Tipo Material:* {record.sub_tipo_material or '-'}")
            lines.append(f"*Saldo:* {record.saldo or '0'}")
        lines.append('')
        lines.append('*Atalho para recolha:*')
        lines.append('- Envie RECOLHA para abrir a solicitacao desse cliente.')
        lines.append('- Envie RECOLHA TODOS para pedir a recolha de todos os comodatos.')
        lines.append('- Envie RECOLHA 1,3 para pedir itens especificos da lista.')
        lines.append('')
        lines.append('Se quiser fazer outra consulta, envie MENU.')
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_giro_response(self, records: list[GiroClientRecord], criteria: str, scope_restricted: bool=True) -> OutgoingMessage:
        flow = _customer_flow_module()
        return self.finance_flow._build_giro_response(records=records, criteria=criteria, scope_restricted=scope_restricted)

    def _build_visit_day_clients_response(self, visit_day: str, records: list[DClienteRecord], decision: AccessDecision, financial_alerts: list[InadimplenciaVisitAlert], alerts_note: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
        if not records:
            return flow.OutgoingMessage(text=f"Nao encontrei clientes para o dia '{visit_day_label}'.\nSe quiser tentar outra consulta, envie MENU.")
        visit_summaries = self._load_visit_day_seller_summaries(decision, visit_day)
        lines = [f'Rota em {visit_day_label}']
        lines.append(f'Setores na rota: {len(visit_summaries)} | Visitas: {len(records)}' if visit_summaries else f'Visitas: {len(records)}')
        lines.append(f"Atualizado em: {records[0].ultima_atualizacao_tabela or '-'}")
        lines.append('')
        for index, record in enumerate(records, start=1):
            client_name = record.nome_fantasia or record.razao_social or '-'
            lines.append(f"{index}. {client_name} | Cod {record.cod_pdv} | Setor {record.vendedor or '-'}")
        self._append_visit_financial_section(lines, financial_alerts, alerts_note)
        lines.append('')
        lines.append('Se quiser fazer outra consulta, envie MENU.')
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _load_visit_day_seller_summaries(self, decision: AccessDecision, visit_day: str, *, limit: int=1000) -> list[VisitSellerSummary]:
        flow = _customer_flow_module()
        try:
            return self.query_service.list_visit_day_seller_summaries(visit_day=visit_day, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=limit)
        except RuntimeError:
            return []

    def _build_visit_day_seller_clients_response(self, visit_day: str, summary: VisitSellerSummary, records: list[DClienteRecord], decision: AccessDecision, financial_alerts: list[InadimplenciaVisitAlert], alerts_note: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        visit_day_label = flow._format_visit_day_label(visit_day)
        if not records:
            return flow.OutgoingMessage(text=f"Nao encontrei visitas para {flow._format_sector_scope_label(summary.seller_code)} no dia '{visit_day_label}'.\n{flow._format_gv_scope_label(summary.manager_code)} | Total no resumo: {summary.visit_count} visita(s)\nSe quiser tentar outra consulta, envie MENU.")
        lines = [f"Clientes de {flow._format_sector_scope_label(summary.seller_code)} no dia '{visit_day_label}':", f'{flow._format_gv_scope_label(summary.manager_code)} | {summary.visit_count} visita(s)', f"Atualizado em: {records[0].ultima_atualizacao_tabela or '-'}"]
        for index, record in enumerate(records, start=1):
            client_name = record.nome_fantasia or record.razao_social or '-'
            lines.append(f'{index}. {client_name} | Cod {record.cod_pdv}')
        self._append_visit_financial_section(lines, financial_alerts, alerts_note)
        lines.append('')
        lines.append('Se quiser fazer outra consulta, envie MENU.')
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_visit_day_giro_summaries(self, decision: AccessDecision, records: list[DClienteRecord]) -> tuple[dict[tuple[str, str], tuple[str, str, str, str]], str]:
        flow = _customer_flow_module()
        status = self.giro_service.status()
        if not status['ready']:
            return ({}, '')
        summaries: dict[tuple[str, str], tuple[str, str, str, str]] = {}
        updated_at = ''
        for record in records:
            filial = flow._normalize_filial(record.filial)
            cod_pdv = flow._normalize_cod_pdv(record.cod_pdv)
            if not filial or not cod_pdv:
                continue
            key = (filial, cod_pdv)
            if key in summaries:
                continue
            try:
                giro_records = self.giro_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=1)
            except RuntimeError:
                continue
            if not giro_records:
                continue
            giro_record = giro_records[0]
            total_caixas = flow._format_quantity(flow._sum_formatted_amounts(giro_record.total_litrinho, giro_record.total_inteira, giro_record.total_litrao))
            gap_caixas = flow._format_quantity(flow._sum_formatted_amounts(giro_record.gap_litrinho, giro_record.gap_inteira, giro_record.gap_litrao))
            gap_detail = flow._format_giro_gap_detail(giro_record)
            summaries[key] = (giro_record.setor or '', total_caixas, gap_caixas, gap_detail)
            updated_at = updated_at or (giro_record.planilha_atualizada_em or '')
        return (summaries, updated_at)

    def _load_visit_day_financial_alerts(self, decision: AccessDecision, visit_day: str, seller_code: str='', manager_code: str='') -> tuple[list[InadimplenciaVisitAlert], str]:
        flow = _customer_flow_module()
        status = self.inadimplencia_service.status()
        if not status['ready']:
            return ([], 'Nao consegui consultar os boletos agora.')
        try:
            alerts = self.inadimplencia_service.list_upcoming_by_visit_day(visit_day=visit_day, seller_code=seller_code or None, manager_code=manager_code or None, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=80)
        except Exception:
            flow.logger.exception('Falha ao consultar boletos por dia de visita', extra={'visit_day': visit_day, 'seller_code': seller_code, 'manager_code': manager_code, 'roles': list(decision.roles)})
            return ([], 'Nao consegui consultar os boletos agora.')
        return (alerts, '')

    def _append_visit_financial_section(self, lines: list[str], alerts: list[InadimplenciaVisitAlert], alerts_note: str) -> None:
        flow = _customer_flow_module()
        lines.append('')
        lines.append('*Atencao Financeira desse dia:*')
        if alerts_note:
            lines.append(alerts_note)
            return
        if not alerts:
            lines.append('Nenhum cliente dessa rota esta vencendo em 2, 1, 0 dias ou ja inadimplente.')
            return
        lines.append(f"Planilha atualizada em: {alerts[0].planilha_atualizada_em or '-'}")
        overdue = [alert for alert in alerts if alert.nearest_days_to_due < 0]
        due_today = [alert for alert in alerts if alert.nearest_days_to_due == 0]
        due_tomorrow = [alert for alert in alerts if alert.nearest_days_to_due == 1]
        due_in_two_days = [alert for alert in alerts if alert.nearest_days_to_due == 2]
        self._append_visit_financial_group(lines, 'Ja inadimplentes', overdue)
        self._append_visit_financial_group(lines, 'Vence hoje', due_today)
        self._append_visit_financial_group(lines, 'Vence amanha', due_tomorrow)
        self._append_visit_financial_group(lines, 'Vence em 2 dias', due_in_two_days)

    def _append_visit_financial_group(self, lines: list[str], label: str, alerts: list[InadimplenciaVisitAlert]) -> None:
        flow = _customer_flow_module()
        if not alerts:
            return
        lines.append(f'{label}: {len(alerts)} cliente(s) | R$ {flow._sum_money_values((alert.total_pendente for alert in alerts))}')
        for index, alert in enumerate(alerts, start=1):
            lines.append(f"{index}. Codigo {alert.cod_pdv} | {alert.nome or '-'} | {alert.title_count} titulo(s) | R$ {alert.total_pendente} | {flow._format_visit_financial_status(alert.nearest_days_to_due)}")
