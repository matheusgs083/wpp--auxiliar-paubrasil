from __future__ import annotations

import json
from pathlib import Path

from bot_api.config import get_settings
from bot_api.services.liga_entrega_raw_sql_import_service import LigaEntregaRawSqlImportService
from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    reports_root = project_root / "exports" / "liga_entrega_reports"
    store = LigaEntregaReportStore(reports_root)
    manifests = {
        path.name: store.list_manifests(path.name)
        for path in reports_root.iterdir()
        if path.is_dir()
    } if reports_root.is_dir() else {}
    settings = get_settings()
    result = LigaEntregaRawSqlImportService(
        database_url=settings.reports_database_url,
        schema=settings.reports_db_schema,
        connect_timeout_seconds=settings.access_database_timeout_seconds,
    ).import_manifests(manifests)
    print(json.dumps({"ok": True, "routines": len(manifests), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
