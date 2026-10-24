"""Family bracketed_log: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class BracketedLogFixture(unittest.TestCase):
    """bracketed_log fixture: header fields, matched_value as a record identifier."""

    def test_fixture(self) -> None:
        fp = parse_fixture("bracketed_log.log")
        self.assertEqual((fp.family, fp.status), ("bracketed_log", "OK"))
        rows = by_ref(fp)
        self.assertEqual(sorted(rows), ["L2", "L3"])
        obs = rows["L3"][0]
        self.assertEqual(obs.record_time, "2026-05-02T08:00:07Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("support_platform", "support_3003"))
        self.assertEqual(obs.trace_id, "tr-2000001")
        self.assertEqual(obs.event, "message_pii_scan")
        self.assertEqual(obs.attrs["level"], "WARN")
        self.assertEqual(obs.attrs["region"], "ap-south-1")
        self.assertEqual(id_set(obs.record_identifiers),
                         {("email", "ada.lovelace@example.test", "matched_value")})
        self.assertEqual(id_set(obs.lookup_identifiers),
                         {("email", "ada.lovelace@example.test", "subject_key")})
        started = rows["L2"][0]
        self.assertIsNone(started.resource_id)
        self.assertEqual(started.record_identifiers, frozenset())


class BracketedLogReal(unittest.TestCase):
    """Every real bracketed_log file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "bracketed_log")


if __name__ == "__main__":
    unittest.main()
