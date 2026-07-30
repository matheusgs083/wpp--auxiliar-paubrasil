from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.security.access_control import AccessControl, AccessDecision
from bot_api.integrations.payip_client import PayipError, PayipMfaRequired
from bot_api.services.customer_lookup_flow import CustomerLookupFlow
from bot_api.services.critica_rn_query_service import (
    CRITICA_PDF_CURRENT_IMPORT_MESSAGE,
    CriticaPdfCurrentImportRequiredError,
    CriticaRnRecord,
    CriticaRnSummary,
)
from bot_api.services.recolha_request_service import RecolhaRequestService


class StubStatusService:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready

    def status(self) -> dict[str, Any]:
        return {"ready": self.ready}


class StubQueryService(StubStatusService):
    def __init__(
        self,
        *,
        ready: bool = True,
        visit_days: list[str] | None = None,
        fantasia_records: list[Any] | None = None,
        registration_records: list[Any] | None = None,
        document_records: list[Any] | None = None,
        payip_profile: Any | None = None,
        visit_day_clients: list[Any] | None = None,
        visit_day_sellers: list[Any] | None = None,
        scope_summary: Any | None = None,
        gv_vdes: list[str] | None = None,
    ) -> None:
        super().__init__(ready=ready)
        self.visit_days = list(visit_days or [])
        self.fantasia_records = list(fantasia_records or [])
        self.registration_records = list(registration_records or [])
        self.document_records = list(document_records or [])
        self.payip_profile = payip_profile
        self.visit_day_clients = list(visit_day_clients or [])
        self.visit_day_sellers = list(visit_day_sellers or [])
        self.scope_summary = scope_summary or SimpleNamespace(
            client_count=0,
            seller_count=0,
            planilha_atualizada_em="",
        )
        self.gv_vdes = list(gv_vdes or [])
        self.visit_days_calls: list[dict[str, Any]] = []
        self.fantasia_calls: list[dict[str, Any]] = []
        self.registration_calls: list[dict[str, Any]] = []
        self.document_calls: list[dict[str, Any]] = []
        self.payip_profile_calls: list[dict[str, Any]] = []
        self.visit_day_clients_calls: list[dict[str, Any]] = []
        self.visit_day_sellers_calls: list[dict[str, Any]] = []
        self.scope_summary_calls: list[dict[str, Any]] = []
        self.gv_vdes_calls: list[dict[str, Any]] = []

    def list_visit_days(self, **kwargs: Any) -> list[str]:
        self.visit_days_calls.append(kwargs)
        return list(self.visit_days)

    def search_by_fantasia(self, **kwargs: Any) -> list[Any]:
        self.fantasia_calls.append(kwargs)
        return list(self.fantasia_records)

    def search_by_registration(self, **kwargs: Any) -> list[Any]:
        self.registration_calls.append(kwargs)
        return list(self.registration_records)

    def search_by_document(self, **kwargs: Any) -> list[Any]:
        self.document_calls.append(kwargs)
        return list(self.document_records)

    def get_payip_profile_by_registration(self, filial: str, cod_pdv: str) -> Any:
        self.payip_profile_calls.append({"filial": filial, "cod_pdv": cod_pdv})
        return self.payip_profile

    def list_clients_by_visit_day(self, **kwargs: Any) -> list[Any]:
        self.visit_day_clients_calls.append(kwargs)
        return list(self.visit_day_clients)

    def list_visit_day_clients(self, **kwargs: Any) -> list[Any]:
        self.visit_day_clients_calls.append(kwargs)
        return list(self.visit_day_clients)

    def list_visit_day_seller_summaries(self, **kwargs: Any) -> list[Any]:
        self.visit_day_sellers_calls.append(kwargs)
        return list(self.visit_day_sellers)

    def list_clients_by_visit_day_and_seller(self, **kwargs: Any) -> list[Any]:
        self.visit_day_clients_calls.append(kwargs)
        seller_code = str(kwargs.get("seller_code") or "").strip()
        if not seller_code:
            return list(self.visit_day_clients)
        return [
            record
            for record in self.visit_day_clients
            if f"{str(getattr(record, 'filial', '') or '').strip()}_{str(getattr(record, 'vendedor', '') or '').strip()}" == seller_code
        ]

    def get_scope_summary(self, **kwargs: Any) -> Any:
        self.scope_summary_calls.append(kwargs)
        return self.scope_summary

    def list_gv_vdes(self, **kwargs: Any) -> list[str]:
        self.gv_vdes_calls.append(kwargs)
        return list(self.gv_vdes)


