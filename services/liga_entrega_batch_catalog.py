from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class LigaEntregaBatchCatalog:
    """Registro, no PostgreSQL, de cada remessa de relatório da Liga Entrega.

    Os CSVs continuam guardados em exports/liga_entrega_reports como arquivo de
    auditoria. Este catálogo responde "qual foi a última remessa de cada rotina"
    sem precisar varrer as pastas, o que levava vários segundos.
    """

    def __init__(self, *, database_url: str, schema: str = "reports", connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "")
        self.schema = str(schema or "reports")
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3), 1.0)
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _connect(self) -> psycopg.Connection[Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)

    def _ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.liga_entrega_batches (
                            batch_id TEXT PRIMARY KEY,
                            routine VARCHAR(64) NOT NULL,
                            reference_date TEXT NOT NULL DEFAULT '',
                            stored_at TEXT NOT NULL DEFAULT '',
                            manifest JSONB NOT NULL,
                            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS liga_entrega_batches_routine_idx "
                        "ON {}.liga_entrega_batches (routine, stored_at DESC)"
                    ).format(sql.Identifier(self.schema))
                )
            conn.commit()
            self._schema_ready = True

    def record(self, manifests: Iterable[Mapping[str, Any]]) -> int:
        """Grava as remessas; uma remessa já registrada é ignorada. Devolve quantas entraram."""
        rows = [
            (
                str(item.get("batch_id") or ""),
                str(item.get("routine") or ""),
                str(item.get("reference_date") or ""),
                str(item.get("stored_at") or ""),
                json.dumps(dict(item), ensure_ascii=False),
            )
            for item in manifests
            if item.get("batch_id") and item.get("routine")
        ]
        if not rows:
            return 0
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                inserted = 0
                for row in rows:
                    cur.execute(
                        sql.SQL(
                            "INSERT INTO {}.liga_entrega_batches (batch_id, routine, reference_date, stored_at, manifest) "
                            "VALUES (%s, %s, %s, %s, %s::jsonb) ON CONFLICT (batch_id) DO NOTHING"
                        ).format(sql.Identifier(self.schema)),
                        row,
                    )
                    inserted += cur.rowcount or 0
            conn.commit()
        return inserted

    def count(self, routine: str) -> int:
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.liga_entrega_batches WHERE routine = %s").format(sql.Identifier(self.schema)),
                    (routine,),
                )
                row = cur.fetchone()
        return int(row[0] if row else 0)

    def latest(self, routine: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT manifest FROM {}.liga_entrega_batches WHERE routine = %s "
                        "ORDER BY stored_at DESC, recorded_at DESC LIMIT 1"
                    ).format(sql.Identifier(self.schema)),
                    (routine,),
                )
                row = cur.fetchone()
        return _manifest(row)

    def list(self, routine: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT manifest FROM {}.liga_entrega_batches WHERE routine = %s "
                        "ORDER BY reference_date, stored_at"
                    ).format(sql.Identifier(self.schema)),
                    (routine,),
                )
                rows = cur.fetchall()
        return [item for item in (_manifest(row) for row in rows) if item is not None]


def _manifest(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    payload = row.get("manifest")
    if isinstance(payload, str):
        payload = json.loads(payload)
    return dict(payload) if isinstance(payload, dict) else None
