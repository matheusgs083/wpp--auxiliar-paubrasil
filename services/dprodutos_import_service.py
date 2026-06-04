from __future__ import annotations

import csv
import hashlib
import io
import unicodedata
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
REQUIRED_HEADERS = {"codigo", "descricao"}
OPTIONAL_HEADERS = {
    "pgv",
    "empresa",
    "tipo_marca",
    "linha_marca",
    "embalagem",
    "marca",
    "vasilhame",
    "grupo",
    "grupo_remuneracao",
    "ean",
    "fator_hecto",
    "familia_embalagem_siv",
    "codigo_produto_sap",
    "ncm",
    "cest",
    "codigo_unitario",
    "descricao_unitaria",
    "subtipo",
}
HEADER_ALIASES = {
    "codigo": "codigo",
    "cod": "codigo",
    "codigoproduto": "codigo",
    "descricao": "descricao",
    "descricaoproduto": "descricao",
    "produto": "descricao",
    "pgv": "pgv",
    "empresa": "empresa",
    "tipomarca": "tipo_marca",
    "linhamarca": "linha_marca",
    "embalagem": "embalagem",
    "marca": "marca",
    "vasilhame": "vasilhame",
    "grupo": "grupo",
    "gruporemuneracao": "grupo_remuneracao",
    "ean": "ean",
    "fatorhecto": "fator_hecto",
    "famembalagemsiv": "familia_embalagem_siv",
    "familiaembalagemsiv": "familia_embalagem_siv",
    "codigoprodutosap": "codigo_produto_sap",
    "ncm": "ncm",
    "cest": "cest",
    "codigounitario": "codigo_unitario",
    "descricaounitaria": "descricao_unitaria",
    "subtipo": "subtipo",
}


@dataclass(frozen=True)
class DProdutosValidationResult:
    dataset_name: str
    source_path: str
    ok: bool
    total_rows: int
    unique_codigos: int
    unique_marcas: int
    unique_grupos: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError("; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao da tabela de produtos.")


@dataclass(frozen=True)
class DProdutosImportSummary:
    source_path: str
    rows: int
    unique_codigos: int
    unique_marcas: int
    unique_grupos: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DProdutosRow:
    codigo: str
    descricao: str
    pgv: str
    empresa: str
    tipo_marca: str
    linha_marca: str
    embalagem: str
    marca: str
    vasilhame: str
    grupo: str
    grupo_remuneracao: str
    ean: str
    fator_hecto: Decimal
    familia_embalagem_siv: str
    codigo_produto_sap: str
    ncm: str
    cest: str
    codigo_unitario: str
    descricao_unitaria: str
    subtipo: str
    source_row_number: int
    payload: dict[str, str]


