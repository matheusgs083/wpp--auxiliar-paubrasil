"""Vínculos excepcionais do terceiro ajudante de Sumé.

O relatório 03.08.05 não possui uma coluna ``CdAju3``. Esta tabela registra
somente as combinações confirmadas na escala de setembro de 2026 em que o
Irismark deve ser acrescentado à equipe da rota.
"""

IRISMARK_CODE = "9076"

# As placas vêm da escala e permitem manter o vínculo mesmo se o motorista for
# trocado. O código do motorista permanece como fallback para placas alteradas
# no relatório de execução.
IRISMARK_AUXILIARY_PLATES: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        ("2026-09", "2026-09-02", "SUME", "SKZ8I17"),
        ("2026-09", "2026-09-02", "SUME", "RLS8A29"),
        ("2026-09", "2026-09-03", "SUME", "SKZ7H38"),
        ("2026-09", "2026-09-04", "SUME", "RLR8F99"),
        ("2026-09", "2026-09-17", "SUME", "SKZ8I57"),
        ("2026-09", "2026-09-21", "SUME", "SKZ8I57"),
        ("2026-09", "2026-09-23", "SUME", "SKZ7H38"),
        ("2026-09", "2026-09-25", "SUME", "SKZ7H38"),
        ("2026-09", "2026-09-25", "SUME", "SKZ8I57"),
    }
)

# (competência, data da rota, filial, código do motorista)
IRISMARK_AUXILIARY: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        ("2026-09", "2026-09-02", "SUME", "9083"),
        ("2026-09", "2026-09-02", "SUME", "9085"),
        ("2026-09", "2026-09-03", "SUME", "9097"),
        ("2026-09", "2026-09-04", "SUME", "9083"),
        ("2026-09", "2026-09-17", "SUME", "9087"),
        ("2026-09", "2026-09-21", "SUME", "9083"),
        ("2026-09", "2026-09-23", "SUME", "9085"),
        ("2026-09", "2026-09-25", "SUME", "9078"),
        ("2026-09", "2026-09-25", "SUME", "9085"),
        ("2026-09", "2026-09-25", "SUME", "9087"),
    }
)
