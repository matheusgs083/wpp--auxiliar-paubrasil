from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Iterable, Sequence
from threading import Lock
from typing import Any

from fastapi import HTTPException, Request, Response


class AdminPanelSessionService:
    def __init__(
        self,
        *,
        admin_api_token: str,
        verify_token: str,
        api_auth_tokens: Sequence[str],
        finance_panel_tokens: Sequence[tuple[str, Sequence[str]]],
        critica_panel_tokens: Sequence[tuple[str, Sequence[str]]],
        session_cookie_name: str,
        session_ttl_seconds: int,
        login_window_seconds: int,
        login_max_failures: int,
    ) -> None:
        self.admin_api_token = str(admin_api_token or "")
        self.verify_token = str(verify_token or "")
        self.api_auth_tokens = tuple(str(token or "") for token in api_auth_tokens)
        self.finance_panel_tokens = tuple((str(token or ""), tuple(filiais)) for token, filiais in finance_panel_tokens)
        self.critica_panel_tokens = tuple((str(token or ""), tuple(filiais)) for token, filiais in critica_panel_tokens)
        self.session_cookie_name = session_cookie_name
        self.session_ttl_seconds = session_ttl_seconds
        self.login_window_seconds = login_window_seconds
        self.login_max_failures = login_max_failures
        self._login_lock = Lock()
        self._login_failures: dict[str, list[float]] = {}

    def context_from_token(self, token: str | None) -> dict[str, Any] | None:
        provided_token = str(token or "").strip()
        if not provided_token:
            return None
        if self.admin_token_matches(provided_token):
            return {"mode": "admin", "is_admin": True, "filiais": ()}
        finance_filiais = self.finance_panel_token_filiais(provided_token)
        if finance_filiais:
            return {"mode": "financeiro", "is_admin": False, "filiais": finance_filiais}
        critica_filiais = self.critica_panel_token_filiais(provided_token)
        if critica_filiais:
            return {"mode": "critica", "is_admin": False, "filiais": critica_filiais}
        return None

    def context_from_session_cookie(self, request: Request) -> dict[str, Any] | None:
        return self._deserialize_session(request.cookies.get(self.session_cookie_name))

    def set_session_cookie(self, response: Response, request: Request, context: dict[str, Any]) -> None:
        response.set_cookie(
            key=self.session_cookie_name,
            value=self._serialize_session(context),
            max_age=self.session_ttl_seconds,
            httponly=True,
            secure=self._request_uses_https(request),
            samesite="lax",
            path="/",
        )

    def check_login_rate_limit(self, request: Request) -> None:
        key = self._login_key(request)
        now = time.time()
        cutoff = now - self.login_window_seconds
        with self._login_lock:
            failures = [ts for ts in self._login_failures.get(key, []) if ts >= cutoff]
            self._login_failures[key] = failures
            if len(failures) >= self.login_max_failures:
                raise HTTPException(status_code=429, detail="Muitas tentativas de login. Aguarde alguns minutos.")

    def record_login_failure(self, request: Request) -> None:
        key = self._login_key(request)
        now = time.time()
        cutoff = now - self.login_window_seconds
        with self._login_lock:
            failures = [ts for ts in self._login_failures.get(key, []) if ts >= cutoff]
            failures.append(now)
            self._login_failures[key] = failures

    def clear_login_failures(self, request: Request) -> None:
        key = self._login_key(request)
        with self._login_lock:
            self._login_failures.pop(key, None)

    def admin_token_matches(self, token: str | None) -> bool:
        expected_token = self.admin_api_token.strip()
        provided_token = str(token or "").strip()
        return bool(expected_token and provided_token and secrets.compare_digest(provided_token, expected_token))

    def finance_panel_token_filiais(self, token: str | None) -> tuple[str, ...]:
        return self._panel_token_filiais(token, self.finance_panel_tokens)

    def critica_panel_token_filiais(self, token: str | None) -> tuple[str, ...]:
        return self._panel_token_filiais(token, self.critica_panel_tokens)

    def panel_context_mode(self, context: dict[str, Any] | None) -> str:
        return str((context or {}).get("mode") or "").strip().lower()

    def panel_context_has_all_filiais(self, context: dict[str, Any] | None) -> bool:
        return any(str(filial).strip() == "*" for filial in (context or {}).get("filiais", ()))

    def panel_context_is_critica_only(self, context: dict[str, Any] | None) -> bool:
        return bool(context) and not bool(context.get("is_admin")) and self.panel_context_mode(context) == "critica"

    def panel_context_can_access_feature(self, context: dict[str, Any] | None, feature: str) -> bool:
        if not context:
            return False
        if bool(context.get("is_admin")):
            return True
        mode = self.panel_context_mode(context)
        clean_feature = str(feature or "").strip().lower()
        if mode == "critica":
            return clean_feature in {"critica", "critica_import", "import_status"}
        if mode == "financeiro":
            return clean_feature not in {"admin_access", "usage"}
        return False

    def require_feature(self, context: dict[str, Any] | None, feature: str) -> None:
        if not self.panel_context_can_access_feature(context, feature):
            raise HTTPException(status_code=403, detail="Acesso nao permitido para este perfil.")

    def allowed_import_datasets(
        self,
        context: dict[str, Any] | None,
        dataset_names: Iterable[str],
    ) -> set[str] | None:
        if not context or bool(context.get("is_admin")) or self.panel_context_mode(context) == "financeiro":
            return None
        if self.panel_context_mode(context) == "critica":
            allowed_filiais = {
                str(filial).strip()
                for filial in context.get("filiais", ())
                if str(filial).strip() and str(filial).strip() != "*"
            }
            if self.panel_context_has_all_filiais(context) or not allowed_filiais:
                return {dataset for dataset in dataset_names if str(dataset).startswith("critica_op_")}
            return {f"critica_op_{filial}" for filial in allowed_filiais}
        return set()

    def _panel_token_filiais(
        self,
        token: str | None,
        configured_tokens: Sequence[tuple[str, Sequence[str]]],
    ) -> tuple[str, ...]:
        provided_token = str(token or "").strip()
        if not provided_token:
            return ()
        for expected_token, filiais in configured_tokens:
            if expected_token and secrets.compare_digest(provided_token, expected_token):
                return tuple(str(filial).strip() for filial in filiais if str(filial).strip())
        return ()

    def _session_secret(self) -> bytes:
        seeds = [self.admin_api_token.strip(), self.verify_token.strip(), *self.api_auth_tokens]
        secret_seed = next((seed for seed in seeds if seed), "")
        if not secret_seed:
            raise HTTPException(status_code=503, detail="Sessao do painel indisponivel.")
        return hashlib.sha256(f"bot-admin-panel-session-v1:{secret_seed}".encode("utf-8")).digest()

    def _serialize_session(self, context: dict[str, Any]) -> str:
        now = int(time.time())
        payload = {
            "mode": str(context.get("mode") or "admin"),
            "is_admin": bool(context.get("is_admin")),
            "filiais": [str(filial).strip() for filial in context.get("filiais", ()) if str(filial).strip()],
            "iat": now,
            "exp": now + self.session_ttl_seconds,
        }
        payload_bytes = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encoded_payload = self._base64url_encode(payload_bytes)
        signature = hmac.new(self._session_secret(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded_payload}.{self._base64url_encode(signature)}"

    def _deserialize_session(self, raw_cookie: str | None) -> dict[str, Any] | None:
        raw_value = str(raw_cookie or "").strip()
        if "." not in raw_value:
            return None
        encoded_payload, encoded_signature = raw_value.split(".", 1)
        if not encoded_payload or not encoded_signature:
            return None
        expected_signature = hmac.new(
            self._session_secret(),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        try:
            provided_signature = self._base64url_decode(encoded_signature)
            payload = json.loads(self._base64url_decode(encoded_payload).decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not secrets.compare_digest(provided_signature, expected_signature):
            return None
        if not isinstance(payload, dict) or int(payload.get("exp") or 0) < int(time.time()):
            return None
        mode = str(payload.get("mode") or "").strip().lower()
        is_admin = bool(payload.get("is_admin"))
        filiais = tuple(str(filial).strip() for filial in payload.get("filiais", []) if str(filial).strip())
        if is_admin and mode == "admin":
            return {"mode": "admin", "is_admin": True, "filiais": ()}
        if mode == "financeiro" and filiais:
            return {"mode": "financeiro", "is_admin": False, "filiais": filiais}
        if mode == "critica" and filiais:
            return {"mode": "critica", "is_admin": False, "filiais": filiais}
        return None

    @staticmethod
    def _request_uses_https(request: Request) -> bool:
        forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
        return request.url.scheme == "https" or forwarded_proto == "https"

    @staticmethod
    def _login_key(request: Request) -> str:
        forwarded_for = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
        return forwarded_for or (request.client.host if request.client else "unknown")

    @staticmethod
    def _base64url_encode(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _base64url_decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
