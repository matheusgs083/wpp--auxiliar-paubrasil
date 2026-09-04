from __future__ import annotations

import io
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterator

from fastapi import HTTPException
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bot_api.db import get_connection_pool


DENOMINATIONS = ("200", "100", "50", "20", "10", "5", "2")


class AdminFinanceiroService:
    def __init__(
        self,
        *,
        database_url: str,
        schema: str,
        connect_timeout_seconds: float,
        filial_labels: dict[str, str],
    ) -> None:
        self.database_url = str(database_url or "").strip()
        self.schema = _clean_identifier(schema or "reports", "reports")
        self.connect_timeout_seconds = float(connect_timeout_seconds or 3)
        self.filial_labels = dict(filial_labels or {})
        self._pool = None
        self._schema_ready = False

    def ensure_schema(self) -> bool:
        if self._schema_ready:
            return True
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.financeiro_caixa_mapas (
                            id BIGSERIAL PRIMARY KEY,
                            caixa_date DATE NOT NULL,
                            filial TEXT NOT NULL DEFAULT '',
                            tipo_bloco TEXT NOT NULL DEFAULT 'mapa',
                            mapa TEXT NOT NULL,
                            mapa_ref TEXT NOT NULL DEFAULT '',
                            motorista TEXT NOT NULL DEFAULT '',
                            placa TEXT NOT NULL DEFAULT '',
                            ajudante1 TEXT NOT NULL DEFAULT '',
                            ajudante2 TEXT NOT NULL DEFAULT '',
                            boletos_rota NUMERIC(14,2) NOT NULL DEFAULT 0,
                            boletos_recebido_qtd NUMERIC(14,2) NOT NULL DEFAULT 0,
                            total_promax NUMERIC(14,2) NOT NULL DEFAULT 0,
                            credito_conta NUMERIC(14,2) NOT NULL DEFAULT 0,
                            dinheiro_promax NUMERIC(14,2) NOT NULL DEFAULT 0,
                            dinheiro JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            moedas NUMERIC(14,2) NOT NULL DEFAULT 0,
                            diarista NUMERIC(14,2) NOT NULL DEFAULT 0,
                            diarista_recibo_recebido BOOLEAN NOT NULL DEFAULT TRUE,
                            pernoite NUMERIC(14,2) NOT NULL DEFAULT 0,
                            hospedagem NUMERIC(14,2) NOT NULL DEFAULT 0,
                            janta NUMERIC(14,2) NOT NULL DEFAULT 0,
                            almoco NUMERIC(14,2) NOT NULL DEFAULT 0,
                            cafe NUMERIC(14,2) NOT NULL DEFAULT 0,
                            pagamentos NUMERIC(14,2) NOT NULL DEFAULT 0,
                            observacao TEXT NOT NULL DEFAULT '',
                            created_by TEXT NOT NULL DEFAULT '',
                            updated_by TEXT NOT NULL DEFAULT '',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            UNIQUE (caixa_date, filial, mapa)
                        )
                        """
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS tipo_bloco TEXT NOT NULL DEFAULT 'mapa'").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS mapa_ref TEXT NOT NULL DEFAULT ''").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS credito_conta NUMERIC(14,2) NOT NULL DEFAULT 0").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS dinheiro_promax NUMERIC(14,2) NOT NULL DEFAULT 0").format(
                        sql.Identifier(self.schema)
                    )
                )
                for column in ("placa", "ajudante1", "ajudante2"):
                    cur.execute(
                        sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS {} TEXT NOT NULL DEFAULT ''").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(column),
                        )
                    )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS boletos_recebido_qtd NUMERIC(14,2) NOT NULL DEFAULT 0").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS diarista_recibo_recebido BOOLEAN NOT NULL DEFAULT TRUE").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_mapas ADD COLUMN IF NOT EXISTS hospedagem NUMERIC(14,2) NOT NULL DEFAULT 0").format(
                        sql.Identifier(self.schema)
                    )
                )
                for table in ("transferencias", "despesas", "vales", "diaristas"):
                    cur.execute(
                        sql.SQL(
                            """
                            CREATE TABLE IF NOT EXISTS {}.{} (
                                id BIGSERIAL PRIMARY KEY,
                                mapa_id BIGINT NOT NULL REFERENCES {}.financeiro_caixa_mapas(id) ON DELETE CASCADE,
                                data TEXT NOT NULL DEFAULT '',
                                nome TEXT NOT NULL DEFAULT '',
                                banco TEXT NOT NULL DEFAULT '',
                                nb TEXT NOT NULL DEFAULT '',
                                nf TEXT NOT NULL DEFAULT '',
                                valor NUMERIC(14,2) NOT NULL DEFAULT 0,
                                observacao TEXT NOT NULL DEFAULT '',
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        ).format(sql.Identifier(self.schema), sql.Identifier(f"financeiro_caixa_{table}"), sql.Identifier(self.schema))
                    )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.financeiro_mapa_prestacao_contas (
                            mapa_id BIGINT PRIMARY KEY REFERENCES {}.financeiro_caixa_mapas(id) ON DELETE CASCADE,
                            rotina TEXT NOT NULL DEFAULT '030322',
                            payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            notas_count INTEGER NOT NULL DEFAULT 0,
                            devolucoes_count INTEGER NOT NULL DEFAULT 0,
                            vasilhames_count INTEGER NOT NULL DEFAULT 0,
                            valor_notas NUMERIC(14,2) NOT NULL DEFAULT 0,
                            valor_devolucao NUMERIC(14,2) NOT NULL DEFAULT 0,
                            valor_liquido NUMERIC(14,2) NOT NULL DEFAULT 0,
                            updated_by TEXT NOT NULL DEFAULT '',
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS financeiro_mapa_prestacao_updated_idx ON {}.financeiro_mapa_prestacao_contas (updated_at)"
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_vales ADD COLUMN IF NOT EXISTS assinado BOOLEAN NOT NULL DEFAULT FALSE").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.financeiro_caixa_diaristas ADD COLUMN IF NOT EXISTS recibo_recebido BOOLEAN NOT NULL DEFAULT TRUE").format(
                        sql.Identifier(self.schema)
                    )
                )
                cur.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS financeiro_caixa_mapas_date_idx ON {}.financeiro_caixa_mapas (caixa_date, filial)"
                    ).format(sql.Identifier(self.schema))
                )
            conn.commit()
        self._schema_ready = True
        return True

    def list_caixa(self, *, data: str, filial: str = "", context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_schema()
        caixa_date = _parse_date(data)
        requested_filial = _normalize_filial(filial)
        allowed_filiais = _allowed_filiais(context)
        if requested_filial and allowed_filiais is not None and requested_filial not in allowed_filiais:
            raise HTTPException(status_code=403, detail="Filial fora do acesso do usuario.")
        if not requested_filial:
            return {
                "data": caixa_date.isoformat(),
                "filial": "",
                "filiais": self._visible_filiais(allowed_filiais),
                "maps": [],
                "summary": self._build_summary([]),
            }

        params: list[Any] = [caixa_date]
        where = ["caixa_date = %s"]
        if requested_filial:
            where.append("filial = %s")
            params.append(requested_filial)
        elif allowed_filiais is not None:
            where.append("filial = ANY(%s)")
            params.append(list(allowed_filiais))

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT *
                        FROM {}.financeiro_caixa_mapas
                        WHERE {}
                        ORDER BY filial NULLS FIRST,
                            CASE tipo_bloco
                                WHEN 'mapa' THEN 0
                                WHEN 'compra' THEN 1
                                WHEN 'despesa' THEN 2
                                WHEN 'vale' THEN 3
                                ELSE 4
                            END,
                            mapa
                        """
                    ).format(sql.Identifier(self.schema), sql.SQL(" AND ").join(sql.SQL(item) for item in where)),
                    params,
                )
                mapas = [dict(row) for row in cur.fetchall()]
                ids = [int(row["id"]) for row in mapas]
                details = self._load_details(cur, ids)
                rotas_dia = self._load_rotas_dia_031120(cur, caixa_date=caixa_date, filial=requested_filial)

        records = [self._serialize_map(row, details) for row in mapas]
        return {
            "data": caixa_date.isoformat(),
            "filial": requested_filial,
            "filiais": self._visible_filiais(allowed_filiais),
            "maps": records,
            "summary": self._build_summary(records),
            "rotas_dia": rotas_dia,
        }

    def upsert_mapa(self, payload: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_schema()
        caixa_date = _parse_date(payload.get("data") or payload.get("caixa_date"))
        filial = _normalize_filial(payload.get("filial"))
        if not filial:
            raise HTTPException(status_code=400, detail="Escolha uma revenda antes de salvar o caixa.")
        tipo_bloco = _normalize_tipo_bloco(payload.get("tipo_bloco"))
        mapa = str(payload.get("mapa") or "").strip()
        mapa_ref = str(payload.get("mapa_ref") or "").strip()
        if tipo_bloco != "mapa" and not mapa:
            mapa = f"{tipo_bloco.upper()}-{mapa_ref or 'GERAL'}-{int(datetime.now().timestamp())}"
        if tipo_bloco == "mapa":
            mapa_ref = mapa
        if not mapa:
            raise HTTPException(status_code=400, detail="Informe o numero do mapa.")
        allowed_filiais = _allowed_filiais(context)
        if allowed_filiais is not None and filial not in allowed_filiais:
            raise HTTPException(status_code=403, detail="Filial fora do acesso do usuario.")

        dinheiro = _normalize_dinheiro(payload.get("dinheiro") or {})
        dirty_fields = _normalize_financeiro_dirty_fields(payload.get("dirty_fields"))
        dirty_flags = _financeiro_manual_update_flags(dirty_fields)
        dinheiro_promax_payload = _decimal(payload.get("dinheiro_promax"))
        total_promax_payload = dinheiro_promax_payload
        username = str((context or {}).get("username") or (context or {}).get("mode") or "")
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                diarista = _decimal(payload.get("diarista"))
                diarista_recibo_recebido = _bool(payload.get("diarista_recibo_recebido"), default=True)
                motorista = str(payload.get("motorista") or "").strip()
                placa = str(payload.get("placa") or "").strip()
                ajudante1 = str(payload.get("ajudante1") or "").strip()
                ajudante2 = str(payload.get("ajudante2") or "").strip()
                schema_identifiers = [sql.Identifier(self.schema)] * 20
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.financeiro_caixa_mapas (
                            caixa_date, filial, tipo_bloco, mapa, mapa_ref, motorista, placa, ajudante1, ajudante2, boletos_rota,
                            boletos_recebido_qtd, total_promax, credito_conta, dinheiro_promax, dinheiro,
                            moedas, diarista, diarista_recibo_recebido, pernoite, hospedagem, janta, almoco, cafe,
                            pagamentos, observacao, created_by, updated_by
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (caixa_date, filial, mapa) DO UPDATE SET
                            tipo_bloco = EXCLUDED.tipo_bloco,
                            mapa_ref = EXCLUDED.mapa_ref,
                            motorista = CASE
                                WHEN %s THEN EXCLUDED.motorista
                                ELSE {}.financeiro_caixa_mapas.motorista
                            END,
                            placa = CASE
                                WHEN %s THEN EXCLUDED.placa
                                ELSE {}.financeiro_caixa_mapas.placa
                            END,
                            ajudante1 = CASE
                                WHEN %s THEN EXCLUDED.ajudante1
                                ELSE {}.financeiro_caixa_mapas.ajudante1
                            END,
                            ajudante2 = CASE
                                WHEN %s THEN EXCLUDED.ajudante2
                                ELSE {}.financeiro_caixa_mapas.ajudante2
                            END,
                            boletos_rota = CASE WHEN %s THEN EXCLUDED.boletos_rota ELSE {}.financeiro_caixa_mapas.boletos_rota END,
                            boletos_recebido_qtd = CASE WHEN %s THEN EXCLUDED.boletos_recebido_qtd ELSE {}.financeiro_caixa_mapas.boletos_recebido_qtd END,
                            total_promax = CASE WHEN %s THEN EXCLUDED.total_promax ELSE {}.financeiro_caixa_mapas.total_promax END,
                            credito_conta = CASE WHEN %s THEN EXCLUDED.credito_conta ELSE {}.financeiro_caixa_mapas.credito_conta END,
                            dinheiro_promax = CASE WHEN %s THEN EXCLUDED.dinheiro_promax ELSE {}.financeiro_caixa_mapas.dinheiro_promax END,
                            dinheiro = CASE WHEN %s THEN EXCLUDED.dinheiro ELSE {}.financeiro_caixa_mapas.dinheiro END,
                            moedas = CASE WHEN %s THEN EXCLUDED.moedas ELSE {}.financeiro_caixa_mapas.moedas END,
                            diarista = CASE WHEN %s THEN EXCLUDED.diarista ELSE {}.financeiro_caixa_mapas.diarista END,
                            diarista_recibo_recebido = CASE WHEN %s THEN EXCLUDED.diarista_recibo_recebido ELSE {}.financeiro_caixa_mapas.diarista_recibo_recebido END,
                            pernoite = CASE WHEN %s THEN EXCLUDED.pernoite ELSE {}.financeiro_caixa_mapas.pernoite END,
                            hospedagem = CASE WHEN %s THEN EXCLUDED.hospedagem ELSE {}.financeiro_caixa_mapas.hospedagem END,
                            janta = CASE WHEN %s THEN EXCLUDED.janta ELSE {}.financeiro_caixa_mapas.janta END,
                            almoco = CASE WHEN %s THEN EXCLUDED.almoco ELSE {}.financeiro_caixa_mapas.almoco END,
                            cafe = CASE WHEN %s THEN EXCLUDED.cafe ELSE {}.financeiro_caixa_mapas.cafe END,
                            pagamentos = EXCLUDED.pagamentos,
                            observacao = CASE WHEN %s THEN EXCLUDED.observacao ELSE {}.financeiro_caixa_mapas.observacao END,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW()
                        RETURNING *
                        """
                    ).format(*schema_identifiers),
                    (
                        caixa_date,
                        filial,
                        tipo_bloco,
                        mapa,
                        mapa_ref,
                        motorista,
                        placa,
                        ajudante1,
                        ajudante2,
                        _decimal(payload.get("boletos_rota")),
                        _decimal(payload.get("boletos_recebido_qtd")),
                        total_promax_payload,
                        _decimal(payload.get("credito_conta")),
                        dinheiro_promax_payload,
                        Jsonb(dinheiro),
                        _decimal(payload.get("moedas")),
                        diarista,
                        diarista_recibo_recebido,
                        _decimal(payload.get("pernoite")),
                        _decimal(payload.get("hospedagem")),
                        _decimal(payload.get("janta")),
                        _decimal(payload.get("almoco")),
                        _decimal(payload.get("cafe")),
                        Decimal("0"),
                        str(payload.get("observacao") or "").strip(),
                        username,
                        username,
                        dirty_flags["motorista"],
                        dirty_flags["placa"],
                        dirty_flags["ajudante1"],
                        dirty_flags["ajudante2"],
                        dirty_flags["boletos_rota"],
                        dirty_flags["boletos_recebido_qtd"],
                        dirty_flags["total_promax"] or dirty_flags["dinheiro_promax"],
                        dirty_flags["credito_conta"],
                        dirty_flags["dinheiro_promax"],
                        dirty_flags["dinheiro"],
                        dirty_flags["moedas"],
                        dirty_flags["diarista"],
                        dirty_flags["diarista_recibo_recebido"],
                        dirty_flags["pernoite"],
                        dirty_flags["hospedagem"],
                        dirty_flags["janta"],
                        dirty_flags["almoco"],
                        dirty_flags["cafe"],
                        dirty_flags["observacao"],
                    ),
                )
                row = dict(cur.fetchone() or {})
                mapa_id = int(row["id"])
                self._replace_details(cur, mapa_id, "transferencias", payload.get("transferencias") or [])
                self._replace_details(cur, mapa_id, "despesas", payload.get("despesas") or [])
                self._replace_details(cur, mapa_id, "vales", payload.get("vales") or [])
                self._replace_details(cur, mapa_id, "diaristas", payload.get("diaristas") or [])
                details = self._load_details(cur, [mapa_id])
            conn.commit()
        return {"ok": True, "map": self._serialize_map(row, details)}

    def sync_fechamento_promax(self, payload: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_schema()
        caixa_date = _parse_date(payload.get("data") or payload.get("caixa_date"))
        filial = _normalize_filial(payload.get("filial"))
        mapa = str(payload.get("mapa") or "").strip()
        if not filial:
            raise HTTPException(status_code=400, detail="Filial do fechamento nao informada.")
        if not mapa:
            raise HTTPException(status_code=400, detail="Mapa do fechamento nao informado.")

        allowed_filiais = _allowed_filiais(context)
        if allowed_filiais is not None and filial not in allowed_filiais:
            raise HTTPException(status_code=403, detail="Filial fora do acesso do usuario.")

        result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        dados_fechamento = _extract_dados_fechamento_03030702(result_payload)
        dados_030322 = _extract_dados_030322(result_payload)
        dados_030303 = _extract_030303_fields(result_payload)
        metrics = _financeiro_metrics_from_fechamento(dados_fechamento)
        has_financeiro_data = bool(dados_fechamento)
        username = str((context or {}).get("username") or (context or {}).get("worker_id") or "promax-worker")
        obs_parts = [
            "Mapa criado/atualizado automaticamente pelo fechamento Promax.",
            f"Job: {payload.get('job_id') or result_payload.get('job_id') or '-'}",
        ]
        integration_code = _nested_get(result_payload, ("metadata", "integration_code")) or _nested_get(result_payload, ("integration_code",))
        if integration_code:
            obs_parts.append(f"Codigo: {integration_code}")
        if dados_fechamento:
            diferencas = dados_fechamento.get("diferencas") if isinstance(dados_fechamento, dict) else None
            if isinstance(diferencas, dict) and diferencas.get("dataEmi"):
                obs_parts.append(f"Data Promax: {diferencas.get('dataEmi')}")

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                dados_030303 = _merge_identity_fallback(
                    dados_030303,
                    self._lookup_conferencia_route_identity(cur, filial=filial, mapa=mapa),
                )
                motorista_promax = dados_030303.get("motorista") or ""
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.financeiro_caixa_mapas (
                            caixa_date, filial, tipo_bloco, mapa, mapa_ref, motorista, placa, ajudante1, ajudante2,
                            boletos_rota, total_promax, credito_conta, dinheiro_promax, observacao,
                            created_by, updated_by
                        )
                        VALUES (%s, %s, 'mapa', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (caixa_date, filial, mapa) DO UPDATE SET
                            tipo_bloco = 'mapa',
                            mapa_ref = EXCLUDED.mapa_ref,
                            motorista = CASE
                                WHEN EXCLUDED.motorista <> ''
                                 AND {} THEN EXCLUDED.motorista
                                ELSE {}.financeiro_caixa_mapas.motorista
                            END,
                            placa = CASE
                                WHEN EXCLUDED.placa <> ''
                                 AND {} THEN EXCLUDED.placa
                                ELSE {}.financeiro_caixa_mapas.placa
                            END,
                            ajudante1 = CASE
                                WHEN EXCLUDED.ajudante1 <> ''
                                 AND {} THEN EXCLUDED.ajudante1
                                ELSE {}.financeiro_caixa_mapas.ajudante1
                            END,
                            ajudante2 = CASE
                                WHEN EXCLUDED.ajudante2 <> ''
                                 AND {} THEN EXCLUDED.ajudante2
                                ELSE {}.financeiro_caixa_mapas.ajudante2
                            END,
                            boletos_rota = CASE WHEN %s THEN EXCLUDED.boletos_rota ELSE {}.financeiro_caixa_mapas.boletos_rota END,
                            total_promax = CASE WHEN %s THEN EXCLUDED.total_promax ELSE {}.financeiro_caixa_mapas.total_promax END,
                            credito_conta = CASE WHEN %s THEN EXCLUDED.credito_conta ELSE {}.financeiro_caixa_mapas.credito_conta END,
                            dinheiro_promax = CASE WHEN %s THEN EXCLUDED.dinheiro_promax ELSE {}.financeiro_caixa_mapas.dinheiro_promax END,
                            observacao = CASE
                                WHEN {}.financeiro_caixa_mapas.observacao = '' THEN EXCLUDED.observacao
                                WHEN {}.financeiro_caixa_mapas.observacao LIKE %s THEN EXCLUDED.observacao
                                ELSE {}.financeiro_caixa_mapas.observacao
                            END,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW()
                        RETURNING *
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        _sql_blankish_field(self.schema, "financeiro_caixa_mapas", "motorista"),
                        sql.Identifier(self.schema),
                        _sql_blankish_field(self.schema, "financeiro_caixa_mapas", "placa"),
                        sql.Identifier(self.schema),
                        _sql_blankish_field(self.schema, "financeiro_caixa_mapas", "ajudante1"),
                        sql.Identifier(self.schema),
                        _sql_blankish_field(self.schema, "financeiro_caixa_mapas", "ajudante2"),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                        sql.Identifier(self.schema),
                    ),
                    (
                        caixa_date,
                        filial,
                        mapa,
                        mapa,
                        motorista_promax,
                        dados_030303.get("placa") or "",
                        dados_030303.get("ajudante1") or "",
                        dados_030303.get("ajudante2") or "",
                        metrics["boletos_rota"],
                        metrics["total_promax"],
                        metrics["credito_conta"],
                        metrics["dinheiro_promax"],
                        "\n".join(obs_parts),
                        username,
                        username,
                        has_financeiro_data,
                        has_financeiro_data,
                        has_financeiro_data,
                        has_financeiro_data,
                        "Mapa criado/atualizado automaticamente pelo fechamento Promax.%",
                    ),
                )
                row = dict(cur.fetchone() or {})
                mapa_id = int(row["id"])
                if dados_030322:
                    self._upsert_prestacao_contas(cur, mapa_id=mapa_id, payload=dados_030322, username=username)
                details = self._load_details(cur, [mapa_id])
            conn.commit()
        return {
            "ok": True,
            "map": self._serialize_map(row, details),
            "metrics": {
                "boletos_rota": _money(metrics["boletos_rota"]),
                "total_promax": _money(metrics["total_promax"]),
                "credito_conta": _money(metrics["credito_conta"]),
                "dinheiro_promax": _money(metrics["dinheiro_promax"]),
            },
            "dados_fechamento_found": bool(dados_fechamento),
            "dados_030322_found": bool(dados_030322),
        }

    def get_mapa_prestacao_contas(self, *, mapa_id: int, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_schema()
        allowed_filiais = _allowed_filiais(context)
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT m.id, m.caixa_date, m.filial, m.mapa, m.motorista, m.placa,
                               p.payload, p.notas_count, p.devolucoes_count, p.vasilhames_count,
                               p.valor_notas, p.valor_devolucao, p.valor_liquido, p.updated_at
                        FROM {}.financeiro_caixa_mapas m
                        LEFT JOIN {}.financeiro_mapa_prestacao_contas p ON p.mapa_id = m.id
                        WHERE m.id = %s
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(self.schema)),
                    (int(mapa_id),),
                )
                row = dict(cur.fetchone() or {})
        if not row:
            raise HTTPException(status_code=404, detail="Mapa nao encontrado.")
        filial = str(row.get("filial") or "")
        if allowed_filiais is not None and filial not in allowed_filiais:
            raise HTTPException(status_code=403, detail="Filial fora do acesso do usuario.")
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        summary = {
            "available": bool(payload),
            "notas_count": int(row.get("notas_count") or 0),
            "devolucoes_count": int(row.get("devolucoes_count") or 0),
            "vasilhames_count": int(row.get("vasilhames_count") or 0),
            "valor_notas": _money(row.get("valor_notas")),
            "valor_devolucao": _money(row.get("valor_devolucao")),
            "valor_liquido": _money(row.get("valor_liquido")),
            "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else str(row.get("updated_at") or ""),
        }
        return {
            "ok": True,
            "mapa": {
                "id": int(row["id"]),
                "data": row["caixa_date"].isoformat() if hasattr(row.get("caixa_date"), "isoformat") else str(row.get("caixa_date") or ""),
                "filial": filial,
                "filial_nome": self.filial_labels.get(filial, ""),
                "mapa": str(row.get("mapa") or ""),
                "motorista": str(row.get("motorista") or ""),
                "placa": str(row.get("placa") or ""),
            },
            "summary": summary,
            "prestacao_contas": payload,
        }

    def _upsert_prestacao_contas(self, cur: Any, *, mapa_id: int, payload: dict[str, Any], username: str) -> None:
        summary = _prestacao_030322_summary(payload)
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {}.financeiro_mapa_prestacao_contas (
                    mapa_id, rotina, payload, notas_count, devolucoes_count, vasilhames_count,
                    valor_notas, valor_devolucao, valor_liquido, updated_by
                )
                VALUES (%s, '030322', %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (mapa_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    notas_count = EXCLUDED.notas_count,
                    devolucoes_count = EXCLUDED.devolucoes_count,
                    vasilhames_count = EXCLUDED.vasilhames_count,
                    valor_notas = EXCLUDED.valor_notas,
                    valor_devolucao = EXCLUDED.valor_devolucao,
                    valor_liquido = EXCLUDED.valor_liquido,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = NOW()
                """
            ).format(sql.Identifier(self.schema)),
            (
                int(mapa_id),
                Jsonb(payload),
                int(summary["notas_count"]),
                int(summary["devolucoes_count"]),
                int(summary["vasilhames_count"]),
                summary["valor_notas"],
                summary["valor_devolucao"],
                summary["valor_liquido"],
                str(username or ""),
            ),
        )

    def _lookup_conferencia_route_identity(self, cur: Any, *, filial: str, mapa: str) -> dict[str, str]:
        if not _relation_exists_cur(cur, self.schema, "conferencia_mapas"):
            return {}
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
            "placa": _clean_identity_text(row.get("placa"), keep_code=True),
            "motorista": _clean_identity_text(row.get("motorista")),
            "ajudante1": _clean_identity_text(row.get("ajudante1")),
            "ajudante2": _clean_identity_text(row.get("ajudante2")),
        }

    def delete_mapa(self, mapa_id: int, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("SELECT filial FROM {}.financeiro_caixa_mapas WHERE id = %s").format(sql.Identifier(self.schema)),
                    (int(mapa_id),),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Mapa nao encontrado.")
                allowed_filiais = _allowed_filiais(context)
                if allowed_filiais is not None and str(row["filial"]) not in allowed_filiais:
                    raise HTTPException(status_code=403, detail="Filial fora do acesso do usuario.")
                cur.execute(
                    sql.SQL("DELETE FROM {}.financeiro_caixa_mapas WHERE id = %s").format(sql.Identifier(self.schema)),
                    (int(mapa_id),),
                )
            conn.commit()
        return {"ok": True, "deleted_id": int(mapa_id)}

    def resolve_fechamento_km(self, *, filial: str, mapa: str, caixa_date: date) -> dict[str, Any]:
        clean_filial = _normalize_filial(filial)
        clean_mapa = _strip_left_zeroes(mapa)
        if not clean_filial or not clean_mapa:
            return {"ok": False, "km_atual": "", "km_inicial": "", "km_prev": "", "source": "missing_payload"}

        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                km_inicial = self._lookup_031120_saida_km_atual(
                    cur,
                    filial=clean_filial,
                    mapa=clean_mapa,
                    caixa_date=caixa_date,
                )
                km_prev = self._lookup_03114902_km_prev(
                    cur,
                    filial=clean_filial,
                    mapa=clean_mapa,
                    caixa_date=caixa_date,
                )

        if km_inicial > 0 and km_prev > 0:
            return {
                "ok": True,
                "km_atual": _fmt_km_integer(km_inicial + km_prev),
                "km_inicial": _fmt_km_integer(km_inicial),
                "km_prev": _fmt_km_integer(km_prev),
                "source": "031120_km_atual_plus_03114902_km_prev",
            }
        return {
            "ok": False,
            "km_atual": "",
            "km_inicial": _fmt_km_integer(km_inicial),
            "km_prev": _fmt_km_integer(km_prev),
            "source": "insufficient_data",
        }

    def _lookup_031120_saida_km_atual(self, cur: Any, *, filial: str, mapa: str, caixa_date: date) -> Decimal:
        if not _relation_exists_cur(cur, self.schema, "relatorio_031120_rows") or not _relation_exists_cur(cur, self.schema, "dataset_state"):
            return Decimal("0")
        dataset_name = f"relatorio_031120_op_{_normalize_filial(filial)}"
        cur.execute(
            sql.SQL(
                """
                SELECT r.payload
                FROM {}.relatorio_031120_rows r
                JOIN {}.dataset_state s
                  ON s.dataset_name = r.dataset_name
                 AND s.active_batch_id = r.batch_id
                WHERE r.dataset_name = %s
                  AND r.filial = %s
                ORDER BY r.row_number
                """
            ).format(sql.Identifier(self.schema), sql.Identifier(self.schema)),
            (dataset_name, _normalize_filial(filial)),
        )
        km_carregado_fallback = Decimal("0")
        for row in cur.fetchall():
            payload = dict(row.get("payload") or {})
            row_date = _parse_report_date(payload.get("Emissao")) or _parse_report_date(payload.get("DtOper"))
            if row_date != caixa_date:
                continue
            if _strip_left_zeroes(payload.get("Mapa")) != mapa:
                continue
            fase = _normalize_031120_fase(payload.get("Fase"))
            km_atual = _decimal(payload.get("KmAtual") or payload.get("KM Atual") or payload.get("Km Atual"))
            if fase == "saida" and km_atual > 0:
                return km_atual
            if fase == "carregado" and km_atual > 0:
                km_carregado_fallback = km_atual
        return km_carregado_fallback

    def _lookup_03114902_km_prev(self, cur: Any, *, filial: str, mapa: str, caixa_date: date) -> Decimal:
        if not _relation_exists_cur(cur, self.schema, "relatorio_031120_rows") or not _relation_exists_cur(cur, self.schema, "dataset_state"):
            return Decimal("0")
        cur.execute(
            sql.SQL(
                """
                SELECT r.payload
                FROM {}.relatorio_031120_rows r
                JOIN {}.dataset_state s
                  ON s.dataset_name = r.dataset_name
                 AND s.active_batch_id = r.batch_id
                WHERE r.dataset_name = 'relatorio_03114902_geo'
                ORDER BY r.row_number
                """
            ).format(sql.Identifier(self.schema), sql.Identifier(self.schema)),
        )
        for row in cur.fetchall():
            payload = dict(row.get("payload") or {})
            row_date = _parse_report_date(payload.get("Data Entrega")) or _parse_report_date(payload.get("Data"))
            if row_date != caixa_date:
                continue
            if _normalize_filial(payload.get("UNB")) != filial:
                continue
            if _strip_left_zeroes(payload.get("Nro do Mapa")) != mapa:
                continue
            km_prev = _decimal(payload.get("KM Prev.") or payload.get("KM Prev") or payload.get("Km Prev."))
            if km_prev > 0:
                return km_prev
        return Decimal("0")

    def export_caixa_pdf(self, *, data: str, filial: str = "", context: dict[str, Any] | None = None) -> tuple[bytes, str]:
        payload = self.list_caixa(data=data, filial=filial, context=context)
        if not str(payload.get("filial") or "").strip():
            raise HTTPException(status_code=400, detail="Escolha uma revenda para exportar o caixa.")
        pdf_bytes = _build_caixa_pdf(payload)
        safe_date = str(payload.get("data") or date.today().isoformat()).replace("/", "-")
        safe_filial = str(payload.get("filial") or "revenda").strip() or "revenda"
        return pdf_bytes, f"caixa-financeiro-{safe_filial}-{safe_date}.pdf"

    def _load_details(self, cur: Any, ids: list[int]) -> dict[str, dict[int, Any]]:
        detail_keys = ("transferencias", "despesas", "vales", "diaristas")
        output: dict[str, dict[int, Any]] = {key: {item: [] for item in ids} for key in detail_keys}
        output["prestacao_contas"] = {item: None for item in ids}
        if not ids:
            return output
        for key in detail_keys:
            extra_cols = sql.SQL(", assinado") if key == "vales" else sql.SQL("")
            if key == "diaristas":
                extra_cols = sql.SQL(", recibo_recebido")
            cur.execute(
                sql.SQL(
                    """
                    SELECT mapa_id, data, nome, banco, nb, nf, valor, observacao{}
                    FROM {}.{}
                    WHERE mapa_id = ANY(%s)
                    ORDER BY id
                    """
                ).format(extra_cols, sql.Identifier(self.schema), sql.Identifier(f"financeiro_caixa_{key}")),
                (ids,),
            )
            for row in cur.fetchall():
                item = dict(row)
                mapa_id = int(item.pop("mapa_id"))
                item["valor"] = _money(item.get("valor"))
                output[key].setdefault(mapa_id, []).append(item)
        cur.execute(
            sql.SQL(
                """
                SELECT mapa_id, notas_count, devolucoes_count, vasilhames_count,
                       valor_notas, valor_devolucao, valor_liquido, updated_at
                FROM {}.financeiro_mapa_prestacao_contas
                WHERE mapa_id = ANY(%s)
                """
            ).format(sql.Identifier(self.schema)),
            (ids,),
        )
        for row in cur.fetchall():
            item = dict(row)
            mapa_id = int(item.pop("mapa_id"))
            item["valor_notas"] = _money(item.get("valor_notas"))
            item["valor_devolucao"] = _money(item.get("valor_devolucao"))
            item["valor_liquido"] = _money(item.get("valor_liquido"))
            item["updated_at"] = item["updated_at"].isoformat() if hasattr(item.get("updated_at"), "isoformat") else str(item.get("updated_at") or "")
            item["available"] = True
            output["prestacao_contas"][mapa_id] = item
        return output

    def _replace_details(self, cur: Any, mapa_id: int, key: str, rows: list[dict[str, Any]]) -> None:
        table = f"financeiro_caixa_{key}"
        cur.execute(
            sql.SQL("DELETE FROM {}.{} WHERE mapa_id = %s").format(sql.Identifier(self.schema), sql.Identifier(table)),
            (mapa_id,),
        )
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            valor = _decimal(raw.get("valor"))
            if valor == 0 and not any(str(raw.get(field) or "").strip() for field in ("data", "nome", "banco", "nb", "nf", "observacao")):
                continue
            values = (
                mapa_id,
                str(raw.get("data") or "").strip(),
                str(raw.get("nome") or "").strip(),
                str(raw.get("banco") or "").strip(),
                str(raw.get("nb") or "").strip(),
                str(raw.get("nf") or "").strip(),
                valor,
                str(raw.get("observacao") or "").strip(),
            )
            if key == "vales":
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.{} (mapa_id, data, nome, banco, nb, nf, valor, observacao, assinado)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(table)),
                    values + (_bool(raw.get("assinado")),),
                )
            elif key == "diaristas":
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.{} (mapa_id, data, nome, banco, nb, nf, valor, observacao, recibo_recebido)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(table)),
                    values + (_bool(raw.get("recibo_recebido"), default=True),),
                )
            else:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.{} (mapa_id, data, nome, banco, nb, nf, valor, observacao)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """
                    ).format(sql.Identifier(self.schema), sql.Identifier(table)),
                    values,
                )

    def _serialize_map(self, row: dict[str, Any], details: dict[str, dict[int, list[dict[str, Any]]]]) -> dict[str, Any]:
        mapa_id = int(row["id"])
        dinheiro = _normalize_dinheiro(row.get("dinheiro") or {})
        hospedagem_total = _decimal(row.get("pernoite")) + _decimal(row.get("hospedagem"))
        dinheiro_total = sum(Decimal(denom) * Decimal(qtd) for denom, qtd in dinheiro.items())
        transferencias_total = _sum_detail(details["transferencias"].get(mapa_id, []))
        despesas_total = _sum_detail(details["despesas"].get(mapa_id, []))
        vales = details["vales"].get(mapa_id, [])
        diaristas = details["diaristas"].get(mapa_id, [])
        diarista_avulso = _decimal(row.get("diarista"))
        diarista_avulso_com_recibo = _bool(row.get("diarista_recibo_recebido"), default=True)
        diaristas_com_recibo = [item for item in diaristas if _bool(item.get("recibo_recebido"), default=True)]
        vales_diaristas = _diarista_vale_rows(
            motorista=str(row.get("motorista") or ""),
            diarista=diarista_avulso,
            diarista_recibo_recebido=diarista_avulso_com_recibo,
            diaristas=diaristas,
            vales=vales,
        )
        vales_total = _sum_detail([item for item in vales if not _is_vale_chapa(item)]) + _sum_detail(vales_diaristas)
        diaristas_total = (diarista_avulso if diarista_avulso_com_recibo else Decimal("0")) + _sum_detail(diaristas_com_recibo)
        alimentacao_total = (
            hospedagem_total
            + _decimal(row.get("janta"))
            + _decimal(row.get("almoco"))
            + _decimal(row.get("cafe"))
        )
        boletos_rota = _decimal(row.get("boletos_rota"))
        boletos_recebido_qtd = _decimal(row.get("boletos_recebido_qtd"))
        boletos_diferenca_qtd = boletos_rota - boletos_recebido_qtd
        total_apurado = dinheiro_total + _decimal(row.get("moedas")) + transferencias_total + despesas_total + vales_total + diaristas_total + alimentacao_total
        dinheiro_promax = _decimal(row.get("dinheiro_promax"))
        total_promax = dinheiro_promax
        diferenca = total_apurado - dinheiro_promax
        tipo_bloco = _normalize_tipo_bloco(row.get("tipo_bloco"))
        mapa_key = str(row.get("mapa") or "")
        mapa_ref = str(row.get("mapa_ref") or "") or mapa_key
        prestacao_summary = (details.get("prestacao_contas") or {}).get(mapa_id)
        return {
            "id": mapa_id,
            "data": row["caixa_date"].isoformat() if hasattr(row.get("caixa_date"), "isoformat") else str(row.get("caixa_date") or ""),
            "filial": str(row.get("filial") or ""),
            "filial_nome": self.filial_labels.get(str(row.get("filial") or ""), ""),
            "tipo_bloco": tipo_bloco,
            "is_compra": tipo_bloco == "compra",
            "mapa": mapa_ref,
            "mapa_key": mapa_key,
            "mapa_ref": mapa_ref,
            "motorista": str(row.get("motorista") or ""),
            "placa": str(row.get("placa") or ""),
            "ajudante1": str(row.get("ajudante1") or ""),
            "ajudante2": str(row.get("ajudante2") or ""),
            "boletos_rota": _money(boletos_rota),
            "boletos_recebido_qtd": _money(boletos_recebido_qtd),
            "boletos_diferenca_qtd": _money(boletos_diferenca_qtd),
            "total_promax": _money(total_promax),
            "credito_conta": _money(row.get("credito_conta")),
            "dinheiro_promax": _money(dinheiro_promax),
            "dinheiro": dinheiro,
            "dinheiro_total": _money(dinheiro_total),
            "moedas": _money(row.get("moedas")),
            "diarista": _money(row.get("diarista")),
            "diarista_recibo_recebido": _bool(row.get("diarista_recibo_recebido"), default=True),
            "pernoite": 0.0,
            "hospedagem": _money(hospedagem_total),
            "janta": _money(row.get("janta")),
            "almoco": _money(row.get("almoco")),
            "cafe": _money(row.get("cafe")),
            "transferencias": details["transferencias"].get(mapa_id, []),
            "despesas": details["despesas"].get(mapa_id, []),
            "vales": vales,
            "vales_consolidados": vales + vales_diaristas,
            "diaristas": diaristas,
            "transferencias_total": _money(transferencias_total),
            "despesas_total": _money(despesas_total),
            "vales_total": _money(vales_total),
            "diaristas_total": _money(diaristas_total),
            "alimentacao_pernoite_total": 0.0,
            "alimentacao_hospedagem_total": _money(hospedagem_total),
            "alimentacao_janta_total": _money(row.get("janta")),
            "alimentacao_almoco_total": _money(row.get("almoco")),
            "alimentacao_cafe_total": _money(row.get("cafe")),
            "alimentacao_total": _money(alimentacao_total),
            "total_apurado": _money(total_apurado),
            "diferenca": _money(diferenca),
            "status": "LANCAMENTO" if tipo_bloco in {"despesa", "vale"} else ("OK" if abs(diferenca) < Decimal("0.01") else "DIVERGENTE"),
            "observacao": str(row.get("observacao") or ""),
            "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else str(row.get("updated_at") or ""),
            "prestacao_contas": prestacao_summary or {"available": False},
        }

    def _build_summary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        mapa_records = [row for row in records if row.get("tipo_bloco") == "mapa"]
        keys = (
            "total_promax",
            "boletos_rota",
            "boletos_recebido_qtd",
            "boletos_diferenca_qtd",
            "dinheiro_total",
            "dinheiro_promax",
            "moedas",
            "transferencias_total",
            "despesas_total",
            "vales_total",
            "diaristas_total",
            "alimentacao_pernoite_total",
            "alimentacao_hospedagem_total",
            "alimentacao_janta_total",
            "alimentacao_almoco_total",
            "alimentacao_cafe_total",
            "alimentacao_total",
            "total_apurado",
            "diferenca",
            "credito_conta",
        )
        summary = {key: _money(sum(_decimal(row.get(key)) for row in records)) for key in keys}
        summary["diferenca"] = _money(sum(_decimal(row.get("diferenca")) for row in mapa_records))
        numerario_total = _decimal(summary.get("dinheiro_total"))
        depositos_total = _decimal(summary.get("credito_conta")) + _decimal(summary.get("transferencias_total"))
        base_dinheiro_deposito = numerario_total + depositos_total
        summary["numerario_total"] = _money(numerario_total)
        summary["depositos_total"] = _money(depositos_total)
        summary["dinheiro_percent"] = _money((numerario_total / base_dinheiro_deposito * Decimal("100")) if base_dinheiro_deposito else Decimal("0"))
        summary["deposito_percent"] = _money((depositos_total / base_dinheiro_deposito * Decimal("100")) if base_dinheiro_deposito else Decimal("0"))
        summary["mapas"] = len([row for row in records if row.get("tipo_bloco") == "mapa"])
        summary["compras"] = len([row for row in records if row.get("tipo_bloco") == "compra"])
        summary["despesas_blocos"] = len([row for row in records if row.get("tipo_bloco") == "despesa"])
        summary["vales_blocos"] = len([row for row in records if row.get("tipo_bloco") == "vale"])
        summary["status"] = "OK" if abs(_decimal(summary["diferenca"])) < Decimal("0.01") else "DIVERGENTE"
        return summary

    def _build_consolidado(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        output: dict[str, list[dict[str, Any]]] = {"despesas": [], "vales": [], "transferencias": [], "diaristas": []}
        for record in records:
            base = {
                "mapa_id": record.get("id"),
                "mapa": record.get("mapa") or "",
                "motorista": record.get("motorista") or "",
                "filial": record.get("filial") or "",
                "filial_nome": record.get("filial_nome") or "",
                "tipo_bloco": record.get("tipo_bloco") or "mapa",
            }
            for key in output:
                for item in record.get(key, []) or []:
                    merged = dict(base)
                    merged.update(item)
                    output[key].append(merged)
        return output

    def _load_rotas_dia_031120(self, cur: Any, *, caixa_date: date, filial: str) -> list[dict[str, Any]]:
        if not filial:
            return []
        cur.execute("SELECT to_regclass(%s) AS rel", (f"{self.schema}.relatorio_031120_rows",))
        table_row = cur.fetchone()
        if not table_row or not table_row.get("rel"):
            return []
        cur.execute("SELECT to_regclass(%s) AS rel", (f"{self.schema}.dataset_state",))
        state_row = cur.fetchone()
        if not state_row or not state_row.get("rel"):
            return []

        dataset_name = f"relatorio_031120_op_{_normalize_filial(filial)}"
        cur.execute(
            sql.SQL(
                """
                SELECT r.payload
                FROM {}.relatorio_031120_rows r
                JOIN {}.dataset_state s
                  ON s.dataset_name = r.dataset_name
                 AND s.active_batch_id = r.batch_id
                WHERE r.dataset_name = %s
                  AND r.filial = %s
                ORDER BY r.row_number
                """
            ).format(sql.Identifier(self.schema), sql.Identifier(self.schema)),
            (dataset_name, _normalize_filial(filial)),
        )
        rows = [dict(row.get("payload") or {}) for row in cur.fetchall()]
        return _build_rotas_dia_031120(rows, caixa_date=caixa_date)

    def _visible_filiais(self, allowed_filiais: set[str] | None) -> list[dict[str, str]]:
        items = self.filial_labels.items()
        if allowed_filiais is not None:
            items = [(code, name) for code, name in items if str(code) in allowed_filiais]
        return [{"code": str(code), "name": str(name)} for code, name in sorted(items, key=lambda item: int(item[0]) if str(item[0]).isdigit() else 999)]

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self._pool is None:
            self._pool = get_connection_pool(
                self.database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
            )
        with self._pool.connection() as conn:
            yield conn


def _build_caixa_pdf(payload: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="Caixa Financeiro",
    )
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "FinanceiroTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#1F2933"),
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "FinanceiroSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#4B5563"),
            spaceAfter=8,
        ),
        "section": ParagraphStyle(
            "FinanceiroSection",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#40566D"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "FinanceiroCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.6,
            leading=9.4,
            textColor=colors.HexColor("#1F2933"),
        ),
        "cell_bold": ParagraphStyle(
            "FinanceiroCellBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.6,
            leading=9.4,
            textColor=colors.HexColor("#1F2933"),
        ),
        "value": ParagraphStyle(
            "FinanceiroValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.6,
            leading=9.4,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#1F2933"),
        ),
        "center": ParagraphStyle(
            "FinanceiroCenter",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.6,
            leading=9.4,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1F2933"),
        ),
    }

    def p(value: Any, style: str = "cell") -> Paragraph:
        return Paragraph(escape(str(value if value not in (None, "") else "-")), styles[style])

    story: list[Any] = []
    maps = list(payload.get("maps") or [])
    caixa_maps = [item for item in maps if str(item.get("tipo_bloco") or "mapa") not in {"despesa", "vale"}]
    summary = dict(payload.get("summary") or {})
    filial_label = next(
        (
            f"{item.get('code')} - {item.get('name')}"
            for item in payload.get("filiais") or []
            if str(item.get("code") or "") == str(payload.get("filial") or "")
        ),
        str(payload.get("filial") or "-"),
    )
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    story.append(Paragraph("Caixa Financeiro", styles["title"]))
    story.append(Paragraph(f"Data: {_format_date_br(payload.get('data'))} | Revenda: {escape(filial_label)} | Gerado em: {generated_at}", styles["subtitle"]))
    story.append(Paragraph(f"Resumo - {escape(str(summary.get('status') or '-'))}", styles["section"]))
    story.append(_pdf_summary_table(summary))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Alimentacao por categoria", styles["section"]))
    story.append(_pdf_alimentacao_table(summary))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Numerario do Malote", styles["section"]))
    story.append(_pdf_denoms_table(caixa_maps))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Relatorio de Rotas do Dia - 031120", styles["section"]))
    story.append(_pdf_rotas_dia_table(list(payload.get("rotas_dia") or []), styles, p))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Lancamentos Consolidados", styles["section"]))
    story.append(_pdf_detail_table("Transferencias", _flatten_detail_rows(caixa_maps, "transferencias"), ["Mapa", "Motorista", "Data", "Banco", "NB", "NF", "Valor"], styles, p))
    story.append(Spacer(1, 2 * mm))
    story.append(_pdf_detail_table("Despesas", _flatten_detail_rows(maps, "despesas"), ["Mapa", "Motorista", "Despesa", "Obs.", "Valor"], styles, p))
    story.append(Spacer(1, 2 * mm))
    story.append(_pdf_detail_table("Vales", _flatten_detail_rows(maps, "vales"), ["Mapa", "Motorista", "Nome", "Obs.", "Valor", "Ass."], styles, p))

    story.append(PageBreak())
    story.append(Paragraph("Mapas do Dia", styles["title"]))
    if not maps:
        story.append(Paragraph("Nenhum mapa lancado para esta data e revenda.", styles["subtitle"]))
    for index, item in enumerate(maps, start=1):
        if index > 1:
            story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"Mapa {item.get('mapa') or '-'} - {item.get('motorista') or '-'}", styles["section"]))
        story.append(_pdf_map_table(item, styles, p))
        detail_blocks = (
            ("Transferencias parciais", "transferencias", ["Data", "Banco", "NB", "NF", "Valor"]),
            ("Despesas do mapa", "despesas", ["Despesa", "Obs.", "Valor"]),
            ("Vales do mapa", "vales", ["Nome", "Obs.", "Valor", "Ass."]),
            ("Diaristas", "diaristas", ["Nome", "Valor", "Recibo"]),
        )
        for title, key, headers in detail_blocks:
            rows = (item.get("vales_consolidados") if key == "vales" else item.get(key)) or []
            if rows:
                story.append(Spacer(1, 1.5 * mm))
                story.append(_pdf_map_detail_table(title, key, rows, headers, styles, p))

    doc.build(story, onFirstPage=_pdf_footer, onLaterPages=_pdf_footer)
    return buffer.getvalue()


