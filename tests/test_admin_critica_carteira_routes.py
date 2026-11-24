from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot_api.routes.admin_critica_carteira import create_admin_critica_carteira_router

VENDEDOR = {"is_admin": False, "username": "rn101", "seller_scopes": ["3-101"], "features": ("gerar_critica",)}
GERENTE = {"is_admin": False, "username": "gv10", "gv_scopes": ["3-10"], "features": ("gerar_critica",)}
OPERACAO = {"is_admin": False, "username": "sup", "filiais": ["1", "4"], "features": ("gerar_critica",)}
ADMIN = {"is_admin": True, "username": "gerente"}
SEM_PERMISSAO = {"is_admin": False, "username": "x", "seller_scopes": ["3-101"], "features": ("critica",)}

# Setores do cadastro: o filtro de acesso é aplicado pelo serviço real; aqui o falso aplica o mesmo recorte.
CADASTRO = [("3_101", "3_10"), ("3_102", "3_10"), ("3_205", "3_20"), ("1_301", "1_30"), ("4_401", "4_40")]


class FakeDClientes:
    def list_seller_base_summaries(self, allowed_sectors=None, allowed_gv_vdes=None, limit=100):
        def liberado(setor: str, gv: str) -> bool:
            if allowed_sectors is None and allowed_gv_vdes is None:
                return True
            for chave in allowed_sectors or []:
                if chave.startswith("filial:") and setor.split("_")[0] == chave[7:]:
                    return True
                if chave == setor:
                    return True
            return gv in (allowed_gv_vdes or [])
        return [SimpleNamespace(seller_code=s, manager_code=g) for s, g in CADASTRO if liberado(s, g)]


class FakeCritica:
    def __init__(self) -> None:
        self.pedidos: list[dict[str, Any]] = []

    def latest_date(self, *, allowed_sectors=None, allowed_gv_vdes=None):
        return date(2026, 11, 23)

    def get_pdf_report(self, *, target_date, allowed_sectors=None, allowed_gv_vdes=None, limit=5000):
        self.pedidos.append({"date": target_date, "sectors": allowed_sectors, "gvs": allowed_gv_vdes})
        return SimpleNamespace(pdf_bytes=b"%PDF-completo", summary_pdf_bytes=b"%PDF-resumo")

    def get_gv_summary_pdf(self, *, target_date, allowed_sectors=None, allowed_gv_vdes=None, limit=50000):
        self.pedidos.append({"date": target_date, "sectors": allowed_sectors, "gvs": allowed_gv_vdes, "tipo": "gv"})
        return SimpleNamespace(pdf_bytes=b"%PDF-gv", summary_pdf_bytes=b"")


def _auth(context):
    def auth(**_kwargs):
        if context is None:
            raise HTTPException(status_code=401, detail="Sessão expirada.")
        return dict(context)
    return auth


def _feature(context, feature):
    if not context.get("is_admin") and feature not in context.get("features", ()):
        raise HTTPException(status_code=403, detail="Sem permissão.")


def _app(context) -> tuple[TestClient, FakeCritica]:
    critica = FakeCritica()
    app = FastAPI()
    app.include_router(
        create_admin_critica_carteira_router(
            require_admin_panel_auth=_auth(context),
            require_admin_panel_feature=_feature,
            dclientes_query_service=FakeDClientes(),
            critica_rn_query_service=critica,
            parse_admin_critica_date=lambda valor: date.fromisoformat(valor) if valor else None,
            record_security_event=lambda *_a, **_k: None,
        )
    )
    return TestClient(app), critica


