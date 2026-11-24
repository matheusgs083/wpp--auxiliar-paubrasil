from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot_api.routes.admin_rota_financeira import boleto_rotulo, create_admin_rota_financeira_router, situacao_rotulo
from bot_api.services.rota_financeira_query_service import RotaFinanceiraPagina

VENDEDOR_107 = {"is_admin": False, "mode": "usuario", "features": ("rota_financeira",), "seller_scopes": ("3-107",)}
GV_4 = {"is_admin": False, "mode": "usuario", "features": ("rota_financeira",), "seller_scopes": ("3-107", "3-108")}
SEM_CARTEIRA = {"is_admin": False, "mode": "usuario", "features": ("rota_financeira",), "seller_scopes": ()}
SEM_FEATURE = {"is_admin": False, "mode": "usuario", "features": ("pedidos",), "seller_scopes": ("3-107",)}

# Carteira fictícia: (filial, NB, setor, GV, menor_dias, títulos, boletos)
CARTEIRA = [
    ("3", "100", "3_107", "3_4", 5, 1, 0),
    ("3", "101", "3_107", "3_4", -10, 2, 1),
    ("3", "200", "3_108", "3_4", 0, 1, 1),
    ("3", "300", "3_109", "3_5", -30, 3, 0),
]


def _permitido(filial: str, setor: str, gv: str, setores: Any, gvs: Any) -> bool:
    """Mesma regra do banco: setor, operação (filial:N) ou GV, combinados com OU."""
    if setores is None and gvs is None:
        return True
    return setor in (setores or []) or f"filial:{filial}" in (setores or []) or gv in (gvs or [])


def _faixa(dias: int | None, titulos: int) -> int:
    if not titulos:
        return 6
    return 1 if dias < 0 else 2 if dias == 0 else 3 if dias == 1 else 4 if dias == 2 else 5


class FakeRota:
    """Imita o banco: escopo AND filtros da tela, depois ordenação por faixa."""

    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    def listar(self, **kwargs: Any) -> RotaFinanceiraPagina:
        self.chamadas.append(kwargs)
        linhas = []
        for filial, nb, setor, gv, dias, titulos, boletos in CARTEIRA:
            if not _permitido(filial, setor, gv, kwargs["allowed_sectors"], kwargs["allowed_gv_vdes"]):
                continue
            if kwargs["setor"] and setor != kwargs["setor"]:
                continue
            if kwargs["gv"] and gv != kwargs["gv"]:
                continue
            if kwargs["busca"] and kwargs["busca"] != nb:
                continue
            faixa = _faixa(dias, titulos)
            linhas.append({
                "filial": filial, "cliente": nb, "nome": f"CLIENTE {nb}", "razao_social": "", "telefone": "(83) 99812-3344",
                "cidade": "Patos", "dia_visita": "SEG", "status": "Ativo", "cond_pagto": "", "limite_credito": "",
                "setor": setor, "gv": gv, "titulos": titulos, "titulos_vencidos": int(dias < 0) * titulos,
                "total_pendente": "100.00", "total_vencido": "0.00", "menor_dias": dias, "vencimento_proximo": "",
                "boletos": boletos if kwargs["incluir_boletos"] else 0, "faixa": faixa,
            })
        linhas.sort(key=lambda l: (l["faixa"], l["menor_dias"] if l["faixa"] == 1 else 0))
        return RotaFinanceiraPagina(clientes=linhas, total=len(linhas), resumo={"clientes": len(linhas)})


class FakeDClientes:
    def list_visit_days(self, allowed_sectors: Any = None, allowed_gv_vdes: Any = None, limit: int = 10) -> list[str]:
        return ["SEG/QUI", "TER/SEX"]

    def list_seller_base_summaries(self, allowed_sectors: Any = None, allowed_gv_vdes: Any = None, limit: int = 100) -> list[Any]:
        todos = {(f, setor, gv) for f, _nb, setor, gv, *_ in CARTEIRA}
        return [
            SimpleNamespace(seller_code=s, manager_code=g, visit_count=1)
            for f, s, g in sorted(todos)
            if _permitido(f, s, g, allowed_sectors, allowed_gv_vdes)
        ]


class Pronto:
    def __init__(self, pronto: bool = True) -> None:
        self.pronto = pronto

    def status(self) -> dict[str, Any]:
        return {"ready": self.pronto}


class FakeGiroVasilhame:
    def catalogo(self) -> dict[str, dict[str, str]]:
        return {"863059": {"descricao": "GARRAFEIRA PLAST PRETA 23 GARRAFAS 30OML", "tipo": "litrinho"}}


