from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bot_api.services.liga_entrega_report_store import LigaEntregaReportStore


@dataclass(frozen=True)
class LigaEntregaImportValidation:
    valid: bool
    error_count: int
    warning_count: int
    file_count: int
    total_bytes: int
    routine: str
    errors: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.valid,
            "valid": self.valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "routine": self.routine,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class LigaEntregaImportSummary:
    dataset_name: str
    label: str
    routine: str
    file_count: int
    total_rows: int
    total_bytes: int
    filenames: list[str]
    reference_date: str | None = None
    batch_id: str | None = None
    stored_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "label": self.label,
            "routine": self.routine,
            "file_count": self.file_count,
            "total_rows": self.total_rows,
            "total_bytes": self.total_bytes,
            "filenames": list(self.filenames),
            "reference_date": self.reference_date,
            "batch_id": self.batch_id,
            "stored_at": self.stored_at,
        }


class LigaEntregaReportImportService:
    """Importa insumos do painel da Liga para o armazenamento compartilhado da Liga Entrega."""

    def __init__(
        self,
        *,
        report_store: LigaEntregaReportStore,
        dataset_name: str,
        label: str,
        routine: str,
        allowed_extensions: set[str],
        min_files: int = 1,
        expected_name_patterns: tuple[str, ...] = (),
    ) -> None:
        self.report_store = report_store
        self.dataset_name = str(dataset_name)
        self.label = str(label)
        self.routine = str(routine)
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions}
        self.min_files = max(1, int(min_files))
        self.expected_name_patterns = tuple(expected_name_patterns)

    def validate_source(self, source_path: str | Path) -> LigaEntregaImportValidation:
        files = self._source_files(source_path)
        errors: list[str] = []
        warnings: list[str] = []
        seen: set[str] = set()
        total_bytes = 0

        if len(files) < self.min_files:
            errors.append(f"Esperado ao menos {self.min_files} arquivo(s); encontrado(s) {len(files)}.")

        for path in files:
            name = path.name
            suffix = path.suffix.lower()
            if name in seen:
                errors.append(f"Arquivo duplicado: {name}.")
            seen.add(name)
            if suffix not in self.allowed_extensions:
                errors.append(f"Extensao invalida em {name}. Use: {', '.join(sorted(self.allowed_extensions))}.")
            try:
                size = path.stat().st_size
            except OSError as exc:
                errors.append(f"Nao foi possivel ler {name}: {exc}.")
                continue
            if size <= 0:
                errors.append(f"Arquivo vazio: {name}.")
            total_bytes += max(size, 0)
            if self.expected_name_patterns and not any(re.search(pattern, name, flags=re.IGNORECASE) for pattern in self.expected_name_patterns):
                warnings.append(f"Nome fora do padrao esperado: {name}.")

        if not files:
            errors.append("Nenhum arquivo encontrado para importar.")

        return LigaEntregaImportValidation(
            valid=not errors,
            error_count=len(errors),
            warning_count=len(warnings),
            file_count=len(files),
            total_bytes=total_bytes,
            routine=self.routine,
            errors=errors,
            warnings=warnings,
        )

    def summarize_source(self, source_path: str | Path) -> LigaEntregaImportSummary:
        files = self._source_files(source_path)
        total_bytes = sum(max(path.stat().st_size, 0) for path in files if path.exists())
        total_rows = 0
        for path in files:
            if path.suffix.lower() in {".csv", ".txt"}:
                total_rows += self._count_text_rows(path)
        return LigaEntregaImportSummary(
            dataset_name=self.dataset_name,
            label=self.label,
            routine=self.routine,
            file_count=len(files),
            total_rows=total_rows,
            total_bytes=total_bytes,
            filenames=[path.name for path in files],
        )

    def import_source(self, source_path: str | Path, reference_date: date | None = None) -> LigaEntregaImportSummary:
        validation = self.validate_source(source_path)
        if validation.error_count:
            raise ValueError("A validacao encontrou erros: " + "; ".join(validation.errors))
        files = self._source_files(source_path)
        payload = {path.name: path.read_bytes() for path in files}
        ref_date = reference_date or datetime.now().date()
        manifest = self.report_store.store_batch(
            routine=self.routine,
            files=payload,
            reference_date=ref_date,
            metadata={"source": "admin_import_panel", "dataset": self.dataset_name},
        )
        summary = self.summarize_source(source_path)
        return LigaEntregaImportSummary(
            dataset_name=self.dataset_name,
            label=self.label,
            routine=self.routine,
            file_count=summary.file_count,
            total_rows=summary.total_rows,
            total_bytes=summary.total_bytes,
            filenames=summary.filenames,
            reference_date=str(manifest.get("reference_date") or ref_date.isoformat()),
            batch_id=str(manifest.get("batch_id") or ""),
            stored_at=str(manifest.get("stored_at") or ""),
        )

    def latest_status(self) -> dict[str, Any] | None:
        manifest = self.report_store.latest_manifest(self.routine)
        if not manifest:
            return None
        files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        total_bytes = sum(int(item.get("bytes") or 0) for item in files if isinstance(item, dict))
        filenames = [str(item.get("filename") or "") for item in files if isinstance(item, dict)]
        return {
            "batch_id": str(manifest.get("batch_id") or ""),
            "source_file": ", ".join(name for name in filenames if name),
            "file_hash": "",
            "reference_date": str(manifest.get("reference_date") or ""),
            "total_rows": len(filenames),
            "imported_at": str(manifest.get("stored_at") or ""),
            "total_bytes": total_bytes,
        }


    def _source_files(self, source_path: str | Path) -> list[Path]:
        path = Path(source_path)
        if path.is_file():
            return [path]
        if not path.exists():
            return []
        return sorted(
            item
            for item in path.iterdir()
            if item.is_file() and not item.name.startswith(".") and item.suffix.lower() in self.allowed_extensions
        )

    @staticmethod
    def _count_text_rows(path: Path) -> int:
        try:
            with path.open("r", encoding="utf-8-sig", errors="ignore") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0
