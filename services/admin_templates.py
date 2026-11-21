from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from pathlib import Path

# Uma linha que contém só "<!--#include caminho/arquivo -->" é trocada pelo
# conteúdo do arquivo (caminho relativo à pasta do template). Serve para o
# painel ficar dividido por aba sem precisar de motor de template.
_INCLUDE = re.compile(r"^[ \t]*<!--#include ([\w./-]+) -->[ \t]*(?:\r?\n|$)", re.MULTILINE)
_MAX_NIVEIS = 5

# Endereços em que o painel busca o CSS e o JS. O "?v=" muda sempre que o
# conteúdo muda, então o navegador pode guardar os arquivos sem prazo.
PAINEL_CSS = "/painel/app.css"
PAINEL_JS = "/painel/app.js"
_TIPOS_RECURSO = {
    PAINEL_CSS: "text/css; charset=utf-8",
    PAINEL_JS: "text/javascript; charset=utf-8",
}


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


@dataclass(frozen=True)
class PainelMontado:
    html: str
    recursos: dict[str, tuple[str, str]]  # endereço -> (tipo, conteúdo)


def separar_recursos(html: str) -> PainelMontado:
    """Tira o CSS e o JS de dentro da página e troca por links com versão.

    Assim a página (que não pode ficar guardada, porque depende do login) fica
    pequena, e os ~1 MB de CSS/JS ficam guardados no navegador entre as visitas.
    """
    estilo_ini = html.index("<style>")
    estilo_fim = html.index("</style>", estilo_ini)
    script_ini = html.rindex("<script>")
    script_fim = html.index("</script>", script_ini)
    css = html[estilo_ini + len("<style>"):estilo_fim]
    js = html[script_ini + len("<script>"):script_fim]
    versao = hashlib.sha256((css + js).encode("utf-8")).hexdigest()[:12]
    pagina = (
        html[:estilo_ini]
        + f'<link rel="stylesheet" href="{PAINEL_CSS}?v={versao}">'
        + html[estilo_fim + len("</style>"):script_ini]
        + f'<script src="{PAINEL_JS}?v={versao}"></script>'
        + html[script_fim + len("</script>"):]
    )
    return PainelMontado(
        html=pagina,
        recursos={PAINEL_CSS: (_TIPOS_RECURSO[PAINEL_CSS], css), PAINEL_JS: (_TIPOS_RECURSO[PAINEL_JS], js)},
    )


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
        self._painel: PainelMontado | None = None
        self._painel_assinatura: tuple | None = None
        self._painel_trava = threading.Lock()

    def _assinatura_painel(self) -> tuple:
        # Data de alteração de cada arquivo da pasta: se nada mudou, o painel
        # montado em memória continua valendo e nenhum arquivo é relido.
        pasta = self.import_panel_template.parent
        return tuple(sorted((str(item), item.stat().st_mtime_ns) for item in pasta.rglob("*") if item.is_file()))

    def _painel_montado(self) -> PainelMontado:
        assinatura = self._assinatura_painel()
        with self._painel_trava:
            if self._painel is None or assinatura != self._painel_assinatura:
                html = montar_template(self.import_panel_template).replace(
                    "__API_AUTH_ENABLED__",
                    "true" if self.api_auth_enabled else "false",
                )
                self._painel = separar_recursos(html)
                self._painel_assinatura = assinatura
            return self._painel

    def load_import_panel_html(self) -> str:
        if self.import_panel_template.exists():
            return self._painel_montado().html
        return "<html><body><h1>Painel indisponivel</h1></body></html>"

    def load_panel_asset(self, endereco: str) -> tuple[str, str] | None:
        """Devolve (tipo, conteúdo) do CSS ou JS do painel, ou None se não existir."""
        if not self.import_panel_template.exists():
            return None
        return self._painel_montado().recursos.get(endereco)

    def load_login_html(self) -> str:
        if self.login_template.exists():
            return montar_template(self.login_template)
        return "<html><body><h1>Login indisponivel</h1></body></html>"

    def load_change_password_html(self) -> str:
        if self.change_password_template and self.change_password_template.exists():
            return montar_template(self.change_password_template)
        return "<html><body><h1>Troca de senha indisponivel</h1></body></html>"
