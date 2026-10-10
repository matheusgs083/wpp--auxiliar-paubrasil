from __future__ import annotations

import unittest

from services.promax_grade_input_service import parse_grade_020304_csv, parse_grade_csv


class PromaxGradeInputTests(unittest.TestCase):
    def test_groups_csv_rows_and_preserves_source_lines(self) -> None:
        groups = parse_grade_csv(
            "armazem;deposito;data_movimento;item;sku\n01;02;08/10/2026;22177;222\n01;02;08/10/2026;22178;3\n".encode()
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["itens"][0]["source_row"], 2)
        self.assertEqual(groups[0]["itens"][1]["sku"], 3)

    def test_rejects_row_without_quantity(self) -> None:
        with self.assertRaisesRegex(ValueError, "Linha 2"):
            parse_grade_csv("armazem;deposito;data_movimento;item;sku\n01;02;08/10/2026;22177;\n".encode())

    def test_020304_accepts_zero_quantity_to_reverse_a_product(self) -> None:
        groups = parse_grade_020304_csv("grade;produto;quantidade\n1;9092;0\n".encode())

        self.assertEqual(groups, [{"grade": "1", "itens": [{"produto": "9092", "quantidade": 0, "source_row": 2}]}])