def _pdf_table_style(*, header_rows: int = 1) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import TableStyle

    commands = [
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1F2933")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D3D7DD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header_rows > 0:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.HexColor("#E7E9ED")),
                ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
            ]
        )
    return TableStyle(commands)


def _pdf_summary_table(summary: dict[str, Any]) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT
    from xml.sax.saxutils import escape

    label_style = ParagraphStyle("PdfSummaryLabel", fontName="Helvetica-Bold", fontSize=7.4, leading=9, textColor=colors.HexColor("#1F2933"))
    value_style = ParagraphStyle("PdfSummaryValue", fontName="Helvetica", fontSize=7.4, leading=9, textColor=colors.HexColor("#1F2933"), alignment=TA_RIGHT)
    rows = [
        ("Dinheiro Promax", _fmt_money(summary.get("dinheiro_promax") or summary.get("total_promax"))),
        ("Numerario do Malote", _fmt_money(summary.get("numerario_total"))),
        ("Boletos rota", f"{_fmt_qty(summary.get('boletos_recebido_qtd'))} / {_fmt_qty(summary.get('boletos_rota'))}"),
        ("Despesas", _fmt_money(summary.get("despesas_total"))),
        ("Diaristas", _fmt_money(summary.get("diaristas_total"))),
        ("Alimentacao", _fmt_money(summary.get("alimentacao_total"))),
        ("Depositos", _fmt_money(summary.get("depositos_total"))),
        ("Vales", _fmt_money(summary.get("vales_total"))),
        ("Moedas", _fmt_money(summary.get("moedas"))),
        ("Diferenca", _fmt_money(summary.get("diferenca"))),
    ]
    data = [
        [Paragraph(escape(label), label_style), Paragraph(escape(value), value_style)]
        for label, value in rows
    ]
    table = Table(data, colWidths=[90 * mm, 90 * mm])
    table.setStyle(_pdf_table_style(header_rows=0))
    return table


