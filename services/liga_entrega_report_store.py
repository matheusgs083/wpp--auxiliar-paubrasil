from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

_SAFE_ROUTINE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[^\\/:*?\"<>|\r\n]{1,255}$")
_ALLOWED_SUFFIXES = {".csv", ".txt", ".xlsx", ".xlsm", ".xls"}


class LigaEntregaReportStore:
    """Armazena arquivos usados na atualizacao automatica do painel Liga Entrega."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self._latest_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._latest_cache_ttl = 5.0

    def store_batch(
        self,
        *,
        routine: str,
        files: Mapping[str, bytes],
        reference_date: date | str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_routine = self._clean_routine(routine)
        if not files:
            raise ValueError("Nenhum arquivo informado para a Liga Entrega.")
        ref_date = self._normalize_reference_date(reference_date)
        batch_id = uuid.uuid4().hex
        target_dir = self.root_dir / clean_routine / ref_date.isoformat() / batch_id
        target_dir.mkdir(parents=True, exist_ok=True)

        stored_files: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for filename, content in files.items():
            safe_name = self._clean_filename(filename)
            if safe_name in seen_names:
                raise ValueError(f"Arquivo duplicado na remessa da Liga Entrega: {safe_name}.")
            seen_names.add(safe_name)
            data = bytes(content or b"")
            if not data.strip():
                raise ValueError(f"Arquivo vazio na remessa da Liga Entrega: {safe_name}.")
            path = target_dir / safe_name
            path.write_bytes(data)
            stored_files.append({"filename": safe_name, "bytes": len(data), "path": str(path)})

        manifest_metadata = dict(metadata or {})
        # Toda remessa passa a carregar explicitamente sua competência. Isso
        # mantém o histórico quando o mesmo arquivo é enviado novamente em
        # outro mês e evita depender apenas da pasta de upload.
        manifest_metadata.setdefault("competencia", ref_date.strftime("%Y-%m"))
        manifest = {
            "batch_id": batch_id,
            "routine": clean_routine,
            "reference_date": ref_date.isoformat(),
            "stored_at": datetime.now().isoformat(timespec="seconds"),
            "file_count": len(stored_files),
            "files": stored_files,
            "metadata": manifest_metadata,
        }
        (target_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._latest_cache.pop(clean_routine, None)
        return manifest


    def list_manifests(
        self,
        routine: str,
        *,
        competencia: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista manifestos gravados para uma rotina, ordenados por data e gravacao."""

        clean_routine = self._clean_routine(routine)
        clean_competencia = str(competencia or "").strip()
        if clean_competencia and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", clean_competencia):
            raise ValueError("Competencia invalida. Use AAAA-MM.")

        routine_dir = self.root_dir / clean_routine
        if not routine_dir.exists() or not routine_dir.is_dir():
            return []

        manifests: list[dict[str, Any]] = []
        try:
            date_dirs = [path for path in routine_dir.iterdir() if path.is_dir()]
        except OSError:
            return []
        for date_dir in date_dirs:
            date_matches = not clean_competencia or date_dir.name.startswith(f"{clean_competencia}-")
            try:
                batch_dirs = [path for path in date_dir.iterdir() if path.is_dir()]
            except OSError:
                continue
            for batch_dir in batch_dirs:
                manifest_path = batch_dir / "manifest.json"
                if not manifest_path.is_file():
                    continue
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    if clean_competencia and not date_matches:
                        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                        manifest_comp = str(metadata.get("competencia") or metadata.get("operational_competencia") or "").strip()
                        if manifest_comp != clean_competencia:
                            continue
                    manifests.append(payload)

        def sort_key(payload: dict[str, Any]) -> tuple[str, str]:
            return (str(payload.get("reference_date") or ""), str(payload.get("stored_at") or ""))

        manifests.sort(key=sort_key)
        return manifests

    def latest_manifest(self, routine: str) -> dict[str, Any] | None:
        """Retorna o manifesto mais recente gravado para uma rotina da Liga Entrega."""

        clean_routine = self._clean_routine(routine)
        now = time.monotonic()
        cached = self._latest_cache.get(clean_routine)
        if cached is not None and now - cached[0] < self._latest_cache_ttl:
            return dict(cached[1]) if isinstance(cached[1], dict) else None
        routine_dir = self.root_dir / clean_routine
        if not routine_dir.exists() or not routine_dir.is_dir():
            self._latest_cache[clean_routine] = (now, None)
            return None

        candidates: list[Path] = []
        try:
            date_dirs = [path for path in routine_dir.iterdir() if path.is_dir()]
        except OSError:
            self._latest_cache[clean_routine] = (now, None)
            return None
        for date_dir in date_dirs:
            try:
                batch_dirs = [path for path in date_dir.iterdir() if path.is_dir()]
            except OSError:
                continue
            for batch_dir in batch_dirs:
                manifest_path = batch_dir / "manifest.json"
                if manifest_path.is_file():
                    candidates.append(manifest_path)

        latest_payload: dict[str, Any] | None = None
        latest_sort_key: tuple[str, float] | None = None
        for manifest_path in candidates:
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            stored_at = str(payload.get("stored_at") or "")
            try:
                mtime = manifest_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            sort_key = (stored_at, mtime)
            if latest_sort_key is None or sort_key > latest_sort_key:
                latest_sort_key = sort_key
                latest_payload = payload
        self._latest_cache[clean_routine] = (now, latest_payload)
        return dict(latest_payload) if isinstance(latest_payload, dict) else None

    @staticmethod
    def _clean_routine(value: str) -> str:
        routine = str(value or "").strip()
        if not _SAFE_ROUTINE_PATTERN.fullmatch(routine):
            raise ValueError(f"Rotina invalida para Liga Entrega: {value!r}.")
        return routine

    @staticmethod
    def _clean_filename(value: str) -> str:
        filename = Path(str(value or "").strip()).name
        if not filename or not _SAFE_FILENAME_PATTERN.fullmatch(filename):
            raise ValueError(f"Nome de arquivo invalido para Liga Entrega: {value!r}.")
        if Path(filename).suffix.lower() not in _ALLOWED_SUFFIXES:
            raise ValueError(f"Extensao nao permitida para Liga Entrega: {filename}.")
        return filename

    @staticmethod
    def _normalize_reference_date(value: date | str | None) -> date:
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            return datetime.now().date()
        return date.fromisoformat(text)
