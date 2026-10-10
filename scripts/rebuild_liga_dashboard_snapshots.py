from __future__ import annotations

import json
from datetime import date
import urllib.request

from bot_api.config import get_settings


def main() -> None:
    settings = get_settings()
    base = f"http://127.0.0.1:{settings.app_port}/api/admin/liga-entrega/dashboard"
    today = date.today()
    atual = f"{today.year:04d}-{today.month:02d}"
    fechamento_date = date(today.year, today.month, 1)
    if fechamento_date.month == 1:
        fechamento = f"{fechamento_date.year - 1:04d}-12"
    else:
        fechamento = f"{fechamento_date.year:04d}-{fechamento_date.month - 1:02d}"
    for period in ("atual", "fechado"):
        competencia = atual if period == "atual" else fechamento
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
