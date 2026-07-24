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
                    self._build_critica_nb_pdf_response(
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
                self._build_critica_nb_response(
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
                self._build_critica_gv_summary_pdf_response(
                    target_date=parsed_date if date_was_explicit else None,
                    decision=decision,
                ),
                return_menu="main",
            )
        if wants_pdf and "setor" in normalized_tokens:
            return self.context._with_post_result_navigation(
                sender,
                session,
                self._build_critica_sector_pdf_response(
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
                self._build_critica_summary_response(
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
                self._build_critica_pdf_response(
                    target_date=target_date,
                    decision=decision,
                ),
                return_menu="main",
            )
        return self.context._with_post_result_navigation(
            sender,
            session,
            self._build_critica_summary_response(
                target_date=target_date,
                decision=decision,
                title="Critica RN | Hoje" if "hoje" in normalized_tokens else "Critica RN",
            ),
            return_menu="main",
        )

    def _build_critica_summary_response(
        self,
        *,
        target_date: date,
        decision: AccessDecision,
        title: str,
        footer_lines: tuple[str, ...] = (),
    ) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        try:
            summary = self.critica_rn_service.get_summary(
                target_date=target_date,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
        except Exception:
            flow.logger.exception("Falha ao consultar resumo da critica RN")
            return flow.OutgoingMessage(text="Nao consegui consultar a critica RN agora.")

        if summary.row_count <= 0:
            return self._build_empty_critica_response(target_date=target_date, decision=decision)

        lines = [
            title,
            "",
            f"Data: {flow._format_display_date(target_date.isoformat())}",
            f"Atualizado em: {flow._format_display_date(summary.planilha_atualizada_em)}",
            "",
            "Resumo:",
            f"- Pedidos: {summary.pedido_count}",
            f"- Clientes: {summary.client_count}",
            f"- Itens: {summary.row_count}",
            f"- Pedidos com problema: {summary.problem_pedido_count}",
            f"- Valor dos pedidos: {flow._format_currency_brl(summary.total_pedido)}",
            f"- Peso total: {flow._format_quantity(summary.peso_total)}",
            f"- Total HL: {flow._format_quantity(summary.total_hectolitros)}",
            (
                "- Cestas HL: "
                f"NAB TT {flow._format_quantity(summary.nab_tt_hectolitros)} | "
                f"High End {flow._format_quantity(summary.high_end_hectolitros)} | "
                f"Cerveja TT {flow._format_quantity(summary.cerveja_tt_hectolitros)}"
            ),
            (
                "- Cestas HL: "
                f"Refri Zero {flow._format_quantity(summary.refri_zero_hectolitros)} | "
                f"Cerveja RGB {flow._format_quantity(summary.cerveja_rgb_hectolitros)} | "
                f"Cerveja OW {flow._format_quantity(summary.cerveja_ow_hectolitros)}"
            ),
            f"- Marketplace TT: {flow._format_currency_brl(summary.marketplace_tt_faturamento)}",
        ]
        if summary.operations:
            lines.append(f"- Operacoes: {', '.join(summary.operations)}")
        lines.extend(
            [
                "",
                "Possiveis problemas:",
                f"- Ocorrencias do relatorio: {summary.rows_with_critica}",
                f"- Produto duplicado no pedido: {summary.duplicated_row_count}",
                f"- Preco divergente: {summary.price_alert_count}",
                f"- Produto sem DPrecos: {summary.missing_price_count}",
                f"- Pedido acima da media: {summary.order_avg_alert_count}",
                f"- Cliente inadimplente: {summary.inadimplente_count}",
                f"- Multipack fora da segmentacao: {summary.multipack_violation_count}",
                f"- Mapa 1 / buffer: {summary.map_buffer_count}",
                f"- Mapa fora do vendedor: {summary.map_outside_count}",
                f"- Cond. pag. divergente: {summary.cond_divergence_count}",
                f"- Estouro de limite: {summary.limit_alert_count}",
            ]
        )
        if footer_lines:
            lines.extend(list(footer_lines))
        else:
            lines.extend(
                [
                    "",
                    "Atalhos:",
                    "- critica hoje",
                    "- critica pdf",
                    "- critica pdf setor 400",
                    "- critica nb pdf 3 18008",
                ]
            )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_critica_problems_response(
        self,
        *,
        target_date: date,
        decision: AccessDecision,
    ) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        try:
            summary = self.critica_rn_service.get_summary(
                target_date=target_date,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            records = self.critica_rn_service.list_problems(
                target_date=target_date,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=12,
            )
        except Exception:
            flow.logger.exception("Falha ao listar problemas da critica RN")
            return flow.OutgoingMessage(text="Nao consegui listar os problemas da critica RN agora.")

        if summary.row_count <= 0:
            return self._build_empty_critica_response(target_date=target_date, decision=decision)
        if not records:
            return flow.OutgoingMessage(
                text=(
                    "Critica RN | Possiveis problemas\n\n"
                    f"Data: {flow._format_display_date(target_date.isoformat())}\n"
                    "Nao encontrei problemas nos pedidos desse filtro.\n\n"
                    "Para gerar o PDF completo, envie critica pdf."
                )
            )

        lines = [
            "Critica RN | Possiveis problemas",
            "",
            f"Data: {flow._format_display_date(target_date.isoformat())}",
            f"Resumo: {summary.problem_pedido_count} pedido(s) com problema.",
            "",
        ]
        for index, record in enumerate(records, start=1):
            lines.extend(flow._format_critica_problem_block(record, index=index))
            if index != len(records):
                lines.append("")
        displayed_order_count = len({(record.filial, record.pedido) for record in records if record.filial and record.pedido})
        remaining = summary.problem_pedido_count - displayed_order_count
        if remaining > 0:
            lines.extend(
                [
                    "",
                    f"Mostrei {displayed_order_count} de {summary.problem_pedido_count} pedido(s) com problema.",
                    "Para ver tudo, envie critica pdf.",
                ]
            )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_critica_nb_response(
        self,
        *,
        filial: str,
        cod_pdv: str,
        target_date: date | None,
        decision: AccessDecision,
    ) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        try:
            records = self.critica_rn_service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                target_date=target_date,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=250,
            )
        except Exception:
            flow.logger.exception("Falha ao consultar critica RN por NB")
            return flow.OutgoingMessage(text="Nao consegui consultar esse NB na critica RN agora.")

        if not records:
            suffix = f" na revenda {filial}" if filial else ""
            date_suffix = f" em {flow._format_display_date(target_date.isoformat())}" if target_date else ""
            return flow.OutgoingMessage(
                text=(
                    "Critica RN | NB\n\n"
                    f"Nao encontrei itens para o NB {cod_pdv}{suffix}{date_suffix} dentro do seu acesso."
                )
            )

        first = records[0]
        pedido_totals: dict[tuple[str, str], flow.Decimal] = {}
        pedido_weights: dict[tuple[str, str], flow.Decimal] = {}
        pedido_conditions: dict[tuple[str, str], list[str]] = {}
        for record in records:
            pedido_key = (record.filial, record.pedido)
            pedido_totals[pedido_key] = record.total_pedido
            pedido_weights[pedido_key] = pedido_weights.get(pedido_key, flow.Decimal("0")) + record.peso_item
            condition_name = str(record.cond_pag_pedido or "").strip()
            if condition_name:
                existing_conditions = pedido_conditions.setdefault(pedido_key, [])
                if condition_name not in existing_conditions:
                    existing_conditions.append(condition_name)
        problem_count = len(
            {
                (record.filial, record.pedido)
                for record in records
                if record.possui_problema and record.filial and record.pedido
            }
        )
        total_pedidos = sum(pedido_totals.values(), flow.Decimal("0"))
        peso_total = sum((record.peso_item for record in records), flow.Decimal("0"))
        lines = [
            "Critica RN | NB",
            "",
            first.nome_pdv or f"NB {cod_pdv}",
            f"Operacao: {flow._format_critica_operation_name(first)} | Revenda: {first.filial} | NB: {first.cod_pdv} | Setor: {first.setor or '-'}",
        ]
        if target_date:
            lines.append(f"Data: {flow._format_display_date(target_date.isoformat())}")
        else:
            dates = sorted({record.data_pedido.isoformat() for record in records if record.data_pedido})
            if dates:
                lines.append(f"Data(s): {', '.join(flow._format_display_date(item) for item in dates[:3])}")
        lines.extend(
            [
                "",
                "Resumo:",
                f"- Pedidos: {len(pedido_totals)}",
                f"- Itens: {len(records)}",
                f"- Pedidos com problema: {problem_count}",
                f"- Valor dos pedidos: {flow._format_currency_brl(total_pedidos)}",
                f"- Peso total: {flow._format_weight_quantity(peso_total)}",
            ]
        )
        lines.extend(["", "Pedidos:"])
        for pedido_key, pedido_total in pedido_totals.items():
            pedido_number = pedido_key[1] or "-"
            pedido_weight = pedido_weights.get(pedido_key, flow.Decimal("0"))
            condition_names = pedido_conditions.get(pedido_key) or []
            condition_label = " | ".join(condition_names) if condition_names else "-"
            lines.append(
                f"- Pedido {pedido_number}: Valor {flow._format_currency_brl(pedido_total)} | "
                f"Peso {flow._format_weight_quantity(pedido_weight)} | Cond. Pag. {condition_label}"
            )
        lines.extend(
            [
                "",
                "Detalhes em PDF:",
                f"- critica nb pdf {first.filial} {first.cod_pdv}",
            ]
        )
        return flow.OutgoingMessage(text="\n".join(lines))

    def _build_critica_pdf_response(
        self,
        *,
        target_date: date,
        decision: AccessDecision,
    ) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        try:
            report = self.critica_rn_service.get_pdf_report(
                target_date=target_date,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=5000,
            )
            summary = report.summary
            if summary.row_count <= 0:
                return self._build_empty_critica_response(target_date=target_date, decision=decision)
            pdf_bytes = report.pdf_bytes
        except flow.CriticaPdfCurrentImportRequiredError as exc:
            return flow.OutgoingMessage(text=f"Critica RN | PDF\n\n{exc}")
        except Exception:
            flow.logger.exception("Falha ao gerar PDF da critica RN")
            return flow.OutgoingMessage(text="Nao consegui gerar o PDF da critica RN agora.")

        filename = f"critica-rn-{target_date.isoformat()}.pdf"
        text = (
            "Critica RN | PDF\n\n"
            f"Data: {flow._format_display_date(target_date.isoformat())}\n"
            f"Atualizado em: {flow._format_display_date(getattr(summary, 'planilha_atualizada_em', '-'))}\n"
            f"Pedidos: {summary.pedido_count} | Itens: {summary.row_count} | Pedidos com problema: {summary.problem_pedido_count}\n"
            "Enviei o PDF consolidado e o resumo.\n\n"
            f"{flow._result_hint_text(allow_back=True)}"
        )
        return flow._build_critica_pdf_media_response(
            text=text,
            main_pdf_bytes=pdf_bytes,
            main_caption=f"Critica RN {flow._format_display_date(target_date.isoformat())}",
            main_filename=filename,
            summary_pdf_bytes=report.summary_pdf_bytes,
            summary_caption=f"Critica RN Resumo {flow._format_display_date(target_date.isoformat())}",
            summary_filename=f"critica-rn-resumo-{target_date.isoformat()}.pdf",
        )

    def _build_critica_gv_summary_pdf_response(
        self,
        *,
        target_date: date | None,
        decision: AccessDecision,
    ) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        if not self._is_gerente_vendas(decision):
            return flow.OutgoingMessage(text="Esse PDF gerencial da critica e liberado apenas para GV.")
        try:
            report = self.critica_rn_service.get_gv_summary_pdf(
                target_date=target_date,
                allowed_sectors=None,
                allowed_gv_vdes=self._critica_gv_summary_allowed_gv_vdes(decision),
                limit=50000,
            )
            if report.summary.row_count <= 0:
                empty_date = target_date or report.summary.data_pedido or flow.datetime.now(flow.LOCAL_TIMEZONE).date()
                return self._build_empty_critica_response(target_date=empty_date, decision=decision)
        except flow.CriticaPdfCurrentImportRequiredError as exc:
            return flow.OutgoingMessage(text=f"Critica RN | PDF Gerencial GV\n\n{exc}")
        except Exception:
            flow.logger.exception("Falha ao gerar PDF gerencial da critica RN para GV")
            return flow.OutgoingMessage(text="Nao consegui gerar o PDF gerencial da critica RN agora.")

        report_date = target_date or report.summary.data_pedido
        report_date_label = flow._format_display_date(report_date.isoformat()) if report_date else "base atual"
        filename_date = report_date.isoformat() if report_date else "base-atual"
        filename = f"critica-rn-gv-resumo-{filename_date}.pdf"
        text = (
            "Critica RN | PDF Gerencial GV\n\n"
            f"Data: {report_date_label}\n"
            f"Pedidos: {report.summary.pedido_count} | Setores: {len({record.setor for record in report.records if record.setor})} | "
            f"Pedidos com problema: {report.summary.problem_pedido_count}\n"
            "Enviei o resumo gerencial separado por setor.\n\n"
            f"{flow._result_hint_text(allow_back=True)}"
        )
        return flow._build_critica_pdf_media_response(
            text=text,
            main_pdf_bytes=report.pdf_bytes,
            main_caption=f"Critica RN GV {report_date_label}",
            main_filename=filename,
            summary_pdf_bytes=b"",
            summary_caption="",
            summary_filename="",
        )

    def _critica_gv_summary_allowed_gv_vdes(self, decision: AccessDecision) -> list[str] | None:
        flow = _customer_flow_module()
        allowed_gv_vdes = self._allowed_gv_vdes(decision)
        if not allowed_gv_vdes:
            return allowed_gv_vdes

        gv_codes: set[str] = set()
        for scope_value in allowed_gv_vdes:
            normalized = flow.normalize_stored_scope_value(scope_value)
            pair = flow.split_scope_pair(normalized)
            gv_code = pair[1] if pair else flow.normalize_numeric_code(normalized)
            if gv_code:
                gv_codes.add(gv_code)

        if len(gv_codes) == 1:
            return [next(iter(gv_codes))]
        return allowed_gv_vdes

    def _build_critica_nb_pdf_response(
        self,
        *,
        filial: str,
        cod_pdv: str,
        target_date: date | None,
        decision: AccessDecision,
    ) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        try:
            report = self.critica_rn_service.get_pdf_report_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                target_date=target_date,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=2000,
            )
        except flow.CriticaPdfCurrentImportRequiredError as exc:
            return flow.OutgoingMessage(text=f"Critica RN | NB PDF\n\n{exc}")
        except Exception:
            flow.logger.exception("Falha ao gerar PDF da critica RN por NB")
            return flow.OutgoingMessage(text="Nao consegui gerar o PDF desse NB agora.")

        if report.summary.row_count <= 0 or not report.records:
            suffix = f" na revenda {filial}" if filial else ""
            date_suffix = f" em {flow._format_display_date(target_date.isoformat())}" if target_date else ""
            return flow.OutgoingMessage(
                text=(
                    "Critica RN | NB PDF\n\n"
                    f"Nao encontrei itens para o NB {cod_pdv}{suffix}{date_suffix} dentro do seu acesso."
                )
            )

        first = report.records[0]
        filename = (
            f"critica-rn-nb-{first.filial}-{first.cod_pdv}-{target_date.isoformat()}.pdf"
            if target_date
            else f"critica-rn-nb-{first.filial}-{first.cod_pdv}.pdf"
        )
        text = (
            "Critica RN | NB PDF\n\n"
            f"Cliente: {first.nome_pdv or f'NB {first.cod_pdv}'}\n"
            f"Revenda: {first.filial} | NB: {first.cod_pdv} | Pedidos: {report.summary.pedido_count} | Itens: {report.summary.row_count}\n"
            "Enviei o PDF detalhado e o resumo desse NB.\n\n"
            f"{flow._result_hint_text(allow_back=True)}"
        )
        return flow._build_critica_pdf_media_response(
            text=text,
            main_pdf_bytes=report.pdf_bytes,
            main_caption=f"Critica RN NB {first.cod_pdv}",
            main_filename=filename,
            summary_pdf_bytes=report.summary_pdf_bytes,
            summary_caption=f"Critica RN Resumo NB {first.cod_pdv}",
            summary_filename=filename.replace(".pdf", "-resumo.pdf"),
        )

    def _build_critica_sector_pdf_response(
        self,
        *,
        target_date: date,
        normalized_text: str,
        decision: AccessDecision,
    ) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        sector_scope, error_text = self._resolve_critica_pdf_sector_scope(
            target_date=target_date,
            normalized_text=normalized_text,
            decision=decision,
        )
        if error_text:
            return flow.OutgoingMessage(text=error_text)
        if not sector_scope:
            return flow.OutgoingMessage(text="Nao consegui identificar o setor para gerar o PDF.")

        try:
            report = self.critica_rn_service.get_pdf_report(
                target_date=target_date,
                allowed_sectors=[sector_scope],
                allowed_gv_vdes=None,
                limit=5000,
            )
        except flow.CriticaPdfCurrentImportRequiredError as exc:
            return flow.OutgoingMessage(text=f"Critica RN | PDF Setor\n\n{exc}")
        except Exception:
            flow.logger.exception("Falha ao gerar PDF da critica RN por setor")
            return flow.OutgoingMessage(text="Nao consegui gerar o PDF desse setor agora.")

        if report.summary.row_count <= 0:
            return flow.OutgoingMessage(
                text=(
                    "Critica RN | PDF Setor\n\n"
                    f"Nao encontrei pedidos para {flow._format_sector_scope_label(sector_scope)} "
                    f"em {flow._format_display_date(target_date.isoformat())}."
                )
            )

        filename = f"critica-rn-setor-{sector_scope.replace('_', '-')}-{target_date.isoformat()}.pdf"
        text = (
            "Critica RN | PDF Setor\n\n"
            f"Setor: {flow._format_sector_scope_label(sector_scope)}\n"
            f"Data: {flow._format_display_date(target_date.isoformat())}\n"
            f"Pedidos: {report.summary.pedido_count} | Itens: {report.summary.row_count}\n"
            "Enviei o PDF detalhado e o resumo desse setor.\n\n"
            f"{flow._result_hint_text(allow_back=True)}"
        )
        return flow._build_critica_pdf_media_response(
            text=text,
            main_pdf_bytes=report.pdf_bytes,
            main_caption=f"Critica RN {flow._format_sector_scope_label(sector_scope)}",
            main_filename=filename,
            summary_pdf_bytes=report.summary_pdf_bytes,
            summary_caption=f"Critica RN Resumo {flow._format_sector_scope_label(sector_scope)}",
            summary_filename=filename.replace(".pdf", "-resumo.pdf"),
        )

    def _resolve_critica_pdf_sector_scope(
        self,
        *,
        target_date: date,
        normalized_text: str,
        decision: AccessDecision,
    ) -> tuple[str, str]:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        explicit_scope, loose_sector_code = flow._parse_critica_sector_query(normalized_text)
        try:
            records = self.critica_rn_service.list_report_rows(
                target_date=target_date,
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
                limit=50000,
            )
        except Exception:
            flow.logger.exception("Falha ao listar setores disponiveis para PDF da critica RN")
            return "", "Nao consegui validar os setores disponiveis para esse PDF agora."

        available_scopes = sorted(
            {
                flow.normalize_stored_scope_value(record.seller_code or f"{record.filial}_{record.setor}")
                for record in records
                if flow.normalize_stored_scope_value(record.seller_code or f"{record.filial}_{record.setor}")
            },
            key=flow._sort_scope_code,
        )
        if not available_scopes:
            return "", (
                "Critica RN | PDF Setor\n\n"
                f"Nao encontrei setores com pedidos em {flow._format_display_date(target_date.isoformat())} dentro do seu acesso."
            )
        if explicit_scope:
            if explicit_scope in available_scopes:
                return explicit_scope, ""
            return "", (
                "Critica RN | PDF Setor\n\n"
                f"O setor {flow._format_sector_scope_label(explicit_scope)} nao apareceu na sua base para "
                f"{flow._format_display_date(target_date.isoformat())}."
            )
        if loose_sector_code:
            matching_scopes = [value for value in available_scopes if (flow.split_scope_pair(value) or ("", ""))[1] == loose_sector_code]
            if len(matching_scopes) == 1:
                return matching_scopes[0], ""
            if len(matching_scopes) > 1:
                options_text = ", ".join(flow._format_sector_scope_label(value) for value in matching_scopes[:5])
                return "", (
                    "Critica RN | PDF Setor\n\n"
                    f"Encontrei mais de um setor {loose_sector_code} na sua base: {options_text}.\n"
                    "Informe filial e setor. Exemplo: critica pdf setor 3/400"
                )
            return "", (
                "Critica RN | PDF Setor\n\n"
                f"Nao encontrei o setor {loose_sector_code} na sua base para {flow._format_display_date(target_date.isoformat())}."
            )
        if len(available_scopes) == 1:
            return available_scopes[0], ""
        preview = ", ".join(flow._format_sector_scope_label(value) for value in available_scopes[:5])
        return "", (
            "Critica RN | PDF Setor\n\n"
            "Informe o setor para gerar o PDF.\n"
            f"Exemplo: critica pdf setor {(flow.split_scope_pair(available_scopes[0]) or ('', '-'))[1]}\n"
            f"Setores com pedidos: {preview}"
        )

    def _build_empty_critica_response(self, *, target_date: date, decision: AccessDecision) -> Any:
        flow = _customer_flow_module()
        assert self.critica_rn_service is not None
        latest_text = ""
        try:
            latest = self.critica_rn_service.latest_date(
                allowed_sectors=self._allowed_sectors(decision),
                allowed_gv_vdes=self._allowed_gv_vdes(decision),
            )
            if latest is not None:
                latest_text = f"\nUltima data encontrada no seu acesso: {flow._format_display_date(latest.isoformat())}."
        except Exception:
            latest_text = ""
        return flow.OutgoingMessage(
            text=(
                "Critica RN\n\n"
                f"Nao encontrei pedidos para {flow._format_display_date(target_date.isoformat())} dentro do seu acesso."
                f"{latest_text}\n\n"
                "Envie critica para ver as opcoes."
            )
        )
