"""Giro de equipamentos do cliente: quanto ele precisa comprar no mês por geladeira em comodato.

Regra (definida em 23/11/2026):

- SOPI (geladeira de cerveja): R$ 2.000,00 por mês, só de cerveja.
- Visa (geladeira de refrigerante): R$ 1.200,00 por mês, de refrigerante.

A meta vale por equipamento: dois SOPI pedem R$ 4.000,00.

- Equipamentos do cliente: comodatos da 02.02.20 com "Sub-Tipo Material" SOPI ou VISA.
- Compras: 03.02.37 do mês atual (resumo por produto, valor total entregue).
- O que é cerveja e o que é refrigerante sai da Cesta de Produtos
  (cestas "Cerveja TT" e "Refrigerante TT").
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg import sql


@dataclass(frozen=True)
class RegraEquipamento:
    tipo: str
    rotulo: str
    sub_tipo: str
    cesta: str
    rotulo_cesta: str
    meta_por_equipamento: Decimal


REGRAS = (
    RegraEquipamento("sopi", "SOPI (cerveja)", "SOPI", "Cerveja TT", "cerveja", Decimal("2000.00")),
    RegraEquipamento("visa", "Visa (refrigerante)", "VISA", "Refrigerante TT", "refrigerante", Decimal("1200.00")),
)


class GiroEquipamentosService:
    def __init__(self, database_url: str, schema: str = "reports", *, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "")
        self.schema = str(schema or "reports")
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3), 1.0)

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=int(self.connect_timeout_seconds))

    def compras_por_cesta(self, filial: str, cliente: str, competencia: str) -> dict[str, Decimal]:
        """Valor comprado no mês em cada cesta da regra (produto → cesta pela Cesta de Produtos)."""
        cestas = [regra.cesta for regra in REGRAS]
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.produto_cestas_latest",))
            linha = cur.fetchone()
            if not linha or not linha[0]:
                raise RuntimeError("Cesta de Produtos não importada.")
            cur.execute(
                sql.SQL(
                    """
                    SELECT c.nome_cesta, sum(p.total)
                    FROM {compras} p
                    JOIN (SELECT DISTINCT codigo, nome_cesta FROM {cestas} WHERE nome_cesta = ANY(%s)) c
                      ON c.codigo = p.produto
                    WHERE p.filial = %s AND p.cliente = %s AND p.competencia = %s
                    GROUP BY c.nome_cesta
                    """
                ).format(
                    compras=sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier("compras_030237_produto")),
                    cestas=sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier("produto_cestas_latest")),
                ),
                (cestas, _codigo(filial), _codigo(cliente), competencia),
            )
            linhas = cur.fetchall()
        return {str(cesta): Decimal(str(total or 0)) for cesta, total in linhas}


def equipamentos_em_comodato(itens: list[dict[str, Any]]) -> dict[str, int]:
    """Quantos SOPI e Visa o cliente tem em comodato (saldo de cada linha)."""
    total = {regra.tipo: 0 for regra in REGRAS}
    por_sub_tipo = {regra.sub_tipo: regra.tipo for regra in REGRAS}
    for item in itens:
        tipo = por_sub_tipo.get(str(item.get("sub_tipo") or "").strip().upper())
        if tipo:
            total[tipo] += max(int(_numero(item.get("saldo"))), 0)
    return total


def giro_por_equipamento(equipamentos: dict[str, int], compras: dict[str, Decimal]) -> list[dict[str, Any]]:
    linhas = []
    for regra in REGRAS:
        quantidade = equipamentos.get(regra.tipo, 0)
        meta = regra.meta_por_equipamento * quantidade
        comprado = compras.get(regra.cesta, Decimal("0"))
        falta = max(meta - comprado, Decimal("0"))
        linhas.append({
            "tipo": regra.tipo,
            "rotulo": regra.rotulo,
            "cesta": regra.rotulo_cesta,
            "equipamentos": quantidade,
            "meta_por_equipamento": regra.meta_por_equipamento,
            "meta": meta,
            "comprado": comprado,
            "falta": falta,
            "em_risco": quantidade > 0 and falta > 0,
            "percentual": round(min(comprado / meta, Decimal("1")) * 100) if meta else None,
        })
    return linhas


def _numero(valor: Any) -> Decimal:
    texto = str(valor or "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _codigo(valor: Any) -> str:
    return str(valor or "").strip().lstrip("0") or "0"
