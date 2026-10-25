"""``evaluation_report.md``: generated from named run artifacts only, never typed by hand.

Sections, and what each reads:

1. **Inputs:** every run the spec names, its producer check and output sha256.
2. **Protocol:** ``notes/split.json`` (method, seed, its ``created`` caveat) and ``split.py``; the
   holdout access log's line count by ``what``.
3. **DEV accuracy** (case/status, row, step, field, sequence, citations) of the spec's DEV run:
   ``scorer.score_predictions`` on its ``output.csv`` against DEV gold from ``gold.load_gold``
   with its defaults (DEV only), plus the cases that are not row-exact and how they differ.
4. **DEV per run:** the same headline for each run of ``dev_history``, with per-case flips
   against the run before it (``runs.flips``).
5. **Custom eval cases (C6):** ``custom_cases``; marks read from each fixture's ``EXPECTED.md``,
   scored against its expectation files, reported apart from DEV and holdout.
5b. **Validation set:** ``validation_set``; every fixture folder with an expectation file, per arm
   of the spec's ``validation`` key, with pass counts per fixture, the run IDs, producer checks
   and replay misses; apart from DEV and holdout.
6. **Agent sections:** ``agent_report.build_report`` and ``render_markdown`` on the spec's arms
   (tool-sequence histogram, N and M, arm deltas on DEV, fixtures and differing test rows, the
   intent table, vision). Runs written before G7 have no agent blocks: the section says so.
7. **Validator and FAILED_CLOSED counts by reason:** the final and DEV runs' pipeline-written
   ``metrics.json``, cross-checked against ``cases.jsonl``.
8. **Coherence and drift** (optional): ``coherence.check_file`` on the final and DEV outputs;
   ``drift.drift_table`` of the final output against DEV gold.
9. **Holdout:** "not run yet" until a completed ``holdout_record.json`` exists under ``runs/``,
   then ``holdout_run.holdout_section(record)``. Always led by ``split.json``'s caveat, read from
   the file (``holdout_run.read_caveat``). No holdout gold is read here.
10. **Limitations already ruled:** each quoted from its ruling in ``notes/DECISIONS.md`` (or the
    holdout proposal), with the count the final run's artifacts give where one applies.
11. **Failures found and improvements made** (T111, T113): ``improvements.check_ledger`` on
    ``code/evaluation/improvements.json``; every quote read from the anchored file, every test run, every
    metric computed from two producer-checked runs (``improvements`` docstring).

The **headline block** (``headline``) is built by ``reports.build_all`` from this data and the
usage report's, and rendered first.
"""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import agent_report, coherence, custom_cases, drift, holdout_run, improvements, runs, validation_set
from .agent_report import CASES_FILE, METRICS_FILE, OUTPUT_FILE, LoadedRun
from .freeze_check import is_failed_closed
from .gold import GoldCase, load_gold, load_requests
from .paths import HOLDOUT_ACCESS_LOG, REPO_ROOT, RUNS, SAMPLE_OUTPUT, SAMPLE_REQUESTS, SPLIT_JSON, TEST_REQUESTS
from .report_spec import ReportSpec
from .scorer import score_predictions
from .split import DEV_IDS, HOLDOUT_IDS, SPLIT_METHOD, SPLIT_SEED

DRIFT_THRESHOLD_PTS = 15.0
SAMPLE = 15


@dataclass(frozen=True)
class Context:
    """Where the generator reads. Production uses the defaults; tests pass temporary paths."""

    runs_root: Path = RUNS
    gold_path: Path = SAMPLE_OUTPUT
    fixtures_root: Path = agent_report.FIXTURES_ROOT
    split_json: Path = SPLIT_JSON
    decisions_md: Path = REPO_ROOT / "notes" / "DECISIONS.md"
    holdout_proposal_md: Path = REPO_ROOT / "notes" / "HOLDOUT_RUN_PROPOSAL.md"
    cache_root: Path = REPO_ROOT / "cache"
    access_log: Path = HOLDOUT_ACCESS_LOG
    test_ids: frozenset[str] | None = None
    improvements_json: Path = REPO_ROOT / "code" / "evaluation" / "improvements.json"
    repo_root: Path = REPO_ROOT
    publish_dir: Path = REPO_ROOT / "code" / "evaluation"
    test_runner: improvements.TestRunner | None = None   # None: run each ledger test in a subprocess

    def ledger_env(self) -> improvements.LedgerEnv:
        """The ledger checks' paths (the same runs, gold and fixtures as the report)."""
        return improvements.LedgerEnv(repo_root=self.repo_root, runs_root=self.runs_root, gold_path=self.gold_path,
                                      fixtures_root=self.fixtures_root, decisions_md=self.decisions_md,
                                      run_tests=self.test_runner)


@dataclass(frozen=True)
class Limitation:
    """One ruled limitation: where its ruling is, which clause to quote, and what to count."""

    label: str
    source: str            # "decisions" or "holdout_proposal"
    ruling: str            # the T-number row, or the proposal heading
    summary: str           # our one-line reading, no figures
    clause: str | None = None   # regex for the clause to quote; default the row's first bold span
    stage: str | None = None    # cases.jsonl account.stage to count on the final run
    dev_cases: bool = False     # check the case IDs the ruling names on the DEV run


