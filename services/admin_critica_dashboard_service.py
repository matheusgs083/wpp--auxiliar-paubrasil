from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any
import unicodedata

from fastapi import HTTPException, Response

from bot_api.commercial_scope import (
    normalize_filial_scope_input,
    normalize_numeric_code,
    normalize_stored_scope_value,
)
from bot_api.services import admin_imports_runtime
from bot_api.services.critica_rn_query_service import CriticaPdfCurrentImportRequiredError
from bot_api.services.filial_labels import FILIAL_LABELS

critica_rn_query_service: Any = None
_panel_context_allowed_report_scopes: Any = None


def configure(**deps: Any) -> None:
    globals().update(deps)


_serialize_admin_import_value = admin_imports_runtime._serialize_admin_import_value

def _parse_localized_decimal(value: Any) -> Decimal:
    raw = str(value or "").strip()
    if not raw:
        return Decimal("0")
    raw = raw.replace("R$", "").replace("+", "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _sum_localized_decimal(values: Any) -> Decimal:
    return sum((_parse_localized_decimal(value) for value in values), Decimal("0"))


def _format_decimal_br(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _format_box_total(value: Decimal) -> str:
    return str(int(value.to_integral_value()))


CRITICA_DASHBOARD_PROBLEM_LABELS = {
    "ocorrencia": "Ocorrencia do relatorio",
    "pedido_duplicado": "Pedido duplicado",
    "produto_duplicado": "Produto duplicado no pedido",
    "preco": "Preco divergente",
    "sem_dprecos": "Produto sem DPrecos",
    "pedido_acima_media": "Pedido acima da media",
    "inadimplente": "Cliente inadimplente",
    "mapa_buffer": "Mapa 1 / buffer",
    "mapa_fora": "Mapa fora do vendedor",
    "condicao": "Cond. pag. divergente",
    "limite": "Estouro de limite",
    "outros": "Outros problemas",
}


def _format_money_br(value: Decimal) -> str:
    return f"R$ {_format_decimal_br(value)}"


def _critica_record_item_revenue(record: Any) -> Decimal:
    quantidade = _parse_localized_decimal(getattr(record, "quantidade", "0"))
    preco_unitario = _parse_localized_decimal(getattr(record, "preco_unitario", "0"))
    return quantidade * preco_unitario


def _parse_admin_critica_date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Data da critica invalida. Use AAAA-MM-DD.") from exc


def _normalize_admin_filter_values(values: str | list[str] | None) -> set[str]:
    if values is None:
        return set()
    raw_values = values if isinstance(values, list) else [values]
    normalized: set[str] = set()
    for value in raw_values:
        for part in str(value or "").split(","):
            text = part.strip()
            if text:
                normalized.add(text)
    return normalized


def _normalize_search_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFD", str(value or "").strip().lower())
    ascii_only = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", ascii_only).strip()


def _critica_record_problem_keys(record: Any) -> set[str]:
    labels = tuple(str(label or "").strip() for label in getattr(record, "problemas", ()) if str(label or "").strip())
    normalized_labels = _normalize_search_text(" ".join(labels))
    keys: set[str] = set()
    if str(getattr(record, "critica_text", "") or "").strip() or str(getattr(record, "ocorrencia_1", "") or "").strip() or str(getattr(record, "ocorrencia_2", "") or "").strip():
        keys.add("ocorrencia")
    if bool(getattr(record, "pedido_cliente_duplicado", False)) or "possivel pedido duplicado" in normalized_labels:
        keys.add("pedido_duplicado")
    if bool(getattr(record, "pedido_produto_duplicado", False)) or "produto repetido" in normalized_labels:
        keys.add("produto_duplicado")
    if "produto sem referencia" in normalized_labels or "sem dprecos" in normalized_labels:
        keys.add("sem_dprecos")
    if "preco" in normalized_labels and "sem dprecos" not in normalized_labels and "sem referencia" not in normalized_labels:
        keys.add("preco")
    if bool(getattr(record, "order_above_average", False)) or "acima da media" in normalized_labels:
        keys.add("pedido_acima_media")
    inad_total_vencido = _parse_localized_decimal(getattr(record, "inad_total_vencido", "0"))
    try:
        inad_titulos_vencidos = int(str(getattr(record, "inad_titulos_vencidos", 0) or "0").strip() or "0")
    except ValueError:
        inad_titulos_vencidos = 0
    if inad_total_vencido > 0 and inad_titulos_vencidos > 0:
        keys.add("inadimplente")
    map_status = str(getattr(record, "map_status", "") or "").strip().lower()
    if map_status == "buffer" or "mapa 1" in normalized_labels or "buffer" in normalized_labels:
        keys.add("mapa_buffer")
    if map_status == "fora" or "fora do mapa" in normalized_labels:
        keys.add("mapa_fora")
    if bool(getattr(record, "cond_divergente", False)) or "condicao de pagamento" in normalized_labels:
        keys.add("condicao")
    if _parse_localized_decimal(getattr(record, "limit_exceeded_amount", "0")) > 0 or "ultrapassa o limite" in normalized_labels:
        keys.add("limite")
    if labels and not keys:
        keys.add("outros")
    return keys


def _critica_order_rows_from_records(records: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for index, record in enumerate(records):
        filial = str(getattr(record, "filial", "") or "").strip()
        pedido = str(getattr(record, "pedido", "") or "").strip() or f"sem-pedido-{index}"
        key = (filial, pedido)
        problem_keys = _critica_record_problem_keys(record)
        problem_labels = [
            str(label or "").strip()
            for label in getattr(record, "problemas", ())
            if str(label or "").strip()
        ]
        entry = grouped.setdefault(
            key,
            {
                "filial": filial,
                "pedido": pedido,
                "data_pedido": _serialize_admin_import_value(getattr(record, "data_pedido", None)),
                "operation_name": str(getattr(record, "operation_name", "") or "").strip(),
                "movement_operation_name": str(getattr(record, "movement_operation_name", "") or "").strip(),
                "setor": str(getattr(record, "setor", "") or "").strip(),
                "seller": str(getattr(record, "seller_code", "") or getattr(record, "vendedor_codigo", "") or "").strip(),
                "manager": str(getattr(record, "manager_code", "") or getattr(record, "codigo_gv", "") or "").strip(),
                "cod_pdv": str(getattr(record, "cod_pdv", "") or "").strip(),
                "nome_pdv": str(getattr(record, "nome_pdv", "") or "").strip(),
                "cond_pagamento": str(getattr(record, "cond_pag_pedido", "") or "").strip(),
                "cidade": str(getattr(record, "client_cidade", "") or "").strip(),
                "bairro": str(getattr(record, "client_bairro", "") or "").strip(),
                "origem": str(getattr(record, "origem_pedido", "") or "").strip(),
                "status_pedido": str(getattr(record, "status_pedido", "") or "").strip(),
                "total_pedido_decimal": Decimal("0"),
                "peso_pedido_decimal": Decimal("0"),
                "item_count": 0,
                "problem_item_count": 0,
                "problem_keys": set(),
                "problem_labels": [],
                "problem_products": [],
                "inad_total_vencido_decimal": Decimal("0"),
                "limit_exceeded_decimal": Decimal("0"),
                "avg_order_value_decimal": Decimal("0"),
                "hectolitros_decimal": Decimal("0"),
                "nab_tt_hectolitros_decimal": Decimal("0"),
                "high_end_hectolitros_decimal": Decimal("0"),
                "cerveja_tt_hectolitros_decimal": Decimal("0"),
                "refri_zero_hectolitros_decimal": Decimal("0"),
                "cerveja_rgb_hectolitros_decimal": Decimal("0"),
                "cerveja_ow_hectolitros_decimal": Decimal("0"),
                "marketplace_tt_faturamento_decimal": Decimal("0"),
                "search_text_parts": [],
            },
        )
        total_pedido = _parse_localized_decimal(getattr(record, "total_pedido", "0"))
        if total_pedido:
            entry["total_pedido_decimal"] = total_pedido
        entry["peso_pedido_decimal"] += _parse_localized_decimal(getattr(record, "peso_item", "0"))
        entry["item_count"] += 1
        if problem_keys:
            entry["problem_item_count"] += 1
        entry["problem_keys"].update(problem_keys)
        entry["problem_labels"].extend(problem_labels)
        if problem_keys:
            product = " ".join(
                str(value or "").strip()
                for value in (getattr(record, "produto_codigo", ""), getattr(record, "produto_descricao", ""))
                if str(value or "").strip()
            )
            if product:
                entry["problem_products"].append(product)
        entry["inad_total_vencido_decimal"] = max(
            entry["inad_total_vencido_decimal"],
            _parse_localized_decimal(getattr(record, "inad_total_vencido", "0")),
        )
        entry["limit_exceeded_decimal"] = max(
            entry["limit_exceeded_decimal"],
            _parse_localized_decimal(getattr(record, "limit_exceeded_amount", "0")),
        )
        entry["avg_order_value_decimal"] = max(
            entry["avg_order_value_decimal"],
            _parse_localized_decimal(getattr(record, "avg_order_value_3m", "0")),
        )
        item_hectolitros = _parse_localized_decimal(getattr(record, "hectolitros", "0"))
        entry["hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_nab_tt", False)):
            entry["nab_tt_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_high_end", False)):
            entry["high_end_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_cerveja_tt", False)):
            entry["cerveja_tt_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_refri_zero", False)):
            entry["refri_zero_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_cerveja_rgb", False)):
            entry["cerveja_rgb_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_cerveja_ow", False)):
            entry["cerveja_ow_hectolitros_decimal"] += item_hectolitros
        if bool(getattr(record, "cesta_marketplace_tt", False)):
            entry["marketplace_tt_faturamento_decimal"] += _critica_record_item_revenue(record)
        entry["search_text_parts"].extend(
            [
                filial,
                pedido,
                entry["operation_name"],
                entry["movement_operation_name"],
                entry["setor"],
                entry["seller"],
                entry["manager"],
                entry["cod_pdv"],
                entry["nome_pdv"],
                entry["cond_pagamento"],
                entry["cidade"],
                entry["bairro"],
                entry["origem"],
                " ".join(problem_labels),
            ]
        )

    rows: list[dict[str, Any]] = []
    for entry in grouped.values():
        labels = _dedupe_texts(entry["problem_labels"])
        products = _dedupe_texts(entry["problem_products"])
        problem_keys = sorted(entry["problem_keys"], key=lambda key: CRITICA_DASHBOARD_PROBLEM_LABELS.get(key, key))
        total_pedido = entry["total_pedido_decimal"]
        peso_pedido = entry["peso_pedido_decimal"]
        rows.append(
            {
                "filial": entry["filial"],
                "pedido": entry["pedido"],
                "data_pedido": entry["data_pedido"],
                "operation_name": entry["operation_name"],
                "movement_operation_name": entry["movement_operation_name"],
                "setor": entry["setor"],
                "seller": entry["seller"],
                "manager": entry["manager"],
                "cod_pdv": entry["cod_pdv"],
                "nome_pdv": entry["nome_pdv"],
                "cond_pagamento": entry["cond_pagamento"],
                "cidade": entry["cidade"],
                "bairro": entry["bairro"],
                "origem": entry["origem"],
                "status_pedido": entry["status_pedido"],
                "total_pedido": _format_money_br(total_pedido),
                "total_pedido_value": str(total_pedido),
                "peso_pedido": _format_decimal_br(peso_pedido),
                "peso_pedido_value": str(peso_pedido),
                "item_count": int(entry["item_count"]),
                "problem_item_count": int(entry["problem_item_count"]),
                "problem_keys": problem_keys,
                "problem_labels": labels,
                "problem_products": products[:6],
                "problem_count": len(problem_keys),
                "inad_total_vencido": _format_money_br(entry["inad_total_vencido_decimal"]),
                "limit_exceeded_amount": _format_money_br(entry["limit_exceeded_decimal"]),
                "avg_order_value": _format_money_br(entry["avg_order_value_decimal"]),
                "hectolitros": _format_decimal_br(entry["hectolitros_decimal"]),
                "hectolitros_value": str(entry["hectolitros_decimal"]),
                "nab_tt_hectolitros_value": str(entry["nab_tt_hectolitros_decimal"]),
                "high_end_hectolitros_value": str(entry["high_end_hectolitros_decimal"]),
                "cerveja_tt_hectolitros_value": str(entry["cerveja_tt_hectolitros_decimal"]),
                "refri_zero_hectolitros_value": str(entry["refri_zero_hectolitros_decimal"]),
                "cerveja_rgb_hectolitros_value": str(entry["cerveja_rgb_hectolitros_decimal"]),
                "cerveja_ow_hectolitros_value": str(entry["cerveja_ow_hectolitros_decimal"]),
                "marketplace_tt_faturamento_value": str(entry["marketplace_tt_faturamento_decimal"]),
                "search_text": _normalize_search_text(" ".join(entry["search_text_parts"])),
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["problem_count"] else 1,
            -int(row["problem_count"]),
            -_parse_localized_decimal(row["total_pedido_value"]),
            _sort_numeric_text(row["filial"]),
            _sort_numeric_text(row["pedido"]),
        )
    )
    return rows


