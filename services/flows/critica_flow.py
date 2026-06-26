from __future__ import annotations

from typing import Any


class CriticaFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def handle_command(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        return self.context._handle_critica_command_impl(
            sender=sender,
            session=session,
            text=text,
            normalized=normalized,
            decision=decision,
        )
