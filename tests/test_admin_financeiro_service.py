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
        {"Mapa": "028430", "Fase": "Carregado", "Placa": "RLS8A29", "Emissao": "19/08/2026", "DtOper": "20/08/2026", "HrOper": "03:00", "KmPrev": "0", "KmAtual": "70000"},
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
            "status_operacional": "Retornou",
            "operacional_ok": True,
            "fechamento_status": "Fechado",
            "fechamento_ok": True,
        },
        {
            "mapa": "28430",
            "placa": "RLS8A29",
            "km_prev": "0",
            "km_atual": "70000",
            "km_percorrido": "0",
            "saida": "20/08/2026 07:00",
            "entrada": "-",
            "tempo_rota": "-",
            "ti_fisico": "-",
            "ti_financeiro": "-",
            "ti_total": "-",
            "status_operacional": "Em rota / sem entrada",
            "operacional_ok": False,
            "fechamento_status": "Nao iniciado",
            "fechamento_ok": False,
        },
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
    assert result[0]["status_operacional"] == "Retornou"
    assert result[0]["operacional_ok"] is True
    assert result[0]["fechamento_status"] == "Entrada sem fechamento financeiro"
    assert result[0]["fechamento_ok"] is False


def test_build_rotas_dia_031120_ignores_maps_without_plate() -> None:
    rows = [
        {"Mapa": "028431", "Fase": "Carregado", "Placa": "", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "03:35", "KmPrev": "106", "KmAtual": "89526"},
        {"Mapa": "028431", "Fase": "Saida Cdd/Fab", "Placa": "", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "07:35", "KmPrev": "106", "KmAtual": "0"},
        {"Mapa": "028432", "Fase": "Carregado", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "03:35", "KmPrev": "106", "KmAtual": "89526"},
        {"Mapa": "028432", "Fase": "Saida Cdd/Fab", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "07:35", "KmPrev": "106", "KmAtual": "0"},
    ]

    result = _build_rotas_dia_031120(rows, caixa_date=date(2026, 8, 20))

    assert [row["mapa"] for row in result] == ["28432"]
    assert result[0]["status_operacional"] == "Em rota / sem entrada"
    assert result[0]["fechamento_status"] == "Nao iniciado"


def test_build_rotas_dia_031120_requires_carregamento() -> None:
    rows = [
        {"Mapa": "028431", "Fase": "Carregado", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "03:35", "KmPrev": "106", "KmAtual": "89526"},
        {"Mapa": "028432", "Fase": "Saida Cdd/Fab", "Placa": "RLS8A30", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "07:35", "KmPrev": "106", "KmAtual": "0"},
        {"Mapa": "028433", "Fase": "Carregado", "Placa": "RLS8A31", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "03:35", "KmPrev": "106", "KmAtual": "89526"},
        {"Mapa": "028433", "Fase": "Saida Cdd/Fab", "Placa": "RLS8A31", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "07:35", "KmPrev": "106", "KmAtual": "0"},
    ]

    result = _build_rotas_dia_031120(rows, caixa_date=date(2026, 8, 20))

    assert [row["mapa"] for row in result] == ["28431", "28433"]
    assert result[0]["status_operacional"] == "Sem saida"
    assert result[0]["fechamento_status"] == "Nao iniciado"


def test_build_rotas_dia_031120_closed_map_uses_entry_date_for_caixa() -> None:
    rows = [
        {"Mapa": "028434", "Fase": "Carregado", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "23:10", "KmPrev": "106", "KmAtual": "89526"},
        {"Mapa": "028434", "Fase": "Saida Cdd/Fab", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "20/08/2026", "HrOper": "23:35", "KmPrev": "106", "KmAtual": "0"},
        {"Mapa": "028434", "Fase": "Entrada Cdd/Fab", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "21/08/2026", "HrOper": "01:25", "KmPrev": "106", "KmAtual": "0"},
        {"Mapa": "028434", "Fase": "PC_Fisica", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "21/08/2026", "HrOper": "01:27", "KmPrev": "106", "KmAtual": "89633"},
        {"Mapa": "028434", "Fase": "PC_Financeira", "Placa": "RLS8A29", "Emissao": "20/08/2026", "DtOper": "21/08/2026", "HrOper": "01:40", "KmPrev": "106", "KmAtual": "0"},
    ]

    assert _build_rotas_dia_031120(rows, caixa_date=date(2026, 8, 20)) == []
    result = _build_rotas_dia_031120(rows, caixa_date=date(2026, 8, 21))

    assert [row["mapa"] for row in result] == ["28434"]
    assert result[0]["fechamento_status"] == "Fechado"


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
    assert result["diferenca"] == -100.0
    assert result["status"] == "DIVERGENTE"


