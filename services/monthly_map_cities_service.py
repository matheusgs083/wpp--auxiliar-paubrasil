from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any


MONTHLY_MAP_CITIES_ROUTINE = "03114902_MENSAL_LIGA"
CURRENT_MAP_CITIES_ROUTINE = "03114902_BOT"


class MonthlyMapCitiesService:
    """Leitura isolada da 03.11.49.02 mensal, sem interferir na Liga."""

    def __init__(self, *, report_store: Any, raw_sql_import_service: Any | None = None) -> None:
        self.report_store = report_store
        self.raw_sql_import_service = raw_sql_import_service

    def build_dashboard(self, *, competencia: str | None = None, period: str = "atual") -> dict[str, Any]:
        # Este card representa o lote mensal e deve permanecer independente do
        # seletor Atual/Fechamento da Liga. A rotina atual (03114902_BOT) já é
        # consumida pelo dashboard de rotas; misturá-la aqui fazia o card ficar
        # vazio sempre que a tela estivesse no período atual.
        del period
        normalized_period = "fechado"
        routine = MONTHLY_MAP_CITIES_ROUTINE
        if self.raw_sql_import_service is not None:
            return self._build_from_sql(routine=routine, competencia=competencia or "")
        manifests = []
        for manifest in self.report_store.list_manifests(routine, competencia=competencia):
            metadata = manifest.get("metadata") or {}
            stored_period = str(metadata.get("period") or ("fechado" if routine == MONTHLY_MAP_CITIES_ROUTINE else "atual"))
            if stored_period == normalized_period:
                manifests.append(manifest)
        if not manifests:
            return self._empty(competencia or "")
        warnings: list[str] = []
        manifest = None
        maps: dict[tuple[str, str], dict[str, str]] = {}
        # Do not let a newer empty/corrupt upload hide the last valid monthly card.
        for candidate in reversed(manifests):
            candidate_maps: dict[tuple[str, str], dict[str, str]] = {}
            for item in candidate.get("files") or []:
                path = Path(str(item.get("path") or ""))
                filial = "SUME" if "SUME" in path.name.upper() else "PATOS" if "PATOS" in path.name.upper() else ""
                try:
                    for row in self._rows(path):
                        mapa = self._mapa(self._pick(row, "Mapa"))
                        cidade = self._pick(row, "Cidade", "Municipio", "Município", "Nome Cidade")
                        if not mapa:
                            continue
                        candidate_maps[(filial, mapa)] = {
                            "filial": filial or "-",
                            "mapa": mapa,
                            "cidade": cidade or "Não informada",
                            "data": self._pick(row, "Data", "Data Movimento"),
                        }
                except (OSError, UnicodeError, csv.Error) as exc:
                    warnings.append(f"{path.name}: {exc}")
            if candidate_maps:
                manifest = candidate
                maps = candidate_maps
                break
        if manifest is None:
            return self._empty(competencia or "") | {"warnings": warnings or ["Nenhum registro reconhecido no lote mensal da 03.11.49.02."]}
        rows = sorted(maps.values(), key=lambda item: (item["filial"], int(item["mapa"]) if item["mapa"].isdigit() else item["mapa"]))
        return {
            "ok": True,
            "competencia": competencia or str(manifest.get("reference_date") or "")[:7],
            "rows": rows,
            "summary": {"mapas": len(rows), "cidades": len({row["cidade"] for row in rows if row["cidade"] != "Não informada"}), "files": int(manifest.get("file_count") or 0), "stored_at": str(manifest.get("stored_at") or "")},
            "warnings": warnings,
        }

    def _build_from_sql(self, *, routine: str, competencia: str) -> dict[str, Any]:
        """Monta o card somente das linhas persistidas em reports.*."""
        records = self._rows_from_sql(routine=routine, competencia=competencia)
        if not records:
            # O upload do painel grava primeiro o manifesto e agenda a carga
            # SQL em segundo plano. Se a página for aberta antes da fila
            # terminar (ou se a fila tiver sido interrompida), aproveitamos o
            # lote salvo para concluir a carga uma única vez e consultamos
            # novamente o SQL. O card continua sem fallback de leitura direta
            # dos CSVs.
            latest_manifest = getattr(self.report_store, "latest_manifest", lambda _routine: None)(routine)
            importer = getattr(self.raw_sql_import_service, "import_manifests", None)
            if latest_manifest and callable(importer):
                importer({routine: [latest_manifest]})
                records = self._rows_from_sql(routine=routine, competencia=competencia)
        if not records:
            return self._empty(competencia) | {
                "warnings": ["Nenhum registro SQL importado para o lote de mapas."]
            }

        # A carga preserva versões de um mesmo arquivo. Começamos pelo lote
        # mais recente e usamos o primeiro lote que contém mapas reconhecidos,
        # mantendo a proteção contra upload vazio/corrompido.
        batches: dict[str, list[dict[str, Any]]] = {}
        filenames: dict[str, str] = {}
        for record in records:
            source_key = str(record.get("source_key") or "")
            if not source_key:
                continue
            batches.setdefault(source_key, []).append(record)
            filenames[source_key] = str(record.get("filename") or "")

        maps: dict[tuple[str, str], dict[str, str]] = {}
        selected_sources: set[str] = set()
        for source_key, batch_rows in batches.items():
            candidate_maps: dict[tuple[str, str], dict[str, str]] = {}
            filename = filenames.get(source_key, "")
            filial = "SUME" if "SUME" in filename.upper() else "PATOS" if "PATOS" in filename.upper() else ""
            for record in batch_rows:
                row = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
                mapa = self._mapa(self._pick(row, "Mapa"))
                cidade = self._pick(row, "Cidade", "Municipio", "Município", "Nome Cidade")
                if not mapa:
                    continue
                candidate_maps[(filial, mapa)] = {
                    "filial": filial or "-",
                    "mapa": mapa,
                    "cidade": cidade or "Não informada",
                    "data": self._pick(row, "Data", "Data Movimento"),
                }
            if candidate_maps:
                for map_key, map_value in candidate_maps.items():
                    # Os registros vieram do SQL em ordem decrescente de
                    # importacao: uma versao mais antiga nao sobrescreve a
                    # mais recente do mesmo mapa/filial.
                    maps.setdefault(map_key, map_value)
                selected_sources.add(source_key)

        if not maps:
            return self._empty(competencia) | {
                "warnings": ["Nenhum registro SQL reconhecido no lote de mapas."]
            }
        rows = sorted(maps.values(), key=lambda item: (item["filial"], int(item["mapa"]) if item["mapa"].isdigit() else item["mapa"]))
        return {
            "ok": True,
            "competencia": competencia,
            "rows": rows,
            "summary": {
                "mapas": len(rows),
                "cidades": len({row["cidade"] for row in rows if row["cidade"] != "Não informada"}),
                "files": len(selected_sources),
                "stored_at": "",
            },
            "warnings": [],
        }

    def _rows_from_sql(self, *, routine: str, competencia: str) -> list[dict[str, Any]]:
        try:
            return self.raw_sql_import_service.rows_for_routine(
                routine=routine,
                competencia=competencia or None,
                period="fechado" if routine == MONTHLY_MAP_CITIES_ROUTINE else "atual",
            )
        except TypeError:
            # Compatibilidade com doubles/integrações antigas; o serviço real
            # sempre recebe o período para não misturar atual e fechamento.
            return self.raw_sql_import_service.rows_for_routine(
                routine=routine,
                competencia=competencia or None,
            )

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
