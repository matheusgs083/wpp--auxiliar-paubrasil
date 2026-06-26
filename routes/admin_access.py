from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from bot_api.routes.admin_access_bulk import bulk_upsert_access_users
from bot_api.routes.admin_access_schemas import AccessRoleUpsertRequest, AccessUserBulkUpsertRequest, AccessUserUpsertRequest
from bot_api.security.access_control import AccessControl


def create_admin_access_router(
    *,
    access_control: AccessControl,
    access_call: Callable[..., Any],
    require_admin_api_auth: Callable[..., None],
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
        require_admin_api_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )

    @router.get("/api/admin/access/users")
    def api_admin_access_users(
        request: Request,
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
        users = access_call(access_control.list_users)
        record_security_event(request, channel="api", event_type="admin_list_users", decision="allowed", reason="success")
        return {"total": len(users), "users": users}

    @router.post("/api/admin/access/users")
    def api_admin_access_users_upsert(
        request: Request,
        payload: AccessUserUpsertRequest,
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
        user = access_call(
            access_control.upsert_user,
            phone_number=payload.phone_number,
            name=payload.name,
            is_active=payload.is_active,
            roles=payload.roles,
            sectors=payload.sectors,
            gv_vdes=payload.gv_vdes,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_upsert_user",
            decision="allowed",
            phone_number=user.get("phone_number"),
            reason="success",
        )
        return {"ok": True, "user": user}

    @router.post("/api/admin/access/users/bulk")
    def api_admin_access_users_bulk_upsert(
        request: Request,
        payload: AccessUserBulkUpsertRequest,
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

        users_payload = list(payload.users or [])
        if not users_payload:
            raise HTTPException(status_code=400, detail="Informe ao menos um cadastro para o lote.")
        if len(users_payload) > 500:
            raise HTTPException(status_code=400, detail="O lote permite no maximo 500 cadastros por envio.")

        saved_users, errors = bulk_upsert_access_users(
            access_control=access_control,
            users_payload=users_payload,
            continue_on_error=payload.continue_on_error,
        )

        decision = "allowed" if not errors else ("partial" if saved_users else "failed")
        record_security_event(
            request,
            channel="api",
            event_type="admin_bulk_upsert_users",
            decision=decision,
            reason=f"saved={len(saved_users)} errors={len(errors)}",
        )
        return {
            "ok": not errors,
            "total_received": len(users_payload),
            "total_saved": len(saved_users),
            "total_failed": len(errors),
            "saved": saved_users,
            "errors": errors,
        }

    @router.delete("/api/admin/access/users/{phone_number}")
    def api_admin_access_users_delete(
        request: Request,
        phone_number: str,
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
        user = access_call(access_control.delete_user, phone_number=phone_number)
        record_security_event(
            request,
            channel="api",
            event_type="admin_delete_user",
            decision="allowed",
            phone_number=user.get("phone_number"),
            reason="success",
        )
        return {"ok": True, "user": user}

    @router.get("/api/admin/access/roles")
    def api_admin_access_roles(
        request: Request,
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
        roles = access_call(access_control.list_roles)
        record_security_event(request, channel="api", event_type="admin_list_roles", decision="allowed", reason="success")
        return {"total": len(roles), "roles": roles}

    @router.get("/api/admin/access/permissions")
    def api_admin_access_permissions(
        request: Request,
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
        permissions = access_call(access_control.list_permissions)
        record_security_event(request, channel="api", event_type="admin_list_permissions", decision="allowed", reason="success")
        return {"total": len(permissions), "permissions": permissions}

    @router.post("/api/admin/access/roles")
    def api_admin_access_roles_upsert(
        request: Request,
        payload: AccessRoleUpsertRequest,
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
        role = access_call(
            access_control.upsert_role,
            role_name=payload.name,
            description=payload.description,
            permissions=payload.permissions,
        )
        record_security_event(
            request,
            channel="api",
            event_type="admin_upsert_role",
            decision="allowed",
            reason=role.get("name"),
        )
        return {"ok": True, "role": role}

    @router.post("/api/admin/access/seed")
    def api_admin_access_seed(
        request: Request,
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
        result = access_call(access_control.seed_defaults)
        if not result.get("ok"):
            raise HTTPException(status_code=503, detail=result.get("reason", "Falha ao inicializar RBAC."))
        record_security_event(request, channel="api", event_type="admin_seed", decision="allowed", reason="success")
        return result

    return router
