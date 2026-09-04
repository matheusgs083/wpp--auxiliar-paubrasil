from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
import tempfile
from secrets import compare_digest
from typing import Any
from zoneinfo import ZoneInfo

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

_FINANCEIRO_LOCAL_TIMEZONE = ZoneInfo("America/Fortaleza")
_PROMAX_JOB_STATUSES = {
    "pending",
    "running",
    "success",
    "partial_success",
    "failed",
    "cancel_requested",
    "cancelled",
}


class AdminFinanceiroMapaRequest(BaseModel):
    data: str
    filial: str = ""
    tipo_bloco: str = "mapa"
    mapa: str = ""
    mapa_ref: str = ""
    motorista: str = ""
    placa: str = ""
    ajudante1: str = ""
    ajudante2: str = ""
    boletos_rota: Any = 0
    boletos_recebido_qtd: Any = 0
    total_promax: Any = 0
    credito_conta: Any = 0
    dinheiro_promax: Any = 0
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
    dirty_fields: list[str] = Field(default_factory=list)


class AdminFinanceiroFechamentoRequest(BaseModel):
    data: str
    data_rotina: str = ""
    filial: str
    mapa: str = Field(min_length=1, max_length=40)
    modo: str = "completo"
    ponto_apoio: str = ""
    km_atual: str = ""
    target_worker_id: str = Field(default="", max_length=120)


class InternalFinanceiroFechamentoSyncRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    data: str
    filial: str
    mapa: str = Field(min_length=1, max_length=40)
    result: dict[str, Any] = Field(default_factory=dict)
    sync_scope: str = "all"


