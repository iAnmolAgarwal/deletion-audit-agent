"""Freeze check (T60, T71 Q5, T87, T88, T101, T108, T109 (c), T110): refuse a run unless every blocking
count is 0 and its output is the approved file.

Usage (from the repo root):
    python3 -B code/evaluation/freeze_check.py --run-id <run_id> [--prior-run-id <id> ...] [--record-run-id <id>]

``--prior-run-id`` names earlier runs of the same command, oldest first (repeatable); the caller
names them, the check does not search for them. It reads ``runs/<run_id>/`` (and each prior run)
only and passes (exit 0) only when ALL of these hold:

* the run is checked: ``evidence_guard.check_producer`` on its ``producer.json`` against the
  sha256 of its ``output.csv`` returns ``ok`` (T72, T81), and ``metrics.json`` names the same
  output hash;
* the adapter (``agent_report.read_run_artifacts``) reports no error: every case has a valid
  ``agent`` block, ``cases.jsonl`` covers exactly the rows of ``output.csv``, and the vision
  artifacts exist and are consistent;

and the blocking counts are all 0:

* ``failed_closed_rows``: cases whose ``row_state`` is FAILED_CLOSED or whose ``failed_closed``
  reason is set (T60, T71 Q5). It must equal ``metrics.json``'s count;
* ``intent_failed_closed``: cases flagged ``INTENT_FAILED_CLOSED`` (record or agent flags), or
  whose intent source, in the record or the agent block, is FAILED_CLOSED or FAILED_BUDGET (T87);
* ``agent_failed_cases`` (T109 (c), T110 (1); T87 (2)): cases whose agent outcome is ``FAILED`` (a
  model call failed at some turn), each listed with its error class: from the record-level
  ``AGENT_CALL_FAILED`` flag detail, else from the failed ``calls.jsonl`` event of one of the
  case's request keys, else "not recorded". Remedy: re-run the same command; the reply cache
  replays the successful calls and only the failed one is sent again;
* ``evidence_skips``: the producer's ``evidence_skipped`` list is empty, so the
  ``png-model-needed`` allow-list is unused (T60). ``evidence_skip_count`` must agree;
* ``vision_failed_readings`` (T108): images whose reading failed (status FAILED: not PNG, or a
  reading returned nothing). An unread screenshot is an unparsed dependency, and freeze needs 0
  skips (T60), so it blocks. Each is listed with its failure code;
* ``vision_unresolved_disagreements`` (T88, T101, T112 4(a)): read images whose two readings
  disagree, each listed with its field paths, unless ``producer.json`` ``vision.review.acknowledged``
  holds an entry with that exact ``file_id`` and both of its reading keys (a recorded
  acknowledgement from a developer turn). An acknowledged image is listed, not counted; the
  acknowledgement never picks a reading. A malformed acknowledgement list leaves the count not computed;
* **the approved output** (T101 (1) and (3)): the sha256 of the run's ``output.csv`` equals the
  ``approved_output.sha256`` of ``notes/approved_output.json``, read at check time, or its
  ``provisional_freeze.sha256`` (developer ruling T119: a candidate approved provisionally, for the
  freeze check and the holdout run only; it does not become the shipped output or the gate's
  baseline). Both hashes are printed, with which one matched.

**FAILED_CLOSED rows identical to the approved file (developer ruling T118 step 4).** When the
record holds ``freeze_accepts_failed_closed_identical_to`` (``{sha256, ruling}``), the approved file
with that sha256 (an entry of ``approved_outputs`` or ``approved_output``, sha256-checked at check
time) is read, and a FAILED_CLOSED row whose ``output.csv`` row equals that file's row for the same
case (status and ``steps_json`` text) is listed as accepted, not counted. Any other FAILED_CLOSED
row still blocks; an unreadable or mismatched file is an error, so nothing is accepted.

Listed but not blocking: ``vision_unmapped_labels``, screenshot labels that map to no resource ID
(such as a support-ticket label with no system). A label is not a resource ID, so it gives no step
by itself; a record the image fails to give is caught by the counts above and by the engine.

**Repeat-failure stop (T110 (2)).** When a case is FAILED with the same error class in this run and
in each of the two prior runs before it (that is, on two re-runs in a row), the result is
STOP-FOR-DEVELOPER (exit 4), never a plain refusal: it names the case, the error class and the
request size (the largest ``usage.input_tokens`` that ``calls.jsonl`` logs for the case's request
keys; a failed request logs no usage, so this is the size of the conversation before the failure,
or "not recorded"). An unrecorded error class counts as the same class on each run, so missing
data never avoids the stop. No option clears it; only the developer's ruling does.

Otherwise it refuses with exit status 1 and names each failing count, or the error that kept a
count from being computed. A count that cannot be computed is never reported as 0.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: same bootstrap as evaluate.py
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import runs  # noqa: E402
from evaluation.agent_report import (  # noqa: E402
    AGENT_FAILED_STATUS,
    CASES_FILE,
    FAILED_SOURCES,
    INTENT_FAILED_FLAG,
    METRICS_FILE,
    OUTPUT_FILE,
    CaseView,
    LoadedRun,
    acknowledged_images,
    load_run,
    run_path,
    shown,
    summarize_errors,
)
from evaluation.paths import REPO_ROOT, RUNS  # noqa: E402

COUNTS: tuple[str, ...] = ("failed_closed_rows", "intent_failed_closed", "agent_failed_cases", "evidence_skips",
                           "vision_failed_readings", "vision_unresolved_disagreements")  # each one blocks
CALLS_FILE = "calls.jsonl"
FAILED_CALL_OUTCOMES: frozenset[str] = frozenset({"give_up", "failed"})
NOT_RECORDED = "not recorded"
REPEAT_RUNS = 3  # T110 (2): this run and the two before it (two re-runs in a row)
STOP = "STOP-FOR-DEVELOPER"
EXIT_REFUSED, EXIT_STOP = 1, 4
RERUN_REMEDY = ("remedy: re-run the same command; the reply cache replays the successful calls and only the "
                "failed one is sent again")
SAMPLE = 10  # case IDs shown per failing count
APPROVED_RECORD: Path = REPO_ROOT / "notes" / "approved_output.json"  # T101 (1): the developer-approved output


def _sha64(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("an approved sha256 is not 64 hex characters")
    return value


def approved_output_check(output_sha256: str | None, record: Path) -> dict[str, Any]:
    """Compare a run's output sha256 with the approved one (T101) or the provisional one (T119);
    ``matched`` names which; ``error`` is set when the record cannot be read."""
    out: dict[str, Any] = {"record": str(record), "output_sha256": output_sha256, "approved_sha256": None,
                           "approved_run_id": None, "provisional_sha256": None, "provisional": None,
                           "matched": None, "matches": False, "error": None}
    try:
        body = json.loads(record.read_text(encoding="utf-8"))
        approved = body["approved_output"]
        sha = _sha64(approved["sha256"])
        prov = body.get("provisional_freeze")
        prov_sha = _sha64(prov["sha256"]) if prov is not None else None
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        out["error"] = f"approved-output record unreadable ({type(exc).__name__})"
        return out
    matched = ("approved_output" if output_sha256 == sha else
               "provisional_freeze (T119)" if prov_sha is not None and output_sha256 == prov_sha else None)
    out.update(approved_sha256=sha, approved_run_id=approved.get("run_id"), provisional_sha256=prov_sha,
               provisional=dict(prov) if prov is not None else None, matched=matched, matches=matched is not None)
    return out


def _csv_rows(data: bytes) -> dict[str, tuple[str, ...]]:
    """``{case_id: (status, steps_json)}`` from output.csv bytes (the text as written, unparsed JSON)."""
    rows: dict[str, tuple[str, ...]] = {}
    for line in list(csv.reader(io.StringIO(data.decode("utf-8"))))[1:]:
        if line:
            rows[line[0]] = tuple(line[1:])
    return rows


def accepted_failed_closed(record: Path, output: bytes | None, fc_cases: Sequence[str],
                           repo_root: Path = REPO_ROOT) -> tuple[list[str], dict[str, Any] | None, list[str]]:
    """T118 step 4 (module docstring): the FAILED_CLOSED cases whose row equals the named approved
    file's row; the acceptance as recorded (None when the record has none); and any errors."""
    try:
        body = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return [], None, []  # the approved-output check reports an unreadable record
    rule = body.get("freeze_accepts_failed_closed_identical_to") if isinstance(body, Mapping) else None
    if rule is None:
        return [], None, []
    try:
        want = _sha64(rule["sha256"])
        per_split = body.get("approved_outputs") or {}
        entries = [*(per_split.values() if isinstance(per_split, Mapping) else []), body["approved_output"]]
        rel = next(str(e["path"]) for e in entries if isinstance(e, Mapping) and e.get("sha256") == want)
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        return [], dict(rule) if isinstance(rule, Mapping) else None, [
            f"freeze_accepts_failed_closed_identical_to: no approved file with that sha256 ({type(exc).__name__})"]
    path = Path(rel) if Path(rel).is_absolute() else repo_root / rel
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [], dict(rule), [f"freeze_accepts_failed_closed_identical_to: {rel} unreadable ({type(exc).__name__})"]
    if hashlib.sha256(data).hexdigest() != want:
        return [], dict(rule), [f"freeze_accepts_failed_closed_identical_to: {rel} does not have the recorded sha256"]
    if output is None:
        return [], dict(rule), []
    base, mine = _csv_rows(data), _csv_rows(output)
    return [c for c in fc_cases if c in base and c in mine and base[c] == mine[c]], dict(rule), []


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


