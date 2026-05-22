from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
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
class PrazoLimiteEntryRecord:
    kpi: str
    percentual_pag_atraso: str
    prazo_atual: str
    cond_pag_atual: str
    limite_total: str
    faturamento_com_pdv: str
    pedidos: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PrazoLimiteClientRecord:
    filial: str
    cod_pdv: str
    nome: str
    documento: str
    setor: str
    seller_code: str
    manager_code: str
    entries: tuple[PrazoLimiteEntryRecord, ...]
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entries"] = [entry.to_dict() for entry in self.entries]
        return payload


class PrazoLimiteQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_expires_at = 0.0

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
                "dclientes_view_exists": False,
                "last_error": "REPORTS_DATABASE_URL nao configurada.",
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
                                  AND table_name = 'prazo_limite_latest'
                            ) AS has_prazo_limite,
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
            ready = bool(row and row["has_prazo_limite"] and row["has_dclientes"])
            if row and not row["has_prazo_limite"] and row["has_dclientes"]:
                last_error = "A base de prazo e limite ainda nao foi importada."
            elif row and row["has_prazo_limite"] and not row["has_dclientes"]:
                last_error = "A base de clientes ainda nao esta pronta para cruzar prazo e limite."
            else:
                last_error = "" if ready else "Views reports.prazo_limite_latest e/ou reports.dclientes_latest nao encontradas."
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": bool(row and row["has_prazo_limite"]),
                "dclientes_view_exists": bool(row and row["has_dclientes"]),
                "last_error": last_error,
            }
            self._cache_status(payload)
            return payload
        except Exception as exc:
            payload = {
                "database_configured": True,
                "ready": False,
                "schema": self.schema,
                "latest_view_exists": False,
                "dclientes_view_exists": False,
                "last_error": str(exc),
            }
            self._cache_status(payload)
            return payload

    def search_by_registration(
        self,
        filial: str,
        cod_pdv: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50,
    ) -> list[PrazoLimiteClientRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de prazo e limite indisponivel.")

        filters = [
            sql.SQL("pl.filial = %s"),
            sql.SQL("pl.cod_pdv = %s"),
        ]
        params: list[Any] = [normalize_stored_scope_value(filial), normalize_stored_scope_value(cod_pdv)]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 500)))
        query = sql.SQL(
            """
            SELECT
                pl.filial,
                pl.cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), CONCAT('NB ', pl.cod_pdv)) AS nome,
                COALESCE(NULLIF(d.documento, ''), '') AS documento,
                COALESCE(NULLIF(d.setor_vde, ''), '') AS setor,
                COALESCE(NULLIF(d.filial_setor_key, ''), '') AS seller_code,
                COALESCE(NULLIF(d.filial_gv_key, ''), '') AS manager_code,
                pl.kpi,
                pl.percentual_pag_atraso,
                pl.prazo_atual,
                pl.cond_pag_atual,
                pl.limite_total,
                pl.faturamento_com_pdv,
                pl.pedidos,
                COALESCE(pl.reference_date::text, '') AS reference_date,
                pl.batch_imported_at
            FROM {schema}.prazo_limite_latest pl
            LEFT JOIN {schema}.dclientes_latest d
              ON d.filial = pl.filial
             AND d.cod_pdv = pl.cod_pdv
            WHERE {where}
            ORDER BY pl.filial, pl.cod_pdv, pl.row_number
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return _group_client_records(rows)

    def search_by_document(
        self,
        document: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 50,
    ) -> list[PrazoLimiteClientRecord]:
        normalized_document = _normalize_document(document)
        if not normalized_document:
            raise ValueError("Informe um CPF ou CNPJ valido.")

        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de prazo e limite indisponivel.")

        filters = [
            sql.SQL("REGEXP_REPLACE(COALESCE(d.documento, ''), '[^0-9]', '', 'g') = %s"),
        ]
        params: list[Any] = [normalized_document]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 500)))
        query = sql.SQL(
            """
            SELECT
                pl.filial,
                pl.cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), CONCAT('NB ', pl.cod_pdv)) AS nome,
                COALESCE(NULLIF(d.documento, ''), '') AS documento,
                COALESCE(NULLIF(d.setor_vde, ''), '') AS setor,
                COALESCE(NULLIF(d.filial_setor_key, ''), '') AS seller_code,
                COALESCE(NULLIF(d.filial_gv_key, ''), '') AS manager_code,
                pl.kpi,
                pl.percentual_pag_atraso,
                pl.prazo_atual,
                pl.cond_pag_atual,
                pl.limite_total,
                pl.faturamento_com_pdv,
                pl.pedidos,
                COALESCE(pl.reference_date::text, '') AS reference_date,
                pl.batch_imported_at
            FROM {schema}.prazo_limite_latest pl
            LEFT JOIN {schema}.dclientes_latest d
              ON d.filial = pl.filial
             AND d.cod_pdv = pl.cod_pdv
            WHERE {where}
            ORDER BY pl.filial, pl.cod_pdv, pl.row_number
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return _group_client_records(rows)

    def _apply_access_filter(
        self,
        filters: list[sql.Composed],
        params: list[Any],
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
    ) -> None:
        filial_codes = partition_filial_scopes(allowed_sectors)
        sector_keys, _legacy_sector_codes = partition_sector_scopes(allowed_sectors)
        gv_keys, dc_keys, _legacy_gv_codes = partition_gv_scopes(allowed_gv_vdes)
        scope_filters: list[sql.Composed] = []
        if filial_codes:
            scope_filters.append(sql.SQL("COALESCE(d.filial, '') = ANY(%s)"))
            params.append(filial_codes)
        if sector_keys:
            scope_filters.append(sql.SQL("COALESCE(d.filial_setor_key, '') = ANY(%s)"))
            params.append(sector_keys)
        if gv_keys:
            scope_filters.append(sql.SQL("COALESCE(d.filial_gv_key, '') = ANY(%s)"))
            params.append(gv_keys)
        dc_scope_keys = [value[len("dc:") :] if value.startswith("dc:") else value for value in dc_keys]
        if dc_scope_keys:
            scope_filters.append(sql.SQL("COALESCE(d.filial_dc_key, '') = ANY(%s)"))
            params.append(dc_scope_keys)
        if scope_filters:
            filters.append(sql.SQL("(") + sql.SQL(" OR ").join(scope_filters) + sql.SQL(")"))
        elif _has_scope_values(allowed_sectors) or _has_scope_values(allowed_gv_vdes):
            filters.append(sql.SQL("FALSE"))

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


