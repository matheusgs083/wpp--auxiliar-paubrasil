from pathlib import Path

import pytest

from bot_api.services.admin_templates import AdminTemplateLoader, montar_template


TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def test_painel_montado_tem_todas_as_abas_e_nenhum_include_pendente() -> None:
    html = montar_template(TEMPLATES / "admin_import_panel.html")

    assert "<!--#include" not in html
    for aba in ("operationsPane", "payipPane", "reportsPane", "entregaPane", "promaxPane", "pedidosPane",
                "estoquePane", "armazemPane", "criticaPane", "financeiroPane", "protestosPane",
                "conferenciaPane", "giroRecolhaPane", "usageEvolutionPane"):
        assert f'id="{aba}"' in html
    assert "function init()" in html
    assert html.rstrip().endswith("</html>")


def test_loader_entrega_o_painel_montado(tmp_path: Path) -> None:
    loader = AdminTemplateLoader(
        import_panel_template=TEMPLATES / "admin_import_panel.html",
        login_template=tmp_path / "login.html",
        api_auth_enabled=True,
    )
    assert "<!--#include" not in loader.load_import_panel_html()


def test_include_resolve_arquivos_aninhados(tmp_path: Path) -> None:
    (tmp_path / "parte").mkdir()
    (tmp_path / "parte" / "a.html").write_text("<p>A</p>\n<!--#include parte/b.html -->\n", encoding="utf-8")
    (tmp_path / "parte" / "b.html").write_text("<p>B</p>", encoding="utf-8")
    (tmp_path / "base.html").write_text("<main>\n  <!--#include parte/a.html -->\n</main>\n", encoding="utf-8")

    assert montar_template(tmp_path / "base.html") == "<main>\n<p>A</p>\n<p>B</p>\n</main>\n"


def test_include_fora_da_pasta_e_recusado(tmp_path: Path) -> None:
    (tmp_path / "base.html").write_text("<!--#include ../segredo.txt -->\n", encoding="utf-8")
    with pytest.raises(ValueError):
        montar_template(tmp_path / "base.html")


def test_include_ausente_gera_erro(tmp_path: Path) -> None:
    (tmp_path / "base.html").write_text("<!--#include faltando.html -->\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        montar_template(tmp_path / "base.html")


def test_login_e_troca_de_senha_usam_o_simbolo_e_o_icone() -> None:
    for nome in ("admin_login.html", "admin_change_password.html", "admin_import_panel.html"):
        html = montar_template(TEMPLATES / nome)
        assert "<!--#include" not in html
        assert 'class="brand-symbol"' in html
        assert 'rel="icon"' in html
