"""Family service_resource_export: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture

LOOKUPS = "$.service_exports.account_service.profile_lookups"
QUERIES = "$.service_exports.search_service.index_queries"


class ServiceResourceExportFixture(unittest.TestCase):
    """Rows per service/collection; nested objects flattened; query kept as lookup."""

    def setUp(self) -> None:
        self.fp = parse_fixture("service_resource_export.json")
        self.rows = by_ref(self.fp)

    def test_family_and_rows(self) -> None:
        self.assertEqual((self.fp.family, self.fp.status), ("service_resource_export", "OK"))
        self.assertEqual(list(self.rows), [f"{LOOKUPS}[0]", f"{LOOKUPS}[1]", f"{QUERIES}[0]"])
        self.assertEqual(self.fp.scopes, ())

    def test_profile_row(self) -> None:
        obs = self.rows[f"{LOOKUPS}[0]"][0]
        self.assertEqual(obs.record_time, "2026-05-07T11:00:01Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("account_service", "account_1001"))
        self.assertEqual(obs.event, "profile_lookups")
        self.assertEqual(id_set(obs.record_identifiers),
                         {("email", "ada.lovelace@example.test", "profile.email")})
        self.assertEqual(obs.attrs["profile.full_name"], "null")
        self.assertEqual(obs.attrs["status_code"], "200")

    def test_null_profile_row(self) -> None:
        obs = self.rows[f"{LOOKUPS}[1]"][0]
        self.assertEqual(obs.attrs["profile"], "null")
        self.assertEqual(obs.record_identifiers, frozenset())

    def test_index_query_row(self) -> None:
        obs = self.rows[f"{QUERIES}[0]"][0]
        self.assertEqual((obs.system_id, obs.resource_id), ("search_service", "search_2002"))
        self.assertEqual(id_set(obs.record_identifiers),
                         {("email", "ada.lovelace@example.test", "hits.documents[0].email")})
        self.assertEqual(id_set(obs.lookup_identifiers),
                         {("email", "ada.lovelace@example.test", "query")})
        self.assertEqual(obs.attrs["hits.total"], "1")


class ServiceResourceExportReal(unittest.TestCase):
    """Every real service_resource_export file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "service_resource_export")


if __name__ == "__main__":
    unittest.main()
