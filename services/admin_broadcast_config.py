from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ADMIN_BROADCAST_SEND_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class AdminBroadcastConfig:
    actions: dict[str, dict[str, Any]]
    day_options: dict[str, dict[str, str]]
    target_modes: dict[str, dict[str, str]]
    audiences: dict[str, dict[str, str]]
    state: dict[str, Any]
    daily_route_status: dict[str, Any]
    send_delay_seconds: float = ADMIN_BROADCAST_SEND_DELAY_SECONDS


def build_admin_broadcast_config(*, daily_route_broadcast_enabled: bool) -> AdminBroadcastConfig:
    return AdminBroadcastConfig(
        actions={
            "rota_dia": {
                "label": "Rota do dia",
                "description": "Envia os clientes da rota do dia para cada usuario.",
                "shortcut": "rota hoje",
                "shortcut_template": "rota {day}",
                "area": "cliente",
                "supports_day": True,
            },
            "inad_hoje": {
                "label": "Inad por dia",
                "description": "Executa o atalho de risco/cobranca da rota escolhida para cada usuario.",
                "shortcut": "inad hoje",
                "shortcut_template": "inad {day}",
                "area": "inadimplencia",
                "supports_day": True,
            },
            "giro_hoje": {
                "label": "Giro por dia",
                "description": "Executa o atalho de giro da rota escolhida para cada usuario.",
                "shortcut": "giro hoje",
                "shortcut_template": "giro {day}",
                "area": "cliente",
                "supports_day": True,
            },
            "inad_base": {
                "label": "Inad da base",
                "description": "Executa o atalho de inadimplentes da base/carteira para cada usuario.",
                "shortcut": "inadimplentes da base",
                "area": "inadimplencia",
                "supports_day": False,
            },
            "giro_zero_base": {
                "label": "Giro zero da base",
                "description": "Executa o atalho de clientes com giro zero da base/carteira para cada usuario.",
                "shortcut": "giro zero da base",
                "area": "cliente",
                "supports_day": False,
            },
            "critica_setor_pdf": {
                "label": "Critica PDF por setor",
                "description": "Envia a critica em PDF do setor do vendedor dentro da operacao escolhida.",
                "shortcut": "critica pdf",
                "area": "cliente",
                "supports_day": False,
                "target_audiences": ["vendedor"],
                "per_recipient_shortcut": "critica_sector_pdf",
            },
        },
        day_options={
            "hoje": {"label": "Hoje", "token": "hoje"},
            "segunda": {"label": "Segunda", "token": "segunda"},
            "terca": {"label": "Terca", "token": "terca"},
            "quarta": {"label": "Quarta", "token": "quarta"},
            "quinta": {"label": "Quinta", "token": "quinta"},
            "sexta": {"label": "Sexta", "token": "sexta"},
            "sabado": {"label": "Sabado", "token": "sabado"},
            "domingo": {"label": "Domingo", "token": "domingo"},
        },
        target_modes={
            "filial": {"label": "Todos da filial"},
            "specific": {"label": "Numero especifico"},
        },
        audiences={
            "vendedor": {
                "label": "Vendedores (RN)",
                "role": "vendedor",
                "role_label": "RN",
                "empty_message": "Nenhum vendedor/RN ativo encontrado para essa filial.",
            },
            "gerente_vendas": {
                "label": "GVs",
                "role": "gerente_vendas",
                "role_label": "GV",
                "empty_message": "Nenhum GV ativo encontrado para essa filial.",
            },
        },
        state={
            "running": False,
            "current_job_id": "",
            "current_filial": "",
            "current_action": "",
            "current_day": "",
            "current_target_mode": "",
            "current_target_audience": "",
            "current_shortcut": "",
            "started_at": "",
            "total": 0,
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "last_job": {},
        },
        daily_route_status={
            "enabled": bool(daily_route_broadcast_enabled),
            "running": False,
            "last_checked_at": "",
            "last_run_date": "",
            "last_run": {},
            "last_error": "",
        },
    )
