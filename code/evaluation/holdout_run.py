"""The HOLDOUT EVALUATION RUN: the one command that unlocks the holdout (T96, proposal section 3).

Usage (from the repo root, in the developer's turn that carries the phrase; ruling T96 (2)):
    .venv/bin/python -B code/evaluation/holdout_run.py --unlock "<the developer's phrase>" \\
        --freeze-tag freeze-<YYYYMMDD> --freeze-run <final run id> --run-id holdout-<YYYYMMDDTHHMM>

It is the only caller of the unlock in ``code/`` (``tests/test_holdout_static.py`` proves it).
The phrase comes from argv only: never from an environment variable, a file or a default.

Order (every check runs before any holdout input or gold is read):

1. **Phrase:** ``--unlock`` must equal ``gold.UNLOCK_PHRASE`` exactly (case, spaces,
   punctuation; no normalising). A refusal never prints the phrase.
2. **Frozen code (T96 (4)):** ``--freeze-tag`` is shaped ``freeze-<YYYYMMDD>``, exists as a tag,
   resolves to a commit (``git rev-parse <tag>^{commit}``), HEAD is that commit, and the tree is
   clean (untracked files only under ``runs/`` and ``cache/``). This command never creates or
   moves a tag; main creates it at freeze.
3. **Freeze check:** ``freeze_check.freeze_check`` is re-run on ``--freeze-run`` and must pass,
   and that run's ``producer.json`` must name the same commit in ``git_head``.
4. **Once only:** no completed holdout record exists anywhere under ``runs/`` and the access log
   holds no ``complete`` line. An unfinished attempt (no ``score.json``) may be retried under the
   same ``--run-id`` only; the retry is numbered in the record and the access log.
5. **Engine:** the engine runs on the holdout IDs in mode A+, through a ``ModelClient`` whose
   ``BudgetGuard`` has the caps :data:`HOLDOUT_DOLLAR_CAP` and :data:`HOLDOUT_CALL_CAP` (T96 (3)).
6. **Score:** ``gold.load_gold(holdout=True, unlock_phrase=<argv phrase>, run_id=...)``.
7. **Write:** ``runs/<id>/score.json`` and ``runs/<id>/holdout_record.json`` (the engine wrote
   ``output.csv``). The record repeats ``notes/split.json``'s ``created`` caveat verbatim (T96 (5)).
8. **Access log** (``gold.HOLDOUT_ACCESS_LOG``): one line by this command before each unlock
   (``what`` = ``engine run``, then ``gold``) and a final ``complete`` line with the sha256 of the
   output and of the score. ``gold.check_unlock`` adds its own line at each granted unlock.

Exit status: 0 done, 3 refused (nothing read, nothing logged), 1 failed after the checks (the
record stays ``started``; the same ``--run-id`` may be retried).

Limit, stated plainly (proposal, "The limit"): the phrase is a constant in the source, not a
secret. The lock stops accidental and incidental access and makes deliberate access visible
and logged; it cannot stop someone with a shell who calls the function on purpose.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if __package__ in (None, ""):  # run as a script: same bootstrap as evaluate.py
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import freeze_check as freeze_check_mod  # noqa: E402
from evaluation import gold as gold_mod  # noqa: E402
from evaluation import paths, runs, split  # noqa: E402
from evaluation.gold import UNLOCK_PHRASE, load_gold  # noqa: E402
from evaluation.outputs import read_output  # noqa: E402
from evaluation.scorer import score_predictions  # noqa: E402

if TYPE_CHECKING:
    from deletion_audit.model import BudgetGuard, ModelClient

# The caps for this run's paid calls (developer ruling T96 (3)). The only place they are named.
HOLDOUT_DOLLAR_CAP: float = 1.00
HOLDOUT_CALL_CAP: int = 60

#: The vision run whose readings the developer acknowledged (T118a in code/docs/DECISIONS.md). A paid
#: full run refuses screenshots that need review without it, and the holdout engine run is one.
HOLDOUT_VISION_ACK: str = "pass1-vision-20261025T1323"
HOLDOUT_MODE: str = "A+"

FREEZE_TAG_RE: re.Pattern[str] = re.compile(r"freeze-[0-9]{8}", re.ASCII)
RUN_ID_PREFIX: str = "holdout-"
ALLOWED_UNTRACKED: tuple[str, ...] = ("runs/", "cache/")
RECORD_FILE: str = "holdout_record.json"
SCORE_FILE: str = "score.json"
OUTPUT_FILE: str = "output.csv"
CALLS_FILE: str = "holdout_calls.jsonl"
EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 3
LOCK_INCIDENT_NOTE: str = (
    "Lock incident T48 (notes/DECISIONS.md): before this run, a G4 verification probe parsed the holdout "
    "gold rows in memory. It printed counts only; no value was seen and no decision used it."
)


class HoldoutRefused(Exception):
    """A pre-run check failed: nothing was read from the holdout and nothing was logged."""


@dataclass(frozen=True)
class Settings:
    """Where the command looks. Production uses :func:`default_settings`; tests pass temp paths."""

    repo_root: Path
    runs_root: Path
    dataset_dir: Path
    gold_path: Path
    split_json: Path
    cache_root: Path

    @property
    def ledger(self) -> Path:
        """The project spend ledger the ``BudgetGuard`` appends to."""
        return self.cache_root / "ledger.jsonl"


def default_settings() -> Settings:
    """The repository's real paths, read from :mod:`evaluation.paths` at call time."""
    return Settings(repo_root=paths.REPO_ROOT, runs_root=paths.RUNS, dataset_dir=paths.DATASET,
                    gold_path=paths.SAMPLE_OUTPUT, split_json=paths.SPLIT_JSON,
                    cache_root=paths.REPO_ROOT / "cache")


