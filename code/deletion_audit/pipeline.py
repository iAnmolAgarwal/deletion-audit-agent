"""The pipeline: inputs -> vision -> agent per case -> checked rows -> ``runs/<run_id>/output.csv`` plus artifacts.

T-numbers point to ``code/docs/DECISIONS.md``. Each rule is stated first, then its reason.

* **Where output goes.** Rule: a run writes ``runs/<run_id>/output.csv``; the root ``output.csv`` is
  written only with ``write_root=True``, only for the test set, and only after the run's checks
  pass. Reason: the root file is the submission; a stopped run leaves it untouched (T112 item 10).
* **The six steps of :func:`run`.** (1) setup: check the request, refuse holdout cases, read the
  inputs; (2) vision: replay both readings of every PNG and check the review acknowledgement;
  (3) cases: the agent per case on the engine's world; (4) conditions and fallback: judge every
  model-derived change against the engine's model-free row computed in the same run; (5) write:
  ``output_raw.csv`` (as computed) and ``output.csv`` (as checked); (6) artifacts: ``producer.json``,
  ``metrics.json``, ``cases.jsonl``, ``usage.json``. Each step's function states its own rule.
* **Model wiring.** Rule: every model call goes through one :class:`ModelSetup` per command: one
  transport, one :class:`~deletion_audit.model.BudgetGuard` and the two reply-cache namespaces
  (``config.REPLY_NAMESPACES``). Replay only is the default: nothing is sent, every cache miss is an
  explicit ``REPLAY_MISS`` failure, that case's intent fails closed (the engine's deletion-path row,
  flagged, T71 Q2) and an image with a missing reading stays an unparsed dependency (T8). Reason: a
  failed call is an explicit failure, never "nothing found", and spend needs a per-run cap.
* **What a full run may buy.** Rule: only the case conversation (turn 1 and the loop), in the first
  namespace; the turn-1 replicate and both vision readings are replayed, bought only by
  :func:`run_routing_check` and :func:`run_vision`. Reason: a full run never pays for a reading the
  developer has not seen (T88 (1), T97).
* **Vision review.** Rule: a paid full run is refused while an image needs review (a failed or
  disagreeing reading, or one whose readings change a row: :func:`row_changing_images`) unless
  ``vision_ack`` names the vision run whose review list and readings equal this run's;
  ``producer.vision.review`` records it, listing each image's ``file_id`` and both reading keys. A
  replay-only run is never refused for it, and an acknowledgement never picks a reading. Reason:
  the developer must have seen these exact readings (T88 (1), T112 item 4 (b)).
* **Model-derived changes** (:mod:`deletion_audit.agent.model_changes`). Rule: an intent or image
  change applies only when its condition holds; otherwise the row is the engine's model-free row (no
  model intent, no image observations), computed in the same run; an unexplained difference marks
  the run as not passing and the CLI exits non-zero. Reason: the developer allows only two kinds of
  model change (T101 (2), T118, T119 (1)), and the runtime reads no stored output file. Comparing a
  finished run with an approved file is an evaluation check (``code/evaluation/regression_check.py``).
* **Image answers.** Rule: a validated ``IMAGE_FIELD_UNREADABLE`` answer is applied by compiling the
  case on a world built from ``patch_image_observations``. Reason: the engine decides every row
  (G7a proposal 6).
* **A failed agent call.** Rule: a case whose agent loop status is ``FAILED`` never becomes
  NOT_APPLICABLE; its row is the engine path without model intent, flagged ``AGENT_CALL_FAILED``.
  Nothing is re-sent: the transport's retry ladder is the one place that gives up. Reason: a turn-1
  label from a loop that later failed is not a decision (T109 (a)).
* **Every requested case gets exactly one row**; a row is never left empty (``FAILED_CLOSED``).
* **Holdout guard.** Rule: :func:`run` refuses, before it reads any input, an explicit case list that
  names a holdout case, and, after resolving ``"test"``, any resolved case that is one, raising
  :class:`HoldoutRefused` and writing nothing. The holdout requests still join the global stages
  (T32, T47). The one unlock is ``holdout_unlock`` equal to the developer's exact phrase, checked by
  ``evaluation.gold.check_unlock``; only ``evaluation/holdout_run.py`` passes it, never the CLI.
  Reason: the holdout split is measured once, after freeze (T96).
* The producer record carries ``git_head`` (the 40-hex HEAD, or None outside a git checkout), so a
  freeze run names the commit it ran on (T96).
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
from datetime import datetime
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
from .agent.model_changes import (
    MAX_DISAGREEING,
    CaseEvidence,
    ChangeCheck,
    Derivation,
    RecordView,
    Row,
    SingleReadingCheck,
    image_facts,
    judge_changes,
    judge_single_readings,
    write_report,
)
from .agent.routing import text_id
from .agent.vision import image_files, reading_observations
from .artifacts import IST, RunArtifacts, now_ist, write_json
from .config import REPLY_NAMESPACES
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
    """The locked holdout case IDs, from ``code/evaluation/split.py``. An import failure propagates:
    the guard never runs without its list."""
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
            "(holdout lock)"
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
    changes: dict[str, Any] | None = None  # the change check's summary (``ChangeCheck.summary``)
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
    """Builds the world for a case's validated image answers, and keeps it for the change check."""

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
class _ChangeInputs:
    """What the change check's recompiles need from one run."""

    world: World
    world_plain: World
    patched: _PatchedWorlds
    vision: VisionRun
    records: Mapping[str, CaseRecord]
    results: Mapping[str, AgentCaseResult]

    def single_readings(self, cid: str, involved: Sequence[str], intent: Any, validated: Sequence[ValidatedAnswer],
                        merged: CaseRecord) -> dict[str, SingleReadingCheck]:
        """T118 rule (a) for the case's disagreeing images (``model_changes`` module docstring): the case
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


def model_free_records(plain: World, wanted: Sequence[str], known: frozenset[str]) -> dict[str, CaseRecord]:
    """Rule: each case's model-free record is the engine on the inputs alone: the fail-closed intent
    and ``plain``, the world without image observations (a malformed request gets its malformed row).

    Reason: that is exactly what an engine-only replay writes (every model call missing, T71 Q2), so
    it is the row a case keeps when a model-derived change fails its condition, and it is computed in
    the same run instead of being read from a stored output file."""
    intent = FailClosedIntent()
    return {cid: audit_case(cid, plain, intent) if cid in known else malformed_record(cid, plain)
            for cid in sorted(set(wanted))}


def _fallback_record(rec: CaseRecord, plain: World, free: CaseRecord, cause: str) -> CaseRecord:
    """Rule: the ``cases.jsonl`` record of a case whose change fell back is the image-free recompile
    with the case's own intent when that reproduces the model-free row, else the model-free record;
    it keeps the agent's questions and answers and is flagged ``MODEL_CHANGE_FELL_BACK``.

    Reason: the run's metrics must describe ``output.csv``; a validated model intent (for example
    DELETION_REQUEST) that does not change the row is shown as it was decided, not as fail-closed
    (T118 step 4 fix)."""
    own = audit_case(rec.case_id, plain, FixedIntent(rec.intent))
    base, how = (own, "image-free recompile with the case's own intent") if _row(own) == _row(free) else (
        free, "engine's model-free record")
    flag = Flag("MODEL_CHANGE_FELL_BACK", f"{cause} change whose condition failed: output keeps the model-free row "
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


def default_run_id(now: datetime | None = None) -> str:
    """Rule: a run without an explicit ID is named ``run-<YYYYMMDDTHHMMSS>`` (IST, the build's clock).

    Reason: every run writes its own ``runs/<run_id>/`` and never the root file, so a generated name
    lets ``python code/main.py --set dev`` run without one; the format matches ``RUN_ID_RE``."""
    t = now or datetime.now(IST)
    return "run-" + t.strftime("%Y%m%dT%H%M%S")


# ----------------------------------------------------------------------------- the full run, step by step
@dataclass
class _RunPlan:
    """Step 1's result: the checked request of one run and where it writes."""

    run_id: str
    mode: Mode
    cases: Sequence[str] | Literal["test"]
    wanted: list[str]
    known: frozenset[str]
    ctx0: AuditContext
    setup: ModelSetup
    runs_root: Path
    run_dir: Path
    arts: RunArtifacts
    granted: bool
    write_root: bool
    command: str
    t0: float


@dataclass
class _Computed:
    """Step 3's result: the run's world and each case's record as computed (model answers applied)."""

    ctx: AuditContext
    world: World
    patched: _PatchedWorlds
    records: dict[str, CaseRecord]
    results: dict[str, AgentCaseResult]


@dataclass(frozen=True)
class _Clients:
    """The run's clients: the case conversation (may send on a paid setup), the turn-1 replicate, and
    the two vision readers (replay only; the second is the replicate client)."""

    primary: ModelClient
    replica: ModelClient
    vision: tuple[ModelClient, ModelClient]

    @classmethod
    def build(cls, plan: _RunPlan) -> _Clients:
        """Rule: only the case conversation may send; the replicate and both readings replay. Reason: a
        full run never buys a reading or replicate the developer has not seen (T88 (1), T97)."""
        s, arts, rid = plan.setup, plan.arts, plan.run_id
        primary = s.client(0, paid=True, log=arts, run_id=rid)
        replica = s.client(1, paid=False, log=arts, run_id=rid)
        return cls(primary, replica, (s.client(0, paid=False, log=arts, run_id=rid), replica))


@dataclass(frozen=True)
class _Written:
    """Step 5's result: the hashes written and whether the root file was written."""

    sha: str
    raw_sha: str
    root_written: bool


def _plan(dataset_dir: Path, *, run_id: str, cases: Sequence[str] | Literal["test"], mode: Mode,
          replay_only: bool, write_root: bool, runs_dir: Path | None, command: str,
          holdout_unlock: str | None, model: ModelSetup | None) -> _RunPlan:
    """Step 1, setup. Rule: refuse a bad run ID or mode, a root write for anything but the test set,
    and any holdout case (an explicit list before any input is read, a resolved ``"test"`` after);
    then read the inputs and resolve the cases.

    Reason: the root ``output.csv`` is the submission over ``deletion_requests.csv``, so only the test
    set may write it; holdout cases are never run or written without the developer's unlock (T96)."""
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run id must match ^[A-Za-z0-9][A-Za-z0-9._-]*$")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    if write_root and cases != "test":
        raise ValueError("only a run of the test set (cases='test') may write the root output.csv")
    granted = False
    if cases != "test":
        granted = guard_holdout(cases, holdout_unlock, run_id, granted)  # before any input is read
    setup = _setup_for(model, replay_only)
    t0 = time.monotonic()
    ctx0 = build_context(dataset_dir)
    wanted = resolve_cases(ctx0, cases)
    granted = guard_holdout(wanted, holdout_unlock, run_id, granted)  # also a resolved "test" run
    known = frozenset(r.case_id for r in ctx0.requests)
    malformed = {i.case_id for i in ctx0.request_issues if i.case_id}
    missing = sorted(set(wanted) - known - malformed)
    if missing:
        raise KeyError(f"{len(missing)} requested case(s) are in no request file")
    runs_root = runs_dir or REPO_ROOT / "runs"
    run_dir = runs_root / run_id
    arts = RunArtifacts(run_dir, extra_log=setup.extra_log)
    arts.start_calls()
    return _RunPlan(run_id, mode, cases, wanted, known, ctx0, setup, runs_root, run_dir, arts, granted,
                    write_root, command, t0)


def _vision(plan: _RunPlan, clients: _Clients, vision_ack: str | None) -> tuple[VisionRun, dict[str, Any]]:
    """Step 2, vision. Rule: replay both readings of every PNG, write the vision artifacts, and refuse a
    paid run while an image needs review that ``vision_ack`` does not cover.

    Reason: a full run never pays for a reading the developer has not seen, and an acknowledgement
    must name these exact readings (T88 (1), T112 item 4 (b))."""
    setup, run_id = plan.setup, plan.run_id
    ctx0 = plan.ctx0
    vision = read_images(ctx0, clients.vision, learn_shapes(ctx0.index.observations(), ctx0.activity))
    needs = review_list(vision, row_changing_images(ctx0, vision))
    write_vision_artifacts(plan.run_dir, vision, needs_review=needs)
    write_json(plan.run_dir / "vision.json", vision_run_report(vision))
    review = check_vision_ack(vision, vision_ack, plan.runs_root, needs_review=needs)
    if setup.paid and review["needs_review"] and not review["ack_matches"]:
        write_json(plan.run_dir / "refused.json", {"run_id": run_id, "refused": "vision review required",
                                                   "vision_review": review, "created_at": now_ist()})
        raise VisionReviewRequired(
            f"refused: {len(review['needs_review'])} image(s) need the developer's review before a paid full "
            "run; pass the reviewed vision run ID (--vision-ack)")
    return vision, review


def _cases(plan: _RunPlan, clients: _Clients, vision: VisionRun, caps: LoopCaps | None) -> _Computed:
    """Step 3, cases. Rule: build the world with the image readings, then audit each case in case-ID
    order with the agent; a malformed request gets its malformed row and no model sees it; a case
    whose agent loop FAILED gets the engine path without model intent.

    Reason: the model interprets and the code decides (the engine compiles every row), and a failed
    call is an explicit failure, never "nothing found" (T86 item 2, T109 (a))."""
    arts = plan.arts
    ctx = replace(plan.ctx0, image_observations=vision.observations, vision_read=vision.read_ok())
    world = build_world(ctx)
    patched = _PatchedWorlds(ctx)
    records: dict[str, CaseRecord] = {}
    results: dict[str, AgentCaseResult] = {}
    for cid in sorted(set(plan.wanted)):
        if cid not in plan.known:
            records[cid] = malformed_record(cid, world)
            arts.case(records[cid], _not_run_report(plan.mode, "MALFORMED_REQUEST"))
            continue
        patched.case = cid
        res = audit_with_agent(cid, world, clients.primary, mode=plan.mode, caps=caps, vision=vision,
                               replicate_clients=(clients.replica,), world_for_answers=patched)
        results[cid] = res
        records[cid] = _agent_failed_record(cid, world, res) if res.outcome.status == "FAILED" else _with_answers(res)
        arts.case(records[cid], res.report)
    return _Computed(ctx, world, patched, records, results)


def _conditions(plan: _RunPlan, vision: VisionRun, computed: _Computed) -> ChangeCheck:
    """Step 4, conditions and fallback. Rule: compute every case's model-free row in this run, judge
    each computed row that differs from it, and replace each change whose condition fails by the
    model-free row (its ``cases.jsonl`` record too); an unexplained change marks the run as stopped.

    Reason: a model-derived change ships only when its condition holds (T101 (2), T118 (2a)-(2c),
    T119 (1); ``model_changes`` module docstring), and the comparison never reads a stored output."""
    ctx = computed.ctx
    plain = computed.world if not (ctx.image_observations or ctx.vision_read) else build_world(plan.ctx0)
    free = model_free_records(plain, plan.wanted, plan.known)
    inputs = _ChangeInputs(computed.world, plain, computed.patched, vision, computed.records, computed.results)
    check = judge_changes({cid: _row(r) for cid, r in free.items()},
                          {cid: _row(r) for cid, r in computed.records.items()}, inputs.evidence)
    write_report(plan.run_dir, check, plan.run_id)
    fell = {k["case_id"]: k["cause"] for k in check.fell_back}
    plan.arts.records[:] = [_fallback_record(rec, plain, free[rec.case_id], fell[rec.case_id])
                            if rec.case_id in fell else rec for rec in plan.arts.records]
    return check


def _write(plan: _RunPlan, computed: _Computed, check: ChangeCheck) -> _Written:
    """Step 5, write. Rule: the rows as computed go to ``output_raw.csv``, the checked rows to
    ``output.csv``; the root ``output.csv`` is written, with the same bytes, only when asked and only
    when the run passed its checks (no stop row).

    Reason: the root file is the submission, so a stopped run leaves it untouched (T112 item 10); the
    raw file shows what each fallback replaced."""
    raw_sha = write_output([(r.case_id, r.status, r.steps) for r in computed.records.values()],
                           plan.run_dir / "output_raw.csv")
    data = render_text_rows((cid, r.status, r.steps_json) for cid, r in check.assembled.items())
    sha = write_output_bytes(data, plan.run_dir / "output.csv")
    root_written = False
    if plan.write_root and check.passed:
        if write_output_bytes(data, REPO_ROOT / "output.csv") != sha:
            raise RuntimeError("root output.csv differs from the run's output.csv")
        root_written = True
    return _Written(sha, raw_sha, root_written)


def _artifacts(plan: _RunPlan, vision: VisionRun, review: Mapping[str, Any], computed: _Computed,
               check: ChangeCheck, written: _Written) -> RunSummary:
    """Step 6, artifacts. Rule: write ``producer.json``, ``metrics.json``, ``cases.jsonl`` and
    ``usage.json``; the producer record names the output hashes, the change check's summary, whether
    the run passed and why not, and the commit it ran on.

    Reason: every number must carry its run ID and how it was measured, and the freeze check verifies
    these records against ``output.csv``."""
    setup, arts, records = plan.setup, plan.arts, computed.records
    usage = arts.usage(setup.roots)
    model_on = setup.paid or any(c.outcome == "ok" and c.event in ("cache_hit", "send") for c in arts.calls)
    summary = check.summary()
    producer = {
        "tool": "code/deletion_audit (pipeline.run)",
        "command": plan.command,
        "description": (
            f"G7 pipeline on {len(records)} case(s), mode {plan.mode}, "
            f"{'paid' if setup.paid else 'replay-only'}: vision, then the agent per case on the G5 engine; "
            f"{usage['replies_used']['count']} model replies used, {usage['model_calls']} sent by this run"
        ),
        "mode": plan.mode,
        "replay_only": not setup.paid,
        "rows_written": len(records),
        "output_sha256": written.sha,
        "output_raw_sha256": written.raw_sha,
        "fell_back_cases": summary["fell_back_cases"],
        "model_ids": usage["model_ids"],
        "paid_model_calls": usage["model_calls"],
        "budget": setup.budget_record(),
        "created_at": now_ist(),
        "code_sha256": code_hash(),
        "git_head": git_head(),
        "holdout_unlocked": plan.granted,
        **evidence_record(computed.ctx, computed.world),
        "vision": {"images": len(vision.records), "read_ok": sorted(vision.read_ok()),
                   "observations": len(vision.observations), "review": dict(review)},
        "intent_sources": dict(sorted(Counter(r.intent.source for r in records.values()).items())),
        "model_changes": summary,
        "model_on": model_on,
        "root_output": {"requested": plan.write_root, "written": written.root_written},
        "run_passed": check.passed,
        "request_issues": [
            {"file": i.file, "line": i.line, "case_id": i.case_id, "reason": i.reason}
            for i in computed.ctx.request_issues
        ],
    }
    if not check.passed:
        producer["refusal"] = f"model-derived changes: {len(check.stops)} changed row(s) marked stop (unexplained)"
    metrics = arts.finish(written.sha, producer, time.monotonic() - plan.t0, usage)
    return RunSummary(plan.run_id, plan.run_dir / "output.csv", written.sha, len(records), metrics, summary,
                      check.passed)


def run(
    dataset_dir: Path,
    *,
    run_id: str | None = None,
    cases: Sequence[str] | Literal["test"],
    mode: Mode = "A+",
    replay_only: bool = True,
    write_root: bool = False,
    runs_dir: Path | None = None,
    command: str = "",
    holdout_unlock: str | None = None,
    model: ModelSetup | None = None,
    vision_ack: str | None = None,
    caps: LoopCaps | None = None,
) -> RunSummary:
    """Run the pipeline on ``cases`` and write the run directory, in six steps (module docstring):
    setup, vision, cases, conditions and fallback, write, artifacts.

    ``run_id`` defaults to :func:`default_run_id`; ``model`` is the command's :class:`ModelSetup`
    (default: replay only over ``cache/``); ``vision_ack`` the reviewed vision run ID."""
    plan = _plan(dataset_dir, run_id=run_id or default_run_id(), cases=cases, mode=mode, replay_only=replay_only,
                 write_root=write_root, runs_dir=runs_dir, command=command, holdout_unlock=holdout_unlock,
                 model=model)
    with _RunLock(plan.setup):
        clients = _Clients.build(plan)
        vision, review = _vision(plan, clients, vision_ack)
        computed = _cases(plan, clients, vision, caps)
    check = _conditions(plan, vision, computed)
    written = _write(plan, computed, check)
    return _artifacts(plan, vision, review, computed, check, written)


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
