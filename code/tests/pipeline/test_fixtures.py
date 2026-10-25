"""The committed G5b fixtures, run end to end through ``pipeline.run`` (G5 verifier finding 1).

Every expected value comes from the fixture folder itself, written by hand and committed before any
engine run (``code/tests/fixtures/*/EXPECTED.md``): ``expected_output.csv`` for F02-F10,
``expected_assertions.json`` / ``expected_partial.csv`` for F11a and F11b. Nothing is read from
``runs/`` or from an earlier engine output. The fixtures are named one by one, never globbed, so a
fixture added later (for example by the red team) is never run by this file.

* F02-F10: ``output.csv`` equals ``expected_output.csv`` byte for byte.
* F11a / F11b: the machine-readable assertions, plus coherence (``code/evaluation/coherence.py``)
  reporting H03 as hard on each FAILED_CLOSED row and on no other row.
* F01 needs G7's intent (T71 Q2): until G7 is wired into ``pipeline.run`` its rows are the
  engine's deletion-path rows, flagged INTENT_FAILED_CLOSED, never NOT_APPLICABLE. That pre-G7 form
  is asserted explicitly here. **When G7 is wired, replace** ``test_f01_pre_g7_form`` **by adding
  F01 to** ``EXACT``.
"""

from __future__ import annotations

import csv
import io
import json
import unittest
from pathlib import Path
from typing import Any

from deletion_audit.pipeline import RunSummary, run
from evaluation.coherence import Violation, check_file, load_evidence_index
from evaluation.outputs import read_output

from ..engine_fixtures import temp_dir

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXACT = (
    "F02_korean_deletion_syslog_export",
    "F03_historical_uppercase_email",
    "F04_lookalike_jr_and_duplicate_name",
    "F05_post_audit_recreation",
    "F06_regional_replica_and_active_connector",
    "F07_open_restore_path",
    "F08_tombstone_with_email_hash",
    "F09_injection_and_free_text_pii",
    "F10_legal_hold_and_attachment",
)
F01 = "F01_non_deletion_negation_traps"
F11A = "F11a_missing_evidence_file"
F11B = "F11b_malformed_request_rows"


class Ran:
    """One pipeline run on one fixture, in a temporary runs directory."""

    def __init__(self, name: str) -> None:
        self.root = FIXTURES / name
        self._tmp = temp_dir()
        self.summary: RunSummary = run(self.root, run_id="fx", cases="test", runs_dir=Path(self._tmp.name))
        self.dir = Path(self._tmp.name) / "fx"
        self.output = (self.dir / "output.csv").read_bytes()
        self.cases = {c["case_id"]: c for c in map(json.loads, (self.dir / "cases.jsonl").read_text().splitlines())}
        self.producer: dict[str, Any] = json.loads((self.dir / "producer.json").read_text())
        self.artifact_text = "".join(
            (self.dir / n).read_text() for n in ("cases.jsonl", "producer.json", "metrics.json")
        )

    def rows(self) -> dict[str, tuple[str, list[dict[str, Any]], str]]:
        """case_id -> (status, steps, the raw CSV line)."""
        lines = self.output.decode().splitlines()
        out = {}
        for line in lines[1:]:
            cid, status, steps = next(csv.reader(io.StringIO(line)))
            out[cid] = (status, json.loads(steps), line)
        return out

    def coherence(self) -> list[Violation]:
        """Coherence violations of the run's output (no ``audit_at`` needed for H03)."""
        ev = load_evidence_index(
            self.root / "evidence_files.csv", self.root / "system_activity.csv", self.root / "user_audit_log.csv"
        )
        return check_file(read_output(self.dir / "output.csv"), audit_at={}, evidence=ev)

    def close(self) -> None:
        """Remove the temporary runs directory."""
        self._tmp.cleanup()


