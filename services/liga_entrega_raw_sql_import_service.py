from __future__ import annotations

import csv
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

import psycopg
from psycopg import sql


def _payload_competencia(payload: dict[str, Any]) -> str:
    """Extrai a competência operacional de uma linha persistida.

    Nem todos os relatórios têm ``Ano``/``Mês``; os diários normalmente
    trazem a data em ``Data`` ou ``Data Entrega``.  Retornar vazio quando não
    há data é intencional: uma linha sem competência não deve aparecer em
    todos os meses por acidente.
    """
    year = str(payload.get("Ano") or "").strip()
    month = str(payload.get("Mês") or payload.get("Mes") or "").strip()
    if re.fullmatch(r"\d{4}", year) and re.fullmatch(r"\d{1,2}", month):
        month_int = int(month)
        if 1 <= month_int <= 12:
            return f"{year}-{month_int:02d}"
    for key in ("Data", "Data Entrega", "Data Movimento", "Dt. Operacao", "Dt Operacao", "Data Operacao", "reference_date"):
        value = str(payload.get(key) or "").strip()
        iso = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
        if iso:
            month_int = int(iso.group(2))
            if 1 <= month_int <= 12:
                return f"{iso.group(1)}-{month_int:02d}"
        br = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
        if br:
            month_int = int(br.group(2))
            if 1 <= month_int <= 12:
                return f"{br.group(3)}-{month_int:02d}"
    return ""


