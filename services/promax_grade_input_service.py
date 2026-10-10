"""Validated CSV input for the Promax 02.01.05 stock-count grid."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from unicodedata import normalize as unicode_normalize


MAX_CSV_BYTES = 2_000_000
MAX_CSV_ROWS = 2_000
MAX_BATCHES = 50

_ALIASES = {
    "armazem": {"armazem", "almoxarifado"},
    "deposito": {"deposito"},
    "data_movimento": {"data_movimento", "data", "dt_movimento", "dtmovimento"},
    "codigo": {"item", "codigo", "codigo_item", "cditem"},
    "pallet": {"pallet", "qt_pallet", "qtpallet"},
    "lastro": {"lastro", "qt_lastro", "qtlastro"},
    "sku": {"sku", "caixa", "qt_caixa", "qtcaixa"},
    "unidade": {"unidade", "avulsa", "qt_unidade", "qtunidade"},
    "garrafa": {"garrafa", "cd_garrafa", "cdgarrafa"},
}
_REQUIRED = ("armazem", "deposito", "data_movimento", "codigo")


def _header(value: Any) -> str:
    text = unicode_normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return "".join(char for char in text.casefold() if char.isalnum() or char == "_")


def _integer(value: Any, *, field: str, line: int) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit():
        raise ValueError(f"Linha {line}: {field} deve ser inteiro nao negativo.")
    return int(text)


def _code(value: Any, *, field: str, line: int) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not text.isdigit():
        raise ValueError(f"Linha {line}: {field} deve ser numerico e informado.")
    return text


def parse_grade_csv(content: bytes) -> list[dict[str, Any]]:
    """Return grouped, driver-ready grade launches and preserve original CSV lines."""
    if not content:
        raise ValueError("Envie um CSV com os itens da grade.")
    if len(content) > MAX_CSV_BYTES:
        raise ValueError("O CSV excede o limite de 2 MB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("CSV sem cabecalho.")
    fields = {_header(name): name for name in reader.fieldnames if name}
    columns: dict[str, str] = {}
    for target, aliases in _ALIASES.items():
        source = next((fields[alias] for alias in aliases if alias in fields), None)
        if source:
            columns[target] = source
    missing = [field for field in _REQUIRED if field not in columns]
    if missing:
        raise ValueError("CSV sem coluna obrigatoria: " + ", ".join(missing) + ".")

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line, row in enumerate(reader, start=2):
        if line - 1 > MAX_CSV_ROWS:
            raise ValueError(f"CSV excede o limite de {MAX_CSV_ROWS} itens.")
        if not isinstance(row, Mapping) or not any(str(value or "").strip() for value in row.values()):
            continue
        armazem = _code(row.get(columns["armazem"]), field="armazem", line=line)
        deposito = _code(row.get(columns["deposito"]), field="deposito", line=line)
        data = str(row.get(columns["data_movimento"]) or "").strip()
        try:
            datetime.strptime(data, "%d/%m/%Y")
        except ValueError as exc:
            raise ValueError(f"Linha {line}: data_movimento deve usar DD/MM/AAAA.") from exc
        item = {"codigo": _code(row.get(columns["codigo"]), field="item", line=line), "source_row": line}
        for field in ("pallet", "lastro", "sku", "unidade"):
            item[field] = _integer(row.get(columns[field]) if field in columns else "", field=field, line=line)
        if not any(item[field] for field in ("pallet", "lastro", "sku", "unidade")):
            raise ValueError(f"Linha {line}: informe pallet, lastro, sku ou unidade.")
        if "garrafa" in columns and str(row.get(columns["garrafa"]) or "").strip():
            item["garrafa"] = str(row[columns["garrafa"]]).strip()
        key = (armazem, deposito, data)
        group = groups.setdefault(key, {"armazem": armazem, "deposito": deposito, "data_movimento": data, "itens": []})
        group["itens"].append(item)
    if not groups:
        raise ValueError("CSV sem itens validos.")
    if len(groups) > MAX_BATCHES:
        raise ValueError(f"CSV excede o limite de {MAX_BATCHES} lancamentos distintos.")
    return list(groups.values())


def parse_grade_020304_csv(content: bytes) -> list[dict[str, Any]]:
    """CSV da 02.03.01: grade, produto e entrada de outra unidade."""
    if not content or len(content) > MAX_CSV_BYTES:
        raise ValueError("CSV inválido ou acima de 2 MB.")
    text = content.decode("utf-8-sig")
    delimiter = ";" if text[:4096].count(";") >= text[:4096].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fields = {_header(name): name for name in reader.fieldnames or []}
    grade_column = fields.get("grade") or fields.get("nr_grade_armazem")
    product_column = fields.get("produto") or fields.get("codigo_produto") or fields.get("item")
    qty_column = fields.get("quantidade") or fields.get("fabricado_outra_unidade") or fields.get("natureza2")
    if not all((grade_column, product_column, qty_column)):
        raise ValueError("CSV requer as colunas: grade; produto; quantidade.")
    batches: dict[str, dict[str, Any]] = {}
    for line, row in enumerate(reader, start=2):
        grade = _code(row.get(grade_column), field="grade", line=line)
        produto = _code(row.get(product_column), field="produto", line=line)
        quantidade = _integer(row.get(qty_column), field="quantidade", line=line)
        if quantidade < 0:
            raise ValueError(f"Linha {line}: quantidade nao pode ser negativa.")
        batches.setdefault(grade, {"grade": grade, "itens": []})["itens"].append({"produto": produto, "quantidade": quantidade, "source_row": line})
    if not batches:
        raise ValueError("CSV sem itens válidos.")
    return list(batches.values())
