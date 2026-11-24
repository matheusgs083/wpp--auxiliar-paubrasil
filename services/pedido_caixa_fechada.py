"""Trava de caixa fechada na digitação: o 600 retornável é digitado em dúzias, mas sai em caixa.

Uma caixa de 600 tem 24 garrafas = 2 dúzias, então a quantidade em dúzias precisa ser
par. Vale para venda e para bonificação. O produto é reconhecido só pela descrição:
600 ml que não seja one way, PET, lata ou caixa de fábrica (esses já são vendidos em
caixa). A unidade da grade não serve: o litrão também vem em DZ, mas a caixa dele é
de 1 dúzia, então não tem trava.
"""

from __future__ import annotations

import re
import unicodedata

DUZIAS_POR_CAIXA = 2

_DESCRICAO_600 = re.compile(r"\b600\s*(ML|M\b|\b)")
_JA_EM_CAIXA = re.compile(r"ONE\s*WAY|\bPET\b|\bLATA\b|\bLT\b|C/\s*\d+|\bCAIXA\b|\bCX\b")


def _texto(valor: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


def exige_caixa_fechada(descricao: str, unidade: str = "") -> bool:
    """True quando o produto é digitado em dúzias e só pode sair em caixa (2 dúzias).

    ``unidade`` fica na assinatura para quem já chama com ela, mas não decide nada.
    """
    texto = _texto(descricao)
    return bool(_DESCRICAO_600.search(texto)) and not _JA_EM_CAIXA.search(texto)


def mensagem_caixa_fechada(produto: str, descricao: str, quantidade: int) -> str:
    nome = f"{produto} ({descricao.strip()})" if descricao.strip() else produto
    abaixo = quantidade - quantidade % DUZIAS_POR_CAIXA
    sugestoes = " ou ".join(str(q) for q in (abaixo, abaixo + DUZIAS_POR_CAIXA) if q > 0)
    return (
        f"Produto {nome}: o 600 só sai em caixa fechada (1 caixa = {DUZIAS_POR_CAIXA} dúzias). "
        f"Digite um número par de dúzias, por exemplo {sugestoes}."
    )
