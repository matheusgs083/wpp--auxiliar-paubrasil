from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.critica_rn_import_service import (
    _clean_text,
    _detect_delimiter,
    _normalize_schema,
    _parse_decimal_value,
    _price_reference_cte,
    _read_text_with_fallback,
    _relation_exists,
    _row_to_payload,
    _sha256,
)
from bot_api.services.import_publication import (
    activate_import_batch,
    ensure_dataset_state_table,
    prune_import_batches,
)


EXPECTED_EXTENSION_SET = {".csv"}
B2B_PRICE_ORIGINS = {"B2BG", "B2BGA"}
B2B_PRICE_TOLERANCE = Decimal("0.60")
EXPECTED_HEADERS = {
    "Filial Origem",
    "Status Pedido",
    "Tipo Movimento",
    "Num Pedido",
    "Cod. Vendedor",
    "Cod. Cliente",
    "Nome Cliente",
    "Valor Pedido",
    "Cod. Setor",
    "Cod. Pedido SIV",
    "Cod. Produto",
    "Nome Produto",
    "Qtde",
    "Unidade",
    "TTV s/ADF",
    "Preco Unit.",
    "Preco Minimo",
    "Ocorrencia 1",
    "Ocorrencia 2",
    "TE",
}
HEADER_ALIASES = {
    "filialorigem": "Filial Origem",
    "statuspedido": "Status Pedido",
    "tipomovimento": "Tipo Movimento",
    "numpedido": "Num Pedido",
    "codvendedor": "Cod. Vendedor",
    "codcliente": "Cod. Cliente",
    "nomecliente": "Nome Cliente",
    "valorpedido": "Valor Pedido",
    "codsetor": "Cod. Setor",
    "codpedidosiv": "Cod. Pedido SIV",
    "codproduto": "Cod. Produto",
    "nomeproduto": "Nome Produto",
    "qtde": "Qtde",
    "unidade": "Unidade",
    "ttvsadf": "TTV s/ADF",
    "precounit": "Preco Unit.",
    "precominimo": "Preco Minimo",
    "ocorrencia1": "Ocorrencia 1",
    "ocorrencia2": "Ocorrencia 2",
    "te": "TE",
}


@dataclass(frozen=True)
class CriticaOperacaoValidationResult:
    dataset_name: str
    source_path: str
    expected_filial: str
    ok: bool
    total_rows: int
    unique_pedidos: int
    unique_unb_setores: int
    unique_produtos: int
    duplicate_pedido_produto_keys: int
    rows_with_critica: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError(
                "; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao da critica por operacao."
            )


@dataclass(frozen=True)
class CriticaOperacaoImportSummary:
    source_path: str
    rows: int
    unique_pedidos: int
    unique_unb_setores: int
    unique_produtos: int
    duplicate_pedido_produto_keys: int
    rows_with_critica: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CriticaOperacaoRow:
    filial: str
    pedido: str
    operacao: str
    cod_pdv: str
    nome_pdv: str
    setor: str
    filial_setor_key: str
    status_pedido: str
    total_pedido: Decimal
    total_cliente: Decimal
    critica_text: str
    produto_codigo: str
    produto_key: str
    nome_produto: str
    quantidade: Decimal
    unid_venda: str
    preco_unitario: Decimal
    preco_sem_adf: Decimal
    minimo_politica: Decimal
    tipo_movimento: str
    codigo_gv: str
    codigo_pgv: str
    te_codigo: str
    source_row_number: int
    payload: dict[str, Any]


