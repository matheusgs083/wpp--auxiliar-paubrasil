import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.dprecos_import_service import (
    DPrecosImportService,
    _build_dprecos_rows_from_mapping_rows,
    _parse_decimal_value,
)


class DPrecosImportServiceTests(unittest.TestCase):
    def test_parse_decimal_value_handles_brazilian_and_plain_values(self) -> None:
        self.assertEqual(_parse_decimal_value("R$ 1.234,56"), Decimal("1234.56"))
        self.assertEqual(_parse_decimal_value("53,90"), Decimal("53.90"))
        self.assertEqual(_parse_decimal_value("2.89"), Decimal("2.89"))
        self.assertEqual(_parse_decimal_value(""), Decimal("0"))

    def test_build_rows_normalizes_product_code_and_prices(self) -> None:
        rows = _build_dprecos_rows_from_mapping_rows(
            [
                {
                    "codigo": "0013205",
                    "produto": " SKOL GFA VD 300ML   ",
                    "und": "23",
                    "asr": "53,90",
                    "sub": "53,90",
                    "frio": "58,50",
                    "ttc": "2,89",
                }
            ],
            header_map={
                "codigo": "codigo",
                "produto": "produto",
                "und": "und",
                "asr": "asr",
                "sub": "sub",
                "frio": "frio",
                "ttc": "ttc",
            },
            row_number_offset=2,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].codigo, "13205")
        self.assertEqual(rows[0].produto, "SKOL GFA VD 300ML")
        self.assertEqual(rows[0].und, Decimal("23"))
        self.assertEqual(rows[0].asr, Decimal("53.90"))
        self.assertEqual(rows[0].frio, Decimal("58.50"))
        self.assertEqual(rows[0].ttc, Decimal("2.89"))

    def test_validate_source_reads_workbook_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "DPrecos.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "export"
            worksheet.append(["codigo", "produto", "und", "asr", "sub", "frio", "ttc"])
            worksheet.append([13205, "SKOL GFA VD 300ML", 23, 53.9, 53.9, 58.5, 2.89])
            worksheet.append([13196, "SKOL ONE WAY 300ML", 23, 75.9, 75.9, 75.9, 3.89])
            workbook.save(path)
            workbook.close()

            result = DPrecosImportService(database_url="", schema="reports").validate_source(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.unique_codigos, 2)
        self.assertEqual(result.error_count, 0)


if __name__ == "__main__":
    unittest.main()
