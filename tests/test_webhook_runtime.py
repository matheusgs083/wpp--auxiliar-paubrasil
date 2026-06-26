from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

from bot_api.services.webhook_runtime import WebhookRuntime


class FakeAccessControl:
    def authorize(self, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            allowed=True,
            normalized_number="5583999999999",
            reason="ok",
        )


class FakeLookupFlow:
    def __init__(self) -> None:
        self.sessions: dict[str, Any] = {}

    def handle(self, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(kind="text", text="Resposta", media_url="")


class FakeEvolutionClient:
    enabled = True

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def send(self, **_kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("falha evolution")

    def send_text(self, **_kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("falha evolution")


def build_runtime(*, evolution_fail: bool = False, executor: ThreadPoolExecutor | None = None) -> WebhookRuntime:
    return WebhookRuntime(
        settings=SimpleNamespace(reports_database_url="", reports_runtime_database_url="", access_database_timeout_seconds=1),
        logger=SimpleNamespace(exception=lambda *_args, **_kwargs: None, debug=lambda *_args, **_kwargs: None, info=lambda *_args, **_kwargs: None),
        access_control=FakeAccessControl(),
        lookup_flow=FakeLookupFlow(),
        evolution_client=FakeEvolutionClient(fail=evolution_fail),
        meta_cloud_client=SimpleNamespace(enabled=False),
        webhook_executor=executor or ThreadPoolExecutor(max_workers=1),
        request_metadata=lambda _request, **extra: extra,
        record_security_event=lambda *_args, **_kwargs: None,
        record_security_event_for_path=lambda *_args, **_kwargs: None,
        should_send_denied_reply=lambda **_kwargs: True,
        denied_reply_cooldown_minutes_for=lambda _reason: 1,
        snapshot_lookup_flow_session=lambda _session: {},
        infer_evolution_usage_feature=lambda **_kwargs: ("", ""),
    )


class WebhookRuntimeMetricsTest(unittest.TestCase):
    def test_queue_and_job_update_runtime_metrics(self) -> None:
        executor = ThreadPoolExecutor(max_workers=1)
        runtime = build_runtime(executor=executor)
        incoming = SimpleNamespace(sender="5583999999999", message_id="msg-1", channel="evolution", reply_targets=())
        request = SimpleNamespace(url=SimpleNamespace(path="/webhook/evolution"))

        response = runtime.queue_incoming_webhook(request=request, incoming=incoming, requested_area="cliente")
        executor.shutdown(wait=True)

        self.assertTrue(response["queued"])
        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["received"], 1)
        self.assertEqual(snapshot["queued"], 1)
        self.assertEqual(snapshot["started"], 1)
        self.assertEqual(snapshot["completed"], 1)
        self.assertEqual(snapshot["active"], 0)
        self.assertEqual(snapshot["last_message_id"], "msg-1")
        self.assertEqual(snapshot["last_sender"], "5583999999999")

    def test_delivery_error_is_visible_in_runtime_snapshot(self) -> None:
        runtime = build_runtime(evolution_fail=True)
        incoming = SimpleNamespace(sender="5583999999999", message_id="msg-2", channel="evolution", reply_targets=())

        runtime._run_webhook_job(
            incoming=incoming,
            requested_area="cliente",
            path="/webhook/evolution",
            metadata={"message_id": "msg-2"},
        )

        snapshot = runtime.snapshot()
        self.assertEqual(snapshot["delivery_errors"], 1)
        self.assertEqual(snapshot["last_error_stage"], "delivery")
        self.assertIn("falha evolution", snapshot["last_error_message"])
        self.assertEqual(snapshot["completed"], 1)


if __name__ == "__main__":
    unittest.main()
