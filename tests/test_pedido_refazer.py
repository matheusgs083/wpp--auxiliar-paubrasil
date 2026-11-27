from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bot_api.routes.admin_pedidos import create_admin_pedidos_router

class RefazerPedidoTest(unittest.TestCase):
    def setUp(self):
        self.jobs = MagicMock()
        self.job = {"id": "00000000-0000-0000-0000-000000000001", "job_type": "digitacao_030104", "created_by": "rn101", "status": "failed", "payload": {"digitacao": {"unidade": "2210003", "pedidos": [{"ref": "p1", "cliente": "100", "motivo_digitacao": "Fora de rota", "operacao": "1", "cond_pagto": "605", "itens": [{"produto": "20", "quantidade": 2, "preco": "10,50"}]}]}}, "result": {"metadata": {"pedidos": [{"ref": "p1", "status": "recusado"}]}}}
        self.jobs.get_job.return_value = self.job
        self.jobs.list_jobs.return_value = [self.job]
        self.clientes = MagicMock()
        self.clientes.search_by_registration.return_value = [object()]
        self.precos_pb = MagicMock()
        self.precos_pb.consultar_precos.return_value = {"20": {"asr": "40.00", "sub": "35.00", "frio": "45.00"}}
        self.precos_ba = MagicMock()
        self.precos_ba.consultar_precos.return_value = {"20": {"asr": "50.00", "sub": "47.00", "frio": "55.00"}}
        estoque = MagicMock()
        estoque.availability.return_value = {"ready": True, "produtos": {"20": {"descricao": "CERVEJA", "unidade": "CX"}}}
        app = FastAPI()
        app.include_router(create_admin_pedidos_router(require_admin_panel_auth=lambda **_: {"is_admin": False, "username": "rn101", "seller_scopes": ["3-101"]}, require_admin_panel_feature=lambda *_: None, dclientes_query_service=self.clientes, inadimplencia_query_service=MagicMock(), cora_estoque_query_service=estoque, promax_jobs_service=self.jobs, dprecos_import_service=self.precos_pb, dprecos_ba_import_service=self.precos_ba, record_security_event=lambda *_a, **_k: None))
        self.client = TestClient(app)
        self.url = "/api/admin/pedidos/jobs/" + self.job["id"] + "/refazer"

    def test_refaz_com_produtos_e_dados_originais(self):
        self.assertTrue(self.client.get("/api/admin/pedidos/jobs").json()["jobs"][0]["pode_refazer"])
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        pedido = resposta.json()["pedido"]
        self.assertEqual((pedido["filial"], pedido["cliente"], pedido["cond_pagto"]), ("3", "100", "605"))
        self.assertEqual(pedido["itens"][0], {"produto": "20", "quantidade": 2, "preco": "10,50", "descricao": "CERVEJA", "unidade": "CX", "precos_referencia": {"asr": "40.00", "sub": "35.00", "frio": "45.00"}})
        self.jobs.enqueue_job.assert_not_called()

    def test_refazer_busca_tabela_atual_da_bahia(self):
        self.job["payload"]["digitacao"]["unidade"] = "3610006"
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["pedido"]["itens"][0]["precos_referencia"]["asr"], "50.00")
        self.precos_ba.consultar_precos.assert_called_once_with(["20"])
        self.precos_pb.consultar_precos.assert_not_called()
        self.assertEqual(resposta.json()["pedido"]["itens"][0]["preco"], "10,50")

    def test_refazer_preserva_valor_quando_tabela_indisponivel(self):
        self.precos_pb.consultar_precos.side_effect = RuntimeError("indisponivel")
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["precos_indisponiveis"])
        item = resposta.json()["pedido"]["itens"][0]
        self.assertEqual(item["preco"], "10,50")
        self.assertIsNone(item["precos_referencia"])

    def test_recusa_pedido_de_outro_usuario_ou_fora_da_carteira(self):
        self.job["created_by"] = "outro"
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.job["created_by"] = "rn101"
        self.clientes.search_by_registration.return_value = []
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_nao_refaz_job_ativo_concluido_ou_com_pedido_salvo(self):
        for status in ("pending", "running", "success", "cancelled"):
            self.job["status"] = status
            self.assertEqual(self.client.get(self.url).status_code, 409, status)
        self.job["status"] = "partial_success"
        self.job["result"]["metadata"]["pedidos"][0].update(status="salvo", pedido="123")
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertFalse(self.client.get("/api/admin/pedidos/jobs").json()["jobs"][0]["pode_refazer"])

if __name__ == "__main__":
    unittest.main()
