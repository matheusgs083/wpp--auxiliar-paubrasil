from __future__ import annotations

from pathlib import Path


class AdminTemplateLoader:
    def __init__(
        self,
        *,
        import_panel_template: Path,
        login_template: Path,
        api_auth_enabled: bool,
    ) -> None:
        self.import_panel_template = import_panel_template
        self.login_template = login_template
        self.api_auth_enabled = api_auth_enabled

    def load_import_panel_html(self) -> str:
        if self.import_panel_template.exists():
            return self.import_panel_template.read_text(encoding="utf-8").replace(
                "__API_AUTH_ENABLED__",
                "true" if self.api_auth_enabled else "false",
            )
        return "<html><body><h1>Painel indisponivel</h1></body></html>"

    def load_login_html(self) -> str:
        if self.login_template.exists():
            return self.login_template.read_text(encoding="utf-8")
        return "<html><body><h1>Login indisponivel</h1></body></html>"
