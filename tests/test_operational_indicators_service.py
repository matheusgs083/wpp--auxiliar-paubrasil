from __future__ import annotations

import tempfile
import unittest

from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore
from bot_api.services.operational_indicators_service import BI_INDICATORS_ROUTINE, OperationalIndicatorsService


class OperationalIndicatorsServiceTests(unittest.TestCase):
    def test_reads_bi_metrics_and_separates_operations_by_puxada(self) -> None:
        csv_data = (
            "Ano;Mês;Puxada;Nome Revenda;Base;Valor Mes\n"
            "2026;09;00747530;Patos;0649;87,5\n"
            "2026;09;00747530;Patos;0652;123,4\n"
            "2026;09;00747548;Sumé;0649;91,2\n"
            "2026;09;00747548;Sumé;0652;101,0\n"
        ).encode("cp1252")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LigaEntregaReportStore(temp_dir)
            store.store_batch(routine=BI_INDICATORS_ROUTINE, files={"PATOS_SET.csv": csv_data}, reference_date="2026-09-30")
            result = OperationalIndicatorsService(report_store=store).build_dashboard(competencia="2026-09")
        self.assertEqual(result["competencia"], "2026-09")
        self.assertEqual([item["puxada"] for item in result["branches"]], ["00747530", "00747548"])
        self.assertEqual(result["branches"][0]["filial"], "Patos")
        self.assertEqual(result["branches"][1]["metrics"]["ocupacao"], 91.2)

    def test_selects_latest_competence_from_multi_month_batch_and_warns_missing_metric(self) -> None:
        csv_data = (
            "Ano;Mês;Puxada;Nome Revenda;Base;Valor Mes\n"
            "2026;08;00747530;Patos;0649;80,0\n"
            "2026;09;00747530;Patos;0649;87,5\n"
            "2026;09;00747530;Patos;0652;\n"
        ).encode("cp1252")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LigaEntregaReportStore(temp_dir)
            store.store_batch(routine=BI_INDICATORS_ROUTINE, files={"BI.csv": csv_data}, reference_date="2026-09-30")
            result = OperationalIndicatorsService(report_store=store).build_dashboard()
        self.assertEqual(result["competencia"], "2026-09")
        self.assertEqual(result["branches"][0]["metrics"]["ocupacao"], 87.5)
        self.assertIsNone(result["branches"][0]["metrics"]["caixas_por_viagem"])
        self.assertTrue(any("2026-09" in warning for warning in result["warnings"]))
        self.assertTrue(any("Valores ausentes" in warning for warning in result["warnings"]))

    def test_falls_back_to_previous_valid_batch_when_latest_has_no_recognized_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LigaEntregaReportStore(temp_dir)
            store.store_batch(
                routine=BI_INDICATORS_ROUTINE,
                files={"BI_valido.csv": "Ano;Mês;Puxada;Base;Valor Mes\n2026;09;00747530;0649;87,5\n".encode("cp1252")},
                reference_date="2026-09-29",
            )
            store.store_batch(
                routine=BI_INDICATORS_ROUTINE,
                files={"BI_incompleto.csv": b"arquivo;sem;colunas\n1;2;3\n"},
                reference_date="2026-09-30",
            )
            result = OperationalIndicatorsService(report_store=store).build_dashboard(competencia="2026-09")
        self.assertEqual(result["branches"][0]["puxada"], "00747530")
        self.assertEqual(result["branches"][0]["metrics"]["ocupacao"], 87.5)
