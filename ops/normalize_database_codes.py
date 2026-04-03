from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot_api.config import get_settings
from bot_api.security.access_control import AccessControl
from bot_api.services.dclientes_import_service import DClientesImportService


def main() -> None:
    args = _parse_args()
    settings = get_settings()

    access_control = AccessControl(
        enabled=settings.access_control_enabled,
        database_url=settings.access_database_url,
        schema=settings.access_db_schema,
        public_enabled=settings.access_public_enabled,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    reports_service = DClientesImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )

    summary: dict[str, object] = {}

    try:
        summary["access_control_ready"] = access_control.initialize()
        summary["access_status"] = access_control.status()

        if args.refresh_view:
            summary["reports_view"] = reports_service.refresh_latest_view()

        if args.reimport_dclientes:
            summary["reimport"] = reports_service.import_csv(args.file_path, reference_date=None)

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normaliza codigos no banco e recria a view do dClientes sem zeros a esquerda."
    )
    parser.add_argument(
        "--refresh-view",
        action="store_true",
        help="Recria a view reports.dclientes_latest com os codigos normalizados.",
    )
    parser.add_argument(
        "--reimport-dclientes",
        action="store_true",
        help="Importa novamente o CSV dClientes usando os codigos ja normalizados.",
    )
    parser.add_argument(
        "--file-path",
        type=Path,
        default=Path("data/dClientes/dClientes.csv"),
        help="Caminho do CSV dClientes para reimportacao.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
