from bot_api.services.liga_entrega_dashboard_service import LigaEntregaDashboardService, route_km_values


class _Store:
    def list_manifests(self, routine, *, competencia=None):
        return [
            {
                "routine": routine,
                "reference_date": "2026-10-02",
                "metadata": {"period": "atual"},
                "files": [{"filename": "PATOS_30_09.csv"}],
            },
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


def test_closed_dashboard_competence_follows_daily_030805_filename():
    service = LigaEntregaDashboardService.__new__(LigaEntregaDashboardService)
    service.report_store = _Store()
    assert service._latest_competencia(period="fechado") == "2026-09"


def test_030805_uses_km_desloc_when_odometer_is_zero():
    actual, planned = route_km_values(
        {
            "kmsai": "0000000",
            "kmentr": "0000000",
            "kmdesloc": "002055",
            "kmprev": "00023,42",
        }
    )
    assert actual == 20.55
    assert planned == 23.42


def test_030805_keeps_odometer_calculation_when_available():
    actual, planned = route_km_values(
        {
            "kmsai": "0082526",
            "kmentr": "0082812",
            "kmdesloc": "0028675",
            "kmprev": "00286,74",
        }
    )
    assert actual == 286
    assert planned == 286.74
