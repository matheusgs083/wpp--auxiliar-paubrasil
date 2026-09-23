
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from bot_api.services.liga_entrega_dashboard_service import LigaEntregaDashboardService


LIGA_ENTREGA_REPORTS = (
    {"routine": "030805_LIGA", "code": "03.08.05", "label": "Rotas do dia", "kind": "Diario"},
    {"routine": "031120_BOT", "code": "03.11.20", "label": "Portaria", "kind": "Mensal"},
    {"routine": "030224_MOTORISTA_LIGA", "code": "03.02.24", "label": "Devolucoes por motorista", "kind": "Mensal"},
    {"routine": "030224_AJUDANTE_LIGA", "code": "03.02.24", "label": "Devolucoes por ajudante", "kind": "Mensal"},
    {"routine": "030237", "code": "03.02.37", "label": "Entregas", "kind": "Mensal"},
    {"routine": "03114902_BOT", "code": "03.11.49.02", "label": "Cidades por mapa", "kind": "Mensal"},
    {"routine": "031129_LIGA", "code": "03.11.29", "label": "Equipe do dia por mapa", "kind": "Mensal"},
    {"routine": "PONTOMAIS_ESPELHO", "code": "PONTO", "label": "Espelho de ponto", "kind": "Mensal"},
    {"routine": "CHECKLIST_FROTA", "code": "XLSX", "label": "Checklist Frota", "kind": "Mensal"},
)


class LigaEntregaExpurgoRequest(BaseModel):
    tipo: str = Field(..., description="devolucao, km, tml ou dispersao")
    competencia: str = Field(..., description="AAAA-MM")
    filial: str = ""
    data: str = ""
    mapa: str = ""
    cliente: str = ""
    motivo: str = ""
    observacao: str = ""
    active: bool = True


class LigaEntregaStatusRequest(BaseModel):
    competencia: str = Field(..., description="AAAA-MM")
    status: str = Field(..., description="ativo, ferias, afastado ou desligado")


