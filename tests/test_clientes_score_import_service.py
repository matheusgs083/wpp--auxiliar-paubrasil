from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bot_api.services.clientes_score_import_service import ClientesScoreImportService


class ClientesScoreImportServiceTest(unittest.TestCase):
    def test_validate_and_summarize_csv(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "clientes_score.csv"
            path.write_text(
                "\n".join(
                    [
                        "Codigo;Cliente;RazaoSocial;Filial;Score;Piorando2026;PctAtrasoHistorico;TitulosHistorico;RecebidoHistorico;MaiorAtrasoDias;VezesMais30d;TarifaPaga;JurosPagos;EmAbertoHoje;VencidoHoje;DiasVencidoMaisAntigo",
                        "9845;O COMILAO;ALLAN KARDEC;3;C;sim;37,43;187;433,20;20;0;458,64;6900000;2940,75;0;0",
                        "9845;O COMILAO;ALLAN KARDEC;1;A;;0;28;27618,48;0;0;0;0;0;0;0",
                    ]
                ),
                encoding="utf-8",
            )
            service = ClientesScoreImportService(database_url="", schema="reports")

            validation = service.validate_source(path)
            summary = service.summarize_source(path)

        self.assertTrue(validation.ok)
        self.assertEqual(validation.total_rows, 2)
        self.assertEqual(validation.unique_clientes, 2)
        self.assertEqual(summary.rows, 2)
        self.assertEqual(summary.unique_filiais, 2)
        self.assertCountEqual(summary.score_counts, [("C", 1), ("A", 1)])


if __name__ == "__main__":
    unittest.main()
