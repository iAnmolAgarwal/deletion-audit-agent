"""The three generated reports (evaluation, usage, metrics.json), built from synthetic run folders.

Every expected count below is computed by hand in the comments next to it, from the rows the
test writes, never by calling the report code. Synthetic data only: case IDs in the 9xxxx range
(or the DEV IDs with made-up one-step answers from ``run_dirs.write_gold``), fictional resource
IDs, no dataset file and no real gold. Lock probes use synthetic files (T48).
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from evaluation import custom_cases, evaluation_report, report_spec, reports, run_metrics, usage_report
from evaluation.agent_report import ReportRefused, load_run
from evaluation.split import DEV_IDS, HOLDOUT_IDS
from evaluation.tests import run_dirs as rd

CAVEAT = "Synthetic caveat for the report tests: made after the answers were read; holdout scores are optimistic."
K = [f"{i:x}" * 64 for i in range(1, 8)]  # seven 64-hex keys: '111..', '222..', ...
MODEL = "claude-sonnet-5-5"  # priced at $2 input and $10 output per million tokens (prices.py)


def usage(inp: int, out: int) -> dict[str, Any]:
    return {"cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "input_tokens": inp,
            "output_tokens": out, "service_tier": "standard"}


def flat(inp: int, out: int) -> dict[str, int]:
    return {"cache_creation.ephemeral_1h_input_tokens": 0, "cache_creation.ephemeral_5m_input_tokens": 0,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "input_tokens": inp, "output_tokens": out}


def call(run_id: str, key: str, event: str, outcome: str = "ok", *, cost: float = 0.0, u: dict[str, int] | None = None,
         error_class: str | None = None) -> dict[str, Any]:
    return {"attempt": 1, "cost_usd": cost, "detail": "", "error_class": error_class, "event": event,
            "from_cache": event == "cache_hit", "key": key, "outcome": outcome, "request_id": None,
            "run_id": run_id, "status": None, "stop_reason": "end_turn", "usage": u or {}}


class World:
    """Temporary runs/, cache/, gold, fixtures, split.json and notes for one test."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="reports-test-"))
        self.runs = self.tmp / "runs"
        self.cache = self.tmp / "cache"
        self.fixtures = self.tmp / "fixtures"
        for d in (self.runs, self.cache / "replies", self.fixtures):
            d.mkdir(parents=True)
        (self.cache / "ledger.jsonl").write_text("", encoding="utf-8")
        self.gold = self.tmp / "gold.csv"
        rd.write_gold(self.gold)
        self.split = self.tmp / "split.json"
        self.split.write_text(json.dumps({"created": CAVEAT, "dev": sorted(DEV_IDS), "holdout": sorted(HOLDOUT_IDS)}),
                              encoding="utf-8")
        self.decisions = self.tmp / "DECISIONS.md"
        self.decisions.write_text("\n".join([
            "| ID | Decision | Basis |", "|---|---|---|",
            "| T27 | **Rule twenty-seven, quoted.** More text. | basis |",
            "| T39 | **Rule thirty-nine, quoted.** | basis |",
            "| T53 | **Rule fifty-three, quoted.** | basis |",
            "| T58 | **DEV shortfall accepted.** The lost row is case_01's account step. | basis |",
            "| T60 | **Defaults kept.** Additions: (1) one; (2) two; (3) the edited-copy limit is listed. | basis |",
        ]) + "\n", encoding="utf-8")
        self.proposal = self.tmp / "PROPOSAL.md"
        self.proposal.write_text("# P\n\n## The limit, stated plainly\nFirst sentence. Second sentence. Third.\n",
                                 encoding="utf-8")
        self.ledger = self.tmp / "notes" / "improvements.json"
        self.ledger.parent.mkdir()
        self.ledger.write_text(json.dumps({"entries": []}), encoding="utf-8")
        self.publish_dir = self.tmp / "publish"
        self.publish_dir.mkdir()

    def ctx(self) -> evaluation_report.Context:
        return evaluation_report.Context(runs_root=self.runs, gold_path=self.gold, fixtures_root=self.fixtures,
                                         split_json=self.split, decisions_md=self.decisions,
                                         holdout_proposal_md=self.proposal, cache_root=self.cache,
                                         access_log=self.runs / "HOLDOUT_ACCESS.log", test_ids=frozenset(),
                                         improvements_json=self.ledger, repo_root=self.tmp,
                                         publish_dir=self.publish_dir, test_runner=lambda ids, root: {})

    def dev_run(self, run_id: str, **kw: Any) -> Path:
        """A DEV run: gold's answers except case_01 gets an extra step and case_02 a wrong status."""
        rows = rd.dev_rows()
        rows["case_01"] = ("COMPLETE", [rd.step("account_01"), dict(rd.step("search_01"), step_no=2)])
        rows["case_02"] = ("INCOMPLETE", rows["case_02"][1])
        d = rd.write_run(self.runs, run_id, rows, [rd.case(c) for c in rows], **kw)
        (d / "calls.jsonl").write_text("", encoding="utf-8")  # the pipeline always writes one, even empty
        return d

    def spec(self, **over: Any) -> report_spec.ReportSpec:
        raw: dict[str, Any] = {"report_id": "rep-1", "final_run": "dev-a", "dev_run": "dev-a", "coherence": False}
        raw.update(over)
        return report_spec.spec_from_mapping(raw)

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.w = World()

    def tearDown(self) -> None:
        self.w.close()

    def build(self, spec: report_spec.ReportSpec) -> dict[str, Any]:
        return reports.build_all(spec, self.w.ctx(), command="test")


