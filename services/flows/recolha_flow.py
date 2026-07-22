from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class RecolhaFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def handle_session(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        return self._handle_recolha_session(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def handle_post_result_request(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any | None:
        flow = _customer_flow_module()
        if self._can_update_recolhas(decision) and flow._looks_like_recolha_update_request(normalized):
            update_request = flow._parse_recolha_finance_update_request(text=text, normalized=normalized)
            if update_request is not None:
                identifier, updates = update_request
                return self._build_recolha_update_response(
                    self._update_recolha_for_decision(
                        identifier=identifier,
                        updates=updates,
                        sender=sender,
                        decision=decision,
                    ),
                    identifier=identifier,
                )
        if not flow._looks_like_recolha_request(normalized):
            return None
        return self._handle_recolha_entry_request(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
            return_menu="main",
        )

    def handle_idle_request(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any | None:
        flow = _customer_flow_module()
        if session.step != "idle":
            return None
        if self._can_update_recolhas(decision) and flow._looks_like_recolha_update_request(normalized):
            update_request = flow._parse_recolha_finance_update_request(text=text, normalized=normalized)
            if update_request is not None:
                identifier, updates = update_request
                return self._build_recolha_update_response(
                    self._update_recolha_for_decision(
                        identifier=identifier,
                        updates=updates,
                        sender=sender,
                        decision=decision,
                    ),
                    identifier=identifier,
                )
        if not flow._looks_like_recolha_request(normalized):
            return None
        return self._handle_recolha_entry_request(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
            return_menu="main",
        )

    def _handle_recolha_entry_request(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
        return_menu: str,
    ) -> Any:
        flow = _customer_flow_module()
        management_request = flow._parse_recolha_management_request(normalized)
        if management_request is not None:
            action, identifier = management_request
            if action == "clear" and not self._can_clear_recolhas(decision):
                return flow.OutgoingMessage(
                    text=(
                        "A limpeza geral de recolhas esta liberada apenas para admin, gerencia, "
                        "diretoria ou financeiro sem restricao de filial."
                    )
                )
            if action == "clear":
                return self._open_recolha_clear_confirmation(sender=sender, session=session)
            if not self._can_view_recolhas(decision):
                return flow.OutgoingMessage(text="Voce nao tem acesso ao gerenciamento de recolhas.")
            return self._open_recolha_delete_confirmation(
                sender=sender,
                session=session,
                identifier=identifier,
                decision=decision,
            )
        if self._can_update_recolhas(decision):
            update_request = flow._parse_recolha_finance_update_request(text=text, normalized=normalized)
            if update_request is not None:
                identifier, updates = update_request
                return self._build_recolha_update_response(
                    self._update_recolha_for_decision(
                        identifier=identifier,
                        updates=updates,
                        sender=sender,
                        decision=decision,
                    ),
                    identifier=identifier,
                )
        if self._can_view_recolhas(decision) and flow._looks_like_recolha_list_request(normalized):
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_recolhas_finance_response(
                    request_text=normalized,
                    sender=sender,
                    decision=decision,
                ),
                return_menu=return_menu,
            )
        if not self._can_request_recolha(decision):
            return flow.OutgoingMessage(
                text=(
                    "A solicitacao de recolha esta liberada para vendedor, GV e financeiro.\n"
                    "Se voce for do financeiro, envie RECOLHAS para ver as solicitacoes."
                )
            )
        return self._open_recolha_request(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _open_recolha_request(self, *, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not self._can_request_recolha(decision):
            self._reset_session(sender)
            return flow.OutgoingMessage(text='A solicitacao de recolha esta liberada para vendedor, GV e financeiro.\nSe voce for do financeiro, envie RECOLHAS para ver as solicitacoes.')
        text = self._contextualize_recolha_request_text(session=session, text=text)
        self._clear_recolha_state(session)
        inline_request = flow._parse_recolha_inline_request(text)
        if inline_request is not None:
            client_ref, comodato, obs = inline_request
            client_error = self._apply_recolha_client_reference(session, decision=decision, client_ref=client_ref)
            if client_error is not None:
                session.step = 'recolha_awaiting_client'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return client_error
            if comodato:
                partial_records = flow._resolve_recolha_partial_group_selection(session=session, text=comodato)
                if partial_records is not None:
                    if not partial_records:
                        session.step = 'recolha_awaiting_comodato'
                        session.updated_at = flow.datetime.now(flow.timezone.utc)
                        self.sessions[sender] = session
                        return self._build_recolha_comodato_prompt(session=session, invalid_selection=True)
                    session.recolha_partial_comodato_options = tuple(partial_records)
                    session.recolha_obs = obs
                    session.step = 'recolha_awaiting_partial_items'
                    session.updated_at = flow.datetime.now(flow.timezone.utc)
                    self.sessions[sender] = session
                    return self._build_recolha_partial_prompt(session=session)
                session.recolha_comodato = flow._resolve_recolha_comodato_selection(session=session, text=comodato)
            if obs:
                session.recolha_obs = obs
            if session.recolha_comodato:
                session.step = 'recolha_confirm'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_recolha_confirmation(session=session)
            session.step = 'recolha_awaiting_comodato'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_comodato_prompt(session=session)
        session.step = 'recolha_awaiting_client'
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_recolha_client_prompt()

    def _contextualize_recolha_request_text(self, *, session: LookupSession, text: str) -> str:
        flow = _customer_flow_module()
        if not (self._has_recent_last_context(session) and session.last_search_context == 'comodato' and session.last_client_filial and session.last_client_cod_pdv):
            return text
        raw = str(text or '').strip()
        if not raw:
            return text
        normalized = flow._normalize_choice(raw)
        if not flow._looks_like_recolha_request(normalized):
            return text
        payload = flow._recolha_request_payload(raw)
        if not payload:
            return f'recolha {session.last_client_filial} {session.last_client_cod_pdv}'
        normalized_payload = flow._normalize_choice(payload)
        if normalized_payload in {'todos', 'tudo', 'total', 'recolha total', 'todos os comodatos', 'recolher todos'} or normalized_payload.startswith(('todos ', 'tudo ', 'total ', 'recolha total ')) or flow._looks_like_recolha_numeric_selection(normalized_payload) or flow._looks_like_recolha_custom_selection(normalized_payload) or flow._looks_like_recolha_partial_group_selection(normalized_payload):
            return f'recolha {session.last_client_filial} {session.last_client_cod_pdv} | {payload}'
        return text

    def _handle_recolha_session(self, *, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        if session.step in {'recolha_delete_confirm', 'recolha_clear_confirm'}:
            if normalized in {'cancelar', 'sair', 'voltar'}:
                self._reset_session(sender)
                return flow.OutgoingMessage(text='Operacao cancelada.\nSe quiser voltar ao inicio, envie MENU.')
            if session.step == 'recolha_delete_confirm':
                if not self._can_view_recolhas(decision):
                    self._reset_session(sender)
                    return flow.OutgoingMessage(text='Voce nao tem acesso ao gerenciamento de recolhas.')
                if normalized in {'confirmar remover', 'confirmar apagar', 'confirmar exclusao', 'confirmar excluir'}:
                    deleted = self._delete_recolha_for_decision(identifier=session.recolha_pending_identifier, sender=sender, decision=decision)
                    self._reset_session(sender)
                    return self._build_recolha_deleted_response(deleted, identifier=session.recolha_pending_identifier)
                self.sessions[sender] = session
                return self._build_recolha_delete_confirmation(self._find_recolha_for_decision(identifier=session.recolha_pending_identifier, sender=sender, decision=decision), identifier=session.recolha_pending_identifier, invalid_selection=True)
            if not self._can_clear_recolhas(decision):
                self._reset_session(sender)
                return flow.OutgoingMessage(text='Esse fluxo de limpeza geral e exclusivo do admin, gerencial ou financeiro sem restricao de filial.')
            if normalized == 'confirmar limpar':
                deleted_count = self.recolha_request_service.clear_requests()
                self._reset_session(sender)
                return flow.OutgoingMessage(text=f'Limpeza de Recolhas\n\n*Resultado:*\n- {deleted_count} solicitacao(oes) removida(s).\n\nO CSV de recolhas ficou apenas com o cabecalho.')
            self.sessions[sender] = session
            return self._build_recolha_clear_confirmation(invalid_selection=True)
        if not self._can_request_recolha(decision):
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Esse fluxo de recolha esta liberado para vendedor, GV e financeiro.')
        if normalized in {'editar', 'recomecar', 'reiniciar'}:
            self._clear_recolha_state(session)
            session.step = 'recolha_awaiting_client'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_client_prompt()
        if session.step == 'recolha_awaiting_client':
            selected_record = flow._select_recolha_client_option(text=text, options=session.recolha_client_options)
            if selected_record is not None:
                self._apply_recolha_client_record(session, record=selected_record, decision=decision)
                session.step = 'recolha_awaiting_comodato'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_recolha_comodato_prompt(session=session)
            client_error = self._apply_recolha_client_reference(session, decision=decision, client_ref=text)
            if client_error is not None:
                self.sessions[sender] = session
                return client_error
            session.step = 'recolha_awaiting_comodato'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_comodato_prompt(session=session)
        if session.step == 'recolha_awaiting_comodato':
            if flow._is_recolha_custom_selection_keyword(normalized):
                self.sessions[sender] = session
                return flow.OutgoingMessage(
                    text=(
                        "Solicitacao de Recolha\n\n"
                        "*Recolha sem comodato:*\n"
                        "- Digite exatamente o que deve ser recolhido.\n"
                        "- Exemplo: AVULSO 2 mesas de plastico e 1 freezer sem contrato."
                    )
                )
            partial_records = flow._resolve_recolha_partial_group_selection(session=session, text=text)
            if partial_records is not None:
                if not partial_records:
                    self.sessions[sender] = session
                    return self._build_recolha_comodato_prompt(session=session, invalid_selection=True)
                session.recolha_partial_comodato_options = tuple(partial_records)
                session.step = 'recolha_awaiting_partial_items'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_recolha_partial_prompt(session=session)
            comodato = flow._resolve_recolha_comodato_selection(session=session, text=text)
            if not comodato:
                self.sessions[sender] = session
                return self._build_recolha_comodato_prompt(session=session, invalid_selection=True)
            session.recolha_comodato = comodato
            session.step = 'recolha_awaiting_obs'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_obs_prompt()
        if session.step == 'recolha_awaiting_partial_items':
            if normalized in {'voltar', 'volta', 'a', 'ant'}:
                session.recolha_partial_comodato_options = ()
                session.step = 'recolha_awaiting_comodato'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_recolha_comodato_prompt(session=session)
            comodato, error_text = flow._resolve_recolha_partial_item_selection(session=session, text=text)
            if not comodato:
                self.sessions[sender] = session
                return self._build_recolha_partial_prompt(session=session, invalid_selection=True, error_text=error_text)
            session.recolha_comodato = comodato
            session.recolha_partial_comodato_options = ()
            session.step = 'recolha_confirm' if session.recolha_obs else 'recolha_awaiting_obs'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if session.step == 'recolha_confirm':
                return self._build_recolha_confirmation(session=session)
            return self._build_recolha_obs_prompt()
        if session.step == 'recolha_awaiting_obs':
            session.recolha_obs = '' if normalized in {'sem obs', 'sem observacao', 'nao', 'n'} else flow._clean_recolha_text(text)
            session.step = 'recolha_confirm'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_recolha_confirmation(session=session)
        if session.step == 'recolha_confirm':
            if normalized in {'confirmar', 'confirma', 'confirmo', 'sim', 's', 'ok'}:
                records = self.recolha_request_service.create_requests(solicitante=decision.normalized_number or sender, solicitante_nome=self._recolha_requester_name(sender=sender, decision=decision), revenda=session.recolha_revenda, data=flow.datetime.now(flow.LOCAL_TIMEZONE).strftime('%d/%m/%Y'), setor=session.recolha_setor, cidade=session.recolha_cidade, rn=session.recolha_rn, nb=session.recolha_nb, comodato=session.recolha_comodato, obs=session.recolha_obs, created_at=flow.datetime.now(flow.LOCAL_TIMEZONE))
                self._reset_session(sender)
                return self._build_recolha_created_response(records=records, cliente=session.recolha_cliente)
            self.sessions[sender] = session
            return self._build_recolha_confirmation(session=session, invalid_selection=True)
        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _clear_recolha_state(self, session: LookupSession) -> None:
        flow = _customer_flow_module()
        session.recolha_filial = ''
        session.recolha_nb = ''
        session.recolha_cliente = ''
        session.recolha_client_options = ()
        session.recolha_revenda = ''
        session.recolha_setor = ''
        session.recolha_cidade = ''
        session.recolha_rn = ''
        session.recolha_comodato = ''
        session.recolha_comodato_options = ()
        session.recolha_partial_comodato_options = ()
        session.recolha_obs = ''
        session.recolha_pending_action = ''
        session.recolha_pending_identifier = ''

    def _apply_recolha_client_reference(self, session: LookupSession, *, decision: AccessDecision, client_ref: str) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        filial, cod_pdv = flow._resolve_recolha_registration_input(client_ref, decision=decision)
        if not filial or not cod_pdv:
            return self._apply_recolha_client_name_reference(session, decision=decision, query_text=client_ref)
        try:
            records = self.query_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision))
        except (RuntimeError, ValueError):
            records = []
        records = self._filter_recolha_client_records_by_scope(records, decision=decision)
        if not records:
            return flow.OutgoingMessage(text=f'Nao encontrei o cliente {filial} {cod_pdv} dentro da sua base.\nConfira a filial/NB e envie novamente.')
        self._apply_recolha_client_record(session, record=records[0], decision=decision)
        return None

    def _apply_recolha_client_name_reference(self, session: LookupSession, *, decision: AccessDecision, query_text: str) -> OutgoingMessage | None:
        flow = _customer_flow_module()
        cleaned_query = flow._clean_recolha_text(query_text)
        if not cleaned_query or flow._normalize_choice(cleaned_query) in {'recolha', 'recolhas'}:
            return flow.OutgoingMessage(text='Nao consegui identificar o cliente para a recolha.\nEnvie o NB, o nome do cliente, ou filial e NB. Exemplo: 3 9845.')
        try:
            records = self.query_service.search_by_fantasia(query_text=cleaned_query, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=10)
        except (RuntimeError, ValueError, AttributeError):
            records = []
        records = self._filter_recolha_client_records_by_scope(records, decision=decision)
        if not records:
            return flow.OutgoingMessage(text=f"Nao encontrei cliente com '{cleaned_query}' dentro da sua base.\nTente pelo NB ou envie MENU.")
        if len(records) == 1:
            self._apply_recolha_client_record(session, record=records[0], decision=decision)
            return None
        session.recolha_client_options = tuple(records[:10])
        return self._build_recolha_client_selection_prompt(cleaned_query, records=list(session.recolha_client_options))

    def _apply_recolha_client_record(self, session: LookupSession, *, record: DClienteRecord, decision: AccessDecision) -> None:
        flow = _customer_flow_module()
        session.recolha_filial = record.filial
        session.recolha_nb = record.cod_pdv
        session.recolha_cliente = record.nome_fantasia or record.razao_social or f'NB {record.cod_pdv}'
        session.recolha_client_options = ()
        session.recolha_revenda = flow.FILIAL_LABELS.get(flow._normalize_filial(record.filial), record.filial)
        session.recolha_setor = record.vendedor or flow._scope_last_code((decision.sectors or ('',))[0] if decision.sectors else '')
        session.recolha_cidade = record.cidade
        session.recolha_rn = session.recolha_setor
        session.recolha_comodato_options = tuple(self._fetch_recolha_comodato_options(filial=record.filial, cod_pdv=record.cod_pdv, decision=decision))
        session.recolha_partial_comodato_options = ()

    def _filter_recolha_client_records_by_scope(self, records: list[DClienteRecord], *, decision: AccessDecision) -> list[DClienteRecord]:
        flow = _customer_flow_module()
        if self._has_unrestricted_lookup_access(decision):
            return list(records)
        allowed_sector_pairs = {flow.normalize_stored_scope_value(value) for value in decision.sectors if flow.normalize_stored_scope_value(value)}
        if not allowed_sector_pairs:
            return list(records)
        filtered: list[flow.DClienteRecord] = []
        for record in records:
            record_pair = flow.normalize_stored_scope_value(f'{record.filial}_{record.vendedor}')
            if record_pair in allowed_sector_pairs:
                filtered.append(record)
        return filtered

    def _fetch_recolha_comodato_options(self, *, filial: str, cod_pdv: str, decision: AccessDecision) -> list[ComodatoRecord]:
        flow = _customer_flow_module()
        try:
            return self.comodatos_service.search_by_registration(filial=filial, cod_pdv=cod_pdv, allowed_sectors=self._allowed_sectors(decision), allowed_gv_vdes=self._allowed_gv_vdes(decision), limit=1000)
        except (RuntimeError, ValueError):
            return []

    def _build_recolha_client_prompt(self) -> OutgoingMessage:
        flow = _customer_flow_module()
        return flow.OutgoingMessage(text='Solicitacao de Recolha\n\n*Cliente:*\n- Envie o NB ou parte do nome do cliente.\n- Se precisar, envie filial e NB: 3 9845.\n\nAtalho em uma mensagem:\nrecolha 9845 todos')

    def _build_recolha_client_selection_prompt(self, query_text: str, *, records: list[DClienteRecord]) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = ['Solicitacao de Recolha', '', f"Encontrei {len(records)} cliente(s) com '{query_text}'.", 'Escolha o cliente pelo numero:']
        for index, record in enumerate(records, start=1):
            lines.append(f"{index}. {record.nome_fantasia or record.razao_social or '-'} | Revenda {record.filial or '-'} | NB {record.cod_pdv or '-'} | Setor {record.vendedor or '-'}")
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_recolha_comodato_prompt(self, *, session: LookupSession, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        first_line = 'O que deve ser recolhido?'
        if invalid_selection:
            first_line = 'Nao entendi o que deve ser recolhido.'
        return flow.OutgoingMessage(text=f"Solicitacao de Recolha\n\n*Cliente:*\n- Nome: {session.recolha_cliente or '-'}\n- Revenda: {session.recolha_filial or '-'} | NB: {session.recolha_nb or '-'} | Setor: {session.recolha_setor or '-'}\n\n" + self._build_recolha_comodato_options_text(first_line, session=session))

    def _build_recolha_comodato_options_text(self, first_line: str, *, session: LookupSession) -> str:
        flow = _customer_flow_module()
        records = list(session.recolha_comodato_options or ())
        if not records:
            return f'*Comodato:*\n- {first_line}\n- Nao encontrei comodatos pendentes listados para esse cliente.\n\n*Como responder:*\n- Digite AVULSO + o que deve ser recolhido.\n- Exemplo: AVULSO 30 cx de litrinho, freezer e mesas.'
        lines = ['*Comodatos pendentes:*', f'- {first_line}']
        for index, group in enumerate(flow._group_recolha_comodato_records(records), start=1):
            lines.append(f'{index}. {flow._format_recolha_comodato_group_option(group)}')
            for record in group:
                lines.append(f'   - {flow._format_recolha_comodato_product_option(record)}')
        lines.extend(['', '*Como responder:*', '- Recolher todos os comodatos: TODOS.', '- Recolher um comodato inteiro: numero da opcao. Ex.: 1.', '- Recolher mais de um comodato inteiro: numeros separados por virgula. Ex.: 1,3.', '- Recolha parcial de um comodato: PARCIAL + numero. Ex.: PARCIAL 2.', '- Item fora da lista: AVULSO + descricao. Ex.: AVULSO 2 mesas e 1 freezer.'])
        return '\n'.join(lines)

    def _build_recolha_partial_prompt(self, *, session: LookupSession, invalid_selection: bool=False, error_text: str='') -> OutgoingMessage:
        flow = _customer_flow_module()
        records = list(session.recolha_partial_comodato_options or ())
        if not records:
            return self._build_recolha_comodato_prompt(session=session, invalid_selection=True)
        first_record = records[0]
        lines = ['Solicitacao de Recolha', '', '*Recolha parcial:*', f"- Comodato: {first_record.nro_comodato or '-'}"]
        if invalid_selection:
            lines.extend(['', error_text or 'Nao entendi os produtos/quantidades da recolha parcial.'])
        lines.extend(['', '*Produtos do comodato:*'])
        for index, record in enumerate(records, start=1):
            lines.append(f'{index}. {flow._format_recolha_comodato_product_option(record)}')
        lines.extend(['', '*Como responder:*', '- Produto inteiro: numero da opcao. Ex.: 1.', '- Mais de um produto inteiro: numeros separados por virgula. Ex.: 1,2.', '- Quantidade parcial: opcao=quantidade. Ex.: 1=120.', '- Mais de uma quantidade parcial: 1=120,2=10.', '- Voltar para os comodatos: VOLTAR.'])
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_recolha_obs_prompt(self) -> OutgoingMessage:
        flow = _customer_flow_module()
        return flow.OutgoingMessage(text='Solicitacao de Recolha\n\n*Observacao:*\n- Envie alguma orientacao para o financeiro/faturista.\n- Se nao tiver, envie SEM OBS.')

    def _build_recolha_confirmation(self, *, session: LookupSession, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = ['Solicitacao de Recolha', '']
        if invalid_selection:
            lines.extend(['Envie CONFIRMAR para registrar, EDITAR para recomeçar ou CANCELAR para sair.', ''])
        lines.extend([f"Cliente: {session.recolha_cliente or '-'}", f"Revenda: {session.recolha_filial or '-'} | NB: {session.recolha_nb or '-'} | Setor: {session.recolha_setor or '-'}", '', '*Pedido:*', f"- Comodato: {session.recolha_comodato or '-'}", f"- OBS.: {session.recolha_obs or '-'}", '', 'Envie CONFIRMAR para registrar.', 'Envie EDITAR para recomeçar ou CANCELAR para sair.'])
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_recolha_created_response(self, *, records: list[RecolhaRequestRecord], cliente: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        record = records[0] if records else None
        if record is None:
            return flow.OutgoingMessage(text='Solicitacao de Recolha\n\nNao consegui registrar a solicitacao agora.\nTente novamente em instantes.')
        item_lines = []
        for index, item in enumerate(records, start=1):
            item_lines.append(f"{index}. ID {item.id} | {item.comodato or '-'}")
        return flow.OutgoingMessage(text=f"Solicitacao de Recolha registrada\n\nCliente: {cliente or '-'}\nRevenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}\n\n*Pedido:*\n- Comodato(s): {len(records)}\n- OBS.: {record.obs or '-'}\n- Status inicial: {record.status_caixa_noturno}\n\n*Itens gerados:*\n" + '\n'.join(item_lines) + '\n\nO financeiro ja consegue ver essa solicitacao em RECOLHAS.\nO CSV ja esta atualizado para copia/importacao.')

    def _open_recolha_delete_confirmation(self, *, sender: str, session: LookupSession, identifier: str, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        record = self._find_recolha_for_decision(identifier=identifier, sender=sender, decision=decision)
        session.step = 'recolha_delete_confirm'
        session.recolha_pending_action = 'delete'
        session.recolha_pending_identifier = identifier
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_recolha_delete_confirmation(record, identifier=identifier)

    def _open_recolha_clear_confirmation(self, *, sender: str, session: LookupSession) -> OutgoingMessage:
        flow = _customer_flow_module()
        session.step = 'recolha_clear_confirm'
        session.recolha_pending_action = 'clear'
        session.recolha_pending_identifier = ''
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_recolha_clear_confirmation()

    def _build_recolha_delete_confirmation(self, record: RecolhaRequestRecord | None, *, identifier: str, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        if record is None:
            return flow.OutgoingMessage(text=f"Remover Recolha\n\nNao encontrei solicitacao para '{identifier}'.\nUse RECOLHAS para conferir os IDs/NBs.")
        lines = ['Remover Recolha', '']
        if invalid_selection:
            lines.extend(['Para remover, envie exatamente CONFIRMAR REMOVER.', ''])
        lines.extend(['*Solicitacao encontrada:*', f"- ID: {record.id or '-'}", f"- Revenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}", f"- Comodato: {record.comodato or '-'}", f"- Status: {record.status_caixa_noturno or '-'}", '', 'Envie CONFIRMAR REMOVER para apagar essa solicitacao.', 'Envie CANCELAR para sair.'])
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_recolha_clear_confirmation(self, *, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = ['Limpar Recolhas', '']
        if invalid_selection:
            lines.extend(['Para limpar tudo, envie exatamente CONFIRMAR LIMPAR.', ''])
        lines.extend(['*Atencao:*', '- Isso remove todas as solicitacoes do CSV de recolhas.', '- O arquivo ficara apenas com o cabecalho.', '', 'Envie CONFIRMAR LIMPAR para continuar.', 'Envie CANCELAR para sair.'])
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_recolha_deleted_response(self, record: RecolhaRequestRecord | None, *, identifier: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        if record is None:
            return flow.OutgoingMessage(text=f"Remover Recolha\n\nNao encontrei solicitacao para '{identifier}'.\nNada foi removido.")
        return flow.OutgoingMessage(text=f"Remover Recolha\n\n*Removida:*\n- ID: {record.id or '-'}\n- Revenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}\n- Comodato: {record.comodato or '-'}\n\nCSV atualizado.")

    def _build_recolha_update_response(self, record: RecolhaRequestRecord | None, *, identifier: str) -> OutgoingMessage:
        flow = _customer_flow_module()
        if record is None:
            return flow.OutgoingMessage(text=f"Atualizacao de Recolha\n\nNao encontrei solicitacao de recolha para '{identifier}'.\nUse RECOLHAS para conferir as solicitacoes abertas.")
        return flow.OutgoingMessage(text=f"Atualizacao de Recolha\n\n*Solicitacao:*\n- Revenda: {record.revenda or '-'} | NB: {record.nb or '-'} | Setor: {record.setor or '-'}\n- Comodato: {record.comodato or '-'}\n\n*Faturista/Caixa:*\n- Lancado: {record.lancado_faturista or '-'}\n- Motorista: {record.motorista_faturista or '-'}\n- Placa: {record.placa_faturista or '-'}\n- Mapa: {record.mapa_faturista or '-'}\n- Status: {record.status_caixa_noturno or '-'}\n- Motivo: {record.motivo_caixa_noturno or '-'}\n\nCSV atualizado.")

    def _recolha_requester_keys(self, *, sender: str, decision: AccessDecision) -> set[str]:
        flow = _customer_flow_module()
        keys: set[str] = set()
        for value in (decision.normalized_number, sender):
            normalized = flow._normalize_phone_number(value)
            if normalized:
                keys.add(normalized)
            digits = ''.join((char for char in str(value or '') if char.isdigit()))
            if digits:
                keys.add(digits)
        return keys

    def _recolha_requester_name(self, *, sender: str, decision: AccessDecision) -> str:
        flow = _customer_flow_module()
        for value in (decision.normalized_number, sender):
            try:
                user = self.access_control.get_user(value)
            except Exception:
                user = None
            name = str((user or {}).get('name') or '').strip()
            if name:
                return name
        return ''

    def _recolha_identity_keys(self, value: str) -> set[str]:
        flow = _customer_flow_module()
        keys: set[str] = set()
        normalized = flow._normalize_phone_number(value)
        if normalized:
            keys.add(normalized)
        digits = ''.join((char for char in str(value or '') if char.isdigit()))
        if digits:
            keys.add(digits)
        return keys

    def _recolha_record_visible_for_decision(self, record: RecolhaRequestRecord, *, sender: str, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        if self._is_admin(decision):
            return True
        if self._is_financeiro(decision):
            allowed_filiais = flow._recolha_allowed_filiais_from_decision(decision)
            if not allowed_filiais:
                return True
            record_filial = flow._recolha_record_filial_code(record)
            return bool(record_filial and record_filial in allowed_filiais)
        if self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision):
            return True
        requester_keys = self._recolha_requester_keys(sender=sender, decision=decision)
        solicitante_keys = self._recolha_identity_keys(record.solicitante)
        return bool(requester_keys & solicitante_keys)

    def _filter_recolha_records_for_decision(self, records: list[RecolhaRequestRecord], *, sender: str, decision: AccessDecision) -> list[RecolhaRequestRecord]:
        flow = _customer_flow_module()
        return [record for record in records if self._recolha_record_visible_for_decision(record, sender=sender, decision=decision)]

    def _find_recolha_for_decision(self, *, identifier: str, sender: str, decision: AccessDecision) -> RecolhaRequestRecord | None:
        flow = _customer_flow_module()
        normalized_identifier = str(identifier or '').strip().lower()
        if not normalized_identifier:
            return None
        try:
            records = self.recolha_request_service.list_requests(limit=500)
        except OSError:
            return None
        for record in records:
            if not flow._recolha_record_matches_identifier(record, normalized_identifier):
                continue
            if self._recolha_record_visible_for_decision(record, sender=sender, decision=decision):
                return record
        return None

    def _update_recolha_for_decision(self, *, identifier: str, updates: dict[str, str], sender: str, decision: AccessDecision) -> RecolhaRequestRecord | None:
        flow = _customer_flow_module()
        record = self._find_recolha_for_decision(identifier=identifier, sender=sender, decision=decision)
        if record is None:
            return None
        return self.recolha_request_service.update_latest(identifier=record.id or identifier, updates=updates)

    def _delete_recolha_for_decision(self, *, identifier: str, sender: str, decision: AccessDecision) -> RecolhaRequestRecord | None:
        flow = _customer_flow_module()
        record = self._find_recolha_for_decision(identifier=identifier, sender=sender, decision=decision)
        if record is None:
            return None
        return self.recolha_request_service.delete_latest(identifier=record.id or identifier)

    def _build_recolhas_finance_response(self, request_text: str='', *, sender: str='', decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        try:
            all_records = self.recolha_request_service.list_all_requests()
        except OSError:
            return flow.OutgoingMessage(text='Solicitacoes de Recolha\n\nNo momento, nao consegui acessar o arquivo de recolhas.\nTente novamente em instantes.')
        visible_records = self._filter_recolha_records_for_decision(all_records, sender=sender, decision=decision)
        total = len(visible_records)
        if not visible_records:
            return flow.OutgoingMessage(text='Solicitacoes de Recolha\n\n*Resumo:*\n- Total visivel: 0\n\nNenhuma solicitacao de recolha encontrada para o seu acesso.')
        base_filters = flow._parse_recolha_request_filters(request_text, default_open=False)
        if base_filters.invalid_reason:
            return flow.OutgoingMessage(text=f'Solicitacoes de Recolha\n\n{base_filters.invalid_reason}\n\n*Exemplos validos:*\n- RECOLHAS HOJE\n- RECOLHAS ONTEM\n- RECOLHAS SEMANA\n- RECOLHAS 19/05/2026\n- RECOLHAS 19/05/2026 A 22/05/2026')
        default_open = not base_filters.explicit_period and (not base_filters.explicit_status)
        request_filters = flow._parse_recolha_request_filters(request_text, default_open=default_open)
        filtered_records = flow._filter_recolha_records_for_request(visible_records, request_text, default_open=default_open)
        csv_bytes = self.recolha_request_service.export_csv_bytes(filtered_records)
        if flow._recolha_request_is_summary(request_text):
            return self._build_recolhas_summary_response(records=filtered_records, total=total, csv_bytes=csv_bytes, request_filters=request_filters)
        records = filtered_records[:30]
        if not records:
            return flow.OutgoingMessage(text=f'Solicitacoes de Recolha\n\nNao encontrei solicitacoes para esse filtro.\n- Periodo: {request_filters.period_label}\n- Status: {request_filters.status_label}\n\nUse RECOLHAS para pendencias abertas, RECOLHAS HOJE para o dia ou RECOLHAS HISTORICO para tudo.')
        lines = ['Solicitacoes de Recolha', '', '*Resumo:*', f'- Total visivel: {total}', f'- No filtro: {len(filtered_records)}', f'- Periodo: {request_filters.period_label}', f'- Status: {request_filters.status_label}', f'- Mostrando ultimas: {len(records)}', '', '*Ultimas solicitacoes:*']
        for index, record in enumerate(records, start=1):
            lines.extend(['', f"{index}) Revenda {record.revenda or '-'} | Setor {record.setor or '-'} | NB {record.nb or '-'}", f"- Data: {record.data or '-'}", f"- RN: {record.rn or '-'}", f"- Cidade: {record.cidade or '-'}", f"- Comodato: {record.comodato or '-'}", f"- Lancado: {record.lancado_faturista or '-'}", f"- Status: {record.status_caixa_noturno or '-'}"])
            if record.motorista_faturista or record.placa_faturista or record.mapa_faturista:
                lines.append(f"- Motorista/Placa/Mapa: {record.motorista_faturista or '-'} | {record.placa_faturista or '-'} | {record.mapa_faturista or '-'}")
            if record.motivo_caixa_noturno:
                lines.append(f'- Motivo: {record.motivo_caixa_noturno}')
            if record.obs:
                lines.append(f'- OBS.: {record.obs}')
        lines.extend(['', '*Atualizacao rapida:*', '- Faturista: FATURISTA 9845 LANCADO MOTORISTA Joao PLACA ABC1234 MAPA 88', '- Caixa: CAIXA 9845 RECOLHIDO', '- Caixa pendente: CAIXA 9845 NAO RECOLHIDO MOTIVO cliente fechado', '- Cancelar: CANCELAR RECOLHA 9845', '', 'CSV anexado no mesmo padrao da planilha de recolhas.'])
        return flow.OutgoingMessage(text='\n'.join(lines), kind='media', media_url=flow._build_csv_data_url(csv_bytes), media_type='document', media_caption='Solicitacoes de recolha CSV', media_filename='solicitacoes_recolha.csv')

    def _build_recolhas_summary_response(self, *, records: list[RecolhaRequestRecord], total: int, csv_bytes: bytes, request_filters: RecolhaRequestFilters | None=None) -> OutgoingMessage:
        flow = _customer_flow_module()
        summary = flow._summarize_recolha_records(records)
        filters = request_filters or flow.RecolhaRequestFilters()
        lines = ['Resumo de Recolhas', '', '*Base:*', f'- Total visivel: {total}', f'- No filtro: {len(records)}', f'- Periodo: {filters.period_label}', f'- Status: {filters.status_label}', f"- Abertas: {summary['abertas']}", f"- Lancadas: {summary['lancadas']}", f"- Recolhidas: {summary['recolhidas']}", f"- Nao recolhidas: {summary['nao_recolhidas']}", '', '*Por filial:*']
        for key, count in summary['por_filial']:
            lines.append(f'- {key}: {count}')
        lines.append('')
        lines.append('*Por setor:*')
        for key, count in summary['por_setor']:
            lines.append(f'- {key}: {count}')
        lines.extend(['', 'CSV anexado no mesmo padrao da planilha de recolhas.'])
        return flow.OutgoingMessage(text='\n'.join(lines), kind='media', media_url=flow._build_csv_data_url(csv_bytes), media_type='document', media_caption='Solicitacoes de recolha CSV', media_filename='solicitacoes_recolha.csv')

    def _can_request_recolha(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._is_vendedor(decision) or self._is_gerente_vendas(decision) or self._can_use_finance_menu(decision)

    def _can_view_recolhas(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._can_request_recolha(decision) or self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)

    def _can_update_recolhas(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._can_use_finance_menu(decision)

    def _can_clear_recolhas(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._is_admin(decision) or (self._is_financeiro(decision) and (not flow._recolha_allowed_filiais_from_decision(decision))) or self._is_gerente_vendas(decision) or self._is_diretor_comercial(decision)

    def _can_manage_recolhas(self, decision: AccessDecision) -> bool:
        flow = _customer_flow_module()
        return self._can_clear_recolhas(decision)