def _pdf_alimentacao_table(summary: dict[str, Any]) -> Any:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT
    from xml.sax.saxutils import escape

    label_style = ParagraphStyle("PdfAlimentacaoLabel", fontName="Helvetica-Bold", fontSize=7.4, leading=9, textColor=colors.HexColor("#1F2933"))
    value_style = ParagraphStyle("PdfAlimentacaoValue", fontName="Helvetica", fontSize=7.4, leading=9, textColor=colors.HexColor("#1F2933"), alignment=TA_RIGHT)
    rows = [
        ("Hospedagem", _fmt_money(summary.get("alimentacao_hospedagem_total"))),
        ("Almoco", _fmt_money(summary.get("alimentacao_almoco_total"))),
        ("Janta", _fmt_money(summary.get("alimentacao_janta_total"))),
        ("Cafe", _fmt_money(summary.get("alimentacao_cafe_total"))),
        ("Total", _fmt_money(summary.get("alimentacao_total"))),
    ]
    data = [
        [Paragraph(escape(label), label_style), Paragraph(escape(value), value_style)]
        for label, value in rows
    ]
    table = Table(data, colWidths=[90 * mm, 90 * mm])
    table.setStyle(_pdf_table_style(header_rows=0))
    return table


def _pdf_denoms_table(maps: list[dict[str, Any]]) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT
    from xml.sax.saxutils import escape

    cell = ParagraphStyle("PdfDenomCell", fontName="Helvetica", fontSize=7.4, leading=9)
    value = ParagraphStyle("PdfDenomValue", fontName="Helvetica-Bold", fontSize=7.4, leading=9, alignment=TA_RIGHT)
    data = [[Paragraph("Cedula", cell), Paragraph("Quantidade", value), Paragraph("Total", value)]]
    for denom in DENOMINATIONS:
        qtd = sum(max(0, int(_decimal((item.get("dinheiro") or {}).get(denom)))) for item in maps)
        data.append([Paragraph(f"R$ {escape(denom)}", cell), Paragraph(str(qtd), value), Paragraph(_fmt_money(Decimal(denom) * Decimal(qtd)), value)])
    data.append([Paragraph("Moedas", cell), Paragraph("-", value), Paragraph(_fmt_money(sum(_decimal(item.get("moedas")) for item in maps)), value)])
    table = Table(data, colWidths=[50 * mm, 55 * mm, 75 * mm], repeatRows=1)
    table.setStyle(_pdf_table_style())
    return table


