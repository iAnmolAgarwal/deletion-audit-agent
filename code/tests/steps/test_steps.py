"""Steps: status from steps, numbering, order, F<->R<->V, evidence rules, serialization.

Property tests use seeded random generators (Hypothesis is not installed; G3 section 4.2): 400
random cases each, the seed fixed, so a failure is reproducible.
"""

from __future__ import annotations

import csv
import io
import json
import random
import unittest

from deletion_audit.policy.rules import Categorization, PolicyDecision
from deletion_audit.record import CrossCheck, IntentDecision, ResourceFinding, derive_status, fail_closed_intent
from deletion_audit.state import ResourceKey, ResourceState
from deletion_audit.steps import CitationPlan, compile_steps, render_output
from deletion_audit.steps.order import FINDING_TO_REMEDIATION, OPERATIONS, REMEDIATION_TO_VERIFICATION

FAIL_CLOSED = fail_closed_intent(CrossCheck(False, ()))
NOT_DELETION = IntentDecision("NOT_DELETION", "MODEL", "k", "k", CrossCheck(True, ("activity_1",)), True)
SYSTEMS = (
    "account_service",
    "search_service",
    "support_platform",
    "analytics_platform",
    "backup_service",
    "integration_service",
    "security_service",
)
TRIPLES = [
    ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
    ("REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"),
    ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED"),
    ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED"),
    ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED"),
]
VERIFS = [op for op, (ph, _) in OPERATIONS.items() if ph == "VERIFICATION"]

#: The contract's step order, typed here by hand from the organiser's operation table (``notes/CONTRACT_DRAFT.md``
#: F10-F12, each confirmed on DEV 22/22): phase, then this operation order, then ``system_id``, then
#: ``resource_id`` as a plain string (A3 reading (a)). It is deliberately not imported from ``steps.order``, so a
#: change to the production table cannot confirm itself (T63 pin 5).
HAND_PHASES = ("FINDING", "REMEDIATION", "VERIFICATION")
HAND_OPERATION_ORDER = (
    "REPORT_REMAINING_RECORD",
    "REPORT_EXPOSED_PII",
    "REPORT_ACTIVE_DATA_FLOW",
    "REPORT_RESTORE_RISK",
    "DISABLE_DATA_FLOW",
    "BLOCK_RESTORE",
    "DELETE_RECORD",
    "REDACT_RECORD",
    "ANONYMIZE_RECORD",
    "VERIFY_RECORD_ABSENT",
    "VERIFY_RECORD_PRESENT",
    "VERIFY_RECORD_REDACTED",
    "VERIFY_RECORD_ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED",
    "VERIFY_RESTORE_BLOCKED",
)


def hand_key(phase: str, operation: str, system_id: str, resource_id: str) -> tuple[int, int, str, str]:
    """The hand-written order above as a sort key (independent of the production key)."""
    return (HAND_PHASES.index(phase), HAND_OPERATION_ORDER.index(operation), system_id, resource_id)


def triple(system: str, rid: str, ops: tuple[str, str, str]) -> ResourceFinding:
    """A FINDING record with the given finding, remediation and verification."""
    key = ResourceKey(system, rid)
    return ResourceFinding(
        key,
        "identifier",
        ResourceState(key, "PRESENT", "latest_observation", None, None),
        Categorization("X", "resource_type"),
        PolicyDecision("rule_x", "FINDING", *ops),
        cite="ev_1",
    )


def finding(system: str, rid: str, rng: random.Random | None = None, cite: str = "ev_1") -> ResourceFinding:
    f, r, v = (rng or random.Random(0)).choice(TRIPLES)
    key = ResourceKey(system, rid)
    return ResourceFinding(
        key,
        "identifier",
        ResourceState(key, "PRESENT", "latest_observation", None, None),
        Categorization("X", "resource_type"),
        PolicyDecision("rule_x", "FINDING", f, r, v),
        cite=cite,
    )


def compliant(system: str, rid: str, op: str = "VERIFY_RECORD_ABSENT") -> ResourceFinding:
    key = ResourceKey(system, rid)
    return ResourceFinding(
        key,
        "identifier",
        ResourceState(key, "ABSENT", "latest_observation", None, None),
        Categorization("X", "resource_type"),
        PolicyDecision("rule_x", "COMPLIANT", None, None, op),
    )


def random_case(rng: random.Random) -> list[ResourceFinding]:
    out = []
    used: set[str] = set()
    for _ in range(rng.randint(1, 8)):
        rid = f"x_{rng.randint(1, 40)}"
        if rid in used:
            continue
        used.add(rid)
        sysid = rng.choice(SYSTEMS)
        out.append(finding(sysid, rid, rng) if rng.random() < 0.4 else compliant(sysid, rid, rng.choice(VERIFS)))
    rng.shuffle(out)
    return out


