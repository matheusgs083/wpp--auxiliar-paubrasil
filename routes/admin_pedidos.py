from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bot_api.commercial_scope import normalize_stored_scope_value, split_scope_pair


_UNIT_BY_FILIAL = {
    "1": "0640001", "2": "0640002", "3": "2210003", "4": "2210004",
    "5": "3480005", "6": "3610006", "7": "3610007", "8": "3610008",
}


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PedidoItemRequest(_StrictPayload):
    produto: str = Field(min_length=1, max_length=20)
    quantidade: int = Field(ge=1, le=99999)
    preco: str = Field(min_length=1, max_length=20)

    @field_validator("produto")
    @classmethod
    def produto_numerico(cls, value: str) -> str:
        value = str(value).strip()
        if not value.isdigit():
            raise ValueError("Código do produto deve conter apenas números.")
        return value

    @field_validator("preco")
    @classmethod
    def preco_valido(cls, value: str) -> str:
        normalized = str(value or "").strip().replace("R$", "").replace(" ", "")
        if normalized.count(",") > 1 or normalized.count(".") > 1:
            raise ValueError("Preço inválido.")
        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(",", ".")
        try:
            price = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError("Preço inválido.") from exc
        if price <= 0 or price > Decimal("999999.99"):
            raise ValueError("Preço deve ser maior que zero e menor que R$ 1.000.000,00.")
        return f"{price:.2f}".replace(".", ",")


class PedidoCreateRequest(_StrictPayload):
    filial: str = Field(min_length=1, max_length=8)
    cliente: str = Field(min_length=1, max_length=20)
    itens: list[PedidoItemRequest] = Field(min_length=1, max_length=200)
    cond_pagto: str = Field(default="", max_length=8)
    motivo_digitacao: str = Field(min_length=1, max_length=80)
    target_worker_id: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("filial", "cliente")
    @classmethod
    def somente_numeros(cls, value: str) -> str:
        value = str(value).strip()
        if not value.isdigit():
            raise ValueError("Filial e cliente devem conter apenas números.")
        return value.lstrip("0") or "0"

    @field_validator("cond_pagto")
    @classmethod
    def condicao_numerica(cls, value: str) -> str:
        value = str(value).strip()
        if value and not value.isdigit():
            raise ValueError("Condição de pagamento deve conter apenas números.")
        return value

    @field_validator("motivo_digitacao")
    @classmethod
    def motivo_preenchido(cls, value: str) -> str:
        value = str(value).strip()
        if not value:
            raise ValueError("Selecione um motivo de digitação.")
        return value


