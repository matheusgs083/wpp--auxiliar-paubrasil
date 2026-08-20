from __future__ import annotations

from collections.abc import Callable
from datetime import date
from secrets import compare_digest
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field


PROMAX_UNIT_BY_FILIAL = {
    "1": "0640001",
    "2": "0640002",
    "3": "2210003",
    "4": "2210004",
    "5": "3480005",
    "6": "3610006",
    "7": "3610007",
    "8": "3610008",
}


class AdminFinanceiroMapaRequest(BaseModel):
    data: str
    filial: str = ""
    tipo_bloco: str = "mapa"
    mapa: str = ""
    mapa_ref: str = ""
    motorista: str = ""
    boletos_rota: Any = 0
    boletos_recebido_qtd: Any = 0
    total_promax: Any = 0
    credito_conta: Any = 0
    dinheiro: dict[str, Any] = Field(default_factory=dict)
    moedas: Any = 0
    diarista: Any = 0
    diarista_recibo_recebido: Any = True
    diaristas: list[dict[str, Any]] = Field(default_factory=list)
    pernoite: Any = 0
    hospedagem: Any = 0
    janta: Any = 0
    almoco: Any = 0
    cafe: Any = 0
    transferencias: list[dict[str, Any]] = Field(default_factory=list)
    despesas: list[dict[str, Any]] = Field(default_factory=list)
    vales: list[dict[str, Any]] = Field(default_factory=list)
    observacao: str = ""


class AdminFinanceiroFechamentoRequest(BaseModel):
    data: str
    filial: str
    mapa: str = Field(min_length=1, max_length=40)
    modo: str = "completo"
    ponto_apoio: str = "0"
    km_atual: str = ""
    target_worker_id: str = Field(default="", max_length=120)


class InternalFinanceiroFechamentoSyncRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    data: str
    filial: str
    mapa: str = Field(min_length=1, max_length=40)
    result: dict[str, Any] = Field(default_factory=dict)


