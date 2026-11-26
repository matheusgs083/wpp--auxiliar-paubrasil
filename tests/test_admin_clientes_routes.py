from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bot_api.routes.admin_clientes import create_admin_clientes_router, situacao_vencimento, telefone_whatsapp
from bot_api.services.clientes_escopo import telefone_discagem

VENDEDOR_107 = {"is_admin": False, "mode": "usuario", "username": "rn107", "features": ("cliente",), "seller_scopes": ("3-107",)}
GV_4 = {"is_admin": False, "mode": "usuario", "username": "gv4", "features": ("cliente",), "seller_scopes": ("3-107", "3-108")}
ADMIN = {"is_admin": True, "mode": "admin", "username": "admin", "features": ()}
SEM_FEATURE = {"is_admin": False, "mode": "usuario", "username": "x", "features": ("pedidos",), "seller_scopes": ("3-107",)}


def _cliente(nb: str, nome: str, setor: str, gv: str = "4", filial: str = "3") -> SimpleNamespace:
    return SimpleNamespace(
        filial=filial, cod_pdv=nb, razao_social=f"{nome} LTDA", nome_fantasia=nome, telefone="(83) 99812-3344",
        dia_visita="Terça", vendedor=setor, status="Ativo", cidade="Patos", cond_pag_atual="505",
        limite_credito="80000,00", total_pendente="1870,00", total_comodatos_pendentes=1,
        ultima_atualizacao_tabela="22/11/2026", gv=gv,
    )


CLIENTES = {
    "100": _cliente("100", "MERCADO DO SETOR 107", "107"),
    "200": _cliente("200", "MERCADO DO SETOR 108", "108"),
    "300": _cliente("300", "MERCADO DO GV 5", "109", gv="5"),
    "400": _cliente("400", "MERCADO DE SUME", "201", gv="1", filial="4"),
}


def _no_escopo(cliente: SimpleNamespace, allowed_sectors: list[str] | None, allowed_gv_vdes: list[str] | None = None) -> bool:
    """Mesma regra do dClientes: setor, operação (filial:N) ou GV, combinados com OU."""
    if allowed_sectors is None and allowed_gv_vdes is None:
        return True
    setores = allowed_sectors or []
    return (
        f"{cliente.filial}_{cliente.vendedor}" in setores
        or f"filial:{cliente.filial}" in setores
        or f"{cliente.filial}_{cliente.gv}" in (allowed_gv_vdes or [])
    )


class FakeDClientes:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, Any]] = []

    def search_by_registration(self, filial: str, cod_pdv: str, allowed_sectors: list[str] | None = None, allowed_gv_vdes: list[str] | None = None) -> list[Any]:
        self.chamadas.append(("registro", allowed_sectors))
        item = CLIENTES.get(str(cod_pdv))
        return [item] if item and item.filial == str(filial) and _no_escopo(item, allowed_sectors, allowed_gv_vdes) else []

    def search_by_fantasia(self, query_text: str, allowed_sectors: list[str] | None = None, allowed_gv_vdes: list[str] | None = None, limit: int = 5, filial: str | None = None) -> list[Any]:
        self.chamadas.append(("nome", allowed_sectors))
        return [c for c in CLIENTES.values() if (query_text.upper() in c.nome_fantasia or query_text.upper() in c.razao_social) and (not filial or c.filial == filial) and _no_escopo(c, allowed_sectors, allowed_gv_vdes)][:limit]

    def search_by_document(self, document: str, allowed_sectors: list[str] | None = None, allowed_gv_vdes: list[str] | None = None, limit: int = 20, filial: str | None = None) -> list[Any]:
        return [c for c in CLIENTES.values() if document in ("12345678000190", "12345678901") and (not filial or c.filial == filial) and _no_escopo(c, allowed_sectors, allowed_gv_vdes)][:limit]

    def get_payip_profile_by_registration(self, filial: str, cod_pdv: str) -> Any:
        return SimpleNamespace(documento="12345678000190", email="a@b.com", endereco="Rua A", numero="10", complemento="", bairro="Centro", cidade="Patos", uf="PB", cep="58700000")