def _call_events(run: LoadedRun) -> list[Mapping[str, Any]]:
    """The ``calls.jsonl`` events of a run, in file order (unreadable lines are skipped; none is invented)."""
    try:
        lines = (run.run_dir / CALLS_FILE).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for line in lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, Mapping):
            out.append(ev)
    return out


def failed_cases(run: LoadedRun) -> dict[str, dict[str, Any]] | None:
    """Cases whose agent outcome is FAILED, with error class and request size; None if agent blocks are unreadable.

    The error class comes from the record-level ``AGENT_CALL_FAILED`` flag detail, else from the
    last failed ``calls.jsonl`` event of one of the case's request keys, else :data:`NOT_RECORDED`.
    The request size is the largest logged ``usage.input_tokens`` of the case's keys, or None."""
    view = run.view
    if view.agent_errors or view.record_errors:
        return None
    events = _call_events(run)
    out: dict[str, dict[str, Any]] = {}
    for c in sorted(view.cases.values(), key=lambda x: x.case_id):
        if c.agent is None or c.agent.status != AGENT_FAILED_STATUS:
            continue
        keys = set(c.agent.replies)
        mine = [e for e in events if isinstance(e.get("key"), str) and e["key"] in keys]
        logged = [e.get("error_class") for e in mine if e.get("outcome") in FAILED_CALL_OUTCOMES]
        logged_ok = [x for x in logged if isinstance(x, str) and shown(x) == x]
        cls = c.call_failure_classes[-1] if c.call_failure_classes else (logged_ok[-1] if logged_ok else NOT_RECORDED)
        tokens = [u["input_tokens"] for e in mine if isinstance(u := e.get("usage"), Mapping)
                  and isinstance(u.get("input_tokens"), int) and not isinstance(u.get("input_tokens"), bool)]
        out[c.case_id] = {"case_id": c.case_id, "error_class": cls,
                          "request_size": {"max_logged_input_tokens": max(tokens) if tokens else None,
                                           "request_keys": len(keys),
                                           "basis": f"{CASES_FILE} agent.replies x {CALLS_FILE} usage.input_tokens"}}
    return out


