"""Scorer: compares predicted rows with gold rows, case by case, then aggregates.

The published metric names (organiser text, untrusted; treated as hypotheses):
``problem_statement.md`` asks for case-level status accuracy, step-level and field-level
accuracy and sequence accuracy, and says scoring considers cited evidence. ``README.md``
asks for case, row, field and sequence accuracy. Neither defines them, and G1
(``notes/CONTRACT_DRAFT.md``) recorded no reading of the metric definitions; it settled only
that ``steps_json`` is compared after JSON parsing (key order and whitespace ignored, array
order kept: F22, F23, A11). The readings below are therefore ours. Each names its
alternative, and the most likely alternatives are computed too, so a reader can pick.

Published metrics (``aggregate()['published']``):

* **status**: share of cases whose ``deletion_status`` equals gold; plus a confusion
  matrix with MISSING (no predicted row) and INVALID (not one of the three statuses).
  Two readings are recorded for a row whose ``steps_json`` does not parse to a JSON list
  (verifier finding M2): (a) ``status_accuracy``, the headline, compares its status like
  any other row, so the status is credited; (c) ``status_accuracy_unparseable_wrong``
  counts such a row as status-wrong. They differ only when an unparseable row has the
  right status. A missing row is status-wrong under both.
* **row (exact)**: share of cases whose whole row equals gold: status equal AND the parsed
  ``steps_json`` equal as JSON values (dict key order ignored, list order kept).
  Alternative: the steps alone (``steps_exact``), also reported. They differ only when the
  steps match but the status does not.
* **step**: predicted and gold steps matched as multisets on the key
  (``phase``, ``operation``, ``system_id``, ``resource_id``). Precision, recall and F1, micro
  over all cases and per operation. Alternative: matching on the full step minus
  ``step_no`` (the prep replay's definition), reported under ``prep``.
* **field**: on key-matched steps, the share with equal ``state``, ``evidence_id`` and
  ``step_no``, each separately and all three together. Alternative: position-aligned
  comparison of all 7 fields over max(len) slots (the prep replay's), under ``prep``.
* **sequence**: (a) exact-order rate: the ordered list of step keys equals gold's; (b)
  pairwise order accuracy: over matched steps, the share of step pairs whose relative order
  agrees with gold (Kendall-tau concordance; micro over all pairs). We chose (b) because it
  measures order alone: missing or extra steps are already charged by step recall and
  precision, and an edit-distance ratio would charge them twice. Cases with fewer than 2
  matched steps add no pairs, and their count is reported.
* **citations**: on matched steps whose gold ``evidence_id`` is non-empty, the share cited
  equal; plus, per case, whether the set of non-empty cited IDs equals gold's, and micro
  precision/recall over (case, evidence_id) pairs.

Prep-replay metrics (``aggregate()['prep']``), kept for continuity with
``research/15_exact_replay_dev.md`` section 1 and ``research/prototype/score.py``: status
exact, case exact, steps exact, sequence exact, the 6-field step-tuple multiset, positional
field accuracy and the (system_id, resource_id) resource sets.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .contract import OPERATIONS, STATUSES, STEP_KEYS, hashable, step_key
from .gold import GoldCase
from .outputs import OutputRow

MATCH_FIELDS: tuple[str, ...] = ("state", "evidence_id", "step_no")
PREP_TUPLE_FIELDS: tuple[str, ...] = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")


def _get(step: Any, key: str) -> Any:
    return step.get(key) if isinstance(step, Mapping) else None


def _occurrence_keys(steps: list[Any]) -> list[tuple[tuple[Any, ...], int]]:
    """Each step's key plus its occurrence number, so duplicate keys match one to one."""
    seen: Counter = Counter()
    out = []
    for s in steps:
        k = step_key(s)
        out.append((k, seen[k]))
        seen[k] += 1
    return out


def match_steps(pred: list[Any], gold: list[Any]) -> list[tuple[int, int]]:
    """Return (pred index, gold index) pairs of key-matched steps, in gold order."""
    p_index = {ok: i for i, ok in enumerate(_occurrence_keys(pred))}
    pairs = []
    for gi, ok in enumerate(_occurrence_keys(gold)):
        if ok in p_index:
            pairs.append((p_index[ok], gi))
    return pairs


def pairwise_order(pairs: list[tuple[int, int]]) -> tuple[int, int]:
    """(concordant pairs, total pairs) over matched steps; ``pairs`` is in gold order."""
    p = [pi for pi, _ in pairs]
    conc = total = 0
    for i in range(len(p)):
        for j in range(i + 1, len(p)):
            total += 1
            conc += p[i] < p[j]
    return conc, total


def _prep_tuple(step: Any) -> tuple[Any, ...]:
    return tuple(hashable(_get(step, k)) for k in PREP_TUPLE_FIELDS)


