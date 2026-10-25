"""The validation set: every rule-derived fixture under ``code/tests/fixtures/``, scored apart from DEV and holdout.

**Which fixtures.** Every folder under the fixtures root (red-team folders one level deeper)
that holds an ``EXPECTED.md`` and at least one expectation file (``custom_cases.ROW_FILES`` or
``custom_cases.ASSERTIONS_FILE``). They are found on disk, never listed in code. Their
expectations were derived by hand from the rules each folder's ``EXPECTED.md`` cites; they are
not sample cases, so they sit outside both DEV and the holdout.

**What each case is scored against.** ``custom_cases.expectations``, the same reader the custom
eval cases use (first file wins: ``expected_output.csv``, ``expected_partial.csv``, then the
``cases`` block of ``expected_assertions.json``). A row expectation passes when
``scorer.score_case`` finds the row exact (status and parsed steps). An assertion expectation
passes when every supported key holds (``custom_cases.check_assertions``); a key outside
``custom_cases.ASSERTION_KEYS`` is listed as not checked, never passed. A fixture passes when
every expected case passes.

**Which runs.** The spec's ``validation`` key maps an arm to ``{fixture folder: run ID}``
(folder relative to the fixtures root). A fixture with no run in an arm is "not run", never a
zero.

**Unchecked runs are never scored (T60, T81 in ``code/docs/DECISIONS.md``).** Each run is loaded
with ``agent_report.load_run`` and its producer check read. Only a run whose check is ``ok`` is
scored. Any other run is listed with its check status and reasons, as neither passed nor failed;
its output and case records are not read.

**Replay misses** are counted from the run's ``calls.jsonl`` (``event == "replay_miss"``): each
is a model reply the cache did not hold, so in a replay-only run that agent turn failed closed (an
explicit failure, never "nothing found"). They are shown beside the pass counts because they
explain a failure that is a missing reply, not a rule.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import custom_cases
from .agent_report import FIXTURES_ROOT, MODES, LoadedRun, load_run
from .gold import GoldCase
from .scorer import score_case

CALLS_FILE = "calls.jsonl"
REPLAY_MISS_EVENT = "replay_miss"
MEASURED = ("row expectations: scorer.score_case row_exact on runs/<id>/output.csv; assertion expectations: "
            "custom_cases.check_assertions on the row and its cases.jsonl record; expectations read by "
            "custom_cases.expectations from each fixture folder")


def discover(fixtures_root: Path = FIXTURES_ROOT) -> list[str]:
    """Every fixture folder (relative, POSIX form) with an ``EXPECTED.md`` and an expectation file."""
    names = (*custom_cases.ROW_FILES, custom_cases.ASSERTIONS_FILE)
    return sorted(md.parent.relative_to(fixtures_root).as_posix()
                  for md in fixtures_root.rglob(custom_cases.EXPECTED_MD)
                  if any((md.parent / n).is_file() for n in names))


def check_spec(validation: Mapping[str, Mapping[str, str]], fixtures_root: Path = FIXTURES_ROOT) -> None:
    """Every arm is known and every folder is a discovered fixture; raises ValueError otherwise."""
    known = set(discover(fixtures_root))
    for arm, m in validation.items():
        if arm not in MODES:
            raise ValueError(f"validation arm {arm!r} must be one of {list(MODES)}")
        for folder in m:
            if folder not in known:
                raise ValueError(f"validation folder {folder!r} is not a fixture with an expectation file under "
                                 f"{fixtures_root}")


def replay_misses(run: LoadedRun) -> int | None:
    """``calls.jsonl`` lines whose event is a replay miss; None when the file cannot be read."""
    try:
        text = (run.run_dir / CALLS_FILE).read_text(encoding="utf-8")
    except OSError:
        return None
    n = 0
    for line in text.splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, Mapping) and raw.get("event") == REPLAY_MISS_EVENT:
            n += 1
    return n


def score_case_expectation(exp: custom_cases.Expectation, run: LoadedRun, case_id: str,
                           records: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """One expected case on one checked run: passed or not, and the assertion keys not checked."""
    assert run.output is not None  # a checked run has an output.csv
    pred = run.output.rows.get(case_id)
    if exp.row is not None:
        sc = score_case(pred, GoldCase(case_id, exp.row.status, list(exp.row.steps or [])))
        return {"case_id": case_id, "kind": "row", "passed": bool(sc["row_exact"]), "pred_status": sc["pred_status"],
                "not_checked": []}
    assert exp.assertions is not None
    res = custom_cases.check_assertions(exp.assertions, pred, records.get(case_id))
    return {"case_id": case_id, "kind": "assertions", "passed": res["passed"],
            "pred_status": pred.status if pred else "MISSING", "not_checked": res["not_checked"]}


def score_fixture(folder: str, run_id: str | None, runs_root: Path, fixtures_root: Path) -> dict[str, Any]:
    """One fixture in one arm: its expectations, its run's producer check and its pass counts."""
    exps, problems = custom_cases.expectations(fixtures_root / folder, fixtures_root)
    base: dict[str, Any] = {"folder": folder, "run_id": run_id, "expected_cases": len(exps),
                            "expectation_problems": problems,
                            "sources": sorted({e.source.rsplit("/", 1)[-1] for e in exps.values()})}
    if run_id is None:
        return {**base, "result": "not run"}
    run = load_run(runs_root, run_id)
    pc = run.producer_check
    base = {**base, "producer_check": pc["status"], "output_sha256": pc["pred_sha256"],
            "mode": run.producer.get("mode"), "replay_only": run.producer.get("replay_only"),
            "paid_model_calls": run.producer.get("paid_model_calls")}
    if pc["status"] != "ok":
        return {**base, "result": "not scored", "why": f"producer check {pc['status']}: " + "; ".join(pc["reasons"])}
    if problems:
        return {**base, "result": "not scored", "why": "expectation files unreadable: " + "; ".join(problems)}
    assert run.output is not None
    records = custom_cases.records_by_case(run)
    cases = [score_case_expectation(exps[c], run, c, records) for c in sorted(exps)]
    passed = [c["case_id"] for c in cases if c["passed"]]
    return {**base, "result": "pass" if len(passed) == len(cases) and cases else "fail",
            "cases_passed": len(passed), "failed": [c["case_id"] for c in cases if not c["passed"]],
            "not_checked": sorted({k for c in cases for k in c["not_checked"]}),
            "rows_without_expectation": len(set(run.output.rows) - set(exps)),
            "replay_misses": replay_misses(run), "cases": cases}


