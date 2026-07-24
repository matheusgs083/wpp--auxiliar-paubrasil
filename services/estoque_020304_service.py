from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.import_publication import activate_import_batch, ensure_dataset_state_table, prune_import_batches
from bot_api.services.relatorio_020304_pdf_service import (
    build_020304_pdf,
    read_020304_csv,
    summarize_020304_rows,
)


DATASET_NAME_PREFIX = "estoque_020304_op_"
EXPECTED_EXTENSION_SET = {".csv"}


@dataclass(frozen=True)
class Estoque020304ValidationResult:
    dataset_name: str
    source_path: str
    expected_filial: str
    ok: bool
    rows: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError(
                "; ".join(self.sample_errors)
                if self.sample_errors
                else "Erros na validacao do estoque 020304."
            )


@dataclass(frozen=True)
class Estoque020304ImportSummary:
    source_path: str
    rows: int
    produtos_com_disponivel: int
    produtos_sem_disponivel: int
    produtos_com_reserva: int
    produtos_com_saida: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Estoque020304PdfRecord:
    filial: str
    filial_nome: str
    reference_date: date | None
    updated_at: datetime | None
    total_rows: int
    source_name: str
    pdf_bytes: bytes


@dataclass(frozen=True)
class Estoque020304ProductStockRecord:
    filial: str
    filial_nome: str
    reference_date: date | None
    updated_at: datetime | None
    source_name: str
    total_rows: int
    codigo: str
    descricao: str
    unidade: str
    inicial: int
    entrada: int
    reserva: int
    transito: int
    saidas: int
    disponivel: int
    reserva_magali: int
    linhas_encontradas: int


class Estoque020304ImportService:
    def __init__(
        self,
        database_url: str,
        schema: str,
        *,
        dataset_name: str,
        expected_filial: str,
        filial_nome: str = "",
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.dataset_name = str(dataset_name or "").strip().lower()
        self.expected_filial = normalize_numeric_code(expected_filial)
        self.filial_nome = str(filial_nome or "").strip()
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        if not self.dataset_name:
            raise ValueError("dataset_name obrigatorio para estoque 020304.")
        if not self.expected_filial:
            raise ValueError("expected_filial obrigatoria para estoque 020304.")

    def validate_source(self, source_path: Path) -> Estoque020304ValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings: list[str] = []
        rows = 0

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                rows = len(read_020304_csv(path))
            except Exception as exc:
                errors.append(str(exc))

        if rows <= 0 and not errors:
            errors.append("Arquivo 02.03.04 sem produtos validos.")

        return Estoque020304ValidationResult(
            dataset_name=self.dataset_name,
            source_path=str(path),
            expected_filial=self.expected_filial,
            ok=not errors,
            rows=rows,
            error_count=len(errors),
            warning_count=len(warnings),
            sample_errors=errors[:10],
            sample_warnings=warnings[:10],
        )

    def summarize_source(self, source_path: Path) -> Estoque020304ImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        path = source_path.expanduser().resolve()
        rows = read_020304_csv(path)
        summary = summarize_020304_rows(
            rows,
            filial=self.expected_filial,
            filial_nome=self.filial_nome,
            source_name=path.name,
        )
        return Estoque020304ImportSummary(
            source_path=str(path),
            rows=summary.row_count,
            produtos_com_disponivel=summary.produtos_com_disponivel,
            produtos_sem_disponivel=summary.produtos_sem_disponivel,
            produtos_com_reserva=summary.produtos_com_reserva,
            produtos_com_saida=summary.produtos_com_saida,
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        rows = read_020304_csv(path)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)
        summary = summarize_020304_rows(
            rows,
            filial=self.expected_filial,
            filial_nome=self.filial_nome,
            reference_date=batch_date,
            source_name=path.name,
        )
        pdf_bytes = build_020304_pdf(rows, summary=summary)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_report(conn, batch_id, path.name, summary, pdf_bytes)
            self._insert_item_rows(conn, batch_id, summary.filial, rows)
            activate_import_batch(conn, self.schema, self.dataset_name, batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, self.dataset_name, keep_last=3)
            conn.commit()

        return {
            "source_path": str(path),
            "batch_id": batch_id,
            "dataset_name": self.dataset_name,
            "filial": self.expected_filial,
            "reference_date": batch_date.isoformat(),
            "source_hash": source_hash,
            "schema": self.schema,
            "rows": len(rows),
            "pdf_bytes": len(pdf_bytes),
            "produtos_com_disponivel": summary.produtos_com_disponivel,
            "produtos_sem_disponivel": summary.produtos_sem_disponivel,
            "produtos_com_reserva": summary.produtos_com_reserva,
            "produtos_com_saida": summary.produtos_com_saida,
            "published_as_active_batch": True,
        }

    def refresh_latest_view(self) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_schema(conn)
            self._create_latest_view(conn)
            conn.commit()
        return {"ok": True, "schema": self.schema, "view": f"{self.schema}.estoque_020304_latest"}

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=int(self.connect_timeout_seconds))

    def _ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.import_batches (
                        id BIGSERIAL PRIMARY KEY,
                        dataset_name VARCHAR(80) NOT NULL,
                        source_file TEXT NOT NULL,
                        file_hash VARCHAR(64) NOT NULL,
                        reference_date DATE,
                        total_rows INTEGER NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            ensure_dataset_state_table(conn, self.schema)
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.estoque_020304_reports (
                        batch_id BIGINT PRIMARY KEY REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        dataset_name VARCHAR(80) NOT NULL,
                        filial VARCHAR(16) NOT NULL DEFAULT '',
                        filial_nome TEXT NOT NULL DEFAULT '',
                        reference_date DATE,
                        source_name TEXT NOT NULL DEFAULT '',
                        total_rows INTEGER NOT NULL DEFAULT 0,
                        summary JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        pdf_bytes BYTEA NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.estoque_020304_items (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        filial VARCHAR(16) NOT NULL DEFAULT '',
                        codigo VARCHAR(32) NOT NULL DEFAULT '',
                        descricao TEXT NOT NULL DEFAULT '',
                        unidade VARCHAR(32) NOT NULL DEFAULT '',
                        inicial INTEGER NOT NULL DEFAULT 0,
                        entrada INTEGER NOT NULL DEFAULT 0,
                        entrada_mcdd INTEGER NOT NULL DEFAULT 0,
                        reserva INTEGER NOT NULL DEFAULT 0,
                        transito INTEGER NOT NULL DEFAULT 0,
                        saidas INTEGER NOT NULL DEFAULT 0,
                        saida_mcdd INTEGER NOT NULL DEFAULT 0,
                        disponivel INTEGER NOT NULL DEFAULT 0,
                        reserva_magali INTEGER NOT NULL DEFAULT 0,
                        inicial_agendado INTEGER NOT NULL DEFAULT 0,
                        entrada_agendado INTEGER NOT NULL DEFAULT 0,
                        saida_agendado INTEGER NOT NULL DEFAULT 0,
                        disponivel_agendado INTEGER NOT NULL DEFAULT 0,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS estoque_020304_reports_filial_idx ON {}.estoque_020304_reports (filial, imported_at DESC)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS estoque_020304_items_batch_codigo_idx ON {}.estoque_020304_items (batch_id, codigo)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS estoque_020304_items_filial_codigo_idx ON {}.estoque_020304_items (filial, codigo)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS import_batches_estoque_020304_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)"
                ).format(sql.Identifier(self.schema))
            )

    def _insert_batch(
        self,
        conn: psycopg.Connection[Any],
        source_file: str,
        reference_date: date,
        file_hash: str,
        rows: int,
    ) -> int:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.import_batches (dataset_name, source_file, file_hash, reference_date, total_rows)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """
                ).format(sql.Identifier(self.schema)),
                (self.dataset_name, source_file, file_hash, reference_date, rows),
            )
            row = cur.fetchone()
        return int(row["id"])

    def _insert_report(
        self,
        conn: psycopg.Connection[Any],
        batch_id: int,
        source_name: str,
        summary: Any,
        pdf_bytes: bytes,
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.estoque_020304_reports (
                        batch_id, dataset_name, filial, filial_nome, reference_date,
                        source_name, total_rows, summary, pdf_bytes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                ).format(sql.Identifier(self.schema)),
                (
                    batch_id,
                    self.dataset_name,
                    summary.filial,
                    summary.filial_nome,
                    summary.reference_date,
                    source_name,
                    summary.row_count,
                    Jsonb(summary.to_dict()),
                    pdf_bytes,
                ),
            )

    def _insert_item_rows(
        self,
        conn: psycopg.Connection[Any],
        batch_id: int,
        filial: str,
        rows: list[Any],
    ) -> None:
        if not rows:
            return
        query = sql.SQL(
            """
            INSERT INTO {}.estoque_020304_items (
                batch_id, row_number, filial, codigo, descricao, unidade,
                inicial, entrada, entrada_mcdd, reserva, transito, saidas,
                saida_mcdd, disponivel, reserva_magali, inicial_agendado,
                entrada_agendado, saida_agendado, disponivel_agendado
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            """
        ).format(sql.Identifier(self.schema))
        params = [
            (
                batch_id,
                row_number,
                filial,
                row.codigo,
                row.descricao,
                row.unidade,
                row.inicial,
                row.entrada,
                row.entrada_mcdd,
                row.reserva,
                row.transito,
                row.saidas,
                row.saida_mcdd,
                row.disponivel,
                row.reserva_magali,
                row.inicial_agendado,
                row.entrada_agendado,
                row.saida_agendado,
                row.disponivel_agendado,
            )
            for row_number, row in enumerate(rows, start=1)
        ]
        with conn.cursor() as cur:
            cur.executemany(query, params)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        ensure_dataset_state_table(conn, self.schema)
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    CREATE OR REPLACE VIEW {}.estoque_020304_latest AS
                    SELECT
                        r.batch_id,
                        r.dataset_name,
                        r.filial,
                        r.filial_nome,
                        r.reference_date,
                        r.source_name,
                        r.total_rows,
                        r.summary,
                        r.pdf_bytes,
                        r.imported_at,
                        b.source_file,
                        b.file_hash,
                        b.imported_at AS batch_imported_at
                    FROM {}.estoque_020304_reports r
                    JOIN {}.dataset_state st
                      ON st.dataset_name = r.dataset_name
                     AND st.active_batch_id = r.batch_id
                    JOIN {}.import_batches b ON b.id = r.batch_id
                    WHERE st.dataset_name LIKE {}
                    """
                ).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                    sql.Literal(f"{DATASET_NAME_PREFIX}%"),
                )
            )


class Estoque020304QueryService:
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
                            WHERE table_schema = %s AND table_name = 'estoque_020304_latest'
                        ) AS view_exists
                        """,
                        (self.schema,),
                    )
                    row = cur.fetchone()
                    view_exists = bool(row and row.get("view_exists"))
                    if not view_exists:
                        return {
                            "ready": False,
                            "latest_view_exists": False,
                            "items_available": False,
                            "last_error": "View de estoque 020304 ainda nao importada.",
                        }
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = 'estoque_020304_items'
                        ) AS table_exists
                        """,
                        (self.schema,),
                    )
                    items_row = cur.fetchone() or {}
                    items_available = False
                    if bool(items_row.get("table_exists")):
                        cur.execute(
                            sql.SQL(
                                """
                                SELECT EXISTS (
                                    SELECT 1
                                    FROM {}.estoque_020304_latest latest
                                    JOIN {}.estoque_020304_items item ON item.batch_id = latest.batch_id
                                    LIMIT 1
                                ) AS items_available
                                """
                            ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
                        )
                        items_available = bool((cur.fetchone() or {}).get("items_available"))
                    cur.execute(
                        sql.SQL("SELECT COUNT(*) AS total FROM {}.estoque_020304_latest").format(
                            sql.Identifier(self.schema)
                        )
                    )
                    total = int(cur.fetchone()["total"] or 0)
            return {
                "ready": total > 0,
                "latest_view_exists": True,
                "items_available": items_available,
                "reports": total,
                "last_error": "" if total else "Nenhum estoque 020304 ativo.",
            }
        except Exception as exc:
            return {"ready": False, "latest_view_exists": False, "last_error": str(exc)}

    def get_pdf_report(self, *, filial: str) -> Estoque020304PdfRecord | None:
        filial_code = normalize_numeric_code(filial)
        if not filial_code:
            return None
        query = sql.SQL(
            """
            SELECT filial, filial_nome, reference_date, batch_imported_at, total_rows, source_name, pdf_bytes
            FROM {}.estoque_020304_latest
            WHERE filial = %s
            ORDER BY batch_imported_at DESC, batch_id DESC
            LIMIT 1
            """
        ).format(sql.Identifier(self.schema))
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, (filial_code,))
                row = cur.fetchone()
        if not row:
            return None
        return Estoque020304PdfRecord(
            filial=str(row.get("filial") or ""),
            filial_nome=str(row.get("filial_nome") or ""),
            reference_date=row.get("reference_date"),
            updated_at=row.get("batch_imported_at"),
            total_rows=int(row.get("total_rows") or 0),
            source_name=str(row.get("source_name") or ""),
            pdf_bytes=bytes(row.get("pdf_bytes") or b""),
        )

    def get_product_stock(self, *, filial: str, product_code: str) -> Estoque020304ProductStockRecord | None:
        filial_code = normalize_numeric_code(filial)
        codigo = normalize_numeric_code(product_code)
        if not filial_code or not codigo:
            return None
        with self._connect() as conn:
            dprodutos_cte = _dprodutos_name_cte(self.schema, conn)
            query = sql.SQL(
                """
                WITH latest_report AS (
                    SELECT
                        batch_id,
                        filial,
                        filial_nome,
                        reference_date,
                        batch_imported_at,
                        total_rows,
                        source_name
                    FROM {}.estoque_020304_latest
                    WHERE filial = %s
                    ORDER BY batch_imported_at DESC, batch_id DESC
                    LIMIT 1
                ),
                {dprodutos_cte}
                SELECT
                    latest.filial,
                    latest.filial_nome,
                    latest.reference_date,
                    latest.batch_imported_at,
                    latest.total_rows,
                    latest.source_name,
                    item.codigo,
                    item.descricao AS estoque_descricao,
                    COALESCE(
                        NULLIF(prod.descricao, ''),
                        NULLIF(prod.descricao_unitaria, ''),
                        NULLIF(item.descricao, ''),
                        ''
                    ) AS produto_descricao,
                    item.unidade,
                    item.inicial,
                    item.entrada,
                    item.reserva,
                    item.transito,
                    item.saidas,
                    item.disponivel,
                    item.reserva_magali
                FROM latest_report latest
                JOIN {}.estoque_020304_items item
                  ON item.batch_id = latest.batch_id
                 AND item.filial = latest.filial
                LEFT JOIN dprodutos_ref prod ON prod.codigo = item.codigo
                WHERE item.codigo = %s
                ORDER BY item.row_number
                """
            ).format(
                sql.Identifier(self.schema),
                sql.Identifier(self.schema),
                dprodutos_cte=dprodutos_cte,
            )
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, (filial_code, codigo))
                rows = cur.fetchall()
        if not rows:
            return None
        first = rows[0]
        units = tuple(
            dict.fromkeys(str(item.get("unidade") or "").strip() for item in rows if str(item.get("unidade") or "").strip())
        )
        unidade = units[0] if len(units) == 1 else "varias"
        return Estoque020304ProductStockRecord(
            filial=str(first.get("filial") or ""),
            filial_nome=str(first.get("filial_nome") or ""),
            reference_date=first.get("reference_date"),
            updated_at=first.get("batch_imported_at"),
            source_name=str(first.get("source_name") or ""),
            total_rows=int(first.get("total_rows") or 0),
            codigo=normalize_numeric_code(first.get("codigo")) or codigo,
            descricao=str(first.get("produto_descricao") or first.get("estoque_descricao") or "").strip(),
            unidade=unidade,
            inicial=sum(_int_value(item.get("inicial")) for item in rows),
            entrada=sum(_int_value(item.get("entrada")) for item in rows),
            reserva=sum(_int_value(item.get("reserva")) for item in rows),
            transito=sum(_int_value(item.get("transito")) for item in rows),
            saidas=sum(_int_value(item.get("saidas")) for item in rows),
            disponivel=sum(_int_value(item.get("disponivel")) for item in rows),
            reserva_magali=sum(_int_value(item.get("reserva_magali")) for item in rows),
            linhas_encontradas=len(rows),
        )

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=int(self.connect_timeout_seconds))