def create_admin_financeiro_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    list_financeiro_caixa: Callable[..., dict[str, Any]],
    upsert_financeiro_mapa: Callable[..., dict[str, Any]],
    export_financeiro_caixa_pdf: Callable[..., tuple[bytes, str]],
    sync_financeiro_fechamento_promax: Callable[..., dict[str, Any]],
    enqueue_promax_job: Callable[..., Any],
    list_promax_worker_heartbeats: Callable[..., list[dict[str, Any]]],
    delete_financeiro_mapa: Callable[..., dict[str, Any]],
    worker_token: str | None,
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()
    expected_worker_token = worker_token.strip() if isinstance(worker_token, str) else ""

    def require_financeiro_context(
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
        require_admin_panel_feature(context, "financeiro")
        return context

    def require_worker_auth(
        request: Request,
        x_promax_worker_token: str | None = Header(default=None, alias="x-promax-worker-token"),
    ) -> None:
        if not expected_worker_token:
            record_security_event(
                request,
                channel="api",
                event_type="promax_financeiro_worker_auth",
                decision="denied",
                reason="worker_token_not_configured",
            )
            raise HTTPException(status_code=503, detail="Token do worker Promax nao configurado.")
        if not x_promax_worker_token or not compare_digest(x_promax_worker_token, expected_worker_token):
            record_security_event(
                request,
                channel="api",
                event_type="promax_financeiro_worker_auth",
                decision="denied",
                reason="invalid_worker_token",
            )
            raise HTTPException(status_code=401, detail="Worker Promax nao autorizado.")

    @router.get("/api/admin/financeiro/caixas")
    def api_admin_financeiro_caixa(
        request: Request,
        data: str,
        filial: str = "",
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_financeiro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        payload = list_financeiro_caixa(data=data, filial=filial, context=context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_list",
            decision="allowed",
            reason=f"data={data}; filial={filial}",
        )
        return payload

    @router.get("/api/admin/financeiro/worker/status")
    def api_admin_financeiro_worker_status(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_financeiro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        workers = list_promax_worker_heartbeats()
        fechamento_workers = [
            worker for worker in workers
            if "fechamento" in str(worker.get("worker_id") or "").strip().lower()
        ]
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_worker_status",
            decision="allowed",
            reason="financeiro_worker_status",
        )
        return {
            "workers": workers,
            "fechamento_workers": fechamento_workers,
            "fechamento_online": any(bool(worker.get("online")) for worker in fechamento_workers),
        }

    @router.get("/api/admin/financeiro/caixa/pdf")
    def api_admin_financeiro_caixa_pdf(
        request: Request,
        data: str,
        filial: str = "",
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        context = require_financeiro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        pdf_bytes, filename = export_financeiro_caixa_pdf(data=data, filial=filial, context=context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_pdf",
            decision="allowed",
            reason=f"data={data}; filial={filial}",
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/api/admin/financeiro/mapas")
    def api_admin_financeiro_mapa_save(
        payload: AdminFinanceiroMapaRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_financeiro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = upsert_financeiro_mapa(payload.model_dump(), context=context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_save",
            decision="allowed",
            reason=f"mapa={payload.mapa}; filial={payload.filial}",
        )
        return result

    @router.post("/api/admin/financeiro/fechamento-promax", status_code=202)
    def api_admin_financeiro_fechamento_promax(
        payload: AdminFinanceiroFechamentoRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_financeiro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        clean_filial = str(payload.filial or "").strip()
        clean_mapa = str(payload.mapa or "").strip()
        clean_modo = str(payload.modo or "completo").strip().lower()
        if clean_modo not in {"completo", "fisico", "financeiro"}:
            raise HTTPException(status_code=400, detail="Modo de fechamento invalido.")
        clean_km_atual = str(payload.km_atual or "").strip()
        if clean_km_atual:
            clean_km_atual = clean_km_atual.replace(".", "").replace(",", "")
            if not clean_km_atual.isdigit():
                raise HTTPException(status_code=400, detail="KM atual deve conter apenas numeros.")
        clean_target_worker_id = str(payload.target_worker_id or "").strip()
        promax_unit = PROMAX_UNIT_BY_FILIAL.get(str(int(clean_filial)) if clean_filial.isdigit() else clean_filial, clean_filial)
        job_payload = {
            "operation": "fechamento-mapa",
            "category": "fechamento-mapa",
            "profile": "fechamento-mapa",
            "mapa": clean_mapa,
            "filial": clean_filial,
            "unidade": promax_unit,
            "units": [promax_unit],
            "modo": clean_modo,
            "ponto_apoio": str(payload.ponto_apoio or "0").strip() or "0",
            "km_atual": clean_km_atual,
            "data": str(payload.data or date.today().isoformat()),
            "start_date": str(payload.data or date.today().isoformat()),
            "end_date": str(payload.data or date.today().isoformat()),
            "send_dates": False,
            "publish": False,
        }
        if clean_target_worker_id:
            job_payload["target_worker_id"] = clean_target_worker_id
        job = enqueue_promax_job(
            job_type="fechamento_mapa",
            payload=job_payload,
            priority=80,
            created_by=str(context.get("username") or context.get("mode") or ""),
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_fechamento_promax",
            decision="allowed",
            reason=f"mapa={clean_mapa}; filial={clean_filial}; modo={clean_modo}; worker={clean_target_worker_id or 'auto'}",
        )
        return {"ok": True, "job": job}

    @router.post("/api/internal/promax/financeiro/fechamento-mapa")
    def api_internal_promax_financeiro_fechamento_mapa(
        payload: InternalFinanceiroFechamentoSyncRequest,
        request: Request,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        result = sync_financeiro_fechamento_promax(
            {
                "job_id": payload.job_id,
                "data": payload.data,
                "filial": payload.filial,
                "mapa": payload.mapa,
                "result": payload.result,
            },
            context={"worker_id": payload.worker_id, "is_admin": True},
        )
        record_security_event(
            request,
            channel="api",
            event_type="promax_financeiro_fechamento_sync",
            decision="allowed",
            reason=f"job={payload.job_id}; mapa={payload.mapa}; filial={payload.filial}",
        )
        return result

    @router.delete("/api/admin/financeiro/mapas/{mapa_id}")
    def api_admin_financeiro_mapa_delete(
        mapa_id: int,
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_financeiro_context(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        result = delete_financeiro_mapa(mapa_id, context=context)
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_delete",
            decision="allowed",
            reason=str(mapa_id),
        )
        return result

    return router
