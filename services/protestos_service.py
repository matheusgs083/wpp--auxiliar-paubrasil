from __future__ import annotations

import re
import shutil
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import psycopg
from fastapi import UploadFile
from psycopg import sql
from psycopg.rows import dict_row


PROTESTO_STATUSES = {
    "em_acompanhamento",
    "protestado",
    "pago_retirar_spc",
    "baixado",
    "cancelado",
}
PROTESTO_RELEASE_STATUSES = {"baixado", "cancelado"}


class ProtestosService:
    def __init__(
        self,
        *,
        database_url: str,
        schema: str,
        storage_root: Path,
        connect_timeout_seconds: float = 3.0,
        filial_labels: dict[str, str] | None = None,
    ) -> None:
        self.database_url = str(database_url or "").strip()
        self.schema = _clean_identifier(schema, "reports")
        self.storage_root = Path(storage_root)
        self.connect_timeout_seconds = max(float(connect_timeout_seconds or 3.0), 1.0)
        self.filial_labels = filial_labels or {}

    def ensure_schema(self) -> bool:
        if not self.database_url:
            return False
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                cur.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {}.protestos_titulos (
                            id BIGSERIAL PRIMARY KEY,
                            titulo_key VARCHAR(64) NOT NULL UNIQUE,
                            filial VARCHAR(16) NOT NULL,
                            nb VARCHAR(32) NOT NULL,
                            titulo_numero TEXT NOT NULL DEFAULT '',
                            nota_fiscal TEXT NOT NULL DEFAULT '',
                            cliente_nome TEXT NOT NULL DEFAULT '',
                            data_emissao TEXT NOT NULL DEFAULT '',
                            data_vencimento TEXT NOT NULL DEFAULT '',
                            valor_pendente TEXT NOT NULL DEFAULT '',
                            status VARCHAR(40) NOT NULL DEFAULT 'em_acompanhamento',
                            boleto_assinado_path TEXT NOT NULL DEFAULT '',
                            boleto_assinado_name TEXT NOT NULL DEFAULT '',
                            boleto_assinado_uploaded_at TIMESTAMPTZ,
                            comprovante_protesto_path TEXT NOT NULL DEFAULT '',
                            comprovante_protesto_name TEXT NOT NULL DEFAULT '',
                            comprovante_protesto_uploaded_at TIMESTAMPTZ,
                            observacao TEXT NOT NULL DEFAULT '',
                            last_seen_120601_at TIMESTAMPTZ,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS protestos_titulos_status_idx ON {}.protestos_titulos (status, updated_at DESC)"
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL(
                        "CREATE INDEX IF NOT EXISTS protestos_titulos_filial_nb_idx ON {}.protestos_titulos (filial, nb)"
                    ).format(sql.Identifier(self.schema))
                )
                cur.execute(
                    sql.SQL("ALTER TABLE {}.protestos_titulos ADD COLUMN IF NOT EXISTS titulo_numero TEXT NOT NULL DEFAULT ''").format(
                        sql.Identifier(self.schema)
                    )
                )
            conn.commit()
        return True

    def list_dashboard(
        self,
        *,
        context: dict[str, Any] | None,
        filial: str = "",
        search: str = "",
        status: str = "",
        title_date_from: str = "",
        title_date_to: str = "",
        protest_date_from: str = "",
        protest_date_to: str = "",
        limit: int = 300,
    ) -> dict[str, Any]:
        self._assert_ready()
        self.ensure_schema()
        allowed_filiais = _allowed_filiais(context)
        requested_filial = _clean_code(filial)
        if requested_filial and allowed_filiais is not None and requested_filial not in allowed_filiais:
            raise PermissionError("Revenda fora do acesso liberado para este usuario.")

        clean_status = _clean_status(status)
        clean_search = str(search or "").strip()
        title_start, title_end = _parse_date_window(title_date_from, title_date_to)
        protest_start, protest_end = _parse_datetime_window(protest_date_from, protest_date_to)
        limit = min(max(int(limit or 300), 1), 1000)

        with self._connect(row_factory=dict_row) as conn:
            self._sync_paid_alerts(conn)
            rows = self._list_open_titles(
                conn,
                allowed_filiais=allowed_filiais,
                filial=requested_filial,
                search=clean_search,
                status=clean_status,
                title_start=title_start,
                title_end=title_end,
                protest_start=protest_start,
                protest_end=protest_end,
                limit=limit,
            )
            paid_alerts = self._list_paid_alerts(
                conn,
                allowed_filiais=allowed_filiais,
                filial=requested_filial,
                search=clean_search,
                limit=100,
            )
            summary = self._build_summary(conn, allowed_filiais=allowed_filiais, filial=requested_filial)

        return {
            "ok": True,
            "filiais": self._visible_filiais(allowed_filiais),
            "filters": {
                "filial": requested_filial,
                "search": clean_search,
                "status": clean_status,
                "title_date_from": title_start.isoformat() if title_start else "",
                "title_date_to": title_end.isoformat() if title_end else "",
                "protest_date_from": protest_start.date().isoformat() if protest_start else "",
                "protest_date_to": (protest_end.date().isoformat() if protest_end else ""),
                "limit": limit,
            },
            "summary": summary,
            "paid_alerts": paid_alerts,
            "titles": rows,
        }

    def update_title(
        self,
        *,
        titulo_key: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self._assert_ready()
        self.ensure_schema()
        clean_key = _clean_key(titulo_key)
        if not clean_key:
            raise ValueError("Titulo invalido.")
        clean_status = _clean_status(payload.get("status") or "em_acompanhamento")
        observacao = str(payload.get("observacao") or "").strip()
        with self._connect(row_factory=dict_row) as conn:
            current = self._upsert_from_latest(conn, clean_key)
            if current is None:
                current = self._get_tracked_title(conn, clean_key)
            if current is None:
                raise ValueError("Titulo nao encontrado na inadimplencia atual nem no acompanhamento.")
            _assert_filial_allowed(str(current.get("filial") or ""), context)
            clear_documents = clean_status in PROTESTO_RELEASE_STATUSES
            if clear_documents:
                self._delete_document_files(current)
            with conn.cursor(row_factory=dict_row) as cur:
                if clear_documents:
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {}.protestos_titulos
                               SET status = %s,
                                   observacao = %s,
                                   boleto_assinado_path = '',
                                   boleto_assinado_name = '',
                                   boleto_assinado_uploaded_at = NULL,
                                   comprovante_protesto_path = '',
                                   comprovante_protesto_name = '',
                                   comprovante_protesto_uploaded_at = NULL,
                                   updated_at = NOW()
                             WHERE titulo_key = %s
                            RETURNING *
                            """
                        ).format(sql.Identifier(self.schema)),
                        (clean_status, observacao, clean_key),
                    )
                else:
                    cur.execute(
                        sql.SQL(
                            """
                            UPDATE {}.protestos_titulos
                               SET status = %s,
                                   observacao = %s,
                                   updated_at = NOW()
                             WHERE titulo_key = %s
                            RETURNING *
                            """
                        ).format(sql.Identifier(self.schema)),
                        (clean_status, observacao, clean_key),
                    )
                row = cur.fetchone()
            conn.commit()
        return {"ok": True, "title": self._serialize_tracked_row(row)}

    def upload_document(
        self,
        *,
        titulo_key: str,
        kind: str,
        upload: UploadFile,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self._assert_ready()
        self.ensure_schema()
        clean_key = _clean_key(titulo_key)
        clean_kind = _clean_doc_kind(kind)
        if not clean_key:
            raise ValueError("Titulo invalido.")
        filename = str(upload.filename or "").strip()
        if not filename.lower().endswith(".pdf"):
            raise ValueError("Envie apenas arquivo PDF.")

        with self._connect(row_factory=dict_row) as conn:
            current = self._upsert_from_latest(conn, clean_key)
            if current is None:
                current = self._get_tracked_title(conn, clean_key)
            if current is None:
                raise ValueError("Titulo nao encontrado na inadimplencia atual nem no acompanhamento.")
            _assert_filial_allowed(str(current.get("filial") or ""), context)

            target_dir = self.storage_root / _safe_path_part(str(current.get("filial") or "sem_filial")) / clean_key
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / f"{clean_kind}.pdf"
            with upload.file as fp:
                first = fp.read(5)
                if first != b"%PDF-":
                    raise ValueError("O arquivo enviado nao parece ser um PDF valido.")
                fp.seek(0)
                with target_path.open("wb") as out:
                    shutil.copyfileobj(fp, out)

            name_column = f"{clean_kind}_name"
            path_column = f"{clean_kind}_path"
            uploaded_column = f"{clean_kind}_uploaded_at"
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        UPDATE {}.protestos_titulos
                           SET {} = %s,
                               {} = %s,
                               {} = NOW(),
                               updated_at = NOW()
                         WHERE titulo_key = %s
                        RETURNING *
                        """
                    ).format(
                        sql.Identifier(self.schema),
                        sql.Identifier(path_column),
                        sql.Identifier(name_column),
                        sql.Identifier(uploaded_column),
                    ),
                    (str(target_path), filename, clean_key),
                )
                row = cur.fetchone()
            conn.commit()
        return {"ok": True, "title": self._serialize_tracked_row(row)}

    def download_document(
        self,
        *,
        titulo_key: str,
        kind: str,
        context: dict[str, Any] | None,
    ) -> tuple[bytes, str]:
        self._assert_ready()
        self.ensure_schema()
        clean_key = _clean_key(titulo_key)
        clean_kind = _clean_doc_kind(kind)
        if not clean_key:
            raise ValueError("Titulo invalido.")
        with self._connect(row_factory=dict_row) as conn:
            current = self._get_tracked_title(conn, clean_key)
        if current is None:
            raise ValueError("Documento nao encontrado.")
        _assert_filial_allowed(str(current.get("filial") or ""), context)
        path = Path(str(current.get(f"{clean_kind}_path") or ""))
        filename = str(current.get(f"{clean_kind}_name") or f"{clean_kind}.pdf").strip() or f"{clean_kind}.pdf"
        if not path.is_file():
            raise FileNotFoundError("Arquivo do documento nao encontrado.")
        return path.read_bytes(), _safe_download_name(filename)

    def _list_open_titles(
        self,
        conn: psycopg.Connection[Any],
        *,
        allowed_filiais: set[str] | None,
        filial: str,
        search: str,
        status: str,
        title_start: date | None,
        title_end: date | None,
        protest_start: datetime | None,
        protest_end: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        filters: list[sql.SQL | sql.Composed] = []
        params: list[Any] = []
        if filial:
            filters.append(sql.SQL("i.unb = %s"))
            params.append(filial)
        elif allowed_filiais is not None:
            filters.append(sql.SQL("i.unb = ANY(%s)"))
            params.append(sorted(allowed_filiais))
        if search:
            filters.append(sql.SQL("(i.cliente ILIKE %s OR i.nome ILIKE %s OR {} ILIKE %s OR {} ILIKE %s)").format(_nota_fiscal_sql("i.payload"), _titulo_sql("i.payload")))
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if status:
            filters.append(sql.SQL("COALESCE(p.status, 'em_aberto') = %s"))
            params.append(status)
        if title_start:
            filters.append(sql.SQL("{} >= %s").format(_br_date_sql("i.data_vencimento")))
            params.append(title_start)
        if title_end:
            filters.append(sql.SQL("{} <= %s").format(_br_date_sql("i.data_vencimento")))
            params.append(title_end)
        if protest_start:
            filters.append(sql.SQL("p.updated_at >= %s"))
            params.append(protest_start)
        if protest_end:
            filters.append(sql.SQL("p.updated_at < %s"))
            params.append(protest_end)
        where = sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE")
        params.append(limit)
        query = sql.SQL(
            """
            SELECT
                {title_key} AS titulo_key,
                i.unb AS filial,
                i.cliente AS nb,
                {titulo_numero} AS titulo_numero,
                COALESCE(i.nome, '') AS cliente_nome,
                {nota_fiscal} AS nota_fiscal,
                COALESCE(i.data_emissao, '') AS data_emissao,
                COALESCE(i.data_vencimento, '') AS data_vencimento,
                COALESCE(i.valor_pendente, '') AS valor_pendente,
                COALESCE(i.reference_date::text, '') AS reference_date,
                COALESCE(p.status, 'em_aberto') AS status,
                COALESCE(p.observacao, '') AS observacao,
                COALESCE(p.boleto_assinado_name, '') AS boleto_assinado_name,
                COALESCE(p.comprovante_protesto_name, '') AS comprovante_protesto_name,
                p.boleto_assinado_uploaded_at,
                p.comprovante_protesto_uploaded_at,
                p.updated_at
            FROM {schema}.inadimplencia_latest i
            LEFT JOIN {schema}.protestos_titulos p
              ON p.titulo_key = {title_key}
            WHERE {where}
            ORDER BY i.unb::int NULLS LAST, i.nome, i.data_vencimento, i.cliente
            LIMIT %s
            """
        ).format(
            schema=sql.Identifier(self.schema),
            title_key=_title_key_sql("i"),
            titulo_numero=_titulo_sql("i.payload"),
            nota_fiscal=_nota_fiscal_sql("i.payload"),
            where=where,
        )
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        tracked_rows = self._list_tracked_titles_not_in_latest(
            conn,
            allowed_filiais=allowed_filiais,
            filial=filial,
            search=search,
            status=status,
            title_start=title_start,
            title_end=title_end,
            protest_start=protest_start,
            protest_end=protest_end,
            limit=limit,
        )
        merged = [self._serialize_current_row(row) for row in rows]
        merged.extend(self._serialize_tracked_row(row) for row in tracked_rows)
        return sorted(
            merged,
            key=lambda item: (
                int(item.get("filial") or 999999) if str(item.get("filial") or "").isdigit() else 999999,
                str(item.get("cliente_nome") or ""),
                str(item.get("data_vencimento") or ""),
                str(item.get("nb") or ""),
            ),
        )[:limit]

    def _list_tracked_titles_not_in_latest(
        self,
        conn: psycopg.Connection[Any],
        *,
        allowed_filiais: set[str] | None,
        filial: str,
        search: str,
        status: str,
        title_start: date | None,
        title_end: date | None,
        protest_start: datetime | None,
        protest_end: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        filters: list[sql.SQL | sql.Composed] = [
            sql.SQL(
                """
                NOT EXISTS (
                    SELECT 1
                    FROM {schema}.inadimplencia_latest i
                    WHERE {title_key} = p.titulo_key
                )
                """
            ).format(schema=sql.Identifier(self.schema), title_key=_title_key_sql("i"))
        ]
        params: list[Any] = []
        if filial:
            filters.append(sql.SQL("p.filial = %s"))
            params.append(filial)
        elif allowed_filiais is not None:
            filters.append(sql.SQL("p.filial = ANY(%s)"))
            params.append(sorted(allowed_filiais))
        if search:
            filters.append(sql.SQL("(p.nb ILIKE %s OR p.cliente_nome ILIKE %s OR p.nota_fiscal ILIKE %s OR p.titulo_numero ILIKE %s)"))
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if status:
            filters.append(sql.SQL("p.status = %s"))
            params.append(status)
        else:
            filters.append(sql.SQL("p.status NOT IN ('baixado', 'cancelado')"))
        if title_start:
            filters.append(sql.SQL("{} >= %s").format(_br_date_sql("p.data_vencimento")))
            params.append(title_start)
        if title_end:
            filters.append(sql.SQL("{} <= %s").format(_br_date_sql("p.data_vencimento")))
            params.append(title_end)
        if protest_start:
            filters.append(sql.SQL("p.updated_at >= %s"))
            params.append(protest_start)
        if protest_end:
            filters.append(sql.SQL("p.updated_at < %s"))
            params.append(protest_end)
        params.append(limit)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT *
                    FROM {}.protestos_titulos p
                    WHERE {}
                    ORDER BY p.updated_at DESC
                    LIMIT %s
                    """
                ).format(sql.Identifier(self.schema), sql.SQL(" AND ").join(filters)),
                params,
            )
            return cur.fetchall()

    def _list_paid_alerts(
        self,
        conn: psycopg.Connection[Any],
        *,
        allowed_filiais: set[str] | None,
        filial: str,
        search: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        filters: list[sql.SQL | sql.Composed] = [
            sql.SQL("p.status = 'pago_retirar_spc'"),
        ]
        params: list[Any] = []
        if filial:
            filters.append(sql.SQL("p.filial = %s"))
            params.append(filial)
        elif allowed_filiais is not None:
            filters.append(sql.SQL("p.filial = ANY(%s)"))
            params.append(sorted(allowed_filiais))
        if search:
            filters.append(sql.SQL("(p.nb ILIKE %s OR p.cliente_nome ILIKE %s OR p.nota_fiscal ILIKE %s OR p.titulo_numero ILIKE %s)"))
            like = f"%{search}%"
            params.extend([like, like, like, like])
        params.append(limit)
        query = sql.SQL(
            """
            SELECT *
            FROM {}.protestos_titulos p
            WHERE {}
            ORDER BY p.updated_at DESC
            LIMIT %s
            """
        ).format(sql.Identifier(self.schema), sql.SQL(" AND ").join(filters))
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [self._serialize_tracked_row(row) for row in rows]

    def _build_summary(
        self,
        conn: psycopg.Connection[Any],
        *,
        allowed_filiais: set[str] | None,
        filial: str,
    ) -> dict[str, Any]:
        filters: list[sql.SQL | sql.Composed] = []
        params: list[Any] = []
        if filial:
            filters.append(sql.SQL("unb = %s"))
            params.append(filial)
        elif allowed_filiais is not None:
            filters.append(sql.SQL("unb = ANY(%s)"))
            params.append(sorted(allowed_filiais))
        where_current = sql.SQL(" AND ").join(filters) if filters else sql.SQL("TRUE")
        filters_tracked: list[sql.SQL | sql.Composed] = []
        params_tracked: list[Any] = []
        if filial:
            filters_tracked.append(sql.SQL("filial = %s"))
            params_tracked.append(filial)
        elif allowed_filiais is not None:
            filters_tracked.append(sql.SQL("filial = ANY(%s)"))
            params_tracked.append(sorted(allowed_filiais))
        where_tracked = sql.SQL(" AND ").join(filters_tracked) if filters_tracked else sql.SQL("TRUE")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT
                        COUNT(*)::int AS titulos_abertos,
                        COUNT(DISTINCT (unb, cliente))::int AS clientes_abertos,
                        COALESCE(MAX(reference_date)::text, '') AS reference_date,
                        COALESCE(MAX(batch_imported_at)::text, '') AS updated_at
                    FROM {}.inadimplencia_latest
                    WHERE {}
                    """
                ).format(sql.Identifier(self.schema), where_current),
                params,
            )
            current = cur.fetchone() or {}
            cur.execute(
                sql.SQL(
                    """
                    SELECT
                        COUNT(*)::int AS acompanhados,
                        COUNT(*) FILTER (WHERE status = 'protestado')::int AS protestados,
                        COUNT(*) FILTER (WHERE status = 'pago_retirar_spc')::int AS retirar_spc
                    FROM {}.protestos_titulos
                    WHERE {}
                    """
                ).format(sql.Identifier(self.schema), where_tracked),
                params_tracked,
            )
            tracked = cur.fetchone() or {}
        return {
            "titulos_abertos": int(current.get("titulos_abertos") or 0),
            "clientes_abertos": int(current.get("clientes_abertos") or 0),
            "acompanhados": int(tracked.get("acompanhados") or 0),
            "protestados": int(tracked.get("protestados") or 0),
            "retirar_spc": int(tracked.get("retirar_spc") or 0),
            "reference_date": str(current.get("reference_date") or ""),
            "updated_at": str(current.get("updated_at") or ""),
        }

    def _sync_paid_alerts(self, conn: psycopg.Connection[Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    UPDATE {schema}.protestos_titulos p
                       SET status = 'pago_retirar_spc',
                           updated_at = NOW()
                     WHERE (
                            p.status = 'protestado'
                            OR p.comprovante_protesto_path <> ''
                            OR p.comprovante_protesto_name <> ''
                       )
                       AND NOT EXISTS (
                            SELECT 1
                            FROM {schema}.inadimplencia_latest i
                            WHERE {title_key} = p.titulo_key
                       )
                    """
                ).format(schema=sql.Identifier(self.schema), title_key=_title_key_sql("i"))
            )
        conn.commit()

    def _upsert_from_latest(self, conn: psycopg.Connection[Any], titulo_key: str) -> dict[str, Any] | None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL(
                    """
                    INSERT INTO {schema}.protestos_titulos (
                        titulo_key, filial, nb, titulo_numero, nota_fiscal, cliente_nome, data_emissao,
                        data_vencimento, valor_pendente, last_seen_120601_at
                    )
                    SELECT
                        {title_key}, i.unb, i.cliente, {titulo_numero}, {nota_fiscal}, COALESCE(i.nome, ''),
                        COALESCE(i.data_emissao, ''), COALESCE(i.data_vencimento, ''),
                        COALESCE(i.valor_pendente, ''), NOW()
                    FROM {schema}.inadimplencia_latest i
                    WHERE {title_key} = %s
                    ON CONFLICT (titulo_key) DO UPDATE
                       SET filial = EXCLUDED.filial,
                           nb = EXCLUDED.nb,
                           titulo_numero = EXCLUDED.titulo_numero,
                           nota_fiscal = EXCLUDED.nota_fiscal,
                           cliente_nome = EXCLUDED.cliente_nome,
                           data_emissao = EXCLUDED.data_emissao,
                           data_vencimento = EXCLUDED.data_vencimento,
                           valor_pendente = EXCLUDED.valor_pendente,
                           last_seen_120601_at = NOW(),
                           updated_at = NOW()
                    RETURNING *
                    """
                ).format(
                    schema=sql.Identifier(self.schema),
                    title_key=_title_key_sql("i"),
                    titulo_numero=_titulo_sql("i.payload"),
                    nota_fiscal=_nota_fiscal_sql("i.payload"),
                ),
                (titulo_key,),
            )
            return cur.fetchone()

    def _get_tracked_title(self, conn: psycopg.Connection[Any], titulo_key: str) -> dict[str, Any] | None:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL("SELECT * FROM {}.protestos_titulos WHERE titulo_key = %s").format(sql.Identifier(self.schema)),
                (titulo_key,),
            )
            return cur.fetchone()

    def _delete_document_files(self, row: dict[str, Any] | None) -> None:
        if not row:
            return
        paths = [
            Path(str(row.get("boleto_assinado_path") or "")),
            Path(str(row.get("comprovante_protesto_path") or "")),
        ]
        for path in paths:
            try:
                if path.is_file() and path.resolve().is_relative_to(self.storage_root.resolve()):
                    path.unlink()
            except Exception:
                pass
        try:
            folder = self.storage_root / _safe_path_part(str(row.get("filial") or "sem_filial")) / _clean_key(row.get("titulo_key"))
            if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        except Exception:
            pass

    def _visible_filiais(self, allowed_filiais: set[str] | None) -> list[dict[str, str]]:
        items = sorted(((str(code), str(name)) for code, name in self.filial_labels.items()), key=lambda item: int(item[0]) if item[0].isdigit() else 999)
        if allowed_filiais is not None:
            items = [item for item in items if item[0] in allowed_filiais]
        if not items and allowed_filiais:
            items = [(filial, filial) for filial in sorted(allowed_filiais)]
        return [{"id": code, "name": name} for code, name in items]

    def _serialize_current_row(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload["filial_nome"] = self.filial_labels.get(str(payload.get("filial") or ""), str(payload.get("filial") or ""))
        payload["boleto_assinado_uploaded_at"] = _iso(payload.get("boleto_assinado_uploaded_at"))
        payload["comprovante_protesto_uploaded_at"] = _iso(payload.get("comprovante_protesto_uploaded_at"))
        payload["updated_at"] = _iso(payload.get("updated_at"))
        return payload

    def _serialize_tracked_row(self, row: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(row or {})
        payload["filial_nome"] = self.filial_labels.get(str(payload.get("filial") or ""), str(payload.get("filial") or ""))
        for key in ("boleto_assinado_uploaded_at", "comprovante_protesto_uploaded_at", "last_seen_120601_at", "created_at", "updated_at"):
            payload[key] = _iso(payload.get(key))
        return payload

    def _assert_ready(self) -> None:
        if not self.database_url:
            raise RuntimeError("REPORTS_DATABASE_URL nao configurada.")

    @contextmanager
    def _connect(self, *, row_factory: Any | None = None) -> Iterator[psycopg.Connection[Any]]:
        kwargs: dict[str, Any] = {
            "autocommit": False,
            "connect_timeout": int(self.connect_timeout_seconds),
        }
        if row_factory is not None:
            kwargs["row_factory"] = row_factory
        with psycopg.connect(self.database_url, **kwargs) as conn:
            yield conn


def _title_key_sql(alias: str) -> sql.Composed:
    prefix = sql.SQL(alias)
    return sql.SQL(
        """
        md5(concat_ws('|',
            {a}.unb,
            {a}.cliente,
            COALESCE({titulo}, ''),
            COALESCE({nf}, ''),
            COALESCE({a}.data_emissao, ''),
            COALESCE({a}.data_vencimento, ''),
            COALESCE({a}.valor_pendente, '')
        ))
        """
    ).format(a=prefix, titulo=_titulo_sql(f"{alias}.payload"), nf=_nota_fiscal_sql(f"{alias}.payload"))


def _titulo_sql(payload_expr: str) -> sql.Composed:
    payload = sql.SQL(payload_expr)
    return sql.SQL(
        """
        COALESCE(
            NULLIF({payload}->>'Titulo', ''),
            NULLIF({payload}->>'Título', ''),
            NULLIF({payload}->>'titulo', ''),
            NULLIF({payload}->>'Nr. Titulo', ''),
            NULLIF({payload}->>'Nr Titulo', ''),
            ''
        )
        """
    ).format(payload=payload)


def _nota_fiscal_sql(payload_expr: str) -> sql.Composed:
    payload = sql.SQL(payload_expr)
    return sql.SQL(
        """
        COALESCE(
            NULLIF({payload}->>'nota_fiscal', ''),
            NULLIF({payload}->>'Nota Fiscal', ''),
            NULLIF({payload}->>'NotaFiscal', ''),
            NULLIF({payload}->>'NF', ''),
            NULLIF({payload}->>'Nf', ''),
            NULLIF({payload}->>'Num. Documento', ''),
            NULLIF({payload}->>'Num Documento', ''),
            ''
        )
        """
    ).format(payload=payload)


def _br_date_sql(column_expr: str) -> sql.Composed:
    column = sql.SQL(column_expr)
    return sql.SQL(
        """
        CASE
            WHEN {column} ~ '^\\d{{2}}/\\d{{2}}/\\d{{4}}$'
                THEN to_date({column}, 'DD/MM/YYYY')
            WHEN {column} ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}'
                THEN left({column}, 10)::date
            ELSE NULL
        END
        """
    ).format(column=column)


def _allowed_filiais(context: dict[str, Any] | None) -> set[str] | None:
    if not context or bool(context.get("is_admin")):
        return None
    raw = [str(item).strip() for item in context.get("filiais", ()) if str(item).strip()]
    if not raw or "*" in raw:
        return None
    return set(raw)


def _assert_filial_allowed(filial: str, context: dict[str, Any] | None) -> None:
    allowed = _allowed_filiais(context)
    if allowed is not None and str(filial or "").strip() not in allowed:
        raise PermissionError("Revenda fora do acesso liberado para este usuario.")


def _clean_status(value: Any) -> str:
    clean = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not clean:
        return ""
    if clean not in PROTESTO_STATUSES and clean != "em_aberto":
        raise ValueError("Status de protesto invalido.")
    return clean


def _clean_key(value: Any) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value or "").strip().lower())[:64]


def _clean_doc_kind(value: Any) -> str:
    clean = str(value or "").strip().lower().replace("-", "_")
    if clean in {"boleto", "boleto_assinado"}:
        return "boleto_assinado"
    if clean in {"comprovante", "comprovante_protesto"}:
        return "comprovante_protesto"
    raise ValueError("Tipo de documento invalido.")


def _clean_code(value: Any) -> str:
    return re.sub(r"\D+", "", str(value or "").strip())


def _clean_identifier(value: str, fallback: str) -> str:
    clean = "".join(char for char in str(value or "").strip() if char.isalnum() or char == "_")
    return clean or fallback


def _safe_path_part(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return clean[:80] or "item"


def _safe_download_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(value or "").strip())
    if not clean.lower().endswith(".pdf"):
        clean = f"{clean or 'documento'}.pdf"
    return clean[:160]


def _parse_single_date(value: Any) -> date | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError("Data invalida. Use YYYY-MM-DD ou DD/MM/AAAA.")


def _parse_date_window(start_value: Any, end_value: Any) -> tuple[date | None, date | None]:
    start = _parse_single_date(start_value)
    end = _parse_single_date(end_value)
    if start and end and start > end:
        raise ValueError("Data inicial nao pode ser maior que a data final.")
    return start, end


def _parse_datetime_window(start_value: Any, end_value: Any) -> tuple[datetime | None, datetime | None]:
    start_date, end_date = _parse_date_window(start_value, end_value)
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc) if start_date else None
    end = datetime.combine(end_date, time.min, tzinfo=timezone.utc) + timedelta(days=1) if end_date else None
    return start, end


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")
