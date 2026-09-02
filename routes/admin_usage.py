from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse


def create_admin_usage_router(
    *,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    list_admin_evolution_usage: Callable[..., dict[str, Any]],
    build_evolution_usage_avg_report_csv: Callable[[dict[str, Any]], str],
    build_evolution_function_usage_report_csv: Callable[..., str],
    record_security_event: Callable[..., None],
    list_admin_panel_audit_actions: Callable[..., dict[str, Any]] | None = None,
    build_admin_panel_audit_report_csv: Callable[[dict[str, Any]], str] | None = None,
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()

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
            module="uso",
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
        )

    @router.get("/api/admin/usage/evolution")
    def api_admin_usage_evolution(
        request: Request,
        days: int = Query(default=7, ge=1, le=30),
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "usage")
        payload = list_admin_evolution_usage(days=days, function_date_from=date_from, function_date_to=date_to)
        record_security_event(
            request,
            channel="api",
            event_type="admin_usage_evolution",
            decision="allowed",
            reason=f"days={payload.get('window_days')}",
        )
        return payload

    @router.get("/api/admin/usage/evolution/report", response_class=PlainTextResponse)
    def api_admin_usage_evolution_report(
        request: Request,
        days: int = Query(default=7, ge=1, le=30),
        limit: int = Query(default=2000, ge=1, le=5000),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> PlainTextResponse:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "usage")
        payload = list_admin_evolution_usage(days=days, top_limit=limit, recent_limit=5)
        csv_content = build_evolution_usage_avg_report_csv(payload)
        generated_at = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"relatorio_media_msg_por_dia_{payload.get('window_days', days)}d_{generated_at}.csv"
        record_security_event(
            request,
            channel="api",
            event_type="admin_usage_evolution_report",
            decision="allowed",
            reason=f"days={payload.get('window_days')};limit={limit}",
        )
        record_panel_action(
            request,
            context,
            action="exportar_media_mensagens_csv",
            target_type="periodo",
            target_id=f"{payload.get('window_days', days)}d",
            metadata={"limit": limit, "filename": filename},
        )
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/api/admin/usage/evolution/functions/report", response_class=PlainTextResponse)
    def api_admin_usage_evolution_functions_report(
        request: Request,
        days: int = Query(default=7, ge=1, le=30),
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
        feature: str | None = Query(default=None),
        limit: int = Query(default=5000, ge=1, le=5000),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> PlainTextResponse:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "usage")
        payload = list_admin_evolution_usage(
            days=days,
            top_limit=limit,
            recent_limit=5,
            function_date_from=date_from,
            function_date_to=date_to,
        )
        selected_feature = str(feature or "").strip()
        csv_content = build_evolution_function_usage_report_csv(payload, feature_code=selected_feature)
        generated_at = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        feature_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", selected_feature).strip("_") or "todas"
        filename = (
            f"numero_x_funcao_evolution_"
            f"{payload.get('function_date_from', '')}_a_{payload.get('function_date_to', '')}_{feature_slug}_{generated_at}.csv"
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_usage_evolution_functions_report",
            decision="allowed",
            reason=f"days={payload.get('window_days')};limit={limit};feature={selected_feature or '*'}",
        )
        record_panel_action(
            request,
            context,
            action="exportar_numero_funcao_csv",
            target_type="periodo",
            target_id=f"{payload.get('function_date_from', '')}..{payload.get('function_date_to', '')}",
            metadata={"feature": selected_feature or "*", "limit": limit, "filename": filename},
        )
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get("/api/admin/usage/panel-actions")
    def api_admin_usage_panel_actions(
        request: Request,
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
        username: str | None = Query(default=None),
        module: str | None = Query(default=None),
        action: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "usage")
        if list_admin_panel_audit_actions is None:
            raise HTTPException(status_code=503, detail="Auditoria do painel nao configurada.")
        payload = list_admin_panel_audit_actions(
            date_from=date_from,
            date_to=date_to,
            username=username,
            module=module,
            action=action,
            status=status,
            limit=limit,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_usage_panel_actions",
            decision="allowed",
            reason=f"limit={payload.get('limit')};total={payload.get('total')}",
        )
        return payload

    @router.get("/api/admin/usage/panel-actions/report", response_class=PlainTextResponse)
    def api_admin_usage_panel_actions_report(
        request: Request,
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
        username: str | None = Query(default=None),
        module: str | None = Query(default=None),
        action: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=5000, ge=1, le=5000),
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> PlainTextResponse:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        require_admin_panel_feature(context, "usage")
        if list_admin_panel_audit_actions is None or build_admin_panel_audit_report_csv is None:
            raise HTTPException(status_code=503, detail="Auditoria do painel nao configurada.")
        payload = list_admin_panel_audit_actions(
            date_from=date_from,
            date_to=date_to,
            username=username,
            module=module,
            action=action,
            status=status,
            limit=limit,
        )
        csv_content = build_admin_panel_audit_report_csv(payload)
        generated_at = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"acoes_painel_{payload.get('date_from', '')}_a_{payload.get('date_to', '')}_{generated_at}.csv"
        record_security_event(
            request,
            channel="api",
            event_type="admin_usage_panel_actions_report",
            decision="allowed",
            reason=f"limit={payload.get('limit')};total={payload.get('total')}",
        )
        record_panel_action(
            request,
            context,
            action="exportar_acoes_painel_csv",
            target_type="periodo",
            target_id=f"{payload.get('date_from', '')}..{payload.get('date_to', '')}",
            metadata={"total": payload.get("total"), "limit": payload.get("limit"), "filename": filename},
        )
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
