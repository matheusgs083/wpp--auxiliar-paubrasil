from __future__ import annotations

import re

from bot_api.services import dprodutos_import_service as module
from bot_api.services.dprodutos_import_service import DProdutosImportService

# Ordem das colunas da view já criada nos bancos em uso. O Postgres só aceita
# CREATE OR REPLACE VIEW se estas continuarem nas mesmas posições.
COLUNAS_EXISTENTES = [
    "batch_id", "row_number", "codigo", "descricao", "pgv", "empresa", "tipo_marca", "linha_marca",
    "embalagem", "marca", "vasilhame", "grupo", "grupo_remuneracao", "ean", "familia_embalagem_siv",
    "codigo_produto_sap", "ncm", "cest", "codigo_unitario", "descricao_unitaria", "subtipo", "payload",
    "imported_at", "reference_date", "source_file", "file_hash", "batch_imported_at", "fator_hecto",
]


def test_view_dprodutos_latest_so_acrescenta_colunas_no_fim(monkeypatch):
    executed = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, query, *args):
            executed.append(str(query))

    class Conexao:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr(module, "resolve_effective_import_batch_id", lambda *a, **k: 1)
    service = DProdutosImportService.__new__(DProdutosImportService)
    service.schema = "reports"
    service._create_latest_view(Conexao())

    select = executed[0].split("SELECT", 1)[1].split("FROM", 1)[0]
    select = re.sub(r"--[^\n]*", "", select)
    colunas = [re.split(r"\s+AS\s+|\.", item.strip())[-1] for item in select.split(",") if item.strip()]
    assert colunas[: len(COLUNAS_EXISTENTES)] == COLUNAS_EXISTENTES
    assert "peso_bruto" in colunas[len(COLUNAS_EXISTENTES):]