class TestEvaluationReport(Base):
    def test_dev_counts_match_hand_computed(self) -> None:
        self.w.dev_run("dev-a")
        b = self.build(self.w.spec())
        p = b["evaluation"]["dev"]["published"]
        # 22 DEV cases; only case_02's status differs -> 21/22.
        self.assertEqual((p["status_accuracy"]["n"], p["status_accuracy"]["of"]), (21, 22))
        # case_01 (extra step) and case_02 (status) are not row exact -> 20/22.
        self.assertEqual(p["row_exact"]["n"], 20)
        # every gold step is matched (22 tp); case_01 adds one predicted step -> pred 23, gold 22.
        self.assertEqual((p["step"]["tp"], p["step"]["pred"], p["step"]["gold"]), (22, 23, 22))
        self.assertEqual([c["case_id"] for c in b["evaluation"]["dev"]["not_row_exact"]], ["case_01", "case_02"])
        md = b["evaluation_md"]
        self.assertIn("| case | status accuracy (a: unparseable row's status credited) | 21/22 (0.9545) |", md)
        self.assertIn("runs/dev-a/output.csv", md)

    def test_limitations_quote_rulings_and_check_named_dev_case(self) -> None:
        self.w.dev_run("dev-a")
        lims = {x["label"]: x for x in self.build(self.w.spec())["evaluation"]["limitations"]}
        self.assertEqual(lims["T27"]["quote"], "Rule twenty-seven, quoted.")
        self.assertEqual(lims["T60 (3)"]["quote"], "(3) the edited-copy limit is listed")
        self.assertEqual(lims["Holdout lock limit (T96)"]["quote"], "First sentence. Second sentence.")
        # the T58 row names case_01, which the DEV run gets wrong (extra step)
        self.assertEqual(lims["T58"]["dev_check"]["named_cases"], {"case_01": "not row-exact"})

    def test_dev_history_flips(self) -> None:
        rd.write_run(self.w.runs, "dev-0", rd.dev_rows(), [rd.case(c) for c in rd.dev_rows()])
        self.w.dev_run("dev-a")
        hist = self.build(self.w.spec(dev_history=["dev-0"]))["evaluation"]["dev_history"]
        self.assertEqual([h["run_id"] for h in hist], ["dev-0", "dev-a"])
        flips = {(f["case_id"], f["metric"]) for f in hist[1]["flips"]}
        # dev-0 is all exact; dev-a breaks case_01 (row exact, order) and case_02 (status, row exact)
        self.assertEqual(flips, {("case_01", "row_exact"), ("case_01", "order_exact"),
                                 ("case_02", "status_ok"), ("case_02", "row_exact")})


