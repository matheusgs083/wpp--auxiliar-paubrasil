from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

AUTH_PATH = "/auth/realms/portal/protocol/openid-connect/token"
PAYMENTS_PATH = "/v1/payments"
CLIENTS_PATH = "/v1/clients"
PAYMENT_INVOICE_REPORT_PATH = "/v1/payments/report/invoice"
STATEMENT_MOVEMENTS_RESUME_PATH = "/v1/statments/movements/resume"
STATEMENT_MOVEMENTS_EXPORT_PDF_PATH = "/v1/statments/movements/export/pdf"
STATEMENT_MOVEMENTS_EXPORT_XLSX_PATH = "/v1/statments/movements/export/xlsx"
PORTAL_ORIGIN = "https://portal.payip.com.br"
TOKEN_EXPIRY_LEEWAY_SECONDS = 120

logger = logging.getLogger(__name__)


DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": PORTAL_ORIGIN,
    "Referer": f"{PORTAL_ORIGIN}/",
    "Sec-CH-UA": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}


class PayipError(RuntimeError):
    """Base error for PayIP integration failures."""


class PayipConfigError(PayipError):
    """Raised when the PayIP integration is not configured."""


class PayipMfaRequired(PayipError):
    """Raised when a fresh MFA code is required to create a new session."""


class PayipAuthError(PayipError):
    """Raised when PayIP authentication or refresh fails."""


@dataclass(frozen=True)
class PayipConfig:
    base_url: str
    client_id: str
    username: str
    password: str
    company_id: str
    token_cache_file: str
    company_ids: tuple[tuple[str, str], ...] = ()
    company_tax_ids: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 30.0
    mfa_code: str = ""

    @property
    def enabled(self) -> bool:
        return bool(
            self.base_url
            and self.client_id
            and self.username
            and self.password
            and (self.company_id or self.company_ids)
        )

    def company_map(self) -> dict[str, str]:
        company_map = {
            _normalize_filial_code(key): value.strip()
            for key, value in self.company_ids
            if _normalize_filial_code(key) and value.strip()
        }
        if self.company_id and "3" not in company_map:
            company_map["3"] = self.company_id
        return company_map

    def company_tax_map(self) -> dict[str, str]:
        return {
            _normalize_filial_code(key): _only_digits(value)
            for key, value in self.company_tax_ids
            if _normalize_filial_code(key) and _only_digits(value)
        }


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: float
    refresh_expires_at: float
    expires_in: int
    refresh_expires_in: int
    token_type: str = "Bearer"
    not_before_policy: int | None = None
    session_state: str | None = None
    scope: str | None = None

    def access_is_valid(self) -> bool:
        return self._is_valid(self.access_expires_at)

    def refresh_is_valid(self) -> bool:
        return self._is_valid(self.refresh_expires_at)

    def authorization_header(self) -> str:
        return f"{self.token_type or 'Bearer'} {self.access_token}"

    def to_cache_payload(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "expires_in": self.expires_in,
            "refresh_expires_in": self.refresh_expires_in,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "not-before-policy": self.not_before_policy,
            "session_state": self.session_state,
            "scope": self.scope,
            "access_expires_at": self.access_expires_at,
            "refresh_expires_at": self.refresh_expires_at,
        }

    @staticmethod
    def _is_valid(expires_at: float) -> bool:
        return expires_at > time.time() + TOKEN_EXPIRY_LEEWAY_SECONDS


class TokenStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None

        try:
            with self.path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("PayIP token cache invalid; ignoring file: %s", exc)
            return None

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=True, indent=2)
        temp_path.replace(self.path)
        self._restrict_permissions()

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove PayIP token cache: %s", exc)

    def _restrict_permissions(self) -> None:
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            return