class StubInadimplenciaService(StubStatusService):
    def __init__(
        self,
        *,
        ready: bool = True,
        name_summaries: list[Any] | None = None,
        client_summaries_in_scope: list[Any] | None = None,
        search_records: list[Any] | None = None,
        upcoming_alerts: list[Any] | None = None,
        finance_summary: Any | None = None,
        finance_summaries_by_filial: list[Any] | None = None,
        finance_summaries_by_gv: list[Any] | None = None,
    ) -> None:
        super().__init__(ready=ready)
        self.name_summaries = list(name_summaries or [])
        self.client_summaries_in_scope = list(client_summaries_in_scope or [])
        self.search_records = list(search_records or [])
        self.upcoming_alerts = list(upcoming_alerts or [])
        self.finance_summary = finance_summary or SimpleNamespace(
            client_count=0,
            total_pendente="0,00",
            due_in_two_days_count=0,
            due_in_two_days_total="0,00",
            due_tomorrow_count=0,
            due_tomorrow_total="0,00",
            due_today_count=0,
            due_today_total="0,00",
            overdue_count=0,
            overdue_total="0,00",
            planilha_atualizada_em="",
        )
        self.finance_summaries_by_filial = list(finance_summaries_by_filial or [])
        self.finance_summaries_by_gv = list(finance_summaries_by_gv or [])
        self.name_calls: list[dict[str, Any]] = []
        self.client_summaries_in_scope_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.upcoming_calls: list[dict[str, Any]] = []
        self.finance_summary_calls: list[dict[str, Any]] = []
        self.finance_summary_by_filial_calls: list[dict[str, Any]] = []
        self.finance_summary_by_gv_calls: list[dict[str, Any]] = []

    def search_client_summaries_by_name(self, **kwargs: Any) -> list[Any]:
        self.name_calls.append(kwargs)
        return list(self.name_summaries)

    def count_clients_in_scope(self, **kwargs: Any) -> int:
        _ = kwargs
        if self.client_summaries_in_scope:
            return len(self.client_summaries_in_scope)
        if self.name_summaries:
            return len(self.name_summaries)
        return len(self.search_records)

    def list_client_summaries_in_scope(self, **kwargs: Any) -> list[Any]:
        self.client_summaries_in_scope_calls.append(kwargs)
        return list(self.client_summaries_in_scope)

    def search_by_registration(self, **kwargs: Any) -> list[Any]:
        self.search_calls.append(kwargs)
        filial = str(kwargs.get("filial") or "").strip()
        cod_pdv = str(kwargs.get("cod_pdv") or "").strip()
        if not filial and not cod_pdv:
            return list(self.search_records)
        return [
            record
            for record in self.search_records
            if (not filial or str(getattr(record, "filial", "") or "").strip() == filial)
            and (not cod_pdv or str(getattr(record, "cod_pdv", "") or "").strip() == cod_pdv)
        ]

    def list_upcoming_by_visit_day(self, **kwargs: Any) -> list[Any]:
        self.upcoming_calls.append(kwargs)
        return list(self.upcoming_alerts)

    def get_finance_summary(self, **kwargs: Any) -> Any:
        self.finance_summary_calls.append(kwargs)
        return self.finance_summary

    def list_finance_summary_by_filial(self, **kwargs: Any) -> list[Any]:
        self.finance_summary_by_filial_calls.append(kwargs)
        return list(self.finance_summaries_by_filial)

    def list_finance_summary_by_gv(self, **kwargs: Any) -> list[Any]:
        self.finance_summary_by_gv_calls.append(kwargs)
        return list(self.finance_summaries_by_gv)


class StubComodatosService(StubStatusService):
    def __init__(
        self,
        *,
        ready: bool = True,
        search_records: list[Any] | None = None,
    ) -> None:
        super().__init__(ready=ready)
        self.search_records = list(search_records or [])
        self.search_calls: list[dict[str, Any]] = []

    def search_by_registration(self, **kwargs: Any) -> list[Any]:
        self.search_calls.append(kwargs)
        return list(self.search_records)


class StubGiroService(StubStatusService):
    def __init__(
        self,
        *,
        ready: bool = True,
        search_records: list[Any] | None = None,
        scope_summary: Any | None = None,
        visit_day_summary: Any | None = None,
        filial_summaries: list[Any] | None = None,
        gv_summaries: list[Any] | None = None,
        seller_summaries: list[Any] | None = None,
        zero_base_records: list[Any] | None = None,
    ) -> None:
        super().__init__(ready=ready)
        self.search_records = list(search_records or [])
        self.scope_summary = scope_summary
        self.visit_day_summary = visit_day_summary or scope_summary
        self.filial_summaries = list(filial_summaries or [])
        self.gv_summaries = list(gv_summaries or [])
        self.seller_summaries = list(seller_summaries or [])
        self.zero_base_records = list(zero_base_records or [])
        self.search_calls: list[dict[str, Any]] = []
        self.scope_summary_calls: list[dict[str, Any]] = []
        self.visit_day_summary_calls: list[dict[str, Any]] = []
        self.filial_summary_calls: list[dict[str, Any]] = []
        self.gv_summary_calls: list[dict[str, Any]] = []
        self.seller_summary_calls: list[dict[str, Any]] = []
        self.zero_base_calls: list[dict[str, Any]] = []

    def search_by_registration(self, **kwargs: Any) -> list[Any]:
        self.search_calls.append(kwargs)
        filial = str(kwargs.get("filial") or "").strip()
        cod_pdv = str(kwargs.get("cod_pdv") or "").strip()
        if not filial and not cod_pdv:
            return list(self.search_records)
        return [
            record
            for record in self.search_records
            if (not filial or str(getattr(record, "filial", "") or "").strip() == filial)
            and (not cod_pdv or str(getattr(record, "cod_pdv", "") or "").strip() == cod_pdv)
        ]

    def get_scope_summary(self, **kwargs: Any) -> Any:
        self.scope_summary_calls.append(kwargs)
        return self.scope_summary

    def get_scope_summary_by_visit_day(self, **kwargs: Any) -> Any:
        self.visit_day_summary_calls.append(kwargs)
        return self.visit_day_summary

    def list_summary_by_filial(self, **kwargs: Any) -> list[Any]:
        self.filial_summary_calls.append(kwargs)
        return list(self.filial_summaries)

    def list_summary_by_gv(self, **kwargs: Any) -> list[Any]:
        self.gv_summary_calls.append(kwargs)
        return list(self.gv_summaries)

    def list_summary_by_seller(self, **kwargs: Any) -> list[Any]:
        self.seller_summary_calls.append(kwargs)
        return list(self.seller_summaries)

    def list_giro_zero_base(self, **kwargs: Any) -> list[Any]:
        self.zero_base_calls.append(kwargs)
        return list(self.zero_base_records)


