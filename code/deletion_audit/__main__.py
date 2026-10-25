"""CLI: ``python -m deletion_audit --run-id <id> (--set dev|test | --cases a,b,...)`` (run with ``code/`` on the path).

Writes ``runs/<run_id>/output.csv`` and the run artifacts. ``--write-root`` also writes the
root ``output.csv`` and needs the developer's approval (``../CLAUDE.md`` section 2).

``--set dev`` takes the 22 DEV IDs from ``code/evaluation/split.py``. A run that names a holdout
case is refused by ``pipeline.run`` itself (its holdout guard raises ``HoldoutRefused`` and writes
nothing); this CLI reports that refusal with exit code 2. Any other caller of ``pipeline.run`` gets
the same refusal. The holdout cases' request inputs still join the account assignment (T32). The
engine's own entry points (``engine.audit_all``) have no guard; they write no output file.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from .pipeline import REPO_ROOT, HoldoutRefused, run


def _dev_ids() -> frozenset[str]:
    code_dir = str(REPO_ROOT / "code")
    if code_dir not in sys.path:
        sys.path.insert(0, code_dir)
    from evaluation.split import DEV_IDS

    return frozenset(DEV_IDS)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the pipeline."""
    ap = argparse.ArgumentParser(
        prog="deletion_audit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--run-id", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--set", choices=["dev", "test"])
    g.add_argument("--cases", help="comma-separated case IDs")
    ap.add_argument("--dataset", default=str(REPO_ROOT / "dataset"))
    ap.add_argument("--mode", default="A+", choices=["A+", "A", "tools_off"])
    ap.add_argument("--write-root", action="store_true", help="also write the root output.csv (needs approval)")
    a = ap.parse_args(argv)
    cases: list[str] | str
    if a.set == "dev":
        cases = sorted(_dev_ids())
    elif a.set == "test":
        cases = "test"
    else:
        cases = [c.strip() for c in a.cases.split(",") if c.strip()]
    command = "python -m deletion_audit " + " ".join(
        shlex.quote(x) for x in (argv if argv is not None else sys.argv[1:])
    )
    try:
        s = run(
            Path(a.dataset),
            run_id=a.run_id,
            cases=cases,
            mode=a.mode,
            replay_only=True,
            write_root=a.write_root,
            command=command,
        )
    except HoldoutRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    m = s.metrics
    print(f"run {s.run_id}: {s.rows} rows -> {s.output_path} (sha256 {s.output_sha256[:16]}...)")
    print(
        f"  status {m['status']}  failed_closed {m['failed_closed']['count']} {m['failed_closed']['by_reason']}  "
        f"runtime {m['runtime_s']} s"
    )
    for part, c in m["validator"]["by_part"].items():
        print(f"  validator {part}: {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
