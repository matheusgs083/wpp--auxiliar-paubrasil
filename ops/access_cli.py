from __future__ import annotations

import argparse
import json
import shlex
import sys
import unicodedata
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot_api.config import get_settings
from bot_api.security.access_control import DEFAULT_ROLE_PERMISSIONS


class AdminApiClient:
    def __init__(self, base_url: str, admin_token: str, api_token: str, timeout_seconds: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token.strip()
        self.api_token = api_token.strip()
        self.timeout_seconds = timeout_seconds

    def status(self) -> dict[str, Any]:
        return self._get("/health")

    def seed_defaults(self) -> dict[str, Any]:
        return self._post("/api/admin/access/seed", admin=True)

    def list_users(self) -> list[dict[str, Any]]:
        payload = self._get("/api/admin/access/users", admin=True)
        return list(payload.get("users", []))

    def list_roles(self) -> list[dict[str, Any]]:
        payload = self._get("/api/admin/access/roles", admin=True)
        return list(payload.get("roles", []))

    def list_permissions(self) -> list[dict[str, Any]]:
        payload = self._get("/api/admin/access/permissions", admin=True)
        return list(payload.get("permissions", []))

    def authorize(self, phone_number: str, area: str) -> dict[str, Any]:
        return self._get("/api/access/check", params={"number": phone_number, "area": area})

    def upsert_user(
        self,
        phone_number: str,
        name: str | None,
        is_active: bool,
        roles: list[str],
        sectors: list[str],
        gv_vdes: list[str],
    ) -> dict[str, Any]:
        payload = self._post(
            "/api/admin/access/users",
            admin=True,
            json_body={
                "phone_number": phone_number,
                "name": name,
                "is_active": is_active,
                "roles": roles,
                "sectors": sectors,
                "gv_vdes": gv_vdes,
            },
        )
        return dict(payload.get("user", {}))

    def upsert_role(
        self,
        role_name: str,
        permissions: list[str],
        description: str | None,
    ) -> dict[str, Any]:
        payload = self._post(
            "/api/admin/access/roles",
            admin=True,
            json_body={
                "name": role_name,
                "description": description,
                "permissions": permissions,
            },
        )
        return dict(payload.get("role", {}))

    def _get(self, path: str, params: dict[str, Any] | None = None, admin: bool = False) -> dict[str, Any]:
        return self._request("GET", path, params=params, admin=admin)

    def _post(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
        admin: bool = False,
    ) -> dict[str, Any]:
        return self._request("POST", path, json_body=json_body, admin=admin)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        admin: bool = False,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        if admin and self.admin_token:
            headers["x-admin-token"] = self.admin_token

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(
                    method=method,
                    url=f"{self.base_url}{path}",
                    params=params,
                    json=json_body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Nao foi possivel conectar em {self.base_url}: {exc}") from exc

        if response.status_code >= 400:
            detail = _extract_error_detail(response)
            raise RuntimeError(f"HTTP {response.status_code}: {detail}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Resposta da API nao veio em JSON.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Resposta inesperada da API.")
        return payload


def main() -> None:
    args = _parse_args()
    client = _build_client(args.base_url, args.admin_token, args.api_token)

    if args.command == "shell":
        _run_shell(client)
        return

    _execute_and_print(client, args)


def _build_client(base_url: str | None, admin_token: str | None, api_token: str | None) -> AdminApiClient:
    settings = get_settings()
    resolved_host = "127.0.0.1" if settings.app_host in {"", "0.0.0.0"} else settings.app_host
    resolved_base_url = (base_url or f"http://{resolved_host}:{settings.app_port}").rstrip("/")
    resolved_token = admin_token if admin_token is not None else settings.admin_api_token
    resolved_api_token = api_token if api_token is not None else (settings.api_auth_tokens[0] if settings.api_auth_tokens else "")
    return AdminApiClient(base_url=resolved_base_url, admin_token=resolved_token, api_token=resolved_api_token)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Terminal administrativo do RBAC para usuarios, cargos e permissoes."
    )
    parser.add_argument(
        "--base-url",
        help="URL base do bot_api. Padrao: http://127.0.0.1:<APP_PORT>.",
    )
    parser.add_argument(
        "--admin-token",
        help="Sobrescreve o ADMIN_API_TOKEN do .env.",
    )
    parser.add_argument(
        "--api-token",
        help="Sobrescreve o primeiro token de API configurado em API_AUTH_TOKENS.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Mostra o status do RBAC e da API.")
    subparsers.add_parser("seed", help="Cria ou atualiza os cargos padrao.")
    subparsers.add_parser("defaults", help="Mostra os cargos padrao e suas permissoes.")

    users_parser = subparsers.add_parser("users", help="Lista usuarios cadastrados.")
    users_parser.add_argument("--number", help="Filtra por numero.")

    roles_parser = subparsers.add_parser("roles", help="Lista cargos cadastrados.")
    roles_parser.add_argument("--name", help="Filtra por nome do cargo.")

    subparsers.add_parser("permissions", help="Lista permissoes cadastradas.")

    check_parser = subparsers.add_parser("check", help="Valida se um numero tem acesso a uma area.")
    check_parser.add_argument("number", help="Numero do usuario.")
    check_parser.add_argument("--area", default="conhecimento", help="Area a validar.")

    user_set_parser = subparsers.add_parser(
        "user-set",
        help="Cria ou atualiza usuario. Mantem cargos atuais se nenhum --role for informado.",
    )
    user_set_parser.add_argument("number", help="Numero do usuario.")
    user_set_parser.add_argument("--name", help="Nome do usuario.")
    active_group = user_set_parser.add_mutually_exclusive_group()
    active_group.add_argument("--active", action="store_true", help="Marca o usuario como ativo.")
    active_group.add_argument("--inactive", action="store_true", help="Marca o usuario como inativo.")
    user_set_parser.add_argument(
        "--role",
        action="append",
        default=[],
        help="Cargo do usuario. Pode repetir a flag ou separar por virgula.",
    )
    user_set_parser.add_argument(
        "--clear-roles",
        action="store_true",
        help="Remove todos os cargos do usuario antes de salvar.",
    )
    user_set_parser.add_argument(
        "--sector",
        action="append",
        default=[],
        help="Setor VDE do usuario. Pode repetir a flag ou separar por virgula.",
    )
    user_set_parser.add_argument(
        "--clear-sectors",
        action="store_true",
        help="Remove todos os setores do usuario antes de salvar.",
    )
    user_set_parser.add_argument(
        "--gv-vde",
        action="append",
        default=[],
        help="GV VDE do usuario. Pode repetir a flag ou separar por virgula.",
    )
    user_set_parser.add_argument(
        "--clear-gv-vdes",
        action="store_true",
        help="Remove todos os GV VDEs do usuario antes de salvar.",
    )

    user_grant_parser = subparsers.add_parser(
        "user-grant-role",
        help="Adiciona um ou mais cargos ao usuario, sem remover os atuais.",
    )
    user_grant_parser.add_argument("number", help="Numero do usuario.")
    user_grant_parser.add_argument("roles", nargs="+", help="Cargos a adicionar.")
    user_grant_parser.add_argument("--name", help="Nome do usuario se for criar agora.")

    user_revoke_parser = subparsers.add_parser(
        "user-revoke-role",
        help="Remove um ou mais cargos do usuario, mantendo os demais.",
    )
    user_revoke_parser.add_argument("number", help="Numero do usuario.")
    user_revoke_parser.add_argument("roles", nargs="+", help="Cargos a remover.")

    user_grant_sector_parser = subparsers.add_parser(
        "user-grant-sector",
        help="Adiciona um ou mais setores ao usuario, sem remover os atuais.",
    )
    user_grant_sector_parser.add_argument("number", help="Numero do usuario.")
    user_grant_sector_parser.add_argument("sectors", nargs="+", help="Setores a adicionar.")
    user_grant_sector_parser.add_argument("--name", help="Nome do usuario se for criar agora.")

    user_revoke_sector_parser = subparsers.add_parser(
        "user-revoke-sector",
        help="Remove um ou mais setores do usuario, mantendo os demais.",
    )
    user_revoke_sector_parser.add_argument("number", help="Numero do usuario.")
    user_revoke_sector_parser.add_argument("sectors", nargs="+", help="Setores a remover.")

    user_grant_gv_vde_parser = subparsers.add_parser(
        "user-grant-gv-vde",
        help="Adiciona um ou mais GV VDEs ao usuario, sem remover os atuais.",
    )
    user_grant_gv_vde_parser.add_argument("number", help="Numero do usuario.")
    user_grant_gv_vde_parser.add_argument("gv_vdes", nargs="+", help="GV VDEs a adicionar.")
    user_grant_gv_vde_parser.add_argument("--name", help="Nome do usuario se for criar agora.")

    user_revoke_gv_vde_parser = subparsers.add_parser(
        "user-revoke-gv-vde",
        help="Remove um ou mais GV VDEs do usuario, mantendo os demais.",
    )
    user_revoke_gv_vde_parser.add_argument("number", help="Numero do usuario.")
    user_revoke_gv_vde_parser.add_argument("gv_vdes", nargs="+", help="GV VDEs a remover.")

    role_set_parser = subparsers.add_parser(
        "role-set",
        help="Cria ou atualiza cargo. Mantem permissoes atuais se nenhum --permission for informado.",
    )
    role_set_parser.add_argument("name", help="Nome do cargo.")
    role_set_parser.add_argument("--description", help="Descricao do cargo.")
    role_set_parser.add_argument(
        "--permission",
        action="append",
        default=[],
        help="Permissao do cargo. Pode repetir a flag ou separar por virgula.",
    )
    role_set_parser.add_argument(
        "--clear-permissions",
        action="store_true",
        help="Remove todas as permissoes do cargo antes de salvar.",
    )

    role_grant_parser = subparsers.add_parser(
        "role-grant",
        help="Adiciona uma ou mais permissoes a um cargo, sem remover as atuais.",
    )
    role_grant_parser.add_argument("name", help="Nome do cargo.")
    role_grant_parser.add_argument("permissions", nargs="+", help="Permissoes a adicionar.")
    role_grant_parser.add_argument("--description", help="Descricao do cargo.")

    role_revoke_parser = subparsers.add_parser(
        "role-revoke",
        help="Remove uma ou mais permissoes de um cargo, mantendo as demais.",
    )
    role_revoke_parser.add_argument("name", help="Nome do cargo.")
    role_revoke_parser.add_argument("permissions", nargs="+", help="Permissoes a remover.")

    subparsers.add_parser("shell", help="Abre um terminal interativo para administrar o RBAC.")

    return parser.parse_args(argv)


def _execute_and_print(client: AdminApiClient, args: argparse.Namespace) -> None:
    try:
        result = _dispatch(client, args)
    except Exception as exc:
        print(_to_json({"ok": False, "error": str(exc)}))
        raise SystemExit(1) from exc

    print(_to_json(result))


def _dispatch(client: AdminApiClient, args: argparse.Namespace) -> Any:
    if args.command == "status":
        return client.status()
    if args.command == "seed":
        return client.seed_defaults()
    if args.command == "defaults":
        return {"roles": DEFAULT_ROLE_PERMISSIONS}
    if args.command == "users":
        users = client.list_users()
        if args.number:
            number = _digits_only(args.number)
            users = [user for user in users if _digits_only(str(user.get("phone_number", ""))) == number]
        return {"total": len(users), "users": users}
    if args.command == "roles":
        roles = client.list_roles()
        if args.name:
            role_name = _normalize_token(args.name)
            roles = [role for role in roles if _normalize_token(str(role.get("name", ""))) == role_name]
        return {"total": len(roles), "roles": roles}
    if args.command == "permissions":
        permissions = client.list_permissions()
        return {"total": len(permissions), "permissions": permissions}
    if args.command == "check":
        return client.authorize(phone_number=args.number, area=args.area)
    if args.command == "user-set":
        return _handle_user_set(client, args)
    if args.command == "user-grant-role":
        return _handle_user_grant_role(client, args)
    if args.command == "user-revoke-role":
        return _handle_user_revoke_role(client, args)
    if args.command == "user-grant-sector":
        return _handle_user_grant_sector(client, args)
    if args.command == "user-revoke-sector":
        return _handle_user_revoke_sector(client, args)
    if args.command == "user-grant-gv-vde":
        return _handle_user_grant_gv_vde(client, args)
    if args.command == "user-revoke-gv-vde":
        return _handle_user_revoke_gv_vde(client, args)
    if args.command == "role-set":
        return _handle_role_set(client, args)
    if args.command == "role-grant":
        return _handle_role_grant(client, args)
    if args.command == "role-revoke":
        return _handle_role_revoke(client, args)
    raise ValueError(f"Comando nao suportado: {args.command}")


def _handle_user_set(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_user(client, args.number)
    roles = _unique_tokens(_split_csv_values(args.role))
    sectors = _unique_tokens(_split_sector_values(args.sector))
    gv_vdes = _unique_tokens(_split_scope_values(args.gv_vde))
    if args.clear_roles:
        resolved_roles: list[str] = []
    elif roles:
        resolved_roles = roles
    elif existing:
        resolved_roles = [str(role) for role in existing.get("roles", [])]
    else:
        resolved_roles = []

    if args.clear_sectors:
        resolved_sectors: list[str] = []
    elif sectors:
        resolved_sectors = sectors
    elif existing:
        resolved_sectors = [str(sector) for sector in existing.get("sectors", [])]
    else:
        resolved_sectors = []

    if args.clear_gv_vdes:
        resolved_gv_vdes: list[str] = []
    elif gv_vdes:
        resolved_gv_vdes = gv_vdes
    elif existing:
        resolved_gv_vdes = [str(gv_vde) for gv_vde in existing.get("gv_vdes", [])]
    else:
        resolved_gv_vdes = []

    if args.active:
        is_active = True
    elif args.inactive:
        is_active = False
    elif existing is not None:
        is_active = bool(existing.get("is_active", True))
    else:
        is_active = True

    if args.name is not None:
        name = args.name
    elif existing is not None:
        name = existing.get("name")
    else:
        name = None

    result = client.upsert_user(
        phone_number=args.number,
        name=name,
        is_active=is_active,
        roles=resolved_roles,
        sectors=resolved_sectors,
        gv_vdes=resolved_gv_vdes,
    )
    return {"ok": True, "user": result}


def _handle_user_grant_role(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_user(client, args.number)
    current_roles = [str(role) for role in (existing or {}).get("roles", [])]
    new_roles = _unique_tokens(current_roles + _split_csv_values(args.roles))
    name = args.name if args.name is not None else (existing or {}).get("name")
    is_active = bool((existing or {}).get("is_active", True))
    current_sectors = [str(sector) for sector in (existing or {}).get("sectors", [])]
    result = client.upsert_user(
        phone_number=args.number,
        name=name,
        is_active=is_active,
        roles=new_roles,
        sectors=current_sectors,
        gv_vdes=[str(gv_vde) for gv_vde in (existing or {}).get("gv_vdes", [])],
    )
    return {"ok": True, "user": result}


def _handle_user_revoke_role(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_user(client, args.number)
    if existing is None:
        raise ValueError("Usuario nao encontrado.")
    roles_to_remove = set(_split_csv_values(args.roles))
    current_roles = [str(role) for role in existing.get("roles", [])]
    new_roles = [role for role in current_roles if _normalize_token(role) not in roles_to_remove]
    result = client.upsert_user(
        phone_number=args.number,
        name=existing.get("name"),
        is_active=bool(existing.get("is_active", True)),
        roles=new_roles,
        sectors=[str(sector) for sector in existing.get("sectors", [])],
        gv_vdes=[str(gv_vde) for gv_vde in existing.get("gv_vdes", [])],
    )
    return {"ok": True, "user": result}


def _handle_user_grant_sector(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_user(client, args.number)
    current_roles = [str(role) for role in (existing or {}).get("roles", [])]
    current_sectors = [str(sector) for sector in (existing or {}).get("sectors", [])]
    new_sectors = _unique_tokens(current_sectors + _split_sector_values(args.sectors))
    name = args.name if args.name is not None else (existing or {}).get("name")
    is_active = bool((existing or {}).get("is_active", True))
    result = client.upsert_user(
        phone_number=args.number,
        name=name,
        is_active=is_active,
        roles=current_roles,
        sectors=new_sectors,
        gv_vdes=[str(gv_vde) for gv_vde in (existing or {}).get("gv_vdes", [])],
    )
    return {"ok": True, "user": result}


def _handle_user_revoke_sector(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_user(client, args.number)
    if existing is None:
        raise ValueError("Usuario nao encontrado.")
    sectors_to_remove = set(_split_sector_values(args.sectors))
    current_sectors = [str(sector) for sector in existing.get("sectors", [])]
    new_sectors = [sector for sector in current_sectors if _normalize_sector(sector) not in sectors_to_remove]
    result = client.upsert_user(
        phone_number=args.number,
        name=existing.get("name"),
        is_active=bool(existing.get("is_active", True)),
        roles=[str(role) for role in existing.get("roles", [])],
        sectors=new_sectors,
        gv_vdes=[str(gv_vde) for gv_vde in existing.get("gv_vdes", [])],
    )
    return {"ok": True, "user": result}


def _handle_user_grant_gv_vde(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_user(client, args.number)
    current_roles = [str(role) for role in (existing or {}).get("roles", [])]
    current_gv_vdes = [str(gv_vde) for gv_vde in (existing or {}).get("gv_vdes", [])]
    new_gv_vdes = _unique_tokens(current_gv_vdes + _split_scope_values(args.gv_vdes))
    name = args.name if args.name is not None else (existing or {}).get("name")
    is_active = bool((existing or {}).get("is_active", True))
    result = client.upsert_user(
        phone_number=args.number,
        name=name,
        is_active=is_active,
        roles=current_roles,
        sectors=[str(sector) for sector in (existing or {}).get("sectors", [])],
        gv_vdes=new_gv_vdes,
    )
    return {"ok": True, "user": result}


def _handle_user_revoke_gv_vde(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_user(client, args.number)
    if existing is None:
        raise ValueError("Usuario nao encontrado.")
    gv_vdes_to_remove = set(_split_scope_values(args.gv_vdes))
    current_gv_vdes = [str(gv_vde) for gv_vde in existing.get("gv_vdes", [])]
    new_gv_vdes = [gv_vde for gv_vde in current_gv_vdes if _normalize_scope_code(gv_vde) not in gv_vdes_to_remove]
    result = client.upsert_user(
        phone_number=args.number,
        name=existing.get("name"),
        is_active=bool(existing.get("is_active", True)),
        roles=[str(role) for role in existing.get("roles", [])],
        sectors=[str(sector) for sector in existing.get("sectors", [])],
        gv_vdes=new_gv_vdes,
    )
    return {"ok": True, "user": result}


def _handle_role_set(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_role(client, args.name)
    permissions = _unique_tokens(_split_csv_values(args.permission))
    if args.clear_permissions:
        resolved_permissions: list[str] = []
    elif permissions:
        resolved_permissions = permissions
    elif existing:
        resolved_permissions = [str(permission) for permission in existing.get("permissions", [])]
    else:
        resolved_permissions = []

    if args.description is not None:
        description = args.description
    elif existing is not None:
        description = existing.get("description")
    else:
        description = None

    result = client.upsert_role(
        role_name=args.name,
        permissions=resolved_permissions,
        description=description,
    )
    return {"ok": True, "role": result}


def _handle_role_grant(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_role(client, args.name)
    current_permissions = [str(permission) for permission in (existing or {}).get("permissions", [])]
    new_permissions = _unique_tokens(current_permissions + _split_csv_values(args.permissions))
    description = args.description if args.description is not None else (existing or {}).get("description")
    result = client.upsert_role(
        role_name=args.name,
        permissions=new_permissions,
        description=description,
    )
    return {"ok": True, "role": result}


def _handle_role_revoke(client: AdminApiClient, args: argparse.Namespace) -> dict[str, Any]:
    existing = _find_role(client, args.name)
    if existing is None:
        raise ValueError("Cargo nao encontrado.")
    permissions_to_remove = set(_split_csv_values(args.permissions))
    current_permissions = [str(permission) for permission in existing.get("permissions", [])]
    new_permissions = [
        permission for permission in current_permissions if _normalize_token(permission) not in permissions_to_remove
    ]
    result = client.upsert_role(
        role_name=args.name,
        permissions=new_permissions,
        description=existing.get("description"),
    )
    return {"ok": True, "role": result}


def _find_user(client: AdminApiClient, number: str) -> dict[str, Any] | None:
    normalized_number = _digits_only(number)
    for user in client.list_users():
        if _digits_only(str(user.get("phone_number", ""))) == normalized_number:
            return user
    return None


def _find_role(client: AdminApiClient, role_name: str) -> dict[str, Any] | None:
    normalized_name = _normalize_token(role_name)
    for role in client.list_roles():
        if _normalize_token(str(role.get("name", ""))) == normalized_name:
            return role
    return None


def _split_csv_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in str(value).split(","):
            normalized = _normalize_token(item)
            if normalized:
                result.append(normalized)
    return result


def _split_sector_values(values: list[str]) -> list[str]:
    return _split_scope_values(values)


def _split_scope_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in str(value).split(","):
            normalized = _normalize_scope_code(item)
            if normalized:
                result.append(normalized)
    return result


def _unique_tokens(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_token(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _normalize_token(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    cleaned = "".join(char for char in unicodedata.normalize("NFD", cleaned) if unicodedata.category(char) != "Mn")
    cleaned = cleaned.replace(" ", "_")
    return "".join(char for char in cleaned if char.isalnum() or char in {"_", "*"})


def _digits_only(value: str) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _normalize_sector(value: str) -> str:
    return _normalize_scope_code(value)


def _normalize_scope_code(value: str) -> str:
    digits = _digits_only(value)
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or "erro sem detalhe"

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if detail:
            return str(detail)
    return json.dumps(payload, ensure_ascii=False)


def _run_shell(client: AdminApiClient) -> None:
    print("RBAC shell interativo. Digite 'help' para exemplos ou 'exit' para sair.")
    while True:
        try:
            line = input("rbac> ").strip()
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            break

        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            break
        if line.lower() in {"help", "?"}:
            _print_shell_help()
            continue

        try:
            args = _parse_args(shlex.split(line))
        except SystemExit:
            continue

        if args.command == "shell":
            print(_to_json({"ok": False, "error": "Voce ja esta no shell."}))
            continue

        try:
            print(_to_json(_dispatch(client, args)))
        except Exception as exc:
            print(_to_json({"ok": False, "error": str(exc)}))


def _print_shell_help() -> None:
    examples = [
        "status",
        "seed",
        "users",
        "roles",
        "permissions",
        "check 5583991964911 --area cliente",
        "user-set 5583991964911 --name \"Teste Real\" --role vendedor --sector 1-206",
        "user-set 5583991964911 --name \"Gerente 1\" --role gerente_vendas --gv-vde 1-2",
        "user-set 5583991964911 --name \"Diretor Comercial\" --role diretor_comercial --gv-vde 1-1,6-2",
        "user-grant-role 5583991964911 financeiro",
        "user-grant-sector 5583991964911 207",
        "user-grant-gv-vde 5583991964911 2",
        "user-revoke-sector 5583991964911 207",
        "user-revoke-gv-vde 5583991964911 2",
        "user-revoke-role 5583991964911 vendedor",
        "role-set financeiro --permission cliente --permission conhecimento",
        "role-grant financeiro inadimplencia",
        "role-revoke financeiro comodato",
    ]
    print("Comandos de exemplo:")
    for example in examples:
        print(f"  {example}")


if __name__ == "__main__":
    main()
