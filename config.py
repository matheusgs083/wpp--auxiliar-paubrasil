from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
_DOTENV_LOADED = False


@dataclass(frozen=True)
class Settings:
    app_host: str
    app_port: int
    webhook_worker_threads: int
    api_auth_enabled: bool
    api_auth_tokens: tuple[str, ...]
    api_require_admin_for_number: bool
    evolution_base_url: str
    evolution_api_key: str
    evolution_webhook_api_keys: tuple[str, ...]
    evolution_webhook_allow_api_key_fallback: bool
    evolution_instance: str
    evolution_send_path: str
    evolution_list_path: str
    evolution_buttons_path: str
    evolution_media_path: str
    evolution_timeout_seconds: float
    meta_cloud_enabled: bool
    meta_cloud_api_version: str
    meta_cloud_phone_number_id: str
    meta_cloud_access_token: str
    meta_cloud_verify_token: str
    meta_cloud_app_secret: str
    verify_token: str
    access_control_enabled: bool
    access_database_url: str
    access_db_schema: str
    access_public_enabled: bool
    access_database_timeout_seconds: float
    security_audit_enabled: bool
    denied_reply_cooldown_minutes: int
    denied_unregistered_reply_cooldown_minutes: int
    admin_api_token: str
    finance_panel_tokens: tuple[tuple[str, tuple[str, ...]], ...]
    critica_panel_tokens: tuple[tuple[str, tuple[str, ...]], ...]
    admin_upload_max_file_size_mb: int
    admin_upload_max_file_count: int
    reports_database_url: str
    reports_runtime_database_url: str
    reports_db_schema: str
    payip_base_url: str
    payip_client_id: str
    payip_username: str
    payip_password: str
    payip_company_id: str
    payip_company_ids: tuple[tuple[str, str], ...]
    payip_company_tax_ids: tuple[tuple[str, str], ...]
    payip_token_cache_file: str
    payip_timeout_seconds: float
    payip_mfa_code: str
    daily_route_broadcast_enabled: bool
    daily_route_broadcast_time: str
    daily_route_broadcast_timezone: str
    daily_route_broadcast_check_interval_seconds: int
    daily_route_broadcast_initial_delay_seconds: int
    daily_route_broadcast_audiences: tuple[str, ...]
    daily_route_broadcast_state_file: str


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_dotenv() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return

    env_file_raw = os.getenv("BOT_ENV_FILE", ".env").strip()
    env_file = Path(env_file_raw)
    if not env_file.is_absolute():
        env_file = (PROJECT_ROOT / env_file).resolve()
    if not env_file.exists():
        _DOTENV_LOADED = True
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = _strip_wrapping_quotes(value.strip())
        os.environ.setdefault(key, value)
    _DOTENV_LOADED = True


