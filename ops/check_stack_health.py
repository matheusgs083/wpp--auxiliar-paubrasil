from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_ALERT_STATE_FILE = PROJECT_ROOT / "exports" / "monitoring" / "stack_alert_state.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida a saude operacional da stack: containers, health endpoints e espaco livre."
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Arquivo .env a ser lido.")
    parser.add_argument("--preview-alert", action="store_true", help="Mostra a mensagem do alerta sem enviar.")
    parser.add_argument("--simulate-failure", default="", help="Adiciona uma falha simulada para testar o alerta.")
    args = parser.parse_args()

    env = load_env_file(Path(args.env_file))
    app_port = int(env.get("APP_PORT", "8080"))
    webhook_port = int(env.get("PUBLIC_WEBHOOK_PORT", "8090"))
    min_free_gb = float(env.get("STACK_MONITOR_MIN_FREE_GB", "5"))

    docker_status = get_container_status()
    app_health = fetch_json(f"http://127.0.0.1:{app_port}/health")
    gateway_health = fetch_text(f"http://127.0.0.1:{webhook_port}/health")
    disk = shutil.disk_usage(PROJECT_ROOT)
    free_gb = disk.free / (1024 ** 3)

    failures: list[str] = []
    unhealthy = [name for name, status in docker_status.items() if "unhealthy" in status.lower() or "exited" in status.lower()]
    if unhealthy:
        failures.append(f"Containers com problema: {', '.join(unhealthy)}")
    if app_health.get("ok") is not True:
        failures.append("Health privado do bot_api nao retornou ok=true.")
    if '"ok":true' not in gateway_health.replace(" ", "").lower() and "ok" not in gateway_health.lower():
        failures.append("Health do gateway nao retornou resposta esperada.")
    if free_gb < min_free_gb:
        failures.append(f"Espaco livre baixo: {free_gb:.2f} GB.")
    if args.simulate_failure.strip():
        failures.append(args.simulate_failure.strip())

    payload = {
        "ok": not failures,
        "containers": docker_status,
        "app_health": app_health,
        "gateway_health": gateway_health.strip(),
        "disk_free_gb": round(free_gb, 2),
        "min_free_gb": min_free_gb,
        "failures": failures,
    }
    payload["alert"] = handle_alerts(payload=payload, env=env, preview_only=args.preview_alert)
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if not failures else 1


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = strip_wrapping_quotes(value.strip())
    return env


def strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_csv_tokens(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def get_container_status() -> dict[str, str]:
    completed = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}|{{.Status}}"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Falha ao consultar containers: {completed.stderr.strip()}")
    status: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "|" not in line:
            continue
        name, raw_status = line.split("|", 1)
        status[name.strip()] = raw_status.strip()
    return status


def fetch_json(url: str) -> dict[str, object]:
    raw = fetch_text(url)
    return json.loads(raw)


