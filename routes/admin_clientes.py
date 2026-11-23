"""Aba Clientes do painel: ficha do cliente com cadastro, 12.06.01, 02.02.20 e 03.02.06.

Toda leitura passa pelo escopo do usuário logado (ver ``EscopoClientes``):
o navegador só informa filial/NB/busca; quem decide o que pode ser visto é o
servidor. Cliente fora do escopo responde 403 com a mesma mensagem de cliente
inexistente, para não revelar a existência de clientes de outra carteira.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.clientes_escopo import EscopoClientes, escopo_do_contexto, telefone_discagem, telefone_whatsapp

FEATURE_CLIENTES = "cliente"
# A Rota Financeira abre o detalhe e o PDF do boleto por estes mesmos endpoints.
FEATURE_ROTA_FINANCEIRA = "rota_financeira"
LIMITE_RESULTADOS = 10
FILTROS_VALIDOS = ("pendencia", "vencidos", "boleto", "comodato")
MENSAGEM_FORA_DA_CARTEIRA = "Cliente não encontrado na carteira autorizada para este usuário."


def create_admin_clientes_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    dclientes_query_service: Any,
    inadimplencia_query_service: Any,
    comodatos_query_service: Any | None,
    boletos_query_service: Any | None,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def autenticar(
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
        x_admin_token: str | None,
        *,
        aceita_rota_financeira: bool = False,
    ) -> tuple[dict[str, Any], EscopoClientes]:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        try:
            require_admin_panel_feature(context, FEATURE_CLIENTES)
        except HTTPException:
            if not aceita_rota_financeira:
                raise
            require_admin_panel_feature(context, FEATURE_ROTA_FINANCEIRA)
        return context, escopo_do_contexto(context)

    def registrar_acao(request: Request, context: Mapping[str, Any], acao: str, **metadata: Any) -> None:
        if record_admin_panel_action:
            record_admin_panel_action(request=request, context=context, module="clientes", action=acao, metadata=metadata)

    def cliente_autorizado(request: Request, escopo: EscopoClientes, filial: str, cliente: str, evento: str) -> Any:
        if not escopo.permite_filial(filial):
            negar(request, evento, filial, cliente)
        try:
            rows = dclientes_query_service.search_by_registration(str(filial), str(cliente), allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Cadastro de clientes (dClientes) indisponível no momento.") from exc
        if not rows:
            negar(request, evento, filial, cliente)
        return rows[0]

    def negar(request: Request, evento: str, filial: str, cliente: str) -> None:
        record_security_event(request, channel="api", event_type=evento, decision="denied", reason=f"filial={filial};cliente={cliente};fora_da_carteira")
        raise HTTPException(status_code=403, detail=MENSAGEM_FORA_DA_CARTEIRA)

    @router.get("/api/admin/clientes")
    def pesquisar_clientes(
        request: Request,
        busca: str = Query(min_length=2, max_length=120),
        filial: str | None = Query(default=None, max_length=8),
        filtros: str | None = Query(default=None, max_length=80),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context, escopo = autenticar(request, authorization, x_api_token, x_admin_token)
        filtros_ativos = _filtros(filtros)
        texto = str(busca).strip()
        digitos = re.sub(r"\D+", "", texto)
        filial_code = normalize_numeric_code(filial or "")
        try:
            # CPF/CNPJ (11 ou 14 dígitos, com ou sem pontuação). NB nunca chega a esse tamanho.
            if len(digitos) in (11, 14) and not re.search(r"[A-Za-zÀ-ÿ]", texto):
                rows = dclientes_query_service.search_by_document(digitos, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=LIMITE_RESULTADOS)
            elif texto.isdigit():
                if not filial_code:
                    raise HTTPException(status_code=422, detail="Para buscar pelo NB, escolha a filial.")
                rows = dclientes_query_service.search_by_registration(filial_code, texto, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes)
            else:
                rows = dclientes_query_service.search_by_fantasia(texto, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=LIMITE_RESULTADOS)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Cadastro de clientes (dClientes) indisponível no momento.") from exc

        rows = [row for row in rows if escopo.permite_filial(str(row.filial))]
        if filial_code:
            rows = [row for row in rows if normalize_numeric_code(str(row.filial)) == filial_code]
        clientes = [_cliente_payload(row) for row in rows[:LIMITE_RESULTADOS]]

        # Vencidos e boleto exigem consulta por cliente: só roda quando o filtro é pedido,
        # e no máximo para os LIMITE_RESULTADOS clientes já autorizados.
        if {"vencidos", "boleto"} & set(filtros_ativos):
            for item in clientes:
                item["resumo"] = _resumo_rapido(item["filial"], item["cliente"], escopo, inadimplencia_query_service, boletos_query_service)
        clientes = [item for item in clientes if _passa_filtros(item, filtros_ativos)]

        record_security_event(request, channel="api", event_type="admin_clientes_busca", decision="allowed", reason=f"total={len(clientes)};filtros={','.join(filtros_ativos) or '-'}")
        return {"ok": True, "clientes": clientes, "total": len(clientes), "limite": LIMITE_RESULTADOS, "escopo": escopo.descricao(), "filtros": filtros_ativos}

    @router.get("/api/admin/clientes/{filial}/{cliente}")
    def ficha_cliente(
        request: Request,
        filial: str,
        cliente: str,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context, escopo = autenticar(request, authorization, x_api_token, x_admin_token, aceita_rota_financeira=True)
        registro = cliente_autorizado(request, escopo, filial, cliente, "admin_clientes_ficha")
        filial_code = normalize_numeric_code(str(registro.filial))
        cliente_code = normalize_numeric_code(str(registro.cod_pdv))

        financeiro = _carregar_titulos(inadimplencia_query_service, filial_code, cliente_code, escopo)
        boletos = _carregar_boletos(boletos_query_service, filial_code, cliente_code, escopo)
        comodatos = _carregar_comodatos(comodatos_query_service, filial_code, cliente_code, escopo)
        _cruzar_titulos_boletos(financeiro["titulos"], boletos["itens"])

        payload = _cliente_payload(registro)
        payload["cadastro"] = _cadastro_completo(dclientes_query_service, filial_code, cliente_code)
        kpis = _kpis(financeiro, boletos, comodatos)

        record_security_event(request, channel="api", event_type="admin_clientes_ficha", decision="allowed", reason=f"filial={filial_code};cliente={cliente_code}")
        registrar_acao(request, context, "consultar_ficha", filial=filial_code, cliente=cliente_code)
        return {"ok": True, "cliente": payload, "kpis": kpis, "financeiro": financeiro, "boletos": boletos, "comodatos": comodatos, "escopo": escopo.descricao()}

    @router.get("/api/admin/clientes/{filial}/{cliente}/boletos/{nosso_numero}/pdf")
    def boleto_pdf(
        request: Request,
        filial: str,
        cliente: str,
        nosso_numero: str,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        context, escopo = autenticar(request, authorization, x_api_token, x_admin_token, aceita_rota_financeira=True)
        registro = cliente_autorizado(request, escopo, filial, cliente, "admin_clientes_boleto_pdf")
        filial_code = normalize_numeric_code(str(registro.filial))
        cliente_code = normalize_numeric_code(str(registro.cod_pdv))
        alvo = _so_digitos(nosso_numero)
        if not alvo or boletos_query_service is None:
            raise HTTPException(status_code=404, detail="Boleto não encontrado para este cliente.")
        try:
            records = boletos_query_service.search_by_registration(
                filial=filial_code,
                cod_pdv=cliente_code,
                allowed_sectors=None,
                limit=20,
                include_pdf=True,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Base de boletos (03.02.06) indisponível no momento.") from exc
        record = next((item for item in records if _so_digitos(item.nosso_numero) == alvo), None)
        if record is None or not record.pdf_bytes:
            raise HTTPException(status_code=404, detail="Boleto não encontrado para este cliente.")
        record_security_event(request, channel="api", event_type="admin_clientes_boleto_pdf", decision="allowed", reason=f"filial={filial_code};cliente={cliente_code};nosso_numero={alvo}")
        registrar_acao(request, context, "abrir_boleto_pdf", filial=filial_code, cliente=cliente_code, nosso_numero=alvo)
        nome = f"boleto-{filial_code}-{cliente_code}-{alvo}.pdf"
        return Response(
            content=record.pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{nome}"', "Cache-Control": "private, no-store"},
        )

    return router


# ---------- fontes da ficha (cada uma falha sozinha, sem derrubar a ficha) ----------

def _fonte(disponivel: bool, mensagem: str = "") -> dict[str, Any]:
    return {"disponivel": disponivel, "mensagem": mensagem}


def _carregar_titulos(service: Any, filial: str, cliente: str, escopo: EscopoClientes) -> dict[str, Any]:
    try:
        rows = service.search_by_registration(filial, cliente, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=100)
    except Exception:
        return {"fonte": _fonte(False, "12.06.01 não importada ou indisponível."), "titulos": []}
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
        return {"fonte": _fonte(False, "Consulta de boletos não configurada."), "itens": []}
    try:
        status = service.status() if hasattr(service, "status") else {"ready": True}
        if not status.get("ready"):
            return {"fonte": _fonte(False, "03.02.06 não importada."), "itens": []}
        records = service.search_by_registration(
            filial=filial,
            cod_pdv=cliente,
            allowed_sectors=None,
            limit=20,
            include_pdf=False,
        )
    except Exception:
        return {"fonte": _fonte(False, "Base de boletos (03.02.06) indisponível."), "itens": []}
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
        return {"fonte": _fonte(False, "Consulta de comodatos não configurada."), "itens": [], "saldo_total": "0"}
    try:
        rows = service.search_by_registration(filial, cliente, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=200)
    except Exception:
        return {"fonte": _fonte(False, "02.02.20 não importada ou indisponível."), "itens": [], "saldo_total": "0"}
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


def _kpis(financeiro: Mapping[str, Any], boletos: Mapping[str, Any], comodatos: Mapping[str, Any]) -> dict[str, Any]:
    titulos = financeiro.get("titulos") or []
    total = sum((_decimal(t["valor_pendente"]) for t in titulos), Decimal("0"))
    vencidos = [t for t in titulos if t["situacao"] == "vencido"]
    total_vencido = sum((_decimal(t["valor_pendente"]) for t in vencidos), Decimal("0"))
    futuros = sorted((t for t in titulos if t["dias"] is not None and t["dias"] >= 0), key=lambda t: t["dias"])
    return {
        "titulos": len(titulos),
        "total_pendente": _dinheiro(total),
        "titulos_vencidos": len(vencidos),
        "total_vencido": _dinheiro(total_vencido),
        "proximo_vencimento": futuros[0]["vencimento"] if futuros else "",
        "boletos_disponiveis": len(boletos.get("itens") or []),
        "comodatos": len(comodatos.get("itens") or []),
        "saldo_material": comodatos.get("saldo_total") or "0",
    }


def _resumo_rapido(filial: str, cliente: str, escopo: EscopoClientes, inadimplencia: Any, boletos: Any | None) -> dict[str, Any]:
    resumo: dict[str, Any] = {"vencidos": None, "boletos": None}
    try:
        rows = inadimplencia.search_by_registration(filial, cliente, allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=100)
        resumo["vencidos"] = sum(1 for row in rows if situacao_vencimento(_inteiro(row.dias)) == "vencido")
    except Exception:
        pass
    if boletos is not None:
        try:
            resumo["boletos"] = len(boletos.search_by_registration(filial=filial, cod_pdv=cliente, allowed_sectors=None, limit=20, include_pdf=False))
        except Exception:
            pass
    return resumo


def _passa_filtros(item: Mapping[str, Any], filtros: Sequence[str]) -> bool:
    resumo = item.get("resumo") or {}
    for filtro in filtros:
        if filtro == "pendencia" and not item["tem_pendencia"]:
            return False
        if filtro == "comodato" and not item["tem_comodato"]:
            return False
        if filtro == "vencidos" and not (resumo.get("vencidos") or 0):
            return False
        if filtro == "boleto" and not (resumo.get("boletos") or 0):
            return False
    return True


def _filtros(valor: str | None) -> list[str]:
    pedidos = [item.strip().lower() for item in str(valor or "").split(",") if item.strip()]
    return [item for item in FILTROS_VALIDOS if item in pedidos]


def _cliente_payload(row: Any) -> dict[str, Any]:
    telefone = str(row.telefone or "")
    comodatos = _inteiro(row.total_comodatos_pendentes) or 0
    pendente = _decimal(row.total_pendente)
    return {
        "filial": normalize_numeric_code(str(row.filial)),
        "cliente": normalize_numeric_code(str(row.cod_pdv)),
        "nome": str(row.nome_fantasia or row.razao_social or ""),
        "razao_social": str(row.razao_social or ""),
        "cidade": str(row.cidade or ""),
        "telefone": telefone,
        "telefone_whatsapp": telefone_whatsapp(telefone),
        "telefone_discagem": telefone_discagem(telefone),
        "dia_visita": str(row.dia_visita or ""),
        "setor": str(row.vendedor or ""),
        "gv": str(getattr(row, "gv", "") or ""),
        "status": str(row.status or ""),
        "cond_pagto": str(row.cond_pag_atual or ""),
        "limite_credito": str(row.limite_credito or ""),
        "total_pendente": str(row.total_pendente or ""),
        "comodatos_pendentes": comodatos,
        "tem_pendencia": pendente > 0,
        "tem_comodato": comodatos > 0,
        "atualizado_em": str(row.ultima_atualizacao_tabela or ""),
    }


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
