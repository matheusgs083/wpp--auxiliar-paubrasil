from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


DEFAULT_BATCH_RETENTION = 3


def ensure_dataset_state_table(conn: psycopg.Connection[Any], schema: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.dataset_state (
                    dataset_name VARCHAR(80) PRIMARY KEY,
                    active_batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                    activated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            ).format(sql.Identifier(schema), sql.Identifier(schema))
        )
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS dataset_state_active_batch_idx ON {}.dataset_state (active_batch_id)").format(
                sql.Identifier(schema)
            )
        )


def activate_import_batch(
    conn: psycopg.Connection[Any],
    schema: str,
    dataset_name: str,
    batch_id: int,
) -> None:
    ensure_dataset_state_table(conn, schema)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {}.dataset_state (dataset_name, active_batch_id, activated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (dataset_name)
                DO UPDATE SET
                    active_batch_id = EXCLUDED.active_batch_id,
                    activated_at = NOW()
                """
            ).format(sql.Identifier(schema)),
            (dataset_name, batch_id),
        )


def get_active_import_batch_id(
    conn: psycopg.Connection[Any],
    schema: str,
    dataset_name: str,
) -> int | None:
    ensure_dataset_state_table(conn, schema)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT active_batch_id
                FROM {}.dataset_state
                WHERE dataset_name = %s
                """
            ).format(sql.Identifier(schema)),
            (dataset_name,),
        )
        row = cur.fetchone()
    if not row:
        return None
    active_batch_id = row.get("active_batch_id")
    return int(active_batch_id) if active_batch_id is not None else None


def get_latest_import_batch_id(
    conn: psycopg.Connection[Any],
    schema: str,
    dataset_name: str,
) -> int | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT id
                FROM {}.import_batches
                WHERE dataset_name = %s
                ORDER BY imported_at DESC, id DESC
                LIMIT 1
                """
            ).format(sql.Identifier(schema)),
            (dataset_name,),
        )
        row = cur.fetchone()
    if not row:
        return None
    batch_id = row.get("id")
    return int(batch_id) if batch_id is not None else None


def resolve_effective_import_batch_id(
    conn: psycopg.Connection[Any],
    schema: str,
    dataset_name: str,
    *,
    activate_if_missing: bool = False,
) -> int | None:
    active_batch_id = get_active_import_batch_id(conn, schema, dataset_name)
    if active_batch_id is not None:
        return active_batch_id

    latest_batch_id = get_latest_import_batch_id(conn, schema, dataset_name)
    if latest_batch_id is not None and activate_if_missing:
        activate_import_batch(conn, schema, dataset_name, latest_batch_id)
    return latest_batch_id


def prune_import_batches(
    conn: psycopg.Connection[Any],
    schema: str,
    dataset_name: str,
    *,
    keep_last: int = DEFAULT_BATCH_RETENTION,
) -> int:
    keep_count = max(int(keep_last), 1)
    active_batch_id = get_active_import_batch_id(conn, schema, dataset_name)
    query = sql.SQL(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (ORDER BY imported_at DESC, id DESC) AS rn
            FROM {}.import_batches
            WHERE dataset_name = %s
        ),
        to_delete AS (
            SELECT id
            FROM ranked
            WHERE rn > %s
              AND (%s::BIGINT IS NULL OR id <> %s::BIGINT)
        )
        DELETE FROM {}.import_batches AS b
        USING to_delete d
        WHERE b.id = d.id
        RETURNING b.id
        """
    ).format(sql.Identifier(schema), sql.Identifier(schema))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (dataset_name, keep_count, active_batch_id, active_batch_id))
        deleted_rows = cur.fetchall()
    return len(deleted_rows)
