"""Family snapshot_bundle: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture


class SnapshotBundleFixture(unittest.TestCase):
    """Every snapshot is a full_collection scope; records carry their snapshot."""

    def setUp(self) -> None:
        self.fp = parse_fixture("snapshot_bundle.json")
        self.rows = by_ref(self.fp)

    def test_scopes_include_the_empty_collection(self) -> None:
        self.assertEqual(self.fp.status, "OK")
        self.assertEqual(
            [(s.locator.ref, s.systems, s.collection, s.as_of, s.source) for s in self.fp.scopes],
            [("$.snapshots[0]", frozenset({"account_service"}), "customer_profiles",
              "2026-05-08T12:00:00Z", "full_collection"),
             ("$.snapshots[1]", frozenset({"support_platform"}), "support_conversations",
              "2026-05-08T11:59:59Z", "full_collection"),
             ("$.snapshots[2]", frozenset({"privacy_treatment_service"}),
              "operational_record_history", "2026-05-08T12:00:00Z", "full_collection")])
        under_first = [o for o in self.fp.observations if o.scope == self.fp.scopes[0]]
        self.assertEqual(under_first, [])

    def test_support_record(self) -> None:
        obs = self.rows["$.snapshots[1].records[0]"][0]
        self.assertEqual(obs.record_time, "2026-05-08T11:59:59Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("support_platform", "support_3003"))
        self.assertIs(obs.scope, self.fp.scopes[1])
        self.assertEqual(obs.text, "Please call +44 20 7946 0001 or write to ada.lovelace@example.test.")
        self.assertEqual(id_set(obs.record_identifiers), {
            ("user_id", "user_9001", "subject_reference"),
            ("email", "ada.lovelace@example.test", "message_text"),
            ("phone", "+442079460001", "message_text"),
        })

    def test_history_record_uses_its_own_system_and_time(self) -> None:
        obs = self.rows["$.snapshots[2].records[0]"][0]
        self.assertEqual(obs.record_time, "2026-05-01T09:30:07Z")
        self.assertEqual((obs.system_id, obs.resource_id),
                         ("analytics_platform", "analytics_6006"))
        self.assertEqual(obs.event, "ANALYTICS_PROFILE")
        self.assertEqual(id_set(obs.lookup_identifiers),
                         {("email", "grace.hopper@example.test", "lookup_value")})
        self.assertEqual(obs.record_identifiers, frozenset())


class SnapshotBundleReal(unittest.TestCase):
    """Every real snapshot_bundle file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "snapshot_bundle")


if __name__ == "__main__":
    unittest.main()
