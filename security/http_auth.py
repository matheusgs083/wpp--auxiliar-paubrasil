from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Request


class DeniedReplyThrottle:
    def __init__(
        self,
        default_cooldown_minutes: int,
        unregistered_cooldown_minutes: int,
    ) -> None:
        self.default_cooldown = timedelta(minutes=max(int(default_cooldown_minutes), 1))
        self.unregistered_cooldown = timedelta(minutes=max(int(unregistered_cooldown_minutes), 1))
        self._cleanup_window = max(self.default_cooldown, self.unregistered_cooldown) * 2
        self._last_reply_at: dict[str, datetime] = {}
        self._lock = Lock()

    def should_send(self, number: str, reason: str) -> bool:
        normalized_number = str(number or "").strip()
        if not normalized_number:
            return False

        now = datetime.now(timezone.utc)
        cooldown = self.unregistered_cooldown if reason == "number_not_registered" else self.default_cooldown
        with self._lock:
            self._cleanup_locked(now)
            last_reply_at = self._last_reply_at.get(normalized_number)
            if last_reply_at is not None and now - last_reply_at < cooldown:
                return False
            self._last_reply_at[normalized_number] = now
            return True

    def cooldown_minutes_for(self, reason: str) -> int:
        cooldown = self.unregistered_cooldown if reason == "number_not_registered" else self.default_cooldown
        return max(1, int(cooldown.total_seconds() // 60))

    def _cleanup_locked(self, now: datetime) -> None:
        expired_numbers = [
            number
            for number, last_reply_at in self._last_reply_at.items()
            if now - last_reply_at >= self._cleanup_window
        ]
        for number in expired_numbers:
            self._last_reply_at.pop(number, None)


class HttpAuthDependencies:
    def __init__(
        self,
        *,
        settings: Any,
        security_monitor: Any,
        admin_panel_session_service: Any,
        admin_import_datasets: dict[str, dict[str, Any]],
        normalize_admin_import_dataset: Callable[[str], str],
    ) -> None:
        self.settings = settings
        self.security_monitor = security_monitor
        self.admin_panel_session_service = admin_panel_session_service
        self.admin_import_datasets = admin_import_datasets
        self.normalize_admin_import_dataset = normalize_admin_import_dataset
        self.denied_reply_throttle = DeniedReplyThrottle(
            default_cooldown_minutes=settings.denied_reply_cooldown_minutes,
            unregistered_cooldown_minutes=settings.denied_unregistered_reply_cooldown_minutes,
        )

    def add_security_middleware(self, app: FastAPI) -> None:
        @app.middleware("http")
        async def add_security_headers(request: Request, call_next: Any) -> Any:
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if request.url.scheme == "https":
                response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            return response

    def request_metadata(self, request: Request, **extra: Any) -> dict[str, Any]:
        metadata = {
            "method": request.method,
            "client_host": request.client.host if request.client else "",
            "user_agent": request.headers.get("user-agent", ""),
            "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
        }
        metadata.update({key: value for key, value in extra.items() if value is not None and value != ""})
        return metadata

    def record_security_event(
        self,
        request: Request,
        *,
        channel: str,
        event_type: str,
        decision: str,
        phone_number: str | None = None,
        area: str | None = None,
        reason: str | None = None,
        **extra: Any,
    ) -> None:
        self.security_monitor.record_event(
            channel=channel,
            path=request.url.path,
            event_type=event_type,
            decision=decision,
            phone_number=phone_number,
            area=area,
            reason=reason,
            metadata=self.request_metadata(request, **extra),
        )

    def record_security_event_for_path(
        self,
        *,
        path: str,
        metadata: dict[str, Any],
        channel: str,
        event_type: str,
        decision: str,
        phone_number: str | None = None,
        area: str | None = None,
        reason: str | None = None,
        **extra: Any,
    ) -> None:
        combined_metadata = dict(metadata)
        combined_metadata.update({key: value for key, value in extra.items() if value is not None and value != ""})
        self.security_monitor.record_event(
            channel=channel,
            path=path,
            event_type=event_type,
            decision=decision,
            phone_number=phone_number,
            area=area,
            reason=reason,
            metadata=combined_metadata,
        )

    def should_send_denied_reply(self, number: str, reason: str) -> bool:
        persisted_decision = self.security_monitor.should_send_denied_reply(number=number, reason=reason)
        if persisted_decision is not None:
            return persisted_decision
        return self.denied_reply_throttle.should_send(number=number, reason=reason)

    def denied_reply_cooldown_minutes_for(self, reason: str) -> int:
        return self.denied_reply_throttle.cooldown_minutes_for(reason)

    def require_admin_token(self, x_admin_token: str | None, request: Request | None = None) -> None:
        expected_token = self.settings.admin_api_token.strip()
        if not expected_token:
            if request is not None:
                self.record_security_event(
                    request,
                    channel="api",
                    event_type="admin_auth",
                    decision="misconfigured",
                    reason="admin_token_not_configured",
                )
            raise HTTPException(status_code=503, detail="Rotas administrativas indisponiveis.")

        provided_token = str(x_admin_token or "").strip()
        if provided_token and secrets.compare_digest(provided_token, expected_token):
            if request is not None:
                self.record_security_event(
                    request,
                    channel="api",
                    event_type="admin_auth",
                    decision="allowed",
                )
            return

        if request is not None:
            self.record_security_event(
                request,
                channel="api",
                event_type="admin_auth",
                decision="denied",
                reason="invalid_admin_token",
            )
        raise HTTPException(status_code=401, detail="Admin token invalido.")

    def require_api_auth(
        self,
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
    ) -> None:
        if not self.settings.api_auth_enabled:
            return

        provided_tokens = []
        bearer_token = self.extract_bearer_token(authorization)
        if bearer_token:
            provided_tokens.append(bearer_token)
        if x_api_token and x_api_token.strip():
            provided_tokens.append(x_api_token.strip())

        valid_tokens = tuple(self.settings.api_auth_tokens)
        if not valid_tokens:
            self.record_security_event(
                request,
                channel="api",
                event_type="api_auth",
                decision="misconfigured",
                reason="api_auth_without_tokens",
            )
            raise HTTPException(status_code=503, detail="Autenticacao da API habilitada, mas sem token configurado.")
        if any(self.token_matches(candidate, valid_tokens) for candidate in provided_tokens):
            self.record_security_event(
                request,
                channel="api",
                event_type="api_auth",
                decision="allowed",
            )
            return

        self.record_security_event(
            request,
            channel="api",
            event_type="api_auth",
            decision="denied",
            reason="invalid_or_missing_api_token",
        )
        raise HTTPException(status_code=401, detail="Token da API invalido ou ausente.")

    def panel_context_allowed_import_datasets(self, context: dict[str, Any] | None) -> set[str] | None:
        return self.admin_panel_session_service.allowed_import_datasets(context, self.admin_import_datasets)

    def require_admin_panel_import_dataset(self, context: dict[str, Any] | None, dataset: str) -> str:
        normalized_dataset = self.normalize_admin_import_dataset(dataset)
        allowed_datasets = self.panel_context_allowed_import_datasets(context)
        if allowed_datasets is not None and normalized_dataset not in allowed_datasets:
            raise HTTPException(status_code=403, detail="Este token so pode importar relatorios de critica liberados.")
        return normalized_dataset

    def require_admin_panel_auth(
        self,
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
        x_admin_token: str | None,
    ) -> dict[str, Any]:
        header_context = self.admin_panel_session_service.context_from_token(x_admin_token)
        if header_context:
            self.record_security_event(
                request,
                channel="api",
                event_type="admin_panel_auth",
                decision="allowed",
                reason=(
                    "admin_token"
                    if header_context.get("is_admin")
                    else f"{self.admin_panel_session_service.panel_context_mode(header_context)}_token"
                ),
            )
            return header_context

        session_context = self.admin_panel_session_service.context_from_session_cookie(request)
        if session_context:
            self.record_security_event(
                request,
                channel="api",
                event_type="admin_panel_auth",
                decision="allowed",
                reason="panel_session",
            )
            return session_context

        self.require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
        self.require_admin_token(x_admin_token, request=request)
        return {"mode": "admin", "is_admin": True, "filiais": ()}

    def require_admin_api_auth(
        self,
        request: Request,
        authorization: str | None,
        x_api_token: str | None,
        x_admin_token: str | None,
    ) -> None:
        if self.admin_panel_session_service.admin_token_matches(x_admin_token):
            self.record_security_event(
                request,
                channel="api",
                event_type="admin_auth",
                decision="allowed",
                reason="admin_token_for_admin_api",
            )
            return
        session_context = self.admin_panel_session_service.context_from_session_cookie(request)
        if session_context and session_context.get("is_admin"):
            self.record_security_event(
                request,
                channel="api",
                event_type="admin_auth",
                decision="allowed",
                reason="admin_session_for_admin_api",
            )
            return
        self.require_api_auth(request=request, authorization=authorization, x_api_token=x_api_token)
        self.require_admin_token(x_admin_token, request=request)

    def require_admin_scope_for_number_routes(
        self,
        request: Request,
        x_admin_token: str | None,
    ) -> None:
        if not self.settings.api_require_admin_for_number:
            return
        session_context = self.admin_panel_session_service.context_from_session_cookie(request)
        if session_context and session_context.get("is_admin"):
            return
        self.require_admin_token(x_admin_token, request=request)

    def decision_has_unrestricted_lookup_access(self, decision: Any) -> bool:
        roles = {str(role or "").strip().lower() for role in getattr(decision, "roles", ())}
        if "admin" in roles:
            return True
        return "financeiro" in roles and not getattr(decision, "sectors", ()) and not getattr(decision, "gv_vdes", ())

    def require_webhook_token(self, request: Request, x_bot_token: str | None, payload: dict[str, Any] | None = None) -> None:
        expected_token = self.settings.verify_token.strip()
        evolution_payload_key = str((payload or {}).get("apikey") or "").strip()
        evolution_webhook_api_keys = [candidate for candidate in self.settings.evolution_webhook_api_keys if candidate]
        if self.settings.evolution_webhook_allow_api_key_fallback and self.settings.evolution_api_key.strip():
            evolution_webhook_api_keys.append(self.settings.evolution_api_key.strip())
        accepted_evolution_keys = tuple(dict.fromkeys(evolution_webhook_api_keys))

        if expected_token and x_bot_token and secrets.compare_digest(x_bot_token.strip(), expected_token):
            self.record_security_event(
                request,
                channel="webhook",
                event_type="webhook_auth",
                decision="allowed",
                reason="x_bot_token",
            )
            return

        if evolution_payload_key and self.token_matches(evolution_payload_key, accepted_evolution_keys):
            self.record_security_event(
                request,
                channel="webhook",
                event_type="webhook_auth",
                decision="allowed",
                reason="webhook_apikey",
            )
            return

        if not expected_token and not accepted_evolution_keys:
            self.record_security_event(
                request,
                channel="webhook",
                event_type="webhook_auth",
                decision="misconfigured",
                reason="webhook_auth_not_configured",
            )
            raise HTTPException(status_code=503, detail="Webhook indisponivel.")

        self.record_security_event(
            request,
            channel="webhook",
            event_type="webhook_auth",
            decision="denied",
            reason="invalid_or_missing_webhook_token",
        )
        raise HTTPException(status_code=401, detail="Nao autorizado.")

    def require_meta_cloud_signature(
        self,
        request: Request,
        *,
        raw_body: bytes,
        x_hub_signature_256: str | None,
    ) -> None:
        app_secret = self.settings.meta_cloud_app_secret.strip()
        if not app_secret:
            self.record_security_event(
                request,
                channel="meta_webhook",
                event_type="meta_signature",
                decision="misconfigured",
                reason="meta_app_secret_missing",
            )
            raise HTTPException(status_code=503, detail="Webhook Meta indisponivel.")

        provided = str(x_hub_signature_256 or "").strip()
        if not provided.startswith("sha256="):
            self.record_security_event(
                request,
                channel="meta_webhook",
                event_type="meta_signature",
                decision="denied",
                reason="missing_or_invalid_signature_header",
            )
            raise HTTPException(status_code=401, detail="Assinatura Meta invalida ou ausente.")

        expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(provided, expected):
            self.record_security_event(
                request,
                channel="meta_webhook",
                event_type="meta_signature",
                decision="denied",
                reason="signature_mismatch",
            )
            raise HTTPException(status_code=401, detail="Assinatura Meta invalida ou ausente.")

        self.record_security_event(
            request,
            channel="meta_webhook",
            event_type="meta_signature",
            decision="allowed",
            reason="x_hub_signature_256",
        )

    @staticmethod
    def extract_bearer_token(authorization: str | None) -> str:
        raw_value = str(authorization or "").strip()
        if not raw_value:
            return ""
        parts = raw_value.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return ""
        return parts[1].strip()

    @staticmethod
    def token_matches(candidate: str, expected_values: tuple[str, ...]) -> bool:
        cleaned_candidate = str(candidate or "").strip()
        if not cleaned_candidate:
            return False
        return any(secrets.compare_digest(cleaned_candidate, expected) for expected in expected_values if expected)
