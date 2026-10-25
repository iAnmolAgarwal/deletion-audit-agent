"""The committed G8 red-team fixtures R01-R12, run end to end through ``pipeline.run``, replay-only
(developer ruling T105 item 4).

Every expected value comes from the fixture folder itself, written by hand before any engine run
(``code/tests/fixtures/redteam/*/EXPECTED.md``): ``expected_output.csv`` / ``expected_partial.csv``
rows, and ``expected_assertions.json`` wherever it exists. Nothing is read from ``runs/``, from a
cache or from an earlier engine output. Each run gets its own empty reply cache, so no model answer
is ever replayed: every case has the fail-closed intent of T71 Q2.

* **Settled rows** must equal their ``expected_output.csv`` / ``expected_partial.csv`` line exactly.
* **Rows that wait for the model's intent** are the expected ``NOT_APPLICABLE`` rows (R01, R02). In
  replay-only mode the engine gives them its deletion-path row, flagged ``INTENT_FAILED_CLOSED``;
  every assertion that does not depend on intent is checked on them (``check_pending``). **When the
  model's intent is in** (G7's mode-A run), move each such row to the exact list by deleting
  ``check_pending``'s call and letting ``check_exact`` cover it.
* The fixtures are named one by one, never globbed, as ``test_fixtures.py`` does.
"""

from __future__ import annotations

import csv
import io
import json
import unittest
from pathlib import Path
from typing import Any

from deletion_audit.pipeline import ModelSetup, run
from evaluation.coherence import Violation, check_file, load_evidence_index
from evaluation.outputs import read_output

from ..engine_fixtures import temp_dir

REDTEAM = Path(__file__).resolve().parents[1] / "fixtures" / "redteam"
FIXTURES = (
    "R01_negation_and_nondeletion",
    "R02_multilingual_requests",
    "R03_injection_request_and_evidence",
    "R04_lookalike_sharing_trace",
    "R05_post_audit_boundary",
    "R06_preaudit_line_in_postaudit_file",
    "R07_replica_copy_after_inventory",
    "R08_inventory_after_replica_copy",
    "R09_restore_and_sync_paths",
    "R10_tombstone_pii_variants",
    "R11_unreadable_evidence_beside_readable",
    "R12_malformed_request_rows_v2",
)


def csv_rows(path: Path) -> dict[str, tuple[str, list[dict[str, Any]], str]]:
    """case_id -> (status, steps, the raw CSV record) of an output-shaped file."""
    text = path.read_text(encoding="utf-8")
    out = {}
    lines = text.splitlines(keepends=True)
    for values, raw in zip(csv.reader(io.StringIO(text)), _records(lines), strict=True):
        if values[0] == "case_id":
            continue
        out[values[0]] = (values[1], json.loads(values[2]), raw)
    return out


def _records(lines: list[str]) -> list[str]:
    """The raw text of each CSV record (a quoted field may hold a newline)."""
    out, buf = [], ""
    for line in lines:
        buf += line
        if buf.count('"') % 2 == 0:
            out.append(buf.rstrip("\r\n"))
            buf = ""
    return out


class Ran:
    """One replay-only pipeline run on one red-team fixture, with an empty reply cache."""

    def __init__(self, name: str) -> None:
        self.root = REDTEAM / name
        self._tmp = temp_dir()
        tmp = Path(self._tmp.name)
        self.summary = run(
            self.root, run_id="rt", cases="test", runs_dir=tmp / "rundirs", model=ModelSetup.replay(tmp / "replycache")
        )
        self.dir = tmp / "rundirs" / "rt"
        self.rows = csv_rows(self.dir / "output.csv")
        self.cases = {c["case_id"]: c for c in map(json.loads, (self.dir / "cases.jsonl").read_text().splitlines())}
        self.producer: dict[str, Any] = json.loads((self.dir / "producer.json").read_text())
        self.artifact_text = "".join(
            (self.dir / n).read_text() for n in ("cases.jsonl", "producer.json", "metrics.json")
        )
        with (self.root / "evidence_files.csv").open(newline="", encoding="utf-8") as fh:
            self.manifest = {r["file_id"]: r for r in csv.DictReader(fh)}

    def coherence_hard(self) -> dict[str, set[str]]:
        """Hard coherence rules violated, by case (``code/evaluation/coherence.py``)."""
        ev = load_evidence_index(
            self.root / "evidence_files.csv", self.root / "system_activity.csv", self.root / "user_audit_log.csv"
        )
        out: dict[str, set[str]] = {}
        v: Violation
        for v in check_file(read_output(self.dir / "output.csv"), audit_at={}, evidence=ev):
            if v.severity == "hard":
                out.setdefault(v.case_id, set()).add(v.rule)
        return out

    def requests(self) -> dict[str, dict[str, str]]:
        """The fixture's well-formed request rows by case."""
        with (self.root / "deletion_requests.csv").open(newline="", encoding="utf-8") as fh:
            return {r["case_id"]: r for r in csv.DictReader(fh)}

    def close(self) -> None:
        self._tmp.cleanup()


