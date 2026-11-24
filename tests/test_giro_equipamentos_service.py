from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from bot_api.services.giro_equipamentos_service import (
    equipamentos_em_comodato,
    giro_por_equipamento,
    mix_cerveja,
    previsao_do_mes,
    situacao_do_giro,
)


class EquipamentosEmComodatoTest(unittest.TestCase):
    def test_conta_sopi_e_visa_pelo_sub_tipo_da_02_02_20(self) -> None:
        itens = [
            {"sub_tipo": "SOPI", "saldo": "1"},
            {"sub_tipo": "SOPI", "saldo": "1"},
            {"sub_tipo": "SOPI", "saldo": "0"},  # já recolhido
            {"sub_tipo": "VISA", "saldo": "1"},
            {"sub_tipo": "GARRAFEIRA CERVEJA 1/1", "saldo": "41"},
            {"sub_tipo": "OUTROS MAT.", "saldo": "3"},
        ]
        self.assertEqual(equipamentos_em_comodato(itens), {"sopi": 2, "visa": 1})


class GiroPorEquipamentoTest(unittest.TestCase):
    def test_meta_vale_por_equipamento(self) -> None:
        sopi, visa = giro_por_equipamento({"sopi": 2, "visa": 1}, {"Cerveja TT": Decimal("3000"), "Refrigerante TT": Decimal("1500")})
        self.assertEqual((sopi["meta"], sopi["falta"], sopi["percentual"]), (Decimal("4000.00"), Decimal("1000.00"), 75))
        self.assertTrue(sopi["em_risco"])
        self.assertEqual((visa["meta"], visa["falta"], visa["percentual"]), (Decimal("1200.00"), Decimal("0"), 100))
        self.assertFalse(visa["em_risco"])

    def test_refrigerante_nao_conta_para_o_sopi(self) -> None:
        sopi, _ = giro_por_equipamento({"sopi": 1, "visa": 0}, {"Refrigerante TT": Decimal("9000")})
        self.assertEqual(sopi["comprado"], Decimal("0"))
        self.assertTrue(sopi["em_risco"])

    def test_sem_equipamento_nao_tem_meta(self) -> None:
        _, visa = giro_por_equipamento({"sopi": 0, "visa": 0}, {})
        self.assertIsNone(visa["percentual"])
        self.assertFalse(visa["em_risco"])



class PrevisaoTest(unittest.TestCase):
    def test_projeta_no_ritmo_dos_dias_corridos(self) -> None:
        self.assertEqual(previsao_do_mes(Decimal("1640.30"), date(2026, 11, 24)), Decimal("2050.38"))  # 1640,30 ÷ 24 × 30

    def test_situacao(self) -> None:
        self.assertEqual(situacao_do_giro(Decimal("2000"), Decimal("2100"), Decimal("2500")), "batido")
        self.assertEqual(situacao_do_giro(Decimal("2000"), Decimal("1640"), Decimal("2050")), "deve_atingir")
        self.assertEqual(situacao_do_giro(Decimal("2000"), Decimal("900"), Decimal("1100")), "em_risco")


def _linha(competencia: str, produto: str, dia: int | None = None) -> dict:
    mes = int(competencia[5:])
    return {"competencia": competencia, "produto": produto, "descricao": f"CERVEJA {produto}", "total": Decimal("100"),
            "ultima_data": date(int(competencia[:4]), mes, dia) if dia else None}


class MixCervejaTest(unittest.TestCase):
    def test_conta_skus_e_sugere_o_que_ele_comprava(self) -> None:
        anteriores = ["2026-08", "2026-09", "2026-10"]
        linhas = [
            _linha("2026-11", "1"), _linha("2026-11", "2"),
            _linha("2026-08", "1"), _linha("2026-08", "3"), _linha("2026-09", "3"), _linha("2026-10", "3", 29),
            _linha("2026-09", "4"), _linha("2026-10", "4", 22),
            _linha("2026-10", "5", 30),
        ]
        mix = mix_cerveja(linhas, "2026-11", anteriores, meta=3)
        self.assertEqual((mix["skus_mes"], mix["faltam"]), (2, 1))
        self.assertEqual([m["skus"] for m in mix["meses_anteriores"]], [2, 2, 3])
        self.assertEqual([m["bateu"] for m in mix["meses_anteriores"]], [False, False, True])
        # 3 nos 3 meses; depois 4 (2 meses); depois 5 (1 mês). O 1 já veio neste mês.
        self.assertEqual([p["produto"] for p in mix["completar"]], ["3", "4", "5"])
        self.assertEqual((mix["completar"][0]["meses"], mix["completar"][0]["ultima"]), (3, "29/10"))

    def test_mes_sem_03_02_37_nao_conta_como_zero(self) -> None:
        mix = mix_cerveja([{"competencia": "2026-08", "sem_base": True}, _linha("2026-11", "1")], "2026-11", ["2026-08", "2026-09", "2026-10"])
        self.assertTrue(mix["meses_anteriores"][0]["sem_base"])
        self.assertFalse(mix["meses_anteriores"][1]["sem_base"])


if __name__ == "__main__":
    unittest.main()
