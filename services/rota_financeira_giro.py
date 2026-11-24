"""Filtros "sem giro" da Rota Financeira: quem não comprou o suficiente no mês.

Mesma regra da ficha do cliente, feita em SQL para a rota inteira de uma vez:

- Vasilhame (``giro_vasilhame_service``): por tipo de garrafeira, comprar no mês
  ``MULTIPLICADOR``× as caixas em comodato.
- Equipamento (``giro_equipamentos_service``): por SOPI/Visa em comodato, comprar no
  mês o valor da meta na cesta do equipamento.

Os CTEs entram depois de ``route`` e usam só os clientes da rota.
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from bot_api.services.comodatos_query_service import _saldo_to_numeric_sql
from bot_api.services.giro_equipamentos_service import REGRAS
from bot_api.services.giro_vasilhame_service import MULTIPLICADOR, _chave

SITUACOES_GIRO = ("sem_giro_vasilhame", "sem_giro_equipamento")

FILTRO_GIRO = {
    "sem_giro_vasilhame": "EXISTS (SELECT 1 FROM vasilhame_falta g WHERE g.filial = f.filial AND g.cod_pdv = f.cod_pdv)",
    "sem_giro_equipamento": "EXISTS (SELECT 1 FROM equipamento_falta g WHERE g.filial = f.filial AND g.cod_pdv = f.cod_pdv)",
}

# Tipo da garrafeira pelo "Sub-Tipo Material" da 02.02.20 (igual a tipo_da_garrafeira);
# sem sub-tipo, pela descrição na tabela de garrafeiras.
_TIPO_CAIXA = """
    CASE
        WHEN btrim(COALESCE(c.sub_tipo_material, '')) = '' THEN d.tipo
        WHEN upper(c.sub_tipo_material) NOT LIKE '%%GARRAFEIRA%%' THEN NULL
        WHEN upper(c.sub_tipo_material) LIKE '%%LITRAO%%' OR upper(c.sub_tipo_material) LIKE '%%LITRÃO%%' THEN 'litrao'
        WHEN c.sub_tipo_material LIKE '%%1/2%%' THEN 'litrinho'
        WHEN c.sub_tipo_material LIKE '%%1/1%%' THEN 'inteira'
    END