class CriticaOperacaoImportService:
    def __init__(
        self,
        database_url: str,
        schema: str,
        *,
        dataset_name: str,
        expected_filial: str,
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.dataset_name = str(dataset_name or "").strip().lower()
        self.expected_filial = normalize_numeric_code(expected_filial)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        if not self.dataset_name:
            raise ValueError("dataset_name obrigatorio para a critica por operacao.")
        if not self.expected_filial:
            raise ValueError("expected_filial obrigatoria para a critica por operacao.")

    def validate_source(self, source_path: Path) -> CriticaOperacaoValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings_list: list[str] = []
        rows: list[CriticaOperacaoRow] = []

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .csv.")
        else:
            try:
                rows = _load_critica_operacao_rows(path, expected_filial=self.expected_filial)
            except Exception as exc:
                errors.append(str(exc))

        if not rows and not errors:
            errors.append("Nao encontrei linhas validas no arquivo de critica por operacao.")

        stats = _summary_stats(rows)
        return CriticaOperacaoValidationResult(
            dataset_name=self.dataset_name,
            source_path=str(path),
            expected_filial=self.expected_filial,
            ok=not errors,
            total_rows=len(rows),
            unique_pedidos=stats["unique_pedidos"],
            unique_unb_setores=stats["unique_unb_setores"],
            unique_produtos=stats["unique_produtos"],
            duplicate_pedido_produto_keys=stats["duplicate_pedido_produto_keys"],
            rows_with_critica=stats["rows_with_critica"],
            error_count=len(errors),
            warning_count=len(warnings_list),
            sample_errors=errors[:10],
            sample_warnings=warnings_list[:10],
        )

    def summarize_source(self, source_path: Path) -> CriticaOperacaoImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        rows = _load_critica_operacao_rows(source_path.expanduser().resolve(), expected_filial=self.expected_filial)
        stats = _summary_stats(rows)
        return CriticaOperacaoImportSummary(
            source_path=str(source_path),
            rows=len(rows),
            unique_pedidos=stats["unique_pedidos"],
            unique_unb_setores=stats["unique_unb_setores"],
            unique_produtos=stats["unique_produtos"],
            duplicate_pedido_produto_keys=stats["duplicate_pedido_produto_keys"],
            rows_with_critica=stats["rows_with_critica"],
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        summary = self.summarize_source(path)
        rows = _load_critica_operacao_rows(path, expected_filial=self.expected_filial)
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        source_hash = _sha256(path)

        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, str(path), batch_date, source_hash, len(rows))
            self._insert_snapshot_rows(conn, rows, batch_id, batch_date)
            self._hydrate_scope_columns(conn, batch_id)
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
                "dataset_name": self.dataset_name,
                "filial": self.expected_filial,
            }
        )
        return result

    def refresh_latest_view(self) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        with self._connect() as conn:
            self._ensure_schema(conn)
            self._hydrate_all_active_scope_columns(conn)
            self._create_latest_view(conn)
            active_batches = self._list_active_batch_ids(conn)
            conn.commit()

        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.critica_latest",
            "active_batch_ids": active_batches,
            "active_batch_count": len(active_batches),
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
                    CREATE TABLE IF NOT EXISTS {}.critica_operacao_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number BIGINT NOT NULL,
                        filial VARCHAR(16) NOT NULL DEFAULT '',
                        pedido VARCHAR(32) NOT NULL DEFAULT '',
                        data_pedido DATE,
                        operacao VARCHAR(32) NOT NULL DEFAULT '',
                        cod_pdv VARCHAR(32) NOT NULL DEFAULT '',
                        nome_pdv TEXT NOT NULL DEFAULT '',
                        setor VARCHAR(32) NOT NULL DEFAULT '',
                        filial_setor_key TEXT NOT NULL DEFAULT '',
                        filial_gv_key TEXT NOT NULL DEFAULT '',
                        filial_dc_key TEXT NOT NULL DEFAULT '',
                        status_pedido TEXT NOT NULL DEFAULT '',
                        total_pedido NUMERIC(18, 4) NOT NULL DEFAULT 0,
                        total_cliente NUMERIC(18, 4) NOT NULL DEFAULT 0,
                        critica_text TEXT NOT NULL DEFAULT '',
                        produto_codigo VARCHAR(32) NOT NULL DEFAULT '',
                        produto_key VARCHAR(32) NOT NULL DEFAULT '',
                        nome_produto TEXT NOT NULL DEFAULT '',
                        quantidade NUMERIC(18, 4) NOT NULL DEFAULT 0,
                        unid_venda VARCHAR(32) NOT NULL DEFAULT '',
                        preco_unitario NUMERIC(18, 4) NOT NULL DEFAULT 0,
                        preco_sem_adf NUMERIC(18, 4) NOT NULL DEFAULT 0,
                        minimo_politica NUMERIC(18, 4) NOT NULL DEFAULT 0,
                        tipo_movimento VARCHAR(32) NOT NULL DEFAULT '',
                        codigo_gv VARCHAR(32) NOT NULL DEFAULT '',
                        codigo_pgv VARCHAR(64) NOT NULL DEFAULT '',
                        te_codigo VARCHAR(32) NOT NULL DEFAULT '',
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_operacao_snapshot_batch_filial_setor_idx ON {}.critica_operacao_snapshot (batch_id, filial_setor_key)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_operacao_snapshot_batch_pedido_idx ON {}.critica_operacao_snapshot (batch_id, filial, pedido)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_operacao_snapshot_batch_data_idx ON {}.critica_operacao_snapshot (batch_id, data_pedido)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_operacao_snapshot_batch_cliente_idx ON {}.critica_operacao_snapshot (batch_id, filial, cod_pdv, data_pedido, pedido)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_operacao_snapshot_batch_gv_idx ON {}.critica_operacao_snapshot (batch_id, filial_gv_key)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_operacao_snapshot_batch_dc_idx ON {}.critica_operacao_snapshot (batch_id, filial_dc_key)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS critica_operacao_snapshot_batch_produto_idx ON {}.critica_operacao_snapshot (batch_id, produto_codigo)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS import_batches_critica_operacao_dataset_idx ON {}.import_batches (dataset_name, imported_at DESC)"
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
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, (self.dataset_name, source_file, file_hash, reference_date, total_rows))
            row = cur.fetchone()
        return int(row["id"])

    def _insert_snapshot_rows(
        self,
        conn: psycopg.Connection[Any],
        rows: list[CriticaOperacaoRow],
        batch_id: int,
        batch_date: date,
    ) -> None:
        query = sql.SQL(
            """
            INSERT INTO {}.critica_operacao_snapshot (
                batch_id,
                row_number,
                filial,
                pedido,
                data_pedido,
                operacao,
                cod_pdv,
                nome_pdv,
                setor,
                filial_setor_key,
                status_pedido,
                total_pedido,
                total_cliente,
                critica_text,
                produto_codigo,
                produto_key,
                nome_produto,
                quantidade,
                unid_venda,
                preco_unitario,
                preco_sem_adf,
                minimo_politica,
                tipo_movimento,
                codigo_gv,
                codigo_pgv,
                te_codigo,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        ).format(sql.Identifier(self.schema))
        payload_batch: list[tuple[Any, ...]] = []
        with conn.cursor() as cur:
            for row_number, row in enumerate(rows, start=1):
                payload_batch.append(
                    (
                        batch_id,
                        row_number,
                        row.filial,
                        row.pedido,
                        batch_date,
                        row.operacao,
                        row.cod_pdv,
                        row.nome_pdv,
                        row.setor,
                        row.filial_setor_key,
                        row.status_pedido,
                        row.total_pedido,
                        row.total_cliente,
                        row.critica_text,
                        row.produto_codigo,
                        row.produto_key,
                        row.nome_produto,
                        row.quantidade,
                        row.unid_venda,
                        row.preco_unitario,
                        row.preco_sem_adf,
                        row.minimo_politica,
                        row.tipo_movimento,
                        row.codigo_gv,
                        row.codigo_pgv,
                        row.te_codigo,
                        Jsonb(row.payload),
                    )
                )
                if len(payload_batch) >= 500:
                    cur.executemany(query, payload_batch)
                    payload_batch.clear()
            if payload_batch:
                cur.executemany(query, payload_batch)

    def _hydrate_scope_columns(self, conn: psycopg.Connection[Any], batch_id: int) -> None:
        if not _relation_exists(conn, self.schema, "dsetores_latest"):
            return
        query = sql.SQL(
            """
            UPDATE {schema}.critica_operacao_snapshot AS c
            SET
                filial_gv_key = COALESCE(ds.filial_gv_key, ''),
                filial_dc_key = COALESCE(ds.filial_dc_key, '')
            FROM {schema}.dsetores_latest AS ds
            WHERE c.batch_id = %s
              AND ds.filial_setor_key = c.filial_setor_key
            """
        ).format(schema=sql.Identifier(self.schema))
        with conn.cursor() as cur:
            cur.execute(query, (batch_id,))

    def _hydrate_all_active_scope_columns(self, conn: psycopg.Connection[Any]) -> None:
        for batch_id in self._list_active_batch_ids(conn):
            self._hydrate_scope_columns(conn, batch_id)

    def _list_active_batch_ids(self, conn: psycopg.Connection[Any]) -> list[int]:
        ensure_dataset_state_table(conn, self.schema)
        query = sql.SQL(
            """
            SELECT active_batch_id
            FROM {}.dataset_state
            WHERE dataset_name LIKE 'critica_op_%'
              AND active_batch_id IS NOT NULL
            ORDER BY dataset_name
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            rows = cur.fetchall()
        return [int(row["active_batch_id"]) for row in rows if row.get("active_batch_id") is not None]

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        ensure_dataset_state_table(conn, self.schema)
        price_ref_cte = _price_reference_cte(self.schema, conn)
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.critica_latest AS
            WITH
            {},
            active_batches AS (
                SELECT active_batch_id AS batch_id
                FROM {}.dataset_state
                WHERE dataset_name LIKE 'critica_op_%'
                  AND active_batch_id IS NOT NULL
            ),
            base AS (
                SELECT
                    c.*,
                    COUNT(*) OVER (PARTITION BY c.batch_id, c.filial, c.pedido) AS pedido_linhas,
                    COUNT(*) OVER (PARTITION BY c.batch_id, c.filial, c.pedido, c.produto_codigo) AS pedido_produto_linhas
                FROM {}.critica_operacao_snapshot c
                JOIN active_batches ab ON ab.batch_id = c.batch_id
            )
            SELECT
                base.batch_id,
                base.row_number,
                base.filial,
                base.pedido,
                CONCAT(base.filial, '_', base.pedido) AS filial_pedido_key,
                base.data_pedido,
                base.operacao,
                base.cod_pdv,
                base.nome_pdv,
                base.setor,
                base.filial_setor_key,
                base.filial_gv_key,
                base.filial_dc_key,
                base.status_pedido,
                base.total_pedido,
                base.total_cliente,
                base.critica_text,
                BTRIM(COALESCE(base.critica_text, '')) <> '' AS possui_critica,
                base.produto_codigo,
                base.produto_key,
                CONCAT(base.filial, '_', base.pedido, '_', COALESCE(NULLIF(base.produto_codigo, ''), 'sem_produto')) AS filial_pedido_produto_key,
                base.quantidade,
                base.unid_venda,
                base.preco_unitario,
                base.preco_sem_adf,
                base.minimo_politica,
                base.tipo_movimento,
                base.codigo_gv,
                base.codigo_pgv,
                base.pedido_linhas,
                base.pedido_produto_linhas,
                base.pedido_produto_linhas > 1 AS pedido_produto_duplicado,
                COALESCE(dp.produto_dprecos, NULLIF(base.nome_produto, '')) AS produto_dprecos,
                dp.dprecos_match_count,
                dp.ttc_min,
                dp.ttc_max,
                dp.caixa_min,
                dp.caixa_max,
                CASE
                    WHEN BTRIM(COALESCE(base.produto_codigo, '')) = '' THEN FALSE
                    ELSE dp.codigo IS NOT NULL
                END AS produto_encontrado_dprecos,
                CASE
                    WHEN BTRIM(COALESCE(base.produto_codigo, '')) = '' THEN 'sem_produto'
                    WHEN dp.codigo IS NULL THEN 'produto_sem_dprecos'
                    WHEN LOWER(BTRIM(COALESCE(base.unid_venda, ''))) IN ('un', 'und', 'unid', 'unidade')
                         AND dp.ttc_min IS NOT NULL
                         AND (base.preco_unitario < dp.ttc_min - 0.01 OR base.preco_unitario > dp.ttc_max + 0.01)
                        THEN 'preco_unidade_fora_referencia'
                    WHEN LOWER(BTRIM(COALESCE(base.unid_venda, ''))) NOT IN ('un', 'und', 'unid', 'unidade')
                         AND dp.caixa_min IS NOT NULL
                         AND (base.preco_unitario < dp.caixa_min - 0.01 OR base.preco_unitario > dp.caixa_max + 0.01)
                        THEN 'preco_caixa_fora_referencia'
                    ELSE 'ok'
                END AS preco_status,
                base.payload,
                base.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM base
            JOIN {}.import_batches b ON b.id = base.batch_id
            LEFT JOIN dprecos_ref dp ON dp.codigo = base.produto_codigo
            """
        ).format(
            sql.Identifier(self.schema),
            price_ref_cte,
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
        )
        with conn.cursor() as cur:
            cur.execute(query)

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)


def _load_critica_operacao_rows(path: Path, *, expected_filial: str) -> list[CriticaOperacaoRow]:
    text = _read_text_with_fallback(path)
    parse_errors: list[str] = []
    rows: list[CriticaOperacaoRow] = []
    last_error = "Arquivo sem cabecalho."
    tried_delimiters: list[str] = []
    for delimiter in (_detect_delimiter(text), ";", ","):
        if delimiter in tried_delimiters:
            continue
        tried_delimiters.append(delimiter)
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            if reader.fieldnames is None:
                raise ValueError("Arquivo sem cabecalho.")
            headers = [str(header or "").strip() for header in reader.fieldnames]
            header_map = _build_header_map(headers)
            raw_rows = [
                {str(key or "").strip(): str(value or "").strip() for key, value in raw_row.items() if key is not None}
                for raw_row in reader
            ]
            rows = _build_critica_operacao_rows_from_mapping_rows(
                raw_rows,
                headers=headers,
                header_map=header_map,
                row_number_offset=2,
            )
            last_error = ""
            break
        except ValueError as exc:
            last_error = str(exc)
            parse_errors.append(f"{delimiter}: {exc}")
    if last_error:
        raise ValueError(last_error if not parse_errors else parse_errors[-1].split(": ", 1)[1])
    found_filiais = sorted({row.filial for row in rows if row.filial})
    if not rows:
        return rows
    if expected_filial and any(filial != expected_filial for filial in found_filiais):
        labels = ", ".join(found_filiais)
        raise ValueError(
            f"Arquivo invalido para a operacao {expected_filial}. Filial Origem encontrada: {labels or '-'}."
        )
    return rows


def _build_header_map(headers: list[str]) -> dict[str, str]:
    header_map: dict[str, str] = {}
    for actual in headers:
        normalized = "".join(char for char in str(actual or "").lower() if char.isalnum())
        canonical = HEADER_ALIASES.get(normalized)
        if canonical and canonical not in header_map:
            header_map[canonical] = actual
    missing_headers = sorted(EXPECTED_HEADERS - set(header_map))
    if missing_headers:
        raise ValueError(f"Arquivo invalido. Colunas obrigatorias ausentes: {', '.join(missing_headers)}")
    return header_map


def _build_critica_operacao_rows_from_mapping_rows(
    raw_rows: list[dict[str, Any]],
    *,
    headers: list[str],
    header_map: dict[str, str],
    row_number_offset: int,
) -> list[CriticaOperacaoRow]:
    rows: list[CriticaOperacaoRow] = []
    for index, row in enumerate(raw_rows, start=row_number_offset):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        filial = normalize_numeric_code(row.get(header_map["Filial Origem"], ""))
        pedido = normalize_numeric_code(row.get(header_map["Num Pedido"], ""))
        setor = normalize_numeric_code(row.get(header_map["Cod. Setor"], ""))
        cod_pdv = normalize_numeric_code(row.get(header_map["Cod. Cliente"], ""))
        produto_codigo = normalize_numeric_code(row.get(header_map["Cod. Produto"], ""))
        if not filial or not pedido or not setor or not cod_pdv:
            continue

        nome_produto = _clean_text(row.get(header_map["Nome Produto"], ""))
        preco_unitario = _parse_decimal_value(row.get(header_map["Preco Unit."], ""))
        minimo_politica = _parse_decimal_value(row.get(header_map["Preco Minimo"], ""))
        te_codigo = normalize_numeric_code(row.get(header_map["TE"], ""))

        criticas = [
            _clean_text(row.get(header_map["Ocorrencia 1"], "")),
            _clean_text(row.get(header_map["Ocorrencia 2"], "")),
        ]
        origem_pedido = _clean_text(row.get("Origem Pedido", ""))
        if _should_append_minimum_price_critica(preco_unitario, minimo_politica, origem_pedido):
            criticas.append(f"Preco abaixo do minimo informado ({_format_decimal_text(minimo_politica)})")

        rows.append(
            CriticaOperacaoRow(
                filial=filial,
                pedido=pedido,
                operacao=filial,
                cod_pdv=cod_pdv,
                nome_pdv=_clean_text(row.get(header_map["Nome Cliente"], "")),
                setor=setor,
                filial_setor_key=f"{filial}_{setor}",
                status_pedido=_clean_text(row.get(header_map["Status Pedido"], "")),
                total_pedido=_parse_decimal_value(row.get(header_map["Valor Pedido"], "")),
                total_cliente=_parse_decimal_value(row.get(header_map["Valor Pedido"], "")),
                critica_text=" | ".join(item for item in criticas if item),
                produto_codigo=produto_codigo,
                produto_key=produto_codigo,
                nome_produto=nome_produto,
                quantidade=_parse_decimal_value(row.get(header_map["Qtde"], "")),
                unid_venda=_clean_text(row.get(header_map["Unidade"], "")),
                preco_unitario=preco_unitario,
                preco_sem_adf=_parse_decimal_value(row.get(header_map["TTV s/ADF"], "")),
                minimo_politica=minimo_politica,
                tipo_movimento=normalize_numeric_code(row.get(header_map["Tipo Movimento"], "")),
                codigo_gv=normalize_numeric_code(row.get(header_map["Cod. Vendedor"], "")),
                codigo_pgv=normalize_numeric_code(row.get(header_map["Cod. Pedido SIV"], "")),
                te_codigo=te_codigo,
                source_row_number=index,
                payload=_row_to_payload(headers, row),
            )
        )
    return rows


def _summary_stats(rows: list[CriticaOperacaoRow]) -> dict[str, int]:
    pedido_keys = {(row.filial, row.pedido) for row in rows}
    unb_setores = {row.filial_setor_key for row in rows if row.filial_setor_key}
    produtos = {row.produto_codigo for row in rows if row.produto_codigo}
    pedido_produto_counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (row.filial, row.pedido, row.produto_codigo)
        pedido_produto_counts[key] = pedido_produto_counts.get(key, 0) + 1
    return {
        "unique_pedidos": len(pedido_keys),
        "unique_unb_setores": len(unb_setores),
        "unique_produtos": len(produtos),
        "duplicate_pedido_produto_keys": sum(1 for total in pedido_produto_counts.values() if total > 1),
        "rows_with_critica": sum(1 for row in rows if row.critica_text),
    }


def _is_meaningful_minimum(value: Decimal) -> bool:
    return value > Decimal("0") and value < Decimal("900")


def _should_append_minimum_price_critica(preco_unitario: Decimal, minimo_politica: Decimal, origem_pedido: str) -> bool:
    if not _is_meaningful_minimum(minimo_politica):
        return False
    if preco_unitario >= (minimo_politica - Decimal("0.01")):
        return False
    if str(origem_pedido or "").strip().upper() in B2B_PRICE_ORIGINS:
        return abs((preco_unitario - minimo_politica) / minimo_politica) >= B2B_PRICE_TOLERANCE
    return True


def _format_decimal_text(value: Decimal) -> str:
    text = f"{value:.2f}"
    return text.replace(".", ",")
