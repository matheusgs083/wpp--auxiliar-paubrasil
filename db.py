from __future__ import annotations

import atexit
from threading import Lock
from typing import Any

from psycopg_pool import ConnectionPool

_POOL_LOCK = Lock()
_POOLS: dict[tuple[str, int, int, int], ConnectionPool[Any]] = {}


def get_connection_pool(
    database_url: str,
    *,
    connect_timeout_seconds: float,
    min_size: int = 1,
    max_size: int = 10,
) -> ConnectionPool[Any]:
    normalized_url = str(database_url or "").strip()
    if not normalized_url:
        raise RuntimeError("URL do banco nao configurada.")

    normalized_timeout = max(int(connect_timeout_seconds), 1)
    normalized_min_size = max(int(min_size), 1)
    normalized_max_size = max(int(max_size), normalized_min_size)
    cache_key = (normalized_url, normalized_timeout, normalized_min_size, normalized_max_size)

    with _POOL_LOCK:
        pool = _POOLS.get(cache_key)
        if pool is None:
            pool = ConnectionPool(
                conninfo=normalized_url,
                min_size=normalized_min_size,
                max_size=normalized_max_size,
                open=True,
                timeout=max(float(connect_timeout_seconds), 5.0),
                kwargs={
                    "autocommit": False,
                    "connect_timeout": normalized_timeout,
                },
            )
            _POOLS[cache_key] = pool
        return pool


def close_all_connection_pools() -> None:
    with _POOL_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()

    for pool in pools:
        try:
            pool.close()
        except Exception:
            continue


atexit.register(close_all_connection_pools)