def _group_client_records(rows: list[dict[str, Any]]) -> list[PrazoLimiteClientRecord]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        filial = normalize_stored_scope_value(str(row.get("filial") or ""))
        cod_pdv = normalize_stored_scope_value(str(row.get("cod_pdv") or ""))
        if not filial or not cod_pdv:
            continue
        key = (filial, cod_pdv)
        if key not in grouped:
            grouped[key] = {
                "filial": filial,
                "cod_pdv": cod_pdv,
                "nome": str(row.get("nome") or "").strip(),
                "documento": str(row.get("documento") or "").strip(),
                "setor": normalize_stored_scope_value(str(row.get("setor") or "")),
                "seller_code": normalize_stored_scope_value(str(row.get("seller_code") or "")),
                "manager_code": normalize_stored_scope_value(str(row.get("manager_code") or "")),
                "entries": [],
                "planilha_atualizada_em": _format_updated_at(row.get("reference_date"), row.get("batch_imported_at")),
            }
        grouped[key]["entries"].append(
            PrazoLimiteEntryRecord(
                kpi=str(row.get("kpi") or "-").strip() or "-",
                percentual_pag_atraso=str(row.get("percentual_pag_atraso") or "-").strip() or "-",
                prazo_atual=str(row.get("prazo_atual") or "-").strip() or "-",
                cond_pag_atual=str(row.get("cond_pag_atual") or "-").strip() or "-",
                limite_total=_format_currency(row.get("limite_total")),
                faturamento_com_pdv=_format_currency(row.get("faturamento_com_pdv")),
                pedidos=_format_numeric_value(row.get("pedidos")),
            )
        )

    return [
        PrazoLimiteClientRecord(
            filial=item["filial"],
            cod_pdv=item["cod_pdv"],
            nome=item["nome"],
            documento=item["documento"],
            setor=item["setor"],
            seller_code=item["seller_code"],
            manager_code=item["manager_code"],
            entries=tuple(item["entries"]),
            planilha_atualizada_em=item["planilha_atualizada_em"],
        )
        for item in grouped.values()
    ]


def _format_updated_at(reference_date: Any, batch_imported_at: Any) -> str:
    reference_text = str(reference_date or "").strip()
    if reference_text:
        return reference_text
    if batch_imported_at is None:
        return "-"
    try:
        return batch_imported_at.astimezone().date().isoformat()
    except Exception:
        return str(batch_imported_at)


def _format_currency(value: Any) -> str:
    amount = _parse_decimal(value)
    if amount is None:
        return "R$ 0,00"
    formatted = f"{amount:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _format_numeric_value(value: Any) -> str:
    amount = _parse_decimal(value)
    if amount is None:
        return "0"
    if amount == amount.to_integral_value():
        return str(int(amount))
    normalized = format(amount.normalize(), "f")
    normalized = normalized.rstrip("0").rstrip(".") or "0"
    return normalized.replace(".", ",")


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    raw = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _normalize_scope_values(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = normalize_stored_scope_value(value)
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _has_scope_values(values: list[str] | None) -> bool:
    return any(str(value or "").strip() for value in values or [])


def _normalize_document(value: str) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits if len(digits) in {11, 14} else ""


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"