def _parse_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _parse_csv_tokens(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    tokens = [item.strip() for item in value.split(",")]
    return tuple(item for item in tokens if item)


def _parse_key_value_pairs(value: str | None) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    pairs: list[tuple[str, str]] = []
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        separator = ":" if ":" in token else "=" if "=" in token else ""
        if not separator:
            continue
        key, pair_value = token.split(separator, 1)
        key = key.strip()
        pair_value = pair_value.strip()
        if key and pair_value:
            pairs.append((key, pair_value))
    return tuple(pairs)


def _parse_scoped_panel_tokens(
    value: str | None,
    *,
    allow_all_scope: bool = False,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if value is None:
        return ()
    mappings: list[tuple[str, tuple[str, ...]]] = []
    for item in value.split(","):
        token = item.strip()
        if not token:
            continue
        separator = ":" if ":" in token else "=" if "=" in token else ""
        if not separator:
            continue
        raw_token, raw_filiais = token.split(separator, 1)
        panel_token = raw_token.strip()
        filial_codes = []
        seen: set[str] = set()
        for raw_code in raw_filiais.replace(";", "|").split("|"):
            raw_text = str(raw_code or "").strip().lower()
            if allow_all_scope and raw_text in {"*", "all", "todos", "todas"}:
                filial_codes = ["*"]
                seen = {"*"}
                break
            digits = "".join(char for char in str(raw_code or "") if char.isdigit())
            normalized = digits.lstrip("0") or ("0" if digits else "")
            if normalized and normalized not in seen:
                seen.add(normalized)
                filial_codes.append(normalized)
        if panel_token and filial_codes:
            mappings.append((panel_token, tuple(filial_codes)))
    return tuple(mappings)


def _parse_finance_panel_tokens(value: str | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _parse_scoped_panel_tokens(value, allow_all_scope=False)


def _parse_critica_panel_tokens(value: str | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _parse_scoped_panel_tokens(value, allow_all_scope=True)


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=int(os.getenv("APP_PORT", "8080")),
        webhook_worker_threads=max(1, int(os.getenv("WEBHOOK_WORKER_THREADS", "4"))),
        api_auth_enabled=_parse_bool(os.getenv("API_AUTH_ENABLED", "1"), default=True),
        api_auth_tokens=_parse_csv_tokens(os.getenv("API_AUTH_TOKENS", "")),
        api_require_admin_for_number=_parse_bool(os.getenv("API_REQUIRE_ADMIN_FOR_NUMBER", "1"), default=True),
        evolution_base_url=os.getenv("EVOLUTION_BASE_URL", "").rstrip("/"),
        evolution_api_key=os.getenv("EVOLUTION_API_KEY", ""),
        evolution_webhook_api_keys=_parse_csv_tokens(os.getenv("EVOLUTION_WEBHOOK_API_KEYS", "")),
        evolution_webhook_allow_api_key_fallback=_parse_bool(
            os.getenv("EVOLUTION_WEBHOOK_ALLOW_API_KEY_FALLBACK", "0"),
            default=False,
        ),
        evolution_instance=os.getenv("EVOLUTION_INSTANCE", ""),
        evolution_send_path=os.getenv("EVOLUTION_SEND_PATH", "/message/sendText/{instance}"),
        evolution_list_path=os.getenv("EVOLUTION_LIST_PATH", "/message/sendList/{instance}"),
        evolution_buttons_path=os.getenv("EVOLUTION_BUTTONS_PATH", "/message/sendButtons/{instance}"),
        evolution_media_path=os.getenv("EVOLUTION_MEDIA_PATH", "/message/sendMedia/{instance}"),
        evolution_timeout_seconds=float(os.getenv("EVOLUTION_TIMEOUT_SECONDS", "20")),
        meta_cloud_enabled=_parse_bool(os.getenv("META_CLOUD_ENABLED", "0"), default=False),
        meta_cloud_api_version=os.getenv("META_CLOUD_API_VERSION", "v23.0").strip() or "v23.0",
        meta_cloud_phone_number_id=os.getenv("META_CLOUD_PHONE_NUMBER_ID", "").strip(),
        meta_cloud_access_token=os.getenv("META_CLOUD_ACCESS_TOKEN", "").strip(),
        meta_cloud_verify_token=os.getenv("META_CLOUD_VERIFY_TOKEN", "").strip(),
        meta_cloud_app_secret=os.getenv("META_CLOUD_APP_SECRET", "").strip(),
        verify_token=os.getenv("BOT_VERIFY_TOKEN", ""),
        access_control_enabled=_parse_bool(os.getenv("ACCESS_CONTROL_ENABLED", "1"), default=True),
        access_database_url=os.getenv("ACCESS_DATABASE_URL", "").strip(),
        access_db_schema=os.getenv("ACCESS_DB_SCHEMA", "bot_access").strip() or "bot_access",
        access_public_enabled=_parse_bool(os.getenv("ACCESS_PUBLIC_ENABLED", "0"), default=False),
        access_database_timeout_seconds=float(os.getenv("ACCESS_DATABASE_TIMEOUT_SECONDS", "3")),
        security_audit_enabled=_parse_bool(os.getenv("SECURITY_AUDIT_ENABLED", "1"), default=True),
        denied_reply_cooldown_minutes=max(1, int(os.getenv("DENIED_REPLY_COOLDOWN_MINUTES", "360"))),
        denied_unregistered_reply_cooldown_minutes=max(
            1,
            int(os.getenv("DENIED_UNREGISTERED_REPLY_COOLDOWN_MINUTES", "720")),
        ),
        admin_api_token=os.getenv("ADMIN_API_TOKEN", "").strip(),
        finance_panel_tokens=_parse_finance_panel_tokens(os.getenv("FINANCE_PANEL_TOKENS", "")),
        critica_panel_tokens=_parse_critica_panel_tokens(os.getenv("CRITICA_PANEL_TOKENS", "")),
        admin_upload_max_file_size_mb=max(0, int(os.getenv("ADMIN_UPLOAD_MAX_FILE_SIZE_MB", "0"))),
        admin_upload_max_file_count=max(1, int(os.getenv("ADMIN_UPLOAD_MAX_FILE_COUNT", "20"))),
        reports_database_url=(os.getenv("REPORTS_DATABASE_URL", "").strip() or os.getenv("ACCESS_DATABASE_URL", "").strip()),
        reports_runtime_database_url=(
            os.getenv("REPORTS_RUNTIME_DATABASE_URL", "").strip()
            or os.getenv("REPORTS_DATABASE_URL", "").strip()
            or os.getenv("ACCESS_DATABASE_URL", "").strip()
        ),
        reports_db_schema=os.getenv("REPORTS_DB_SCHEMA", "reports").strip() or "reports",
        payip_base_url=(
            os.getenv("PAYIP_BASE_URL", "").strip()
            or os.getenv("PAYMENTS_API_BASE_URL", "").strip()
        ).rstrip("/"),
        payip_client_id=(
            os.getenv("PAYIP_CLIENT_ID", "").strip()
            or os.getenv("PAYMENTS_API_CLIENT_ID", "payip-auth-portal").strip()
            or "payip-auth-portal"
        ),
        payip_username=(
            os.getenv("PAYIP_USERNAME", "").strip()
            or os.getenv("PAYMENTS_API_USERNAME", "").strip()
            or os.getenv("email", "").strip()
        ),
        payip_password=(
            os.getenv("PAYIP_PASSWORD", "").strip()
            or os.getenv("PAYMENTS_API_PASSWORD", "").strip()
            or os.getenv("senha", "").strip()
        ),
        payip_company_id=(
            os.getenv("PAYIP_COMPANY_ID", "").strip()
            or os.getenv("PAYMENTS_API_COMPANY_ID", "").strip()
        ),
        payip_company_ids=_parse_key_value_pairs(
            os.getenv("PAYIP_COMPANY_IDS", "").strip()
            or os.getenv("PAYMENTS_API_COMPANY_IDS", "").strip()
        ),
        payip_company_tax_ids=_parse_key_value_pairs(
            os.getenv("PAYIP_COMPANY_TAX_IDS", "").strip()
            or os.getenv("PAYMENTS_API_COMPANY_TAX_IDS", "").strip()
        ),
        payip_token_cache_file=(
            os.getenv("PAYIP_TOKEN_CACHE_FILE", "").strip()
            or str(PROJECT_ROOT / "exports" / "payip" / "tokens.json")
        ),
        payip_timeout_seconds=float(os.getenv("PAYIP_TIMEOUT_SECONDS", "30")),
        payip_mfa_code=(
            os.getenv("PAYIP_MFA_CODE", "").strip()
            or os.getenv("PAYMENTS_API_TOTP", "").strip()
        ),
        daily_route_broadcast_enabled=_parse_bool(os.getenv("DAILY_ROUTE_BROADCAST_ENABLED", "0"), default=False),
        daily_route_broadcast_time=os.getenv("DAILY_ROUTE_BROADCAST_TIME", "07:00").strip() or "07:00",
        daily_route_broadcast_timezone=(
            os.getenv("DAILY_ROUTE_BROADCAST_TIMEZONE", "America/Fortaleza").strip()
            or "America/Fortaleza"
        ),
        daily_route_broadcast_check_interval_seconds=max(
            60,
            int(os.getenv("DAILY_ROUTE_BROADCAST_CHECK_INTERVAL_SECONDS", "300")),
        ),
        daily_route_broadcast_initial_delay_seconds=max(
            0,
            int(os.getenv("DAILY_ROUTE_BROADCAST_INITIAL_DELAY_SECONDS", "20")),
        ),
        daily_route_broadcast_audiences=_parse_csv_tokens(os.getenv("DAILY_ROUTE_BROADCAST_AUDIENCES", "vendedor")),
        daily_route_broadcast_state_file=(
            os.getenv("DAILY_ROUTE_BROADCAST_STATE_FILE", "").strip()
            or str(PROJECT_ROOT / "exports" / "scheduled_messages" / "daily_route_state.json")
        ),
    )
