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


@dataclass(frozen=True)
class GiroRecolhaOpportunity:
    filial: str
    cod_pdv: str
    nome: str
    documento: str
    revenda: str
    setor: str
    seller_code: str
    manager_code: str
    status_pdv: str
    cidade: str
    bairro: str
    visit_day: str
    total_caixas: str
    real_caixas: str
    gap_caixas: str
    gap_litrinho: str
    gap_inteira: str
    gap_litrao: str
    giro_litrinho: str
    giro_inteira: str
    giro_litrao: str
    faturamento_total: str
    pedidos_total: str
    media_faturamento_pedido: str
    percentual_pag_atraso: str
    prazo_atual: str
    cond_pag_atual: str
    planilha_giro_atualizada_em: str
    planilha_faturamento_atualizada_em: str

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

    def list_recolha_opportunities(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 200,
        min_gap: Decimal | int | float | str = 1,
        operation: str | list[str] | None = None,
        city: str | list[str] | None = None,
        district: str | list[str] | None = None,
        seller: str | list[str] | None = None,
        manager: str | list[str] | None = None,
        visit_day: str | list[str] | None = None,
        zero_only: bool = False,
    ) -> list[GiroRecolhaOpportunity]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de giro indisponivel.")

        filters: list[sql.Composed] = [
            sql.SQL(
                "("
                "g.giro_litrinho IN ('NOK', 'ZERO') "
                "OR g.giro_inteira IN ('NOK', 'ZERO') "
                "OR g.giro_litrao IN ('NOK', 'ZERO')"
                ")"
            )
        ]
        if zero_only:
            filters.append(
                sql.SQL(
                    "("
                    "g.giro_litrinho = 'ZERO' "
                    "OR g.giro_inteira = 'ZERO' "
                    "OR g.giro_litrao = 'ZERO'"
                    ")"
                )
            )
        params: list[Any] = []
        self._apply_access_filter(filters, params, _normalize_scope_values(allowed_sectors), _normalize_scope_values(allowed_gv_vdes))
        outer_filters: list[sql.Composed] = [sql.SQL("gb.gap_caixas >= %s")]
        min_gap_value = _parse_decimal(min_gap) or Decimal("0")
        outer_params: list[Any] = [min_gap_value]

        operation_filters = _normalize_scope_filter_values(operation)
        if len(operation_filters) == 1:
            outer_filters.append(sql.SQL("gb.filial = %s"))
            outer_params.append(operation_filters[0])
        elif operation_filters:
            outer_filters.append(sql.SQL("gb.filial = ANY(%s::text[])"))
            outer_params.append(operation_filters)

        seller_filters = _normalize_scope_filter_values(seller)
        if len(seller_filters) == 1:
            outer_filters.append(sql.SQL("COALESCE(NULLIF(d.filial_setor_key, ''), gb.filial_setor_key, '') = %s"))
            outer_params.append(seller_filters[0])
        elif seller_filters:
            outer_filters.append(sql.SQL("COALESCE(NULLIF(d.filial_setor_key, ''), gb.filial_setor_key, '') = ANY(%s::text[])"))
            outer_params.append(seller_filters)

        manager_filters = _normalize_scope_filter_values(manager)
        if len(manager_filters) == 1:
            outer_filters.append(sql.SQL("COALESCE(NULLIF(d.filial_gv_key, ''), gb.filial_gv_key, '') = %s"))
            outer_params.append(manager_filters[0])
        elif manager_filters:
            outer_filters.append(sql.SQL("COALESCE(NULLIF(d.filial_gv_key, ''), gb.filial_gv_key, '') = ANY(%s::text[])"))
            outer_params.append(manager_filters)

        city_filters = _normalize_text_filter_values(city)
        if len(city_filters) == 1:
            outer_filters.append(sql.SQL("COALESCE(d.payload ->> 'Cidade', '') ILIKE %s"))
            outer_params.append(f"%{city_filters[0]}%")
        elif city_filters:
            outer_filters.append(sql.SQL("BTRIM(COALESCE(d.payload ->> 'Cidade', '')) = ANY(%s::text[])"))
            outer_params.append(city_filters)

        district_filters = _normalize_text_filter_values(district)
        if len(district_filters) == 1:
            outer_filters.append(
                sql.SQL("COALESCE(d.payload ->> 'Bairro', d.payload ->> 'BAIRRO', d.payload ->> 'bairro', '') ILIKE %s")
            )
            outer_params.append(f"%{district_filters[0]}%")
        elif district_filters:
            outer_filters.append(
                sql.SQL("BTRIM(COALESCE(d.payload ->> 'Bairro', d.payload ->> 'BAIRRO', d.payload ->> 'bairro', '')) = ANY(%s::text[])")
            )
            outer_params.append(district_filters)

        visit_day_filters = _normalize_visit_day_filter_values(visit_day)
        if len(visit_day_filters) == 1:
            outer_filters.append(
                sql.SQL(
                    "("
                    "POSITION(%s IN UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')))) > 0 "
                    "OR UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', ''))) = %s"
                    ")"
                )
            )
            outer_params.extend([visit_day_filters[0], visit_day_filters[0]])
        elif visit_day_filters:
            outer_filters.append(
                sql.SQL(
                    "EXISTS ("
                    "SELECT 1 FROM unnest(%s::text[]) AS selected_visit_day(token) "
                    "WHERE POSITION(selected_visit_day.token IN UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')))) > 0 "
                    "OR UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', ''))) = selected_visit_day.token"
                    ")"
                )
            )
            outer_params.append(visit_day_filters)

        params.extend(outer_params)
        params.append(max(1, min(int(limit or 200), 1000)))

        query = sql.SQL(
            """
            WITH giro_base AS (
                SELECT
                    g.*,
                    (COALESCE(g.total_litrinho, 0) + COALESCE(g.total_inteira, 0) + COALESCE(g.total_litrao, 0)) AS total_caixas,
                    (COALESCE(g.real_litrinho, 0) + COALESCE(g.real_inteira, 0) + COALESCE(g.real_litrao, 0)) AS real_caixas,
                    (COALESCE(g.gap_litrinho, 0) + COALESCE(g.gap_inteira, 0) + COALESCE(g.gap_litrao, 0)) AS gap_caixas
                FROM {schema}.giro_latest g
                WHERE {where}
            ),
            prazo_agg AS (
                SELECT
                    pl.filial,
                    pl.cod_pdv,
                    SUM(COALESCE(pl.faturamento_com_pdv, 0)) AS faturamento_total,
                    SUM(COALESCE(pl.pedidos, 0)) AS pedidos_total,
                    MAX(NULLIF(pl.percentual_pag_atraso, '')) AS percentual_pag_atraso,
                    MAX(NULLIF(pl.prazo_atual, '')) AS prazo_atual,
                    MAX(NULLIF(pl.cond_pag_atual, '')) AS cond_pag_atual,
                    COALESCE(MAX(pl.reference_date)::text, '') AS prazo_reference_date,
                    MAX(pl.batch_imported_at) AS prazo_batch_imported_at
                FROM {schema}.prazo_limite_latest pl
                GROUP BY pl.filial, pl.cod_pdv
            )
            SELECT
                gb.filial,
                gb.nb,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), gb.fantasia, '') AS fantasia,
                COALESCE(NULLIF(d.documento, ''), '') AS documento,
                gb.setor,
                gb.revenda,
                COALESCE(NULLIF(d.filial_setor_key, ''), gb.filial_setor_key, '') AS filial_setor_key,
                COALESCE(NULLIF(d.filial_gv_key, ''), gb.filial_gv_key, '') AS filial_gv_key,
                COALESCE(NULLIF(d.status_pdv, ''), '') AS status_pdv,
                COALESCE(d.payload ->> 'Cidade', '') AS cidade,
                COALESCE(d.payload ->> 'Bairro', d.payload ->> 'BAIRRO', d.payload ->> 'bairro', '') AS bairro,
                COALESCE(d.payload ->> 'Dia de Visita do VDE', '') AS visit_day,
                gb.total_caixas,
                gb.real_caixas,
                gb.gap_caixas,
                gb.gap_litrinho,
                gb.gap_inteira,
                gb.gap_litrao,
                gb.giro_litrinho,
                gb.giro_inteira,
                gb.giro_litrao,
                COALESCE(
                    NULLIF(
                        REPLACE(
                            REPLACE(
                                REGEXP_REPLACE(
                                    COALESCE(
                                        NULLIF(d.payload ->> 'Faturamento Total (M-1)', ''),
                                        NULLIF(d.payload ->> 'Faturamento DH (M-1)', '')
                                    ),
                                    '[^0-9,.]',
                                    '',
                                    'g'
                                ),
                                '.',
                                ''
                            ),
                            ',',
                            '.'
                        ),
                        ''
                    )::numeric,
                    0
                ) AS faturamento_total,
                COALESCE(pa.pedidos_total, 0) AS pedidos_total,
                CASE
                    WHEN COALESCE(pa.pedidos_total, 0) > 0 THEN COALESCE(
                        NULLIF(
                            REPLACE(
                                REPLACE(
                                    REGEXP_REPLACE(
                                        COALESCE(
                                            NULLIF(d.payload ->> 'Faturamento Total (M-1)', ''),
                                            NULLIF(d.payload ->> 'Faturamento DH (M-1)', '')
                                        ),
                                        '[^0-9,.]',
                                        '',
                                        'g'
                                    ),
                                    '.',
                                    ''
                                ),
                                ',',
                                '.'
                            ),
                            ''
                        )::numeric,
                        0
                    ) / pa.pedidos_total
                    ELSE 0
                END AS media_faturamento_pedido,
                COALESCE(pa.percentual_pag_atraso, '') AS percentual_pag_atraso,
                COALESCE(pa.prazo_atual, '') AS prazo_atual,
                COALESCE(pa.cond_pag_atual, '') AS cond_pag_atual,
                COALESCE(gb.reference_date::text, '') AS giro_reference_date,
                gb.batch_imported_at AS giro_batch_imported_at,
                COALESCE(pa.prazo_reference_date, '') AS prazo_reference_date,
                pa.prazo_batch_imported_at
            FROM giro_base gb
            LEFT JOIN prazo_agg pa
              ON pa.filial = gb.filial
             AND pa.cod_pdv = gb.nb
            LEFT JOIN {schema}.dclientes_latest d
              ON d.filial = gb.filial
             AND d.cod_pdv = gb.nb
            WHERE {outer_where}
            ORDER BY
                gb.gap_caixas DESC,
                media_faturamento_pedido DESC,
                faturamento_total DESC,
                gb.filial,
                gb.setor,
                gb.nb
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            outer_where=sql.SQL(" AND ").join(outer_filters),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [_row_to_recolha_opportunity(row) for row in rows]

    def list_recolha_filter_options(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        min_gap: Decimal | int | float | str = 1,
        operation: str | list[str] | None = None,
        city: str | list[str] | None = None,
        district: str | list[str] | None = None,
        seller: str | list[str] | None = None,
        manager: str | list[str] | None = None,
        visit_day: str | list[str] | None = None,
        zero_only: bool = False,
    ) -> dict[str, list[dict[str, str]]]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de giro indisponivel.")

        filters: list[sql.Composed] = [
            sql.SQL(
                "("
                "g.giro_litrinho IN ('NOK', 'ZERO') "
                "OR g.giro_inteira IN ('NOK', 'ZERO') "
                "OR g.giro_litrao IN ('NOK', 'ZERO')"
                ")"
            )
        ]
        if zero_only:
            filters.append(
                sql.SQL(
                    "("
                    "g.giro_litrinho = 'ZERO' "
                    "OR g.giro_inteira = 'ZERO' "
                    "OR g.giro_litrao = 'ZERO'"
                    ")"
                )
            )
        params: list[Any] = []
        self._apply_access_filter(filters, params, _normalize_scope_values(allowed_sectors), _normalize_scope_values(allowed_gv_vdes))

        option_filters: list[sql.Composed] = [sql.SQL("gap_caixas >= %s")]
        min_gap_value = _parse_decimal(min_gap) or Decimal("0")
        option_params: list[Any] = [min_gap_value]

        operation_filters = _normalize_scope_filter_values(operation)
        if len(operation_filters) == 1:
            option_filters.append(sql.SQL("filial = %s"))
            option_params.append(operation_filters[0])
        elif operation_filters:
            option_filters.append(sql.SQL("filial = ANY(%s::text[])"))
            option_params.append(operation_filters)

        seller_filters = _normalize_scope_filter_values(seller)
        if len(seller_filters) == 1:
            option_filters.append(sql.SQL("seller_code = %s"))
            option_params.append(seller_filters[0])
        elif seller_filters:
            option_filters.append(sql.SQL("seller_code = ANY(%s::text[])"))
            option_params.append(seller_filters)

        manager_filters = _normalize_scope_filter_values(manager)
        if len(manager_filters) == 1:
            option_filters.append(sql.SQL("manager_code = %s"))
            option_params.append(manager_filters[0])
        elif manager_filters:
            option_filters.append(sql.SQL("manager_code = ANY(%s::text[])"))
            option_params.append(manager_filters)

        city_filters = _normalize_text_filter_values(city)
        if city_filters:
            option_filters.append(sql.SQL("cidade = ANY(%s::text[])"))
            option_params.append(city_filters)

        district_filters = _normalize_text_filter_values(district)
        if len(district_filters) == 1:
            option_filters.append(sql.SQL("bairro = %s"))
            option_params.append(district_filters[0])
        elif district_filters:
            option_filters.append(sql.SQL("bairro = ANY(%s::text[])"))
            option_params.append(district_filters)

        visit_day_filters = _normalize_visit_day_filter_values(visit_day)
        if len(visit_day_filters) == 1:
            option_filters.append(
                sql.SQL(
                    "("
                    "POSITION(%s IN UPPER(BTRIM(COALESCE(visit_day, '')))) > 0 "
                    "OR UPPER(BTRIM(COALESCE(visit_day, ''))) = %s"
                    ")"
                )
            )
            option_params.extend([visit_day_filters[0], visit_day_filters[0]])
        elif visit_day_filters:
            option_filters.append(
                sql.SQL(
                    "EXISTS ("
                    "SELECT 1 FROM unnest(%s::text[]) AS selected_visit_day(token) "
                    "WHERE POSITION(selected_visit_day.token IN UPPER(BTRIM(COALESCE(visit_day, '')))) > 0 "
                    "OR UPPER(BTRIM(COALESCE(visit_day, ''))) = selected_visit_day.token"
                    ")"
                )
            )
            option_params.append(visit_day_filters)

        params.extend(option_params)
        query = sql.SQL(
            """
            WITH base AS (
                SELECT
                    g.filial,
                    NULLIF(g.revenda, '') AS revenda,
                    COALESCE(NULLIF(d.filial_setor_key, ''), g.filial_setor_key, '') AS seller_code,
                    COALESCE(NULLIF(d.filial_gv_key, ''), g.filial_gv_key, '') AS manager_code,
                    COALESCE(d.payload ->> 'Cidade', '') AS cidade,
                    COALESCE(d.payload ->> 'Bairro', d.payload ->> 'BAIRRO', d.payload ->> 'bairro', '') AS bairro,
                    COALESCE(d.payload ->> 'Dia de Visita do VDE', '') AS visit_day,
                    (COALESCE(g.gap_litrinho, 0) + COALESCE(g.gap_inteira, 0) + COALESCE(g.gap_litrao, 0)) AS gap_caixas
                FROM {schema}.giro_latest g
                LEFT JOIN {schema}.dclientes_latest d
                  ON d.filial = g.filial
                 AND d.cod_pdv = g.nb
                WHERE {where}
            ),
            filtered AS (
                SELECT * FROM base WHERE {option_where}
            )
            SELECT
                COALESCE((
                    SELECT jsonb_agg(item ORDER BY item ->> 'value')
                    FROM (
                        SELECT DISTINCT jsonb_build_object(
                            'value', filial,
                            'label', filial || CASE WHEN BTRIM(COALESCE(revenda, '')) <> '' THEN ' - ' || revenda ELSE '' END
                        ) AS item
                        FROM filtered
                        WHERE BTRIM(COALESCE(filial, '')) <> ''
                    ) operation_items
                ), '[]'::jsonb) AS operations,
                COALESCE((
                    SELECT jsonb_agg(item ORDER BY item ->> 'value')
                    FROM (
                        SELECT DISTINCT jsonb_build_object('value', seller_code, 'label', seller_code) AS item
                        FROM filtered
                        WHERE BTRIM(COALESCE(seller_code, '')) <> ''
                    ) seller_items
                ), '[]'::jsonb) AS sellers,
                COALESCE((
                    SELECT jsonb_agg(item ORDER BY item ->> 'value')
                    FROM (
                        SELECT DISTINCT jsonb_build_object('value', manager_code, 'label', manager_code) AS item
                        FROM filtered
                        WHERE BTRIM(COALESCE(manager_code, '')) <> ''
                    ) manager_items
                ), '[]'::jsonb) AS managers,
                COALESCE((
                    SELECT jsonb_agg(item ORDER BY item ->> 'label')
                    FROM (
                        SELECT DISTINCT jsonb_build_object('value', cidade, 'label', cidade) AS item
                        FROM filtered
                        WHERE BTRIM(COALESCE(cidade, '')) <> ''
                    ) city_items
                ), '[]'::jsonb) AS cities,
                COALESCE((
                    SELECT jsonb_agg(item ORDER BY item ->> 'label')
                    FROM (
                        SELECT DISTINCT jsonb_build_object('value', bairro, 'label', bairro) AS item
                        FROM filtered
                        WHERE BTRIM(COALESCE(bairro, '')) <> ''
                    ) district_items
                ), '[]'::jsonb) AS districts,
                COALESCE((
                    SELECT jsonb_agg(item ORDER BY item ->> 'label')
                    FROM (
                        SELECT DISTINCT jsonb_build_object('value', visit_day, 'label', visit_day) AS item
                        FROM filtered
                        WHERE BTRIM(COALESCE(visit_day, '')) <> ''
                    ) visit_day_items
                ), '[]'::jsonb) AS visit_days
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            option_where=sql.SQL(" AND ").join(option_filters),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone() or {}
        return {
            "operations": _normalize_option_items(row.get("operations")),
            "sellers": _normalize_option_items(row.get("sellers")),
            "managers": _normalize_option_items(row.get("managers")),
            "cities": _normalize_option_items(row.get("cities")),
            "districts": _normalize_option_items(row.get("districts")),
            "visit_days": _normalize_option_items(row.get("visit_days")),
        }

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
            litrinho_gap_total="0",
            inteira_monitored_count=0,
            inteira_ok_count=0,
            inteira_nok_count=0,
            inteira_zero_count=0,
            inteira_gap_total="0",
            litrao_monitored_count=0,
            litrao_ok_count=0,
            litrao_nok_count=0,
            litrao_zero_count=0,
            litrao_gap_total="0",
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
        "litrinho_gap_total": _format_box_quantity(row.get("litrinho_gap_total")),
        "inteira_monitored_count": int(row.get("inteira_monitored_count") or 0),
        "inteira_ok_count": int(row.get("inteira_ok_count") or 0),
        "inteira_nok_count": int(row.get("inteira_nok_count") or 0),
        "inteira_zero_count": int(row.get("inteira_zero_count") or 0),
        "inteira_gap_total": _format_box_quantity(row.get("inteira_gap_total")),
        "litrao_monitored_count": int(row.get("litrao_monitored_count") or 0),
        "litrao_ok_count": int(row.get("litrao_ok_count") or 0),
        "litrao_nok_count": int(row.get("litrao_nok_count") or 0),
        "litrao_zero_count": int(row.get("litrao_zero_count") or 0),
        "litrao_gap_total": _format_box_quantity(row.get("litrao_gap_total")),
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


def _normalize_text_filter_values(values: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, (list, tuple)) else [values]
    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        for part in str(value or "").replace("|", ",").split(","):
            item = " ".join(part.strip().split())
            if item and item not in seen:
                normalized.append(item)
                seen.add(item)
    return normalized


def _normalize_scope_filter_values(values: str | list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in _normalize_text_filter_values(values):
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


def _normalize_visit_day_filter_values(values: str | list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in _normalize_text_filter_values(values):
        item = _normalize_visit_day_token(value)
        if item and item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


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
    amount = _parse_decimal(value)
    if amount is None:
        return "0,00"
    return f"{amount:.2f}".replace(".", ",")


def _format_box_quantity(value: Any) -> str:
    amount = _parse_decimal(value)
    if amount is None:
        return "0"
    return str(int(amount.to_integral_value()))


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.upper().startswith("R$"):
        raw = raw[2:].strip()
    if "," in raw:
        cleaned = raw.replace(".", "").replace(",", ".").replace("+", "").strip()
    else:
        cleaned = raw.replace("+", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _row_to_client_record(row: dict[str, Any]) -> GiroClientRecord:
    return GiroClientRecord(
        filial=normalize_stored_scope_value(str(row.get("filial") or "")),
        cod_pdv=normalize_stored_scope_value(str(row.get("nb") or "")),
        nome=str(row.get("fantasia") or "").strip(),
        setor=normalize_stored_scope_value(str(row.get("setor") or "")),
        revenda=str(row.get("revenda") or "").strip(),
        total_litrinho=_format_box_quantity(row.get("total_litrinho")),
        real_litrinho=_format_box_quantity(row.get("real_litrinho")),
        gap_litrinho=_format_box_quantity(row.get("gap_litrinho")),
        giro_litrinho=str(row.get("giro_litrinho") or "-").strip() or "-",
        total_inteira=_format_box_quantity(row.get("total_inteira")),
        real_inteira=_format_box_quantity(row.get("real_inteira")),
        gap_inteira=_format_box_quantity(row.get("gap_inteira")),
        giro_inteira=str(row.get("giro_inteira") or "-").strip() or "-",
        total_litrao=_format_box_quantity(row.get("total_litrao")),
        real_litrao=_format_box_quantity(row.get("real_litrao")),
        gap_litrao=_format_box_quantity(row.get("gap_litrao")),
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
        total_caixas=_format_box_quantity(row.get("total_caixas")),
        gap_caixas=_format_box_quantity(row.get("gap_caixas")),
        gap_litrinho=_format_box_quantity(row.get("gap_litrinho")),
        gap_inteira=_format_box_quantity(row.get("gap_inteira")),
        gap_litrao=_format_box_quantity(row.get("gap_litrao")),
        planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
    )


def _row_to_recolha_opportunity(row: dict[str, Any]) -> GiroRecolhaOpportunity:
    return GiroRecolhaOpportunity(
        filial=normalize_stored_scope_value(str(row.get("filial") or "")),
        cod_pdv=normalize_stored_scope_value(str(row.get("nb") or "")),
        nome=str(row.get("fantasia") or "").strip(),
        documento=str(row.get("documento") or "").strip(),
        revenda=str(row.get("revenda") or "").strip(),
        setor=normalize_stored_scope_value(str(row.get("setor") or "")),
        seller_code=normalize_stored_scope_value(str(row.get("filial_setor_key") or "")),
        manager_code=normalize_stored_scope_value(str(row.get("filial_gv_key") or "")),
        status_pdv=str(row.get("status_pdv") or "").strip(),
        cidade=str(row.get("cidade") or "").strip(),
        bairro=str(row.get("bairro") or "").strip(),
        visit_day=str(row.get("visit_day") or "").strip(),
        total_caixas=_format_box_quantity(row.get("total_caixas")),
        real_caixas=_format_box_quantity(row.get("real_caixas")),
        gap_caixas=_format_box_quantity(row.get("gap_caixas")),
        gap_litrinho=_format_box_quantity(row.get("gap_litrinho")),
        gap_inteira=_format_box_quantity(row.get("gap_inteira")),
        gap_litrao=_format_box_quantity(row.get("gap_litrao")),
        giro_litrinho=str(row.get("giro_litrinho") or "-").strip() or "-",
        giro_inteira=str(row.get("giro_inteira") or "-").strip() or "-",
        giro_litrao=str(row.get("giro_litrao") or "-").strip() or "-",
        faturamento_total=_format_currency(row.get("faturamento_total")),
        pedidos_total=_format_quantity(row.get("pedidos_total")),
        media_faturamento_pedido=_format_currency(row.get("media_faturamento_pedido")),
        percentual_pag_atraso=str(row.get("percentual_pag_atraso") or "-").strip() or "-",
        prazo_atual=str(row.get("prazo_atual") or "-").strip() or "-",
        cond_pag_atual=str(row.get("cond_pag_atual") or "-").strip() or "-",
        planilha_giro_atualizada_em=_format_reference_date(row.get("giro_reference_date"), row.get("giro_batch_imported_at")),
        planilha_faturamento_atualizada_em=_format_reference_date(row.get("prazo_reference_date"), row.get("prazo_batch_imported_at")),
    )


def _format_currency(value: Any) -> str:
    return f"R$ {_format_money(value)}"


def _format_quantity(value: Any) -> str:
    amount = _parse_decimal(value)
    if amount is None:
        return "0"
    if amount == amount.to_integral_value():
        return str(int(amount))
    normalized = format(amount.normalize(), "f").rstrip("0").rstrip(".")
    return normalized.replace(".", ",") or "0"


def _normalize_option_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        option_value = str(item.get("value") or "").strip()
        if not option_value or option_value in seen:
            continue
        seen.add(option_value)
        options.append(
            {
                "value": option_value,
                "label": str(item.get("label") or option_value).strip() or option_value,
            }
        )
    return options