def build_validation(validation: Mapping[str, Mapping[str, str]], *, runs_root: Path,
                     fixtures_root: Path = FIXTURES_ROOT) -> dict[str, Any]:
    """The validation-set section's data, per arm (module docstring)."""
    check_spec(validation, fixtures_root)
    folders = discover(fixtures_root)
    arms: dict[str, Any] = {}
    for arm in [a for a in MODES if a in validation]:
        per = [score_fixture(f, validation[arm].get(f), runs_root, fixtures_root) for f in folders]
        scored = [p for p in per if p["result"] in ("pass", "fail")]
        arms[arm] = {"fixtures": per, "listed": len(per), "run": sum(1 for p in per if p["result"] != "not run"),
                     "not_scored": sum(1 for p in per if p["result"] == "not scored"),
                     "scored": len(scored), "fixtures_passed": sum(1 for p in scored if p["result"] == "pass"),
                     "cases_scored": sum(p["expected_cases"] for p in scored),
                     "cases_passed": sum(p["cases_passed"] for p in scored),
                     "replay_misses": sum(p["replay_misses"] or 0 for p in scored)}
    return {"measured": MEASURED, "folders": folders, "arms": arms}


def _cell(x: Mapping[str, Any]) -> str:
    if x["result"] == "not run":
        return "| none | n/a | n/a | n/a | n/a | n/a | not run |"
    if x["result"] == "not scored":
        return f"| `{x['run_id']}` | {x['producer_check']} | n/a | n/a | n/a | n/a | not scored: {x['why']} |"
    nc = f"; keys not checked {x['not_checked']}" if x["not_checked"] else ""
    misses = "n/a (no calls.jsonl)" if x["replay_misses"] is None else str(x["replay_misses"])
    return (f"| `{x['run_id']}` | {x['producer_check']} | {x['cases_passed']}/{x['expected_cases']} | "
            f"{', '.join(x['failed']) or 'none'} | {misses} | {x['rows_without_expectation']} | "
            f"{x['result']}{nc} |")


def render_section(v: Mapping[str, Any], heading: str) -> list[str]:
    """The section's Markdown lines, from :func:`build_validation`'s dict only."""
    L = [heading, "",
         f"Every fixture folder under `code/tests/fixtures/` with an expectation file ({len(v['folders'])} folders, "
         "found on disk). Their expectations were derived by hand from the rules each folder's `EXPECTED.md` "
         "cites; they are not sample cases, so they are reported apart from DEV and the holdout. Measured: "
         f"{v['measured']}. A run whose producer check is not `ok` is not scored (T60, T81); a replay miss is a "
         "model reply the cache did not hold, so that agent turn failed closed.", ""]
    if not v["arms"]:
        return [*L, "No fixture run is named in the spec's `validation` key, so nothing was scored. This is not a "
                    "zero.", ""]
    for arm, a in v["arms"].items():
        L += [f"### Arm {arm}", "",
              f"Fixtures passed {a['fixtures_passed']}/{a['scored']} scored ({a['listed']} listed, {a['run']} run, "
              f"{a['not_scored']} not scored); cases passed {a['cases_passed']}/{a['cases_scored']} scored; replay "
              f"misses in scored runs {a['replay_misses']}.", "",
              "| fixture | run | producer check | cases passed | failed cases | replay misses | rows without "
              "expectation | result |", "|---|---|---|---:|---|---:|---:|---|"]
        L += [f"| {x['folder']} {_cell(x)}" for x in a["fixtures"]]
        L.append("")
    return L
