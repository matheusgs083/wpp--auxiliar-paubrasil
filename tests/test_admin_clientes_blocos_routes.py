from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot_api.routes.admin_clientes import create_admin_clientes_router
from bot_api.services.comodatos_query_service import vencimento_do_payload
from bot_api.tests.test_admin_clientes_routes import (
    ADMIN,
    CLIENTES,
    VENDEDOR_107,
    FakeBoletos,
    FakeDClientes,
    FakeInadimplencia,
    _no_escopo,
)

HOJE = date(2026, 11, 23)
GV_5 = {"is_admin": False, "mode": "usuario", "username": "gv5", "features": ("cliente",), "gv_scopes": ("3-5",)}
SO_ROTA = {"is_admin": False, "mode": "usuario", "username": "rota", "features": ("rota_financeira",), "seller_scopes": ("3-107",)}
BLOCOS = ("titulos", "credito", "compras", "vasilhames", "equipamentos", "comodatos", "devolucoes", "cadastro")


class Escopado:
    """Base dos fakes: só devolve dados quando o cliente está no escopo pedido."""

    def _permitido(self, cod_pdv: str, allowed_sectors: Any, allowed_gv_vdes: Any) -> bool:
        return _no_escopo(CLIENTES[str(cod_pdv)], allowed_sectors, allowed_gv_vdes)


class FakeComodatos(Escopado):
    def search_by_registration(self, filial: str, cod_pdv: str, allowed_sectors: Any = None, allowed_gv_vdes: Any = None, limit: int = 100) -> list[Any]:
        if not self._permitido(cod_pdv, allowed_sectors, allowed_gv_vdes):
            return []
        return [
            SimpleNamespace(nro_comodato="5521", material="REFRIGERADOR,BRAHMA,NORMAL PC,220W", sub_tipo_material="SOPI", saldo="1", valor="4.850,00", vencimento="10/01/2026", planilha_atualizada_em="22/11/2026"),
            SimpleNamespace(nro_comodato="5522", material="GARRAFEIRA PLAST PRETA 23 GARRAFAS 30OML", sub_tipo_material="GARRAFEIRA CERVEJA 1/2", saldo="10", vencimento="10/01/2027", planilha_atualizada_em="22/11/2026"),
        ]


class FakePrazo(Escopado):
    def search_by_registration(self, filial: str, cod_pdv: str, allowed_sectors: Any = None, allowed_gv_vdes: Any = None, limit: int = 50) -> list[Any]:
        if not self._permitido(cod_pdv, allowed_sectors, allowed_gv_vdes):
            return []
        entrada = SimpleNamespace(kpi="Mês atual", percentual_pag_atraso="4%", prazo_atual="21 dias", cond_pag_atual="505", limite_total="10.000,00", faturamento_com_pdv="R$ 3.000,00", pedidos="3")
        return [SimpleNamespace(entries=(entrada,), planilha_atualizada_em="20/11/2026")]


class FakeGiroVasilhame:
    def __init__(self) -> None:
        self.pedidos: list[tuple[str, str, str]] = []

    def catalogo(self) -> dict[str, dict[str, str]]:
        return {"863059": {"descricao": "GARRAFEIRA PLAST PRETA 23 GARRAFAS 30OML", "tipo": "litrinho"}}

    def caixas_compradas(self, filial: str, cliente: str, competencia: str) -> dict[str, float]:
        self.pedidos.append((filial, cliente, competencia))
        return {"litrinho": 12.0, "inteira": 5.0, "litrao": 0.0}


class FakeGiroEquipamentos:
    def __init__(self) -> None:
        self.pedidos: list[tuple[str, str, str]] = []

    def compras_por_cesta(self, filial: str, cliente: str, competencia: str) -> dict[str, Decimal]:
        self.pedidos.append((filial, cliente, competencia))
        return {"Cerveja TT": Decimal("1200"), "Refrigerante TT": Decimal("5000")}

    def produtos_da_cesta(self, filial: str, cliente: str, competencias: list[str]) -> list[dict[str, Any]]:
        return [{"competencia": competencias[-1], "produto": "1", "descricao": "SKOL LATA 350ML", "total": Decimal("1200"), "ultima_data": None}]


class FakeDocumentos(Escopado):
    def search_by_registration(self, filial: str, cod_pdv: str, allowed_sectors: Any = None, allowed_gv_vdes: Any = None, limit: int = 20) -> list[Any]:
        if not self._permitido(cod_pdv, allowed_sectors, allowed_gv_vdes):
            return []
        return [SimpleNamespace(contrato_social="OK", comprovante_residencia="PENDENTE", cpf="OK", rg="PENDENTE", fachada="OK", ficha_cadastro="OK", pending_count=2)]


