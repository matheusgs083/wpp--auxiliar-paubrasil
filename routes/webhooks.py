from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from bot_api.integrations.evolution_client import extract_incoming_message
from bot_api.integrations.meta_cloud_client import extract_incoming_message as extract_meta_cloud_incoming_message
from bot_api.integrations.meta_cloud_client import verify_webhook_token as verify_meta_cloud_webhook_token


def create_webhooks_router(
    *,
    settings: Any,
    meta_cloud_client: Any,
    require_webhook_token: Callable[..., None],
    require_meta_cloud_signature: Callable[..., None],
    queue_incoming_webhook: Callable[..., dict[str, Any]],
    record_security_event: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    @router.post("/webhook/evolution")
    def webhook_evolution(
        request: Request,
        payload: dict[str, Any],
        x_bot_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_webhook_token(request=request, x_bot_token=x_bot_token, payload=payload)

        incoming = extract_incoming_message(payload)
        if incoming is None:
            record_security_event(
                request,
                channel="webhook",
                event_type="incoming_event",
                decision="ignored",
                reason="non_processable",
            )
            return {"received": True, "handled": False, "reason": "evento nao processavel"}

        requested_area = "cliente"
        return queue_incoming_webhook(
            request=request,
            incoming=incoming,
            requested_area=requested_area,
            event_type_prefix="webhook",
        )

    @router.get("/webhook/meta", response_class=PlainTextResponse)
    def webhook_meta_verify(
        request: Request,
        hub_mode: str = Query(default="", alias="hub.mode"),
        hub_verify_token: str = Query(default="", alias="hub.verify_token"),
        hub_challenge: str = Query(default="", alias="hub.challenge"),
    ) -> str:
        challenge = verify_meta_cloud_webhook_token(
            mode=hub_mode,
            verify_token=hub_verify_token,
            challenge=hub_challenge,
            config=meta_cloud_client.config,
            shared_token=settings.verify_token.strip(),
        )
        if challenge is None:
            record_security_event(
                request,
                channel="meta_webhook",
                event_type="meta_verify",
                decision="denied",
                reason="invalid_verify_token",
            )
            raise HTTPException(status_code=403, detail="Token de verificacao invalido.")
        record_security_event(
            request,
            channel="meta_webhook",
            event_type="meta_verify",
            decision="allowed",
            reason="verify_token",
        )
        return challenge

    @router.post("/webhook/meta")
    async def webhook_meta(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if not settings.meta_cloud_enabled:
            record_security_event(
                request,
                channel="meta_webhook",
                event_type="incoming_event",
                decision="ignored",
                reason="meta_cloud_disabled",
            )
            return {"received": True, "handled": False, "reason": "meta_cloud_disabled"}

        raw_body = await request.body()
        require_meta_cloud_signature(
            request,
            raw_body=raw_body,
            x_hub_signature_256=x_hub_signature_256,
        )
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            record_security_event(
                request,
                channel="meta_webhook",
                event_type="incoming_event",
                decision="denied",
                reason="invalid_json",
            )
            raise HTTPException(status_code=400, detail="Payload JSON invalido.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload JSON invalido.")

        incoming = extract_meta_cloud_incoming_message(payload)
        if incoming is None:
            record_security_event(
                request,
                channel="meta_webhook",
                event_type="incoming_event",
                decision="ignored",
                reason="non_processable",
            )
            return {"received": True, "handled": False, "reason": "evento nao processavel"}

        requested_area = "cliente"
        return queue_incoming_webhook(
            request=request,
            incoming=incoming,
            requested_area=requested_area,
            event_type_prefix="meta_webhook",
        )

    return router