LIMITATIONS: tuple[Limitation, ...] = (
    Limitation("T27", "decisions", "T27", "An account's identity may come from a log line after audit_at; its state "
               "and every citation still come only from evidence at or before audit_at. No DEV case tests it.",
               stage="T27_LATER_LOOKUP"),
    Limitation("T39", "decisions", "T39", "Remaining account ties are decided by an openly arbitrary, stable order; "
               "each such pick is a coin flip and is flagged.", stage="S5_TIE_PICK"),
    Limitation("T53 (with D17)", "decisions", "T53", "Account tie-breaks (D17) and identifier-free analytics use "
               "generator timing, a data-derived correlation rather than a spec rule.", stage="S4_FINGERPRINT"),
    Limitation("T58", "decisions", "T58", "The DEV shortfall the developer accepted for the rulings as implemented; "
               "the measured DEV result is shown beside it.", dev_cases=True),
    Limitation("T60 (3)", "decisions", "T60", "The gold identity guard catches the gold file by identity or exact "
               "bytes; an edited copy is not caught.", clause=r"\(3\)[^.;|]*"),
    Limitation("Holdout lock limit (T96)", "holdout_proposal", "## The limit, stated plainly",
               "The unlock phrase is a constant in the source: the lock stops accidental access and logs deliberate "
               "access, but cannot stop a deliberate call."),
)


# ---- small readers ----
def _rate(n: int, of: int) -> dict[str, Any]:
    return {"n": n, "of": of, "rate": n / of if of else None}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _raw_lines(run: LoadedRun) -> list[Mapping[str, Any]]:
    try:
        text = (run.run_dir / CASES_FILE).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, Mapping):
            out.append(raw)
    return out


def _run_row(run: LoadedRun, role: str) -> dict[str, Any]:
    return {"role": role, "run_id": run.run_id, "producer_check": run.producer_check["status"],
            "output_sha256": run.producer_check["pred_sha256"], "rows": len(run.output.rows) if run.output else None,
            "producer_command": run.producer.get("command"), "created_at": run.producer.get("created_at")}


# ---- sections ----
def protocol(ctx: Context) -> dict[str, Any]:
    """The split, its caveat and the holdout access log (counts by ``what`` only)."""
    split = _read_json(ctx.split_json) or {}
    lines: list[Any] = []
    if ctx.access_log.exists():
        for x in ctx.access_log.read_text(encoding="utf-8").splitlines():
            try:
                lines.append(json.loads(x))
            except json.JSONDecodeError:
                lines.append({"what": "<unreadable line>"})
    return {"split_json": "notes/split.json", "created": split.get("created"), "method": SPLIT_METHOD,
            "seed": SPLIT_SEED, "dev_size": len(DEV_IDS), "holdout_size": len(HOLDOUT_IDS),
            "split_json_matches_split_py": set(split.get("dev") or []) == set(DEV_IDS)
            and set(split.get("holdout") or []) == set(HOLDOUT_IDS),
            "access_log_lines": len(lines),
            "access_log_by_what": dict(sorted(Counter(str(x.get("what")) if isinstance(x, Mapping) else "<bad>"
                                                      for x in lines).items()))}


def dev_scores(run: LoadedRun, gold: Mapping[str, GoldCase]) -> dict[str, Any]:
    """The DEV run's full published block and per-case differences (counts only)."""
    assert run.output is not None
    res = score_predictions(run.output.rows, gold)
    inexact = [{"case_id": c["case_id"], "pred_status": c["pred_status"], "gold_status": c["gold_status"],
                "missing_steps": len(c["diff"]["missing_steps"]), "extra_steps": len(c["diff"]["extra_steps"]),
                "field_mismatches": len(c["diff"]["field_mismatches"]), "order_exact": c["order_exact"]}
               for c in res["cases"] if not c["row_exact"]]
    return {"run_id": run.run_id, "pred_sha256": run.producer_check["pred_sha256"],
            "producer_command": run.producer.get("command"), "published": res["aggregate"]["published"],
            "cases": res["aggregate"]["cases"], "not_row_exact": inexact,
            "pred_cases_not_in_gold": res["pred_cases_not_in_gold"], "case_scores": res["cases"]}


def dev_history(ids: Sequence[str], loaded: Mapping[str, LoadedRun],
                gold: Mapping[str, GoldCase]) -> list[dict[str, Any]]:
    """Headline per DEV run, oldest first, with flips against the run before it."""
    out: list[dict[str, Any]] = []
    prev_cases: list[dict[str, Any]] | None = None
    prev_id: str | None = None
    for rid in ids:
        d = dev_scores(loaded[rid], gold)
        p = d["published"]
        out.append({"run_id": rid, "created_at": loaded[rid].producer.get("created_at"),
                    "status": p["status_accuracy"], "row_exact": p["row_exact"], "steps_exact": p["steps_exact"],
                    "step_f1": p["step"]["f1"], "sequence_exact": p["sequence_exact"],
                    "pairwise_order": p["sequence_pairwise_order"],
                    "flips_vs": prev_id, "flips": None if prev_cases is None else runs.flips(prev_cases,
                                                                                             d["case_scores"])})
        prev_cases, prev_id = d["case_scores"], rid
    return out


