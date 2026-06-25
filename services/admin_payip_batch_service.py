from __future__ import annotations

import base64
import csv
import io
import re
import secrets
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from threading import Lock
from typing import Any

from fastapi import HTTPException

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.integrations.payip_client import PayipMfaRequired

MAX_PAYIP_BATCH_ITEMS = 100
DEFAULT_PAYIP_RATE_AMOUNT = Decimal("3.92")
DEFAULT_PAYIP_INTEREST_PERC = Decimal("10.00")
PAYIP_BATCH_DELAY_SECONDS = 0.8
PAYIP_PDF_ATTEMPTS = 5
PAYIP_PDF_RETRY_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class PayipBatchOptions:
    raw_text: str
    use_default_rate: bool = True
    use_default_interest: bool = True
    include_nb: bool = False
    include_nf: bool = False
    mfa_code: str = ""


class AdminPayipBatchService:
    def __init__(
        self,
        *,
        payip_payments_service: Any,
        panel_context_has_all_filiais: Any,
        logger: Any,
    ) -> None:
        self.payip_payments_service = payip_payments_service
        self.panel_context_has_all_filiais = panel_context_has_all_filiais
        self.logger = logger
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="admin-payip-batch")
        self.lock = Lock()
        self.state: dict[str, Any] = {
            "running": False,
            "current_job_id": "",
            "queued_at": "",
            "started_at": "",
            "finished_at": "",
            "total": 0,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "last_job": {},
        }
        self.jobs: dict[str, dict[str, Any]] = {}

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)

    def preview(self, payload: Any, context: dict[str, Any] | None) -> dict[str, Any]:
        options = _payload_options(payload)
        rows = self._parse_rows(options=options, context=context)
        return {
            "total": len(rows),
            "items": rows,
            "options": _options_payload(options),
        }

    def queue(self, payload: Any, context: dict[str, Any] | None) -> dict[str, Any]:
        options = _payload_options(payload)
        rows = self._parse_rows(options=options, context=context)
        if not rows:
            raise HTTPException(status_code=400, detail="Informe ao menos uma cobranca PayIP para gerar.")
        with self.lock:
            if self.state["running"]:
                raise HTTPException(status_code=409, detail="Ja existe um lote PayIP em processamento.")
            job_id = _new_job_id()
            queued_at = datetime.now(timezone.utc).isoformat()
            job = {
                "job_id": job_id,
                "status": "queued",
                "queued_at": queued_at,
                "started_at": "",
                "finished_at": "",
                "total": len(rows),
                "processed": 0,
                "success": 0,
                "failed": 0,
                "options": _options_payload(options),
                "_mfa_code": options.mfa_code,
                "items": rows,
                "results": [],
            }
            self.jobs[job_id] = job
            self.state.update(
                {
                    "running": True,
                    "current_job_id": job_id,
                    "queued_at": queued_at,
                    "started_at": "",
                    "finished_at": "",
                    "total": len(rows),
                    "processed": 0,
                    "success": 0,
                    "failed": 0,
                }
            )
        try:
            self.executor.submit(self._worker, job_id)
        except Exception as exc:
            with self.lock:
                self.state["running"] = False
                self.state["current_job_id"] = ""
                job["status"] = "failed"
                job["finished_at"] = datetime.now(timezone.utc).isoformat()
                job["error"] = str(exc)
            raise HTTPException(status_code=503, detail=f"Falha ao enfileirar lote PayIP: {exc}") from exc
        return self.snapshot(job_id=job_id)

    def snapshot(self, *, job_id: str | None = None) -> dict[str, Any]:
        with self.lock:
            state = dict(self.state)
            selected_job_id = str(job_id or state.get("current_job_id") or "").strip()
            selected = self.jobs.get(selected_job_id) if selected_job_id else state.get("last_job")
            job_payload = _public_job_payload(selected) if isinstance(selected, dict) else {}
        return {"state": state, "job": job_payload}

    def export_csv(self, *, job_id: str | None = None) -> tuple[bytes, str]:
        snapshot = self.snapshot(job_id=job_id)
        job = snapshot.get("job") if isinstance(snapshot, dict) else {}
        if not isinstance(job, dict) or not job.get("job_id"):
            raise HTTPException(status_code=404, detail="Nenhum lote PayIP encontrado para exportar.")
        rows = job.get("results") if isinstance(job.get("results"), list) else []
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["linha", "status", "revenda", "nb", "cliente", "valor", "vencimento", "payment_id", "pix_copia_cola", "erro"])
        for item in rows:
            writer.writerow(
                [
                    item.get("line_number", ""),
                    item.get("status", ""),
                    item.get("filial", ""),
                    item.get("nb", ""),
                    item.get("client_name", ""),
                    item.get("amount", ""),
                    item.get("due_date", ""),
                    item.get("payment_id", ""),
                    item.get("pix_code", ""),
                    item.get("error", ""),
                ]
            )
        filename = f"payip-lote-{job.get('job_id') or 'resultado'}.csv"
        return ("\ufeff" + buffer.getvalue()).encode("utf-8"), filename

    def pdf_bytes(self, item_id: str, *, job_id: str | None = None) -> tuple[bytes, str]:
        clean_item_id = str(item_id or "").strip()
        with self.lock:
            state = dict(self.state)
            selected_job_id = str(job_id or state.get("current_job_id") or "").strip()
            job = self.jobs.get(selected_job_id) if selected_job_id else self.jobs.get(str((state.get("last_job") or {}).get("job_id") or ""))
            rows = job.get("results") if isinstance(job, dict) and isinstance(job.get("results"), list) else []
            item = next((candidate for candidate in rows if str(candidate.get("item_id") or "") == clean_item_id), None)
            item_data = dict(item or {})
        if item_data:
            raw_pdf = str(item_data.get("pdf_base64") or "")
            if raw_pdf:
                return base64.b64decode(raw_pdf), f"payip-cobranca-{clean_item_id}.pdf"
            payment_id = str(item_data.get("payment_id") or "").strip()
            filial = str(item_data.get("filial") or "").strip()
            company_id = str(item_data.get("company_id") or "").strip()
            if not payment_id:
                raise HTTPException(status_code=404, detail="PDF PayIP ainda nao disponivel para este item.")
            pdf_bytes, pdf_error = self._generate_charge_pdf(filial=filial, company_id=company_id, payment_id=payment_id)
            if not pdf_bytes:
                detail = f"PDF PayIP ainda nao disponivel para este item: {pdf_error}" if pdf_error else "PDF PayIP ainda nao disponivel para este item."
                raise HTTPException(status_code=404, detail=detail)
            encoded_pdf = base64.b64encode(pdf_bytes).decode("ascii")
            with self.lock:
                if item is not None:
                    item["pdf_available"] = True
                    item["pdf_base64"] = encoded_pdf
                    if str(item.get("error") or "").startswith("PDF indisponivel:"):
                        item["error"] = ""
            return pdf_bytes, f"payip-cobranca-{clean_item_id}.pdf"
        raise HTTPException(status_code=404, detail="Item do lote PayIP nao encontrado.")

    def _parse_rows(self, *, options: PayipBatchOptions, context: dict[str, Any] | None) -> list[dict[str, Any]]:
        parsed = _parse_batch_text(options.raw_text)
        if len(parsed) > MAX_PAYIP_BATCH_ITEMS:
            raise HTTPException(status_code=400, detail=f"O lote PayIP permite no maximo {MAX_PAYIP_BATCH_ITEMS} cobrancas.")
        allowed_filiais = self._allowed_filiais(context)
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for row in parsed:
            try:
                item = _normalize_input_row(row, options=options)
                if allowed_filiais is not None and item["filial"] not in allowed_filiais:
                    raise ValueError("Revenda fora do escopo liberado para este painel.")
                rows.append(item)
            except ValueError as exc:
                errors.append(f"Linha {row.get('_line_number')}: {exc}")
        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors[:8]))
        return rows

    def _allowed_filiais(self, context: dict[str, Any] | None) -> set[str] | None:
        if not context or bool(context.get("is_admin")) or self.panel_context_has_all_filiais(context):
            return None
        allowed: set[str] = set()
        for filial in context.get("filiais", ()) or ():
            normalized = normalize_numeric_code(str(filial or ""))
            if normalized:
                allowed.add(normalized)
        return allowed

    def _worker(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["started_at"] = datetime.now(timezone.utc).isoformat()
            self.state["started_at"] = job["started_at"]

        rows = list(job.get("items") or [])
        mfa_error = self._bootstrap_mfa_for_job(job)
        if mfa_error:
            self._finish_job_with_error(job_id, rows, error=mfa_error)
            return

        for index, row in enumerate(rows, start=1):
            result = self._process_row(row)
            with self.lock:
                current = self.jobs.get(job_id)
                if not current:
                    return
                current.setdefault("results", []).append(result)
                current["processed"] = index
                if result["status"] == "success":
                    current["success"] = int(current.get("success") or 0) + 1
                else:
                    current["failed"] = int(current.get("failed") or 0) + 1
                self.state["processed"] = current["processed"]
                self.state["success"] = current["success"]
                self.state["failed"] = current["failed"]
            if index < len(rows) and PAYIP_BATCH_DELAY_SECONDS > 0:
                time.sleep(PAYIP_BATCH_DELAY_SECONDS)

        with self.lock:
            current = self.jobs.get(job_id)
            if current:
                current["status"] = "done"
                current["finished_at"] = datetime.now(timezone.utc).isoformat()
                self.state["last_job"] = _public_job_payload(current)
            self.state["running"] = False
            self.state["current_job_id"] = ""
            self.state["finished_at"] = datetime.now(timezone.utc).isoformat()

    def _bootstrap_mfa_for_job(self, job: dict[str, Any]) -> str:
        mfa_code = str(job.pop("_mfa_code", "") or "").strip()
        if not mfa_code:
            return ""
        try:
            self.payip_payments_service.bootstrap_session(mfa_code=mfa_code)
        except Exception as exc:
            self.logger.exception("Falha ao validar MFA PayIP para lote %s: %s", job.get("job_id"), exc)
            return f"Nao consegui validar o token MFA PayIP: {_short_error(str(exc))}"
        return ""

    def _finish_job_with_error(self, job_id: str, rows: list[dict[str, Any]], *, error: str) -> None:
        results = [_failed_result(row, error=error) for row in rows]
        finished_at = datetime.now(timezone.utc).isoformat()
        with self.lock:
            current = self.jobs.get(job_id)
            if current:
                current["status"] = "done"
                current["processed"] = len(rows)
                current["success"] = 0
                current["failed"] = len(rows)
                current["results"] = results
                current["finished_at"] = finished_at
                self.state["last_job"] = _public_job_payload(current)
            self.state.update(
                {
                    "running": False,
                    "current_job_id": "",
                    "processed": len(rows),
                    "success": 0,
                    "failed": len(rows),
                    "finished_at": finished_at,
                }
            )

    def _process_row(self, row: dict[str, Any]) -> dict[str, Any]:
        result = _failed_result(row, error="")
        try:
            if self.payip_payments_service is None:
                raise RuntimeError("PayIP nao configurada.")
            client = self.payip_payments_service.find_client_by_code(
                filial=row["filial"],
                client_code=row["nb"],
            )
            if client is None:
                raise RuntimeError(f"Cliente ativo nao encontrado na PayIP para revenda {row['filial']} e NB {row['nb']}.")
            result["client_name"] = str(getattr(client, "fantasy_name", "") or getattr(client, "name", "") or "").strip()
            payment = self._emit_charge(row=row, client=client)
            payment_id = _payment_id(payment)
            result["payment_id"] = payment_id
            payment_detail = self._generated_payment_detail(payment=payment, payment_id=payment_id)
            result["company_id"] = _payment_company_id(payment_detail)
            result["pix_code"] = _pix_code(payment_detail) or _pix_code(payment)
            if payment_id:
                pdf_bytes, pdf_error = self._generate_charge_pdf(
                    filial=row["filial"],
                    company_id=result["company_id"],
                    payment_id=payment_id,
                )
                if pdf_bytes:
                    result["pdf_available"] = True
                    result["pdf_base64"] = base64.b64encode(pdf_bytes).decode("ascii")
                elif pdf_error:
                    result["error"] = f"PDF indisponivel: {pdf_error}"
            result["status"] = "success"
        except PayipMfaRequired as exc:
            result["error"] = "PayIP pediu token MFA. Informe o codigo do Google Authenticator e gere o lote novamente."
            self.logger.warning("PayIP pediu MFA no lote linha %s: %s", row.get("line_number"), exc)
        except Exception as exc:
            result["error"] = _short_error(str(exc))
            self.logger.exception("Falha ao gerar cobranca PayIP em lote linha %s: %s", row.get("line_number"), exc)
        return result

    def _emit_charge(self, *, row: dict[str, Any], client: Any) -> dict[str, Any]:
        title = _payip_charge_title(row["filial"])
        return self.payip_payments_service.create_pix_charge(
            filial=row["filial"],
            amount=Decimal(row["amount"]),
            rate_amount=Decimal(row["rate_amount"]),
            interest_perc=Decimal(row["interest_perc"]),
            tax_payer_id=str(getattr(client, "tax_payer_id", "") or ""),
            external_id=row["external_id"],
            due_date=date.fromisoformat(row["due_date"]),
            issue_date=datetime.now().date(),
            title=title,
            description=row["description"] or title,
            invoice=row["invoice"],
        )

    def _generated_payment_detail(self, *, payment: dict[str, Any], payment_id: str) -> dict[str, Any]:
        if not payment_id:
            return payment
        try:
            return self.payip_payments_service.get_payment(payment_id)
        except Exception as exc:
            self.logger.warning("Falha ao consultar cobranca PayIP %s: %s", payment_id, exc)
            return payment

    def _generate_charge_pdf(self, *, filial: str, company_id: str, payment_id: str) -> tuple[bytes, str]:
        last_error = ""
        for attempt in range(1, PAYIP_PDF_ATTEMPTS + 1):
            try:
                return (
                    self.payip_payments_service.invoice_report_pdf(
                        filial=filial,
                        company_id=company_id,
                        payment_ids=[payment_id],
                    ),
                    "",
                )
            except Exception as exc:
                last_error = _short_error(str(exc))
                if attempt < PAYIP_PDF_ATTEMPTS and _is_payip_pdf_not_ready_error(last_error):
                    time.sleep(PAYIP_PDF_RETRY_DELAY_SECONDS)
                    continue
                break
        return b"", last_error


def _payload_options(payload: Any) -> PayipBatchOptions:
    return PayipBatchOptions(
        raw_text=str(getattr(payload, "raw_text", "") or ""),
        use_default_rate=bool(getattr(payload, "use_default_rate", True)),
        use_default_interest=bool(getattr(payload, "use_default_interest", True)),
        include_nb=bool(getattr(payload, "include_nb", False)),
        include_nf=bool(getattr(payload, "include_nf", False)),
        mfa_code=str(getattr(payload, "mfa_code", "") or "").strip(),
    )


def _options_payload(options: PayipBatchOptions) -> dict[str, Any]:
    return {
        "use_default_rate": options.use_default_rate,
        "use_default_interest": options.use_default_interest,
        "include_nb": options.include_nb,
        "include_nf": options.include_nf,
        "mfa_code_provided": bool(options.mfa_code),
    }


def _parse_batch_text(raw_text: str) -> list[dict[str, Any]]:
    text = str(raw_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Cole as cobrancas PayIP no formato CSV.")
    sample = text.splitlines()[0]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    lines = [row for row in reader if any(str(cell or "").strip() for cell in row)]
    if not lines:
        raise HTTPException(status_code=400, detail="Nenhuma linha valida informada.")

    first = [_clean_header(cell) for cell in lines[0]]
    has_header = bool({"filial", "revenda", "operacao"} & set(first)) and bool({"nb", "codpdv", "codigopdv"} & set(first))
    rows: list[dict[str, Any]] = []
    headers = first if has_header else ["filial", "nb", "valor", "vencimento", "nf", "taxa", "juros", "descricao"]
    start_index = 2 if has_header else 1
    data_lines = lines[1:] if has_header else lines
    for offset, values in enumerate(data_lines, start=start_index):
        item = {"_line_number": offset}
        for index, header in enumerate(headers):
            item[header] = values[index] if index < len(values) else ""
        rows.append(item)
    return rows


def _normalize_input_row(row: dict[str, Any], *, options: PayipBatchOptions) -> dict[str, Any]:
    line_number = int(row.get("_line_number") or 0)
    filial = normalize_numeric_code(_row_value(row, "filial", "revenda", "operacao"))
    nb = normalize_numeric_code(_row_value(row, "nb", "codpdv", "codigopdv", "cliente"))
    amount = _parse_money(_row_value(row, "valor", "amount"))
    due_date = _parse_date(_row_value(row, "vencimento", "due_date", "datavencimento"))
    if not filial:
        raise ValueError("Revenda obrigatoria.")
    if not nb:
        raise ValueError("NB obrigatorio.")
    if amount is None or amount <= 0:
        raise ValueError("Valor invalido.")
    if due_date is None:
        raise ValueError("Vencimento invalido. Use AAAA-MM-DD ou DD/MM/AAAA.")
    row_rate = _parse_money(_row_value(row, "taxa", "rate", "amount_rate"))
    row_interest = _parse_money(_row_value(row, "juros", "interest", "juro"))
    rate_amount = row_rate if row_rate is not None else DEFAULT_PAYIP_RATE_AMOUNT if options.use_default_rate else Decimal("0")
    interest_perc = row_interest if row_interest is not None else DEFAULT_PAYIP_INTEREST_PERC if options.use_default_interest else Decimal("0")
    invoice = str(_row_value(row, "nf", "nota", "notafiscal", "invoice") or "").strip() if options.include_nf else ""
    external_id = nb if options.include_nb else ""
    description = str(_row_value(row, "descricao", "description", "obs") or "").strip()
    return {
        "item_id": f"item-{line_number}-{secrets.token_hex(3)}",
        "line_number": line_number,
        "filial": filial,
        "nb": nb,
        "amount": _decimal_text(amount),
        "due_date": due_date.isoformat(),
        "rate_amount": _decimal_text(max(rate_amount, Decimal("0"))),
        "interest_perc": _decimal_text(max(interest_perc, Decimal("0"))),
        "invoice": invoice,
        "external_id": external_id,
        "description": description,
    }


def _row_value(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        clean = _clean_header(key)
        if clean in row and str(row.get(clean) or "").strip():
            return str(row.get(clean) or "").strip()
    return ""


def _clean_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _parse_money(value: Any) -> Decimal | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    cleaned = raw.replace("R$", "").replace("%", "").replace(" ", "").replace("+", "")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.rfind(",") > cleaned.rfind(".") else cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def _decimal_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _new_job_id() -> str:
    return f"payip-batch-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def _payip_charge_title(filial: str) -> str:
    return f"Fatura revenda Pau Brasil - {filial}"


def _payment_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = str(data.get("id") or "").strip()
    if direct:
        return direct
    nested = data.get("data")
    return str(nested.get("id") or "").strip() if isinstance(nested, dict) else ""


def _payment_company_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    company = data.get("company")
    if isinstance(company, dict):
        company_id = str(company.get("companyId") or company.get("id") or "").strip()
        if company_id:
            return company_id
    for key in ("companyId", "company_id"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    nested = data.get("data")
    return _payment_company_id(nested) if isinstance(nested, dict) else ""


def _pix_code(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    qr = data.get("qrCodePixCashin")
    if isinstance(qr, dict):
        return str(qr.get("emv") or qr.get("pixCode") or "").strip()
    nested = data.get("data")
    return _pix_code(nested) if isinstance(nested, dict) else ""


def _short_error(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:220] if len(text) > 220 else text


def _is_payip_pdf_not_ready_error(value: str) -> bool:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return "arquivo ainda nao foi criado" in normalized or "tente novamente" in normalized


def _failed_result(row: dict[str, Any], *, error: str) -> dict[str, Any]:
    return {
        "item_id": row["item_id"],
        "line_number": row["line_number"],
        "status": "failed",
        "filial": row["filial"],
        "nb": row["nb"],
        "client_name": "",
        "amount": row["amount"],
        "due_date": row["due_date"],
        "payment_id": "",
        "company_id": "",
        "pix_code": "",
        "pdf_available": False,
        "pdf_base64": "",
        "error": error,
    }


def _public_job_payload(job: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    return {
        "job_id": job.get("job_id", ""),
        "status": job.get("status", ""),
        "queued_at": job.get("queued_at", ""),
        "started_at": job.get("started_at", ""),
        "finished_at": job.get("finished_at", ""),
        "total": int(job.get("total") or 0),
        "processed": int(job.get("processed") or 0),
        "success": int(job.get("success") or 0),
        "failed": int(job.get("failed") or 0),
        "options": dict(job.get("options") or {}),
        "items": list(job.get("items") or []),
        "results": list(job.get("results") or []),
    }
