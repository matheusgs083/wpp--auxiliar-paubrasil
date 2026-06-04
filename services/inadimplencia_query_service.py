from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import re
from time import monotonic
from typing import Any
import unicodedata

import psycopg
from psycopg import sql
from psycopg.rows import dict_row, tuple_row

from bot_api.commercial_scope import (
    normalize_stored_scope_value,
    partition_filial_scopes,
    partition_gv_scopes,
    partition_sector_scopes,
    split_scope_pair,
)
from bot_api.db import get_connection_pool

_ACCENTED_SQL_SOURCE = (
    "\u00e1\u00e0\u00e3\u00e2\u00e4"
    "\u00e9\u00e8\u00ea\u00eb"
    "\u00ed\u00ec\u00ee\u00ef"
    "\u00f3\u00f2\u00f5\u00f4\u00f6"
    "\u00fa\u00f9\u00fb\u00fc"
    "\u00e7\u00f1"
)
_ACCENTED_SQL_TARGET = "aaaaaeeeeiiiiooooouuuucn"


@dataclass(frozen=True)
class InadimplenciaRecord:
    filial: str
    cod_pdv: str
    nome: str
    data_emissao: str
    data_vencimento: str
    valor_original: str
    valor_pendente: str
    valor_corrigido: str
    dias: str
    planilha_atualizada_em: str
    nota_fiscal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InadimplenciaClientSummary:
    filial: str
    cod_pdv: str
    nome: str
    title_count: int
    total_pendente: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InadimplenciaVisitAlert:
    filial: str
    cod_pdv: str
    nome: str
    seller_code: str
    manager_code: str
    title_count: int
    total_pendente: str
    nearest_days_to_due: int
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InadimplenciaVisitRiskSummary:
    seller_code: str
    manager_code: str
    client_count: int
    overdue_count: int
    due_today_count: int
    total_pendente: str
    visit_day_token: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InadimplenciaFinanceSummary:
    client_count: int
    total_pendente: str
    due_in_two_days_count: int
    due_in_two_days_total: str
    due_tomorrow_count: int
    due_tomorrow_total: str
    due_today_count: int
    due_today_total: str
    overdue_count: int
    overdue_total: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InadimplenciaFinanceFilialSummary:
    filial: str
    client_count: int
    total_pendente: str
    due_in_two_days_count: int
    due_in_two_days_total: str
    due_tomorrow_count: int
    due_tomorrow_total: str
    due_today_count: int
    due_today_total: str
    overdue_count: int
    overdue_total: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InadimplenciaFinanceManagementSummary:
    manager_code: str
    client_count: int
    total_pendente: str
    due_in_two_days_count: int
    due_in_two_days_total: str
    due_tomorrow_count: int
    due_tomorrow_total: str
    due_today_count: int
    due_today_total: str
    overdue_count: int
    overdue_total: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InadimplenciaFinanceSellerSummary:
    seller_code: str
    manager_code: str
    client_count: int
    total_pendente: str
    due_in_two_days_count: int
    due_in_two_days_total: str
    due_tomorrow_count: int
    due_tomorrow_total: str
    due_today_count: int
    due_today_total: str
    overdue_count: int
    overdue_total: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InadimplenciaQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None
        self._last_error = ""
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_expires_at = 0.0
        self._client_count_cache: dict[tuple[tuple[str, ...], tuple[str, ...], str], tuple[float, int]] = {}
        self._finance_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, InadimplenciaFinanceSummary],
        ] = {}
        self._finance_filial_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[InadimplenciaFinanceFilialSummary]],
        ] = {}
        self._finance_management_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[InadimplenciaFinanceManagementSummary]],
        ] = {}
        self._finance_seller_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[InadimplenciaFinanceSellerSummary]],
        ] = {}
        self._latest_batch_id_cache: dict[str, tuple[float, int | None]] = {}
        self._visit_risk_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int],
            tuple[float, list[InadimplenciaVisitRiskSummary]],
        ] = {}
        self._visit_risk_alert_cache: dict[
            tuple[tuple[str, ...], str, str, tuple[str, ...], tuple[str, ...], int],
            tuple[float, list[InadimplenciaVisitAlert]],
        ] = {}

    def status(self) -> dict[str, Any]:
        now = monotonic()
        if self._status_cache is not None and now < self._status_cache_expires_at:
            return dict(self._status_cache)

        if not self.database_url:
            self._last_error = "REPORTS_DATABASE_URL nao configurada."
            payload = {
                "database_configured": False,
                "ready": False,
                "schema": self.schema,
                "latest_view_exists": False,
                "dclientes_view_exists": False,
                "last_error": self._last_error,
            }
            self._cache_status(payload)
            return payload

        try:
            with self._connect(row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            EXISTS (
                                SELECT 1
                                FROM information_schema.views
                                WHERE table_schema = %s
                                  AND table_name = 'inadimplencia_latest'
                            ) AS has_inadimplencia,
                            EXISTS (
                                SELECT 1
                                FROM information_schema.views
                                WHERE table_schema = %s
                                  AND table_name = 'dclientes_latest'
                            ) AS has_dclientes
                        """,
                        (self.schema, self.schema),
                    )
                    row = cur.fetchone()
            inad_ready = bool(row and row["has_inadimplencia"])
            dclientes_ready = bool(row and row["has_dclientes"])
            ready = inad_ready and dclientes_ready
            self._last_error = ""
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": inad_ready,
                "dclientes_view_exists": dclientes_ready,
                "last_error": "" if ready else "Views reports.inadimplencia_latest e/ou reports.dclientes_latest nao encontradas.",
            }
            self._cache_status(payload)
            return payload
        except Exception as exc:
            self._last_error = str(exc)
            payload = {
                "database_configured": True,
                "ready": False,
                "schema": self.schema,
                "latest_view_exists": False,
                "dclientes_view_exists": False,
                "last_error": self._last_error,
            }
            self._cache_status(payload)
            return payload

    def count_clients_in_scope(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        due_bucket: str | None = None,
    ) -> int:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        normalized_due_bucket = _normalize_due_bucket(due_bucket)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes), normalized_due_bucket)
        now = monotonic()
        cached_entry = self._client_count_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return cached_entry[1]

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        due_bucket_filter = _due_bucket_filter_sql(normalized_due_bucket, _days_to_due_sql("i.dias"))
        if due_bucket_filter is not None:
            filters.append(due_bucket_filter)

        query = sql.SQL(
            """
            SELECT COUNT(DISTINCT (i.unb, i.cliente))::int AS client_count
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            WHERE {where}
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()

        client_count = int(row["client_count"] or 0) if row else 0
        self._client_count_cache[cache_key] = (now + 60.0, client_count)
        return client_count

    def get_finance_summary(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> InadimplenciaFinanceSummary:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._finance_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return cached_entry[1]

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        days_sql = _days_to_due_sql("i.dias")
        valor_pendente_sql = _money_to_numeric_sql("i.valor_pendente")
        query = sql.SQL(
            """
            SELECT
                COUNT(DISTINCT (i.unb, i.cliente))::int AS client_count,
                COALESCE(SUM({valor_pendente_sql}), 0) AS total_pendente,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 2)::int AS due_in_two_days_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 2), 0) AS due_in_two_days_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 1)::int AS due_tomorrow_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 1), 0) AS due_tomorrow_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 0)::int AS due_today_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 0), 0) AS due_today_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} < 0)::int AS overdue_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} < 0), 0) AS overdue_total,
                COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                MAX(i.batch_imported_at) AS batch_imported_at
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
            WHERE {where}
            """
        ).format(
            schema=sql.Identifier(self.schema),
            valor_pendente_sql=valor_pendente_sql,
            days_sql=days_sql,
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()

        summary = InadimplenciaFinanceSummary(
            client_count=int(row["client_count"] or 0) if row else 0,
            total_pendente=_format_money(row["total_pendente"] if row else None),
            due_in_two_days_count=int(row["due_in_two_days_count"] or 0) if row else 0,
            due_in_two_days_total=_format_money(row["due_in_two_days_total"] if row else None),
            due_tomorrow_count=int(row["due_tomorrow_count"] or 0) if row else 0,
            due_tomorrow_total=_format_money(row["due_tomorrow_total"] if row else None),
            due_today_count=int(row["due_today_count"] or 0) if row else 0,
            due_today_total=_format_money(row["due_today_total"] if row else None),
            overdue_count=int(row["overdue_count"] or 0) if row else 0,
            overdue_total=_format_money(row["overdue_total"] if row else None),
            planilha_atualizada_em=_format_reference_date(
                row.get("reference_date") if row else None,
                row.get("batch_imported_at") if row else None,
            ),
        )
        self._finance_summary_cache[cache_key] = (now + 60.0, summary)
        return summary

    def get_finance_summary_for_seller(
        self,
        seller_code: str,
        manager_code: str = "",
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> InadimplenciaFinanceSummary:
        normalized_seller_code = normalize_stored_scope_value(seller_code)
        normalized_manager_code = normalize_stored_scope_value(manager_code)
        if not normalized_seller_code:
            raise ValueError("Setor do vendedor obrigatorio.")

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        _append_scope_value_filter(
            filters=filters,
            params=params,
            value=normalized_seller_code,
            key_field="d.filial_setor_key",
        )
        if normalized_manager_code:
            _append_scope_value_filter(
                filters=filters,
                params=params,
                value=normalized_manager_code,
                key_field="d.filial_gv_key",
            )
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        days_sql = _days_to_due_sql("i.dias")
        valor_pendente_sql = _money_to_numeric_sql("i.valor_pendente")
        query = sql.SQL(
            """
            SELECT
                COUNT(DISTINCT (i.unb, i.cliente))::int AS client_count,
                COALESCE(SUM({valor_pendente_sql}), 0) AS total_pendente,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 2)::int AS due_in_two_days_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 2), 0) AS due_in_two_days_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 1)::int AS due_tomorrow_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 1), 0) AS due_tomorrow_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 0)::int AS due_today_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 0), 0) AS due_today_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} < 0)::int AS overdue_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} < 0), 0) AS overdue_total,
                COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                MAX(i.batch_imported_at) AS batch_imported_at
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
            WHERE {where}
            """
        ).format(
            schema=sql.Identifier(self.schema),
            valor_pendente_sql=valor_pendente_sql,
            days_sql=days_sql,
            where=sql.SQL(" AND ").join(filters),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()

        return InadimplenciaFinanceSummary(
            client_count=int(row["client_count"] or 0) if row else 0,
            total_pendente=_format_money(row["total_pendente"] if row else None),
            due_in_two_days_count=int(row["due_in_two_days_count"] or 0) if row else 0,
            due_in_two_days_total=_format_money(row["due_in_two_days_total"] if row else None),
            due_tomorrow_count=int(row["due_tomorrow_count"] or 0) if row else 0,
            due_tomorrow_total=_format_money(row["due_tomorrow_total"] if row else None),
            due_today_count=int(row["due_today_count"] or 0) if row else 0,
            due_today_total=_format_money(row["due_today_total"] if row else None),
            overdue_count=int(row["overdue_count"] or 0) if row else 0,
            overdue_total=_format_money(row["overdue_total"] if row else None),
            planilha_atualizada_em=_format_reference_date(
                row.get("reference_date") if row else None,
                row.get("batch_imported_at") if row else None,
            ),
        )

    def list_finance_summary_by_filial(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[InadimplenciaFinanceFilialSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._finance_filial_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        days_sql = _days_to_due_sql("i.dias")
        valor_pendente_sql = _money_to_numeric_sql("i.valor_pendente")
        query = sql.SQL(
            """
            SELECT
                i.unb AS filial,
                COUNT(DISTINCT (i.unb, i.cliente))::int AS client_count,
                COALESCE(SUM({valor_pendente_sql}), 0) AS total_pendente,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 2)::int AS due_in_two_days_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 2), 0) AS due_in_two_days_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 1)::int AS due_tomorrow_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 1), 0) AS due_tomorrow_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 0)::int AS due_today_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 0), 0) AS due_today_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} < 0)::int AS overdue_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} < 0), 0) AS overdue_total
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            WHERE {where}
            GROUP BY i.unb
            ORDER BY i.unb
            """
        ).format(
            schema=sql.Identifier(self.schema),
            valor_pendente_sql=valor_pendente_sql,
            days_sql=days_sql,
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        summaries = [
            InadimplenciaFinanceFilialSummary(
                filial=_normalize_code_value(str(row["filial"] or "")),
                client_count=int(row["client_count"] or 0),
                total_pendente=_format_money(row["total_pendente"]),
                due_in_two_days_count=int(row["due_in_two_days_count"] or 0),
                due_in_two_days_total=_format_money(row["due_in_two_days_total"]),
                due_tomorrow_count=int(row["due_tomorrow_count"] or 0),
                due_tomorrow_total=_format_money(row["due_tomorrow_total"]),
                due_today_count=int(row["due_today_count"] or 0),
                due_today_total=_format_money(row["due_today_total"]),
                overdue_count=int(row["overdue_count"] or 0),
                overdue_total=_format_money(row["overdue_total"]),
            )
            for row in rows
        ]
        self._finance_filial_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def list_finance_summary_by_gv(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[InadimplenciaFinanceManagementSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._finance_management_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        filters: list[sql.Composed] = [
            sql.SQL("BTRIM(COALESCE(d.filial_gv_key, '')) <> ''"),
        ]
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        days_sql = _days_to_due_sql("i.dias")
        valor_pendente_sql = _money_to_numeric_sql("i.valor_pendente")
        query = sql.SQL(
            """
            SELECT
                d.filial_gv_key AS manager_code,
                COUNT(DISTINCT (i.unb, i.cliente))::int AS client_count,
                COALESCE(SUM({valor_pendente_sql}), 0) AS total_pendente,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 2)::int AS due_in_two_days_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 2), 0) AS due_in_two_days_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 1)::int AS due_tomorrow_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 1), 0) AS due_tomorrow_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 0)::int AS due_today_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 0), 0) AS due_today_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} < 0)::int AS overdue_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} < 0), 0) AS overdue_total,
                COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                MAX(i.batch_imported_at) AS batch_imported_at
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
            WHERE {where}
            GROUP BY d.filial_gv_key
            ORDER BY d.filial_gv_key
            """
        ).format(
            schema=sql.Identifier(self.schema),
            valor_pendente_sql=valor_pendente_sql,
            days_sql=days_sql,
            where=sql.SQL(" AND ").join(filters),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        summaries = [
            InadimplenciaFinanceManagementSummary(
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")),
                client_count=int(row["client_count"] or 0),
                total_pendente=_format_money(row["total_pendente"]),
                due_in_two_days_count=int(row["due_in_two_days_count"] or 0),
                due_in_two_days_total=_format_money(row["due_in_two_days_total"]),
                due_tomorrow_count=int(row["due_tomorrow_count"] or 0),
                due_tomorrow_total=_format_money(row["due_tomorrow_total"]),
                due_today_count=int(row["due_today_count"] or 0),
                due_today_total=_format_money(row["due_today_total"]),
                overdue_count=int(row["overdue_count"] or 0),
                overdue_total=_format_money(row["overdue_total"]),
                planilha_atualizada_em=_format_reference_date(
                    row.get("reference_date"),
                    row.get("batch_imported_at"),
                ),
            )
            for row in rows
            if normalize_stored_scope_value(str(row["manager_code"] or ""))
        ]
        self._finance_management_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def list_finance_summary_by_seller(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[InadimplenciaFinanceSellerSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._finance_seller_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        filters: list[sql.Composed] = [
            sql.SQL("BTRIM(COALESCE(d.filial_setor_key, '')) <> ''"),
        ]
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        days_sql = _days_to_due_sql("i.dias")
        valor_pendente_sql = _money_to_numeric_sql("i.valor_pendente")
        query = sql.SQL(
            """
            SELECT
                d.filial_setor_key AS seller_code,
                d.filial_gv_key AS manager_code,
                COUNT(DISTINCT (i.unb, i.cliente))::int AS client_count,
                COALESCE(SUM({valor_pendente_sql}), 0) AS total_pendente,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 2)::int AS due_in_two_days_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 2), 0) AS due_in_two_days_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 1)::int AS due_tomorrow_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 1), 0) AS due_tomorrow_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} = 0)::int AS due_today_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} = 0), 0) AS due_today_total,
                COUNT(DISTINCT (i.unb, i.cliente)) FILTER (WHERE {days_sql} < 0)::int AS overdue_count,
                COALESCE(SUM({valor_pendente_sql}) FILTER (WHERE {days_sql} < 0), 0) AS overdue_total,
                COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                MAX(i.batch_imported_at) AS batch_imported_at
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
            WHERE {where}
            GROUP BY d.filial_setor_key, d.filial_gv_key
            ORDER BY d.filial_gv_key, d.filial_setor_key
            """
        ).format(
            schema=sql.Identifier(self.schema),
            valor_pendente_sql=valor_pendente_sql,
            days_sql=days_sql,
            where=sql.SQL(" AND ").join(filters),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        summaries = [
            InadimplenciaFinanceSellerSummary(
                seller_code=normalize_stored_scope_value(str(row["seller_code"] or "")),
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")),
                client_count=int(row["client_count"] or 0),
                total_pendente=_format_money(row["total_pendente"]),
                due_in_two_days_count=int(row["due_in_two_days_count"] or 0),
                due_in_two_days_total=_format_money(row["due_in_two_days_total"]),
                due_tomorrow_count=int(row["due_tomorrow_count"] or 0),
                due_tomorrow_total=_format_money(row["due_tomorrow_total"]),
                due_today_count=int(row["due_today_count"] or 0),
                due_today_total=_format_money(row["due_today_total"]),
                overdue_count=int(row["overdue_count"] or 0),
                overdue_total=_format_money(row["overdue_total"]),
                planilha_atualizada_em=_format_reference_date(
                    row.get("reference_date"),
                    row.get("batch_imported_at"),
                ),
            )
            for row in rows
            if normalize_stored_scope_value(str(row["seller_code"] or ""))
        ]
        self._finance_seller_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def search_by_registration(
        self,
        filial: str,
        cod_pdv: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50,
    ) -> list[InadimplenciaRecord]:
        normalized_filial = _normalize_code_value(filial)
        normalized_cod_pdv = _normalize_code_value(cod_pdv)
        if not normalized_filial:
            raise ValueError("Revenda/filial invalida.")
        if not normalized_cod_pdv:
            raise ValueError("NB/Cod PDV invalido.")

        filters = [
            sql.SQL("i.unb = %s"),
            sql.SQL("i.cliente = %s"),
        ]
        params: list[Any] = [normalized_filial, normalized_cod_pdv]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 100)))
        query = self._base_select(where=sql.SQL(" AND ").join(filters))
        return self._fetch(query, params)

    def search_by_name(
        self,
        query_text: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50,
    ) -> list[InadimplenciaRecord]:
        normalized_query = _normalize_search_text(query_text)
        if not normalized_query:
            raise ValueError("Nome obrigatorio.")

        pattern = f"%{normalized_query}%"
        prefix = f"{normalized_query}%"
        filters = [
            sql.SQL("({} ILIKE %s OR {} ILIKE %s OR {} ILIKE %s)").format(
                _normalized_text_sql("i.nome"),
                _normalized_text_sql("d.nome_fantasia"),
                _normalized_text_sql("d.razao_social"),
            ),
        ]
        params: list[Any] = [pattern, pattern, pattern]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.extend([prefix, prefix, prefix, max(1, min(limit, 100))])
        query = sql.SQL(
            """
            SELECT
                i.unb AS filial,
                i.cliente AS cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), i.nome, '') AS nome,
                i.data_emissao,
                i.data_vencimento,
                i.valor_original,
                i.valor_pendente,
                i.valor_corrigido,
                {days_sql} AS dias,
                COALESCE(
                    NULLIF(i.payload->>'Nota Fiscal', ''),
                    NULLIF(i.payload->>'NF', ''),
                    NULLIF(i.payload->>'NFe', ''),
                    NULLIF(i.payload->>'Titulo', ''),
                    ''
                ) AS nota_fiscal,
                COALESCE(b.reference_date::text, '') AS reference_date,
                i.batch_imported_at
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
            WHERE {where}
            ORDER BY
                CASE
                    WHEN {nome_sql} ILIKE %s THEN 0
                    WHEN {fantasia_sql} ILIKE %s THEN 1
                    WHEN {razao_sql} ILIKE %s THEN 2
                    ELSE 3
                END,
                nome,
                filial,
                cod_pdv,
                i.data_vencimento
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            nome_sql=_normalized_text_sql("i.nome"),
            fantasia_sql=_normalized_text_sql("d.nome_fantasia"),
            razao_sql=_normalized_text_sql("d.razao_social"),
            days_sql=_days_to_due_sql("i.dias"),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch(query, params)

    def search_client_summaries_by_name(
        self,
        query_text: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 20,
    ) -> list[InadimplenciaClientSummary]:
        normalized_query = _normalize_search_text(query_text)
        if not normalized_query:
            raise ValueError("Nome obrigatorio.")

        pattern = f"%{normalized_query}%"
        prefix = f"{normalized_query}%"
        filters = [
            sql.SQL("({} ILIKE %s OR {} ILIKE %s OR {} ILIKE %s)").format(
                _normalized_text_sql("i.nome"),
                _normalized_text_sql("d.nome_fantasia"),
                _normalized_text_sql("d.razao_social"),
            ),
        ]
        params: list[Any] = [pattern, pattern, pattern]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.extend([prefix, max(1, min(limit, 30))])
        query = sql.SQL(
            """
            WITH grouped AS (
                SELECT
                    i.unb AS filial,
                    i.cliente AS cod_pdv,
                    COALESCE(
                        NULLIF(MAX(d.nome_fantasia), ''),
                        NULLIF(MAX(d.razao_social), ''),
                        MAX(i.nome),
                        ''
                    ) AS nome,
                    COUNT(*)::int AS title_count,
                    SUM({valor_pendente_sql}) AS total_pendente,
                    COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                    MAX(i.batch_imported_at) AS batch_imported_at
                FROM {schema}.inadimplencia_latest i
                JOIN {schema}.dclientes_latest d
                  ON d.filial = i.unb
                 AND d.cod_pdv = i.cliente
                LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
                WHERE {where}
                GROUP BY i.unb, i.cliente
            )
            SELECT
                filial,
                cod_pdv,
                nome,
                title_count,
                total_pendente,
                reference_date,
                batch_imported_at
            FROM grouped
            ORDER BY
                CASE
                    WHEN {grouped_nome_sql} ILIKE %s THEN 0
                    ELSE 1
                END,
                nome,
                filial,
                cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            valor_pendente_sql=_money_to_numeric_sql("i.valor_pendente"),
            grouped_nome_sql=_normalized_text_sql("nome"),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch_client_summaries(query, params)

    def list_client_summaries_in_scope(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "total_pendente",
        due_bucket: str | None = None,
    ) -> list[InadimplenciaClientSummary]:
        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        due_bucket_filter = _due_bucket_filter_sql(due_bucket, _days_to_due_sql("i.dias"))
        if due_bucket_filter is not None:
            filters.append(due_bucket_filter)
        params.extend([max(1, min(limit, 30)), max(int(offset), 0)])
        order_by_sql = _client_summary_order_by_sql(order_by)
        query = sql.SQL(
            """
            WITH grouped AS (
                SELECT
                    i.unb AS filial,
                    i.cliente AS cod_pdv,
                    COALESCE(
                        NULLIF(MAX(d.nome_fantasia), ''),
                        NULLIF(MAX(d.razao_social), ''),
                        MAX(i.nome),
                        ''
                    ) AS nome,
                    COUNT(*)::int AS title_count,
                    SUM({valor_pendente_sql}) AS total_pendente,
                    COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                    MAX(i.batch_imported_at) AS batch_imported_at
                FROM {schema}.inadimplencia_latest i
                JOIN {schema}.dclientes_latest d
                  ON d.filial = i.unb
                 AND d.cod_pdv = i.cliente
                LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
                WHERE {where}
                GROUP BY i.unb, i.cliente
            )
            SELECT
                filial,
                cod_pdv,
                nome,
                title_count,
                total_pendente,
                reference_date,
                batch_imported_at
            FROM grouped
            ORDER BY {order_by}
            LIMIT %s
            OFFSET %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            valor_pendente_sql=_money_to_numeric_sql("i.valor_pendente"),
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
            order_by=order_by_sql,
        )
        return self._fetch_client_summaries(query, params)

    def search_by_document(
        self,
        document: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50,
    ) -> list[InadimplenciaRecord]:
        normalized_document = _normalize_document(document)
        if not normalized_document:
            raise ValueError("Informe um CPF ou CNPJ valido.")

        filters = [sql.SQL("REGEXP_REPLACE(COALESCE(d.documento, ''), '[^0-9]', '', 'g') = %s")]
        params: list[Any] = [normalized_document]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 100)))
        query = self._base_select(where=sql.SQL(" AND ").join(filters))
        return self._fetch(query, params)

    def list_upcoming_by_visit_day(
        self,
        visit_day: str,
        seller_code: str | None = None,
        manager_code: str | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 80,
    ) -> list[InadimplenciaVisitAlert]:
        normalized_visit_day = _normalize_visit_day(visit_day)
        if not normalized_visit_day:
            raise ValueError("Dia de visita obrigatorio.")
        normalized_seller_code = normalize_stored_scope_value(seller_code or "")
        normalized_manager_code = normalize_stored_scope_value(manager_code or "")

        days_sql = _days_to_due_sql("i.dias")
        filters: list[sql.Composed] = []
        params: list[Any] = []
        _append_visit_day_filter(
            filters=filters,
            params=params,
            visit_day=visit_day,
            field_sql=sql.SQL("UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')))"),
        )
        if normalized_seller_code:
            _append_scope_value_filter(
                filters=filters,
                params=params,
                value=normalized_seller_code,
                key_field="d.filial_setor_key",
            )
        if normalized_manager_code:
            _append_scope_value_filter(
                filters=filters,
                params=params,
                value=normalized_manager_code,
                key_field="d.filial_gv_key",
            )
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 200)))

        query = sql.SQL(
            """
            WITH route_clients AS (
                SELECT
                    d.filial,
                    d.cod_pdv,
                    d.nome_fantasia,
                    d.razao_social,
                    {setor_sql} AS seller_code,
                    {gv_sql} AS manager_code
                FROM {schema}.dclientes_latest d
                WHERE {where}
            )
            SELECT
                i.unb AS filial,
                i.cliente AS cod_pdv,
                COALESCE(
                    NULLIF(MAX(route_clients.nome_fantasia), ''),
                    NULLIF(MAX(route_clients.razao_social), ''),
                    MAX(i.nome),
                    ''
                ) AS nome,
                MAX(route_clients.seller_code) AS seller_code,
                MAX(route_clients.manager_code) AS manager_code,
                COUNT(*)::int AS title_count,
                SUM({valor_pendente_sql}) AS total_pendente,
                MIN({days_sql})::int AS nearest_days_to_due,
                COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                MAX(i.batch_imported_at) AS batch_imported_at
            FROM route_clients
            JOIN {schema}.inadimplencia_latest i
              ON i.unb = route_clients.filial
             AND i.cliente = route_clients.cod_pdv
            LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
            WHERE {days_sql} IS NOT NULL
              AND {days_sql} <= 2
            GROUP BY i.unb, i.cliente
            ORDER BY
                nearest_days_to_due ASC,
                title_count DESC,
                total_pendente DESC,
                nome,
                filial,
                cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            days_sql=days_sql,
            valor_pendente_sql=_money_to_numeric_sql("i.valor_pendente"),
            setor_sql=_code_field_sql("d.filial_setor_key"),
            gv_sql=_code_field_sql("d.filial_gv_key"),
        )
        return self._fetch_visit_alerts(query, params)

    def list_visit_day_risk_by_seller(
        self,
        visit_day_token: str,
        visit_day_values: list[str] | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 80,
    ) -> list[InadimplenciaVisitRiskSummary]:
        normalized_visit_day_token = _normalize_visit_day_token(visit_day_token)
        normalized_visit_day_values = _normalize_exact_visit_day_values(visit_day_values)
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        if not normalized_visit_day_token:
            raise ValueError("Dia de visita obrigatorio.")
        normalized_limit = max(1, min(limit, 200))
        inadimplencia_batch_id = self._get_latest_batch_id("inadimplencia")
        if inadimplencia_batch_id is None:
            return []
        cache_key = (
            ("exact", *normalized_visit_day_values) if normalized_visit_day_values else ("token", normalized_visit_day_token),
            tuple(normalized_sectors),
            tuple(normalized_gv_vdes),
            normalized_limit,
        )
        cached_payload = self._visit_risk_summary_cache.get(cache_key)
        now = monotonic()
        if cached_payload is not None and now < cached_payload[0]:
            return list(cached_payload[1])

        days_sql = _days_to_due_sql("i.dias")
        filters = [
            sql.SQL("BTRIM(COALESCE({}, '')) <> ''").format(_code_field_sql("d.filial_setor_key")),
        ]
        params: list[Any] = [inadimplencia_batch_id]
        if normalized_visit_day_values:
            filters.append(sql.SQL("BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')) = ANY(%s)"))
            params.append(normalized_visit_day_values)
        else:
            filters.append(sql.SQL("POSITION(%s IN UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')))) > 0"))
            params.append(normalized_visit_day_token)
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        params.extend([inadimplencia_batch_id, normalized_limit])

        query = sql.SQL(
            """
            WITH latest_batch_info AS MATERIALIZED (
                SELECT reference_date, imported_at
                FROM {schema}.import_batches
                WHERE id = %s
            ),
            route_clients AS MATERIALIZED (
                SELECT
                    d.filial,
                    d.cod_pdv,
                    {setor_sql} AS seller_code,
                    {gv_sql} AS manager_code
                FROM {schema}.dclientes_latest d
                WHERE {where}
            ),
            active_titles AS MATERIALIZED (
                SELECT
                    i.unb AS filial,
                    i.cliente AS cod_pdv,
                    {days_sql} AS nearest_days_to_due,
                    {valor_pendente_sql} AS valor_pendente
                FROM {schema}.inadimplencia_snapshot i
                WHERE i.batch_id = %s
                  AND {days_sql} IS NOT NULL
                  AND {days_sql} <= 0
            ),
            client_risks AS (
                SELECT
                    route_clients.seller_code,
                    route_clients.manager_code,
                    route_clients.filial,
                    route_clients.cod_pdv,
                    MIN(active_titles.nearest_days_to_due)::int AS nearest_days_to_due,
                    SUM(active_titles.valor_pendente) AS total_pendente
                FROM route_clients
                JOIN active_titles
                  ON active_titles.filial = route_clients.filial
                 AND active_titles.cod_pdv = route_clients.cod_pdv
                GROUP BY
                    route_clients.seller_code,
                    route_clients.manager_code,
                    route_clients.filial,
                    route_clients.cod_pdv
            )
            SELECT
                seller_code,
                manager_code,
                COUNT(*)::int AS client_count,
                COUNT(*) FILTER (WHERE nearest_days_to_due < 0)::int AS overdue_count,
                COUNT(*) FILTER (WHERE nearest_days_to_due = 0)::int AS due_today_count,
                SUM(total_pendente) AS total_pendente,
                COALESCE(MAX(latest_batch_info.reference_date)::text, '') AS reference_date,
                MAX(latest_batch_info.imported_at) AS batch_imported_at
            FROM client_risks
            CROSS JOIN latest_batch_info
            GROUP BY seller_code, manager_code
            ORDER BY client_count DESC, total_pendente DESC, seller_code, manager_code
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            days_sql=days_sql,
            valor_pendente_sql=_money_to_numeric_sql("i.valor_pendente"),
            setor_sql=_code_field_sql("d.filial_setor_key"),
            gv_sql=_code_field_sql("d.filial_gv_key"),
        )
        summaries = self._fetch_visit_risk_summaries(query, params, normalized_visit_day_token)
        self._visit_risk_summary_cache[cache_key] = (now + 90.0, list(summaries))
        return summaries

    def list_visit_day_risk_alerts_by_seller(
        self,
        visit_day_token: str,
        seller_code: str,
        visit_day_values: list[str] | None = None,
        manager_code: str | None = None,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 120,
    ) -> list[InadimplenciaVisitAlert]:
        normalized_visit_day_token = _normalize_visit_day_token(visit_day_token)
        normalized_visit_day_values = _normalize_exact_visit_day_values(visit_day_values)
        normalized_seller_code = normalize_stored_scope_value(seller_code)
        normalized_manager_code = normalize_stored_scope_value(manager_code or "")
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        if not normalized_visit_day_token or not normalized_seller_code:
            raise ValueError("Dia de visita e setor sao obrigatorios.")
        normalized_limit = max(1, min(limit, 200))
        inadimplencia_batch_id = self._get_latest_batch_id("inadimplencia")
        if inadimplencia_batch_id is None:
            return []
        cache_key = (
            ("exact", *normalized_visit_day_values) if normalized_visit_day_values else ("token", normalized_visit_day_token),
            normalized_seller_code,
            normalized_manager_code,
            tuple(normalized_sectors),
            tuple(normalized_gv_vdes),
            normalized_limit,
        )
        cached_payload = self._visit_risk_alert_cache.get(cache_key)
        now = monotonic()
        if cached_payload is not None and now < cached_payload[0]:
            return list(cached_payload[1])

        days_sql = _days_to_due_sql("i.dias")
        filters: list[sql.Composed] = []
        params: list[Any] = [inadimplencia_batch_id]
        if normalized_visit_day_values:
            filters.append(sql.SQL("BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')) = ANY(%s)"))
            params.append(normalized_visit_day_values)
        else:
            filters.append(sql.SQL("POSITION(%s IN UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')))) > 0"))
            params.append(normalized_visit_day_token)
        _append_scope_value_filter(
            filters=filters,
            params=params,
            value=normalized_seller_code,
            key_field="d.filial_setor_key",
        )
        if normalized_manager_code:
            _append_scope_value_filter(
                filters=filters,
                params=params,
                value=normalized_manager_code,
                key_field="d.filial_gv_key",
            )
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        params.extend([inadimplencia_batch_id, normalized_limit])

        query = sql.SQL(
            """
            WITH latest_batch_info AS MATERIALIZED (
                SELECT reference_date, imported_at
                FROM {schema}.import_batches
                WHERE id = %s
            ),
            route_clients AS MATERIALIZED (
                SELECT
                    d.filial,
                    d.cod_pdv,
                    d.nome_fantasia,
                    d.razao_social,
                    {setor_sql} AS seller_code,
                    {gv_sql} AS manager_code
                FROM {schema}.dclientes_latest d
                WHERE {where}
            ),
            active_titles AS MATERIALIZED (
                SELECT
                    i.unb AS filial,
                    i.cliente AS cod_pdv,
                    i.nome,
                    {valor_pendente_sql} AS valor_pendente,
                    {days_sql} AS nearest_days_to_due
                FROM {schema}.inadimplencia_snapshot i
                WHERE i.batch_id = %s
                  AND {days_sql} IS NOT NULL
                  AND {days_sql} <= 0
            )
            SELECT
                active_titles.filial AS filial,
                active_titles.cod_pdv AS cod_pdv,
                COALESCE(
                    NULLIF(MAX(route_clients.nome_fantasia), ''),
                    NULLIF(MAX(route_clients.razao_social), ''),
                    MAX(active_titles.nome),
                    ''
                ) AS nome,
                MAX(route_clients.seller_code) AS seller_code,
                MAX(route_clients.manager_code) AS manager_code,
                COUNT(*)::int AS title_count,
                SUM(active_titles.valor_pendente) AS total_pendente,
                MIN(active_titles.nearest_days_to_due)::int AS nearest_days_to_due,
                COALESCE(MAX(latest_batch_info.reference_date)::text, '') AS reference_date,
                MAX(latest_batch_info.imported_at) AS batch_imported_at
            FROM route_clients
            JOIN active_titles
              ON active_titles.filial = route_clients.filial
             AND active_titles.cod_pdv = route_clients.cod_pdv
            CROSS JOIN latest_batch_info
            GROUP BY active_titles.filial, active_titles.cod_pdv
            ORDER BY
                nearest_days_to_due ASC,
                title_count DESC,
                total_pendente DESC,
                nome,
                filial,
                cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            days_sql=days_sql,
            valor_pendente_sql=_money_to_numeric_sql("i.valor_pendente"),
            setor_sql=_code_field_sql("d.filial_setor_key"),
            gv_sql=_code_field_sql("d.filial_gv_key"),
        )
        alerts = self._fetch_visit_alerts(query, params)
        self._visit_risk_alert_cache[cache_key] = (now + 90.0, list(alerts))
        return alerts

    def _apply_access_filter(
        self,
        filters: list[sql.Composed],
        params: list[Any],
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
    ) -> None:
        access_filter, access_params = self._build_access_filter(allowed_sectors, allowed_gv_vdes)
        if access_filter is None:
            return
        filters.append(access_filter)
        params.extend(access_params)

    def _build_access_filter(
        self,
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
    ) -> tuple[sql.Composed | None, list[Any]]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        if not normalized_sectors and not normalized_gv_vdes:
            if _has_scope_values(allowed_sectors) or _has_scope_values(allowed_gv_vdes):
                return sql.SQL("FALSE"), []
            return None, []

        scope_filters, params = _build_commercial_scope_filters(
            allowed_sectors=normalized_sectors,
            allowed_gv_vdes=normalized_gv_vdes,
        )
        if not scope_filters:
            return sql.SQL("FALSE"), []
        return sql.SQL("({})").format(sql.SQL(" OR ").join(scope_filters)), params

    def _base_select(self, where: sql.SQL) -> sql.SQL:
        return sql.SQL(
            """
            SELECT
                i.unb AS filial,
                i.cliente AS cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), i.nome, '') AS nome,
                i.data_emissao,
                i.data_vencimento,
                i.valor_original,
                i.valor_pendente,
                i.valor_corrigido,
                {days_sql} AS dias,
                COALESCE(
                    NULLIF(i.payload->>'Nota Fiscal', ''),
                    NULLIF(i.payload->>'NF', ''),
                    NULLIF(i.payload->>'NFe', ''),
                    NULLIF(i.payload->>'Titulo', ''),
                    ''
                ) AS nota_fiscal,
                COALESCE(b.reference_date::text, '') AS reference_date,
                i.batch_imported_at
            FROM {schema}.inadimplencia_latest i
            JOIN {schema}.dclientes_latest d
              ON d.filial = i.unb
             AND d.cod_pdv = i.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = i.batch_id
            WHERE {where}
            ORDER BY
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), i.nome, ''),
                i.unb,
                i.cliente,
                i.data_vencimento
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            days_sql=_days_to_due_sql("i.dias"),
            where=where,
        )

    def _fetch(self, query: sql.SQL, params: list[Any]) -> list[InadimplenciaRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [
            InadimplenciaRecord(
                filial=_normalize_code_value(str(row["filial"] or "")),
                cod_pdv=_normalize_code_value(str(row["cod_pdv"] or "")),
                nome=str(row["nome"] or ""),
                data_emissao=str(row["data_emissao"] or ""),
                data_vencimento=str(row["data_vencimento"] or ""),
                valor_original=_format_money(row["valor_original"]),
                valor_pendente=_format_money(row["valor_pendente"]),
                valor_corrigido=_format_money(row["valor_corrigido"]),
                dias=_format_days(row["dias"]),
                planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
                nota_fiscal=_normalize_invoice_number(str(row.get("nota_fiscal") or "")),
            )
            for row in rows
        ]

    def _fetch_client_summaries(self, query: sql.SQL, params: list[Any]) -> list[InadimplenciaClientSummary]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            InadimplenciaClientSummary(
                filial=_normalize_code_value(str(row["filial"] or "")),
                cod_pdv=_normalize_code_value(str(row["cod_pdv"] or "")),
                nome=str(row["nome"] or ""),
                title_count=int(row["title_count"] or 0),
                total_pendente=_format_money(row.get("total_pendente")),
                planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
            )
            for row in rows
        ]

    def _fetch_visit_alerts(self, query: sql.SQL, params: list[Any]) -> list[InadimplenciaVisitAlert]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            InadimplenciaVisitAlert(
                filial=_normalize_code_value(str(row["filial"] or "")),
                cod_pdv=_normalize_code_value(str(row["cod_pdv"] or "")),
                nome=str(row["nome"] or ""),
                seller_code=normalize_stored_scope_value(str(row["seller_code"] or "")) or "-",
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")) or "-",
                title_count=int(row["title_count"] or 0),
                total_pendente=_format_money(row.get("total_pendente")),
                nearest_days_to_due=int(row["nearest_days_to_due"] or 0),
                planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
            )
            for row in rows
        ]

    def _fetch_visit_risk_summaries(
        self,
        query: sql.SQL,
        params: list[Any],
        visit_day_token: str,
    ) -> list[InadimplenciaVisitRiskSummary]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de inadimplencia indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            InadimplenciaVisitRiskSummary(
                seller_code=normalize_stored_scope_value(str(row["seller_code"] or "")) or "-",
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")) or "-",
                client_count=int(row["client_count"] or 0),
                overdue_count=int(row["overdue_count"] or 0),
                due_today_count=int(row["due_today_count"] or 0),
                total_pendente=_format_money(row.get("total_pendente")),
                visit_day_token=visit_day_token,
                planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
            )
            for row in rows
        ]

    @contextmanager
    def _connect(self, row_factory: Any | None = None) -> Any:
        if self._pool is None:
            self._pool = get_connection_pool(
                self.database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
            )
        with self._pool.connection() as conn:
            conn.row_factory = row_factory or tuple_row
            yield conn

    def _get_latest_batch_id(self, dataset_name: str) -> int | None:
        normalized_dataset = str(dataset_name or "").strip().lower()
        if not normalized_dataset:
            return None

        now = monotonic()
        cached_payload = self._latest_batch_id_cache.get(normalized_dataset)
        if cached_payload is not None and now < cached_payload[0]:
            return cached_payload[1]

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT id
                        FROM {}.import_batches
                        WHERE dataset_name = %s
                        ORDER BY imported_at DESC, id DESC
                        LIMIT 1
                        """
                    ).format(sql.Identifier(self.schema)),
                    (normalized_dataset,),
                )
                row = cur.fetchone()

        latest_batch_id = int(row["id"]) if row and row.get("id") is not None else None
        self._latest_batch_id_cache[normalized_dataset] = (now + 30.0, latest_batch_id)
        return latest_batch_id

    def _cache_status(self, payload: dict[str, Any]) -> None:
        self._status_cache = dict(payload)
        self._status_cache_expires_at = monotonic() + (300.0 if payload.get("ready") else 10.0)


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _normalize_code_value(value: str) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _normalize_document(value: str) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if len(digits) not in {11, 14}:
        return ""
    return digits


def _normalize_scope_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = normalize_stored_scope_value(value)
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _normalize_visit_day(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_visit_day_token(value: str) -> str:
    normalized = _normalize_visit_day(value).upper()
    if not normalized:
        return ""
    return normalized if normalized.endswith("/") else f"{normalized}/"


def _normalize_exact_visit_day_values(
    values: list[str] | tuple[str, ...] | None,
) -> list[str]:
    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        normalized = _normalize_visit_day(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _append_visit_day_filter(
    *,
    filters: list[sql.Composed],
    params: list[Any],
    visit_day: str,
    field_sql: sql.SQL,
) -> None:
    normalized_visit_day = _normalize_visit_day(visit_day)
    normalized_visit_day_token = _normalize_visit_day_token(visit_day)
    if not normalized_visit_day or not normalized_visit_day_token:
        raise ValueError("Dia de visita obrigatorio.")
    filters.append(
        sql.SQL(
            "("
            "POSITION(%s IN {field_sql}) > 0 "
            "OR {field_sql} = %s"
            ")"
        ).format(field_sql=field_sql)
    )
    params.extend([normalized_visit_day_token, normalized_visit_day.upper()])


def _normalize_search_text(value: str) -> str:
    lowered = str(value or "").strip().lower()
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", lowered) if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _code_field_sql(field_name: str) -> sql.SQL:
    return sql.SQL(field_name) if "." in field_name else sql.Identifier(field_name)


def _append_scope_value_filter(
    *,
    filters: list[sql.Composed],
    params: list[Any],
    value: str,
    key_field: str,
) -> None:
    if not value:
        return
    normalized_value = normalize_stored_scope_value(value)
    if normalized_value.startswith("dc:") or not split_scope_pair(normalized_value):
        filters.append(sql.SQL("FALSE"))
        return
    filters.append(sql.SQL("{} = %s").format(_code_field_sql(key_field)))
    params.append(normalized_value)


def _build_commercial_scope_filters(
    *,
    allowed_sectors: list[str],
    allowed_gv_vdes: list[str],
) -> tuple[list[sql.Composed], list[Any]]:
    scope_filters: list[sql.Composed] = []
    params: list[Any] = []

    filial_codes = partition_filial_scopes(allowed_sectors)
    sector_keys, _legacy_sector_codes = partition_sector_scopes(allowed_sectors)
    gv_keys, dc_keys, _legacy_gv_codes = partition_gv_scopes(allowed_gv_vdes)

    if filial_codes:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("d.filial")))
        params.append(filial_codes)
    if sector_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("d.filial_setor_key")))
        params.append(sector_keys)
    if gv_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("d.filial_gv_key")))
        params.append(gv_keys)
    dc_scope_keys = [value[len("dc:") :] for value in dc_keys]
    if dc_scope_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("d.filial_dc_key")))
        params.append(dc_scope_keys)

    return scope_filters, params


def _has_scope_values(values: list[str] | None) -> bool:
    return any(str(value or "").strip() for value in values or [])


def _normalized_text_sql(field_name: str) -> sql.SQL:
    return sql.SQL(
        "REGEXP_REPLACE(TRANSLATE(LOWER(COALESCE({field}, '')), {source}, {target}), '\\s+', ' ', 'g')"
    ).format(
        field=_code_field_sql(field_name),
        source=sql.Literal(_ACCENTED_SQL_SOURCE),
        target=sql.Literal(_ACCENTED_SQL_TARGET),
    )


def _money_to_numeric_sql(field_name: str) -> sql.SQL:
    return sql.SQL(
        "CASE "
        "WHEN BTRIM(COALESCE({field}, '')) = '' THEN 0::numeric "
        "ELSE COALESCE(NULLIF(REPLACE(REPLACE(REPLACE(BTRIM({field}), '.', ''), ',', '.'), '+', ''), ''), '0')::numeric "
        "END"
    ).format(field=_code_field_sql(field_name))


def _days_to_due_sql(field_name: str, due_date_field_name: str = "i.data_vencimento") -> sql.SQL:
    due_date_field = _code_field_sql(due_date_field_name)
    imported_days_sql = sql.SQL(
        "CASE "
        "WHEN REGEXP_REPLACE(BTRIM(COALESCE({field}, '')), '[^0-9-]', '', 'g') = '' THEN NULL "
        "ELSE REGEXP_REPLACE(BTRIM(COALESCE({field}, '')), '[^0-9-]', '', 'g')::int "
        "END"
    ).format(field=_code_field_sql(field_name))
    return sql.SQL(
        "CASE "
        "WHEN BTRIM(COALESCE({due_date_field}, '')) ~ '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}$' "
        "THEN (TO_DATE(BTRIM({due_date_field}), 'DD/MM/YYYY') - CURRENT_DATE)::int "
        "WHEN BTRIM(COALESCE({due_date_field}, '')) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$' "
        "THEN (TO_DATE(BTRIM({due_date_field}), 'YYYY-MM-DD') - CURRENT_DATE)::int "
        "ELSE {imported_days_sql} "
        "END"
    ).format(
        due_date_field=due_date_field,
        imported_days_sql=imported_days_sql,
    )


def _normalize_due_bucket(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"in_two_days", "tomorrow", "today", "overdue"}:
        return normalized
    return ""


def _due_bucket_filter_sql(due_bucket: str | None, days_sql: sql.SQL) -> sql.SQL | None:
    normalized_due_bucket = _normalize_due_bucket(due_bucket)
    if not normalized_due_bucket:
        return None
    if normalized_due_bucket == "in_two_days":
        return sql.SQL("{} = 2").format(days_sql)
    if normalized_due_bucket == "tomorrow":
        return sql.SQL("{} = 1").format(days_sql)
    if normalized_due_bucket == "today":
        return sql.SQL("{} = 0").format(days_sql)
    return sql.SQL("{} < 0").format(days_sql)


def _client_summary_order_by_sql(order_by: str) -> sql.SQL:
    normalized = str(order_by or "").strip().lower()
    if normalized == "name":
        return sql.SQL("nome, filial, cod_pdv")
    return sql.SQL("total_pendente DESC, title_count DESC, nome, filial, cod_pdv")


def _format_money(value: Any) -> str:
    if value is None:
        return "0,00"
    if isinstance(value, Decimal):
        return f"{value:.2f}".replace(".", ",")
    if isinstance(value, (int, float)):
        return f"{value:.2f}".replace(".", ",")
    raw = str(value or "").strip()
    if not raw:
        return "0,00"
    if "," in raw:
        cleaned = raw.replace(".", "").replace(",", ".").replace("+", "").strip()
    else:
        cleaned = raw.replace("+", "").strip()
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return raw
    return f"{amount:.2f}".replace(".", ",")


def _format_days(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    sign = "-" if raw.startswith("-") else ""
    digits = "".join(char for char in raw if char.isdigit())
    if not digits:
        return raw
    normalized = digits.lstrip("0") or "0"
    return f"{sign}{normalized}"


def _normalize_invoice_number(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    digits = "".join(char for char in raw if char.isdigit())
    if digits:
        return digits.lstrip("0") or "0"
    return raw


def _format_reference_date(reference_date: Any, batch_imported_at: Any) -> str:
    raw_reference = str(reference_date or "").strip()
    if raw_reference:
        try:
            parsed = datetime.strptime(raw_reference, "%Y-%m-%d")
            return parsed.strftime("%d/%m/%Y")
        except ValueError:
            return raw_reference
    if isinstance(batch_imported_at, datetime):
        if batch_imported_at.tzinfo is not None:
            batch_imported_at = batch_imported_at.astimezone(timezone.utc)
        return batch_imported_at.strftime("%d/%m/%Y")
    return str(batch_imported_at or "")