class PayipTokenManager:
    def __init__(self, config: PayipConfig, token_store: TokenStore) -> None:
        self.config = config
        self.token_store = token_store
        self.tokens = self._load_cached_tokens()

    def ensure_access_token(self, client: httpx.Client) -> TokenPair:
        if self.tokens and self.tokens.access_is_valid():
            logger.info("PayIP using cached access token")
            return self.tokens

        if self.tokens and self.tokens.refresh_is_valid():
            logger.info("PayIP access token expired; refreshing session")
            try:
                return self.refresh(client)
            except PayipAuthError as exc:
                logger.warning("PayIP refresh failed; clearing cached session: %s", exc)
                self.token_store.clear()
                self.tokens = None

        return self.login(client)

    def login(self, client: httpx.Client, *, mfa_code: str | None = None) -> TokenPair:
        payload = {
            "grant_type": "password",
            "client_id": self.config.client_id,
            "username": self.config.username,
            "password": self.config.password,
        }
        response = self._post_auth(client, payload)
        logger.info("PayIP initial auth response status=%s", response.status_code)

        if self._requires_mfa_code(response):
            code = (mfa_code or self.config.mfa_code or "").strip()
            if not code:
                raise PayipMfaRequired(
                    "PayIP requested MFA. Bootstrap a session with PAYIP_MFA_CODE "
                    "or refresh the token cache manually."
                )
            payload["code"] = code
            response = self._post_auth(client, payload)
            logger.info("PayIP MFA auth response status=%s", response.status_code)

        self._raise_for_status(response, "PayIP authentication failed")
        self.tokens = self._parse_tokens(response.json())
        self._save_tokens()
        logger.info(
            "PayIP authenticated session_state=%s expires_in=%s refresh_expires_in=%s",
            self.tokens.session_state,
            self.tokens.expires_in,
            self.tokens.refresh_expires_in,
        )
        return self.tokens

    def refresh(self, client: httpx.Client) -> TokenPair:
        if not self.tokens:
            return self.login(client)
        if not self.tokens.refresh_is_valid():
            self.token_store.clear()
            self.tokens = None
            raise PayipAuthError("PayIP refresh token expired")

        response = self._post_auth(
            client,
            {
                "grant_type": "refresh_token",
                "client_id": self.config.client_id,
                "refresh_token": self.tokens.refresh_token,
            },
        )
        logger.info("PayIP refresh response status=%s", response.status_code)
        self._raise_for_status(response, "PayIP token refresh failed")
        self.tokens = self._parse_tokens(response.json())
        self._save_tokens()
        logger.info(
            "PayIP refreshed session_state=%s expires_in=%s refresh_expires_in=%s",
            self.tokens.session_state,
            self.tokens.expires_in,
            self.tokens.refresh_expires_in,
        )
        return self.tokens

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.config.enabled,
            "token_cache_file": str(self.token_store.path),
            "has_cached_tokens": self.tokens is not None,
            "access_token_valid": bool(self.tokens and self.tokens.access_is_valid()),
            "refresh_token_valid": bool(self.tokens and self.tokens.refresh_is_valid()),
            "access_expires_at": self.tokens.access_expires_at if self.tokens else None,
            "refresh_expires_at": self.tokens.refresh_expires_at if self.tokens else None,
            "session_state": self.tokens.session_state if self.tokens else None,
            "scope": self.tokens.scope if self.tokens else None,
        }

    def _load_cached_tokens(self) -> TokenPair | None:
        cached = self.token_store.load()
        if not cached:
            return None

        metadata = cached.get("metadata", {})
        if metadata.get("base_url") != self.config.base_url.rstrip("/"):
            return None
        if metadata.get("client_id") != self.config.client_id:
            return None
        if metadata.get("username") != self.config.username:
            return None

        tokens_data = cached.get("tokens")
        if not isinstance(tokens_data, dict):
            return None

        try:
            tokens = TokenPair(
                access_token=tokens_data["access_token"],
                refresh_token=tokens_data["refresh_token"],
                access_expires_at=float(tokens_data["access_expires_at"]),
                refresh_expires_at=float(tokens_data["refresh_expires_at"]),
                expires_in=_optional_int(tokens_data.get("expires_in")) or 3_600,
                refresh_expires_in=_optional_int(tokens_data.get("refresh_expires_in")) or 21_600,
                token_type=str(tokens_data.get("token_type") or "Bearer"),
                not_before_policy=_optional_int(
                    tokens_data.get("not-before-policy") or tokens_data.get("not_before_policy")
                ),
                session_state=tokens_data.get("session_state"),
                scope=tokens_data.get("scope"),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("PayIP token cache incomplete; ignoring file")
            return None

        if not tokens.access_is_valid() and not tokens.refresh_is_valid():
            logger.info("PayIP cached tokens expired; clearing cache")
            self.token_store.clear()
            return None

        logger.info(
            "PayIP token cache loaded access_valid=%s refresh_valid=%s",
            tokens.access_is_valid(),
            tokens.refresh_is_valid(),
        )
        return tokens

    def _save_tokens(self) -> None:
        if not self.tokens:
            return

        self.token_store.save(
            {
                "metadata": {
                    "base_url": self.config.base_url.rstrip("/"),
                    "client_id": self.config.client_id,
                    "username": self.config.username,
                    "company_id": self.config.company_id,
                    "saved_at": time.time(),
                },
                "tokens": self.tokens.to_cache_payload(),
            }
        )
        logger.info(
            "PayIP tokens cached access_expires_at=%s refresh_expires_at=%s",
            self.tokens.access_expires_at,
            self.tokens.refresh_expires_at,
        )

    @staticmethod
    def _post_auth(client: httpx.Client, payload: dict[str, Any]) -> httpx.Response:
        return client.post(
            AUTH_PATH,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    @staticmethod
    def _requires_mfa_code(response: httpx.Response) -> bool:
        if not response.is_success:
            return False
        try:
            data = response.json()
        except ValueError:
            return False
        return data.get("status") == "REQUEST_CODE_MFA"

    @staticmethod
    def _parse_tokens(data: dict[str, Any]) -> TokenPair:
        try:
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
        except KeyError as exc:
            raise PayipAuthError("PayIP auth response did not include tokens") from exc

        expires_in = _optional_int(data.get("expires_in")) or 3_600
        refresh_expires_in = _optional_int(data.get("refresh_expires_in")) or 21_600
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=_token_expires_at(
                token=access_token,
                expires_in=expires_in,
            ),
            refresh_expires_at=_token_expires_at(
                token=refresh_token,
                expires_in=refresh_expires_in,
            ),
            expires_in=expires_in,
            refresh_expires_in=refresh_expires_in,
            token_type=str(data.get("token_type") or "Bearer"),
            not_before_policy=_optional_int(data.get("not-before-policy")),
            session_state=data.get("session_state"),
            scope=data.get("scope"),
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response, message: str) -> None:
        if 200 <= response.status_code < 300:
            return
        raise PayipAuthError(
            f"{message}: HTTP {response.status_code}. Response: {_safe_response_body(response)}"
        )


class PayipClient:
    def __init__(self, config: PayipConfig) -> None:
        if not config.enabled:
            raise PayipConfigError("PayIP integration is not fully configured.")
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(config.timeout_seconds),
            headers=DEFAULT_HEADERS,
            http2=True,
        )
        self.tokens = PayipTokenManager(config, TokenStore(config.token_cache_file))

    def close(self) -> None:
        self._client.close()

    def status(self) -> dict[str, Any]:
        return self.tokens.status()

    def company_map(self) -> dict[str, str]:
        return self.config.company_map()

    def company_tax_map(self) -> dict[str, str]:
        return self.config.company_tax_map()

    def resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
        return self._resolve_company_id(filial=filial, company_id=company_id)

    def resolve_company_tax_id(self, *, filial: str, company_tax_id: str = "") -> str:
        return self._resolve_company_tax_id(filial=filial, company_tax_id=company_tax_id)

    def bootstrap_session(self, *, mfa_code: str) -> dict[str, Any]:
        self.tokens.login(self._client, mfa_code=mfa_code)
        return self.status()

    def list_payments(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str = "",
        client_code: str = "",
        invoice: str = "",
        search: str = "",
        due_date_start: str = "",
        due_date_end: str = "",
        created_at_start: str = "",
        created_at_end: str = "",
        filial: str = "",
        company_id: str = "",
    ) -> dict[str, Any]:
        token_pair = self.tokens.ensure_access_token(self._client)
        resolved_company_id = self._resolve_company_id(filial=filial, company_id=company_id)
        response = self._get_payments(
            token_pair=token_pair,
            page=page,
            page_size=page_size,
            status=status,
            client_code=client_code,
            invoice=invoice,
            search=search,
            due_date_start=due_date_start,
            due_date_end=due_date_end,
            created_at_start=created_at_start,
            created_at_end=created_at_end,
            company_id=resolved_company_id,
        )
        logger.info(
            "PayIP payments response status=%s page=%s page_size=%s company_id=%s filter_status=%s client_code=%s invoice=%s search=%s due=%s..%s created=%s..%s",
            response.status_code,
            page,
            page_size,
            resolved_company_id,
            status or "-",
            client_code or "-",
            invoice or "-",
            search or "-",
            due_date_start or "-",
            due_date_end or "-",
            created_at_start or "-",
            created_at_end or "-",
        )

        if response.status_code == 401:
            logger.warning("PayIP access token rejected; refreshing and retrying once")
            token_pair = self.tokens.refresh(self._client)
            response = self._get_payments(
                token_pair=token_pair,
                page=page,
                page_size=page_size,
                status=status,
                client_code=client_code,
                invoice=invoice,
                search=search,
                due_date_start=due_date_start,
                due_date_end=due_date_end,
                created_at_start=created_at_start,
                created_at_end=created_at_end,
                company_id=resolved_company_id,
            )
            logger.info("PayIP payments retry response status=%s", response.status_code)

        if not 200 <= response.status_code < 300:
            raise PayipError(
                f"PayIP payments request failed: HTTP {response.status_code}. "
                f"Response: {_safe_response_body(response)}"
            )

        data = response.json()
        logger.info("PayIP payments summary %s", summarize_collection_response(data))
        return data

    def list_clients(
        self,
        *,
        page: int = 1,
        page_size: int = 10,
        search: str = "",
        status: str = "ACTIVE",
        code: str = "",
        tax_payer_id: str = "",
        filial: str = "",
        company_id: str = "",
    ) -> dict[str, Any]:
        token_pair = self.tokens.ensure_access_token(self._client)
        resolved_company_id = self._resolve_company_id(filial=filial, company_id=company_id)
        response = self._get_clients(
            token_pair=token_pair,
            page=page,
            page_size=page_size,
            search=search,
            status=status,
            code=code,
            tax_payer_id=tax_payer_id,
            company_id=resolved_company_id,
        )
        logger.info(
            "PayIP clients response status=%s page=%s page_size=%s company_id=%s code=%s tax_payer_id=%s",
            response.status_code,
            page,
            page_size,
            resolved_company_id,
            code or "-",
            _mask_document(tax_payer_id),
        )
        if response.status_code == 401:
            logger.warning("PayIP access token rejected on clients request; refreshing and retrying once")
            token_pair = self.tokens.refresh(self._client)
            response = self._get_clients(
                token_pair=token_pair,
                page=page,
                page_size=page_size,
                search=search,
                status=status,
                code=code,
                tax_payer_id=tax_payer_id,
                company_id=resolved_company_id,
            )
            logger.info("PayIP clients retry response status=%s", response.status_code)

        if not 200 <= response.status_code < 300:
            raise PayipError(
                f"PayIP clients request failed: HTTP {response.status_code}. "
                f"Response: {_safe_response_body(response)}"
            )
        return response.json()

    def create_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        token_pair = self.tokens.ensure_access_token(self._client)
        response = self._client.post(
            PAYMENTS_PATH,
            json=payload,
            headers={"Authorization": token_pair.authorization_header()},
        )
        logger.info(
            "PayIP create payment response status=%s external_id=%s amount=%s company_tax_id=%s",
            response.status_code,
            payload.get("externalId") or "-",
            payload.get("amount") or "-",
            _mask_document(payload.get("companyTaxId")),
        )
        if response.status_code == 401:
            logger.warning("PayIP access token rejected on create payment; refreshing and retrying once")
            token_pair = self.tokens.refresh(self._client)
            response = self._client.post(
                PAYMENTS_PATH,
                json=payload,
                headers={"Authorization": token_pair.authorization_header()},
            )
            logger.info("PayIP create payment retry response status=%s", response.status_code)

        if not 200 <= response.status_code < 300:
            raise PayipError(
                f"PayIP create payment failed: HTTP {response.status_code}. "
                f"Response: {_safe_response_body(response)}"
            )
        return response.json()

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        token_pair = self.tokens.ensure_access_token(self._client)
        normalized_payment_id = str(payment_id or "").strip()
        if not normalized_payment_id:
            raise PayipError("PayIP payment_id vazio")
        response = self._client.get(
            f"{PAYMENTS_PATH}/{normalized_payment_id}",
            headers={"Authorization": token_pair.authorization_header()},
        )
        logger.info("PayIP get payment response status=%s payment_id=%s", response.status_code, normalized_payment_id)
        if response.status_code == 401:
            logger.warning("PayIP access token rejected on get payment; refreshing and retrying once")
            token_pair = self.tokens.refresh(self._client)
            response = self._client.get(
                f"{PAYMENTS_PATH}/{normalized_payment_id}",
                headers={"Authorization": token_pair.authorization_header()},
            )
            logger.info("PayIP get payment retry response status=%s", response.status_code)

        if not 200 <= response.status_code < 300:
            raise PayipError(
                f"PayIP get payment failed: HTTP {response.status_code}. "
                f"Response: {_safe_response_body(response)}"
            )
        return response.json()

    def invoice_report_pdf(
        self,
        *,
        company_id: str,
        payment_ids: list[str] | tuple[str, ...],
        filial: str = "",
    ) -> bytes:
        token_pair = self.tokens.ensure_access_token(self._client)
        resolved_company_id = self._resolve_company_id(filial=filial, company_id=company_id)
        normalized_payment_ids = [str(payment_id or "").strip() for payment_id in payment_ids]
        normalized_payment_ids = [payment_id for payment_id in normalized_payment_ids if payment_id]
        if not normalized_payment_ids:
            raise PayipError("PayIP payments vazio para gerar PDF")

        payload = {
            "companyId": resolved_company_id,
            "payments": normalized_payment_ids,
        }
        response = self._client.post(
            PAYMENT_INVOICE_REPORT_PATH,
            json=payload,
            headers={
                "Authorization": token_pair.authorization_header(),
                "Accept": "application/pdf",
            },
        )
        logger.info(
            "PayIP invoice report response status=%s company_id=%s payments=%s",
            response.status_code,
            resolved_company_id,
            len(normalized_payment_ids),
        )
        if response.status_code == 401:
            logger.warning("PayIP access token rejected on invoice report; refreshing and retrying once")
            token_pair = self.tokens.refresh(self._client)
            response = self._client.post(
                PAYMENT_INVOICE_REPORT_PATH,
                json=payload,
                headers={
                    "Authorization": token_pair.authorization_header(),
                    "Accept": "application/pdf",
                },
            )
            logger.info("PayIP invoice report retry response status=%s", response.status_code)

        if not 200 <= response.status_code < 300:
            raise PayipError(
                f"PayIP invoice report failed: HTTP {response.status_code}. "
                f"Response: {_safe_response_body(response)}"
            )
        if not response.content:
            raise PayipError("PayIP invoice report retornou PDF vazio")
        return response.content

    def statement_movements_resume(
        self,
        *,
        filial: str = "",
        company_id: str = "",
        date_start: str,
        date_end: str,
    ) -> dict[str, Any]:
        token_pair = self.tokens.ensure_access_token(self._client)
        resolved_company_id = self._resolve_company_id(filial=filial, company_id=company_id)
        response = self._get_statement_movements_resume(
            token_pair=token_pair,
            company_id=resolved_company_id,
            date_start=date_start,
            date_end=date_end,
        )
        logger.info(
            "PayIP statement movements resume response status=%s company_id=%s date=%s..%s",
            response.status_code,
            resolved_company_id,
            date_start,
            date_end,
        )
        if response.status_code == 401:
            logger.warning("PayIP access token rejected on statement resume; refreshing and retrying once")
            token_pair = self.tokens.refresh(self._client)
            response = self._get_statement_movements_resume(
                token_pair=token_pair,
                company_id=resolved_company_id,
                date_start=date_start,
                date_end=date_end,
            )
            logger.info("PayIP statement movements resume retry response status=%s", response.status_code)

        if not 200 <= response.status_code < 300:
            raise PayipError(
                f"PayIP statement resume failed: HTTP {response.status_code}. "
                f"Response: {_safe_response_body(response)}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise PayipError("PayIP statement resume retornou JSON invalido") from exc
        if not isinstance(data, dict):
            raise PayipError("PayIP statement resume retornou formato inesperado")
        return data

    def statement_movements_export(
        self,
        *,
        file_format: str,
        filial: str = "",
        company_id: str = "",
        date_start: str,
        date_end: str,
    ) -> bytes:
        normalized_format = str(file_format or "").strip().lower()
        if normalized_format not in {"pdf", "xlsx"}:
            raise PayipError("Formato de exportacao PayIP invalido")
        token_pair = self.tokens.ensure_access_token(self._client)
        resolved_company_id = self._resolve_company_id(filial=filial, company_id=company_id)
        response = self._get_statement_movements_export(
            token_pair=token_pair,
            company_id=resolved_company_id,
            file_format=normalized_format,
            date_start=date_start,
            date_end=date_end,
        )
        logger.info(
            "PayIP statement movements export response status=%s format=%s company_id=%s date=%s..%s",
            response.status_code,
            normalized_format,
            resolved_company_id,
            date_start,
            date_end,
        )
        if response.status_code == 401:
            logger.warning("PayIP access token rejected on statement export; refreshing and retrying once")
            token_pair = self.tokens.refresh(self._client)
            response = self._get_statement_movements_export(
                token_pair=token_pair,
                company_id=resolved_company_id,
                file_format=normalized_format,
                date_start=date_start,
                date_end=date_end,
            )
            logger.info("PayIP statement movements export retry response status=%s", response.status_code)

        if not 200 <= response.status_code < 300:
            raise PayipError(
                f"PayIP statement export {normalized_format} failed: HTTP {response.status_code}. "
                f"Response: {_safe_response_body(response)}"
            )
        if not response.content:
            raise PayipError(f"PayIP statement export {normalized_format} retornou arquivo vazio")
        return response.content

    def _get_payments(
        self,
        *,
        token_pair: TokenPair,
        page: int,
        page_size: int,
        company_id: str,
        status: str = "",
        client_code: str = "",
        invoice: str = "",
        search: str = "",
        due_date_start: str = "",
        due_date_end: str = "",
        created_at_start: str = "",
        created_at_end: str = "",
    ) -> httpx.Response:
        params = {
            "companyId": company_id,
            "page": page,
            "pageSize": page_size,
        }
        if status:
            params["status"] = status
        if client_code:
            params["clientCode"] = client_code
        if invoice:
            params["invoice"] = invoice
        if search:
            params["search"] = search
        if due_date_start:
            params["dueDateStart"] = due_date_start
        if due_date_end:
            params["dueDateEnd"] = due_date_end
        if created_at_start:
            params["createdAtStart"] = created_at_start
        if created_at_end:
            params["createdAtEnd"] = created_at_end

        return self._client.get(
            PAYMENTS_PATH,
            params=params,
            headers={"Authorization": token_pair.authorization_header()},
        )

    def _get_clients(
        self,
        *,
        token_pair: TokenPair,
        page: int,
        page_size: int,
        company_id: str,
        search: str = "",
        status: str = "",
        code: str = "",
        tax_payer_id: str = "",
    ) -> httpx.Response:
        params: dict[str, str | int] = {
            "companyId": company_id,
            "page": page,
            "pageSize": page_size,
        }
        if search:
            params["search"] = search
        if status:
            params["status"] = status
        if code:
            params["code"] = code
        normalized_tax_payer_id = _only_digits(tax_payer_id)
        if normalized_tax_payer_id:
            params["taxPayerId"] = normalized_tax_payer_id
        return self._client.get(
            CLIENTS_PATH,
            params=params,
            headers={"Authorization": token_pair.authorization_header()},
        )

    def _get_statement_movements_resume(
        self,
        *,
        token_pair: TokenPair,
        company_id: str,
        date_start: str,
        date_end: str,
    ) -> httpx.Response:
        return self._client.get(
            f"{STATEMENT_MOVEMENTS_RESUME_PATH}/{company_id}",
            params={
                "dateStart": date_start,
                "dateEnd": date_end,
            },
            headers={"Authorization": token_pair.authorization_header()},
        )

    def _get_statement_movements_export(
        self,
        *,
        token_pair: TokenPair,
        company_id: str,
        file_format: str,
        date_start: str,
        date_end: str,
    ) -> httpx.Response:
        accept = (
            "application/pdf"
            if file_format == "pdf"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        path = STATEMENT_MOVEMENTS_EXPORT_PDF_PATH if file_format == "pdf" else STATEMENT_MOVEMENTS_EXPORT_XLSX_PATH
        return self._client.get(
            f"{path}/{company_id}",
            params={
                "dateStart": date_start,
                "dateEnd": date_end,
            },
            headers={
                "Authorization": token_pair.authorization_header(),
                "Accept": accept,
            },
        )

    def _resolve_company_id(self, *, filial: str = "", company_id: str = "") -> str:
        explicit_company_id = str(company_id or "").strip()
        if explicit_company_id:
            return explicit_company_id

        company_map = self.config.company_map()
        normalized_filial = _normalize_filial_code(filial)
        if normalized_filial:
            mapped_company_id = company_map.get(normalized_filial)
            if mapped_company_id:
                return mapped_company_id
            raise PayipConfigError(f"PayIP companyId nao configurado para a filial {normalized_filial}")

        if self.config.company_id:
            return self.config.company_id
        if len(company_map) == 1:
            return next(iter(company_map.values()))
        raise PayipConfigError("Informe a filial da PayIP para resolver o companyId")

    def _resolve_company_tax_id(self, *, filial: str, company_tax_id: str = "") -> str:
        explicit_company_tax_id = _only_digits(company_tax_id)
        if explicit_company_tax_id:
            return explicit_company_tax_id

        normalized_filial = _normalize_filial_code(filial)
        company_tax_map = self.config.company_tax_map()
        if normalized_filial:
            mapped_company_tax_id = company_tax_map.get(normalized_filial)
            if mapped_company_tax_id:
                return mapped_company_tax_id
            raise PayipConfigError(f"PayIP companyTaxId nao configurado para a filial {normalized_filial}")
        if len(company_tax_map) == 1:
            return next(iter(company_tax_map.values()))
        raise PayipConfigError("Informe a filial da PayIP para resolver o companyTaxId")


def summarize_collection_response(data: Any) -> dict[str, int | None]:
    items = _extract_items(data)
    if isinstance(data, dict):
        total_items = _first_int(data, "total", "totalItems", "total_items", "totalElements", "count")
        page = _first_int(data, "page", "pageNumber", "currentPage")
        page_size = _first_int(data, "pageSize", "page_size", "size", "limit", "perPage")
    else:
        total_items = None
        page = None
        page_size = None

    return {
        "items_count": len(items) if items is not None else None,
        "total_items": total_items,
        "page": page,
        "page_size": page_size,
    }


def _extract_items(data: Any) -> list[Any] | None:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    for key in ("items", "data", "content", "results", "payments"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _first_int(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        parsed = _optional_int(value)
        if parsed is not None:
            return parsed
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _normalize_filial_code(value: Any) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _only_digits(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _mask_document(value: Any) -> str:
    digits = _only_digits(value)
    if not digits:
        return "-"
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"{digits[:3]}***{digits[-2:]}"


def _token_expires_at(*, token: str, expires_in: int) -> float:
    jwt_expires_at = _jwt_expires_at(token)
    if jwt_expires_at is not None:
        return min(jwt_expires_at, time.time() + float(expires_in))
    return time.time() + float(expires_in)


def _jwt_expires_at(token: str) -> float | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}")
        data = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    exp = data.get("exp")
    if isinstance(exp, bool):
        return None
    if isinstance(exp, (int, float)):
        return float(exp)
    return None


def _safe_response_body(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return "<empty>"
    try:
        payload = response.json()
    except ValueError:
        return text[:1_000]
    return json.dumps(_redact_sensitive(payload), ensure_ascii=False)[:1_000]


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in {"access_token", "refresh_token", "password", "code", "totp", "otp"}:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value
