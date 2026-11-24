"""Bloco "Cadastro e documentos" da ficha do cliente, montado da linha da dClientes.

Tudo sai do payload da dClientes (a linha inteira do relatório), menos o status de
cada documento, que vem da base de documentação pendente (OK/Nok por documento).
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date, timedelta
from typing import Any

DIAS_SEMANA = {
    "SEG": ("Segunda", 0), "TER": ("Terça", 1), "QUA": ("Quarta", 2), "QUI": ("Quinta", 3),
    "SEX": ("Sexta", 4), "SAB": ("Sábado", 5), "DOM": ("Domingo", 6),
}

# (rótulo, campos da documentação pendente que precisam estar OK, observação)
DOCUMENTOS = (
    ("Contrato social", ("contrato_social",), ""),
    ("Comprovante de residência", ("comprovante_residencia",), ""),
    ("Identidade", ("rg", "cpf"), "RG e CPF"),
    ("Fachada", ("fachada",), ""),
)


def montar_cadastro(payload: dict[str, Any], doc: Any | None, *, hoje: date, docs_disponivel: bool = True) -> dict[str, Any]:
    """Campos do bloco a partir da linha da dClientes e do registro de documentação (ou None)."""
    dias_vendedor = dias_da_visita(campo(payload, "Dia de Visita do VDE"))
    dias_bees = dias_da_visita(campo(payload, "Dia de Visita do VDI"))
    return {
        "razao_social": campo(payload, "Razão Social"),
        "nome_fantasia": campo(payload, "Nome Fantasia"),
        "documento": campo(payload, "Documento"),
        "tipo_pessoa": campo(payload, "Tipo de Pessoa"),
        "situacao_rf": campo(payload, "Situação na RF"),
        "status": campo(payload, "Status do PDV"),
        "endereco": " - ".join(p for p in (campo(payload, "Endereço"), campo(payload, "Complemento")) if p),
        "bairro_cidade": _bairro_cidade(payload),
        "cep": campo(payload, "CEP"),
        "telefones": telefones(campo(payload, "Telefone(s)")),
        "setor": _codigo(campo(payload, "Setor VDE")),
        "gv": _codigo(campo(payload, "GV VDE")),
        "visita_vendedor": dias_por_extenso(dias_vendedor),
        "proxima_visita": _proxima(campo(payload, "Data da Prox Visita VDE"), dias_vendedor, hoje),
        "contato_bees": dias_por_extenso(dias_bees),
        "proximo_contato_bees": _proxima(campo(payload, "Data da Prox Visita VDI"), dias_bees, hoje),
        "categoria": campo(payload, "Categoria"),
        "segmento": campo(payload, "Segmento NGE"),
        "rede": campo(payload, "Nome Rede"),
        "cliente_desde": _data_valida(campo(payload, "Data de Cadastro")),
        "documentacao": documentacao(doc, campo(payload, "Situação Documentação"), docs_disponivel),
    }


def documentacao(doc: Any | None, situacao_dclientes: str, disponivel: bool) -> dict[str, Any]:
    """Status por documento (base de documentação pendente) e se o cadastro está completo."""
    itens = []
    if doc is not None:
        for rotulo, campos, observacao in DOCUMENTOS:
            ok = all(str(getattr(doc, nome, "") or "").strip().upper() == "OK" for nome in campos)
            itens.append({"rotulo": rotulo, "ok": ok, "observacao": observacao})
    if itens:
        completa: bool | None = all(item["ok"] for item in itens)
    elif situacao_dclientes:
        completa = _sem_acento(situacao_dclientes).upper().startswith("SIM")
    else:
        completa = None
    return {"completa": completa, "pendentes": sum(1 for item in itens if not item["ok"]), "itens": itens, "disponivel": disponivel}


def dias_da_visita(texto: str) -> list[str]:
    """'SEG/QUI' -> ['SEG', 'QUI'] (só dias conhecidos, na ordem da semana)."""
    codigos = {parte[:3] for parte in re.split(r"[^A-Z]+", _sem_acento(texto).upper()) if parte[:3] in DIAS_SEMANA}
    return sorted(codigos, key=lambda c: DIAS_SEMANA[c][1])


def dias_por_extenso(codigos: list[str]) -> str:
    return ", ".join(DIAS_SEMANA[c][0] for c in codigos)


def proxima_data(codigos: list[str], hoje: date) -> date | None:
    """Próximo dia da semana da lista, a partir de hoje (inclusive)."""
    for passo in range(7):
        dia = hoje + timedelta(days=passo)
        if any(DIAS_SEMANA[c][1] == dia.weekday() for c in codigos):
            return dia
    return None


def visitas_no_mes(codigos: list[str], ano: int, mes: int, *, desde: int = 1) -> int:
    """Quantos dias de visita há no mês a partir do dia ``desde`` (inclusive)."""
    dias = calendar.monthrange(ano, mes)[1]
    semana = {DIAS_SEMANA[c][1] for c in codigos}
    return sum(1 for dia in range(desde, dias + 1) if date(ano, mes, dia).weekday() in semana)


def telefones(texto: str) -> list[str]:
    return [re.sub(r"\s+", " ", parte).strip() for parte in str(texto or "").split("|") if parte.strip()]


def campo(payload: dict[str, Any], nome: str) -> str:
    """Valor da coluna da dClientes, sem depender de acento ou espaço sobrando no cabeçalho."""
    if nome in payload:
        return str(payload.get(nome) or "").strip()
    alvo = _sem_acento(nome).lower()
    for chave, valor in payload.items():
        if _sem_acento(str(chave)).strip().lower() == alvo:
            return str(valor or "").strip()
    return ""


def _proxima(data_relatorio: str, codigos: list[str], hoje: date) -> str:
    # A data do relatório vale enquanto não passou; depois, calcula pelo dia da visita.
    data = _para_data(data_relatorio)
    if data and data >= hoje:
        return data.strftime("%d/%m/%Y")
    calculada = proxima_data(codigos, hoje)
    return calculada.strftime("%d/%m/%Y") if calculada else ""


def _bairro_cidade(payload: dict[str, Any]) -> str:
    cidade = campo(payload, "Cidade")
    uf = campo(payload, "UF")
    return ", ".join(p for p in (campo(payload, "Bairro"), cidade, uf) if p)


def _data_valida(texto: str) -> str:
    data = _para_data(texto)
    return data.strftime("%d/%m/%Y") if data else ""


def _para_data(texto: str) -> date | None:
    achado = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", str(texto or "").strip())
    if not achado:
        return None
    dia, mes, ano = (int(p) for p in achado.groups())
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def _codigo(texto: str) -> str:
    return str(texto or "").strip().lstrip("0")


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto or "")) if not unicodedata.combining(c))
