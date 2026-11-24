"""Blocos da ficha do cliente (Rota Financeira e Clientes).

Cada bloco é montado por uma função que recebe o cliente já autorizado pelo
escopo e devolve sempre o mesmo formato:

    {"bloco", "titulo", "estado": ok|vazio|indisponivel, "resumo", "dados", "fonte"}

Uma fonte fora do ar vira ``estado = indisponivel`` só no próprio bloco; os
outros blocos continuam respondendo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

from bot_api.services.clientes_escopo import EscopoClientes
from bot_api.services.clientes_fontes import (
    _cadastro_completo,
    _carregar_boletos,
    _carregar_comodatos,
    _carregar_titulos,
    _cruzar_titulos_boletos,
    _decimal,
    _documento_formatado,
    _dinheiro,
    _quantidade,
)
from bot_api.services.compras_030237_service import DIAS_DEVOLUCAO, meses_fechados
from bot_api.services.ficha_cadastro import dias_da_visita, dias_por_extenso, montar_cadastro
from bot_api.services.giro_equipamentos_service import (
    REGRAS,
    equipamentos_em_comodato,
    giro_por_equipamento,
    mix_cerveja,
    previsao_do_mes,
    situacao_do_giro,
)
from bot_api.services.giro_vasilhame_service import MULTIPLICADOR, caixas_em_comodato, giro_por_tipo

BLOCOS = ("titulos", "credito", "compras", "vasilhames", "equipamentos", "comodatos", "devolucoes", "cadastro")
SITUACAO_BOLETO_SEM_VINCULO = "Boleto não importado"


@dataclass(frozen=True)
class ClienteAutorizado:
    """Cliente que já passou pelo escopo no dClientes; só ele chega aos blocos."""

    filial: str
    cliente: str
    registro: Any
    escopo: EscopoClientes


@dataclass(frozen=True)
class Fontes:
    dclientes: Any
    inadimplencia: Any
    boletos: Any | None = None
    comodatos: Any | None = None
    prazo_limite: Any | None = None
    documentacao: Any | None = None
    compras: Any | None = None
    justificativas: Any | None = None
    giro_vasilhame: Any | None = None
    giro_equipamentos: Any | None = None


def montar_bloco(nome: str, cliente: ClienteAutorizado, fontes: Fontes, *, hoje: date) -> dict[str, Any]:
    construtor = _CONSTRUTORES.get(nome)
    if construtor is None:
        raise KeyError(nome)
    return construtor(cliente, fontes, hoje)


def cabecalho(cliente: ClienteAutorizado, fontes: Fontes, payload_cliente: dict[str, Any]) -> dict[str, Any]:
    cadastro = _cadastro_completo(fontes.dclientes, cliente.filial, cliente.cliente)
    endereco = ", ".join(
        parte for parte in (cadastro.get("endereco"), cadastro.get("bairro"), cadastro.get("cidade_uf") or payload_cliente.get("cidade"), cadastro.get("cep")) if parte
    )
    return {
        **payload_cliente,
        "endereco_completo": endereco,
        "mapa_url": f"https://www.google.com/maps/search/?api=1&query={quote_plus(endereco)}" if cadastro.get("endereco") else "",
        "blocos": list(BLOCOS),
    }


# ------------------------------------------------------------------ blocos

def _bloco(nome: str, titulo: str, *, estado: str, resumo: str, dados: Any, fonte: str, atualizado_em: Any = "", mensagem: str = "") -> dict[str, Any]:
    return {
        "bloco": nome,
        "titulo": titulo,
        "estado": estado,
        "resumo": resumo,
        "dados": dados,
        "fonte": {"nome": fonte, "atualizado_em": _texto_data(atualizado_em), "disponivel": estado != "indisponivel", "mensagem": mensagem},
    }


def _indisponivel(nome: str, titulo: str, fonte: str, mensagem: str) -> dict[str, Any]:
    return _bloco(nome, titulo, estado="indisponivel", resumo=mensagem, dados=None, fonte=fonte, mensagem=mensagem)


def bloco_titulos(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Títulos em aberto"
    financeiro = _carregar_titulos(fontes.inadimplencia, cliente.filial, cliente.cliente, cliente.escopo)
    if not financeiro["fonte"]["disponivel"]:
        return _indisponivel("titulos", titulo, "12.06.01", financeiro["fonte"]["mensagem"])
    boletos = _carregar_boletos(fontes.boletos, cliente.filial, cliente.cliente, cliente.escopo)
    titulos = financeiro["titulos"]
    _cruzar_titulos_boletos(titulos, boletos["itens"])
    for item in titulos:
        if item["boleto"] is not None:
            item["situacao_boleto"] = "Boleto disponível"
        elif boletos["fonte"]["disponivel"]:
            item["situacao_boleto"] = SITUACAO_BOLETO_SEM_VINCULO
        else:
            item["situacao_boleto"] = "Base de boletos indisponível"
    total = sum((_decimal(t["valor_pendente"]) for t in titulos), Decimal("0"))
    vencidos = sum(1 for t in titulos if t["situacao"] == "vencido")
    if not titulos:
        return _bloco("titulos", titulo, estado="vazio", resumo="Nenhum título em aberto", dados={"titulos": []}, fonte="12.06.01", atualizado_em=financeiro.get("atualizado_em"))
    resumo = f"R$ {_dinheiro(total)} em {len(titulos)} título{'s' if len(titulos) != 1 else ''}, {vencidos} vencido{'s' if vencidos != 1 else ''}"
    return _bloco(
        "titulos", titulo, estado="ok", resumo=resumo,
        dados={"titulos": titulos, "total_pendente": _dinheiro(total), "vencidos": vencidos, "boletos_disponivel": boletos["fonte"]["disponivel"]},
        fonte="12.06.01 + 03.02.06", atualizado_em=financeiro.get("atualizado_em"),
    )


def bloco_credito(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Análise de crédito"
    if fontes.prazo_limite is None:
        return _indisponivel("credito", titulo, "Prazo e limite", "Base de prazo e limite não configurada.")
    try:
        registros = fontes.prazo_limite.search_by_registration(
            cliente.filial, cliente.cliente, allowed_sectors=cliente.escopo.allowed_sectors, allowed_gv_vdes=cliente.escopo.allowed_gv_vdes, limit=5
        )
    except Exception:
        return _indisponivel("credito", titulo, "Prazo e limite", "Base de prazo e limite indisponível.")
    entradas = [entrada for registro in registros for entrada in registro.entries]
    limite_total = _primeiro(entradas, "limite_total") or str(getattr(cliente.registro, "limite_credito", "") or "")
    prazo = _primeiro(entradas, "prazo_atual")
    condicao = _primeiro(entradas, "cond_pag_atual") or str(getattr(cliente.registro, "cond_pag_atual", "") or "")
    atraso = _primeiro(entradas, "percentual_pag_atraso")
    financeiro = _carregar_titulos(fontes.inadimplencia, cliente.filial, cliente.cliente, cliente.escopo)
    pendente = sum((_decimal(t["valor_pendente"]) for t in financeiro["titulos"]), Decimal("0")) if financeiro["fonte"]["disponivel"] else None
    limite = _decimal(limite_total)
    disponivel = (limite - pendente) if (limite_total and pendente is not None) else None
    faturamento, fonte_faturamento = _faturamento_030237(cliente, fontes, hoje)
    dados = {
        "limite_total": _dinheiro(limite) if limite_total else "",
        "limite_utilizado": _dinheiro(pendente) if pendente is not None else "",
        "limite_disponivel": _dinheiro(disponivel) if disponivel is not None else "",
        "limite_disponivel_calculado": disponivel is not None,
        "condicao_pagamento": condicao,
        "prazo_atual": prazo,
        "percentual_pag_atraso": atraso,
        "faturamento": faturamento,
        "faturamento_fonte": fonte_faturamento,
    }
    if not registros and not limite_total:
        return _bloco("credito", titulo, estado="vazio", resumo="Sem dados de prazo e limite", dados=dados, fonte="Prazo e limite")
    partes = []
    if disponivel is not None:
        partes.append(f"Limite disponível R$ {_dinheiro(disponivel)} (calculado)")
    elif limite_total:
        partes.append(f"Limite total R$ {_dinheiro(limite)}")
    if prazo:
        partes.append(f"Prazo atual {prazo}")
    atualizado = getattr(registros[0], "planilha_atualizada_em", "") if registros else ""
    return _bloco("credito", titulo, estado="ok", resumo=" · ".join(partes) or "Sem limite informado", dados=dados, fonte="Prazo e limite + 12.06.01 + 03.02.37", atualizado_em=atualizado)


def _faturamento_030237(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> tuple[list[dict[str, Any]], str]:
    """Faturamento entregue e notas por mês, da 03.02.37 (mesma base do bloco Compras)."""
    if fontes.compras is None:
        return [], "indisponivel"
    try:
        resumo = fontes.compras.resumo_cliente(cliente.filial, cliente.cliente, hoje=hoje)
    except Exception:
        return [], "indisponivel"
    linhas = []
    for mes in reversed(resumo.get("serie") or []):
        rotulo = f"{_mes_br(mes['competencia'])}{' (parcial)' if mes.get('atual') else ''}"
        if not mes.get("com_base", True):
            rotulo += " · fora da base"
        linhas.append({"kpi": rotulo, "faturamento_com_pdv": f"R$ {_dinheiro(Decimal(str(mes.get('total') or 0)))}", "pedidos": str(mes.get("notas") or 0)})
    if resumo.get("media_3_meses") is not None:
        linhas.append({"kpi": "Média mensal (3 meses)", "faturamento_com_pdv": f"R$ {_dinheiro(Decimal(str(resumo['media_3_meses'])))}", "pedidos": ""})
    return linhas, "03.02.37"


def bloco_compras(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Compras"
    if fontes.compras is None:
        return _indisponivel("compras", titulo, "03.02.37", "Base de compras não configurada.")
    try:
        resumo = fontes.compras.resumo_cliente(cliente.filial, cliente.cliente, hoje=hoje)
    except Exception:
        return _indisponivel("compras", titulo, "03.02.37", "Base de compras (03.02.37) indisponível.")
    if not resumo.get("base_desde"):
        return _bloco("compras", titulo, estado="vazio", resumo="Sem compras importadas da 03.02.37", dados=resumo, fonte="03.02.37")
    if resumo.get("media_3_meses") is None:
        texto = f"Base desde {_mes_br(resumo['base_desde'])}"
    else:
        texto = f"Média mensal entregue (3 meses): R$ {_dinheiro(Decimal(str(resumo['media_3_meses'])))}"
    return _bloco("compras", titulo, estado="ok", resumo=texto, dados=resumo, fonte="03.02.37", atualizado_em=resumo.get("atualizado_em"))


def bloco_vasilhames(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Vasilhames"
    fonte = "02.02.20 + 03.02.37 + garrafeiras"
    if fontes.giro_vasilhame is None or fontes.comodatos is None:
        return _indisponivel("vasilhames", titulo, fonte, "Giro de vasilhames não configurado.")
    competencia = f"{hoje.year:04d}-{hoje.month:02d}"
    try:
        catalogo = fontes.giro_vasilhame.catalogo()
        comodatos = fontes.comodatos.search_by_registration(
            cliente.filial, cliente.cliente, allowed_sectors=cliente.escopo.allowed_sectors, allowed_gv_vdes=cliente.escopo.allowed_gv_vdes, limit=200
        )
        compradas = fontes.giro_vasilhame.caixas_compradas(cliente.filial, cliente.cliente, competencia)
    except Exception:
        return _indisponivel("vasilhames", titulo, fonte, "Base do giro de vasilhames indisponível (comodatos, 03.02.37 ou garrafeiras).")
    itens = [{"material": str(r.material or ""), "sub_tipo": str(r.sub_tipo_material or ""), "saldo": str(r.saldo or "0")} for r in comodatos]
    tipos = giro_por_tipo(caixas_em_comodato(itens, catalogo), compradas)
    for t in tipos:
        for campo in ("caixas", "meta", "compradas", "falta"):
            t[campo] = _quantidade(Decimal(str(round(t[campo], 3))))
    dados = {
        "tipos": tipos,
        "competencia": competencia,
        "multiplicador": MULTIPLICADOR,
        "explicacao": f"Para girar, o cliente precisa comprar no mês {MULTIPLICADOR}× as caixas que tem em comodato (10 caixas → 20 caixas). Conta só a 03.02.37 do mês atual.",
    }
    if not any(_decimal(t["caixas"]) > 0 for t in tipos):
        return _bloco("vasilhames", titulo, estado="vazio", resumo="Sem garrafeiras em comodato", dados=dados, fonte=fonte)
    em_risco = sum(1 for t in tipos if t["em_risco"])
    resumo = f"{em_risco} vasilhame{'s' if em_risco != 1 else ''} em risco de não bater o giro" if em_risco else "Giro de vasilhames batido no mês"
    return _bloco("vasilhames", titulo, estado="ok", resumo=resumo, dados=dados, fonte=fonte, atualizado_em=getattr(comodatos[0], "planilha_atualizada_em", "") if comodatos else "")


def bloco_equipamentos(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Equipamentos"
    fonte = "02.02.20 + 03.02.37 + Cesta de Produtos"
    if fontes.giro_equipamentos is None or fontes.comodatos is None:
        return _indisponivel("equipamentos", titulo, fonte, "Giro de equipamentos não configurado.")
    competencia = f"{hoje.year:04d}-{hoje.month:02d}"
    anteriores = meses_fechados(hoje)
    try:
        comodatos = fontes.comodatos.search_by_registration(
            cliente.filial, cliente.cliente, allowed_sectors=cliente.escopo.allowed_sectors, allowed_gv_vdes=cliente.escopo.allowed_gv_vdes, limit=200
        )
        itens = [{"sub_tipo": str(r.sub_tipo_material or ""), "saldo": str(r.saldo or "0"), "valor": str(getattr(r, "valor", "") or "")} for r in comodatos]
        equipamentos = equipamentos_em_comodato(itens)
        compras = fontes.giro_equipamentos.compras_por_cesta(cliente.filial, cliente.cliente, competencia) if any(equipamentos.values()) else {}
        cervejas = (
            fontes.giro_equipamentos.produtos_da_cesta(cliente.filial, cliente.cliente, [*anteriores, competencia])
            if equipamentos.get("sopi") else []
        )
    except Exception:
        return _indisponivel("equipamentos", titulo, fonte, "Base do giro de equipamentos indisponível (comodatos, 03.02.37 ou Cesta de Produtos).")
    tipos = giro_por_equipamento(equipamentos, compras)
    valores = _valor_dos_equipamentos(itens)
    for t in tipos:
        previsao = previsao_do_mes(t["comprado"], hoje)
        t["situacao"] = situacao_do_giro(t["meta"], t["comprado"], previsao) if t["equipamentos"] else ""
        t["previsao"] = _dinheiro(previsao)
        t["valor_equipamentos"] = _dinheiro(valores.get(t["tipo"], Decimal("0")))
        for campo in ("meta_por_equipamento", "meta", "comprado", "falta"):
            t[campo] = _dinheiro(t[campo])
    mix = mix_cerveja(cervejas, competencia, anteriores) if equipamentos.get("sopi") else None
    dados = {
        "tipos": tipos,
        "mix": mix,
        "competencia": competencia,
        "explicacao": "Meta por equipamento no mês: SOPI R$ 2.000,00 em cerveja e Visa R$ 1.200,00 em refrigerante, pela 03.02.37 e pela Cesta de Produtos. A previsão segue o ritmo do mês até hoje.",
    }
    if not any(equipamentos.values()):
        return _bloco("equipamentos", titulo, estado="vazio", resumo="Sem SOPI ou Visa em comodato", dados=dados, fonte=fonte)
    return _bloco("equipamentos", titulo, estado="ok", resumo=_resumo_equipamentos(tipos, mix), dados=dados, fonte=fonte,
                  atualizado_em=getattr(comodatos[0], "planilha_atualizada_em", "") if comodatos else "")


def _valor_dos_equipamentos(itens: list[dict[str, str]]) -> dict[str, Decimal]:
    """Soma da coluna Valor da 02.02.20 dos SOPI/Visa que estão no cliente."""
    por_sub_tipo = {regra.sub_tipo: regra.tipo for regra in REGRAS}
    total: dict[str, Decimal] = {}
    for item in itens:
        tipo = por_sub_tipo.get(item["sub_tipo"].strip().upper())
        if tipo and _decimal(item["saldo"]) > 0:
            total[tipo] = total.get(tipo, Decimal("0")) + _decimal(item["valor"])
    return total


def _resumo_equipamentos(tipos: list[dict[str, Any]], mix: dict[str, Any] | None) -> str:
    frases = {"batido": "giro batido", "deve_atingir": "deve atingir a meta no mês", "em_risco": "abaixo da meta no ritmo atual"}
    partes = [
        f"{t['rotulo'].split(' ')[0]}: {frases[t['situacao']]}"
        for t in tipos if t["equipamentos"]
    ]
    if mix is not None:
        partes.append(f"mix de cerveja {mix['skus_mes']} de {mix['meta']} SKUs")
    return " · ".join(partes)


def bloco_comodatos(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Comodatos"
    if fontes.comodatos is None:
        return _indisponivel("comodatos", titulo, "02.02.20", "Consulta de comodatos não configurada.")
    try:
        registros = fontes.comodatos.search_by_registration(
            cliente.filial, cliente.cliente, allowed_sectors=cliente.escopo.allowed_sectors, allowed_gv_vdes=cliente.escopo.allowed_gv_vdes, limit=200
        )
    except Exception:
        return _indisponivel("comodatos", titulo, "02.02.20", "02.02.20 não importada ou indisponível.")
    itens = []
    for r in registros:
        vencimento = _data(getattr(r, "vencimento", ""))
        itens.append({
            "nro_comodato": str(r.nro_comodato or ""),
            "material": str(r.material or ""),
            "sub_tipo": str(r.sub_tipo_material or ""),
            "saldo": str(r.saldo or "0"),
            "vencimento": getattr(r, "vencimento", "") or "",
            "vencido": bool(vencimento and vencimento < hoje),
        })
    saldo = sum((_decimal(i["saldo"]) for i in itens), Decimal("0"))
    if not itens:
        return _bloco("comodatos", titulo, estado="vazio", resumo="Nenhum comodato em aberto", dados={"itens": []}, fonte="02.02.20")
    com_data = any(i["vencimento"] for i in itens)
    vencidos = sum(1 for i in itens if i["vencido"])
    if com_data:
        resumo = f"{len(itens)} {'itens' if len(itens) != 1 else 'item'}, {vencidos} com contrato vencido"
    else:
        resumo = f"{len(itens)} comodato{'s' if len(itens) != 1 else ''} · saldo total {_quantidade(saldo)}"
    dados = {"itens": itens, "saldo_total": _quantidade(saldo), "vencidos": vencidos, "tem_vencimento": com_data}
    return _bloco("comodatos", titulo, estado="ok", resumo=resumo, dados=dados, fonte="02.02.20", atualizado_em=getattr(registros[0], "planilha_atualizada_em", ""))


def bloco_devolucoes(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Devoluções"
    if fontes.compras is None:
        return _indisponivel("devolucoes", titulo, "03.02.37", "Base de devoluções não configurada.")
    desde = hoje - timedelta(days=DIAS_DEVOLUCAO)
    try:
        itens = fontes.compras.devolucoes_cliente(cliente.filial, cliente.cliente, desde=desde)
        atualizado = fontes.compras.atualizado_em(cliente.filial)
    except Exception:
        return _indisponivel("devolucoes", titulo, "03.02.37", "Base de devoluções (03.02.37) indisponível.")
    for item in itens:
        item["justificativa"] = _justificativa(fontes.justificativas, cliente, item)
    dados = {"itens": itens, "desde": desde.isoformat(), "dias": DIAS_DEVOLUCAO}
    if not itens:
        return _bloco("devolucoes", titulo, estado="vazio", resumo="Sem devoluções recentes", dados=dados, fonte="03.02.37", atualizado_em=atualizado)
    resumo = f"{len(itens)} devoluç{'ões' if len(itens) != 1 else 'ão'} recente{'s' if len(itens) != 1 else ''}"
    return _bloco("devolucoes", titulo, estado="ok", resumo=resumo, dados=dados, fonte="03.02.37", atualizado_em=atualizado)


def bloco_cadastro(cliente: ClienteAutorizado, fontes: Fontes, hoje: date) -> dict[str, Any]:
    titulo = "Cadastro e documentos"
    r = cliente.registro
    try:
        perfil = fontes.dclientes.get_payip_profile_by_registration(cliente.filial, cliente.cliente)
    except Exception:
        perfil = None
    payload = dict(getattr(perfil, "payload", None) or {})
    try:
        docs = fontes.documentacao.search_by_registration(
            cliente.filial, cliente.cliente, allowed_sectors=cliente.escopo.allowed_sectors, allowed_gv_vdes=cliente.escopo.allowed_gv_vdes, limit=5
        ) if fontes.documentacao is not None else None
    except Exception:
        docs = None
    dados = montar_cadastro(payload, docs[0] if docs else None, hoje=hoje, docs_disponivel=docs is not None)
    # Sem a linha completa da dClientes, fica o básico do registro do cliente.
    for chave, atributo in (("razao_social", "razao_social"), ("nome_fantasia", "nome_fantasia"), ("status", "status"), ("setor", "vendedor"), ("gv", "gv")):
        dados[chave] = dados[chave] or str(getattr(r, atributo, "") or "")
    if not dados["visita_vendedor"]:
        dia = str(getattr(r, "dia_visita", "") or "")
        dados["visita_vendedor"] = dias_por_extenso(dias_da_visita(dia)) or dia
    if perfil is not None and not payload:
        dados["documento"] = _documento_formatado(getattr(perfil, "documento", ""))
        dados["endereco"] = ", ".join(p for p in (getattr(perfil, "endereco", ""), getattr(perfil, "numero", "")) if p)
        dados["bairro_cidade"] = ", ".join(p for p in (getattr(perfil, "bairro", ""), getattr(perfil, "cidade", ""), getattr(perfil, "uf", "")) if p)
        dados["cep"] = str(getattr(perfil, "cep", "") or "")
    if not dados["telefones"] and getattr(r, "telefone", ""):
        dados["telefones"] = [str(r.telefone)]
    partes = [f"Setor {_setor_curto(dados['setor'])}" if dados["setor"] else "", dados["visita_vendedor"]]
    doc = dados["documentacao"]
    if doc["completa"] is True:
        partes.append("documentação completa")
    elif doc["pendentes"]:
        partes.append(f"{doc['pendentes']} documento{'s' if doc['pendentes'] != 1 else ''} pendente{'s' if doc['pendentes'] != 1 else ''}")
    elif doc["completa"] is False:
        partes.append("documentação pendente")
    resumo = " · ".join(p for p in partes if p) or "Cadastro do cliente"
    return _bloco("cadastro", titulo, estado="ok", resumo=resumo, dados=dados, fonte="dClientes + documentação pendente", atualizado_em=getattr(r, "ultima_atualizacao_tabela", ""))


def _setor_curto(setor: str) -> str:
    """'3_107' -> '107' (a chave filial_setor só interessa pelo setor)."""
    return setor.split("_", 1)[-1] if "_" in setor else setor


_CONSTRUTORES: dict[str, Callable[[ClienteAutorizado, Fontes, date], dict[str, Any]]] = {
    "titulos": bloco_titulos,
    "credito": bloco_credito,
    "compras": bloco_compras,
    "vasilhames": bloco_vasilhames,
    "equipamentos": bloco_equipamentos,
    "comodatos": bloco_comodatos,
    "devolucoes": bloco_devolucoes,
    "cadastro": bloco_cadastro,
}


# ------------------------------------------------------------------ apoio

def _primeiro(entradas: list[Any], campo: str) -> str:
    for entrada in entradas:
        valor = str(getattr(entrada, campo, "") or "").strip()
        if valor and valor != "-":
            return valor
    return ""


def _justificativa(service: Any | None, cliente: ClienteAutorizado, item: dict[str, Any]) -> str:
    if service is None:
        return ""
    try:
        from bot_api.services.devolucoes_justificativas_service import devolucao_id

        # A Liga registra a justificativa pela nota da devolução; algumas vêm pela NF de origem.
        for nota in dict.fromkeys(n for n in (item["nota"], item["nf_referencia"]) if n):
            chave = devolucao_id({"filial": cliente.filial, "cliente_cod": cliente.cliente, "nota": nota, "serie": item["serie"], "data_devolucao": item["data"]})
            registro = service.get(chave) or {}
            if registro.get("text"):
                return str(registro["text"])
        return ""
    except Exception:
        return ""


def _data(valor: Any) -> date | None:
    texto = str(valor or "").strip()
    try:
        if len(texto) == 10 and texto[2] == "/":
            return datetime.strptime(texto, "%d/%m/%Y").date()
        if len(texto) >= 10 and texto[4] == "-":
            return date.fromisoformat(texto[:10])
    except ValueError:
        return None
    return None


def _texto_data(valor: Any) -> str:
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor or "").strip()
    if len(texto) >= 16 and texto[4] == "-" and texto[10] in "T ":
        try:
            return datetime.fromisoformat(texto[:19]).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return texto
    return texto


def _mes_br(competencia: str) -> str:
    ano, _, mes = str(competencia or "").partition("-")
    return f"{mes}/{ano}" if ano and mes else competencia

