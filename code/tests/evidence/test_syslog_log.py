"""Family syslog_log: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class SyslogLogFixture(unittest.TestCase):
    """syslog_log fixture: APP is the service, PROCID the trace."""

    def test_fixture(self) -> None:
        fp = parse_fixture("syslog_log.log")
        self.assertEqual((fp.family, fp.status), ("syslog_log", "OK"))
        rows = by_ref(fp)
        self.assertEqual(sorted(rows), ["L2", "L3"])
        obs = rows["L3"][0]
        self.assertEqual(obs.record_time, "2026-05-03T09:00:02Z")
        self.assertEqual((obs.system_id, obs.resource_id),
                         ("integration_service", "data_flow_4004"))
        self.assertEqual(obs.trace_id, "tr-3000001")
        self.assertEqual(obs.attrs["host"], "node-2")
        self.assertEqual(obs.attrs["pri"], "12")
        self.assertEqual(obs.attrs["enabled"], "true")
        self.assertEqual(id_set(obs.lookup_identifiers),
                         {("email", "grace.hopper@example.test", "subject_key")})


class SyslogLogReal(unittest.TestCase):
    """Every real syslog_log file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "syslog_log")


if __name__ == "__main__":
    unittest.main()
