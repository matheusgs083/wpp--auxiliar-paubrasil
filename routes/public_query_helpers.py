from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request


def run_scoped_report_query(
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
    ensure_decision_allowed(request, decision, record_security_event)
    unrestricted_lookup, allowed_sectors, allowed_gv_vdes = scoped_lookup_parts(
        decision=decision,
        require_scope=True,
        decision_has_unrestricted_lookup_access=decision_has_unrestricted_lookup_access,
    )
    try:
        records = search_report_records(
            service=service,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            missing_detail=missing_detail,
            filial=filial,
            cod_pdv=cod_pdv,
            fantasia=fantasia,
            documento=documento,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    record_allowed_query(request, decision, query_event_type, len(records), record_security_event)
    return records


def authorize_scoped_query(
    *,
    request: Request,
    access_control: Any,
    number: str,
    area: str,
    require_scope: bool,
    decision_has_unrestricted_lookup_access: Callable[[Any], bool],
    record_security_event: Callable[..., None],
) -> tuple[Any, bool, list[str] | None, list[str] | None]:
    decision = access_control.authorize(phone_number=number, area=area)
    ensure_decision_allowed(request, decision, record_security_event)
    unrestricted_lookup, allowed_sectors, allowed_gv_vdes = scoped_lookup_parts(
        decision=decision,
        require_scope=require_scope,
        decision_has_unrestricted_lookup_access=decision_has_unrestricted_lookup_access,
    )
    return decision, unrestricted_lookup, allowed_sectors, allowed_gv_vdes


def ensure_decision_allowed(request: Request, decision: Any, record_security_event: Callable[..., None]) -> None:
    if decision.allowed:
        return
    record_denied_access(request, decision, record_security_event)
    raise HTTPException(status_code=403, detail=f"Acesso negado: {decision.reason}")


def scoped_lookup_parts(
    *,
    decision: Any,
    require_scope: bool,
    decision_has_unrestricted_lookup_access: Callable[[Any], bool],
) -> tuple[bool, list[str] | None, list[str] | None]:
    unrestricted_lookup = decision_has_unrestricted_lookup_access(decision)
    if require_scope:
        require_scoped_lookup_if_restricted(decision, unrestricted_lookup)
    allowed_sectors = None if unrestricted_lookup else list(decision.sectors)
    allowed_gv_vdes = None if unrestricted_lookup else list(decision.gv_vdes)
    return unrestricted_lookup, allowed_sectors, allowed_gv_vdes


def search_dclientes_records(
    *,
    service: Any,
    decision: Any,
    unrestricted_lookup: bool,
    allowed_sectors: list[str] | None,
    allowed_gv_vdes: list[str] | None,
    filial: str | None,
    cod_pdv: str | None,
    fantasia: str | None,
    documento: str | None,
) -> list[Any]:
    if documento and documento.strip():
        return service.search_by_document(
            document=documento,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=20,
        )
    if filial and cod_pdv:
        require_scoped_lookup_if_restricted(decision, unrestricted_lookup)
        return service.search_by_registration(
            filial=filial,
            cod_pdv=cod_pdv,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
        )
    if fantasia and fantasia.strip():
        require_scoped_lookup_if_restricted(decision, unrestricted_lookup)
        return service.search_by_fantasia(
            query_text=fantasia,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=5,
        )
    raise HTTPException(status_code=400, detail="Informe filial + cod_pdv, fantasia ou documento para pesquisar no dClientes.")


def search_report_records(
    *,
    service: Any,
    allowed_sectors: list[str] | None,
    allowed_gv_vdes: list[str] | None,
    missing_detail: str,
    filial: str | None,
    cod_pdv: str | None,
    fantasia: str | None,
    documento: str | None,
) -> list[Any]:
    if filial and cod_pdv:
        return service.search_by_registration(
            filial=filial,
            cod_pdv=cod_pdv,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=50,
        )
    if fantasia and fantasia.strip():
        return service.search_by_name(
            query_text=fantasia,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=50,
        )
    if documento and documento.strip():
        return service.search_by_document(
            document=documento,
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=50,
        )
    raise HTTPException(status_code=400, detail=missing_detail)


def record_denied_access(request: Request, decision: Any, record_security_event: Callable[..., None]) -> None:
    record_security_event(
        request,
        channel="api",
        event_type="rbac_access",
        decision="denied",
        phone_number=decision.normalized_number,
        area=decision.area,
        reason=decision.reason,
    )


def record_allowed_query(
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


def require_scoped_lookup_if_restricted(decision: Any, unrestricted_lookup: bool) -> None:
    if not unrestricted_lookup and not decision.sectors and not decision.gv_vdes:
        raise HTTPException(status_code=403, detail="Numero autorizado, mas sem escopo comercial vinculado.")


def query_response(decision: Any, records: list[Any]) -> dict[str, Any]:
    return {
        "total": len(records),
        "number": decision.normalized_number,
        "roles": list(decision.roles),
        "sectors": list(decision.sectors),
        "gv_vdes": list(decision.gv_vdes),
        "results": [record.to_dict() for record in records],
    }
