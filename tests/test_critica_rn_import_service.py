import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.critica_rn_import_service import (
    CriticaRnImportService,
    _build_critica_rn_rows_from_mapping_rows,
)


class CriticaRnImportServiceTests(unittest.TestCase):
    def test_build_rows_creates_sector_and_product_links(self) -> None:
        headers = [
            "UNB",
            "Pedido",
            "Data Pedido",
            "Operacao",
            "Cod. PDV",
            "Nome PDV",
            "Setor",
            "Status Pedido",
            "Total Pedido",
            "Total Cliente",
            "Critica 1",
            "Produto",
            "Quantidade",
            "Unid. Venda",
            "Preco Unitario",
            "Preco S/ ADF",
            "Minimo Politica",
            "Tipo Movimento",
            "Codigo GV",
            "Codigo PGV",
        ]
        header_map = {header: header for header in headers}

        rows = _build_critica_rn_rows_from_mapping_rows(
            [
                {
                    "UNB": "03",
                    "Pedido": "43929",
                    "Data Pedido": date(2026, 6, 3),
                    "Operacao": "5",
                    "Cod. PDV": "1088",
                    "Nome PDV": " SUPERMERCADO TOLENTI ",
                    "Setor": "401",
                    "Status Pedido": "Normal",
                    "Total Pedido": "13,93",
                    "Total Cliente": "3919,57",
                    "Critica 1": "Preco baixo",
                    "Produto": "00021658",
                    "Quantidade": "2",
                    "Unid. Venda": "cx",
                    "Preco Unitario": "64",
                    "Preco S/ ADF": "64",
                    "Minimo Politica": "37,90",
                    "Tipo Movimento": "51",
                    "Codigo GV": "35",
                    "Codigo PGV": "3501",
                }
            ],
            headers=headers,
            header_map=header_map,
            row_number_offset=2,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].filial, "3")
        self.assertEqual(rows[0].setor, "401")
        self.assertEqual(rows[0].filial_setor_key, "3_401")
        self.assertEqual(rows[0].produto_codigo, "21658")
        self.assertEqual(rows[0].produto_key, "21658")
        self.assertEqual(rows[0].preco_unitario, Decimal("64"))
        self.assertEqual(rows[0].critica_text, "Preco baixo")

    def test_validate_source_counts_duplicate_order_product_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "critica_rn.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "03013604"
            worksheet.append(
                [
                    "UNB",
                    "Pedido",
                    "Data Pedido",
                    "Operacao",
                    "Cod. PDV",
                    "Nome PDV",
                    "Setor",
                    "Status Pedido",
                    "Total Pedido",
                    "Total Cliente",
                    "Critica 1",
                    "Produto",
                    "Quantidade",
                    "Unid. Venda",
                    "Preco Unitario",
                    "Preco S/ ADF",
                    "Minimo Politica",
                ]
            )
            worksheet.append([3, 43929, date(2026, 6, 3), 5, 1088, "PDV A", 401, "Normal", 10, 100, "", 21658, 1, "cx", 64, 64, 37.9])
            worksheet.append([3, 43929, date(2026, 6, 3), 5, 1088, "PDV A", 401, "Normal", 10, 100, "", 21658, 1, "cx", 64, 64, 37.9])
            worksheet.append([3, 43930, date(2026, 6, 3), 5, 1089, "PDV B", 500, "Normal", 20, 200, "Critica", 9067, 2, "un", 5, 5, 0])
            workbook.save(path)
            workbook.close()

            result = CriticaRnImportService(database_url="", schema="reports").validate_source(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.total_rows, 3)
        self.assertEqual(result.unique_pedidos, 2)
        self.assertEqual(result.unique_unb_setores, 2)
        self.assertEqual(result.unique_produtos, 2)
        self.assertEqual(result.duplicate_pedido_produto_keys, 1)
        self.assertEqual(result.rows_with_critica, 1)


if __name__ == "__main__":
    unittest.main()
