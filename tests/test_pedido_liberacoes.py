from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot_api.routes.admin_pedidos import create_admin_pedidos_router
from bot_api.routes.admin_pedidos_liberacoes import create_admin_pedidos_liberacoes_router
from bot_api.services.pedido_liberacoes_service import FUSO, PedidoLiberacoesService

ADMIN = {"is_admin": True, "username": "gerente"}
VENDEDOR = {"is_admin": False, "username": "rn101", "seller_scopes": ["3-101"], "features": ("pedidos",)}


class _Relogio:
    def __init__(self, quando: datetime) -> None:
        self.quando = quando

    def __call__(self) -> datetime:
        return self.quando


def _servico(pasta: str, relogio: _Relogio) -> PedidoLiberacoesService:
    return PedidoLiberacoesService(Path(pasta) / "liberacoes.json", agora=relogio)


class ServicoTest(unittest.TestCase):
    def test_liberacao_vale_ate_o_fim_do_ultimo_dia(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            relogio = _Relogio(datetime(2026, 11, 24, 15, 0, tzinfo=FUSO))
            servico = _servico(pasta, relogio)
            registro = servico.liberar("03", "0016883", nome="MERCADO", motivo="Acordo de pagamento", dias=3, actor="gerente")
            self.assertEqual((registro["filial"], registro["cliente"], registro["valida_ate"]), ("3", "16883", "2026-11-26"))
            relogio.quando = datetime(2026, 11, 26, 23, 59, tzinfo=FUSO)
            self.assertIsNotNone(servico.ativa("3", "16883"))
            relogio.quando = datetime(2026, 11, 27, 0, 1, tzinfo=FUSO)
            self.assertIsNone(servico.ativa("3", "16883"))
            self.assertEqual(servico.listar(), {})

    def test_um_dia_e_so_hoje_e_revogar_remove(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            servico = _servico(pasta, _Relogio(datetime(2026, 11, 24, 8, 0, tzinfo=FUSO)))
            self.assertEqual(servico.liberar("3", "10", nome="", motivo="Pagou hoje", dias=1, actor="a")["valida_ate"], "2026-11-24")
            self.assertTrue(servico.revogar("3", "10"))
            self.assertFalse(servico.revogar("3", "10"))
            self.assertIsNone(servico.ativa("3", "10"))

    def test_recusa_prazo_e_motivo_invalidos(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            servico = _servico(pasta, _Relogio(datetime(2026, 11, 24, 8, 0, tzinfo=FUSO)))
            with self.assertRaises(ValueError):
                servico.liberar("3", "10", nome="", motivo="ok ok", dias=30, actor="a")
            with self.assertRaises(ValueError):
                servico.liberar("3", "10", nome="", motivo="  ", dias=1, actor="a")


def _auth(context):
    return lambda **_kwargs: dict(context)


def _feature(context, feature):
    if not context.get("is_admin") and feature not in context.get("features", ()):
        raise HTTPException(status_code=403, detail="Sem permissão.")


def _resumo(filial: str, cliente: str, nome: str) -> SimpleNamespace:
    return SimpleNamespace(filial=filial, cod_pdv=cliente, nome=nome, title_count=2, total_pendente="1870,00")


class RotasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = tempfile.TemporaryDirectory()
        self.servico = _servico(self.pasta.name, _Relogio(datetime(2026, 11, 24, 15, 0, tzinfo=FUSO)))
        self.inadimplencia = MagicMock()
        self.inadimplencia.count_clients_in_scope.return_value = 2
        self.inadimplencia.list_client_summaries_in_scope.return_value = [_resumo("3", "100", "MERCADO A"), _resumo("3", "200", "MERCADO B")]

    def tearDown(self) -> None:
        self.pasta.cleanup()

    def _app(self, context: dict[str, Any]) -> TestClient:
        app = FastAPI()
        app.include_router(create_admin_pedidos_liberacoes_router(
            require_admin_panel_auth=_auth(context), require_admin_panel_feature=_feature,
            inadimplencia_query_service=self.inadimplencia, pedido_liberacoes_service=self.servico,
            record_security_event=lambda *_a, **_k: None,
        ))
        return TestClient(app)

    def test_admin_lista_os_bloqueados_da_filial(self) -> None:
        dados = self._app(ADMIN).get("/api/admin/pedidos/gerencial/bloqueados", params={"filial": "3"}).json()
        self.assertEqual([c["cliente"] for c in dados["clientes"]], ["100", "200"])
        self.assertEqual(dados["total"], 2)
        self.assertEqual(self.inadimplencia.list_client_summaries_in_scope.call_args.kwargs["allowed_sectors"], ["filial:3"])

    def test_admin_libera_e_a_lista_mostra(self) -> None:
        cliente = self._app(ADMIN)
        resposta = cliente.post("/api/admin/pedidos/gerencial/liberacoes", json={"filial": "3", "cliente": "100", "nome": "MERCADO A", "motivo": "Acordo de pagamento", "dias": 3})
        self.assertEqual(resposta.status_code, 201, resposta.text)
        dados = cliente.get("/api/admin/pedidos/gerencial/bloqueados").json()
        self.assertEqual(dados["clientes"][0]["liberacao"]["valida_ate"], "2026-11-26")
        self.assertIsNone(dados["clientes"][1]["liberacao"])
        self.assertEqual(len(dados["liberacoes"]), 1)
        self.assertEqual(cliente.delete("/api/admin/pedidos/gerencial/liberacoes/3/100").status_code, 200)
        self.assertEqual(cliente.delete("/api/admin/pedidos/gerencial/liberacoes/3/100").status_code, 404)

    def test_vendedor_nao_ve_nem_libera(self) -> None:
        cliente = self._app(VENDEDOR)
        self.assertEqual(cliente.get("/api/admin/pedidos/gerencial/bloqueados").status_code, 403)
        resposta = cliente.post("/api/admin/pedidos/gerencial/liberacoes", json={"filial": "3", "cliente": "100", "motivo": "Acordo", "dias": 1})
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.servico.listar(), {})


class _Linha(SimpleNamespace):
    def __getattr__(self, _nome: str) -> str:
        return ""


class PedidoDoClienteLiberadoTest(unittest.TestCase):
    def _app(self, servico: PedidoLiberacoesService) -> tuple[TestClient, MagicMock]:
        jobs = MagicMock()
        jobs.get_pedido_digitacao_config.return_value = {"motivos": ["Fora de rota"], "max_caixas_por_produto": 99, "limites_por_produto": [], "horario_bloqueio": ""}
        jobs.enqueue_job.return_value = {"id": "job-1"}
        dclientes = MagicMock()
        dclientes.search_by_registration.return_value = [_Linha(filial="3", cod_pdv="100", vendedor="101", nome_fantasia="MERCADO A")]
        inadimplencia = MagicMock()
        inadimplencia.search_by_registration.return_value = [_Linha(nota_fiscal="1", data_vencimento="01/11/2026", valor_pendente="10,00", dias="23")]
        estoque = MagicMock()
        estoque.availability.return_value = {"ready": True, "ok": True}
        app = FastAPI()
        app.include_router(create_admin_pedidos_router(
            require_admin_panel_auth=_auth(VENDEDOR), require_admin_panel_feature=_feature,
            dclientes_query_service=dclientes, inadimplencia_query_service=inadimplencia,
            cora_estoque_query_service=estoque, promax_jobs_service=jobs,
            record_security_event=lambda *_a, **_k: None, pedido_liberacoes_service=servico,
        ))
        return TestClient(app), jobs

    def test_vendedor_digita_para_cliente_liberado_e_nao_para_bloqueado(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            servico = _servico(pasta, _Relogio(datetime.now(FUSO)))
            cliente, jobs = self._app(servico)
            pedido = {"filial": "3", "cliente": "100", "motivo_digitacao": "Fora de rota", "itens": [{"produto": "1001", "quantidade": 1, "preco": "10,00"}]}
            self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=pedido).status_code, 409)
            self.assertFalse(cliente.get("/api/admin/pedidos/clientes/3/100").json()["cliente"]["pedido_liberado"])
            servico.liberar("3", "100", nome="MERCADO A", motivo="Acordo de pagamento", dias=1, actor="gerente")
            detalhe = cliente.get("/api/admin/pedidos/clientes/3/100").json()["cliente"]
            self.assertTrue(detalhe["pedido_liberado"])
            self.assertEqual(detalhe["inadimplencia"]["liberacao"]["liberado_por"], "gerente")
            self.assertEqual(cliente.post("/api/admin/pedidos/jobs", json=pedido).status_code, 202)
            enviado = jobs.enqueue_job.call_args.kwargs["payload"]["digitacao"]["pedidos"][0]
            self.assertEqual(enviado["liberacao_inadimplencia"], "gerente")


if __name__ == "__main__":
    unittest.main()
