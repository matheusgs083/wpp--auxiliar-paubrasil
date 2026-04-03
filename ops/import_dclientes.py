from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot_api.config import get_settings
from bot_api.services.dclientes_import_service import DClientesImportService


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    service = DClientesImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )

    try:
        validation = service.validate_csv(args.file_path)
        print(json.dumps({"mode": "validate", **validation.to_dict()}, ensure_ascii=False, indent=2))
        validation.ensure_valid()

        summary = service.summarize_csv(args.file_path)
        print(json.dumps({"mode": "analyze", **summary.to_dict()}, ensure_ascii=False, indent=2))

        if not args.import_db:
            return

        batch_date = date.fromisoformat(args.reference_date) if args.reference_date else None
        result = service.import_csv(args.file_path, reference_date=batch_date)
        print(json.dumps({"mode": "import", **result}, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"mode": "error", "detail": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisa e importa o CSV dClientes para PostgreSQL, normalizando codigos sem zeros a esquerda."
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        type=Path,
        default=Path("data/dClientes/dClientes.csv"),
        help="Caminho do CSV dClientes.",
    )
    parser.add_argument(
        "--import-db",
        action="store_true",
        help="Alem da analise, importa o arquivo para o banco configurado.",
    )
    parser.add_argument(
        "--reference-date",
        help="Data de referencia da carga no formato YYYY-MM-DD. Se omitida, usa a data de modificacao do arquivo.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
