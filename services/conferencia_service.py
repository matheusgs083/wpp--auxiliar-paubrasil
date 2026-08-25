from __future__ import annotations

import re
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bot_api.db import get_connection_pool


@dataclass(frozen=True)
class ConferenciaItemDraft:
    cod_item: str
    descricao: str
    tipo_item: str
    categoria: str
    grupo_contagem: str
    unidade: str
    total_sistema: Decimal
    valor_unitario: Decimal
    payload: dict[str, Any]


class ConferenciaService:
    def __init__(
        self,
        *,
        database_url: str,
        schema: str,
        connect_timeout_seconds: float = 3.0,
        filial_labels: dict[str, str] | None = None,
    ) -> None:
        self.database_url = str(database_url or "").strip()
        self.schema = _clean_identifier(schema, "reports")
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3), 1.0)
        self.filial_labels = dict(filial_labels or {})
        self._pool = None

    def ensure_schema(self) -> bool:
        if not self.database_url:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.conferencia_mapas (
                            id BIGSERIAL PRIMARY KEY,
                            caixa_date DATE NOT NULL,
                            filial TEXT NOT NULL,
                            mapa TEXT NOT NULL,
                            placa TEXT NOT NULL DEFAULT '',
                            motorista TEXT NOT NULL DEFAULT '',
                            ajudante1 TEXT NOT NULL DEFAULT '',
                            ajudante2 TEXT NOT NULL DEFAULT '',
                            status TEXT NOT NULL DEFAULT 'aberta',
                            source_job_id TEXT NOT NULL DEFAULT '',
                            source_payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            UNIQUE (caixa_date, filial, mapa)
                        )
                        """
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.conferencia_itens (
                            id BIGSERIAL PRIMARY KEY,
                            conferencia_id BIGINT NOT NULL REFERENCES {}.conferencia_mapas(id) ON DELETE CASCADE,
                            cod_item TEXT NOT NULL,
                            descricao TEXT NOT NULL DEFAULT '',
                            tipo_item TEXT NOT NULL DEFAULT '',
                            categoria TEXT NOT NULL DEFAULT '',
                            grupo_contagem TEXT NOT NULL DEFAULT '',
                            unidade TEXT NOT NULL DEFAULT '',
                            total_sistema NUMERIC(14, 3) NOT NULL DEFAULT 0,
                            valor_unitario NUMERIC(14, 4) NOT NULL DEFAULT 0,
                            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            UNIQUE (conferencia_id, cod_item)
                        )
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.conferencia_contagens (
                            item_id BIGINT PRIMARY KEY REFERENCES {}.conferencia_itens(id) ON DELETE CASCADE,
                            contagem_real NUMERIC(14, 3),
                            contagem_vazia NUMERIC(14, 3),
                            contagem_caixas NUMERIC(14, 3),
                            contagem_unidades NUMERIC(14, 3),
                            observacao TEXT NOT NULL DEFAULT '',
                            updated_by TEXT NOT NULL DEFAULT '',
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
                )
                for column_name in ("contagem_vazia", "contagem_caixas", "contagem_unidades"):
                    cur.execute(
                        sql.SQL("ALTER TABLE {}.conferencia_contagens ADD COLUMN IF NOT EXISTS {} NUMERIC(14, 3)").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(column_name),
                        )
                    )
                cur.execute(
                    sql.SQL("CREATE INDEX IF NOT EXISTS conferencia_mapas_date_filial_idx ON {}.conferencia_mapas (caixa_date DESC, filial, mapa)").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL("CREATE INDEX IF NOT EXISTS conferencia_itens_busca_idx ON {}.conferencia_itens (conferencia_id, grupo_contagem, tipo_item)").format(
                        sql.Identifier(self.schema)
                    )
                )
            conn.commit()
        return True

    def sync_from_promax(self, payload: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_schema()
        caixa_date = _parse_date(payload.get("data") or payload.get("caixa_date"))
        filial = _normalize_filial(payload.get("filial"))
        mapa = str(payload.get("mapa") or "").strip()
        if not filial:
            raise ValueError("Filial da conferencia nao informada.")
        if not mapa:
            raise ValueError("Mapa da conferencia nao informado.")
        _assert_filial_allowed(filial, context)

        result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        dados_030303 = _extract_030303_fields(result_payload)
        item_drafts = _extract_030302_items(result_payload)
        username = str((context or {}).get("username") or (context or {}).get("worker_id") or "promax-worker")

        with self._connect() as conn:
            product_lookup = self._load_product_lookup(conn, {item.cod_item for item in item_drafts})
            material_lookup = self._load_material_lookup(conn, {item.cod_item for item in item_drafts})
            garrafeira_lookup = self._load_garrafeira_lookup(conn, {item.cod_item for item in item_drafts})
            enriched = [
                _enrich_item(
                    item,
                    product_lookup.get(item.cod_item),
                    material_lookup.get(item.cod_item),
                    garrafeira_lookup.get(item.cod_item),
                )
                for item in item_drafts
            ]
            grouped_items = _aggregate_conferencia_items(enriched)
            with conn.cursor(row_factory=dict_row) as cur:
                dados_030303 = _merge_identity_fallback(
                    dados_030303,
                    self._lookup_route_identity(cur, filial=filial, mapa=mapa),
                )
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.conferencia_mapas AS current_map (
                            caixa_date, filial, mapa, placa, motorista, ajudante1, ajudante2,
                            source_job_id, source_payload, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (caixa_date, filial, mapa) DO UPDATE SET
                            placa = CASE WHEN EXCLUDED.placa <> '' AND {} THEN EXCLUDED.placa ELSE current_map.placa END,
                            motorista = CASE WHEN EXCLUDED.motorista <> '' AND {} THEN EXCLUDED.motorista ELSE current_map.motorista END,
                            ajudante1 = CASE WHEN EXCLUDED.ajudante1 <> '' AND {} THEN EXCLUDED.ajudante1 ELSE current_map.ajudante1 END,
                            ajudante2 = CASE WHEN EXCLUDED.ajudante2 <> '' AND {} THEN EXCLUDED.ajudante2 ELSE current_map.ajudante2 END,
                            status = 'aberta',
                            source_job_id = EXCLUDED.source_job_id,
                            source_payload = EXCLUDED.source_payload,
                            updated_at = NOW()
                        RETURNING id
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        _sql_blankish_alias("current_map", "placa"),
                        _sql_blankish_alias("current_map", "motorista"),
                        _sql_blankish_alias("current_map", "ajudante1"),
                        _sql_blankish_alias("current_map", "ajudante2"),
                    ),
                    (
                        caixa_date,
                        filial,
                        mapa,
                        dados_030303.get("placa") or "",
                        dados_030303.get("motorista") or "",
                        dados_030303.get("ajudante1") or "",
                        dados_030303.get("ajudante2") or "",
                        str(payload.get("job_id") or result_payload.get("job_id") or ""),
                        Jsonb(_json_safe(result_payload)),
                    ),
                )
                conferencia_id = int(cur.fetchone()["id"])
                for item in grouped_items:
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {}.conferencia_itens (
                                conferencia_id, cod_item, descricao, tipo_item, categoria, grupo_contagem,
                                unidade, total_sistema, valor_unitario, payload, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (conferencia_id, cod_item) DO UPDATE SET
                                descricao = EXCLUDED.descricao,
                                tipo_item = EXCLUDED.tipo_item,
                                categoria = EXCLUDED.categoria,
                                grupo_contagem = EXCLUDED.grupo_contagem,
                                unidade = EXCLUDED.unidade,
                                total_sistema = EXCLUDED.total_sistema,
                                valor_unitario = EXCLUDED.valor_unitario,
                                payload = EXCLUDED.payload,
                                updated_at = NOW()
                            """
                        ).format(sql.Identifier(self.schema)),
                        (
                            conferencia_id,
                            item.cod_item,
                            item.descricao,
                            item.tipo_item,
                            item.categoria,
                            item.grupo_contagem,
                            item.unidade,
                            item.total_sistema,
                            item.valor_unitario,
                            Jsonb(_json_safe(item.payload)),
                        ),
                    )
                cur.execute(
                    sql.SQL(
                        """
                        SELECT COUNT(*) AS total,
                               COUNT(c.item_id) AS conferidos
                        FROM {}.conferencia_itens i
                        LEFT JOIN {}.conferencia_contagens c ON c.item_id = i.id
                        WHERE i.conferencia_id = %s
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(self.schema)),
                    (conferencia_id,),
                )
                stats = dict(cur.fetchone() or {})
            conn.commit()
        return {
            "ok": True,
            "conferencia_id": conferencia_id,
            "filial": filial,
            "mapa": mapa,
            "created_by": username,
            "itens": len(grouped_items),
            "itens_extraidos_030302": len(item_drafts),
            "conferidos": int(stats.get("conferidos") or 0),
            "dados_030302_found": bool(item_drafts),
            "dados_030303_found": any(dados_030303.values()),
        }

    def _lookup_route_identity(self, cur: Any, *, filial: str, mapa: str) -> dict[str, str]:
        cur.execute(
            sql.SQL(
                """
                SELECT placa, motorista, ajudante1, ajudante2
                FROM {}.conferencia_mapas
                WHERE filial = %s
                  AND mapa = %s
                  AND source_job_id = '03114902'
                ORDER BY caixa_date DESC, updated_at DESC
                LIMIT 1
                """
            ).format(sql.Identifier(self.schema)),
            (_normalize_filial(filial), str(mapa or "").strip()),
        )
        row = cur.fetchone()
        if not row:
            return {}
        return {
            "placa": _clean_select_text(row.get("placa"), keep_code=True),
            "motorista": _clean_select_text(row.get("motorista")),
            "ajudante1": _clean_select_text(row.get("ajudante1")),
            "ajudante2": _clean_select_text(row.get("ajudante2")),
        }

    def list_mapas(
        self,
        *,
        data: Any,
        filial: str = "",
        search: str = "",
        context: dict[str, Any] | None = None,
        reveal_totals: bool = False,
    ) -> dict[str, Any]:
        self.ensure_schema()
        caixa_date = _parse_date(data)
        clean_filial = _normalize_filial(filial)
        allowed_filiais = _allowed_filiais(context)
        if clean_filial:
            _assert_filial_allowed(clean_filial, context)
        self._sync_open_mapas_from_03114902(
            caixa_date=caixa_date,
            filial=clean_filial,
            allowed_filiais=allowed_filiais,
        )
        clean_search = str(search or "").strip().lower()
        where = ["m.caixa_date <= %s", "m.status IN ('aberta', 'aberta_03114902')"]
        params: list[Any] = [caixa_date]
        if clean_filial:
            where.append("m.filial = %s")
            params.append(clean_filial)
        elif allowed_filiais is not None:
            where.append("m.filial = ANY(%s)")
            params.append(sorted(allowed_filiais))
        if clean_search:
            where.append("(LOWER(m.mapa) LIKE %s OR LOWER(m.motorista) LIKE %s OR LOWER(m.placa) LIKE %s)")
            token = f"%{clean_search}%"
            params.extend([token, token, token])

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        WITH latest_maps AS (
                            SELECT DISTINCT ON (m.filial, m.mapa) m.*
                            FROM {}.conferencia_mapas m
                            WHERE {}
                            ORDER BY m.filial, m.mapa, m.caixa_date DESC, m.updated_at DESC, m.id DESC
                        )
                        SELECT m.*,
                               COUNT(i.id) AS itens,
                               COUNT(c.item_id) AS conferidos,
                               COALESCE(SUM(i.total_sistema), 0) AS total_sistema,
                               COALESCE(SUM(
                                   CASE
                                       WHEN i.grupo_contagem = 'PRODUTO' THEN
                                           COALESCE(c.contagem_caixas, 0) * COALESCE(NULLIF((i.payload->>'unidades_por_caixa')::numeric, 0), 1)
                                           + COALESCE(c.contagem_unidades, 0)
                                       WHEN i.grupo_contagem IN ('300', '600', '1L', '51') THEN
                                           COALESCE(c.contagem_real, 0) + COALESCE(c.contagem_vazia, 0)
                                       ELSE COALESCE(c.contagem_real, 0)
                                   END
                               ), 0) AS contagem_real
                        FROM latest_maps m
                        LEFT JOIN {}.conferencia_itens i ON i.conferencia_id = m.id
                        LEFT JOIN {}.conferencia_contagens c ON c.item_id = i.id
                        GROUP BY
                            m.id, m.caixa_date, m.filial, m.mapa, m.placa, m.motorista,
                            m.ajudante1, m.ajudante2, m.status, m.source_job_id,
                            m.source_payload, m.created_at, m.updated_at
                        ORDER BY m.filial, m.mapa
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        sql.SQL(" AND ").join(sql.SQL(part) for part in where),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                    ),
                    params,
                )
                rows = [self._serialize_mapa(row, reveal_totals=reveal_totals) for row in cur.fetchall()]
        return {"ok": True, "data": caixa_date.isoformat(), "filial": clean_filial, "mapas": rows}

    def list_garrafeira_consolidado(
        self,
        *,
        data: Any,
        filial: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        caixa_date = _parse_date(data)
        clean_filial = _normalize_filial(filial)
        allowed_filiais = _allowed_filiais(context)
        if clean_filial:
            _assert_filial_allowed(clean_filial, context)
        self._sync_open_mapas_from_03114902(
            caixa_date=caixa_date,
            filial=clean_filial,
            allowed_filiais=allowed_filiais,
        )
        where = ["m.caixa_date <= %s", "m.status IN ('aberta', 'aberta_03114902')"]
        params: list[Any] = [caixa_date]
        if clean_filial:
            where.append("m.filial = %s")
            params.append(clean_filial)
        elif allowed_filiais is not None:
            where.append("m.filial = ANY(%s)")
            params.append(sorted(allowed_filiais))

        groups = ("300", "600", "1L", "51")
        by_map: dict[int, dict[str, Any]] = {}
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        WITH latest_maps AS (
                            SELECT DISTINCT ON (m.filial, m.mapa) m.*
                            FROM {}.conferencia_mapas m
                            WHERE {}
                            ORDER BY m.filial, m.mapa, m.caixa_date DESC, m.updated_at DESC, m.id DESC
                        )
                        SELECT m.id, m.caixa_date, m.filial, m.mapa, m.placa, m.motorista,
                               i.grupo_contagem,
                               COALESCE(i.total_sistema, 0) AS total_sistema,
                               COALESCE(i.valor_unitario, 0) AS valor_unitario,
                               COALESCE(c.contagem_real, 0) AS contagem_real,
                               COALESCE(c.contagem_vazia, 0) AS contagem_vazia
                        FROM latest_maps m
                        JOIN {}.conferencia_itens i ON i.conferencia_id = m.id
                        LEFT JOIN {}.conferencia_contagens c ON c.item_id = i.id
                        WHERE i.grupo_contagem = ANY(%s)
                        ORDER BY m.filial, m.mapa, i.grupo_contagem
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        sql.SQL(" AND ").join(sql.SQL(part) for part in where),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                    ),
                    (*params, list(groups)),
                )
                for row in cur.fetchall():
                    mapa_id = int(row.get("id") or 0)
                    group = str(row.get("grupo_contagem") or "").upper()
                    if group not in groups:
                        continue
                    entry = by_map.setdefault(
                        mapa_id,
                        {
                            "id": mapa_id,
                            "data": _date_iso(row.get("caixa_date")),
                            "filial": str(row.get("filial") or ""),
                            "filial_label": self.filial_labels.get(str(row.get("filial") or ""), str(row.get("filial") or "")),
                            "placa": str(row.get("placa") or ""),
                            "mapa": str(row.get("mapa") or ""),
                            "motorista": str(row.get("motorista") or ""),
                            "groups": {
                                item: {"total": Decimal("0"), "cont": Decimal("0"), "dif": Decimal("0"), "valor": Decimal("0")}
                                for item in groups
                            },
                            "valor_total": Decimal("0"),
                        },
                    )
                    total = _decimal(row.get("total_sistema"))
                    cont = _decimal(row.get("contagem_real")) + _decimal(row.get("contagem_vazia"))
                    diff = cont - total
                    unit_price = _decimal(row.get("valor_unitario")) or _garrafeira_unit_price(group)
                    missing_value = max(total - cont, Decimal("0")) * unit_price
                    bucket = entry["groups"][group]
                    bucket["total"] += total
                    bucket["cont"] += cont
                    bucket["dif"] += diff
                    bucket["valor"] += missing_value
                    entry["valor_total"] += missing_value

        totals = {
            item: {"total": Decimal("0"), "cont": Decimal("0"), "dif": Decimal("0"), "valor": Decimal("0")}
            for item in groups
        }
        total_value = Decimal("0")
        serialized_rows: list[dict[str, Any]] = []
        for row in sorted(by_map.values(), key=lambda item: (item["filial"], _digits_sort_key(item["mapa"]))):
            serialized_groups: dict[str, dict[str, str]] = {}
            for group in groups:
                bucket = row["groups"][group]
                totals[group]["total"] += bucket["total"]
                totals[group]["cont"] += bucket["cont"]
                totals[group]["dif"] += bucket["dif"]
                totals[group]["valor"] += bucket["valor"]
                serialized_groups[group] = {
                    "total": _count_display_str(bucket["total"], group),
                    "cont": _count_display_str(bucket["cont"], group),
                    "dif": _count_display_str(bucket["dif"], group),
                    "valor": _decimal_str(bucket["valor"]),
                }
            total_value += row["valor_total"]
            serialized_rows.append(
                {
                    "id": row["id"],
                    "data": row["data"],
                    "filial": row["filial"],
                    "filial_label": row["filial_label"],
                    "placa": row["placa"],
                    "mapa": row["mapa"],
                    "motorista": row["motorista"],
                    "groups": serialized_groups,
                    "valor_total": _decimal_str(row["valor_total"]),
                }
            )
        serialized_totals = {
            group: {
                "total": _count_display_str(values["total"], group),
                "cont": _count_display_str(values["cont"], group),
                "dif": _count_display_str(values["dif"], group),
                "valor": _decimal_str(values["valor"]),
            }
            for group, values in totals.items()
        }
        return {
            "ok": True,
            "data": caixa_date.isoformat(),
            "filial": clean_filial,
            "groups": list(groups),
            "rows": serialized_rows,
            "totals": serialized_totals,
            "valor_total": _decimal_str(total_value),
        }

    def get_mapa(
        self,
        mapa_id: int,
        *,
        context: dict[str, Any] | None = None,
        reveal_totals: bool = False,
        item_search: str = "",
        grupo: str = "",
    ) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("SELECT * FROM {}.conferencia_mapas WHERE id = %s").format(sql.Identifier(self.schema)),
                    (int(mapa_id),),
                )
                mapa = dict(cur.fetchone() or {})
                if not mapa:
                    raise ValueError("Mapa de conferencia nao encontrado.")
                _assert_filial_allowed(str(mapa.get("filial") or ""), context)
                item_where = ["i.conferencia_id = %s"]
                params: list[Any] = [int(mapa_id)]
                clean_search = str(item_search or "").strip().lower()
                if clean_search:
                    item_where.append("(LOWER(i.cod_item) LIKE %s OR LOWER(i.descricao) LIKE %s OR LOWER(i.categoria) LIKE %s)")
                    token = f"%{clean_search}%"
                    params.extend([token, token, token])
                clean_grupo = str(grupo or "").strip()
                if clean_grupo:
                    item_where.append("i.grupo_contagem = %s")
                    params.append(clean_grupo)
                cur.execute(
                    sql.SQL(
                        """
                        SELECT i.*,
                               c.contagem_real,
                               c.contagem_vazia,
                               c.contagem_caixas,
                               c.contagem_unidades,
                               c.observacao AS contagem_observacao,
                               c.updated_by,
                               c.updated_at AS contagem_updated_at
                        FROM {}.conferencia_itens i
                        LEFT JOIN {}.conferencia_contagens c ON c.item_id = i.id
                        WHERE {}
                        ORDER BY
                            CASE i.grupo_contagem
                                WHEN '300' THEN 1 WHEN '600' THEN 2 WHEN '1L' THEN 3 WHEN '51' THEN 4
                                WHEN 'FREEZER' THEN 5 WHEN 'CADEIRA' THEN 6 WHEN 'MESA' THEN 7
                                WHEN 'BARRIL' THEN 8 WHEN 'BARRACA' THEN 9
                                WHEN 'OUTRAS GARRAFEIRAS' THEN 10 WHEN 'OUTROS MATERIAIS' THEN 11 ELSE 12
                            END,
                            i.tipo_item, i.descricao, i.cod_item
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.SQL(" AND ").join(sql.SQL(part) for part in item_where),
                    ),
                    params,
                )
                items = [self._serialize_item(row, reveal_totals=reveal_totals) for row in cur.fetchall()]
                cur.execute(
                    sql.SQL(
                        """
                        SELECT grupo_contagem,
                               COUNT(*) AS itens,
                               COUNT(c.item_id) AS conferidos,
                               COALESCE(SUM(i.total_sistema), 0) AS total_sistema,
                               COALESCE(SUM(
                                   CASE
                                       WHEN i.grupo_contagem = 'PRODUTO' THEN
                                           COALESCE(c.contagem_caixas, 0) * COALESCE(NULLIF((i.payload->>'unidades_por_caixa')::numeric, 0), 1)
                                           + COALESCE(c.contagem_unidades, 0)
                                       WHEN i.grupo_contagem IN ('300', '600', '1L', '51') THEN
                                           COALESCE(c.contagem_real, 0) + COALESCE(c.contagem_vazia, 0)
                                       ELSE COALESCE(c.contagem_real, 0)
                                   END
                               ), 0) AS contagem_real
                        FROM {}.conferencia_itens i
                        LEFT JOIN {}.conferencia_contagens c ON c.item_id = i.id
                        WHERE i.conferencia_id = %s
                        GROUP BY grupo_contagem
                        ORDER BY grupo_contagem
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                    ),
                    (int(mapa_id),),
                )
                groups = [dict(row) for row in cur.fetchall()]
                mapa["itens"] = sum(int(row.get("itens") or 0) for row in groups)
                mapa["conferidos"] = sum(int(row.get("conferidos") or 0) for row in groups)
                mapa["total_sistema"] = sum((_decimal(row.get("total_sistema")) for row in groups), Decimal("0"))
                mapa["contagem_real"] = sum((_decimal(row.get("contagem_real")) for row in groups), Decimal("0"))
        return {
            "ok": True,
            "mapa": self._serialize_mapa(mapa, reveal_totals=reveal_totals),
            "items": items,
            "groups": groups,
            "reveal_totals": bool(reveal_totals),
        }

    def save_counts(
        self,
        mapa_id: int,
        *,
        counts: Iterable[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        username = str((context or {}).get("username") or "painel").strip() or "painel"
        clean_counts: list[tuple[int, Decimal | None, Decimal | None, Decimal | None, Decimal | None, str, str, str, str, str]] = []
        for item in counts:
            item_id = int(item.get("item_id") or item.get("id") or 0)
            code = _manual_code(item.get("cod_item") or "")
            description = str(item.get("descricao") or "").strip()
            group = str(item.get("grupo_contagem") or "").strip().upper()
            unidade = str(item.get("unidade") or "").strip()
            if item_id <= 0 and not description and not code:
                continue
            count_value = _optional_decimal(item.get("contagem_real"))
            empty_value = _optional_decimal(item.get("contagem_vazia"))
            box_value = _optional_decimal(item.get("contagem_caixas"))
            unit_value = _optional_decimal(item.get("contagem_unidades"))
            if group == "PRODUTO":
                if box_value is not None:
                    box_value = Decimal(int(box_value))
                if unit_value is not None:
                    unit_value = Decimal(int(unit_value))
                if count_value is None and (box_value is not None or unit_value is not None):
                    count_value = (box_value or Decimal("0")) + (unit_value or Decimal("0"))
            elif _requires_integer_count(group):
                if count_value is not None:
                    count_value = Decimal(int(count_value))
                if empty_value is not None:
                    empty_value = Decimal(int(empty_value))
            obs = str(item.get("observacao") or "").strip()[:500]
            clean_counts.append((item_id, count_value, empty_value, box_value, unit_value, obs, code, description, group, unidade))
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("SELECT id, filial FROM {}.conferencia_mapas WHERE id = %s").format(sql.Identifier(self.schema)),
                    (int(mapa_id),),
                )
                mapa = dict(cur.fetchone() or {})
                if not mapa:
                    raise ValueError("Mapa de conferencia nao encontrado.")
                _assert_filial_allowed(str(mapa.get("filial") or ""), context)
                saved = 0
                for item_id, count_value, empty_value, box_value, unit_value, obs, code, description, group, unidade in clean_counts:
                    if item_id <= 0:
                        item_id = self._upsert_manual_item(
                            cur,
                            conferencia_id=int(mapa_id),
                            cod_item=code,
                            descricao=description,
                            grupo_contagem=group,
                            unidade=unidade,
                        )
                    else:
                        cur.execute(
                            sql.SQL("SELECT 1 FROM {}.conferencia_itens WHERE id = %s AND conferencia_id = %s").format(
                                sql.Identifier(self.schema)
                            ),
                            (item_id, int(mapa_id)),
                        )
                        if cur.fetchone() is None:
                            continue
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {}.conferencia_contagens (
                                item_id, contagem_real, contagem_vazia, contagem_caixas, contagem_unidades,
                                observacao, updated_by, updated_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (item_id) DO UPDATE SET
                                contagem_real = EXCLUDED.contagem_real,
                                contagem_vazia = EXCLUDED.contagem_vazia,
                                contagem_caixas = EXCLUDED.contagem_caixas,
                                contagem_unidades = EXCLUDED.contagem_unidades,
                                observacao = EXCLUDED.observacao,
                                updated_by = EXCLUDED.updated_by,
                                updated_at = NOW()
                            """
                        ).format(sql.Identifier(self.schema)),
                        (item_id, count_value, empty_value, box_value, unit_value, obs, username),
                    )
                    saved += 1
            conn.commit()
        return {"ok": True, "mapa_id": int(mapa_id), "saved": saved}

    def search_products(
        self,
        *,
        search: str,
        limit: int = 20,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        query = str(search or "").strip()
        if len(query) < 2:
            return {"ok": True, "products": []}
        clean_limit = min(max(int(limit or 20), 1), 50)
        with self._connect() as conn:
            if not _relation_exists(conn, self.schema, "dprodutos_latest"):
                return {"ok": True, "products": []}
            token = f"%{query.lower()}%"
            digits = re.sub(r"\D+", "", query)
            params: list[Any] = [token, token, token]
            where = """
                LOWER(COALESCE(descricao, '')) LIKE %s
                OR LOWER(COALESCE(descricao_unitaria, '')) LIKE %s
                OR LOWER(COALESCE(codigo::text, '')) LIKE %s
            """
            if digits:
                where += " OR regexp_replace(COALESCE(codigo::text, ''), '\\D', '', 'g') LIKE %s"
                params.append(f"%{digits}%")
            params.append(clean_limit)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT codigo, descricao, descricao_unitaria, embalagem, grupo, subtipo
                        FROM {}.dprodutos_latest
                        WHERE {}
                        ORDER BY
                            CASE
                                WHEN regexp_replace(COALESCE(codigo::text, ''), '\\D', '', 'g') = %s THEN 0
                                WHEN LOWER(COALESCE(descricao_unitaria, '')) LIKE %s THEN 1
                                ELSE 2
                            END,
                            descricao_unitaria, descricao
                        LIMIT %s
                        """
                    ).format(sql.Identifier(self.schema), sql.SQL(where)),
                    (*params[:-1], digits, token, params[-1]),
                )
                rows = [dict(row) for row in cur.fetchall()]
        return {
            "ok": True,
            "products": [
                {
                    "codigo": _manual_code(row.get("codigo")),
                    "descricao": str(row.get("descricao_unitaria") or row.get("descricao") or "").strip(),
                    "descricao_completa": str(row.get("descricao") or "").strip(),
                    "embalagem": str(row.get("embalagem") or "").strip(),
                    "grupo": str(row.get("grupo") or "").strip(),
                    "subtipo": str(row.get("subtipo") or "").strip(),
                }
                for row in rows
            ],
        }

    def _upsert_manual_item(
        self,
        cur: Any,
        *,
        conferencia_id: int,
        cod_item: str,
        descricao: str,
        grupo_contagem: str,
        unidade: str = "",
    ) -> int:
        clean_code = _manual_code(cod_item) or f"MANUAL-{_manual_item_slug(descricao)}"
        clean_description = str(descricao or clean_code).strip()[:240]
        clean_group = _normalize_manual_group(grupo_contagem or _classify_group(clean_description))
        clean_unidade = str(unidade or "").strip()[:40]
        tipo_item = "produto" if clean_group == "PRODUTO" else "manual"
        payload = {"source": "manual"}
        units_per_box = _units_per_box_from_text(clean_unidade)
        if units_per_box:
            payload["unidades_por_caixa"] = units_per_box
        valor_unitario = _garrafeira_unit_price(clean_group)
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {}.conferencia_itens (
                    conferencia_id, cod_item, descricao, tipo_item, categoria, grupo_contagem,
                    unidade, total_sistema, valor_unitario, payload, updated_at
                )
                VALUES (%s, %s, %s, %s, 'Lancamento manual', %s, %s, 0, %s, %s, NOW())
                ON CONFLICT (conferencia_id, cod_item) DO UPDATE SET
                    descricao = EXCLUDED.descricao,
                    tipo_item = EXCLUDED.tipo_item,
                    categoria = EXCLUDED.categoria,
                    grupo_contagem = EXCLUDED.grupo_contagem,
                    unidade = EXCLUDED.unidade,
                    payload = EXCLUDED.payload,
                    updated_at = NOW()
                RETURNING id
                """
            ).format(sql.Identifier(self.schema)),
            (
                conferencia_id,
                clean_code,
                clean_description,
                tipo_item,
                clean_group,
                clean_unidade,
                valor_unitario,
                Jsonb(payload),
            ),
        )
        return int(cur.fetchone()["id"])

    @contextmanager
    def _connect(self):
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        if self._pool is None:
            self._pool = get_connection_pool(
                self.database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
                min_size=1,
                max_size=4,
            )
        with self._pool.connection() as conn:
            yield conn

    def _load_product_lookup(self, conn: psycopg.Connection[Any], codes: set[str]) -> dict[str, dict[str, Any]]:
        return _load_lookup(
            conn,
            self.schema,
            "dprodutos_latest",
            codes,
            ("codigo", "descricao", "descricao_unitaria", "embalagem", "grupo", "subtipo"),
        )

    def _load_material_lookup(self, conn: psycopg.Connection[Any], codes: set[str]) -> dict[str, dict[str, Any]]:
        return _load_lookup(
            conn,
            self.schema,
            "dmateriais_latest",
            codes,
            ("codigo", "descricao", "tipo_material", "grupo", "familia", "capacidade", "un_venda"),
        )

    def _load_garrafeira_lookup(self, conn: psycopg.Connection[Any], codes: set[str]) -> dict[str, dict[str, Any]]:
        return _load_lookup(
            conn,
            self.schema,
            "dgarrafeiras_latest",
            codes,
            ("codigo", "descricao", "tipo_material", "grupo", "familia", "capacidade", "un_venda", "retornavel"),
        )

    def _serialize_mapa(self, row: dict[str, Any], *, reveal_totals: bool) -> dict[str, Any]:
        payload = {
            "id": int(row.get("id") or 0),
            "data": _date_iso(row.get("caixa_date")),
            "filial": str(row.get("filial") or ""),
            "filial_label": self.filial_labels.get(str(row.get("filial") or ""), str(row.get("filial") or "")),
            "mapa": str(row.get("mapa") or ""),
            "placa": str(row.get("placa") or ""),
            "motorista": _motorista_display(row.get("motorista")),
            "ajudante1": str(row.get("ajudante1") or ""),
            "ajudante2": str(row.get("ajudante2") or ""),
            "status": str(row.get("status") or "aberta"),
            "source_status": _source_status_label(row.get("status")),
            "itens": int(row.get("itens") or 0),
            "conferidos": int(row.get("conferidos") or 0),
            "updated_at": _datetime_iso(row.get("updated_at")),
        }
        if reveal_totals:
            total = _decimal(row.get("total_sistema"))
            count = _decimal(row.get("contagem_real"))
            payload.update(
                {
                    "total_sistema": _decimal_str(total),
                    "contagem_real": _decimal_str(count),
                    "diferenca": _decimal_str(count - total),
                }
            )
        return payload

    def _sync_open_mapas_from_03114902(
        self,
        *,
        caixa_date: date,
        filial: str = "",
        allowed_filiais: set[str] | None = None,
    ) -> int:
        with self._connect() as conn:
            if not _relation_exists(conn, self.schema, "relatorio_031120_rows") or not _relation_exists(conn, self.schema, "dataset_state"):
                return 0
            where = ["r.dataset_name = 'relatorio_03114902_geo'", "s.active_batch_id = r.batch_id"]
            params: list[Any] = []
            date_tokens = {caixa_date.isoformat(), caixa_date.strftime("%d/%m/%Y")}
            where.append("(r.payload->>'Data Entrega' = ANY(%s) OR r.payload->>'Data' = ANY(%s))")
            params.extend([sorted(date_tokens), sorted(date_tokens)])
            if filial:
                where.append("COALESCE(NULLIF(regexp_replace(r.payload->>'UNB', '\\D', '', 'g'), ''), r.filial) = %s")
                params.append(filial)
            elif allowed_filiais is not None:
                where.append("COALESCE(NULLIF(regexp_replace(r.payload->>'UNB', '\\D', '', 'g'), ''), r.filial) = ANY(%s)")
                params.append(sorted(allowed_filiais))
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        WITH active_rows AS (
                            SELECT
                                COALESCE(NULLIF(regexp_replace(r.payload->>'UNB', '\\D', '', 'g'), ''), r.filial) AS filial,
                                regexp_replace(COALESCE(r.payload->>'Nro do Mapa', r.payload->>'Mapa', ''), '^0+', '') AS mapa,
                                MAX(NULLIF(r.payload->>'Placa', '')) AS placa,
                                MAX(NULLIF(r.payload->>'Motorista', '')) AS motorista,
                                BOOL_OR((r.payload->>'MPD') ILIKE '%%saida%%' OR (r.payload->>'MPD') ILIKE '%%saída%%') AS tem_saida,
                                BOOL_OR((r.payload->>'MPD') ILIKE '%%entrada%%') AS tem_entrada,
                                jsonb_agg(r.payload ORDER BY r.row_number) AS payloads
                            FROM {}.relatorio_031120_rows r
                            JOIN {}.dataset_state s ON s.dataset_name = r.dataset_name
                            WHERE {}
                            GROUP BY 1, 2
                        )
                        INSERT INTO {}.conferencia_mapas AS current_map (
                            caixa_date, filial, mapa, placa, motorista, status,
                            source_job_id, source_payload, updated_at
                        )
                        SELECT
                            %s, filial, mapa, COALESCE(placa, ''), COALESCE(motorista, ''),
                            'aberta_03114902',
                            '03114902',
                            jsonb_build_object('source', '03114902', 'payloads', payloads),
                            NOW()
                        FROM active_rows
                        WHERE tem_saida
                          AND NOT tem_entrada
                          AND filial <> ''
                          AND mapa <> ''
                        ON CONFLICT (caixa_date, filial, mapa) DO UPDATE SET
                            placa = CASE WHEN current_map.placa = '' THEN EXCLUDED.placa ELSE current_map.placa END,
                            motorista = CASE WHEN current_map.motorista = '' THEN EXCLUDED.motorista ELSE current_map.motorista END,
                            status = CASE
                                WHEN current_map.status = 'aberta' THEN current_map.status
                                ELSE EXCLUDED.status
                            END,
                            source_payload = CASE
                                WHEN current_map.source_job_id = '03114902' THEN EXCLUDED.source_payload
                                ELSE current_map.source_payload
                            END,
                            updated_at = NOW()
                        RETURNING id
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.SQL(" AND ").join(sql.SQL(part) for part in where),
                        sql.Identifier(self.schema),
                    ),
                    (*params, caixa_date),
                )
                inserted = len(cur.fetchall())
            conn.commit()
            return inserted

    def _serialize_item(self, row: dict[str, Any], *, reveal_totals: bool) -> dict[str, Any]:
        group = str(row.get("grupo_contagem") or "")
        effective_count = _effective_count_from_row(row)
        payload = {
            "id": int(row.get("id") or 0),
            "cod_item": _display_item_code(row.get("cod_item")),
            "descricao": str(row.get("descricao") or ""),
            "tipo_item": str(row.get("tipo_item") or ""),
            "categoria": str(row.get("categoria") or ""),
            "grupo_contagem": group,
            "unidade": str(row.get("unidade") or ""),
            "contagem_real": _count_display_str(row.get("contagem_real"), group),
            "contagem_vazia": _count_display_str(row.get("contagem_vazia"), group),
            "contagem_caixas": _count_display_str(row.get("contagem_caixas"), group),
            "contagem_unidades": _count_display_str(row.get("contagem_unidades"), group),
            "contagem_efetiva": _count_display_str(effective_count, group),
            "unidades_por_caixa": _units_per_box_from_payload(row.get("payload")),
            "observacao": str(row.get("contagem_observacao") or ""),
            "updated_by": str(row.get("updated_by") or ""),
            "updated_at": _datetime_iso(row.get("contagem_updated_at")),
        }
        if reveal_totals:
            total = _decimal(row.get("total_sistema"))
            payload.update(
                {
                    "total_sistema": _count_display_str(total, group),
                    "valor_unitario": _decimal_str(_decimal(row.get("valor_unitario"))),
                    "diferenca": _count_display_str(effective_count - total, group),
                }
            )
        return payload


