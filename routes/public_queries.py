from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from bot_api.routes.public_query_helpers import (
    authorize_scoped_query,
    query_response,
    record_allowed_query,
    run_scoped_report_query,
    search_dclientes_records,
)


def create_public_queries_router(
    *,
    access_control: Any,
    dclientes_query_service: Any,
    inadimplencia_query_service: Any,
    comodatos_query_service: Any,
    require_api_auth: Callable[..., None],
    require_admin_scope_for_number_routes: Callable[..., None],
    decision_has_unrestricted_lookup_access: Callable[[Any], bool],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def require_auth(
        *,
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
        x_admin_token: str | None,
    ) -> None:
        require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
        require_admin_scope_for_number_routes(request=request, x_admin_token=x_admin_token)

    @router.get("/api/client-search")
    def api_client_search(
        request: Request,
        q: str,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
        if not q.strip():
            raise HTTPException(status_code=400, detail="Parametro q e obrigatorio.")
        record_security_event(
            request,
            channel="api",
            event_type="client_search",
            decision="deprecated",
            reason="legacy_route_disabled",
        )
        return {
            "handled": False,
            "intent": "legacy_route_disabled",
            "reply": "Essa rota antiga foi desativada. Use /api/dclientes/search ou o fluxo principal do bot.",
        }

    @router.get("/api/dclientes/search")
    def api_dclientes_search(
        request: Request,
        number: str,
        filial: str | None = None,
        cod_pdv: str | None = None,
        fantasia: str | None = None,
        documento: str | None = None,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        decision, unrestricted_lookup, allowed_sectors, allowed_gv_vdes = authorize_scoped_query(
            request=request,
            access_control=access_control,
            number=number,
            area="cliente",
            require_scope=False,
            decision_has_unrestricted_lookup_access=decision_has_unrestricted_lookup_access,
            record_security_event=record_security_event,
        )
        try:
            records = search_dclientes_records(
                service=dclientes_query_service,
                decision=decision,
                unrestricted_lookup=unrestricted_lookup,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                filial=filial,
                cod_pdv=cod_pdv,
                fantasia=fantasia,
                documento=documento,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        record_allowed_query(request, decision, "customer_query", len(records), record_security_event)
        return query_response(decision, records)

    @router.get("/api/inadimplencia/search")
    def api_inadimplencia_search(
        request: Request,
        number: str,
        filial: str | None = None,
        cod_pdv: str | None = None,
        fantasia: str | None = None,
        documento: str | None = None,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        decision = access_control.authorize(phone_number=number, area="inadimplencia")
        records = run_scoped_report_query(
            request=request,
            decision=decision,
            service=inadimplencia_query_service,
            query_event_type="inadimplencia_query",
            missing_detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar na inadimplencia.",
            filial=filial,
            cod_pdv=cod_pdv,
            fantasia=fantasia,
            documento=documento,
            decision_has_unrestricted_lookup_access=decision_has_unrestricted_lookup_access,
            record_security_event=record_security_event,
        )
        return query_response(decision, records)

    @router.get("/api/comodatos/search")
    def api_comodatos_search(
        request: Request,
        number: str,
        filial: str | None = None,
        cod_pdv: str | None = None,
        fantasia: str | None = None,
        documento: str | None = None,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        decision = access_control.authorize(phone_number=number, area="comodato")
        records = run_scoped_report_query(
            request=request,
            decision=decision,
            service=comodatos_query_service,
            query_event_type="comodatos_query",
            missing_detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar nos comodatos.",
            filial=filial,
            cod_pdv=cod_pdv,
            fantasia=fantasia,
            documento=documento,
            decision_has_unrestricted_lookup_access=decision_has_unrestricted_lookup_access,
            record_security_event=record_security_event,
        )
        return query_response(decision, records)

    @router.get("/api/access/check")
    def api_access_check(
        request: Request,
        number: str,
        area: str = "conhecimento",
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        decision = access_control.authorize(phone_number=number, area=area)
        record_security_event(
            request,
            channel="api",
            event_type="access_check",
            decision="allowed" if decision.allowed else "denied",
            phone_number=decision.normalized_number,
            area=decision.area,
            reason=decision.reason,
        )
        return {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "normalized_number": decision.normalized_number,
            "area": decision.area,
            "roles": list(decision.roles),
            "sectors": list(decision.sectors),
            "gv_vdes": list(decision.gv_vdes),
        }

    return router
