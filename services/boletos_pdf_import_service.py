from __future__ import annotations

import hashlib
import io
import os
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream
import pypdfium2 as pdfium

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.import_publication import activate_import_batch, prune_import_batches

try:
    import pytesseract
except Exception:  # pragma: no cover - dependency/runtime validation reports this.
    pytesseract = None  # type: ignore[assignment]


EXPECTED_EXTENSION_SET = {".pdf"}
DATASET_NAME = "boletos_bradesco"
DATASET_NAME_PREFIX = "boletos_bradesco_op_"
OCR_SAMPLE_PAGES = 3
DEFAULT_OCR_WORKERS = 2


@dataclass(frozen=True)
class BoletosPdfValidationResult:
    dataset_name: str
    source_path: str
    ok: bool
    pages: int
    sample_pages_checked: int
    sample_pages_with_nb: int
    sample_pages_with_document: int
    error_count: int
    warning_count: int
    sample_errors: list[str]
    sample_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def ensure_valid(self) -> None:
        if self.error_count:
            raise ValueError("; ".join(self.sample_errors) if self.sample_errors else "Erros na validacao dos boletos.")


@dataclass(frozen=True)
class BoletosPdfImportSummary:
    source_path: str
    pages: int
    sample_pages_checked: int
    sample_pages_with_nb: int
    sample_pages_with_document: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BoletoExtractedPage:
    page_number: int
    raw_text: str
    nb: str
    mapa: str
    nota_fiscal: str
    num_documento: str
    document: str
    payer_name: str
    document_date: date | None
    due_date: date | None
    amount_cents: int
    nosso_numero: str
    linha_digitavel: str
    pdf_bytes: bytes


@dataclass(frozen=True)
class BoletoResolvedRow:
    page_number: int
    status: str
    match_reason: str
    filial: str
    cod_pdv: str
    mapa: str
    nota_fiscal: str
    num_documento: str
    filial_setor_key: str
    filial_gv_key: str
    setor: str
    gv: str
    document: str
    payer_name: str
    document_date: date | None
    due_date: date | None
    amount_cents: int
    nosso_numero: str
    linha_digitavel: str
    pdf_bytes: bytes
    raw_text: str


@dataclass(frozen=True)
class ClientIndex:
    by_document: dict[str, list[dict[str, Any]]]
    by_nb: dict[str, list[dict[str, Any]]]