def validator_counts(run: LoadedRun) -> dict[str, Any]:
    """The pipeline's validator and FAILED_CLOSED counts, cross-checked against ``cases.jsonl``."""
    m = _read_json(run.run_dir / METRICS_FILE)
    if not isinstance(m, Mapping):
        return {"run_id": run.run_id, "error": f"{METRICS_FILE} missing or unreadable"}
    fc_raw, val_raw = m.get("failed_closed"), m.get("validator")
    fc: Mapping[str, Any] = fc_raw if isinstance(fc_raw, Mapping) else {}
    val: Mapping[str, Any] = val_raw if isinstance(val_raw, Mapping) else {}
    problems = []
    if run.view.record_errors:
        problems.append(f"{len(run.view.record_errors)} record error(s) in {CASES_FILE}: cross-check not done")
        from_cases = None
    else:
        fcs = [c for c in run.view.cases.values() if is_failed_closed(c)]
        from_cases = {"count": len(fcs), "by_reason": dict(sorted(Counter(c.failed_closed or "ROW_STATE_ONLY"
                                                                          for c in fcs).items()))}
        if fc.get("count") != from_cases["count"] or dict(fc.get("by_reason") or {}) != from_cases["by_reason"]:
            problems.append(f"{METRICS_FILE} failed_closed disagrees with {CASES_FILE}")
    if m.get("output_sha256") != run.producer_check["pred_sha256"]:
        problems.append(f"{METRICS_FILE} output_sha256 differs from the sha256 of {OUTPUT_FILE}")
    return {"run_id": run.run_id, "source": f"runs/{run.run_id}/{METRICS_FILE} (pipeline-written)",
            "cases": m.get("cases"), "by_part": val.get("by_part"),
            "failing_cases": {k: {"count": len(v), "case_ids": list(v)[:SAMPLE]}
                              for k, v in (val.get("failing_cases") or {}).items()},
            "failed_closed": {"count": fc.get("count"), "by_reason": fc.get("by_reason")},
            "failed_closed_from_cases_jsonl": from_cases, "problems": problems}


def _audit_times() -> dict[str, str]:
    times = {cid: r["audit_at"] for cid, r in load_requests(SAMPLE_REQUESTS).items()}
    times.update({cid: r["audit_at"] for cid, r in load_requests(TEST_REQUESTS).items()})
    return times


def coherence_counts(run: LoadedRun, expected_ids: set[str], audit_at: Mapping[str, str],
                     evidence: coherence.EvidenceIndex) -> dict[str, Any]:
    """Hard and soft coherence counts, and hard cases outside FAILED_CLOSED rows (T87 (1))."""
    assert run.output is not None
    s = coherence.summarize(coherence.check_file(run.output, audit_at=audit_at, evidence=evidence,
                                                 expected_ids=expected_ids))
    fc = {c.case_id for c in run.view.cases.values() if is_failed_closed(c)}
    outside = sorted(set(s["hard_cases"]) - fc)
    return {"run_id": run.run_id, "hard": s["hard"], "soft": s["soft"], "by_rule": s["by_rule"],
            "hard_cases": len(s["hard_cases"]), "hard_cases_outside_failed_closed": len(outside),
            "hard_cases_outside_failed_closed_ids": outside[:SAMPLE]}


def holdout_part(spec: ReportSpec, ctx: Context) -> dict[str, Any]:
    """The holdout section's data: the caveat always; the rendered section once a record is complete."""
    settings = dataclasses.replace(holdout_run.default_settings(), runs_root=ctx.runs_root, split_json=ctx.split_json)
    try:
        caveat = holdout_run.read_caveat(settings)
    except holdout_run.HoldoutRefused as exc:
        raise ValueError(f"the holdout section cannot carry its caveat: {exc}") from exc
    records = []
    for p in sorted(ctx.runs_root.glob(f"*/{holdout_run.RECORD_FILE}")):
        rec = _read_json(p)
        records.append((p.parent.name, rec if isinstance(rec, Mapping) else None))
    complete = [(d, r) for d, r in records if r is not None and r.get("status") == "complete"]
    problems = [f"{d}/{holdout_run.RECORD_FILE} is unreadable" for d, r in records if r is None]
    if len(complete) > 1:
        problems.append(f"{len(complete)} completed holdout records exist: {[d for d, _ in complete]}")
    if spec.holdout_run and spec.holdout_run not in [d for d, _ in complete]:
        problems.append(f"the spec names holdout run {spec.holdout_run}, which has no completed record")
    out: dict[str, Any] = {"caveat": caveat, "caveat_source": "notes/split.json 'created'", "problems": problems,
                           "unfinished": [d for d, r in records if r is not None and r.get("status") != "complete"],
                           "run_id": None, "section_md": None}
    if len(complete) == 1 and not problems:
        d, rec = complete[0]
        out["run_id"] = d
        out["caveat_matches_record"] = rec.get("caveat") == caveat
        out["headline"] = rec.get("headline") if isinstance(rec.get("headline"), Mapping) else None
        commit = str(rec.get("freeze_commit") or "")
        out["section_md"] = holdout_run.holdout_section(
            rec, current_head=runs.git_head(), package_changed=package_differs(ctx.repo_root, commit),
            notes=replicate_notes(ctx.runs_root / d))
    return out


