"""B2: the evidence guard refuses non-allow-listed skips, zero-unit files and swallowed log
JSON errors; ``check_producer`` refuses bad producer records and reports missing ones."""
from __future__ import annotations

import json
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

from evaluation import evidence_guard as eg


@dataclass
class U:
    file_id: str
    kind: str


def recorder(units: list[U], files: dict[str, str]) -> eg.Recorder:
    r = eg.Recorder()
    r.units = units
    r.manifest = {fid: {"file_path": path} for fid, path in files.items()}
    return r


class TestAllowList(unittest.TestCase):
    def test_exactly_one_reason(self) -> None:
        self.assertEqual(eg.ALLOWED_SKIP_REASONS, frozenset({"png-model-needed"}))

    def test_reasons(self) -> None:
        self.assertTrue(eg.skip_allowed("evidence_04:png-model-needed"))
        for bad in ("evidence_05:unknown-json", "evidence_05:unknown", "evidence_05:FAILED:ValueError:x",
                    "evidence_05:alias-scan-failed:OSError", "evidence_05:something-new", "evidence_05",
                    "evidence_05:png-model-needed-later"):
            self.assertFalse(eg.skip_allowed(bad), bad)


class TestAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ds = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def files(self, **content: object) -> dict[str, str]:
        out = {}
        for fid, body in content.items():
            name = f"{fid}.json"
            (self.ds / name).write_text(json.dumps(body), encoding="utf-8")
            out[fid] = name
        return out

    def test_clean(self) -> None:
        f = {"e1": "a.log", "e2": "b.png"}
        (self.ds / "b.png").write_bytes(eg.PNG_SIGNATURE + b"\x00" * 8)  # T72: allowed only by content
        a = eg.audit_extraction(recorder([U("e1", "log:x")], f), ["e2:png-model-needed"], self.ds)
        self.assertTrue(a["ok"], a)
        self.assertEqual(a["allowed_skips"], ["e2:png-model-needed"])

    def test_refused_skip(self) -> None:
        f = {"e1": "a.log", "e2": "b.json"}
        a = eg.audit_extraction(recorder([U("e1", "log:x")], f), ["e2:unknown-json"], self.ds)
        self.assertFalse(a["ok"])
        self.assertEqual(a["refused_skips"], ["e2:unknown-json"])

    def test_zero_units_is_failure(self) -> None:
        f = {"e1": "a.log", "e2": "doc.pdf"}
        a = eg.audit_extraction(recorder([U("e1", "log:x")], f), [], self.ds)
        self.assertFalse(a["ok"])
        self.assertEqual(len(a["zero_unit_files"]), 1)
        self.assertTrue(a["zero_unit_files"][0].startswith("e2:zero-units"))

    def test_declared_scope_no_rows_is_ok(self) -> None:
        f = self.files(
            e1={"collection": "customer_export_jobs", "records": []},
            e2={"service_exports": {"account_service": {"customer_profiles": []}}},
            e3={"snapshots": [{"data_store": "x", "collection": "c", "captured_at": "t", "records": []}]},
        )
        a = eg.audit_extraction(recorder([], f), [], self.ds)
        self.assertTrue(a["ok"], a)
        self.assertEqual(a["declared_scope_no_rows_files"], ["e1", "e2", "e3"])

    def test_no_declared_scope_is_failure(self) -> None:
        f = self.files(e1={"records": []}, e2={"service_exports": {}}, e3={"snapshots": []}, e4=[1, 2],
                       e5={"collection": "c", "records": [{"resource_id": "x"}]})
        a = eg.audit_extraction(recorder([], f), [], self.ds)
        self.assertEqual(len(a["zero_unit_files"]), 5, a)

    def test_scope_marker_only_listed(self) -> None:
        a = eg.audit_extraction(recorder([U("e1", "sql_scope:t")], {"e1": "x.sql"}), [], self.ds)
        self.assertTrue(a["ok"])
        self.assertEqual(a["scope_marker_only_files"], ["e1"])

    def test_not_instrumented(self) -> None:
        self.assertFalse(eg.audit_extraction(eg.Recorder(), [], self.ds)["ok"])


