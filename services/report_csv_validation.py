from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CsvDatasetSpec:
    dataset_name: str
    required_columns: tuple[str, ...]
    key_columns: tuple[str, ...]
    allowed_duplicate_headers: frozenset[str] = frozenset()
    pending_filter_column: str | None = None
    pending_filter_value: str | None = None


@dataclass(frozen=True)
class CsvValidationIssue:
    severity: str
    code: str
    message: str
    file_path: str
    row_number: int | None = None
    column_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CsvFileValidation:
    file_path: str
    columns: int
    data_rows: int
    ok: bool
    error_count: int
    warning_count: int
    shorter_row_count: int
    longer_row_count: int
    missing_columns: tuple[str, ...]
    key_blank_counts: dict[str, int]
    pending_candidate_rows: int | None
    sample_errors: tuple[CsvValidationIssue, ...]
    sample_warnings: tuple[CsvValidationIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "columns": self.columns,
            "data_rows": self.data_rows,
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "shorter_row_count": self.shorter_row_count,
            "longer_row_count": self.longer_row_count,
            "missing_columns": list(self.missing_columns),
            "key_blank_counts": dict(self.key_blank_counts),
            "pending_candidate_rows": self.pending_candidate_rows,
            "sample_errors": [issue.to_dict() for issue in self.sample_errors],
            "sample_warnings": [issue.to_dict() for issue in self.sample_warnings],
        }


@dataclass(frozen=True)
class CsvValidationSummary:
    dataset_name: str
    source_path: str
    ok: bool
    file_count: int
    total_rows: int
    error_count: int
    warning_count: int
    files: tuple[CsvFileValidation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "source_path": self.source_path,
            "ok": self.ok,
            "file_count": self.file_count,
            "total_rows": self.total_rows,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "files": [item.to_dict() for item in self.files],
        }

    def first_error_message(self) -> str:
        for file_result in self.files:
            for issue in file_result.sample_errors:
                return issue.message
        return f"Validacao estrutural falhou para {self.dataset_name}."

    def ensure_valid(self) -> None:
        if not self.ok:
            raise RuntimeError(self.first_error_message())


DCLIENTES_CSV_SPEC = CsvDatasetSpec(
    dataset_name="dclientes",
    required_columns=(
        "Empresa",
        "Filial",
        "Cod PDV",
        "Documento",
        "Nome Fantasia",
        "Razao Social",
        "Status do PDV",
        "Setor VDE",
        "Area VDE",
        "GV VDE",
        "Setor VDI",
        "Area VDI",
        "GV VDI",
    ),
    key_columns=("Filial", "Cod PDV"),
)

INADIMPLENCIA_CSV_SPEC = CsvDatasetSpec(
    dataset_name="inadimplencia",
    required_columns=(
        "UNB",
        "Cliente",
        "Nome",
        "DataEmissao",
        "DataVencto",
        "ValorOriginal",
        "ValorPendente",
        "ValorCorrigido",
        "Dias",
    ),
    key_columns=("UNB", "Cliente"),
    allowed_duplicate_headers=frozenset({"UNB"}),
)

COMODATOS_CSV_SPEC = CsvDatasetSpec(
    dataset_name="comodatos",
    required_columns=(
        "UNB Cliente",
        "Cliente",
        "Nome / Razao",
        "Nro Comodato",
        "Descricao",
        "Saldo",
        "Sub-Tipo Material",
        "Data Recolha",
    ),
    key_columns=("UNB Cliente", "Cliente", "Nro Comodato"),
    pending_filter_column="Data Recolha",
    pending_filter_value="00/00/0000",
)

DSETORES_CSV_SPEC = CsvDatasetSpec(
    dataset_name="dsetores",
    required_columns=(
        "Filial",
        "Dc",
        "Gv",
        "Setor",
    ),
    key_columns=("Filial", "Setor"),
)


def validate_csv_source(source_path: Path, spec: CsvDatasetSpec) -> CsvValidationSummary:
    files = resolve_csv_files(source_path)
    file_results = tuple(_validate_csv_file(file_path, spec) for file_path in files)
    total_rows = sum(item.data_rows for item in file_results)
    error_count = sum(item.error_count for item in file_results)
    warning_count = sum(item.warning_count for item in file_results)
    return CsvValidationSummary(
        dataset_name=spec.dataset_name,
        source_path=str(source_path),
        ok=error_count == 0,
        file_count=len(file_results),
        total_rows=total_rows,
        error_count=error_count,
        warning_count=warning_count,
        files=file_results,
    )


def resolve_csv_files(source_path: Path) -> list[Path]:
    path = source_path.expanduser().resolve()
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(f"Caminho nao encontrado: {source_path}")
    files = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".csv")
    if not files:
        raise FileNotFoundError(f"Nao encontrei arquivos CSV em: {source_path}")
    return files


def build_required_indexes(header: list[str], spec: CsvDatasetSpec) -> dict[str, int]:
    normalized_header = [normalize_header_name(item) for item in header]
    indexes: dict[str, int] = {}
    for column_name in spec.required_columns:
        normalized = normalize_header_name(column_name)
        try:
            indexes[column_name] = normalized_header.index(normalized)
        except ValueError as exc:
            raise RuntimeError(f"Coluna obrigatoria ausente em {spec.dataset_name}: {column_name}") from exc
    return indexes


