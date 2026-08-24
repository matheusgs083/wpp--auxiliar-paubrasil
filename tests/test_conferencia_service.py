from decimal import Decimal

from services.conferencia_service import _extract_030302_items


def test_extract_030302_items_from_resultado_fisico_metadata_and_groups_by_code():
    payload = {
        "metadata": {
            "resultado_fisico": {
                "metadata": {
                    "dados_030302": {
                        "materiais": [
                            {"codigo": "100", "descricao": "VASILHAME 600 ML", "quantidade": "3", "unidade": "un"},
                            {"codigo": "100", "descricao": "VASILHAME 600 ML", "quantidade": "2", "unidade": "un"},
                        ],
                        "produtos": [
                            {"codigo": "200", "descricao": "ORIGINAL LATA 350 ML", "qtde": "4", "un": "cx12"},
                        ],
                    }
                }
            }
        }
    }

    rows = {row.cod_item: row for row in _extract_030302_items(payload)}

    assert rows["100"].total_sistema == Decimal("5")
    assert rows["100"].grupo_contagem == "600"
    assert rows["200"].total_sistema == Decimal("4")
    assert rows["200"].grupo_contagem == "300"