class TestNoResourceIdState(unittest.TestCase):
    """T51: "text present, no resource ID" is listed and passes; everything else refuses.
    Fake PDFs (content starts with %PDF-) with a fake text-layer extractor."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ds = Path(self.tmp.name)
        self.layers: dict[str, str] = {}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def pdf(self, name: str, layer: str, raw_extra: bytes = b"") -> str:
        (self.ds / name).write_bytes(b"%PDF-1.4\n%fake\n" + raw_extra)
        self.layers[name] = layer
        return name

    def audit(self, files: dict[str, str], units: list[U] | None = None) -> dict:
        return eg.audit_extraction(recorder(units or [], files), [], self.ds,
                                   pdf_text=lambda p: self.layers[Path(p).name], extra_prefixes=["legal_hold_"])

    def test_qualifying_file_passes_and_is_listed(self) -> None:
        f = {"e1": self.pdf("report.pdf", "Account history for user_12 and user_340.\nNo record numbers here.")}
        a = self.audit(f)
        self.assertTrue(a["ok"], a)
        self.assertEqual(a["no_resource_id_files"], ["e1"])
        self.assertEqual(a["zero_unit_files"], [])

    def test_resource_id_token_in_text_refuses(self) -> None:
        for token in ("support_4417", "AUDIT_RECORD_9", "x_account_12", "legal_hold_3"):
            with self.subTest(token=token):
                a = self.audit({"e1": self.pdf("r.pdf", f"see {token} for details")})
                self.assertFalse(a["ok"])
                self.assertEqual(a["no_resource_id_files"], [])
                self.assertIn("zero-units-resource-id-unparsed", a["zero_unit_files"][0])

    def test_resource_id_token_in_raw_bytes_refuses(self) -> None:
        a = self.audit({"e1": self.pdf("r.pdf", "plain words only", raw_extra=b"(backup_77) Tj")})
        self.assertFalse(a["ok"])
        self.assertIn("zero-units-resource-id-unparsed", a["zero_unit_files"][0])

    def test_empty_text_layer_refuses(self) -> None:
        for layer in ("", "   \n\t "):
            with self.subTest(layer=layer):
                a = self.audit({"e1": self.pdf("r.pdf", layer)})
                self.assertFalse(a["ok"])
                self.assertIn("zero-units-empty-text", a["zero_unit_files"][0])

    def test_by_content_not_name(self) -> None:
        good, bad = "only user_5 is named", "names support_1"
        for fid, name in (("evidence_18", "account_history_report_20260718.pdf"), ("zz", "renamed.bin")):
            with self.subTest(fid=fid):
                self.assertTrue(self.audit({fid: self.pdf(name, good)})["ok"])
                self.assertFalse(self.audit({fid: self.pdf(name, bad)})["ok"])
        # a ".pdf" name without PDF content is not a text-layer document: refuses as zero units
        (self.ds / "fake.pdf").write_text("only user_5 is named", encoding="utf-8")
        a = self.audit({"e9": "fake.pdf"})
        self.assertFalse(a["ok"])
        self.assertEqual(a["zero_unit_files"], ["e9:zero-units:fake.pdf"])

    def test_structured_file_without_tokens_still_refuses(self) -> None:
        (self.ds / "x.json").write_text(json.dumps({"collection": "c", "records": [{"resource_id": "x"}]}))
        a = self.audit({"e1": "x.json"})
        self.assertFalse(a["ok"])

    def test_extractor_raising_refuses(self) -> None:
        self.pdf("r.pdf", "x")
        a = eg.audit_extraction(recorder([], {"e1": "r.pdf"}), [], self.ds, pdf_text=lambda p: 1 / 0)
        self.assertFalse(a["ok"])
        self.assertIn("zero-units-unreadable:ZeroDivisionError", a["zero_unit_files"][0])

    def test_units_present_means_not_listed(self) -> None:
        a = self.audit({"e1": self.pdf("r.pdf", "no ids")}, units=[U("e1", "pdf:x")])
        self.assertEqual(a["no_resource_id_files"], [])


class TestInstrumentLogLines(unittest.TestCase):
    def test_swallowed_json_error_surfaces_and_patches_restored(self) -> None:
        def parse_line(line: str) -> dict:  # mimics logparse: swallows the JSON error
            return {"raw": line.rstrip("\n"), "kv": {}}

        def parse_log(path, fid, cap):  # type: ignore[no-untyped-def]
            return [ext.parse_line(x) for x in ('2026-09-01T00:00:00Z {"event":"ok"}',
                                                 '2026-09-01T00:00:01Z {"event":"trunc',
                                                 "2026-09-01T00:00:02Z event=kv")]

        def extract_all():  # type: ignore[no-untyped-def]
            ext.parse_log(None, "evidence_06", "t")
            return [U("evidence_06", "log:x")], {"evidence_06": {"file_path": "a.log"}}, []

        ext = types.SimpleNamespace(parse_line=parse_line, parse_log=parse_log)
        sol = types.SimpleNamespace(extract_all=extract_all)
        with eg.instrument(sol, ext) as rec:
            sol.extract_all()
        self.assertIs(ext.parse_line, parse_line)
        self.assertIs(sol.extract_all, extract_all)
        self.assertEqual(len(rec.log_line_failures), 1)
        self.assertTrue(rec.log_line_failures[0].startswith("evidence_06:log-json-failed:"))
        a = eg.audit_extraction(rec, [], Path("/nonexistent"))
        self.assertFalse(a["ok"])


class TestCheckProducer(unittest.TestCase):
    def test_statuses(self) -> None:
        h = "c" * 64
        chk = lambda rec: eg.check_producer(rec, pred_sha256=h)  # noqa: E731
        self.assertEqual(chk(None)["status"], "no-producer-record")
        self.assertEqual(chk({})["status"], "no-producer-record")
        good = {"evidence_skipped": ["e4:png-model-needed"], "evidence_failures": [], "output_sha256": h}
        ok = chk(good)
        self.assertEqual((ok["status"], ok["allowed_skips"]), ("ok", ["e4:png-model-needed"]))
        self.assertEqual(chk(dict(good, evidence_skipped=["e5:unknown-json"]))["status"], "refused")
        self.assertEqual(chk(dict(good, evidence_skipped=[], evidence_failures=["e58:zero-units:x"]))["status"],
                         "refused")
        self.assertEqual(chk({"evidence_skipped": ["e4:png-model-needed"]})["status"], "unverified")
        self.assertEqual(chk({"evidence_skipped": ["e5:unknown"]})["status"], "refused")
        rec = chk(dict(good, evidence_skip_count=1, evidence_no_resource_id_files=["e18"]))
        self.assertEqual((rec["status"], rec["skip_count"], rec["no_resource_id_files"]), ("ok", 1, ["e18"]))


class TestReportsTakeOnlyCheckedRuns(unittest.TestCase):
    """T51: an unchecked run is listed by ID and reason only; none of its numbers appear."""

    def test_render(self) -> None:
        from evaluation.numbers_md import render
        from evaluation.scorer import score_case

        from .fixtures import gold, incomplete_example, row

        g = gold("case_a", "INCOMPLETE", incomplete_example())
        ok_cases = [score_case(row("case_a", "INCOMPLETE", incomplete_example()), g)]
        bad_cases = [score_case(row("case_a", "COMPLETE", incomplete_example()[:1]), g)] * 7
        from evaluation.scorer import aggregate
        base = {"kind": "score", "command": "x", "description": "d", "coherence": {"hard": 0, "soft": 0}}
        runs = {
            "run-ok": {**base, "run_id": "run-ok", "created_at": "1", "aggregate": aggregate(ok_cases), "cases": ok_cases,
                       "producer_check": {"status": "ok", "reasons": [], "allowed_skips": ["e4:png-model-needed"],
                                          "no_resource_id_files": ["e18"], "skip_count": 1},
                       "prev_run": "run-old", "flips": [{"case_id": "case_a", "metric": "row_exact", "prev": False, "now": True}]},
            "run-old": {**base, "run_id": "run-old", "created_at": "0", "aggregate": aggregate(bad_cases), "cases": bad_cases},
            "run-unv": {**base, "run_id": "run-unv", "created_at": "2", "aggregate": aggregate(bad_cases), "cases": bad_cases,
                        "producer_check": {"status": "unverified", "reasons": ["predates"], "allowed_skips": [],
                                           "no_resource_id_files": [], "skip_count": 0}},
        }
        with tempfile.TemporaryDirectory() as t:
            for rid, sc in runs.items():
                (Path(t) / rid).mkdir()
                (Path(t) / rid / "score.json").write_text(json.dumps(sc), encoding="utf-8")
            (Path(t) / "run-ok" / "config.json").write_text(json.dumps({  # T72: re-checked at render time
                "producer": {"evidence_skipped": [], "evidence_failures": [], "output_sha256": "a" * 64},
                "pred_sha256": "a" * 64, "config_hash": "0" * 16, "scorer_code_sha256": "0" * 16,
                "model_ids": [], "paid_model_calls": 0}), encoding="utf-8")
            text = render(Path(t))
        self.assertIn("| `run-ok` | 1/1 |", text)
        self.assertNotIn("0/7", text)            # the unchecked runs' status count
        self.assertNotIn("| `run-old`", text)
        self.assertNotIn("| `run-unv`", text)
        self.assertIn("- `run-old`: scored before the producer check existed", text)
        self.assertIn("- `run-unv`: producer check unverified: predates", text)
        self.assertIn("not shown here (that run is excluded below)", text)
        self.assertNotIn("row_exact False->True", text)
        self.assertIn("`e18`", text)
