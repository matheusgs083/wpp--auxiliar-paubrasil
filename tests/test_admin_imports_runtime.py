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

    def test_boleto_reference_date_uses_upload_activation_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset = "boletos_bradesco_op_3"
            admin_imports_runtime.ADMIN_IMPORT_RUNTIME_ROOT = root
            admin_imports_runtime.ADMIN_IMPORT_DATASETS = {
                dataset: {
                    "label": "Boletos Operacao 3",
                    "default_path": root / "default.pdf",
                    "upload_mode": "single",
                    "allow_default_source": False,
                },
                "dclientes": {
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
            self.assertEqual(
                admin_imports_runtime._resolve_admin_import_reference_date("dclientes", "2026-01-01"),
                "2026-01-01",
            )


if __name__ == "__main__":
    unittest.main()
