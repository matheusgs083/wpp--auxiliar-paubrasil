from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

_SAFE_ROUTINE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[^\\/:*?\"<>|\r\n]{1,255}$")
_ALLOWED_SUFFIXES = {".csv", ".txt", ".xlsx"}


class LigaEntregaReportStore:
    """Armazena arquivos usados na atualizacao automatica do painel Liga Entrega."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

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

        manifest = {
            "batch_id": batch_id,
            "routine": clean_routine,
            "reference_date": ref_date.isoformat(),
            "stored_at": datetime.now().isoformat(timespec="seconds"),
            "file_count": len(stored_files),
            "files": stored_files,
            "metadata": dict(metadata or {}),
        }
        (target_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest

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
