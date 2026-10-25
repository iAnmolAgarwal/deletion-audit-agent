"""Pre-write validator: T66 as amended by T71 Q3/Q4 and T77, plus the row and evidence rules."""

from __future__ import annotations

import unittest
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from deletion_audit.identity.resolve import IdentifierSet, IdentityResolution
from deletion_audit.record import CaseRecord, CrossCheck, FailedClosedReason, IntentDecision, fail_closed_intent
from deletion_audit.state import ResourceKey
from deletion_audit.steps.model import CitationPlan, Step
from deletion_audit.validate import CheckResult, ValidationContext, gate, hard_failures, validate_row

from ..engine_fixtures import req

AUDIT = "2026-07-19T13:00:00Z"
INTENT = fail_closed_intent(CrossCheck(False, ()))


def ctx(**over: Any) -> ValidationContext:
    base = dict(
        citable_time={
            "ev_pdf": "2026-07-18T11:00:00Z",
            "ev_sql": "2026-07-01T00:00:00Z",
            "ev_late": "2026-07-20T00:00:00Z",
            "ev_rep": "2026-07-01T00:00:00Z",
            "activity_5": "2026-07-18T11:07:01Z",
            "audit_7": "2026-02-01T00:00:00Z",
        },
        file_resources={
            "ev_sql": frozenset({ResourceKey("account_service", "account_1")}),
            "ev_rep": frozenset({ResourceKey("account_service", "account_8")}),
        },
        file_scope_systems={"ev_sql": frozenset({"account_service"})},
        file_listed_systems={"ev_sql": frozenset({"account_service"}), "ev_rep": frozenset({"account_service"})},
        file_status={},
        file_aliases={"ev_pdf": frozenset({"REF-1"})},
        resource_aliases={"export_1": (("REF-1", "2026-07-18T11:07:01Z"),)},
        activity_resource={"activity_5": "export_1"},
    )
    base.update(over)
    return ValidationContext(**base)  # type: ignore[arg-type]


def s(no: int, phase: str, system: str, rid: str, op: str, state: str, ev: str) -> Step:
    return Step(no, phase, system, rid, op, state, ev)


def record(
    steps: tuple[Step, ...], *, failed: FailedClosedReason | None = None, intent: IntentDecision = INTENT
) -> CaseRecord:
    ident = IdentityResolution("CURRENT", IdentifierSet("user_9", frozenset(), frozenset(), frozenset()), ())
    return CaseRecord(
        "c_1",
        req("c_1", "a@example.test", audit_at=AUDIT),
        intent,
        ident,
        None,
        (),
        CitationPlan(None, "none"),
        (),
        (),
        (),
        frozenset(),
        steps,
        (),
        (),
        failed,
    )