class DProdutosImportService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def validate_source(self, source_path: Path) -> DProdutosValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings_list: list[str] = []
        rows: list[DProdutosRow] = []

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                rows = _load_dprodutos_rows(path)
            except Exception as exc:
                errors.append(str(exc))

        if not rows and not errors:
            errors.append("Nao encontrei linhas validas na tabela de produtos.")

        return DProdutosValidationResult(
            dataset_name="dprodutos",
            source_path=str(path),
            ok=not errors,
            total_rows=len(rows),
            unique_codigos=len({row.codigo for row in rows}),
            unique_marcas=len({row.marca for row in rows if row.marca}),
            unique_grupos=len({row.grupo for row in rows if row.grupo}),
            error_count=len(errors),
            warning_count=len(warnings_list),
            sample_errors=errors[:10],
            sample_warnings=warnings_list[:10],
        )

    def summarize_source(self, source_path: Path) -> DProdutosImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        rows = _load_dprodutos_rows(source_path.expanduser().resolve())
        return DProdutosImportSummary(
            source_path=str(source_path),
            rows=len(rows),
            unique_codigos=len({row.codigo for row in rows}),
            unique_marcas=len({row.marca for row in rows if row.marca}),
            unique_grupos=len({row.grupo for row in rows if row.grupo}),
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        summary = self.summarize_source(path)
        rows = _load_dprodutos_rows(path)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_snapshot_rows(conn, rows, batch_id)
            activate_import_batch(conn, self.schema, "dprodutos", batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, "dprodutos", keep_last=3)
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
            active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dprodutos", activate_if_missing=True)
            self._create_latest_view(conn)
            conn.commit()

        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.dprodutos_latest",
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
                    CREATE TABLE IF NOT EXISTS {}.dprodutos_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        codigo VARCHAR(32) NOT NULL,
                        descricao TEXT NOT NULL,
                        pgv VARCHAR(32) NOT NULL DEFAULT '',
                        empresa VARCHAR(32) NOT NULL DEFAULT '',
                        tipo_marca TEXT NOT NULL DEFAULT '',
                        linha_marca TEXT NOT NULL DEFAULT '',
                        embalagem TEXT NOT NULL DEFAULT '',
                        marca TEXT NOT NULL DEFAULT '',
                        vasilhame VARCHAR(64) NOT NULL DEFAULT '',
                        grupo VARCHAR(64) NOT NULL DEFAULT '',
                        grupo_remuneracao VARCHAR(64) NOT NULL DEFAULT '',
                        ean VARCHAR(64) NOT NULL DEFAULT '',
                        fator_hecto NUMERIC(18, 6) NOT NULL DEFAULT 0,
                        familia_embalagem_siv TEXT NOT NULL DEFAULT '',
                        codigo_produto_sap VARCHAR(64) NOT NULL DEFAULT '',
                        ncm VARCHAR(64) NOT NULL DEFAULT '',
                        cest VARCHAR(64) NOT NULL DEFAULT '',
                        codigo_unitario VARCHAR(64) NOT NULL DEFAULT '',
                        descricao_unitaria TEXT NOT NULL DEFAULT '',
                        subtipo VARCHAR(64) NOT NULL DEFAULT '',
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "ALTER TABLE {}.dprodutos_snapshot ADD COLUMN IF NOT EXISTS fator_hecto NUMERIC(18, 6) NOT NULL DEFAULT 0"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    UPDATE {}.dprodutos_snapshot
                    SET fator_hecto = COALESCE(
                        NULLIF(
                            REPLACE(
                                REPLACE(
                                    REPLACE(
                                        BTRIM(
                                            COALESCE(
                                                payload ->> 'Fator Hecto',
                                                payload ->> 'Fator Hecto Comercial',
                                                payload ->> 'FatorHecto',
                                                payload ->> 'Fator_Hecto',
                                                ''
                                            )
                                        ),
                                        'R$',
                                        ''
                                    ),
                                    '.',
                                    ''
                                ),
                                ',',
                                '.'
                            ),
                            ''
                        ),
                        '0'
                    )::numeric
                    WHERE COALESCE(fator_hecto, 0) = 0
                      AND COALESCE(
                        NULLIF(
                            REPLACE(
                                REPLACE(
                                    REPLACE(
                                        BTRIM(
                                            COALESCE(
                                                payload ->> 'Fator Hecto',
                                                payload ->> 'Fator Hecto Comercial',
                                                payload ->> 'FatorHecto',
                                                payload ->> 'Fator_Hecto',
                                                ''
                                            )
                                        ),
                                        'R$',
                                        ''
                                    ),
                                    '.',
                                    ''
                                ),
                                ',',
                                '.'
                            ),
                            ''
                        ),
                        '0'
                    )::numeric <> 0
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dprodutos_snapshot_batch_codigo_idx ON {}.dprodutos_snapshot (batch_id, codigo)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dprodutos_snapshot_batch_descricao_idx ON {}.dprodutos_snapshot (batch_id, descricao)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS import_batches_dprodutos_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)"
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
            VALUES ('dprodutos', %s, %s, %s, %s)
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
        rows: list[DProdutosRow],
        batch_id: int,
    ) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.dprodutos_snapshot (
                batch_id,
                row_number,
                codigo,
                descricao,
                pgv,
                empresa,
                tipo_marca,
                linha_marca,
                embalagem,
                marca,
                vasilhame,
                grupo,
                grupo_remuneracao,
                ean,
                fator_hecto,
                familia_embalagem_siv,
                codigo_produto_sap,
                ncm,
                cest,
                codigo_unitario,
                descricao_unitaria,
                subtipo,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema))
        params = [
            (
                batch_id,
                index,
                row.codigo,
                row.descricao,
                row.pgv,
                row.empresa,
                row.tipo_marca,
                row.linha_marca,
                row.embalagem,
                row.marca,
                row.vasilhame,
                row.grupo,
                row.grupo_remuneracao,
                row.ean,
                row.fator_hecto,
                row.familia_embalagem_siv,
                row.codigo_produto_sap,
                row.ncm,
                row.cest,
                row.codigo_unitario,
                row.descricao_unitaria,
                row.subtipo,
                Jsonb(row.payload),
            )
            for index, row in enumerate(rows, start=1)
        ]
        with conn.cursor() as cur:
            cur.executemany(query, params)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dprodutos", activate_if_missing=True)
        where_clause = sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id)) if active_batch_id is not None else sql.SQL("FALSE")
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.dprodutos_latest AS
            SELECT
                s.batch_id,
                s.row_number,
                s.codigo,
                s.descricao,
                s.pgv,
                s.empresa,
                s.tipo_marca,
                s.linha_marca,
                s.embalagem,
                s.marca,
                s.vasilhame,
                s.grupo,
                s.grupo_remuneracao,
                s.ean,
                s.familia_embalagem_siv,
                s.codigo_produto_sap,
                s.ncm,
                s.cest,
                s.codigo_unitario,
                s.descricao_unitaria,
                s.subtipo,
                s.payload,
                s.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at,
                s.fator_hecto
            FROM {}.dprodutos_snapshot s
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


