"""Compras e devoluções por cliente a partir da 03.02.37 com itens.

A 03.02.37 da Liga Entrega já fica gravada linha a linha em
``liga_entrega_raw_rows``. Cada exportação é um acumulado do mês de emissão,
reenviado várias vezes. Este serviço resume essas linhas por cliente em
tabelas próprias, para a ficha do cliente nunca ler linhas cruas nem
recalcular o histórico a cada abertura.

Regra de deduplicação (decidida em 23/11/2026):
- para cada (filial, mês de emissão) vale só o arquivo mais recente que tem
  linhas daquele mês; os anteriores são versões menores do mesmo acumulado;
- nenhuma linha é cortada dentro do arquivo escolhido: o mesmo produto em duas
  linhas da nota é venda real (preços diferentes, bonificação);
- a compra conta no mês da Dt. Operacao; status A e E são entrega, D é
  devolução e C (cancelada) fica de fora.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

import psycopg
from psycopg import sql

from bot_api.services.liga_entrega_motivos import MOTIVOS_DEVOLUCAO
from bot_api.services.liga_entrega_raw_sql_import_service import _payload_historico

ROTINA = "030237"
# 03.02.37 no padrão do giro: um CSV mensal por filial ("01-2026 Sumé.csv"), mandado
# pelo worker. Fica em tabela própria e entra na mesma regra de deduplicação.
TABELA_GIRO = "raw_030237_giro"
STATUS_ENTREGUE = ("A", "E")
STATUS_DEVOLVIDO = "D"
MESES_MEDIA = 3
DIAS_DEVOLUCAO = 90
TOP_PRODUTOS = 5


@dataclass(frozen=True)
class Mes:
    competencia: str
    total: float
    qtde: float
    notas: int


def mes_anterior(competencia: str, passos: int = 1) -> str:
    ano, mes = (int(parte) for parte in competencia.split("-"))
    indice = ano * 12 + (mes - 1) - passos
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}"


def meses_fechados(hoje: date, quantidade: int = MESES_MEDIA) -> list[str]:
    atual = f"{hoje.year:04d}-{hoje.month:02d}"
    return [mes_anterior(atual, passo) for passo in range(quantidade, 0, -1)]


def media_mensal(totais: dict[str, float], fechados: list[str], meses_com_base: set[str]) -> float | None:
    """Soma dos meses fechados ÷ quantidade de meses; mês sem compra vale zero.

    Devolve None quando algum desses meses nem foi importado: contar como zero
    um mês fora da base subestimaria o cliente.
    """
    if any(mes not in meses_com_base for mes in fechados):
        return None
    return round(sum(totais.get(mes, 0.0) for mes in fechados) / len(fechados), 2)


def _texto_num(expr: str) -> str:
    """Número do payload: '21.600,00' e '12.420' (milhar com ponto) viram numeric."""
    return (
        f"(CASE WHEN jsonb_typeof(payload->'{expr}') = 'number' THEN (payload->>'{expr}')::numeric"
        f" WHEN trim(payload->>'{expr}') ~ '^-?[0-9.]+(,[0-9]+)?$'"
        f" THEN replace(replace(trim(payload->>'{expr}'), '.', ''), ',', '.')::numeric ELSE 0 END)"
    )


def _texto_data(expr: str) -> str:
    return (
        f"(CASE WHEN trim(payload->>'{expr}') ~ '^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
        f" THEN substring(trim(payload->>'{expr}') from 1 for 10)::date"
        f" WHEN trim(payload->>'{expr}') ~ '^[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]$'"
        f" THEN to_date(trim(payload->>'{expr}'), 'DD/MM/YYYY') END)"
    )


def _texto_codigo(expr: str) -> str:
    return f"COALESCE(NULLIF(ltrim(trim(payload->>'{expr}'), '0'), ''), '0')"


class Compras030237Service:
    def __init__(self, database_url: str, schema: str = "reports", *, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "")
        self.schema = str(schema or "reports")
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3), 1.0)
        self._schema_ready = False

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=int(self.connect_timeout_seconds))

    def _t(self, nome: str) -> sql.Composed:
        return sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier(nome))

    # ------------------------------------------------------------------ schema
    def ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        if self._schema_ready:
            return
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    filial VARCHAR(10) NOT NULL,
                    mes_emissao VARCHAR(7) NOT NULL,
                    source_key TEXT NOT NULL,
                    imported_at TIMESTAMPTZ,
                    linhas INTEGER NOT NULL DEFAULT 0,
                    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (filial, mes_emissao)
                )
                """
            ).format(self._t("compras_030237_cargas")))
            cur.execute(sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    filial VARCHAR(10) NOT NULL,
                    mes_emissao VARCHAR(7) NOT NULL,
                    cliente VARCHAR(20) NOT NULL,
                    competencia VARCHAR(7) NOT NULL,
                    total NUMERIC(16, 2) NOT NULL DEFAULT 0,
                    qtde NUMERIC(16, 3) NOT NULL DEFAULT 0,
                    notas INTEGER NOT NULL DEFAULT 0,
                    ultima_entrega DATE,
                    PRIMARY KEY (filial, mes_emissao, cliente, competencia)
                )
                """
            ).format(self._t("compras_030237_mes")))
            cur.execute(sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    filial VARCHAR(10) NOT NULL,
                    mes_emissao VARCHAR(7) NOT NULL,
                    cliente VARCHAR(20) NOT NULL,
                    competencia VARCHAR(7) NOT NULL,
                    produto VARCHAR(30) NOT NULL,
                    descricao TEXT NOT NULL DEFAULT '',
                    unidade VARCHAR(10) NOT NULL DEFAULT '',
                    total NUMERIC(16, 2) NOT NULL DEFAULT 0,
                    qtde NUMERIC(16, 3) NOT NULL DEFAULT 0,
                    PRIMARY KEY (filial, mes_emissao, cliente, competencia, produto)
                )
                """
            ).format(self._t("compras_030237_produto")))
            cur.execute(sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    filial VARCHAR(10) NOT NULL,
                    mes_emissao VARCHAR(7) NOT NULL,
                    cliente VARCHAR(20) NOT NULL,
                    nota VARCHAR(20) NOT NULL,
                    serie VARCHAR(10) NOT NULL DEFAULT '',
                    data DATE,
                    nf_referencia VARCHAR(20) NOT NULL DEFAULT '',
                    motivo_codigo VARCHAR(10) NOT NULL DEFAULT '',
                    itens INTEGER NOT NULL DEFAULT 0,
                    qtde NUMERIC(16, 3) NOT NULL DEFAULT 0,
                    total NUMERIC(16, 2) NOT NULL DEFAULT 0,
                    PRIMARY KEY (filial, mes_emissao, cliente, nota, serie)
                )
                """
            ).format(self._t("devolucoes_030237")))
            cur.execute(sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    source_key TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    row_number INTEGER NOT NULL,
                    mes_emissao VARCHAR(7),
                    payload JSONB NOT NULL,
                    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (source_key, row_number)
                )
                """
            ).format(self._t(TABELA_GIRO)))
            cur.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (mes_emissao)").format(
                sql.Identifier(f"{TABELA_GIRO}_mes_idx"), self._t(TABELA_GIRO)
            ))
            # Filial gravada na linha: a reconstrução escolhe a versão de cada (filial, mês)
            # só pelo índice, sem abrir o payload das versões antigas do acumulado.
            cur.execute(sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS filial VARCHAR(10)").format(self._t(TABELA_GIRO)))
            cur.execute(sql.SQL(f"UPDATE {{}} SET filial = {_texto_codigo('Filial')} WHERE filial IS NULL").format(self._t(TABELA_GIRO)))
            cur.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (filial, mes_emissao, source_key, imported_at)").format(
                sql.Identifier(f"{TABELA_GIRO}_versao_idx"), self._t(TABELA_GIRO)
            ))
            # Última compra do produto no mês (mix de cerveja da ficha). Linhas antigas ficam
            # sem a data até a próxima reconstrução do mês.
            cur.execute(sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS ultima_data DATE").format(self._t("compras_030237_produto")))
            for tabela in ("compras_030237_mes", "compras_030237_produto", "devolucoes_030237"):
                cur.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (filial, cliente)").format(
                    sql.Identifier(f"{tabela}_cliente_idx"), self._t(tabela)
                ))
        conn.commit()
        self._schema_ready = True

    # ------------------------------------------------------- importação giro
    def importar_arquivos_giro(self, arquivos: Mapping[str, bytes]) -> dict[str, Any]:
        """Grava os CSVs da 030237 Giro e refaz o resumo dos meses que eles trazem.

        O mesmo arquivo reenviado (mesmo conteúdo) é ignorado; uma versão nova do
        acumulado do mês entra como outra origem e passa a valer por ser a mais recente.
        """
        if not self.database_url:
            raise RuntimeError("Banco de relatórios não configurado.")
        arquivos_novos = linhas_total = 0
        meses: set[str] = set()
        filiais: set[str] = set()
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor() as cur:
                for nome, conteudo in arquivos.items():
                    source_key = f"giro|{hashlib.sha256(conteudo).hexdigest()}"
                    # Mesmo arquivo chegando junto pelo painel e pelo worker: um espera o outro.
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (source_key,))
                    cur.execute(sql.SQL("SELECT 1 FROM {} WHERE source_key = %s LIMIT 1").format(self._t(TABELA_GIRO)), (source_key,))
                    if cur.fetchone():
                        continue
                    linhas = ler_csv_030237(conteudo)
                    if not linhas:
                        raise ValueError(f"{nome}: nenhuma linha da 03.02.37 encontrada.")
                    if "Produto" not in linhas[0]:
                        raise ValueError(f"{nome}: a 03.02.37 precisa vir com itens (coluna Produto).")
                    registros = linhas_para_gravar(source_key, nome, linhas)
                    meses.update(r[3] for r in registros if r[3])
                    filiais.update(r[4] for r in registros)
                    with cur.copy(sql.SQL(
                        "COPY {} (source_key, filename, row_number, mes_emissao, filial, payload) FROM STDIN"
                    ).format(self._t(TABELA_GIRO))) as copia:
                        for registro in registros:
                            copia.write_row(registro)
                    arquivos_novos += 1
                    linhas_total += len(linhas)
            conn.commit()
        resumo = (
            self.rebuild(desde_mes=min(meses), ate_mes=max(meses), filiais=sorted(filiais))
            if meses else {"ok": True}
        )
        return {
            "arquivos": arquivos_novos, "ignorados": len(arquivos) - arquivos_novos, "rows": linhas_total,
            "meses": sorted(meses), "filiais": sorted(filiais), "resumo": resumo,
        }

    # ------------------------------------------------------------- reconstrução
    def rebuild(
        self, *, desde_mes: str | None = None, ate_mes: str | None = None, filiais: list[str] | None = None
    ) -> dict[str, Any]:
        """Refaz o resumo dos meses de emissão entre ``desde_mes`` e ``ate_mes`` (None = sem limite).

        ``filiais`` limita às filiais informadas (None = todas): a importação de um
        arquivo só refaz a filial dele.

        Roda numa transação só: quem lê a ficha durante a carga vê o resumo
        anterior inteiro, nunca meio apagado.
        """
        if not self.database_url:
            return {"ok": False, "motivo": "sem banco configurado"}
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor() as cur:
                for comando, params in self.comandos_rebuild(desde_mes, ate_mes, filiais):
                    cur.execute(comando, params)
                cur.execute(sql.SQL("SELECT count(*), COALESCE(sum(linhas), 0) FROM {} WHERE ").format(
                    self._t("compras_030237_cargas")
                ) + _FILTRO_MES + sql.SQL(" AND ") + _FILTRO_FILIAL, _params_filtro(desde_mes, ate_mes, filiais))
                cargas, linhas = cur.fetchone() or (0, 0)
            conn.commit()
        return {
            "ok": True, "desde_mes": desde_mes or "", "ate_mes": ate_mes or "", "filiais": list(filiais or []),
            "meses_filial": int(cargas or 0), "linhas": int(linhas or 0),
        }

    def comandos_rebuild(
        self, desde_mes: str | None, ate_mes: str | None = None, filiais: list[str] | None = None
    ) -> list[tuple[sql.Composable, tuple[Any, ...]]]:
        raw = self._t("liga_entrega_raw_rows")
        giro = self._t(TABELA_GIRO)
        # A competência da linha crua é o mês da Dt. Operacao; uma linha emitida
        # em M pode ter operação em M-1 (ex.: 31/10 emitida em 03/11).
        competencia_minima = mes_anterior(desde_mes) if desde_mes else None
        filtro = _params_filtro(desde_mes, ate_mes, filiais)
        apagar = [
            (sql.SQL("DELETE FROM {} WHERE ").format(self._t(tabela)) + _FILTRO_MES + sql.SQL(" AND ") + _FILTRO_FILIAL, filtro)
            for tabela in ("compras_030237_mes", "compras_030237_produto", "devolucoes_030237", "compras_030237_cargas")
        ]
        temporarias = sql.SQL(
            """
            CREATE TEMP TABLE IF NOT EXISTS compras_030237_versoes (
                filial TEXT, mes_emissao TEXT, source_key TEXT, imported_at TIMESTAMPTZ, origem TEXT
            ) ON COMMIT DROP;
            CREATE TEMP TABLE IF NOT EXISTS compras_030237_linhas (
                source_key TEXT, imported_at TIMESTAMPTZ, filial TEXT, mes_emissao TEXT, cliente TEXT,
                status TEXT, data_operacao DATE, nota TEXT, serie TEXT, produto TEXT, descricao TEXT,
                unidade TEXT, qtde NUMERIC, total NUMERIC, nf_referencia TEXT, motivo_codigo TEXT
            ) ON COMMIT DROP
            """
        )
        limpar = sql.SQL("TRUNCATE compras_030237_versoes, compras_030237_linhas")
        liga_filial = sql.SQL(_texto_codigo("Filial"))
        liga_mes = sql.SQL(f"to_char({_texto_data('Emissao')}, 'YYYY-MM')")
        liga_competencia = sql.SQL(
            "routine = %s AND payload ? 'Produto' AND (%s::text IS NULL OR competencia >= %s) AND (%s::text IS NULL OR competencia <= %s)"
        )
        params_liga = (ROTINA, competencia_minima, competencia_minima, ate_mes, ate_mes)
        # 1) Qual arquivo vale para cada (filial, mês): o importado por último. No giro
        #    isso sai do índice (filial, mes_emissao, source_key, imported_at).
        versoes = sql.SQL(
            """
            INSERT INTO compras_030237_versoes
            SELECT DISTINCT ON (filial, mes_emissao) filial, mes_emissao, source_key, imported_at, origem
            FROM (
                SELECT filial, mes_emissao, source_key, max(imported_at) AS imported_at, 'giro' AS origem
                FROM {giro}
                WHERE mes_emissao IS NOT NULL AND {filtro_mes} AND {filtro_filial}
                GROUP BY filial, mes_emissao, source_key
                UNION ALL
                SELECT filial, mes_emissao, source_key, max(imported_at), 'liga'
                FROM (
                    SELECT source_key, imported_at, {liga_filial} AS filial, {liga_mes} AS mes_emissao
                    FROM {raw} WHERE {liga_competencia}
                ) liga
                WHERE mes_emissao IS NOT NULL AND {filtro_mes} AND {filtro_filial}
                GROUP BY filial, mes_emissao, source_key
            ) todas
            ORDER BY filial, mes_emissao, imported_at DESC, source_key DESC
            """
        ).format(
            giro=giro, raw=raw, filtro_mes=_FILTRO_MES, filtro_filial=_FILTRO_FILIAL,
            liga_filial=liga_filial, liga_mes=liga_mes, liga_competencia=liga_competencia,
        )
        params_versoes = (*filtro, *params_liga, *filtro)
        # 2) Só as linhas dos arquivos escolhidos entram na conta.
        linhas = sql.SQL(
            f"""
            WITH base AS (
                SELECT source_key, imported_at,
                       {_texto_codigo('Filial')} AS filial,
                       to_char({_texto_data('Emissao')}, 'YYYY-MM') AS mes_emissao,
                       {_texto_codigo('Cliente')} AS cliente,
                       upper(trim(COALESCE(payload->>'Status', ''))) AS status,
                       {_texto_data('Dt. Operacao')} AS data_operacao,
                       {_texto_codigo('Nota')} AS nota,
                       trim(COALESCE(payload->>'Serie', '')) AS serie,
                       {_texto_codigo('Produto')} AS produto,
                       trim(COALESCE(payload->>'Descricao', '')) AS descricao,
                       lower(trim(COALESCE(payload->>'Unidade', ''))) AS unidade,
                       {_texto_num('Qtde')} AS qtde,
                       {_texto_num('Total')} AS total,
                       COALESCE(NULLIF(ltrim(trim(COALESCE(payload->>'NF Referencia', '')), '0'), ''), '') AS nf_referencia,
                       trim(COALESCE(payload->>'Mot. Cancelamento', '')) AS motivo_codigo
                FROM (
                    SELECT g.source_key, g.imported_at, g.payload
                    FROM {{giro}} g
                    JOIN compras_030237_versoes v
                      ON v.origem = 'giro' AND v.source_key = g.source_key
                     AND v.filial = g.filial AND v.mes_emissao = g.mes_emissao
                    UNION ALL
                    SELECT r.source_key, r.imported_at, r.payload
                    FROM {{raw}} r
                    WHERE r.source_key IN (SELECT source_key FROM compras_030237_versoes WHERE origem = 'liga')
                      AND {{liga_competencia}}
                ) origem
            )
            INSERT INTO compras_030237_linhas
            SELECT b.source_key, b.imported_at, b.filial, b.mes_emissao, b.cliente, b.status, b.data_operacao,
                   b.nota, b.serie, b.produto, b.descricao, b.unidade, b.qtde, b.total, b.nf_referencia, b.motivo_codigo
            FROM base b
            JOIN compras_030237_versoes e USING (filial, mes_emissao, source_key)
            WHERE b.data_operacao IS NOT NULL AND b.cliente <> '0'
            """
        ).format(giro=giro, raw=raw, liga_competencia=liga_competencia)
        params_linhas = params_liga
        cargas = sql.SQL(
            """
            INSERT INTO {} (filial, mes_emissao, source_key, imported_at, linhas)
            SELECT filial, mes_emissao, min(source_key), max(imported_at), count(*)
            FROM compras_030237_linhas GROUP BY filial, mes_emissao
            """
        ).format(self._t("compras_030237_cargas"))
        por_mes = sql.SQL(
            """
            INSERT INTO {} (filial, mes_emissao, cliente, competencia, total, qtde, notas, ultima_entrega)
            SELECT filial, mes_emissao, cliente, to_char(data_operacao, 'YYYY-MM'),
                   sum(total), sum(qtde), count(DISTINCT nota || '|' || serie), max(data_operacao)
            FROM compras_030237_linhas
            WHERE status IN ('A', 'E')
            GROUP BY filial, mes_emissao, cliente, to_char(data_operacao, 'YYYY-MM')
            """
        ).format(self._t("compras_030237_mes"))
        por_produto = sql.SQL(
            """
            INSERT INTO {} (filial, mes_emissao, cliente, competencia, produto, descricao, unidade, total, qtde, ultima_data)
            SELECT filial, mes_emissao, cliente, to_char(data_operacao, 'YYYY-MM'), produto,
                   max(descricao), max(unidade), sum(total), sum(qtde), max(data_operacao)
            FROM compras_030237_linhas
            WHERE status IN ('A', 'E') AND produto <> '0'
            GROUP BY filial, mes_emissao, cliente, to_char(data_operacao, 'YYYY-MM'), produto
            """
        ).format(self._t("compras_030237_produto"))
        devolucoes = sql.SQL(
            """
            INSERT INTO {} (filial, mes_emissao, cliente, nota, serie, data, nf_referencia, motivo_codigo, itens, qtde, total)
            SELECT filial, mes_emissao, cliente, nota, serie, max(data_operacao), max(nf_referencia),
                   max(motivo_codigo), count(*), sum(qtde), sum(total)
            FROM compras_030237_linhas
            WHERE status = 'D'
            GROUP BY filial, mes_emissao, cliente, nota, serie
            """
        ).format(self._t("devolucoes_030237"))
        return [
            *apagar, (temporarias, ()), (limpar, ()), (versoes, params_versoes), (linhas, params_linhas),
            (cargas, ()), (por_mes, ()), (por_produto, ()), (devolucoes, ()),
        ]

    # ----------------------------------------------------------------- leitura
    def resumo_cliente(self, filial: str, cliente: str, *, hoje: date) -> dict[str, Any]:
        filial_n, cliente_n = _codigo(filial), _codigo(cliente)
        atual = f"{hoje.year:04d}-{hoje.month:02d}"
        fechados = meses_fechados(hoje)
        janela = [*fechados, atual]
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(sql.SQL(
                    "SELECT mes_emissao, max(atualizado_em) FROM {} WHERE filial = %s GROUP BY mes_emissao"
                ).format(self._t("compras_030237_cargas")), (filial_n,))
                cargas = cur.fetchall()
                cur.execute(sql.SQL(
                    """
                    SELECT competencia, sum(total), sum(qtde), sum(notas), max(ultima_entrega)
                    FROM {} WHERE filial = %s AND cliente = %s AND competencia = ANY(%s)
                    GROUP BY competencia
                    """
                ).format(self._t("compras_030237_mes")), (filial_n, cliente_n, janela))
                meses = cur.fetchall()
                cur.execute(sql.SQL(
                    "SELECT max(ultima_entrega) FROM {} WHERE filial = %s AND cliente = %s"
                ).format(self._t("compras_030237_mes")), (filial_n, cliente_n))
                ultima = (cur.fetchone() or (None,))[0]
                cur.execute(sql.SQL(
                    """
                    SELECT produto, max(descricao), max(unidade), sum(total), sum(qtde)
                    FROM {} WHERE filial = %s AND cliente = %s AND competencia = ANY(%s)
                    GROUP BY produto
                    """
                ).format(self._t("compras_030237_produto")), (filial_n, cliente_n, janela))
                produtos = cur.fetchall()
        return montar_resumo(
            atual=atual, fechados=fechados, cargas=cargas, meses=meses, ultima_entrega=ultima, produtos=produtos
        )

    def devolucoes_cliente(self, filial: str, cliente: str, *, desde: date) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(sql.SQL(
                    """
                    SELECT data, nota, serie, nf_referencia, motivo_codigo, itens, qtde, total
                    FROM {} WHERE filial = %s AND cliente = %s AND data >= %s
                    ORDER BY data DESC, nota DESC
                    """
                ).format(self._t("devolucoes_030237")), (_codigo(filial), _codigo(cliente), desde))
                linhas = cur.fetchall()
        return [devolucao_payload(linha) for linha in linhas]

    def notas_cliente(self, filial: str, cliente: str) -> list[dict[str, Any]]:
        """Notas entregues dos arquivos ativos por filial/mês, sem duplicar versões."""
        filial_n, cliente_n = _codigo(filial), _codigo(cliente)
        query = sql.SQL(f"""
            WITH linhas AS (
                SELECT g.payload FROM {{giro}} g
                JOIN {{cargas}} c ON c.source_key = g.source_key
                  AND c.filial = g.filial AND c.mes_emissao = g.mes_emissao
                WHERE c.filial = %s AND {_texto_codigo('Cliente')} = %s
                UNION ALL
                SELECT r.payload FROM {{raw}} r
                JOIN {{cargas}} c ON c.source_key = r.source_key
                  AND c.filial = {_texto_codigo('Filial')}
                  AND c.mes_emissao = to_char({_texto_data('Emissao')}, 'YYYY-MM')
                WHERE c.filial = %s AND r.routine = %s AND {_texto_codigo('Cliente')} = %s
            ), notas AS (
                SELECT {_texto_data('Dt. Operacao')} AS data,
                       {_texto_codigo('Nota')} AS nota,
                       trim(COALESCE(payload->>'Serie', '')) AS serie,
                       {_texto_codigo('Produto')} AS produto,
                       trim(COALESCE(payload->>'Descricao', '')) AS descricao,
                       trim(COALESCE(payload->>'Unidade', '')) AS unidade,
                       {_texto_num('Qtde')} AS qtde, {_texto_num('Total')} AS total
                FROM linhas WHERE upper(trim(COALESCE(payload->>'Status', ''))) IN ('A', 'E')
            )
            SELECT data, nota, serie, count(*), sum(qtde), sum(total),
                   jsonb_agg(jsonb_build_object('produto', produto, 'descricao', descricao,
                       'unidade', unidade, 'qtde', qtde, 'total', total)
                       ORDER BY produto, descricao)
            FROM notas WHERE data IS NOT NULL AND nota <> '0'
            GROUP BY data, nota, serie ORDER BY data DESC, nota DESC, serie
        """).format(giro=self._t(TABELA_GIRO), cargas=self._t("compras_030237_cargas"), raw=self._t("liga_entrega_raw_rows"))
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(query, (filial_n, cliente_n, filial_n, ROTINA, cliente_n))
                linhas = cur.fetchall()
        return [{"data": d.isoformat(), "nota": str(n), "serie": str(s or ""),
                 "itens": int(i), "qtde": float(q or 0), "total": float(t or 0), "produtos": produtos}
                for d, n, s, i, q, t, produtos in linhas]

    def atualizado_em(self, filial: str) -> Any:
        with self._connect() as conn:
            self.ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT max(atualizado_em) FROM {} WHERE filial = %s").format(
                    self._t("compras_030237_cargas")
                ), (_codigo(filial),))
                return (cur.fetchone() or (None,))[0]


