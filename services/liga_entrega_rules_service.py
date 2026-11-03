from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


DEFAULT_LIGA_RULES: dict[str, Any] = {
    "metas": {"devol": 1.4, "devolucao_base": "hl", "saida": "07:30", "saida_pct": 90.0, "tempo": 110.0, "tempo_pern": 100.0, "km": 10.0, "min_rotas": 3},
    "indicadores": {"devolucao": True, "tml": True, "km": True},
    "pesos": {
        "motorista": {"devol": 60.0, "saida": 25.0, "km": 15.0},
        "ajudante": {"devol": 60.0, "saida": 25.0, "km": 15.0},
    },
}
OPERATIONS = ("PATOS", "SUME")


class LigaEntregaRulesService:
    """Armazena regras de ranking por competência e operação da Liga."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._lock = RLock()

    def all_rules(self, *, competencia: str | None = None) -> dict[str, dict[str, Any]]:
        clean_competencia = _competencia(competencia)
        with self._lock:
            stored = (self._read().get("competencias", {}).get(clean_competencia) or {})
            return {operation: _merge_rules(stored.get(operation)) for operation in OPERATIONS}

    def rules_for(self, operation: str, *, competencia: str | None = None) -> dict[str, Any]:
        return self.all_rules(competencia=competencia).get(_operation(operation), deepcopy(DEFAULT_LIGA_RULES))

    def set_rules(self, *, competencia: str, operation: str, payload: dict[str, Any], actor: str = "") -> dict[str, Any]:
        clean_competencia = _competencia(competencia)
        clean_operation = _operation(operation)
        if clean_operation not in OPERATIONS:
            raise ValueError("Operação da Liga inválida. Use PATOS ou SUME.")
        rules = _validate_rules(payload)
        with self._lock:
            document = self._read()
            operations = document.setdefault("competencias", {}).setdefault(clean_competencia, {})
            operations[clean_operation] = rules
            document["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            document["updated_by"] = str(actor or "")
            self._write(document)
        return {"competencia": clean_competencia, "operation": clean_operation, "rules": rules}

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"operations": {}}
        except (OSError, ValueError):
            return {"operations": {}}

    def _write(self, payload: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.storage_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.storage_path)


def _operation(value: Any) -> str:
    return str(value or "").strip().upper()


def _competencia(value: Any) -> str:
    competencia = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", competencia):
        raise ValueError("Competência inválida. Use AAAA-MM.")
    return competencia


def _merge_rules(value: Any) -> dict[str, Any]:
    result = deepcopy(DEFAULT_LIGA_RULES)
    if not isinstance(value, dict):
        return result
    for group in ("metas", "pesos"):
        incoming = value.get(group)
        if not isinstance(incoming, dict):
            continue
        if group == "pesos":
            for role in ("motorista", "ajudante"):
                if isinstance(incoming.get(role), dict):
                    result[group][role].update(incoming[role])
        else:
            result[group].update(incoming)
    indicadores = value.get("indicadores")
    if isinstance(indicadores, dict):
        for key in result["indicadores"]:
            if key in indicadores:
                result["indicadores"][key] = bool(indicadores[key])
    return result


def _validate_rules(value: Any) -> dict[str, Any]:
    rules = _merge_rules(value)
    metas = rules["metas"]
    try:
        metas["devol"] = _number(metas["devol"], "Meta de devolução", 0, 100)
        metas["saida_pct"] = _number(metas["saida_pct"], "Meta percentual de saída", 0, 100)
        metas["tempo"] = _number(metas["tempo"], "Meta de tempo", 1, 500)
        metas["tempo_pern"] = _number(metas["tempo_pern"], "Meta de tempo pernoite", 1, 500)
        metas["km"] = _number(metas["km"], "Meta de KM", 0, 500)
        metas["min_rotas"] = int(_number(metas["min_rotas"], "Mínimo de rotas", 0, 1000))
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    horario = str(metas.get("saida") or "").strip()
    if len(horario) != 5 or horario[2] != ":" or not horario.replace(":", "").isdigit() or not (0 <= int(horario[:2]) <= 23 and 0 <= int(horario[3:]) <= 59):
        raise ValueError("Hora limite de saída inválida. Use HH:MM.")
    metas["saida"] = horario
    base_devolucao = str(metas.get("devolucao_base") or "hl").strip().lower()
    if base_devolucao not in {"hl", "entregas"}:
        raise ValueError("Base de devolução inválida. Use hl ou entregas.")
    metas["devolucao_base"] = base_devolucao
    indicadores = rules["indicadores"]
    for key in indicadores:
        if not isinstance(indicadores[key], bool):
            raise ValueError(f"Indicador {key} inválido.")
    if not any(indicadores.values()):
        raise ValueError("Ative ao menos um indicador para a Liga.")
    for role in ("motorista", "ajudante"):
        weights = rules["pesos"][role]
        for key in ("devol", "saida", "km"):
            weights[key] = _number(weights[key], f"Peso {key}", 0, 100)
        if sum(weights.values()) <= 0:
            raise ValueError(f"Informe ao menos um peso para {role}.")
    return rules


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} inválida.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} deve ficar entre {minimum:g} e {maximum:g}.")
    return number