def package_differs(repo: Path, commit: str) -> bool | None:
    """Whether ``code/deletion_audit`` differs between ``commit`` and HEAD, by
    ``git diff --quiet <commit> HEAD -- code/deletion_audit`` at generation time (exit 0: identical,
    1: differs); None when git fails or the commit is empty. Reason: the holdout numbers describe the
    frozen commit, so the report must say whether the code that writes ``output.csv`` moved since.
    """
    if not commit:
        return None
    try:
        r = subprocess.run(["git", "-C", str(repo), "diff", "--quiet", commit, "HEAD", "--", "code/deletion_audit"],
                           capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: False, 1: True}.get(r.returncode)


def _jsonl(path: Path) -> list[Mapping[str, Any]] | None:
    """The JSON objects of a JSONL file, or None when it is missing or any line is unreadable."""
    try:
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return None
    return rows if all(isinstance(r, Mapping) for r in rows) else None


def replicate_notes(run_dir: Path) -> list[str]:
    """Generated lines on the holdout run's turn-1 replicate, from its ``calls.jsonl``, ``cases.jsonl``
    and ``regression_vs_engine.json``.

    Reason (domain logic): the turn-1 replicate replays from the cache only (``pipeline`` "the run's
    clients", T88 (1), T97), so a holdout text whose replicate reply the cache does not hold gets no
    second reading; ``agent/loop.py`` then flags ``TURN1_REPLICATES_DISAGREE``, because a missing
    reading counts as a different one. The report must say that nothing disagreed and why no row
    changed. A file that cannot be read gives an explicit line, never "nothing found".
    """
    calls, cases = _jsonl(run_dir / "calls.jsonl"), _jsonl(run_dir / CASES_FILE)
    reg = _read_json(run_dir / "regression_vs_engine.json")
    if calls is None or cases is None or not isinstance(reg, Mapping):
        return [f"- Turn-1 replicate: not reported; `{run_dir.name}`'s calls.jsonl, {CASES_FILE} or "
                "regression_vs_engine.json could not be read."]
    misses = sum(1 for c in calls if c.get("event") == "replay_miss" and c.get("outcome") == "give_up")
    agents = [(str(c.get("case_id")), c.get("agent") if isinstance(c.get("agent"), Mapping) else {}) for c in cases]
    missing = sorted(cid for cid, a in agents if None in (a.get("turn1_replicates") or [None]))
    flagged = sorted(cid for cid, a in agents if "TURN1_REPLICATES_DISAGREE" in (a.get("flags") or []))
    labels = Counter(str(x) for _, a in agents for x in (a.get("turn1_replicates") or []) if x is not None)
    split = sorted(cid for cid, a in agents if len({x for x in (a.get("turn1_replicates") or []) if x is not None}) > 1)
    return [
        f"- **Turn-1 replicate (run `{run_dir.name}`):** {len(missing)} of {len(agents)} cases had no second turn-1 "
        f"intent reading: the replicate replays from the cache only, and the cache held no replicate reply for "
        f"those texts ({misses} `replay_miss` events with outcome `give_up` in `calls.jsonl`). The loop flags "
        f"{len(flagged)} cases `TURN1_REPLICATES_DISAGREE` (`agent/loop.py`: a missing reading counts as a "
        f"different one), although no two readings disagree: {len(split)} cases have two different labels; "
        f"the readings present are {dict(sorted(labels.items()))}.",
        f"- No holdout row changed because of it: {reg.get('changed_rows')} of {reg.get('rows_compared')} rows "
        "differ from the model-free rows (`regression_vs_engine.json`). In `agent/model_changes.py` "
        "`_intent_condition`, a `NOT_APPLICABLE` change needs at least two turn-1 readings, all NOT_DELETION, so "
        "a missing replicate can only block an intent change, never make one; and a deletion reading takes the "
        "same deletion path as the model-free row.",
    ]


def _row_cell(path: Path, ruling: str) -> str | None:
    """The ruling text (second column) of the ``| <ruling> |`` row of a decisions table."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {ruling} |"):
            cells = line.split(" | ")
            return cells[1] if len(cells) > 1 else None
    return None


def _quote(lim: Limitation, ctx: Context) -> tuple[str | None, str]:
    """(quoted ruling text, where it came from)."""
    if lim.source == "holdout_proposal":
        text = ctx.holdout_proposal_md.read_text(encoding="utf-8")
        _, _, after = text.partition(lim.ruling + "\n")
        para = after.strip().split("\n\n")[0].replace("\n", " ")
        sentences = re.split(r"(?<=\.)\s+", para)
        return " ".join(sentences[:2]) or None, f"notes/HOLDOUT_RUN_PROPOSAL.md, \"{lim.ruling.lstrip('# ')}\""
    cell = _row_cell(ctx.decisions_md, lim.ruling)
    src = f"notes/DECISIONS.md {lim.ruling}"
    if cell is None:
        return None, src
    m = re.search(lim.clause, cell) if lim.clause else re.search(r"\*\*(.+?)\*\*", cell)
    if m is None:
        return None, src
    return (m.group(0) if lim.clause else m.group(1)).strip(), src


def limitations(ctx: Context, final: LoadedRun, dev: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each ruled limitation, quoted from its ruling, with the artifact count where one applies."""
    stages = Counter(str((x.get("account") or {}).get("stage")) for x in _raw_lines(final)
                     if isinstance(x.get("account"), Mapping))
    out = []
    for lim in LIMITATIONS:
        quote, src = _quote(lim, ctx)
        item: dict[str, Any] = {"label": lim.label, "summary": lim.summary, "quote": quote, "quote_source": src}
        if lim.stage:
            item["count"] = {"run_id": final.run_id, "measured": f"cases.jsonl account.stage == {lim.stage}",
                             "cases": stages.get(lim.stage, 0), "of": len(final.view.cases)}
        if lim.dev_cases:
            cell = _row_cell(ctx.decisions_md, lim.ruling) or ""
            named = sorted(set(re.findall(r"case_[0-9]+", cell)))
            inexact = {c["case_id"] for c in dev["not_row_exact"]}
            item["dev_check"] = {"run_id": dev["run_id"], "row_exact": dev["published"]["row_exact"],
                                 "named_cases": {c: ("not row-exact" if c in inexact else "row-exact")
                                                 for c in named},
                                 "not_row_exact": sorted(inexact)}
        out.append(item)
    return out


