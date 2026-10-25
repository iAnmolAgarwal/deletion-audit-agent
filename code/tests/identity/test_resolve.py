"""Identity resolution: current and historical emails, the complete identifier set (T59), unresolved (T63)."""

from __future__ import annotations

import unittest

from deletion_audit.evidence.interpret import make_identifier
from deletion_audit.identity import build_people, email_hash, resolve, resolve_with
from deletion_audit.inputs.model import AuditLogRow, IdentityRow

from ..engine_fixtures import req


def _people() -> tuple[list[IdentityRow], list[AuditLogRow]]:
    rows = [
        IdentityRow(
            "user_9001",
            "Ada Example",
            make_identifier("email", "ada.new@example.test", "email"),
            make_identifier("phone", "+1 555 0101", "phone"),
            email_hash("ada.new@example.test"),
            "2026-01-01T00:00:00Z",
        ),
        IdentityRow(
            "user_9002",
            "Bo Example",
            make_identifier("email", "bo@example.test", "email"),
            make_identifier("phone", "+1 555 0102", "phone"),
            email_hash("bo@example.test"),
            "2026-01-01T00:00:00Z",
        ),
    ]
    audit = [
        AuditLogRow(
            "audit_9",
            "user_9001",
            "2026-02-01T00:00:00Z",
            "email",
            "Ada.Old@Example.test",
            "ada.new@example.test",
            make_identifier("email", "Ada.Old@Example.test", "old_value"),
            make_identifier("email", "ada.new@example.test", "new_value"),
        ),
        AuditLogRow(
            "audit_10",
            "user_9001",
            "2026-02-02T00:00:00Z",
            "phone",
            "+1 555 0199",
            "+1 555 0101",
            make_identifier("phone", "+1 555 0199", "old_value"),
            make_identifier("phone", "+1 555 0101", "new_value"),
        ),
    ]
    return rows, audit


class Resolve(unittest.TestCase):
    """R1, T59, T63."""

    def test_identity_case_insensitive_current_and_historical(self) -> None:
        rows, audit = _people()
        cur = resolve(req("c1", "ADA.NEW@example.TEST"), rows, audit)
        self.assertEqual((cur.status, cur.person), ("CURRENT", "user_9001"))
        old = resolve(req("c2", "ada.old@example.test"), rows, audit)
        self.assertEqual((old.status, old.person), ("HISTORICAL", "user_9001"))
        self.assertEqual(old.via_audit_ids, ("audit_9",))

    def test_identifier_set_is_complete(self) -> None:
        rows, audit = _people()
        ids = build_people(rows, audit).people["user_9001"]
        self.assertEqual(ids.emails, {"ada.new@example.test", "ada.old@example.test"})
        self.assertEqual(ids.phones, {"+15550101", "+15550199"})
        self.assertIn(email_hash("ada.old@example.test"), ids.email_hashes)  # hash of an old email (T59)
        self.assertTrue(ids.matches(make_identifier("email_hash", email_hash("ada.old@example.test"), "email_hash")))

    def test_lookalike_does_not_match(self) -> None:
        rows, audit = _people()
        ids = build_people(rows, audit).people["user_9001"]
        self.assertFalse(ids.matches(make_identifier("email", "ada.new.jr@example.test", "email")))
        self.assertFalse(ids.matches(make_identifier("name", "Ada Example", "name")))  # names never link

    def test_email_hash_formula_lowercases_and_strips(self) -> None:
        """T59: sha256 of the stripped, lower-cased email. The expected digest is computed here from the
        literal lower-case bytes, so a formula that skips lower-casing gives a different value."""
        import hashlib

        want = hashlib.sha256(b"ada.new@example.test").hexdigest()
        for raw in ("ada.new@example.test", "ADA.New@Example.TEST", "  Ada.New@example.test \n"):
            with self.subTest(raw=raw):
                self.assertEqual(email_hash(raw), want)

    def test_email_hash_formula_matches_the_identities_file(self) -> None:
        """T59's basis, on the real inputs (not gold): the file's ``email_hash`` is this formula of
        its own ``email`` on every row that has both."""
        from pathlib import Path

        from deletion_audit.inputs import load_identities

        rows = load_identities(Path(__file__).resolve().parents[3] / "dataset")
        pairs = [(r.email.raw, r.email_hash) for r in rows if r.email is not None and r.email_hash]
        self.assertGreater(len(pairs), 100)
        self.assertEqual([h for raw, h in pairs if email_hash(raw) != h], [])

    def test_unresolved_identity_keeps_only_request_email_and_hash(self) -> None:
        rows, audit = _people()
        r = resolve_with(req("c3", "nobody@example.test"), build_people(rows, audit))
        self.assertEqual(r.status, "UNRESOLVED")
        self.assertIsNone(r.person)
        self.assertEqual(r.identifiers.emails, {"nobody@example.test"})
        self.assertEqual(r.identifiers.email_hashes, {email_hash("nobody@example.test")})


if __name__ == "__main__":
    unittest.main()
