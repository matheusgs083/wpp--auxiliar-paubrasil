from __future__ import annotations

import tempfile
import unittest

from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore
from bot_api.services.monthly_map_cities_service import MONTHLY_MAP_CITIES_ROUTINE, MonthlyMapCitiesService


class MonthlyMapCitiesServiceTests(unittest.TestCase):
    def test_reads_monthly_maps_without_using_liga_dashboard_batch(self) -> None:
        content = b"Mapa;Cidade;Data\n000123;Patos;30/09/2026\n000124;Sume;30/09/2026\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LigaEntregaReportStore(temp_dir)
            store.store_batch(routine=MONTHLY_MAP_CITIES_ROUTINE, files={"03.11.49.02_PATOS_SET.csv": content}, reference_date="2026-09-30")
            result = MonthlyMapCitiesService(report_store=store).build_dashboard(competencia="2026-09")
        self.assertEqual(result["summary"]["mapas"], 2)
        self.assertEqual(result["summary"]["cidades"], 2)
        self.assertEqual(result["rows"][0]["mapa"], "123")
