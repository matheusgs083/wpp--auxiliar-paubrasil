from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4


class JornadaMapaJustificativaConflict(ValueError):
    pass


def jornada_mapa_id(row: dict) -> str:
    identity = [str(row.get(key) or "").strip().upper() for key in ("competencia", "data", "filial", "mapa")]
    if not all(identity):
        raise ValueError("Mapa sem competência, data, filial ou identificação para justificar.")
    identity[3] = str(int(identity[3])) if identity[3].isdigit() else identity[3]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


class JornadaMapasJustificativasService:
    """Justificativas manuais independentes das importações dos relatórios."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._lock = RLock()

    def _read(self) -> dict[str, dict]:
        if not self.storage_path.exists():
            return {}
        value = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Arquivo de justificativas de jornada inválido.")
        return value

    def get(self, key: str) -> dict | None:
        with self._lock:
            return deepcopy(self._read().get(key))

    def annotate(self, rows: list[dict]) -> None:
        with self._lock:
            records = self._read()
        for row in rows:
            key = jornada_mapa_id(row)
            row["justificativa_id"] = key
            row["justificativa"] = deepcopy(records.get(key))

    def save(self, row: dict, text: str, *, actor: str, version: str = "") -> dict:
        text = str(text or "").strip()
        if not text or len(text) > 5_000:
            raise ValueError("Informe uma justificativa com até 5.000 caracteres.")
        key = jornada_mapa_id(row)
        with self._lock:
            records = self._read()
            previous = records.get(key)
            if (previous or {}).get("version", "") != str(version or ""):
                raise JornadaMapaJustificativaConflict("A justificativa foi alterada por outra pessoa. Atualize antes de salvar.")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            revision = {"text": text, "actor": actor, "at": now, "version": uuid4().hex}
            clean = {field: value for field, value in row.items() if field not in {"justificativa", "justificativa_id"}}
            record = {
                "id": key,
                "mapa": clean,
                "text": text,
                "updated_by": actor,
                "updated_at": now,
                "version": revision["version"],
                "history": [*(previous or {}).get("history", []), revision],
            }
            records[key] = record
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.storage_path.with_suffix("." + uuid4().hex + ".tmp")
            try:
                temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.storage_path)
            finally:
                temporary.unlink(missing_ok=True)
            return deepcopy(record)