def _extract_030302_items(source: Any) -> list[ConferenciaItemDraft]:
    roots = _candidate_030302_roots(source)
    merged: dict[str, ConferenciaItemDraft] = {}
    for root in roots:
        for raw, parent_key in _iter_item_dicts(root):
            draft = _draft_from_raw_item(raw, parent_key)
            if not draft:
                continue
            existing = merged.get(draft.cod_item)
            if existing:
                merged[draft.cod_item] = ConferenciaItemDraft(
                    cod_item=existing.cod_item,
                    descricao=existing.descricao or draft.descricao,
                    tipo_item=existing.tipo_item or draft.tipo_item,
                    categoria=existing.categoria or draft.categoria,
                    grupo_contagem=existing.grupo_contagem or draft.grupo_contagem,
                    unidade=existing.unidade or draft.unidade,
                    total_sistema=existing.total_sistema + draft.total_sistema,
                    valor_unitario=existing.valor_unitario or draft.valor_unitario,
                    payload={"partes": [existing.payload, draft.payload]},
                )
            else:
                merged[draft.cod_item] = draft
    return list(merged.values())


def _candidate_030302_roots(source: Any) -> list[Any]:
    decisive_paths = (
        ("metadata", "resultado_fisico", "metadata", "captura_diferencas", "itens"),
        ("resultado_fisico", "metadata", "captura_diferencas", "itens"),
        ("result", "metadata", "resultado_fisico", "metadata", "captura_diferencas", "itens"),
        ("metadata", "resultado_fisico", "metadata", "captura_material", "itens"),
        ("resultado_fisico", "metadata", "captura_material", "itens"),
    )
    for path in decisive_paths:
        value = _nested_get(source, path)
        if value:
            return [value]

    paths = (
        ("metadata", "resultado_fisico", "metadata", "dados_030302"),
        ("metadata", "resultado_fisico", "dados_030302"),
        ("resultado_fisico", "metadata", "dados_030302"),
        ("resultado_fisico", "dados_030302"),
        ("metadata", "dados_030302"),
        ("dados_030302",),
        ("result", "metadata", "resultado_fisico", "metadata", "dados_030302"),
        ("result", "metadata", "dados_030302"),
    )
    for path in paths:
        value = _nested_get(source, path)
        if value:
            return [value]

    fisico = _nested_get(source, ("metadata", "resultado_fisico")) or _nested_get(source, ("resultado_fisico",))
    return [fisico] if fisico else []


