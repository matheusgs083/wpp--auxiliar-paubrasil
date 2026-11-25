import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.dcondicoes_import_service import DCondicoesImportService, _load_dcondicoes_rows


class DCondicoesImportServiceTests(unittest.TestCase):
    def test_load_rows_reads_real_csv_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dCondicoes.csv"
            path.write_text(
                "\n".join(
                    [
                        "Filial;Condição de Pagto;Descrição;Forma de Pagto",
                        "0001;000000000060;ACERTO              ;060",
                        "0003;000000000605;PROMO 21 DIAS       ;004",
                    ]
                ),
                encoding="utf-8",
            )

            rows = _load_dcondicoes_rows(path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].filial, "1")
        self.assertEqual(rows[0].condicao_codigo, "60")
        self.assertEqual(rows[0].descricao, "ACERTO")
        self.assertEqual(rows[0].filial_condicao_key, "1_60")
        self.assertEqual(rows[1].filial_condicao_key, "3_605")

    def test_validate_source_counts_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dCondicoes.csv"
            path.write_text(
                "\n".join(
                    [
                        "Filial;Condição de Pagto;Descrição;Forma de Pagto",
                        "0001;000000000060;ACERTO;060",
                    ]
                ),
                encoding="utf-8",
            )

            result = DCondicoesImportService(database_url="", schema="reports").validate_source(path)

        self.assertTrue(result.ok)
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.unique_filiais, 1)
        self.assertEqual(result.unique_condicoes, 1)
        self.assertEqual(result.error_count, 0)

    def test_import_preserves_monthly_adf_and_keeps_missing_distinct_from_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dCondicoes.csv"
            path.write_text(
                "Filial;Condição de Pagto;Descrição;Taxa Mensal p/ ADF;Dias até 1° Vencimento\n"
                "0003;000000000605;BOLETO;006,11;010\n"
                "0003;000000000606;OUTRA;000,00;000\n"
                "0003;000000000607;SEM TAXA;;\n", encoding="utf-8"
            )
            rows = _load_dcondicoes_rows(path)
        self.assertEqual([r.taxa_mensal_adf for r in rows], ["006,11", "000,00", ""])
        self.assertEqual([r.dias_primeiro_vencimento for r in rows], ["010", "000", ""])


if __name__ == "__main__":
    unittest.main()
