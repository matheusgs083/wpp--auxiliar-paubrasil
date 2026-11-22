from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_pedidos import create_admin_pedidos_router
from bot_api.services.pedido_horario_bloqueio import FUSO_PEDIDOS, situacao_bloqueio

VENDEDOR = {"is_admin": False, "username": "rn101", "seller_scopes": ["3-101"]}
ADMIN = {"is_admin": True, "username": "gerente"}

PEDIDO = {
    "filial": "3",
    "cliente": "1234",
    "itens": [{"produto": "1001", "quantidade": 2, "preco": "10,00"}],
    "motivo_digitacao": "Fora de rota",
}


class FakePromaxJobs:
    def __init__(self, horario_bloqueio: str) -> None:
        self.config = {
            "motivos": ["Fora de rota"],
            "max_caixas_por_produto": 99_999,
            "limites_por_produto": [],
            "horario_bloqueio": horario_bloqueio,
            "updated_by": "",
            "updated_at": None,
        }
        self.updates: list[dict[str, Any]] = []
        self.enqueue_job = MagicMock(return_value={"id": "job-1"})

    def get_pedido_digitacao_config(self) -> dict[str, Any]:
        return dict(self.config)

    def update_pedido_digitacao_config(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        self.config.update(horario_bloqueio=kwargs["horario_bloqueio"], motivos=kwargs["motivos"])
        return dict(self.config)


def _relogio(hora: int, minuto: int):
    agora = datetime(2026, 11, 23, hora, minuto, tzinfo=FUSO_PEDIDOS)
    return patch(
        "bot_api.routes.admin_pedidos.situacao_bloqueio",
        side_effect=lambda horario: situacao_bloqueio(horario, agora),
    )


def _cliente(context: dict[str, Any], jobs: FakePromaxJobs) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_admin_pedidos_router(
            require_admin_panel_auth=lambda **_kwargs: dict(context),
            require_admin_panel_feature=lambda _context, _feature: None,
            dclientes_query_service=MagicMock(),
            inadimplencia_query_service=MagicMock(),
            cora_estoque_query_service=MagicMock(),
            promax_jobs_service=jobs,
            record_security_event=lambda *_args, **_kwargs: None,
        )
    )
    return TestClient(app)


class HorarioBloqueioRoutesTest(unittest.TestCase):
    def test_vendedor_nao_envia_pedido_depois_do_horario(self) -> None:
        jobs = FakePromaxJobs("17:30")
        with _relogio(18, 0):
            response = _cliente(VENDEDOR, jobs).post("/api/admin/pedidos/jobs", json=PEDIDO)

        self.assertEqual(response.status_code, 409)
        self.assertIn("encerrada às 17:30", response.json()["detail"])
        jobs.enqueue_job.assert_not_called()

    def test_config_informa_bloqueio_para_vendedor_e_liberacao_para_admin(self) -> None:
        jobs = FakePromaxJobs("17:30")
        with _relogio(18, 0):
            vendedor = _cliente(VENDEDOR, jobs).get("/api/admin/pedidos/config").json()
            admin = _cliente(ADMIN, jobs).get("/api/admin/pedidos/config").json()

        self.assertTrue(vendedor["bloqueado"])
        self.assertFalse(vendedor["pode_ignorar_bloqueio"])
        self.assertTrue(admin["bloqueado"])
        self.assertTrue(admin["pode_ignorar_bloqueio"])

    def test_config_antes_do_horario_traz_contagem(self) -> None:
        jobs = FakePromaxJobs("17:30")
        with _relogio(17, 0):
            payload = _cliente(VENDEDOR, jobs).get("/api/admin/pedidos/config").json()

        self.assertFalse(payload["bloqueado"])
        self.assertEqual(payload["segundos_ate_bloqueio"], 1800)

    def test_gerencial_salva_horario_e_recusa_formato_invalido(self) -> None:
        jobs = FakePromaxJobs("")
        cliente = _cliente(ADMIN, jobs)
        corpo = {"motivos": ["Fora de rota"], "max_caixas_por_produto": 50, "limites_por_produto": []}

        invalido = cliente.put("/api/admin/pedidos/gerencial/config", json={**corpo, "horario_bloqueio": "25:00"})
        self.assertEqual(invalido.status_code, 422)
        self.assertEqual(jobs.updates, [])

        with _relogio(10, 0):
            salvo = cliente.put("/api/admin/pedidos/gerencial/config", json={**corpo, "horario_bloqueio": "9:30"})
        self.assertEqual(salvo.status_code, 200)
        self.assertEqual(jobs.updates[0]["horario_bloqueio"], "09:30")
        self.assertEqual(salvo.json()["horario_bloqueio"], "09:30")


if __name__ == "__main__":
    unittest.main()
