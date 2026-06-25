from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.app import _build_admin_critica_sector_pdf_response
from tests.test_support import StubCriticaRnService


class AdminCriticaPanelPdfTests(unittest.TestCase):
    def test_build_sector_pdf_response_uses_operation_and_sector_scope(self) -> None:
        service = StubCriticaRnService(latest=date(2026, 6, 10))

        with patch("bot_api.app_factory.critica_rn_query_service", service):
            response = _build_admin_critica_sector_pdf_response(
                {"is_admin": False, "filiais": ["3"]},
                operation="3",
                sector="401",
                target_date=None,
                summary_only=False,
            )

        self.assertEqual(response.media_type, "application/pdf")
        self.assertEqual(response.body, b"%PDF-critica-detalhe")
        self.assertIn('filename="critica-rn-setor-3-401-2026-06-10.pdf"', response.headers.get("content-disposition", ""))
        self.assertEqual(service.latest_calls[-1]["allowed_sectors"], ["3_401"])
        self.assertEqual(service.pdf_report_calls[-1]["allowed_sectors"], ["3_401"])
        self.assertEqual(service.pdf_report_calls[-1]["target_date"], date(2026, 6, 10))

    def test_build_sector_summary_pdf_response_uses_summary_bytes(self) -> None:
        service = StubCriticaRnService(latest=date(2026, 6, 9))

        with patch("bot_api.app_factory.critica_rn_query_service", service):
            response = _build_admin_critica_sector_pdf_response(
                {"is_admin": True},
                operation="3",
                sector="400",
                target_date=date(2026, 6, 8),
                summary_only=True,
            )

        self.assertEqual(response.media_type, "application/pdf")
        self.assertEqual(response.body, b"%PDF-critica-resumo")
        self.assertIn('filename="critica-rn-setor-3-400-2026-06-08-resumo.pdf"', response.headers.get("content-disposition", ""))
        self.assertEqual(service.latest_calls, [])
        self.assertEqual(service.pdf_report_calls[-1]["allowed_sectors"], ["3_400"])
        self.assertEqual(service.pdf_report_calls[-1]["target_date"], date(2026, 6, 8))

    def test_build_sector_pdf_response_blocks_without_today_upload(self) -> None:
        service = StubCriticaRnService(latest=date(2026, 6, 10), current_import_available=False)

        with patch("bot_api.app_factory.critica_rn_query_service", service):
            with self.assertRaises(HTTPException) as raised:
                _build_admin_critica_sector_pdf_response(
                    {"is_admin": False, "filiais": ["3"]},
                    operation="3",
                    sector="401",
                    target_date=None,
                    summary_only=False,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("importe os relatorios de critica de hoje", str(raised.exception.detail))
        self.assertEqual(len(service.pdf_report_calls), 0)


if __name__ == "__main__":
    unittest.main()
