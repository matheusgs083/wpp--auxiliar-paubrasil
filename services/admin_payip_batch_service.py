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
PAYIP_CHARGE_ATTEMPTS = 3
PAYIP_CHARGE_RETRY_DELAY_SECONDS = 1.5


@dataclass(frozen=True)
class PayipBatchOptions:
    raw_text: str
    use_default_rate: bool = True
    use_default_interest: bool = True
    include_nb: bool = False
    include_nf: bool = False
    auto_create_clients: bool = False
    mfa_code: str = ""


@dataclass(frozen=True)
class PayipPromaxImportOptions:
    filial: str
    start_date: str
    end_date: str
    mfa_code: str = ""
    auto_create_clients: bool = False


class AdminPayipBatchService:
    def __init__(
        self,
        *,
        payip_payments_service: Any,
        dclientes_query_service: Any | None = None,
        panel_context_has_all_filiais: Any,
        logger: Any,
    ) -> None:
        self.payip_payments_service = payip_payments_service
        self.dclientes_query_service = dclientes_query_service
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

    def validate_promax_import(self, payload: Any, context: dict[str, Any] | None) -> dict[str, Any]:
        options = _promax_import_options(payload)
        self._ensure_filial_allowed(options.filial, context)
        validation = self._validate_promax_import(options)
        client_creation = {"created": [], "not_found": [], "failed": []}
        missing_codes = tuple(str(item or "").strip() for item in getattr(validation, "missing_client_codes", ()) or () if str(item or "").strip())
        if missing_codes and options.auto_create_clients:
            self._bootstrap_mfa_if_provided(options.mfa_code)
            client_creation = self._create_missing_clients(filial=options.filial, codes=missing_codes)
            validation = self._validate_promax_import(options)
        return _promax_import_payload(validation, client_creation=client_creation)

    def run_promax_import(self, payload: Any, context: dict[str, Any] | None) -> dict[str, Any]:
        options = _promax_import_options(payload)
        self._ensure_filial_allowed(options.filial, context)
        if not options.mfa_code:
            raise HTTPException(status_code=400, detail="Informe o token MFA PayIP para confirmar a importacao.")
        validation = self._validate_promax_import(options)
        client_creation = {"created": [], "not_found": [], "failed": []}
        missing_codes = tuple(str(item or "").strip() for item in getattr(validation, "missing_client_codes", ()) or () if str(item or "").strip())
        if missing_codes and options.auto_create_clients:
            self._bootstrap_mfa_if_provided(options.mfa_code)
            client_creation = self._create_missing_clients(filial=options.filial, codes=missing_codes)
            validation = self._validate_promax_import(options)
            missing_codes = tuple(str(item or "").strip() for item in getattr(validation, "missing_client_codes", ()) or () if str(item or "").strip())
        if missing_codes:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Ainda existem clientes faltando na PayIP: "
                    + ", ".join(missing_codes[:20])
                    + ("..." if len(missing_codes) > 20 else "")
                ),
            )
        result = self.payip_payments_service.import_promax_batch(
            filial=options.filial,
            date_start=options.start_date,
            date_end=options.end_date,
            totp_code=options.mfa_code,
        )
        return _promax_import_payload(result, client_creation=client_creation, imported=True)

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

    def _ensure_filial_allowed(self, filial: str, context: dict[str, Any] | None) -> None:
        allowed_filiais = self._allowed_filiais(context)
        if allowed_filiais is not None and filial not in allowed_filiais:
            raise HTTPException(status_code=400, detail="Revenda fora do escopo liberado para este painel.")

    def _validate_promax_import(self, options: PayipPromaxImportOptions) -> Any:
        if self.payip_payments_service is None:
            raise HTTPException(status_code=503, detail="PayIP nao configurada.")
        try:
            return self.payip_payments_service.validate_promax_import_batch(
                filial=options.filial,
                date_start=options.start_date,
                date_end=options.end_date,
            )
        except PayipMfaRequired as exc:
            if not options.mfa_code:
                raise HTTPException(status_code=400, detail="PayIP pediu MFA. Informe o token MFA e valide novamente.") from exc
            try:
                self.payip_payments_service.bootstrap_session(mfa_code=options.mfa_code)
                return self.payip_payments_service.validate_promax_import_batch(
                    filial=options.filial,
                    date_start=options.start_date,
                    date_end=options.end_date,
                )
            except PayipMfaRequired as retry_exc:
                raise HTTPException(status_code=400, detail="Token MFA PayIP nao validou. Confira o codigo e tente novamente.") from retry_exc
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.exception("Falha ao validar importacao automatizada PayIP: %s", exc)
            raise HTTPException(status_code=503, detail=f"Falha ao validar importacao PayIP: {_short_error(str(exc))}") from exc

    def _bootstrap_mfa_if_provided(self, mfa_code: str) -> None:
        clean_code = str(mfa_code or "").strip()
        if not clean_code:
            return
        try:
            self.payip_payments_service.bootstrap_session(mfa_code=clean_code)
        except PayipMfaRequired as exc:
            raise HTTPException(status_code=400, detail="Token MFA PayIP nao validou. Confira o codigo e tente novamente.") from exc
        except Exception as exc:
            self.logger.exception("Falha ao validar MFA PayIP antes de criar clientes: %s", exc)
            raise HTTPException(status_code=503, detail=f"Falha ao validar MFA PayIP: {_short_error(str(exc))}") from exc

    def _create_missing_clients(self, *, filial: str, codes: tuple[str, ...]) -> dict[str, list[str]]:
        if self.dclientes_query_service is None:
            return {"created": [], "not_found": list(codes), "failed": ["dClientes indisponivel no painel."]}
        created: list[str] = []
        not_found: list[str] = []
        failed: list[str] = []
        for code in dict.fromkeys(str(item or "").strip() for item in codes if str(item or "").strip()):
            normalized_code = normalize_numeric_code(code)
            try:
                profile = self.dclientes_query_service.get_payip_profile_by_registration(filial, normalized_code)
                if profile is None:
                    not_found.append(normalized_code)
                    continue
                if not getattr(profile, "documento", ""):
                    failed.append(f"{normalized_code}: sem CPF/CNPJ valido na dClientes")
                    continue
                self.payip_payments_service.create_client_from_profile(profile=profile)
                created.append(normalized_code)
            except PayipMfaRequired:
                failed.append(f"{normalized_code}: PayIP pediu MFA para criar cliente; informe o token MFA e valide novamente")
            except Exception as exc:
                self.logger.exception("Falha ao criar cliente PayIP NB %s: %s", normalized_code, exc)
                failed.append(f"{normalized_code}: {_short_error(str(exc))}")
        return {"created": created, "not_found": not_found, "failed": failed}

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

        job_options = dict(job.get("options") or {})
        auto_create_clients = bool(job_options.get("auto_create_clients"))
        for index, row in enumerate(rows, start=1):
            result = self._process_row(row, auto_create_clients=auto_create_clients)
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

    def _process_row(self, row: dict[str, Any], *, auto_create_clients: bool = False) -> dict[str, Any]:
        result = _failed_result(row, error="")
        try:
            if self.payip_payments_service is None:
                raise RuntimeError("PayIP nao configurada.")
            client = self.payip_payments_service.find_client_by_code(
                filial=row["filial"],
                client_code=row["nb"],
            )
            if client is None and auto_create_clients:
                client_creation = self._create_missing_clients(filial=row["filial"], codes=(row["nb"],))
                result["client_creation"] = client_creation
                if client_creation.get("created"):
                    client = self._find_client_after_creation(row)
                elif client_creation.get("not_found"):
                    raise RuntimeError(
                        f"Cliente NB {row['nb']} nao encontrado na dClientes para criar na PayIP."
                    )
                elif client_creation.get("failed"):
                    raise RuntimeError("Falha ao criar cliente PayIP: " + " | ".join(client_creation["failed"]))
            if client is None:
                raise RuntimeError(f"Cliente ativo nao encontrado na PayIP para revenda {row['filial']} e NB {row['nb']}.")
            if auto_create_clients and result.get("client_creation") and not getattr(client, "tax_payer_id", ""):
                raise RuntimeError(f"Cliente NB {row['nb']} criado, mas retornou sem CPF/CNPJ na PayIP.")
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

    def _find_client_after_creation(self, row: dict[str, Any]) -> Any | None:
        for attempt in range(1, 4):
            if attempt > 1:
                time.sleep(1.0)
            client = self.payip_payments_service.find_client_by_code(
                filial=row["filial"],
                client_code=row["nb"],
            )
            if client is not None:
                return client
        raise RuntimeError(
            f"Cliente NB {row['nb']} foi criado, mas ainda nao apareceu ativo na PayIP. Tente gerar novamente em alguns segundos."
        )

    def _emit_charge(self, *, row: dict[str, Any], client: Any) -> dict[str, Any]:
        title = _payip_charge_title(row["filial"])
        last_error: Exception | None = None
        for attempt in range(1, PAYIP_CHARGE_ATTEMPTS + 1):
            try:
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
            except PayipMfaRequired:
                raise
            except Exception as exc:
                last_error = exc
                existing = self._find_existing_charge_after_create_error(row=row)
                if existing:
                    self.logger.warning(
                        "PayIP lote linha %s usou cobranca ja criada apos erro na tentativa %s: %s",
                        row.get("line_number"),
                        attempt,
                        _payment_id(existing) or "-",
                    )
                    return existing
                if attempt >= PAYIP_CHARGE_ATTEMPTS or not _is_retryable_payip_error(str(exc)):
                    break
                self.logger.warning(
                    "PayIP lote linha %s falhou ao emitir na tentativa %s/%s; tentando novamente: %s",
                    row.get("line_number"),
                    attempt,
                    PAYIP_CHARGE_ATTEMPTS,
                    _short_error(str(exc)),
                )
                time.sleep(PAYIP_CHARGE_RETRY_DELAY_SECONDS)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Falha desconhecida ao gerar cobranca PayIP.")

    def _find_existing_charge_after_create_error(self, *, row: dict[str, Any]) -> dict[str, Any]:
        client_code = row.get("external_id") or row.get("nb") or ""
        if not client_code:
            return {}
        created_at = datetime.now().date().isoformat()
        try:
            page = self.payip_payments_service.list_payments(
                page=1,
                page_size=50,
                status="PENDING",
                client_code=str(client_code),
                due_date_start=str(row.get("due_date") or ""),
                due_date_end=str(row.get("due_date") or ""),
                created_at_start=created_at,
                created_at_end=created_at,
                filial=str(row.get("filial") or ""),
            )
        except PayipMfaRequired:
            raise
        except Exception as exc:
            self.logger.warning(
                "Falha ao procurar cobranca PayIP ja criada para lote linha %s: %s",
                row.get("line_number"),
                _short_error(str(exc)),
            )
            return {}
        items = [item for item in getattr(page, "items", ()) or () if isinstance(item, dict)]
        matches = [item for item in items if _payment_matches_input_row(item, row)]
        return matches[0] if matches else {}

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
        auto_create_clients=bool(getattr(payload, "auto_create_clients", False)),
        mfa_code=str(getattr(payload, "mfa_code", "") or "").strip(),
    )


