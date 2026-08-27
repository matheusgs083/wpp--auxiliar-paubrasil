from datetime import date, datetime

from bot_api.services.admin_financeiro_service import (
    AdminFinanceiroService,
    _build_rotas_dia_031120,
    _financeiro_manual_update_flags,
    _normalize_financeiro_dirty_fields,
)


def test_build_rotas_dia_031120_groups_route_phases_by_map() -> None:
    rows = [
        {"Mapa": "028429", "Fase": "Carregado", "Placa": "SKZ8I57", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "03:10", "KmPrev": "85", "KmAtual": "80945"},
        {"Mapa": "028429", "Fase": "Saida Cdd/Fab", "Placa": "SKZ8I57", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "07:34", "KmPrev": "85", "KmAtual": "0"},
        {"Mapa": "028429", "Fase": "Entrada Cdd/Fab", "Placa": "SKZ8I57", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "21:52", "KmPrev": "85", "KmAtual": "0"},
        {"Mapa": "028429", "Fase": "PC_Fisica", "Placa": "SKZ8I57", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "21:53", "KmPrev": "85", "KmAtual": "81027"},
        {"Mapa": "028429", "Fase": "PC_Financeira", "Placa": "SKZ8I57", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "21:55", "KmPrev": "100", "KmAtual": "0"},
        {"Mapa": "028430", "Fase": "Saida Cdd/Fab", "Placa": "RLS8A29", "Emissao": "19/08/2026", "DtOper": "20/08/2026", "HrOper": "07:00", "KmPrev": "0", "KmAtual": "0"},
    ]

    result = _build_rotas_dia_031120(rows, caixa_date=date(2026, 8, 20))

    assert result == [
        {
            "mapa": "28429",
            "placa": "SKZ8I57",
            "km_prev": "85",
            "km_atual": "81027",
            "km_percorrido": "82",
            "saida": "20/08/2026 07:34",
            "entrada": "20/08/2026 21:52",
            "tempo_rota": "14:18",
            "ti_fisico": "00:01",
            "ti_financeiro": "00:02",
            "ti_total": "00:03",
            "fechamento_status": "Fechado",
            "fechamento_ok": True,
        }
    ]


def test_build_rotas_dia_031120_flags_entered_route_without_financial_close() -> None:
    rows = [
        {"Mapa": "028430", "Fase": "Carregado", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "03:11", "KmPrev": "106", "KmAtual": "89526"},
        {"Mapa": "028430", "Fase": "Saida Cdd/Fab", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "07:35", "KmPrev": "106", "KmAtual": "0"},
        {"Mapa": "028430", "Fase": "Entrada Cdd/Fab", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "19:25", "KmPrev": "106", "KmAtual": "0"},
        {"Mapa": "028430", "Fase": "PC_Fisica", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "19:25", "KmPrev": "106", "KmAtual": "89633"},
    ]

    result = _build_rotas_dia_031120(rows, caixa_date=date(2026, 8, 20))

    assert result[0]["km_percorrido"] == "107"
    assert result[0]["fechamento_status"] == "Entrada sem fechamento financeiro"
    assert result[0]["fechamento_ok"] is False


def test_normalize_financeiro_dirty_fields_ignores_unknown_values() -> None:
    fields = _normalize_financeiro_dirty_fields(["motorista", "credito_conta", "", "nao_existe", None, "motorista"])

    assert fields == {"motorista", "credito_conta"}


def test_financeiro_manual_update_flags_only_enables_dirty_fields() -> None:
    flags = _financeiro_manual_update_flags({"motorista", "dinheiro", "observacao"})

    assert flags["motorista"] is True
    assert flags["dinheiro"] is True
    assert flags["observacao"] is True
    assert flags["placa"] is False
    assert flags["total_promax"] is False


def test_financeiro_diferenca_usa_dinheiro_promax_e_permite_sobra() -> None:
    service = AdminFinanceiroService.__new__(AdminFinanceiroService)
    service.filial_labels = {"3": "Patos"}
    row = {
        "id": 1,
        "caixa_date": date(2026, 8, 26),
        "filial": "3",
        "tipo_bloco": "mapa",
        "mapa": "93796",
        "mapa_ref": "93796",
        "motorista": "MATHEUS",
        "dinheiro_promax": "1000",
        "total_promax": "99999",
        "credito_conta": "0",
        "dinheiro": {"100": 9},
        "moedas": "0",
        "boletos_rota": "0",
        "boletos_recebido_qtd": "0",
        "diarista": "0",
        "pernoite": "0",
        "hospedagem": "0",
        "janta": "0",
        "almoco": "0",
        "cafe": "0",
        "observacao": "",
        "updated_at": datetime(2026, 8, 26, 12, 0),
    }
    details = {"transferencias": {}, "despesas": {}, "vales": {}, "diaristas": {}}

    result = service._serialize_map(row, details)

    assert result["total_apurado"] == 900.0
    assert result["dinheiro_promax"] == 1000.0
    assert result["total_promax"] == 1000.0
    assert result["diferenca"] == 100.0
    assert result["status"] == "DIVERGENTE"


def test_financeiro_diarista_sem_recibo_vira_vale_calculado() -> None:
    service = AdminFinanceiroService.__new__(AdminFinanceiroService)
    service.filial_labels = {"3": "Patos"}
    row = {
        "id": 1,
        "caixa_date": date(2026, 8, 26),
        "filial": "3",
        "tipo_bloco": "mapa",
        "mapa": "93796",
        "mapa_ref": "93796",
        "motorista": "MOTORISTA TESTE",
        "dinheiro_promax": "100",
        "total_promax": "100",
        "credito_conta": "0",
        "dinheiro": {},
        "moedas": "0",
        "boletos_rota": "0",
        "boletos_recebido_qtd": "0",
        "diarista": "0",
        "diarista_recibo_recebido": True,
        "pernoite": "0",
        "hospedagem": "0",
        "janta": "0",
        "almoco": "0",
        "cafe": "0",
        "observacao": "",
        "updated_at": datetime(2026, 8, 26, 12, 0),
    }
    details = {
        "transferencias": {},
        "despesas": {},
        "vales": {},
        "diaristas": {1: [{"nome": "CHAPA 1", "valor": "80", "recibo_recebido": False}]},
    }

    result = service._serialize_map(row, details)

    assert result["diaristas_total"] == 0.0
    assert result["vales_total"] == 80.0
    assert result["total_apurado"] == 80.0
    assert result["vales_consolidados"] == [
        {
            "nome": "CHAPA 1",
            "valor": 80.0,
            "observacao": "vale de chapa",
            "assinado": False,
            "origem": "diarista_sem_recibo",
        }
    ]
