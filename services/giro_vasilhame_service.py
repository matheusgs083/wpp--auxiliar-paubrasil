"""Giro de vasilhames do cliente: comprar no mês o dobro das caixas que tem em comodato.

Regra (definida em 23/11/2026): quem tem 10 caixas (garrafeiras) em comodato precisa
comprar 20 caixas no mês de produtos daquela garrafeira.

- Caixas que o cliente tem: comodatos da 02.02.20 cujas garrafeiras estão na tabela
  de garrafeiras (dgarrafeiras), separadas por tipo.
- Caixas compradas: 03.02.37 do mês atual (resumo por produto), e cada produto é
  ligado à garrafeira pela coluna "Garrrafeira" do dProdutos.
- Tipo da garrafeira: "Tp Material" da tabela de garrafeiras (1/2 = litrinho,
  1/1 = inteira, litrão); sem tipo, pelo tamanho na descrição.

Este giro é de vasilhame; o faturamento do cliente fica no bloco Compras.
"""

from __future__ import annotations

import re
import time
from typing import Any

import psycopg
from psycopg import sql

TIPOS = (("litrinho", "Cerveja 1/2 (litrinho)"), ("inteira", "Cerveja 1/1"), ("litrao", "Cerveja Litrão"))
MULTIPLICADOR = 2
CACHE_SEGUNDOS = 600


def tipo_da_garrafeira(descricao: Any, tipo_material: Any = "") -> str:
    """Litrinho, inteira ou litrão para garrafeiras (caixas); vazio para garrafa e o resto.

    A tabela de garrafeiras também traz as garrafas ("VASILHAME CERVEJA 1/2"); essas
    não são caixas e ficam de fora.
    """
    tipo = str(tipo_material or "").upper().strip()
    if tipo:
        if "GARRAFEIRA" not in tipo:
            return ""
        if "LITRAO" in tipo or "LITRÃO" in tipo:
            return "litrao"
        if "1/2" in tipo:
            return "litrinho"
        if "1/1" in tipo:
            return "inteira"
        return ""
    nome = str(descricao or "").upper()
    if not nome.startswith("GARRAF") or nome.startswith("GARRAFA "):
        return ""
    texto = re.sub(r"\s+", "", nome).replace("O", "0")
    if re.search(r"(1L|1,1L|965ML|1000ML|LITRA0)", texto):
        return "litrao"
    if re.search(r"(600ML|620ML|630ML)", texto):
        return "inteira"
    if re.search(r"(300ML|30\dML|LITRINH0|LITR300|LIT300)", texto):
        return "litrinho"
    return ""


def _chave(descricao: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(descricao or "").upper())


class GiroVasilhameService:
    def __init__(self, database_url: str, schema: str = "reports", *, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "")
        self.schema = str(schema or "reports")
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3), 1.0)
        self._catalogo: tuple[float, dict[str, dict[str, str]]] | None = None

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=int(self.connect_timeout_seconds))

    def _view_garrafeiras(self, cur: Any) -> sql.Composable:
        # A tabela de garrafeiras (0109) é a fonte; sem ela, a de materiais tem as mesmas colunas.
        for view in ("dgarrafeiras_latest", "dmateriais_latest"):
            cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.{view}",))
            linha = cur.fetchone()
            if linha and linha[0]:
                return sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier(view))
        raise RuntimeError("Tabela de garrafeiras não importada.")

    def catalogo(self) -> dict[str, dict[str, str]]:
        """Garrafeiras por código: descrição e tipo (litrinho/inteira/litrão)."""
        agora = time.monotonic()
        if self._catalogo and agora - self._catalogo[0] < CACHE_SEGUNDOS:
            return self._catalogo[1]
        with self._connect() as conn, conn.cursor() as cur:
            view = self._view_garrafeiras(cur)
            cur.execute(sql.SQL("SELECT codigo, descricao, tipo_material FROM {}").format(view))
            linhas = cur.fetchall()
        catalogo = {}
        for codigo, descricao, tipo_material in linhas:
            tipo = tipo_da_garrafeira(descricao, tipo_material)
            if tipo:
                catalogo[str(codigo or "").lstrip("0")] = {"descricao": str(descricao or "").strip(), "tipo": tipo}
        self._catalogo = (agora, catalogo)
        return catalogo

    def caixas_compradas(self, filial: str, cliente: str, competencia: str) -> dict[str, float]:
        """Caixas compradas no mês por tipo de garrafeira (produto → garrafeira pelo dProdutos)."""
        return self.caixas_compradas_meses(filial, cliente, [competencia])[competencia]

    def caixas_compradas_meses(self, filial: str, cliente: str, competencias: list[str]) -> dict[str, dict[str, float]]:
        """Caixas por tipo de garrafeira em cada competência pedida (mês sem compra vem zerado)."""
        catalogo = self.catalogo()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    WITH compras AS (
                        SELECT competencia, produto, sum(qtde) AS qtde
                        FROM {compras}
                        WHERE filial = %s AND cliente = %s AND competencia = ANY(%s)
                        GROUP BY competencia, produto
                    )
                    SELECT c.competencia, c.produto,
                           NULLIF(ltrim(trim(COALESCE(p.payload->>'Garrrafeira', p.payload->>'Garrafeira', '')), '0'), '') AS garrafeira,
                           c.qtde
                    FROM compras c
                    JOIN {produtos} p ON ltrim(p.codigo, '0') = c.produto
                    """
                ).format(
                    compras=sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier("compras_030237_produto")),
                    produtos=sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier("dprodutos_latest")),
                ),
                (_codigo(filial), _codigo(cliente), list(competencias)),
            )
            linhas = cur.fetchall()
        return {c: somar_por_tipo([l[1:] for l in linhas if l[0] == c], catalogo) for c in competencias}

    def compras_ate(self, filial: str, competencia: str) -> Any:
        """Última data de operação da 03.02.37 importada no mês, para a filial (None sem dado)."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT max(ultima_data) FROM {} WHERE filial = %s AND competencia = %s").format(
                    sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier("compras_030237_produto"))
                ),
                (_codigo(filial), competencia),
            )
            return (cur.fetchone() or (None,))[0]


