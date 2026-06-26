from __future__ import annotations

from typing import Any


def _customer_flow_module() -> Any:
    from bot_api.services import customer_lookup_flow

    return customer_lookup_flow


class CriticaFlow:
    def __init__(self, context: Any) -> None:
        self.context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    def ensure_ready(self, decision: Any) -> Any | None:
        area_decision = self.context._decision_for_area(decision, "cliente")
        if not area_decision.allowed:
            return self.context._build_area_access_denied_response("cliente")
        if not self.context._can_use_critica(decision):
            flow = _customer_flow_module()
            return flow.OutgoingMessage(
                text=(
                    "Critica RN\n\n"
                    "Essa consulta esta liberada apenas para vendedores e gerentes de vendas."
                )
            )
        if self.context.critica_rn_service is None:
            flow = _customer_flow_module()
            return flow.OutgoingMessage(
                text=(
                    "A consulta de critica RN ainda nao esta configurada no bot.\n"
                    "Suba a planilha no painel admin e tente novamente."
                )
            )
        status = self.context.critica_rn_service.status()
        if not status.get("ready"):
            flow = _customer_flow_module()
            return flow.OutgoingMessage(
                text=(
                    "No momento, eu nao consegui acessar a base de critica RN.\n"
                    f"Detalhe: {status.get('last_error') or 'base indisponivel'}"
                )
            )
        return None

    def handle_command(
        self,
        *,
        sender: str,
        session: Any,
        text: str,
        normalized: str,
        decision: Any,
    ) -> Any:
        flow = _customer_flow_module()
        readiness_error = self.ensure_ready(decision)
        if readiness_error is not None:
            return readiness_error

        action = flow._parse_critica_action(normalized)
        parsed_date, date_was_explicit = flow._parse_critica_target_date(normalized)
        wants_pdf = flow._critica_wants_pdf(normalized)
        if action == "menu":
            session.step = "awaiting_critica_action"
            session.updated_at = flow.datetime.now(flow.timezone.utc)
            self.context.sessions[sender] = session
            return flow._build_critica_menu_response()

        if action == "nb":
            filial, cod_pdv = flow._parse_critica_nb_query(normalized)
            if not cod_pdv:
                return flow.OutgoingMessage(
                    text=(
                        "Informe o NB para consultar a critica RN.\n"
                        "Exemplos:\n"
                        "- critica nb 3 18008\n"
                        "- critica nb 18008"
                    )
                )
            target_date = parsed_date if date_was_explicit else None
            if wants_pdf:
                return self.context._with_post_result_navigation(
                    sender,
                    session,
                    self.context._build_critica_nb_pdf_response(
                        filial=filial,
                        cod_pdv=cod_pdv,
                        target_date=target_date,
                        decision=decision,
                    ),
                    return_menu="main",
                )
            return self.context._with_post_result_navigation(
                sender,
                session,
                self.context._build_critica_nb_response(
                    filial=filial,
                    cod_pdv=cod_pdv,
                    target_date=target_date,
                    decision=decision,
                ),
                return_menu="main",
            )

        target_date = parsed_date or flow.datetime.now(flow.LOCAL_TIMEZONE).date()
        normalized_tokens = set(normalized.replace(":", " ").split())
        if wants_pdf and flow._critica_wants_gv_summary_pdf(normalized):
            return self.context._with_post_result_navigation(
                sender,
                session,
                self.context._build_critica_gv_summary_pdf_response(
                    target_date=parsed_date if date_was_explicit else None,
                    decision=decision,
                ),
                return_menu="main",
            )
        if wants_pdf and "setor" in normalized_tokens:
            return self.context._with_post_result_navigation(
                sender,
                session,
                self.context._build_critica_sector_pdf_response(
                    target_date=target_date,
                    normalized_text=normalized,
                    decision=decision,
                ),
                return_menu="main",
            )
        if action == "problems":
            return self.context._with_post_result_navigation(
                sender,
                session,
                self.context._build_critica_summary_response(
                    target_date=target_date,
                    decision=decision,
                    title="Critica RN | Resumo",
                    footer_lines=(
                        "",
                        "Detalhes completos ficam no PDF.",
                        "- critica pdf",
                        "- critica pdf setor 400",
                        "- critica nb pdf 3 18008",
                    ),
                ),
                return_menu="main",
            )
        if action == "pdf":
            return self.context._with_post_result_navigation(
                sender,
                session,
                self.context._build_critica_pdf_response(
                    target_date=target_date,
                    decision=decision,
                ),
                return_menu="main",
            )
        return self.context._with_post_result_navigation(
            sender,
            session,
            self.context._build_critica_summary_response(
                target_date=target_date,
                decision=decision,
                title="Critica RN | Hoje" if "hoje" in normalized_tokens else "Critica RN",
            ),
            return_menu="main",
        )
