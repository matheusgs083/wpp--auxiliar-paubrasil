from __future__ import annotations

import unittest

from bot_api.services.admin_usage_service import (
    EVOLUTION_USAGE_FEATURE_LABELS,
    _infer_evolution_usage_feature,
)


class AdminUsageServiceTests(unittest.TestCase):
    def test_infers_boleto_feature_from_command_text(self) -> None:
        feature, detail = _infer_evolution_usage_feature(
            incoming_text="boleto 4 11305",
            requested_area="",
            session_before={"step": "idle"},
            session_after={"step": "idle"},
        )

        self.assertEqual(feature, "boleto")
        self.assertIn("boleto", EVOLUTION_USAGE_FEATURE_LABELS)
        self.assertEqual(EVOLUTION_USAGE_FEATURE_LABELS["boleto"], "Boletos")
        self.assertIn("etapa=idle", detail)

    def test_infers_boleto_feature_from_selection_step(self) -> None:
        feature, detail = _infer_evolution_usage_feature(
            incoming_text="1",
            requested_area="",
            session_before={"step": "awaiting_boleto_selection"},
            session_after={"step": "idle"},
        )

        self.assertEqual(feature, "boleto")
        self.assertIn("etapa=idle", detail)

    def test_infers_granular_features_from_text_commands(self) -> None:
        cases = {
            "menu": "menu_principal",
            "rota do dia": "rota_dia",
            "risco da rota": "risco_rota",
            "vence amanha": "cobranca_vence_amanha",
            "vence em 2 dias": "cobranca_vence_2_dias",
            "giro zero": "giro_zero",
            "giro segunda": "giro_dia",
            "documentacao segunda": "documentacao_dia",
            "estoque 3 13203": "estoque",
            "armazem 3 13203": "estoque",
            "critica pdf setor 401": "critica_pdf_setor",
            "critica pdf gv": "critica_pdf_gv",
            "critica nb pdf 3 18008": "critica_nb_pdf",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                feature, _detail = _infer_evolution_usage_feature(
                    incoming_text=text,
                    requested_area="",
                    session_before={"step": "idle"},
                    session_after={"step": "idle"},
                )
                self.assertEqual(feature, expected)
                self.assertIn(expected, EVOLUTION_USAGE_FEATURE_LABELS)

    def test_infers_granular_features_from_flow_intents(self) -> None:
        cases = {
            "search_cliente": "cliente_busca",
            "inadimplencia_client": "cobranca_cliente",
            "inadimplencia_visit_day": "cobranca_rota_dia",
            "inadimplencia_list": "cobranca_inadimplentes",
            "giro_visit_day": "giro_dia",
            "giro_zero_base": "giro_zero",
            "documentacao_visit_day": "documentacao_dia",
            "comodato_client": "comodato_cliente",
            "finance_giro_by_gv": "giro_resumo",
            "seller_summary": "carteira",
        }
        for intent, expected in cases.items():
            with self.subTest(intent=intent):
                feature, detail = _infer_evolution_usage_feature(
                    incoming_text="1",
                    requested_area="",
                    session_before={"step": "idle"},
                    session_after={"step": "idle", "last_intent": intent},
                )
                self.assertEqual(feature, expected)
                self.assertIn(f"intent={intent}", detail)


if __name__ == "__main__":
    unittest.main()
