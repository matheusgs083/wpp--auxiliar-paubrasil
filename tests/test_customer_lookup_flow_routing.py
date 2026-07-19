from __future__ import annotations

import sys
import unittest
from inspect import signature
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.models import IncomingMessage
from bot_api.integrations.payip_client import PayipError
from bot_api.services.customer_lookup_flow import (
    ComodatoRecord,
    DClienteRecord,
    INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS,
    INADIMPLENCIA_CONTEXT_SCOPE_BASE,
    InadimplenciaClientSummary,
    InadimplenciaRecord,
    LookupSession,
    GiroClientRecord,
    GiroFilialSummary,
    GiroManagementSummary,
    GiroSellerSummary,
    _current_visit_day_label,
)
from bot_api.services.dclientes_query_service import DClientesQueryService
from bot_api.services.recolha_request_service import RecolhaRequestService

from tests.test_support import (
    StubComodatosService,
    StubCriticaRnService,
    StubDocumentacaoPendenteService,
    StubGiroService,
    StubInadimplenciaService,
    StubPayipPaymentsService,
    StubPrazoLimiteService,
    StubQueryService,
    make_decision,
    make_flow,
)


class StubBoletosService:
    def __init__(self, records: list[SimpleNamespace]) -> None:
        self.records = records
        self.calls: list[dict[str, object]] = []

    def status(self) -> dict[str, bool]:
        return {"ready": True}

    def search_by_registration(self, **kwargs: object) -> list[SimpleNamespace]:
        self.calls.append(dict(kwargs))
        return list(self.records)


class CustomerLookupFlowRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.query_service = StubQueryService(ready=True)
        self.inadimplencia_service = StubInadimplenciaService(ready=True)
        self.giro_service = StubGiroService(ready=True)
        self.critica_service = StubCriticaRnService(ready=True)
        self.documentacao_service = StubDocumentacaoPendenteService(ready=True)
        self.prazo_limite_service = StubPrazoLimiteService(ready=True)
        self.payip_service = StubPayipPaymentsService()
        self.flow = make_flow(
            query_service=self.query_service,
            inadimplencia_service=self.inadimplencia_service,
            giro_service=self.giro_service,
            critica_rn_service=self.critica_service,
            documentacao_pendente_service=self.documentacao_service,
            prazo_limite_service=self.prazo_limite_service,
            payip_payments_service=self.payip_service,
        )

    def _make_boleto_pdf_bytes(self) -> bytes:
        import io

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def _make_boleto_records(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                filial="3",
                cod_pdv="11305",
                mapa="27848",
                nota_fiscal="167139",
                setor="401",
                gv="5",
                pagador="MARIA GABRIELY RAMOS FARIAS LTDA",
                data_documento=date(2026, 6, 12),
                vencimento=date(2026, 6, 18),
                valor_centavos=403525,
                nosso_numero="09/15630075670-3",
                pdf_bytes=self._make_boleto_pdf_bytes(),
            ),
            SimpleNamespace(
                filial="3",
                cod_pdv="11305",
                mapa="27849",
                nota_fiscal="168228",
                setor="401",
                gv="5",
                pagador="MARIA GABRIELY RAMOS FARIAS LTDA",
                data_documento=date(2026, 6, 20),
                vencimento=date(2026, 6, 22),
                valor_centavos=379500,
                nosso_numero="09/15630075671-1",
                pdf_bytes=self._make_boleto_pdf_bytes(),
            ),
        ]

    def test_dclientes_document_lookup_accepts_scope_filters(self) -> None:
        parameters = signature(DClientesQueryService.search_by_document).parameters

        self.assertIn("allowed_sectors", parameters)
        self.assertIn("allowed_gv_vdes", parameters)

    def test_boleto_multiple_selection_sends_all_merged(self) -> None:
        import base64
        import io

        from pypdf import PdfReader

        boletos_service = StubBoletosService(self._make_boleto_records())
        self.flow.boletos_service = boletos_service
        sender = "5511-boleto-merged"
        decision = make_decision(allowed=True, roles=("financeiro",))

        selection = self.flow.handle(IncomingMessage(sender=sender, text="boleto 3 11305"), decision)
        self.assertIn("TODOS JUNTOS", selection.text)
        self.assertIn("TODOS SEPARADOS", selection.text)

        response = self.flow.handle(IncomingMessage(sender=sender, text="todos juntos"), decision)

        self.assertEqual(response.kind, "media")
        self.assertEqual(response.media_filename, "boletos-3-11305.pdf")
        self.assertEqual(response.extra_media, ())
        self.assertIn("unico PDF", response.text)
        merged_pdf = base64.b64decode(response.media_url.split(",", 1)[1])
        reader = PdfReader(io.BytesIO(merged_pdf))
        self.assertEqual(len(reader.pages), 2)
        self.assertTrue(boletos_service.calls[-1].get("include_pdf"))

    def test_boleto_multiple_selection_sends_all_separate(self) -> None:
        boletos_service = StubBoletosService(self._make_boleto_records())
        self.flow.boletos_service = boletos_service
        sender = "5511-boleto-separate"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="boleto 3 11305"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="todos separados"), decision)

        self.assertEqual(response.kind, "media")
        self.assertEqual(response.media_filename, "boleto-3-11305-nf-167139.pdf")
        self.assertEqual(len(response.extra_media), 1)
        self.assertEqual(response.extra_media[0].media_filename, "boleto-3-11305-nf-168228.pdf")
        self.assertIn("separadamente", response.text)
        self.assertTrue(boletos_service.calls[-1].get("include_pdf"))

    def test_handle_routes_natural_inadimplencia_alias_to_search_menu(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="Inadimplência"),
            make_decision(allowed=True),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Consultar Inadimplencia")
        self.assertIn("Como voce quer procurar a inadimplencia?", response.text)
        self.assertEqual(len(response.options), 4)

    def test_handle_routes_abbreviated_inad_alias_to_search_menu(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="inad"),
            make_decision(allowed=True),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Consultar Inadimplencia")
        self.assertIn("Como voce quer procurar a inadimplencia?", response.text)

    def test_handle_seller_inad_menu_includes_visit_day_and_base(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="inad"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Cobranca da Carteira")
        self.assertEqual(
            [(option.shortcut, option.title) for option in response.options],
            [
                ("1", "Filial e NB"),
                ("2", "Nome do cliente"),
                ("3", "CPF ou CNPJ"),
                ("4", "Risco por dia"),
                ("5", "Vence amanha"),
                ("6", "Vence em 2 dias"),
                ("7", "Ver inadimplentes"),
            ],
        )
        self.assertIn("Vence amanha: 0 cliente(s) | R$ 0,00", response.text)
        self.assertIn("Vence em 2 dias: 0 cliente(s) | R$ 0,00", response.text)
        self.assertIn("inad segunda", response.footer)
        self.assertIn("inad santa maria", response.footer)

    def test_handle_critica_hoje_uses_user_scope(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica hoje"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",), gv_vdes=("3_5",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Critica RN | Hoje", response.text)
        self.assertIn("Pedidos: 2", response.text)
        self.assertEqual(self.critica_service.summary_calls[0]["allowed_sectors"], ["3_400"])
        self.assertEqual(self.critica_service.summary_calls[0]["allowed_gv_vdes"], ["3_5"])

    def test_handle_critica_menu_accepts_number_selection(self) -> None:
        menu = self.flow.handle(
            IncomingMessage(sender="5511", text="critica"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )
        self.assertEqual(menu.kind, "menu")
        self.assertIn("Resumo rapido por mensagem", menu.text)
        self.assertNotIn("critica nb 3 18008", menu.text)
        self.assertEqual(
            [(option.shortcut, option.title) for option in menu.options],
            [
                ("1", "Critica hoje"),
                ("2", "PDF geral"),
                ("3", "PDF por setor"),
                ("4", "PDF por NB"),
            ],
        )

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="2"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "media")
        self.assertTrue(response.media_url.startswith("data:application/pdf;base64,"))
        self.assertEqual(len(self.critica_service.pdf_report_calls), 1)

    def test_handle_critica_nb_searches_by_filial_and_nb(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica nb 3 18008"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("POSTO PAIZAO", response.text)
        self.assertIn("Setor: 400", response.text)
        self.assertIn("Pedidos:", response.text)
        self.assertIn("Peso 25,00", response.text)
        self.assertIn("Cond. Pag. PROMO 21 DIAS", response.text)
        self.assertIn("Detalhes em PDF:", response.text)
        self.assertIn("critica nb pdf 3 18008", response.text)
        self.assertEqual(self.critica_service.registration_calls[0]["filial"], "3")
        self.assertEqual(self.critica_service.registration_calls[0]["cod_pdv"], "18008")
        self.assertIsNone(self.critica_service.registration_calls[0]["target_date"])

    def test_handle_critica_nb_pdf_returns_document_media(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica nb pdf 3 18008"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "media")
        self.assertTrue(response.media_url.startswith("data:application/pdf;base64,"))
        self.assertEqual(response.media_filename, "critica-rn-nb-3-18008.pdf")
        self.assertEqual(len(response.extra_media), 1)
        self.assertEqual(response.extra_media[0].media_filename, "critica-rn-nb-3-18008-resumo.pdf")
        self.assertEqual(len(self.critica_service.registration_pdf_calls), 1)
        self.assertEqual(self.critica_service.registration_pdf_calls[0]["filial"], "3")
        self.assertEqual(self.critica_service.registration_pdf_calls[0]["cod_pdv"], "18008")

    def test_handle_critica_nb_pdf_blocks_without_today_upload(self) -> None:
        self.critica_service.current_import_available = False

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica nb pdf 3 18008"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Critica RN | NB PDF", response.text)
        self.assertIn("importe os relatorios de critica de hoje", response.text)
        self.assertEqual(len(self.critica_service.registration_pdf_calls), 0)

    def test_handle_critica_pdf_returns_document_media(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf 03/06/2026"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5",)),
        )

        self.assertEqual(response.kind, "media")
        self.assertTrue(response.media_url.startswith("data:application/pdf;base64,"))
        self.assertEqual(response.media_type, "document")
        self.assertEqual(response.media_filename, "critica-rn-2026-06-03.pdf")
        self.assertEqual(len(response.extra_media), 1)
        self.assertEqual(response.extra_media[0].media_filename, "critica-rn-resumo-2026-06-03.pdf")
        self.assertEqual(len(self.critica_service.pdf_report_calls), 1)
        self.assertEqual(self.critica_service.pdf_report_calls[0]["limit"], 5000)

    def test_handle_critica_pdf_blocks_without_today_upload(self) -> None:
        self.critica_service.current_import_available = False

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf 03/06/2026"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Critica RN | PDF", response.text)
        self.assertIn("importe os relatorios de critica de hoje", response.text)
        self.assertEqual(len(self.critica_service.pdf_report_calls), 0)

    def test_handle_critica_pdf_setor_for_gv_filters_to_requested_sector(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf setor 400 03/06/2026"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5",)),
        )

        self.assertEqual(response.kind, "media")
        self.assertEqual(response.media_filename, "critica-rn-setor-3-400-2026-06-03.pdf")
        self.assertEqual(len(response.extra_media), 1)
        self.assertEqual(response.extra_media[0].media_filename, "critica-rn-setor-3-400-2026-06-03-resumo.pdf")
        self.assertEqual(self.critica_service.report_calls[0]["target_date"], date(2026, 6, 3))
        self.assertEqual(self.critica_service.pdf_report_calls[-1]["allowed_sectors"], ["3_400"])
        self.assertIsNone(self.critica_service.pdf_report_calls[-1]["allowed_gv_vdes"])

    def test_handle_critica_pdf_setor_blocks_without_today_upload(self) -> None:
        self.critica_service.current_import_available = False

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf setor 400 03/06/2026"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Critica RN | PDF Setor", response.text)
        self.assertIn("importe os relatorios de critica de hoje", response.text)
        self.assertEqual(len(self.critica_service.pdf_report_calls), 0)

    def test_handle_critica_pdf_gv_returns_manager_summary(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf gv 03/06/2026"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5",)),
        )

        self.assertEqual(response.kind, "media")
        self.assertEqual(response.media_filename, "critica-rn-gv-resumo-2026-06-03.pdf")
        self.assertEqual(len(response.extra_media), 0)
        self.assertEqual(len(self.critica_service.gv_summary_pdf_calls), 1)
        self.assertEqual(self.critica_service.gv_summary_pdf_calls[0]["allowed_gv_vdes"], ["5"])

    def test_handle_critica_pdf_gv_blocks_without_today_upload(self) -> None:
        self.critica_service.current_import_available = False

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf gv 03/06/2026"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Critica RN | PDF Gerencial GV", response.text)
        self.assertIn("importe os relatorios de critica de hoje", response.text)
        self.assertEqual(len(self.critica_service.gv_summary_pdf_calls), 0)

    def test_handle_critica_pdf_gv_expands_same_manager_across_filiais(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf gv 03/06/2026"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5", "4_5", "51_5")),
        )

        self.assertEqual(response.kind, "media")
        self.assertEqual(response.media_filename, "critica-rn-gv-resumo-2026-06-03.pdf")
        self.assertEqual(len(self.critica_service.gv_summary_pdf_calls), 1)
        self.assertEqual(self.critica_service.gv_summary_pdf_calls[0]["allowed_gv_vdes"], ["5"])

    def test_handle_critica_pdf_gv_without_date_uses_current_base_all_filiais(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf gv"),
            make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_5", "4_5")),
        )

        self.assertEqual(response.kind, "media")
        self.assertEqual(response.media_filename, "critica-rn-gv-resumo-2026-06-03.pdf")
        self.assertEqual(len(self.critica_service.gv_summary_pdf_calls), 1)
        self.assertIsNone(self.critica_service.gv_summary_pdf_calls[0]["target_date"])
        self.assertIsNone(self.critica_service.gv_summary_pdf_calls[0]["allowed_sectors"])
        self.assertEqual(self.critica_service.gv_summary_pdf_calls[0]["allowed_gv_vdes"], ["5"])

    def test_handle_critica_pdf_gv_denies_seller(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="critica pdf gv 03/06/2026"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("apenas para GV", response.text)
        self.assertEqual(len(self.critica_service.gv_summary_pdf_calls), 0)

    def test_handle_critica_denies_non_seller_and_non_gv_roles(self) -> None:
        for role in ("financeiro", "admin", "diretor_comercial"):
            with self.subTest(role=role):
                response = self.flow.handle(
                    IncomingMessage(sender=f"5511-{role}", text="critica pdf 03/06/2026"),
                    make_decision(allowed=True, roles=(role,), gv_vdes=("dc:3",) if role == "diretor_comercial" else ()),
                )

                self.assertEqual(response.kind, "text")
                self.assertIn("apenas para vendedores e gerentes de vendas", response.text)

        self.assertEqual(len(self.critica_service.pdf_report_calls), 0)
        self.assertEqual(len(self.critica_service.summary_calls), 0)
        self.assertEqual(len(self.critica_service.problem_calls), 0)
        self.assertEqual(len(self.critica_service.registration_calls), 0)

    def test_handle_critica_existing_menu_session_denies_non_seller_and_non_gv(self) -> None:
        self.flow.sessions["5511-financeiro-menu"] = LookupSession(step="awaiting_critica_action")

        response = self.flow.handle(
            IncomingMessage(sender="5511-financeiro-menu", text="2"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("apenas para vendedores e gerentes de vendas", response.text)
        self.assertEqual(len(self.critica_service.problem_calls), 0)

    def test_handle_seller_inad_menu_due_tomorrow_lists_scope_clients(self) -> None:
        sender = "5511-venc-amanha"
        self.inadimplencia_service.client_summaries_in_scope = [
            InadimplenciaClientSummary(
                filial="3",
                cod_pdv="111",
                nome="Cliente Alpha",
                title_count=1,
                total_pendente="20,00",
                planilha_atualizada_em="2026-04-15",
            ),
            InadimplenciaClientSummary(
                filial="3",
                cod_pdv="222",
                nome="Cliente Beta",
                title_count=1,
                total_pendente="15,00",
                planilha_atualizada_em="2026-04-15",
            )
        ]

        self.flow.handle(
            IncomingMessage(sender=sender, text="inad"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )
        response = self.flow.handle(
            IncomingMessage(sender=sender, text="5"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertIn("vencem amanha", response.text)
        self.assertEqual(self.inadimplencia_service.client_summaries_in_scope_calls[-1]["due_bucket"], "tomorrow")

    def test_handle_routes_natural_giro_phrase_to_search_menu(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="consultar giro"),
            make_decision(allowed=True),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Consultar Giro")
        self.assertIn("Como voce quer procurar o giro?", response.text)
        self.assertEqual(len(response.options), 3)

    def test_handle_seller_giro_menu_includes_giro_zero_base_option(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511-giro-menu", text="giro"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Consultar Giro")
        self.assertEqual(
            [(option.shortcut, option.title) for option in response.options],
            [
                ("1", "Filial e NB"),
                ("2", "Nome do cliente"),
                ("3", "CPF ou CNPJ"),
                ("4", "Giro por dia"),
                ("5", "Giro Zero da Base"),
            ],
        )

    def test_handle_giro_zero_base_shortcut_returns_scoped_clients(self) -> None:
        sender = "5511-giro-zero"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.giro_service.zero_base_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="12249",
                nome="BAR DO MOTORISTA",
                setor="400",
                revenda="PATOS",
                total_caixas="2",
                gap_caixas="4",
                gap_litrinho="4",
                gap_inteira="0",
                gap_litrao="0",
                planilha_atualizada_em="15/04/2026",
            ),
            SimpleNamespace(
                filial="3",
                cod_pdv="9725",
                nome="BAR DA LENA",
                setor="400",
                revenda="PATOS",
                total_caixas="3",
                gap_caixas="6",
                gap_litrinho="2",
                gap_inteira="0",
                gap_litrao="4",
                planilha_atualizada_em="15/04/2026",
            ),
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="giro"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="giro zero"), decision)

        self.assertEqual(response.kind, "text")
        self.assertIn("Giro Zero da Base", response.text)
        self.assertIn("Regra: faltam caixas = caixas * 2", response.text)
        self.assertIn("Clientes: 2 | Caixas: 5 | Faltam: 10", response.text)
        self.assertIn("Setor 400", response.text)
        self.assertIn("1) BAR DA LENA | Cod 9725", response.text)
        self.assertIn("Base: 3 | Falta: 6", response.text)
        self.assertIn("Tipo: Litrinho 2, Litrao 4", response.text)
        self.assertIn("2) BAR DO MOTORISTA | Cod 12249", response.text)
        self.assertIn("Base: 2 | Falta: 4", response.text)
        self.assertIn("Tipo: Litrinho 4", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertEqual(len(self.giro_service.zero_base_calls), 1)
        self.assertEqual(self.giro_service.zero_base_calls[0]["allowed_sectors"], ["3_400"])

    def test_handle_documentacao_main_menu_shortcut_opens_search_menu(self) -> None:
        sender = "5511-doc-menu"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="4"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Documentacao Pendente")
        self.assertEqual(
            [(option.shortcut, option.title) for option in response.options],
            [
                ("1", "Filial e NB"),
                ("2", "Nome do cliente"),
                ("3", "CPF ou CNPJ"),
                ("4", "Pendencia por dia"),
            ],
        )
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_search_mode")
        self.assertEqual(self.flow.sessions[sender].search_context, "documentacao")

    def test_idle_direct_registration_prioritizes_customer_lookup_before_menu_shortcut(self) -> None:
        sender = "5511-idle-direct-client"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.query_service.registration_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="16883",
                razao_social="CLIENTE TESTE LTDA",
                nome_fantasia="CLIENTE TESTE",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="Ativo",
                cidade="PATOS",
                cond_pag_atual="505",
                limite_credito="0",
                total_pendente="0",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-07-02 08:00:00 UTC",
            )
        ]

        response = self.flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)

        self.assertEqual(response.kind, "text")
        self.assertIn("CLIENTE TESTE", response.text)
        self.assertEqual(self.query_service.registration_calls[-1]["filial"], "3")
        self.assertEqual(self.query_service.registration_calls[-1]["cod_pdv"], "16883")
        self.assertEqual(self.giro_service.search_calls, [])

    def test_direct_registration_inside_giro_menu_keeps_giro_context(self) -> None:
        sender = "5511-giro-direct-giro"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.query_service.registration_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="16883",
                razao_social="CLIENTE TESTE LTDA",
                nome_fantasia="CLIENTE TESTE",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="Ativo",
                cidade="PATOS",
                cond_pag_atual="505",
                limite_credito="0",
                total_pendente="0",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-07-02 08:00:00 UTC",
            )
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="3",
                cod_pdv="16883",
                nome="CLIENTE GIRO",
                setor="400",
                revenda="PATOS",
                total_litrinho="2",
                real_litrinho="0",
                gap_litrinho="4",
                giro_litrinho="0",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="0",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="0",
                planilha_atualizada_em="2026-07-02",
            )
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="giro"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)

        self.assertEqual(response.kind, "text")
        self.assertIn("giro", response.text.lower())
        self.assertEqual(self.giro_service.search_calls[-1]["filial"], "3")
        self.assertEqual(self.giro_service.search_calls[-1]["cod_pdv"], "16883")

    def test_handle_documentacao_visit_day_shortcut_opens_day_menu(self) -> None:
        sender = "5511-doc-dia"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.query_service.visit_days = ["SEG/", "QUI/"]

        _ = self.flow.handle(
            IncomingMessage(sender=sender, text="4"),
            decision,
        )
        response = self.flow.handle(
            IncomingMessage(sender=sender, text="4"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Documentacao por Dia")
        self.assertIn("Qual dia voce quer consultar", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_documentacao_visit_day_selection")
        self.assertEqual(self.flow.sessions[sender].visit_day_options, ("SEG/", "QUI/"))

    def test_handle_documentacao_visit_day_selection_builds_response(self) -> None:
        sender = "5511-doc-seg"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.query_service.visit_days = ["SEG/", "QUI/"]
        self.documentacao_service.visit_day_summary = SimpleNamespace(
            monitored_client_count=10,
            pending_client_count=2,
            pending_document_count=4,
            contrato_social_pendentes=1,
            cpf_pendentes=1,
            rg_pendentes=0,
            comprovante_residencia_pendentes=1,
            fachada_pendentes=1,
            ficha_cadastro_pendentes=1,
            planilha_atualizada_em="2026-04-20",
        )
        self.documentacao_service.pending_by_visit_day = [
            SimpleNamespace(
                filial="3",
                cod_pdv="12249",
                nome="BAR DO MOTORISTA",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="SEG/",
                contrato_social="OK",
                cpf="Nok",
                rg="OK",
                comprovante_residencia="Nok",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=2,
                pending_docs=("Cpf", "Comprovante de residencia"),
                planilha_atualizada_em="2026-04-20",
            )
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="4"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="4"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="1"), decision)

        self.assertEqual(response.kind, "text")
        self.assertIn("Documentacao pendente em Segunda", response.text)
        self.assertIn("Clientes monitorados: 10", response.text)
        self.assertIn("Clientes com pendencia: 2", response.text)
        self.assertIn("Codigo 12249 | BAR DO MOTORISTA | Pendencias 2", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertEqual(len(self.documentacao_service.visit_day_summary_calls), 1)
        self.assertEqual(self.documentacao_service.visit_day_summary_calls[0]["visit_day"], "SEG/")

    def test_handle_manager_documentacao_visit_day_groups_by_sector(self) -> None:
        sender = "5511-doc-gv"
        decision = make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_4",))
        self.query_service.visit_days = ["QUI/"]
        self.documentacao_service.visit_day_summary = SimpleNamespace(
            monitored_client_count=30,
            pending_client_count=3,
            pending_document_count=7,
            contrato_social_pendentes=2,
            cpf_pendentes=1,
            rg_pendentes=1,
            comprovante_residencia_pendentes=2,
            fachada_pendentes=1,
            ficha_cadastro_pendentes=3,
            planilha_atualizada_em="2026-05-14",
        )
        self.documentacao_service.pending_by_visit_day = [
            SimpleNamespace(
                filial="3",
                cod_pdv="10001",
                nome="CLIENTE A",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="QUI/",
                contrato_social="Nok",
                cpf="OK",
                rg="OK",
                comprovante_residencia="Nok",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=2,
                pending_docs=("contrato_social", "comprovante_residencia"),
                planilha_atualizada_em="2026-05-14",
            ),
            SimpleNamespace(
                filial="3",
                cod_pdv="10002",
                nome="CLIENTE B",
                setor="401",
                seller_code="3_401",
                manager_code="3_4",
                visit_day="QUI/",
                contrato_social="OK",
                cpf="Nok",
                rg="OK",
                comprovante_residencia="OK",
                fachada="Nok",
                ficha_cadastro="Nok",
                pending_count=2,
                pending_docs=("cpf", "fachada"),
                planilha_atualizada_em="2026-05-14",
            ),
        ]

        response = self.flow.handle(IncomingMessage(sender=sender, text="documentacao quinta"), decision)

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Documentacao por Setor")
        self.assertIn("Setores com pendencia: 2", response.text)
        self.assertEqual([(option.shortcut, option.title) for option in response.options], [
            ("1", "Filial 3 | Setor 400"),
            ("2", "Filial 3 | Setor 401"),
        ])
        self.assertEqual(self.flow.sessions[sender].step, "documentacao_select_visit_sector")

        detail = self.flow.handle(IncomingMessage(sender=sender, text="2"), decision)

        self.assertEqual(detail.kind, "text")
        self.assertIn("CLIENTE B", detail.text)
        self.assertIn("Falta: Cpf, Fachada", detail.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertEqual(self.flow.sessions[sender].return_menu, "documentacao_visit_sector")

    def test_handle_director_documentacao_visit_day_groups_by_gv_then_sector(self) -> None:
        sender = "5511-doc-dc"
        decision = make_decision(
            allowed=True,
            roles=("diretor_comercial",),
            gv_vdes=("dc:3_1",),
        )
        self.query_service.visit_days = ["QUI/"]
        self.documentacao_service.visit_day_summary = SimpleNamespace(
            monitored_client_count=50,
            pending_client_count=2,
            pending_document_count=4,
            contrato_social_pendentes=1,
            cpf_pendentes=1,
            rg_pendentes=0,
            comprovante_residencia_pendentes=1,
            fachada_pendentes=1,
            ficha_cadastro_pendentes=2,
            planilha_atualizada_em="2026-05-14",
        )
        self.documentacao_service.pending_by_visit_day = [
            SimpleNamespace(
                filial="3",
                cod_pdv="10001",
                nome="CLIENTE GV4",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="QUI/",
                contrato_social="Nok",
                cpf="OK",
                rg="OK",
                comprovante_residencia="OK",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=1,
                pending_docs=("contrato_social",),
                planilha_atualizada_em="2026-05-14",
            ),
            SimpleNamespace(
                filial="3",
                cod_pdv="10002",
                nome="CLIENTE GV5",
                setor="500",
                seller_code="3_500",
                manager_code="3_5",
                visit_day="QUI/",
                contrato_social="OK",
                cpf="Nok",
                rg="OK",
                comprovante_residencia="Nok",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=2,
                pending_docs=("cpf", "comprovante_residencia"),
                planilha_atualizada_em="2026-05-14",
            ),
        ]

        gv_menu = self.flow.handle(IncomingMessage(sender=sender, text="documentacao quinta"), decision)

        self.assertEqual(gv_menu.kind, "menu")
        self.assertEqual(gv_menu.title, "Documentacao por Dia")
        self.assertIn("GVs com pendencia documental: 2", gv_menu.text)
        self.assertEqual([(option.shortcut, option.title) for option in gv_menu.options], [
            ("1", "Filial 3 | GV 4"),
            ("2", "Filial 3 | GV 5"),
        ])
        self.assertEqual(self.flow.sessions[sender].step, "documentacao_select_visit_gv")

        sector_menu = self.flow.handle(IncomingMessage(sender=sender, text="2"), decision)

        self.assertEqual(sector_menu.kind, "menu")
        self.assertEqual(sector_menu.title, "Documentacao por Setor")
        self.assertIn("Filial 3 | GV 5", sector_menu.text)
        self.assertEqual([(option.shortcut, option.title) for option in sector_menu.options], [
            ("1", "Filial 3 | Setor 500"),
        ])

        detail = self.flow.handle(IncomingMessage(sender=sender, text="1"), decision)

        self.assertEqual(detail.kind, "text")
        self.assertIn("CLIENTE GV5", detail.text)
        self.assertIn("Falta: Cpf, Comprovante de residencia", detail.text)

    def test_finance_menu_includes_prazo_limite_option(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511-fin-menu", text="financeiro"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Financeiro")
        self.assertEqual(response.options[-3].shortcut, "8")
        self.assertEqual(response.options[-3].title, "Prazo e Limite")
        self.assertEqual(response.options[-2].shortcut, "9")
        self.assertEqual(response.options[-2].title, "Pagamentos PayIP")
        self.assertEqual(response.options[-1].shortcut, "10")
        self.assertEqual(response.options[-1].title, "Solicitacoes de Recolha")

    def test_seller_recolha_inline_request_records_csv(self) -> None:
        registration = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="O COMILAO LTDA",
            nome_fantasia="O COMILAO",
            telefone="",
            dia_visita="SEG/",
            vendedor="400",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=0,
            ultima_atualizacao_tabela="",
        )
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[registration]),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-recolha-seller"

            confirmation = flow.handle(
                IncomingMessage(sender=sender, text="recolha 9845 | recolha total | enviar recibo"),
                decision,
            )

            self.assertIn("Solicitacao de Recolha", confirmation.text)
            self.assertIn("O COMILAO", confirmation.text)
            self.assertIn("recolha total", confirmation.text)
            self.assertEqual(flow.sessions[sender].step, "recolha_confirm")

            result = flow.handle(IncomingMessage(sender=sender, text="confirmar"), decision)

            self.assertIn("Solicitacao de Recolha registrada", result.text)
            self.assertIn("O CSV ja esta atualizado", result.text)
            records = recolha_service.list_requests()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].revenda, "Patos")
            self.assertEqual(records[0].setor, "400")
            self.assertEqual(records[0].rn, "400")
            self.assertEqual(records[0].nb, "9845")
            self.assertEqual(records[0].comodato, "recolha total")
            self.assertEqual(records[0].obs, "enviar recibo")

    def test_seller_recolha_allows_selecting_multiple_comodatos(self) -> None:
        registration = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="O COMILAO LTDA",
            nome_fantasia="O COMILAO",
            telefone="",
            dia_visita="SEG/",
            vendedor="400",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=2,
            ultima_atualizacao_tabela="",
        )
        comodatos = [
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato="720268",
                material="Freezer",
                sub_tipo_material="Visa Cooler",
                saldo="1",
                planilha_atualizada_em="19/05/2026",
            ),
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato="102291",
                material="Mesa",
                sub_tipo_material="Jogo de mesa",
                saldo="5",
                planilha_atualizada_em="19/05/2026",
            ),
        ]
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[registration]),
                comodatos_service=StubComodatosService(ready=True, search_records=comodatos),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-recolha-select"

            _ = flow.handle(IncomingMessage(sender=sender, text="recolha"), decision)
            prompt = flow.handle(IncomingMessage(sender=sender, text="9845"), decision)

            self.assertIn("*Comodatos pendentes:*", prompt.text)
            self.assertIn("1. Comodato 720268", prompt.text)
            self.assertIn("2. Comodato 102291", prompt.text)
            self.assertIn("Envie TODOS", prompt.text)

            obs_prompt = flow.handle(IncomingMessage(sender=sender, text="1,2"), decision)

            self.assertIn("*Observacao:*", obs_prompt.text)
            self.assertIn("Comodato 720268", flow.sessions[sender].recolha_comodato)
            self.assertIn("Comodato 102291", flow.sessions[sender].recolha_comodato)

            confirmation = flow.handle(IncomingMessage(sender=sender, text="sem obs"), decision)

            self.assertIn("Comodato 720268", confirmation.text)
            self.assertIn("Comodato 102291", confirmation.text)

            result = flow.handle(IncomingMessage(sender=sender, text="confirmar"), decision)

            self.assertIn("Solicitacao de Recolha registrada", result.text)
            records = recolha_service.list_requests()
            self.assertEqual(len(records), 2)
            comodatos_registrados = " | ".join(record.comodato for record in records)
            self.assertIn("Comodato 720268", comodatos_registrados)
            self.assertIn("Comodato 102291", comodatos_registrados)

    def test_seller_recolha_prompt_lists_all_comodatos(self) -> None:
        registration = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="O COMILAO LTDA",
            nome_fantasia="O COMILAO",
            telefone="",
            dia_visita="SEG/",
            vendedor="400",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=25,
            ultima_atualizacao_tabela="",
        )
        comodatos = [
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato=str(720000 + index),
                material="Freezer",
                sub_tipo_material="Visa Cooler",
                saldo="1",
                planilha_atualizada_em="19/05/2026",
            )
            for index in range(1, 26)
        ]
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            comodatos_service = StubComodatosService(ready=True, search_records=comodatos)
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[registration]),
                comodatos_service=comodatos_service,
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-recolha-all-options"

            _ = flow.handle(IncomingMessage(sender=sender, text="recolha"), decision)
            prompt = flow.handle(IncomingMessage(sender=sender, text="9845"), decision)

            self.assertIn("1. Comodato 720001", prompt.text)
            self.assertIn("25. Comodato 720025", prompt.text)
            self.assertNotIn("mais 5", prompt.text)
            self.assertEqual(comodatos_service.search_calls[-1]["limit"], 1000)

    def test_seller_can_start_recolha_from_comodato_result_shortcut(self) -> None:
        registration = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="O COMILAO LTDA",
            nome_fantasia="O COMILAO",
            telefone="",
            dia_visita="SEG/",
            vendedor="400",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=2,
            ultima_atualizacao_tabela="",
        )
        comodatos = [
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato="720268",
                material="Freezer",
                sub_tipo_material="Visa Cooler",
                saldo="1",
                planilha_atualizada_em="19/05/2026",
            ),
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato="102291",
                material="Mesa",
                sub_tipo_material="Jogo de mesa",
                saldo="5",
                planilha_atualizada_em="19/05/2026",
            ),
        ]
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[registration]),
                comodatos_service=StubComodatosService(ready=True, search_records=comodatos),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-recolha-from-comodato"

            _ = flow.handle(IncomingMessage(sender=sender, text="comodatos"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="1"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="3"), decision)
            comodato_response = flow.handle(IncomingMessage(sender=sender, text="9845"), decision)

            self.assertIn("*Atalho para recolha:*", comodato_response.text)
            self.assertIn("RECOLHA TODOS", comodato_response.text)

            confirmation = flow.handle(IncomingMessage(sender=sender, text="recolha todos"), decision)

            self.assertIn("Solicitacao de Recolha", confirmation.text)
            self.assertIn("Comodato 720268", confirmation.text)
            self.assertIn("Comodato 102291", confirmation.text)
            self.assertEqual(flow.sessions[sender].step, "recolha_confirm")

    def test_seller_recolha_allows_selecting_all_comodatos(self) -> None:
        registration = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="O COMILAO LTDA",
            nome_fantasia="O COMILAO",
            telefone="",
            dia_visita="SEG/",
            vendedor="400",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=2,
            ultima_atualizacao_tabela="",
        )
        comodatos = [
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato="720268",
                material="Freezer",
                sub_tipo_material="Visa Cooler",
                saldo="1",
                planilha_atualizada_em="19/05/2026",
            ),
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato="102291",
                material="Mesa",
                sub_tipo_material="Jogo de mesa",
                saldo="5",
                planilha_atualizada_em="19/05/2026",
            ),
        ]
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[registration]),
                comodatos_service=StubComodatosService(ready=True, search_records=comodatos),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-recolha-all"

            _ = flow.handle(IncomingMessage(sender=sender, text="recolha"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="9845"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="todos"), decision)
            confirmation = flow.handle(IncomingMessage(sender=sender, text="sem obs"), decision)

            self.assertIn("Comodato 720268", confirmation.text)
            self.assertIn("Comodato 102291", confirmation.text)

    def test_seller_recolha_inline_without_pipes_selects_all_and_obs(self) -> None:
        registration = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="O COMILAO LTDA",
            nome_fantasia="O COMILAO",
            telefone="",
            dia_visita="SEG/",
            vendedor="400",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=1,
            ultima_atualizacao_tabela="",
        )
        comodatos = [
            ComodatoRecord(
                filial="3",
                cod_pdv="9845",
                nome="O COMILAO",
                nro_comodato="720268",
                material="Freezer",
                sub_tipo_material="Visa Cooler",
                saldo="1",
                planilha_atualizada_em="19/05/2026",
            ),
        ]
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[registration]),
                comodatos_service=StubComodatosService(ready=True, search_records=comodatos),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-recolha-fast"

            confirmation = flow.handle(
                IncomingMessage(sender=sender, text="recolha 9845 todos cliente pediu retirada"),
                decision,
            )

            self.assertIn("Comodato 720268", confirmation.text)
            self.assertIn("cliente pediu retirada", confirmation.text)
            result = flow.handle(IncomingMessage(sender=sender, text="s"), decision)

            self.assertIn("Solicitacao de Recolha registrada", result.text)
            records = recolha_service.list_requests()
            self.assertIn("Comodato 720268", records[0].comodato)
            self.assertEqual(records[0].obs, "cliente pediu retirada")

    def test_seller_recolha_accepts_name_lookup(self) -> None:
        records = [
            DClienteRecord(
                filial="3",
                cod_pdv="9845",
                razao_social="O COMILAO LTDA",
                nome_fantasia="O COMILAO",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="Ativo",
                cidade="PATOS",
                cond_pag_atual="",
                limite_credito="",
                total_pendente="0",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="10235",
                razao_social="COMILAO 2 LTDA",
                nome_fantasia="COMILAO 2",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="Ativo",
                cidade="PATOS",
                cond_pag_atual="",
                limite_credito="",
                total_pendente="0",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="",
            ),
        ]
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, fantasia_records=records),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-recolha-name"

            menu = flow.handle(IncomingMessage(sender=sender, text="recolha comilao"), decision)

            self.assertIn("Encontrei 2 cliente", menu.text)
            self.assertIn("1. O COMILAO", menu.text)

            prompt = flow.handle(IncomingMessage(sender=sender, text="2"), decision)

            self.assertIn("COMILAO 2", prompt.text)
            self.assertEqual(flow.sessions[sender].recolha_nb, "10235")

    def test_seller_recolha_rejects_client_outside_sector(self) -> None:
        outside_sector_client = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="CLIENTE FORA DO SETOR",
            nome_fantasia="CLIENTE FORA",
            telefone="",
            dia_visita="SEG/",
            vendedor="401",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=0,
            ultima_atualizacao_tabela="",
        )
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[outside_sector_client]),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )

            response = flow.handle(
                IncomingMessage(sender="5511-recolha-outside", text="recolha 9845 | recolha total"),
                decision,
            )

            self.assertIn("Nao encontrei o cliente 3 9845 dentro da sua base", response.text)
            self.assertEqual(recolha_service.count_requests(), 0)

    def test_finance_can_create_recolha_request(self) -> None:
        registration = DClienteRecord(
            filial="3",
            cod_pdv="9845",
            razao_social="O COMILAO LTDA",
            nome_fantasia="O COMILAO",
            telefone="",
            dia_visita="SEG/",
            vendedor="400",
            status="Ativo",
            cidade="PATOS",
            cond_pag_atual="",
            limite_credito="",
            total_pendente="0",
            total_comodatos_pendentes=0,
            ultima_atualizacao_tabela="",
        )
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            flow = make_flow(
                query_service=StubQueryService(ready=True, registration_records=[registration]),
                recolha_request_service=recolha_service,
            )
            decision = make_decision(
                allowed=True,
                roles=("financeiro",),
                normalized_number="5583991111222",
            )
            sender = "5511-recolha-finance"

            confirmation = flow.handle(
                IncomingMessage(sender=sender, text="solicitar recolha 3 9845 | recolha total | financeiro abriu"),
                decision,
            )

            self.assertIn("Solicitacao de Recolha", confirmation.text)
            self.assertIn("O COMILAO", confirmation.text)
            self.assertEqual(flow.sessions[sender].step, "recolha_confirm")

            result = flow.handle(IncomingMessage(sender=sender, text="confirmar"), decision)

            self.assertIn("Solicitacao de Recolha registrada", result.text)
            records = recolha_service.list_requests()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].solicitante, "5583991111222")
            self.assertEqual(records[0].nb, "9845")
            self.assertEqual(records[0].comodato, "recolha total")
            self.assertEqual(records[0].obs, "financeiro abriu")

    def test_finance_recolhas_exports_csv(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="5583999999999",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="recolha total",
                obs="enviar recibo",
            )
            flow = make_flow(recolha_request_service=recolha_service)

            response = flow.handle(
                IncomingMessage(sender="5511-fin-recolhas", text="recolhas"),
                make_decision(allowed=True, roles=("financeiro",)),
            )

            self.assertEqual(response.kind, "media")
            self.assertTrue(response.media_url.startswith("data:text/csv;base64,"))
            self.assertEqual(response.media_filename, "solicitacoes_recolha.csv")
            self.assertIn("Solicitacoes de Recolha", response.text)
            self.assertIn("NB 9845", response.text)
            self.assertIn("recolha total", response.text)
            exported_csv = recolha_service.export_csv_bytes().decode("utf-8-sig")
            self.assertIn("Lançado (faturista)", exported_csv)
            self.assertNotIn("Solicitante", exported_csv.splitlines()[0])

    def test_seller_recolhas_lists_only_own_requests(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="5583999999999",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer",
            )
            recolha_service.create_request(
                solicitante="5583888888888",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="10235",
                comodato="mesa",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )

            response = flow.handle(IncomingMessage(sender="5511-seller-recolhas", text="recolhas"), decision)

            self.assertEqual(response.kind, "media")
            self.assertIn("- Total visivel: 1", response.text)
            self.assertIn("NB 9845", response.text)
            self.assertIn("freezer", response.text)
            self.assertNotIn("NB 10235", response.text)
            self.assertNotIn("mesa", response.text)

    def test_seller_can_cancel_own_recolha_after_confirmation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="5583999999999",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer",
            )
            recolha_service.create_request(
                solicitante="5583888888888",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="mesa de outro vendedor",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )
            sender = "5511-seller-cancel-own"

            prompt = flow.handle(IncomingMessage(sender=sender, text="cancelar recolha 9845"), decision)

            self.assertIn("Remover Recolha", prompt.text)
            self.assertIn("CONFIRMAR REMOVER", prompt.text)
            self.assertIn("freezer", prompt.text)
            self.assertEqual(recolha_service.count_requests(), 2)

            result = flow.handle(IncomingMessage(sender=sender, text="confirmar remover"), decision)

            self.assertIn("*Removida:*", result.text)
            self.assertIn("freezer", result.text)
            self.assertEqual(recolha_service.count_requests(), 1)
            self.assertEqual(recolha_service.list_requests()[0].comodato, "mesa de outro vendedor")

    def test_finance_updates_recolha_faturista_fields_by_nb(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="5583999999999",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="recolha total",
                obs="enviar recibo",
            )
            flow = make_flow(recolha_request_service=recolha_service)

            response = flow.handle(
                IncomingMessage(sender="5511-fin-recolha-update", text="recolha 9845 lancado motorista Joao placa ABC1234 mapa 88"),
                make_decision(allowed=True, roles=("financeiro",)),
            )

            self.assertIn("Atualizacao de Recolha", response.text)
            self.assertIn("- Lancado: Ok", response.text)
            self.assertIn("- Motorista: Joao", response.text)
            records = recolha_service.list_requests()
            self.assertEqual(records[0].lancado_faturista, "Ok")
            self.assertEqual(records[0].motorista_faturista, "Joao")
            self.assertEqual(records[0].placa_faturista, "ABC1234")
            self.assertEqual(records[0].mapa_faturista, "88")

    def test_finance_accepts_faturista_and_caixa_update_aliases(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="5583999999999",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="recolha total",
                obs="enviar recibo",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("financeiro",))

            faturista = flow.handle(
                IncomingMessage(
                    sender="5511-fin-recolha-alias",
                    text="faturista 9845 lancado motorista Joao placa ABC1234 mapa 88",
                ),
                decision,
            )
            caixa = flow.handle(
                IncomingMessage(
                    sender="5511-fin-recolha-alias",
                    text="caixa 9845 nao recolhido motivo cliente fechado",
                ),
                decision,
            )

            self.assertIn("Atualizacao de Recolha", faturista.text)
            self.assertIn("- Motorista: Joao", faturista.text)
            self.assertIn("Atualizacao de Recolha", caixa.text)
            self.assertIn("cliente fechado", caixa.text)
            records = recolha_service.list_requests()
            self.assertEqual(records[0].lancado_faturista, "Ok")
            self.assertEqual(records[0].motorista_faturista, "Joao")
            self.assertEqual(records[0].status_caixa_noturno, "N\u00e3o Recolhido")
            self.assertEqual(records[0].motivo_caixa_noturno, "cliente fechado")

    def test_finance_recolhas_filters_and_summary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="1",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer",
            )
            recolha_service.create_request(
                solicitante="2",
                revenda="Sume",
                data="19/05/2026",
                setor="503",
                cidade="SUME",
                rn="503",
                nb="10235",
                comodato="mesa",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("financeiro",))

            filtered = flow.handle(IncomingMessage(sender="5511-fin-recolha-filter", text="recolhas setor 400"), decision)

            self.assertIn("NB 9845", filtered.text)
            self.assertNotIn("NB 10235", filtered.text)

            summary = flow.handle(IncomingMessage(sender="5511-fin-recolha-summary", text="recolhas resumo"), decision)

            self.assertIn("Resumo de Recolhas", summary.text)
            self.assertIn("- Abertas: 2", summary.text)
            self.assertIn("*Por setor:*", summary.text)

    def test_finance_recolhas_today_filter_uses_created_date(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            today = datetime.now(timezone(timedelta(hours=-3)))
            yesterday = today - timedelta(days=1)
            recolha_service.create_request(
                solicitante="1",
                revenda="Patos",
                data=yesterday.strftime("%d/%m/%Y"),
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer antigo",
                created_at=yesterday,
            )
            recolha_service.create_request(
                solicitante="2",
                revenda="Patos",
                data=today.strftime("%d/%m/%Y"),
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="10235",
                comodato="freezer hoje",
                created_at=today,
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("financeiro",))

            response = flow.handle(IncomingMessage(sender="5511-fin-recolha-hoje", text="recolhas hoje"), decision)

            self.assertIn("- Periodo: Hoje", response.text)
            self.assertIn("NB 10235", response.text)
            self.assertIn("freezer hoje", response.text)
            self.assertNotIn("NB 9845", response.text)
            self.assertNotIn("freezer antigo", response.text)

    def test_finance_recolhas_default_shows_open_not_recolhidas(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="1",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer aberto",
            )
            recolhida = recolha_service.create_request(
                solicitante="2",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="10235",
                comodato="freezer recolhido",
            )
            recolha_service.update_latest(identifier=recolhida.id, updates={"status_caixa_noturno": "Recolhido"})
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("financeiro",))

            response = flow.handle(IncomingMessage(sender="5511-fin-recolha-open-default", text="recolhas"), decision)

            self.assertIn("- Status: Pendentes/abertas", response.text)
            self.assertIn("NB 9845", response.text)
            self.assertNotIn("NB 10235", response.text)

    def test_scoped_finance_recolhas_are_limited_to_allowed_filiais(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="1",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer patos",
            )
            recolha_service.create_request(
                solicitante="2",
                revenda="Sousa",
                data="19/05/2026",
                setor="101",
                cidade="SOUSA",
                rn="101",
                nb="10235",
                comodato="freezer sousa",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("financeiro",), sectors=("filial:3", "filial:4"))

            response = flow.handle(IncomingMessage(sender="5511-fin-recolha-filial-scope", text="recolhas historico"), decision)

            self.assertIn("NB 9845", response.text)
            self.assertIn("freezer patos", response.text)
            self.assertNotIn("NB 10235", response.text)
            self.assertNotIn("freezer sousa", response.text)

    def test_scoped_finance_cannot_update_recolha_outside_filial(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="1",
                revenda="Sousa",
                data="19/05/2026",
                setor="101",
                cidade="SOUSA",
                rn="101",
                nb="10235",
                comodato="freezer sousa",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("financeiro",), sectors=("filial:3",))

            response = flow.handle(
                IncomingMessage(sender="5511-fin-recolha-update-scope", text="caixa 10235 recolhido"),
                decision,
            )

            self.assertIn("Nao encontrei solicitacao", response.text)
            records = recolha_service.list_all_requests()
            self.assertEqual(records[0].status_caixa_noturno, "N\u00e3o Recolhido")

    def test_recolha_update_accepts_filial_nb_identifier(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="1",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer patos",
            )
            recolha_service.create_request(
                solicitante="2",
                revenda="Sousa",
                data="19/05/2026",
                setor="101",
                cidade="SOUSA",
                rn="101",
                nb="9845",
                comodato="freezer sousa",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("financeiro",), sectors=("filial:3", "filial:1"))

            response = flow.handle(
                IncomingMessage(sender="5511-fin-recolha-pair-update", text="caixa 3-9845 recolhido"),
                decision,
            )

            self.assertIn("Atualizacao de Recolha", response.text)
            records_by_revenda = {record.revenda: record for record in recolha_service.list_all_requests()}
            self.assertEqual(records_by_revenda["Patos"].status_caixa_noturno, "Recolhido")
            self.assertEqual(records_by_revenda["Sousa"].status_caixa_noturno, "N\u00e3o Recolhido")

    def test_manager_can_delete_recolha_after_confirmation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="1",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_4",))
            sender = "5511-manager-delete-recolha"

            prompt = flow.handle(IncomingMessage(sender=sender, text="remover recolha 9845"), decision)

            self.assertIn("Remover Recolha", prompt.text)
            self.assertIn("CONFIRMAR REMOVER", prompt.text)
            self.assertEqual(recolha_service.count_requests(), 1)

            result = flow.handle(IncomingMessage(sender=sender, text="confirmar remover"), decision)

            self.assertIn("*Removida:*", result.text)
            self.assertEqual(recolha_service.count_requests(), 0)

    def test_manager_can_clear_recolhas_after_confirmation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="1",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer",
            )
            recolha_service.create_request(
                solicitante="2",
                revenda="Sume",
                data="19/05/2026",
                setor="503",
                cidade="SUME",
                rn="503",
                nb="10235",
                comodato="mesa",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(allowed=True, roles=("diretor_comercial",), gv_vdes=("3_4",))
            sender = "5511-director-clear-recolha"

            prompt = flow.handle(IncomingMessage(sender=sender, text="limpar recolhas"), decision)

            self.assertIn("Limpar Recolhas", prompt.text)
            self.assertIn("CONFIRMAR LIMPAR", prompt.text)
            self.assertEqual(recolha_service.count_requests(), 2)

            result = flow.handle(IncomingMessage(sender=sender, text="confirmar limpar"), decision)

            self.assertIn("2 solicitacao", result.text)
            self.assertEqual(recolha_service.count_requests(), 0)

    def test_seller_cannot_cancel_other_recolha(self) -> None:
        with TemporaryDirectory() as tmpdir:
            recolha_service = RecolhaRequestService(Path(tmpdir) / "solicitacoes_recolha.csv")
            recolha_service.create_request(
                solicitante="5583888888888",
                revenda="Patos",
                data="19/05/2026",
                setor="400",
                cidade="PATOS",
                rn="400",
                nb="9845",
                comodato="freezer",
            )
            flow = make_flow(recolha_request_service=recolha_service)
            decision = make_decision(
                allowed=True,
                roles=("vendedor",),
                sectors=("3_400",),
                normalized_number="5583999999999",
            )

            response = flow.handle(IncomingMessage(sender="5511-seller-delete-recolha", text="remover recolha 9845"), decision)

            self.assertIn("Nao encontrei solicitacao", response.text)
            self.assertEqual(recolha_service.count_requests(), 1)

    def test_finance_payip_menu_status_and_login_test(self) -> None:
        sender = "5511-fin-payip"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        menu = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)

        self.assertEqual(menu.kind, "menu")
        self.assertEqual(menu.title, "Pagamentos PayIP")
        self.assertEqual([(option.shortcut, option.title) for option in menu.options], [
            ("1", "Buscar Nota Fiscal"),
            ("2", "Buscar por NB"),
            ("3", "PIX da Ultima Consulta"),
            ("4", "Diagnostico PayIP"),
            ("5", "Emitir Cobranca"),
            ("6", "Extrato PayIP"),
            ("7", "Buscar Valor/Dia"),
            ("8", "Validar Data"),
            ("9", "Validar Importacao"),
            ("10", "Criar Cliente"),
            ("11", "Rotas em Progresso"),
        ])

        status = self.flow.handle(IncomingMessage(sender=sender, text="4"), decision)

        self.assertEqual(status.kind, "text")
        self.assertIn("PayIP | Status da sessao", status.text)
        self.assertIn("Access token valido: Sim", status.text)

        _ = self.flow.handle(IncomingMessage(sender=sender, text="A"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="diagnostico"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Status da sessao", result.text)
        self.assertEqual(self.payip_service.list_calls, [])

    def test_finance_payip_statement_resume_uses_filial_and_period(self) -> None:
        sender = "5511-fin-payip-statement"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="6"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Informe a filial para consultar o extrato PayIP", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_statement_awaiting_period")

        result = self.flow.handle(IncomingMessage(sender=sender, text="4 01/05/2026 08/05/2026"), decision)

        self.assertEqual(result.kind, "media")
        self.assertIn("PayIP | Extrato", result.text)
        self.assertIn("Revenda: 4 - Sume", result.text)
        self.assertIn("Periodo: 01/05/2026 a 08/05/2026", result.text)
        self.assertIn("Saldo atual: R$ 1.000,50", result.text)
        self.assertIn("Entrada: R$ 150,75", result.text)
        self.assertIn("Movimentacao: R$ 40,25", result.text)
        self.assertNotIn("Total:", result.text)
        self.assertIn("Movimentos: 3", result.text)
        self.assertIn("Arquivos: PDF e XLSX anexados.", result.text)
        self.assertEqual(result.media_type, "document")
        self.assertTrue(result.media_url.startswith("data:application/pdf;base64,"))
        self.assertTrue(result.media_filename.endswith(".pdf"))
        self.assertEqual(len(result.extra_media), 1)
        self.assertTrue(result.extra_media[0].media_url.startswith("data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"))
        self.assertTrue(result.extra_media[0].media_filename.endswith(".xlsx"))
        self.assertEqual(
            self.payip_service.statement_resume_calls[-1],
            {"filial": "4", "date_start": "2026-05-01", "date_end": "2026-05-08"},
        )
        self.assertEqual(
            self.payip_service.statement_export_calls[-2:],
            [
                {"filial": "4", "date_start": "2026-05-01", "date_end": "2026-05-08", "file_format": "pdf"},
                {"filial": "4", "date_start": "2026-05-01", "date_end": "2026-05-08", "file_format": "xlsx"},
            ],
        )

    def test_finance_payip_statement_resume_accepts_inline_shortcut(self) -> None:
        sender = "5511-fin-payip-statement-inline"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="extrato 4 2026-05-01 2026-05-08"), decision)

        self.assertEqual(result.kind, "media")
        self.assertIn("PayIP | Extrato", result.text)
        self.assertEqual(
            self.payip_service.statement_resume_calls[-1],
            {"filial": "4", "date_start": "2026-05-01", "date_end": "2026-05-08"},
        )

    def test_finance_payip_statement_resume_accepts_natural_shortcut_from_idle(self) -> None:
        sender = "5511-fin-payip-statement-natural"
        decision = make_decision(allowed=True, roles=("financeiro",))

        result = self.flow.handle(
            IncomingMessage(sender=sender, text="extrato 4 01/05/2026 08/05/2026"),
            decision,
        )

        self.assertEqual(result.kind, "media")
        self.assertIn("PayIP | Extrato", result.text)
        self.assertIn("Entrada: R$ 150,75", result.text)
        self.assertIn("Movimentacao: R$ 40,25", result.text)
        self.assertNotIn("Total:", result.text)
        self.assertEqual(len(result.extra_media), 1)
        self.assertEqual(
            self.payip_service.statement_resume_calls[-1],
            {"filial": "4", "date_start": "2026-05-01", "date_end": "2026-05-08"},
        )

    def test_finance_payip_searches_amount_and_paid_day(self) -> None:
        sender = "5511-fin-payip-amount-day"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="7"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("valor recebido e o dia de pagamento", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_amount_day_awaiting_query")

        result = self.flow.handle(IncomingMessage(sender=sender, text="3 0,99 13/04/2026"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Valor e Dia", result.text)
        self.assertIn(
            "Revenda: 3 - Patos | Pagamento: 13/04/2026 | Valor: R$ 0,99 | Tolerancia: R$ 0,05",
            result.text,
        )
        self.assertIn("Pagamento confirmado em: 13/04/2026", result.text)
        self.assertIn("Nota Fiscal: 147478", result.text)
        self.assertNotIn("Nota Fiscal: 147479", result.text)
        self.assertIn("Quer fazer outra consulta do mesmo tipo? Envie SIM.", result.text)
        self.assertEqual(
            self.payip_service.amount_day_calls[-1],
            {
                "filial": "3",
                "amount": "0.99",
                "day": "2026-04-13",
                "tolerance": "0.05",
                "status": "",
                "page_size": 100,
                "max_pages": None,
            },
        )

        repeat_prompt = self.flow.handle(IncomingMessage(sender=sender, text="SIM"), decision)

        self.assertIn("valor recebido e o dia de pagamento", repeat_prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_amount_day_awaiting_query")

    def test_finance_payip_accepts_custom_amount_tolerance(self) -> None:
        sender = "5511-fin-payip-amount-day-custom-tolerance"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        result = self.flow.handle(
            IncomingMessage(sender=sender, text="valor 3 0,99 13/04/2026 tolerancia 0,10"),
            decision,
        )

        self.assertEqual(result.kind, "text")
        self.assertIn("Tolerancia: R$ 0,10", result.text)
        self.assertEqual(self.payip_service.amount_day_calls[-1]["tolerance"], "0.10")

    def test_finance_payip_validates_due_and_created_day(self) -> None:
        sender = "5511-fin-payip-validate-day"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="8"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("validar as cobrancas", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_validate_day_awaiting_query")

        result = self.flow.handle(IncomingMessage(sender=sender, text="3 07072026"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Validacao por Data", result.text)
        self.assertIn("Revenda: 3 - Patos", result.text)
        self.assertIn("Data: 07/07/2026", result.text)
        self.assertIn("- Com vencimento nessa data: 10", result.text)
        self.assertIn("- Criadas nessa data: 10", result.text)
        self.assertNotIn("Vencimento - exemplos", result.text)
        self.assertNotIn("Nota Fiscal:", result.text)
        self.assertNotIn("Quer fazer outra consulta", result.text)
        self.assertEqual(
            self.payip_service.list_calls[-2],
            {
                "page": 1,
                "page_size": 5,
                "status": "",
                "client_code": "",
                "invoice": "",
                "filial": "3",
                "due_date_start": "2026-07-07",
                "due_date_end": "2026-07-07",
            },
        )
        self.assertEqual(
            self.payip_service.list_calls[-1],
            {
                "page": 1,
                "page_size": 5,
                "status": "",
                "client_code": "",
                "invoice": "",
                "filial": "3",
                "created_at_start": "2026-07-07",
                "created_at_end": "2026-07-07",
            },
        )
    def test_finance_payip_validate_day_accepts_inline_shortcut(self) -> None:
        sender = "5511-fin-payip-validate-day-inline"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="validar 3 07/07/2026"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Validacao por Data", result.text)
        self.assertEqual(self.payip_service.list_calls[-2]["due_date_start"], "2026-07-07")
        self.assertEqual(self.payip_service.list_calls[-1]["created_at_start"], "2026-07-07")

    def test_finance_payip_validate_day_shortcut_from_idle_does_not_fall_into_client_lookup(self) -> None:
        sender = "5511-fin-payip-validate-day-idle"
        decision = make_decision(allowed=True, roles=("financeiro",))

        result = self.flow.handle(IncomingMessage(sender=sender, text="validar 3 07072026"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Validacao por Data", result.text)
        self.assertNotIn("Nao encontrei cliente", result.text)
        self.assertEqual(self.payip_service.list_calls[-2]["due_date_start"], "2026-07-07")
        self.assertEqual(self.payip_service.list_calls[-1]["created_at_start"], "2026-07-07")

    def test_finance_payip_validate_day_resumes_after_mfa(self) -> None:
        sender = "5511-fin-payip-validate-day-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(require_mfa_once=True)
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = flow.handle(IncomingMessage(sender=sender, text="validar 3 07072026"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_awaiting_mfa")
        self.assertEqual(flow.sessions[sender].payip_pending_action, "validate_day")

        result = flow.handle(IncomingMessage(sender=sender, text="123456"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Validacao por Data", result.text)
        self.assertEqual(payip_service.bootstrap_calls, ["123456"])
        self.assertEqual(payip_service.list_calls[-2]["due_date_start"], "2026-07-07")
        self.assertEqual(payip_service.list_calls[-1]["created_at_start"], "2026-07-07")

    def test_finance_payip_validates_promax_import_batch(self) -> None:
        sender = "5511-fin-payip-import-batch"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="3 07072026 07072026"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Importacao Automatizada", result.text)
        self.assertIn("Revenda: 3 - Patos", result.text)
        self.assertIn("Periodo: 07/07/2026 a 07/07/2026", result.text)
        self.assertIn("Validacao aprovada.", result.text)
        self.assertIn("- Cobrancas encontradas: 1", result.text)
        self.assertIn("- Valor total: R$ 20,00", result.text)
        self.assertIn("CONFIRMAR IMPORTACAO", result.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_import_batch_confirm")
        self.assertEqual(
            self.payip_service.import_batch_calls[-1],
            {"filial": "3", "date_start": "2026-07-07", "date_end": "2026-07-07"},
        )

    def test_finance_payip_import_batch_confirms_after_mfa(self) -> None:
        sender = "5511-fin-payip-import-batch-confirm"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="3 07072026 07072026"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR IMPORTACAO"), decision)

        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_awaiting_mfa")
        self.assertEqual(self.flow.sessions[sender].payip_pending_action, "import_batch_confirm")

        result = self.flow.handle(IncomingMessage(sender=sender, text="422649"), decision)

        self.assertIn("PayIP | Importacao Confirmada", result.text)
        self.assertIn("Importacao enviada com sucesso.", result.text)
        self.assertEqual(
            self.payip_service.import_batch_confirm_calls[-1],
            {
                "filial": "3",
                "date_start": "2026-07-07",
                "date_end": "2026-07-07",
                "totp_code": "422649",
            },
        )

    def test_finance_payip_import_batch_accepts_mfa_directly_after_validation(self) -> None:
        sender = "5511-fin-payip-import-batch-direct-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="3 07072026 07072026"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="422649"), decision)

        self.assertIn("PayIP | Importacao Confirmada", result.text)
        self.assertEqual(self.payip_service.import_batch_confirm_calls[-1]["totp_code"], "422649")

    def test_finance_payip_import_batch_stores_missing_client_codes(self) -> None:
        sender = "5511-fin-payip-import-batch-missing-client"
        decision = make_decision(allowed=True, roles=("financeiro",))

        class MissingClientPayipService(StubPayipPaymentsService):
            def validate_promax_import_batch(self, **kwargs: Any) -> Any:
                self.import_batch_calls.append(
                    {
                        "filial": str(kwargs.get("filial") or ""),
                        "date_start": str(kwargs.get("date_start") or ""),
                        "date_end": str(kwargs.get("date_end") or ""),
                    }
                )
                return SimpleNamespace(
                    raw={"details": {"codes_client": ["19167"]}},
                    filial=str(kwargs.get("filial") or ""),
                    company_id="bdfee22b-ac11-4355-909a-54bd348c87cc",
                    date_start=str(kwargs.get("date_start") or ""),
                    date_end=str(kwargs.get("date_end") or ""),
                    items=(),
                    missing_client_codes=("19167",),
                    ok=False,
                )

        payip_service = MissingClientPayipService()
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        result = flow.handle(IncomingMessage(sender=sender, text="importar 3 07072026 07072026"), decision)

        self.assertIn("Validacao com erro.", result.text)
        self.assertIn("- Clientes nao encontrados: 1", result.text)
        self.assertIn("- Codigos: 19167", result.text)
        self.assertEqual(flow.sessions[sender].payip_import_missing_client_codes, ("19167",))

    def test_finance_payip_import_batch_can_create_missing_clients_from_dclientes(self) -> None:
        sender = "5511-fin-payip-import-batch-create-missing-client"
        decision = make_decision(allowed=True, roles=("financeiro",))

        class MissingClientPayipService(StubPayipPaymentsService):
            def validate_promax_import_batch(self, **kwargs: Any) -> Any:
                self.import_batch_calls.append(
                    {
                        "filial": str(kwargs.get("filial") or ""),
                        "date_start": str(kwargs.get("date_start") or ""),
                        "date_end": str(kwargs.get("date_end") or ""),
                    }
                )
                return SimpleNamespace(
                    raw={"details": {"codes_client": ["19167"]}},
                    filial=str(kwargs.get("filial") or ""),
                    company_id="bdfee22b-ac11-4355-909a-54bd348c87cc",
                    date_start=str(kwargs.get("date_start") or ""),
                    date_end=str(kwargs.get("date_end") or ""),
                    items=(),
                    missing_client_codes=("19167",),
                    ok=False,
                )

        query_service = StubQueryService(
            payip_profile=SimpleNamespace(
                filial="3",
                cod_pdv="19167",
                documento="12467128490",
                razao_social="JHEFFERSON KAUA",
                nome_fantasia="Kaua",
                email="",
                telefone="",
                cep="58706560",
                endereco="Rua Professora Cristina Lima",
                numero="SN",
                complemento="",
                bairro="Salgadinho",
                cidade="Patos",
                uf="PB",
            )
        )
        payip_service = MissingClientPayipService()
        flow = make_flow(query_service=query_service, payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="importar 3 07072026 07072026"), decision)
        result = flow.handle(IncomingMessage(sender=sender, text="criar clientes payip"), decision)

        self.assertIn("PayIP | Clientes da Importacao", result.text)
        self.assertIn("- Criados: 1", result.text)
        self.assertIn("19167", result.text)
        self.assertEqual(query_service.payip_profile_calls[-1], {"filial": "3", "cod_pdv": "19167"})
        self.assertEqual(payip_service.create_client_calls[-1]["payload"]["client"]["code"], "19167")

    def test_finance_payip_creates_client_from_dclientes(self) -> None:
        sender = "5511-fin-payip-create-client"
        decision = make_decision(allowed=True, roles=("financeiro",))
        query_service = StubQueryService(
            payip_profile=SimpleNamespace(
                filial="3",
                cod_pdv="19167",
                documento="12467128490",
                razao_social="JHEFFERSON KAUA",
                nome_fantasia="Kaua",
                email="",
                telefone="",
                cep="58706560",
                endereco="Rua Professora Cristina Lima",
                numero="SN",
                complemento="",
                bairro="Salgadinho",
                cidade="Patos",
                uf="PB",
            )
        )
        payip_service = StubPayipPaymentsService()
        flow = make_flow(query_service=query_service, payip_payments_service=payip_service)

        result = flow.handle(IncomingMessage(sender=sender, text="criar cliente payip 3 19167"), decision)

        self.assertIn("PayIP | Cliente Criado", result.text)
        self.assertIn("NB: 19167", result.text)
        self.assertIn("Cliente: JHEFFERSON KAUA", result.text)
        self.assertIn("Campos com fallback: email, telefone", result.text)
        self.assertEqual(query_service.payip_profile_calls[-1], {"filial": "3", "cod_pdv": "19167"})
        self.assertEqual(payip_service.create_client_calls[-1]["payload"]["client"]["code"], "19167")

    def test_finance_payip_create_client_menu_prompts_for_registration(self) -> None:
        sender = "5511-fin-payip-create-client-menu"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="10"), decision)

        self.assertIn("Informe a filial e o NB do cliente", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_create_client_awaiting_registration")

    def test_finance_payip_import_batch_resumes_after_mfa(self) -> None:
        sender = "5511-fin-payip-import-batch-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(require_mfa_once=True)
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = flow.handle(IncomingMessage(sender=sender, text="importar 3 07072026 07072026"), decision)

        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].payip_pending_action, "import_batch")

        result = flow.handle(IncomingMessage(sender=sender, text="123456"), decision)

        self.assertIn("PayIP | Importacao Automatizada", result.text)
        self.assertEqual(payip_service.bootstrap_calls, ["123456"])
        self.assertEqual(payip_service.import_batch_calls[-1]["date_start"], "2026-07-07")

    def test_finance_payip_routes_lists_in_progress_maps(self) -> None:
        sender = "5511-fin-payip-routes"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService()

        def list_routes_page(**kwargs: Any) -> Any:
            page = int(kwargs.get("page") or 1)
            filial = str(kwargs.get("filial") or "")
            status = str(kwargs.get("status") or "IN_PROGRESS")
            payip_service.routes_calls.append(
                {
                    "filial": filial,
                    "status": status,
                    "code": str(kwargs.get("code") or ""),
                    "page": page,
                    "page_size": int(kwargs.get("page_size") or 25),
                }
            )
            page_items = {
                1: (
                    {
                        "id": "route-2",
                        "code": "92305",
                        "status": "IN_PROGRESS",
                        "driversRoute": [{"driver": {"name": "Jose Marcelo", "code": "7444"}}],
                    },
                ),
                2: (
                    {
                        "id": "route-1",
                        "code": "92304",
                        "status": "IN_PROGRESS",
                        "driversRoute": [{"driver": {"name": "Ana Maria", "code": "7333"}}],
                    },
                ),
            }.get(page, ())
            return SimpleNamespace(
                raw={"data": list(page_items), "total": 2, "page": page, "pageSize": 1},
                filial=filial,
                company_id="bdfee22b-ac11-4355-909a-54bd348c87cc",
                status=status,
                items=page_items,
                items_count=len(page_items),
                total_items=2,
                page=page,
                page_size=1,
            )

        payip_service.list_routes = list_routes_page  # type: ignore[method-assign]

        def list_all_routes_pages(**kwargs: Any) -> Any:
            items = []
            for page in (1, 2):
                current = list_routes_page(**{**kwargs, "page": page, "page_size": 1})
                items.extend(list(current.items))
            return SimpleNamespace(
                raw={"pages": []},
                filial=str(kwargs.get("filial") or ""),
                company_id="bdfee22b-ac11-4355-909a-54bd348c87cc",
                status=str(kwargs.get("status") or "IN_PROGRESS"),
                items=tuple(items),
                items_count=len(items),
                total_items=len(items),
                page=1,
                page_size=1,
            )

        payip_service.list_all_routes = list_all_routes_pages  # type: ignore[method-assign]
        flow = make_flow(payip_payments_service=payip_service)

        result = flow.handle(IncomingMessage(sender=sender, text="rotas 3"), decision)

        self.assertIn("PayIP | Rotas em Progresso", result.text)
        self.assertIn("Revenda: 3 - Patos", result.text)
        self.assertLess(result.text.index("92304 - Ana Maria (7333)"), result.text.index("92305 - Jose Marcelo (7444)"))
        self.assertIn("92305 - Jose Marcelo (7444)", result.text)
        self.assertEqual([call["page"] for call in payip_service.routes_calls], [1, 2])

    def test_finance_payip_routes_resumes_after_mfa(self) -> None:
        sender = "5511-fin-payip-routes-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(require_mfa_once=True)
        flow = make_flow(payip_payments_service=payip_service)

        prompt = flow.handle(IncomingMessage(sender=sender, text="rotas 3"), decision)

        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].payip_pending_action, "routes")

        result = flow.handle(IncomingMessage(sender=sender, text="123456"), decision)

        self.assertIn("PayIP | Rotas em Progresso", result.text)
        self.assertEqual(payip_service.bootstrap_calls, ["123456"])
        self.assertEqual(payip_service.routes_calls[-1]["filial"], "3")

    def test_finance_payip_amount_day_resumes_after_mfa(self) -> None:
        sender = "5511-fin-payip-amount-day-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(require_mfa_once=True)
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = flow.handle(IncomingMessage(sender=sender, text="valor 3 0,99 13/04/2026"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_awaiting_mfa")
        self.assertEqual(flow.sessions[sender].payip_pending_action, "amount_day")

        result = flow.handle(IncomingMessage(sender=sender, text="123456"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Valor e Dia", result.text)
        self.assertEqual(payip_service.bootstrap_calls, ["123456"])
        self.assertEqual(payip_service.amount_day_calls[-1]["day"], "2026-04-13")

    def test_finance_payip_statement_resume_resumes_after_mfa(self) -> None:
        sender = "5511-fin-payip-statement-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(require_mfa_once=True)
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = flow.handle(IncomingMessage(sender=sender, text="extrato 4 01/05/2026 08/05/2026"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_awaiting_mfa")
        self.assertEqual(flow.sessions[sender].payip_pending_action, "statement")

        result = flow.handle(IncomingMessage(sender=sender, text="123456"), decision)

        self.assertEqual(result.kind, "media")
        self.assertIn("PayIP | Extrato", result.text)
        self.assertEqual(payip_service.bootstrap_calls, ["123456"])
        self.assertEqual(len(result.extra_media), 1)
        self.assertEqual(
            payip_service.statement_resume_calls[-1],
            {"filial": "4", "date_start": "2026-05-01", "date_end": "2026-05-08"},
        )

    def test_finance_payip_accepts_mfa_code_in_conversation(self) -> None:
        sender = "5511-fin-payip-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(require_mfa_once=True)
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="1"), decision)
        prompt = flow.handle(IncomingMessage(sender=sender, text="3 147478"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_awaiting_mfa")

        result = flow.handle(IncomingMessage(sender=sender, text="123456"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Nota Fiscal 147478", result.text)
        self.assertEqual(payip_service.bootstrap_calls, ["123456"])
        self.assertEqual(
            payip_service.list_calls[-1],
            {"page": 1, "page_size": 50, "status": "", "client_code": "", "invoice": "147478", "filial": "3"},
        )

    def test_finance_payip_searches_invoice_and_formats_important_fields(self) -> None:
        sender = "5511-fin-payip-invoice"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="1"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Informe a filial e o numero da nota fiscal", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_awaiting_invoice")

        result = self.flow.handle(IncomingMessage(sender=sender, text="3 147478"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Nota Fiscal 147478", result.text)
        self.assertIn("Filtro: invoice=147478", result.text)
        self.assertIn("Nota Fiscal: 147478", result.text)
        self.assertIn("Cliente: THIAGO COD | NB 12447", result.text)
        self.assertIn("Vencimento: 14/04/2026", result.text)
        self.assertIn("Status: PENDENTE", result.text)
        self.assertIn("Valor: R$ 0,99 | Pago: R$ 0,00", result.text)
        self.assertIn("PIX: envie PIX 1", result.text)
        self.assertNotIn("ID da cobranca", result.text)
        self.assertNotIn("https://example.test/qrcode/147478.png", result.text)
        self.assertEqual(
            self.payip_service.list_calls[-1],
            {"page": 1, "page_size": 50, "status": "", "client_code": "", "invoice": "147478", "filial": "3"},
        )

        pix = self.flow.handle(IncomingMessage(sender=sender, text="PIX 1"), decision)

        self.assertEqual(pix.kind, "media")
        self.assertEqual(pix.text, "000201010212PAYIPPIXTESTE1474786304ABCD")
        self.assertTrue(pix.media_url.startswith("data:application/pdf;base64,"))
        self.assertEqual(pix.media_type, "document")
        self.assertIn("PDF cobranca PayIP | NF 147478", pix.media_caption)
        self.assertNotIn("ID pay-1", pix.text)
        self.assertEqual(
            self.payip_service.invoice_report_calls[-1],
            {
                "filial": "3",
                "payment_ids": ["pay-1"],
                "company_id": "bdfee22b-ac11-4355-909a-54bd348c87cc",
            },
        )

    def test_finance_payip_filters_pending_by_client_code(self) -> None:
        sender = "5511-fin-payip-nb"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="2"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Informe a filial e o NB/codigo do cliente", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_awaiting_client_code")

        filter_prompt = self.flow.handle(IncomingMessage(sender=sender, text="3 17"), decision)

        self.assertEqual(filter_prompt.kind, "text")
        self.assertIn("Somente pendentes", filter_prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_awaiting_client_filter")

        result = self.flow.handle(IncomingMessage(sender=sender, text="1"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Pendentes NB 17", result.text)
        self.assertIn("Filtro: status=PENDING | clientCode=17", result.text)
        self.assertIn("Cliente: THIAGO COD | NB 17", result.text)
        self.assertIn("Status: PENDENTE", result.text)
        self.assertEqual(
            self.payip_service.list_calls[-1],
            {"page": 1, "page_size": 50, "status": "PENDING", "client_code": "17", "invoice": "", "filial": "3"},
        )

    def test_finance_payip_filters_all_statuses_by_client_code(self) -> None:
        sender = "5511-fin-payip-nb-all"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="2"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("consultar pagamentos", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_awaiting_client_code")

        result = self.flow.handle(IncomingMessage(sender=sender, text="3 17 todos"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Pagamentos NB 17", result.text)
        self.assertIn("Filtro: clientCode=17", result.text)
        self.assertNotIn("status=PENDING", result.text)
        self.assertIn("Cliente: THIAGO COD | NB 17", result.text)
        self.assertEqual(
            self.payip_service.list_calls[-1],
            {"page": 1, "page_size": 50, "status": "", "client_code": "17", "invoice": "", "filial": "3"},
        )

    def test_finance_payip_accepts_sume_filial_for_client_code(self) -> None:
        sender = "5511-fin-payip-sume"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="2"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="4 17 todos"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("Revenda: 4 - Sume", result.text)
        self.assertIn("Filtro: clientCode=17", result.text)
        self.assertEqual(
            self.payip_service.list_calls[-1],
            {"page": 1, "page_size": 50, "status": "", "client_code": "17", "invoice": "", "filial": "4"},
        )

    def test_finance_payip_creates_charge_after_confirmation(self) -> None:
        sender = "5511-fin-payip-create"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="5"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Informe a filial e o NB", prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_charge_awaiting_client")

        amount_prompt = self.flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)

        self.assertIn("Cliente encontrado para emissao PayIP", amount_prompt.text)
        self.assertIn("MATHEUS GONCALVES DE SOUSA", amount_prompt.text)
        self.assertEqual(self.payip_service.client_lookup_calls[-1], {"filial": "3", "client_code": "16883"})
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_charge_awaiting_amount")

        due_prompt = self.flow.handle(IncomingMessage(sender=sender, text="0,99"), decision)

        self.assertIn("data de vencimento", due_prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_charge_awaiting_due_date")

        confirmation = self.flow.handle(IncomingMessage(sender=sender, text="31/12/2026"), decision)

        self.assertIn("Confirmar emissao PayIP", confirmation.text)
        self.assertIn("Valor base: R$ 0,99", confirmation.text)
        self.assertIn("Taxa PIX: R$ 3,92", confirmation.text)
        self.assertIn("Total estimado: R$ 4,91", confirmation.text)
        self.assertEqual(self.flow.sessions[sender].step, "finance_payip_charge_confirm")
        self.assertEqual(self.payip_service.create_charge_calls, [])

        result = self.flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR."), decision)

        self.assertEqual(result.kind, "media")
        self.assertEqual(result.text, "000201010212PAYIPPIXCREATE168836304DCBA")
        self.assertTrue(result.media_url.startswith("data:application/pdf;base64,"))
        self.assertEqual(result.media_type, "document")
        self.assertIn("PDF cobranca PayIP", result.media_caption)
        self.assertEqual(self.payip_service.get_payment_calls[-1], "created-payment-1")
        self.assertEqual(
            self.payip_service.invoice_report_calls[-1],
            {
                "filial": "3",
                "payment_ids": ["created-payment-1"],
                "company_id": "bdfee22b-ac11-4355-909a-54bd348c87cc",
            },
        )
        self.assertEqual(
            self.payip_service.create_charge_calls[-1],
            {
                "filial": "3",
                "amount": "0.99",
                "rate_amount": "3.92",
                "interest_perc": "10.00",
                "tax_payer_id": "15954335460",
                "external_id": "16883",
                "invoice": "",
                "due_date": "2026-12-31",
                "issue_date": self.payip_service.create_charge_calls[-1]["issue_date"],
                "title": "Fatura revenda Pau Brasil - Patos",
                "description": "Fatura revenda Pau Brasil - Patos",
            },
        )

    def test_finance_payip_charge_failure_keeps_confirmation_for_retry(self) -> None:
        sender = "5511-fin-payip-create-retry"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(
            create_charge_error=PayipError("PayIP charge request failed: HTTP 503")
        )
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="5"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="0,99"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="31/12/2026"), decision)

        failure = flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR"), decision)

        self.assertEqual(failure.kind, "text")
        self.assertIn("PayIP | Falha na emissao", failure.text)
        self.assertIn("A cobranca nao foi gerada", failure.text)
        self.assertIn("Para tentar novamente", failure.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_charge_confirm")
        self.assertEqual(payip_service.create_charge_calls, [])

        payip_service.create_charge_error = None
        retry = flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR"), decision)

        self.assertEqual(retry.kind, "media")
        self.assertEqual(retry.text, "000201010212PAYIPPIXCREATE168836304DCBA")
        self.assertEqual(payip_service.create_charge_calls[-1]["external_id"], "16883")

    def test_finance_payip_charge_accepts_confirmation_with_extra_words(self) -> None:
        sender = "5511-fin-payip-create-confirm-extra"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="5"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="0,99"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="31/12/2026"), decision)

        result = self.flow.handle(IncomingMessage(sender=sender, text="Confirmar emissao PayIP"), decision)

        self.assertEqual(result.kind, "media")
        self.assertEqual(result.text, "000201010212PAYIPPIXCREATE168836304DCBA")
        self.assertEqual(self.payip_service.create_charge_calls[-1]["external_id"], "16883")

    def test_finance_payip_charge_retries_transient_create_error_before_failing(self) -> None:
        import bot_api.services.flows.payip_flow as payip_flow_module

        class RetryChargePayipService(StubPayipPaymentsService):
            def __init__(self) -> None:
                super().__init__()
                self.remaining_failures = 1

            def create_pix_charge(self, **kwargs: object) -> dict[str, object]:
                if self.remaining_failures:
                    self.remaining_failures -= 1
                    raise PayipError("PayIP charge request failed: HTTP 503")
                return super().create_pix_charge(**kwargs)

        sender = "5511-fin-payip-create-internal-retry"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = RetryChargePayipService()
        flow = make_flow(payip_payments_service=payip_service)

        previous_delay = payip_flow_module.PAYIP_CHARGE_RETRY_DELAY_SECONDS
        payip_flow_module.PAYIP_CHARGE_RETRY_DELAY_SECONDS = 0
        try:
            _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="5"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="0,99"), decision)
            _ = flow.handle(IncomingMessage(sender=sender, text="31/12/2026"), decision)
            result = flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR"), decision)
        finally:
            payip_flow_module.PAYIP_CHARGE_RETRY_DELAY_SECONDS = previous_delay

        self.assertEqual(result.kind, "media")
        self.assertEqual(result.text, "000201010212PAYIPPIXCREATE168836304DCBA")
        self.assertEqual(len(payip_service.create_charge_calls), 1)

    def test_finance_payip_allows_charge_rate_interest_and_due_date_adjustment(self) -> None:
        sender = "5511-fin-payip-create-adjust"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="5"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="10,00"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="31/12/2026"), decision)

        adjusted_rate = self.flow.handle(IncomingMessage(sender=sender, text="taxa 5,00"), decision)
        self.assertIn("Taxa PIX: R$ 5,00", adjusted_rate.text)
        self.assertIn("Total estimado: R$ 15,00", adjusted_rate.text)

        adjusted_interest = self.flow.handle(IncomingMessage(sender=sender, text="juros 8"), decision)
        self.assertIn("Juros apos vencimento: 8% ao dia", adjusted_interest.text)

        adjusted_due_date = self.flow.handle(IncomingMessage(sender=sender, text="vencimento 30/12/2026"), decision)
        self.assertIn("Vencimento: 30/12/2026", adjusted_due_date.text)

        result = self.flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR"), decision)

        self.assertEqual(result.kind, "media")
        self.assertEqual(self.payip_service.create_charge_calls[-1]["rate_amount"], "5.00")
        self.assertEqual(self.payip_service.create_charge_calls[-1]["interest_perc"], "8.00")
        self.assertEqual(self.payip_service.create_charge_calls[-1]["due_date"], "2026-12-30")

    def test_finance_payip_allows_optional_invoice_on_charge(self) -> None:
        sender = "5511-fin-payip-create-invoice"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="5"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="10,00"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="31/12/2026"), decision)

        with_invoice = self.flow.handle(IncomingMessage(sender=sender, text="nf 147478"), decision)

        self.assertIn("Nota fiscal: 147478", with_invoice.text)

        without_invoice = self.flow.handle(IncomingMessage(sender=sender, text="sem nf"), decision)

        self.assertIn("Nota fiscal: -", without_invoice.text)

        _ = self.flow.handle(IncomingMessage(sender=sender, text="nota fiscal 147478"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR"), decision)

        self.assertEqual(result.kind, "media")
        self.assertEqual(self.payip_service.create_charge_calls[-1]["invoice"], "147478")

    def test_finance_payip_allows_optional_nb_on_charge(self) -> None:
        sender = "5511-fin-payip-create-no-nb"
        decision = make_decision(allowed=True, roles=("financeiro",))

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="5"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="3 16883"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="10,00"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="31/12/2026"), decision)

        without_nb = self.flow.handle(IncomingMessage(sender=sender, text="sem nb"), decision)

        self.assertIn("NB: -", without_nb.text)

        with_nb = self.flow.handle(IncomingMessage(sender=sender, text="nb 16883"), decision)

        self.assertIn("NB: 16883", with_nb.text)

        _ = self.flow.handle(IncomingMessage(sender=sender, text="sem nb"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="CONFIRMAR"), decision)

        self.assertEqual(result.kind, "media")
        self.assertEqual(self.payip_service.create_charge_calls[-1]["external_id"], "")

    def test_finance_payip_invoice_search_resumes_after_mfa(self) -> None:
        sender = "5511-fin-payip-invoice-mfa"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(require_mfa_once=True)
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="1"), decision)
        prompt = flow.handle(IncomingMessage(sender=sender, text="3 147478"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_awaiting_mfa")
        self.assertEqual(flow.sessions[sender].payip_pending_action, "invoice")
        self.assertEqual(flow.sessions[sender].payip_pending_invoice, "147478")

        result = flow.handle(IncomingMessage(sender=sender, text="123456"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("PayIP | Nota Fiscal 147478", result.text)
        self.assertEqual(payip_service.bootstrap_calls, ["123456"])
        self.assertEqual(
            payip_service.list_calls[-1],
            {"page": 1, "page_size": 50, "status": "", "client_code": "", "invoice": "147478", "filial": "3"},
        )

    def test_finance_payip_charge_lookup_after_mfa_reports_company_error_without_reasking_mfa(self) -> None:
        sender = "5511-fin-payip-charge-mfa-company-error"
        decision = make_decision(allowed=True, roles=("financeiro",))
        payip_service = StubPayipPaymentsService(
            require_mfa_once=True,
            client_lookup_error=PayipError(
                'PayIP clients request failed: HTTP 403. Response: {"message":"Empresa nao encontrada.","error":"FORBIDDEN"}'
            ),
        )
        flow = make_flow(payip_payments_service=payip_service)

        _ = flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="9"), decision)
        _ = flow.handle(IncomingMessage(sender=sender, text="5"), decision)
        prompt = flow.handle(IncomingMessage(sender=sender, text="3 9860"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("Envie aqui o codigo atual do Google Authenticator", prompt.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_awaiting_mfa")

        result = flow.handle(IncomingMessage(sender=sender, text="949047"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("Nao consegui buscar esse cliente na PayIP agora.", result.text)
        self.assertIn("Revenda: 3 - Patos", result.text)
        self.assertIn("NB: 9860", result.text)
        self.assertIn("A sessao foi validada", result.text)
        self.assertNotIn("Nao consegui validar esse codigo MFA", result.text)
        self.assertNotIn("Envie aqui o codigo atual do Google Authenticator", result.text)
        self.assertEqual(flow.sessions[sender].step, "finance_payip_charge_awaiting_client")
        self.assertEqual(payip_service.bootstrap_calls, ["949047"])

    def test_finance_prazo_limite_lookup_by_registration_builds_response(self) -> None:
        sender = "5511-fin-prazo"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.documentacao_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="SEG/",
                contrato_social="OK",
                cpf="OK",
                rg="Nok",
                comprovante_residencia="OK",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=0,
                pending_docs=(),
                planilha_atualizada_em="2026-04-27",
            )
        ]
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                documento="12345678901",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Jan",
                        percentual_pag_atraso="0.16",
                        prazo_atual="15",
                        cond_pag_atual="715",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 92.256,85",
                        pedidos="8",
                    ),
                    SimpleNamespace(
                        kpi="Fev",
                        percentual_pag_atraso="0.16",
                        prazo_atual="15",
                        cond_pag_atual="715",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 90.144,61",
                        pedidos="12",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]
        self.inadimplencia_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                valor_pendente="100,00",
            ),
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                valor_pendente="250,50",
            ),
        ]
        self.giro_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                setor="400",
                revenda="3",
                total_litrinho="10",
                real_litrinho="5",
                gap_litrinho="20",
                giro_litrinho="NOK",
                total_inteira="10",
                real_inteira="3",
                gap_inteira="12",
                giro_inteira="NOK",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="2026-04-27",
            )
        ]
        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="8"), decision)

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Prazo e Limite")
        self.assertEqual(self.flow.sessions[sender].search_context, "prazo_limite")

        _ = self.flow.handle(IncomingMessage(sender=sender, text="1"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="3"), decision)
        result = self.flow.handle(IncomingMessage(sender=sender, text="9845"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("Analise Financeira", result.text)
        self.assertIn("Cliente: CLIENTE TESTE", result.text)
        self.assertIn("Revenda: 3 | NB: 9845 | Setor: 400", result.text)
        self.assertIn("RN: 400 | GV: 4", result.text)
        self.assertIn("CPF: 123.456.789-01 | CNPJ: -", result.text)
        self.assertIn("Prazo e Limite", result.text)
        self.assertIn("Prazo atual: 15", result.text)
        self.assertIn("Cond. pag.: 715", result.text)
        self.assertIn("Limite total: R$ 80.000,00", result.text)
        self.assertIn("Pag. em atraso: 16%", result.text)
        self.assertIn("Faturamento", result.text)
        self.assertIn("Jan: R$ 92.256,85", result.text)
        self.assertIn("Pedidos: 8 | Media por pedido: R$ 11.532,11", result.text)
        self.assertIn("Fev: R$ 90.144,61", result.text)
        self.assertIn("Pedidos: 12 | Media por pedido: R$ 7.512,05", result.text)
        self.assertIn("Inadimplencia", result.text)
        self.assertIn("Total vencido: R$ 350,50", result.text)
        self.assertIn("Titulos em aberto: 2", result.text)
        self.assertIn("Documentacao", result.text)
        self.assertIn("Contrato Social: OK", result.text)
        self.assertIn("Cpf/Rg: OK", result.text)
        self.assertIn("Comprovante residencia: OK", result.text)
        self.assertIn("Fachada: OK", result.text)
        self.assertIn("Giro de Vasilhame", result.text)
        self.assertIn("Caixas na base: 20", result.text)
        self.assertIn("Caixas OK: 8", result.text)
        self.assertIn("Faltam: 32", result.text)
        self.assertIn("Falta: Litrinho 20 | Inteira 12", result.text)
        self.assertIn("Atualizado em: 27/04/2026", result.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_finance_alias_analise_runs_prazo_limite_name_lookup_directly(self) -> None:
        sender = "5511-fin-analise"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.query_service.fantasia_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="9845",
                razao_social="CLIENTE TESTE LTDA",
                nome_fantasia="CLIENTE TESTE",
                telefone="83999999999",
                dia_visita="SEG/",
                vendedor="400",
                status="ATIVO",
                cidade="Patos",
                cond_pag_atual="715",
                limite_credito="80000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-27",
            )
        ]
        self.documentacao_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="SEG/",
                contrato_social="OK",
                cpf="OK",
                rg="Nok",
                comprovante_residencia="OK",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=0,
                pending_docs=(),
                planilha_atualizada_em="2026-04-27",
            )
        ]
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                documento="12345678901",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Jan",
                        percentual_pag_atraso="0.16",
                        prazo_atual="15",
                        cond_pag_atual="715",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 92.256,85",
                        pedidos="8",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="analise cliente teste"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Analise Financeira", response.text)
        self.assertIn("Prazo e Limite", response.text)
        self.assertIn("CLIENTE TESTE", response.text)
        self.assertIn("CPF: 123.456.789-01 | CNPJ: -", response.text)
        self.assertIn("Documentacao", response.text)
        self.assertIn("Contrato Social: OK", response.text)
        self.assertIn("Cpf/Rg: OK", response.text)
        self.assertIn("Pag. em atraso: 16%", response.text)
        self.assertIn("Prazo atual: 15", response.text)
        self.assertIn("Jan: R$ 92.256,85", response.text)
        self.assertIn("Pedidos: 8 | Media por pedido: R$ 11.532,11", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_finance_alias_analise_runs_prazo_limite_registration_lookup_directly(self) -> None:
        sender = "5511-fin-analise-reg"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                documento="12345678901",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Abr",
                        percentual_pag_atraso="0.05",
                        prazo_atual="5",
                        cond_pag_atual="505",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 66.008,44",
                        pedidos="12",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="analise 3 9845"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Analise Financeira", response.text)
        self.assertIn("Cliente: CLIENTE TESTE", response.text)
        self.assertIn("Revenda: 3 | NB: 9845 | Setor: 400", response.text)
        self.assertIn("CPF: 123.456.789-01 | CNPJ: -", response.text)
        self.assertIn("Abr: R$ 66.008,44", response.text)
        self.assertEqual(self.prazo_limite_service.search_calls[0]["filial"], "3")
        self.assertEqual(self.prazo_limite_service.search_calls[0]["cod_pdv"], "9845")
        self.assertEqual(self.query_service.fantasia_calls, [])

    def test_prazo_limite_name_search_multiple_results_uses_contextual_menu(self) -> None:
        sender = "5511-fin-prazo-lista"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.query_service.fantasia_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="9845",
                razao_social="CLIENTE TESTE LTDA",
                nome_fantasia="CLIENTE TESTE",
                telefone="83999999999",
                dia_visita="SEG/",
                vendedor="400",
                status="ATIVO",
                cidade="Patos",
                cond_pag_atual="715",
                limite_credito="80000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-27",
            ),
            DClienteRecord(
                filial="4",
                cod_pdv="1111",
                razao_social="CLIENTE TESTE 2 LTDA",
                nome_fantasia="CLIENTE TESTE 2",
                telefone="83988888888",
                dia_visita="TER/",
                vendedor="500",
                status="ATIVO",
                cidade="Sousa",
                cond_pag_atual="505",
                limite_credito="50000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-27",
            ),
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="8"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="2"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="cliente teste"), decision)

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Resultados de Prazo e Limite")
        self.assertIn("na base de prazo e limite", response.text)
        self.assertIn("prazo, limite e documentacao", response.text)
        self.assertIn("nb, revenda e nome do cliente", response.footer.lower())

    def test_prazo_limite_name_search_selection_keeps_prazo_limite_context(self) -> None:
        sender = "5511-fin-prazo-lista-pick"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.query_service.fantasia_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="9845",
                razao_social="CLIENTE TESTE LTDA",
                nome_fantasia="CLIENTE TESTE",
                telefone="83999999999",
                dia_visita="SEG/",
                vendedor="400",
                status="ATIVO",
                cidade="Patos",
                cond_pag_atual="715",
                limite_credito="80000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-27",
            ),
            DClienteRecord(
                filial="4",
                cod_pdv="1111",
                razao_social="CLIENTE TESTE 2 LTDA",
                nome_fantasia="CLIENTE TESTE 2",
                telefone="83988888888",
                dia_visita="TER/",
                vendedor="500",
                status="ATIVO",
                cidade="Sousa",
                cond_pag_atual="505",
                limite_credito="50000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-27",
            ),
        ]
        self.documentacao_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="SEG/",
                contrato_social="OK",
                cpf="OK",
                rg="Nok",
                comprovante_residencia="OK",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=0,
                pending_docs=(),
                planilha_atualizada_em="2026-04-27",
            )
        ]
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                documento="12345678901",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Jan",
                        percentual_pag_atraso="0.16",
                        prazo_atual="15",
                        cond_pag_atual="715",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 92.256,85",
                        pedidos="8",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="8"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="2"), decision)
        menu = self.flow.handle(IncomingMessage(sender=sender, text="cliente teste"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="1"), decision)

        self.assertEqual(menu.kind, "menu")
        self.assertEqual(response.kind, "text")
        self.assertIn("Analise Financeira", response.text)
        self.assertIn("CPF: 123.456.789-01 | CNPJ: -", response.text)
        self.assertIn("Prazo e Limite", response.text)
        self.assertIn("Jan: R$ 92.256,85", response.text)
        self.assertIn("Pedidos: 8 | Media por pedido: R$ 11.532,11", response.text)
        self.assertIn("Cliente: CLIENTE TESTE", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_prazo_limite_document_search_keeps_prazo_limite_context(self) -> None:
        sender = "5511-fin-prazo-doc"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.query_service.document_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="9845",
                razao_social="CLIENTE TESTE LTDA",
                nome_fantasia="CLIENTE TESTE",
                telefone="83999999999",
                dia_visita="SEG/",
                vendedor="400",
                status="ATIVO",
                cidade="Patos",
                cond_pag_atual="715",
                limite_credito="80000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-27",
            )
        ]
        self.documentacao_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="SEG/",
                contrato_social="OK",
                cpf="OK",
                rg="Nok",
                comprovante_residencia="OK",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=0,
                pending_docs=(),
                planilha_atualizada_em="2026-04-27",
            )
        ]
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                documento="12345678901",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Jan",
                        percentual_pag_atraso="0.16",
                        prazo_atual="15",
                        cond_pag_atual="715",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 92.256,85",
                        pedidos="8",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        _ = self.flow.handle(IncomingMessage(sender=sender, text="8"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="3"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="12345678901"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("cpf ou cnpj", prompt.text.lower())
        self.assertEqual(response.kind, "text")
        self.assertIn("Analise Financeira", response.text)
        self.assertIn("CPF: 123.456.789-01 | CNPJ: -", response.text)
        self.assertIn("Prazo e Limite", response.text)
        self.assertIn("Jan: R$ 92.256,85", response.text)
        self.assertIn("Pedidos: 8 | Media por pedido: R$ 11.532,11", response.text)
        self.assertIn("Cliente: CLIENTE TESTE", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_finance_alias_analise_cpf_runs_prazo_limite_document_lookup_directly(self) -> None:
        sender = "5511-fin-analise-cpf"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.query_service.document_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="9845",
                razao_social="CLIENTE TESTE LTDA",
                nome_fantasia="CLIENTE TESTE",
                telefone="83999999999",
                dia_visita="SEG/",
                vendedor="400",
                status="ATIVO",
                cidade="Patos",
                cond_pag_atual="715",
                limite_credito="80000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-27",
            )
        ]
        self.documentacao_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="SEG/",
                contrato_social="OK",
                cpf="OK",
                rg="Nok",
                comprovante_residencia="OK",
                fachada="OK",
                ficha_cadastro="Nok",
                pending_count=0,
                pending_docs=(),
                planilha_atualizada_em="2026-04-27",
            )
        ]
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                documento="12345678901",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Jan",
                        percentual_pag_atraso="0.16",
                        prazo_atual="15",
                        cond_pag_atual="715",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 92.256,85",
                        pedidos="8",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="analise cpf 123.456.789-01"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Analise Financeira", response.text)
        self.assertIn("CPF: 123.456.789-01 | CNPJ: -", response.text)
        self.assertEqual(self.prazo_limite_service.document_calls[0]["document"], "12345678901")
        self.assertEqual(self.prazo_limite_service.document_calls[0]["allowed_sectors"], None)
        self.assertEqual(self.query_service.document_calls, [])
        self.assertEqual(self.query_service.fantasia_calls, [])
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_finance_cpf_alias_runs_prazo_limite_document_lookup_directly(self) -> None:
        sender = "5511-fin-cpf-prazo"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="9845",
                nome="CLIENTE TESTE",
                documento="12345678901",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Jan",
                        percentual_pag_atraso="0.16",
                        prazo_atual="15",
                        cond_pag_atual="715",
                        limite_total="R$ 80.000,00",
                        faturamento_com_pdv="R$ 92.256,85",
                        pedidos="8",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="cpf 123.456.789-01"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Analise Financeira", response.text)
        self.assertEqual(self.prazo_limite_service.document_calls[0]["document"], "12345678901")
        self.assertEqual(self.query_service.document_calls, [])

    def test_seller_analise_cpf_runs_unrestricted_prazo_limite_document_lookup(self) -> None:
        sender = "5511-seller-analise-cpf"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_406",))
        self.prazo_limite_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="10009",
                nome="BOX MARCON",
                documento="82552401449",
                setor="406",
                seller_code="3_406",
                manager_code="3_4",
                entries=(
                    SimpleNamespace(
                        kpi="Jan",
                        percentual_pag_atraso="0.05",
                        prazo_atual="7",
                        cond_pag_atual="705",
                        limite_total="R$ 1.000,00",
                        faturamento_com_pdv="R$ 2.000,00",
                        pedidos="4",
                    ),
                ),
                planilha_atualizada_em="2026-04-27",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="analise cpf 825.524.014-49"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Analise Financeira", response.text)
        self.assertEqual(self.prazo_limite_service.document_calls[0]["document"], "82552401449")
        self.assertIsNone(self.prazo_limite_service.document_calls[0]["allowed_sectors"])
        self.assertIsNone(self.prazo_limite_service.document_calls[0]["allowed_gv_vdes"])
        self.assertEqual(self.query_service.document_calls, [])

    def test_build_single_record_response_includes_documentacao_pending_summary(self) -> None:
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.documentacao_service.search_records = [
            SimpleNamespace(
                filial="3",
                cod_pdv="6643",
                nome="ESPETO DO PAULO",
                setor="400",
                seller_code="3_400",
                manager_code="3_4",
                visit_day="SEG/",
                contrato_social="OK",
                cpf="Nok",
                rg="OK",
                comprovante_residencia="Nok",
                fachada="OK",
                ficha_cadastro="OK",
                pending_count=2,
                pending_docs=("Cpf", "Comprovante de residencia"),
                planilha_atualizada_em="2026-04-20",
            )
        ]
        record = DClienteRecord(
            filial="3",
            cod_pdv="6643",
            razao_social="ESPETO DO PAULO LTDA",
            nome_fantasia="ESPETO DO PAULO",
            telefone="83999999999",
            dia_visita="SEG/",
            vendedor="400",
            status="ATIVO",
            cidade="Patos",
            cond_pag_atual="A vista",
            limite_credito="1000",
            total_pendente="0,00",
            total_comodatos_pendentes=0,
            ultima_atualizacao_tabela="2026-04-20",
        )

        response = self.flow._build_single_record_response(
            record=record,
            criteria="revenda 3 e Cod PDV 6643",
            decision=decision,
        )

        self.assertIn("*Documentacao:*", response.text)
        self.assertIn("- Cpf: Nok", response.text)
        self.assertIn("- Comprovante de residencia: Nok", response.text)

    def test_handle_dynamic_main_menu_shortcut_routes_seller_to_giro(self) -> None:
        sender = "5520"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.query_service.visit_days = ["SEG/", "QUI/"]
        menu = self.flow.handle(
            IncomingMessage(sender=sender, text="menu"),
            decision,
        )

        self.assertEqual(menu.kind, "menu")
        self.assertEqual(menu.title, "Consultas")
        self.assertEqual(
            [(option.shortcut, option.title) for option in menu.options],
            [
                ("1", "Rota do Dia"),
                ("2", "Risco da Rota"),
                ("3", "Giro"),
                ("4", "Documentacao Pendente"),
                ("5", "Buscar Cliente"),
                ("6", "Cobranca da Carteira"),
                ("7", "Comodatos"),
                ("8", "Financeiro"),
                ("9", "Carteira"),
                ("10", "Critica"),
            ],
        )
        self.assertIn("rota segunda", menu.footer)
        self.assertIn("giro quinta", menu.footer)
        self.assertIn("inad hoje", menu.footer)
        self.assertIn("3 6643", menu.footer)

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="3"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Consultar Giro")
        self.assertIn("Como voce quer procurar o giro?", response.text)

        finance_menu = self.flow.handle(
            IncomingMessage(sender=sender, text="menu"),
            decision,
        )
        self.assertEqual(finance_menu.kind, "menu")
        response = self.flow.handle(
            IncomingMessage(sender=sender, text="8"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Financeiro")
        self.assertEqual(
            [(option.shortcut, option.title) for option in response.options],
            [("1", "Solicitar Recolha"), ("2", "Solicitar Boleto")],
        )

    def test_handle_seller_carteira_response_is_more_operational(self) -> None:
        sender = "5520-carteira"
        current_day_label = _current_visit_day_label()
        current_token_map = {
            "segunda": "SEG/",
            "terca": "TER/",
            "quarta": "QUA/",
            "quinta": "QUI/",
            "sexta": "SEX/",
            "sabado": "SAB/",
            "domingo": "DOM/",
        }
        self.query_service.scope_summary = SimpleNamespace(
            client_count=12,
            seller_count=1,
            planilha_atualizada_em="2026-04-15",
        )
        self.inadimplencia_service.finance_summary = SimpleNamespace(
            client_count=5,
            total_pendente="100,00",
            due_in_two_days_count=1,
            due_in_two_days_total="15,00",
            due_tomorrow_count=1,
            due_tomorrow_total="20,00",
            due_today_count=1,
            due_today_total="25,00",
            overdue_count=2,
            overdue_total="40,00",
            planilha_atualizada_em="2026-04-15",
        )
        self.giro_service.scope_summary = SimpleNamespace(
            client_count=12,
            attention_count=5,
            zero_count=2,
            litrinho_monitored_count=40,
            litrinho_ok_count=10,
            litrinho_nok_count=20,
            litrinho_zero_count=10,
            litrinho_gap_total="30",
            inteira_monitored_count=10,
            inteira_ok_count=4,
            inteira_nok_count=4,
            inteira_zero_count=2,
            inteira_gap_total="6",
            litrao_monitored_count=5,
            litrao_ok_count=2,
            litrao_nok_count=2,
            litrao_zero_count=1,
            litrao_gap_total="3",
            planilha_atualizada_em="2026-04-15",
        )
        self.query_service.visit_days = [current_token_map[current_day_label]]
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="111",
                razao_social="Cliente Alpha LTDA",
                nome_fantasia="Cliente Alpha",
                telefone="",
                dia_visita=current_token_map[current_day_label],
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="25,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-15",
            )
        ]
        self.inadimplencia_service.upcoming_alerts = [
            SimpleNamespace(
                cod_pdv="111",
                nome="Cliente Alpha",
                title_count=1,
                total_pendente="25,00",
                nearest_days_to_due=0,
                planilha_atualizada_em="2026-04-15",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="carteira"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Carteira de Hoje", response.text)
        self.assertIn("Base: 12 clientes | 1 setor(es)", response.text)
        self.assertIn("Cobranca da carteira: 5 inadimplentes | R$ 100,00", response.text)
        self.assertIn(f"*Rota de hoje ({current_day_label.title()}):* 1 visita(s)", response.text)
        self.assertIn("Risco da rota: 1 cliente(s) | R$ 25,00", response.text)

    def test_handle_manager_main_menu_prioritizes_gerencia_and_routes_to_submenu(self) -> None:
        sender = "5521"
        decision = make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_4",))

        menu = self.flow.handle(
            IncomingMessage(sender=sender, text="menu"),
            decision,
        )

        self.assertEqual(menu.kind, "menu")
        self.assertEqual(menu.title, "Consultas")
        self.assertEqual(
            [(option.shortcut, option.title) for option in menu.options],
            [
                ("1", "Gerencia"),
                ("2", "Rota do Dia"),
                ("3", "Cobranca da Gerencia"),
                ("4", "Giro da Gerencia"),
                ("5", "Documentacao Pendente"),
                ("6", "Buscar Cliente"),
                ("7", "Comodatos"),
                ("8", "Financeiro"),
                ("9", "Critica"),
            ],
        )
        self.assertIn("rota segunda", menu.footer)
        self.assertIn("inad segunda", menu.footer)
        self.assertIn("giro segunda", menu.footer)
        self.assertIn("vencimentos", menu.footer)
        self.assertIn("equipe", menu.footer)

        submenu = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(submenu.kind, "menu")
        self.assertEqual(submenu.title, "Gerencia")
        self.assertEqual(
            [(option.shortcut, option.title) for option in submenu.options],
            [
                ("1", "Risco da Rota"),
                ("2", "Vencimentos"),
                ("3", "Cobranca Consolidada"),
                ("4", "Equipe"),
                ("5", "Filiais"),
                ("6", "Giro Consolidado"),
                ("7", "Resumo Total"),
            ],
        )

        main_menu = self.flow.handle(
            IncomingMessage(sender=sender, text="menu"),
            decision,
        )
        self.assertEqual(main_menu.kind, "menu")
        finance_menu = self.flow.handle(
            IncomingMessage(sender=sender, text="8"),
            decision,
        )

        self.assertEqual(finance_menu.kind, "menu")
        self.assertEqual(finance_menu.title, "Financeiro")
        self.assertEqual(
            [(option.shortcut, option.title) for option in finance_menu.options],
            [("1", "Solicitar Recolha"), ("2", "Solicitar Boleto")],
        )

    def test_handle_director_main_menu_prioritizes_diretoria_and_routes_to_submenu(self) -> None:
        sender = "5521dc"
        decision = make_decision(allowed=True, roles=("diretor_comercial",), gv_vdes=("dc:3_1",))

        menu = self.flow.handle(
            IncomingMessage(sender=sender, text="menu"),
            decision,
        )

        self.assertEqual(menu.kind, "menu")
        self.assertEqual(menu.title, "Consultas")
        self.assertEqual(
            [(option.shortcut, option.title) for option in menu.options],
            [
                ("1", "Diretoria"),
                ("2", "Rota do Dia"),
                ("3", "Cobranca"),
                ("4", "Giro"),
                ("5", "Documentacao Pendente"),
                ("6", "Buscar Cliente"),
                ("7", "Comodatos"),
            ],
        )

        submenu = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(submenu.kind, "menu")
        self.assertEqual(submenu.title, "Diretoria")
        self.assertEqual(
            [(option.shortcut, option.title) for option in submenu.options],
            [
                ("1", "Risco da Rota"),
                ("2", "Cobranca"),
                ("3", "GVs"),
                ("4", "Filiais"),
                ("5", "Giro"),
                ("6", "Ranking dos GVs"),
                ("7", "Resumo Total"),
            ],
        )

    def test_handle_director_main_menu_shortcut_routes_to_cobranca(self) -> None:
        sender = "5521dc-cobranca"
        decision = make_decision(allowed=True, roles=("diretor_comercial",), gv_vdes=("dc:3_1",))

        menu = self.flow.handle(
            IncomingMessage(sender=sender, text="menu"),
            decision,
        )

        self.assertEqual(menu.title, "Consultas")

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="3"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Consultar Inadimplencia")
        self.assertIn("como voce quer procurar a inadimplencia", response.text.lower())

    def test_handle_director_summary_menu_shortcut_routes_to_giro_menu(self) -> None:
        sender = "5521dc-giro"
        decision = make_decision(allowed=True, roles=("diretor_comercial",), gv_vdes=("dc:3_1",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="menu"),
            decision,
        )
        self.assertEqual(first.title, "Consultas")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )
        self.assertEqual(second.title, "Diretoria")

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="5"),
            decision,
        )

        self.assertEqual(third.kind, "menu")
        self.assertEqual(third.title, "Giro da Diretoria")

    def test_resolve_admin_scope_codes_for_dc_requires_filial_dc_key(self) -> None:
        self.query_service.gv_vdes = ["3_4"]

        scope_codes, error = self.flow._resolve_admin_scope_codes("3-1", "diretor_comercial")

        self.assertEqual(scope_codes, ["dc:3_1"])
        self.assertIsNone(error)

        scope_codes, error = self.flow._resolve_admin_scope_codes("1", "diretor_comercial")

        self.assertEqual(scope_codes, [])
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("filial-DC", error)

    def test_resolve_admin_scope_codes_for_financeiro_accepts_filiais_only(self) -> None:
        scope_codes, error = self.flow._resolve_admin_scope_codes("3, 4", "financeiro")

        self.assertEqual(scope_codes, ["filial:3", "filial:4"])
        self.assertIsNone(error)

        scope_codes, error = self.flow._resolve_admin_scope_codes("3-400", "financeiro")

        self.assertEqual(scope_codes, [])
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("filial valida", error)

    def test_financeiro_with_filial_scope_is_restricted_to_allowed_filiais(self) -> None:
        decision = make_decision(allowed=True, roles=("financeiro",), sectors=("filial:3",))

        self.assertFalse(self.flow._has_unrestricted_lookup_access(decision))
        self.assertEqual(self.flow._allowed_sectors(decision), ["filial:3"])
        self.assertEqual(self.flow._allowed_gv_vdes(decision), [])

    def test_handle_giro_visit_day_selection_returns_summary_for_selected_day(self) -> None:
        sender = "5521"
        self.query_service.visit_days = ["SEG/", "QUA/"]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=43,
            attention_count=20,
            zero_count=9,
            litrinho_monitored_count=397,
            litrinho_ok_count=77,
            litrinho_nok_count=118,
            litrinho_zero_count=202,
            litrinho_gap_total="320",
            inteira_monitored_count=99,
            inteira_ok_count=14,
            inteira_nok_count=36,
            inteira_zero_count=49,
            inteira_gap_total="85",
            litrao_monitored_count=12,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=12,
            litrao_gap_total="12",
            planilha_atualizada_em="11/04/2026",
        )
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_401",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="giro"),
            decision,
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Consultar Giro")
        option_titles = {option.title for option in first.options}
        self.assertIn("Giro por dia", option_titles)

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="4"),
            decision,
        )

        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Giro por Dia")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_giro_visit_day_selection")

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(third.kind, "text")
        self.assertIn("Oportunidade de giro em Segunda:", third.text)
        self.assertIn("Clientes monitorados: 43", third.text)
        self.assertIn("Caixas na rota: 508", third.text)
        self.assertIn("Caixas OK: 91", third.text)
        self.assertIn("Caixas faltando para bater o giro: 417", third.text)
        self.assertIn("Resumo OK:", third.text)
        self.assertIn("Clientes com oportunidade: 0 | Caixas com giro: 0 | Faltam: 0", third.text)
        self.assertEqual(self.giro_service.visit_day_summary_calls[-1]["visit_day"], "SEG/")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_giro_visit_day_unifies_summary_and_clients_with_boxes(self) -> None:
        sender = "5521b"
        self.query_service.visit_days = ["SEG/"]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=2,
            attention_count=1,
            zero_count=0,
            litrinho_monitored_count=10,
            litrinho_ok_count=5,
            litrinho_nok_count=5,
            litrinho_zero_count=0,
            litrinho_gap_total="15",
            inteira_monitored_count=2,
            inteira_ok_count=0,
            inteira_nok_count=2,
            inteira_zero_count=0,
            inteira_gap_total="4",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0",
            planilha_atualizada_em="11/04/2026",
        )
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="100",
                razao_social="Cliente Zero LTDA",
                nome_fantasia="Cliente Zero",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="101",
                razao_social="Cliente Caixa LTDA",
                nome_fantasia="Cliente Caixa",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="102",
                razao_social="Cliente OK LTDA",
                nome_fantasia="Cliente OK",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="3",
                cod_pdv="100",
                nome="Cliente Zero",
                setor="400",
                revenda="3",
                total_litrinho="0",
                real_litrinho="0",
                gap_litrinho="0",
                giro_litrinho="-",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="101",
                nome="Cliente Caixa",
                setor="400",
                revenda="3",
                total_litrinho="10",
                real_litrinho="5",
                gap_litrinho="15",
                giro_litrinho="NOK",
                total_inteira="2",
                real_inteira="0",
                gap_inteira="4",
                giro_inteira="NOK",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="102",
                nome="Cliente OK",
                setor="400",
                revenda="3",
                total_litrinho="6",
                real_litrinho="12",
                gap_litrinho="0",
                giro_litrinho="OK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="giro"),
            decision,
        )

        self.assertEqual(first.kind, "menu")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="4"),
            decision,
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("Oportunidade de giro em Segunda:", second.text)
        self.assertIn("Resumo OK:", second.text)
        self.assertIn("Clientes com oportunidade de giro:", second.text)
        self.assertIn("*Setor 400*", second.text)
        self.assertIn("1) Cliente Caixa | Cod 101", second.text)
        self.assertIn("Base: 12 | Falta: 19", second.text)
        self.assertIn("Tipo: Litrinho 15, Inteira 4", second.text)
        self.assertNotIn("Codigo 100 | Cliente Zero", second.text)
        self.assertNotIn("Codigo 102 | Cliente OK", second.text)

    def test_handle_natural_giro_de_quinta_goes_straight_to_visit_day_summary(self) -> None:
        sender = "5522"
        self.query_service.visit_days = ["SEG/", "QUI/"]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=12,
            attention_count=5,
            zero_count=2,
            litrinho_monitored_count=100,
            litrinho_ok_count=25,
            litrinho_nok_count=50,
            litrinho_zero_count=25,
            litrinho_gap_total="75",
            inteira_monitored_count=20,
            inteira_ok_count=5,
            inteira_nok_count=10,
            inteira_zero_count=5,
            inteira_gap_total="15",
            litrao_monitored_count=10,
            litrao_ok_count=2,
            litrao_nok_count=4,
            litrao_zero_count=4,
            litrao_gap_total="8",
            planilha_atualizada_em="11/04/2026",
        )
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="giro de quinta"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Oportunidade de giro em Quinta:", response.text)
        self.assertIn("Clientes com oportunidade de giro:", response.text)
        self.assertEqual(self.giro_service.visit_day_summary_calls[-1]["visit_day"], "QUI/")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_manager_giro_visit_day_groups_opportunities_by_sector_in_order(self) -> None:
        sender = "5522b"
        self.query_service.visit_days = ["SEG/"]
        self.query_service.visit_day_sellers = [
            SimpleNamespace(seller_code="3_400", manager_code="3_4", visit_count=3),
            SimpleNamespace(seller_code="3_401", manager_code="3_4", visit_count=1),
        ]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=4,
            attention_count=3,
            zero_count=0,
            litrinho_monitored_count=30,
            litrinho_ok_count=10,
            litrinho_nok_count=20,
            litrinho_zero_count=0,
            litrinho_gap_total="20",
            inteira_monitored_count=3,
            inteira_ok_count=1,
            inteira_nok_count=2,
            inteira_zero_count=0,
            inteira_gap_total="3",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0",
            planilha_atualizada_em="11/04/2026",
        )
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="301",
                razao_social="Cliente Setor 401 LTDA",
                nome_fantasia="Cliente Setor 401",
                telefone="",
                dia_visita="SEG/",
                vendedor="401",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="200",
                razao_social="Cliente Setor 400 B LTDA",
                nome_fantasia="Cliente Setor 400 B",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="100",
                razao_social="Cliente Setor 400 A LTDA",
                nome_fantasia="Cliente Setor 400 A",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="150",
                razao_social="Cliente Sem Gap LTDA",
                nome_fantasia="Cliente Sem Gap",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="3",
                cod_pdv="301",
                nome="Cliente Setor 401",
                setor="401",
                revenda="3",
                total_litrinho="4",
                real_litrinho="2",
                gap_litrinho="6",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="200",
                nome="Cliente Setor 400 B",
                setor="400",
                revenda="3",
                total_litrinho="5",
                real_litrinho="0",
                gap_litrinho="10",
                giro_litrinho="NOK",
                total_inteira="1",
                real_inteira="0",
                gap_inteira="2",
                giro_inteira="NOK",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="100",
                nome="Cliente Setor 400 A",
                setor="400",
                revenda="3",
                total_litrinho="3",
                real_litrinho="1",
                gap_litrinho="5",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="150",
                nome="Cliente Sem Gap",
                setor="400",
                revenda="3",
                total_litrinho="8",
                real_litrinho="16",
                gap_litrinho="0",
                giro_litrinho="OK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        decision = make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_4",))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="giro segunda"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Oportunidade de giro em Segunda:", response.text)
        self.assertIn("Clientes com oportunidade de giro:", response.text)
        self.assertIn("*Setor 400*", response.text)
        self.assertIn("*Setor 401*", response.text)
        self.assertNotIn("Cliente Sem Gap", response.text)
        self.assertIn("1) Cliente Setor 400 A | Cod 100", response.text)
        self.assertIn("Base: 3 | Falta: 5", response.text)
        self.assertIn("Tipo: Litrinho 5", response.text)
        self.assertIn("2) Cliente Setor 400 B | Cod 200", response.text)
        self.assertIn("Base: 6 | Falta: 12", response.text)
        self.assertIn("Tipo: Litrinho 10, Inteira 2", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_financeiro_giro_visit_day_groups_by_gv_and_sector(self) -> None:
        sender = "5522c"
        self.query_service.visit_days = ["SEG/"]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=6,
            attention_count=4,
            zero_count=1,
            litrinho_monitored_count=73,
            litrinho_ok_count=20,
            litrinho_nok_count=40,
            litrinho_zero_count=13,
            litrinho_gap_total="66",
            inteira_monitored_count=0,
            inteira_ok_count=0,
            inteira_nok_count=0,
            inteira_zero_count=0,
            inteira_gap_total="0",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0",
            planilha_atualizada_em="11/04/2026",
        )
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="10668",
                razao_social="BAR DO ROCK LTDA",
                nome_fantasia="BAR DO ROCK",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="12961",
                razao_social="CAFE LTDA",
                nome_fantasia="CAFE",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="10428",
                razao_social="HASHI MIX LTDA",
                nome_fantasia="HASHI MIX",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="16169",
                razao_social="RESTAURANTE DA GEANE LTDA",
                nome_fantasia="RESTAURANTE DA GEANE",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="140",
                razao_social="ADEGA DAOZINHO QUAR LTDA",
                nome_fantasia="ADEGA DAOZINHO QUAR",
                telefone="",
                dia_visita="SEG/",
                vendedor="203",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
        ]
        self.query_service.visit_day_sellers = [
            SimpleNamespace(seller_code="3_203", manager_code="3_2", visit_count=1),
            SimpleNamespace(seller_code="3_400", manager_code="3_4", visit_count=4),
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="3",
                cod_pdv="10668",
                nome="BAR DO ROCK",
                setor="400",
                revenda="3",
                total_litrinho="20",
                real_litrinho="0",
                gap_litrinho="40",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="12961",
                nome="CAFE",
                setor="400",
                revenda="3",
                total_litrinho="13",
                real_litrinho="4",
                gap_litrinho="22",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="10428",
                nome="HASHI MIX",
                setor="400",
                revenda="3",
                total_litrinho="0",
                real_litrinho="0",
                gap_litrinho="0",
                giro_litrinho="-",
                total_inteira="1",
                real_inteira="0",
                gap_inteira="2",
                giro_inteira="NOK",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="16169",
                nome="RESTAURANTE DA GEANE",
                setor="400",
                revenda="3",
                total_litrinho="0",
                real_litrinho="0",
                gap_litrinho="0",
                giro_litrinho="-",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="1",
                real_litrao="0",
                gap_litrao="2",
                giro_litrao="NOK",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="140",
                nome="ADEGA DAOZINHO QUAR",
                setor="203",
                revenda="3",
                total_litrinho="2",
                real_litrinho="0",
                gap_litrinho="4",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        decision = make_decision(allowed=True, roles=("financeiro",))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="giro segunda"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Giro por Dia")
        self.assertIn("Oportunidade de giro em Segunda:", response.text)
        self.assertIn("Clientes com oportunidade: 5 | Caixas com giro: 37 | Faltam: 70", response.text)
        self.assertIn("GVs com oportunidade: 2", response.text)
        self.assertEqual([option.title for option in response.options], ["Filial 3 | GV 2", "Filial 3 | GV 4"])
        self.assertEqual(response.options[0].description, "1 setor(es) | 1 cliente(s) | Caixas 2 | Faltam 4")
        self.assertEqual(response.options[1].description, "1 setor(es) | 4 cliente(s) | Caixas 35 | Faltam 66")
        self.assertEqual(self.query_service.visit_day_clients_calls[-1]["limit"], 5000)

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="2"),
            decision,
        )

        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Giro por Setor")
        self.assertIn("Filial 3 | GV 4", second.text)
        self.assertNotIn("Resumo dos setores:", second.text)
        self.assertEqual([option.title for option in second.options], ["Filial 3 | Setor 400"])
        self.assertEqual(second.options[0].description, "4 cliente(s) | Caixas 35 | Faltam 66")

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(third.kind, "text")
        self.assertIn("Filial 3 | GV 4 | Setor 400", third.text)
        self.assertIn("Clientes com oportunidade de giro:", third.text)
        self.assertIn("2) BAR DO ROCK | Cod 10668", third.text)
        self.assertIn("Base: 20 | Falta: 40", third.text)
        self.assertIn("Tipo: Litrinho 40", third.text)
        self.assertIn("1) HASHI MIX | Cod 10428", third.text)
        self.assertIn("Base: 1 | Falta: 2", third.text)
        self.assertIn("Tipo: Inteira 2", third.text)

    def test_handle_giro_visit_day_menu_hides_raw_composite_day_labels(self) -> None:
        response = self.flow._build_giro_visit_day_menu(
            ["SEG/QUI/", "SEG/TER/QUA/QUI/SEX/SAB/DOM/", "QUA/SEX/"]
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Giro por Dia")
        self.assertEqual(
            [option.title for option in response.options],
            ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"],
        )

    def test_handle_finance_giro_terca_matches_composite_visit_days(self) -> None:
        sender = "5522ter"
        self.query_service.visit_days = ["SEG/QUI/", "SEG/TER/QUA/QUI/SEX/SAB/DOM/", "QUA/SEX/"]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=1,
            attention_count=1,
            zero_count=0,
            litrinho_monitored_count=10,
            litrinho_ok_count=2,
            litrinho_nok_count=8,
            litrinho_zero_count=0,
            litrinho_gap_total="8",
            inteira_monitored_count=0,
            inteira_ok_count=0,
            inteira_nok_count=0,
            inteira_zero_count=0,
            inteira_gap_total="0",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0",
            planilha_atualizada_em="11/04/2026",
        )
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="10668",
                razao_social="BAR DO ROCK LTDA",
                nome_fantasia="BAR DO ROCK",
                telefone="",
                dia_visita="SEG/TER/QUA/QUI/SEX/SAB/DOM/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
        ]
        self.query_service.visit_day_sellers = [
            SimpleNamespace(seller_code="3_400", manager_code="3_4", visit_count=1),
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="3",
                cod_pdv="10668",
                nome="BAR DO ROCK",
                setor="400",
                revenda="3",
                total_litrinho="10",
                real_litrinho="2",
                gap_litrinho="8",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        decision = make_decision(allowed=True, roles=("financeiro",))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="giro terca"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Giro por Setor")
        self.assertIn("Filial 3 | GV 4", response.text)
        self.assertIn("Setores com oportunidade: 1 | Clientes com oportunidade: 1 | Caixas 10 | Faltam 8", response.text)
        self.assertEqual([option.title for option in response.options], ["Filial 3 | Setor 400"])
        self.assertEqual(response.options[0].description, "1 cliente(s) | Caixas 10 | Faltam 8")
        self.assertEqual(self.giro_service.visit_day_summary_calls[-1]["visit_day"], "TER/")
        self.assertEqual(self.query_service.visit_day_clients_calls[-1]["visit_day"], "TER/")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("Filial 3 | GV 4 | Setor 400", second.text)
        self.assertIn("1) BAR DO ROCK | Cod 10668", second.text)
        self.assertIn("Base: 10 | Falta: 8", second.text)
        self.assertIn("Tipo: Litrinho 8", second.text)

    def test_handle_director_multi_gv_giro_visit_day_uses_grouped_menu_and_full_limit(self) -> None:
        sender = "5522dcgiro"
        self.query_service.visit_days = ["QUI/"]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=10,
            attention_count=4,
            zero_count=1,
            litrinho_monitored_count=40,
            litrinho_ok_count=5,
            litrinho_nok_count=35,
            litrinho_zero_count=0,
            litrinho_gap_total="35",
            inteira_monitored_count=0,
            inteira_ok_count=0,
            inteira_nok_count=0,
            inteira_zero_count=0,
            inteira_gap_total="0",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0",
            planilha_atualizada_em="11/04/2026",
        )
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="1",
                cod_pdv="100",
                razao_social="CLIENTE A LTDA",
                nome_fantasia="CLIENTE A",
                telefone="",
                dia_visita="QUI/",
                vendedor="113",
                status="ativo",
                cidade="Sousa",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
            DClienteRecord(
                filial="3",
                cod_pdv="200",
                razao_social="CLIENTE B LTDA",
                nome_fantasia="CLIENTE B",
                telefone="",
                dia_visita="QUI/",
                vendedor="401",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            ),
        ]
        self.query_service.visit_day_sellers = [
            SimpleNamespace(seller_code="1_113", manager_code="1_1", visit_count=1),
            SimpleNamespace(seller_code="3_401", manager_code="3_4", visit_count=1),
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="1",
                cod_pdv="100",
                nome="CLIENTE A",
                setor="113",
                revenda="1",
                total_litrinho="5",
                real_litrinho="0",
                gap_litrinho="10",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroClientRecord(
                filial="3",
                cod_pdv="200",
                nome="CLIENTE B",
                setor="401",
                revenda="3",
                total_litrinho="6",
                real_litrinho="0",
                gap_litrinho="12",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        decision = make_decision(allowed=True, roles=("diretor_comercial",), gv_vdes=("dc:1_1", "dc:3_1"))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="giro quinta"),
            decision,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Giro por Dia")
        self.assertIn("GVs com oportunidade: 2", response.text)
        self.assertEqual(response.options[0].description, "1 setor(es) | 1 cliente(s) | Caixas 5 | Faltam 10")
        self.assertEqual(response.options[1].description, "1 setor(es) | 1 cliente(s) | Caixas 6 | Faltam 12")
        self.assertEqual(self.query_service.visit_day_clients_calls[-1]["limit"], 5000)

    def test_build_visit_day_manager_menu_shows_gv_summary_before_sector_detail(self) -> None:
        response = self.flow._build_visit_day_manager_menu(
            "SEG/",
            [
                SimpleNamespace(seller_code="3_400", manager_code="3_4", visit_count=8),
                SimpleNamespace(seller_code="3_401", manager_code="3_4", visit_count=5),
                SimpleNamespace(seller_code="4_500", manager_code="4_5", visit_count=7),
            ],
        )

        self.assertEqual(response.kind, "menu")
        self.assertIn("GVs na rota: 2 | Setores: 3 | Visitas: 20", response.text)
        self.assertIn("Detalhe por setor: escolha o setor.", response.text)
        self.assertEqual(response.options[0].description, "Filial 3 | GV 4 | 8 visita(s)")
        self.assertEqual(response.options[2].description, "Filial 4 | GV 5 | 7 visita(s)")

    def test_build_finance_visit_risk_menu_shows_gv_summary_before_sector_detail(self) -> None:
        response = self.flow._build_finance_visit_risk_menu(
            visit_day_label="Segunda",
            summaries=[
                SimpleNamespace(
                    seller_code="3_400",
                    manager_code="3_4",
                    client_count=2,
                    total_pendente="120,00",
                    planilha_atualizada_em="11/04/2026",
                ),
                SimpleNamespace(
                    seller_code="3_401",
                    manager_code="3_4",
                    client_count=1,
                    total_pendente="30,00",
                    planilha_atualizada_em="11/04/2026",
                ),
                SimpleNamespace(
                    seller_code="4_500",
                    manager_code="4_5",
                    client_count=3,
                    total_pendente="90,00",
                    planilha_atualizada_em="11/04/2026",
                ),
            ],
        )

        self.assertEqual(response.kind, "menu")
        self.assertIn("Detalhe por setor: escolha o setor para ver os clientes com risco.", response.text)
        self.assertEqual(response.options[0].description, "Filial 3 | GV 4 | 2 cliente(s) | R$ 120,00")
        self.assertEqual(response.options[2].description, "Filial 4 | GV 5 | 3 cliente(s) | R$ 90,00")

    def test_handle_natural_giro_do_dia_uses_current_visit_day(self) -> None:
        sender = "5523"
        current_day_label = _current_visit_day_label()
        current_token_map = {
            "segunda": "SEG/",
            "terca": "TER/",
            "quarta": "QUA/",
            "quinta": "QUI/",
            "sexta": "SEX/",
            "sabado": "SAB/",
            "domingo": "DOM/",
        }
        self.query_service.visit_days = ["QUI/", current_token_map[current_day_label]]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=8,
            attention_count=4,
            zero_count=1,
            litrinho_monitored_count=70,
            litrinho_ok_count=30,
            litrinho_nok_count=20,
            litrinho_zero_count=20,
            litrinho_gap_total="40",
            inteira_monitored_count=15,
            inteira_ok_count=6,
            inteira_nok_count=5,
            inteira_zero_count=4,
            inteira_gap_total="9",
            litrao_monitored_count=5,
            litrao_ok_count=1,
            litrao_nok_count=2,
            litrao_zero_count=2,
            litrao_gap_total="4",
            planilha_atualizada_em="11/04/2026",
        )
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="giro do dia"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn(f"Oportunidade de giro em {current_day_label.capitalize()}:", response.text)
        self.assertIn("Clientes com oportunidade de giro:", response.text)
        self.assertEqual(
            self.giro_service.visit_day_summary_calls[-1]["visit_day"],
            current_token_map[current_day_label],
        )
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_route_day_returns_single_message_with_client_giro_summary(self) -> None:
        sender = "5524"
        self.query_service.visit_days = ["SEG/"]
        self.query_service.visit_day_sellers = [
            SimpleNamespace(seller_code="3_400", manager_code="3_4", visit_count=1),
        ]
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="10237",
                razao_social="ESPET DO PAULO LTDA",
                nome_fantasia="ESPET DO PAULO",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="11/04/2026",
            )
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="3",
                cod_pdv="10237",
                nome="ESPET DO PAULO",
                setor="400",
                revenda="3",
                total_litrinho="5",
                real_litrinho="2",
                gap_litrinho="8",
                giro_litrinho="NOK",
                total_inteira="0",
                real_inteira="0",
                gap_inteira="0",
                giro_inteira="-",
                total_litrao="0",
                real_litrao="0",
                gap_litrao="0",
                giro_litrao="-",
                planilha_atualizada_em="11/04/2026",
            )
        ]
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="rota de segunda"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Rota em Segunda", response.text)
        self.assertIn("Setores na rota: 1 | Visitas: 1", response.text)
        self.assertNotIn("Resumo dos GVs:", response.text)
        self.assertNotIn("Giro atualizado em:", response.text)
        self.assertNotIn("Base:", response.text)
        self.assertNotIn("Tipo:", response.text)
        self.assertIn("1. ESPET DO PAULO | Cod 10237 | Setor 400", response.text)

    def test_handle_manager_route_day_multi_gv_opens_gv_then_sector_menu(self) -> None:
        sender = "5525"
        decision = make_decision(allowed=True, roles=("gerente_vendas",), gv_vdes=("3_4", "4_5"))
        self.query_service.visit_days = ["SEG/"]
        self.query_service.visit_day_sellers = [
            SimpleNamespace(seller_code="3_400", manager_code="3_4", visit_count=8),
            SimpleNamespace(seller_code="3_401", manager_code="3_4", visit_count=5),
            SimpleNamespace(seller_code="4_500", manager_code="4_5", visit_count=7),
        ]
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="111",
                razao_social="Cliente Alfa LTDA",
                nome_fantasia="Cliente Alfa",
                telefone="",
                dia_visita="SEG/",
                vendedor="400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-15",
            )
        ]

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="rota segunda"),
            decision,
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Visitas por GV")
        self.assertIn("Escolha o GV para ver os setores da rota.", first.text)
        self.assertNotIn("Resumo dos GVs:", first.text)
        self.assertEqual(first.options[0].description, "2 setor(es) | 13 visita(s)")
        self.assertEqual(first.options[1].description, "1 setor(es) | 7 visita(s)")
        self.assertEqual(self.flow.sessions[sender].step, "visit_select_gv")
        self.assertEqual(self.query_service.visit_day_sellers_calls[-1]["limit"], 1000)

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Visitas por Setor")
        self.assertIn("Filial 3 | GV 4", second.text)
        self.assertNotIn("Resumo dos setores:", second.text)
        self.assertEqual(second.options[0].description, "8 visita(s)")
        self.assertEqual(second.options[1].description, "5 visita(s)")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_visit_seller_selection")

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(third.kind, "text")
        self.assertIn("Clientes de Filial 3 | Setor 400 no dia 'Segunda':", third.text)
        self.assertIn("Filial 3 | GV 4 | 8 visita(s)", third.text)
        self.assertNotIn("Giro atualizado em:", third.text)
        self.assertNotIn("Base:", third.text)
        self.assertNotIn("Tipo:", third.text)
        self.assertIn("1. Cliente Alfa | Cod 111", third.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_routes_financeiro_phrase_to_finance_menu(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="financeiro"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Financeiro")
        self.assertIn("o que voce deseja acompanhar no financeiro?", response.text.lower())

    def test_handle_finance_summary_option_opens_summary_menu_and_returns_total(self) -> None:
        sender = "5511-fin-summary"
        self.query_service.scope_summary = SimpleNamespace(
            client_count=12,
            seller_count=4,
            planilha_atualizada_em="2026-04-15",
        )
        self.inadimplencia_service.finance_summary = SimpleNamespace(
            client_count=5,
            total_pendente="100,00",
            due_in_two_days_count=1,
            due_in_two_days_total="15,00",
            due_tomorrow_count=1,
            due_tomorrow_total="20,00",
            due_today_count=1,
            due_today_total="25,00",
            overdue_count=2,
            overdue_total="40,00",
            planilha_atualizada_em="2026-04-15",
        )
        self.giro_service.scope_summary = SimpleNamespace(
            client_count=12,
            attention_count=5,
            zero_count=2,
            litrinho_monitored_count=40,
            litrinho_ok_count=10,
            litrinho_nok_count=20,
            litrinho_zero_count=10,
            litrinho_gap_total="30",
            inteira_monitored_count=10,
            inteira_ok_count=4,
            inteira_nok_count=4,
            inteira_zero_count=2,
            inteira_gap_total="6",
            litrao_monitored_count=5,
            litrao_ok_count=2,
            litrao_nok_count=2,
            litrao_zero_count=1,
            litrao_gap_total="3",
            planilha_atualizada_em="2026-04-15",
        )
        decision = make_decision(allowed=True, roles=("financeiro",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="financeiro"),
            decision,
        )
        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Financeiro")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )
        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Resumo Financeiro")
        self.assertEqual(self.flow.sessions[sender].step, "finance_select_summary_mode")

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )
        self.assertEqual(third.kind, "text")
        self.assertIn("Resumo Financeiro | Base Total", third.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_finance_summary_documentacao_by_filial_returns_active_client_view(self) -> None:
        sender = "5511-fin-doc-filial"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.documentacao_service.filial_summaries = [
            SimpleNamespace(
                filial="3",
                active_client_count=120,
                scanned_client_count=90,
                ok_client_count=70,
                pending_client_count=20,
                missing_scan_count=30,
                planilha_atualizada_em="2026-04-20",
            ),
            SimpleNamespace(
                filial="4",
                active_client_count=80,
                scanned_client_count=50,
                ok_client_count=40,
                pending_client_count=10,
                missing_scan_count=30,
                planilha_atualizada_em="2026-04-20",
            ),
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="financeiro"), decision)
        second = self.flow.handle(IncomingMessage(sender=sender, text="1"), decision)
        self.assertEqual(second.title, "Resumo Financeiro")

        third = self.flow.handle(IncomingMessage(sender=sender, text="5"), decision)
        self.assertEqual(third.kind, "text")
        self.assertIn("Documentacao Escaneada por Revenda", third.text)
        self.assertIn("Clientes ativos: 200", third.text)
        self.assertIn("Escaneados: 140 | OK: 110 | Pendentes: 30 | Sem escanear: 60", third.text)
        self.assertIn("3 - Patos", third.text)
        self.assertIn("Ativos: 120 | Escaneados: 90", third.text)
        self.assertIn("OK: 70 | Pendentes: 20 | Sem escanear: 30", third.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_finance_menu_giro_with_visit_day_phrase_routes_to_giro_day(self) -> None:
        sender = "5511-fin-giro-dia"
        self.query_service.visit_days = ["SEG/"]
        self.giro_service.visit_day_summary = SimpleNamespace(
            client_count=0,
            attention_count=0,
            zero_count=0,
            litrinho_monitored_count=0,
            litrinho_ok_count=0,
            litrinho_nok_count=0,
            litrinho_zero_count=0,
            litrinho_gap_total="0",
            inteira_monitored_count=0,
            inteira_ok_count=0,
            inteira_nok_count=0,
            inteira_zero_count=0,
            inteira_gap_total="0",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0",
            planilha_atualizada_em="11/04/2026",
        )
        decision = make_decision(allowed=True, roles=("financeiro",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="financeiro"),
            decision,
        )
        self.assertEqual(first.kind, "menu")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="giro segunda"),
            decision,
        )
        self.assertIn("Oportunidade de giro em Segunda:", second.text)
        self.assertNotIn("Nao entendi essa opcao.", second.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_finance_risk_day_menu_shows_only_days_available_in_base(self) -> None:
        sender = "5511-fin-risk-days"
        self.query_service.visit_days = ["SEG/QUI/", "QUA/SEX/"]
        decision = make_decision(allowed=True, roles=("financeiro",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="financeiro"),
            decision,
        )
        self.assertEqual(first.kind, "menu")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="5"),
            decision,
        )
        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Risco da Rota")
        self.assertEqual(
            [option.title for option in second.options],
            ["Segunda", "Quarta", "Quinta", "Sexta"],
        )

    def test_handle_financeiro_de_hoje_requests_clarification(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="financeiro de hoje"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("financeiro de hoje", response.text.lower())
        self.assertEqual(self.flow.sessions["5511"].step, "finance_clarify_today")

    def test_handle_financeiro_de_hoje_clarifies_and_then_selects_due_bucket(self) -> None:
        sender = "5514"
        self.inadimplencia_service.client_summaries_in_scope = [
            InadimplenciaClientSummary(
                filial="2",
                cod_pdv="222",
                nome="Cliente Alfa",
                title_count=1,
                total_pendente="90,00",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="2",
                cod_pdv="222",
                nome="Cliente Alfa",
                data_emissao="2026-04-01",
                data_vencimento="2026-04-09",
                valor_original="90,00",
                valor_pendente="90,00",
                valor_corrigido="90,00",
                dias="8",
                planilha_atualizada_em="2026-04-09",
            )
        ]

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="financeiro de hoje"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(first.kind, "text")
        self.assertIn("quando voce diz 'financeiro de hoje'", first.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "finance_clarify_today")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("*Cliente Alfa*", second.text)
        self.assertIn("- Revenda: 2", second.text)
        self.assertIn("- NB: 222", second.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_giro_por_cpf_opens_document_prompt(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="giro por cpf"),
            make_decision(allowed=True, sectors=("206",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("cpf ou cnpj", response.text.lower())
        self.assertEqual(self.flow.sessions["5511"].step, "awaiting_document")

    def test_handle_giro_por_cpf_clarifies_then_completes_lookup(self) -> None:
        sender = "5516"
        self.query_service.document_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="6643",
                razao_social="Cliente Giro LTDA",
                nome_fantasia="Cliente Giro",
                telefone="",
                dia_visita="",
                vendedor="206",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-09",
            )
        ]
        self.giro_service.search_records = [
            GiroClientRecord(
                filial="3",
                cod_pdv="6643",
                nome="Cliente Giro",
                setor="206",
                revenda="3",
                total_litrinho="10",
                real_litrinho="9",
                gap_litrinho="1",
                giro_litrinho="ok",
                total_inteira="20",
                real_inteira="18",
                gap_inteira="2",
                giro_inteira="ok",
                total_litrao="30",
                real_litrao="28",
                gap_litrao="2",
                giro_litrao="ok",
                planilha_atualizada_em="2026-04-09",
            )
        ]

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="giro por cpf"),
            make_decision(allowed=True, sectors=("206",)),
        )

        self.assertEqual(first.kind, "text")
        self.assertIn("cpf ou cnpj", first.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_document")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="12345678901"),
            make_decision(allowed=True, sectors=("206",)),
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("Encontrei 1 registro(s) de giro para CPF/CNPJ 12345678901.", second.text)
        self.assertIn("*Base:* 60 | *Falta:* 5", second.text)
        self.assertIn("*Tipo:* Litrinho 1, Inteira 2, Litrao 2", second.text)
        self.assertIn("Litrinho: Base 10 | Faltam 1 | Status ok", second.text)
        self.assertIn("Inteira: Base 20 | Faltam 2 | Status ok", second.text)
        self.assertIn("Litrao: Base 30 | Faltam 2 | Status ok", second.text)
        self.assertIsNone(self.query_service.document_calls[0]["allowed_sectors"])
        self.assertIsNone(self.query_service.document_calls[0]["allowed_gv_vdes"])
        self.assertIsNone(self.giro_service.search_calls[0]["allowed_sectors"])
        self.assertIsNone(self.giro_service.search_calls[0]["allowed_gv_vdes"])
        self.assertIn(sender, self.flow.sessions)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

        repeat_prompt = self.flow.handle(
            IncomingMessage(sender=sender, text="SIM"),
            make_decision(allowed=True, sectors=("206",)),
        )

        self.assertIn("CPF ou CNPJ do cliente para consultar o giro", repeat_prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_document")

    def test_cliente_document_search_is_unrestricted_by_commercial_scope(self) -> None:
        sender = "5516-cliente-doc"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_206",))
        self.query_service.document_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="6643",
                razao_social="Cliente Cadastro LTDA",
                nome_fantasia="Cliente Cadastro",
                telefone="",
                dia_visita="",
                vendedor="206",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-09",
            )
        ]

        _ = self.flow.handle(IncomingMessage(sender=sender, text="buscar cliente"), decision)
        prompt = self.flow.handle(IncomingMessage(sender=sender, text="3"), decision)
        response = self.flow.handle(IncomingMessage(sender=sender, text="12345678901"), decision)

        self.assertEqual(prompt.kind, "text")
        self.assertIn("cpf ou cnpj", prompt.text.lower())
        self.assertEqual(response.kind, "text")
        self.assertIn("*Cliente Cadastro*", response.text)
        self.assertIsNone(self.query_service.document_calls[0]["allowed_sectors"])
        self.assertIsNone(self.query_service.document_calls[0]["allowed_gv_vdes"])

    def test_direct_buscar_cliente_por_cnpj_uses_cliente_document_lookup(self) -> None:
        sender = "5516-cliente-cnpj"
        decision = make_decision(allowed=True, roles=("financeiro", "vendedor"), sectors=("3_206",))
        self.query_service.document_records = [
            DClienteRecord(
                filial="3",
                cod_pdv="6643",
                razao_social="Cliente CNPJ LTDA",
                nome_fantasia="Cliente CNPJ",
                telefone="",
                dia_visita="",
                vendedor="206",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-09",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="buscar cliente por cnpj 12345678000199"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("*Cliente CNPJ*", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertEqual(self.query_service.document_calls[0]["document"], "12345678000199")
        self.assertIsNone(self.query_service.document_calls[0]["allowed_sectors"])
        self.assertIsNone(self.query_service.document_calls[0]["allowed_gv_vdes"])
        self.assertEqual(self.giro_service.search_calls, [])

    def test_handle_bare_resumo_with_multiple_roles_opens_clarification_menu(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5517", text="resumo"),
            make_decision(allowed=True, roles=("financeiro", "vendedor"), sectors=("206",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Resumo")
        self.assertIn("qual deles voce quer ver", response.text.lower())
        self.assertEqual(self.flow.sessions["5517"].step, "awaiting_intent_clarification")
        option_titles = {option.title for option in response.options}
        self.assertIn("Resumo Financeiro", option_titles)
        self.assertIn("Resumo da Carteira", option_titles)

    def test_handle_bare_giro_for_finance_clarifies_and_routes_to_client_search(self) -> None:
        sender = "5518"
        decision = make_decision(allowed=True, roles=("financeiro",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="giro"),
            decision,
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Giro")
        self.assertIn("qual caminho voce quer seguir", first.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_intent_clarification")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="giro por cliente"),
            decision,
        )

        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Consultar Giro")
        self.assertIn("como voce quer procurar o giro", second.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_search_mode")

    def test_handle_bare_hoje_for_seller_clarifies_and_routes_to_current_visits(self) -> None:
        sender = "5519"
        current_day_label = _current_visit_day_label().title()
        self.query_service.visit_days = ["Segunda", current_day_label, "Sexta"]
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="6643",
                razao_social="Cliente Hoje LTDA",
                nome_fantasia="Cliente Hoje",
                telefone="",
                dia_visita=current_day_label,
                vendedor="206",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-09",
            )
        ]
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("206",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="hoje"),
            decision,
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Hoje")
        self.assertIn("qual consulta voce quer abrir", first.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_intent_clarification")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("rota em", second.text.lower())
        self.assertIn(current_day_label.lower(), second.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_giro_por_filial_for_finance_routes_to_analytic_giro(self) -> None:
        self.giro_service.filial_summaries = [
            GiroFilialSummary(
                filial="3",
                client_count=12,
                attention_count=2,
                zero_count=1,
                litrinho_monitored_count=8,
                litrinho_ok_count=6,
                litrinho_nok_count=1,
                litrinho_zero_count=1,
                litrinho_gap_total="4,00",
                inteira_monitored_count=7,
                inteira_ok_count=5,
                inteira_nok_count=1,
                inteira_zero_count=1,
                inteira_gap_total="3,00",
                litrao_monitored_count=6,
                litrao_ok_count=4,
                litrao_nok_count=1,
                litrao_zero_count=1,
                litrao_gap_total="2,00",
                planilha_atualizada_em="2026-04-09",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender="5520", text="giro por filial"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Giro por Filial | Base Total", response.text)
        self.assertIn("Patos", response.text)
        self.assertEqual(self.flow.sessions["5520"].step, "awaiting_post_result_navigation")
        self.assertEqual(len(self.giro_service.filial_summary_calls), 1)

    def test_handle_giro_short_request_then_textual_choice_uses_cached_scope_options(self) -> None:
        sender = "5525"
        self.giro_service.filial_summaries = [
            GiroFilialSummary(
                filial="3",
                client_count=12,
                attention_count=2,
                zero_count=1,
                litrinho_monitored_count=8,
                litrinho_ok_count=6,
                litrinho_nok_count=1,
                litrinho_zero_count=1,
                litrinho_gap_total="4,00",
                inteira_monitored_count=7,
                inteira_ok_count=5,
                inteira_nok_count=1,
                inteira_zero_count=1,
                inteira_gap_total="3,00",
                litrao_monitored_count=6,
                litrao_ok_count=4,
                litrao_nok_count=1,
                litrao_zero_count=1,
                litrao_gap_total="2,00",
                planilha_atualizada_em="2026-04-09",
            )
        ]

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="giro"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Giro")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_intent_clarification")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="Giro por Filial da Base"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("Giro por Filial | Base Total", second.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertEqual(len(self.giro_service.filial_summary_calls), 1)

    def test_handle_natural_inadimplencia_name_query_runs_lookup(self) -> None:
        self.inadimplencia_service.name_summaries = [
            InadimplenciaClientSummary(
                filial="1",
                cod_pdv="111",
                nome="Santa Maria Farma",
                title_count=2,
                total_pendente="100,00",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="1",
                cod_pdv="111",
                nome="Santa Maria Farma",
                data_emissao="2026-04-01",
                data_vencimento="2026-04-09",
                valor_original="100,00",
                valor_pendente="100,00",
                valor_corrigido="100,00",
                dias="8",
                planilha_atualizada_em="2026-04-09",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="quero ver a inadimplência da santa maria"),
            make_decision(allowed=True, sectors=("206",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("*Santa Maria Farma*", response.text)
        self.assertIn("- Revenda: 1", response.text)
        self.assertIn("- NB: 111", response.text)
        self.assertEqual(self.flow.sessions["5511"].step, "awaiting_post_result_navigation")
        self.assertEqual(self.inadimplencia_service.name_calls[0]["query_text"], "santa maria")

    def test_handle_inad_registration_query_repeats_same_type_after_sim(self) -> None:
        sender = "5511-inad-repeat"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="3",
                cod_pdv="18008",
                nome="POSTO PAIZAO",
                data_emissao="2026-05-20",
                data_vencimento="2026-06-01",
                valor_original="1530,91",
                valor_pendente="1530,91",
                valor_corrigido="1530,91",
                dias="1",
                planilha_atualizada_em="2026-06-01",
            )
        ]

        result = self.flow.handle(IncomingMessage(sender=sender, text="inad 3 18008"), decision)

        self.assertEqual(result.kind, "text")
        self.assertIn("*POSTO PAIZAO*", result.text)
        self.assertIn("- Revenda: 3", result.text)
        self.assertIn("- NB: 18008", result.text)
        self.assertIn("Quer fazer outra consulta do mesmo tipo? Envie SIM.", result.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

        repeat_prompt = self.flow.handle(IncomingMessage(sender=sender, text="sim"), decision)

        self.assertIn("Informe a revenda/filial para consultar a inadimplencia.", repeat_prompt.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_filial")
        self.assertEqual(self.flow.sessions[sender].search_context, "inadimplencia")

    def test_handle_abbreviated_inad_name_query_runs_lookup(self) -> None:
        self.inadimplencia_service.name_summaries = [
            InadimplenciaClientSummary(
                filial="1",
                cod_pdv="111",
                nome="Santa Maria Farma",
                title_count=2,
                total_pendente="100,00",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="1",
                cod_pdv="111",
                nome="Santa Maria Farma",
                data_emissao="2026-04-01",
                data_vencimento="2026-04-09",
                valor_original="100,00",
                valor_pendente="100,00",
                valor_corrigido="100,00",
                dias="8",
                planilha_atualizada_em="2026-04-09",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender="5512", text="quero ver a inad da santa maria"),
            make_decision(allowed=True, sectors=("206",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("*Santa Maria Farma*", response.text)
        self.assertIn("- Revenda: 1", response.text)
        self.assertIn("- NB: 111", response.text)
        self.assertEqual(self.flow.sessions["5512"].step, "awaiting_post_result_navigation")
        self.assertEqual(self.inadimplencia_service.name_calls[0]["query_text"], "santa maria")

    def test_handle_natural_inad_segunda_routes_to_visit_day_risk(self) -> None:
        sender = "5513"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.query_service.visit_days = ["SEG/", "QUI/"]
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="111",
                razao_social="Cliente Alpha LTDA",
                nome_fantasia="Cliente Alpha",
                telefone="",
                dia_visita="SEG/",
                vendedor="3_400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="120,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-11",
            )
        ]
        self.inadimplencia_service.upcoming_alerts = [
            SimpleNamespace(
                cod_pdv="111",
                nome="Cliente Alpha",
                title_count=2,
                total_pendente="120,00",
                nearest_days_to_due=0,
                planilha_atualizada_em="2026-04-11",
            ),
            SimpleNamespace(
                cod_pdv="222",
                nome="Cliente Beta",
                title_count=1,
                total_pendente="45,00",
                nearest_days_to_due=1,
                planilha_atualizada_em="2026-04-11",
            ),
        ]

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="inad segunda"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Risco da Rota em Segunda", response.text)
        self.assertIn("Visitas na rota: 1", response.text)
        self.assertIn("Clientes com risco: 2 | R$ 165,00", response.text)
        self.assertIn("Vence hoje: 1 cliente(s)", response.text)
        self.assertIn("Vence amanha: 1 cliente(s)", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertEqual(self.query_service.visit_day_clients_calls[-1]["visit_day"], "SEG/")
        self.assertEqual(self.inadimplencia_service.upcoming_calls[-1]["visit_day"], "SEG/")

    def test_handle_seller_inad_menu_visit_day_shortcut_opens_day_flow(self) -> None:
        sender = "5514"
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("3_400",))
        self.query_service.visit_days = ["SEG/", "QUI/"]
        self.inadimplencia_service.upcoming_alerts = [
            SimpleNamespace(
                cod_pdv="111",
                nome="Cliente Alpha",
                title_count=2,
                total_pendente="120,00",
                nearest_days_to_due=-3,
                planilha_atualizada_em="2026-04-11",
            )
        ]

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="inad"),
            decision,
        )

        self.assertEqual(first.kind, "menu")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="4"),
            decision,
        )

        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Inadimplencia por Dia")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_inadimplencia_visit_day_selection")

        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="111",
                razao_social="Cliente Alpha LTDA",
                nome_fantasia="Cliente Alpha",
                telefone="",
                dia_visita="SEG/",
                vendedor="3_400",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="120,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-11",
            )
        ]
        self.query_service.visit_day_sellers = [
            SimpleNamespace(seller_code="3_400", manager_code="3_4", visit_count=1),
        ]

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(third.kind, "text")
        self.assertIn("Risco da Rota em Segunda", third.text)
        self.assertNotIn("Resumo dos GVs:", third.text)
        self.assertIn("Ja inadimplentes: 1 cliente(s)", third.text)

    def test_handle_finance_visit_risk_multi_gv_opens_gv_then_sector_menu(self) -> None:
        sender = "5515"
        decision = make_decision(allowed=True, roles=("financeiro",))
        self.flow.sessions[sender] = LookupSession(
            step="finance_select_visit_risk_day",
            search_context="inadimplencia",
            visit_risk_day_options=("Segunda",),
        )
        risk_calls: list[dict[str, object]] = []

        def list_visit_day_risk_by_seller(**kwargs: object) -> list[SimpleNamespace]:
            risk_calls.append(dict(kwargs))
            return [
                SimpleNamespace(
                    seller_code="3_400",
                    manager_code="3_4",
                    client_count=2,
                    total_pendente="120,00",
                    planilha_atualizada_em="11/04/2026",
                ),
                SimpleNamespace(
                    seller_code="3_401",
                    manager_code="3_4",
                    client_count=1,
                    total_pendente="30,00",
                    planilha_atualizada_em="11/04/2026",
                ),
                SimpleNamespace(
                    seller_code="4_500",
                    manager_code="4_5",
                    client_count=3,
                    total_pendente="90,00",
                    planilha_atualizada_em="11/04/2026",
                ),
            ]

        self.inadimplencia_service.list_visit_day_risk_by_seller = list_visit_day_risk_by_seller
        self.inadimplencia_service.list_visit_day_risk_alerts_by_seller = lambda **kwargs: [
            SimpleNamespace(
                filial="3",
                cod_pdv="111",
                nome="Cliente Alpha",
                seller_code="3_400",
                manager_code="3_4",
                title_count=1,
                total_pendente="120,00",
                nearest_days_to_due=-2,
                planilha_atualizada_em="11/04/2026",
            )
        ]

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Risco da Rota")
        self.assertIn("Escolha o GV para ver os setores com risco.", first.text)
        self.assertNotIn("Resumo dos GVs:", first.text)
        self.assertEqual(first.options[0].description, "2 setor(es) | 3 cliente(s) | R$ 150,00")
        self.assertEqual(first.options[1].description, "1 setor(es) | 3 cliente(s) | R$ 90,00")
        self.assertEqual(self.flow.sessions[sender].step, "finance_select_visit_risk_gv")
        self.assertEqual(risk_calls[-1]["visit_day_token"], "SEG/")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(second.kind, "menu")
        self.assertEqual(second.title, "Risco da Rota")
        self.assertIn("Detalhe por setor: escolha o setor para ver os clientes com risco.", second.text)
        self.assertNotIn("Filial 3 | GV 4", second.text)
        self.assertEqual([option.title for option in second.options], ["Filial 3 | Setor 400", "Filial 3 | Setor 401"])
        self.assertEqual(second.options[0].description, "Filial 3 | GV 4 | 2 cliente(s) | R$ 120,00")
        self.assertEqual(second.options[1].description, "Filial 3 | GV 4 | 1 cliente(s) | R$ 30,00")
        self.assertEqual(self.flow.sessions[sender].step, "finance_select_visit_risk_sector")

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="1"),
            decision,
        )

        self.assertEqual(third.kind, "text")
        self.assertIn("Clientes de Filial 3 | Setor 400 com risco financeiro em Segunda:", third.text)
        self.assertIn("Ja inadimplentes: 1 cliente(s)", third.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_buscar_cliente_then_textual_selection_opens_unique_record(self) -> None:
        sender = "5522"
        self.query_service.fantasia_records = [
            DClienteRecord(
                filial="1",
                cod_pdv="111",
                razao_social="A Ideal LTDA",
                nome_fantasia="A Ideal",
                telefone="83 99999-1111",
                dia_visita="Quinta",
                vendedor="206",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-09",
            )
        ]
        decision = make_decision(allowed=True, roles=("vendedor",), sectors=("206",))

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="buscar cliente"),
            decision,
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_search_mode")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="nome fantasia"),
            decision,
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("Digite parte do nome do cliente", second.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_fantasia")

        third = self.flow.handle(
            IncomingMessage(sender=sender, text="A Ideal"),
            decision,
        )

        self.assertEqual(third.kind, "text")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertIn("*A Ideal*", third.text)
        self.assertIn("NB: 111 | Revenda: 1 | Setor: 206", third.text)
        self.assertEqual(self.query_service.fantasia_calls[0]["query_text"], "A Ideal")

    def test_handle_client_name_with_article_preserves_query(self) -> None:
        self.query_service.fantasia_records = [
            DClienteRecord(
                filial="1",
                cod_pdv="111",
                razao_social="A Ideal LTDA",
                nome_fantasia="A Ideal",
                telefone="",
                dia_visita="",
                vendedor="206",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-09",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="quero ver o cliente da A Ideal"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("206",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("*A Ideal*", response.text)
        self.assertIn("NB: 111 | Revenda: 1 | Setor: 206", response.text)
        self.assertEqual(self.query_service.fantasia_calls[0]["query_text"], "a ideal")

    def test_handle_short_cliente_opens_clarification_menu(self) -> None:
        sender = "5526"

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="cliente"),
            make_decision(allowed=True, roles=("financeiro",), sectors=("206",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Cliente")
        self.assertIn("qual consulta voce quer abrir", response.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_intent_clarification")

    def test_handle_short_lista_reuses_recent_inadimplencia_context(self) -> None:
        sender = "5527"
        self.inadimplencia_service.client_summaries_in_scope = [
            InadimplenciaClientSummary(
                filial="2",
                cod_pdv="222",
                nome="Cliente Lista",
                title_count=1,
                total_pendente="50,00",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="2",
                cod_pdv="222",
                nome="Cliente Lista",
                data_emissao="2026-04-01",
                data_vencimento="2026-04-09",
                valor_original="50,00",
                valor_pendente="50,00",
                valor_corrigido="50,00",
                dias="8",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        self.flow.sessions[sender] = LookupSession(
            step="idle",
            last_intent="finance_summary",
            last_search_context="inadimplencia",
            last_context_updated_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="lista"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("*Cliente Lista*", response.text)
        self.assertIn("- Revenda: 2", response.text)
        self.assertIn("- NB: 222", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_handle_short_base_opens_clarification_menu(self) -> None:
        sender = "5528"

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="base"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Base")
        self.assertIn("qual visao voce quer abrir", response.text.lower())
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_intent_clarification")

    def test_handle_repeated_giro_por_filial_reuses_cached_response(self) -> None:
        self.giro_service.filial_summaries = [
            GiroFilialSummary(
                filial="3",
                client_count=12,
                attention_count=2,
                zero_count=1,
                litrinho_monitored_count=8,
                litrinho_ok_count=6,
                litrinho_nok_count=1,
                litrinho_zero_count=1,
                litrinho_gap_total="4,00",
                inteira_monitored_count=7,
                inteira_ok_count=5,
                inteira_nok_count=1,
                inteira_zero_count=1,
                inteira_gap_total="3,00",
                litrao_monitored_count=6,
                litrao_ok_count=4,
                litrao_nok_count=1,
                litrao_zero_count=1,
                litrao_gap_total="2,00",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        decision = make_decision(allowed=True, roles=("financeiro",))

        first = self.flow.handle(
            IncomingMessage(sender="5529", text="giro por filial"),
            decision,
        )
        second = self.flow.handle(
            IncomingMessage(sender="5530", text="giro por filial"),
            decision,
        )

        self.assertEqual(first.kind, "text")
        self.assertEqual(second.kind, "text")
        self.assertIn("Giro por Filial | Base Total", second.text)
        self.assertEqual(len(self.giro_service.filial_summary_calls), 1)

    def test_handle_giro_por_gv_includes_sector_breakdown_for_finance(self) -> None:
        self.giro_service.gv_summaries = [
            GiroManagementSummary(
                manager_code="3_4",
                client_count=67,
                attention_count=41,
                zero_count=29,
                litrinho_monitored_count=5208,
                litrinho_ok_count=417,
                litrinho_nok_count=1906,
                litrinho_zero_count=2885,
                litrinho_gap_total="4791",
                inteira_monitored_count=1476,
                inteira_ok_count=183,
                inteira_nok_count=498,
                inteira_zero_count=795,
                inteira_gap_total="1293",
                litrao_monitored_count=326,
                litrao_ok_count=16,
                litrao_nok_count=33,
                litrao_zero_count=277,
                litrao_gap_total="310",
                planilha_atualizada_em="11/04/2026",
            )
        ]
        self.giro_service.seller_summaries = [
            GiroSellerSummary(
                seller_code="3_400",
                manager_code="3_4",
                client_count=12,
                attention_count=7,
                zero_count=4,
                litrinho_monitored_count=777,
                litrinho_ok_count=89,
                litrinho_nok_count=301,
                litrinho_zero_count=387,
                litrinho_gap_total="688",
                inteira_monitored_count=219,
                inteira_ok_count=39,
                inteira_nok_count=18,
                inteira_zero_count=162,
                inteira_gap_total="180",
                litrao_monitored_count=14,
                litrao_ok_count=3,
                litrao_nok_count=0,
                litrao_zero_count=11,
                litrao_gap_total="11",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroSellerSummary(
                seller_code="3_401",
                manager_code="3_4",
                client_count=8,
                attention_count=5,
                zero_count=3,
                litrinho_monitored_count=397,
                litrinho_ok_count=77,
                litrinho_nok_count=118,
                litrinho_zero_count=202,
                litrinho_gap_total="320",
                inteira_monitored_count=99,
                inteira_ok_count=14,
                inteira_nok_count=36,
                inteira_zero_count=49,
                inteira_gap_total="85",
                litrao_monitored_count=12,
                litrao_ok_count=0,
                litrao_nok_count=0,
                litrao_zero_count=12,
                litrao_gap_total="12",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        decision = make_decision(allowed=True, roles=("financeiro",))

        response = self.flow.handle(
            IncomingMessage(sender="5530b", text="giro por gv"),
            decision,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Giro por GV | Base Total", response.text)
        self.assertIn("*Filial 3 | GV 4*", response.text)
        self.assertIn("Litrinho: Total 5208 | Caixas OK 417 | % Giro OK 8,0% | Gap 4791 | Giro Zero 2885", response.text)
        self.assertIn("Setores do GV:", response.text)
        self.assertIn(
            "Filial 3 | Setor 400 | Total 1010 | Caixas OK 131 | % Giro OK 13,0% | Gap 879 | Giro Zero 560",
            response.text,
        )
        self.assertIn(
            "Filial 3 | Setor 401 | Total 508 | Caixas OK 91 | % Giro OK 17,9% | Gap 417 | Giro Zero 263",
            response.text,
        )

    def test_director_total_summary_keeps_same_gv_number_from_different_filiais_separate(self) -> None:
        self.query_service.list_scope_summary_by_gv = lambda **kwargs: [
            SimpleNamespace(
                manager_code="1_1",
                client_count=10,
                seller_count=2,
                planilha_atualizada_em="11/04/2026",
            ),
            SimpleNamespace(
                manager_code="2_1",
                client_count=7,
                seller_count=1,
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        self.inadimplencia_service.finance_summaries_by_gv = [
            SimpleNamespace(
                manager_code="1_1",
                client_count=3,
                total_pendente="100,00",
                overdue_count=1,
                overdue_total="40,00",
                due_today_count=1,
                due_today_total="20,00",
                due_tomorrow_count=1,
                due_tomorrow_total="20,00",
                due_in_two_days_count=0,
                due_in_two_days_total="0,00",
                planilha_atualizada_em="11/04/2026",
            ),
            SimpleNamespace(
                manager_code="2_1",
                client_count=2,
                total_pendente="80,00",
                overdue_count=1,
                overdue_total="35,00",
                due_today_count=0,
                due_today_total="0,00",
                due_tomorrow_count=1,
                due_tomorrow_total="25,00",
                due_in_two_days_count=0,
                due_in_two_days_total="0,00",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        self.giro_service.gv_summaries = [
            GiroManagementSummary(
                manager_code="1_1",
                client_count=10,
                attention_count=3,
                zero_count=1,
                litrinho_monitored_count=100,
                litrinho_ok_count=25,
                litrinho_nok_count=60,
                litrinho_zero_count=15,
                litrinho_gap_total="75",
                inteira_monitored_count=30,
                inteira_ok_count=10,
                inteira_nok_count=15,
                inteira_zero_count=5,
                inteira_gap_total="20",
                litrao_monitored_count=10,
                litrao_ok_count=2,
                litrao_nok_count=5,
                litrao_zero_count=3,
                litrao_gap_total="8",
                planilha_atualizada_em="11/04/2026",
            ),
            GiroManagementSummary(
                manager_code="2_1",
                client_count=7,
                attention_count=2,
                zero_count=1,
                litrinho_monitored_count=80,
                litrinho_ok_count=20,
                litrinho_nok_count=50,
                litrinho_zero_count=10,
                litrinho_gap_total="60",
                inteira_monitored_count=20,
                inteira_ok_count=5,
                inteira_nok_count=10,
                inteira_zero_count=5,
                inteira_gap_total="15",
                litrao_monitored_count=5,
                litrao_ok_count=1,
                litrao_nok_count=2,
                litrao_zero_count=2,
                litrao_gap_total="4",
                planilha_atualizada_em="11/04/2026",
            ),
        ]
        decision = make_decision(
            allowed=True,
            roles=("diretor_comercial",),
            gv_vdes=("dc:1_1", "dc:2_1"),
        )

        response = self.flow._build_director_total_summary_response(decision)

        self.assertEqual(response.kind, "text")
        self.assertIn("*GVs na base:* 2", response.text)
        self.assertIn("*Filial 1 | GV 1*", response.text)
        self.assertIn("*Filial 2 | GV 1*", response.text)
        self.assertIn("Base: 10 clientes | 2 setores", response.text)
        self.assertIn("Inadimplentes: 3 | R$ 100,00 | Ja vencidos 1", response.text)
        self.assertIn("Vencimentos: Hoje 1 (R$ 20,00) | Amanha 1 (R$ 20,00) | 2 dias 0 (R$ 0,00)", response.text)
        self.assertIn("Resumo OK:", response.text)
        self.assertNotIn("\n*GV 1*\n", response.text)

    def test_director_visit_risk_gv_menu_is_compact(self) -> None:
        response = self.flow._build_director_visit_risk_gv_menu(
            visit_day_label="Segunda",
            gv_options=["3_4"],
            seller_summaries=[
                SimpleNamespace(
                    manager_code="3_4",
                    seller_code="3_400",
                    client_count=2,
                    total_pendente="120,00",
                    planilha_atualizada_em="11/04/2026",
                ),
                SimpleNamespace(
                    manager_code="3_4",
                    seller_code="3_401",
                    client_count=1,
                    total_pendente="30,00",
                    planilha_atualizada_em="11/04/2026",
                ),
            ],
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Diretoria | Risco da Rota")
        self.assertIn("GVs com risco: 1 | Setores com risco: 2 | Clientes com risco: 3 | R$ 150,00", response.text)
        self.assertEqual(response.options[0].description, "2 setor(es) | 3 cliente(s) | R$ 150,00")

    def test_director_visit_risk_sector_response_is_compact(self) -> None:
        self.inadimplencia_service.list_visit_day_risk_alerts_by_seller = lambda **kwargs: [
            SimpleNamespace(
                filial="3",
                cod_pdv="101",
                nome="Cliente Alfa",
                seller_code="3_400",
                manager_code="3_4",
                title_count=2,
                total_pendente="70,00",
                nearest_days_to_due=-2,
                planilha_atualizada_em="11/04/2026",
            ),
            SimpleNamespace(
                filial="3",
                cod_pdv="102",
                nome="Cliente Beta",
                seller_code="3_400",
                manager_code="3_4",
                title_count=1,
                total_pendente="50,00",
                nearest_days_to_due=0,
                planilha_atualizada_em="11/04/2026",
            ),
        ]

        response = self.flow._build_director_visit_risk_sector_response(
            decision=make_decision(allowed=True, roles=("diretor_comercial",), gv_vdes=("dc:3_1",)),
            summary=SimpleNamespace(
                seller_code="3_400",
                manager_code="3_4",
                client_count=2,
                total_pendente="120,00",
                planilha_atualizada_em="11/04/2026",
            ),
            visit_day_token="SEG/",
            visit_day_label="Segunda",
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Diretoria | Risco da Rota em Segunda", response.text)
        self.assertIn("Filial 3 | GV 4 | Setor 400", response.text)
        self.assertIn("Clientes com risco: 2 | R$ 120,00", response.text)
        self.assertIn("Ja vencidos: 1 cliente(s) | R$ 70,00", response.text)
        self.assertIn("Vence hoje: 1 cliente(s) | R$ 50,00", response.text)

    def test_director_cobranca_client_menu_is_compact(self) -> None:
        response = self.flow._build_inadimplencia_client_menu(
            query_text="Esses sao os maiores devedores da sua diretoria.",
            summaries=[
                InadimplenciaClientSummary(
                    filial="3",
                    cod_pdv="10237",
                    nome="ESPET DO PAULO",
                    title_count=2,
                    total_pendente="150,00",
                    planilha_atualizada_em="11/04/2026",
                ),
                InadimplenciaClientSummary(
                    filial="3",
                    cod_pdv="10428",
                    nome="HASHI MIX",
                    title_count=1,
                    total_pendente="80,00",
                    planilha_atualizada_em="11/04/2026",
                ),
            ],
            total_available=2,
            list_context=INADIMPLENCIA_CONTEXT_DIRECTOR_TOP_DEBTORS,
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Diretoria | Cobranca")
        self.assertIn("Clientes na lista: 2", response.text)
        self.assertEqual(response.options[0].description, "NB 10237 | Revenda 3 | 2 titulo(s) | R$ 150,00")

    def test_director_cobranca_detail_is_compact(self) -> None:
        response = self.flow._build_inadimplencia_response(
            [
                InadimplenciaRecord(
                    filial="3",
                    cod_pdv="10237",
                    nome="ESPET DO PAULO",
                    data_emissao="2026-04-01",
                    data_vencimento="2026-04-09",
                    valor_original="80,00",
                    valor_pendente="80,00",
                    valor_corrigido="85,00",
                    dias="-8",
                    planilha_atualizada_em="11/04/2026",
                    nota_fiscal="158043",
                ),
                InadimplenciaRecord(
                    filial="3",
                    cod_pdv="10237",
                    nome="ESPET DO PAULO",
                    data_emissao="2026-04-02",
                    data_vencimento="2026-04-10",
                    valor_original="65,00",
                    valor_pendente="65,00",
                    valor_corrigido="70,00",
                    dias="-7",
                    planilha_atualizada_em="11/04/2026",
                ),
            ],
            "cliente ESPET DO PAULO | revenda 3 | NB 10237",
            compact=True,
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Diretoria | Cobranca", response.text)
        self.assertIn("*ESPET DO PAULO*", response.text)
        self.assertIn("- Revenda: 3", response.text)
        self.assertIn("- NB: 10237", response.text)
        self.assertIn("- Titulos: 2", response.text)
        self.assertIn("- Total pendente: R$ 145,00", response.text)
        self.assertIn("- Total atrasado: R$ 155,00", response.text)
        self.assertIn("- Maior atraso: 8 dias", response.text)
        self.assertIn("1) Vencido ha 8 dias", response.text)
        self.assertIn("- NF: 158043", response.text)
        self.assertIn("- Vencimento: 09/04/2026", response.text)
        self.assertIn("2) Vencido ha 7 dias", response.text)
        self.assertIn("- Vencimento: 10/04/2026", response.text)
        self.assertIn("- Valor: R$ 85,00", response.text)
        self.assertIn("- Valor: R$ 70,00", response.text)

    def test_handle_inadimplentes_da_base_then_textual_selection_opens_unique_client(self) -> None:
        sender = "5523"
        self.inadimplencia_service.client_summaries_in_scope = [
            InadimplenciaClientSummary(
                filial="1",
                cod_pdv="111",
                nome="Cliente Alfa",
                title_count=2,
                total_pendente="100,00",
                planilha_atualizada_em="2026-04-09",
            ),
            InadimplenciaClientSummary(
                filial="2",
                cod_pdv="222",
                nome="Cliente Beta",
                title_count=1,
                total_pendente="80,00",
                planilha_atualizada_em="2026-04-09",
            ),
        ]
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="2",
                cod_pdv="222",
                nome="Cliente Beta",
                data_emissao="2026-04-01",
                data_vencimento="2026-04-09",
                valor_original="80,00",
                valor_pendente="80,00",
                valor_corrigido="80,00",
                dias="8",
                planilha_atualizada_em="2026-04-09",
            )
        ]

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="inadimplentes da base"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_inadimplencia_client_selection")

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="Cliente Beta"),
            make_decision(allowed=True, roles=("financeiro",)),
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("*Cliente Beta*", second.text)
        self.assertIn("- Revenda: 2", second.text)
        self.assertIn("- NB: 222", second.text)
        self.assertEqual(len(self.inadimplencia_service.client_summaries_in_scope_calls), 1)
        self.assertEqual(len(self.inadimplencia_service.search_calls), 1)

    def test_handle_visitas_de_hoje_uses_current_day_reference(self) -> None:
        current_day_label = _current_visit_day_label().title()
        self.query_service.visit_days = ["Segunda", current_day_label, "Sexta"]
        self.query_service.visit_day_clients = [
            DClienteRecord(
                filial="3",
                cod_pdv="6643",
                razao_social="Cliente Quinta",
                nome_fantasia="Cliente Quinta",
                telefone="",
                dia_visita=current_day_label,
                vendedor="206",
                status="ativo",
                cidade="Patos",
                cond_pag_atual="A vista",
                limite_credito="1000",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="2026-04-09",
            )
        ]

        response = self.flow.handle(
            IncomingMessage(sender="5511", text="visitas de hoje"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("206",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("Se quiser voltar, envie A ou ANT.", response.text)
        self.assertEqual(len(self.query_service.visit_days_calls), 1)
        self.assertEqual(len(self.query_service.visit_day_clients_calls), 1)

    def test_handle_resumo_short_request_then_textual_choice_uses_cached_summary_options(self) -> None:
        sender = "5524"
        self.query_service.scope_summary = SimpleNamespace(
            client_count=12,
            seller_count=3,
            planilha_atualizada_em="2026-04-09",
        )
        self.inadimplencia_service.finance_summary = SimpleNamespace(
            client_count=5,
            total_pendente="100,00",
            due_in_two_days_count=1,
            due_in_two_days_total="10,00",
            due_tomorrow_count=1,
            due_tomorrow_total="20,00",
            due_today_count=1,
            due_today_total="30,00",
            overdue_count=2,
            overdue_total="40,00",
            planilha_atualizada_em="2026-04-09",
        )
        self.inadimplencia_service.finance_summaries_by_filial = [
            SimpleNamespace(
                filial="1",
                client_count=2,
                total_pendente="50,00",
                due_in_two_days_count=0,
                due_in_two_days_total="0,00",
                due_tomorrow_count=1,
                due_tomorrow_total="10,00",
                due_today_count=0,
                due_today_total="0,00",
                overdue_count=1,
                overdue_total="40,00",
            )
        ]
        self.giro_service.scope_summary = SimpleNamespace(
            client_count=18,
            attention_count=2,
            zero_count=1,
            litrinho_monitored_count=10,
            litrinho_ok_count=7,
            litrinho_nok_count=2,
            litrinho_zero_count=1,
            litrinho_gap_total="4,00",
            inteira_monitored_count=9,
            inteira_ok_count=6,
            inteira_nok_count=2,
            inteira_zero_count=1,
            inteira_gap_total="3,00",
            litrao_monitored_count=8,
            litrao_ok_count=5,
            litrao_nok_count=2,
            litrao_zero_count=1,
            litrao_gap_total="2,00",
            planilha_atualizada_em="2026-04-09",
        )

        first = self.flow.handle(
            IncomingMessage(sender=sender, text="resumo"),
            make_decision(allowed=True, roles=("financeiro", "vendedor"), sectors=("206",)),
        )

        self.assertEqual(first.kind, "menu")
        self.assertEqual(first.title, "Resumo")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_intent_clarification")
        self.assertGreaterEqual(len(first.options), 2)

        second = self.flow.handle(
            IncomingMessage(sender=sender, text="Resumo Financeiro"),
            make_decision(allowed=True, roles=("financeiro", "vendedor"), sectors=("206",)),
        )

        self.assertEqual(second.kind, "text")
        self.assertIn("Resumo Financeiro | Base Total", second.text)
        self.assertIn("*Clientes na base:* 12", second.text)
        self.assertIn("*Clientes inadimplentes:* 5", second.text)
        self.assertIn("*Valor total pendente:* R$ 100,00", second.text)
        self.assertIn("*Ja vencidos:* 2 cliente(s) | R$ 40,00", second.text)
        self.assertIn("Atualizado em:", second.text)
        self.assertIn("Clientes: 2026-04-09", second.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")
        self.assertEqual(len(self.query_service.scope_summary_calls), 1)
        self.assertEqual(len(self.inadimplencia_service.finance_summary_calls), 1)
        self.assertEqual(len(self.inadimplencia_service.finance_summary_by_filial_calls), 0)
        self.assertEqual(len(self.giro_service.scope_summary_calls), 1)

    def test_handle_unknown_text_falls_back_to_main_menu(self) -> None:
        response = self.flow.handle(
            IncomingMessage(sender="5511", text="quero ver o status da fazenda"),
            make_decision(allowed=True),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Consultas")
        self.assertIn("Nao entendi essa opcao.", response.text)
        self.assertGreater(len(response.options), 0)

    def test_invalid_inadimplencia_selection_reprompts_the_same_menu(self) -> None:
        sender = "5511"
        self.flow.sessions[sender] = LookupSession(
            step="awaiting_inadimplencia_client_selection",
            search_context="inadimplencia",
            fantasia_query="base da regiao",
            inadimplencia_client_summaries=(
                InadimplenciaClientSummary(
                    filial="1",
                    cod_pdv="111",
                    nome="Cliente Alfa",
                    title_count=2,
                    total_pendente="100,00",
                    planilha_atualizada_em="2026-04-09",
                ),
                InadimplenciaClientSummary(
                    filial="2",
                    cod_pdv="222",
                    nome="Cliente Beta",
                    title_count=3,
                    total_pendente="200,00",
                    planilha_atualizada_em="2026-04-09",
                ),
            ),
            inadimplencia_total_available=2,
            inadimplencia_page=1,
            inadimplencia_page_size=20,
            updated_at=datetime.now(timezone.utc),
        )

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="qualquer coisa"),
            make_decision(allowed=True, sectors=("1",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertIn("Nao entendi essa opcao.", response.text)
        self.assertIn("Escolha o cliente certo para ver os titulos pendentes.", response.text)
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_inadimplencia_client_selection")

    def test_numeric_inadimplencia_selection_routes_to_selected_client(self) -> None:
        sender = "5511"
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="2",
                cod_pdv="222",
                nome="Cliente Beta",
                data_emissao="2026-04-01",
                data_vencimento="2026-04-09",
                valor_original="200,00",
                valor_pendente="200,00",
                valor_corrigido="200,00",
                dias="8",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        self.flow.sessions[sender] = LookupSession(
            step="awaiting_inadimplencia_client_selection",
            search_context="inadimplencia",
            fantasia_query="base da regiao",
            inadimplencia_client_summaries=(
                InadimplenciaClientSummary(
                    filial="1",
                    cod_pdv="111",
                    nome="Cliente Alfa",
                    title_count=2,
                    total_pendente="100,00",
                    planilha_atualizada_em="2026-04-09",
                ),
                InadimplenciaClientSummary(
                    filial="2",
                    cod_pdv="222",
                    nome="Cliente Beta",
                    title_count=3,
                    total_pendente="200,00",
                    planilha_atualizada_em="2026-04-09",
                ),
            ),
            inadimplencia_total_available=2,
            inadimplencia_page=1,
            inadimplencia_page_size=20,
            updated_at=datetime.now(timezone.utc),
        )

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="2"),
            make_decision(allowed=True, sectors=("1",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("*Cliente Beta*", response.text)
        self.assertIn("- Revenda: 2", response.text)
        self.assertIn("- NB: 222", response.text)
        self.assertEqual(len(self.inadimplencia_service.search_calls), 1)
        self.assertEqual(self.inadimplencia_service.search_calls[0]["filial"], "2")
        self.assertEqual(self.inadimplencia_service.search_calls[0]["cod_pdv"], "222")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_post_result_navigation")

    def test_textual_inadimplencia_selection_routes_to_selected_client(self) -> None:
        sender = "5512"
        self.inadimplencia_service.search_records = [
            InadimplenciaRecord(
                filial="1",
                cod_pdv="111",
                nome="Cliente Alfa",
                data_emissao="2026-04-01",
                data_vencimento="2026-04-09",
                valor_original="100,00",
                valor_pendente="100,00",
                valor_corrigido="100,00",
                dias="8",
                planilha_atualizada_em="2026-04-09",
            )
        ]
        self.flow.sessions[sender] = LookupSession(
            step="awaiting_inadimplencia_client_selection",
            search_context="inadimplencia",
            fantasia_query="cliente alfa",
            inadimplencia_client_summaries=(
                InadimplenciaClientSummary(
                    filial="1",
                    cod_pdv="111",
                    nome="Cliente Alfa",
                    title_count=2,
                    total_pendente="100,00",
                    planilha_atualizada_em="2026-04-09",
                ),
                InadimplenciaClientSummary(
                    filial="2",
                    cod_pdv="222",
                    nome="Cliente Beta",
                    title_count=3,
                    total_pendente="200,00",
                    planilha_atualizada_em="2026-04-09",
                ),
            ),
            updated_at=datetime.now(timezone.utc),
        )

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="Cliente Alfa"),
            make_decision(allowed=True, sectors=("1",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("*Cliente Alfa*", response.text)
        self.assertIn("- Revenda: 1", response.text)
        self.assertIn("- NB: 111", response.text)
        self.assertEqual(self.inadimplencia_service.search_calls[-1]["cod_pdv"], "111")

    def test_expired_session_prompts_for_context_again(self) -> None:
        sender = "5599"
        self.flow.sessions[sender] = LookupSession(
            step="awaiting_document",
            search_context="giro",
            updated_at=datetime.now(timezone.utc).replace(year=2025),
        )

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="cpf"),
            make_decision(allowed=True, roles=("vendedor",), sectors=("206",)),
        )

        self.assertEqual(response.kind, "text")
        self.assertIn("perdi o contexto", response.text.lower())
        self.assertNotIn(sender, self.flow.sessions)

    def test_paginated_inadimplencia_uses_a_as_back_and_anterior_as_page_nav(self) -> None:
        sender = "5513"
        self.flow.sessions[sender] = LookupSession(
            step="awaiting_inadimplencia_client_selection",
            search_context="inadimplencia",
            fantasia_query="base",
            inadimplencia_client_summaries=(
                InadimplenciaClientSummary(
                    filial="1",
                    cod_pdv="111",
                    nome="Cliente Alfa",
                    title_count=2,
                    total_pendente="100,00",
                    planilha_atualizada_em="2026-04-09",
                ),
            ),
            inadimplencia_total_available=50,
            inadimplencia_list_context=INADIMPLENCIA_CONTEXT_SCOPE_BASE,
            inadimplencia_page=2,
            inadimplencia_page_size=20,
            updated_at=datetime.now(timezone.utc),
        )

        response = self.flow.handle(
            IncomingMessage(sender=sender, text="A"),
            make_decision(allowed=True, sectors=("206",), roles=("vendedor",)),
        )

        self.assertEqual(response.kind, "menu")
        self.assertEqual(response.title, "Cobranca da Carteira")
        self.assertEqual(self.flow.sessions[sender].step, "awaiting_search_mode")


if __name__ == "__main__":
    unittest.main()
