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
    partition_gv_scopes,
    partition_sector_scopes,
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
class ComodatoRecord:
    filial: str
    cod_pdv: str
    nome: str
    nro_comodato: str
    material: str
    sub_tipo_material: str
    saldo: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComodatoClientSummary:
    filial: str
    cod_pdv: str
    nome: str
    comodato_count: int
    total_material: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ComodatosScopeSummary:
    client_count: int
    comodato_count: int
    total_material: str
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComodatosQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None
        self._last_error = ""
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_expires_at = 0.0
        self._scope_summary_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[float, ComodatosScopeSummary],
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
                                  AND table_name = 'comodatos_latest'
                            ) AS has_comodatos,
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
            comodatos_ready = bool(row and row["has_comodatos"])
            dclientes_ready = bool(row and row["has_dclientes"])
            ready = comodatos_ready and dclientes_ready
            self._last_error = ""
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": comodatos_ready,
                "dclientes_view_exists": dclientes_ready,
                "last_error": "" if ready else "Views reports.comodatos_latest e/ou reports.dclientes_latest nao encontradas.",
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

    def search_by_registration(
        self,
        filial: str,
        cod_pdv: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 100,
    ) -> list[ComodatoRecord]:
        normalized_filial = _normalize_code_value(filial)
        normalized_cod_pdv = _normalize_code_value(cod_pdv)
        if not normalized_filial:
            raise ValueError("Revenda/filial invalida.")
        if not normalized_cod_pdv:
            raise ValueError("NB/Cod PDV invalido.")

        filters = [
            sql.SQL("c.unb = %s"),
            sql.SQL("c.cliente = %s"),
        ]
        params: list[Any] = [normalized_filial, normalized_cod_pdv]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 200)))
        query = self._base_select(where=sql.SQL(" AND ").join(filters))
        return self._fetch(query, params)

    def search_by_name(
        self,
        query_text: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 100,
    ) -> list[ComodatoRecord]:
        normalized_query = _normalize_search_text(query_text)
        if not normalized_query:
            raise ValueError("Nome obrigatorio.")

        pattern = f"%{normalized_query}%"
        prefix = f"{normalized_query}%"
        filters = [
            sql.SQL("({} ILIKE %s OR {} ILIKE %s)").format(
                _normalized_text_sql("d.nome_fantasia"),
                _normalized_text_sql("d.razao_social"),
            ),
        ]
        params: list[Any] = [pattern, pattern]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        client_limit = max(1, min(limit, 20))
        row_limit = max(1, min(limit, 200))
        params.extend([prefix, prefix, client_limit, row_limit])
        query = sql.SQL(
            """
            WITH matched_clients AS (
                SELECT
                    d.filial,
                    d.cod_pdv,
                    COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), '') AS nome
                FROM {schema}.dclientes_latest d
                WHERE {where}
                  AND EXISTS (
                      SELECT 1
                      FROM {schema}.comodatos_latest c
                      WHERE c.unb = d.filial
                        AND c.cliente = d.cod_pdv
                  )
                ORDER BY
                    CASE
                        WHEN {fantasia_sql} ILIKE %s THEN 0
                        WHEN {razao_sql} ILIKE %s THEN 1
                        ELSE 2
                    END,
                    COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), ''),
                    d.filial,
                    d.cod_pdv
                LIMIT %s
            )
            SELECT
                m.filial,
                m.cod_pdv,
                COALESCE(NULLIF(m.nome, ''), c.nome, '') AS nome,
                c.nro_comodato,
                c.material,
                c.sub_tipo_material,
                {saldo_sql} AS saldo,
                COALESCE(b.reference_date::text, '') AS reference_date,
                c.batch_imported_at
            FROM matched_clients m
            JOIN {schema}.comodatos_latest c
              ON c.unb = m.filial
             AND c.cliente = m.cod_pdv
            LEFT JOIN {schema}.import_batches b ON b.id = c.batch_id
            ORDER BY
                COALESCE(NULLIF(m.nome, ''), c.nome, ''),
                m.filial,
                m.cod_pdv,
                c.nro_comodato,
                c.material
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            saldo_sql=_saldo_to_numeric_sql("c.saldo"),
            fantasia_sql=_normalized_text_sql("d.nome_fantasia"),
            razao_sql=_normalized_text_sql("d.razao_social"),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch(query, params)

    def search_client_summaries_by_name(
        self,
        query_text: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 20,
    ) -> list[ComodatoClientSummary]:
        normalized_query = _normalize_search_text(query_text)
        if not normalized_query:
            raise ValueError("Nome obrigatorio.")

        pattern = f"%{normalized_query}%"
        prefix = f"{normalized_query}%"
        filters = [
            sql.SQL("({} ILIKE %s OR {} ILIKE %s)").format(
                _normalized_text_sql("d.nome_fantasia"),
                _normalized_text_sql("d.razao_social"),
            ),
        ]
        params: list[Any] = [pattern, pattern]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.extend([prefix, prefix, max(1, min(limit, 30))])
        query = sql.SQL(
            """
            SELECT
                d.filial AS filial,
                d.cod_pdv AS cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), '') AS nome,
                COUNT(DISTINCT c.nro_comodato)::int AS comodato_count,
                SUM({saldo_sql}) AS total_material,
                COALESCE(b.reference_date::text, '') AS reference_date,
                MAX(c.batch_imported_at) AS batch_imported_at
            FROM {schema}.dclientes_latest d
            JOIN {schema}.comodatos_latest c
              ON c.unb = d.filial
             AND c.cliente = d.cod_pdv
            LEFT JOIN {schema}.import_batches b ON b.id = c.batch_id
            WHERE {where}
              AND EXISTS (
                  SELECT 1
                  FROM {schema}.comodatos_latest c_exists
                  WHERE c_exists.unb = d.filial
                    AND c_exists.cliente = d.cod_pdv
              )
            GROUP BY
                d.filial,
                d.cod_pdv,
                d.nome_fantasia,
                d.razao_social,
                b.reference_date
            ORDER BY
                CASE
                    WHEN {fantasia_sql} ILIKE %s THEN 0
                    WHEN {razao_sql} ILIKE %s THEN 1
                    ELSE 2
                END,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), ''),
                d.filial,
                d.cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            saldo_sql=_saldo_to_numeric_sql("c.saldo"),
            fantasia_sql=_normalized_text_sql("d.nome_fantasia"),
            razao_sql=_normalized_text_sql("d.razao_social"),
            where=sql.SQL(" AND ").join(filters),
        )
        return self._fetch_client_summaries(query, params)

    def search_by_document(
        self,
        document: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 100,
    ) -> list[ComodatoRecord]:
        normalized_document = _normalize_document(document)
        if not normalized_document:
            raise ValueError("Informe um CPF ou CNPJ valido.")

        filters = [sql.SQL("REGEXP_REPLACE(COALESCE(d.documento, ''), '[^0-9]', '', 'g') = %s")]
        params: list[Any] = [normalized_document]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 200)))
        query = self._base_select(where=sql.SQL(" AND ").join(filters))
        return self._fetch(query, params)

    def get_scope_summary(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> ComodatosScopeSummary:
        normalized_sectors = _normalize_scope_values(allowed_sectors)
        normalized_gv_vdes = _normalize_scope_values(allowed_gv_vdes)
        cache_key = (tuple(normalized_sectors), tuple(normalized_gv_vdes))
        now = monotonic()
        cached_entry = self._scope_summary_cache.get(cache_key)
        if cached_entry is not None and now < cached_entry[0]:
            return cached_entry[1]

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de comodatos indisponivel.")

        filters: list[sql.Composed] = []
        params: list[Any] = []
        self._apply_access_filter(filters, params, normalized_sectors, normalized_gv_vdes)
        query = sql.SQL(
            """
            SELECT
                COUNT(DISTINCT (c.unb, c.cliente))::int AS client_count,
                COUNT(DISTINCT c.nro_comodato)::int AS comodato_count,
                COALESCE(SUM({saldo_sql}), 0) AS total_material,
                COALESCE(MAX(b.reference_date)::text, '') AS reference_date,
                MAX(c.batch_imported_at) AS batch_imported_at
            FROM {schema}.comodatos_latest c
            JOIN {schema}.dclientes_latest d
              ON d.filial = c.unb
             AND d.cod_pdv = c.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = c.batch_id
            WHERE {where}
            """
        ).format(
            schema=sql.Identifier(self.schema),
            saldo_sql=_saldo_to_numeric_sql("c.saldo"),
            where=sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE"),
        )

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()

        summary = ComodatosScopeSummary(
            client_count=int(row["client_count"] or 0) if row else 0,
            comodato_count=int(row["comodato_count"] or 0) if row else 0,
            total_material=_format_quantity(row.get("total_material") if row else None),
            planilha_atualizada_em=_format_reference_date(
                row.get("reference_date") if row else None,
                row.get("batch_imported_at") if row else None,
            ),
        )
        self._scope_summary_cache[cache_key] = (now + 60.0, summary)
        return summary

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
                c.unb AS filial,
                c.cliente AS cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), c.nome, '') AS nome,
                c.nro_comodato,
                c.material,
                c.sub_tipo_material,
                {saldo_sql} AS saldo,
                COALESCE(b.reference_date::text, '') AS reference_date,
                c.batch_imported_at
            FROM {schema}.comodatos_latest c
            JOIN {schema}.dclientes_latest d
              ON d.filial = c.unb
             AND d.cod_pdv = c.cliente
            LEFT JOIN {schema}.import_batches b ON b.id = c.batch_id
            WHERE {where}
            ORDER BY
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), c.nome, ''),
                c.unb,
                c.cliente,
                c.nro_comodato,
                c.material
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            saldo_sql=_saldo_to_numeric_sql("c.saldo"),
            where=where,
        )

    def _fetch(self, query: sql.SQL, params: list[Any]) -> list[ComodatoRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de comodatos indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [
            ComodatoRecord(
                filial=_normalize_code_value(str(row["filial"] or "")),
                cod_pdv=_normalize_code_value(str(row["cod_pdv"] or "")),
                nome=str(row["nome"] or ""),
                nro_comodato=_normalize_code_value(str(row["nro_comodato"] or "")),
                material=str(row["material"] or ""),
                sub_tipo_material=str(row["sub_tipo_material"] or ""),
                saldo=_format_quantity(row.get("saldo")),
                planilha_atualizada_em=_format_reference_date(row.get("reference_date"), row.get("batch_imported_at")),
            )
            for row in rows
        ]

    def _fetch_client_summaries(self, query: sql.SQL, params: list[Any]) -> list[ComodatoClientSummary]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de comodatos indisponivel.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            ComodatoClientSummary(
                filial=_normalize_code_value(str(row["filial"] or "")),
                cod_pdv=_normalize_code_value(str(row["cod_pdv"] or "")),
                nome=str(row["nome"] or ""),
                comodato_count=int(row["comodato_count"] or 0),
                total_material=_format_quantity(row.get("total_material")),
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


def _normalize_search_text(value: str) -> str:
    lowered = str(value or "").strip().lower()
    normalized = "".join(
        char for char in unicodedata.normalize("NFD", lowered) if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _code_field_sql(field_name: str) -> sql.SQL:
    return sql.SQL(field_name) if "." in field_name else sql.Identifier(field_name)


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


def _saldo_to_numeric_sql(field_name: str) -> sql.SQL:
    return sql.SQL(
        "CASE "
        "WHEN BTRIM(COALESCE({field}, '')) = '' THEN 0::numeric "
        "ELSE COALESCE(NULLIF(REPLACE(REPLACE(REPLACE(BTRIM({field}), '.', ''), ',', '.'), '+', ''), ''), '0')::numeric * -1 "
        "END"
    ).format(field=_code_field_sql(field_name))


def _format_quantity(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, Decimal):
        numeric = value
    elif isinstance(value, (int, float)):
        numeric = Decimal(str(value))
    else:
        raw = str(value or "").strip()
        if not raw:
            return "0"
        if "," in raw:
            cleaned = raw.replace(".", "").replace(",", ".").replace("+", "").strip()
        else:
            cleaned = raw.replace("+", "").strip()
        try:
            numeric = Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return raw
    if numeric == numeric.to_integral():
        return str(int(numeric))
    return f"{numeric:.2f}".replace(".", ",")


def _format_reference_date(reference_date: Any, batch_imported_at: Any) -> str:
    if reference_date:
        return str(reference_date)
    if isinstance(batch_imported_at, datetime):
        if batch_imported_at.tzinfo is not None:
            return batch_imported_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return batch_imported_at.strftime("%Y-%m-%d %H:%M:%S")
    return str(batch_imported_at or "")
