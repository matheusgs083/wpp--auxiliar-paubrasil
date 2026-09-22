from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bot_api.services.liga_entrega_import_service import LigaEntregaReportImportService
from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore


class LigaEntregaReportImportServiceTest(unittest.TestCase):
    def test_import_source_stores_manifest_and_latest_status(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "PATOS_21_09.csv").write_text("a;b\n1;2\n", encoding="utf-8")
            (source / "SUME_21_09.csv").write_text("a;b\n3;4\n", encoding="utf-8")
            store = LigaEntregaReportStore(root / "store")
            service = LigaEntregaReportImportService(
                report_store=store,
                dataset_name="liga_030805",
                label="Liga Entrega - 03.08.05 Rotas do dia",
                routine="030805_LIGA",
                allowed_extensions={".csv", ".txt"},
                expected_name_patterns=(r"^(PATOS|SUME)_\d{2}_\d{2}\.csv$",),
            )

            validation = service.validate_source(source).to_dict()
            self.assertEqual(validation["error_count"], 0)
            self.assertEqual(validation["file_count"], 2)

            result = service.import_source(source).to_dict()
            self.assertEqual(result["file_count"], 2)
            self.assertEqual(result["routine"], "030805_LIGA")

            latest = service.latest_status()
            self.assertIsNotNone(latest)
            self.assertEqual(latest["total_rows"], 2)
            self.assertIn("PATOS_21_09.csv", latest["source_file"])

    def test_validate_rejects_invalid_extension(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "Checklist Setembro.pdf").write_bytes(b"pdf")
            service = LigaEntregaReportImportService(
                report_store=LigaEntregaReportStore(root / "store"),
                dataset_name="liga_checklist_frota",
                label="Liga Entrega - Checklist Frota",
                routine="CHECKLIST_FROTA",
                allowed_extensions={".xlsx", ".xlsm"},
            )

            validation = service.validate_source(source).to_dict()
            self.assertGreater(validation["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
