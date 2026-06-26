from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.integrations.evolution_client import (
    EvolutionClient,
    EvolutionConfig,
    _media_payload_variants,
    _recipient_candidates,
    _split_data_url,
    _text_payload_variants,
)


class EvolutionClientTests(unittest.TestCase):
    def test_status_reports_disabled_client_without_network_call(self) -> None:
        client = EvolutionClient(
            EvolutionConfig(
                base_url="",
                api_key="",
                instance="",
                send_path="/message/sendText/{instance}",
                list_path="/message/sendList/{instance}",
                buttons_path="/message/sendButtons/{instance}",
                media_path="/message/sendMedia/{instance}",
                timeout_seconds=1,
            )
        )

        status = client.status()

        self.assertFalse(status["enabled"])
        self.assertFalse(status["ready"])
        self.assertIn("EVOLUTION_BASE_URL", status["last_error"])

    def test_media_payload_variants_send_pdf_data_url_as_raw_base64_first(self) -> None:
        variants = _media_payload_variants(
            number="558391964911",
            media_url="data:application/pdf;base64,JVBERi0xLjQK",
            media_type="document",
            caption="PDF cobranca PayIP",
            filename="payip.pdf",
        )

        self.assertGreaterEqual(len(variants), 3)
        self.assertEqual(variants[0]["mediatype"], "document")
        self.assertEqual(variants[0]["mimetype"], "application/pdf")
        self.assertEqual(variants[0]["media"], "JVBERi0xLjQK")
        self.assertEqual(variants[0]["fileName"], "payip.pdf")
        self.assertEqual(variants[-1]["media"], "data:application/pdf;base64,JVBERi0xLjQK")

    def test_split_data_url_ignores_non_base64_url(self) -> None:
        self.assertEqual(_split_data_url("https://example.test/file.pdf"), ("", ""))

    def test_text_payload_variants_try_plain_text_shape_first(self) -> None:
        variants = _text_payload_variants(number="558391964911", text="Mensagem teste")

        self.assertEqual(variants[0], {"number": "558391964911", "text": "Mensagem teste"})
        self.assertEqual(variants[1], {"number": "558391964911", "textMessage": {"text": "Mensagem teste"}})

    def test_recipient_candidates_try_phone_targets_before_lid_targets(self) -> None:
        candidates = _recipient_candidates(
            number="558391964911",
            reply_targets=(
                "126014407594140@lid",
                "5583991964911@s.whatsapp.net",
                "558391964911@s.whatsapp.net",
            ),
        )

        self.assertEqual(
            candidates,
            (
                "5583991964911@s.whatsapp.net",
                "558391964911@s.whatsapp.net",
                "558391964911",
                "126014407594140@lid",
            ),
        )


if __name__ == "__main__":
    unittest.main()