def normalize_header_name(value: str) -> str:
    text = str(value or "").replace("\ufeff", "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _validate_csv_file(file_path: Path, spec: CsvDatasetSpec) -> CsvFileValidation:
    errors: list[CsvValidationIssue] = []
    warnings: list[CsvValidationIssue] = []
    error_count = 0
    warning_count = 0
    shorter_row_count = 0
    longer_row_count = 0
    data_rows = 0
    pending_candidate_rows = 0 if spec.pending_filter_column else None
    key_blank_counts = {column_name: 0 for column_name in spec.key_columns}

    def add_issue(
        severity: str,
        code: str,
        message: str,
        row_number: int | None = None,
        column_name: str | None = None,
    ) -> None:
        nonlocal error_count, warning_count
        issue = CsvValidationIssue(
            severity=severity,
            code=code,
            message=message,
            file_path=str(file_path),
            row_number=row_number,
            column_name=column_name,
        )
        if severity == "error":
            error_count += 1
            if len(errors) < 10:
                errors.append(issue)
            return
        warning_count += 1
        if len(warnings) < 10:
            warnings.append(issue)

    with file_path.open("r", encoding="cp1252", newline="") as fp:
        reader = csv.reader(fp, delimiter=";")
        try:
            header = next(reader)
        except StopIteration:
            add_issue("error", "empty_file", f"Arquivo vazio em {spec.dataset_name}: {file_path}.")
            return CsvFileValidation(
                file_path=str(file_path),
                columns=0,
                data_rows=0,
                ok=False,
                error_count=error_count,
                warning_count=warning_count,
                shorter_row_count=0,
                longer_row_count=0,
                missing_columns=tuple(spec.required_columns),
                key_blank_counts=key_blank_counts,
                pending_candidate_rows=pending_candidate_rows,
                sample_errors=tuple(errors),
                sample_warnings=tuple(warnings),
            )

        normalized_header = [normalize_header_name(item) for item in header]
        normalized_counter = Counter(item for item in normalized_header if item)
        required_normalized = {column_name: normalize_header_name(column_name) for column_name in spec.required_columns}
        allowed_duplicate_headers = {normalize_header_name(item) for item in spec.allowed_duplicate_headers}

        blank_header_count = sum(1 for item in normalized_header if not item)
        if blank_header_count:
            add_issue(
                "warning",
                "blank_header",
                f"{file_path} tem {blank_header_count} coluna(s) sem nome no cabecalho.",
            )

        for normalized_name, count in normalized_counter.items():
            if count <= 1:
                continue
            duplicated_label = next(
                (raw_name.strip() for raw_name in header if normalize_header_name(raw_name) == normalized_name and raw_name.strip()),
                normalized_name,
            )
            if normalized_name in required_normalized.values() and normalized_name not in allowed_duplicate_headers:
                add_issue(
                    "error",
                    "duplicated_required_header",
                    f"{file_path} tem coluna obrigatoria duplicada: {duplicated_label}.",
                    column_name=duplicated_label,
                )
            elif normalized_name not in allowed_duplicate_headers:
                add_issue(
                    "warning",
                    "duplicated_header",
                    f"{file_path} tem coluna repetida no cabecalho: {duplicated_label}.",
                    column_name=duplicated_label,
                )

        missing_columns = tuple(
            column_name
            for column_name, normalized_name in required_normalized.items()
            if normalized_name not in normalized_header
        )
        for column_name in missing_columns:
            add_issue(
                "error",
                "missing_required_column",
                f"Coluna obrigatoria ausente em {spec.dataset_name}: {column_name}.",
                column_name=column_name,
            )

        key_indexes: dict[str, int] = {}
        pending_index: int | None = None
        if not missing_columns:
            key_indexes = build_required_indexes(header, spec)
            if spec.pending_filter_column:
                pending_index = key_indexes[spec.pending_filter_column]

        for row_number, row in enumerate(reader, start=2):
            if not row or not any(str(value or "").strip() for value in row):
                continue
            data_rows += 1

            if len(row) < len(header):
                shorter_row_count += 1
                add_issue(
                    "error",
                    "short_row",
                    f"{file_path} tem linha {row_number} com menos colunas que o cabecalho ({len(row)} de {len(header)}).",
                    row_number=row_number,
                )
            elif len(row) > len(header):
                extra_values = row[len(header) :]
                if any(str(value or "").strip() for value in extra_values):
                    longer_row_count += 1
                    add_issue(
                        "warning",
                        "long_row",
                        f"{file_path} tem linha {row_number} com mais colunas que o cabecalho ({len(row)} de {len(header)}).",
                        row_number=row_number,
                    )

            for column_name in spec.key_columns:
                idx = key_indexes.get(column_name)
                value = row[idx].strip() if idx is not None and idx < len(row) else ""
                if value:
                    continue
                key_blank_counts[column_name] += 1
                add_issue(
                    "error",
                    "blank_key_column",
                    f"{file_path} tem linha {row_number} com chave vazia em {column_name}.",
                    row_number=row_number,
                    column_name=column_name,
                )

            if pending_index is not None and pending_index < len(row):
                if row[pending_index].strip() == str(spec.pending_filter_value or "").strip():
                    pending_candidate_rows = (pending_candidate_rows or 0) + 1

        if data_rows == 0:
            add_issue(
                "warning",
                "no_data_rows",
                f"{file_path} nao possui linhas de dados.",
            )
        if spec.pending_filter_column and pending_candidate_rows == 0:
            add_issue(
                "warning",
                "no_pending_rows",
                f"{file_path} nao possui linhas com {spec.pending_filter_column} = {spec.pending_filter_value}.",
                column_name=spec.pending_filter_column,
            )

    return CsvFileValidation(
        file_path=str(file_path),
        columns=len(header),
        data_rows=data_rows,
        ok=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        shorter_row_count=shorter_row_count,
        longer_row_count=longer_row_count,
        missing_columns=missing_columns,
        key_blank_counts=key_blank_counts,
        pending_candidate_rows=pending_candidate_rows,
        sample_errors=tuple(errors),
        sample_warnings=tuple(warnings),
    )
