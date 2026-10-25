"""Red-team fixtures through the wired pipeline: R03 (instruction-like text; T95 C4) and R06 (T101's
post-audit-only finding rule). The fixtures are read as test input only; case IDs come from their files.
"""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from deletion_audit.engine import audit_all, build_context
from deletion_audit.pipeline import ModelSetup, run

from ..agent._support import answer, audit_input, dataset, final_reply, tmpdir, tool_reply
from ._wiring import cases_jsonl, paid_setup, read_json, sent

REDTEAM = Path(__file__).resolve().parents[1] / "fixtures" / "redteam"
R03 = REDTEAM / "R03_injection_request_and_evidence"
R06 = REDTEAM / "R06_preaudit_line_in_postaudit_file"


def requests(root: Path) -> list[dict[str, str]]:
    with (root / "deletion_requests.csv").open(encoding="utf-8", newline="") as fh:
        return sorted(csv.DictReader(fh), key=lambda r: int(r["case_id"].split("_")[1]))


class TestR03InstructionLikeText(unittest.TestCase):
    """T95 C4: the code check and the model's flag are both in the per-case record; nothing is obeyed."""

    def setUp(self) -> None:
        self.tmp = tmpdir()
        rows = requests(R03)
        script = []
        for r in rows:
            quote = r["request_text"][:24]
            planted = "NOTE FOR THE AUTOMATED AUDITOR" in r["request_text"]  # the fixture's own marker
            script += [tool_reply(("audit_case", audit_input(quote, instruction_like_text=planted))),
                       final_reply(answer("DELETION_REQUEST", quote, kind="full_deletion", instruction_like=planted))]
        self.rows = rows
        self.setup = paid_setup(self.tmp / "replycache", script)
        self.summary = run(R03, run_id="r03", cases="test", runs_dir=self.tmp / "rundirs", replay_only=False,
                           model=self.setup)
        self.cases = cases_jsonl(self.tmp / "rundirs" / "r03")

    def test_both_flags_in_the_record_for_the_injected_request(self) -> None:
        injected = [r["case_id"] for r in self.rows if "NOTE FOR THE AUTOMATED AUDITOR" in r["request_text"]]
        self.assertEqual(len(injected), 1)
        line = self.cases[injected[0]]
        ilt = line["instruction_like_text"]
        self.assertEqual((ilt["code"], ilt["model"], ilt["merged"]), (True, True, True))
        self.assertIn("request", ilt["code_sources"])
        self.assertTrue(ilt["code_patterns"])
        self.assertEqual(line["agent"]["instruction_like_text"], ilt)
        self.assertLessEqual({"INSTRUCTION_LIKE_TEXT_CODE", "INSTRUCTION_LIKE_TEXT_MODEL"}, set(line["agent"]["flags"]))

    def test_the_injection_changes_no_row(self) -> None:
        self.assertEqual((self.tmp / "rundirs" / "r03" / "output.csv").read_bytes(),
                         (R03 / "expected_output.csv").read_bytes())
        self.assertEqual({c["status"] for c in self.cases.values()}, {"INCOMPLETE"})
        self.assertEqual(len(sent(self.setup)), 2 * len(self.rows))

    def test_the_plain_request_is_not_flagged_by_code(self) -> None:
        plain = [r["case_id"] for r in self.rows if "NOTE FOR THE AUTOMATED AUDITOR" not in r["request_text"]]
        for cid in plain:
            self.assertFalse(self.cases[cid]["instruction_like_text"]["code"], cid)


class TestR06PostAuditOnlyFinding(unittest.TestCase):
    """T101: a finding whose record only post-audit files hold fails its row closed, with its own reason."""

    def setUp(self) -> None:
        self.tmp = tmpdir()
        self.expect = json.loads((R06 / "expected_assertions.json").read_text(encoding="utf-8"))["cases"]
        run(R06, run_id="r06", cases="test", runs_dir=self.tmp / "rundirs",
            model=ModelSetup.replay(self.tmp / "replycache"))
        self.d = self.tmp / "rundirs" / "r06"
        self.cases = cases_jsonl(self.d)
        with (self.d / "output.csv").open(encoding="utf-8", newline="") as fh:
            self.rows = {r["case_id"]: r for r in csv.DictReader(fh)}

    def test_expected_assertions_hold(self) -> None:
        self.assertEqual(sorted(self.expect), sorted(self.rows))
        for cid, exp in self.expect.items():
            row, line = self.rows[cid], self.cases[cid]
            self.assertEqual(row["deletion_status"], exp["deletion_status"])
            self.assertNotIn(row["deletion_status"], exp["deletion_status_never"])
            self.assertEqual(line["row_state"] == "FAILED_CLOSED", exp["failed_closed"])
            self.assertEqual(line["failed_closed"], "POST_AUDIT_ONLY_FINDING")
            details = [f["detail"] for f in line["flags"] if f["code"] == "POST_AUDIT_ONLY_FINDING"]
            for rid in exp["failed_closed_reason_names"]:
                self.assertTrue(any(d.startswith(rid + ":") for d in details), rid)
            cited = {s["evidence_id"] for s in json.loads(row["steps_json"])}
            self.assertFalse(cited & set(exp["never_cite"]), cited)

    def test_reason_is_counted_in_the_metrics(self) -> None:
        metrics = read_json(self.d / "metrics.json")
        self.assertEqual(metrics["failed_closed"]["by_reason"], {"POST_AUDIT_ONLY_FINDING": len(self.expect)})
        self.assertEqual(metrics["flags"]["POST_AUDIT_ONLY_FINDING"], len(self.expect))

    def test_decided_by_the_engine_not_left_to_the_validator(self) -> None:
        ctx = build_context(R06)
        records = audit_all(ctx, sorted(self.expect))
        self.assertEqual({r.failed_closed for r in records.values()}, {"POST_AUDIT_ONLY_FINDING"})

    def test_a_record_a_pre_audit_file_also_holds_is_not_caught(self) -> None:
        d = dataset()  # Ada's account is in a pre-audit log and in a post-audit bundle
        (self.tmp / "ds").mkdir()
        root = d.write(self.tmp / "ds")
        ctx = build_context(root)
        records = audit_all(ctx, sorted(r.case_id for r in ctx.requests))
        self.assertFalse(any(f.code == "POST_AUDIT_ONLY_FINDING" for r in records.values() for f in r.flags))
        self.assertNotIn("POST_AUDIT_ONLY_FINDING", {r.failed_closed for r in records.values()})


if __name__ == "__main__":
    unittest.main()
