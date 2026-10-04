from __future__ import annotations

import json
import threading
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class LigaEntregaDashboardSnapshotStore:
    """Persiste o resultado normalizado do painel da Liga no PostgreSQL.

    Os CSVs continuam sendo a fonte de auditoria. O snapshot evita reler e
    recalcular todos os arquivos depois de reiniciar o processo ou o container.
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
                        CREATE TABLE IF NOT EXISTS {}.liga_entrega_dashboard_snapshots (
                            competencia VARCHAR(7) NOT NULL,
                            period VARCHAR(12) NOT NULL,
                            signature TEXT NOT NULL,
                            payload JSONB NOT NULL,
                            generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            PRIMARY KEY (competencia, period)
                        )
                        """
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS liga_entrega_dashboard_snapshots_generated_idx "
                        "ON {}.liga_entrega_dashboard_snapshots (generated_at DESC)"
                    ).format(sql.Identifier(self.schema))
                )
            conn.commit()
            self._schema_ready = True

    def get(self, *, competencia: str, period: str, signature: str) -> dict[str, Any] | None:
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        sql.SQL(
                            "SELECT payload FROM {}.liga_entrega_dashboard_snapshots "
                            "WHERE competencia = %s AND period = %s AND signature = %s"
                        ).format(sql.Identifier(self.schema)),
                        (competencia, period, signature),
                    )
                    row = cur.fetchone()
                return dict(row["payload"]) if row and isinstance(row.get("payload"), dict) else None
        except Exception:
            return None

    def put(self, *, competencia: str, period: str, signature: str, payload: dict[str, Any]) -> None:
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {}.liga_entrega_dashboard_snapshots
                                (competencia, period, signature, payload, generated_at)
                            VALUES (%s, %s, %s, %s::jsonb, NOW())
                            ON CONFLICT (competencia, period)
                            DO UPDATE SET signature = EXCLUDED.signature,
                                          payload = EXCLUDED.payload,
                                          generated_at = NOW()
                            """
                        ).format(sql.Identifier(self.schema)),
                        (competencia, period, signature, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
                    )
                conn.commit()
        except Exception:
            # O cache SQL nunca pode impedir o painel de usar a fonte original.
            return