def _load_dprodutos_rows(path: Path) -> list[DProdutosRow]:
    text = _read_text_with_fallback(path)
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ValueError("Arquivo sem cabecalho.")

    headers = [str(header or "").strip() for header in reader.fieldnames]
    header_map = _build_header_map(headers)
    rows: list[DProdutosRow] = []
    for row_number, raw_row in enumerate(reader, start=2):
        row = {str(key or "").strip(): str(value or "").strip() for key, value in raw_row.items() if key is not None}
        if not any(str(value or "").strip() for value in row.values()):
            continue
        codigo = normalize_numeric_code(row.get(header_map["codigo"], ""))
        descricao = _clean_text(row.get(header_map["descricao"], ""))
        if not codigo or not descricao:
            continue
        rows.append(
            DProdutosRow(
                codigo=codigo,
                descricao=descricao,
                pgv=_clean_code(row.get(header_map.get("pgv", ""), "")),
                empresa=_clean_code(row.get(header_map.get("empresa", ""), "")),
                tipo_marca=_clean_text(row.get(header_map.get("tipo_marca", ""), "")),
                linha_marca=_clean_text(row.get(header_map.get("linha_marca", ""), "")),
                embalagem=_clean_text(row.get(header_map.get("embalagem", ""), "")),
                marca=_clean_text(row.get(header_map.get("marca", ""), "")),
                vasilhame=_clean_code(row.get(header_map.get("vasilhame", ""), "")),
                grupo=_clean_code(row.get(header_map.get("grupo", ""), "")),
                grupo_remuneracao=_clean_code(row.get(header_map.get("grupo_remuneracao", ""), "")),
                ean=_clean_code(row.get(header_map.get("ean", ""), "")),
                fator_hecto=_parse_decimal_value(row.get(header_map.get("fator_hecto", ""), "")),
                familia_embalagem_siv=_clean_text(row.get(header_map.get("familia_embalagem_siv", ""), "")),
                codigo_produto_sap=_clean_code(row.get(header_map.get("codigo_produto_sap", ""), "")),
                ncm=_clean_code(row.get(header_map.get("ncm", ""), "")),
                cest=_clean_code(row.get(header_map.get("cest", ""), "")),
                codigo_unitario=normalize_numeric_code(row.get(header_map.get("codigo_unitario", ""), "")),
                descricao_unitaria=_clean_text(row.get(header_map.get("descricao_unitaria", ""), "")),
                subtipo=_clean_code(row.get(header_map.get("subtipo", ""), "")),
                source_row_number=row_number,
                payload={header: _clean_text(row.get(header, "")) for header in headers if header},
            )
        )
    rows.sort(key=lambda item: (_sort_numeric(item.codigo), item.descricao, item.source_row_number))
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


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _clean_code(value: Any) -> str:
    return str(value or "").strip()


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _parse_decimal_value(value: Any) -> Decimal:
    cleaned = str(value or "").strip()
    if not cleaned:
        return Decimal("0")
    normalized = cleaned.replace("R$", "").replace(" ", "")
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sort_numeric(value: str) -> tuple[int, str]:
    cleaned = normalize_numeric_code(value)
    if cleaned:
        try:
            return (0, f"{int(cleaned):09d}")
        except ValueError:
            return (1, cleaned)
    return (2, str(value or "").strip())
