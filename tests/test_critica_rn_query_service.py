import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from bot_api.services.critica_rn_query_service import (
    CriticaRnQueryService,
    _annotate_duplicate_client_orders,
    _annotate_client_total_above_average,
    _annotate_duplicate_products_by_price,
    _build_order_records,
    _build_product_summary_rows,
    _build_problem_labels,
    _compact_problem_hint,
    _detail_report_text,
    _has_price_alert,
    _naturalize_critica_text,
    _resolve_price_reference,
    _row_to_record,
    _summary_order_client_markup,
    _summarize_records,
)
from bot_api.tests.test_support import make_critica_record


class CriticaRnQueryServiceRuleTests(unittest.TestCase):
    def test_current_critica_import_allows_matching_operation_scope_only(self) -> None:
        class FakeCursor:
            def __init__(self) -> None:
                self.calls: list[tuple[object, tuple[object, ...]]] = []
                self._result_sets = [
                    [{"dataset_name": "critica_op_3"}],
                    [{"dataset_name": "critica_op_3"}, {"dataset_name": "critica_op_4"}],
                    [{"dataset_name": "critica_op_3"}],
                    [{"dataset_name": "critica_op_3"}, {"dataset_name": "critica_op_4"}],
                    [{"dataset_name": "critica_op_3"}],
                    [{"dataset_name": "critica_op_3"}, {"dataset_name": "critica_op_4"}],
                    [{"dataset_name": "critica_op_3"}],
                    [{"dataset_name": "critica_op_3"}, {"dataset_name": "critica_op_4"}],
                ]

            def __enter__(self) -> "FakeCursor":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, _query: object, params: tuple[object, ...]) -> None:
                self.calls.append((_query, params))

            def fetchall(self) -> list[dict[str, str]]:
                return self._result_sets.pop(0)

        class FakeConnection:
            def __init__(self, cursor: FakeCursor) -> None:
                self._cursor = cursor

            def __enter__(self) -> "FakeConnection":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def cursor(self) -> FakeCursor:
                return self._cursor

        cursor = FakeCursor()
        service = CriticaRnQueryService(database_url="postgresql://example", schema="reports")
        service._connect = lambda **_kwargs: FakeConnection(cursor)  # type: ignore[method-assign]

        self.assertTrue(
            service.has_current_critica_import(
                today=date(2026, 6, 25),
                allowed_sectors=["3_400"],
            )
        )
        self.assertFalse(
            service.has_current_critica_import(
                today=date(2026, 6, 25),
                allowed_sectors=["4_400"],
            )
        )
        self.assertFalse(service.has_current_critica_import(today=date(2026, 6, 25)))
        self.assertTrue(
            service.has_current_critica_import(
                today=date(2026, 6, 25),
                target_date=date(2026, 6, 25),
            )
        )
        self.assertEqual(cursor.calls[0][1], ("critica_rn", "critica_op_%", date(2026, 6, 25), date(2026, 6, 25)))

    def test_resolve_price_reference_uses_ttc_for_unit_sales(self) -> None:
        reference, label = _resolve_price_reference(
            filial="1",
            unit_label="UN",
            product_name="SKOL LATA 269ML",
            client_segment="AS",
            ttc_ref=Decimal("3.89"),
            caixa_asr=Decimal("89.47"),
            caixa_sub=Decimal("89.47"),
            caixa_frio=Decimal("91.00"),
        )

        self.assertEqual(reference, Decimal("3.89"))
        self.assertEqual(label, "ttc")

    def test_resolve_price_reference_handles_600ml_sold_in_dozens(self) -> None:
        reference, label = _resolve_price_reference(
            filial="3",
            unit_label="Dz",
            product_name="SKOL 600ML",
            client_segment="AS",
            ttc_ref=Decimal("0"),
            caixa_asr=Decimal("132.00"),
            caixa_sub=Decimal("0"),
            caixa_frio=Decimal("0"),
        )

        self.assertEqual(reference, Decimal("66.0000"))
        self.assertEqual(label, "caixa_600_dz")

    def test_price_alert_uses_stricter_tolerance_for_operacao_1(self) -> None:
        op1_record = make_critica_record(
            filial="1",
            price_reference=Decimal("100"),
            price_delta_pct=Decimal("0.04"),
            problemas=(),
        )
        op3_record = make_critica_record(
            filial="3",
            price_reference=Decimal("100"),
            price_delta_pct=Decimal("0.04"),
            problemas=(),
        )

        self.assertTrue(_has_price_alert(op1_record))
        self.assertFalse(_has_price_alert(op3_record))

    def test_b2b_origin_ignores_price_problem_under_sixty_percent(self) -> None:
        record = make_critica_record(
            origem_pedido="B2BGA",
            critica_text="Preco abaixo do minimo informado (131,94)",
            price_reference=Decimal("100"),
            price_delta_pct=Decimal("0.15"),
            produto_encontrado_dprecos=False,
            problemas=(),
        )

        labels = _build_problem_labels(record)

        self.assertFalse(_has_price_alert(record))
        self.assertFalse(any("Preco" in label for label in labels))
        self.assertNotIn("Produto sem referencia na DPrecos", labels)

    def test_b2b_origin_reports_price_problem_at_sixty_percent(self) -> None:
        record = make_critica_record(
            origem_pedido="B2BG",
            critica_text="Preco abaixo do minimo informado (131,94)",
            preco_unitario=Decimal("160"),
            price_reference=Decimal("100"),
            price_delta_pct=Decimal("0.60"),
            problemas=(),
        )

        labels = _build_problem_labels(record)

        self.assertTrue(_has_price_alert(record))
        self.assertTrue(any("60,0% acima da referencia" in label for label in labels))
        self.assertTrue(any("Preco abaixo do minimo permitido" in label for label in labels))

    def test_non_sale_order_ignores_price_problem_under_sixty_percent(self) -> None:
        record = make_critica_record(
            tipo_movimento="52",
            movement_operation_name="TROCA",
            critica_text="Preco abaixo do minimo informado (131,94)",
            price_reference=Decimal("100"),
            price_delta_pct=Decimal("0.20"),
            problemas=(),
        )

        labels = _build_problem_labels(record)

        self.assertFalse(_has_price_alert(record))
        self.assertFalse(any("Preco" in label for label in labels))

    def test_non_sale_order_reports_price_problem_at_sixty_percent(self) -> None:
        record = make_critica_record(
            tipo_movimento="52",
            movement_operation_name="TROCA",
            preco_unitario=Decimal("40"),
            price_reference=Decimal("100"),
            price_delta_pct=Decimal("-0.60"),
            problemas=(),
        )

        self.assertTrue(_has_price_alert(record))

    def test_build_problem_labels_includes_new_business_flags(self) -> None:
        record = make_critica_record(
            critica_text="TE 99 | Preco abaixo do minimo informado (131,94)",
            ocorrencia_1="Condicao divergente",
            ocorrencia_2="Pedido acima da media",
            te_codigo="99",
            price_reference=Decimal("40"),
            price_reference_label="caixa",
            price_delta_pct=Decimal("0.15"),
            order_above_average=True,
            avg_order_value_3m=Decimal("300"),
            total_pedido=Decimal("600"),
            inad_total_vencido=Decimal("250"),
            inad_titulos_vencidos=1,
            multipack_item=True,
            multipack_allowed=False,
            client_segment="ROTA",
            map_status="buffer",
            limit_exceeded_amount=Decimal("80"),
            client_limite_usado=Decimal("500"),
            cond_divergente=True,
            cond_pag_pedido="PROMO 21 DIAS",
            client_cond_pag_atual="A VISTA",
            cond_pag_pedido_codigo="605",
            client_cond_pag_atual_codigo="2",
            problemas=(),
        )

        labels = _build_problem_labels(record)

        self.assertTrue(any("Ocorrencia do relatorio: Condicao divergente" in label for label in labels))
        self.assertTrue(any("Ocorrencia complementar: Pedido acima da media" in label for label in labels))
        self.assertTrue(any("Produto 2349 - GCA PT2 CX6: Preco abaixo do minimo permitido. Minimo informado: R$ 131,94" in label for label in labels))
        self.assertFalse(any("Codigo interno TE 99" in label for label in labels))
        self.assertTrue(any("Produto 2349 - GCA PT2 CX6 com preco 15,0% acima da referencia (DPrecos):" in label for label in labels))
        self.assertTrue(any("Cliente acima da media de compra:" in label for label in labels))
        self.assertTrue(any("Cliente com R$ 250,00 vencido em aberto" in label for label in labels))
        self.assertFalse(any("multipack" in label.lower() for label in labels))
        self.assertIn("Pedido em buffer (mapa 1)", labels)
        self.assertTrue(any("Com este pedido, o cliente ultrapassa o limite em R$ 80,00" in label for label in labels))
        self.assertTrue(
            any(
                "Condicao de pagamento diferente do cadastro: pedido PROMO 21 DIAS; cadastro A VISTA" in label
                for label in labels
            )
        )

    def test_build_problem_labels_does_not_treat_open_not_due_titles_as_overdue(self) -> None:
        record = make_critica_record(
            inad_total_aberto=Decimal("500"),
            inad_total_vencido=Decimal("500"),
            inad_titulos_abertos=2,
            inad_titulos_vencidos=0,
            problemas=(),
        )

        labels = _build_problem_labels(record)

        self.assertFalse(any("vencido em aberto" in label for label in labels))

    def test_naturalize_critica_text_removes_te_prefix_and_formats_minimum(self) -> None:
        text = _naturalize_critica_text("TE 3 | Preco abaixo do minimo informado (131,94)")

        self.assertEqual(text, "Preco abaixo do minimo permitido. Minimo informado: R$ 131,94")
        self.assertEqual(_naturalize_critica_text("TE 3"), "")

    def test_row_to_record_applies_condition_and_limit_only_for_tipo_movimento_51(self) -> None:
        base_row = {
            "filial": "3",
            "pedido": "707118",
            "data_pedido": None,
            "operacao": "3",
            "cod_pdv": "17099",
            "nome_pdv": "CLIENTE TESTE",
            "setor": "12",
            "filial_setor_key": "3_12",
            "filial_gv_key": "3_5",
            "status_pedido": "NORMAL",
            "total_pedido": "80",
            "total_cliente": "80",
            "critica_text": "",
            "produto_codigo": "21530",
            "produto_dprecos": "SMIRNOFF ORIGINAL GARRAFA VIDRO 998ML",
            "produto_descricao_pdf": "SMIRNOFF GF VD 998ML",
            "nome_produto_original": "SMIRNOFF ORIGINAL GARRAFA VIDRO 998ML",
            "quantidade": "1",
            "unid_venda": "cx",
            "preco_unitario": "50",
            "preco_sem_adf": "50",
            "minimo_politica": "50",
            "codigo_gv": "12",
            "codigo_pgv": "21530",
            "pedido_linhas": 1,
            "pedido_produto_linhas": 1,
            "pedido_produto_duplicado": False,
            "produto_encontrado_dprecos": True,
            "preco_status": "ok",
            "asr_preco": "50",
            "sub_preco": "50",
            "frio_preco": "50",
            "cond_pag_pedido": "PROMO 21 DIAS",
            "client_cond_pag_atual": "A VISTA",
            "cond_pag_pedido_codigo": "605",
            "client_cond_pag_atual_codigo": "002",
            "client_limite_credito": "100",
            "client_limite_usado": "150",
            "valor_estouro_limite_text": "40",
            "produto_peso_bruto": "12,50",
        }

        record_51 = _row_to_record({**base_row, "tipo_movimento": "051"})
        record_52 = _row_to_record({**base_row, "tipo_movimento": "052"})

        self.assertTrue(record_51.cond_divergente)
        self.assertEqual(record_51.produto_descricao, "SMIRNOFF GF VD 998ML")
        self.assertEqual(record_51.produto_peso_bruto, Decimal("12.50"))
        self.assertEqual(record_51.peso_item, Decimal("12.50"))
        self.assertEqual(record_51.limit_exceeded_amount, Decimal("40"))
        self.assertTrue(any("Condicao de pagamento diferente do cadastro" in label for label in record_51.problemas))
        self.assertTrue(any("ultrapassa o limite" in label for label in record_51.problemas))

        self.assertFalse(record_52.cond_divergente)
        self.assertEqual(record_52.limit_exceeded_amount, Decimal("0"))
        self.assertFalse(any("Condicao de pagamento diferente do cadastro" in label for label in record_52.problemas))
        self.assertFalse(any("ultrapassa o limite" in label for label in record_52.problemas))

    def test_row_to_record_does_not_apply_limit_alert_for_cash_condition(self) -> None:
        record = _row_to_record(
            {
                "filial": "3",
                "pedido": "923108",
                "data_pedido": None,
                "operacao": "3",
                "cod_pdv": "11923",
                "nome_pdv": "JOAO JESSE BATIST",
                "setor": "503",
                "filial_setor_key": "3_503",
                "filial_gv_key": "3_5",
                "status_pedido": "BLOQUEADO",
                "total_pedido": "1161.42",
                "total_cliente": "1161.42",
                "critica_text": "",
                "produto_codigo": "348",
                "produto_dprecos": "PRODUTO TESTE",
                "produto_descricao_pdf": "PRODUTO TESTE",
                "nome_produto_original": "PRODUTO TESTE",
                "quantidade": "1",
                "unid_venda": "cx",
                "preco_unitario": "10",
                "preco_sem_adf": "10",
                "minimo_politica": "10",
                "tipo_movimento": "051",
                "codigo_gv": "503",
                "codigo_pgv": "348",
                "pedido_linhas": 1,
                "pedido_produto_linhas": 1,
                "pedido_produto_duplicado": False,
                "produto_encontrado_dprecos": True,
                "preco_status": "ok",
                "cond_pag_pedido": "DINHEIRO",
                "client_cond_pag_atual": "DINHEIRO",
                "cond_pag_pedido_codigo": "002",
                "client_cond_pag_atual_codigo": "002",
                "client_limite_credito": "543.00",
                "client_limite_usado": "0",
                "valor_estouro_limite_text": "618.42",
                "produto_peso_bruto": "19.42",
            }
        )

        self.assertEqual(record.limit_exceeded_amount, Decimal("0"))
        self.assertFalse(any("ultrapassa o limite" in label for label in record.problemas))

    def test_detail_report_text_groups_items_and_shows_setor(self) -> None:
        long_reason = (
            "Preco abaixo do minimo permitido. Minimo informado: R$ 57,30; "
            "motivo completo vindo do relatorio sem corte para o vendedor conferir antes da rota"
        )
        records = [
            make_critica_record(
                pedido="708005",
                cod_pdv="6667",
                nome_pdv="SUPERM. DENISE",
                setor="107",
                movement_operation_name="VENDA",
                cond_pag_pedido="PROMO 21 DIAS",
                peso_item=Decimal("10.5"),
                produto_codigo="14135",
                produto_descricao="BUD LT473SPSHC",
                problemas=(long_reason,),
            ),
            make_critica_record(
                pedido="708005",
                cod_pdv="6667",
                nome_pdv="SUPERM. DENISE",
                setor="107",
                movement_operation_name="VENDA",
                cond_pag_pedido="PROMO 21 DIAS",
                peso_item=Decimal("8"),
                produto_codigo="13065",
                produto_descricao="H2OH LNETO PT1",
                problemas=(),
            ),
        ]

        text = _detail_report_text(records)

        self.assertIn("Pedido   UNB/NB", text)
        self.assertNotIn("M Pol", text)
        self.assertNotIn(" Pz ", text)
        self.assertIn("Tipo", text)
        self.assertIn("VENDA", text)
        self.assertIn("Setor do Pedido: 107", text)
        self.assertIn("Peso do Pedido: 18,5", text)
        self.assertIn("Cond. Pag.: PROMO 21 DIAS", text)
        self.assertIn("Valor do Pedido (R$): 120,00", text)
        self.assertIn("14135 BUD LT473SPSHC", text)
        self.assertIn("13065 H2OH LNETO PT1", text)
        self.assertIn(long_reason, text)

    def test_compact_problem_hint_only_uses_item_specific_occurrences(self) -> None:
        general_record = make_critica_record(
            problemas=(
                "Cliente acima da media de compra: total em pedidos R$ 740,80; media R$ 440,86",
                "Cliente com R$ 120,00 vencido em aberto",
            )
        )
        item_record = make_critica_record(
            problemas=(
                "Cliente acima da media de compra: total em pedidos R$ 740,80; media R$ 440,86",
                "Produto 2349 - GCA PT2 CX6 com preco 13,4% abaixo da referencia (DPrecos)",
            )
        )
        falta_record = make_critica_record(
            problemas=(
                "Ocorrencia do relatorio: Falta de produto no pedido",
            )
        )

        self.assertEqual(_compact_problem_hint(general_record), "")
        self.assertEqual(_compact_problem_hint(item_record), "Preco")
        self.assertEqual(_compact_problem_hint(falta_record), "Falta")

    def test_naturalize_critica_text_removes_te_codes_and_keeps_reason(self) -> None:
        text = _naturalize_critica_text("TE 4 | Preco abaixo do minimo informado (57,30); TE: 4")

        self.assertEqual(text, "Preco abaixo do minimo permitido. Minimo informado: R$ 57,30")

    def test_annotate_duplicate_client_orders_compares_same_client_order_products(self) -> None:
        records = [
            make_critica_record(pedido="708005", cod_pdv="6667", data_pedido=date(2026, 6, 3), problemas=()),
            make_critica_record(pedido="708006", cod_pdv="6667", data_pedido=date(2026, 6, 4), problemas=()),
            make_critica_record(pedido="708007", cod_pdv="9999", problemas=()),
        ]

        annotated = _annotate_duplicate_client_orders(records)
        duplicated = [record for record in annotated if record.cod_pdv == "6667"]
        isolated = [record for record in annotated if record.cod_pdv == "9999"][0]

        self.assertTrue(all(record.pedido_cliente_duplicado for record in duplicated))
        self.assertEqual(duplicated[0].duplicate_order_numbers, ("708005", "708006"))
        self.assertEqual(duplicated[0].duplicate_order_refs, ("708005 em 03/06/2026", "708006 em 04/06/2026"))
        self.assertTrue(any("Possivel pedido duplicado" in label for label in duplicated[0].problemas))
        self.assertFalse(isolated.pedido_cliente_duplicado)

    def test_annotate_duplicate_client_orders_uses_context_from_other_dates(self) -> None:
        records = [
            make_critica_record(pedido="708005", cod_pdv="6667", data_pedido=date(2026, 6, 3), problemas=()),
        ]
        context_records = records + [
            make_critica_record(pedido="708006", cod_pdv="6667", data_pedido=date(2026, 6, 2), problemas=()),
        ]

        annotated = _annotate_duplicate_client_orders(records, context_records=context_records)

        self.assertTrue(annotated[0].pedido_cliente_duplicado)
        self.assertEqual(annotated[0].duplicate_order_refs, ("708005 em 03/06/2026", "708006 em 02/06/2026"))

    def test_annotate_duplicate_client_orders_ignores_same_client_with_different_products(self) -> None:
        records = [
            make_critica_record(pedido="708005", cod_pdv="6667", produto_codigo="2349", problemas=()),
            make_critica_record(pedido="708006", cod_pdv="6667", produto_codigo="13065", problemas=()),
        ]

        annotated = _annotate_duplicate_client_orders(records)

        self.assertFalse(any(record.pedido_cliente_duplicado for record in annotated))

    def test_annotate_duplicate_client_orders_ignores_same_client_with_different_quantities(self) -> None:
        records = [
            make_critica_record(pedido="708005", cod_pdv="6667", quantidade=Decimal("2"), problemas=()),
            make_critica_record(pedido="708006", cod_pdv="6667", quantidade=Decimal("3"), problemas=()),
        ]

        annotated = _annotate_duplicate_client_orders(records)

        self.assertFalse(any(record.pedido_cliente_duplicado for record in annotated))

    def test_summarize_records_and_order_records_group_by_order(self) -> None:
        records = [
            make_critica_record(
                filial="3",
                pedido="100",
                cod_pdv="18008",
                total_pedido=Decimal("120"),
                peso_item=Decimal("20"),
                cond_pag_pedido="PROMO 21 DIAS",
                quantidade=Decimal("2"),
                fator_hecto=Decimal("0.100000"),
                hectolitros=Decimal("0.200000"),
                cesta_nab_tt=True,
                problemas=("Pedido no buffer (mapa 1)",),
            ),
            make_critica_record(
                filial="3",
                pedido="100",
                cod_pdv="18008",
                produto_codigo="999",
                total_pedido=Decimal("120"),
                peso_item=Decimal("15"),
                cond_pag_pedido="PROMO 21 DIAS",
                quantidade=Decimal("3"),
                fator_hecto=Decimal("0.050000"),
                hectolitros=Decimal("0.150000"),
                cesta_high_end=True,
                cesta_cerveja_tt=True,
                problemas=(),
            ),
            make_critica_record(
                filial="1",
                pedido="200",
                cod_pdv="19095",
                total_pedido=Decimal("300"),
                peso_item=Decimal("40"),
                cond_pag_pedido="A VISTA",
                operation_name="Sousa",
                quantidade=Decimal("4"),
                fator_hecto=Decimal("0.200000"),
                hectolitros=Decimal("0.800000"),
                cesta_refri_zero=True,
                cesta_cerveja_rgb=True,
                cesta_cerveja_ow=True,
                cesta_marketplace_tt=True,
                problemas=("Preco fora da DPrecos",),
            ),
        ]

        summary = _summarize_records(records)
        order_records = _build_order_records(records)

        self.assertEqual(summary.pedido_count, 2)
        self.assertEqual(summary.row_count, 3)
        self.assertEqual(summary.problem_pedido_count, 2)
        self.assertEqual(summary.total_pedido, Decimal("420"))
        self.assertEqual(summary.peso_total, Decimal("75"))
        self.assertEqual(summary.total_hectolitros, Decimal("1.150000"))
        self.assertEqual(summary.nab_tt_hectolitros, Decimal("0.200000"))
        self.assertEqual(summary.high_end_hectolitros, Decimal("0.150000"))
        self.assertEqual(summary.cerveja_tt_hectolitros, Decimal("0.150000"))
        self.assertEqual(summary.refri_zero_hectolitros, Decimal("0.800000"))
        self.assertEqual(summary.cerveja_rgb_hectolitros, Decimal("0.800000"))
        self.assertEqual(summary.cerveja_ow_hectolitros, Decimal("0.800000"))
        self.assertEqual(summary.marketplace_tt_hectolitros, Decimal("0"))
        self.assertEqual(summary.marketplace_tt_faturamento, Decimal("172.80"))
        self.assertEqual(summary.operations, ("Patos", "Sousa"))
        self.assertEqual(len(order_records), 2)
        self.assertEqual(order_records[0].pedido, "200")
        self.assertEqual(order_records[0].peso_pedido, Decimal("40"))
        self.assertEqual(order_records[0].cond_pag_pedido, "A VISTA")
        self.assertEqual(order_records[1].pedido, "100")
        self.assertEqual(order_records[1].peso_pedido, Decimal("35"))
        self.assertEqual(order_records[1].cond_pag_pedido, "PROMO 21 DIAS")
        self.assertEqual(order_records[1].item_count, 2)
        self.assertEqual(order_records[1].problem_item_count, 1)

    def test_summary_order_client_markup_includes_weight_and_payment_condition(self) -> None:
        order = _build_order_records(
            [
                make_critica_record(
                    pedido="100",
                    peso_item=Decimal("12.5"),
                    cond_pag_pedido="PROMO 21 DIAS",
                ),
                make_critica_record(
                    pedido="100",
                    produto_codigo="999",
                    peso_item=Decimal("7.5"),
                    cond_pag_pedido="PROMO 21 DIAS",
                ),
            ]
        )[0]

        markup = _summary_order_client_markup(order)

        self.assertIn("POSTO PAIZAO", markup)
        self.assertIn("Peso&#160;do&#160;Pedido(Kg):20", markup)
        self.assertIn("Cond.Pag.:", markup)
        self.assertIn("PROMO&#160;21&#160;DIAS", markup)

    def test_build_product_summary_rows_groups_product_totals(self) -> None:
        rows = _build_product_summary_rows(
            [
                make_critica_record(
                    produto_codigo="100",
                    produto_descricao="PRODUTO TESTE",
                    quantidade=Decimal("2"),
                    hectolitros=Decimal("0.20"),
                    preco_unitario=Decimal("10"),
                    peso_item=Decimal("5"),
                    problemas=(),
                ),
                make_critica_record(
                    produto_codigo="100",
                    produto_descricao="PRODUTO TESTE",
                    quantidade=Decimal("3"),
                    hectolitros=Decimal("0.30"),
                    preco_unitario=Decimal("10"),
                    peso_item=Decimal("7"),
                    problemas=(),
                ),
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantidade"], Decimal("5"))
        self.assertEqual(rows[0]["hectolitros"], Decimal("0.50"))
        self.assertEqual(rows[0]["faturamento"], Decimal("50"))
        self.assertEqual(rows[0]["peso"], Decimal("12"))

    def test_duplicate_product_requires_same_price_or_extreme_difference(self) -> None:
        records = [
            make_critica_record(filial="3", pedido="100", produto_codigo="2349", preco_unitario=Decimal("10"), problemas=()),
            make_critica_record(filial="3", pedido="100", produto_codigo="2349", preco_unitario=Decimal("11"), problemas=()),
            make_critica_record(filial="3", pedido="101", produto_codigo="2349", preco_unitario=Decimal("10"), problemas=()),
            make_critica_record(filial="3", pedido="101", produto_codigo="2349", preco_unitario=Decimal("10"), problemas=()),
            make_critica_record(filial="3", pedido="102", produto_codigo="2349", preco_unitario=Decimal("10"), problemas=()),
            make_critica_record(filial="3", pedido="102", produto_codigo="2349", preco_unitario=Decimal("16"), problemas=()),
        ]

        annotated = _annotate_duplicate_products_by_price(records)

        self.assertFalse(annotated[0].pedido_produto_duplicado)
        self.assertFalse(annotated[1].pedido_produto_duplicado)
        self.assertTrue(annotated[2].pedido_produto_duplicado)
        self.assertTrue(annotated[3].pedido_produto_duplicado)
        self.assertTrue(annotated[4].pedido_produto_duplicado)
        self.assertTrue(annotated[5].pedido_produto_duplicado)

    def test_annotate_client_total_above_average_uses_sum_of_client_orders(self) -> None:
        records = [
            make_critica_record(
                filial="3",
                cod_pdv="18008",
                pedido="100",
                total_pedido=Decimal("350"),
                total_cliente=Decimal("350"),
                avg_order_value_3m=Decimal("300"),
                problemas=(),
            ),
            make_critica_record(
                filial="3",
                cod_pdv="18008",
                pedido="101",
                produto_codigo="999",
                total_pedido=Decimal("280"),
                total_cliente=Decimal("280"),
                avg_order_value_3m=Decimal("300"),
                problemas=(),
            ),
            make_critica_record(
                filial="3",
                cod_pdv="19095",
                pedido="200",
                total_pedido=Decimal("550"),
                total_cliente=Decimal("550"),
                avg_order_value_3m=Decimal("300"),
                problemas=(),
            ),
        ]

        annotated = _annotate_client_total_above_average(records)

        self.assertTrue(annotated[0].order_above_average)
        self.assertTrue(annotated[1].order_above_average)
        self.assertEqual(annotated[0].total_cliente, Decimal("630"))
        self.assertEqual(annotated[1].total_cliente, Decimal("630"))
        self.assertTrue(any("Cliente acima da media de compra: total em pedidos R$ 630,00; media R$ 300,00" in label for label in annotated[0].problemas))
        self.assertFalse(annotated[2].order_above_average)

    def test_summarize_problem_indicators_count_orders_not_products(self) -> None:
        records = [
            make_critica_record(
                filial="3",
                pedido="100",
                produto_codigo="2349",
                critica_text="Fora de rota",
                ocorrencia_1="Ocorrencia",
                pedido_produto_duplicado=True,
                produto_encontrado_dprecos=False,
                order_above_average=True,
                inad_total_vencido=Decimal("100"),
                inad_titulos_vencidos=1,
                multipack_item=True,
                multipack_allowed=False,
                map_status="buffer",
                cond_divergente=True,
                limit_exceeded_amount=Decimal("50"),
                price_reference=Decimal("100"),
                price_delta_pct=Decimal("0.20"),
                problemas=("Problema",),
            ),
            make_critica_record(
                filial="3",
                pedido="100",
                produto_codigo="9999",
                critica_text="Fora de rota",
                ocorrencia_2="Ocorrencia complementar",
                pedido_produto_duplicado=True,
                produto_encontrado_dprecos=False,
                order_above_average=True,
                inad_total_vencido=Decimal("100"),
                inad_titulos_vencidos=1,
                multipack_item=True,
                multipack_allowed=False,
                map_status="buffer",
                cond_divergente=True,
                limit_exceeded_amount=Decimal("50"),
                price_reference=Decimal("100"),
                price_delta_pct=Decimal("0.20"),
                problemas=("Problema",),
            ),
        ]

        summary = _summarize_records(records)

        self.assertEqual(summary.row_count, 2)
        self.assertEqual(summary.pedido_count, 1)
        self.assertEqual(summary.rows_with_critica, 1)
        self.assertEqual(summary.duplicated_row_count, 1)
        self.assertEqual(summary.price_alert_count, 1)
        self.assertEqual(summary.missing_price_count, 1)
        self.assertEqual(summary.order_avg_alert_count, 1)
        self.assertEqual(summary.inadimplente_count, 1)
        self.assertEqual(summary.multipack_violation_count, 0)
        self.assertEqual(summary.map_buffer_count, 1)
        self.assertEqual(summary.cond_divergence_count, 1)
        self.assertEqual(summary.limit_alert_count, 1)


if __name__ == "__main__":
    unittest.main()
