from __future__ import annotations

import io
import re
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from time import monotonic
from typing import Any
from xml.sax.saxutils import escape

from psycopg import sql
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from bot_api.commercial_scope import (
    normalize_stored_scope_value,
    partition_filial_scopes,
    partition_gv_scopes,
    partition_sector_scopes,
)
from bot_api.db import get_connection_pool
from bot_api.services.filial_labels import FILIAL_LABELS

PRICE_TOLERANCE_OP1 = Decimal("0.03")
PRICE_TOLERANCE_DEFAULT = Decimal("0.12")
B2B_PRICE_TOLERANCE = Decimal("0.60")
NON_SALE_PRICE_TOLERANCE = Decimal("0.60")
B2B_PRICE_ORIGINS = {"B2BG", "B2BGA"}
ORDER_AVG_ALERT_RATIO = Decimal("2.0")
REPORT_CACHE_TTL_SECONDS = 300.0
PDF_CACHE_TTL_SECONDS = 600.0
REPORT_CACHE_MAX_ENTRIES = 32
PDF_CACHE_MAX_ENTRIES = 16
DETAIL_PDF_GROUPS_PER_TABLE = 12
CRITICA_PDF_CACHE_TABLE = "critica_pdf_cache"
PDF_SCOPE_SECTOR = "setor"
PDF_SCOPE_GV = "gv"
REPORT_SESSION_WORK_MEM = "64MB"
CRITICA_PDF_CACHE_VERSION = "v27-cash-condition-limit-rule"
CRITICA_PDF_CURRENT_IMPORT_MESSAGE = (
    "PDF da critica bloqueado: importe os relatorios de critica de hoje antes de gerar."
)
CRITICA_IMPORT_LOCAL_TIMEZONE = timezone(timedelta(hours=-3))
PDF_THEME = {
    "page_bg": "#F5F6F8",
    "panel_bg": "#FFFFFF",
    "panel_bg_alt": "#F8F9FA",
    "header_bg": "#E7E9ED",
    "border": "#D3D7DD",
    "border_strong": "#C6CBD3",
    "text_primary": "#1F2933",
    "text_muted": "#4B5563",
    "accent": "#40566D",
    "accent_soft": "#EEF2F6",
    "warning_bg": "#FFF7E8",
    "warning_border": "#E8C98E",
    "warning_text": "#6B5A3C",
    "danger": "#B42318",
    "danger_bg": "#FFF1F0",
    "danger_bg_soft": "#FFF7F6",
    "danger_border": "#F0A6A1",
    "ok_text": "#1F2933",
}


@dataclass(frozen=True)
class CriticaRnSummary:
    data_pedido: date | None
    row_count: int
    pedido_count: int
    client_count: int
    problem_row_count: int
    problem_pedido_count: int
    rows_with_critica: int
    duplicated_row_count: int
    price_alert_count: int
    missing_price_count: int
    total_pedido: Decimal
    planilha_atualizada_em: str
    operations: tuple[str, ...] = ()
    peso_total: Decimal = Decimal("0")
    total_hectolitros: Decimal = Decimal("0")
    nab_tt_hectolitros: Decimal = Decimal("0")
    high_end_hectolitros: Decimal = Decimal("0")
    cerveja_tt_hectolitros: Decimal = Decimal("0")
    refri_zero_hectolitros: Decimal = Decimal("0")
    cerveja_rgb_hectolitros: Decimal = Decimal("0")
    cerveja_ow_hectolitros: Decimal = Decimal("0")
    marketplace_tt_hectolitros: Decimal = Decimal("0")
    marketplace_tt_faturamento: Decimal = Decimal("0")
    duplicated_pedido_count: int = 0
    order_avg_alert_count: int = 0
    inadimplente_count: int = 0
    multipack_violation_count: int = 0
    map_buffer_count: int = 0
    map_outside_count: int = 0
    cond_divergence_count: int = 0
    limit_alert_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_pedido"] = self.data_pedido.isoformat() if self.data_pedido else ""
        for field_name in (
            "total_pedido",
            "peso_total",
            "total_hectolitros",
            "nab_tt_hectolitros",
            "high_end_hectolitros",
            "cerveja_tt_hectolitros",
            "refri_zero_hectolitros",
            "cerveja_rgb_hectolitros",
            "cerveja_ow_hectolitros",
            "marketplace_tt_hectolitros",
            "marketplace_tt_faturamento",
        ):
            payload[field_name] = str(payload.get(field_name) or "0")
        payload["operations"] = list(self.operations)
        return payload


@dataclass(frozen=True)
class CriticaRnRecord:
    filial: str
    pedido: str
    data_pedido: date | None
    operacao: str
    cod_pdv: str
    nome_pdv: str
    setor: str
    seller_code: str
    manager_code: str
    status_pedido: str
    total_pedido: Decimal
    total_cliente: Decimal
    critica_text: str
    produto_codigo: str
    produto_descricao: str
    quantidade: Decimal
    unid_venda: str
    preco_unitario: Decimal
    preco_sem_adf: Decimal
    minimo_politica: Decimal
    tipo_movimento: str
    codigo_gv: str
    codigo_pgv: str
    pedido_linhas: int
    pedido_produto_linhas: int
    pedido_produto_duplicado: bool
    produto_encontrado_dprecos: bool
    preco_status: str
    ttc_min: Decimal | None
    ttc_max: Decimal | None
    caixa_min: Decimal | None
    caixa_max: Decimal | None
    problemas: tuple[str, ...]
    planilha_atualizada_em: str
    operation_name: str = ""
    produto_peso_bruto: Decimal = Decimal("0")
    peso_item: Decimal = Decimal("0")
    pedido_cliente_duplicado: bool = False
    duplicate_order_numbers: tuple[str, ...] = ()
    duplicate_order_refs: tuple[str, ...] = ()
    movement_operation_name: str = ""
    nome_produto_original: str = ""
    mapa_codigo: str = ""
    vendedor_codigo: str = ""
    area_codigo: str = ""
    cond_pag_pedido_codigo: str = ""
    cond_pag_pedido: str = ""
    forma_pagto: str = ""
    prazo_dias: str = ""
    segmento_cerveja: str = ""
    origem_pedido: str = ""
    valor_estouro_limite: Decimal = Decimal("0")
    maior_atraso_pedido: str = ""
    ocorrencia_1: str = ""
    ocorrencia_2: str = ""
    te_codigo: str = ""
    client_segment: str = ""
    client_cond_pag_atual_codigo: str = ""
    client_cond_pag_atual: str = ""
    client_media_faturamento_3m: Decimal = Decimal("0")
    client_limite_credito: Decimal = Decimal("0")
    client_limite_usado: Decimal = Decimal("0")
    client_saldo_aberto: Decimal = Decimal("0")
    client_status_pdv: str = ""
    client_cidade: str = ""
    client_bairro: str = ""
    avg_order_value_3m: Decimal = Decimal("0")
    avg_order_total_3m: Decimal = Decimal("0")
    avg_order_count_3m: Decimal = Decimal("0")
    inad_total_aberto: Decimal = Decimal("0")
    inad_total_vencido: Decimal = Decimal("0")
    inad_titulos_abertos: int = 0
    inad_titulos_vencidos: int = 0
    multipack_item: bool = False
    multipack_allowed: bool = True
    map_status: str = ""
    cond_divergente: bool = False
    order_above_average: bool = False
    limit_exceeded_amount: Decimal = Decimal("0")
    price_reference: Decimal | None = None
    price_reference_label: str = ""
    price_delta_pct: Decimal | None = None
    fator_hecto: Decimal = Decimal("0")
    hectolitros: Decimal = Decimal("0")
    cesta_nab_tt: bool = False
    cesta_high_end: bool = False
    cesta_cerveja_tt: bool = False
    cesta_refri_zero: bool = False
    cesta_cerveja_rgb: bool = False
    cesta_cerveja_ow: bool = False
    cesta_marketplace_tt: bool = False

    @property
    def possui_problema(self) -> bool:
        return bool(self.problemas)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_pedido"] = self.data_pedido.isoformat() if self.data_pedido else ""
        for field_name in (
            "total_pedido",
            "produto_peso_bruto",
            "peso_item",
            "total_cliente",
            "quantidade",
            "preco_unitario",
            "preco_sem_adf",
            "minimo_politica",
            "ttc_min",
            "ttc_max",
            "caixa_min",
            "caixa_max",
            "valor_estouro_limite",
            "client_media_faturamento_3m",
            "client_limite_credito",
            "client_limite_usado",
            "client_saldo_aberto",
            "avg_order_value_3m",
            "avg_order_total_3m",
            "avg_order_count_3m",
            "inad_total_aberto",
            "inad_total_vencido",
            "limit_exceeded_amount",
            "price_reference",
            "price_delta_pct",
            "fator_hecto",
            "hectolitros",
        ):
            value = payload.get(field_name)
            payload[field_name] = "" if value is None else str(value)
        return payload


@dataclass(frozen=True)
class CriticaRnOrderRecord:
    filial: str
    pedido: str
    data_pedido: date | None
    operation_name: str
    movement_operation_name: str
    setor: str
    cod_pdv: str
    nome_pdv: str
    status_pedido: str
    total_pedido: Decimal
    peso_pedido: Decimal
    cond_pag_pedido: str
    problem_labels: tuple[str, ...]
    problem_item_count: int
    item_count: int


@dataclass(frozen=True)
class CriticaRnReportData:
    summary: CriticaRnSummary
    records: list[CriticaRnRecord]


@dataclass(frozen=True)
class CriticaRnPdfReport:
    summary: CriticaRnSummary
    records: list[CriticaRnRecord]
    pdf_bytes: bytes
    summary_pdf_bytes: bytes


class CriticaPdfCurrentImportRequiredError(RuntimeError):
    pass


@dataclass
class _TimedCacheEntry:
    value: Any
    expires_at: float


class CriticaRnQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_expires_at = 0.0
        self._cache_lock = threading.Lock()
        self._report_cache: dict[tuple[Any, ...], _TimedCacheEntry] = {}
        self._pdf_cache: dict[tuple[Any, ...], _TimedCacheEntry] = {}
        self._inflight: dict[tuple[str, tuple[Any, ...]], threading.Event] = {}

    def status(self) -> dict[str, Any]:
        now = monotonic()
        if self._status_cache is not None and now < self._status_cache_expires_at:
            return dict(self._status_cache)
        if not self.database_url:
            payload = {
                "database_configured": False,
                "ready": False,
                "schema": self.schema,
                "latest_view_exists": False,
                "last_error": "REPORTS_DATABASE_URL nao configurada.",
            }
            self._cache_status(payload)
            return payload
        try:
            with self._connect(row_factory=dict_row) as conn:
                relation = self._resolve_source_relation(conn)
            ready = relation is not None
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": ready,
                "source_view": relation or "",
                "last_error": "" if ready else "Views reports.critica_latest e reports.critica_rn_latest nao encontradas.",
            }
            self._cache_status(payload)
            return payload
        except Exception as exc:
            payload = {
                "database_configured": True,
                "ready": False,
                "schema": self.schema,
                "latest_view_exists": False,
                "last_error": str(exc),
            }
            self._cache_status(payload)
            return payload

    def latest_date(
        self,
        *,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> date | None:
        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        with self._connect(row_factory=dict_row) as conn:
            relation = self._require_source_relation(conn)
            query = sql.SQL(
                """
                SELECT MAX(c.data_pedido) AS data_pedido
                FROM {schema}.{relation} c
                {where_clause}
                """
            ).format(
                schema=sql.Identifier(self.schema),
                relation=sql.Identifier(relation),
                where_clause=_where_clause(filters),
            )
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone() or {}
        value = row.get("data_pedido")
        return value if isinstance(value, date) else None

    def has_current_critica_import(
        self,
        *,
        today: date | None = None,
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        filial: str | None = None,
    ) -> bool:
        check_date = today or datetime.now(CRITICA_IMPORT_LOCAL_TIMEZONE).date()
        query = sql.SQL(
            """
            SELECT b.dataset_name
            FROM {schema}.import_batches b
            LEFT JOIN {schema}.dataset_state s
              ON s.dataset_name = b.dataset_name
            WHERE (b.dataset_name = %s OR b.dataset_name LIKE %s)
              AND COALESCE(s.active_batch_id, b.id) = b.id
              AND (
                  b.reference_date = %s
                  OR (b.imported_at AT TIME ZONE 'America/Fortaleza')::date = %s
              )
            """
        ).format(schema=sql.Identifier(self.schema))
        active_query = sql.SQL(
            """
            SELECT dataset_name
            FROM {schema}.dataset_state
            WHERE dataset_name LIKE %s
              AND active_batch_id IS NOT NULL
            """
        ).format(schema=sql.Identifier(self.schema))
        try:
            with self._connect(row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, ("critica_rn", "critica_op_%", check_date, check_date))
                    current_datasets = {str(row.get("dataset_name") or "") for row in cur.fetchall()}
                    cur.execute(active_query, ("critica_op_%",))
                    active_operation_datasets = {str(row.get("dataset_name") or "") for row in cur.fetchall()}
        except Exception:
            return False

        if "critica_rn" in current_datasets:
            return True

        required_operation_datasets = {
            f"critica_op_{filial_code}"
            for filial_code in _extract_critica_scope_filiais(
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                filial=filial,
            )
        }
        if required_operation_datasets:
            return required_operation_datasets.issubset(current_datasets)

        current_operation_datasets = {dataset for dataset in current_datasets if dataset.startswith("critica_op_")}
        if target_date == check_date and current_operation_datasets:
            return True
        return bool(active_operation_datasets) and active_operation_datasets.issubset(current_operation_datasets)

    def _ensure_current_critica_import_for_pdf(
        self,
        *,
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        filial: str | None = None,
    ) -> None:
        if not self.has_current_critica_import(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            filial=filial,
        ):
            raise CriticaPdfCurrentImportRequiredError(CRITICA_PDF_CURRENT_IMPORT_MESSAGE)

    def get_report_data(
        self,
        *,
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 5000,
    ) -> CriticaRnReportData:
        normalized_limit = max(1, min(int(limit or 1), 50000))
        cache_key = (
            "data",
            _date_cache_key(target_date),
            _scope_cache_key(allowed_sectors),
            _scope_cache_key(allowed_gv_vdes),
            normalized_limit,
        )

        def factory() -> CriticaRnReportData:
            access_filters, access_params = self._build_access_filter_parts(allowed_sectors, allowed_gv_vdes)
            filters: list[sql.Composed] = []
            params: list[Any] = []
            if target_date is not None:
                filters.append(sql.SQL("c.data_pedido = %s"))
                params.append(target_date)
            filters.extend(access_filters)
            params.extend(access_params)
            records = self._list_records(
                filters=filters,
                params=params,
                limit=normalized_limit,
                duplicate_context_filters=access_filters if target_date is not None else None,
                duplicate_context_params=access_params if target_date is not None else None,
            )
            return CriticaRnReportData(summary=_summarize_records(records), records=records)

        data = self._cached_value(
            namespace="report",
            cache=self._report_cache,
            key=cache_key,
            ttl_seconds=REPORT_CACHE_TTL_SECONDS,
            max_entries=REPORT_CACHE_MAX_ENTRIES,
            factory=factory,
        )
        return CriticaRnReportData(summary=data.summary, records=list(data.records))

    def get_pdf_report(
        self,
        *,
        target_date: date,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 5000,
    ) -> CriticaRnPdfReport:
        self._ensure_current_critica_import_for_pdf(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
        )
        normalized_limit = max(1, min(int(limit or 1), 50000))
        cache_key = (
            "pdf",
            _date_cache_key(target_date),
            _scope_cache_key(allowed_sectors),
            _scope_cache_key(allowed_gv_vdes),
            normalized_limit,
        )

        def factory() -> CriticaRnPdfReport:
            pregenerated = self._load_pregenerated_pdf_report(
                target_date=target_date,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=normalized_limit,
            )
            if pregenerated is not None:
                return pregenerated
            data = self.get_report_data(
                target_date=target_date,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=normalized_limit,
            )
            if data.summary.row_count <= 0:
                return CriticaRnPdfReport(summary=data.summary, records=data.records, pdf_bytes=b"", summary_pdf_bytes=b"")
            report = CriticaRnPdfReport(
                summary=data.summary,
                records=data.records,
                pdf_bytes=build_critica_rn_pdf(summary=data.summary, records=data.records),
                summary_pdf_bytes=build_critica_rn_summary_pdf(summary=data.summary, records=data.records),
            )
            self._store_pregenerated_pdf_report(
                target_date=target_date,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=normalized_limit,
                report=report,
            )
            return report

        report = self._cached_value(
            namespace="pdf",
            cache=self._pdf_cache,
            key=cache_key,
            ttl_seconds=PDF_CACHE_TTL_SECONDS,
            max_entries=PDF_CACHE_MAX_ENTRIES,
            factory=factory,
        )
        return CriticaRnPdfReport(
            summary=report.summary,
            records=list(report.records),
            pdf_bytes=report.pdf_bytes,
            summary_pdf_bytes=report.summary_pdf_bytes,
        )

    def build_pdf_report_for_records(self, records: list[CriticaRnRecord]) -> CriticaRnPdfReport:
        summary = _summarize_records(records)
        if summary.row_count <= 0:
            return CriticaRnPdfReport(summary=summary, records=list(records), pdf_bytes=b"", summary_pdf_bytes=b"")
        return CriticaRnPdfReport(
            summary=summary,
            records=list(records),
            pdf_bytes=build_critica_rn_pdf(summary=summary, records=records),
            summary_pdf_bytes=build_critica_rn_summary_pdf(summary=summary, records=records),
        )

    def get_pdf_report_by_registration(
        self,
        *,
        cod_pdv: str,
        filial: str = "",
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 300,
    ) -> CriticaRnPdfReport:
        self._ensure_current_critica_import_for_pdf(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            filial=filial,
        )
        records = self.search_by_registration(
            cod_pdv=cod_pdv,
            filial=filial,
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=limit,
        )
        return self.build_pdf_report_for_records(records)

    def get_gv_summary_pdf(
        self,
        *,
        target_date: date,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50000,
    ) -> CriticaRnPdfReport:
        self._ensure_current_critica_import_for_pdf(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
        )
        data = self.get_report_data(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=limit,
        )
        if data.summary.row_count <= 0 and _uses_legacy_gv_scope_only(allowed_gv_vdes):
            access_filters, access_params = self._build_access_filter_parts(allowed_sectors, allowed_gv_vdes)
            records = self._list_records_from_relation(
                relation="critica_rn_latest",
                filters=access_filters,
                params=access_params,
                limit=limit,
            )
            data = CriticaRnReportData(summary=_summarize_records(records), records=records)
        if data.summary.row_count <= 0:
            return CriticaRnPdfReport(summary=data.summary, records=data.records, pdf_bytes=b"", summary_pdf_bytes=b"")
        return CriticaRnPdfReport(
            summary=data.summary,
            records=data.records,
            pdf_bytes=build_critica_rn_gv_summary_pdf(summary=data.summary, records=data.records),
            summary_pdf_bytes=b"",
        )

    def get_summary(
        self,
        *,
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> CriticaRnSummary:
        return self.get_report_data(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=50000,
        ).summary

    def list_problems(
        self,
        *,
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 20,
    ) -> list[CriticaRnRecord]:
        records = self.get_report_data(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=max(5000, int(limit or 1) * 50),
        ).records
        return [record for record in records if record.possui_problema][: max(1, int(limit or 1))]

    def search_by_registration(
        self,
        *,
        cod_pdv: str,
        filial: str = "",
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 300,
    ) -> list[CriticaRnRecord]:
        access_filters, access_params = self._build_access_filter_parts(allowed_sectors, allowed_gv_vdes)
        filters: list[sql.Composed] = [sql.SQL("c.cod_pdv = %s")]
        params: list[Any] = [normalize_stored_scope_value(cod_pdv)]
        normalized_filial = normalize_stored_scope_value(filial)
        if normalized_filial:
            filters.append(sql.SQL("c.filial = %s"))
            params.append(normalized_filial)
        if target_date is not None:
            filters.append(sql.SQL("c.data_pedido = %s"))
            params.append(target_date)
        filters.extend(access_filters)
        params.extend(access_params)
        return self._list_records(
            filters=filters,
            params=params,
            limit=limit,
            duplicate_context_filters=access_filters if target_date is not None else None,
            duplicate_context_params=access_params if target_date is not None else None,
        )

    def list_report_rows(
        self,
        *,
        target_date: date | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        only_problems: bool = False,
        limit: int = 5000,
    ) -> list[CriticaRnRecord]:
        records = self.get_report_data(
            target_date=target_date,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=limit,
        ).records
        if only_problems:
            return [record for record in records if record.possui_problema]
        return records

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._report_cache.clear()
            self._pdf_cache.clear()

    def warm_pdf_reports(
        self,
        *,
        target_date: date | None = None,
        scope_types: tuple[str, ...] = (PDF_SCOPE_SECTOR, PDF_SCOPE_GV),
        limit: int = 5000,
    ) -> dict[str, Any]:
        started_at = monotonic()
        normalized_limit = max(1, min(int(limit or 1), 50000))
        effective_date = target_date or self.latest_date()
        self._ensure_current_critica_import_for_pdf(target_date=effective_date)
        if effective_date is None:
            return {
                "ok": True,
                "target_date": "",
                "generated": 0,
                "skipped_empty": 0,
                "scope_count": 0,
                "elapsed_ms": 0,
            }

        with self._connect(row_factory=dict_row) as conn:
            relation = self._require_source_relation(conn)
            self._ensure_pdf_cache_schema(conn)
            source_signature = self._source_cache_signature(conn, relation)
            conn.commit()

        full_data = self.get_report_data(target_date=effective_date, limit=50000)
        grouped_records = _group_records_for_pdf_scopes(full_data.records, scope_types=scope_types)
        scopes = sorted(grouped_records, key=lambda item: (item[0], _sort_key_numeric_text(item[1])))

        generated = 0
        skipped_empty = 0
        errors: list[str] = []
        for scope_type, scope_key in scopes:
            try:
                records = grouped_records[(scope_type, scope_key)][:normalized_limit]
                summary = _summarize_records(records)
                if summary.row_count <= 0:
                    skipped_empty += 1
                    continue
                report = CriticaRnPdfReport(
                    summary=summary,
                    records=records,
                    pdf_bytes=build_critica_rn_pdf(summary=summary, records=records),
                    summary_pdf_bytes=build_critica_rn_summary_pdf(summary=summary, records=records),
                )
                self._store_pdf_report_for_scope(
                    target_date=effective_date,
                    scope_type=scope_type,
                    scope_key=scope_key,
                    limit=normalized_limit,
                    source_signature=source_signature,
                    report=report,
                    ensure_schema=False,
                )
                generated += 1
            except Exception as exc:
                errors.append(f"{scope_type}:{scope_key}: {exc}")

        self.clear_cache()
        return {
            "ok": not errors,
            "target_date": effective_date.isoformat(),
            "generated": generated,
            "skipped_empty": skipped_empty,
            "scope_count": len(scopes),
            "scope_types": list(scope_types),
            "limit": normalized_limit,
            "elapsed_ms": int((monotonic() - started_at) * 1000),
            "errors": errors[:10],
        }

    def _load_pregenerated_pdf_report(
        self,
        *,
        target_date: date,
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
        limit: int,
    ) -> CriticaRnPdfReport | None:
        scope = _resolve_pdf_cache_scope(allowed_sectors, allowed_gv_vdes)
        if scope is None:
            return None
        scope_type, scope_key = scope
        try:
            with self._connect(row_factory=dict_row) as conn:
                if not self._relation_exists(conn, CRITICA_PDF_CACHE_TABLE):
                    return None
                relation = self._require_source_relation(conn)
                source_signature = self._source_cache_signature(conn, relation)
                query = sql.SQL(
                    """
                    SELECT summary_json, pdf_bytes, summary_pdf_bytes
                    FROM {schema}.{table}
                    WHERE target_date = %s
                      AND scope_type = %s
                      AND scope_key = %s
                      AND row_limit = %s
                      AND source_signature = %s
                    """
                ).format(
                    schema=sql.Identifier(self.schema),
                    table=sql.Identifier(CRITICA_PDF_CACHE_TABLE),
                )
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (target_date, scope_type, scope_key, int(limit), source_signature))
                    row = cur.fetchone()
            if not row:
                return None
            return CriticaRnPdfReport(
                summary=_summary_from_cache_payload(row.get("summary_json") or {}),
                records=[],
                pdf_bytes=bytes(row.get("pdf_bytes") or b""),
                summary_pdf_bytes=bytes(row.get("summary_pdf_bytes") or b""),
            )
        except Exception:
            return None

    def _store_pregenerated_pdf_report(
        self,
        *,
        target_date: date,
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
        limit: int,
        report: CriticaRnPdfReport,
    ) -> None:
        scope = _resolve_pdf_cache_scope(allowed_sectors, allowed_gv_vdes)
        if scope is None or report.summary.row_count <= 0:
            return
        try:
            with self._connect(row_factory=dict_row) as conn:
                relation = self._require_source_relation(conn)
                source_signature = self._source_cache_signature(conn, relation)
            self._store_pdf_report_for_scope(
                target_date=target_date,
                scope_type=scope[0],
                scope_key=scope[1],
                limit=limit,
                source_signature=source_signature,
                report=report,
                ensure_schema=True,
            )
        except Exception:
            return

    def _store_pdf_report_for_scope(
        self,
        *,
        target_date: date,
        scope_type: str,
        scope_key: str,
        limit: int,
        source_signature: str,
        report: CriticaRnPdfReport,
        ensure_schema: bool,
    ) -> None:
        with self._connect(row_factory=dict_row) as conn:
            if ensure_schema:
                self._ensure_pdf_cache_schema(conn)
            query = sql.SQL(
                """
                INSERT INTO {schema}.{table} (
                    target_date,
                    scope_type,
                    scope_key,
                    row_limit,
                    source_signature,
                    summary_json,
                    pdf_bytes,
                    summary_pdf_bytes,
                    row_count,
                    pedido_count,
                    generated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (target_date, scope_type, scope_key, row_limit)
                DO UPDATE SET
                    source_signature = EXCLUDED.source_signature,
                    summary_json = EXCLUDED.summary_json,
                    pdf_bytes = EXCLUDED.pdf_bytes,
                    summary_pdf_bytes = EXCLUDED.summary_pdf_bytes,
                    row_count = EXCLUDED.row_count,
                    pedido_count = EXCLUDED.pedido_count,
                    generated_at = NOW()
                """
            ).format(
                schema=sql.Identifier(self.schema),
                table=sql.Identifier(CRITICA_PDF_CACHE_TABLE),
            )
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        target_date,
                        scope_type,
                        scope_key,
                        int(limit),
                        source_signature,
                        Jsonb(report.summary.to_dict()),
                        report.pdf_bytes,
                        report.summary_pdf_bytes,
                        report.summary.row_count,
                        report.summary.pedido_count,
                    ),
                )
            conn.commit()

    def _ensure_pdf_cache_schema(self, conn: Any) -> None:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        target_date DATE NOT NULL,
                        scope_type TEXT NOT NULL,
                        scope_key TEXT NOT NULL,
                        row_limit INTEGER NOT NULL DEFAULT 5000,
                        source_signature TEXT NOT NULL DEFAULT '',
                        summary_json JSONB NOT NULL,
                        pdf_bytes BYTEA NOT NULL,
                        summary_pdf_bytes BYTEA NOT NULL,
                        row_count INTEGER NOT NULL DEFAULT 0,
                        pedido_count INTEGER NOT NULL DEFAULT 0,
                        generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (target_date, scope_type, scope_key, row_limit)
                    )
                    """
                ).format(
                    schema=sql.Identifier(self.schema),
                    table=sql.Identifier(CRITICA_PDF_CACHE_TABLE),
                )
            )
            cur.execute(
                sql.SQL("ALTER TABLE {schema}.{table} ALTER COLUMN source_signature TYPE TEXT").format(
                    schema=sql.Identifier(self.schema),
                    table=sql.Identifier(CRITICA_PDF_CACHE_TABLE),
                )
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_pdf_cache_scope_idx ON {schema}.{table} (scope_type, scope_key, target_date DESC)"
                ).format(
                    schema=sql.Identifier(self.schema),
                    table=sql.Identifier(CRITICA_PDF_CACHE_TABLE),
                )
            )

    def _source_cache_signature(self, conn: Any, relation: str) -> str:
        dataset_filter = "critica_rn" if relation == "critica_rn_latest" else "critica_op_%"
        operator = "=" if relation == "critica_rn_latest" else "LIKE"
        dependency_datasets = [
            "dclientes",
            "dcondicoes",
            "doperacoes",
            "dprecos",
            "dprodutos",
            "inadimplencia",
            "prazo_limite",
            "produto_cestas",
        ]
        query = sql.SQL(
            """
            SELECT COALESCE(
                STRING_AGG(dataset_name || '=' || COALESCE(active_batch_id::text, ''), ',' ORDER BY dataset_name),
                ''
            ) AS signature
            FROM {schema}.dataset_state
            WHERE dataset_name {operator} %s
               OR dataset_name = ANY(%s)
            """
        ).format(
            schema=sql.Identifier(self.schema),
            operator=sql.SQL(operator),
        )
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (dataset_filter, dependency_datasets))
            row = cur.fetchone() or {}
        return f"{CRITICA_PDF_CACHE_VERSION}:{relation}:{row.get('signature') or ''}"

    def _list_pdf_report_scopes(
        self,
        *,
        conn: Any,
        relation: str,
        target_date: date,
        scope_types: tuple[str, ...],
    ) -> list[tuple[str, str]]:
        scopes: list[tuple[str, str]] = []
        with conn.cursor(row_factory=tuple_row) as cur:
            if PDF_SCOPE_SECTOR in scope_types:
                query = sql.SQL(
                    """
                    SELECT DISTINCT c.filial_setor_key
                    FROM {schema}.{relation} c
                    WHERE c.data_pedido = %s
                      AND COALESCE(c.filial_setor_key, '') <> ''
                    ORDER BY c.filial_setor_key
                    """
                ).format(schema=sql.Identifier(self.schema), relation=sql.Identifier(relation))
                cur.execute(query, (target_date,))
                scopes.extend((PDF_SCOPE_SECTOR, row[0]) for row in cur.fetchall())
            if PDF_SCOPE_GV in scope_types:
                query = sql.SQL(
                    """
                    SELECT DISTINCT c.filial_gv_key
                    FROM {schema}.{relation} c
                    WHERE c.data_pedido = %s
                      AND COALESCE(c.filial_gv_key, '') <> ''
                    ORDER BY c.filial_gv_key
                    """
                ).format(schema=sql.Identifier(self.schema), relation=sql.Identifier(relation))
                cur.execute(query, (target_date,))
                scopes.extend((PDF_SCOPE_GV, row[0]) for row in cur.fetchall())
        return scopes

    def _cached_value(
        self,
        *,
        namespace: str,
        cache: dict[tuple[Any, ...], _TimedCacheEntry],
        key: tuple[Any, ...],
        ttl_seconds: float,
        max_entries: int,
        factory: Any,
    ) -> Any:
        inflight_key = (namespace, key)
        while True:
            now = monotonic()
            with self._cache_lock:
                entry = cache.get(key)
                if entry is not None and entry.expires_at > now:
                    return entry.value
                event = self._inflight.get(inflight_key)
                if event is None:
                    event = threading.Event()
                    self._inflight[inflight_key] = event
                    owner = True
                    break
                owner = False
            if not owner:
                event.wait(timeout=max(float(ttl_seconds), 30.0))

        try:
            value = factory()
        except Exception:
            with self._cache_lock:
                self._inflight.pop(inflight_key, None)
                event.set()
            raise

        with self._cache_lock:
            cache[key] = _TimedCacheEntry(value=value, expires_at=monotonic() + ttl_seconds)
            self._prune_cache(cache, max_entries=max_entries)
            self._inflight.pop(inflight_key, None)
            event.set()
        return value

    def _prune_cache(self, cache: dict[tuple[Any, ...], _TimedCacheEntry], *, max_entries: int) -> None:
        if len(cache) <= max_entries:
            return
        for cache_key, _entry in sorted(cache.items(), key=lambda item: item[1].expires_at)[: len(cache) - max_entries]:
            cache.pop(cache_key, None)

    def _list_records(
        self,
        *,
        filters: list[sql.Composed],
        params: list[Any],
        limit: int,
        duplicate_context_filters: list[sql.Composed] | None = None,
        duplicate_context_params: list[Any] | None = None,
    ) -> list[CriticaRnRecord]:
        query_params = list(params)
        query_params.append(max(1, min(int(limit or 1), 50000)))
        with self._connect(row_factory=dict_row) as conn:
            relation = self._require_source_relation(conn)
            query = self._build_records_query(conn=conn, relation=relation, filters=filters)
            with conn.cursor() as cur:
                cur.execute(query, query_params)
                rows = cur.fetchall()
            records = [_row_to_record(row) for row in rows]
            duplicate_context_records = records
            if duplicate_context_filters is not None and records:
                duplicate_context_records = self._fetch_duplicate_context_records(
                    conn=conn,
                    relation=relation,
                    filters=duplicate_context_filters,
                    params=duplicate_context_params or [],
                    client_keys={(record.filial, record.cod_pdv) for record in records},
                )
        records = _annotate_duplicate_client_orders(records, context_records=duplicate_context_records)
        records = _annotate_duplicate_products_by_price(records)
        records = _annotate_client_total_above_average(records)
        records.sort(
            key=lambda record: (
                0 if record.possui_problema else 1,
                int(record.filial or "0") if str(record.filial or "").isdigit() else 999,
                record.operation_name,
                record.pedido,
                record.cod_pdv,
                record.produto_codigo,
            )
        )
        return records

    def _list_records_from_relation(
        self,
        *,
        relation: str,
        filters: list[sql.Composed],
        params: list[Any],
        limit: int,
        duplicate_context_filters: list[sql.Composed] | None = None,
        duplicate_context_params: list[Any] | None = None,
    ) -> list[CriticaRnRecord]:
        query_params = list(params)
        query_params.append(max(1, min(int(limit or 1), 50000)))
        with self._connect(row_factory=dict_row) as conn:
            query = self._build_records_query(conn=conn, relation=relation, filters=filters)
            with conn.cursor() as cur:
                cur.execute(query, query_params)
                rows = cur.fetchall()
            records = [_row_to_record(row) for row in rows]
            duplicate_context_records = records
            if duplicate_context_filters is not None and records:
                duplicate_context_records = self._fetch_duplicate_context_records(
                    conn=conn,
                    relation=relation,
                    filters=duplicate_context_filters,
                    params=duplicate_context_params or [],
                    client_keys={(record.filial, record.cod_pdv) for record in records},
                )
        records = _annotate_duplicate_client_orders(records, context_records=duplicate_context_records)
        records = _annotate_duplicate_products_by_price(records)
        records = _annotate_client_total_above_average(records)
        records.sort(
            key=lambda record: (
                0 if record.possui_problema else 1,
                int(record.filial or "0") if str(record.filial or "").isdigit() else 999,
                record.operation_name,
                record.pedido,
                record.cod_pdv,
                record.produto_codigo,
            )
        )
        return records

    def _fetch_duplicate_context_records(
        self,
        *,
        conn: Any,
        relation: str,
        filters: list[sql.Composed],
        params: list[Any],
        client_keys: set[tuple[str, str]],
    ) -> list[CriticaRnRecord]:
        normalized_filiais = sorted(
            {
                normalize_stored_scope_value(filial)
                for filial, cod_pdv in client_keys
                if normalize_stored_scope_value(filial) and normalize_stored_scope_value(cod_pdv)
            },
            key=_sort_key_numeric_text,
        )
        normalized_cod_pdvs = sorted(
            {
                normalize_stored_scope_value(cod_pdv)
                for filial, cod_pdv in client_keys
                if normalize_stored_scope_value(filial) and normalize_stored_scope_value(cod_pdv)
            },
            key=_sort_key_numeric_text,
        )
        if not normalized_filiais or not normalized_cod_pdvs:
            return []

        context_filters = list(filters)
        context_params = list(params)
        context_filters.append(sql.SQL("c.filial = ANY(%s)"))
        context_params.append(normalized_filiais)
        context_filters.append(sql.SQL("c.cod_pdv = ANY(%s)"))
        context_params.append(normalized_cod_pdvs)
        context_params.append(50000)
        query = sql.SQL(
            """
            SELECT
                c.filial,
                c.cod_pdv,
                c.pedido,
                c.data_pedido,
                c.produto_codigo,
                COALESCE(NULLIF(c.produto_dprecos, ''), NULLIF(c.payload ->> 'Nome Produto', ''), NULLIF(c.payload ->> 'Produto', '')) AS produto_descricao,
                COALESCE(NULLIF(c.payload ->> 'Nome Produto', ''), NULLIF(c.payload ->> 'Produto', '')) AS nome_produto_original,
                c.quantidade,
                c.unid_venda
            FROM {schema}.{relation} c
            {where_clause}
            ORDER BY c.filial, c.cod_pdv, c.pedido, c.produto_codigo
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            relation=sql.Identifier(relation),
            where_clause=_where_clause(context_filters),
        )
        with conn.cursor() as cur:
            cur.execute(query, context_params)
            rows = cur.fetchall()
        return [_row_to_duplicate_context_record(row) for row in rows]

    def _build_records_query(self, *, conn: Any, relation: str, filters: list[sql.Composed]) -> sql.Composed:
        ctes = [
            _dprecos_reference_cte(self.schema, conn),
            _dprodutos_reference_cte(self.schema, conn),
            _produto_cesta_metrics_cte(self.schema, conn),
            _doperacoes_reference_cte(self.schema, conn),
            _dcondicoes_reference_cte(self.schema, conn),
            _dclientes_reference_cte(self.schema, conn),
            _prazo_media_cte(self.schema, conn),
            _inad_stats_cte(self.schema, conn),
        ]
        return sql.SQL(
            """
            WITH
            {ctes}
            SELECT
                c.filial,
                c.pedido,
                c.row_number,
                c.data_pedido,
                c.operacao,
                c.cod_pdv,
                c.nome_pdv,
                c.setor,
                c.filial_setor_key,
                c.filial_gv_key,
                c.status_pedido,
                c.total_pedido,
                c.total_cliente,
                c.critica_text,
                c.produto_codigo,
                COALESCE(NULLIF(c.produto_dprecos, ''), NULLIF(c.payload ->> 'Nome Produto', ''), NULLIF(c.payload ->> 'Produto', '')) AS produto_dprecos,
                COALESCE(NULLIF(c.payload ->> 'Nome Produto', ''), NULLIF(c.payload ->> 'Produto', ''), NULLIF(c.produto_dprecos, '')) AS produto_descricao_pdf,
                COALESCE(NULLIF(c.payload ->> 'Nome Produto', ''), NULLIF(c.payload ->> 'Produto', '')) AS nome_produto_original,
                c.quantidade,
                c.unid_venda,
                c.preco_unitario,
                c.preco_sem_adf,
                c.minimo_politica,
                c.tipo_movimento,
                c.codigo_gv,
                c.codigo_pgv,
                c.pedido_linhas,
                c.pedido_produto_linhas,
                c.pedido_produto_duplicado,
                c.produto_encontrado_dprecos,
                c.preco_status,
                c.ttc_min,
                c.ttc_max,
                c.caixa_min,
                c.caixa_max,
                c.reference_date,
                c.batch_imported_at,
                c.payload,
                COALESCE(NULLIF(c.payload ->> 'Mapa', ''), '') AS mapa_codigo,
                COALESCE(NULLIF(c.payload ->> 'Cod. Vendedor', ''), '') AS vendedor_codigo,
                COALESCE(NULLIF(c.payload ->> 'Cod. Area', ''), '') AS area_codigo,
                COALESCE(NULLIF(c.payload ->> 'Cond Pgto', ''), '') AS cond_pag_pedido_codigo,
                COALESCE(NULLIF(dcp.descricao, ''), NULLIF(c.payload ->> 'Cond Pgto', ''), '') AS cond_pag_pedido,
                COALESCE(NULLIF(c.payload ->> 'Forma Pgto', ''), '') AS forma_pgto,
                COALESCE(NULLIF(c.payload ->> 'Prazo em Dias', ''), '') AS prazo_dias,
                COALESCE(NULLIF(c.payload ->> 'DS Segmento Cerveja', ''), '') AS segmento_cerveja,
                COALESCE(NULLIF(c.payload ->> 'Origem Pedido', ''), '') AS origem_pedido,
                COALESCE(NULLIF(c.payload ->> 'Maior Atraso', ''), '') AS maior_atraso_pedido,
                COALESCE(NULLIF(c.payload ->> 'Ocorrencia 1', ''), '') AS ocorrencia_1,
                COALESCE(NULLIF(c.payload ->> 'Ocorrencia 2', ''), '') AS ocorrencia_2,
                COALESCE(NULLIF(c.payload ->> 'TE', ''), '') AS te_codigo,
                COALESCE(NULLIF(c.payload ->> 'Vl Estouro Limite', ''), '') AS valor_estouro_limite_text,
                COALESCE(dp.produto_dprecos, '') AS dprecos_produto,
                dp.asr_preco,
                dp.sub_preco,
                dp.frio_preco,
                dp.ttc_preco,
                COALESCE(prod.fator_hecto, 0) AS produto_fator_hecto,
                COALESCE(prod.peso_bruto, 0) AS produto_peso_bruto,
                COALESCE(pcm.cesta_nab_tt, FALSE) AS cesta_nab_tt,
                COALESCE(pcm.cesta_high_end, FALSE) AS cesta_high_end,
                COALESCE(pcm.cesta_cerveja_tt, FALSE) AS cesta_cerveja_tt,
                COALESCE(pcm.cesta_refri_zero, FALSE) AS cesta_refri_zero,
                COALESCE(pcm.cesta_cerveja_rgb, FALSE) AS cesta_cerveja_rgb,
                COALESCE(pcm.cesta_cerveja_ow, FALSE) AS cesta_cerveja_ow,
                COALESCE(pcm.cesta_marketplace_tt, FALSE) AS cesta_marketplace_tt,
                COALESCE(dop.nome_operacao, '') AS movement_operation_name,
                COALESCE(d.segmento_nge, '') AS client_segment,
                COALESCE(d.cond_pag_atual, '') AS client_cond_pag_atual_codigo,
                COALESCE(NULLIF(dcc.descricao, ''), COALESCE(d.cond_pag_atual, ''), '') AS client_cond_pag_atual,
                COALESCE(d.media_faturamento_3m, '') AS client_media_faturamento_3m,
                COALESCE(d.limite_credito, '') AS client_limite_credito,
                COALESCE(d.limite_usado, '') AS client_limite_usado,
                COALESCE(d.saldo_aberto, '') AS client_saldo_aberto,
                COALESCE(d.status_pdv, '') AS client_status_pdv,
                COALESCE(d.cidade, '') AS client_cidade,
                COALESCE(d.bairro, '') AS client_bairro,
                pm.total_faturamento_3m,
                pm.total_pedidos_3m,
                pm.avg_order_value_3m,
                ins.inad_total_aberto,
                ins.inad_total_vencido,
                ins.inad_titulos_abertos,
                ins.inad_titulos_vencidos
            FROM {schema}.{relation} c
            LEFT JOIN dprecos_ref dp
              ON dp.codigo = c.produto_codigo
            LEFT JOIN dprodutos_ref prod
              ON prod.codigo = c.produto_codigo
            LEFT JOIN produto_cesta_metrics_ref pcm
              ON pcm.codigo = c.produto_codigo
            LEFT JOIN doperacoes_ref dop
              ON dop.tipo_movimento = COALESCE(NULLIF(LTRIM(COALESCE(c.tipo_movimento, ''), '0'), ''), '0')
            LEFT JOIN dcondicoes_ref dcp
              ON dcp.filial_condicao_key = {pedido_condicao_key_sql}
            LEFT JOIN dclientes_ref d
              ON d.filial = c.filial
             AND d.cod_pdv = c.cod_pdv
            LEFT JOIN dcondicoes_ref dcc
              ON dcc.filial_condicao_key = {cliente_condicao_key_sql}
            LEFT JOIN prazo_media_ref pm
              ON pm.filial = c.filial
             AND pm.cod_pdv = c.cod_pdv
            LEFT JOIN inad_stats_ref ins
              ON ins.filial = c.filial
             AND ins.cod_pdv = c.cod_pdv
            {where_clause}
            ORDER BY c.filial, c.pedido, c.cod_pdv, c.row_number
            LIMIT %s
            """
        ).format(
            ctes=sql.SQL(",\n").join(ctes),
            schema=sql.Identifier(self.schema),
            relation=sql.Identifier(relation),
            pedido_condicao_key_sql=sql.SQL(
                "CONCAT(COALESCE(c.filial, ''), '_', {codigo_sql})"
            ).format(codigo_sql=_normalized_code_sql(sql.SQL("c.payload ->> 'Cond Pgto'"))),
            cliente_condicao_key_sql=sql.SQL(
                "CONCAT(COALESCE(c.filial, ''), '_', {codigo_sql})"
            ).format(codigo_sql=_normalized_code_sql(sql.SQL("d.cond_pag_atual"))),
            where_clause=_where_clause(filters),
        )

    def _build_access_filter_parts(
        self,
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
    ) -> tuple[list[sql.Composed], list[Any]]:
        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        return filters, params

    def _apply_access_filter(
        self,
        filters: list[sql.Composed],
        params: list[Any],
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
    ) -> None:
        filial_codes = partition_filial_scopes(allowed_sectors)
        sector_keys, _legacy_sector_codes = partition_sector_scopes(allowed_sectors)
        gv_keys, dc_keys, legacy_gv_codes = partition_gv_scopes(allowed_gv_vdes)
        scope_filters: list[sql.Composed] = []
        if filial_codes:
            scope_filters.append(sql.SQL("COALESCE(c.filial, '') = ANY(%s)"))
            params.append(filial_codes)
        if sector_keys:
            scope_filters.append(sql.SQL("COALESCE(c.filial_setor_key, '') = ANY(%s)"))
            params.append(sector_keys)
        if gv_keys:
            scope_filters.append(sql.SQL("COALESCE(c.filial_gv_key, '') = ANY(%s)"))
            params.append(gv_keys)
        if legacy_gv_codes:
            normalized_filial_gv_suffix = sql.SQL(
                "COALESCE(NULLIF(LTRIM(REGEXP_REPLACE(SPLIT_PART(COALESCE(c.filial_gv_key, ''), '_', 2), '\\D+', '', 'g'), '0'), ''), '0')"
            )
            normalized_codigo_gv = _normalized_code_sql(sql.SQL("c.codigo_gv"))
            scope_filters.append(
                sql.SQL("({codigo_gv} = ANY(%s) OR {filial_gv_suffix} = ANY(%s))").format(
                    codigo_gv=normalized_codigo_gv,
                    filial_gv_suffix=normalized_filial_gv_suffix,
                )
            )
            params.extend([legacy_gv_codes, legacy_gv_codes])
        dc_scope_keys = [value[len("dc:") :] if value.startswith("dc:") else value for value in dc_keys]
        if dc_scope_keys:
            scope_filters.append(sql.SQL("COALESCE(c.filial_dc_key, '') = ANY(%s)"))
            params.append(dc_scope_keys)
        if scope_filters:
            filters.append(sql.SQL("(") + sql.SQL(" OR ").join(scope_filters) + sql.SQL(")"))
        elif _has_scope_values(allowed_sectors) or _has_scope_values(allowed_gv_vdes):
            filters.append(sql.SQL("FALSE"))

    def _ensure_ready(self) -> None:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de critica RN indisponivel.")

    def _require_source_relation(self, conn: Any) -> str:
        relation = self._resolve_source_relation(conn)
        if relation is None:
            raise RuntimeError("Views reports.critica_latest e reports.critica_rn_latest nao encontradas.")
        return relation

    def _resolve_source_relation(self, conn: Any) -> str | None:
        if self._relation_exists(conn, "critica_latest") and self._has_active_operacao_batches(conn):
            return "critica_latest"
        if self._relation_exists(conn, "critica_rn_latest"):
            return "critica_rn_latest"
        if self._relation_exists(conn, "critica_latest"):
            return "critica_latest"
        return None

    def _relation_exists(self, conn: Any, relation: str) -> bool:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT to_regclass(%s) AS relation_name", (f"{self.schema}.{relation}",))
            row = cur.fetchone() or {}
        return bool(row.get("relation_name"))

    def _has_active_operacao_batches(self, conn: Any) -> bool:
        if not self._relation_exists(conn, "dataset_state"):
            return False
        query = sql.SQL(
            """
            SELECT EXISTS (
                SELECT 1
                FROM {}.dataset_state
                WHERE dataset_name LIKE 'critica_op_%'
                  AND active_batch_id IS NOT NULL
            ) AS has_active
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            row = cur.fetchone() or {}
        return bool(row.get("has_active"))

    @contextmanager
    def _connect(self, row_factory: Any | None = None) -> Any:
        if self._pool is None:
            self._pool = get_connection_pool(self.database_url, connect_timeout_seconds=self.connect_timeout_seconds)
        with self._pool.connection() as conn:
            conn.row_factory = row_factory or tuple_row
            with conn.cursor() as cur:
                cur.execute("SET jit = off")
                cur.execute(sql.SQL("SET work_mem = {}").format(sql.Literal(REPORT_SESSION_WORK_MEM)))
            yield conn

    def _cache_status(self, payload: dict[str, Any]) -> None:
        self._status_cache = dict(payload)
        self._status_cache_expires_at = monotonic() + (300.0 if payload.get("ready") else 10.0)


def build_critica_rn_pdf(
    *,
    summary: CriticaRnSummary,
    records: list[CriticaRnRecord],
    generated_at: datetime | None = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    generated_at = generated_at or datetime.now()
    buffer = io.BytesIO()
    page_size = A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=9 * mm,
        rightMargin=9 * mm,
        topMargin=34 * mm,
        bottomMargin=12 * mm,
    )
    styles = _build_report_pdf_styles("CriticaDetalhe")

    elements: list[Any] = [
        Paragraph("RESUMO DA CRITICA", styles["section"]),
        _summary_table(summary, records, styles["table_header"], styles["table_cell"]),
        Spacer(1, 4),
        Paragraph("INDICADORES DE PROBLEMA", styles["section"]),
        _problem_table(summary, styles["table_header"], styles["table_cell"]),
    ]

    if records:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("PEDIDOS CRITICADOS", styles["section"]))
        elements.extend(_detail_report_tables(records, styles))
    else:
        elements.append(Paragraph("Nenhum item encontrado para o filtro informado.", styles["note"]))

    def draw_page_header(canvas: Any, doc_obj: Any) -> None:
        _draw_report_page_header(
            canvas,
            doc_obj,
            page_size=page_size,
            generated_at=generated_at,
            title="Critica dos Pedidos",
            summary=summary,
            records=records,
        )

    doc.build(elements, onFirstPage=draw_page_header, onLaterPages=_draw_report_page_background)
    return buffer.getvalue()


def build_critica_rn_summary_pdf(
    *,
    summary: CriticaRnSummary,
    records: list[CriticaRnRecord],
    generated_at: datetime | None = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    generated_at = generated_at or datetime.now()
    buffer = io.BytesIO()
    page_size = A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=9 * mm,
        rightMargin=9 * mm,
        topMargin=34 * mm,
        bottomMargin=12 * mm,
    )
    styles = _build_report_pdf_styles("CriticaResumo")

    elements: list[Any] = [
        Paragraph("RESUMO DA CRITICA", styles["section"]),
        _summary_table(summary, records, styles["table_header"], styles["table_cell"]),
    ]
    if records:
        elements.extend(
            [
                PageBreak(),
                Paragraph("PRODUTOS DO RELATORIO", styles["section"]),
                _product_summary_table(records, styles),
                PageBreak(),
            ]
        )
    else:
        elements.append(Spacer(1, 4))
    elements.extend(
        [
            Spacer(1, 4),
            Paragraph("INDICADORES DE PROBLEMA", styles["section"]),
            _problem_table(summary, styles["table_header"], styles["table_cell"]),
        ]
    )

    order_records = _build_order_records(records)
    if order_records:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("PEDIDOS CRITICADOS - RESUMO", styles["section"]))
        elements.append(_detail_order_table(order_records, styles))
    else:
        elements.append(Paragraph("Nenhum pedido encontrado para o filtro informado.", styles["note"]))

    def draw_page_header(canvas: Any, doc_obj: Any) -> None:
        _draw_report_page_header(
            canvas,
            doc_obj,
            page_size=page_size,
            generated_at=generated_at,
            title="Critica dos Pedidos - Resumo",
            summary=summary,
            records=records,
        )

    doc.build(elements, onFirstPage=draw_page_header, onLaterPages=_draw_report_page_background)
    return buffer.getvalue()


def build_critica_rn_gv_summary_pdf(
    *,
    summary: CriticaRnSummary,
    records: list[CriticaRnRecord],
    generated_at: datetime | None = None,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    generated_at = generated_at or datetime.now()
    buffer = io.BytesIO()
    page_size = A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=9 * mm,
        rightMargin=9 * mm,
        topMargin=34 * mm,
        bottomMargin=12 * mm,
    )
    styles = _build_report_pdf_styles("CriticaGvResumo")
    elements: list[Any] = [
        Paragraph("RESUMO GERENCIAL DA CRITICA", styles["section"]),
        _summary_table(summary, records, styles["table_header"], styles["table_cell"]),
        Spacer(1, 4),
        Paragraph("INDICADORES DE PROBLEMA", styles["section"]),
        _problem_table(summary, styles["table_header"], styles["table_cell"]),
        Spacer(1, 4),
        Paragraph("RESUMO POR SETOR", styles["section"]),
        _gv_sector_summary_table(records, styles),
        Spacer(1, 4),
        Paragraph("CIDADES POR SETOR", styles["section"]),
        *_gv_city_by_sector_tables(records, styles),
        Spacer(1, 4),
        Paragraph("PRODUTOS DO RELATORIO", styles["section"]),
        _product_summary_table(records, styles),
    ]

    def draw_page_header(canvas: Any, doc_obj: Any) -> None:
        _draw_report_page_header(
            canvas,
            doc_obj,
            page_size=page_size,
            generated_at=generated_at,
            title="Critica dos Pedidos - Resumo GV",
            summary=summary,
            records=records,
        )

    doc.build(elements, onFirstPage=draw_page_header, onLaterPages=_draw_report_page_background)
    return buffer.getvalue()


def _summary_table(summary: CriticaRnSummary, records: list[CriticaRnRecord], header_style: Any, value_style: Any) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    sectors_text = _format_compact_list(_collect_sectors(records), fallback="-")
    has_problem_counts = any(
        value > 0
        for value in (
            summary.problem_pedido_count,
            summary.problem_row_count,
            summary.duplicated_pedido_count,
            summary.duplicated_row_count,
        )
    )
    rows = [
        [
            Paragraph("Data Pedido", header_style),
            Paragraph("Atualizado em", header_style),
            Paragraph("Operacoes", header_style),
            Paragraph("Setores", header_style),
        ],
        [
            Paragraph(_format_date(summary.data_pedido), value_style),
            Paragraph(_escape(summary.planilha_atualizada_em or "-"), value_style),
            Paragraph(_escape(", ".join(summary.operations) or "-"), value_style),
            Paragraph(_escape(sectors_text), value_style),
        ],
        [
            Paragraph("Pedidos", header_style),
            Paragraph("Clientes", header_style),
            Paragraph("Itens", header_style),
            Paragraph("Valor Pedidos", header_style),
        ],
        [
            Paragraph(str(summary.pedido_count), value_style),
            Paragraph(str(summary.client_count), value_style),
            Paragraph(str(summary.row_count), value_style),
            Paragraph(_format_money(summary.total_pedido), value_style),
        ],
        [
            Paragraph("Peso Total", header_style),
            Paragraph("Total HL", header_style),
            Paragraph("NAB TT HL", header_style),
            Paragraph("High End HL", header_style),
        ],
        [
            Paragraph(_format_decimal(summary.peso_total), value_style),
            Paragraph(_format_decimal(summary.total_hectolitros), value_style),
            Paragraph(_format_decimal(summary.nab_tt_hectolitros), value_style),
            Paragraph(_format_decimal(summary.high_end_hectolitros), value_style),
        ],
        [
            Paragraph("Cerveja TT HL", header_style),
            Paragraph("Refri Zero HL", header_style),
            Paragraph("RGB / OW HL", header_style),
            Paragraph("Marketplace TT R$", header_style),
        ],
        [
            Paragraph(_format_decimal(summary.cerveja_tt_hectolitros), value_style),
            Paragraph(_format_decimal(summary.refri_zero_hectolitros), value_style),
            Paragraph(
                f"{_format_decimal(summary.cerveja_rgb_hectolitros)} / {_format_decimal(summary.cerveja_ow_hectolitros)}",
                value_style,
            ),
            Paragraph(_format_money(summary.marketplace_tt_faturamento), value_style),
        ],
        [
            Paragraph("Pedidos c/ Problema", header_style),
            Paragraph("Linhas c/ Problema", header_style),
            Paragraph("Pedidos Duplicados", header_style),
            Paragraph("Ped. c/ Prod. Dup.", header_style),
        ],
        [
            Paragraph(_alert_count_markup(summary.problem_pedido_count), value_style),
            Paragraph(_alert_count_markup(summary.problem_row_count), value_style),
            Paragraph(_alert_count_markup(summary.duplicated_pedido_count), value_style),
            Paragraph(_alert_count_markup(summary.duplicated_row_count), value_style),
        ],
    ]
    table = Table(rows, colWidths=[48 * mm, 48 * mm, 48 * mm, 48 * mm])
    table.setStyle(_report_table_style(header_row_indexes=(0, 2, 4, 6, 8), grid=True))
    return table


def _problem_table(summary: CriticaRnSummary, header_style: Any, value_style: Any) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    metrics = [
        ("Ocorrencias do relatorio", summary.rows_with_critica),
        ("Pedido duplicado", summary.duplicated_pedido_count),
        ("Produto duplicado no pedido", summary.duplicated_row_count),
        ("Preco divergente", summary.price_alert_count),
        ("Produto sem DPrecos", summary.missing_price_count),
        ("Pedido acima da media", summary.order_avg_alert_count),
        ("Cliente inadimplente", summary.inadimplente_count),
        ("Mapa 1 / buffer", summary.map_buffer_count),
        ("Mapa fora do vendedor", summary.map_outside_count),
        ("Cond. pag. divergente", summary.cond_divergence_count),
        ("Estouro de limite", summary.limit_alert_count),
    ]
    rows: list[list[Any]] = [
        [
            Paragraph("Problema", header_style),
            Paragraph("Pedidos", header_style),
            Paragraph("Problema", header_style),
            Paragraph("Pedidos", header_style),
        ]
    ]
    for index in range(0, len(metrics), 2):
        left_label, left_value = metrics[index]
        if index + 1 < len(metrics):
            right_label, right_value = metrics[index + 1]
        else:
            right_label, right_value = "", ""
        row_index = len(rows)
        rows.append(
            [
                Paragraph(_metric_label_markup(left_label, left_value), value_style),
                Paragraph(_alert_count_markup(left_value), value_style),
                Paragraph(_metric_label_markup(right_label, right_value), value_style),
                Paragraph("" if right_value == "" else _alert_count_markup(right_value), value_style),
            ]
        )
    table = Table(rows, colWidths=[72 * mm, 24 * mm, 72 * mm, 24 * mm])
    table.setStyle(_report_table_style(header_row_indexes=(0,), grid=True))
    return table


def _build_product_summary_rows(records: list[CriticaRnRecord]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        code = str(record.produto_codigo or "").strip()
        name = str(record.produto_descricao or record.nome_produto_original or "-").strip() or "-"
        key = (code, name)
        entry = grouped.setdefault(
            key,
            {
                "codigo": code,
                "nome": name,
                "quantidade": Decimal("0"),
                "hectolitros": Decimal("0"),
                "faturamento": Decimal("0"),
                "peso": Decimal("0"),
            },
        )
        entry["quantidade"] += record.quantidade or Decimal("0")
        entry["hectolitros"] += record.hectolitros or Decimal("0")
        entry["faturamento"] += _record_item_revenue(record)
        entry["peso"] += record.peso_item or Decimal("0")

    rows = list(grouped.values())
    rows.sort(key=lambda item: (_normalize_token(item["nome"]), _sort_key_numeric_text(item["codigo"])))
    return rows


def _product_summary_table(records: list[CriticaRnRecord], styles: dict[str, Any]) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    rows: list[list[Any]] = [
        [
            Paragraph("Produto", styles["table_header"]),
            Paragraph("Quantidade", styles["table_header"]),
            Paragraph("Hecto", styles["table_header"]),
            Paragraph("Faturamento", styles["table_header"]),
            Paragraph("Peso", styles["table_header"]),
        ]
    ]
    for item in _build_product_summary_rows(records):
        product_name = f"{item['codigo']} {item['nome']}".strip()
        rows.append(
            [
                Paragraph(_escape(product_name), styles["table_cell_bold"]),
                Paragraph(_escape(_format_decimal(item["quantidade"])), styles["table_cell_bold_right"]),
                Paragraph(_escape(_format_decimal(item["hectolitros"])), styles["table_cell_bold_right"]),
                Paragraph(_escape(_format_money(item["faturamento"])), styles["table_cell_bold_right"]),
                Paragraph(_escape(_format_decimal(item["peso"])), styles["table_cell_bold_right"]),
            ]
        )

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[96 * mm, 22 * mm, 20 * mm, 31 * mm, 23 * mm],
        splitByRow=1,
    )
    table.setStyle(_report_table_style(header_row_indexes=(0,), grid=True))
    return table


def _gv_sector_summary_table(records: list[CriticaRnRecord], styles: dict[str, Any]) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    rows: list[list[Any]] = [
        [
            Paragraph("Setor", styles["table_header"]),
            Paragraph("Pedidos", styles["table_header"]),
            Paragraph("Clientes", styles["table_header"]),
            Paragraph("Valor", styles["table_header"]),
            Paragraph("Peso", styles["table_header"]),
            Paragraph("HL", styles["table_header"]),
            Paragraph("Ped. c/ Prob.", styles["table_header"]),
            Paragraph("Principais indicadores", styles["table_header"]),
        ]
    ]
    grouped: dict[str, list[CriticaRnRecord]] = {}
    for record in records:
        grouped.setdefault(record.seller_code or f"{record.filial}_{record.setor}" or record.setor or "-", []).append(record)

    for sector_key in sorted(grouped, key=_sort_key_numeric_text):
        sector_records = grouped[sector_key]
        sector_summary = _summarize_records(sector_records)
        labels = _sector_problem_summary_labels(sector_summary)
        rows.append(
            [
                Paragraph(_escape(_format_sector_key_for_pdf(sector_key, sector_records)), styles["table_cell_bold"]),
                Paragraph(_escape(str(sector_summary.pedido_count)), styles["table_cell_bold_right"]),
                Paragraph(_escape(str(sector_summary.client_count)), styles["table_cell_bold_right"]),
                Paragraph(_escape(_format_money(sector_summary.total_pedido)), styles["table_cell_bold_right"]),
                Paragraph(_escape(_format_decimal(sector_summary.peso_total)), styles["table_cell_bold_right"]),
                Paragraph(_escape(_format_decimal(sector_summary.total_hectolitros)), styles["table_cell_bold_right"]),
                Paragraph(_alert_count_markup(sector_summary.problem_pedido_count), styles["table_cell_bold_right"]),
                Paragraph(_summary_problem_markup(labels) if labels else "OK", styles["occurrence"] if labels else styles["table_cell"]),
            ]
        )

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[18 * mm, 15 * mm, 16 * mm, 25 * mm, 19 * mm, 16 * mm, 19 * mm, 64 * mm],
        splitByRow=1,
    )
    table.setStyle(_report_table_style(header_row_indexes=(0,), grid=True))
    return table


def _gv_city_by_sector_tables(records: list[CriticaRnRecord], styles: dict[str, Any]) -> list[Any]:
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table

    grouped: dict[str, dict[str, list[CriticaRnRecord]]] = {}
    sector_labels: dict[str, str] = {}
    for record in records:
        sector_key = record.seller_code or f"{record.filial}_{record.setor}" or record.setor or "-"
        sector_labels.setdefault(sector_key, _format_sector_key_for_pdf(sector_key, [record]))
        city = str(record.client_cidade or "").strip() or "Sem cidade"
        grouped.setdefault(sector_key, {}).setdefault(city, []).append(record)

    flowables: list[Any] = []
    for sector_key in sorted(grouped, key=_sort_key_numeric_text):
        sector_records = [record for city_records in grouped[sector_key].values() for record in city_records]
        sector_summary = _summarize_records(sector_records)
        sector_title = (
            f"Setor {sector_labels.get(sector_key, sector_key)}  |  "
            f"{sector_summary.pedido_count} pedidos  |  "
            f"{sector_summary.client_count} clientes  |  "
            f"{_format_money(sector_summary.total_pedido)}"
        )
        rows: list[list[Any]] = [
            [
                Paragraph("Cidade", styles["table_header"]),
                Paragraph("Pedidos", styles["table_header"]),
                Paragraph("Clientes", styles["table_header"]),
                Paragraph("Valor", styles["table_header"]),
                Paragraph("Peso", styles["table_header"]),
                Paragraph("HL", styles["table_header"]),
            ]
        ]
        city_groups = grouped[sector_key]
        for city in sorted(city_groups, key=_normalize_token):
            city_summary = _summarize_records(city_groups[city])
            rows.append(
                [
                    Paragraph(_escape(city), styles["table_cell_bold"]),
                    Paragraph(_escape(str(city_summary.pedido_count)), styles["table_cell_bold_right"]),
                    Paragraph(_escape(str(city_summary.client_count)), styles["table_cell_bold_right"]),
                    Paragraph(_escape(_format_money(city_summary.total_pedido)), styles["table_cell_bold_right"]),
                    Paragraph(_escape(_format_decimal(city_summary.peso_total)), styles["table_cell_bold_right"]),
                    Paragraph(_escape(_format_decimal(city_summary.total_hectolitros)), styles["table_cell_bold_right"]),
                ]
            )
        title = Paragraph(_escape(sector_title), styles["section"])
        table = Table(
            rows,
            repeatRows=1,
            colWidths=[72 * mm, 20 * mm, 20 * mm, 34 * mm, 24 * mm, 22 * mm],
            splitByRow=1,
        )
        table.setStyle(
            _report_table_style(
                header_row_indexes=(0,),
                extra_commands=(
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
                ),
                grid=True,
            )
        )
        flowables.append(KeepTogether([title, table, Spacer(1, 3)]))
    if not flowables:
        flowables.append(Paragraph("Nenhuma cidade encontrada para o filtro informado.", styles["note"]))
    return flowables


def _format_sector_key_for_pdf(sector_key: str, records: list[CriticaRnRecord]) -> str:
    split = sector_key.split("_", 1)
    if len(split) == 2 and split[1]:
        return f"{split[0]}/{split[1]}"
    first = records[0] if records else None
    if first and first.filial and first.setor:
        return f"{first.filial}/{first.setor}"
    return sector_key or "-"


def _sector_problem_summary_labels(summary: CriticaRnSummary) -> tuple[str, ...]:
    metrics = [
        ("Ocorrencias", summary.rows_with_critica),
        ("Pedido duplicado", summary.duplicated_pedido_count),
        ("Produto duplicado", summary.duplicated_row_count),
        ("Preco", summary.price_alert_count),
        ("Sem DPrecos", summary.missing_price_count),
        ("Acima da media", summary.order_avg_alert_count),
        ("Inadimplente", summary.inadimplente_count),
        ("Buffer", summary.map_buffer_count),
        ("Mapa fora", summary.map_outside_count),
        ("Cond. divergente", summary.cond_divergence_count),
        ("Estouro limite", summary.limit_alert_count),
    ]
    return tuple(f"{label}: {count}" for label, count in metrics if count)


def _detail_report_tables(records: list[CriticaRnRecord], styles: dict[str, Any]) -> list[Any]:
    grouped = _ordered_detail_groups(records)
    return [
        _detail_report_table_from_groups(grouped[start : start + DETAIL_PDF_GROUPS_PER_TABLE], styles)
        for start in range(0, len(grouped), DETAIL_PDF_GROUPS_PER_TABLE)
    ]


def _detail_report_table(records: list[CriticaRnRecord], styles: dict[str, Any]) -> Any:
    return _detail_report_table_from_groups(_ordered_detail_groups(records), styles)


def _ordered_detail_groups(records: list[CriticaRnRecord]) -> list[list[CriticaRnRecord]]:
    grouped: dict[tuple[str, str], list[CriticaRnRecord]] = {}
    for record in records:
        grouped.setdefault((record.filial, record.pedido), []).append(record)

    return sorted(
        grouped.values(),
        key=lambda items: (
            0 if any(item.possui_problema for item in items) else 1,
            _order_movement_group_sort_key(items[0]),
            int(items[0].filial or "0") if str(items[0].filial or "").isdigit() else 999,
            items[0].cod_pdv,
            items[0].pedido,
        ),
    )


def _detail_report_table_from_groups(ordered_groups: list[list[CriticaRnRecord]], styles: dict[str, Any]) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    rows: list[list[Any]] = [
        [
            Paragraph("Pedido", styles["table_header"]),
            Paragraph("UNB/NB", styles["table_header"]),
            Paragraph("Cliente", styles["table_header"]),
            Paragraph("Tipo", styles["table_header"]),
            Paragraph("SC", styles["table_header"]),
            Paragraph("Ori", styles["table_header"]),
            Paragraph("Produto", styles["table_header"]),
            Paragraph("Qtde", styles["table_header"]),
            Paragraph("Un", styles["table_header"]),
            Paragraph("Preco Uni", styles["table_header"]),
            Paragraph("Pr s/ADF", styles["table_header"]),
            Paragraph("Ocor", styles["table_header"]),
        ]
    ]
    commands: list[tuple[Any, ...]] = []
    current_movement = ""
    for items in ordered_groups:
        items.sort(key=lambda item: (item.produto_codigo, item.nome_produto_original, item.produto_descricao))
        first = items[0]
        movement = _movement_display(first.operation_name, first.movement_operation_name)
        if movement != current_movement:
            current_movement = movement
            row_index = len(rows)
            rows.append([Paragraph(_escape(movement), styles["movement"])] + [""] * 11)
            commands.extend(
                [
                    ("SPAN", (0, row_index), (-1, row_index)),
                    ("BACKGROUND", (0, row_index), (-1, row_index), _theme_color("panel_bg_alt")),
                    ("TOPPADDING", (0, row_index), (-1, row_index), 4),
                    ("BOTTOMPADDING", (0, row_index), (-1, row_index), 3),
                ]
            )
        client_lines = _order_client_pdf_lines(first, items)
        detail_row_count = max(len(items), len(client_lines))
        for index in range(detail_row_count):
            record = items[index] if index < len(items) else None
            row_index = len(rows)
            item_problem_hint = _compact_problem_hint(record) if record is not None else ""
            rows.append(
                [
                    Paragraph((_escape(first.pedido) if index == 0 and first.pedido else ""), styles["table_cell_bold"]),
                    Paragraph((_escape(first.cod_pdv) if index == 0 and first.cod_pdv else ""), styles["table_cell_bold"]),
                    Paragraph(client_lines[index] if index < len(client_lines) else "", styles["table_cell_bold"]),
                    Paragraph(
                        (
                            _escape(_movement_display(first.operation_name, first.movement_operation_name))
                            if index == 0
                            else ""
                        ),
                        styles["table_cell_bold"],
                    ),
                    Paragraph(
                        (
                            _escape(_truncate(first.client_segment or first.segmento_cerveja or "-", 10))
                            if index == 0
                            else ""
                        ),
                        styles["table_cell_bold"],
                    ),
                    Paragraph(
                        (_escape(_truncate(first.origem_pedido or "-", 5)) if index == 0 else ""),
                        styles["table_cell_bold"],
                    ),
                    Paragraph(
                        _product_pdf_markup(record) if record is not None else "",
                        styles["table_cell_bold"],
                    ),
                    Paragraph(_escape(_format_decimal(record.quantidade)) if record is not None else "", styles["table_cell_bold_right"]),
                    Paragraph(_nowrap_markup(record.unid_venda or "-") if record is not None else "", styles["table_cell_bold"]),
                    Paragraph(_escape(_format_money_raw(record.preco_unitario)) if record is not None else "", styles["table_cell_bold_right"]),
                    Paragraph(_escape(_format_money_raw(record.preco_sem_adf)) if record is not None else "", styles["table_cell_bold_right"]),
                    Paragraph(
                        _alert_hint_markup(item_problem_hint) if item_problem_hint else "",
                        styles["table_alert"] if item_problem_hint else styles["table_cell"],
                    ),
                ]
            )

        problem_labels = _build_order_problem_labels(items)
        if problem_labels:
            problem_index = len(rows)
            rows.append(
                [
                    Paragraph(
                        _occurrence_markup(problem_labels),
                        styles["occurrence"],
                    )
                ]
                + [""] * 11
            )
            commands.extend(
                [
                    ("SPAN", (0, problem_index), (-1, problem_index)),
                    ("BACKGROUND", (0, problem_index), (-1, problem_index), _theme_color("danger_bg")),
                    ("BOX", (0, problem_index), (-1, problem_index), 0.35, _theme_color("danger_border")),
                    ("TOPPADDING", (0, problem_index), (-1, problem_index), 2),
                    ("BOTTOMPADDING", (0, problem_index), (-1, problem_index), 2),
                ]
            )

        spacer_index = len(rows)
        rows.append([""] * 12)
        commands.extend(
            [
                ("SPAN", (0, spacer_index), (-1, spacer_index)),
                ("BOTTOMPADDING", (0, spacer_index), (-1, spacer_index), 2),
            ]
        )

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[12 * mm, 13 * mm, 42 * mm, 11 * mm, 9 * mm, 8 * mm, 38 * mm, 8 * mm, 10 * mm, 14 * mm, 14 * mm, 13 * mm],
        splitByRow=1,
    )
    table.setStyle(_report_table_style(header_row_indexes=(0,), extra_commands=tuple(commands)))
    return table


def _detail_items_table(records: list[CriticaRnRecord], header_style: Any, value_style: Any) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    rows: list[list[Any]] = [
        [
            Paragraph("Pedido", header_style),
            Paragraph("Tipo Pedido", header_style),
            Paragraph("Setor", header_style),
            Paragraph("UNB / NB", header_style),
            Paragraph("Cliente", header_style),
            Paragraph("Produto", header_style),
            Paragraph("Qtde", header_style),
            Paragraph("Un", header_style),
            Paragraph("Preco Uni", header_style),
            Paragraph("Pr s/ADF", header_style),
            Paragraph("Vlr Ped", header_style),
            Paragraph("Ocorrencia", header_style),
        ]
    ]
    for record in records:
        item_problem_labels = _item_specific_problem_labels(record)
        rows.append(
            [
                Paragraph(_escape(record.pedido), value_style),
                Paragraph(_escape(_movement_display(record.operation_name, record.movement_operation_name)), value_style),
                Paragraph(_escape(record.setor or "-"), value_style),
                Paragraph(_escape(f"{record.filial} / {record.cod_pdv}"), value_style),
                Paragraph(_escape(_truncate(record.nome_pdv or "-", 32)), value_style),
                Paragraph(_escape(f"{record.produto_codigo} {record.produto_descricao or '-'}"), value_style),
                Paragraph(_escape(_format_decimal(record.quantidade)), value_style),
                Paragraph(_escape(record.unid_venda or "-"), value_style),
                Paragraph(_escape(_format_money(record.preco_unitario)), value_style),
                Paragraph(_escape(_format_money(record.preco_sem_adf)), value_style),
                Paragraph(_escape(_format_money(record.total_pedido)), value_style),
                Paragraph(_escape("; ".join(item_problem_labels) or ""), value_style),
            ]
        )
    table = Table(
        rows,
        repeatRows=1,
        colWidths=[12 * mm, 18 * mm, 10 * mm, 15 * mm, 27 * mm, 39 * mm, 8 * mm, 7 * mm, 12 * mm, 12 * mm, 14 * mm, 18 * mm],
    )
    table.setStyle(_report_table_style(header_row_indexes=(0,)))
    return table


def _detail_report_text(records: list[CriticaRnRecord]) -> str:
    grouped: dict[tuple[str, str], list[CriticaRnRecord]] = {}
    for record in records:
        grouped.setdefault((record.filial, record.pedido), []).append(record)

    ordered_groups = sorted(
        grouped.values(),
        key=lambda items: (
            0 if any(item.possui_problema for item in items) else 1,
            int(items[0].filial or "0") if str(items[0].filial or "").isdigit() else 999,
            items[0].pedido,
            items[0].cod_pdv,
        ),
    )

    lines = [
        "Pedido   UNB/NB  Cliente                      Set  Tipo             Seg       Ori   Produto                      Qtde Un Preco Uni Pr s/ADF Ocor",
        "-" * 146,
    ]
    for items in ordered_groups:
        items.sort(key=lambda item: (item.produto_codigo, item.nome_produto_original, item.produto_descricao))
        first = items[0]
        for index, record in enumerate(items):
            left_pedido = record.pedido if index == 0 else ""
            left_nb = f"{record.filial}/{record.cod_pdv}" if index == 0 else ""
            left_cliente = _truncate_mono(record.nome_pdv or "-", 26) if index == 0 else ""
            left_setor = (record.setor or "-") if index == 0 else ""
            left_tipo = _truncate_mono(_movement_display(record.operation_name, record.movement_operation_name), 16) if index == 0 else ""
            left_segment = _truncate_mono(record.client_segment or record.segmento_cerveja or "-", 9) if index == 0 else ""
            left_origem = _truncate_mono(record.origem_pedido or "-", 5) if index == 0 else ""
            product = _truncate_mono(f"{record.produto_codigo} {record.produto_descricao or '-'}", 28)
            problem_hint = _truncate_mono(_compact_problem_hint(record), 20)
            lines.append(
                f"{left_pedido:<8} {left_nb:<7} {left_cliente:<26} {left_setor:<4} {left_tipo:<16} {left_segment:<9} {left_origem:<5} "
                f"{product:<28} {_format_decimal(record.quantidade):>4} {record.unid_venda or '-':<3} "
                f"{_format_money_raw(record.preco_unitario):>9} {_format_money_raw(record.preco_sem_adf):>8} {problem_hint:<20}"
            )
        lines.append(f"         Setor do Pedido: {first.setor or '-'}")
        lines.append(f"         Peso do Pedido: {_format_decimal(_order_weight(items))}")
        lines.append(f"         Cond. Pag.: {first.cond_pag_pedido or '-'}")
        lines.append(f"         Valor do Pedido (R$): {_format_money_raw(first.total_pedido)}")
        order_problem_text = "; ".join(_build_order_problem_labels(items)) or "-"
        lines.append(f"         Ocorrencias: {order_problem_text}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _detail_order_table(order_records: list[CriticaRnOrderRecord], styles: dict[str, Any]) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table

    rows: list[list[Any]] = [
        [
            Paragraph("Pedido", styles["table_header"]),
            Paragraph("Tipo Pedido", styles["table_header"]),
            Paragraph("Setor", styles["table_header"]),
            Paragraph("UNB / NB", styles["table_header"]),
            Paragraph("Cliente", styles["table_header"]),
            Paragraph("Status", styles["table_header"]),
            Paragraph("Valor", styles["table_header"]),
            Paragraph("Ocorrencias", styles["table_header"]),
        ]
    ]
    commands: list[tuple[Any, ...]] = []
    for order in order_records:
        has_problem = bool(order.problem_labels)
        row_index = len(rows)
        rows.append(
            [
                Paragraph(_escape(order.pedido), styles["table_cell_bold"]),
                Paragraph(
                    _escape(_movement_display(order.operation_name, order.movement_operation_name)),
                    styles["table_cell_bold"],
                ),
                Paragraph(_escape(order.setor or "-"), styles["table_cell_bold"]),
                Paragraph(_escape(order.cod_pdv), styles["table_cell_bold"]),
                Paragraph(_summary_order_client_markup(order), styles["table_cell_bold"]),
                Paragraph(_escape(order.status_pedido or "-"), styles["table_cell_bold"]),
                Paragraph(_nowrap_markup(_format_money(order.total_pedido)), styles["table_cell_bold"]),
                Paragraph(
                    _summary_problem_markup(order.problem_labels) if has_problem else "OK",
                    styles["occurrence"] if has_problem else styles["table_cell"],
                ),
            ]
        )
        if has_problem:
            commands.extend(
                [
                    ("BACKGROUND", (7, row_index), (7, row_index), _theme_color("danger_bg")),
                    ("BOX", (7, row_index), (7, row_index), 0.35, _theme_color("danger_border")),
                    ("LEFTPADDING", (7, row_index), (7, row_index), 4),
                    ("RIGHTPADDING", (7, row_index), (7, row_index), 4),
                    ("TOPPADDING", (7, row_index), (7, row_index), 4),
                    ("BOTTOMPADDING", (7, row_index), (7, row_index), 4),
                ]
            )
    table = Table(rows, repeatRows=1, colWidths=[15 * mm, 21 * mm, 11 * mm, 16 * mm, 34 * mm, 16 * mm, 17 * mm, 62 * mm])
    table.setStyle(_report_table_style(header_row_indexes=(0,), extra_commands=tuple(commands), grid=True))
    return table


def _summary_order_client_markup(order: CriticaRnOrderRecord) -> str:
    lines = [_escape(_truncate(order.nome_pdv or "-", 42))]
    if order.peso_pedido > 0:
        lines.append(
            f'<font color="{PDF_THEME["text_primary"]}">{_nowrap_markup(f"Peso do Pedido(Kg):{_format_decimal(order.peso_pedido)}")}</font>'
        )
    if order.cond_pag_pedido:
        lines.append(
            f'<font color="{PDF_THEME["text_primary"]}">{_nowrap_markup(f"Cond.Pag.:{_truncate(order.cond_pag_pedido, 40)}")}</font>'
        )
    return "<br/>".join(lines)


def _build_report_pdf_styles(prefix: str) -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    return {
        "section": ParagraphStyle(
            f"{prefix}Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=9.8,
            leading=10.7,
            alignment=TA_LEFT,
            spaceBefore=4,
            spaceAfter=2,
            textColor=_theme_color("accent"),
        ),
        "table_header": ParagraphStyle(
            f"{prefix}TableHeader",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.0,
            leading=7.8,
            alignment=TA_LEFT,
            textColor=_theme_color("text_primary"),
        ),
        "table_cell": ParagraphStyle(
            f"{prefix}TableCell",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=6.7,
            leading=7.5,
            alignment=TA_LEFT,
            textColor=_theme_color("text_primary"),
        ),
        "table_cell_right": ParagraphStyle(
            f"{prefix}TableCellRight",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=6.7,
            leading=7.5,
            alignment=2,
            textColor=_theme_color("text_primary"),
        ),
        "table_cell_bold": ParagraphStyle(
            f"{prefix}TableCellBold",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.0,
            leading=7.8,
            alignment=TA_LEFT,
            textColor=_theme_color("text_primary"),
        ),
        "table_cell_bold_right": ParagraphStyle(
            f"{prefix}TableCellBoldRight",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.0,
            leading=7.8,
            alignment=2,
            textColor=_theme_color("text_primary"),
        ),
        "table_alert": ParagraphStyle(
            f"{prefix}TableAlert",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.0,
            leading=7.9,
            alignment=TA_LEFT,
            textColor=_theme_color("danger"),
        ),
        "movement": ParagraphStyle(
            f"{prefix}Movement",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.4,
            leading=8.2,
            alignment=TA_LEFT,
            textColor=_theme_color("accent"),
        ),
        "occurrence": ParagraphStyle(
            f"{prefix}Occurrence",
            parent=styles["BodyText"],
            fontName="Courier-Bold",
            fontSize=7.0,
            leading=8.4,
            alignment=TA_LEFT,
            textColor=_theme_color("text_primary"),
        ),
        "mono": ParagraphStyle(
            f"{prefix}Mono",
            parent=styles["Code"],
            fontName="Courier-Bold",
            fontSize=6.8,
            leading=7.8,
            alignment=TA_LEFT,
            spaceAfter=0,
            spaceBefore=0,
            textColor=_theme_color("text_primary"),
        ),
        "note": ParagraphStyle(
            f"{prefix}Note",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=8.0,
            alignment=TA_LEFT,
            textColor=_theme_color("text_muted"),
        ),
    }


def _report_table_style(
    *,
    header_row_indexes: tuple[int, ...],
    extra_commands: tuple[tuple[Any, ...], ...] = (),
    grid: bool = False,
) -> Any:
    from reportlab.platypus import TableStyle

    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
        ("BACKGROUND", (0, 0), (-1, -1), _theme_color("panel_bg")),
    ]
    if grid:
        commands.append(("ROWBACKGROUNDS", (0, 0), (-1, -1), [_theme_color("panel_bg"), _theme_color("panel_bg_alt")]))
        commands.append(("GRID", (0, 0), (-1, -1), 0.25, _theme_color("border")))
        for header_row_index in header_row_indexes:
            commands.extend(
                [
                    ("BACKGROUND", (0, header_row_index), (-1, header_row_index), _theme_color("header_bg")),
                    ("LINEBELOW", (0, header_row_index), (-1, header_row_index), 0.4, _theme_color("border_strong")),
                ]
            )
    commands.extend(extra_commands)
    return TableStyle(commands)


def _draw_report_page_background(canvas: Any, doc_obj: Any) -> None:
    width, height = doc_obj.pagesize
    canvas.saveState()
    canvas.setFillColor(_theme_color("page_bg"))
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.restoreState()


def _draw_report_page_header(
    canvas: Any,
    doc_obj: Any,
    *,
    page_size: tuple[float, float],
    generated_at: datetime,
    title: str,
    summary: CriticaRnSummary,
    records: list[CriticaRnRecord],
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    width, height = page_size
    operations_text = _format_compact_list(summary.operations, fallback="-")
    sectors_text = _format_compact_list(_collect_sectors(records), fallback="-")
    stats_line = (
        f"Data Pedido: {_format_date(summary.data_pedido)}      "
        f"Pedidos: {summary.pedido_count}      "
        f"Valor: {_format_money(summary.total_pedido)}      "
        f"Peso: {_format_decimal(summary.peso_total)}      "
        f"HL: {_format_decimal(summary.total_hectolitros)}"
    )
    canvas.saveState()
    canvas.setFillColor(_theme_color("page_bg"))
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(_theme_color("panel_bg"))
    canvas.rect(7 * mm, height - 30 * mm, width - 14 * mm, 23 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(_theme_color("border_strong"))
    canvas.rect(7 * mm, height - 30 * mm, width - 14 * mm, 23 * mm, fill=0, stroke=1)
    canvas.setFillColor(_theme_color("text_primary"))
    canvas.setFont("Helvetica", 7)
    canvas.drawString(9 * mm, height - 9 * mm, "PW02041R-l-Bot API")
    canvas.drawCentredString(width / 2, height - 9 * mm, title)
    canvas.drawRightString(width - 9 * mm, height - 9 * mm, generated_at.strftime("%d/%m/%Y"))
    canvas.setFillColor(_theme_color("text_muted"))
    canvas.setFont("Helvetica", 6.5)
    canvas.drawString(9 * mm, height - 13 * mm, "Distribuidora de Bebidas Pau Brasil LTDA")
    canvas.drawRightString(width - 9 * mm, height - 13 * mm, f"Pag. {doc_obj.page}")
    canvas.drawString(9 * mm, height - 17 * mm, "Versao: Bot API      Rotina: 03.01.11      Usuario: BOT")
    canvas.drawRightString(width - 9 * mm, height - 17 * mm, generated_at.strftime("%H:%M"))
    canvas.drawString(9 * mm, height - 21 * mm, _truncate(f"Operacao(s): {operations_text} | Setor(es): {sectors_text}", 112))
    canvas.drawString(9 * mm, height - 25 * mm, _truncate(stats_line, 112))
    canvas.setStrokeColor(_theme_color("accent"))
    canvas.line(9 * mm, height - 28 * mm, width - 9 * mm, height - 28 * mm)
    canvas.restoreState()


def _collect_sectors(records: list[CriticaRnRecord]) -> tuple[str, ...]:
    sectors = sorted({record.setor for record in records if str(record.setor or "").strip()})
    return tuple(sectors)


def _format_compact_list(values: tuple[str, ...] | list[str], *, fallback: str = "-") -> str:
    cleaned = [str(value).strip() for value in values if str(value or "").strip()]
    if not cleaned:
        return fallback
    if len(cleaned) <= 8:
        return ", ".join(cleaned)
    return ", ".join(cleaned[:8]) + f" +{len(cleaned) - 8}"


def _date_cache_key(value: date | None) -> str:
    return value.isoformat() if value else ""


def _scope_cache_key(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    return tuple(sorted({str(value or "").strip() for value in values or () if str(value or "").strip()}))


def _extract_critica_scope_filiais(
    *,
    allowed_sectors: list[str] | tuple[str, ...] | None = None,
    allowed_gv_vdes: list[str] | tuple[str, ...] | None = None,
    filial: str | None = None,
) -> set[str]:
    filiais: set[str] = set()
    direct_filial = str(filial or "").strip()
    if direct_filial:
        filiais.add(direct_filial)
    sector_keys, _legacy_sector_codes = partition_sector_scopes(allowed_sectors)
    for sector_key in sector_keys:
        operation, _sep, _scope = str(sector_key or "").partition("_")
        if operation:
            filiais.add(operation)
    gv_keys, dc_keys, _legacy_gv_codes = partition_gv_scopes(allowed_gv_vdes)
    for scope_key in [*gv_keys, *dc_keys]:
        operation, _sep, _scope = str(scope_key or "").partition("_")
        if operation:
            filiais.add(operation)
    return {value for value in filiais if value}


def _group_records_for_pdf_scopes(
    records: list[CriticaRnRecord],
    *,
    scope_types: tuple[str, ...],
) -> dict[tuple[str, str], list[CriticaRnRecord]]:
    grouped: dict[tuple[str, str], list[CriticaRnRecord]] = {}
    include_sector = PDF_SCOPE_SECTOR in scope_types
    include_gv = PDF_SCOPE_GV in scope_types
    for record in records:
        if include_sector and record.seller_code:
            grouped.setdefault((PDF_SCOPE_SECTOR, record.seller_code), []).append(record)
        if include_gv and record.manager_code:
            grouped.setdefault((PDF_SCOPE_GV, record.manager_code), []).append(record)
    return grouped


def _resolve_pdf_cache_scope(
    allowed_sectors: list[str] | tuple[str, ...] | None,
    allowed_gv_vdes: list[str] | tuple[str, ...] | None,
) -> tuple[str, str] | None:
    sector_keys, _legacy_sector_codes = partition_sector_scopes(allowed_sectors)
    cleaned_sector_keys = tuple(sorted({value for value in sector_keys if value}, key=_sort_key_numeric_text))
    if len(cleaned_sector_keys) == 1:
        return PDF_SCOPE_SECTOR, cleaned_sector_keys[0]

    gv_keys, dc_keys, _legacy_gv_codes = partition_gv_scopes(allowed_gv_vdes)
    cleaned_gv_keys = tuple(sorted({value for value in gv_keys if value}, key=_sort_key_numeric_text))
    if len(cleaned_gv_keys) == 1 and not dc_keys:
        return PDF_SCOPE_GV, cleaned_gv_keys[0]
    return None


def _uses_legacy_gv_scope_only(allowed_gv_vdes: list[str] | tuple[str, ...] | None) -> bool:
    if not allowed_gv_vdes:
        return False
    gv_keys, dc_keys, legacy_gv_codes = partition_gv_scopes(allowed_gv_vdes)
    return bool(legacy_gv_codes) and not gv_keys and not dc_keys


def _summary_from_cache_payload(payload: dict[str, Any]) -> CriticaRnSummary:
    data_pedido_raw = str(payload.get("data_pedido") or "").strip()
    data_pedido = date.fromisoformat(data_pedido_raw) if data_pedido_raw else None
    return CriticaRnSummary(
        data_pedido=data_pedido,
        row_count=int(payload.get("row_count") or 0),
        pedido_count=int(payload.get("pedido_count") or 0),
        client_count=int(payload.get("client_count") or 0),
        problem_row_count=int(payload.get("problem_row_count") or 0),
        problem_pedido_count=int(payload.get("problem_pedido_count") or 0),
        rows_with_critica=int(payload.get("rows_with_critica") or 0),
        duplicated_row_count=int(payload.get("duplicated_row_count") or 0),
        price_alert_count=int(payload.get("price_alert_count") or 0),
        missing_price_count=int(payload.get("missing_price_count") or 0),
        total_pedido=_decimal(payload.get("total_pedido")),
        planilha_atualizada_em=str(payload.get("planilha_atualizada_em") or "-"),
        operations=tuple(str(value) for value in payload.get("operations") or () if str(value or "").strip()),
        peso_total=_decimal(payload.get("peso_total")),
        total_hectolitros=_decimal(payload.get("total_hectolitros")),
        nab_tt_hectolitros=_decimal(payload.get("nab_tt_hectolitros")),
        high_end_hectolitros=_decimal(payload.get("high_end_hectolitros")),
        cerveja_tt_hectolitros=_decimal(payload.get("cerveja_tt_hectolitros")),
        refri_zero_hectolitros=_decimal(payload.get("refri_zero_hectolitros")),
        cerveja_rgb_hectolitros=_decimal(payload.get("cerveja_rgb_hectolitros")),
        cerveja_ow_hectolitros=_decimal(payload.get("cerveja_ow_hectolitros")),
        marketplace_tt_hectolitros=_decimal(payload.get("marketplace_tt_hectolitros")),
        marketplace_tt_faturamento=_decimal(payload.get("marketplace_tt_faturamento")),
        duplicated_pedido_count=int(payload.get("duplicated_pedido_count") or 0),
        order_avg_alert_count=int(payload.get("order_avg_alert_count") or 0),
        inadimplente_count=int(payload.get("inadimplente_count") or 0),
        multipack_violation_count=int(payload.get("multipack_violation_count") or 0),
        map_buffer_count=int(payload.get("map_buffer_count") or 0),
        map_outside_count=int(payload.get("map_outside_count") or 0),
        cond_divergence_count=int(payload.get("cond_divergence_count") or 0),
        limit_alert_count=int(payload.get("limit_alert_count") or 0),
    )


def _sort_key_numeric_text(value: str) -> tuple[int, Any]:
    text = str(value or "").strip()
    return (0, int(text)) if text.isdigit() else (1, text)


def _movement_display(operation_name: str, movement_operation_name: str) -> str:
    operation_label = str(movement_operation_name or operation_name or "-").strip()
    return _truncate(operation_label, 18)


def _compact_problem_hint(record: CriticaRnRecord) -> str:
    item_labels = _item_specific_problem_labels(record)
    if not item_labels:
        return ""
    first = str(item_labels[0] or "").strip()
    lowered = _normalize_token(first)
    if "possivel pedido duplicado" in lowered:
        return "Ped. duplicado"
    if "produto repetido" in lowered:
        return "Prod. duplicado"
    if "falta" in lowered:
        return "Falta"
    if "ocorrencia do relatorio" in lowered or "ocorrencia complementar" in lowered:
        return "Ocorrencia"
    if "preco" in lowered:
        return "Preco"
    if "mapa" in lowered or "buffer" in lowered:
        return "Mapa"
    if "condicao" in lowered:
        return "Condicao"
    if "limite" in lowered:
        return "Limite"
    if "inadimplente" in lowered or "vencido" in lowered:
        return "Inadimplencia"
    return first


def _item_specific_problem_labels(record: CriticaRnRecord) -> tuple[str, ...]:
    return _dedupe_labels([label for label in record.problemas if _is_item_specific_problem_label(label)])


def _is_item_specific_problem_label(label: str) -> bool:
    normalized = _normalize_token(label)
    if not normalized:
        return False
    if (
        ("ocorrencia do relatorio" in normalized or "ocorrencia complementar" in normalized)
        and "falta" in normalized
    ):
        return True
    general_prefixes = (
        "ocorrencia do relatorio",
        "ocorrencia complementar",
        "possivel pedido duplicado",
        "pedido acima da media",
        "cliente com",
        "pedido em buffer",
        "pedido digitado fora",
        "com este pedido",
        "condicao de pagamento",
    )
    if normalized.startswith(general_prefixes):
        return False
    return (
        normalized.startswith("produto ")
        or "produto repetido" in normalized
        or "preco" in normalized
        or "dprecos" in normalized
    )


def _build_order_problem_labels(records: list[CriticaRnRecord]) -> tuple[str, ...]:
    labels: list[str] = []
    for record in records:
        labels.extend(record.problemas)
    return _dedupe_labels(labels)


def _nowrap_markup(value: Any) -> str:
    return _escape(str(value or "")).replace(" ", "&#160;")


def _product_pdf_markup(record: CriticaRnRecord) -> str:
    product_name = f"{record.produto_codigo} {record.produto_descricao or '-'}".strip()
    return f'<font size="6.2">{_nowrap_markup(_truncate(product_name, 34))}</font>'


def _alert_hint_markup(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f'<font color="{PDF_THEME["danger"]}"><b>{_escape(text)}</b></font>'


def _has_positive_count(value: Any) -> bool:
    try:
        return int(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _alert_count_markup(value: Any) -> str:
    text = str(value if value is not None else "0")
    if _has_positive_count(value):
        return _alert_hint_markup(text)
    return _escape(text)


def _metric_label_markup(label: str, value: Any) -> str:
    text = str(label or "").strip()
    if not text:
        return ""
    if _has_positive_count(value):
        return _alert_hint_markup(text)
    return _escape(text)


def _summary_problem_markup(labels: tuple[str, ...]) -> str:
    if not labels:
        return "OK"
    return "<br/>".join(_problem_label_markup(label) for label in labels)


def _occurrence_markup(labels: tuple[str, ...]) -> str:
    if not labels:
        return ""
    rendered = [_problem_label_markup(label) for label in labels]
    return f'<font color="{PDF_THEME["danger"]}"><b>Ocorrencias:</b></font><br/>' + "<br/>".join(rendered)


def _problem_label_markup(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return ""
    return f'<font color="{PDF_THEME["danger"]}"><b>{_escape(text)}</b></font>'


def _theme_color(name: str) -> Any:
    from reportlab.lib import colors

    return colors.HexColor(PDF_THEME[name])


def _row_to_record(row: dict[str, Any]) -> CriticaRnRecord:
    filial = normalize_stored_scope_value(str(row.get("filial") or ""))
    tipo_movimento = normalize_stored_scope_value(str(row.get("tipo_movimento") or ""))
    produto_descricao = (
        str(row.get("nome_produto_original") or "").strip()
        or str(row.get("produto_dprecos") or "").strip()
        or str(row.get("dprecos_produto") or "").strip()
    )
    caixa_min = _coalesce_first_decimal(
        _nullable_decimal(row.get("caixa_min")),
        _nullable_decimal(row.get("asr_preco")),
        _nullable_decimal(row.get("sub_preco")),
        _nullable_decimal(row.get("frio_preco")),
    )
    caixa_max = _coalesce_first_decimal(
        _nullable_decimal(row.get("caixa_max")),
        _nullable_decimal(row.get("asr_preco")),
        _nullable_decimal(row.get("sub_preco")),
        _nullable_decimal(row.get("frio_preco")),
    )
    ttc_ref = _coalesce_first_decimal(_nullable_decimal(row.get("ttc_min")), _nullable_decimal(row.get("ttc_preco")))
    client_limite_credito = _decimal(row.get("client_limite_credito"))
    client_limite_usado = _decimal(row.get("client_limite_usado"))
    client_saldo_aberto = _decimal(row.get("client_saldo_aberto"))
    avg_order_value_3m = _decimal(row.get("avg_order_value_3m"))
    total_pedido = _decimal(row.get("total_pedido"))
    quantidade = _decimal(row.get("quantidade"))
    fator_hecto = _decimal(row.get("produto_fator_hecto"))
    hectolitros = fator_hecto * quantidade
    produto_peso_bruto = _decimal(row.get("produto_peso_bruto"))
    peso_item = produto_peso_bruto * quantidade
    valor_estouro_limite = _decimal(row.get("valor_estouro_limite_text"))
    mapa_codigo = normalize_stored_scope_value(str(row.get("mapa_codigo") or ""))
    vendedor_codigo = normalize_stored_scope_value(
        str(row.get("vendedor_codigo") or row.get("setor") or row.get("codigo_gv") or "")
    )
    map_status = _map_status(mapa_codigo=mapa_codigo, vendedor_codigo=vendedor_codigo)
    cond_pag_pedido_codigo = normalize_stored_scope_value(
        str(row.get("cond_pag_pedido_codigo") or row.get("cond_pag_pedido") or "")
    )
    client_cond_pag_atual_codigo = normalize_stored_scope_value(
        str(row.get("client_cond_pag_atual_codigo") or row.get("client_cond_pag_atual") or "")
    )
    cond_pag_pedido = str(row.get("cond_pag_pedido") or row.get("cond_pag_pedido_codigo") or "").strip()
    client_cond_pag_atual = str(row.get("client_cond_pag_atual") or row.get("client_cond_pag_atual_codigo") or "").strip()
    allow_credit_and_condition_checks = _supports_credit_and_condition_checks(tipo_movimento)
    allow_limit_checks = allow_credit_and_condition_checks and not _is_cash_payment_condition(
        cond_pag_pedido_codigo,
        cond_pag_pedido,
    )
    cond_divergente = bool(
        allow_credit_and_condition_checks
        and cond_pag_pedido_codigo
        and client_cond_pag_atual_codigo
        and cond_pag_pedido_codigo != client_cond_pag_atual_codigo
    )
    price_reference, price_reference_label = _resolve_price_reference(
        filial=filial,
        unit_label=str(row.get("unid_venda") or "").strip(),
        product_name=produto_descricao,
        client_segment=str(row.get("client_segment") or "").strip(),
        ttc_ref=ttc_ref,
        caixa_asr=_nullable_decimal(row.get("asr_preco")),
        caixa_sub=_nullable_decimal(row.get("sub_preco")),
        caixa_frio=_nullable_decimal(row.get("frio_preco")),
    )
    price_delta_pct = _calculate_price_delta_pct(
        filial=filial,
        unit_label=str(row.get("unid_venda") or "").strip(),
        product_name=produto_descricao,
        actual_price=_decimal(row.get("preco_unitario")),
        reference_price=price_reference,
    )
    order_above_average = False
    computed_limit_exceeded = Decimal("0")
    if allow_limit_checks and client_limite_credito > 0:
        computed_limit_exceeded = max((client_limite_usado + total_pedido) - client_limite_credito, Decimal("0"))
    if allow_limit_checks:
        limit_exceeded_amount = valor_estouro_limite if valor_estouro_limite > 0 else computed_limit_exceeded
    else:
        limit_exceeded_amount = Decimal("0")
    record = CriticaRnRecord(
        filial=normalize_stored_scope_value(str(row.get("filial") or "")),
        pedido=normalize_stored_scope_value(str(row.get("pedido") or "")),
        data_pedido=row.get("data_pedido") if isinstance(row.get("data_pedido"), date) else None,
        operacao=normalize_stored_scope_value(str(row.get("operacao") or "")),
        cod_pdv=normalize_stored_scope_value(str(row.get("cod_pdv") or "")),
        nome_pdv=str(row.get("nome_pdv") or "").strip(),
        setor=normalize_stored_scope_value(str(row.get("setor") or "")),
        seller_code=normalize_stored_scope_value(str(row.get("filial_setor_key") or "")),
        manager_code=normalize_stored_scope_value(str(row.get("filial_gv_key") or "")),
        status_pedido=str(row.get("status_pedido") or "").strip(),
        total_pedido=_decimal(row.get("total_pedido")),
        total_cliente=_decimal(row.get("total_cliente")),
        critica_text=str(row.get("critica_text") or "").strip(),
        produto_codigo=normalize_stored_scope_value(str(row.get("produto_codigo") or "")),
        produto_descricao=str(row.get("produto_descricao_pdf") or row.get("produto_dprecos") or "").strip(),
        quantidade=quantidade,
        unid_venda=str(row.get("unid_venda") or "").strip(),
        preco_unitario=_decimal(row.get("preco_unitario")),
        preco_sem_adf=_decimal(row.get("preco_sem_adf")),
        minimo_politica=_decimal(row.get("minimo_politica")),
        tipo_movimento=tipo_movimento,
        codigo_gv=normalize_stored_scope_value(str(row.get("codigo_gv") or "")),
        codigo_pgv=normalize_stored_scope_value(str(row.get("codigo_pgv") or "")),
        pedido_linhas=int(row.get("pedido_linhas") or 0),
        pedido_produto_linhas=int(row.get("pedido_produto_linhas") or 0),
        pedido_produto_duplicado=bool(row.get("pedido_produto_duplicado")),
        produto_encontrado_dprecos=bool(row.get("produto_encontrado_dprecos")),
        preco_status=str(row.get("preco_status") or "").strip(),
        ttc_min=ttc_ref,
        ttc_max=ttc_ref,
        caixa_min=caixa_min,
        caixa_max=caixa_max,
        problemas=(),
        planilha_atualizada_em=_format_updated_at(row.get("reference_date"), row.get("batch_imported_at")),
        operation_name=FILIAL_LABELS.get(filial, filial),
        produto_peso_bruto=produto_peso_bruto,
        peso_item=peso_item,
        movement_operation_name=str(row.get("movement_operation_name") or "").strip(),
        nome_produto_original=str(row.get("nome_produto_original") or "").strip(),
        mapa_codigo=mapa_codigo,
        vendedor_codigo=vendedor_codigo,
        area_codigo=normalize_stored_scope_value(str(row.get("area_codigo") or "")),
        cond_pag_pedido_codigo=cond_pag_pedido_codigo,
        cond_pag_pedido=cond_pag_pedido,
        forma_pagto=str(row.get("forma_pgto") or "").strip(),
        prazo_dias=str(row.get("prazo_dias") or "").strip(),
        segmento_cerveja=str(row.get("segmento_cerveja") or "").strip(),
        origem_pedido=str(row.get("origem_pedido") or "").strip(),
        valor_estouro_limite=valor_estouro_limite,
        maior_atraso_pedido=str(row.get("maior_atraso_pedido") or "").strip(),
        ocorrencia_1=str(row.get("ocorrencia_1") or "").strip(),
        ocorrencia_2=str(row.get("ocorrencia_2") or "").strip(),
        te_codigo=normalize_stored_scope_value(str(row.get("te_codigo") or "")),
        client_segment=str(row.get("client_segment") or "").strip(),
        client_cond_pag_atual_codigo=client_cond_pag_atual_codigo,
        client_cond_pag_atual=client_cond_pag_atual,
        client_media_faturamento_3m=_decimal(row.get("client_media_faturamento_3m")),
        client_limite_credito=client_limite_credito,
        client_limite_usado=client_limite_usado,
        client_saldo_aberto=client_saldo_aberto,
        client_status_pdv=str(row.get("client_status_pdv") or "").strip(),
        client_cidade=str(row.get("client_cidade") or "").strip(),
        client_bairro=str(row.get("client_bairro") or "").strip(),
        avg_order_value_3m=avg_order_value_3m,
        avg_order_total_3m=_decimal(row.get("total_faturamento_3m")),
        avg_order_count_3m=_decimal(row.get("total_pedidos_3m")),
        inad_total_aberto=_decimal(row.get("inad_total_aberto")),
        inad_total_vencido=_decimal(row.get("inad_total_vencido")),
        inad_titulos_abertos=int(row.get("inad_titulos_abertos") or 0),
        inad_titulos_vencidos=int(row.get("inad_titulos_vencidos") or 0),
        multipack_item=_is_multipack_item(produto_descricao),
        multipack_allowed=_segment_allows_multipack(str(row.get("client_segment") or "")),
        map_status=map_status,
        cond_divergente=cond_divergente,
        order_above_average=order_above_average,
        limit_exceeded_amount=limit_exceeded_amount,
        price_reference=price_reference,
        price_reference_label=price_reference_label,
        price_delta_pct=price_delta_pct,
        fator_hecto=fator_hecto,
        hectolitros=hectolitros,
        cesta_nab_tt=bool(row.get("cesta_nab_tt")),
        cesta_high_end=bool(row.get("cesta_high_end")),
        cesta_cerveja_tt=bool(row.get("cesta_cerveja_tt")),
        cesta_refri_zero=bool(row.get("cesta_refri_zero")),
        cesta_cerveja_rgb=bool(row.get("cesta_cerveja_rgb")),
        cesta_cerveja_ow=bool(row.get("cesta_cerveja_ow")),
        cesta_marketplace_tt=bool(row.get("cesta_marketplace_tt")),
    )
    return replace(record, problemas=_build_problem_labels(record))


def _row_to_duplicate_context_record(row: dict[str, Any]) -> CriticaRnRecord:
    return CriticaRnRecord(
        filial=normalize_stored_scope_value(str(row.get("filial") or "")),
        pedido=normalize_stored_scope_value(str(row.get("pedido") or "")),
        data_pedido=row.get("data_pedido") if isinstance(row.get("data_pedido"), date) else None,
        operacao="",
        cod_pdv=normalize_stored_scope_value(str(row.get("cod_pdv") or "")),
        nome_pdv="",
        setor="",
        seller_code="",
        manager_code="",
        status_pedido="",
        total_pedido=Decimal("0"),
        total_cliente=Decimal("0"),
        critica_text="",
        produto_codigo=normalize_stored_scope_value(str(row.get("produto_codigo") or "")),
        produto_descricao=str(row.get("produto_descricao") or "").strip(),
        quantidade=_decimal(row.get("quantidade")),
        unid_venda=str(row.get("unid_venda") or "").strip(),
        preco_unitario=Decimal("0"),
        preco_sem_adf=Decimal("0"),
        minimo_politica=Decimal("0"),
        tipo_movimento="",
        codigo_gv="",
        codigo_pgv="",
        pedido_linhas=0,
        pedido_produto_linhas=0,
        pedido_produto_duplicado=False,
        produto_encontrado_dprecos=True,
        preco_status="",
        ttc_min=None,
        ttc_max=None,
        caixa_min=None,
        caixa_max=None,
        problemas=(),
        planilha_atualizada_em="-",
        nome_produto_original=str(row.get("nome_produto_original") or "").strip(),
    )


def _annotate_duplicate_client_orders(
    records: list[CriticaRnRecord],
    *,
    context_records: list[CriticaRnRecord] | None = None,
) -> list[CriticaRnRecord]:
    grouped_orders: dict[tuple[str, str], dict[str, list[CriticaRnRecord]]] = {}
    comparison_records = context_records if context_records is not None else records
    for record in comparison_records:
        if not record.filial or not record.cod_pdv or not record.pedido or record.data_pedido is None:
            continue
        grouped_orders.setdefault((record.filial, record.cod_pdv), {}).setdefault(record.pedido, []).append(record)

    duplicate_orders: dict[tuple[str, str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for client_key, orders in grouped_orders.items():
        if len(orders) < 2:
            continue
        signatures: dict[tuple[tuple[str, str, str], ...], set[str]] = {}
        for order_number, order_items in orders.items():
            signature = _order_product_composition_signature(order_items)
            if signature:
                signatures.setdefault(signature, set()).add(order_number)
        for order_numbers in signatures.values():
            if len(order_numbers) < 2:
                continue
            sorted_order_numbers = tuple(sorted(order_numbers, key=_sort_key_numeric_text))
            sorted_order_refs = tuple(_duplicate_order_ref(order_number, orders[order_number]) for order_number in sorted_order_numbers)
            for order_number in sorted_order_numbers:
                duplicate_orders[(*client_key, order_number)] = (sorted_order_numbers, sorted_order_refs)

    if not duplicate_orders:
        return records

    annotated: list[CriticaRnRecord] = []
    for record in records:
        duplicate_payload = duplicate_orders.get((record.filial, record.cod_pdv, record.pedido))
        if not duplicate_payload:
            annotated.append(record)
            continue
        order_numbers, order_refs = duplicate_payload
        updated = replace(
            record,
            pedido_cliente_duplicado=True,
            duplicate_order_numbers=order_numbers,
            duplicate_order_refs=order_refs,
        )
        merged_labels = _dedupe_labels(list(record.problemas) + list(_build_problem_labels(updated)))
        annotated.append(replace(updated, problemas=merged_labels))
    return annotated


def _annotate_duplicate_products_by_price(records: list[CriticaRnRecord]) -> list[CriticaRnRecord]:
    if not records:
        return records

    grouped: dict[tuple[str, str, str, str], list[CriticaRnRecord]] = {}
    for record in records:
        if not record.filial or not record.pedido:
            continue
        product_key = normalize_stored_scope_value(record.produto_codigo) or _normalize_token(
            record.produto_descricao or record.nome_produto_original
        )
        if not product_key:
            continue
        grouped.setdefault((record.filial, record.pedido, product_key, _normalize_token(record.unid_venda)), []).append(record)

    duplicate_keys: set[tuple[str, str, str, str]] = set()
    for key, items in grouped.items():
        if len(items) < 2:
            continue
        prices = [item.preco_unitario for item in items if item.preco_unitario is not None]
        same_price = len(set(_decimal_signature(price) for price in prices)) < len(prices)
        extreme_delta = False
        positive_prices = [price for price in prices if price > 0]
        if len(positive_prices) >= 2:
            min_price = min(positive_prices)
            max_price = max(positive_prices)
            extreme_delta = min_price > 0 and ((max_price - min_price) / min_price) >= NON_SALE_PRICE_TOLERANCE
        if same_price or extreme_delta:
            duplicate_keys.add(key)

    if not duplicate_keys:
        return [replace(record, pedido_produto_duplicado=False) for record in records]

    annotated: list[CriticaRnRecord] = []
    for record in records:
        product_key = normalize_stored_scope_value(record.produto_codigo) or _normalize_token(
            record.produto_descricao or record.nome_produto_original
        )
        key = (record.filial, record.pedido, product_key, _normalize_token(record.unid_venda))
        is_duplicate = key in duplicate_keys
        updated = replace(record, pedido_produto_duplicado=is_duplicate)
        merged_labels = _dedupe_labels(list(updated.problemas) + list(_build_problem_labels(updated)))
        annotated.append(replace(updated, problemas=merged_labels))
    return annotated


def _annotate_client_total_above_average(records: list[CriticaRnRecord]) -> list[CriticaRnRecord]:
    if not records:
        return records

    order_totals_by_client: dict[tuple[str, str], dict[tuple[str, str], Decimal]] = {}
    for record in records:
        if not record.filial or not record.cod_pdv or not record.pedido:
            continue
        client_key = (record.filial, record.cod_pdv)
        pedido_key = (record.filial, record.pedido)
        order_totals_by_client.setdefault(client_key, {})[pedido_key] = record.total_pedido

    client_total_by_key = {
        client_key: sum(order_totals.values(), Decimal("0"))
        for client_key, order_totals in order_totals_by_client.items()
    }

    annotated: list[CriticaRnRecord] = []
    for record in records:
        client_key = (record.filial, record.cod_pdv)
        client_total = client_total_by_key.get(client_key, record.total_cliente)
        order_above_average = bool(
            record.avg_order_value_3m > 0 and client_total >= (record.avg_order_value_3m * ORDER_AVG_ALERT_RATIO)
        )
        updated = replace(record, total_cliente=client_total, order_above_average=order_above_average, problemas=())
        annotated.append(replace(updated, problemas=_build_problem_labels(updated)))
    return annotated


def _order_product_composition_signature(records: list[CriticaRnRecord]) -> tuple[tuple[str, str, str], ...]:
    totals: dict[tuple[str, str], Decimal] = {}
    for record in records:
        product_key = normalize_stored_scope_value(record.produto_codigo) or _normalize_token(
            record.produto_descricao or record.nome_produto_original
        )
        if not product_key:
            continue
        unit_key = _normalize_token(record.unid_venda)
        item_key = (product_key, unit_key)
        totals[item_key] = totals.get(item_key, Decimal("0")) + record.quantidade
    return tuple(
        (product_key, unit_key, _decimal_signature(quantity))
        for (product_key, unit_key), quantity in sorted(totals.items())
    )


def _decimal_signature(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f").rstrip("0").rstrip(".")


def _duplicate_order_ref(order_number: str, records: list[CriticaRnRecord]) -> str:
    order_dates = sorted({record.data_pedido for record in records if record.data_pedido})
    if not order_dates:
        return order_number
    return f"{order_number} em {_format_date(order_dates[0])}"


def _summarize_records(records: list[CriticaRnRecord]) -> CriticaRnSummary:
    if not records:
        return CriticaRnSummary(
            data_pedido=None,
            row_count=0,
            pedido_count=0,
            client_count=0,
            problem_row_count=0,
            problem_pedido_count=0,
            rows_with_critica=0,
            duplicated_row_count=0,
            price_alert_count=0,
            missing_price_count=0,
            total_pedido=Decimal("0"),
            planilha_atualizada_em="-",
        )
    pedido_totals: dict[tuple[str, str], Decimal] = {}
    problem_pedidos: set[tuple[str, str]] = set()
    client_keys = {(record.filial, record.cod_pdv) for record in records if record.filial and record.cod_pdv}
    operations = tuple(sorted({record.operation_name for record in records if record.operation_name}))
    duplicate_order_keys = {
        (record.filial, record.pedido)
        for record in records
        if record.pedido_cliente_duplicado and record.filial and record.pedido
    }
    occurrence_order_keys = _order_keys_with(
        records,
        lambda record: bool(record.critica_text or record.ocorrencia_1 or record.ocorrencia_2),
    )
    duplicated_product_order_keys = _order_keys_with(records, lambda record: record.pedido_produto_duplicado)
    price_alert_order_keys = _order_keys_with(records, _has_price_alert)
    missing_price_order_keys = _order_keys_with(
        records,
        lambda record: not record.produto_encontrado_dprecos and not _is_b2b_price_origin(record),
    )
    order_avg_alert_keys = _order_keys_with(records, lambda record: record.order_above_average)
    inadimplente_order_keys = _order_keys_with(records, _record_has_overdue_inad)
    map_buffer_order_keys = _order_keys_with(records, lambda record: record.map_status == "buffer")
    map_outside_order_keys = _order_keys_with(records, lambda record: record.map_status == "fora")
    cond_divergence_order_keys = _order_keys_with(records, lambda record: record.cond_divergente)
    limit_alert_order_keys = _order_keys_with(records, lambda record: record.limit_exceeded_amount > 0)
    for record in records:
        pedido_key = (record.filial, record.pedido)
        pedido_totals[pedido_key] = record.total_pedido
        if record.possui_problema:
            problem_pedidos.add(pedido_key)
    total_hectolitros = sum((record.hectolitros for record in records), Decimal("0"))
    return CriticaRnSummary(
        data_pedido=max((record.data_pedido for record in records if record.data_pedido), default=None),
        row_count=len(records),
        pedido_count=len(pedido_totals),
        client_count=len(client_keys),
        problem_row_count=sum(1 for record in records if record.possui_problema),
        problem_pedido_count=len(problem_pedidos),
        rows_with_critica=len(occurrence_order_keys),
        duplicated_row_count=len(duplicated_product_order_keys),
        duplicated_pedido_count=len(duplicate_order_keys),
        price_alert_count=len(price_alert_order_keys),
        missing_price_count=len(missing_price_order_keys),
        total_pedido=sum(pedido_totals.values(), Decimal("0")),
        planilha_atualizada_em=max(
            (record.planilha_atualizada_em for record in records if record.planilha_atualizada_em and record.planilha_atualizada_em != "-"),
            default="-",
        ),
        operations=operations,
        peso_total=sum((record.peso_item for record in records), Decimal("0")),
        total_hectolitros=total_hectolitros,
        nab_tt_hectolitros=sum((record.hectolitros for record in records if record.cesta_nab_tt), Decimal("0")),
        high_end_hectolitros=sum((record.hectolitros for record in records if record.cesta_high_end), Decimal("0")),
        cerveja_tt_hectolitros=sum((record.hectolitros for record in records if record.cesta_cerveja_tt), Decimal("0")),
        refri_zero_hectolitros=sum((record.hectolitros for record in records if record.cesta_refri_zero), Decimal("0")),
        cerveja_rgb_hectolitros=sum((record.hectolitros for record in records if record.cesta_cerveja_rgb), Decimal("0")),
        cerveja_ow_hectolitros=sum((record.hectolitros for record in records if record.cesta_cerveja_ow), Decimal("0")),
        marketplace_tt_faturamento=sum((_record_item_revenue(record) for record in records if record.cesta_marketplace_tt), Decimal("0")),
        order_avg_alert_count=len(order_avg_alert_keys),
        inadimplente_count=len(inadimplente_order_keys),
        multipack_violation_count=0,
        map_buffer_count=len(map_buffer_order_keys),
        map_outside_count=len(map_outside_order_keys),
        cond_divergence_count=len(cond_divergence_order_keys),
        limit_alert_count=len(limit_alert_order_keys),
    )


def _record_item_revenue(record: CriticaRnRecord) -> Decimal:
    return (record.quantidade or Decimal("0")) * (record.preco_unitario or Decimal("0"))


def _order_weight(records: list[CriticaRnRecord]) -> Decimal:
    return sum((record.peso_item for record in records), Decimal("0"))


def _order_client_pdf_lines(record: CriticaRnRecord, order_records: list[CriticaRnRecord]) -> list[str]:
    order_weight = _order_weight(order_records)
    return [
        _escape(_truncate(record.nome_pdv or "-", 28)),
        _nowrap_markup(f"Valor do Pedido(R$):{_format_money_raw(record.total_pedido)}"),
        _nowrap_markup(f"Peso do Pedido(Kg):{_format_decimal(order_weight)}"),
        _nowrap_markup(f"Cond.Pag.:{_truncate(record.cond_pag_pedido or '-', 28)}"),
    ]


def _order_client_pdf_markup(record: CriticaRnRecord, order_records: list[CriticaRnRecord]) -> str:
    return "<br/>".join(_order_client_pdf_lines(record, order_records))


def _order_keys_with(records: list[CriticaRnRecord], predicate: Any) -> set[tuple[str, str]]:
    return {
        (record.filial, record.pedido)
        for record in records
        if record.filial and record.pedido and predicate(record)
    }


def _build_problem_labels(record: CriticaRnRecord) -> tuple[str, ...]:
    labels: list[str] = []
    if record.ocorrencia_1:
        labels.append(f"Ocorrencia do relatorio: {record.ocorrencia_1}")
    if record.ocorrencia_2:
        labels.append(f"Ocorrencia complementar: {record.ocorrencia_2}")
    critica_text = _naturalize_critica_text(record.critica_text)
    if critica_text:
        if _is_price_related_text(critica_text):
            if _should_report_price_problem(record):
                labels.append(f"{_problem_product_label(record)}: {critica_text}")
        else:
            labels.append(critica_text)
    if record.pedido_produto_duplicado:
        labels.append("Produto repetido dentro do mesmo pedido")
    if record.pedido_cliente_duplicado:
        duplicate_refs = record.duplicate_order_refs or record.duplicate_order_numbers
        labels.append(
            "Possivel pedido duplicado: mesmo cliente com outro pedido usando os mesmos produtos e quantidades "
            f"({', '.join(duplicate_refs)})"
        )
    if _has_price_alert(record):
        labels.append(_price_alert_label(record))
    if not record.produto_encontrado_dprecos and record.produto_codigo and not _is_b2b_price_origin(record):
        labels.append("Produto sem referencia na DPrecos")
    if record.order_above_average:
        labels.append(
            f"Cliente acima da media de compra: total em pedidos {_format_money(record.total_cliente)}; media {_format_money(record.avg_order_value_3m)}"
        )
    if _record_has_overdue_inad(record):
        labels.append(f"Cliente com {_format_money(record.inad_total_vencido)} vencido em aberto")
    if record.map_status == "buffer":
        labels.append("Pedido em buffer (mapa 1)")
    elif record.map_status == "fora":
        labels.append(
            f"Pedido digitado fora do mapa do vendedor: mapa {record.mapa_codigo or '-'}; vendedor {record.vendedor_codigo or record.setor or '-'}"
        )
    if record.limit_exceeded_amount > 0:
        labels.append(
            f"Com este pedido, o cliente ultrapassa o limite em {_format_money(record.limit_exceeded_amount)}; aberto {_format_money(record.client_limite_usado or record.inad_total_aberto)}"
        )
    if record.cond_divergente:
        labels.append(
            f"Condicao de pagamento diferente do cadastro: pedido {record.cond_pag_pedido or '-'}; cadastro {record.client_cond_pag_atual or '-'}"
        )
    return _dedupe_labels(labels)


def _record_has_overdue_inad(record: CriticaRnRecord) -> bool:
    return record.inad_total_vencido > 0 and int(record.inad_titulos_vencidos or 0) > 0


def _has_price_alert(record: CriticaRnRecord) -> bool:
    if record.price_reference is None or record.price_reference <= 0:
        return False
    if record.price_delta_pct is None:
        return False
    return _should_report_price_problem(record)


def _should_report_price_problem(record: CriticaRnRecord) -> bool:
    if record.price_delta_pct is None:
        return True
    if not _is_sale_order(record):
        return abs(record.price_delta_pct) >= NON_SALE_PRICE_TOLERANCE
    if _is_b2b_price_origin(record):
        return abs(record.price_delta_pct) >= B2B_PRICE_TOLERANCE
    tolerance = PRICE_TOLERANCE_OP1 if record.filial == "1" else PRICE_TOLERANCE_DEFAULT
    return abs(record.price_delta_pct) >= tolerance


def _is_b2b_price_origin(record: CriticaRnRecord) -> bool:
    return str(record.origem_pedido or "").strip().upper() in B2B_PRICE_ORIGINS


def _movement_search_text(record: CriticaRnRecord) -> str:
    return _normalize_token(
        " ".join(
            [
                str(record.tipo_movimento or ""),
                str(record.operation_name or ""),
                str(record.movement_operation_name or ""),
                str(record.status_pedido or ""),
            ]
        )
    )


def _is_bonus_order(record: CriticaRnRecord) -> bool:
    return "bonif" in _movement_search_text(record)


def _is_sale_order(record: CriticaRnRecord) -> bool:
    tipo_movimento = normalize_stored_scope_value(str(record.tipo_movimento or ""))
    if tipo_movimento == "51":
        return True
    movement_text = _movement_search_text(record)
    return "venda" in movement_text and not _is_bonus_order(record)


def _order_movement_group_sort_key(record: CriticaRnRecord) -> int:
    if _is_bonus_order(record):
        return 2
    if _is_sale_order(record):
        return 0
    return 1


def _price_alert_label(record: CriticaRnRecord) -> str:
    if record.price_reference is None:
        return "Preco sem referencia"
    if record.price_reference_label == "ttc":
        source = "TTC"
    elif record.price_reference_label == "caixa_600_dz":
        source = "referencia da caixa de 600ml"
    else:
        source = "DPrecos"
    if record.price_delta_pct is None:
        return f"Preco fora da referencia ({source})"
    pct = abs(record.price_delta_pct * Decimal("100")).quantize(Decimal("0.1"))
    direction = "abaixo" if record.price_delta_pct < 0 else "acima"
    pct_text = f"{pct:.1f}".replace(".", ",")
    return (
        f"{_problem_product_label(record)} com preco {pct_text}% {direction} da referencia ({source}): "
        f"cobrado {_format_money(record.preco_unitario)}; referencia {_format_money(record.price_reference)}"
    )


def _naturalize_critica_text(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    text = re.sub(r"^\s*TE\s*0*\d+\s*(?:[|:-]\s*)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:^|\s*[|;]\s*)TE\s*:?\s*0*\d+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"Preco abaixo do minimo informado \(([^)]+)\)",
        lambda match: f"Preco abaixo do minimo permitido. Minimo informado: {_format_embedded_money(match.group(1))}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"Preco acima do maximo informado \(([^)]+)\)",
        lambda match: f"Preco acima do maximo permitido. Maximo informado: {_format_embedded_money(match.group(1))}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*[|;]\s*", "; ", text)
    return text.strip(" ;")


def _is_price_related_text(value: str) -> bool:
    return "preco" in _normalize_token(value)


def _problem_product_label(record: CriticaRnRecord) -> str:
    code = str(record.produto_codigo or "").strip()
    description = str(record.produto_descricao or record.nome_produto_original or "").strip()
    if code and description:
        return f"Produto {code} - {_truncate(description, 48)}"
    if description:
        return f"Produto {_truncate(description, 56)}"
    if code:
        return f"Produto {code}"
    return "Produto"


def _format_embedded_money(value: str) -> str:
    parsed = _nullable_decimal(value)
    if parsed is None:
        cleaned = str(value or "").strip()
        return cleaned or "-"
    return _format_money(parsed)


def _map_status(*, mapa_codigo: str, vendedor_codigo: str) -> str:
    if mapa_codigo == "1":
        return "buffer"
    if mapa_codigo and vendedor_codigo and mapa_codigo != vendedor_codigo:
        return "fora"
    return ""


def _supports_credit_and_condition_checks(tipo_movimento: str) -> bool:
    return normalize_stored_scope_value(str(tipo_movimento or "")) == "51"


def _is_cash_payment_condition(code: str, label: str) -> bool:
    normalized_code = normalize_stored_scope_value(str(code or ""))
    if normalized_code == "2":
        return True
    return "dinheiro" in _normalize_token(label)


def _resolve_price_reference(
    *,
    filial: str,
    unit_label: str,
    product_name: str,
    client_segment: str,
    ttc_ref: Decimal | None,
    caixa_asr: Decimal | None,
    caixa_sub: Decimal | None,
    caixa_frio: Decimal | None,
) -> tuple[Decimal | None, str]:
    normalized_unit = _normalize_token(unit_label)
    selected_caixa = _selected_box_reference(client_segment=client_segment, caixa_asr=caixa_asr, caixa_sub=caixa_sub, caixa_frio=caixa_frio)
    if normalized_unit in {"un", "und", "unid", "unidade"} and ttc_ref is not None and ttc_ref > 0:
        return ttc_ref, "ttc"
    if normalized_unit.startswith("dz") and _is_600ml_product(product_name) and selected_caixa is not None and selected_caixa > 0:
        return (selected_caixa / Decimal("2")).quantize(Decimal("0.0001")), "caixa_600_dz"
    if selected_caixa is not None and selected_caixa > 0:
        return selected_caixa, "caixa"
    return None, ""


def _selected_box_reference(
    *,
    client_segment: str,
    caixa_asr: Decimal | None,
    caixa_sub: Decimal | None,
    caixa_frio: Decimal | None,
) -> Decimal | None:
    normalized_segment = _normalize_token(client_segment)
    if normalized_segment.startswith("as"):
        return _coalesce_first_decimal(caixa_asr, caixa_sub, caixa_frio)
    if normalized_segment == "sub":
        return _coalesce_first_decimal(caixa_sub, caixa_asr, caixa_frio)
    return _coalesce_first_decimal(caixa_frio, caixa_asr, caixa_sub)


def _calculate_price_delta_pct(
    *,
    filial: str,
    unit_label: str,
    product_name: str,
    actual_price: Decimal,
    reference_price: Decimal | None,
) -> Decimal | None:
    if reference_price is None or reference_price <= 0:
        return None
    comparable_price = actual_price
    if _normalize_token(unit_label).startswith("dz") and _is_600ml_product(product_name):
        comparable_price = comparable_price
    return (comparable_price - reference_price) / reference_price


def _is_600ml_product(value: str) -> bool:
    normalized = _normalize_token(value)
    return "600" in normalized


def _is_multipack_item(value: str) -> bool:
    normalized = _normalize_token(value)
    return "mpa" in normalized or "multipack" in normalized or "multi pack" in normalized


def _segment_allows_multipack(value: str) -> bool:
    normalized = _normalize_token(value)
    return normalized.startswith("as") or normalized == "sub"


def _dedupe_labels(labels: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for label in labels:
        normalized = " ".join(str(label or "").split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _coalesce_first_decimal(*values: Decimal | None) -> Decimal | None:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_only).strip()


def _operation_display_name(operation_name: str, movement_operation_name: str = "") -> str:
    branch_name = str(operation_name or "").strip()
    movement_name = str(movement_operation_name or "").strip()
    if branch_name and movement_name:
        return f"{branch_name} | {movement_name}"
    return branch_name or movement_name


def _build_order_records(records: list[CriticaRnRecord]) -> list[CriticaRnOrderRecord]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (record.filial, record.pedido)
        entry = grouped.setdefault(
            key,
            {
                "filial": record.filial,
                "pedido": record.pedido,
                "data_pedido": record.data_pedido,
                "operation_name": record.operation_name,
                "movement_operation_name": record.movement_operation_name,
                "setor": record.setor,
                "cod_pdv": record.cod_pdv,
                "nome_pdv": record.nome_pdv,
                "status_pedido": record.status_pedido,
                "total_pedido": record.total_pedido,
                "peso_pedido": Decimal("0"),
                "cond_pagamentos": [],
                "problem_labels": [],
                "problem_item_count": 0,
                "item_count": 0,
            },
        )
        entry["peso_pedido"] += record.peso_item
        cond_pag_pedido = str(record.cond_pag_pedido or "").strip()
        if cond_pag_pedido and cond_pag_pedido not in entry["cond_pagamentos"]:
            entry["cond_pagamentos"].append(cond_pag_pedido)
        entry["item_count"] += 1
        if record.possui_problema:
            entry["problem_item_count"] += 1
        entry["problem_labels"].extend(record.problemas)
    result: list[CriticaRnOrderRecord] = []
    for entry in grouped.values():
        result.append(
            CriticaRnOrderRecord(
                filial=entry["filial"],
                pedido=entry["pedido"],
                data_pedido=entry["data_pedido"],
                operation_name=entry["operation_name"],
                movement_operation_name=entry["movement_operation_name"],
                setor=entry["setor"],
                cod_pdv=entry["cod_pdv"],
                nome_pdv=entry["nome_pdv"],
                status_pedido=entry["status_pedido"],
                total_pedido=entry["total_pedido"],
                peso_pedido=entry["peso_pedido"],
                cond_pag_pedido=" | ".join(entry["cond_pagamentos"]),
                problem_labels=_dedupe_labels(entry["problem_labels"]),
                problem_item_count=int(entry["problem_item_count"]),
                item_count=int(entry["item_count"]),
            )
        )
    result.sort(
        key=lambda item: (
            0 if item.problem_labels else 1,
            _order_record_movement_group_sort_key(item),
            int(item.filial or "0") if str(item.filial or "").isdigit() else 999,
            item.operation_name,
            item.cod_pdv,
            item.pedido,
        )
    )
    return result


def _order_record_movement_group_sort_key(order: CriticaRnOrderRecord) -> int:
    search_text = _normalize_token(
        " ".join(
            [
                str(order.operation_name or ""),
                str(order.movement_operation_name or ""),
                str(order.status_pedido or ""),
            ]
        )
    )
    if "bonif" in search_text:
        return 2
    if "venda" in search_text:
        return 0
    return 1


def _where_clause(filters: list[sql.Composed]) -> sql.Composed:
    if not filters:
        return sql.SQL("")
    return sql.SQL("WHERE ") + sql.SQL(" AND ").join(filters)


def _dprecos_reference_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "dprecos_latest"):
        return sql.SQL(
            """
            dprecos_ref AS (
                SELECT
                    NULL::text AS codigo,
                    NULL::text AS produto_dprecos,
                    NULL::numeric AS asr_preco,
                    NULL::numeric AS sub_preco,
                    NULL::numeric AS frio_preco,
                    NULL::numeric AS ttc_preco
                WHERE FALSE
            )
            """
        )
    return sql.SQL(
        """
        dprecos_ref AS (
            SELECT
                codigo,
                MIN(produto) AS produto_dprecos,
                MIN(NULLIF(asr, 0)) AS asr_preco,
                MIN(NULLIF(sub, 0)) AS sub_preco,
                MIN(NULLIF(frio, 0)) AS frio_preco,
                MIN(NULLIF(ttc, 0)) AS ttc_preco
            FROM {}.dprecos_latest
            GROUP BY codigo
        )
        """
    ).format(sql.Identifier(schema))


def _dprodutos_reference_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "dprodutos_latest"):
        return sql.SQL(
            """
            dprodutos_ref AS (
                SELECT
                    NULL::text AS codigo,
                    NULL::numeric AS fator_hecto,
                    NULL::numeric AS peso_bruto
                WHERE FALSE
            )
            """
    )
    has_fator_hecto_column = _relation_column_exists(conn, schema, "dprodutos_latest", "fator_hecto")
    has_peso_bruto_column = _relation_column_exists(conn, schema, "dprodutos_latest", "peso_bruto")
    has_payload_column = _relation_column_exists(conn, schema, "dprodutos_latest", "payload")
    if has_payload_column:
        payload_fator_sql = _localized_numeric_sql(
            sql.SQL(
                """
                COALESCE(
                    payload ->> 'Fator Hecto',
                    payload ->> 'Fator Hecto Comercial',
                    payload ->> 'FatorHecto',
                    payload ->> 'Fator_Hecto',
                    ''
                )
                """
            )
        )
        payload_peso_sql = _localized_numeric_sql(
            sql.SQL(
                """
                COALESCE(
                    payload ->> 'Peso Bruto',
                    payload ->> 'Peso bruto',
                    payload ->> 'Peso Bruto KG',
                    payload ->> 'Peso Bruto Kg',
                    payload ->> 'Peso KG',
                    payload ->> 'Peso',
                    ''
                )
                """
            )
        )
    else:
        payload_fator_sql = sql.SQL("0::numeric")
        payload_peso_sql = sql.SQL("0::numeric")
    if has_fator_hecto_column:
        fator_sql = sql.SQL("COALESCE(NULLIF(COALESCE(fator_hecto, 0), 0), {payload_fator}, 0)").format(
            payload_fator=payload_fator_sql
        )
    else:
        fator_sql = payload_fator_sql
    if has_peso_bruto_column:
        peso_sql = sql.SQL("COALESCE(NULLIF(COALESCE(peso_bruto, 0), 0), {payload_peso}, 0)").format(
            payload_peso=payload_peso_sql
        )
    else:
        peso_sql = payload_peso_sql
    return sql.SQL(
        """
        dprodutos_ref AS (
            SELECT
                codigo,
                MAX({fator_sql}) AS fator_hecto,
                MAX({peso_sql}) AS peso_bruto
            FROM {}.dprodutos_latest
            GROUP BY codigo
        )
        """
    ).format(
        sql.Identifier(schema),
        fator_sql=fator_sql,
        peso_sql=peso_sql,
    )


def _produto_cesta_metrics_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "produto_cestas_latest"):
        return sql.SQL(
            """
            produto_cesta_metrics_ref AS (
                SELECT
                    NULL::text AS codigo,
                    FALSE AS cesta_nab_tt,
                    FALSE AS cesta_high_end,
                    FALSE AS cesta_cerveja_tt,
                    FALSE AS cesta_refri_zero,
                    FALSE AS cesta_cerveja_rgb,
                    FALSE AS cesta_cerveja_ow,
                    FALSE AS cesta_marketplace_tt
                WHERE FALSE
            )
            """
        )
    return sql.SQL(
        """
        produto_cesta_metrics_ref AS (
            SELECT
                codigo,
                BOOL_OR(nome_cesta = 'NAB TT') AS cesta_nab_tt,
                BOOL_OR(nome_cesta = 'High End') AS cesta_high_end,
                BOOL_OR(nome_cesta = 'Cerveja TT') AS cesta_cerveja_tt,
                BOOL_OR(nome_cesta = 'Refri Zero') AS cesta_refri_zero,
                BOOL_OR(nome_cesta = 'Cerveja RGB') AS cesta_cerveja_rgb,
                BOOL_OR(nome_cesta = 'Cerveja OW') AS cesta_cerveja_ow,
                BOOL_OR(nome_cesta = 'Marketplace TT') AS cesta_marketplace_tt
            FROM {}.produto_cestas_latest
            GROUP BY codigo
        )
        """
    ).format(sql.Identifier(schema))


def _doperacoes_reference_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "doperacoes_latest"):
        return sql.SQL(
            """
            doperacoes_ref AS (
                SELECT
                    NULL::text AS tipo_movimento,
                    NULL::text AS nome_operacao
                WHERE FALSE
            )
            """
        )
    return sql.SQL(
        """
        doperacoes_ref AS (
            SELECT DISTINCT ON (normalized_tipo_movimento)
                normalized_tipo_movimento AS tipo_movimento,
                nome_operacao
            FROM (
                SELECT
                    COALESCE(NULLIF(LTRIM(COALESCE(tipo_movimento, ''), '0'), ''), '0') AS normalized_tipo_movimento,
                    COALESCE(NULLIF(BTRIM(nome_operacao), ''), '') AS nome_operacao
                FROM {}.doperacoes_latest
            ) src
            WHERE nome_operacao <> ''
            ORDER BY normalized_tipo_movimento, LENGTH(nome_operacao), nome_operacao
        )
        """
    ).format(sql.Identifier(schema))


def _dcondicoes_reference_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "dcondicoes_latest"):
        return sql.SQL(
            """
            dcondicoes_ref AS (
                SELECT
                    NULL::text AS filial_condicao_key,
                    NULL::text AS descricao
                WHERE FALSE
            )
            """
        )
    return sql.SQL(
        """
        dcondicoes_ref AS (
            SELECT DISTINCT ON (filial_condicao_key)
                filial_condicao_key,
                descricao
            FROM {}.dcondicoes_latest
            WHERE COALESCE(filial_condicao_key, '') <> ''
            ORDER BY filial_condicao_key, LENGTH(COALESCE(descricao, '')), descricao
        )
        """
    ).format(sql.Identifier(schema))


def _dclientes_reference_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "dclientes_latest"):
        return sql.SQL(
            """
            dclientes_ref AS (
                SELECT
                    NULL::text AS filial,
                    NULL::text AS cod_pdv,
                    NULL::text AS status_pdv,
                    NULL::text AS segmento_nge,
                    NULL::text AS cond_pag_atual,
                    NULL::text AS media_faturamento_3m,
                    NULL::text AS limite_credito,
                    NULL::text AS limite_usado,
                    NULL::text AS saldo_aberto,
                    NULL::text AS cidade,
                    NULL::text AS bairro
                WHERE FALSE
            )
            """
        )
    return sql.SQL(
        """
        dclientes_ref AS (
            SELECT
                filial,
                cod_pdv,
                COALESCE(status_pdv, '') AS status_pdv,
                COALESCE(payload ->> 'Segmento NGE', '') AS segmento_nge,
                COALESCE(payload ->> 'Cond Pag Atual', '') AS cond_pag_atual,
                COALESCE(payload ->> 'Média Faturamento(3 meses)', '') AS media_faturamento_3m,
                COALESCE(payload ->> 'Limite de Crédito', '') AS limite_credito,
                COALESCE(payload ->> 'Limite Total Usado (Títulos Abertos + Títulos Abertos FIDC)', '') AS limite_usado,
                COALESCE(payload ->> 'Saldo em Aberto', '') AS saldo_aberto,
                COALESCE(payload ->> 'Cidade', '') AS cidade,
                COALESCE(payload ->> 'Bairro', '') AS bairro
            FROM {}.dclientes_latest
        )
        """
    ).format(sql.Identifier(schema))


def _prazo_media_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "prazo_limite_latest"):
        return sql.SQL(
            """
            prazo_media_ref AS (
                SELECT
                    NULL::text AS filial,
                    NULL::text AS cod_pdv,
                    NULL::numeric AS total_faturamento_3m,
                    NULL::numeric AS total_pedidos_3m,
                    NULL::numeric AS avg_order_value_3m
                WHERE FALSE
            )
            """
        )
    return sql.SQL(
        """
        prazo_media_ref AS (
            SELECT
                filial,
                cod_pdv,
                SUM(COALESCE(faturamento_com_pdv, 0)) AS total_faturamento_3m,
                SUM(COALESCE(pedidos, 0)) AS total_pedidos_3m,
                CASE
                    WHEN SUM(COALESCE(pedidos, 0)) > 0
                        THEN SUM(COALESCE(faturamento_com_pdv, 0)) / SUM(COALESCE(pedidos, 0))
                    ELSE NULL::numeric
                END AS avg_order_value_3m
            FROM {}.prazo_limite_latest
            GROUP BY filial, cod_pdv
        )
        """
    ).format(sql.Identifier(schema))


def _inad_stats_cte(schema: str, conn: Any) -> sql.Composed:
    if not _relation_exists(conn, schema, "inadimplencia_latest"):
        return sql.SQL(
            """
            inad_stats_ref AS (
                SELECT
                    NULL::text AS filial,
                    NULL::text AS cod_pdv,
                    NULL::numeric AS inad_total_aberto,
                    NULL::numeric AS inad_total_vencido,
                    NULL::int AS inad_titulos_abertos,
                    NULL::int AS inad_titulos_vencidos
                WHERE FALSE
            )
            """
        )
    valor_sql = _localized_numeric_sql(sql.SQL("valor_pendente"))
    days_to_due_sql = _inad_days_to_due_sql(sql.SQL("i.dias"), sql.SQL("i.data_vencimento"))
    return sql.SQL(
        """
        inad_stats_ref AS (
            SELECT
                i.unb AS filial,
                i.cliente AS cod_pdv,
                COALESCE(SUM({valor_sql}), 0) AS inad_total_aberto,
                COALESCE(SUM(CASE WHEN {days_to_due_sql} < 0 THEN {valor_sql} ELSE 0 END), 0) AS inad_total_vencido,
                COUNT(*)::int AS inad_titulos_abertos,
                COUNT(*) FILTER (WHERE {days_to_due_sql} < 0)::int AS inad_titulos_vencidos
            FROM {}.inadimplencia_latest i
            GROUP BY i.unb, i.cliente
        )
        """
    ).format(sql.Identifier(schema), valor_sql=valor_sql, days_to_due_sql=days_to_due_sql)


def _localized_numeric_sql(expression: sql.Composed) -> sql.Composed:
    return sql.SQL(
        "COALESCE(NULLIF(REPLACE(REPLACE(REPLACE(BTRIM(COALESCE({expr}::text, '')), 'R$', ''), '.', ''), ',', '.'), ''), '0')::numeric"
    ).format(expr=expression)


def _normalized_code_sql(expression: sql.Composed) -> sql.Composed:
    return sql.SQL(
        "COALESCE(NULLIF(LTRIM(REGEXP_REPLACE(BTRIM(COALESCE({expr}::text, '')), '[^0-9]', '', 'g'), '0'), ''), '0')"
    ).format(expr=expression)


def _localized_integer_sql(expression: sql.Composed) -> sql.Composed:
    return sql.SQL(
        "COALESCE(NULLIF(REGEXP_REPLACE(BTRIM(COALESCE({expr}::text, '')), '[^0-9-]', '', 'g'), ''), '0')::int"
    ).format(expr=expression)


def _inad_days_to_due_sql(days_expression: sql.Composed, due_date_expression: sql.Composed) -> sql.Composed:
    imported_days_sql = sql.SQL(
        "CASE "
        "WHEN REGEXP_REPLACE(BTRIM(COALESCE({days_expr}::text, '')), '[^0-9-]', '', 'g') = '' THEN NULL "
        "ELSE REGEXP_REPLACE(BTRIM(COALESCE({days_expr}::text, '')), '[^0-9-]', '', 'g')::int "
        "END"
    ).format(days_expr=days_expression)
    return sql.SQL(
        "CASE "
        "WHEN BTRIM(COALESCE({due_expr}::text, '')) ~ '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}$' "
        "THEN (TO_DATE(BTRIM({due_expr}::text), 'DD/MM/YYYY') - CURRENT_DATE)::int "
        "WHEN BTRIM(COALESCE({due_expr}::text, '')) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$' "
        "THEN (TO_DATE(BTRIM({due_expr}::text), 'YYYY-MM-DD') - CURRENT_DATE)::int "
        "ELSE {imported_days_sql} "
        "END"
    ).format(due_expr=due_date_expression, imported_days_sql=imported_days_sql)


def _relation_exists(conn: Any, schema: str, relation: str) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT to_regclass(%s) AS relation_name", (f"{schema}.{relation}",))
        row = cur.fetchone() or {}
    return bool(row.get("relation_name"))


def _relation_column_exists(conn: Any, schema: str, relation: str, column: str) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = %s
            ) AS has_column
            """,
            (schema, relation, column),
        )
        row = cur.fetchone() or {}
    return bool(row.get("has_column"))