def _pdf_rotas_dia_table(rows: list[dict[str, Any]], styles: dict[str, Any], p: Any) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Table

    data = [[
        p("Mapa", "cell_bold"),
        p("Placa", "cell_bold"),
        p("Km", "cell_bold"),
        p("Km Prev.", "cell_bold"),
        p("Saida", "cell_bold"),
        p("Entrada", "cell_bold"),
        p("Tempo rota", "cell_bold"),
        p("TI Fisico", "cell_bold"),
        p("TI Financeiro", "cell_bold"),
        p("TI total", "cell_bold"),
        p("Validacao", "cell_bold"),
    ]]
    if not rows:
        data.append([p("Sem relatorio 031120 importado para esta data."), "", "", "", "", "", "", "", "", "", ""])
    for row in rows:
        data.append([
            p(row.get("mapa")),
            p(row.get("placa")),
            p(row.get("km_percorrido"), "value"),
            p(row.get("km_prev"), "value"),
            p(row.get("saida"), "center"),
            p(row.get("entrada"), "center"),
            p(row.get("tempo_rota"), "center"),
            p(row.get("ti_fisico"), "center"),
            p(row.get("ti_financeiro"), "center"),
            p(row.get("ti_total"), "center"),
            p(row.get("fechamento_status")),
        ])
    table = Table(
        data,
        colWidths=[13 * mm, 20 * mm, 13 * mm, 15 * mm, 18 * mm, 18 * mm, 20 * mm, 20 * mm, 22 * mm, 17 * mm, 24 * mm],
        repeatRows=1,
    )
    table.setStyle(_pdf_table_style())
    return table


