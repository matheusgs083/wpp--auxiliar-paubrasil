from __future__ import annotations

from bot_api.commercial_scope import normalize_numeric_code


DEFAULT_FILIAL_LABELS = {
    "1": "Sousa",
    "2": "Itaporanga",
    "3": "Patos",
    "4": "Sume",
    "5": "Guarabira",
    "6": "Brumado",
    "7": "Barra",
    "8": "Cacule",
}
FILIAL_LABELS = dict(DEFAULT_FILIAL_LABELS)


def set_filial_labels(labels: dict[str, str] | None) -> None:
    cleaned: dict[str, str] = {}
    for code, label in (labels or {}).items():
        normalized_code = normalize_numeric_code(str(code or "").strip())
        cleaned_label = " ".join(str(label or "").strip().split())
        if normalized_code and cleaned_label:
            cleaned[normalized_code] = cleaned_label
    FILIAL_LABELS.clear()
    FILIAL_LABELS.update(cleaned or DEFAULT_FILIAL_LABELS)
