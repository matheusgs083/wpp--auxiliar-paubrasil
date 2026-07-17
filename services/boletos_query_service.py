from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from datetime import date
import re
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from pypdf import PdfReader, PdfWriter

from bot_api.commercial_scope import normalize_numeric_code


@dataclass(frozen=True)
class BoletoRecord:
    filial: str
    cod_pdv: str
    mapa: str
    nota_fiscal: str
    num_documento: str
    setor: str
    gv: str
    pagador: str
    documento: str
    data_documento: date | None
    vencimento: date | None
    valor_centavos: int
    nosso_numero: str
    linha_digitavel: str
    page_number: int
    pdf_bytes: bytes

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["pdf_bytes"] = b""
        return payload


@dataclass(frozen=True)
class BoletoRevendaPdfRecord:
    filial: str
    total_boletos: int
    total_valor_centavos: int
    data_inicial: date | None
    data_final: date | None
    pdf_bytes: bytes


class BoletosQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def status(self) -> dict[str, Any]:
        if not self.database_url:
            return {"ready": False, "latest_view_exists": False, "last_error": "REPORTS_DATABASE_URL nao configurada."}
        try:
            with self._connect() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.views
                            WHERE table_schema = %s AND table_name = 'boletos_latest'
                        ) AS exists
                        """,
                        (self.schema,),
                    )
                    exists = bool(cur.fetchone()["exists"])
            return {"ready": exists, "latest_view_exists": exists, "last_error": "" if exists else "View de boletos ainda nao importada."}
        except Exception as exc:
            return {"ready": False, "latest_view_exists": False, "last_error": str(exc)}

    def search_by_registration(
        self,
        *,
        filial: str,
        cod_pdv: str,
        allowed_sectors: list[str] | tuple[str, ...] | None = None,
        allowed_gv_vdes: list[str] | tuple[str, ...] | None = None,
        limit: int = 5,
        include_pdf: bool = True,
    ) -> list[BoletoRecord]:
        filial_code = normalize_numeric_code(filial)
        nb_code = normalize_numeric_code(cod_pdv)
        if not filial_code or not nb_code:
            return []
        filters = [
            sql.SQL("b.status = 'ok'"),
            sql.SQL("b.filial = %s"),
            sql.SQL("b.cod_pdv = %s"),
        ]
        params: list[Any] = [filial_code, nb_code]
        sector_scopes = tuple(str(item or "").strip() for item in (allowed_sectors or ()) if str(item or "").strip())
        gv_scopes = tuple(str(item or "").strip() for item in (allowed_gv_vdes or ()) if str(item or "").strip())
        if sector_scopes:
            filters.append(sql.SQL("b.filial_setor_key = ANY(%s)"))
            params.append(list(sector_scopes))
        if gv_scopes:
            filters.append(sql.SQL("b.filial_gv_key = ANY(%s)"))
            params.append(list(gv_scopes))
        params.append(max(1, min(int(limit), 20)))
        source_pdf_select = sql.SQL("src.pdf_bytes AS source_pdf_bytes") if include_pdf else sql.SQL("NULL::bytea AS source_pdf_bytes")
        query = sql.SQL(
            """
            SELECT b.filial, b.cod_pdv, b.setor, b.gv, b.pagador, b.documento, b.vencimento,
                   b.valor_centavos, b.nosso_numero, b.linha_digitavel, b.page_number,
                   b.mapa, b.nota_fiscal, b.num_documento, b.data_documento,
                   b.pdf_bytes, {}
            FROM {}.boletos_latest b
            LEFT JOIN {}.boletos_pdf_source src ON src.batch_id = b.batch_id
            WHERE {}
            ORDER BY b.vencimento ASC NULLS LAST, b.page_number ASC
            LIMIT %s
            """
        ).format(source_pdf_select, sql.Identifier(self.schema), sql.Identifier(self.schema), sql.SQL(" AND ").join(filters))
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                return [_row_to_record(row) for row in cur.fetchall()]

    def get_revenda_pdf(self, *, filial: str) -> BoletoRevendaPdfRecord | None:
        filial_code = normalize_numeric_code(filial)
        if not filial_code:
            return None
        query = sql.SQL(
            """
            SELECT p.filial, p.total_boletos, p.total_valor_centavos,
                   p.data_inicial, p.data_final, p.pdf_bytes
            FROM {}.boletos_revenda_pdf p
            JOIN {}.dataset_state st ON st.dataset_name IN (%s, %s) AND st.active_batch_id = p.batch_id
            WHERE p.filial = %s
            LIMIT 1
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, (f"boletos_bradesco_op_{filial_code}", "boletos_bradesco", filial_code))
                row = cur.fetchone()
                if not row:
                    return None
                return BoletoRevendaPdfRecord(
                    filial=str(row.get("filial") or ""),
                    total_boletos=int(row.get("total_boletos") or 0),
                    total_valor_centavos=int(row.get("total_valor_centavos") or 0),
                    data_inicial=row.get("data_inicial"),
                    data_final=row.get("data_final"),
                    pdf_bytes=bytes(row.get("pdf_bytes") or b""),
                )

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=int(self.connect_timeout_seconds))


def _row_to_record(row: dict[str, Any]) -> BoletoRecord:
    page_number = int(row.get("page_number") or 0)
    pdf_bytes = bytes(row.get("pdf_bytes") or b"")
    source_pdf_bytes = bytes(row.get("source_pdf_bytes") or b"")
    if not pdf_bytes and source_pdf_bytes and page_number > 0:
        pdf_bytes = _split_pdf_page_bytes(source_pdf_bytes, page_number)
    return BoletoRecord(
        filial=str(row.get("filial") or ""),
        cod_pdv=str(row.get("cod_pdv") or ""),
        mapa=str(row.get("mapa") or ""),
        nota_fiscal=str(row.get("nota_fiscal") or ""),
        num_documento=str(row.get("num_documento") or ""),
        setor=str(row.get("setor") or ""),
        gv=str(row.get("gv") or ""),
        pagador=str(row.get("pagador") or ""),
        documento=str(row.get("documento") or ""),
        data_documento=row.get("data_documento"),
        vencimento=row.get("vencimento"),
        valor_centavos=int(row.get("valor_centavos") or 0),
        nosso_numero=str(row.get("nosso_numero") or ""),
        linha_digitavel=str(row.get("linha_digitavel") or ""),
        page_number=page_number,
        pdf_bytes=pdf_bytes,
    )


def _split_pdf_page_bytes(source_pdf_bytes: bytes, page_number: int) -> bytes:
    reader = PdfReader(io.BytesIO(source_pdf_bytes))
    page_index = page_number - 1
    if page_index < 0 or page_index >= len(reader.pages):
        return b""
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _normalize_schema(value: str) -> str:
    normalized = str(value or "reports").strip() or "reports"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise ValueError(f"Schema invalido: {value!r}")
    return normalized
