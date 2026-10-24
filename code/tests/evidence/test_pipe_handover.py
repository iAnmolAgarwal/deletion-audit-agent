"""Family pipe_handover: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class PipeHandoverFixture(unittest.TestCase):
    """Rows are the '- ' lines; prose lines are not records."""

    def test_fixture(self) -> None:
        fp = parse_fixture("pipe_handover.txt")
        self.assertEqual((fp.family, fp.status), ("pipe_handover", "OK"))
        rows = by_ref(fp)
        self.assertEqual(list(rows), ["L4", "L5"])
        obs = rows["L5"][0]
        self.assertEqual(obs.record_time, "2026-05-11T12:00:01Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("backup_service", "backup_7007"))
        self.assertEqual(obs.event, "BACKUP_ARCHIVE")
        self.assertEqual(obs.attrs["result"], "BLOCKED")
        self.assertEqual(id_set(obs.record_identifiers),
                         {("user_id", "user_9001", "subject_reference")})


class PipeHandoverReal(unittest.TestCase):
    """Every real pipe_handover file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "pipe_handover")


if __name__ == "__main__":
    unittest.main()
