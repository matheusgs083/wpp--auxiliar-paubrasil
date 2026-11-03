from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re
import unicodedata
from typing import Any


ROUTINE_031120 = "031120_BOT"


class LigaEntregaOperationalMapsService:
    """Acompanhamento diário da portaria 03.11.20 para a aba Entrega.

    A consulta é somente leitura e usa as linhas já persistidas no SQL.  Ao
    contrário da visão Financeiro, ela não descarta mapas incompletos: eles são
    justamente os que precisam aparecer como pendência no acompanhamento.
    """

    def __init__(self, *, raw_sql_import_service: Any | None) -> None:
        self.raw_sql_import_service = raw_sql_import_service

    def build_dashboard(self, *, competencia: str | None = None, period: str = "atual") -> dict[str, Any]:
        if self.raw_sql_import_service is None:
            return self._empty(competencia or "", "A fonte SQL da 03.11.20 não está disponível.")
        try:
            records = self.raw_sql_import_service.rows_for_routine(
                routine=ROUTINE_031120,
                competencia=competencia or None,
                period=period,
            )
        except TypeError:
            records = self.raw_sql_import_service.rows_for_routine(
                routine=ROUTINE_031120,
                competencia=competencia or None,
            )
        return self._build_from_records(records, competencia=competencia or "")

    @classmethod
    def _build_from_records(cls, records: list[dict[str, Any]], *, competencia: str) -> dict[str, Any]:
        if not records:
            return cls._empty(competencia, "Nenhuma 03.11.20 foi importada para esta competência.")

        # rows_for_routine já vem por importação decrescente. Mantemos somente
        # a versão mais recente de cada arquivo para não misturar reimportações.
        selected_sources: set[str] = set()
        seen_filenames: set[str] = set()
        for record in records:
            source_key = str(record.get("source_key") or "")
            filename = str(record.get("filename") or "").strip()
            if not source_key or not filename or filename in seen_filenames:
                continue
            seen_filenames.add(filename)
            selected_sources.add(source_key)
        selected = [row for row in records if str(row.get("source_key") or "") in selected_sources]
        if not selected:
            return cls._empty(competencia, "Nenhuma linha reconhecida da 03.11.20 foi encontrada.")

        maps: dict[tuple[str, str, str], dict[str, Any]] = {}
        for record in selected:
            row = record.get("payload") if isinstance(record.get("payload"), Mapping) else {}
            mapa = cls._mapa(cls._pick(row, "Mapa"))
            if not mapa:
                continue
            filename = str(record.get("filename") or "")
            filial = cls._filial(filename)
            key = (str(record.get("source_key") or ""), filial, mapa)
            bucket = maps.setdefault(
                key,
                {"filial": filial or "-", "mapa": mapa, "placa": "", "motorista": "", "events": {}},
            )
            placa = cls._pick(row, "Placa")
            motorista = cls._pick(row, "Motorista", "Nome Motorista")
            if placa and not bucket["placa"]:
                bucket["placa"] = placa
            if motorista and not bucket["motorista"]:
                bucket["motorista"] = motorista
            phase = cls._phase(cls._pick(row, "Fase"))
            when = cls._datetime(cls._pick(row, "DtOper", "Data Operação", "Data Operacao"), cls._pick(row, "HrOper", "Hora Operação", "Hora Operacao"))
            if phase and when:
                old = bucket["events"].get(phase)
                # Para cada marco, guardamos o último horário registrado.
                if old is None or when > old:
                    bucket["events"][phase] = when

        output: list[dict[str, Any]] = []
        now = datetime.now()
        for bucket in maps.values():
            events = bucket["events"]
            carregado = events.get("carregado")
            saida = events.get("saida")
            entrada = events.get("entrada")
            fisico = events.get("fisico")
            financeiro = events.get("financeiro")
            route_day = (saida or carregado or entrada or fisico or financeiro)
            if route_day is None:
                continue
            operational, operational_ok = cls._operational_status(saida, entrada, financeiro)
            closing, closing_ok = cls._closing_status(entrada, fisico, financeiro)
            route_minutes = cls._duration_minutes(saida, entrada or now if saida else None)
            internal_physical_minutes = cls._duration_minutes(entrada, fisico)
            internal_financial_minutes = cls._duration_minutes(fisico, financeiro)
            internal_total_minutes = cls._duration_minutes(entrada, financeiro)
            skipped_mpd = bool(financeiro and not entrada)
            alerts: list[str] = []
            if internal_total_minutes is not None and internal_total_minutes > 30:
                alerts.append("TI total acima de 30 min")
            if route_minutes is not None and route_minutes > 48 * 60:
                alerts.append("Mais de 2 dias em rota")
            if skipped_mpd:
                alerts.append("Pulou MPD")
            output.append(
                {
                    "data": route_day.date().isoformat(),
                    "filial": bucket["filial"],
                    "mapa": bucket["mapa"],
                    "placa": bucket["placa"] or "-",
                    "motorista": bucket["motorista"] or "-",
                    "carregado": cls._fmt_datetime(carregado),
                    "saida": cls._fmt_datetime(saida),
                    "entrada": cls._fmt_datetime(entrada),
                    "fechamento_fisico": cls._fmt_datetime(fisico),
                    "fechamento_financeiro": cls._fmt_datetime(financeiro),
                    "tempo_rota": cls._fmt_minutes(route_minutes),
                    "tempo_interno_fisico": cls._fmt_minutes(internal_physical_minutes),
                    "tempo_interno_financeiro": cls._fmt_minutes(internal_financial_minutes),
                    "tempo_interno_total": cls._fmt_minutes(internal_total_minutes),
                    "ti_total_acima_30min": internal_total_minutes is not None and internal_total_minutes > 30,
                    "em_rota_acima_2dias": route_minutes is not None and route_minutes > 48 * 60,
                    "pulou_mpd": skipped_mpd,
                    "alertas": alerts,
                    "status_operacional": operational,
                    "status_fechamento": closing,
                    "status_tone": "ok" if operational_ok and closing_ok else "warning" if entrada else "pending",
                }
            )

        by_day: dict[str, list[dict[str, Any]]] = {}
        for item in output:
            by_day.setdefault(item["data"], []).append(item)
        days: list[dict[str, Any]] = []
        for day, maps_for_day in sorted(by_day.items(), reverse=True):
            maps_for_day.sort(key=lambda item: (item["filial"], cls._map_sort_key(item["mapa"])))
            days.append({"data": day, "summary": cls._summary(maps_for_day), "maps": maps_for_day})
        all_maps = [item for day in days for item in day["maps"]]
        result_competencia = competencia or cls._infer_competencia(records, output)
        return {
            "ok": True,
            "competencia": result_competencia,
            "days": days,
            "summary": cls._summary(all_maps) | {"dias": len(days), "files": len(selected_sources)},
            "warnings": [] if output else ["A 03.11.20 importada não possui fases de portaria com data e hora válidas."],
        }

    @staticmethod
    def _summary(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "mapas": len(rows),
            "retornados": sum(row["status_operacional"] == "Retornou" for row in rows),
            "fisico_fechado": sum(bool(row["fechamento_fisico"] != "-") for row in rows),
            "financeiro_fechado": sum(bool(row.get("fechamento_financeiro") not in {None, "", "-"}) for row in rows),
            "pendentes": sum(not bool(row.get("fechamento_financeiro") not in {None, "", "-"}) for row in rows),
            "ti_total_acima_30min": sum(bool(row.get("ti_total_acima_30min")) for row in rows),
            "em_rota_acima_2dias": sum(bool(row.get("em_rota_acima_2dias")) for row in rows),
            "pulou_mpd": sum(bool(row.get("pulou_mpd")) for row in rows),
        }

    @staticmethod
    def _empty(competencia: str, warning: str) -> dict[str, Any]:
        return {"ok": True, "competencia": competencia, "days": [], "summary": {"mapas": 0, "dias": 0, "retornados": 0, "fisico_fechado": 0, "financeiro_fechado": 0, "pendentes": 0, "ti_total_acima_30min": 0, "em_rota_acima_2dias": 0, "pulou_mpd": 0, "files": 0}, "warnings": [warning]}

    @staticmethod
    def _pick(row: Mapping[str, Any], *names: str) -> str:
        normalized = {LigaEntregaOperationalMapsService._normal(key): str(value or "").strip() for key, value in row.items()}
        return next((normalized.get(LigaEntregaOperationalMapsService._normal(name), "") for name in names if normalized.get(LigaEntregaOperationalMapsService._normal(name), "")), "")

    @staticmethod
    def _normal(value: Any) -> str:
        text = unicodedata.normalize("NFD", str(value or ""))
        return "".join(char for char in text if unicodedata.category(char) != "Mn").casefold().replace(" ", "").replace("_", "")

    @staticmethod
    def _mapa(value: str) -> str:
        digits = re.sub(r"\D", "", value)
        return (digits.lstrip("0") or "0") if digits else ""

    @staticmethod
    def _filial(filename: str) -> str:
        text = str(filename or "").upper()
        if "SUME" in text:
            return "SUME"
        if "PATOS" in text:
            return "PATOS"
        return ""

    @classmethod
    def _phase(cls, value: str) -> str:
        text = cls._normal(value).upper()
        if text == "CARREGADO":
            return "carregado"
        if "SAIDA" in text and ("CDD" in text or "FAB" in text):
            return "saida"
        if "ENTRADA" in text and ("CDD" in text or "FAB" in text):
            return "entrada"
        if "PCFISICA" in text:
            return "fisico"
        if "PCFINANCEIRA" in text:
            return "financeiro"
        return ""

    @staticmethod
    def _datetime(date_value: str, time_value: str) -> datetime | None:
        date_value, time_value = str(date_value or "").strip(), str(time_value or "").strip()
        if not date_value:
            return None
        for date_fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            for time_fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(f"{date_value} {time_value}", f"{date_fmt} {time_fmt}")
                except ValueError:
                    continue
        return None

    @staticmethod
    def _fmt_datetime(value: datetime | None) -> str:
        return value.strftime("%d/%m %H:%M") if value else "-"

    @staticmethod
    def _fmt_duration(start: datetime | None, end: datetime | None) -> str:
        return LigaEntregaOperationalMapsService._fmt_minutes(LigaEntregaOperationalMapsService._duration_minutes(start, end))

    @staticmethod
    def _duration_minutes(start: datetime | None, end: datetime | None) -> int | None:
        if not start or not end or end < start:
            return None
        return int((end - start).total_seconds() // 60)

    @staticmethod
    def _fmt_minutes(minutes: int | None) -> str:
        if minutes is None:
            return "-"
        return f"{minutes // 60}h {minutes % 60:02d}min"

    @staticmethod
    def _operational_status(saida: datetime | None, entrada: datetime | None, financeiro: datetime | None) -> tuple[str, bool]:
        if financeiro and not entrada:
            return "Fechado sem MPD", True
        if saida and entrada:
            return "Retornou", True
        if saida:
            return "Em rota / sem entrada", False
        return "Sem saída", False

    @staticmethod
    def _closing_status(entrada: datetime | None, fisico: datetime | None, financeiro: datetime | None) -> tuple[str, bool]:
        if financeiro and not entrada:
            return "Fechado sem MPD", True
        if entrada and fisico and financeiro:
            return "Fechado", True
        if entrada and not fisico:
            return "Entrada sem fechamento físico", False
        if entrada and fisico and not financeiro:
            return "Físico sem fechamento financeiro", False
        return "Ainda sem entrada", False

    @staticmethod
    def _map_sort_key(value: str) -> tuple[int, str]:
        return (0, f"{int(value):010d}") if str(value).isdigit() else (1, str(value))

    @staticmethod
    def _infer_competencia(records: list[dict[str, Any]], output: list[dict[str, Any]]) -> str:
        for record in records:
            if str(record.get("competencia") or ""):
                return str(record["competencia"])
        return str(output[0]["data"])[:7] if output else ""
