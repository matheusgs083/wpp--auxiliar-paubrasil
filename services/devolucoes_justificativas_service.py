from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from threading import RLock
import unicodedata
from uuid import uuid4


def _search(value: object) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or '')).casefold() if not unicodedata.combining(c))


def devolucao_id(row: dict) -> str:
    # Nomes, motivos e valores podem mudar nas reimportações; não compõem a chave.
    identity = [str(row.get(k) or '').strip().upper() for k in
                ('filial', 'cliente_cod', 'nota', 'serie', 'data_devolucao')]
    identity[-1] = identity[-1] or str(row.get('data') or '').strip()
    for i in (1, 2, 3):
        if identity[i].isdigit():
            identity[i] = str(int(identity[i]))
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


class JustificativaConflict(ValueError):
    pass


class DevolucoesJustificativasService:
    """Arquivo separado dos snapshots/importações, com histórico imutável de revisões."""

    def __init__(self, storage_path: str | Path):
        self.storage_path = Path(storage_path)
        self._lock = RLock()

    def _read(self) -> dict:
        if not self.storage_path.exists():
            return {}
        # Não sobrescrever silenciosamente um arquivo corrompido.
        result = json.loads(self.storage_path.read_text(encoding='utf-8'))
        if not isinstance(result, dict):
            raise ValueError('Arquivo de justificativas inválido.')
        return result

    def list(self, q: str = '', limit: int = 200) -> dict:
        with self._lock:
            records = list(self._read().values())
        query = _search(q).strip()
        records = [r for r in records if not query or query in _search(json.dumps(r, ensure_ascii=False))]
        records.sort(key=lambda r: r['updated_at'], reverse=True)
        return {'items': deepcopy(records[:limit]), 'total': len(records)}

    def annotate(self, rows: list[dict]) -> None:
        with self._lock:
            records = self._read()
        for row in rows:
            row['justificativa_id'] = devolucao_id(row)
            row['justificativa'] = deepcopy(records.get(row['justificativa_id']))

    def get(self, key: str) -> dict | None:
        with self._lock:
            return deepcopy(self._read().get(key))

    def save(self, row: dict, text: str, *, actor: str, version: str = '') -> dict:
        text = text.strip()
        if not text or len(text) > 5000:
            raise ValueError('Informe uma justificativa com até 5.000 caracteres.')
        if not row.get('filial') or not row.get('nota') or not row.get('cliente_cod'):
            raise ValueError('Devolução sem identificação completa: filial, nota e código do cliente.')
        key = devolucao_id(row)
        with self._lock:
            records = self._read()
            previous = records.get(key)
            if (previous or {}).get('version', '') != version:
                raise JustificativaConflict('A justificativa foi alterada por outra pessoa. Atualize antes de salvar.')
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            revision = {'text': text, 'actor': actor, 'at': now, 'version': uuid4().hex}
            clean = {k: v for k, v in row.items() if k not in ('justificativa', 'justificativa_id')}
            record = {'id': key, 'devolucao': clean, 'text': text, 'updated_by': actor,
                      'updated_at': now, 'version': revision['version'],
                      'history': [*(previous or {}).get('history', []), revision]}
            records[key] = record
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.storage_path.with_suffix('.' + uuid4().hex + '.tmp')
            try:
                temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(self.storage_path)
            finally:
                temporary.unlink(missing_ok=True)
            return deepcopy(record)
