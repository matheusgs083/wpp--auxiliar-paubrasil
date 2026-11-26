from __future__ import annotations

import gzip
import sys
import unittest
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.routes.admin_promax import create_admin_promax_router


class FakeCompras030237:
    def __init__(self, erro: Exception | None = None) -> None:
        self.chamadas: list[dict[str, bytes]] = []
        self.erro = erro

    def importar_arquivos_giro(self, arquivos: dict[str, bytes]) -> dict[str, Any]:
        self.chamadas.append(dict(arquivos))
        if self.erro:
            raise self.erro
        return {"arquivos": 1, "ignorados": 0, "rows": 2, "meses": ["2026-11"], "resumo": {"ok": True}}


def _cliente(compras: Any, *, is_admin: bool = True, coordenadas: Any = None) -> tuple[TestClient, list[dict[str, Any]]]:
    acoes: list[dict[str, Any]] = []

    def autenticar(**_kwargs: Any) -> dict[str, Any]:
        return {"is_admin": is_admin, "username": "admin", "features": ("promax",)}

    app = FastAPI()
    app.include_router(
        create_admin_promax_router(
            service=object(),
            catalog={},
            worker_token="token",
            compras_030237_service=compras,
            coordenadas_012012_service=coordenadas,
            require_admin_panel_auth=autenticar,
            require_admin_panel_feature=lambda _context, _feature: None,
            record_security_event=lambda _request, **_kwargs: None,
            record_admin_panel_action=lambda **kwargs: acoes.append(kwargs),
        )
    )
    return TestClient(app), acoes


def _enviar(cliente: TestClient, nome: str = "0111.csv", conteudo: bytes = b"Emissao;Produto\n01/11/2026;123\n"):
    return cliente.post("/api/admin/promax/030237/importar", files={"arquivo": (nome, conteudo, "text/csv")})


class Importar012012PeloPainelTest(unittest.TestCase):
    def test_admin_importa_e_registra_arquivo_por_revenda(self) -> None:
        from unittest.mock import Mock
        service = Mock()
        recebido = {}
        def importar(paths):
            recebido["nome"] = paths[0].name
            recebido["conteudo"] = paths[0].read_bytes()
            return {"filiais": ["3"], "rows": 2, "com_coordenadas": 1}
        service.import_files.side_effect = importar
        cliente, acoes = _cliente(None, coordenadas=service)
        resposta = cliente.post("/api/admin/promax/012012/importar", files={"arquivo": ("012012_relatorio_400_2210003.csv", b"dados", "text/csv")})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(recebido, {"nome": "012012_relatorio_400_2210003.csv", "conteudo": b"dados"})
        self.assertEqual(resposta.json()["result"]["filiais"], ["3"])
        self.assertEqual(acoes[0]["action"], "importar_012012_coordenadas")

    def test_acesso_e_arquivo_invalidos_sao_recusados(self) -> None:
        from unittest.mock import Mock
        service = Mock()
        cliente, _ = _cliente(None, is_admin=False, coordenadas=service)
        self.assertEqual(cliente.post("/api/admin/promax/012012/importar", files={"arquivo": ("x.csv", b"x")}).status_code, 403)
        cliente, _ = _cliente(None, coordenadas=service)
        self.assertEqual(cliente.post("/api/admin/promax/012012/importar", files={"arquivo": ("x.xlsx", b"x")}).status_code, 422)
        self.assertEqual(cliente.post("/api/admin/promax/012012/importar", files={"arquivo": ("x.csv", b"")}).status_code, 422)
        service.import_files.assert_not_called()


class Importar030237PeloPainelTest(unittest.TestCase):
    def test_admin_importa_um_csv_e_registra_a_acao(self) -> None:
        compras = FakeCompras030237()
        cliente, acoes = _cliente(compras)
        resposta = _enviar(cliente)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["result"]["meses"], ["2026-11"])
        self.assertEqual(list(compras.chamadas[0]), ["0111.csv"])
        self.assertEqual(acoes[0]["action"], "importar_030237_itens")

    def test_aceita_o_csv_compactado_pelo_painel(self) -> None:
        compras = FakeCompras030237()
        cliente, _ = _cliente(compras)
        original = b"Emissao;Produto\n01/11/2026;123\n"
        resposta = _enviar(cliente, nome="0111.csv.gz", conteudo=gzip.compress(original))
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(compras.chamadas[0], {"0111.csv": original})

    def test_quem_nao_e_admin_nao_importa(self) -> None:
        compras = FakeCompras030237()
        cliente, _ = _cliente(compras, is_admin=False)
        self.assertEqual(_enviar(cliente).status_code, 403)
        self.assertEqual(compras.chamadas, [])

    def test_recusa_arquivo_que_nao_e_csv_ou_vazio(self) -> None:
        compras = FakeCompras030237()
        cliente, _ = _cliente(compras)
        self.assertEqual(_enviar(cliente, nome="0111.xlsx").status_code, 422)
        self.assertEqual(_enviar(cliente, conteudo=b"  \n").status_code, 422)
        self.assertEqual(compras.chamadas, [])

    def test_030237_sem_itens_volta_422_com_o_motivo(self) -> None:
        cliente, _ = _cliente(FakeCompras030237(ValueError("0111.csv: a 03.02.37 precisa vir com itens (coluna Produto).")))
        resposta = _enviar(cliente)
        self.assertEqual(resposta.status_code, 422)
        self.assertIn("precisa vir com itens", resposta.json()["detail"])

    def test_sem_importador_configurado_volta_503(self) -> None:
        cliente, _ = _cliente(None)
        self.assertEqual(_enviar(cliente).status_code, 503)


if __name__ == "__main__":
    unittest.main()