def _pdf_detail_table(title: str, rows: list[dict[str, Any]], headers: list[str], styles: dict[str, Any], p: Any) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Table

    if not rows:
        rows = [{"empty": f"Sem {title.lower()} lancadas."}]
    if "Transferencias" in title:
        data = [[p(title, "cell_bold"), "", "", "", "", "", ""]]
        data.append([p(item, "cell_bold") for item in headers])
        for row in rows:
            if row.get("empty"):
                data.append([p(row["empty"]), "", "", "", "", "", ""])
            else:
                data.append([p(row.get("mapa")), p(row.get("motorista")), p(row.get("data")), p(row.get("banco")), p(row.get("nb")), p(row.get("nf")), p(_fmt_money(row.get("valor")), "value")])
        widths = [22 * mm, 34 * mm, 22 * mm, 25 * mm, 20 * mm, 20 * mm, 27 * mm]
    elif "Vales" in title:
        data = [[p(title, "cell_bold"), "", "", "", "", ""]]
        data.append([p(item, "cell_bold") for item in headers])
        for row in rows:
            if row.get("empty"):
                data.append([p(row["empty"]), "", "", "", "", ""])
            else:
                data.append([p(row.get("mapa")), p(row.get("motorista")), p(row.get("nome")), p(row.get("observacao")), p(_fmt_money(row.get("valor")), "value"), p("OK" if row.get("assinado") else "NOK", "center")])
        widths = [25 * mm, 35 * mm, 35 * mm, 50 * mm, 23 * mm, 12 * mm]
    else:
        data = [[p(title, "cell_bold"), "", "", "", ""]]
        data.append([p(item, "cell_bold") for item in headers])
        for row in rows:
            if row.get("empty"):
                data.append([p(row["empty"]), "", "", "", ""])
            else:
                data.append([p(row.get("mapa")), p(row.get("motorista")), p(row.get("nome")), p(row.get("observacao")), p(_fmt_money(row.get("valor")), "value")])
        widths = [25 * mm, 35 * mm, 45 * mm, 52 * mm, 23 * mm]
    table = Table(data, colWidths=widths, repeatRows=2)
    table.setStyle(_pdf_table_style(header_rows=2))
    return table


