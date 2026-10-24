"""G4-fix round 3 (T80): verifier M1 (decode errors), M2 (run-ID check in load_score), and
one read of the bytes for both the hash and the parse in ``evaluate.py score``.

Gold: the CLI tests load DEV gold through ``gold.load_gold`` (the dev-filtered loader), as
``evaluate.py score`` does; the holdout is never loaded. ``runs.RUNS`` points at a temp dir.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evaluation import evaluate, runs
from evaluation.coherence import EvidenceIndex, check_file, format_report, parse_time
from evaluation.drift import drift_table
from evaluation.outputs import read_output
from evaluation.scorer import score_predictions

from .fixtures import complete_example, gold

EV = EvidenceIndex(files={"evidence_03": parse_time("2026-09-01T00:00:00Z")}, activities={}, audits={})
GOOD = json.dumps(complete_example()).replace('"', '""')


def write(path: Path, body: bytes) -> Path:
    path.write_bytes(body)
    return path


class TestM1DecodeErrors(unittest.TestCase):
    def test_bad_byte_in_one_row(self) -> None:
        body = (b"case_id,deletion_status,steps_json\n"
                b"case_01,NOT_APPLICABLE,[]\n"
                b'case_02,NOT_APPLICABLE,"[{""x"":""caf\xe9""}]"\n'
                b'case_03,COMPLETE,"' + GOOD.encode() + b'"\n')
        with tempfile.TemporaryDirectory() as t:
            out = read_output(write(Path(t) / "o.csv", body))
        self.assertEqual(sorted(out.rows), ["case_01", "case_03"])
        self.assertTrue(any(i.startswith("record 3: invalid UTF-8") for i in out.issues), out.issues)
        self.assertFalse(any("caf" in i for i in out.issues))
        g = {c: gold(c, "COMPLETE", complete_example()) for c in ("case_01", "case_02", "case_03")}
        self.assertEqual(score_predictions(out.rows, g)["gold_cases_without_pred"], ["case_02"])
        v = check_file(out, audit_at={}, evidence=EV, expected_ids=["case_01", "case_02", "case_03"])
        self.assertIn(("<file>", "H16", "hard"), {(x.case_id, x.rule, x.severity) for x in v})
        format_report(v)
        drift_table(out.rows, g)

    def test_bad_byte_in_case_id_and_header(self) -> None:
        body = b"case_id,deletion_\xff,steps_json\ncase_\xe901,COMPLETE,[]\ncase_02,COMPLETE,[]\n"
        with tempfile.TemporaryDirectory() as t:
            out = read_output(write(Path(t) / "o.csv", body))
        self.assertEqual(list(out.rows), ["case_02"])
        self.assertIsNone(out.header)
        self.assertTrue(any(i.startswith("record 1: invalid UTF-8") for i in out.issues))
        self.assertTrue(any(i.startswith("record 2: invalid UTF-8") for i in out.issues))

    def test_bom_still_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            out = read_output(write(Path(t) / "o.csv", b"\xef\xbb\xbfcase_id,deletion_status,steps_json\ncase_01,COMPLETE,[]\n"))
        self.assertEqual(out.header, ["case_id", "deletion_status", "steps_json"])
        self.assertIn("UTF-8 BOM present", out.issues)

    def test_hash_is_of_the_bytes_parsed(self) -> None:
        body = b"case_id,deletion_status,steps_json\ncase_01,COMPLETE,[]\n"
        with tempfile.TemporaryDirectory() as t:
            out = read_output(write(Path(t) / "o.csv", body))
        self.assertEqual(out.sha256, hashlib.sha256(body).hexdigest())


class CliCase(unittest.TestCase):
    """Runs ``evaluate.cmd_score`` with ``runs.RUNS`` in a temp dir."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.patch = mock.patch.object(runs, "RUNS", self.runs)
        self.patch.start()
        self.pred = self.root / "pred" / "output.csv"
        self.pred.parent.mkdir()
        self.pred.write_bytes(b"case_id,deletion_status,steps_json\ncase_01,COMPLETE,[]\n")

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def score(self, **kw: object) -> int:
        a = argparse.Namespace(pred=str(self.pred), run_id="t-run", prev=None, reconcile=None, expect="none",
                               description="", allow_incoherent=True)
        for k, v in kw.items():
            setattr(a, k, v)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return evaluate.cmd_score(a)


class TestOneReadForHashAndParse(CliCase):
    def test_pred_hashed_from_the_parsed_bytes(self) -> None:
        """The pred file's bytes are read exactly once, by any route (T81: the old version only
        patched runs.sha256_file, so a second read through hashlib still passed). The file
        changes after the first read: the recorded hash must be that of the bytes parsed."""
        first = self.pred.read_bytes()
        later = first + b"case_02,COMPLETE,[]\n"
        pred = self.pred.resolve()
        reads: list[str] = []
        inside = {"read_bytes": False}
        real_read_bytes, real_open = Path.read_bytes, Path.open

        def read_bytes(path: Path) -> bytes:
            inside["read_bytes"] = True
            try:
                data = real_read_bytes(path)
            finally:
                inside["read_bytes"] = False
            if path.resolve() == pred:
                reads.append("read_bytes")
                with real_open(pred, "wb") as f:  # the file changes right after the first read
                    f.write(later)
            return data

        def open_(path: Path, mode: str = "r", *a: object, **k: object):  # type: ignore[no-untyped-def]
            if path.resolve() == pred and mode.startswith("r") and not inside["read_bytes"]:
                reads.append(f"open-{mode}")
            return real_open(path, mode, *a, **k)

        with mock.patch.object(runs, "sha256_file", side_effect=AssertionError("pred file read a second time")), \
                mock.patch.object(Path, "read_bytes", read_bytes), mock.patch.object(Path, "open", open_):
            self.assertEqual(self.score(), 0)
        self.assertEqual(reads, ["read_bytes"])
        cfg = json.loads((self.runs / "t-run" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["pred_sha256"], hashlib.sha256(first).hexdigest())


class TestM2LoadScore(CliCase):
    def test_load_score_validates(self) -> None:
        outside = self.root / "outside" / "x"
        outside.mkdir(parents=True)
        (outside / "score.json").write_text(json.dumps({"cases": []}), encoding="utf-8")
        for bad in ("../outside/x", "a b", "", ".hidden", "-x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                runs.load_score(bad)

    def test_prev_refused_before_anything_is_written(self) -> None:
        """T81: not even the run directory may be created (the old version checked only the
        files, which load_score's own check already prevented)."""
        with self.assertRaises(ValueError):
            self.score(prev="../outside/x")
        self.assertFalse((self.runs / "t-run").exists())
        self.assertEqual(list(self.runs.iterdir()), [])

    def test_valid_prev_still_works(self) -> None:
        self.assertEqual(self.score(run_id="first"), 0)
        self.assertEqual(self.score(run_id="second", prev="first"), 0)
        s = json.loads((self.runs / "second" / "score.json").read_text(encoding="utf-8"))
        self.assertEqual((s["prev_run"], s["flips"]), ("first", []))


if __name__ == "__main__":
    unittest.main()


class TestGoldCheckOnHeldBytes(unittest.TestCase):
    """Synthetic gold only: the path check is forced to miss (as if the file became gold after
    it); the check on the bytes actually read must still refuse."""

    def test_second_check_refuses(self) -> None:
        from evaluation import outputs, paths
        from evaluation.gold import HoldoutLockedError

        from .test_gold import write_fixture
        with tempfile.TemporaryDirectory() as t:
            fake_gold, copy = Path(t) / "sample_output.csv", Path(t) / "copy.csv"
            write_fixture(fake_gold)
            copy.write_bytes(fake_gold.read_bytes())
            real = outputs.is_gold_file
            with mock.patch.object(paths, "SAMPLE_OUTPUT", fake_gold), \
                    mock.patch.object(outputs, "is_gold_file",
                                      side_effect=lambda p, data=None: False if data is None else real(p, data)):
                with self.assertRaises(HoldoutLockedError):
                    read_output(copy)


class TestG9GoldCheckOnHeldBytes(unittest.TestCase):
    """T81 item 1 (synthetic gold only): the check on held bytes compares them first and fails closed."""

    def setUp(self) -> None:
        from evaluation import paths
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.gold = self.d / "sample_output.csv"
        self.gold.write_bytes(b"case_id,deletion_status,steps_json\ncase_99,COMPLETE,[]\n")
        self.patch = mock.patch.object(paths, "SAMPLE_OUTPUT", self.gold)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_path_gone_but_bytes_are_gold(self) -> None:
        from evaluation.outputs import is_gold_file
        self.assertTrue(is_gold_file(self.d / "gone.csv", self.gold.read_bytes()))

    def test_race_in_read_output_refused(self) -> None:
        from evaluation.gold import HoldoutLockedError
        gb = self.gold.read_bytes()
        p = self.d / "pred.csv"
        p.write_bytes(b"case_id,deletion_status,steps_json\n")
        real = Path.read_bytes

        def rb(path: Path) -> bytes:
            if path == p:  # becomes gold for the read, then disappears before the second check
                p.write_bytes(gb)
                data = real(path)
                p.unlink()
                return data
            return real(path)

        with mock.patch.object(Path, "read_bytes", rb), self.assertRaises(HoldoutLockedError):
            read_output(p)

    def test_fails_closed_on_gold_side_error(self) -> None:
        from evaluation import outputs
        with mock.patch.object(outputs, "_sha256", side_effect=PermissionError("denied")):
            self.assertTrue(outputs.is_gold_file(self.d / "x.csv", self.gold.read_bytes()))

    def test_non_gold_and_missing_gold(self) -> None:
        from evaluation import outputs, paths
        gb = self.gold.read_bytes()
        self.assertFalse(outputs.is_gold_file(self.d / "q.csv", gb[:-2] + b"X\n"))
        with mock.patch.object(paths, "SAMPLE_OUTPUT", self.d / "no_gold_here.csv"):
            self.assertFalse(outputs.is_gold_file(self.d / "q.csv", gb))


class TestG9NumbersRunIds(unittest.TestCase):
    """T81 item 2: numbers_md never reads by an invalid or mismatched run ID from score.json."""

    def test_refused_and_nothing_read_outside(self) -> None:
        from evaluation import numbers_md
        with tempfile.TemporaryDirectory() as t:
            R = Path(t) / "runs"
            (R / "legit").mkdir(parents=True)
            (Path(t) / "outside").mkdir()
            (Path(t) / "outside" / "config.json").write_text("{}", encoding="utf-8")
            ok = {"status": "ok", "reasons": []}
            cases = {"../outside": "not a valid run ID", "other": "differs from the directory"}
            for rid, why in cases.items():
                (R / "legit" / "score.json").write_text(json.dumps(
                    {"run_id": rid, "kind": "score", "created_at": "x", "producer_check": ok}), encoding="utf-8")
                reads: list[str] = []
                real = Path.read_text

                def spy(path: Path, *a: object, **k: object) -> str:
                    reads.append(str(path))
                    return real(path, *a, **k)  # type: ignore[arg-type]

                with self.subTest(rid=rid), mock.patch.object(Path, "read_text", spy):
                    s = numbers_md._load_runs(R)[0]
                    reason = numbers_md._exclusion_reason(s, R)
                    self.assertIsNotNone(reason)
                    self.assertIn(why, reason)
                    self.assertFalse([r for r in reads if "outside" in r or "config.json" in r], reads)
            # the direct call the verifier used (no directory known): still refused, nothing read
            s = {"run_id": "../outside", "kind": "score", "producer_check": ok}
            self.assertIn("not a valid run ID", numbers_md._exclusion_reason(s, R))


class TestG9DriftReportsSkips(unittest.TestCase):
    """T81 item 4: drift reports records skipped as unreadable, records them, exits 2."""

    def test_drift(self) -> None:
        with tempfile.TemporaryDirectory() as t, mock.patch.object(runs, "RUNS", Path(t) / "runs"):
            p = write(Path(t) / "o.csv", b"case_id,deletion_status,steps_json\ncase_01,COMPLETE,[]\n"
                                         b"case_02,COMPLETE,\"[\"\"caf\xe9\"\"]\"\n")
            buf = io.StringIO()
            a = argparse.Namespace(pred=str(p), run_id="d-run", threshold=15.0)
            with contextlib.redirect_stdout(buf):
                rc = evaluate.cmd_drift(a)
            d = json.loads((Path(t) / "runs" / "d-run" / "drift.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 2)
        self.assertIn("skipped as unreadable", buf.getvalue())
        self.assertIn("record 3: invalid UTF-8", buf.getvalue())
        self.assertEqual(d["rows_read"], 1)
        self.assertEqual(len(d["unreadable_records_skipped"]), 1)
