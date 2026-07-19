from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workers.promax_catalog import discover_report_catalog, read_report_group_manifest


class PromaxCatalogDiscoveryTest(unittest.TestCase):
    def test_discovers_literal_report_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            driver_dir = Path(temp_dir)
            groups_dir = driver_dir / "report_groups"
            groups_dir.mkdir()
            (groups_dir / "obz.py").write_text(
                "\n".join(
                    [
                        "REPORT_GROUP = {",
                        "    'key': 'obz',",
                        "    'name': 'OBZ',",
                        "    'description': 'Orcamento base zero',",
                        "    'routines': [",
                        "        {'id': '0512', 'name': 'Rotina 0512'},",
                        "        {'id': '150501', 'name': 'Rotina 150501'},",
                        "    ],",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )

            catalog = discover_report_catalog(driver_dir)

            self.assertEqual(list(catalog["categories"]), ["obz"])
            self.assertEqual(
                [item["id"] for item in catalog["categories"]["obz"]["routines"]],
                ["0512", "150501"],
            )
            self.assertEqual(catalog["warnings"], [])

    def test_rejects_executable_statements_without_running_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            driver_dir = Path(temp_dir)
            groups_dir = driver_dir / "report_groups"
            groups_dir.mkdir()
            marker = driver_dir / "executed.txt"
            (groups_dir / "unsafe.py").write_text(
                "\n".join(
                    [
                        "REPORT_GROUP = {'key': 'unsafe', 'name': 'Unsafe', 'routines': ['0512']}",
                        f"open({str(marker)!r}, 'w').write('executed')",
                    ]
                ),
                encoding="utf-8",
            )

            catalog = discover_report_catalog(driver_dir)

            self.assertFalse(marker.exists())
            self.assertEqual(catalog["categories"], {})
            self.assertEqual(len(catalog["warnings"]), 1)
            self.assertIn("somente a atribuicao literal", catalog["warnings"][0])

    def test_invalid_manifest_is_reported_without_hiding_valid_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            groups_dir = Path(temp_dir) / "report_groups"
            groups_dir.mkdir()
            (groups_dir / "giro.py").write_text(
                "REPORT_GROUP = {'key': 'giro', 'name': 'Giro', 'routines': ['030237_GIRO']}",
                encoding="utf-8",
            )
            (groups_dir / "invalid.py").write_text(
                "REPORT_GROUP = build_group()",
                encoding="utf-8",
            )

            catalog = discover_report_catalog(Path(temp_dir))

            self.assertIn("giro", catalog["categories"])
            self.assertEqual(len(catalog["warnings"]), 1)
            self.assertIn("literal Python", catalog["warnings"][0])

    def test_rejects_duplicate_routines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "duplicated.py"
            path.write_text(
                "REPORT_GROUP = {'key': 'obz', 'name': 'OBZ', 'routines': ['0512', '0512']}",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "rotina duplicada"):
                read_report_group_manifest(path)


if __name__ == "__main__":
    unittest.main()
