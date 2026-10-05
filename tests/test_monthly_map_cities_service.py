from __future__ import annotations

import tempfile
import unittest

from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore
from bot_api.services.monthly_map_cities_service import (
    MONTHLY_MAP_CITIES_ROUTINE,
    MonthlyMapCitiesService,
)


class MonthlyMapCitiesServiceTests(unittest.TestCase):
    def test_sql_rows_are_used_without_reading_report_store(self) -> None:
        class SqlRows:
            def rows_for_routine(self, *, routine: str, competencia: str | None = None):
                self.called = (routine, competencia)
                return [
                    {
                        "source_key": "file-1",
                        "filename": "03114902_PATOS.csv",
                        "payload": {"Mapa": "000777", "Cidade": "Patos", "Data": "02/10/2026"},
                    }
                ]

        class NoCsvStore:
            def list_manifests(self, *args, **kwargs):
                raise AssertionError("o endpoint SQL nao deve ler manifestos/CSV")

        result = MonthlyMapCitiesService(
            report_store=NoCsvStore(),
            raw_sql_import_service=SqlRows(),
        ).build_dashboard(competencia="2026-10", period="atual")
        self.assertEqual(result["rows"][0]["mapa"], "777")
        self.assertEqual(result["summary"]["files"], 1)

    def test_reads_monthly_maps_without_using_liga_dashboard_batch(self) -> None:
        content = b"Mapa;Cidade;Data\n000123;Patos;30/09/2026\n000124;Sume;30/09/2026\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LigaEntregaReportStore(temp_dir)
            store.store_batch(
                routine=MONTHLY_MAP_CITIES_ROUTINE,
                files={"03.11.49.02_PATOS_SET.csv": content},
                reference_date="2026-09-30",
            )
            result = MonthlyMapCitiesService(report_store=store).build_dashboard(competencia="2026-09", period="fechado")
        self.assertEqual(result["summary"]["mapas"], 2)
        self.assertEqual(result["summary"]["cidades"], 2)
        self.assertEqual(result["rows"][0]["mapa"], "123")

    def test_reads_monthly_maps_even_when_liga_period_is_current(self) -> None:
        content = b"Mapa;Cidade;Data\n000125;Patos;02/10/2026\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LigaEntregaReportStore(temp_dir)
            store.store_batch(
                routine=MONTHLY_MAP_CITIES_ROUTINE,
                files={"03.11.49.02_PATOS_SET.csv": content},
                reference_date="2026-10-02",
            )
            result = MonthlyMapCitiesService(report_store=store).build_dashboard(
                competencia="2026-10",
                period="atual",
            )
        self.assertEqual(result["summary"]["mapas"], 1)
        self.assertEqual(result["rows"][0]["mapa"], "125")

    def test_falls_back_when_latest_monthly_batch_has_no_valid_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LigaEntregaReportStore(temp_dir)
            store.store_batch(
                routine=MONTHLY_MAP_CITIES_ROUTINE,
                files={"mapas_validos.csv": b"Mapa;Cidade;Data\n000123;Patos;30/09/2026\n"},
                reference_date="2026-09-29",
            )
            store.store_batch(
                routine=MONTHLY_MAP_CITIES_ROUTINE,
                files={"mapas_incompletos.csv": b"arquivo;sem;coluna\n1;2;3\n"},
                reference_date="2026-09-30",
            )
            result = MonthlyMapCitiesService(report_store=store).build_dashboard(competencia="2026-09", period="fechado")
        self.assertEqual(result["summary"]["mapas"], 1)
        self.assertEqual(result["rows"][0]["mapa"], "123")
