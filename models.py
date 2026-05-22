from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IncomingMessage:
    sender: str
    text: str
    channel: str = "evolution"
    message_id: str = ""
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class InteractiveOption:
    option_id: str
    title: str
    description: str = ""
    shortcut: str = ""


@dataclass(frozen=True)
class MediaAttachment:
    media_url: str
    media_type: str = "document"
    media_caption: str = ""
    media_filename: str = ""


@dataclass(frozen=True)
class OutgoingMessage:
    text: str
    kind: str = "text"
    title: str = ""
    footer: str = ""
    button_text: str = "Escolher"
    options: tuple[InteractiveOption, ...] = ()
    media_url: str = ""
    media_type: str = ""
    media_caption: str = ""
    media_filename: str = ""
    extra_media: tuple[MediaAttachment, ...] = ()
