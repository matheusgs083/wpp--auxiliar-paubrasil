from __future__ import annotations

import csv
import hashlib
import io
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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
    "Codigo",
    "Cliente",
    "RazaoSocial",
    "Filial",
    "Score",
    "PctAtrasoHistorico",
    "TitulosHistorico",
    "RecebidoHistorico",
    "MaiorAtrasoDias",
    "VezesMais30d",
    "TarifaPaga",
    "JurosPagos",
    "EmAbertoHoje",
    "VencidoHoje",
    "DiasVencidoMaisAntigo",
}
OPTIONAL_HEADERS = {"Piorando2026"}
HEADER_ALIASES = {
    "codigo": "Codigo",
    "cliente": "Cliente",
    "razaosocial": "RazaoSocial",
    "filial": "Filial",
    "score": "Score",
    "piorando2026": "Piorando2026",
    "pctatrasohistorico": "PctAtrasoHistorico",
    "tituloshistorico": "TitulosHistorico",
    "recebidohistorico": "RecebidoHistorico",
    "maioratrasodias": "MaiorAtrasoDias",
    "vezesmais30d": "VezesMais30d",
    "tarifapaga": "TarifaPaga",
    "jurospagos": "JurosPagos",
    "emabertohoje": "EmAbertoHoje",
    "vencidohoje": "VencidoHoje",
    "diasvencidomaisantigo": "DiasVencidoMaisAntigo",
}


@dataclass(frozen=True)
class ClientesScoreValidationResult:
    dataset_name: str
    source_path: str
    ok: bool
    total_rows: int
    unique_clientes: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError("; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao do score de clientes.")


@dataclass(frozen=True)
class ClientesScoreImportSummary:
    source_path: str
    rows: int
    unique_clientes: int
    unique_filiais: int
    duplicate_clientes: int
    score_counts: list[tuple[str, int]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClienteScoreRow:
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
    source_row_number: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "filial": self.filial,
            "cod_pdv": self.cod_pdv,
            "cliente": self.cliente,
            "razao_social": self.razao_social,
            "score": self.score,
            "piorando_2026": self.piorando_2026,
            "pct_atraso_historico": _decimal_to_json(self.pct_atraso_historico),
            "titulos_historico": self.titulos_historico,
            "recebido_historico": _decimal_to_json(self.recebido_historico),
            "maior_atraso_dias": self.maior_atraso_dias,
            "vezes_mais_30d": self.vezes_mais_30d,
            "tarifa_paga": _decimal_to_json(self.tarifa_paga),
            "juros_pagos": _decimal_to_json(self.juros_pagos),
            "em_aberto_hoje": _decimal_to_json(self.em_aberto_hoje),
            "vencido_hoje": _decimal_to_json(self.vencido_hoje),
            "dias_vencido_mais_antigo": self.dias_vencido_mais_antigo,
            "source_row_number": self.source_row_number,
        }