def _iter_item_dicts(value: Any, parent_key: str = "") -> Iterable[tuple[dict[str, Any], str]]:
    if isinstance(value, dict):
        if _looks_like_item(value):
            yield value, parent_key
        for key, child in value.items():
            key_text = str(key or "")
            if isinstance(child, list) and _norm_key(key_text) in {"materiais", "material", "produtos", "produto", "itens", "items", "diferencas", "linhasdisponiveis"}:
                for item in child:
                    yield from _iter_item_dicts(item, key_text)
            elif isinstance(child, dict):
                yield from _iter_item_dicts(child, key_text)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_item_dicts(item, parent_key)


def _looks_like_item(value: dict[str, Any]) -> bool:
    keys = {_norm_key(key) for key in value}
    has_code = bool(keys.intersection({"codigo", "coditem", "cod_item", "cod", "item", "produto", "material", "codigoproduto", "codigomaterial"}))
    has_qty = bool(keys.intersection({
        "total",
        "quantidade",
        "qtd",
        "qtde",
        "saldo",
        "cobrado",
        "sistema",
        "diferenca",
        "faltaun",
        "faltaav",
        "vazun",
        "vazav",
        "troun",
        "troav",
        "devun",
        "devav",
    }))
    return has_code and has_qty


def _draft_from_raw_item(raw: dict[str, Any], parent_key: str) -> ConferenciaItemDraft | None:
    code = _first_text(raw, "codigo", "cod_item", "codItem", "cod", "item", "produto", "material", "codigoProduto", "codigoMaterial")
    code = _digits_or_text(code)
    if not code:
        return None
    raw_text = _first_text(raw, "texto", "label", "value")
    parsed = _parse_030302_item_text(raw_text, code)
    descricao = _first_text(raw, "descricao", "descrição", "nome", "descricao_item", "produto_descricao", "material_descricao", "desc")
    if not descricao:
        descricao = parsed.get("descricao") or raw_text
    tipo_item = "material" if "material" in str(parent_key or "").lower() else "produto" if "produto" in str(parent_key or "").lower() else _first_text(raw, "tipo_item", "tipo")
    if not tipo_item:
        tipo_item = "item"
    total = _quantity_from_030302_raw(raw)
    unidade = _first_text(raw, "unidade", "un", "embalagem") or parsed.get("unidade")
    valor_unit = _first_decimal(raw, "valor_unitario", "valorUnitario", "preco", "valor")
    categoria = _first_text(raw, "categoria", "tipo_material", "grupo", "familia", "tipo")
    grupo = _classify_group(f"{categoria} {descricao} {unidade}")
    payload = dict(raw)
    if parsed:
        payload["texto_parseado_030302"] = parsed
    if unidade:
        payload["sistema_unidade"] = str(unidade).strip().lower()
    return ConferenciaItemDraft(
        cod_item=code,
        descricao=descricao or code,
        tipo_item=tipo_item,
        categoria=categoria,
        grupo_contagem=grupo,
        unidade=unidade,
        total_sistema=total,
        valor_unitario=valor_unit,
        payload=payload,
    )