def agent_availability(report: Mapping[str, Any]) -> dict[str, Any]:
    """Which agent sections hold counts, and which are empty because the runs predate G7."""
    unwired: list[str] = []
    other: list[str] = []
    for sec in ("n_tools", "m_answers", "intent", "vision"):
        for role, arms in report[sec].items():
            for arm, v in arms.items():
                if "error" not in v:
                    continue
                errs = v.get("errors") or []
                missing = all(e["problem"].startswith("missing") and e["path"] in (agent_report.AGENT_KEY, "<file>")
                              for e in errs)
                (unwired if missing and errs else other).append(f"{sec}/{role}/{arm} (run {v['run_id']})")
    return {"unwired": unwired, "other_errors": other}


def build_evaluation(spec: ReportSpec, loaded: Mapping[str, LoadedRun], ctx: Context, *,
                     command: str, created_at: str) -> dict[str, Any]:
    """The evaluation report's data. Raises ``agent_report.ReportRefused`` if an arm run is unchecked."""
    gold = load_gold(ctx.gold_path)  # DEV only: the loader's defaults
    final, dev = loaded[spec.final_run], loaded[spec.dev_run]
    roles = [("final", spec.final_run), ("dev", spec.dev_run)]
    roles += [("previous", spec.previous_run)] if spec.previous_run else []
    roles += [("dev_history", r) for r in spec.dev_history]
    roles += [(f"custom:{f}", r) for f, r in spec.custom_runs.items()]
    data: dict[str, Any] = {"report_id": spec.report_id, "kind": "evaluation_report", "created_at": created_at,
                            "command": command, "gold": "DEV only (evaluation.gold.load_gold defaults)",
                            "gold_dev_hash": runs.gold_hash(gold), "scorer_code_sha256": runs.code_hash(),
                            "git_head": runs.git_head(),
                            "inputs": [_run_row(loaded[r], role) for role, r in roles],
                            "protocol": protocol(ctx)}
    d = dev_scores(dev, gold)
    data["dev"] = {k: v for k, v in d.items() if k != "case_scores"}
    hist = [*dict.fromkeys([*spec.dev_history, spec.dev_run])]
    data["dev_history"] = dev_history(hist, loaded, gold)
    data["custom"] = custom_cases.score_custom(custom_cases.discover(ctx.fixtures_root), spec.custom_runs, loaded)
    data["validation"] = validation_set.build_validation(spec.validation, runs_root=ctx.runs_root,
                                                         fixtures_root=ctx.fixtures_root)
    arms = spec.arms
    if arms.dev or arms.test or arms.fixtures:
        ar = agent_report.build_report(arms, report_id=spec.report_id, runs_root=ctx.runs_root,
                                       gold_path=ctx.gold_path, test_ids=ctx.test_ids,
                                       fixtures_root=ctx.fixtures_root, command=command)
        data["agent"] = {"report": ar, "availability": agent_availability(ar),
                         "markdown": agent_report.render_markdown(ar)}
    else:
        data["agent"] = None
    data["validator"] = [validator_counts(final)] + ([validator_counts(dev)] if dev is not final else [])
    if spec.coherence:
        times = _audit_times()
        ev = coherence.load_evidence_index()
        test_ids = set(ctx.test_ids) if ctx.test_ids is not None else set(load_requests(TEST_REQUESTS))
        data["coherence"] = [coherence_counts(final, test_ids, times, ev),
                             coherence_counts(dev, set(DEV_IDS), times, ev)]
    else:
        data["coherence"] = None
    assert final.output is not None
    table = drift.drift_table(final.output.rows, gold, DRIFT_THRESHOLD_PTS)
    data["drift"] = {"run_id": final.run_id, "threshold_pts": DRIFT_THRESHOLD_PTS, "table": table,
                     "flagged": sum(1 for r in table if r["flag"])}
    prev = loaded.get(spec.previous_run or "")
    data["final_vs_previous"] = None if prev is None or prev.output is None else {
        "runs": [final.run_id, prev.run_id], "measured": agent_report.MEASURED["test_rows_differ"],
        **agent_report.rows_differ(final.output, prev.output)}
    data["holdout"] = holdout_part(spec, ctx)
    data["limitations"] = limitations(ctx, final, data["dev"])
    data["improvements"] = improvements.check_ledger(ctx.improvements_json, ctx.ledger_env())
    return data