def _pdf_map_table(item: dict[str, Any], styles: dict[str, Any], p: Any) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Table

    boletos_text = f"{_fmt_qty(item.get('boletos_recebido_qtd'))} / {_fmt_qty(item.get('boletos_rota'))}"
    data = [
        [p("Identificacao", "cell_bold"), p("", "cell_bold"), p("", "cell_bold"), p("", "cell_bold")],
        [p("Numero do mapa"), p(item.get("mapa") or "-"), p("Motorista"), p(item.get("motorista") or "-")],
        [p("Placa"), p(item.get("placa") or "-"), p("Ajudante 1"), p(item.get("ajudante1") or "-")],
        [p("Ajudante 2"), p(item.get("ajudante2") or "-"), p("Tipo"), p(_tipo_bloco_label(item.get("tipo_bloco")))],
        [p("Boletos rota (qtd.)"), p(_fmt_qty(item.get("boletos_rota"))), p("Boletos que voltaram (qtd.)"), p(_fmt_qty(item.get("boletos_recebido_qtd")))],
        [p("Credito em conta"), p(_fmt_money(item.get("credito_conta")), "value"), p("Dinheiro Promax"), p(_fmt_money(item.get("dinheiro_promax")), "value")],
        [p("Total Apurado"), p(_fmt_money(item.get("total_apurado")), "value"), p("Diferenca"), p(_fmt_money(item.get("diferenca")), "value")],
        [p("Status"), p(item.get("status") or "-"), p("Conferencia boletos"), p(boletos_text)],
        [p("Dinheiro e alimentacao", "cell_bold"), p("", "cell_bold"), p("", "cell_bold"), p("", "cell_bold")],
        [p("R$ 200"), p(str(int(_decimal((item.get("dinheiro") or {}).get("200"))))), p("R$ 100"), p(str(int(_decimal((item.get("dinheiro") or {}).get("100")))))],
        [p("R$ 50"), p(str(int(_decimal((item.get("dinheiro") or {}).get("50"))))), p("R$ 20"), p(str(int(_decimal((item.get("dinheiro") or {}).get("20")))))],
        [p("R$ 10"), p(str(int(_decimal((item.get("dinheiro") or {}).get("10"))))), p("R$ 5"), p(str(int(_decimal((item.get("dinheiro") or {}).get("5")))))],
        [p("R$ 2"), p(str(int(_decimal((item.get("dinheiro") or {}).get("2"))))), p("Moedas"), p(_fmt_money(item.get("moedas")), "value")],
        [p("Hospedagem"), p(_fmt_money(item.get("alimentacao_hospedagem_total")), "value"), p("Janta"), p(_fmt_money(item.get("alimentacao_janta_total")), "value")],
        [p("Almoco"), p(_fmt_money(item.get("alimentacao_almoco_total")), "value"), p("Cafe"), p(_fmt_money(item.get("alimentacao_cafe_total")), "value")],
        [p("Diaristas"), p(_fmt_money(item.get("diaristas_total")), "value"), p("Vales"), p(_fmt_money(item.get("vales_total")), "value")],
        [p("Dinheiro contado"), p(_fmt_money(item.get("dinheiro_total")), "value"), p("Alimentacao"), p(_fmt_money(item.get("alimentacao_total")), "value")],
    ]
    if item.get("observacao"):
        data.append([p("Observacao"), p(item.get("observacao")), "", ""])
    table = Table(data, colWidths=[28 * mm, 62 * mm, 28 * mm, 62 * mm], repeatRows=1)
    table.setStyle(_pdf_table_style())
    return table


def _pdf_map_detail_table(title: str, key: str, rows: list[dict[str, Any]], headers: list[str], styles: dict[str, Any], p: Any) -> Any:
    from reportlab.lib.units import mm
    from reportlab.platypus import Table

    data = [[p(title, "cell_bold")] + [p("") for _ in headers[1:]], [p(item, "cell_bold") for item in headers]]
    for row in rows:
        if key == "transferencias":
            data.append([p(row.get("data")), p(row.get("banco")), p(row.get("nb")), p(row.get("nf")), p(_fmt_money(row.get("valor")), "value")])
        elif key == "vales":
            data.append([p(row.get("nome")), p(row.get("observacao")), p(_fmt_money(row.get("valor")), "value"), p("OK" if row.get("assinado") else "NOK", "center")])
        elif key == "diaristas":
            data.append([p(row.get("nome")), p(_fmt_money(row.get("valor")), "value"), p("OK" if row.get("recibo_recebido") else "NOK", "center")])
        else:
            data.append([p(row.get("nome")), p(row.get("observacao")), p(_fmt_money(row.get("valor")), "value")])
    widths_by_key = {
        "transferencias": [32 * mm, 43 * mm, 28 * mm, 28 * mm, 32 * mm],
        "vales": [55 * mm, 76 * mm, 32 * mm, 17 * mm],
        "diaristas": [75 * mm, 55 * mm, 25 * mm],
        "despesas": [60 * mm, 84 * mm, 32 * mm],
    }
    table = Table(data, colWidths=widths_by_key.get(key), repeatRows=2)
    table.setStyle(_pdf_table_style(header_rows=2))
    return table


