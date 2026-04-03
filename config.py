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
    evolution_instance: str
    evolution_send_path: str
    evolution_list_path: str
    evolution_buttons_path: str
    evolution_timeout_seconds: float
    meta_cloud_enabled: bool
    meta_cloud_api_version: str
    meta_cloud_phone_number_id: str
    meta_cloud_access_token: str
    meta_cloud_verify_token: str
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
    reports_database_url: str
    reports_runtime_database_url: str
    reports_db_schema: str


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
        evolution_instance=os.getenv("EVOLUTION_INSTANCE", ""),
        evolution_send_path=os.getenv("EVOLUTION_SEND_PATH", "/message/sendText/{instance}"),
        evolution_list_path=os.getenv("EVOLUTION_LIST_PATH", "/message/sendList/{instance}"),
        evolution_buttons_path=os.getenv("EVOLUTION_BUTTONS_PATH", "/message/sendButtons/{instance}"),
        evolution_timeout_seconds=float(os.getenv("EVOLUTION_TIMEOUT_SECONDS", "20")),
        meta_cloud_enabled=_parse_bool(os.getenv("META_CLOUD_ENABLED", "0"), default=False),
        meta_cloud_api_version=os.getenv("META_CLOUD_API_VERSION", "v23.0").strip() or "v23.0",
        meta_cloud_phone_number_id=os.getenv("META_CLOUD_PHONE_NUMBER_ID", "").strip(),
        meta_cloud_access_token=os.getenv("META_CLOUD_ACCESS_TOKEN", "").strip(),
        meta_cloud_verify_token=os.getenv("META_CLOUD_VERIFY_TOKEN", "").strip(),
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
        reports_database_url=(os.getenv("REPORTS_DATABASE_URL", "").strip() or os.getenv("ACCESS_DATABASE_URL", "").strip()),
        reports_runtime_database_url=(
            os.getenv("REPORTS_RUNTIME_DATABASE_URL", "").strip()
            or os.getenv("REPORTS_DATABASE_URL", "").strip()
            or os.getenv("ACCESS_DATABASE_URL", "").strip()
        ),
        reports_db_schema=os.getenv("REPORTS_DB_SCHEMA", "reports").strip() or "reports",
    )
