"""Aba Crítica: pede ao worker a Crítica do portal Cora, sem passar pela aba Promax.

O worker baixa o CSV e chama a importação interna da crítica por operação, então o
usuário só precisa apertar o botão e acompanhar a situação aqui.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

# Quem usa a aba Crítica (área Dados) pede a geração; "gerar_critica" agora é o PDF da carteira.
FEATURE_GERAR_CRITICA = "critica"
JOB_TYPE_CRITICA = "cora_critica"
STATUS_ATIVOS = ("pending", "running", "cancel_requested")
DIAS_PARA_TRAS = 31
HISTORICO = 8
FUSO = ZoneInfo("America/Fortaleza")

SITUACOES = {
    "pending": "Na fila",
    "running": "Gerando",
    "cancel_requested": "Cancelando",
    "success": "Concluída",
    "partial_success": "Concluída com avisos",
    "failed": "Falhou",
    "cancelled": "Cancelada",
}


class GerarCriticaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: date | None = None


def create_admin_critica_geracao_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    promax_jobs_service: Any,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def autenticar(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> dict[str, Any]:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        require_admin_panel_feature(context, FEATURE_GERAR_CRITICA)
        return context

    def geracao_ativa() -> Mapping[str, Any] | None:
        ativos = promax_jobs_service.list_jobs(statuses=list(STATUS_ATIVOS), job_types=[JOB_TYPE_CRITICA], limit=1)
        return ativos[0] if ativos else None

    @router.get("/api/admin/critica/geracao")
    def situacao_geracao(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        autenticar(request, authorization, x_api_token, x_admin_token)
        try:
            historico = promax_jobs_service.list_jobs(job_types=[JOB_TYPE_CRITICA], limit=HISTORICO)
            fila = promax_jobs_service.get_queue_state()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Não foi possível consultar a fila do worker agora.") from exc
        itens = [resumo_geracao(job) for job in historico]
        ativo = next((item for item in itens if item["ativo"]), None)
        return {
            "ok": True,
            "em_andamento": ativo,
            "historico": itens,
            "fila_pausada": bool(_campo(fila, "paused")),
            "motivo_pausa": str(_campo(fila, "pause_reason") or ""),
            "hoje": _hoje().isoformat(),
        }

    @router.post("/api/admin/critica/geracao", status_code=202)
    def gerar_critica(
        request: Request,
        payload: GerarCriticaRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = autenticar(request, authorization, x_api_token, x_admin_token)
        data = payload.data or _hoje()
        validar_data(data)
        ativo = geracao_ativa()
        if ativo is not None:
            # Um pedido por vez: dois downloads da Crítica ao mesmo tempo só duplicam a importação.
            return {"ok": True, "ja_na_fila": True, "geracao": resumo_geracao(ativo)}
        usuario = str(context.get("username") or context.get("user_id") or "painel")
        job = promax_jobs_service.enqueue_job(
            job_type=JOB_TYPE_CRITICA,
            payload={
                "site": "cora",
                "operation": "critica",
                "category": JOB_TYPE_CRITICA,
                "routines": ["critica"],
                "units": [],
                "target_worker_id": None,
                "reference_date": data.isoformat(),
            },
            priority=75,
            created_by=usuario,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_critica_gerar",
            decision="allowed",
            reason=f"data={data.isoformat()};job={job.get('id') or ''}",
        )
        if record_admin_panel_action:
            record_admin_panel_action(
                request=request,
                context=context,
                module="critica",
                action="gerar_critica",
                metadata={"data": data.isoformat(), "job_id": str(job.get("id") or "")},
            )
        return {"ok": True, "ja_na_fila": False, "geracao": resumo_geracao(job)}

    return router


def validar_data(data: date) -> None:
    hoje = _hoje()
    if data > hoje:
        raise HTTPException(status_code=422, detail="A data da crítica não pode ser futura.")
    if data < hoje - timedelta(days=DIAS_PARA_TRAS):
        raise HTTPException(status_code=422, detail=f"Escolha uma data dos últimos {DIAS_PARA_TRAS} dias.")


def resumo_geracao(job: Mapping[str, Any]) -> dict[str, Any]:
    """O que a tela precisa de um job da Crítica, sem expor payload nem lease do worker."""
    status = str(job.get("status") or "")
    payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
    importacao = _resultado_importacao(job.get("result"))
    imports = importacao.get("imports") if isinstance(importacao.get("imports"), list) else []
    filiais = sorted(
        {str(item.get("filial")) for item in imports if isinstance(item, Mapping) and item.get("filial")},
        key=lambda valor: (len(valor), valor),
    )
    erro = str(job.get("failure_reason") or job.get("error") or "") if status in {"failed", "partial_success"} else ""
    pos = importacao.get("post_actions") if isinstance(importacao.get("post_actions"), Mapping) else {}
    return {
        "id": str(job.get("id") or ""),
        "status": status,
        "situacao": SITUACOES.get(status, status or "-"),
        "ativo": status in STATUS_ATIVOS,
        "data_referencia": str(payload.get("reference_date") or ""),
        "criado_por": str(job.get("created_by") or ""),
        "criado_em": job.get("created_at"),
        "iniciado_em": job.get("started_at"),
        "finalizado_em": job.get("finished_at"),
        "linhas": importacao.get("rows"),
        "filiais": filiais,
        "erro": erro[:300],
        "aviso": str(pos.get("post_import_warning") or "")[:300],
    }


def _resultado_importacao(result: Any) -> Mapping[str, Any]:
    """O worker pode devolver o retorno da importação no topo ou dentro de uma chave."""
    if not isinstance(result, Mapping):
        return {}
    if "imports" in result or "rows" in result:
        return result
    for valor in result.values():
        if isinstance(valor, Mapping) and ("imports" in valor or "rows" in valor):
            return valor
    return {}


def _campo(registro: Any, nome: str) -> Any:
    if isinstance(registro, Mapping):
        return registro.get(nome)
    return getattr(registro, nome, None)


def _hoje() -> date:
    return datetime.now(FUSO).date()