def _flatten_detail_rows(maps: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in maps:
        details = item.get("vales_consolidados") if key == "vales" else item.get(key)
        for detail in details or []:
            merged = dict(detail)
            merged["mapa"] = item.get("mapa") or ""
            merged["motorista"] = item.get("motorista") or ""
            rows.append(merged)
    return rows


def _pdf_footer(canvas: Any, doc: Any) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#4B5563"))
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 6 * mm, f"Pagina {doc.page}")
    canvas.restoreState()


def _fmt_money(value: Any) -> str:
    number = _decimal(value).quantize(Decimal("0.01"))
    text = f"{number:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"


def _fmt_qty(value: Any) -> str:
    number = _decimal(value)
    if number == number.to_integral_value():
        return str(int(number))
    return f"{number:.2f}".replace(".", ",")


def _format_date_br(value: Any) -> str:
    try:
        parsed = _parse_date(value)
    except HTTPException:
        return str(value or "-")
    return parsed.strftime("%d/%m/%Y")


def _tipo_bloco_label(value: Any) -> str:
    tipo = str(value or "mapa").strip().lower()
    if tipo == "compra":
        return "Compra"
    if tipo == "despesa":
        return "Despesa"
    if tipo == "vale":
        return "Vale"
    return "Mapa"


def _build_rotas_dia_031120(rows: list[dict[str, Any]], *, caixa_date: date) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row_date = _parse_report_date(raw.get("Emissao")) or _parse_report_date(raw.get("DtOper"))
        if row_date != caixa_date:
            continue
        mapa = _strip_left_zeroes(raw.get("Mapa"))
        if not mapa:
            continue
        bucket = grouped.setdefault(
            mapa,
            {
                "mapa": mapa,
                "placa": "",
                "km_prev": Decimal("0"),
                "km_atual": Decimal("0"),
                "fase_kms": {},
                "fases": {},
            },
        )
        placa = str(raw.get("Placa") or "").strip()
        if placa and not bucket["placa"]:
            bucket["placa"] = placa
        km_prev = _decimal(raw.get("KmPrev"))
        km_atual = _decimal(raw.get("KmAtual"))
        if km_prev > 0 and bucket["km_prev"] == 0:
            bucket["km_prev"] = km_prev
        if km_atual > bucket["km_atual"]:
            bucket["km_atual"] = km_atual
        fase_key = _normalize_031120_fase(raw.get("Fase"))
        when = _parse_report_datetime(raw.get("DtOper"), raw.get("HrOper"))
        if fase_key and when:
            bucket["fases"][fase_key] = when
        if fase_key and km_atual > 0:
            bucket["fase_kms"][fase_key] = km_atual

    output: list[dict[str, Any]] = []
    for mapa, bucket in grouped.items():
        fases = bucket["fases"]
        fase_kms = bucket["fase_kms"]
        saida = fases.get("saida")
        entrada = fases.get("entrada")
        pc_fisica = fases.get("pc_fisica")
        pc_financeira = fases.get("pc_financeira")
        fechamento_status, fechamento_ok = _status_fechamento_031120(
            saida=saida,
            entrada=entrada,
            pc_fisica=pc_fisica,
            pc_financeira=pc_financeira,
        )
        km_prev = _decimal(bucket.get("km_prev"))
        km_atual = _decimal(bucket.get("km_atual"))
        km_carregado = _decimal(fase_kms.get("carregado"))
        km_pc_fisica = _decimal(fase_kms.get("pc_fisica"))
        if km_carregado > 0 and km_pc_fisica > 0:
            km_percorrido = abs(km_pc_fisica - km_carregado)
        else:
            km_percorrido = Decimal("0")
        output.append(
            {
                "mapa": mapa,
                "placa": bucket.get("placa") or "",
                "km_prev": _fmt_plain_qty(km_prev),
                "km_atual": _fmt_plain_qty(km_atual),
                "km_percorrido": _fmt_plain_qty(km_percorrido),
                "saida": _fmt_datetime_short(saida),
                "entrada": _fmt_datetime_short(entrada),
                "tempo_rota": _fmt_duration(_duration_minutes(saida, entrada)),
                "ti_fisico": _fmt_duration(_duration_minutes(entrada, pc_fisica)),
                "ti_financeiro": _fmt_duration(_duration_minutes(pc_fisica, pc_financeira)),
                "ti_total": _fmt_duration(_duration_minutes(entrada, pc_financeira)),
                "fechamento_status": fechamento_status,
                "fechamento_ok": fechamento_ok,
            }
        )
    return sorted(output, key=lambda item: int(item["mapa"]) if str(item.get("mapa") or "").isdigit() else 999999999)


def _normalize_031120_fase(value: Any) -> str:
    text = _text_key(value)
    if text == "CARREGADO":
        return "carregado"
    if "SAIDA" in text and ("CDD" in text or "FAB" in text):
        return "saida"
    if "ENTRADA" in text and ("CDD" in text or "FAB" in text):
        return "entrada"
    if "PC_FISICA" in text or "PC FISICA" in text:
        return "pc_fisica"
    if "PC_FINANCEIRA" in text or "PC FINANCEIRA" in text:
        return "pc_financeira"
    return ""


def _status_fechamento_031120(
    *,
    saida: datetime | None,
    entrada: datetime | None,
    pc_fisica: datetime | None,
    pc_financeira: datetime | None,
) -> tuple[str, bool]:
    if entrada and pc_fisica and pc_financeira:
        return "Fechado", True
    if entrada and not pc_fisica:
        return "Entrada sem fechamento fisico", False
    if entrada and pc_fisica and not pc_financeira:
        return "Entrada sem fechamento financeiro", False
    if saida and not entrada:
        return "Em rota / sem entrada", True
    return "Sem saida", True


def _parse_report_date(value: Any) -> date | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _parse_report_datetime(raw_date: Any, raw_time: Any) -> datetime | None:
    parsed_date = _parse_report_date(raw_date)
    if not parsed_date:
        return None
    time_text = str(raw_time or "").strip()
    if not time_text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            parsed_time = datetime.strptime(time_text, fmt).time()
            return datetime.combine(parsed_date, parsed_time)
        except ValueError:
            continue
    return None


