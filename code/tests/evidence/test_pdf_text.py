"""Family pdf_text: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, id_set, parse_fixture


class PdfTextFixture(unittest.TestCase):
    """One observation per resource ID named on a page; no text layer -> NEEDS_MODEL."""

    def test_pages(self) -> None:
        fp = parse_fixture("pdf_text.pdf")
        self.assertEqual((fp.family, fp.status), ("pdf_text", "OK"))
        self.assertEqual([(o.locator.kind, o.locator.ref, o.resource_id, o.system_id)
                          for o in fp.observations],
                         [("pdf_page", "p1", "support_3003", "support_platform"),
                          ("pdf_page", "p2", "audit_record_5005", "security_service"),
                          ("pdf_page", "p2", "support_3003", "support_platform")])
        first = fp.observations[0]
        self.assertIsNone(first.record_time)
        self.assertIn("Reference CS-1 / support_3003", first.text or "")
        self.assertEqual(id_set(first.record_identifiers), {
            ("email", "ada.lovelace@example.test", "pdf_text"),
            ("phone", "+442079460001", "pdf_text"),
        })
        self.assertEqual(id_set(fp.observations[1].record_identifiers),
                         {("user_id", "user_9001", "pdf_text")})

    def test_no_text_layer_needs_model(self) -> None:
        fp = parse_fixture("pdf_no_text.pdf")
        self.assertEqual((fp.family, fp.status), ("pdf_text", "NEEDS_MODEL"))
        self.assertEqual(fp.observations, ())


class PdfTextReal(unittest.TestCase):
    """Every real PDF has a text layer and parses OK."""

    def test_real_files(self) -> None:
        assert_real_family(self, "pdf_text")


if __name__ == "__main__":
    unittest.main()
