from __future__ import annotations

import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Any

from bot_api.commercial_scope import (
    normalize_dc_scope_input,
    normalize_filial_scope_input,
    normalize_gv_scope_input,
    normalize_sector_scope_input,
    normalize_stored_scope_value,
    split_scope_pair,
)
from bot_api.db import get_connection_pool

ROLE_ADMIN = "admin"
ROLE_FINANCEIRO = "financeiro"
ROLE_GERENTE_VENDAS = "gerente_vendas"
ROLE_DIRETOR_COMERCIAL = "diretor_comercial"
ROLE_VENDEDOR = "vendedor"
ROLE_ARMAZEM = "armazem"

DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    ROLE_ADMIN: ("*",),
    ROLE_FINANCEIRO: ("inadimplencia", "comodato", "cliente", "conhecimento", "payip", "estoque"),
    ROLE_GERENTE_VENDAS: ("inadimplencia", "comodato", "cliente", "conhecimento", "estoque"),
    ROLE_DIRETOR_COMERCIAL: ("inadimplencia", "comodato", "cliente", "conhecimento", "estoque"),
    ROLE_VENDEDOR: ("inadimplencia", "comodato", "cliente", "estoque"),
    ROLE_ARMAZEM: ("cliente", "estoque"),
}


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    area: str
    normalized_number: str
    roles: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()
    gv_vdes: tuple[str, ...] = ()


