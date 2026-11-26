"""Importação de coordenadas da 01.20.12, relatório 400, por revenda e NB."""
from __future__ import annotations

import csv
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from bot_api.commercial_scope import normalize_numeric_code

_UNIDADES = {"0640001": "1", "0640002": "2", "2210003": "3", "2210004": "4", "3480005": "5", "3610006": "6", "3610007": "7", "3610008": "8"}
_NOME = re.compile(r"^012012_relatorio_400_(\d{7})\.csv$", re.I)
_COORD = re.compile(r"^\s*([+-]?\d+(?:[,.]\d+)?[+-]?)\s*/\s*([+-]?\d+(?:[,.]\d+)?[+-]?)\s*$")


def _decimal(texto: str) -> Decimal:
    texto = texto.strip().replace(",", ".")
    if texto.endswith(("-", "+")):
        texto = texto[-1] + texto[:-1]
    return Decimal(texto)


def parse_coordenadas(valor: str) -> tuple[Decimal, Decimal] | None:
    achado = _COORD.fullmatch(valor.strip())
    if not achado:
        return None
    try:
        lat, lon = map(_decimal, achado.groups())
    except InvalidOperation:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lat, lon


def ler_arquivo(path: Path) -> tuple[str, list[tuple[str, str, Decimal | None, Decimal | None]]]:
    match = _NOME.fullmatch(path.name)
    if not match or match.group(1) not in _UNIDADES:
        raise ValueError(f"Nome ou unidade invalida para 012012: {path.name}")
    filial = _UNIDADES[match.group(1)]
    rows = []
    encontrados = set()
    # O relatório Salvar da 012012 é texto cp1252, sem cabeçalho, com linhas vazias.
    with path.open("r", encoding="cp1252", newline="") as f:
        for numero, row in enumerate(csv.reader(f, delimiter=";"), 1):
            if not row or all(not x.strip() for x in row):
                continue
            if len(row) != 8 or not row[0].strip().isdigit():
                raise ValueError(f"Linha {numero}: formato invalido no arquivo {path.name}.")
            nb = normalize_numeric_code(row[0].strip())
            if not nb or nb in encontrados:
                raise ValueError(f"Linha {numero}: NB invalido ou duplicado no arquivo {path.name}.")
            encontrados.add(nb)
            raw = row[6].strip()
            coords = parse_coordenadas(raw)
            rows.append((filial, nb, *(coords or (None, None))))
    if not rows:
        raise ValueError(f"Arquivo sem clientes: {path.name}")
    return filial, rows


class Coordenadas012012Service:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("Schema invalido")
        self.database_url, self.schema = database_url, schema
        self.timeout = max(float(connect_timeout_seconds), 1.0)

    def import_files(self, paths: list[Path]) -> dict[str, Any]:
        if not paths:
            raise ValueError("Informe ao menos um CSV da 012012.")
        parsed = [ler_arquivo(p) for p in paths]
        filiais = [filial for filial, _ in parsed]
        if len(set(filiais)) != len(filiais):
            raise ValueError("Mais de um arquivo para a mesma filial.")
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        with psycopg.connect(self.database_url, connect_timeout=self.timeout) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} ").format(sql.Identifier(self.schema)))
                cur.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {}.coordenadas_012012 (
                    filial text NOT NULL, cod_pdv text NOT NULL, latitude numeric(10,7), longitude numeric(11,7),
                    atualizado_em timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (filial, cod_pdv))""").format(sql.Identifier(self.schema)))
                # Serializa importações para que um lote parcial não substitua dados de outra execução.
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.schema + ".coordenadas_012012",))
                for filial, rows in parsed:
                    cur.execute(sql.SQL("DELETE FROM {}.coordenadas_012012 WHERE filial = %s").format(sql.Identifier(self.schema)), (filial,))
                    cur.executemany(sql.SQL("INSERT INTO {}.coordenadas_012012 (filial,cod_pdv,latitude,longitude) VALUES (%s,%s,%s,%s)").format(sql.Identifier(self.schema)), rows)
            conn.commit()
        return {"filiais": filiais, "arquivos": len(paths), "rows": sum(len(rows) for _, rows in parsed), "com_coordenadas": sum(lat is not None for _, rows in parsed for _, _, lat, _ in rows)}

    def buscar(self, filial: str, cliente: str) -> dict[str, str] | None:
        if not self.database_url:
            return None
        query = sql.SQL("""SELECT c.latitude, c.longitude FROM {}.coordenadas_012012 c
            JOIN {}.dclientes_latest d ON d.filial = c.filial AND d.cod_pdv = c.cod_pdv
            WHERE c.filial = %s AND c.cod_pdv = %s AND c.latitude IS NOT NULL AND c.longitude IS NOT NULL LIMIT 1""").format(sql.Identifier(self.schema), sql.Identifier(self.schema))
        try:
            with psycopg.connect(self.database_url, connect_timeout=self.timeout) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (normalize_numeric_code(filial), normalize_numeric_code(cliente)))
                    row = cur.fetchone()
        except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedSchema):
            return None
        return {"latitude": str(row["latitude"]), "longitude": str(row["longitude"])} if row else None
