from decimal import Decimal

from services.admin_financeiro_service import (
    _extract_motorista_030303,
    _financeiro_metrics_from_fechamento,
)


def test_extract_motorista_030303_from_worker_result_metadata():
    payload = {
        "metadata": {
            "resultado_030303": {
                "dados_030303": {
                    "motorista": {
                        "nome": "GABRIEL MORAIS BEZERRA",
                        "origem_nome": "ajudante1",
                    }
                }
            }
        }
    }

    assert _extract_motorista_030303(payload) == "GABRIEL MORAIS BEZERRA"


def test_extract_motorista_030303_from_direct_result_metadata():
    payload = {
        "resultado_030303": {
            "metadata": {
                "dados_030303": {
                    "motorista": {
                        "nome": "JOAO DA SILVA",
                        "origem_nome": "csMotorista",
                    }
                }
            }
        }
    }

    assert _extract_motorista_030303(payload) == "JOAO DA SILVA"


def test_financeiro_metrics_recalcula_total_promax_com_dinheiro_da_saida():
    dados = {
        "saida": {
            "total": "",
            "itens": [
                {"descricao": "CREDITO EM CONTA", "qtNfs": "17", "valor": "17.127,80"},
                {"descricao": "BLOQUETO BANCARIO", "qtNfs": "7", "valor": "7.656,63"},
                {"descricao": "BONIFICACAO", "qtNfs": "0", "valor": "232,18"},
                {"descricao": "A VISTA", "qtNfs": "1", "valor": "161,70"},
                {"descricao": "Vasilhame", "qtNfs": "0", "valor": "16.201,92"},
            ],
        }
    }

    metrics = _financeiro_metrics_from_fechamento(dados)

    assert metrics["total_promax"] == Decimal("41380.23")
    assert metrics["credito_conta"] == Decimal("17127.80")
    assert metrics["dinheiro_promax"] == Decimal("161.70")
    assert metrics["boletos_rota"] == Decimal("7")
