"""One command builds the three generated reports from a spec of named runs.

Usage (from the repo root):
    .venv/bin/python -B code/evaluation/reports.py --spec <spec.json> [--report-id <id>] [--publish]

The spec format is in ``report_spec``'s docstring. ``--report-id`` overrides the spec's
``report_id``. Output, always under ``runs/<report_id>/``:

* ``evaluation_report.md`` (``evaluation_report``),
* ``usage_report.md`` (``usage_report``),
* ``metrics.json`` (``run_metrics``; the I4 production metrics of the final run, naming its
  source runs; the final run's own pipeline-written ``metrics.json`` is not touched),
* ``reports_build.json``: the spec, the data every report was rendered from, and the
  cross-check failures.

Both Markdown reports open with the same generated headline block (``headline``).

**``--publish``** also writes ``evaluation_report.md`` and ``usage_report.md`` into
``code/evaluation/`` (the deliverable path; G10 uses it once on the final runs). It refuses
(exit 3, nothing published, the ``runs/<report_id>/`` copies still written) unless:
(1) every input run passed the producer check (as for any build, ledger runs included);
(2) the spec says ``"final": true`` and its usage run is its final run;
(3) the final run covers the full test dataset (one row per test request);
(4) the build has no cross-check failure, which includes every refused or PENDING ledger entry.
The paths and sha256 of the published files are recorded in ``reports_build.json``.

Exit status: 0 written and every cross-check agrees; 2 written, with cross-check failures listed
(on stderr and in ``reports_build.json``); 3 refused (an unchecked input run, T60/T81, or a
report ID that names an input run), with ``refused.json`` written and no report. Agent sections
that are empty because the runs predate G7 do not change the exit status; the report says so.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import shlex
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: same bootstrap as evaluate.py
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import evaluation_report, headline, run_metrics, runs, usage_report  # noqa: E402
from evaluation.agent_report import OUTPUT_FILE, ReportRefused, read_usage, run_path  # noqa: E402
from evaluation.gold import load_requests  # noqa: E402
from evaluation.paths import TEST_REQUESTS  # noqa: E402
from evaluation.report_spec import ReportSpec, load_checked, load_spec  # noqa: E402

EVALUATION_MD = "evaluation_report.md"
USAGE_MD = "usage_report.md"
METRICS_JSON = "metrics.json"
BUILD_JSON = "reports_build.json"


def build_all(spec: ReportSpec, ctx: evaluation_report.Context, *, command: str) -> dict[str, Any]:
    """Build the three reports' data and Markdown. Raises ``ReportRefused`` on an unchecked run."""
    created = runs.now_ist()
    loaded = load_checked(spec, ctx.runs_root)
    ev = evaluation_report.build_evaluation(spec, loaded, ctx, command=command, created_at=created)
    u = spec.usage_spec
    usage_json, _ = read_usage(ctx.runs_root / u.run / "usage.json")
    raw_usage = None
    if usage_json is not None:  # read_usage type-checks five fields; the full object feeds the cross-check
        raw_usage = json.loads((ctx.runs_root / u.run / "usage.json").read_text(encoding="utf-8"))
    final = loaded[spec.final_run]
    assert final.output is not None
    test_ids = ctx.test_ids if ctx.test_ids is not None else frozenset(load_requests(TEST_REQUESTS))
    facts = {"run_id": spec.final_run, "rows": len(final.output.rows), "test_requests": len(test_ids),
             "rows_not_in_test_requests": len(set(final.output.rows) - set(test_ids)),
             "test_requests_without_row": len(set(test_ids) - set(final.output.rows))}
    us = usage_report.build_usage(u.run, runs_root=ctx.runs_root, cache_root=ctx.cache_root,
                                  calls_file=u.calls_file, usage=raw_usage, final=facts)
    dev_prev = [r for r in spec.dev_history if r != spec.dev_run]
    entries = [("final", loaded[spec.final_run], loaded.get(spec.previous_run or "")),
               ("dev", loaded[spec.dev_run], loaded[dev_prev[-1]] if dev_prev else None)]
    met = run_metrics.build_metrics(entries, report_id=spec.report_id, created_at=created, command=command)
    failures = [*evaluation_report.problems(ev), *(f"usage: {x}" for x in usage_report.failures_found(us))]
    head = headline.build_headline(ev, us, final)
    head_md = headline.render_headline(head)
    ev["headline"] = head
    return {
        "evaluation": ev, "usage": us, "metrics": met, "failures": failures, "headline": head,
        "evaluation_md": evaluation_report.render_evaluation({**ev, "headline_md": head_md}),
        "usage_md": usage_report.render_usage(us, report_id=spec.report_id, created_at=created, command=command,
                                              headline=head_md),
    }