def hard_by_case(violations: list[Violation]) -> dict[str, set[str]]:
    """Hard rules violated, by case."""
    out: dict[str, set[str]] = {}
    for v in violations:
        if v.severity == "hard":
            out.setdefault(v.case_id, set()).add(v.rule)
    return out


def assertions(name: str) -> dict[str, Any]:
    """A fixture's committed ``expected_assertions.json``."""
    data: dict[str, Any] = json.loads((FIXTURES / name / "expected_assertions.json").read_text(encoding="utf-8"))
    return data


class ExactFixtures(unittest.TestCase):
    """F02-F10: byte-for-byte equality with the hand-written ``expected_output.csv``."""

    def test_output_equals_expected_byte_for_byte(self) -> None:
        for name in EXACT:
            with self.subTest(fixture=name):
                ran = Ran(name)
                try:
                    self.assertEqual(ran.output, (FIXTURES / name / "expected_output.csv").read_bytes())
                    self.assertEqual(ran.summary.metrics["failed_closed"]["count"], 0)
                    self.assertEqual(hard_by_case(ran.coherence()), {})
                finally:
                    ran.close()


class PreG7Fixture(unittest.TestCase):
    """F01, until G7 is wired (module docstring): its pre-G7 form, asserted explicitly."""

    def test_f01_pre_g7_form(self) -> None:
        ran = Ran(F01)
        try:
            expected = [r[0] for r in csv.reader(io.StringIO((FIXTURES / F01 / "expected_output.csv").read_text()))]
            rows = ran.rows()
            self.assertEqual(list(rows), expected[1:])  # one row per expected case, in order
            for cid, (status, steps, _) in rows.items():
                with self.subTest(case=cid):
                    self.assertNotEqual(status, "NOT_APPLICABLE")  # never NA without a validated model answer
                    self.assertEqual(status, "INCOMPLETE")  # the engine's deletion-path row (T71 Q2)
                    self.assertTrue(steps)
                    self.assertEqual(ran.cases[cid]["intent_source"], "FAILED_CLOSED")
                    self.assertIn("INTENT_FAILED_CLOSED", {f["code"] for f in ran.cases[cid]["flags"]})
        finally:
            ran.close()


class MissingEvidenceFixture(unittest.TestCase):
    """F11a: every assertion of its ``expected_assertions.json`` (T86 item 1)."""

    def test_f11a_assertions(self) -> None:
        spec = assertions(F11A)
        ran = Ran(F11A)
        try:
            rows = ran.rows()
            self.assertEqual(len(rows), spec["output"]["row_count"])
            self.assertEqual(list(rows), spec["output"]["case_ids"])
            readable = "".join(
                (ran.root / n).read_text(encoding="utf-8")
                for n in (
                    "deletion_requests.csv",
                    "sample_deletion_requests.csv",
                    "user_identities.csv",
                    "user_audit_log.csv",
                    "system_activity.csv",
                )
            )
            hard = hard_by_case(ran.coherence())
            for cid, want in spec["cases"].items():
                with self.subTest(case=cid):
                    status, steps, _ = rows[cid]
                    self.assertEqual(ran.cases[cid]["row_state"], want["row_state"])
                    self.assertEqual(status, want["deletion_status"])
                    self.assertNotIn(status, want["deletion_status_never"])
                    cited = {s["evidence_id"] for s in steps}
                    for fid in want["steps_never_cite"]:
                        self.assertNotIn(fid, cited)
                    if want["step_resource_ids_must_occur_in_readable_inputs"]:
                        for s in steps:
                            self.assertIn(s["resource_id"], readable)
                    reason = want["failed_closed_reason"]
                    fid = reason["must_name_file_id"]
                    self.assertEqual(ran.cases[cid]["failed_closed"], "MISSING_EVIDENCE_FILE")
                    self.assertIn(fid, ran.cases[cid]["failed_dependencies"])
                    self.assertEqual(ran.producer["evidence_parse"][fid], reason["parse_status_of_file"])
                    self.assertIn(f"{fid}:{reason['parse_status_of_file']}", ran.producer["evidence_failures"])
                    with (ran.root / "evidence_files.csv").open(newline="", encoding="utf-8") as fh:
                        paths = {r["file_id"]: r["file_path"] for r in csv.DictReader(fh)}
                    self.assertFalse((ran.root / paths[fid]).exists())  # the input really lacks the file
                    self.assertIn("H03", hard.get(cid, set()))  # "H03 reported as hard"
            self.assertEqual(set(hard), set(spec["cases"]))  # hard violations only in FAILED_CLOSED rows
        finally:
            ran.close()


