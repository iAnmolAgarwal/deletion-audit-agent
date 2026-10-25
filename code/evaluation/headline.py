"""The generated headline block at the top of both reports (T111 (2)).

Every number is read from the data the two reports are rendered from (``evaluation_report``
and ``usage_report`` dicts, and the final run's own artifacts), and each names its run. A number
that is not available yet says **"not run yet"** with the reason, never 0:

* DEV status accuracy, row exact and step F1: the spec's DEV run, scored against DEV gold;
* test rows by status: the final run's ``output.csv``; FAILED_CLOSED rows: its ``cases.jsonl``,
  cross-checked against its pipeline-written ``metrics.json`` (report section 7);
* two tool-use rates, over the final run's cases: cases whose agent block records an ``audit_case``
  call (``audit_case_calls`` > 0), and cases with a call to any other read-only tool
  (``agent_report.READ_ONLY_TOOLS``, from ``tool_calls``); a tool name outside both sets is counted
  on its own. Each names the run, its mode and whether it was replay-only. Both are not run yet when
  the records carry no agent block, or when the run used no model reply at all (then the model
  never ran, so a 0 would be no measurement);
* tools on vs tools off: the agent report's DEV arm deltas (``A+``/``A`` minus ``tools_off``); not
  run yet without a ``tools_off`` arm;
* total cost: what the replies the final output used originally cost (usage report part (a)),
  the run IDs that bought them, and per case over the final run's rows; plus the final run's own
  sends (part (b)). Not run yet when the usage run used no model reply and sent nothing;
* the holdout: its completed record's headline, or not run yet; always with ``split.json``'s caveat.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from .agent_report import AGENT_KEY, AUDIT_CASE_TOOL, READ_ONLY_TOOLS, LoadedRun, rate_text

NOT_RUN = "not run yet"


def _rate(x: Mapping[str, Any] | None) -> str:
    if not x or not x.get("of"):
        return NOT_RUN
    return f"{x['n']}/{x['of']} ({x['n'] / x['of']:.4f})"


def tool_use(final: LoadedRun) -> dict[str, Any]:
    """The final run's two tool-use rates from its agent blocks; or why they are not available."""
    v = final.view
    p = final.producer
    facts = {"run_id": final.run_id, "mode": p.get("mode"), "replay_only": p.get("replay_only"),
             "paid_model_calls": p.get("paid_model_calls")}
    errs = [*v.record_errors, *v.agent_errors]
    if errs and all(e.problem.startswith("missing") and e.path in (AGENT_KEY, "<file>") for e in errs):
        return {**facts, "available": False, "why": "the run's cases.jsonl records carry no agent block"}
    if errs:
        return {**facts, "available": False, "why": f"{len(errs)} adapter error(s) in cases.jsonl"}
    agents = [c.agent for c in v.cases.values()]
    if not agents or any(a is None for a in agents):
        return {**facts, "available": False, "why": "the run's cases.jsonl records carry no agent block"}
    av = [a for a in agents if a is not None]
    return {**facts, "available": True, "cases": len(av),
            "cases_with_audit_case": sum(1 for a in av if a.audit_case_calls > 0),
            "cases_with_read_only_tool": sum(1 for a in av if any(t.name in READ_ONLY_TOOLS for t in a.tool_calls)),
            "cases_with_unknown_tool": sum(1 for a in av if any(t.name not in READ_ONLY_TOOLS for t in a.tool_calls))}


def build_headline(ev: Mapping[str, Any], us: Mapping[str, Any], final: LoadedRun) -> dict[str, Any]:
    """The headline's data (module docstring)."""
    d = ev["dev"]
    p = d["published"]
    assert final.output is not None
    by_status = dict(sorted(Counter(r.status for r in final.output.rows.values()).items()))
    val: Mapping[str, Any] = next((x for x in ev["validator"] if x.get("run_id") == final.run_id), {})
    fc = val.get("failed_closed_from_cases_jsonl")
    agent = ev.get("agent") or {}
    deltas = ((agent.get("report") or {}).get("arm_deltas") or {}).get("dev_delta_vs_tools_off") or {}
    a, b = us["a_replies_used"], us["b_own_calls"]
    rows = len(final.output.rows)
    cost_a = a["total"]["cost_settled_usd"]
    no_model = a["replies_used"] == 0 and b["send_attempts"] == 0
    tu = tool_use(final)
    if tu["available"] and no_model and us["run_id"] == final.run_id:
        tu = {**tu, "available": False, "why": "the run used no model reply (0 replies used, 0 sends), so the model "
                                               "never ran"}
    h = ev["holdout"]
    rec = h.get("headline") or {}
    return {
        "dev": {"run_id": d["run_id"], "status": p["status_accuracy"], "row_exact": p["row_exact"],
                "step_f1": p["step"]["f1"]},
        "test": {"run_id": final.run_id, "rows": rows, "by_status": by_status,
                 "failed_closed": None if fc is None else fc["count"],
                 "failed_closed_by_reason": None if fc is None else fc["by_reason"]},
        "tool_use": tu,
        "tools_delta": deltas,
        "cost": {"usage_run": us["run_id"], "is_final_run": us["run_id"] == final.run_id, "no_model": no_model,
                 "replies_used": a["total"]["replies"], "replies_unresolved": a["replies_unresolved"],
                 "cost_replies_used_usd": cost_a, "bought_by": sorted(a["by_buying_run"]),
                 "rows": rows, "per_case_usd": None if cost_a is None or not rows else cost_a / rows,
                 "own_send_attempts": b["send_attempts"], "own_cost_usd": b["cost_usd"]},
        "holdout": {"run_id": h.get("run_id"), "status": rec.get("status_accuracy"),
                    "row_exact": rec.get("row_exact"), "step_f1": (rec.get("step") or {}).get("f1"),
                    "caveat": h["caveat"], "caveat_source": h["caveat_source"]},
    }


