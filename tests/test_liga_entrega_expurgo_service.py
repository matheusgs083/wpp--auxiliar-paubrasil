
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bot_api.services.liga_entrega_expurgo_service import LigaEntregaExpurgoService


class LigaEntregaExpurgoServiceTest(unittest.TestCase):
    def test_upsert_lists_and_soft_deletes_expurgo(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            item = service.upsert_expurgo(
                {
                    "tipo": "km",
                    "competencia": "2026-09",
                    "filial": "PATOS",
                    "data": "2026-09-22",
                    "mapa": "12345",
                    "motivo": "km digitado errado",
                },
                actor="admin",
            )

            listed = service.list_expurgos(competencia="2026-09", tipo="km")
            self.assertEqual(listed["total"], 1)
            self.assertEqual(listed["items"][0]["id"], item["id"])

            deleted = service.delete_expurgo(item["id"], actor="admin")
            self.assertFalse(deleted["active"])
            self.assertEqual(service.list_expurgos(competencia="2026-09")["total"], 0)
            self.assertEqual(service.list_expurgos(competencia="2026-09", active_only=False)["total"], 1)

    def test_key_uses_data_to_avoid_reused_map_collision(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            first = service.upsert_expurgo(
                {"tipo": "tml", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-21", "mapa": "777"},
                actor="admin",
            )
            second = service.upsert_expurgo(
                {"tipo": "tml", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-22", "mapa": "777"},
                actor="admin",
            )

            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(service.list_expurgos(competencia="2026-09", tipo="tml")["total"], 2)

    def test_devolucao_requires_cliente_and_date(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            with self.assertRaises(ValueError):
                service.upsert_expurgo({"tipo": "devolucao", "competencia": "2026-09", "filial": "PATOS"})

    def test_tml_can_be_registered_for_the_whole_day_without_map(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            item = service.upsert_expurgo(
                {"tipo": "tml", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23", "motivo": "TML do dia inteiro"},
                actor="admin",
            )

            self.assertEqual(item["mapa"], "")
            self.assertEqual(service.list_expurgos(competencia="2026-09", tipo="tml")["total"], 1)

    def test_team_scope_clears_target_and_accepts_all_indicators(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            item = service.upsert_expurgo(
                {
                    "tipo": "km",
                    "escopo": "equipe",
                    "competencia": "2026-09",
                    "filial": "PATOS",
                    "data": "2026-09-23",
                    "mapa": "999",
                    "motivo": "KM geral do dia",
                },
                actor="admin",
            )

            self.assertEqual(item["escopo"], "equipe")
            self.assertEqual(item["mapa"], "")
            self.assertEqual(item["cliente"], "")

    def test_invalid_scope_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            with self.assertRaisesRegex(ValueError, "Escopo"):
                service.upsert_expurgo(
                    {"tipo": "tml", "escopo": "todos", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23"}
                )


if __name__ == "__main__":
    unittest.main()