class ClientesScoreImportService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def validate_source(self, source_path: Path) -> ClientesScoreValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings_list: list[str] = []
        rows: list[ClienteScoreRow] = []

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                rows = _load_clientes_score_rows(path)
            except Exception as exc:
                errors.append(str(exc))

        if not rows and not errors:
            errors.append("Nao encontrei linhas validas no CSV de score de clientes.")

        duplicate_count = _duplicate_key_count(rows)
        if duplicate_count:
            warnings_list.append(f"{duplicate_count} cliente(s) repetido(s) por filial + codigo; a consulta usara o primeiro da carga.")

        return ClientesScoreValidationResult(
            dataset_name="clientes_score",
            source_path=str(path),
            ok=not errors,
            total_rows=len(rows),
            unique_clientes=len({(row.filial, row.cod_pdv) for row in rows}),
            error_count=len(errors),
            warning_count=len(warnings_list),
            sample_errors=errors[:10],
            sample_warnings=warnings_list[:10],
        )

    def summarize_source(self, source_path: Path) -> ClientesScoreImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        rows = _load_clientes_score_rows(source_path.expanduser().resolve())
        score_counter = Counter(row.score or "-" for row in rows)
        return ClientesScoreImportSummary(
            source_path=str(source_path),
            rows=len(rows),
            unique_clientes=len({(row.filial, row.cod_pdv) for row in rows}),
            unique_filiais=len({row.filial for row in rows}),
            duplicate_clientes=_duplicate_key_count(rows),
            score_counts=score_counter.most_common(),
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        summary = self.summarize_source(path)
        rows = _load_clientes_score_rows(path)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_snapshot_rows(conn, rows, batch_id)
            activate_import_batch(conn, self.schema, "clientes_score", batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, "clientes_score", keep_last=3)
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
            active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "clientes_score", activate_if_missing=True)
            self._create_latest_view(conn)
            conn.commit()
        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.clientes_score_latest",
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
                    CREATE TABLE IF NOT EXISTS {}.clientes_score_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        filial VARCHAR(16) NOT NULL,
                        cod_pdv VARCHAR(32) NOT NULL,
                        cliente TEXT NOT NULL,
                        razao_social TEXT NOT NULL,
                        score VARCHAR(8) NOT NULL,
                        piorando_2026 BOOLEAN NOT NULL DEFAULT FALSE,
                        pct_atraso_historico NUMERIC(8, 2) NOT NULL DEFAULT 0,
                        titulos_historico INTEGER NOT NULL DEFAULT 0,
                        recebido_historico NUMERIC(18, 2) NOT NULL DEFAULT 0,
                        maior_atraso_dias INTEGER NOT NULL DEFAULT 0,
                        vezes_mais_30d INTEGER NOT NULL DEFAULT 0,
                        tarifa_paga NUMERIC(18, 2) NOT NULL DEFAULT 0,
                        juros_pagos NUMERIC(18, 2) NOT NULL DEFAULT 0,
                        em_aberto_hoje NUMERIC(18, 2) NOT NULL DEFAULT 0,
                        vencido_hoje NUMERIC(18, 2) NOT NULL DEFAULT 0,
                        dias_vencido_mais_antigo INTEGER NOT NULL DEFAULT 0,
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS clientes_score_snapshot_batch_filial_cod_idx ON {}.clientes_score_snapshot (batch_id, filial, cod_pdv)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS clientes_score_snapshot_batch_score_idx ON {}.clientes_score_snapshot (batch_id, score)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS import_batches_clientes_score_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)"
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
            VALUES ('clientes_score', %s, %s, %s, %s)
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
        rows: list[ClienteScoreRow],
        batch_id: int,
    ) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.clientes_score_snapshot (
                batch_id,
                row_number,
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
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema))
        params = [
            (
                batch_id,
                index,
                row.filial,
                row.cod_pdv,
                row.cliente,
                row.razao_social,
                row.score,
                row.piorando_2026,
                row.pct_atraso_historico,
                row.titulos_historico,
                row.recebido_historico,
                row.maior_atraso_dias,
                row.vezes_mais_30d,
                row.tarifa_paga,
                row.juros_pagos,
                row.em_aberto_hoje,
                row.vencido_hoje,
                row.dias_vencido_mais_antigo,
                Jsonb(row.to_payload()),
            )
            for index, row in enumerate(rows, start=1)
        ]
        with conn.cursor() as cur:
            cur.executemany(query, params)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "clientes_score", activate_if_missing=True)
        where_clause = sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id)) if active_batch_id is not None else sql.SQL("FALSE")
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.clientes_score_latest AS
            SELECT
                s.batch_id,
                s.row_number,
                s.filial,
                s.cod_pdv,
                s.cliente,
                s.razao_social,
                s.score,
                s.piorando_2026,
                s.pct_atraso_historico,
                s.titulos_historico,
                s.recebido_historico,
                s.maior_atraso_dias,
                s.vezes_mais_30d,
                s.tarifa_paga,
                s.juros_pagos,
                s.em_aberto_hoje,
                s.vencido_hoje,
                s.dias_vencido_mais_antigo,
                s.payload,
                s.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM {}.clientes_score_snapshot s
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


