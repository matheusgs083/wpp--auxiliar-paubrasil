from __future__ import annotations

import base64
import binascii
import csv
import io
import re
import threading
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path as FilePath
from secrets import compare_digest
from typing import Any, Literal
from unicodedata import normalize as unicode_normalize
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


_CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
_MAX_DATE_RANGE_DAYS = 366
_PROMAX_LOCAL_TIMEZONE = ZoneInfo("America/Fortaleza")
_PROMAX_NON_RETRYABLE_UNIT_STATUSES = {"SEM CONTEUDO", "SEM CONTEÚDO", "SEM DADOS"}
_PROMAX_030206_UNIT_FILIAL_DEFAULTS = {
    "0640001": "1",
    "0640002": "2",
    "2210003": "3",
    "2210004": "4",
    "3480005": "5",
    "3610006": "6",
    "3610007": "7",
    "3610008": "8",
}
_PROMAX_BOLETO_IMPORT_LOCK = threading.Lock()
_PROMAX_RETRYABLE_ERROR_TERMS = (
    "download(s) http falharam",
    "falha na fila de downloads http",
    "resposta html sem url temporaria",
    "url temporaria nao encontrada",
    "url temporária não encontrada",
    "temporarily unavailable",
    "temporariamente indisponivel",
    "temporariamente indisponível",
    "timeout",
    "timed out",
    "connection",
    "conexao",
    "conexão",
    "10054",
    "10060",
    "10061",
    "502",
    "503",
    "504",
)