def _options_payload(options: PayipBatchOptions) -> dict[str, Any]:
    return {
        "use_default_rate": options.use_default_rate,
        "use_default_interest": options.use_default_interest,
        "include_nb": options.include_nb,
        "include_nf": options.include_nf,
        "auto_create_clients": options.auto_create_clients,
        "mfa_code_provided": bool(options.mfa_code),
    }


def _promax_import_options(payload: Any) -> PayipPromaxImportOptions:
    filial = normalize_numeric_code(getattr(payload, "filial", "") or getattr(payload, "revenda", ""))
    start_date = _promax_import_date_text(getattr(payload, "start_date", "") or getattr(payload, "date_start", ""))
    end_date = _promax_import_date_text(getattr(payload, "end_date", "") or getattr(payload, "date_end", ""))
    if not filial:
        raise HTTPException(status_code=400, detail="Informe a revenda da importacao PayIP.")
    if not start_date or not end_date:
        raise HTTPException(status_code=400, detail="Informe data inicial e final no formato AAAA-MM-DD ou DD/MM/AAAA.")
    return PayipPromaxImportOptions(
        filial=filial,
        start_date=start_date,
        end_date=end_date,
        mfa_code=str(getattr(payload, "mfa_code", "") or "").strip(),
        auto_create_clients=bool(getattr(payload, "auto_create_clients", False)),
    )