def _app(context: dict[str, Any] | None, *, rota: FakeRota | None = None, boletos_prontos: bool = True, giro: Any = None) -> TestClient:
    def auth(**_kwargs: Any) -> dict[str, Any]:
        if context is None:
            raise HTTPException(status_code=401, detail="Sessão expirada.")
        return dict(context)

    def feature(ctx: dict[str, Any] | None, nome: str) -> None:
        if not ctx or not (ctx.get("is_admin") or nome in ctx.get("features", ())):
            raise HTTPException(status_code=403, detail="Acesso nao permitido para este perfil.")

    app = FastAPI()
    app.include_router(create_admin_rota_financeira_router(
        require_admin_panel_auth=auth,
        require_admin_panel_feature=feature,
        dclientes_query_service=FakeDClientes(),
        inadimplencia_query_service=Pronto(True),
        boletos_query_service=Pronto(boletos_prontos),
        rota_financeira_query_service=rota or FakeRota(),
        record_security_event=lambda *_args, **_kwargs: None,
        giro_vasilhame_service=giro,
        agora=lambda: datetime(2026, 11, 23, 21, 0),
    ))
    return TestClient(app)


def _nbs(response: Any) -> list[str]:
    return [c["cliente"] for c in response.json()["clientes"]]


class RotaEscopoTest(unittest.TestCase):
    def test_vendedor_ve_so_a_rota_dos_setores_dele(self) -> None:
        rota = FakeRota()
        response = _app(VENDEDOR_107, rota=rota).get("/api/admin/rota-financeira", params={"dia": "SEG"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(_nbs(response)), ["100", "101"])
        self.assertEqual(rota.chamadas[0]["allowed_sectors"], ["3_107"])

    def test_gv_so_recebe_os_gvs_da_carteira(self) -> None:
        opcoes = _app(GV_4).get("/api/admin/rota-financeira/opcoes").json()
        self.assertEqual(opcoes["gvs"], ["3_4"])
        self.assertEqual(sorted(item["setor"] for item in opcoes["setores"]), ["3_107", "3_108"])
        lista = _app(GV_4).get("/api/admin/rota-financeira", params={"dia": "SEG"})
        self.assertNotIn("300", _nbs(lista))

    def test_usuario_gv_ve_a_rota_inteira_do_gv(self) -> None:
        gerente = {**SEM_CARTEIRA, "gv_scopes": ("3-5",)}
        rota = FakeRota()
        response = _app(gerente, rota=rota).get("/api/admin/rota-financeira", params={"dia": "SEG"})
        self.assertEqual(_nbs(response), ["300"])
        self.assertEqual(rota.chamadas[0]["allowed_gv_vdes"], ["3_5"])
        opcoes = _app(gerente).get("/api/admin/rota-financeira/opcoes").json()
        self.assertEqual(opcoes["gvs"], ["3_5"])

    def test_usuario_com_operacao_ve_a_filial(self) -> None:
        patos = {**SEM_CARTEIRA, "filiais": ("3",)}
        rota = FakeRota()
        response = _app(patos, rota=rota).get("/api/admin/rota-financeira", params={"dia": "SEG"})
        self.assertEqual(sorted(_nbs(response)), ["100", "101", "200", "300"])
        self.assertEqual(rota.chamadas[0]["allowed_sectors"], ["filial:3"])
        fora = _app(patos, rota=FakeRota()).get("/api/admin/rota-financeira", params={"dia": "SEG", "filial": "4"})
        self.assertEqual(fora.json()["clientes"], [])

    def test_usuario_sem_escopo_nao_recebe_opcoes(self) -> None:
        response = _app(SEM_CARTEIRA).get("/api/admin/rota-financeira/opcoes")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("dias", response.json())

    def test_filtros_busca_e_pagina_nao_contornam_o_escopo(self) -> None:
        cliente = _app(VENDEDOR_107)
        for params in (
            {"dia": "SEG", "setor": "3_109"},
            {"dia": "SEG", "gv": "3_5"},
            {"dia": "SEG", "busca": "300"},
            {"dia": "SEG", "pagina": "2", "busca": "300"},
        ):
            with self.subTest(params=params):
                response = cliente.get("/api/admin/rota-financeira", params=params)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("300", _nbs(response))

    def test_filial_fora_do_escopo_do_financeiro_volta_vazio(self) -> None:
        financeiro = {"is_admin": False, "mode": "financeiro", "filiais": ("4",), "features": ("rota_financeira",)}
        rota = FakeRota()
        response = _app(financeiro, rota=rota).get("/api/admin/rota-financeira", params={"dia": "SEG", "filial": "3"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["clientes"], [])
        self.assertEqual(rota.chamadas, [])

    def test_permissao_de_clientes_nao_libera_a_rota(self) -> None:
        so_clientes = {**VENDEDOR_107, "features": ("cliente",)}
        self.assertEqual(_app(so_clientes).get("/api/admin/rota-financeira?dia=SEG").status_code, 403)

    def test_rota_exige_autenticacao_e_feature_rota_financeira(self) -> None:
        for path in ("/api/admin/rota-financeira/opcoes", "/api/admin/rota-financeira?dia=SEG"):
            with self.subTest(path=path):
                self.assertEqual(_app(None).get(path).status_code, 401)
                self.assertEqual(_app(SEM_FEATURE).get(path).status_code, 403)


class RotaPrioridadeTest(unittest.TestCase):
    def test_vencidos_aparecem_antes_dos_titulos_a_vencer(self) -> None:
        clientes = _app(GV_4).get("/api/admin/rota-financeira", params={"dia": "SEG"}).json()["clientes"]
        self.assertEqual([c["cliente"] for c in clientes], ["101", "200", "100"])
        self.assertEqual(clientes[0]["situacao"]["texto"], "Vencido há 10 dias")
        self.assertEqual(clientes[1]["situacao"]["texto"], "Vence hoje")

    def test_sem_03_02_06_os_titulos_continuam_aparecendo(self) -> None:
        response = _app(VENDEDOR_107, boletos_prontos=False).get("/api/admin/rota-financeira", params={"dia": "SEG"})
        self.assertEqual(response.status_code, 200)
        dados = response.json()
        self.assertFalse(dados["fontes"]["boletos"]["disponivel"])
        self.assertTrue(all(c["titulos"] for c in dados["clientes"]))
        filtro = _app(VENDEDOR_107, boletos_prontos=False).get("/api/admin/rota-financeira", params={"dia": "SEG", "situacao": "com_boleto"})
        self.assertEqual(filtro.status_code, 409)

    def test_titulo_sem_boleto_mostra_boleto_nao_importado(self) -> None:
        self.assertEqual(boleto_rotulo({"titulos": 2, "boletos": 0}, True)["texto"], "Boleto não importado")
        self.assertEqual(boleto_rotulo({"titulos": 2, "boletos": 1}, True)["texto"], "Boleto disponível (1)")
        self.assertEqual(boleto_rotulo({"titulos": 0, "boletos": 0}, True)["texto"], "Sem título")
        clientes = _app(VENDEDOR_107).get("/api/admin/rota-financeira", params={"dia": "SEG"}).json()["clientes"]
        self.assertEqual({c["cliente"]: c["boleto"]["texto"] for c in clientes}["100"], "Boleto não importado")

    def test_textos_de_situacao(self) -> None:
        self.assertEqual(situacao_rotulo({"titulos": 1, "menor_dias": -1})["texto"], "Vencido há 1 dia")
        self.assertEqual(situacao_rotulo({"titulos": 1, "menor_dias": 1})["texto"], "Vence amanhã")
        self.assertEqual(situacao_rotulo({"titulos": 1, "menor_dias": 2})["texto"], "Vence em 2 dias")
        self.assertEqual(situacao_rotulo({"titulos": 0, "menor_dias": None})["texto"], "Sem títulos em aberto")


class RotaGiroTest(unittest.TestCase):
    def test_filtro_sem_giro_leva_as_consultas_do_giro_do_mes(self) -> None:
        rota = FakeRota()
        for situacao in ("sem_giro_vasilhame", "sem_giro_equipamento"):
            resposta = _app(VENDEDOR_107, rota=rota, giro=FakeGiroVasilhame()).get("/api/admin/rota-financeira", params={"dia": "SEG", "situacao": situacao})
            self.assertEqual(resposta.status_code, 200, resposta.text)
            _ctes, params = rota.chamadas[-1]["giro"]
            self.assertIn("2026-11", params)  # compras do mês atual
            self.assertIn(["863059"], params)  # garrafeiras da tabela

    def test_filtros_comuns_nao_pagam_pelo_giro(self) -> None:
        rota = FakeRota()
        _app(VENDEDOR_107, rota=rota, giro=FakeGiroVasilhame()).get("/api/admin/rota-financeira", params={"dia": "SEG", "situacao": "vencidos"})
        self.assertIsNone(rota.chamadas[-1]["giro"])

    def test_sem_base_do_giro_avisa_em_vez_de_listar_errado(self) -> None:
        resposta = _app(VENDEDOR_107).get("/api/admin/rota-financeira", params={"dia": "SEG", "situacao": "sem_giro_vasilhame"})
        self.assertEqual(resposta.status_code, 409)


if __name__ == "__main__":
    unittest.main()