class TestCustomCases(Base):
    def write_fixture(self, rel: str, mark: str, rows: dict[str, tuple[str, list[dict[str, Any]]]] | None = None,
                      assertions: dict[str, Any] | None = None) -> None:
        d = self.w.fixtures / rel
        d.mkdir(parents=True)
        (d / "EXPECTED.md").write_text(f"# {rel}\n\n**Tests:** a made-up family.\n{mark}\n", encoding="utf-8")
        if rows is not None:
            rd.write_csv(d / "expected_output.csv", rows)
        if assertions is not None:
            (d / "expected_assertions.json").write_text(json.dumps({"cases": assertions}), encoding="utf-8")

    def setUp(self) -> None:
        super().setUp()
        self.write_fixture("FX1_one", "**G8 custom eval case:** yes.", {"case_95001": ("COMPLETE", [rd.step("a_1")])})
        self.write_fixture("red/RX2_two", "**Custom eval case:** **yes, case_95012.** *A correct system does X.*",
                           {"case_95011": ("COMPLETE", [rd.step("a_11")]),
                            "case_95012": ("COMPLETE", [rd.step("a_12")])})
        self.write_fixture("FX3_not", "**G8 custom eval case:** no (a candidate).",
                           {"case_95031": ("COMPLETE", [rd.step("a_31")])})
        self.write_fixture("FX4_assert", "**Custom eval case:** yes.",
                           assertions={"case_95041": {"deletion_status_never": ["COMPLETE"], "never_cite": ["ev_9"],
                                                      "extra_key": 1}})

    def test_marks_are_read_from_files(self) -> None:
        found = [(c.folder, c.case_id) for c in custom_cases.discover(self.w.fixtures)]
        self.assertEqual(found, [("FX1_one", "case_95001"), ("FX4_assert", "case_95041"),
                                 ("red/RX2_two", "case_95012")])
        rx = [c for c in custom_cases.discover(self.w.fixtures) if c.case_id == "case_95012"][0]
        self.assertEqual(rx.statement, "A correct system does X.")

    def test_scored_apart_from_dev(self) -> None:
        self.w.dev_run("dev-a")
        rd.write_run(self.w.runs, "fx1-run", {"case_95001": ("COMPLETE", [rd.step("a_1")])}, [rd.case("case_95001")])
        bad = [dict(rd.step("a_41", "REPORT_REMAINING_RECORD", "ev_1"), phase="FINDING", state="PRESENT")]
        rd.write_run(self.w.runs, "fx4-run", {"case_95041": ("INCOMPLETE", bad)}, [rd.case("case_95041")])
        b = self.build(self.w.spec(custom_runs={"FX1_one": "fx1-run", "FX4_assert": "fx4-run"}))
        c = b["evaluation"]["custom"]
        # 3 marked; FX1 row exact and FX4 assertions pass (INCOMPLETE, cites ev_1 only) -> 2 scored,
        # 2 passed; RX2 has no run -> 1 not run
        self.assertEqual((c["marked"], c["scored"], c["not_run"], c["passed"]), (3, 2, 1, 2))
        fx4 = [x for x in c["cases"] if x["case_id"] == "case_95041"][0]
        self.assertEqual(fx4["not_checked"], ["extra_key"])
        # DEV is untouched by the custom runs: still 22 cases, and no custom ID among them
        self.assertEqual(b["evaluation"]["dev"]["cases"], 22)
        self.assertEqual(b["evaluation"]["dev"]["pred_cases_not_in_gold"], 0)
        md = b["evaluation_md"]
        dev_part = md.split("## 5. Custom eval cases")[0]
        self.assertNotIn("case_950", dev_part)
        self.assertIn("## 5. Custom eval cases (reported apart from DEV and holdout)", md)


