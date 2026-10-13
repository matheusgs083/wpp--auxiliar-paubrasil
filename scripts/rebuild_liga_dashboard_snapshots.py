from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import re
import urllib.request

from bot_api.config import get_settings


def main() -> None:
    settings = get_settings()
    base = f"http://127.0.0.1:{settings.app_port}/api/admin/liga-entrega/dashboard"
    competencias: set[str] = set()
    reports_root = Path(__file__).resolve().parents[1] / "exports" / "liga_entrega_reports"
    if reports_root.is_dir():
        for path in reports_root.rglob("manifest.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            metadata = payload.get("metadata") or {}
            for value in (metadata.get("competencia"), metadata.get("operational_competencia"), payload.get("reference_date")):
                match = re.search(r"(\d{4}-\d{2})", str(value or ""))
                if match:
                    competencias.add(match.group(1))
    if not competencias:
        today = date.today()
        competencias.add(f"{today.year:04d}-{today.month:02d}")
    for competencia in sorted(competencias):
        period = "atual"
        request = urllib.request.Request(
            f"{base}?period={period}&competencia={competencia}&bootstrap=1",
            headers={"X-Admin-Token": settings.admin_api_token},
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            payload = json.loads(response.read().decode("utf-8"))
        summary = payload.get("summary") or {}
        print(json.dumps({"period": period, "competencia": payload.get("competencia"), "rotas": summary.get("rotas"), "devolucoes": summary.get("devolucoes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
