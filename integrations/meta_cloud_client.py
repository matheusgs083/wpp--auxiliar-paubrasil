from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from bot_api.models import IncomingMessage


@dataclass(frozen=True)
class MetaCloudConfig:
    enabled: bool
    api_version: str
    phone_number_id: str
    access_token: str
    verify_token: str


class MetaCloudClient:
    def __init__(self, config: MetaCloudConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(
            self.config.enabled
            and self.config.api_version
            and self.config.phone_number_id
            and self.config.access_token
        )

    def send_text(self, number: str, text: str) -> None:
        if not self.enabled:
            raise RuntimeError("Meta Cloud API nao configurada para envio.")
        url = (
            f"https://graph.facebook.com/{self.config.api_version}/"
            f"{self.config.phone_number_id}/messages"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.access_token}",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": number,
            "type": "text",
            "text": {"body": text},
        }
        with httpx.Client(timeout=20) as client:
            response = client.post(url, headers=headers, content=json.dumps(payload, ensure_ascii=False))
        if 200 <= response.status_code < 300:
            return
        raise RuntimeError(f"Falha ao enviar mensagem pela Meta Cloud API: {response.status_code} {response.text}")


def verify_webhook_token(
    *,
    mode: str,
    verify_token: str,
    challenge: str,
    config: MetaCloudConfig,
    shared_token: str,
) -> str | None:
    if mode != "subscribe":
        return None
    valid_tokens = tuple(token for token in (config.verify_token, shared_token) if token)
    if any(secrets.compare_digest(verify_token, token) for token in valid_tokens):
        return challenge
    return None


def extract_incoming_message(payload: dict[str, Any]) -> IncomingMessage | None:
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return None

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            messages = value.get("messages")
            if not isinstance(messages, list):
                continue
            contacts = value.get("contacts") if isinstance(value.get("contacts"), list) else []
            wa_id = ""
            if contacts and isinstance(contacts[0], dict):
                wa_id = str(contacts[0].get("wa_id") or "").strip()
            for message in messages:
                if not isinstance(message, dict):
                    continue
                sender = str(message.get("from") or wa_id or "").strip()
                text_candidates = [
                    message.get("text", {}).get("body") if isinstance(message.get("text"), dict) else None,
                    message.get("button", {}).get("text") if isinstance(message.get("button"), dict) else None,
                    message.get("interactive", {}).get("button_reply", {}).get("title")
                    if isinstance(message.get("interactive"), dict)
                    else None,
                    message.get("interactive", {}).get("list_reply", {}).get("title")
                    if isinstance(message.get("interactive"), dict)
                    else None,
                    message.get("image", {}).get("caption") if isinstance(message.get("image"), dict) else None,
                    message.get("video", {}).get("caption") if isinstance(message.get("video"), dict) else None,
                    message.get("document", {}).get("caption") if isinstance(message.get("document"), dict) else None,
                ]
                text = next((item for item in text_candidates if isinstance(item, str) and item.strip()), "")
                if sender and text:
                    return IncomingMessage(
                        sender=sender,
                        text=text.strip(),
                        channel="meta_cloud",
                        message_id=str(message.get("id") or ""),
                        raw=payload,
                    )
    return None
