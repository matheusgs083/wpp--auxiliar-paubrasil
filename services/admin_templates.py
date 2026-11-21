from __future__ import annotations

import re
from pathlib import Path

# Uma linha que contém só "<!--#include caminho/arquivo -->" é trocada pelo
# conteúdo do arquivo (caminho relativo à pasta do template). Serve para o
# painel ficar dividido por aba sem precisar de motor de template.
_INCLUDE = re.compile(r"^[ \t]*<!--#include ([\w./-]+) -->[ \t]*(?:\r?\n|$)", re.MULTILINE)
_MAX_NIVEIS = 5


def montar_template(caminho: Path, raiz: Path | None = None, _nivel: int = 0) -> str:
    """Lê o template e resolve os includes, inclusive dentro dos arquivos incluídos."""
    raiz = (raiz or caminho.parent).resolve()
    if _nivel > _MAX_NIVEIS:
        raise ValueError(f"Includes aninhados demais em {caminho}")
    texto = caminho.read_text(encoding="utf-8")

    def incluir(match: re.Match[str]) -> str:
        alvo = (raiz / match.group(1)).resolve()
        if raiz not in alvo.parents:
            raise ValueError(f"Include fora da pasta de templates: {match.group(1)}")
        if not alvo.is_file():
            raise FileNotFoundError(f"Include não encontrado: {match.group(1)}")
        conteudo = montar_template(alvo, raiz, _nivel + 1)
        return conteudo if conteudo.endswith("\n") else conteudo + "\n"

    return _INCLUDE.sub(incluir, texto)


class AdminTemplateLoader:
    def __init__(
        self,
        *,
        import_panel_template: Path,
        login_template: Path,
        change_password_template: Path | None = None,
        api_auth_enabled: bool,
    ) -> None:
        self.import_panel_template = import_panel_template
        self.login_template = login_template
        self.change_password_template = change_password_template
        self.api_auth_enabled = api_auth_enabled

    def load_import_panel_html(self) -> str:
        if self.import_panel_template.exists():
            return montar_template(self.import_panel_template).replace(
                "__API_AUTH_ENABLED__",
                "true" if self.api_auth_enabled else "false",
            )
        return "<html><body><h1>Painel indisponivel</h1></body></html>"

    def load_login_html(self) -> str:
        if self.login_template.exists():
            return montar_template(self.login_template)
        return "<html><body><h1>Login indisponivel</h1></body></html>"

    def load_change_password_html(self) -> str:
        if self.change_password_template and self.change_password_template.exists():
            return montar_template(self.change_password_template)
        return "<html><body><h1>Troca de senha indisponivel</h1></body></html>"