def _normalize_category(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _CATEGORY_PATTERN.fullmatch(normalized):
        raise ValueError("category must use lowercase letters, numbers, '_' or '-'")
    return normalized


def _normalize_identifiers(values: list[str], *, field_name: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value or "").strip()
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(f"{field_name} contains an invalid identifier")
        if value in seen:
            raise ValueError(f"{field_name} must not contain duplicate identifiers")
        seen.add(value)
        normalized.append(value)
    return normalized


def _validate_date_range(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if (end_date - start_date).days > _MAX_DATE_RANGE_DAYS:
        raise ValueError(f"date range must not exceed {_MAX_DATE_RANGE_DAYS} days")


def _promax_job_created_bounds(
    created_from: date | None,
    created_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    if created_from and created_to and created_to < created_from:
        raise HTTPException(
            status_code=422,
            detail="A data final do filtro nao pode ser anterior a data inicial.",
        )
    start_at = (
        datetime.combine(created_from, time.min, _PROMAX_LOCAL_TIMEZONE).astimezone(UTC)
        if created_from
        else None
    )
    before_at = (
        datetime.combine(
            created_to + timedelta(days=1),
            time.min,
            _PROMAX_LOCAL_TIMEZONE,
        ).astimezone(UTC)
        if created_to
        else None
    )
    return start_at, before_at


def _plain_text(value: Any) -> str:
    text = str(value or "")
    normalized = unicode_normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text.casefold()


def _mapping_value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _clean_identifier(value: Any) -> str:
    text = str(value or "").strip()
    return text if _IDENTIFIER_PATTERN.fullmatch(text) else ""


def _payload_units(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    units = payload.get("units")
    if not isinstance(units, Sequence) or isinstance(units, (str, bytes, bytearray)):
        return []
    normalized: list[str] = []
    for item in units:
        clean = _clean_identifier(item)
        if clean and clean not in normalized:
            normalized.append(clean)
    return normalized


def _failed_units_from_result(result: Any) -> tuple[list[str], list[dict[str, Any]]]:
    failed_units: list[str] = []
    failed_details: list[dict[str, Any]] = []
    if not isinstance(result, Mapping):
        return failed_units, failed_details

    explicit_units = result.get("failed_units")
    if isinstance(explicit_units, Sequence) and not isinstance(explicit_units, (str, bytes, bytearray)):
        for item in explicit_units:
            clean = _clean_identifier(item)
            if clean and clean not in failed_units:
                failed_units.append(clean)

    detail_rows = result.get("failed_unit_details")
    if isinstance(detail_rows, Sequence) and not isinstance(detail_rows, (str, bytes, bytearray)):
        for row in detail_rows:
            if isinstance(row, Mapping):
                status = str(row.get("status") or "").strip().upper()
                if status in _PROMAX_NON_RETRYABLE_UNIT_STATUSES:
                    continue
                unit = next(
                    (
                        _clean_identifier(row.get(key))
                        for key in ("unit", "unidade", "unit_id", "code", "id")
                        if _clean_identifier(row.get(key))
                    ),
                    "",
                )
                detail = dict(row)
            else:
                status = ""
                unit = _clean_identifier(row)
                detail = {"unit": unit}
            if unit and unit not in failed_units:
                failed_units.append(unit)
            if unit:
                failed_details.append({"unit": unit, "status": status, **detail})

    return failed_units, failed_details


def _extract_failed_retry_units(job: Any) -> tuple[list[str], list[dict[str, Any]], str]:
    payload = _mapping_value(job, "payload", {})
    result = _mapping_value(job, "result", {})
    original_units = _payload_units(payload)
    failed_units, failed_details = _failed_units_from_result(result)
    if original_units and not failed_units:
        result_text = _plain_text(_promax_result_text(job))
        for unit in original_units:
            if _plain_text(unit) in result_text:
                failed_units.append(unit)
                failed_details.append(
                    {
                        "unit": unit,
                        "status": "FALHA DETECTADA",
                        "detail": _mapping_value(result, "message", "") or _mapping_value(job, "error", ""),
                    }
                )
    if original_units and failed_units:
        allowed = set(original_units)
        failed_units = [unit for unit in failed_units if unit in allowed]
        failed_details = [
            detail
            for detail in failed_details
            if str(detail.get("unit") or "").strip() in allowed
        ]
    if failed_units:
        return failed_units, failed_details, "failed_units"
    return original_units, failed_details, "full_job"


def _promax_result_text(job: Any) -> str:
    result = _mapping_value(job, "result", {})
    parts = [
        _mapping_value(result, "message", ""),
        _mapping_value(job, "error", ""),
        _mapping_value(job, "failure_reason", ""),
    ]
    return " ".join(str(part or "") for part in parts)


def _is_recoverable_promax_failure(job: Any) -> bool:
    text = _plain_text(_promax_result_text(job))
    return any(_plain_text(term) in text for term in _PROMAX_RETRYABLE_ERROR_TERMS)


def _has_auto_retry_marker(job: Any) -> bool:
    payload = _mapping_value(job, "payload", {})
    return isinstance(payload, Mapping) and bool(payload.get("auto_retry_of_job_id"))


def _retry_payload_for_job(job: Any) -> tuple[dict[str, Any], list[str], str]:
    payload = _mapping_value(job, "payload", {})
    retry_payload = dict(payload or {}) if isinstance(payload, Mapping) else {}
    retry_units, failed_details, retry_mode = _extract_failed_retry_units(job)
    if retry_mode == "failed_units" and retry_units:
        retry_payload["units"] = retry_units
        retry_payload["retry_scope"] = "failed_units"
        retry_payload["failed_unit_details"] = failed_details
    else:
        retry_payload["retry_scope"] = "full_job"
    return retry_payload, retry_units, retry_mode


def _catalog_identifiers(value: Any) -> set[str] | None:
    if isinstance(value, Mapping):
        return {str(item).strip() for item in value if str(item).strip()}
    if not isinstance(value, (list, tuple, set, frozenset)):
        return None

    identifiers: set[str] = set()
    for item in value:
        if isinstance(item, Mapping):
            identifier = next(
                (
                    str(item.get(key) or "").strip()
                    for key in ("id", "key", "code", "value", "routine", "unit")
                    if str(item.get(key) or "").strip()
                ),
                "",
            )
        else:
            identifier = str(item or "").strip()
        if identifier:
            identifiers.add(identifier)
    return identifiers


def _catalog_category_config(resolved_catalog: Mapping[str, Any], category: str) -> Any:
    categories = resolved_catalog.get("categories", resolved_catalog)
    if isinstance(categories, Mapping):
        return categories.get(category)
    if isinstance(categories, (list, tuple)):
        for item in categories:
            if not isinstance(item, Mapping):
                continue
            item_category = next(
                (
                    str(item.get(key) or "").strip().lower()
                    for key in ("id", "key", "category", "name")
                    if str(item.get(key) or "").strip()
                ),
                "",
            )
            if item_category == category:
                return item
    return None


def _validate_catalog_selection(
    resolved_catalog: Any,
    *,
    category: str,
    routines: list[str] | None,
    units: list[str] | None,
) -> None:
    if not isinstance(resolved_catalog, Mapping):
        raise HTTPException(status_code=503, detail="Catalogo Promax indisponivel ou mal configurado.")

    category_config = _catalog_category_config(resolved_catalog, category)
    if category_config is None:
        raise HTTPException(status_code=422, detail=f"Categoria Promax desconhecida: {category}.")

    if isinstance(category_config, Mapping):
        catalog_routines = category_config.get("routines")
        catalog_units = category_config.get("units", resolved_catalog.get("units"))
    else:
        catalog_routines = category_config
        catalog_units = resolved_catalog.get("units")

    if routines is not None:
        allowed_routines = _catalog_identifiers(catalog_routines)
        if allowed_routines is None:
            raise HTTPException(status_code=503, detail="Catalogo Promax sem rotinas validas.")
        unknown_routines = [routine for routine in routines if routine not in allowed_routines]
        if unknown_routines:
            raise HTTPException(
                status_code=422,
                detail=f"Rotinas fora do catalogo para {category}: {', '.join(unknown_routines)}.",
            )

    if units is not None:
        allowed_units = _catalog_identifiers(catalog_units)
        if allowed_units is None:
            raise HTTPException(status_code=503, detail="Catalogo Promax sem unidades validas.")
        unknown_units = [unit for unit in units if allowed_units and unit not in allowed_units]
        if unknown_units:
            raise HTTPException(
                status_code=422,
                detail=f"Unidades fora do catalogo para {category}: {', '.join(unknown_units)}.",
            )


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PromaxJobCreateRequest(_StrictPayload):
    category: str = Field(min_length=1, max_length=64)
    routines: list[str] = Field(min_length=1, max_length=50)
    units: list[str] = Field(default_factory=list, max_length=100)
    start_date: date
    end_date: date
    send_dates: StrictBool = False
    publish: StrictBool = False

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return _normalize_category(value)

    @field_validator("routines")
    @classmethod
    def validate_routines(cls, values: list[str]) -> list[str]:
        return _normalize_identifiers(values, field_name="routines")

    @field_validator("units")
    @classmethod
    def validate_units(cls, values: list[str]) -> list[str]:
        return _normalize_identifiers(values, field_name="units")

    @model_validator(mode="after")
    def validate_dates(self) -> PromaxJobCreateRequest:
        _validate_date_range(self.start_date, self.end_date)
        return self


class PromaxScheduleCreateRequest(PromaxJobCreateRequest):
    name: str = Field(min_length=1, max_length=120)
    schedule_type: Literal["daily", "weekly", "monthly"]
    time_of_day: time
    timezone: str = Field(default="America/Fortaleza", min_length=1, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    trigger_after_schedule_id: str | None = Field(
        default=None,
        pattern=_UUID_PATTERN,
    )
    enabled: StrictBool = True

    @model_validator(mode="after")
    def validate_schedule(self) -> PromaxScheduleCreateRequest:
        if self.schedule_type == "weekly" and self.weekday is None:
            raise ValueError("weekday is required for a weekly schedule")
        if self.schedule_type == "monthly" and self.day_of_month is None:
            raise ValueError("day_of_month is required for a monthly schedule")
        return self


class PromaxGroupSelection(_StrictPayload):
    category: str = Field(min_length=1, max_length=64)
    routines: list[str] = Field(min_length=1, max_length=50)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return _normalize_category(value)

    @field_validator("routines")
    @classmethod
    def validate_routines(cls, values: list[str]) -> list[str]:
        return _normalize_identifiers(values, field_name="routines")


class PromaxJobBatchCreateRequest(_StrictPayload):
    groups: list[PromaxGroupSelection] = Field(min_length=1, max_length=50)
    units: list[str] = Field(default_factory=list, max_length=100)
    start_date: date
    end_date: date
    send_dates: StrictBool = False
    publish: StrictBool = False

    @field_validator("units")
    @classmethod
    def validate_units(cls, values: list[str]) -> list[str]:
        return _normalize_identifiers(values, field_name="units")

    @model_validator(mode="after")
    def validate_batch(self) -> PromaxJobBatchCreateRequest:
        _validate_date_range(self.start_date, self.end_date)
        categories = [group.category for group in self.groups]
        if len(categories) != len(set(categories)):
            raise ValueError("groups must not contain duplicate categories")
        return self


class PromaxScheduleChainCreateRequest(_StrictPayload):
    name: str = Field(min_length=1, max_length=120)
    groups: list[PromaxGroupSelection] = Field(min_length=1, max_length=50)
    units: list[str] = Field(default_factory=list, max_length=100)
    start_date: date
    end_date: date
    send_dates: StrictBool = False
    publish: StrictBool = False
    schedule_type: Literal["daily", "weekly", "monthly"]
    time_of_day: time
    timezone: str = Field(default="America/Fortaleza", min_length=1, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    trigger_after_schedule_id: str | None = Field(
        default=None,
        pattern=_UUID_PATTERN,
    )
    enabled: StrictBool = True

    @field_validator("units")
    @classmethod
    def validate_units(cls, values: list[str]) -> list[str]:
        return _normalize_identifiers(values, field_name="units")

    @model_validator(mode="after")
    def validate_chain(self) -> PromaxScheduleChainCreateRequest:
        _validate_date_range(self.start_date, self.end_date)
        categories = [group.category for group in self.groups]
        if len(categories) != len(set(categories)):
            raise ValueError("groups must not contain duplicate categories")
        if self.schedule_type == "weekly" and self.weekday is None:
            raise ValueError("weekday is required for a weekly schedule")
        if self.schedule_type == "monthly" and self.day_of_month is None:
            raise ValueError("day_of_month is required for a monthly schedule")
        return self


class PromaxScheduleUpdateRequest(_StrictPayload):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    schedule_type: Literal["daily", "weekly", "monthly"] | None = None
    time_of_day: time | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    weekday: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    trigger_after_schedule_id: str | None = Field(
        default=None,
        pattern=_UUID_PATTERN,
    )
    enabled: StrictBool | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    routines: list[str] | None = Field(default=None, min_length=1, max_length=50)
    units: list[str] | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    send_dates: StrictBool | None = None
    publish: StrictBool | None = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        return _normalize_category(value) if value is not None else None

    @field_validator("routines")
    @classmethod
    def validate_routines(cls, values: list[str] | None) -> list[str] | None:
        return _normalize_identifiers(values, field_name="routines") if values is not None else None

    @field_validator("units")
    @classmethod
    def validate_units(cls, values: list[str] | None) -> list[str] | None:
        return _normalize_identifiers(values, field_name="units") if values is not None else None

    @model_validator(mode="after")
    def validate_update(self) -> PromaxScheduleUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("at least one schedule field must be provided")
        selection_fields = {
            "category",
            "routines",
            "units",
            "start_date",
            "end_date",
            "send_dates",
            "publish",
        }
        changed_selection_fields = selection_fields.intersection(self.model_fields_set)
        if changed_selection_fields and changed_selection_fields != selection_fields:
            raise ValueError("all job selection fields are required when a schedule payload is updated")
        if self.start_date is not None and self.end_date is not None:
            _validate_date_range(self.start_date, self.end_date)
        if self.schedule_type == "weekly" and self.weekday is None:
            raise ValueError("weekday is required when changing to a weekly schedule")
        if self.schedule_type == "monthly" and self.day_of_month is None:
            raise ValueError("day_of_month is required when changing to a monthly schedule")
        return self


class PromaxWorkerClaimRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    pid: int = Field(gt=0, le=2_147_483_647)
    lease_seconds: int = Field(default=120, ge=15, le=3600)


class PromaxWorkerAssignmentItem(_StrictPayload):
    scope_type: Literal["category", "routine"] = "category"
    category: str = Field(min_length=1, max_length=120)
    routine: str = Field(default="", max_length=120)
    target_worker_id: str = Field(min_length=1, max_length=160)

    @field_validator("category", "routine", "target_worker_id")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def validate_assignment(self) -> PromaxWorkerAssignmentItem:
        if not self.category:
            raise ValueError("category e obrigatoria")
        if not self.target_worker_id:
            raise ValueError("target_worker_id e obrigatorio")
        if self.scope_type == "routine" and not self.routine:
            raise ValueError("routine e obrigatoria para regra por rotina")
        if self.scope_type == "category":
            self.routine = ""
        return self


class PromaxWorkerAssignmentsRequest(_StrictPayload):
    assignments: list[PromaxWorkerAssignmentItem] = Field(default_factory=list, max_length=300)


class PromaxWorkerHeartbeatRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    pid: int = Field(gt=0, le=2_147_483_647)
    version: str | None = Field(default=None, max_length=120)
    details: dict[str, Any] = Field(default_factory=dict)


class PromaxJobHeartbeatRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    pid: int = Field(gt=0, le=2_147_483_647)
    lease_token: str | None = Field(default=None, min_length=1, max_length=120)
    lease_seconds: int = Field(default=120, ge=15, le=3600)


class PromaxJobLogRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    lease_token: str | None = Field(default=None, min_length=1, max_length=120)
    level: str = Field(default="info", min_length=1, max_length=16)
    message: str = Field(min_length=1, max_length=8000)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"debug", "info", "warning", "error"}:
            raise ValueError("level must be debug, info, warning or error")
        return normalized


class PromaxJobFinishRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    pid: int = Field(gt=0, le=2_147_483_647)
    lease_token: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal[
        "success",
        "partial_success",
        "succeeded",
        "failed",
        "cancelled",
        "stopped",
    ]
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=8000)

    @model_validator(mode="after")
    def validate_finish(self) -> PromaxJobFinishRequest:
        if self.status == "failed" and not self.error:
            raise ValueError("error is required when status is failed")
        return self


class PromaxBoletoImportRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    lease_token: str | None = Field(default=None, min_length=1, max_length=120)
    filial: str = Field(min_length=1, max_length=16)
    filename: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(min_length=1)
    reference_date: date | None = None

    @field_validator("filial")
    @classmethod
    def validate_filial(cls, value: str) -> str:
        normalized = _normalize_promax_filial_code(value)
        if not normalized:
            raise ValueError("filial deve conter ao menos um digito")
        return normalized

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        name = FilePath(str(value or "").strip()).name
        if not name or name.lower().endswith(".pdf") is False:
            raise ValueError("filename deve ser um PDF")
        return name


def _validate_030206_filename_filial(filename: str, filial: str) -> None:
    match = re.fullmatch(r"03,02,06_([A-Za-z0-9_.-]+)\.pdf", filename)
    if not match:
        return
    unit = match.group(1)
    expected_filial = _PROMAX_030206_UNIT_FILIAL_DEFAULTS.get(unit)
    if expected_filial and expected_filial != filial:
        raise HTTPException(
            status_code=400,
            detail=(
                "Arquivo de boleto nao corresponde a filial informada: "
                f"{filename} pertence a filial {expected_filial}, mas foi enviado como filial {filial}."
            ),
        )


class PromaxEstoque020304ImportRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    lease_token: str | None = Field(default=None, min_length=1, max_length=120)
    filial: str = Field(min_length=1, max_length=16)
    filename: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(min_length=1)
    reference_date: date | None = None

    @field_validator("filial")
    @classmethod
    def validate_filial(cls, value: str) -> str:
        normalized = _normalize_promax_filial_code(value)
        if not normalized:
            raise ValueError("filial deve conter ao menos um digito")
        return normalized

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        name = FilePath(str(value or "").strip()).name
        if not name or name.lower().endswith(".csv") is False:
            raise ValueError("filename deve ser um CSV")
        return name


class PromaxCsvImportFile(_StrictPayload):
    filename: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(min_length=1)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        name = FilePath(str(value or "").strip()).name
        if not name or name.lower().endswith(".csv") is False:
            raise ValueError("filename deve ser um CSV")
        return name


class PromaxInadimplenciaImportRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    lease_token: str | None = Field(default=None, min_length=1, max_length=120)
    files: list[PromaxCsvImportFile] = Field(min_length=1, max_length=200)
    reference_date: date | None = None

    @model_validator(mode="after")
    def validate_files(self) -> PromaxInadimplenciaImportRequest:
        filenames = [item.filename for item in self.files]
        if len(filenames) != len(set(filenames)):
            raise ValueError("files contem nomes duplicados")
        return self


def _decode_csv_text(csv_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return csv_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return csv_bytes.decode("latin-1", errors="replace")


def _detect_csv_delimiter(text: str) -> str:
    sample = text[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";" if sample.count(";") >= sample.count(",") else ","


def _csv_header_key(value: Any) -> str:
    normalized = unicode_normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(char for char in ascii_text.casefold() if char.isalnum())


def _normalize_promax_filial_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if not digits:
        return ""
    return digits.lstrip("0") or "0"


def _detect_critica_filial(csv_bytes: bytes) -> str:
    text = _decode_csv_text(csv_bytes)
    delimiter = _detect_csv_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = list(reader.fieldnames or [])
    header_map = {_csv_header_key(header): header for header in headers}
    filial_field = header_map.get("filialorigem") or header_map.get("filial")
    if not filial_field:
        return ""
    for row in reader:
        raw_filial = row.get(filial_field, "")
        filial = _normalize_promax_filial_code(raw_filial)
        if filial:
            return filial
    return ""


class PromaxWorkerClientClaimRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)


class PromaxWorkerClientHeartbeatRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    hostname: str = Field(min_length=1, max_length=255)
    status: Literal["idle", "running"]
    job_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_running_job(self) -> PromaxWorkerClientHeartbeatRequest:
        if self.status == "running" and not self.job_id:
            raise ValueError("job_id is required when worker status is running")
        return self


class PromaxWorkerClientLogRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    stream: Literal["stdout", "stderr"]
    message: str = Field(min_length=1, max_length=8000)


class PromaxWorkerClientControlRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)


class PromaxWorkerClientFinishRequest(_StrictPayload):
    worker_id: str = Field(min_length=1, max_length=120)
    job_id: str = Field(min_length=1, max_length=120)
    status: Literal["succeeded", "failed", "cancelled"]
    exit_code: int | None = Field(default=None, ge=-2_147_483_648, le=2_147_483_647)
    error: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def validate_finish(self) -> PromaxWorkerClientFinishRequest:
        if self.status == "failed" and not self.error:
            raise ValueError("error is required when status is failed")
        return self


def _mapping_or_value(value: Any, *, key: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {"ok": True, **dict(value)}
    return {"ok": True, key: value}


def _item_response(value: Any, *, key: str) -> dict[str, Any]:
    return {"ok": True, key: value}


def create_admin_promax_router(
    *,
    service: Any,
    catalog: Callable[[], Any] | Mapping[str, Any],
    worker_token: str | None,
    boletos_pdf_import_services: Mapping[str, Any] | None = None,
    estoque_020304_import_services: Mapping[str, Any] | None = None,
    relatorio_031120_import_services: Mapping[str, Any] | None = None,
    relatorio_03114902_import_service: Any | None = None,
    inadimplencia_import_service: Any | None = None,
    comodatos_import_service: Any | None = None,
    dclientes_import_service: Any | None = None,
    dmateriais_import_service: Any | None = None,
    documentacao_pendente_import_service: Any | None = None,
    critica_operacao_import_services: Mapping[str, Any] | None = None,
    after_critica_operacao_import: Callable[[str], Mapping[str, Any] | None] | None = None,
    require_admin_panel_auth: Callable[..., dict[str, Any]],
    require_admin_panel_feature: Callable[[dict[str, Any] | None, str], None],
    record_security_event: Callable[..., None],
    record_admin_panel_action: Callable[..., None] | None = None,
) -> APIRouter:
    router = APIRouter()
    expected_worker_token = worker_token.strip() if isinstance(worker_token, str) else ""
    boleto_import_services = dict(boletos_pdf_import_services or {})
    estoque_import_services = dict(estoque_020304_import_services or {})
    relatorio_031120_import_services_map = dict(relatorio_031120_import_services or {})
    critica_import_services = dict(critica_operacao_import_services or {})

    def require_promax_context(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_token: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        context = require_admin_panel_auth(
            request=request,
            authorization=authorization,
            x_api_token=x_api_token,
            x_admin_token=x_admin_token,
        )
        if not isinstance(context, Mapping) or not bool(context.get("is_admin")):
            record_security_event(
                request,
                channel="api",
                event_type="admin_promax_rbac",
                decision="denied",
                reason="admin_required",
            )
            raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
        require_admin_panel_feature(context, "promax")
        return context

    def require_worker_auth(
        request: Request,
        x_promax_worker_token: str | None = Header(default=None, alias="x-promax-worker-token"),
    ) -> None:
        if not expected_worker_token:
            record_security_event(
                request,
                channel="api",
                event_type="promax_worker_auth",
                decision="denied",
                reason="worker_token_not_configured",
            )
            raise HTTPException(status_code=503, detail="Promax worker authentication is not configured.")

        provided_token = str(x_promax_worker_token or "")
        if not provided_token or not compare_digest(provided_token, expected_worker_token):
            record_security_event(
                request,
                channel="api",
                event_type="promax_worker_auth",
                decision="denied",
                reason="worker_token_missing" if not provided_token else "worker_token_invalid",
            )
            raise HTTPException(status_code=401, detail="Invalid Promax worker token.")

        record_security_event(
            request,
            channel="api",
            event_type="promax_worker_auth",
            decision="allowed",
            reason="worker_token",
        )

    def record_admin_event(request: Request, event_type: str, reason: str = "success") -> None:
        record_security_event(
            request,
            channel="api",
            event_type=event_type,
            decision="allowed",
            reason=reason,
        )

    def record_panel_action(
        request: Request,
        context: dict[str, Any] | None,
        *,
        action: str,
        target_type: str = "",
        target_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if record_admin_panel_action is None:
            return
        record_admin_panel_action(
            request=request,
            context=context,
            module="promax",
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata or {},
        )

    def resolve_catalog() -> Any:
        return catalog() if callable(catalog) else catalog

    def context_actor(context: Mapping[str, Any]) -> str:
        return str(
            context.get("user")
            or context.get("username")
            or context.get("subject")
            or context.get("mode")
            or "admin"
        ).strip()

    def resolve_job_lease_token(
        *,
        job_id: str,
        worker_id: str,
        provided_lease_token: str | None,
    ) -> str:
        if provided_lease_token:
            return provided_lease_token
        job = service.get_job(job_id)
        leased_by = job.get("leased_by") if isinstance(job, Mapping) else getattr(job, "leased_by", None)
        lease_token = job.get("lease_token") if isinstance(job, Mapping) else getattr(job, "lease_token", None)
        if (
            job is not None
            and str(leased_by or "") == worker_id
            and str(lease_token or "").strip()
        ):
            return str(lease_token)
        raise HTTPException(status_code=409, detail="Lease ativo do job nao encontrado para este worker.")

    def record_worker_heartbeat(
        *,
        worker_id: str,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        register_worker_heartbeat = getattr(service, "register_worker_heartbeat", None)
        if callable(register_worker_heartbeat):
            register_worker_heartbeat(worker_id=worker_id, metadata=dict(metadata))
            return {
                "worker_id": worker_id,
                "online": True,
                "metadata": dict(metadata),
            }
        heartbeat_worker = getattr(service, "heartbeat_worker", None)
        if callable(heartbeat_worker):
            return heartbeat_worker(worker_id=worker_id, metadata=dict(metadata))
        return {
            "worker_id": worker_id,
            "online": True,
            "metadata": dict(metadata),
        }

    def final_service_status(status: str) -> str:
        return {
            "success": "success",
            "partial_success": "partial_success",
            "succeeded": "success",
            "failed": "failed",
            "cancelled": "cancelled",
            "stopped": "cancelled",
        }[status]

    def enqueue_auto_retry_if_needed(completed_job: Any, *, worker_id: str) -> dict[str, Any] | None:
        status = str(_mapping_value(completed_job, "status", "") or "")
        if status not in {"failed", "partial_success"}:
            return None
        if _has_auto_retry_marker(completed_job):
            return None

        retry_payload, retry_units, retry_mode = _retry_payload_for_job(completed_job)
        if retry_mode != "failed_units" and not _is_recoverable_promax_failure(completed_job):
            return None
        if retry_mode == "failed_units" and not retry_units:
            return None

        original_job_id = str(_mapping_value(completed_job, "id", "") or "").strip()
        retry_payload["auto_retry_of_job_id"] = original_job_id
        retry_payload["auto_retry_attempt"] = 1
        job_type = str(_mapping_value(completed_job, "job_type", "") or "").strip()
        priority = int(_mapping_value(completed_job, "priority", 0) or 0)
        retry_job = service.enqueue_job(
            job_type=job_type,
            payload=retry_payload,
            priority=priority,
            created_by=f"auto_retry:{worker_id}",
        )
        append_log = getattr(service, "append_job_log", None)
        if callable(append_log) and original_job_id:
            append_log(
                job_id=original_job_id,
                level="warning",
                message=(
                    "Retry automatico enfileirado para unidades com falha: "
                    + (", ".join(retry_units) if retry_units else "job completo")
                ),
                data={
                    "retry_job_id": _mapping_value(retry_job, "id", ""),
                    "retry_mode": retry_mode,
                    "retry_units": retry_units,
                },
                worker_id=worker_id,
            )
        return {
            "job": retry_job,
            "retry_mode": retry_mode,
            "retry_units": retry_units,
        }

    def worker_control(worker_id: str, job_id: str | None = None) -> dict[str, Any]:
        queue = service.get_queue_state()
        cancel_jobs = service.list_jobs(statuses=["cancel_requested"], limit=500)
        stop_job_ids = [
            str(job.get("id") if isinstance(job, Mapping) else getattr(job, "id", ""))
            for job in cancel_jobs
            if str(
                job.get("leased_by")
                if isinstance(job, Mapping)
                else getattr(job, "leased_by", "")
            )
            == worker_id
            and str(job.get("id") if isinstance(job, Mapping) else getattr(job, "id", ""))
        ]
        queue_paused = queue.get("paused") if isinstance(queue, Mapping) else getattr(queue, "paused", False)
        return {
            "paused": bool(queue_paused),
            "stop_job_ids": stop_job_ids,
            "cancel_requested": bool(job_id and job_id in stop_job_ids),
        }

    @router.get("/api/admin/promax/catalog")
    def api_admin_promax_catalog(
        request: Request,
        _context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        resolved_catalog = resolve_catalog()
        record_admin_event(request, "admin_promax_catalog")
        return _item_response(resolved_catalog, key="catalog")

    @router.get("/api/admin/promax/worker-assignments")
    def api_admin_promax_worker_assignments(
        request: Request,
        _context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        list_assignments = getattr(service, "list_worker_assignments", None)
        if not callable(list_assignments):
            raise HTTPException(status_code=503, detail="Configuracao de workers nao disponivel.")
        assignments = list_assignments()
        record_admin_event(request, "admin_promax_worker_assignments_list")
        return _mapping_or_value(assignments, key="assignments")

    @router.put("/api/admin/promax/worker-assignments")
    def api_admin_promax_replace_worker_assignments(
        request: Request,
        payload: PromaxWorkerAssignmentsRequest,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        replace_assignments = getattr(service, "replace_worker_assignments", None)
        if not callable(replace_assignments):
            raise HTTPException(status_code=503, detail="Configuracao de workers nao disponivel.")
        assignments = replace_assignments(
            [item.model_dump(mode="json") for item in payload.assignments],
            updated_by=context_actor(context),
        )
        record_admin_event(
            request,
            "admin_promax_worker_assignments_replace",
            reason=f"assignments={len(payload.assignments)}",
        )
        record_panel_action(
            request,
            context,
            action="configurar_workers",
            metadata={"assignments": len(payload.assignments)},
        )
        return _mapping_or_value(assignments, key="assignments")

    @router.post("/api/admin/promax/jobs", status_code=202)
    def api_admin_promax_create_job(
        request: Request,
        payload: PromaxJobCreateRequest,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        _validate_catalog_selection(
            resolve_catalog(),
            category=payload.category,
            routines=payload.routines,
            units=payload.units,
        )
        job_payload = payload.model_dump(mode="json")
        job = service.enqueue_job(
            job_type=payload.category,
            payload=job_payload,
            created_by=context_actor(context),
        )
        record_admin_event(request, "admin_promax_job_create")
        record_panel_action(
            request,
            context,
            action="executar_agora",
            target_type="job",
            target_id=str(job.get("id") if isinstance(job, Mapping) else ""),
            metadata={"category": payload.category, "routines": payload.routines, "units": payload.units},
        )
        return _item_response(job, key="job")

    @router.post("/api/admin/promax/jobs/batch", status_code=202)
    def api_admin_promax_create_job_batch(
        request: Request,
        payload: PromaxJobBatchCreateRequest,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        resolved_catalog = resolve_catalog()
        for group in payload.groups:
            _validate_catalog_selection(
                resolved_catalog,
                category=group.category,
                routines=group.routines,
                units=payload.units,
            )

        common_payload = {
            "units": payload.units,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "send_dates": payload.send_dates,
            "publish": payload.publish,
        }
        jobs = service.enqueue_jobs(
            items=[
                {
                    "job_type": group.category,
                    "payload": {
                        "category": group.category,
                        "routines": group.routines,
                        **common_payload,
                    },
                }
                for group in payload.groups
            ],
            created_by=context_actor(context),
        )
        record_admin_event(
            request,
            "admin_promax_job_batch_create",
            reason=f"groups={','.join(group.category for group in payload.groups)}",
        )
        record_panel_action(
            request,
            context,
            action="executar_grupos",
            metadata={"groups": [group.category for group in payload.groups], "units": payload.units},
        )
        return _mapping_or_value(jobs, key="jobs")

    @router.post("/api/admin/promax/publications/reprocess", status_code=202)
    def api_admin_promax_reprocess_publications(
        request: Request,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        active_jobs = service.list_jobs(
            statuses=["pending", "running", "cancel_requested"],
            limit=500,
        )
        for active_job in active_jobs:
            active_job_type = str(
                active_job.get("job_type")
                if isinstance(active_job, Mapping)
                else getattr(active_job, "job_type", "")
            )
            if active_job_type == "reprocess_publication":
                record_admin_event(
                    request,
                    "admin_promax_publication_reprocess",
                    reason="already_queued",
                )
                return _item_response(active_job, key="job")

        job = service.enqueue_job(
            job_type="reprocess_publication",
            payload={"operation": "reprocess_publication"},
            priority=50,
            created_by=context_actor(context),
        )
        record_admin_event(request, "admin_promax_publication_reprocess")
        record_panel_action(request, context, action="reprocessar_publicacoes", target_type="job", target_id=str(job.get("id") if isinstance(job, Mapping) else ""))
        return _item_response(job, key="job")

    @router.get("/api/admin/promax/jobs")
    def api_admin_promax_list_jobs(
        request: Request,
        status: str | None = Query(default=None, min_length=1, max_length=32),
        category: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$"),
        created_from: date | None = Query(default=None),
        created_to: date | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        created_from_at, created_before_at = _promax_job_created_bounds(
            created_from,
            created_to,
        )
        result = service.list_jobs(
            statuses=[status] if status else None,
            created_from=created_from_at,
            created_before=created_before_at,
            limit=500 if category else limit,
        )
        if category:
            result = [
                job
                for job in result
                if str(
                    (
                        job.get("job_type")
                        or (job.get("payload") or {}).get("category")
                    )
                    if isinstance(job, Mapping)
                    else getattr(job, "job_type", "")
                )
                == category
            ][:limit]
        record_admin_event(request, "admin_promax_jobs_list")
        return _mapping_or_value(result, key="jobs")

    @router.get("/api/admin/promax/jobs/{job_id}")
    def api_admin_promax_get_job(
        request: Request,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        job = service.get_job(job_id)
        record_admin_event(request, "admin_promax_job_detail", reason=f"job_id={job_id}")
        return _item_response(job, key="job")

    @router.post("/api/admin/promax/jobs/{job_id}/retry", status_code=202)
    def api_admin_promax_retry_job(
        request: Request,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        original_job = service.get_job(job_id)
        if not original_job:
            raise HTTPException(status_code=404, detail="Job Promax nao encontrado.")

        original_status = str(
            original_job.get("status")
            if isinstance(original_job, Mapping)
            else getattr(original_job, "status", "")
        )
        if original_status not in {"failed", "partial_success", "cancelled"}:
            raise HTTPException(status_code=409, detail="Apenas jobs com falha, parcial ou cancelados podem ser reenfileirados.")

        original_job_type = str(
            original_job.get("job_type")
            if isinstance(original_job, Mapping)
            else getattr(original_job, "job_type", "")
        ).strip()
        original_priority = int(
            original_job.get("priority")
            if isinstance(original_job, Mapping)
            else getattr(original_job, "priority", 100)
            or 100
        )
        retry_payload, retry_units, retry_mode = _retry_payload_for_job(original_job)
        job = service.enqueue_job(
            job_type=original_job_type,
            payload=retry_payload,
            priority=original_priority,
            created_by=context_actor(context),
        )
        record_admin_event(request, "admin_promax_job_retry", reason=f"job_id={job_id}")
        record_panel_action(
            request,
            context,
            action="retry_job",
            target_type="job",
            target_id=job_id,
            metadata={"retry_mode": retry_mode, "retry_units": retry_units},
        )
        return {
            "ok": True,
            "job": job,
            "retry_mode": retry_mode,
            "retry_units": retry_units,
        }

    @router.get("/api/admin/promax/jobs/{job_id}/logs")
    def api_admin_promax_job_logs(
        request: Request,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        limit: int = Query(default=200, ge=1, le=1000),
        after_id: int | None = Query(default=None, ge=0),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        logs = service.list_job_logs(
            job_id,
            limit=limit,
            after_id=after_id or 0,
        )
        result = {"logs": logs}
        record_admin_event(request, "admin_promax_job_logs", reason=f"job_id={job_id}")
        return _mapping_or_value(result, key="logs")

    @router.post("/api/admin/promax/jobs/{job_id}/cancel")
    def api_admin_promax_cancel_job(
        request: Request,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        result = service.cancel_job(
            job_id,
            requested_by=context_actor(context),
            reason="Pending job cancelled by admin.",
        )
        record_admin_event(request, "admin_promax_job_cancel", reason=f"job_id={job_id}")
        record_panel_action(request, context, action="cancelar_job", target_type="job", target_id=job_id)
        return _mapping_or_value(result, key="job")

    @router.post("/api/admin/promax/jobs/{job_id}/stop")
    def api_admin_promax_stop_job(
        request: Request,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        result = service.cancel_job(
            job_id,
            requested_by=context_actor(context),
            reason="Running job stop requested by admin.",
        )
        record_admin_event(request, "admin_promax_job_stop", reason=f"job_id={job_id}")
        record_panel_action(request, context, action="parar_job", target_type="job", target_id=job_id)
        return _mapping_or_value(result, key="job")

    @router.post("/api/admin/promax/queue/pause")
    def api_admin_promax_pause_queue(
        request: Request,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        result = service.pause_queue(
            paused_by=context_actor(context),
            reason="Paused by admin.",
        )
        record_admin_event(request, "admin_promax_queue_pause")
        record_panel_action(request, context, action="pausar_fila")
        return _mapping_or_value(result, key="queue")

    @router.post("/api/admin/promax/queue/resume")
    def api_admin_promax_resume_queue(
        request: Request,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        result = service.resume_queue(resumed_by=context_actor(context))
        record_admin_event(request, "admin_promax_queue_resume")
        record_panel_action(request, context, action="retomar_fila")
        return _mapping_or_value(result, key="queue")

    @router.delete("/api/admin/promax/queue/pending")
    def api_admin_promax_clear_pending(
        request: Request,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        result = service.clear_pending_jobs(
            requested_by=context_actor(context),
            reason="Pending queue cleared by admin.",
        )
        record_admin_event(request, "admin_promax_queue_clear_pending")
        record_panel_action(request, context, action="limpar_fila_pendente")
        return _mapping_or_value(result, key="queue")

    @router.get("/api/admin/promax/worker/status")
    def api_admin_promax_worker_status(
        request: Request,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        result = {
            "queue": service.get_queue_state(),
            "active_jobs": service.list_jobs(
                statuses=["running", "cancel_requested"],
                limit=100,
            ),
        }
        list_worker_heartbeats = getattr(service, "list_worker_heartbeats", None)
        if callable(list_worker_heartbeats):
            result["workers"] = list_worker_heartbeats()
        record_admin_event(request, "admin_promax_worker_status")
        return _mapping_or_value(result, key="worker")

    @router.post("/api/admin/promax/schedules", status_code=201)
    def api_admin_promax_create_schedule(
        request: Request,
        payload: PromaxScheduleCreateRequest,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        _validate_catalog_selection(
            resolve_catalog(),
            category=payload.category,
            routines=payload.routines,
            units=payload.units,
        )
        schedule_payload = payload.model_dump(
            mode="json",
            exclude={
                "name",
                "schedule_type",
                "time_of_day",
                "timezone",
                "weekday",
                "day_of_month",
                "trigger_after_schedule_id",
                "enabled",
            },
        )
        try:
            schedule = service.create_schedule(
                name=payload.name,
                job_type=payload.category,
                payload=schedule_payload,
                schedule_type=payload.schedule_type,
                time_of_day=payload.time_of_day,
                timezone_name=payload.timezone,
                weekday=payload.weekday,
                day_of_month=payload.day_of_month,
                trigger_after_schedule_id=payload.trigger_after_schedule_id,
                enabled=payload.enabled,
                created_by=context_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record_admin_event(request, "admin_promax_schedule_create")
        record_panel_action(
            request,
            context,
            action="criar_agenda",
            target_type="agenda",
            target_id=str(schedule.get("id") if isinstance(schedule, Mapping) else ""),
            metadata={"name": payload.name, "category": payload.category, "routines": payload.routines, "units": payload.units},
        )
        return _item_response(schedule, key="schedule")

    @router.post("/api/admin/promax/schedule-chains", status_code=201)
    def api_admin_promax_create_schedule_chain(
        request: Request,
        payload: PromaxScheduleChainCreateRequest,
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        resolved_catalog = resolve_catalog()
        for group in payload.groups:
            _validate_catalog_selection(
                resolved_catalog,
                category=group.category,
                routines=group.routines,
                units=payload.units,
            )

        multiple_groups = len(payload.groups) > 1
        common_payload = {
            "units": payload.units,
            "start_date": payload.start_date.isoformat(),
            "end_date": payload.end_date.isoformat(),
            "send_dates": payload.send_dates,
            "publish": payload.publish,
        }
        chain_items = [
            {
                "name": (
                    f"{payload.name[: max(1, 157 - len(group.category))]} - {group.category}"
                    if multiple_groups
                    else payload.name
                ),
                "job_type": group.category,
                "payload": {
                    "category": group.category,
                    "routines": group.routines,
                    **common_payload,
                },
            }
            for group in payload.groups
        ]
        try:
            schedules = service.create_schedule_chain(
                items=chain_items,
                schedule_type=payload.schedule_type,
                time_of_day=payload.time_of_day,
                timezone_name=payload.timezone,
                weekday=payload.weekday,
                day_of_month=payload.day_of_month,
                trigger_after_schedule_id=payload.trigger_after_schedule_id,
                enabled=payload.enabled,
                created_by=context_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record_admin_event(
            request,
            "admin_promax_schedule_chain_create",
            reason=f"groups={','.join(group.category for group in payload.groups)}",
        )
        record_panel_action(
            request,
            context,
            action="criar_agenda_em_cadeia",
            metadata={"name": payload.name, "groups": [group.category for group in payload.groups], "units": payload.units},
        )
        return _mapping_or_value(schedules, key="schedules")

    @router.get("/api/admin/promax/schedules")
    def api_admin_promax_list_schedules(
        request: Request,
        enabled: bool | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        result = service.list_schedules(include_disabled=enabled is not True)
        if enabled is not None:
            result = [
                schedule
                for schedule in result
                if isinstance(schedule, Mapping) and bool(schedule.get("enabled")) is enabled
            ]
        result = result[:limit]
        record_admin_event(request, "admin_promax_schedules_list")
        return _mapping_or_value(result, key="schedules")

    @router.get("/api/admin/promax/schedules/{schedule_id}")
    def api_admin_promax_get_schedule(
        request: Request,
        schedule_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        schedule = service.get_schedule(schedule_id)
        record_admin_event(request, "admin_promax_schedule_detail", reason=f"schedule_id={schedule_id}")
        return _item_response(schedule, key="schedule")

    @router.post("/api/admin/promax/schedules/{schedule_id}/run-now", status_code=202)
    def api_admin_promax_run_schedule_now(
        request: Request,
        schedule_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        try:
            job = service.enqueue_schedule_now(
                schedule_id,
                requested_by=context_actor(context),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if job is None:
            raise HTTPException(status_code=404, detail="Agenda Promax nao encontrada.")
        record_admin_event(request, "admin_promax_schedule_run_now", reason=f"schedule_id={schedule_id}")
        record_panel_action(request, context, action="executar_agenda", target_type="agenda", target_id=schedule_id)
        return _item_response(job, key="job")

    @router.patch("/api/admin/promax/schedules/{schedule_id}")
    def api_admin_promax_update_schedule(
        request: Request,
        payload: PromaxScheduleUpdateRequest,
        schedule_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        if payload.category is not None:
            _validate_catalog_selection(
                resolve_catalog(),
                category=payload.category,
                routines=payload.routines,
                units=payload.units,
            )
        selection_fields = {
            "category",
            "routines",
            "units",
            "start_date",
            "end_date",
            "send_dates",
            "publish",
        }
        selection_changed = bool(selection_fields.intersection(payload.model_fields_set))
        schedule_payload = (
            payload.model_dump(mode="json", include=selection_fields)
            if selection_changed
            else None
        )
        update_values = payload.model_dump(exclude_unset=True)
        schedule_kwargs: dict[str, Any] = {}
        for payload_field, service_field in (
            ("name", "name"),
            ("category", "job_type"),
            ("schedule_type", "schedule_type"),
            ("time_of_day", "time_of_day"),
            ("timezone", "timezone_name"),
            ("weekday", "weekday"),
            ("day_of_month", "day_of_month"),
            ("trigger_after_schedule_id", "trigger_after_schedule_id"),
            ("enabled", "enabled"),
        ):
            if payload_field in update_values:
                schedule_kwargs[service_field] = update_values[payload_field]
        if selection_changed:
            schedule_kwargs["payload"] = schedule_payload
        try:
            schedule = service.update_schedule(schedule_id, **schedule_kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record_admin_event(request, "admin_promax_schedule_update", reason=f"schedule_id={schedule_id}")
        record_panel_action(
            request,
            context,
            action="editar_agenda",
            target_type="agenda",
            target_id=schedule_id,
            metadata={"fields": sorted(update_values.keys())},
        )
        return _item_response(schedule, key="schedule")

    @router.delete("/api/admin/promax/schedules/{schedule_id}")
    def api_admin_promax_delete_schedule(
        request: Request,
        schedule_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        context: dict[str, Any] = Depends(require_promax_context),
    ) -> dict[str, Any]:
        try:
            result = service.delete_schedule(schedule_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        record_admin_event(request, "admin_promax_schedule_delete", reason=f"schedule_id={schedule_id}")
        record_panel_action(request, context, action="apagar_agenda", target_type="agenda", target_id=schedule_id)
        return _mapping_or_value(result, key="schedule")

    @router.post("/api/internal/promax/next-job/claim")
    def api_internal_promax_claim_job(
        payload: PromaxWorkerClaimRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        job = service.claim_next_job(
            worker_id=payload.worker_id,
            lease_seconds=payload.lease_seconds,
        )
        return _item_response(job, key="job")

    @router.post("/api/internal/promax/heartbeat")
    def api_internal_promax_worker_heartbeat(
        payload: PromaxWorkerHeartbeatRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        result = record_worker_heartbeat(
            worker_id=payload.worker_id,
            metadata={
                "pid": payload.pid,
                "version": payload.version,
                **payload.details,
            },
        )
        return _mapping_or_value(result, key="worker")

    @router.post("/api/internal/promax/jobs/{job_id}/heartbeat")
    def api_internal_promax_job_heartbeat(
        payload: PromaxJobHeartbeatRequest,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        lease_token = resolve_job_lease_token(
            job_id=job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        result = service.heartbeat_job(
            job_id=job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            lease_seconds=payload.lease_seconds,
            worker_metadata={"pid": payload.pid},
        )
        return _mapping_or_value(result, key="job")

    @router.post("/api/internal/promax/jobs/{job_id}/log")
    def api_internal_promax_job_log(
        payload: PromaxJobLogRequest,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        lease_token = resolve_job_lease_token(
            job_id=job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        result = service.append_job_log(
            job_id=job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level=payload.level,
            message=payload.message,
            data=payload.data,
        )
        return _mapping_or_value(result, key="log")

    @router.post("/api/internal/promax/jobs/{job_id}/finish")
    def api_internal_promax_finish_job(
        payload: PromaxJobFinishRequest,
        job_id: str = Path(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$"),
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        lease_token = resolve_job_lease_token(
            job_id=job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        result = service.finish_job(
            job_id=job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            status=final_service_status(payload.status),
            result={"pid": payload.pid, **(payload.result or {})},
            error=payload.error or "",
        )
        auto_retry = enqueue_auto_retry_if_needed(result, worker_id=payload.worker_id)
        response = _mapping_or_value(result, key="job")
        if auto_retry:
            response["auto_retry"] = auto_retry
        return response

    @router.get("/api/internal/promax/control")
    def api_internal_promax_control(
        worker_id: str = Query(min_length=1, max_length=120),
        job_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=120,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$",
        ),
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        result = worker_control(worker_id, job_id)
        return _mapping_or_value(result, key="control")

    @router.post("/api/internal/promax/boletos/import")
    def api_internal_promax_import_boleto_pdf(
        payload: PromaxBoletoImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        _validate_030206_filename_filial(payload.filename, payload.filial)
        import_service = boleto_import_services.get(payload.filial)
        if import_service is None:
            raise HTTPException(
                status_code=400,
                detail=f"Importador de boletos nao configurado para a filial {payload.filial}.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 030206 iniciada para filial {payload.filial}: {payload.filename}",
            data={"event": "promax_030206_auto_import_start", "filial": payload.filial, "filename": payload.filename},
        )
        try:
            pdf_bytes = base64.b64decode(payload.file_base64.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail="Arquivo PDF em base64 invalido.") from exc
        if not pdf_bytes.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail="Arquivo enviado nao parece ser um PDF valido.")

        temp_path = ""
        with _PROMAX_BOLETO_IMPORT_LOCK:
            try:
                with tempfile.NamedTemporaryFile(prefix="promax_030206_", suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_bytes)
                    temp_path = tmp.name
                result = import_service.import_source(FilePath(temp_path), reference_date=payload.reference_date)
            finally:
                if temp_path:
                    try:
                        FilePath(temp_path).unlink(missing_ok=True)
                    except OSError:
                        pass
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 030206 concluida para filial "
                f"{payload.filial}: {result.get('imported', 0)} pagina(s), "
                f"{result.get('matched', 0)} boleto(s) vinculados."
            ),
            data={
                "event": "promax_030206_auto_import_success",
                "filial": payload.filial,
                "filename": payload.filename,
                "result": result,
            },
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/estoque/import")
    def api_internal_promax_import_estoque_020304_csv(
        payload: PromaxEstoque020304ImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        import_service = estoque_import_services.get(payload.filial)
        if import_service is None:
            raise HTTPException(
                status_code=400,
                detail=f"Importador de estoque 020304 nao configurado para a filial {payload.filial}.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 020304_BOT iniciada para filial {payload.filial}: {payload.filename}",
            data={"event": "promax_020304_auto_import_start", "filial": payload.filial, "filename": payload.filename},
        )
        try:
            csv_bytes = base64.b64decode(payload.file_base64.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
        if not csv_bytes.strip():
            raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {payload.filename}.")

        with tempfile.TemporaryDirectory(prefix="promax_020304_") as temp_dir:
            file_path = FilePath(temp_dir) / payload.filename
            file_path.write_bytes(csv_bytes)
            result = import_service.import_source(file_path, reference_date=payload.reference_date)

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 020304_BOT concluida para filial "
                f"{payload.filial}: {result.get('rows', 0)} produto(s), "
                f"PDF gerado com {result.get('pdf_bytes', 0)} bytes."
            ),
            data={
                "event": "promax_020304_auto_import_success",
                "filial": payload.filial,
                "filename": payload.filename,
                "result": result,
            },
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/031120/import")
    def api_internal_promax_import_031120_csv(
        payload: PromaxEstoque020304ImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        import_service = relatorio_031120_import_services_map.get(payload.filial)
        if import_service is None:
            raise HTTPException(
                status_code=400,
                detail=f"Importador de 031120 nao configurado para a filial {payload.filial}.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 031120_BOT iniciada para filial {payload.filial}: {payload.filename}",
            data={"event": "promax_031120_auto_import_start", "filial": payload.filial, "filename": payload.filename},
        )
        try:
            csv_bytes = base64.b64decode(payload.file_base64.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
        if not csv_bytes.strip():
            raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {payload.filename}.")

        with tempfile.TemporaryDirectory(prefix="promax_031120_") as temp_dir:
            file_path = FilePath(temp_dir) / payload.filename
            file_path.write_bytes(csv_bytes)
            result = import_service.import_source(file_path, reference_date=payload.reference_date)

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 031120_BOT concluida para filial "
                f"{payload.filial}: {result.get('rows', 0)} linha(s)."
            ),
            data={
                "event": "promax_031120_auto_import_success",
                "filial": payload.filial,
                "filename": payload.filename,
                "result": result,
            },
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/03114902/import")
    def api_internal_promax_import_03114902_csv(
        payload: PromaxEstoque020304ImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if relatorio_03114902_import_service is None:
            raise HTTPException(
                status_code=400,
                detail="Importador de 03114902 nao configurado.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 03114902_BOT iniciada: {payload.filename}",
            data={"event": "promax_03114902_auto_import_start", "filename": payload.filename},
        )
        try:
            csv_bytes = base64.b64decode(payload.file_base64.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
        if not csv_bytes.strip():
            raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {payload.filename}.")

        with tempfile.TemporaryDirectory(prefix="promax_03114902_") as temp_dir:
            file_path = FilePath(temp_dir) / payload.filename
            file_path.write_bytes(csv_bytes)
            result = relatorio_03114902_import_service.import_source(file_path, reference_date=payload.reference_date)

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 03114902_BOT concluida: "
                f"{result.get('rows', 0)} linha(s)."
            ),
            data={
                "event": "promax_03114902_auto_import_success",
                "filename": payload.filename,
                "result": result,
            },
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/inadimplencia/import")
    def api_internal_promax_import_inadimplencia_csvs(
        payload: PromaxInadimplenciaImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if inadimplencia_import_service is None:
            raise HTTPException(
                status_code=400,
                detail="Importador de inadimplencia nao configurado.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 120601_BOT iniciada: "
                f"{len(payload.files)} arquivo(s) CSV."
            ),
            data={
                "event": "promax_120601_auto_import_start",
                "file_count": len(payload.files),
                "files": [item.filename for item in payload.files],
            },
        )
        with tempfile.TemporaryDirectory(prefix="promax_120601_") as temp_dir:
            temp_root = FilePath(temp_dir)
            for item in payload.files:
                try:
                    csv_bytes = base64.b64decode(item.file_base64.encode("ascii"), validate=True)
                except (UnicodeEncodeError, binascii.Error) as exc:
                    raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
                if not csv_bytes.strip():
                    raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {item.filename}.")
                (temp_root / item.filename).write_bytes(csv_bytes)

            result = inadimplencia_import_service.import_source(
                temp_root,
                reference_date=payload.reference_date,
            )

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 120601_BOT concluida: "
                f"{result.get('file_count', len(payload.files))} arquivo(s), "
                f"{result.get('rows', 0)} linha(s)."
            ),
            data={
                "event": "promax_120601_auto_import_success",
                "result": result,
            },
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/comodatos/import")
    def api_internal_promax_import_comodatos_csvs(
        payload: PromaxInadimplenciaImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if comodatos_import_service is None:
            raise HTTPException(
                status_code=400,
                detail="Importador de comodatos nao configurado.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 020220_BOT iniciada: {len(payload.files)} arquivo(s) CSV.",
            data={
                "event": "promax_020220_auto_import_start",
                "file_count": len(payload.files),
                "files": [item.filename for item in payload.files],
            },
        )
        with tempfile.TemporaryDirectory(prefix="promax_020220_") as temp_dir:
            temp_root = FilePath(temp_dir)
            for item in payload.files:
                try:
                    csv_bytes = base64.b64decode(item.file_base64.encode("ascii"), validate=True)
                except (UnicodeEncodeError, binascii.Error) as exc:
                    raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
                if not csv_bytes.strip():
                    raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {item.filename}.")
                (temp_root / item.filename).write_bytes(csv_bytes)

            result = comodatos_import_service.import_source(
                temp_root,
                reference_date=payload.reference_date,
            )

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 020220_BOT concluida: "
                f"{result.get('file_count', len(payload.files))} arquivo(s), "
                f"{result.get('rows', 0)} linha(s)."
            ),
            data={"event": "promax_020220_auto_import_success", "result": result},
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/dclientes/import")
    def api_internal_promax_import_dclientes_csv(
        payload: PromaxInadimplenciaImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if dclientes_import_service is None:
            raise HTTPException(
                status_code=400,
                detail="Importador de dClientes nao configurado.",
            )
        if len(payload.files) != 1:
            raise HTTPException(status_code=400, detail="dClientes deve receber exatamente um CSV.")
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        item = payload.files[0]
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 0105070402_BOT iniciada: {item.filename}.",
            data={"event": "promax_0105070402_auto_import_start", "filename": item.filename},
        )
        try:
            csv_bytes = base64.b64decode(item.file_base64.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
        if not csv_bytes.strip():
            raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {item.filename}.")

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="promax_0105070402_", suffix=".csv", delete=False) as tmp:
                tmp.write(csv_bytes)
                temp_path = tmp.name
            result = dclientes_import_service.import_csv(FilePath(temp_path), reference_date=payload.reference_date)
        finally:
            if temp_path:
                try:
                    FilePath(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 0105070402_BOT concluida: "
                f"{result.get('rows', 0)} linha(s)."
            ),
            data={"event": "promax_0105070402_auto_import_success", "result": result},
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/dmateriais/import")
    def api_internal_promax_import_dmateriais_csv(
        payload: PromaxInadimplenciaImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if dmateriais_import_service is None:
            raise HTTPException(
                status_code=400,
                detail="Importador de dMateriais nao configurado.",
            )
        if len(payload.files) != 1:
            raise HTTPException(status_code=400, detail="dMateriais deve receber exatamente um CSV.")
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        item = payload.files[0]
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 0112_BOT iniciada: {item.filename}.",
            data={"event": "promax_0112_auto_import_start", "filename": item.filename},
        )
        try:
            csv_bytes = base64.b64decode(item.file_base64.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
        if not csv_bytes.strip():
            raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {item.filename}.")

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="promax_0112_", suffix=".csv", delete=False) as tmp:
                tmp.write(csv_bytes)
                temp_path = tmp.name
            result = dmateriais_import_service.import_source(FilePath(temp_path), reference_date=payload.reference_date)
        finally:
            if temp_path:
                try:
                    FilePath(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 0112_BOT concluida: "
                f"{result.get('rows', 0)} linha(s)."
            ),
            data={"event": "promax_0112_auto_import_success", "result": result},
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/documentacao/import")
    def api_internal_promax_import_documentacao_csvs(
        payload: PromaxInadimplenciaImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if documentacao_pendente_import_service is None:
            raise HTTPException(
                status_code=400,
                detail="Importador de documentacao pendente nao configurado.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 031702_BOT iniciada: {len(payload.files)} arquivo(s) CSV.",
            data={
                "event": "promax_031702_auto_import_start",
                "file_count": len(payload.files),
                "files": [item.filename for item in payload.files],
            },
        )
        with tempfile.TemporaryDirectory(prefix="promax_031702_") as temp_dir:
            temp_root = FilePath(temp_dir)
            for item in payload.files:
                try:
                    csv_bytes = base64.b64decode(item.file_base64.encode("ascii"), validate=True)
                except (UnicodeEncodeError, binascii.Error) as exc:
                    raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
                if not csv_bytes.strip():
                    raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {item.filename}.")
                (temp_root / item.filename).write_bytes(csv_bytes)

            result = documentacao_pendente_import_service.import_source(
                temp_root,
                reference_date=payload.reference_date,
            )

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 031702_BOT concluida: "
                f"{result.get('file_count', len(payload.files))} arquivo(s), "
                f"{result.get('rows', 0)} linha(s)."
            ),
            data={"event": "promax_031702_auto_import_success", "result": result},
        )
        return {"ok": True, "result": result}

    @router.post("/api/internal/promax/critica/import")
    def api_internal_promax_import_critica_csvs(
        payload: PromaxInadimplenciaImportRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if not critica_import_services:
            raise HTTPException(
                status_code=400,
                detail="Importadores de critica por operacao nao configurados.",
            )
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=payload.lease_token,
        )
        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=f"Importacao automatica 030111_BOT iniciada: {len(payload.files)} arquivo(s) CSV.",
            data={
                "event": "promax_030111_auto_import_start",
                "file_count": len(payload.files),
                "files": [item.filename for item in payload.files],
            },
        )

        decoded_items: list[tuple[PromaxCsvImportFile, bytes, str, Any]] = []
        for item in payload.files:
            try:
                csv_bytes = base64.b64decode(item.file_base64.encode("ascii"), validate=True)
            except (UnicodeEncodeError, binascii.Error) as exc:
                raise HTTPException(status_code=400, detail="Arquivo CSV em base64 invalido.") from exc
            if not csv_bytes.strip():
                raise HTTPException(status_code=400, detail=f"Arquivo CSV vazio: {item.filename}.")
            filial = _detect_critica_filial(csv_bytes)
            if not filial:
                raise HTTPException(
                    status_code=400,
                    detail=f"Nao consegui identificar a Filial Origem no CSV da critica: {item.filename}.",
                )
            import_service = critica_import_services.get(filial)
            if import_service is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Importador de critica nao configurado para a filial {filial}.",
                )
            decoded_items.append((item, csv_bytes, filial, import_service))

        imports: list[dict[str, Any]] = []
        rows_total = 0
        with tempfile.TemporaryDirectory(prefix="promax_030111_") as temp_dir:
            temp_root = FilePath(temp_dir)
            for item, csv_bytes, filial, import_service in decoded_items:
                file_path = temp_root / item.filename
                file_path.write_bytes(csv_bytes)
                result = import_service.import_source(
                    file_path,
                    reference_date=payload.reference_date,
                )
                try:
                    rows_total += int(result.get("rows") or 0)
                except (TypeError, ValueError):
                    pass
                imports.append(
                    {
                        "filename": item.filename,
                        "filial": filial,
                        "dataset_name": result.get("dataset_name"),
                        "rows": result.get("rows"),
                        "batch_id": result.get("batch_id"),
                        "result": result,
                    }
                )

        post_actions: dict[str, Any] = {}
        if after_critica_operacao_import is not None:
            try:
                callback_result = after_critica_operacao_import("030111_BOT")
                if isinstance(callback_result, Mapping):
                    post_actions.update(callback_result)
            except Exception as exc:
                post_actions["post_import_warning"] = str(exc)
                service.append_job_log(
                    job_id=payload.job_id,
                    worker_id=payload.worker_id,
                    lease_token=lease_token,
                    level="warning",
                    message=f"Critica 030111_BOT importada, mas o pos-processamento falhou: {exc}",
                    data={"event": "promax_030111_auto_import_post_action_failed"},
                )

        result_payload: dict[str, Any] = {
            "dataset_name": "critica_operacao",
            "file_count": len(imports),
            "rows": rows_total,
            "imports": imports,
        }
        if post_actions:
            result_payload["post_actions"] = post_actions

        service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="info",
            message=(
                "Importacao automatica 030111_BOT concluida: "
                f"{len(imports)} arquivo(s), {rows_total} linha(s)."
            ),
            data={"event": "promax_030111_auto_import_success", "result": result_payload},
        )
        return {"ok": True, "result": result_payload}

    @router.post("/api/internal/promax/worker/claim")
    def api_internal_promax_worker_client_claim(
        payload: PromaxWorkerClientClaimRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        job = service.claim_next_job(
            worker_id=payload.worker_id,
            lease_seconds=120,
        )
        return _item_response(job, key="job")

    @router.post("/api/internal/promax/worker/heartbeat")
    def api_internal_promax_worker_client_heartbeat(
        payload: PromaxWorkerClientHeartbeatRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        if payload.job_id:
            lease_token = resolve_job_lease_token(
                job_id=payload.job_id,
                worker_id=payload.worker_id,
                provided_lease_token=None,
            )
            result = service.heartbeat_job(
                job_id=payload.job_id,
                worker_id=payload.worker_id,
                lease_token=lease_token,
                lease_seconds=120,
                worker_metadata={"hostname": payload.hostname, "status": payload.status},
            )
        else:
            result = record_worker_heartbeat(
                worker_id=payload.worker_id,
                metadata={"hostname": payload.hostname, "status": payload.status},
            )
        return _mapping_or_value(result, key="worker")

    @router.post("/api/internal/promax/worker/log")
    def api_internal_promax_worker_client_log(
        payload: PromaxWorkerClientLogRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=None,
        )
        result = service.append_job_log(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            level="error" if payload.stream == "stderr" else "info",
            message=payload.message,
            data={"stream": payload.stream},
        )
        return _mapping_or_value(result, key="log")

    @router.post("/api/internal/promax/worker/control")
    def api_internal_promax_worker_client_control(
        payload: PromaxWorkerClientControlRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        return _mapping_or_value(
            worker_control(payload.worker_id, payload.job_id),
            key="control",
        )

    @router.post("/api/internal/promax/worker/finish")
    def api_internal_promax_worker_client_finish(
        payload: PromaxWorkerClientFinishRequest,
        _worker_auth: None = Depends(require_worker_auth),
    ) -> dict[str, Any]:
        lease_token = resolve_job_lease_token(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            provided_lease_token=None,
        )
        result = service.finish_job(
            job_id=payload.job_id,
            worker_id=payload.worker_id,
            lease_token=lease_token,
            status=final_service_status(payload.status),
            result={"exit_code": payload.exit_code},
            error=payload.error,
        )
        auto_retry = enqueue_auto_retry_if_needed(result, worker_id=payload.worker_id)
        response = _mapping_or_value(result, key="job")
        if auto_retry:
            response["auto_retry"] = auto_retry
        return response

    return router