def test_financeiro_percentuais_usam_base_dinheiro_mais_deposito() -> None:
    service = AdminFinanceiroService.__new__(AdminFinanceiroService)
    records = [
        {
            "total_promax": 1000.0,
            "dinheiro_total": 400.0,
            "moedas": 100.0,
            "credito_conta": 300.0,
            "transferencias_total": 200.0,
            "boletos_rota": 0,
            "boletos_recebido_qtd": 0,
            "boletos_diferenca_qtd": 0,
            "dinheiro_promax": 1000.0,
            "despesas_total": 0,
            "vales_total": 0,
            "diaristas_total": 0,
            "alimentacao_pernoite_total": 0,
            "alimentacao_hospedagem_total": 0,
            "alimentacao_janta_total": 0,
            "alimentacao_almoco_total": 0,
            "alimentacao_cafe_total": 0,
            "alimentacao_total": 0,
            "total_apurado": 1000.0,
            "diferenca": 0,
            "tipo_bloco": "mapa",
        }
    ]

    summary = service._build_summary(records)

    assert summary["numerario_total"] == 400.0
    assert summary["depositos_total"] == 500.0
    assert summary["dinheiro_percent"] == 44.44
    assert summary["deposito_percent"] == 55.56


def test_financeiro_summary_diferenca_soma_apenas_diferencas_dos_mapas() -> None:
    service = AdminFinanceiroService.__new__(AdminFinanceiroService)
    records = [
        {
            "tipo_bloco": "mapa",
            "diferenca": -80.03,
            "total_promax": 1000,
            "dinheiro_promax": 1000,
            "total_apurado": 919.97,
        },
        {
            "tipo_bloco": "mapa",
            "diferenca": 25,
            "total_promax": 500,
            "dinheiro_promax": 500,
            "total_apurado": 525,
        },
        {
            "tipo_bloco": "despesa",
            "diferenca": 120,
            "total_apurado": 120,
        },
        {
            "tipo_bloco": "vale",
            "diferenca": 50,
            "total_apurado": 50,
        },
        {
            "tipo_bloco": "compra",
            "diferenca": 300,
            "total_apurado": 300,
        },
    ]

    summary = service._build_summary(records)

    assert summary["diferenca"] == -55.03


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


def test_financeiro_diarista_sem_recibo_nao_duplica_vale_manual_mesmo_nome_valor() -> None:
    service = AdminFinanceiroService.__new__(AdminFinanceiroService)
    service.filial_labels = {"3": "Patos"}
    row = {
        "id": 1,
        "caixa_date": date(2026, 8, 26),
        "filial": "3",
        "tipo_bloco": "mapa",
        "mapa": "93853",
        "mapa_ref": "93853",
        "motorista": "DIOGO",
        "dinheiro_promax": "1725.77",
        "total_promax": "1725.77",
        "credito_conta": "0",
        "dinheiro": {"200": 8, "2": 1},
        "moedas": "0",
        "boletos_rota": "0",
        "boletos_recebido_qtd": "0",
        "diarista": "0",
        "diarista_recibo_recebido": True,
        "pernoite": "0",
        "hospedagem": "0",
        "janta": "0",
        "almoco": "22",
        "cafe": "0",
        "observacao": "",
        "updated_at": datetime(2026, 8, 26, 12, 0),
    }
    details = {
        "transferencias": {},
        "despesas": {},
        "vales": {1: [{"nome": "Allan", "valor": "80", "observacao": ""}]},
        "diaristas": {1: [{"nome": "Allan", "valor": "80", "recibo_recebido": False}]},
    }

    result = service._serialize_map(row, details)

    assert result["vales_total"] == 80.0
    assert result["total_apurado"] == 1704.0
    assert result["diferenca"] == -21.77
