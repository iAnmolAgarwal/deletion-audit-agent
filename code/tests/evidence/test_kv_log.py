"""Family kv_log: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class KvLogFixture(unittest.TestCase):
    """kv_log fixture: noise lines dropped, trace lookups joined, record_lookup rows typed."""

    def setUp(self) -> None:
        self.fp = parse_fixture("kv_log.log")
        self.rows = by_ref(self.fp)

    def test_family_and_status(self) -> None:
        self.assertEqual((self.fp.family, self.fp.status), ("kv_log", "OK"))

    def test_noise_lines_yield_no_observation(self) -> None:
        self.assertEqual(sorted(self.rows), ["L2", "L4", "L5"])

    def test_completed_line(self) -> None:
        obs = self.rows["L4"][0]
        self.assertEqual(obs.record_time, "2026-05-01T10:00:03Z")
        self.assertEqual(obs.captured_at, "2026-06-01T00:00:00Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("account_service", "account_1001"))
        self.assertEqual(obs.trace_id, "tr-1000001")
        self.assertEqual(obs.event, "profile_lookup_completed")
        self.assertEqual(obs.record_identifiers, frozenset())
        self.assertEqual(id_set(obs.lookup_identifiers),
                         {("email", "ada.lovelace@example.test", "lookup_key")})
        self.assertEqual({i.raw for i in obs.lookup_identifiers}, {"Ada.Lovelace@Example.Test"})
        self.assertEqual(obs.attrs["region"], "eu-west-1")
        self.assertEqual(obs.attrs["http_status"], "200")

    def test_record_lookup_line_uses_its_system_field(self) -> None:
        obs = self.rows["L5"][0]
        self.assertEqual((obs.system_id, obs.resource_id), ("search_service", "search_2002"))
        self.assertEqual(obs.event, "record_lookup")
        self.assertEqual(obs.attrs["level"], "INFO")
        self.assertEqual(obs.attrs["result"], "FOUND")
        self.assertEqual(id_set(obs.record_identifiers),
                         {("email", "grace.hopper@example.test", "subject_reference")})
        self.assertIsNone(obs.trace_id)


class KvLogReal(unittest.TestCase):
    """Every real kv_log file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "kv_log")


if __name__ == "__main__":
    unittest.main()
