from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_pedidos import create_admin_pedidos_router

VENDEDOR_PATOS = {"is_admin": False, "username": "rn101", "seller_scopes": ["3-101"]}
OPERACOES = {"is_admin": False, "username": "sup", "filiais": ["1", "4"]}
ADMIN = {"is_admin": True, "username": "gerente"}


class _Linha(SimpleNamespace):
    def __getattr__(self, _nome: str) -> str:  # campos do cadastro que o teste não usa
        return ""


def _linha(filial: str, cliente: str) -> SimpleNamespace:
    return _Linha(filial=filial, cod_pdv=cliente, nome_fantasia=f"CLIENTE {cliente}")


def _cliente(context: dict[str, Any], dclientes: Any = None) -> TestClient:
    jobs = MagicMock()
    jobs.get_pedido_digitacao_config.return_value = {"motivos": ["Fora de rota"], "horario_bloqueio": ""}
    app = FastAPI()
    app.include_router(
        create_admin_pedidos_router(
            require_admin_panel_auth=lambda **_kwargs: dict(context),
            require_admin_panel_feature=lambda _context, _feature: None,
            dclientes_query_service=dclientes or MagicMock(),
            inadimplencia_query_service=MagicMock(),
            cora_estoque_query_service=MagicMock(),
            promax_jobs_service=jobs,
            record_security_event=lambda *_args, **_kwargs: None,
        )
    )
    return TestClient(app)


class FiliaisDaCarteiraTest(unittest.TestCase):
    def _filiais(self, context: dict[str, Any]) -> list[str]:
        resposta = _cliente(context).get("/api/admin/pedidos/config")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return [item["codigo"] for item in resposta.json()["filiais"]]

    def test_config_traz_so_as_filiais_da_carteira(self) -> None:
        self.assertEqual(self._filiais(VENDEDOR_PATOS), ["3"])
        self.assertEqual(self._filiais(OPERACOES), ["1", "4"])
        self.assertEqual(self._filiais(ADMIN), ["1", "2", "3", "4", "5", "6", "7", "8"])

    def test_nome_da_filial_vem_da_drevendas(self) -> None:
        resposta = _cliente(VENDEDOR_PATOS).get("/api/admin/pedidos/config").json()
        self.assertEqual(resposta["filiais"], [{"codigo": "3", "nome": "Patos"}])

    def test_busca_em_filial_fora_da_carteira_e_recusada(self) -> None:
        dclientes = MagicMock()
        resposta = _cliente(VENDEDOR_PATOS, dclientes).get("/api/admin/pedidos/clientes", params={"busca": "mercado", "filial": "1"})
        self.assertEqual(resposta.status_code, 403)
        dclientes.search_by_fantasia.assert_not_called()

    def test_busca_por_nome_fica_na_filial_escolhida(self) -> None:
        dclientes = MagicMock()
        dclientes.search_by_fantasia.return_value = [_linha("1", "10"), _linha("4", "20")]
        resposta = _cliente(OPERACOES, dclientes).get("/api/admin/pedidos/clientes", params={"busca": "mercado", "filial": "4"})
        self.assertEqual([c["cliente"] for c in resposta.json()["clientes"]], ["20"])


if __name__ == "__main__":
    unittest.main()
