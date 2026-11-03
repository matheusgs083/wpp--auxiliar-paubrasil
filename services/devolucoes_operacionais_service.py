from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row


# Contingência para quando a dRevendas ainda não tiver sido importada no SQL.
# São os mesmos códigos operacionais usados nos relatórios de entrega.
DEFAULT_OPERATION_LABELS = {"1": "SOUSA", "2": "ITAPORANGA", "3": "PATOS", "4": "SUME"}


class DevolucoesCadastrosService:
    """Nomes operacionais de setor e gerente, independentes da Liga."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._lock = RLock()

    def list(self) -> dict[str, list[dict[str, str]]]:
        with self._lock:
            data = self._read()
        return {key: deepcopy(data.get(key) or []) for key in ("setores", "gerentes")}

    def replace(self, payload: dict[str, Any], *, actor: str = "") -> dict[str, list[dict[str, str]]]:
        cleaned = {key: _clean_entries(payload.get(key)) for key in ("setores", "gerentes")}
        with self._lock:
            self._write({**cleaned, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "updated_by": actor})
        return cleaned

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.storage_path)


def _clean_entries(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("Cadastros devem ser enviados como lista.")
    result: dict[tuple[str, str], dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        filial = str(item.get("filial") or "").strip().upper()
        codigo = str(item.get("codigo") or "").strip()
        nome = str(item.get("nome") or "").strip()
        if not codigo or not nome:
            continue
        result[(filial, codigo)] = {"filial": filial, "codigo": codigo, "nome": nome}
    return sorted(result.values(), key=lambda item: (item["filial"], item["codigo"]))


def build_devolucoes_operacionais_dashboard(source: dict[str, Any], cadastros: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    """Publica somente fatos de devolução; não usa pontos, metas ou expurgos."""
    sector_names = {(str(x.get("filial", "")).upper(), str(x.get("codigo", ""))): x.get("nome", "") for x in cadastros.get("setores", [])}
    manager_names = {(str(x.get("filial", "")).upper(), str(x.get("codigo", ""))): x.get("nome", "") for x in cadastros.get("gerentes", [])}
    operation_names = {str(item.get("codigo", "")).upper(): str(item.get("nome", "")).upper() for item in cadastros.get("operacoes", []) if isinstance(item, dict)}
    rows: list[dict[str, Any]] = []
    for item in source.get("devolucoes_auxiliares") or source.get("devolucoes") or []:
        if not isinstance(item, dict):
            continue
        row = {key: value for key, value in item.items() if key not in {"excluida", "expurgo_id"}}
        filial = str(row.get("filial") or "").strip().upper()
        setor = str(row.get("setor") or "").strip()
        gerente = str(row.get("gv") or "").strip()
        row["filial"] = filial
        def display_name(names: dict[tuple[str, str], Any], code: str, fallback: str) -> Any:
            direct = names.get((filial, code), names.get(("", code)))
            if direct:
                return direct
            # dSetores usa o código da operação; a devolução usa o nome
            # operacional (ex.: 3 -> PATOS). Faz a ponte pela dRevendas.
            for (operation, saved_code), saved_name in names.items():
                if saved_code == code and saved_name and filial and filial in operation_names.get(operation, ""):
                    return saved_name
            return fallback
        row["setor_nome"] = display_name(sector_names, setor, setor)
        row["gerente_nome"] = display_name(manager_names, gerente, gerente)
        rows.append(row)
    operation = source.get("operacao") if isinstance(source.get("operacao"), dict) else {}
    branches = operation.get("filiais") if isinstance(operation.get("filiais"), dict) else {}
    def base_of(value: Any) -> dict[str, float]:
        item = value if isinstance(value, dict) else {}
        return {
            "entregas_hl": float(item.get("entregas_hl") or 0),
            "entregas_pdvs": float(item.get("entregas_pdvs") or 0),
            "entregas_nfs": float(item.get("entregas_nfs") or 0),
        }
    return {
        "ok": True,
        "competencia": str(source.get("competencia") or ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
        "cadastros": cadastros,
        # Bases de entrega já importadas dos relatórios operacionais. Elas são
        # expostas aqui apenas para os percentuais da devolução, sem metas ou
        # qualquer regra de ranking.
        "bases_entrega": {"geral": base_of(operation), "filiais": {str(key).upper(): base_of(value) for key, value in branches.items()}},
        "source": "03.02.24 Motorista",
    }


def list_dsetores_catalog(service: Any | None, drevendas_service: Any | None = None) -> dict[str, list[dict[str, str]]]:
    """Lê o cadastro completo ativo de dSetores, sem depender de devoluções."""
    if service is None:
        return {"setores": [], "gerentes": [], "operacoes": []}
    try:
        with service._connect() as conn:  # serviço de importação já controla URL, schema e timeout
            query = sql.SQL("SELECT DISTINCT filial, setor, gv FROM {}.dsetores_latest ORDER BY filial, setor, gv").format(sql.Identifier(service.schema))
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query)
                rows = cur.fetchall()
    except Exception:
        return {"setores": [], "gerentes": [], "operacoes": []}
    setores = {(str(row.get("filial") or "").strip().upper(), str(row.get("setor") or "").strip()) for row in rows}
    gerentes = {(str(row.get("filial") or "").strip().upper(), str(row.get("gv") or "").strip()) for row in rows}
    labels: dict[str, str] = dict(DEFAULT_OPERATION_LABELS)
    try:
        labels.update({str(key).lstrip("0") or "0": str(value) for key, value in (drevendas_service.latest_labels() if drevendas_service is not None else {}).items()})
    except Exception:
        pass
    filiais = sorted({filial for filial, _ in setores | gerentes if filial}, key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value))
    return {
        "setores": [{"filial": filial, "codigo": codigo} for filial, codigo in sorted(setores) if codigo],
        "gerentes": [{"filial": filial, "codigo": codigo} for filial, codigo in sorted(gerentes) if codigo],
        "operacoes": [{"codigo": filial, "nome": labels.get(filial.lstrip("0") or "0", filial)} for filial in filiais],
    }
