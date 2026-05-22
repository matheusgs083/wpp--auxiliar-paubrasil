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
        DSETORES_CSV_SPEC,
        build_required_indexes,
        validate_csv_source,
    )
    from services.import_publication import (
        activate_import_batch,
        ensure_dataset_state_table,
        prune_import_batches,
        resolve_effective_import_batch_id,
    )
except ModuleNotFoundError:
    from bot_api.services.report_csv_validation import (
        DSETORES_CSV_SPEC,
        build_required_indexes,
        validate_csv_source,
    )
    from bot_api.services.import_publication import (
        activate_import_batch,
        ensure_dataset_state_table,
        prune_import_batches,
        resolve_effective_import_batch_id,
    )

from bot_api.commercial_scope import normalize_numeric_code


@dataclass(frozen=True)
class DSetoresSummary:
    source_path: str
    file_count: int
    rows: int
    columns: int
    unique_filiais: int
    unique_dcs: int
    unique_gvs: int
    unique_setores: int
    unique_filial_setores: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DSetoresImportService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def validate_csv(self, source_path: Path):
        return validate_csv_source(source_path, DSETORES_CSV_SPEC)

    def summarize_csv(self, source_path: Path) -> DSetoresSummary:
        self.validate_csv(source_path).ensure_valid()
        files = _resolve_csv_files(source_path)
        rows = 0
        columns = 0
        filial_counter: Counter[str] = Counter()
        dc_counter: Counter[str] = Counter()
        gv_counter: Counter[str] = Counter()
        setor_counter: Counter[str] = Counter()
        filial_setor_counter: Counter[tuple[str, str]] = Counter()

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
                    filial = normalize_numeric_code(row[indexes["Filial"]])
                    dc = normalize_numeric_code(row[indexes["Dc"]])
                    gv = normalize_numeric_code(row[indexes["Gv"]])
                    setor = normalize_numeric_code(row[indexes["Setor"]])
                    filial_counter[filial] += 1
                    dc_counter[dc] += 1
                    gv_counter[gv] += 1
                    setor_counter[setor] += 1
                    filial_setor_counter[(filial, setor)] += 1

        return DSetoresSummary(
            source_path=str(source_path),
            file_count=len(files),
            rows=rows,
            columns=columns,
            unique_filiais=len([item for item in filial_counter if item]),
            unique_dcs=len([item for item in dc_counter if item]),
            unique_gvs=len([item for item in gv_counter if item]),
            unique_setores=len([item for item in setor_counter if item]),
            unique_filial_setores=len([item for item in filial_setor_counter if all(item)]),
        )

    def import_csv(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        files = _resolve_csv_files(source_path)
        summary = self.summarize_csv(source_path)
        batch_date = reference_date or _latest_source_date(files)
        source_hash = _sha256_many(files)

        with self._connect() as conn:
            ensure_dsetores_schema(conn, self.schema)
            batch_id = self._insert_batch(conn, str(source_path), batch_date, source_hash, summary.rows)
            self._insert_snapshot_rows(conn, files, batch_id)
            activate_import_batch(conn, self.schema, "dsetores", batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, "dsetores", keep_last=3)
            conn.commit()

        result = summary.to_dict()
        result.update(
            {
                "batch_id": batch_id,
                "reference_date": batch_date.isoformat(),
                "source_hash": source_hash,
                "schema": self.schema,
                "files": [str(file_path) for file_path in files],
                "replaced_previous_batches": False,
                "published_as_active_batch": True,
            }
        )
        return result

    def refresh_latest_view(self) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        with self._connect() as conn:
            ensure_dsetores_schema(conn, self.schema)
            active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dsetores", activate_if_missing=True)
            self._create_latest_view(conn)
            conn.commit()

        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.dsetores_latest",
            "active_batch_id": active_batch_id,
        }

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
            cur.execute(query, ("dsetores", source_label, source_hash, reference_date, total_rows))
            row = cur.fetchone()
        return int(row["id"])

    def _insert_snapshot_rows(self, conn: psycopg.Connection[Any], files: list[Path], batch_id: int) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.dsetores_snapshot (
                batch_id,
                row_number,
                source_file,
                filial,
                dc,
                gv,
                setor,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema))

        row_number = 0
        with conn.cursor() as cur:
            for file_path in files:
                with file_path.open("r", encoding="cp1252", newline="") as fp:
                    reader = csv.reader(fp, delimiter=";")
                    header = next(reader)
                    indexes = _required_indexes(header)
                    payload_batch: list[tuple[Any, ...]] = []
                    for row in reader:
                        if not row or not any(str(value or "").strip() for value in row):
                            continue
                        row_number += 1
                        payload_batch.append(
                            (
                                batch_id,
                                row_number,
                                str(file_path),
                                normalize_numeric_code(row[indexes["Filial"]]),
                                normalize_numeric_code(row[indexes["Dc"]]),
                                normalize_numeric_code(row[indexes["Gv"]]),
                                normalize_numeric_code(row[indexes["Setor"]]),
                                Jsonb(_row_to_record(header, row)),
                            )
                        )
                        if len(payload_batch) >= 1000:
                            cur.executemany(query, payload_batch)
                            payload_batch.clear()

                    if payload_batch:
                        cur.executemany(query, payload_batch)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dsetores", activate_if_missing=True)
        where_clause = (
            sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id))
            if active_batch_id is not None
            else sql.SQL("FALSE")
        )
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.dsetores_latest AS
            SELECT
                s.batch_id,
                s.row_number,
                s.filial,
                s.dc,
                s.gv,
                s.setor,
                CONCAT(s.filial, '_', s.setor) AS filial_setor_key,
                CONCAT(s.filial, '_', s.gv) AS filial_gv_key,
                CONCAT(s.filial, '_', s.dc) AS filial_dc_key,
                s.payload,
                s.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM {}.dsetores_snapshot s
            JOIN {}.import_batches b ON b.id = s.batch_id
            WHERE {}
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            where_clause,
        )
        with conn.cursor() as cur:
            cur.execute(query)

    def _replace_dataset_contents(self, conn: psycopg.Connection[Any], dataset_name: str) -> None:
        query = sql.SQL(
            """
            DELETE FROM {}.import_batches
            WHERE dataset_name = %s
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor() as cur:
            cur.execute(query, (dataset_name,))

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(
            self.database_url,
            autocommit=False,
            connect_timeout=int(self.connect_timeout_seconds),
        )


def ensure_dsetores_schema(conn: psycopg.Connection[Any], schema: str) -> None:
    normalized_schema = _normalize_schema(schema)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(normalized_schema)))
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
            ).format(sql.Identifier(normalized_schema))
        )
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.dsetores_snapshot (
                    batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                    row_number BIGINT NOT NULL,
                    source_file TEXT NOT NULL,
                    filial VARCHAR(16) NOT NULL,
                    dc VARCHAR(32) NOT NULL,
                    gv VARCHAR(32) NOT NULL,
                    setor VARCHAR(32) NOT NULL,
                    payload JSONB NOT NULL,
                    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (batch_id, row_number),
                    UNIQUE (batch_id, filial, setor)
                )
                """
            ).format(sql.Identifier(normalized_schema), sql.Identifier(normalized_schema))
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS dsetores_snapshot_batch_filial_setor_idx ON {}.dsetores_snapshot (batch_id, filial, setor)"
            ).format(sql.Identifier(normalized_schema))
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS dsetores_snapshot_batch_filial_gv_idx ON {}.dsetores_snapshot (batch_id, filial, gv)"
            ).format(sql.Identifier(normalized_schema))
        )
        cur.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS dsetores_snapshot_batch_filial_dc_idx ON {}.dsetores_snapshot (batch_id, filial, dc)"
            ).format(sql.Identifier(normalized_schema))
        )
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS import_batches_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)").format(
                sql.Identifier(normalized_schema)
            )
        )
        ensure_dataset_state_table(conn, normalized_schema)
        active_batch_id = resolve_effective_import_batch_id(conn, normalized_schema, "dsetores", activate_if_missing=True)
        where_clause = (
            sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id))
            if active_batch_id is not None
            else sql.SQL("FALSE")
        )
        cur.execute(
            sql.SQL(
                """
                CREATE OR REPLACE VIEW {}.dsetores_latest AS
                SELECT
                    s.batch_id,
                    s.row_number,
                    s.filial,
                    s.dc,
                    s.gv,
                    s.setor,
                    CONCAT(s.filial, '_', s.setor) AS filial_setor_key,
                    CONCAT(s.filial, '_', s.gv) AS filial_gv_key,
                    CONCAT(s.filial, '_', s.dc) AS filial_dc_key,
                    s.payload,
                    s.imported_at,
                    b.reference_date,
                    b.source_file,
                    b.file_hash,
                    b.imported_at AS batch_imported_at
                FROM {}.dsetores_snapshot s
                JOIN {}.import_batches b ON b.id = s.batch_id
                WHERE {}
                """
            ).format(
                sql.Identifier(normalized_schema),
                sql.Identifier(normalized_schema),
                sql.Identifier(normalized_schema),
                where_clause,
            )
        )


def _required_indexes(header: list[str]) -> dict[str, int]:
    return build_required_indexes(header, DSETORES_CSV_SPEC)


def _resolve_csv_files(source_path: Path) -> list[Path]:
    path = source_path.expanduser().resolve()
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(f"Caminho nao encontrado: {source_path}")
    files = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".csv")
    if not files:
        raise FileNotFoundError(f"Nao encontrei arquivos CSV em: {source_path}")
    return files


def _row_to_record(header: list[str], row: list[str]) -> dict[str, str]:
    record: dict[str, str] = {}
    for index, value in enumerate(row):
        key = str(header[index] if index < len(header) else f"col_{index + 1:03d}").strip() or f"col_{index + 1:03d}"
        record[key] = str(value or "").strip()
    return record


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _sha256_many(files: list[Path]) -> str:
    digest = hashlib.sha256()
    for file_path in files:
        digest.update(file_path.name.encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _latest_source_date(files: list[Path]) -> date:
    latest_timestamp = max(datetime.fromtimestamp(file_path.stat().st_mtime) for file_path in files)
    return latest_timestamp.date()