def montar_resumo(
    *,
    atual: str,
    fechados: list[str],
    cargas: list[tuple[Any, ...]],
    meses: list[tuple[Any, ...]],
    ultima_entrega: Any,
    produtos: list[tuple[Any, ...]],
) -> dict[str, Any]:
    meses_com_base = {str(linha[0]) for linha in cargas}
    atualizado = max((linha[1] for linha in cargas if linha[1] is not None), default=None)
    por_mes = {
        str(linha[0]): Mes(str(linha[0]), float(linha[1] or 0), float(linha[2] or 0), int(linha[3] or 0))
        for linha in meses
    }
    totais = {mes: item.total for mes, item in por_mes.items()}
    media = media_mensal(totais, fechados, meses_com_base)
    media_semanal = None
    if media is not None and fechados:
        inicio = date.fromisoformat(f"{fechados[0]}-01")
        fim = date.fromisoformat(f"{atual}-01")
        dias = (fim - inicio).days
        if dias > 0:
            media_semanal = round(sum(totais.get(mes, 0.0) for mes in fechados) * 7 / dias, 2)
    base_desde = min(meses_com_base) if meses_com_base else ""
    serie = [
        {
            "competencia": mes,
            "total": round(por_mes[mes].total, 2) if mes in por_mes else 0.0,
            "qtde": round(por_mes[mes].qtde, 3) if mes in por_mes else 0.0,
            "notas": por_mes[mes].notas if mes in por_mes else 0,
            "com_base": mes in meses_com_base,
            "atual": mes == atual,
        }
        for mes in [*fechados, atual]
    ]
    itens = [
        {"produto": str(p[0]), "descricao": str(p[1] or ""), "unidade": str(p[2] or ""), "total": round(float(p[3] or 0), 2), "qtde": round(float(p[4] or 0), 3)}
        for p in produtos
    ]
    fechados_serie = [item for item in serie if not item["atual"]]
    return {
        "mes_atual": serie[-1],
        "meses_fechados": fechados_serie,
        "media_3_meses": media,
        "media_semanal": media_semanal,
        "base_desde": base_desde,
        "historico_suficiente": media is not None,
        "qtde_3_meses": round(sum(item["qtde"] for item in fechados_serie), 3),
        "notas_3_meses": sum(item["notas"] for item in fechados_serie),
        "ultima_entrega": ultima_entrega.isoformat() if hasattr(ultima_entrega, "isoformat") else (str(ultima_entrega) if ultima_entrega else ""),
        "top_faturamento": sorted(itens, key=lambda item: (-item["total"], item["produto"]))[:TOP_PRODUTOS],
        "top_quantidade": sorted(itens, key=lambda item: (-item["qtde"], item["produto"]))[:TOP_PRODUTOS],
        "serie": serie,
        "atualizado_em": atualizado.isoformat() if hasattr(atualizado, "isoformat") else "",
    }