def repeat_failures(current: Mapping[str, Mapping[str, Any]], priors: list[tuple[str, dict[str, dict[str, Any]]]],
                    run_id: str) -> list[dict[str, Any]]:
    """T110 (2): cases FAILED with one error class in this run and each of the two runs before it."""
    if len(priors) < REPEAT_RUNS - 1:
        return []
    window = priors[-(REPEAT_RUNS - 1):]
    out = []
    for cid, cur in sorted(current.items()):
        if all(cid in fails and fails[cid]["error_class"] == cur["error_class"] for _, fails in window):
            out.append({"case_id": cid, "error_class": cur["error_class"], "request_size": cur["request_size"],
                        "runs": [r for r, _ in window] + [run_id]})
    return out


def _vision_parts(run: LoadedRun) -> tuple[dict[str, list[str]], dict[str, dict[str, str]], dict[str, Any] | None,
                                          list[str], list[str]]:
    """The two blocking vision lists, their annotations, the non-blocking unmapped-label listing, the
    acknowledged disagreements (T112 4(a): listed, not counted) and any acknowledgement-record errors."""
    images = run.view.vision
    if images is None or run.view.vision_errors:
        return {}, {}, None, [], []
    acked, ack_errors = acknowledged_images(run.producer, images)
    failed = sorted((i for i in images if i.failed), key=lambda i: i.file_id)
    every = sorted((i for i in images if not i.failed and i.agree is False), key=lambda i: i.file_id)
    dis = [i for i in every if i.file_id not in acked]
    lists = {"vision_failed_readings": [i.file_id for i in failed]}
    if not ack_errors:  # an unreadable acknowledgement record leaves the count not computed, never 0
        lists["vision_unresolved_disagreements"] = [i.file_id for i in dis]
    notes = {"vision_failed_readings": {i.file_id: ", ".join(i.failure_reasons) for i in failed},
             "vision_unresolved_disagreements": {i.file_id: ", ".join(d.display() for d in i.disagreements)
                                                 for i in dis}}
    labels = [f"{i.file_id}:{shown(r.label)}" for i in images for r in i.resource_ids if not r.mapped]
    unmapped = {"count": len(labels), "labels": labels, "blocks": False,
                "why": "a label is not a resource ID: it gives no step by itself"}
    return lists, notes, unmapped, sorted(acked), ack_errors


