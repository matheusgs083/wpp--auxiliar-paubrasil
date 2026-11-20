from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bot_api.services.entrega_frota_service import EntregaFrotaService
from bot_api.services.entrega_pallets_service import EntregaPalletsService
from bot_api.services.jornada_mapas_indicadores_service import JornadaMapasIndicadoresService
from bot_api.services.liga_entrega_raw_sql_import_service import _payload_historico

FIXTURE = Path(__file__).parent / "fixtures" / "03.02.37_PATOS_NOV.csv"

# (Fator, Caixas Pallet) da 01.11 real para os produtos do arquivo de teste.
PALETIZACAO_0111 = {"982": (12.0, 84.0), "33820": (12.0, 286.0), "1388": (12.0, 50.0)}


class FakeProdutos:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_paletizacao(self, codigos):
        self.calls += 1
        return {codigo: PALETIZACAO_0111[codigo] for codigo in codigos if codigo in PALETIZACAO_0111}


class FakeReportStore:
    def __init__(self, manifests):
        self.manifests = manifests

    def list_manifests(self, routine, *, competencia=None):
        return self.manifests if routine == "030237" else []


def _manifest(tmp_path: Path, *, batch_id: str = "b1", stored_at: str = "2026-11-20T10:00:00", competencia: str = "2026-11") -> dict:
    target = tmp_path / batch_id / FIXTURE.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE, target)
    return {
        "batch_id": batch_id,
        "stored_at": stored_at,
        "reference_date": f"{competencia}-20",
        "metadata": {"competencia": competencia},
        "files": [{"filename": target.name, "path": str(target)}],
    }


# ---------------------------------------------------------------- frota


def test_frota_normaliza_placa_e_guarda_por_operacao(tmp_path: Path):
    service = EntregaFrotaService(tmp_path / "frota.json")
    result = service.replace({
        "caminhoes": [
            {"filial": "patos", "placa": "rlu-6a86", "descricao": "Toco", "capacidade_pallets": "10"},
            {"filial": "SUME", "placa": "RLU6A86", "capacidade_pallets": 12},
        ],
        "metas": [
            {"filial": "patos", "ocupacao_meta_pct": "65,76", "caixas_viagem_meta": "285,69"},
            {"filial": "SUME", "ocupacao_meta_pct": "", "caixas_viagem_meta": "250"},
        ],
    }, actor="teste")
    assert [(c["filial"], c["placa"], c["capacidade_pallets"]) for c in result["caminhoes"]] == [
        ("PATOS", "RLU6A86", 10.0), ("SUME", "RLU6A86", 12.0),
    ]
    lookup = service.lookup()
    assert lookup.caminhao("Patos", "RLU-6A86")["descricao"] == "Toco"
    assert lookup.caminhao("SUME", "RLU6A86")["capacidade_pallets"] == 12.0
    assert lookup.meta_ocupacao("PATOS") == 65.76
    assert lookup.meta_caixas_viagem("PATOS") == 285.69
    # Cada meta é opcional: Sumé só tem caixas por viagem.
    assert lookup.meta_ocupacao("SUME") is None
    assert lookup.meta_caixas_viagem("SUME") == 250.0
    assert service.list()["updated_by"] == "teste"


def test_meta_invalida_e_recusada(tmp_path: Path):
    with pytest.raises(ValueError, match="caixas por viagem"):
        EntregaFrotaService(tmp_path / "frota.json").replace({"caminhoes": [], "metas": [{"filial": "PATOS", "caixas_viagem_meta": "-1"}]})