def _dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = _normalize_search_text(text)
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _sort_numeric_text(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    return (int(text), text) if text.isdigit() else (999999, text)


def _critica_order_matches_filters(
    row: dict[str, Any],
    *,
    operation: set[str],
    sector: set[str],
    seller: set[str],
    manager: set[str],
    city: set[str],
    district: set[str],
    origin: set[str],
    problem: set[str],
    search: str,
    only_problems: bool,
) -> bool:
    if only_problems and not row.get("problem_keys"):
        return False
    if operation and str(row.get("filial") or "").strip() not in operation:
        return False
    if sector and str(row.get("setor") or "").strip() not in sector:
        return False
    if seller and str(row.get("seller") or "").strip() not in seller:
        return False
    if manager and str(row.get("manager") or "").strip() not in manager:
        return False
    if city and str(row.get("cidade") or "").strip() not in city:
        return False
    if district and str(row.get("bairro") or "").strip() not in district:
        return False
    if origin and str(row.get("origem") or "").strip() not in origin:
        return False
    if problem and not (set(row.get("problem_keys") or []) & problem):
        return False
    if search and search not in str(row.get("search_text") or ""):
        return False
    return True


def _critica_option_items(
    rows: list[dict[str, Any]],
    *,
    value_key: str,
    label_factory: Any | None = None,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for row in rows:
        value = str(row.get(value_key) or "").strip()
        if not value:
            continue
        counts[value] += 1
        labels.setdefault(value, label_factory(row, value) if label_factory else value)
    return [
        {"value": value, "label": labels.get(value, value), "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (_sort_numeric_text(item[0]), labels.get(item[0], item[0])))
    ]


def _critica_problem_option_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key in row.get("problem_keys") or []:
            counts[str(key)] += 1
    return [
        {"value": key, "label": CRITICA_DASHBOARD_PROBLEM_LABELS.get(key, key), "count": counts[key]}
        for key in sorted(counts, key=lambda item: (-counts[item], CRITICA_DASHBOARD_PROBLEM_LABELS.get(item, item)))
    ]


def _critica_dashboard_options(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "operations": _critica_option_items(
            rows,
            value_key="filial",
            label_factory=lambda row, value: f"{value} - {row.get('operation_name') or FILIAL_LABELS.get(value, '')}".strip(" -"),
        ),
        "sectors": _critica_option_items(rows, value_key="setor"),
        "sellers": _critica_option_items(rows, value_key="seller"),
        "managers": _critica_option_items(rows, value_key="manager"),
        "cities": _critica_option_items(rows, value_key="cidade"),
        "districts": _critica_option_items(rows, value_key="bairro"),
        "origins": _critica_option_items(rows, value_key="origem"),
        "problems": _critica_problem_option_items(rows),
    }


def _critica_dashboard_slicer_options(
    all_rows: list[dict[str, Any]],
    filters: dict[str, Any],
    *,
    only_problems: bool,
) -> dict[str, list[dict[str, Any]]]:
    def rows_for(omit: str) -> list[dict[str, Any]]:
        return [
            row
            for row in all_rows
            if _critica_order_matches_filters(
                row,
                operation=set() if omit == "operation" else filters["operation"],
                sector=set() if omit == "sector" else filters["sector"],
                seller=set() if omit == "seller" else filters["seller"],
                manager=set() if omit == "manager" else filters["manager"],
                city=set() if omit == "city" else filters["city"],
                district=set() if omit == "district" else filters["district"],
                origin=set() if omit == "origin" else filters["origin"],
                problem=set() if omit == "problem" else filters["problem"],
                search=filters["search"],
                only_problems=only_problems,
            )
        ]

    return {
        "operations": _critica_option_items(
            rows_for("operation"),
            value_key="filial",
            label_factory=lambda row, value: f"{value} - {row.get('operation_name') or FILIAL_LABELS.get(value, '')}".strip(" -"),
        ),
        "sectors": _critica_option_items(rows_for("sector"), value_key="setor"),
        "sellers": _critica_option_items(rows_for("seller"), value_key="seller"),
        "managers": _critica_option_items(rows_for("manager"), value_key="manager"),
        "cities": _critica_option_items(rows_for("city"), value_key="cidade"),
        "districts": _critica_option_items(rows_for("district"), value_key="bairro"),
        "origins": _critica_option_items(rows_for("origin"), value_key="origem"),
        "problems": _critica_problem_option_items(rows_for("problem")),
    }


def _critica_problem_rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key in row.get("problem_keys") or []:
            counts[str(key)] += 1
    return [
        {"key": key, "label": CRITICA_DASHBOARD_PROBLEM_LABELS.get(key, key), "orders": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], CRITICA_DASHBOARD_PROBLEM_LABELS.get(item[0], item[0])))
    ]


def _critica_group_rank(rows: list[dict[str, Any]], *, key: str, label: str, limit: int = 8) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip() or "-"
        entry = grouped.setdefault(value, {"value": value, "label": value, "orders": 0, "problem_orders": 0, "total_decimal": Decimal("0")})
        entry["orders"] += 1
        if row.get("problem_keys"):
            entry["problem_orders"] += 1
        entry["total_decimal"] += _parse_localized_decimal(row.get("total_pedido_value"))
    ranked = sorted(grouped.values(), key=lambda item: (-int(item["problem_orders"]), -item["total_decimal"], item["label"]))[:limit]
    return [
        {
            "value": item["value"],
            "label": f"{label} {item['label']}" if label else item["label"],
            "orders": item["orders"],
            "problem_orders": item["problem_orders"],
            "total": _format_money_br(item["total_decimal"]),
        }
        for item in ranked
    ]


def _critica_client_rank(rows: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("filial") or ""), str(row.get("cod_pdv") or ""))
        entry = grouped.setdefault(
            key,
            {
                "filial": row.get("filial") or "",
                "cod_pdv": row.get("cod_pdv") or "",
                "nome_pdv": row.get("nome_pdv") or "-",
                "orders": 0,
                "problem_orders": 0,
                "total_decimal": Decimal("0"),
            },
        )
        entry["orders"] += 1
        if row.get("problem_keys"):
            entry["problem_orders"] += 1
        entry["total_decimal"] += _parse_localized_decimal(row.get("total_pedido_value"))
    ranked = sorted(grouped.values(), key=lambda item: (-int(item["problem_orders"]), -item["total_decimal"], item["nome_pdv"]))[:limit]
    return [
        {
            "filial": item["filial"],
            "cod_pdv": item["cod_pdv"],
            "label": item["nome_pdv"],
            "orders": item["orders"],
            "problem_orders": item["problem_orders"],
            "total": _format_money_br(item["total_decimal"]),
        }
        for item in ranked
    ]


