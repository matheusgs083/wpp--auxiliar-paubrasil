from __future__ import annotations

import re
from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


PAYIP_FORM_STEPS = {
    "finance_payip_awaiting_invoice",
    "finance_payip_awaiting_client_code",
    "finance_payip_awaiting_client_code_all",
    "finance_payip_awaiting_client_filter",
    "finance_payip_create_client_awaiting_registration",
    "finance_payip_amount_day_awaiting_query",
    "finance_payip_validate_day_awaiting_query",
    "finance_payip_import_batch_awaiting_period",
    "finance_payip_import_batch_confirm",
    "finance_payip_statement_awaiting_period",
    "finance_payip_charge_awaiting_client",
    "finance_payip_charge_awaiting_amount",
    "finance_payip_charge_awaiting_due_date",
    "finance_payip_charge_confirm",
}
PAYIP_SESSION_STEPS = PAYIP_FORM_STEPS | {"finance_payip_awaiting_mfa", "finance_payip_menu"}
PAYIP_CHARGE_ATTEMPTS = 3
PAYIP_CHARGE_RETRY_DELAY_SECONDS = 1.5


class PayipFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def handle_session_if_applicable(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any | None:
        flow = _customer_flow_module()
        if session.step in PAYIP_SESSION_STEPS:
            return self.handle_session(
                sender=sender,
                session=session,
                text=text,
                normalized=normalized,
                decision=decision,
            )
        if session.step == "finance_select_action":
            request = flow._parse_hybrid_finance_request(normalized)
            if request.action == "payip":
                return self.handle_finance_action(
                    sender=sender,
                    session=session,
                    text=text,
                    normalized=normalized,
                    decision=decision,
                )
        return None

    def handle_session(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any | None:
        flow = _customer_flow_module()
        access_error = self._ensure_payip_access(sender=sender, session=session, decision=decision)
        if access_error is not None:
            return access_error
        if session.step == "finance_payip_menu":
            return self.handle_menu(sender=sender, session=session, text=text, normalized=normalized, decision=decision)
        if session.step == "finance_payip_awaiting_mfa":
            if not self._can_use_payip_menu(decision):
                self.sessions[sender] = session
                return flow.OutgoingMessage(
                    text=(
                        "Esse menu de pagamentos PayIP esta liberado apenas para financeiro e administracao.\n"
                        "Se quiser voltar, envie MENU."
                    )
                )
            mfa_code = flow._extract_mfa_code(text)
            if not mfa_code:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return flow.OutgoingMessage(
                    text=(
                        "Envie o codigo atual do Google Authenticator com 6 digitos.\n"
                        "Exemplo: 123456\n"
                        "Para voltar, envie A ou ANT."
                    )
                )
            if session.payip_pending_action == "invoice":
                return self._run_payip_invoice_search(
                    sender=sender,
                    session=session,
                    invoice=session.payip_pending_invoice,
                    filial=session.payip_pending_filial,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "pending_client":
                return self._run_payip_pending_client_search(
                    sender=sender,
                    session=session,
                    client_code=session.payip_pending_client_code,
                    filial=session.payip_pending_filial,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "client":
                return self._run_payip_client_search(
                    sender=sender,
                    session=session,
                    client_code=session.payip_pending_client_code,
                    filial=session.payip_pending_filial,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "charge_lookup":
                return self._run_payip_charge_client_lookup(
                    sender=sender,
                    session=session,
                    client_code=session.payip_pending_client_code,
                    filial=session.payip_pending_filial,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "charge_create":
                return self._run_payip_charge_create(
                    sender=sender,
                    session=session,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "statement":
                return self._run_payip_statement_resume(
                    sender=sender,
                    session=session,
                    filial=session.payip_pending_filial,
                    date_start=session.payip_pending_date_start,
                    date_end=session.payip_pending_date_end,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "amount_day":
                return self._run_payip_amount_day_search(
                    sender=sender,
                    session=session,
                    filial=session.payip_pending_filial,
                    amount=session.payip_pending_amount,
                    day=session.payip_pending_day,
                    tolerance=session.payip_pending_tolerance,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "validate_day":
                return self._run_payip_validate_day_search(
                    sender=sender,
                    session=session,
                    filial=session.payip_pending_filial,
                    day=session.payip_pending_day,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "import_batch":
                return self._run_payip_import_batch_validation(
                    sender=sender,
                    session=session,
                    filial=session.payip_pending_filial,
                    date_start=session.payip_pending_date_start,
                    date_end=session.payip_pending_date_end,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "import_batch_confirm":
                return self._run_payip_import_batch_confirmation(
                    sender=sender,
                    session=session,
                    filial=session.payip_pending_filial,
                    date_start=session.payip_pending_date_start,
                    date_end=session.payip_pending_date_end,
                    mfa_code=mfa_code,
                )
            if session.payip_pending_action == "routes":
                return self._run_payip_routes_search(
                    sender=sender,
                    session=session,
                    filial=session.payip_pending_filial,
                    mfa_code=mfa_code,
                )
            return self._run_payip_login_test(
                sender=sender,
                session=session,
                mfa_code=mfa_code,
            )

        if session.step == "finance_payip_awaiting_invoice":
            invoice = flow._extract_payip_invoice_query(text)
            if not invoice:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_invoice_prompt(invalid_selection=True)
            return self._run_payip_invoice_search(
                sender=sender,
                session=session,
                invoice=invoice,
                filial=flow._extract_payip_filial_query(text),
            )

        if session.step == "finance_payip_awaiting_client_code":
            client_code = flow._extract_payip_client_code_query(text)
            if not client_code:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_client_code_prompt(invalid_selection=True)
            filial = flow._extract_payip_filial_query(text)
            filter_action = flow._parse_payip_client_filter(normalized)
            if session.payip_pending_status == "PENDING" or filter_action == "pending":
                return self._run_payip_pending_client_search(
                    sender=sender,
                    session=session,
                    client_code=client_code,
                    filial=filial,
                )
            if filter_action == "all":
                return self._run_payip_client_search(
                    sender=sender,
                    session=session,
                    client_code=client_code,
                    filial=filial,
                )
            if session.payip_pending_status == "":
                return self._open_payip_client_filter_or_search(
                    sender=sender,
                    session=session,
                    client_code=client_code,
                    filial=filial,
                )
            return self._run_payip_pending_client_search(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )

        if session.step == "finance_payip_awaiting_client_code_all":
            client_code = flow._extract_payip_client_code_query(text)
            if not client_code:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_client_code_prompt(invalid_selection=True, pending_only=False)
            return self._run_payip_client_search(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=flow._extract_payip_filial_query(text),
            )

        if session.step == "finance_payip_awaiting_client_filter":
            filter_action = flow._parse_payip_client_filter(normalized)
            if not filter_action:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_client_filter_prompt(invalid_selection=True)
            if filter_action == "pending":
                return self._run_payip_pending_client_search(
                    sender=sender,
                    session=session,
                    client_code=session.payip_pending_client_code,
                    filial=session.payip_pending_filial,
                )
            return self._run_payip_client_search(
                sender=sender,
                session=session,
                client_code=session.payip_pending_client_code,
                filial=session.payip_pending_filial,
            )

        if session.step == "finance_payip_create_client_awaiting_registration":
            filial, client_code = self._parse_payip_filial_client_pair(text)
            if not filial or not client_code:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_create_client_prompt(invalid_selection=True)
            return self._run_payip_create_client_from_dclientes(
                sender=sender,
                session=session,
                filial=filial,
                client_code=client_code,
            )

        if session.step == "finance_payip_amount_day_awaiting_query":
            query = flow._parse_payip_amount_day_query(text)
            if not query[0] or query[1] is None or query[2] is None or query[4]:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_amount_day_prompt(invalid_selection=True)
            return self._run_payip_amount_day_search(
                sender=sender,
                session=session,
                filial=query[0],
                amount=query[1],
                day=query[2],
                tolerance=query[3],
            )

        if session.step == "finance_payip_validate_day_awaiting_query":
            query = self._parse_payip_validate_day_query(text)
            if not query[0] or query[1] is None or query[2]:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_validate_day_prompt(invalid_selection=True)
            return self._run_payip_validate_day_search(
                sender=sender,
                session=session,
                filial=query[0],
                day=query[1],
            )

        if session.step == "finance_payip_import_batch_awaiting_period":
            query = flow._parse_payip_statement_query(text)
            if not query[0] or query[3]:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_import_batch_prompt(invalid_selection=True)
            return self._run_payip_import_batch_validation(
                sender=sender,
                session=session,
                filial=query[0],
                date_start=query[1],
                date_end=query[2],
            )

        if session.step == "finance_payip_import_batch_confirm":
            mfa_code = flow._extract_mfa_code(text)
            if mfa_code:
                return self._run_payip_import_batch_confirmation(
                    sender=sender,
                    session=session,
                    filial=session.payip_pending_filial,
                    date_start=session.payip_pending_date_start,
                    date_end=session.payip_pending_date_end,
                    mfa_code=mfa_code,
                )
            if self._is_payip_import_confirm_command(normalized):
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "import_batch_confirm"
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    context=(
                        "confirmacao da importacao automatizada | "
                        f"Revenda: {flow._format_filial_label(session.payip_pending_filial)} | "
                        f"Periodo: {flow._format_display_date(session.payip_pending_date_start)} a "
                        f"{flow._format_display_date(session.payip_pending_date_end)}"
                    )
                )
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_import_batch_confirmation_prompt(session=session, invalid_selection=True)

        if session.step == "finance_payip_statement_awaiting_period":
            query = flow._parse_payip_statement_query(text)
            if not query[0] or query[3]:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_statement_prompt(invalid_selection=True)
            return self._run_payip_statement_resume(
                sender=sender,
                session=session,
                filial=query[0],
                date_start=query[1],
                date_end=query[2],
            )

        if session.step == "finance_payip_charge_awaiting_client":
            client_code = flow._extract_payip_client_code_query(text)
            filial = flow._extract_payip_filial_query(text)
            if not client_code or not filial:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_charge_client_prompt(invalid_selection=True)
            return self._run_payip_charge_client_lookup(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )

        if session.step == "finance_payip_charge_awaiting_amount":
            amount = flow._parse_payip_charge_amount(text)
            if amount is None or amount <= 0:
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_charge_amount_prompt(session=session, invalid_selection=True)
            session.payip_charge_amount = flow._decimal_cache_text(amount)
            session.step = "finance_payip_charge_awaiting_due_date"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_due_date_prompt()

        if session.step == "finance_payip_charge_awaiting_due_date":
            due_date = flow._parse_payip_charge_due_date(text)
            if due_date is None or due_date < flow.datetime.now(flow.LOCAL_TIMEZONE).date():
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_charge_due_date_prompt(invalid_selection=True)
            session.payip_charge_due_date = due_date.isoformat()
            session.step = "finance_payip_charge_confirm"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_confirmation(session=session)

        if session.step == "finance_payip_charge_confirm":
            if self._is_payip_charge_confirm_command(normalized):
                return self._run_payip_charge_create(sender=sender, session=session)
            charge_adjustment = flow._parse_payip_charge_adjustment(text)
            if charge_adjustment is not None:
                field, value = charge_adjustment
                if field == "rate":
                    session.payip_charge_rate_amount = flow._decimal_cache_text(value)
                elif field == "interest":
                    session.payip_charge_interest_perc = flow._decimal_cache_text(value)
                elif field == "due_date":
                    due_date = flow._parse_payip_charge_due_date(str(value))
                    if due_date is None or due_date < flow.datetime.now(flow.LOCAL_TIMEZONE).date():
                        session.updated_at = flow.datetime.now(flow.timezone.utc)
                        self.sessions[sender] = session
                        return self._build_payip_charge_confirmation(
                            session=session,
                            invalid_selection=True,
                            detail="Data de vencimento invalida. Use dd/mm/aaaa e uma data de hoje em diante.",
                        )
                    session.payip_charge_due_date = due_date.isoformat()
                elif field == "invoice":
                    session.payip_charge_invoice = str(value or "").strip()
                elif field == "external_id":
                    session.payip_charge_external_id = str(value or "").strip()
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_charge_confirmation(session=session)
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_confirmation(session=session, invalid_selection=True)
        return None

    def handle_post_result_request(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any | None:
        _ = text
        if not self._is_payip_missing_clients_create_command(normalized):
            return None
        if not tuple(getattr(session, "payip_import_missing_client_codes", ()) or ()):
            return None
        access_error = self._ensure_payip_access(sender=sender, session=session, decision=decision)
        if access_error is not None:
            return access_error
        return self._run_payip_create_missing_import_clients(sender=sender, session=session)

    @staticmethod
    def _is_payip_charge_confirm_command(normalized: str) -> bool:
        value = re.sub(r"[^a-z0-9 ]+", " ", str(normalized or "").lower())
        value = re.sub(r"\s+", " ", value).strip()
        if value in {
            "sim",
            "s",
            "ok",
            "confirmar",
            "confirma",
            "confirmo",
            "tentar novamente",
            "tentar de novo",
            "retry",
            "repetir",
        }:
            return True
        tokens = set(value.split())
        if {"tentar", "novamente"} <= tokens or {"tentar", "de", "novo"} <= tokens:
            return True
        return bool(tokens & {"confirmar", "confirma", "confirmo"} and tokens & {"emissao", "cobranca", "payip"})

    @staticmethod
    def _is_payip_import_confirm_command(normalized: str) -> bool:
        value = re.sub(r"[^a-z0-9 ]+", " ", str(normalized or "").lower())
        value = re.sub(r"\s+", " ", value).strip()
        if value in {
            "confirmar importacao",
            "confirmar importacao payip",
            "confirmar cobrancas",
            "confirmar cobrancas payip",
            "emitir importacao",
            "importar agora",
        }:
            return True
        tokens = set(value.split())
        return bool(tokens & {"confirmar", "confirma", "confirmo", "emitir"} and tokens & {"importacao", "cobrancas", "payip"})

    @staticmethod
    def _is_payip_missing_clients_create_command(normalized: str) -> bool:
        value = re.sub(r"[^a-z0-9 ]+", " ", str(normalized or "").lower())
        value = re.sub(r"\s+", " ", value).strip()
        if value in {
            "criar clientes payip",
            "criar clientes",
            "criar todos",
            "cadastrar clientes payip",
            "cadastrar clientes",
            "criar nbs",
        }:
            return True
        tokens = set(value.split())
        return bool(tokens & {"criar", "cadastrar"} and tokens & {"clientes", "nbs", "todos"} and ("payip" in tokens or "todos" in tokens))

    def handle_finance_action(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        flow = _customer_flow_module()
        access_error = self._ensure_payip_access(sender=sender, session=session, decision=decision)
        if access_error is not None:
            return access_error
        if not self._can_use_payip_menu(decision):
            self.sessions[sender] = session
            return flow.OutgoingMessage(
                text=(
                    "Esse menu de pagamentos PayIP esta liberado apenas para financeiro e administracao.\n"
                    "Se quiser voltar, envie MENU."
                )
        )
        payip_action = flow._parse_payip_action(normalized)
        statement_query = flow._parse_payip_statement_query(text)
        amount_day_query = flow._parse_payip_amount_day_query(text)
        validate_day_query = self._parse_payip_validate_day_query(text)
        import_batch_query = flow._parse_payip_statement_query(text)
        routes_filial = self._parse_payip_routes_query(text)
        create_client_filial, create_client_code = self._parse_payip_filial_client_pair(text)
        if payip_action == "routes" and routes_filial:
            return self._run_payip_routes_search(
                sender=sender,
                session=session,
                filial=routes_filial,
            )
        if payip_action == "routes":
            session.step = "finance_payip_menu"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_routes_prompt(invalid_selection=normalized not in {flow.PAYIP_ACTION_ROUTES, "11"})
        if payip_action == "create_client" and create_client_filial and create_client_code:
            return self._run_payip_create_client_from_dclientes(
                sender=sender,
                session=session,
                filial=create_client_filial,
                client_code=create_client_code,
            )
        if payip_action == "import_batch" and import_batch_query[0] and not import_batch_query[3]:
            return self._run_payip_import_batch_validation(
                sender=sender,
                session=session,
                filial=import_batch_query[0],
                date_start=import_batch_query[1],
                date_end=import_batch_query[2],
            )
        if payip_action == "validate_day" and validate_day_query[0] and validate_day_query[1] is not None and not validate_day_query[2]:
            return self._run_payip_validate_day_search(
                sender=sender,
                session=session,
                filial=validate_day_query[0],
                day=validate_day_query[1],
            )
        if payip_action == "amount_day" and amount_day_query[0] and amount_day_query[1] is not None and amount_day_query[2] is not None and not amount_day_query[4]:
            return self._run_payip_amount_day_search(
                sender=sender,
                session=session,
                filial=amount_day_query[0],
                amount=amount_day_query[1],
                day=amount_day_query[2],
                tolerance=amount_day_query[3],
            )
        if not payip_action and amount_day_query[0] and amount_day_query[1] is not None and amount_day_query[2] is not None and not amount_day_query[4]:
            return self._run_payip_amount_day_search(
                sender=sender,
                session=session,
                filial=amount_day_query[0],
                amount=amount_day_query[1],
                day=amount_day_query[2],
                tolerance=amount_day_query[3],
            )
        if payip_action == "statement" and statement_query[0] and not statement_query[3]:
            return self._run_payip_statement_resume(
                sender=sender,
                session=session,
                filial=statement_query[0],
                date_start=statement_query[1],
                date_end=statement_query[2],
            )
        session.step = "finance_payip_menu"
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_payip_menu()

    def handle_menu(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        flow = _customer_flow_module()
        if not self._can_use_payip_menu(decision):
            self.sessions[sender] = session
            return flow.OutgoingMessage(
                text=(
                    "Esse menu de pagamentos PayIP esta liberado apenas para financeiro e administracao.\n"
                    "Se quiser voltar, envie MENU."
                )
            )
        action = flow._parse_payip_action(normalized)
        invoice = flow._extract_payip_invoice_query(text)
        client_code = flow._extract_payip_client_code_query(text)
        filial = flow._extract_payip_filial_query(text)
        statement_query = flow._parse_payip_statement_query(text)
        amount_day_query = flow._parse_payip_amount_day_query(text)
        validate_day_query = self._parse_payip_validate_day_query(text)
        import_batch_query = flow._parse_payip_statement_query(text)
        create_client_filial, create_client_code = self._parse_payip_filial_client_pair(text)
        routes_filial = self._parse_payip_routes_query(text)
        if action == "routes" and routes_filial:
            return self._run_payip_routes_search(
                sender=sender,
                session=session,
                filial=routes_filial,
            )
        if action == "routes":
            session.step = "finance_payip_menu"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_routes_prompt(invalid_selection=normalized not in {flow.PAYIP_ACTION_ROUTES, "11"})
        if action == "create_client" and create_client_filial and create_client_code and normalized not in {flow.PAYIP_ACTION_CREATE_CLIENT, "10"}:
            return self._run_payip_create_client_from_dclientes(
                sender=sender,
                session=session,
                filial=create_client_filial,
                client_code=create_client_code,
            )
        if action == "import_batch" and import_batch_query[0] and not import_batch_query[3] and normalized not in {flow.PAYIP_ACTION_IMPORT_BATCH, "9"}:
            return self._run_payip_import_batch_validation(
                sender=sender,
                session=session,
                filial=import_batch_query[0],
                date_start=import_batch_query[1],
                date_end=import_batch_query[2],
            )
        if action == "validate_day" and validate_day_query[0] and validate_day_query[1] is not None and not validate_day_query[2] and normalized not in {flow.PAYIP_ACTION_VALIDATE_DAY, "8"}:
            return self._run_payip_validate_day_search(
                sender=sender,
                session=session,
                filial=validate_day_query[0],
                day=validate_day_query[1],
            )
        if action == "amount_day" and amount_day_query[0] and amount_day_query[1] is not None and amount_day_query[2] is not None and not amount_day_query[4] and normalized not in {flow.PAYIP_ACTION_AMOUNT_DAY, "7"}:
            return self._run_payip_amount_day_search(
                sender=sender,
                session=session,
                filial=amount_day_query[0],
                amount=amount_day_query[1],
                day=amount_day_query[2],
                tolerance=amount_day_query[3],
            )
        if action == "invoice" and invoice and normalized not in {flow.PAYIP_ACTION_SEARCH_INVOICE, "1", "3"}:
            return self._run_payip_invoice_search(
                sender=sender,
                session=session,
                invoice=invoice,
                filial=filial,
            )
        if action == "pending_client" and client_code and normalized not in {flow.PAYIP_ACTION_PENDING_CLIENT, "4"}:
            return self._run_payip_pending_client_search(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )
        if action == "client" and client_code and normalized not in {flow.PAYIP_ACTION_CLIENT, "2", "5"}:
            filter_action = flow._parse_payip_client_filter(normalized)
            if filter_action == "pending":
                return self._run_payip_pending_client_search(
                    sender=sender,
                    session=session,
                    client_code=client_code,
                    filial=filial,
                )
            if filter_action == "all":
                return self._run_payip_client_search(
                    sender=sender,
                    session=session,
                    client_code=client_code,
                    filial=filial,
                )
            return self._open_payip_client_filter_or_search(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )
        if action == "create_charge" and client_code and normalized not in {flow.PAYIP_ACTION_CREATE_CHARGE, "5"}:
            return self._run_payip_charge_client_lookup(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )
        if action == "statement" and statement_query[0] and not statement_query[3] and normalized not in {flow.PAYIP_ACTION_STATEMENT, "6"}:
            return self._run_payip_statement_resume(
                sender=sender,
                session=session,
                filial=statement_query[0],
                date_start=statement_query[1],
                date_end=statement_query[2],
            )
        if not action and amount_day_query[0] and amount_day_query[1] is not None and amount_day_query[2] is not None and not amount_day_query[4]:
            return self._run_payip_amount_day_search(
                sender=sender,
                session=session,
                filial=amount_day_query[0],
                amount=amount_day_query[1],
                day=amount_day_query[2],
                tolerance=amount_day_query[3],
            )
        if not action and validate_day_query[0] and validate_day_query[1] is not None and not validate_day_query[2]:
            return self._run_payip_validate_day_search(
                sender=sender,
                session=session,
                filial=validate_day_query[0],
                day=validate_day_query[1],
            )
        if not action and import_batch_query[0] and import_batch_query[1] is not None and import_batch_query[2] is not None and not import_batch_query[3]:
            return self._run_payip_import_batch_validation(
                sender=sender,
                session=session,
                filial=import_batch_query[0],
                date_start=import_batch_query[1],
                date_end=import_batch_query[2],
            )
        if not action and invoice:
            return self._run_payip_invoice_search(
                sender=sender,
                session=session,
                invoice=invoice,
                filial=filial,
            )
        if not action and client_code:
            return self._open_payip_client_filter_or_search(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )
        if not action:
            self.sessions[sender] = session
            return self._build_payip_menu(invalid_selection=True)
        if action == "status":
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_payip_status_response(),
                return_menu="finance_payip_menu",
            )
        if action == "pix":
            if not session.payip_pix_payloads:
                self.sessions[sender] = session
                return flow.OutgoingMessage(
                    text=(
                        "Ainda nao tenho PIX salvo nesta conversa.\n"
                        "Faça uma busca PayIP primeiro e depois envie PIX 1."
                    )
                )
            return flow._build_payip_pix_code_response(
                session.payip_pix_payloads,
                selection=1,
                payip_payments_service=self.payip_payments_service,
            )
        if action == "create_charge":
            session.step = "finance_payip_charge_awaiting_client"
            session.payip_pending_status = ""
            session.payip_pending_action = ""
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
            self.sessions[sender] = session
            return self._build_payip_charge_client_prompt()
        if action == "create_client":
            if create_client_filial and create_client_code:
                return self._run_payip_create_client_from_dclientes(
                    sender=sender,
                    session=session,
                    filial=create_client_filial,
                    client_code=create_client_code,
                )
            session.step = "finance_payip_create_client_awaiting_registration"
            session.payip_pending_action = ""
            session.payip_pending_client_code = ""
            session.payip_pending_filial = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_create_client_prompt()
        if action == "amount_day":
            if amount_day_query[0] and amount_day_query[1] is not None and amount_day_query[2] is not None and not amount_day_query[4]:
                return self._run_payip_amount_day_search(
                    sender=sender,
                    session=session,
                    filial=amount_day_query[0],
                    amount=amount_day_query[1],
                    day=amount_day_query[2],
                    tolerance=amount_day_query[3],
                )
            session.step = "finance_payip_amount_day_awaiting_query"
            session.payip_pending_action = ""
            session.payip_pending_filial = ""
            session.payip_pending_amount = ""
            session.payip_pending_day = ""
            session.payip_pending_tolerance = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_amount_day_prompt(invalid_selection=amount_day_query[4])
        if action == "validate_day":
            if validate_day_query[0] and validate_day_query[1] is not None and not validate_day_query[2]:
                return self._run_payip_validate_day_search(
                    sender=sender,
                    session=session,
                    filial=validate_day_query[0],
                    day=validate_day_query[1],
                )
            session.step = "finance_payip_validate_day_awaiting_query"
            session.payip_pending_action = ""
            session.payip_pending_filial = ""
            session.payip_pending_day = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_validate_day_prompt(invalid_selection=validate_day_query[2])
        if action == "import_batch":
            if import_batch_query[0] and not import_batch_query[3]:
                return self._run_payip_import_batch_validation(
                    sender=sender,
                    session=session,
                    filial=import_batch_query[0],
                    date_start=import_batch_query[1],
                    date_end=import_batch_query[2],
                )
            session.step = "finance_payip_import_batch_awaiting_period"
            session.payip_pending_action = ""
            session.payip_pending_filial = ""
            session.payip_pending_date_start = ""
            session.payip_pending_date_end = ""
            session.payip_import_missing_client_codes = ()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_import_batch_prompt(invalid_selection=import_batch_query[3])
        if action == "statement":
            if normalized in {flow.PAYIP_ACTION_STATEMENT, "6"}:
                session.step = "finance_payip_statement_awaiting_period"
                session.payip_pending_action = ""
                session.payip_pending_filial = ""
                session.payip_pending_date_start = ""
                session.payip_pending_date_end = ""
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_statement_prompt()
            if statement_query[0] and not statement_query[3]:
                return self._run_payip_statement_resume(
                    sender=sender,
                    session=session,
                    filial=statement_query[0],
                    date_start=statement_query[1],
                    date_end=statement_query[2],
                )
            session.step = "finance_payip_statement_awaiting_period"
            session.payip_pending_action = ""
            session.payip_pending_filial = ""
            session.payip_pending_date_start = ""
            session.payip_pending_date_end = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_statement_prompt(invalid_selection=statement_query[3])
        if action == "invoice":
            session.step = "finance_payip_awaiting_invoice"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_invoice_prompt()
        if action == "pending_client" and client_code:
            return self._run_payip_pending_client_search(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )
        if action == "pending_client":
            session.step = "finance_payip_awaiting_client_code"
            session.payip_pending_status = "PENDING"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(pending_only=True)
        if action == "client" and client_code and normalized not in {flow.PAYIP_ACTION_CLIENT, "2", "5"}:
            filter_action = flow._parse_payip_client_filter(normalized)
            if filter_action == "pending":
                return self._run_payip_pending_client_search(
                    sender=sender,
                    session=session,
                    client_code=client_code,
                    filial=filial,
                )
            if filter_action == "all":
                return self._run_payip_client_search(
                    sender=sender,
                    session=session,
                    client_code=client_code,
                    filial=filial,
                )
            return self._open_payip_client_filter_or_search(
                sender=sender,
                session=session,
                client_code=client_code,
                filial=filial,
            )
        if action == "client":
            session.step = "finance_payip_awaiting_client_code"
            session.payip_pending_status = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(pending_only=None)
        return self._run_payip_login_test(
            sender=sender,
            session=session,
        )

    def _build_payip_menu(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        text = "O que voce quer consultar na PayIP?"
        if invalid_selection:
            text = flow._invalid_option_text("Escolha uma opcao da PayIP.")
        options: list[flow.InteractiveOption] = [
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_SEARCH_INVOICE,
                title="Buscar Nota Fiscal",
                description="Buscar pagamento pela NF",
                shortcut="1",
            ),
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_CLIENT,
                title="Buscar por NB",
                description="Consultar pendentes ou todos",
                shortcut="2",
            ),
        ]
        options.append(
            flow.InteractiveOption(
                option_id="payip:action:pix",
                title="PIX da Ultima Consulta",
                description="Enviar copia e cola e PDF",
                shortcut="3",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_STATUS,
                title="Diagnostico PayIP",
                description="Ver sessao, cache e revendas",
                shortcut="4",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_CREATE_CHARGE,
                title="Emitir Cobranca",
                description="Criar PIX com confirmacao",
                shortcut="5",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_STATEMENT,
                title="Extrato PayIP",
                description="Resumo de movimentacoes por periodo",
                shortcut="6",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_AMOUNT_DAY,
                title="Buscar Valor/Dia",
                description="Cobrancas pagas por valor",
                shortcut="7",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_VALIDATE_DAY,
                title="Validar Data",
                description="Totais por vencimento e criacao",
                shortcut="8",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_IMPORT_BATCH,
                title="Validar Importacao",
                description="Cobrancas automatizadas ProMax",
                shortcut="9",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_CREATE_CLIENT,
                title="Criar Cliente",
                description="Cadastrar cliente da dClientes",
                shortcut="10",
            )
        )
        options.append(
            flow.InteractiveOption(
                option_id=flow.PAYIP_ACTION_ROUTES,
                title="Rotas em Progresso",
                description="Mapas e motoristas ativos",
                shortcut="11",
            )
        )
        return flow.OutgoingMessage(
            kind="menu",
            title="Pagamentos PayIP",
            text=text,
            footer=(
                "Atalhos: nf 3 147478, nb 3 17581 pendentes, nb 4 17581 todos, extrato 4 01/05/2026 08/05/2026, valor 3 0,99 13/04/2026 tolerancia 0,10. "
                "Validar data: validar 3 07072026. Importacao: importar 3 07072026 07072026. Rotas: rotas 3. "
                "Cliente: criar cliente payip 3 19167. "
                "Use A ou ANT para voltar."
            ),
            button_text="Escolher",
            options=tuple(options),
        )

    def _build_payip_status_response(self) -> OutgoingMessage:
        flow = _customer_flow_module()
        if self.payip_payments_service is None:
            return flow.OutgoingMessage(
                text=(
                    "PayIP ainda nao esta configurada no bot.\n"
                    "Configure PAYIP_BASE_URL, PAYIP_USERNAME, PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            )

        status = self.payip_payments_service.status()
        lines = ["PayIP | Status da sessao", ""]
        lines.append(f"Configurado: {flow._format_yes_no(bool(status.get('configured')))}")
        lines.append(f"Cache local: {flow._format_yes_no(bool(status.get('has_cached_tokens')))}")
        lines.append(f"Access token valido: {flow._format_yes_no(bool(status.get('access_token_valid')))}")
        lines.append(f"Refresh token valido: {flow._format_yes_no(bool(status.get('refresh_token_valid')))}")
        session_state = str(status.get("session_state") or "").strip()
        if session_state:
            lines.append(f"Sessao: {session_state}")
        scope = str(status.get("scope") or "").strip()
        if scope:
            lines.append(f"Escopo: {scope}")
        company_ids = status.get("company_ids")
        if isinstance(company_ids, dict) and company_ids:
            labels = [
                flow._format_filial_label(filial)
                for filial in sorted(company_ids, key=flow._sort_numeric_text)
            ]
            lines.append(f"Revendas PayIP: {', '.join(labels)}")
        company_tax_ids = status.get("company_tax_ids")
        if isinstance(company_tax_ids, dict) and company_tax_ids:
            labels = [
                flow._format_filial_label(filial)
                for filial in sorted(company_tax_ids, key=flow._sort_numeric_text)
            ]
            lines.append(f"CNPJs emissao: {', '.join(labels)}")
        return flow.OutgoingMessage(text="\n".join(lines))

    def _run_payip_login_test(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        session.payip_pending_action = ""
        session.payip_pending_invoice = ""
        session.payip_pending_client_code = ""
        session.payip_pending_filial = ""
        session.payip_pending_date_start = ""
        session.payip_pending_date_end = ""
        session.payip_pending_amount = ""
        session.payip_pending_day = ""
        session.payip_pending_tolerance = ""
        session.payip_pix_payloads = ()
        try:
            outgoing = self._build_payip_login_test_response(mfa_code=mfa_code)
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt()
        except flow.PayipError as exc:
            if mfa_code:
                session.step = "finance_payip_awaiting_mfa"
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                )
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui validar o login da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar a PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
            )

        return self._with_post_result_navigation(
            sender,
            session,
            outgoing,
            return_menu="finance_payip_menu",
        )

    def _build_payip_mfa_prompt(
        self,
        *,
        invalid_selection: bool = False,
        detail: str = "",
        context: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Nao consegui validar esse codigo MFA.")
            if detail:
                lines.append(f"Detalhe: {detail}")
            lines.append("")
        lines.extend(
            [
                "A PayIP pediu MFA para iniciar uma nova sessao.",
                f"Consulta pendente: {context}" if context else "",
                "Envie aqui o codigo atual do Google Authenticator com 6 digitos.",
                "Exemplo: 123456",
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(line for line in lines if line != ""))

    def _build_payip_login_test_response(self, *, mfa_code: str = "") -> OutgoingMessage:
        flow = _customer_flow_module()
        if self.payip_payments_service is None:
            return flow.OutgoingMessage(
                text=(
                    "PayIP ainda nao esta configurada no bot.\n"
                    "Configure PAYIP_BASE_URL, PAYIP_USERNAME, PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            )

        if mfa_code:
            self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
        status = self.payip_payments_service.status()

        lines = ["PayIP | Diagnostico", ""]
        lines.append("Sessao autenticada.")
        lines.append(f"Access token valido: {flow._format_yes_no(bool(status.get('access_token_valid')))}")
        lines.append(f"Refresh token valido: {flow._format_yes_no(bool(status.get('refresh_token_valid')))}")
        company_ids = status.get("company_ids")
        if isinstance(company_ids, dict) and company_ids:
            labels = [flow._format_filial_label(filial) for filial in sorted(company_ids, key=flow._sort_numeric_text)]
            lines.append(f"Revendas PayIP: {', '.join(labels)}")
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_invoice_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Nao identifiquei o numero da nota fiscal.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial e o numero da nota fiscal para buscar na PayIP.",
                "Exemplo: 3 147478",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _payip_filial_hint(self) -> str:
        flow = _customer_flow_module()
        if self.payip_payments_service is None:
            return "Informe a filial da revenda."
        try:
            status = self.payip_payments_service.status()
        except RuntimeError:
            return "Informe a filial da revenda."
        company_ids = status.get("company_ids")
        if not isinstance(company_ids, dict) or not company_ids:
            return "Informe a filial da revenda."
        labels = [flow._format_filial_label(filial) for filial in sorted(company_ids, key=flow._sort_numeric_text)]
        return f"Filiais PayIP: {' | '.join(labels)}"

    def _build_payip_client_code_prompt(
        self,
        invalid_selection: bool = False,
        *,
        pending_only: bool | None = True,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Nao identifiquei o NB/codigo do cliente.")
            lines.append("")
        if pending_only is None:
            action_label = "consultar pagamentos"
            example = "Exemplo: 3 17"
        elif pending_only:
            action_label = "listar pagamentos pendentes"
            example = "Exemplo: 3 17"
        else:
            action_label = "listar pagamentos de todos os status"
            example = "Exemplo: 3 17"
        lines.extend(
            [
                f"Informe a filial e o NB/codigo do cliente para {action_label}.",
                example,
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_client_filter_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Escolha 1 para pendentes ou 2 para todos os status.")
            lines.append("")
        lines.extend(
            [
                "Qual filtro voce quer usar para esse NB?",
                "1. Somente pendentes",
                "2. Todos os status",
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_charge_client_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe a filial e o NB/codigo do cliente.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial e o NB do cliente para emitir a cobranca.",
                "Exemplo: 3 16883",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_create_client_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe uma filial e um NB validos.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial e o NB do cliente para cadastrar na PayIP usando a dClientes.",
                "Exemplo: 3 19167",
                "Exemplo: criar cliente payip 3 19167",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_statement_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe uma filial valida e, se usar periodo, duas datas validas.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial para consultar o extrato PayIP.",
                "Se enviar apenas a filial, consulto do inicio do mes atual ate hoje.",
                "Exemplo: 4",
                "Exemplo com periodo: 4 01/05/2026 08/05/2026",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_amount_day_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe uma filial, um valor e uma data valida.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial, o valor recebido e o dia de pagamento para buscar cobrancas na PayIP.",
                "Exemplo: 3 0,99 13/04/2026",
                "Tolerancia padrao: R$ 0,05. Para alterar: 3 0,99 13/04/2026 tolerancia 0,10",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_validate_day_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe uma filial e uma data valida.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial e a data para validar as cobrancas na PayIP.",
                "Vou conferir quantas cobrancas vencem nessa data e quantas foram criadas nessa data.",
                "Exemplo: 3 07072026",
                "Exemplo: validar 3 07/07/2026",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_import_batch_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe uma filial e duas datas validas.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial e o periodo de entrega para validar a importacao automatizada da PayIP.",
                "Exemplo: 3 07072026 07072026",
                "Exemplo: importar 3 07/07/2026 07/07/2026",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_routes_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe uma filial valida.")
            lines.append("")
        lines.extend(
            [
                "Informe a filial para consultar os mapas em progresso na PayIP.",
                "Exemplo: rotas 3",
                self._payip_filial_hint(),
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    @staticmethod
    def _parse_payip_filial_client_pair(text: str) -> tuple[str, str]:
        flow = _customer_flow_module()
        raw = str(text or "").strip()
        if not raw:
            return "", ""
        filial = flow._extract_payip_filial_query(raw)
        client_code = flow._extract_payip_client_code_query(raw)
        if filial and client_code:
            return filial, client_code
        numbers = [item for item in re.findall(r"\b\d+\b", raw) if item]
        if len(numbers) >= 2:
            filial_candidate = flow._resolve_payip_filial(numbers[0])
            client_candidate = flow._normalize_cod_pdv(numbers[1])
            if filial_candidate and client_candidate:
                return filial_candidate, client_candidate
        return "", ""

    @staticmethod
    def _parse_payip_validate_day_query(text: str) -> tuple[str, Any | None, bool]:
        flow = _customer_flow_module()
        raw = str(text or "").strip()
        if not raw:
            return "", None, False

        date_matches = list(
            re.finditer(
                r"(?<!\d)(\d{4}-\d{2}-\d{2}|\d{8}|\d{6}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
                raw,
            )
        )
        parsed_dates = [flow._parse_payip_statement_date_token(match.group(1)) for match in date_matches]
        invalid_date = any(item is None for item in parsed_dates)
        valid_dates = [item for item in parsed_dates if item is not None]
        if len(valid_dates) > 1:
            invalid_date = True

        text_without_dates = raw
        for match in reversed(date_matches):
            text_without_dates = text_without_dates[: match.start()] + " " + text_without_dates[match.end() :]

        normalized = flow._normalize_choice(text_without_dates)
        tokens = flow._normalized_tokens(normalized)
        if not valid_dates:
            today = flow.datetime.now(flow.LOCAL_TIMEZONE).date()
            if "hoje" in tokens:
                valid_dates = [today]
            elif "ontem" in tokens:
                valid_dates = [today - flow.timedelta(days=1)]

        filial = flow._extract_payip_filial_query(text_without_dates)
        if not filial:
            for number in re.findall(r"\b\d{1,2}\b", text_without_dates):
                candidate = flow._normalize_filial(number)
                if candidate in flow.FILIAL_LABELS:
                    filial = candidate
                    break

        return filial, valid_dates[0] if len(valid_dates) == 1 else None, invalid_date

    @staticmethod
    def _parse_payip_routes_query(text: str) -> str:
        flow = _customer_flow_module()
        raw = str(text or "").strip()
        if not raw:
            return ""
        text_without_dates = re.sub(
            r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{8}|\d{6}|\d{1,2}/\d{1,2}(?:/\d{2,4})?)(?!\d)",
            " ",
            raw,
        )
        filial = flow._extract_payip_filial_query(text_without_dates)
        if filial:
            return filial
        for number in re.findall(r"\b\d{1,2}\b", text_without_dates):
            candidate = flow._resolve_payip_filial(number)
            if candidate:
                return candidate
        return ""

    def _run_payip_routes_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        filial: str,
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_filial = flow._resolve_payip_filial(filial)
        if not normalized_filial:
            session.step = "finance_payip_menu"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_routes_prompt(invalid_selection=True)

        mfa_bootstrapped = False
        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            if mfa_code:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
            routes_page = self.payip_payments_service.list_all_routes(
                filial=normalized_filial,
                status="IN_PROGRESS",
                page_size=25,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = "routes"
            session.payip_pending_filial = normalized_filial
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=f"rotas em progresso | Revenda: {flow._format_filial_label(normalized_filial)}"
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "routes"
                session.payip_pending_filial = normalized_filial
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=f"rotas em progresso | Revenda: {flow._format_filial_label(normalized_filial)}",
                )
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar as rotas da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_ROUTES,
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar as rotas da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_ROUTES,
            )

        session.payip_pending_action = ""
        session.payip_pending_filial = ""
        self.sessions[sender] = session
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_payip_routes_response(filial=normalized_filial, routes_page=routes_page),
            return_menu="finance_payip_menu",
            repeat_action=flow.REPEAT_PAYIP_ROUTES,
        )

    def _run_payip_validate_day_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        filial: str,
        day: Any,
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_filial = flow._resolve_payip_filial(filial)
        normalized_day = flow._coerce_payip_statement_date(day)
        if not normalized_filial or normalized_day is None:
            session.step = "finance_payip_validate_day_awaiting_query"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_validate_day_prompt(invalid_selection=True)

        mfa_bootstrapped = False
        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            if mfa_code:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
            due_page = self._load_payip_payments_page(
                page=1,
                page_size=5,
                due_date_start=normalized_day.isoformat(),
                due_date_end=normalized_day.isoformat(),
                filial=normalized_filial,
            )
            created_page = self._load_payip_payments_page(
                page=1,
                page_size=5,
                created_at_start=normalized_day.isoformat(),
                created_at_end=normalized_day.isoformat(),
                filial=normalized_filial,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = "validate_day"
            session.payip_pending_filial = normalized_filial
            session.payip_pending_day = normalized_day.isoformat()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=(
                    f"validar {normalized_day.strftime('%d/%m/%Y')} | "
                    f"Revenda: {flow._format_filial_label(normalized_filial)}"
                )
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "validate_day"
                session.payip_pending_filial = normalized_filial
                session.payip_pending_day = normalized_day.isoformat()
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=(
                        f"validar {normalized_day.strftime('%d/%m/%Y')} | "
                        f"Revenda: {flow._format_filial_label(normalized_filial)}"
                    ),
                )
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui validar as cobrancas da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_VALIDATE_DAY,
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui validar as cobrancas da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_VALIDATE_DAY,
            )

        session.payip_pending_action = ""
        session.payip_pending_filial = ""
        session.payip_pending_day = ""
        session.payip_pix_payloads = flow._extract_payip_pix_payloads(
            tuple(getattr(due_page, "items", ()) or ()) + tuple(getattr(created_page, "items", ()) or ()),
            filial=normalized_filial,
            company_id=getattr(due_page, "company_id", "") or getattr(created_page, "company_id", ""),
        )
        self.sessions[sender] = session
        return self._build_payip_validate_day_response(
            filial=normalized_filial,
            day=normalized_day,
            due_page=due_page,
            created_page=created_page,
        )

    def _run_payip_import_batch_validation(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        filial: str,
        date_start: Any,
        date_end: Any,
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_filial = flow._resolve_payip_filial(filial)
        normalized_date_start, normalized_date_end, invalid_date = flow._normalize_payip_statement_period(
            date_start=date_start,
            date_end=date_end,
        )
        if not normalized_filial or invalid_date:
            session.step = "finance_payip_import_batch_awaiting_period"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_import_batch_prompt(invalid_selection=True)

        mfa_bootstrapped = False
        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            if mfa_code:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
            validation = self.payip_payments_service.validate_promax_import_batch(
                filial=normalized_filial,
                date_start=normalized_date_start,
                date_end=normalized_date_end,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = "import_batch"
            session.payip_pending_filial = normalized_filial
            session.payip_pending_date_start = normalized_date_start.isoformat()
            session.payip_pending_date_end = normalized_date_end.isoformat()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=(
                    f"importacao automatizada {normalized_date_start.strftime('%d/%m/%Y')} a "
                    f"{normalized_date_end.strftime('%d/%m/%Y')} | Revenda: {flow._format_filial_label(normalized_filial)}"
                )
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "import_batch"
                session.payip_pending_filial = normalized_filial
                session.payip_pending_date_start = normalized_date_start.isoformat()
                session.payip_pending_date_end = normalized_date_end.isoformat()
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=(
                        f"importacao automatizada {normalized_date_start.strftime('%d/%m/%Y')} a "
                        f"{normalized_date_end.strftime('%d/%m/%Y')} | Revenda: {flow._format_filial_label(normalized_filial)}"
                    ),
                )
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui validar a importacao automatizada da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_IMPORT_BATCH,
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui validar a importacao automatizada da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_IMPORT_BATCH,
            )

        missing_codes = tuple(str(item or "").strip() for item in getattr(validation, "missing_client_codes", ()) if str(item or "").strip())
        session.payip_import_missing_client_codes = missing_codes
        session.payip_pending_filial = normalized_filial
        session.payip_pending_date_start = normalized_date_start.isoformat()
        session.payip_pending_date_end = normalized_date_end.isoformat()
        if missing_codes:
            session.payip_pending_action = ""
            self.sessions[sender] = session
            return self._with_post_result_navigation(
                sender,
                session,
                self._build_payip_import_batch_validation_response(validation),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_IMPORT_BATCH,
            )

        session.step = "finance_payip_import_batch_confirm"
        session.payip_pending_action = "import_batch_confirm"
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_payip_import_batch_validation_response(validation)

    def _run_payip_import_batch_confirmation(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        filial: str,
        date_start: Any,
        date_end: Any,
        mfa_code: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_filial = flow._resolve_payip_filial(filial)
        normalized_date_start, normalized_date_end, invalid_date = flow._normalize_payip_statement_period(
            date_start=date_start,
            date_end=date_end,
        )
        normalized_mfa = flow._extract_mfa_code(mfa_code)
        if not normalized_filial or invalid_date or not normalized_mfa:
            session.step = "finance_payip_import_batch_confirm"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_import_batch_confirmation_prompt(session=session, invalid_selection=True)

        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            result = self.payip_payments_service.import_promax_batch(
                filial=normalized_filial,
                date_start=normalized_date_start,
                date_end=normalized_date_end,
                totp_code=normalized_mfa,
            )
        except flow.PayipError as exc:
            session.step = "finance_payip_import_batch_confirm"
            session.payip_pending_action = "import_batch_confirm"
            session.payip_pending_filial = normalized_filial
            session.payip_pending_date_start = normalized_date_start.isoformat()
            session.payip_pending_date_end = normalized_date_end.isoformat()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_import_batch_confirmation_prompt(
                session=session,
                invalid_selection=True,
                detail=flow._short_error_text(str(exc)),
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui confirmar a importacao automatizada da PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_IMPORT_BATCH,
            )

        missing_codes = tuple(str(item or "").strip() for item in getattr(result, "missing_client_codes", ()) if str(item or "").strip())
        session.payip_import_missing_client_codes = missing_codes
        session.payip_pending_action = ""
        session.payip_pending_filial = ""
        session.payip_pending_date_start = ""
        session.payip_pending_date_end = ""
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_payip_import_batch_result_response(result),
            return_menu="finance_payip_menu",
            repeat_action=flow.REPEAT_PAYIP_IMPORT_BATCH,
        )

    def _run_payip_amount_day_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        filial: str,
        amount: flow.Decimal | str | int | float | None,
        day: flow.date | str | None,
        tolerance: flow.Decimal | str | int | float | None = None,
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        normalized_filial = flow._resolve_payip_filial(filial)
        normalized_amount = flow._parse_decimal_text(amount)
        normalized_day = flow._coerce_payip_statement_date(day)
        normalized_tolerance = (
            flow._parse_decimal_text(tolerance)
            if str(tolerance or "").strip()
            else flow.DEFAULT_PAYMENT_AMOUNT_TOLERANCE
        )
        if (
            not normalized_filial
            or normalized_amount is None
            or normalized_amount <= 0
            or normalized_day is None
            or normalized_tolerance is None
            or normalized_tolerance < 0
        ):
            session.step = "finance_payip_amount_day_awaiting_query"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_amount_day_prompt(invalid_selection=True)

        mfa_bootstrapped = False
        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            if mfa_code:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
            page = self.payip_payments_service.find_payments_by_amount_and_paid_date(
                filial=normalized_filial,
                amount=normalized_amount,
                day=normalized_day,
                tolerance=normalized_tolerance,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = "amount_day"
            session.payip_pending_filial = normalized_filial
            session.payip_pending_amount = flow._decimal_cache_text(normalized_amount)
            session.payip_pending_day = normalized_day.isoformat()
            session.payip_pending_tolerance = flow._decimal_cache_text(normalized_tolerance)
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=(
                    f"valor {flow._format_currency_brl(normalized_amount)} em "
                    f"{normalized_day.strftime('%d/%m/%Y')} | Tolerancia: {flow._format_currency_brl(normalized_tolerance)} | "
                    f"Revenda: {flow._format_filial_label(normalized_filial)}"
                )
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "amount_day"
                session.payip_pending_filial = normalized_filial
                session.payip_pending_amount = flow._decimal_cache_text(normalized_amount)
                session.payip_pending_day = normalized_day.isoformat()
                session.payip_pending_tolerance = flow._decimal_cache_text(normalized_tolerance)
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=(
                        f"valor {flow._format_currency_brl(normalized_amount)} em "
                        f"{normalized_day.strftime('%d/%m/%Y')} | Tolerancia: {flow._format_currency_brl(normalized_tolerance)} | "
                        f"Revenda: {flow._format_filial_label(normalized_filial)}"
                    ),
                )
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar a PayIP por valor e dia agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_AMOUNT_DAY,
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar a PayIP por valor e dia agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_AMOUNT_DAY,
            )

        session.payip_pending_action = ""
        session.payip_pending_filial = ""
        session.payip_pending_amount = ""
        session.payip_pending_day = ""
        session.payip_pending_tolerance = ""
        session.payip_pix_payloads = flow._extract_payip_pix_payloads(
            page.items,
            filial=normalized_filial,
            company_id=getattr(page, "company_id", ""),
        )
        criteria = (
            f"Revenda: {flow._format_filial_label(normalized_filial)} | "
            f"Pagamento: {normalized_day.strftime('%d/%m/%Y')} | "
            f"Valor: {flow._format_currency_brl(normalized_amount)} | "
            f"Tolerancia: {flow._format_currency_brl(normalized_tolerance)}"
        )
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_payip_payments_response(
                title="PayIP | Valor e Dia",
                page=page,
                criteria=criteria,
                empty_text=(
                    "Nao encontrei cobrancas pagas nesse dia dentro da tolerancia informada nessa revenda."
                ),
            ),
            return_menu="finance_payip_menu",
            repeat_action=flow.REPEAT_PAYIP_AMOUNT_DAY,
        )

    def _build_payip_validate_day_response(
        self,
        *,
        filial: str,
        day: Any,
        due_page: Any,
        created_page: Any,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        due_items = tuple(getattr(due_page, "items", ()) or ())
        created_items = tuple(getattr(created_page, "items", ()) or ())
        due_total = getattr(due_page, "total_items", None)
        created_total = getattr(created_page, "total_items", None)
        if due_total is None:
            due_total = getattr(due_page, "items_count", None)
        if created_total is None:
            created_total = getattr(created_page, "items_count", None)
        if due_total is None:
            due_total = len(due_items)
        if created_total is None:
            created_total = len(created_items)

        day_label = day.strftime("%d/%m/%Y") if hasattr(day, "strftime") else flow._format_display_date(str(day or ""))
        lines = [
            "PayIP | Validacao por Data",
            "",
            f"Revenda: {flow._format_filial_label(filial)}",
            f"Data: {day_label}",
            "",
            f"- Com vencimento nessa data: {flow._format_optional_count(due_total)}",
            f"- Criadas nessa data: {flow._format_optional_count(created_total)}",
        ]
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_routes_response(self, *, filial: str, routes_page: Any) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        items = tuple(sorted(getattr(routes_page, "items", ()) or (), key=self._payip_route_sort_key))
        total = getattr(routes_page, "total_items", None)
        if total is None:
            total = getattr(routes_page, "items_count", None)
        if total is None:
            total = len(items)

        lines = [
            "PayIP | Rotas em Progresso",
            "",
            f"Revenda: {flow._format_filial_label(filial)}",
            f"Rotas em progresso: {flow._format_optional_count(total)}",
        ]
        if not items:
            lines.extend(["", "Nao encontrei mapas em progresso nessa revenda."])
            return flow.OutgoingMessage(text="\n".join(lines))

        lines.append("")
        for index, item in enumerate(items, start=1):
            route_code = str(item.get("code") or item.get("map") or item.get("mapa") or "-").strip() if isinstance(item, dict) else "-"
            drivers = self._payip_route_driver_names(item)
            driver_label = ", ".join(drivers) if drivers else "Motorista nao informado"
            lines.append(f"{index}) {route_code} - {driver_label}")
        return flow.OutgoingMessage(text="\n".join(lines))

    @staticmethod
    def _payip_route_sort_key(item: Any) -> tuple[int, int | str]:
        if not isinstance(item, dict):
            return (1, "")
        code = str(item.get("code") or item.get("map") or item.get("mapa") or "").strip()
        digits = "".join(char for char in code if char.isdigit())
        if digits:
            return (0, int(digits))
        return (1, code)

    @staticmethod
    def _payip_route_driver_names(item: Any) -> tuple[str, ...]:
        if not isinstance(item, dict):
            return ()
        names: list[str] = []
        for driver_route in item.get("driversRoute") or item.get("drivers_route") or ():
            if not isinstance(driver_route, dict):
                continue
            driver = driver_route.get("driver")
            if isinstance(driver, dict):
                name = str(driver.get("name") or "").strip()
                code = str(driver.get("code") or "").strip()
                if name and code:
                    names.append(f"{name} ({code})")
                elif name:
                    names.append(name)
                elif code:
                    names.append(code)
            else:
                name = str(driver_route.get("driverName") or driver_route.get("driver_name") or "").strip()
                if name:
                    names.append(name)
        return tuple(dict.fromkeys(names))

    def _build_payip_import_batch_validation_response(self, validation: Any) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        items = tuple(getattr(validation, "items", ()) or ())
        missing_codes = tuple(getattr(validation, "missing_client_codes", ()) or ())
        date_start = str(getattr(validation, "date_start", "") or "")
        date_end = str(getattr(validation, "date_end", "") or "")
        total_amount = flow.Decimal("0")
        for item in items:
            parsed = flow._parse_decimal_text(item.get("total") if isinstance(item, dict) else None)
            if parsed is not None:
                total_amount += parsed

        lines = [
            "PayIP | Importacao Automatizada",
            "",
            f"Revenda: {flow._format_filial_label(getattr(validation, 'filial', '') or '')}",
            f"Periodo: {flow._format_display_date(date_start)} a {flow._format_display_date(date_end)}",
            "",
        ]
        if missing_codes:
            lines.extend(
                [
                    "Validacao com erro.",
                    f"- Clientes nao encontrados: {len(missing_codes)}",
                    f"- Codigos: {', '.join(missing_codes[:20])}",
                    "",
                    "Guardei esses codigos para a proxima etapa.",
                    "Para tentar criar todos pela dClientes, envie CRIAR CLIENTES PAYIP.",
                ]
            )
            if len(missing_codes) > 20:
                lines.append(f"- Mais codigos omitidos: {len(missing_codes) - 20}")
            return flow.OutgoingMessage(text="\n".join(lines))

        lines.extend(
            [
                "Validacao aprovada.",
                f"- Cobrancas encontradas: {len(items)}",
                f"- Valor total: {flow._format_currency_brl(total_amount)}",
            ]
        )
        if items:
            lines.append("")
            lines.append("Amostra:")
            for index, item in enumerate(items[:5], start=1):
                invoice = flow._payip_clean_text(item.get("invoice")) if isinstance(item, dict) else ""
                client_code = flow._payip_clean_text(item.get("clientCode")) if isinstance(item, dict) else ""
                total = flow._parse_decimal_text(item.get("total") if isinstance(item, dict) else None) or flow.Decimal("0")
                due_date = flow._format_display_date(item.get("dueDate") if isinstance(item, dict) else "")
                lines.append(f"{index}) NB {client_code or '-'} | NF {invoice or '-'} | {flow._format_currency_brl(total)} | Venc {due_date}")
        lines.extend(
            [
                "",
                "Para emitir essas cobrancas, envie CONFIRMAR IMPORTACAO.",
                "Se ja estiver com o token MFA, pode enviar o codigo de 6 digitos.",
                "Para cancelar, envie MENU.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_import_batch_confirmation_prompt(
        self,
        *,
        session: Any,
        invalid_selection: bool = False,
        detail: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        lines: list[str] = []
        if invalid_selection:
            lines.append("Nao consegui confirmar a importacao automatizada.")
            if detail:
                lines.append(f"Detalhe: {detail}")
            lines.append("")
        lines.extend(
            [
                "PayIP | Confirmar Importacao",
                "",
                f"Revenda: {flow._format_filial_label(getattr(session, 'payip_pending_filial', '') or '')}",
                (
                    "Periodo: "
                    f"{flow._format_display_date(getattr(session, 'payip_pending_date_start', '') or '')} a "
                    f"{flow._format_display_date(getattr(session, 'payip_pending_date_end', '') or '')}"
                ),
                "",
                "Envie CONFIRMAR IMPORTACAO para prosseguir.",
                "Ou envie o codigo MFA de 6 digitos para confirmar agora.",
                "Para cancelar, envie MENU.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_import_batch_result_response(self, result: Any) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        items = tuple(getattr(result, "items", ()) or ())
        missing_codes = tuple(getattr(result, "missing_client_codes", ()) or ())
        date_start = str(getattr(result, "date_start", "") or "")
        date_end = str(getattr(result, "date_end", "") or "")
        total_amount = flow.Decimal("0")
        for item in items:
            parsed = flow._parse_decimal_text(item.get("total") if isinstance(item, dict) else None)
            if parsed is not None:
                total_amount += parsed

        lines = [
            "PayIP | Importacao Confirmada",
            "",
            f"Revenda: {flow._format_filial_label(getattr(result, 'filial', '') or '')}",
            f"Periodo: {flow._format_display_date(date_start)} a {flow._format_display_date(date_end)}",
            "",
        ]
        if missing_codes:
            lines.extend(
                [
                    "Confirmacao com erro.",
                    f"- Clientes nao encontrados: {len(missing_codes)}",
                    f"- Codigos: {', '.join(missing_codes[:20])}",
                    "",
                    "Guardei esses codigos para a proxima etapa.",
                ]
            )
            if len(missing_codes) > 20:
                lines.append(f"- Mais codigos omitidos: {len(missing_codes) - 20}")
            return flow.OutgoingMessage(text="\n".join(lines))

        lines.extend(
            [
                "Importacao enviada com sucesso.",
                f"- Cobrancas retornadas: {len(items)}",
                f"- Valor total retornado: {flow._format_currency_brl(total_amount)}",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _run_payip_statement_resume(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        filial: str,
        date_start: flow.date | str | None = None,
        date_end: flow.date | str | None = None,
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_filial = flow._resolve_payip_filial(filial)
        normalized_date_start, normalized_date_end, invalid_date = flow._normalize_payip_statement_period(
            date_start=date_start,
            date_end=date_end,
        )
        if not normalized_filial or invalid_date:
            session.step = "finance_payip_statement_awaiting_period"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_statement_prompt(invalid_selection=True)

        mfa_bootstrapped = False
        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            if mfa_code:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
            resume = self.payip_payments_service.statement_movements_resume(
                filial=normalized_filial,
                date_start=normalized_date_start,
                date_end=normalized_date_end,
            )
            pdf_bytes, xlsx_bytes, export_errors = self._load_payip_statement_exports(
                filial=normalized_filial,
                date_start=normalized_date_start,
                date_end=normalized_date_end,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = "statement"
            session.payip_pending_filial = normalized_filial
            session.payip_pending_date_start = normalized_date_start.isoformat()
            session.payip_pending_date_end = normalized_date_end.isoformat()
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=(
                    f"extrato {flow._format_filial_label(normalized_filial)} "
                    f"{normalized_date_start.strftime('%d/%m/%Y')} a {normalized_date_end.strftime('%d/%m/%Y')}"
                )
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "statement"
                session.payip_pending_filial = normalized_filial
                session.payip_pending_date_start = normalized_date_start.isoformat()
                session.payip_pending_date_end = normalized_date_end.isoformat()
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=(
                        f"extrato {flow._format_filial_label(normalized_filial)} "
                        f"{normalized_date_start.strftime('%d/%m/%Y')} a {normalized_date_end.strftime('%d/%m/%Y')}"
                    ),
                )
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar o extrato PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_STATEMENT,
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar o extrato PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=flow.REPEAT_PAYIP_STATEMENT,
            )

        session.payip_pending_action = ""
        session.payip_pending_filial = ""
        session.payip_pending_date_start = ""
        session.payip_pending_date_end = ""
        return self._with_post_result_navigation(
            sender,
            session,
            flow._build_payip_statement_resume_response(
                resume,
                filial=normalized_filial,
                date_start=normalized_date_start.isoformat(),
                date_end=normalized_date_end.isoformat(),
                pdf_bytes=pdf_bytes,
                xlsx_bytes=xlsx_bytes,
                export_errors=export_errors,
            ),
            return_menu="finance_payip_menu",
            repeat_action=flow.REPEAT_PAYIP_STATEMENT,
        )

    def _load_payip_statement_exports(
        self,
        *,
        filial: str,
        date_start: flow.date,
        date_end: flow.date,
    ) -> tuple[bytes, bytes, tuple[str, ...]]:
        flow = _customer_flow_module()
        if self.payip_payments_service is None:
            return b"", b"", ()
        errors: list[str] = []
        pdf_bytes = b""
        xlsx_bytes = b""
        try:
            pdf_bytes = self.payip_payments_service.statement_movements_export(
                filial=filial,
                date_start=date_start,
                date_end=date_end,
                file_format="pdf",
            )
        except (flow.PayipError, RuntimeError) as exc:
            errors.append(f"PDF: {flow._short_error_text(str(exc))}")
        try:
            xlsx_bytes = self.payip_payments_service.statement_movements_export(
                filial=filial,
                date_start=date_start,
                date_end=date_end,
                file_format="xlsx",
            )
        except (flow.PayipError, RuntimeError) as exc:
            errors.append(f"XLSX: {flow._short_error_text(str(exc))}")
        return pdf_bytes, xlsx_bytes, tuple(errors)

    def _build_payip_charge_lookup_error(
        self,
        *,
        filial: str,
        client_code: str,
        error_text: str,
        mfa_was_validated: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        detail = flow._short_error_text(error_text)
        lines = [
            "Nao consegui buscar esse cliente na PayIP agora.",
            f"Revenda: {flow._format_filial_label(filial)}" if filial else "Revenda: -",
            f"NB: {client_code or '-'}",
            f"Detalhe: {detail}",
        ]
        if mfa_was_validated and flow._is_payip_company_forbidden_error(error_text):
            lines.extend(
                [
                    "",
                    "A sessao foi validada, mas a PayIP recusou essa empresa/revenda.",
                    "Confira se essa filial esta liberada para o usuario PayIP usado no bot.",
                ]
            )
        lines.extend(["", "Informe outra filial e NB, ou envie A para voltar."])
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_charge_amount_prompt(
        self,
        *,
        session: flow.LookupSession,
        invalid_selection: bool = False,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe um valor valido maior que zero.")
            lines.append("")
        lines.extend(
            [
                "Cliente encontrado para emissao PayIP",
                "",
                f"Revenda: {flow._format_filial_label(session.payip_charge_filial)}",
                f"Cliente: {session.payip_charge_client_name}",
                f"NB: {session.payip_charge_external_id or '-'}",
                f"CPF/CNPJ: {flow._format_tax_payer_id(session.payip_charge_tax_payer_id)}",
                "",
                "Informe o valor da cobranca.",
                "Exemplo: 0,99",
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_charge_due_date_prompt(self, invalid_selection: bool = False) -> OutgoingMessage:
        flow = _customer_flow_module()
        lines = []
        if invalid_selection:
            lines.append("Informe uma data de vencimento valida, hoje ou futura.")
            lines.append("")
        lines.extend(
            [
                "Informe a data de vencimento da cobranca.",
                "Exemplo: 07/05/2026",
                "",
                "Para voltar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_charge_confirmation(
        self,
        *,
        session: flow.LookupSession,
        invalid_selection: bool = False,
        detail: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        flow = _customer_flow_module()
        amount = flow._parse_decimal_text(session.payip_charge_amount) or flow.Decimal("0")
        rate_amount = flow._payip_charge_rate_amount(session)
        interest_perc = flow._payip_charge_interest_perc(session)
        due_date = flow._parse_iso_date(session.payip_charge_due_date)
        issue_date = flow.datetime.now(flow.LOCAL_TIMEZONE).date()
        title = flow._payip_charge_title(session.payip_charge_filial)
        total = amount + rate_amount
        lines = []
        if invalid_selection:
            lines.append("Para emitir a cobranca real, responda CONFIRMAR.")
            if detail:
                lines.append(f"Detalhe: {detail}")
            lines.append("")
        lines.extend(
            [
                "Confirmar emissao PayIP",
                "",
                f"Revenda: {flow._format_filial_label(session.payip_charge_filial)}",
                f"Cliente: {session.payip_charge_client_name}",
                f"NB: {session.payip_charge_external_id or '-'}",
                f"CPF/CNPJ: {flow._format_tax_payer_id(session.payip_charge_tax_payer_id)}",
                f"Nota fiscal: {session.payip_charge_invoice or '-'}",
                "",
                f"Titulo: {title}",
                f"Descricao: {title}",
                f"Emissao: {issue_date.strftime('%d/%m/%Y')}",
                f"Vencimento: {due_date.strftime('%d/%m/%Y') if due_date else '-'}",
                "",
                f"Valor base: {flow._format_currency_brl(amount)}",
                f"Taxa PIX: {flow._format_currency_brl(rate_amount)}",
                f"Total estimado: {flow._format_currency_brl(total)}",
                f"Juros apos vencimento: {flow._format_decimal_percent(interest_perc)} ao dia",
                "Multa: nao",
                "Validade apos vencimento: 30 dias",
                "",
                "Para alterar antes de emitir: nb 16883 | nf 147478 | taxa 5,00 | juros 8 | vencimento 31/12/2026.",
                "Para remover: sem nb (gera ID tecnico) | sem nf | taxa 0 | juros 0.",
                "Responda CONFIRMAR para emitir.",
                "Para cancelar, envie A ou ANT.",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _run_payip_charge_client_lookup(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        client_code: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_client_code = flow._extract_payip_client_code_query(client_code) or flow._normalize_cod_pdv(client_code)
        normalized_filial = flow._resolve_payip_filial(filial or flow._extract_payip_filial_query(client_code))
        if not normalized_client_code or not normalized_filial:
            session.step = "finance_payip_charge_awaiting_client"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_client_prompt(invalid_selection=True)
        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD, PAYIP_COMPANY_IDS e PAYIP_COMPANY_TAX_IDS no .env."
                )
            mfa_bootstrapped = False
            if mfa_code:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
            client_record = self.payip_payments_service.find_client_by_code(
                filial=normalized_filial,
                client_code=normalized_client_code,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = "charge_lookup"
            session.payip_pending_client_code = normalized_client_code
            session.payip_pending_filial = normalized_filial
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=f"emissao NB {normalized_client_code} | Revenda: {flow._format_filial_label(normalized_filial)}"
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "charge_lookup"
                session.payip_pending_client_code = normalized_client_code
                session.payip_pending_filial = normalized_filial
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=f"emissao NB {normalized_client_code} | Revenda: {flow._format_filial_label(normalized_filial)}",
                )
            session.step = "finance_payip_charge_awaiting_client"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_lookup_error(
                filial=normalized_filial,
                client_code=normalized_client_code,
                error_text=str(exc),
                mfa_was_validated=bool(mfa_code and mfa_bootstrapped),
            )
        except RuntimeError as exc:
            session.step = "finance_payip_charge_awaiting_client"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_lookup_error(
                filial=normalized_filial,
                client_code=normalized_client_code,
                error_text=str(exc),
            )

        if client_record is None:
            session.step = "finance_payip_charge_awaiting_client"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(
                text=(
                    f"Nao encontrei cliente ativo com NB {normalized_client_code} na revenda "
                    f"{flow._format_filial_label(normalized_filial)}.\n\n"
                    "Informe outra filial e NB, ou envie A para voltar."
                )
            )

        session.payip_charge_filial = normalized_filial
        session.payip_charge_client_code = client_record.code
        session.payip_charge_external_id = client_record.code
        session.payip_charge_client_name = client_record.name
        session.payip_charge_tax_payer_id = client_record.tax_payer_id
        session.payip_charge_invoice = ""
        session.payip_charge_amount = ""
        session.payip_charge_due_date = ""
        session.payip_charge_rate_amount = "3.92"
        session.payip_charge_interest_perc = "10.00"
        session.payip_pending_action = ""
        session.payip_pending_client_code = ""
        session.payip_pending_filial = ""
        session.step = "finance_payip_charge_awaiting_amount"
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_payip_charge_amount_prompt(session=session)

    def _run_payip_create_client_from_dclientes(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        filial: str,
        client_code: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_filial = flow._resolve_payip_filial(filial)
        normalized_client_code = flow._normalize_cod_pdv(client_code)
        if not normalized_filial or not normalized_client_code:
            session.step = "finance_payip_create_client_awaiting_registration"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_create_client_prompt(invalid_selection=True)

        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
                )
            profile = self.query_service.get_payip_profile_by_registration(
                normalized_filial,
                normalized_client_code,
            )
            if profile is None:
                session.step = "finance_payip_create_client_awaiting_registration"
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return flow.OutgoingMessage(
                    text=(
                        f"Nao encontrei NB {normalized_client_code} na dClientes da revenda "
                        f"{flow._format_filial_label(normalized_filial)}.\n\n"
                        "Informe outra filial e NB, ou envie A para voltar."
                    )
                )
            if not getattr(profile, "documento", ""):
                raise RuntimeError("Cliente encontrado na dClientes, mas sem CPF/CNPJ valido.")
            result = self.payip_payments_service.create_client_from_profile(profile=profile)
        except flow.PayipMfaRequired:
            session.step = "finance_payip_create_client_awaiting_registration"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(
                text=(
                    "A PayIP pediu uma nova sessao MFA antes de criar cliente.\n"
                    "Valide o login no menu PayIP e tente novamente."
                )
            )
        except (flow.PayipError, RuntimeError, ValueError) as exc:
            session.step = "finance_payip_create_client_awaiting_registration"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return flow.OutgoingMessage(
                text=(
                    "Nao consegui criar o cliente na PayIP agora.\n"
                    f"Detalhe: {flow._short_error_text(str(exc))}\n\n"
                    "Informe outra filial e NB, ou envie A para voltar."
                )
            )

        session.payip_pending_action = ""
        session.payip_pending_client_code = ""
        session.payip_pending_filial = ""
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_payip_create_client_response(result),
            return_menu="finance_payip_menu",
            repeat_action=flow.REPEAT_PAYIP_CREATE_CLIENT,
        )

    def _run_payip_create_missing_import_clients(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        filial = flow._resolve_payip_filial(getattr(session, "payip_pending_filial", "") or "")
        codes = tuple(dict.fromkeys(str(item or "").strip() for item in getattr(session, "payip_import_missing_client_codes", ()) or () if str(item or "").strip()))
        if not filial or not codes:
            self.sessions[sender] = session
            return flow.OutgoingMessage(
                text=(
                    "Nao tenho uma lista de clientes faltantes da importacao PayIP nesta conversa.\n"
                    "Valide a importacao novamente e, se houver clientes faltantes, envie CRIAR CLIENTES PAYIP."
                )
            )
        if self.payip_payments_service is None:
            self.sessions[sender] = session
            return flow.OutgoingMessage(text="PayIP ainda nao esta configurada no bot.")

        created: list[str] = []
        not_found: list[str] = []
        failed: list[str] = []
        for code in codes:
            normalized_code = flow._normalize_cod_pdv(code)
            try:
                profile = self.query_service.get_payip_profile_by_registration(filial, normalized_code)
                if profile is None:
                    not_found.append(normalized_code)
                    continue
                if not getattr(profile, "documento", ""):
                    failed.append(f"{normalized_code}: sem CPF/CNPJ valido na dClientes")
                    continue
                self.payip_payments_service.create_client_from_profile(profile=profile)
                created.append(normalized_code)
            except Exception as exc:
                failed.append(f"{normalized_code}: {flow._short_error_text(str(exc))}")

        if not_found or failed:
            session.payip_import_missing_client_codes = tuple(not_found + [item.split(":", 1)[0] for item in failed if item])
        else:
            session.payip_import_missing_client_codes = ()
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_payip_missing_clients_create_response(
                filial=filial,
                total=len(codes),
                created=created,
                not_found=not_found,
                failed=failed,
            ),
            return_menu="finance_payip_menu",
            repeat_action=flow.REPEAT_PAYIP_IMPORT_BATCH,
        )

    def _build_payip_missing_clients_create_response(
        self,
        *,
        filial: str,
        total: int,
        created: list[str],
        not_found: list[str],
        failed: list[str],
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        lines = [
            "PayIP | Clientes da Importacao",
            "",
            f"Revenda: {flow._format_filial_label(filial)}",
            f"- NBs avaliados: {total}",
            f"- Criados: {len(created)}",
            f"- Nao encontrados na dClientes: {len(not_found)}",
            f"- Falhas PayIP/dados: {len(failed)}",
        ]
        if created:
            lines.extend(["", f"Criados: {', '.join(created[:20])}"])
            if len(created) > 20:
                lines.append(f"Mais criados: {len(created) - 20}")
        if not_found:
            lines.extend(["", f"Nao encontrados na dClientes: {', '.join(not_found[:20])}"])
            if len(not_found) > 20:
                lines.append(f"Mais nao encontrados: {len(not_found) - 20}")
        if failed:
            lines.append("")
            lines.append("Falhas:")
            for item in failed[:10]:
                lines.append(f"- {item}")
            if len(failed) > 10:
                lines.append(f"- Mais falhas: {len(failed) - 10}")
        if created and not not_found and not failed:
            lines.extend(["", "Agora valide a importacao novamente."])
        return flow.OutgoingMessage(text="\n".join(lines))

    def _run_payip_charge_create(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        amount = flow._parse_decimal_text(session.payip_charge_amount)
        due_date = flow._parse_iso_date(session.payip_charge_due_date)
        if (
            amount is None
            or amount <= 0
            or due_date is None
            or not session.payip_charge_filial
            or not session.payip_charge_client_code
            or not session.payip_charge_tax_payer_id
        ):
            session.step = "finance_payip_charge_awaiting_client"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_client_prompt(invalid_selection=True)

        title = flow._payip_charge_title(session.payip_charge_filial)
        try:
            if self.payip_payments_service is None:
                raise RuntimeError(
                    "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                    "PAYIP_PASSWORD, PAYIP_COMPANY_IDS e PAYIP_COMPANY_TAX_IDS no .env."
                )
            mfa_bootstrapped = False
            if mfa_code:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
            payment = self._create_payip_charge_with_retry(
                session=session,
                amount=amount,
                due_date=due_date,
                title=title,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = "charge_create"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=f"emitir cobranca NB {session.payip_charge_client_code}"
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = "charge_create"
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=f"emitir cobranca NB {session.payip_charge_client_code}",
                )
            session.step = "finance_payip_charge_confirm"
            session.payip_pending_action = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_create_error_response(
                session=session,
                error_text=str(exc),
            )
        except RuntimeError as exc:
            session.step = "finance_payip_charge_confirm"
            session.payip_pending_action = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_charge_create_error_response(
                session=session,
                error_text=str(exc),
            )

        session.payip_pending_action = ""
        session.payip_pending_client_code = ""
        session.payip_pending_filial = ""
        session.payip_pending_status = ""
        outgoing = self._build_payip_charge_post_create_response(
            session=session,
            payment=payment,
            title=title,
        )
        return self._with_post_result_navigation(
            sender,
            session,
            outgoing,
            return_menu="finance_payip_menu",
            repeat_action=flow.REPEAT_PAYIP_CREATE_CHARGE,
        )

    def _build_payip_create_client_response(self, result: Any) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        payload = getattr(result, "payload", {}) if result is not None else {}
        client = payload.get("client") if isinstance(payload, dict) and isinstance(payload.get("client"), dict) else {}
        address = payload.get("address") if isinstance(payload, dict) and isinstance(payload.get("address"), dict) else {}
        generic_fields: list[str] = []
        if str(client.get("email") or "").endswith("@sememail.com.br"):
            generic_fields.append("email")
        if str(client.get("phone") or "") == "83990000000":
            generic_fields.append("telefone")
        if str(address.get("postalCode") or "") == "00000000":
            generic_fields.append("CEP")
        if str(address.get("street") or "") == "NAO INFORMADO":
            generic_fields.append("rua")
        if str(address.get("neighborhood") or "") == "NAO INFORMADO":
            generic_fields.append("bairro")
        if str(address.get("city") or "") == "NAO INFORMADO":
            generic_fields.append("cidade")
        generic_fields.extend(["complemento", "latitude", "longitude"])
        lines = [
            "PayIP | Cliente Criado",
            "",
            f"Revenda: {flow._format_filial_label(getattr(result, 'filial', '') or '')}",
            f"NB: {getattr(result, 'client_code', '') or client.get('code') or '-'}",
            f"Cliente: {client.get('name') or '-'}",
            f"Fantasia: {client.get('fantasyName') or '-'}",
            f"CPF/CNPJ: {self._format_payip_document(getattr(result, 'tax_payer_id', '') or client.get('taxPayerId') or '')}",
            "",
            "Cadastro enviado para a PayIP.",
        ]
        if generic_fields:
            lines.extend(
                [
                    "",
                    f"Campos com fallback: {', '.join(dict.fromkeys(generic_fields))}.",
                ]
            )
        return flow.OutgoingMessage(text="\n".join(lines))

    @staticmethod
    def _format_payip_document(value: Any) -> str:
        digits = "".join(char for char in str(value or "") if char.isdigit())
        if len(digits) == 11:
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
        if len(digits) == 14:
            return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
        return str(value or "").strip() or "-"


    def _create_payip_charge_with_retry(
        self,
        *,
        session: Any,
        amount: Any,
        due_date: Any,
        title: str,
    ) -> dict[str, Any]:
        flow = _customer_flow_module()
        last_error: Exception | None = None
        for attempt in range(1, PAYIP_CHARGE_ATTEMPTS + 1):
            try:
                return self.payip_payments_service.create_pix_charge(
                    filial=session.payip_charge_filial,
                    amount=amount,
                    rate_amount=flow._payip_charge_rate_amount(session),
                    interest_perc=flow._payip_charge_interest_perc(session),
                    tax_payer_id=session.payip_charge_tax_payer_id,
                    external_id=session.payip_charge_external_id,
                    due_date=due_date,
                    issue_date=flow.datetime.now(flow.LOCAL_TIMEZONE).date(),
                    title=title,
                    description=title,
                    invoice=session.payip_charge_invoice,
                )
            except flow.PayipMfaRequired:
                raise
            except (flow.PayipError, RuntimeError) as exc:
                last_error = exc
                existing = self._find_existing_payip_charge_after_create_error(session=session)
                if existing:
                    return existing
                if attempt >= PAYIP_CHARGE_ATTEMPTS or not self._is_retryable_payip_charge_error(str(exc)):
                    break
                flow.time.sleep(PAYIP_CHARGE_RETRY_DELAY_SECONDS)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Falha desconhecida ao emitir cobranca PayIP.")

    def _find_existing_payip_charge_after_create_error(self, *, session: Any) -> dict[str, Any]:
        flow = _customer_flow_module()
        if self.payip_payments_service is None:
            return {}
        due_date_text = str(session.payip_charge_due_date or "").strip()
        created_at_text = flow.datetime.now(flow.LOCAL_TIMEZONE).date().isoformat()
        client_code = session.payip_charge_external_id or session.payip_charge_client_code
        if not client_code:
            return {}
        try:
            page = self._load_payip_payments_page(
                page=1,
                page_size=50,
                status="PENDING",
                client_code=client_code,
                due_date_start=due_date_text,
                due_date_end=due_date_text,
                created_at_start=created_at_text,
                created_at_end=created_at_text,
                filial=session.payip_charge_filial,
            )
        except (flow.PayipMfaRequired, flow.PayipError, RuntimeError):
            return {}
        items = tuple(item for item in getattr(page, "items", ()) or () if isinstance(item, dict))
        selected = flow._select_payip_created_payment_items(items, payment={}, session=session)
        return selected[0] if selected else {}

    @staticmethod
    def _is_retryable_payip_charge_error(value: str) -> bool:
        normalized = str(value or "").lower()
        if any(
            term in normalized
            for term in (
                "http 400",
                "http 401",
                "http 403",
                "http 404",
                "forbidden",
                "nao configurad",
                "não configurad",
                "nao encontrado",
                "não encontrado",
                "not found",
                "valor invalido",
                "valor inválido",
            )
        ):
            return False
        return any(
            term in normalized
            for term in (
                "http 408",
                "http 409",
                "http 425",
                "http 429",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
                "timeout",
                "timed out",
                "connection",
                "conexao",
                "conexão",
                "temporar",
                "tente novamente",
                "try again",
                "unavailable",
                "indisponivel",
                "indisponível",
                "reset",
            )
        )

    def _build_payip_charge_create_error_response(
        self,
        *,
        session: flow.LookupSession,
        error_text: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        due_date = flow._parse_iso_date(session.payip_charge_due_date)
        amount = flow._parse_decimal_text(session.payip_charge_amount) or flow.Decimal("0")
        rate_amount = flow._payip_charge_rate_amount(session)
        total = amount + rate_amount
        lines = [
            "PayIP | Falha na emissao",
            "",
            "A cobranca nao foi gerada.",
            f"Detalhe: {flow._short_error_text(error_text)}",
            "",
            "*Dados mantidos:*",
            f"- Revenda: {flow._format_filial_label(session.payip_charge_filial)}",
            f"- Cliente: {session.payip_charge_client_name or '-'}",
            f"- NB: {session.payip_charge_external_id or '-'}",
            f"- Valor base: {flow._format_currency_brl(amount)}",
            f"- Taxa PIX: {flow._format_currency_brl(rate_amount)}",
            f"- Total estimado: {flow._format_currency_brl(total)}",
            f"- Vencimento: {due_date.strftime('%d/%m/%Y') if due_date else '-'}",
            "",
            "Para tentar novamente, envie TENTAR NOVAMENTE ou CONFIRMAR.",
            "Para ajustar antes de tentar: taxa 5,00 | juros 8 | vencimento 31/12/2026 | nf 147478.",
            "Para cancelar e voltar ao menu PayIP, envie A ou ANT.",
        ]
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_payip_charge_post_create_response(
        self,
        *,
        session: flow.LookupSession,
        payment: dict[str, Any],
        title: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        search_error = ""
        search_items: tuple[dict[str, Any], ...] = ()
        search_company_id = ""
        direct_payment: dict[str, Any] | None = None
        created_payment_id = flow._payip_clean_text(flow._payip_value(payment, "id"))
        due_date_text = str(session.payip_charge_due_date or "").strip()
        created_at_text = flow.datetime.now(flow.LOCAL_TIMEZONE).date().isoformat()
        search_criteria = flow._payip_post_create_search_criteria(
            client_code=session.payip_charge_client_code,
            due_date=due_date_text,
            created_at=created_at_text,
        )
        if created_payment_id and self.payip_payments_service is not None:
            try:
                direct_payment = self.payip_payments_service.get_payment(created_payment_id)
            except (flow.PayipError, RuntimeError) as exc:
                search_error = flow._short_error_text(str(exc))

        try:
            if direct_payment is None:
                page = self._load_payip_payments_page(
                    page=1,
                    page_size=50,
                    status="PENDING",
                    client_code=session.payip_charge_client_code,
                    due_date_start=due_date_text,
                    due_date_end=due_date_text,
                    created_at_start=created_at_text,
                    created_at_end=created_at_text,
                    filial=session.payip_charge_filial,
                )
                search_items = tuple(item for item in getattr(page, "items", ()) or () if isinstance(item, dict))
                search_company_id = str(getattr(page, "company_id", "") or "")
        except (flow.PayipError, RuntimeError) as exc:
            search_error = flow._short_error_text(str(exc))

        selected_items = (direct_payment,) if direct_payment is not None else flow._select_payip_created_payment_items(
            search_items,
            payment=payment,
            session=session,
        )
        used_search = bool(selected_items)
        lookup_criteria = f"GET /v1/payments/{created_payment_id}" if direct_payment is not None else search_criteria
        display_items = selected_items or (payment,)
        session.payip_pix_payloads = flow._extract_payip_pix_payloads(
            display_items,
            filial=session.payip_charge_filial,
            company_id=search_company_id,
        )
        if session.payip_pix_payloads:
            return flow._build_payip_pix_code_response(
                session.payip_pix_payloads,
                selection=1,
                payip_payments_service=self.payip_payments_service,
                pdf_attempts=5,
                pdf_retry_delay_seconds=2.0,
            )
        return flow._build_payip_charge_created_search_response(
            payment=display_items[0],
            title=title,
            filial=session.payip_charge_filial,
            fallback_client_name=session.payip_charge_client_name,
            fallback_client_code=session.payip_charge_client_code,
            used_search=used_search,
            search_criteria=lookup_criteria,
            search_error=search_error,
        )

    def _run_payip_invoice_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        invoice: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_invoice = flow._extract_payip_invoice_query(invoice) or str(invoice or "").strip()
        normalized_filial = flow._resolve_payip_filial(filial or flow._extract_payip_filial_query(invoice))
        if not normalized_invoice:
            session.step = "finance_payip_awaiting_invoice"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_invoice_prompt(invalid_selection=True)
        if not normalized_filial:
            session.step = "finance_payip_awaiting_invoice"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_invoice_prompt(invalid_selection=True)
        return self._run_payip_search(
            sender=sender,
            session=session,
            action="invoice",
            filial=normalized_filial,
            invoice=normalized_invoice,
            mfa_code=mfa_code,
        )

    def _run_payip_pending_client_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        client_code: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_client_code = flow._extract_payip_client_code_query(client_code) or flow._normalize_cod_pdv(client_code)
        normalized_filial = flow._resolve_payip_filial(filial or flow._extract_payip_filial_query(client_code))
        if not normalized_client_code:
            session.step = "finance_payip_awaiting_client_code"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(invalid_selection=True)
        if not normalized_filial:
            session.step = "finance_payip_awaiting_client_code"
            session.payip_pending_status = "PENDING"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(invalid_selection=True, pending_only=True)
        return self._run_payip_search(
            sender=sender,
            session=session,
            action="pending_client",
            filial=normalized_filial,
            client_code=normalized_client_code,
            status="PENDING",
            mfa_code=mfa_code,
        )

    def _run_payip_client_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        client_code: str,
        filial: str = "",
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_client_code = flow._extract_payip_client_code_query(client_code) or flow._normalize_cod_pdv(client_code)
        normalized_filial = flow._resolve_payip_filial(filial or flow._extract_payip_filial_query(client_code))
        if not normalized_client_code:
            session.step = "finance_payip_awaiting_client_code_all"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(invalid_selection=True, pending_only=False)
        if not normalized_filial:
            session.step = "finance_payip_awaiting_client_code"
            session.payip_pending_status = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(invalid_selection=True, pending_only=False)
        return self._run_payip_search(
            sender=sender,
            session=session,
            action="client",
            filial=normalized_filial,
            client_code=normalized_client_code,
            mfa_code=mfa_code,
        )

    def _run_payip_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        action: str,
        filial: str,
        invoice: str = "",
        client_code: str = "",
        status: str = "",
        mfa_code: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        repeat_action = flow._payip_repeat_action(action)
        mfa_bootstrapped = False
        try:
            operation_mfa_code = mfa_code
            if mfa_code and self.payip_payments_service is not None:
                self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
                mfa_bootstrapped = True
                operation_mfa_code = ""
            page = self._load_payip_payments_page(
                page=1,
                page_size=50,
                status=status,
                client_code=client_code,
                invoice=invoice,
                filial=filial,
                mfa_code=operation_mfa_code,
            )
        except flow.PayipMfaRequired:
            session.step = "finance_payip_awaiting_mfa"
            session.payip_pending_action = action
            session.payip_pending_invoice = invoice
            session.payip_pending_client_code = client_code
            session.payip_pending_filial = filial
            session.payip_pending_status = status
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_mfa_prompt(
                context=flow._payip_search_label(action, invoice, client_code, filial=filial, status=status)
            )
        except flow.PayipError as exc:
            if mfa_code and not mfa_bootstrapped:
                session.step = "finance_payip_awaiting_mfa"
                session.payip_pending_action = action
                session.payip_pending_invoice = invoice
                session.payip_pending_client_code = client_code
                session.payip_pending_filial = filial
                session.payip_pending_status = status
                session.updated_at = flow.datetime.now(flow.timezone.utc)
                self.sessions[sender] = session
                return self._build_payip_mfa_prompt(
                    invalid_selection=True,
                    detail=flow._short_error_text(str(exc)),
                    context=flow._payip_search_label(action, invoice, client_code, filial=filial, status=status),
                )
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        f"Nao consegui consultar a PayIP para {flow._payip_search_label(action, invoice, client_code)} agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=repeat_action,
            )
        except RuntimeError as exc:
            return self._with_post_result_navigation(
                sender,
                session,
                flow.OutgoingMessage(
                    text=(
                        "Nao consegui consultar a PayIP agora.\n"
                        f"Detalhe: {flow._short_error_text(str(exc))}"
                    )
                ),
                return_menu="finance_payip_menu",
                repeat_action=repeat_action,
            )

        session.payip_pending_action = ""
        session.payip_pending_invoice = ""
        session.payip_pending_client_code = ""
        session.payip_pending_filial = ""
        session.payip_pending_status = ""
        session.payip_pending_amount = ""
        session.payip_pending_day = ""
        session.payip_pending_tolerance = ""
        session.payip_pix_payloads = flow._extract_payip_pix_payloads(
            page.items,
            filial=filial,
            company_id=getattr(page, "company_id", ""),
        )
        title, criteria, empty_text = flow._payip_response_labels(
            action=action,
            filial=filial,
            invoice=invoice,
            client_code=client_code,
            status=status,
        )
        return self._with_post_result_navigation(
            sender,
            session,
            self._build_payip_payments_response(
                title=title,
                page=page,
                criteria=criteria,
                empty_text=empty_text,
            ),
                return_menu="finance_payip_menu",
                repeat_action=repeat_action,
            )

    def _open_payip_client_filter_or_search(
        self,
        *,
        sender: str,
        session: flow.LookupSession,
        client_code: str,
        filial: str = "",
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        normalized_client_code = flow._extract_payip_client_code_query(client_code) or flow._normalize_cod_pdv(client_code)
        normalized_filial = flow._resolve_payip_filial(filial or flow._extract_payip_filial_query(client_code))
        if not normalized_client_code or not normalized_filial:
            session.step = "finance_payip_awaiting_client_code"
            session.payip_pending_status = ""
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.sessions[sender] = session
            return self._build_payip_client_code_prompt(
                invalid_selection=True,
                pending_only=None,
            )

        session.step = "finance_payip_awaiting_client_filter"
        session.payip_pending_action = "client"
        session.payip_pending_invoice = ""
        session.payip_pending_client_code = normalized_client_code
        session.payip_pending_filial = normalized_filial
        session.payip_pending_status = ""
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.sessions[sender] = session
        return self._build_payip_client_filter_prompt()

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
        flow = _customer_flow_module()
        if self.payip_payments_service is None:
            raise RuntimeError(
                "PayIP ainda nao esta configurada. Configure PAYIP_BASE_URL, PAYIP_USERNAME, "
                "PAYIP_PASSWORD e PAYIP_COMPANY_IDS no .env."
            )
        if mfa_code:
            self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
        return self.payip_payments_service.list_payments(
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
        )

    def _build_payip_payments_response(
        self,
        *,
        title: str,
        page: Any,
        criteria: str,
        empty_text: str,
    ) -> flow.OutgoingMessage:
        flow = _customer_flow_module()
        items = tuple(getattr(page, "items", ()) or ())
        returned_count = getattr(page, "items_count", None)
        if returned_count is None:
            returned_count = len(items)

        lines = [title, ""]
        lines.append(criteria)
        lines.append(
            "Pagina: "
            f"{getattr(page, 'page', 1)} | "
            f"Itens: {flow._format_optional_count(returned_count)} | "
            f"Total API: {flow._format_optional_count(getattr(page, 'total_items', None))}"
        )

        if not items:
            lines.append("")
            lines.append(empty_text)
            lines.append("")
            lines.append(flow._result_hint_text(allow_back=True))
            return flow.OutgoingMessage(text="\n".join(lines))

        lines.append("")
        max_items = 5
        for index, payment in enumerate(items[:max_items], start=1):
            if index > 1:
                lines.append("")
            lines.extend(flow._format_payip_payment_block(payment, index=index if len(items) > 1 else None))

        pix_count = len(flow._extract_payip_pix_payloads(items[:max_items]))
        if pix_count:
            lines.append("")
            if pix_count == 1:
                lines.append("Para receber o codigo PIX copia e cola e o PDF em mensagem separada, envie PIX 1.")
            else:
                lines.append(f"Para copiar um PIX e receber o PDF, envie PIX 1 ate PIX {pix_count}.")

        if len(items) > max_items:
            lines.append("")
            lines.append(f"Mostrando 5 de {len(items)} pagamentos retornados nesta pagina.")
        lines.append("")
        lines.append(flow._result_hint_text(allow_back=True))
        return flow.OutgoingMessage(text="\n".join(lines))

    def handle_back_command(self, *, sender: str, session: Any) -> Any | None:
        if session.step == "finance_payip_awaiting_mfa":
            return self._set_step_and_return(
                sender=sender,
                session=session,
                step="finance_payip_menu",
                response=self.context._build_payip_menu(),
            )
        if session.step in PAYIP_FORM_STEPS:
            return self._set_step_and_return(
                sender=sender,
                session=session,
                step="finance_payip_menu",
                response=self.context._build_payip_menu(),
            )
        return None

    def _ensure_payip_access(self, *, sender: str, session: Any, decision: Any) -> Any | None:
        if self.context._can_use_payip_menu(decision):
            return None
        flow = _customer_flow_module()
        self.context.sessions[sender] = session
        return flow.OutgoingMessage(
            text=(
                "Esse menu de pagamentos PayIP esta liberado apenas para financeiro e administracao.\n"
                "Se quiser voltar, envie MENU."
            )
        )

    def _set_step_and_return(self, *, sender: str, session: Any, step: str, response: Any) -> Any:
        flow = _customer_flow_module()
        session.step = step
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.context.sessions[sender] = session
        return response
