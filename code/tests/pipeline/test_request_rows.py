"""Request rows: the readable case-ID shape (T87(5)) and a case in both request files (T86 item 2).

G5 verifier findings 3 and 4. Every value is made up; case IDs are built at run time (T71 Q8).
"""

from __future__ import annotations

import csv
import io
import json
import unittest
from pathlib import Path

from deletion_audit.inputs.requests import SAMPLE_FILE, TEST_FILE, load_requests_checked
from deletion_audit.pipeline import run

from ..engine_fixtures import Dataset, Person, case, temp_dir

ADA, BO = "ada@example.test", "bo@example.test"
HEADER = "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\n"
TAIL = ",2026-05-01T08:00:00Z,COMPLETE,2026-05-02T12:00:00Z,2026-05-04T12:00:00Z,Please delete.\n"
BAD_TIME = ",2026-05-01T08:00:00Z,COMPLETE,2026-05-02T12:00:00Z,2026-13-40T99:00:00Z,Please delete.\n"
C1, C2, C3 = case(9301), case(9302), case(9303)


class RequestFilesCase(unittest.TestCase):
    """Writes a two-person dataset whose request files are raw text, so any case-ID text can be tried."""

    def write(self, test_rows: str, sample_rows: str = "") -> Path:
        """The dataset in a temporary directory removed after the test."""
        tmp = temp_dir()
        self.addCleanup(tmp.cleanup)
        root = Dataset(people=[Person("user_9001", ADA), Person("user_9002", BO)]).write(Path(tmp.name))
        (root / TEST_FILE).write_text(HEADER + test_rows, encoding="utf-8")
        (root / SAMPLE_FILE).write_text(HEADER + sample_rows, encoding="utf-8")
        return root


def output_ids(path: Path) -> list[str]:
    """The case IDs of an output file, in order."""
    return [r[0] for r in csv.reader(io.StringIO(path.read_text()))][1:]


class CaseIdShape(RequestFilesCase):
    """T87(5): a readable case ID is non-empty and exactly ``case_<digits>``."""

    def test_only_the_ruled_shape_is_readable(self) -> None:
        unreadable = ["zzz", "Robert.Tables", "case_", "Case_1", "case-1", "case_1a", " " + C1, C1 + " ", "x" + C1, ""]
        body = "".join(f"{bad},{ADA}{TAIL}" for bad in unreadable)
        root = self.write(f"{C1},{ADA}{TAIL}" + body)
        reqs, issues = load_requests_checked(root)
        self.assertEqual([r.case_id for r in reqs], [C1])
        self.assertEqual([(i.case_id, i.reason) for i in issues], [(None, "case_id not readable")] * len(unreadable))
        self.assertEqual([i.line for i in issues], list(range(3, 3 + len(unreadable))))

    def test_unreadable_ids_get_no_row_and_are_reported(self) -> None:
        """The verifier's probe ``p1`` form: a bad row and a valid row whose IDs are not readable."""
        root = self.write(
            f"{C1},{ADA}{TAIL}" + f"zzz,{BO}{BAD_TIME}" + f"Robert.Tables,{BO}{TAIL}" + f"{C2},{BO}{BAD_TIME}"
        )
        with temp_dir() as runs:
            s = run(root, run_id="ids", cases="test", runs_dir=Path(runs))
            self.assertEqual(output_ids(s.output_path), [C1, C2])
            producer = json.loads((Path(runs) / "ids" / "producer.json").read_text())
            self.assertEqual(
                [(i["line"], i["case_id"], i["reason"]) for i in producer["request_issues"]],
                [
                    (3, None, "case_id not readable"),
                    (4, None, "case_id not readable"),
                    (5, C2, "audit_at: unrecognized time"),
                ],
            )
            text = (Path(runs) / "ids" / "cases.jsonl").read_text() + json.dumps(producer)
            for value in ("zzz", "Robert.Tables", BO):
                self.assertNotIn(value, text)
            self.assertEqual(s.metrics["failed_closed"]["by_reason"].get("MALFORMED_REQUEST"), 1)  # the C2 row only


class CaseInBothFiles(RequestFilesCase):
    """T86 item 2: a case ID in both request files is a MALFORMED_REQUEST row, never a silent drop."""

    def test_clash_is_an_issue_in_each_file_at_its_line(self) -> None:
        root = self.write(f"{C1},{ADA}{TAIL}{C2},{BO}{TAIL}", f"{C3},{BO}{TAIL}{C2},{BO}{TAIL}")
        reqs, issues = load_requests_checked(root)
        self.assertEqual([(r.case_id, r.source) for r in reqs], [(C1, "test"), (C3, "sample")])
        self.assertEqual(
            sorted((i.file, i.line, i.case_id) for i in issues), sorted([(TEST_FILE, 3, C2), (SAMPLE_FILE, 3, C2)])
        )
        self.assertEqual({i.reason for i in issues}, {f"case_id also in {SAMPLE_FILE}", f"case_id also in {TEST_FILE}"})

    def test_malformed_test_row_never_answered_from_the_sample_file(self) -> None:
        """A malformed test row whose ID has a valid sample row: still MALFORMED_REQUEST, and the sample
        row is not used for it (or for anything else)."""
        root = self.write(f"{C1},{ADA}{TAIL}{C2},{BO}{BAD_TIME}", f"{C2},{BO}{TAIL}")
        reqs, issues = load_requests_checked(root)
        self.assertEqual([r.case_id for r in reqs], [C1])
        self.assertEqual(
            sorted((i.file, i.line, i.case_id) for i in issues), sorted([(TEST_FILE, 3, C2), (SAMPLE_FILE, 2, C2)])
        )
        with temp_dir() as runs:
            s = run(root, run_id="mal", cases="test", runs_dir=Path(runs))
            rows = {r[0]: r for r in csv.reader(io.StringIO(s.output_path.read_text()))}
            self.assertEqual(rows[C2][1:], ["INCOMPLETE", "[]"])

    def test_clash_case_gets_a_malformed_request_row(self) -> None:
        """The verifier's probe ``p1`` form: a test case copied into the sample file."""
        root = self.write(f"{C1},{ADA}{TAIL}{C2},{BO}{TAIL}", f"{C2},{BO}{TAIL}")
        with temp_dir() as runs:
            s = run(root, run_id="clash", cases="test", runs_dir=Path(runs))
            self.assertEqual(output_ids(s.output_path), [C1, C2])
            rows = {r[0]: r for r in csv.reader(io.StringIO(s.output_path.read_text()))}
            self.assertEqual(rows[C2][1:], ["INCOMPLETE", "[]"])
            cases = {
                c["case_id"]: c
                for c in map(json.loads, (Path(runs) / "clash" / "cases.jsonl").read_text().splitlines())
            }
            self.assertEqual(
                (cases[C2]["failed_closed"], cases[C2]["row_state"]), ("MALFORMED_REQUEST", "FAILED_CLOSED")
            )
            self.assertNotEqual(cases[C1]["failed_closed"], "MALFORMED_REQUEST")  # its neighbour is unaffected


if __name__ == "__main__":
    unittest.main()