def fetch_text(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Falha ao consultar {url}: {exc}") from exc


def handle_alerts(*, payload: dict[str, Any], env: dict[str, str], preview_only: bool) -> dict[str, Any]:
    numbers = parse_csv_tokens(env.get("STACK_ALERT_NUMBERS", ""))
    cooldown_minutes = max(1, int(env.get("STACK_ALERT_COOLDOWN_MINUTES", "30")))
    state_file = Path(env.get("STACK_ALERT_STATE_FILE", "") or DEFAULT_ALERT_STATE_FILE)
    status = "failed" if payload.get("failures") else "ok"
    previous_state = load_alert_state(state_file)
    previous_status = str(previous_state.get("status", "unknown"))
    previous_signature = str(previous_state.get("failure_signature", ""))
    current_signature = build_failure_signature(payload.get("failures", []))
    now = datetime.now(timezone.utc)

    message_text = build_alert_message(payload=payload, previous_status=previous_status)
    should_send = False
    reason = "not_needed"

    if not numbers:
        reason = "not_configured"
    elif status == "failed":
        last_sent_at = parse_state_datetime(previous_state.get("last_sent_at"))
        cooldown_elapsed = last_sent_at is None or now - last_sent_at >= timedelta(minutes=cooldown_minutes)
        if previous_status != "failed":
            should_send = True
            reason = "first_failure"
        elif previous_signature != current_signature:
            should_send = True
            reason = "failure_changed"
        elif cooldown_elapsed:
            should_send = True
            reason = "cooldown_elapsed"
        else:
            reason = "cooldown_active"
    elif previous_status == "failed":
        should_send = True
        reason = "recovered"

    if preview_only:
        return {
            "configured": bool(numbers),
            "preview_only": True,
            "would_send": should_send,
            "reason": reason,
            "numbers": numbers,
            "message": message_text,
        }

    if should_send and numbers:
        send_alert_via_evolution(
            numbers=numbers,
            message_text=message_text,
            evolution_base_url=env.get("EVOLUTION_BASE_URL", "").strip(),
            evolution_api_key=env.get("EVOLUTION_API_KEY", "").strip(),
            evolution_instance=env.get("EVOLUTION_INSTANCE", "").strip(),
            evolution_send_path=env.get("EVOLUTION_SEND_PATH", "/message/sendText/{instance}").strip() or "/message/sendText/{instance}",
            timeout_seconds=float(env.get("EVOLUTION_TIMEOUT_SECONDS", "20")),
        )
        save_alert_state(
            state_file,
            {
                "status": status,
                "failure_signature": current_signature,
                "last_sent_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        return {
            "configured": True,
            "preview_only": False,
            "sent": True,
            "reason": reason,
            "numbers": numbers,
        }

    save_alert_state(
        state_file,
        {
            "status": status,
            "failure_signature": current_signature,
            "last_sent_at": str(previous_state.get("last_sent_at", "")),
            "updated_at": now.isoformat(),
        },
    )
    return {
        "configured": bool(numbers),
        "preview_only": False,
        "sent": False,
        "reason": reason,
        "numbers": numbers,
    }


def load_alert_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_alert_state(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def parse_state_datetime(raw: object) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def build_failure_signature(failures: list[str]) -> str:
    return " | ".join(str(item).strip() for item in failures if str(item).strip())


def build_alert_message(*, payload: dict[str, Any], previous_status: str) -> str:
    status = "FALHA" if payload.get("failures") else "RECUPERADO"
    lines = [f"Alerta do bot_api: {status}"]
    if status == "RECUPERADO":
        lines.append("O healthcheck voltou ao normal.")
    else:
        lines.append("Falhas detectadas:")
        for failure in payload.get("failures", []):
            lines.append(f"- {failure}")
    lines.append("")
    lines.append(f"bot_api ok={payload.get('app_health', {}).get('ok')}")
    lines.append(f"gateway: {payload.get('gateway_health', '')}")
    lines.append(f"espaco livre: {payload.get('disk_free_gb')} GB")
    if previous_status and previous_status not in {"", "unknown"}:
        lines.append(f"status anterior: {previous_status}")
    lines.append(f"horario: {datetime.now(timezone.utc).astimezone().strftime('%d/%m/%Y %H:%M:%S')}")
    return "\n".join(lines)


def send_alert_via_evolution(
    *,
    numbers: list[str],
    message_text: str,
    evolution_base_url: str,
    evolution_api_key: str,
    evolution_instance: str,
    evolution_send_path: str,
    timeout_seconds: float,
) -> None:
    if not evolution_base_url or not evolution_instance:
        raise RuntimeError("Evolution nao configurada para envio de alerta.")
    url = f"{evolution_base_url.rstrip('/')}{evolution_send_path.format(instance=evolution_instance)}"
    headers = {"Content-Type": "application/json"}
    if evolution_api_key:
        headers["apikey"] = evolution_api_key

    for number in numbers:
        payload_variants = [
            {"number": number, "textMessage": {"text": message_text}},
            {"number": number, "text": message_text},
        ]
        last_error = ""
        for candidate in payload_variants:
            request = urllib.request.Request(
                url,
                data=json.dumps(candidate, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    if 200 <= response.status < 300:
                        last_error = ""
                        break
                    last_error = str(response.status)
            except urllib.error.HTTPError as exc:
                last_error = f"{exc.code} {exc.read().decode('utf-8', errors='replace')}"
            except urllib.error.URLError as exc:
                last_error = str(exc)
        if last_error:
            raise RuntimeError(f"Falha ao enviar alerta via Evolution para {number}: {last_error}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True, indent=2), file=sys.stderr)
        raise
