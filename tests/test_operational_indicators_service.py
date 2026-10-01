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
