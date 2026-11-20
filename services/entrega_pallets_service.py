from __future__ import annotations

from collections import defaultdict
from threading import RLock
from time import monotonic
from typing import Any

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.liga_entrega_dashboard_service import (
    filial_from_name,
    norm_header,
    norm_mapa,
    rows_from,
    stored_files,
    text_encoding,
    to_float,
)

R030237 = "030237"
# A e E são entregas; D (devolução) e C (cancelamento) não saem no caminhão.
STATUS_ENTREGUES = {"A", "E"}
# Colunas que só existem na 03.02.37 gerada com itens.
COLUNAS_ITENS = {"produto", "qtde"}
CACHE_SEGUNDOS = 60


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
        result["warnings"] = [*([manifest["_aviso"]] if manifest.get("_aviso") else []), *result["warnings"]]
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

        candidates = sorted(
            (m for m in manifests if isinstance(m, dict) and covers(m)),
            key=lambda m: (str(m.get("stored_at") or ""), str(m.get("batch_id") or "")),
            reverse=True,
        )
        # A 03.02.37 é um acumulado do mês: vale a remessa mais recente que tenha itens.
        # Uma remessa posterior sem itens (worker ainda no layout antigo) não apaga os pallets.
        com_itens = next((m for m in candidates if self._tem_itens(m)), None)
        if com_itens is not None and com_itens is not candidates[0]:
            com_itens = {**com_itens, "_aviso": (
                f"A última 03.02.37 (recebida em {self._quando(candidates[0])}) veio sem itens; "
                f"pallets calculados com a de {self._quando(com_itens)}."
            )}
        return com_itens or (candidates[0] if candidates else None)

    @staticmethod
    def _quando(manifest: dict[str, Any]) -> str:
        texto = str(manifest.get("stored_at") or "")
        return f"{texto[8:10]}/{texto[5:7]} {texto[11:16]}" if len(texto) >= 16 else (texto or "data desconhecida")

    @staticmethod
    def _tem_itens(manifest: dict[str, Any]) -> bool:
        for file in stored_files(manifest):
            try:
                with file["path"].open("r", encoding=text_encoding(file["path"]), errors="replace", newline="") as handle:
                    head = next((line for line in handle if line.strip()), "")
            except OSError:
                continue
            delimiter = ";" if head.count(";") >= head.count(",") else ","
            if COLUNAS_ITENS <= {norm_header(column) for column in head.split(delimiter)}:
                return True
        return False

    @staticmethod
    def _campo(row: dict[str, str], nome: str) -> str:
        # Só o nome exato da coluna. A busca aproximada da Liga confundiria, numa
        # 03.02.37 sem itens, "Produto" com "NF Venda AG/Produto/Material".
        return str(row.get(norm_header(nome)) or "")

    def _calcular(self, manifest: dict[str, Any]) -> dict[str, Any]:
        itens: list[tuple[str, str, str, str, float]] = []
        com_itens = False
        for file in stored_files(manifest):
            filial = filial_from_name(file["filename"])
            for row in rows_from(file["path"]):
                if self._campo(row, "Status").strip().upper() not in STATUS_ENTREGUES:
                    continue
                produto = normalize_numeric_code(self._campo(row, "Produto"))
                if not produto:
                    continue
                com_itens = True
                itens.append((
                    filial,
                    norm_mapa(self._campo(row, "Mapa")),
                    produto,
                    self._campo(row, "Unidade").strip(),
                    to_float(self._campo(row, "Qtde")),
                ))
        if not com_itens:
            return {"mapas": {}, "batch_id": manifest.get("batch_id", ""), "warnings": ["A última 03.02.37 importada não tem itens (Produto/Qtde)."]}

        produtos = {item[2] for item in itens}
        paletizacao, erro = self._paletizacao(produtos)
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
        if erro:
            warnings.append(erro)
        elif not paletizacao:
            warnings.append(
                "Nenhum dos %d produtos da 03.02.37 tem \"Caixas Pallet\" no cadastro de produtos: "
                "reimporte a 01.11 completa no Cadastro de Produtos." % len(produtos)
            )
        elif sem_cadastro:
            exemplos = ", ".join(sorted(sem_cadastro)[:8])
            warnings.append(
                "%d de %d produtos sem \"Caixas Pallet\" na 01.11 (ficam fora dos pallets): %s%s."
                % (len(sem_cadastro), len(produtos), exemplos, "..." if len(sem_cadastro) > 8 else "")
            )
        return {"mapas": dict(mapas), "batch_id": manifest.get("batch_id", ""), "warnings": warnings, "produtos_sem_paletizacao": len(sem_cadastro)}

    def _paletizacao(self, produtos: set[str]) -> tuple[dict[str, tuple[float, float]], str]:
        """(paletização, erro). O erro vai para os avisos da tela em vez de virar zero calado."""
        lookup = getattr(self.dprodutos_import_service, "lookup_paletizacao", None)
        if not callable(lookup):
            return {}, "Cadastro de produtos indisponível no servidor."
        try:
            return lookup(produtos), ""
        except Exception as exc:  # noqa: BLE001
            return {}, f"Falha ao ler o cadastro de produtos (01.11): {exc}"