def _resources(steps: list[Any]) -> set[tuple[Any, Any]]:
    return {(hashable(_get(s, "system_id")), hashable(_get(s, "resource_id"))) for s in steps}


def _citations(steps: list[Any]) -> set[str]:
    return {e for e in (_get(s, "evidence_id") for s in steps) if isinstance(e, str) and e}


@dataclass(frozen=True)
class _Pred:
    status: str
    steps: list[Any]
    valid: bool        # a row exists and its steps_json parsed to a list
    reason: str | None


def _normalize_pred(pred: OutputRow | None) -> _Pred:
    if pred is None:
        return _Pred("MISSING", [], False, "no predicted row")
    if pred.steps is None:
        return _Pred(pred.status, [], False, pred.parse_error)
    return _Pred(pred.status, pred.steps, True, None)


def score_case(pred_row: OutputRow | None, gold: GoldCase) -> dict[str, Any]:
    """Score one case.

    A missing prediction scores as wrong everywhere. An unparseable prediction (its
    ``steps_json`` is not a JSON list) counts as zero predicted steps, so every step,
    field, sequence and citation metric charges it, and ``steps_exact``/``row_exact``
    are false; but its status is still compared and credited when equal (reading (a),
    ``status_ok``). Reading (c), where such a row is status-wrong, is
    ``status_ok_unparseable_wrong``.
    """
    p = _normalize_pred(pred_row)
    gs, ps = gold.steps, p.steps
    pairs = match_steps(ps, gs)
    matched_p = {pi for pi, _ in pairs}
    matched_g = {gi for _, gi in pairs}

    field_eq = {f: sum(_get(ps[pi], f) == gs[gi][f] for pi, gi in pairs) for f in MATCH_FIELDS}
    all_eq = sum(all(_get(ps[pi], f) == gs[gi][f] for f in MATCH_FIELDS) for pi, gi in pairs)
    cite_pairs = [(pi, gi) for pi, gi in pairs if gs[gi]["evidence_id"]]
    cite_eq = sum(_get(ps[pi], "evidence_id") == gs[gi]["evidence_id"] for pi, gi in cite_pairs)
    conc, total_pairs = pairwise_order(pairs)

    op_counts: dict[str, list[int]] = {}
    for gi, g in enumerate(gs):
        op_counts.setdefault(g["operation"], [0, 0, 0])[2] += 1
        if gi in matched_g:
            op_counts[g["operation"]][0] += 1
    for s in ps:
        op = _get(s, "operation")
        op_counts.setdefault(op if isinstance(op, str) else "<invalid>", [0, 0, 0])[1] += 1

    # prep-replay definitions (research/prototype/score.py), re-implemented
    pt, gt = Counter(_prep_tuple(s) for s in ps), Counter(_prep_tuple(s) for s in gs)
    n_slots = max(len(ps), len(gs))
    pos_hits = sum(
        sum(_get(ps[i], k) == gs[i][k] for k in STEP_KEYS)
        for i in range(min(len(ps), len(gs)))
    )
    pr, gr = _resources(ps), _resources(gs)
    pc, gc = _citations(ps), _citations(gs)

    status_ok = p.status == gold.status
    status_ok_strict = status_ok and p.valid  # reading (c): an unparseable row is status-wrong
    steps_exact = p.valid and ps == gs
    field_mismatches = [
        {"key": list(step_key(gs[gi])), "field": f, "pred": _get(ps[pi], f), "gold": gs[gi][f]}
        for pi, gi in pairs for f in MATCH_FIELDS if _get(ps[pi], f) != gs[gi][f]
    ]
    return {
        "case_id": gold.case_id,
        "pred_status": p.status,
        "gold_status": gold.status,
        "pred_valid": p.valid,
        "pred_invalid_reason": p.reason,
        "status_ok": status_ok,
        "status_ok_unparseable_wrong": status_ok_strict,
        "steps_exact": steps_exact,
        "row_exact": status_ok and steps_exact,
        "n_pred": len(ps),
        "n_gold": len(gs),
        "step_tp": len(pairs),
        "per_op": op_counts,
        "field_eq": field_eq,
        "field_all_eq": all_eq,
        "cite_steps": len(cite_pairs),
        "cite_eq": cite_eq,
        "order_exact": p.valid and [step_key(s) for s in ps] == [step_key(s) for s in gs],
        "order_concordant": conc,
        "order_pairs": total_pairs,
        "citation_set_exact": p.valid and pc == gc,
        "cite_tp": len(pc & gc),
        "cite_pred": len(pc),
        "cite_gold": len(gc),
        "prep_tuple_tp": sum((pt & gt).values()),
        "prep_pos_hits": pos_hits,
        "prep_pos_slots": n_slots * len(STEP_KEYS),
        "res_tp": len(pr & gr),
        "res_pred": len(pr),
        "res_gold": len(gr),
        "diff": {
            "missing_steps": [list(step_key(gs[gi])) for gi in range(len(gs)) if gi not in matched_g],
            "extra_steps": [list(step_key(ps[pi])) for pi in range(len(ps)) if pi not in matched_p],
            "field_mismatches": field_mismatches,
            "missing_resources": sorted(map(list, gr - pr), key=str),
            "extra_resources": sorted(map(list, pr - gr), key=str),
            "missing_citations": sorted(gc - pc),
            "extra_citations": sorted(pc - gc),
        },
    }


