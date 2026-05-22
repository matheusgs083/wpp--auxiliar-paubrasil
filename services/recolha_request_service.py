from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from uuid import uuid4


RECOLHA_SHEET_COLUMNS = (
    "REVENDA",
    "Data",
    "Setor",
    "CIDADE",
    "RN",
    "NB",
    "Comodato",
    "OBS.",
    "Lançado (faturista)",
    "Motorista (faturista)",
    "Placa (faturista)",
    "Mapa (faturista)",
    "Status (Caixa Noturno)",
    "Motivo (Caixa Noturno)",
)
RECOLHA_META_COLUMNS = ("Solicitante", "Solicitante Nome", "Criado em", "ID")
RECOLHA_COLUMNS = RECOLHA_SHEET_COLUMNS + RECOLHA_META_COLUMNS


@dataclass(frozen=True)
class RecolhaRequestRecord:
    id: str
    criado_em: str
    solicitante: str
    revenda: str
    data: str
    setor: str
    cidade: str
    rn: str
    nb: str
    comodato: str
    solicitante_nome: str = ""
    obs: str = ""
    lancado_faturista: str = "Nok"
    motorista_faturista: str = ""
    placa_faturista: str = ""
    mapa_faturista: str = ""
    status_caixa_noturno: str = "Não Recolhido"
    motivo_caixa_noturno: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, str]:
        return {
            "REVENDA": self.revenda,
            "Data": self.data,
            "Setor": self.setor,
            "CIDADE": self.cidade,
            "RN": self.rn,
            "NB": self.nb,
            "Comodato": self.comodato,
            "OBS.": self.obs,
            "Lançado (faturista)": self.lancado_faturista,
            "Motorista (faturista)": self.motorista_faturista,
            "Placa (faturista)": self.placa_faturista,
            "Mapa (faturista)": self.mapa_faturista,
            "Status (Caixa Noturno)": self.status_caixa_noturno,
            "Motivo (Caixa Noturno)": self.motivo_caixa_noturno,
            "Solicitante": self.solicitante,
            "Solicitante Nome": self.solicitante_nome,
            "Criado em": self.criado_em,
            "ID": self.id,
        }

    def to_sheet_row(self) -> dict[str, str]:
        row = self.to_csv_row()
        return {column: str(row.get(column) or "") for column in RECOLHA_SHEET_COLUMNS}

    def to_sheet_tsv_row(self) -> str:
        return "\t".join(_sanitize_sheet_cell(self.to_sheet_row().get(column, "")) for column in RECOLHA_SHEET_COLUMNS)


