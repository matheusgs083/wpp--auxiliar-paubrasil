from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re
import unicodedata
from typing import Any


R030805 = "030805_LIGA"
R03114902 = "03114902_BOT"
# A planilha de jornada desconta 1h de almoço da jornada total.
ALMOCO_MINUTOS = 60
MINUTOS_DIA = 24 * 60


class JornadaMapasIndicadoresService:
    """Cruza planejamento 03.11.49.02 com execução 03.08.05 por mapa."""

    def __init__(
        self,
        *,
        raw_sql_import_service: Any | None,
        justificativas_service: Any | None = None,
        pallets_service: Any | None = None,
        frota_service: Any | None = None,
    ) -> None:
        self.raw_sql_import_service = raw_sql_import_service
        self.justificativas_service = justificativas_service
        self.pallets_service = pallets_service
        self.frota_service = frota_service

    def build_dashboard(self, *, competencia: str | None = None) -> dict[str, Any]:
        comp = str(competencia or "").strip()
        planned = self._rows(R03114902, comp)
        operational = self._rows(R030805, comp)
        maps: dict[tuple[str, str, str], dict[str, Any]] = {}
        by_branch_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
        processed_operational: set[tuple[str, str, str]] = set()

        for row in planned:
            data = self._date(self._pick(row, "Data Entrega", "Data", "Data Movimento"))
            filial = self._branch(row)
            mapa = self._mapa(self._pick(row, "Nro do Mapa", "Mapa"))
            if not data or not filial or not mapa:
                continue
            item = {
                "competencia": comp or data[:7], "data": data, "filial": filial, "mapa": mapa,
                "placa": self._pick(row, "Placa"), "motorista": self._code(self._pick(row, "Motorista")),
                "rota": self._pick(row, "Cidades +Entregas", "Região +Entregas", "Regiao +Entregas") or "Não informada",
                "peso_kg": self._number(self._pick(row, "Total peso", "PesoCargaKG")),
                "capacidade_kg": None, "ocupacao_percentual": None,
                "entregas": self._integer(self._pick(row, "Entregas")),
                "tempo_previsto": self._pick(row, "Tempo Prev. (+almoço)", "Tempo Prev. (+almoco)", "TempoPrev"),
                "saida": "", "entrada": "", "cx_carregadas": None, "cx_entregues": None,
                "devolucao_caixas": None, "tem_03114902": True, "tem_030805": False,
            }
            # A leitura SQL vem da importação mais recente para a mais antiga.
            # Preservamos a primeira ocorrência para não misturar reenvios do
            # mesmo mapa na mesma competência.
            key = (data, filial, mapa)
            if key in maps:
                continue
            maps[key] = item
            by_branch_map.setdefault((filial, mapa), []).append(item)

        for row in operational:
            data = self._date(self._pick(row, "Data"))
            filial = self._branch(row)
            mapa = self._mapa(self._pick(row, "Mapa"))
            if not data or not filial or not mapa:
                continue
            row_key = (data, filial, mapa)
            if row_key in processed_operational:
                continue
            processed_operational.add(row_key)
            target = maps.get((data, filial, mapa))
            if target is None:
                candidates = by_branch_map.get((filial, mapa), [])
                target = candidates[0] if len(candidates) == 1 else None
            if target is None:
                target = {
                    "competencia": comp or data[:7], "data": data, "filial": filial, "mapa": mapa,
                    "placa": "", "motorista": "", "rota": "Não informada", "peso_kg": None,
                    "capacidade_kg": None, "ocupacao_percentual": None,
                    "entregas": None, "tempo_previsto": "", "saida": "", "entrada": "",
                    "cx_carregadas": None, "cx_entregues": None, "devolucao_caixas": None,
                    "tem_03114902": False, "tem_030805": False,
                }
                maps[(data, filial, mapa)] = target
                by_branch_map.setdefault((filial, mapa), []).append(target)
            target["tem_030805"] = True
            target["placa"] = target["placa"] or self._pick(row, "Placa")
            target["motorista"] = target["motorista"] or self._code(self._pick(row, "CdMot", "Motorista"))
            target["peso_kg"] = target["peso_kg"] if target["peso_kg"] is not None else self._number(self._pick(row, "PesoCargaKG", "Total peso"))
            capacity = self._number(self._pick(row, "CapacidadeVeiculoKG"))
            target["capacidade_kg"] = capacity if capacity and capacity > 0 else target.get("capacidade_kg")
            reported_occupation = self._number(self._pick(row, "Ocup."))
            if reported_occupation is not None and reported_occupation > 0:
                target["ocupacao_percentual"] = round(reported_occupation, 2)
            elif target.get("peso_kg") is not None and target.get("capacidade_kg"):
                target["ocupacao_percentual"] = round(float(target["peso_kg"]) / float(target["capacidade_kg"]) * 100, 2)
            target["entregas"] = target["entregas"] if target["entregas"] is not None else self._integer(self._pick(row, "Entregas"))
            target["tempo_previsto"] = target["tempo_previsto"] or self._pick(row, "TempoPrev", "Tempo Prev")
            target["saida"] = self._pick(row, "HrSai", "Hora Saida")
            target["entrada"] = self._pick(row, "HrEntr", "Hora Entrada")
            target["tempo_interno"] = self._pick(row, "TmpoInterno")
            loaded = self._number(self._pick(row, "CxCarreg"))
            delivered = self._number(self._pick(row, "CxEntreg"))
            target["cx_carregadas"] = loaded
            target["cx_entregues"] = delivered
            target["devolucao_caixas"] = round(max(loaded - delivered, 0), 2) if loaded is not None and delivered is not None else None

        for item in maps.values():
            item.update(self._jornada(item))
        ocupacao_avisos = self._aplicar_pallets(maps.values(), comp)
        rows = sorted(maps.values(), key=lambda item: (item["data"], item["filial"], self._map_sort(item["mapa"])), reverse=True)
        if self.justificativas_service is not None:
            self.justificativas_service.annotate(rows)
        for row in rows:
            justification = row.get("justificativa") or {}
            row["justificada"] = bool(str(justification.get("text") or "").strip())
            occupation_justification = row.get("ocupacao_justificativa") or {}
            row["ocupacao_justificada"] = bool(str(occupation_justification.get("text") or "").strip())
        returned = sum(float(row.get("devolucao_caixas") or 0) for row in rows)
        vehicles = [
            row for row in rows
            if str(row.get("placa") or "").strip()
            and (row.get("pallets") is not None or row.get("ocupacao_percentual") is not None)
        ]
        return {
            "ok": True,
            "competencia": comp,
            "rows": rows,
            "vehicles": vehicles,
            "summary": {
                "mapas": len(rows),
                "com_030805": sum(bool(row["tem_030805"]) for row in rows),
                "devolucao_caixas": round(returned, 2),
                "com_devolucao": sum(float(row.get("devolucao_caixas") or 0) > 0 for row in rows),
                "pendentes": sum(not row["justificada"] for row in rows),
                "justificados": sum(row["justificada"] for row in rows),
                "veiculos_com_ocupacao": len(vehicles),
            },
            "warnings": ([] if rows else ["Aguardando importação da 03.11.49.02 e/ou 03.08.05 para a competência selecionada."]),
            "ocupacao_avisos": ocupacao_avisos,
            "sources": {
                "03114902": "Rota/cidade, peso e entregas planejadas.",
                "030805": "Execução, caixas carregadas e entregues. Devolução = CxCarreg − CxEntreg.",
            },
        }

    def _aplicar_pallets(self, items: Any, competencia: str) -> list[str]:
        """Ocupação por pallets: pallets do mapa ÷ capacidade do caminhão cadastrado."""
        avisos: list[str] = []
        pallets: dict[Any, dict[str, Any]] = {}
        if self.pallets_service is not None and competencia:
            resultado = self.pallets_service.pallets_por_mapa(competencia)
            pallets = resultado.get("mapas") or {}
            avisos.extend(resultado.get("warnings") or [])
        frota = self.frota_service.lookup() if self.frota_service is not None else None
        sem_cadastro: set[str] = set()
        for item in items:
            info = pallets.get((item["filial"], item["mapa"]))
            item["pallets"] = info["pallets"] if info else None
            item["caixas"] = info["caixas"] if info else None
            caminhao = frota.caminhao(item["filial"], item.get("placa")) if frota else None
            item["capacidade_pallets"] = caminhao["capacidade_pallets"] if caminhao else None
            item["caminhao_descricao"] = caminhao["descricao"] if caminhao else ""
            item["meta_ocupacao_pct"] = frota.meta_ocupacao(item["filial"]) if frota else None
            item["ocupacao_pallets_pct"] = (
                round(item["pallets"] / item["capacidade_pallets"] * 100, 2)
                if item["pallets"] is not None and item["capacidade_pallets"]
                else None
            )
            if info and item.get("placa") and not caminhao:
                sem_cadastro.add(f"{item['filial']} {item['placa']}")
        if sem_cadastro:
            avisos.append(f"{len(sem_cadastro)} caminhão(ões) sem capacidade cadastrada na aba Caminhões.")
        return avisos

    @classmethod
    def _jornada(cls, item: Mapping[str, Any]) -> dict[str, Any]:
        """Colunas da planilha de jornada a partir da 03.08.05.

        Início = HrSai; Final = HrEntr + TmpoInterno; Jornada = Final - Início - almoço;
        Diferença = Jornada - Tempo previsto (positiva = passou do previsto).
        """
        inicio = cls._minutes(item.get("saida"))
        entrada = cls._minutes(item.get("entrada"))
        interno = cls._minutes(item.get("tempo_interno"))
        prevista = cls._minutes(item.get("tempo_previsto"))
        final = entrada + (interno or 0) if entrada is not None else None
        jornada = None
        if inicio is not None and final is not None:
            jornada = max((final - inicio) % MINUTOS_DIA - ALMOCO_MINUTOS, 0)
        return {
            "inicio_jornada": cls._clock(inicio),
            "hora_entrada": cls._clock(entrada),
            "hora_final": cls._clock(final),
            "tempo_interno_min": interno,
            "jornada_min": jornada,
            "prevista_min": prevista,
            "dif_jornada_min": jornada - prevista if jornada is not None and prevista is not None else None,
        }

    @staticmethod
    def _minutes(value: Any) -> int | None:
        match = re.fullmatch(r"(\d{1,3}):(\d{2})(?::\d{2})?", str(value or "").strip())
        if not match or int(match.group(2)) > 59:
            return None
        return int(match.group(1)) * 60 + int(match.group(2))

    @staticmethod
    def _clock(minutes: int | None) -> str:
        if minutes is None:
            return ""
        minutes %= MINUTOS_DIA
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _rows(self, routine: str, competencia: str) -> list[dict[str, Any]]:
        if self.raw_sql_import_service is None:
            return []
        try:
            records = self.raw_sql_import_service.rows_for_routine(
                routine=routine,
                competencia=competencia or None,
                period="atual",
            )
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for record in records:
            if not isinstance(record, Mapping) or not isinstance(record.get("payload"), Mapping):
                continue
            source_key = str(record.get("source_key") or "")
            payload = dict(record["payload"])
            marker = (source_key, str(payload))
            if marker in seen:
                continue
            seen.add(marker)
            # A 03.08.05 não traz a UNB em cada linha. O nome do arquivo é a
            # fonte estável para identificar Patos ou Sumé nesse caso.
            payload["_filename"] = str(record.get("filename") or "")
            rows.append(payload)
        return rows

    @staticmethod
    def _normal(value: Any) -> str:
        text = unicodedata.normalize("NFD", str(value or ""))
        return "".join(char for char in text if unicodedata.category(char) != "Mn").casefold().replace(" ", "").replace("_", "").replace(".", "")

    @classmethod
    def _pick(cls, row: Mapping[str, Any], *names: str) -> str:
        normalized = {cls._normal(key): str(value or "").strip() for key, value in row.items()}
        return next((normalized.get(cls._normal(name), "") for name in names if normalized.get(cls._normal(name), "")), "")

    @classmethod
    def _branch(cls, row: Mapping[str, Any]) -> str:
        unb = cls._pick(row, "UNB")
        if unb == "3":
            return "PATOS"
        if unb == "4":
            return "SUME"
        name = " ".join(filter(None, (
            cls._pick(row, "Nome UNB", "Filial"),
            cls._pick(row, "_filename"),
        )))
        normalized = cls._normal(name).upper()
        return "PATOS" if "PATOS" in normalized else "SUME" if "SUME" in normalized else ""

    @staticmethod
    def _date(value: str) -> str:
        text = str(value or "").strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d%m%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        return ""

    @staticmethod
    def _mapa(value: str) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        return digits.lstrip("0") or "0" if digits else ""

    @staticmethod
    def _code(value: str) -> str:
        digits = re.sub(r"\D", "", str(value or ""))
        return digits.lstrip("0") or "0" if digits else ""

    @staticmethod
    def _number(value: str) -> float | None:
        text = str(value or "").strip().replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            return float(text) if text else None
        except ValueError:
            return None

    @classmethod
    def _integer(cls, value: str) -> int | None:
        number = cls._number(value)
        return int(number) if number is not None else None

    @staticmethod
    def _map_sort(value: str) -> tuple[int, str]:
        return (0, f"{int(value):010d}") if str(value).isdigit() else (1, str(value))
