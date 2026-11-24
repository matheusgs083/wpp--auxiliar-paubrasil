"""Liberações manuais de clientes bloqueados pela inadimplência (12.06.01) na digitação de pedidos.

O administrador libera um cliente por alguns dias; enquanto a liberação vale, o painel
deixa digitar pedido mesmo com títulos em aberto. As liberações ficam num arquivo JSON,
independente das importações, como as justificativas de jornada.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Fortaleza")
DIAS_PERMITIDOS = (1, 3, 7)


def chave_cliente(filial: str, cliente: str) -> str:
    filial_limpa = str(filial or "").strip().lstrip("0") or "0"
    cliente_limpo = str(cliente or "").strip().lstrip("0") or "0"
    if not str(filial or "").strip().isdigit() or not str(cliente or "").strip().isdigit():
        raise ValueError("Filial e NB devem ser numéricos.")
    return f"{filial_limpa}_{cliente_limpo}"


class PedidoLiberacoesService:
    def __init__(self, storage_path: str | Path, agora: Callable[[], datetime] = lambda: datetime.now(FUSO)) -> None:
        self.storage_path = Path(storage_path)
        self._agora = agora
        self._lock = RLock()

    def _hoje(self) -> date:
        return self._agora().astimezone(FUSO).date()

    def _read(self) -> dict[str, dict]:
        if not self.storage_path.exists():
            return {}
        value = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Arquivo de liberações de pedidos inválido.")
        return value

    def _write(self, records: dict[str, dict]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.storage_path.with_suffix("." + uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.storage_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _vigentes(self, records: dict[str, dict]) -> dict[str, dict]:
        hoje = self._hoje().isoformat()
        return {chave: item for chave, item in records.items() if str(item.get("valida_ate") or "") >= hoje}

    def ativa(self, filial: str, cliente: str) -> dict | None:
        """Liberação que ainda vale hoje para o cliente, ou None."""
        with self._lock:
            return deepcopy(self._vigentes(self._read()).get(chave_cliente(filial, cliente)))

    def listar(self) -> dict[str, dict]:
        with self._lock:
            return deepcopy(self._vigentes(self._read()))

    def liberar(self, filial: str, cliente: str, *, nome: str, motivo: str, dias: int, actor: str) -> dict:
        if dias not in DIAS_PERMITIDOS:
            raise ValueError("Escolha liberar por 1, 3 ou 7 dias.")
        motivo = " ".join(str(motivo or "").split())
        if not motivo or len(motivo) > 200:
            raise ValueError("Informe o motivo da liberação (até 200 caracteres).")
        chave = chave_cliente(filial, cliente)
        agora = self._agora().astimezone(FUSO)
        registro = {
            "filial": chave.split("_")[0],
            "cliente": chave.split("_")[1],
            "nome": str(nome or "").strip()[:120],
            "motivo": motivo,
            "liberado_por": str(actor or "").strip(),
            "liberado_em": agora.isoformat(timespec="seconds"),
            # Vale até o fim do último dia: 1 dia = só hoje.
            "valida_ate": (agora.date() + timedelta(days=dias - 1)).isoformat(),
        }
        with self._lock:
            # Ao gravar, as liberações vencidas saem do arquivo.
            records = self._vigentes(self._read())
            records[chave] = registro
            self._write(records)
        return deepcopy(registro)

    def revogar(self, filial: str, cliente: str) -> bool:
        chave = chave_cliente(filial, cliente)
        with self._lock:
            records = self._vigentes(self._read())
            existia = records.pop(chave, None) is not None
            self._write(records)
        return existia
