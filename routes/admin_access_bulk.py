from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from bot_api.routes.admin_access_schemas import AccessUserUpsertRequest
from bot_api.security.access_control import AccessControl


def bulk_upsert_access_users(
    *,
    access_control: AccessControl,
    users_payload: list[AccessUserUpsertRequest],
    continue_on_error: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    saved_users: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(users_payload, start=1):
        try:
            user = access_control.upsert_user(
                phone_number=item.phone_number,
                name=item.name,
                is_active=item.is_active,
                roles=item.roles,
                sectors=item.sectors,
                gv_vdes=item.gv_vdes,
            )
            saved_users.append({"line": index, "user": user})
        except ValueError as exc:
            append_bulk_user_error(errors, index=index, item=item, error=exc)
            if not continue_on_error:
                raise HTTPException(status_code=400, detail=f"Linha {index}: {exc}") from exc
        except RuntimeError as exc:
            append_bulk_user_error(errors, index=index, item=item, error=exc)
            if not continue_on_error:
                raise HTTPException(status_code=503, detail=f"Linha {index}: {exc}") from exc
    return saved_users, errors


def append_bulk_user_error(
    errors: list[dict[str, Any]],
    *,
    index: int,
    item: AccessUserUpsertRequest,
    error: Exception,
) -> None:
    errors.append(
        {
            "line": index,
            "phone_number": str(item.phone_number or "").strip(),
            "error": str(error),
        }
    )
