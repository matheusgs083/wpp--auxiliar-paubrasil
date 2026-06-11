from __future__ import annotations

import csv
import hashlib
import io
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.import_publication import (
    activate_import_batch,
    ensure_dataset_state_table,
    prune_import_batches,
    resolve_effective_import_batch_id,
)


EXPECTED_EXTENSION_SET = {".csv"}
REQUIRED_HEADERS = {"filial", "condicao_codigo", "descricao"}
OPTIONAL_HEADERS = {"forma_pagto"}
HEADER_ALIASES = {
    "filial": "filial",
    "condicaodepagto": "condicao_codigo",
    "condicaodepagamento": "condicao_codigo",
    "codicaodepagto": "condicao_codigo",
    "codigo": "condicao_codigo",
    "descricao": "descricao",
    "formadepagto": "forma_pagto",
    "formadepagamento": "forma_pagto",
}


@dataclass(frozen=True)
class DCondicoesValidationResult:
    dataset_name: str
    source_path: str
    ok: bool
    total_rows: int
    unique_filiais: int
    unique_condicoes: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError("; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao da tabela de condicoes.")


@dataclass(frozen=True)
class DCondicoesImportSummary:
    source_path: str
    rows: int
    unique_filiais: int
    unique_condicoes: int
    unique_descricoes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DCondicoesRow:
    filial: str
    condicao_codigo: str
    descricao: str
    forma_pagto: str
    filial_condicao_key: str
    source_row_number: int