class FakeCompras:
    def __init__(self, disponivel: bool = True) -> None:
        self.disponivel = disponivel
        self.pedidos: list[tuple[str, str]] = []

    def resumo_cliente(self, filial: str, cliente: str, *, hoje: date) -> dict[str, Any]:
        if not self.disponivel:
            raise RuntimeError("banco fora")
        self.pedidos.append((filial, cliente))
        serie = [
            {"competencia": "2026-08", "total": 1000.0, "notas": 2, "com_base": True, "atual": False},
            {"competencia": "2026-09", "total": 0.0, "notas": 0, "com_base": True, "atual": False},
            {"competencia": "2026-10", "total": 3500.0, "notas": 4, "com_base": True, "atual": False},
            {"competencia": "2026-11", "total": 700.0, "notas": 1, "com_base": True, "atual": True},
        ]
        return {"base_desde": "2026-08", "media_3_meses": 1500.0, "atualizado_em": "2026-11-20T08:00:00", "serie": serie, "mes_atual": serie[-1]}

    def devolucoes_cliente(self, filial: str, cliente: str, *, desde: date) -> list[dict[str, Any]]:
        if not self.disponivel:
            raise RuntimeError("banco fora")
        return [{"data": "2026-11-06", "nota": "231577", "serie": "003", "nf_referencia": "39254", "motivo_codigo": "1", "motivo": "FALTA CAMINHAO", "responsabilidade": "LOGISTICA", "itens": 3, "qtde": 10.0, "total": 5981.6}]

    def atualizado_em(self, filial: str) -> str:
        return "2026-11-20T08:00:00"


def _app(context: dict[str, Any] | None, *, compras: Any = None, inadimplencia: Any = None, boletos: Any = None) -> TestClient:
    def auth(**_kwargs: Any) -> dict[str, Any]:
        if context is None:
            raise HTTPException(status_code=401, detail="Sessão expirada.")
        return dict(context)

    def feature(ctx: dict[str, Any] | None, nome: str) -> None:
        if not ctx or not (ctx.get("is_admin") or nome in ctx.get("features", ())):
            raise HTTPException(status_code=403, detail="Acesso nao permitido para este perfil.")

    app = FastAPI()
    app.include_router(create_admin_clientes_router(
        require_admin_panel_auth=auth,
        require_admin_panel_feature=feature,
        dclientes_query_service=FakeDClientes(),
        inadimplencia_query_service=inadimplencia or FakeInadimplencia(),
        comodatos_query_service=FakeComodatos(),
        boletos_query_service=boletos or FakeBoletos(),
        record_security_event=lambda *_args, **_kwargs: None,
        prazo_limite_query_service=FakePrazo(),
        giro_vasilhame_service=FakeGiroVasilhame(),
        giro_equipamentos_service=FakeGiroEquipamentos(),
        documentacao_pendente_query_service=FakeDocumentos(),
        compras_030237_service=compras or FakeCompras(),
        hoje=lambda: HOJE,
    ))
    return TestClient(app)


def _bloco(cliente: TestClient, nb: str, bloco: str) -> Any:
    return cliente.get(f"/api/admin/clientes/3/{nb}/blocos/{bloco}")


class EscopoDosBlocosTest(unittest.TestCase):
    def test_vendedor_abre_todos_os_blocos_do_proprio_cliente(self) -> None:
        cliente = _app(VENDEDOR_107)
        for bloco in BLOCOS:
            resposta = _bloco(cliente, "100", bloco)
            self.assertEqual(resposta.status_code, 200, bloco)
            self.assertEqual(resposta.json()["bloco"], bloco)

    def test_cliente_fora_do_escopo_nao_devolve_bloco_nem_cabecalho(self) -> None:
        compras = FakeCompras()
        cliente = _app(VENDEDOR_107, compras=compras)
        self.assertEqual(cliente.get("/api/admin/clientes/3/200/cabecalho").status_code, 403)
        for bloco in BLOCOS:
            resposta = _bloco(cliente, "200", bloco)
            self.assertEqual(resposta.status_code, 403, bloco)
            self.assertNotIn("dados", resposta.json())
        self.assertEqual(compras.pedidos, [])

    def test_gv_ve_os_blocos_do_cliente_do_gv(self) -> None:
        cliente = _app(GV_5)
        self.assertEqual(_bloco(cliente, "300", "titulos").status_code, 200)
        self.assertEqual(_bloco(cliente, "100", "titulos").status_code, 403)

    def test_quem_so_tem_rota_financeira_abre_os_blocos(self) -> None:
        self.assertEqual(_bloco(_app(SO_ROTA), "100", "compras").status_code, 200)

    def test_pdf_do_boleto_exige_escopo(self) -> None:
        self.assertEqual(_app(VENDEDOR_107).get("/api/admin/clientes/3/200/boletos/09123456/pdf").status_code, 403)
        self.assertEqual(_app(VENDEDOR_107).get("/api/admin/clientes/3/100/boletos/09123456/pdf").status_code, 200)

    def test_bloco_desconhecido(self) -> None:
        self.assertEqual(_bloco(_app(ADMIN), "100", "senhas").status_code, 404)


class ConteudoDosBlocosTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cliente = _app(VENDEDOR_107)

    def dados(self, bloco: str) -> dict[str, Any]:
        resposta = _bloco(self.cliente, "100", bloco)
        self.assertEqual(resposta.status_code, 200)
        return resposta.json()

    def test_titulo_com_boleto_vinculado_traz_linha_digitavel(self) -> None:
        bloco = self.dados("titulos")
        titulo = next(t for t in bloco["dados"]["titulos"] if t["nota_fiscal"] == "183201")
        self.assertEqual(titulo["situacao_boleto"], "Boleto disponível")
        self.assertTrue(titulo["boleto"]["linha_digitavel"].startswith("23790"))
        self.assertEqual(bloco["resumo"], "R$ 1.870,00 em 2 títulos, 1 vencido")

    def test_titulo_sem_boleto_mostra_boleto_nao_importado(self) -> None:
        titulo = next(t for t in self.dados("titulos")["dados"]["titulos"] if t["nota_fiscal"] == "183644")
        self.assertIsNone(titulo["boleto"])
        self.assertEqual(titulo["situacao_boleto"], "Boleto não importado")

    def test_credito_traz_faturamento_e_notas_da_030237(self) -> None:
        faturamento = self.dados("credito")["dados"]["faturamento"]
        self.assertEqual(faturamento[0], {"kpi": "11/2026 (parcial)", "faturamento_com_pdv": "R$ 700,00", "pedidos": "1"})
        self.assertEqual(faturamento[-1]["kpi"], "Média mensal (3 meses)")
        self.assertEqual(faturamento[-1]["faturamento_com_pdv"], "R$ 1.500,00")

    def test_comodatos_contam_os_vencidos_pela_data(self) -> None:
        bloco = self.dados("comodatos")
        self.assertEqual(bloco["resumo"], "2 itens, 1 com contrato vencido")
        self.assertEqual([i["vencido"] for i in bloco["dados"]["itens"]], [True, False])

    def test_documentos_pendentes_no_cadastro(self) -> None:
        bloco = self.dados("cadastro")
        self.assertEqual(bloco["resumo"], "Setor 107 · Terça · 2 documentos pendentes")
        docs = {d["rotulo"]: d["ok"] for d in bloco["dados"]["documentacao"]["itens"]}
        self.assertFalse(docs["Identidade"])  # RG pendente, mesmo com CPF OK
        self.assertTrue(docs["Contrato social"])
        self.assertEqual(bloco["dados"]["documento"], "12.345.678/0001-90")

    def test_credito_mostra_disponivel_calculado(self) -> None:
        bloco = self.dados("credito")
        self.assertEqual(bloco["dados"]["limite_disponivel"], "8.130,00")
        self.assertTrue(bloco["dados"]["limite_disponivel_calculado"])
        self.assertIn("Prazo atual 21 dias", bloco["resumo"])

    def test_giro_de_vasilhames_pede_o_dobro_das_caixas_em_comodato(self) -> None:
        vasilhames = self.dados("vasilhames")
        litrinho = next(t for t in vasilhames["dados"]["tipos"] if t["tipo"] == "litrinho")
        self.assertEqual((litrinho["caixas"], litrinho["meta"], litrinho["compradas"], litrinho["falta"]), ("10", "20", "12", "8"))
        self.assertTrue(litrinho["em_risco"])
        inteira = next(t for t in vasilhames["dados"]["tipos"] if t["tipo"] == "inteira")
        self.assertFalse(inteira["em_risco"])  # comprou, mas não tem garrafeira de inteira em comodato
        self.assertEqual(vasilhames["resumo"], "1 vasilhame em risco de não bater o giro")

    def test_giro_de_vasilhames_separado_do_giro_comercial(self) -> None:
        vasilhames = self.dados("vasilhames")
        compras = self.dados("compras")
        self.assertEqual(compras["fonte"]["nome"], "03.02.37")
        self.assertNotIn("tipos", compras["dados"])
        self.assertNotIn("media_3_meses", vasilhames["dados"])

    def test_compras_e_devolucoes(self) -> None:
        self.assertEqual(self.dados("compras")["resumo"], "Média mensal entregue (3 meses): R$ 1.500,00")
        devolucoes = self.dados("devolucoes")
        self.assertEqual(devolucoes["resumo"], "1 devolução recente")
        self.assertEqual(devolucoes["dados"]["itens"][0]["responsabilidade"], "LOGISTICA")

    def test_sopi_pede_2000_de_cerveja_no_mes(self) -> None:
        bloco = self.dados("equipamentos")
        sopi = next(t for t in bloco["dados"]["tipos"] if t["tipo"] == "sopi")
        self.assertEqual((sopi["equipamentos"], sopi["meta"], sopi["comprado"], sopi["falta"]), (1, "2.000,00", "1.200,00", "800,00"))
        self.assertTrue(sopi["em_risco"])
        visa = next(t for t in bloco["dados"]["tipos"] if t["tipo"] == "visa")
        self.assertFalse(visa["em_risco"])  # comprou refrigerante, mas não tem Visa em comodato
        self.assertEqual(sopi["valor_equipamentos"], "4.850,00")
        self.assertEqual(sopi["situacao"], "em_risco")  # 1.200 até o dia 23: prevê 1.565,22
        self.assertEqual(bloco["dados"]["mix"]["skus_mes"], 1)
        self.assertEqual(bloco["resumo"], "SOPI: abaixo da meta no ritmo atual · mix de cerveja 1 de 10 SKUs")

    def test_cabecalho_traz_contato_e_mapa(self) -> None:
        cabecalho = self.cliente.get("/api/admin/clientes/3/100/cabecalho").json()["cliente"]
        self.assertEqual(cabecalho["telefone_whatsapp"], "5583998123344")
        self.assertIn("google.com/maps", cabecalho["mapa_url"])
        self.assertEqual(cabecalho["blocos"], list(BLOCOS))


