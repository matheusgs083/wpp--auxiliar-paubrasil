from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "admin_import_panel.html"


def test_financeiro_preserva_assinatura_ao_editar_mapa() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'data-financeiro-cell="assinado"' in html
    assert 'value="${row.assinado ? "true" : "false"}"' in html


def test_financeiro_conferencia_salva_somente_detalhes_alterados() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'detail_fields: ["vales"]' in html
    assert 'detail_fields: ["despesas"]' in html
    assert "valeReviewChangedMapIds" in html


def test_financeiro_conferencia_exibe_vale_virtual_de_diarista() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'vale.origem === "diarista_sem_recibo"' in html
    assert "targetMap.vales.push(vale)" in html


def test_financeiro_refresh_preserva_editor_com_alteracoes_nao_salvas() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "function financeiroHasPendingEditorChanges()" in html
    assert "financeiroRender({ preserveEditor: true });" in html
    assert "financeiroRender({ preserveEditor: !refreshDraft });" in html


def test_financeiro_ignora_linha_de_vale_vazia_com_assinatura_oculta() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'if (type === "diaristas" || type === "vales")' in html
    assert 'return ["nome", "valor", "observacao"].some' in html


def test_painel_bloqueia_alteracao_de_numero_pela_roda_do_mouse() -> None:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "function setupNumberInputWheelGuard()" in html
    assert 'target.type !== "number"' in html
    assert 'event.preventDefault();' in html
    assert 'setupNumberInputWheelGuard();' in html
