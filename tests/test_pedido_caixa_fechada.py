from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_pedidos import create_admin_pedidos_router
from bot_api.services.pedido_caixa_fechada import exige_caixa_fechada

ADMIN = {"is_admin": True, "username": "gerente"}


class RegraTest(unittest.TestCase):
    def test_600_retornavel_exige_caixa(self) -> None:
        for descricao in ("SKOL 600ML", "ANTARCTICA PILSEN 600", "STELLA ARTOIS 600 ML", "BUDWEISER 600ML"):
            self.assertTrue(exige_caixa_fechada(descricao), descricao)
        self.assertTrue(exige_caixa_fechada("SKOL 600ML", "DZ"))

    def test_litrao_em_duzia_nao_trava(self) -> None:
        # O litrão também vem em DZ na grade, mas a caixa dele é de 1 dúzia.
        self.assertFalse(exige_caixa_fechada("BRAHMA CHOPP GFA VD 1L COM TTC", "DZ"))
        self.assertFalse(exige_caixa_fechada("SKOL LITRAO 1L", "DZ"))

    def test_o_que_ja_sai_em_caixa_fica_livre(self) -> None:
        for descricao in ("SPATEN N ONE WAY 600M", "KAS GUARANA MARACUJA PET 600ML CAIXA C/24", "SKOL LATA 350ML", "BRAHMA 1600 ML", "SKOL 300ML"):
            self.assertFalse(exige_caixa_fechada(descricao), descricao)


class _Linha(SimpleNamespace):
    def __getattr__(self, _nome: str) -> str:
        return ""


def _app() -> tuple[TestClient, MagicMock]:
    jobs = MagicMock()
    jobs.get_pedido_digitacao_config.return_value = {"motivos": ["Fora de rota"], "max_caixas_por_produto": 999, "limites_por_produto": [], "horario_bloqueio": ""}
    jobs.enqueue_job.return_value = {"id": "job-1"}
    dclientes = MagicMock()
    dclientes.search_by_registration.return_value = [_Linha(filial="3", cod_pdv="100", vendedor="101")]
    inadimplencia = MagicMock()
    inadimplencia.search_by_registration.return_value = []
    estoque = MagicMock()
    estoque.availability.return_value = {"ready": True, "ok": True, "produtos": {
        "982": {"descricao": "SKOL 600ML", "unidade": "DZ"},
        "21668": {"descricao": "SPATEN N ONE WAY 600M", "unidade": "CX"},
        "1695": {"descricao": "BRAHMA CHOPP GFA VD 1L COM TTC", "unidade": "DZ"},
    }}
    app = FastAPI()
    app.include_router(create_admin_pedidos_router(
        require_admin_panel_auth=lambda **_k: dict(ADMIN), require_admin_panel_feature=lambda *_a: None,
        dclientes_query_service=dclientes, inadimplencia_query_service=inadimplencia,
        cora_estoque_query_service=estoque, promax_jobs_service=jobs, record_security_event=lambda *_a, **_k: None,
    ))
    return TestClient(app), jobs


def _pedido(quantidade: int, produto: str = "982", **extra) -> dict:
    return {"filial": "3", "cliente": "100", "motivo_digitacao": "Fora de rota", "itens": [{"produto": produto, "quantidade": quantidade, "preco": "90,00"}], **extra}


class DigitacaoTest(unittest.TestCase):
    def test_venda_de_600_com_duzia_impar_e_recusada(self) -> None:
        cliente, jobs = _app()
        resposta = cliente.post("/api/admin/pedidos/jobs", json=_pedido(3))
        self.assertEqual(resposta.status_code, 422)
        self.assertIn("caixa fechada", resposta.json()["detail"])
        self.assertIn("2 ou 4", resposta.json()["detail"])
        jobs.enqueue_job.assert_not_called()

    def test_bonificacao_de_600_tambem_trava(self) -> None:
        cliente, jobs = _app()
        self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=_pedido(1, operacao="2")).status_code, 422)
        self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=_pedido(2, operacao="2")).status_code, 202)

    def test_duzias_pares_e_one_way_passam(self) -> None:
        cliente, jobs = _app()
        self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=_pedido(4)).status_code, 202)
        self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=_pedido(3, produto="21668")).status_code, 202)
        self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=_pedido(3, produto="1695")).status_code, 202)


if __name__ == "__main__":
    unittest.main()
