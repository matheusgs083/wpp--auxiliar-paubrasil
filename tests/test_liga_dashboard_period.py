from bot_api.services.liga_entrega_dashboard_service import LigaEntregaDashboardService


class _Store:
    def list_manifests(self, routine, *, competencia=None):
        return [
            {"routine": routine, "reference_date": "2026-09-30", "metadata": {"period": "atual"}},
        ]


def test_closed_dashboard_reuses_daily_030805_batch_without_reimport():
    service = LigaEntregaDashboardService.__new__(LigaEntregaDashboardService)
    service.report_store = _Store()
    result = service._list("030805_LIGA", "2026-09", period="fechado")
    assert len(result) == 1


def test_other_closed_routines_still_require_closed_period_metadata():
    service = LigaEntregaDashboardService.__new__(LigaEntregaDashboardService)
    service.report_store = _Store()
    result = service._list("031120_BOT", "2026-09", period="fechado")
    assert result == []