class AccessControl:
    def __init__(
        self,
        enabled: bool,
        database_url: str,
        schema: str,
        public_enabled: bool = False,
        connect_timeout_seconds: float = 3.0,
    ) -> None:
        self.enabled = enabled
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.public_enabled = public_enabled
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None
        self._initialized = False
        self._last_error = ""
        self._authorization_cache: dict[tuple[str, str], tuple[float, AccessDecision]] = {}
        self._authorization_cache_ttl_seconds = 30.0

    def initialize(self) -> bool:
        if not self.enabled:
            self._initialized = True
            self._last_error = ""
            return True
        if not self.database_url:
            self._last_error = "ACCESS_DATABASE_URL nao configurada."
            self._initialized = False
            return False

        try:
            with self._connect() as conn:
                if not self._has_required_tables(conn):
                    self._bootstrap_schema(conn)
                conn.commit()
            self._normalize_existing_sector_codes()
            self._normalize_existing_gv_vde_codes()
            self._migrate_legacy_role_names()
            self._merge_equivalent_phone_numbers()
            try:
                self._ensure_equivalent_phone_number_index()
            except Exception as exc:
                if not _is_optional_ddl_permission_error(exc):
                    raise
            self._initialized = True
            self._last_error = ""
            self.seed_defaults()
            return True
        except Exception as exc:
            self._initialized = False
            self._last_error = _format_bootstrap_error(exc, schema=self.schema, context="RBAC")
            return False

    def status(self) -> dict[str, Any]:
        available = self._ensure_ready()
        return {
            "enabled": self.enabled,
            "database_configured": bool(self.database_url),
            "schema": self.schema,
            "ready": available,
            "last_error": self._last_error,
            "public_enabled": self.public_enabled,
            "connect_timeout_seconds": self.connect_timeout_seconds,
        }

    def authorize(self, phone_number: str, area: str) -> AccessDecision:
        normalized_number = _normalize_number(phone_number)
        comparable_number = _comparable_number(normalized_number)
        normalized_area = _normalize_name(area, fallback="conhecimento")
        cache_key = (comparable_number, normalized_area)
        cached_entry = self._authorization_cache.get(cache_key)
        if cached_entry is not None and monotonic() < cached_entry[0]:
            return cached_entry[1]
        if not self.enabled:
            decision = AccessDecision(
                allowed=True,
                reason="access_control_disabled",
                area=normalized_area,
                normalized_number=normalized_number,
            )
            self._cache_authorization(cache_key, decision)
            return decision

        if self.public_enabled:
            decision = AccessDecision(
                allowed=True,
                reason="public_access_enabled",
                area=normalized_area,
                normalized_number=normalized_number,
            )
            self._cache_authorization(cache_key, decision)
            return decision

        if not self._ensure_ready():
            decision = AccessDecision(
                allowed=False,
                reason="access_control_unavailable",
                area=normalized_area,
                normalized_number=normalized_number,
            )
            self._cache_authorization(cache_key, decision)
            return decision

        try:
            sql, dict_row = _psycopg_sql()
            query = sql.SQL(
                """
                SELECT
                    u.phone_number,
                    u.is_active,
                    COALESCE(array_agg(DISTINCT r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::text[]) AS roles,
                    COALESCE(array_agg(DISTINCT p.name) FILTER (WHERE p.name IS NOT NULL), ARRAY[]::text[]) AS permissions,
                    COALESCE(array_agg(DISTINCT us.sector_code) FILTER (WHERE us.sector_code IS NOT NULL), ARRAY[]::text[]) AS sectors,
                    COALESCE(array_agg(DISTINCT ug.gv_vde_code) FILTER (WHERE ug.gv_vde_code IS NOT NULL), ARRAY[]::text[]) AS gv_vdes
                FROM {}.users u
                LEFT JOIN {}.user_roles ur ON ur.user_id = u.id
                LEFT JOIN {}.roles r ON r.id = ur.role_id
                LEFT JOIN {}.role_permissions rp ON rp.role_id = r.id
                LEFT JOIN {}.permissions p ON p.id = rp.permission_id
                LEFT JOIN {}.user_sectors us ON us.user_id = u.id
                LEFT JOIN {}.user_gv_vdes ug ON ug.user_id = u.id
                WHERE {} = %s
                GROUP BY u.id
                """
            ).format(
                sql.Identifier(self.schema),
                sql.Identifier(self.schema),
                sql.Identifier(self.schema),
                sql.Identifier(self.schema),
                sql.Identifier(self.schema),
                sql.Identifier(self.schema),
                sql.Identifier(self.schema),
                _normalized_number_sql("u.phone_number"),
            )
            with self._connect(row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (comparable_number,))
                    row = cur.fetchone()
            if not row:
                decision = AccessDecision(
                    allowed=False,
                    reason="number_not_registered",
                    area=normalized_area,
                    normalized_number=normalized_number,
                )
                self._cache_authorization(cache_key, decision)
                return decision
            if not row["is_active"]:
                decision = AccessDecision(
                    allowed=False,
                    reason="user_inactive",
                    area=normalized_area,
                    normalized_number=str(row["phone_number"] or normalized_number),
                    roles=tuple(row["roles"]),
                    sectors=tuple(row["sectors"]),
                    gv_vdes=tuple(row["gv_vdes"]),
                )
                self._cache_authorization(cache_key, decision)
                return decision

            permissions = {str(item) for item in row["permissions"] if str(item).strip()}
            roles = _canonicalize_role_sequence(row["roles"])
            sectors = tuple(str(item) for item in row["sectors"] if str(item).strip())
            gv_vdes = tuple(str(item) for item in row["gv_vdes"] if str(item).strip())
            if "*" in permissions or normalized_area in permissions:
                decision = AccessDecision(
                    allowed=True,
                    reason="authorized",
                    area=normalized_area,
                    normalized_number=str(row["phone_number"] or normalized_number),
                    roles=roles,
                    sectors=sectors,
                    gv_vdes=gv_vdes,
                )
                self._cache_authorization(cache_key, decision)
                return decision
            decision = AccessDecision(
                allowed=False,
                reason="area_not_allowed",
                area=normalized_area,
                normalized_number=str(row["phone_number"] or normalized_number),
                roles=roles,
                sectors=sectors,
                gv_vdes=gv_vdes,
            )
            self._cache_authorization(cache_key, decision)
            return decision
        except Exception as exc:
            self._last_error = str(exc)
            self._initialized = False
            decision = AccessDecision(
                allowed=False,
                reason="access_control_query_failed",
                area=normalized_area,
                normalized_number=normalized_number,
            )
            self._cache_authorization(cache_key, decision)
            return decision

    def seed_defaults(self) -> dict[str, Any]:
        if not self._ensure_ready():
            return {"ok": False, "reason": self._last_error}

        created_roles: list[str] = []
        updated_roles: list[str] = []
        skipped_roles: list[str] = []
        try:
            existing_roles = {str(item["name"]): item for item in self.list_roles()}
            for role_name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
                existing = existing_roles.get(role_name)
                if existing and existing.get("permissions"):
                    existing_permissions = {
                        str(permission)
                        for permission in existing.get("permissions", [])
                        if str(permission).strip()
                    }
                    target_permissions = existing_permissions | set(permissions)
                    if target_permissions == existing_permissions:
                        skipped_roles.append(role_name)
                        continue
                    created = self.upsert_role(
                        role_name=role_name,
                        permissions=sorted(target_permissions),
                    )
                else:
                    created = self.upsert_role(role_name=role_name, permissions=list(permissions))
                if created["created"]:
                    created_roles.append(role_name)
                else:
                    updated_roles.append(role_name)
            return {
                "ok": True,
                "created_roles": created_roles,
                "updated_roles": updated_roles,
                "skipped_roles": skipped_roles,
            }
        except Exception as exc:
            self._last_error = str(exc)
            self._initialized = False
            return {"ok": False, "reason": self._last_error}

    def list_users(self) -> list[dict[str, Any]]:
        if not self._ensure_ready():
            raise RuntimeError(self._last_error or "RBAC indisponivel.")
        sql, dict_row = _psycopg_sql()
        query = sql.SQL(
            """
            SELECT
                u.phone_number,
                u.name,
                u.is_active,
                u.created_at,
                u.updated_at,
                COALESCE(array_agg(DISTINCT r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::text[]) AS roles,
                COALESCE(array_agg(DISTINCT us.sector_code) FILTER (WHERE us.sector_code IS NOT NULL), ARRAY[]::text[]) AS sectors,
                COALESCE(array_agg(DISTINCT ug.gv_vde_code) FILTER (WHERE ug.gv_vde_code IS NOT NULL), ARRAY[]::text[]) AS gv_vdes
            FROM {}.users u
            LEFT JOIN {}.user_roles ur ON ur.user_id = u.id
            LEFT JOIN {}.roles r ON r.id = ur.role_id
            LEFT JOIN {}.user_sectors us ON us.user_id = u.id
            LEFT JOIN {}.user_gv_vdes ug ON ug.user_id = u.id
            GROUP BY u.id
            ORDER BY u.phone_number
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        return [_canonicalize_user_row(dict(row)) for row in rows]

    def get_user(self, phone_number: str) -> dict[str, Any] | None:
        if not self._ensure_ready():
            raise RuntimeError(self._last_error or "RBAC indisponivel.")
        normalized_number = _normalize_number(phone_number)
        comparable_number = _comparable_number(normalized_number)
        if not normalized_number:
            raise ValueError("Numero invalido.")
        sql, dict_row = _psycopg_sql()
        query = sql.SQL(
            """
            SELECT
                u.phone_number,
                u.name,
                u.is_active,
                u.created_at,
                u.updated_at,
                COALESCE(array_agg(DISTINCT r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::text[]) AS roles,
                COALESCE(array_agg(DISTINCT us.sector_code) FILTER (WHERE us.sector_code IS NOT NULL), ARRAY[]::text[]) AS sectors,
                COALESCE(array_agg(DISTINCT ug.gv_vde_code) FILTER (WHERE ug.gv_vde_code IS NOT NULL), ARRAY[]::text[]) AS gv_vdes
            FROM {}.users u
            LEFT JOIN {}.user_roles ur ON ur.user_id = u.id
            LEFT JOIN {}.roles r ON r.id = ur.role_id
            LEFT JOIN {}.user_sectors us ON us.user_id = u.id
            LEFT JOIN {}.user_gv_vdes ug ON ug.user_id = u.id
            WHERE {} = %s
            GROUP BY u.id
            """
        ).format(
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            sql.Identifier(self.schema),
            _normalized_number_sql("u.phone_number"),
        )
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (comparable_number,))
                row = cur.fetchone()
        return _canonicalize_user_row(dict(row)) if row else None

    def list_roles(self) -> list[dict[str, Any]]:
        if not self._ensure_ready():
            raise RuntimeError(self._last_error or "RBAC indisponivel.")
        sql, dict_row = _psycopg_sql()
        query = sql.SQL(
            """
            SELECT
                r.name,
                r.description,
                r.created_at,
                r.updated_at,
                COALESCE(array_agg(DISTINCT p.name) FILTER (WHERE p.name IS NOT NULL), ARRAY[]::text[]) AS permissions
            FROM {}.roles r
            LEFT JOIN {}.role_permissions rp ON rp.role_id = r.id
            LEFT JOIN {}.permissions p ON p.id = rp.permission_id
            GROUP BY r.id
            ORDER BY r.name
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.schema), sql.Identifier(self.schema))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        return [_canonicalize_role_row(dict(row)) for row in rows]

    def list_permissions(self) -> list[dict[str, Any]]:
        if not self._ensure_ready():
            raise RuntimeError(self._last_error or "RBAC indisponivel.")
        sql, dict_row = _psycopg_sql()
        query = sql.SQL(
            """
            SELECT name, description, created_at
            FROM {}.permissions
            ORDER BY name
            """
        ).format(sql.Identifier(self.schema))
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def upsert_user(
        self,
        phone_number: str,
        name: str | None = None,
        is_active: bool = True,
        roles: list[str] | None = None,
        sectors: list[str] | None = None,
        gv_vdes: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self._ensure_ready():
            raise RuntimeError(self._last_error or "RBAC indisponivel.")
        normalized_number = _normalize_number(phone_number)
        comparable_number = _comparable_number(normalized_number)
        if not normalized_number:
            raise ValueError("Numero invalido.")
        normalized_roles = [
            normalized_role
            for role in (roles or [])
            if str(role).strip()
            for normalized_role in [_normalize_role_name(role)]
            if normalized_role
        ]
        target_role = normalized_roles[0] if normalized_roles else ""
        self._validate_scope_input_formats(
            role_name=target_role,
            sectors=sectors or [],
            gv_vdes=gv_vdes or [],
        )
        normalized_sectors = (
            _normalize_finance_filial_scope_list(sectors)
            if target_role in {ROLE_FINANCEIRO, ROLE_ARMAZEM}
            else _normalize_sector_scope_list(sectors)
        )
        normalized_gv_vdes = _normalize_gv_scope_list(gv_vdes, role_name=target_role)
        self._validate_user_scope_policy(
            roles=normalized_roles,
            sectors=normalized_sectors,
            gv_vdes=normalized_gv_vdes,
        )
        sql, dict_row = _psycopg_sql()
        existing_user_query = sql.SQL(
            """
            SELECT id, phone_number
            FROM {}.users
            WHERE {} = %s
            ORDER BY CASE WHEN phone_number = %s THEN 0 ELSE 1 END, id
            LIMIT 1
            """
        ).format(sql.Identifier(self.schema), _normalized_number_sql("phone_number"))
        insert_query = sql.SQL(
            """
            INSERT INTO {}.users (phone_number, name, is_active, updated_at)
            VALUES (%s, %s, %s, NOW())
            RETURNING id, phone_number, name, is_active
            """
        ).format(sql.Identifier(self.schema))
        update_query = sql.SQL(
            """
            UPDATE {}.users
            SET phone_number = %s,
                name = %s,
                is_active = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, phone_number, name, is_active
            """
        ).format(sql.Identifier(self.schema))
        role_lookup_query = sql.SQL("SELECT id FROM {}.roles WHERE name = %s").format(sql.Identifier(self.schema))
        role_insert_query = sql.SQL("INSERT INTO {}.roles (name, updated_at) VALUES (%s, NOW()) ON CONFLICT (name) DO NOTHING").format(
            sql.Identifier(self.schema)
        )
        delete_roles_query = sql.SQL("DELETE FROM {}.user_roles WHERE user_id = %s").format(sql.Identifier(self.schema))
        insert_user_role_query = sql.SQL(
            "INSERT INTO {}.user_roles (user_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING"
        ).format(sql.Identifier(self.schema))
        delete_sectors_query = sql.SQL("DELETE FROM {}.user_sectors WHERE user_id = %s").format(sql.Identifier(self.schema))
        insert_user_sector_query = sql.SQL(
            "INSERT INTO {}.user_sectors (user_id, sector_code) VALUES (%s, %s) ON CONFLICT DO NOTHING"
        ).format(sql.Identifier(self.schema))
        delete_gv_vdes_query = sql.SQL("DELETE FROM {}.user_gv_vdes WHERE user_id = %s").format(sql.Identifier(self.schema))
        insert_user_gv_vde_query = sql.SQL(
            "INSERT INTO {}.user_gv_vdes (user_id, gv_vde_code) VALUES (%s, %s) ON CONFLICT DO NOTHING"
        ).format(sql.Identifier(self.schema))

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(existing_user_query, (comparable_number, normalized_number))
                existing_user = cur.fetchone()
                stored_number = _preferred_storage_number(
                    [
                        str(existing_user["phone_number"] or "") if existing_user else "",
                        normalized_number,
                    ]
                ) or normalized_number
                if existing_user:
                    cur.execute(update_query, (stored_number, (name or "").strip() or None, is_active, existing_user["id"]))
                else:
                    cur.execute(insert_query, (stored_number, (name or "").strip() or None, is_active))
                user = cur.fetchone()
                cur.execute(delete_roles_query, (user["id"],))
                cur.execute(delete_sectors_query, (user["id"],))
                cur.execute(delete_gv_vdes_query, (user["id"],))
                for role_name in normalized_roles:
                    cur.execute(role_insert_query, (role_name,))
                    cur.execute(role_lookup_query, (role_name,))
                    role_row = cur.fetchone()
                    if role_row:
                        cur.execute(insert_user_role_query, (user["id"], role_row["id"]))
                for sector_code in normalized_sectors:
                    cur.execute(insert_user_sector_query, (user["id"], sector_code))
                for gv_vde_code in normalized_gv_vdes:
                    cur.execute(insert_user_gv_vde_query, (user["id"], gv_vde_code))
            conn.commit()
        self._clear_authorization_cache()
        return {
            "phone_number": user["phone_number"],
            "name": user["name"],
            "is_active": user["is_active"],
            "roles": normalized_roles,
            "sectors": normalized_sectors,
            "gv_vdes": normalized_gv_vdes,
        }

    def delete_user(self, phone_number: str) -> dict[str, Any]:
        if not self._ensure_ready():
            raise RuntimeError(self._last_error or "RBAC indisponivel.")
        normalized_number = _normalize_number(phone_number)
        comparable_number = _comparable_number(normalized_number)
        if not normalized_number:
            raise ValueError("Numero invalido.")

        sql, dict_row = _psycopg_sql()
        select_query = sql.SQL(
            """
            SELECT id
            FROM {}.users
            WHERE {} = %s
            ORDER BY CASE WHEN phone_number = %s THEN 0 ELSE 1 END, id
            LIMIT 1
            """
        ).format(sql.Identifier(self.schema), _normalized_number_sql("phone_number"))
        delete_query = sql.SQL(
            """
            DELETE FROM {}.users
            WHERE id = %s
            RETURNING phone_number
            """
        ).format(sql.Identifier(self.schema))

        existing_user = self.get_user(normalized_number)
        if not existing_user:
            raise ValueError("Usuario nao encontrado.")

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(select_query, (comparable_number, normalized_number))
                row = cur.fetchone()
                if not row:
                    raise ValueError("Usuario nao encontrado.")
                cur.execute(delete_query, (row["id"],))
                deleted_row = cur.fetchone()
            conn.commit()

        self._clear_authorization_cache()
        return {
            **existing_user,
            "deleted": bool(deleted_row),
        }

    def _validate_scope_input_formats(
        self,
        *,
        role_name: str,
        sectors: list[str],
        gv_vdes: list[str],
    ) -> None:
        sector_values = [str(value or "").strip() for value in sectors if str(value or "").strip()]
        gv_values = [str(value or "").strip() for value in gv_vdes if str(value or "").strip()]

        if role_name == ROLE_VENDEDOR:
            invalid = [value for value in sector_values if not normalize_sector_scope_input(value)]
            if invalid:
                raise ValueError("Para Vendedor, use somente chaves filial-setor, por exemplo: 3-107.")
            return
        if role_name == ROLE_GERENTE_VENDAS:
            invalid = [value for value in gv_values if not normalize_gv_scope_input(value)]
            if invalid:
                raise ValueError("Para Gerente de Vendas, use somente chaves filial-GV, por exemplo: 1-2.")
            return
        if role_name == ROLE_DIRETOR_COMERCIAL:
            invalid = [value for value in gv_values if not normalize_dc_scope_input(value)]
            if invalid:
                raise ValueError("Para Diretor Comercial, use somente chaves filial-DC, por exemplo: 1-1.")
            return
        if role_name in {ROLE_FINANCEIRO, ROLE_ARMAZEM}:
            invalid = [value for value in sector_values if not normalize_filial_scope_input(value)]
            if invalid:
                label = "Financeiro" if role_name == ROLE_FINANCEIRO else "Armazem"
                raise ValueError(f"Para {label}, use somente filiais, por exemplo: 3 ou 3,4.")
            return

    def _validate_user_scope_policy(
        self,
        *,
        roles: list[str],
        sectors: list[str],
        gv_vdes: list[str],
    ) -> None:
        normalized_roles = [str(role).strip() for role in roles if str(role).strip()]
        if not normalized_roles:
            raise ValueError("Escolha um cargo para o usuario.")
        if len(normalized_roles) != 1:
            raise ValueError("Escolha apenas um cargo por usuario.")

        role_name = normalized_roles[0]
        if role_name == ROLE_ADMIN:
            if sectors or gv_vdes:
                raise ValueError("Admin nao deve ter setor nem GV vinculado.")
            return
        if role_name == ROLE_FINANCEIRO:
            if gv_vdes:
                raise ValueError("Financeiro nao deve ter GV vinculado.")
            if not sectors:
                raise ValueError("Para Financeiro, informe ao menos uma filial.")
            if any(not normalize_filial_scope_input(value) for value in sectors):
                raise ValueError("Financeiro aceita somente filiais.")
            return
        if role_name == ROLE_ARMAZEM:
            if gv_vdes:
                raise ValueError("Armazem nao deve ter GV vinculado.")
            if not sectors:
                raise ValueError("Para Armazem, informe ao menos uma filial.")
            if any(not normalize_filial_scope_input(value) for value in sectors):
                raise ValueError("Armazem aceita somente filiais.")
            return
        if role_name == ROLE_GERENTE_VENDAS:
            if sectors:
                raise ValueError("Gerente de vendas nao deve ter setor vinculado.")
            if not gv_vdes:
                raise ValueError("Para Gerente de Vendas, informe ao menos uma chave filial-GV.")
            if any(not split_scope_pair(value) or str(value).startswith("dc:") for value in gv_vdes):
                raise ValueError("Gerente de Vendas aceita somente chaves filial-GV.")
            return
        if role_name == ROLE_DIRETOR_COMERCIAL:
            if sectors:
                raise ValueError("Diretor comercial nao deve ter setor vinculado.")
            if not gv_vdes:
                raise ValueError("Para Diretor Comercial, informe ao menos uma chave filial-DC.")
            if any(not str(value).startswith("dc:") or not split_scope_pair(value) for value in gv_vdes):
                raise ValueError("Diretor Comercial aceita somente chaves filial-DC.")
            return
        if role_name == ROLE_VENDEDOR:
            if gv_vdes:
                raise ValueError("Vendedor nao deve ter GV vinculado.")
            if not sectors:
                raise ValueError("Para Vendedor, informe ao menos uma chave filial-setor.")
            if any(not split_scope_pair(value) or str(value).startswith("dc:") for value in sectors):
                raise ValueError("Vendedor aceita somente chaves filial-setor.")
            return
        raise ValueError("Cargo invalido.")

    def upsert_role(
        self,
        role_name: str,
        permissions: list[str] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        if not self._ensure_ready():
            raise RuntimeError(self._last_error or "RBAC indisponivel.")
        normalized_role = _normalize_role_name(role_name)
        if not normalized_role:
            raise ValueError("Cargo invalido.")
        normalized_permissions = [
            _normalize_name(permission, fallback="conhecimento")
            for permission in (permissions or [])
            if str(permission).strip()
        ]
        sql, dict_row = _psycopg_sql()
        exists_query = sql.SQL("SELECT 1 AS found FROM {}.roles WHERE name = %s").format(sql.Identifier(self.schema))
        upsert_role_query = sql.SQL(
            """
            INSERT INTO {}.roles AS target (name, description, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (name)
            DO UPDATE SET
                description = COALESCE(EXCLUDED.description, target.description),
                updated_at = NOW()
            RETURNING id, name, description
            """
        ).format(sql.Identifier(self.schema))
        insert_permission_query = sql.SQL(
            """
            INSERT INTO {}.permissions (name, description)
            VALUES (%s, %s)
            ON CONFLICT (name) DO NOTHING
            """
        ).format(sql.Identifier(self.schema))
        permission_lookup_query = sql.SQL("SELECT id FROM {}.permissions WHERE name = %s").format(sql.Identifier(self.schema))
        delete_permissions_query = sql.SQL("DELETE FROM {}.role_permissions WHERE role_id = %s").format(sql.Identifier(self.schema))
        insert_role_permission_query = sql.SQL(
            "INSERT INTO {}.role_permissions (role_id, permission_id) VALUES (%s, %s) ON CONFLICT DO NOTHING"
        ).format(sql.Identifier(self.schema))

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(exists_query, (normalized_role,))
                created = cur.fetchone() is None
                cur.execute(upsert_role_query, (normalized_role, (description or "").strip() or None))
                role_row = cur.fetchone()
                cur.execute(delete_permissions_query, (role_row["id"],))
                for permission_name in normalized_permissions:
                    cur.execute(insert_permission_query, (permission_name, None))
                    cur.execute(permission_lookup_query, (permission_name,))
                    permission_row = cur.fetchone()
                    if permission_row:
                        cur.execute(insert_role_permission_query, (role_row["id"], permission_row["id"]))
            conn.commit()
        self._clear_authorization_cache()
        return {
            "created": created,
            "name": role_row["name"],
            "description": role_row["description"],
            "permissions": normalized_permissions,
        }

    def _normalize_existing_sector_codes(self) -> None:
        sql, dict_row = _psycopg_sql()
        select_query = sql.SQL("SELECT user_id, sector_code, created_at FROM {}.user_sectors").format(sql.Identifier(self.schema))
        delete_query = sql.SQL("DELETE FROM {}.user_sectors").format(sql.Identifier(self.schema))
        insert_query = sql.SQL(
            "INSERT INTO {}.user_sectors (user_id, sector_code, created_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"
        ).format(sql.Identifier(self.schema))

        normalized_rows: list[tuple[Any, str, Any]] = []
        seen: set[tuple[Any, str]] = set()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(select_query)
                rows = cur.fetchall()
                for row in rows:
                    normalized_sector = normalize_stored_scope_value(str(row["sector_code"] or ""))
                    key = (row["user_id"], normalized_sector)
                    if not normalized_sector or key in seen:
                        continue
                    seen.add(key)
                    normalized_rows.append((row["user_id"], normalized_sector, row["created_at"]))
                cur.execute(delete_query)
                if normalized_rows:
                    cur.executemany(insert_query, normalized_rows)
            conn.commit()

    def _normalize_existing_gv_vde_codes(self) -> None:
        sql, dict_row = _psycopg_sql()
        select_query = sql.SQL("SELECT user_id, gv_vde_code, created_at FROM {}.user_gv_vdes").format(
            sql.Identifier(self.schema)
        )
        delete_query = sql.SQL("DELETE FROM {}.user_gv_vdes").format(sql.Identifier(self.schema))
        insert_query = sql.SQL(
            "INSERT INTO {}.user_gv_vdes (user_id, gv_vde_code, created_at) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"
        ).format(sql.Identifier(self.schema))

        normalized_rows: list[tuple[Any, str, Any]] = []
        seen: set[tuple[Any, str]] = set()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(select_query)
                rows = cur.fetchall()
                for row in rows:
                    normalized_gv_vde = normalize_stored_scope_value(str(row["gv_vde_code"] or ""))
                    key = (row["user_id"], normalized_gv_vde)
                    if not normalized_gv_vde or key in seen:
                        continue
                    seen.add(key)
                    normalized_rows.append((row["user_id"], normalized_gv_vde, row["created_at"]))
                cur.execute(delete_query)
                if normalized_rows:
                    cur.executemany(insert_query, normalized_rows)
            conn.commit()

    def _migrate_legacy_role_names(self) -> None:
        sql, dict_row = _psycopg_sql()
        select_query = sql.SQL(
            """
            SELECT id, name
            FROM {}.roles
            WHERE name IN (%s, %s)
            ORDER BY id
            """
        ).format(sql.Identifier(self.schema))
        update_query = sql.SQL(
            """
            UPDATE {}.roles
            SET name = %s,
                updated_at = NOW()
            WHERE id = %s
            """
        ).format(sql.Identifier(self.schema))
        merge_user_roles_query = sql.SQL(
            """
            INSERT INTO {}.user_roles (user_id, role_id)
            SELECT user_id, %s
            FROM {}.user_roles
            WHERE role_id = %s
            ON CONFLICT DO NOTHING
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
        merge_role_permissions_query = sql.SQL(
            """
            INSERT INTO {}.role_permissions (role_id, permission_id)
            SELECT %s, permission_id
            FROM {}.role_permissions
            WHERE role_id = %s
            ON CONFLICT DO NOTHING
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
        delete_legacy_role_query = sql.SQL("DELETE FROM {}.roles WHERE id = %s").format(sql.Identifier(self.schema))

        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(select_query, ("gestor", ROLE_GERENTE_VENDAS))
                rows = cur.fetchall()
                legacy_role = next((row for row in rows if row["name"] == "gestor"), None)
                canonical_role = next((row for row in rows if row["name"] == ROLE_GERENTE_VENDAS), None)
                if not legacy_role:
                    conn.commit()
                    return
                if canonical_role:
                    cur.execute(merge_user_roles_query, (canonical_role["id"], legacy_role["id"]))
                    cur.execute(merge_role_permissions_query, (canonical_role["id"], legacy_role["id"]))
                    cur.execute(delete_legacy_role_query, (legacy_role["id"],))
                else:
                    cur.execute(update_query, (ROLE_GERENTE_VENDAS, legacy_role["id"]))
            conn.commit()

    def _merge_equivalent_phone_numbers(self) -> None:
        sql, dict_row = _psycopg_sql()
        select_query = sql.SQL(
            """
            SELECT id, phone_number, name, is_active, created_at, updated_at
            FROM {}.users
            ORDER BY id
            """
        ).format(sql.Identifier(self.schema))
        update_user_query = sql.SQL(
            """
            UPDATE {}.users
            SET phone_number = %s,
                name = %s,
                is_active = %s,
                updated_at = NOW()
            WHERE id = %s
            """
        ).format(sql.Identifier(self.schema))
        merge_roles_query = sql.SQL(
            """
            INSERT INTO {}.user_roles (user_id, role_id)
            SELECT %s, role_id
            FROM {}.user_roles
            WHERE user_id = %s
            ON CONFLICT DO NOTHING
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
        merge_sectors_query = sql.SQL(
            """
            INSERT INTO {}.user_sectors (user_id, sector_code)
            SELECT %s, sector_code
            FROM {}.user_sectors
            WHERE user_id = %s
            ON CONFLICT DO NOTHING
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
        merge_gv_vdes_query = sql.SQL(
            """
            INSERT INTO {}.user_gv_vdes (user_id, gv_vde_code)
            SELECT %s, gv_vde_code
            FROM {}.user_gv_vdes
            WHERE user_id = %s
            ON CONFLICT DO NOTHING
            """
        ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
        delete_users_query = sql.SQL("DELETE FROM {}.users WHERE id = ANY(%s)").format(sql.Identifier(self.schema))

        grouped_rows: dict[str, list[dict[str, Any]]] = {}
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(select_query)
                rows = [dict(row) for row in cur.fetchall()]
                for row in rows:
                    comparable_number = _comparable_number(str(row["phone_number"] or ""))
                    if not comparable_number:
                        continue
                    grouped_rows.setdefault(comparable_number, []).append(row)

                for duplicate_rows in grouped_rows.values():
                    if len(duplicate_rows) < 2:
                        continue
                    keeper = min(duplicate_rows, key=lambda item: int(item["id"]))
                    duplicates = [row for row in duplicate_rows if int(row["id"]) != int(keeper["id"])]
                    preferred_phone = _preferred_storage_number(
                        [str(row["phone_number"] or "") for row in duplicate_rows]
                    ) or str(keeper["phone_number"] or "")
                    preferred_name = _preferred_user_name(duplicate_rows)
                    merged_is_active = any(bool(row["is_active"]) for row in duplicate_rows)
                    cur.execute(
                        update_user_query,
                        (preferred_phone, preferred_name, merged_is_active, keeper["id"]),
                    )
                    duplicate_ids = [int(row["id"]) for row in duplicates]
                    for duplicate_id in duplicate_ids:
                        cur.execute(merge_roles_query, (keeper["id"], duplicate_id))
                        cur.execute(merge_sectors_query, (keeper["id"], duplicate_id))
                        cur.execute(merge_gv_vdes_query, (keeper["id"], duplicate_id))
                    cur.execute(delete_users_query, (duplicate_ids,))
            conn.commit()

    def _ensure_equivalent_phone_number_index(self) -> None:
        sql, _ = _psycopg_sql()
        index_query = sql.SQL(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS user_phone_equivalent_number_uidx
            ON {}.users (({}))
            """
        ).format(
            sql.Identifier(self.schema),
            _normalized_number_sql("phone_number"),
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(index_query)
            conn.commit()

    def _ensure_ready(self) -> bool:
        if self._initialized:
            return True
        return self.initialize()

    def _has_required_tables(self, conn: Any) -> bool:
        required_tables = (
            "users",
            "roles",
            "permissions",
            "user_roles",
            "role_permissions",
            "user_sectors",
            "user_gv_vdes",
        )
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (self.schema, list(required_tables)),
            )
            found_tables = {str(row[0]) for row in cur.fetchall()}
        return all(table_name in found_tables for table_name in required_tables)

    def _bootstrap_schema(self, conn: Any) -> None:
        sql, _ = _psycopg_sql()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.users (
                        id BIGSERIAL PRIMARY KEY,
                        phone_number VARCHAR(32) NOT NULL UNIQUE,
                        name TEXT,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS user_phone_equivalent_number_uidx
                    ON {}.users (({}))
                    """
                ).format(
                    sql.Identifier(self.schema),
                    _normalized_number_sql("phone_number"),
                )
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.roles (
                        id BIGSERIAL PRIMARY KEY,
                        name VARCHAR(80) NOT NULL UNIQUE,
                        description TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.permissions (
                        id BIGSERIAL PRIMARY KEY,
                        name VARCHAR(80) NOT NULL UNIQUE,
                        description TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.user_roles (
                        user_id BIGINT NOT NULL REFERENCES {}.users(id) ON DELETE CASCADE,
                        role_id BIGINT NOT NULL REFERENCES {}.roles(id) ON DELETE CASCADE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (user_id, role_id)
                    )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                )
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.role_permissions (
                        role_id BIGINT NOT NULL REFERENCES {}.roles(id) ON DELETE CASCADE,
                        permission_id BIGINT NOT NULL REFERENCES {}.permissions(id) ON DELETE CASCADE,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (role_id, permission_id)
                    )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                )
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.user_sectors (
                        user_id BIGINT NOT NULL REFERENCES {}.users(id) ON DELETE CASCADE,
                        sector_code VARCHAR(32) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (user_id, sector_code)
                    )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                )
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.user_gv_vdes (
                        user_id BIGINT NOT NULL REFERENCES {}.users(id) ON DELETE CASCADE,
                        gv_vde_code VARCHAR(32) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (user_id, gv_vde_code)
                    )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                )
            )

    def _cache_authorization(self, cache_key: tuple[str, str], decision: AccessDecision) -> None:
        self._authorization_cache[cache_key] = (monotonic() + self._authorization_cache_ttl_seconds, decision)

    def _clear_authorization_cache(self) -> None:
        self._authorization_cache.clear()

    @contextmanager
    def _connect(self, row_factory: Any | None = None) -> Any:
        if self._pool is None:
            self._pool = get_connection_pool(
                self.database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
            )
        with self._pool.connection() as conn:
            conn.row_factory = row_factory or _tuple_row()
            yield conn


def _normalize_number(raw_number: str) -> str:
    digits = re.sub(r"\D+", "", raw_number or "")
    if len(digits) in {10, 11} and not digits.startswith("55"):
        return f"55{digits}"
    return digits


def _comparable_number(raw_number: str) -> str:
    normalized = _normalize_number(raw_number)
    if normalized.startswith("55") and len(normalized) == 13 and normalized[4] == "9":
        return f"{normalized[:4]}{normalized[5:]}"
    return normalized


def _preferred_storage_number(values: list[str] | tuple[str, ...]) -> str:
    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_number(str(value or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    if not normalized_values:
        return ""
    return max(normalized_values, key=lambda item: (len(item), item))


def _preferred_user_name(rows: list[dict[str, Any]]) -> str | None:
    named_values = [" ".join(str(row.get("name") or "").split()) for row in rows]
    named_values = [value for value in named_values if value]
    return named_values[0] if named_values else None


def _normalized_number_sql(field_name: str) -> Any:
    sql, _ = _psycopg_sql()
    field = sql.SQL(field_name)
    digits = sql.SQL("REGEXP_REPLACE(COALESCE({field}, ''), '\\D+', '', 'g')").format(field=field)
    return sql.SQL(
        "CASE "
        "WHEN LEFT({digits}, 2) = '55' "
        "THEN CASE "
        "  WHEN LENGTH({digits}) = 13 AND SUBSTRING({digits}, 5, 1) = '9' "
        "  THEN LEFT({digits}, 4) || SUBSTRING({digits}, 6) "
        "  ELSE {digits} "
        "END "
        "WHEN LENGTH({digits}) = 11 "
        "THEN CASE "
        "  WHEN SUBSTRING({digits}, 3, 1) = '9' "
        "  THEN '55' || LEFT({digits}, 2) || SUBSTRING({digits}, 4) "
        "  ELSE '55' || {digits} "
        "END "
        "WHEN LENGTH({digits}) = 10 "
        "THEN '55' || {digits} "
        "ELSE {digits} "
        "END"
    ).format(digits=digits)


def _normalize_name(value: str, fallback: str = "") -> str:
    cleaned = str(value or "").strip().lower()
    cleaned = "".join(char for char in unicodedata.normalize("NFD", cleaned) if unicodedata.category(char) != "Mn")
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^a-z0-9_*]", "", cleaned)
    return cleaned or fallback


def _normalize_role_name(value: str, fallback: str = "") -> str:
    normalized = _normalize_name(value, fallback=fallback)
    return {
        "gestor": ROLE_GERENTE_VENDAS,
        "gerente": ROLE_GERENTE_VENDAS,
        "gerente_de_vendas": ROLE_GERENTE_VENDAS,
        "diretor": ROLE_DIRETOR_COMERCIAL,
        "diretor_comercial": ROLE_DIRETOR_COMERCIAL,
        "armazen": ROLE_ARMAZEM,
        "almoxarifado": ROLE_ARMAZEM,
        "estoque": ROLE_ARMAZEM,
    }.get(normalized, normalized)


def _canonicalize_role_sequence(values: Any) -> tuple[str, ...]:
    ordered_roles: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = _normalize_role_name(str(value))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered_roles.append(normalized)
    return tuple(ordered_roles)


def _canonicalize_user_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized_row = dict(row)
    normalized_row["roles"] = list(_canonicalize_role_sequence(normalized_row.get("roles", [])))
    return normalized_row


def _canonicalize_role_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized_row = dict(row)
    normalized_row["name"] = _normalize_role_name(str(normalized_row.get("name", "")))
    return normalized_row


def _normalize_schema(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", str(value or "").strip())
    return cleaned or "bot_access"


def _normalize_sector_code(value: str) -> str:
    return normalize_sector_scope_input(value)


def _normalize_sector_scope_list(values: list[str] | None) -> list[str]:
    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = normalize_sector_scope_input(str(value or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _normalize_finance_filial_scope_list(values: list[str] | None) -> list[str]:
    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = normalize_filial_scope_input(str(value or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _normalize_gv_scope_list(values: list[str] | None, *, role_name: str) -> list[str]:
    normalized_values: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        if role_name == ROLE_DIRETOR_COMERCIAL:
            normalized = normalize_dc_scope_input(str(value or ""))
        else:
            normalized = normalize_gv_scope_input(str(value or ""))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _format_bootstrap_error(exc: Exception, *, schema: str, context: str) -> str:
    message = str(exc)
    if "permission denied" in message.lower():
        return (
            f"{context} indisponivel: o usuario atual nao pode criar ou alterar objetos em {schema}. "
            f"Deixe o schema bootstrapado antes do startup. Erro original: {message}"
        )
    return message


def _is_optional_ddl_permission_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "must be owner of table" in message or "permission denied" in message


def _psycopg() -> tuple[Any, Any]:
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError("Dependencia psycopg ausente. Rode: pip install -r requirements.txt") from exc
    return psycopg, sql


def _psycopg_sql() -> tuple[Any, Any]:
    _, sql = _psycopg()
    from psycopg.rows import dict_row

    return sql, dict_row


def _tuple_row() -> Any:
    from psycopg.rows import tuple_row

    return tuple_row
