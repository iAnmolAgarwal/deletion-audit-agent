"""A linked record whose evidence gives no step fails the row closed (G5 verifier finding 5), next to
the two no-step rules it must not absorb: T69 (a legal hold that names no resource) and R8 (a record
with no observation at all).

The new rule (``engine`` module docstring, UNINTERPRETED_RECORD) rests on ``../CLAUDE.md`` section 3:
a failed read is never "nothing found". Every value here is made up.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from deletion_audit.engine import audit_all, build_context
from deletion_audit.record import CaseRecord

from ..engine_fixtures import Dataset, Person, case, kv_line, temp_dir

ADA = "ada@example.test"
C1 = case(9401)


def ada_with(*lines: str, activity: tuple[tuple[str, ...], ...] = ()) -> CaseRecord:
    """Ada asks for deletion; her account is gone (404 by her own email), plus the given log lines."""
    d = Dataset(people=[Person("user_9001", ADA)])
    d.add_request(C1, ADA)
    log = kv_line(
        "2026-05-02T10:00:00Z",
        level="INFO",
        service="account_service",
        trace_id="t1",
        event="profile_lookup_completed",
        resource_id="account_1",
        http_status="404",
        lookup_key=ADA,
    ) + "".join(lines)
    d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", log)
    for row in activity:
        d.add_activity(*row)
    with temp_dir() as tmp:
        return audit_all(build_context(d.write(Path(tmp))), [C1])[C1]


def codes(r: CaseRecord) -> set[str]:
    return {f.code for f in r.flags}


class Uninterpreted(unittest.TestCase):
    """Evidence at or before ``audit_at`` that the engine cannot turn into a step: FAILED_CLOSED."""

    def test_baseline_is_complete(self) -> None:
        r = ada_with()
        self.assertEqual((r.status, r.failed_closed), ("COMPLETE", None))
        self.assertEqual([s.operation for s in r.steps], ["VERIFY_RECORD_ABSENT"])

    def test_unknown_system_record_fails_closed(self) -> None:
        """The verifier's probe ``p2`` form: a live record of a system no rule covers."""
        line = kv_line(
            "2026-05-02T10:40:00Z",
            level="INFO",
            service="crm_service",
            trace_id="t6",
            event="crm_lookup_completed",
            resource_id="crm_1",
            http_status="200",
            email=ADA,
        )
        r = ada_with(line)
        self.assertEqual(
            (r.failed_closed, r.status, r.row_state), ("UNINTERPRETED_RECORD", "INCOMPLETE", "FAILED_CLOSED")
        )
        crm = [x for x in r.resources if x.key.resource_id == "crm_1"]
        self.assertEqual([x.decision.outcome for x in crm], ["NO_STEP"])
        self.assertIn("UNINTERPRETED_RECORD", {f.code for f in crm[0].flags})
        self.assertNotIn("crm_1", {s.resource_id for s in r.steps})  # no invented step
        self.assertTrue(all(s.evidence_id == "" for s in r.steps if s.phase == "VERIFICATION"))

    def test_known_system_record_with_no_readable_state_fails_closed(self) -> None:
        """A search record seen at or before ``audit_at`` only in lines that state nothing."""
        line = kv_line(
            "2026-05-02T10:20:00Z",
            level="DEBUG",
            service="search_service",
            trace_id="t3",
            event="index_query_started",
            resource_id="search_1",
            lookup_key=ADA,
        )
        r = ada_with(line)
        search = [x for x in r.resources if x.key.resource_id == "search_1"]
        self.assertEqual([(x.state.value, x.decision.outcome) for x in search], [(None, "NO_STEP")])
        self.assertEqual((r.failed_closed, r.status), ("UNINTERPRETED_RECORD", "INCOMPLETE"))

    def test_record_seen_only_after_audit_is_not_uninterpreted(self) -> None:
        """R5/R8: a record tied to Ada by a catalog row whose only observation is after ``audit_at``
        has no observation that counts, so it gets no step and does not fail the row closed."""
        row = (
            "a_1",
            "2026-05-02T09:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "crm_service",
            "crm_1",
            "SUCCESS",
            f"Data catalog linked crm_1 (crm_1) to {ADA} and user_9001.",
        )
        late = kv_line(
            "2026-05-09T10:40:00Z",
            level="INFO",
            service="crm_service",
            trace_id="t6",
            event="crm_lookup_completed",
            resource_id="crm_1",
            http_status="200",
            email=ADA,
        )
        r = ada_with(late, activity=(row,))
        crm = [x for x in r.resources if x.key.resource_id == "crm_1"]
        self.assertEqual([x.decision.outcome for x in crm], ["NO_STEP"])
        self.assertNotIn("UNINTERPRETED_RECORD", codes(r))
        self.assertEqual((r.status, r.failed_closed), ("COMPLETE", None))


class NoStepRulesKept(unittest.TestCase):
    """The no-step rules the new rule must not absorb (developer ruling, 2026-10-25T06:08:27+05:30)."""

    def test_t69_hold_naming_no_resource_gives_no_step_and_row_stays_complete(self) -> None:
        """T69: a legal-hold register entry that names the person but no resource produces no step."""
        line = kv_line(
            "2026-05-02T10:30:00Z",
            level="INFO",
            service="legal_service",
            trace_id="t4",
            event="retained_order_loaded",
            subject_ref="user_9001",
            order_number="ORD-9001",
            retain_until="2033-12-31T23:59:59Z",
        )
        r = ada_with(line)
        self.assertEqual((r.status, r.failed_closed), ("COMPLETE", None))
        self.assertEqual([(s.system_id, s.operation) for s in r.steps], [("account_service", "VERIFY_RECORD_ABSENT")])
        self.assertNotIn("legal_service", {x.key.system_id for x in r.resources})
        self.assertNotIn("UNINTERPRETED_RECORD", codes(r))

    def test_r8_record_with_no_observation_gives_no_step(self) -> None:
        """R8: a record known only by a catalog row, with no observation anywhere, has no state and no
        step, and does not fail the row closed (nothing was read that could not be interpreted)."""
        row = (
            "a_1",
            "2026-05-02T09:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "search_service",
            "search_7",
            "SUCCESS",
            f"Data catalog linked search_7 (search_7) to {ADA} and user_9001.",
        )
        r = ada_with(activity=(row,))
        search = [x for x in r.resources if x.key.resource_id == "search_7"]
        self.assertEqual([(x.state.value, x.decision.outcome) for x in search], [(None, "NO_STEP")])
        self.assertEqual((r.status, r.failed_closed), ("COMPLETE", None))
        self.assertNotIn("UNINTERPRETED_RECORD", codes(r))


if __name__ == "__main__":
    unittest.main()
