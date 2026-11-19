from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator


_CORA_ESTOQUE_UNIDADE_POR_FILIAL = {
    "1": "487570",  # Sousa
    "2": "820288",  # Itaporanga
    "3": "747530",  # Patos
    "4": "747548",  # Sumé
    "5": "1036580",  # Guarabira
    "6": "1044303",  # Brumado
    "7": "1044591",  # Barra
    "8": "1045180",  # Caculé
}


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AtualizarEstoqueCoraRequest(_StrictPayload):
    filiais: list[str] = Field(default_factory=list, max_length=8)
    target_worker_id: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("filiais")
    @classmethod
    def filiais_numericas(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            filial = str(value or "").strip().lstrip("0") or "0"
            if not filial.isdigit():
                raise ValueError("Filial deve conter apenas números.")
            if filial not in normalized:
                normalized.append(filial)
        return normalized


def create_admin_estoque_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    estoque_import_service: Any,
    estoque_query_service: Any,
    promax_jobs_service: Any,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def context_for_stock(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> dict[str, Any]:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        require_admin_panel_feature(context, "estoque")
        return context

    def allow_filial(context: Mapping[str, Any], filial: str) -> None:
        if bool(context.get("is_admin")):
            return
        allowed = {str(value).strip().lstrip("0") or "0" for value in (context.get("filiais") or ())}
        if str(filial) not in allowed:
            raise HTTPException(status_code=403, detail="Sua conta não possui acesso a esta filial.")

    @router.get("/api/admin/estoque")
    def consultar_estoque(
        request: Request,
        filial: str = Query(min_length=1, max_length=8),
        busca: str = Query(default="", max_length=120),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = context_for_stock(request, authorization, x_api_token, x_admin_token)
        filial = str(filial).strip().lstrip("0") or "0"
        if not filial.isdigit():
            raise HTTPException(status_code=422, detail="Filial inválida.")
        allow_filial(context, filial)
        try:
            result = estoque_query_service.dashboard(filial=filial, search=busca)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_estoque_consulta", decision="allowed", reason=f"filial={filial};ready={result.get('ready')}")
        return {"ok": True, **result}

    @router.post("/api/admin/estoque/importar")
    async def importar_estoque(
        request: Request,
        filial: str = Form(...),
        arquivo: UploadFile = File(...),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = context_for_stock(request, authorization, x_api_token, x_admin_token)
        if not bool(context.get("is_admin")):
            raise HTTPException(status_code=403, detail="Somente administrador pode importar a grade do Cora.")
        filial = str(filial).strip().lstrip("0") or "0"
        if not filial.isdigit():
            raise HTTPException(status_code=422, detail="Filial inválida.")
        filename = str(arquivo.filename or "").strip()
        if not filename.lower().endswith(".csv"):
            raise HTTPException(status_code=422, detail="Envie o CSV Stock_Product exportado pelo Cora.")
        content = await arquivo.read()
        try:
            result = estoque_import_service.import_csv(filial=filial, filename=filename, content=content)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc
        record_security_event(request, channel="api", event_type="admin_estoque_importar", decision="allowed", reason=f"filial={filial};items={result['items']}")
        if record_admin_panel_action:
            record_admin_panel_action(request=request, context=context, module="estoque", action="importar_grade_cora", metadata={"filial": filial, "items": result["items"], "source": filename})
        return result

    @router.post("/api/admin/estoque/atualizar", status_code=202)
    def atualizar_estoque_pelo_cora(
        request: Request,
        payload: AtualizarEstoqueCoraRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Enfileira a exportação da grade Cora e a importação automática do CSV."""
        context = context_for_stock(request, authorization, x_api_token, x_admin_token)
        if not bool(context.get("is_admin")):
            raise HTTPException(status_code=403, detail="Somente administrador pode atualizar a grade pelo Cora.")
        filiais = payload.filiais or sorted(_CORA_ESTOQUE_UNIDADE_POR_FILIAL)
        unsupported = [filial for filial in filiais if filial not in _CORA_ESTOQUE_UNIDADE_POR_FILIAL]
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Não há unidade Cora configurada para: " + ", ".join(unsupported)
                    + ". Atualize a dRevendas ou o mapeamento de unidades Cora."
                ),
            )
        units = [_CORA_ESTOQUE_UNIDADE_POR_FILIAL[filial] for filial in filiais]
        job = promax_jobs_service.enqueue_job(
            job_type="cora_estoque",
            payload={
                "site": "cora",
                "operation": "grade_estoque",
                "category": "cora_estoque",
                "routines": ["grade_estoque"],
                "units": units,
                "target_worker_id": payload.target_worker_id,
            },
            priority=75,
            created_by=str(context.get("username") or context.get("user_id") or "painel"),
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_estoque_atualizar_cora",
            decision="allowed",
            reason=f"filiais={','.join(filiais)};units={','.join(units)}",
        )
        if record_admin_panel_action:
            record_admin_panel_action(
                request=request,
                context=context,
                module="estoque",
                action="atualizar_grade_cora",
                metadata={"filiais": filiais, "units": units, "job_id": str(job.get("id") or "")},
            )
        return {"ok": True, "job": job, "filiais": filiais, "units": units}

    return router
