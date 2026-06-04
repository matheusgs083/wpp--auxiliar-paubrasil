import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.doperacoes_import_service import (
    DOperacoesImportService,
    _load_doperacoes_rows,
)


class DOperacoesImportServiceTests(unittest.TestCase):
    def test_load_rows_uses_only_first_three_columns_and_preserves_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dOperacoes.csv"
            path.write_text(
                "\n".join(
                    [
                        "Codigo;Tipo Movimento;Nome da Operacao;Ignorada",
                        "000000000001;051;VENDA DE PRODUTOS             ;05405",
                        "000000000002;052;BONIF DES BALZ/COMBO          ;05910",
                    ]
                ),
                encoding="utf-8",
            )

            rows = _load_doperacoes_rows(path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].codigo, "000000000001")
        self.assertEqual(rows[0].tipo_movimento, "051")
        self.assertEqual(rows[0].nome_operacao, "VENDA DE PRODUTOS")
        self.assertEqual(rows[1].codigo, "000000000002")
        self.assertEqual(rows[1].tipo_movimento, "052")

    def test_validate_source_reads_real_csv_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dOperacoes.csv"
            path.write_text(
                "\n".join(
                    [
                        "Codigo;Tipo Movimento;Nome da Operacao;Codigo Fiscal",
                        "000000000003;054;COMODATO ATIVO GIRO;05908",
                    ]
                ),
                encoding="utf-8",
            )

            result = DOperacoesImportService(database_url="", schema="reports").validate_source(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.unique_codigos, 1)
        self.assertEqual(result.unique_tipos_movimento, 1)
        self.assertEqual(result.error_count, 0)


if __name__ == "__main__":
    unittest.main()