def make_critica_summary(**overrides: Any) -> CriticaRnSummary:
    values: dict[str, Any] = {
        "data_pedido": date(2026, 6, 3),
        "row_count": 3,
        "pedido_count": 2,
        "client_count": 1,
        "problem_row_count": 1,
        "problem_pedido_count": 1,
        "rows_with_critica": 1,
        "duplicated_row_count": 0,
        "price_alert_count": 1,
        "missing_price_count": 0,
        "total_pedido": Decimal("250.00"),
        "planilha_atualizada_em": "2026-06-03",
        "operations": ("Patos",),
    }
    values.update(overrides)
    return CriticaRnSummary(**values)


def make_critica_record(**overrides: Any) -> CriticaRnRecord:
    values: dict[str, Any] = {
        "filial": "3",
        "pedido": "706840",
        "data_pedido": date(2026, 6, 3),
        "operacao": "1",
        "cod_pdv": "18008",
        "nome_pdv": "POSTO PAIZAO",
        "setor": "400",
        "seller_code": "3_400",
        "manager_code": "3_5",
        "status_pedido": "Normal",
        "total_pedido": Decimal("120.00"),
        "total_cliente": Decimal("120.00"),
        "critica_text": "Fora de rota",
        "produto_codigo": "2349",
        "produto_descricao": "GCA PT2 CX6",
        "quantidade": Decimal("2"),
        "unid_venda": "cx",
        "preco_unitario": Decimal("43.20"),
        "preco_sem_adf": Decimal("43.20"),
        "minimo_politica": Decimal("43.20"),
        "tipo_movimento": "51",
        "codigo_gv": "5",
        "codigo_pgv": "2349",
        "pedido_linhas": 2,
        "pedido_produto_linhas": 1,
        "pedido_produto_duplicado": False,
        "produto_encontrado_dprecos": True,
        "preco_status": "preco_caixa_fora_referencia",
        "ttc_min": None,
        "ttc_max": None,
        "caixa_min": Decimal("40.00"),
        "caixa_max": Decimal("42.00"),
        "cond_pag_pedido": "PROMO 21 DIAS",
        "peso_item": Decimal("25.00"),
        "problemas": ("Critica RN: Fora de rota", "Preco caixa fora da DPrecos"),
        "planilha_atualizada_em": "2026-06-03",
        "operation_name": "Patos",
    }
    values.update(overrides)
    return CriticaRnRecord(**values)


class StubCriticaRnService(StubStatusService):
    def __init__(
        self,
        *,
        ready: bool = True,
        summary: CriticaRnSummary | None = None,
        records: list[CriticaRnRecord] | None = None,
        problems: list[CriticaRnRecord] | None = None,
        latest: date | None = None,
        current_import_available: bool = True,
    ) -> None:
        super().__init__(ready=ready)
        self.summary = summary or make_critica_summary()
        self.records = list(records or [make_critica_record()])
        self.problems = list(problems or self.records)
        self.latest = latest if latest is not None else date(2026, 6, 3)
        self.current_import_available = current_import_available
        self.summary_calls: list[dict[str, Any]] = []
        self.problem_calls: list[dict[str, Any]] = []
        self.registration_calls: list[dict[str, Any]] = []
        self.report_calls: list[dict[str, Any]] = []
        self.pdf_report_calls: list[dict[str, Any]] = []
        self.gv_summary_pdf_calls: list[dict[str, Any]] = []
        self.registration_pdf_calls: list[dict[str, Any]] = []
        self.latest_calls: list[dict[str, Any]] = []

    def get_summary(self, **kwargs: Any) -> CriticaRnSummary:
        self.summary_calls.append(kwargs)
        return self.summary

    def list_problems(self, **kwargs: Any) -> list[CriticaRnRecord]:
        self.problem_calls.append(kwargs)
        return list(self.problems)

    def search_by_registration(self, **kwargs: Any) -> list[CriticaRnRecord]:
        self.registration_calls.append(kwargs)
        filial = str(kwargs.get("filial") or "").strip()
        cod_pdv = str(kwargs.get("cod_pdv") or "").strip()
        return [
            record
            for record in self.records
            if (not filial or record.filial == filial) and (not cod_pdv or record.cod_pdv == cod_pdv)
        ]

    def list_report_rows(self, **kwargs: Any) -> list[CriticaRnRecord]:
        self.report_calls.append(kwargs)
        return list(self.records)

    def get_pdf_report(self, **kwargs: Any) -> Any:
        self._raise_if_current_import_missing()
        self.pdf_report_calls.append(kwargs)
        return SimpleNamespace(
            summary=self.summary,
            records=list(self.records),
            pdf_bytes=b"%PDF-critica-detalhe",
            summary_pdf_bytes=b"%PDF-critica-resumo",
        )

    def get_pdf_report_by_registration(self, **kwargs: Any) -> Any:
        self._raise_if_current_import_missing()
        self.registration_pdf_calls.append(kwargs)
        filtered_records = self.search_by_registration(**kwargs)
        summary = self.summary
        if filtered_records:
            summary = replace(
                self.summary,
                row_count=len(filtered_records),
                pedido_count=len({(record.filial, record.pedido) for record in filtered_records}),
            )
        return SimpleNamespace(
            summary=summary,
            records=filtered_records,
            pdf_bytes=b"%PDF-critica-nb",
            summary_pdf_bytes=b"%PDF-critica-resumo",
        )

    def get_gv_summary_pdf(self, **kwargs: Any) -> Any:
        self._raise_if_current_import_missing()
        self.gv_summary_pdf_calls.append(kwargs)
        return SimpleNamespace(
            summary=self.summary,
            records=list(self.records),
            pdf_bytes=b"%PDF-critica-gv-resumo",
            summary_pdf_bytes=b"",
        )

    def latest_date(self, **kwargs: Any) -> date | None:
        self.latest_calls.append(kwargs)
        return self.latest

    def has_current_critica_import(self, **_kwargs: Any) -> bool:
        return self.current_import_available

    def _raise_if_current_import_missing(self) -> None:
        if not self.current_import_available:
            raise CriticaPdfCurrentImportRequiredError(CRITICA_PDF_CURRENT_IMPORT_MESSAGE)