def problems(data: Mapping[str, Any]) -> list[str]:
    """Cross-check failures to surface in the CLI exit status (agent sections before G7 excluded)."""
    out = [f"validator {v['run_id']}: {p}" for v in data["validator"] for p in v.get("problems", [])]
    out += [f"validator {v['run_id']}: {v['error']}" for v in data["validator"] if "error" in v]
    out += [f"holdout: {p}" for p in data["holdout"]["problems"]]
    if not data["protocol"]["split_json_matches_split_py"]:
        out.append("notes/split.json differs from split.py")
    if data["agent"] and data["agent"]["availability"]["other_errors"]:
        out += [f"agent section error: {x}" for x in data["agent"]["availability"]["other_errors"]]
    out += [f"limitation {x['label']}: ruling text not found in {x['quote_source']}"
            for x in data["limitations"] if x["quote"] is None]
    out += improvements.problems(data["improvements"])
    return out


# ---- Markdown ----
def _r(x: Mapping[str, Any] | None) -> str:
    if not x or not x.get("of"):
        return "n/a"
    return f"{x['n']}/{x['of']} ({x['rate']:.4f})"


def _f(v: Any) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def _demote(md: str, by: int = 2) -> list[str]:
    return [("#" * by + line) if line.startswith("#") else line for line in md.splitlines()]


def _md_dev(L: list[str], d: Mapping[str, Any], command: str) -> None:
    p = d["published"]
    st = p["step"]
    f = p["field_on_matched"]
    L += [f"## 3. DEV accuracy (run `{d['run_id']}`)", "",
          f"Measured by `evaluation.scorer.score_predictions` on `runs/{d['run_id']}/output.csv` (sha256 "
          f"`{str(d['pred_sha256'])[:16]}`) against DEV gold only (`evaluation.gold.load_gold` defaults; "
          f"{d['cases']} cases), inside `{command}`. The output was produced by "
          f"`{d['producer_command'] or 'unknown'}`. Metric definitions: `code/evaluation/scorer.py` docstring.", "",
          "| level | metric | value |", "|---|---|---|",
          f"| case | status accuracy (a: unparseable row's status credited) | {_r(p['status_accuracy'])} |",
          "| case | status accuracy (c: unparseable row counted wrong) | "
          f"{_r(p['status_accuracy_unparseable_wrong'])} |",
          f"| row | row exact (status and parsed steps_json equal) | {_r(p['row_exact'])} |",
          f"| row | steps exact (steps only) | {_r(p['steps_exact'])} |",
          f"| step | P / R / F1 on (phase, operation, system_id, resource_id) | {_f(st['precision'])} / "
          f"{_f(st['recall'])} / {_f(st['f1'])} (tp {st['tp']}, pred {st['pred']}, gold {st['gold']}) |",
          f"| field | state on matched steps | {_r(f['state'])} |",
          f"| field | evidence_id on matched steps | {_r(f['evidence_id'])} |",
          f"| field | step_no on matched steps | {_r(f['step_no'])} |",
          f"| field | all three | {_r(f['all_three'])} |",
          f"| sequence | exact order of step keys | {_r(p['sequence_exact'])} |",
          f"| sequence | pairwise order (concordant pairs of matched steps) | {_r(p['sequence_pairwise_order'])} |",
          f"| citation | evidence_id on cited gold steps | {_r(p['citation_on_cited_steps'])} |",
          f"| citation | citation set exact per case | {_r(p['citation_set_exact'])} |", "",
          "Status confusion (rows gold, columns predicted):", "",
          "| gold \\ predicted | " + " | ".join(next(iter(p["status_confusion"].values()))) + " |",
          "|---|" + "---:|" * len(next(iter(p["status_confusion"].values())))]
    L += [f"| {g} | " + " | ".join(str(n) for n in row.values()) + " |" for g, row in p["status_confusion"].items()]
    L += ["", "Per operation (step P / R / F1):", "", "| operation | tp | pred | gold | P | R | F1 |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {op} | {x['tp']} | {x['pred']} | {x['gold']} | {_f(x['precision'])} | {_f(x['recall'])} | "
          f"{_f(x['f1'])} |" for op, x in p["step_per_operation"].items()]
    L += ["", f"Cases not row-exact ({len(d['not_row_exact'])}):", ""]
    if d["not_row_exact"]:
        L += ["| case | status pred / gold | missing steps | extra steps | field mismatches | order exact |",
              "|---|---|---:|---:|---:|---|"]
        L += [f"| {c['case_id']} | {c['pred_status']} / {c['gold_status']} | {c['missing_steps']} | "
              f"{c['extra_steps']} | {c['field_mismatches']} | {c['order_exact']} |" for c in d["not_row_exact"]]
    else:
        L.append("- none")
    L.append("")


def _md_history(L: list[str], hist: Sequence[Mapping[str, Any]]) -> None:
    L += ["## 4. DEV numbers per run", "", "Each row: `score_predictions` on that run's `output.csv` against DEV "
          "gold, computed in this build. Flips: per-case changes of status_ok, row_exact, order_exact and "
          "citation_set_exact against the row above (`runs.flips`).", "",
          "| run | produced at | status | row exact | steps exact | step F1 | sequence exact | pairwise order "
          "| flips |",
          "|---|---|---|---|---|---|---|---|---|"]
    for h in hist:
        fl = "n/a (first)" if h["flips"] is None else ", ".join(
            f"{x['case_id']} {x['metric']} {x['prev']}->{x['now']}" for x in h["flips"]) or "none"
        L.append(f"| `{h['run_id']}` | {h['created_at']} | {_r(h['status'])} | {_r(h['row_exact'])} | "
                 f"{_r(h['steps_exact'])} | {_f(h['step_f1'])} | {_r(h['sequence_exact'])} | "
                 f"{_r(h['pairwise_order'])} | {fl} |")
    L.append("")


