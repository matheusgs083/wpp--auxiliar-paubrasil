from __future__ import annotations

import unittest
from types import SimpleNamespace

from bot_api.services.flows.critica_flow import CriticaFlow
from bot_api.services.flows.finance_flow import FinanceFlow
from bot_api.services.flows.payip_flow import PayipFlow


class FakeFlowContext:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.sessions: dict[str, object] = {}
        critica_summary = SimpleNamespace(row_count=2, pedido_count=1, problem_row_count=1)
        self.critica_rn_service = SimpleNamespace(
            status=lambda: {"ready": True},
            get_pdf_report=lambda **kwargs: SimpleNamespace(
                summary=critica_summary,
                pdf_bytes=b"pdf",
                summary_pdf_bytes=b"summary-pdf",
            ),
        )
        self.finance_allowed = True

    def _handle_finance_session_impl(self, **kwargs: object) -> str:
        self.calls.append(("finance", kwargs))
        return "finance-result"

    def _handle_critica_command_impl(self, **kwargs: object) -> str:
        self.calls.append(("critica", kwargs))
        return "critica-result"

    def _decision_for_area(self, decision: object, area: str) -> object:
        self.calls.append(("area", {"area": area}))
        return SimpleNamespace(allowed=True)

    def _can_use_critica(self, decision: object) -> bool:
        return True

    def _with_post_result_navigation(
        self,
        sender: str,
        session: object,
        message: object,
        *,
        return_menu: str,
    ) -> object:
        self.calls.append(("post_nav", {"sender": sender, "return_menu": return_menu}))
        return message

    def _build_critica_pdf_response(self, **kwargs: object) -> str:
        self.calls.append(("critica_pdf", kwargs))
        return "critica-pdf-result"

    def _allowed_sectors(self, decision: object) -> None:
        return None

    def _allowed_gv_vdes(self, decision: object) -> None:
        return None

    def _can_use_finance_menu(self, decision: object) -> bool:
        return self.finance_allowed

    def _reset_session(self, sender: str) -> None:
        self.calls.append(("reset", {"sender": sender}))

    def _build_main_menu(self, decision: object) -> str:
        self.calls.append(("main_menu", {}))
        return "main-menu"

    def _build_finance_menu(self) -> str:
        self.calls.append(("finance_menu", {}))
        return "finance-menu"

    def _build_payip_menu(self) -> str:
        self.calls.append(("payip_menu", {}))
        return "payip-menu"


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

    def test_finance_flow_blocks_without_finance_access(self) -> None:
        context = FakeFlowContext()
        context.finance_allowed = False
        result = FinanceFlow(context).handle_session(
            sender="5583999999999",
            session=SimpleNamespace(step="finance_select_action"),
            text="resumo financeiro",
            normalized="resumo financeiro",
            decision=SimpleNamespace(),
        )

        self.assertIn("exclusivo do financeiro", result.text)
        self.assertEqual(context.calls[0][0], "reset")

    def test_finance_flow_handles_back_from_submenu(self) -> None:
        context = FakeFlowContext()
        session = SimpleNamespace(step="finance_select_due_bucket")
        result = FinanceFlow(context).handle_session(
            sender="5583999999999",
            session=session,
            text="A",
            normalized="a",
            decision=SimpleNamespace(),
        )

        self.assertEqual(result, "finance-menu")
        self.assertEqual(session.step, "finance_select_action")
        self.assertEqual(context.sessions["5583999999999"], session)

    def test_payip_flow_handles_back_to_payip_menu(self) -> None:
        context = FakeFlowContext()
        session = SimpleNamespace(step="finance_payip_charge_awaiting_amount")
        result = PayipFlow(context).handle_back_command(
            sender="5583999999999",
            session=session,
        )

        self.assertEqual(result, "payip-menu")
        self.assertEqual(session.step, "finance_payip_menu")
        self.assertEqual(context.sessions["5583999999999"], session)

    def test_critica_flow_opens_menu_after_readiness_check(self) -> None:
        context = FakeFlowContext()
        result = CriticaFlow(context).handle_command(
            sender="5583999999999",
            session=SimpleNamespace(step="awaiting_critica_action"),
            text="critica",
            normalized="critica",
            decision=SimpleNamespace(),
        )

        self.assertEqual(result.kind, "menu")
        self.assertEqual(result.title, "Critica RN")
        self.assertEqual(context.calls[0][0], "area")
        self.assertEqual(context.sessions["5583999999999"].step, "awaiting_critica_action")

    def test_critica_flow_routes_pdf_to_customer_flow_builder(self) -> None:
        context = FakeFlowContext()
        result = CriticaFlow(context).handle_command(
            sender="5583999999999",
            session=SimpleNamespace(step="awaiting_critica_action"),
            text="critica pdf",
            normalized="critica pdf",
            decision=SimpleNamespace(),
        )

        self.assertEqual(result.kind, "media")
        self.assertIn("Critica RN | PDF", result.text)
        self.assertEqual(context.calls[-1][0], "post_nav")


if __name__ == "__main__":
    unittest.main()
