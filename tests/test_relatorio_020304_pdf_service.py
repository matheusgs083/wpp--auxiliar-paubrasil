from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.services.relatorio_020304_pdf_service import (
    build_020304_pdf,
    read_020304_csv,
    summarize_020304_rows,
)


SAMPLE_CSV = """Grade;Cod;Descricao;UN;Inicial;Ent.;Ent.MCDD;Reserva;Trans.;Saidas;Sai.MCDD;Disp.;Res.Magali;Inic.Agend.;Ent.Agend.;Sai.Agend.;Disp.Agend.
01;000347;SU PT1 CX12    ;cx  ;0000309;0000000;0000000;0000000;000000; 000025; 000000; 0000284; 0000000;0000000;0000000;0000000; 0000000
01;002546;ORIGINAL 600   ;Dz  ;0000032;0000000;0000000;0000000;000000; 000032; 000000; 0000000; 0000000;0000000;0000000;0000000; 0000000
01;001695;BC GFAVD1L COM ;Dz  ;0000474;0000000;0000000;0000001;000000; 000029; 000000; 0000444; 0000000;0000000;0000000;0000000; 0000000
"""


class Relatorio020304PdfServiceTests(unittest.TestCase):
    def test_read_020304_csv_and_summarize_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "020304.csv"
            csv_path.write_text(SAMPLE_CSV, encoding="utf-8")

            rows = read_020304_csv(csv_path)
            summary = summarize_020304_rows(
                rows,
                filial="3",
                filial_nome="Patos",
                reference_date=date(2026, 7, 23),
                source_name=csv_path.name,
            )

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].codigo, "347")
        self.assertEqual(rows[0].descricao, "SU PT1 CX12")
        self.assertEqual(summary.filial, "3")
        self.assertEqual(summary.filial_nome, "Patos")
        self.assertEqual(summary.totals["inicial"], 815)
        self.assertEqual(summary.totals["saidas"], 86)
        self.assertEqual(summary.totals["disponivel"], 728)
        self.assertEqual(summary.produtos_sem_disponivel, 1)
        self.assertEqual(summary.produtos_com_reserva, 1)

    def test_build_020304_pdf_returns_pdf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "020304.csv"
            csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
            rows = read_020304_csv(csv_path)

        summary = summarize_020304_rows(
            rows,
            filial="3",
            filial_nome="Patos",
            reference_date=date(2026, 7, 23),
            source_name="020304.csv",
        )
        pdf_bytes = build_020304_pdf(rows, summary=summary)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 1000)


if __name__ == "__main__":
    unittest.main()
