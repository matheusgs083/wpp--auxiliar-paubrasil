from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any


logger = logging.getLogger(__name__)
_CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class PromaxCatalogService:
    def __init__(
        self,
        *,
        jobs_service: Any,
        fallback_catalog: Mapping[str, Any],
    ) -> None:
        self.jobs_service = jobs_service
        self.fallback_catalog = normalize_catalog(fallback_catalog)

    def get_catalog(self) -> dict[str, Any]:
        try:
            workers = self.jobs_service.list_worker_heartbeats(
                online_within_seconds=90,
                limit=20,
            )
        except Exception as exc:
            logger.warning("Falha ao consultar catalogo dos workers Promax: %s", exc)
            return self._fallback()

        for worker in workers:
            if not isinstance(worker, Mapping) or not bool(worker.get("online")):
                continue
            metadata = worker.get("metadata")
            raw_catalog = metadata.get("catalog") if isinstance(metadata, Mapping) else None
            try:
                catalog = normalize_catalog(raw_catalog)
            except ValueError as exc:
                logger.warning(
                    "Worker Promax %s enviou catalogo invalido: %s",
                    worker.get("worker_id"),
                    exc,
                )
                continue
            if not catalog["categories"]:
                continue
            catalog["source"] = "worker"
            catalog["worker_id"] = str(worker.get("worker_id") or "")
            warnings = raw_catalog.get("warnings") if isinstance(raw_catalog, Mapping) else None
            if isinstance(warnings, list):
                catalog["warnings"] = [str(item)[:500] for item in warnings[:50]]
            return catalog
        return self._fallback()

    def _fallback(self) -> dict[str, Any]:
        return {
            **self.fallback_catalog,
            "source": "fallback",
            "worker_id": "",
        }


def normalize_catalog(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("catalogo deve ser um objeto")
    raw_categories = value.get("categories", value)
    if not isinstance(raw_categories, Mapping):
        raise ValueError("categories deve ser um objeto")

    categories: dict[str, dict[str, Any]] = {}
    for raw_key, raw_category in raw_categories.items():
        key = str(raw_key or "").strip().lower()
        if not _CATEGORY_PATTERN.fullmatch(key):
            raise ValueError(f"categoria invalida: {raw_key!r}")
        if not isinstance(raw_category, Mapping):
            raise ValueError(f"configuracao invalida para categoria {key}")
        raw_routines = raw_category.get("routines")
        if not isinstance(raw_routines, (list, tuple)) or not raw_routines:
            raise ValueError(f"categoria {key} sem rotinas")

        routines: list[dict[str, str]] = []
        seen_routines: set[str] = set()
        for raw_routine in raw_routines:
            if isinstance(raw_routine, Mapping):
                routine_id = str(
                    raw_routine.get("id")
                    or raw_routine.get("key")
                    or raw_routine.get("code")
                    or ""
                ).strip()
                routine_name = str(
                    raw_routine.get("name")
                    or raw_routine.get("label")
                    or f"Rotina {routine_id}"
                ).strip()
            else:
                routine_id = str(raw_routine or "").strip()
                routine_name = f"Rotina {routine_id}"
            if not _IDENTIFIER_PATTERN.fullmatch(routine_id):
                raise ValueError(f"rotina invalida em {key}: {routine_id!r}")
            if routine_id in seen_routines:
                raise ValueError(f"rotina duplicada em {key}: {routine_id}")
            if not routine_name or len(routine_name) > 160:
                raise ValueError(f"nome de rotina invalido em {key}")
            seen_routines.add(routine_id)
            routines.append({"id": routine_id, "name": routine_name})

        raw_units = raw_category.get("units") or []
        if not isinstance(raw_units, (list, tuple)):
            raise ValueError(f"units invalido em {key}")
        units: list[str] = []
        for raw_unit in raw_units:
            unit = str(raw_unit or "").strip()
            if not _IDENTIFIER_PATTERN.fullmatch(unit):
                raise ValueError(f"unidade invalida em {key}: {unit!r}")
            if unit not in units:
                units.append(unit)

        name = str(raw_category.get("name") or raw_category.get("label") or key).strip()
        description = str(raw_category.get("description") or "").strip()
        if not name or len(name) > 120:
            raise ValueError(f"nome invalido para categoria {key}")
        if len(description) > 500:
            raise ValueError(f"descricao excede o limite para categoria {key}")
        categories[key] = {
            "key": key,
            "name": name,
            "description": description,
            "routines": routines,
            "units": units,
        }
    return {"categories": categories}
