"""Escopo comercial do usuário do painel nas telas Clientes e Rota Financeira.

Fica num lugar só para as duas telas aplicarem exatamente a mesma regra.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from bot_api.commercial_scope import FILIAL_SCOPE_PREFIX, normalize_numeric_code, normalize_sector_scope_input
from bot_api.services.filial_labels import FILIAL_LABELS


@dataclass(frozen=True)
class EscopoClientes:
    """Recorte comercial do usuário do painel nas abas da área Vendedor.

    Ordem de precedência (a primeira que existir vale):
    - administrador: todos os clientes;
    - setores e/ou GVs do usuário (vendedor e gerente de vendas);
    - operações (filiais): todas (``*``) ou só as marcadas. Também vale para o acesso do financeiro.

    As filiais só viram escopo comercial quando o usuário não tem setor nem GV, para
    um vendedor que também usa a Crítica (filiais) não passar a ver a filial inteira.
    """

    irrestrito: bool
    setores: tuple[str, ...] = ()
    gvs: tuple[str, ...] = ()
    filiais: tuple[str, ...] = ()

    @property
    def allowed_sectors(self) -> list[str] | None:
        valores = [*self.setores, *(f"{FILIAL_SCOPE_PREFIX}{filial}" for filial in self.filiais)]
        return valores or None

    @property
    def allowed_gv_vdes(self) -> list[str] | None:
        return list(self.gvs) or None

    def permite_filial(self, filial: str) -> bool:
        """Filtro rápido de filial: só restringe quem tem escopo por operação."""
        if self.irrestrito or not self.filiais:
            return True
        return normalize_numeric_code(filial) in self.filiais

    def filiais_alcancadas(self) -> set[str] | None:
        """Filiais em que o usuário tem algum cliente (None = todas)."""
        if self.irrestrito:
            return None
        chaves = [*self.setores, *self.gvs]
        return {normalize_numeric_code(chave.split("_", 1)[0]) for chave in chaves} | set(self.filiais)

    def descricao(self) -> str:
        if self.irrestrito:
            return "Acesso a todas as operações"
        partes = []
        if self.setores:
            partes.append("Setores: " + ", ".join(item.replace("_", "-") for item in self.setores))
        if self.gvs:
            partes.append("GVs: " + ", ".join(item.replace("_", "-") for item in self.gvs))
        if self.filiais:
            partes.append("Operações: " + ", ".join(FILIAL_LABELS.get(filial, filial) for filial in self.filiais))
        return " · ".join(partes)


def escopo_do_contexto(context: Mapping[str, Any]) -> EscopoClientes:
    if bool(context.get("is_admin")):
        return EscopoClientes(irrestrito=True)
    setores = _chaves(context.get("seller_scopes"))
    gvs = _chaves(context.get("gv_scopes"))
    if setores or gvs:
        return EscopoClientes(irrestrito=False, setores=setores, gvs=gvs)
    brutas = [str(item).strip() for item in context.get("filiais") or ()]
    if "*" in brutas:
        return EscopoClientes(irrestrito=True)
    filiais = tuple(dict.fromkeys(code for code in (normalize_numeric_code(item) for item in brutas) if code))
    if filiais:
        return EscopoClientes(irrestrito=False, filiais=filiais)
    raise HTTPException(status_code=403, detail="Seu usuário não possui carteira (setor, GV ou operação) configurada.")


def _chaves(valores: Any) -> tuple[str, ...]:
    chaves: list[str] = []
    for item in valores or ():
        chave = normalize_sector_scope_input(str(item))
        if chave and chave not in chaves:
            chaves.append(chave)
    return tuple(chaves)


def _telefones(telefone: str) -> list[str]:
    """Separa os números do cadastro ("83 99889-1242 | 83 98166-6618") e tira os repetidos."""
    numeros: list[str] = []
    for parte in re.split(r"[|/;,]|\s{2,}", str(telefone or "")):
        digitos = re.sub(r"\D+", "", parte).lstrip("0")
        if digitos.startswith("55") and len(digitos) in (12, 13):
            digitos = digitos[2:]
        if len(digitos) in (10, 11) and digitos not in numeros:
            numeros.append(digitos)
    return numeros


def telefone_whatsapp(telefone: str) -> str:
    """Número no formato do wa.me (55 + DDD + número) ou vazio se não der para confiar nele.

    Com mais de um número no cadastro, usa o primeiro celular (DDD + 9 dígitos começando
    com 9); sem celular, o primeiro número válido.
    """
    numeros = _telefones(telefone)
    celular = next((n for n in numeros if len(n) == 11 and n[2] == "9"), "")
    escolhido = celular or (numeros[0] if numeros else "")
    return f"55{escolhido}" if escolhido else ""


def telefone_discagem(telefone: str) -> str:
    """Primeiro número do cadastro, só dígitos, para o link tel:."""
    numeros = _telefones(telefone)
    return numeros[0] if numeros else ""