class StubDocumentacaoPendenteService(StubStatusService):
    def __init__(
        self,
        *,
        ready: bool = True,
        search_records: list[Any] | None = None,
        visit_day_summary: Any | None = None,
        pending_by_visit_day: list[Any] | None = None,
        filial_summaries: list[Any] | None = None,
    ) -> None:
        super().__init__(ready=ready)
        self.search_records = list(search_records or [])
        self.visit_day_summary = visit_day_summary or SimpleNamespace(
            monitored_client_count=0,
            pending_client_count=0,
            pending_document_count=0,
            contrato_social_pendentes=0,
            cpf_pendentes=0,
            rg_pendentes=0,
            comprovante_residencia_pendentes=0,
            fachada_pendentes=0,
            ficha_cadastro_pendentes=0,
            planilha_atualizada_em="",
        )
        self.pending_by_visit_day = list(pending_by_visit_day or [])
        self.filial_summaries = list(filial_summaries or [])
        self.search_calls: list[dict[str, Any]] = []
        self.visit_day_summary_calls: list[dict[str, Any]] = []
        self.pending_by_visit_day_calls: list[dict[str, Any]] = []
        self.filial_summary_calls: list[dict[str, Any]] = []

    def search_by_registration(self, **kwargs: Any) -> list[Any]:
        self.search_calls.append(kwargs)
        filial = str(kwargs.get("filial") or "").strip()
        cod_pdv = str(kwargs.get("cod_pdv") or "").strip()
        if not filial and not cod_pdv:
            return list(self.search_records)
        return [
            record
            for record in self.search_records
            if (not filial or str(getattr(record, "filial", "") or "").strip() == filial)
            and (not cod_pdv or str(getattr(record, "cod_pdv", "") or "").strip() == cod_pdv)
        ]

    def get_scope_summary_by_visit_day(self, **kwargs: Any) -> Any:
        self.visit_day_summary_calls.append(kwargs)
        return self.visit_day_summary

    def list_pending_by_visit_day(self, **kwargs: Any) -> list[Any]:
        self.pending_by_visit_day_calls.append(kwargs)
        return list(self.pending_by_visit_day)

    def list_summary_by_filial(self, **kwargs: Any) -> list[Any]:
        self.filial_summary_calls.append(kwargs)
        return list(self.filial_summaries)


class StubPrazoLimiteService(StubStatusService):
    def __init__(
        self,
        *,
        ready: bool = True,
        search_records: list[Any] | None = None,
    ) -> None:
        super().__init__(ready=ready)
        self.search_records = list(search_records or [])
        self.search_calls: list[dict[str, Any]] = []
        self.document_calls: list[dict[str, Any]] = []

    def search_by_registration(self, **kwargs: Any) -> list[Any]:
        self.search_calls.append(kwargs)
        filial = str(kwargs.get("filial") or "").strip()
        cod_pdv = str(kwargs.get("cod_pdv") or "").strip()
        if not filial and not cod_pdv:
            return list(self.search_records)
        return [
            record
            for record in self.search_records
            if (not filial or str(getattr(record, "filial", "") or "").strip() == filial)
            and (not cod_pdv or str(getattr(record, "cod_pdv", "") or "").strip() == cod_pdv)
        ]

    def search_by_document(self, **kwargs: Any) -> list[Any]:
        self.document_calls.append(kwargs)
        document = "".join(char for char in str(kwargs.get("document") or "") if char.isdigit())
        if not document:
            return []
        return [
            record
            for record in self.search_records
            if "".join(char for char in str(getattr(record, "documento", "") or "") if char.isdigit()) == document
        ]


