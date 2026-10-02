from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any


MONTHLY_MAP_CITIES_ROUTINE = "03114902_MENSAL_LIGA"


class MonthlyMapCitiesService:
    """Leitura isolada da 03.11.49.02 mensal, sem interferir na Liga."""

    def __init__(self, *, report_store: Any) -> None:
        self.report_store = report_store

    def build_dashboard(self, *, competencia: str | None = None, period: str = "atual") -> dict[str, Any]:
        manifests = [m for m in self.report_store.list_manifests(MONTHLY_MAP_CITIES_ROUTINE, competencia=competencia) if str((m.get("metadata") or {}).get("period") or "atual") == ("fechado" if period == "fechado" else "atual")]
        if not manifests:
            return self._empty(competencia or "")
        manifest = manifests[-1]
        maps: dict[tuple[str, str], dict[str, str]] = {}
        warnings: list[str] = []
        for item in manifest.get("files") or []:
            path = Path(str(item.get("path") or ""))
            filial = "SUME" if "SUME" in path.name.upper() else "PATOS" if "PATOS" in path.name.upper() else ""
            try:
                for row in self._rows(path):
                    mapa = self._mapa(self._pick(row, "Mapa"))
                    cidade = self._pick(row, "Cidade", "Municipio", "Município", "Nome Cidade")
                    if not mapa:
                        continue
                    maps[(filial, mapa)] = {
                        "filial": filial or "-",
                        "mapa": mapa,
                        "cidade": cidade or "Não informada",
                        "data": self._pick(row, "Data", "Data Movimento"),
                    }
            except (OSError, UnicodeError, csv.Error) as exc:
                warnings.append(f"{path.name}: {exc}")
        rows = sorted(maps.values(), key=lambda item: (item["filial"], int(item["mapa"]) if item["mapa"].isdigit() else item["mapa"]))
        return {
            "ok": True,
            "competencia": competencia or str(manifest.get("reference_date") or "")[:7],
            "rows": rows,
            "summary": {"mapas": len(rows), "cidades": len({row["cidade"] for row in rows if row["cidade"] != "Não informada"}), "files": int(manifest.get("file_count") or 0), "stored_at": str(manifest.get("stored_at") or "")},
            "warnings": warnings,
        }

    @staticmethod
    def _rows(path: Path) -> list[dict[str, str]]:
        content = path.read_bytes().decode("cp1252", errors="replace")
        return list(csv.DictReader(io.StringIO(content), delimiter=";"))

    @classmethod
    def _pick(cls, row: Mapping[str, Any], *names: str) -> str:
        normalized = {cls._normal(key): str(value or "").strip() for key, value in row.items()}
        for name in names:
            value = normalized.get(cls._normal(name), "")
            if value:
                return value
        return ""

    @staticmethod
    def _normal(value: Any) -> str:
        return "".join(char for char in unicodedata.normalize("NFD", str(value or "")) if unicodedata.category(char) != "Mn").casefold().replace(" ", "")

    @staticmethod
    def _mapa(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        return digits.lstrip("0") or "0" if digits else ""

    @staticmethod
    def _empty(competencia: str) -> dict[str, Any]:
        return {"ok": True, "competencia": competencia, "rows": [], "summary": {"mapas": 0, "cidades": 0, "files": 0, "stored_at": ""}, "warnings": ["Nenhum lote mensal da 03.11.49.02 foi importado ainda."]}
