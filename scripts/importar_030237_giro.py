"""Importa CSVs da 03.02.37 no padrão do giro (um por filial e mês) de uma pasta.

Uso (carga do histórico, uma vez):
    python -m bot_api.scripts.importar_030237_giro "C:\\caminho\\030237 Giro"

Cada arquivo vai numa chamada; um arquivo já importado com o mesmo conteúdo é
ignorado. Depois o worker passa a mandar os novos sozinho (rotina 030237_GIRO).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bot_api.config import get_settings
from bot_api.services.compras_030237_service import Compras030237Service


def main(argv: list[str]) -> int:
    if len(argv) < 2 or not Path(argv[1]).is_dir():
        print("Informe a pasta com os CSVs da 030237 Giro.", file=sys.stderr)
        return 2
    settings = get_settings()
    service = Compras030237Service(
        settings.reports_database_url,
        settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    arquivos = sorted(Path(argv[1]).glob("*.csv"))
    for arquivo in arquivos:
        resultado = service.importar_arquivos_giro({arquivo.name: arquivo.read_bytes()})
        print(json.dumps({"arquivo": arquivo.name, "linhas": resultado["rows"], "repetido": bool(resultado["ignorados"]), "meses": resultado["meses"]}, ensure_ascii=False))
    print(json.dumps({"ok": True, "arquivos": len(arquivos)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