class StubPayipPaymentsService:
    def __init__(
        self,
        *,
        configured: bool = True,
        access_token_valid: bool = True,
        refresh_token_valid: bool = True,
        items_count: int = 2,
        total_items: int = 10,
        require_mfa_once: bool = False,
        client_lookup_error: PayipError | None = None,
        create_charge_error: PayipError | None = None,
    ) -> None:
        self.configured = configured
        self.access_token_valid = access_token_valid
        self.refresh_token_valid = refresh_token_valid
        self.items_count = items_count
        self.total_items = total_items
        self.require_mfa_once = require_mfa_once
        self.client_lookup_error = client_lookup_error
        self.create_charge_error = create_charge_error
        self.status_calls = 0
        self.list_calls: list[dict[str, Any]] = []
        self.client_lookup_calls: list[dict[str, Any]] = []
        self.create_charge_calls: list[dict[str, Any]] = []
        self.get_payment_calls: list[str] = []
        self.invoice_report_calls: list[dict[str, Any]] = []
        self.invoice_batch_process_calls: list[dict[str, Any]] = []
        self.invoice_batch_download_calls: list[dict[str, Any]] = []
        self.statement_resume_calls: list[dict[str, Any]] = []
        self.statement_export_calls: list[dict[str, Any]] = []
        self.amount_day_calls: list[dict[str, Any]] = []
        self.import_batch_calls: list[dict[str, Any]] = []
        self.import_batch_confirm_calls: list[dict[str, Any]] = []
        self.routes_calls: list[dict[str, Any]] = []
        self.create_client_calls: list[dict[str, Any]] = []
        self.bootstrap_calls: list[str] = []

    def status(self) -> dict[str, Any]:
        self.status_calls += 1
        return {
            "configured": self.configured,
            "has_cached_tokens": self.access_token_valid or self.refresh_token_valid,
            "access_token_valid": self.access_token_valid,
            "refresh_token_valid": self.refresh_token_valid,
            "session_state": "test-session",
            "scope": "profile email",
            "company_ids": {
                "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
                "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
            },
            "company_tax_ids": {
                "3": "20983885000101",
            },
        }

    def list_payments(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str = "",
        client_code: str = "",
        invoice: str = "",
        search: str = "",
        due_date_start: str = "",
        due_date_end: str = "",
        paid_date_start: str = "",
        paid_date_end: str = "",
        created_at_start: str = "",
        created_at_end: str = "",
        filial: str = "",
    ) -> Any:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        call = {
            "page": page,
            "page_size": page_size,
            "status": status,
            "client_code": client_code,
            "invoice": invoice,
            "filial": filial,
        }
        if search:
            call["search"] = search
        if due_date_start:
            call["due_date_start"] = due_date_start
        if due_date_end:
            call["due_date_end"] = due_date_end
        if paid_date_start:
            call["paid_date_start"] = paid_date_start
        if paid_date_end:
            call["paid_date_end"] = paid_date_end
        if created_at_start:
            call["created_at_start"] = created_at_start
        if created_at_end:
            call["created_at_end"] = created_at_end
        self.list_calls.append(call)
        items = [
            {
                "id": "pay-1",
                "batchId": "50cb5371-8218-41b3-aab7-1d2f32332ed0",
                "invoice": invoice or "147478",
                "title": "Fatura revenda Pau Brasil - Patos",
                "description": "Fatura revenda Pau Brasil - Patos",
                "status": status or "PENDING",
                "statusPaymentApply": "PENDING",
                "amount": 0.99,
                "amountPaid": 0,
                "dueDate": "2026-04-14T03:00:00.000Z",
                "createdAt": "2026-04-13T22:08:00.000Z",
                "client": {"code": client_code or "12447", "fantasyName": "THIAGO COD", "name": "THIAGO FELIX"},
                "paymentShape": {"name": "PIX"},
                "paymentMethod": {"name": "A vista"},
                "qrCodePixCashin": {
                    "emv": "000201010212PAYIPPIXTESTE1474786304ABCD",
                    "linkImage": "https://example.test/qrcode/147478.png",
                },
            },
            {
                "id": "pay-2",
                "batchId": "50cb5371-8218-41b3-aab7-1d2f32332ed0",
                "invoice": "147479",
                "title": "Fatura revenda Pau Brasil - Patos",
                "description": "Fatura revenda Pau Brasil - Patos",
                "status": status or "PENDING",
                "statusPaymentApply": "PENDING",
                "amount": 1.99,
                "amountPaid": 0,
                "dueDate": "2026-04-15T03:00:00.000Z",
                "createdAt": "2026-04-13T22:09:00.000Z",
                "client": {"code": client_code or "12447", "fantasyName": "THIAGO COD", "name": "THIAGO FELIX"},
                "paymentShape": {"name": "PIX"},
                "paymentMethod": {"name": "A vista"},
                "qrCodePixCashin": {
                    "emv": "000201010212PAYIPPIXTESTE1474796304EFGH",
                    "linkImage": "https://example.test/qrcode/147479.png",
                },
            },
        ]
        return SimpleNamespace(
            raw={"data": items},
            items=tuple(items),
            items_count=self.items_count,
            total_items=self.total_items,
            page=page,
            page_size=page_size,
            filial=filial,
            company_id={
                "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
                "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
            }.get(filial or "3", ""),
        )

    def list_payments_history(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        filial: str = "",
    ) -> Any:
        return self.list_payments(page=page, page_size=page_size, filial=filial)

    def list_payment_batches(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        batch_type: str = "CREATE-PAYMENT",
        filial: str = "",
    ) -> Any:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        items = [
            {
                "id": "50cb5371-8218-41b3-aab7-1d2f32332ed0",
                "type": batch_type,
                "status": "DONE",
                "paymentsCount": 2,
                "amount": 2.98,
                "createdAt": "2026-04-13T22:08:00.000Z",
                "payments": [
                    {
                        "invoice": "147478",
                        "amount": 0.99,
                        "client": {"code": "12447", "fantasyName": "THIAGO COD"},
                    },
                    {
                        "invoice": "147479",
                        "amount": 1.99,
                        "client": {"code": "12447", "fantasyName": "THIAGO COD"},
                    },
                ],
            }
        ]
        return SimpleNamespace(
            raw={"data": items},
            items=tuple(items),
            items_count=len(items),
            total_items=len(items),
            page=page,
            page_size=page_size,
            filial=filial,
            company_id={
                "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
                "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
            }.get(filial or "3", ""),
        )

    def invoice_batch_process_file(self, **kwargs: Any) -> tuple[bytes, str]:
        self.invoice_batch_process_calls.append(dict(kwargs))
        return b"PK\x03\x04stub-payip-batch\n", "application/zip"

    def invoice_batch_process(self, **kwargs: Any) -> dict[str, Any]:
        self.invoice_batch_process_calls.append(dict(kwargs))
        return {"status": "Sucesso", "message": "Criacao do arquivo pdf em progresso"}

    def invoice_batch_download_file(self, **kwargs: Any) -> tuple[bytes, str]:
        self.invoice_batch_download_calls.append(dict(kwargs))
        return b"PK\x03\x04stub-payip-batch\n", "application/zip"

    def find_payments_by_amount_and_paid_date(
        self,
        *,
        filial: str,
        amount: Any,
        day: Any,
        tolerance: Any = Decimal("0.05"),
        status: str = "",
        page_size: int = 100,
        max_pages: int | None = None,
    ) -> Any:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        self.amount_day_calls.append(
            {
                "filial": filial,
                "amount": str(amount),
                "day": str(day),
                "tolerance": str(tolerance),
                "status": status,
                "page_size": page_size,
                "max_pages": max_pages,
            }
        )
        page = self.list_payments(
            page=1,
            page_size=page_size,
            status=status,
            paid_date_start=str(day),
            paid_date_end=str(day),
            filial=filial,
        )
        target = Decimal(str(amount).replace(",", "."))
        amount_tolerance = Decimal(str(tolerance).replace(",", "."))
        paid_items = tuple(
            {
                **item,
                "amountPaid": item.get("amount"),
                "paidDate": f"{day}T12:00:00.000Z",
            }
            for item in page.items
        )
        items = tuple(
            item
            for item in paid_items
            if abs(Decimal(str(item.get("amountPaid")).replace(",", ".")) - target) <= amount_tolerance
        )
        return SimpleNamespace(
            raw={"data": list(items)},
            items=items,
            items_count=len(items),
            total_items=len(items),
            page=1,
            page_size=page_size,
            filial=filial,
            company_id=page.company_id,
        )

    def bootstrap_session(self, *, mfa_code: str) -> dict[str, Any]:
        self.bootstrap_calls.append(mfa_code)
        self.access_token_valid = True
        self.refresh_token_valid = True
        self.require_mfa_once = False
        return self.status()

    def validate_promax_import_batch(
        self,
        *,
        filial: str,
        date_start: Any,
        date_end: Any,
    ) -> Any:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        self.import_batch_calls.append(
            {
                "filial": filial,
                "date_start": str(date_start),
                "date_end": str(date_end),
            }
        )
        items = (
            {
                "clientCode": "19167",
                "invoice": "181886",
                "total": 20,
                "dueDate": "2026-07-07T00:00:00",
            },
        )
        return SimpleNamespace(
            raw={"success": True, "data": list(items)},
            filial=filial,
            company_id={
                "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
                "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
            }.get(filial or "3", ""),
            date_start=str(date_start),
            date_end=str(date_end),
            items=items,
            missing_client_codes=(),
            ok=True,
        )

    def import_promax_batch(
        self,
        *,
        filial: str,
        date_start: Any,
        date_end: Any,
        totp_code: str,
    ) -> Any:
        self.import_batch_confirm_calls.append(
            {
                "filial": filial,
                "date_start": str(date_start),
                "date_end": str(date_end),
                "totp_code": str(totp_code),
            }
        )
        items = (
            {
                "clientCode": "19167",
                "invoice": "181886",
                "total": 20,
                "dueDate": "2026-07-07T00:00:00",
            },
        )
        return SimpleNamespace(
            raw={"success": True, "data": list(items)},
            filial=filial,
            company_id={
                "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
                "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
            }.get(filial or "3", ""),
            date_start=str(date_start),
            date_end=str(date_end),
            items=items,
            missing_client_codes=(),
            ok=True,
        )

    def list_routes(
        self,
        *,
        filial: str,
        status: str = "IN_PROGRESS",
        code: str = "",
        page: int = 1,
        page_size: int = 25,
    ) -> Any:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        self.routes_calls.append(
            {
                "filial": filial,
                "status": status,
                "code": code,
                "page": page,
                "page_size": page_size,
            }
        )
        items = (
            {
                "id": "route-1",
                "code": "92305",
                "status": "IN_PROGRESS",
                "driversRoute": [
                    {
                        "status": "IN_PROGRESS",
                        "driver": {"name": "Jose Marcelo", "code": "7444"},
                    }
                ],
            },
        )
        return SimpleNamespace(
            raw={"data": list(items)},
            filial=filial,
            company_id={
                "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
                "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
            }.get(filial or "3", ""),
            status=status,
            items=items,
            items_count=len(items),
            total_items=len(items),
            page=page,
            page_size=page_size,
        )

    def list_all_routes(
        self,
        *,
        filial: str,
        status: str = "IN_PROGRESS",
        code: str = "",
        page_size: int = 25,
        max_pages: int = 20,
    ) -> Any:
        pages: list[Any] = []
        items: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            current = self.list_routes(filial=filial, status=status, code=code, page=page, page_size=page_size)
            pages.append(current.raw)
            items.extend(list(current.items))
            total = current.total_items if current.total_items is not None else len(items)
            if len(items) >= total or len(current.items) < page_size:
                break
        return SimpleNamespace(
            raw={"pages": pages},
            filial=filial,
            company_id={
                "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
                "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
            }.get(filial or "3", ""),
            status=status,
            items=tuple(items),
            items_count=len(items),
            total_items=len(items),
            page=1,
            page_size=page_size,
        )

    def create_client_from_profile(self, *, profile: Any) -> Any:
        payload = {
            "companyId": "bdfee22b-ac11-4355-909a-54bd348c87cc",
            "client": {
                "taxPayerId": str(getattr(profile, "documento", "")),
                "name": str(getattr(profile, "razao_social", "")),
                "fantasyName": str(getattr(profile, "nome_fantasia", "")),
                "email": str(getattr(profile, "email", "") or f"cliente.{getattr(profile, 'filial', '')}.{getattr(profile, 'cod_pdv', '')}@sememail.com.br"),
                "phone": str(getattr(profile, "telefone", "") or "83990000000"),
                "code": str(getattr(profile, "cod_pdv", "")),
                "type": "PF",
            },
            "address": {
                "postalCode": str(getattr(profile, "cep", "")),
                "street": str(getattr(profile, "endereco", "")),
                "number": str(getattr(profile, "numero", "") or "SN"),
                "complement": str(getattr(profile, "complemento", "") or "n/d"),
                "neighborhood": str(getattr(profile, "bairro", "")),
                "city": str(getattr(profile, "cidade", "")),
                "state": str(getattr(profile, "uf", "")),
                "latitude": "",
                "longitude": "",
            },
        }
        self.create_client_calls.append({"profile": profile, "payload": payload})
        return SimpleNamespace(
            raw={"id": "client-company-1"},
            payload=payload,
            verify_raw={"success": True},
            filial=str(getattr(profile, "filial", "")),
            client_code=str(getattr(profile, "cod_pdv", "")),
            tax_payer_id=str(getattr(profile, "documento", "")),
        )

    def find_client_by_code(self, *, filial: str, client_code: str) -> Any:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        if self.client_lookup_error is not None:
            raise self.client_lookup_error
        self.client_lookup_calls.append({"filial": filial, "client_code": client_code})
        if client_code == "404":
            return None
        return SimpleNamespace(
            raw={},
            client_company_id="client-company-1",
            client_id="client-1",
            code=client_code,
            tax_payer_id="15954335460",
            name="MATHEUS GONCALVES DE SOUSA",
            fantasy_name="matheus",
            phone="83991964911",
        )

    def create_pix_charge(
        self,
        *,
        filial: str,
        amount: Any,
        rate_amount: Any,
        interest_perc: Any,
        tax_payer_id: str,
        external_id: str,
        due_date: Any,
        issue_date: Any,
        title: str,
        description: str,
        invoice: str = "",
    ) -> dict[str, Any]:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        if self.create_charge_error is not None:
            raise self.create_charge_error
        self.create_charge_calls.append(
            {
                "filial": filial,
                "amount": str(amount),
                "rate_amount": str(rate_amount),
                "interest_perc": str(interest_perc),
                "tax_payer_id": tax_payer_id,
                "external_id": external_id,
                "invoice": invoice,
                "due_date": str(due_date),
                "issue_date": str(issue_date),
                "title": title,
                "description": description,
            }
        )
        return {
            "id": "created-payment-1",
            "externalId": external_id,
            "status": "PENDING",
            "amount": float(amount),
            "amountDetails": {
                "amount": float(amount),
                "amountTotal": float(amount) + float(rate_amount),
                "amountRate": float(rate_amount),
            },
            "dueDate": f"{due_date}T03:00:00.000Z",
            "client": {
                "code": external_id,
                "taxPayerId": tax_payer_id,
                "name": "MATHEUS GONCALVES DE SOUSA",
                "fantasyName": "matheus",
            },
            "qrCodePixCashin": {
                "emv": "000201010212PAYIPPIXCREATE168836304DCBA",
                "linkImage": None,
                "statusPayment": "PENDING",
            },
        }

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        self.get_payment_calls.append(payment_id)
        return {
            "id": payment_id,
            "externalId": "16883",
            "invoice": "",
            "title": "Fatura revenda Pau Brasil - Patos",
            "description": "Fatura revenda Pau Brasil - Patos",
            "status": "PENDING",
            "amount": 0.99,
            "amountDetails": {
                "amount": 0.99,
                "amountTotal": 4.91,
                "amountRate": 3.92,
            },
            "dueDate": "2026-12-31T03:00:00.000Z",
            "client": {
                "code": "16883",
                "taxPayerId": "15954335460",
                "name": "MATHEUS GONCALVES DE SOUSA",
                "fantasyName": "matheus",
            },
            "company": {
                "companyId": "bdfee22b-ac11-4355-909a-54bd348c87cc",
            },
            "qrCodePixCashin": {
                "emv": "000201010212PAYIPPIXCREATE168836304DCBA",
                "linkImage": None,
                "statusPayment": "PENDING",
            },
        }

    def invoice_report_pdf(
        self,
        *,
        filial: str,
        payment_ids: list[str] | tuple[str, ...],
        company_id: str = "",
    ) -> bytes:
        self.invoice_report_calls.append(
            {
                "filial": filial,
                "payment_ids": list(payment_ids),
                "company_id": company_id,
            }
        )
        return b"%PDF-1.4\n%stub-payip\n"

    def statement_movements_resume(
        self,
        *,
        filial: str,
        date_start: Any,
        date_end: Any,
    ) -> Any:
        if self.require_mfa_once:
            self.require_mfa_once = False
            raise PayipMfaRequired("MFA required")
        company_id = {
            "3": "bdfee22b-ac11-4355-909a-54bd348c87cc",
            "4": "aa11f5fe-38dd-4bf5-86e3-71d874cdc24c",
        }.get(filial or "3", "")
        self.statement_resume_calls.append(
            {
                "filial": filial,
                "date_start": str(date_start),
                "date_end": str(date_end),
            }
        )
        return SimpleNamespace(
            raw={
                "currentBalance": 1000.50,
                "totalCredt": 150.75,
                "totalDebit": 40.25,
                "total": 191.00,
                "movementCount": 3,
                "companyId": company_id,
            },
            filial=filial,
            company_id=company_id,
            date_start=str(date_start),
            date_end=str(date_end),
        )

    def statement_movements_export(
        self,
        *,
        filial: str,
        date_start: Any,
        date_end: Any,
        file_format: str,
    ) -> bytes:
        self.statement_export_calls.append(
            {
                "filial": filial,
                "date_start": str(date_start),
                "date_end": str(date_end),
                "file_format": file_format,
            }
        )
        if file_format == "pdf":
            return b"%PDF-1.4\n%stub-payip-statement\n"
        if file_format == "xlsx":
            return b"PK\x03\x04stub-payip-statement"
        raise PayipError("Formato invalido")


