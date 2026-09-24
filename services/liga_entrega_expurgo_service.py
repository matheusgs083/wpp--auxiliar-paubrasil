
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

_VALID_TYPES = {"devolucao", "km", "tml", "dispersao"}
_VALID_SCOPES = {"individual", "equipe"}
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COMPETENCIA_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class LigaEntregaExpurgoService:
    """Persiste expurgos do painel da Liga separados dos relatorios importados."""

    def __init__(self, storage_path: str | Path) -> None:
        self.storage_path = Path(storage_path)
        self._lock = RLock()

    def list_expurgos(
        self,
        *,
        competencia: str | None = None,
        tipo: str | None = None,
        active_only: bool = True,
    ) -> dict[str, Any]:
        clean_competencia = self._clean_optional_competencia(competencia)
        clean_tipo = self._clean_optional_tipo(tipo)
        payload = self._read_payload()
        records = payload.get("items") if isinstance(payload.get("items"), list) else []
        filtered = []
        for item in records:
            if not isinstance(item, dict):
                continue
            if clean_competencia and str(item.get("competencia") or "") != clean_competencia:
                continue
            if clean_tipo and str(item.get("tipo") or "") != clean_tipo:
                continue
            if active_only and not bool(item.get("active", True)):
                continue
            filtered.append(dict(item))
        filtered.sort(key=lambda row: (str(row.get("competencia") or ""), str(row.get("tipo") or ""), str(row.get("created_at") or "")))
        return {"items": filtered, "total": len(filtered), "storage_path": str(self.storage_path)}

    def upsert_expurgo(self, payload: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
        record = self._normalize_record(payload, actor=actor)
        with self._lock:
            state = self._read_payload()
            items = state.get("items") if isinstance(state.get("items"), list) else []
            now = self._now()
            existing_idx = next((idx for idx, item in enumerate(items) if isinstance(item, dict) and item.get("id") == record["id"]), None)
            if existing_idx is None:
                record["created_at"] = now
                record["updated_at"] = now
                items.append(record)
            else:
                previous = dict(items[existing_idx])
                record["created_at"] = str(previous.get("created_at") or now)
                record["created_by"] = str(previous.get("created_by") or record.get("created_by") or "")
                record["updated_at"] = now
                items[existing_idx] = {**previous, **record}
            state["items"] = items
            state["updated_at"] = now
            self._write_payload(state)
        return record

    def delete_expurgo(self, expurgo_id: str, *, actor: str = "") -> dict[str, Any]:
        clean_id = self._clean_id(expurgo_id)
        with self._lock:
            state = self._read_payload()
            items = state.get("items") if isinstance(state.get("items"), list) else []
            now = self._now()
            for item in items:
                if not isinstance(item, dict) or item.get("id") != clean_id:
                    continue
                item["active"] = False
                item["deleted_at"] = now
                item["updated_at"] = now
                item["deleted_by"] = str(actor or "")
                state["items"] = items
                state["updated_at"] = now
                self._write_payload(state)
                return dict(item)
        raise KeyError(f"Expurgo nao encontrado: {clean_id}")

    def apply_to_records(self, records: list[dict[str, Any]], *, key_field: str = "expurgo_key") -> list[dict[str, Any]]:
        active = self.list_expurgos(active_only=True).get("items", [])
        active_ids = {str(item.get("id") or "") for item in active if isinstance(item, dict)}
        active_keys = {str(item.get("key") or "") for item in active if isinstance(item, dict)}
        result: list[dict[str, Any]] = []
        for row in records:
            item = dict(row)
            row_key = str(item.get(key_field) or "")
            row_id = str(item.get("expurgo_id") or "")
            item["expurgado"] = bool((row_id and row_id in active_ids) or (row_key and row_key in active_keys))
            result.append(item)
        return result

    def _normalize_record(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        tipo = self._clean_tipo(payload.get("tipo"))
        raw_escopo = payload.get("escopo")
        competencia = self._clean_competencia(payload.get("competencia"))
        filial = self._clean_text(payload.get("filial"), max_len=40).upper()
        data = self._clean_optional_date(payload.get("data"))
        mapa = self._clean_text(payload.get("mapa"), max_len=40)
        cliente = self._clean_text(payload.get("cliente"), max_len=80)
        motivo = self._clean_text(payload.get("motivo"), max_len=300)
        observacao = self._clean_text(payload.get("observacao"), max_len=500)
        # Compatibilidade com os expurgos TML de dia inteiro criados antes do
        # campo escopo existir: mapa vazio significava toda a equipe.
        escopo = self._clean_escopo("equipe" if raw_escopo in (None, "") and tipo == "tml" and not mapa else raw_escopo)
        if escopo == "individual" and tipo in {"km", "tml", "dispersao"} and not mapa:
            raise ValueError("Mapa obrigatorio para expurgo de rota.")
        if escopo == "individual" and tipo == "devolucao" and not cliente:
            raise ValueError("Cliente obrigatorio para expurgo de devolucao.")
        if tipo in {"km", "tml", "dispersao"} and not data:
            raise ValueError("Data obrigatoria para expurgo de rota.")
        if tipo == "devolucao" and not data:
            raise ValueError("Data obrigatoria para expurgo de devolucao.")
        if escopo == "equipe":
            mapa = ""
            cliente = ""
        key = self._build_key(tipo=tipo, escopo=escopo, competencia=competencia, filial=filial, data=data, mapa=mapa, cliente=cliente)
        return {
            "id": self._id_from_key(key),
            "key": key,
            "tipo": tipo,
            "escopo": escopo,
            "competencia": competencia,
            "filial": filial,
            "data": data,
            "mapa": mapa,
            "cliente": cliente,
            "motivo": motivo,
            "observacao": observacao,
            "active": bool(payload.get("active", True)),
            "created_by": str(actor or ""),
            "updated_by": str(actor or ""),
        }

    def _read_payload(self) -> dict[str, Any]:
        if not self.storage_path.exists():
            return {"version": 1, "items": []}
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "items": []}
        return payload if isinstance(payload, dict) else {"version": 1, "items": []}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.storage_path.with_name(f"{self.storage_path.name}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.storage_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _clean_text(value: Any, *, max_len: int) -> str:
        return str(value or "").strip()[:max_len]

    @staticmethod
    def _clean_id(value: Any) -> str:
        clean = str(value or "").strip().lower()
        if not re.fullmatch(r"[a-f0-9]{16,64}", clean):
            raise ValueError("ID de expurgo invalido.")
        return clean

    @classmethod
    def _clean_tipo(cls, value: Any) -> str:
        tipo = str(value or "").strip().lower()
        if tipo not in _VALID_TYPES:
            raise ValueError("Tipo de expurgo invalido. Use devolucao, km, tml ou dispersao.")
        return tipo

    @classmethod
    def _clean_escopo(cls, value: Any) -> str:
        escopo = str(value or "individual").strip().lower()
        if escopo not in _VALID_SCOPES:
            raise ValueError("Escopo de expurgo invalido. Use individual ou equipe.")
        return escopo

    @classmethod
    def _clean_optional_tipo(cls, value: Any) -> str:
        raw = str(value or "").strip()
        return cls._clean_tipo(raw) if raw else ""

    @staticmethod
    def _clean_competencia(value: Any) -> str:
        competencia = str(value or "").strip()
        if not _COMPETENCIA_PATTERN.fullmatch(competencia):
            raise ValueError("Competencia invalida. Use AAAA-MM.")
        return competencia

    @classmethod
    def _clean_optional_competencia(cls, value: Any) -> str:
        raw = str(value or "").strip()
        return cls._clean_competencia(raw) if raw else ""

    @staticmethod
    def _clean_optional_date(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if not _DATE_PATTERN.fullmatch(raw):
            raise ValueError("Data invalida. Use AAAA-MM-DD.")
        return raw

    @staticmethod
    def _build_key(*, tipo: str, escopo: str, competencia: str, filial: str, data: str, mapa: str, cliente: str) -> str:
        return "|".join([tipo, escopo, competencia, filial, data, mapa, cliente])

    @staticmethod
    def _id_from_key(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