def _enrich_item(
    item: ConferenciaItemDraft,
    product: dict[str, Any] | None,
    material: dict[str, Any] | None,
    garrafeira: dict[str, Any] | None = None,
) -> ConferenciaItemDraft:
    ref = garrafeira or material or product or {}
    tipo_item = "material" if garrafeira or material else "produto" if product else item.tipo_item
    descricao = item.descricao
    if garrafeira:
        descricao = str(ref.get("descricao") or item.descricao or item.cod_item)
    elif product:
        descricao = str(ref.get("descricao_unitaria") or ref.get("descricao") or item.descricao or item.cod_item)
    elif not descricao or descricao == item.cod_item:
        descricao = str(ref.get("descricao") or ref.get("descricao_unitaria") or item.cod_item)
    categoria = str(ref.get("tipo_material") or ref.get("grupo") or ref.get("subtipo") or ref.get("familia") or "") if garrafeira else item.categoria or str(ref.get("tipo_material") or ref.get("grupo") or ref.get("subtipo") or ref.get("familia") or "")
    unidade = str(ref.get("un_venda") or ref.get("embalagem") or "") if garrafeira else item.unidade or str(ref.get("un_venda") or ref.get("embalagem") or "")
    grupo = _classify_garrafeira_tipo_material(categoria) if garrafeira else _classify_group(f"{categoria} {descricao} {unidade}")
    item_payload = {**item.payload, "cadastro_ref": _json_safe(ref), "garrafeira_ref": bool(garrafeira)}
    units_per_box = _units_per_box_from_text(unidade)
    if units_per_box:
        item_payload["unidades_por_caixa"] = units_per_box
    valor_unitario = item.valor_unitario
    if garrafeira:
        valor_unitario = item.valor_unitario or _garrafeira_unit_price(grupo)
    return ConferenciaItemDraft(
        cod_item=item.cod_item,
        descricao=descricao,
        tipo_item=tipo_item,
        categoria=categoria,
        grupo_contagem=grupo,
        unidade=unidade,
        total_sistema=item.total_sistema,
        valor_unitario=valor_unitario,
        payload=item_payload,
    )


