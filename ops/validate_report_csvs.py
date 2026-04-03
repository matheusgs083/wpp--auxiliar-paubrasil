from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot_api.config import get_settings
from bot_api.services.comodatos_import_service import ComodatosImportService
from bot_api.services.dclientes_import_service import DClientesImportService
from bot_api.services.dsetores_import_service import DSetoresImportService
from bot_api.services.inadimplencia_import_service import InadimplenciaImportService


def main() -> None:
    args = _parse_args()
    settings = get_settings()

    dclientes_service = DClientesImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    dsetores_service = DSetoresImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    inadimplencia_service = InadimplenciaImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    comodatos_service = ComodatosImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )

    try:
        validations = [
            dsetores_service.validate_csv(args.dsetores_path),
            dclientes_service.validate_csv(args.dclientes_path),
            inadimplencia_service.validate_source(args.inadimplencia_path),
            comodatos_service.validate_source(args.comodatos_path),
        ]
        payload = {
            "ok": all(item.ok for item in validations),
            "datasets": [item.to_dict() for item in validations],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if not payload["ok"]:
            raise SystemExit(1)
    except Exception as exc:
        print(json.dumps({"ok": False, "detail": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida a estrutura dos CSVs de dSetores, dClientes, inadimplencia e comodatos antes da importacao."
    )
    parser.add_argument(
        "--dsetores-path",
        type=Path,
        default=Path("data/dSetores/dSetores.csv"),
        help="Caminho do CSV dSetores.",
    )
    parser.add_argument(
        "--dclientes-path",
        type=Path,
        default=Path("data/dClientes/dClientes.csv"),
        help="Caminho do CSV dClientes.",
    )
    parser.add_argument(
        "--inadimplencia-path",
        type=Path,
        default=Path("data/Inadimplencia"),
        help="Pasta ou arquivo CSV da inadimplencia.",
    )
    parser.add_argument(
        "--comodatos-path",
        type=Path,
        default=Path("data/Comodatos"),
        help="Pasta ou arquivo CSV dos comodatos.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