def _md_custom(L: list[str], c: Mapping[str, Any]) -> None:
    L += ["## 5. Custom eval cases (reported apart from DEV and holdout)", "",
          f"Marked in each fixture's `EXPECTED.md` (code/tests/fixtures/); {c['marked']} case(s) marked, "
          f"{c['scored']} scored, {c['not_run']} not run, {c['passed']} passed. Measured: {c['measured']}. "
          "Each expected output was derived by hand in the folder's `EXPECTED.md` (rule cited per step); the "
          "statement column quotes what a correct system must do.", "",
          "| fixture | case | expected (source) | provisional | run | result | statement |",
          "|---|---|---|---|---|---|---|"]
    for x in c["cases"]:
        exp = x.get("expected") or {}
        exp_s = (f"{exp['status']}, {exp['steps']} steps" if "status" in exp else
                 f"assertions {exp.get('assertions')}" if exp else "unreadable")
        res = x["result"]
        if "row_exact" in x:
            res += f" (status {x['pred_status']}; steps tp {x['step_tp']}/{x['n_gold']}, pred {x['n_pred']})"
        if x.get("problem"):
            res += f": {x['problem']}"
        stmt = (x.get("statement") or "").replace("|", "/")
        L.append(f"| {x['folder']} | {x['case_id']} | {exp_s} (`{x['expected_source']}`) | "
                 f"{x.get('provisional') or 'not stated'} | {('`' + x['run_id'] + '`') if x.get('run_id') else 'none'} "
                 f"| {res} | {stmt} |")
    agg = c["row_aggregate"]
    if agg:
        L += ["", f"Custom-case aggregate (row expectations only): status {_r(agg['status_accuracy'])}, row exact "
              f"{_r(agg['row_exact'])}, step F1 {_f(agg['step']['f1'])}, sequence exact {_r(agg['sequence_exact'])}."]
    else:
        L += ["", "No custom case has been scored yet: no fixture run is named in the spec's `custom_runs`. "
              "This is not a zero."]
    L.append("")


def _md_agent(L: list[str], a: Mapping[str, Any] | None) -> None:
    L += ["## 6. Agent sections (tool use, answers, arm deltas, intent, vision)", ""]
    if a is None:
        L += ["No arm runs are named in the spec, so no agent section was built. This is not a zero.", ""]
        return
    av = a["availability"]
    if av["unwired"]:
        L += [f"**Empty until G7 is wired, not zero:** {len(av['unwired'])} section(s) have no counts because the "
              "named runs' `cases.jsonl` lines carry no `agent` block and the runs wrote no `vision.json`: "
              + "; ".join(av["unwired"]) + ".", ""]
    if av["other_errors"]:
        L += ["**Adapter errors (not a missing-wiring case):** " + "; ".join(av["other_errors"]) + ".", ""]
    L += ["Embedded from `agent_report.render_markdown` (headings demoted):", ""]
    L += _demote(a["markdown"])
    L.append("")


def _md_validator(L: list[str], vals: Sequence[Mapping[str, Any]]) -> None:
    L += ["## 7. Validator and FAILED_CLOSED counts", ""]
    for v in vals:
        L.append(f"### run `{v['run_id']}`")
        if "error" in v:
            L += [f"- **ERROR:** {v['error']}", ""]
            continue
        L += [f"Source: {v['source']}; cross-checked against `cases.jsonl`.", "",
              "| validator part | checked | pass | fail |", "|---|---:|---:|---:|"]
        L += [f"| {k} | {x.get('checked', 0)} | {x.get('pass', 0)} | {x.get('fail', 0)} |"
              for k, x in (v["by_part"] or {}).items()]
        L += ["", "Failing checks by rule: " + ("; ".join(f"`{k}` {x['count']} ({', '.join(x['case_ids'])})"
                                                     for k, x in v["failing_cases"].items()) or "none") + ".",
              f"FAILED_CLOSED rows: {v['failed_closed']['count']}, by reason {v['failed_closed']['by_reason'] or {}}; "
              f"from cases.jsonl: {v['failed_closed_from_cases_jsonl']}."]
        L += [f"- **Cross-check failure:** {p}" for p in v["problems"]]
        L.append("")


