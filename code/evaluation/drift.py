"""Drift table: predicted label distributions (e.g. on the test output) against DEV gold.

A gap over the threshold (15 percentage points by default) is flagged for a human to
explain. It is a prompt to look for a bug or a population difference, never a target:
changing rules so that predicted frequencies match gold's is forbidden (../CLAUDE.md
section 4, "matching gold's class frequencies").
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .contract import OPERATIONS, PHASES, STATUSES
from .gold import GoldCase
from .outputs import OutputRow

DIMENSIONS: tuple[str, ...] = ("status", "phase", "operation", "system_id", "steps_per_case")


def _bucket(n: int) -> str:
    return "0" if n == 0 else "1-3" if n <= 3 else "4-7" if n <= 7 else "8+"


def distributions(rows: Iterable[tuple[str, list[Any]]]) -> dict[str, dict[str, float]]:
    """Percent distributions per dimension. Status and steps-per-case are per case; the
    step dimensions are per step."""
    counts: dict[str, Counter[str]] = {d: Counter() for d in DIMENSIONS}
    n_cases = 0
    for status, steps in rows:
        n_cases += 1
        counts["status"][status] += 1
        counts["steps_per_case"][_bucket(len(steps))] += 1
        for s in steps:
            if isinstance(s, Mapping):
                counts["phase"][str(s.get("phase"))] += 1
                counts["operation"][str(s.get("operation"))] += 1
                counts["system_id"][str(s.get("system_id"))] += 1
    out: dict[str, dict[str, float]] = {}
    for d, c in counts.items():
        total = sum(c.values())
        out[d] = {k: 100.0 * v / total for k, v in c.items()} if total else {}
    return out


def drift_table(preds: Mapping[str, OutputRow], gold: Mapping[str, GoldCase],
                threshold_pts: float = 15.0) -> list[dict[str, Any]]:
    """One row per (dimension, label) seen on either side, with the gap in points."""
    pd = distributions((r.status, r.steps or []) for r in preds.values())
    gd = distributions((g.status, g.steps) for g in gold.values())
    order = {"status": list(STATUSES), "phase": list(PHASES), "operation": list(OPERATIONS),
             "steps_per_case": ["0", "1-3", "4-7", "8+"]}
    table = []
    for d in DIMENSIONS:
        labels = set(pd.get(d, {})) | set(gd.get(d, {}))
        ranked = [x for x in order.get(d, []) if x in labels] + sorted(labels - set(order.get(d, [])))
        for label in ranked:
            p, g = pd.get(d, {}).get(label, 0.0), gd.get(d, {}).get(label, 0.0)
            table.append({"dimension": d, "label": label, "pred_pct": round(p, 1), "gold_pct": round(g, 1),
                          "gap_pts": round(p - g, 1), "flag": abs(p - g) > threshold_pts})
    return table


def format_table(table: list[dict[str, Any]]) -> str:
    """Markdown rendering of a drift table."""
    lines = ["| dimension | label | predicted % | DEV gold % | gap (pts) | flag |", "|---|---|---:|---:|---:|---|"]
    for r in table:
        flag = "**>15**" if r["flag"] else ""
        lines.append(f"| {r['dimension']} | {r['label']} | {r['pred_pct']} | {r['gold_pct']} | {r['gap_pts']} "
                     f"| {flag} |")
    return "\n".join(lines)