def publish_refusals(spec: ReportSpec, built: dict[str, Any]) -> list[str]:
    """Why ``--publish`` must refuse (empty: it may publish). Checks (2)-(4) of the module docstring."""
    out = []
    if not spec.final:
        out.append('the spec does not say "final": true')
    if spec.usage_spec.run != spec.final_run:
        out.append(f"the usage run {spec.usage_spec.run} is not the final run {spec.final_run}")
    fin = built["usage"]["final"]
    if fin["rows"] != fin["test_requests"] or fin["rows_not_in_test_requests"] or fin["test_requests_without_row"]:
        out.append(f"the final run is not the full dataset: {fin['rows']} rows for {fin['test_requests']} test "
                   f"requests ({fin['test_requests_without_row']} without a row, {fin['rows_not_in_test_requests']} "
                   "rows not in the test file)")
    if built["failures"]:
        out.append(f"{len(built['failures'])} cross-check failure(s) (refused or PENDING ledger entries included)")
    return out


def publish(built: dict[str, Any], publish_dir: Path) -> list[dict[str, str]]:
    """Write the two Markdown reports into the deliverable folder; return their paths and sha256."""
    out = []
    for name, key in ((EVALUATION_MD, "evaluation_md"), (USAGE_MD, "usage_md")):
        path = publish_dir / name
        path.write_text(built[key], encoding="utf-8")
        out.append({"path": str(path), "sha256": runs.sha256_file(path)})
    return out


def write_all(spec: ReportSpec, built: dict[str, Any], out_dir: Path) -> list[Path]:
    """Write the three reports and the build record into ``out_dir``; return the paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / EVALUATION_MD, out_dir / USAGE_MD, out_dir / METRICS_JSON, out_dir / BUILD_JSON]
    paths[0].write_text(built["evaluation_md"], encoding="utf-8")
    paths[1].write_text(built["usage_md"], encoding="utf-8")
    runs.write_json(paths[2], built["metrics"])
    ev = dict(built["evaluation"])
    if ev.get("agent"):
        ev["agent"] = {k: v for k, v in ev["agent"].items() if k != "markdown"}
    runs.write_json(paths[3], {"report_id": spec.report_id, "kind": "reports-build",
                               "spec": dataclasses.asdict(spec), "failures": built["failures"],
                               "publish": built.get("publish"), "evaluation": ev, "usage": built["usage"]})
    return paths


def main(argv: list[str] | None = None, *, ctx: evaluation_report.Context | None = None) -> int:
    """Build and write the reports; exit 0, 2 (cross-check failures) or 3 (refused)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, help="JSON spec file (report_spec docstring)")
    ap.add_argument("--report-id", help="override the spec's report_id")
    ap.add_argument("--publish", action="store_true",
                    help="also write both Markdown reports into code/evaluation/ (refusals: module docstring)")
    a = ap.parse_args(argv)
    c = ctx or evaluation_report.Context()
    spec = load_spec(Path(a.spec))
    if a.report_id:
        spec = dataclasses.replace(spec, report_id=runs.check_run_id(a.report_id))
    out_dir = run_path(c.runs_root, spec.report_id)
    command = "python3 -B code/evaluation/reports.py " + " ".join(
        shlex.quote(x) for x in (argv if argv is not None else sys.argv[1:]))
    if (out_dir / OUTPUT_FILE).exists() or spec.report_id in spec.input_runs():
        print(f"refused: {spec.report_id} names an input or producer run; give the reports their own ID",
              file=sys.stderr)
        return 3
    try:
        built = build_all(spec, c, command=command)
    except ReportRefused as exc:
        out_dir.mkdir(parents=True, exist_ok=True)
        runs.write_json(out_dir / "refused.json", {"run_id": spec.report_id, "kind": "reports-refused",
                                                   "created_at": runs.now_ist(), "command": command,
                                                   "reasons": exc.reasons})
        print("reports refused: unchecked input run(s) never feed a report (T60, T81):", file=sys.stderr)
        for r in exc.reasons:
            print(f"  {r}", file=sys.stderr)
        return 3
    refusals = publish_refusals(spec, built) if a.publish else []
    built["publish"] = None if not a.publish else {"requested": True, "refused": refusals, "published": []}
    if a.publish and not refusals:
        built["publish"]["published"] = publish(built, c.publish_dir)
    paths = write_all(spec, built, out_dir)
    for p in paths:
        print(f"wrote {p}")
    if a.publish:
        if refusals:
            print("publish refused (nothing written to the deliverable folder):", file=sys.stderr)
            for r in refusals:
                print(f"  {r}", file=sys.stderr)
            for f in built["failures"]:
                print(f"  failure: {f}", file=sys.stderr)
            return 3
        for x in built["publish"]["published"]:
            print(f"published {x['path']} (sha256 {x['sha256'][:16]})")
    m = built["metrics"]
    print(f"metrics.json alerts firing: {m['alerts_firing'] or 'none'}; not computed: "
          f"{m['alerts_not_computed'] or 'none'}")
    if built["failures"]:
        print(f"{len(built['failures'])} cross-check failure(s):", file=sys.stderr)
        for f in built["failures"]:
            print(f"  {f}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
