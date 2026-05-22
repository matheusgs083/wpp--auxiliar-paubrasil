from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.integrations.evolution_client import _media_payload_variants, _split_data_url


class EvolutionClientTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
