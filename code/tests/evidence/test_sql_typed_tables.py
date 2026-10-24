"""Family sql_typed_tables: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class SqlTypedTablesFixture(unittest.TestCase):
    """Plain tables; the table name maps to the system; indexed_at is the row time."""

    def test_fixture(self) -> None:
        fp = parse_fixture("sql_typed_tables.sql")
        self.assertEqual((fp.family, fp.status), ("sql_typed_tables", "OK"))
        obs = by_ref(fp)["search_documents_primary#rowid=1"][0]
        self.assertEqual(obs.record_time, "2026-05-14T22:12:00Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("search_service", "search_2002"))
        self.assertEqual(obs.attrs["source_resource_id"], "account_1001")
        self.assertEqual(id_set(obs.record_identifiers), {
            ("name", "ada lovelace", "display_name"),
            ("email", "ada.lovelace@example.test", "email"),
        })


class SqlTypedTablesReal(unittest.TestCase):
    """Every real sql_typed_tables file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "sql_typed_tables")


if __name__ == "__main__":
    unittest.main()
