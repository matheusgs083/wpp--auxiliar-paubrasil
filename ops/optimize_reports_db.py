from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from bot_api.config import get_settings
from bot_api.services.comodatos_import_service import ComodatosImportService
from bot_api.services.dclientes_import_service import DClientesImportService
from bot_api.services.dsetores_import_service import DSetoresImportService
from bot_api.services.giro_import_service import GiroImportService
from bot_api.services.inadimplencia_import_service import InadimplenciaImportService


def main() -> None:
    settings = get_settings()
    if not settings.reports_database_url:
        raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

    dclientes = DClientesImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    dsetores = DSetoresImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    inadimplencia = InadimplenciaImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    comodatos = ComodatosImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )
    giro = GiroImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    )

    result = {
        "dsetores": dsetores.refresh_latest_view(),
        "dclientes": dclientes.refresh_latest_view(),
        "inadimplencia": inadimplencia.refresh_latest_view(),
        "comodatos": comodatos.refresh_latest_view(),
        "giro": giro.refresh_latest_view(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