def _aggregate_conferencia_items(items: list[ConferenciaItemDraft]) -> list[ConferenciaItemDraft]:
    result: dict[str, ConferenciaItemDraft] = {}
    for item in items:
        is_garrafeira = _is_expected_garrafeira_item(item)
        is_product = _is_conferencia_product_item(item)
        if not is_garrafeira and not is_product:
            continue
        group = _classify_garrafeira_tipo_material(item.categoria) if is_garrafeira else "PRODUTO"
        key = item.cod_item
        existing = result.get(key)
        if existing:
            merged_payload = {"partes": [existing.payload, item.payload]}
            units_per_box = _units_per_box_from_payload(existing.payload) or _units_per_box_from_payload(item.payload)
            if units_per_box:
                merged_payload["unidades_por_caixa"] = units_per_box
            result[key] = ConferenciaItemDraft(
                cod_item=existing.cod_item,
                descricao=existing.descricao or item.descricao,
                tipo_item=existing.tipo_item or item.tipo_item,
                categoria=_merge_distinct_text(existing.categoria, item.categoria),
                grupo_contagem=group,
                unidade=existing.unidade or item.unidade,
                total_sistema=existing.total_sistema + item.total_sistema,
                valor_unitario=existing.valor_unitario or item.valor_unitario,
                payload=merged_payload,
            )
        else:
            result[key] = ConferenciaItemDraft(
                cod_item=item.cod_item,
                descricao=item.descricao,
                tipo_item=item.tipo_item,
                categoria=item.categoria,
                grupo_contagem=group,
                unidade=item.unidade,
                total_sistema=item.total_sistema,
                valor_unitario=item.valor_unitario,
                payload=item.payload,
            )
    return sorted(result.values(), key=lambda row: (_group_sort_key(f"GRUPO-{row.grupo_contagem}"), row.descricao, row.cod_item))


