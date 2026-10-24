"""Produce the prep prototype's DEV output under ``runs/<run_id>/`` (a measurement tool).

This is not the pipeline and does not ship: it needs the prep kit at
``../research/prototype/`` and exists only to give G4 a baseline to score. The prototype is
imported read-only (``sys.dont_write_bytecode`` is set before the import, so no
``__pycache__`` lands in ``../research``). Nothing is written outside ``runs/<run_id>/``.

Variants (each its own run ID):
    default             the prototype as report 15 ran it on DEV: no vision table, signature on
    --vision            add the hand-typed ``vision_facts.py`` table (T7: does not ship)
    --no-signature      switch the job-timing signature off (``Opts(use_signature=False)``)
    --force-intent      bypass ``intent.py``'s keyword tables (T7: per-row tables do not
                        ship) by treating every request as deletion-authorized

Holdout lock: requests come from ``evaluation.gold.load_requests`` (holdout rows dropped),
and the prototype never reads gold during ``solve``.

Usage: python3 -B code/evaluation/prototype_baseline.py --run-id <id> [--vision] [--no-signature] [--force-intent]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import shlex
import sys
from pathlib import Path

sys.dont_write_bytecode = True
if __package__ in (None, ""):  # run as a script: make the ``evaluation`` package importable
    # Drop this file's own directory from sys.path: its module names (e.g. ``drift``,
    # ``runs``) must never shadow other top-level modules. G4 hit this once: a module
    # named ``numbers`` shadowed the stdlib and silently broke pdfplumber in the prototype.
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import runs  # noqa: E402
from evaluation.gold import load_requests  # noqa: E402
from evaluation.outputs import write_output  # noqa: E402
from evaluation.paths import REPO_ROOT  # noqa: E402

PROTOTYPE = REPO_ROOT.parent / "research" / "prototype"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--vision", action="store_true")
    ap.add_argument("--no-signature", action="store_true")
    ap.add_argument("--force-intent", action="store_true")
    a = ap.parse_args(argv)
    if not PROTOTYPE.is_dir():
        print(f"prototype not found at {PROTOTYPE}; this tool needs the prep kit", file=sys.stderr)
        return 1
    sys.path.insert(0, str(PROTOTYPE))
    import solver  # type: ignore  # noqa: E402

    if a.force_intent:
        solver.authorizes_deletion = lambda text: (True, "forced by prototype_baseline --force-intent")
    vision_units = None
    if a.vision:
        from vision_facts import vision_units as _vu  # type: ignore  # noqa: E402
        vision_units = _vu()
    world = solver.World(vision_units=vision_units)
    failed = [x for x in world.skipped if ":FAILED:" in x or "-failed" in x]
    if failed:  # a failed read is an explicit failure, never "nothing found": refuse to write output
        print(f"evidence parse failures, no output written: {failed}", file=sys.stderr)
        return 3
    opts = solver.Opts(use_signature=not a.no_signature)

    requests = load_requests()  # DEV sample requests, holdout rows dropped
    rows, per_case = [], {}
    for cid in sorted(requests):
        res = solver.solve(requests[cid], world, opts)
        rows.append((cid, res.status, res.steps))
        per_case[cid] = {"status": res.status, "n_steps": len(res.steps), "validator": solver.validate(res),
                         "guesses": res.trace.get("guesses"), "cited_file": res.trace.get("F")}
    d = runs.run_dir(a.run_id)
    n = write_output(d / "output.csv", rows)
    variant = [name for flag, name in ((a.vision, "vision"), (a.no_signature, "no-signature"),
                                       (a.force_intent, "force-intent")) if flag] or ["default"]
    producer = {
        "tool": "code/evaluation/prototype_baseline.py",
        "command": "python3 -B code/evaluation/prototype_baseline.py " + " ".join(map(shlex.quote, sys.argv[1:] if argv is None else argv)),
        "description": (
            f"prep prototype (../research/prototype/solver.py, imported read-only) on the 22 DEV cases; "
            f"variant: {'+'.join(variant)}; vision table {'ON (hand-typed, T7: not shippable)' if a.vision else 'off'}; "
            f"job-timing signature {'off' if a.no_signature else 'on'}; intent tables "
            f"{'bypassed (all deletion-authorized)' if a.force_intent else 'as in intent.py'}"),
        "variant": variant,
        "opts": dataclasses.asdict(opts),
        "vision": a.vision,
        "force_intent": a.force_intent,
        "prototype_sha256": {p.name: runs.sha256_file(p) for p in sorted(PROTOTYPE.glob("*.py"))},
        "rows_written": n,
        "evidence_skipped": sorted(world.skipped),
        "validator_errors": {c: v["validator"] for c, v in per_case.items() if v["validator"]},
        "per_case": per_case,
        "model_ids": [],
        "paid_model_calls": 0,
        "created_at": runs.now_ist(),
    }
    runs.write_json(d / "producer.json", producer)
    print(f"wrote {n} DEV rows to {d / 'output.csv'}; validator errors: {producer['validator_errors'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
