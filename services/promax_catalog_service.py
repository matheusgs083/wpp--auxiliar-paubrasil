from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any


logger = logging.getLogger(__name__)
_CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


DEFAULT_PROMAX_CATALOG: dict[str, Any] = {
    "categories": {
        "adf": {
            "name": "ADF",
            "description": "Relatorios de dados para o ADF.",
            "routines": [
                {"id": "030237", "name": "Rotina 030237"},
            ],
            "units": [],
        },
        "bot_zap": {
            "name": "Bot Zap",
            "description": "Relatorios consumidos pelos fluxos do bot de WhatsApp.",
            "routines": [
                {"id": "120601_BOT", "name": "Rotina 120601 Bot"},
                {"id": "020220_BOT", "name": "Rotina 020220 Bot"},
                {"id": "030206_BOT", "name": "Rotina 030206 Bot"},
            ],
            "units": [],
        },
        "estoque": {
            "name": "Estoque",
            "description": "Relatorios de posicao e movimentacao de estoque.",
            "routines": [
                {"id": "030237_ESTOQUE", "name": "Rotina 030237 Estoque"},
                {"id": "020502", "name": "Rotina 020502"},
            ],
            "units": [],
        },
        "fluxo_caixa": {
            "name": "Fluxo de Caixa",
            "description": "Relatorios usados na consolidacao do fluxo de caixa.",
            "routines": [
                {"id": "140506", "name": "Rotina 140506"},
                {"id": "120606", "name": "Rotina 120606"},
                {"id": "020502_FLUXO_DE_CAIXA", "name": "Rotina 020502 Fluxo de Caixa"},
                {"id": "150501_FLUXO_DE_CAIXA", "name": "Rotina 150501 Fluxo de Caixa"},
            ],
            "units": [],
        },
        "giro": {
            "name": "Giro",
            "description": "Relatorios de giro de estoque e comodatos.",
            "routines": [
                {"id": "030237_GIRO", "name": "Rotina 030237 Giro"},
                {"id": "020220_GIRO", "name": "Rotina 020220 Giro"},
            ],
            "units": [],
        },
        "inadimplencia": {
            "name": "Inadimplencia",
            "description": "Relatorios operacionais de inadimplencia.",
            "routines": [
                {"id": "0513", "name": "Rotina 0513"},
                {"id": "120616", "name": "Rotina 120616"},
                {"id": "120601", "name": "Rotina 120601"},
            ],
            "units": [],
        },
        "obz": {
            "name": "OBZ",
            "description": "Relatorios de acompanhamento do OBZ.",
            "routines": [
                {"id": "0512", "name": "Rotina 0512"},
                {"id": "150501", "name": "Rotina 150501"},
            ],
            "units": [],
        },
        "outros": {
            "name": "Outros",
            "description": "Relatorios administrativos fora dos grupos especializados.",
            "routines": [
                {"id": "020220_AUDITOOL", "name": "Rotina 020220 Auditool"},
                {"id": "020220_RECOLHAS", "name": "Rotina 020220 Recolhas"},
            ],
            "units": [],
        },
    }
}


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
