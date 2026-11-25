"""Cadastro persistente dos nomes de GV, sem alterar os códigos de acesso."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import psycopg
from psycopg import sql


def chave_gv(chave: str) -> str:
    match = re.fullmatch(r"\s*(\d+)[_-](\d+)\s*", str(chave or ""))
    if not match:
        raise ValueError("Informe filial e GV numéricos.")
    return f"{int(match.group(1))}_{int(match.group(2))}"


def nome_padrao(chave: str) -> str:
    return "Tratamento" if chave_gv(chave).split("_")[1] == "99" else ""


def agrupar_gerentes(chaves: list[str], nomes: dict[str, str]) -> list[dict[str, Any]]:
    grupos: dict[str, dict[str, Any]] = {}
    for chave in sorted({chave_gv(item) for item in chaves}):
        filial, gv = chave.split("_")
        tratamento = gv == "99"
        nome = "Tratamento" if tratamento else str(nomes.get(chave) or "").strip()
        if not nome:
            continue
        normalizado = "".join(c for c in unicodedata.normalize("NFKD", nome.casefold()) if not unicodedata.combining(c))
        identificador = "tratamento:99" if tratamento else f"nome:{normalizado}"
        grupo = grupos.setdefault(identificador, {"nome": nome, "chaves": [], "filiais": [], "tratamento": tratamento})
        grupo["chaves"].append(chave)
        if filial not in grupo["filiais"]:
            grupo["filiais"].append(filial)
    return sorted(grupos.values(), key=lambda item: item["nome"].casefold())


class GerentesVendasService:
    def __init__(self, database_url: str, schema: str = "reports") -> None:
        self.database_url = database_url
        self.schema = schema

    def _ensure(self, conn: Any) -> None:
        conn.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {}.gerentes_vendas (filial TEXT NOT NULL, gv TEXT NOT NULL, nome VARCHAR(60) NOT NULL, atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (filial, gv))").format(sql.Identifier(self.schema)))

    def nomes(self) -> dict[str, str]:
        with psycopg.connect(self.database_url) as conn:
            self._ensure(conn)
            rows = conn.execute(sql.SQL("SELECT filial, gv, nome FROM {}.gerentes_vendas").format(sql.Identifier(self.schema))).fetchall()
            return {f"{filial}_{gv}": nome for filial, gv, nome in rows}

    def catalogo(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url) as conn:
            self._ensure(conn)
            rows = conn.execute(sql.SQL("SELECT filial, gv, COUNT(DISTINCT setor) FROM {}.dsetores_latest WHERE filial <> '' AND gv <> '' GROUP BY filial, gv ORDER BY filial, gv").format(sql.Identifier(self.schema))).fetchall()
            nomes = {f"{filial}_{gv}": nome for filial, gv, nome in conn.execute(sql.SQL("SELECT filial, gv, nome FROM {}.gerentes_vendas").format(sql.Identifier(self.schema))).fetchall()}
        return [{"filial": str(filial), "gv": str(gv), "chave": chave_gv(f"{filial}_{gv}"), "setores": count, "nome": nomes.get(chave_gv(f"{filial}_{gv}"), nome_padrao(f"{filial}_{gv}"))} for filial, gv, count in rows]

    def salvar(self, nomes: dict[str, str]) -> None:
        normalizados = []
        for chave, valor in nomes.items():
            filial, gv = chave_gv(chave).split("_")
            nome = " ".join(str(valor or "").split())
            if len(nome) > 60:
                raise ValueError("O nome deve ter no máximo 60 caracteres.")
            normalizados.append((filial, gv, nome))
        with psycopg.connect(self.database_url) as conn:
            self._ensure(conn)
            with conn.cursor() as cur:
                for filial, gv, nome in normalizados:
                    if nome:
                        cur.execute(sql.SQL("INSERT INTO {}.gerentes_vendas (filial, gv, nome) VALUES (%s, %s, %s) ON CONFLICT (filial, gv) DO UPDATE SET nome = EXCLUDED.nome, atualizado_em = NOW()").format(sql.Identifier(self.schema)), (filial, gv, nome))
                    else:
                        cur.execute(sql.SQL("DELETE FROM {}.gerentes_vendas WHERE filial = %s AND gv = %s").format(sql.Identifier(self.schema)), (filial, gv))