def finding_row(ev: str) -> tuple[Step, ...]:
    return (
        s(1, "FINDING", "export_service", "export_1", "REPORT_REMAINING_RECORD", "PRESENT", ev),
        s(2, "REMEDIATION", "export_service", "export_1", "DELETE_RECORD", "ABSENT", ""),
        s(3, "VERIFICATION", "export_service", "export_1", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
    )


def failed_rules(checks: Sequence[CheckResult]) -> set[str]:
    return {c.rule for c in checks if not c.ok}


class HardCheck(unittest.TestCase):
    """test_hard_citation_contains_resource, with the alias three ways (T71 Q3)."""

    def test_alias_with_timely_link_counts_as_contained(self) -> None:
        self.assertEqual(failed_rules(validate_row(record(finding_row("ev_pdf")), ctx())), set())

    def test_alias_without_link_fails(self) -> None:
        got = validate_row(record(finding_row("ev_pdf")), ctx(resource_aliases={}))
        self.assertIn("HARD_CONTAINS", {c.rule for c in hard_failures(got)})

    def test_alias_with_link_after_audit_fails(self) -> None:
        late = ctx(resource_aliases={"export_1": (("REF-1", "2026-07-20T00:00:00Z"),)})
        self.assertIn(
            "HARD_CONTAINS", {c.rule for c in hard_failures(validate_row(record(finding_row("ev_pdf")), late))}
        )

    def test_hard_citation_contains_resource(self) -> None:
        bad = finding_row("ev_sql")  # ev_sql holds account_1 only
        self.assertIn("HARD_CONTAINS", {c.rule for c in hard_failures(validate_row(record(bad), ctx()))})
        present = (
            s(1, "VERIFICATION", "security_service", "audit_record_1", "VERIFY_RECORD_PRESENT", "PRESENT", "ev_sql"),
        )
        self.assertIn("HARD_CONTAINS", {c.rule for c in hard_failures(validate_row(record(present), ctx()))})

    def test_activity_citation_contains_its_resource(self) -> None:
        self.assertEqual(failed_rules(validate_row(record(finding_row("activity_5")), ctx())), set())


class AbsenceBranches(unittest.TestCase):
    """test_absent_citation_branches and test_other_absence_citation_flagged_not_changed."""

    def _v(
        self, rid: str, ev: str, op: str = "VERIFY_RECORD_ABSENT", system: str = "account_service"
    ) -> tuple[CheckResult, ...]:
        row = (s(1, "VERIFICATION", system, rid, op, {"VERIFY_RECORD_ABSENT": "ABSENT"}.get(op, "REDACTED"), ev),)
        return validate_row(record(row), ctx())

    def test_absent_citation_branches(self) -> None:
        self.assertEqual(failed_rules(self._v("account_1", "ev_sql")), set())  # contains
        self.assertEqual(failed_rules(self._v("account_2", "ev_sql")), set())  # declared scope
        self.assertEqual(failed_rules(self._v("account_2", "ev_rep")), set())  # same-system listing
        off = self._v("search_2", "ev_rep", system="search_service")
        self.assertEqual([(c.rule, c.severity) for c in off if not c.ok], [("ABSENT_BRANCH", "flag")])

    def test_other_absence_citation_flagged_not_changed(self) -> None:
        r = record(
            (s(1, "VERIFICATION", "support_platform", "support_1", "VERIFY_RECORD_REDACTED", "REDACTED", "ev_sql"),)
        )
        checks = validate_row(r, ctx())
        self.assertEqual([(c.rule, c.severity) for c in checks if not c.ok], [("OTHER_ABSENCE", "flag")])
        out = gate(r, ctx())
        self.assertEqual((out.steps, out.failed_closed), (r.steps, None))


class RowRules(unittest.TestCase):
    """T77, evidence rules, NA rows, audit IDs, and the gate."""

    def test_row_rules(self) -> None:
        cited_v = finding_row("ev_pdf")[:2] + (replace(finding_row("ev_pdf")[2], evidence_id="ev_pdf"),)
        self.assertIn("T77_INCOMPLETE_VERIFICATION_EMPTY", failed_rules(validate_row(record(cited_v), ctx())))
        uncited = (s(1, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", ""),)
        self.assertIn("T77_COMPLETE_VERIFICATION_CITES", failed_rules(validate_row(record(uncited), ctx())))
        self.assertIn("T77_FINDING_CITES", failed_rules(validate_row(record(finding_row("")), ctx())))

    def test_every_cited_id_in_index_and_not_after_audit_at(self) -> None:
        late = (s(1, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_late"),)
        self.assertIn("EVIDENCE_TIME", failed_rules(validate_row(record(late), ctx())))
        ghost = (s(1, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_none"),)
        self.assertIn("EVIDENCE_EXISTS", failed_rules(validate_row(record(ghost), ctx())))
        equal = ctx(citable_time={"ev_sql": AUDIT})
        ok = (s(1, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_sql"),)
        self.assertEqual(failed_rules(validate_row(record(ok), equal)), set())  # equality allowed

    def test_audit_id_citation_accepted(self) -> None:
        row = (s(1, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", "audit_7"),)
        self.assertNotIn("EVIDENCE_EXISTS", failed_rules(validate_row(record(row), ctx())))

    def test_na_rows_validated(self) -> None:
        na = IntentDecision("NOT_DELETION", "MODEL", "k", "k", CrossCheck(True, ()), True)
        self.assertEqual(failed_rules(validate_row(record((), intent=na), ctx())), set())
        with_steps = validate_row(record(finding_row("ev_pdf"), intent=na), ctx())
        self.assertIn("NA_EMPTY", failed_rules(with_steps))
        self.assertIn("NA_EMPTY", failed_rules(validate_row(record(()), ctx())))  # a deletion row is never []

    def test_hard_failure_never_drops_a_finding(self) -> None:
        """A finding is never dropped; since T105 (R06) its citation of a file that does not hold the
        record is blanked (before: ``ev_sql`` was written although it holds only account_1)."""
        out = gate(record(finding_row("ev_sql")), ctx())
        self.assertEqual(out.failed_closed, "VALIDATOR_REFUSED")
        self.assertEqual([x.phase for x in out.steps], ["FINDING", "REMEDIATION", "VERIFICATION"])
        self.assertEqual(out.steps[0].evidence_id, "")
        self.assertEqual(out.status, "INCOMPLETE")


class GateFixRound2(unittest.TestCase):
    """T105 on R06 (citation blanking, one count) and on R04 (the ownership safety net)."""

    def test_failed_hard_contains_citation_is_blanked_in_a_failed_closed_row(self) -> None:
        """R06 shape: the row is already FAILED_CLOSED for its own reason; its finding cites a file that
        does not contain the record. The citation is blanked, the step and the reason are kept."""
        r = record(finding_row("ev_sql"), failed="POST_AUDIT_ONLY_FINDING")
        out = gate(r, ctx())
        self.assertEqual(out.failed_closed, "POST_AUDIT_ONLY_FINDING")
        self.assertEqual([(x.phase, x.resource_id) for x in out.steps], [(x.phase, x.resource_id) for x in r.steps])
        self.assertEqual({x.evidence_id for x in out.steps}, {""})
        self.assertNotIn("ev_sql", {x.evidence_id for x in out.steps})

    def test_a_failure_seen_by_both_passes_is_counted_once(self) -> None:
        """Before: the gate kept both passes' results, so HARD_CONTAINS (and FAILED_CLOSED) counted twice."""
        out = gate(record(finding_row("ev_sql"), failed="POST_AUDIT_ONLY_FINDING"), ctx())
        failing = [(c.rule, c.step_no) for c in out.checks if not c.ok]
        self.assertEqual(len(failing), len(set(failing)))
        self.assertEqual(failing.count(("HARD_CONTAINS", 1)), 1)
        self.assertEqual(failing.count(("FAILED_CLOSED", None)), 1)
        self.assertIn(("T77_FINDING_CITES", 1), failing)  # the blanked finding, found by the second pass

    def test_every_check_counted_once_on_random_gated_rows(self) -> None:
        """Seeded property test (Hypothesis is not installed): whatever the citations, a gated row's
        checks never repeat a (rule, step_no, ok) failure, and the gate never drops a step."""
        import random

        cites = ("ev_sql", "ev_late", "ev_pdf", "nowhere", "", "activity_5")
        reasons: tuple[FailedClosedReason | None, ...] = (None, "POST_AUDIT_ONLY_FINDING", "UNPARSED_DEPENDENCY")
        for seed in range(200):
            rng = random.Random(seed)
            steps = tuple(replace(x, evidence_id=rng.choice(cites)) for x in finding_row("ev_pdf"))
            out = gate(record(steps, failed=rng.choice(reasons)), ctx())
            failing = [(c.rule, c.step_no) for c in out.checks if not c.ok]
            self.assertEqual(len(failing), len(set(failing)), seed)
            self.assertEqual(len(out.steps), len(steps), seed)
            if out.failed_closed is not None:
                self.assertEqual(out.status, "INCOMPLETE", seed)

    def test_step_on_another_persons_record_is_a_hard_failure(self) -> None:
        """T105 safety net: the requester is user_9; a record whose own key names user_8 never gets a step."""
        own = {"export_1": frozenset({"user_8"})}
        got = validate_row(record(finding_row("ev_pdf")), ctx(resource_own_persons=own))
        self.assertIn("OWN_KEY_OTHER_PERSON", {c.rule for c in hard_failures(got)})
        both = {"export_1": frozenset({"user_8", "user_9"})}
        got = validate_row(record(finding_row("ev_pdf")), ctx(resource_own_persons=both))
        self.assertIn("OWN_KEY_OTHER_PERSON", {c.rule for c in hard_failures(got)})
        out = gate(record(finding_row("ev_pdf")), ctx(resource_own_persons=own))
        self.assertEqual((out.failed_closed, out.status, len(out.steps)), ("VALIDATOR_REFUSED", "INCOMPLETE", 3))

    def test_step_on_the_requesters_own_record_passes(self) -> None:
        mine = {"export_1": frozenset({"user_9"})}
        got = validate_row(record(finding_row("ev_pdf")), ctx(resource_own_persons=mine))
        self.assertEqual(failed_rules(got), set())
        self.assertIn("OWN_KEY_OTHER_PERSON", {c.rule for c in got})  # it was checked

    def test_post_audit_citation_is_blanked_and_row_fails_closed(self) -> None:
        r = record((s(1, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_late"),))
        out = gate(r, ctx())
        self.assertEqual(
            (out.failed_closed, out.status, out.steps[0].evidence_id), ("VALIDATOR_REFUSED", "INCOMPLETE", "")
        )

    def test_complete_row_holds_verification_steps_only(self) -> None:
        """``../CLAUDE.md`` section 3 (COMPLETE => VERIFICATION steps only), G1 H03; G5 verifier finding 2.

        A row with no FINDING derives COMPLETE; a REMEDIATION (or any non-verification) step in it is a
        hard failure, and the gate turns the row into FAILED_CLOSED(VALIDATOR_REFUSED), never COMPLETE."""
        verify = s(2, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_sql")
        clean = record((replace(verify, step_no=1),))
        self.assertEqual((clean.status, failed_rules(validate_row(clean, ctx()))), ("COMPLETE", set()))
        stray = record((s(1, "REMEDIATION", "account_service", "account_1", "DELETE_RECORD", "ABSENT", ""), verify))
        self.assertEqual(stray.status, "COMPLETE")
        self.assertIn("COMPLETE_VERIFICATION_ONLY", {c.rule for c in hard_failures(validate_row(stray, ctx()))})
        out = gate(stray, ctx())
        self.assertEqual((out.failed_closed, out.status), ("VALIDATOR_REFUSED", "INCOMPLETE"))
        self.assertEqual([x.operation for x in out.steps], ["DELETE_RECORD", "VERIFY_RECORD_ABSENT"])  # nothing dropped

    def test_complete_engine_row_with_a_remediation_added_fails(self) -> None:
        """The G5 verifier's ``valprobe`` repro, on committed fixture F04 (a COMPLETE row): adding a
        DELETE_RECORD remediation must give a hard failure."""
        from pathlib import Path

        from deletion_audit.engine import audit_all, build_context, build_world

        root = Path(__file__).resolve().parents[1] / "fixtures" / "F04_lookalike_jr_and_duplicate_name"
        c = build_context(root)
        w = build_world(c)
        (cid,) = [r.case_id for r in c.requests]
        r = audit_all(c, [cid], world=w)[cid]
        self.assertEqual(r.status, "COMPLETE")
        extra = Step(0, "REMEDIATION", "account_service", "account_900410", "DELETE_RECORD", "ABSENT", "")
        steps = tuple(replace(x, step_no=i) for i, x in enumerate((extra, *r.steps), start=1))
        bad = replace(r, steps=steps, checks=())
        self.assertEqual(bad.status, "COMPLETE")
        self.assertIn("COMPLETE_VERIFICATION_ONLY", {c.rule for c in hard_failures(validate_row(bad, w.validation))})

    def test_order_check_against_hand_written_sequences(self) -> None:
        """ORDER: phase, the contract's operation order, system_id, resource_id (``notes/CONTRACT_DRAFT.md``
        F10-F12, DEV 22/22). Each row is written out by hand; none is sorted with the production key."""
        good = (
            s(1, "FINDING", "search_service", "search_1", "REPORT_REMAINING_RECORD", "PRESENT", "ev_sql"),
            s(2, "FINDING", "analytics_platform", "analytics_1", "REPORT_EXPOSED_PII", "PRESENT", "ev_sql"),
            s(3, "FINDING", "integration_service", "data_flow_1", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE", "ev_sql"),
            s(4, "REMEDIATION", "integration_service", "data_flow_1", "DISABLE_DATA_FLOW", "DISABLED", ""),
            s(5, "REMEDIATION", "search_service", "search_1", "DELETE_RECORD", "ABSENT", ""),
            s(6, "REMEDIATION", "analytics_platform", "analytics_1", "ANONYMIZE_RECORD", "ANONYMIZED", ""),
            s(7, "VERIFICATION", "search_service", "search_1", "VERIFY_RECORD_ABSENT", "ABSENT", ""),
            s(8, "VERIFICATION", "analytics_platform", "analytics_1", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED", ""),
            s(9, "VERIFICATION", "integration_service", "data_flow_1", "VERIFY_DATA_FLOW_DISABLED", "DISABLED", ""),
        )
        self.assertNotIn("ORDER", failed_rules(validate_row(record(good), ctx())))
        by_system = tuple(replace(x, step_no=i) for i, x in enumerate((good[1], good[2], good[0], *good[3:]), 1))
        self.assertIn("ORDER", failed_rules(validate_row(record(by_system), ctx())))  # system before operation
        delete_first = tuple(replace(x, step_no=i) for i, x in enumerate((*good[:3], good[4], good[3], *good[5:]), 1))
        self.assertIn("ORDER", failed_rules(validate_row(record(delete_first), ctx())))  # F24: disable first
        ties = (
            s(1, "VERIFICATION", "search_service", "search_10", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_sql"),
            s(2, "VERIFICATION", "search_service", "search_9", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_sql"),
            s(3, "VERIFICATION", "account_service", "account_1", "VERIFY_RECORD_PRESENT", "PRESENT", "ev_sql"),
        )
        self.assertNotIn("ORDER", failed_rules(validate_row(record(ties), ctx())))  # plain-string resource order
        swapped = tuple(replace(x, step_no=i) for i, x in enumerate((ties[1], ties[0], ties[2]), 1))
        self.assertIn("ORDER", failed_rules(validate_row(record(swapped), ctx())))
        by_resource = (
            s(1, "VERIFICATION", "search_service", "a_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_sql"),
            s(2, "VERIFICATION", "account_service", "b_1", "VERIFY_RECORD_ABSENT", "ABSENT", "ev_sql"),
        )
        self.assertIn("ORDER", failed_rules(validate_row(record(by_resource), ctx())))  # system before resource

    def test_failed_closed_never_complete_never_na(self) -> None:
        for reason in (
            "UNPARSED_DEPENDENCY",
            "UNINTERPRETED_RECORD",
            "MISSING_EVIDENCE_FILE",
            "EVIDENCE_PARSE_ERROR",
            "UNKNOWN_EVIDENCE_FAMILY",
            "OWN_KEY_CONFLICT",
            "NO_CATEGORY_RULE",
            "IMAGE_OMITS_CATALOG_RECORD",
            "IMAGE_STATE_NOT_SHOWN",
            "IDENTITY_UNRESOLVED",
            "NOTHING_FOUND",
            "MALFORMED_REQUEST",
            "VALIDATOR_REFUSED",
        ):
            r = record((), failed=reason)
            self.assertEqual(r.status, "INCOMPLETE")
            self.assertEqual(r.row_state, "FAILED_CLOSED")
            self.assertEqual(gate(r, ctx()).failed_closed, reason)  # keeps its own reason


if __name__ == "__main__":
    unittest.main()
