from __future__ import annotations

import csv
import hashlib
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
try:
    from services.report_csv_validation import (
        INADIMPLENCIA_CSV_SPEC,
        build_required_indexes,
        normalize_header_name,
        resolve_csv_files,
        validate_csv_source,
    )
except ModuleNotFoundError:
    from bot_api.services.report_csv_validation import (
        INADIMPLENCIA_CSV_SPEC,
        build_required_indexes,
        normalize_header_name,
        resolve_csv_files,
        validate_csv_source,
    )


NORMALIZED_CODE_HEADERS = {
    "unb",
    "cliente",
    "superv",
    "vendedor",
    "gtevendas",
}

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
class InadimplenciaSummary:
    source_path: str
    file_count: int
    rows: int
    columns: int
    unique_unbs: int
    unique_clientes: int
    unique_pairs: int
    top_unbs: list[tuple[str, int]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InadimplenciaImportService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def summarize_source(self, source_path: Path) -> InadimplenciaSummary:
        self.validate_source(source_path).ensure_valid()
        files = _resolve_csv_files(source_path)
        rows = 0
        columns = 0
        unb_counter: Counter[str] = Counter()
        cliente_counter: Counter[str] = Counter()
        pair_counter: Counter[tuple[str, str]] = Counter()

        for file_path in files:
            with file_path.open("r", encoding="cp1252", newline="") as fp:
                reader = csv.reader(fp, delimiter=";")
                header = next(reader)
                indexes = _required_indexes(header)
                columns = max(columns, len(header))
                for row in reader:
                    if not row or not any(str(value or "").strip() for value in row):
                        continue
                    rows += 1
                    unb = _normalize_code_value(row[indexes["UNB"]])
                    cliente = _normalize_code_value(row[indexes["Cliente"]])
                    unb_counter[unb] += 1
                    cliente_counter[cliente] += 1
                    pair_counter[(unb, cliente)] += 1

        return InadimplenciaSummary(
            source_path=str(source_path),
            file_count=len(files),
            rows=rows,
            columns=columns,
            unique_unbs=len(unb_counter),
            unique_clientes=len(cliente_counter),
            unique_pairs=len(pair_counter),
            top_unbs=unb_counter.most_common(20),
        )

    def validate_source(self, source_path: Path):
        return validate_csv_source(source_path, INADIMPLENCIA_CSV_SPEC)

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        files = _resolve_csv_files(source_path)
        summary = self.summarize_source(source_path)
        batch_date = reference_date or _latest_source_date(files)
        source_hash = _sha256_many(files)

        with self._connect() as conn:
            self._ensure_schema(conn)
            self._replace_dataset_contents(conn, dataset_name="inadimplencia")
            batch_id = self._insert_batch(conn, str(source_path), batch_date, source_hash, summary.rows)
            self._insert_snapshot_rows(conn, files, batch_id)
            self._create_latest_view(conn)
            conn.commit()

        result = summary.to_dict()
        result.update(
            {
                "batch_id": batch_id,
                "reference_date": batch_date.isoformat(),
                "source_hash": source_hash,
                "schema": self.schema,
                "files": [str(file_path) for file_path in files],
                "replaced_previous_batches": True,
            }
        )
        return result

    def refresh_latest_view(self) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        with self._connect() as conn:
            self._ensure_schema(conn)
            self._create_latest_view(conn)
            conn.commit()

        return {"ok": True, "schema": self.schema, "view": f"{self.schema}.inadimplencia_latest"}

    def _ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
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
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.inadimplencia_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        source_file TEXT NOT NULL,
                        unb VARCHAR(16) NOT NULL,
                        cliente VARCHAR(32) NOT NULL,
                        nome TEXT,
                        data_emissao TEXT,
                        data_vencimento TEXT,
                        valor_original TEXT,
                        valor_pendente TEXT,
                        valor_corrigido TEXT,
                        dias TEXT,
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS inadimplencia_snapshot_unb_cliente_idx ON {}.inadimplencia_snapshot (unb, cliente)").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS inadimplencia_snapshot_batch_unb_cliente_idx ON {}.inadimplencia_snapshot (batch_id, unb, cliente)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS inadimplencia_snapshot_batch_idx ON {}.inadimplencia_snapshot (batch_id)").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS inadimplencia_snapshot_nome_trgm_idx
                    ON {}.inadimplencia_snapshot
                    USING gin (
                        (
                            REGEXP_REPLACE(
                                TRANSLATE(LOWER(COALESCE(nome, '')), {source}, {target}),
                                '\\s+',
                                ' ',
                                'g'
                            )
                        ) gin_trgm_ops
                    )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    source=sql.Literal(_ACCENTED_SQL_SOURCE),
                    target=sql.Literal(_ACCENTED_SQL_TARGET),
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS import_batches_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)").format(
                    sql.Identifier(self.schema)
                )
            )

    def _insert_batch(
        self,
        conn: psycopg.Connection[Any],
        source_label: str,
        reference_date: date,
        source_hash: str,
        total_rows: int,
    ) -> int:
        query = sql.SQL(
            """
            INSERT INTO {}.import_batches (dataset_name, source_file, file_hash, reference_date, total_rows)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, ("inadimplencia", source_label, source_hash, reference_date, total_rows))
            row = cur.fetchone()
        return int(row["id"])

    def _insert_snapshot_rows(self, conn: psycopg.Connection[Any], files: list[Path], batch_id: int) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.inadimplencia_snapshot (
                batch_id,
                row_number,
                source_file,
                unb,
                cliente,
                nome,
                data_emissao,
                data_vencimento,
                valor_original,
                valor_pendente,
                valor_corrigido,
                dias,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema))

        next_row_number = 1
        payload_batch: list[tuple[Any, ...]] = []
        with conn.cursor() as cur:
            for file_path in files:
                with file_path.open("r", encoding="cp1252", newline="") as fp:
                    reader = csv.reader(fp, delimiter=";")
                    header = next(reader)
                    indexes = _required_indexes(header)
                    for row in reader:
                        if not row or not any(str(value or "").strip() for value in row):
                            continue
                        record = _row_to_record(header, row)
                        payload_batch.append(
                            (
                                batch_id,
                                next_row_number,
                                str(file_path),
                                _normalize_code_value(row[indexes["UNB"]]),
                                _normalize_code_value(row[indexes["Cliente"]]),
                                row[indexes["Nome"]].strip(),
                                row[indexes["DataEmissao"]].strip(),
                                row[indexes["DataVencto"]].strip(),
                                row[indexes["ValorOriginal"]].strip(),
                                row[indexes["ValorPendente"]].strip(),
                                row[indexes["ValorCorrigido"]].strip(),
                                row[indexes["Dias"]].strip(),
                                Jsonb(record),
                            )
                        )
                        next_row_number += 1
                        if len(payload_batch) >= 1000:
                            cur.executemany(query, payload_batch)
                            payload_batch.clear()
            if payload_batch:
                cur.executemany(query, payload_batch)

    def _replace_dataset_contents(self, conn: psycopg.Connection[Any], dataset_name: str) -> None:
        query = sql.SQL(
            """
            DELETE FROM {}.import_batches
            WHERE dataset_name = %s
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor() as cur:
            cur.execute(query, (dataset_name,))

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        drop_query = sql.SQL("DROP VIEW IF EXISTS {}.inadimplencia_latest").format(sql.Identifier(self.schema))
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.inadimplencia_latest AS
            WITH latest_batch AS (
                SELECT id
                FROM {}.import_batches
                WHERE dataset_name = 'inadimplencia'
                ORDER BY imported_at DESC, id DESC
                LIMIT 1
            )
            SELECT
                s.batch_id,
                s.row_number,
                s.source_file,
                s.unb,
                s.cliente,
                CONCAT(s.unb, '_', s.cliente) AS unb_cliente,
                s.nome,
                s.data_emissao,
                s.data_vencimento,
                s.valor_original,
                s.valor_pendente,
                s.valor_corrigido,
                s.dias,
                s.payload,
                s.imported_at,
                b.reference_date,
                b.source_file AS batch_source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM {}.inadimplencia_snapshot s
            JOIN {}.import_batches b ON b.id = s.batch_id
            JOIN latest_batch lb ON lb.id = s.batch_id
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
        )
        with conn.cursor() as cur:
            cur.execute(drop_query)
            cur.execute(query)

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(
            self.database_url,
            autocommit=False,
            connect_timeout=int(self.connect_timeout_seconds),
        )


