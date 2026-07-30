from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bot_api.services import admin_imports_runtime


class AdminImportsRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._datasets = admin_imports_runtime.ADMIN_IMPORT_DATASETS
        self._runtime_root = admin_imports_runtime.ADMIN_IMPORT_RUNTIME_ROOT

    def tearDown(self) -> None:
        admin_imports_runtime.ADMIN_IMPORT_DATASETS = self._datasets
        admin_imports_runtime.ADMIN_IMPORT_RUNTIME_ROOT = self._runtime_root

    def test_reference_date_uses_upload_activation_date_for_all_datasets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = "boletos_bradesco_op_3"
            csv_dataset = "dclientes"
            admin_imports_runtime.ADMIN_IMPORT_RUNTIME_ROOT = root
            admin_imports_runtime.ADMIN_IMPORT_DATASETS = {
                dataset: {
                    "label": "Boletos Operacao 3",
                    "default_path": root / "default.pdf",
                    "upload_mode": "single",
                    "allow_default_source": False,
                },
                csv_dataset: {
                    "label": "dClientes",
                    "default_path": root / "dClientes.csv",
                    "upload_mode": "single",
                },
            }
            source_path = root / dataset / "versions" / "job-1" / "default.pdf"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"%PDF-1.4\n")
            manifest_path = root / dataset / "active.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "dataset": dataset,
                        "job_id": "job-1",
                        "source_path": str(source_path),
                        "stored_files": [],
                        "activated_at": "2026-07-23T00:57:09+00:00",
                    }
                ),
                encoding="utf-8",
            )

            resolved = admin_imports_runtime._resolve_admin_import_reference_date(dataset, "2026-01-01")

            self.assertEqual(resolved, "2026-07-22")

            csv_source_path = root / csv_dataset / "versions" / "job-2" / "dClientes.csv"
            csv_source_path.parent.mkdir(parents=True)
            csv_source_path.write_text("nb;cliente\n1;Teste\n", encoding="utf-8")
            (root / csv_dataset / "active.json").write_text(
                json.dumps(
                    {
                        "dataset": csv_dataset,
                        "job_id": "job-2",
                        "source_path": str(csv_source_path),
                        "stored_files": [],
                        "activated_at": "2026-07-24T12:30:00-03:00",
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                admin_imports_runtime._resolve_admin_import_reference_date(csv_dataset, "2026-01-01"),
                "2026-07-24",
            )


if __name__ == "__main__":
    unittest.main()
