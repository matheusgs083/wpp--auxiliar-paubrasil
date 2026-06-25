from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request


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
        decision = access_control.authorize(phone_number=number, area="cliente")
        if not decision.allowed:
            _record_denied_access(request, decision, record_security_event)
            raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")

        unrestricted_lookup = decision_has_unrestricted_lookup_access(decision)
        allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
        allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
        try:
            if documento and documento.strip():
                records = dclientes_query_service.search_by_document(
                    document=documento,
                    allowed_sectors=allowed_sectors,
                    allowed_gv_vdes=allowed_gv_vdes,
                    limit=20,
                )
            elif filial and cod_pdv:
                _require_scoped_lookup_if_restricted(decision, unrestricted_lookup)
                records = dclientes_query_service.search_by_registration(
                    filial=filial,
                    cod_pdv=cod_pdv,
                    allowed_sectors=allowed_sectors,
                    allowed_gv_vdes=allowed_gv_vdes,
                )
            elif fantasia and fantasia.strip():
                _require_scoped_lookup_if_restricted(decision, unrestricted_lookup)
                records = dclientes_query_service.search_by_fantasia(
                    query_text=fantasia,
                    allowed_sectors=allowed_sectors,
                    allowed_gv_vdes=allowed_gv_vdes,
                    limit=5,
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar no dClientes.",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        _record_allowed_query(request, decision, "customer_query", len(records), record_security_event)
        return _query_response(decision, records)

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
        records = _run_scoped_report_query(
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
        return _query_response(decision, records)

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
        records = _run_scoped_report_query(
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
        return _query_response(decision, records)

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


def _run_scoped_report_query(
    *,
    request: Request,
    decision: Any,
    service: Any,
    query_event_type: str,
    missing_detail: str,
    filial: str | None,
    cod_pdv: str | None,
    fantasia: str | None,
    documento: str | None,
    decision_has_unrestricted_lookup_access: Callable[[Any], bool],
    record_security_event: Callable[..., None],
) -> list[Any]:
    if not decision.allowed:
        _record_denied_access(request, decision, record_security_event)
        raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")
    unrestricted_lookup = decision_has_unrestricted_lookup_access(decision)
    _require_scoped_lookup_if_restricted(decision, unrestricted_lookup)
    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    try:
        if filial and cod_pdv:
            records = service.search_by_registration(
                filial=filial,
                cod_pdv=cod_pdv,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif fantasia and fantasia.strip():
            records = service.search_by_name(
                query_text=fantasia,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        elif documento and documento.strip():
            records = service.search_by_document(
                document=documento,
                allowed_sectors=allowed_sectors,
                allowed_gv_vdes=allowed_gv_vdes,
                limit=50,
            )
        else:
            raise HTTPException(status_code=400, detail=missing_detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    _record_allowed_query(request, decision, query_event_type, len(records), record_security_event)
    return records


def _record_denied_access(request: Request, decision: Any, record_security_event: Callable[..., None]) -> None:
    record_security_event(
        request,
        channel="api",
        event_type="rbac_access",
        decision="denied",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason=decision.reason,
    )


def _record_allowed_query(
    request: Request,
    decision: Any,
    event_type: str,
    result_count: int,
    record_security_event: Callable[..., None],
) -> None:
    record_security_event(
        request,
        channel="api",
        event_type=event_type,
        decision="allowed",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason="success",
        result_count=result_count,
    )


def _require_scoped_lookup_if_restricted(decision: Any, unrestricted_lookup: bool) -> None:
    if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
        raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")


def _query_response(decision: Any, records: list[Any]) -> dict[str, Any]:
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }
