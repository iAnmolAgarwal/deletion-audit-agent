"""G4-fix round 2 (T72): verifier F1, F2, F3, notes 1 and 2, and run-ID validation.

Each test failed on the code before the fix (shown in the run log of this round).
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from evaluation import evidence_guard as eg
from evaluation import outputs, runs
from evaluation.coherence import EvidenceIndex, check_file, format_report, parse_time, summarize
from evaluation.drift import drift_table
from evaluation.outputs import read_output
from evaluation.scorer import score_predictions

from .fixtures import complete_example, gold

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
EV = EvidenceIndex(files={"evidence_03": parse_time("2026-09-01T00:00:00Z")}, activities={}, audits={})


@dataclass
class U:
    file_id: str
    kind: str


def recorder(units: list[U], files: dict[str, str]) -> eg.Recorder:
    r = eg.Recorder()
    r.units, r.manifest = units, {fid: {"file_path": p} for fid, p in files.items()}
    return r


class TestF1PngSignature(unittest.TestCase):
    """A png-model-needed skip is allowed only when the file's bytes start with the PNG signature."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ds = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def audit(self, name: str, data: bytes | None) -> dict:
        if data is not None:
            (self.ds / name).write_bytes(data)
        return eg.audit_extraction(recorder([], {"e1": name}), ["e1:png-model-needed"], self.ds)

    def test_real_png_signature_allowed(self) -> None:
        a = self.audit("shot.png", PNG)
        self.assertTrue(a["ok"], a)
        self.assertEqual(a["allowed_skips"], ["e1:png-model-needed"])

    def test_pdf_labelled_png_refused(self) -> None:
        a = self.audit("shot.png", b"%PDF-1.4\n")
        self.assertFalse(a["ok"])
        self.assertEqual(a["allowed_skips"], [])
        self.assertTrue(any(x.startswith("e1:png-model-needed") for x in a["refused_skips"]), a)

    def test_near_signatures_refused(self) -> None:
        for data in (b"", b"\x89PNG", b"\x89PNG\r\n\x1a", b"PNG\r\n\x1a\n" + b"\x00" * 8, b"\x89png\r\n\x1a\n"):
            with self.subTest(data=data):
                self.assertFalse(self.audit("x.png", data)["ok"])

    def test_missing_file_refused(self) -> None:
        self.assertFalse(self.audit("absent.png", None)["ok"])

    def test_by_content_not_name(self) -> None:
        self.assertTrue(self.audit("named.pdf", PNG)["ok"])

    def test_skip_for_file_not_in_manifest_refused(self) -> None:
        a = eg.audit_extraction(recorder([], {}), ["e9:png-model-needed"], self.ds)
        self.assertFalse(a["ok"])


class TestF2OutputHash(unittest.TestCase):
    REC = {"evidence_skipped": [], "evidence_failures": [], "output_sha256": "a" * 64}

    def test_match_ok(self) -> None:
        self.assertEqual(eg.check_producer(self.REC, pred_sha256="a" * 64)["status"], "ok")

    def test_mismatch_unchecked(self) -> None:
        c = eg.check_producer(self.REC, pred_sha256="b" * 64)
        self.assertEqual(c["status"], "output-mismatch")
        self.assertTrue(any("output_sha256" in r for r in c["reasons"]))

    def test_missing_hash_unchecked(self) -> None:
        rec = {k: v for k, v in self.REC.items() if k != "output_sha256"}
        self.assertNotEqual(eg.check_producer(rec, pred_sha256="a" * 64)["status"], "ok")

    def test_refusal_still_wins(self) -> None:
        rec = dict(self.REC, evidence_failures=["e1:zero-units:x"])
        self.assertEqual(eg.check_producer(rec, pred_sha256="b" * 64)["status"], "refused")


class TestNote2NullLists(unittest.TestCase):
    def test_null_failures_refused(self) -> None:
        rec = {"evidence_skipped": [], "evidence_failures": None, "output_sha256": "a" * 64}
        self.assertEqual(eg.check_producer(rec, pred_sha256="a" * 64)["status"], "refused")

    def test_null_or_non_list_skips_refused(self) -> None:
        for bad in (None, "e4:png-model-needed", {"a": 1}):
            rec = {"evidence_skipped": bad, "evidence_failures": [], "output_sha256": "a" * 64}
            with self.subTest(bad=bad):
                self.assertEqual(eg.check_producer(rec, pred_sha256="a" * 64)["status"], "refused")


class TestF3FieldSize(unittest.TestCase):
    def write(self, path: Path, cells: list[list[str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["case_id", "deletion_status", "steps_json"])
            w.writerows(cells)

    def test_200k_cell_reads(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "big.csv"
            self.write(p, [["case_01", "COMPLETE", json.dumps([{"x": "a" * 200000}])]])
            before = csv.field_size_limit()
            out = read_output(p)
            self.assertEqual(csv.field_size_limit(), before)  # the process limit is restored
        self.assertEqual(len(out.rows["case_01"].steps), 1)

    def test_cap_value(self) -> None:
        self.assertEqual(outputs.FIELD_SIZE_CAP, 16 * 1024 * 1024)

    def test_over_cap_row_is_issue_and_pipeline_continues(self) -> None:
        good = json.dumps(complete_example())
        with tempfile.TemporaryDirectory() as t, mock.patch.object(outputs, "FIELD_SIZE_CAP", 1000):
            p = Path(t) / "big.csv"
            self.write(p, [["case_01", "COMPLETE", "[" + "1," * 2000 + "1]"], ["case_02", "COMPLETE", good]])
            out = read_output(p)
        self.assertNotIn("case_01", out.rows)
        self.assertIn("case_02", out.rows)
        self.assertTrue(any("CSV error" in i for i in out.issues), out.issues)
        g = {c: gold(c, "COMPLETE", complete_example()) for c in ("case_01", "case_02")}
        res = score_predictions(out.rows, g)
        self.assertEqual(res["gold_cases_without_pred"], ["case_01"])
        v = check_file(out, audit_at={}, evidence=EV, expected_ids=["case_01", "case_02"])
        self.assertIn(("<file>", "H16", "hard"), {(x.case_id, x.rule, x.severity) for x in v})
        drift_table(out.rows, g)


class TestNote1CaseNames(unittest.TestCase):
    def test_non_case_ids_named_by_position(self) -> None:
        secret = "zq.person@example.test"
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "o.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(["case_id", "deletion_status", "steps_json"])
                w.writerow(["case_01", "BAD", "[]"])
                w.writerow([secret, "BAD", "[]"])
                w.writerow([secret, "BAD", "[]"])          # duplicate
                w.writerow(["case_7 ", "BAD", "[]"])       # near miss: trailing space
            out = read_output(p)
            v = check_file(out, audit_at={}, evidence=EV, expected_ids=["case_01", "case_99"])
        text = "\n".join(out.issues) + format_report(v) + json.dumps(summarize(v))
        self.assertNotIn(secret, text)
        self.assertNotIn("case_7 ", text)
        self.assertIn("case_01", text)
        self.assertIn("case_99", text)
        self.assertIn("<record 3>", text)  # header is record 1, as in read_output issues
        self.assertIn("<record 5>", text)


class TestRunIds(unittest.TestCase):
    def test_validation(self) -> None:
        with tempfile.TemporaryDirectory() as t, mock.patch.object(runs, "RUNS", Path(t)):
            for bad in ("g4fix-x --vision-1", "a b", "", ".hidden", "-x", "a/b", "..", "x\n", "é"):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    runs.run_dir(bad)
            for good in ("g4fix2-baseline-20261025T0430", "a", "A.b_c-1"):
                self.assertTrue(runs.run_dir(good).is_dir())


class TestReportRecheck(unittest.TestCase):
    """A run stored as producer-check ok is excluded when the current check fails on its record."""

    def test_recheck(self) -> None:
        from evaluation.numbers_md import render
        from evaluation.scorer import aggregate, score_case

        from .fixtures import row
        g = gold("case_01", "COMPLETE", complete_example())
        cases = [score_case(row("case_01", "COMPLETE", complete_example()), g)]
        ok_check = {"status": "ok", "reasons": [], "allowed_skips": [], "no_resource_id_files": [], "skip_count": 0}
        base = {"kind": "score", "command": "x", "description": "d", "coherence": {"hard": 0, "soft": 0},
                "aggregate": aggregate(cases), "cases": cases, "producer_check": ok_check}
        rec = {"evidence_skipped": [], "evidence_failures": [], "output_sha256": "a" * 64}
        cfgs = {"run-good": ({**rec}, "a" * 64), "run-nohash": ({"evidence_skipped": [], "evidence_failures": []}, "a" * 64),
                "run-mismatch": ({**rec}, "b" * 64)}
        with tempfile.TemporaryDirectory() as t:
            for i, (rid, (prod, sha)) in enumerate(cfgs.items()):
                d = Path(t) / rid
                d.mkdir()
                (d / "score.json").write_text(json.dumps({**base, "run_id": rid, "created_at": str(i)}), encoding="utf-8")
                (d / "config.json").write_text(json.dumps({"producer": prod, "pred_sha256": sha, "config_hash": "0" * 16,
                                                           "scorer_code_sha256": "0" * 16, "model_ids": [],
                                                           "paid_model_calls": 0}), encoding="utf-8")
            text = render(Path(t))
        self.assertIn("| `run-good` |", text)
        self.assertNotIn("| `run-nohash` |", text)
        self.assertNotIn("| `run-mismatch` |", text)
        self.assertIn("- `run-nohash`: passed the producer check at scoring time, but the current check says unverified", text)
        self.assertIn("- `run-mismatch`: passed the producer check at scoring time, but the current check says output-mismatch", text)


class TestRunNotes(unittest.TestCase):
    def test_discrim_time_suffix_note(self) -> None:
        from evaluation.numbers_md import RUN_NOTES
        self.assertIn("g4fix-discrim-20261025T0318", RUN_NOTES)
        self.assertIn("created_at", RUN_NOTES["g4fix-discrim-20261025T0318"])


if __name__ == "__main__":
    unittest.main()
