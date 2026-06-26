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

    def handle_session(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        flow = _customer_flow_module()
        if not self.context._can_use_finance_menu(decision):
            self.context._reset_session(sender)
            return flow.OutgoingMessage(
                text="Esse menu e exclusivo do financeiro e da administracao.\nSe quiser voltar, envie MENU."
            )

        back_response = self._handle_back_command(
            sender=sender,
            session=session,
            normalized=normalized,
            decision=decision,
        )
        if back_response is not None:
            return back_response

        payip_response = self.payip_flow.handle_session_if_applicable(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )
        if payip_response is not None:
            return payip_response

        return self.context._handle_finance_session_impl(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

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
