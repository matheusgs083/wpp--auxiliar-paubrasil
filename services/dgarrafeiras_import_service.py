from __future__ import annotations

from bot_api.services.dmateriais_import_service import DMateriaisImportService


class DGarrafeirasImportService(DMateriaisImportService):
    dataset_name = "dgarrafeiras"
    snapshot_table = "dgarrafeiras_snapshot"
    latest_view = "dgarrafeiras_latest"
    dataset_label = "tabela de garrafeiras"
