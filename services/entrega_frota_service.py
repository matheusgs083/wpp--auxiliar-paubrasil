from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

PLACA_PATTERN = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")
MAX_PALLETS = 100
MAX_META_PERCENTUAL = 200
MAX_META_CAIXAS_VIAGEM = 100_000


class EntregaFrotaService:
    """Caminhões por operação (capacidade em pallets) e metas da entrega.

    Cadastro operacional do painel, guardado fora das importações dos relatórios.
    """

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._lock = RLock()

    def list(self) -> dict[str, Any]:
        with self._lock:
            data = self._read()
        return {
            "caminhoes": deepcopy(data.get("caminhoes") or []),
            "metas": deepcopy(data.get("metas") or []),
            "updated_at": data.get("updated_at") or "",
            "updated_by": data.get("updated_by") or "",
        }

    def replace(self, payload: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
        cleaned = {
            "caminhoes": _clean_caminhoes(payload.get("caminhoes")),
            "metas": _clean_metas(payload.get("metas")),
        }
        record = {**cleaned, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "updated_by": actor}
        with self._lock:
            self._write(record)
        return deepcopy(record)

    def lookup(self) -> "FrotaLookup":
        """Consulta rápida por (operação, placa) e meta da operação."""
        return FrotaLookup(self.list())

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.storage_path)


class FrotaLookup:
    def __init__(self, cadastro: dict[str, Any]) -> None:
        self._caminhoes = {
            (item["filial"], item["placa"]): item
            for item in cadastro.get("caminhoes") or []
            if item.get("ativo", True)
        }
        self._metas = {item["filial"]: item for item in cadastro.get("metas") or []}

    def caminhao(self, filial: str, placa: str) -> dict[str, Any] | None:
        return self._caminhoes.get((normalize_filial(filial), normalize_placa(placa)))

    def meta_ocupacao(self, filial: str) -> float | None:
        meta = self._metas.get(normalize_filial(filial))
        return meta.get("ocupacao_meta_pct") if meta else None

    def meta_caixas_viagem(self, filial: str) -> float | None:
        meta = self._metas.get(normalize_filial(filial))
        return meta.get("caixas_viagem_meta") if meta else None


def normalize_filial(value: Any) -> str:
    return " ".join(str(value or "").strip().upper().split())


def normalize_placa(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _clean_caminhoes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Caminhões devem ser enviados como lista.")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        filial = normalize_filial(item.get("filial"))
        placa = normalize_placa(item.get("placa"))
        if not filial and not placa:
            continue
        if not filial:
            raise ValueError(f"Informe a operação do caminhão {placa or '(sem placa)'}.")
        if not PLACA_PATTERN.fullmatch(placa):
            raise ValueError(f"Placa inválida: {item.get('placa') or '(vazia)'}. Use o formato ABC1234 ou ABC1D23.")
        capacidade = _number(item.get("capacidade_pallets"))
        if capacidade is None or not 0 < capacidade <= MAX_PALLETS:
            raise ValueError(f"Capacidade em pallets do caminhão {placa} deve ser maior que 0 e até {MAX_PALLETS}.")
        if (filial, placa) in result:
            raise ValueError(f"Caminhão {placa} cadastrado duas vezes em {filial}.")
        result[(filial, placa)] = {
            "filial": filial,
            "placa": placa,
            "descricao": str(item.get("descricao") or "").strip()[:80],
            "capacidade_pallets": round(capacidade, 2),
            "ativo": bool(item.get("ativo", True)),
        }
    return sorted(result.values(), key=lambda item: (item["filial"], item["placa"]))


def _clean_metas(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Metas devem ser enviadas como lista.")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        filial = normalize_filial(item.get("filial"))
        ocupacao = _number(item.get("ocupacao_meta_pct"))
        caixas = _number(item.get("caixas_viagem_meta"))
        if not filial or (ocupacao is None and caixas is None):
            continue
        if ocupacao is not None and not 0 < ocupacao <= MAX_META_PERCENTUAL:
            raise ValueError(f"Meta de ocupação de {filial} deve ser maior que 0 e até {MAX_META_PERCENTUAL}%.")
        if caixas is not None and not 0 < caixas <= MAX_META_CAIXAS_VIAGEM:
            raise ValueError(f"Meta de caixas por viagem de {filial} deve ser maior que 0.")
        result[filial] = {
            "filial": filial,
            "ocupacao_meta_pct": round(ocupacao, 2) if ocupacao is not None else None,
            "caixas_viagem_meta": round(caixas, 2) if caixas is not None else None,
        }
    return sorted(result.values(), key=lambda item: item["filial"])
