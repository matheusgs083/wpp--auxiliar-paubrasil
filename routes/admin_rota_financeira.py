"""Aba Rota Financeira: fila do dia de visita priorizada pelo risco financeiro.

Escopo: o mesmo da aba Clientes (``services/clientes_escopo.py``). Os filtros da
tela (filial, GV, setor, busca) só estreitam o que o escopo já liberou.
O detalhe, a linha digitável e o PDF do boleto usam os endpoints da aba Clientes,
que validam o escopo de novo a cada chamada e aceitam a permissão de Clientes ou
de Rota Financeira.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query, Request

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.clientes_escopo import EscopoClientes, escopo_do_contexto, telefone_discagem, telefone_whatsapp
from bot_api.services.filial_labels import FILIAL_LABELS
from bot_api.services.rota_financeira_giro import SITUACOES_GIRO, ctes_giro
from bot_api.services.rota_financeira_query_service import SITUACOES
from bot_api.services.gerentes_vendas_service import agrupar_gerentes

FEATURE_ROTA_FINANCEIRA = "rota_financeira"
TAMANHO_PAGINA = 25


def create_admin_rota_financeira_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    dclientes_query_service: Any,
    inadimplencia_query_service: Any,
    boletos_query_service: Any | None,
    rota_financeira_query_service: Any,
    gerentes_vendas_service: Any | None = None,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
    giro_vasilhame_service: Any | None = None,
    agora: Callable[[], datetime] = lambda: datetime.now(ZoneInfo("America/Fortaleza")),
) -> APIRouter:
    router = APIRouter()

    def autenticar(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> tuple[dict[str, Any], EscopoClientes]:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        require_admin_panel_feature(context, FEATURE_ROTA_FINANCEIRA)
        return context, escopo_do_contexto(context)

    @router.get("/api/admin/rota-financeira/opcoes")
    def opcoes_rota(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _context, escopo = autenticar(request, authorization, x_api_token, x_admin_token)
        try:
            dias = dclientes_query_service.list_visit_days(allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=20)
            combinacoes = dclientes_query_service.list_seller_base_summaries(allowed_sectors=escopo.allowed_sectors, allowed_gv_vdes=escopo.allowed_gv_vdes, limit=10000)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Cadastro de clientes indisponível no momento. Tente de novo em instantes.") from exc
        setores: list[dict[str, str]] = []
        for item in combinacoes:
            setor = str(item.seller_code or "")
            gv = str(item.manager_code or "")
            filial = normalize_numeric_code(setor.split("_", 1)[0]) if "_" in setor else ""
            if not setor or setor == "-" or not escopo.permite_filial(filial):
                continue
            setores.append({"setor": setor, "gv": "" if gv == "-" else gv, "filial": filial})
        filiais = sorted({item["filial"] for item in setores if item["filial"]}, key=lambda f: int(f))
        gvs = sorted({item["gv"] for item in setores if item["gv"]})
        nomes_gvs = gerentes_vendas_service.nomes() if gerentes_vendas_service is not None else {}
        record_security_event(request, channel="api", event_type="admin_rota_financeira_opcoes", decision="allowed", reason=f"setores={len(setores)}")
        return {
            "ok": True,
            "escopo": escopo.descricao(),
            "dias": list(dias),
            "dia_sugerido": _dia_de_hoje(dias),
            "filiais": filiais,
            # Nome de cada revenda vem da dRevendas (FILIAL_LABELS é recarregado dela).
            "filiais_nomes": {filial: FILIAL_LABELS.get(filial, "") for filial in filiais},
            "gvs": gvs,
            "gerentes": agrupar_gerentes(gvs, nomes_gvs),
            "mostrar_gv": len(gvs) > 1,
            "setores": setores,
            "situacoes": list(SITUACOES),
        }

    @router.get("/api/admin/rota-financeira")
    def listar_rota(
        request: Request,
        dia: str = Query(min_length=2, max_length=40),
        filial: str | None = Query(default=None, max_length=8),
        gv: str | None = Query(default=None, max_length=2000),
        setor: str | None = Query(default=None, max_length=20),
        busca: str | None = Query(default=None, max_length=120),
        situacao: str = Query(default="todos", max_length=20),
        pagina: int = Query(default=1, ge=1, le=400),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context, escopo = autenticar(request, authorization, x_api_token, x_admin_token)
        if situacao not in SITUACOES:
            raise HTTPException(status_code=422, detail="Filtro de situação inválido.")
        if filial and not escopo.permite_filial(filial):
            # Filial fora do escopo: devolve vazio, sem dizer se existe alguém lá.
            return _pagina_vazia(escopo, pagina)

        fontes = _fontes(inadimplencia_query_service, boletos_query_service)
        if not fontes["inadimplencia"]["disponivel"]:
            raise HTTPException(status_code=503, detail="Os títulos em aberto estão indisponíveis agora, então a rota não pode ser montada. Tente de novo em instantes.")
        incluir_boletos = fontes["boletos"]["disponivel"]
        if situacao in {"com_boleto", "sem_boleto"} and not incluir_boletos:
            raise HTTPException(status_code=409, detail="Os boletos estão indisponíveis agora, então não dá para filtrar por boleto.")

        giro = None
        if situacao in SITUACOES_GIRO:
            giro = _giro_do_mes(giro_vasilhame_service, getattr(rota_financeira_query_service, "schema", "reports"), agora())

        try:
            resultado = rota_financeira_query_service.listar(
                dia=dia,
                allowed_sectors=escopo.allowed_sectors,
                allowed_gv_vdes=escopo.allowed_gv_vdes,
                filial=filial or "",
                gv=gv or "",
                setor=setor or "",
                busca=busca or "",
                situacao=situacao,
                incluir_boletos=incluir_boletos,
                giro=giro,
                limite=TAMANHO_PAGINA,
                offset=(pagina - 1) * TAMANHO_PAGINA,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Não foi possível montar a rota agora. Tente de novo em instantes.") from exc
        except Exception as exc:
            if giro is None:
                raise
            raise HTTPException(status_code=503, detail="O giro está indisponível agora. Tente de novo em instantes.") from exc

        nomes_gvs = gerentes_vendas_service.nomes() if gerentes_vendas_service is not None else {}
        clientes = [_cliente_da_rota(item, incluir_boletos) for item in resultado.clientes]
        for item in clientes:
            chave = str(item.get("gv") or "")
            item["gerente_nome"] = nomes_gvs.get(chave) or ("Tratamento" if chave.endswith("_99") else "")
        record_security_event(request, channel="api", event_type="admin_rota_financeira_lista", decision="allowed", reason=f"dia={dia};situacao={situacao};pagina={pagina};total={resultado.total}")
        if record_admin_panel_action and pagina == 1:
            record_admin_panel_action(request=request, context=context, module="rota_financeira", action="consultar_rota", metadata={"dia": dia, "situacao": situacao, "total": resultado.total})
        return {
            "ok": True,
            "escopo": escopo.descricao(),
            "fontes": fontes,
            "resumo": resultado.resumo,
            "clientes": clientes,
            "total": resultado.total,
            "pagina": pagina,
            "por_pagina": TAMANHO_PAGINA,
            "paginas": max(1, -(-resultado.total // TAMANHO_PAGINA)),
        }

    return router


def _giro_do_mes(giro_vasilhame_service: Any | None, schema: str, agora: datetime) -> tuple[Any, list[Any]]:
    """CTEs dos filtros "sem giro" do mês atual; a tabela de garrafeiras vem do serviço do giro."""
    if giro_vasilhame_service is None:
        raise HTTPException(status_code=409, detail="O giro está indisponível agora.")
    try:
        catalogo = giro_vasilhame_service.catalogo()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="O giro está indisponível agora. Tente de novo em instantes.") from exc
    return ctes_giro(schema, f"{agora.year:04d}-{agora.month:02d}", catalogo)


def _pagina_vazia(escopo: EscopoClientes, pagina: int) -> dict[str, Any]:
    return {"ok": True, "escopo": escopo.descricao(), "fontes": {}, "resumo": {}, "clientes": [], "total": 0, "pagina": pagina, "por_pagina": TAMANHO_PAGINA, "paginas": 1}


def _fontes(inadimplencia: Any, boletos: Any | None) -> dict[str, dict[str, Any]]:
    def pronto(service: Any | None) -> bool:
        if service is None:
            return False
        try:
            return bool(service.status().get("ready"))
        except Exception:
            return False

    inad_ok = pronto(inadimplencia)
    bol_ok = pronto(boletos)
    return {
        "inadimplencia": {"disponivel": inad_ok, "mensagem": "" if inad_ok else "Títulos em aberto indisponíveis agora."},
        "boletos": {"disponivel": bol_ok, "mensagem": "" if bol_ok else "Boletos indisponíveis agora: os títulos aparecem, mas sem boleto."},
    }


def situacao_rotulo(item: Mapping[str, Any]) -> dict[str, str]:
    """Texto da situação do cliente (sempre escrito, nunca só cor)."""
    if not item.get("titulos"):
        return {"chave": "sem_titulo", "texto": "Sem títulos em aberto", "tom": "neutral"}
    dias = item.get("menor_dias")
    if dias is None:
        return {"chave": "a_vencer", "texto": "Sem data de vencimento", "tom": "neutral"}
    if dias < 0:
        return {"chave": "vencidos", "texto": f"Vencido há {-dias} dia{'s' if dias < -1 else ''}", "tom": "err"}
    if dias == 0:
        return {"chave": "hoje", "texto": "Vence hoje", "tom": "warn"}
    if dias == 1:
        return {"chave": "amanha", "texto": "Vence amanhã", "tom": "warn"}
    return {"chave": "a_vencer", "texto": f"Vence em {dias} dias", "tom": "info" if dias == 2 else "ok"}


def boleto_rotulo(item: Mapping[str, Any], boletos_disponiveis: bool) -> dict[str, str]:
    if not item.get("titulos"):
        return {"texto": "Sem título", "tom": "neutral"}
    if not boletos_disponiveis:
        return {"texto": "Boleto indisponível", "tom": "neutral"}
    if item.get("boletos"):
        return {"texto": f"Boleto disponível ({item['boletos']})", "tom": "info"}
    return {"texto": "Sem boleto", "tom": "neutral"}


def _cliente_da_rota(item: Mapping[str, Any], boletos_disponiveis: bool) -> dict[str, Any]:
    return {
        **item,
        "filial_nome": FILIAL_LABELS.get(str(item.get("filial") or ""), ""),
        "prioridade": item.get("faixa"),
        "situacao": situacao_rotulo(item),
        "boleto": boleto_rotulo(item, boletos_disponiveis),
        "telefone_whatsapp": telefone_whatsapp(str(item.get("telefone") or "")),
        "telefone_discagem": telefone_discagem(str(item.get("telefone") or "")),
    }


_DIAS_SEMANA = ("SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM")


def _dia_de_hoje(dias: list[str]) -> str:
    hoje = _DIAS_SEMANA[datetime.now(ZoneInfo("America/Fortaleza")).weekday()]
    for dia in dias:
        normalizado = dia.upper().replace("Á", "A").replace("Ç", "C")
        if normalizado.startswith(hoje):
            return dia
    return dias[0] if dias else ""
