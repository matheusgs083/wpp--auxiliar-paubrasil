import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.prazo_limite_import_service import (
    _build_prazo_limite_rows_from_mapping_rows,
    _parse_currency_decimal,
)


class PrazoLimiteImportServiceTests(unittest.TestCase):
    def test_parse_currency_decimal_handles_brl_values(self) -> None:
        self.assertEqual(_parse_currency_decimal("R$ 80.000,00"), Decimal("80000.00"))
        self.assertEqual(_parse_currency_decimal("R$ 66.008,44"), Decimal("66008.44"))
        self.assertEqual(_parse_currency_decimal(""), Decimal("0"))

    def test_build_rows_reads_optional_pedidos_column(self) -> None:
        rows = _build_prazo_limite_rows_from_mapping_rows(
            [
                {
                    "KPI": "Abr",
                    "Filial": "3",
                    "NB": "9845",
                    "% Pag Atraso": "0.18",
                    "Prazo Atual": "5",
                    "Cond Pag Atual": "505",
                    "Limite Total": "R$ 80.000,00",
                    "Faturamento com PDV": "R$ 66.008,44",
                    "Pedidos": "8",
                }
            ],
            header_map={
                "KPI": "KPI",
                "Filial": "Filial",
                "NB": "NB",
                "% Pag Atraso": "% Pag Atraso",
                "Prazo Atual": "Prazo Atual",
                "Cond Pag Atual": "Cond Pag Atual",
                "Limite Total": "Limite Total",
                "Faturamento com PDV": "Faturamento com PDV",
                "Pedidos": "Pedidos",
            },
            row_number_offset=2,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].pedidos, Decimal("8"))
        self.assertEqual(rows[0].limite_total, Decimal("80000.00"))
        self.assertEqual(rows[0].faturamento_com_pdv, Decimal("66008.44"))


if __name__ == "__main__":
    unittest.main()
