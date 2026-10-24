"""Each coherence rule fires on a hand-built bad row, and stays silent on good rows and DEV gold."""
from __future__ import annotations

import datetime as dt
import json
import unittest

from evaluation.coherence import (EvidenceIndex, check_file, check_row, format_report, load_evidence_index,
                                  parse_time)
from evaluation.gold import load_gold, load_requests
from evaluation.outputs import OUTPUT_HEADER, OutputFile

from .fixtures import complete_example, incomplete_example, renumber, row, st

AUDIT = "2026-09-15T12:00:00Z"
EV = EvidenceIndex(
    files={"evidence_01": parse_time("2026-09-01T00:00:00Z"), "evidence_03": parse_time(AUDIT),
           "evidence_late": parse_time("2026-09-16T00:00:00Z")},
    activities={"activity_7": parse_time("2026-09-01T00:00:00Z")},
    audits={"audit_9": parse_time("2026-09-20T00:00:00Z")},
)


def rules(r, audit_at: str | None = AUDIT, hard_only: bool = True) -> set[str]:
    return {v.rule for v in check_row(r, audit_at=audit_at, evidence=EV) if v.severity == "hard" or not hard_only}


class TestGoodRows(unittest.TestCase):
    def test_incomplete_ok(self) -> None:
        self.assertEqual(rules(row("c", "INCOMPLETE", incomplete_example())), set())

    def test_complete_ok_with_capture_equal_to_audit(self) -> None:
        self.assertEqual(rules(row("c", "COMPLETE", complete_example("evidence_03"))), set())

    def test_na_ok(self) -> None:
        self.assertEqual(rules(row("c", "NOT_APPLICABLE", []), hard_only=False), set())


class TestStatusSteps(unittest.TestCase):
    def test_na_with_steps(self) -> None:
        self.assertIn("H03", rules(row("c", "NOT_APPLICABLE", complete_example())))

    def test_complete_with_finding(self) -> None:
        self.assertIn("H03", rules(row("c", "COMPLETE", incomplete_example())))

    def test_incomplete_without_finding(self) -> None:
        steps = renumber([s for s in incomplete_example() if s["phase"] != "FINDING"])
        self.assertIn("H03", rules(row("c", "INCOMPLETE", steps)))

    def test_empty_but_not_na(self) -> None:
        self.assertIn("H03", rules(row("c", "COMPLETE", [])))

    def test_unparseable(self) -> None:
        self.assertEqual(rules(row("c", "COMPLETE", None, raw="not json")), {"H03"})

    def test_bad_status(self) -> None:
        self.assertIn("H02", rules(row("c", "DONE", complete_example())))


class TestShapeEnumsOrder(unittest.TestCase):
    def test_step_no_gap(self) -> None:
        s = complete_example()
        s[1]["step_no"] = 3
        self.assertIn("H04", rules(row("c", "COMPLETE", s)))

    def test_step_no_string(self) -> None:
        s = complete_example()
        s[0]["step_no"] = "1"
        self.assertIn("H04", rules(row("c", "COMPLETE", s)))

    def test_missing_key(self) -> None:
        s = complete_example()
        del s[0]["state"]
        self.assertIn("H04", rules(row("c", "COMPLETE", s)))

    def test_unknown_operation_and_wrong_state(self) -> None:
        s = complete_example()
        s[0]["operation"] = "VERIFY_VIBES"
        self.assertIn("H05", rules(row("c", "COMPLETE", s)))
        s = complete_example()
        s[0]["state"] = "PRESENT"
        self.assertIn("H05", rules(row("c", "COMPLETE", s)))

    def test_out_of_order(self) -> None:
        s = complete_example()
        self.assertIn("H06", rules(row("c", "COMPLETE", renumber([s[1], s[0]]))))

    def test_operation_order_beats_system_order(self) -> None:
        # REDACTED (table index 11) before ANONYMIZED (12) even though support > analytics alphabetically
        s = [st(1, "VERIFY_RECORD_ABSENT", "account_service", "account_1", "evidence_01"),
             st(2, "VERIFY_RECORD_REDACTED", "support_platform", "support_1", "evidence_01"),
             st(3, "VERIFY_RECORD_ANONYMIZED", "analytics_platform", "analytics_1", "evidence_01")]
        self.assertEqual(rules(row("c", "COMPLETE", s)), set())

    def test_duplicate(self) -> None:
        s = complete_example()
        self.assertIn("H07", rules(row("c", "COMPLETE", renumber([s[0], s[0], s[1]]))))