def assertions(name: str) -> dict[str, Any] | None:
    path = REDTEAM / name / "expected_assertions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def expected(name: str) -> dict[str, tuple[str, list[dict[str, Any]], str]]:
    out: dict[str, tuple[str, list[dict[str, Any]], str]] = {}
    for fname in ("expected_output.csv", "expected_partial.csv"):
        path = REDTEAM / name / fname
        if path.exists():
            out.update(csv_rows(path))
    return out


def step_text(s: dict[str, Any]) -> str:
    return f"{s['phase']} {s['operation']} {s['system_id']} {s['resource_id']}"


class RedTeamFixtures(unittest.TestCase):
    """R01-R12 (module docstring)."""

    def test_every_fixture(self) -> None:
        for name in FIXTURES:
            with self.subTest(fixture=name):
                ran = Ran(name)
                try:
                    self.check_fixture(name, ran)
                finally:
                    ran.close()

    def check_fixture(self, name: str, ran: Ran) -> None:
        want = expected(name)
        spec = assertions(name)
        self.assertTrue(want or spec, "a fixture has expected rows or assertions")
        for cid, (status, _steps, raw) in sorted(want.items()):
            with self.subTest(fixture=name, case=cid):
                self.assertIn(cid, ran.rows)
                if status == "NOT_APPLICABLE":
                    self.check_pending(ran, cid)
                else:
                    self.check_exact(ran, cid, raw)
        if spec is not None:
            self.check_assertions(name, ran, spec)

    # ----------------------------------------------------------------- settled and pending rows
    def check_exact(self, ran: Ran, cid: str, raw: str) -> None:
        """A settled row: byte-equal to its expected line, and not a FAILED_CLOSED row."""
        self.assertEqual(ran.rows[cid][2], raw)
        self.assertIsNone(ran.cases[cid]["failed_closed"])
        self.assertNotIn(cid, ran.coherence_hard())

    def check_pending(self, ran: Ran, cid: str) -> None:
        """An expected NOT_APPLICABLE row before the model's intent: everything that does not depend on it."""
        status, steps, _ = ran.rows[cid]
        line = ran.cases[cid]
        self.assertNotEqual(status, "NOT_APPLICABLE")  # never NA without a validated model answer (T71 Q2)
        self.assertEqual(line["intent_source"], "FAILED_CLOSED")
        self.assertIn("INTENT_FAILED_CLOSED", {f["code"] for f in line["flags"]})
        self.assertEqual([c for c in line["checks_failed"] if c["severity"] == "hard"], [])
        self.assertNotIn(cid, ran.coherence_hard())
        req = ran.requests()[cid]
        audit_at = req["audit_at"]
        mine = self.person_tokens(ran, req["email"])
        lines = self.evidence_lines(ran)
        for s in steps:
            if s["evidence_id"]:  # no citation of a file captured after audit_at (CD-F21)
                self.assertLessEqual(ran.manifest[s["evidence_id"]]["captured_at"], audit_at)
            # the step's record shares an evidence line with one of the requester's own identifiers
            self.assertTrue(
                any(s["resource_id"] in ln and any(t in ln for t in mine) for ln in lines), s["resource_id"]
            )

    def person_tokens(self, ran: Ran, email: str) -> set[str]:
        """The requester's email and user_id(s) (``user_identities.csv``, exact email match)."""
        with (ran.root / "user_identities.csv").open(newline="", encoding="utf-8") as fh:
            ids = {r["user_id"] for r in csv.DictReader(fh) if r["email"].strip().lower() == email.strip().lower()}
        return {email} | {f"{u} " for u in ids} | {f"{u}\n" for u in ids} | {f"={u}" for u in ids}

    def evidence_lines(self, ran: Ran) -> list[str]:
        out = []
        for r in ran.manifest.values():
            path = ran.root / r["file_path"]
            if path.is_file():
                out += [ln + "\n" for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
        return out

    # ----------------------------------------------------------------- expected_assertions.json
    def check_assertions(self, name: str, ran: Ran, spec: dict[str, Any]) -> None:
        out = spec.get("output", {})
        if "row_count" in out:
            self.assertEqual(len(ran.rows), out["row_count"])
        if "case_ids" in out:
            self.assertEqual(list(ran.rows), out["case_ids"])
        everyone = spec.get("all_cases", {})
        hard = ran.coherence_hard()
        for cid, want in spec.get("cases", {}).items():
            with self.subTest(fixture=name, assertion_case=cid):
                status, steps, _ = ran.rows[cid]
                line = ran.cases[cid]
                cited = {s["evidence_id"] for s in steps}
                never = set(want.get("deletion_status_never", ())) | set(everyone.get("deletion_status_never", ()))
                self.assertNotIn(status, never)
                if "deletion_status" in want:
                    self.assertEqual(status, want["deletion_status"])
                for fid in list(want.get("never_cite", ())) + list(everyone.get("never_cite", ())):
                    self.assertNotIn(fid, cited)
                if want.get("failed_closed") or want.get("row_state") == "FAILED_CLOSED":
                    self.assertEqual(line["row_state"], "FAILED_CLOSED")
                    if "H03" in spec.get("coherence", {}):  # R11: "reported as hard for every FAILED_CLOSED row"
                        self.assertIn("H03", hard.get(cid, set()))
                for rid in want.get("failed_closed_reason_names", ()):
                    own = [f["detail"] for f in line["flags"] if f["code"] == line["failed_closed"]]
                    self.assertTrue(any(rid in d for d in own), (line["failed_closed"], own))
                if "reason_names_file" in want:  # R11: the file is named with its own reason and status
                    fid = want["reason_names_file"]
                    dep = [f["detail"] for f in line["flags"] if f["code"] == "FAILED_DEPENDENCY"]
                    status_of = ran.producer["evidence_parse"][fid]
                    self.assertTrue(
                        any(d.startswith(f"{fid}: ") and f"parse status {status_of})" in d for d in dep), dep
                    )
                    self.assertIn(fid, line["failed_dependencies"])
                for text in want.get("steps_must_include", ()):
                    self.assertIn(text, {step_text(s) for s in steps})
                if "search_finding_evidence_id" in want:
                    found = [
                        s["evidence_id"]
                        for s in steps
                        if s["phase"] == "FINDING" and s["system_id"] == "search_service"
                    ]
                    self.assertEqual(found, [want["search_finding_evidence_id"]])
                if want.get("never_findings"):
                    self.assertFalse([s for s in steps if s["phase"] == "FINDING"])
                if "rows" in want:
                    self.assertEqual(sum(1 for c in ran.rows if c == cid), want["rows"])
                reason = want.get("failed_closed_reason", {})
                if reason:
                    self.check_request_reason(ran, cid, reason)
                if everyone.get("steps_allowed"):
                    self.check_allowed_steps(steps)
                for rid in everyone.get("never_verified_resources", ()):
                    self.assertNotIn(rid, {s["resource_id"] for s in steps if s["phase"] == "VERIFICATION"})
        failed = {c for c, x in ran.cases.items() if x["row_state"] == "FAILED_CLOSED"}
        self.assertLessEqual(set(hard), failed)  # hard coherence violations only on FAILED_CLOSED rows
        for cid in spec.get("valid_rows", {}):
            with self.subTest(fixture=name, valid=cid):
                self.assertEqual(ran.rows[cid][2], expected(name)[cid][2])
                self.assertIsNone(ran.cases[cid]["failed_closed"])

    def check_allowed_steps(self, steps: list[dict[str, Any]]) -> None:
        """R11: ``[]``, or the own account's VERIFY_RECORD_ABSENT and the own audit record's
        VERIFY_RECORD_PRESENT, both with ``""``."""
        if not steps:
            return
        self.assertEqual(
            [(s["system_id"], s["operation"], s["evidence_id"]) for s in steps],
            [("account_service", "VERIFY_RECORD_ABSENT", ""), ("security_service", "VERIFY_RECORD_PRESENT", "")],
        )

    def check_request_reason(self, ran: Ran, cid: str, reason: dict[str, Any]) -> None:
        """R12: the malformed-request reason names the column (or the field count) and leaks no cell."""
        issues = [i for i in ran.producer["request_issues"] if i["case_id"] == cid]
        self.assertTrue(issues)
        self.assertEqual(ran.cases[cid]["failed_closed"], "MALFORMED_REQUEST")
        column = reason.get("must_name_column")
        if column == "(row)":
            self.assertTrue(any(i["reason"].startswith("expected 7 fields, found 8") for i in issues), issues)
        elif column:
            self.assertTrue(all(column in i["reason"] for i in issues), issues)
        if "more than once" in reason.get("must_state", ""):
            self.assertTrue(all("duplicate case_id" in i["reason"] for i in issues), issues)
        if reason.get("must_not_contain_cell_value"):
            with (ran.root / "deletion_requests.csv").open(newline="", encoding="utf-8") as fh:
                rows = [v for v in csv.reader(fh) if v and v[0] == cid]
            for values in rows:
                for v in values[1:]:
                    if v and v not in ("COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"):
                        self.assertNotIn(v, ran.artifact_text)


if __name__ == "__main__":
    unittest.main()
