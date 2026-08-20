from __future__ import annotations

import io
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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
                            boletos_rota NUMERIC(14,2) NOT NULL DEFAULT 0,
                            boletos_recebido_qtd NUMERIC(14,2) NOT NULL DEFAULT 0,
                            total_promax NUMERIC(14,2) NOT NULL DEFAULT 0,
                            credito_conta NUMERIC(14,2) NOT NULL DEFAULT 0,
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

        records = [self._serialize_map(row, details) for row in mapas]
        return {
            "data": caixa_date.isoformat(),
            "filial": requested_filial,
            "filiais": self._visible_filiais(allowed_filiais),
            "maps": records,
            "summary": self._build_summary(records),
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
        username = str((context or {}).get("username") or (context or {}).get("mode") or "")
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                diarista = _decimal(payload.get("diarista"))
                diarista_recibo_recebido = _bool(payload.get("diarista_recibo_recebido"), default=True)
                motorista = str(payload.get("motorista") or "").strip()
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.financeiro_caixa_mapas (
                            caixa_date, filial, tipo_bloco, mapa, mapa_ref, motorista, boletos_rota,
                            boletos_recebido_qtd, total_promax, credito_conta, dinheiro,
                            moedas, diarista, diarista_recibo_recebido, pernoite, hospedagem, janta, almoco, cafe,
                            pagamentos, observacao, created_by, updated_by
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (caixa_date, filial, mapa) DO UPDATE SET
                            tipo_bloco = EXCLUDED.tipo_bloco,
                            mapa_ref = EXCLUDED.mapa_ref,
                            motorista = EXCLUDED.motorista,
                            boletos_rota = EXCLUDED.boletos_rota,
                            boletos_recebido_qtd = EXCLUDED.boletos_recebido_qtd,
                            total_promax = EXCLUDED.total_promax,
                            credito_conta = EXCLUDED.credito_conta,
                            dinheiro = EXCLUDED.dinheiro,
                            moedas = EXCLUDED.moedas,
                            diarista = EXCLUDED.diarista,
                            diarista_recibo_recebido = EXCLUDED.diarista_recibo_recebido,
                            pernoite = EXCLUDED.pernoite,
                            hospedagem = EXCLUDED.hospedagem,
                            janta = EXCLUDED.janta,
                            almoco = EXCLUDED.almoco,
                            cafe = EXCLUDED.cafe,
                            pagamentos = EXCLUDED.pagamentos,
                            observacao = EXCLUDED.observacao,
                            updated_by = EXCLUDED.updated_by,
                            updated_at = NOW()
                        RETURNING *
                        """
                    ).format(sql.Identifier(self.schema)),
                    (
                        caixa_date,
                        filial,
                        tipo_bloco,
                        mapa,
                        mapa_ref,
                        motorista,
                        _decimal(payload.get("boletos_rota")),
                        _decimal(payload.get("boletos_recebido_qtd")),
                        _decimal(payload.get("total_promax")),
                        _decimal(payload.get("credito_conta")),
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
        motorista_promax = _extract_motorista_030303(result_payload)
        metrics = _financeiro_metrics_from_fechamento(dados_fechamento)
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
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {}.financeiro_caixa_mapas (
                            caixa_date, filial, tipo_bloco, mapa, mapa_ref, motorista,
                            boletos_rota, total_promax, credito_conta, observacao,
                            created_by, updated_by
                        )
                        VALUES (%s, %s, 'mapa', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (caixa_date, filial, mapa) DO UPDATE SET
                            tipo_bloco = 'mapa',
                            mapa_ref = EXCLUDED.mapa_ref,
                            motorista = CASE
                                WHEN {}.financeiro_caixa_mapas.motorista = '' THEN EXCLUDED.motorista
                                ELSE {}.financeiro_caixa_mapas.motorista
                            END,
                            boletos_rota = EXCLUDED.boletos_rota,
                            total_promax = EXCLUDED.total_promax,
                            credito_conta = EXCLUDED.credito_conta,
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
                        metrics["boletos_rota"],
                        metrics["total_promax"],
                        metrics["credito_conta"],
                        "\n".join(obs_parts),
                        username,
                        username,
                        "Mapa criado/atualizado automaticamente pelo fechamento Promax.%",
                    ),
                )
                row = dict(cur.fetchone() or {})
                mapa_id = int(row["id"])
                details = self._load_details(cur, [mapa_id])
            conn.commit()
        return {
            "ok": True,
            "map": self._serialize_map(row, details),
            "metrics": {
                "boletos_rota": _money(metrics["boletos_rota"]),
                "total_promax": _money(metrics["total_promax"]),
                "credito_conta": _money(metrics["credito_conta"]),
            },
            "dados_fechamento_found": bool(dados_fechamento),
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

    def export_caixa_pdf(self, *, data: str, filial: str = "", context: dict[str, Any] | None = None) -> tuple[bytes, str]:
        payload = self.list_caixa(data=data, filial=filial, context=context)
        if not str(payload.get("filial") or "").strip():
            raise HTTPException(status_code=400, detail="Escolha uma revenda para exportar o caixa.")
        pdf_bytes = _build_caixa_pdf(payload)
        safe_date = str(payload.get("data") or date.today().isoformat()).replace("/", "-")
        safe_filial = str(payload.get("filial") or "revenda").strip() or "revenda"
        return pdf_bytes, f"caixa-financeiro-{safe_filial}-{safe_date}.pdf"

    def _load_details(self, cur: Any, ids: list[int]) -> dict[str, dict[int, list[dict[str, Any]]]]:
        output = {key: {item: [] for item in ids} for key in ("transferencias", "despesas", "vales", "diaristas")}
        if not ids:
            return output
        for key in output:
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
        dinheiro_total = sum(Decimal(denom) * Decimal(qtd) for denom, qtd in dinheiro.items())
        transferencias_total = _sum_detail(details["transferencias"].get(mapa_id, []))
        despesas_total = _sum_detail(details["despesas"].get(mapa_id, []))
        vales_total = _sum_detail([row for row in details["vales"].get(mapa_id, []) if not _is_vale_chapa(row)])
        diaristas_total = _decimal(row.get("diarista")) + _sum_detail(details["diaristas"].get(mapa_id, []))
        alimentacao_total = (
            _decimal(row.get("pernoite"))
            + _decimal(row.get("hospedagem"))
            + _decimal(row.get("janta"))
            + _decimal(row.get("almoco"))
            + _decimal(row.get("cafe"))
        )
        boletos_rota = _decimal(row.get("boletos_rota"))
        boletos_recebido_qtd = _decimal(row.get("boletos_recebido_qtd"))
        boletos_diferenca_qtd = boletos_rota - boletos_recebido_qtd
        total_apurado = dinheiro_total + _decimal(row.get("moedas")) + transferencias_total + despesas_total + vales_total + diaristas_total + alimentacao_total
        total_promax = _decimal(row.get("total_promax"))
        diferenca = total_promax - total_apurado
        tipo_bloco = _normalize_tipo_bloco(row.get("tipo_bloco"))
        mapa_key = str(row.get("mapa") or "")
        mapa_ref = str(row.get("mapa_ref") or "") or mapa_key
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
            "boletos_rota": _money(boletos_rota),
            "boletos_recebido_qtd": _money(boletos_recebido_qtd),
            "boletos_diferenca_qtd": _money(boletos_diferenca_qtd),
            "total_promax": _money(total_promax),
            "credito_conta": _money(row.get("credito_conta")),
            "dinheiro": dinheiro,
            "dinheiro_total": _money(dinheiro_total),
            "moedas": _money(row.get("moedas")),
            "diarista": _money(row.get("diarista")),
            "diarista_recibo_recebido": _bool(row.get("diarista_recibo_recebido"), default=True),
            "pernoite": _money(row.get("pernoite")),
            "hospedagem": _money(row.get("hospedagem")),
            "janta": _money(row.get("janta")),
            "almoco": _money(row.get("almoco")),
            "cafe": _money(row.get("cafe")),
            "transferencias": details["transferencias"].get(mapa_id, []),
            "despesas": details["despesas"].get(mapa_id, []),
            "vales": details["vales"].get(mapa_id, []),
            "diaristas": details["diaristas"].get(mapa_id, []),
            "transferencias_total": _money(transferencias_total),
            "despesas_total": _money(despesas_total),
            "vales_total": _money(vales_total),
            "diaristas_total": _money(diaristas_total),
            "alimentacao_pernoite_total": _money(row.get("pernoite")),
            "alimentacao_hospedagem_total": _money(row.get("hospedagem")),
            "alimentacao_janta_total": _money(row.get("janta")),
            "alimentacao_almoco_total": _money(row.get("almoco")),
            "alimentacao_cafe_total": _money(row.get("cafe")),
            "alimentacao_total": _money(alimentacao_total),
            "total_apurado": _money(total_apurado),
            "diferenca": _money(diferenca),
            "status": "LANCAMENTO" if tipo_bloco in {"despesa", "vale"} else ("OK" if abs(diferenca) < Decimal("0.01") else "DIVERGENTE"),
            "observacao": str(row.get("observacao") or ""),
            "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else str(row.get("updated_at") or ""),
        }

    def _build_summary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        keys = (
            "total_promax",
            "boletos_rota",
            "boletos_recebido_qtd",
            "boletos_diferenca_qtd",
            "dinheiro_total",
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
    story.append(_pdf_summary_table(summary))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Numerario do Malote", styles["section"]))
    story.append(_pdf_denoms_table(caixa_maps))
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
            ("Transferencias", "transferencias", ["Data", "Banco", "NB", "NF", "Valor"]),
            ("Despesas", "despesas", ["Despesa", "Obs.", "Valor"]),
            ("Vales", "vales", ["Nome", "Obs.", "Valor", "Ass."]),
            ("Diaristas", "diaristas", ["Nome", "Valor", "Recibo"]),
        )
        for title, key, headers in detail_blocks:
            rows = item.get(key) or []
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
        ("Total Promax", _fmt_money(summary.get("total_promax"))),
        ("Total Apurado", _fmt_money(summary.get("total_apurado"))),
        ("Diferenca", _fmt_money(summary.get("diferenca"))),
        ("Numerario", _fmt_money(_decimal(summary.get("dinheiro_total")) + _decimal(summary.get("moedas")))),
        ("Credito em conta", _fmt_money(summary.get("credito_conta"))),
        ("Transferencias", _fmt_money(summary.get("transferencias_total"))),
        ("Boletos rota", f"{_fmt_qty(summary.get('boletos_recebido_qtd'))} / {_fmt_qty(summary.get('boletos_rota'))}"),
        ("Despesas", _fmt_money(summary.get("despesas_total"))),
        ("Diaristas", _fmt_money(summary.get("diaristas_total"))),
        ("Alimentacao", _fmt_money(summary.get("alimentacao_total"))),
        ("Vales", _fmt_money(summary.get("vales_total"))),
        ("Status", str(summary.get("status") or "-")),
    ]
    data = []
    for idx in range(0, len(rows), 3):
        row = rows[idx : idx + 3]
        data.append([Paragraph(escape(label), label_style) for label, _value in row] + [Paragraph("", label_style)] * (3 - len(row)))
        data.append([Paragraph(escape(value), value_style) for _label, value in row] + [Paragraph("", value_style)] * (3 - len(row)))
    table = Table(data, colWidths=[60 * mm, 60 * mm, 60 * mm])
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

    data = [
        [p("Campo", "cell_bold"), p("Valor", "cell_bold"), p("Campo", "cell_bold"), p("Valor", "cell_bold")],
        [p("Tipo"), p(_tipo_bloco_label(item.get("tipo_bloco"))), p("Status"), p(item.get("status"))],
        [p("Total Promax"), p(_fmt_money(item.get("total_promax")), "value"), p("Total Apurado"), p(_fmt_money(item.get("total_apurado")), "value")],
        [p("Diferenca"), p(_fmt_money(item.get("diferenca")), "value"), p("Credito em conta"), p(_fmt_money(item.get("credito_conta")), "value")],
        [p("Boletos rota"), p(f"{_fmt_qty(item.get('boletos_recebido_qtd'))} / {_fmt_qty(item.get('boletos_rota'))}"), p("Dinheiro"), p(_fmt_money(item.get("dinheiro_total")), "value")],
        [p("Moedas"), p(_fmt_money(item.get("moedas")), "value"), p("Diaristas"), p(_fmt_money(item.get("diaristas_total")), "value")],
        [p("Alimentacao"), p(_fmt_money(item.get("alimentacao_total")), "value"), p("Hospedagem"), p(_fmt_money(item.get("alimentacao_hospedagem_total")), "value")],
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
        for detail in item.get(key) or []:
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
        text = str(value or "").strip()
        if text:
            return text
    metadata = source.get("metadata")
    if isinstance(metadata, dict) and metadata is not source:
        return _extract_motorista_030303(metadata)
    return ""


def _financeiro_metrics_from_fechamento(dados: dict[str, Any]) -> dict[str, Decimal]:
    metrics = {
        "boletos_rota": Decimal("0"),
        "total_promax": Decimal("0"),
        "credito_conta": Decimal("0"),
    }
    if not isinstance(dados, dict) or not dados:
        return metrics

    saida = dados.get("saida")
    if isinstance(saida, dict):
        metrics["total_promax"] = abs(_decimal(saida.get("total")))
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

    if metrics["total_promax"] == 0:
        retorno = dados.get("retorno")
        if isinstance(retorno, dict):
            metrics["total_promax"] = abs(_decimal(retorno.get("totalRetorno")))
            itens = retorno.get("itens")
            if isinstance(itens, list):
                for item in itens:
                    if not isinstance(item, dict):
                        continue
                    descricao = _text_key(item.get("descricao"))
                    if any(term in descricao for term in ("TRANSFERENCIA", "CREDITO", "CREDITO EM CONTA", "PIX")):
                        metrics["credito_conta"] += abs(_decimal(item.get("valor")))
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