@dataclass(frozen=True)
class Invocation:
    """What the developer asked for, minus the phrase (which is passed on its own, from argv)."""

    run_id: str
    freeze_tag: str
    freeze_run: str
    argv: tuple[str, ...]


@dataclass
class Context:
    """Facts established by the checks, carried into the run and the log lines."""

    inv: Invocation
    freeze_commit: str
    freeze_result: dict[str, Any]
    caveat: str
    attempt: int
    record: dict[str, Any]


ClientFactory = Callable[[str, "BudgetGuard", Settings], "ModelClient"]
EngineRunner = Callable[..., Any]
FreezeChecker = Callable[..., dict[str, Any]]


# ---- small helpers -------------------------------------------------------------------------

def _utc_now() -> str:
    """UTC time in the same form ``gold.check_unlock`` writes to the access log."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a read-only git command in ``repo``; a git that cannot run is a refusal."""
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30,
                              check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HoldoutRefused(f"git could not run ({type(exc).__name__})") from exc


def _write_json_atomic(path: Path, obj: Any) -> None:
    """Write JSON through a temporary file and a rename, so a crash never leaves half a record."""
    tmp = path.with_name(path.name + ".tmp")
    runs.write_json(tmp, obj)
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    """Parse a JSON file; raise :class:`HoldoutRefused` if it is unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldoutRefused(f"{path.name} in {path.parent.name}/ is unreadable ({type(exc).__name__})") from exc


def _access_log() -> Path:
    """The access log, read from ``evaluation.gold`` at call time so both writers share one file."""
    log = vars(gold_mod)["HOLDOUT_ACCESS_LOG"]  # gold.py's own global, as check_unlock reads it
    return Path(log)


def _append_access(ctx: Context, what: str, **extra: Any) -> None:
    """Append one line by this command to the access log."""
    line = {"at": _utc_now(), "what": what, "run_id": ctx.inv.run_id, "git_head": ctx.freeze_commit,
            "freeze_tag": ctx.inv.freeze_tag, "freeze_run": ctx.inv.freeze_run, "argv": list(ctx.inv.argv),
            "attempt": ctx.attempt, "by": "holdout_run", **extra}
    log = _access_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")


# ---- the checks (none reads a holdout input or gold) -----------------------------------------

def check_phrase(*, phrase: str | None) -> None:
    """Refuse unless ``phrase`` is exactly the developer's phrase; the message never shows it."""
    if not isinstance(phrase, str) or phrase != UNLOCK_PHRASE:
        raise HoldoutRefused("the developer's unlock phrase is missing or not exact (argv --unlock only)")


