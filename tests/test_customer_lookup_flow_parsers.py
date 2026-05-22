from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.models import InteractiveOption
from bot_api.services.customer_lookup_flow import (
    DClienteRecord,
    _detect_explicit_search_context,
    _extract_requested_visit_day_label,
    _format_quantity,
    _looks_like_base_short_request,
    _looks_like_client_short_request,
    _looks_like_contextual_follow_up,
    _looks_like_giro_short_request,
    _looks_like_list_short_request,
    _looks_like_summary_short_request,
    _looks_like_today_short_request,
    _normalize_choice,
    _parse_direct_registration_lookup,
    _parse_director_summary_action,
    _parse_finance_action,
    _parse_finance_summary_mode,
    _parse_finance_today_clarification,
    _parse_hybrid_finance_request,
    _parse_hybrid_search_request,
    _parse_inadimplencia_page_action,
    _parse_manager_summary_action,
    _select_fantasia_record,
    _select_interactive_option,
    _select_visit_day,
    _sum_formatted_amounts,
)


class CustomerLookupFlowParserTests(unittest.TestCase):
    def test_normalize_choice_removes_accents_and_collapses_spaces(self) -> None:
        self.assertEqual(_normalize_choice("  Inadimplência   de   Hoje "), "inadimplencia de hoje")

    def test_format_quantity_accepts_dot_and_comma_decimal_without_scaling(self) -> None:
        self.assertEqual(_format_quantity("10,00"), "10")
        self.assertEqual(_format_quantity("10.00"), "10")
        self.assertEqual(_sum_formatted_amounts("10,00", "2.50"), "12.5")

    def test_finance_parser_understands_natural_phrases(self) -> None:
        cases = {
            "resumo financeiro": "summary",
            "visitas com risco hoje": "visit_risk",
            "risco da rota": "visit_risk",
            "cobranca da base": "list",
            "submenu giro": "giro",
            "vencimentos proximos": "upcoming",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_parse_finance_action(_normalize_choice(text)), expected)

    def test_hybrid_finance_request_supports_giro_with_visit_day_inside_finance_menu(self) -> None:
        request = _parse_hybrid_finance_request(_normalize_choice("giro terca"))
        self.assertEqual(request.action, "giro")
        self.assertEqual(request.visit_day_label, "Terca")

    def test_hybrid_finance_request_marks_financeiro_de_hoje_as_clarification(self) -> None:
        request = _parse_hybrid_finance_request(_normalize_choice("quero ver o financeiro de hoje"))
        self.assertTrue(request.clarify_today)
        self.assertEqual(request.due_bucket, "today")

    def test_finance_today_clarification_accepts_short_follow_up_answers(self) -> None:
        self.assertEqual(_parse_finance_today_clarification("1"), "upcoming")
        self.assertEqual(_parse_finance_today_clarification("3"), "summary")
        self.assertEqual(
            _parse_finance_today_clarification(_normalize_choice("visitas com risco hoje")),
            "visit_risk",
        )

    def test_finance_summary_mode_parser_understands_documentacao_por_filial(self) -> None:
        self.assertEqual(_parse_finance_summary_mode("5"), "documentacao_by_filial")
        self.assertEqual(
            _parse_finance_summary_mode(_normalize_choice("documentacao escaneada por revenda")),
            "documentacao_by_filial",
        )

    def test_manager_summary_parser_follows_new_operational_order(self) -> None:
        self.assertEqual(_parse_manager_summary_action("1"), "visit_risk")
        self.assertEqual(_parse_manager_summary_action("2"), "upcoming")
        self.assertEqual(_parse_manager_summary_action("3"), "list")
        self.assertEqual(_parse_manager_summary_action("4"), "by_seller")
        self.assertEqual(_parse_manager_summary_action("5"), "by_filial")
        self.assertEqual(_parse_manager_summary_action("6"), "giro")
        self.assertEqual(_parse_manager_summary_action("7"), "total")
        self.assertEqual(_parse_manager_summary_action(_normalize_choice("cobranca")), "list")
        self.assertEqual(_parse_manager_summary_action(_normalize_choice("cobranca consolidada")), "list")
        self.assertEqual(_parse_manager_summary_action(_normalize_choice("giro consolidado")), "giro")
        self.assertEqual(_parse_manager_summary_action(_normalize_choice("equipe")), "by_seller")
        self.assertEqual(_parse_manager_summary_action(_normalize_choice("filiais")), "by_filial")

    def test_director_summary_parser_follows_new_operational_order(self) -> None:
        self.assertEqual(_parse_director_summary_action("1"), "visit_risk")
        self.assertEqual(_parse_director_summary_action("2"), "top_debtors")
        self.assertEqual(_parse_director_summary_action("3"), "by_revenda")
        self.assertEqual(_parse_director_summary_action("4"), "by_filial")
        self.assertEqual(_parse_director_summary_action("5"), "giro")
        self.assertEqual(_parse_director_summary_action("6"), "ranking")
        self.assertEqual(_parse_director_summary_action("7"), "total")
        self.assertEqual(_parse_director_summary_action(_normalize_choice("diretoria")), "total")
        self.assertEqual(_parse_director_summary_action(_normalize_choice("cobranca")), "top_debtors")
        self.assertEqual(_parse_director_summary_action(_normalize_choice("gvs")), "by_revenda")
        self.assertEqual(_parse_director_summary_action(_normalize_choice("filiais")), "by_filial")

    def test_hybrid_search_request_extracts_name_query_from_phrase(self) -> None:
        request = _parse_hybrid_search_request(
            text="quero ver a inadimplência da santa maria",
            normalized_text=_normalize_choice("quero ver a inadimplência da santa maria"),
            search_context="inadimplencia",
            allow_contextless_query=False,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.search_mode, "fantasia")
        self.assertEqual(request.query_text, "santa maria")

    def test_hybrid_search_request_preserves_leading_article_in_client_name(self) -> None:
        request = _parse_hybrid_search_request(
            text="quero ver o cliente da A Ideal",
            normalized_text=_normalize_choice("quero ver o cliente da A Ideal"),
            search_context="cliente",
            allow_contextless_query=False,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.query_text, "a ideal")

    def test_explicit_search_context_detects_giro_and_inadimplencia(self) -> None:
        self.assertEqual(_detect_explicit_search_context(_normalize_choice("consultar giro por cpf")), "giro")
        self.assertEqual(_detect_explicit_search_context(_normalize_choice("ver inadimplência da base")), "inadimplencia")
        self.assertEqual(_detect_explicit_search_context(_normalize_choice("inad")), "inadimplencia")

    def test_hybrid_search_request_understands_abbreviated_inad_phrase(self) -> None:
        request = _parse_hybrid_search_request(
            text="quero ver a inad da santa maria",
            normalized_text=_normalize_choice("quero ver a inad da santa maria"),
            search_context="inadimplencia",
            allow_contextless_query=False,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.search_mode, "fantasia")
        self.assertEqual(request.query_text, "santa maria")

    def test_hybrid_search_request_routes_inad_segunda_to_visit_day(self) -> None:
        request = _parse_hybrid_search_request(
            text="inad segunda",
            normalized_text=_normalize_choice("inad segunda"),
            search_context="inadimplencia",
            allow_contextless_query=False,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.visit_day_label, "Segunda")
        self.assertEqual(request.query_text, "")

    def test_hybrid_search_request_keeps_inad_name_when_weekday_is_part_of_name(self) -> None:
        request = _parse_hybrid_search_request(
            text="inad segunda chance",
            normalized_text=_normalize_choice("inad segunda chance"),
            search_context="inadimplencia",
            allow_contextless_query=False,
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.search_mode, "fantasia")
        self.assertEqual(request.query_text, "segunda chance")

    def test_short_contextual_follow_up_tokens_are_marked_as_follow_up(self) -> None:
        self.assertTrue(_looks_like_contextual_follow_up("cpf"))
        self.assertTrue(_looks_like_contextual_follow_up("hoje"))
        self.assertTrue(_looks_like_contextual_follow_up("1"))

    def test_low_confidence_detectors_mark_short_summary_today_and_giro_requests(self) -> None:
        self.assertTrue(_looks_like_summary_short_request(_normalize_choice("meu resumo")))
        self.assertTrue(_looks_like_today_short_request(_normalize_choice("hoje")))
        self.assertTrue(_looks_like_giro_short_request(_normalize_choice("resumo de giro")))
        self.assertFalse(_looks_like_giro_short_request(_normalize_choice("giro por cpf")))

    def test_low_confidence_detectors_mark_short_list_base_and_client_requests(self) -> None:
        self.assertTrue(_looks_like_list_short_request(_normalize_choice("lista")))
        self.assertTrue(_looks_like_base_short_request(_normalize_choice("base")))
        self.assertTrue(_looks_like_client_short_request(_normalize_choice("cliente")))
        self.assertTrue(_looks_like_client_short_request(_normalize_choice("esse cliente")))
        self.assertFalse(_looks_like_list_short_request(_normalize_choice("lista de inadimplentes")))
        self.assertFalse(_looks_like_base_short_request(_normalize_choice("giro da base")))
        self.assertFalse(_looks_like_client_short_request(_normalize_choice("buscar cliente")))

    def test_extract_requested_visit_day_label_understands_hoje(self) -> None:
        label = _extract_requested_visit_day_label(_normalize_choice("visitas de hoje"))
        self.assertTrue(label)

    def test_extract_requested_visit_day_label_understands_inad_do_dia(self) -> None:
        label = _extract_requested_visit_day_label(_normalize_choice("inad do dia"))
        self.assertTrue(label)

    def test_direct_registration_lookup_handles_plain_and_labeled_forms(self) -> None:
        self.assertEqual(_parse_direct_registration_lookup("3 6643"), ("3", "6643"))
        self.assertEqual(_parse_direct_registration_lookup("revenda 03 nb 06643"), ("3", "6643"))

    def test_visit_day_selector_accepts_label_or_number(self) -> None:
        visit_days = ("Segunda", "Quinta", "Sexta")
        self.assertEqual(_select_visit_day("quinta", "quinta", visit_days), "Quinta")
        self.assertEqual(_select_visit_day("2", "2", visit_days), "Quinta")

    def test_fantasia_selector_uses_numeric_disambiguation(self) -> None:
        records = (
            DClienteRecord(
                filial="1",
                cod_pdv="111",
                razao_social="Alpha LTDA",
                nome_fantasia="Alpha",
                telefone="",
                dia_visita="",
                vendedor="",
                status="",
                cidade="",
                cond_pag_atual="",
                limite_credito="",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="",
            ),
            DClienteRecord(
                filial="2",
                cod_pdv="222",
                razao_social="Beta LTDA",
                nome_fantasia="Beta",
                telefone="",
                dia_visita="",
                vendedor="",
                status="",
                cidade="",
                cond_pag_atual="",
                limite_credito="",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela="",
            ),
        )
        self.assertEqual(_select_fantasia_record("2", "2", records), records[1])
        self.assertEqual(_select_fantasia_record("Beta", "beta", records), records[1])

    def test_interactive_option_selector_uses_unique_text_match(self) -> None:
        options = (
            InteractiveOption(
                option_id="finance_total",
                title="Giro Total da Base",
                description="Ver o consolidado da base total",
            ),
            InteractiveOption(
                option_id="finance_filial",
                title="Giro por Filial da Base",
                description="Separar o giro por revenda",
            ),
        )

        selected = _select_interactive_option("filial", "filial", options)

        self.assertIs(selected, options[1])

    def test_inadimplencia_page_action_understands_navigation_shortcuts(self) -> None:
        self.assertEqual(_parse_inadimplencia_page_action("a"), "")
        self.assertEqual(_parse_inadimplencia_page_action("anterior"), "prev")
        self.assertEqual(_parse_inadimplencia_page_action("prox"), "next")


if __name__ == "__main__":
    unittest.main()
