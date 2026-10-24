"""Family sql_replica_topology: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class SqlReplicaTopologyFixture(unittest.TestCase):
    """record_json decoded under record_json.*; the table name is the event."""

    def test_fixture(self) -> None:
        fp = parse_fixture("sql_replica_topology.sql")
        self.assertEqual((fp.family, fp.status), ("sql_replica_topology", "OK"))
        self.assertEqual(fp.scopes, ())
        rows = by_ref(fp)
        self.assertEqual(list(rows), ["customer_data_primary#rowid=1",
                                      "customer_data_read_replica#rowid=1"])
        primary = rows["customer_data_primary#rowid=1"][0]
        self.assertEqual(primary.record_time, "2026-05-13T10:00:00Z")
        self.assertEqual((primary.system_id, primary.resource_id),
                         ("analytics_platform", "analytics_6006"))
        self.assertEqual(primary.event, "customer_data_primary")
        self.assertEqual(primary.attrs["collection_name"], "customer_analytics_reports")
        self.assertEqual(primary.attrs["record_json.metrics.sessions_30d"], "3")
        self.assertEqual(id_set(primary.record_identifiers), {
            ("user_id", "user_9001", "record_json.user_id"),
            ("email", "ada.lovelace@example.test", "record_json.email"),
        })
        replica = rows["customer_data_read_replica#rowid=1"][0]
        self.assertEqual((replica.system_id, replica.resource_id),
                         ("identity_service", "tombstone_9009"))
        self.assertEqual(replica.attrs["record_json.email"], "null")


class SqlReplicaTopologyReal(unittest.TestCase):
    """Every real sql_replica_topology file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "sql_replica_topology")


if __name__ == "__main__":
    unittest.main()
