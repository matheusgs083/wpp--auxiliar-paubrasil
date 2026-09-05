from decimal import Decimal

from services.conferencia_service import (
    _aggregate_conferencia_items,
    _enrich_item,
    _extract_030302_items,
    _extract_030322_items,
)


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


def test_extract_030302_items_prefers_single_captura_diferencas_list():
    item = {"codigo": "863059", "texto": " pc GFE 300ML,PRET ", "faltaUn": "102", "faltaAv": "0"}
    payload = {
        "metadata": {
            "resultado_fisico": {
                "metadata": {
                    "captura_diferencas": {
                        "itens": [item],
                        "captura_inicial": {"itens": [item]},
                        "captura_material": {"itens": [item]},
                    },
                    "diferencas_corrigidas": {
                        "material": {"aplicados": [item]},
                        "aplicados": [item],
                    },
                }
            }
        }
    }

    rows = {row.cod_item: row for row in _extract_030302_items(payload)}

    assert rows["863059"].total_sistema == Decimal("102")


def test_extract_030302_items_from_flat_independent_metadata_capture():
    payload = {
        "metadata": {
            "captura_diferencas": {
                "itens": [
                    {"codigo": "863059", "texto": " pc GFE 300ML,PRET ", "faltaUn": "102", "faltaAv": "0"},
                    {"codigo": "899599", "texto": " pc GFE 1/1 PRETA ", "faltaUn": "70", "faltaAv": "0"},
                ]
            }
        }
    }

    rows = {row.cod_item: row for row in _extract_030302_items(payload)}

    assert rows["863059"].total_sistema == Decimal("102")
    assert rows["899599"].total_sistema == Decimal("70")


def test_extract_030322_items_from_prestacao_vasilhames_payload():
    payload = {
        "metadata": {
            "dados_030322": {
                "vasilhames": [
                    {
                        "codigo": "863059",
                        "unidade": "pc",
                        "denominacao": "GFE 300ML,PRET",
                        "preco": 40.8,
                        "saida_qtd": "102/00",
                        "retorno_qtd": "/00",
                        "diferenca_qtd": "102/00",
                    },
                    {
                        "codigo": "899599",
                        "unidade": "pc",
                        "denominacao": "GFE 1/1 PRETA",
                        "preco": "66,32",
                        "saida_qtd": "70/00",
                        "retorno_qtd": "/00",
                        "diferenca_qtd": "70/00",
                    },
                ]
            }
        }
    }

    rows = {row.cod_item: row for row in _extract_030322_items(payload)}

    assert rows["863059"].descricao == "GFE 300ML,PRET"
    assert rows["863059"].total_sistema == Decimal("102.000")
    assert rows["863059"].valor_unitario == Decimal("40.800")
    assert rows["899599"].total_sistema == Decimal("70.000")
    assert rows["899599"].payload["fonte_conferencia"] == "030322"


def test_extract_030302_items_uses_av_when_un_is_zero():
    payload = {
        "resultado_fisico": {
            "metadata": {
                "captura_diferencas": {
                    "itens": [
                        {"codigo": "2353", "texto": " cx GCAD PT2 CX6 ", "faltaUn": 0, "faltaAv": 2},
                    ]
                }
            }
        }
    }

    rows = {row.cod_item: row for row in _extract_030302_items(payload)}

    assert rows["2353"].total_sistema == Decimal("2")


def test_aggregate_030302_items_consolidates_only_expected_garrafeira_groups():
    payload = {
        "resultado_fisico": {
            "linhasDisponiveis": [
                {"codigo": "786238", "texto": " un GFA VERDE 600ML ", "vazUn": "288"},
                {"codigo": "188006", "texto": " un GFA VIDRO 1L ", "vazUn": "36"},
                {"codigo": "899599", "texto": " pc GFE 1/1 PRETA ", "vazUn": "36"},
                {"codigo": "900001", "texto": " pc GFE 1/2 PRETA ", "vazUn": "5"},
                {"codigo": "900002", "texto": " pc GFE 635ML PRETA ", "vazUn": "7"},
                {"codigo": "900003", "texto": " pc GFE 965ML PRETA ", "vazUn": "9"},
                {"codigo": "857679", "texto": " un GFE 51 AMARELA ", "vazUn": "2"},
                {"codigo": "37108", "texto": " pc CHAPATEX ", "vazUn": "12"},
                {"codigo": "863059", "texto": " pc GFE 300ML,PRET ", "vazUn": "714"},
                {"codigo": "198214", "texto": " un GFA LITRINHO ", "vazUn": "16146"},
            ]
        }
    }

    extracted = _extract_030302_items(payload)
    garrafeira_lookup = {
        "899599": {"descricao": "GARRAFEIRA PLAST,24 GFA 600ML", "tipo_material": "GARRAFEIRA CERVEJA 1/1", "un_venda": "003"},
        "900001": {"descricao": "GARRAFEIRA PLAST,24 GFA 600ML", "tipo_material": "GARRAFEIRA CERVEJA 1/2", "un_venda": "003"},
        "900002": {"descricao": "GARRAFEIRA PLAST,24 GFA 635ML", "tipo_material": "GARRAFEIRA CERVEJA 1/1", "un_venda": "003"},
        "900003": {"descricao": "GARRAFEIRA PLAST,12 GFA 965ML", "tipo_material": "GARRAFEIRA CERVEJA LITRAO", "un_venda": "003"},
        "857679": {"descricao": "GARRAFEIRA PLAST,12 GFA 965ML", "tipo_material": "", "un_venda": "003"},
        "863059": {"descricao": "GARRAFEIRA PLAST PRETA 23 GARRAFAS 300ML", "tipo_material": "GARRAFEIRA CERVEJA 1/2", "un_venda": "003"},
    }
    enriched = [_enrich_item(row, None, None, garrafeira_lookup.get(row.cod_item)) for row in extracted]
    rows = {row.cod_item: row for row in _aggregate_conferencia_items(enriched)}

    assert sorted(rows) == ["863059", "899599", "900001", "900002", "900003"]
    assert rows["899599"].grupo_contagem == "600"
    assert rows["900001"].grupo_contagem == "300"
    assert rows["900002"].grupo_contagem == "600"
    assert rows["900003"].grupo_contagem == "1L"
    assert rows["863059"].grupo_contagem == "300"
    assert rows["863059"].total_sistema == Decimal("714")
    assert rows["863059"].valor_unitario == Decimal("40.80")
    assert rows["899599"].valor_unitario == Decimal("66.32")
    assert rows["900003"].valor_unitario == Decimal("54.32")
