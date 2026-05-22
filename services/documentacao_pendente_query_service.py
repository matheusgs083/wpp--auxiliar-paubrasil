from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
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

OK_ELIGIBLE_DOC_COLUMNS = (
    "contrato_social",
    "cpf",
    "rg",
    "comprovante_residencia",
    "fachada",
)


@dataclass(frozen=True)
class DocumentacaoPendenteScopeSummary:
    monitored_client_count: int
    pending_client_count: int
    pending_document_count: int
    contrato_social_pendentes: int
    cpf_pendentes: int
    rg_pendentes: int
    comprovante_residencia_pendentes: int
    fachada_pendentes: int
    ficha_cadastro_pendentes: int
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentacaoPendenteClientRecord:
    filial: str
    cod_pdv: str
    nome: str
    setor: str
    seller_code: str
    manager_code: str
    visit_day: str
    contrato_social: str
    cpf: str
    rg: str
    comprovante_residencia: str
    fachada: str
    ficha_cadastro: str
    pending_count: int
    pending_docs: tuple[str, ...]
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentacaoPendenteFilialSummary:
    filial: str
    active_client_count: int
    scanned_client_count: int
    ok_client_count: int
    pending_client_count: int
    missing_scan_count: int
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DocumentacaoPendenteQueryService:
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
                                  AND table_name = 'documentacao_pendente_latest'
                            ) AS has_documentacao,
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
            ready = bool(row and row["has_documentacao"] and row["has_dclientes"])
            if row and not row["has_documentacao"] and row["has_dclientes"]:
                last_error = "A base de documentacao pendente ainda nao foi importada."
            elif row and row["has_documentacao"] and not row["has_dclientes"]:
                last_error = "A base de clientes ainda nao esta pronta para cruzar a documentacao pendente."
            else:
                last_error = "" if ready else "Views reports.documentacao_pendente_latest e/ou reports.dclientes_latest nao encontradas."
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": bool(row and row["has_documentacao"]),
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
        limit: int = 20,
    ) -> list[DocumentacaoPendenteClientRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de documentacao pendente indisponivel.")
        filters = [
            sql.SQL("doc.filial = %s"),
            sql.SQL("doc.cod_pdv = %s"),
        ]
        params: list[Any] = [normalize_stored_scope_value(filial), normalize_stored_scope_value(cod_pdv)]
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 100)))
        query = sql.SQL(
            """
            SELECT
                doc.filial,
                doc.cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), CONCAT('NB ', doc.cod_pdv)) AS nome,
                COALESCE(NULLIF(d.setor_vde, ''), '') AS setor,
                COALESCE(NULLIF(d.filial_setor_key, ''), '') AS seller_code,
                COALESCE(NULLIF(d.filial_gv_key, ''), '') AS manager_code,
                COALESCE(BTRIM(d.payload ->> 'Dia de Visita do VDE'), '') AS visit_day,
                doc.contrato_social,
                doc.cpf,
                doc.rg,
                doc.comprovante_residencia,
                doc.fachada,
                doc.ficha_cadastro,
                {_effective_pending_count_sql} AS pending_count,
                {_effective_pending_docs_sql} AS pending_docs,
                COALESCE(doc.reference_date::text, '') AS reference_date,
                doc.batch_imported_at
            FROM {schema}.documentacao_pendente_latest doc
            LEFT JOIN {schema}.dclientes_latest d
              ON d.filial = doc.filial
             AND d.cod_pdv = doc.cod_pdv
            WHERE {where}
            ORDER BY doc.filial, doc.cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            _effective_pending_count_sql=_effective_pending_count_sql(),
            _effective_pending_docs_sql=_effective_pending_docs_sql(),
        )
        return self._fetch_rows(query, params)

    def get_scope_summary_by_visit_day(
        self,
        visit_day: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> DocumentacaoPendenteScopeSummary:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de documentacao pendente indisponivel.")
        visit_day_filter, visit_params = _visit_day_filter_sql(visit_day)
        filters = [visit_day_filter]
        params = list(visit_params)
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        query = sql.SQL(
            """
            WITH visit_base AS (
                SELECT DISTINCT
                    d.filial,
                    d.cod_pdv
                FROM {schema}.dclientes_latest d
                WHERE {where}
            )
            SELECT
                COUNT(*)::int AS monitored_client_count,
                COUNT(*) FILTER (WHERE {_effective_pending_count_sql} > 0)::int AS pending_client_count,
                COALESCE(SUM({_effective_pending_count_sql}), 0)::int AS pending_document_count,
                COUNT(*) FILTER (WHERE COALESCE(doc.contrato_social, 'Nok') = 'Nok')::int AS contrato_social_pendentes,
                COUNT(*) FILTER (WHERE COALESCE(doc.cpf, 'Nok') = 'Nok')::int AS cpf_pendentes,
                COUNT(*) FILTER (WHERE COALESCE(doc.rg, 'Nok') = 'Nok')::int AS rg_pendentes,
                COUNT(*) FILTER (WHERE COALESCE(doc.comprovante_residencia, 'Nok') = 'Nok')::int AS comprovante_residencia_pendentes,
                COUNT(*) FILTER (WHERE COALESCE(doc.fachada, 'Nok') = 'Nok')::int AS fachada_pendentes,
                COUNT(*) FILTER (WHERE COALESCE(doc.ficha_cadastro, 'Nok') = 'Nok')::int AS ficha_cadastro_pendentes,
                COALESCE(MAX(doc.reference_date)::text, '') AS reference_date,
                MAX(doc.batch_imported_at) AS batch_imported_at
            FROM visit_base base
            LEFT JOIN {schema}.documentacao_pendente_latest doc
              ON doc.filial = base.filial
             AND doc.cod_pdv = base.cod_pdv
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            _effective_pending_count_sql=_effective_pending_count_sql(),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone() or {}
        return DocumentacaoPendenteScopeSummary(
            monitored_client_count=int(row.get("monitored_client_count") or 0),
            pending_client_count=int(row.get("pending_client_count") or 0),
            pending_document_count=int(row.get("pending_document_count") or 0),
            contrato_social_pendentes=int(row.get("contrato_social_pendentes") or 0),
            cpf_pendentes=int(row.get("cpf_pendentes") or 0),
            rg_pendentes=int(row.get("rg_pendentes") or 0),
            comprovante_residencia_pendentes=int(row.get("comprovante_residencia_pendentes") or 0),
            fachada_pendentes=int(row.get("fachada_pendentes") or 0),
            ficha_cadastro_pendentes=int(row.get("ficha_cadastro_pendentes") or 0),
            planilha_atualizada_em=_format_updated_at(row.get("reference_date"), row.get("batch_imported_at")),
        )

    def list_pending_by_visit_day(
        self,
        visit_day: str,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
        limit: int = 5000,
    ) -> list[DocumentacaoPendenteClientRecord]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de documentacao pendente indisponivel.")
        visit_day_filter, visit_params = _visit_day_filter_sql(visit_day)
        filters = [visit_day_filter, sql.SQL("(") + _effective_pending_count_sql() + sql.SQL(" > 0)")]
        params = list(visit_params)
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        params.append(max(1, min(limit, 5000)))
        query = sql.SQL(
            """
            SELECT
                doc.filial,
                doc.cod_pdv,
                COALESCE(NULLIF(d.nome_fantasia, ''), NULLIF(d.razao_social, ''), CONCAT('NB ', doc.cod_pdv)) AS nome,
                COALESCE(NULLIF(d.setor_vde, ''), '') AS setor,
                COALESCE(NULLIF(d.filial_setor_key, ''), '') AS seller_code,
                COALESCE(NULLIF(d.filial_gv_key, ''), '') AS manager_code,
                COALESCE(BTRIM(d.payload ->> 'Dia de Visita do VDE'), '') AS visit_day,
                doc.contrato_social,
                doc.cpf,
                doc.rg,
                doc.comprovante_residencia,
                doc.fachada,
                doc.ficha_cadastro,
                {_effective_pending_count_sql} AS pending_count,
                {_effective_pending_docs_sql} AS pending_docs,
                COALESCE(doc.reference_date::text, '') AS reference_date,
                doc.batch_imported_at
            FROM {schema}.documentacao_pendente_latest doc
            INNER JOIN {schema}.dclientes_latest d
              ON d.filial = doc.filial
             AND d.cod_pdv = doc.cod_pdv
            WHERE {where}
            ORDER BY d.filial_gv_key, d.filial_setor_key, doc.filial, doc.cod_pdv
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            _effective_pending_count_sql=_effective_pending_count_sql(),
            _effective_pending_docs_sql=_effective_pending_docs_sql(),
        )
        return self._fetch_rows(query, params)

    def list_summary_by_filial(
        self,
        allowed_sectors: list[str] | None = None,
        allowed_gv_vdes: list[str] | None = None,
    ) -> list[DocumentacaoPendenteFilialSummary]:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de documentacao pendente indisponivel.")

        filters = [sql.SQL(_active_clients_sql())]
        params: list[Any] = []
        self._apply_access_filter(filters, params, allowed_sectors, allowed_gv_vdes)
        query = sql.SQL(
            """
            WITH active_base AS (
                SELECT DISTINCT
                    d.filial,
                    d.cod_pdv
                FROM {schema}.dclientes_latest d
                WHERE {where}
            )
            SELECT
                base.filial,
                COUNT(*)::int AS active_client_count,
                COUNT(*) FILTER (WHERE doc.cod_pdv IS NOT NULL)::int AS scanned_client_count,
                COUNT(*) FILTER (
                    WHERE doc.cod_pdv IS NOT NULL
                      AND {_effective_pending_count_sql} = 0
                )::int AS ok_client_count,
                COUNT(*) FILTER (
                    WHERE doc.cod_pdv IS NOT NULL
                      AND {_effective_pending_count_sql} > 0
                )::int AS pending_client_count,
                COUNT(*) FILTER (WHERE doc.cod_pdv IS NULL)::int AS missing_scan_count,
                COALESCE(MAX(doc.reference_date)::text, '') AS reference_date,
                MAX(doc.batch_imported_at) AS batch_imported_at
            FROM active_base base
            LEFT JOIN {schema}.documentacao_pendente_latest doc
              ON doc.filial = base.filial
             AND doc.cod_pdv = base.cod_pdv
            GROUP BY base.filial
            ORDER BY base.filial
            """
        ).format(
            schema=sql.Identifier(self.schema),
            where=sql.SQL(" AND ").join(filters),
            _effective_pending_count_sql=_effective_pending_count_sql(),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [
            DocumentacaoPendenteFilialSummary(
                filial=normalize_stored_scope_value(str(row.get("filial") or "")),
                active_client_count=int(row.get("active_client_count") or 0),
                scanned_client_count=int(row.get("scanned_client_count") or 0),
                ok_client_count=int(row.get("ok_client_count") or 0),
                pending_client_count=int(row.get("pending_client_count") or 0),
                missing_scan_count=int(row.get("missing_scan_count") or 0),
                planilha_atualizada_em=_format_updated_at(row.get("reference_date"), row.get("batch_imported_at")),
            )
            for row in rows
            if normalize_stored_scope_value(str(row.get("filial") or ""))
        ]

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

    def _fetch_rows(self, query: sql.SQL, params: list[Any]) -> list[DocumentacaoPendenteClientRecord]:
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [_row_to_client_record(row) for row in rows]

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


def _row_to_client_record(row: dict[str, Any]) -> DocumentacaoPendenteClientRecord:
    raw_pending_docs = row.get("pending_docs") or []
    pending_docs = tuple(str(item).strip() for item in raw_pending_docs if str(item).strip())
    return DocumentacaoPendenteClientRecord(
        filial=normalize_stored_scope_value(str(row.get("filial") or "")),
        cod_pdv=normalize_stored_scope_value(str(row.get("cod_pdv") or "")),
        nome=str(row.get("nome") or "").strip(),
        setor=normalize_stored_scope_value(str(row.get("setor") or "")),
        seller_code=normalize_stored_scope_value(str(row.get("seller_code") or "")),
        manager_code=normalize_stored_scope_value(str(row.get("manager_code") or "")),
        visit_day=str(row.get("visit_day") or "").strip(),
        contrato_social=str(row.get("contrato_social") or "Nok").strip() or "Nok",
        cpf=str(row.get("cpf") or "Nok").strip() or "Nok",
        rg=str(row.get("rg") or "Nok").strip() or "Nok",
        comprovante_residencia=str(row.get("comprovante_residencia") or "Nok").strip() or "Nok",
        fachada=str(row.get("fachada") or "Nok").strip() or "Nok",
        ficha_cadastro=str(row.get("ficha_cadastro") or "Nok").strip() or "Nok",
        pending_count=int(row.get("pending_count") or 0),
        pending_docs=pending_docs,
        planilha_atualizada_em=_format_updated_at(row.get("reference_date"), row.get("batch_imported_at")),
    )


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


def _visit_day_filter_sql(visit_day: str) -> tuple[sql.Composed, list[Any]]:
    normalized_visit_day = _normalize_visit_day(visit_day)
    normalized_visit_day_token = _normalize_visit_day_token(visit_day)
    if not normalized_visit_day or not normalized_visit_day_token:
        raise ValueError("Dia de visita obrigatorio.")
    filter_sql = sql.SQL(
        "("
        "POSITION(%s IN UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', '')))) > 0 "
        "OR UPPER(BTRIM(COALESCE(d.payload ->> 'Dia de Visita do VDE', ''))) = %s"
        ")"
    )
    return filter_sql, [normalized_visit_day_token, normalized_visit_day.upper()]


def _normalize_visit_day(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_visit_day_token(value: str) -> str:
    normalized = _normalize_visit_day(value)
    visit_day_map = {
        "SEGUNDA": "SEG/",
        "TERCA": "TER/",
        "QUARTA": "QUA/",
        "QUINTA": "QUI/",
        "SEXTA": "SEX/",
        "SABADO": "SAB/",
        "DOMINGO": "DOM/",
    }
    normalized = visit_day_map.get(normalized, normalized)
    return normalized if normalized.endswith("/") else f"{normalized}/"


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


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _active_clients_sql() -> str:
    return "LEFT(UPPER(BTRIM(COALESCE(d.status_pdv, ''))), 4) = 'ATIV'"


def _effective_pending_count_sql() -> sql.Composed:
    terms = [
        sql.SQL("(CASE WHEN COALESCE(doc.{}, 'Nok') = 'Nok' THEN 1 ELSE 0 END)").format(sql.Identifier(column_name))
        for column_name in OK_ELIGIBLE_DOC_COLUMNS
    ]
    return sql.SQL(" + ").join(terms)


def _effective_pending_docs_sql() -> sql.Composed:
    parts = []
    for column_name in OK_ELIGIBLE_DOC_COLUMNS:
        label = _field_label(column_name)
        parts.append(
            sql.SQL("CASE WHEN COALESCE(doc.{}, 'Nok') = 'Nok' THEN {} ELSE NULL END").format(
                sql.Identifier(column_name),
                sql.Literal(label),
            )
        )
    return sql.SQL("ARRAY_REMOVE(ARRAY[") + sql.SQL(", ").join(parts) + sql.SQL("], NULL)")


def _field_label(column_name: str) -> str:
    labels = {
        "contrato_social": "Contrato Social",
        "cpf": "Cpf",
        "rg": "Rg",
        "comprovante_residencia": "Comprovante de residencia",
        "fachada": "Fachada",
        "ficha_cadastro": "Ficha de Cadastro",
    }
    return labels.get(column_name, column_name)