class RecolhaRequestService:
    def __init__(self, csv_path: Path | str) -> None:
        self.csv_path = Path(csv_path)
        self._lock = RLock()

    def create_request(
        self,
        *,
        solicitante: str,
        revenda: str,
        data: str,
        setor: str,
        cidade: str,
        rn: str,
        nb: str,
        comodato: str,
        obs: str = "",
        solicitante_nome: str = "",
        created_at: datetime | None = None,
    ) -> RecolhaRequestRecord:
        now = created_at or datetime.now().astimezone()
        record = self._build_record(
            solicitante=solicitante,
            solicitante_nome=solicitante_nome,
            revenda=revenda,
            data=data,
            setor=setor,
            cidade=cidade,
            rn=rn,
            nb=nb,
            comodato=comodato,
            obs=obs,
            created_at=now,
        )
        with self._lock:
            self._ensure_file()
            with self.csv_path.open("a", encoding="utf-8-sig", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=RECOLHA_COLUMNS, delimiter=";")
                writer.writerow(record.to_csv_row())
        return record

    def create_requests(
        self,
        *,
        solicitante: str,
        revenda: str,
        data: str,
        setor: str,
        cidade: str,
        rn: str,
        nb: str,
        comodato: str,
        obs: str = "",
        solicitante_nome: str = "",
        created_at: datetime | None = None,
    ) -> list[RecolhaRequestRecord]:
        now = created_at or datetime.now().astimezone()
        comodato_items = split_comodato_selection(comodato)
        records = [
            self._build_record(
                solicitante=solicitante,
                solicitante_nome=solicitante_nome,
                revenda=revenda,
                data=data,
                setor=setor,
                cidade=cidade,
                rn=rn,
                nb=nb,
                comodato=item,
                obs=obs,
                created_at=now,
            )
            for item in comodato_items
        ]
        with self._lock:
            self._ensure_file()
            with self.csv_path.open("a", encoding="utf-8-sig", newline="") as fp:
                writer = csv.DictWriter(fp, fieldnames=RECOLHA_COLUMNS, delimiter=";")
                for record in records:
                    writer.writerow(record.to_csv_row())
        return records

    def normalize_grouped_comodato_requests(self) -> int:
        with self._lock:
            records = [_row_to_record(row) for row in self._read_rows()]
            records = [record for record in records if record is not None]
            normalized_records: list[RecolhaRequestRecord] = []
            changed = False
            for record in records:
                items = split_comodato_selection(record.comodato)
                if len(items) <= 1:
                    normalized_records.append(record)
                    continue
                changed = True
                for index, item in enumerate(items, start=1):
                    normalized_records.append(
                        replace(
                            record,
                            id=f"{record.id}-{index}" if record.id else uuid4().hex[:12],
                            comodato=item,
                        )
                    )
            if changed:
                self._write_records(normalized_records)
            return len(normalized_records) - len(records) if changed else 0

    def list_requests(self, *, limit: int = 50) -> list[RecolhaRequestRecord]:
        with self._lock:
            rows = self._read_rows()
        records = [_row_to_record(row) for row in rows]
        records = [record for record in records if record is not None]
        return records[-max(1, min(int(limit or 50), 500)) :][::-1]

    def list_all_requests(self) -> list[RecolhaRequestRecord]:
        with self._lock:
            rows = self._read_rows()
        records = [_row_to_record(row) for row in rows]
        return [record for record in records if record is not None][::-1]

    def update_latest(
        self,
        *,
        identifier: str,
        updates: dict[str, str],
    ) -> RecolhaRequestRecord | None:
        normalized_identifier = str(identifier or "").strip().lower()
        if not normalized_identifier or not updates:
            return None
        with self._lock:
            records = [_row_to_record(row) for row in self._read_rows()]
            records = [record for record in records if record is not None]
            for index in range(len(records) - 1, -1, -1):
                record = records[index]
                if _matches_identifier(record, normalized_identifier):
                    records[index] = replace(record, **_clean_updates(updates))
                    self._write_records(records)
                    return records[index]
        return None

    def find_latest(self, *, identifier: str) -> RecolhaRequestRecord | None:
        normalized_identifier = str(identifier or "").strip().lower()
        if not normalized_identifier:
            return None
        with self._lock:
            records = [_row_to_record(row) for row in self._read_rows()]
        records = [record for record in records if record is not None]
        for record in reversed(records):
            if _matches_identifier(record, normalized_identifier):
                return record
        return None

    def delete_latest(self, *, identifier: str) -> RecolhaRequestRecord | None:
        normalized_identifier = str(identifier or "").strip().lower()
        if not normalized_identifier:
            return None
        with self._lock:
            records = [_row_to_record(row) for row in self._read_rows()]
            records = [record for record in records if record is not None]
            for index in range(len(records) - 1, -1, -1):
                record = records[index]
                if _matches_identifier(record, normalized_identifier):
                    deleted = records.pop(index)
                    self._write_records(records)
                    return deleted
        return None

    def clear_requests(self) -> int:
        with self._lock:
            records = [_row_to_record(row) for row in self._read_rows()]
            records = [record for record in records if record is not None]
            count = len(records)
            self._write_records([])
            return count

    def import_csv_bytes(
        self,
        payload: bytes,
        *,
        replace_filter: Callable[[RecolhaRequestRecord], bool] | None = None,
    ) -> dict[str, Any]:
        imported_records = parse_recolha_csv_bytes(payload)
        normalized_records = _normalize_grouped_records(imported_records)
        if not normalized_records:
            raise ValueError("CSV de recolhas sem linhas validas.")

        if replace_filter is None:
            allowed_records = normalized_records
            skipped_records: list[RecolhaRequestRecord] = []
        else:
            allowed_records = [record for record in normalized_records if replace_filter(record)]
            skipped_records = [record for record in normalized_records if not replace_filter(record)]
        if not allowed_records:
            raise PermissionError("Nenhuma linha do CSV pertence as filiais liberadas para este token.")

        with self._lock:
            existing_records = [_row_to_record(row) for row in self._read_rows()]
            existing_records = [record for record in existing_records if record is not None]
            if replace_filter is None:
                final_records = allowed_records
                preserved_count = 0
            else:
                preserved_records = [record for record in existing_records if not replace_filter(record)]
                preserved_count = len(preserved_records)
                final_records = preserved_records + allowed_records
            self._write_records(final_records)

        return {
            "imported": len(allowed_records),
            "skipped": len(skipped_records),
            "preserved": preserved_count,
            "total_csv": len(normalized_records),
        }

    def export_csv_bytes(self, records: list[RecolhaRequestRecord] | None = None) -> bytes:
        if records is None:
            with self._lock:
                loaded_records = [_row_to_record(row) for row in self._read_rows()]
            records = [record for record in loaded_records if record is not None]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=RECOLHA_SHEET_COLUMNS, delimiter=";")
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_sheet_row())
        return ("\ufeff" + output.getvalue()).encode("utf-8")

    def count_requests(self) -> int:
        with self._lock:
            return len(self._read_rows())

    def _ensure_file(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if self.csv_path.exists():
            with self.csv_path.open("r", encoding="utf-8-sig", newline="") as fp:
                reader = csv.reader(fp, delimiter=";")
                header = next(reader, [])
            if all(column in header for column in RECOLHA_COLUMNS):
                return
            rows = self._read_rows()
            records = [_row_to_record(row) for row in rows]
            self._write_records([record for record in records if record is not None])
            return
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=RECOLHA_COLUMNS, delimiter=";")
            writer.writeheader()

    def _read_rows(self) -> list[dict[str, str]]:
        if not self.csv_path.exists():
            return []
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as fp:
            return list(csv.DictReader(fp, delimiter=";"))

    def _write_records(self, records: list[RecolhaRequestRecord]) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.csv_path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=RECOLHA_COLUMNS, delimiter=";")
            writer.writeheader()
            for record in records:
                writer.writerow(record.to_csv_row())

    def _build_record(
        self,
        *,
        solicitante: str,
        solicitante_nome: str,
        revenda: str,
        data: str,
        setor: str,
        cidade: str,
        rn: str,
        nb: str,
        comodato: str,
        obs: str,
        created_at: datetime,
    ) -> RecolhaRequestRecord:
        return RecolhaRequestRecord(
            id=uuid4().hex[:12],
            criado_em=created_at.strftime("%d/%m/%Y %H:%M"),
            solicitante=str(solicitante or "").strip(),
            solicitante_nome=str(solicitante_nome or "").strip(),
            revenda=str(revenda or "").strip(),
            data=str(data or "").strip(),
            setor=str(setor or "").strip(),
            cidade=str(cidade or "").strip(),
            rn=str(rn or "").strip(),
            nb=str(nb or "").strip(),
            comodato=str(comodato or "").strip(),
            obs=str(obs or "").strip(),
        )


