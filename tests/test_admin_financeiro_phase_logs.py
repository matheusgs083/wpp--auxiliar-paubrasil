from routes.admin_financeiro import _build_fechamento_phase_logs


def test_fechamento_phase_logs_ignore_logger_bootstrap() -> None:
    logs = [
        {"id": 1, "message": "PROCESSO_030303 | logger.py:155 | get_logger | Logger iniciado | level_file=INFO"},
        {"id": 2, "message": "PROCESSO_030302 | logger.py:155 | get_logger | Logger iniciado | level_file=INFO"},
        {"id": 3, "message": "PROCESSO_03030702 | logger.py:155 | get_logger | Logger iniciado | level_file=INFO"},
    ]

    assert _build_fechamento_phase_logs(logs) == []


def test_fechamento_phase_logs_show_only_real_progress() -> None:
    logs = [
        {"id": 1, "message": "FECHAMENTO COMPLETO DE MAPA | INICIO | Mapa: 93792 | Unidade: 2210003"},
        {"id": 2, "message": "Iniciando com driver local: C:\\DriverIE\\IEDriverServer.exe"},
        {"id": 3, "message": "--- LOGIN PROMAX (Unidade: 2210003) ---"},
        {"id": 4, "message": "--- PASSO 0: INICIANDO ROTINA 030303 ---"},
        {"id": 5, "message": "--- PASSO 1: INICIANDO ROTINA FISICA (030302) ---"},
        {"id": 6, "message": "03030702 | Fechamento financeiro iniciado"},
    ]

    phases = _build_fechamento_phase_logs(logs)

    assert [phase["phase"] for phase in phases] == ["inicio", "webdriver", "login", "030303", "030302", "03030702"]
