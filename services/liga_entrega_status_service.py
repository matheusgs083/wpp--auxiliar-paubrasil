from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


class LigaEntregaStatusService:
    """Mantém o status mensal da equipe fora dos arquivos importados."""

    VALID = {"ativo", "ferias", "afastado", "desligado"}

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._lock = RLock()

    def statuses(self, competencia: str) -> dict[str, str]:
        self._validate_competencia(competencia)
        payload = self._read()
        items = payload.get("items", {}) if isinstance(payload, dict) else {}
        rows = items.get(competencia, {}) if isinstance(items, dict) else {}
        return {str(code): str(status) for code, status in rows.items() if str(status) in self.VALID}

    def set_status(self, *, competencia: str, cod: str, status: str, actor: str = "") -> dict[str, str]:
        self._validate_competencia(competencia)
        code = re.sub(r"\D", "", str(cod or ""))
        clean_status = str(status or "").strip().lower()
        if not code:
            raise ValueError("Código do colaborador inválido.")
        if clean_status not in self.VALID:
            raise ValueError("Status inválido.")
        with self._lock:
            payload = self._read()
            items = payload.setdefault("items", {})
            rows = items.setdefault(competencia, {})
            rows[code] = clean_status
            payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            payload["updated_by"] = actor
            self._write(payload)
        return {"competencia": competencia, "cod": code, "status": clean_status}

    def roster(self, competencia: str) -> dict[str, dict[str, str]]:
        """Retorna os colaboradores explicitamente cadastrados na Liga."""
        self._validate_competencia(competencia)
        payload = self._read()
        rows = ((payload.get("roster") or {}).get(competencia) or {}) if isinstance(payload, dict) else {}
        return {str(code): dict(item) for code, item in rows.items() if isinstance(item, dict) and item.get("active", True)}

    def set_roster(self, *, competencia: str, cod: str, nome: str, filial: str, funcao: str, actor: str = "") -> dict[str, str]:
        self._validate_competencia(competencia)
        code = re.sub(r"\D", "", str(cod or ""))
        clean_name = str(nome or "").strip()[:160]
        clean_filial = str(filial or "").strip().upper()[:80]
        clean_role = str(funcao or "").strip().upper()
        if not code or not clean_name or clean_role not in {"MOTORISTA", "AJUDANTE"}:
            raise ValueError("Informe código, nome e função válidos para cadastrar o colaborador.")
        with self._lock:
            payload = self._read()
            roster = payload.setdefault("roster", {})
            rows = roster.setdefault(competencia, {})
            rows[code] = {"cod": code, "nome": clean_name, "filial": clean_filial, "funcao": clean_role, "active": True}
            payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            payload["updated_by"] = actor
            self._write(payload)
        return {"competencia": competencia, **rows[code]}

    def remove_roster(self, *, competencia: str, cod: str, actor: str = "") -> bool:
        self._validate_competencia(competencia)
        code = re.sub(r"\D", "", str(cod or ""))
        with self._lock:
            payload = self._read()
            rows = ((payload.get("roster") or {}).get(competencia) or {}) if isinstance(payload, dict) else {}
            if code not in rows:
                return False
            rows.pop(code, None)
            payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            payload["updated_by"] = actor
            self._write(payload)
        return True

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"items": {}}
        except (OSError, ValueError):
            return {"items": {}}

    def _write(self, payload: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.storage_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.storage_path)

    @staticmethod
    def _validate_competencia(value: str) -> None:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(value or "")):
            raise ValueError("Competência inválida. Use AAAA-MM.")
