"""CLI (run with ``code/`` on the path). Three commands; every one is replay-only unless ``--paid`` is given.

Full run (the default command)::

    python -m deletion_audit [--run-id <id>] (--set dev|test | --cases a,b,...) [--mode A+|A|tools_off]
        [--vision-ack <vision run id>] [--write-root] [model options]

Turn-1 routing check (T70, T92, T97; two replicates in separate cache namespaces)::

    python -m deletion_audit routing-check --run-id <id> --texts dev,fixtures,redteam[,test] [model options]

Vision readings (T88; every screenshot read twice)::

    python -m deletion_audit vision --run-id <id> [model options]

Model options: ``--cache-dir`` (default ``cache/``), and for a paid command ``--paid --dollar-cap X
--call-cap N`` plus optionally ``--env-file PATH``. Every command takes ``--runs-dir`` (default
``runs/``), the parent of ``<run_id>/``. Rules:

* **Nothing is sent without ``--paid``.** Without it the command replays the reply cache only, and
  the caps and ``--env-file`` are refused. With it, the real transport is built and one
  ``BudgetGuard`` with the two caps covers the whole command run.
* **``--env-file``** loads only the ``ANTHROPIC_API_KEY`` line of that file into this process's
  environment (the transport reads it from there). The value is never printed, logged or written
  anywhere; an error message never quotes the file.
* **``--run-id``** is optional: without it the run is named ``run-<YYYYMMDDTHHMMSS>`` (IST), so
  ``python code/main.py --set dev`` works. The run directory is ``runs/<run_id>/``.
* **``--write-root``** also writes the root ``output.csv``, which is the submission, so it needs
  the developer's approval. It is accepted only with ``--set test``, and the root file is written
  only after the run's checks pass; a stopped run leaves it untouched (T112 item 10).
* **``--set dev``** takes the 22 DEV IDs from ``code/evaluation/split.py``. A run that names a
  holdout case is refused by ``pipeline.run`` itself (exit 2). The CLI never passes the unlock.
* **``--vision-ack``** names the vision run whose readings the developer reviewed; a paid full run
  with images that need review is refused without it (exit 4).
* **Model-derived changes** are checked on every run against the engine's model-free rows computed
  in the same run (``agent/model_changes.py``): a change whose condition fails falls back to the
  model-free row, and an unexplained change exits 5. ``--regression-gate`` is kept as a no-op alias
  (the check can be neither added nor turned off), so older commands still parse.

T-numbers point to ``code/docs/DECISIONS.md``.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .model import AnthropicTransport, Transport
from .pipeline import (
    REPO_ROOT,
    TEXT_SOURCES,
    HoldoutRefused,
    ModelSetup,
    VisionReviewRequired,
    default_run_id,
    dev_ids,
    run,
    run_routing_check,
    run_vision,
)

API_KEY_NAME = "ANTHROPIC_API_KEY"
EXIT_HOLDOUT, EXIT_VISION_REVIEW, EXIT_GATE_STOP = 2, 4, 5
TransportFactory = Callable[[], Transport]


class EnvFileError(ValueError):
    """The env file cannot supply the API key (the message never quotes the file)."""


def load_api_key(path: Path) -> None:
    """Set ``ANTHROPIC_API_KEY`` in this process's environment from a dotenv-style file.

    Only that one line is used (``NAME=value``, optionally ``export NAME=value``, the value
    optionally quoted; an unquoted value ends at `` #``). Every other line is ignored. Nothing is
    printed or written; a missing file, a missing line or an empty value raises :class:`EnvFileError`.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EnvFileError(f"the env file cannot be read ({type(exc).__name__})") from None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        if not sep or name.strip() != API_KEY_NAME:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if not value:
            raise EnvFileError("the env file's API key line has no value")
        os.environ[API_KEY_NAME] = value
        return
    raise EnvFileError("the env file has no API key line")


def _add_model_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--runs-dir", default=str(REPO_ROOT / "runs"), help="the parent of runs/<run_id>/")
    ap.add_argument("--cache-dir", default=str(REPO_ROOT / "cache"), help="holds the reply namespaces and ledger")
    ap.add_argument("--paid", action="store_true", help="send cache misses to the API (needs both caps)")
    ap.add_argument("--dollar-cap", type=float, help="paid only: the command's dollar cap")
    ap.add_argument("--call-cap", type=int, help="paid only: the command's send cap")
    ap.add_argument("--env-file", help="paid only: load ANTHROPIC_API_KEY (and nothing else) from this file")


def _setup(ap: argparse.ArgumentParser, a: argparse.Namespace, factory: TransportFactory | None) -> ModelSetup:
    """The command's :class:`ModelSetup` (module docstring rules)."""
    cache_dir = Path(a.cache_dir)
    if not a.paid:
        if a.dollar_cap is not None or a.call_cap is not None or a.env_file:
            ap.error("--dollar-cap, --call-cap and --env-file need --paid")
        return ModelSetup.replay(cache_dir)
    if a.dollar_cap is None or a.call_cap is None:
        ap.error("--paid needs --dollar-cap and --call-cap")
    if a.env_file:
        try:
            load_api_key(Path(a.env_file))
        except EnvFileError as exc:
            ap.error(str(exc))
    transport = (factory or AnthropicTransport)()
    try:
        return ModelSetup.paid_run(transport, dollar_cap=a.dollar_cap, call_cap=a.call_cap, cache_dir=cache_dir)
    except ValueError as exc:
        ap.error(str(exc))
        raise  # unreachable: ap.error exits


def _command(argv: Sequence[str]) -> str:
    return "python -m deletion_audit " + " ".join(shlex.quote(x) for x in argv)


def _print_budget(rec: dict[str, object]) -> None:
    b = rec.get("budget")
    if isinstance(b, dict):
        print(f"  budget: paid {b['paid']}, sends {b['sends']} of {b['call_cap']}, "
              f"${b['settled_usd']} of ${b['dollar_cap']}")


def _main_routing(argv: list[str], factory: TransportFactory | None) -> int:
    ap = argparse.ArgumentParser(prog="deletion_audit routing-check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--texts", required=True, help=f"comma-separated sources among {','.join(TEXT_SOURCES)}")
    _add_model_args(ap)
    a = ap.parse_args(argv)
    sources = [s.strip() for s in a.texts.split(",") if s.strip()]
    if not sources or set(sources) - set(TEXT_SOURCES) or len(set(sources)) != len(sources):
        ap.error(f"--texts takes distinct sources among {','.join(TEXT_SOURCES)}")
    setup = _setup(ap, a, factory)
    rec = run_routing_check(run_id=a.run_id, sources=sources, model=setup, runs_dir=Path(a.runs_dir),
                            command=_command(["routing-check", *argv]))
    print(f"routing check {rec['run_id']}: {rec['cases']} cases, {rec['distinct_texts']} distinct texts, "
          f"{rec['model_calls']} sends")
    print(f"  replicate agreement: {rec['replicate_agreement']}")
    for ns, counts in rec["matrix_label_x_intake"].items():
        print(f"  {ns}: {counts}")
    _print_budget(rec)
    return 0


def _main_vision(argv: list[str], factory: TransportFactory | None) -> int:
    ap = argparse.ArgumentParser(prog="deletion_audit vision", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--dataset", default=str(REPO_ROOT / "dataset"))
    _add_model_args(ap)
    a = ap.parse_args(argv)
    setup = _setup(ap, a, factory)
    rec = run_vision(Path(a.dataset), run_id=a.run_id, model=setup, runs_dir=Path(a.runs_dir),
                     command=_command(["vision", *argv]))
    print(f"vision {rec['run_id']}: {rec['images']} image(s), read OK {len(rec['read_ok'])}, "
          f"needs review {rec['needs_review'] or 'none'}; {rec['model_calls']} sends")
    _print_budget(rec)
    return 0


def _main_run(argv: list[str], factory: TransportFactory | None) -> int:
    ap = argparse.ArgumentParser(prog="deletion_audit", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", help="the run directory's name (default: run-<YYYYMMDDTHHMMSS>, IST)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--set", choices=["dev", "test"])
    g.add_argument("--cases", help="comma-separated case IDs")
    ap.add_argument("--dataset", default=str(REPO_ROOT / "dataset"))
    ap.add_argument("--mode", default="A+", choices=["A+", "A", "tools_off"])
    ap.add_argument("--vision-ack", help="the vision run ID whose readings the developer reviewed")
    ap.add_argument("--regression-gate", action="store_true",
                    help="no-op, kept so older commands parse: the model-change check runs on every run")
    ap.add_argument("--write-root", action="store_true",
                    help="also write the root output.csv after the run's checks pass (--set test only; needs approval)")
    _add_model_args(ap)
    a = ap.parse_args(argv)
    if a.write_root and a.set != "test":
        ap.error("--write-root needs --set test: the root output.csv holds the test set")
    run_id = a.run_id or default_run_id()
    cases: list[str] | str
    if a.set == "dev":
        cases = sorted(dev_ids())
    elif a.set == "test":
        cases = "test"
    else:
        cases = [c.strip() for c in a.cases.split(",") if c.strip()]
    setup = _setup(ap, a, factory)
    try:
        s = run(
            Path(a.dataset),
            run_id=run_id,
            cases=cases,
            mode=a.mode,
            replay_only=not setup.paid,
            write_root=a.write_root,
            runs_dir=Path(a.runs_dir),
            command=_command(argv),
            model=setup,
            vision_ack=a.vision_ack,
        )
    except HoldoutRefused as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_HOLDOUT
    except VisionReviewRequired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_VISION_REVIEW
    m = s.metrics
    print(f"run {s.run_id}: {s.rows} rows -> {s.output_path} (sha256 {s.output_sha256[:16]}...)")
    print(
        f"  status {m['status']}  failed_closed {m['failed_closed']['count']} {m['failed_closed']['by_reason']}  "
        f"runtime {m['runtime_s']} s"
    )
    for part, c in m["validator"]["by_part"].items():
        print(f"  validator {part}: {c}")
    if s.changes is not None:
        print(f"  model-derived changes: passed {s.changes['passed']}, changed {s.changes['changed_rows']}, "
              f"by cause {s.changes['by_cause']}")
        print(f"  fell back to the model-free row (T118): {s.changes.get('fell_back_cases') or 'none'}; "
              f"stops: {s.changes.get('stop_cases') or 'none'}")
    if not s.passed:
        print("RUN NOT PASSING: an unexplained model-derived change stopped it for the developer's review",
              file=sys.stderr)
        return EXIT_GATE_STOP
    return 0


COMMANDS: dict[str, Callable[[list[str], TransportFactory | None], int]] = {
    "routing-check": _main_routing,
    "vision": _main_vision,
}


def main(argv: list[str] | None = None, *, transport_factory: TransportFactory | None = None) -> int:
    """Dispatch to a command (module docstring). ``transport_factory`` replaces the real transport in tests."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in COMMANDS:
        return COMMANDS[args[0]](args[1:], transport_factory)
    return _main_run(args, transport_factory)


if __name__ == "__main__":
    sys.exit(main())