def check_ids(inv: Invocation) -> None:
    """Refuse a malformed run ID, freeze run ID or tag name."""
    for label, value in (("--run-id", inv.run_id), ("--freeze-run", inv.freeze_run)):
        try:
            runs.check_run_id(value)
        except ValueError as exc:
            raise HoldoutRefused(f"{label}: {exc}") from exc
    if not inv.run_id.startswith(RUN_ID_PREFIX):
        raise HoldoutRefused(f"--run-id must start with {RUN_ID_PREFIX!r}")
    if inv.run_id == inv.freeze_run:
        raise HoldoutRefused("--run-id must differ from --freeze-run")
    if FREEZE_TAG_RE.fullmatch(inv.freeze_tag or "") is None:
        raise HoldoutRefused("--freeze-tag must be shaped freeze-<YYYYMMDD>")


def dirty_paths(porcelain_z: str) -> list[str]:
    """Paths that make the tree unclean, from ``git status --porcelain=v1 -z`` output.

    Every tracked change counts. An untracked file counts unless it is under ``runs/`` or
    ``cache/``. A rename or copy entry carries a second path field, which is skipped.
    """
    fields = porcelain_z.split("\0")
    bad: list[str] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1  # the original path of a rename or copy
        if code == "??" and path.startswith(ALLOWED_UNTRACKED):
            continue
        bad.append(path)
    return bad


