from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot_api.services import boletos_pdf_import_service as modulo

TEXTO_BOM = "MAPA:295085 CLIENTE: 99550 - NF\nCPF: 032.386.974-20\n09/15940341023-5\n23791.59409 91594.034109 23001.150400 7 16470000008160"
OCR_RUIM = "ee O BgS50 LUIZ PAULINO DE OLIVEIRA - GPF: 032:305.974-20"


class ValidacaoBoletosTest(unittest.TestCase):
    def validar(self, *, texto: str, ocr: str) -> tuple[modulo.BoletosPdfValidationResult, mock.Mock]:
        servico = modulo.BoletosPdfImportService("postgresql://x", "reports", expected_filial="1")
        with tempfile.TemporaryDirectory() as pasta:
            pdf = Path(pasta) / "03,02,06_0640001.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            with mock.patch.object(modulo, "_pdf_page_count", return_value=1440), \
                 mock.patch.object(modulo, "_extract_text_page", return_value=texto), \
                 mock.patch.object(modulo, "_ocr_pdf_page", return_value=ocr) as ocr_mock:
                return servico.validate_source(pdf), ocr_mock

    def test_texto_do_pdf_vale_mesmo_com_ocr_ruim(self) -> None:
        resultado, ocr_mock = self.validar(texto=TEXTO_BOM, ocr=OCR_RUIM)
        self.assertTrue(resultado.ok, resultado.sample_errors)
        self.assertEqual(resultado.sample_pages_with_document, 3)
        ocr_mock.assert_not_called()

    def test_sem_texto_usa_ocr_e_recusa_quando_nao_acha_documento(self) -> None:
        resultado, ocr_mock = self.validar(texto="", ocr=OCR_RUIM)
        self.assertFalse(resultado.ok)
        self.assertIn("Nao encontrei CPF/CNPJ nas paginas de amostra.", resultado.sample_errors)
        self.assertEqual(ocr_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
