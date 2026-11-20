from __future__ import annotations

from collections import defaultdict
from threading import RLock
from time import monotonic
from typing import Any

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.liga_entrega_dashboard_service import (
    filial_from_name,
    norm_mapa,
    pick,
    rows_from,
    stored_files,
    to_float,
)

R030237 = "030237"
# A e E são entregas; D (devolução) e C (cancelamento) não saem no caminhão.
STATUS_ENTREGUES = {"A", "E"}
CACHE_SEGUNDOS = 600


class EntregaPalletsService:
    """Pallets por mapa: itens da 03.02.37 ÷ "Caixas Pallet" da 01.11 (cadastro de produtos).

    A Qtde vem em caixas (cx, Dz) ou em unidades avulsas (Un). Unidades são
    convertidas em caixas pelo "Fator" do produto antes da divisão.
    """

    def __init__(self, *, report_store: Any | None, dprodutos_import_service: Any | None) -> None:
        self.report_store = report_store
        self.dprodutos_import_service = dprodutos_import_service
        self._lock = RLock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def pallets_por_mapa(self, competencia: str) -> dict[str, Any]:
        """{"mapas": {(filial, mapa): {...}}, "batch_id": ..., "warnings": [...]}"""
        manifest = self._latest_manifest(competencia)
        if manifest is None:
            return {"mapas": {}, "batch_id": "", "warnings": ["03.02.37 com itens ainda não importada para a competência."]}
        batch_id = str(manifest.get("batch_id") or "")
        with self._lock:
            cached = self._cache.get(batch_id)
            if cached and monotonic() - cached[0] < CACHE_SEGUNDOS:
                return cached[1]
        result = self._calcular(manifest)
        with self._lock:
            self._cache = {batch_id: (monotonic(), result)}
        return result

    def _latest_manifest(self, competencia: str) -> dict[str, Any] | None:
        if self.report_store is None:
            return None
        try:
            manifests = self.report_store.list_manifests(R030237, competencia=None)
        except Exception:
            return None

        def covers(manifest: dict[str, Any]) -> bool:
            metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
            comp = str(metadata.get("operational_competencia") or metadata.get("competencia") or "")
            return comp == competencia or (not comp and str(manifest.get("reference_date") or "").startswith(competencia))

        candidates = [m for m in manifests if isinstance(m, dict) and covers(m)]
        # A 03.02.37 é um acumulado do mês: vale só a última remessa.
        return max(candidates, key=lambda m: (str(m.get("stored_at") or ""), str(m.get("batch_id") or "")), default=None)

    def _calcular(self, manifest: dict[str, Any]) -> dict[str, Any]:
        itens: list[tuple[str, str, str, str, float]] = []
        com_itens = False
        for file in stored_files(manifest):
            filial = filial_from_name(file["filename"])
            for row in rows_from(file["path"]):
                if str(pick(row, "Status") or "").strip().upper() not in STATUS_ENTREGUES:
                    continue
                produto = normalize_numeric_code(pick(row, "Produto"))
                if not produto:
                    continue
                com_itens = True
                itens.append((
                    filial,
                    norm_mapa(pick(row, "Mapa")),
                    produto,
                    str(pick(row, "Unidade") or "").strip(),
                    to_float(pick(row, "Qtde")),
                ))
        if not com_itens:
            return {"mapas": {}, "batch_id": manifest.get("batch_id", ""), "warnings": ["A última 03.02.37 importada não tem itens (Produto/Qtde)."]}

        paletizacao = self._paletizacao({item[2] for item in itens})
        mapas: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"pallets": 0.0, "caixas": 0.0, "itens_sem_paletizacao": 0})
        sem_cadastro: set[str] = set()
        for filial, mapa, produto, unidade, qtde in itens:
            if not filial or not mapa:
                continue
            fator, caixas_pallet = paletizacao.get(produto, (0.0, 0.0))
            target = mapas[(filial, mapa)]
            if caixas_pallet <= 0:
                # Vasilhame, garrafeira e palete não estão na 01.11 ou não têm paletização.
                target["itens_sem_paletizacao"] += 1
                sem_cadastro.add(produto)
                continue
            caixas = qtde / fator if unidade.lower() == "un" and fator > 1 else qtde
            target["caixas"] += caixas
            target["pallets"] += caixas / caixas_pallet
        for item in mapas.values():
            item["pallets"] = round(item["pallets"], 2)
            item["caixas"] = round(item["caixas"], 2)
        warnings = []
        if not paletizacao:
            warnings.append("Cadastro de produtos (01.11) sem \"Caixas Pallet\": reimporte a 01.11 completa.")
        return {"mapas": dict(mapas), "batch_id": manifest.get("batch_id", ""), "warnings": warnings, "produtos_sem_paletizacao": len(sem_cadastro)}

    def _paletizacao(self, produtos: set[str]) -> dict[str, tuple[float, float]]:
        lookup = getattr(self.dprodutos_import_service, "lookup_paletizacao", None)
        if not callable(lookup):
            return {}
        try:
            return lookup(produtos)
        except Exception:
            return {}
