
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.admin_liga_entrega import create_admin_liga_entrega_router
from bot_api.services.liga_entrega_expurgo_service import LigaEntregaExpurgoService
from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore
from bot_api.services.liga_entrega_status_service import LigaEntregaStatusService


class AdminLigaEntregaRoutesTest(unittest.TestCase):
    def make_client(self) -> tuple[TestClient, list[dict[str, Any]]]:
        self.tmp = TemporaryDirectory()
        events: list[dict[str, Any]] = []

        def record_security_event(_request: Any, **kwargs: Any) -> None:
            events.append(kwargs)

        app = FastAPI()
        app.include_router(
            create_admin_liga_entrega_router(
                require_admin_panel_auth=lambda **_kwargs: {"mode": "admin", "is_admin": True},
                require_admin_panel_feature=lambda _context, _feature: None,
                liga_entrega_expurgo_service=LigaEntregaExpurgoService(Path(self.tmp.name) / "expurgos.json"),
                liga_entrega_status_service=LigaEntregaStatusService(Path(self.tmp.name) / "status.json"),
                liga_entrega_report_store=LigaEntregaReportStore(Path(self.tmp.name) / "reports"),
                record_security_event=record_security_event,
                record_admin_panel_action=lambda **_kwargs: None,
            )
        )
        return TestClient(app), events

    def tearDown(self) -> None:
        tmp = getattr(self, "tmp", None)
        if tmp is not None:
            tmp.cleanup()


    def test_list_relatorios_reports_latest_stored_batches(self) -> None:
        client, events = self.make_client()
        store = LigaEntregaReportStore(Path(self.tmp.name) / "reports")
        store.store_batch(
            routine="030805_LIGA",
            files={"PATOS_21_09.csv": b"rota;valor\n1;10\n"},
            reference_date="2026-09-22",
        )

        response = client.get("/api/admin/liga-entrega/relatorios")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["summary"]["loaded"], 1)
        item = next(item for item in payload["items"] if item["routine"] == "030805_LIGA")
        self.assertTrue(item["loaded"])
        self.assertEqual(item["manifest"]["file_count"], 1)
        missing = next(item for item in payload["items"] if item["routine"] == "031120_BOT")
        self.assertFalse(missing["loaded"])
        self.assertFalse(payload["summary"]["ready"])
        self.assertEqual(payload["summary"]["total_files"], 1)
        self.assertEqual(payload["summary"]["latest_reference_date"], "2026-09-22")
        self.assertEqual(events[-1]["event_type"], "admin_liga_relatorios_list")

    def test_list_relatorios_uses_manual_upload_routine_names(self) -> None:
        client, _events = self.make_client()
        store = LigaEntregaReportStore(Path(self.tmp.name) / "reports")
        store.store_batch(
            routine="PONTOMAIS_ESPELHO",
            files={"Espelho_SET_PATOS.csv": b"matricula;nome\n1;A\n"},
            reference_date="2026-09-22",
        )
        store.store_batch(
            routine="CHECKLIST_FROTA",
            files={"Checklist Setembro.xlsx": b"xlsx"},
            reference_date="2026-09-22",
        )

        response = client.get("/api/admin/liga-entrega/relatorios")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        espelho = next(item for item in payload["items"] if item["routine"] == "PONTOMAIS_ESPELHO")
        checklist = next(item for item in payload["items"] if item["routine"] == "CHECKLIST_FROTA")
        self.assertTrue(espelho["loaded"])
        self.assertTrue(checklist["loaded"])


    def test_dashboard_calculates_rankings_and_applies_expurgos(self) -> None:
        client, events = self.make_client()
        store = LigaEntregaReportStore(Path(self.tmp.name) / "reports")
        store.store_batch(
            routine="030805_LIGA",
            files={
                "PATOS_22_09.csv": (
                    "Data;Mapa;CdMot;CdAju1;CdAju2;KmEntr;KmSai;KmPrev;TempoPrev;HrSai;HrEntr;Entregas;CxCarreg;CxEntreg\n"
                    "22092026;123;7302;7218;9999;150;100;50;10:00;07:10;17:10;10;1;1\n"
                    "22092026;124;7302;7218;0;340;200;120;10:00;07:20;17:20;10;1;1\n"
                    "22092026;125;7302;7218;0;430;340;90;10:00;07:40;17:40;10;1;1\n"
                ).encode("utf-8"),
            },
            reference_date="2026-09-22",
        )
        store.store_batch(
            routine="031120_BOT",
            files={
                "03.11.20_PATOS_SET.csv": (
                    "Fase;Mapa;DtOper;HrOper;Motorista\n"
                    "Saida;123;22/09/2026;07:10;7302\nEntrada;123;22/09/2026;17:10;7302\n"
                    "Saida;124;22/09/2026;07:20;7302\nEntrada;124;22/09/2026;17:20;7302\n"
                    "Saida;125;22/09/2026;08:00;7302\nEntrada;125;22/09/2026;18:00;7302\n"
                ).encode("utf-8"),
            },
            reference_date="2026-09-22",
        )
        store.store_batch(
            routine="031129_LIGA",
            files={
                "03.11.29_PATOS_SET.csv": (
                    "Data;Mapa;Motorista;Nome Motorista;Ajudante 1;Nome Ajudante 1;Ajudante 2;Nome Ajudante 2;Nome Superv. Rota;Placa\n"
                    "22/09/2026;123;7302;ADRIANO DINIZ PAULO;7218;MARCIO NUNES ALVES;9999;Fora da Liga;Sup;AAA1A11\n"
                    "22/09/2026;124;7302;ADRIANO DINIZ PAULO;7218;MARCIO NUNES ALVES;0;;Sup;AAA1A11\n"
                    "22/09/2026;125;7302;ADRIANO DINIZ PAULO;7218;MARCIO NUNES ALVES;0;;Sup;AAA1A11\n"
                ).encode("utf-8"),
            },
            reference_date="2026-09-22",
        )
        store.store_batch(
            routine="030237",
            files={
                "03.02.37_PATOS_SET.csv": (
                    "Status;Cliente;Dt. Operacao;Motorista;ajudante-1;ajudante-2\n"
                    "N;501;22/09/2026;7302;7218;0\nN;502;22/09/2026;7302;7218;0\n"
                ).encode("utf-8"),
            },
            reference_date="2026-09-22",
        )
        store.store_batch(
            routine="030224_AJUDANTE_LIGA",
            files={"03.02.24_PATOS_SET.csv": b"Nota;Serie;Data;Ajudante 1;Ajudante 2\n1;A;22/09/2026;7218;0\n"},
            reference_date="2026-09-22",
        )
        store.store_batch(
            routine="030224_MOTORISTA_LIGA",
            files={"03.02.24_PATOS_SET.csv": b"Nota;Serie;Data;Motorista;Cod. Cliente;Nome Cliente;Valor;Desc. Motivo;Cod. Motivo\n1;A;22/09/2026;7302;501;Cliente Um;10;Motivo;1\n"},
            reference_date="2026-09-22",
        )
        exp = client.post(
            "/api/admin/liga-entrega/expurgos",
            json={"tipo": "devolucao", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-22", "cliente": "000501", "motivo": "teste"},
        )
        self.assertEqual(exp.status_code, 200, exp.text)

        response = client.get("/api/admin/liga-entrega/dashboard", params={"competencia": "2026-09"})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["summary"]["rotas"], 3)
        self.assertEqual(payload["summary"]["devolucoes"], 0)
        self.assertEqual(payload["summary"]["devolucoes_expurgadas"], 1)
        self.assertEqual(payload["expurgos"]["items"][0]["aplicados"], 1)
        motorista = payload["rankings"]["motoristas"][0]
        self.assertEqual(motorista["cod"], "7302")
        self.assertEqual(motorista["pos"], 1)
        self.assertEqual(motorista["devol"], 0)
        self.assertEqual(motorista["expurgos"]["devolucao"], 1)
        self.assertEqual(motorista["check_pct"], 100.0)
        self.assertGreaterEqual(payload["summary"]["motoristas_ativos"], 1)
        self.assertGreaterEqual(payload["summary"]["motoristas_elegiveis"], 1)
        self.assertEqual(payload["operacao"]["rotas"], 3)
        self.assertEqual(events[-1]["event_type"], "admin_liga_dashboard")

        km_exp = client.post(
            "/api/admin/liga-entrega/expurgos",
            json={"tipo": "km", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-22", "mapa": "124", "motivo": "km incorreto"},
        )
        self.assertEqual(km_exp.status_code, 200, km_exp.text)
        recalculated = client.get("/api/admin/liga-entrega/dashboard", params={"competencia": "2026-09"}).json()
        recalculated_driver = next(row for row in recalculated["rankings"]["motoristas"] if row["cod"] == "7302")
        recalculated_helper = next(row for row in recalculated["rankings"]["ajudantes"] if row["cod"] == "7218")
        unknown_helper = next(row for row in recalculated["rankings"]["ajudantes"] if row["cod"] == "9999")
        self.assertEqual(recalculated_driver["km_desv"], 0.0)
        self.assertEqual(recalculated_driver["expurgos"]["km"], 1)
        self.assertEqual(recalculated_helper["km_desv"], 0.0)
        self.assertEqual(recalculated_helper["expurgos"]["km"], 1)
        self.assertEqual(unknown_helper["status"], "desligado")
        self.assertFalse(unknown_helper["elegivel"])

    def test_upsert_list_and_delete_expurgo(self) -> None:
        client, events = self.make_client()

        response = client.post(
            "/api/admin/liga-entrega/expurgos",
            json={
                "tipo": "km",
                "competencia": "2026-09",
                "filial": "PATOS",
                "data": "2026-09-22",
                "mapa": "12345",
                "motivo": "km digitado errado",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        item_id = response.json()["item"]["id"]

        listed = client.get("/api/admin/liga-entrega/expurgos", params={"competencia": "2026-09"})
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)

        deleted = client.delete(f"/api/admin/liga-entrega/expurgos/{item_id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(deleted.json()["item"]["active"])
        self.assertEqual([event["event_type"] for event in events], ["admin_liga_expurgo_upsert", "admin_liga_expurgos_list", "admin_liga_expurgo_delete"])

    def test_persists_monthly_team_status(self) -> None:
        client, events = self.make_client()
        response = client.put(
            "/api/admin/liga-entrega/equipe/100",
            json={"competencia": "2026-09", "status": "ferias"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["item"]["status"], "ferias")
        self.assertEqual(events[-1]["event_type"], "admin_liga_equipe_status")

    def test_dashboard_pdf_exports_the_selected_ranking(self) -> None:
        client, events = self.make_client()

        response = client.get(
            "/api/admin/liga-entrega/dashboard/pdf",
            params={"view": "motoristas", "competencia": "2026-09"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("liga-entrega-motoristas-2026-09.pdf", response.headers["content-disposition"])
        self.assertEqual(events[-1]["event_type"], "admin_liga_dashboard_pdf")

        helper_response = client.get(
            "/api/admin/liga-entrega/dashboard/pdf",
            params={"view": "ajudantes", "competencia": "2026-09"},
        )
        self.assertEqual(helper_response.status_code, 200, helper_response.text)
        self.assertTrue(helper_response.content.startswith(b"%PDF"))
        self.assertIn("liga-entrega-ajudantes-2026-09.pdf", helper_response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