class DCondicoesImportService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def validate_source(self, source_path: Path) -> DCondicoesValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings_list: list[str] = []
        rows: list[DCondicoesRow] = []

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                rows = _load_dcondicoes_rows(path)
            except Exception as exc:
                errors.append(str(exc))

        if not rows and not errors:
            errors.append("Nao encontrei linhas validas na tabela de condicoes.")

        return DCondicoesValidationResult(
            dataset_name="dcondicoes",
            source_path=str(path),
            ok=not errors,
            total_rows=len(rows),
            unique_filiais=len({row.filial for row in rows}),
            unique_condicoes=len({row.filial_condicao_key for row in rows}),
            error_count=len(errors),
            warning_count=len(warnings_list),
            sample_errors=errors[:10],
            sample_warnings=warnings_list[:10],
        )

    def summarize_source(self, source_path: Path) -> DCondicoesImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        rows = _load_dcondicoes_rows(source_path.expanduser().resolve())
        return DCondicoesImportSummary(
            source_path=str(source_path),
            rows=len(rows),
            unique_filiais=len({row.filial for row in rows}),
            unique_condicoes=len({row.filial_condicao_key for row in rows}),
            unique_descricoes=len({row.descricao for row in rows}),
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        summary = self.summarize_source(path)
        rows = _load_dcondicoes_rows(path)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_snapshot_rows(conn, rows, batch_id)
            activate_import_batch(conn, self.schema, "dcondicoes", batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, "dcondicoes", keep_last=3)
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
            active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dcondicoes", activate_if_missing=True)
            self._create_latest_view(conn)
            conn.commit()

        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.dcondicoes_latest",
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
                    CREATE TABLE IF NOT EXISTS {}.dcondicoes_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        filial VARCHAR(32) NOT NULL,
                        condicao_codigo VARCHAR(32) NOT NULL,
                        descricao TEXT NOT NULL,
                        forma_pagto TEXT NOT NULL DEFAULT '',
                        filial_condicao_key VARCHAR(80) NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dcondicoes_snapshot_batch_key_idx ON {}.dcondicoes_snapshot (batch_id, filial_condicao_key)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dcondicoes_snapshot_batch_filial_idx ON {}.dcondicoes_snapshot (batch_id, filial)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS import_batches_dcondicoes_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)"
                ).format(sql.Identifier(self.schema))
            )
            ensure_dataset_state_table(conn, self.schema)

    def _insert_batch(
        self,
        conn: psycopg.Connection[Any],
        source_file: str,
        reference_date: date,
        file_hash: str,
        total_rows: int,
    ) -> int:
        query = sql.SQL(
            """
            INSERT INTO {}.import_batches (dataset_name, source_file, file_hash, reference_date, total_rows)
            VALUES ('dcondicoes', %s, %s, %s, %s)
            RETURNING id
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (source_file, file_hash, reference_date, total_rows))
            row = cur.fetchone()
        return int(row["id"])

    def _insert_snapshot_rows(self, conn: psycopg.Connection[Any], rows: list[DCondicoesRow], batch_id: int) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.dcondicoes_snapshot (
                batch_id,
                row_number,
                filial,
                condicao_codigo,
                descricao,
                forma_pagto,
                filial_condicao_key
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema))
        params = [
            (
                batch_id,
                index,
                row.filial,
                row.condicao_codigo,
                row.descricao,
                row.forma_pagto,
                row.filial_condicao_key,
            )
            for index, row in enumerate(rows, start=1)
        ]
        with conn.cursor() as cur:
            cur.executemany(query, params)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dcondicoes", activate_if_missing=True)
        where_clause = sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id)) if active_batch_id is not None else sql.SQL("FALSE")
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.dcondicoes_latest AS
            SELECT
                s.batch_id,
                s.row_number,
                s.filial,
                s.condicao_codigo,
                s.descricao,
                s.forma_pagto,
                s.filial_condicao_key,
                s.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM {}.dcondicoes_snapshot s
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

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)


def _load_dcondicoes_rows(path: Path) -> list[DCondicoesRow]:
    text = _read_text_with_fallback(path)
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if reader.fieldnames is None:
        raise ValueError("Arquivo sem cabecalho.")

    headers = [str(header or "").strip() for header in reader.fieldnames]
    header_map = _build_header_map(headers)
    rows: list[DCondicoesRow] = []
    for row_number, raw_row in enumerate(reader, start=2):
        row = {str(key or "").strip(): str(value or "").strip() for key, value in raw_row.items() if key is not None}
        if not any(str(value or "").strip() for value in row.values()):
            continue
        filial = normalize_numeric_code(row.get(header_map["filial"], ""))
        condicao_codigo = normalize_numeric_code(row.get(header_map["condicao_codigo"], ""))
        descricao = _clean_text(row.get(header_map["descricao"], ""))
        if not filial or not condicao_codigo or not descricao:
            continue
        rows.append(
            DCondicoesRow(
                filial=filial,
                condicao_codigo=condicao_codigo,
                descricao=descricao,
                forma_pagto=_clean_text(row.get(header_map.get("forma_pagto", ""), "")),
                filial_condicao_key=f"{filial}_{condicao_codigo}",
                source_row_number=row_number,
            )
        )
    rows.sort(key=lambda item: (_sort_numeric(item.filial), _sort_numeric(item.condicao_codigo), item.source_row_number))
    return rows


def _build_header_map(headers: list[str]) -> dict[str, str]:
    header_map: dict[str, str] = {}
    for actual in headers:
        normalized = _normalize_header(actual)
        canonical = HEADER_ALIASES.get(normalized)
        if canonical and canonical not in header_map:
            header_map[canonical] = actual
    missing_headers = sorted(REQUIRED_HEADERS - set(header_map))
    if missing_headers:
        raise ValueError(f"Arquivo invalido. Colunas obrigatorias ausentes: {', '.join(missing_headers)}")
    return {key: value for key, value in header_map.items() if key in REQUIRED_HEADERS or key in OPTIONAL_HEADERS}


def _read_text_with_fallback(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Nao consegui ler o arquivo com um encoding suportado.")


def _normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return "".join(char for char in ascii_only.lower() if char.isalnum())


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sort_numeric(value: str) -> tuple[int, str]:
    normalized = normalize_numeric_code(value)
    if normalized:
        try:
            return (0, f"{int(normalized):09d}")
        except ValueError:
            return (1, normalized)
    return (2, str(value or "").strip())