def _row_to_record(row: dict[str, str]) -> RecolhaRequestRecord | None:
    if not row:
        return None
    now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    return RecolhaRequestRecord(
        id=str(_row_get(row, "ID") or uuid4().hex[:12]).strip(),
        criado_em=str(_row_get(row, "Criado em") or now).strip(),
        solicitante=str(_row_get(row, "Solicitante") or "").strip(),
        revenda=str(_row_get(row, "REVENDA") or "").strip(),
        data=str(_row_get(row, "Data") or "").strip(),
        setor=str(_row_get(row, "Setor") or "").strip(),
        cidade=str(_row_get(row, "CIDADE") or "").strip(),
        rn=str(_row_get(row, "RN") or "").strip(),
        nb=str(_row_get(row, "NB") or "").strip(),
        comodato=str(_row_get(row, "Comodato") or "").strip(),
        solicitante_nome=str(_row_get(row, "Solicitante Nome", "Nome Solicitante") or "").strip(),
        obs=str(_row_get(row, "OBS.") or "").strip(),
        lancado_faturista=str(_row_get(row, "Lançado (faturista)", "Lancado (faturista)") or "Nok").strip(),
        motorista_faturista=str(_row_get(row, "Motorista (faturista)") or "").strip(),
        placa_faturista=str(_row_get(row, "Placa (faturista)") or "").strip(),
        mapa_faturista=str(_row_get(row, "Mapa (faturista)") or "").strip(),
        status_caixa_noturno=str(_row_get(row, "Status (Caixa Noturno)") or "Não Recolhido").strip(),
        motivo_caixa_noturno=str(_row_get(row, "Motivo (Caixa Noturno)") or "").strip(),
    )


