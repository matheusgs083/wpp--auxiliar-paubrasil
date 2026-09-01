from __future__ import annotations

import unittest

from bot_api.services.promax_catalog_service import (
    DEFAULT_PROMAX_CATALOG,
    PromaxCatalogService,
    normalize_catalog,
)


FALLBACK = {
    "categories": {
        "fluxo_caixa": {
            "name": "Fluxo de Caixa",
            "routines": ["140506", "120606"],
            "units": [],
        }
    }
}


class FakeJobsService:
    def __init__(self, workers: list[dict] | None = None, error: Exception | None = None) -> None:
        self.workers = workers or []
        self.error = error

    def list_worker_heartbeats(self, **_kwargs):
        if self.error is not None:
            raise self.error
        return self.workers


class PromaxCatalogServiceTest(unittest.TestCase):
    def test_uses_catalog_from_first_online_worker(self) -> None:
        service = PromaxCatalogService(
            jobs_service=FakeJobsService(
                [
                    {
                        "worker_id": "host-1",
                        "online": True,
                        "metadata": {
                            "catalog": {
                                "categories": {
                                    "obz": {
                                        "name": "OBZ",
                                        "description": "Orcamento",
                                        "routines": [
                                            {"id": "0512", "name": "Rotina 0512"},
                                            {"id": "150501", "name": "Rotina 150501"},
                                        ],
                                        "units": [],
                                    }
                                }
                            }
                        },
                    }
                ]
            ),
            fallback_catalog=FALLBACK,
        )

        catalog = service.get_catalog()

        self.assertEqual(catalog["source"], "worker")
        self.assertEqual(catalog["worker_id"], "host-1")
        self.assertEqual(list(catalog["categories"]), ["obz"])

    def test_uses_fallback_when_worker_is_offline_or_database_fails(self) -> None:
        for jobs_service in (
            FakeJobsService([{"worker_id": "host-1", "online": False, "metadata": {}}]),
            FakeJobsService(error=RuntimeError("db offline")),
        ):
            with self.subTest(jobs_service=jobs_service):
                service = PromaxCatalogService(
                    jobs_service=jobs_service,
                    fallback_catalog=FALLBACK,
                )
                catalog = service.get_catalog()

                self.assertEqual(catalog["source"], "fallback")
                self.assertIn("fluxo_caixa", catalog["categories"])

    def test_default_fallback_keeps_all_standard_groups_visible(self) -> None:
        service = PromaxCatalogService(
            jobs_service=FakeJobsService(),
            fallback_catalog=DEFAULT_PROMAX_CATALOG,
        )

        catalog = service.get_catalog()

        self.assertEqual(catalog["source"], "fallback")
        self.assertEqual(
            set(catalog["categories"]),
            {
                "adf",
                "bot_zap",
                "botzapfechamento",
                "estoque",
                "fluxo_caixa",
                "giro",
                "inadimplencia",
                "obz",
                "outros",
            },
        )

    def test_rejects_invalid_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "categoria invalida"):
            normalize_catalog(
                {
                    "categories": {
                        "../obz": {
                            "name": "OBZ",
                            "routines": ["0512"],
                        }
                    }
                }
            )


if __name__ == "__main__":
    unittest.main()
