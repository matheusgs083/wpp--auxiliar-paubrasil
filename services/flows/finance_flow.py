from __future__ import annotations

from typing import Any


class FinanceFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def handle_session(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        return self.context._handle_finance_session_impl(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )

