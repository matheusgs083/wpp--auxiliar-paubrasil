from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from bot_api.services.clientes_escopo import EscopoClientes
from bot_api.services.ficha_cliente_blocos import ClienteAutorizado, Fontes, bloco_credito


class CondicaoFichaTest(TestCase):
    def setUp(self):
        self.cliente = ClienteAutorizado("3", "10", SimpleNamespace(cond_pag_atual="605", limite_credito="100"), EscopoClientes(irrestrito=True))
        self.prazo = Mock()
        self.prazo.search_by_registration.return_value = []
        self.condicoes = Mock()

    def consultar(self):
        return bloco_credito(self.cliente, Fontes(dclientes=None, inadimplencia=None, prazo_limite=self.prazo, condicoes=self.condicoes), date(2026, 11, 25))["dados"]

    def test_descricao_e_taxa_da_filial(self):
        self.condicoes.consultar_condicao.return_value = {"descricao": "BOLETO 5 DIAS", "taxa_mensal_adf": "006,11", "dias_primeiro_vencimento": "10"}
        dados = self.consultar()
        self.condicoes.consultar_condicao.assert_called_once_with("3", "605")
        self.assertEqual((dados["condicao_pagamento_nome"], dados["adf_condicao"]), ("BOLETO 5 DIAS", "2,00%"))

    def test_catalogo_indisponivel_preserva_codigo(self):
        self.condicoes.consultar_condicao.side_effect = RuntimeError("fora do ar")
        dados = self.consultar()
        self.assertEqual((dados["condicao_pagamento"], dados["condicao_pagamento_nome"], dados["adf_condicao"]), ("605", "", ""))

    def test_taxa_zero_nao_e_ausente(self):
        self.condicoes.consultar_condicao.return_value = {"descricao": "DINHEIRO", "taxa_mensal_adf": "000,00", "dias_primeiro_vencimento": "0"}
        self.assertEqual(self.consultar()["adf_condicao"], "0,00%")
