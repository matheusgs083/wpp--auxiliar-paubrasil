from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_INSTANCE_EVENTS = (
    "MESSAGES_UPSERT",
    "MESSAGES_UPDATE",
    "SEND_MESSAGE",
    "CONNECTION_UPDATE",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CloudApiHomologationConfig:
    evolution_base_url: str
    evolution_api_key: str
    evolution_server_url: str
    wa_business_token_webhook: str
    instance_name: str
    number_id: str
    business_id: str
    permanent_token: str
    instance_webhook_url: str
    timeout_seconds: float

    @property
    def meta_webhook_url(self) -> str:
        if not self.evolution_server_url:
            return ""
        return f"{self.evolution_server_url.rstrip('/')}/webhook/meta"


def _mask_secret(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if len(cleaned) <= 8:
        return "*" * len(cleaned)
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def _load_config() -> CloudApiHomologationConfig:
    env = _load_env_file(_resolve_env_file())
    return CloudApiHomologationConfig(
        evolution_base_url=_env_value(env, "EVOLUTION_BASE_URL").rstrip("/"),
        evolution_api_key=_env_value(env, "EVOLUTION_API_KEY").strip(),
        evolution_server_url=_env_value(env, "EVOLUTION_SERVER_URL").strip(),
        wa_business_token_webhook=_env_value(env, "EVOLUTION_WA_BUSINESS_TOKEN_WEBHOOK").strip(),
        instance_name=_env_value(env, "EVOLUTION_CLOUDAPI_HML_INSTANCE").strip(),
        number_id=_env_value(env, "EVOLUTION_CLOUDAPI_NUMBER_ID").strip(),
        business_id=_env_value(env, "EVOLUTION_CLOUDAPI_BUSINESS_ID").strip(),
        permanent_token=_env_value(env, "EVOLUTION_CLOUDAPI_PERMANENT_TOKEN").strip(),
        instance_webhook_url=_env_value(env, "EVOLUTION_CLOUDAPI_INSTANCE_WEBHOOK_URL").strip(),
        timeout_seconds=float(_env_value(env, "EVOLUTION_TIMEOUT_SECONDS", "20")),
    )


def _resolve_env_file() -> Path:
    env_file_raw = os.getenv("BOT_ENV_FILE", ".env").strip() or ".env"
    env_file = Path(env_file_raw)
    if not env_file.is_absolute():
        env_file = (PROJECT_ROOT / env_file).resolve()
    return env_file


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def _env_value(env: dict[str, str], key: str, default: str = "") -> str:
    return str(os.getenv(key, env.get(key, default)))


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["apikey"] = api_key
    return headers


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_text(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        safe = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        sys.stdout.buffer.write(safe.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")


def _check_requirements(config: CloudApiHomologationConfig) -> int:
    checks = [
        ("EVOLUTION_BASE_URL", bool(config.evolution_base_url), config.evolution_base_url),
        ("EVOLUTION_API_KEY", bool(config.evolution_api_key), _mask_secret(config.evolution_api_key)),
        ("EVOLUTION_SERVER_URL", bool(config.evolution_server_url), config.evolution_server_url),
        (
            "EVOLUTION_WA_BUSINESS_TOKEN_WEBHOOK",
            bool(config.wa_business_token_webhook),
            _mask_secret(config.wa_business_token_webhook),
        ),
        ("EVOLUTION_CLOUDAPI_HML_INSTANCE", bool(config.instance_name), config.instance_name),
        ("EVOLUTION_CLOUDAPI_NUMBER_ID", bool(config.number_id), config.number_id),
        ("EVOLUTION_CLOUDAPI_BUSINESS_ID", bool(config.business_id), config.business_id),
        ("EVOLUTION_CLOUDAPI_PERMANENT_TOKEN", bool(config.permanent_token), _mask_secret(config.permanent_token)),
        (
            "EVOLUTION_CLOUDAPI_INSTANCE_WEBHOOK_URL",
            bool(config.instance_webhook_url),
            config.instance_webhook_url,
        ),
    ]

    print("Checklist da homologacao Cloud API")
    print()
    for key, ok, display in checks:
        status = "ok" if ok else "pendente"
        suffix = f" -> {display}" if display else ""
        print(f"- {key}: {status}{suffix}")

    print()
    print("URLs derivadas")
    print(f"- Webhook Meta: {config.meta_webhook_url or 'pendente'}")
    print(f"- Webhook da instancia para o bot: {config.instance_webhook_url or 'pendente'}")
    print()
    print("Observacoes")
    print("- Configure a Meta para validar o webhook da Evolution em /webhook/meta.")
    print("- Mantenha a instancia Cloud API em homologacao separada da produtiva.")
    print("- Homologue o formato de autenticacao do webhook da Evolution antes do cutover.")

    missing = [key for key, ok, _ in checks if not ok]
    if missing:
        print()
        print("Pendencias encontradas:")
        for key in missing:
            print(f"- {key}")
        return 1
    return 0


def _build_create_payload(config: CloudApiHomologationConfig) -> dict[str, Any]:
    return {
        "instanceName": config.instance_name,
        "number": config.number_id,
        "businessId": config.business_id,
        "qrcode": False,
        "integration": "WHATSAPP-BUSINESS",
        "token": config.permanent_token,
    }


def _build_webhook_payload(config: CloudApiHomologationConfig) -> dict[str, Any]:
    return {
        "webhook": {
            "enabled": True,
            "url": config.instance_webhook_url,
            "events": list(DEFAULT_INSTANCE_EVENTS),
            "webhookByEvents": False,
            "webhookBase64": False,
        }
    }


def _post_json(
    *,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[int, str]:
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(url, headers=_headers(api_key), content=json.dumps(payload, ensure_ascii=False))
    return response.status_code, response.text


def _command_check(_args: argparse.Namespace) -> int:
    return _check_requirements(_load_config())


def _command_create_instance(args: argparse.Namespace) -> int:
    config = _load_config()
    required = {
        "EVOLUTION_BASE_URL": config.evolution_base_url,
        "EVOLUTION_API_KEY": config.evolution_api_key,
        "EVOLUTION_CLOUDAPI_HML_INSTANCE": config.instance_name,
        "EVOLUTION_CLOUDAPI_NUMBER_ID": config.number_id,
        "EVOLUTION_CLOUDAPI_BUSINESS_ID": config.business_id,
        "EVOLUTION_CLOUDAPI_PERMANENT_TOKEN": config.permanent_token,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        _check_requirements(config)
        return 1

    url = f"{config.evolution_base_url}/instance/create"
    payload = _build_create_payload(config)
    display_payload = dict(payload)
    display_payload["token"] = _mask_secret(config.permanent_token)

    print("Criacao da instancia Cloud API")
    print(f"- URL: {url}")
    print("- Payload:")
    _print_json(display_payload)

    if args.dry_run:
        return 0

    status_code, response_text = _post_json(
        url=url,
        api_key=config.evolution_api_key,
        payload=payload,
        timeout_seconds=config.timeout_seconds,
    )
    print()
    print(f"Resposta: {status_code}")
    _print_text(response_text)
    return 0 if 200 <= status_code < 300 else 1


def _command_set_instance_webhook(args: argparse.Namespace) -> int:
    config = _load_config()
    required = {
        "EVOLUTION_BASE_URL": config.evolution_base_url,
        "EVOLUTION_API_KEY": config.evolution_api_key,
        "EVOLUTION_CLOUDAPI_HML_INSTANCE": config.instance_name,
        "EVOLUTION_CLOUDAPI_INSTANCE_WEBHOOK_URL": config.instance_webhook_url,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        _check_requirements(config)
        return 1

    url = f"{config.evolution_base_url}/webhook/set/{config.instance_name}"
    payload = _build_webhook_payload(config)

    print("Configuracao do webhook da instancia")
    print(f"- URL: {url}")
    print("- Payload:")
    _print_json(payload)

    if args.dry_run:
        return 0

    status_code, response_text = _post_json(
        url=url,
        api_key=config.evolution_api_key,
        payload=payload,
        timeout_seconds=config.timeout_seconds,
    )
    print()
    print(f"Resposta: {status_code}")
    _print_text(response_text)
    return 0 if 200 <= status_code < 300 else 1


def _command_meta_webhook(_args: argparse.Namespace) -> int:
    config = _load_config()
    print("Webhook da Meta para configurar na Evolution")
    print(f"- URL: {config.meta_webhook_url or 'pendente'}")
    print(f"- Verify token: {_mask_secret(config.wa_business_token_webhook)}")
    print()
    print("Esse endpoint precisa ficar publico com HTTPS e chegar na Evolution.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ferramenta operacional para homologar Cloud API da Meta via Evolution.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Valida configuracao minima da homologacao.")
    check_parser.set_defaults(func=_command_check)

    create_parser = subparsers.add_parser(
        "create-instance",
        help="Cria a instancia WHATSAPP-BUSINESS na Evolution.",
    )
    create_parser.add_argument("--dry-run", action="store_true", help="Mostra a chamada sem enviar.")
    create_parser.set_defaults(func=_command_create_instance)

    webhook_parser = subparsers.add_parser(
        "set-instance-webhook",
        help="Configura o webhook da instancia para apontar para o bot.",
    )
    webhook_parser.add_argument("--dry-run", action="store_true", help="Mostra a chamada sem enviar.")
    webhook_parser.set_defaults(func=_command_set_instance_webhook)

    meta_parser = subparsers.add_parser(
        "show-meta-webhook",
        help="Mostra a URL e o token que devem ser configurados na Meta.",
    )
    meta_parser.set_defaults(func=_command_meta_webhook)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
