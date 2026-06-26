from __future__ import annotations

import unittest
from types import SimpleNamespace

from bot_api.services.flows.critica_flow import CriticaFlow
from bot_api.services.flows.finance_flow import FinanceFlow


class FakeFlowContext:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _handle_finance_session_impl(self, **kwargs: object) -> str:
        self.calls.append(("finance", kwargs))
        return "finance-result"

    def _handle_critica_command_impl(self, **kwargs: object) -> str:
        self.calls.append(("critica", kwargs))
        return "critica-result"


class CustomerFlowModulesTest(unittest.TestCase):
    def test_finance_flow_delegates_to_customer_flow_context(self) -> None:
        context = FakeFlowContext()
        result = FinanceFlow(context).handle_session(
            sender="5583999999999",
            session=SimpleNamespace(step="finance_select_action"),
            text="resumo financeiro",
            normalized="resumo financeiro",
            decision=SimpleNamespace(),
        )

        self.assertEqual(result, "finance-result")
        self.assertEqual(context.calls[0][0], "finance")
        self.assertEqual(context.calls[0][1]["sender"], "5583999999999")

    def test_critica_flow_delegates_to_customer_flow_context(self) -> None:
        context = FakeFlowContext()
        result = CriticaFlow(context).handle_command(
            sender="5583999999999",
            session=SimpleNamespace(step="awaiting_critica_action"),
            text="critica pdf",
            normalized="critica pdf",
            decision=SimpleNamespace(),
        )

        self.assertEqual(result, "critica-result")
        self.assertEqual(context.calls[0][0], "critica")
        self.assertEqual(context.calls[0][1]["normalized"], "critica pdf")


if __name__ == "__main__":
    unittest.main()
