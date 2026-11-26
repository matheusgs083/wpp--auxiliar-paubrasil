from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bot_api.services.coordenadas_012012_service import Coordenadas012012Service, ler_arquivo, parse_coordenadas
from bot_api.services.ficha_cliente_blocos import ClienteAutorizado, Fontes, cabecalho
from bot_api.services.clientes_escopo import EscopoClientes

class CoordenadasTests(unittest.TestCase):
    def test_sinais_e_coordenadas_ausentes(self):
        self.assertEqual(parse_coordenadas("7,014465- / 37,286665-"), (Decimal("-7.014465"), Decimal("-37.286665")))
        self.assertEqual(parse_coordenadas("7,002058- / 37,265296+"), (Decimal("-7.002058"), Decimal("37.265296")))
        for valor in ("Sem Coordenada", "0 / 0", "999 / 10", ""):
            self.assertIsNone(parse_coordenadas(valor))

    def test_importacao_identifica_revenda_nb_e_preserva_sem_coordenadas(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "012012_relatorio_400_2210003.csv"
            path.write_text("\n00001;Razao;Fantasia;Rua;Bairro;Cidade;7,014465- / 37,286665-;A\n\n00002;R;F;R;B;C;Sem Coordenada;A\n", encoding="cp1252")
            filial, rows = ler_arquivo(path)
            self.assertEqual(filial, "3")
            self.assertEqual(rows[0], ("3", "1", Decimal("-7.014465"), Decimal("-37.286665")))
            self.assertEqual(rows[1], ("3", "2", None, None))
            connection = MagicMock()
            with patch("bot_api.services.coordenadas_012012_service.psycopg.connect", return_value=connection):
                summary = Coordenadas012012Service("postgresql://test", "reports").import_files([path])
            self.assertEqual((summary["rows"], summary["com_coordenadas"]), (2, 1))
            cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
            self.assertEqual(cursor.executemany.call_args.args[1], rows)
            self.assertTrue(any(call.args[1:] == (("3",),) for call in cursor.execute.call_args_list))

    def test_ficha_usa_coordenadas_e_faz_fallback_para_endereco(self):
        cliente = ClienteAutorizado("3", "1", SimpleNamespace(), EscopoClientes(irrestrito=True))
        cadastro = MagicMock()
        cadastro.get_payip_profile_by_registration.return_value = SimpleNamespace(endereco="Rua A", numero="1", documento="", email="", complemento="", bairro="", cidade="", uf="", cep="")
        coords = MagicMock()
        coords.buscar.return_value = {"latitude": "-7.014465", "longitude": "-37.286665"}
        fontes = Fontes(dclientes=cadastro, inadimplencia=None, coordenadas=coords)
        resultado = cabecalho(cliente, fontes, {})
        self.assertIn("-7.014465%2C-37.286665", resultado["mapa_url"])
        coords.buscar.assert_called_once_with("3", "1")
        coords.buscar.return_value = None
        self.assertIn("Rua+A", cabecalho(cliente, fontes, {})["mapa_url"])

if __name__ == "__main__":
    unittest.main()
