"""The improvements ledger (T113), the headline block (T111 (2)), the organiser's usage fields and --publish.

Synthetic data only: a temporary git repository holds the anchored files, the decisions table
and the runs (``run_dirs`` rows on the DEV IDs with made-up one-step answers, scored against
``run_dirs.write_gold``'s synthetic gold). Every expected value is written out by hand in the test,
never taken from the code under test.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import subprocess
import unittest
from pathlib import Path
from typing import Any

from evaluation import headline, improvements, reports, usage_report
from evaluation.agent_report import load_run
from evaluation.tests import run_dirs as rd
from evaluation.tests.test_reports import World

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "-c", "commit.gpgsign=false"]
VERIFY_MD = "\n".join([
    "# A verifier report", "", "## Findings", "",
    "**1. MAJOR: the widget drops a row.**", "- **Where:** `widget.py:1`.", "",
    "**2. MINOR: a label is misspelt.**", "- **(a) The engine:** the first part.", "- **(b) The gate:** the second.",
    "", "## Notes", "- **(a) The engine:** a later, unrelated line.", ""])
LOG = "\n".join([
    "## [2026-10-25T10:00:00+05:30] Some turn", "", "User Prompt (verbatim, secrets redacted):",
    "Review checkpoint 9: the policy is fine. (a) a silent drop must fail closed.", "",
    "## [2026-10-25T11:00:00+05:30] A later turn", "", "User Prompt (verbatim, secrets redacted):", "Carry on.", ""])
FIXTURE_MD = "# RX9: a made-up red-team family\n\n**Attacks:** a decoy.\n\n- `case_95901`: a fictional person.\n"
TEST_PY = '''import unittest


class Good(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(True)

    def test_fail(self):
        self.assertTrue(False)

    @unittest.skip("not a pass")
    def test_skipped(self):
        pass


def test_module_level():
    pass
'''


def git(root: Path, *args: str) -> str:
    return subprocess.run([*GIT, "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


class LedgerWorld(World):
    """World plus a git repository at its root holding a verifier report, a log and a test file."""

    def __init__(self) -> None:
        super().__init__()
        t = self.tmp
        (t / "notes" / "verify").mkdir(parents=True)
        (t / "notes" / "verify" / "v.md").write_text(VERIFY_MD, encoding="utf-8")
        (t / "log.txt").write_text(LOG, encoding="utf-8")
        fx = t / "code" / "tests" / "fixtures" / "redteam" / "RX9_decoy"
        fx.mkdir(parents=True)
        (fx / "EXPECTED.md").write_text(FIXTURE_MD, encoding="utf-8")
        (t / "code" / "faketests").mkdir()
        (t / "code" / "faketests" / "__init__.py").write_text("", encoding="utf-8")
        (t / "code" / "faketests" / "test_fake.py").write_text(TEST_PY, encoding="utf-8")
        self.decisions.write_text(self.decisions.read_text(encoding="utf-8")
                                  + "| T90 | **The widget fix, quoted.** More. | basis |\n", encoding="utf-8")
        subprocess.run([*GIT, "init", "-q", str(t)], check=True)
        git(t, "add", "-A")
        git(t, "commit", "-q", "-m", "fixture commit")
        self.commit = git(t, "rev-parse", "HEAD")
        self.passing: set[str] = {"faketests.test_fake.Good.test_pass"}

    def ctx(self) -> Any:
        return dataclasses.replace(super().ctx(), test_runner=self.runner)

    def runner(self, ids: Any, root: Path) -> dict[str, dict[str, Any]]:
        return {i: {"ok": i in self.passing, "ran": 1} for i in ids}

    def env(self, **over: Any) -> improvements.LedgerEnv:
        kw: dict[str, Any] = {"repo_root": self.tmp, "runs_root": self.runs, "gold_path": self.gold,
                              "fixtures_root": self.tmp / "code" / "tests" / "fixtures",
                              "decisions_md": self.decisions, "run_tests": self.runner}
        kw.update(over)
        return improvements.LedgerEnv(**kw)

    def check(self, *entries: dict[str, Any], **over: Any) -> dict[str, Any]:
        self.ledger.write_text(json.dumps({"entries": list(entries)}), encoding="utf-8")
        return improvements.check_ledger(self.ledger, self.env(**over))


def entry(eid: str = "I01", *, failure: dict[str, Any] | None = None, fix: dict[str, Any] | None = None,
          evidence: dict[str, Any] | None = None, commit: str = "") -> dict[str, Any]:
    return {"id": eid,
            "failure": failure or {"kind": "verifier", "path": "notes/verify/v.md", "anchor": "**1. MAJOR:"},
            "fix": fix or {"ruling": "T90", "commit": commit},
            "evidence": evidence or {"test": "code/faketests/test_fake.py::Good.test_pass"}}


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.w = LedgerWorld()

    def tearDown(self) -> None:
        self.w.close()

    def one(self, **kw: Any) -> dict[str, Any]:
        kw.setdefault("commit", self.w.commit[:7])
        over = kw.pop("env", {})
        got: dict[str, Any] = self.w.check(entry(**kw), **over)["entries"][0]
        return got


class TestLedgerEntries(Base):
    def test_good_entry_quotes_the_anchored_line_and_passes(self) -> None:
        e = self.one()
        self.assertEqual((e["status"], e["reasons"]), ("ok", []))
        self.assertEqual(e["failure"]["quote"], ["**1. MAJOR: the widget drops a row.**"])
        self.assertEqual(e["failure"]["quote_line"], 5)  # line 5 of VERIFY_MD
        self.assertEqual(e["fix"]["ruling_quote"], "The widget fix, quoted.")
        self.assertEqual(e["fix"]["commit_sha"], self.w.commit)
        self.assertEqual(e["fix"]["commit_subject"], "fixture commit")
        self.assertEqual(e["evidence"]["test"]["unittest_id"], "faketests.test_fake.Good.test_pass")
        self.assertIs(e["evidence"]["test"]["file_differs_from_head"], False)

    def test_line_locator_is_searched_inside_the_anchored_section_only(self) -> None:
        # "(a) The engine:" occurs twice in the file, once under finding 2 and once under "## Notes"
        e = self.one(failure={"kind": "verifier", "path": "notes/verify/v.md", "anchor": "**2. MINOR:",
                              "line": "**(a) The engine:**"})
        self.assertEqual(e["status"], "ok", e["reasons"])
        self.assertEqual(e["failure"]["quote"], ["**2. MINOR: a label is misspelt.**",
                                                 "**(a) The engine:** the first part."])
        self.assertEqual(e["failure"]["quote_line"], 9)

    def test_review_anchor_is_the_log_heading_of_the_turn(self) -> None:
        e = self.one(failure={"kind": "review", "path": "log.txt", "anchor": "2026-10-25T10:00:00+05:30"})
        # heading text, then the first content line (the "User Prompt ...:" label is skipped)
        self.assertEqual(e["failure"]["quote"], ["[2026-10-25T10:00:00+05:30] Some turn",
                                                 "Review checkpoint 9: the policy is fine. (a) a silent drop must "
                                                 "fail closed."])
        e = self.one(failure={"kind": "review", "path": "log.txt", "anchor": "2026-10-25T10:00:00+05:30",
                              "line": "(a) a silent drop"})
        self.assertEqual(e["failure"]["quote"][1], "(a) a silent drop must fail closed.")

    def test_pending_commit_is_pending_and_a_problem(self) -> None:
        d = self.w.check(entry(commit="PENDING"))
        self.assertEqual(d["entries"][0]["status"], "pending")
        self.assertEqual(improvements.problems(d), ["improvements I01: fix commit PENDING (not yet committed)"])
        md = "\n".join(improvements.render_section(d))
        self.assertIn("commit **PENDING**: not counted as an improvement made", md)
        self.assertIn("fix not yet committed (PENDING): 1", md)

    def test_refusals(self) -> None:
        cases: list[tuple[dict[str, Any], str]] = [
            ({"failure": {"kind": "verifier", "path": "notes/verify/missing.md", "anchor": "x"}}, "does not exist"),
            ({"failure": {"kind": "verifier", "path": "notes/verify/v.md", "anchor": "no such text"}},
             "matches 0 lines"),
            ({"failure": {"kind": "verifier", "path": "notes/verify/v.md", "anchor": "**(a) The engine:**"}},
             "matches 2 lines"),
            ({"failure": {"kind": "verifier", "path": "dataset/sample_output.md", "anchor": "x"}},
             "not a citable file"),
            ({"failure": {"kind": "verifier", "path": "../outside.md", "anchor": "x"}}, "without '..'"),
            ({"failure": {"kind": "oracle", "path": "notes/verify/v.md", "anchor": "**1. MAJOR:"}}, "failure kind"),
            ({"failure": {"kind": "redteam", "path": "notes/verify/v.md", "anchor": "**1. MAJOR:"}},
             "needs 'case'"),
            ({"failure": {"kind": "redteam", "path": "notes/verify/v.md", "anchor": "**1. MAJOR:",
                          "case": "case_95901"}}, "is not named in"),
            ({"failure": {"kind": "review", "path": "log.txt", "anchor": "2026-10-25T09:59:59+05:30"}},
             "matches 0 lines"),
            ({"commit": "deadbeef"}, "not in history"),
            ({"commit": "main"}, "must be a hex commit ID"),
            ({"fix": {"ruling": "T999", "commit": "PENDING"}}, "has no row"),
            ({"evidence": {"test": "code/faketests/test_fake.py::Good.test_absent"}}, "not found"),
            ({"evidence": {"test": "code/faketests/nope.py::Good.test_pass"}}, "does not exist"),
            ({"evidence": {"test": "code/faketests/test_fake.py::Good.test_fail"}}, "did not pass"),
            ({"evidence": {"test": "code/faketests/test_fake.py::Good.test_pass", "metric": {}}}, "exactly one"),
            ({"evidence": {"metric": {"name": "vibes", "scope": "dev", "before_run": "a", "after_run": "b"}}},
             "unknown metric name"),
        ]
        for kw, want in cases:
            with self.subTest(want=want, kw=kw):
                e = self.one(**kw)
                self.assertEqual(e["status"], "refused")
                self.assertTrue(any(want in r for r in e["reasons"]), e["reasons"])

    def test_ruling_clause_is_quoted_from_its_place_in_the_row(self) -> None:
        # the T90 row's cell is "**The widget fix, quoted.** More."
        e = self.one(fix={"ruling": "T90", "commit": self.w.commit, "clause": "More."})
        self.assertEqual((e["status"], e["fix"]["ruling_quote"]), ("ok", "More."))
        e = self.one(fix={"ruling": "T90", "commit": self.w.commit, "clause": "Not in the row"})
        self.assertTrue(any("occurs 0 times" in r for r in e["reasons"]), e["reasons"])

    def test_redteam_case_named_in_the_fixture(self) -> None:
        e = self.one(failure={"kind": "redteam", "path": "code/tests/fixtures/redteam/RX9_decoy/EXPECTED.md",
                              "anchor": "# RX9:", "case": "case_95901"})
        self.assertEqual(e["status"], "ok", e["reasons"])
        self.assertEqual(e["failure"]["quote"], ["RX9: a made-up red-team family", "**Attacks:** a decoy."])

    def test_unknown_keys_and_duplicate_ids_are_refused(self) -> None:
        a = entry(commit=self.w.commit)
        a["description"] = "typed text is not allowed"
        d = self.w.check(a, entry(commit=self.w.commit))
        self.assertTrue(any("unknown key" in r for r in d["entries"][0]["reasons"]))
        self.assertTrue(any("unique" in r for r in d["entries"][1]["reasons"]))

    def test_render_quotes_and_refusals(self) -> None:
        d = self.w.check(entry(commit=self.w.commit), entry("I02", commit="deadbeef"))
        md = "\n".join(improvements.render_section(d))
        self.assertIn('"**1. MAJOR: the widget drops a row.**"', md)
        self.assertIn("improvements made (fix committed, evidence checked): 1", md)
        self.assertIn("- **REFUSED:** commit deadbeef is not in history (git cat-file -e)", md)
        self.assertIn("checked by running this one test at build time", md)


class TestRealRunner(Base):
    def test_subprocess_runner_reports_each_test(self) -> None:
        env = self.w.env(run_tests=None)
        got = improvements.subprocess_tests(env)(
            ["faketests.test_fake.Good.test_pass", "faketests.test_fake.Good.test_fail",
             "faketests.test_fake.Good.test_skipped", "faketests.test_fake.Good.test_absent"], env.code_root)
        self.assertEqual({k: v["ok"] for k, v in got.items()},
                         {"faketests.test_fake.Good.test_pass": True, "faketests.test_fake.Good.test_fail": False,
                          "faketests.test_fake.Good.test_skipped": False,
                          "faketests.test_fake.Good.test_absent": False})
        self.assertEqual(got["faketests.test_fake.Good.test_fail"]["failures"], 1)

    def test_module_level_function_resolves(self) -> None:
        t, why = improvements.resolve_test(self.w.env(), "code/faketests/test_fake.py::test_module_level")
        self.assertIsNone(why)
        assert t is not None
        self.assertEqual(t["unittest_id"], "faketests.test_fake.test_module_level")


class TestMetricEvidence(Base):
    def write(self, run_id: str, wrong: tuple[str, ...] = (), **kw: Any) -> None:
        rows = rd.dev_rows()
        for c in wrong:
            rows[c] = ("INCOMPLETE", rows[c][1])
        rd.write_run(self.w.runs, run_id, rows, [rd.case(c) for c in rows], **kw)

    def metric(self, name: str, before: str, after: str, scope: str = "dev") -> dict[str, Any]:
        return self.one(evidence={"metric": {"name": name, "scope": scope, "before_run": before,
                                             "after_run": after}})

    def test_improved_unchanged_and_worse_are_all_shown(self) -> None:
        self.write("before", ("case_02", "case_03"))   # 20/22 row exact
        self.write("after", ("case_03",))              # 21/22
        self.write("same", ("case_03",))               # 21/22 again
        e = self.metric("row_exact", "before", "after")
        m = e["evidence"]["metric"]
        self.assertEqual((e["status"], m["before"]["shown"], m["after"]["shown"], m["moved"]),
                         ("ok", "20/22", "21/22", "improved"))
        self.assertEqual(self.metric("row_exact", "after", "same")["evidence"]["metric"]["moved"], "unchanged")
        worse = self.metric("status_accuracy", "after", "before")
        self.assertEqual((worse["status"], worse["evidence"]["metric"]["moved"]), ("ok", "worse"))
        md = "\n".join(improvements.render_section(self.w.check(entry(
            commit=self.w.commit, evidence={"metric": {"name": "status_accuracy", "scope": "dev",
                                                       "before_run": "after", "after_run": "before"}}))))
        self.assertIn("before 21/22 on `after`, after 20/22 on `before`: **worse**", md)

    def test_fail_closed_rows_on_test_scope_is_a_change_not_a_judgement(self) -> None:
        self.write("before")
        rows = rd.dev_rows()
        cases = [rd.case(c) for c in rows]
        cases[0] = rd.case("case_01", row_state="FAILED_CLOSED", failed_closed="NOTHING_FOUND")
        rd.write_run(self.w.runs, "after", rows, cases)
        m = self.metric("fail_closed_rows", "before", "after", scope="test")["evidence"]["metric"]
        self.assertEqual((m["before"]["shown"], m["after"]["shown"], m["moved"]), ("0 of 22 rows", "1 of 22 rows",
                                                                                  "changed"))

    def test_unchecked_or_missing_run_and_bad_scope_are_refused(self) -> None:
        self.write("good")
        self.write("unchecked", bad_hash=True)
        for args, want in [(("row_exact", "good", "unchecked"), "is unchecked"),
                           (("row_exact", "good", "nowhere"), "has no folder"),
                           (("row_exact", "good", "good"), "two different runs"),
                           (("row_exact", "good", "unchecked", "test"), "has no scope"),
                           (("custom_passed", "good", "unchecked", "custom:nowhere"), "no marked custom")]:
            with self.subTest(args=args):
                e = self.metric(*args)
                self.assertEqual(e["status"], "refused")
                self.assertTrue(any(want in r for r in e["reasons"]), e["reasons"])


class TestHeadlineAndUsageFields(Base):
    def build(self, **spec: Any) -> dict[str, Any]:
        self.w.dev_run("dev-a")
        return reports.build_all(self.w.spec(**spec), self.w.ctx(), command="test")

    def test_headline_is_first_in_both_reports_with_run_ids_and_not_run_yet(self) -> None:
        b = self.build()
        for md in (b["evaluation_md"], b["usage_md"]):
            self.assertLess(md.index("## Headline"), md.index("Generated "))
            # World.dev_run: case_02 has a wrong status; case_01 an extra step -> 21/22 and 20/22
            self.assertIn("| DEV status accuracy | 21/22 (0.9545) | `dev-a` |", md)
            self.assertIn("| DEV row exact | 20/22 (0.9091) | `dev-a` |", md)
            # 21 COMPLETE + 1 INCOMPLETE rows; no FAILED_CLOSED record
            self.assertIn("| Test rows by status | COMPLETE 21, INCOMPLETE 1 (of 22) | `dev-a` |", md)
            self.assertIn("| Test FAILED_CLOSED rows | 0 (by reason {}) | `dev-a` |", md)
            self.assertIn("| Tools on vs off (DEV) | not run yet: the spec names no tools_off arm on DEV | none |", md)
            self.assertIn("| Holdout | not run yet (no completed holdout record under runs/) | none |", md)
            self.assertIn("Synthetic caveat for the report tests", md)
        # the run used no model reply and sent nothing: tool use and cost are not run yet, never 0
        for which in ("audit_case", "other read-only tools"):
            self.assertIn(f"| Tool-use rate: {which} | not run yet: the run used no model reply (0 replies used, 0 "
                          "sends), so the model never ran |", b["evaluation_md"])
        self.assertIn("| Total cost: replies the final output used | not run yet: the run used no model reply",
                      b["usage_md"])

    def test_tool_use_rate_is_measured_once_the_model_ran(self) -> None:
        rows = rd.dev_rows()
        cases = [rd.case(c) for c in rows]
        cases[0] = rd.case("case_01", rd.agent(tool_calls=[rd.tool("inspect_evidence")]))
        cases[1] = rd.case("case_02", rd.agent(audit_case_calls=0))
        d = rd.write_run(self.w.runs, "dev-a", rows, cases)
        (d / "calls.jsonl").write_text("", encoding="utf-8")
        b = reports.build_all(self.w.spec(), self.w.ctx(), command="test")
        us = json.loads(json.dumps(b["usage"]))
        us["a_replies_used"]["replies_used"] = 1  # as if one cached reply had been used
        h = headline.build_headline(b["evaluation"], us, load_run(self.w.runs, "dev-a"))
        tu = h["tool_use"]
        # 21 of the 22 cases call audit_case (case_02 does not); one calls inspect_evidence; none an unknown tool
        self.assertEqual((tu["cases_with_audit_case"], tu["cases_with_read_only_tool"], tu["cases_with_unknown_tool"],
                          tu["cases"]), (21, 1, 0, 22))
        md = "\n".join(headline.render_headline(h))
        self.assertIn("| Tool-use rate: audit_case | 21/22 (0.9545) cases called audit_case; mode A+", md)
        self.assertIn("| Tool-use rate: other read-only tools | 1/22 (0.0455) cases called another read-only tool "
                      "(get_request_context, inspect_evidence, lookup_identity, list_activity); mode A+", md)
        self.assertIn("| `dev-a` |", md)

    def test_unknown_tool_name_is_counted_apart_from_both_rates(self) -> None:
        rows = rd.dev_rows()
        cases = [rd.case(c) for c in rows]
        cases[0] = rd.case("case_01", rd.agent(tool_calls=[rd.tool("query_evidence")]))
        d = rd.write_run(self.w.runs, "dev-a", rows, cases)
        (d / "calls.jsonl").write_text("", encoding="utf-8")
        b = reports.build_all(self.w.spec(), self.w.ctx(), command="test")
        us = json.loads(json.dumps(b["usage"]))
        us["a_replies_used"]["replies_used"] = 1
        h = headline.build_headline(b["evaluation"], us, load_run(self.w.runs, "dev-a"))
        # query_evidence is not one of the four read-only tools: 0 read-only cases, 1 unknown
        self.assertEqual((h["tool_use"]["cases_with_read_only_tool"], h["tool_use"]["cases_with_unknown_tool"]), (0, 1))
        self.assertIn("**1 case(s) called a tool outside both sets**", "\n".join(headline.render_headline(h)))

    def test_unwired_run_tool_use_is_not_run_yet(self) -> None:
        rows = rd.dev_rows()
        d = rd.write_run(self.w.runs, "dev-a", rows, [rd.case(c, rd.ABSENT) for c in rows], vision=rd.ABSENT)
        (d / "calls.jsonl").write_text("", encoding="utf-8")
        b = reports.build_all(self.w.spec(), self.w.ctx(), command="test")
        for which in ("audit_case", "other read-only tools"):
            self.assertIn(f"| Tool-use rate: {which} | not run yet: the run's cases.jsonl records carry no agent "
                          "block |", b["evaluation_md"])

    def test_every_organiser_field_is_present_and_filled(self) -> None:
        md = self.build()["usage_md"]
        section = md.split("## Required fields (notes/ORGANISER_README.md:97, read as data)")[1].split("\n## ")[0]
        for f in usage_report.ORGANISER_FIELDS:
            rows = [x for x in section.splitlines() if x.startswith(f"| {f} | ")]
            self.assertEqual(len(rows), 1, f)
            cells = [c.strip() for c in rows[0].strip("|").split(" | ")]
            self.assertEqual(len(cells), 3, rows[0])
            self.assertTrue(cells[1] and cells[2], rows[0])
            for sec in ("(a)", "(b)", "Price basis", "Providers and models"):
                if sec in cells[2]:
                    self.assertIn(f"## {sec}", md)
        self.assertEqual(len(usage_report.ORGANISER_FIELDS), 7)
        # the field list's own items, as worded in the organiser's line 97
        for words in ("final full-dataset run", "model providers and names", "model calls", "input and output tokens",
                      "total and average tokens per request", "estimated total and per-request cost",
                      "per-model and overall totals"):
            self.assertIn(words, [f.lower() for f in usage_report.ORGANISER_FIELDS])
        # World's test_ids is empty, so the 22-row run is not the full dataset, and the report says so
        self.assertIn("the final run wrote 22 rows for 0 test requests (**not the full dataset**)", md)


class TestPublish(Base):
    def run_main(self, spec: dict[str, Any], *extra: str, test_ids: frozenset[str] | None = None) -> tuple[int, str]:
        path = self.w.tmp / "spec.json"
        path.write_text(json.dumps({"report_id": "rep-1", "final_run": "dev-a", "dev_run": "dev-a",
                                    "coherence": False, **spec}), encoding="utf-8")
        ctx = self.w.ctx()
        if test_ids is not None:
            ctx = dataclasses.replace(ctx, test_ids=test_ids)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            status = reports.main(["--spec", str(path), *extra], ctx=ctx)
        return status, err.getvalue()

    def published(self) -> list[str]:
        return sorted(p.name for p in self.w.publish_dir.iterdir())

    def setUp(self) -> None:
        super().setUp()
        self.w.dev_run("dev-a")
        self.full = frozenset(rd.dev_rows())

    def test_without_publish_nothing_reaches_the_deliverable_folder(self) -> None:
        status, _ = self.run_main({"final": True}, test_ids=self.full)
        self.assertEqual((status, self.published()), (0, []))
        self.assertTrue((self.w.runs / "rep-1" / "evaluation_report.md").is_file())

    def test_refusals(self) -> None:
        self.w.ledger.write_text(json.dumps({"entries": [entry(commit="PENDING")]}), encoding="utf-8")
        status, err = self.run_main({"final": True}, "--publish", test_ids=self.full)
        self.assertEqual((status, self.published()), (3, []))
        self.assertIn("PENDING", err)
        self.w.ledger.write_text(json.dumps({"entries": []}), encoding="utf-8")
        for spec, ids, want in [({}, self.full, '"final": true'),
                                ({"final": True}, frozenset(), "not the full dataset")]:
            with self.subTest(want=want):
                status, err = self.run_main(spec, "--publish", test_ids=ids)
                self.assertEqual((status, self.published()), (3, []))
                self.assertIn(want, err)
        build = json.loads((self.w.runs / "rep-1" / "reports_build.json").read_text(encoding="utf-8"))
        self.assertTrue(build["publish"]["refused"])

    def test_publish_writes_both_reports_equal_to_the_run_copies(self) -> None:
        self.w.ledger.write_text(json.dumps({"entries": [entry(commit=self.w.commit)]}), encoding="utf-8")
        status, err = self.run_main({"final": True}, "--publish", test_ids=self.full)
        self.assertEqual(status, 0, err)
        self.assertEqual(self.published(), ["evaluation_report.md", "usage_report.md"])
        for name in self.published():
            self.assertEqual((self.w.publish_dir / name).read_bytes(), (self.w.runs / "rep-1" / name).read_bytes())
        build = json.loads((self.w.runs / "rep-1" / "reports_build.json").read_text(encoding="utf-8"))
        self.assertEqual(len(build["publish"]["published"]), 2)
        self.assertIn("## 11. Failures found and improvements made",
                      (self.w.publish_dir / "evaluation_report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