class StubEstoque020304Service:
    def __init__(self, record: Any | None = None, *, ready: bool = True, product_record: Any | None = None) -> None:
        self.record = record
        self.product_record = product_record
        self.ready = ready
        self.calls: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        return {"ready": self.ready}

    def get_pdf_report(self, *, filial: str) -> Any | None:
        self.calls.append({"filial": filial})
        return self.record

    def get_product_stock(self, *, filial: str, product_code: str) -> Any | None:
        self.calls.append({"filial": filial, "product_code": product_code})
        return self.product_record


def make_flow(
    *,
    query_service: StubQueryService | None = None,
    inadimplencia_service: StubInadimplenciaService | None = None,
    comodatos_service: StubComodatosService | None = None,
    giro_service: StubGiroService | None = None,
    critica_rn_service: StubCriticaRnService | None = None,
    documentacao_pendente_service: StubDocumentacaoPendenteService | None = None,
    prazo_limite_service: StubPrazoLimiteService | None = None,
    estoque_020304_service: StubEstoque020304Service | None = None,
    payip_payments_service: StubPayipPaymentsService | None = None,
    recolha_request_service: RecolhaRequestService | None = None,
    access_control: AccessControl | None = None,
    session_ttl_minutes: int = 20,
) -> CustomerLookupFlow:
    return CustomerLookupFlow(
        query_service=query_service or StubQueryService(),
        inadimplencia_service=inadimplencia_service or StubInadimplenciaService(),
        comodatos_service=comodatos_service or StubComodatosService(),
        giro_service=giro_service or StubGiroService(),
        critica_rn_service=critica_rn_service or StubCriticaRnService(),
        documentacao_pendente_service=documentacao_pendente_service or StubDocumentacaoPendenteService(),
        prazo_limite_service=prazo_limite_service or StubPrazoLimiteService(),
        estoque_020304_service=estoque_020304_service or StubEstoque020304Service(),
        payip_payments_service=payip_payments_service or StubPayipPaymentsService(),
        recolha_request_service=recolha_request_service,
        access_control=access_control
        or AccessControl(
            enabled=False,
            database_url="",
            schema="public",
        ),
        session_ttl_minutes=session_ttl_minutes,
    )


def make_decision(
    *,
    allowed: bool = True,
    area: str = "cliente",
    roles: tuple[str, ...] = (),
    sectors: tuple[str, ...] = (),
    gv_vdes: tuple[str, ...] = (),
    normalized_number: str = "5511999999999",
    reason: str = "test",
) -> AccessDecision:
    return AccessDecision(
        allowed=allowed,
        reason=reason,
        area=area,
        normalized_number=normalized_number,
        roles=roles,
        sectors=sectors,
        gv_vdes=gv_vdes,
    )
