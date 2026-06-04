from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

import httpx

from bot_api.integrations.payip_client import PayipClient, PayipConfig, PayipTokenManager, TokenPair, summarize_collection_response
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


if __name__ == "__main__":
    unittest.main()
