from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row, tuple_row

from bot_api.commercial_scope import (
    normalize_stored_scope_value,
    partition_filial_scopes,
    partition_gv_scopes,
    partition_sector_scopes,
)
from bot_api.db import get_connection_pool


@dataclass(frozen=True)
class GiroScopeSummary:
    client_count: int
    attention_count: int
    zero_count: int
    litrinho_monitored_count: int
    litrinho_ok_count: int
    litrinho_nok_count: int
    litrinho_zero_count: int
    litrinho_gap_total: str
    inteira_monitored_count: int
    inteira_ok_count: int
    inteira_nok_count: int
    inteira_zero_count: int
    inteira_gap_total: str
    litrao_monitored_count: int
    litrao_ok_count: int
    litrao_nok_count: int
    litrao_zero_count: int
    litrao_gap_total: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GiroManagementSummary(GiroScopeSummary):
    manager_code: str


@dataclass(frozen=True)
class GiroFilialSummary(GiroScopeSummary):
    filial: str


@dataclass(frozen=True)
class GiroSellerSummary(GiroScopeSummary):
    seller_code: str
    manager_code: str


@dataclass(frozen=True)
class GiroVisitDaySummary(GiroScopeSummary):
    visit_day: str


@dataclass(frozen=True)
class GiroClientRecord:
    filial: str
    cod_pdv: str
    nome: str
    setor: str
    revenda: str
    total_litrinho: str
    real_litrinho: str
    gap_litrinho: str
    giro_litrinho: str
    total_inteira: str
    real_inteira: str
    gap_inteira: str
    giro_inteira: str
    total_litrao: str
    real_litrao: str
    gap_litrao: str
    giro_litrao: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GiroZeroBaseRecord:
    filial: str
    cod_pdv: str
    nome: str
    setor: str
    revenda: str
    total_caixas: str
    gap_caixas: str
    gap_litrinho: str
    gap_inteira: str
    gap_litrao: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GiroQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_expires_at = 0.0
        self._scope_summary_cache: dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[float, GiroScopeSummary]] = {}
        self._management_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[GiroManagementSummary]],
        ] = {}
        self._seller_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[GiroSellerSummary]],
        ] = {}
        self._filial_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[GiroFilialSummary]],
        ] = {}
        self._visit_day_summary_cache: dict[
            tuple[str, tuple[str, ...], tuple[str, ...]],
            tuple[float, GiroVisitDaySummary],
        ] = {}

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
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.views
                            WHERE table_schema = %s
                              AND table_name = 'giro_latest'
                        ) AS has_giro
                        """,
                        (self.schema,),
                    )
                    row = cur.fetchone()
            ready = bool(row and row["has_giro"])
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": ready,
                "last_error": "" if ready else "View reports.giro_latest nao encontrada.",
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

    def get_scope_summary(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> GiroScopeSummary:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._scope_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return cached_entry[1]

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        row = self._execute_summary_query(group_by=None, filters=filters, params=params)
        summary = _row_to_scope_summary(row)
        self._scope_summary_cache[cache_key] = (now + 60.0, summary)
        return summary

    def get_scope_summary_for_seller(
        self,
        seller_code: str,
        manager_code: str = "",
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> GiroScopeSummary:
        normalized_seller_code = normalize_stored_scope_value(seller_code)
        normalized_manager_code = normalize_stored_scope_value(manager_code)
        if not normalized_seller_code:
            raise ValueError("Setor do vendedor obrigatorio.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        _append_scope_value_filter(filters=filters, params=params, value=normalized_seller_code, key_field="filial_setor_key")
        if normalized_manager_code:
            _append_scope_value_filter(filters=filters, params=params, value=normalized_manager_code, key_field="filial_gv_key")
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        row = self._execute_summary_query(group_by=None, filters=filters, params=params)
        return _row_to_scope_summary(row)

    def list_summary_by_gv(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[GiroManagementSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._management_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        filters = [sql.SQL("BTRIM(COALESCE(filial_gv_key, '')) <> ''")]
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        rows = self._execute_summary_query(
            group_by=sql.Identifier("filial_gv_key"),
            select_alias="manager_code",
            filters=filters,
            params=params,
        )
        summaries = [
            GiroManagementSummary(
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")),
                **_scope_summary_kwargs(row),
            )
            for row in rows
            if normalize_stored_scope_value(str(row["manager_code"] or ""))
        ]
        self._management_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def list_summary_by_filial(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[GiroFilialSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._filial_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        rows = self._execute_summary_query(
            group_by=sql.Identifier("filial"),
            select_alias="filial",
            filters=filters,
            params=params,
        )
        summaries = [
            GiroFilialSummary(
                filial=normalize_stored_scope_value(str(row["filial"] or "")),
                **_scope_summary_kwargs(row),
            )
            for row in rows
            if normalize_stored_scope_value(str(row["filial"] or ""))
        ]
        self._filial_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def list_summary_by_seller(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[GiroSellerSummary]:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._seller_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return list(cached_entry[1])

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de giro indisponivel.")

        filters = [sql.SQL("BTRIM(COALESCE(filial_setor_key, '')) <> ''")]
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        query = sql.SQL(
            """
            SELECT
                filial_setor_key AS seller_code,
                filial_gv_key AS manager_code,
                {summary_select},
                COALESCE(MAX(reference_date)::text, '') AS reference_date,
                MAX(batch_imported_at) AS batch_imported_at
            FROM {schema}.giro_latest g
            WHERE {where}
            GROUP BY filial_setor_key, filial_gv_key
            ORDER BY filial_gv_key, filial_setor_key
            """
        ).format(
            summary_select=_summary_select_sql("g"),
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        summaries = [
            GiroSellerSummary(
                seller_code=normalize_stored_scope_value(str(row["seller_code"] or "")),
                manager_code=normalize_stored_scope_value(str(row["manager_code"] or "")),
                **_scope_summary_kwargs(row),
            )
            for row in rows
            if normalize_stored_scope_value(str(row["seller_code"] or ""))
        ]
        self._seller_summary_cache[cache_key] = (now + 60.0, summaries)
        return list(summaries)

    def get_scope_summary_by_visit_day(
        self,
        visit_day: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> GiroVisitDaySummary:
        normalized_visit_day = _normalize_visit_day(visit_day)
        normalized_visit_day_token = _normalize_visit_day_token(visit_day)
        if not normalized_visit_day or not normalized_visit_day_token:
            raise ValueError("Dia de visita obrigatorio.")

        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (normalized_visit_day, tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._visit_day_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return cached_entry[1]

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de giro indisponivel.")

        visit_filters = [
            sql.SQL(
                "("
                "POSITION(%s IN UPPER(BTRIM(COALESCE(payload ->> 'Dia de Visita do VDE', '')))) > 0 "
                "OR UPPER(BTRIM(COALESCE(payload ->> 'Dia de Visita do VDE', ''))) = %s"
                ")"
            ),
        ]
        visit_params: list[Any] = [normalized_visit_day_token, normalized_visit_day.upper()]
        self._apply_access_filter(visit_filters, visit_params, normalized_sectors, normalized_gv_vdes)

        query = sql.SQL(
            """
            WITH visit_base AS (
                SELECT DISTINCT
                    filial,
                    cod_pdv
                FROM {schema}.dclientes_latest
                WHERE {visit_where}
            )
            SELECT
                {summary_select},
                COALESCE(MAX(g.reference_date)::text, '') AS reference_date,
                MAX(g.batch_imported_at) AS batch_imported_at
            FROM {schema}.giro_latest g
            INNER JOIN visit_base base
                ON base.filial = g.filial
               AND base.cod_pdv = g.nb
            """
        ).format(
            schema=sql.Identifier(self.schema),
            visit_where=sql.SQL(" AND ").join(visit_filters),
            summary_select=_summary_select_sql("g"),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, visit_params)
                row = cur.fetchone()
        summary = GiroVisitDaySummary(
            visit_day=normalized_visit_day,
            **_scope_summary_kwargs(row or {}),
        )
        self._visit_day_summary_cache[cache_key] = (now + 60.0, summary)
        return summary

    def search_by_registration(
        self,
        filial: str,
        cod_pdv: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50,
    ) -> list[GiroClientRecord]:
        normalized_filial = normalize_stored_scope_value(filial)
        normalized_cod_pdv = normalize_stored_scope_value(cod_pdv)
        if normalized_filial.isdigit():
            normalized_filial = str(int(normalized_filial))
        if normalized_cod_pdv.isdigit():
            normalized_cod_pdv = str(int(normalized_cod_pdv))
        if not normalized_filial:
            raise ValueError("Revenda/filial invalida.")
        if not normalized_cod_pdv:
            raise ValueError("NB invalido.")

        filters = [
            sql.SQL("{} = %s").format(sql.Identifier("filial")),
            sql.SQL("{} = %s").format(sql.Identifier("nb")),
        ]
        params: list[Any] = [normalized_filial, normalized_cod_pdv]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 100)))
        query = sql.SQL(
            """
            SELECT
                filial,
                nb,
                fantasia,
                setor,
                revenda,
                total_litrinho,
                real_litrinho,
                gap_litrinho,
                giro_litrinho,
                total_inteira,
                real_inteira,
                gap_inteira,
                giro_inteira,
                total_litrao,
                real_litrao,
                gap_litrao,
                giro_litrao,
                reference_date,
                batch_imported_at
            FROM {schema}.giro_latest
            WHERE {where}
            ORDER BY filial, nb
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch_client_rows(query, params)

    def search_history_by_registration(
        self,
        filial: str,
        cod_pdv: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 5,
    ) -> list[GiroClientRecord]:
        normalized_filial = normalize_stored_scope_value(filial)
        normalized_cod_pdv = normalize_stored_scope_value(cod_pdv)
        if normalized_filial.isdigit():
            normalized_filial = str(int(normalized_filial))
        if normalized_cod_pdv.isdigit():
            normalized_cod_pdv = str(int(normalized_cod_pdv))
        if not normalized_filial:
            raise ValueError("Revenda/filial invalida.")
        if not normalized_cod_pdv:
            raise ValueError("NB invalido.")

        filters = [
            sql.SQL("{} = %s").format(sql.Identifier("filial")),
            sql.SQL("{} = %s").format(sql.Identifier("nb")),
        ]
        params: list[Any] = [normalized_filial, normalized_cod_pdv]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 20)))
        query = sql.SQL(
            """
            SELECT
                g.filial,
                g.nb,
                g.fantasia,
                g.setor,
                g.revenda,
                g.total_litrinho,
                g.real_litrinho,
                g.gap_litrinho,
                g.giro_litrinho,
                g.total_inteira,
                g.real_inteira,
                g.gap_inteira,
                g.giro_inteira,
                g.total_litrao,
                g.real_litrao,
                g.gap_litrao,
                g.giro_litrao,
                b.reference_date,
                b.imported_at AS batch_imported_at
            FROM {schema}.giro_snapshot g
            JOIN {schema}.import_batches b ON b.id = g.batch_id
            WHERE {where}
            ORDER BY b.reference_date DESC NULLS LAST, b.imported_at DESC, g.batch_id DESC
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch_client_rows(query, params)

    def list_giro_zero_base(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 500,
    ) -> list[GiroZeroBaseRecord]:
        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, _normalize_scope_values(allowed_sectors), _normalize_scope_values(allowed_gv_vdes))
        filters.append(
            sql.SQL(
                "("
                "(COALESCE(total_litrinho, 0) + COALESCE(total_inteira, 0) + COALESCE(total_litrao, 0)) > 0 "
                "AND ABS("
                "(COALESCE(gap_litrinho, 0) + COALESCE(gap_inteira, 0) + COALESCE(gap_litrao, 0)) "
                "- ((COALESCE(total_litrinho, 0) + COALESCE(total_inteira, 0) + COALESCE(total_litrao, 0)) * 2)"
                ") < 0.0001"
                ")"
            )
        )
        params.append(max(1, min(limit, 5000)))
        query = sql.SQL(
            """
            SELECT
                filial,
                nb,
                fantasia,
                setor,
                revenda,
                gap_litrinho,
                gap_inteira,
                gap_litrao,
                (COALESCE(total_litrinho, 0) + COALESCE(total_inteira, 0) + COALESCE(total_litrao, 0)) AS total_caixas,
                (COALESCE(gap_litrinho, 0) + COALESCE(gap_inteira, 0) + COALESCE(gap_litrao, 0)) AS gap_caixas,
                reference_date,
                batch_imported_at
            FROM {schema}.giro_latest
            WHERE {where}
            ORDER BY filial, setor, nb
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de giro indisponivel.")
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [_row_to_giro_zero_base_record(row) for row in rows]

    def _execute_summary_query(
        self,
        *,
        group_by: sql.SQL | None,
        select_alias: str | None = None,
        filters: list[sql.Composed],
        params: list[Any],
    ) -> Any:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de giro indisponivel.")

        if group_by is None:
            query = sql.SQL(
                """
                SELECT
                    {summary_select},
                    COALESCE(MAX(reference_date)::text, '') AS reference_date,
                    MAX(batch_imported_at) AS batch_imported_at
                FROM {schema}.giro_latest g
                WHERE {where}
                """
            ).format(
                summary_select=_summary_select_sql("g"),
                schema=sql.Identifier(self.schema),
                where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
            )
            with self._connect(row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return cur.fetchone()

        query = sql.SQL(
            """
            SELECT
                {group_by} AS {select_alias},
                {summary_select},
                COALESCE(MAX(reference_date)::text, '') AS reference_date,
                MAX(batch_imported_at) AS batch_imported_at
            FROM {schema}.giro_latest g
            WHERE {where}
            GROUP BY {group_by}
            ORDER BY {group_by}
            """
        ).format(
            group_by=group_by,
            select_alias=sql.Identifier(str(select_alias or "scope_value")),
            summary_select=_summary_select_sql("g"),
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()

    def _apply_access_filter(
        self,
        filters: list[sql.Composed],
        params: list[Any],
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
    ) -> None:
        access_filter, access_params = _build_access_filter(allowed_sectors, allowed_gv_vdes)
        if access_filter is None:
            return
        filters.append(access_filter)
        params.extend(access_params)

    @contextmanager
    def _connect(self, row_factory: Any | None = None) -> Any:
        if self._pool is None:
            self._pool = get_connection_pool(self.database_url, connect_timeout_seconds=self.connect_timeout_seconds)
        with self._pool.connection() as conn:
            conn.row_factory = row_factory or tuple_row
            yield conn

    def _cache_status(self, payload: dict[str, Any]) -> None:
        self._status_cache = dict(payload)
        self._status_cache_expires_at = monotonic() + (300.0 if payload.get("ready") else 10.0)

    def _fetch_client_rows(self, query: sql.SQL, params: list[Any]) -> list[GiroClientRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de giro indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [_row_to_client_record(row) for row in rows]


def _summary_select_sql(table_alias: str = "") -> sql.SQL:
    qualifier = f"{table_alias}." if table_alias else ""
    return sql.SQL(
        """
        COUNT(DISTINCT ({qualifier}filial, {qualifier}nb))::int AS client_count,
        COUNT(DISTINCT ({qualifier}filial, {qualifier}nb)) FILTER (
            WHERE {qualifier}giro_litrinho IN ('NOK', 'ZERO')
               OR {qualifier}giro_inteira IN ('NOK', 'ZERO')
               OR {qualifier}giro_litrao IN ('NOK', 'ZERO')
        )::int AS attention_count,
        COUNT(DISTINCT ({qualifier}filial, {qualifier}nb)) FILTER (
            WHERE {qualifier}giro_litrinho = 'ZERO'
               OR {qualifier}giro_inteira = 'ZERO'
               OR {qualifier}giro_litrao = 'ZERO'
        )::int AS zero_count,
        COALESCE(SUM({qualifier}total_litrinho) FILTER (WHERE {qualifier}giro_litrinho <> '-'), 0)::int AS litrinho_monitored_count,
        COALESCE(SUM({qualifier}total_litrinho) FILTER (WHERE {qualifier}giro_litrinho = 'OK'), 0)::int AS litrinho_ok_count,
        COALESCE(SUM({qualifier}total_litrinho) FILTER (WHERE {qualifier}giro_litrinho = 'NOK'), 0)::int AS litrinho_nok_count,
        COALESCE(SUM({qualifier}total_litrinho) FILTER (WHERE {qualifier}giro_litrinho = 'ZERO'), 0)::int AS litrinho_zero_count,
        (
            COALESCE(SUM({qualifier}total_litrinho) FILTER (WHERE {qualifier}giro_litrinho <> '-'), 0)
            - COALESCE(SUM({qualifier}total_litrinho) FILTER (WHERE {qualifier}giro_litrinho = 'OK'), 0)
        ) AS litrinho_gap_total,
        COALESCE(SUM({qualifier}total_inteira) FILTER (WHERE {qualifier}giro_inteira <> '-'), 0)::int AS inteira_monitored_count,
        COALESCE(SUM({qualifier}total_inteira) FILTER (WHERE {qualifier}giro_inteira = 'OK'), 0)::int AS inteira_ok_count,
        COALESCE(SUM({qualifier}total_inteira) FILTER (WHERE {qualifier}giro_inteira = 'NOK'), 0)::int AS inteira_nok_count,
        COALESCE(SUM({qualifier}total_inteira) FILTER (WHERE {qualifier}giro_inteira = 'ZERO'), 0)::int AS inteira_zero_count,
        (
            COALESCE(SUM({qualifier}total_inteira) FILTER (WHERE {qualifier}giro_inteira <> '-'), 0)
            - COALESCE(SUM({qualifier}total_inteira) FILTER (WHERE {qualifier}giro_inteira = 'OK'), 0)
        ) AS inteira_gap_total,
        COALESCE(SUM({qualifier}total_litrao) FILTER (WHERE {qualifier}giro_litrao <> '-'), 0)::int AS litrao_monitored_count,
        COALESCE(SUM({qualifier}total_litrao) FILTER (WHERE {qualifier}giro_litrao = 'OK'), 0)::int AS litrao_ok_count,
        COALESCE(SUM({qualifier}total_litrao) FILTER (WHERE {qualifier}giro_litrao = 'NOK'), 0)::int AS litrao_nok_count,
        COALESCE(SUM({qualifier}total_litrao) FILTER (WHERE {qualifier}giro_litrao = 'ZERO'), 0)::int AS litrao_zero_count,
        (
            COALESCE(SUM({qualifier}total_litrao) FILTER (WHERE {qualifier}giro_litrao <> '-'), 0)
            - COALESCE(SUM({qualifier}total_litrao) FILTER (WHERE {qualifier}giro_litrao = 'OK'), 0)
        ) AS litrao_gap_total
        """
    ).format(qualifier=sql.SQL(qualifier))


def _build_access_filter(
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
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier("filial")))
        params.append(filial_codes)
    if sector_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier("filial_setor_key")))
        params.append(sector_keys)
    if gv_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier("filial_gv_key")))
        params.append(gv_keys)
    dc_scope_keys = [value[len("dc:") :] for value in dc_keys]
    if dc_scope_keys:
        scope_filters.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier("filial_dc_key")))
        params.append(dc_scope_keys)

    return scope_filters, params