@pytest.mark.parametrize("caminhao, mensagem", [
    ({"filial": "PATOS", "placa": "123", "capacidade_pallets": 10}, "Placa inválida"),
    ({"filial": "PATOS", "placa": "ABC1234", "capacidade_pallets": 0}, "Capacidade"),
    ({"filial": "", "placa": "ABC1234", "capacidade_pallets": 5}, "operação"),
])
def test_frota_recusa_cadastro_invalido(tmp_path: Path, caminhao, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        EntregaFrotaService(tmp_path / "frota.json").replace({"caminhoes": [caminhao], "metas": []})


def test_frota_recusa_placa_repetida_na_mesma_operacao(tmp_path: Path):
    caminhao = {"filial": "PATOS", "placa": "ABC1234", "capacidade_pallets": 5}
    with pytest.raises(ValueError, match="duas vezes"):
        EntregaFrotaService(tmp_path / "frota.json").replace({"caminhoes": [caminhao, caminhao], "metas": []})


def test_caminhao_inativo_nao_entra_na_conta(tmp_path: Path):
    service = EntregaFrotaService(tmp_path / "frota.json")
    service.replace({"caminhoes": [{"filial": "PATOS", "placa": "ABC1234", "capacidade_pallets": 5, "ativo": False}]})
    assert service.lookup().caminhao("PATOS", "ABC1234") is None


# -------------------------------------------------------------- pallets


def test_pallets_por_mapa_converte_unidades_e_ignora_vasilhame_e_devolucao(tmp_path: Path):
    service = EntregaPalletsService(report_store=FakeReportStore([_manifest(tmp_path)]), dprodutos_import_service=FakeProdutos())
    mapas = service.pallets_por_mapa("2026-11")["mapas"]
    # 168 Dz / 84 + 143 cx / 286 + (504 Un / 12) / 84 = 2,0 + 0,5 + 0,5
    assert mapas[("PATOS", "96027")]["pallets"] == 3.0
    assert mapas[("PATOS", "96027")]["itens_sem_paletizacao"] == 1
    assert mapas[("PATOS", "96030")]["pallets"] == 0.5


def test_pallets_usa_a_ultima_remessa_da_competencia_e_guarda_em_cache(tmp_path: Path):
    produtos = FakeProdutos()
    store = FakeReportStore([
        _manifest(tmp_path, batch_id="antiga", stored_at="2026-11-10T08:00:00"),
        _manifest(tmp_path, batch_id="nova", stored_at="2026-11-20T08:00:00"),
        _manifest(tmp_path, batch_id="outubro", stored_at="2026-11-21T08:00:00", competencia="2026-10"),
    ])
    service = EntregaPalletsService(report_store=store, dprodutos_import_service=produtos)
    assert service.pallets_por_mapa("2026-11")["batch_id"] == "nova"
    service.pallets_por_mapa("2026-11")
    assert produtos.calls == 1


def test_sem_03_02_37_avisa_em_vez_de_zerar(tmp_path: Path):
    result = EntregaPalletsService(report_store=FakeReportStore([]), dprodutos_import_service=FakeProdutos()).pallets_por_mapa("2026-11")
    assert result["mapas"] == {}
    assert result["warnings"]


# ----------------------------------------------------- ocupação no painel


class FakeRawSql:
    def rows_for_routine(self, *, routine, competencia, period):
        if routine != "030805_LIGA":
            return []
        linha = {"Data": "03112026", "UNB": "3", "Mapa": "096027", "Placa": "RLU6A86", "Entregas": "010",
                 "CxCarreg": "100", "CxEntreg": "100", "PesoCargaKG": "5000", "CapacidadeVeiculoKG": "7000",
                 "Ocup.": "071,43", "HrSai": "07:00", "HrEntr": "17:00", "TmpoInterno": "00:10", "TempoPrev": "10:00"}
        return [{"source_key": "k", "filename": "030805_PATOS.csv", "payload": linha}]


def test_ocupacao_em_pallets_compara_com_a_capacidade_e_meta_cadastradas(tmp_path: Path):
    frota = EntregaFrotaService(tmp_path / "frota.json")
    frota.replace({
        "caminhoes": [{"filial": "PATOS", "placa": "RLU6A86", "descricao": "Toco", "capacidade_pallets": 6}],
        "metas": [{"filial": "PATOS", "ocupacao_meta_pct": 65.76}],
    })
    pallets = EntregaPalletsService(report_store=FakeReportStore([_manifest(tmp_path)]), dprodutos_import_service=FakeProdutos())
    result = JornadaMapasIndicadoresService(raw_sql_import_service=FakeRawSql(), pallets_service=pallets, frota_service=frota).build_dashboard(competencia="2026-11")
    veiculo = result["vehicles"][0]
    assert veiculo["pallets"] == 3.0
    assert veiculo["capacidade_pallets"] == 6.0
    assert veiculo["ocupacao_pallets_pct"] == 50.0
    assert veiculo["meta_ocupacao_pct"] == 65.76
    assert veiculo["caminhao_descricao"] == "Toco"
    assert result["ocupacao_avisos"] == []


def test_caminhao_sem_cadastro_mostra_pallets_e_avisa(tmp_path: Path):
    frota = EntregaFrotaService(tmp_path / "frota.json")
    pallets = EntregaPalletsService(report_store=FakeReportStore([_manifest(tmp_path)]), dprodutos_import_service=FakeProdutos())
    result = JornadaMapasIndicadoresService(raw_sql_import_service=FakeRawSql(), pallets_service=pallets, frota_service=frota).build_dashboard(competencia="2026-11")
    veiculo = result["vehicles"][0]
    assert veiculo["pallets"] == 3.0
    assert veiculo["ocupacao_pallets_pct"] is None
    assert "sem capacidade cadastrada" in result["ocupacao_avisos"][0]


# ------------------------------------------------------ histórico enxuto


def test_historico_da_03_02_37_guarda_so_as_colunas_da_entrega():
    linha = {"Nota": "1", "Produto": "982", "Qtde": "168", "Mapa": "96.027", "Status": "A", "Chave de Acesso NF-e": "x" * 44, "Valor CBS": "0"}
    assert _payload_historico("030237", linha) == {"Nota": "1", "Produto": "982", "Qtde": "168", "Mapa": "96.027", "Status": "A"}
    assert _payload_historico("030805_LIGA", linha) == linha