def _is_expected_garrafeira_item(item: ConferenciaItemDraft) -> bool:
    if not bool(item.payload.get("garrafeira_ref")):
        return False
    return _classify_garrafeira_tipo_material(item.categoria) in {"300", "600", "1L"}


def _is_conferencia_product_item(item: ConferenciaItemDraft) -> bool:
    if bool(item.payload.get("garrafeira_ref")):
        return False
    tipo = _strip_accents(item.tipo_item).upper()
    if tipo == "MATERIAL":
        return False
    text = _strip_accents(f"{item.descricao} {item.categoria}").upper()
    if any(token in text for token in ("GARRAFEIRA", "GFA ", "GFA_", "VASILHAME", "CHAPATEX", "PALLET")):
        return False
    return item.total_sistema != 0


def _classify_garrafeira_tipo_material(tipo_material: str) -> str:
    value = _strip_accents(tipo_material).upper()
    if value == "GARRAFEIRA CERVEJA 1/2":
        return "300"
    if value == "GARRAFEIRA CERVEJA 1/1":
        return "600"
    if value == "GARRAFEIRA CERVEJA LITRAO":
        return "1L"
    return ""


def _garrafeira_unit_price(group: str) -> Decimal:
    prices = {
        "300": Decimal("40.80"),
        "600": Decimal("66.32"),
        "1L": Decimal("54.32"),
    }
    return prices.get(str(group or "").strip().upper(), Decimal("0"))


def _classify_gfe_group(text: str) -> str:
    value = _strip_accents(text).upper()
    if re.search(r"\b51\b", value) or "5/1" in value:
        return "51"
    if "965" in value or "LITRAO" in value:
        return "1L"
    if "1/2" in value:
        return "300"
    if "1/1" in value or "635" in value or "600ML" in value or re.search(r"\b600\b", value):
        return "600"
    if "300ML" in value or "330ML" in value or "LITRINHO" in value or re.search(r"\b300\b", value):
        return "300"
    if "1000" in value or "1L" in value or "1 L" in value:
        return "1L"
    return _classify_group(value)


