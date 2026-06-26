from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from typing import Any

import psycopg
from fastapi import Request


class WebhookRuntime:
    def __init__(
        self,
        *,
        settings: Any,
        logger: Any,
        access_control: Any,
        lookup_flow: Any,
        evolution_client: Any,
        meta_cloud_client: Any,
        webhook_executor: ThreadPoolExecutor,
        request_metadata: Any,
        record_security_event: Any,
        record_security_event_for_path: Any,
        should_send_denied_reply: Any,
        denied_reply_cooldown_minutes_for: Any,
        snapshot_lookup_flow_session: Any,
        infer_evolution_usage_feature: Any,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.access_control = access_control
        self.lookup_flow = lookup_flow
        self.evolution_client = evolution_client
        self.meta_cloud_client = meta_cloud_client
        self.webhook_executor = webhook_executor
        self.request_metadata = request_metadata
        self.record_security_event = record_security_event
        self.record_security_event_for_path = record_security_event_for_path
        self.should_send_denied_reply = should_send_denied_reply
        self.denied_reply_cooldown_minutes_for = denied_reply_cooldown_minutes_for
        self.snapshot_lookup_flow_session = snapshot_lookup_flow_session
        self.infer_evolution_usage_feature = infer_evolution_usage_feature
        self._metrics_lock = Lock()
        self._metrics: dict[str, Any] = {
            "received": 0,
            "queued": 0,
            "queue_errors": 0,
            "started": 0,
            "completed": 0,
            "processing_errors": 0,
            "delivery_errors": 0,
            "unexpected_errors": 0,
            "active": 0,
            "last_received_at": "",
            "last_started_at": "",
            "last_completed_at": "",
            "last_error_at": "",
            "last_error_stage": "",
            "last_error_message": "",
            "last_message_id": "",
            "last_sender": "",
            "last_duration_ms": 0,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._metrics_lock:
            payload = dict(self._metrics)
        payload["queue_depth"] = self._queue_depth()
        return payload

    def _queue_depth(self) -> int:
        queue = getattr(self.webhook_executor, "_work_queue", None)
        if queue is None or not hasattr(queue, "qsize"):
            return -1
        try:
            return int(queue.qsize())
        except Exception:
            return -1

    def _mark_received(self, *, incoming: Any) -> None:
        with self._metrics_lock:
            self._metrics["received"] += 1
            self._metrics["last_received_at"] = _utc_now_iso()
            self._metrics["last_message_id"] = str(getattr(incoming, "message_id", "") or "")
            self._metrics["last_sender"] = str(getattr(incoming, "sender", "") or "")

    def _mark_queued(self) -> None:
        with self._metrics_lock:
            self._metrics["queued"] += 1

    def _mark_queue_error(self, *, exc: Exception) -> None:
        self._mark_error(stage="queue", exc=exc)
        with self._metrics_lock:
            self._metrics["queue_errors"] += 1

    def _mark_started(self, *, incoming: Any) -> datetime:
        started_at = datetime.now(timezone.utc)
        with self._metrics_lock:
            self._metrics["started"] += 1
            self._metrics["active"] += 1
            self._metrics["last_started_at"] = _format_utc(started_at)
            self._metrics["last_message_id"] = str(getattr(incoming, "message_id", "") or "")
            self._metrics["last_sender"] = str(getattr(incoming, "sender", "") or "")
        return started_at

    def _mark_completed(self, *, started_at: datetime) -> None:
        finished_at = datetime.now(timezone.utc)
        elapsed_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        with self._metrics_lock:
            self._metrics["completed"] += 1
            self._metrics["active"] = max(0, int(self._metrics["active"]) - 1)
            self._metrics["last_completed_at"] = _format_utc(finished_at)
            self._metrics["last_duration_ms"] = elapsed_ms

    def _mark_error(self, *, stage: str, exc: Exception) -> None:
        with self._metrics_lock:
            self._metrics["last_error_at"] = _utc_now_iso()
            self._metrics["last_error_stage"] = stage
            self._metrics["last_error_message"] = str(exc)[:500]

    def _run_webhook_job(
        self,
        *,
        incoming: Any,
        requested_area: str,
        path: str,
        metadata: dict[str, Any],
    ) -> None:
        started_at = self._mark_started(incoming=incoming)
        try:
            self.process_webhook_message(
                incoming=incoming,
                requested_area=requested_area,
                path=path,
                metadata=metadata,
            )
        except Exception as exc:
            self._mark_error(stage="unexpected", exc=exc)
            with self._metrics_lock:
                self._metrics["unexpected_errors"] += 1
            self.logger.exception("Falha inesperada no job do webhook: %s", exc)
        finally:
            self._mark_completed(started_at=started_at)

    def process_webhook_message(
        self,
        *,
        incoming: Any,
        requested_area: str,
        path: str,
        metadata: dict[str, Any],
    ) -> None:
        decision = self.access_control.authorize(phone_number=incoming.sender, area=requested_area)
        if not decision.allowed:
            self.record_security_event_for_path(
                path=path,
                metadata=metadata,
                channel="webhook",
                event_type="rbac_access",
                decision="denied",
                phone_number=decision.normalized_number or incoming.sender,
                area=requested_area,
                reason=decision.reason,
            )
            blocked_text = (
                "Seu numero ainda nao tem acesso a essa consulta.\n"
                "Se precisar, fale com o responsavel para liberar o seu acesso."
            )
            blocked_reply_sent = self.should_send_denied_reply(
                number=decision.normalized_number or incoming.sender,
                reason=decision.reason,
            )
            self.record_security_event_for_path(
                path=path,
                metadata=metadata,
                channel="webhook",
                event_type="denied_reply",
                decision="sent" if blocked_reply_sent else "suppressed",
                phone_number=decision.normalized_number or incoming.sender,
                area=requested_area,
                reason=decision.reason,
            )
            if blocked_reply_sent:
                self.send_text_reply(incoming=incoming, text=blocked_text)
                self.logger.info(
                    "Resposta de bloqueio enviada para %s (%s); proxima resposta em %s minuto(s).",
                    decision.normalized_number or incoming.sender,
                    decision.reason,
                    self.denied_reply_cooldown_minutes_for(decision.reason),
                )
            else:
                self.logger.info(
                    "Resposta de bloqueio suprimida para %s (%s).",
                    decision.normalized_number or incoming.sender,
                    decision.reason,
                )
            return

        session_before = self.snapshot_lookup_flow_session(self.lookup_flow.sessions.get(incoming.sender))
        try:
            outgoing = self.lookup_flow.handle(incoming=incoming, decision=decision)
        except Exception as exc:
            self._mark_error(stage="processing", exc=exc)
            with self._metrics_lock:
                self._metrics["processing_errors"] += 1
            self.record_security_event_for_path(
                path=path,
                metadata=metadata,
                channel="webhook",
                event_type="processing",
                decision="error",
                phone_number=decision.normalized_number or incoming.sender,
                area=requested_area,
                reason="processing_error",
            )
            self.logger.exception("Falha no processamento da mensagem: %s", exc)
            error_text = "Tive um problema para atender sua mensagem agora.\nTente novamente em instantes."
            self.send_text_reply(incoming=incoming, text=error_text)
            return

        session_after = self.snapshot_lookup_flow_session(self.lookup_flow.sessions.get(incoming.sender))
        self.record_security_event_for_path(
            path=path,
            metadata=metadata,
            channel="webhook",
            event_type="processing",
            decision="allowed",
            phone_number=decision.normalized_number or incoming.sender,
            area=requested_area,
            reason=outgoing.kind,
        )
        feature_code, feature_reason = self.infer_evolution_usage_feature(
            incoming_text=getattr(incoming, "text", ""),
            requested_area=requested_area,
            session_before=session_before,
            session_after=session_after,
        )
        if feature_code:
            self.record_security_event_for_path(
                path=path,
                metadata=metadata,
                channel="webhook",
                event_type="feature_usage",
                decision="viewed",
                phone_number=decision.normalized_number or incoming.sender,
                area=feature_code,
                reason=feature_reason or outgoing.kind,
            )
        try:
            self.send_outgoing_reply(incoming=incoming, outgoing=outgoing)
        except Exception as exc:
            self._mark_error(stage="delivery", exc=exc)
            with self._metrics_lock:
                self._metrics["delivery_errors"] += 1
            self.record_security_event_for_path(
                path=path,
                metadata=metadata,
                channel="webhook",
                event_type="delivery",
                decision="error",
                phone_number=decision.normalized_number or incoming.sender,
                area=requested_area,
                reason="delivery_error",
            )
            self.logger.exception("Falha ao enviar resposta pela Evolution/Meta: %s", exc)

    def send_text_reply(self, *, incoming: Any, text: str) -> None:
        channel = getattr(incoming, "channel", "evolution")
        if channel == "meta_cloud":
            if self.meta_cloud_client.enabled:
                self.meta_cloud_client.send_text(number=incoming.sender, text=text)
            return
        if self.evolution_client.enabled:
            self.evolution_client.send_text(
                number=incoming.sender,
                text=text,
                reply_targets=self.evolution_reply_targets(incoming),
            )

    def send_outgoing_reply(self, *, incoming: Any, outgoing: Any) -> None:
        channel = getattr(incoming, "channel", "evolution")
        if channel == "meta_cloud":
            if self.meta_cloud_client.enabled:
                meta_text = outgoing.text
                if getattr(outgoing, "media_url", ""):
                    caption = str(getattr(outgoing, "media_caption", "") or "QR Code").strip()
                    meta_text = f"{meta_text}\n\n{caption}: {outgoing.media_url}".strip()
                self.meta_cloud_client.send_text(number=incoming.sender, text=meta_text)
            return
        if self.evolution_client.enabled:
            self.evolution_client.send(
                number=incoming.sender,
                message=outgoing,
                reply_targets=self.evolution_reply_targets(incoming),
            )

    def evolution_reply_targets(self, incoming: Any) -> tuple[str, ...]:
        targets: list[str] = []
        seen: set[str] = set()
        for target in (*self.lookup_evolution_lid_targets(incoming), *getattr(incoming, "reply_targets", ())):
            value = str(target or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            targets.append(value)
        return tuple(targets)

    def lookup_evolution_lid_targets(self, incoming: Any) -> tuple[str, ...]:
        message_id = str(getattr(incoming, "message_id", "") or "").strip()
        if not message_id or message_id.startswith(("admin-broadcast:", "daily-route:")):
            return ()
        database_url = self.settings.reports_database_url or self.settings.reports_runtime_database_url
        if not database_url:
            return ()
        try:
            with psycopg.connect(database_url, connect_timeout=int(self.settings.access_database_timeout_seconds)) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            key->>'remoteJid' AS remote_jid,
                            key->>'remoteJidAlt' AS remote_jid_alt,
                            key->>'participant' AS participant,
                            key->>'participantAlt' AS participant_alt
                        FROM public."Message"
                        WHERE key->>'id' = %s
                          AND COALESCE((key->>'fromMe')::boolean, false) = false
                        ORDER BY "messageTimestamp" DESC
                        LIMIT 5
                        """,
                        (message_id,),
                    )
                    rows = cur.fetchall()
        except Exception as exc:
            self.logger.debug("Nao foi possivel resolver LID da Evolution para resposta: %s", exc)
            return ()

        lids: list[str] = []
        phones: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for value in row:
                target = str(value or "").strip()
                if not target or target in seen:
                    continue
                seen.add(target)
                if target.endswith("@lid"):
                    lids.append(target)
                elif target.endswith("@s.whatsapp.net"):
                    phones.append(target)
        return tuple([*lids, *phones])

    def queue_incoming_webhook(
        self,
        *,
        request: Request,
        incoming: Any,
        requested_area: str,
        event_type_prefix: str = "webhook",
    ) -> dict[str, Any]:
        self._mark_received(incoming=incoming)
        try:
            self.webhook_executor.submit(
                self._run_webhook_job,
                incoming=incoming,
                requested_area=requested_area,
                path=request.url.path,
                metadata=self.request_metadata(request, message_id=incoming.message_id),
            )
        except Exception as exc:
            self._mark_queue_error(exc=exc)
            self.record_security_event(
                request,
                channel=event_type_prefix,
                event_type="queue",
                decision="error",
                phone_number=incoming.sender,
                area=requested_area,
                reason="queue_submit_failed",
            )
            self.logger.exception("Falha ao enfileirar processamento do webhook: %s", exc)
            return {
                "received": True,
                "handled": False,
                "intent": "queue_error",
                "message_id": incoming.message_id,
            }
        self._mark_queued()
        self.record_security_event(
            request,
            channel=event_type_prefix,
            event_type="queue",
            decision="accepted",
            phone_number=incoming.sender,
            area=requested_area,
            reason="queued",
        )
        return {
            "received": True,
            "handled": True,
            "intent": "queued",
            "queued": True,
            "message_id": incoming.message_id,
        }


def _utc_now_iso() -> str:
    return _format_utc(datetime.now(timezone.utc))


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
