from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT.parent))

from bot_api.integrations.evolution_client import extract_incoming_message as extract_evolution_incoming_message
from bot_api.integrations.meta_cloud_client import extract_incoming_message as extract_meta_cloud_incoming_message


def _load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reprocessa um payload salvo de webhook e mostra o que o parser do bot extrai dele.",
    )
    parser.add_argument("provider", choices=("evolution", "meta"), help="Origem do payload salvo.")
    parser.add_argument("payload_path", help="Caminho do arquivo JSON capturado.")
    args = parser.parse_args(argv)

    payload_path = Path(args.payload_path)
    payload = _load_payload(payload_path)
    if args.provider == "evolution":
        incoming = extract_evolution_incoming_message(payload)
    else:
        incoming = extract_meta_cloud_incoming_message(payload)

    if incoming is None:
        print("Nenhuma mensagem processavel foi extraida desse payload.")
        return 1

    print(json.dumps(
        {
            "channel": incoming.channel,
            "sender": incoming.sender,
            "text": incoming.text,
            "message_id": incoming.message_id,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