class LigaEntregaRawSqlImportService:
    """Importa as linhas dos arquivos da Liga para o PostgreSQL.

    Os arquivos continuam preservados no armazenamento de origem. A chave
    source_key evita reler e duplicar um arquivo que não foi alterado.
    """

    def __init__(self, *, database_url: str, schema: str = "reports", connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "")
        self.schema = str(schema or "reports")
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3), 1.0)
        self._schema_ready = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="liga-sql-import")
        self._pending_lock = Lock()
        self._pending = False

    def enqueue_manifests(self, manifests: dict[str, list[dict[str, Any]]]) -> None:
        """Agenda a conversao sem bloquear a resposta do painel."""
        if not self.database_url:
            return
        with self._pending_lock:
            if self._pending:
                return
            self._pending = True
        self._executor.submit(self._run_pending, manifests)

    def _run_pending(self, manifests: dict[str, list[dict[str, Any]]]) -> None:
        try:
            self.import_manifests(manifests)
        finally:
            with self._pending_lock:
                self._pending = False

    def _connect(self) -> psycopg.Connection[Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)

    def _ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        if self._schema_ready:
            return
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.liga_entrega_raw_rows (
                        source_key TEXT NOT NULL,
                        routine VARCHAR(80) NOT NULL,
                        reference_date DATE,
                        period VARCHAR(12) NOT NULL DEFAULT 'atual',
                        filename TEXT NOT NULL,
                        row_number INTEGER NOT NULL,
                        payload JSONB NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (source_key, row_number)
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "ALTER TABLE {}.liga_entrega_raw_rows "
                    "ADD COLUMN IF NOT EXISTS period VARCHAR(12) NOT NULL DEFAULT 'atual'"
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    "CREATE INDEX IF NOT EXISTS liga_entrega_raw_rows_routine_idx "
                    "ON {}.liga_entrega_raw_rows (routine, period, reference_date)"
                ).format(sql.Identifier(self.schema))
            )
        conn.commit()
        self._schema_ready = True

    def import_manifests(self, manifests: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        if not self.database_url:
            return {"files": 0, "rows": 0, "skipped": 0}
        files = rows = skipped = 0
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                for routine, routine_manifests in manifests.items():
                    for manifest in routine_manifests:
                        for item in manifest.get("files") or []:
                            imported, imported_rows = self._import_file(conn, routine, manifest, item)
                            if imported:
                                files += 1
                                rows += imported_rows
                            else:
                                skipped += 1
                conn.commit()
        except Exception:
            # A indisponibilidade do banco não interrompe o painel; os CSVs
            # continuam sendo a fonte de fallback.
            return {"files": files, "rows": rows, "skipped": skipped}
        return {"files": files, "rows": rows, "skipped": skipped}

    def rows_for_routine(self, *, routine: str, competencia: str | None = None, period: str = "atual") -> list[dict[str, Any]]:
        """Retorna linhas importadas para uma rotina, sem tocar nos arquivos de origem.

        Este método é usado pelos endpoints de leitura da Liga. A carga dos CSVs
        acontece separadamente; a requisição do painel consulta apenas o SQL.
        """
        if not self.database_url:
            return []
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                clauses = ["routine = %s", "period = %s"]
                params: list[Any] = [str(routine), self._normalize_period(period)]
                if competencia:
                    clauses.append("reference_date >= (%s || '-01')::date")
                    clauses.append("reference_date < ((%s || '-01')::date + INTERVAL '1 month')")
                    params.extend([str(competencia), str(competencia)])
                query = sql.SQL(
                    """
                    SELECT source_key, filename, imported_at, payload
                    FROM {}.liga_entrega_raw_rows
                    WHERE {}
                    ORDER BY imported_at DESC, source_key DESC, row_number
                    """
                ).format(sql.Identifier(self.schema), sql.SQL(" AND ").join(sql.SQL(item) for item in clauses))
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return [
                        {
                            "source_key": row[0],
                            "filename": row[1],
                            "imported_at": row[2],
                            "payload": row[3] if isinstance(row[3], dict) else {},
                        }
                        for row in cur.fetchall()
                    ]
        except Exception:
            # A leitura SQL indisponível não deve reabrir o caminho CSV durante
            # uma requisição. O endpoint devolve o estado vazio e o alerta.
            return []

    def fetch_rows(self, *, routine: str, competencia: str | None = None, period: str = "atual") -> list[dict[str, Any]]:
        """Retorna linhas persistidas para uma rotina, sem tocar nos arquivos de origem.

        A consulta privilegia a versão mais recente de cada arquivo/linha
        dentro da competência solicitada. Arquivos com o mesmo nome podem ser
        reenviados em meses diferentes; por isso a competência faz parte da
        deduplicação e o CSV permanece apenas como entrada da importação.
        """
        if not self.database_url:
            return []
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                with conn.cursor() as cur:
                    query = sql.SQL(
                        """
                        SELECT filename, row_number, payload, reference_date, imported_at
                        FROM {}.liga_entrega_raw_rows
                        WHERE routine = %s AND period = %s
                        ORDER BY imported_at DESC, filename, row_number
                        """
                    ).format(sql.Identifier(self.schema))
                    cur.execute(query, (routine, self._normalize_period(period)))
                    rows = []
                    seen: set[tuple[str, int, str]] = set()
                    selected = str(competencia or "").strip()
                    for item in cur.fetchall():
                        if not isinstance(item[2], dict):
                            continue
                        payload = dict(item[2])
                        reference_date = item[3].isoformat() if hasattr(item[3], "isoformat") else str(item[3] or "")
                        if reference_date:
                            payload["_reference_date"] = reference_date
                        row_comp = _payload_competencia(payload) or reference_date[:7]
                        if selected and row_comp != selected:
                            continue
                        # Arquivos com o mesmo nome são reenviados em vários
                        # meses. A competência precisa fazer parte da chave;
                        # deduplicar apenas por filename/linha apagava o mês
                        # anterior e fazia a Liga misturar todas as rotas.
                        key = (str(item[0] or ""), int(item[1] or 0), row_comp)
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(payload)
        except Exception:
            return []
        return rows

    def _import_file(self, conn: psycopg.Connection[Any], routine: str, manifest: dict[str, Any], item: dict[str, Any]) -> tuple[bool, int]:
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            return False, 0
        stat = path.stat()
        period = self._manifest_period(routine, manifest)
        source_key = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{period}"
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT 1 FROM {}.liga_entrega_raw_rows WHERE source_key = %s LIMIT 1").format(sql.Identifier(self.schema)),
                (source_key,),
            )
            if cur.fetchone():
                return False, 0
        rows = list(self._read_rows(path))
        if not rows:
            return True, 0
        reference_date = str(manifest.get("reference_date") or "") or None
        filename = path.name
        with conn.cursor() as cur:
            cur.executemany(
                sql.SQL(
                    """
                    INSERT INTO {}.liga_entrega_raw_rows
                        (source_key, routine, reference_date, period, filename, row_number, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (source_key, row_number) DO NOTHING
                    """
                ).format(sql.Identifier(self.schema)),
                [
                    (source_key, routine, reference_date, period, filename, index, json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                    for index, row in enumerate(rows, start=1)
                ],
            )
        return True, len(rows)

    @staticmethod
    def _normalize_period(value: Any) -> str:
        return "fechado" if str(value or "").strip().lower() == "fechado" else "atual"

    def _manifest_period(self, routine: str, manifest: dict[str, Any]) -> str:
        metadata = manifest.get("metadata") if isinstance(manifest, dict) else {}
        value = metadata.get("period") if isinstance(metadata, dict) else None
        if value:
            return self._normalize_period(value)
        # Rotinas mensais e de fechamento já têm semântica própria mesmo nos
        # manifestos antigos que não gravavam metadata.period.
        return "fechado" if str(routine) in {"03114902_MENSAL_LIGA", "1706_BI_INDICADORES_FECHAMENTO"} else "atual"

    def _read_rows(self, path: Path) -> Iterable[dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet in workbook.worksheets:
                    values = sheet.iter_rows(values_only=True)
                    headers = [self._clean_header(value, index) for index, value in enumerate(next(values, ()), start=1)]
                    if not any(headers):
                        continue
                    for values_row in values:
                        row = {headers[index]: self._json_value(value) for index, value in enumerate(values_row) if index < len(headers) and headers[index]}
                        if any(value not in (None, "") for value in row.values()):
                            yield row
            finally:
                workbook.close()
            return
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        if not lines:
            return
        delimiter = self._delimiter(lines[0])
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        for raw in reader:
            row = {self._clean_header(key, index): self._json_value(value) for index, (key, value) in enumerate(raw.items(), start=1) if key}
            if any(value not in (None, "") for value in row.values()):
                yield row

    @staticmethod
    def _delimiter(line: str) -> str:
        candidates = [";", "\t", ",", "|"]
        return max(candidates, key=lambda item: line.count(item))

    @staticmethod
    def _clean_header(value: Any, index: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        return text or f"coluna_{index}"

    @staticmethod
    def _json_value(value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value).strip() if isinstance(value, str) else value
