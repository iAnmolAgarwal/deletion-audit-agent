"""Production metrics with alert thresholds (research/18 I4), computed from one run's artifacts.

Written beside the reports as ``runs/<report_id>/metrics.json``; the run's own pipeline-written
``metrics.json`` is never touched. Each metric carries its value, the artifact it was read from,
its alert threshold, whether the alert fires, and why the threshold sits where it does. A value
that cannot be computed is ``null`` with the reason, and its alert is ``null`` (not computed),
never "not firing".

Metrics:

* ``fail_closed_rows``: cases whose ``row_state`` is FAILED_CLOSED or whose ``failed_closed``
  reason is set (``freeze_check.is_failed_closed``), by reason. Fires above 0 (T60, T87: zero at
  freeze).
* ``unresolved_open_questions``: open questions posed for a case (``open_questions`` in its
  ``cases.jsonl`` line) with no validated answer (``answers``). Fires above 0: each one is a
  slot the row was compiled without.
* ``tool_fire_rate``: cases with at least one tool call other than ``audit_case`` over cases
  with an agent block (``agent.tool_calls``). Fires above :data:`TOOL_RATE_ALERT`.
* ``status_mix_drift``: the largest change, in percentage points, of any status's share of the
  output rows against the previous run. Fires above :data:`DRIFT_ALERT_PTS`.
* ``rejected_post_audit_evidence``: model answers rejected as ``EVIDENCE_AFTER_AUDIT``
  (``agent.answers_rejected``) plus rows failed closed as ``POST_AUDIT_ONLY_FINDING``. Fires above
  0: either means post-audit evidence reached a decision point and was turned away.

The agent-derived metrics need every case of the run to carry a valid agent block (G7); a run
without them gets ``null`` and the reason, which is the state of every G5 run.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_report import CASES_FILE, OUTPUT_FILE, LoadedRun, summarize_errors
from .contract import STATUSES
from .freeze_check import is_failed_closed

# ---- the artifact contract this module reads beyond agent_report's adapter (reconcile at G7) ----
OPEN_QUESTIONS_KEY = "open_questions"   # cases.jsonl: oq_ids posed for the case
ANSWERS_KEY = "answers"                 # cases.jsonl: oq_ids with a validated answer
POST_AUDIT_REJECTION = "EVIDENCE_AFTER_AUDIT"
POST_AUDIT_FAILED_CLOSED = "POST_AUDIT_ONLY_FINDING"

# ---- alert thresholds ----
FAIL_CLOSED_ALERT = 0
OPEN_QUESTION_ALERT = 0
TOOL_RATE_ALERT = 0.05
DRIFT_ALERT_PTS = 15.0
POST_AUDIT_ALERT = 0
SAMPLE = 20  # case IDs listed per metric

BASIS = {
    "fail_closed_rows": "T60 and T87: FAILED_CLOSED rows must be 0 at freeze",
    "unresolved_open_questions": "an unanswered open question means the row was compiled without that slot",
    "tool_fire_rate": "notes/ARCHITECTURE_OPTIONS.md section 9 expects tools on a few image cases only; a rate "
                      "above the threshold means tools fire far more often than designed (cost and latency)",
    "status_mix_drift": "the drift threshold of ../CLAUDE.md (gaps over 15 points are flagged for a human; never "
                        "fixed by matching frequencies); here against the previous run, not gold",
    "rejected_post_audit_evidence": "evidence captured after audit_at may never decide a row; any rejection is "
                                    "worth reading, though the guard worked",
}


def _metric(name: str, value: Any, threshold: float, source: str, **extra: Any) -> dict[str, Any]:
    fires = None if value is None else value > threshold
    return {"value": value, "threshold": {"fires_when": "value >", "value": threshold}, "fires": fires,
            "basis": BASIS[name], "source": source, **extra}


def _raw_lines(run: LoadedRun) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    try:
        text = (run.run_dir / CASES_FILE).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, Mapping) and isinstance(raw.get("case_id"), str):
            out.setdefault(raw["case_id"], raw)
    return out


def _agent_unavailable(run: LoadedRun) -> str | None:
    """Why the agent-derived metrics cannot be computed for ``run``, or None."""
    v = run.view
    if v.record_errors:
        return f"{len(v.record_errors)} record error(s) in {CASES_FILE}"
    if v.agent_errors:
        groups = summarize_errors(v.agent_errors)
        what = "; ".join(f"{g['path']} {g['problem']} ({g['count']})" for g in groups[:3])
        return f"agent blocks missing or malformed: {what} (G7 wiring writes them)"
    if not v.cases:
        return f"{CASES_FILE} holds no case"
    return None


def status_shares(statuses: Sequence[str]) -> dict[str, float]:
    """Percent share of each status (the three statuses plus any other label seen)."""
    n = len(statuses)
    c = Counter(statuses)
    labels = [s for s in STATUSES] + sorted(set(c) - set(STATUSES))
    return {s: (100.0 * c[s] / n if n else 0.0) for s in labels}


def compute(run: LoadedRun, previous: LoadedRun | None) -> dict[str, Any]:
    """The five metrics for ``run`` (module docstring); ``previous`` feeds the drift metric."""
    v = run.view
    rid = run.run_id
    cases = sorted(v.cases.values(), key=lambda c: c.case_id)
    out: dict[str, Any] = {}
    # 1. fail-closed rows (record level: always computable unless the records are broken)
    if v.record_errors:
        out["fail_closed_rows"] = _metric("fail_closed_rows", None, FAIL_CLOSED_ALERT, f"runs/{rid}/{CASES_FILE}",
                                          error=f"{len(v.record_errors)} record error(s)")
    else:
        fc = [c for c in cases if is_failed_closed(c)]
        out["fail_closed_rows"] = _metric(
            "fail_closed_rows", len(fc), FAIL_CLOSED_ALERT, f"runs/{rid}/{CASES_FILE} row_state and failed_closed",
            of=len(cases), by_reason=dict(sorted(Counter(c.failed_closed or "ROW_STATE_ONLY" for c in fc).items())),
            case_ids=[c.case_id for c in fc][:SAMPLE])
    why = _agent_unavailable(run)
    # 2. unresolved open questions
    raw = _raw_lines(run)
    if why is None and all(isinstance(raw.get(c.case_id, {}).get(OPEN_QUESTIONS_KEY), list)
                           and isinstance(raw.get(c.case_id, {}).get(ANSWERS_KEY), list) for c in cases):
        per = {c.case_id: sorted(set(raw[c.case_id][OPEN_QUESTIONS_KEY]) - set(raw[c.case_id][ANSWERS_KEY]))
               for c in cases}
        bad = sorted(cid for cid, q in per.items() if q)
        out["unresolved_open_questions"] = _metric(
            "unresolved_open_questions", sum(len(q) for q in per.values()), OPEN_QUESTION_ALERT,
            f"runs/{rid}/{CASES_FILE} {OPEN_QUESTIONS_KEY} minus {ANSWERS_KEY}",
            posed=sum(len(raw[c][OPEN_QUESTIONS_KEY]) for c in per), cases_with_unresolved=len(bad),
            case_ids=bad[:SAMPLE])
    else:
        out["unresolved_open_questions"] = _metric(
            "unresolved_open_questions", None, OPEN_QUESTION_ALERT, f"runs/{rid}/{CASES_FILE}",
            error=why or f"{OPEN_QUESTIONS_KEY}/{ANSWERS_KEY} lists missing in some case lines")
    # 3. tool-fire rate
    if why is None:
        agents = [c.agent for c in cases if c.agent is not None]
        fired = [c.case_id for c in cases if c.agent is not None and c.agent.tool_calls]
        out["tool_fire_rate"] = _metric("tool_fire_rate", len(fired) / len(agents), TOOL_RATE_ALERT,
                                        f"runs/{rid}/{CASES_FILE} agent.tool_calls (audit_case excluded)",
                                        n=len(fired), of=len(agents), case_ids=fired[:SAMPLE])
    else:
        out["tool_fire_rate"] = _metric("tool_fire_rate", None, TOOL_RATE_ALERT, f"runs/{rid}/{CASES_FILE}",
                                        error=why)
    # 4. status-mix drift against the previous run
    if previous is None or run.output is None or previous.output is None:
        out["status_mix_drift"] = _metric("status_mix_drift", None, DRIFT_ALERT_PTS, f"runs/{rid}/{OUTPUT_FILE}",
                                          error="no previous run named in the spec" if previous is None
                                          else f"{OUTPUT_FILE} unreadable")
    else:
        now = status_shares([r.status for r in run.output.rows.values()])
        prev = status_shares([r.status for r in previous.output.rows.values()])
        labels = list(dict.fromkeys([*now, *prev]))
        by = {s: {"now_pct": round(now.get(s, 0.0), 2), "previous_pct": round(prev.get(s, 0.0), 2),
                  "gap_pts": round(now.get(s, 0.0) - prev.get(s, 0.0), 2)} for s in labels}
        out["status_mix_drift"] = _metric(
            "status_mix_drift", max(abs(x["gap_pts"]) for x in by.values()), DRIFT_ALERT_PTS,
            f"runs/{rid}/{OUTPUT_FILE} vs runs/{previous.run_id}/{OUTPUT_FILE} deletion_status shares",
            previous_run=previous.run_id, rows_now=len(run.output.rows), rows_previous=len(previous.output.rows),
            by_status=by)
    # 5. rejected post-audit evidence
    pa_fc = [] if v.record_errors else [c.case_id for c in cases if c.failed_closed == POST_AUDIT_FAILED_CLOSED]
    parts: dict[str, Any] = {"post_audit_only_findings": None if v.record_errors else len(pa_fc)}
    if why is None:
        parts["answers_rejected_evidence_after_audit"] = sum(
            1 for c in cases if c.agent for _, r in c.agent.answers_rejected if r == POST_AUDIT_REJECTION)
    else:
        parts["answers_rejected_evidence_after_audit"] = None
    known = [x for x in parts.values() if x is not None]
    total = sum(known) if len(known) == len(parts) else None
    m = _metric("rejected_post_audit_evidence", total, POST_AUDIT_ALERT,
                f"runs/{rid}/{CASES_FILE} agent.answers_rejected[].reason and failed_closed", parts=parts,
                case_ids=pa_fc[:SAMPLE])
    if total is None:
        floor = sum(known)
        m["lower_bound"] = floor
        m["fires"] = True if floor > POST_AUDIT_ALERT else None
        m["error"] = why or "record errors"
    out["rejected_post_audit_evidence"] = m
    return out


def build_metrics(entries: Sequence[tuple[str, LoadedRun, LoadedRun | None]], *, report_id: str, created_at: str,
                  command: str) -> dict[str, Any]:
    """The ``metrics.json`` document written beside the reports: one block per (role, run, previous run)."""
    blocks: list[dict[str, Any]] = []
    for role, run, previous in entries:
        metrics = compute(run, previous)
        blocks.append({"role": role, "run": run.run_id, "previous_run": previous.run_id if previous else None,
                       "metrics": metrics,
                       "alerts_firing": sorted(k for k, m in metrics.items() if m["fires"] is True),
                       "alerts_not_computed": sorted(k for k, m in metrics.items() if m["fires"] is None)})
    return {
        "report_id": report_id, "kind": "production-metrics", "created_at": created_at, "command": command,
        "source_runs": {b["role"]: {"run": b["run"], "previous_run": b["previous_run"]} for b in blocks},
        "note": "computed by code/evaluation/run_metrics.py from the named runs' artifacts; the runs' own "
                "pipeline-written metrics.json files are not this file",
        "runs": blocks,
        "alerts_firing": [f"{b['role']}:{k}" for b in blocks for k in b["alerts_firing"]],
        "alerts_not_computed": [f"{b['role']}:{k}" for b in blocks for k in b["alerts_not_computed"]],
    }