class FakeInadimplencia:
    def __init__(self, disponivel: bool = True) -> None:
        self.disponivel = disponivel

    def search_by_registration(self, filial: str, cod_pdv: str, allowed_sectors: list[str] | None = None, allowed_gv_vdes: list[str] | None = None, limit: int = 50) -> list[Any]:
        if not self.disponivel:
            raise RuntimeError("Views reports.inadimplencia_latest nao encontradas.")
        if not _no_escopo(CLIENTES[str(cod_pdv)], allowed_sectors, allowed_gv_vdes):
            return []
        comum = {"filial": "3", "cod_pdv": cod_pdv, "nome": "", "data_emissao": "20/10/2026", "valor_original": "1200,00", "valor_corrigido": "1236,40", "planilha_atualizada_em": "22/11/2026"}
        return [
            SimpleNamespace(**comum, nota_fiscal="183201", data_vencimento="10/11/2026", valor_pendente="1200,00", dias="-13"),
            SimpleNamespace(**comum, nota_fiscal="183644", data_vencimento="23/11/2026", valor_pendente="670,00", dias="0"),
        ]


class FakeComodatos:
    def search_by_registration(self, filial: str, cod_pdv: str, allowed_sectors: list[str] | None = None, allowed_gv_vdes: list[str] | None = None, limit: int = 100) -> list[Any]:
        return [SimpleNamespace(nro_comodato="5521", material="Geladeira Brahma", sub_tipo_material="Refrigerador", saldo="1")]


class FakeBoletos:
    def __init__(self) -> None:
        self.include_pdf: list[bool] = []

    def status(self) -> dict[str, Any]:
        return {"ready": True}

    def search_by_registration(self, *, filial: str, cod_pdv: str, allowed_sectors: Any = None, allowed_gv_vdes: Any = None, limit: int = 5, include_pdf: bool = True) -> list[Any]:
        self.include_pdf.append(include_pdf)
        if not _no_escopo(CLIENTES[str(cod_pdv)], allowed_sectors, allowed_gv_vdes):
            return []
        return [SimpleNamespace(
            nosso_numero="09123456", nota_fiscal="183201", num_documento="183201/1",
            linha_digitavel="23790.12345 60000.123456 78000.123405 1 98760000120000",
            vencimento=date(2026, 11, 10), valor_centavos=120000,
            pdf_bytes=b"%PDF-1.4 boleto" if include_pdf else b"",
        )]


def _app(context: dict[str, Any] | None, *, inadimplencia: Any = None, boletos: Any = None, dclientes: Any = None) -> TestClient:
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
        dclientes_query_service=dclientes or FakeDClientes(),
        inadimplencia_query_service=inadimplencia or FakeInadimplencia(),
        comodatos_query_service=FakeComodatos(),
        boletos_query_service=boletos or FakeBoletos(),
        record_security_event=lambda *_args, **_kwargs: None,
    ))
    return TestClient(app)


