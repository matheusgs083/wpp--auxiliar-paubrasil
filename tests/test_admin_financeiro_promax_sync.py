from services.admin_financeiro_service import _extract_motorista_030303


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
