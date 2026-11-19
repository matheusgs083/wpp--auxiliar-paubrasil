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
    def test_pins_updated_worker_even_when_old_worker_has_newer_heartbeat(self) -> None:
        def worker(name, routines, online=True):
            return {'worker_id': name, 'online': online, 'metadata': {'catalog': {
                'categories': {'fluxo_caixa': {'name': 'Fluxo de Caixa', 'routines': routines}}
            }}}
        workers = [worker('antigo', ['140506']), worker('promax-producao', ['140501', '140506'])]
        service = PromaxCatalogService(jobs_service=FakeJobsService(workers), fallback_catalog=FALLBACK, preferred_worker_id='promax-producao')
        catalog = service.get_catalog()
        self.assertEqual(catalog['worker_id'], 'promax-producao')
        self.assertIn('140501', [r['id'] for r in catalog['categories']['fluxo_caixa']['routines']])
        self.assertEqual(workers[0]['metadata']['catalog']['categories']['fluxo_caixa']['routines'], ['140506'])

    def test_pinned_worker_offline_does_not_switch_to_old_worker(self) -> None:
        worker = {'worker_id': 'antigo', 'online': True, 'metadata': {'catalog': FALLBACK}}
        service = PromaxCatalogService(jobs_service=FakeJobsService([worker]), fallback_catalog=DEFAULT_PROMAX_CATALOG, preferred_worker_id='promax-producao')
        result = service.get_catalog()
        self.assertEqual(result['source'], 'fallback')
        self.assertEqual(result['preferred_worker_id'], 'promax-producao')
        self.assertIn('indisponível', result['warnings'][0])

    def test_cora_estoque_aceita_codigos_promax_mesmo_com_worker_publicando_codigos_cora(self) -> None:
        worker = {'worker_id': 'host-1', 'online': True, 'metadata': {'catalog': {'categories': {
            'obz': {'name': 'OBZ', 'routines': ['0512']},
            'cora_estoque': {'name': 'Cora', 'routines': ['grade_estoque'], 'units': ['487570', '747530']},
        }}}}
        catalog = PromaxCatalogService(jobs_service=FakeJobsService([worker]), fallback_catalog=DEFAULT_PROMAX_CATALOG).get_catalog()
        self.assertEqual(catalog['source'], 'worker')
        self.assertEqual(catalog['categories']['cora_estoque']['units'], [])
        self.assertEqual(catalog['categories']['cora_critica']['units'], [])

    def test_worker_antigo_sem_cora_estoque_recebe_a_categoria_do_servidor(self) -> None:
        worker = {'worker_id': 'host-1', 'online': True, 'metadata': {'catalog': FALLBACK}}
        catalog = PromaxCatalogService(jobs_service=FakeJobsService([worker]), fallback_catalog=DEFAULT_PROMAX_CATALOG).get_catalog()
        self.assertIn('grade_estoque', [r['id'] for r in catalog['categories']['cora_estoque']['routines']])

    def test_140501_is_available_in_cashflow_fallback(self) -> None:
        routines = DEFAULT_PROMAX_CATALOG['categories']['fluxo_caixa']['routines']
        self.assertIn('140501', [row['id'] for row in routines])

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
                "cora_critica",
                "cora_estoque",
                "estoque",
                "fluxo_caixa",
                "giro",
                "inadimplencia",
                "liga_entrega",
                "liga_entrega_fechamento",
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