def _classify_group(text: str) -> str:
    value = _strip_accents(text).upper()
    if "FREEZER" in value or "COOLER" in value or "GELADEIRA" in value:
        return "FREEZER"
    if "CADEIRA" in value:
        return "CADEIRA"
    if "MESA" in value:
        return "MESA"
    if "BARRIL" in value:
        return "BARRIL"
    if "BARRACA" in value or "TENDA" in value:
        return "BARRACA"
    if re.search(r"\b51\b", value) or "5/1" in value:
        return "51"
    if "1000" in value or "1L" in value or "1 L" in value or "1/1" in value:
        return "1L"
    if re.search(r"\b600\b", value) or "600ML" in value or "630ML" in value or "635ML" in value:
        return "600"
    if re.search(r"\b300\b", value) or "300ML" in value or "330ML" in value or "350" in value or "355" in value or "LATA" in value or "LITRINHO" in value:
        return "300"
    if "VASILHAME" in value or "GARRAFEIRA" in value:
        return "OUTRAS GARRAFEIRAS"
    return "OUTROS MATERIAIS"


def _load_lookup(
    conn: psycopg.Connection[Any],
    schema: str,
    table: str,
    codes: set[str],
    columns: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    clean_codes = sorted({str(code or "").strip() for code in codes if str(code or "").strip()})
    if not clean_codes or not _relation_exists(conn, schema, table):
        return {}
    existing_columns = [col for col in columns if _relation_column_exists(conn, schema, table, col)]
    if "codigo" not in existing_columns:
        return {}
    select_list = sql.SQL(", ").join(sql.Identifier(col) for col in existing_columns)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql.SQL("SELECT {} FROM {}.{} WHERE codigo = ANY(%s)").format(
                select_list, sql.Identifier(schema), sql.Identifier(table)
            ),
            (clean_codes,),
        )
        return {str(row.get("codigo") or "").strip(): dict(row) for row in cur.fetchall()}


def _relation_exists(conn: psycopg.Connection[Any], schema: str, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            UNION ALL
            SELECT 1
            FROM information_schema.views
            WHERE table_schema = %s AND table_name = %s
            LIMIT 1
            """,
            (schema, name, schema, name),
        )
        return cur.fetchone() is not None


def _relation_column_exists(conn: psycopg.Connection[Any], schema: str, table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            LIMIT 1
            """,
            (schema, table, column),
        )
        return cur.fetchone() is not None


def _extract_030303_fields(source: Any) -> dict[str, str]:
    dados = _extract_dados_030303(source)
    motorista = _clean_select_text(_nested_get(dados, ("motorista", "nome")) or _field_030303_value(dados, "motorista"))
    if _is_generic_motorista(motorista):
        motorista = _clean_select_text(_field_030303_value(dados, "ajudante1")) or ""
    if not motorista:
        motorista = _clean_select_text(_field_030303_value(dados, "csMotorista"))
    if not motorista:
        motorista = _clean_select_text(_field_030303_value(dados, "cdMotorista"))
    return {
        "motorista": motorista,
        "placa": _clean_select_text(_field_030303_value(dados, "placa"), keep_code=True),
        "ajudante1": _clean_select_text(_field_030303_value(dados, "ajudante1")),
        "ajudante2": _clean_select_text(_field_030303_value(dados, "ajudante2")),
    }


def _extract_dados_030303(source: Any) -> dict[str, Any]:
    paths = (
        ("metadata", "resultado_030303", "dados_030303"),
        ("metadata", "resultado_030303", "metadata", "dados_030303"),
        ("resultado_030303", "dados_030303"),
        ("resultado_030303", "metadata", "dados_030303"),
        ("dados_030303",),
        ("result", "metadata", "resultado_030303", "dados_030303"),
    )
    for path in paths:
        value = _nested_get(source, path)
        if isinstance(value, dict):
            return value
    metadata = source.get("metadata") if isinstance(source, dict) else None
    if isinstance(metadata, dict) and metadata is not source:
        return _extract_dados_030303(metadata)
    return {}


def _field_030303_value(dados: dict[str, Any], field_name: str) -> Any:
    if not isinstance(dados, dict):
        return ""
    target = _norm_key(field_name)
    campos = dados.get("campos")
    if isinstance(campos, list):
        for campo in campos:
            if not isinstance(campo, dict):
                continue
            if (
                _norm_key(campo.get("name")) == target
                or _norm_key(campo.get("id")) == target
                or _norm_key(campo.get("label")) == target
            ):
                return campo.get("value")
    field = dados.get(field_name)
    if isinstance(field, dict):
        for key in ("texto", "nome", "valor", "value", "label"):
            value = field.get(key)
            if value not in (None, ""):
                return value
    return field


def _clean_select_text(value: Any, *, keep_code: bool = False) -> str:
    if isinstance(value, dict):
        text = str(value.get("texto") or value.get("nome") or value.get("label") or value.get("value") or "").strip()
        raw_code = str(value.get("valor") or "").strip()
        if raw_code in {"", "00000"} and _is_blank_identity_text(text):
            return ""
    else:
        text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if _is_blank_identity_text(text):
        return ""
    if keep_code:
        return text
    text = re.sub(r"^\s*\d+\s*[-|]\s*", "", text).strip()
    text = text.replace("(*)", "").strip()
    if _is_blank_identity_text(text):
        return ""
    return text


def _is_generic_motorista(value: str) -> bool:
    return _is_blank_identity_text(value)


def _is_blank_identity_text(value: Any) -> bool:
    clean = _strip_accents(value).upper().strip()
    if not clean:
        return True
    return clean in {
        "--SELECIONAR--",
        "SELECIONAR",
        "00000",
        "SEM PLACA",
        "00001 - (*) PAU BRASIL",
        "(*) PAU BRASIL",
        "PAU BRASIL",
        "DISTRIBUIDORA PAU BRASIL",
    }


def _merge_identity_fallback(primary: dict[str, str], fallback: dict[str, str]) -> dict[str, str]:
    merged = dict(primary or {})
    for key in ("motorista", "placa", "ajudante1", "ajudante2"):
        current = _clean_select_text(merged.get(key), keep_code=(key == "placa"))
        candidate = _clean_select_text((fallback or {}).get(key), keep_code=(key == "placa"))
        merged[key] = current or candidate
    return merged


def _sql_blankish_alias(alias: str, column: str) -> sql.SQL:
    field = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(column))
    numeric_fallback = sql.SQL("")
    if column != "placa":
        numeric_fallback = sql.SQL("OR BTRIM({}) ~ '^[0-9]+$'").format(field)
    return sql.SQL(
        """(
            COALESCE(NULLIF(BTRIM({}), ''), '') = ''
            OR UPPER(BTRIM({})) = ANY(ARRAY[
                '--SELECIONAR--',
                'SELECIONAR',
                '00000',
                'SEM PLACA',
                '00001 - (*) PAU BRASIL',
                '(*) PAU BRASIL',
                'PAU BRASIL',
                'DISTRIBUIDORA PAU BRASIL'
            ])
            {}
        )"""
    ).format(field, field, numeric_fallback)


def _nested_get(source: Any, path: tuple[str, ...]) -> Any:
    current = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_text(raw: dict[str, Any], *keys: str) -> str:
    indexed = {_norm_key(key): value for key, value in raw.items()}
    for key in keys:
        value = indexed.get(_norm_key(key))
        if value not in (None, ""):
            if isinstance(value, dict):
                value = value.get("texto") or value.get("nome") or value.get("valor") or value.get("value") or value.get("label")
            return str(value or "").strip()
    return ""


def _first_decimal(raw: dict[str, Any], *keys: str) -> Decimal:
    indexed = {_norm_key(key): value for key, value in raw.items()}
    for key in keys:
        if _norm_key(key) in indexed:
            value = indexed[_norm_key(key)]
            if value not in (None, ""):
                return _decimal(value)
    return Decimal("0")


def _quantity_from_030302_raw(raw: dict[str, Any]) -> Decimal:
    direct = _first_decimal(raw, "total", "quantidade", "qtd", "qtde", "saldo", "cobrado", "sistema", "diferenca")
    if direct:
        return direct
    for left_key, right_key in (
        ("faltaUn", "faltaAv"),
        ("vazUn", "vazAv"),
        ("troUn", "troAv"),
        ("devUn", "devAv"),
        ("previsaoUn", "previsaoAv"),
    ):
        left = _first_decimal(raw, left_key)
        right = _first_decimal(raw, right_key)
        if left:
            return left
        if right:
            return right
    return Decimal("0")


