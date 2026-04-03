from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row, tuple_row

from bot_api.commercial_scope import normalize_stored_scope_value, partition_gv_scopes, partition_sector_scopes
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
        self._filial_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, list[GiroFilialSummary]],
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
                FROM {schema}.giro_latest
                WHERE {where}
                """
            ).format(
                summary_select=_summary_select_sql(),
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
            FROM {schema}.giro_latest
            WHERE {where}
            GROUP BY {group_by}
            ORDER BY {group_by}
            """
        ).format(
            group_by=group_by,
            select_alias=sql.Identifier(str(select_alias or "scope_value")),
            summary_select=_summary_select_sql(),
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


def _summary_select_sql() -> sql.SQL:
    return sql.SQL(
        """
        COUNT(DISTINCT (filial, nb))::int AS client_count,
        COUNT(DISTINCT (filial, nb)) FILTER (
            WHERE giro_litrinho IN ('NOK', 'ZERO')
               OR giro_inteira IN ('NOK', 'ZERO')
               OR giro_litrao IN ('NOK', 'ZERO')
        )::int AS attention_count,
        COUNT(DISTINCT (filial, nb)) FILTER (
            WHERE giro_litrinho = 'ZERO'
               OR giro_inteira = 'ZERO'
               OR giro_litrao = 'ZERO'
        )::int AS zero_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrinho <> '-')::int AS litrinho_monitored_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrinho = 'OK')::int AS litrinho_ok_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrinho = 'NOK')::int AS litrinho_nok_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrinho = 'ZERO')::int AS litrinho_zero_count,
        COALESCE(SUM(gap_litrinho) FILTER (WHERE giro_litrinho <> '-'), 0) AS litrinho_gap_total,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_inteira <> '-')::int AS inteira_monitored_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_inteira = 'OK')::int AS inteira_ok_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_inteira = 'NOK')::int AS inteira_nok_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_inteira = 'ZERO')::int AS inteira_zero_count,
        COALESCE(SUM(gap_inteira) FILTER (WHERE giro_inteira <> '-'), 0) AS inteira_gap_total,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrao <> '-')::int AS litrao_monitored_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrao = 'OK')::int AS litrao_ok_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrao = 'NOK')::int AS litrao_nok_count,
        COUNT(DISTINCT (filial, nb)) FILTER (WHERE giro_litrao = 'ZERO')::int AS litrao_zero_count,
        COALESCE(SUM(gap_litrao) FILTER (WHERE giro_litrao <> '-'), 0) AS litrao_gap_total
        """
    )


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

    sector_keys, _legacy_sector_codes = partition_sector_scopes(allowed_sectors)
    gv_keys, dc_keys, _legacy_gv_codes = partition_gv_scopes(allowed_gv_vdes)

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
