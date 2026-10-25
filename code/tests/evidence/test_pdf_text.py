"""Family pdf_text: fixture expectations and every real file."""
from __future__ import annotations

import unittest
from typing import Any

from ._support import DATASET, assert_real_family, id_set, parse_fixture, real_index


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

    def test_no_page_mixes_several_resources_and_several_people(self) -> None:
        """T68: a page gives its identifiers to every resource it names, so no real page may
        name more than one resource together with more than one person."""
        from deletion_audit.inputs import load_audit_log, load_identities
        owner: dict[tuple[str, str], set[str]] = {}
        for row in load_identities(DATASET):
            owner.setdefault(("user_id", row.user_id), set()).add(row.user_id)
            for ident in (row.email, row.phone):
                if ident is not None:
                    owner.setdefault((ident.kind, ident.value), set()).add(row.user_id)
        for audit_row in load_audit_log(DATASET):
            for ident in (audit_row.old_identifier, audit_row.new_identifier):
                if ident is not None:
                    owner.setdefault((ident.kind, ident.value), set()).add(audit_row.user_id)
        pages: dict[tuple[str, str], list[Any]] = {}
        for obs in real_index().observations():
            if obs.locator.kind == "pdf_page":
                pages.setdefault((obs.file_id, obs.locator.ref), []).append(obs)
        self.assertTrue(pages)
        for key, observations in pages.items():
            resources = {o.resource_id for o in observations if o.resource_id}
            people = {u for o in observations for i in o.record_identifiers
                      for u in owner.get((i.kind, i.value), ())}
            self.assertFalse(len(resources) > 1 and len(people) > 1, (key, len(resources), len(people)))


if __name__ == "__main__":
    unittest.main()
