"""Integração opcional com PostgreSQL isolado (GV_TEST_DATABASE_URL)."""
import os
import unittest

import psycopg

from bot_api.services.gerentes_vendas_service import GerentesVendasService


@unittest.skipUnless(os.getenv("GV_TEST_DATABASE_URL"), "PostgreSQL de teste não configurado")
class GerentesPostgresTest(unittest.TestCase):
    def test_cadastro_e_catalogo(self):
        url = os.environ["GV_TEST_DATABASE_URL"]
        with psycopg.connect(url) as conn:
            conn.execute("CREATE SCHEMA reports")
            conn.execute("CREATE TABLE reports.dsetores_latest (filial text, gv text, setor text)")
            conn.execute("INSERT INTO reports.dsetores_latest VALUES ('3','2','107'), ('3','2','108'), ('4','1','109'), ('3','99','999')")
        service = GerentesVendasService(url)
        service.salvar({"3_2": "Maria", "4_1": "Maria"})
        self.assertEqual(service.nomes(), {"3_2": "Maria", "4_1": "Maria"})
        itens = {item["chave"]: item for item in service.catalogo()}
        self.assertEqual(itens["3_2"]["setores"], 2)
        self.assertEqual(itens["3_99"]["nome"], "Tratamento")
        service.salvar({"3_2": ""})
        self.assertNotIn("3_2", service.nomes())
