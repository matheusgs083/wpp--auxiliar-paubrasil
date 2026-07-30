from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

import httpx

from bot_api.integrations import payip_client
from bot_api.integrations.payip_client import PayipClient, PayipConfig, PayipImportClientsNotFound, PayipTokenManager, TokenPair, summarize_collection_response
from bot_api.services.payip_payments_service import (
    PayipPaymentsService,
    _build_pix_charge_payload,
    _normalize_payip_external_id,
)


class PayipClientTests(unittest.TestCase):
    def test_payip_config_maps_filial_to_company_id_with_patos_fallback(self) -> None:
        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("4", "sume-company"),),
        )

        self.assertTrue(config.enabled)
        self.assertEqual(
            config.company_map(),
            {
                "3": "patos-company",
                "4": "sume-company",
            },
        )

    def test_parse_tokens_preserves_auth_payload_metadata(self) -> None:
        payload = {
            "access_token": "access.test.token",
            "expires_in": 3600,
            "refresh_expires_in": 21600,
            "refresh_token": "refresh.test.token",
            "token_type": "Bearer",
            "not-before-policy": 0,
            "session_state": "b28c1415-9cc3-4e50-870c-d4587e821f69",
            "scope": "profile email",
        }

        tokens = PayipTokenManager._parse_tokens(payload)

        self.assertEqual(tokens.access_token, "access.test.token")
        self.assertEqual(tokens.refresh_token, "refresh.test.token")
        self.assertEqual(tokens.expires_in, 3600)
        self.assertEqual(tokens.refresh_expires_in, 21600)
        self.assertEqual(tokens.token_type, "Bearer")
        self.assertEqual(tokens.not_before_policy, 0)
        self.assertEqual(tokens.session_state, "b28c1415-9cc3-4e50-870c-d4587e821f69")
        self.assertEqual(tokens.scope, "profile email")
        self.assertEqual(tokens.to_cache_payload()["not-before-policy"], 0)

    def test_summarize_collection_response_detects_common_payment_shapes(self) -> None:
        self.assertEqual(
            summarize_collection_response(
                {"data": [{"id": "1"}, {"id": "2"}], "total": 10, "page": 1, "pageSize": 50}
            ),
            {
                "items_count": 2,
                "total_items": 10,
                "page": 1,
                "page_size": 50,
            },
        )

        self.assertEqual(
            summarize_collection_response([{"id": "1"}]),
            {
                "items_count": 1,
                "total_items": None,
                "page": None,
                "page_size": None,
            },
        )

    def test_pix_charge_payload_generates_valid_external_id_when_nb_is_empty(self) -> None:
        payload = _build_pix_charge_payload(
            amount=Decimal("0.99"),
            rate_amount=Decimal("3.92"),
            interest_perc=Decimal("10"),
            tax_payer_id="15954335460",
            external_id="",
            invoice="",
            company_tax_id="20983885000101",
            due_date=date(2026, 5, 7),
            issue_date=date(2026, 5, 6),
            title="Fatura revenda Pau Brasil - Patos",
            description="Fatura revenda Pau Brasil - Patos",
        )

        self.assertRegex(payload["externalId"], r"^BOT-[a-f0-9-]{36}$")
        self.assertLessEqual(len(payload["externalId"]), 60)

    def test_normalize_payip_external_id_keeps_api_contract(self) -> None:
        self.assertEqual(_normalize_payip_external_id("17"), "NB-17")
        self.assertEqual(_normalize_payip_external_id("abc_123"), "abc-123")
        self.assertEqual(_normalize_payip_external_id("142541"), "142541")
        self.assertEqual(len(_normalize_payip_external_id("A" * 90)), 60)

    def test_statement_resume_service_preserves_request_metadata(self) -> None:
        class FakePayipClient:
            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or {"4": "sume-company"}.get(filial, "patos-company")

            def statement_movements_resume(
                self,
                *,
                filial: str = "",
                company_id: str = "",
                date_start: str,
                date_end: str,
            ) -> dict:
                return {"balance": 10}

        service = PayipPaymentsService(FakePayipClient())  # type: ignore[arg-type]

        resume = service.statement_movements_resume(
            filial="4",
            date_start=date(2026, 5, 1),
            date_end=date(2026, 5, 8),
        )

        self.assertEqual(resume.filial, "4")
        self.assertEqual(resume.company_id, "sume-company")
        self.assertEqual(resume.date_start, "2026-05-01")
        self.assertEqual(resume.date_end, "2026-05-08")
        self.assertEqual(resume.raw, {"balance": 10})

    def test_service_searches_paid_day_and_filters_paid_amount_with_tolerance(self) -> None:
        class FakePayipClient:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or {"4": "sume-company"}.get(filial, "patos-company")

            def list_payments(self, **kwargs) -> dict:
                self.calls.append(kwargs)
                return {
                    "data": [
                        {"id": "pay-1", "amount": 9.99, "amountPaid": 0.99, "paidDate": "2026-04-13T12:00:00.000Z"},
                        {"id": "pay-2", "amount": 0.99, "amountPaid": 1.99, "paidDate": "2026-04-13T13:00:00.000Z"},
                        {"id": "pay-near", "amount": 9.99, "amountPaid": 1.04, "paidDate": "2026-04-13T13:30:00.000Z"},
                        {
                            "id": "pay-3",
                            "amount": 0.01,
                            "amountDetails": {"amountPaid": 0.99},
                            "paidDate": "2026-04-13T14:00:00.000Z",
                        },
                    ],
                    "total": 4,
                    "page": 1,
                    "pageSize": 100,
                }

        client = FakePayipClient()
        service = PayipPaymentsService(client)  # type: ignore[arg-type]

        page = service.find_payments_by_amount_and_paid_date(
            filial="4",
            amount=Decimal("0.99"),
            day=date(2026, 4, 13),
        )

        self.assertEqual([item["id"] for item in page.items], ["pay-1", "pay-near", "pay-3"])
        self.assertEqual(page.raw["tolerance"], "0.05")
        self.assertEqual(page.raw["paid_date"], "2026-04-13")
        self.assertEqual(page.company_id, "sume-company")
        self.assertEqual(
            client.calls[-1],
            {
                "page": 1,
                "page_size": 100,
                "status": "",
                "paid_date_start": "2026-04-13",
                "paid_date_end": "2026-04-13",
                "filial": "4",
                "company_id": "sume-company",
            },
        )

    def test_service_allows_custom_amount_tolerance(self) -> None:
        class FakePayipClient:
            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or "patos-company"

            def list_payments(self, **kwargs) -> dict:
                return {
                    "data": [
                        {"id": "pay-near", "amountPaid": 10.09, "paidDate": "2026-04-13T12:00:00.000Z"},
                        {"id": "pay-far", "amountPaid": 10.11, "paidDate": "2026-04-13T12:00:00.000Z"},
                    ],
                    "total": 2,
                    "page": 1,
                    "pageSize": 100,
                }

        service = PayipPaymentsService(FakePayipClient())  # type: ignore[arg-type]

        page = service.find_payments_by_amount_and_paid_date(
            filial="3",
            amount=Decimal("10.00"),
            day=date(2026, 4, 13),
            tolerance=Decimal("0.10"),
        )

        self.assertEqual([item["id"] for item in page.items], ["pay-near"])
        self.assertEqual(page.raw["tolerance"], "0.10")

    def test_service_validate_promax_import_batch_returns_items(self) -> None:
        class FakePayipClient:
            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or "patos-company"

            def validate_promax_payments_import_batch(self, **kwargs) -> dict:
                return {
                    "success": True,
                    "data": [
                        {
                            "clientCode": "19167",
                            "invoice": "181886",
                            "total": 20,
                            "dueDate": "2026-07-07T00:00:00",
                        }
                    ],
                    "request": kwargs,
                }

        service = PayipPaymentsService(FakePayipClient())  # type: ignore[arg-type]

        validation = service.validate_promax_import_batch(
            filial="3",
            date_start=date(2026, 7, 7),
            date_end=date(2026, 7, 7),
        )

        self.assertTrue(validation.ok)
        self.assertEqual(validation.company_id, "patos-company")
        self.assertEqual(validation.date_start, "2026-07-07")
        self.assertEqual(validation.date_end, "2026-07-07")
        self.assertEqual(validation.items[0]["invoice"], "181886")

    def test_service_validate_promax_import_batch_keeps_missing_client_codes(self) -> None:
        class FakePayipClient:
            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or "patos-company"

            def validate_promax_payments_import_batch(self, **_kwargs) -> dict:
                raise PayipImportClientsNotFound(
                    "Cliente nao encontrado",
                    codes_client=("19167",),
                    payload={"details": {"codes_client": ["19167"]}},
                )

        service = PayipPaymentsService(FakePayipClient())  # type: ignore[arg-type]

        validation = service.validate_promax_import_batch(
            filial="3",
            date_start="2026-07-07",
            date_end="2026-07-07",
        )

        self.assertFalse(validation.ok)
        self.assertEqual(validation.missing_client_codes, ("19167",))

    def test_service_import_promax_batch_returns_items(self) -> None:
        class FakePayipClient:
            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or "patos-company"

            def import_promax_payments_batch(self, **kwargs) -> dict:
                return {
                    "success": True,
                    "data": [
                        {
                            "clientCode": "19167",
                            "invoice": "181886",
                            "total": 20,
                            "dueDate": "2026-07-07T00:00:00",
                        }
                    ],
                    "request": kwargs,
                }

        service = PayipPaymentsService(FakePayipClient())  # type: ignore[arg-type]

        result = service.import_promax_batch(
            filial="3",
            date_start=date(2026, 7, 7),
            date_end=date(2026, 7, 7),
            totp_code="422649",
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.company_id, "patos-company")
        self.assertEqual(result.date_start, "2026-07-07")
        self.assertEqual(result.date_end, "2026-07-07")
        self.assertEqual(result.items[0]["invoice"], "181886")

    def test_service_create_client_from_profile_builds_payload(self) -> None:
        class FakePayipClient:
            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or "patos-company"

            def verify_client_tax_payer(self, *, tax_payer_id: str) -> dict:
                return {"verified": tax_payer_id}

            def create_client(self, payload: dict) -> dict:
                return {"id": "client-company-1", "payload": payload}

        service = PayipPaymentsService(FakePayipClient())  # type: ignore[arg-type]
        profile = type(
            "Profile",
            (),
            {
                "filial": "3",
                "cod_pdv": "19167",
                "documento": "12467128490",
                "razao_social": "JHEFFERSON KAUA",
                "nome_fantasia": "Kaua",
                "email": "",
                "telefone": "",
                "cep": "58706560",
                "endereco": "Rua Professora Cristina Lima",
                "numero": "SN",
                "complemento": "",
                "bairro": "Salgadinho",
                "cidade": "Patos",
                "uf": "PB",
            },
        )()

        result = service.create_client_from_profile(profile=profile)

        self.assertEqual(result.payload["companyId"], "patos-company")
        self.assertEqual(result.payload["client"]["taxPayerId"], "12467128490")
        self.assertEqual(result.payload["client"]["code"], "19167")
        self.assertEqual(result.payload["client"]["type"], "PF")
        self.assertEqual(result.payload["client"]["email"], "cliente.3.19167@sememail.com.br")
        self.assertEqual(result.payload["client"]["phone"], "83990000000")
        self.assertEqual(result.payload["address"]["number"], "SN")

    def test_service_reads_all_pages_before_filtering_paid_day_and_amount(self) -> None:
        class FakePayipClient:
            def __init__(self) -> None:
                self.pages: list[int] = []

            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or "patos-company"

            def list_payments(self, **kwargs) -> dict:
                page = kwargs["page"]
                self.pages.append(page)
                items = {
                    1: [
                        {"id": "pay-1", "amountPaid": 10.00, "paidDate": "2026-04-13T12:00:00.000Z"},
                        {"id": "pay-2", "amountPaid": 20.00, "paidDate": "2026-04-13T12:00:00.000Z"},
                    ],
                    2: [
                        {"id": "pay-3", "amountPaid": 10.03, "paidDate": "2026-04-13T13:00:00.000Z"},
                    ],
                }[page]
                return {"data": items, "total": 3, "page": page, "pageSize": 2}

        client = FakePayipClient()
        service = PayipPaymentsService(client)  # type: ignore[arg-type]

        page = service.find_payments_by_amount_and_paid_date(
            filial="3",
            amount=Decimal("10.00"),
            day=date(2026, 4, 13),
            page_size=2,
        )

        self.assertEqual(client.pages, [1, 2])
        self.assertEqual([item["id"] for item in page.items], ["pay-1", "pay-3"])

    def test_service_compares_paid_date_in_fortaleza_timezone(self) -> None:
        class FakePayipClient:
            def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
                return company_id or "patos-company"

            def list_payments(self, **kwargs) -> dict:
                return {
                    "data": [
                        {"id": "pay-local-day", "amountPaid": 10.00, "paidDate": "2026-04-14T01:00:00.000Z"},
                        {"id": "pay-next-day", "amountPaid": 10.00, "paidDate": "2026-04-14T04:00:00.000Z"},
                    ],
                    "total": 2,
                    "page": 1,
                    "pageSize": 100,
                }

        service = PayipPaymentsService(FakePayipClient())  # type: ignore[arg-type]

        page = service.find_payments_by_amount_and_paid_date(
            filial="3",
            amount=Decimal("10.00"),
            day=date(2026, 4, 13),
        )

        self.assertEqual([item["id"] for item in page.items], ["pay-local-day"])

    def test_payments_endpoint_sends_paid_date_period(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"data": [], "total": 0, "page": 1, "pageSize": 100})

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("4", "sume-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=httpx.MockTransport(handler),
        )
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        client.list_payments(
            filial="4",
            page=1,
            page_size=100,
            paid_date_start="2026-04-13",
            paid_date_end="2026-04-13",
        )

        self.assertEqual(requests[0].url.path, "/v1/payments")
        self.assertEqual(requests[0].url.params["companyId"], "sume-company")
        self.assertEqual(requests[0].url.params["paidDateStart"], "2026-04-13")
        self.assertEqual(requests[0].url.params["paidDateEnd"], "2026-04-13")
        self.assertNotIn("createdAtStart", requests[0].url.params)

    def test_statement_endpoints_use_three_distinct_routes_with_same_params(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/resume/sume-company"):
                return httpx.Response(200, json={"balance": 10})
            return httpx.Response(200, content=b"file")

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("4", "sume-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=httpx.MockTransport(handler),
        )
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        client.statement_movements_resume(
            filial="4",
            date_start="2026-05-01",
            date_end="2026-05-08",
        )
        client.statement_movements_export(
            file_format="pdf",
            filial="4",
            date_start="2026-05-01",
            date_end="2026-05-08",
        )
        client.statement_movements_export(
            file_format="xlsx",
            filial="4",
            date_start="2026-05-01",
            date_end="2026-05-08",
        )

        self.assertEqual(
            [request.url.path for request in requests],
            [
                "/v1/statments/movements/resume/sume-company",
                "/v1/statments/movements/export/pdf/sume-company",
                "/v1/statments/movements/export/xlsx/sume-company",
            ],
        )
        for request in requests:
            self.assertEqual(request.url.params["dateStart"], "2026-05-01")
            self.assertEqual(request.url.params["dateEnd"], "2026-05-08")
        self.assertEqual(requests[1].headers["accept"], "application/pdf")
        self.assertEqual(
            requests[2].headers["accept"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_invoice_batch_process_generates_then_downloads_zip(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/v1/payments/invoices/batch/process":
                return httpx.Response(200, json={"data": {"downloadUrl": "https://s3.example.test/downloads/payip-lote.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256"}})
            if request.url.path == "/v1/batchs/batch-1/pdf/sume-company":
                return httpx.Response(200, json={"data": {"url": "https://s3.example.test/downloads/payip-lote.zip?X-Amz-Algorithm=AWS4-HMAC-SHA256"}})
            if request.url.path == "/downloads/payip-lote.zip":
                self.assertNotIn("authorization", request.headers)
                return httpx.Response(200, content=b"PK\x03\x04zip-content", headers={"content-type": "application/zip"})
            return httpx.Response(404, json={"message": "not found"})

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("4", "sume-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        file_bytes, media_type = client.invoice_batch_process_file(
            filial="4",
            company_id="",
            batch_id="batch-1",
            payment_shape="shape-1",
            payment_method="method-1",
        )

        self.assertEqual(file_bytes, b"PK\x03\x04zip-content")
        self.assertEqual(media_type, "application/zip")
        self.assertEqual([request.method for request in requests], ["POST", "GET", "GET"])
        self.assertEqual(requests[0].url.path, "/v1/payments/invoices/batch/process")
        self.assertEqual(requests[0].url.params["sortInvoice"], "asc")
        self.assertEqual(requests[0].headers["accept"], "application/zip, application/octet-stream, application/pdf, */*")
        self.assertEqual(requests[1].url.path, "/v1/batchs/batch-1/pdf/sume-company")
        self.assertEqual(requests[2].url.path, "/downloads/payip-lote.zip")
        self.assertNotIn("authorization", requests[2].headers)

    def test_invoice_batch_process_downloads_from_batch_pdf_when_generation_is_in_progress(self) -> None:
        requests: list[httpx.Request] = []
        pdf_attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal pdf_attempts
            requests.append(request)
            if request.url.path == "/v1/payments/invoices/batch/process":
                return httpx.Response(200, json={"status": "Sucesso", "message": "Criacao do arquivo pdf em progresso"})
            if request.url.path == "/v1/batchs/batch-1/pdf/sume-company":
                pdf_attempts += 1
                if pdf_attempts == 1:
                    return httpx.Response(200, json={"status": "Sucesso", "message": "Criacao do arquivo pdf em progresso"})
                return httpx.Response(200, json={"data": {"url": "https://s3.example.test/downloads/payip-lote.zip?X-Amz-Signature=abc"}})
            if request.url.path == "/downloads/payip-lote.zip":
                self.assertNotIn("authorization", request.headers)
                return httpx.Response(200, content=b"PK\x03\x04zip-content", headers={"content-type": "application/zip"})
            return httpx.Response(404, json={"message": "not found"})

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("4", "sume-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        original_retry_seconds = payip_client.PAYIP_BATCH_DOWNLOAD_RETRY_SECONDS
        payip_client.PAYIP_BATCH_DOWNLOAD_RETRY_SECONDS = 0
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        try:
            file_bytes, media_type = client.invoice_batch_process_file(
                filial="4",
                company_id="",
                batch_id="batch-1",
                payment_shape="shape-1",
                payment_method="method-1",
            )
        finally:
            payip_client.PAYIP_BATCH_DOWNLOAD_RETRY_SECONDS = original_retry_seconds

        self.assertEqual(file_bytes, b"PK\x03\x04zip-content")
        self.assertEqual(media_type, "application/zip")
        self.assertEqual([request.method for request in requests], ["POST", "GET", "GET", "GET"])
        self.assertEqual(requests[1].url.path, "/v1/batchs/batch-1/pdf/sume-company")
        self.assertEqual(requests[2].url.path, "/v1/batchs/batch-1/pdf/sume-company")
        self.assertEqual(requests[3].url.path, "/downloads/payip-lote.zip")
        self.assertNotIn("authorization", requests[3].headers)

    def test_invoice_batch_process_omits_payment_method_when_all_methods_selected(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"status": "Sucesso"})

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("4", "sume-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        client.invoice_batch_process(
            filial="4",
            company_id="",
            batch_id="batch-1",
            payment_shape="shape-1",
            payment_method="",
            sort_invoice="desc",
        )

        payload = json.loads(requests[0].content.decode("utf-8"))
        self.assertEqual(payload["paymentShape"], "shape-1")
        self.assertEqual(payload["sortInvoice"], "desc")
        self.assertNotIn("paymentMethod", payload)

    def test_list_payment_batches_uses_batchs_endpoint(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "batch-1",
                            "type": "CREATE-PAYMENT",
                            "status": "DONE",
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "pageSize": 50,
                },
            )

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("4", "sume-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        data = client.list_payment_batches(filial="4", page=1, page_size=50)

        self.assertEqual(data["data"][0]["id"], "batch-1")
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].url.path, "/v1/batchs/sume-company")
        self.assertEqual(requests[0].url.params["type"], "CREATE-PAYMENT")
        self.assertEqual(requests[0].url.params["page"], "1")
        self.assertEqual(requests[0].url.params["pageSize"], "50")

    def test_promax_import_validate_batch_uses_company_route_and_dates(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "clientCode": "19167",
                            "invoice": "181886",
                            "total": 20,
                            "dueDate": "2026-07-07T00:00:00",
                        }
                    ],
                },
            )

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("3", "patos-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        payload = client.validate_promax_payments_import_batch(
            filial="3",
            date_start="2026-07-07",
            date_end="2026-07-07",
        )

        self.assertTrue(payload["success"])
        self.assertEqual(requests[0].method, "POST")
        self.assertEqual(requests[0].url.path, "/v1/payments-import/patos-company/promax/api/validate-batch")
        self.assertEqual(requests[0].url.params["startDate"], "2026-07-07")
        self.assertEqual(requests[0].url.params["endDate"], "2026-07-07")

    def test_routes_uses_company_route_and_in_progress_status(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "route-1",
                            "code": "92305",
                            "status": "IN_PROGRESS",
                            "driversRoute": [{"driver": {"name": "Jose Marcelo", "code": "7444"}}],
                        }
                    ]
                },
            )

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("3", "patos-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        payload = client.list_routes(filial="3", status="IN_PROGRESS", page=1, page_size=25)

        self.assertEqual(payload["data"][0]["code"], "92305")
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].url.path, "/v1/routes/patos-company")
        self.assertEqual(requests[0].url.params["status"], "IN_PROGRESS")
        self.assertEqual(requests[0].url.params["page"], "1")
        self.assertEqual(requests[0].url.params["pageSize"], "25")
        self.assertEqual(requests[0].url.params["code"], "")

    def test_promax_import_validate_batch_extracts_missing_client_codes(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "message": "Cliente não encontrado",
                    "error": "NOT_FOUND",
                    "statusCode": 404,
                    "code": "CLI404",
                    "details": {"codes_client": ["19167", "19167", "20001"]},
                },
            )

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        with self.assertRaises(PayipImportClientsNotFound) as raised:
            client.validate_promax_payments_import_batch(
                filial="3",
                date_start="2026-07-07",
                date_end="2026-07-07",
            )

        self.assertEqual(raised.exception.codes_client, ("19167", "20001"))

    def test_promax_import_batch_uses_company_route_dates_and_totp(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "clientCode": "19167",
                            "invoice": "181886",
                            "total": 20,
                            "dueDate": "2026-07-07T00:00:00",
                        }
                    ],
                },
            )

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
            company_ids=(("3", "patos-company"),),
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]

        payload = client.import_promax_payments_batch(
            filial="3",
            date_start="2026-07-07",
            date_end="2026-07-07",
            totp_code="422649",
        )

        self.assertTrue(payload["success"])
        self.assertEqual(requests[0].method, "POST")
        self.assertEqual(requests[0].url.path, "/v1/payments-import/patos-company/promax/api")
        self.assertEqual(requests[0].url.params["totpCode"], "422649")
        self.assertEqual(requests[0].url.params["startDate"], "2026-07-07")
        self.assertEqual(requests[0].url.params["endDate"], "2026-07-07")

    def test_create_client_verifies_document_and_posts_payload(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/v1/clients/verify/12467128490":
                return httpx.Response(200, json={"valid": True})
            if request.url.path == "/v1/clients":
                return httpx.Response(201, json={"id": "client-company-1"})
            return httpx.Response(404, json={"message": "not found"})

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]
        payload = {
            "companyId": "patos-company",
            "client": {"taxPayerId": "12467128490", "name": "Cliente", "code": "19167"},
            "address": {"city": "Patos"},
        }

        verified = client.verify_client_tax_payer(tax_payer_id="124.671.284-90")
        created = client.create_client(payload)

        self.assertTrue(verified["valid"])
        self.assertEqual(created["id"], "client-company-1")
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[0].url.path, "/v1/clients/verify/12467128490")
        self.assertEqual(requests[1].method, "POST")
        self.assertEqual(requests[1].url.path, "/v1/clients")

    def test_create_client_continues_when_verify_returns_not_found(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/v1/clients/verify/12467128490":
                return httpx.Response(404, json={"message": "Cliente nao encontrado"})
            if request.url.path == "/v1/clients":
                return httpx.Response(201, json={"id": "client-company-1"})
            return httpx.Response(404, json={"message": "not found"})

        config = PayipConfig(
            base_url="https://api.example.test",
            client_id="client",
            username="user",
            password="password",
            company_id="patos-company",
            token_cache_file="tokens.json",
        )
        client = PayipClient(config)
        client._client.close()
        client._client = httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(handler))
        token = TokenPair(
            access_token="access",
            refresh_token="refresh",
            access_expires_at=9999999999,
            refresh_expires_at=9999999999,
            expires_in=3600,
            refresh_expires_in=21600,
        )
        client.tokens.ensure_access_token = lambda _http_client: token  # type: ignore[method-assign]
        service = PayipPaymentsService(client)
        profile = type(
            "Profile",
            (),
            {
                "filial": "3",
                "cod_pdv": "19167",
                "documento": "12467128490",
                "razao_social": "JHEFFERSON KAUA",
                "nome_fantasia": "Kaua",
                "email": "",
                "telefone": "",
                "cep": "58706560",
                "endereco": "Rua Professora Cristina Lima",
                "numero": "SN",
                "complemento": "",
                "bairro": "Salgadinho",
                "cidade": "Patos",
                "uf": "PB",
            },
        )()

        result = service.create_client_from_profile(profile=profile)

        self.assertEqual(result.verify_raw["found"], False)
        self.assertEqual(result.raw["id"], "client-company-1")
        self.assertEqual(requests[0].method, "GET")
        self.assertEqual(requests[1].method, "POST")


if __name__ == "__main__":
    unittest.main()
