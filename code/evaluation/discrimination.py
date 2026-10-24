"""Proof that the scorer discriminates: known-bad predictions must move the metrics.

Every variant is built in memory from DEV gold (never the holdout) and then serialized and
re-parsed through ``outputs.parse_steps``, the same path a prediction file takes:

* ``gold``                 identity; every published metric must be 1.0
* ``gold_reformatted``     keys reversed, whitespace added; must score exactly like gold
                           (the grader claim F22: key order and whitespace are ignored)
* ``majority_empty``       every case gets the majority DEV status and ``[]``
* ``drop_last_step``       last step removed, step numbers still consecutive
* ``extra_step``           one invented verification step appended
* ``swap_first_two``       first two steps swapped, step numbers rewritten (order only)
* ``wrong_state``          the first step's state replaced
* ``wrong_evidence``       every non-empty evidence_id replaced by another manifest file
* ``step_no_shift``        every step_no + 1
* ``flip_status``          COMPLETE <-> INCOMPLETE, steps untouched
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Any, Callable, Mapping

from .contract import STATES
from .gold import GoldCase
from .outputs import OutputRow, parse_steps
from .scorer import score_predictions

Steps = list[dict[str, Any]]


def _renumber(steps: Steps) -> Steps:
    for i, s in enumerate(steps, start=1):
        s["step_no"] = i
    return steps


def _row(case_id: str, status: str, steps: Steps, *, reformat: bool = False) -> OutputRow:
    if reformat:
        raw = json.dumps([dict(reversed(list(s.items()))) for s in steps], indent=2)
    else:
        raw = json.dumps(steps, separators=(",", ":"))
    parsed, err = parse_steps(raw)
    return OutputRow(case_id, status, parsed, raw, err)


def build_variants(gold: Mapping[str, GoldCase], file_ids: list[str]) -> dict[str, dict[str, OutputRow]]:
    """Return {variant name: {case_id: OutputRow}}; deterministic, no randomness."""
    majority = Counter(g.status for g in gold.values()).most_common(1)[0][0]
    files = sorted(file_ids)

    def other_file(fid: str) -> str:
        return files[(files.index(fid) + 1) % len(files)] if fid in files else files[0]

    def other_state(st: str) -> str:
        return sorted(STATES - {st})[0]

    def per_case(fn: Callable[[GoldCase, Steps], tuple[str, Steps]], **kw: Any) -> dict[str, OutputRow]:
        out = {}
        for cid, g in gold.items():
            status, steps = fn(g, copy.deepcopy(g.steps))
            out[cid] = _row(cid, status, steps, **kw)
        return out

    def swap(g: GoldCase, s: Steps) -> tuple[str, Steps]:
        if len(s) >= 2:
            s[0], s[1] = s[1], s[0]
        return g.status, _renumber(s)

    def wrong_state(g: GoldCase, s: Steps) -> tuple[str, Steps]:
        if s:
            s[0]["state"] = other_state(s[0]["state"])
        return g.status, s

    def wrong_ev(g: GoldCase, s: Steps) -> tuple[str, Steps]:
        for x in s:
            if x["evidence_id"]:
                x["evidence_id"] = other_file(x["evidence_id"])
        return g.status, s

    def extra(g: GoldCase, s: Steps) -> tuple[str, Steps]:
        s.append({"step_no": 0, "phase": "VERIFICATION", "system_id": "search_service",
                  "resource_id": "search_0000000", "operation": "VERIFY_RECORD_ABSENT", "state": "ABSENT",
                  "evidence_id": ""})
        return g.status, _renumber(s)

    flip = {"COMPLETE": "INCOMPLETE", "INCOMPLETE": "COMPLETE", "NOT_APPLICABLE": "INCOMPLETE"}
    return {
        "gold": per_case(lambda g, s: (g.status, s)),
        "gold_reformatted": per_case(lambda g, s: (g.status, s), reformat=True),
        "majority_empty": per_case(lambda g, s: (majority, [])),
        "drop_last_step": per_case(lambda g, s: (g.status, _renumber(s[:-1]))),
        "extra_step": per_case(extra),
        "swap_first_two": per_case(swap),
        "wrong_state": per_case(wrong_state),
        "wrong_evidence": per_case(wrong_ev),
        "step_no_shift": per_case(lambda g, s: (g.status, [dict(x, step_no=x["step_no"] + 1) for x in s])),
        "flip_status": per_case(lambda g, s: (flip[g.status], s)),
    }


HEADLINE: tuple[tuple[str, ...], ...] = (
    ("published", "status_accuracy", "rate"),
    ("published", "row_exact", "rate"),
    ("published", "step", "f1"),
    ("published", "field_on_matched", "state", "rate"),
    ("published", "field_on_matched", "evidence_id", "rate"),
    ("published", "field_on_matched", "step_no", "rate"),
    ("published", "sequence_exact", "rate"),
    ("published", "sequence_pairwise_order", "rate"),
    ("published", "citation_set_exact", "rate"),
    ("prep", "field_positional", "rate"),
)


def dig(d: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    """Follow a key path into nested dicts."""
    for k in path:
        d = d[k]
    return d


def run(gold: Mapping[str, GoldCase], file_ids: list[str]) -> dict[str, Any]:
    """Score every variant; return {variant: {metric path: value}} plus full aggregates."""
    table, full = {}, {}
    for name, preds in build_variants(gold, file_ids).items():
        agg = score_predictions(preds, gold)["aggregate"]
        full[name] = agg
        table[name] = {".".join(p[1:]): dig(agg, p) for p in HEADLINE}
    return {"table": table, "aggregates": full}