class TestMappingAndEvidence(unittest.TestCase):
    def test_finding_without_remediation(self) -> None:
        s = incomplete_example()
        self.assertIn("H08", rules(row("c", "INCOMPLETE", renumber([s[0], s[2], s[3]]))))

    def test_remediation_without_verification(self) -> None:
        s = incomplete_example()
        self.assertIn("H08", rules(row("c", "INCOMPLETE", renumber([s[0], s[1], s[3]]))))

    def test_remediation_with_evidence(self) -> None:
        s = incomplete_example()
        s[1]["evidence_id"] = "evidence_01"
        self.assertIn("H09", rules(row("c", "INCOMPLETE", s)))

    def test_incomplete_verification_with_evidence(self) -> None:
        s = incomplete_example()
        s[2]["evidence_id"] = "evidence_01"
        self.assertIn("H09", rules(row("c", "INCOMPLETE", s)))

    def test_finding_without_evidence(self) -> None:
        self.assertIn("H09", rules(row("c", "INCOMPLETE", incomplete_example(ev=""))))

    def test_complete_verification_without_evidence(self) -> None:
        self.assertIn("H09", rules(row("c", "COMPLETE", complete_example(ev=""))))

    def test_evidence_after_audit(self) -> None:
        self.assertIn("H10", rules(row("c", "COMPLETE", complete_example("evidence_late"))))

    def test_unknown_evidence(self) -> None:
        self.assertIn("H10", rules(row("c", "COMPLETE", complete_example("evidence_404"))))

    def test_activity_citation_is_soft_and_time_checked(self) -> None:
        r = row("c", "COMPLETE", complete_example("activity_7"))
        self.assertEqual(rules(r), set())
        self.assertIn("S10", rules(r, hard_only=False))
        self.assertIn("H10", rules(row("c", "COMPLETE", complete_example("audit_9"))))


class TestFileLevel(unittest.TestCase):
    def _file(self, ids: list[str]) -> OutputFile:
        rows = {i: row(i, "NOT_APPLICABLE", []) for i in ids}
        return OutputFile(rows=rows, order=ids, issues=[], header=list(OUTPUT_HEADER))

    def test_missing_and_extra_cases(self) -> None:
        v = check_file(self._file(["case_1", "case_3"]), audit_at={}, evidence=EV, expected_ids={"case_1", "case_2"})
        hard = {(x.case_id, x.rule) for x in v if x.severity == "hard"}
        self.assertEqual(hard, {("case_2", "H16"), ("case_3", "H16")})

    def test_order(self) -> None:
        v = check_file(self._file(["case_2", "case_1"]), audit_at={}, evidence=EV)
        self.assertIn("H16", {x.rule for x in v if x.severity == "hard"})
        v = check_file(self._file(["case_9", "case_10"]), audit_at={}, evidence=EV)
        self.assertEqual({(x.rule, x.severity) for x in v}, {("H16", "soft")})

    def test_report_lists_offending_rows(self) -> None:
        r = row("case_77", "COMPLETE", complete_example("evidence_late"))
        text = format_report(check_row(r, audit_at=AUDIT, evidence=EV))
        self.assertIn("case_77", text)
        self.assertIn("H10", text)


class TestDevGoldIsCoherent(unittest.TestCase):
    """G1 found 0 structural violations in the 22 DEV rows; the checker must agree."""

    def test_dev_gold(self) -> None:
        gold = load_gold()
        audit = {c: r["audit_at"] for c, r in load_requests().items()}
        ids = sorted(gold)
        out = OutputFile(rows={c: row(c, gold[c].status, gold[c].steps) for c in ids}, order=ids, issues=[],
                         header=list(OUTPUT_HEADER))
        v = check_file(out, audit_at=audit, evidence=load_evidence_index(), expected_ids=set(ids))
        self.assertEqual([x for x in v if x.severity == "hard"], [])


if __name__ == "__main__":
    unittest.main()
