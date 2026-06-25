from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal
from time import monotonic
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row, tuple_row

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.db import get_connection_pool


@dataclass(frozen=True)
class ClienteScoreRecord:
    filial: str
    cod_pdv: str
    cliente: str
    razao_social: str
    score: str
    piorando_2026: bool
    pct_atraso_historico: Decimal
    titulos_historico: int
    recebido_historico: Decimal
    maior_atraso_dias: int
    vezes_mais_30d: int
    tarifa_paga: Decimal
    juros_pagos: Decimal
    em_aberto_hoje: Decimal
    vencido_hoje: Decimal
    dias_vencido_mais_antigo: int
    planilha_atualizada_em: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ClientesScoreQueryService:
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
                              AND table_name = 'clientes_score_latest'
                        ) AS has_clientes_score
                        """,
                        (self.schema,),
                    )
                    row = cur.fetchone()
            ready = bool(row and row["has_clientes_score"])
            payload = {
                "database_configured": True,
                "ready": ready,
                "schema": self.schema,
                "latest_view_exists": ready,
                "last_error": "" if ready else "A base clientes_score ainda nao foi importada.",
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

    def search_by_registration(self, filial: str, cod_pdv: str) -> ClienteScoreRecord | None:
        status = self.status()
        if not status["ready"]:
            raise RuntimeError(status["last_error"] or "Base de score de clientes indisponivel.")
        normalized_filial = normalize_numeric_code(filial)
        normalized_cod_pdv = normalize_numeric_code(cod_pdv)
        if not normalized_filial or not normalized_cod_pdv:
            return None
        query = sql.SQL(
            """
            SELECT
                filial,
                cod_pdv,
                cliente,
                razao_social,
                score,
                piorando_2026,
                pct_atraso_historico,
                titulos_historico,
                recebido_historico,
                maior_atraso_dias,
                vezes_mais_30d,
                tarifa_paga,
                juros_pagos,
                em_aberto_hoje,
                vencido_hoje,
                dias_vencido_mais_antigo,
                COALESCE(reference_date::text, '') AS reference_date,
                batch_imported_at
            FROM {schema}.clientes_score_latest
            WHERE filial = %s
              AND cod_pdv = %s
            ORDER BY row_number
            LIMIT 1
            """
        ).format(schema=sql.Identifier(self.schema))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (normalized_filial, normalized_cod_pdv))
                row = cur.fetchone()
        return _row_to_score_record(row) if row else None

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


def _row_to_score_record(row: dict[str, Any]) -> ClienteScoreRecord:
    return ClienteScoreRecord(
        filial=normalize_numeric_code(str(row.get("filial") or "")),
        cod_pdv=normalize_numeric_code(str(row.get("cod_pdv") or "")),
        cliente=str(row.get("cliente") or "").strip(),
        razao_social=str(row.get("razao_social") or "").strip(),
        score=str(row.get("score") or "").strip().upper() or "-",
        piorando_2026=bool(row.get("piorando_2026")),
        pct_atraso_historico=_decimal(row.get("pct_atraso_historico")),
        titulos_historico=int(row.get("titulos_historico") or 0),
        recebido_historico=_decimal(row.get("recebido_historico")),
        maior_atraso_dias=int(row.get("maior_atraso_dias") or 0),
        vezes_mais_30d=int(row.get("vezes_mais_30d") or 0),
        tarifa_paga=_decimal(row.get("tarifa_paga")),
        juros_pagos=_decimal(row.get("juros_pagos")),
        em_aberto_hoje=_decimal(row.get("em_aberto_hoje")),
        vencido_hoje=_decimal(row.get("vencido_hoje")),
        dias_vencido_mais_antigo=int(row.get("dias_vencido_mais_antigo") or 0),
        planilha_atualizada_em=_format_updated_at(row.get("reference_date"), row.get("batch_imported_at")),
    )


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


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


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"