def _promax_import_date_text(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed is not None else ""


def _promax_import_payload(result: Any, *, client_creation: dict[str, list[str]], imported: bool = False) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        payload = result.to_dict()
    else:
        payload = {
            "filial": str(getattr(result, "filial", "") or ""),
            "company_id": str(getattr(result, "company_id", "") or ""),
            "date_start": str(getattr(result, "date_start", "") or ""),
            "date_end": str(getattr(result, "date_end", "") or ""),
            "items": list(getattr(result, "items", ()) or ()),
            "missing_client_codes": list(getattr(result, "missing_client_codes", ()) or ()),
            "ok": bool(getattr(result, "ok", not bool(getattr(result, "missing_client_codes", ())))),
            "raw": getattr(result, "raw", {}) or {},
        }
        payload["items_count"] = len(payload["items"])
    items = [item for item in payload.get("items", []) if isinstance(item, dict)]
    total_amount = Decimal("0")
    for item in items:
        amount = _parse_money(
            item.get("total")
            or item.get("value")
            or item.get("amount")
            or item.get("valor")
        )
        if amount is not None:
            total_amount += amount
    payload["items"] = items
    payload["items_count"] = len(items)
    payload["missing_client_codes"] = [
        normalize_numeric_code(item)
        for item in payload.get("missing_client_codes", [])
        if normalize_numeric_code(item)
    ]
    payload["total_amount"] = _decimal_text(total_amount)
    payload["client_creation"] = {
        "created": list(client_creation.get("created") or []),
        "not_found": list(client_creation.get("not_found") or []),
        "failed": list(client_creation.get("failed") or []),
    }
    payload["imported"] = bool(imported)
    payload["ok"] = not bool(payload["missing_client_codes"])
    return payload


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


def _payment_matches_input_row(payment: dict[str, Any], row: dict[str, Any]) -> bool:
    row_amount = _parse_money(row.get("amount"))
    payment_amount = _parse_money(
        payment.get("amount")
        or _nested_value(payment, "amountDetails", "amount")
        or _nested_value(payment, "amountDetails", "amountTotal")
    )
    if row_amount is not None and payment_amount is not None and row_amount != payment_amount:
        return False

    due_date = str(row.get("due_date") or "").strip()
    payment_due_date = str(payment.get("dueDate") or payment.get("due_date") or "").strip()
    if due_date and payment_due_date and not payment_due_date.startswith(due_date):
        return False

    invoice = str(row.get("invoice") or "").strip()
    payment_invoice = str(payment.get("invoice") or "").strip()
    if invoice and payment_invoice and invoice != payment_invoice:
        return False

    return bool(_payment_id(payment) or _pix_code(payment))


def _nested_value(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _short_error(value: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:220] if len(text) > 220 else text


def _is_retryable_payip_error(value: str) -> bool:
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    non_retryable_terms = (
        "http 400",
        "http 401",
        "http 403",
        "http 404",
        "forbidden",
        "nao configurad",
        "nao encontrado",
        "not found",
        "valor invalido",
        "vencimento invalido",
        "cliente ativo nao encontrado",
    )
    if any(term in normalized for term in non_retryable_terms):
        return False
    retryable_terms = (
        "http 408",
        "http 409",
        "http 425",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "timeout",
        "timed out",
        "connection",
        "conexao",
        "temporar",
        "tente novamente",
        "try again",
        "unavailable",
        "indisponivel",
        "reset",
    )
    return any(term in normalized for term in retryable_terms)


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
        "client_creation": {},
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