def _duration_minutes(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    if end < start:
        end = end + timedelta(days=1)
    return max(0, int((end - start).total_seconds() // 60))


def _fmt_duration(minutes: int | None) -> str:
    if minutes is None:
        return ""
    hours, mins = divmod(int(minutes), 60)
    return f"{hours:02d}:{mins:02d}"


def _fmt_time(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else ""


def _fmt_datetime_short(value: datetime | None) -> str:
    return value.strftime("%d/%m/%Y %H:%M") if value else ""


def _fmt_plain_qty(value: Any) -> str:
    number = _decimal(value)
    if number == 0:
        return ""
    if number == number.to_integral_value():
        return str(int(number))
    return f"{number:.2f}".replace(".", ",")


def _fmt_km_integer(value: Any) -> str:
    number = _decimal(value)
    if number <= 0:
        return ""
    return str(int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def _strip_left_zeroes(value: Any) -> str:
    cleaned = str(value or "").strip()
    if cleaned.isdigit():
        return str(int(cleaned))
    return cleaned


def _relation_exists_cur(cur: Any, schema: str, relation: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS rel", (f"{schema}.{relation}",))
    row = cur.fetchone()
    return bool(row and row.get("rel"))


def _parse_date(value: Any) -> date:
    cleaned = str(value or "").strip()
    if not cleaned:
        return date.today()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Data invalida. Use YYYY-MM-DD ou DD/MM/AAAA.")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    cleaned = str(value if value is not None else "0").strip()
    if not cleaned:
        return Decimal("0")
    cleaned = cleaned.replace("R$", "").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value: Any) -> float:
    return float(_decimal(value).quantize(Decimal("0.01")))


def _bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return default
    return cleaned in {"1", "true", "sim", "s", "yes", "y", "on"}


def _sum_detail(rows: list[dict[str, Any]]) -> Decimal:
    return sum((_decimal(row.get("valor")) for row in rows), Decimal("0"))


def _is_vale_chapa(row: dict[str, Any]) -> bool:
    return str(row.get("observacao") or "").strip().lower() == "vale de chapa"


def _diarista_vale_rows(
    *,
    motorista: str,
    diarista: Decimal,
    diarista_recibo_recebido: bool,
    diaristas: list[dict[str, Any]],
    vales: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def has_existing_vale_chapa(nome: str, valor: Decimal) -> bool:
        clean_nome = str(nome or "").strip().lower()
        for vale in vales:
            if str(vale.get("nome") or "").strip().lower() != clean_nome:
                continue
            if _decimal(vale.get("valor")) == valor:
                return True
        return False

    def add_row(nome: str, valor: Decimal) -> None:
        if valor <= 0:
            return
        clean_nome = str(nome or "").strip() or motorista or "Diarista"
        if has_existing_vale_chapa(clean_nome, valor):
            return
        rows.append(
            {
                "nome": clean_nome,
                "valor": _money(valor),
                "observacao": "vale de chapa",
                "assinado": False,
                "origem": "diarista_sem_recibo",
            }
        )

    if diarista > 0 and not diarista_recibo_recebido:
        add_row(motorista, diarista)
    for item in diaristas:
        if _bool(item.get("recibo_recebido"), default=True):
            continue
        add_row(str(item.get("nome") or motorista or ""), _decimal(item.get("valor")))
    return rows


def _nested_get(source: Any, path: tuple[str, ...]) -> Any:
    current = source
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_dados_fechamento_03030702(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    candidates = (
        ("metadata", "dados_fechamento_03030702"),
        ("metadata", "resultado_financeiro", "metadata", "dados_fechamento_03030702"),
        ("resultado_financeiro", "metadata", "dados_fechamento_03030702"),
        ("dados_fechamento_03030702",),
        ("result", "metadata", "dados_fechamento_03030702"),
    )
    for path in candidates:
        value = _nested_get(source, path)
        if isinstance(value, dict) and value:
            return value
    metadata = source.get("metadata")
    if isinstance(metadata, dict):
        return _extract_dados_fechamento_03030702(metadata)
    return {}


def _extract_dados_030322(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    candidates = (
        ("metadata", "dados_030322"),
        ("dados_030322",),
        ("resultado_030322", "dados_030322"),
        ("resultado_030322", "metadata", "dados_030322"),
        ("result", "metadata", "dados_030322"),
        ("metadata", "resultado_030322", "dados_030322"),
        ("metadata", "resultado_030322", "metadata", "dados_030322"),
        ("metadata", "prestacao_contas"),
        ("prestacao_contas",),
    )
    for path in candidates:
        value = _nested_get(source, path)
        if isinstance(value, dict) and value:
            return value
    metadata = source.get("metadata")
    if isinstance(metadata, dict) and metadata is not source:
        return _extract_dados_030322(metadata)
    return {}


def _prestacao_030322_summary(payload: dict[str, Any]) -> dict[str, Any]:
    resumo = payload.get("resumo") if isinstance(payload.get("resumo"), dict) else {}
    notas = payload.get("notas") if isinstance(payload.get("notas"), list) else []
    vasilhames = payload.get("vasilhames") if isinstance(payload.get("vasilhames"), list) else []
    devolucoes = [
        item for item in notas
        if str((item or {}).get("situacao") or "").strip().upper() == "DEV"
        or _decimal((item or {}).get("valor_devolucao")) != 0
    ]
    return {
        "notas_count": int(resumo.get("notas") or len(notas)),
        "devolucoes_count": int(resumo.get("devolucoes") or len(devolucoes)),
        "vasilhames_count": int(resumo.get("vasilhames") or len(vasilhames)),
        "valor_notas": _decimal(resumo.get("valor_notas")),
        "valor_devolucao": _decimal(resumo.get("valor_devolucao")),
        "valor_liquido": _decimal(resumo.get("valor_liquido")),
    }


def _extract_motorista_030303(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    candidates = (
        ("metadata", "resultado_030303", "dados_030303", "motorista", "nome"),
        ("metadata", "resultado_030303", "metadata", "dados_030303", "motorista", "nome"),
        ("resultado_030303", "dados_030303", "motorista", "nome"),
        ("resultado_030303", "metadata", "dados_030303", "motorista", "nome"),
        ("dados_030303", "motorista", "nome"),
        ("result", "metadata", "resultado_030303", "dados_030303", "motorista", "nome"),
    )
    for path in candidates:
        value = _nested_get(source, path)
        text = _clean_identity_text(value)
        if text:
            return text
    metadata = source.get("metadata")
    if isinstance(metadata, dict) and metadata is not source:
        return _extract_motorista_030303(metadata)
    return ""


def _extract_030303_fields(source: Any) -> dict[str, str]:
    dados = _extract_dados_030303(source)
    motorista = _extract_motorista_030303(source)
    if not motorista:
        motorista = _clean_identity_text(_field_030303_value(dados, "motorista"))
    if not motorista:
        motorista = _clean_identity_text(_field_030303_value(dados, "csMotorista"))
    if not motorista:
        motorista = _clean_identity_text(_field_030303_value(dados, "cdMotorista"))
    return {
        "motorista": motorista,
        "placa": _clean_030303_select_text(_field_030303_value(dados, "placa"), keep_code=True),
        "ajudante1": _clean_030303_select_text(_field_030303_value(dados, "ajudante1")),
        "ajudante2": _clean_030303_select_text(_field_030303_value(dados, "ajudante2")),
    }


def _extract_dados_030303(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    candidates = (
        ("metadata", "resultado_030303", "dados_030303"),
        ("metadata", "resultado_030303", "metadata", "dados_030303"),
        ("resultado_030303", "dados_030303"),
        ("resultado_030303", "metadata", "dados_030303"),
        ("dados_030303",),
        ("result", "metadata", "resultado_030303", "dados_030303"),
    )
    for path in candidates:
        value = _nested_get(source, path)
        if isinstance(value, dict) and value:
            return value
    metadata = source.get("metadata")
    if isinstance(metadata, dict) and metadata is not source:
        return _extract_dados_030303(metadata)
    return {}


def _field_030303_value(dados: dict[str, Any], field_name: str) -> Any:
    if not isinstance(dados, dict):
        return ""
    target = _text_key(field_name)
    target_compact = target.replace(" ", "")
    campos = dados.get("campos")
    if isinstance(campos, list):
        for campo in campos:
            if not isinstance(campo, dict):
                continue
            keys = (_text_key(campo.get("name")), _text_key(campo.get("id")), _text_key(campo.get("label")))
            if any(key == target or key.replace(" ", "") == target_compact for key in keys):
                return campo.get("value")
    return dados.get(field_name) or ""


def _clean_030303_select_text(value: Any, *, keep_code: bool = False) -> str:
    return _clean_identity_text(value, keep_code=keep_code)


def _clean_identity_text(value: Any, *, keep_code: bool = False) -> str:
    if isinstance(value, dict):
        text = str(value.get("texto") or value.get("label") or value.get("value") or "").strip()
        raw_code = str(value.get("valor") or "").strip()
        if raw_code in {"", "00000"} and _text_key(text) in {"--SELECIONAR--", "SELECIONAR"}:
            return ""
    else:
        text = str(value or "").strip()
    if not text or _text_key(text) in {"--SELECIONAR--", "SELECIONAR", "00000"}:
        return ""
    if keep_code:
        return text
    if " - " in text:
        text = text.split(" - ", 1)[1]
    text = text.replace("(*)", "").strip()
    if _is_blank_identity_text(text):
        return ""
    return text


def _is_blank_identity_text(value: Any) -> bool:
    text = _text_key(value)
    if not text:
        return True
    return text in {
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
        current = _clean_identity_text(merged.get(key), keep_code=(key == "placa"))
        candidate = _clean_identity_text((fallback or {}).get(key), keep_code=(key == "placa"))
        merged[key] = current or candidate
    return merged


def _sql_blankish_field(schema: str, table: str, column: str) -> sql.SQL:
    field = sql.SQL("{}.{}.{}").format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(column))
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


def _financeiro_metrics_from_fechamento(dados: dict[str, Any]) -> dict[str, Decimal]:
    metrics = {
        "boletos_rota": Decimal("0"),
        "total_promax": Decimal("0"),
        "credito_conta": Decimal("0"),
        "dinheiro_promax": Decimal("0"),
    }
    if not isinstance(dados, dict) or not dados:
        return metrics

    saida = dados.get("saida")
    if isinstance(saida, dict):
        itens = saida.get("itens")
        if isinstance(itens, list):
            for item in itens:
                if not isinstance(item, dict):
                    continue
                descricao = _text_key(item.get("descricao"))
                valor = abs(_decimal(item.get("valor")))
                if any(term in descricao for term in ("BOLETO", "BLOQUETO")):
                    metrics["boletos_rota"] += _decimal(item.get("qtNfs"))
                if any(term in descricao for term in ("TRANSFERENCIA", "CREDITO", "CREDITO EM CONTA", "PIX")):
                    metrics["credito_conta"] += valor
                if any(term in descricao for term in ("A VISTA", "AVISTA", "DINHEIRO")):
                    metrics["dinheiro_promax"] += valor
        metrics["total_promax"] = metrics["dinheiro_promax"]

    if metrics["total_promax"] == 0:
        retorno = dados.get("retorno")
        if isinstance(retorno, dict):
            itens = retorno.get("itens")
            if isinstance(itens, list):
                for item in itens:
                    if not isinstance(item, dict):
                        continue
                    descricao = _text_key(item.get("descricao"))
                    if any(term in descricao for term in ("TRANSFERENCIA", "CREDITO", "CREDITO EM CONTA", "PIX")):
                        metrics["credito_conta"] += abs(_decimal(item.get("valor")))
                    if any(term in descricao for term in ("A VISTA", "AVISTA", "DINHEIRO")):
                        metrics["dinheiro_promax"] += abs(_decimal(item.get("valor")))
            metrics["total_promax"] = metrics["dinheiro_promax"]
    return metrics


def _text_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    replacements = {
        "Á": "A",
        "À": "A",
        "Â": "A",
        "Ã": "A",
        "É": "E",
        "Ê": "E",
        "Í": "I",
        "Ó": "O",
        "Ô": "O",
        "Õ": "O",
        "Ú": "U",
        "Ç": "C",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _normalize_dinheiro(value: dict[str, Any]) -> dict[str, int]:
    output: dict[str, int] = {}
    for denom in DENOMINATIONS:
        try:
            output[denom] = max(int(str((value or {}).get(denom) or "0").strip() or "0"), 0)
        except ValueError:
            output[denom] = 0
    return output


def _normalize_financeiro_dirty_fields(value: Any) -> set[str]:
    supported = {
        "tipo_bloco",
        "mapa",
        "mapa_ref",
        "motorista",
        "placa",
        "ajudante1",
        "ajudante2",
        "boletos_rota",
        "boletos_recebido_qtd",
        "total_promax",
        "credito_conta",
        "dinheiro_promax",
        "dinheiro",
        "moedas",
        "diarista",
        "diarista_recibo_recebido",
        "pernoite",
        "hospedagem",
        "janta",
        "almoco",
        "cafe",
        "observacao",
    }
    return {
        item for item in (str(raw or "").strip() for raw in (value or []))
        if item in supported
    }


def _financeiro_manual_update_flags(dirty_fields: set[str]) -> dict[str, bool]:
    return {
        field: field in dirty_fields
        for field in (
            "motorista",
            "placa",
            "ajudante1",
            "ajudante2",
            "boletos_rota",
            "boletos_recebido_qtd",
            "total_promax",
            "credito_conta",
            "dinheiro_promax",
            "dinheiro",
            "moedas",
            "diarista",
            "diarista_recibo_recebido",
            "pernoite",
            "hospedagem",
            "janta",
            "almoco",
            "cafe",
            "observacao",
        )
    }


def _normalize_filial(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if cleaned.isdigit():
        return str(int(cleaned))
    return cleaned


def _normalize_tipo_bloco(value: Any) -> str:
    cleaned = str(value or "mapa").strip().lower()
    if cleaned in {"compra", "despesa", "vale"}:
        return cleaned
    return "mapa"


def _allowed_filiais(context: dict[str, Any] | None) -> set[str] | None:
    if not context or bool(context.get("is_admin")):
        return None
    raw = [str(item).strip() for item in context.get("filiais", ()) if str(item).strip()]
    if not raw or "*" in raw:
        return None
    return {_normalize_filial(item) for item in raw}


def _clean_identifier(value: str, fallback: str) -> str:
    cleaned = "".join(ch for ch in str(value or "").strip() if ch.isalnum() or ch == "_")
    return cleaned or fallback