class MalformedRequestFixture(unittest.TestCase):
    """F11b: every assertion of its ``expected_assertions.json`` and ``expected_partial.csv`` (T86 item 2)."""

    def test_f11b_assertions(self) -> None:
        spec = assertions(F11B)
        ran = Ran(F11B)
        try:
            rows = ran.rows()
            self.assertEqual(len(rows), spec["output"]["row_count"])
            self.assertEqual(list(rows), spec["output"]["case_ids"])
            partial = (FIXTURES / F11B / "expected_partial.csv").read_text().splitlines()
            partial_rows = {next(csv.reader(io.StringIO(line)))[0]: line for line in partial[1:]}
            self.assertEqual(set(partial_rows), set(spec["valid_rows"]))
            for cid, line in partial_rows.items():
                with self.subTest(valid=cid):
                    self.assertEqual(rows[cid][2], line)
                    self.assertIsNone(ran.cases[cid]["failed_closed"])
            with (ran.root / "deletion_requests.csv").open(newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                next(reader)
                by_line: dict[int, list[str]] = {}
                for values in reader:
                    by_line[reader.line_num] = values
            issues = ran.producer["request_issues"]
            hard = hard_by_case(ran.coherence())
            for cid, want in spec["cases"].items():
                with self.subTest(case=cid):
                    status, _, _ = rows[cid]
                    self.assertEqual(ran.cases[cid]["row_state"], want["row_state"])
                    self.assertEqual(ran.cases[cid]["failed_closed"], "MALFORMED_REQUEST")
                    self.assertEqual(status, want["deletion_status"])
                    self.assertNotIn(status, want["deletion_status_never"])
                    mine = [i for i in issues if i["case_id"] == cid]
                    self.assertEqual(len(mine), 1)  # the reason names its case
                    column = want["failed_closed_reason"]["must_name_column"]
                    if column == "(row)":  # the field count: "expected 7 fields, found 5"
                        values = by_line[mine[0]["line"]]
                        self.assertIn(f"expected 7 fields, found {len(values)}", mine[0]["reason"])
                    else:
                        self.assertIn(column, mine[0]["reason"])
                    self.assertIn(mine[0]["reason"], {f["detail"] for f in ran.cases[cid]["flags"]})
                    self.assertIn("H03", hard.get(cid, set()))
                    self._no_cell_values(ran, by_line[mine[0]["line"]])
            for want in spec["unreadable_case_id_rows"]:
                with self.subTest(line=want["file_line"]):
                    got = [i for i in issues if i["line"] == want["file_line"]]
                    self.assertEqual([(i["file"], i["case_id"]) for i in got], [("deletion_requests.csv", None)])
                    self._no_cell_values(ran, by_line[want["file_line"]])
            self.assertTrue(spec["output"]["no_row_for_unreadable_case_id"])
            self.assertEqual(set(hard), set(spec["cases"]))  # hard violations only in FAILED_CLOSED rows
        finally:
            ran.close()

    def _no_cell_values(self, ran: Ran, values: list[str]) -> None:
        """No cell of the row (email, times, request text) appears in the run artifacts (T51 (2)).
        The case ID is the row's name and the status column is an enum, so both may appear."""
        for v in values[1:]:
            if v and v not in ("COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"):
                self.assertNotIn(v, ran.artifact_text)


if __name__ == "__main__":
    unittest.main()
