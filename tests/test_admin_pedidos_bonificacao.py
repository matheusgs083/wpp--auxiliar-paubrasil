from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_pedidos import create_admin_pedidos_router

VENDEDOR = {"is_admin": False, "username": "rn101", "seller_scopes": ["3-101"]}
ADMIN = {"is_admin": True, "username": "gerente"}

PEDIDO = {"filial": "3", "cliente": "1234", "motivo_digitacao": "Fora de rota", "itens": [{"produto": "1001", "quantidade": 2}]}


class _Linha(SimpleNamespace):
    def __getattr__(self, _nome: str) -> str:  # campos do cadastro que o teste não usa
        return ""


def _cliente(context: dict[str, Any]) -> tuple[TestClient, MagicMock]:
    jobs = MagicMock()
    jobs.get_pedido_digitacao_config.return_value = {
        "motivos": ["Fora de rota"], "max_caixas_por_produto": 99, "limites_por_produto": [], "horario_bloqueio": "",
    }
    jobs.enqueue_job.return_value = {"id": "job-1"}
    dclientes = MagicMock()
    dclientes.search_by_registration.return_value = [_Linha(
        filial="3", cod_pdv="1234", vendedor="101", gv="", cond_pag_atual="", nome_fantasia="MERCADO", razao_social="MERCADO LTDA",
    )]
    inadimplencia = MagicMock()
    inadimplencia.search_by_registration.return_value = []
    estoque = MagicMock()
    estoque.availability.return_value = {"ready": True, "ok": True}
    app = FastAPI()
    app.include_router(
        create_admin_pedidos_router(
            require_admin_panel_auth=lambda **_kwargs: dict(context),
            require_admin_panel_feature=lambda _context, _feature: None,
            dclientes_query_service=dclientes,
            inadimplencia_query_service=inadimplencia,
            cora_estoque_query_service=estoque,
            promax_jobs_service=jobs,
            record_security_event=lambda *_args, **_kwargs: None,
        )
    )
    return TestClient(app), jobs


def _pedido_enfileirado(jobs: MagicMock) -> dict[str, Any]:
    return jobs.enqueue_job.call_args.kwargs["payload"]["digitacao"]["pedidos"][0]


class BonificacaoTest(unittest.TestCase):
    def test_vendedor_nao_digita_bonificacao(self) -> None:
        cliente, jobs = _cliente(VENDEDOR)
        resposta = cliente.post("/api/admin/pedidos/jobs", json={**PEDIDO, "operacao": "2"})
        self.assertEqual(resposta.status_code, 403)
        jobs.enqueue_job.assert_not_called()

    def test_admin_digita_bonificacao_sem_preco(self) -> None:
        cliente, jobs = _cliente(ADMIN)
        itens = [{"produto": "1001", "quantidade": 2, "preco": "9,99"}]
        resposta = cliente.post("/api/admin/pedidos/jobs", json={**PEDIDO, "itens": itens, "operacao": "2"})
        self.assertEqual(resposta.status_code, 202, resposta.text)
        pedido = _pedido_enfileirado(jobs)
        self.assertEqual(pedido["operacao"], "2")
        self.assertEqual([item["preco"] for item in pedido["itens"]], [""])

    def test_venda_continua_exigindo_preco(self) -> None:
        cliente, jobs = _cliente(ADMIN)
        self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=PEDIDO).status_code, 422)
        itens = [{"produto": "1001", "quantidade": 2, "preco": "10,50"}]
        resposta = cliente.post("/api/admin/pedidos/jobs", json={**PEDIDO, "itens": itens})
        self.assertEqual(resposta.status_code, 202, resposta.text)
        self.assertEqual(_pedido_enfileirado(jobs)["operacao"], "1")

    def test_config_so_libera_bonificacao_para_admin(self) -> None:
        self.assertFalse(_cliente(VENDEDOR)[0].get("/api/admin/pedidos/config").json()["pode_bonificar"])
        self.assertTrue(_cliente(ADMIN)[0].get("/api/admin/pedidos/config").json()["pode_bonificar"])


if __name__ == "__main__":
    unittest.main()
