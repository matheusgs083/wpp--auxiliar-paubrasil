from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_PARENT = PROJECT_ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from bot_api.config import get_settings
from bot_api.integrations.evolution_client import EvolutionClient, EvolutionConfig
from bot_api.models import InteractiveOption, OutgoingMessage


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Envia um menu interativo simples pela Evolution para testar suporte real da instancia."
    )
    parser.add_argument("--number", required=True, help="Numero WhatsApp com DDI e DDD. Ex: 5583999999999.")
    parser.add_argument(
        "--mode",
        choices=("list", "buttons", "both"),
        default="list",
        help="Tipo de menu interativo a testar.",
    )
    parser.add_argument(
        "--baseline-text",
        action="store_true",
        help="Envia uma mensagem de texto antes do teste interativo para validar o envio simples.",
    )
    args = parser.parse_args()

    settings = get_settings()
    client = EvolutionClient(
        EvolutionConfig(
            base_url=settings.evolution_base_url,
            api_key=settings.evolution_api_key,
            instance=settings.evolution_instance,
            send_path=settings.evolution_send_path,
            list_path=settings.evolution_list_path,
            buttons_path=settings.evolution_buttons_path,
            media_path=settings.evolution_media_path,
            timeout_seconds=settings.evolution_timeout_seconds,
        )
    )

    if not client.enabled:
        raise RuntimeError("Evolution nao configurada. Confira EVOLUTION_BASE_URL e EVOLUTION_INSTANCE.")

    message = OutgoingMessage(
        kind="menu",
        title="Teste de menu interativo",
        text="Escolha uma opcao abaixo. Este envio nao altera nenhum dado do bot.",
        footer="Se aparecer como lista/botoes, o canal suporta menu interativo.",
        button_text="Escolher opcao",
        options=(
            InteractiveOption(option_id="teste1", title="Opcao 1", description="Teste de selecao"),
            InteractiveOption(option_id="teste2", title="Opcao 2", description="Teste de selecao"),
            InteractiveOption(option_id="voltar", title="Voltar", description="Opcao de retorno"),
        ),
    )

    if args.baseline_text:
        client.send_text(
            number=args.number,
            text="Teste base: se voce recebeu esta mensagem, o envio de texto pela Evolution esta funcionando.",
        )
        print("baseline_text=ok")

    failures: list[str] = []
    if args.mode in {"list", "both"}:
        try:
            client.send_list(number=args.number, message=message)
            print("list=ok")
        except Exception as exc:
            failures.append(f"list={exc}")
            print(f"list=fail: {exc}")

    if args.mode in {"buttons", "both"}:
        try:
            client.send_buttons(number=args.number, message=message)
            print("buttons=ok")
        except Exception as exc:
            failures.append(f"buttons={exc}")
            print(f"buttons=fail: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
