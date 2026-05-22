from __future__ import annotations

import csv
import hashlib
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.import_publication import (
    activate_import_batch,
    ensure_dataset_state_table,
    prune_import_batches,
    resolve_effective_import_batch_id,
)


EXPECTED_EXTENSION_SET = {".csv"}
EXPECTED_HEADERS = {
    "UNB",
    "Codigo Cliente",
    "Tipo Documento",
    "Nome Arquivo",
}
DOCUMENT_CODE_TO_FIELD = {
    "CS": "contrato_social",
    "CPF": "cpf",
    "RG": "rg",
    "CR": "comprovante_residencia",
    "FAC": "fachada",
    "FC": "ficha_cadastro",
}
FIELD_TO_LABEL = {
    "contrato_social": "Contrato Social",
    "cpf": "Cpf",
    "rg": "Rg",
    "comprovante_residencia": "Comprovante de residencia",
    "fachada": "Fachada",
    "ficha_cadastro": "Ficha de Cadastro",
}
OK_ELIGIBLE_FIELDS = (
    "contrato_social",
    "cpf",
    "rg",
    "comprovante_residencia",
    "fachada",
)
STATUS_OK = "OK"
STATUS_NOK = "Nok"


@dataclass(frozen=True)
class DocumentacaoPendenteValidationResult:
    dataset_name: str
    source_path: str
    ok: bool
    total_rows: int
    unique_keys: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError("; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao da documentacao pendente.")


@dataclass(frozen=True)
class DocumentacaoPendenteImportSummary:
    source_path: str
    rows: int
    unique_clientes: int
    pending_clients: int
    pending_documents: int
    contrato_social_pendentes: int
    cpf_pendentes: int
    rg_pendentes: int
    comprovante_residencia_pendentes: int
    fachada_pendentes: int
    ficha_cadastro_pendentes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentacaoPendenteRow:
    filial: str
    cod_pdv: str
    chave: str
    contrato_social: str
    cpf: str
    rg: str
    comprovante_residencia: str
    fachada: str
    ficha_cadastro: str
    pending_count: int
    pending_docs: tuple[str, ...]
    source_row_number: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "filial": self.filial,
            "cod_pdv": self.cod_pdv,
            "chave": self.chave,
            "contrato_social": self.contrato_social,
            "cpf": self.cpf,
            "rg": self.rg,
            "comprovante_residencia": self.comprovante_residencia,
            "fachada": self.fachada,
            "ficha_cadastro": self.ficha_cadastro,
            "pending_count": self.pending_count,
            "pending_docs": list(self.pending_docs),
            "source_row_number": self.source_row_number,
        }


