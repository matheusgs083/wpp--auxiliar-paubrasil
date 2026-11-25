"""Consulta da Rota Financeira: clientes do dia de visita com o risco financeiro de cada um.

Uma única consulta junta, para a página pedida:
- a rota (dClientes, já recortada pelo escopo comercial e pelos filtros);
- os títulos da 12.06.01 agregados por cliente;
- a quantidade de boletos da 03.02.06 por cliente (quando a base existir).

A ordenação, os filtros de situação e a paginação acontecem no banco; o painel
nunca recebe a carteira inteira.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row

from bot_api.db import get_connection_pool
from bot_api.services.dclientes_query_service import (
    _append_scope_value_filter,
    _append_visit_day_filter,
    _build_commercial_scope_filters,
    _has_scope_values,
    _normalize_filial,
    _normalize_scope_values,
    _normalize_search_text,
    _normalized_text_sql,
)
from bot_api.services.inadimplencia_query_service import _days_to_due_sql, _money_to_numeric_sql
from bot_api.services.rota_financeira_giro import FILTRO_GIRO, SITUACOES_GIRO

SITUACOES = ("todos", "vencidos", "ate_dois_dias", "hoje", "amanha", "dois_dias", "com_boleto", "sem_boleto", *SITUACOES_GIRO)
LIMITE_PAGINA = 50

# Faixa de prioridade de cada cliente (menor = mais urgente).
FAIXA_VENCIDO, FAIXA_HOJE, FAIXA_AMANHA, FAIXA_DOIS_DIAS, FAIXA_A_VENCER, FAIXA_SEM_TITULO = 1, 2, 3, 4, 5, 6

_FILTRO_SITUACAO = {
    "todos": "TRUE",
    "vencidos": f"faixa = {FAIXA_VENCIDO}",
    "hoje": f"faixa = {FAIXA_HOJE}",
    "amanha": f"faixa = {FAIXA_AMANHA}",
    "dois_dias": f"faixa = {FAIXA_DOIS_DIAS}",
    # Filtro principal da tela: hoje, amanhã e depois de amanhã juntos.
    "ate_dois_dias": f"faixa IN ({FAIXA_HOJE}, {FAIXA_AMANHA}, {FAIXA_DOIS_DIAS})",
    "com_boleto": "titulos > 0 AND boletos > 0",
    "sem_boleto": "titulos > 0 AND boletos = 0",
    **FILTRO_GIRO,
}


@dataclass(frozen=True)
class RotaFinanceiraPagina:
    clientes: list[dict[str, Any]]
    total: int
    resumo: dict[str, Any]


class RotaFinanceiraQueryService:
    def __init__(self, database_url: str, schema: str, connect_timeout_seconds: float = 3.0) -> None:
        self.database_url = database_url.strip()
        self.schema = schema if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema or "") else "reports"
        self.connect_timeout_seconds = max(float(connect_timeout_seconds), 1.0)
        self._pool = None

    def listar(
        self,
        *,
        dia: str,
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None = None,
        filial: str = "",
        gv: str = "",
        setor: str = "",
        busca: str = "",
        situacao: str = "todos",
        incluir_boletos: bool = True,
        giro: tuple[sql.Composable, list[Any]] | None = None,
        limite: int = 25,
        offset: int = 0,
    ) -> RotaFinanceiraPagina:
        """``giro`` (de ``rota_financeira_giro.ctes_giro``) é obrigatório nos filtros "sem giro"."""
        if situacao not in _FILTRO_SITUACAO:
            raise ValueError("Filtro de situação inválido.")
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")
        if situacao in SITUACOES_GIRO and giro is None:
            raise ValueError("Filtro de giro sem a base do giro.")

        where, params = self._filtros_da_rota(
            dia=dia, allowed_sectors=allowed_sectors, allowed_gv_vdes=allowed_gv_vdes,
            filial=filial, gv=gv, setor=setor, busca=busca,
        )
        base = self._ctes(where, incluir_boletos)
        if situacao in SITUACOES_GIRO and giro is not None:
            # Os CTEs do giro só entram quando o filtro pede: a rota comum não paga por eles.
            ctes_giro, params_giro = giro
            base = sql.Composed([base, ctes_giro])
            params = [*params, *params_giro]
        consulta_pagina = sql.SQL(
            """
            {base}
            SELECT f.*, COUNT(*) OVER () AS total_linhas
            FROM joined f
            WHERE {situacao}
            ORDER BY
                f.faixa,
                CASE WHEN f.faixa = {vencido} THEN f.menor_dias END ASC NULLS LAST,
                f.total_pendente DESC,
                f.nome,
                f.filial,
                f.cod_pdv
            LIMIT %s OFFSET %s
            """
        ).format(base=base, situacao=sql.SQL(_FILTRO_SITUACAO[situacao]), vencido=sql.Literal(FAIXA_VENCIDO))
        consulta_resumo = sql.SQL(
            """
            {base}
            SELECT
                COUNT(*)::int AS clientes,
                COUNT(*) FILTER (WHERE titulos > 0)::int AS clientes_pendencia,
                COALESCE(SUM(titulos), 0)::int AS titulos,
                COALESCE(SUM(total_pendente), 0) AS total_pendente,
                COALESCE(SUM(total_vencido), 0) AS total_vencido,
                COUNT(*) FILTER (WHERE faixa = {vencido})::int AS clientes_vencidos,
                COUNT(*) FILTER (WHERE faixa = {hoje})::int AS vence_hoje,
                COUNT(*) FILTER (WHERE faixa = {amanha})::int AS vence_amanha,
                COUNT(*) FILTER (WHERE faixa = {dois_dias})::int AS vence_dois_dias,
                COUNT(*) FILTER (WHERE titulos > 0 AND boletos > 0)::int AS clientes_com_boleto,
                COUNT(*) FILTER (WHERE titulos > 0 AND boletos = 0)::int AS clientes_sem_boleto,
                COALESCE(SUM(boletos), 0)::int AS boletos,
                COALESCE(SUM(GREATEST(titulos - boletos, 0)) FILTER (WHERE titulos > 0), 0)::int AS titulos_sem_boleto
            FROM joined
            """
        ).format(
            base=base, vencido=sql.Literal(FAIXA_VENCIDO), hoje=sql.Literal(FAIXA_HOJE),
            amanha=sql.Literal(FAIXA_AMANHA), dois_dias=sql.Literal(FAIXA_DOIS_DIAS),
        )

        limite = max(1, min(int(limite), LIMITE_PAGINA))
        offset = max(0, min(int(offset), 10_000))
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(consulta_pagina, [*params, limite, offset])
                linhas = cur.fetchall()
                cur.execute(consulta_resumo, params)
                resumo = cur.fetchone() or {}
        total = int(linhas[0]["total_linhas"]) if linhas else 0
        return RotaFinanceiraPagina(
            clientes=[_linha(row) for row in linhas],
            total=total,
            resumo={chave: _numero(valor) for chave, valor in dict(resumo).items()},
        )

    def _filtros_da_rota(
        self,
        *,
        dia: str,
        allowed_sectors: list[str] | None,
        allowed_gv_vdes: list[str] | None,
        filial: str,
        gv: str,
        setor: str,
        busca: str,
    ) -> tuple[sql.Composed, list[Any]]:
        filters: list[sql.Composed] = []
        params: list[Any] = []
        _append_visit_day_filter(filters=filters, params=params, visit_day=dia)

        # Escopo comercial: mesma regra do dClientes (setores, GVs e operações "filial:N",
        # combinados com OU). Lista com valores que não viram escopo válido fecha o
        # acesso (FALSE), nunca o abre.
        setores = _normalize_scope_values(allowed_sectors)
        gvs = _normalize_scope_values(allowed_gv_vdes)
        if setores or gvs:
            scope_filters, scope_params = _build_commercial_scope_filters(allowed_sectors=setores, allowed_gv_vdes=gvs)
            filters.append(sql.SQL("({})").format(sql.SQL(" OR ").join(scope_filters)) if scope_filters else sql.SQL("FALSE"))
            params.extend(scope_params)
        elif _has_scope_values(allowed_sectors) or _has_scope_values(allowed_gv_vdes):
            filters.append(sql.SQL("FALSE"))

        # Filtros da tela: só estreitam o que o escopo já liberou.
        if filial:
            filters.append(sql.SQL("filial = %s"))
            params.append(_normalize_filial(filial))
        if gv:
            chaves = gv.split(",")
            if len(chaves) > 100 or any(not re.fullmatch(r"\d+_\d+", item) for item in chaves):
                raise ValueError("Filtro de gerentes inválido.")
            gv_filters: list[Any] = []
            gv_params: list[Any] = []
            for chave in chaves:
                _append_scope_value_filter(filters=gv_filters, params=gv_params, value=chave, key_field="filial_gv_key")
            filters.append(sql.SQL("({})").format(sql.SQL(" OR ").join(gv_filters)))
            params.extend(gv_params)
        if setor:
            _append_scope_value_filter(filters=filters, params=params, value=setor, key_field="filial_setor_key")
        texto = _normalize_search_text(busca)
        if texto:
            if texto.isdigit():
                filters.append(sql.SQL("cod_pdv = %s"))
                params.append(texto.lstrip("0") or "0")
            else:
                filters.append(sql.SQL("({} ILIKE %s OR {} ILIKE %s)").format(_normalized_text_sql("nome_fantasia"), _normalized_text_sql("razao_social")))
                params.extend([f"%{texto}%", f"%{texto}%"])
        return sql.SQL(" AND ").join(filters), params

    def _ctes(self, where: sql.Composed, incluir_boletos: bool) -> sql.Composed:
        schema = sql.Identifier(self.schema)
        if incluir_boletos:
            boletos = sql.SQL(
                """
                SELECT b.filial, b.cod_pdv, COUNT(*)::int AS boletos
                FROM {schema}.boletos_latest b
                JOIN route r ON r.filial = b.filial AND r.cod_pdv = b.cod_pdv
                WHERE b.status = 'ok'
                GROUP BY b.filial, b.cod_pdv
                """
            ).format(schema=schema)
        else:
            boletos = sql.SQL("SELECT NULL::text AS filial, NULL::text AS cod_pdv, 0 AS boletos WHERE FALSE")
        return sql.SQL(
            """
            WITH route AS MATERIALIZED (
                SELECT
                    filial,
                    cod_pdv,
                    COALESCE(NULLIF(nome_fantasia, ''), razao_social, '') AS nome,
                    COALESCE(razao_social, '') AS razao_social,
                    COALESCE(payload ->> 'Telefone(s)', '') AS telefone,
                    COALESCE(payload ->> 'Cidade', '') AS cidade,
                    COALESCE(payload ->> 'Dia de Visita do VDE', '') AS dia_visita,
                    COALESCE(status_pdv, '') AS status,
                    COALESCE(payload ->> 'Cond Pag Atual', '') AS cond_pagto,
                    COALESCE(payload ->> 'Limite de Crédito', '') AS limite_credito,
                    COALESCE(filial_setor_key, '') AS setor_key,
                    COALESCE(filial_gv_key, '') AS gv_key
                FROM {schema}.dclientes_latest
                WHERE {where}
            ),
            titulos_raw AS (
                SELECT
                    i.unb AS filial,
                    i.cliente AS cod_pdv,
                    {valor} AS valor,
                    {dias} AS dias,
                    COALESCE(i.data_vencimento, '') AS vencimento
                FROM {schema}.inadimplencia_latest i
                JOIN route r ON r.filial = i.unb AND r.cod_pdv = i.cliente
            ),
            titulos AS (
                SELECT
                    filial,
                    cod_pdv,
                    COUNT(*)::int AS titulos,
                    SUM(valor) AS total_pendente,
                    COALESCE(SUM(valor) FILTER (WHERE dias < 0), 0) AS total_vencido,
                    COUNT(*) FILTER (WHERE dias < 0)::int AS titulos_vencidos,
                    MIN(dias) AS menor_dias,
                    (ARRAY_AGG(vencimento ORDER BY dias ASC NULLS LAST))[1] AS vencimento_proximo
                FROM titulos_raw
                GROUP BY filial, cod_pdv
            ),
            boletos AS (
                {boletos}
            ),
            joined AS (
                SELECT
                    r.*,
                    COALESCE(t.titulos, 0) AS titulos,
                    COALESCE(t.total_pendente, 0) AS total_pendente,
                    COALESCE(t.total_vencido, 0) AS total_vencido,
                    COALESCE(t.titulos_vencidos, 0) AS titulos_vencidos,
                    t.menor_dias,
                    COALESCE(t.vencimento_proximo, '') AS vencimento_proximo,
                    COALESCE(b.boletos, 0) AS boletos,
                    CASE
                        WHEN COALESCE(t.titulos, 0) = 0 THEN {sem_titulo}
                        WHEN t.menor_dias < 0 THEN {vencido}
                        WHEN t.menor_dias = 0 THEN {hoje}
                        WHEN t.menor_dias = 1 THEN {amanha}
                        WHEN t.menor_dias = 2 THEN {dois_dias}
                        ELSE {a_vencer}
                    END AS faixa
                FROM route r
                LEFT JOIN titulos t ON t.filial = r.filial AND t.cod_pdv = r.cod_pdv
                LEFT JOIN boletos b ON b.filial = r.filial AND b.cod_pdv = r.cod_pdv
            )
            """
        ).format(
            schema=schema,
            where=where,
            valor=_money_to_numeric_sql("i.valor_pendente"),
            dias=_days_to_due_sql("i.dias"),
            boletos=boletos,
            sem_titulo=sql.Literal(FAIXA_SEM_TITULO),
            vencido=sql.Literal(FAIXA_VENCIDO),
            hoje=sql.Literal(FAIXA_HOJE),
            amanha=sql.Literal(FAIXA_AMANHA),
            dois_dias=sql.Literal(FAIXA_DOIS_DIAS),
            a_vencer=sql.Literal(FAIXA_A_VENCER),
        )

    @contextmanager
    def _connect(self) -> Any:
        if self._pool is None:
            self._pool = get_connection_pool(self.database_url, connect_timeout_seconds=self.connect_timeout_seconds)
        with self._pool.connection() as conn:
            yield conn


def _numero(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    return valor


def _linha(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "filial": _normalize_filial(str(row.get("filial") or "")),
        "cliente": str(row.get("cod_pdv") or "").lstrip("0") or "0",
        "nome": str(row.get("nome") or ""),
        "razao_social": str(row.get("razao_social") or ""),
        "telefone": str(row.get("telefone") or ""),
        "cidade": str(row.get("cidade") or ""),
        "dia_visita": str(row.get("dia_visita") or ""),
        "status": str(row.get("status") or ""),
        "cond_pagto": str(row.get("cond_pagto") or ""),
        "limite_credito": str(row.get("limite_credito") or ""),
        "setor": str(row.get("setor_key") or ""),
        "gv": str(row.get("gv_key") or ""),
        "titulos": int(row.get("titulos") or 0),
        "titulos_vencidos": int(row.get("titulos_vencidos") or 0),
        "total_pendente": _numero(Decimal(str(row.get("total_pendente") or 0))),
        "total_vencido": _numero(Decimal(str(row.get("total_vencido") or 0))),
        "menor_dias": None if row.get("menor_dias") is None else int(row["menor_dias"]),
        "vencimento_proximo": str(row.get("vencimento_proximo") or ""),
        "boletos": int(row.get("boletos") or 0),
        "faixa": int(row.get("faixa") or FAIXA_SEM_TITULO),
    }