class ClientesEscopoTest(unittest.TestCase):
    def test_busca_livre_entre_setores_filiais_e_sem_carteira(self) -> None:
        for context in (VENDEDOR_107, GV_4, {**VENDEDOR_107, "seller_scopes": ()}):
            response = _app(context).get("/api/admin/clientes", params={"busca": "mercado"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(sorted(c["cliente"] for c in response.json()["clientes"]), ["100", "200", "300", "400"])

    def test_busca_por_fantasia_razao_documento_e_nb(self) -> None:
        client = _app(VENDEDOR_107)
        for busca in ("MERCADO DO SETOR 108", "SETOR 108 LTDA"):
            self.assertEqual(client.get("/api/admin/clientes", params={"busca": busca}).json()["clientes"][0]["cliente"], "200")
        for documento in ("12345678000190", "12.345.678/0001-90", "12345678901", "123.456.789-01"):
            resposta = client.get("/api/admin/clientes", params={"busca": documento, "filial": "4"})
            self.assertEqual([c["cliente"] for c in resposta.json()["clientes"]], ["400"])
        resposta = client.get("/api/admin/clientes", params={"busca": "200", "filial": "3"})
        self.assertEqual(resposta.json()["clientes"][0]["cliente"], "200")
        self.assertEqual(client.get("/api/admin/clientes", params={"busca": "200"}).status_code, 422)

    def test_ficha_e_boleto_de_outro_setor(self) -> None:
        cliente = _app(VENDEDOR_107)
        self.assertEqual(cliente.get("/api/admin/clientes/3/200").status_code, 200)
        self.assertEqual(cliente.get("/api/admin/clientes/3/200/boletos/09123456/pdf").status_code, 200)
        self.assertEqual(cliente.get("/api/admin/clientes/3/999").status_code, 403)

    def test_cliente_no_escopo_abre_boleto_pdf(self) -> None:
        response = _app(VENDEDOR_107).get("/api/admin/clientes/3/100/boletos/09123456/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_rotas_exigem_autenticacao_e_feature_cliente(self) -> None:
        for path in ("/api/admin/clientes?busca=mercado", "/api/admin/clientes/3/100", "/api/admin/clientes/3/100/boletos/09123456/pdf"):
            with self.subTest(path=path):
                self.assertEqual(_app(None).get(path).status_code, 401)
                self.assertEqual(_app(SEM_FEATURE).get(path).status_code, 403)


class ClientesPermissaoRotaTest(unittest.TestCase):
    """Quem só tem a Rota Financeira abre o detalhe e o boleto, mas não pesquisa clientes."""

    SO_ROTA = {**VENDEDOR_107, "features": ("rota_financeira",)}

    def test_rota_financeira_abre_detalhe_e_pdf(self) -> None:
        cliente = _app(self.SO_ROTA)
        self.assertEqual(cliente.get("/api/admin/clientes/3/100").status_code, 200)
        self.assertEqual(cliente.get("/api/admin/clientes/3/100/boletos/09123456/pdf").status_code, 200)

    def test_rota_financeira_nao_pesquisa_na_aba_clientes(self) -> None:
        self.assertEqual(_app(self.SO_ROTA).get("/api/admin/clientes", params={"busca": "mercado"}).status_code, 403)

    def test_rota_financeira_continua_presa_ao_escopo(self) -> None:
        self.assertEqual(_app(self.SO_ROTA).get("/api/admin/clientes/3/200").status_code, 403)


class ClientesFichaTest(unittest.TestCase):
    def test_cadastro_abre_mesmo_sem_12_06_01(self) -> None:
        response = _app(VENDEDOR_107, inadimplencia=FakeInadimplencia(disponivel=False)).get("/api/admin/clientes/3/100")
        self.assertEqual(response.status_code, 200)
        ficha = response.json()
        self.assertEqual(ficha["cliente"]["cliente"], "100")
        self.assertFalse(ficha["financeiro"]["fonte"]["disponivel"])
        self.assertEqual(ficha["financeiro"]["titulos"], [])

    def test_titulo_sem_boleto_fica_marcado_sem_boleto(self) -> None:
        titulos = _app(VENDEDOR_107).get("/api/admin/clientes/3/100").json()["financeiro"]["titulos"]
        por_nf = {t["nota_fiscal"]: t for t in titulos}
        self.assertEqual(por_nf["183201"]["boleto"]["nosso_numero"], "09123456")
        self.assertIsNone(por_nf["183644"]["boleto"])
        self.assertEqual(por_nf["183201"]["situacao"], "vencido")
        self.assertEqual(por_nf["183644"]["situacao"], "hoje")

    def test_cliente_com_comodato_exibe_itens_da_02_02_20(self) -> None:
        ficha = _app(VENDEDOR_107).get("/api/admin/clientes/3/100").json()
        self.assertEqual(ficha["comodatos"]["itens"][0]["material"], "Geladeira Brahma")
        self.assertEqual(ficha["kpis"]["comodatos"], 1)

    def test_linha_digitavel_vem_na_ficha_sem_baixar_pdf(self) -> None:
        boletos = FakeBoletos()
        ficha = _app(VENDEDOR_107, boletos=boletos).get("/api/admin/clientes/3/100").json()
        self.assertTrue(ficha["boletos"]["itens"][0]["linha_digitavel"].startswith("23790"))
        self.assertEqual(boletos.include_pdf, [False])


class ClientesFormatacaoTest(unittest.TestCase):
    def test_situacao_do_vencimento(self) -> None:
        self.assertEqual([situacao_vencimento(d) for d in (-1, 0, 1, 2, 3, None)], ["vencido", "hoje", "amanha", "dois_dias", "em_dia", "sem_data"])

    def test_telefone_whatsapp_so_quando_confiavel(self) -> None:
        self.assertEqual(telefone_whatsapp("(83) 99812-3344"), "5583998123344")
        self.assertEqual(telefone_whatsapp("99812-3344"), "")
        self.assertEqual(telefone_whatsapp(""), "")

    def test_varios_numeros_no_cadastro(self) -> None:
        self.assertEqual(telefone_whatsapp("83 99889-1242 | 83 99889-1242"), "5583998891242")
        self.assertEqual(telefone_whatsapp("83 3421-0000 | 83 98166-8118"), "5583981668118")
        self.assertEqual(telefone_whatsapp("83 3421-0000"), "558334210000")
        self.assertEqual(telefone_discagem("83 99934-1835 | 83 99934-1835 | 83 98116-5271"), "83999341835")


if __name__ == "__main__":
    unittest.main()
