"""Vínculos excepcionais do terceiro ajudante de Sumé.

O relatório 03.08.05 não possui uma coluna ``CdAju3``. Esta tabela registra
as combinações confirmadas na escala de setembro de 2026 em que o Irismark
deve ser acrescentado à equipe da rota. A regra é por competência, data e
placa; portanto continua válida mesmo quando o motorista troca.
"""

IRISMARK_CODE = "9076"

# As placas vêm da escala e permitem manter o vínculo mesmo se o motorista for
# trocado. As datas abaixo são as datas das colunas da escala (segunda a sexta),
# e não a data de processamento que aparece no 03.08.05.
IRISMARK_AUXILIARY_PLATES: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        ("2026-09", "2026-09-01", "SUME", "SKZ8I57"),
        ("2026-09", "2026-09-01", "SUME", "SKZ7H38"),
        ("2026-09", "2026-09-02", "SUME", "SKZ8I17"),
        ("2026-09", "2026-09-02", "SUME", "RLS8A29"),
        ("2026-09", "2026-09-03", "SUME", "SKZ7H38"),
        ("2026-09", "2026-09-04", "SUME", "RLR8F99"),
        ("2026-09", "2026-09-15", "SUME", "SKZ8I57"),
        ("2026-09", "2026-09-17", "SUME", "SKZ8I57"),
        ("2026-09", "2026-09-21", "SUME", "SKZ8I57"),
        ("2026-09", "2026-09-22", "SUME", "SKZ7H38"),
        ("2026-09", "2026-09-23", "SUME", "SKZ7H38"),
        ("2026-09", "2026-09-24", "SUME", "SKZ7H38"),
    }
)

# (competência, data da rota, filial, código do motorista)
IRISMARK_AUXILIARY: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        ("2026-09", "2026-09-01", "SUME", "9083"),
        ("2026-09", "2026-09-01", "SUME", "9085"),
        ("2026-09", "2026-09-02", "SUME", "9083"),
        ("2026-09", "2026-09-02", "SUME", "9085"),
        ("2026-09", "2026-09-02", "SUME", "9087"),
        ("2026-09", "2026-09-02", "SUME", "9097"),
        ("2026-09", "2026-09-03", "SUME", "9083"),
        ("2026-09", "2026-09-03", "SUME", "9087"),
        ("2026-09", "2026-09-04", "SUME", "9083"),
        ("2026-09", "2026-09-15", "SUME", "9085"),
        ("2026-09", "2026-09-17", "SUME", "9087"),
        ("2026-09", "2026-09-21", "SUME", "9083"),
        ("2026-09", "2026-09-22", "SUME", "9078"),
        ("2026-09", "2026-09-23", "SUME", "9085"),
        ("2026-09", "2026-09-24", "SUME", "9087"),
    }
)