class TestAgentAndHoldoutSections(Base):
    def test_unwired_runs_say_empty_not_zero(self) -> None:
        rows = rd.dev_rows()
        d = rd.write_run(self.w.runs, "dev-a", rows, [rd.case(c, rd.ABSENT) for c in rows], vision=rd.ABSENT)
        (d / "calls.jsonl").write_text("", encoding="utf-8")
        b = self.build(self.w.spec(arms={"dev": {"A+": "dev-a"}}))
        self.assertTrue(b["evaluation"]["agent"]["availability"]["unwired"])
        self.assertIn("**Empty until G7 is wired, not zero:**", b["evaluation_md"])
        self.assertEqual(b["failures"], [])

    def test_wired_runs_have_counts(self) -> None:
        rows = rd.dev_rows()
        cases = [rd.case(c) for c in rows]
        cases[0] = rd.case("case_01", rd.agent(tool_calls=[rd.tool("query_evidence")]))
        rd.write_run(self.w.runs, "dev-a", rows, cases)
        b = self.build(self.w.spec(arms={"dev": {"A+": "dev-a"}}))
        av = b["evaluation"]["agent"]["availability"]
        self.assertEqual((av["unwired"], av["other_errors"]), ([], []))
        # one of 22 cases calls a tool other than audit_case
        self.assertEqual(b["evaluation"]["agent"]["report"]["n_tools"]["dev"]["A+"]["cases_with_tool_call"], 1)
        self.assertIn("| query_evidence | 1 |", b["evaluation_md"])

    def test_holdout_not_run_carries_caveat(self) -> None:
        self.w.dev_run("dev-a")
        md = self.build(self.w.spec())["evaluation_md"]
        part = md.split("## 9. Holdout")[1].split("## 10.")[0]
        self.assertIn(CAVEAT, part)
        self.assertIn("**Not run yet.**", part)

    def test_holdout_complete_record_renders_with_caveat(self) -> None:
        self.w.dev_run("dev-a")
        d = self.w.runs / "holdout-20261025T1800"
        d.mkdir()
        rec = {"run_id": "holdout-20261025T1800", "status": "complete", "caveat": CAVEAT,
               "caveat_source": "notes/split.json 'created'", "freeze_tag": "freeze-20261025",
               "freeze_commit": "0" * 40,
               "attempts": [{"engine_unlocked_at": "t1", "gold_unlocked_at": "t2"}], "holdout_cases": 10,
               "headline": {"status_accuracy": {"n": 9, "of": 10, "rate": 0.9}}, "budget": {}}
        (d / "holdout_record.json").write_text(json.dumps(rec), encoding="utf-8")
        md = self.build(self.w.spec())["evaluation_md"]
        part = md.split("## 9. Holdout")[1].split("## 10.")[0]
        self.assertIn(CAVEAT, part)
        self.assertIn("holdout-20261025T1800", part)
        self.assertIn("| Status accuracy | 9/10 (0.9000) |", part)
        self.assertNotIn("Not run yet", part)


