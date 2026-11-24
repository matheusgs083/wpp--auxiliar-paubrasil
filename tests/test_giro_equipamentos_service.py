from __future__ import annotations

import unittest
from decimal import Decimal

from bot_api.services.giro_equipamentos_service import equipamentos_em_comodato, giro_por_equipamento


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


if __name__ == "__main__":
    unittest.main()
