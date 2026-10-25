"""State at audit_at: latest wins (R6), omission in declared scopes (T50/T54), PDF time (T68), defaults (R8)."""

from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Literal

from deletion_audit.discovery.obstime import ObsTime, observation_time, pdf_stated_time
from deletion_audit.evidence.model import EvidenceIndex, FileParse, Locator, SnapshotScope
from deletion_audit.state import (
    ResourceKey,
    StateObservation,
    is_replica_copy,
    observation_state,
    omission_readings,
    record_readings,
    scope_listings,
    state_at,
)

from ..engine_fixtures import obs

ReadingKind = Literal["record", "alias", "omission", "image"]
ACC = ResourceKey("account_service", "account_1")
AUDIT = "2026-05-04T12:00:00Z"


def reading(
    value: str, t: str, file_id: str = "ev_1", kind: ReadingKind = "record", captured: str = "2026-05-01T00:00:00Z"
) -> StateObservation:
    return StateObservation(
        value, ObsTime(t, "second", "record_time"), file_id, captured, Locator(file_id, "line", "L1"), kind
    )


def scoped_index(
    listed: list[str],
    system: str = "account_service",
    source: str = "sql_snapshot_scope",
    collection: str | None = None,
    as_of: str = "2026-05-03T00:00:00Z",
) -> EvidenceIndex:
    scope = SnapshotScope("ev_s", frozenset({system}), as_of, source, collection, Locator("ev_s", "sql_row", "s#1"))  # type: ignore[arg-type]
    rows = tuple(
        obs(r, file_id="ev_s", system=system, family="sql_inventory", kind="sql_row", ref=f"t#{i}")
        for i, r in enumerate(listed)
    )
    rows = tuple(replace(o, scope=scope) for o in rows)
    return EvidenceIndex({"ev_s": FileParse("ev_s", "s.sql", "sql_inventory", "OK", rows, (scope,), None)})


class LatestWins(unittest.TestCase):
    """R5/R6."""

    def test_latest_observation_wins_same_time_violating(self) -> None:
        viol = frozenset({"PRESENT"})
        s = state_at(
            ACC,
            [reading("PRESENT", "2026-05-02T00:00:00Z"), reading("ABSENT", "2026-05-03T00:00:00Z")],
            AUDIT,
            violating=viol,
            default_absent=True,
        )
        self.assertEqual((s.value, s.basis), ("ABSENT", "latest_observation"))
        tie = state_at(
            ACC,
            [reading("ABSENT", "2026-05-03T00:00:00Z", "ev_a"), reading("PRESENT", "2026-05-03T00:00:00Z", "ev_b")],
            AUDIT,
            violating=viol,
            default_absent=True,
        )
        self.assertEqual(tie.value, "PRESENT")

    def test_post_audit_observation_never_decides(self) -> None:
        s = state_at(
            ACC,
            [reading("ABSENT", "2026-05-03T00:00:00Z"), reading("PRESENT", "2026-05-05T00:00:00Z")],
            AUDIT,
            violating=frozenset({"PRESENT"}),
            default_absent=True,
        )
        self.assertEqual(s.value, "ABSENT")

    def test_account_with_no_observation_default_absent_other_no_state(self) -> None:
        self.assertEqual(state_at(ACC, [], AUDIT, violating=frozenset(), default_absent=True).basis, "default_absent")
        other = state_at(
            ResourceKey("search_service", "search_1"), [], AUDIT, violating=frozenset(), default_absent=False
        )
        self.assertIsNone(other.value)

    def test_unparsed_dependency_blocks_default(self) -> None:
        s = state_at(ACC, [], AUDIT, violating=frozenset(), default_absent=True, depends_on=frozenset({"ev_png"}))
        self.assertEqual((s.value, s.depends_on), (None, frozenset({"ev_png"})))


