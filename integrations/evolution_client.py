from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from bot_api.models import IncomingMessage, OutgoingMessage


@dataclass(frozen=True)
class EvolutionConfig:
    base_url: str
    api_key: str
    instance: str
    send_path: str
    list_path: str
    buttons_path: str
    timeout_seconds: float


class EvolutionClient:
    def __init__(self, config: EvolutionConfig) -> None:
        self.config = config

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["apikey"] = self.config.api_key
        return headers

    @property
    def enabled(self) -> bool:
        return bool(self.config.base_url and self.config.instance)

    def send(self, number: str, message: OutgoingMessage) -> None:
        # Menus ficam sempre em texto para evitar falhas interativas na Evolution.
        if message.kind == "menu":
            self.send_text(number=number, text=self._menu_fallback_text(message))
            return
        self.send_text(number=number, text=message.text)

    def send_text(self, number: str, text: str) -> None:
        if not self.enabled:
            raise RuntimeError("EVOLUTION_BASE_URL e EVOLUTION_INSTANCE sao obrigatorios para envio.")

        path = self.config.send_path.format(instance=self.config.instance)
        url = f"{self.config.base_url}{path}"

        payload_variants = [
            {"number": number, "text": text},
            {"number": number, "textMessage": {"text": text}},
        ]

        last_error: str | None = None
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            for payload in payload_variants:
                response = client.post(url, headers=self._headers(), content=json.dumps(payload, ensure_ascii=False))
                if 200 <= response.status_code < 300:
                    return
                last_error = f"{response.status_code} {response.text}"

        raise RuntimeError(f"Falha ao enviar mensagem para Evolution: {last_error}")

    def send_list(self, number: str, message: OutgoingMessage) -> None:
        if not self.enabled:
            raise RuntimeError("EVOLUTION_BASE_URL e EVOLUTION_INSTANCE sao obrigatorios para envio.")

        path = self.config.list_path.format(instance=self.config.instance)
        url = f"{self.config.base_url}{path}"
        payload = {
            "number": number,
            "title": message.title or "Consulta de Clientes",
            "description": message.text,
            "buttonText": message.button_text or "Escolher",
            "footerText": message.footer,
            "sections": [
                {
                    "title": "Opcoes",
                    "rows": [
                        {
                            "title": option.title,
                            "description": option.description,
                            "rowId": option.option_id,
                        }
                        for option in message.options
                    ],
                }
            ],
        }
        self._post_json(url, payload)

    def send_buttons(self, number: str, message: OutgoingMessage) -> None:
        if not self.enabled:
            raise RuntimeError("EVOLUTION_BASE_URL e EVOLUTION_INSTANCE sao obrigatorios para envio.")

        path = self.config.buttons_path.format(instance=self.config.instance)
        url = f"{self.config.base_url}{path}"
        payload = {
            "number": number,
            "title": message.title or "Consulta de Clientes",
            "description": message.text,
            "footer": message.footer,
            "buttons": [
                {
                    "type": "reply",
                    "title": option.title,
                    "displayText": option.title,
                    "id": option.option_id,
                }
                for option in message.options[:3]
            ],
        }
        self._post_json(url, payload)

    def _post_json(self, url: str, payload: dict[str, Any]) -> None:
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(url, headers=self._headers(), content=json.dumps(payload, ensure_ascii=False))
        if 200 <= response.status_code < 300:
            return
        raise RuntimeError(f"Falha ao enviar payload interativo: {response.status_code} {response.text}")

    def _menu_fallback_text(self, message: OutgoingMessage) -> str:
        lines = []
        if message.title:
            lines.append(f"*{message.title}*")
        lines.append(message.text)
        shortcuts: list[str] = []
        for index, option in enumerate(message.options, start=1):
            description = f" - {option.description}" if option.description else ""
            shortcut = option.shortcut or str(index)
            shortcuts.append(shortcut)
            lines.append(f"{shortcut}. {option.title}{description}")
        if message.options:
            choices = " ou ".join(shortcuts)
            lines.append(f"Responda com {choices}.")
        if message.footer:
            lines.append(message.footer)
        return "\n".join(lines)