class DocumentacaoPendenteImportService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def validate_source(self, source_path: Path) -> DocumentacaoPendenteValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings_list: list[str] = []
        rows: list[DocumentacaoPendenteRow] = []

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                rows = _load_documentacao_rows(path)
            except Exception as exc:
                errors.append(str(exc))

        if not rows and not errors:
            errors.append("Nao encontrei linhas validas no CSV de documentacao pendente.")

        return DocumentacaoPendenteValidationResult(
            dataset_name="documentacao_pendente",
            source_path=str(path),
            ok=not errors,
            total_rows=len(rows),
            unique_keys=len({row.chave for row in rows}),
            error_count=len(errors),
            warning_count=len(warnings_list),
            sample_errors=errors[:10],
            sample_warnings=warnings_list[:10],
        )

    def summarize_source(self, source_path: Path) -> DocumentacaoPendenteImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        rows = _load_documentacao_rows(source_path.expanduser().resolve())
        return DocumentacaoPendenteImportSummary(
            source_path=str(source_path),
            rows=len(rows),
            unique_clientes=len({(row.filial, row.cod_pdv) for row in rows}),
            pending_clients=sum(1 for row in rows if row.pending_count > 0),
            pending_documents=sum(row.pending_count for row in rows),
            contrato_social_pendentes=sum(1 for row in rows if row.contrato_social == STATUS_NOK),
            cpf_pendentes=sum(1 for row in rows if row.cpf == STATUS_NOK),
            rg_pendentes=sum(1 for row in rows if row.rg == STATUS_NOK),
            comprovante_residencia_pendentes=sum(1 for row in rows if row.comprovante_residencia == STATUS_NOK),
            fachada_pendentes=sum(1 for row in rows if row.fachada == STATUS_NOK),
            ficha_cadastro_pendentes=sum(1 for row in rows if row.ficha_cadastro == STATUS_NOK),
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        summary = self.summarize_source(path)
        rows = _load_documentacao_rows(path)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_snapshot_rows(conn, rows, batch_id)
            activate_import_batch(conn, self.schema, "documentacao_pendente", batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, "documentacao_pendente", keep_last=3)
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
            active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "documentacao_pendente", activate_if_missing=True)
            self._create_latest_view(conn)
            conn.commit()

        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.documentacao_pendente_latest",
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
                    CREATE TABLE IF NOT EXISTS {}.documentacao_pendente_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        filial VARCHAR(16) NOT NULL,
                        cod_pdv VARCHAR(32) NOT NULL,
                        chave TEXT NOT NULL,
                        contrato_social VARCHAR(8) NOT NULL,
                        cpf VARCHAR(8) NOT NULL,
                        rg VARCHAR(8) NOT NULL,
                        comprovante_residencia VARCHAR(8) NOT NULL,
                        fachada VARCHAR(8) NOT NULL,
                        ficha_cadastro VARCHAR(8) NOT NULL,
                        pending_count INTEGER NOT NULL,
                        pending_docs JSONB NOT NULL,
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS documentacao_pendente_snapshot_batch_filial_cod_idx ON {}.documentacao_pendente_snapshot (batch_id, filial, cod_pdv)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS documentacao_pendente_snapshot_batch_pending_idx ON {}.documentacao_pendente_snapshot (batch_id, pending_count)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS import_batches_documentacao_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)"
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
            VALUES ('documentacao_pendente', %s, %s, %s, %s)
            RETURNING id
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (source_file, file_hash, reference_date, total_rows))
            row = cur.fetchone()
        return int(row["id"])

    def _insert_snapshot_rows(
        self,
        conn: psycopg.Connection[Any],
        rows: list[DocumentacaoPendenteRow],
        batch_id: int,
    ) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.documentacao_pendente_snapshot (
                batch_id,
                row_number,
                filial,
                cod_pdv,
                chave,
                contrato_social,
                cpf,
                rg,
                comprovante_residencia,
                fachada,
                ficha_cadastro,
                pending_count,
                pending_docs,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema))
        params = [
            (
                batch_id,
                index,
                row.filial,
                row.cod_pdv,
                row.chave,
                row.contrato_social,
                row.cpf,
                row.rg,
                row.comprovante_residencia,
                row.fachada,
                row.ficha_cadastro,
                row.pending_count,
                Jsonb(list(row.pending_docs)),
                Jsonb(row.to_payload()),
            )
            for index, row in enumerate(rows, start=1)
        ]
        with conn.cursor() as cur:
            cur.executemany(query, params)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "documentacao_pendente", activate_if_missing=True)
        where_clause = sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id)) if active_batch_id is not None else sql.SQL("FALSE")
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.documentacao_pendente_latest AS
            SELECT
                s.batch_id,
                s.row_number,
                s.filial,
                s.cod_pdv,
                s.chave,
                s.contrato_social,
                s.cpf,
                s.rg,
                s.comprovante_residencia,
                s.fachada,
                s.ficha_cadastro,
                s.pending_count,
                s.pending_docs,
                s.payload,
                s.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM {}.documentacao_pendente_snapshot s
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


def _load_documentacao_rows(path: Path) -> list[DocumentacaoPendenteRow]:
    header_map: dict[str, str] = {}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    with path.open("r", encoding="cp1252", newline="") as fp:
        reader = csv.DictReader(fp, delimiter=";")
        if reader.fieldnames is None:
            raise ValueError("CSV sem cabecalho.")
        fieldnames = [str(name or "").strip() for name in reader.fieldnames]
        present_headers = {name for name in fieldnames if name}
        missing_headers = sorted(EXPECTED_HEADERS - present_headers)
        if missing_headers:
            raise ValueError(f"CSV invalido. Colunas obrigatorias ausentes: {', '.join(missing_headers)}")
        header_map = {name: name for name in fieldnames if name}

        for source_row_number, raw_row in enumerate(reader, start=2):
            row = {str(key or "").strip(): str(value or "").strip() for key, value in raw_row.items() if key is not None}
            if not any(row.values()):
                continue
            filial = normalize_numeric_code(row.get(header_map["UNB"], ""))
            cod_pdv = normalize_numeric_code(row.get(header_map["Codigo Cliente"], ""))
            if not filial or not cod_pdv:
                continue
            doc_code = str(row.get(header_map["Tipo Documento"], "")).split(" -", 1)[0].strip().upper()
            if doc_code not in DOCUMENT_CODE_TO_FIELD:
                continue
            status = _normalize_status(row.get(header_map["Nome Arquivo"], ""))
            key = (filial, cod_pdv)
            if key not in grouped:
                grouped[key] = {
                    "filial": filial,
                    "cod_pdv": cod_pdv,
                    "chave": f"{filial}_{cod_pdv}",
                    "contrato_social": STATUS_NOK,
                    "cpf": STATUS_NOK,
                    "rg": STATUS_NOK,
                    "comprovante_residencia": STATUS_NOK,
                    "fachada": STATUS_NOK,
                    "ficha_cadastro": STATUS_NOK,
                    "source_row_number": source_row_number,
                    "_seen_docs": set(),
                }
            target = grouped[key]
            if doc_code in target["_seen_docs"]:
                continue
            target["_seen_docs"].add(doc_code)
            target[DOCUMENT_CODE_TO_FIELD[doc_code]] = status

    rows: list[DocumentacaoPendenteRow] = []
    for item in sorted(grouped.values(), key=lambda value: (_sort_numeric(value["filial"]), _sort_numeric(value["cod_pdv"]))):
        pending_docs = tuple(
            FIELD_TO_LABEL[field_name]
            for field_name in OK_ELIGIBLE_FIELDS
            if item[field_name] == STATUS_NOK
        )
        rows.append(
            DocumentacaoPendenteRow(
                filial=item["filial"],
                cod_pdv=item["cod_pdv"],
                chave=item["chave"],
                contrato_social=item["contrato_social"],
                cpf=item["cpf"],
                rg=item["rg"],
                comprovante_residencia=item["comprovante_residencia"],
                fachada=item["fachada"],
                ficha_cadastro=item["ficha_cadastro"],
                pending_count=len(pending_docs),
                pending_docs=pending_docs,
                source_row_number=int(item["source_row_number"]),
            )
        )
    return rows


def _normalize_status(value: str) -> str:
    cleaned = _normalize_text(value)
    if cleaned in {
        _normalize_text("Documento não Encontrado"),
        _normalize_text("Documento nao Encontrado"),
        _normalize_text("Documento nÃ£o Encontrado"),
    }:
        return STATUS_NOK
    return STATUS_OK


def _normalize_text(value: str) -> str:
    lowered = str(value or "").strip().lower()
    return "".join(
        char for char in unicodedata.normalize("NFD", lowered) if unicodedata.category(char) != "Mn"
    )


def _sort_numeric(value: str) -> tuple[int, str]:
    normalized = normalize_numeric_code(value)
    if normalized.isdigit():
        return (int(normalized), normalized)
    return (10**9, normalized)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"
