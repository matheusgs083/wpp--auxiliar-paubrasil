from __future__ import annotations

import base64
import hashlib
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from psycopg import sql
from psycopg.rows import dict_row

from bot_api.db import get_connection_pool

PANEL_FEATURES: tuple[str, ...] = (
    "operations",
    "reports",
    "payip",
    "promax",
    "critica",
    "recolhas",
    "giro",
    "usage",
)

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390_000
PASSWORD_MIN_LENGTH = 8
FAILED_LOGIN_LIMIT = 8
LOCKOUT_MINUTES = 15
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._@-]{3,80}$")


class AdminPanelUserService:
    def __init__(
        self,
        *,
        database_url: str,
        schema: str,
        connect_timeout_seconds: float,
        bootstrap_database_url: str | None = None,
    ) -> None:
        self.database_url = str(database_url or "").strip()
        self.bootstrap_database_url = str(bootstrap_database_url or "").strip() or self.database_url
        self.schema = _clean_identifier(schema, "bot_access")
        self.connect_timeout_seconds = float(connect_timeout_seconds or 3)
        self._pool = None
        self._bootstrap_pool = None

    def ensure_schema(self) -> bool:
        with self._bootstrap_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (self.schema,))
                if cur.fetchone() is None:
                    cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.panel_users (
                            id BIGSERIAL PRIMARY KEY,
                            username VARCHAR(80) NOT NULL UNIQUE,
                            display_name TEXT NOT NULL DEFAULT '',
                            password_hash TEXT NOT NULL,
                            password_version INTEGER NOT NULL DEFAULT 1,
                            must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                            filiais TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                            feature_permissions TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                            failed_login_count INTEGER NOT NULL DEFAULT 0,
                            locked_until TIMESTAMPTZ,
                            last_login_at TIMESTAMPTZ,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS panel_users_active_idx
                        ON {}.panel_users (is_active)
                        """
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS panel_users_username_lower_uidx
                        ON {}.panel_users (LOWER(username))
                        """
                    ).format(sql.Identifier(self.schema))
                )
                runtime_user = self._runtime_database_user()
                if runtime_user:
                    cur.execute(
                        sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(runtime_user),
                        )
                    )
                    cur.execute(
                        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {}.panel_users TO {}").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(runtime_user),
                        )
                    )
                    cur.execute(
                        sql.SQL("GRANT USAGE, SELECT, UPDATE ON SEQUENCE {}.panel_users_id_seq TO {}").format(
                            sql.Identifier(self.schema),
                            sql.Identifier(runtime_user),
                        )
                    )
            conn.commit()
        return True

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT id, username, display_name, is_active, is_admin, filiais, feature_permissions,
                               must_change_password, failed_login_count, locked_until, last_login_at,
                               created_at, updated_at
                        FROM {}.panel_users
                        ORDER BY username ASC
                        """
                    ).format(sql.Identifier(self.schema))
                )
                return [self._public_user(row) for row in cur.fetchall()]

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        is_admin: bool,
        features: list[str] | tuple[str, ...],
        filiais: list[str] | tuple[str, ...],
        is_active: bool = True,
    ) -> dict[str, Any]:
        normalized_username = self._normalize_username(username)
        clean_display_name = self._clean_display_name(display_name)
        clean_features = list(PANEL_FEATURES) if bool(is_admin) else self._normalize_features(features)
        clean_filiais = self._normalize_filiais(filiais)
        temp_password = self.generate_temporary_password()
        password_hash = self.hash_password(temp_password)
        try:
            with self._connect(row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL(
                            """
                            INSERT INTO {}.panel_users (
                                username, display_name, password_hash, must_change_password,
                                is_active, is_admin, filiais, feature_permissions
                            )
                            VALUES (%s, %s, %s, TRUE, %s, %s, %s, %s)
                            RETURNING id, username, display_name, is_active, is_admin, filiais,
                                      feature_permissions, must_change_password, failed_login_count,
                                      locked_until, last_login_at, created_at, updated_at
                            """
                        ).format(sql.Identifier(self.schema)),
                        (
                            normalized_username,
                            clean_display_name,
                            password_hash,
                            bool(is_active),
                            bool(is_admin),
                            clean_filiais,
                            clean_features,
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError("Ja existe um usuario do painel com esse login.") from exc
            raise
        return {"user": self._public_user(row), "temporary_password": temp_password}

    def update_user(
        self,
        *,
        user_id: int,
        display_name: str,
        is_admin: bool,
        features: list[str] | tuple[str, ...],
        filiais: list[str] | tuple[str, ...],
        is_active: bool,
    ) -> dict[str, Any]:
        clean_display_name = self._clean_display_name(display_name)
        clean_features = list(PANEL_FEATURES) if bool(is_admin) else self._normalize_features(features)
        clean_filiais = self._normalize_filiais(filiais)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.panel_users
                        SET display_name = %s,
                            is_admin = %s,
                            feature_permissions = %s,
                            filiais = %s,
                            is_active = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, username, display_name, is_active, is_admin, filiais,
                                  feature_permissions, must_change_password, failed_login_count,
                                  locked_until, last_login_at, created_at, updated_at
                        """
                    ).format(sql.Identifier(self.schema)),
                    (clean_display_name, bool(is_admin), clean_features, clean_filiais, bool(is_active), int(user_id)),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Usuario do painel nao encontrado.")
        return self._public_user(row)

    def reset_password(self, *, user_id: int) -> dict[str, Any]:
        temp_password = self.generate_temporary_password()
        password_hash = self.hash_password(temp_password)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.panel_users
                        SET password_hash = %s,
                            password_version = password_version + 1,
                            must_change_password = TRUE,
                            failed_login_count = 0,
                            locked_until = NULL,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, username, display_name, is_active, is_admin, filiais,
                                  feature_permissions, must_change_password, failed_login_count,
                                  locked_until, last_login_at, created_at, updated_at
                        """
                    ).format(sql.Identifier(self.schema)),
                    (password_hash, int(user_id)),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Usuario do painel nao encontrado.")
        return {"user": self._public_user(row), "temporary_password": temp_password}

    def delete_user(self, *, user_id: int) -> dict[str, Any]:
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        DELETE FROM {}.panel_users
                        WHERE id = %s
                        RETURNING id, username, display_name, is_active, is_admin, filiais,
                                  feature_permissions, must_change_password, failed_login_count,
                                  locked_until, last_login_at, created_at, updated_at
                        """
                    ).format(sql.Identifier(self.schema)),
                    (int(user_id),),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise ValueError("Usuario do painel nao encontrado.")
        return self._public_user(row)

    def authenticate(self, *, username: str, password: str) -> dict[str, Any] | None:
        normalized_username = self._normalize_username(username, for_login=True)
        plain_password = str(password or "")
        if not normalized_username or not plain_password:
            return None
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT id, username, display_name, password_hash, password_version, must_change_password,
                               is_active, is_admin, filiais, feature_permissions, failed_login_count, locked_until
                        FROM {}.panel_users
                        WHERE LOWER(username) = LOWER(%s)
                        """
                    ).format(sql.Identifier(self.schema)),
                    (normalized_username,),
                )
                row = cur.fetchone()
                if not row or not bool(row["is_active"]):
                    return None
                now = datetime.now(timezone.utc)
                locked_until = row.get("locked_until")
                if locked_until is not None and locked_until > now:
                    return None
                if not self.verify_password(plain_password, str(row["password_hash"] or "")):
                    failed_count = int(row.get("failed_login_count") or 0) + 1
                    lock_until = now + timedelta(minutes=LOCKOUT_MINUTES) if failed_count >= FAILED_LOGIN_LIMIT else None
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {}.panel_users
                            SET failed_login_count = %s, locked_until = %s, updated_at = NOW()
                            WHERE id = %s
                            """
                        ).format(sql.Identifier(self.schema)),
                        (failed_count, lock_until, row["id"]),
                    )
                    conn.commit()
                    return None
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.panel_users
                        SET failed_login_count = 0,
                            locked_until = NULL,
                            last_login_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        """
                    ).format(sql.Identifier(self.schema)),
                    (row["id"],),
                )
            conn.commit()
        return self._context_from_row(row)

    def change_password(self, *, user_id: int, current_password: str, new_password: str) -> dict[str, Any]:
        self.validate_new_password(new_password)
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT id, username, display_name, password_hash, password_version, must_change_password,
                               is_active, is_admin, filiais, feature_permissions
                        FROM {}.panel_users
                        WHERE id = %s
                        """
                    ).format(sql.Identifier(self.schema)),
                    (int(user_id),),
                )
                row = cur.fetchone()
                if not row or not bool(row["is_active"]):
                    raise ValueError("Sessao invalida. Faca login novamente.")
                if not self.verify_password(str(current_password or ""), str(row["password_hash"] or "")):
                    raise ValueError("Senha atual invalida.")
                new_hash = self.hash_password(new_password)
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.panel_users
                        SET password_hash = %s,
                            password_version = password_version + 1,
                            must_change_password = FALSE,
                            failed_login_count = 0,
                            locked_until = NULL,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, username, display_name, password_version, must_change_password,
                                  is_active, is_admin, filiais, feature_permissions
                        """
                    ).format(sql.Identifier(self.schema)),
                    (new_hash, int(user_id)),
                )
                updated = cur.fetchone()
            conn.commit()
        return self._context_from_row(updated)

    def context_for_session(self, *, user_id: int, password_version: int) -> dict[str, Any] | None:
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT id, username, display_name, password_version, must_change_password,
                               is_active, is_admin, filiais, feature_permissions
                        FROM {}.panel_users
                        WHERE id = %s
                        """
                    ).format(sql.Identifier(self.schema)),
                    (int(user_id),),
                )
                row = cur.fetchone()
        if not row or not bool(row["is_active"]):
            return None
        if int(row.get("password_version") or 0) != int(password_version or 0):
            return None
        return self._context_from_row(row)

    @classmethod
    def hash_password(cls, password: str) -> str:
        plain = str(password or "")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt, PASSWORD_ITERATIONS)
        return "$".join(
            (
                PASSWORD_ALGORITHM,
                str(PASSWORD_ITERATIONS),
                _b64(salt),
                _b64(digest),
            )
        )

    @classmethod
    def verify_password(cls, password: str, stored_hash: str) -> bool:
        parts = str(stored_hash or "").split("$")
        if len(parts) != 4 or parts[0] != PASSWORD_ALGORITHM:
            return False
        try:
            iterations = int(parts[1])
            salt = _b64decode(parts[2])
            expected = _b64decode(parts[3])
        except Exception:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
        return secrets.compare_digest(digest, expected)

    @classmethod
    def generate_temporary_password(cls, length: int = 8) -> str:
        lower = "abcdefghijkmnpqrstuvwxyz"
        digits = "23456789"
        alphabet = lower + digits
        return "".join(secrets.choice(alphabet) for _ in range(max(length, PASSWORD_MIN_LENGTH)))

    @classmethod
    def validate_new_password(cls, password: str) -> None:
        value = str(password or "")
        if len(value) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"A nova senha deve ter pelo menos {PASSWORD_MIN_LENGTH} caracteres.")

    def _context_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        is_admin = bool(row.get("is_admin"))
        features = tuple(PANEL_FEATURES if is_admin else self._normalize_features(row.get("feature_permissions") or ()))
        filiais = tuple(str(item).strip() for item in (row.get("filiais") or []) if str(item).strip())
        return {
            "auth_type": "user",
            "user_id": int(row["id"]),
            "username": str(row.get("username") or ""),
            "display_name": str(row.get("display_name") or ""),
            "password_version": int(row.get("password_version") or 1),
            "must_change_password": bool(row.get("must_change_password")),
            "mode": "admin" if is_admin else "usuario",
            "is_admin": is_admin,
            "filiais": filiais,
            "features": features,
        }

    def _public_user(self, row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {}
        return {
            "id": int(row["id"]),
            "username": str(row.get("username") or ""),
            "display_name": str(row.get("display_name") or ""),
            "is_active": bool(row.get("is_active")),
            "is_admin": bool(row.get("is_admin")),
            "filiais": [str(item) for item in (row.get("filiais") or [])],
            "features": [str(item) for item in (row.get("feature_permissions") or [])],
            "must_change_password": bool(row.get("must_change_password")),
            "failed_login_count": int(row.get("failed_login_count") or 0),
            "locked_until": _iso_or_none(row.get("locked_until")),
            "last_login_at": _iso_or_none(row.get("last_login_at")),
            "created_at": _iso_or_none(row.get("created_at")),
            "updated_at": _iso_or_none(row.get("updated_at")),
        }

    def _normalize_username(self, username: str, *, for_login: bool = False) -> str:
        value = str(username or "").strip()
        if not value:
            if for_login:
                return ""
            raise ValueError("Informe o login do usuario.")
        if not USERNAME_PATTERN.fullmatch(value):
            if for_login:
                return ""
            raise ValueError("Login deve ter 3 a 80 caracteres e usar letras maiusculas/minusculas, numeros, ponto, traco, underline ou @.")
        return value

    @staticmethod
    def _clean_display_name(value: str) -> str:
        cleaned = str(value or "").strip()
        if len(cleaned) > 120:
            raise ValueError("Nome deve ter no maximo 120 caracteres.")
        return cleaned

    @staticmethod
    def _normalize_features(features: list[str] | tuple[str, ...] | Any) -> list[str]:
        allowed = set(PANEL_FEATURES)
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in features or ():
            feature = str(raw or "").strip().lower()
            if feature not in allowed or feature in seen:
                continue
            seen.add(feature)
            normalized.append(feature)
        return normalized

    @staticmethod
    def _normalize_filiais(filiais: list[str] | tuple[str, ...] | Any) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in filiais or ():
            text = str(raw or "").strip().lower()
            if text in {"*", "all", "todos", "todas"}:
                return ["*"]
            digits = "".join(ch for ch in text if ch.isdigit())
            value = digits.lstrip("0") or ("0" if digits else "")
            if value and value not in seen:
                seen.add(value)
                normalized.append(value)
        return normalized

    @contextmanager
    def _connect(self, row_factory: Any | None = None) -> Any:
        if not self.database_url:
            raise RuntimeError("Banco de usuarios do painel nao configurado.")
        if self._pool is None:
            self._pool = get_connection_pool(
                self.database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
            )
        with self._pool.connection() as conn:
            if row_factory is not None:
                conn.row_factory = row_factory
            yield conn

    @contextmanager
    def _bootstrap_connect(self) -> Any:
        if not self.bootstrap_database_url:
            raise RuntimeError("Banco de bootstrap dos usuarios do painel nao configurado.")
        if self._bootstrap_pool is None:
            self._bootstrap_pool = get_connection_pool(
                self.bootstrap_database_url,
                connect_timeout_seconds=self.connect_timeout_seconds,
            )
        with self._bootstrap_pool.connection() as conn:
            yield conn

    def _runtime_database_user(self) -> str:
        try:
            return str(urlparse(self.database_url).username or "").strip()
        except Exception:
            return ""


def _clean_identifier(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", str(value or "").strip())
    return cleaned or fallback


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