def _critica_dashboard_recommendations(problem_rank: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    rank_by_key = {item["key"]: int(item.get("orders") or 0) for item in problem_rank}
    recommendations: list[dict[str, str]] = []
    if rank_by_key.get("limite", 0) or rank_by_key.get("condicao", 0):
        recommendations.append(
            {
                "title": "Validar credito antes de faturar",
                "detail": "Priorize pedidos com estouro de limite ou condicao divergente, principalmente quando a operacao for 51.",
            }
        )
    if rank_by_key.get("pedido_duplicado", 0) or rank_by_key.get("produto_duplicado", 0):
        recommendations.append(
            {
                "title": "Conferir duplicidades por cliente",
                "detail": "Compare pedidos do mesmo NB em datas proximas e confirme se nao houve redigitacao do mesmo mix.",
            }
        )
    if rank_by_key.get("preco", 0) or rank_by_key.get("sem_dprecos", 0):
        recommendations.append(
            {
                "title": "Tratar preco e cadastro de produto",
                "detail": "Separe divergencias de preco real de produto sem DPrecos para evitar retrabalho na critica manual.",
            }
        )
    if rank_by_key.get("mapa_buffer", 0) or rank_by_key.get("mapa_fora", 0):
        recommendations.append(
            {
                "title": "Revisar origem do pedido",
                "detail": "Pedidos em buffer ou fora do mapa indicam falha de digitacao, rota ou setor e devem ser cobrados com o responsavel.",
            }
        )
    if rank_by_key.get("inadimplente", 0):
        recommendations.append(
            {
                "title": "Cruzar critica com cobranca",
                "detail": "Clientes inadimplentes com pedido novo devem ir para validacao comercial antes de seguir o fluxo normal.",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "title": "Sem concentracao critica nos filtros",
                "detail": "Use filtros por operacao, setor ou problema para encontrar bolsões específicos de erro.",
            }
        )
    if len(rows) > 300:
        recommendations.append(
            {
                "title": "Quebrar a fila de trabalho",
                "detail": "Para operacao grande, filtre por setor ou GV e trate primeiro os pedidos com maior valor total.",
            }
        )
    return recommendations[:5]


def _build_admin_critica_dashboard(
    context: dict[str, Any] | None = None,
    *,
    target_date: date | None = None,
    limit: int = 200,
    operation: str | list[str] | None = None,
    sector: str | list[str] | None = None,
    seller: str | list[str] | None = None,
    manager: str | list[str] | None = None,
    city: str | list[str] | None = None,
    district: str | list[str] | None = None,
    origin: str | list[str] | None = None,
    problem: str | list[str] | None = None,
    search: str = "",
    only_problems: bool = True,
) -> dict[str, Any]:
    allowed_sectors, allowed_gv_vdes = _panel_context_allowed_report_scopes(context)
    effective_date = target_date or critica_rn_query_service.latest_date(
        allowed_sectors=allowed_sectors,
        allowed_gv_vdes=allowed_gv_vdes,
    )
    if effective_date is None:
        return {
            "total": 0,
            "limit": limit,
            "summary": {
                "data_pedido": "",
                "pedidos": 0,
                "pedidos_com_problema": 0,
                "clientes": 0,
                "itens": 0,
                "valor_total": "R$ 0,00",
                "taxa_problema": "0,0%",
            },
            "options": _critica_dashboard_options([]),
            "rankings": {"problems": [], "operations": [], "sectors": [], "clients": []},
            "recommendations": _critica_dashboard_recommendations([], []),
            "orders": [],
        }
    data = critica_rn_query_service.get_report_data(
        target_date=effective_date,
        allowed_sectors=allowed_sectors,
        allowed_gv_vdes=allowed_gv_vdes,
        limit=50000,
    )
    all_rows = _critica_order_rows_from_records(data.records)
    filters = {
        "operation": _normalize_admin_filter_values(operation),
        "sector": _normalize_admin_filter_values(sector),
        "seller": _normalize_admin_filter_values(seller),
        "manager": _normalize_admin_filter_values(manager),
        "city": _normalize_admin_filter_values(city),
        "district": _normalize_admin_filter_values(district),
        "origin": _normalize_admin_filter_values(origin),
        "problem": _normalize_admin_filter_values(problem),
        "search": _normalize_search_text(search),
    }
    filtered_rows = [
        row
        for row in all_rows
        if _critica_order_matches_filters(
            row,
            operation=filters["operation"],
            sector=filters["sector"],
            seller=filters["seller"],
            manager=filters["manager"],
            city=filters["city"],
            district=filters["district"],
            origin=filters["origin"],
            problem=filters["problem"],
            search=filters["search"],
            only_problems=only_problems,
        )
    ]
    total_value = sum((_parse_localized_decimal(row.get("total_pedido_value")) for row in filtered_rows), Decimal("0"))
    peso_total = sum((_parse_localized_decimal(row.get("peso_pedido_value")) for row in filtered_rows), Decimal("0"))
    total_hectolitros = sum((_parse_localized_decimal(row.get("hectolitros_value")) for row in filtered_rows), Decimal("0"))
    nab_tt_hectolitros = sum((_parse_localized_decimal(row.get("nab_tt_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    high_end_hectolitros = sum((_parse_localized_decimal(row.get("high_end_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    cerveja_tt_hectolitros = sum((_parse_localized_decimal(row.get("cerveja_tt_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    refri_zero_hectolitros = sum((_parse_localized_decimal(row.get("refri_zero_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    cerveja_rgb_hectolitros = sum((_parse_localized_decimal(row.get("cerveja_rgb_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    cerveja_ow_hectolitros = sum((_parse_localized_decimal(row.get("cerveja_ow_hectolitros_value")) for row in filtered_rows), Decimal("0"))
    marketplace_tt_faturamento = sum((_parse_localized_decimal(row.get("marketplace_tt_faturamento_value")) for row in filtered_rows), Decimal("0"))
    problem_orders = sum(1 for row in filtered_rows if row.get("problem_keys"))
    client_count = len({(row.get("filial"), row.get("cod_pdv")) for row in filtered_rows if row.get("filial") and row.get("cod_pdv")})
    problem_rank = _critica_problem_rank(filtered_rows)
    safe_limit = max(1, min(int(limit or 200), 1000))
    return {
        "total": len(filtered_rows),
        "limit": safe_limit,
        "summary": {
            "data_pedido": effective_date.isoformat(),
            "planilha_atualizada_em": data.summary.planilha_atualizada_em,
            "pedidos": len(filtered_rows),
            "pedidos_base": len(all_rows),
            "pedidos_com_problema": problem_orders,
            "clientes": client_count,
            "itens": sum(int(row.get("item_count") or 0) for row in filtered_rows),
            "valor_total": _format_money_br(total_value),
            "peso_total": _format_decimal_br(peso_total),
            "total_hectolitros": _format_decimal_br(total_hectolitros),
            "nab_tt_hectolitros": _format_decimal_br(nab_tt_hectolitros),
            "high_end_hectolitros": _format_decimal_br(high_end_hectolitros),
            "cerveja_tt_hectolitros": _format_decimal_br(cerveja_tt_hectolitros),
            "refri_zero_hectolitros": _format_decimal_br(refri_zero_hectolitros),
            "cerveja_rgb_hectolitros": _format_decimal_br(cerveja_rgb_hectolitros),
            "cerveja_ow_hectolitros": _format_decimal_br(cerveja_ow_hectolitros),
            "marketplace_tt_faturamento": _format_money_br(marketplace_tt_faturamento),
            "ticket_medio": _format_money_br(total_value / Decimal(len(filtered_rows))) if filtered_rows else "R$ 0,00",
            "taxa_problema": _format_decimal_br((Decimal(problem_orders) / Decimal(len(filtered_rows)) * Decimal("100")) if filtered_rows else Decimal("0")) + "%",
            "maior_problema": problem_rank[0]["label"] if problem_rank else "-",
        },
        "options": _critica_dashboard_slicer_options(all_rows, filters, only_problems=only_problems),
        "rankings": {
            "problems": problem_rank[:12],
            "operations": _critica_group_rank(filtered_rows, key="filial", label="Operacao", limit=8),
            "sectors": _critica_group_rank(filtered_rows, key="setor", label="Setor", limit=8),
            "clients": _critica_client_rank(filtered_rows, limit=8),
        },
        "recommendations": _critica_dashboard_recommendations(problem_rank, filtered_rows),
        "orders": filtered_rows[:safe_limit],
    }


def _normalize_admin_critica_operation(value: Any) -> str:
    normalized = normalize_numeric_code(str(value or "").strip())
    if not normalized:
        raise HTTPException(status_code=400, detail="Operacao da critica obrigatoria.")
    return normalized


def _normalize_admin_critica_sector(value: Any) -> str:
    normalized = normalize_numeric_code(str(value or "").strip())
    if not normalized:
        raise HTTPException(status_code=400, detail="Setor da critica obrigatorio.")
    return normalized


def _build_admin_critica_sector_pdf_response(
    context: dict[str, Any] | None,
    *,
    operation: Any,
    sector: Any,
    target_date: date | None,
    summary_only: bool,
) -> Response:
    normalized_operation = _normalize_admin_critica_operation(operation)
    raw_sector = str(sector or "").strip()
    normalized_sector = _normalize_admin_critica_sector(raw_sector) if raw_sector else ""
    allowed_filiais, _allowed_gv_vdes = _panel_context_allowed_report_scopes(context)
    if allowed_filiais is not None and normalized_operation not in set(allowed_filiais):
        raise HTTPException(status_code=403, detail="Operacao fora do escopo liberado para este painel.")

    is_sector_scope = bool(normalized_sector)
    allowed_sector_scopes = (
        [normalize_stored_scope_value(f"{normalized_operation}_{normalized_sector}")]
        if is_sector_scope
        else [normalize_filial_scope_input(normalized_operation)]
    )
    effective_date = target_date or critica_rn_query_service.latest_date(allowed_sectors=allowed_sector_scopes)
    if effective_date is None:
        scope_label = (
            f"operacao {normalized_operation} e setor {normalized_sector}"
            if is_sector_scope
            else f"operacao {normalized_operation}"
        )
        raise HTTPException(
            status_code=404,
            detail=f"Nao encontrei critica para a {scope_label}.",
        )

    try:
        report = critica_rn_query_service.get_pdf_report(
            target_date=effective_date,
            allowed_sectors=allowed_sector_scopes,
            allowed_gv_vdes=None,
            limit=5000 if is_sector_scope else 50000,
        )
    except CriticaPdfCurrentImportRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    pdf_bytes = report.summary_pdf_bytes if summary_only else report.pdf_bytes
    if not pdf_bytes:
        report_label = "resumo" if summary_only else "detalhada"
        scope_label = (
            f"operacao {normalized_operation} e setor {normalized_sector}"
            if is_sector_scope
            else f"operacao {normalized_operation}"
        )
        raise HTTPException(
            status_code=404,
            detail=(
                f"Nao encontrei critica {report_label} para a {scope_label} "
                f"em {effective_date.isoformat()}."
            ),
        )

    base_filename = (
        f"critica-rn-setor-{normalized_operation}-{normalized_sector}-{effective_date.isoformat()}"
        if is_sector_scope
        else f"critica-rn-operacao-{normalized_operation}-{effective_date.isoformat()}"
    )
    filename = f"{base_filename}-resumo.pdf" if summary_only else f"{base_filename}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
