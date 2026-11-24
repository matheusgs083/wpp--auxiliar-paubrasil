from __future__ import annotations

import unittest

from bot_api.services.liga_entrega_dashboard_service import (
    apply_route_team_overrides_to_routes,
    rebuild_route_delivery_facts,
)


class _RouteTeamOverrides:
    def __init__(self, motorista: str, ajudantes: list[str]) -> None:
        self.motorista = motorista
        self.ajudantes = ajudantes

    def list_overrides(self, *, competencia: str) -> list[dict[str, object]]:
        self.asserted_competencia = competencia
        return [{
            "id": 1,
            "active": True,
            "data": "2026-11-23",
            "filial": "PATOS",
            "mapa": "96854",
            "motorista": self.motorista,
            "ajudantes": self.ajudantes,
        }]


class LigaRouteTeamRebalanceTest(unittest.TestCase):
    def test_moves_deliveries_to_adjusted_team_without_accumulating_previous_adjustment(self) -> None:
        route = {
            "data": "2026-11-23",
            "filial": "PATOS",
            "mapa": "96854",
            "mot": "7001",
            "aju": ["8001"],
            "entregas": 27,
        }
        facts: dict[str, object] = {"ent_m": {"7001": 27}, "ent_a": {"8001": 27}}

        first = _RouteTeamOverrides("7002", ["8002"])
        self.assertEqual(apply_route_team_overrides_to_routes([route], first, "2026-11"), 1)
        ent_m, ent_a = rebuild_route_delivery_facts([route], facts)
        self.assertEqual(ent_m, {"7001": 0, "7002": 27})
        self.assertEqual(ent_a, {"8001": 0, "8002": 27})

        second = _RouteTeamOverrides("7003", ["8003"])
        self.assertEqual(apply_route_team_overrides_to_routes([route], second, "2026-11"), 1)
        ent_m, ent_a = rebuild_route_delivery_facts([route], facts)
        self.assertEqual(ent_m, {"7001": 0, "7003": 27})
        self.assertEqual(ent_a, {"8001": 0, "8003": 27})


if __name__ == "__main__":
    unittest.main()
