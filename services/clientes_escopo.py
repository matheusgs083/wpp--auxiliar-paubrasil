"""Escopo comercial do usuário do painel nas telas Clientes e Rota Financeira.

Fica num lugar só para as duas telas aplicarem exatamente a mesma regra.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from bot_api.commercial_scope import normalize_numeric_code, normalize_sector_scope_input


@dataclass(frozen=True)
class EscopoClientes:
    """Recorte comercial do usuário do painel.

    - administrador: todos os clientes;
    - financeiro (token do financeiro): clientes das filiais liberadas;
    - demais usuários: setores da carteira (``seller_scopes``), igual à aba Pedidos.
    """

    irrestrito: bool
    setores: tuple[str, ...] = ()
    filiais: tuple[str, ...] = ()

    @property
    def allowed_sectors(self) -> list[str] | None:
        return list(self.setores) if self.setores else None

    def permite_filial(self, filial: str) -> bool:
        if self.irrestrito or not self.filiais:
            return True
        return normalize_numeric_code(filial) in self.filiais

    def descricao(self) -> str:
        if self.irrestrito:
            return "Acesso administrativo"
        if self.setores:
            return "Carteira: " + ", ".join(item.replace("_", "-") for item in self.setores)
        return "Filiais: " + ", ".join(self.filiais)


def escopo_do_contexto(context: Mapping[str, Any]) -> EscopoClientes:
    if bool(context.get("is_admin")):
        return EscopoClientes(irrestrito=True)
    setores = _setores_da_carteira(context)
    if setores:
        return EscopoClientes(irrestrito=False, setores=setores)
    if str(context.get("mode") or "").strip().lower() == "financeiro":
        filiais = tuple(
            code
            for code in (normalize_numeric_code(str(item)) for item in context.get("filiais") or ())
            if code
        )
        if any(str(item).strip() == "*" for item in context.get("filiais") or ()):
            return EscopoClientes(irrestrito=True)
        if filiais:
            return EscopoClientes(irrestrito=False, filiais=filiais)
    raise HTTPException(status_code=403, detail="Seu usuário não possui uma carteira configurada para Clientes.")


def _setores_da_carteira(context: Mapping[str, Any]) -> tuple[str, ...]:
    setores: list[str] = []
    for item in context.get("seller_scopes") or ():
        chave = normalize_sector_scope_input(str(item))
        if chave and chave not in setores:
            setores.append(chave)
    return tuple(setores)


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
