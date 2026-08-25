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
    "tipo_mercadoria",
    "un_venda",
    "tipo_marca",
    "grupo",
    "secao",
    "familia",
    "capacidade",
    "peso_bruto",
    "fator_conversor",
    "tipo_roadshow",
    "conta_corrente",
    "retornavel",
    "ind_meia",
    "id_tp_material",
    "id_tp_embalagem",
    "tipo_material",
    "vasilhame_ficticio",
    "ncm",
    "tab_icms",
    "cest",
    "cst_cbs_ibs",
    "class_trib_cbs_ibs",
}
HEADER_ALIASES = {
    "codigo": "codigo",
    "cod": "codigo",
    "codigomaterial": "codigo",
    "descricao": "descricao",
    "descricaomaterial": "descricao",
    "tipomercadoria": "tipo_mercadoria",
    "unvenda": "un_venda",
    "unidadedevenda": "un_venda",
    "tipomarca": "tipo_marca",
    "grupo": "grupo",
    "secao": "secao",
    "seção": "secao",
    "familia": "familia",
    "capacidade": "capacidade",
    "pesobruto": "peso_bruto",
    "peso": "peso_bruto",
    "fatorconversor": "fator_conversor",
    "tiporoadshow": "tipo_roadshow",
    "tproadshow": "tipo_roadshow",
    "contacorrente": "conta_corrente",
    "retornavel": "retornavel",
    "retornável": "retornavel",
    "indmeia": "ind_meia",
    "idtpmaterial": "id_tp_material",
    "idtpembalagem": "id_tp_embalagem",
    "tipomaterial": "tipo_material",
    "tpmaterial": "tipo_material",
    "vasilhameficticio": "vasilhame_ficticio",
    "vasilhamefictício": "vasilhame_ficticio",
    "ncm": "ncm",
    "tabicms": "tab_icms",
    "cest": "cest",
    "cstcbsibs": "cst_cbs_ibs",
    "classtribcbsibs": "class_trib_cbs_ibs",
}


@dataclass(frozen=True)
class DMateriaisValidationResult:
    dataset_name: str
    source_path: str
    ok: bool
    total_rows: int
    unique_codigos: int
    unique_tipos_material: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError("; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao da tabela de materiais.")


@dataclass(frozen=True)
class DMateriaisImportSummary:
    source_path: str
    rows: int
    unique_codigos: int
    unique_tipos_material: int
    unique_grupos: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DMateriaisRow:
    codigo: str
    descricao: str
    tipo_mercadoria: str
    un_venda: str
    tipo_marca: str
    grupo: str
    secao: str
    familia: str
    capacidade: Decimal
    peso_bruto: Decimal
    fator_conversor: Decimal
    tipo_roadshow: str
    conta_corrente: str
    retornavel: str
    ind_meia: str
    id_tp_material: str
    id_tp_embalagem: str
    tipo_material: str
    vasilhame_ficticio: str
    ncm: str
    tab_icms: str
    cest: str
    cst_cbs_ibs: str
    class_trib_cbs_ibs: str
    source_row_number: int
    payload: dict[str, str]


