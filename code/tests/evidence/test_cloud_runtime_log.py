"""Family cloud_runtime_log: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class CloudRuntimeLogFixture(unittest.TestCase):
    """cloud_runtime_log fixture: escaped inner pairs are decoded."""

    def test_fixture(self) -> None:
        fp = parse_fixture("cloud_runtime_log.log")
        self.assertEqual((fp.family, fp.status), ("cloud_runtime_log", "OK"))
        rows = by_ref(fp)
        self.assertEqual(sorted(rows), ["L2"])
        obs = rows["L2"][0]
        self.assertEqual(obs.record_time, "2026-05-05T06:00:01Z")
        self.assertEqual((obs.system_id, obs.resource_id),
                         ("analytics_platform", "analytics_6006"))
        self.assertEqual(obs.trace_id, "tr-5000001")
        self.assertEqual(obs.event, "analytics_profile_read")
        self.assertEqual(obs.attrs["requestId"], "tr-5000001")
        self.assertEqual(obs.attrs["direct_identifiers"], "1")
        self.assertNotIn("message", obs.attrs)
        self.assertEqual(id_set(obs.record_identifiers), {
            ("email", "ada.lovelace@example.test", "email"),
            ("phone", "+442079460001", "phone"),
        })


class CloudRuntimeLogReal(unittest.TestCase):
    """Every real cloud_runtime_log file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "cloud_runtime_log")


if __name__ == "__main__":
    unittest.main()
