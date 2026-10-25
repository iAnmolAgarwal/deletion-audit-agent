"""The pipeline: inputs -> vision -> agent per case -> engine rows -> ``runs/<run_id>/output.csv`` plus artifacts.

* The output goes to ``runs/<run_id>/output.csv``. The root ``output.csv`` is written only when
  ``write_root=True`` is passed explicitly (``../CLAUDE.md`` section 5; developer approval needed).
* **Model wiring (G7; G7a's wiring proposals 1-6).** Every model call goes through GM's
  :class:`~deletion_audit.model.ModelClient`. A :class:`ModelSetup` holds the one transport, the
  one :class:`~deletion_audit.model.BudgetGuard` and the two reply-cache namespaces
  (``config.REPLY_NAMESPACES``) of a command run. **Replay-only is the default:** without a paid
  setup no request is ever sent, every cache miss is an explicit ``REPLAY_MISS`` failure, the
  intent of such a case fails closed (T71 Q2: the engine's deletion-path row, flagged) and an
  image with a missing reading stays an unparsed dependency (T8).
* **What a full run may buy:** only the case conversation (turn 1 and the loop) in the first
  namespace. The turn-1 replicate and both vision readings are replayed from the cache; they are
  bought by their own commands (:func:`run_routing_check`, :func:`run_vision`), so a full run
  never pays for a reading the developer has not seen (T88 (1), T97).
* **Order of a run:** inputs -> vision (two readings per PNG, ``learn_shapes`` then
  ``read_images``, ``vision_readings.json``/``.md`` and ``vision.json``) -> the engine's world on
  ``replace(ctx, image_observations=..., vision_read=...)`` -> per case
  :func:`~deletion_audit.agent.audit_with_agent` (``result.applied`` is the row; ``result.report``
  goes under ``"agent"`` in ``cases.jsonl``) -> the pre-write gate (inside the engine) -> output.
* **Vision review (T88 (1); G7a proposal 2):** a paid full run is refused while any image needs
  review (a failed or disagreeing reading) unless ``vision_ack`` names the vision run whose
  readings the developer reviewed, and that run's review list and readings equal this run's. The
  acknowledgement is recorded in ``producer.json``. A replay-only run is never refused for it.
* **Image answers (G7a proposal 6):** a validated ``IMAGE_FIELD_UNREADABLE`` answer is applied by
  compiling the case on a world built from ``patch_image_observations``.
* **Model-on regression gate (T100, T101; :mod:`deletion_audit.agent.regression`):** the output is
  compared row by row with the approved file named in ``notes/approved_output.json``; every changed
  row gets a cause by recompiling. A stop row or a refused baseline marks the run as not passing in
  ``producer.json`` (``run_passed`` false, with the refusal) and the CLI exits non-zero. **The gate
  is mandatory** (developer ruling T112 item 11, G7 verifier MINOR 7) whenever the model is on, that
  is, a paid run or a replay run that used at least one model reply, and whenever the root
  ``output.csv`` is to be written; ``regression_gate=True`` only adds it to an engine-only run. A run
  whose case set is not the approved file's (DEV, a fixture) is refused by the gate and so does not
  pass. **The root ``output.csv`` is written only after the gate passes** (T112 item 10, verifier
  finding 5): a stopped or refused run leaves it untouched, and ``producer.json`` says so.
* **Candidate assembly by row (developer ruling T118 (2a), (2c)):** when the gate runs, the rows as
  computed go to ``output_raw.csv`` and ``output.csv`` carries the gate's assembled rows: each
  ``kept_approved`` row is the approved file's row, byte for byte. Its ``cases.jsonl`` record is the
  engine-only recompile (fail-closed intent, no image readings) when that reproduces the approved row,
  flagged ``GATE_KEPT_APPROVED``, so the run's metrics describe ``output.csv``; ``producer.json``
  lists the kept cases and both hashes. The assembly runs after every row is computed, so no model
  request changes. A refused gate assembles nothing (``output.csv`` = the computed rows; not passing).
* **Baseline per split (developer ruling T117 B2):** ``cases="test"`` is gated against the approved
  test file, the exact DEV case set against the DEV baseline, anything else against the record's
  ``approved_output`` (so a fixture dataset needs its own record). The record lives in the package
  (``config.APPROVED_OUTPUT_RECORD``), so an unzipped ``code/`` finds it.
* **Vision review list (T112, item 4 (b)):** the images the developer must review before a paid
  full run (and that ``--vision-ack`` must cover) are the failed or disagreeing ones plus every
  image whose readings change a row (:func:`row_changing_images`: each case compiled on the world
  without and with the readings, fail-closed intent, and the images involved in each changed row).
  ``producer.vision.review.images`` lists, for each, its ``file_id`` and both reading keys, so the
  freeze check can verify that an acknowledgement covers that exact image and both readings. An
  acknowledgement never picks a reading.
* **A failed agent call (developer ruling T109 (a)):** a case whose agent loop status is ``FAILED``
  (a call failed at any turn) never becomes NOT_APPLICABLE, whatever turn 1 said. Its row is the
  engine path without model intent (the fail-closed intent of T71 Q2, compiled on the run's world
  with no model answer applied), flagged ``AGENT_CALL_FAILED``. This is decided here, in the
  pipeline's intent decision, not only in the regression gate. Nothing is re-sent: the transport's
  retry ladder stays the one place that gives up (``../CLAUDE.md`` section 5).
* Every requested case gets exactly one row; a row is never left empty (``FAILED_CLOSED``).
* **Holdout guard** (``../CLAUDE.md`` section 4): :func:`run` refuses, before it reads any input,
  an explicit case list that names a holdout case, and, after resolving ``"test"``, any resolved
  case that is one. It raises :class:`HoldoutRefused` and writes nothing. The holdout cases'
  request inputs still join the global stages (T32, T47); only running or writing them is
  refused. **The one unlock (T96):** ``holdout_unlock`` must be the developer's exact phrase,
  checked by ``evaluation.gold.check_unlock``, which raises ``HoldoutLockedError`` on any other
  value and logs a granted unlock once per run. Only ``evaluation/holdout_run.py`` passes it
  (``code/evaluation/tests/test_holdout_static.py``); the CLI never does.
* The producer record carries ``git_head`` (the 40-hex HEAD, or None outside a git checkout), so a
  freeze run names the commit it ran on (T96: ``holdout_run`` checks it against the freeze tag).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from .agent import (
    MODES,
    AgentCaseResult,
    FixedIntent,
    LoopCaps,
    ValidatedAnswer,
    VisionRun,
    audit_with_agent,
    learn_shapes,
    read_images,
    routing_table,
    vision_run_report,
    write_vision_artifacts,
)
from .agent.answers import patch_image_observations
from .agent.crosscheck import intake_crosscheck
from .agent.regression import (
    MAX_DISAGREEING,
    Baseline,
    BaselineRefused,
    CaseEvidence,
    Derivation,
    RecordView,
    Row,
    SingleReadingCheck,
    image_facts,
    judge_single_readings,
    load_baseline,
    run_gate,
)
from .agent.regression import write_gate as write_regression
from .agent.routing import text_id
from .agent.vision import image_files, reading_observations
from .artifacts import RunArtifacts, now_ist, write_json
from .config import APPROVED_OUTPUT_RECORD, REPLY_NAMESPACES
from .discovery.accounts import Flag
from .engine import AuditContext, FailClosedIntent, World, audit_case, build_context, build_world, malformed_record
from .inputs.requests import load_requests_checked
from .model import BudgetGuard, CallLog, ModelClient, ReplyCache, RetryPolicy, Transport
from .record import CaseRecord, fail_closed_intent
from .steps.serialize import render_text_rows, steps_json, write_output, write_output_bytes

Mode = Literal["A+", "A", "tools_off"]
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)
REPO_ROOT = Path(__file__).resolve().parents[2]
TEXT_SOURCES: tuple[str, ...] = ("dev", "test", "fixtures", "redteam")


class HoldoutRefused(ValueError):
    """A run named a holdout case (module docstring); the message never lists the IDs."""


class VisionReviewRequired(RuntimeError):
    """A paid full run met images that need the developer's review and no matching acknowledgement."""


