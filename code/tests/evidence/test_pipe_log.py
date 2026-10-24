"""Family pipe_log: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class PipeLogFixture(unittest.TestCase):
    """pipe_log fixture: four header columns, subject_ref as a lookup user_id."""

    def test_fixture(self) -> None:
        fp = parse_fixture("pipe_log.log")
        self.assertEqual((fp.family, fp.status), ("pipe_log", "OK"))
        rows = by_ref(fp)
        self.assertEqual(sorted(rows), ["L2", "L3"])
        obs = rows["L3"][0]
        self.assertEqual(obs.record_time, "2026-05-04T07:00:02Z")
        self.assertEqual((obs.system_id, obs.resource_id),
                         ("security_service", "audit_record_5005"))
        self.assertEqual(obs.trace_id, "tr-4000001")
        self.assertEqual(obs.event, "audit_record_read_completed")
        self.assertEqual(obs.attrs["integrity_check"], "passed")
        self.assertEqual(id_set(obs.lookup_identifiers), {("user_id", "user_9001", "subject_ref")})
        self.assertEqual(obs.record_identifiers, frozenset())


class PipeLogReal(unittest.TestCase):
    """Every real pipe_log file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "pipe_log")


if __name__ == "__main__":
    unittest.main()
