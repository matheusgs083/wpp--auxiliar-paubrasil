from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from bot_api.models import IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvolutionConfig:
    base_url: str
    api_key: str
    instance: str
    send_path: str
    list_path: str
    buttons_path: str
    media_path: str
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

    def status(self) -> dict[str, Any]:
        base_url_configured = bool(self.config.base_url)
        instance_configured = bool(self.config.instance)
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "base_url_configured": base_url_configured,
            "instance_configured": instance_configured,
            "instance": self.config.instance,
            "ready": False,
            "state": "",
            "last_error": "",
        }
        if not self.enabled:
            payload["last_error"] = "EVOLUTION_BASE_URL ou EVOLUTION_INSTANCE nao configurado."
            return payload

        instance = quote(self.config.instance, safe="")
        url = f"{self.config.base_url}/instance/connectionState/{instance}"
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.get(url, headers=self._headers())
            if not 200 <= response.status_code < 300:
                payload["last_error"] = f"{response.status_code} {response.text[:240]}"
                return payload
            data = response.json()
        except Exception as exc:
            payload["last_error"] = str(exc)
            return payload

        instance_payload = data.get("instance") if isinstance(data, dict) else {}
        state = str(instance_payload.get("state") if isinstance(instance_payload, dict) else data.get("state", "")).strip()
        payload["state"] = state
        payload["ready"] = state.lower() == "open"
        return payload

    def send(self, number: str, message: OutgoingMessage, *, reply_targets: tuple[str, ...] = ()) -> None:
        # Menus ficam sempre em texto para evitar falhas interativas na Evolution.
        if message.kind == "menu":
            self.send_text(number=number, text=self._menu_fallback_text(message), reply_targets=reply_targets)
            return
        if message.kind == "media" and message.media_url:
            if message.text.strip():
                self.send_text(number=number, text=message.text, reply_targets=reply_targets)
            self._send_media_with_fallback(
                number=number,
                media_url=message.media_url,
                media_type=message.media_type or "image",
                caption=message.media_caption,
                filename=message.media_filename,
                reply_targets=reply_targets,
                data_url_fallback_suffix="Use a mensagem enviada acima como referencia.",
            )
            for attachment in message.extra_media:
                self._send_media_with_fallback(
                    number=number,
                    media_url=attachment.media_url,
                    media_type=attachment.media_type or "document",
                    caption=attachment.media_caption,
                    filename=attachment.media_filename,
                    reply_targets=reply_targets,
                )
            return
        if message.extra_media:
            if message.text.strip():
                self.send_text(number=number, text=message.text, reply_targets=reply_targets)
            for attachment in message.extra_media:
                self._send_media_with_fallback(
                    number=number,
                    media_url=attachment.media_url,
                    media_type=attachment.media_type or "document",
                    caption=attachment.media_caption,
                    filename=attachment.media_filename,
                    reply_targets=reply_targets,
                )
            return
        self.send_text(number=number, text=message.text, reply_targets=reply_targets)

    def send_text(self, number: str, text: str, *, reply_targets: tuple[str, ...] = ()) -> None:
        if not self.enabled:
            raise RuntimeError("EVOLUTION_BASE_URL e EVOLUTION_INSTANCE sao obrigatorios para envio.")

        path = self.config.send_path.format(instance=self.config.instance)
        url = f"{self.config.base_url}{path}"
        clean_text = str(text or "").strip()
        if not clean_text:
            raise RuntimeError("Texto vazio para envio pela Evolution.")

        payload_variants = _text_payload_variants(number=number, text=clean_text, reply_targets=reply_targets)

        errors: list[str] = []
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            for payload in payload_variants:
                response = client.post(url, headers=self._headers(), json=payload)
                if 200 <= response.status_code < 300:
                    return
                errors.append(f"{response.status_code} {response.text}")

        raise RuntimeError(f"Falha ao enviar mensagem para Evolution: {' | '.join(errors)}")

    def send_list(self, number: str, message: OutgoingMessage, *, reply_targets: tuple[str, ...] = ()) -> None:
        if not self.enabled:
            raise RuntimeError("EVOLUTION_BASE_URL e EVOLUTION_INSTANCE sao obrigatorios para envio.")

        path = self.config.list_path.format(instance=self.config.instance)
        url = f"{self.config.base_url}{path}"
        payloads = []
        for recipient in _recipient_candidates(number=number, reply_targets=reply_targets):
            payloads.append(
                {
                    "number": recipient,
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
            )
        self._post_json(url, payloads)

    def send_buttons(self, number: str, message: OutgoingMessage, *, reply_targets: tuple[str, ...] = ()) -> None:
        if not self.enabled:
            raise RuntimeError("EVOLUTION_BASE_URL e EVOLUTION_INSTANCE sao obrigatorios para envio.")

        path = self.config.buttons_path.format(instance=self.config.instance)
        url = f"{self.config.base_url}{path}"
        payloads = []
        for recipient in _recipient_candidates(number=number, reply_targets=reply_targets):
            payloads.append(
                {
                    "number": recipient,
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
            )
        self._post_json(url, payloads)

    def send_media(
        self,
        *,
        number: str,
        media_url: str,
        media_type: str = "image",
        caption: str = "",
        filename: str = "",
        reply_targets: tuple[str, ...] = (),
    ) -> None:
        if not self.enabled:
            raise RuntimeError("EVOLUTION_BASE_URL e EVOLUTION_INSTANCE sao obrigatorios para envio.")

        path = self.config.media_path.format(instance=self.config.instance)
        url = f"{self.config.base_url}{path}"
        normalized_media_type = str(media_type or "image").strip().lower() or "image"
        media_filename = str(filename or "").strip() or _default_media_filename(normalized_media_type)
        payload_variants = _media_payload_variants(
            number=number,
            media_url=media_url,
            media_type=normalized_media_type,
            caption=caption,
            filename=media_filename,
            reply_targets=reply_targets,
        )

        last_error: str | None = None
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            for payload in payload_variants:
                response = client.post(url, headers=self._headers(), content=json.dumps(payload, ensure_ascii=False))
                if 200 <= response.status_code < 300:
                    return
                last_error = f"{response.status_code} {response.text}"

        raise RuntimeError(f"Falha ao enviar midia para Evolution: {last_error}")

    def _post_json(self, url: str, payloads: list[dict[str, Any]]) -> None:
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            errors: list[str] = []
            for payload in payloads:
                response = client.post(url, headers=self._headers(), content=json.dumps(payload, ensure_ascii=False))
                if 200 <= response.status_code < 300:
                    return
                errors.append(f"{response.status_code} {response.text}")
        raise RuntimeError(f"Falha ao enviar payload interativo: {' | '.join(errors)}")

    def _send_media_with_fallback(
        self,
        *,
        number: str,
        media_url: str,
        media_type: str,
        caption: str,
        filename: str,
        reply_targets: tuple[str, ...],
        data_url_fallback_suffix: str = "Tente novamente mais tarde.",
    ) -> None:
        try:
            self.send_media(
                number=number,
                media_url=media_url,
                media_type=media_type,
                caption=caption,
                filename=filename,
                reply_targets=reply_targets,
            )
        except RuntimeError as exc:
            logger.warning("Falha ao enviar midia pela Evolution: %s", exc)
            if str(media_url).startswith("data:"):
                fallback_text = f"{caption or 'Midia'} nao pode ser enviada agora. {data_url_fallback_suffix}"
            else:
                fallback_text = f"{caption or 'Midia'}: {media_url}".strip()
            self.send_text(number=number, text=fallback_text, reply_targets=reply_targets)

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
            if len(message.options) == 1:
                lines.append("Voce pode responder com o numero ou com o nome da opcao.")
            else:
                choices = " ou ".join(shortcuts)
                lines.append(f"Voce pode responder com o numero ou com o nome da opcao. Atalhos: {choices}.")
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
        data.get("key", {}).get("remoteJidAlt") if isinstance(data.get("key"), dict) else None,
        data.get("key", {}).get("remoteJid") if isinstance(data.get("key"), dict) else None,
        data.get("key", {}).get("participantAlt") if isinstance(data.get("key"), dict) else None,
        data.get("key", {}).get("participant") if isinstance(data.get("key"), dict) else None,
        data.get("remoteJidAlt"),
        data.get("remoteJid"),
        data.get("participantAlt"),
        data.get("participant"),
        data.get("from"),
        nested_message.get("from") if isinstance(nested_message, dict) else None,
        data.get("sender"),
        payload.get("sender"),
    ]
    sender = _select_sender(sender_candidates)
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
    reply_targets = _extract_reply_targets(data=data, nested_message=nested_message, payload=payload)
    return IncomingMessage(
        sender=sender,
        text=text.strip(),
        channel="evolution",
        message_id=message_id,
        reply_targets=reply_targets,
        raw=payload,
    )


def _normalize_sender(sender: str) -> str:
    normalized = str(sender or "").strip()
    for suffix in ("@s.whatsapp.net", "@g.us", "@lid"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def _select_sender(candidates: list[Any]) -> str:
    values = [str(candidate or "").strip() for candidate in candidates if str(candidate or "").strip()]
    phone_candidates = [
        value
        for value in values
        if value.endswith("@s.whatsapp.net") or (_normalize_sender(value).isdigit() and not value.endswith("@lid"))
    ]
    if phone_candidates:
        return phone_candidates[0]
    return values[0] if values else ""


def _default_media_filename(media_type: str) -> str:
    normalized = str(media_type or "").strip().lower()
    if normalized == "image":
        return "image.png"
    if normalized == "video":
        return "video.mp4"
    if normalized == "audio":
        return "audio.ogg"
    if normalized == "document":
        return "document.pdf"
    return "media.bin"


def _media_payload_variants(
    *,
    number: str,
    media_url: str,
    media_type: str,
    caption: str,
    filename: str,
    reply_targets: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    normalized_media_type = str(media_type or "image").strip().lower() or "image"
    media_value = str(media_url or "").strip()
    mimetype, raw_base64 = _split_data_url(media_value)
    mimetype = mimetype or _default_mimetype(normalized_media_type)

    variants: list[dict[str, Any]] = []
    for recipient in _recipient_candidates(number=number, reply_targets=reply_targets):
        if raw_base64:
            variants.extend(
                [
                    {
                        "number": recipient,
                        "mediatype": normalized_media_type,
                        "mimetype": mimetype,
                        "media": raw_base64,
                        "caption": caption,
                        "fileName": filename,
                    },
                    {
                        "number": recipient,
                        "mediaType": normalized_media_type,
                        "mimetype": mimetype,
                        "media": raw_base64,
                        "caption": caption,
                        "fileName": filename,
                    },
                    {
                        "number": recipient,
                        "mediaMessage": {
                            "mediatype": normalized_media_type,
                            "mimetype": mimetype,
                            "media": raw_base64,
                            "caption": caption,
                            "fileName": filename,
                        },
                    },
                ]
            )

        variants.extend(
            [
                {
                    "number": recipient,
                    "mediatype": normalized_media_type,
                    "mimetype": mimetype,
                    "media": media_value,
                    "caption": caption,
                    "fileName": filename,
                },
                {
                    "number": recipient,
                    "mediaType": normalized_media_type,
                    "mimetype": mimetype,
                    "media": media_value,
                    "caption": caption,
                    "fileName": filename,
                },
            ]
        )
    return variants


def _text_payload_variants(*, number: str, text: str, reply_targets: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for recipient in _recipient_candidates(number=number, reply_targets=reply_targets):
        variants.extend(
            [
                {"number": recipient, "text": text},
                {"number": recipient, "textMessage": {"text": text}},
            ]
        )
    return variants


def _extract_reply_targets(*, data: dict[str, Any], nested_message: dict[str, Any], payload: dict[str, Any]) -> tuple[str, ...]:
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    candidates = [
        key.get("remoteJid"),
        key.get("remoteJidAlt"),
        key.get("participant"),
        key.get("participantAlt"),
        data.get("remoteJid"),
        data.get("remoteJidAlt"),
        data.get("participant"),
        data.get("participantAlt"),
        nested_message.get("from"),
        data.get("from"),
        payload.get("sender"),
    ]
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return tuple(normalized)


def _recipient_candidates(*, number: str, reply_targets: tuple[str, ...]) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()
    for candidate in (*reply_targets, number, _normalize_sender(number)):
        value = str(candidate or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        candidates.append(value)
    return tuple(sorted(candidates, key=_recipient_candidate_priority))


def _recipient_candidate_priority(value: str) -> int:
    normalized = _normalize_sender(value)
    if str(value or "").strip().endswith("@lid"):
        return 3
    if str(value or "").strip().endswith("@s.whatsapp.net"):
        return 0
    if normalized.isdigit():
        return 1
    return 2


def _split_data_url(value: str) -> tuple[str, str]:
    if not value.startswith("data:") or "," not in value:
        return "", ""
    header, payload = value.split(",", 1)
    if ";base64" not in header.lower():
        return "", ""
    mimetype = header[5:].split(";", 1)[0].strip()
    return mimetype, payload.strip()


def _default_mimetype(media_type: str) -> str:
    normalized = str(media_type or "").strip().lower()
    if normalized == "image":
        return "image/png"
    if normalized == "video":
        return "video/mp4"
    if normalized == "audio":
        return "audio/ogg"
    if normalized == "document":
        return "application/pdf"
    return "application/octet-stream"