def _resolve_csv_files(source_path: Path) -> list[Path]:
    return resolve_csv_files(source_path)


def _latest_source_date(files: list[Path]) -> date:
    latest_timestamp = max(file_path.stat().st_mtime for file_path in files)
    return datetime.fromtimestamp(latest_timestamp).date()


def _required_indexes(header: list[str]) -> dict[str, int]:
    return build_required_indexes(header, INADIMPLENCIA_CSV_SPEC)


def _row_to_record(header: list[str], row: list[str]) -> dict[str, str]:
    record: dict[str, str] = {}
    repeated_counter: Counter[str] = Counter()
    for idx, value in enumerate(row):
        raw_name = header[idx].strip() if idx < len(header) else ""
        key = raw_name or f"col_{idx + 1:03d}"
        repeated_counter[key] += 1
        if repeated_counter[key] > 1:
            key = f"{key}__{repeated_counter[key]}"
        record[key] = _normalize_record_value(raw_name, value)
    return record


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _normalize_record_value(header_name: str, value: str) -> str:
    if normalize_header_name(header_name) in NORMALIZED_CODE_HEADERS:
        return _normalize_code_value(value)
    return str(value or "").strip()


def _normalize_code_value(value: str) -> str:
    stripped = str(value or "").strip()
    if not stripped:
        return ""
    if not stripped.isdigit():
        return stripped
    normalized = stripped.lstrip("0")
    return normalized or "0"


def _sha256_many(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for file_path in files:
        digest.update(str(file_path.name).encode("utf-8"))
        with file_path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()