def devolucao_payload(linha: tuple[Any, ...]) -> dict[str, Any]:
    data, nota, serie, nf_ref, motivo_codigo, itens, qtde, total = linha
    codigo = str(motivo_codigo or "").strip().lstrip("0") or ""
    motivo = MOTIVOS_DEVOLUCAO.get(codigo, {})
    return {
        "data": data.isoformat() if hasattr(data, "isoformat") else str(data or ""),
        "nota": str(nota or ""),
        "serie": str(serie or ""),
        "nf_referencia": str(nf_ref or ""),
        "motivo_codigo": codigo,
        "motivo": motivo.get("motivo") or ("Motivo não informado" if not codigo else f"Motivo {codigo}"),
        "responsabilidade": motivo.get("responsabilidade") or "",
        "itens": int(itens or 0),
        "qtde": round(float(qtde or 0), 3),
        "total": round(float(total or 0), 2),
    }


def _codigo(valor: Any) -> str:
    return str(valor or "").strip().lstrip("0") or "0"


def ler_csv_030237(conteudo: bytes) -> list[dict[str, Any]]:
    """Lê o CSV do Promax (cp1252, ";") e guarda só as colunas do histórico."""
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("cp1252", errors="replace")
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cabecalho = next(leitor, None)
    if not cabecalho:
        return []
    nomes = [re.sub(r"\s+", " ", str(h or "").strip()) or f"coluna_{i}" for i, h in enumerate(cabecalho, start=1)]
    linhas = []
    for valores in leitor:
        if not any(str(v or "").strip() for v in valores):
            continue
        bruto = {nome: str(valor).strip() for nome, valor in zip(nomes, valores)}
        linhas.append(_payload_historico(ROTINA, bruto))
    return linhas


_FILTRO_MES = sql.SQL("(%s::text IS NULL OR mes_emissao >= %s) AND (%s::text IS NULL OR mes_emissao <= %s)")
_FILTRO_FILIAL = sql.SQL("(%s::text[] IS NULL OR filial = ANY(%s::text[]))")


def _params_filtro(desde_mes: str | None, ate_mes: str | None, filiais: list[str] | None) -> tuple[Any, ...]:
    lista = [_codigo(f) for f in filiais] if filiais else None
    return (desde_mes, desde_mes, ate_mes, ate_mes, lista, lista)


def linhas_para_gravar(source_key: str, nome: str, linhas: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Registros do COPY: (source_key, arquivo, nº da linha, mês de emissão, filial, payload)."""
    return [
        (source_key, nome, i, _mes_da_data(linha.get("Emissao")) or None, _codigo(linha.get("Filial")), _json(linha))
        for i, linha in enumerate(linhas, start=1)
    ]


def _mes_da_data(valor: Any) -> str:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", str(valor or "").strip())
    return f"{m.group(3)}-{m.group(2)}" if m else ""


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"))
