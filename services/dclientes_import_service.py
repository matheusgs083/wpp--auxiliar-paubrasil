from __future__ import annotations

import csv
import hashlib
import time
from collections import Counter, defaultdict
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
        DCLIENTES_CSV_SPEC,
        build_required_indexes,
        normalize_header_name,
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
        DCLIENTES_CSV_SPEC,
        build_required_indexes,
        normalize_header_name,
        validate_csv_source,
    )
    from bot_api.services.import_publication import (
        activate_import_batch,
        ensure_dataset_state_table,
        prune_import_batches,
        resolve_effective_import_batch_id,
    )

from bot_api.services.dsetores_import_service import ensure_dsetores_schema

NORMALIZED_CODE_HEADERS = {
    "filial",
    "cod pdv",
    "setor vde",
    "area vde",
    "gv vde",
    "setor vdi",
    "area vdi",
    "gv vdi",
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
_DEADLOCK_RETRY_ATTEMPTS = 3
_DEADLOCK_RETRY_BASE_SECONDS = 0.35


@dataclass(frozen=True)
class DClientesSummary:
    file_path: str
    rows: int
    columns: int
    unique_filiais: int
    unique_client_codes: int
    repeated_client_codes: int
    multi_filial_client_codes: int
    unique_filial_client_pairs: int
    duplicated_filial_client_pairs: int
    unique_setor_vde: int
    clients_with_multiple_setor_vde: int
    filiais: list[tuple[str, int]]
    top_setor_vde: list[tuple[str, int]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DClientesImportService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)

    def validate_csv(self, file_path: Path):
        return validate_csv_source(file_path, DCLIENTES_CSV_SPEC)

    def summarize_csv(self, file_path: Path, *, validate: bool = True) -> DClientesSummary:
        if validate:
            self.validate_csv(file_path).ensure_valid()

        rows = 0
        filiais = Counter()
        client_to_rows = Counter()
        client_to_filiais: dict[str, set[str]] = defaultdict(set)
        pair_counter = Counter()
        setor_counter = Counter()
        client_to_setores: dict[str, set[str]] = defaultdict(set)

        with file_path.open("r", encoding="cp1252", newline="") as fp:
            reader = csv.reader(fp, delimiter=";")
            header = next(reader)
            indexes = _required_indexes(header)

            for row in reader:
                if not row or not any(str(value or "").strip() for value in row):
                    continue
                rows += 1
                filial = _normalize_code_value(row[indexes["Filial"]])
                cod_pdv = _normalize_code_value(row[indexes["Cod PDV"]])
                setor_vde = _normalize_code_value(row[indexes["Setor VDE"]])

                filiais[filial] += 1
                client_to_rows[cod_pdv] += 1
                client_to_filiais[cod_pdv].add(filial)
                pair_counter[(filial, cod_pdv)] += 1
                if setor_vde:
                    setor_counter[setor_vde] += 1
                    client_to_setores[cod_pdv].add(setor_vde)

        return DClientesSummary(
            file_path=str(file_path),
            rows=rows,
            columns=len(header),
            unique_filiais=len(filiais),
            unique_client_codes=len(client_to_rows),
            repeated_client_codes=sum(1 for _, count in client_to_rows.items() if count > 1),
            multi_filial_client_codes=sum(1 for _, mapped_filiais in client_to_filiais.items() if len(mapped_filiais) > 1),
            unique_filial_client_pairs=len(pair_counter),
            duplicated_filial_client_pairs=sum(1 for _, count in pair_counter.items() if count > 1),
            unique_setor_vde=len(setor_counter),
            clients_with_multiple_setor_vde=sum(1 for _, setores in client_to_setores.items() if len(setores) > 1),
            filiais=filiais.most_common(),
            top_setor_vde=setor_counter.most_common(20),
        )

    def import_csv(
        self,
        file_path: Path,
        reference_date: date | None = None,
        summary: DClientesSummary | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        if not file_path.exists():
            raise FileNotFoundError(f"Arquivo nao encontrado: {file_path}")

        if summary is None:
            summary = self.summarize_csv(file_path)
            summary_payload = summary.to_dict()
            total_rows = summary.rows
        elif isinstance(summary, DClientesSummary):
            summary_payload = summary.to_dict()
            total_rows = summary.rows
        else:
            summary_payload = dict(summary)
            total_rows = int(summary_payload.get("rows") or summary_payload.get("total_rows") or 0)
        batch_date = reference_date or datetime.fromtimestamp(file_path.stat().st_mtime).date()
        file_hash = _sha256(file_path)

        batch_id = self._run_with_deadlock_retry(
            operation_name="carga dclientes",
            callback=lambda: self._run_snapshot_stage(
                file_path=file_path,
                batch_date=batch_date,
                file_hash=file_hash,
                total_rows=total_rows,
            ),
        )
        self._run_with_deadlock_retry(
            operation_name="publicacao dclientes",
            callback=lambda: self._run_publish_stage(batch_id=batch_id),
        )

        result = summary_payload
        result.update(
            {
                "batch_id": batch_id,
                "reference_date": batch_date.isoformat(),
                "file_hash": file_hash,
                "schema": self.schema,
                "normalized_codes": True,
                "replaced_previous_batches": False,
                "published_as_active_batch": True,
            }
        )
        return result

    def _run_snapshot_stage(self, *, file_path: Path, batch_date: date, file_hash: str, total_rows: int) -> int:
        with self._connect() as conn:
            self._ensure_schema(conn)
            batch_id = self._insert_batch(conn, file_path, batch_date, file_hash, total_rows)
            self._insert_snapshot_rows(conn, file_path, batch_id)
            self._hydrate_scope_columns(conn, batch_id=batch_id)
            conn.commit()
            return batch_id

    def _run_publish_stage(self, *, batch_id: int) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            activate_import_batch(conn, self.schema, "dclientes", batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, "dclientes", keep_last=3)
            conn.commit()

    def _run_with_deadlock_retry(self, *, operation_name: str, callback: Any) -> Any:
        max_attempts = max(1, int(_DEADLOCK_RETRY_ATTEMPTS))
        for attempt in range(1, max_attempts + 1):
            try:
                return callback()
            except psycopg.errors.DeadlockDetected as exc:
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"Falha na {operation_name} apos {max_attempts} tentativa(s) por deadlock."
                    ) from exc
                time.sleep(_DEADLOCK_RETRY_BASE_SECONDS * attempt)

    def refresh_latest_view(self) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

        with self._connect() as conn:
            self._ensure_schema(conn)
            active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dclientes", activate_if_missing=True)
            if active_batch_id is not None:
                self._hydrate_scope_columns(conn, batch_id=active_batch_id)
            self._create_latest_view(conn)
            conn.commit()

        return {
            "ok": True,
            "schema": self.schema,
            "view": f"{self.schema}.dclientes_latest",
            "normalized_codes": True,
            "active_batch_id": active_batch_id,
        }

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
                    CREATE TABLE IF NOT EXISTS {}.dclientes_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        row_number INTEGER NOT NULL,
                        empresa TEXT,
                        filial VARCHAR(16) NOT NULL,
                        cod_pdv VARCHAR(32) NOT NULL,
                        documento TEXT,
                        nome_fantasia TEXT,
                        razao_social TEXT,
                        status_pdv TEXT,
                        setor_vde VARCHAR(32),
                        area_vde VARCHAR(32),
                        gv_vde VARCHAR(32),
                        gv_vde_resolved VARCHAR(32) NOT NULL DEFAULT '',
                        dc_vde VARCHAR(32) NOT NULL DEFAULT '',
                        filial_setor_key TEXT NOT NULL DEFAULT '',
                        filial_gv_key TEXT NOT NULL DEFAULT '',
                        filial_dc_key TEXT NOT NULL DEFAULT '',
                        setor_vdi VARCHAR(32),
                        area_vdi VARCHAR(32),
                        gv_vdi VARCHAR(32),
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, row_number),
                        UNIQUE (batch_id, filial, cod_pdv)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL("ALTER TABLE {}.dclientes_snapshot ADD COLUMN IF NOT EXISTS gv_vde_resolved VARCHAR(32) NOT NULL DEFAULT ''").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("ALTER TABLE {}.dclientes_snapshot ADD COLUMN IF NOT EXISTS dc_vde VARCHAR(32) NOT NULL DEFAULT ''").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("ALTER TABLE {}.dclientes_snapshot ADD COLUMN IF NOT EXISTS filial_setor_key TEXT NOT NULL DEFAULT ''").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("ALTER TABLE {}.dclientes_snapshot ADD COLUMN IF NOT EXISTS filial_gv_key TEXT NOT NULL DEFAULT ''").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("ALTER TABLE {}.dclientes_snapshot ADD COLUMN IF NOT EXISTS filial_dc_key TEXT NOT NULL DEFAULT ''").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS dclientes_snapshot_cod_idx ON {}.dclientes_snapshot (cod_pdv)").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS dclientes_snapshot_filial_cod_idx ON {}.dclientes_snapshot (filial, cod_pdv)").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_cod_idx ON {}.dclientes_snapshot (batch_id, filial, cod_pdv)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS dclientes_snapshot_setor_vde_idx ON {}.dclientes_snapshot (setor_vde)").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_setor_vde_idx ON {}.dclientes_snapshot (batch_id, setor_vde)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_setor_vde_idx ON {}.dclientes_snapshot (batch_id, filial, setor_vde)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_gv_vde_idx ON {}.dclientes_snapshot (batch_id, gv_vde)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_gv_vde_idx ON {}.dclientes_snapshot (batch_id, filial, gv_vde)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_gv_resolved_idx ON {}.dclientes_snapshot (batch_id, filial, gv_vde_resolved)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_dc_vde_idx ON {}.dclientes_snapshot (batch_id, filial, dc_vde)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_setor_key_idx ON {}.dclientes_snapshot (batch_id, filial_setor_key)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_gv_key_idx ON {}.dclientes_snapshot (batch_id, filial_gv_key)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_filial_dc_key_idx ON {}.dclientes_snapshot (batch_id, filial_dc_key)"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_documento_digits_idx
                    ON {}.dclientes_snapshot (
                        batch_id,
                        (REGEXP_REPLACE(COALESCE(documento, ''), '[^0-9]', '', 'g'))
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_visit_day_idx
                    ON {}.dclientes_snapshot (
                        batch_id,
                        (BTRIM(COALESCE(payload ->> 'Dia de Visita do VDE', '')))
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_nome_fantasia_search_idx
                    ON {}.dclientes_snapshot (
                        batch_id,
                        (
                            REGEXP_REPLACE(
                                TRANSLATE(LOWER(COALESCE(nome_fantasia, '')), {source}, {target}),
                                '\\s+',
                                ' ',
                                'g'
                            )
                        )
                    )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    source=sql.Literal(_ACCENTED_SQL_SOURCE),
                    target=sql.Literal(_ACCENTED_SQL_TARGET),
                )
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS dclientes_snapshot_batch_razao_social_search_idx
                    ON {}.dclientes_snapshot (
                        batch_id,
                        (
                            REGEXP_REPLACE(
                                TRANSLATE(LOWER(COALESCE(razao_social, '')), {source}, {target}),
                                '\\s+',
                                ' ',
                                'g'
                            )
                        )
                    )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    source=sql.Literal(_ACCENTED_SQL_SOURCE),
                    target=sql.Literal(_ACCENTED_SQL_TARGET),
                )
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS dclientes_snapshot_nome_fantasia_trgm_idx
                    ON {}.dclientes_snapshot
                    USING gin (
                        (
                            REGEXP_REPLACE(
                                TRANSLATE(LOWER(COALESCE(nome_fantasia, '')), {source}, {target}),
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
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS dclientes_snapshot_razao_social_trgm_idx
                    ON {}.dclientes_snapshot
                    USING gin (
                        (
                            REGEXP_REPLACE(
                                TRANSLATE(LOWER(COALESCE(razao_social, '')), {source}, {target}),
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
            ensure_dataset_state_table(conn, self.schema)
        ensure_dsetores_schema(conn, self.schema)

    def _insert_batch(
        self,
        conn: psycopg.Connection[Any],
        file_path: Path,
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
            cur.execute(query, ("dclientes", str(file_path), file_hash, reference_date, total_rows))
            row = cur.fetchone()
        return int(row["id"])

    def _insert_snapshot_rows(self, conn: psycopg.Connection[Any], file_path: Path, batch_id: int) -> None:
        copy_query = sql.SQL(
            """
            COPY {}.dclientes_snapshot (
                batch_id,
                row_number,
                empresa,
                filial,
                cod_pdv,
                documento,
                nome_fantasia,
                razao_social,
                status_pdv,
                setor_vde,
                area_vde,
                gv_vde,
                setor_vdi,
                area_vdi,
                gv_vdi,
                payload
            )
            FROM STDIN
            """
        ).format(sql.Identifier(self.schema))

        with conn.cursor() as cur:
            with cur.copy(copy_query) as copy:
                for payload_row in _iter_dclientes_snapshot_rows(file_path=file_path, batch_id=batch_id):
                    copy.write_row(payload_row)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        active_batch_id = resolve_effective_import_batch_id(conn, self.schema, "dclientes", activate_if_missing=True)
        where_clause = (
            sql.SQL("s.batch_id = {}").format(sql.Literal(active_batch_id))
            if active_batch_id is not None
            else sql.SQL("FALSE")
        )
        query = sql.SQL(
            """
            CREATE OR REPLACE VIEW {}.dclientes_latest AS
            SELECT
                s.batch_id,
                s.row_number,
                s.empresa,
                s.filial,
                s.cod_pdv,
                CONCAT(s.filial, '_', s.cod_pdv) AS unb_cliente,
                s.documento,
                s.nome_fantasia,
                s.razao_social,
                s.status_pdv,
                s.setor_vde,
                s.area_vde,
                s.gv_vde,
                s.gv_vde_resolved,
                s.dc_vde,
                s.filial_setor_key,
                s.filial_gv_key,
                s.filial_dc_key,
                s.setor_vdi,
                s.area_vdi,
                s.gv_vdi,
                s.payload,
                s.imported_at,
                b.reference_date,
                b.source_file,
                b.file_hash,
                b.imported_at AS batch_imported_at
            FROM {}.dclientes_snapshot s
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

    def _hydrate_scope_columns(self, conn: psycopg.Connection[Any], batch_id: int | None = None) -> None:
        update_base_query = sql.SQL(
            """
            UPDATE {}.dclientes_snapshot AS s
            SET
                gv_vde_resolved = '',
                dc_vde = '',
                filial_setor_key = CASE
                    WHEN BTRIM(COALESCE(s.setor_vde, '')) <> '' THEN CONCAT(s.filial, '_', s.setor_vde)
                    ELSE ''
                END,
                filial_gv_key = '',
                filial_dc_key = ''
            {}
            """
        ).format(
            sql.Identifier(self.schema),
            sql.SQL("WHERE s.batch_id = %s") if batch_id is not None else sql.SQL(""),
        )
        update_join_query = sql.SQL(
            """
            UPDATE {}.dclientes_snapshot AS s
            SET
                gv_vde_resolved = COALESCE(NULLIF(ds.gv, ''), ''),
                dc_vde = COALESCE(NULLIF(ds.dc, ''), ''),
                filial_gv_key = CASE
                    WHEN BTRIM(COALESCE(ds.gv, '')) <> '' THEN CONCAT(s.filial, '_', ds.gv)
                    ELSE ''
                END,
                filial_dc_key = CASE
                    WHEN BTRIM(COALESCE(ds.dc, '')) <> '' THEN CONCAT(s.filial, '_', ds.dc)
                    ELSE ''
                END
            FROM {}.dsetores_latest ds
            WHERE ds.filial = s.filial
              AND ds.setor = s.setor_vde
              {}
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.SQL("AND s.batch_id = %s") if batch_id is not None else sql.SQL(""),
        )
        params = [batch_id] if batch_id is not None else []
        with conn.cursor() as cur:
            cur.execute(update_base_query, params)
            cur.execute(update_join_query, params)

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


def _required_indexes(header: list[str]) -> dict[str, int]:
    return build_required_indexes(header, DCLIENTES_CSV_SPEC)


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


def _iter_dclientes_snapshot_rows(*, file_path: Path, batch_id: int) -> Any:
    with file_path.open("r", encoding="cp1252", newline="") as fp:
        reader = csv.reader(fp, delimiter=";")
        header = next(reader)
        indexes = _required_indexes(header)
        next_row_number = 1
        for row in reader:
            if not row or not any(str(value or "").strip() for value in row):
                continue
            record = _row_to_record(header, row)
            yield (
                batch_id,
                next_row_number,
                row[indexes["Empresa"]].strip(),
                _normalize_code_value(row[indexes["Filial"]]),
                _normalize_code_value(row[indexes["Cod PDV"]]),
                row[indexes["Documento"]].strip(),
                row[indexes["Nome Fantasia"]].strip(),
                row[indexes["Razao Social"]].strip(),
                row[indexes["Status do PDV"]].strip(),
                _normalize_code_value(row[indexes["Setor VDE"]]),
                _normalize_code_value(row[indexes["Area VDE"]]),
                _normalize_code_value(row[indexes["GV VDE"]]),
                _normalize_code_value(row[indexes["Setor VDI"]]),
                _normalize_code_value(row[indexes["Area VDI"]]),
                _normalize_code_value(row[indexes["GV VDI"]]),
                Jsonb(record),
            )
            next_row_number += 1


def _normalize_schema(value: str) -> str:
    cleaned = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return cleaned or "reports"


def _sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
