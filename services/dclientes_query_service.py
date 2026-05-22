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
    normalize_numeric_code,
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
class DClienteRecord:
    filial: str
    cod_pdv: str
    razao_social: str
    nome_fantasia: str
    telefone: str
    dia_visita: str
    vendedor: str
    status: str
    cidade: str
    cond_pag_atual: str
    limite_credito: str
    total_pendente: str
    total_comodatos_pendentes: int
    ultima_atualizacao_tabela: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisitSellerSummary:
    seller_code: str
    manager_code: str
    visit_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DClientesScopeSummary:
    client_count: int
    seller_count: int
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DClientesManagementSummary:
    manager_code: str
    client_count: int
    seller_count: int
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DClientesFilialSummary:
    filial: str
    client_count: int
    seller_count: int
    manager_count: int
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DClientesQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None
        self._last_error = ""
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_expires_at = 0.0
        self._latest_batch_id_cache: int | None = None
        self._latest_batch_id_cache_expires_at = 0.0
        self._visit_days_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...], int],
            tuple[float, list[str]],
        ] = {}
        self._scope_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, DClientesScopeSummary],
        ] = {}
        self._management_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[DClientesManagementSummary]],
        ] = {}
        self._filial_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[DClientesFilialSummary]],
        ] = {}
        self._gv_options_cache: dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[float, list[str]]] = {}
        self._gv_scope_expand_cache: dict[tuple[str, ...], tuple[float, list[str]]] = {}
        self._dc_scope_expand_cache: dict[tuple[str, ...], tuple[float, list[str]]] = {}

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
                                  AND table_name = 'dclientes_latest'
                            ) AS has_dclientes,
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
                                  AND table_name = 'comodatos_latest'
                            ) AS has_comodatos
                        """,
                        (self.schema, self.schema, self.schema),
                    )
                    row = cur.fetchone()
            has_dclientes = bool(row and row["has_dclientes"])
            has_inadimplencia = bool(row and row["has_inadimplencia"])
            has_comodatos = bool(row and row["has_comodatos"])
            ready = has_dclientes and has_inadimplencia and has_comodatos
            self._last_error = ""
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": has_dclientes,
                "inadimplencia_view_exists": has_inadimplencia,
                "comodatos_view_exists": has_comodatos,
                "last_error": (
                    ""
                    if ready
                    else "Views reports.dclientes_latest, reports.inadimplencia_latest e/ou reports.comodatos_latest nao encontradas."
                ),
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
                "last_error": self._last_error,
            }
            self._cache_status(payload)
            return payload

    def search_by_registration(
        self,
        filial: str,
        cod_pdv: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[DClienteRecord]:
        normalized_filial = _normalize_filial(filial)
        normalized_cod_pdv = _normalize_cod_pdv(cod_pdv)
        if not normalized_filial:
            raise ValueError("Revenda/filial invalida.")
        if not normalized_cod_pdv:
            raise ValueError("NB/Cod PDV invalido.")

        filters = [
            sql.SQL("{} = %s").format(_code_field_sql("filial")),
            sql.SQL("{} = %s").format(_code_field_sql("cod_pdv")),
        ]
        params: list[Any] = [normalized_filial, normalized_cod_pdv]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        base_query = self._base_rows_query(where=sql.SQL(" AND ").join(filters))
        query = self._details_query_from_base(base_query, order_by=sql.SQL("base.filial, base.cod_pdv"))
        return self._fetch(query, params)

    def search_by_fantasia(
        self,
        query_text: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 5,
    ) -> list[DClienteRecord]:
        normalized_query = _normalize_search_text(query_text)
        if not normalized_query:
            raise ValueError("Nome fantasia obrigatorio.")

        pattern = f"%{normalized_query}%"
        prefix = f"{normalized_query}%"
        filters = [
            sql.SQL("({} ILIKE %s OR {} ILIKE %s)").format(
                _normalized_text_sql("nome_fantasia"),
                _normalized_text_sql("razao_social"),
            ),
        ]
        params: list[Any] = [pattern, pattern]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.extend([prefix, prefix, max(1, min(limit, 10)), prefix, prefix])
        base_query = sql.SQL(
            """
            SELECT
                filial,
                cod_pdv,
                razao_social,
                nome_fantasia,
                status_pdv,
                setor_vde,
                payload,
                payload ->> 'Cidade' AS cidade_payload,
                batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            ORDER BY
                CASE
                    WHEN {normalized_nome_sql} ILIKE %s THEN 0
                    WHEN {normalized_razao_sql} ILIKE %s THEN 1
                    ELSE 2
                END,
                nome_fantasia,
                razao_social
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            normalized_nome_sql=_normalized_text_sql("nome_fantasia"),
            normalized_razao_sql=_normalized_text_sql("razao_social"),
        )
        query = self._details_query_from_base(
            base_query,
            order_by=sql.SQL(
                """
                CASE
                    WHEN {normalized_nome_sql} ILIKE %s THEN 0
                    WHEN {normalized_razao_sql} ILIKE %s THEN 1
                    ELSE 2
                END,
                base.nome_fantasia,
                base.razao_social
                """
            ).format(
                normalized_nome_sql=_normalized_text_sql("base.nome_fantasia"),
                normalized_razao_sql=_normalized_text_sql("base.razao_social"),
            ),
        )
        return self._fetch(query, params)

    def search_by_document(
        self,
        document: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 20,
    ) -> list[DClienteRecord]:
        normalized_document = _normalize_document(document)
        if not normalized_document:
            raise ValueError("Informe um CPF ou CNPJ valido.")

        filters = [
            sql.SQL("REGEXP_REPLACE(COALESCE(documento, ''), '[^0-9]', '', 'g') = %s"),
        ]
        params: list[Any] = [normalized_document]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 50)))
        base_query = sql.SQL(
            """
            SELECT
                filial,
                cod_pdv,
                razao_social,
                nome_fantasia,
                status_pdv,
                setor_vde,
                payload,
                payload ->> 'Cidade' AS cidade_payload,
                batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            ORDER BY filial, cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        query = self._details_query_from_base(base_query, order_by=sql.SQL("base.filial, base.cod_pdv"))
        return self._fetch(query, params)

    def list_visit_days(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 10,
    ) -> list[str]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        normalized_limit = max(1, min(limit, 20))
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes), normalized_limit)
        cached_payload = self._visit_days_cache.get(cache_key)
        now = monotonic()
        if cached_payload is not None and now < cached_payload[0]:
            return list(cached_payload[1])

        filters = [
            sql.SQL("BTRIM(COALESCE(payload ->> 'Dia de Visita do VDE', '')) <> ''"),
        ]
        params: list[Any] = []
        access_filter, access_params = self._build_access_filter(normalized_sectors, normalized_gv_vdes)
        if access_filter is not None:
            filters.append(access_filter)
            params.extend(access_params)
        params.append(normalized_limit)
        query = sql.SQL(
            """
            SELECT DISTINCT BTRIM(COALESCE(payload ->> 'Dia de Visita do VDE', '')) AS dia_visita
            FROM {schema}.dclientes_latest
            WHERE {where}
            ORDER BY dia_visita
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        visit_days = self._fetch_visit_days(query, params)
        self._visit_days_cache[cache_key] = (now + 120.0, list(visit_days))
        return visit_days

    def list_clients_by_visit_day(
        self,
        visit_day: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 200,
    ) -> list[DClienteRecord]:
        filters: list[sql.Composed] = []
        params: list[Any] = []
        _append_visit_day_filter(filters=filters, params=params, visit_day=visit_day)
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 10000)))
        query = sql.SQL(
            """
            SELECT
                filial,
                cod_pdv,
                razao_social,
                nome_fantasia,
                batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            ORDER BY COALESCE(NULLIF(nome_fantasia, ''), razao_social), cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch_visit_clients(query, params)

    def list_visit_day_seller_summaries(
        self,
        visit_day: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 100,
    ) -> list[VisitSellerSummary]:
        access_filter, access_params = self._build_access_filter(allowed_sectors, allowed_gv_vdes)
        seller_present_filter = sql.SQL("{} <> ''").format(_code_field_sql("filial_setor_key"))

        seller_filters = [seller_present_filter]
        visit_filters: list[sql.Composed] = [seller_present_filter]
        seller_params: list[Any] = []
        visit_params: list[Any] = []
        if access_filter is not None:
            seller_filters.append(access_filter)
            seller_params.extend(access_params)
            visit_filters.append(access_filter)
            visit_params.extend(access_params)
        _append_visit_day_filter(filters=visit_filters, params=visit_params, visit_day=visit_day)

        params = seller_params + visit_params + [max(1, min(limit, 1000))]
        query = sql.SQL(
            """
            WITH sellers AS (
                SELECT DISTINCT
                    {setor_sql} AS seller_code,
                    {gv_sql} AS manager_code
                FROM {schema}.dclientes_latest
                WHERE {seller_where}
            ),
            visits AS (
                SELECT
                    {setor_sql} AS seller_code,
                    {gv_sql} AS manager_code,
                    COUNT(*)::int AS visit_count
                FROM {schema}.dclientes_latest
                WHERE {visit_where}
                GROUP BY seller_code, manager_code
            )
            SELECT
                sellers.seller_code,
                sellers.manager_code,
                COALESCE(visits.visit_count, 0)::int AS visit_count
            FROM sellers
            LEFT JOIN visits
                ON visits.seller_code = sellers.seller_code
               AND visits.manager_code = sellers.manager_code
            ORDER BY
                CASE WHEN sellers.manager_code = '' THEN 1 ELSE 0 END,
                sellers.manager_code,
                sellers.seller_code
            LIMIT %s
            """
        ).format(
            setor_sql=_code_field_sql("filial_setor_key"),
            gv_sql=_code_field_sql("filial_gv_key"),
            schema=sql.Identifier(self.schema),
            seller_where=sql.SQL(" AND ").join(seller_filters),
            visit_where=sql.SQL(" AND ").join(visit_filters),
        )
        return self._fetch_visit_summaries(query, params)

    def list_seller_base_summaries(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 100,
    ) -> list[VisitSellerSummary]:
        filters = [
            sql.SQL("{} <> ''").format(_code_field_sql("filial_setor_key")),
        ]
        params: list[Any] = []
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 200)))
        query = sql.SQL(
            """
            SELECT
                {setor_sql} AS seller_code,
                {gv_sql} AS manager_code,
                COUNT(DISTINCT (filial, cod_pdv))::int AS visit_count
            FROM {schema}.dclientes_latest
            WHERE {where}
            GROUP BY seller_code, manager_code
            ORDER BY manager_code, seller_code
            LIMIT %s
            """
        ).format(
            setor_sql=_code_field_sql("filial_setor_key"),
            gv_sql=_code_field_sql("filial_gv_key"),
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch_visit_summaries(query, params)

    def list_clients_by_visit_day_and_seller(
        self,
        visit_day: str,
        seller_code: str,
        manager_code: str = "",
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 200,
    ) -> list[DClienteRecord]:
        normalized_seller_code = normalize_stored_scope_value(seller_code)
        normalized_manager_code = normalize_stored_scope_value(manager_code)
        if not normalized_seller_code:
            raise ValueError("Setor do vendedor obrigatorio.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        _append_visit_day_filter(filters=filters, params=params, visit_day=visit_day)
        _append_scope_value_filter(
            filters=filters,
            params=params,
            value=normalized_seller_code,
            key_field="filial_setor_key",
        )
        if normalized_manager_code:
            _append_scope_value_filter(
                filters=filters,
                params=params,
                value=normalized_manager_code,
                key_field="filial_gv_key",
            )
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 200)))
        query = sql.SQL(
            """
            SELECT
                filial,
                cod_pdv,
                razao_social,
                nome_fantasia,
                batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            ORDER BY COALESCE(NULLIF(nome_fantasia, ''), razao_social), cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch_visit_clients(query, params)

    def get_scope_summary(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> DClientesScopeSummary:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._scope_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return cached_entry[1]

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        query = sql.SQL(
            """
            SELECT
                COUNT(DISTINCT (filial, cod_pdv))::int AS client_count,
                COUNT(DISTINCT NULLIF({seller_sql}, ''))::int AS seller_count,
                MAX(batch_imported_at) AS batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            """
        ).format(
            schema=sql.Identifier(self.schema),
            seller_sql=_code_field_sql("filial_setor_key"),
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()

        summary = DClientesScopeSummary(
            client_count=int(row["client_count"] or 0) if row else 0,
            seller_count=int(row["seller_count"] or 0) if row else 0,
            planilha_atualizada_em=_format_batch_timestamp(row.get("batch_imported_at") if row else None),
        )
        self._scope_summary_cache[cache_key] = (now + 60.0, summary)
        return summary

    def get_scope_summary_for_seller(
        self,
        seller_code: str,
        manager_code: str = "",
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> DClientesScopeSummary:
        normalized_seller_code = normalize_stored_scope_value(seller_code)
        normalized_manager_code = normalize_stored_scope_value(manager_code)
        if not normalized_seller_code:
            raise ValueError("Setor do vendedor obrigatorio.")

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        _append_scope_value_filter(
            filters=filters,
            params=params,
            value=normalized_seller_code,
            key_field="filial_setor_key",
        )
        if normalized_manager_code:
            _append_scope_value_filter(
                filters=filters,
                params=params,
                value=normalized_manager_code,
                key_field="filial_gv_key",
            )
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        query = sql.SQL(
            """
            SELECT
                COUNT(DISTINCT (filial, cod_pdv))::int AS client_count,
                COUNT(DISTINCT NULLIF({seller_sql}, ''))::int AS seller_count,
                MAX(batch_imported_at) AS batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            """
        ).format(
            schema=sql.Identifier(self.schema),
            seller_sql=_code_field_sql("filial_setor_key"),
            where=sql.SQL(" AND ").join(filters),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()

        return DClientesScopeSummary(
            client_count=int(row["client_count"] or 0) if row else 0,
            seller_count=int(row["seller_count"] or 0) if row else 0,
            planilha_atualizada_em=_format_batch_timestamp(row.get("batch_imported_at") if row else None),
        )

    def list_scope_summary_by_gv(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[DClientesManagementSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._management_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        filters = [
            sql.SQL("{} <> ''").format(_code_field_sql("filial_gv_key")),
        ]
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        query = sql.SQL(
            """
            SELECT
                {manager_sql} AS manager_code,
                COUNT(DISTINCT (filial, cod_pdv))::int AS client_count,
                COUNT(DISTINCT NULLIF({seller_sql}, ''))::int AS seller_count,
                MAX(batch_imported_at) AS batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            GROUP BY manager_code
            ORDER BY manager_code
            """
        ).format(
            schema=sql.Identifier(self.schema),
            manager_sql=_code_field_sql("filial_gv_key"),
            seller_sql=_code_field_sql("filial_setor_key"),
            where=sql.SQL(" AND ").join(filters),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        summaries = [
            DClientesManagementSummary(
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")),
                client_count=int(row["client_count"] or 0),
                seller_count=int(row["seller_count"] or 0),
                planilha_atualizada_em=_format_batch_timestamp(row.get("batch_imported_at")),
            )
            for row in rows
            if normalize_stored_scope_value(str(row["manager_code"] or ""))
        ]
        self._management_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def list_scope_summary_by_filial(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[DClientesFilialSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._filial_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        query = sql.SQL(
            """
            SELECT
                filial,
                COUNT(DISTINCT (filial, cod_pdv))::int AS client_count,
                COUNT(DISTINCT NULLIF({seller_sql}, ''))::int AS seller_count,
                COUNT(DISTINCT NULLIF({manager_sql}, ''))::int AS manager_count,
                MAX(batch_imported_at) AS batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            GROUP BY filial
            ORDER BY filial
            """
        ).format(
            schema=sql.Identifier(self.schema),
            seller_sql=_code_field_sql("filial_setor_key"),
            manager_sql=_code_field_sql("filial_gv_key"),
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        summaries = [
            DClientesFilialSummary(
                filial=normalize_stored_scope_value(str(row["filial"] or "")),
                client_count=int(row["client_count"] or 0),
                seller_count=int(row["seller_count"] or 0),
                manager_count=int(row["manager_count"] or 0),
                planilha_atualizada_em=_format_batch_timestamp(row.get("batch_imported_at")),
            )
            for row in rows
            if normalize_stored_scope_value(str(row["filial"] or ""))
        ]
        self._filial_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def list_gv_vdes(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50,
    ) -> list[str]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._gv_options_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])[: max(1, min(limit, 100))]

        filters = [
            sql.SQL("BTRIM(COALESCE({}, '')) <> ''").format(_code_field_sql("filial_gv_key")),
        ]
        params: list[Any] = []
        access_filter, access_params = self._build_access_filter(normalized_sectors, normalized_gv_vdes)
        if access_filter is not None:
            filters.append(access_filter)
            params.extend(access_params)
        params.append(max(1, min(limit, 100)))
        query = sql.SQL(
            """
            SELECT DISTINCT {gv_sql} AS gv_vde
            FROM {schema}.dclientes_latest
            WHERE {where}
            ORDER BY gv_vde
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            gv_sql=_code_field_sql("filial_gv_key"),
            where=sql.SQL(" AND ").join(filters),
        )

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        gv_vdes = [
            normalize_stored_scope_value(str(row["gv_vde"] or ""))
            for row in rows
            if normalize_stored_scope_value(str(row["gv_vde"] or ""))
        ]
        self._gv_options_cache[cache_key] = (now + 120.0, list(gv_vdes))
        return gv_vdes

    def expand_gv_scope_codes(self, gv_codes: list[str] | tuple[str, ...]) -> list[str]:
        normalized_codes = _normalize_numeric_codes(gv_codes)
        if not normalized_codes:
            return []
        cache_key = tuple(normalized_codes)
        now = monotonic()
        cached_entry = self._gv_scope_expand_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        query = sql.SQL(
            """
            SELECT DISTINCT {scope_sql} AS scope_key
            FROM {schema}.dclientes_latest
            WHERE BTRIM(COALESCE({code_sql}, '')) <> ''
              AND {code_sql} = ANY(%s)
              AND BTRIM(COALESCE({scope_sql}, '')) <> ''
            ORDER BY scope_key
            """
        ).format(
            schema=sql.Identifier(self.schema),
            code_sql=_code_field_sql("gv_vde_resolved"),
            scope_sql=_code_field_sql("filial_gv_key"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (normalized_codes,))
                rows = cur.fetchall()

        expanded = [
            normalize_stored_scope_value(str(row["scope_key"] or ""))
            for row in rows
            if normalize_stored_scope_value(str(row["scope_key"] or ""))
        ]
        self._gv_scope_expand_cache[cache_key] = (now + 120.0, list(expanded))
        return expanded

    def expand_dc_scope_codes(self, dc_codes: list[str] | tuple[str, ...]) -> list[str]:
        normalized_codes = _normalize_numeric_codes(dc_codes)
        if not normalized_codes:
            return []
        cache_key = tuple(normalized_codes)
        now = monotonic()
        cached_entry = self._dc_scope_expand_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        query = sql.SQL(
            """
            SELECT DISTINCT {scope_sql} AS scope_key
            FROM {schema}.dclientes_latest
            WHERE BTRIM(COALESCE({code_sql}, '')) <> ''
              AND {code_sql} = ANY(%s)
              AND BTRIM(COALESCE({scope_sql}, '')) <> ''
            ORDER BY scope_key
            """
        ).format(
            schema=sql.Identifier(self.schema),
            code_sql=_code_field_sql("dc_vde"),
            scope_sql=_code_field_sql("filial_dc_key"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (normalized_codes,))
                rows = cur.fetchall()

        expanded = []
        for row in rows:
            normalized_scope = normalize_stored_scope_value(str(row["scope_key"] or ""))
            if normalized_scope:
                expanded.append(f"dc:{normalized_scope}")
        self._dc_scope_expand_cache[cache_key] = (now + 120.0, list(expanded))
        return expanded

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

    def _build_snapshot_access_filter(
        self,
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
    ) -> tuple[sql.Composed | None, list[Any]]:
        return self._build_access_filter(allowed_sectors, allowed_gv_vdes)

    def _base_rows_query(self, where: sql.SQL) -> sql.SQL:
        return sql.SQL(
            """
            SELECT
                filial,
                cod_pdv,
                razao_social,
                nome_fantasia,
                status_pdv,
                setor_vde,
                payload,
                payload ->> 'Cidade' AS cidade_payload,
                batch_imported_at
            FROM {schema}.dclientes_latest
            WHERE {where}
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=where,
        )

    def _details_query_from_base(self, base_query: sql.SQL, order_by: sql.SQL) -> sql.SQL:
        return sql.SQL(
            """
            WITH base AS (
                {base_query}
            )
            SELECT
                base.filial AS filial,
                base.cod_pdv AS cod_pdv,
                base.razao_social,
                base.nome_fantasia,
                COALESCE(base.payload ->> 'Telefone(s)', '') AS telefone,
                COALESCE(base.payload ->> 'Dia de Visita do VDE', '') AS dia_visita,
                base.setor_vde AS vendedor,
                COALESCE(base.status_pdv, '') AS status,
                COALESCE(base.payload ->> 'Cidade', base.cidade_payload, '') AS cidade,
                COALESCE(base.payload ->> 'Cond Pag Atual', '') AS cond_pag_atual,
                COALESCE(base.payload ->> 'Limite de Cr\u00e9dito', '') AS limite_credito,
                COALESCE(inad.total_pendente, 0) AS total_pendente,
                COALESCE(comod.total_comodatos_pendentes, 0)::int AS total_comodatos_pendentes,
                base.batch_imported_at
            FROM base
            LEFT JOIN LATERAL (
                SELECT SUM({valor_pendente_sql}) AS total_pendente
                FROM {schema}.inadimplencia_latest inad
                WHERE inad.unb = base.filial
                  AND inad.cliente = base.cod_pdv
            ) inad ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(DISTINCT nro_comodato)::int AS total_comodatos_pendentes
                FROM {schema}.comodatos_latest comod
                WHERE comod.unb = base.filial
                  AND comod.cliente = base.cod_pdv
            ) comod ON TRUE
            ORDER BY {order_by}
            """
        ).format(
            base_query=base_query,
            valor_pendente_sql=_money_to_numeric_sql("valor_pendente"),
            schema=sql.Identifier(self.schema),
            order_by=order_by,
        )

    def _fetch(self, query: sql.SQL, params: list[Any]) -> list[DClienteRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [
            DClienteRecord(
                filial=_normalize_filial(str(row["filial"] or "")),
                cod_pdv=_normalize_cod_pdv(str(row["cod_pdv"] or "")),
                razao_social=str(row["razao_social"] or ""),
                nome_fantasia=str(row["nome_fantasia"] or ""),
                telefone=str(row["telefone"] or ""),
                dia_visita=str(row["dia_visita"] or ""),
                vendedor=_normalize_sector_value(str(row["vendedor"] or "")),
                status=str(row["status"] or ""),
                cidade=str(row["cidade"] or ""),
                cond_pag_atual=str(row.get("cond_pag_atual") or ""),
                limite_credito=_format_optional_money(row.get("limite_credito")),
                total_pendente=_format_money(row.get("total_pendente")),
                total_comodatos_pendentes=int(row.get("total_comodatos_pendentes") or 0),
                ultima_atualizacao_tabela=_format_batch_timestamp(row.get("batch_imported_at")),
            )
            for row in rows
        ]

    def _fetch_visit_days(self, query: sql.SQL, params: list[Any]) -> list[str]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        visit_days: list[str] = []
        seen: set[str] = set()
        for row in rows:
            visit_day = _normalize_visit_day(str(row["dia_visita"] or ""))
            key = visit_day.casefold()
            if not visit_day or key in seen:
                continue
            seen.add(key)
            visit_days.append(visit_day)
        return visit_days

    def _fetch_visit_summaries(self, query: sql.SQL, params: list[Any]) -> list[VisitSellerSummary]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            VisitSellerSummary(
                seller_code=normalize_stored_scope_value(str(row["seller_code"] or "")) or "-",
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")) or "-",
                visit_count=int(row["visit_count"] or 0),
            )
            for row in rows
        ]

    def _fetch_visit_clients(self, query: sql.SQL, params: list[Any]) -> list[DClienteRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            DClienteRecord(
                filial=_normalize_filial(str(row["filial"] or "")),
                cod_pdv=_normalize_cod_pdv(str(row["cod_pdv"] or "")),
                razao_social=str(row["razao_social"] or ""),
                nome_fantasia=str(row["nome_fantasia"] or ""),
                telefone="",
                dia_visita="",
                vendedor="",
                status="",
                cidade="",
                cond_pag_atual="",
                limite_credito="",
                total_pendente="0,00",
                total_comodatos_pendentes=0,
                ultima_atualizacao_tabela=_format_batch_timestamp(row.get("batch_imported_at")),
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

    def _cache_status(self, payload: dict[str, Any]) -> None:
        self._status_cache = dict(payload)
        self._status_cache_expires_at = monotonic() + (300.0 if payload.get("ready") else 10.0)

    def _get_latest_dclientes_batch_id(self) -> int | None:
        now = monotonic()
        if self._latest_batch_id_cache is not None and now < self._latest_batch_id_cache_expires_at:
            return self._latest_batch_id_cache

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base dClientes indisponivel.")

        query = sql.SQL(
            """
            SELECT id
            FROM {schema}.import_batches
            WHERE dataset_name = 'dclientes'
            ORDER BY imported_at DESC, id DESC
            LIMIT 1
            """
        ).format(schema=sql.Identifier(self.schema))

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()

        latest_batch_id = int(row["id"]) if row and row.get("id") is not None else None
        self._latest_batch_id_cache = latest_batch_id
        self._latest_batch_id_cache_expires_at = now + 30.0
        return latest_batch_id


def _normalize_filial(value: str) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _normalize_cod_pdv(value: str) -> str:
    cleaned = "".join(char for char in str(value or "") if char.isdigit())
    if cleaned:
        return cleaned.lstrip("0") or "0"
    return str(value or "").strip()


def _normalize_scope_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = normalize_stored_scope_value(str(value or ""))
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _normalize_sector_value(value: str) -> str:
    return normalize_stored_scope_value(value)


def _normalize_visit_day(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_visit_day_token(value: str) -> str:
    normalized = _normalize_visit_day(value).upper()
    if not normalized:
        return ""
    visit_day_map = {
        "SEGUNDA": "SEG/",
        "SEG/": "SEG/",
        "TERCA": "TER/",
        "TER/": "TER/",
        "QUARTA": "QUA/",
        "QUA/": "QUA/",
        "QUINTA": "QUI/",
        "QUI/": "QUI/",
        "SEXTA": "SEX/",
        "SEX/": "SEX/",
        "SABADO": "SAB/",
        "SAB/": "SAB/",
        "DOMINGO": "DOM/",
        "DOM/": "DOM/",
    }
    return visit_day_map.get(normalized, normalized)


def _normalize_visit_day_label(value: str) -> str:
    token = _normalize_visit_day_token(value)
    if not token:
        return ""
    visit_day_map = {
        "SEG/": "SEGUNDA",
        "TER/": "TERCA",
        "QUA/": "QUARTA",
        "QUI/": "QUINTA",
        "SEX/": "SEXTA",
        "SAB/": "SABADO",
        "DOM/": "DOMINGO",
    }
    return visit_day_map.get(token, _normalize_visit_day(value).upper())


def _append_visit_day_filter(
    *,
    filters: list[sql.Composed],
    params: list[Any],
    visit_day: str,
) -> None:
    normalized_visit_day = _normalize_visit_day(visit_day)
    normalized_visit_day_token = _normalize_visit_day_token(visit_day)
    normalized_visit_day_label = _normalize_visit_day_label(visit_day)
    if not normalized_visit_day or not normalized_visit_day_token:
        raise ValueError("Dia de visita obrigatorio.")

    visit_day_sql = sql.SQL("UPPER(BTRIM(COALESCE(payload ->> 'Dia de Visita do VDE', '')))")
    filters.append(
        sql.SQL(
            "("
            "POSITION(%s IN {visit_day_sql}) > 0 "
            "OR {visit_day_sql} = %s "
            "OR {visit_day_sql} = %s"
            ")"
        ).format(visit_day_sql=visit_day_sql)
    )
    params.extend([normalized_visit_day_token, normalized_visit_day.upper(), normalized_visit_day_label])


def _normalize_document(value: str) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if len(digits) not in {11, 14}:
        return ""
    return digits


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
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("filial")))
        params.append(filial_codes)
    if sector_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("filial_setor_key")))
        params.append(sector_keys)
    if gv_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("filial_gv_key")))
        params.append(gv_keys)
    dc_scope_keys = [value[len("dc:") :] for value in dc_keys]
    if dc_scope_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(_code_field_sql("filial_dc_key")))
        params.append(dc_scope_keys)

    return scope_filters, params


def _has_scope_values(values: list[str] | None) -> bool:
    return any(str(value or "").strip() for value in values or [])


def _normalize_numeric_codes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = normalize_numeric_code(str(value or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


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


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _format_batch_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _format_money(value: Any) -> str:
    if value is None:
        return "0,00"
    if isinstance(value, Decimal):
        return f"{value:.2f}".replace(".", ",")
    if isinstance(value, (int, float)):
        return f"{value:.2f}".replace(".", ",")
    raw = str(value).strip()
    if not raw:
        return "0,00"
    if "," in raw:
        cleaned = raw.replace(".", "").replace(",", ".").replace("+", "")
    else:
        cleaned = raw.replace("+", "")
    try:
        numeric = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return raw
    return f"{numeric:.2f}".replace(".", ",")


def _format_optional_money(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    return _format_money(value)
