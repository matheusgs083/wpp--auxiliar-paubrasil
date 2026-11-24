from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


_REQUIRED_COLUMNS = {
    "codigoproduto": "codigo_produto",
    "descricaoproduto": "descricao_produto",
    "unidademedida": "unidade_medida",
    "gradeestoque": "grade_estoque",
    "gradecadastrada": "grade_cadastrada",
    "reserva": "reserva",
    "saida": "saida",
    "saldodisponivel": "saldo_disponivel",
}


def _identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", str(value or ""))
    return cleaned or "reports"


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower().translate(str.maketrans("áàãâéêíóôõúç", "aaaaeeiooouc")))


def _code(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw.lstrip("0") or "0"


def _number(value: Any) -> Decimal:
    raw = str(value or "").strip().replace(" ", "")
    if not raw:
        return Decimal("0")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Valor numérico inválido no estoque: {value!r}.") from exc


class CoraEstoqueImportService:
    """Recebe a grade Stock_Product do Cora por upload manual.

    A importação não chama o Cora. Cada envio forma um lote auditável e a
    consulta sempre usa o último lote recebido para a filial.
    """

    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "").strip()
        self.schema = _identifier(schema)
        self.connect_timeout_seconds = max(int(connect_timeout_seconds or 3), 1)

    def import_csv(self, *, filial: str, filename: str, content: bytes) -> dict[str, Any]:
        filial = str(filial or "").strip().lstrip("0") or "0"
        if not filial.isdigit():
            raise ValueError("Filial do estoque deve ser numérica.")
        if not content:
            raise ValueError("Envie o CSV Stock_Product do Cora.")
        if len(content) > 20 * 1024 * 1024:
            raise ValueError("O arquivo de estoque excede 20 MB.")
        rows = self.parse_csv(content)
        if not rows:
            raise ValueError("O CSV Stock_Product não possui produtos válidos.")
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL não configurada.")

        imported_at = datetime.now(timezone.utc)
        digest = hashlib.sha256(content).hexdigest()
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("""
                        INSERT INTO {}.cora_estoque_batches
                            (filial, source_name, file_hash, total_items, imported_at)
                        VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """).format(sql.Identifier(self.schema)),
                    (filial, str(filename or "STOCK_PRODUCT.csv"), digest, len(rows), imported_at),
                )
                batch_id = int(cur.fetchone()["id"])
                cur.executemany(
                    sql.SQL("""
                        INSERT INTO {}.cora_estoque_items
                            (batch_id, filial, codigo_produto, descricao_produto, unidade_medida,
                             grade_estoque, grade_cadastrada, reserva, saida, saldo_disponivel)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """).format(sql.Identifier(self.schema)),
                    [
                        (batch_id, filial, row["codigo_produto"], row["descricao_produto"], row["unidade_medida"],
                         row["grade_estoque"], row["grade_cadastrada"], row["reserva"], row["saida"], row["saldo_disponivel"])
                        for row in rows
                    ],
                )
            conn.commit()
        return {"ok": True, "batch_id": batch_id, "filial": filial, "source_name": filename, "items": len(rows), "imported_at": imported_at.isoformat()}

    def parse_csv(self, content: bytes) -> list[dict[str, Any]]:
        text = _decode(content)
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        aliases = {_header(name): name for name in (reader.fieldnames or [])}
        missing = [source for source in _REQUIRED_COLUMNS if source not in aliases]
        if missing:
            raise ValueError("CSV inválido. Colunas obrigatórias: " + ", ".join(_REQUIRED_COLUMNS.values()) + ".")
        products: dict[str, dict[str, Any]] = {}
        for line, source in enumerate(reader, start=2):
            codigo = _code(source.get(aliases["codigoproduto"]))
            descricao = str(source.get(aliases["descricaoproduto"]) or "").strip()
            if not codigo or codigo == "0" or not descricao:
                continue
            if codigo in products:
                raise ValueError(f"Produto {codigo} repetido na linha {line} do CSV.")
            products[codigo] = {
                "codigo_produto": codigo,
                "descricao_produto": descricao,
                "unidade_medida": str(source.get(aliases["unidademedida"]) or "").strip(),
                "grade_estoque": _number(source.get(aliases["gradeestoque"])),
                "grade_cadastrada": _number(source.get(aliases["gradecadastrada"])),
                "reserva": _number(source.get(aliases["reserva"])),
                "saida": _number(source.get(aliases["saida"])),
                "saldo_disponivel": _number(source.get(aliases["saldodisponivel"])),
            }
        return list(products.values())

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)

    def _ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {}.cora_estoque_batches (
                    id BIGSERIAL PRIMARY KEY, filial VARCHAR(16) NOT NULL,
                    source_name TEXT NOT NULL, file_hash VARCHAR(64) NOT NULL,
                    total_items INTEGER NOT NULL, imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """).format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {}.cora_estoque_items (
                    batch_id BIGINT NOT NULL REFERENCES {}.cora_estoque_batches(id) ON DELETE CASCADE,
                    filial VARCHAR(16) NOT NULL, codigo_produto VARCHAR(32) NOT NULL,
                    descricao_produto TEXT NOT NULL, unidade_medida VARCHAR(40) NOT NULL DEFAULT '',
                    grade_estoque NUMERIC NOT NULL DEFAULT 0, grade_cadastrada NUMERIC NOT NULL DEFAULT 0,
                    reserva NUMERIC NOT NULL DEFAULT 0, saida NUMERIC NOT NULL DEFAULT 0,
                    saldo_disponivel NUMERIC NOT NULL DEFAULT 0,
                    PRIMARY KEY (batch_id, codigo_produto)
                )
            """).format(sql.Identifier(self.schema), sql.Identifier(self.schema)))
            cur.execute(sql.SQL("CREATE INDEX IF NOT EXISTS cora_estoque_batches_filial_idx ON {}.cora_estoque_batches (filial, imported_at DESC)").format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL("CREATE INDEX IF NOT EXISTS cora_estoque_items_batch_codigo_idx ON {}.cora_estoque_items (batch_id, codigo_produto)").format(sql.Identifier(self.schema)))


class CoraEstoqueQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "").strip()
        self.schema = _identifier(schema)
        self.connect_timeout_seconds = max(int(connect_timeout_seconds or 3), 1)

    def dashboard(self, *, filial: str, search: str = "", limit: int = 100) -> dict[str, Any]:
        batch = self._latest_batch(filial)
        if not batch:
            return {"ready": False, "filial": str(filial), "items": [], "summary": {"produtos": 0, "saldo_disponivel": "0"}}
        terms = f"%{str(search or '').strip()}%"
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL("""
                SELECT codigo_produto, descricao_produto, unidade_medida, grade_estoque, grade_cadastrada, reserva, saida, saldo_disponivel
                FROM {}.cora_estoque_items
                WHERE batch_id = %s AND (%s = '%%' OR codigo_produto ILIKE %s OR descricao_produto ILIKE %s)
                ORDER BY descricao_produto LIMIT %s
            """).format(sql.Identifier(self.schema)), (batch["id"], terms, terms, terms, max(1, min(int(limit), 500))))
            items = [_serialize_row(row) for row in cur.fetchall()]
            cur.execute(sql.SQL("SELECT COUNT(*) AS produtos, COALESCE(SUM(saldo_disponivel), 0) AS saldo FROM {}.cora_estoque_items WHERE batch_id = %s").format(sql.Identifier(self.schema)), (batch["id"],))
            summary = cur.fetchone() or {}
        return {"ready": True, "filial": str(filial), "batch": _serialize_row(batch), "items": items, "summary": {"produtos": int(summary.get("produtos") or 0), "saldo_disponivel": str(summary.get("saldo") or 0)}}

    def availability(self, *, filial: str, products: Iterable[dict[str, Any]]) -> dict[str, Any]:
        batch = self._latest_batch(filial)
        if not batch:
            return {"ready": False, "reason": "Nenhuma grade Stock_Product foi importada para esta filial."}
        requested = {_code(item.get("produto")): int(item.get("quantidade") or 0) for item in products}
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL("SELECT codigo_produto, descricao_produto, unidade_medida, saldo_disponivel FROM {}.cora_estoque_items WHERE batch_id = %s AND codigo_produto = ANY(%s)").format(sql.Identifier(self.schema)), (batch["id"], list(requested)))
            found = {str(row["codigo_produto"]): row for row in cur.fetchall()}
        unavailable = []
        for code, quantity in requested.items():
            row = found.get(code)
            if not row:
                unavailable.append({"produto": code, "motivo": "Produto não consta na grade atual."})
            elif Decimal(str(row["saldo_disponivel"] or 0)) < quantity:
                unavailable.append({"produto": code, "descricao": str(row["descricao_produto"]), "saldo_disponivel": str(row["saldo_disponivel"]), "quantidade_solicitada": quantity, "motivo": "Saldo disponível insuficiente."})
        # Descrição e unidade de cada produto achado, para as travas da digitação (ex.: caixa fechada do 600).
        produtos = {code: {"descricao": str(row["descricao_produto"] or ""), "unidade": str(row["unidade_medida"] or "")} for code, row in found.items()}
        return {"ready": True, "ok": not unavailable, "batch": _serialize_row(batch), "indisponiveis": unavailable, "produtos": produtos}

    def _latest_batch(self, filial: str) -> dict[str, Any] | None:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL não configurada.")
        try:
            with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("SELECT id, filial, source_name, total_items, imported_at FROM {}.cora_estoque_batches WHERE filial = %s ORDER BY imported_at DESC, id DESC LIMIT 1").format(sql.Identifier(self.schema)), (str(filial),))
                return cur.fetchone()
        except psycopg.errors.UndefinedTable:
            return None

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Não foi possível ler o CSV como UTF-8 ou Latin-1.")


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: (value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, Decimal) else value) for key, value in row.items()}
