"""``coherence.check_row`` is split into named checks: each states its rule first, then its reason, and
``check_row`` is exactly H02, the parse half of H03, then :data:`coherence.ROW_CHECKS` in order.

Rows are hand-built (``fixtures``); expected rule IDs are written out by hand.
"""
from __future__ import annotations

import re
import unittest
from collections.abc import Callable
from typing import Any

from evaluation import coherence
from evaluation.coherence import EvidenceIndex, RowChecks, Violation, check_row, parse_time

from .fixtures import complete_example, incomplete_example, row

AUDIT = "2026-09-15T12:00:00Z"
EV = EvidenceIndex(files={"evidence_01": parse_time("2026-09-01T00:00:00Z"),
                          "evidence_late": parse_time("2026-09-16T00:00:00Z")},
                   activities={"activity_7": parse_time("2026-09-01T00:00:00Z")}, audits={})
RULE_ID = re.compile(r"(?:H|S)[0-9]{2}")


Check = Callable[[RowChecks], None]


def found(check: Check, status: str, steps: list[Any], audit_at: str | None = AUDIT) -> list[Violation]:
    r = RowChecks("case_1", row("case_1", status, steps), steps, audit_at, EV)
    check(r)
    return r.found


def run_one(check: Check, status: str, steps: list[Any]) -> list[str]:
    return [v.rule for v in found(check, status, steps)]


class TestDocstrings(unittest.TestCase):
    def test_each_check_states_its_rule_then_its_reason(self) -> None:
        for check in (coherence.check_status_enum, *coherence.ROW_CHECKS):
            doc = check.__doc__ or ""
            first = doc.strip().split(":")[0]
            self.assertTrue(RULE_ID.search(first), f"{check.__name__}: docstring must open with its rule ID")
            self.assertIn("Reason:", doc, check.__name__)
            self.assertLess(doc.index(first), doc.index("Reason:"), check.__name__)

    def test_every_hard_rule_of_the_module_docstring_has_a_named_check(self) -> None:
        # H02-H10 are row rules (H01 and H16 are file rules, in check_file)
        opened = {m.group(0) for c in (coherence.check_status_enum, *coherence.ROW_CHECKS)
                  if (m := RULE_ID.search((c.__doc__ or "").strip())) is not None}
        self.assertTrue({"H02", "H03", "H04", "H05", "H06", "H07", "H08", "H09", "H10"} <= opened, opened)


class TestCheckRowIsTheNamedChecks(unittest.TestCase):
    def test_check_row_equals_h02_then_row_checks_in_order(self) -> None:
        bad = incomplete_example()[::-1]          # out of order, wrong step_no
        bad[0]["evidence_id"] = "evidence_late"   # a step dated after audit_at
        r = row("case_1", "COMPLETE", bad)        # COMPLETE with findings
        want = RowChecks("case_1", r, bad, AUDIT, EV)
        coherence.check_status_enum(want)
        for check in coherence.ROW_CHECKS:
            check(want)
        got = check_row(r, audit_at=AUDIT, evidence=EV)
        self.assertEqual(got, want.found)
        self.assertTrue({"H03", "H04", "H06", "H09"} <= {v.rule for v in got})

    def test_unparsed_steps_get_h02_and_h03_only(self) -> None:
        got = check_row(row("case_1", "DONE", None, raw="not json"), audit_at=AUDIT, evidence=EV)
        self.assertEqual([v.rule for v in got], ["H02", "H03"])


class TestNamedChecks(unittest.TestCase):
    def test_evidence_times_flags_post_audit_and_unknown_ids(self) -> None:
        s = complete_example("evidence_late")
        self.assertEqual(set(run_one(coherence.check_evidence_times, "COMPLETE", s)), {"H10"})
        s = complete_example("evidence_nowhere")
        self.assertEqual(set(run_one(coherence.check_evidence_times, "COMPLETE", s)), {"H10"})
        s = complete_example("activity_7")
        self.assertEqual(set(run_one(coherence.check_evidence_times, "COMPLETE", s)), {"S10"})

    def test_finding_mapping_runs_on_incomplete_only(self) -> None:
        s = [x for x in incomplete_example() if x["phase"] != "REMEDIATION"]
        self.assertIn("H08", run_one(coherence.check_finding_mapping, "INCOMPLETE", s))
        self.assertEqual(run_one(coherence.check_finding_mapping, "COMPLETE", s), [])

    def test_spec_order_flags_a_reversed_list(self) -> None:
        self.assertIn("H06", run_one(coherence.check_spec_order, "INCOMPLETE", incomplete_example()[::-1]))
        self.assertEqual(run_one(coherence.check_spec_order, "INCOMPLETE", incomplete_example()), [])

    def test_good_rows_pass_every_named_check(self) -> None:
        for status, steps in (("INCOMPLETE", incomplete_example()), ("COMPLETE", complete_example("evidence_01"))):
            for check in coherence.ROW_CHECKS:
                hard = [v for v in found(check, status, steps) if v.severity == "hard"]
                self.assertEqual(hard, [], f"{check.__name__} on a good {status} row")


if __name__ == "__main__":
    unittest.main()
