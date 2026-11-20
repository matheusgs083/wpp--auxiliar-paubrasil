from __future__ import annotations

from pathlib import Path

import pytest

from bot_api.services.jornada_mapas_indicadores_service import JornadaMapasIndicadoresService
from bot_api.services.jornada_mapas_justificativas_service import (
    JornadaMapasJustificativasService,
    jornada_mapa_id,
)


class FakeRawSql:
    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows

    def rows_for_routine(self, *, routine, competencia, period):
        return [{"source_key": routine, "filename": "030805_PATOS.csv", "payload": row} for row in self.rows.get(routine, [])]


def _linha_030805(**campos):
    base = {"Data": "07112026", "UNB": "3", "Mapa": "029240", "Placa": "TOT4F49", "Entregas": "046",
            "CxCarreg": "0000193,54", "CxEntreg": "0000190,54", "PesoCargaKG": "0010262,00",
            "CapacidadeVeiculoKG": "0012000,00", "Ocup.": "085,52",
            "HrSai": "07:41", "HrEntr": "23:47", "TmpoInterno": "00:09", "TempoPrev": "10:22"}
    return base | campos


def _dashboard(*linhas, justificativas=None):
    service = JornadaMapasIndicadoresService(
        raw_sql_import_service=FakeRawSql({"030805_LIGA": list(linhas)}),
        justificativas_service=justificativas,
    )
    return service.build_dashboard(competencia="2026-11")


@pytest.mark.parametrize("hr_sai, hr_entr, interno, previsto, final, jornada, dif", [
    # Linhas da planilha "Jornada Patos / Sumé" usada como modelo.
    ("07:41", "23:47", "00:09", "10:22", "23:56", 15 * 60 + 15, 4 * 60 + 53),
    ("06:12", "21:43", "00:42", "23:24", "22:25", 15 * 60 + 13, -(8 * 60 + 11)),
    ("07:28", "22:02", "01:06", "07:39", "23:08", 14 * 60 + 40, 7 * 60 + 1),
])
def test_horarios_da_jornada_batem_com_a_planilha(hr_sai, hr_entr, interno, previsto, final, jornada, dif):
    row = _dashboard(_linha_030805(HrSai=hr_sai, HrEntr=hr_entr, TmpoInterno=interno, TempoPrev=previsto))["rows"][0]
    assert row["inicio_jornada"] == hr_sai
    assert row["hora_entrada"] == hr_entr
    assert row["hora_final"] == final
    assert row["jornada_min"] == jornada
    assert row["dif_jornada_min"] == dif


def test_jornada_que_passa_da_meia_noite():
    row = _dashboard(_linha_030805(HrSai="08:00", HrEntr="23:50", TmpoInterno="00:30"))["rows"][0]
    assert row["hora_final"] == "00:20"
    assert row["jornada_min"] == 15 * 60 + 20


def test_sem_horario_nao_inventa_jornada():
    row = _dashboard(_linha_030805(HrSai="", TempoPrev=""))["rows"][0]
    assert row["inicio_jornada"] == ""
    assert row["jornada_min"] is None
    assert row["dif_jornada_min"] is None


def test_justificativa_de_ocupacao_e_separada_da_de_jornada(tmp_path: Path):
    store = JornadaMapasJustificativasService(tmp_path / "just.json")
    row = _dashboard(_linha_030805(), justificativas=store)["rows"][0]
    assert row["justificativa_id"] != row["ocupacao_justificativa_id"]
    # A chave da jornada continua a mesma de antes (dados já salvos não se perdem).
    assert row["justificativa_id"] == jornada_mapa_id({k: row[k] for k in ("competencia", "data", "filial", "mapa")})

    store.save(row, "Carga fracionada", actor="teste", tipo="ocupacao")
    row = _dashboard(_linha_030805(), justificativas=store)["rows"][0]
    assert row["ocupacao_justificada"] is True
    assert row["ocupacao_justificativa"]["text"] == "Carga fracionada"
    assert row["ocupacao_justificativa"]["tipo"] == "ocupacao"
    assert row["justificada"] is False


def test_tipo_de_justificativa_invalido():
    with pytest.raises(ValueError):
        jornada_mapa_id({"competencia": "2026-11", "data": "2026-11-07", "filial": "PATOS", "mapa": "1"}, "outro")
