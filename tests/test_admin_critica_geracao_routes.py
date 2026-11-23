from __future__ import annotations

import unittest
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot_api.routes.admin_critica_geracao import _hoje, create_admin_critica_geracao_router, resumo_geracao

COM_PERMISSAO = {"is_admin": False, "mode": "usuario", "username": "ana", "features": ("gerar_critica",)}
SO_CRITICA = {"is_admin": False, "mode": "usuario", "username": "bia", "features": ("critica",)}


class FakeJobs:
    def __init__(self, jobs: list[dict[str, Any]] | None = None) -> None:
        self.jobs = list(jobs or [])
        self.enfileirados: list[dict[str, Any]] = []

    def list_jobs(self, *, statuses: Any = None, job_types: Any = None, limit: int = 50, **_: Any) -> list[dict[str, Any]]:
        itens = [
            job for job in self.jobs
            if (not statuses or job["status"] in statuses) and (not job_types or job["job_type"] in job_types)
        ]
        return itens[:limit]

    def get_queue_state(self) -> dict[str, Any]:
        return {"paused": False, "pause_reason": ""}

    def enqueue_job(self, **kwargs: Any) -> dict[str, Any]:
        self.enfileirados.append(kwargs)
        job = {"id": "novo", "job_type": kwargs["job_type"], "status": "pending", "payload": kwargs["payload"], "created_by": kwargs["created_by"]}
        self.jobs.insert(0, job)
        return job


def _app(context: dict[str, Any] | None, jobs: FakeJobs) -> TestClient:
    def auth(**_kwargs: Any) -> dict[str, Any]:
        if context is None:
            raise HTTPException(status_code=401, detail="Sessão expirada.")
        return dict(context)

    def feature(ctx: dict[str, Any] | None, nome: str) -> None:
        if not ctx or not (ctx.get("is_admin") or nome in ctx.get("features", ())):
            raise HTTPException(status_code=403, detail="Acesso nao permitido para este perfil.")

    app = FastAPI()
    app.include_router(create_admin_critica_geracao_router(
        require_admin_panel_auth=auth,
        require_admin_panel_feature=feature,
        promax_jobs_service=jobs,
        record_security_event=lambda *_args, **_kwargs: None,
    ))
    return TestClient(app)


class GerarCriticaTest(unittest.TestCase):
    def test_pede_a_critica_ao_worker(self) -> None:
        jobs = FakeJobs()
        response = _app(COM_PERMISSAO, jobs).post("/api/admin/critica/geracao", json={})
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["ja_na_fila"])
        pedido = jobs.enfileirados[0]
        self.assertEqual(pedido["job_type"], "cora_critica")
        self.assertEqual(pedido["payload"]["operation"], "critica")
        self.assertEqual(pedido["payload"]["reference_date"], _hoje().isoformat())
        self.assertEqual(pedido["created_by"], "ana")

    def test_nao_duplica_quando_ja_tem_uma_na_fila(self) -> None:
        jobs = FakeJobs([{"id": "j1", "job_type": "cora_critica", "status": "running", "payload": {}}])
        response = _app(COM_PERMISSAO, jobs).post("/api/admin/critica/geracao", json={})
        self.assertTrue(response.json()["ja_na_fila"])
        self.assertEqual(response.json()["geracao"]["id"], "j1")
        self.assertEqual(jobs.enfileirados, [])

    def test_outros_jobs_ativos_nao_bloqueiam(self) -> None:
        jobs = FakeJobs([{"id": "e1", "job_type": "cora_estoque", "status": "running", "payload": {}}])
        _app(COM_PERMISSAO, jobs).post("/api/admin/critica/geracao", json={})
        self.assertEqual(len(jobs.enfileirados), 1)

    def test_data_futura_ou_antiga_e_recusada(self) -> None:
        cliente = _app(COM_PERMISSAO, FakeJobs())
        amanha = (_hoje() + timedelta(days=1)).isoformat()
        antiga = (_hoje() - timedelta(days=40)).isoformat()
        self.assertEqual(cliente.post("/api/admin/critica/geracao", json={"data": amanha}).status_code, 422)
        self.assertEqual(cliente.post("/api/admin/critica/geracao", json={"data": antiga}).status_code, 422)

    def test_exige_permissao_gerar_critica(self) -> None:
        jobs = FakeJobs()
        self.assertEqual(_app(SO_CRITICA, jobs).post("/api/admin/critica/geracao", json={}).status_code, 403)
        self.assertEqual(_app(SO_CRITICA, jobs).get("/api/admin/critica/geracao").status_code, 403)
        self.assertEqual(_app(None, jobs).get("/api/admin/critica/geracao").status_code, 401)
        self.assertEqual(jobs.enfileirados, [])

    def test_situacao_mostra_andamento_e_historico_so_da_critica(self) -> None:
        jobs = FakeJobs([
            {"id": "j2", "job_type": "cora_critica", "status": "pending", "payload": {"reference_date": "2026-11-23"}},
            {"id": "e1", "job_type": "cora_estoque", "status": "success", "payload": {}},
            {"id": "j1", "job_type": "cora_critica", "status": "success", "payload": {"reference_date": "2026-11-22"},
             "result": {"rows": 900, "imports": [{"filial": "3"}, {"filial": "1"}]}},
        ])
        dados = _app(COM_PERMISSAO, jobs).get("/api/admin/critica/geracao").json()
        self.assertEqual(dados["em_andamento"]["id"], "j2")
        self.assertEqual([item["id"] for item in dados["historico"]], ["j2", "j1"])
        self.assertEqual(dados["historico"][1]["filiais"], ["1", "3"])
        self.assertEqual(dados["historico"][1]["linhas"], 900)

    def test_resumo_nao_expoe_dados_do_worker(self) -> None:
        resumo = resumo_geracao({
            "id": "j", "status": "failed", "payload": {"target_worker_id": "pc-1"}, "lease_token": "segredo",
            "failure_reason": "Login no Cora falhou",
        })
        self.assertEqual(resumo["situacao"], "Falhou")
        self.assertEqual(resumo["erro"], "Login no Cora falhou")
        self.assertNotIn("segredo", str(resumo))
        self.assertNotIn("pc-1", str(resumo))


if __name__ == "__main__":
    unittest.main()
