"""Vínculos excepcionais do terceiro ajudante de Sumé.

O relatório 03.08.05 não possui uma coluna ``CdAju3``. Esta tabela registra
somente as combinações confirmadas na escala de setembro de 2026 em que o
Irismark deve ser acrescentado à equipe da rota.
"""

IRISMARK_CODE = "9076"

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
