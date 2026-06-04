from __future__ import annotations

import re
from uuid import uuid4
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from bot_api.config import Settings
from bot_api.integrations.payip_client import PayipClient, PayipConfig, PayipError, summarize_collection_response

DEFAULT_PAYMENT_AMOUNT_TOLERANCE = Decimal("0.05")
PAYIP_LOCAL_TIMEZONE = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class PayipPaymentsPage:
    raw: dict[str, Any]
    items: tuple[dict[str, Any], ...]
    items_count: int | None
    total_items: int | None
    page: int
    page_size: int
    filial: str = ""
    company_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "items_count": self.items_count,
            "total_items": self.total_items,
            "page": self.page,
            "page_size": self.page_size,
            "filial": self.filial,
            "company_id": self.company_id,
            "items": list(self.items),
            "raw": self.raw,
        }


@dataclass(frozen=True)
class PayipClientRecord:
    raw: dict[str, Any]
    client_company_id: str
    client_id: str
    code: str
    tax_payer_id: str
    name: str
    fantasy_name: str = ""
    phone: str = ""


@dataclass(frozen=True)
class PayipStatementResume:
    raw: dict[str, Any]
    filial: str
    company_id: str
    date_start: str
    date_end: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "filial": self.filial,
            "company_id": self.company_id,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "raw": self.raw,
        }


class PayipPaymentsService:
    def __init__(self, client: PayipClient) -> None:
        self.client = client

    def status(self) -> dict[str, Any]:
        status = self.client.status()
        status["company_ids"] = self.client.company_map()
        status["company_tax_ids"] = self.client.company_tax_map()
        return status

    def bootstrap_session(self, *, mfa_code: str) -> dict[str, Any]:
        return self.client.bootstrap_session(mfa_code=mfa_code)

    def list_payments(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str = "",
        client_code: str = "",
        invoice: str = "",
        search: str = "",
        due_date_start: str = "",
        due_date_end: str = "",
        paid_date_start: str = "",
        paid_date_end: str = "",
        created_at_start: str = "",
        created_at_end: str = "",
        filial: str = "",
    ) -> PayipPaymentsPage:
        company_id = self.client.resolve_company_id(filial=filial)
        raw = self.client.list_payments(
            page=page,
            page_size=page_size,
            status=status,
            client_code=client_code,
            invoice=invoice,
            search=search,
            due_date_start=due_date_start,
            due_date_end=due_date_end,
            paid_date_start=paid_date_start,
            paid_date_end=paid_date_end,
            created_at_start=created_at_start,
            created_at_end=created_at_end,
            filial=filial,
            company_id=company_id,
        )
        summary = summarize_collection_response(raw)
        items = tuple(item for item in _extract_payment_items(raw) if isinstance(item, dict))
        return PayipPaymentsPage(
            raw=raw,
            items=items,
            items_count=summary["items_count"],
            total_items=summary["total_items"],
            page=summary["page"] or page,
            page_size=summary["page_size"] or page_size,
            filial=filial,
            company_id=company_id,
        )

    def find_payments_by_amount_and_paid_date(
        self,
        *,
        filial: str,
        amount: Decimal | str | int | float,
        day: date | str,
        tolerance: Decimal | str | int | float = DEFAULT_PAYMENT_AMOUNT_TOLERANCE,
        status: str = "",
        page_size: int = 100,
        max_pages: int | None = None,
    ) -> PayipPaymentsPage:
        normalized_amount = _payment_amount(amount)
        if normalized_amount is None or normalized_amount <= 0:
            raise PayipError("Valor PayIP invalido para busca")
        normalized_tolerance = _payment_amount(tolerance)
        if normalized_tolerance is None or normalized_tolerance < 0:
            raise PayipError("Tolerancia PayIP invalida para busca")
        normalized_day = _date_text(day)
        if not normalized_day:
            raise PayipError("Data PayIP invalida para busca")
        try:
            date.fromisoformat(normalized_day)
        except ValueError as exc:
            raise PayipError("Data PayIP invalida para busca") from exc

        company_id = self.client.resolve_company_id(filial=filial)
        safe_page_size = max(1, min(int(page_size or 100), 500))
        safe_max_pages = max(1, int(max_pages)) if max_pages is not None else None
        filtered_items: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        api_total_items: int | None = None
        page = 1

        while safe_max_pages is None or page <= safe_max_pages:
            raw = self.client.list_payments(
                page=page,
                page_size=safe_page_size,
                status=status,
                paid_date_start=normalized_day,
                paid_date_end=normalized_day,
                filial=filial,
                company_id=company_id,
            )
            raw_pages.append(raw)
            summary = summarize_collection_response(raw)
            if api_total_items is None:
                api_total_items = summary["total_items"]

            page_items = tuple(item for item in _extract_payment_items(raw) if isinstance(item, dict))
            filtered_items.extend(
                item
                for item in page_items
                if _payment_matches_paid_date(item, normalized_day)
                and _payment_matches_paid_amount(item, normalized_amount, tolerance=normalized_tolerance)
            )

            current_page_size = summary["page_size"] or safe_page_size
            current_page = summary["page"] or page
            if not page_items:
                break
            if api_total_items is not None and current_page * current_page_size >= api_total_items:
                break
            if api_total_items is None and len(page_items) < safe_page_size:
                break
            page += 1

        raw_result = {
            "pages": raw_pages,
            "api_total_items": api_total_items,
            "filtered_count": len(filtered_items),
            "amount": str(normalized_amount),
            "tolerance": str(normalized_tolerance),
            "paid_date": normalized_day,
        }
        return PayipPaymentsPage(
            raw=raw_result,
            items=tuple(filtered_items),
            items_count=len(filtered_items),
            total_items=len(filtered_items),
            page=1,
            page_size=safe_page_size,
            filial=filial,
            company_id=company_id,
        )

    def find_client_by_code(self, *, filial: str, client_code: str) -> PayipClientRecord | None:
        normalized_client_code = _only_digits(client_code)
        if not normalized_client_code:
            return None
        company_id = self.client.resolve_company_id(filial=filial)
        raw = self.client.list_clients(
            page=1,
            page_size=10,
            status="ACTIVE",
            code=normalized_client_code,
            filial=filial,
            company_id=company_id,
        )
        records = [
            record
            for record in (_parse_client_record(item) for item in _extract_payment_items(raw))
            if record is not None
        ]
        exact = [record for record in records if _only_digits(record.code) == normalized_client_code]
        return exact[0] if exact else records[0] if records else None

    def create_pix_charge(
        self,
        *,
        filial: str,
        amount: Decimal,
        rate_amount: Decimal,
        interest_perc: Decimal,
        tax_payer_id: str,
        external_id: str,
        due_date: date,
        issue_date: date,
        title: str,
        description: str,
        invoice: str = "",
    ) -> dict[str, Any]:
        company_tax_id = self.client.resolve_company_tax_id(filial=filial)
        payload = _build_pix_charge_payload(
            amount=amount,
            rate_amount=rate_amount,
            interest_perc=interest_perc,
            tax_payer_id=tax_payer_id,
            external_id=external_id,
            invoice=invoice,
            company_tax_id=company_tax_id,
            due_date=due_date,
            issue_date=issue_date,
            title=title,
            description=description,
        )
        return self.client.create_payment(payload)

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        return self.client.get_payment(payment_id)

    def invoice_report_pdf(
        self,
        *,
        filial: str,
        payment_ids: list[str] | tuple[str, ...],
        company_id: str = "",
    ) -> bytes:
        resolved_company_id = self.client.resolve_company_id(filial=filial, company_id=company_id)
        return self.client.invoice_report_pdf(
            company_id=resolved_company_id,
            payment_ids=payment_ids,
        )

    def statement_movements_resume(
        self,
        *,
        filial: str,
        date_start: date | str,
        date_end: date | str,
    ) -> PayipStatementResume:
        normalized_date_start = _date_text(date_start)
        normalized_date_end = _date_text(date_end)
        company_id = self.client.resolve_company_id(filial=filial)
        raw = self.client.statement_movements_resume(
            filial=filial,
            company_id=company_id,
            date_start=normalized_date_start,
            date_end=normalized_date_end,
        )
        return PayipStatementResume(
            raw=raw,
            filial=filial,
            company_id=company_id,
            date_start=normalized_date_start,
            date_end=normalized_date_end,
        )

    def statement_movements_export(
        self,
        *,
        filial: str,
        date_start: date | str,
        date_end: date | str,
        file_format: str,
    ) -> bytes:
        normalized_date_start = _date_text(date_start)
        normalized_date_end = _date_text(date_end)
        company_id = self.client.resolve_company_id(filial=filial)
        return self.client.statement_movements_export(
            file_format=file_format,
            filial=filial,
            company_id=company_id,
            date_start=normalized_date_start,
            date_end=normalized_date_end,
        )


