from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ROUTINE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MAX_MANIFEST_BYTES = 128 * 1024
_MISSING = object()


def discover_report_catalog(driver_dir: str | Path) -> dict[str, Any]:
    groups_dir = Path(driver_dir).expanduser().resolve() / "report_groups"
    categories: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    if not groups_dir.is_dir():
        return {
            "categories": {},
            "warnings": [f"Diretorio de grupos nao encontrado: {groups_dir}"],
        }

    for manifest_path in sorted(groups_dir.glob("*.py"), key=lambda path: path.name.lower()):
        if manifest_path.name.startswith("_"):
            continue
        try:
            category = read_report_group_manifest(manifest_path)
        except (OSError, SyntaxError, ValueError) as exc:
            warnings.append(f"{manifest_path.name}: {exc}")
            continue
        category_key = category["key"]
        if category_key in categories:
            warnings.append(
                f"{manifest_path.name}: grupo duplicado {category_key}")
            continue
        categories[category_key] = category

    return {
        "categories": categories,
        "warnings": warnings,
    }


def read_report_group_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("arquivo excede o limite de 128 KiB")
    source = manifest_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(manifest_path))
    if len(tree.body) != 1:
        raise ValueError(
            "arquivo deve conter somente a atribuicao literal REPORT_GROUP")
    manifest_value: Any = _MISSING
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(
            node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "REPORT_GROUP" for target in targets):
            continue
        if manifest_value is not _MISSING:
            raise ValueError("REPORT_GROUP deve ser declarado apenas uma vez")
        value_node = node.value
        if value_node is None:
            raise ValueError("REPORT_GROUP nao possui valor")
        try:
            manifest_value = ast.literal_eval(value_node)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "REPORT_GROUP deve ser um literal Python") from exc

    if manifest_value is _MISSING:
        raise ValueError("REPORT_GROUP nao encontrado")
    return normalize_report_group(manifest_value)


def normalize_report_group(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("REPORT_GROUP deve ser um dicionario")
    key = str(value.get("key") or "").strip().lower()
    if not _CATEGORY_PATTERN.fullmatch(key):
        raise ValueError("key de grupo invalida")
    name = _limited_text(value.get("name") or key,
                         field_name="name", max_length=120)
    description = _limited_text(
        value.get("description") or "",
        field_name="description",
        max_length=500,
        required=False,
    )
    routines_value = value.get("routines")
    if not isinstance(routines_value, (list, tuple)) or not routines_value:
        raise ValueError("routines deve ser uma lista nao vazia")

    routines: list[dict[str, str]] = []
    seen_routines: set[str] = set()
    for item in routines_value:
        if isinstance(item, Mapping):
            routine_id = str(item.get("id") or item.get("key") or "").strip()
            routine_name = _limited_text(
                item.get("name") or f"Rotina {routine_id}",
                field_name="routine.name",
                max_length=160,
            )
        else:
            routine_id = str(item or "").strip()
            routine_name = f"Rotina {routine_id}"
        if not _ROUTINE_PATTERN.fullmatch(routine_id):
            raise ValueError(f"rotina invalida: {routine_id!r}")
        if routine_id in seen_routines:
            raise ValueError(f"rotina duplicada: {routine_id}")
        seen_routines.add(routine_id)
        routines.append({"id": routine_id, "name": routine_name})

    units_value = value.get("units") or []
    if not isinstance(units_value, (list, tuple)):
        raise ValueError("units deve ser uma lista")
    units: list[str] = []
    for raw_unit in units_value:
        unit = str(raw_unit or "").strip()
        if not _ROUTINE_PATTERN.fullmatch(unit):
            raise ValueError(f"unidade invalida: {unit!r}")
        if unit not in units:
            units.append(unit)

    return {
        "key": key,
        "name": name,
        "description": description,
        "routines": routines,
        "units": units,
    }


def _limited_text(
    value: Any,
    *,
    field_name: str,
    max_length: int,
    required: bool = True,
) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field_name} nao pode ser vazio")
    if len(text) > max_length:
        raise ValueError(f"{field_name} excede {max_length} caracteres")
    return text
