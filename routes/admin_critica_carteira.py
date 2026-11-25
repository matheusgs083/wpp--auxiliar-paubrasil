"""Aba "Gerar crítica" (área Vendedor): PDF da crítica da carteira do usuário.

O usuário escolhe a filial e baixa a crítica de um setor, da carteira inteira ou o
resumo de um GV; o PDF sai com o mesmo recorte da carteira (``services/clientes_escopo.py``):
vendedor só vê os próprios setores, gerente os setores do GV, operações as filiais
marcadas e administrador tudo. A crítica do GV só sai para quem responde pelo GV
(gerente, operações ou administrador), nunca para o vendedor de um setor dele.
A geração da crítica no Cora (worker) fica na aba Crítica, não aqui.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from bot_api.commercial_scope import FILIAL_SCOPE_PREFIX, normalize_numeric_code, normalize_sector_scope_input
from bot_api.services.clientes_escopo import EscopoClientes, escopo_do_contexto
from bot_api.services.filial_labels import FILIAL_LABELS

FEATURE_CRITICA_CARTEIRA = "gerar_critica"


def create_admin_critica_carteira_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    dclientes_query_service: Any,
    critica_rn_query_service: Any,
    gerentes_vendas_service: Any | None = None,
    parse_admin_critica_date: Callable[[str | None], date | None],
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def autenticar(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> tuple[dict[str, Any], EscopoClientes]:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        require_admin_panel_feature(context, FEATURE_CRITICA_CARTEIRA)
        return context, escopo_do_contexto(context)

    def setores_da_filial(escopo: EscopoClientes, filial: str) -> list[dict[str, str]]:
        allowed_sectors, allowed_gv_vdes = escopo_na_filial(escopo, filial)
        try:
            combinacoes = dclientes_query_service.list_seller_base_summaries(allowed_sectors=allowed_sectors, allowed_gv_vdes=allowed_gv_vdes, limit=200)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Cadastro de clientes indisponível no momento. Tente de novo em instantes.") from exc
        setores: dict[str, dict[str, str]] = {}
        for item in combinacoes:
            chave = normalize_sector_scope_input(str(item.seller_code or ""))
            if not chave or chave.split("_", 1)[0] != filial:
                continue
            gv = str(item.manager_code or "")
            setores.setdefault(chave, {"setor": chave, "codigo": chave.split("_", 1)[1], "gv": "" if gv == "-" else gv.split("_", 1)[-1]})
        return sorted(setores.values(), key=lambda s: int(s["codigo"]) if s["codigo"].isdigit() else 0)

    @router.get("/api/admin/critica/carteira/opcoes")
    def opcoes_critica_carteira(
        request: Request,
        filial: str | None = Query(default=None, max_length=8),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _context, escopo = autenticar(request, authorization, x_api_token, x_admin_token)
        filiais = filiais_do_escopo(escopo)
        escolhida = normalize_numeric_code(filial or "") or (filiais[0] if len(filiais) == 1 else "")
        if escolhida and escolhida not in filiais:
            raise HTTPException(status_code=403, detail="Filial fora da sua carteira.")
        setores = setores_da_filial(escopo, escolhida) if escolhida else []
        gvs = gvs_liberados(escopo, escolhida, setores) if escolhida else []
        nomes_gvs = gerentes_vendas_service.nomes() if gerentes_vendas_service is not None else {}
        ultima_data = ultima_critica(escopo, escolhida) if escolhida else None
        record_security_event(request, channel="api", event_type="admin_critica_carteira_opcoes", decision="allowed", reason=f"filial={escolhida};setores={len(setores)}")
        return {
            "ok": True,
            "escopo": escopo.descricao(),
            "filiais": [{"codigo": codigo, "nome": FILIAL_LABELS.get(codigo, "") or f"Filial {codigo}"} for codigo in filiais],
            "filial": escolhida,
            "setores": setores,
            # Data que sai quando o usuário não escolhe uma: a tela mostra antes do download.
            "ultima_data": ultima_data.isoformat() if ultima_data else "",
            "gvs": [{"gv": gv, "nome": nomes_gvs.get(f"{escolhida}_{gv}") or ("Tratamento" if gv == "99" else ""), "setores": sum(1 for s in setores if s["gv"] == gv)} for gv in gvs],
            # Quem tem a filial inteira pode baixar a crítica de todos os setores de uma vez.
            "pode_filial_inteira": escopo.irrestrito or bool(escopo.filiais),
        }

    def ultima_critica(escopo: EscopoClientes, filial: str) -> date | None:
        allowed_sectors, allowed_gv_vdes = escopo_na_filial(escopo, filial)
        try:
            return critica_rn_query_service.latest_date(allowed_sectors=allowed_sectors, allowed_gv_vdes=allowed_gv_vdes)
        except RuntimeError:
            return None  # sem a data a tela só não mostra o aviso; o download continua funcionando

    @router.get("/api/admin/critica/carteira/pdf")
    def pdf_critica_carteira(
        request: Request,
        filial: str = Query(min_length=1, max_length=8),
        setor: str | None = Query(default=None, max_length=20),
        gv: str | None = Query(default=None, max_length=20),
        date_value: str | None = Query(default=None, alias="date"),
        summary_only: bool = Query(default=False),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        context, escopo = autenticar(request, authorization, x_api_token, x_admin_token)
        codigo_filial = normalize_numeric_code(filial)
        if codigo_filial not in filiais_do_escopo(escopo):
            raise HTTPException(status_code=403, detail="Filial fora da sua carteira.")
        chave_setor = normalize_sector_scope_input(f"{codigo_filial}_{setor}") if setor and "_" not in setor else normalize_sector_scope_input(setor or "")
        codigo_gv = normalize_numeric_code((gv or "").split("_")[-1])
        if gv and (setor or not codigo_gv):
            raise HTTPException(status_code=422, detail="Escolha o GV ou o setor, não os dois.")
        if setor and not chave_setor:
            raise HTTPException(status_code=422, detail="Setor inválido.")
        if codigo_gv:
            if codigo_gv not in gvs_liberados(escopo, codigo_filial, setores_da_filial(escopo, codigo_filial)):
                raise HTTPException(status_code=403, detail="GV fora da sua carteira.")
            allowed_sectors, allowed_gv_vdes = None, [f"{codigo_filial}_{codigo_gv}"]
        elif chave_setor:
            if chave_setor.split("_", 1)[0] != codigo_filial:
                raise HTTPException(status_code=422, detail="O setor escolhido é de outra filial.")
            if chave_setor not in {item["setor"] for item in setores_da_filial(escopo, codigo_filial)}:
                raise HTTPException(status_code=403, detail="Setor fora da sua carteira.")
            allowed_sectors, allowed_gv_vdes = [chave_setor], None
        else:
            allowed_sectors, allowed_gv_vdes = escopo_na_filial(escopo, codigo_filial)

        target_date = parse_admin_critica_date(date_value)
        try:
            effective_date = target_date or critica_rn_query_service.latest_date(allowed_sectors=allowed_sectors, allowed_gv_vdes=allowed_gv_vdes)
            if effective_date is None:
                raise HTTPException(status_code=404, detail="Ainda não há crítica para essa seleção.")
            if codigo_gv:
                # Crítica do GV: um PDF próprio, com o resumo por setor do gerente.
                report = critica_rn_query_service.get_gv_summary_pdf(target_date=effective_date, allowed_gv_vdes=allowed_gv_vdes)
            else:
                report = critica_rn_query_service.get_pdf_report(
                    target_date=effective_date,
                    allowed_sectors=allowed_sectors,
                    allowed_gv_vdes=allowed_gv_vdes,
                    limit=5000 if chave_setor else 50000,
                )
        except RuntimeError as exc:
            # Inclui a crítica ainda sem importação atual (o PDF não sai pela metade).
            raise HTTPException(status_code=409, detail=str(exc) or "A crítica desse dia ainda não está pronta.") from exc
        pdf_bytes = report.summary_pdf_bytes if summary_only and not codigo_gv else report.pdf_bytes
        if not pdf_bytes:
            raise HTTPException(status_code=404, detail=f"Não há crítica para essa seleção em {effective_date.strftime('%d/%m/%Y')}.")

        recorte = f"gv-{codigo_gv}" if codigo_gv else (f"setor-{chave_setor.split('_', 1)[1]}" if chave_setor else "carteira")
        nome = f"critica-{codigo_filial}-{recorte}-{effective_date.isoformat()}{'-resumo' if summary_only and not codigo_gv else ''}.pdf"
        record_security_event(request, channel="api", event_type="admin_critica_carteira_pdf", decision="allowed", reason=f"filial={codigo_filial};setor={chave_setor};gv={codigo_gv};summary={int(summary_only)}")
        if record_admin_panel_action is not None:
            record_admin_panel_action(
                request=request,
                context=context,
                module="critica",
                action="pdf_carteira",
                target_type="critica",
                target_id=(f"{codigo_filial}_gv{codigo_gv}" if codigo_gv else chave_setor) or codigo_filial,
                metadata={"date": effective_date.isoformat(), "summary_only": summary_only},
            )
        return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    return router


def filiais_do_escopo(escopo: EscopoClientes) -> list[str]:
    """Filiais em que o usuário tem carteira (todas as da dRevendas para quem é irrestrito)."""
    alcancadas = escopo.filiais_alcancadas()
    codigos = set(FILIAL_LABELS) if alcancadas is None else alcancadas
    return sorted((c for c in codigos if c), key=lambda c: int(c) if c.isdigit() else 0)


def gvs_liberados(escopo: EscopoClientes, filial: str, setores: list[dict[str, str]]) -> list[str]:
    """GVs cuja crítica o usuário pode baixar: todos da filial para quem tem a filial; o próprio para o gerente."""
    if escopo.irrestrito or filial in escopo.filiais:
        codigos = {s["gv"] for s in setores if s["gv"]}
    else:
        codigos = {chave.split("_", 1)[1] for chave in escopo.gvs if chave.split("_", 1)[0] == filial}
    return sorted(codigos, key=lambda c: int(c) if c.isdigit() else 0)


def escopo_na_filial(escopo: EscopoClientes, filial: str) -> tuple[list[str] | None, list[str] | None]:
    """Recorte da carteira dentro de uma filial, no formato que as consultas aceitam."""
    if escopo.irrestrito or filial in escopo.filiais:
        return [f"{FILIAL_SCOPE_PREFIX}{filial}"], None
    setores = [chave for chave in escopo.setores if chave.split("_", 1)[0] == filial]
    gvs = [chave for chave in escopo.gvs if chave.split("_", 1)[0] == filial]
    if not setores and not gvs:
        raise HTTPException(status_code=403, detail="Filial fora da sua carteira.")
    return setores or None, gvs or None
