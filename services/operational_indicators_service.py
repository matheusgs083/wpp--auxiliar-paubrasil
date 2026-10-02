from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any


BI_INDICATORS_ROUTINE = "1706_BI_INDICADORES"
_BRANCH_FALLBACKS = {"00747530": "Patos", "00747548": "Sumé"}
_INDICATOR_BASES = {"0649": "ocupacao", "0652": "caixas_por_viagem"}


class OperationalIndicatorsService:
    """Consolida os indicadores oficiais exportados pelo BI (relatório 17.06)."""

    def __init__(self, *, report_store: Any, drevendas_import_service: Any | None = None) -> None:
        self.report_store = report_store
        self.drevendas_import_service = drevendas_import_service

    def build_dashboard(self, *, competencia: str | None = None, period: str = "atual") -> dict[str, Any]:
        manifests = [m for m in self.report_store.list_manifests(BI_INDICATORS_ROUTINE, competencia=competencia) if str((m.get("metadata") or {}).get("period") or "atual") == ("fechado" if period == "fechado" else "atual")]
        if not manifests:
            return self._empty(competencia or "")

        latest = manifests[-1]
        labels = self._labels_by_puxada()
        branches: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        selected_competencia = str(competencia or "")
        for file_info in latest.get("files") or []:
            raw_path = str(file_info.get("path") or "")
            path = Path(raw_path)
            try:
                rows = self._read_csv(path)
            except (OSError, UnicodeError, csv.Error) as exc:
                warnings.append(f"{path.name}: não foi possível ler ({exc}).")
                continue
            for row in rows:
                puxada = self._clean_puxada(row.get("Puxada"))
                base = str(row.get("Base") or "").strip().zfill(4)
                metric = _INDICATOR_BASES.get(base)
                if not puxada or metric is None:
                    continue
                year = str(row.get("Ano") or "").strip()
                month = str(row.get("Mês") or row.get("Mes") or "").strip().zfill(2)
                row_competencia = f"{year}-{month}" if year.isdigit() and month.isdigit() else ""
                if selected_competencia and row_competencia and row_competencia != selected_competencia:
                    continue
                selected_competencia = selected_competencia or row_competencia
                branch = branches.setdefault(
                    puxada,
                    {"puxada": puxada, "filial": labels.get(puxada) or _BRANCH_FALLBACKS.get(puxada) or str(row.get("Nome Revenda") or puxada).strip(), "metrics": {}},
                )
                branch["metrics"][metric] = self._number(row.get("Valor Mes"))

        items = sorted(branches.values(), key=lambda item: str(item["filial"]).casefold())
        return {
            "ok": True,
            "competencia": selected_competencia,
            "operation": {"routine": BI_INDICATORS_ROUTINE, "code": "17.06", "label": "Indicadores BI"},
            "branches": items,
            "summary": {"branches": len(items), "files": int(latest.get("file_count") or 0), "stored_at": str(latest.get("stored_at") or "")},
            "warnings": warnings,
        }

    def _labels_by_puxada(self) -> dict[str, str]:
        service = self.drevendas_import_service
        if service is None:
            return {}
        try:
            return {self._clean_puxada(key): str(value) for key, value in service.latest_labels_by_puxada().items() if self._clean_puxada(key)}
        except Exception:
            return {}

    @staticmethod
    def _read_csv(path: Path) -> list[dict[str, str]]:
        content = path.read_bytes().decode("cp1252", errors="replace")
        return list(csv.DictReader(io.StringIO(content), delimiter=";"))

    @staticmethod
    def _clean_puxada(value: Any) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        return digits.zfill(8) if digits else ""

    @staticmethod
    def _number(value: Any) -> float:
        text = str(value or "").replace(".", "").replace(",", ".").strip()
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def _empty(competencia: str) -> dict[str, Any]:
        return {
            "ok": True,
            "competencia": competencia,
            "operation": {"routine": BI_INDICATORS_ROUTINE, "code": "17.06", "label": "Indicadores BI"},
            "branches": [],
            "summary": {"branches": 0, "files": 0, "stored_at": ""},
            "warnings": ["Nenhum lote 17.06 foi importado ainda."],
        }