def _append_scope_value_filter(
    *,
    filters: list[sql.Composed],
    params: list[Any],
    value: str,
    key_field: str,
) -> None:
    normalized_value = normalize_stored_scope_value(value)
    if not normalized_value or normalized_value.startswith("dc:"):
        filters.append(sql.SQL("FALSE"))
        return
    filters.append(sql.SQL("{} = %s").format(sql.Identifier(key_field)))
    params.append(normalized_value)


def _row_to_scope_summary(row: dict[str, Any] | None) -> GiroScopeSummary:
    if row is None:
        return GiroScopeSummary(
            client_count=0,
            attention_count=0,
            zero_count=0,
            litrinho_monitored_count=0,
            litrinho_ok_count=0,
            litrinho_nok_count=0,
            litrinho_zero_count=0,
            litrinho_gap_total="0,00",
            inteira_monitored_count=0,
            inteira_ok_count=0,
            inteira_nok_count=0,
            inteira_zero_count=0,
            inteira_gap_total="0,00",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0,00",
            planilha_atualizada_em="-",
        )
    return GiroScopeSummary(**_scope_summary_kwargs(row))


def _scope_summary_kwargs(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "client_count": int(row.get("client_count") or 0),
        "attention_count": int(row.get("attention_count") or 0),
        "zero_count": int(row.get("zero_count") or 0),
        "litrinho_monitored_count": int(row.get("litrinho_monitored_count") or 0),
        "litrinho_ok_count": int(row.get("litrinho_ok_count") or 0),
        "litrinho_nok_count": int(row.get("litrinho_nok_count") or 0),
        "litrinho_zero_count": int(row.get("litrinho_zero_count") or 0),
        "litrinho_gap_total": _format_money(row.get("litrinho_gap_total")),
        "inteira_monitored_count": int(row.get("inteira_monitored_count") or 0),
        "inteira_ok_count": int(row.get("inteira_ok_count") or 0),
        "inteira_nok_count": int(row.get("inteira_nok_count") or 0),
        "inteira_zero_count": int(row.get("inteira_zero_count") or 0),
        "inteira_gap_total": _format_money(row.get("inteira_gap_total")),
        "litrao_monitored_count": int(row.get("litrao_monitored_count") or 0),
        "litrao_ok_count": int(row.get("litrao_ok_count") or 0),
        "litrao_nok_count": int(row.get("litrao_nok_count") or 0),
        "litrao_zero_count": int(row.get("litrao_zero_count") or 0),
        "litrao_gap_total": _format_money(row.get("litrao_gap_total")),
        "planilha_atualizada_em": _format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
    }


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