class PedidoGerencialConfigRequest(_StrictPayload):
    motivos: list[str] = Field(min_length=1, max_length=20)
    max_caixas_por_produto: int = Field(ge=1, le=99_999)
    limites_por_produto: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    @field_validator("motivos")
    @classmethod
    def motivos_validos(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
        if not cleaned or any(len(value) > 80 for value in cleaned):
            raise ValueError("Informe ao menos um motivo com até 80 caracteres.")
        return cleaned

    @field_validator("limites_por_produto")
    @classmethod
    def limites_validos(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in values:
            if not str(item.get("produto") or "").strip().isdigit():
                raise ValueError("Cada limite deve indicar um produto numérico.")
        return values


def create_admin_pedidos_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    dclientes_query_service: Any,
    inadimplencia_query_service: Any,
    cora_estoque_query_service: Any,
    promax_jobs_service: Any,
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

    def context_for_pedidos(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> dict[str, Any]:
        context = require_admin_panel_auth(request=request, authorization=authorization, x_api_token=x_api_token, x_admin_token=x_admin_token)
        require_admin_panel_feature(context, "pedidos")
        if not bool(context.get("is_admin")) and not _seller_scopes(context):
            raise HTTPException(status_code=403, detail="Seu usuário não possui uma carteira de vendedor configurada para Pedidos.")
        return context

    def record_action(request: Request, context: Mapping[str, Any], action: str, **metadata: Any) -> None:
        if record_admin_panel_action:
            record_admin_panel_action(request=request, context=context, module="pedidos", action=action, metadata=metadata)

    def admin_context(request: Request, authorization: str | None, x_api_token: str | None, x_admin_token: str | None) -> dict[str, Any]:
        context = context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        if not bool(context.get("is_admin")):
            raise HTTPException(status_code=403, detail="A área gerencial de pedidos é exclusiva para administradores.")
        return context

    @router.get("/api/admin/pedidos/clientes")
    def pesquisar_clientes(
        request: Request,
        busca: str = Query(min_length=2, max_length=120),
        filial: str | None = Query(default=None, max_length=8),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        scopes = None if bool(context.get("is_admin")) else list(_seller_scopes(context))
        try:
            if str(busca).strip().isdigit() and filial:
                rows = dclientes_query_service.search_by_registration(str(filial), str(busca), allowed_sectors=scopes)
            else:
                rows = dclientes_query_service.search_by_fantasia(str(busca), allowed_sectors=scopes, limit=10)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc
        result = [_client_payload(item) for item in rows]
        record_security_event(request, channel="api", event_type="admin_pedidos_clientes", decision="allowed", reason=f"total={len(result)}")
        return {"ok": True, "clientes": result, "total": len(result), "seller_scopes": list(scopes or ())}

    @router.get("/api/admin/pedidos/clientes/{filial}/{cliente}")
    def detalhar_cliente(
        request: Request,
        filial: str,
        cliente: str,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        scopes = None if bool(context.get("is_admin")) else list(_seller_scopes(context))
        cliente_registro = _load_authorized_client(
            dclientes_query_service,
            filial=filial,
            cliente=cliente,
            scopes=scopes,
        )
        inadimplencia = _load_inadimplencia(
            inadimplencia_query_service,
            filial=filial,
            cliente=cliente,
            scopes=scopes,
        )
        payload = _client_payload(cliente_registro)
        payload["inadimplencia"] = inadimplencia
        payload["pedido_liberado"] = not bool(inadimplencia["bloqueado"])
        record_security_event(
            request,
            channel="api",
            event_type="admin_pedidos_cliente_detalhe",
            decision="allowed",
            reason=f"filial={filial};cliente={cliente};bloqueado={inadimplencia['bloqueado']}",
        )
        return {"ok": True, "cliente": payload}

    @router.get("/api/admin/pedidos/estoque")
    def pesquisar_produtos_estoque(
        request: Request,
        filial: str = Query(min_length=1, max_length=8),
        busca: str = Query(min_length=1, max_length=120),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        filial = str(filial).strip().lstrip("0") or "0"
        if not filial.isdigit():
            raise HTTPException(status_code=422, detail="Filial inválida.")
        if not bool(context.get("is_admin")):
            allowed_filiais = {scope.split("-", 1)[0] for scope in _seller_scopes(context)}
            if filial not in allowed_filiais:
                raise HTTPException(status_code=403, detail="Sua carteira não permite consultar a grade desta filial.")
        try:
            result = cora_estoque_query_service.dashboard(filial=filial, search=busca, limit=12)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Não foi possível consultar a grade de estoque.") from exc
        record_security_event(
            request,
            channel="api",
            event_type="admin_pedidos_estoque",
            decision="allowed",
            reason=f"filial={filial};total={len(result.get('items') or ())}",
        )
        return {"ok": True, **result}

    @router.get("/api/admin/pedidos/condicoes")
    def listar_condicoes_pagamento(
        request: Request,
        filial: str = Query(min_length=1, max_length=8),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        filial = str(filial).strip().lstrip("0") or "0"
        unidade = _UNIT_BY_FILIAL.get(filial)
        if not unidade:
            raise HTTPException(status_code=422, detail="Filial sem unidade Promax mapeada.")
        if not bool(context.get("is_admin")):
            allowed_filiais = {scope.split("-", 1)[0] for scope in _seller_scopes(context)}
            if filial not in allowed_filiais:
                raise HTTPException(status_code=403, detail="Sua carteira não permite consultar as condições desta filial.")
        catalogo = _load_promax_conditions_catalog(unidade, promax_jobs_service)
        record_security_event(
            request,
            channel="api",
            event_type="admin_pedidos_condicoes",
            decision="allowed",
            reason=f"filial={filial};condicoes={len(catalogo['condicoes'])}",
        )
        return {"ok": True, "filial": filial, "unidade": unidade, **catalogo}

    @router.get("/api/admin/pedidos/config")
    def obter_configuracao_pedidos(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        return {"ok": True, **promax_jobs_service.get_pedido_digitacao_config()}

    @router.get("/api/admin/pedidos/gerencial/config")
    def obter_configuracao_gerencial_pedidos(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = admin_context(request, authorization, x_api_token, x_admin_token)
        config = promax_jobs_service.get_pedido_digitacao_config()
        record_security_event(request, channel="api", event_type="admin_pedidos_gerencial_config", decision="allowed", reason=f"user={_pedido_created_by(context)}")
        return {"ok": True, **config}

    @router.get("/api/admin/pedidos/gerencial/produtos")
    def pesquisar_produtos_gerencial_pedidos(
        request: Request,
        filial: str = Query(min_length=1, max_length=8),
        busca: str = Query(min_length=2, max_length=120),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        admin_context(request, authorization, x_api_token, x_admin_token)
        normalized_filial = str(filial).strip().lstrip("0") or "0"
        try:
            result = cora_estoque_query_service.dashboard(filial=normalized_filial, search=busca, limit=12)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Não foi possível consultar a grade para selecionar o produto.") from exc
        return {"ok": True, "items": [{"produto": str(item.get("codigo_produto") or ""), "descricao": str(item.get("descricao_produto") or "")} for item in result.get("items") or []]}

    @router.put("/api/admin/pedidos/gerencial/config")
    def atualizar_configuracao_gerencial_pedidos(
        request: Request,
        payload: PedidoGerencialConfigRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = admin_context(request, authorization, x_api_token, x_admin_token)
        config = promax_jobs_service.update_pedido_digitacao_config(
            motivos=payload.motivos,
            max_caixas_por_produto=payload.max_caixas_por_produto,
            limites_por_produto=payload.limites_por_produto,
            updated_by=_pedido_created_by(context),
        )
        record_security_event(request, channel="api", event_type="admin_pedidos_gerencial_config_update", decision="allowed", reason=f"motivos={len(config['motivos'])};limite={config['max_caixas_por_produto']};produtos={len(config['limites_por_produto'])}")
        record_action(request, context, "configurar_digitacao_pedidos", motivos=config["motivos"], max_caixas_por_produto=config["max_caixas_por_produto"], limites_por_produto=config["limites_por_produto"])
        return {"ok": True, **config}

    @router.get("/api/admin/pedidos/gerencial/auditoria")
    def auditoria_gerencial_pedidos(
        request: Request,
        data_de: str | None = Query(default=None, max_length=10),
        data_ate: str | None = Query(default=None, max_length=10),
        filial: str | None = Query(default=None, max_length=8),
        motivo: str | None = Query(default=None, max_length=80),
        status: str | None = Query(default=None, max_length=32),
        gv: str | None = Query(default=None, max_length=32),
        rn: str | None = Query(default=None, max_length=160),
        condicao: str | None = Query(default=None, max_length=16),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = admin_context(request, authorization, x_api_token, x_admin_token)
        try:
            start = date.fromisoformat(data_de) if data_de else None
            end = date.fromisoformat(data_ate) if data_ate else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Use datas no formato AAAA-MM-DD.") from exc
        if start and end and end < start:
            raise HTTPException(status_code=422, detail="A data final deve ser igual ou posterior à inicial.")
        normalized_filial = str(filial or "").strip().lstrip("0") or None
        normalized_motivo = str(motivo or "").strip() or None
        normalized_status = str(status or "").strip().lower() or None
        normalized_gv = str(gv or "").strip() or None
        normalized_rn = str(rn or "").strip() or None
        normalized_condicao = str(condicao or "").strip() or None
        rows: list[dict[str, Any]] = []
        for job in promax_jobs_service.list_jobs(limit=500):
            if job.get("job_type") != "digitacao_030104":
                continue
            payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
            digitacao = payload.get("digitacao") if isinstance(payload.get("digitacao"), Mapping) else {}
            unidade = str(digitacao.get("unidade") or "")
            job_filial = next((code for code, unit in _UNIT_BY_FILIAL.items() if unit == unidade), "")
            created_at = str(job.get("created_at") or "")
            try:
                created_day = date.fromisoformat(created_at[:10])
            except ValueError:
                created_day = None
            if start and (created_day is None or created_day < start):
                continue
            if end and (created_day is None or created_day > end):
                continue
            if normalized_filial and normalized_filial != job_filial:
                continue
            if normalized_status and str(job.get("status") or "").lower() != normalized_status:
                continue
            pedidos = digitacao.get("pedidos") if isinstance(digitacao.get("pedidos"), list) else []
            for pedido in pedidos:
                if not isinstance(pedido, Mapping):
                    continue
                pedido_motivo = str(pedido.get("motivo_digitacao") or "Sem motivo registrado")
                if normalized_motivo and pedido_motivo != normalized_motivo:
                    continue
                pedido_gv = str(pedido.get("gv") or pedido.get("vendedor") or "-")
                pedido_rn = str(job.get("created_by") or "-")
                pedido_condicao = str(pedido.get("cond_pagto") or "Padrão")
                if normalized_gv and pedido_gv != normalized_gv:
                    continue
                if normalized_rn and pedido_rn != normalized_rn:
                    continue
                if normalized_condicao and pedido_condicao != normalized_condicao:
                    continue
                itens = pedido.get("itens") if isinstance(pedido.get("itens"), list) else []
                total_caixas = sum(int(item.get("quantidade") or 0) for item in itens if isinstance(item, Mapping))
                total_valor = sum(_item_total(item) for item in itens if isinstance(item, Mapping))
                rows.append({
                    "job_id": str(job.get("id") or ""), "status": str(job.get("status") or "pending"),
                    "filial": job_filial, "unidade": unidade, "cliente": str(pedido.get("cliente") or "-"),
                    "mapa": str(pedido.get("mapa") or "NOVO1"), "vendedor": pedido_gv, "condicao": pedido_condicao,
                    "motivo": pedido_motivo, "criado_por": pedido_rn,
                    "criado_em": created_at, "iniciado_em": job.get("started_at"), "finalizado_em": job.get("finished_at"),
                    "itens": len(itens), "caixas": total_caixas, "valor": float(total_valor),
                    "produtos": ", ".join(str(item.get("produto") or "-") for item in itens if isinstance(item, Mapping)),
                })
        motivos = _group_count(rows, "motivo")
        statuses = _group_count(rows, "status")
        usuarios = _group_count(rows, "criado_por")
        by_day = _group_count_by_day(rows)
        filters = {"gvs": _filter_values(rows, "vendedor"), "rns": _filter_values(rows, "criado_por"), "condicoes": _filter_values(rows, "condicao"), "motivos": _filter_values(rows, "motivo")}
        summary = {"pedidos": len(rows), "caixas": sum(row["caixas"] for row in rows), "valor": float(sum(Decimal(str(row["valor"])) for row in rows)), "pendentes": sum(1 for row in rows if row["status"] in {"pending", "running"}), "falhos": sum(1 for row in rows if row["status"] in {"failed", "partial_success", "cancelled"})}
        record_security_event(request, channel="api", event_type="admin_pedidos_gerencial_auditoria", decision="allowed", reason=f"user={_pedido_created_by(context)};rows={len(rows)}")
        return {"ok": True, "summary": summary, "motivos": motivos, "statuses": statuses, "usuarios": usuarios, "por_dia": by_day, "filters": filters, "rows": rows}

    @router.get("/api/admin/pedidos/jobs")
    def listar_meus_pedidos(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Lista somente os pedidos criados pela identidade autenticada."""
        context = context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        created_by = _pedido_created_by(context)
        jobs: list[dict[str, Any]] = []
        for job in promax_jobs_service.list_jobs(limit=500):
            if job.get("job_type") != "digitacao_030104" or str(job.get("created_by") or "") != created_by:
                continue
            payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
            digitacao = payload.get("digitacao") if isinstance(payload.get("digitacao"), Mapping) else {}
            pedidos = digitacao.get("pedidos") if isinstance(digitacao.get("pedidos"), list) else []
            pedido = pedidos[0] if pedidos and isinstance(pedidos[0], Mapping) else {}
            result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
            detail = _pedido_execution_detail(result, pedido)
            jobs.append({
                "id": str(job.get("id") or ""),
                "status": str(job.get("status") or "pending"),
                "cliente": str(pedido.get("cliente") or "-"),
                "motivo_digitacao": str(pedido.get("motivo_digitacao") or ""),
                "created_at": job.get("created_at"),
                "started_at": job.get("started_at"),
                "finished_at": job.get("finished_at"),
                "message": str(result.get("message") or job.get("error") or job.get("failure_reason") or "Aguardando execução."),
                "detail": detail,
            })
            if len(jobs) >= limit:
                break
        record_security_event(
            request,
            channel="api",
            event_type="admin_pedidos_jobs",
            decision="allowed",
            reason=f"created_by={created_by};total={len(jobs)}",
        )
        return {"ok": True, "jobs": jobs, "total": len(jobs)}

    @router.post("/api/admin/pedidos/jobs", status_code=202)
    def criar_pedido(
        request: Request,
        payload: PedidoCreateRequest,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = context_for_pedidos(request, authorization, x_api_token, x_admin_token)
        filial = str(payload.filial)
        unidade = _UNIT_BY_FILIAL.get(filial)
        if not unidade:
            raise HTTPException(status_code=422, detail="Filial sem unidade Promax mapeada.")
        config = promax_jobs_service.get_pedido_digitacao_config()
        if payload.motivo_digitacao not in set(config["motivos"]):
            raise HTTPException(status_code=422, detail="O motivo escolhido não está liberado no gerencial de pedidos.")
        limits_by_product = {str(item.get("produto")): int(item.get("limite") or 0) for item in config.get("limites_por_produto") or []}
        for item in payload.itens:
            limit = limits_by_product.get(item.produto, int(config["max_caixas_por_produto"]))
            if item.quantidade > limit:
                raise HTTPException(status_code=422, detail=f"Produto {item.produto}: máximo de {limit:,} caixa(s) por pedido.")
        scopes = None if bool(context.get("is_admin")) else list(_seller_scopes(context))
        cliente = _load_authorized_client(
            dclientes_query_service,
            filial=filial,
            cliente=payload.cliente,
            scopes=scopes,
        )
        inadimplencia = _load_inadimplencia(
            inadimplencia_query_service,
            filial=filial,
            cliente=payload.cliente,
            scopes=scopes,
        )
        if inadimplencia["bloqueado"]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cliente possui títulos em aberto na 12.06.01. "
                    "A digitação de pedido está bloqueada até a regularização."
                ),
            )
        vendedor = str(cliente.vendedor or "").strip()
        if not vendedor:
            raise HTTPException(status_code=422, detail="Cliente sem vendedor/setor na dClientes. O pedido não foi enviado.")
        produtos = [item.produto for item in payload.itens]
        if len(set(produtos)) != len(produtos):
            raise HTTPException(status_code=422, detail="Não inclua o mesmo produto duas vezes no pedido.")
        try:
            estoque = cora_estoque_query_service.availability(
                filial=filial,
                products=[{"produto": item.produto, "quantidade": item.quantidade} for item in payload.itens],
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Não foi possível consultar a grade de estoque. O pedido não foi enviado por segurança.") from exc
        if not estoque.get("ready"):
            raise HTTPException(status_code=409, detail="Não existe grade Stock_Product atualizada para esta filial. Importe o relatório do Cora antes de digitar pedidos.")
        if not estoque.get("ok"):
            detalhes = []
            for item in estoque.get("indisponiveis", []):
                produto = str(item.get("produto") or "")
                motivo = str(item.get("motivo") or "indisponível")
                saldo = item.get("saldo_disponivel")
                detalhes.append(f"{produto}: {motivo}{f' Saldo: {saldo}.' if saldo is not None else ''}")
            raise HTTPException(
                status_code=409,
                detail="Pedido bloqueado pela grade de estoque atual. " + " ".join(detalhes[:8]),
            )
        pedido = {
            "ref": f"painel-{context.get('user_id') or 'admin'}-{filial}-{payload.cliente}",
            # Cada envio é um novo pedido. O mapa é apenas uma referência interna
            # para o Promax e não é escolhido nem exposto ao vendedor.
            "mapa": "NOVO1",
            "vendedor": vendedor,
            "gv": str(getattr(cliente, "gv", "") or ""),
            "cliente": payload.cliente,
            "cond_pagto": payload.cond_pagto,
            "motivo_digitacao": payload.motivo_digitacao,
            "itens": [{"produto": item.produto, "quantidade": item.quantidade, "preco": item.preco} for item in payload.itens],
        }
        job = promax_jobs_service.enqueue_job(
            job_type="digitacao_030104",
            payload={"operation": "digitacao_030104", "unidade": unidade, "target_worker_id": payload.target_worker_id, "digitacao": {"unidade": unidade, "pedidos": [pedido]}},
            priority=80,
            created_by=_pedido_created_by(context),
        )
        record_security_event(request, channel="api", event_type="admin_pedidos_create", decision="allowed", reason=f"filial={filial};cliente={payload.cliente};motivo={payload.motivo_digitacao};itens={len(payload.itens)}")
        record_action(request, context, "enviar_pedido", filial=filial, cliente=payload.cliente, vendedor=vendedor, motivo=payload.motivo_digitacao, itens=len(payload.itens), job_id=str(job.get("id") or ""))
        return {"ok": True, "job": job, "cliente": _client_payload(cliente), "unidade": unidade}

    return router


def _seller_scopes(context: Mapping[str, Any]) -> tuple[str, ...]:
    values = context.get("seller_scopes") or ()
    scopes: list[str] = []
    for item in values:
        normalized = normalize_stored_scope_value(str(item))
        pair = split_scope_pair(normalized)
        if not pair:
            continue
        scope = f"{pair[0]}-{pair[1]}"
        if scope not in scopes:
            scopes.append(scope)
    return tuple(scopes)


def _pedido_created_by(context: Mapping[str, Any]) -> str:
    return str(context.get("username") or context.get("user_id") or "painel")


def _pedido_execution_detail(result: Mapping[str, Any], pedido: Mapping[str, Any]) -> str:
    """Retorna a causa do Promax para o pedido, quando ela estiver disponível."""
    metadata = result.get("metadata") if isinstance(result.get("metadata"), Mapping) else {}
    results = metadata.get("pedidos") if isinstance(metadata.get("pedidos"), list) else []
    expected_ref = str(pedido.get("ref") or "").strip()
    for item in results:
        if not isinstance(item, Mapping):
            continue
        if expected_ref and str(item.get("ref") or "").strip() != expected_ref:
            continue
        detail = str(item.get("motivo") or item.get("erro") or item.get("mensagem") or "").strip()
        if not detail:
            continue
        detail = detail.replace("Adicionar item: Promax respondeu", "").strip()
        detail = detail.replace("\\n", " ").replace("\n", " ").replace("\\", " ")
        detail = " ".join(detail.strip(" []'").split())
        return detail
    return ""


def _item_total(item: Mapping[str, Any]) -> Decimal:
    raw_price = str(item.get("preco") or "0").strip().replace("R$", "").replace(" ", "")
    if "," in raw_price and "." in raw_price:
        raw_price = raw_price.replace(".", "").replace(",", ".") if raw_price.rfind(",") > raw_price.rfind(".") else raw_price.replace(",", "")
    else:
        raw_price = raw_price.replace(",", ".")
    try:
        return Decimal(raw_price or "0") * Decimal(int(item.get("quantidade") or 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _group_count(rows: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key) or "Sem informação")
        counts[label] = counts.get(label, 0) + 1
    return [{"label": label, "value": value} for label, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _filter_values(rows: Sequence[Mapping[str, Any]], key: str) -> list[str]:
    return sorted({str(row.get(key) or "").strip() for row in rows if str(row.get(key) or "").strip()})


def _group_count_by_day(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        day = str(row.get("criado_em") or "")[:10]
        if len(day) == 10:
            counts[day] = counts.get(day, 0) + 1
    return [{"date": day, "value": value} for day, value in sorted(counts.items())]


def _load_authorized_client(
    service: Any,
    *,
    filial: str,
    cliente: str,
    scopes: list[str] | None,
) -> Any:
    try:
        rows = service.search_by_registration(str(filial), str(cliente), allowed_sectors=scopes)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc
    if not rows:
        raise HTTPException(status_code=403, detail="Cliente não encontrado na carteira autorizada para este usuário.")
    return rows[0]


def _load_inadimplencia(
    service: Any,
    *,
    filial: str,
    cliente: str,
    scopes: list[str] | None,
) -> dict[str, Any]:
    try:
        rows = service.search_by_registration(str(filial), str(cliente), allowed_sectors=scopes, limit=50)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503 if isinstance(exc, RuntimeError) else 422,
            detail=(
                "Não foi possível validar a inadimplência na 12.06.01. "
                "O pedido não foi enviado por segurança."
            ),
        ) from exc
    titles = [
        {
            "nota_fiscal": str(row.nota_fiscal or ""),
            "vencimento": str(row.data_vencimento or ""),
            "valor_pendente": str(row.valor_pendente or ""),
            "dias": str(row.dias or ""),
        }
        for row in rows
    ]
    return {
        "bloqueado": bool(titles),
        "quantidade_titulos": len(titles),
        "titulos": titles,
    }


def _client_payload(row: Any) -> dict[str, str]:
    return {
        "filial": str(row.filial),
        "cliente": str(row.cod_pdv),
        "nome": str(row.nome_fantasia or row.razao_social),
        "razao_social": str(row.razao_social),
        "cidade": str(row.cidade),
        "telefone": str(row.telefone),
        "dia_visita": str(row.dia_visita),
        "vendedor": str(row.vendedor),
        "gv": str(getattr(row, "gv", "") or ""),
        "cond_pagto": str(row.cond_pag_atual),
        "status": str(row.status),
        "limite_credito": str(row.limite_credito),
        "total_pendente": str(row.total_pendente),
        "comodatos_pendentes": str(row.total_comodatos_pendentes),
        "atualizado_em": str(row.ultima_atualizacao_tabela),
    }


def _load_promax_conditions_catalog(unidade: str, jobs_service: Any | None = None) -> dict[str, Any]:
    """Obtém a lista retornada pelo robô, persistida no resultado mais recente da 03.01.04."""
    if jobs_service is not None:
        try:
            for job in jobs_service.list_jobs(limit=500):
                if str(job.get("job_type") or "") != "digitacao_030104":
                    continue
                payload = job.get("payload") if isinstance(job.get("payload"), Mapping) else {}
                digitacao = payload.get("digitacao") if isinstance(payload, Mapping) else {}
                if not isinstance(digitacao, Mapping):
                    digitacao = {}
                if str(digitacao.get("unidade") or payload.get("unidade") or "") != unidade:
                    continue
                result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
                metadata = result.get("metadata") if isinstance(result, Mapping) else {}
                catalogo = metadata.get("catalogo") if isinstance(metadata, Mapping) else None
                parsed = _normalize_conditions_catalog(catalogo, updated_at=str(job.get("finished_at") or "") or None)
                if parsed["condicoes"]:
                    return parsed
        except Exception:
            # A indisponibilidade do histórico não deve impedir o uso da condição padrão.
            pass

    # Fallback para o host Windows: o mesmo arquivo é gravado pelo robô no fim da leitura.
    driver_dir = Path(
        os.environ.get("PROMAX_DRIVER_DIR")
        or Path(__file__).resolve().parents[2] / "promax-web-driver"
    ).expanduser()
    path = driver_dir / "data" / "catalogos" / f"030104_condicoes_{unidade}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {
            "condicoes": [],
            "atualizado_em": None,
            "disponivel": False,
            "mensagem": "O robô ainda não retornou a lista de condições desta unidade.",
        }
    except (OSError, json.JSONDecodeError):
        return {
            "condicoes": [],
            "atualizado_em": None,
            "disponivel": False,
            "mensagem": "A lista de condições retornada pelo robô está inválida.",
        }
    return _normalize_conditions_catalog(raw)


def _normalize_conditions_catalog(raw: Any, *, updated_at: str | None = None) -> dict[str, Any]:
    rows = raw.get("condicoes") if isinstance(raw, Mapping) else None
    conditions: list[dict[str, str]] = []
    seen: set[str] = set()
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            code = str(item.get("codigo") or "").strip()
            description = str(item.get("descricao") or "").strip()
            if not code.isdigit() or code in seen:
                continue
            seen.add(code)
            conditions.append({"codigo": code, "descricao": description})
    conditions.sort(key=lambda item: (int(item["codigo"]), item["descricao"]))
    return {
        "condicoes": conditions,
        "atualizado_em": updated_at or (str(raw.get("lido_em") or "") or None if isinstance(raw, Mapping) else None),
        "disponivel": bool(conditions),
        "mensagem": "" if conditions else "O robô não retornou condições válidas para esta unidade.",
    }
