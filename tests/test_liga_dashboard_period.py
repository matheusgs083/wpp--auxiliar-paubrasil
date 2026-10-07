from bot_api.services.liga_entrega_dashboard_service import (
    LigaEntregaDashboardService,
    preserve_operational_route_date,
    route_km_values,
)


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


def test_closed_dashboard_recovers_legacy_devolucao_batch_without_period_metadata():
    from bot_api.services.liga_entrega_dashboard_service import R030224S

    service = LigaEntregaDashboardService.__new__(LigaEntregaDashboardService)
    service.report_store = _Store()
    result = service._list(R030224S, "2026-09", period="fechado")
    assert len(result) == 1


def test_bootstrap_rebuilds_instead_of_returning_stale_snapshot():
    class EmptyStore:
        def list_manifests(self, _routine, *, competencia=None):
            return []

    class SnapshotStore:
        def get_latest(self, **_kwargs):
            return ("2026-08", {"summary": {"ready": True, "devolucoes": 999}})

        def get(self, **_kwargs):
            return None

        def put(self, **_kwargs):
            return None

    class Expurgos:
        def list_expurgos(self, **_kwargs):
            return {"items": []}

    service = LigaEntregaDashboardService(
        report_store=EmptyStore(),
        expurgo_service=Expurgos(),
        snapshot_store=SnapshotStore(),
        allow_source_files=True,
    )

    rebuilt = service.build_dashboard(competencia="2026-08", period="fechado")

    assert rebuilt["summary"]["devolucoes"] == 0


def test_closed_dashboard_competence_follows_daily_030805_filename():
    service = LigaEntregaDashboardService.__new__(LigaEntregaDashboardService)
    service.report_store = _Store()
    assert service._latest_competencia(period="fechado") == "2026-09"


def test_current_dashboard_competence_also_follows_daily_030805_filename():
    service = LigaEntregaDashboardService.__new__(LigaEntregaDashboardService)
    service.report_store = _Store()
    assert service._latest_competencia(period="atual") == "2026-09"


def test_auxiliary_manifest_matches_operational_csv_date_when_uploaded_next_month(tmp_path):
    from bot_api.services.liga_entrega_dashboard_service import _manifest_covers_operational_competencia

    path = tmp_path / "031120_PATOS.csv"
    path.write_text("Mapa;DtOper;Fase;HrOper\n123;30/09/2026;Saida;07:00\n", encoding="cp1252")
    manifest = {
        "reference_date": "2026-10-02",
        "metadata": {"period": "fechado"},
        "files": [{"filename": path.name, "path": str(path)}],
    }
    assert _manifest_covers_operational_competencia(manifest, "2026-09")


def test_auxiliary_list_does_not_require_reference_date_directory(tmp_path):
    from bot_api.services.liga_entrega_dashboard_service import R031120

    path = tmp_path / "031120_PATOS.csv"
    path.write_text("Mapa;DtOper;Fase;HrOper\n123;30/09/2026;Saida;07:00\n", encoding="cp1252")

    class Store:
        def list_manifests(self, routine, *, competencia=None):
            return [{
                "routine": routine,
                "reference_date": "2026-10-02",
                "metadata": {"period": "fechado"},
                "files": [{"filename": path.name, "path": str(path)}],
            }]

    service = LigaEntregaDashboardService.__new__(LigaEntregaDashboardService)
    service.report_store = Store()
    assert len(service._list(R031120, "2026-09", period="fechado")) == 1


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


def test_031129_never_replaces_operational_date_from_030805():
    route = {"data": "2026-09-30"}
    preserve_operational_route_date(route, {"data": "2026-10-02"})
    assert route["data"] == "2026-09-30"


def test_031129_date_can_fill_route_created_without_030805():
    route = {"data": ""}
    preserve_operational_route_date(route, {"data": "2026-09-30"})
    assert route["data"] == "2026-09-30"