def _row_get(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row:
            return str(row.get(key) or "")
    return ""


def _sanitize_sheet_cell(value: str) -> str:
    return " ".join(str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").split())


def split_comodato_selection(value: str) -> list[str]:
    text = _sanitize_sheet_cell(str(value or ""))
    if not text:
        return ["-"]
    matches = list(re.finditer(r"(?i)\bcomodato\s+[A-Za-z0-9_.-]+", text))
    if len(matches) <= 1:
        return [text]

    items: list[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        item = text[start:end].strip(" |;,-")
        if item:
            items.append(item)
    return items or [text]


def parse_recolha_csv_bytes(payload: bytes) -> list[RecolhaRequestRecord]:
    if not payload:
        raise ValueError("Arquivo de recolhas vazio.")
    text = _decode_recolha_csv(payload)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";\t,")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    except csv.Error:
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames:
        raise ValueError("CSV de recolhas sem cabecalho.")
    normalized_headers = {_normalize_header_name(header) for header in reader.fieldnames if header}
    required = {_normalize_header_name(column) for column in ("REVENDA", "NB", "Comodato")}
    missing = required - normalized_headers
    if missing:
        raise ValueError("CSV de recolhas precisa ter ao menos as colunas REVENDA, NB e Comodato.")

    records: list[RecolhaRequestRecord] = []
    for row in reader:
        normalized_row = {_canonical_recolha_column_name(key): value for key, value in row.items()}
        record = _row_to_record(normalized_row)
        if record is not None:
            records.append(record)
    return records


def _decode_recolha_csv(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _canonical_recolha_column_name(value: str) -> str:
    normalized = _normalize_header_name(value)
    mapping = {
        "revenda": "REVENDA",
        "data": "Data",
        "setor": "Setor",
        "cidade": "CIDADE",
        "rn": "RN",
        "nb": "NB",
        "comodato": "Comodato",
        "obs": "OBS.",
        "observacao": "OBS.",
        "observacoes": "OBS.",
        "lancadofaturista": "Lancado (faturista)",
        "motoristafaturista": "Motorista (faturista)",
        "placafaturista": "Placa (faturista)",
        "mapafaturista": "Mapa (faturista)",
        "statuscaixanoturno": "Status (Caixa Noturno)",
        "motivocaixanoturno": "Motivo (Caixa Noturno)",
        "solicitante": "Solicitante",
        "solicitantenome": "Solicitante Nome",
        "nomesolicitante": "Solicitante Nome",
        "criadoem": "Criado em",
        "id": "ID",
    }
    return mapping.get(normalized, value)


def _normalize_header_name(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    normalized = "".join(char for char in unicodedata.normalize("NFD", text) if unicodedata.category(char) != "Mn")
    return "".join(char for char in normalized if char.isalnum())


def _normalize_grouped_records(records: list[RecolhaRequestRecord]) -> list[RecolhaRequestRecord]:
    normalized_records: list[RecolhaRequestRecord] = []
    for record in records:
        items = split_comodato_selection(record.comodato)
        if len(items) <= 1:
            normalized_records.append(record)
            continue
        for index, item in enumerate(items, start=1):
            normalized_records.append(
                replace(
                    record,
                    id=f"{record.id}-{index}" if record.id else uuid4().hex[:12],
                    comodato=item,
                )
            )
    return normalized_records


def _matches_identifier(record: RecolhaRequestRecord, identifier: str) -> bool:
    normalized_id = str(record.id or "").strip().lower()
    normalized_nb = str(record.nb or "").strip().lower()
    if normalized_id:
        if normalized_id == identifier:
            return True
        if "-" not in normalized_id and normalized_id.startswith(identifier):
            return True
    return bool(
        normalized_nb and normalized_nb == identifier
    )


def _clean_updates(updates: dict[str, str]) -> dict[str, str]:
    allowed = {
        "lancado_faturista",
        "motorista_faturista",
        "placa_faturista",
        "mapa_faturista",
        "status_caixa_noturno",
        "motivo_caixa_noturno",
    }
    return {
        key: str(value or "").strip()
        for key, value in updates.items()
        if key in allowed
    }
