"""Gerencial de pedidos: clientes bloqueados pela 12.06.01 e as liberações do administrador.

A lista vem da inadimplência importada (o mesmo dado que bloqueia a digitação). O
administrador libera um cliente por 1, 3 ou 7 dias com um motivo; a digitação
(``routes/admin_pedidos.py``) consulta a liberação antes de bloquear o pedido.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from bot_api.commercial_scope import FILIAL_SCOPE_PREFIX, normalize_numeric_code
from bot_api.services.filial_labels import FILIAL_LABELS
from bot_api.services.pedido_liberacoes_service import DIAS_PERMITIDOS, PedidoLiberacoesService, chave_cliente

POR_PAGINA = 30


class LiberacaoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filial: str = Field(min_length=1, max_length=8, pattern=r"^\d+$")
    cliente: str = Field(min_length=1, max_length=20, pattern=r"^\d+$")
    nome: str = Field(default="", max_length=120)
    motivo: str = Field(min_length=3, max_length=200)
    dias: int = Field(default=1)


def create_admin_pedidos_liberacoes_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    inadimplencia_query_service: Any,
    pedido_liberacoes_service: PedidoLiberacoesService,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def admin_context(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> dict[str, Any]:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        require_admin_panel_feature(context, "pedidos")
        if not bool(context.get("is_admin")):
            raise HTTPException(status_code=403, detail="A liberação de clientes bloqueados é exclusiva para administradores.")
        return context

    def record_action(request: Request, context: Mapping[str, Any], action: str, **metadata: Any) -> None:
        if record_admin_panel_action:
            record_admin_panel_action(request=request, context=context, module="pedidos", action=action, metadata=metadata)

    @router.get("/api/admin/pedidos/gerencial/bloqueados")
    def listar_bloqueados(
        request: Request,
        filial: str | None = Query(default=None, max_length=8),
        busca: str | None = Query(default=None, max_length=120),
        pagina: int = Query(default=1, ge=1, le=500),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        admin_context(request, authorization, x_api_token, x_admin_token)
        codigo_filial = normalize_numeric_code(filial or "")
        escopo = [f"{FILIAL_SCOPE_PREFIX}{codigo_filial}"] if codigo_filial else None
        termo = " ".join(str(busca or "").split())
        try:
            if termo.isdigit() and codigo_filial:
                titulos = inadimplencia_query_service.search_by_registration(codigo_filial, termo, limit=100)
                resumos = [_resumo_dos_titulos(titulos)] if titulos else []
                total = len(resumos)
            elif len(termo) >= 3:
                resumos = [
                    item for item in inadimplencia_query_service.search_client_summaries_by_name(termo, allowed_sectors=escopo, limit=30)
                    if not codigo_filial or normalize_numeric_code(item.filial) == codigo_filial
                ]
                total = len(resumos)
            else:
                total = inadimplencia_query_service.count_clients_in_scope(allowed_sectors=escopo)
                resumos = inadimplencia_query_service.list_client_summaries_in_scope(
                    allowed_sectors=escopo, limit=POR_PAGINA, offset=(pagina - 1) * POR_PAGINA
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="A inadimplência (12.06.01) não está disponível agora. Tente de novo em instantes.") from exc
        liberacoes = pedido_liberacoes_service.listar()
        clientes = [_cliente_bloqueado(item, liberacoes) for item in resumos]
        record_security_event(request, channel="api", event_type="admin_pedidos_bloqueados", decision="allowed", reason=f"filial={codigo_filial};total={total}")
        return {
            "ok": True,
            "clientes": clientes,
            "total": total,
            "pagina": pagina,
            "paginas": max(1, -(-total // POR_PAGINA)),
            "liberacoes": sorted(liberacoes.values(), key=lambda item: item.get("liberado_em", ""), reverse=True),
            "dias_permitidos": list(DIAS_PERMITIDOS),
            "filiais": [{"codigo": codigo, "nome": nome} for codigo, nome in sorted(FILIAL_LABELS.items(), key=lambda par: int(par[0]))],
        }

    @router.post("/api/admin/pedidos/gerencial/liberacoes", status_code=201)
    def liberar_cliente(
        request: Request,
        payload: LiberacaoRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = admin_context(request, authorization, x_api_token, x_admin_token)
        try:
            registro = pedido_liberacoes_service.liberar(
                payload.filial, payload.cliente, nome=payload.nome, motivo=payload.motivo, dias=payload.dias, actor=_quem(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_pedidos_liberacao", decision="allowed", reason=f"filial={registro['filial']};cliente={registro['cliente']};ate={registro['valida_ate']}")
        record_action(request, context, "liberar_cliente_bloqueado", filial=registro["filial"], cliente=registro["cliente"], motivo=registro["motivo"], valida_ate=registro["valida_ate"])
        return {"ok": True, "liberacao": registro}

    @router.delete("/api/admin/pedidos/gerencial/liberacoes/{filial}/{cliente}")
    def revogar_liberacao(
        request: Request,
        filial: str,
        cliente: str,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = admin_context(request, authorization, x_api_token, x_admin_token)
        try:
            chave = chave_cliente(filial, cliente)
            existia = pedido_liberacoes_service.revogar(filial, cliente)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not existia:
            raise HTTPException(status_code=404, detail="Este cliente não tem liberação ativa.")
        record_security_event(request, channel="api", event_type="admin_pedidos_liberacao_revogada", decision="allowed", reason=f"cliente={chave}")
        record_action(request, context, "revogar_liberacao_cliente", filial=chave.split("_")[0], cliente=chave.split("_")[1])
        return {"ok": True}

    return router


def _quem(context: Mapping[str, Any]) -> str:
    return str(context.get("username") or context.get("user_id") or "admin")


def _resumo_dos_titulos(titulos: list[Any]) -> Any:
    """Um cliente achado pelo NB vira o mesmo formato da lista (soma dos títulos)."""
    total = 0.0
    for item in titulos:
        texto = str(item.valor_pendente or "0").replace(".", "").replace(",", ".")
        try:
            total += float(texto)
        except ValueError:
            continue
    primeiro = titulos[0]
    return SimpleNamespace(
        filial=primeiro.filial, cod_pdv=primeiro.cod_pdv, nome=primeiro.nome,
        title_count=len(titulos), total_pendente=f"{total:.2f}".replace(".", ","),
    )


def _cliente_bloqueado(item: Any, liberacoes: Mapping[str, dict]) -> dict[str, Any]:
    filial = normalize_numeric_code(str(item.filial or ""))
    cliente = normalize_numeric_code(str(item.cod_pdv or ""))
    return {
        "filial": filial,
        "filial_nome": FILIAL_LABELS.get(filial, ""),
        "cliente": cliente,
        "nome": str(item.nome or ""),
        "titulos": int(item.title_count or 0),
        "total_pendente": str(item.total_pendente or "0,00"),
        "liberacao": liberacoes.get(f"{filial}_{cliente}"),
    }
