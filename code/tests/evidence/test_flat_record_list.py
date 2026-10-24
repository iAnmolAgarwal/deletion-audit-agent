"""Family flat_record_list: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class FlatRecordListFixture(unittest.TestCase):
    """Flat check results; no scope; 'no direct identifier' is not an identifier."""

    def test_fixture(self) -> None:
        fp = parse_fixture("flat_record_list.json")
        self.assertEqual((fp.family, fp.status), ("flat_record_list", "OK"))
        self.assertEqual(fp.scopes, ())
        rows = by_ref(fp)
        self.assertEqual(list(rows), ["$.records[0]", "$.records[1]"])
        first = rows["$.records[0]"][0]
        self.assertEqual(first.record_time, "2026-05-09T12:00:00Z")
        self.assertEqual((first.system_id, first.resource_id), ("account_service", "account_1001"))
        self.assertEqual(first.event, "USER_PROFILE")
        self.assertEqual(first.attrs["result"], "NOT_FOUND")
        self.assertEqual(id_set(first.record_identifiers),
                         {("email", "ada.lovelace@example.test", "subject_reference")})
        self.assertEqual({i.raw for i in first.record_identifiers}, {"ADA.LOVELACE@EXAMPLE.TEST"})
        second = rows["$.records[1]"][0]
        self.assertEqual(second.record_identifiers, frozenset())
        self.assertEqual(second.attrs["subject_reference"], "no direct identifier")


class FlatRecordListReal(unittest.TestCase):
    """Every real flat_record_list file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "flat_record_list")


if __name__ == "__main__":
    unittest.main()
