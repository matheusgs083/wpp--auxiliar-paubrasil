import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.produto_cestas_import_service import (
    ProdutoCestasImportService,
    _load_produto_cesta_rows,
    _parse_categoria_from_cesta,
)


class ProdutoCestasImportServiceTests(unittest.TestCase):
    def test_parse_categoria_from_cesta(self) -> None:
        self.assertEqual(_parse_categoria_from_cesta("Categoria - Cerveja"), ("categoria", "Cerveja"))
        self.assertEqual(_parse_categoria_from_cesta("Categoria Agrupado - Outros"), ("categoria_agrupada", "Outros"))
        self.assertEqual(_parse_categoria_from_cesta("Pepsi - Familia"), ("familia", "Pepsi"))
        self.assertEqual(_parse_categoria_from_cesta("Cesta Especial"), ("cesta", "Cesta Especial"))

    def test_load_rows_from_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Cesta de Produtos.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "Export"
            worksheet.append(["Código Abreviado Produto", "Nome Cesta", "Nome Produto", "Nome Fornec. Mktplace"])
            worksheet.append([2, "Categoria - Outros", "GAS CARBONICO BRAHMA CILINDRO 1 KG", ""])
            worksheet.append([2, "Categoria Agrupado - Outros", "GAS CARBONICO BRAHMA CILINDRO 1 KG", ""])
            worksheet.append([8, "Pepsi - Familia", "MIST. SUBST. ODORIF. TUTTI-FRUTTI", ""])
            workbook.save(path)
            workbook.close()

            rows = _load_produto_cesta_rows(path)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].codigo, "2")
        self.assertEqual(rows[0].categoria_tipo, "categoria")
        self.assertEqual(rows[0].categoria_nome, "Outros")
        self.assertEqual(rows[1].categoria_tipo, "categoria_agrupada")
        self.assertEqual(rows[2].categoria_tipo, "familia")
        self.assertEqual(rows[2].categoria_nome, "Pepsi")

    def test_validate_source_reads_workbook_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Cesta de Produtos.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.append(["Código Abreviado Produto", "Nome Cesta", "Nome Produto"])
            worksheet.append([2349, "Categoria - Cerveja", "GCA PT2 CX6"])
            workbook.save(path)
            workbook.close()

            result = ProdutoCestasImportService(database_url="", schema="reports").validate_source(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.unique_codigos, 1)
        self.assertEqual(result.unique_categorias, 1)
        self.assertEqual(result.error_count, 0)


if __name__ == "__main__":
    unittest.main()
