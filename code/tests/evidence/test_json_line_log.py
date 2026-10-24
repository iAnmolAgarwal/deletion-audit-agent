"""Family json_line_log: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class JsonLineLogFixture(unittest.TestCase):
    """json_line_log fixture: JSON object per line."""

    def test_fixture(self) -> None:
        fp = parse_fixture("json_line_log.log")
        self.assertEqual((fp.family, fp.status), ("json_line_log", "OK"))
        rows = by_ref(fp)
        self.assertEqual(sorted(rows), ["L2", "L3"])
        obs = rows["L3"][0]
        self.assertEqual(obs.record_time, "2026-05-06T05:00:02Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("backup_service", "backup_7007"))
        self.assertEqual(obs.trace_id, "tr-6000001")
        self.assertEqual(obs.attrs["restore_allowed"], "false")
        self.assertEqual(obs.attrs["severity"], "INFO")
        self.assertEqual(id_set(obs.lookup_identifiers),
                         {("email", "grace.hopper@example.test", "subject_key")})


class JsonLineLogReal(unittest.TestCase):
    """Every real json_line_log file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "json_line_log")


if __name__ == "__main__":
    unittest.main()
