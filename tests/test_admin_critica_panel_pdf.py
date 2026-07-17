from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.services import admin_critica_dashboard_service
from tests.test_support import StubCriticaRnService


def _panel_context_allowed_report_scopes(context: dict[str, object] | None) -> tuple[list[str] | None, None]:
    if not context or bool(context.get("is_admin")):
        return None, None
    filiais = [
        str(filial).strip()
        for filial in context.get("filiais", [])
        if str(filial).strip() and str(filial).strip() != "*"
    ]
    return filiais, None


class AdminCriticaPanelPdfTests(unittest.TestCase):
    def configure_service(self, service: StubCriticaRnService) -> None:
        admin_critica_dashboard_service.configure(
            critica_rn_query_service=service,
            _panel_context_allowed_report_scopes=_panel_context_allowed_report_scopes,
        )

    def test_build_sector_pdf_response_uses_operation_and_sector_scope(self) -> None:
        service = StubCriticaRnService(latest=date(2026, 6, 10))
        self.configure_service(service)

        response = admin_critica_dashboard_service._build_admin_critica_sector_pdf_response(
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
        self.configure_service(service)

        response = admin_critica_dashboard_service._build_admin_critica_sector_pdf_response(
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

    def test_build_operation_pdf_response_uses_filial_scope_when_sector_is_empty(self) -> None:
        service = StubCriticaRnService(latest=date(2026, 6, 11))
        self.configure_service(service)

        response = admin_critica_dashboard_service._build_admin_critica_sector_pdf_response(
            {"is_admin": False, "filiais": ["3"]},
            operation="3",
            sector="",
            target_date=None,
            summary_only=False,
        )

        self.assertEqual(response.media_type, "application/pdf")
        self.assertEqual(response.body, b"%PDF-critica-detalhe")
        self.assertIn('filename="critica-rn-operacao-3-2026-06-11.pdf"', response.headers.get("content-disposition", ""))
        self.assertEqual(service.latest_calls[-1]["allowed_sectors"], ["filial:3"])
        self.assertEqual(service.pdf_report_calls[-1]["allowed_sectors"], ["filial:3"])
        self.assertEqual(service.pdf_report_calls[-1]["target_date"], date(2026, 6, 11))
        self.assertEqual(service.pdf_report_calls[-1]["limit"], 50000)

    def test_build_sector_pdf_response_blocks_without_today_upload(self) -> None:
        service = StubCriticaRnService(latest=date(2026, 6, 10), current_import_available=False)
        self.configure_service(service)

        with self.assertRaises(HTTPException) as raised:
            admin_critica_dashboard_service._build_admin_critica_sector_pdf_response(
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
