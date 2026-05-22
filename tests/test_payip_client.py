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