def create_admin_liga_entrega_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    liga_entrega_expurgo_service: Any,
    liga_entrega_status_service: Any | None = None,
    liga_entrega_report_store: Any | None = None,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def require_liga_context(
        *,
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
        x_admin_token: str | None,
    ) -> dict[str, Any]:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "reports")
        return context

    def actor_from_context(context: dict[str, Any] | None) -> str:
        if not context:
            return ""
        if context.get("is_admin"):
            return "admin"
        mode = str(context.get("mode") or "").strip()
        user_id = str(context.get("user_id") or context.get("phone") or "").strip()
        return f"{mode}:{user_id}" if user_id else mode

    def record_panel_action(
        request: Request,
        context: dict[str, Any] | None,
        *,
        action: str,
        target_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if record_admin_panel_action is None:
            return
        record_admin_panel_action(
            request=request,
            context=context,
            module="liga_entrega",
            action=action,
            target_type="expurgo",
            target_id=target_id,
            metadata=metadata or {},
        )


    @router.get("/api/admin/liga-entrega/relatorios")
    def api_admin_liga_entrega_relatorios(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        items: list[dict[str, Any]] = []
        loaded = 0
        for spec in LIGA_ENTREGA_REPORTS:
            manifest = None
            if liga_entrega_report_store is not None:
                try:
                    manifest = liga_entrega_report_store.latest_manifest(str(spec["routine"]))
                except ValueError:
                    manifest = None
            if manifest:
                loaded += 1
            items.append(
                {
                    **spec,
                    "loaded": bool(manifest),
                    "manifest": manifest,
                }
            )
        loaded_items = [item for item in items if item.get("loaded")]
        latest_stored_at = max(
            (str((item.get("manifest") or {}).get("stored_at") or "") for item in loaded_items),
            default="",
        )
        latest_reference_date = max(
            (str((item.get("manifest") or {}).get("reference_date") or "") for item in loaded_items),
            default="",
        )
        total_files = sum(
            int((item.get("manifest") or {}).get("file_count") or 0)
            for item in loaded_items
        )
        result = {
            "ok": True,
            "items": items,
            "summary": {
                "total": len(items),
                "loaded": loaded,
                "missing": len(items) - loaded,
                "ready": loaded == len(items),
                "total_files": total_files,
                "latest_reference_date": latest_reference_date,
                "latest_stored_at": latest_stored_at,
            },
        }
        record_security_event(
            request,
            channel="api",
            event_type="admin_liga_relatorios_list",
            decision="allowed",
            reason=f"loaded={loaded}",
        )
        return result

    @router.get("/api/admin/liga-entrega/dashboard")
    def api_admin_liga_entrega_dashboard(
        request: Request,
        competencia: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        if liga_entrega_report_store is None:
            raise HTTPException(status_code=503, detail="Armazenamento da Liga Entrega indisponivel.")
        try:
            result = LigaEntregaDashboardService(
                report_store=liga_entrega_report_store,
                expurgo_service=liga_entrega_expurgo_service,
                status_service=liga_entrega_status_service,
            ).build_dashboard(competencia=competencia)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        record_security_event(
            request,
            channel="api",
            event_type="admin_liga_dashboard",
            decision="allowed",
            reason=f"rotas={summary.get('rotas', 0)}",
        )
        return result

    @router.get("/api/admin/liga-entrega/expurgos")
    def api_admin_liga_entrega_expurgos(
        request: Request,
        competencia: str | None = Query(default=None),
        tipo: str | None = Query(default=None),
        active_only: bool = Query(default=True),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            result = liga_entrega_expurgo_service.list_expurgos(
                competencia=competencia,
                tipo=tipo,
                active_only=active_only,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_liga_expurgos_list", decision="allowed", reason=f"total={result.get('total')}")
        return {"ok": True, **result}

    @router.post("/api/admin/liga-entrega/expurgos")
    def api_admin_liga_entrega_expurgo_upsert(
        request: Request,
        payload: LigaEntregaExpurgoRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            item = liga_entrega_expurgo_service.upsert_expurgo(
                payload.model_dump(),
                actor=actor_from_context(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_liga_expurgo_upsert", decision="allowed", reason=str(item.get("id") or ""))
        record_panel_action(request, context, action="salvar_expurgo", target_id=str(item.get("id") or ""), metadata={"tipo": item.get("tipo"), "competencia": item.get("competencia")})
        return {"ok": True, "item": item}

    @router.put("/api/admin/liga-entrega/equipe/{cod}")
    def api_admin_liga_entrega_equipe_status(
        cod: str,
        request: Request,
        payload: LigaEntregaStatusRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_liga_context(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        if liga_entrega_status_service is None:
            raise HTTPException(status_code=503, detail="Status da equipe indisponível.")
        try:
            item = liga_entrega_status_service.set_status(competencia=payload.competencia, cod=cod, status=payload.status, actor=actor_from_context(context))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_liga_equipe_status", decision="allowed", reason=str(item.get("cod") or ""))
        record_panel_action(request, context, action="salvar_status_equipe", target_id=str(item.get("cod") or ""), metadata=item)
        return {"ok": True, "item": item}

    @router.delete("/api/admin/liga-entrega/expurgos/{expurgo_id}")
    def api_admin_liga_entrega_expurgo_delete(
        expurgo_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_liga_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        try:
            item = liga_entrega_expurgo_service.delete_expurgo(expurgo_id, actor=actor_from_context(context))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_liga_expurgo_delete", decision="allowed", reason=str(item.get("id") or expurgo_id))
        record_panel_action(request, context, action="remover_expurgo", target_id=str(item.get("id") or expurgo_id), metadata={"tipo": item.get("tipo"), "competencia": item.get("competencia")})
        return {"ok": True, "item": item}

    return router
