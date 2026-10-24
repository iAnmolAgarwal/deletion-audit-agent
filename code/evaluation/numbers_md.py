"""Renders the generated block of ``code/evaluation/NUMBERS.md`` from ``runs/*/score.json``.

Only the text between the BEGIN and END markers is replaced; anything outside them is kept,
so people can add hand-written context around the generated numbers without losing it.
No number inside the block is typed by hand.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from . import evidence_guard
from .paths import NUMBERS_MD, RUNS

BEGIN = "<!-- BEGIN GENERATED: evaluate.py numbers (do not edit by hand) -->"
END = "<!-- END GENERATED -->"

DEFAULT_HEAD = """# NUMBERS

Every number here carries its run ID, the command that produced it and what it measures
(the kit rules, ../../../CLAUDE.md section 4, outside this repo). The block between the markers is regenerated from
`runs/<run_id>/score.json` by `python3 -B code/evaluation/evaluate.py numbers`.
"""

METRIC_NOTES: list[tuple[str, str]] = [
    ("status", "cases whose deletion_status equals gold; reading (a): an unparseable steps_json row's status is still credited"),
    ("status (c)", "reading (c): as status, but a row whose steps_json is not a JSON list counts as status-wrong"),
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


# Corrections to a run's INVALID.txt note. The note itself is kept as written (it is evidence);
# the correction is rendered under it. Text only: no figures.
INVALID_CORRECTIONS: dict[str, str] = {
    "g4-baseline-20261025T0228": (
        "the guard that note describes refused output only on `:FAILED:` or `-failed` skip labels, that is, on "
        "raised exceptions. An empty parse, other skip labels (`unknown-json`, `unknown`) and a log line whose JSON "
        "failed to parse still passed (verifier finding B2, `notes/verify/g4_verify.md`). Replaced under T47 by "
        "`code/evaluation/evidence_guard.py`: a skip allow-list holding only `png-model-needed`, a zero-unit check "
        "with the T38 declared-scope exception, and a log-line JSON check; `evaluate.py score` checks the producer record."),
}


# Notes on a run that its artifacts cannot state themselves. Text only: no figures.
RUN_NOTES: dict[str, str] = {
    "g4fix-discrim-20261025T0318": (
        "the time suffix `T0318` in this run ID was chosen before the run and does not match its created_at; "
        "the created_at shown is the run's real time."),
}


def _r(x: Mapping[str, Any]) -> str:
    return f"{x['n']}/{x['of']}" if x.get("of") else "n/a"


def _f(v: Any) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def score_row(s: Mapping[str, Any]) -> str:
    """One comparison-table row for a scored run."""
    p, q = s["aggregate"]["published"], s["aggregate"]["prep"]
    f, st = p["field_on_matched"], p["step"]
    cells = [
        f"`{s['run_id']}`", _r(p["status_accuracy"]),
        _r(p["status_accuracy_unparseable_wrong"]) if "status_accuracy_unparseable_wrong" in p else "n/a",
        _r(p["row_exact"]), _r(p["steps_exact"]),
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


def _exclusion_reason(s: Mapping[str, Any], runs_dir: Path = RUNS) -> str | None:
    """None when a scored run may feed this file, else why not (T51, T60).

    The stored ``producer_check`` must be ``ok`` AND the CURRENT ``check_producer`` must also
    pass on the run's stored producer record and scored-file hash (``config.json``), so a
    run checked under an older, weaker rule cannot feed this file after the rule tightens.
    """
    pc = s.get("producer_check")
    if not pc:
        return "scored before the producer check existed (T47): its evidence skips and failures were never checked"
    if pc.get("status") != "ok":
        return f"producer check {pc.get('status')}: " + "; ".join(pc.get("reasons") or [])
    cfg_path = runs_dir / s["run_id"] / "config.json"
    if not cfg_path.exists():
        return "no config.json: the producer record cannot be re-checked"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    now = evidence_guard.check_producer(cfg.get("producer") or None, pred_sha256=cfg.get("pred_sha256"))
    if now["status"] != "ok":
        return (f"passed the producer check at scoring time, but the current check says {now['status']}: "
                + "; ".join(now["reasons"]))
    return None


def render(runs_dir: Path = RUNS) -> str:
    """The generated block's markdown.

    T51: numbers come only from scored runs whose producer check passed (and from the
    scorer-discrimination runs, which parse no evidence: they are built in memory from DEV
    gold). Every other run is listed by ID with the reason it is excluded, and nothing else:
    no metric, no flip against it, no reference value from it.
    """
    loaded = _load_runs(runs_dir)
    invalid = [s for s in loaded if s["_invalid"]]
    scores = [s for s in loaded if s["kind"] == "score" and not s["_invalid"]]
    reasons = {s["run_id"]: _exclusion_reason(s, runs_dir) for s in scores}
    scored = [s for s in scores if reasons[s["run_id"]] is None]
    excluded = [(s, reasons[s["run_id"]]) for s in scores if reasons[s["run_id"]] is not None]
    included_ids = {s["run_id"] for s in scored}
    discr = [s for s in loaded if s["kind"] == "discrimination" and not s["_invalid"]]
    L: list[str] = ["## Scored runs (DEV, 22 cases; holdout never loaded; producer check passed)", ""]
    L += ["| run | status | status (c) | row exact | steps exact | step P / R / F1 | state | evidence | step_no | seq exact "
          "| pairwise order | citation set | prep tuple | prep fields | prep resources | coherence hard / soft |",
          "|---|" + "---:|" * 15]
    L += [score_row(s) for s in scored]
    if not scored:
        L.append("| (no run has passed the producer check) |" + " |" * 15)
    L += ["", "Metric definitions (code: `code/evaluation/scorer.py`):", ""]
    L += [f"- **{k}**: {v}" for k, v in METRIC_NOTES]
    for s in scored:
        L += ["", f"### `{s['run_id']}`", "", f"- What: {s.get('description') or '(no description)'}",
              f"- Scored at {s['created_at']} by: `{s['command']}`",
              *([f"- Note: {RUN_NOTES[s['run_id']]}"] if s["run_id"] in RUN_NOTES else [])]
        cfg_path = runs_dir / s["run_id"] / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            prod = cfg.get("producer") or {}
            if prod.get("command"):
                L.append(f"- Produced by: `{prod['command']}`")
            L.append(f"- Config hash `{cfg['config_hash'][:16]}`; scorer code `{cfg['scorer_code_sha256'][:16]}`; "
                     f"output sha256 `{cfg['pred_sha256'][:16]}`; model IDs: {cfg['model_ids'] or 'none'}; "
                     f"paid calls: {cfg['paid_model_calls']}")
        pc = s["producer_check"]
        L.append(f"- Producer check: **{pc['status']}** (record: `{pc.get('producer_record') or 'none'}`); "
                 f"evidence skip count {pc.get('skip_count')} (must be 0 at freeze, G9)")
        L.append(f"- Allowed evidence skips ({len(pc['allowed_skips'])}, allow-list `png-model-needed` only): "
                 + (", ".join(f"`{x}`" for x in pc["allowed_skips"]) or "none"))
        nr = pc.get("no_resource_id_files") or []
        L.append(f"- Text present, no resource ID (T51; listed, not refused) ({len(nr)}): "
                 + (", ".join(f"`{x}`" for x in nr) or "none"))
        inexact = [c["case_id"] for c in s["cases"] if not c["row_exact"]]
        L.append(f"- Cases not row-exact: {', '.join(inexact) if inexact else 'none'}")
        rec = s.get("reconciliation")
        if rec:
            bad = [r["metric"] for r in rec["rows"] if not r["equal"]]
            L.append(f"- Reconciliation with `{rec['reference']}` (prototype `score.py` definitions; the reference "
                     f"values are not reproduced here): " + ("all counts equal" if not bad else
                                                             "**not equal**: " + ", ".join(bad)))
        if s.get("prev_run"):
            if s["prev_run"] in included_ids:
                fl = s.get("flips") or []
                L.append(f"- Flips against `{s['prev_run']}`: " + (", ".join(
                    f"{x['case_id']} {x['metric']} {x['prev']}->{x['now']}" for x in fl) if fl else "none"))
            else:
                L.append(f"- Flips against `{s['prev_run']}`: not shown here (that run is excluded below); "
                         "they are in this run's `flips.json`")
    for s in discr:
        L += ["", f"## Scorer discrimination `{s['run_id']}`", "", f"- Command: `{s['command']}` at {s['created_at']}",
              *([f"- Note: {RUN_NOTES[s['run_id']]}"] if s["run_id"] in RUN_NOTES else []),
              "- Variants are built in memory from DEV gold (`code/evaluation/discrimination.py`). Producer check: "
              "not applicable (no evidence file is parsed).", "",
              discrimination_table(s["table"])]
    if excluded:
        L += ["", "## Excluded runs (producer check not passed; T51: listed by ID and reason only)", ""]
        L += [f"- `{s['run_id']}`: {why}" for s, why in excluded]
    if invalid:
        L += ["", "## Invalidated runs (kept as evidence; their numbers are not results)", ""]
        for s in invalid:
            L.append(f"- `{s['run_id']}`: {s['_invalid']}")
            if s["run_id"] in INVALID_CORRECTIONS:
                L.append(f"  - **Correction:** {INVALID_CORRECTIONS[s['run_id']]}")
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
