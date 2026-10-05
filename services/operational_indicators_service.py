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

    def __init__(self, *, report_store: Any, drevendas_import_service: Any | None = None, raw_sql_import_service: Any | None = None) -> None:
        self.report_store = report_store
        self.drevendas_import_service = drevendas_import_service
        self.raw_sql_import_service = raw_sql_import_service

    def build_dashboard(self, *, competencia: str | None = None, period: str = "atual") -> dict[str, Any]:
        normalized_period = "fechado" if str(period).lower() == "fechado" else "atual"
        # A Liga em produção deve consultar apenas a carga SQL. Os arquivos
        # são usados exclusivamente pelo importador, fora da requisição.
        if self.raw_sql_import_service is not None:
            return self._build_from_sql(competencia=competencia, period=normalized_period)
        manifests = [m for m in self.report_store.list_manifests(BI_INDICATORS_ROUTINE, competencia=competencia) if str((m.get("metadata") or {}).get("period") or "atual") == normalized_period]
        if not manifests:
            return self._empty(competencia or "")

        labels = self._labels_by_puxada()
        warnings: list[str] = []
        selected_competencia = str(competencia or "")
        latest: dict[str, Any] | None = None
        branches: dict[str, dict[str, Any]] = {}
        recognized_competencias: set[str] = set()
        # A newer, incomplete upload must not hide the last valid BI card.
        # Keep scanning newest-to-oldest until at least one recognized row is found.
        for candidate in reversed(manifests):
            candidate_branches: dict[str, dict[str, Any]] = {}
            candidate_competencias: set[str] = set()
            candidate_warnings: list[str] = []
            for file_info in candidate.get("files") or []:
                raw_path = str(file_info.get("path") or "")
                path = Path(raw_path)
                try:
                    rows = self._read_csv(path)
                except (OSError, UnicodeError, csv.Error) as exc:
                    candidate_warnings.append(f"{path.name}: não foi possível ler ({exc}).")
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
                    if row_competencia:
                        candidate_competencias.add(row_competencia)
                    if selected_competencia and row_competencia and row_competencia != selected_competencia:
                        continue
                    branch = candidate_branches.setdefault(
                        puxada,
                        {"puxada": puxada, "filial": labels.get(puxada) or _BRANCH_FALLBACKS.get(puxada) or str(row.get("Nome Revenda") or puxada).strip(), "metrics": {}},
                    )
                    raw_value = row.get("Valor Mes")
                    if metric in branch["metrics"]:
                        candidate_warnings.append(f"Métrica duplicada no 17.06: {puxada}/{metric}; foi mantido o último valor válido.")
                    branch["metrics"][metric] = self._number(raw_value) if str(raw_value or "").strip() else None
            if candidate_branches:
                latest = candidate
                branches = candidate_branches
                recognized_competencias = candidate_competencias
                warnings.extend(candidate_warnings)
                break
            warnings.extend(candidate_warnings)
        if latest is None:
            return self._empty(competencia or "") | {"warnings": warnings or ["Nenhum registro reconhecido no lote 17.06."]}
        if not selected_competencia and recognized_competencias:
            selected_competencia = max(recognized_competencias)
            if len(recognized_competencias) > 1:
                warnings.append("O lote 17.06 contém múltiplas competências; foi selecionada a mais recente: " + selected_competencia + ".")
            # Rebuild using the selected competence so a multi-month CSV does not mix cards.
            result = self.build_dashboard(competencia=selected_competencia, period=normalized_period)
            result["warnings"] = warnings + list(result.get("warnings") or [])
            return result
        missing: list[str] = []
        for branch in branches.values():
            for metric in _INDICATOR_BASES.values():
                if branch["metrics"].get(metric) is None:
                    missing.append(f"{branch['filial']}: {metric}")
        if missing:
            warnings.append("Valores ausentes no 17.06: " + ", ".join(missing[:20]) + ("." if len(missing) <= 20 else "; ..."))

        items = sorted(branches.values(), key=lambda item: str(item["filial"]).casefold())
        return {
            "ok": True,
            "competencia": selected_competencia,
            "operation": {"routine": BI_INDICATORS_ROUTINE, "code": "17.06", "label": "Indicadores BI"},
            "branches": items,
            "summary": {"branches": len(items), "files": int(latest.get("file_count") or 0), "stored_at": str(latest.get("stored_at") or "")},
            "warnings": warnings,
        }

    def _build_from_sql(self, *, competencia: str | None, period: str) -> dict[str, Any]:
        try:
            rows = self.raw_sql_import_service.fetch_rows(routine=BI_INDICATORS_ROUTINE, competencia=competencia, period=period)
        except Exception:
            rows = []
        if not rows:
            return self._empty(competencia or "") | {"warnings": ["Nenhum registro 17.06 persistido no SQL para esta competência."]}
        labels = self._labels_by_puxada()
        warnings: list[str] = []
        selected = str(competencia or "")
        recognized: set[str] = set()
        branches: dict[str, dict[str, Any]] = {}
        for row in rows:
            puxada = self._clean_puxada(row.get("Puxada"))
            metric = _INDICATOR_BASES.get(str(row.get("Base") or "").strip().zfill(4))
            if not puxada or metric is None:
                continue
            reference_date = str(row.get("_reference_date") or "").strip()
            year = str(row.get("Ano") or "").strip() or reference_date[:4]
            month_value = str(row.get("Mês") or row.get("Mes") or "").strip()
            month = month_value.zfill(2) if month_value else reference_date[5:7]
            row_competencia = f"{year}-{month}" if year.isdigit() and month.isdigit() else ""
            if row_competencia:
                recognized.add(row_competencia)
            if selected and row_competencia and row_competencia != selected:
                continue
            branch = branches.setdefault(puxada, {"puxada": puxada, "filial": labels.get(puxada) or _BRANCH_FALLBACKS.get(puxada) or str(row.get("Nome Revenda") or puxada).strip(), "metrics": {}})
            if metric in branch["metrics"]:
                warnings.append(f"Métrica duplicada no SQL: {puxada}/{metric}; foi mantido o último valor válido.")
            branch["metrics"][metric] = self._number(row.get("Valor Mes")) if str(row.get("Valor Mes") or "").strip() else None
        if not selected and recognized:
            selected = max(recognized)
            branches = {key: value for key, value in branches.items() if any(str(row.get("Puxada") or "") == key for row in rows)}
        if not branches:
            return self._empty(selected) | {"warnings": warnings or ["Nenhum registro reconhecido no SQL."]}
        items = sorted(branches.values(), key=lambda item: str(item["filial"]).casefold())
        return {"ok": True, "competencia": selected, "operation": {"routine": BI_INDICATORS_ROUTINE, "code": "17.06", "label": "Indicadores BI"}, "branches": items, "summary": {"branches": len(items), "files": 0, "stored_at": "sql"}, "warnings": warnings}

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
    def _number(value: Any) -> float | None:
        text = str(value or "").replace(".", "").replace(",", ".").strip()
        try:
            return float(text)
        except ValueError:
            return None

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