def _rate(n: int, of: int) -> dict[str, Any]:
    return {"n": n, "of": of, "rate": (n / of) if of else None}


def _prf(tp: int, n_pred: int, n_gold: int) -> dict[str, Any]:
    """Precision, recall, F1. Undefined parts are None; F1 is 0.0 if either side scores 0."""
    p = tp / n_pred if n_pred else None
    r = tp / n_gold if n_gold else None
    if p is None and r is None:
        f1 = None
    elif not p or not r:
        f1 = 0.0
    else:
        f1 = 2 * p * r / (p + r)
    return {"tp": tp, "pred": n_pred, "gold": n_gold, "precision": p, "recall": r, "f1": f1}


def confusion(cases: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """gold status -> predicted status -> count; predicted labels add MISSING and INVALID."""
    labels = list(STATUSES) + ["INVALID", "MISSING"]
    out = {g: {p: 0 for p in labels} for g in STATUSES}
    for c in cases:
        ps = c["pred_status"]
        ps = ps if ps in STATUSES or ps == "MISSING" else "INVALID"
        out.setdefault(c["gold_status"], {p: 0 for p in labels})[ps] += 1
    return out


def aggregate(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case scores into the published and prep-replay metric blocks."""
    n = len(cases)
    s = lambda k: sum(int(c[k]) for c in cases)  # noqa: E731
    per_op: dict[str, list[int]] = {}
    for c in cases:
        for op, (tp, np_, ng) in c["per_op"].items():
            acc = per_op.setdefault(op, [0, 0, 0])
            acc[0] += tp; acc[1] += np_; acc[2] += ng
    ordered_ops = [op for op in OPERATIONS if op in per_op] + sorted(op for op in per_op if op not in OPERATIONS)
    matched = s("step_tp")
    eligible = sum(1 for c in cases if c["order_pairs"] > 0)
    return {
        "cases": n,
        "published": {
            "status_accuracy": _rate(s("status_ok"), n),
            "status_accuracy_unparseable_wrong": _rate(s("status_ok_unparseable_wrong"), n),
            "status_confusion": confusion(cases),
            "row_exact": _rate(s("row_exact"), n),
            "steps_exact": _rate(s("steps_exact"), n),
            "step": _prf(matched, s("n_pred"), s("n_gold")),
            "step_per_operation": {op: _prf(*per_op[op]) for op in ordered_ops},
            "field_on_matched": {
                **{f: _rate(sum(c["field_eq"][f] for c in cases), matched) for f in MATCH_FIELDS},
                "all_three": _rate(s("field_all_eq"), matched),
            },
            "sequence_exact": _rate(s("order_exact"), n),
            "sequence_pairwise_order": {
                **_rate(s("order_concordant"), s("order_pairs")),
                "cases_with_pairs": eligible,
                "cases_without_pairs": n - eligible,
            },
            "citation_on_cited_steps": _rate(s("cite_eq"), s("cite_steps")),
            "citation_set_exact": _rate(s("citation_set_exact"), n),
            "citation_ids": _prf(s("cite_tp"), s("cite_pred"), s("cite_gold")),
        },
        "prep": {
            "status_exact": _rate(s("status_ok"), n),
            "case_exact": _rate(s("row_exact"), n),
            "steps_exact": _rate(s("steps_exact"), n),
            "sequence_exact": _rate(s("order_exact"), n),
            "step_tuple": _prf(s("prep_tuple_tp"), s("n_pred"), s("n_gold")),
            "field_positional": _rate(s("prep_pos_hits"), s("prep_pos_slots")),
            "resources": _prf(s("res_tp"), s("res_pred"), s("res_gold")),
        },
    }


def score_predictions(preds: Mapping[str, OutputRow], gold: Mapping[str, GoldCase]) -> dict[str, Any]:
    """Score every gold case; predictions for non-gold cases are listed, never scored."""
    cases = [score_case(preds.get(cid), gold[cid]) for cid in sorted(gold)]
    return {
        "aggregate": aggregate(cases),
        "cases": cases,
        "pred_cases_not_in_gold": len(set(preds) - set(gold)),
        "gold_cases_without_pred": sorted(set(gold) - set(preds)),
        "invalid_pred_cases": [c["case_id"] for c in cases if not c["pred_valid"]],
    }
