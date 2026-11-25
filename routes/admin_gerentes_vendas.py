from __future__ import annotations

from typing import Any, Callable
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from bot_api.services.filial_labels import FILIAL_LABELS


class NomesRequest(BaseModel):
    nomes: dict[str, str]


def create_admin_gerentes_vendas_router(*, service: Any, require_admin_panel_auth: Callable[..., dict], record_admin_panel_action: Callable[..., None] | None = None) -> APIRouter:
    router = APIRouter()

    def admin(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> dict:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        if not context.get("is_admin"):
            raise HTTPException(status_code=403, detail="Apenas administradores podem gerenciar nomes de gerentes.")
        return context

    @router.get("/api/admin/gerentes-vendas")
    def listar(request: Request, authorization: str | None = Header(default=None), x_api_token: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)) -> dict:
        admin(request, authorization, x_api_token, x_admin_token)
        return {"ok": True, "gerentes": service.catalogo(), "filiais_nomes": dict(FILIAL_LABELS)}

    @router.put("/api/admin/gerentes-vendas")
    def salvar(payload: NomesRequest, request: Request, authorization: str | None = Header(default=None), x_api_token: str | None = Header(default=None), x_admin_token: str | None = Header(default=None)) -> dict:
        context = admin(request, authorization, x_api_token, x_admin_token)
        validas = {item["chave"] for item in service.catalogo()}
        if not set(payload.nomes).issubset(validas):
            raise HTTPException(status_code=422, detail="GV não encontrado na dSetores.")
        try:
            service.salvar(payload.nomes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if record_admin_panel_action:
            record_admin_panel_action(request=request, context=context, module="acessos", action="salvar_nomes_gerentes", metadata={"quantidade": len(payload.nomes)})
        return {"ok": True}

    return router
