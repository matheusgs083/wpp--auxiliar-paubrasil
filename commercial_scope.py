from __future__ import annotations

import re

DC_SCOPE_PREFIX = "dc:"
FILIAL_SCOPE_PREFIX = "filial:"
_COMPOSITE_SCOPE_RE = re.compile(r"^(\d+)_(\d+)$")


def normalize_numeric_code(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def normalize_sector_scope_input(value: str) -> str:
    pair = split_scope_pair(value)
    return f"{pair[0]}_{pair[1]}" if pair else ""


def normalize_gv_scope_input(value: str) -> str:
    pair = split_scope_pair(value)
    return f"{pair[0]}_{pair[1]}" if pair else ""


def normalize_dc_scope_input(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith(DC_SCOPE_PREFIX):
        pair = split_scope_pair(raw[len(DC_SCOPE_PREFIX) :])
        return f"{DC_SCOPE_PREFIX}{pair[0]}_{pair[1]}" if pair else ""

    pair = split_scope_pair(raw)
    if pair:
        return f"{DC_SCOPE_PREFIX}{pair[0]}_{pair[1]}"
    return ""


def normalize_filial_scope_input(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith(FILIAL_SCOPE_PREFIX):
        raw = raw[len(FILIAL_SCOPE_PREFIX) :]
    if split_scope_pair(raw):
        return ""
    code = normalize_numeric_code(raw)
    return f"{FILIAL_SCOPE_PREFIX}{code}" if code else ""


def normalize_stored_scope_value(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if raw.startswith(FILIAL_SCOPE_PREFIX):
        return normalize_filial_scope_input(raw)
    if raw.startswith(DC_SCOPE_PREFIX):
        return normalize_dc_scope_input(raw)
    return _normalize_pair_or_simple(raw)


def split_scope_pair(value: str) -> tuple[str, str] | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw.startswith(DC_SCOPE_PREFIX):
        raw = raw[len(DC_SCOPE_PREFIX) :]

    composite_match = _COMPOSITE_SCOPE_RE.fullmatch(raw)
    if composite_match:
        left = normalize_numeric_code(composite_match.group(1))
        right = normalize_numeric_code(composite_match.group(2))
        return (left, right) if left and right else None

    pair_match = re.fullmatch(r"\s*(\d+)\s*[-/:\\|]\s*(\d+)\s*", raw)
    if pair_match:
        left = normalize_numeric_code(pair_match.group(1))
        right = normalize_numeric_code(pair_match.group(2))
        return (left, right) if left and right else None

    return None


def is_composite_scope(value: str) -> bool:
    pair = split_scope_pair(value)
    return pair is not None and not str(value or "").strip().isdigit()


def is_dc_scope(value: str) -> bool:
    return str(value or "").strip().lower().startswith(DC_SCOPE_PREFIX)


def is_filial_scope(value: str) -> bool:
    return str(value or "").strip().lower().startswith(FILIAL_SCOPE_PREFIX)


def partition_filial_scopes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    filial_codes: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        raw = str(value or "").strip().lower()
        if not is_filial_scope(raw):
            continue
        normalized = normalize_filial_scope_input(raw)
        code = normalized[len(FILIAL_SCOPE_PREFIX) :] if normalized.startswith(FILIAL_SCOPE_PREFIX) else ""
        if code and code not in seen:
            seen.add(code)
            filial_codes.append(code)

    return filial_codes


def partition_sector_scopes(values: list[str] | tuple[str, ...] | None) -> tuple[list[str], list[str]]:
    composite_keys: list[str] = []
    legacy_codes: list[str] = []
    seen_composite: set[str] = set()
    seen_legacy: set[str] = set()

    for value in values or []:
        raw = str(value or "").strip().lower()
        if not raw:
            continue
        if is_dc_scope(raw) or is_filial_scope(raw):
            continue
        if is_composite_scope(raw):
            normalized = normalize_sector_scope_input(raw)
            if normalized and normalized not in seen_composite:
                seen_composite.add(normalized)
                composite_keys.append(normalized)
            continue
        normalized = normalize_numeric_code(raw)
        if normalized and normalized not in seen_legacy:
            seen_legacy.add(normalized)
            legacy_codes.append(normalized)

    return composite_keys, legacy_codes


def partition_gv_scopes(
    values: list[str] | tuple[str, ...] | None,
) -> tuple[list[str], list[str], list[str]]:
    gv_keys: list[str] = []
    dc_keys: list[str] = []
    legacy_codes: list[str] = []
    seen_gv: set[str] = set()
    seen_dc: set[str] = set()
    seen_legacy: set[str] = set()

    for value in values or []:
        raw = str(value or "").strip().lower()
        if not raw:
            continue
        if is_dc_scope(raw):
            normalized_dc = normalize_dc_scope_input(raw)
            if normalized_dc and normalized_dc not in seen_dc:
                seen_dc.add(normalized_dc)
                dc_keys.append(normalized_dc)
            continue
        if is_composite_scope(raw):
            normalized_gv = normalize_gv_scope_input(raw)
            if normalized_gv and normalized_gv not in seen_gv:
                seen_gv.add(normalized_gv)
                gv_keys.append(normalized_gv)
            continue
        normalized_legacy = normalize_numeric_code(raw)
        if normalized_legacy and normalized_legacy not in seen_legacy:
            seen_legacy.add(normalized_legacy)
            legacy_codes.append(normalized_legacy)

    return gv_keys, dc_keys, legacy_codes


def extract_scope_input_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for match in re.finditer(r"\d+\s*[-/:\\|]\s*\d+|\d+", str(text or "")):
        token = match.group(0).strip()
        if token and token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def format_sector_scope(value: str) -> str:
    pair = split_scope_pair(value)
    if pair:
        return f"Filial {pair[0]} | Setor {pair[1]}"
    return str(value or "-").strip() or "-"


def format_gv_scope(value: str) -> str:
    pair = split_scope_pair(value)
    if pair:
        return f"Filial {pair[0]} | GV {pair[1]}"
    return str(value or "-").strip() or "-"


def format_dc_scope(value: str) -> str:
    pair = split_scope_pair(value)
    if pair:
        return f"Filial {pair[0]} | DC {pair[1]}"
    return str(value or "-").strip() or "-"


def format_filial_scope(value: str) -> str:
    normalized = normalize_filial_scope_input(value)
    if normalized.startswith(FILIAL_SCOPE_PREFIX):
        return f"Filial {normalized[len(FILIAL_SCOPE_PREFIX):]}"
    return str(value or "-").strip() or "-"


def format_scope_list(
    values: list[str] | tuple[str, ...] | None,
    formatter,
    empty_label: str = "nenhum",
) -> str:
    items = [formatter(value) for value in (values or []) if str(value or "").strip()]
    return ", ".join(items) if items else empty_label


def _normalize_pair_or_simple(value: str) -> str:
    pair = split_scope_pair(value)
    if pair:
        return f"{pair[0]}_{pair[1]}"
    return normalize_numeric_code(value)