def _parse_030302_item_text(text: Any, code: str) -> dict[str, str]:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return {}
    clean_code = re.escape(str(code or "").strip())
    pattern = rf"^\s*0*{clean_code}\s+([A-Za-z]{{1,4}})\s+(.+?)\s+(?:-?\d+\s*/\s*-?\d+\s*)+$"
    match = re.match(pattern, raw)
    if not match:
        match = re.match(r"^\s*\S+\s+([A-Za-z]{1,4})\s+(.+?)\s+(?:-?\d+\s*/\s*-?\d+\s*)+$", raw)
    if match:
        return {
            "unidade": match.group(1).strip().lower(),
            "descricao": match.group(2).strip(),
        }
    match = re.match(r"^\s*\S+\s+([A-Za-z]{1,4})\s+(.+)$", raw)
    if match:
        return {
            "unidade": match.group(1).strip().lower(),
            "descricao": match.group(2).strip(),
        }
    return {}


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return Decimal("0")
    text = text.replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _decimal_str(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001'))}"


def _decimal_optional_str(value: Any) -> str:
    if value in (None, ""):
        return ""
    return _decimal_str(_decimal(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return _decimal(value)


def _units_per_box_from_text(value: Any) -> int:
    text = _strip_accents(str(value or "")).upper()
    if not text:
        return 0
    match = re.search(r"\bCX\s*0*(\d{1,3})\b", text)
    if not match:
        match = re.search(r"\bC\s*/\s*0*(\d{1,3})\b", text)
    if not match:
        match = re.search(r"\b(\d{1,3})\s*(UN|UND|UNID|UNIDADE|UNIDADES)\b", text)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return 0


def _units_per_box_from_payload(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    try:
        return int(value.get("unidades_por_caixa") or 0)
    except (TypeError, ValueError):
        return 0


def _effective_count_from_row(row: dict[str, Any]) -> Decimal:
    group = str(row.get("grupo_contagem") or "").strip().upper()
    if group == "PRODUTO":
        boxes = _decimal(row.get("contagem_caixas"))
        units = _decimal(row.get("contagem_unidades"))
        if boxes or units:
            factor = _units_per_box_from_payload(row.get("payload")) or _units_per_box_from_text(row.get("unidade")) or 1
            return boxes * Decimal(factor) + units
    if group in {"300", "600", "1L", "51"}:
        return _decimal(row.get("contagem_real")) + _decimal(row.get("contagem_vazia"))
    return _decimal(row.get("contagem_real"))


def _count_display_str(value: Any, group: str) -> str:
    if value in (None, ""):
        return ""
    decimal_value = _decimal(value)
    if _requires_integer_count(group):
        return str(int(decimal_value))
    return _decimal_str(decimal_value)


def _source_status_label(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status == "aberta_03114902":
        return "Mapa aberto pela 03114902"
    if status == "aberta":
        return "Itens carregados pela 030302"
    return status or "aberta"


def _motorista_display(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return f"Motorista cod. {text.lstrip('0') or '0'}"
    return _clean_select_text(text)


def _normalize_manual_group(value: Any) -> str:
    clean = str(value or "").strip().upper()
    if clean == "OUTROS VASILHAMES":
        clean = "OUTRAS GARRAFEIRAS"
    allowed = {
        "300",
        "600",
        "1L",
        "51",
        "FREEZER",
        "CADEIRA",
        "MESA",
        "BARRIL",
        "BARRACA",
        "OUTRAS GARRAFEIRAS",
        "OUTROS MATERIAIS",
        "PRODUTO",
    }
    return clean if clean in allowed else "OUTROS MATERIAIS"


def _requires_integer_count(group: str) -> bool:
    return str(group or "").strip().upper() in {
        "300",
        "600",
        "1L",
        "51",
        "FREEZER",
        "CADEIRA",
        "MESA",
        "BARRIL",
        "BARRACA",
        "OUTRAS GARRAFEIRAS",
        "OUTROS MATERIAIS",
        "PRODUTO",
    }


def _is_material_group_item(item: ConferenciaItemDraft) -> bool:
    group = _normalize_manual_group(item.grupo_contagem)
    if group == "PRODUTO":
        return False
    tipo = _strip_accents(item.tipo_item).upper()
    category = _strip_accents(f"{item.categoria} {item.descricao}").upper()
    if tipo == "PRODUTO":
        return False
    return tipo in {"MATERIAL", "ITEM", ""} or any(
        token in category
        for token in (
            "GARRAFEIRA",
            "VASILHAME",
            "FREEZER",
            "COOLER",
            "GELADEIRA",
            "CADEIRA",
            "MESA",
            "BARRIL",
            "BARRACA",
            "TENDA",
            "OUTROS MAT",
        )
    )


def _group_description(group: str) -> str:
    clean = str(group or "").strip().upper()
    if clean in {"300", "600", "1L", "51"}:
        return f"Garrafeira {clean}"
    labels = {
        "FREEZER": "Freezer",
        "CADEIRA": "Cadeira",
        "MESA": "Mesa",
        "BARRIL": "Barril",
        "BARRACA": "Barraca",
        "OUTRAS GARRAFEIRAS": "Outras garrafeiras",
        "OUTROS MATERIAIS": "Outros materiais",
    }
    return labels.get(clean, clean or "Material")


def _group_sort_key(value: str) -> tuple[int, str]:
    order = {
        "GRUPO-300": 1,
        "GRUPO-600": 2,
        "GRUPO-1L": 3,
        "GRUPO-51": 4,
        "GRUPO-FREEZER": 5,
        "GRUPO-CADEIRA": 6,
        "GRUPO-MESA": 7,
        "GRUPO-BARRIL": 8,
        "GRUPO-BARRACA": 9,
        "GRUPO-OUTRAS GARRAFEIRAS": 10,
        "GRUPO-OUTROS MATERIAIS": 11,
    }
    clean = str(value or "").strip().upper()
    return (order.get(clean, 99), clean)


def _merge_distinct_text(left: str, right: str) -> str:
    values: list[str] = []
    for item in (left, right):
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
    return " | ".join(values)[:240]


def _manual_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text.isdigit():
        return text.lstrip("0") or "0"
    return re.sub(r"[^A-Z0-9._-]+", "", text)[:80]


def _manual_item_slug(value: Any) -> str:
    text = str(value or "ITEM").strip().upper()
    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return digest


def _display_item_code(value: Any) -> str:
    text = str(value or "").strip()
    if text.upper().startswith("MANUAL-"):
        return ""
    return text


def _digits_or_text(value: Any) -> str:
    text = str(value or "").strip()
    digits = re.sub(r"\D+", "", text)
    return digits or text


def _digits_sort_key(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    digits = re.sub(r"\D+", "", text)
    return (int(digits) if digits else 0, text)


def _norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_accents(str(value or "")).lower())


def _strip_accents(value: str) -> str:
    table = str.maketrans("áàãâäéèêëíìîïóòõôöúùûüçÁÀÃÂÄÉÈÊËÍÌÎÏÓÒÕÔÖÚÙÛÜÇ", "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC")
    return value.translate(table)


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return date.today()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return date.today()


def _date_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")


def _datetime_iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_filial(value: Any) -> str:
    text = str(value or "").strip()
    digits = re.sub(r"\D+", "", text)
    if not digits:
        return ""
    if len(digits) >= 7:
        return str(int(digits[-4:]))
    return str(int(digits))


def _allowed_filiais(context: dict[str, Any] | None) -> set[str] | None:
    if not context or bool(context.get("is_admin")):
        return None
    raw = [str(item).strip() for item in context.get("filiais", ()) if str(item).strip()]
    if not raw or "*" in raw:
        return None
    return {_normalize_filial(item) for item in raw if _normalize_filial(item)}


def _assert_filial_allowed(filial: str, context: dict[str, Any] | None) -> None:
    allowed = _allowed_filiais(context)
    if allowed is not None and _normalize_filial(filial) not in allowed:
        raise PermissionError("Filial fora do acesso do usuario.")


def _clean_identifier(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return fallback
    return text


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(child) for child in value]
    return value
