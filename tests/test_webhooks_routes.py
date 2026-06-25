from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bot_api.routes.webhooks import create_webhooks_router


class WebhooksRoutesTest(unittest.TestCase):
    def test_evolution_non_processable_payload_is_ignored_after_token_check(self) -> None:
        token_checks: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []

        app = FastAPI()
        app.include_router(
            create_webhooks_router(
                settings=SimpleNamespace(meta_cloud_enabled=False, verify_token="shared"),
                meta_cloud_client=SimpleNamespace(config=SimpleNamespace(verify_token="meta")),
                require_webhook_token=lambda **kwargs: token_checks.append(kwargs),
                require_meta_cloud_signature=lambda *_args, **_kwargs: None,
                queue_incoming_webhook=lambda **_kwargs: {"received": True, "handled": True},
                record_security_event=lambda _request, **kwargs: events.append(kwargs),
            )
        )

        response = TestClient(app).post("/webhook/evolution", json={})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["handled"])
        self.assertEqual(len(token_checks), 1)
        self.assertEqual(events[0]["reason"], "non_processable")

    def test_meta_disabled_ignores_without_signature_check(self) -> None:
        signature_checks: list[dict[str, Any]] = []

        app = FastAPI()
        app.include_router(
            create_webhooks_router(
                settings=SimpleNamespace(meta_cloud_enabled=False, verify_token="shared"),
                meta_cloud_client=SimpleNamespace(config=SimpleNamespace(verify_token="meta")),
                require_webhook_token=lambda **_kwargs: None,
                require_meta_cloud_signature=lambda **kwargs: signature_checks.append(kwargs),
                queue_incoming_webhook=lambda **_kwargs: {"received": True, "handled": True},
                record_security_event=lambda _request, **_kwargs: None,
            )
        )

        response = TestClient(app).post("/webhook/meta", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "meta_cloud_disabled")
        self.assertEqual(signature_checks, [])


if __name__ == "__main__":
    unittest.main()
