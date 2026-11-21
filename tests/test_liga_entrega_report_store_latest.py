from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore


class FakeCatalog:
    """Catálogo em memória com o mesmo contrato do LigaEntregaBatchCatalog."""

    def __init__(self, broken: bool = False) -> None:
        self.rows: dict[str, dict] = {}
        self.broken = broken
        self.count_calls = 0

    def _check(self) -> None:
        if self.broken:
            raise RuntimeError("banco fora")

    def record(self, manifests):
        self._check()
        novos = 0
        for item in manifests:
            if item["batch_id"] not in self.rows:
                self.rows[item["batch_id"]] = dict(item)
                novos += 1
        return novos

    def count(self, routine):
        self._check()
        self.count_calls += 1
        return sum(1 for item in self.rows.values() if item["routine"] == routine)

    def latest(self, routine):
        self._check()
        items = [item for item in self.rows.values() if item["routine"] == routine]
        return max(items, key=lambda item: item["stored_at"]) if items else None

    def list(self, routine):
        self._check()
        return [item for item in self.rows.values() if item["routine"] == routine]


class LigaEntregaReportStoreCatalogTest(unittest.TestCase):
    def test_store_batch_records_in_catalog_and_latest_comes_from_it(self):
        with TemporaryDirectory() as tmp:
            catalog = FakeCatalog()
            store = LigaEntregaReportStore(Path(tmp), catalog=catalog)
            first = store.store_batch(routine="030237", files={"a.csv": b"x;y\n"}, reference_date="2026-11-19")
            self.assertIn(first["batch_id"], catalog.rows)

            fresh = LigaEntregaReportStore(Path(tmp), catalog=catalog)
            fresh._scan_manifest_files = lambda routine: self.fail("nao deveria ler as pastas")
            self.assertEqual(fresh.latest_manifest("030237")["batch_id"], first["batch_id"])

    def test_first_read_registers_existing_folders_once(self):
        with TemporaryDirectory() as tmp:
            old = LigaEntregaReportStore(Path(tmp))
            a = old.store_batch(routine="030805_LIGA", files={"a.csv": b"x;y\n"}, reference_date="2026-10-06")
            b = old.store_batch(routine="030805_LIGA", files={"b.csv": b"x;y\n"}, reference_date="2026-11-06")

            catalog = FakeCatalog()
            store = LigaEntregaReportStore(Path(tmp), catalog=catalog)
            self.assertEqual(store.list_manifests("030805_LIGA", competencia="2026-11")[0]["batch_id"], b["batch_id"])
            self.assertEqual(set(catalog.rows), {a["batch_id"], b["batch_id"]})
            store.list_manifests("030805_LIGA")
            self.assertEqual(catalog.count_calls, 1)

    def test_list_from_catalog_matches_list_from_folders(self):
        with TemporaryDirectory() as tmp:
            plain = LigaEntregaReportStore(Path(tmp))
            plain.store_batch(routine="030224_RESUMO_LIGA", files={"a.csv": b"x;y\n"}, reference_date="2026-10-07",
                              metadata={"competencia": "2026-09"})
            plain.store_batch(routine="030224_RESUMO_LIGA", files={"b.csv": b"x;y\n"}, reference_date="2026-09-24")
            with_catalog = LigaEntregaReportStore(Path(tmp), catalog=FakeCatalog())
            for comp in (None, "2026-09", "2026-10"):
                ids = lambda store: [m["batch_id"] for m in store.list_manifests("030224_RESUMO_LIGA", competencia=comp)]
                self.assertEqual(ids(plain), ids(with_catalog), comp)

    def test_database_down_falls_back_to_folders(self):
        with TemporaryDirectory() as tmp:
            store = LigaEntregaReportStore(Path(tmp), catalog=FakeCatalog(broken=True))
            batch = store.store_batch(routine="031120_BOT", files={"a.csv": b"x;y\n"}, reference_date="2026-11-02")
            self.assertEqual(store.latest_manifest("031120_BOT")["batch_id"], batch["batch_id"])
            self.assertEqual(len(store.list_manifests("031120_BOT")), 1)


if __name__ == "__main__":
    unittest.main()