def freeze_check(run_id: str, *, runs_root: Path = RUNS, approved_record: Path | None = None,
                 prior_run_ids: Sequence[str] = ()) -> dict[str, Any]:
    """Compute the freeze record for one run (never raises on bad artifacts; reports them).

    ``approved_record`` defaults to :data:`APPROVED_RECORD` (``notes/approved_output.json``).
    ``prior_run_ids`` are earlier runs of the same command, oldest first (T110 (2) repeat stop)."""
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
    record_path = approved_record or APPROVED_RECORD
    try:
        out_bytes: bytes | None = (run.run_dir / OUTPUT_FILE).read_bytes()
    except OSError:
        out_bytes = None
    fc_accepted, fc_rule, fc_errors = accepted_failed_closed(record_path, out_bytes, fc_cases)
    errors += fc_errors
    if record_ok:
        counts["failed_closed_rows"] = len([c for c in fc_cases if c not in fc_accepted])
        case_lists["failed_closed_rows"] = [c for c in fc_cases if c not in fc_accepted]
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
    fails = failed_cases(run)
    notes: dict[str, dict[str, str]] = {}
    if fails is not None:
        counts["agent_failed_cases"], case_lists["agent_failed_cases"] = len(fails), sorted(fails)
        notes["agent_failed_cases"] = {c: f["error_class"] for c, f in fails.items()}
    skips, serr = _skips(run.producer)
    errors += serr
    counts["evidence_skips"] = skips
    case_lists["evidence_skips"] = [str(x).split(":")[0] for x in run.producer.get("evidence_skipped") or []]
    vlists, vnotes, unmapped, acked, ack_errors = _vision_parts(run)
    errors += ack_errors
    for k, ids in vlists.items():
        counts[k], case_lists[k] = len(ids), ids
    notes.update(vnotes)
    priors: list[tuple[str, dict[str, dict[str, Any]]]] = []
    for pid in prior_run_ids:
        pf = failed_cases(load_run(runs_root, pid))
        if pf is None:
            errors.append(f"prior run {pid}: agent blocks unreadable, so the repeat-failure stop cannot be checked")
        else:
            priors.append((pid, pf))
    stops = repeat_failures(fails or {}, priors, run_id) if len(priors) == len(prior_run_ids) else []

    def listed(k: str) -> str:
        return ", ".join(f"{x} [{notes[k][x]}]" if x in notes.get(k, {}) else x for x in case_lists[k][:SAMPLE])

    refusals = [f"{k} = {n} (e.g. {listed(k)})" for k, n in counts.items() if n]
    if counts["agent_failed_cases"]:
        refusals.append(f"agent_failed_cases: {RERUN_REMEDY}" if not stops else
                        f"agent_failed_cases: {STOP}: {len(stops)} case(s) failed with the same error class on "
                        f"{REPEAT_RUNS} runs in a row; do not re-run again until the developer rules (T110 (2))")
    refusals += [f"{k}: not computed (see errors)" for k, n in counts.items() if n is None]
    refusals += [f"error: {e}" for e in errors]
    approved = approved_output_check(run.producer_check["pred_sha256"], record_path)
    if approved["error"]:
        refusals.append(f"approved output: {approved['error']}")
    elif not approved["matches"]:
        refusals.append(f"approved output: the run's output sha256 {approved['output_sha256']} differs from the "
                        f"approved {approved['approved_sha256']} (T101) and from the provisional "
                        f"{approved['provisional_sha256']} (T119)")
    return {"run_id": run_id, "kind": "freeze-check", "checked_at": runs.now_ist(), "producer_check": pstatus,
            "output_sha256": run.producer_check["pred_sha256"], "approved_output": approved, "counts": counts,
            "lower_bounds_when_not_computed": lower_bounds,
            "ids": {k: v for k, v in case_lists.items() if v}, "agent_failed": list((fails or {}).values()),
            "vision_unmapped_labels": unmapped, "vision_acknowledged_disagreements": acked,
            "failed_closed_accepted": {"cases": fc_accepted, "rule": fc_rule},
            "prior_run_ids": list(prior_run_ids),
            "stop_for_developer": stops, "result": STOP if stops else ("REFUSED" if refusals else "PASSED"),
            "errors": errors, "refusals": refusals, "passed": not refusals and not stops}


