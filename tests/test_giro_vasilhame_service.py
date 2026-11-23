from __future__ import annotations

import unittest

from bot_api.services.compras_030237_service import ler_csv_030237
from bot_api.services.giro_vasilhame_service import caixas_em_comodato, giro_por_tipo, somar_por_tipo, tipo_da_garrafeira

CATALOGO = {
    "863059": {"descricao": "GARRAFEIRA PLAST PRETA 23 GARRAFAS 30OML", "tipo": "litrinho"},
    "899599": {"descricao": "GARRAFEIRA PLAST,24 GFA 600ML,,,,", "tipo": "inteira"},
    "188005": {"descricao": "GARRAFEIRA PLAST,12 GFA 1L,AMBEV,", "tipo": "litrao"},
}


class TipoDaGarrafeiraTest(unittest.TestCase):
    def test_pelo_tipo_material_da_tabela_de_garrafeiras(self) -> None:
        self.assertEqual(tipo_da_garrafeira("X", "GARRAFEIRA CERVEJA 1/2"), "litrinho")
        self.assertEqual(tipo_da_garrafeira("X", "GARRAFEIRA CERVEJA 1/1"), "inteira")
        self.assertEqual(tipo_da_garrafeira("X", "GARRAFEIRA CERVEJA LITRAO"), "litrao")

    def test_sem_tipo_usa_o_tamanho_da_descricao(self) -> None:
        self.assertEqual(tipo_da_garrafeira("GARRAFEIRA PLAST,12 GFA 965ML,,,,"), "litrao")
        self.assertEqual(tipo_da_garrafeira("GARRAFEIRA PLAST PRETA 23 GARRAFAS 30OML"), "litrinho")
        self.assertEqual(tipo_da_garrafeira("GELADEIRA BRAHMA"), "")


class RegraDoGiroTest(unittest.TestCase):
    def test_precisa_comprar_o_dobro_das_caixas(self) -> None:
        linhas = giro_por_tipo({"litrinho": 10.0, "inteira": 0.0, "litrao": 3.0}, {"litrinho": 20.0, "inteira": 9.0, "litrao": 4.0})
        por_tipo = {l["tipo"]: l for l in linhas}
        self.assertEqual((por_tipo["litrinho"]["meta"], por_tipo["litrinho"]["falta"]), (20.0, 0.0))
        self.assertFalse(por_tipo["litrinho"]["em_risco"])
        self.assertEqual((por_tipo["litrao"]["meta"], por_tipo["litrao"]["falta"]), (6.0, 2.0))
        self.assertTrue(por_tipo["litrao"]["em_risco"])
        self.assertFalse(por_tipo["inteira"]["em_risco"])

    def test_compras_somam_pela_garrafeira_do_produto(self) -> None:
        linhas = [("2350", None, 5), ("37108", "899599", 7), ("1", "0899599", 3), ("2", "188005", 2)]
        self.assertEqual(somar_por_tipo(linhas, CATALOGO), {"litrinho": 0.0, "inteira": 10.0, "litrao": 2.0})

    def test_comodato_usa_o_sub_tipo_da_02_02_20(self) -> None:
        itens = [
            {"material": "GARRAFEIRA PLAST,24 GFA 600ML,BRAHMA,C/1,", "sub_tipo": "GARRAFEIRA CERVEJA 1/1", "saldo": "41"},
            {"material": "GARRAFEIRA PLAST,12 GFA 1L,AMBEV,", "sub_tipo": "GARRAFEIRA CERVEJA LITRAO", "saldo": "10"},
            {"material": "GFA VIDRO 635ML,AMBAR,TIPO A,RETORN.,", "sub_tipo": "VASILHAME CERVEJA 1/1", "saldo": "2400"},
            {"material": "VISA COOLER", "sub_tipo": "VISA", "saldo": "1"},
        ]
        self.assertEqual(caixas_em_comodato(itens, {}), {"litrinho": 0.0, "inteira": 41.0, "litrao": 10.0})

    def test_comodato_liga_pela_descricao_da_garrafeira(self) -> None:
        itens = [
            {"material": "GARRAFEIRA PLAST,24 GFA 600ML,,,,", "sub_tipo": "", "saldo": "15"},
            {"material": "Garrafeira plast preta 23 garrafas 30oml", "sub_tipo": "", "saldo": "1.000,0"},
            {"material": "GELADEIRA BRAHMA", "sub_tipo": "Refrigerador", "saldo": "1"},
        ]
        self.assertEqual(caixas_em_comodato(itens, CATALOGO), {"litrinho": 1000.0, "inteira": 15.0, "litrao": 0.0})


class LeituraCsvGiroTest(unittest.TestCase):
    def test_le_csv_do_promax_em_cp1252(self) -> None:
        conteudo = "Empresa;Filial;Operacao .;          ;Dt. Operacao;Emissao   ;Nota;Status;Cliente;Produto;Descrição;Qtde;Total\n221;4;1;0;31/12/2025;02/01/2026;360717;A;11313;2349;GUARANÁ;4;170,88\n".encode("cp1252")
        linhas = ler_csv_030237(conteudo)
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["Emissao"], "02/01/2026")
        self.assertEqual(linhas[0]["Descricao"], "GUARANÁ")
        self.assertNotIn("Operacao .", linhas[0])


if __name__ == "__main__":
    unittest.main()
