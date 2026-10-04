from __future__ import annotations

import json
import urllib.request

from bot_api.config import get_settings


def main() -> None:
    settings = get_settings()
    base = f"http://127.0.0.1:{settings.app_port}/api/admin/liga-entrega/dashboard"
    for period in ("atual", "fechado"):
        request = urllib.request.Request(
            f"{base}?period={period}",
            headers={"X-Admin-Token": settings.admin_api_token},
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            payload = json.loads(response.read().decode("utf-8"))
        summary = payload.get("summary") or {}
        print(json.dumps({"period": period, "competencia": payload.get("competencia"), "rotas": summary.get("rotas"), "devolucoes": summary.get("devolucoes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