def check_frozen_code(repo: Path, tag: str) -> str:
    """Return the tag's commit after checking it exists, HEAD is it, and the tree is clean."""
    exists = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    if exists.returncode != 0:
        raise HoldoutRefused(f"tag {tag} does not exist")
    resolved = _git(repo, "rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}")
    commit = resolved.stdout.strip()
    if resolved.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise HoldoutRefused(f"tag {tag} does not resolve to a commit")
    head = _git(repo, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != commit:
        raise HoldoutRefused(f"HEAD is not the commit of {tag}")
    status = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status.returncode != 0:
        raise HoldoutRefused("git status failed")
    bad = dirty_paths(status.stdout)
    if bad:
        shown = ", ".join(bad[:10]) + (" ..." if len(bad) > 10 else "")
        raise HoldoutRefused(f"the tree is not clean ({len(bad)} path(s): {shown})")
    return commit


def check_freeze_run(settings: Settings, inv: Invocation, commit: str,
                     freeze_checker: FreezeChecker) -> dict[str, Any]:
    """Re-run the freeze check on ``--freeze-run`` and check its producer names ``commit``."""
    result = freeze_checker(inv.freeze_run, runs_root=settings.runs_root)
    if not result.get("passed"):
        refusals = "; ".join(str(r) for r in result.get("refusals", [])) or "no reason given"
        raise HoldoutRefused(f"the freeze check refuses {inv.freeze_run}: {refusals}")
    producer = _read_json(settings.runs_root / inv.freeze_run / "producer.json")
    if not isinstance(producer, Mapping) or producer.get("git_head") != commit:
        raise HoldoutRefused(f"the producer record of {inv.freeze_run} does not name the frozen commit "
                             "in git_head")
    return result


def read_caveat(settings: Settings) -> str:
    """``notes/split.json``'s ``created`` text, after checking its holdout list matches split.py."""
    data = _read_json(settings.split_json)
    created = data.get("created") if isinstance(data, Mapping) else None
    if not isinstance(created, str) or not created.strip():
        raise HoldoutRefused("split.json has no 'created' caveat")
    if set(data.get("holdout") or []) != set(split.HOLDOUT_IDS):
        raise HoldoutRefused("split.json's holdout list differs from split.HOLDOUT_IDS")
    return created


def check_once(settings: Settings, run_id: str) -> tuple[int, dict[str, Any] | None]:
    """Refuse a second holdout run; return (attempt number, the unfinished record to resume)."""
    log = _access_log()
    if log.exists():
        try:
            lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HoldoutRefused("the access log is unreadable") from exc
        if any(not isinstance(x, Mapping) for x in lines):
            raise HoldoutRefused("the access log holds a line that is not a JSON object")
        if any(x.get("what") == "complete" for x in lines):
            raise HoldoutRefused("the access log records a completed holdout run; a second one needs a "
                                 "new developer ruling")
        others = sorted({str(x.get("run_id")) for x in lines} - {run_id})
        if others:
            raise HoldoutRefused(f"the access log records an unlock under another run ID ({', '.join(others)}); "
                                 "resume that run ID or ask the developer")
    resume: dict[str, Any] | None = None
    for rec_path in sorted(settings.runs_root.glob(f"*/{RECORD_FILE}")):
        rec = _read_json(rec_path)
        if not isinstance(rec, Mapping):
            raise HoldoutRefused(f"{rec_path.parent.name}/{RECORD_FILE} is not a JSON object")
        if rec.get("status") == "complete":
            raise HoldoutRefused(f"a completed holdout record exists ({rec_path.parent.name}); a second run "
                                 "needs a new developer ruling")
        if rec_path.parent.name != run_id or rec.get("run_id") != run_id:
            raise HoldoutRefused(f"an unfinished holdout attempt exists under {rec_path.parent.name}; retry it "
                                 "under that run ID only")
        resume = dict(rec)
    d = settings.runs_root / run_id
    if (d / SCORE_FILE).exists():
        raise HoldoutRefused(f"{run_id} already has a {SCORE_FILE}; it is not a retry")
    if resume is None and d.exists() and any(d.iterdir()):
        raise HoldoutRefused(f"runs/{run_id}/ already holds files but no holdout record")
    attempt = len(resume.get("attempts") or []) + 1 if resume else 1
    return attempt, resume


def run_checks(inv: Invocation, *, phrase: str | None, settings: Settings,
               freeze_checker: FreezeChecker) -> Context:
    """Steps 1-4, in order. Raises :class:`HoldoutRefused`; reads no holdout input and no gold."""
    check_phrase(phrase=phrase)
    check_ids(inv)
    commit = check_frozen_code(settings.repo_root, inv.freeze_tag)
    freeze_result = check_freeze_run(settings, inv, commit, freeze_checker)
    caveat = read_caveat(settings)
    attempt, resume = check_once(settings, inv.run_id)
    record = resume or {"run_id": inv.run_id, "kind": "holdout-record", "status": "started", "attempts": []}
    return Context(inv=inv, freeze_commit=commit, freeze_result=freeze_result, caveat=caveat, attempt=attempt,
                   record=record)


# ---- the run ---------------------------------------------------------------------------------

def make_budget(settings: Settings) -> BudgetGuard:
    """The run's ``BudgetGuard``: exactly :data:`HOLDOUT_DOLLAR_CAP` and :data:`HOLDOUT_CALL_CAP`."""
    from deletion_audit.model import BudgetGuard

    return BudgetGuard(HOLDOUT_DOLLAR_CAP, HOLDOUT_CALL_CAP, settings.ledger)


def anthropic_client(run_id: str, budget: BudgetGuard, settings: Settings) -> ModelClient:
    """The production client: the real transport, the first reply namespace under the shared cache
    (``pipeline.namespace_roots``), a paid (not replay) client on the holdout ``BudgetGuard``."""
    from deletion_audit.model import AnthropicTransport, JsonlCallLog, ModelClient, ReplyCache, RetryPolicy
    from deletion_audit.pipeline import namespace_roots

    return ModelClient(AnthropicTransport(), ReplyCache(namespace_roots(settings.cache_root)[0]), budget,
                       RetryPolicy(), JsonlCallLog(settings.runs_root / run_id / CALLS_FILE), replay_only=False,
                       run_id=run_id)


def pipeline_runner(*, dataset_dir: Path, run_id: str, cases: Sequence[str], phrase: str, client: ModelClient,
                    runs_dir: Path, command: str) -> Any:
    """Run ``deletion_audit.pipeline.run`` on the holdout cases with the unlock (T96) and ``client``'s wiring.

    ``pipeline.ModelSetup.from_client`` keeps ``client``'s transport, its one ``BudgetGuard`` (the
    $1 / 60-send caps of :func:`make_budget`), its retry policy and its call log
    (``holdout_calls.jsonl``; the pipeline also writes ``calls.jsonl``). Only the case conversation
    may send: the turn-1 replicate and both vision readings replay from the cache (``pipeline``
    module docstring), so vision is never bought by this run.
    """
    from deletion_audit import pipeline

    engine: Callable[..., Any] = pipeline.run
    return engine(dataset_dir, run_id=run_id, cases=list(cases), mode=HOLDOUT_MODE, replay_only=False,
                  holdout_unlock=phrase, model=pipeline.ModelSetup.from_client(client), runs_dir=runs_dir,
                  command=command, vision_ack=HOLDOUT_VISION_ACK)


def _published(score: Mapping[str, Any]) -> dict[str, Any]:
    """The headline metrics copied from the score, for the record and the report section."""
    p = score["aggregate"]["published"]
    keys = ("status_accuracy", "row_exact", "steps_exact", "step", "field_on_matched", "sequence_exact",
            "sequence_pairwise_order", "citation_set_exact")
    return {k: p[k] for k in keys if k in p}


def execute(ctx: Context, *, phrase: str, settings: Settings, runner: EngineRunner,
            client_factory: ClientFactory, freeze_checker: FreezeChecker, command: str) -> dict[str, Any]:
    """Steps 5-8: engine, score, write, log. Returns the completed record."""
    inv, rec = ctx.inv, ctx.record
    d = settings.runs_root / inv.run_id
    d.mkdir(parents=True, exist_ok=True)
    attempt: dict[str, Any] = {"attempt": ctx.attempt, "started_at": _utc_now(), "argv": list(inv.argv),
                               "retry": ctx.attempt > 1}
    rec["attempts"] = [*(rec.get("attempts") or []), attempt]
    rec.update({"freeze_tag": inv.freeze_tag, "freeze_commit": ctx.freeze_commit, "freeze_run": inv.freeze_run,
                "caveat": ctx.caveat, "caveat_source": "notes/split.json 'created'", "command": command})
    _write_json_atomic(d / RECORD_FILE, rec)
    budget = make_budget(settings)
    cases = sorted(split.HOLDOUT_IDS)
    try:
        client = client_factory(inv.run_id, budget, settings)
        with client:  # releases the paid-run lock on every exit
            if getattr(client, "budget", None) is not budget:
                raise RuntimeError("the client factory did not use the holdout BudgetGuard")
            _append_access(ctx, "engine run")
            attempt["engine_unlocked_at"] = _utc_now()
            summary = runner(dataset_dir=settings.dataset_dir, run_id=inv.run_id, cases=cases, phrase=phrase,
                             client=client, runs_dir=settings.runs_root, command=command)
        out_path = d / OUTPUT_FILE
        if not out_path.is_file():
            raise RuntimeError(f"the engine wrote no {OUTPUT_FILE}")
        out = read_output(out_path)
        claimed = getattr(summary, "output_sha256", None)
        if claimed is not None and claimed != out.sha256:
            raise RuntimeError(f"the engine's output_sha256 differs from the sha256 of {OUTPUT_FILE}")
        if set(out.rows) != set(cases) or any("skipped" in i or "duplicate" in i for i in out.issues):
            raise RuntimeError(f"{OUTPUT_FILE} does not hold exactly one readable row per holdout case")
        own = freeze_checker(inv.run_id, runs_root=settings.runs_root)
        _append_access(ctx, "gold")
        attempt["gold_unlocked_at"] = _utc_now()
        gold = load_gold(settings.gold_path, holdout=True, unlock_phrase=phrase, run_id=inv.run_id)
        result = score_predictions(out.rows, gold)
        score = {"run_id": inv.run_id, "kind": "holdout-score", "created_at": runs.now_ist(), "command": command,
                 "gold": "HOLDOUT (evaluation.gold.load_gold, unlocked by holdout_run)",
                 "gold_holdout_hash": runs.gold_hash(gold), "scorer_code_sha256": runs.code_hash(),
                 "pred_sha256": out.sha256, "freeze_tag": inv.freeze_tag, "freeze_commit": ctx.freeze_commit,
                 "freeze_run": inv.freeze_run, "caveat": ctx.caveat, **result}
        runs.write_json(d / SCORE_FILE, score)
        score_sha = runs.sha256_file(d / SCORE_FILE)
    except BaseException as exc:
        attempt["failed"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        attempt["paid_sends"] = budget.calls
        attempt["spent_usd"] = budget.run_spent_usd
        _write_json_atomic(d / RECORD_FILE, rec)
    attempt["completed_at"] = _utc_now()
    rec.update({"status": "complete", "completed_at": attempt["completed_at"], "holdout_cases": len(cases),
                "output_sha256": out.sha256, "score_sha256": score_sha, "headline": _published(score),
                "budget": {"dollar_cap": HOLDOUT_DOLLAR_CAP, "call_cap": HOLDOUT_CALL_CAP,
                           "paid_sends": sum(int(a.get("paid_sends") or 0) for a in rec["attempts"]),
                           "spent_usd": sum(float(a.get("spent_usd") or 0.0) for a in rec["attempts"])},
                "freeze_check": {k: ctx.freeze_result.get(k) for k in ("passed", "counts", "output_sha256")},
                "holdout_run_check": {k: own.get(k) for k in ("passed", "counts", "refusals")},
                "model_ids": _model_ids(d)})
    _write_json_atomic(d / RECORD_FILE, rec)
    _append_access(ctx, "complete", output_sha256=out.sha256, score_sha256=score_sha)
    return rec


def _model_ids(d: Path) -> list[str]:
    """Model IDs from the holdout run's producer record, if it names them."""
    try:
        ids = json.loads((d / "producer.json").read_text(encoding="utf-8")).get("model_ids")
    except (OSError, ValueError, AttributeError):
        return []
    return [str(x) for x in ids] if isinstance(ids, list) else []


# ---- the report section ----------------------------------------------------------------------

def _rate(m: Any) -> str:
    """``n/of (rate)`` for a scorer rate block, or n/a."""
    if not isinstance(m, Mapping) or "n" not in m:
        return "n/a"
    rate = m.get("rate")
    return f"{m['n']}/{m['of']}" + ("" if rate is None else f" ({rate:.4f})")


def _num(v: Any) -> str:
    """A rate to 4 places, or n/a."""
    return "n/a" if not isinstance(v, (int, float)) else f"{v:.4f}"


def holdout_section(record: Mapping[str, Any], *, current_head: str | None = None) -> str:
    """Render the ``evaluation_report.md`` holdout section from a completed record, caveat first.

    Raises ValueError for a record that is not complete or carries no caveat: the section never
    renders a holdout number without ``notes/split.json``'s caveat. When ``current_head`` is given
    and differs from the frozen commit, the section is marked "pre-change" (../CLAUDE.md section 6).
    """
    if record.get("status") != "complete":
        raise ValueError("holdout_section needs a completed holdout record")
    caveat = record.get("caveat")
    if not isinstance(caveat, str) or not caveat.strip():
        raise ValueError("the holdout record carries no caveat; refusing to render holdout numbers")
    h = record.get("headline") or {}
    step, fields = h.get("step") or {}, h.get("field_on_matched") or {}
    budget = record.get("budget") or {}
    attempts = record.get("attempts") or []
    last = attempts[-1] if attempts else {}
    lines = [
        f"## Holdout evaluation (run {record.get('run_id')})",
        "",
        f"> **Caveat (verbatim from `{record.get('caveat_source', 'notes/split.json')}`):** {caveat}",
        "",
    ]
    commit = str(record.get("freeze_commit") or "")
    if current_head is not None and current_head != commit:
        lines += [f"**Pre-change:** the code has changed since this run (HEAD `{current_head[:12]}`, frozen "
                  f"`{commit[:12]}`). These numbers describe the frozen commit only.", ""]
    lines += [
        f"- Frozen code: tag `{record.get('freeze_tag')}` at commit `{commit}`; freeze run "
        f"`{record.get('freeze_run')}`.",
        f"- Unlocked: engine at {last.get('engine_unlocked_at')}, gold at {last.get('gold_unlocked_at')}; "
        f"completed at {record.get('completed_at')}; attempts: {len(attempts)}.",
        f"- Holdout cases: {record.get('holdout_cases')}. Output sha256 `{record.get('output_sha256')}`, "
        f"score sha256 `{record.get('score_sha256')}`.",
        f"- Paid sends in this run: {budget.get('paid_sends')}, ${_num(budget.get('spent_usd'))} "
        f"(caps ${float(budget.get('dollar_cap') or 0):.2f} and {budget.get('call_cap')} sends).",
        "",
        "| Metric | Holdout |",
        "|---|---|",
        f"| Status accuracy | {_rate(h.get('status_accuracy'))} |",
        f"| Row exact | {_rate(h.get('row_exact'))} |",
        f"| Step P / R / F1 | {_num(step.get('precision'))} / {_num(step.get('recall'))} / {_num(step.get('f1'))} |",
        f"| Field on matched: state | {_rate(fields.get('state'))} |",
        f"| Field on matched: evidence_id | {_rate(fields.get('evidence_id'))} |",
        f"| Field on matched: step_no | {_rate(fields.get('step_no'))} |",
        f"| Sequence exact | {_rate(h.get('sequence_exact'))} |",
        f"| Sequence pairwise order | {_rate(h.get('sequence_pairwise_order'))} |",
        "",
        LOCK_INCIDENT_NOTE,
        "",
    ]
    return "\n".join(lines)


# ---- command line ----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """The argument parser. ``--unlock`` has no default, no type and no file indirection."""
    ap = argparse.ArgumentParser(prog="holdout_run", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unlock", help="the developer's phrase, exactly as the developer gave it")
    ap.add_argument("--freeze-tag", required=True, help="the freeze tag, freeze-<YYYYMMDD>")
    ap.add_argument("--freeze-run", required=True, help="the final (freeze) run ID under runs/")
    ap.add_argument("--run-id", required=True, help="this run's ID, holdout-<YYYYMMDDTHHMM>")
    return ap


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None,
         runner: EngineRunner | None = None, client_factory: ClientFactory | None = None,
         freeze_checker: FreezeChecker | None = None) -> int:
    """Parse argv, run the checks, then the holdout run; return the exit status."""
    arg_list = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(arg_list)
    inv = Invocation(run_id=args.run_id, freeze_tag=args.freeze_tag, freeze_run=args.freeze_run,
                     argv=tuple(arg_list))
    s = settings or default_settings()
    checker = freeze_checker or freeze_check_mod.freeze_check
    command = "python3 -B code/evaluation/holdout_run.py " + " ".join(shlex.quote(a) for a in arg_list)
    try:
        ctx = run_checks(inv, phrase=args.unlock, settings=s, freeze_checker=checker)
    except HoldoutRefused as exc:
        print(f"HOLDOUT RUN REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        rec = execute(ctx, phrase=args.unlock, settings=s, runner=runner or pipeline_runner,
                      client_factory=client_factory or anthropic_client, freeze_checker=checker, command=command)
    except Exception as exc:  # the record keeps the failure; the same --run-id may be retried
        print(f"HOLDOUT RUN FAILED (attempt {ctx.attempt}): {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(f"HOLDOUT RUN COMPLETE: {rec['run_id']} (attempt {ctx.attempt}); record "
          f"{s.runs_root / rec['run_id'] / RECORD_FILE}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
