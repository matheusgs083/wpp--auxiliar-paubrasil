import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.critica_operacao_import_service import (
    CriticaOperacaoImportService,
    _build_critica_operacao_rows_from_mapping_rows,
)


class CriticaOperacaoImportServiceTests(unittest.TestCase):
    def test_build_rows_generates_dynamic_criticas_from_minimum_price_without_exposing_te(self) -> None:
        headers = [
            "Filial Origem",
            "Status Pedido",
            "Tipo Movimento",
            "Num Pedido",
            "Cod. Vendedor",
            "Cod. Cliente",
            "Nome Cliente",
            "Valor Pedido",
            "Cod. Setor",
            "Cod. Pedido SIV",
            "Cod. Produto",
            "Nome Produto",
            "Qtde",
            "Unidade",
            "TTV s/ADF",
            "Preco Unit.",
            "Preco Minimo",
            "Ocorrencia 1",
            "Ocorrencia 2",
            "TE",
        ]
        header_map = {header: header for header in headers}

        rows = _build_critica_operacao_rows_from_mapping_rows(
            [
                {
                    "Filial Origem": "0003",
                    "Status Pedido": "NORMAL",
                    "Tipo Movimento": "51",
                    "Num Pedido": "707116",
                    "Cod. Vendedor": "000500",
                    "Cod. Cliente": "017099",
                    "Nome Cliente": "WILIAN MEDEIROS",
                    "Valor Pedido": "000000002008,93",
                    "Cod. Setor": "00500",
                    "Cod. Pedido SIV": "093131885750001",
                    "Cod. Produto": "0021530",
                    "Nome Produto": "SMOR GV998ML",
                    "Qtde": "00005",
                    "Unidade": "un",
                    "TTV s/ADF": "0033,3900",
                    "Preco Unit.": "0033,3900",
                    "Preco Minimo": "034,88",
                    "Ocorrencia 1": "",
                    "Ocorrencia 2": "",
                    "TE": "0002",
                }
            ],
            headers=headers,
            header_map=header_map,
            row_number_offset=2,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].filial, "3")
        self.assertEqual(rows[0].setor, "500")
        self.assertEqual(rows[0].filial_setor_key, "3_500")
        self.assertEqual(rows[0].produto_codigo, "21530")
        self.assertEqual(rows[0].preco_unitario, Decimal("33.3900"))
        self.assertEqual(rows[0].minimo_politica, Decimal("34.88"))
        self.assertIn("Preco abaixo do minimo informado (34,88)", rows[0].critica_text)
        self.assertNotIn("TE", rows[0].critica_text)

    def test_build_rows_ignores_small_b2b_price_minimum_difference(self) -> None:
        headers = [
            "Filial Origem",
            "Status Pedido",
            "Tipo Movimento",
            "Num Pedido",
            "Cod. Vendedor",
            "Cod. Cliente",
            "Nome Cliente",
            "Valor Pedido",
            "Cod. Setor",
            "Cod. Pedido SIV",
            "Cod. Produto",
            "Nome Produto",
            "Qtde",
            "Unidade",
            "TTV s/ADF",
            "Preco Unit.",
            "Preco Minimo",
            "Ocorrencia 1",
            "Ocorrencia 2",
            "TE",
            "Origem Pedido",
        ]
        header_map = {header: header for header in headers if header != "Origem Pedido"}

        rows = _build_critica_operacao_rows_from_mapping_rows(
            [
                {
                    "Filial Origem": "0003",
                    "Status Pedido": "NORMAL",
                    "Tipo Movimento": "51",
                    "Num Pedido": "707116",
                    "Cod. Vendedor": "000500",
                    "Cod. Cliente": "017099",
                    "Nome Cliente": "WILIAN MEDEIROS",
                    "Valor Pedido": "000000002008,93",
                    "Cod. Setor": "00500",
                    "Cod. Pedido SIV": "093131885750001",
                    "Cod. Produto": "0021530",
                    "Nome Produto": "SMOR GV998ML",
                    "Qtde": "00005",
                    "Unidade": "un",
                    "TTV s/ADF": "0110,0800",
                    "Preco Unit.": "0110,0800",
                    "Preco Minimo": "127,16",
                    "Ocorrencia 1": "",
                    "Ocorrencia 2": "",
                    "TE": "0002",
                    "Origem Pedido": "B2BGA",
                },
                {
                    "Filial Origem": "0003",
                    "Status Pedido": "NORMAL",
                    "Tipo Movimento": "51",
                    "Num Pedido": "707117",
                    "Cod. Vendedor": "000500",
                    "Cod. Cliente": "017099",
                    "Nome Cliente": "WILIAN MEDEIROS",
                    "Valor Pedido": "000000002008,93",
                    "Cod. Setor": "00500",
                    "Cod. Pedido SIV": "093131885750001",
                    "Cod. Produto": "0021530",
                    "Nome Produto": "SMOR GV998ML",
                    "Qtde": "00005",
                    "Unidade": "un",
                    "TTV s/ADF": "0040,0000",
                    "Preco Unit.": "0040,0000",
                    "Preco Minimo": "100,00",
                    "Ocorrencia 1": "",
                    "Ocorrencia 2": "",
                    "TE": "0002",
                    "Origem Pedido": "B2BG",
                },
            ],
            headers=headers,
            header_map=header_map,
            row_number_offset=2,
        )

        self.assertNotIn("Preco abaixo do minimo", rows[0].critica_text)
        self.assertIn("Preco abaixo do minimo informado (100,00)", rows[1].critica_text)

    def test_validate_source_rejects_file_from_another_operation(self) -> None:
        csv_content = "\n".join(
            [
                "Mapa;Empresa Origem;Filial Origem;Oper Televnd;Status Pedido;Tipo Movimento;Num Pedido;Cod. Vendedor;Cod. Cliente;Nome Cliente;Forma Pgto;Cond Pgto;Prazo em Dias;Cod. Segmento Cerveja;DS Segmento Cerveja;Origem Pedido;Vl Estouro Limite;Maior Atraso;Valor Pedido;Cod. Area;Cod. Setor;Cod. Pedido SIV;Alcada Final 1;Alcada Final 2;Alcada Final 3;Seq. Pedido;Cod. Produto;Nome Produto;Qtde;Qtde Avulsa;Unidade;TTV s/ADF;Valor Desconto;Preco Unit.;Preco Minimo;Ocorrencia 1;Ocorrencia 2;TE",
                "000001;221;0004;000012;NORMAL;51;706840;000012;019095;CLIENTE TESTE;DH;002;000;73;AS ROTA - VAREJO;B2BGA;00000000000,00;0000;000000000120,00;00099;00012;093138216140001;Vendedor;;;;001;0018152;GCA PT200MLSH12;00001;0000000;cx12;0019,2000;00008,80;0019,2000;999,99;;;0000",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "critica_operacao_3.csv"
            path.write_text(csv_content, encoding="utf-8")
            result = CriticaOperacaoImportService(
                database_url="",
                schema="reports",
                dataset_name="critica_op_3",
                expected_filial="3",
            ).validate_source(path)

        self.assertFalse(result.ok)
        self.assertGreater(result.error_count, 0)
        self.assertIn("operacao 3", result.sample_errors[0].lower())
        self.assertIn("4", result.sample_errors[0])


if __name__ == "__main__":
    unittest.main()