class TestRefusals(Base):
    def test_unchecked_final_run_is_refused(self) -> None:
        self.w.dev_run("dev-a")
        rd.write_run(self.w.runs, "final-x", {"case_96001": ("COMPLETE", [rd.step("a")])}, [rd.case("case_96001")],
                     bad_hash=True)
        spec = self.w.spec(final_run="final-x")
        with self.assertRaises(ReportRefused):
            self.build(spec)
        path = self.w.tmp / "spec.json"
        path.write_text(json.dumps({"report_id": "rep-1", "final_run": "final-x", "dev_run": "dev-a",
                                    "coherence": False}), encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(reports.main(["--spec", str(path)], ctx=self.w.ctx()), 3)
        self.assertTrue((self.w.runs / "rep-1" / "refused.json").exists())
        self.assertFalse((self.w.runs / "rep-1" / "evaluation_report.md").exists())
        self.assertIn("output-mismatch", err.getvalue())

    def test_usage_run_without_output_is_refused(self) -> None:
        """T107: a usage run with no output.csv is refused; there is no calls-only exception."""
        self.w.dev_run("dev-a")
        (self.w.runs / "probe").mkdir()
        (self.w.runs / "probe" / "calls.jsonl").write_text("", encoding="utf-8")
        with self.assertRaises(ReportRefused):
            self.build(self.w.spec(usage={"run": "probe"}))
        with self.assertRaises(ValueError):  # the old flag is now an unknown key
            self.w.spec(usage={"run": "probe", "calls_only": True})

    def test_spec_rejects_unknown_key_and_self_reference(self) -> None:
        with self.assertRaises(ValueError):
            self.w.spec(finall_run="x")
        with self.assertRaises(ValueError):
            self.w.spec(report_id="dev-a")


class TestUsageAttribution(Base):
    def setUp(self) -> None:
        super().setUp()
        w = self.w
        # Cache entries (reply usage -> cost at $2/M in, $10/M out):
        # K0 bought by buy-a: 1000 in, 800 out -> 0.002 + 0.008 = 0.010
        # K1 bought by buy-a: 5000 in, 1000 out -> 0.010 + 0.010 = 0.020
        # K2 bought by buy-b: 1000 in, 300 out -> 0.002 + 0.003 = 0.005
        # K4 bought by final: 500 in, 200 out -> 0.001 + 0.002 = 0.003
        self.entries = {K[0]: ("buy-a", 1000, 800, 0.010), K[1]: ("buy-a", 5000, 1000, 0.020),
                        K[2]: ("buy-b", 1000, 300, 0.005), K[4]: ("final", 500, 200, 0.003)}
        for key, (buyer, i, o, _) in self.entries.items():
            p = w.cache / "replies" / key[:2] / f"{key}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"key": key, "model": MODEL, "bought_by_run": buyer, "usage": usage(i, o),
                                     "written_at": "2026-10-25T00:00:00Z"}), encoding="utf-8")
        self.logs = {
            "buy-a": [call("buy-a", K[0], "send", cost=0.010, u=flat(1000, 800)),
                      call("buy-a", K[1], "send", cost=0.020, u=flat(5000, 1000))],
            "buy-b": [call("buy-b", K[3], "send", "retry", error_class="RateLimitError"),
                      call("buy-b", K[2], "send", cost=0.005, u=flat(1000, 300))],
            "final": [call("final", K[0], "cache_hit"), call("final", K[1], "cache_hit"),
                      call("final", K[2], "cache_hit"), call("final", K[0], "cache_hit"),
                      call("final", K[4], "send", cost=0.003, u=flat(500, 200)),
                      call("final", K[5], "send", "give_up", error_class="APIConnectionError")],
        }
        for rid, lines in self.logs.items():
            (w.runs / rid).mkdir()
            (w.runs / rid / "calls.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        self.ledger = [(K[0], 0.010), (K[1], 0.020), (K[3], 0.0), (K[2], 0.005), (K[4], 0.003), (K[5], 0.0)]
        self.write_ledger()

    def write_ledger(self) -> None:
        (self.w.cache / "ledger.jsonl").write_text("".join(
            json.dumps({"key": k, "cost_usd": c, "reserved_usd": 0.03, "usage": {}}) + "\n" for k, c in self.ledger),
            encoding="utf-8")

    def usage_of(self) -> dict[str, Any]:
        return usage_report.build_usage("final", runs_root=self.w.runs, cache_root=self.w.cache)

    def test_cache_hits_summed_by_buying_run(self) -> None:
        u = self.usage_of()
        a = u["a_replies_used"]
        by = a["by_buying_run"]
        # buy-a: K0 (used twice) and K1 -> 2 replies, 3 uses, 6000 in, 1800 out, $0.030
        self.assertEqual((by["buy-a"]["replies"], by["buy-a"]["uses"]), (2, 3))
        self.assertEqual((by["buy-a"]["input_tokens"], by["buy-a"]["output_tokens"]), (6000, 1800))
        self.assertAlmostEqual(by["buy-a"]["cost_settled_usd"], 0.030, places=9)
        # buy-b: K2 -> 1 reply, 1000 in, 300 out, $0.005; final: K4 -> $0.003
        self.assertEqual((by["buy-b"]["replies"], by["buy-b"]["input_tokens"]), (1, 1000))
        self.assertAlmostEqual(by["buy-b"]["cost_settled_usd"], 0.005, places=9)
        self.assertAlmostEqual(by["final"]["cost_settled_usd"], 0.003, places=9)
        # total: 4 replies, $0.038, re-priced equal
        self.assertEqual(a["total"]["replies"], 4)
        self.assertAlmostEqual(a["total"]["cost_settled_usd"], 0.038, places=9)
        self.assertAlmostEqual(a["total"]["cost_repriced_usd"], 0.038, places=9)
        self.assertEqual(usage_report.failures_found(u), [])

    def test_totals_and_per_request_averages(self) -> None:
        a = self.usage_of()["a_replies_used"]
        # (a) input 1000+5000+1000+500 = 7500, output 800+1000+300+200 = 2300, total 9800, over 4 replies:
        #     1875.0 in, 575.0 out, 2450.0 total; $0.038 / 4 = $0.0095
        self.assertEqual(a["total"]["total_tokens"], 9800)
        self.assertEqual(a["per_reply"]["total_tokens"], 2450.0)
        self.assertAlmostEqual(a["per_reply"]["cost_usd"], 0.0095, places=9)
        u = self.usage_of()
        rows = {f: v for f, v, _ in usage_report.organiser_rows(u)}
        self.assertIn("(a) total 9800; 1875.0 input, 575.0 output, 2450.0 total tokens and $0.009500 per reply",
                      rows["Total and average tokens per request"])
        # (b) one successful send of 500 in + 200 out, at $0.003
        self.assertIn("(b) total 700; 500.0 input, 200.0 output, 700.0 total tokens and $0.003000 per successful "
                      "send", rows["Total and average tokens per request"])
        self.assertIn("(b) the run made 2 send attempts (1 returned a reply) and 4 cache reads", rows["Model calls"])

    def test_own_calls(self) -> None:
        b = self.usage_of()["b_own_calls"]
        # final sent K4 (ok, $0.003) and K5 (give_up, $0); four cache hits
        self.assertEqual((b["send_attempts"], b["sends_ok"], b["cache_hits"]), (2, 1, 4))
        self.assertAlmostEqual(b["cost_usd"], 0.003, places=9)
        self.assertEqual(b["failures"], {"send:give_up:APIConnectionError:-": {"count": 1, "cost_usd": 0.0}})
        self.assertEqual(b["per_model"][MODEL]["sends_ok"], 1)

    def test_ledger_mismatch_is_reported(self) -> None:
        self.ledger[1] = (K[1], 0.025)  # the ledger says K1 cost $0.025; buy-a's call log says $0.020
        self.write_ledger()
        u = self.usage_of()
        fails = usage_report.failures_found(u)
        self.assertTrue(any(K[1][:12] in f and "settled_vs_ledger" in f for f in fails), fails)
        self.assertFalse(u["cross_checks"]["project_ledger"]["agree"])
        self.assertIn("**DISAGREE**", usage_report.render_usage(u, report_id="r", created_at="t", command="c"))

    def test_line_of_another_run_is_left_out(self) -> None:
        p = self.w.runs / "final" / "calls.jsonl"
        p.write_text(p.read_text(encoding="utf-8") + json.dumps(call("other", K[6], "cache_hit")) + "\n",
                     encoding="utf-8")
        u = self.usage_of()
        self.assertEqual(u["a_replies_used"]["replies_used"], 4)
        self.assertTrue(any("names run other" in x for x in u["call_log_problems"]))


class TestMetrics(Base):
    def write(self, run_id: str, statuses: list[str], lines: list[dict[str, Any]] | None = None) -> None:
        ids = [f"case_97{i:03d}" for i in range(len(statuses))]
        rows = {c: (s, [] if s == "NOT_APPLICABLE" else [rd.step("a_" + c[5:])]) for c, s in zip(ids, statuses,
                                                                                               strict=True)}
        cases = lines or [rd.case(c) for c in ids]
        rd.write_run(self.w.runs, run_id, rows, cases)

    def test_drift_and_agent_metrics_hand_computed(self) -> None:
        # previous: 3 COMPLETE, 5 INCOMPLETE, 2 NOT_APPLICABLE -> 30 / 50 / 20 %
        self.write("prev", ["COMPLETE"] * 3 + ["INCOMPLETE"] * 5 + ["NOT_APPLICABLE"] * 2)
        ids = [f"case_97{i:03d}" for i in range(10)]
        lines = [rd.case(c) for c in ids]
        for ln in lines:
            ln.update({"open_questions": [], "answers": []})
        lines[0]["agent"] = rd.agent(tool_calls=[rd.tool("query_evidence")])
        lines[1]["agent"] = rd.agent(tool_calls=[rd.tool("read_image")],
                                     answers_rejected=[{"oq_id": "q_b", "reason": "EVIDENCE_AFTER_AUDIT"}])
        lines[1].update({"open_questions": ["q_a", "q_b"], "answers": ["q_a"]})
        lines[2].update({"row_state": "FAILED_CLOSED", "failed_closed": "POST_AUDIT_ONLY_FINDING"})
        # now: 6 COMPLETE, 4 INCOMPLETE -> 60 / 40 / 0 %; gaps +30, -10, -20 -> drift 30 points
        self.write("now", ["COMPLETE"] * 6 + ["INCOMPLETE"] * 4, lines)
        now, prev = load_run(self.w.runs, "now"), load_run(self.w.runs, "prev")
        m = run_metrics.compute(now, prev)
        self.assertEqual(m["status_mix_drift"]["value"], 30.0)
        self.assertEqual(m["status_mix_drift"]["by_status"]["NOT_APPLICABLE"]["gap_pts"], -20.0)
        self.assertTrue(m["status_mix_drift"]["fires"])
        # 2 of 10 cases call a tool -> 0.2 > 0.05
        self.assertEqual((m["tool_fire_rate"]["value"], m["tool_fire_rate"]["fires"]), (0.2, True))
        # q_b is posed and unanswered -> 1
        self.assertEqual(m["unresolved_open_questions"]["value"], 1)
        # one EVIDENCE_AFTER_AUDIT rejection + one POST_AUDIT_ONLY_FINDING row -> 2
        self.assertEqual(m["rejected_post_audit_evidence"]["value"], 2)
        self.assertEqual((m["fail_closed_rows"]["value"], m["fail_closed_rows"]["by_reason"]),
                         (1, {"POST_AUDIT_ONLY_FINDING": 1}))

    def test_unwired_run_gives_null_not_zero(self) -> None:
        ids = [f"case_97{i:03d}" for i in range(4)]
        self.write("g5", ["COMPLETE"] * 4, [rd.case(c, rd.ABSENT) for c in ids])
        doc = run_metrics.build_metrics([("final", load_run(self.w.runs, "g5"), None)], report_id="r",
                                        created_at="t", command="c")
        m = doc["runs"][0]["metrics"]
        for k in ("tool_fire_rate", "unresolved_open_questions"):
            self.assertIsNone(m[k]["value"])
            self.assertIsNone(m[k]["fires"])
        self.assertEqual(m["rejected_post_audit_evidence"]["lower_bound"], 0)
        self.assertEqual(m["fail_closed_rows"]["value"], 0)
        self.assertIn("final:tool_fire_rate", doc["alerts_not_computed"])
        self.assertEqual(doc["source_runs"], {"final": {"run": "g5", "previous_run": None}})


class TestCommand(Base):
    def test_one_command_writes_three_reports_under_runs(self) -> None:
        self.w.dev_run("dev-a")
        path = self.w.tmp / "spec.json"
        path.write_text(json.dumps({"report_id": "rep-1", "final_run": "dev-a", "dev_run": "dev-a",
                                    "coherence": False}), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            status = reports.main(["--spec", str(path)], ctx=self.w.ctx())
        self.assertEqual(status, 0)
        out = self.w.runs / "rep-1"
        for name in ("evaluation_report.md", "usage_report.md", "metrics.json", "reports_build.json"):
            self.assertTrue((out / name).is_file(), name)
        met = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(met["source_runs"]["final"]["run"], "dev-a")
        # the run's own pipeline-written metrics.json is untouched
        own = json.loads((self.w.runs / "dev-a" / "metrics.json").read_text(encoding="utf-8"))
        self.assertNotIn("kind", own)

    def test_report_id_of_a_producer_run_is_refused(self) -> None:
        self.w.dev_run("dev-a")
        rd.write_run(self.w.runs, "busy", rd.dev_rows(), [rd.case(c) for c in rd.dev_rows()])
        path = self.w.tmp / "spec.json"
        path.write_text(json.dumps({"report_id": "busy", "final_run": "dev-a", "dev_run": "dev-a",
                                    "coherence": False}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reports.main(["--spec", str(path)], ctx=self.w.ctx()), 3)


class TestUsageNamespaces(unittest.TestCase):
    """The usage report reads both reply namespaces, as the pipeline does."""

    def test_reply_namespaces_match_the_pipeline(self) -> None:
        from deletion_audit import config
        self.assertEqual(usage_report.REPLY_NAMESPACES, tuple(config.REPLY_NAMESPACES))


if __name__ == "__main__":
    unittest.main()
