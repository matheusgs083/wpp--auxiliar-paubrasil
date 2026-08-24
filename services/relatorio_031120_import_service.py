from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from bot_api.services.import_publication import (
    activate_import_batch,
    ensure_dataset_state_table,
    prune_import_batches,
    resolve_effective_import_batch_id,
)


EXPECTED_EXTENSION_SET = {".csv"}


@dataclass(frozen=True)
class Relatorio031120ValidationResult:
    dataset_name: str
    source_path: str
    ok: bool
    total_rows: int
    total_columns: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError("; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao da 031120.")


@dataclass(frozen=True)
class Relatorio031120ImportSummary:
    source_path: str
    rows: int
    total_columns: int
    filial: str
    filial_nome: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Relatorio031120ImportService:
    def __init__(
        self,
        *,
        database_url: str,
        schema: str,
        dataset_name: str,
        expected_filial: str,
        filial_nome: str = "",
        display_name: str = "031120",
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.dataset_name = str(dataset_name or "").strip()
        self.expected_filial = str(expected_filial or "").strip()
        self.filial_nome = str(filial_nome or "").strip()
        self.display_name = str(display_name or "031120").strip()
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        if not self.dataset_name:
            raise ValueError(f"dataset_name obrigatorio para {self.display_name}.")
        if not self.expected_filial:
            raise ValueError(f"expected_filial obrigatoria para {self.display_name}.")

    def validate_source(self, source_path: Path) -> Relatorio031120ValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings: list[str] = []
        rows: list[dict[str, str]] = []
        headers: list[str] = []

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                headers, rows = _read_csv_rows(path)
            except Exception as exc:
                errors.append(str(exc))

        if not rows and not errors:
            errors.append(f"Nao encontrei linhas validas no CSV da {self.display_name}.")
        if not headers and not errors:
            errors.append(f"Nao encontrei cabecalho no CSV da {self.display_name}.")

        return Relatorio031120ValidationResult(
            dataset_name=self.dataset_name,
            source_path=str(path),
            ok=not errors,
            total_rows=len(rows),
            total_columns=len(headers),
            error_count=len(errors),
            warning_count=len(warnings),
            sample_errors=errors[:10],
            sample_warnings=warnings[:10],
        )

    def summarize_source(self, source_path: Path) -> Relatorio031120ImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        headers, rows = _read_csv_rows(source_path.expanduser().resolve())
        return Relatorio031120ImportSummary(
            source_path=str(source_path),
            rows=len(rows),
            total_columns=len(headers),
            filial=self.expected_filial,
            filial_nome=self.filial_nome,
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        summary = self.summarize_source(path)
        headers, rows = _read_csv_rows(path)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_report(conn, batch_id, path.name, headers, len(rows))
            self._insert_rows(conn, batch_id, rows)
            activate_import_batch(conn, self.schema, self.dataset_name, batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, self.dataset_name, keep_last=3)
            conn.commit()

        result = summary.to_dict()
        result.update(
            {
                "batch_id": batch_id,
                "reference_date": batch_date.isoformat(),
                "source_hash": source_hash,
                "schema": self.schema,
                "replaced_previous_batches": False,
                "published_as_active_batch": True,
            }
        )
        return result

    def refresh_latest_view(self) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        with self._connect() as conn:
            self._ensure_schema(conn)
            active_batch_id = resolve_effective_import_batch_id(conn, self.schema, self.dataset_name, activate_if_missing=True)
            self._create_latest_view(conn)
            conn.commit()
        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.relatorio_031120_latest",
            "active_batch_id": active_batch_id,
        }

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
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.relatorio_031120_reports (
                        batch_id BIGINT PRIMARY KEY REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        dataset_name VARCHAR(80) NOT NULL,
                        filial VARCHAR(16) NOT NULL,
                        filial_nome TEXT NOT NULL DEFAULT '',
                        filename TEXT NOT NULL,
                        headers JSONB NOT NULL DEFAULT '[]'::jsonb,
                        total_rows INTEGER NOT NULL DEFAULT 0,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.relatorio_031120_rows (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        dataset_name VARCHAR(80) NOT NULL,
                        filial VARCHAR(16) NOT NULL,
                        payload JSONB NOT NULL,
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS relatorio_031120_reports_dataset_idx ON {}.relatorio_031120_reports (dataset_name, imported_at DESC)").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS relatorio_031120_rows_dataset_filial_idx ON {}.relatorio_031120_rows (dataset_name, filial)").format(
                    sql.Identifier(self.schema)
                )
            )
            ensure_dataset_state_table(conn, self.schema)

    def _insert_batch(self, conn: psycopg.Connection[Any], source_file: str, reference_date: date, source_hash: str, rows: int) -> int:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.import_batches (dataset_name, source_file, file_hash, reference_date, total_rows)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """
                ).format(sql.Identifier(self.schema)),
                (self.dataset_name, source_file, source_hash, reference_date, rows),
            )
            return int(cur.fetchone()[0])

    def _insert_report(self, conn: psycopg.Connection[Any], batch_id: int, filename: str, headers: list[str], rows: int) -> None:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.relatorio_031120_reports (
                        batch_id, dataset_name, filial, filial_nome, filename, headers, total_rows
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """
                ).format(sql.Identifier(self.schema)),
                (batch_id, self.dataset_name, self.expected_filial, self.filial_nome, filename, Jsonb(headers), rows),
            )

    def _insert_rows(self, conn: psycopg.Connection[Any], batch_id: int, rows: list[dict[str, str]]) -> None:
        values = [
            (batch_id, idx, self.dataset_name, self.expected_filial, Jsonb(row))
            for idx, row in enumerate(rows, start=1)
        ]
        with conn.cursor() as cur:
            cur.executemany(
                sql.SQL(
                    """
                    INSERT INTO {}.relatorio_031120_rows (batch_id, row_number, dataset_name, filial, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    """
                ).format(sql.Identifier(self.schema)),
                values,
            )

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    CREATE OR REPLACE VIEW {}.relatorio_031120_latest AS
                    SELECT r.*
                    FROM {}.relatorio_031120_reports r
                    JOIN {}.dataset_state s
                      ON s.dataset_name = r.dataset_name
                     AND s.active_batch_id = r.batch_id
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema), sql.Identifier(self.schema))
            )

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    raw_bytes = path.read_bytes()
    text = _decode_csv(raw_bytes)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
    else:
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [str(header or "").strip() for header in (reader.fieldnames or [])]
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {str(key or "").strip(): str(value or "").strip() for key, value in row.items() if key is not None}
        if any(value for value in cleaned.values()):
            rows.append(cleaned)
    return headers, rows


def _decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_schema(value: str) -> str:
    cleaned = (value or "reports").strip()
    if not cleaned.replace("_", "").isalnum():
        raise ValueError(f"Schema invalido: {value!r}")
    return cleaned
