"""Carga inicial (ou refazer) do resumo de compras e devoluções da 03.02.37.

Uso:
    python -m bot_api.scripts.reconstruir_compras_030237             # todo o histórico
    python -m bot_api.scripts.reconstruir_compras_030237 2026-09     # meses de emissão a partir de set/2026

Lê só ``liga_entrega_raw_rows`` (a 03.02.37 que a Liga já importou) e grava as
tabelas ``compras_030237_*`` e ``devolucoes_030237``. Não mexe nos dados da Liga.
"""

from __future__ import annotations

import json
import re
import sys

from bot_api.config import get_settings
from bot_api.services.compras_030237_service import Compras030237Service


def main(argv: list[str]) -> int:
    desde = argv[1] if len(argv) > 1 else None
    if desde is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", desde):
        print("Informe o mês como AAAA-MM, por exemplo 2026-09.", file=sys.stderr)
        return 2
    settings = get_settings()
    service = Compras030237Service(
        settings.reports_database_url,
        settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    print(json.dumps(service.rebuild(desde_mes=desde), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