def _normalize_schema(value: str) -> str:
    normalized = str(value or "reports").strip() or "reports"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise ValueError(f"Schema invalido: {value!r}")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dprodutos_name_cte(schema: str, conn: psycopg.Connection[Any]) -> sql.Composed:
    if not _relation_exists(conn, schema, "dprodutos_latest") or not _relation_column_exists(
        conn, schema, "dprodutos_latest", "codigo"
    ):
        return sql.SQL(
            """
            dprodutos_ref AS (
                SELECT
                    NULL::text AS codigo,
                    NULL::text AS descricao,
                    NULL::text AS descricao_unitaria
                WHERE FALSE
            )
            """
        )
    descricao_sql = sql.SQL("descricao") if _relation_column_exists(conn, schema, "dprodutos_latest", "descricao") else sql.SQL("NULL::text")
    descricao_unitaria_sql = (
        sql.SQL("descricao_unitaria")
        if _relation_column_exists(conn, schema, "dprodutos_latest", "descricao_unitaria")
        else sql.SQL("NULL::text")
    )
    return sql.SQL(
        """
        dprodutos_ref AS (
            SELECT
                codigo,
                MAX(NULLIF({descricao}, '')) AS descricao,
                MAX(NULLIF({descricao_unitaria}, '')) AS descricao_unitaria
            FROM {}.dprodutos_latest
            GROUP BY codigo
        )
        """
    ).format(sql.Identifier(schema), descricao=descricao_sql, descricao_unitaria=descricao_unitaria_sql)


def _relation_exists(conn: psycopg.Connection[Any], schema: str, relation: str) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT to_regclass(%s) AS relation_name", (f"{schema}.{relation}",))
        row = cur.fetchone() or {}
    return bool(row.get("relation_name"))


def _relation_column_exists(conn: psycopg.Connection[Any], schema: str, relation: str, column: str) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                  AND column_name = %s
            ) AS column_exists
            """,
            (schema, relation, column),
        )
        row = cur.fetchone() or {}
    return bool(row.get("column_exists"))


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        text = str(value or "").strip().replace(".", "").replace(",", ".")
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return 0
