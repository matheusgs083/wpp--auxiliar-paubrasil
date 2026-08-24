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


def test_extract_030302_items_from_real_promax_linhas_disponiveis():
    payload = {
        "resultado_fisico": {
            "linhasDisponiveis": [
                {"codigo": "27983", "texto": " un GFA A 635ML ", "vazUn": "192"},
                {"codigo": "198214", "texto": " un GFA LITRINHO ", "vazUn": "5382"},
                {"codigo": "863059", "texto": " pc GFE 300ML,PRET ", "vazUn": "238"},
                {"codigo": "37108", "texto": " pc CHAPATEX ", "vazUn": "4"},
                {"codigo": "42069", "texto": " pc PALLET PBR2 ", "vazUn": ""},
            ]
        }
    }

    rows = {row.cod_item: row for row in _extract_030302_items(payload)}

    assert rows["27983"].total_sistema == Decimal("192")
    assert rows["198214"].total_sistema == Decimal("5382")
    assert rows["863059"].total_sistema == Decimal("238")
    assert rows["37108"].total_sistema == Decimal("4")
    assert "42069" in rows


def test_extract_030302_items_from_nested_result_metadata_linhas_disponiveis():
    payload = {
        "metadata": {
            "resultado_fisico": {
                "metadata": {
                    "linhasDisponiveis": [
                        {"codigo": "27983", "texto": " un GFA VIDRO 635ML,AMBAR,", "vazUn": "192"},
                        {"codigo": "188006", "texto": " un GFA VIDRO 1L,AMBAR,RET", "vazUn": "12"},
                        {"codigo": "198214", "texto": " un GFA VIDRO 330ML,AMBAR,", "vazUn": "5382"},
                        {"codigo": "37108", "texto": " pc CHAPATEX,1,00 M,1,20 M", "vazUn": "4"},
                    ],
                    "naoAplicados": [],
                    "totalRecebido": 8,
                }
            }
        }
    }

    rows = {row.cod_item: row for row in _extract_030302_items(payload)}

    assert rows["27983"].total_sistema == Decimal("192")
    assert rows["188006"].total_sistema == Decimal("12")
    assert rows["198214"].total_sistema == Decimal("5382")
    assert rows["37108"].total_sistema == Decimal("4")
