from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bot_api.services.admin_payip_batch_service as payip_batch_module
from bot_api.integrations.payip_client import PayipError
from bot_api.services.admin_payip_batch_service import AdminPayipBatchService
from tests.test_support import StubPayipPaymentsService, StubQueryService


class AdminPayipBatchServiceTests(unittest.TestCase):
    def make_service(
        self,
        payip_service: StubPayipPaymentsService | None = None,
        dclientes_query_service: object | None = None,
    ) -> AdminPayipBatchService:
        return AdminPayipBatchService(
            payip_payments_service=payip_service or StubPayipPaymentsService(),
            dclientes_query_service=dclientes_query_service,
            panel_context_has_all_filiais=lambda context: "*" in (context or {}).get("filiais", ()),
            logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None, exception=lambda *_args, **_kwargs: None),
        )

    def payload(self, raw_text: str, **overrides: object) -> SimpleNamespace:
        data = {
            "raw_text": raw_text,
            "use_default_rate": True,
            "use_default_interest": True,
            "include_nb": False,
            "include_nf": False,
        }
        data.update(overrides)
        return SimpleNamespace(**data)

    def test_preview_requires_finance_scope(self) -> None:
        service = self.make_service()
        with self.assertRaises(HTTPException) as raised:
            service.preview(
                self.payload("filial;nb;valor;vencimento\n4;16883;100,00;2026-12-31"),
                {"is_admin": False, "mode": "financeiro", "filiais": ["3"]},
            )
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("fora do escopo", str(raised.exception.detail))

    def test_queue_creates_payip_charge_without_nb_or_nf_by_default(self) -> None:
        payip = StubPayipPaymentsService()
        service = self.make_service(payip)
        result = service.queue(
            self.payload("filial;nb;valor;vencimento;nf\n3;16883;99,90;2026-12-31;147478"),
            {"is_admin": True},
        )
        job_id = result["job"]["job_id"]
        for _ in range(20):
            snapshot = service.snapshot(job_id=job_id)
            if snapshot["job"].get("status") == "done":
                break
            time.sleep(0.05)

        snapshot = service.snapshot(job_id=job_id)
        job = snapshot["job"]
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["success"], 1)
        self.assertEqual(payip.client_lookup_calls[-1], {"filial": "3", "client_code": "16883"})
        self.assertEqual(payip.create_charge_calls[-1]["external_id"], "")
        self.assertEqual(payip.create_charge_calls[-1]["invoice"], "")
        self.assertEqual(payip.create_charge_calls[-1]["rate_amount"], "3.92")
        self.assertEqual(payip.create_charge_calls[-1]["interest_perc"], "10.00")
        self.assertTrue(job["results"][0]["pix_code"])
        self.assertTrue(job["results"][0]["pdf_available"])
        pdf_bytes, filename = service.pdf_bytes(job["results"][0]["item_id"], job_id=job_id)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertTrue(filename.endswith(".pdf"))

    def test_queue_bootstraps_payip_mfa_before_processing(self) -> None:
        payip = StubPayipPaymentsService(require_mfa_once=True)
        service = self.make_service(payip)
        result = service.queue(
            self.payload("filial;nb;valor;vencimento\n3;16883;99,90;2026-12-31", mfa_code="123456"),
            {"is_admin": True},
        )
        job_id = result["job"]["job_id"]
        for _ in range(20):
            snapshot = service.snapshot(job_id=job_id)
            if snapshot["job"].get("status") == "done":
                break
            time.sleep(0.05)

        snapshot = service.snapshot(job_id=job_id)
        self.assertEqual(payip.bootstrap_calls, ["123456"])
        self.assertEqual(snapshot["job"]["success"], 1)
        self.assertNotIn("_mfa_code", snapshot["job"])

    def test_queue_retries_pdf_when_payip_report_is_not_ready(self) -> None:
        class RetryPdfPayipService(StubPayipPaymentsService):
            def __init__(self) -> None:
                super().__init__()
                self.remaining_failures = 1

            def invoice_report_pdf(self, **kwargs: object) -> bytes:
                self.invoice_report_calls.append(
                    {
                        "filial": kwargs.get("filial"),
                        "payment_ids": list(kwargs.get("payment_ids") or []),
                        "company_id": kwargs.get("company_id", ""),
                    }
                )
                if self.remaining_failures:
                    self.remaining_failures -= 1
                    raise PayipError("arquivo ainda nao foi criado, tente novamente")
                return b"%PDF-1.4\n%stub-payip\n"

        previous_delay = payip_batch_module.PAYIP_PDF_RETRY_DELAY_SECONDS
        payip_batch_module.PAYIP_PDF_RETRY_DELAY_SECONDS = 0
        try:
            payip = RetryPdfPayipService()
            service = self.make_service(payip)
            result = service.queue(
                self.payload("filial;nb;valor;vencimento\n3;16883;99,90;2026-12-31"),
                {"is_admin": True},
            )
            job_id = result["job"]["job_id"]
            for _ in range(20):
                snapshot = service.snapshot(job_id=job_id)
                if snapshot["job"].get("status") == "done":
                    break
                time.sleep(0.05)
        finally:
            payip_batch_module.PAYIP_PDF_RETRY_DELAY_SECONDS = previous_delay

        snapshot = service.snapshot(job_id=job_id)
        self.assertEqual(snapshot["job"]["success"], 1)
        self.assertTrue(snapshot["job"]["results"][0]["pdf_available"])
        self.assertEqual(len(payip.invoice_report_calls), 2)

    def test_queue_retries_charge_creation_after_transient_error(self) -> None:
        class RetryChargePayipService(StubPayipPaymentsService):
            def __init__(self) -> None:
                super().__init__()
                self.remaining_failures = 1

            def create_pix_charge(self, **kwargs: object) -> dict[str, object]:
                if self.remaining_failures:
                    self.remaining_failures -= 1
                    raise PayipError("PayIP create payment failed: HTTP 503")
                return super().create_pix_charge(**kwargs)

        previous_delay = payip_batch_module.PAYIP_CHARGE_RETRY_DELAY_SECONDS
        payip_batch_module.PAYIP_CHARGE_RETRY_DELAY_SECONDS = 0
        try:
            payip = RetryChargePayipService()
            service = self.make_service(payip)
            result = service.queue(
                self.payload("filial;nb;valor;vencimento\n3;16883;99,90;2026-12-31"),
                {"is_admin": True},
            )
            job_id = result["job"]["job_id"]
            for _ in range(20):
                snapshot = service.snapshot(job_id=job_id)
                if snapshot["job"].get("status") == "done":
                    break
                time.sleep(0.05)
        finally:
            payip_batch_module.PAYIP_CHARGE_RETRY_DELAY_SECONDS = previous_delay

        snapshot = service.snapshot(job_id=job_id)
        self.assertEqual(snapshot["job"]["success"], 1)
        self.assertEqual(len(payip.create_charge_calls), 1)
        self.assertEqual(snapshot["job"]["results"][0]["payment_id"], "created-payment-1")

    def test_promax_import_validation_returns_missing_clients(self) -> None:
        class MissingClientPayipService(StubPayipPaymentsService):
            def validate_promax_import_batch(self, **kwargs: object) -> object:
                return SimpleNamespace(
                    raw={"details": {"codes_client": ["19167"]}},
                    filial=str(kwargs.get("filial") or ""),
                    company_id="company-3",
                    date_start=str(kwargs.get("date_start") or ""),
                    date_end=str(kwargs.get("date_end") or ""),
                    items=(),
                    missing_client_codes=("19167",),
                    ok=False,
                )

        service = self.make_service(MissingClientPayipService())
        payload = SimpleNamespace(filial="3", start_date="2026-07-07", end_date="2026-07-07", auto_create_clients=False)

        result = service.validate_promax_import(payload, {"is_admin": True})

        self.assertEqual(result["missing_client_codes"], ["19167"])
        self.assertFalse(result["ok"])

    def test_promax_import_validation_uses_mfa_when_payip_requests_it(self) -> None:
        payip = StubPayipPaymentsService(require_mfa_once=True)
        service = self.make_service(payip)
        payload = SimpleNamespace(
            filial="3",
            start_date="2026-07-07",
            end_date="2026-07-07",
            mfa_code="123456",
            auto_create_clients=False,
        )

        result = service.validate_promax_import(payload, {"is_admin": True})

        self.assertEqual(result["items_count"], 1)
        self.assertEqual(payip.bootstrap_calls, ["123456"])

    def test_promax_import_validation_auto_creates_missing_clients_from_dclientes(self) -> None:
        class MissingThenOkPayipService(StubPayipPaymentsService):
            def validate_promax_import_batch(self, **kwargs: object) -> object:
                self.import_batch_calls.append(dict(kwargs))
                if not self.create_client_calls:
                    return SimpleNamespace(
                        raw={"details": {"codes_client": ["19167"]}},
                        filial=str(kwargs.get("filial") or ""),
                        company_id="company-3",
                        date_start=str(kwargs.get("date_start") or ""),
                        date_end=str(kwargs.get("date_end") or ""),
                        items=(),
                        missing_client_codes=("19167",),
                        ok=False,
                    )
                return super().validate_promax_import_batch(**kwargs)

        profile = SimpleNamespace(
            filial="3",
            cod_pdv="19167",
            documento="12467128490",
            razao_social="JHEFFERSON KAUA",
            nome_fantasia="Kaua",
            email="",
            telefone="",
            cep="58706560",
            endereco="Rua Professora Cristina Lima",
            numero="SN",
            complemento="",
            bairro="Salgadinho",
            cidade="Patos",
            uf="PB",
        )
        payip = MissingThenOkPayipService()
        query = StubQueryService(payip_profile=profile)
        service = self.make_service(payip, dclientes_query_service=query)
        payload = SimpleNamespace(filial="3", start_date="2026-07-07", end_date="2026-07-07", auto_create_clients=True)

        result = service.validate_promax_import(payload, {"is_admin": True})

        self.assertEqual(result["missing_client_codes"], [])
        self.assertEqual(result["client_creation"]["created"], ["19167"])
        self.assertEqual(query.payip_profile_calls[-1], {"filial": "3", "cod_pdv": "19167"})
        self.assertGreaterEqual(len(payip.import_batch_calls), 2)


if __name__ == "__main__":
    unittest.main()
