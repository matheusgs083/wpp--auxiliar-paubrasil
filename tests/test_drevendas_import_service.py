import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.drevendas_import_service import (
    DRevendasImportService,
    _load_drevendas_rows,
)


class DRevendasImportServiceTests(unittest.TestCase):
    def test_load_rows_from_workbook_uses_unb_and_nome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dRevendas.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.append(["UNB", "NOME"])
            worksheet.append([1, "Sousa"])
            worksheet.append([4, "Sume"])
            workbook.save(path)

            rows = _load_drevendas_rows(path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].codigo, "1")
        self.assertEqual(rows[0].nome, "Sousa")
        self.assertEqual(rows[1].codigo, "4")
        self.assertEqual(rows[1].nome, "Sume")

    def test_validate_source_reads_csv_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dRevendas.csv"
            path.write_text(
                "\n".join(
                    [
                        "UNB;NOME",
                        "3;Patos",
                        "8;Cacule",
                    ]
                ),
                encoding="utf-8",
            )

            result = DRevendasImportService(database_url="", schema="reports").validate_source(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.unique_revendas, 2)
        self.assertEqual(result.error_count, 0)


if __name__ == "__main__":
    unittest.main()