def _decimal(value: Any) -> Decimal:
    parsed = _nullable_decimal(value)
    return parsed if parsed is not None else Decimal("0")


def _nullable_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("R$", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def _format_updated_at(reference_date: Any, batch_imported_at: Any) -> str:
    try:
        if batch_imported_at is not None:
            return batch_imported_at.astimezone(CRITICA_IMPORT_LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M")
    except Exception:
        imported_text = str(batch_imported_at or "").strip()
        if imported_text:
            return imported_text
    reference_text = str(reference_date or "").strip()
    if reference_text:
        return reference_text
    return "-"


def _format_date(value: date | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%d/%m/%Y")


def _format_money(value: Decimal | str | int | float | None) -> str:
    amount = _nullable_decimal(value)
    if amount is None:
        return "R$ 0,00"
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    formatted = f"{quantized:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _format_money_raw(value: Decimal | str | int | float | None) -> str:
    amount = _nullable_decimal(value)
    if amount is None:
        return "0,00"
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    formatted = f"{quantized:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_decimal(value: Decimal | str | int | float | None) -> str:
    amount = _nullable_decimal(value)
    if amount is None:
        return "0"
    if amount == amount.to_integral_value():
        return str(int(amount))
    text = format(amount.normalize(), "f").rstrip("0").rstrip(".") or "0"
    return text.replace(".", ",")


def _truncate(value: str, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _truncate_mono(value: str, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_length:
        return text
    return text[:max(0, max_length)]


def _escape(value: str) -> str:
    return escape(str(value or ""))


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _has_scope_values(values: list[str] | None) -> bool:
    return any(str(value or "").strip() for value in values or [])