def _load_clientes_score_rows(path: Path) -> list[ClienteScoreRow]:
    text = _read_text_with_fallback(path)
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ValueError("CSV sem cabecalho.")

    header_map = _build_header_map(reader.fieldnames)
    missing_headers = sorted(EXPECTED_HEADERS - set(header_map))
    if missing_headers:
        raise ValueError(f"CSV invalido. Colunas obrigatorias ausentes: {', '.join(missing_headers)}")

    rows: list[ClienteScoreRow] = []
    for source_row_number, raw_row in enumerate(reader, start=2):
        row = {str(key or "").strip(): str(value or "").strip() for key, value in raw_row.items() if key is not None}
        if not any(row.values()):
            continue
        filial = normalize_numeric_code(row.get(header_map["Filial"], ""))
        cod_pdv = normalize_numeric_code(row.get(header_map["Codigo"], ""))
        if not filial or not cod_pdv:
            continue
        rows.append(
            ClienteScoreRow(
                filial=filial,
                cod_pdv=cod_pdv,
                cliente=_clean_text(row.get(header_map["Cliente"], "")),
                razao_social=_clean_text(row.get(header_map["RazaoSocial"], "")),
                score=_clean_text(row.get(header_map["Score"], "")).upper() or "-",
                piorando_2026=_parse_bool(row.get(header_map.get("Piorando2026", ""), "")),
                pct_atraso_historico=_parse_decimal(row.get(header_map["PctAtrasoHistorico"], "")),
                titulos_historico=_parse_int(row.get(header_map["TitulosHistorico"], "")),
                recebido_historico=_parse_decimal(row.get(header_map["RecebidoHistorico"], "")),
                maior_atraso_dias=_parse_int(row.get(header_map["MaiorAtrasoDias"], "")),
                vezes_mais_30d=_parse_int(row.get(header_map["VezesMais30d"], "")),
                tarifa_paga=_parse_decimal(row.get(header_map["TarifaPaga"], "")),
                juros_pagos=_parse_decimal(row.get(header_map["JurosPagos"], "")),
                em_aberto_hoje=_parse_decimal(row.get(header_map["EmAbertoHoje"], "")),
                vencido_hoje=_parse_decimal(row.get(header_map["VencidoHoje"], "")),
                dias_vencido_mais_antigo=_parse_int(row.get(header_map["DiasVencidoMaisAntigo"], "")),
                source_row_number=source_row_number,
            )
        )
    rows.sort(key=lambda item: (_sort_numeric(item.filial), _sort_numeric(item.cod_pdv), item.source_row_number))
    return rows


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    header_map: dict[str, str] = {}
    for header in fieldnames:
        actual = str(header or "").strip()
        canonical = HEADER_ALIASES.get(_normalize_header(actual))
        if canonical and canonical not in header_map:
            header_map[canonical] = actual
    return header_map


def _read_text_with_fallback(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Nao consegui ler o arquivo com um encoding suportado.")


def _detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        return str(dialect.delimiter or ";")
    except Exception:
        return ";"


def _normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return "".join(char for char in ascii_only.lower() if char.isalnum())


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_decimal(value: Any) -> Decimal:
    cleaned = _clean_text(value)
    if not cleaned:
        return Decimal("0")
    normalized = cleaned.replace("R$", "").replace("%", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_int(value: Any) -> int:
    decimal_value = _parse_decimal(value)
    try:
        return int(decimal_value)
    except (ValueError, OverflowError):
        return 0


def _parse_bool(value: Any) -> bool:
    normalized = _normalize_header(_clean_text(value))
    return normalized in {"1", "s", "sim", "true", "yes", "y"}


def _duplicate_key_count(rows: list[ClienteScoreRow]) -> int:
    counter = Counter((row.filial, row.cod_pdv) for row in rows)
    return sum(1 for count in counter.values() if count > 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal_to_json(value: Decimal) -> str:
    return f"{value:.2f}"


def _sort_numeric(value: str) -> tuple[int, str]:
    normalized = normalize_numeric_code(value)
    if normalized.isdigit():
        return (int(normalized), normalized)
    return (10**9, normalized)


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"