def _md_coherence_drift(L: list[str], data: Mapping[str, Any]) -> None:
    L += ["## 8. Coherence and drift", ""]
    if data["coherence"] is None:
        L += ["Coherence not run in this build (spec `coherence: false`).", ""]
    else:
        L += ["`coherence.check_file` (hard rules from the spec confirmed on DEV, soft rules are DEV regularities). "
              "A FAILED_CLOSED row reports H03 as hard by design (T86), so hard cases outside FAILED_CLOSED rows "
              "are shown on their own (T87 (1)).", "",
              "| run | hard | soft | hard cases | hard cases outside FAILED_CLOSED | by rule |",
              "|---|---:|---:|---:|---:|---|"]
        L += [f"| `{c['run_id']}` | {c['hard']} | {c['soft']} | {c['hard_cases']} | "
              f"{c['hard_cases_outside_failed_closed']} {c['hard_cases_outside_failed_closed_ids'] or ''} | "
              f"{c['by_rule']} |" for c in data["coherence"]]
        L.append("")
    fp = data.get("final_vs_previous")
    if fp:
        L += [f"Final run `{fp['runs'][0]}` against the previous run `{fp['runs'][1]}` (measured: {fp['measured']}): "
              f"{len(fp['differ'])} of {fp['cases_compared']} rows differ: {', '.join(fp['differ'][:SAMPLE]) or 'none'}"
              f"{' ...' if len(fp['differ']) > SAMPLE else ''}; only in the final run "
              f"{len(fp['only_first'])}, only in the previous run {len(fp['only_second'])}.", ""]
    dr = data["drift"]
    L += [f"Drift of run `{dr['run_id']}` against DEV gold (`drift.drift_table`; {dr['flagged']} gap(s) over "
          f"{dr['threshold_pts']:g} points, flagged for a human to explain, never fixed by matching frequencies):",
          "", drift.format_table(dr["table"]), ""]


def _md_holdout(L: list[str], h: Mapping[str, Any]) -> None:
    L += ["## 9. Holdout", "", f"> **Caveat (verbatim from `{h['caveat_source']}`):** {h['caveat']}", ""]
    if h["section_md"]:
        if h.get("caveat_matches_record") is False:
            L += ["**Note:** the completed record's caveat differs from split.json's current text.", ""]
        L += _demote(h["section_md"], 1)
    else:
        L.append("**Not run yet.** No completed `holdout_record.json` exists under runs/; holdout gold has not been "
                 "loaded by this generator or by any scorer run it reads.")
        if h["unfinished"]:
            L.append(f"An unfinished attempt is recorded under {', '.join(h['unfinished'])}.")
    L += [f"- **Problem:** {p}" for p in h["problems"]]
    L.append("")


def _md_limitations(L: list[str], lims: Sequence[Mapping[str, Any]]) -> None:
    L += ["## 10. Limitations already ruled", ""]
    for x in lims:
        L.append(f"- **{x['label']}.** {x['summary']} Ruling ({x['quote_source']}): "
                 + (f"\"{x['quote']}\"" if x["quote"] else "**not found**") + ".")
        if "count" in x:
            c = x["count"]
            L.append(f"  - Run `{c['run_id']}`: {c['cases']} of {c['of']} cases ({c['measured']}).")
        if "dev_check" in x:
            d = x["dev_check"]
            L.append(f"  - Measured on DEV run `{d['run_id']}`: row exact {_r(d['row_exact'])}; cases the ruling "
                     f"names: {d['named_cases'] or 'none'}; not row-exact: {', '.join(d['not_row_exact']) or 'none'}.")
    L.append("")


def render_evaluation(data: Mapping[str, Any]) -> str:
    """The Markdown report, rendered from :func:`build_evaluation`'s dict only."""
    pr = data["protocol"]
    L = [f"# Evaluation report `{data['report_id']}`", "", *data.get("headline_md", []),
         f"Generated {data['created_at']} by `{data['command']}` from the named runs' artifacts only "
         "(code/evaluation/evaluation_report.py). Every number names its run. Nothing is typed by hand.", "",
         f"Gold: {data['gold']}, hash `{data['gold_dev_hash'][:16]}`; scorer code `{data['scorer_code_sha256'][:16]}`; "
         f"git HEAD `{str(data['git_head'])[:12]}`.", "", "## 1. Inputs", "",
         "| role | run | producer check | output sha256 | rows | produced by |", "|---|---|---|---|---:|---|"]
    L += [f"| {r['role']} | `{r['run_id']}` | {r['producer_check']} | `{str(r['output_sha256'])[:16]}` | {r['rows']} | "
          f"`{r['producer_command'] or 'unknown'}` |" for r in data["inputs"]]
    L += ["", "Every input run passed the producer check (`evidence_guard.check_producer` against its output's "
          "sha256); an unchecked run is refused before any report is built (T60, T81).", "",
          "## 2. Protocol", "",
          f"- Split: {pr['dev_size']} DEV and {pr['holdout_size']} holdout sample cases, seed {pr['seed']}; method: "
          f"{pr['method']}. `notes/split.json` and `code/evaluation/split.py` agree: "
          f"{pr['split_json_matches_split_py']}.",
          f"- When it was locked and who saw what (verbatim from `{pr['split_json']}` 'created'): {pr['created']}",
          "- DEV gold is loaded only through `gold.load_gold`, which drops holdout rows on their first field before "
          "any JSON parsing. This generator never asks for holdout gold.",
          f"- Holdout access log (`runs/HOLDOUT_ACCESS.log`): {pr['access_log_lines']} line(s), by kind "
          f"{pr['access_log_by_what'] or '{}'}.", ""]
    _md_dev(L, data["dev"], data["command"])
    _md_history(L, data["dev_history"])
    _md_custom(L, data["custom"])
    L += validation_set.render_section(data["validation"], "## 5b. Validation set: rule-derived fixtures, apart from "
                                                           "DEV and holdout")
    _md_agent(L, data["agent"])
    _md_validator(L, data["validator"])
    _md_coherence_drift(L, data)
    _md_holdout(L, data["holdout"])
    _md_limitations(L, data["limitations"])
    L += improvements.render_section(data["improvements"])
    return "\n".join(L) + "\n"
