from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


class LigaEntregaRouteTeamService:
    """Persiste ajustes manuais de equipe por rota sem alterar os relatórios brutos."""

    def __init__(self, *, database_url: str, schema: str = "reports", connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = str(database_url or "")
        self.schema = str(schema or "reports")
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3), 1.0)

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout_seconds)

    def _ensure_schema(self, conn: Any) -> None:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}" ).format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {}.liga_entrega_route_team_overrides (
                    id BIGSERIAL PRIMARY KEY,
                    competencia VARCHAR(7) NOT NULL,
                    data DATE NOT NULL,
                    filial VARCHAR(80) NOT NULL DEFAULT '',
                    mapa VARCHAR(80) NOT NULL,
                    motorista VARCHAR(40) NOT NULL,
                    ajudantes JSONB NOT NULL DEFAULT '[]'::jsonb,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    actor TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (competencia, data, filial, mapa)
                )
            """).format(sql.Identifier(self.schema)))
            cur.execute(sql.SQL("""
                CREATE INDEX IF NOT EXISTS liga_entrega_route_team_overrides_lookup_idx
                ON {}.liga_entrega_route_team_overrides (competencia, data, filial, mapa, active)
            """).format(sql.Identifier(self.schema)))
        conn.commit()

    @staticmethod
    def _validate_competencia(value: str) -> str:
        value = str(value or "").strip()
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("competencia deve estar no formato AAAA-MM.")
        return value

    @staticmethod
    def _validate_date(value: str) -> str:
        value = str(value or "").strip()
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("data deve estar no formato AAAA-MM-DD.") from exc
        return parsed.isoformat()

    def list_overrides(self, *, competencia: str, active_only: bool = True) -> list[dict[str, Any]]:
        competencia = self._validate_competencia(competencia)
        if not self.database_url:
            return []
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                clause = "WHERE competencia = %s" + (" AND active = TRUE" if active_only else "")
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(sql.SQL("SELECT * FROM {}.liga_entrega_route_team_overrides {} ORDER BY data, mapa").format(sql.Identifier(self.schema), sql.SQL(clause)), (competencia,))
                    return [dict(row) for row in cur.fetchall()]
        except Exception:
            return []

    def upsert_override(self, payload: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
        competencia = self._validate_competencia(payload.get("competencia"))
        data = self._validate_date(payload.get("data"))
        if data[:7] != competencia:
            raise ValueError("data deve pertencer a competencia informada.")
        filial = str(payload.get("filial") or "").strip().upper()
        mapa = str(payload.get("mapa") or "").strip()
        motorista = str(payload.get("motorista") or "").strip()
        ajudantes = []
        for item in payload.get("ajudantes") or []:
            code = str(item or "").strip()
            if code and code not in ajudantes:
                ajudantes.append(code)
        if not mapa or not motorista:
            raise ValueError("mapa e motorista sao obrigatorios.")
        if len(ajudantes) > 2:
            raise ValueError("a rota aceita no maximo dois ajudantes.")
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql.SQL("""
                    INSERT INTO {}.liga_entrega_route_team_overrides
                        (competencia, data, filial, mapa, motorista, ajudantes, active, actor, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, TRUE, %s, NOW())
                    ON CONFLICT (competencia, data, filial, mapa)
                    DO UPDATE SET motorista = EXCLUDED.motorista,
                                  ajudantes = EXCLUDED.ajudantes,
                                  active = TRUE,
                                  actor = EXCLUDED.actor,
                                  updated_at = NOW()
                    RETURNING *
                """).format(sql.Identifier(self.schema)), (competencia, data, filial, mapa, motorista, json.dumps(ajudantes), str(actor or "")))
                row = cur.fetchone()
            conn.commit()
        return dict(row or {})

    def delete_override(self, *, competencia: str, data: str, filial: str, mapa: str, actor: str = "") -> bool:
        competencia = self._validate_competencia(competencia)
        data = self._validate_date(data)
        if not self.database_url:
            return False
        with self._connect() as conn:
            self._ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(sql.SQL("""
                    UPDATE {}.liga_entrega_route_team_overrides
                    SET active = FALSE, actor = %s, updated_at = NOW()
                    WHERE competencia = %s AND data = %s AND filial = %s AND mapa = %s AND active = TRUE
                """).format(sql.Identifier(self.schema)), (str(actor or ""), competencia, data, str(filial or "").strip().upper(), str(mapa or "").strip()))
                changed = cur.rowcount
            conn.commit()
        return bool(changed)