class VencimentoComodatoTest(unittest.TestCase):
    def test_le_a_coluna_de_vencimento_da_02_02_20(self) -> None:
        self.assertEqual(vencimento_do_payload({"Nro Comodato": "1", "Dt. Vencimento": "10/01/2026"}), "10/01/2026")
        self.assertEqual(vencimento_do_payload({"Data Vencimento Contrato": "2026-01-10"}), "10/01/2026")

    def test_data_vazia_do_promax_nao_vira_vencimento(self) -> None:
        self.assertEqual(vencimento_do_payload({"Dt. Vencimento": "00/00/0000"}), "")
        self.assertEqual(vencimento_do_payload({"Vencimento": "31/12/2199"}), "")  # permanente

    def test_usa_a_coluna_vencimento_e_nao_o_vencimento_do_credito(self) -> None:
        payload = {"Data 1o. Venc.": "08/09/2026", "Saldo CR Venc.": "32.397,47", "Vencimento": "25/02/2020"}
        self.assertEqual(vencimento_do_payload(payload), "25/02/2020")
        self.assertEqual(vencimento_do_payload({"Saldo": "1"}), "")
        self.assertEqual(vencimento_do_payload(None), "")


class FonteForaDoArTest(unittest.TestCase):
    def test_uma_fonte_fora_nao_derruba_as_outras(self) -> None:
        cliente = _app(VENDEDOR_107, compras=FakeCompras(disponivel=False), inadimplencia=FakeInadimplencia(disponivel=False))
        compras = _bloco(cliente, "100", "compras")
        titulos = _bloco(cliente, "100", "titulos")
        self.assertEqual(compras.status_code, 200)
        self.assertEqual(compras.json()["estado"], "indisponivel")
        self.assertEqual(titulos.json()["estado"], "indisponivel")
        for bloco in ("vasilhames", "comodatos", "cadastro"):
            self.assertEqual(_bloco(cliente, "100", bloco).json()["estado"], "ok", bloco)


if __name__ == "__main__":
    unittest.main()
