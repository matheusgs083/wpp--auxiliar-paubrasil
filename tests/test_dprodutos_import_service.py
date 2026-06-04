import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.dprodutos_import_service import DProdutosImportService, _load_dprodutos_rows


class DProdutosImportServiceTests(unittest.TestCase):
    def test_load_rows_normalizes_product_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "01.11.CSV"
            path.write_text(
                "\n".join(
                    [
                        "Codigo;Descricao;PGV;Empresa;Tipo Marca;Linha Marca;Embalagem;Marca;Grupo;Fator Hecto;Codigo Unitario;Descricao unitaria;Subtipo",
                        "0002349; GCA PT2 CX6 ;000123;GE;001 - CERVEJA;009;CX6;00038;037;00,050000;00002349; GCA PT2 CX6 ;012",
                    ]
                ),
                encoding="utf-8",
            )

            rows = _load_dprodutos_rows(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].codigo, "2349")
        self.assertEqual(rows[0].descricao, "GCA PT2 CX6")
        self.assertEqual(rows[0].pgv, "000123")
        self.assertEqual(rows[0].tipo_marca, "001 - CERVEJA")
        self.assertEqual(rows[0].fator_hecto, Decimal("0.050000"))
        self.assertEqual(rows[0].codigo_unitario, "2349")
        self.assertEqual(rows[0].payload["Tipo Marca"], "001 - CERVEJA")

    def test_validate_source_reads_csv_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "01.11.CSV"
            path.write_text(
                "\n".join(
                    [
                        "Código;Descrição;Marca;Grupo",
                        "0000002;GAS CARBONICO BRAHMA CILINDRO 1 KG;00038;037",
                    ]
                ),
                encoding="utf-8",
            )

            result = DProdutosImportService(database_url="", schema="reports").validate_source(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.unique_codigos, 1)
        self.assertEqual(result.unique_marcas, 1)
        self.assertEqual(result.error_count, 0)


if __name__ == "__main__":
    unittest.main()
