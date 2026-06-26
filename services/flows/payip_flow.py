from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


PAYIP_FORM_STEPS = {
    "finance_payip_awaiting_invoice",
    "finance_payip_awaiting_client_code",
    "finance_payip_awaiting_client_code_all",
    "finance_payip_awaiting_client_filter",
    "finance_payip_amount_day_awaiting_query",
    "finance_payip_statement_awaiting_period",
    "finance_payip_charge_awaiting_client",
    "finance_payip_charge_awaiting_amount",
    "finance_payip_charge_awaiting_due_date",
    "finance_payip_charge_confirm",
}


class PayipFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

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

    def _set_step_and_return(self, *, sender: str, session: Any, step: str, response: Any) -> Any:
        flow = _customer_flow_module()
        session.step = step
        session.updated_at = flow.datetime.now(flow.timezone.utc)
        self.context.sessions[sender] = session
        return response
