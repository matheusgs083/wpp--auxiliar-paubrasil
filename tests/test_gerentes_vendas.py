import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from bot_api.routes.admin_gerentes_vendas import create_admin_gerentes_vendas_router
from bot_api.services.gerentes_vendas_service import agrupar_gerentes, nome_padrao
from bot_api.services.rota_financeira_query_service import RotaFinanceiraQueryService


class GerentesVendasTest(unittest.TestCase):
    def test_agrupa_nomes_ignorando_caixa_e_acentos_e_99(self):
        grupos = agrupar_gerentes(["3_2", "1_1", "3_99", "1_99"], {"3_2": "Maria", "1_1": "MARÍA"})
        self.assertEqual(sorted(len(g["chaves"]) for g in grupos), [2, 2])
        self.assertEqual(nome_padrao("3_99"), "Tratamento")

    def test_omite_gvs_sem_nome_e_separa_99_como_tratamento(self):
        grupos = agrupar_gerentes(["3_2", "4_1", "3_5", "3_99", "4_99"], {"3_2": "Maria", "4_1": "MARIA", "3_99": "Outro nome"})
        self.assertEqual(len(grupos), 2)
        gerente = next(item for item in grupos if not item["tratamento"])
        tratamento = next(item for item in grupos if item["tratamento"])
        self.assertEqual(set(gerente["chaves"]), {"3_2", "4_1"})
        self.assertEqual(tratamento["nome"], "Tratamento")
        self.assertEqual(set(tratamento["chaves"]), {"3_99", "4_99"})

    def test_somente_administrador_pode_ler_e_salvar(self):
        service = Mock()
        service.catalogo.return_value = [{"chave": "3_2"}]
        for is_admin in (False, True):
            app = FastAPI()
            app.include_router(create_admin_gerentes_vendas_router(service=service, require_admin_panel_auth=lambda **kwargs: {"is_admin": is_admin}))
            client = TestClient(app)
            self.assertEqual(client.get("/api/admin/gerentes-vendas").status_code, 200 if is_admin else 403)
            self.assertEqual(client.put("/api/admin/gerentes-vendas", json={"nomes": {"3_2": "Maria"}}).status_code, 200 if is_admin else 403)
            if is_admin:
                self.assertEqual(client.put("/api/admin/gerentes-vendas", json={"nomes": {"4_2": "Maria"}}).status_code, 422)

    def test_filtro_de_dois_gvs_conserva_escopo_do_usuario(self):
        service = RotaFinanceiraQueryService("", "reports")
        where, params = service._filtros_da_rota(dia="SEGUNDA", allowed_sectors=None, allowed_gv_vdes=["3_2"], filial="", gv="3_2,4_1", setor="", busca="")
        self.assertIn(" OR ", where.as_string())
        self.assertIn("3_2", params)
        self.assertIn("4_1", params)
        self.assertIn(["3_2"], params)