class BoletosPdfImportService:
    def __init__(
        self,
        database_url: str,
        schema: str,
        connect_timeout_seconds: float = 3.0,
        *,
        dataset_name: str = DATASET_NAME,
        expected_filial: str = "",
    ) -> None:
        self.database_url = database_url.strip()
        self.schema = _normalize_schema(schema)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self.dataset_name = str(dataset_name or DATASET_NAME).strip().lower()
        self.expected_filial = normalize_numeric_code(expected_filial)

    def validate_source(self, source_path: Path) -> BoletosPdfValidationResult:
        path = source_path.expanduser().resolve()
        errors: list[str] = []
        warnings: list[str] = []
        pages = 0
        checked = 0
        with_nb = 0
        with_document = 0

        if not path.exists():
            errors.append(f"Arquivo nao encontrado: {path}")
        elif path.suffix.lower() not in EXPECTED_EXTENSION_SET:
            errors.append("Formato invalido. Use um arquivo .pdf.")
        elif pytesseract is None:
            errors.append("OCR indisponivel. Instale pytesseract e tesseract-ocr no container.")
        else:
            try:
                pages = _pdf_page_count(path)
                if pages <= 0:
                    errors.append("PDF sem paginas.")
                else:
                    for page_number in range(1, min(pages, OCR_SAMPLE_PAGES) + 1):
                        checked += 1
                        text = _ocr_pdf_page(path, page_number)
                        if _extract_nb(text):
                            with_nb += 1
                        if _extract_document(text):
                            with_document += 1
                    if checked and not with_nb:
                        warnings.append("Nao encontrei NB nas paginas de amostra; a importacao tentara resolver pelo CPF/CNPJ.")
                    if checked and not with_document:
                        errors.append("Nao encontrei CPF/CNPJ nas paginas de amostra.")
            except Exception as exc:
                errors.append(str(exc))

        return BoletosPdfValidationResult(
            dataset_name=self.dataset_name,
            source_path=str(path),
            ok=not errors,
            pages=pages,
            sample_pages_checked=checked,
            sample_pages_with_nb=with_nb,
            sample_pages_with_document=with_document,
            error_count=len(errors),
            warning_count=len(warnings),
            sample_errors=errors[:10],
            sample_warnings=warnings[:10],
        )

    def summarize_source(self, source_path: Path) -> BoletosPdfImportSummary:
        validation = self.validate_source(source_path)
        validation.ensure_valid()
        return BoletosPdfImportSummary(
            source_path=str(source_path),
            pages=validation.pages,
            sample_pages_checked=validation.sample_pages_checked,
            sample_pages_with_nb=validation.sample_pages_with_nb,
            sample_pages_with_document=validation.sample_pages_with_document,
        )

    def import_source(self, source_path: Path, reference_date: date | None = None) -> dict[str, Any]:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        path = source_path.expanduser().resolve()
        validation = self.validate_source(path)
        validation.ensure_valid()
        pages = validation.pages
        batch_date = reference_date or datetime.fromtimestamp(path.stat().st_mtime).date()
        file_hash = _sha256(path)

        extracted_rows = _extract_pdf_pages(path)
        with self._connect() as conn:
            self._ensure_schema(conn)
            clients = self._load_clients(conn)
            if self.expected_filial:
                clients = [client for client in clients if normalize_numeric_code(client.get("filial")) == self.expected_filial]
            client_index = _build_client_index(clients)
            resolved_rows = [_resolve_boleto(row, client_index, expected_filial=self.expected_filial) for row in extracted_rows]
            batch_id = self._insert_batch(conn, str(path), batch_date, file_hash, len(resolved_rows))
            self._insert_pdf_source(conn, batch_id, path.read_bytes())
            self._insert_snapshot_rows(conn, batch_id, resolved_rows)
            revenda_pdf_count = self._insert_revenda_pdfs(conn, batch_id, path, resolved_rows)
            activate_import_batch(conn, self.schema, self.dataset_name, batch_id)
            self._create_latest_view(conn)
            prune_import_batches(conn, self.schema, self.dataset_name, keep_last=3)
            conn.commit()

        imported = len(resolved_rows)
        matched = sum(1 for row in resolved_rows if row.status == "ok")
        without_match = sum(1 for row in resolved_rows if row.status == "sem_match")
        ambiguous = sum(1 for row in resolved_rows if row.status == "ambiguo")
        return {
            "source_path": str(path),
            "batch_id": batch_id,
            "dataset_name": self.dataset_name,
            "filial": self.expected_filial,
            "reference_date": batch_date.isoformat(),
            "source_hash": file_hash,
            "schema": self.schema,
            "pages": pages,
            "imported": imported,
            "matched": matched,
            "without_match": without_match,
            "ambiguous": ambiguous,
            "revenda_pdfs": revenda_pdf_count,
            "published_as_active_batch": True,
        }

    def refresh_latest_view(self) -> dict[str, Any]:
        with self._connect() as conn:
            self._ensure_schema(conn)
            self._create_latest_view(conn)
            conn.commit()
        return {"ok": True, "schema": self.schema, "view": f"{self.schema}.boletos_latest"}

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url, connect_timeout=int(self.connect_timeout_seconds))

    def _ensure_schema(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.import_batches (
                        id BIGSERIAL PRIMARY KEY,
                        dataset_name VARCHAR(80) NOT NULL,
                        source_file TEXT NOT NULL,
                        file_hash VARCHAR(64) NOT NULL,
                        reference_date DATE,
                        total_rows INTEGER NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.boletos_pdf_source (
                        batch_id BIGINT PRIMARY KEY REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        pdf_bytes BYTEA NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.boletos_revenda_pdf (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        filial VARCHAR(16) NOT NULL,
                        total_boletos INTEGER NOT NULL DEFAULT 0,
                        total_valor_centavos BIGINT NOT NULL DEFAULT 0,
                        data_inicial DATE,
                        data_final DATE,
                        pdf_bytes BYTEA NOT NULL,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, filial)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            cur.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.boletos_snapshot (
                        batch_id BIGINT NOT NULL REFERENCES {}.import_batches(id) ON DELETE CASCADE,
                        page_number INTEGER NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        match_reason TEXT NOT NULL DEFAULT '',
                        filial VARCHAR(16) NOT NULL DEFAULT '',
                        cod_pdv VARCHAR(32) NOT NULL DEFAULT '',
                        mapa TEXT NOT NULL DEFAULT '',
                        nota_fiscal TEXT NOT NULL DEFAULT '',
                        num_documento TEXT NOT NULL DEFAULT '',
                        filial_setor_key TEXT NOT NULL DEFAULT '',
                        filial_gv_key TEXT NOT NULL DEFAULT '',
                        setor VARCHAR(32) NOT NULL DEFAULT '',
                        gv VARCHAR(32) NOT NULL DEFAULT '',
                        documento TEXT NOT NULL DEFAULT '',
                        pagador TEXT NOT NULL DEFAULT '',
                        data_documento DATE,
                        vencimento DATE,
                        valor_centavos BIGINT NOT NULL DEFAULT 0,
                        nosso_numero TEXT NOT NULL DEFAULT '',
                        linha_digitavel TEXT NOT NULL DEFAULT '',
                        pdf_bytes BYTEA NOT NULL,
                        ocr_text TEXT NOT NULL DEFAULT '',
                        payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (batch_id, page_number)
                    )
                    """
                ).format(sql.Identifier(self.schema), sql.Identifier(self.schema))
            )
            for column_sql in (
                "ALTER TABLE {}.boletos_snapshot ADD COLUMN IF NOT EXISTS mapa TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE {}.boletos_snapshot ADD COLUMN IF NOT EXISTS nota_fiscal TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE {}.boletos_snapshot ADD COLUMN IF NOT EXISTS num_documento TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE {}.boletos_snapshot ADD COLUMN IF NOT EXISTS data_documento DATE",
            ):
                cur.execute(sql.SQL(column_sql).format(sql.Identifier(self.schema)))
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS boletos_snapshot_doc_idx ON {}.boletos_snapshot (documento)").format(
                    sql.Identifier(self.schema)
                )
            )
            cur.execute(
                sql.SQL("CREATE INDEX IF NOT EXISTS boletos_snapshot_filial_nb_idx ON {}.boletos_snapshot (filial, cod_pdv)").format(
                    sql.Identifier(self.schema)
                )
            )

    def _insert_batch(self, conn: psycopg.Connection[Any], source_file: str, reference_date: date, file_hash: str, rows: int) -> int:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.import_batches (dataset_name, source_file, file_hash, reference_date, total_rows)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """
                ).format(sql.Identifier(self.schema)),
                (self.dataset_name, source_file, file_hash, reference_date, rows),
            )
            return int(cur.fetchone()[0])

    def _insert_pdf_source(self, conn: psycopg.Connection[Any], batch_id: int, pdf_bytes: bytes) -> None:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.boletos_pdf_source (batch_id, pdf_bytes)
                    VALUES (%s, %s)
                    """
                ).format(sql.Identifier(self.schema)),
                (batch_id, pdf_bytes),
            )

    def _load_clients(self, conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
        query = sql.SQL(
            """
            SELECT filial, cod_pdv, documento, nome_fantasia, razao_social, setor_vde, gv_vde_resolved, filial_setor_key, filial_gv_key
            FROM {}.dclientes_latest
            WHERE COALESCE(documento, '') <> '' OR COALESCE(cod_pdv, '') <> ''
            """
        ).format(sql.Identifier(self.schema))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]

    def _insert_snapshot_rows(self, conn: psycopg.Connection[Any], batch_id: int, rows: list[BoletoResolvedRow]) -> None:
        with conn.cursor() as cur:
            insert_sql = sql.SQL(
                """
                INSERT INTO {}.boletos_snapshot (
                    batch_id, page_number, status, match_reason, filial, cod_pdv, filial_setor_key, filial_gv_key,
                    mapa, nota_fiscal, num_documento, setor, gv, documento, pagador, data_documento,
                    vencimento, valor_centavos, nosso_numero, linha_digitavel,
                    pdf_bytes, ocr_text, payload
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
            ).format(sql.Identifier(self.schema))
            cur.executemany(
                insert_sql,
                [
                    (
                        batch_id,
                        row.page_number,
                        row.status,
                        row.match_reason,
                        row.filial,
                        row.cod_pdv,
                        row.filial_setor_key,
                        row.filial_gv_key,
                        row.mapa,
                        row.nota_fiscal,
                        row.num_documento,
                        row.setor,
                        row.gv,
                        row.document,
                        row.payer_name,
                        row.document_date,
                        row.due_date,
                        row.amount_cents,
                        row.nosso_numero,
                        row.linha_digitavel,
                        row.pdf_bytes,
                        row.raw_text,
                        Jsonb(
                            {
                                "ocr_document": row.document,
                                "ocr_nb": row.cod_pdv,
                                "mapa": row.mapa,
                                "nota_fiscal": row.nota_fiscal,
                                "num_documento": row.num_documento,
                                "data_documento": row.document_date.isoformat() if row.document_date else "",
                                "status": row.status,
                                "match_reason": row.match_reason,
                            }
                        ),
                    )
                    for row in rows
                ],
            )

    def _insert_revenda_pdfs(self, conn: psycopg.Connection[Any], batch_id: int, source_path: Path, rows: list[BoletoResolvedRow]) -> int:
        groups: dict[str, list[BoletoResolvedRow]] = {}
        for row in rows:
            if row.status == "ok" and row.filial:
                groups.setdefault(row.filial, []).append(row)
        if not groups:
            return 0

        reader = PdfReader(str(source_path))
        payloads: list[tuple[Any, ...]] = []
        for filial, filial_rows in sorted(groups.items(), key=lambda item: normalize_numeric_code(item[0])):
            writer = PdfWriter()
            for row in sorted(filial_rows, key=lambda item: item.page_number):
                page_index = row.page_number - 1
                if 0 <= page_index < len(reader.pages):
                    writer.add_page(reader.pages[page_index])
            buffer = io.BytesIO()
            writer.write(buffer)
            due_dates = [row.due_date for row in filial_rows if row.due_date]
            payloads.append(
                (
                    batch_id,
                    filial,
                    len(filial_rows),
                    sum(row.amount_cents for row in filial_rows),
                    min(due_dates) if due_dates else None,
                    max(due_dates) if due_dates else None,
                    buffer.getvalue(),
                )
            )

        with conn.cursor() as cur:
            cur.executemany(
                sql.SQL(
                    """
                    INSERT INTO {}.boletos_revenda_pdf (
                        batch_id, filial, total_boletos, total_valor_centavos,
                        data_inicial, data_final, pdf_bytes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """
                ).format(sql.Identifier(self.schema)),
                payloads,
            )
        return len(payloads)

    def _create_latest_view(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    CREATE OR REPLACE VIEW {}.boletos_latest AS
                    SELECT s.*
                    FROM {}.boletos_snapshot s
                    JOIN {}.dataset_state st ON st.active_batch_id = s.batch_id
                    WHERE st.dataset_name LIKE {}
                       OR (
                           st.dataset_name = {}
                           AND NOT EXISTS (
                               SELECT 1
                               FROM {}.dataset_state active_boletos
                               WHERE active_boletos.dataset_name LIKE {}
                           )
                       )
                    """
                ).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                    sql.Identifier(self.schema),
                    sql.Literal(f"{DATASET_NAME_PREFIX}%"),
                    sql.Literal(DATASET_NAME),
                    sql.Identifier(self.schema),
                    sql.Literal(f"{DATASET_NAME_PREFIX}%"),
                )
            )


def _extract_pdf_pages(path: Path) -> list[BoletoExtractedPage]:
    if pytesseract is None:
        raise RuntimeError("OCR indisponivel. pytesseract nao esta instalado.")
    pdf_doc = pdfium.PdfDocument(str(path))
    pages = len(pdf_doc)
    workers = _ocr_worker_count()
    if workers <= 1:
        return [_extract_single_pdf_page(path, index) for index in range(pages)]
    jobs = [(str(path), index) for index in range(pages)]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_extract_single_pdf_page_from_job, jobs))


def _extract_single_pdf_page_from_job(job: tuple[str, int]) -> BoletoExtractedPage:
    path, page_index = job
    return _extract_single_pdf_page(Path(path), page_index)


def _extract_single_pdf_page(path: Path, page_index: int) -> BoletoExtractedPage:
    pdf_doc = pdfium.PdfDocument(str(path))
    page_number = page_index + 1
    text = _extract_text_page(path, page_index)
    if not _text_extraction_is_enough(text):
        text = _ocr_rendered_page(pdf_doc[page_index])
    return BoletoExtractedPage(
        page_number=page_number,
        raw_text=text,
        nb=_extract_nb(text),
        mapa=_extract_mapa(text),
        nota_fiscal=_extract_nota_fiscal(text),
        num_documento=_extract_num_documento(text),
        document=_extract_document(text),
        payer_name=_extract_payer_name(text),
        document_date=_extract_document_date(text),
        due_date=_extract_due_date(text),
        amount_cents=_extract_amount_cents(text),
        nosso_numero=_extract_nosso_numero(text),
        linha_digitavel=_extract_linha_digitavel(text),
        pdf_bytes=b"",
    )


def _text_extraction_is_enough(text: str) -> bool:
    if not text.strip():
        return False
    has_boleto_identity = bool(_extract_linha_digitavel(text) or _extract_nosso_numero(text))
    has_customer_identity = bool(_extract_document(text) or _extract_nb(text))
    return has_boleto_identity and has_customer_identity


def _extract_text_page(path: Path, page_index: int) -> str:
    reader = PdfReader(str(path))
    page = reader.pages[page_index]
    contents = page.get_contents()
    if contents is None:
        return ""
    content_stream = ContentStream(contents, reader)
    current_font = ""
    chunks: list[str] = []
    for operands, operator in content_stream.operations:
        if operator == b"Tf" and operands:
            current_font = str(operands[0])
            continue
        if current_font not in {"/R12", "/R8"}:
            continue
        if operator == b"Tj" and operands:
            chunks.append(str(operands[0]))
        elif operator == b"TJ" and operands:
            chunks.append("".join(str(item) for item in operands[0] if isinstance(item, str)))
    return "\n".join(chunks)


def _ocr_worker_count() -> int:
    raw = os.getenv("BOLETOS_OCR_WORKERS", str(DEFAULT_OCR_WORKERS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_OCR_WORKERS
    return max(1, min(value, 4))


def _ocr_pdf_page(path: Path, page_number: int) -> str:
    if pytesseract is None:
        raise RuntimeError("OCR indisponivel. pytesseract nao esta instalado.")
    pdf = pdfium.PdfDocument(str(path))
    return _ocr_rendered_page(pdf[page_number - 1])


def _ocr_rendered_page(page: Any) -> str:
    image = page.render(scale=1.7).to_pil()
    width, height = image.size
    # O boleto tem layout fixo: ler apenas as faixas com linha digitavel,
    # vencimento/valor e dados do pagador evita OCR caro no PDF inteiro.
    boxes = (
        (int(width * 0.70), int(height * 0.16), width, int(height * 0.245)),
        (0, int(height * 0.34), width, int(height * 0.43)),
    )
    parts: list[str] = []
    for box in boxes:
        crop = image.crop(box)
        gray = crop.convert("L")
        prepared = gray.point(lambda value: 255 if value > 175 else 0)
        parts.append(pytesseract.image_to_string(prepared, lang="por+eng", config="--psm 6"))
    return "\n".join(parts)


def _pdf_page_count(path: Path) -> int:
    reader = PdfReader(str(path))
    return len(reader.pages)


def _build_client_index(clients: list[dict[str, Any]]) -> ClientIndex:
    by_document: dict[str, list[dict[str, Any]]] = {}
    by_nb: dict[str, list[dict[str, Any]]] = {}
    for client in clients:
        document = _normalize_document(client.get("documento"))
        nb = normalize_numeric_code(client.get("cod_pdv"))
        if document:
            by_document.setdefault(document, []).append(client)
        if nb:
            by_nb.setdefault(nb, []).append(client)
    return ClientIndex(by_document=by_document, by_nb=by_nb)


def _resolve_boleto(row: BoletoExtractedPage, clients: ClientIndex, *, expected_filial: str = "") -> BoletoResolvedRow:
    document = _normalize_document(row.document)
    nb = normalize_numeric_code(row.nb)
    candidates: list[dict[str, Any]] = []
    if document:
        candidates = list(clients.by_document.get(document, []))
    if nb:
        nb_candidates = list(clients.by_nb.get(nb, []))
        if candidates:
            narrowed = [client for client in candidates if normalize_numeric_code(client.get("cod_pdv")) == nb]
            if narrowed:
                candidates = narrowed
        else:
            candidates = nb_candidates

    status = "sem_match"
    reason = "documento/nb nao localizado na dclientes"
    selected: dict[str, Any] | None = None
    if len(candidates) == 1:
        selected = candidates[0]
        status = "ok"
        reason = "documento+nb" if document and nb else "documento" if document else "nb"
    elif len(candidates) > 1:
        status = "ambiguo"
        reason = f"{len(candidates)} clientes possiveis na dclientes"

    payer_name = row.payer_name if _is_valid_payer_name(row.payer_name) else ""
    if not payer_name:
        payer_name = str((selected or {}).get("nome_fantasia") or (selected or {}).get("razao_social") or "")
    return BoletoResolvedRow(
        page_number=row.page_number,
        status=status,
        match_reason=reason,
        filial=str((selected or {}).get("filial") or expected_filial),
        cod_pdv=str((selected or {}).get("cod_pdv") or nb),
        mapa=row.mapa,
        nota_fiscal=row.nota_fiscal,
        num_documento=row.num_documento,
        filial_setor_key=str((selected or {}).get("filial_setor_key") or ""),
        filial_gv_key=str((selected or {}).get("filial_gv_key") or ""),
        setor=str((selected or {}).get("setor_vde") or ""),
        gv=str((selected or {}).get("gv_vde_resolved") or ""),
        document=document,
        payer_name=payer_name,
        document_date=row.document_date,
        due_date=row.due_date,
        amount_cents=row.amount_cents,
        nosso_numero=row.nosso_numero,
        linha_digitavel=row.linha_digitavel,
        pdf_bytes=row.pdf_bytes,
        raw_text=row.raw_text[:12000],
    )


def _extract_nb(text: str) -> str:
    patterns = [
        r"CLIENTE\s*[:\-]?\s*(\d{3,8})",
        r"SACADO\s+(\d{3,8})\s*[-–]",
        r"Pagador.*?\n\s*(\d{3,8})\s+",
        r"(?m)^\s*(\d{3,8})\s+[A-Z][A-Z0-9 .,&'/-]{3,}\s*[-+]\s*(?:CPF|CNPJ|GPF|\$PF)\s*:",
        r"\b(\d{3,8})-\1[A-Z0-9]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return normalize_numeric_code(match.group(1))
    return ""


def _extract_mapa(text: str) -> str:
    match = re.search(r"MAPA\s*:?\s*(\d{3,12})", text, flags=re.IGNORECASE)
    if match:
        return normalize_numeric_code(match.group(1))
    match = re.search(r"NOTAFISCAL.*?NOSSON[ÚU]MERO.*?(\d{3,12})", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return normalize_numeric_code(match.group(1))
    return ""


def _extract_num_documento(text: str) -> str:
    patterns = [
        r"\b\d{2}/\d{2}/\d{4}\s*(\d{5,12})\s*DMN",
        r"\b(\d{5,12})\s*DMN",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return normalize_numeric_code(match.group(1))
    return ""


def _extract_nota_fiscal(text: str) -> str:
    number = _extract_num_documento(text)
    if number.endswith("00") and len(number) > 2:
        number = number[:-2]
    return number


def _extract_document(text: str) -> str:
    documents: list[str] = []
    for match in re.finditer(r"\b(?:CPF|CNPJ|GPF|\$PF)\s*[:\-]?\s*([0-9.\-/\s]{11,24})", text, flags=re.IGNORECASE):
        clean = _normalize_document(match.group(1))
        if len(clean) in {11, 14} and not _is_beneficiary_document(clean):
            documents.append(clean)
    for candidate in re.findall(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", text):
        clean = _normalize_document(candidate)
        if len(clean) in {11, 14} and not _is_beneficiary_document(clean):
            documents.append(clean)
    if documents:
        return documents[-1]
    return ""


def _extract_document_date(text: str) -> date | None:
    match = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\s*\d{5,12}\s*DMN", text, flags=re.IGNORECASE)
    if match:
        day, month, year = match.groups()
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None
    dates = _extract_dates(text)
    return dates[0] if dates else None


def _extract_payer_name(text: str) -> str:
    match = re.search(r"Nome do Pagador.*?\n\s*(.+?)\s+-\s+(?:CPF|CNPJ|GPF|\$PF)", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return _clean_text(match.group(1))[:120]
    match = re.search(r"\b\d{3,8}\s+(.+?)\s*[-+]\s+(?:CPF|CNPJ|GPF|\$PF)\s*:", text, flags=re.IGNORECASE)
    if match:
        return _clean_text(match.group(1))[:120]
    match = re.search(r"SACADO\s+\d+\s*[-–]\s*(.+)", text, flags=re.IGNORECASE)
    if match:
        return _clean_text(match.group(1))[:120]
    return ""


def _extract_due_date(text: str) -> date | None:
    dates = _extract_dates(text)
    return max(dates) if dates else None


def _extract_dates(text: str) -> list[date]:
    dates: list[date] = []
    for day, month, year in re.findall(r"\b(\d{2})/(\d{2})/(\d{4})\b", text):
        try:
            dates.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return dates


def _extract_amount_cents(text: str) -> int:
    for raw in re.findall(r"\b237[0-9.\s]{30,80}\b", text):
        digits = re.sub(r"\D+", "", raw)
        if len(digits) >= 44:
            try:
                value = int(digits[-10:])
            except ValueError:
                continue
            if value > 0:
                return value
    values: list[int] = []
    for raw in re.findall(r"\b\d{1,3}(?:\.\d{3})*[,.]\d{2}\b", text):
        clean = raw.replace(".", "").replace(",", "")
        try:
            values.append(int(clean))
        except ValueError:
            continue
    if not values:
        for raw in re.findall(r"\b\d{13,14}\b", text):
            if not raw.startswith("1"):
                continue
            try:
                value = int(raw[4:])
            except ValueError:
                continue
            if value > 0:
                values.append(value)
    return max(values) if values else 0


def _extract_nosso_numero(text: str) -> str:
    match = re.search(r"\b09\s*/?\s*([0-9]{8,14})\s*[- ]\s*([0-9XxPp])\b", text)
    if match:
        return f"09/{match.group(1)}-{match.group(2).upper()}"
    return ""


def _extract_linha_digitavel(text: str) -> str:
    match = re.search(r"\b237[0-9.\s]{35,60}\b", text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(0)).strip()


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_valid_payer_name(value: Any) -> bool:
    text = _clean_text(value)
    return len(text) >= 4 and bool(re.search(r"[A-Za-zÁ-Úá-ú]", text))


def _normalize_document(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _is_beneficiary_document(value: str) -> bool:
    # CNPJs da distribuidora aparecem antes do pagador no boleto e nao devem guiar o match do cliente.
    return str(value or "").startswith("20983885")


def _normalize_schema(value: str) -> str:
    normalized = str(value or "reports").strip() or "reports"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
        raise ValueError(f"Schema invalido: {value!r}")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
