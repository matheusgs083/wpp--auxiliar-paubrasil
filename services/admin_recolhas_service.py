from __future__ import annotations

import io
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from fastapi import HTTPException, UploadFile

from bot_api.commercial_scope import normalize_numeric_code
from bot_api.services.recolha_request_service import RecolhaRequestService


PanelContextPredicate = Callable[[dict[str, Any] | None], bool]
UploadCopy = Callable[[UploadFile, Any], int]


class AdminRecolhasService:
    def __init__(
        self,
        *,
        recolha_request_service: RecolhaRequestService,
        giro_query_service: Any,
        comodatos_query_service: Any,
        access_control: Any,
        filial_labels: dict[str, str],
        panel_context_has_all_filiais: PanelContextPredicate,
        panel_context_is_critica_only: PanelContextPredicate,
        copy_upload_with_limit: UploadCopy,
        logger: logging.Logger | None = None,
    ) -> None:
        self.recolha_request_service = recolha_request_service
        self.giro_query_service = giro_query_service
        self.comodatos_query_service = comodatos_query_service
        self.access_control = access_control
        self.filial_labels = dict(filial_labels)
        self.panel_context_has_all_filiais = panel_context_has_all_filiais
        self.panel_context_is_critica_only = panel_context_is_critica_only
        self.copy_upload_with_limit = copy_upload_with_limit
        self.logger = logger or logging.getLogger(__name__)

    def build_giro_recolha_dashboard(
        self,
        context: dict[str, Any] | None = None,
        *,
        limit: int = 200,
        min_gap: str = "1",
        operation: str | list[str] | None = None,
        city: str | list[str] | None = None,
        district: str | list[str] | None = None,
        seller: str | list[str] | None = None,
        manager: str | list[str] | None = None,
        visit_day: str | list[str] | None = None,
        zero_only: bool = False,
    ) -> dict[str, Any]:
        allowed_sectors, allowed_gv_vdes = self._panel_context_allowed_report_scopes(context)
        records = self.giro_query_service.list_recolha_opportunities(
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=limit,
            min_gap=min_gap,
            operation=operation,
            city=city,
            district=district,
            seller=seller,
            manager=manager,
            visit_day=visit_day,
            zero_only=zero_only,
        )
        rows = [record.to_dict() for record in records]
        total_gap = _sum_localized_decimal(row.get("gap_caixas") for row in rows)
        zero_clients = sum(
            1
            for row in rows
            if str(row.get("giro_litrinho") or "") == "ZERO"
            or str(row.get("giro_inteira") or "") == "ZERO"
            or str(row.get("giro_litrao") or "") == "ZERO"
        )
        return {
            "total": len(rows),
            "limit": limit,
            "min_gap": str(min_gap or "1"),
            "summary": {
                "clientes": len(rows),
                "clientes_zero": zero_clients,
                "gap_total": _format_box_total(total_gap),
                "maior_gap": rows[0].get("gap_caixas", "0") if rows else "0",
            },
            "records": rows,
        }

    def build_giro_recolha_filter_options(
        self,
        context: dict[str, Any] | None = None,
        *,
        min_gap: str = "1",
        operation: str | list[str] | None = None,
        city: str | list[str] | None = None,
        district: str | list[str] | None = None,
        seller: str | list[str] | None = None,
        manager: str | list[str] | None = None,
        visit_day: str | list[str] | None = None,
        zero_only: bool = False,
    ) -> dict[str, Any]:
        allowed_sectors, allowed_gv_vdes = self._panel_context_allowed_report_scopes(context)
        options = self.giro_query_service.list_recolha_filter_options(
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            min_gap=min_gap,
            operation=operation,
            city=city,
            district=district,
            seller=seller,
            manager=manager,
            visit_day=visit_day,
            zero_only=zero_only,
        )
        return {"options": options}

    def build_giro_recolha_routes(
        self,
        context: dict[str, Any] | None = None,
        *,
        limit: int = 500,
        min_gap: str = "1",
        operation: str | list[str] | None = None,
        city: str | list[str] | None = None,
        district: str | list[str] | None = None,
        seller: str | list[str] | None = None,
        manager: str | list[str] | None = None,
        visit_day: str | list[str] | None = None,
        zero_only: bool = False,
        max_route_size: int = 12,
    ) -> dict[str, Any]:
        allowed_sectors, allowed_gv_vdes = self._panel_context_allowed_report_scopes(context)
        records = self.giro_query_service.list_recolha_opportunities(
            allowed_sectors=allowed_sectors,
            allowed_gv_vdes=allowed_gv_vdes,
            limit=limit,
            min_gap=min_gap,
            operation=operation,
            city=city,
            district=district,
            seller=seller,
            manager=manager,
            visit_day=visit_day,
            zero_only=zero_only,
        )
        rows = [record.to_dict() for record in records]
        max_size = max(1, min(int(max_route_size or 12), 50))

        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (
                str(row.get("filial") or "").strip() or "Sem operacao",
                str(row.get("visit_day") or "").strip() or "Sem dia de visita",
                str(row.get("cidade") or "").strip() or "Sem cidade",
            )
            grouped.setdefault(key, []).append(row)

        routes: list[dict[str, Any]] = []
        sequence = 1
        for key in sorted(grouped, key=lambda item: (item[0], _route_day_sort_key(item[1]), item[2])):
            items = sorted(
                grouped[key],
                key=lambda row: (
                    str(row.get("bairro") or ""),
                    -_parse_localized_decimal(row.get("gap_caixas")),
                    -_parse_localized_decimal(row.get("media_faturamento_pedido")),
                    str(row.get("nome") or ""),
                ),
            )
            for start in range(0, len(items), max_size):
                chunk = items[start : start + max_size]
                total_gap = _sum_localized_decimal(row.get("gap_caixas") for row in chunk)
                total_boxes = _sum_localized_decimal(row.get("total_caixas") for row in chunk)
                total_revenue = _sum_localized_decimal(row.get("faturamento_total") for row in chunk)
                sellers = sorted(
                    {
                        str(row.get("seller_code") or row.get("setor") or "").strip()
                        for row in chunk
                        if str(row.get("seller_code") or row.get("setor") or "").strip()
                    }
                )
                managers = sorted(
                    {
                        str(row.get("manager_code") or "").strip()
                        for row in chunk
                        if str(row.get("manager_code") or "").strip()
                    }
                )
                neighborhoods = sorted(
                    {
                        str(row.get("bairro") or "").strip()
                        for row in chunk
                        if str(row.get("bairro") or "").strip()
                    }
                )
                route_rows = [
                    {
                        "sequence": index,
                        "filial": row.get("filial"),
                        "cod_pdv": row.get("cod_pdv"),
                        "nome": row.get("nome"),
                        "cidade": row.get("cidade"),
                        "bairro": row.get("bairro"),
                        "visit_day": row.get("visit_day"),
                        "total_caixas": row.get("total_caixas"),
                        "real_caixas": row.get("real_caixas"),
                        "gap_caixas": row.get("gap_caixas"),
                        "gap_litrinho": row.get("gap_litrinho"),
                        "gap_inteira": row.get("gap_inteira"),
                        "gap_litrao": row.get("gap_litrao"),
                        "giro_litrinho": row.get("giro_litrinho"),
                        "giro_inteira": row.get("giro_inteira"),
                        "giro_litrao": row.get("giro_litrao"),
                        "media_faturamento_pedido": row.get("media_faturamento_pedido"),
                        "faturamento_total": row.get("faturamento_total"),
                        "seller": row.get("seller_code") or row.get("setor"),
                        "manager": row.get("manager_code"),
                        "command": f"recolha {row.get('filial') or ''} {row.get('cod_pdv') or ''}".strip(),
                    }
                    for index, row in enumerate(chunk, start=1)
                ]
                routes.append(
                    {
                        "id": f"R{sequence:03d}",
                        "operation": key[0],
                        "seller": sellers[0] if len(sellers) == 1 else ("Varios" if sellers else "-"),
                        "sellers": sellers,
                        "manager": managers[0] if len(managers) == 1 else ("Varios" if managers else "-"),
                        "managers": managers,
                        "visit_day": key[1],
                        "city": key[2],
                        "neighborhoods": neighborhoods,
                        "neighborhood_sequence": " -> ".join(neighborhoods),
                        "pdvs": len(chunk),
                        "total_caixas": _format_box_total(total_boxes),
                        "gap_total": _format_box_total(total_gap),
                        "faturamento_total": f"R$ {_format_decimal_br(total_revenue)}",
                        "items": route_rows,
                    }
                )
                sequence += 1

        routes.sort(
            key=lambda route: (
                _route_day_sort_key(route.get("visit_day", "")),
                route.get("operation", ""),
                route.get("city", ""),
                str(route.get("neighborhood_sequence") or ""),
                -_parse_localized_decimal(route.get("gap_total")),
            )
        )
        for index, route in enumerate(routes, start=1):
            route["id"] = f"R{index:03d}"
        return {
            "total": len(routes),
            "summary": {
                "rotas": len(routes),
                "pdvs": len(rows),
                "gap_total": _format_box_total(_sum_localized_decimal(row.get("gap_caixas") for row in rows)),
                "total_caixas": _format_box_total(_sum_localized_decimal(row.get("total_caixas") for row in rows)),
                "max_pdvs_por_rota": max_size,
            },
            "routes": routes,
        }

    def list_recolhas(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        self.recolha_request_service.normalize_grouped_comodato_requests()
        records = self.recolha_request_service.list_all_requests()
        records = [record for record in records if self._panel_context_allows_recolha(context, record)]
        baixa_validation_map = self._build_recolha_baixa_validation_map(records)
        requester_name_cache: dict[str, str] = {}
        grouped: dict[str, dict[str, Any]] = {}
        for record in records:
            revenda = str(record.revenda or "").strip() or "Sem operacao"
            bucket = grouped.setdefault(
                revenda,
                {
                    "revenda": revenda,
                    "total": 0,
                    "abertas": 0,
                    "lancadas": 0,
                    "recolhidas": 0,
                    "nao_recolhidas": 0,
                    "records": [],
                },
            )
            bucket["total"] += 1
            bucket[_recolha_status_bucket(record)] += 1
            bucket["records"].append(
                self._serialize_recolha_request(
                    record,
                    baixa_validation_map.get(str(record.id or "")),
                    requester_name_cache=requester_name_cache,
                )
            )

        operations = sorted(grouped.values(), key=lambda item: str(item["revenda"]).lower())
        return {"total": len(records), "operations": operations}

    def export_recolhas_csv(
        self,
        context: dict[str, Any] | None = None,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[bytes, int, str]:
        self.recolha_request_service.normalize_grouped_comodato_requests()
        start = _parse_admin_recolha_export_date(start_date, label="Data inicial")
        end = _parse_admin_recolha_export_date(end_date, label="Data final")
        if start and end and start > end:
            raise HTTPException(status_code=400, detail="Periodo invalido. A data inicial nao pode ser maior que a final.")

        records = self.recolha_request_service.list_all_requests()
        records = [record for record in records if self._panel_context_allows_recolha(context, record)]
        if start or end:
            filtered_records = []
            for record in records:
                created_date = _recolha_record_created_date(record)
                if created_date is None:
                    continue
                if start and created_date < start:
                    continue
                if end and created_date > end:
                    continue
                filtered_records.append(record)
            records = filtered_records

        csv_bytes = self.recolha_request_service.export_csv_bytes(records, include_meta=True)
        generated_at = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"relatorio_recolhas_{generated_at}.csv"
        return csv_bytes, len(records), filename

    def update_recolha(
        self,
        recolha_id: str,
        payload: Any,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        identifier = str(recolha_id or "").strip()
        if not identifier:
            raise HTTPException(status_code=400, detail="ID da recolha nao informado.")
        current_record = self.recolha_request_service.find_latest(identifier=identifier)
        if current_record is None:
            raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
        if not self._panel_context_allows_recolha(context, current_record):
            raise HTTPException(status_code=403, detail="Recolha fora das filiais liberadas para este financeiro.")

        updates: dict[str, str] = {}
        if getattr(payload, "lancado_faturista", None) is not None:
            status = _normalize_recolha_status(payload.lancado_faturista)
            updates["lancado_faturista"] = "Ok" if status == "Ok" else "Nok"
        for field_name in ("motorista_faturista", "placa_faturista", "mapa_faturista", "motivo_caixa_noturno"):
            value = getattr(payload, field_name, None)
            if value is not None:
                updates[field_name] = str(value or "").strip()
        if getattr(payload, "status_caixa_noturno", None) is not None:
            status = _normalize_recolha_status(payload.status_caixa_noturno)
            updates["status_caixa_noturno"] = status or "Não Recolhido"
            if status == "Recolhido" and getattr(payload, "motivo_caixa_noturno", None) is None:
                updates["motivo_caixa_noturno"] = ""

        if not updates:
            raise HTTPException(status_code=400, detail="Nenhum campo de recolha informado para atualizar.")

        record = self.recolha_request_service.update_latest(identifier=identifier, updates=updates)
        if record is None:
            raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
        return {"record": self._serialize_recolha_request(record)}

    def update_recolhas_bulk(
        self,
        payload: Any,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ids: list[str] = []
        seen: set[str] = set()
        for raw_id in payload.ids:
            item = str(raw_id or "").strip()
            if not item or item in seen:
                continue
            seen.add(item)
            ids.append(item)
        if not ids:
            raise HTTPException(status_code=400, detail="Nenhuma recolha selecionada para atualizar.")
        if len(ids) > 500:
            raise HTTPException(status_code=400, detail="Atualizacao em lote limitada a 500 recolhas por vez.")

        updated: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for recolha_id in ids:
            try:
                result = self.update_recolha(recolha_id, payload, context)
                updated.append(result["record"])
            except HTTPException as exc:
                errors.append({"id": recolha_id, "status_code": exc.status_code, "detail": exc.detail})
        return {"updated": len(updated), "errors": errors, "records": updated}

    def import_recolhas_csv(self, upload: UploadFile, context: dict[str, Any] | None = None) -> dict[str, Any]:
        filename = str(upload.filename or "").strip()
        if not filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Envie um arquivo CSV de recolhas.")
        buffer = io.BytesIO()
        try:
            self.copy_upload_with_limit(upload, buffer)
        except HTTPException:
            raise
        finally:
            upload.file.close()

        replace_filter = (
            None
            if (context is None or bool(context.get("is_admin")))
            else (lambda record: self._panel_context_allows_recolha(context, record))
        )
        try:
            result = self.recolha_request_service.import_csv_bytes(buffer.getvalue(), replace_filter=replace_filter)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        self.recolha_request_service.normalize_grouped_comodato_requests()
        return {
            **result,
            "filename": filename,
            "mode": "replace_all" if replace_filter is None else "replace_allowed_filiais",
        }

    def delete_recolha(self, recolha_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        identifier = str(recolha_id or "").strip()
        if not identifier:
            raise HTTPException(status_code=400, detail="ID da recolha nao informado.")
        current_record = self.recolha_request_service.find_latest(identifier=identifier)
        if current_record is None:
            raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
        if not self._panel_context_allows_recolha(context, current_record):
            raise HTTPException(status_code=403, detail="Recolha fora das filiais liberadas para este financeiro.")

        deleted = self.recolha_request_service.delete_latest(identifier=identifier)
        if deleted is None:
            raise HTTPException(status_code=404, detail="Solicitacao de recolha nao encontrada.")
        return {"record": self._serialize_recolha_request(deleted)}

    def _build_recolha_baixa_validation_map(self, records: list[Any]) -> dict[str, dict[str, Any]]:
        validation: dict[str, dict[str, Any]] = {}
        candidates: list[tuple[str, str, str, str]] = []
        checked_at = datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec="seconds")

        for record in records:
            record_id = str(getattr(record, "id", "") or "")
            status = _normalize_recolha_status(getattr(record, "status_caixa_noturno", ""))
            if status != "Recolhido":
                validation[record_id] = {
                    "status": "aguardando",
                    "label": "Aguardando fechamento",
                    "checked_at": checked_at,
                }
                continue
            filial = self._recolha_record_filial(record)
            nb = normalize_numeric_code(getattr(record, "nb", "") or "")
            comodato_number = _extract_recolha_comodato_number(getattr(record, "comodato", "") or "")
            if not filial or not nb or not comodato_number:
                validation[record_id] = {
                    "status": "sem_numero",
                    "label": "Sem numero para validar",
                    "checked_at": checked_at,
                }
                continue
            candidates.append((record_id, filial, nb, comodato_number))

        if not candidates:
            return validation

        try:
            pending_keys = self.comodatos_query_service.pending_comodato_keys_for_clients(
                [(filial, nb) for _, filial, nb, _ in candidates]
            )
        except Exception as exc:
            self.logger.warning("Falha ao validar baixa de recolhas na base de comodatos: %s", exc)
            for record_id, _, _, _ in candidates:
                validation[record_id] = {
                    "status": "erro",
                    "label": "Validacao indisponivel",
                    "checked_at": checked_at,
                }
            return validation

        for record_id, filial, nb, comodato_number in candidates:
            validation[record_id] = {
                "status": "pendente" if (filial, nb, comodato_number) in pending_keys else "baixado",
                "label": "Ainda consta na base" if (filial, nb, comodato_number) in pending_keys else "Baixado na base",
                "checked_at": checked_at,
            }
        return validation

    def _resolve_recolha_solicitante_nome(self, record: Any, cache: dict[str, str] | None = None) -> str:
        saved_name = str(getattr(record, "solicitante_nome", "") or "").strip()
        if saved_name:
            return saved_name
        raw_solicitante = str(getattr(record, "solicitante", "") or "").strip()
        if not raw_solicitante:
            return ""
        cache_key = "".join(char for char in raw_solicitante if char.isdigit()) or raw_solicitante
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        try:
            user = self.access_control.get_user(raw_solicitante)
        except Exception:
            user = None
        resolved_name = str((user or {}).get("name") or "").strip()
        if cache is not None:
            cache[cache_key] = resolved_name
        return resolved_name

    def _serialize_recolha_request(
        self,
        record: Any,
        baixa_validation: dict[str, Any] | None = None,
        requester_name_cache: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        comodato = str(record.comodato or "")
        return {
            "id": str(record.id or ""),
            "criado_em": str(record.criado_em or ""),
            "criado_em_iso": _recolha_created_at_iso(str(record.criado_em or "")),
            "filial": self._recolha_record_filial(record),
            "solicitante": str(record.solicitante or ""),
            "solicitante_nome": self._resolve_recolha_solicitante_nome(record, requester_name_cache),
            "revenda": str(record.revenda or ""),
            "data": str(record.data or ""),
            "setor": str(record.setor or ""),
            "cidade": str(record.cidade or ""),
            "rn": str(record.rn or ""),
            "nb": str(record.nb or ""),
            "comodato": comodato,
            "comodato_numero": _extract_recolha_comodato_number(comodato),
            "obs": str(record.obs or ""),
            "lancado_faturista": str(record.lancado_faturista or ""),
            "motorista_faturista": str(record.motorista_faturista or ""),
            "placa_faturista": str(record.placa_faturista or ""),
            "mapa_faturista": str(record.mapa_faturista or ""),
            "status_caixa_noturno": str(record.status_caixa_noturno or ""),
            "motivo_caixa_noturno": str(record.motivo_caixa_noturno or ""),
            "baixa_validacao": baixa_validation or {},
        }

    def _recolha_record_filial(self, record: Any) -> str:
        raw_revenda = str(getattr(record, "revenda", "") or "").strip()
        direct_code = normalize_numeric_code(raw_revenda)
        if direct_code:
            return direct_code
        label_map = {_normalize_label_key(label): code for code, label in self.filial_labels.items()}
        return label_map.get(_normalize_label_key(raw_revenda), "")

    def _panel_context_allows_recolha(self, context: dict[str, Any] | None, record: Any) -> bool:
        if not context or bool(context.get("is_admin")):
            return True
        if self.panel_context_is_critica_only(context):
            return False
        if self.panel_context_has_all_filiais(context):
            return True
        allowed_filiais = {str(filial).strip() for filial in context.get("filiais", ()) if str(filial).strip()}
        record_filial = self._recolha_record_filial(record)
        return bool(record_filial and record_filial in allowed_filiais)

    def _panel_context_allowed_report_scopes(
        self,
        context: dict[str, Any] | None,
    ) -> tuple[list[str] | None, list[str] | None]:
        if not context or bool(context.get("is_admin")):
            return None, None
        if self.panel_context_has_all_filiais(context):
            return None, None
        allowed_filiais = [
            str(filial).strip()
            for filial in context.get("filiais", ())
            if str(filial).strip() and str(filial).strip() != "*"
        ]
        return allowed_filiais, None


def _normalize_recolha_status(value: str | None) -> str:
    normalized = " ".join(
        str(value or "")
        .strip()
        .replace("ÃƒÂ£", "ã")
        .replace("ÃƒÂ§", "ç")
        .replace("NÃ£o", "Não")
        .replace("nÃ£o", "não")
        .split()
    )
    comparable = "".join(
        char
        for char in unicodedata.normalize("NFD", normalized.lower())
        if unicodedata.category(char) != "Mn"
    )
    if comparable in {"ok", "sim", "s", "lancado"}:
        return "Ok"
    if comparable in {"nok", "nao", "n", "nao lancado"}:
        return "Nok"
    if comparable == "recolhido":
        return "Recolhido"
    if comparable in {"nao recolhido", "nao-recolhido"}:
        return "Não Recolhido"
    return normalized


def _extract_recolha_comodato_number(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    labeled_match = re.search(
        r"\b(?:comodato|pedido|numero|nro|num)\s*[:#-]?\s*([A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*)",
        raw,
        flags=re.IGNORECASE,
    )
    if labeled_match:
        return normalize_numeric_code(labeled_match.group(1))

    if re.fullmatch(r"[A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*", raw):
        return normalize_numeric_code(raw)

    leading_match = re.match(
        r"^\s*([A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*)\s*(?:[|;/,]|-\s+)",
        raw,
    )
    if leading_match:
        return normalize_numeric_code(leading_match.group(1))

    return ""


def _recolha_status_bucket(record: Any) -> str:
    status = _normalize_recolha_status(getattr(record, "status_caixa_noturno", ""))
    lancado = _normalize_recolha_status(getattr(record, "lancado_faturista", ""))
    comparable_status = "".join(
        char for char in unicodedata.normalize("NFD", status.lower()) if unicodedata.category(char) != "Mn"
    )
    if comparable_status == "recolhido":
        return "recolhidas"
    if comparable_status == "nao recolhido":
        return "nao_recolhidas"
    if lancado == "Ok":
        return "lancadas"
    return "abertas"


def _recolha_created_at_iso(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return ""


def _normalize_label_key(value: str) -> str:
    text = "".join(
        char for char in unicodedata.normalize("NFD", str(value or "").strip().lower())
        if unicodedata.category(char) != "Mn"
    )
    return "".join(char for char in text if char.isalnum())


def _parse_admin_recolha_export_date(value: str | None, *, label: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} invalida. Use AAAA-MM-DD.") from exc


def _recolha_record_created_date(record: Any) -> date | None:
    iso = _recolha_created_at_iso(str(getattr(record, "criado_em", "") or ""))
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        return None


def _route_day_sort_key(value: str) -> tuple[int, str]:
    normalized = str(value or "").upper()
    order = {
        "SEG": 1,
        "TER": 2,
        "QUA": 3,
        "QUI": 4,
        "SEX": 5,
        "SAB": 6,
        "DOM": 7,
    }
    for token, index in order.items():
        if token in normalized:
            return index, normalized
    return 99, normalized


def _parse_localized_decimal(value: Any) -> Decimal:
    raw = str(value or "").strip()
    if not raw:
        return Decimal("0")
    raw = raw.replace("R$", "").replace("+", "").strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _sum_localized_decimal(values: Any) -> Decimal:
    return sum((_parse_localized_decimal(value) for value in values), Decimal("0"))


def _format_decimal_br(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def _format_box_total(value: Decimal) -> str:
    return str(int(value.to_integral_value()))