def holdout_ids() -> frozenset[str]:
    """The locked holdout case IDs, from ``code/evaluation/split.py`` (the mirror of
    ``notes/split.json``). An import failure propagates: the guard never runs without its list."""
    code_dir = str(REPO_ROOT / "code")
    if code_dir not in sys.path:
        sys.path.insert(0, code_dir)
    from evaluation.split import HOLDOUT_IDS

    return frozenset(HOLDOUT_IDS)


def dev_ids() -> frozenset[str]:
    """The DEV case IDs, from ``code/evaluation/split.py``."""
    holdout_ids()  # puts code/ on the path
    from evaluation.split import DEV_IDS

    return frozenset(DEV_IDS)


def refuse_holdout(cases: Iterable[str]) -> None:
    """Raise :class:`HoldoutRefused` when any of ``cases`` is a holdout case."""
    named = set(cases) & holdout_ids()
    if named:
        raise HoldoutRefused(
            f"refused: {len(named)} holdout case(s) requested; holdout cases are never run or written "
            "(../CLAUDE.md section 4)"
        )


def guard_holdout(cases: Iterable[str], holdout_unlock: str | None, run_id: str, granted: bool) -> bool:
    """Refuse holdout cases unless ``holdout_unlock`` is the developer's phrase (module docstring).

    Returns whether the unlock is granted for this run; a granted unlock is logged once (the
    second call of a run, after ``"test"`` is resolved, passes ``granted=True``).
    """
    if not set(cases) & holdout_ids():
        return granted
    if holdout_unlock is None:
        refuse_holdout(cases)
    if not granted:
        from evaluation.gold import check_unlock  # code/ is on sys.path: holdout_ids() put it there

        check_unlock(True, holdout_unlock, "engine run", run_id)
    return True


def git_head() -> str | None:
    """The repo's HEAD commit (40 hex), or None when it cannot be read."""
    try:
        out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    head = out.stdout.strip()
    return head if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else None


