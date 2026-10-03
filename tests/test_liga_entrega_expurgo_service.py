
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bot_api.services.liga_entrega_expurgo_service import LigaEntregaExpurgoService
from bot_api.services.liga_entrega_dashboard_service import match_dev_exp, matching_route_expurgos


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

    def test_team_devolucao_keeps_cliente_and_never_becomes_daily_expurgo(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            with self.assertRaisesRegex(ValueError, "Cliente obrigatorio"):
                service.upsert_expurgo(
                    {"tipo": "devolucao", "escopo": "equipe", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23"}
                )
            item = service.upsert_expurgo(
                {"tipo": "devolucao", "escopo": "equipe", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23", "cliente": "501"}
            )
            self.assertEqual(item["cliente"], "501")

    def test_legacy_team_devolucao_without_cliente_is_not_applied_broadly(self) -> None:
        dev = {"data": "2026-09-23", "filial": "PATOS", "cliente_cod": "502"}
        legacy = {"tipo": "devolucao", "escopo": "equipe", "data": "2026-09-23", "filial": "PATOS", "cliente": ""}
        targeted = {"tipo": "devolucao", "escopo": "equipe", "data": "2026-09-23", "filial": "PATOS", "cliente": "502"}

        self.assertIsNone(match_dev_exp(dev, [legacy]))
        self.assertEqual(match_dev_exp(dev, [targeted]), targeted)

    def test_tml_can_be_registered_for_the_whole_day_without_map(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            item = service.upsert_expurgo(
                {"tipo": "tml", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23", "motivo": "TML do dia inteiro"},
                actor="admin",
            )

            self.assertEqual(item["mapa"], "")
            self.assertEqual(service.list_expurgos(competencia="2026-09", tipo="tml")["total"], 1)

    def test_team_scope_preserves_optional_route_target_for_operational_indicators(self) -> None:
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
                    "motivo": "KM da equipe do mapa",
                },
                actor="admin",
            )

            self.assertEqual(item["escopo"], "equipe")
            self.assertEqual(item["mapa"], "999")
            self.assertEqual(item["cliente"], "")

    def test_invalid_scope_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            service = LigaEntregaExpurgoService(Path(tmp) / "expurgos.json")
            with self.assertRaisesRegex(ValueError, "Escopo"):
                service.upsert_expurgo(
                    {"tipo": "tml", "escopo": "todos", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23"}
                )

    def test_route_matching_respects_scope_and_competence(self) -> None:
        route = {"data": "2026-09-23", "filial": "PATOS", "mapa": "999"}
        individual_without_map = {"tipo": "km", "escopo": "individual", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23", "mapa": ""}
        team_day = {"tipo": "km", "escopo": "equipe", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23", "mapa": ""}
        wrong_competence = {"tipo": "km", "escopo": "equipe", "competencia": "2026-10", "filial": "PATOS", "data": "2026-09-23", "mapa": ""}

        matches = matching_route_expurgos(route, [individual_without_map, team_day, wrong_competence], {"km"})

        self.assertEqual(matches, [team_day])

    def test_multiple_matching_route_expurgos_are_counted(self) -> None:
        route = {"data": "2026-09-23", "filial": "PATOS", "mapa": "999"}
        km = {"tipo": "km", "escopo": "equipe", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23", "mapa": "999"}
        dispersao = {"tipo": "dispersao", "escopo": "equipe", "competencia": "2026-09", "filial": "PATOS", "data": "2026-09-23", "mapa": "999"}

        matches = matching_route_expurgos(route, [km, dispersao], {"km", "dispersao"})

        self.assertEqual(matches, [km, dispersao])


if __name__ == "__main__":
    unittest.main()