def somar_por_tipo(linhas: list[tuple[Any, ...]], catalogo: dict[str, dict[str, str]]) -> dict[str, float]:
    total = {tipo: 0.0 for tipo, _ in TIPOS}
    for _produto, garrafeira, qtde in linhas:
        item = catalogo.get(str(garrafeira or "").lstrip("0"))
        if item:
            total[item["tipo"]] += float(qtde or 0)
    return total


def caixas_em_comodato(itens: list[dict[str, Any]], catalogo: dict[str, dict[str, str]]) -> dict[str, float]:
    """Saldo das garrafeiras em comodato por tipo; a descrição liga o comodato à tabela de garrafeiras."""
    por_descricao = {_chave(item["descricao"]): item["tipo"] for item in catalogo.values()}
    total = {tipo: 0.0 for tipo, _ in TIPOS}
    for item in itens:
        sub_tipo = str(item.get("sub_tipo") or "").strip()
        if sub_tipo:
            # A 02.02.20 já diz o tipo ("GARRAFEIRA CERVEJA 1/1"); garrafa ("VASILHAME ...")
            # e outros materiais (SOPI, VISA...) não são caixa.
            tipo = tipo_da_garrafeira(item.get("material"), sub_tipo)
        else:
            tipo = por_descricao.get(_chave(item.get("material"))) or tipo_da_garrafeira(item.get("material"))
        if tipo:
            total[tipo] += _numero(item.get("saldo"))
    return total


def giro_por_tipo(caixas: dict[str, float], compradas: dict[str, float]) -> list[dict[str, Any]]:
    linhas = []
    for tipo, rotulo in TIPOS:
        tem = caixas.get(tipo, 0.0)
        meta = tem * MULTIPLICADOR
        comprou = compradas.get(tipo, 0.0)
        falta = max(meta - comprou, 0.0)
        linhas.append({
            "tipo": tipo,
            "rotulo": rotulo,
            "caixas": tem,
            "meta": meta,
            "compradas": comprou,
            "falta": falta,
            "em_risco": tem > 0 and falta > 0,
            "percentual": round(min(comprou / meta, 1) * 100) if meta else None,
        })
    return linhas


def previsao_por_visitas(compradas: float, media_mensal: float, visitas_no_mes: int, visitas_restantes: int) -> float:
    """Comprado até agora + o que ele costuma comprar por visita × visitas que faltam no mês."""
    if not visitas_no_mes:
        return compradas
    return compradas + media_mensal / visitas_no_mes * visitas_restantes


def situacao_das_caixas(meta: float, compradas: float, previsao: float) -> str:
    if compradas >= meta:
        return "batido"
    return "deve_bater" if previsao >= meta else "em_risco"


def _numero(valor: Any) -> float:
    texto = str(valor or "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _codigo(valor: Any) -> str:
    return str(valor or "").strip().lstrip("0") or "0"