# ----------------------------------------------------------------------------- model setup
class NoSendTransport:
    """The transport of a replay-only setup. A replay-only client never sends, so a send is a bug."""

    def send(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        """Refuse every send."""
        raise RuntimeError("replay-only setup: nothing is ever sent")


def namespace_roots(cache_dir: Path) -> tuple[Path, Path]:
    """The two reply-cache roots under ``cache_dir`` (``config.REPLY_NAMESPACES``)."""
    return (Path(cache_dir) / REPLY_NAMESPACES[0], Path(cache_dir) / REPLY_NAMESPACES[1])


@dataclass(frozen=True)
class ModelSetup:
    """One command run's model wiring: one transport, one BudgetGuard, one retry policy, two namespaces.

    ``paid`` False means replay only: every client is built with ``replay_only=True`` and nothing is
    sent, whatever a caller asks for. ``extra_log`` also receives every call entry (the holdout
    run's own call file).
    """

    transport: Transport
    budget: BudgetGuard
    roots: tuple[Path, Path]
    paid: bool
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    extra_log: CallLog | None = None

    def __post_init__(self) -> None:
        """Refuse one root for both namespaces (reading 2 would replay reading 1; T88 (1))."""
        if Path(self.roots[0]).resolve() == Path(self.roots[1]).resolve():
            raise ValueError("the two reply namespaces need separate cache roots")

    @classmethod
    def replay(cls, cache_dir: Path) -> ModelSetup:
        """A replay-only setup over ``cache_dir`` (no transport, a zero budget that never reserves)."""
        return cls(NoSendTransport(), BudgetGuard(0.0, 0, Path(cache_dir) / "ledger.jsonl"),
                   namespace_roots(cache_dir), paid=False)

    @classmethod
    def paid_run(cls, transport: Transport, *, dollar_cap: float, call_cap: int, cache_dir: Path) -> ModelSetup:
        """A paid setup: ``transport`` and one BudgetGuard with these caps on the project ledger."""
        return cls(transport, BudgetGuard(dollar_cap, call_cap, Path(cache_dir) / "ledger.jsonl"),
                   namespace_roots(cache_dir), paid=True)

    @classmethod
    def from_client(cls, client: ModelClient) -> ModelSetup:
        """The setup around an existing client (the holdout run's): its transport, budget, policy and log;
        its cache root is the first namespace and the second is its sibling."""
        root = Path(client.cache.root)
        if root.name != REPLY_NAMESPACES[0]:
            raise ValueError(f"the client's cache root must be named {REPLY_NAMESPACES[0]!r}")
        return cls(client.transport, client.budget, namespace_roots(root.parent), paid=not client.replay_only,
                   policy=client.policy, extra_log=client.log)

    def client(self, namespace: int, *, paid: bool, log: CallLog | RunArtifacts, run_id: str) -> ModelClient:
        """A client on one namespace; it may send only when ``paid`` and the setup is paid. Given the run's
        artifacts as ``log``, its entries are tagged with the namespace (for ``usage.json``)."""
        send = paid and self.paid
        sink = log.namespace_log(namespace) if isinstance(log, RunArtifacts) else log
        return ModelClient(self.transport, ReplyCache(self.roots[namespace]), self.budget, self.policy, sink,
                           replay_only=not send, run_id=run_id)

    def budget_record(self) -> dict[str, Any]:
        """Caps and spend of this setup's guard (for the run records)."""
        return {"paid": self.paid, "dollar_cap": self.budget.dollar_cap, "call_cap": self.budget.call_cap,
                "sends": self.budget.calls, "settled_usd": round(self.budget.run_spent_usd, 6),
                "namespaces": [Path(r).name for r in self.roots]}


class _RunLock:
    """Releases the setup's paid-run lock at the end of a command, if the command took it."""

    def __init__(self, setup: ModelSetup) -> None:
        self.setup = setup
        self.held_before = setup.budget.holds_run_lock

    def __enter__(self) -> _RunLock:
        return self

    def __exit__(self, *exc: object) -> None:
        if not self.held_before:
            self.setup.budget.release_run_lock()


# ----------------------------------------------------------------------------- the full run
@dataclass(frozen=True)
class RunSummary:
    """What a run wrote and its headline counts."""

    run_id: str
    output_path: Path
    output_sha256: str
    rows: int
    metrics: dict[str, Any]
    gate: dict[str, Any] | None = None
    passed: bool = True


def evidence_record(ctx: AuditContext, world: World) -> dict[str, Any]:
    """Producer-record evidence fields for ``evidence_guard.check_producer`` (T47, T60, T72).

    A PNG the vision step read (``ctx.vision_read``) is not a failure of the world, so it is not a
    skip; it is listed under ``evidence_read_by_vision`` instead.
    """
    skipped = sorted(f"{f.file_id}:png-model-needed" for f in world.failures if f.png)
    failures = sorted(f"{f.file_id}:{f.status}" for f in world.failures if not f.png)
    return {
        "evidence_skipped": skipped,
        "evidence_skip_count": len(skipped),
        "evidence_failures": failures,
        "evidence_no_resource_id_files": [],
        "evidence_parse": {fid: fp.status for fid, fp in ctx.index.files.items()},
        "evidence_read_by_vision": sorted(ctx.vision_read),
    }


def resolve_cases(ctx: AuditContext, cases: Sequence[str] | Literal["test"]) -> list[str]:
    """``"test"`` = every row of ``deletion_requests.csv``; otherwise the given case IDs."""
    if cases == "test":
        bad = [i.case_id for i in ctx.request_issues if i.case_id and i.file == "deletion_requests.csv"]
        return sorted({r.case_id for r in ctx.requests if r.source == "test"} | set(bad))
    return list(cases)


def row_changing_images(ctx0: AuditContext, vision: VisionRun) -> tuple[str, ...]:
    """The images read OK whose readings change a row (module docstring, item 4 (b)).

    Every request's case is compiled with the fail-closed intent on the world without the readings
    and on the world with them; for each changed row, the images involved are the read images it
    depended on and the images with an observation of any of its records. Inputs only (no gold)."""
    ok = vision.read_ok()
    if not ok:
        return ()
    plain = build_world(ctx0)
    full = build_world(replace(ctx0, image_observations=vision.observations, vision_read=ok))
    by_resource: dict[str, set[str]] = {}
    for o in vision.observations:
        if o.resource_id and o.file_id in ok:
            by_resource.setdefault(o.resource_id, set()).add(o.file_id)
    out: set[str] = set()
    intent = FailClosedIntent()
    for cid in sorted({r.case_id for r in ctx0.requests}):
        before, after = audit_case(cid, plain, intent), audit_case(cid, full, intent)
        if _row(before) == _row(after):
            continue
        involved = set(before.failed_dependencies) & ok
        for x in (*before.resources, *after.resources):
            involved |= by_resource.get(x.key.resource_id, set())
        out |= involved
    return tuple(sorted(out))


def review_list(vision: VisionRun, changing: Sequence[str]) -> tuple[str, ...]:
    """Failed or disagreeing images plus the row-changing ones, sorted (module docstring)."""
    return tuple(sorted(set(vision.needs_review()) | set(changing)))


def check_vision_ack(vision: VisionRun, ack_run_id: str | None, runs_dir: Path,
                     needs_review: Sequence[str] | None = None) -> dict[str, Any]:
    """Whether ``ack_run_id`` acknowledges exactly this run's images that need review (module docstring).

    The named run's ``vision_readings.json`` must list the same images as needing review, and its
    report of each of them (status, reply keys, both readings, agreement, flags, IDs) must equal this
    run's: the developer reviewed these very readings, not others; the report includes the sha256 of
    each reading's raw reply, so a re-read with a different reply never matches (T112 4(b)).
    ``needs_review`` is the run's review list (:func:`review_list`; default: the failed or disagreeing
    images only). When the acknowledgement matches, ``acknowledged`` lists each image with both
    reading keys and both reading hashes (the freeze check's shape); an acknowledgement never picks
    a reading.
    """
    needs = list(needs_review) if needs_review is not None else list(vision.needs_review())
    out: dict[str, Any] = {"needs_review": needs, "ack_run_id": ack_run_id, "acknowledged": []}
    if not needs:
        return {**out, "ack_matches": None, "reason": "no image needs review"}
    if ack_run_id is None:
        return {**out, "ack_matches": False, "reason": "no acknowledgement given"}
    if RUN_ID_RE.fullmatch(ack_run_id) is None:
        return {**out, "ack_matches": False, "reason": "the acknowledged run ID is not shaped like a run ID"}
    path = Path(runs_dir) / ack_run_id / "vision_readings.json"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        theirs = {i["file_id"]: i for i in body["images"]}
        listed = list(body["needs_review"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {**out, "ack_matches": False, "reason": f"the acknowledged run's vision_readings.json is unreadable "
                                                       f"({type(exc).__name__})"}
    mine = {i["file_id"]: i for i in vision_run_report(vision)}
    same = listed == needs and all(theirs.get(f) == mine.get(f) for f in needs)
    reason = "same images and readings" if same else "the acknowledged run's review list or readings differ"
    acked = [{"file_id": f, "reply_keys": list(mine[f]["reply_keys"]),
              "reading_sha256": list(mine[f]["reading_sha256"])} for f in needs] if same else []
    return {**out, "ack_matches": same, "reason": reason, "acknowledged": acked}


class _PatchedWorlds:
    """Builds the world for a case's validated image answers, and keeps it for the regression gate."""

    def __init__(self, ctx: AuditContext) -> None:
        self.ctx = ctx
        self.case: str | None = None
        self.built: dict[str, World] = {}

    def __call__(self, validated: Sequence[ValidatedAnswer]) -> World:
        obs = patch_image_observations(self.ctx.image_observations, validated)
        w = build_world(replace(self.ctx, image_observations=obs))
        if self.case is not None:
            self.built[self.case] = w
        return w


def _not_run_report(mode: str, reason: str) -> dict[str, Any]:
    """The ``"agent"`` object of a case the agent did not run (a request row that could not be loaded):
    nothing about the request is trusted, so no model sees it (T86 item 2). Same fields as G7a's report."""
    return {
        "mode": mode,
        "intent": {"label": None, "source": "FAILED_CLOSED", "committed_key": None, "final_key": None,
                   "committed_label": None, "final_label": None, "agrees": None,
                   "crosscheck": {"intake_non_deletion": False, "activity_ids": []}},
        "turn1_replicates": [], "tool_calls": [], "audit_case_calls": 0, "answers_applied": [], "answers_noted": [],
        "answers_rejected": [], "steps_differ_when_applied": False, "status": "FAILED",
        "flags": ["AGENT_NOT_RUN"], "not_run_reason": reason,
        "instruction_like_text": {"code": False, "model": False, "merged": False, "code_patterns": [],
                                  "code_sources": [], "checked": False},
        "replies": [],
    }


def _with_answers(res: AgentCaseResult) -> CaseRecord:
    """The applied record with its open questions, validated answers and rejections (G7a proposal 6)."""
    return replace(
        res.applied,
        open_questions=tuple(q.oq_id for q in res.outcome.questions),
        answers=tuple(v.oq_id for v in res.check.validated),
        rejected=tuple(f"{r.oq_id}:{r.reason}" for r in res.check.rejected),
    )


def _agent_failed_record(cid: str, world: World, res: AgentCaseResult) -> CaseRecord:
    """T109 (a): the record of a case whose agent loop FAILED (module docstring): the engine path
    without model intent, with the agent's questions, answers and rejections kept for the artifacts."""
    base = audit_case(cid, world, FixedIntent(fail_closed_intent(res.intent.crosscheck)))
    flag = Flag("AGENT_CALL_FAILED", f"agent loop FAILED ({res.outcome.failure}): engine path without model intent")
    flags = tuple(sorted(set(base.flags) | {flag}, key=lambda f: (f.code, f.detail)))
    return replace(
        base,
        flags=flags,
        open_questions=tuple(q.oq_id for q in res.outcome.questions),
        answers=tuple(v.oq_id for v in res.check.validated),
        rejected=tuple(f"{r.oq_id}:{r.reason}" for r in res.check.rejected),
    )


def _row(rec: CaseRecord) -> Row:
    return Row(rec.status, steps_json(rec.steps))


def record_derivation(rec: CaseRecord) -> Derivation:
    """Per record of the case, its state value and the evidence IDs its steps (and FINDING cite)
    name, plus the row's FAILED_CLOSED reason: what T118 rule (a) compares across readings."""
    cited: dict[tuple[str, str], set[str]] = {}
    for st in rec.steps:
        if st.evidence_id:
            cited.setdefault((st.system_id, st.resource_id), set()).add(st.evidence_id)
    views: dict[tuple[str, str], RecordView] = {}
    for r in rec.resources:
        k = (r.key.system_id, r.key.resource_id)
        ids = cited.get(k, set()) | ({r.cite} if r.cite else set())
        views[k] = RecordView(k[0], k[1], r.state.value, tuple(sorted(ids)))
    for k in set(cited) - set(views):
        views[k] = RecordView(k[0], k[1], None, tuple(sorted(cited[k])))
    return Derivation(rec.failed_closed, tuple(views[k] for k in sorted(views)))


@dataclass
class _GateInputs:
    """What the regression gate's recompiles need from one run."""

    world: World
    world_plain: World
    patched: _PatchedWorlds
    vision: VisionRun
    records: Mapping[str, CaseRecord]
    results: Mapping[str, AgentCaseResult]

    def single_readings(self, cid: str, involved: Sequence[str], intent: Any, validated: Sequence[ValidatedAnswer],
                        merged: CaseRecord) -> dict[str, SingleReadingCheck]:
        """T118 rule (a) for the case's disagreeing images (``regression`` module docstring): the case
        recompiled once per combination of their readings, each image's observations built from one
        reading alone, the other images as the run read them, the run's intent and image answers."""
        by_file = self.vision.by_file()
        files = [f for f in involved if f in by_file and by_file[f].status == "OK" and by_file[f].agree is False]
        if not files:
            return {}
        if len(files) > MAX_DISAGREEING:
            why = f"{len(files)} disagreeing images in one case: more than {MAX_DISAGREEING}, not enumerated"
            return {f: SingleReadingCheck(f, False, why) for f in files}
        ctx = self.world.ctx
        refs = {ref.file_id: ref for ref in image_files(ctx)}
        derivations: dict[tuple[int, ...], Derivation] = {}
        for combo in itertools.product((0, 1), repeat=len(files)):
            pick = dict(zip(files, combo, strict=True))
            obs = [o for r in self.vision.records
                   for o in (reading_observations(refs[r.file_id], r, pick[r.file_id]) if r.file_id in pick
                             else r.observations)]
            w = build_world(replace(ctx, image_observations=patch_image_observations(tuple(obs), validated)))
            derivations[combo] = record_derivation(audit_case(cid, w, FixedIntent(intent)))
        return {c.file_id: c for c in judge_single_readings(files, derivations, record_derivation(merged))}

    def evidence(self, cid: str) -> CaseEvidence:
        """Recompile one changed case with the intent only, the images only and both (T100)."""
        after = self.records[cid]
        res = self.results.get(cid)
        if res is None:  # the agent did not run: neither input exists for this case
            row = _row(after)
            return CaseEvidence(cid, row, row, row, row, False, None, after.intent.source, (), False)
        failed_loop = res.outcome.status == "FAILED"
        applied = after.intent if failed_loop else res.intent  # T109 (a): a failed loop has no model intent
        w_case = self.world if failed_loop else self.patched.built.get(cid, self.world)
        fail = FixedIntent(fail_closed_intent(applied.crosscheck))
        intent_only = audit_case(cid, self.world_plain, FixedIntent(applied))
        image_only = audit_case(cid, w_case, fail)
        both = audit_case(cid, w_case, FixedIntent(applied))
        plain_fc = audit_case(cid, self.world_plain, fail)
        resources = frozenset(r.key.resource_id for rec in (after, image_only) for r in rec.resources)
        png = {r.file_id for r in self.vision.records}
        image_obs = w_case.ctx.image_observations
        involved = set(plain_fc.failed_dependencies) & png
        involved |= {o.file_id for o in image_obs if o.resource_id in resources}
        waiting = sorted(r.key.resource_id for r in plain_fc.resources
                         if any(f.code == "STATE_NEEDS_IMAGE" for f in r.flags))
        supplied = sorted({o.resource_id for o in image_obs if o.file_id in involved and o.resource_id})
        validated = () if failed_loop else tuple(res.check.validated)
        singles = self.single_readings(cid, sorted(involved), applied, validated, both)
        facts = tuple(replace(f, single=singles.get(f.file_id))
                      for f in image_facts(sorted(involved), self.vision.by_file(), resources))
        return CaseEvidence(
            case_id=cid, after=_row(after), intent_only=_row(intent_only), image_only=_row(image_only),
            both=_row(both), intent_changed=applied.source in ("MODEL", "MODEL_AFTER_TOOLS"),
            intent_label=applied.label, intent_source=applied.source,
            turn1_labels=tuple(res.report["turn1_replicates"]),
            intake_non_deletion=applied.crosscheck.intake_non_deletion,
            images=facts,
            waiting_resources=tuple(waiting), image_resources=tuple(supplied),
            loop_status=res.outcome.status,
        )


def _split_of(cases: Sequence[str] | Literal["test"], wanted: Sequence[str]) -> str | None:
    """The baseline split of a run (module docstring, T117 B2): ``"test"`` for the test set, ``"dev"``
    for exactly the DEV case set, else None (the record's ``approved_output``)."""
    if cases == "test":
        return "test"
    return "dev" if set(wanted) == set(dev_ids()) else None


def _kept_record(rec: CaseRecord, plain: World, approved: Row, cause: str) -> CaseRecord:
    """The ``cases.jsonl`` record of a kept-approved case (module docstring): the engine-only
    recompile when it reproduces the approved row, else the computed record; flagged either way."""
    engine_only = audit_case(rec.case_id, plain, FixedIntent(fail_closed_intent(rec.intent.crosscheck)))
    base, how = (engine_only, "engine-only recompile") if _row(engine_only) == approved else (rec, "computed record")
    flag = Flag("GATE_KEPT_APPROVED", f"{cause} change whose condition failed: output keeps the approved row "
                                      f"(T118); this record is the {how}")
    return replace(base, flags=tuple(sorted(set(base.flags) | {flag}, key=lambda f: (f.code, f.detail))),
                   open_questions=rec.open_questions, answers=rec.answers, rejected=rec.rejected)


def _setup_for(model: ModelSetup | None, replay_only: bool) -> ModelSetup:
    """The run's setup; ``replay_only`` must agree with it (a paid run needs a paid setup)."""
    if model is None:
        if not replay_only:
            raise ValueError("a paid run needs a paid ModelSetup (pipeline.ModelSetup.paid_run)")
        return ModelSetup.replay(REPO_ROOT / "cache")
    if model.paid == replay_only:
        raise ValueError("replay_only contradicts the ModelSetup's paid flag")
    return model


def run(
    dataset_dir: Path,
    *,
    run_id: str,
    cases: Sequence[str] | Literal["test"],
    mode: Mode = "A+",
    replay_only: bool = True,
    write_root: bool = False,
    runs_dir: Path | None = None,
    command: str = "",
    holdout_unlock: str | None = None,
    model: ModelSetup | None = None,
    vision_ack: str | None = None,
    regression_gate: bool = False,
    approved_record: Path | None = None,
    caps: LoopCaps | None = None,
) -> RunSummary:
    """Run the pipeline on ``cases`` and write the run directory (module docstring).

    ``model`` is the command's :class:`ModelSetup` (default: replay only over ``cache/``);
    ``vision_ack`` the reviewed vision run ID; ``regression_gate`` turns on the T100/T101 gate
    against ``approved_record`` (default ``notes/approved_output.json``).
    """
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run id must match ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    granted = False
    if cases != "test":
        granted = guard_holdout(cases, holdout_unlock, run_id, granted)  # before any input is read
    setup = _setup_for(model, replay_only)
    t0 = time.monotonic()
    ctx0 = build_context(dataset_dir)
    wanted = resolve_cases(ctx0, cases)
    granted = guard_holdout(wanted, holdout_unlock, run_id, granted)  # also a resolved "test" run
    known = {r.case_id for r in ctx0.requests}
    malformed = {i.case_id for i in ctx0.request_issues if i.case_id}
    missing = sorted(set(wanted) - known - malformed)
    if missing:
        raise KeyError(f"{len(missing)} requested case(s) are in no request file")
    runs_root = runs_dir or REPO_ROOT / "runs"
    run_dir = runs_root / run_id
    arts = RunArtifacts(run_dir, extra_log=setup.extra_log)
    arts.start_calls()
    with _RunLock(setup):
        primary = setup.client(0, paid=True, log=arts, run_id=run_id)
        replica = setup.client(1, paid=False, log=arts, run_id=run_id)
        vision_clients = (setup.client(0, paid=False, log=arts, run_id=run_id), replica)
        vision = read_images(ctx0, vision_clients, learn_shapes(ctx0.index.observations(), ctx0.activity))
        needs = review_list(vision, row_changing_images(ctx0, vision))
        write_vision_artifacts(run_dir, vision, needs_review=needs)
        write_json(run_dir / "vision.json", vision_run_report(vision))
        review = check_vision_ack(vision, vision_ack, runs_root, needs_review=needs)
        if setup.paid and review["needs_review"] and not review["ack_matches"]:
            write_json(run_dir / "refused.json", {"run_id": run_id, "refused": "vision review required",
                                                  "vision_review": review, "created_at": now_ist()})
            raise VisionReviewRequired(
                f"refused: {len(review['needs_review'])} image(s) need the developer's review before a paid full "
                "run; pass the reviewed vision run ID (--vision-ack)")
        ctx = replace(ctx0, image_observations=vision.observations, vision_read=vision.read_ok())
        world = build_world(ctx)
        patched = _PatchedWorlds(ctx)
        records: dict[str, CaseRecord] = {}
        results: dict[str, AgentCaseResult] = {}
        for cid in sorted(set(wanted)):
            if cid not in known:
                records[cid] = malformed_record(cid, world)
                arts.case(records[cid], _not_run_report(mode, "MALFORMED_REQUEST"))
                continue
            patched.case = cid
            res = audit_with_agent(cid, world, primary, mode=mode, caps=caps, vision=vision,
                                   replicate_clients=(replica,), world_for_answers=patched)
            failed_loop = res.outcome.status == "FAILED"
            results[cid] = res
            records[cid] = _agent_failed_record(cid, world, res) if failed_loop else _with_answers(res)
            arts.case(records[cid], res.report)
    out_path = run_dir / "output.csv"
    rows = [(r.case_id, r.status, r.steps) for r in records.values()]
    gate: dict[str, Any] | None = None
    passed = True
    raw_sha: str | None = None
    kept_cases: list[str] = []
    model_on = setup.paid or any(c.outcome == "ok" and c.event in ("cache_hit", "send") for c in arts.calls)
    if not (regression_gate or model_on or write_root):
        sha = write_output(rows, out_path)
        data = out_path.read_bytes()
    else:  # T112 items 10-11: mandatory when the model is on
        raw_sha = write_output(rows, run_dir / "output_raw.csv")
        baseline: Baseline | BaselineRefused
        try:
            baseline = load_baseline(approved_record or REPO_ROOT / APPROVED_OUTPUT_RECORD, REPO_ROOT,
                                     split=_split_of(cases, wanted))
        except BaselineRefused as exc:
            baseline = exc
        plain = world if not (ctx.image_observations or ctx.vision_read) else build_world(ctx0)
        inputs = _GateInputs(world, plain, patched, vision, records, results)
        result = run_gate(baseline, {cid: _row(r) for cid, r in records.items()}, inputs.evidence)
        write_regression(run_dir, result, run_id)
        gate, passed = result.summary(), result.passed
        gate["mandatory"] = bool(model_on or write_root)
        if result.refusal is None:  # T118: the assembled rows; kept-approved rows are the approved bytes
            data = render_text_rows((cid, r.status, r.steps_json) for cid, r in result.assembled.items())
            for k in result.kept:
                kept_cases.append(k["case_id"])
                arts.records[:] = [_kept_record(rec, plain, result.assembled[rec.case_id], k["cause"])
                                   if rec.case_id == k["case_id"] else rec for rec in arts.records]
        else:
            data = (run_dir / "output_raw.csv").read_bytes()
        sha = write_output_bytes(data, out_path)
    root_written = False
    if write_root and passed:  # T112 item 10: only after the gate passes; a stopped run leaves it untouched
        root_sha = write_output_bytes(data, REPO_ROOT / "output.csv")
        if root_sha != sha:
            raise RuntimeError("root output.csv differs from the run's output.csv")
        root_written = True
    usage = arts.usage(setup.roots)
    producer = {
        "tool": "code/deletion_audit (pipeline.run)",
        "command": command,
        "description": (
            f"G7 pipeline on {len(records)} case(s), mode {mode}, "
            f"{'paid' if setup.paid else 'replay-only'}: vision, then the agent per case on the G5 engine; "
            f"{usage['replies_used']['count']} model replies used, {usage['model_calls']} sent by this run"
        ),
        "mode": mode,
        "replay_only": not setup.paid,
        "rows_written": len(records),
        "output_sha256": sha,
        "output_raw_sha256": raw_sha,
        "kept_approved_cases": kept_cases,
        "model_ids": usage["model_ids"],
        "paid_model_calls": usage["model_calls"],
        "budget": setup.budget_record(),
        "created_at": now_ist(),
        "code_sha256": code_hash(),
        "git_head": git_head(),
        "holdout_unlocked": granted,
        **evidence_record(ctx, world),
        "vision": {"images": len(vision.records), "read_ok": sorted(vision.read_ok()),
                   "observations": len(vision.observations), "review": review},
        "intent_sources": dict(sorted(Counter(r.intent.source for r in records.values()).items())),
        "regression_gate": gate if gate is not None else {"run": False},
        "model_on": model_on,
        "root_output": {"requested": write_root, "written": root_written},
        "run_passed": passed,
        "request_issues": [
            {"file": i.file, "line": i.line, "case_id": i.case_id, "reason": i.reason} for i in ctx.request_issues
        ],
    }
    if not passed and gate is not None:
        producer["refusal"] = (f"regression gate: {gate['refusal']}" if gate.get("refusal")
                               else f"regression gate: {len(gate['stop_cases'])} changed row(s) marked stop")
    metrics = arts.finish(sha, producer, time.monotonic() - t0, usage)
    return RunSummary(run_id, out_path, sha, len(records), metrics, gate, passed)


# ----------------------------------------------------------------------------- the paid entry points
@dataclass(frozen=True)
class TextCase:
    """One request of a text source: where it came from and its text (never written to an artifact)."""

    source: str
    folder: str
    dataset_dir: Path
    case_id: str
    text: str


def _fixture_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "deletion_requests.csv").is_file())


def text_cases(sources: Sequence[str], repo_root: Path = REPO_ROOT) -> list[TextCase]:
    """The requests of each named source, read from the request files only (never from gold).

    * ``dev``: the DEV case IDs (``code/evaluation/split.py``) of ``dataset/sample_deletion_requests.csv``;
      a holdout case is never included (the selection is refused if one slips in);
    * ``test``: every loadable row of ``dataset/deletion_requests.csv``;
    * ``fixtures``: every loadable row of both request files of each ``code/tests/fixtures/F*`` folder;
    * ``redteam``: the same for each ``code/tests/fixtures/redteam/R*`` folder.
    """
    unknown = sorted(set(sources) - set(TEXT_SOURCES))
    if unknown or not sources:
        raise ValueError(f"text sources must be among {list(TEXT_SOURCES)}")
    out: list[TextCase] = []
    fixtures = repo_root / "code" / "tests" / "fixtures"
    for source in sources:
        if source in ("dev", "test"):
            d = repo_root / "dataset"
            reqs, _ = load_requests_checked(d)
            if source == "dev":
                pick = [r for r in reqs if r.source == "sample" and r.case_id in dev_ids()]
                refuse_holdout(r.case_id for r in pick)
            else:
                pick = [r for r in reqs if r.source == "test"]
            out += [TextCase(source, "dataset", d, r.case_id, r.request_text) for r in pick]
            continue
        dirs = _fixture_dirs(fixtures / "redteam") if source == "redteam" else [
            p for p in _fixture_dirs(fixtures) if p.name != "redteam"]
        for d in dirs:
            reqs, _ = load_requests_checked(d)
            out += [TextCase(source, d.name, d, r.case_id, r.request_text) for r in reqs]
    return out


def _run_record(kind: str, run_id: str, command: str, setup: ModelSetup, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "run_id": run_id, "command": command, "created_at": now_ist(), "git_head": git_head(),
            "code_sha256": code_hash(), "budget": setup.budget_record(), **extra}


def run_routing_check(*, run_id: str, sources: Sequence[str], model: ModelSetup, runs_dir: Path | None = None,
                      command: str = "", repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The turn-1 routing check (G3 section 3; T70, T92, T97): turn 1 only, on every distinct text of
    ``sources``, once per namespace (two replicates; G7a's :func:`~deletion_audit.agent.routing_table`).

    Writes ``routing_table.json`` / ``.md`` (per case: each reading's label against the intake
    cross-check, and whether the two readings agree), ``calls.jsonl``, ``usage.json`` and
    ``run.json`` under ``runs/<run_id>/``. Texts are named by ``text_id``, never written.
    """
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run id must match ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    picked = text_cases(sources, repo_root)
    worlds: dict[Path, World] = {}
    for c in picked:
        if c.dataset_dir not in worlds:
            worlds[c.dataset_dir] = build_world(build_context(c.dataset_dir))
    run_dir = (runs_dir or REPO_ROOT / "runs") / run_id
    arts = RunArtifacts(run_dir, extra_log=model.extra_log)
    arts.start_calls()
    with _RunLock(model):
        clients = [model.client(i, paid=True, log=arts, run_id=run_id) for i in (0, 1)]
        table = routing_table([c.text for c in picked], clients)
    by_text = {row["text_id"]: row for row in table}
    case_rows = []
    for c in picked:
        cc = intake_crosscheck(c.case_id, worlds[c.dataset_dir])
        row = by_text[text_id(c.text)]
        case_rows.append({"source": c.source, "folder": c.folder, "case_id": c.case_id, "text_id": row["text_id"],
                          "labels": row["labels"], "agree": row["agree"], "intake_non_deletion": cc.intake_non_deletion,
                          "intake_activity_ids": list(cc.activity_ids)})
    matrix = {}
    for k, ns in enumerate(REPLY_NAMESPACES):
        counts: dict[str, dict[str, int]] = {}
        for r in case_rows:
            label = r["labels"][k] or "FAILED"
            cell = counts.setdefault(label, {"intake_row_present": 0, "intake_row_absent": 0})
            cell["intake_row_present" if r["intake_non_deletion"] else "intake_row_absent"] += 1
        matrix[ns] = dict(sorted(counts.items()))
    usage = arts.usage(model.roots)
    body = {
        "kind": "routing-check", "run_id": run_id, "sources": list(sources), "namespaces": list(REPLY_NAMESPACES),
        "distinct_texts": len(table), "cases": len(case_rows),
        "texts": table, "case_rows": case_rows, "matrix_label_x_intake": matrix,
        "replicate_agreement": {
            "texts": dict(sorted(Counter("agree" if r["agree"] else "disagree_or_failed" for r in table).items())),
            "cases": dict(sorted(Counter("agree" if r["agree"] else "disagree_or_failed" for r in case_rows).items())),
        },
        "measured": "turn-1 replies through ModelClient per namespace; intake cross-check from the engine's world",
    }
    write_json(run_dir / "routing_table.json", body)
    (run_dir / "routing_table.md").write_text(_routing_markdown(body), encoding="utf-8")
    write_json(run_dir / "usage.json", usage)
    record = _run_record("routing-check", run_id, command, model, sources=list(sources), distinct_texts=len(table),
                         cases=len(case_rows), model_calls=usage["model_calls"], model_ids=usage["model_ids"])
    write_json(run_dir / "run.json", record)
    return {**record, "matrix_label_x_intake": matrix, "replicate_agreement": body["replicate_agreement"]}


def _routing_markdown(body: Mapping[str, Any]) -> str:
    lines = [f"# Turn-1 routing check: run {body['run_id']}", "",
             f"Sources {', '.join(body['sources'])}: {body['cases']} cases, {body['distinct_texts']} distinct texts, "
             f"read once in each namespace ({', '.join(body['namespaces'])}).", ""]
    for ns, counts in body["matrix_label_x_intake"].items():
        lines += [f"## Model label x intake cross-check ({ns})", "",
                  "| label | intake row present | intake row absent |", "|---|---|---|"]
        lines += [f"| {lab} | {c['intake_row_present']} | {c['intake_row_absent']} |" for lab, c in counts.items()]
        lines.append("")
    agree = body["replicate_agreement"]
    lines += [f"Replicate agreement: texts {agree['texts']}; cases {agree['cases']}.", "",
              "| source | folder | case | text | labels | agree | intake row |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['source']} | {r['folder']} | {r['case_id']} | {r['text_id']} | {r['labels']} | {r['agree']} | "
              f"{r['intake_non_deletion']} |" for r in body["case_rows"]]
    return "\n".join(lines) + "\n"


def run_vision(dataset_dir: Path, *, run_id: str, model: ModelSetup, runs_dir: Path | None = None,
               command: str = "") -> dict[str, Any]:
    """The vision command (T88, T97): every PNG read twice, once per namespace, then compared and merged.

    Writes ``vision_readings.json`` / ``.md`` (both readings, for the developer's review),
    ``vision.json`` (G7b's adapter list), ``calls.jsonl``, ``usage.json`` and ``run.json``.
    """
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run id must match ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    ctx = build_context(dataset_dir)
    run_dir = (runs_dir or REPO_ROOT / "runs") / run_id
    arts = RunArtifacts(run_dir, extra_log=model.extra_log)
    arts.start_calls()
    with _RunLock(model):
        clients = [model.client(i, paid=True, log=arts, run_id=run_id) for i in (0, 1)]
        vision = read_images(ctx, clients, learn_shapes(ctx.index.observations(), ctx.activity))
    needs = review_list(vision, row_changing_images(ctx, vision))
    write_vision_artifacts(run_dir, vision, needs_review=needs)
    write_json(run_dir / "vision.json", vision_run_report(vision))
    usage = arts.usage(model.roots)
    write_json(run_dir / "usage.json", usage)
    record = _run_record("vision-readings", run_id, command, model, images=len(vision.records),
                         read_ok=sorted(vision.read_ok()), needs_review=list(needs),
                         model_calls=usage["model_calls"], model_ids=usage["model_ids"])
    write_json(run_dir / "run.json", record)
    return record


def code_hash() -> str:
    """sha256 over the package's .py files, by relative path (metadata for the producer record)."""
    pkg = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted(pkg.rglob("*.py")):
        h.update(str(p.relative_to(pkg)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()