def extract_incoming_message(payload: dict[str, Any]) -> IncomingMessage | None:
    event = str(payload.get("event", "")).lower()
    if event and "message" not in event:
        return None

    data = payload.get("data")
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        data = payload

    nested_messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    nested_message = nested_messages[0] if nested_messages and isinstance(nested_messages[0], dict) else {}
    message = data.get("message") if isinstance(data.get("message"), dict) else nested_message or data

    from_me_candidates = [
        data.get("key", {}).get("fromMe") if isinstance(data.get("key"), dict) else None,
        nested_message.get("fromMe") if isinstance(nested_message, dict) else None,
        data.get("fromMe"),
        payload.get("fromMe"),
    ]
    if any(candidate is True for candidate in from_me_candidates):
        return None

    sender_candidates = [
        data.get("key", {}).get("remoteJid") if isinstance(data.get("key"), dict) else None,
        data.get("key", {}).get("participant") if isinstance(data.get("key"), dict) else None,
        data.get("participant"),
        data.get("from"),
        nested_message.get("from") if isinstance(nested_message, dict) else None,
        data.get("sender"),
        payload.get("sender"),
    ]
    sender = next((candidate for candidate in sender_candidates if isinstance(candidate, str) and candidate.strip()), "")
    sender = _normalize_sender(sender)

    text_candidates = [
        message.get("listResponseMessage", {}).get("singleSelectReply", {}).get("selectedRowId")
        if isinstance(message, dict)
        else None,
        message.get("buttonsResponseMessage", {}).get("selectedButtonId") if isinstance(message, dict) else None,
        message.get("templateButtonReplyMessage", {}).get("selectedId") if isinstance(message, dict) else None,
        message.get("interactiveResponseMessage", {}).get("nativeFlowResponseMessage", {}).get("paramsJson")
        if isinstance(message, dict)
        else None,
        message.get("conversation") if isinstance(message, dict) else None,
        message.get("extendedTextMessage", {}).get("text") if isinstance(message, dict) else None,
        message.get("imageMessage", {}).get("caption") if isinstance(message, dict) else None,
        message.get("videoMessage", {}).get("caption") if isinstance(message, dict) else None,
        message.get("documentMessage", {}).get("caption") if isinstance(message, dict) else None,
        message.get("text") if isinstance(message, dict) else None,
        message.get("text", {}).get("body") if isinstance(message, dict) and isinstance(message.get("text"), dict) else None,
        nested_message.get("text", {}).get("body")
        if isinstance(nested_message, dict) and isinstance(nested_message.get("text"), dict)
        else None,
        nested_message.get("button", {}).get("text")
        if isinstance(nested_message, dict) and isinstance(nested_message.get("button"), dict)
        else None,
        nested_message.get("interactive", {}).get("button_reply", {}).get("title")
        if isinstance(nested_message, dict) and isinstance(nested_message.get("interactive"), dict)
        else None,
        nested_message.get("interactive", {}).get("list_reply", {}).get("title")
        if isinstance(nested_message, dict) and isinstance(nested_message.get("interactive"), dict)
        else None,
        data.get("text"),
        payload.get("text"),
    ]
    text = next((candidate for candidate in text_candidates if isinstance(candidate, str) and candidate.strip()), "")

    if not sender or not text:
        return None

    message_id = (
        data.get("key", {}).get("id")
        if isinstance(data.get("key"), dict)
        else None
    ) or nested_message.get("id") or data.get("id") or ""
    return IncomingMessage(sender=sender, text=text.strip(), channel="evolution", message_id=message_id, raw=payload)


def _normalize_sender(sender: str) -> str:
    normalized = str(sender or "").strip()
    for suffix in ("@s.whatsapp.net", "@g.us"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized
