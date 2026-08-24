from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
import tempfile
from secrets import compare_digest
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Path, Query, Request, Response, UploadFile
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
    sync_conferencia_fechamento_promax: Callable[..., dict[str, Any]] | None,
    resolve_financeiro_fechamento_km: Callable[..., dict[str, Any]],
    relatorio_031120_import_services: dict[str, Any],
    enqueue_promax_job: Callable[..., Any],
    get_promax_job: Callable[..., Any],
    list_promax_job_logs: Callable[..., list[dict[str, Any]]],
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

    @router.post("/api/admin/financeiro/031120/download", status_code=202)
    def api_admin_financeiro_031120_download(
        payload: dict[str, Any],
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
        clean_filial = _require_allowed_financeiro_filial(payload.get("filial"), context)
        promax_unit = PROMAX_UNIT_BY_FILIAL.get(clean_filial)
        if not promax_unit:
            raise HTTPException(status_code=400, detail="Revenda sem unidade Promax configurada para 031120.")
        data_value = str(payload.get("data") or date.today().isoformat())
        job_payload = {
            "category": "bot_zap",
            "routines": ["031120_BOT"],
            "units": [promax_unit],
            "start_date": data_value,
            "end_date": data_value,
            "send_dates": True,
            "publish": True,
            "source": "financeiro_031120",
        }
        job = enqueue_promax_job(
            job_type="bot_zap",
            payload=job_payload,
            priority=60,
            created_by=str(context.get("username") or context.get("mode") or ""),
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_031120_download",
            decision="allowed",
            reason=f"filial={clean_filial}; unit={promax_unit}",
        )
        return {"ok": True, "job": job, "filial": clean_filial, "unit": promax_unit}

    @router.post("/api/admin/financeiro/031120/upload")
    async def api_admin_financeiro_031120_upload(
        request: Request,
        filial: str = Form(...),
        file: UploadFile = File(...),
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
        clean_filial = _require_allowed_financeiro_filial(filial, context)
        import_service = relatorio_031120_import_services.get(clean_filial)
        if import_service is None:
            raise HTTPException(status_code=400, detail=f"Importador 031120 nao configurado para a revenda {clean_filial}.")
        filename = str(file.filename or f"031120_filial_{clean_filial}.csv").strip()
        content = await file.read()
        if not content.strip():
            raise HTTPException(status_code=400, detail="Arquivo CSV 031120 vazio.")
        with tempfile.TemporaryDirectory(prefix=f"financeiro_031120_{clean_filial}_") as temp_dir:
            from pathlib import Path as FilePath

            safe_name = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in filename) or f"031120_filial_{clean_filial}.csv"
            file_path = FilePath(temp_dir) / safe_name
            file_path.write_bytes(content)
            result = import_service.import_source(file_path)
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_031120_upload",
            decision="allowed",
            reason=f"filial={clean_filial}; filename={filename}",
        )
        return {"ok": True, "filial": clean_filial, "result": result}

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
        km_resolved: dict[str, Any] = {}
        clean_km_inicial = ""
        clean_km_prev = ""
        if not clean_km_atual:
            km_resolved = resolve_financeiro_fechamento_km(
                filial=clean_filial,
                mapa=clean_mapa,
                caixa_date=_parse_admin_financeiro_date(payload.data),
            )
            clean_km_atual = str(km_resolved.get("km_atual") or "").strip().replace(".", "").replace(",", "")
            clean_km_inicial = str(km_resolved.get("km_inicial") or "").strip().replace(".", "").replace(",", "")
            clean_km_prev = str(km_resolved.get("km_prev") or "").strip().replace(".", "").replace(",", "")
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
            "km_inicial": clean_km_inicial,
            "km_prev": clean_km_prev,
            "km_source": km_resolved.get("source") or ("manual" if clean_km_atual else ""),
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

    @router.get("/api/admin/financeiro/fechamento-promax/{job_id}/logs")
    def api_admin_financeiro_fechamento_promax_logs(
        request: Request,
        job_id: str = Path(min_length=1, max_length=120),
        limit: int = Query(default=80, ge=1, le=500),
        after_id: int = Query(default=0, ge=0),
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
        job = get_promax_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job de fechamento nao encontrado.")
        payload = job.get("payload") if isinstance(job, dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        operation = str(payload.get("operation") or job.get("job_type") or "").strip().lower()
        if operation not in {"fechamento-mapa", "fechamento_mapa", "mapa_fechamento"}:
            raise HTTPException(status_code=404, detail="Job de fechamento nao encontrado.")
        clean_filial = _require_allowed_financeiro_filial(payload.get("filial"), context)
        logs = list_promax_job_logs(job_id, limit=limit, after_id=after_id)
        return {
            "ok": True,
            "job": {
                "id": job.get("id"),
                "status": job.get("status"),
                "result_status": job.get("result_status"),
                "filial": clean_filial,
                "mapa": str(payload.get("mapa") or ""),
                "modo": str(payload.get("modo") or ""),
            },
            "logs": logs,
            "phases": _build_fechamento_phase_logs(logs),
        }

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
        if sync_conferencia_fechamento_promax is not None:
            try:
                result["conferencia"] = sync_conferencia_fechamento_promax(
                    {
                        "job_id": payload.job_id,
                        "data": payload.data,
                        "filial": payload.filial,
                        "mapa": payload.mapa,
                        "result": payload.result,
                    },
                    context={"worker_id": payload.worker_id, "is_admin": True},
                )
            except Exception as exc:
                result["conferencia_error"] = str(exc)
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


def _parse_admin_financeiro_date(value: Any) -> date:
    cleaned = str(value or "").strip()
    if not cleaned:
        return date.today()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail="Data invalida. Use YYYY-MM-DD ou DD/MM/AAAA.")


def _allowed_financeiro_filiais(context: dict[str, Any] | None) -> set[str] | None:
    if not context or bool(context.get("is_admin")):
        return None
    raw = [str(item).strip() for item in context.get("filiais", ()) if str(item).strip()]
    if not raw or "*" in raw:
        return None
    return {str(int(item)) if item.isdigit() else item for item in raw}


def _require_allowed_financeiro_filial(value: Any, context: dict[str, Any] | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Escolha a revenda antes de continuar.")
    clean = str(int(clean)) if clean.isdigit() else clean
    allowed = _allowed_financeiro_filiais(context)
    if allowed is not None and clean not in allowed:
        raise HTTPException(status_code=403, detail="Revenda fora do escopo liberado para este usuario.")
    return clean


def _build_fechamento_phase_logs(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for log in logs:
        message = str((log or {}).get("message") or "").strip()
        if not message:
            continue
        normalized = message.upper()
        phase_key = ""
        phase_label = ""
        if "030303" in normalized:
            phase_key = "030303"
            phase_label = "Passando na 030303 - dados do mapa"
        elif "030302" in normalized or "FISICO" in normalized or "FÍSICO" in normalized:
            phase_key = "030302"
            phase_label = "Passando na 030302 - fechamento fisico"
        elif "03030702" in normalized or "FINANCEIRO" in normalized:
            phase_key = "03030702"
            phase_label = "Passando na 03030702 - fechamento financeiro"
        elif "SINCRONIZ" in normalized or "CAIXA FINANCEIRO" in normalized:
            phase_key = "sync_caixa"
            phase_label = "Atualizando o caixa financeiro"
        elif "RESULTADO FINAL" in normalized or "RESUMO FINAL" in normalized:
            phase_key = "resultado"
            phase_label = message
        if not phase_key:
            continue
        if phase_key in seen and phase_key != "resultado":
            continue
        seen.add(phase_key)
        phases.append(
            {
                "id": log.get("id"),
                "created_at": log.get("created_at"),
                "level": log.get("level") or "info",
                "phase": phase_key,
                "label": phase_label,
                "message": message,
            }
        )
    return phases
