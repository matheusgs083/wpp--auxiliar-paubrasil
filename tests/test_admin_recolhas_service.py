from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException

from bot_api.services.admin_recolhas_service import AdminRecolhasService
from bot_api.services.recolha_request_service import RecolhaRequestService


class FakeComodatosService:
    def pending_comodato_keys_for_clients(self, _clients: list[tuple[str, str]]) -> set[tuple[str, str, str]]:
        return set()


class FakeAccessControl:
    def get_user(self, _number: str) -> dict[str, str]:
        return {"name": "Usuario Teste"}


class FakeGiroService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def list_recolha_opportunities(self, **kwargs: Any) -> list[Any]:
        self.calls.append(kwargs)
        return []

    def list_recolha_filter_options(self, **kwargs: Any) -> dict[str, list[Any]]:
        self.calls.append(kwargs)
        return {"operations": []}


class AdminRecolhasServiceTest(unittest.TestCase):
    def make_service(self, csv_path: Path) -> AdminRecolhasService:
        return AdminRecolhasService(
            recolha_request_service=RecolhaRequestService(csv_path),
            giro_query_service=FakeGiroService(),
            comodatos_query_service=FakeComodatosService(),
            access_control=FakeAccessControl(),
            filial_labels={"3": "Patos", "4": "Sume"},
            panel_context_has_all_filiais=lambda context: "*" in tuple(context.get("filiais", ())) if context else False,
            panel_context_is_critica_only=lambda context: str(context.get("mode") or "") == "critica" if context else False,
            copy_upload_with_limit=lambda upload, buffer: buffer.write(upload.file.read()),
        )

    def test_list_recolhas_filters_by_allowed_filial(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp) / "recolhas.csv")
            service.recolha_request_service.create_request(
                solicitante="5583",
                revenda="3",
                data="15/06/2026",
                setor="400",
                cidade="Patos",
                rn="400",
                nb="9845",
                comodato="Comodato 10",
                created_at=datetime(2026, 6, 15, 8, 0),
            )
            service.recolha_request_service.create_request(
                solicitante="5583",
                revenda="4",
                data="15/06/2026",
                setor="500",
                cidade="Sume",
                rn="500",
                nb="1111",
                comodato="Comodato 20",
                created_at=datetime(2026, 6, 15, 9, 0),
            )

            payload = service.list_recolhas({"mode": "financeiro", "is_admin": False, "filiais": ["3"]})

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["operations"][0]["revenda"], "3")
        self.assertEqual(payload["operations"][0]["records"][0]["solicitante_nome"], "Usuario Teste")

    def test_export_recolhas_csv_filters_by_created_period(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp) / "recolhas.csv")
            service.recolha_request_service.create_request(
                solicitante="5583",
                revenda="3",
                data="14/06/2026",
                setor="400",
                cidade="Patos",
                rn="400",
                nb="9845",
                comodato="Comodato 10",
                created_at=datetime(2026, 6, 14, 8, 0),
            )
            service.recolha_request_service.create_request(
                solicitante="5583",
                revenda="3",
                data="15/06/2026",
                setor="400",
                cidade="Patos",
                rn="400",
                nb="9846",
                comodato="Comodato 11",
                created_at=datetime(2026, 6, 15, 8, 0),
            )

            csv_bytes, total, filename = service.export_recolhas_csv(
                {"mode": "financeiro", "is_admin": False, "filiais": ["3"]},
                start_date="2026-06-15",
                end_date="2026-06-15",
            )

        exported = csv_bytes.decode("utf-8-sig")
        self.assertEqual(total, 1)
        self.assertIn("9846", exported)
        self.assertNotIn("9845", exported)
        self.assertTrue(filename.startswith("relatorio_recolhas_"))

    def test_update_recolha_denies_record_outside_filial_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp) / "recolhas.csv")
            record = service.recolha_request_service.create_request(
                solicitante="5583",
                revenda="4",
                data="15/06/2026",
                setor="500",
                cidade="Sume",
                rn="500",
                nb="1111",
                comodato="Comodato 20",
                created_at=datetime(2026, 6, 15, 9, 0),
            )

            with self.assertRaises(HTTPException) as raised:
                service.update_recolha(
                    record.id,
                    SimpleNamespace(status_caixa_noturno="Recolhido", motivo_caixa_noturno=None),
                    {"mode": "financeiro", "is_admin": False, "filiais": ["3"]},
                )

        self.assertEqual(raised.exception.status_code, 403)

    def test_update_recolha_requires_detail_for_partial_collection(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp) / "recolhas.csv")
            record = service.recolha_request_service.create_request(
                solicitante="5583",
                revenda="3",
                data="15/06/2026",
                setor="400",
                cidade="Patos",
                rn="400",
                nb="9845",
                comodato="Comodato 10",
                created_at=datetime(2026, 6, 15, 8, 0),
            )

            with self.assertRaises(HTTPException) as raised:
                service.update_recolha(
                    record.id,
                    SimpleNamespace(status_caixa_noturno="Nao Recolhido", motivo_caixa_noturno="Recolha parcial"),
                    {"mode": "financeiro", "is_admin": False, "filiais": ["3"]},
                )

            self.assertEqual(raised.exception.status_code, 400)
            result = service.update_recolha(
                record.id,
                SimpleNamespace(
                    status_caixa_noturno="Nao Recolhido",
                    motivo_caixa_noturno="Recolha parcial: 2 caixas litrinho",
                ),
                {"mode": "financeiro", "is_admin": False, "filiais": ["3"]},
            )

        self.assertEqual(result["record"]["motivo_caixa_noturno"], "Recolha parcial: 2 caixas litrinho")


if __name__ == "__main__":
    unittest.main()