def create_admin_financeiro_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    list_financeiro_caixa: Callable[..., dict[str, Any]],
    upsert_financeiro_mapa: Callable[..., dict[str, Any]],
    get_financeiro_mapa_prestacao_contas: Callable[..., dict[str, Any]],
    export_financeiro_caixa_pdf: Callable[..., tuple[bytes, str]],
    sync_financeiro_fechamento_promax: Callable[..., dict[str, Any]],
    sync_conferencia_fechamento_promax: Callable[..., dict[str, Any]] | None,
    resolve_financeiro_fechamento_km: Callable[..., dict[str, Any]],
    relatorio_031120_import_services: dict[str, Any],
    enqueue_promax_job: Callable[..., Any],
    list_promax_jobs: Callable[..., list[dict[str, Any]]],
    get_promax_job: Callable[..., Any],
    list_promax_job_logs: Callable[..., list[dict[str, Any]]],
    cancel_promax_job: Callable[..., Any],
    list_promax_worker_heartbeats: Callable[..., list[dict[str, Any]]],
    delete_financeiro_mapa: Callable[..., dict[str, Any]],
    worker_token: str | None,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
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

    def record_panel_action(
        request: Request,
        context: dict[str, Any] | None,
        *,
        action: str,
        target_type: str = "",
        target_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if record_admin_panel_action is None:
            return
        record_admin_panel_action(
            request=request,
            context=context,
            module="financeiro",
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
        )

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

    @router.get("/api/admin/financeiro/mapas/{mapa_id}/prestacao-contas")
    def api_admin_financeiro_mapa_prestacao_contas(
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
        payload = get_financeiro_mapa_prestacao_contas(mapa_id=mapa_id, context=context)
        record_panel_action(
            request,
            context,
            action="abrir_prestacao_030322",
            target_type="financeiro_mapa",
            target_id=str(mapa_id),
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_prestacao_030322",
            decision="allowed",
            reason=f"mapa_id={mapa_id}",
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
        record_panel_action(
            request,
            context,
            action="baixar_relatorio_031120",
            target_type="filial",
            target_id=clean_filial,
            metadata={"data": data_value, "unit": promax_unit},
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
        record_panel_action(
            request,
            context,
            action="upload_relatorio_031120",
            target_type="filial",
            target_id=clean_filial,
            metadata={"filename": filename, "linhas": result.get("rows_imported") if isinstance(result, dict) else None},
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
        record_panel_action(
            request,
            context,
            action="exportar_caixa_pdf",
            target_type="filial",
            target_id=filial,
            metadata={"data": data, "filename": filename},
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
        record_panel_action(
            request,
            context,
            action="salvar_mapa",
            target_type="mapa",
            target_id=payload.mapa,
            metadata={"data": payload.data, "filial": payload.filial, "tipo_bloco": payload.tipo_bloco},
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
        clean_filial = _require_allowed_financeiro_filial(payload.filial, context)
        clean_mapa = str(payload.mapa or "").strip()
        clean_modo = str(payload.modo or "completo").strip().lower()
        if clean_modo not in {"completo", "fisico", "financeiro", "prestacao", "030322"}:
            raise HTTPException(status_code=400, detail="Modo de fechamento invalido.")
        caixa_date = _parse_admin_financeiro_date(payload.data)
        data_rotina = str(payload.data_rotina or "").strip()
        if data_rotina:
            _parse_admin_financeiro_date(data_rotina)
        clean_km_atual = str(payload.km_atual or "").strip()
        if clean_km_atual:
            clean_km_atual = clean_km_atual.replace(".", "").replace(",", "")
            if not clean_km_atual.isdigit():
                raise HTTPException(status_code=400, detail="KM atual deve conter apenas numeros.")
        km_resolved = resolve_financeiro_fechamento_km(
            filial=clean_filial,
            mapa=clean_mapa,
            caixa_date=caixa_date,
        )
        clean_km_inicial = str(km_resolved.get("km_inicial") or "").strip().replace(".", "").replace(",", "")
        clean_km_prev = str(km_resolved.get("km_prev") or "").strip().replace(".", "").replace(",", "")
        clean_km_fallback = str(km_resolved.get("km_atual") or "").strip().replace(".", "").replace(",", "")
        if not clean_km_atual:
            clean_km_atual = clean_km_fallback
        km_source = km_resolved.get("source") or ""
        if str(payload.km_atual or "").strip():
            km_source = "manual_with_fallback" if clean_km_inicial and clean_km_prev else "manual"
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
            "km_atual": clean_km_atual,
            "km_inicial": clean_km_inicial,
            "km_prev": clean_km_prev,
            "km_fallback_atual": clean_km_fallback,
            "km_source": km_source,
            "data": caixa_date.isoformat(),
            "data_rotina": data_rotina or caixa_date.isoformat(),
            "start_date": caixa_date.isoformat(),
            "end_date": caixa_date.isoformat(),
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
        record_panel_action(
            request,
            context,
            action="solicitar_fechamento_promax",
            target_type="mapa",
            target_id=clean_mapa,
            metadata={"filial": clean_filial, "modo": clean_modo, "worker": clean_target_worker_id or "auto", "km_source": km_source},
        )
        return {"ok": True, "job": job}

    @router.get("/api/admin/financeiro/fechamento-promax/jobs")
    def api_admin_financeiro_fechamento_promax_jobs(
        request: Request,
        status: str | None = Query(default=None, min_length=1, max_length=32),
        created_from: date | None = Query(default=None),
        created_to: date | None = Query(default=None),
        limit: int = Query(default=80, ge=1, le=200),
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
        clean_status = str(status or "").strip()
        if clean_status and clean_status not in _PROMAX_JOB_STATUSES:
            raise HTTPException(status_code=422, detail="Status de fechamento invalido.")
        created_from_at, created_before_at = _financeiro_job_created_bounds(created_from, created_to)
        job_candidates = list_promax_jobs(
            statuses=[clean_status] if clean_status else None,
            created_from=created_from_at,
            created_before=created_before_at,
            limit=500,
        )
        if not clean_status:
            active_candidates = list_promax_jobs(
                statuses=["pending", "running", "cancel_requested"],
                created_from=created_from_at,
                created_before=created_before_at,
                limit=500,
            )
            seen_ids = {str(job.get("id") or "") for job in job_candidates if isinstance(job, dict)}
            for job in active_candidates:
                job_id = str(job.get("id") or "") if isinstance(job, dict) else ""
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                job_candidates.append(job)
        allowed_filiais = _allowed_financeiro_filiais(context)
        filtered: list[dict[str, Any]] = []
        for job in job_candidates:
            payload = job.get("payload") if isinstance(job, dict) else {}
            if not isinstance(payload, dict):
                payload = {}
            operation = str(payload.get("operation") or job.get("job_type") or "").strip().lower()
            if operation not in {"fechamento-mapa", "fechamento_mapa", "mapa_fechamento"}:
                continue
            filial = _normalize_admin_filial(payload.get("filial"))
            if not filial:
                continue
            if allowed_filiais is not None and filial not in allowed_filiais:
                continue
            result = job.get("result") if isinstance(job.get("result"), dict) else {}
            filtered.append(
                {
                    "id": job.get("id"),
                    "job_type": job.get("job_type"),
                    "status": job.get("status"),
                    "created_at": job.get("created_at"),
                    "started_at": job.get("started_at"),
                    "finished_at": job.get("finished_at"),
                    "leased_by": job.get("leased_by"),
                    "result": result,
                    "error": job.get("error") or job.get("failure_reason") or "",
                    "payload": {
                        "filial": filial,
                        "unidade": str(payload.get("unidade") or ""),
                        "mapa": str(payload.get("mapa") or ""),
                        "modo": str(payload.get("modo") or ""),
                        "data": str(payload.get("data") or payload.get("start_date") or ""),
                        "km_atual": str(payload.get("km_atual") or ""),
                        "km_inicial": str(payload.get("km_inicial") or ""),
                        "km_prev": str(payload.get("km_prev") or ""),
                        "km_fallback_atual": str(payload.get("km_fallback_atual") or ""),
                        "km_source": str(payload.get("km_source") or ""),
                    },
                }
            )
        active_statuses = {"running", "pending", "cancel_requested"}

        active = [item for item in filtered if str(item.get("status") or "") in active_statuses]
        inactive = [item for item in filtered if str(item.get("status") or "") not in active_statuses]
        active.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or "")), reverse=True)
        inactive.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or "")), reverse=True)
        filtered = (active + inactive)[:limit]
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_fechamento_jobs",
            decision="allowed",
            reason=f"status={clean_status or '*'}; total={len(filtered)}",
        )
        return {"ok": True, "jobs": filtered}

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

    @router.post("/api/admin/financeiro/fechamento-promax/{job_id}/stop")
    def api_admin_financeiro_fechamento_promax_stop(
        request: Request,
        job_id: str = Path(min_length=1, max_length=120),
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
        job = _require_financeiro_fechamento_job(job_id, context, get_promax_job)
        result = cancel_promax_job(
            job_id,
            requested_by=str(context.get("username") or context.get("mode") or ""),
            reason="Fechamento Promax interrompido pelo painel financeiro.",
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_financeiro_fechamento_stop",
            decision="allowed",
            reason=f"job={job_id}; filial={(job.get('payload') or {}).get('filial')}",
        )
        record_panel_action(
            request,
            context,
            action="parar_fechamento_promax",
            target_type="job",
            target_id=job_id,
            metadata={"filial": (job.get("payload") or {}).get("filial"), "mapa": (job.get("payload") or {}).get("mapa")},
        )
        return {"ok": True, "job": result}

    @router.post("/api/internal/promax/financeiro/fechamento-mapa")
    def api_internal_promax_financeiro_fechamento_mapa(
        payload: InternalFinanceiroFechamentoSyncRequest,
        request: Request,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        scope = str(payload.sync_scope or "all").strip().lower()
        if scope not in {"all", "financeiro", "conferencia", "prestacao", "030302", "03030702", "030322"}:
            scope = "all"
        sync_payload = {
            "job_id": payload.job_id,
            "data": payload.data,
            "filial": payload.filial,
            "mapa": payload.mapa,
            "result": payload.result,
            "sync_scope": scope,
        }
        result: dict[str, Any] = {"ok": True, "sync_scope": scope}
        if scope in {"all", "financeiro", "prestacao", "03030702", "030322"}:
            result.update(
                sync_financeiro_fechamento_promax(
                    sync_payload,
                    context={"worker_id": payload.worker_id, "is_admin": True},
                )
            )
        if scope in {"all", "conferencia", "financeiro", "030302", "03030702"} and sync_conferencia_fechamento_promax is not None:
            try:
                result["conferencia"] = sync_conferencia_fechamento_promax(
                    sync_payload,
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
        record_panel_action(request, context, action="apagar_mapa", target_type="mapa_id", target_id=str(mapa_id))
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


def _normalize_admin_filial(value: Any) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return str(int(clean)) if clean.isdigit() else clean


def _require_allowed_financeiro_filial(value: Any, context: dict[str, Any] | None) -> str:
    clean = _normalize_admin_filial(value)
    if not clean:
        raise HTTPException(status_code=400, detail="Escolha a revenda antes de continuar.")
    allowed = _allowed_financeiro_filiais(context)
    if allowed is not None and clean not in allowed:
        raise HTTPException(status_code=403, detail="Revenda fora do escopo liberado para este usuario.")
    return clean


def _financeiro_job_created_bounds(
    created_from: date | None,
    created_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    if created_from and created_to and created_to < created_from:
        raise HTTPException(
            status_code=422,
            detail="A data final do filtro nao pode ser anterior a data inicial.",
        )
    start_at = (
        datetime.combine(created_from, time.min, _FINANCEIRO_LOCAL_TIMEZONE).astimezone(UTC)
        if created_from
        else None
    )
    before_at = (
        datetime.combine(created_to + timedelta(days=1), time.min, _FINANCEIRO_LOCAL_TIMEZONE).astimezone(UTC)
        if created_to
        else None
    )
    return start_at, before_at


def _require_financeiro_fechamento_job(
    job_id: str,
    context: dict[str, Any] | None,
    get_promax_job: Callable[..., Any],
) -> dict[str, Any]:
    job = get_promax_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job de fechamento nao encontrado.")
    payload = job.get("payload") if isinstance(job, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    operation = str(payload.get("operation") or job.get("job_type") or "").strip().lower()
    if operation not in {"fechamento-mapa", "fechamento_mapa", "mapa_fechamento"}:
        raise HTTPException(status_code=404, detail="Job de fechamento nao encontrado.")
    _require_allowed_financeiro_filial(payload.get("filial"), context)
    return job


def _build_fechamento_phase_logs(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for log in logs:
        message = str((log or {}).get("message") or "").strip()
        if not message:
            continue
        normalized = message.upper()
        if _is_fechamento_bootstrap_log(normalized):
            continue
        phase_key = ""
        phase_label = ""
        if "FECHAMENTO COMPLETO DE MAPA" in normalized and ("INICIO" in normalized or "INÍCIO" in normalized):
            phase_key = "inicio"
            phase_label = "Iniciando fechamento Promax"
        elif "INICIANDO COM DRIVER" in normalized or "IEDRIVER INICIADO" in normalized:
            phase_key = "webdriver"
            phase_label = "Iniciando WebDriver"
        elif (
            "LOGIN PROMAX" in normalized
            or "CREDENCIAIS ENVIADAS" in normalized
            or "SELECIONANDO UNIDADE" in normalized
            or ("SESS" in normalized and "INICIADA COM SUCESSO" in normalized)
        ):
            phase_key = "login"
            phase_label = "Login Promax em andamento"
        elif "030303" in normalized and _is_fechamento_routine_event(normalized):
            phase_key = "030303"
            phase_label = "Passando na 030303 - dados do mapa"
        elif "RESULTADO FINAL" in normalized or "RESUMO FINAL" in normalized:
            phase_key = "resultado"
            phase_label = message
        elif "SINCRONIZ" in normalized or "CAIXA FINANCEIRO" in normalized:
            phase_key = "sync_caixa"
            phase_label = "Atualizando o caixa financeiro"
        elif "030302" in normalized and not _is_fechamento_routine_event(normalized):
            continue
        elif ("FISICO" in normalized or "FÍSICO" in normalized) and "030302" not in normalized:
            continue
        elif "030302" in normalized or "FISICO" in normalized or "FÍSICO" in normalized:
            phase_key = "030302"
            phase_label = "Passando na 030302 - fechamento fisico"
        elif "03030702" in normalized and not _is_fechamento_routine_event(normalized):
            continue
        elif "FINANCEIRO" in normalized and "03030702" not in normalized:
            continue
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


def _is_fechamento_bootstrap_log(normalized_message: str) -> bool:
    return any(
        token in normalized_message
        for token in (
            "LOGGER INICIADO",
            "LEVEL_FILE=",
            "LEVEL_CONSOLE=",
        )
    )


def _is_fechamento_routine_event(normalized_message: str) -> bool:
    return any(
        token in normalized_message
        for token in (
            "PASSO",
            "ACESSANDO ROTINA",
            "CARREGANDO MAPA",
            "SALVANDO MAPA",
            "SALVAR",
            "SALVO",
            "RESULTADO DO PROCESSO",
            "INICIANDO ROTINA",
            "ROTINA FISICA",
            "ROTINA FÍSICA",
            "FECHAMENTO FINANCEIRO",
            "APLICANDO PRODUTOS",
            "CHECAGEM DE CODIGOS",
            "CHECAGEM DE CÓDIGOS",
        )
    )