class OpcoesTest(unittest.TestCase):
    def test_vendedor_ve_so_a_propria_filial_e_setor(self) -> None:
        dados = _app(VENDEDOR)[0].get("/api/admin/critica/carteira/opcoes").json()
        self.assertEqual(dados["filiais"], [{"codigo": "3", "nome": "Patos"}])
        self.assertEqual(dados["filial"], "3")
        self.assertEqual([s["setor"] for s in dados["setores"]], ["3_101"])
        self.assertFalse(dados["pode_filial_inteira"])
        self.assertEqual(dados["gvs"], [])
        self.assertEqual(dados["ultima_data"], "2026-11-23")

    def test_gerente_ve_os_setores_do_gv(self) -> None:
        dados = _app(GERENTE)[0].get("/api/admin/critica/carteira/opcoes").json()
        self.assertEqual([s["setor"] for s in dados["setores"]], ["3_101", "3_102"])
        self.assertEqual(dados["gvs"], [{"gv": "10", "setores": 2}])

    def test_operacao_escolhe_entre_as_filiais_marcadas(self) -> None:
        cliente = _app(OPERACAO)[0]
        dados = cliente.get("/api/admin/critica/carteira/opcoes").json()
        self.assertEqual([f["codigo"] for f in dados["filiais"]], ["1", "4"])
        self.assertEqual(dados["setores"], [])
        self.assertEqual([s["setor"] for s in cliente.get("/api/admin/critica/carteira/opcoes", params={"filial": "4"}).json()["setores"]], ["4_401"])
        self.assertEqual(cliente.get("/api/admin/critica/carteira/opcoes", params={"filial": "3"}).status_code, 403)

    def test_admin_ve_todas_as_filiais(self) -> None:
        dados = _app(ADMIN)[0].get("/api/admin/critica/carteira/opcoes").json()
        self.assertEqual([f["codigo"] for f in dados["filiais"]], ["1", "2", "3", "4", "5", "6", "7", "8"])
        gvs = _app(ADMIN)[0].get("/api/admin/critica/carteira/opcoes", params={"filial": "3"}).json()["gvs"]
        self.assertEqual([g["gv"] for g in gvs], ["10", "20"])

    def test_exige_permissao(self) -> None:
        self.assertEqual(_app(SEM_PERMISSAO)[0].get("/api/admin/critica/carteira/opcoes").status_code, 403)
        self.assertEqual(_app(None)[0].get("/api/admin/critica/carteira/opcoes").status_code, 401)


class PdfTest(unittest.TestCase):
    def test_vendedor_baixa_o_proprio_setor(self) -> None:
        cliente, critica = _app(VENDEDOR)
        resposta = cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3", "setor": "101"})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.content, b"%PDF-completo")
        self.assertIn("critica-3-setor-101-2026-11-23.pdf", resposta.headers["content-disposition"])
        self.assertEqual(critica.pedidos[-1]["sectors"], ["3_101"])

    def test_vendedor_nao_baixa_setor_de_outro(self) -> None:
        cliente, critica = _app(VENDEDOR)
        self.assertEqual(cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3", "setor": "205"}).status_code, 403)
        self.assertEqual(cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "1"}).status_code, 403)
        self.assertEqual(critica.pedidos, [])

    def test_sem_setor_o_vendedor_recebe_so_a_carteira_dele(self) -> None:
        cliente, critica = _app(VENDEDOR)
        resposta = cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3", "summary_only": "1"})
        self.assertEqual(resposta.content, b"%PDF-resumo")
        self.assertEqual(critica.pedidos[-1]["sectors"], ["3_101"])

    def test_gerente_sem_setor_recebe_o_gv(self) -> None:
        cliente, critica = _app(GERENTE)
        self.assertEqual(cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3"}).status_code, 200)
        self.assertEqual((critica.pedidos[-1]["sectors"], critica.pedidos[-1]["gvs"]), (None, ["3_10"]))
        self.assertEqual(cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3", "setor": "205"}).status_code, 403)

    def test_operacao_baixa_a_filial_inteira_na_data_escolhida(self) -> None:
        cliente, critica = _app(OPERACAO)
        resposta = cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "4", "date": "2026-11-20"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(critica.pedidos[-1], {"date": date(2026, 11, 20), "sectors": ["filial:4"], "gvs": None})


class CriticaDoGvTest(unittest.TestCase):
    def test_gerente_baixa_a_critica_do_proprio_gv(self) -> None:
        cliente, critica = _app(GERENTE)
        resposta = cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3", "gv": "10"})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.content, b"%PDF-gv")
        self.assertIn("critica-3-gv-10-2026-11-23.pdf", resposta.headers["content-disposition"])
        self.assertEqual(critica.pedidos[-1]["gvs"], ["3_10"])
        self.assertEqual(cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3", "gv": "20"}).status_code, 403)

    def test_vendedor_nao_baixa_a_critica_do_gv_do_setor_dele(self) -> None:
        cliente, critica = _app(VENDEDOR)
        self.assertEqual(cliente.get("/api/admin/critica/carteira/pdf", params={"filial": "3", "gv": "10"}).status_code, 403)
        self.assertEqual(critica.pedidos, [])

    def test_gv_e_setor_juntos_sao_recusados(self) -> None:
        self.assertEqual(_app(ADMIN)[0].get("/api/admin/critica/carteira/pdf", params={"filial": "3", "gv": "10", "setor": "101"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
