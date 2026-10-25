"""T51: coherence messages name only the case and the column, never a cell value.

A synthetic requests-shaped file (wrong header, extra columns, emails, free text, and JSON
cells full of distinctive step values) goes through read_output, check_file, summarize and
format_report; no cell value other than the case_id may appear in any message.
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from evaluation.coherence import EvidenceIndex, check_file, format_report, parse_time, summarize
from evaluation.outputs import read_output

EV = EvidenceIndex(files={"evidence_01": parse_time("2026-09-01T00:00:00Z")}, activities={}, audits={})


def leaves(value: object) -> list[str]:
    """Every string key and leaf of a JSON value, plus the str() of every scalar leaf."""
    if isinstance(value, dict):
        return [k for k in value] + [x for v in value.values() for x in leaves(v)]
    if isinstance(value, list):
        return [x for v in value for x in leaves(v)]
    return [] if value is None or isinstance(value, bool) else [str(value)]


class TestNoCellValueInMessages(unittest.TestCase):
    def test_requests_shaped_file(self) -> None:
        bad_step = {"step_no": "SNO-ZQ71", "phase": "PHASE-ZQ72", "system_id": "SYS-ZQ73",
                    "resource_id": "backup_9917", "operation": "OP-ZQ74", "state": "STATE-ZQ75",
                    "evidence_id": "EVID-ZQ76", "extra_key_ZQ77": "EXTRA-ZQ78"}
        late = {"step_no": 1, "phase": "VERIFICATION", "system_id": "system-ZQ79", "resource_id": "account_8813",
                "operation": "VERIFY_RECORD_PRESENT", "state": "PRESENT", "evidence_id": "evidence_01"}
        rows = [
            ["case_201", "zq.person1@example.test", "Zq Person One", "please erase everything ZQ80",
             "2026-08-01T00:00:00Z"],
            ["case_202", "zq.person2@example.test", json.dumps([bad_step, bad_step, late])],
            ["case_203", "COMPLETEZQ81", json.dumps([late, {"nested": ["ZQ82", {"kZQ86": "ZQ83"}]}, "ZQ84", 98765])],
            ["case_204", "NOT_APPLICABLE", json.dumps({"objZQ87": "ZQ85"})],
        ]
        header = ["case_id", "requester_email_zq", "requester_name_zq", "request_text_zq", "audit_at_zq"]
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "requests_like.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(header)
                w.writerows(rows)
            out = read_output(p)
            v = check_file(out, audit_at={"case_202": "2026-08-01T00:00:00Z"}, evidence=EV,
                           expected_ids=["case_201", "case_202", "case_203", "case_205"])
        self.assertTrue(v)
        messages = out.issues + [format_report(v), json.dumps(summarize(v))]
        forbidden: set[str] = set(header[1:])
        for r in rows:
            for cell in r[1:]:
                forbidden.add(cell)
                try:
                    forbidden.update(leaves(json.loads(cell)))
                except json.JSONDecodeError:
                    pass
        forbidden -= {"1"}  # the int 1 is also a step position; positions are allowed
        # values that are the rule's own vocabulary may appear as rule text, not as echoes
        forbidden -= {"VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT", "NOT_APPLICABLE", "step_no", "phase",
                      "system_id", "resource_id", "operation", "state", "evidence_id"}
        leaked = sorted(x for x in forbidden for m in messages if x and x in m)
        self.assertEqual(leaked, [], f"cell values in coherence messages: {leaked}")
        for x in v:
            self.assertTrue(x.step_no is None or isinstance(x.step_no, int))


if __name__ == "__main__":
    unittest.main()