def _normalize_visit_day(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_visit_day_token(value: str) -> str:
    normalized = _normalize_visit_day(value).upper()
    if not normalized:
        return ""
    visit_day_map = {
        "SEG/": "SEG/",
        "SEGUNDA": "SEG/",
        "TER/": "TER/",
        "TERCA": "TER/",
        "QUA/": "QUA/",
        "QUARTA": "QUA/",
        "QUI/": "QUI/",
        "QUINTA": "QUI/",
        "SEX/": "SEX/",
        "SEXTA": "SEX/",
        "SAB/": "SAB/",
        "SABADO": "SAB/",
        "DOM/": "DOM/",
        "DOMINGO": "DOM/",
    }
    return visit_day_map.get(normalized, normalized)


def _has_scope_values(values: list[str] | None) -> bool:
    return any(str(value or "").strip() for value in values or [])


def _normalize_schema(schema: str) -> str:
    normalized = str(schema or "").strip()
    return normalized or "reports"


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


def _row_to_client_record(row: dict[str, Any]) -> GiroClientRecord:
    return GiroClientRecord(
        filial=normalize_stored_scope_value(str(row.get("filial") or "")),
        cod_pdv=normalize_stored_scope_value(str(row.get("nb") or "")),
        nome=str(row.get("fantasia") or "").strip(),
        setor=normalize_stored_scope_value(str(row.get("setor") or "")),
        revenda=str(row.get("revenda") or "").strip(),
        total_litrinho=_format_money(row.get("total_litrinho")),
        real_litrinho=_format_money(row.get("real_litrinho")),
        gap_litrinho=_format_money(row.get("gap_litrinho")),
        giro_litrinho=str(row.get("giro_litrinho") or "-").strip() or "-",
        total_inteira=_format_money(row.get("total_inteira")),
        real_inteira=_format_money(row.get("real_inteira")),
        gap_inteira=_format_money(row.get("gap_inteira")),
        giro_inteira=str(row.get("giro_inteira") or "-").strip() or "-",
        total_litrao=_format_money(row.get("total_litrao")),
        real_litrao=_format_money(row.get("real_litrao")),
        gap_litrao=_format_money(row.get("gap_litrao")),
        giro_litrao=str(row.get("giro_litrao") or "-").strip() or "-",
        planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
    )


def _row_to_giro_zero_base_record(row: dict[str, Any]) -> GiroZeroBaseRecord:
    return GiroZeroBaseRecord(
        filial=normalize_stored_scope_value(str(row.get("filial") or "")),
        cod_pdv=normalize_stored_scope_value(str(row.get("nb") or "")),
        nome=str(row.get("fantasia") or "").strip(),
        setor=normalize_stored_scope_value(str(row.get("setor") or "")),
        revenda=str(row.get("revenda") or "").strip(),
        total_caixas=_format_money(row.get("total_caixas")),
        gap_caixas=_format_money(row.get("gap_caixas")),
        gap_litrinho=_format_money(row.get("gap_litrinho")),
        gap_inteira=_format_money(row.get("gap_inteira")),
        gap_litrao=_format_money(row.get("gap_litrao")),
        planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
    )
