from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace

from bot_api.services.ficha_cadastro import dias_da_visita, montar_cadastro, proxima_data, visitas_no_mes

# Linha real da dClientes (cliente 1 de Sousa), com os nomes de coluna do relatório.
LINHA = {
    "Documento": "07.946.089/0001-22", "Nome Fantasia": "MERCADINHO ZONA SUL", "Razão Social": "GERAILDO EUFRASIO PEREIRA",
    "Endereço": "Rua Nonato Vieira 38", "Complemento": "", "Bairro": "AUGUSTO BRAGA", "Cidade": "SOUSA", "UF": "PB",
    "CEP": "58.808-478", "Telefone(s)": " 83 99141-0501  |   83 99139-7184", "Categoria": "MINIMERCADO",
    "Situação Documentação": "Sim", "Data de Cadastro": "29/04/2002", "Status do PDV": "Ativo", "Tipo de Pessoa": "Juridica",
    "Setor VDE": "00995", "GV VDE": "009", "Dia de Visita do VDE": "SEG/QUI", "Data da Prox Visita VDE": "13/07/2026",
    "Dia de Visita do VDI": "TER/", "Data da Prox Visita VDI": "", "Segmento NGE": "TRAD",
}
TERCA = date(2026, 11, 24)


class MontarCadastroTest(unittest.TestCase):
    def test_campos_da_dclientes(self) -> None:
        d = montar_cadastro(LINHA, None, hoje=TERCA)
        self.assertEqual(d["bairro_cidade"], "AUGUSTO BRAGA, SOUSA, PB")
        self.assertEqual(d["telefones"], ["83 99141-0501", "83 99139-7184"])
        self.assertEqual((d["setor"], d["gv"]), ("995", "9"))
        self.assertEqual(d["visita_vendedor"], "Segunda, Quinta")
        self.assertEqual(d["contato_bees"], "Terça")
        self.assertEqual((d["categoria"], d["segmento"], d["cliente_desde"]), ("MINIMERCADO", "TRAD", "29/04/2002"))

    def test_proxima_visita_vencida_e_recalculada_pelo_dia(self) -> None:
        d = montar_cadastro(LINHA, None, hoje=TERCA)
        self.assertEqual(d["proxima_visita"], "26/11/2026")  # data do relatório já passou: próxima quinta
        self.assertEqual(d["proximo_contato_bees"], "24/11/2026")  # hoje é terça
        futura = montar_cadastro({**LINHA, "Data da Prox Visita VDE": "30/11/2026"}, None, hoje=TERCA)
        self.assertEqual(futura["proxima_visita"], "30/11/2026")

    def test_documentacao_pela_base_de_documentos_ou_pela_dclientes(self) -> None:
        doc = SimpleNamespace(contrato_social="OK", comprovante_residencia="OK", rg="OK", cpf="Nok", fachada="OK")
        d = montar_cadastro(LINHA, doc, hoje=TERCA)["documentacao"]
        self.assertEqual((d["completa"], d["pendentes"]), (False, 1))
        self.assertTrue(montar_cadastro(LINHA, None, hoje=TERCA)["documentacao"]["completa"])  # "Sim" na dClientes

    def test_dias_e_proxima_data(self) -> None:
        self.assertEqual(dias_da_visita("QUI/SEG"), ["SEG", "QUI"])
        self.assertEqual(dias_da_visita(""), [])
        self.assertIsNone(proxima_data([], TERCA))

    def test_visitas_no_mes(self) -> None:
        self.assertEqual(visitas_no_mes(["SEG", "QUI"], 2026, 11), 9)  # 5 segundas + 4 quintas
        self.assertEqual(visitas_no_mes(["SEG", "QUI"], 2026, 11, desde=24), 2)  # 26 e 30


if __name__ == "__main__":
    unittest.main()