def main(argv: list[str] | None = None) -> int:
    """Run the freeze check; exit 0 on pass, 1 on refusal (each failing count named)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True, help="the run to check (runs/<id>/)")
    ap.add_argument("--prior-run-id", action="append", default=[], metavar="RUN_ID",
                    help="an earlier run of the same command, oldest first (repeatable; T110 (2) repeat stop)")
    ap.add_argument("--record-run-id", help="also write runs/<id>/freeze_check.json under this separate run ID")
    a = ap.parse_args(argv)
    res = freeze_check(a.run_id, runs_root=RUNS, prior_run_ids=a.prior_run_id)
    print(f"freeze check {res['run_id']}: producer check {res['producer_check']}")
    floors = res["lower_bounds_when_not_computed"]
    for k, n in res["counts"].items():
        floor = f" (record-level floor: at least {floors[k]})" if k in floors else ""
        print(f"  {k}: {'not computed' if n is None else n}{floor}")
    if res["vision_acknowledged_disagreements"]:
        print(f"  vision disagreements acknowledged (T112 4(a); not counted): "
              f"{', '.join(res['vision_acknowledged_disagreements'])}")
    um = res["vision_unmapped_labels"]
    print(f"  vision_unmapped_labels (listed, not blocking): {'not computed' if um is None else um['count']}"
          + (f" ({', '.join(um['labels'][:SAMPLE])})" if um and um["labels"] else ""))
    acc = res["failed_closed_accepted"]
    if acc["cases"]:
        print(f"  FAILED_CLOSED rows accepted ({(acc['rule'] or {}).get('ruling')}; identical to the approved "
              f"{str((acc['rule'] or {}).get('sha256'))[:16]}...; not counted): {', '.join(acc['cases'])}")
    ap_out = res["approved_output"]
    print(f"  output sha256:   {ap_out['output_sha256']}")
    verdict = ap_out["error"] or (f"match: {ap_out['matched']}" if ap_out["matches"] else "MISMATCH")
    print(f"  approved sha256: {ap_out['approved_sha256']} ({verdict})")
    if ap_out.get("provisional"):
        prov = ap_out["provisional"]
        print(f"  provisional sha256: {ap_out['provisional_sha256']} (run {prov.get('run_id')}, {prov.get('ruling')}; "
              f"scope: {prov.get('scope')})")
    if a.record_run_id:
        d = run_path(RUNS, a.record_run_id)
        if d == run_path(RUNS, a.run_id) or (d / OUTPUT_FILE).exists():
            print("refused to write the record into a producer run; give it its own run ID", file=sys.stderr)
            return 1
        d.mkdir(parents=True, exist_ok=True)
        runs.write_json(d / "freeze_check.json", res)
    if res["stop_for_developer"]:
        print(f"{STOP}: the same case failed with the same error class on {REPEAT_RUNS} runs in a row (T110 (2)). "
              "No option clears this; it needs the developer's ruling.")
        for x in res["stop_for_developer"]:
            size = x["request_size"]["max_logged_input_tokens"]
            print(f"  case {x['case_id']}: error class {x['error_class']}; request size "
                  f"{NOT_RECORDED if size is None else f'{size} input tokens (largest logged)'}; "
                  f"runs {', '.join(x['runs'])}")
        for r in res["refusals"]:
            print(f"  also: {r}")
        return EXIT_STOP
    if res["passed"]:
        print(f"FREEZE CHECK PASSED: all {len(COUNTS)} blocking counts are 0 on a checked run whose output is the "
              f"approved file ({res['approved_output']['matched']})")
        return 0
    print("FREEZE CHECK REFUSED:")
    for r in res["refusals"]:
        print(f"  {r}")
    return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
