from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class AdminAccessFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def open_menu(
        self,
        *,
        sender: str,
        session: Any,
        decision: Any,
    ) -> Any:
        flow = _customer_flow_module()
        if not self._is_admin(decision):
            return flow.OutgoingMessage(
                text=(
                    "Essa opcao esta disponivel apenas para administradores.\n"
                    "Se quiser, envie MENU para voltar."
                )
            )
        if not self.access_control.enabled:
            return flow.OutgoingMessage(
                text="No momento, o cadastro de usuarios pelo WhatsApp nao esta disponivel."
            )
        session = flow.LookupSession(step="admin_select_action")
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_admin_action_menu()

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
        if not self._is_admin(decision):
            return None
        admin_check_match = flow.re.match(
            r"^(?:validar acesso|checar acesso|conferir acesso)\s+(.+)$",
            normalized,
        )
        if admin_check_match:
            phone_number = flow._normalize_phone_number(admin_check_match.group(1))
            if not phone_number:
                return flow.OutgoingMessage(text="Me envie o telefone com DDI para validar o acesso.")
            try:
                user = self.access_control.get_user(phone_number)
            except RuntimeError:
                self._reset_session(sender)
                return flow.OutgoingMessage(
                    text=(
                        "Nao consegui validar esse acesso agora.\n"
                        "Tente novamente em instantes."
                    )
                )
            self._reset_session(sender)
            return self._build_admin_access_check_response(phone_number, user)

        admin_action = flow._parse_admin_action(normalized)
        if not admin_action or flow._looks_like_plain_numeric_choice(normalized):
            return None
        if not self.access_control.enabled:
            return flow.OutgoingMessage(
                text="No momento, o cadastro de usuarios pelo WhatsApp nao esta disponivel."
            )
        admin_session = flow.LookupSession(step="admin_select_action")
        admin_session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = admin_session
        return self._handle_admin_session(
            sender=sender,
            session=admin_session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

    def _handle_admin_session(self, sender: str, session: LookupSession, text: str, normalized: str, decision: AccessDecision) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not self._is_admin(decision):
            self._reset_session(sender)
            return flow.OutgoingMessage(text='Esse menu e exclusivo do administrador.\nSe quiser voltar, envie MENU.')
        if flow._is_back_menu_command(normalized) and session.step == 'admin_select_action':
            self._reset_session(sender)
            return self._build_main_menu(decision)
        if session.step == 'admin_select_action':
            action = flow._parse_admin_action(normalized)
            if not action:
                self.sessions[sender] = session
                return self._build_admin_action_menu(invalid_selection=True)
            if action == 'summary':
                try:
                    users = self.access_control.list_users()
                except RuntimeError:
                    self._reset_session(sender)
                    return flow.OutgoingMessage(text='Nao consegui montar o resumo administrativo agora.\nTente novamente em instantes.')
                self._reset_session(sender)
                return self._build_admin_summary_response(users)
            if action == 'health':
                self._reset_session(sender)
                return self._build_admin_health_response()
            if action == 'list':
                try:
                    users = self.access_control.list_users()
                except RuntimeError:
                    self._reset_session(sender)
                    return flow.OutgoingMessage(text='Nao consegui listar os usuarios agora.\nTente novamente em instantes.')
                self._reset_session(sender)
                return self._build_admin_users_list_response(users)
            session.admin_action = action
            session.step = 'admin_awaiting_phone'
            session.target_phone = ''
            session.current_name = ''
            session.target_name = ''
            session.target_role = ''
            session.target_sectors = ()
            session.target_gv_vdes = ()
            session.current_roles = ()
            session.current_sectors = ()
            session.current_gv_vdes = ()
            session.current_is_active = True
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if action == 'create':
                return flow.OutgoingMessage(text='Vamos cadastrar um novo usuario.\nMe envie o numero com DDI.\nPode mandar com espacos, + ou traco que eu ajusto aqui.\nExemplo: +55 83 99196-4911')
            if action == 'rename':
                return flow.OutgoingMessage(text='Vamos alterar o nome de um usuario que ja existe.\nMe envie o numero com DDI.\nPode mandar com espacos, + ou traco que eu ajusto aqui.\nExemplo: +55 83 99196-4911')
            if action == 'check':
                return flow.OutgoingMessage(text='Vamos validar o acesso de um numero.\nMe envie o telefone com DDI.\nPode mandar com espacos, + ou traco que eu ajusto aqui.\nExemplo: +55 83 99196-4911')
            return flow.OutgoingMessage(text='Vamos alterar um usuario que ja existe.\nMe envie o numero com DDI.\nPode mandar com espacos, + ou traco que eu ajusto aqui.\nExemplo: +55 83 99196-4911')
        if session.step == 'admin_awaiting_phone':
            phone_number = flow._normalize_phone_number(text)
            if len(phone_number) < 10:
                self.sessions[sender] = session
                return flow.OutgoingMessage(text='Nao consegui entender esse numero.\nMe envie o telefone com DDI.\nPode mandar com espacos, + ou traco que eu ajusto aqui.\nExemplo: +55 83 99196-4911')
            try:
                existing_user = self.access_control.get_user(phone_number)
            except (RuntimeError, ValueError):
                self._reset_session(sender)
                return flow.OutgoingMessage(text='Nao consegui consultar esse numero agora.\nTente novamente em instantes.')
            if session.admin_action == 'create' and existing_user is not None:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return flow.OutgoingMessage(text="Esse numero ja esta cadastrado.\nVoce pode escolher 'Alterar acesso' ou enviar outro numero.")
            if session.admin_action in {'update', 'rename'} and existing_user is None:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return flow.OutgoingMessage(text='Nao encontrei esse numero no cadastro.\nEnvie outro numero ou digite MENU para voltar.')
            session.target_phone = phone_number
            session.current_name = str(existing_user.get('name') or '') if existing_user else ''
            session.target_name = session.current_name
            session.current_roles = tuple((str(item) for item in existing_user.get('roles', []))) if existing_user else ()
            session.current_sectors = tuple((str(item) for item in existing_user.get('sectors', []))) if existing_user else ()
            session.current_gv_vdes = tuple((str(item) for item in existing_user.get('gv_vdes', []))) if existing_user else ()
            session.current_is_active = bool(existing_user.get('is_active')) if existing_user else False
            session.target_role = ''
            session.target_sectors = ()
            session.target_gv_vdes = ()
            if session.admin_action == 'check':
                self._reset_session(sender)
                return self._build_admin_access_check_response(phone_number=phone_number, user=existing_user)
            session.step = 'admin_awaiting_name' if session.admin_action in {'create', 'rename'} else 'admin_awaiting_role'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if session.admin_action == 'create':
                return flow.OutgoingMessage(text=f'Numero recebido: {phone_number}\nAgora me envie o nome desse usuario.\nSe preferir deixar sem nome, envie PULAR.')
            if session.admin_action == 'rename':
                return flow.OutgoingMessage(text=f"Numero recebido: {phone_number}\nNome atual: {session.current_name or '-'}\nAgora me envie o novo nome desse usuario.\nSe preferir deixar sem nome, envie PULAR.")
            return self._build_role_menu(phone_number=phone_number, session=session)
        if session.step == 'admin_awaiting_name':
            if normalized in {'pular', 'sem nome', 'nao informar', 'nao_informar'}:
                session.target_name = ''
            else:
                target_name = flow._normalize_admin_name(text)
                if not target_name:
                    self.sessions[sender] = session
                    return flow.OutgoingMessage(text='Nao consegui entender o nome.\nMe envie o nome do usuario ou digite PULAR.')
                session.target_name = target_name
            session.step = 'admin_confirming' if session.admin_action == 'rename' else 'admin_awaiting_role'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            if session.admin_action == 'rename':
                return self._build_admin_confirmation(session)
            return self._build_role_menu(phone_number=session.target_phone, session=session)
        if session.step == 'admin_awaiting_role':
            role_name = flow._parse_admin_role(normalized)
            if not role_name:
                self.sessions[sender] = session
                return self._build_role_menu(phone_number=session.target_phone, session=session, invalid_selection=True)
            session.target_role = role_name
            session.target_sectors = ()
            session.target_gv_vdes = ()
            if role_name == flow.ROLE_ADMIN:
                session.step = 'admin_confirming'
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_admin_confirmation(session)
            session.step = 'admin_awaiting_scope'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(text=self._build_scope_prompt(role_name))
        if session.step == 'admin_awaiting_scope':
            scope_codes, scope_error = self._resolve_admin_scope_codes(text=text, role_name=session.target_role)
            if scope_error is not None:
                self.sessions[sender] = session
                return flow.OutgoingMessage(text=scope_error)
            if session.target_role == flow.ROLE_VENDEDOR:
                session.target_sectors = tuple(scope_codes)
                session.target_gv_vdes = ()
            elif session.target_role == flow.ROLE_FINANCEIRO:
                session.target_sectors = tuple(scope_codes)
                session.target_gv_vdes = ()
            elif session.target_role in {flow.ROLE_GERENTE_VENDAS, flow.ROLE_DIRETOR_COMERCIAL}:
                session.target_sectors = ()
                session.target_gv_vdes = tuple(scope_codes)
            session.step = 'admin_confirming'
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_admin_confirmation(session)
        if session.step == 'admin_confirming':
            if normalized in {flow.ADMIN_CONFIRM, '1', 'confirmar', 'salvar'}:
                try:
                    user = self.access_control.upsert_user(phone_number=session.target_phone, name=session.target_name or None, is_active=True, roles=list(session.current_roles) if session.admin_action == 'rename' else [session.target_role], sectors=list(session.current_sectors) if session.admin_action == 'rename' else list(session.target_sectors), gv_vdes=list(session.current_gv_vdes) if session.admin_action == 'rename' else list(session.target_gv_vdes))
                except ValueError as exc:
                    self._reset_session(sender)
                    return flow.OutgoingMessage(text=f'{str(exc).strip()}\nSe quiser tentar novamente, envie MENU.')
                except RuntimeError:
                    self._reset_session(sender)
                    return flow.OutgoingMessage(text='Nao consegui salvar agora.\nTente novamente em instantes.')
                action_text = 'Cadastro concluido' if session.admin_action == 'create' else 'Nome atualizado' if session.admin_action == 'rename' else 'Alteracao concluida'
                self._reset_session(sender)
                scope_text = self._format_user_access_label(roles=tuple((str(item) for item in user.get('roles', []))), sectors=tuple((str(item) for item in user.get('sectors', []))), gv_vdes=tuple((str(item) for item in user.get('gv_vdes', []))))
                return flow.OutgoingMessage(text=f"{action_text} com sucesso.\nNome: {user['name'] or '-'}\nNumero: {user['phone_number']}\nCargo: {(self._display_role(user['roles'][0]) if user['roles'] else '-')}\nAcesso: {scope_text}\nSe quiser continuar, envie MENU.")
            if normalized in {flow.ADMIN_CANCEL, '2', 'cancelar'}:
                self._reset_session(sender)
                return self._build_main_menu(decision)
            self.sessions[sender] = session
            return self._build_admin_confirmation(session)
        self._reset_session(sender)
        return self._build_main_menu(decision)

    def _build_admin_action_menu(self, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = 'O que voce deseja fazer?'
        if invalid_selection:
            text = flow._invalid_option_text('O que voce deseja fazer?')
        return flow.OutgoingMessage(kind='menu', title='Acessos', text=text, footer='Cada usuario deve ter um unico cargo. Vendedor usa filial-setor. Gerente de Vendas usa filial-GV. Diretor Comercial usa filial-DC. Financeiro e admin nao usam escopo comercial.', button_text='Escolher', options=(flow.InteractiveOption(option_id=flow.ADMIN_ACTION_CREATE, title='Cadastrar usuario', description='Adicionar um novo numero', shortcut='1'), flow.InteractiveOption(option_id=flow.ADMIN_ACTION_UPDATE, title='Alterar acesso', description='Mudar o acesso de um numero', shortcut='2'), flow.InteractiveOption(option_id=flow.ADMIN_ACTION_LIST, title='Listar usuarios', description='Ver numeros e cargos', shortcut='3'), flow.InteractiveOption(option_id=flow.ADMIN_ACTION_RENAME, title='Alterar nome', description='Atualizar o nome de um numero', shortcut='4'), flow.InteractiveOption(option_id=flow.ADMIN_ACTION_SUMMARY, title='Resumo Operacional', description='Ver cargos e usuarios ativos', shortcut='5'), flow.InteractiveOption(option_id=flow.ADMIN_ACTION_HEALTH, title='Saude do Sistema', description='Ver o status das bases e acessos', shortcut='6'), flow.InteractiveOption(option_id=flow.ADMIN_ACTION_CHECK, title='Validar Acesso', description='Conferir o acesso de um numero', shortcut='7')))

    def _build_admin_summary_response(self, users: list[dict[str, Any]]) -> OutgoingMessage:
        flow = _customer_flow_module()
        total_users = len(users)
        active_users = sum((1 for user in users if bool(user.get('is_active'))))
        inactive_users = total_users - active_users
        role_totals = {flow.ROLE_ADMIN: 0, flow.ROLE_FINANCEIRO: 0, flow.ROLE_GERENTE_VENDAS: 0, flow.ROLE_DIRETOR_COMERCIAL: 0, flow.ROLE_VENDEDOR: 0}
        out_of_policy = 0
        for user in users:
            roles = [str(item) for item in user.get('roles', []) if str(item).strip()]
            sectors = [str(item) for item in user.get('sectors', []) if str(item).strip()]
            gv_vdes = [str(item) for item in user.get('gv_vdes', []) if str(item).strip()]
            for role_name in roles:
                if role_name in role_totals:
                    role_totals[role_name] += 1
            if len(roles) != 1:
                out_of_policy += 1
                continue
            role_name = roles[0]
            has_invalid_sector_scope = any((not flow.normalize_sector_scope_input(value) for value in sectors))
            has_invalid_filial_scope = any((not flow.normalize_filial_scope_input(value) for value in sectors))
            has_invalid_gv_scope = any((not flow.normalize_gv_scope_input(value) for value in gv_vdes))
            has_invalid_dc_scope = any((not flow.normalize_dc_scope_input(value) for value in gv_vdes))
            if role_name == flow.ROLE_ADMIN and (sectors or gv_vdes):
                out_of_policy += 1
            elif role_name == flow.ROLE_FINANCEIRO and (gv_vdes or not sectors or has_invalid_filial_scope):
                out_of_policy += 1
            elif role_name == flow.ROLE_GERENTE_VENDAS and (sectors or not gv_vdes or has_invalid_gv_scope):
                out_of_policy += 1
            elif role_name == flow.ROLE_DIRETOR_COMERCIAL and (sectors or not gv_vdes or has_invalid_dc_scope):
                out_of_policy += 1
            elif role_name == flow.ROLE_VENDEDOR and (gv_vdes or not sectors or has_invalid_sector_scope):
                out_of_policy += 1
        lines = ['Resumo operacional', '', f'*Usuarios cadastrados:* {total_users}', f'*Usuarios ativos:* {active_users}', f'*Usuarios inativos:* {inactive_users}', '', f'*Admins:* {role_totals[flow.ROLE_ADMIN]}', f'*Financeiro:* {role_totals[flow.ROLE_FINANCEIRO]}', f'*Gerentes de Vendas:* {role_totals[flow.ROLE_GERENTE_VENDAS]}', f'*Diretores Comerciais:* {role_totals[flow.ROLE_DIRETOR_COMERCIAL]}', f'*Vendedores:* {role_totals[flow.ROLE_VENDEDOR]}', '', f'*Cadastros fora da politica atual:* {out_of_policy}', '', 'Se quiser continuar, envie MENU.']
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_admin_health_response(self) -> OutgoingMessage:
        flow = _customer_flow_module()
        access_status = self.access_control.status()
        clients_status = self.query_service.status()
        inad_status = self.inadimplencia_service.status()
        comod_status = self.comodatos_service.status()
        lines = ['Saude do sistema', '', f"*RBAC:* {flow._format_health_status(access_status.get('ready', False))}", f"*Base de clientes:* {flow._format_health_status(clients_status.get('ready', False))}", f"*Inadimplencia:* {flow._format_health_status(inad_status.get('ready', False))}", f"*Comodatos:* {flow._format_health_status(comod_status.get('ready', False))}"]
        errors = [('RBAC', access_status.get('last_error')), ('Clientes', clients_status.get('last_error')), ('Inadimplencia', inad_status.get('last_error')), ('Comodatos', comod_status.get('last_error'))]
        visible_errors = [(label, str(message).strip()) for label, message in errors if str(message or '').strip()]
        if visible_errors:
            lines.append('')
            lines.append('Detalhes:')
            for label, message in visible_errors:
                lines.append(f'{label}: {message}')
        lines.append('')
        lines.append('Se quiser continuar, envie MENU.')
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_admin_access_check_response(self, phone_number: str, user: dict[str, Any] | None) -> OutgoingMessage:
        flow = _customer_flow_module()
        client_decision = self.access_control.authorize(phone_number=phone_number, area='cliente')
        inad_decision = self.access_control.authorize(phone_number=phone_number, area='inadimplencia')
        comodato_decision = self.access_control.authorize(phone_number=phone_number, area='comodato')
        roles = tuple((str(item) for item in (user or {}).get('roles', [])))
        sectors = tuple((str(item) for item in (user or {}).get('sectors', [])))
        gv_vdes = tuple((str(item) for item in (user or {}).get('gv_vdes', [])))
        active_label = 'Sim' if bool((user or {}).get('is_active')) else 'Nao'
        lines = ['Validacao de acesso', '', f'Numero: {phone_number}', f"Nome: {str((user or {}).get('name') or '-').strip() or '-'}"]
        if user is None:
            lines.append('Cadastro: numero nao encontrado')
        else:
            lines.append(f'Ativo: {active_label}')
            lines.append(f'Cargo: {flow._format_roles(roles)}')
            lines.append(f'Acesso comercial: {self._format_user_access_label(roles, sectors, gv_vdes)}')
        lines.append('')
        lines.append(f'Cliente: {flow._format_access_decision_label(client_decision)}')
        lines.append(f'Inadimplencia: {flow._format_access_decision_label(inad_decision)}')
        lines.append(f'Comodatos: {flow._format_access_decision_label(comodato_decision)}')
        lines.append(f"Visitas do dia: {('liberado' if self._can_use_visit_menu(client_decision) else 'bloqueado')}")
        lines.append(f"Menu financeiro: {('liberado' if self._can_use_finance_menu(client_decision) else 'bloqueado')}")
        lines.append(f"Menu admin: {('liberado' if self._is_admin(client_decision) else 'bloqueado')}")
        lines.append('')
        lines.append('Se quiser continuar, envie MENU.')
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _build_role_menu(self, phone_number: str, session: LookupSession, invalid_selection: bool=False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if session.admin_action == 'update':
            lines.append(f'Encontrei este numero: {phone_number}')
            lines.append(f"Nome atual: {session.current_name or '-'}")
            lines.append(f'Cargo atual: {flow._format_roles(session.current_roles)}')
            if flow.ROLE_FINANCEIRO in session.current_roles:
                lines.append(f'Filiais atuais: {flow._format_finance_filiais(session.current_sectors)}')
            else:
                lines.append(f'Setor atual: {flow._format_sectors(session.current_sectors)}')
            lines.append(f'Escopo atual de gestao: {flow._format_gv_vdes(session.current_gv_vdes, role_name=flow._primary_role(session.current_roles))}')
        else:
            lines.append(f'Numero recebido: {phone_number}')
            lines.append(f"Nome: {session.target_name or '-'}")
        if invalid_selection:
            lines.append('Nao entendi essa opcao.')
        lines.append('Escolha o cargo desse usuario.')
        return flow.OutgoingMessage(kind='menu', title='Cargo do Usuario', text='\n'.join(lines), footer='Escolha um unico cargo. Vendedor usa filial-setor. GV usa filial-GV. DC usa filial-DC. Financeiro usa apenas filiais. Admin tem acesso total.', button_text='Escolher', options=(flow.InteractiveOption(option_id=flow.ADMIN_ROLE_VENDEDOR, title='Vendedor', description='Consulta clientes da propria chave filial-setor', shortcut='1'), flow.InteractiveOption(option_id=flow.ADMIN_ROLE_GERENTE_VENDAS, title='Gerente de Vendas', description='Consulta a base do proprio GV em todas as revendas', shortcut='2'), flow.InteractiveOption(option_id=flow.ADMIN_ROLE_ADMIN, title='Admin', description='Acesso completo', shortcut='3'), flow.InteractiveOption(option_id=flow.ADMIN_ROLE_FINANCEIRO, title='Financeiro', description='Consulta as filiais liberadas', shortcut='4'), flow.InteractiveOption(option_id=flow.ADMIN_ROLE_DIRETOR_COMERCIAL, title='Diretor Comercial', description='Acompanha todos os gerentes sob responsabilidade', shortcut='5')))

    def _build_admin_confirmation(self, session: LookupSession) -> OutgoingMessage:
        flow = _customer_flow_module()
        if session.admin_action == 'create':
            action_title = 'Confirmar Cadastro'
            action_label = 'Cadastrar usuario'
        elif session.admin_action == 'rename':
            action_title = 'Confirmar Nome'
            action_label = 'Alterar nome'
        else:
            action_title = 'Confirmar Alteracao'
            action_label = 'Alterar acesso'
        lines = [f'Acao: {action_label}', f'Numero: {session.target_phone}']
        if session.admin_action == 'rename':
            lines.append(f"Nome atual: {session.current_name or '-'}")
            lines.append(f"Novo nome: {session.target_name or '-'}")
            lines.append(f'Cargo atual: {flow._format_roles(session.current_roles)}')
            lines.append(f'Acesso atual: {self._format_user_access_label(session.current_roles, session.current_sectors, session.current_gv_vdes)}')
        else:
            lines.append(f"Nome: {session.target_name or '-'}")
        if session.admin_action != 'rename' and (session.current_roles or session.current_sectors or session.current_gv_vdes):
            lines.append(f'Cargo atual: {flow._format_roles(session.current_roles)}')
            if flow.ROLE_FINANCEIRO in session.current_roles:
                lines.append(f'Filiais atuais: {flow._format_finance_filiais(session.current_sectors)}')
            else:
                lines.append(f'Setor atual: {flow._format_sectors(session.current_sectors)}')
            lines.append(f'Escopo atual de gestao: {flow._format_gv_vdes(session.current_gv_vdes, role_name=flow._primary_role(session.current_roles))}')
        if session.admin_action != 'rename':
            lines.append(f'Novo cargo: {self._display_role(session.target_role)}')
            if session.target_role == flow.ROLE_VENDEDOR:
                lines.append(f'Novo setor: {flow._format_sectors(session.target_sectors)}')
            elif session.target_role == flow.ROLE_GERENTE_VENDAS:
                lines.append(f'Novo acesso por GV: {flow._format_gv_vdes(session.target_gv_vdes, role_name=flow.ROLE_GERENTE_VENDAS)}')
            elif session.target_role == flow.ROLE_DIRETOR_COMERCIAL:
                lines.append(f'Novos DCs sob responsabilidade: {flow._format_gv_vdes(session.target_gv_vdes, role_name=flow.ROLE_DIRETOR_COMERCIAL)}')
            elif session.target_role == flow.ROLE_FINANCEIRO:
                lines.append(f'Novas filiais: {flow._format_finance_filiais(session.target_sectors)}')
            else:
                lines.append('Novo acesso: acesso completo')
        lines.append('')
        lines.append('Se estiver tudo certo, confirme.')
        return flow.OutgoingMessage(kind='menu', title=action_title, text='\n'.join(lines), footer='Escolha Confirmar para salvar.', button_text='Revisar', options=(flow.InteractiveOption(option_id=flow.ADMIN_CONFIRM, title='Confirmar', description='Salvar alteracoes', shortcut='1'), flow.InteractiveOption(option_id=flow.ADMIN_CANCEL, title='Cancelar', description='Voltar sem salvar', shortcut='2')))

    def _build_admin_users_list_response(self, users: list[dict[str, Any]]) -> OutgoingMessage:
        flow = _customer_flow_module()
        if not users:
            return flow.OutgoingMessage(text='Nao encontrei usuarios cadastrados.\nSe quiser continuar, envie MENU.')
        visible_users = users[:50]
        lines = [f'Usuarios cadastrados: {len(users)}']
        if len(users) > len(visible_users):
            lines.append(f'Mostrando os primeiros {len(visible_users)}.')
        for index, user in enumerate(visible_users, start=1):
            name = str(user.get('name') or '').strip() or 'Sem nome'
            phone_number = str(user.get('phone_number') or '-')
            is_active = bool(user.get('is_active'))
            roles = tuple((str(item) for item in user.get('roles', [])))
            sectors = tuple((str(item) for item in user.get('sectors', [])))
            gv_vdes = tuple((str(item) for item in user.get('gv_vdes', [])))
            role_label = ', '.join((self._display_role(role_name) for role_name in roles)) if roles else '-'
            access_label = self._format_user_access_label(roles=roles, sectors=sectors, gv_vdes=gv_vdes)
            lines.append(f'{index}. {name} | {phone_number}')
            lines.append(f"Cargo: {role_label} | Ativo: {('Sim' if is_active else 'Nao')} | Acesso: {access_label}")
        lines.append('')
        lines.append('Se quiser continuar, envie MENU.')
        return flow.OutgoingMessage(text='\n'.join(lines))

    def _display_role(self, role_name: str) -> str:
        flow = _customer_flow_module()
        return {flow.ROLE_VENDEDOR: 'Vendedor', flow.ROLE_GERENTE_VENDAS: 'Gerente de Vendas', flow.ROLE_DIRETOR_COMERCIAL: 'Diretor Comercial', flow.ROLE_ADMIN: 'Admin', flow.ROLE_FINANCEIRO: 'Financeiro'}.get(role_name, role_name.title())

    def _build_scope_prompt(self, role_name: str) -> str:
        flow = _customer_flow_module()
        if role_name == flow.ROLE_GERENTE_VENDAS:
            return f'Cargo {self._display_role(role_name)} selecionado.\nAgora me envie o numero do GV ou varios numeros separados por virgula.\nExemplo: 2 ou 2,5'
        if role_name == flow.ROLE_DIRETOR_COMERCIAL:
            return f'Cargo {self._display_role(role_name)} selecionado.\nAgora me envie a chave filial-DC ou varias chaves separadas por virgula.\nExemplo: 3-1 ou 3-1,4-1'
        if role_name == flow.ROLE_FINANCEIRO:
            return f'Cargo {self._display_role(role_name)} selecionado.\nAgora me envie a filial ou varias filiais separadas por virgula.\nExemplo: 3 ou 3,4'
        return f'Cargo {self._display_role(role_name)} selecionado.\nAgora me envie a chave filial-setor ou as chaves separadas por virgula.\nExemplo: 1-206 ou 1-206,3-107'

    def _build_scope_retry_prompt(self, role_name: str) -> str:
        flow = _customer_flow_module()
        if role_name == flow.ROLE_GERENTE_VENDAS:
            return 'Para esse cargo, preciso de pelo menos um numero de GV valido.\nEnvie nesse formato: 2 ou 2,5'
        if role_name == flow.ROLE_DIRETOR_COMERCIAL:
            return 'Para esse cargo, preciso de pelo menos uma chave filial-DC valida.\nEnvie nesse formato: 3-1 ou 3-1,4-1'
        if role_name == flow.ROLE_FINANCEIRO:
            return 'Para esse cargo, preciso de pelo menos uma filial valida.\nEnvie nesse formato: 3 ou 3,4'
        return 'Para esse cargo, preciso de pelo menos uma chave filial-setor valida.\nEnvie nesse formato: 1-206 ou 1-206,3-107'

    def _build_scope_not_found_prompt(self, role_name: str, codes: list[str]) -> str:
        flow = _customer_flow_module()
        joined_codes = ', '.join(codes) if codes else '-'
        if role_name == flow.ROLE_GERENTE_VENDAS:
            return f'Nao encontrei base para o(s) GV(s): {joined_codes}.\nConfira os numeros e envie novamente.\nExemplo: 2 ou 2,5'
        if role_name == flow.ROLE_DIRETOR_COMERCIAL:
            joined_codes = flow._format_gv_vdes(tuple(codes), role_name=flow.ROLE_DIRETOR_COMERCIAL) if codes else '-'
            return f'Nao encontrei base para o(s) diretor(es): {joined_codes}.\nConfira as chaves e envie novamente.\nExemplo: 3-1 ou 3-1,4-1'
        if role_name == flow.ROLE_FINANCEIRO:
            return self._build_scope_retry_prompt(role_name)
        return self._build_scope_retry_prompt(role_name)

    def _resolve_admin_scope_codes(self, text: str, role_name: str) -> tuple[list[str], str | None]:
        flow = _customer_flow_module()
        if role_name == flow.ROLE_VENDEDOR:
            scope_codes = flow._parse_scope_code_list(text, role_name)
            if not scope_codes:
                return ([], self._build_scope_retry_prompt(role_name))
            return (scope_codes, None)
        if role_name == flow.ROLE_FINANCEIRO:
            scope_codes = flow._parse_scope_code_list(text, role_name)
            if not scope_codes:
                return ([], self._build_scope_retry_prompt(role_name))
            return (scope_codes, None)
        if role_name == flow.ROLE_DIRETOR_COMERCIAL:
            scope_codes = flow._parse_scope_code_list(text, role_name)
            if not scope_codes:
                return ([], self._build_scope_retry_prompt(role_name))
            try:
                matching_gvs = self.query_service.list_gv_vdes(allowed_gv_vdes=scope_codes, limit=1)
            except RuntimeError:
                return ([], 'Nao consegui consultar a base agora.\nTente novamente em instantes.')
            if not matching_gvs:
                return ([], self._build_scope_not_found_prompt(role_name, scope_codes))
            return (scope_codes, None)
        base_codes = flow._parse_management_scope_code_list(text)
        if not base_codes:
            return ([], self._build_scope_retry_prompt(role_name))
        try:
            if role_name == flow.ROLE_GERENTE_VENDAS:
                scope_codes = self.query_service.expand_gv_scope_codes(base_codes)
            else:
                return ([], self._build_scope_retry_prompt(role_name))
        except RuntimeError:
            return ([], 'Nao consegui consultar a base agora.\nTente novamente em instantes.')
        if not scope_codes:
            return ([], self._build_scope_not_found_prompt(role_name, base_codes))
        return (scope_codes, None)

    def _format_user_access_label(self, roles: tuple[str, ...], sectors: tuple[str, ...], gv_vdes: tuple[str, ...]) -> str:
        flow = _customer_flow_module()
        if flow.ROLE_ADMIN in roles:
            return 'acesso total'
        if flow.ROLE_FINANCEIRO in roles:
            return f'Filiais liberadas: {flow._format_finance_filiais(sectors)}'
        if flow.ROLE_DIRETOR_COMERCIAL in roles:
            return f'DCs sob responsabilidade: {flow._format_gv_vdes(gv_vdes, role_name=flow.ROLE_DIRETOR_COMERCIAL)}'
        if flow.ROLE_GERENTE_VENDAS in roles:
            return f'GVs liberados: {flow._format_gv_vdes(gv_vdes, role_name=flow.ROLE_GERENTE_VENDAS)}'
        if flow.ROLE_VENDEDOR in roles:
            return f'Setores liberados: {flow._format_sectors(sectors)}'
        return '-'
