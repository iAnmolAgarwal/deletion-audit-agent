"""Evaluation command line. Every subcommand writes its results under ``runs/<run_id>/``.

Usage (from the repo root; ``-B`` keeps bytecode out of the tree):
    python3 -B code/evaluation/evaluate.py score --pred runs/<id>/output.csv --run-id <id>
        [--prev <run_id>] [--reconcile runs/g2-0137/q2.json:dev_all] [--allow-incoherent]
    python3 -B code/evaluation/evaluate.py coherence --pred <output.csv> [--expect dev|test|none]
    python3 -B code/evaluation/evaluate.py drift --pred <output.csv> --run-id <id>
    python3 -B code/evaluation/evaluate.py discriminate --run-id <id>
    python3 -B code/evaluation/evaluate.py numbers

``score`` reads DEV gold only. The holdout is never scored by this CLI: that needs a
separate, explicitly unlocked call after freeze (``gold.load_gold(holdout=True, ...)``).
``score`` and ``coherence`` exit with status 2 when a hard coherence rule fails, after
listing every offending row (``--allow-incoherent`` keeps exit status 0 for score).
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: make the ``evaluation`` package importable
    # Drop this file's own directory from sys.path: its module names (e.g. ``drift``,
    # ``runs``) must never shadow other top-level modules. G4 hit this once: a module
    # named ``numbers`` shadowed the stdlib and silently broke pdfplumber in the prototype.
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import coherence, discrimination, drift, numbers_md, runs  # noqa: E402
from evaluation.gold import load_gold, load_requests  # noqa: E402
from evaluation.outputs import read_output  # noqa: E402
from evaluation.paths import REPO_ROOT, SAMPLE_REQUESTS, TEST_REQUESTS  # noqa: E402
from evaluation.scorer import score_predictions  # noqa: E402
from evaluation.split import DEV_IDS  # noqa: E402

PREP_TO_REFERENCE: dict[str, tuple[tuple[str, ...], str]] = {
    # our prep-block metric path -> key in a research/prototype/score.py aggregate
    "status_exact": (("status_exact", "n"), "status_exact"),
    "case_exact": (("case_exact", "n"), "case_exact"),
    "steps_exact": (("steps_exact", "n"), "steps_exact"),
    "sequence_exact": (("sequence_exact", "n"), "sequence_exact"),
    "step_tp": (("step_tuple", "tp"), "step_tp"),
    "step_pred": (("step_tuple", "pred"), "step_pred"),
    "step_gold": (("step_tuple", "gold"), "step_gold"),
    "field_hits": (("field_positional", "n"), "field_hits"),
    "field_slots": (("field_positional", "of"), "field_slots"),
    "res_tp": (("resources", "tp"), "res_tp"),
    "res_pred": (("resources", "pred"), "res_pred"),
    "res_gold": (("resources", "gold"), "res_gold"),
}


def _command() -> str:
    return "python3 -B " + " ".join(shlex.quote(a) for a in [str(Path(sys.argv[0]).resolve().relative_to(REPO_ROOT))] + sys.argv[1:]) \
        if Path(sys.argv[0]).resolve().is_relative_to(REPO_ROOT) else " ".join(map(shlex.quote, sys.argv))


def _rel(p: Path) -> str:
    p = p.resolve()
    return str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p)


def _audit_times() -> dict[str, str]:
    """audit_at for DEV sample cases (holdout rows dropped) and all test cases."""
    times = {cid: r["audit_at"] for cid, r in load_requests(SAMPLE_REQUESTS).items()}
    times.update({cid: r["audit_at"] for cid, r in load_requests(TEST_REQUESTS).items()})
    return times


def _expected(kind: str, pred_ids: set[str]) -> set[str] | None:
    if kind == "auto":
        kind = "dev" if pred_ids and pred_ids <= DEV_IDS else "test"
    if kind == "dev":
        return set(DEV_IDS)
    if kind == "test":
        return set(load_requests(TEST_REQUESTS))
    return None


def reconcile(prep: dict[str, Any], spec: str) -> dict[str, Any]:
    """Compare our prep-block counts with a reference aggregate ``file.json:key``."""
    file_part, _, key = spec.rpartition(":")
    ref = json.loads((REPO_ROOT / file_part).read_text(encoding="utf-8"))[key]
    rows = []
    for name, (path, ref_key) in PREP_TO_REFERENCE.items():
        ours = discrimination.dig(prep, path)
        rows.append({"metric": name, "ours": ours, "reference": ref.get(ref_key), "equal": ours == ref.get(ref_key)})
    return {"reference": spec, "rows": rows, "all_equal": all(r["equal"] for r in rows)}


def cmd_score(a: argparse.Namespace) -> int:
    pred_path = Path(a.pred).resolve()
    out = read_output(pred_path)
    gold = load_gold()  # DEV only
    result = score_predictions(out.rows, gold)
    violations = coherence.check_file(out, audit_at=_audit_times(), evidence=coherence.load_evidence_index(),
                                      expected_ids=_expected(a.expect, set(out.rows)))
    coh = coherence.summarize(violations)
    d = runs.run_dir(a.run_id)
    producer = {}
    if (d / "producer.json").exists():
        producer = json.loads((d / "producer.json").read_text(encoding="utf-8"))
    config = {
        "run_id": a.run_id,
        "kind": "score",
        "created_at": runs.now_ist(),
        "command": _command(),
        "pred_file": _rel(pred_path),
        "pred_sha256": runs.sha256_file(pred_path),
        "gold": "DEV only (evaluation.gold.load_gold default; holdout rows dropped before JSON parsing)",
        "gold_dev_hash": runs.gold_hash(gold),
        "scorer_code_sha256": runs.code_hash(),
        "git_head": runs.git_head(),
        "producer": producer,
        "model_ids": producer.get("model_ids", []),
        "paid_model_calls": producer.get("paid_model_calls", 0),
    }
    config["config_hash"] = runs.canonical_hash({k: config[k] for k in
                                                 ("pred_sha256", "gold_dev_hash", "scorer_code_sha256", "producer")})
    score = {"run_id": a.run_id, "kind": "score", "created_at": config["created_at"], "command": config["command"],
             "description": a.description or producer.get("description", ""), **result,
             "coherence": {k: coh[k] for k in ("hard", "soft", "by_rule", "hard_cases")}}
    if a.reconcile:
        score["reconciliation"] = reconcile(result["aggregate"]["prep"], a.reconcile)
    flip_rows: list[dict[str, Any]] | None = None
    if a.prev:
        flip_rows = runs.flips(runs.load_score(a.prev)["cases"], result["cases"])
    score["prev_run"] = a.prev
    score["flips"] = flip_rows
    runs.write_json(d / "config.json", config)
    runs.write_json(d / "score.json", score)
    runs.write_json(d / "coherence.json", coh)
    runs.write_json(d / "flips.json", {"prev_run": a.prev, "flips": flip_rows})
    (d / "README.txt").write_text(_readme(config, score), encoding="utf-8")
    _print_summary(score)
    print(coherence.format_report(violations))
    return 2 if coh["hard"] and not a.allow_incoherent else 0


def _readme(config: dict[str, Any], score: dict[str, Any]) -> str:
    p = score["aggregate"]["published"]
    prod = config.get("producer") or {}
    lines = [
        f"Run {config['run_id']} ({config['created_at']})",
        "",
        "How the output was produced:",
        f"  {prod.get('description', '(no producer.json: output supplied externally)')}",
        *(f"  producer command: {prod['command']}" for _ in [0] if prod.get("command")),
        "",
        "How it was scored:",
        f"  {config['command']}",
        f"  gold: {config['gold']}",
        f"  scorer code sha256 {config['scorer_code_sha256'][:16]}..., config hash {config['config_hash'][:16]}...",
        f"  model ids: {config['model_ids'] or 'none'}; paid model calls: {config['paid_model_calls']}",
        "",
        "Headline (DEV):",
        f"  status {p['status_accuracy']['n']}/{p['status_accuracy']['of']}, row exact {p['row_exact']['n']}/{p['row_exact']['of']},"
        f" step F1 {p['step']['f1']:.4f}, sequence exact {p['sequence_exact']['n']}/{p['sequence_exact']['of']}",
        f"  coherence: {score['coherence']['hard']} hard, {score['coherence']['soft']} soft",
        "",
        "Files: output.csv (DEV rows only), score.json (aggregate + per-case diffs), coherence.json,",
        "config.json (hashes), flips.json (vs --prev), producer.json (if the producer wrote one).",
        "Numbers are rendered into code/evaluation/NUMBERS.md by `evaluate.py numbers`; never hand-typed.",
        "",
    ]
    return "\n".join(lines)


def _print_summary(score: dict[str, Any]) -> None:
    p, q = score["aggregate"]["published"], score["aggregate"]["prep"]
    f = p["field_on_matched"]
    print(f"run {score['run_id']}: {score['aggregate']['cases']} DEV cases")
    print(f"  status {p['status_accuracy']['n']}/{p['status_accuracy']['of']}  row exact {p['row_exact']['n']}  "
          f"steps exact {p['steps_exact']['n']}")
    print(f"  step P/R/F1 {p['step']['precision']:.4f}/{p['step']['recall']:.4f}/{p['step']['f1']:.4f} "
          f"(tp {p['step']['tp']}, pred {p['step']['pred']}, gold {p['step']['gold']})")
    print(f"  fields on matched: state {f['state']['n']}/{f['state']['of']}  evidence {f['evidence_id']['n']}/{f['evidence_id']['of']}"
          f"  step_no {f['step_no']['n']}/{f['step_no']['of']}")
    so = p["sequence_pairwise_order"]
    print(f"  sequence exact {p['sequence_exact']['n']}  pairwise order {so['n']}/{so['of']}  "
          f"citation set exact {p['citation_set_exact']['n']}")
    print(f"  prep: tuple tp {q['step_tuple']['tp']}/{q['step_tuple']['gold']}  positional fields "
          f"{q['field_positional']['n']}/{q['field_positional']['of']}  resources {q['resources']['tp']}/{q['resources']['gold']}")
    if "reconciliation" in score:
        r = score["reconciliation"]
        bad = [x for x in r["rows"] if not x["equal"]]
        print(f"  reconciliation with {r['reference']}: {'all equal' if not bad else bad}")
    if score.get("flips") is not None:
        print(f"  flips vs {score['prev_run']}: {score['flips']}")


def cmd_coherence(a: argparse.Namespace) -> int:
    out = read_output(Path(a.pred).resolve())
    violations = coherence.check_file(out, audit_at=_audit_times(), evidence=coherence.load_evidence_index(),
                                      expected_ids=_expected(a.expect, set(out.rows)))
    print(coherence.format_report(violations))
    return 2 if any(v.severity == "hard" for v in violations) else 0


def cmd_drift(a: argparse.Namespace) -> int:
    out = read_output(Path(a.pred).resolve())
    table = drift.drift_table(out.rows, load_gold(), a.threshold)
    d = runs.run_dir(a.run_id)
    runs.write_json(d / "drift.json", {"run_id": a.run_id, "kind": "drift", "created_at": runs.now_ist(),
                                       "command": _command(), "pred_file": _rel(Path(a.pred)),
                                       "threshold_pts": a.threshold, "table": table})
    print(drift.format_table(table))
    return 0


def cmd_discriminate(a: argparse.Namespace) -> int:
    gold = load_gold()
    res = discrimination.run(gold, sorted(coherence.load_evidence_index().files))
    d = runs.run_dir(a.run_id)
    runs.write_json(d / "score.json", {"run_id": a.run_id, "kind": "discrimination", "created_at": runs.now_ist(),
                                       "command": _command(), "gold_dev_hash": runs.gold_hash(gold),
                                       "scorer_code_sha256": runs.code_hash(), **res})
    (d / "README.txt").write_text(
        f"Run {a.run_id}: scorer discrimination check on DEV gold (in memory; no model calls).\n"
        f"Command: {_command()}\nVariants: see code/evaluation/discrimination.py. Results: score.json 'table'.\n",
        encoding="utf-8")
    print(numbers_md.discrimination_table(res["table"]))
    return 0


def cmd_numbers(a: argparse.Namespace) -> int:
    path = numbers_md.regenerate()
    print(f"regenerated the generated block of {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="score a prediction file against DEV gold")
    s.add_argument("--pred", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--prev", help="previous run ID for per-case flips")
    s.add_argument("--reconcile", help="reference aggregate 'path/to/file.json:key' (prototype score.py form)")
    s.add_argument("--expect", default="auto", choices=["auto", "dev", "test", "none"])
    s.add_argument("--description", default="")
    s.add_argument("--allow-incoherent", action="store_true")
    s.set_defaults(fn=cmd_score)
    c = sub.add_parser("coherence", help="coherence checks only (no gold)")
    c.add_argument("--pred", required=True)
    c.add_argument("--expect", default="auto", choices=["auto", "dev", "test", "none"])
    c.set_defaults(fn=cmd_coherence)
    d = sub.add_parser("drift", help="predicted distributions vs DEV gold")
    d.add_argument("--pred", required=True)
    d.add_argument("--run-id", required=True)
    d.add_argument("--threshold", type=float, default=15.0)
    d.set_defaults(fn=cmd_drift)
    x = sub.add_parser("discriminate", help="majority baseline and perturbed DEV gold")
    x.add_argument("--run-id", required=True)
    x.set_defaults(fn=cmd_discriminate)
    n = sub.add_parser("numbers", help="regenerate the generated block of NUMBERS.md")
    n.set_defaults(fn=cmd_numbers)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
