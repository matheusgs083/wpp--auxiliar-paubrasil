"""Fontes da ficha do cliente (12.06.01, 03.02.06, 02.02.20, dClientes) e formatação.

Usadas pela ficha da aba Clientes e pelos blocos da ficha (Rota Financeira).
Cada carregador só é chamado depois de o cliente passar pelo escopo no dClientes
e falha sozinho, devolvendo ``fonte.disponivel = False`` em vez de exceção.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.clientes_escopo import EscopoClientes


def _fonte(disponivel: bool, mensagem: str = "") -> dict[str, Any]:
    return {"disponivel": disponivel, "mensagem": mensagem}


def _carregar_titulos(service: Any, filial: str, cliente: str, escopo: EscopoClientes) -> dict[str, Any]:
    try:
        rows = service.search_by_registration(filial, cliente, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=100)
    except Exception:
        return {"fonte": _fonte(False, "Títulos indisponíveis agora."), "titulos": []}
    titulos = []
    for row in rows:
        dias = _inteiro(row.dias)
        titulos.append({
            "nota_fiscal": str(row.nota_fiscal or ""),
            "emissao": str(row.data_emissao or ""),
            "vencimento": str(row.data_vencimento or ""),
            "dias": dias,
            "situacao": situacao_vencimento(dias),
            "valor_original": str(row.valor_original or ""),
            "valor_pendente": str(row.valor_pendente or ""),
            "valor_corrigido": str(row.valor_corrigido or ""),
            "boleto": None,
        })
    atualizado = str(rows[0].planilha_atualizada_em) if rows else ""
    return {"fonte": _fonte(True), "titulos": titulos, "atualizado_em": atualizado}


def _carregar_boletos(service: Any | None, filial: str, cliente: str, escopo: EscopoClientes) -> dict[str, Any]:
    # Só é chamada depois de o cliente passar pelo escopo no dClientes. A busca de boletos
    # é por filial + NB desse cliente e vai sem filtro de carteira, porque a base 03.02.06
    # não entende escopo por GV junto com setor, nem escopo por operação.
    if service is None:
        return {"fonte": _fonte(False, "Boletos indisponíveis agora."), "itens": []}
    try:
        status = service.status() if hasattr(service, "status") else {"ready": True}
        if not status.get("ready"):
            return {"fonte": _fonte(False, "Boletos indisponíveis agora."), "itens": []}
        records = service.search_by_registration(
            filial=filial,
            cod_pdv=cliente,
            allowed_sectors=None,
            limit=20,
            include_pdf=False,
        )
    except Exception:
        return {"fonte": _fonte(False, "Boletos indisponíveis agora."), "itens": []}
    itens = [
        {
            "nosso_numero": _so_digitos(record.nosso_numero),
            "nota_fiscal": str(record.nota_fiscal or ""),
            "num_documento": str(record.num_documento or ""),
            "linha_digitavel": str(record.linha_digitavel or ""),
            "vencimento": _data_br(record.vencimento),
            "valor": _centavos_br(record.valor_centavos),
            "valor_centavos": int(record.valor_centavos or 0),
        }
        for record in records
        if _so_digitos(record.nosso_numero)
    ]
    return {"fonte": _fonte(True), "itens": itens}


def _carregar_comodatos(service: Any | None, filial: str, cliente: str, escopo: EscopoClientes) -> dict[str, Any]:
    if service is None:
        return {"fonte": _fonte(False, "Comodatos indisponíveis agora."), "itens": [], "saldo_total": "0"}
    try:
        rows = service.search_by_registration(filial, cliente, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=200)
    except Exception:
        return {"fonte": _fonte(False, "Comodatos indisponíveis agora."), "itens": [], "saldo_total": "0"}
    itens = [
        {
            "nro_comodato": str(row.nro_comodato or ""),
            "material": str(row.material or ""),
            "sub_tipo": str(row.sub_tipo_material or ""),
            "saldo": str(row.saldo or "0"),
        }
        for row in rows
    ]
    total = sum((_decimal(item["saldo"]) for item in itens), Decimal("0"))
    return {"fonte": _fonte(True), "itens": itens, "saldo_total": _quantidade(total)}


def _cadastro_completo(service: Any, filial: str, cliente: str) -> dict[str, str]:
    """Campos extras do cadastro (documento, endereço). Só é chamado depois da autorização."""
    try:
        perfil = service.get_payip_profile_by_registration(filial, cliente)
    except Exception:
        perfil = None
    if perfil is None:
        return {}
    endereco = ", ".join(part for part in (perfil.endereco, perfil.numero) if part)
    return {
        "documento": _documento_formatado(perfil.documento),
        "email": perfil.email,
        "endereco": endereco,
        "complemento": perfil.complemento,
        "bairro": perfil.bairro,
        "cidade_uf": " / ".join(part for part in (perfil.cidade, perfil.uf) if part),
        "cep": perfil.cep,
    }


def _cruzar_titulos_boletos(titulos: list[dict[str, Any]], boletos: list[dict[str, Any]]) -> None:
    """Liga cada título da 12.06.01 ao boleto da 03.02.06: pela NF; sem NF, por vencimento + valor."""
    livres = list(boletos)
    for titulo in titulos:
        nf = normalize_numeric_code(titulo["nota_fiscal"])
        escolhido = None
        if nf:
            escolhido = next(
                (b for b in livres if normalize_numeric_code(b["nota_fiscal"]) == nf or _so_digitos(b["num_documento"]).lstrip("0").startswith(nf)),
                None,
            )
        if escolhido is None:
            valor = _decimal(titulo["valor_pendente"])
            escolhido = next(
                (b for b in livres if b["vencimento"] == titulo["vencimento"] and valor and _decimal(b["valor"]) == valor),
                None,
            )
        if escolhido is not None:
            livres.remove(escolhido)
            titulo["boleto"] = escolhido


# ---------- formatação ----------

def situacao_vencimento(dias: int | None) -> str:
    if dias is None:
        return "sem_data"
    if dias < 0:
        return "vencido"
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "amanha"
    if dias == 2:
        return "dois_dias"
    return "em_dia"


def _so_digitos(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _inteiro(value: Any) -> int | None:
    texto = str(value if value is not None else "").strip()
    if not re.fullmatch(r"-?\d+", texto):
        return None
    return int(texto)


def _decimal(value: Any) -> Decimal:
    texto = str(value or "").replace("R$", "").replace(" ", "").strip()
    if not texto:
        return Decimal("0")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _dinheiro(value: Decimal) -> str:
    inteiro, _, centavos = f"{value:.2f}".partition(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    return f"{sinal}{'.'.join(grupos) or '0'},{centavos}"


def _centavos_br(centavos: Any) -> str:
    return _dinheiro(Decimal(int(centavos or 0)) / Decimal(100))


def _quantidade(value: Decimal) -> str:
    texto = f"{value.normalize():f}" if value else "0"
    return texto.replace(".", ",")


def _data_br(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value or "")


def _documento_formatado(documento: str) -> str:
    d = _so_digitos(documento)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return documento
