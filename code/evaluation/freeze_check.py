"""Freeze check (T60, T71 Q5, T87, T88, T101): refuse a run unless its four blocking counts are 0 and its
output is the approved file.

Usage (from the repo root):
    python3 -B code/evaluation/freeze_check.py --run-id <run_id> [--record-run-id <id>]

It reads ``runs/<run_id>/`` only and passes (exit 0) only when ALL of these hold:

* the run is checked: ``evidence_guard.check_producer`` on its ``producer.json`` against the
  sha256 of its ``output.csv`` returns ``ok`` (T72, T81), and ``metrics.json`` names the same
  output hash;
* the adapter (``agent_report.read_run_artifacts``) reports no error: every case has a valid
  ``agent`` block, ``cases.jsonl`` covers exactly the rows of ``output.csv``, and the vision
  artifact exists and is consistent;
* ``failed_closed_rows`` = 0: cases whose ``row_state`` is FAILED_CLOSED or whose
  ``failed_closed`` reason is set (T60, T71 Q5). It must equal ``metrics.json``'s count;
* ``intent_failed_closed`` = 0: cases flagged ``INTENT_FAILED_CLOSED`` (record or agent flags),
  or whose intent source, in the record or the agent block, is FAILED_CLOSED or FAILED_BUDGET
  (T87: never ship a row whose intent came from the fail-closed path; the budget path is the
  same Q2 path, so it counts too);
* ``evidence_skips`` = 0: the producer's ``evidence_skipped`` list is empty, so the
  ``png-model-needed`` allow-list is unused (T60). ``evidence_skip_count`` must agree;
* ``vision_unresolved_disagreements`` = 0: images whose two readings disagree (T88). The
  artifact has no resolution field yet, so every disagreement is unresolved;
* **the approved output** (developer ruling T101 (1) and (3)): the sha256 of the run's
  ``output.csv`` equals the ``approved_output.sha256`` of ``notes/approved_output.json``, read at
  check time. Both are printed. A mismatch, or a record that cannot be read, refuses.

Otherwise it refuses with exit status 1 and names each failing count, or the error that kept
a count from being computed. A count that cannot be computed is never reported as 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: same bootstrap as evaluate.py
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import runs  # noqa: E402
from evaluation.agent_report import (  # noqa: E402
    CASES_FILE,
    FAILED_SOURCES,
    INTENT_FAILED_FLAG,
    METRICS_FILE,
    OUTPUT_FILE,
    CaseView,
    LoadedRun,
    load_run,
    run_path,
    summarize_errors,
)
from evaluation.paths import REPO_ROOT, RUNS  # noqa: E402

COUNTS: tuple[str, ...] = ("failed_closed_rows", "intent_failed_closed", "evidence_skips",
                           "vision_unresolved_disagreements")
SAMPLE = 10  # case IDs shown per failing count
APPROVED_RECORD: Path = REPO_ROOT / "notes" / "approved_output.json"  # T101 (1): the developer-approved output


def approved_output_check(output_sha256: str | None, record: Path) -> dict[str, Any]:
    """Compare a run's output sha256 with the approved one (T101); ``error`` is set when it cannot be read."""
    out: dict[str, Any] = {"record": str(record), "output_sha256": output_sha256, "approved_sha256": None,
                           "approved_run_id": None, "matches": False, "error": None}
    try:
        approved = json.loads(record.read_text(encoding="utf-8"))["approved_output"]
        sha = approved["sha256"]
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError("approved sha256 is not 64 hex characters")
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        out["error"] = f"approved-output record unreadable ({type(exc).__name__})"
        return out
    out.update(approved_sha256=sha, approved_run_id=approved.get("run_id"), matches=output_sha256 == sha)
    return out


def is_failed_closed(c: CaseView) -> bool:
    """A FAILED_CLOSED row: by row state or by a recorded reason."""
    return c.row_state == "FAILED_CLOSED" or c.failed_closed is not None


def is_intent_failed_closed(c: CaseView) -> bool:
    """A row whose intent came from the fail-closed path (flag or source, record or agent)."""
    flags = set(c.flags) | (set(c.agent.flags) if c.agent else set())
    sources = {c.intent_source} | ({c.agent.intent.source} if c.agent else set())
    return INTENT_FAILED_FLAG in flags or bool(sources & FAILED_SOURCES)


