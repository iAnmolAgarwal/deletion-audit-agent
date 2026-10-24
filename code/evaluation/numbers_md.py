"""Renders the generated block of ``code/evaluation/NUMBERS.md`` from ``runs/*/score.json``.

Only the text between the BEGIN and END markers is replaced; anything outside them is kept,
so people can add hand-written context around the generated numbers without losing it.
No number inside the block is typed by hand.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .paths import NUMBERS_MD, RUNS

BEGIN = "<!-- BEGIN GENERATED: evaluate.py numbers (do not edit by hand) -->"
END = "<!-- END GENERATED -->"

DEFAULT_HEAD = """# NUMBERS

Every number here carries its run ID, the command that produced it and what it measures
(the kit rules, ../../../CLAUDE.md section 4, outside this repo). The block between the markers is regenerated from
`runs/<run_id>/score.json` by `python3 -B code/evaluation/evaluate.py numbers`.
"""

METRIC_NOTES: list[tuple[str, str]] = [
    ("status", "cases whose deletion_status equals gold"),
    ("row exact", "status equal AND parsed steps_json equal (key order ignored, list order kept)"),
    ("steps exact", "parsed steps_json equal, status ignored (alternative reading of 'row')"),
    ("step P/R/F1", "multiset match on (phase, operation, system_id, resource_id), micro"),
    ("state / evidence / step_no", "field equality on key-matched steps"),
    ("seq exact", "ordered list of step keys equals gold's"),
    ("pairwise order", "concordant pairs / all pairs of matched steps (order only)"),
    ("citation set", "cases whose set of non-empty evidence_ids equals gold's"),
    ("prep tuple", "prep replay: multiset of 6-field tuples (step_no excluded), tp/gold"),
    ("prep fields", "prep replay: position-aligned 7-field hits / (max(len) x 7) slots"),
    ("prep resources", "prep replay: (system_id, resource_id) set, tp/gold"),
]


def _r(x: Mapping[str, Any]) -> str:
    return f"{x['n']}/{x['of']}" if x.get("of") else "n/a"


def _f(v: Any) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def score_row(s: Mapping[str, Any]) -> str:
    """One comparison-table row for a scored run."""
    p, q = s["aggregate"]["published"], s["aggregate"]["prep"]
    f, st = p["field_on_matched"], p["step"]
    cells = [
        f"`{s['run_id']}`", _r(p["status_accuracy"]), _r(p["row_exact"]), _r(p["steps_exact"]),
        f"{_f(st['precision'])} / {_f(st['recall'])} / {_f(st['f1'])}",
        _r(f["state"]), _r(f["evidence_id"]), _r(f["step_no"]), _r(p["sequence_exact"]),
        _r(p["sequence_pairwise_order"]), _r(p["citation_set_exact"]),
        f"{q['step_tuple']['tp']}/{q['step_tuple']['gold']}", _r(q["field_positional"]),
        f"{q['resources']['tp']}/{q['resources']['gold']}", f"{s['coherence']['hard']} / {s['coherence']['soft']}",
    ]
    return "| " + " | ".join(cells) + " |"


def discrimination_table(table: Mapping[str, Mapping[str, Any]]) -> str:
    """Markdown table of variant -> headline metrics."""
    names = list(table)
    metrics = list(table[names[0]]) if names else []
    lines = ["| variant | " + " | ".join(metrics) + " |", "|---|" + "---:|" * len(metrics)]
    for n in names:
        lines.append(f"| {n} | " + " | ".join(_f(v) for v in table[n].values()) + " |")
    return "\n".join(lines)


def _load_runs(runs_dir: Path) -> list[dict[str, Any]]:
    out = []
    for p in sorted(runs_dir.glob("*/score.json")):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if s.get("kind") in ("score", "discrimination"):
            inv = p.parent / "INVALID.txt"
            s["_invalid"] = inv.read_text(encoding="utf-8").strip() if inv.exists() else None
            out.append(s)
    return sorted(out, key=lambda s: (s.get("created_at", ""), s["run_id"]))


def render(runs_dir: Path = RUNS) -> str:
    """The generated block's markdown."""
    loaded = _load_runs(runs_dir)
    invalid = [s for s in loaded if s["_invalid"]]
    scored = [s for s in loaded if s["kind"] == "score" and not s["_invalid"]]
    discr = [s for s in loaded if s["kind"] == "discrimination" and not s["_invalid"]]
    L: list[str] = ["## Scored runs (DEV, 22 cases; holdout never loaded)", ""]
    L += ["| run | status | row exact | steps exact | step P / R / F1 | state | evidence | step_no | seq exact "
          "| pairwise order | citation set | prep tuple | prep fields | prep resources | coherence hard / soft |",
          "|---|" + "---:|" * 14]
    L += [score_row(s) for s in scored]
    L += ["", "Metric definitions (code: `code/evaluation/scorer.py`):", ""]
    L += [f"- **{k}**: {v}" for k, v in METRIC_NOTES]
    for s in scored:
        L += ["", f"### `{s['run_id']}`", "", f"- What: {s.get('description') or '(no description)'}",
              f"- Scored at {s['created_at']} by: `{s['command']}`"]
        cfg_path = runs_dir / s["run_id"] / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            prod = cfg.get("producer") or {}
            if prod.get("command"):
                L.append(f"- Produced by: `{prod['command']}`")
            L.append(f"- Config hash `{cfg['config_hash'][:16]}`; scorer code `{cfg['scorer_code_sha256'][:16]}`; "
                     f"output sha256 `{cfg['pred_sha256'][:16]}`; model IDs: {cfg['model_ids'] or 'none'}; "
                     f"paid calls: {cfg['paid_model_calls']}")
        inexact = [c["case_id"] for c in s["cases"] if not c["row_exact"]]
        L.append(f"- Cases not row-exact: {', '.join(inexact) if inexact else 'none'}")
        rec = s.get("reconciliation")
        if rec:
            L += ["", f"Reconciliation with `{rec['reference']}` (prototype `score.py` definitions):", "",
                  "| metric | this run | reference | equal |", "|---|---:|---:|---|"]
            L += [f"| {r['metric']} | {r['ours']} | {r['reference']} | {'yes' if r['equal'] else '**no**'} |"
                  for r in rec["rows"]]
        if s.get("prev_run"):
            fl = s.get("flips") or []
            L.append("")
            L.append(f"Flips against `{s['prev_run']}`: " + (", ".join(
                f"{x['case_id']} {x['metric']} {x['prev']}->{x['now']}" for x in fl) if fl else "none"))
    for s in discr:
        L += ["", f"## Scorer discrimination `{s['run_id']}`", "", f"- Command: `{s['command']}` at {s['created_at']}",
              "- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`).", "",
              discrimination_table(s["table"])]
    if invalid:
        L += ["", "## Invalidated runs (kept as evidence; their numbers are not results)", ""]
        L += [f"- `{s['run_id']}`: {s['_invalid']}" for s in invalid]
    return "\n".join(L) + "\n"


def regenerate(path: Path = NUMBERS_MD, runs_dir: Path = RUNS) -> Path:
    """Replace the generated block in ``path`` (creating the file if needed)."""
    text = path.read_text(encoding="utf-8") if path.exists() else DEFAULT_HEAD + "\n" + BEGIN + "\n" + END + "\n"
    if BEGIN not in text or END not in text:
        text = text.rstrip("\n") + "\n\n" + BEGIN + "\n" + END + "\n"
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    path.write_text(head + BEGIN + "\n" + render(runs_dir) + END + tail, encoding="utf-8")
    return path