class DMateriaisImportService:
    dataset_name = "dmateriais"
    snapshot_table = "dmateriais_snapshot"
    latest_view = "dmateriais_latest"
    dataset_label = "tabela de materiais"

    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def validate_source(self, source_path: Path) -> DMateriaisValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings_list: list[str] = []
        rows: list[DMateriaisRow] = []

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                rows = _load_dmateriais_rows(path)
            except Exception as exc:
                errors.append(str(exc))

        if not rows and not errors:
            errors.append("Nao encontrei linhas validas na tabela de materiais.")

        return DMateriaisValidationResult(
            dataset_name=self.dataset_name,
            source_path=str(path),
            ok=not errors,
            total_rows=len(rows),
            unique_codigos=len({row.codigo for row in rows}),
            unique_tipos_material=len({row.tipo_material for row in rows if row.tipo_material}),
            error_count=len(errors),
            warning_count=len(warnings_list),
            sample_errors=errors[:10],
            sample_warnings=warnings_list[:10],
        )

    def summarize_source(self, source_path: Path) -> DMateriaisImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        rows = _load_dmateriais_rows(source_path.expanduser().resolve())
        return DMateriaisImportSummary(
            source_path=str(source_path),
            rows=len(rows),
            unique_codigos=len({row.codigo for row in rows}),
            unique_tipos_material=len({row.tipo_material for row in rows if row.tipo_material}),
            unique_grupos=len({row.grupo for row in rows if row.grupo}),
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        summary = self.summarize_source(path)
        rows = _load_dmateriais_rows(path)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_snapshot_rows(conn, rows, batch_id)
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
            "view": f"{self.schema}.{self.latest_view}",
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
                    CREATE TABLE IF NOT EXISTS {}.{} (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        codigo VARCHAR(32) NOT NULL,
                        descricao TEXT NOT NULL,
                        tipo_mercadoria VARCHAR(32) NOT NULL DEFAULT '',
                        un_venda VARCHAR(32) NOT NULL DEFAULT '',
                        tipo_marca TEXT NOT NULL DEFAULT '',
                        grupo VARCHAR(64) NOT NULL DEFAULT '',
                        secao VARCHAR(64) NOT NULL DEFAULT '',
                        familia VARCHAR(64) NOT NULL DEFAULT '',
                        capacidade NUMERIC(18,6) NOT NULL DEFAULT 0,
                        peso_bruto NUMERIC(18,6) NOT NULL DEFAULT 0,
                        fator_conversor NUMERIC(18,6) NOT NULL DEFAULT 0,
                        tipo_roadshow TEXT NOT NULL DEFAULT '',
                        conta_corrente TEXT NOT NULL DEFAULT '',
                        retornavel VARCHAR(8) NOT NULL DEFAULT '',
                        ind_meia VARCHAR(8) NOT NULL DEFAULT '',
                        id_tp_material VARCHAR(32) NOT NULL DEFAULT '',
                        id_tp_embalagem VARCHAR(32) NOT NULL DEFAULT '',
                        tipo_material TEXT NOT NULL DEFAULT '',
                        vasilhame_ficticio VARCHAR(8) NOT NULL DEFAULT '',
                        ncm VARCHAR(64) NOT NULL DEFAULT '',
                        tab_icms VARCHAR(32) NOT NULL DEFAULT '',
                        cest VARCHAR(64) NOT NULL DEFAULT '',
                        cst_cbs_ibs TEXT NOT NULL DEFAULT '',
                        class_trib_cbs_ibs TEXT NOT NULL DEFAULT '',
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.snapshot_table), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} (batch_id, codigo)").format(
                    sql.Identifier(f"{self.snapshot_table}_batch_codigo_idx"),
                    sql.Identifier(self.schema),
                    sql.Identifier(self.snapshot_table),
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} (batch_id, tipo_material)").format(
                    sql.Identifier(f"{self.snapshot_table}_batch_tipo_idx"),
                    sql.Identifier(self.schema),
                    sql.Identifier(self.snapshot_table),
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.import_batches (dataset_name, imported_at DESC)").format(
                    sql.Identifier(f"import_batches_{self.dataset_name}_dataset_idx"),
                    sql.Identifier(self.schema)
                )
            )
            ensure_dataset_state_table(conn, self.schema)

    def _insert_batch(self, conn: psycopg.Connection[Any], source_file: str, reference_date: date, file_hash: str, total_rows: int) -> int:
        query = sql.SQL(
            """
            INSERT INTO {}.import_batches (dataset_name, source_file, file_hash, reference_date, total_rows)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (self.dataset_name, source_file, file_hash, reference_date, total_rows))
            row = cur.fetchone()
        return int(row["id"])

    def _insert_snapshot_rows(self, conn: psycopg.Connection[Any], rows: list[DMateriaisRow], batch_id: int) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.{} (
                batch_id, row_number, codigo, descricao, tipo_mercadoria, un_venda,
                tipo_marca, grupo, secao, familia, capacidade, peso_bruto,
                fator_conversor, tipo_roadshow, conta_corrente, retornavel, ind_meia,
                id_tp_material, id_tp_embalagem, tipo_material, vasilhame_ficticio,
                ncm, tab_icms, cest, cst_cbs_ibs, class_trib_cbs_ibs, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.snapshot_table))
        params = [
            (
                batch_id,
                index,
                row.codigo,
                row.descricao,
                row.tipo_mercadoria,
                row.un_venda,
                row.tipo_marca,
                row.grupo,
                row.secao,
                row.familia,
                row.capacidade,
                row.peso_bruto,
                row.fator_conversor,
                row.tipo_roadshow,
                row.conta_corrente,
                row.retornavel,
                row.ind_meia,
                row.id_tp_material,
                row.id_tp_embalagem,
                row.tipo_material,
                row.vasilhame_ficticio,
                row.ncm,
                row.tab_icms,
                row.cest,
                row.cst_cbs_ibs,
                row.class_trib_cbs_ibs,
                Jsonb(row.payload),
            )
            for index, row in enumerate(rows, start=1)
        ]
        with conn.cursor() as cur:
            cur.executemany(query, params)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        active_batch_id = resolve_effective_import_batch_id(conn, self.schema, self.dataset_name, activate_if_missing=True)
        where_clause = sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id)) if active_batch_id is not None else sql.SQL("FALSE")
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.{} AS
            SELECT
                s.batch_id,
                s.row_number,
                s.codigo,
                s.descricao,
                s.tipo_mercadoria,
                s.un_venda,
                s.tipo_marca,
                s.grupo,
                s.secao,
                s.familia,
                s.capacidade,
                s.peso_bruto,
                s.fator_conversor,
                s.tipo_roadshow,
                s.conta_corrente,
                s.retornavel,
                s.ind_meia,
                s.id_tp_material,
                s.id_tp_embalagem,
                s.tipo_material,
                s.vasilhame_ficticio,
                s.ncm,
                s.tab_icms,
                s.cest,
                s.cst_cbs_ibs,
                s.class_trib_cbs_ibs,
                s.payload,
                s.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM {}.{} s
            JOIN {}.import_batches b ON b.id = s.batch_id
            WHERE {}
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.latest_view),
            sql.Identifier(self.schema),
            sql.Identifier(self.snapshot_table),
            sql.Identifier(self.schema),
            where_clause,
        )
        with conn.cursor() as cur:
            cur.execute(query)

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)


def _load_dmateriais_rows(path: Path) -> list[DMateriaisRow]:
    text = _read_text_with_fallback(path)
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ValueError("Arquivo sem cabecalho.")

    headers = [str(header or "").strip() for header in reader.fieldnames]
    header_map = _build_header_map(headers)
    rows: list[DMateriaisRow] = []
    for row_number, raw_row in enumerate(reader, start=2):
        row = {str(key or "").strip(): str(value or "").strip() for key, value in raw_row.items() if key is not None}
        if not any(str(value or "").strip() for value in row.values()):
            continue
        codigo = normalize_numeric_code(row.get(header_map["codigo"], ""))
        descricao = _clean_text(row.get(header_map["descricao"], ""))
        if not codigo or not descricao:
            continue
        rows.append(
            DMateriaisRow(
                codigo=codigo,
                descricao=descricao,
                tipo_mercadoria=_clean_code(row.get(header_map.get("tipo_mercadoria", ""), "")),
                un_venda=_clean_code(row.get(header_map.get("un_venda", ""), "")),
                tipo_marca=_clean_text(row.get(header_map.get("tipo_marca", ""), "")),
                grupo=_clean_code(row.get(header_map.get("grupo", ""), "")),
                secao=_clean_code(row.get(header_map.get("secao", ""), "")),
                familia=_clean_code(row.get(header_map.get("familia", ""), "")),
                capacidade=_parse_decimal_value(row.get(header_map.get("capacidade", ""), "")),
                peso_bruto=_parse_decimal_value(row.get(header_map.get("peso_bruto", ""), "")),
                fator_conversor=_parse_decimal_value(row.get(header_map.get("fator_conversor", ""), "")),
                tipo_roadshow=_clean_text(row.get(header_map.get("tipo_roadshow", ""), "")),
                conta_corrente=_clean_text(row.get(header_map.get("conta_corrente", ""), "")),
                retornavel=_clean_code(row.get(header_map.get("retornavel", ""), "")),
                ind_meia=_clean_code(row.get(header_map.get("ind_meia", ""), "")),
                id_tp_material=_clean_code(row.get(header_map.get("id_tp_material", ""), "")),
                id_tp_embalagem=_clean_code(row.get(header_map.get("id_tp_embalagem", ""), "")),
                tipo_material=_clean_text(row.get(header_map.get("tipo_material", ""), "")),
                vasilhame_ficticio=_clean_code(row.get(header_map.get("vasilhame_ficticio", ""), "")),
                ncm=_clean_code(row.get(header_map.get("ncm", ""), "")),
                tab_icms=_clean_code(row.get(header_map.get("tab_icms", ""), "")),
                cest=_clean_code(row.get(header_map.get("cest", ""), "")),
                cst_cbs_ibs=_clean_text(row.get(header_map.get("cst_cbs_ibs", ""), "")),
                class_trib_cbs_ibs=_clean_text(row.get(header_map.get("class_trib_cbs_ibs", ""), "")),
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
