from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from bot_api.services.compras_030237_service import (
    Compras030237Service,
    devolucao_payload,
    linhas_para_gravar,
    media_mensal,
    meses_fechados,
    montar_resumo,
)
from bot_api.services.liga_entrega_raw_sql_import_service import _payload_historico


def _sql(comando: object) -> str:
    return comando.as_string(None) if hasattr(comando, "as_string") else str(comando)


class MediaTest(unittest.TestCase):
    def test_meses_fechados_sao_os_tres_anteriores(self) -> None:
        self.assertEqual(meses_fechados(date(2026, 1, 15)), ["2025-10", "2025-11", "2025-12"])

    def test_media_divide_por_3_com_mes_sem_compra(self) -> None:
        fechados = ["2026-08", "2026-09", "2026-10"]
        media = media_mensal({"2026-08": 300.0, "2026-10": 600.0}, fechados, set(fechados))
        self.assertEqual(media, 300.0)

    def test_sem_base_de_um_mes_nao_calcula_media(self) -> None:
        fechados = ["2026-08", "2026-09", "2026-10"]
        self.assertIsNone(media_mensal({"2026-09": 900.0, "2026-10": 900.0}, fechados, {"2026-09", "2026-10"}))

    def test_resumo_mostra_base_desde_e_serie(self) -> None:
        resumo = montar_resumo(
            atual="2026-11",
            fechados=["2026-08", "2026-09", "2026-10"],
            cargas=[("2026-10", None), ("2026-11", None)],
            meses=[("2026-10", 1000, 10, 2), ("2026-11", 500, 5, 1)],
            ultima_entrega=date(2026, 11, 20),
            produtos=[("1", "CERVEJA", "cx", 900, 9), ("2", "AGUA", "pc", 600, 30)],
        )
        self.assertIsNone(resumo["media_3_meses"])
        self.assertEqual(resumo["base_desde"], "2026-10")
        self.assertEqual(resumo["mes_atual"]["total"], 500)
        self.assertEqual([m["competencia"] for m in resumo["meses_fechados"]], ["2026-08", "2026-09", "2026-10"])
        self.assertFalse(resumo["meses_fechados"][0]["com_base"])
        self.assertEqual(resumo["top_faturamento"][0]["produto"], "1")
        self.assertEqual(resumo["top_quantidade"][0]["produto"], "2")
        self.assertEqual(resumo["ultima_entrega"], "2026-11-20")


class ReconstrucaoTest(unittest.TestCase):
    """A regra roda em SQL; aqui garantimos as cláusulas que a sustentam.

    A carga foi conferida num Postgres local com a amostra real de Patos
    (43.738 linhas, duas versões do mesmo acumulado): total A+E de
    R$ 11.513.704,41, igual ao cálculo direto do CSV, sem dobrar a versão antiga.
    """

    def setUp(self) -> None:
        self.comandos = [_sql(c) for c, _ in Compras030237Service("postgresql://x").comandos_rebuild("2026-11")]
        self.texto = "\n".join(self.comandos)

    def test_reimportacao_cumulativa_usa_so_a_versao_mais_recente(self) -> None:
        self.assertIn("DISTINCT ON (filial, mes_emissao)", self.texto)
        self.assertIn("ORDER BY filial, mes_emissao, imported_at DESC", self.texto)
        self.assertIn("JOIN compras_030237_versoes e USING (filial, mes_emissao, source_key)", self.texto)

    def test_importacao_refaz_so_a_filial_do_arquivo(self) -> None:
        comandos = Compras030237Service("postgresql://x").comandos_rebuild("2026-11", "2026-11", ["03"])
        deletes = [params for comando, params in comandos if _sql(comando).strip().startswith("DELETE")]
        self.assertTrue(all(params[-2:] == (["3"], ["3"]) for params in deletes))
        self.assertTrue(all("filial = ANY" in _sql(c) for c, _ in comandos if _sql(c).strip().startswith("DELETE")))

    def test_linha_gravada_leva_mes_e_filial(self) -> None:
        registros = linhas_para_gravar("giro|x", "0111.csv", [{"Filial": "003", "Emissao": "05/11/2026", "Produto": "1"}])
        self.assertEqual(registros[0][:5], ("giro|x", "0111.csv", 1, "2026-11", "3"))

    def test_reconstrucao_apaga_antes_de_gravar_os_meses(self) -> None:
        primeiro_insert = next(i for i, c in enumerate(self.comandos) if "INSERT INTO" in c)
        deletes = [i for i, c in enumerate(self.comandos) if c.strip().startswith("DELETE")]
        self.assertEqual(len(deletes), 4)
        self.assertTrue(all(i < primeiro_insert for i in deletes))

    def test_compras_so_a_e_e_devolucoes_so_d(self) -> None:
        compras = next(c for c in self.comandos if '"compras_030237_mes"' in c and "INSERT" in c)
        devolucoes = next(c for c in self.comandos if '"devolucoes_030237"' in c and "INSERT" in c)
        self.assertIn("status IN ('A', 'E')", compras)
        self.assertNotIn("'D'", compras)
        self.assertIn("status = 'D'", devolucoes)

    def test_compra_conta_no_mes_da_operacao(self) -> None:
        compras = next(c for c in self.comandos if '"compras_030237_mes"' in c and "INSERT" in c)
        self.assertIn("to_char(data_operacao, 'YYYY-MM')", compras)

    def test_notas_usam_versao_publicada_e_cliente_da_filial(self) -> None:
        servico = Compras030237Service("postgresql://x")
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(date(2026, 11, 6), "123", "003", 1, 2, 30, [{"produto": "1", "descricao": "Bebida"}])]
        with patch.object(servico, "_connect") as conectar, patch.object(servico, "ensure_schema"):
            conectar.return_value.__enter__.return_value = conn
            notas = servico.notas_cliente("003", "00100")
        query, params = cursor.execute.call_args.args
        self.assertIn('"compras_030237_cargas"', _sql(query))
        self.assertIn("c.source_key = r.source_key", _sql(query))
        self.assertEqual(params, ("3", "100", "3", "030237", "100"))
        self.assertEqual(notas[0]["produtos"][0]["descricao"], "Bebida")


class DevolucaoTest(unittest.TestCase):
    def test_motivo_e_responsabilidade_vem_da_tabela(self) -> None:
        item = devolucao_payload((date(2026, 11, 6), "231577", "003", "39254", "1", 3, 10, 5981.6))
        self.assertEqual(item["motivo"], "FALTA CAMINHAO PARA CARREGAR")
        self.assertEqual(item["responsabilidade"], "LOGISTICA")
        self.assertEqual(item["data"], "2026-11-06")

    def test_sem_codigo_mostra_motivo_nao_informado(self) -> None:
        self.assertEqual(devolucao_payload((None, "1", "", "", "", 1, 1, 1))["motivo"], "Motivo não informado")

    def test_historico_guarda_motivo_nf_referencia_e_descricao(self) -> None:
        linha = {"Status": "D", "Mot. Cancelamento": "1", "NF Referencia": "39254", "Descri��o": "CERVEJA", "Placa": "X"}
        payload = _payload_historico("030237", linha)
        self.assertEqual(payload["Mot. Cancelamento"], "1")
        self.assertEqual(payload["NF Referencia"], "39254")
        self.assertEqual(payload["Descricao"], "CERVEJA")
        self.assertNotIn("Placa", payload)


if __name__ == "__main__":
    unittest.main()
