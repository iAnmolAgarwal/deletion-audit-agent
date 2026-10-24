"""Family sql_inventory: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class SqlInventoryFixture(unittest.TestCase):
    """snapshot_scope rows become scopes; a scope with zero rows is still declared."""

    def setUp(self) -> None:
        self.fp = parse_fixture("sql_inventory.sql")

    def test_scopes(self) -> None:
        self.assertEqual((self.fp.family, self.fp.status), ("sql_inventory", "OK"))
        self.assertEqual(
            [(s.locator.ref, s.systems, s.as_of, s.source) for s in self.fp.scopes],
            [("snapshot_scope#rowid=1", frozenset({"account_service"}), "2026-05-12T07:43:27Z",
              "sql_snapshot_scope"),
             ("snapshot_scope#rowid=2", frozenset({"search_service"}), "2026-05-12T07:43:27Z",
              "sql_snapshot_scope")])
        self.assertFalse([o for o in self.fp.observations if o.scope is self.fp.scopes[0]])

    def test_row(self) -> None:
        obs = by_ref(self.fp)["customer_search_documents#rowid=1"][0]
        self.assertEqual(obs.record_time, "2026-05-12T06:34:26Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("search_service", "search_2002"))
        self.assertIs(obs.scope, self.fp.scopes[1])
        self.assertEqual(obs.event, "customer_search_documents")
        self.assertEqual(obs.attrs["email_hash"], "null")
        self.assertEqual(id_set(obs.record_identifiers), {
            ("user_id", "user_9001", "customer_reference"),
            ("name", "ada lovelace", "display_name"),
            ("email", "ada.lovelace@example.test", "email"),
            ("phone", "+442079460001", "phone"),
        })


class SqlInventoryReal(unittest.TestCase):
    """Every real sql_inventory file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "sql_inventory")


if __name__ == "__main__":
    unittest.main()