class Omission(unittest.TestCase):
    """T54 in the tested sql_strict form, with T50."""

    def test_omission_in_declared_scope_absent(self) -> None:
        idx = scoped_index(["account_2"])
        rd = omission_readings(ACC, scope_listings(idx), {"ev_s": "2026-05-03T00:00:00Z"}, False)
        self.assertEqual([(r.value, r.file_id) for r in rd], [("ABSENT", "ev_s")])
        s = state_at(
            ACC,
            [reading("PRESENT", "2026-05-02T00:00:00Z"), *rd],
            AUDIT,
            violating=frozenset({"PRESENT"}),
            default_absent=True,
        )
        self.assertEqual((s.value, s.basis), ("ABSENT", "omission_in_declared_scope"))

    def test_listed_record_gets_no_omission(self) -> None:
        idx = scoped_index(["account_1"])
        self.assertEqual(omission_readings(ACC, scope_listings(idx), {"ev_s": AUDIT}, False), ())

    def test_scope_file_captured_after_audit_never_counts(self) -> None:
        rd = omission_readings(ACC, scope_listings(scoped_index([])), {"ev_s": "2026-05-09T00:00:00Z"}, False)
        s = state_at(
            ACC,
            [reading("PRESENT", "2026-05-02T00:00:00Z"), *rd],
            AUDIT,
            violating=frozenset({"PRESENT"}),
            default_absent=True,
        )
        self.assertEqual(s.value, "PRESENT")

    def test_sql_inventory_never_rules_out_replica_copy(self) -> None:
        self.assertTrue(is_replica_copy(obs("account_1", family="sql_replica_topology", event="customer_data_primary")))
        self.assertTrue(
            is_replica_copy(obs("account_1", family="sql_typed_tables", event="customer_profiles_failover_replica"))
        )
        self.assertFalse(is_replica_copy(obs("account_1", family="sql_inventory", event="customer_profiles")))

    def test_support_records_never_cover_attachments(self) -> None:
        key = ResourceKey("support_platform", "support_1")
        listings = scope_listings(scoped_index([], system="support_platform"))
        self.assertEqual(len(omission_readings(key, listings, {"ev_s": AUDIT}, False)), 1)  # a message: covered
        self.assertEqual(omission_readings(key, listings, {"ev_s": AUDIT}, True), ())  # an attachment: never

    def test_bundle_snapshot_covers_only_its_collection(self) -> None:
        good = scope_listings(scoped_index([], source="full_collection", collection="customer_profiles"))
        other = scope_listings(scoped_index([], source="full_collection", collection="operational_record_history"))
        self.assertEqual(len(omission_readings(ACC, good, {"ev_s": AUDIT}, False)), 1)
        self.assertEqual(omission_readings(ACC, other, {"ev_s": AUDIT}, False), ())

    def test_plain_export_never_proves_absence(self) -> None:
        """T50: a file that declares no scope yields no omission (real data: no collection_export scope)."""
        from ..evidence._support import real_index

        exports = [fp for fp in real_index().files.values() if fp.family == "collection_export"]
        self.assertTrue(exports)
        self.assertTrue(all(fp.scopes == () for fp in exports))
        idx = EvidenceIndex({fp.file_id: fp for fp in exports})
        self.assertEqual(scope_listings(idx), ())


class ObservationStates(unittest.TestCase):
    """Port of research/15's state reading (spot checks of each branch)."""

    def test_branches(self) -> None:
        cases = [
            (obs("account_1", attrs={"status_code": "404"}), "account_service", "ABSENT"),
            (obs("account_1", attrs={"http_status": "200"}), "account_service", "PRESENT"),
            (obs("search_1", event="index_query_completed", attrs={"result": "miss"}), "search_service", "ABSENT"),
            (obs("analytics_1", attrs={"direct_identifiers": "0"}), "analytics_platform", "ANONYMIZED"),
            (
                obs("support_1", event="message_read", attrs={"message_text": "[REDACTED]"}),
                "support_platform",
                "REDACTED",
            ),
            (obs("data_flow_1", attrs={"enabled": "true"}), "integration_service", "FLOW_ENABLED"),
            (obs("backup_1", attrs={"restore_allowed": "0"}), "backup_service", "RESTORE_BLOCKED"),
            (obs("tombstone_1", attrs={"email": "a@example.test"}), "identity_service", "EXPOSED_PII"),
            (obs("x_1", attrs={"record_type": "USER_PROFILE", "result": "NOT_FOUND"}), "account_service", "ABSENT"),
            (obs("account_1", event="profile_lookup_started", attrs={"status_code": "200"}), "account_service", None),
        ]
        for o, system, want in cases:
            with self.subTest(system=system, want=want):
                self.assertEqual(observation_state(o, system), want)
        self.assertEqual([r.value for r in record_readings(ACC, [cases[0][0]])], ["ABSENT"])


class PdfTime(unittest.TestCase):
    """T68: a page's stated production time at its precision, else captured_at; the basis is recorded."""

    def test_stated_minute_day_and_fallback(self) -> None:
        self.assertEqual(pdf_stated_time("issued 05 Sep 2026 06 30 UTC"), ("2026-09-05T06:30:00Z", "minute"))
        self.assertEqual(pdf_stated_time("generated 29 May 2026"), ("2026-05-29T00:00:00Z", "day"))
        self.assertIsNone(pdf_stated_time("submitted 18 Jun 2026 10 24 UTC"))  # an event the page describes
        page = obs(
            "support_1",
            kind="pdf_page",
            family="pdf_text",
            text="captured 12 Sep 2026 07 30 UTC",
            time=None,
            captured_at="2026-09-12T08:00:00Z",
        )
        t = observation_time(page)
        self.assertEqual((t.value, t.precision, t.basis), ("2026-09-12T07:30:00Z", "minute", "pdf_stated"))
        bare = obs(
            "support_1",
            kind="pdf_page",
            family="pdf_text",
            text="no time",
            time=None,
            captured_at="2026-09-12T08:00:00Z",
        )
        self.assertEqual(observation_time(bare).basis, "captured_at")

    def test_day_precision_compares_at_day(self) -> None:
        from deletion_audit.discovery.obstime import at_or_before

        day = ObsTime("2026-06-18T00:00:00Z", "day", "pdf_stated")
        self.assertTrue(at_or_before(day, "2026-06-18T00:00:01Z"))
        self.assertFalse(at_or_before(day, "2026-06-17T23:59:59Z"))


if __name__ == "__main__":
    unittest.main()