def _metrics(run: LoadedRun) -> tuple[Mapping[str, Any] | None, list[str]]:
    try:
        m = json.loads((run.run_dir / METRICS_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, [f"{METRICS_FILE}: missing or unreadable"]
    return (m, []) if isinstance(m, Mapping) else (None, [f"{METRICS_FILE}: not a JSON object"])


def _skips(producer: Mapping[str, Any]) -> tuple[int | None, list[str]]:
    skipped = producer.get("evidence_skipped")
    if not isinstance(skipped, list):
        return None, ["producer evidence_skipped is not a list"]
    count = producer.get("evidence_skip_count", len(skipped))
    if count != len(skipped):
        return None, [f"producer evidence_skip_count ({count}) differs from len(evidence_skipped) ({len(skipped)})"]
    return len(skipped), []


def freeze_check(run_id: str, *, runs_root: Path = RUNS, approved_record: Path | None = None) -> dict[str, Any]:
    """Compute the freeze record for one run (never raises on bad artifacts; reports them).

    ``approved_record`` defaults to :data:`APPROVED_RECORD` (``notes/approved_output.json``)."""
    run = load_run(runs_root, run_id)
    view = run.view
    errors: list[str] = []
    pstatus = run.producer_check["status"]
    if pstatus != "ok":
        errors.append(f"producer check {pstatus}: " + "; ".join(run.producer_check["reasons"]))
    metrics, merr = _metrics(run)
    errors += merr
    if metrics is not None and metrics.get("output_sha256") != run.producer_check["pred_sha256"]:
        errors.append(f"{METRICS_FILE} output_sha256 differs from the sha256 of {OUTPUT_FILE}")
    if run.output is not None and set(run.output.rows) != set(view.cases):
        errors.append(f"{CASES_FILE} covers {len(view.cases)} case(s), {OUTPUT_FILE} has {len(run.output.rows)}")
    adapter = summarize_errors([*view.record_errors, *view.agent_errors, *view.vision_errors])
    errors += [f"adapter: {e['path']}: {e['problem']} ({e['count']}; e.g. {', '.join(e['where'])})" for e in adapter]
    cases = sorted(view.cases.values(), key=lambda c: c.case_id)
    record_ok = not view.record_errors
    fc_cases = [c.case_id for c in cases if is_failed_closed(c)]
    counts: dict[str, int | None] = {k: None for k in COUNTS}
    case_lists: dict[str, list[str]] = {}
    if record_ok:
        counts["failed_closed_rows"] = len(fc_cases)
        case_lists["failed_closed_rows"] = fc_cases
        mfc = (metrics or {}).get("failed_closed", {})
        if metrics is not None and (not isinstance(mfc, Mapping) or mfc.get("count") != len(fc_cases)):
            errors.append(f"{METRICS_FILE} failed_closed.count disagrees with {CASES_FILE} ({len(fc_cases)})")
    lower_bounds: dict[str, int] = {}
    if record_ok:
        ifc = [c.case_id for c in cases if is_intent_failed_closed(c)]
        if not view.agent_errors:
            counts["intent_failed_closed"], case_lists["intent_failed_closed"] = len(ifc), ifc
        else:  # agent blocks unreadable: the record-level part is a floor, never the count
            lower_bounds["intent_failed_closed"] = len(ifc)
    skips, serr = _skips(run.producer)
    errors += serr
    counts["evidence_skips"] = skips
    case_lists["evidence_skips"] = [str(x).split(":")[0] for x in run.producer.get("evidence_skipped") or []]
    if view.vision is not None and not view.vision_errors:
        dis = sorted(i.file_id for i in view.vision if not i.agree)
        counts["vision_unresolved_disagreements"], case_lists["vision_unresolved_disagreements"] = len(dis), dis
    refusals = [f"{k} = {n} (e.g. {', '.join(case_lists[k][:SAMPLE])})" for k, n in counts.items() if n]
    refusals += [f"{k}: not computed (see errors)" for k, n in counts.items() if n is None]
    refusals += [f"error: {e}" for e in errors]
    approved = approved_output_check(run.producer_check["pred_sha256"], approved_record or APPROVED_RECORD)
    if approved["error"]:
        refusals.append(f"approved output: {approved['error']}")
    elif not approved["matches"]:
        refusals.append(f"approved output: the run's output sha256 {approved['output_sha256']} differs from the "
                        f"approved {approved['approved_sha256']} (T101)")
    return {"run_id": run_id, "kind": "freeze-check", "checked_at": runs.now_ist(), "producer_check": pstatus,
            "output_sha256": run.producer_check["pred_sha256"], "approved_output": approved, "counts": counts,
            "lower_bounds_when_not_computed": lower_bounds,
            "ids": {k: v for k, v in case_lists.items() if v}, "errors": errors, "refusals": refusals,
            "passed": not refusals}


def main(argv: list[str] | None = None) -> int:
    """Run the freeze check; exit 0 on pass, 1 on refusal (each failing count named)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True, help="the run to check (runs/<id>/)")
    ap.add_argument("--record-run-id", help="also write runs/<id>/freeze_check.json under this separate run ID")
    a = ap.parse_args(argv)
    res = freeze_check(a.run_id, runs_root=RUNS)
    print(f"freeze check {res['run_id']}: producer check {res['producer_check']}")
    floors = res["lower_bounds_when_not_computed"]
    for k, n in res["counts"].items():
        floor = f" (record-level floor: at least {floors[k]})" if k in floors else ""
        print(f"  {k}: {'not computed' if n is None else n}{floor}")
    ap_out = res["approved_output"]
    print(f"  output sha256:   {ap_out['output_sha256']}")
    verdict = ap_out["error"] or ("match" if ap_out["matches"] else "MISMATCH")
    print(f"  approved sha256: {ap_out['approved_sha256']} ({verdict})")
    if a.record_run_id:
        d = run_path(RUNS, a.record_run_id)
        if d == run_path(RUNS, a.run_id) or (d / OUTPUT_FILE).exists():
            print("refused to write the record into a producer run; give it its own run ID", file=sys.stderr)
            return 1
        d.mkdir(parents=True, exist_ok=True)
        runs.write_json(d / "freeze_check.json", res)
    if res["passed"]:
        print("FREEZE CHECK PASSED: all four counts are 0 on a checked run whose output is the approved file")
        return 0
    print("FREEZE CHECK REFUSED:")
    for r in res["refusals"]:
        print(f"  {r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