def _usd(v: float | None) -> str:
    return "unknown" if v is None else f"${v:.6f}"


def render_headline(h: Mapping[str, Any]) -> list[str]:
    """The headline block's Markdown lines, from :func:`build_headline`'s dict only."""
    d, t, tu, c, ho = h["dev"], h["test"], h["tool_use"], h["cost"], h["holdout"]
    f1 = "n/a" if d["step_f1"] is None else f"{d['step_f1']:.4f}"
    status_s = ", ".join(f"{k} {n}" for k, n in t["by_status"].items()) or "none"
    fc_s = NOT_RUN + " (cases.jsonl unreadable)" if t["failed_closed"] is None else \
        f"{t['failed_closed']} (by reason {t['failed_closed_by_reason'] or {}})"
    if tu["available"]:
        of = tu["cases"]
        how = (f"mode {tu['mode']}, {'replay-only' if tu['replay_only'] else 'not replay-only'}, paid model calls "
               f"{tu['paid_model_calls']}")
        tu_audit = f"{rate_text(tu['cases_with_audit_case'], of)} cases called {AUDIT_CASE_TOOL}; {how}"
        tu_other = (f"{rate_text(tu['cases_with_read_only_tool'], of)} cases called another read-only tool "
                    f"({', '.join(READ_ONLY_TOOLS)}); {how}")
        if tu["cases_with_unknown_tool"]:
            tu_other += f"; **{tu['cases_with_unknown_tool']} case(s) called a tool outside both sets**"
    else:
        tu_audit = tu_other = f"{NOT_RUN}: {tu['why']}"
    if h["tools_delta"]:
        td_s = "; ".join(f"{k}: status {v['status_n']:+d}, row exact {v['row_exact_n']:+d}, step F1 "
                         f"{'n/a' if v['step_f1'] is None else format(v['step_f1'], '+.4f')} (runs `{v['runs'][0]}` "
                         f"vs `{v['runs'][1]}`)" for k, v in h["tools_delta"].items())
        td_run = "DEV arms"
    else:
        td_s, td_run = f"{NOT_RUN}: the spec names no tools_off arm on DEV", "none"
    bought = ", ".join(f"`{r}`" for r in c["bought_by"]) or "none"
    per_case = NOT_RUN if c["per_case_usd"] is None else f"{_usd(c['per_case_usd'])} over {c['rows']} rows"
    cost_note = "" if c["is_final_run"] else " (**the usage run is not the final run**)"
    total_s = (f"{_usd(c['cost_replies_used_usd'])} for {c['replies_used']} replies ({c['replies_unresolved']} "
               f"unresolved), bought by {bought}{cost_note}")
    if c["no_model"]:
        total_s = f"{NOT_RUN}: the run used no model reply and sent nothing (0 replies, 0 sends){cost_note}"
        per_case = f"{NOT_RUN}: no model cost in this run"
    if ho["run_id"]:
        hf1 = "n/a" if ho["step_f1"] is None else f"{ho['step_f1']:.4f}"
        ho_s = f"status {_rate(ho['status'])}, row exact {_rate(ho['row_exact'])}, step F1 {hf1}"
        ho_run = f"`{ho['run_id']}`"
    else:
        ho_s, ho_run = f"{NOT_RUN} (no completed holdout record under runs/)", "none"
    return [
        "## Headline", "",
        "Generated from the same run artifacts as the sections below (code/evaluation/headline.py); every number "
        "names its run, and a number not yet available says so.", "",
        "| what | value | run |", "|---|---|---|",
        f"| DEV status accuracy | {_rate(d['status'])} | `{d['run_id']}` |",
        f"| DEV row exact | {_rate(d['row_exact'])} | `{d['run_id']}` |",
        f"| DEV step F1 | {f1} | `{d['run_id']}` |",
        f"| Test rows by status | {status_s} (of {t['rows']}) | `{t['run_id']}` |",
        f"| Test FAILED_CLOSED rows | {fc_s} | `{t['run_id']}` |",
        f"| Tool-use rate: audit_case | {tu_audit} | `{tu['run_id']}` |",
        f"| Tool-use rate: other read-only tools | {tu_other} | `{tu['run_id']}` |",
        f"| Tools on vs off (DEV) | {td_s} | {td_run} |",
        f"| Total cost: replies the final output used | {total_s} | `{c['usage_run']}` |",
        f"| Cost per case | {per_case} | `{c['usage_run']}` |",
        f"| The final run's own sends | {_usd(c['own_cost_usd'])} in {c['own_send_attempts']} send attempts | "
        f"`{c['usage_run']}` |",
        f"| Holdout | {ho_s} | {ho_run} |", "",
        f"> **Holdout caveat (verbatim from `{ho['caveat_source']}`):** {ho['caveat']}", "",
    ]