class Properties(unittest.TestCase):
    """Seeded property tests over random record sets."""

    def test_status_derived_from_steps(self) -> None:
        rng = random.Random(20261025)
        for _ in range(400):
            res = random_case(rng)
            steps = compile_steps(FAIL_CLOSED, res, CitationPlan("ev_9", "R14_linked"))
            has_f = any(r.decision.outcome == "FINDING" for r in res)
            self.assertEqual(derive_status(FAIL_CLOSED, steps), "INCOMPLETE" if has_f else "COMPLETE")
            self.assertEqual(any(s.phase == "FINDING" for s in steps), has_f)
            if not has_f:
                self.assertTrue(all(s.phase == "VERIFICATION" and s.evidence_id == "ev_9" for s in steps))
        self.assertEqual(compile_steps(NOT_DELETION, random_case(rng), CitationPlan("ev_9", "R14_linked")), ())
        self.assertEqual(derive_status(NOT_DELETION, ()), "NOT_APPLICABLE")

    def test_not_applicable_only_from_a_validated_model_answer(self) -> None:
        """Section 6 derivation (T71 Q2): NOT_DELETION is NOT_APPLICABLE only from MODEL or
        MODEL_AFTER_TOOLS; the same label from a failed or budget-capped call is the deletion path."""
        res = [compliant("account_service", "account_1")]
        for source, na in (
            ("MODEL", True),
            ("MODEL_AFTER_TOOLS", True),
            ("FAILED_CLOSED", False),
            ("FAILED_BUDGET", False),
        ):
            with self.subTest(source=source):
                intent = IntentDecision("NOT_DELETION", source, "k", "k", CrossCheck(False, ()), True)  # type: ignore[arg-type]
                self.assertEqual(intent.not_applicable, na)
                steps = compile_steps(intent, res, CitationPlan("ev_1", "R14_linked"))
                self.assertEqual((steps == ()), na)
                self.assertEqual(derive_status(intent, steps) == "NOT_APPLICABLE", na)

    def test_step_numbers_consecutive_from_one_and_sorted(self) -> None:
        """Numbering 1..n, and the order of the hand-written contract key (not the production key)."""
        rng = random.Random(7)
        for _ in range(400):
            steps = compile_steps(FAIL_CLOSED, random_case(rng), CitationPlan("ev_9", "R14_linked"))
            self.assertEqual([s.step_no for s in steps], list(range(1, len(steps) + 1)))
            keys = [hand_key(s.phase, s.operation, s.system_id, s.resource_id) for s in steps]
            self.assertEqual(keys, sorted(keys))

    def test_step_order_hand_written_sequence(self) -> None:
        """One mixed case, its whole expected order written out by hand from the contract (F10-F13).

        It separates operation order from system order (an operation-first sort and a system-first
        sort differ in every phase here), puts DISABLE_DATA_FLOW and BLOCK_RESTORE ahead of
        DELETE_RECORD (F24), and ties two resources on the same operation and system."""
        delete = ("REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
        anon = ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED")
        restore = ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED")
        flow = ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED")
        resources = [
            triple("search_service", "search_2", delete),
            triple("account_service", "account_1", delete),
            triple("analytics_platform", "analytics_3", anon),
            triple("backup_service", "backup_4", restore),
            triple("integration_service", "data_flow_5", flow),
            triple("search_service", "search_10", delete),
            compliant("security_service", "audit_record_6", "VERIFY_RECORD_PRESENT"),
            compliant("support_platform", "support_7", "VERIFY_RECORD_REDACTED"),
        ]
        steps = compile_steps(FAIL_CLOSED, resources, CitationPlan("ev_1", "R14_linked"))
        expected = [
            ("FINDING", "REPORT_REMAINING_RECORD", "account_service", "account_1"),
            ("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_10"),
            ("FINDING", "REPORT_REMAINING_RECORD", "search_service", "search_2"),
            ("FINDING", "REPORT_EXPOSED_PII", "analytics_platform", "analytics_3"),
            ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "integration_service", "data_flow_5"),
            ("FINDING", "REPORT_RESTORE_RISK", "backup_service", "backup_4"),
            ("REMEDIATION", "DISABLE_DATA_FLOW", "integration_service", "data_flow_5"),
            ("REMEDIATION", "BLOCK_RESTORE", "backup_service", "backup_4"),
            ("REMEDIATION", "DELETE_RECORD", "account_service", "account_1"),
            ("REMEDIATION", "DELETE_RECORD", "search_service", "search_10"),
            ("REMEDIATION", "DELETE_RECORD", "search_service", "search_2"),
            ("REMEDIATION", "ANONYMIZE_RECORD", "analytics_platform", "analytics_3"),
            ("VERIFICATION", "VERIFY_RECORD_ABSENT", "account_service", "account_1"),
            ("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_10"),
            ("VERIFICATION", "VERIFY_RECORD_ABSENT", "search_service", "search_2"),
            ("VERIFICATION", "VERIFY_RECORD_PRESENT", "security_service", "audit_record_6"),
            ("VERIFICATION", "VERIFY_RECORD_REDACTED", "support_platform", "support_7"),
            ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "analytics_platform", "analytics_3"),
            ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "integration_service", "data_flow_5"),
            ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "backup_service", "backup_4"),
        ]
        self.assertEqual([(s.phase, s.operation, s.system_id, s.resource_id) for s in steps], expected)
        self.assertEqual([s.step_no for s in steps], list(range(1, 21)))

    def test_operation_phase_state_table_and_no_duplicates(self) -> None:
        rng = random.Random(11)
        for _ in range(400):
            steps = compile_steps(FAIL_CLOSED, random_case(rng), CitationPlan("ev_9", "R14_linked"))
            for s in steps:
                self.assertEqual(OPERATIONS[s.operation], (s.phase, s.state))
            slots = [(s.phase, s.system_id, s.resource_id) for s in steps]
            self.assertEqual(len(slots), len(set(slots)))

    def test_finding_remediation_verification_one_to_one_and_evidence(self) -> None:
        rng = random.Random(13)
        for _ in range(400):
            steps = compile_steps(FAIL_CLOSED, random_case(rng), CitationPlan("ev_9", "R14_linked"))
            if not any(s.phase == "FINDING" for s in steps):
                continue
            by: dict[tuple[str, str], dict[str, str]] = {}
            for s in steps:
                by.setdefault((s.system_id, s.resource_id), {})[s.phase] = s.operation
                if s.phase == "FINDING":
                    self.assertTrue(s.evidence_id)
                else:
                    self.assertEqual(s.evidence_id, "")  # INCOMPLETE remediation and verification
            for ph in by.values():
                if "FINDING" in ph:
                    self.assertIn(ph["REMEDIATION"], FINDING_TO_REMEDIATION[ph["FINDING"]])
                    self.assertEqual(ph["VERIFICATION"], REMEDIATION_TO_VERIFICATION[ph["REMEDIATION"]])

    def test_resource_order_is_plain_string(self) -> None:
        steps = compile_steps(
            FAIL_CLOSED,
            [compliant("search_service", "search_10"), compliant("search_service", "search_9")],
            CitationPlan("ev_1", "R14_linked"),
        )
        self.assertEqual([s.resource_id for s in steps], ["search_10", "search_9"])

    def test_failed_closed_row_cites_no_verification(self) -> None:
        steps = compile_steps(
            FAIL_CLOSED,
            [compliant("account_service", "account_1")],
            CitationPlan("ev_1", "R14_linked"),
            failed_closed=True,
        )
        self.assertEqual([s.evidence_id for s in steps], [""])
        self.assertEqual(derive_status(FAIL_CLOSED, steps, "UNPARSED_DEPENDENCY"), "INCOMPLETE")


class Serialization(unittest.TestCase):
    """test_output_one_row_per_case_numeric_order_lf_compact_json."""

    def test_output_one_row_per_case_numeric_order_lf_compact_json(self) -> None:
        steps = compile_steps(
            FAIL_CLOSED, [compliant("account_service", "account_1")], CitationPlan("ev_1", "R14_linked")
        )
        data = render_output([("c_100", "COMPLETE", steps), ("c_9", "COMPLETE", steps), ("c_10", "NOT_APPLICABLE", ())])
        self.assertNotIn(b"\r\n", data)
        self.assertTrue(data.endswith(b"\n"))
        rows = list(csv.reader(io.StringIO(data.decode())))
        self.assertEqual(rows[0], ["case_id", "deletion_status", "steps_json"])
        self.assertEqual([r[0] for r in rows[1:]], ["c_9", "c_10", "c_100"])
        self.assertEqual(rows[2][2], "[]")
        self.assertEqual(rows[1][2], json.dumps(json.loads(rows[1][2]), separators=(",", ":")))
        self.assertEqual(
            list(json.loads(rows[1][2])[0]),
            ["step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"],
        )


if __name__ == "__main__":
    unittest.main()
