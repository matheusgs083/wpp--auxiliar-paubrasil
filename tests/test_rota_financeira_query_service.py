from __future__ import annotations

import unittest
from contextlib import contextmanager
from typing import Any

from bot_api.services.rota_financeira_query_service import RotaFinanceiraQueryService


class _Cursor:
    def __init__(self, registro: list[tuple[str, list[Any]]]) -> None:
        self.registro = registro

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: Any, params: list[Any]) -> None:
        self.registro.append((query.as_string(None), list(params)))

    def fetchall(self) -> list[dict[str, Any]]:
        return []

    def fetchone(self) -> dict[str, Any]:
        return {"clientes": 0}


class ServicoSemBanco(RotaFinanceiraQueryService):
    """Executa a montagem real do SQL e guarda a consulta em vez de ir ao Postgres."""

    def __init__(self) -> None:
        super().__init__(database_url="postgresql://teste", schema="reports")
        self.registro: list[tuple[str, list[Any]]] = []

    @contextmanager
    def _connect(self) -> Any:
        registro = self.registro

        class _Conn:
            def cursor(self, row_factory: Any = None) -> _Cursor:
                return _Cursor(registro)

        yield _Conn()


class RotaFinanceiraSqlTest(unittest.TestCase):
    def consulta(self, **kwargs: Any) -> tuple[str, list[Any]]:
        servico = ServicoSemBanco()
        servico.listar(dia="SEG", **{"allowed_sectors": ["3_107"], **kwargs})
        return servico.registro[0]

    def test_vencidos_vem_primeiro_com_maior_atraso(self) -> None:
        texto, _params = self.consulta()
        self.assertIn("WHEN t.menor_dias < 0 THEN 1", texto)
        self.assertIn("WHEN COALESCE(t.titulos, 0) = 0 THEN 6", texto)
        ordem = texto[texto.index("ORDER BY"):]
        self.assertLess(ordem.index("f.faixa"), ordem.index("f.total_pendente DESC"))
        self.assertIn("CASE WHEN f.faixa = 1 THEN f.menor_dias END ASC", ordem)

    def test_escopo_vai_sempre_na_consulta(self) -> None:
        texto, params = self.consulta(setor="3_109", busca="300")
        self.assertIn("filial_setor_key", texto)
        self.assertIn(["3_107"], params)
        self.assertIn("300", params)

    def test_escopo_invalido_fecha_em_vez_de_abrir(self) -> None:
        texto, _params = self.consulta(allowed_sectors=["lixo"])
        self.assertIn("FALSE", texto)

    def test_sem_03_02_06_nao_consulta_boletos(self) -> None:
        texto, _params = self.consulta(incluir_boletos=False)
        self.assertNotIn("boletos_latest", texto)
        com, _ = self.consulta(incluir_boletos=True)
        self.assertIn("boletos_latest", com)

    def test_situacao_invalida_e_recusada(self) -> None:
        with self.assertRaises(ValueError):
            ServicoSemBanco().listar(dia="SEG", allowed_sectors=["3_107"], situacao="tudo")

    def test_pagina_tem_limite(self) -> None:
        _texto, params = self.consulta(limite=5000, offset=-3)
        self.assertEqual(params[-2:], [50, 0])


if __name__ == "__main__":
    unittest.main()