def _extract_payment_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "data", "content", "results", "payments"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_payment_items(value)
            if nested:
                return nested
    return []


def _date_text(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def _payment_amount(value: Decimal | str | int | float | None) -> Decimal | None:
    parsed = _parse_decimal_value(value)
    if parsed is None:
        return None
    return parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _payment_matches_paid_amount(
    item: dict[str, Any],
    target_amount: Decimal,
    *,
    tolerance: Decimal = DEFAULT_PAYMENT_AMOUNT_TOLERANCE,
) -> bool:
    candidates = [item.get("amountPaid")]
    amount_details = item.get("amountDetails")
    if isinstance(amount_details, dict):
        candidates.append(amount_details.get("amountPaid"))

    parsed_candidates = [_payment_amount(candidate) for candidate in candidates]
    parsed_candidates = [candidate for candidate in parsed_candidates if candidate is not None]
    if parsed_candidates:
        return any(abs(candidate - target_amount) <= tolerance for candidate in parsed_candidates)

    return _payment_matches_charge_amount(item, target_amount, tolerance=tolerance)


def _payment_matches_charge_amount(
    item: dict[str, Any],
    target_amount: Decimal,
    *,
    tolerance: Decimal = DEFAULT_PAYMENT_AMOUNT_TOLERANCE,
) -> bool:
    candidates = [item.get("amount")]
    amount_details = item.get("amountDetails")
    if isinstance(amount_details, dict):
        candidates.extend([amount_details.get("amount"), amount_details.get("amountTotal")])

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        parsed = _payment_amount(candidate)
        if parsed is not None and abs(parsed - target_amount) <= tolerance:
            return True
    return False


def _payment_matches_paid_date(item: dict[str, Any], target_day: str) -> bool:
    try:
        parsed_target_day = date.fromisoformat(target_day)
    except ValueError:
        return False

    for key in ("paidDate", "paymentDate", "paidAt"):
        parsed = _parse_payip_datetime(item.get(key))
        if parsed is not None and parsed.astimezone(PAYIP_LOCAL_TIMEZONE).date() == parsed_target_day:
            return True
    return False


def _parse_payip_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_decimal_value(value: Decimal | str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    raw = str(value).strip()
    if not raw:
        return None
    cleaned = (
        raw.replace("R$", "")
        .replace("r$", "")
        .replace("%", "")
        .replace(" ", "")
        .replace("+", "")
    )
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _parse_client_record(item: Any) -> PayipClientRecord | None:
    if not isinstance(item, dict):
        return None
    client = item.get("client")
    if not isinstance(client, dict):
        client = item
    code = str(client.get("code") or item.get("code") or item.get("externalId") or "").strip()
    tax_payer_id = _only_digits(client.get("taxPayerId") or item.get("taxPayerId"))
    name = str(client.get("name") or item.get("name") or "").strip()
    fantasy_name = str(client.get("fantasyName") or item.get("fantasyName") or "").strip()
    if not code or not tax_payer_id:
        return None
    return PayipClientRecord(
        raw=item,
        client_company_id=str(item.get("id") or item.get("clientCompanyId") or "").strip(),
        client_id=str(client.get("clientId") or item.get("clientId") or "").strip(),
        code=code,
        tax_payer_id=tax_payer_id,
        name=name or fantasy_name or "-",
        fantasy_name=fantasy_name,
        phone=_only_digits(client.get("phone") or item.get("phone")),
    )


def _build_pix_charge_payload(
    *,
    amount: Decimal,
    rate_amount: Decimal,
    interest_perc: Decimal,
    tax_payer_id: str,
    external_id: str,
    invoice: str,
    company_tax_id: str,
    due_date: date,
    issue_date: date,
    title: str,
    description: str,
) -> dict[str, Any]:
    amount_value = float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    normalized_rate_amount = max(rate_amount, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    normalized_interest_perc = max(interest_perc, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    payload: dict[str, Any] = {
        "issueDate": issue_date.isoformat(),
        "amount": amount_value,
        "taxPayerId": _only_digits(tax_payer_id),
        "companyTaxId": _only_digits(company_tax_id),
        "isPixCashIn": True,
        "isBillet": False,
        "dueDate": due_date.isoformat(),
        "title": str(title or "").strip(),
        "paymentShape": "PIX",
        "paymentMethod": "AVISTA",
        "description": str(description or "").strip() or "Nao informado",
        "expirationInDays": 30,
    }
    payload["externalId"] = _normalize_payip_external_id(external_id)
    if normalized_rate_amount > 0:
        payload["amountRate"] = {
            "hasRate": True,
            "modality": "FIXED_VALUE",
            "amount": float(normalized_rate_amount),
        }
    if normalized_interest_perc > 0:
        payload["amountInterest"] = {
            "hasInterest": True,
            "modality": "PERCENTAGE_PER_DAY_CALENDAR_DAYS",
            "amountPerc": float(normalized_interest_perc),
        }
    normalized_invoice = str(invoice or "").strip()
    if normalized_invoice:
        payload["invoice"] = normalized_invoice
    return payload


def _payment_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    direct = str(data.get("id") or "").strip()
    if direct:
        return direct
    nested = data.get("data")
    if isinstance(nested, dict):
        return str(nested.get("id") or "").strip()
    return ""


def _only_digits(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit())


def _normalize_payip_external_id(external_id: str) -> str:
    raw = str(external_id or "").strip()
    if not raw:
        return f"BOT-{uuid4()}"

    normalized = re.sub(r"[^A-Za-z0-9-]+", "-", raw)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized:
        return f"BOT-{uuid4()}"
    if len(normalized) < 4:
        normalized = f"NB-{normalized}"
    if len(normalized) > 60:
        normalized = normalized[:60].strip("-")
    if len(normalized) < 4:
        return f"BOT-{uuid4()}"
    return normalized


def build_payip_payments_service(settings: Settings) -> PayipPaymentsService:
    client = PayipClient(
        PayipConfig(
            base_url=settings.payip_base_url,
            client_id=settings.payip_client_id,
            username=settings.payip_username,
            password=settings.payip_password,
            company_id=settings.payip_company_id,
            token_cache_file=settings.payip_token_cache_file,
            company_ids=settings.payip_company_ids,
            company_tax_ids=settings.payip_company_tax_ids,
            timeout_seconds=settings.payip_timeout_seconds,
            mfa_code=settings.payip_mfa_code,
        )
    )
    return PayipPaymentsService(client)