"""


def ctes_giro(schema: str, competencia: str, catalogo: dict[str, dict[str, str]]) -> tuple[sql.Composable, list[Any]]:
    """CTEs ``vasilhame_falta`` e ``equipamento_falta`` (filial, cod_pdv) e os parâmetros deles."""
    codigos = list(catalogo)
    tipos_codigo = [catalogo[codigo]["tipo"] for codigo in codigos]
    chaves = [_chave(item["descricao"]) for item in catalogo.values()]
    tipos_chave = [item["tipo"] for item in catalogo.values()]
    soma_equipamentos = sql.SQL(", ").join(
        sql.SQL("COALESCE(SUM(GREATEST(trunc(saldo), 0)) FILTER (WHERE sub_tipo = {}), 0) AS {}").format(
            sql.Literal(regra.sub_tipo), sql.Identifier(regra.tipo)
        )
        for regra in REGRAS
    )
    soma_cestas = sql.SQL(", ").join(
        sql.SQL("COALESCE(SUM(p.total) FILTER (WHERE c.nome_cesta = {}), 0) AS {}").format(
            sql.Literal(regra.cesta), sql.Identifier(f"compra_{regra.tipo}")
        )
        for regra in REGRAS
    )
    falta_equipamento = sql.SQL(" OR ").join(
        sql.SQL("(e.{tipo} > 0 AND COALESCE(v.{compra}, 0) < e.{tipo} * {meta})").format(
            tipo=sql.Identifier(regra.tipo), compra=sql.Identifier(f"compra_{regra.tipo}"), meta=sql.Literal(regra.meta_por_equipamento)
        )
        for regra in REGRAS
    )
    ctes = sql.SQL(
        """,
        comodato_rota AS MATERIALIZED (
            SELECT c.unb AS filial, c.cliente AS cod_pdv,
                   upper(btrim(COALESCE(c.sub_tipo_material, ''))) AS sub_tipo,
                   """ + _TIPO_CAIXA + """ AS tipo_caixa,
                   {saldo} AS saldo
            FROM {schema}.comodatos_latest c
            JOIN route r ON r.filial = c.unb AND r.cod_pdv = c.cliente
            LEFT JOIN unnest(%s::text[], %s::text[]) AS d(chave, tipo)
              ON d.chave = regexp_replace(upper(COALESCE(c.material, '')), '[^A-Z0-9]', '', 'g')
        ),
        compras_rota AS MATERIALIZED (
            SELECT r.filial, r.cod_pdv, p.produto, p.qtde, p.total
            FROM {schema}.compras_030237_produto p
            JOIN route r ON p.filial = (COALESCE(NULLIF(ltrim(r.filial, '0'), ''), '0'))
                        AND p.cliente = (COALESCE(NULLIF(ltrim(r.cod_pdv, '0'), ''), '0'))
            WHERE p.competencia = %s
        ),
        caixas_rota AS (
            SELECT filial, cod_pdv, tipo_caixa AS tipo, SUM(saldo) AS caixas
            FROM comodato_rota WHERE tipo_caixa IS NOT NULL
            GROUP BY filial, cod_pdv, tipo_caixa
        ),
        caixas_compradas AS (
            SELECT p.filial, p.cod_pdv, g.tipo, SUM(p.qtde) AS qtde
            FROM compras_rota p
            JOIN {schema}.dprodutos_latest dp ON ltrim(dp.codigo, '0') = p.produto
            JOIN unnest(%s::text[], %s::text[]) AS g(codigo, tipo)
              ON g.codigo = NULLIF(ltrim(trim(COALESCE(dp.payload->>'Garrrafeira', dp.payload->>'Garrafeira', '')), '0'), '')
            GROUP BY p.filial, p.cod_pdv, g.tipo
        ),
        vasilhame_falta AS (
            SELECT DISTINCT k.filial, k.cod_pdv
            FROM caixas_rota k
            LEFT JOIN caixas_compradas q ON q.filial = k.filial AND q.cod_pdv = k.cod_pdv AND q.tipo = k.tipo
            WHERE k.caixas > 0 AND COALESCE(q.qtde, 0) < k.caixas * {multiplicador}
        ),
        equipamentos_rota AS (
            SELECT filial, cod_pdv, {soma_equipamentos}
            FROM comodato_rota GROUP BY filial, cod_pdv
        ),
        compras_cesta AS (
            SELECT p.filial, p.cod_pdv, {soma_cestas}
            FROM compras_rota p
            JOIN (SELECT DISTINCT codigo, nome_cesta FROM {schema}.produto_cestas_latest WHERE nome_cesta = ANY(%s)) c
              ON c.codigo = p.produto
            GROUP BY p.filial, p.cod_pdv
        ),
        equipamento_falta AS (
            SELECT e.filial, e.cod_pdv
            FROM equipamentos_rota e
            LEFT JOIN compras_cesta v ON v.filial = e.filial AND v.cod_pdv = e.cod_pdv
            WHERE {falta_equipamento}
        )
        """
    ).format(
        schema=sql.Identifier(schema),
        # Mesmo saldo da consulta de comodatos: o Promax manda negativo o que está com o cliente.
        saldo=_saldo_to_numeric_sql("c.saldo"),
        multiplicador=sql.Literal(MULTIPLICADOR),
        soma_equipamentos=soma_equipamentos,
        soma_cestas=soma_cestas,
        falta_equipamento=falta_equipamento,
    )
    params: list[Any] = [chaves, tipos_chave, competencia, codigos, tipos_codigo, [regra.cesta for regra in REGRAS]]
    return ctes, params

