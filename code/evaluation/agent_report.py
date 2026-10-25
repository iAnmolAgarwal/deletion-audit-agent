"""The reported effect of the agent (G3 section 9, T63 pin 2), generated from run artifacts only.

Usage (from the repo root):
    python3 -B code/evaluation/agent_report.py --run-id <report_id> \\
        [--dev ARM=RUN_ID ...] [--test ARM=RUN_ID ...] [--fixture ARM:FIXTURE=RUN_ID ...] [--spec spec.json]

``ARM`` is ``A+``, ``A`` or ``tools_off``. ``FIXTURE`` is a folder name under
``code/tests/fixtures/``. A spec file holds the same mapping as JSON:
``{"dev": {ARM: RUN_ID}, "test": {ARM: RUN_ID}, "fixtures": {ARM: {FIXTURE: RUN_ID}}}``.
The report goes to ``runs/<report_id>/agent_report.json`` and ``agent_report.md``. Every
number in it names the run it came from and how it was measured. Nothing is typed by hand.

What it reports, per arm:
1. **N:** two tool-use rates over the run's cases, each with its run ID: cases where the model
   called ``audit_case`` (``agent.audit_case_calls`` > 0), and cases with a call to any other
   read-only tool (:data:`READ_ONLY_TOOLS`, from ``agent.tool_calls``); a tool name outside both is
   counted on its own, never folded into either rate. Plus calls per tool and the tool-sequence
   histogram.
2. **M:** cases whose steps differ with validated answers applied vs withheld, and the
   rejected answers by reason.
3. **Arm deltas:** DEV status, row exact and step F1 from ``scorer.score_predictions`` on DEV
   gold (``gold.load_gold``, DEV only), fixture pass counts, and the test rows that differ
   between arms, by case ID.
4. **Intent:** the model's label against the intake cross-check, ``agrees``, committed vs
   final intent label (T92: labels, not reply keys; the keys are read as provenance only), and
   turn-1 replicate agreement.
5. **Vision:** per-field replicate agreement per image, and the extracted resource IDs. Every
   image is reported, never dropped (T108): a failed image is listed with its failure code and
   the readings that failed, never counted as agreeing or as zero; a screenshot label that maps to
   no resource ID (no system, such as a support-ticket label) is listed and counted as unmapped;
   a disagreement on a nested field is counted and named by its path, such as
   ``records[<shown id>].sync_enabled``.
6. **Cost:** from each run's ``usage.json``.

Rules:
* **Unchecked runs never feed a report (T60, T81).** Each input run's ``producer.json`` is
  checked with ``evidence_guard.check_producer`` against the sha256 of its ``output.csv``.
  Any status other than ``ok`` refuses the whole report: exit 3, and ``refused.json`` is
  written instead of the report.
* **A missing or malformed field is an error, never a zero.** All per-case agent fields and
  the vision artifact are read through one adapter, :func:`read_run_artifacts`; their names
  sit in the constants block below, so renaming one at wiring time touches one place. If any
  case of a run has an adapter error, that run's agent sections hold the error and no counts.
  The report is still written, and the exit status is 2.
* **Untrusted data.** The report prints IDs, labels, codes and counts, never request or
  evidence text. The adapter requires names, codes, reasons and field names to be ID-shaped
  (:data:`SAFE_ID_RE`). A model-extracted resource ID that is not ID-shaped is kept but printed
  as ``<not shown>``.
* **Holdout lock.** Gold comes only from ``gold.load_gold`` with its defaults (DEV only). A
  DEV-role run holding a case outside DEV, or a test-role run holding a case outside the test
  request file, is an adapter error for that run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: same bootstrap as evaluate.py
    _here = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(_here)]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "evaluation"

from evaluation import evidence_guard, runs  # noqa: E402
from evaluation.gold import GoldCase, HoldoutLockedError, load_gold, load_requests  # noqa: E402
from evaluation.outputs import OutputFile, OutputRow, is_case_name, read_output  # noqa: E402
from evaluation.paths import REPO_ROOT, RUNS, SAMPLE_OUTPUT, TEST_REQUESTS  # noqa: E402
from evaluation.scorer import score_case, score_predictions  # noqa: E402
from evaluation.split import DEV_IDS  # noqa: E402

# ---- The artifact contract: every name the adapter reads (reconcile with G7a here only) ----
CASES_FILE = "cases.jsonl"
VISION_ARTIFACT = "vision.json"        # run-level list, one item per image (G7a names the file at wiring)
OUTPUT_FILE = "output.csv"
PRODUCER_FILE = "producer.json"
USAGE_FILE = "usage.json"
METRICS_FILE = "metrics.json"

AGENT_KEY = "agent"
RECORD_KEYS = {"case_id": "case_id", "row_state": "row_state", "failed_closed": "failed_closed",
               "flags": "flags", "flag_code": "code", "intent_source": "intent_source"}
AGENT_KEYS = {"mode": "mode", "intent": "intent", "turn1_replicates": "turn1_replicates",
              "tool_calls": "tool_calls", "audit_case_calls": "audit_case_calls",
              "answers_applied": "answers_applied", "answers_rejected": "answers_rejected",
              "steps_differ_when_applied": "steps_differ_when_applied", "status": "status", "flags": "flags",
              "replies": "replies"}
INTENT_KEYS = {"label": "label", "source": "source", "committed_key": "committed_key",
               "final_key": "final_key", "committed_label": "committed_label", "final_label": "final_label",
               "agrees": "agrees", "crosscheck": "crosscheck",
               "intake_non_deletion": "intake_non_deletion", "activity_ids": "activity_ids"}
TOOL_KEYS = {"name": "name", "args_hash": "args_hash", "is_error": "is_error", "evidence_ids": "evidence_ids"}
REJECT_KEYS = {"oq_id": "oq_id", "reason": "reason"}
# Vision: the writer is deletion_audit/agent/vision.py (image_report, reading_report) through
# agent/report.py vision_run_report (vision.json) and write_vision_artifacts (vision_readings.json).
VISION_READINGS_FILE = "vision_readings.json"  # {"images": [the vision.json items], "needs_review": [file_id]}
VISION_KEYS = {"file_id": "file_id", "status": "status", "reply_keys": "reply_keys", "readings": "readings",
               "agree": "agree", "disagreements": "disagreements", "flags": "flags", "resource_ids": "resource_ids",
               "system_id": "system_id", "resource_id": "resource_id", "well_formed": "well_formed",
               "named_elsewhere": "named_elsewhere", "shown_id": "shown_id", "basis": "basis",
               "named_by": "named_by", "images": "images", "needs_review": "needs_review"}
READING_KEYS = {"records": "records", "shown_id": "shown_id", "unreadable_count": "unreadable_count",
                "instruction_like_text": "instruction_like_text"}
VISION_SUBJECT_FIELDS: tuple[str, ...] = ("subject_emails", "subject_phones", "subject_names", "subject_user_ids")
VISION_STATE_FIELDS: tuple[str, ...] = ("sync_enabled", "restore_allowed", "marked_deleted", "download_available")
VISION_STATE_VALUES: tuple[str, ...] = ("yes", "no", "not_shown", "unreadable")
# Verbatim on-screen text per record (T112 item 9): untrusted model text, compared, never printed.
VISION_MARKERS, VISION_STATUS_LABEL = "visible_markers", "status_label"
VISION_VERBATIM_FIELDS: tuple[str, ...] = (VISION_MARKERS, VISION_STATUS_LABEL)
# The merge rule's finding value per state field (mirror of vision.FINDING_VALUE; a contract test pins it).
VISION_FINDING_VALUE: Mapping[str, str] = {"sync_enabled": "yes", "restore_allowed": "yes", "marked_deleted": "no",
                                           "download_available": "yes"}
VISION_UNREADABLE = "unreadable"
IMAGE_OK, IMAGE_FAILED = "OK", "FAILED"
IMAGE_STATUSES: tuple[str, ...] = (IMAGE_OK, IMAGE_FAILED)
VISION_NOT_PNG, VISION_READ_FAILED, VISION_DISAGREE = "VISION_NOT_PNG", "VISION_READ_FAILED", "VISION_READINGS_DISAGREE"
VISION_FAILURE_FLAGS: tuple[str, ...] = (VISION_NOT_PNG, VISION_READ_FAILED)
ID_BASES: tuple[str, ...] = ("shape", "catalog_display_name", "malformed", "unrecognized", "ambiguous")
MAPPED_BASES: frozenset[str] = frozenset({"shape", "catalog_display_name"})  # the bases that give a resource ID
SHA12_RE: re.Pattern[str] = re.compile(r"sha256:[0-9a-f]{12}", re.ASCII)
# Image-level disagreement paths (vision.compare_readings); record-level ones are records[<id>].<field>.
IMAGE_LEVEL_FIELDS: tuple[str, ...] = ("records", "instruction_like_text", "unreadable")
RECORD_LEVEL_FIELDS: tuple[str, ...] = ("count", *VISION_SUBJECT_FIELDS, *VISION_STATE_FIELDS, *VISION_VERBATIM_FIELDS)
# T112 4(a): producer.json vision.review.acknowledged = [{"file_id", "reply_keys": [reading 1, reading 2]}]
# (fix round 2 writes it; absent means nothing is acknowledged). An acknowledgement only clears the
# freeze check's disagreement count for that image; it never picks a reading.
REVIEW_KEYS = {"vision": "vision", "review": "review", "acknowledged": "acknowledged", "file_id": "file_id",
               "reply_keys": "reply_keys"}
# T112 4(b): the regression gate's report (written only with --regression-gate); read, never required.
GATE_FILE = "regression_vs_engine.json"
GATE_KEYS = {"rows": "rows", "case_id": "case_id", "cause": "cause", "image_file_ids": "image_file_ids"}
IMAGE_CAUSES: frozenset[str] = frozenset({"image", "intent+image"})
AGENT_CALL_FAILED_FLAG = "AGENT_CALL_FAILED"  # record-level flag; its detail ends "(<error class>)"
AGENT_FAILED_STATUS = "FAILED"
USAGE_KEYS: tuple[str, ...] = ("model_calls", "input_tokens", "output_tokens", "cost_usd", "model_ids")

MODES: tuple[str, ...] = ("A+", "A", "tools_off")
INTENT_LABELS: tuple[str, ...] = ("DELETION_REQUEST", "NOT_DELETION", "UNCERTAIN")
INTENT_SOURCES: tuple[str, ...] = ("MODEL", "MODEL_AFTER_TOOLS", "FAILED_CLOSED", "FAILED_BUDGET")
FAILED_SOURCES: frozenset[str] = frozenset({"FAILED_CLOSED", "FAILED_BUDGET"})
AGENT_STATUSES: tuple[str, ...] = ("OK", "FINALIZED_AT_CAP", "FAILED")
ROW_STATES: tuple[str, ...] = ("VALID", "FAILED_CLOSED")
AUDIT_CASE_TOOL = "audit_case"
# The read-only tools other than audit_case (deletion_audit/agent/tools.py TOOL_NAMES; a test keeps them equal).
READ_ONLY_TOOLS: tuple[str, ...] = ("get_request_context", "inspect_evidence", "lookup_identity", "list_activity")
INTENT_FAILED_FLAG = "INTENT_FAILED_CLOSED"
INTENT_DRIFT_FLAG = "INTENT_DRIFT"
READINGS_PER_IMAGE = 2                 # T88: each image is read twice, in separate cache namespaces
FAILED_LABEL = "FAILED"                # the intent table's row for a null label (failed intent)

SAFE_ID_RE: re.Pattern[str] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,79}", re.ASCII)
FIXTURES_ROOT: Path = REPO_ROOT / "code" / "tests" / "fixtures"
ROLES: tuple[str, ...] = ("dev", "test")
NOT_SHOWN = "<not shown>"


class ReportRefused(Exception):
    """An input run is unchecked (producer record missing, unverified, refused or mismatched)."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


# ---- Typed views of the artifacts ----
@dataclass(frozen=True)
class AdapterError:
    """One missing or malformed field: where (case or image), the field path, the problem."""

    where: str
    path: str
    problem: str


@dataclass(frozen=True)
class ToolCall:
    """One tool call other than ``audit_case``."""

    name: str
    args_hash: str
    is_error: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class IntentView:
    """The case's intent decision and its intake cross-check."""

    label: str | None
    source: str
    committed_key: str | None  # reply-cache keys: provenance only, never compared (T92)
    final_key: str | None
    agrees: bool | None
    intake_non_deletion: bool
    activity_ids: tuple[str, ...]
    committed_label: str | None = None  # the intent labels compared committed vs final (T92)
    final_label: str | None = None


@dataclass(frozen=True)
class AgentView:
    """The ``agent`` block of one ``cases.jsonl`` line."""

    mode: str
    intent: IntentView
    turn1_replicates: tuple[str | None, ...]
    tool_calls: tuple[ToolCall, ...]
    audit_case_calls: int
    answers_applied: tuple[str, ...]
    answers_rejected: tuple[tuple[str, str], ...]
    steps_differ_when_applied: bool
    status: str
    flags: tuple[str, ...]
    replies: tuple[str, ...] = ()  # the case's request keys, oldest first (provenance; the freeze check's T110 size)


@dataclass(frozen=True)
class CaseView:
    """One ``cases.jsonl`` line: record-level fields, plus the agent block when it is valid."""

    case_id: str
    row_state: str
    failed_closed: str | None
    flags: tuple[str, ...]
    intent_source: str | None
    agent: AgentView | None
    call_failure_classes: tuple[str, ...] = ()  # from record-level AGENT_CALL_FAILED details "(<class>)"


@dataclass(frozen=True)
class ResourceIdView:
    """One shown identifier of an image and how it maps to a resource ID (T88 (2)).

    ``resource_id`` is the mapped ID, or the shown label itself when ``basis`` is not in
    :data:`MAPPED_BASES` (an unmapped label). ``system_id`` is null for a label with no system."""

    system_id: str | None
    resource_id: str
    well_formed: bool
    named_elsewhere: bool
    basis: str = "shape"
    label: str = ""  # the shown ID, stripped (untrusted: printed through ``shown``)

    @property
    def mapped(self) -> bool:
        """Whether the label maps to a resource ID (shape or catalog display name)."""
        return self.basis in MAPPED_BASES


@dataclass(frozen=True)
class DisagreementView:
    """One field on which an image's two readings differ: image-level, or a record's field."""

    record: str | None  # the record's shown ID (untrusted: printed through ``shown``); None for image level
    field: str

    def display(self) -> str:
        """The path as the writer names it, with the shown ID masked unless it is ID-shaped."""
        return self.field if self.record is None else f"records[{shown(self.record)}].{self.field}"


@dataclass(frozen=True)
class ImageView:
    """One image of the vision artifact: its status, two readings' agreement and its labels.

    A FAILED image has ``agree`` None, no disagreements and no labels; ``failure_reasons`` holds
    its failure codes and ``failed_readings`` the 1-based readings that returned nothing."""

    file_id: str
    status: str
    agree: bool | None
    disagreements: tuple[DisagreementView, ...]
    flags: tuple[str, ...]
    resource_ids: tuple[ResourceIdView, ...]
    failure_reasons: tuple[str, ...] = ()
    failed_readings: tuple[int, ...] = ()
    compared_fields: tuple[tuple[str, bool], ...] = ()  # (field, the readings agree on it), OK images only
    reply_keys: tuple[str, ...] = ()  # one request key per reading (provenance; T112 4(a) acknowledgement match)

    @property
    def failed(self) -> bool:
        """Whether the image was not read (it counts as a failed reading, never as agreeing)."""
        return self.status != IMAGE_OK


@dataclass
class RunView:
    """Everything the adapter read from one run directory."""

    run_dir: Path
    cases: dict[str, CaseView] = field(default_factory=dict)
    vision: tuple[ImageView, ...] | None = None
    record_errors: list[AdapterError] = field(default_factory=list)
    agent_errors: list[AdapterError] = field(default_factory=list)
    vision_errors: list[AdapterError] = field(default_factory=list)


# ---- The adapter ----
_MISSING = object()


def _tname(v: Any) -> str:
    return "missing" if v is _MISSING else ("null" if v is None else type(v).__name__)


def _safe(v: Any) -> bool:
    return isinstance(v, str) and SAFE_ID_RE.fullmatch(v) is not None


def shown(v: Any) -> str:
    """``v`` when it is ID-shaped, else :data:`NOT_SHOWN` (untrusted values are never printed)."""
    return v if _safe(v) else NOT_SHOWN


class _Fields:
    """Typed field reads that record an :class:`AdapterError` for each bad field."""

    def __init__(self, where: str, errors: list[AdapterError]) -> None:
        self.where, self.errors, self.ok = where, errors, True

    def bad(self, path: str, problem: str) -> None:
        self.ok = False
        self.errors.append(AdapterError(self.where, path, problem))

    def get(self, obj: Any, key: str, path: str) -> Any:
        if not isinstance(obj, Mapping):
            self.bad(path, f"expected an object, got {_tname(obj)}")
            return _MISSING
        v = obj.get(key, _MISSING)
        if v is _MISSING:
            self.bad(path, "missing")
        return v

    def check(self, v: Any, ok: bool, path: str, want: str) -> Any:
        if v is not _MISSING and not ok:
            self.bad(path, f"expected {want}, got {_tname(v)}")
        return v

    def bool_(self, obj: Any, key: str, path: str, *, nullable: bool = False) -> Any:
        v = self.get(obj, key, path)
        return self.check(v, isinstance(v, bool) or (nullable and v is None), path,
                          "bool or null" if nullable else "bool")

    def str_(self, obj: Any, key: str, path: str, *, nullable: bool = False) -> Any:
        v = self.get(obj, key, path)
        return self.check(v, isinstance(v, str) or (nullable and v is None), path,
                          "string or null" if nullable else "string")

    def enum(self, obj: Any, key: str, path: str, allowed: Sequence[str | None]) -> Any:
        v = self.get(obj, key, path)
        if v is not _MISSING and v not in allowed:
            self.bad(path, f"not one of {[a for a in allowed]} (value not shown)")
        return v

    def int_(self, obj: Any, key: str, path: str) -> Any:
        v = self.get(obj, key, path)
        return self.check(v, isinstance(v, int) and not isinstance(v, bool) and v >= 0, path, "int >= 0")

    def ids(self, obj: Any, key: str, path: str) -> tuple[str, ...]:
        """A list of ID-shaped strings."""
        v = self.get(obj, key, path)
        if v is _MISSING:
            return ()
        if not isinstance(v, list):
            self.bad(path, f"expected a list, got {_tname(v)}")
            return ()
        if not all(_safe(x) for x in v):
            self.bad(path, "expected ID-shaped strings (value not shown)")
            return ()
        return tuple(v)

    def list_(self, obj: Any, key: str, path: str) -> list[Any]:
        v = self.get(obj, key, path)
        if v is _MISSING:
            return []
        if not isinstance(v, list):
            self.bad(path, f"expected a list, got {_tname(v)}")
            return []
        return v


def _adapt_intent(f: _Fields, raw: Any) -> IntentView | None:
    k = INTENT_KEYS
    p = f"{AGENT_KEY}.{AGENT_KEYS['intent']}"
    label = f.enum(raw, k["label"], f"{p}.{k['label']}", [*INTENT_LABELS, None])
    source = f.enum(raw, k["source"], f"{p}.{k['source']}", INTENT_SOURCES)
    committed = f.str_(raw, k["committed_key"], f"{p}.{k['committed_key']}", nullable=True)
    final = f.str_(raw, k["final_key"], f"{p}.{k['final_key']}", nullable=True)
    committed_label = f.enum(raw, k["committed_label"], f"{p}.{k['committed_label']}", [*INTENT_LABELS, None])
    final_label = f.enum(raw, k["final_label"], f"{p}.{k['final_label']}", [*INTENT_LABELS, None])
    agrees = f.bool_(raw, k["agrees"], f"{p}.{k['agrees']}", nullable=True)
    cc = f.get(raw, k["crosscheck"], f"{p}.{k['crosscheck']}")
    cp = f"{p}.{k['crosscheck']}"
    intake: Any = None
    acts: tuple[str, ...] = ()
    if cc is not _MISSING:
        intake = f.bool_(cc, k["intake_non_deletion"], f"{cp}.{k['intake_non_deletion']}")
        acts = f.ids(cc, k["activity_ids"], f"{cp}.{k['activity_ids']}")
    if f.ok and (source in FAILED_SOURCES) != (label is None):
        f.bad(f"{p}.{k['label']}", "label must be null exactly when the source is FAILED_CLOSED or FAILED_BUDGET")
    if not f.ok:
        return None
    return IntentView(label, source, committed, final, agrees, intake, acts, committed_label, final_label)


def _adapt_tool_calls(f: _Fields, items: list[Any], path: str) -> tuple[ToolCall, ...]:
    out = []
    k = TOOL_KEYS
    for i, t in enumerate(items):
        tp = f"{path}[{i}]"
        name = f.get(t, k["name"], f"{tp}.{k['name']}")
        if name is not _MISSING and not _safe(name):
            f.bad(f"{tp}.{k['name']}", "expected an ID-shaped tool name (value not shown)")
        elif name == AUDIT_CASE_TOOL:
            f.bad(f"{tp}.{k['name']}", f"{AUDIT_CASE_TOOL} belongs in {AGENT_KEYS['audit_case_calls']}, not here")
        args_hash = f.str_(t, k["args_hash"], f"{tp}.{k['args_hash']}")
        is_error = f.bool_(t, k["is_error"], f"{tp}.{k['is_error']}")
        ev = f.ids(t, k["evidence_ids"], f"{tp}.{k['evidence_ids']}")
        out.append(ToolCall(name, args_hash, is_error, ev))
    return tuple(out)


def _adapt_agent(f: _Fields, raw: Any) -> AgentView | None:
    k = AGENT_KEYS
    p = AGENT_KEY
    if raw is _MISSING:
        return None
    if not isinstance(raw, Mapping):
        f.bad(p, f"expected an object, got {_tname(raw)}")
        return None
    mode = f.enum(raw, k["mode"], f"{p}.{k['mode']}", MODES)
    intent = _adapt_intent(f, f.get(raw, k["intent"], f"{p}.{k['intent']}"))
    reps_raw = f.list_(raw, k["turn1_replicates"], f"{p}.{k['turn1_replicates']}")
    if not all(r in INTENT_LABELS or r is None for r in reps_raw):
        f.bad(f"{p}.{k['turn1_replicates']}", f"each item must be one of {list(INTENT_LABELS)} or null "
              "(value not shown)")
    tools = _adapt_tool_calls(f, f.list_(raw, k["tool_calls"], f"{p}.{k['tool_calls']}"), f"{p}.{k['tool_calls']}")
    audit = f.int_(raw, k["audit_case_calls"], f"{p}.{k['audit_case_calls']}")
    applied = f.ids(raw, k["answers_applied"], f"{p}.{k['answers_applied']}")
    rejected = []
    rp = f"{p}.{k['answers_rejected']}"
    for i, r in enumerate(f.list_(raw, k["answers_rejected"], rp)):
        oq = f.get(r, REJECT_KEYS["oq_id"], f"{rp}[{i}].{REJECT_KEYS['oq_id']}")
        reason = f.get(r, REJECT_KEYS["reason"], f"{rp}[{i}].{REJECT_KEYS['reason']}")
        for name, v in (("oq_id", oq), ("reason", reason)):
            if v is not _MISSING and not _safe(v):
                f.bad(f"{rp}[{i}].{REJECT_KEYS[name]}", "expected an ID-shaped string (value not shown)")
        rejected.append((oq, reason))
    differ = f.bool_(raw, k["steps_differ_when_applied"], f"{p}.{k['steps_differ_when_applied']}")
    status = f.enum(raw, k["status"], f"{p}.{k['status']}", AGENT_STATUSES)
    flags = f.ids(raw, k["flags"], f"{p}.{k['flags']}")
    replies = f.ids(raw, k["replies"], f"{p}.{k['replies']}")
    if not f.ok or intent is None:
        return None
    return AgentView(mode, intent, tuple(reps_raw), tools, audit, applied, tuple(rejected), differ, status, flags,
                     replies)


_ERROR_CLASS_RE: re.Pattern[str] = re.compile(r"\(([A-Za-z][A-Za-z0-9_]{0,79})\)\s*$", re.ASCII)


def _adapt_case(line: str, lineno: int, view: RunView, seen: set[str]) -> None:
    where = f"{CASES_FILE} line {lineno}"
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        view.record_errors.append(AdapterError(where, "<line>", "not JSON"))
        return
    k = RECORD_KEYS
    case_id: Any = raw.get(k["case_id"]) if isinstance(raw, Mapping) else None
    if not isinstance(case_id, str) or not is_case_name(case_id) or case_id in seen:
        problem = "duplicate case_id" if case_id in seen else "missing or not shaped case_<digits> (value not shown)"
        view.record_errors.append(AdapterError(where, k["case_id"], problem))
        return
    seen.add(case_id)
    rf = _Fields(case_id, view.record_errors)
    row_state = rf.enum(raw, k["row_state"], k["row_state"], ROW_STATES)
    failed_closed = rf.str_(raw, k["failed_closed"], k["failed_closed"], nullable=True)
    flags: list[str] = []
    classes: list[str] = []
    for i, fl in enumerate(rf.list_(raw, k["flags"], k["flags"])):
        code = rf.get(fl, k["flag_code"], f"{k['flags']}[{i}].{k['flag_code']}")
        if code is not _MISSING and not _safe(code):
            rf.bad(f"{k['flags']}[{i}].{k['flag_code']}", "expected an ID-shaped code (value not shown)")
        flags.append(code)
        detail = fl.get("detail") if isinstance(fl, Mapping) else None
        m = _ERROR_CLASS_RE.search(detail) if code == AGENT_CALL_FAILED_FLAG and isinstance(detail, str) else None
        if m:
            classes.append(m.group(1))
    source = raw.get(k["intent_source"])
    af = _Fields(case_id, view.agent_errors)
    agent_raw = raw.get(AGENT_KEY, _MISSING)
    if agent_raw is _MISSING:
        af.bad(AGENT_KEY, "missing")
    agent = _adapt_agent(af, agent_raw)
    if not rf.ok:
        return
    view.cases[case_id] = CaseView(case_id, row_state, failed_closed, tuple(flags),
                                   source if _safe(source) else None, agent, tuple(classes))


def _sha12(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


# The hash the writer gives a blank subject value (vision.reading_report hashes the normalized value;
# the normalizer maps a blank email, name or user ID to "" and a blank phone to "+"). The merge
# rule drops blank values. A phone with no digits also normalizes to "+", so for phones a "+"
# hash is ambiguous: a path that turns on it is "undetermined", never forced either way.
_BLANK_HASH: Mapping[str, str] = {"subject_emails": _sha12(""), "subject_phones": _sha12("+"),
                                  "subject_names": _sha12(""), "subject_user_ids": _sha12("")}
_AMBIGUOUS_BLANK = frozenset({"subject_phones"})


@dataclass(frozen=True)
class _Reading:
    """One reading report, grouped as the writer compares it: records by stripped shown ID."""

    groups: Mapping[str, tuple[Mapping[str, Any], ...]]
    unreadable: bool
    instruction_like_text: bool


def _adapt_reading(f: _Fields, raw: Any, path: str) -> _Reading | None:
    """Type-check one non-null reading report (``vision.reading_report``)."""
    k = READING_KEYS
    before = len(f.errors)
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for i, r in enumerate(f.list_(raw, k["records"], f"{path}.{k['records']}")):
        rp = f"{path}.{k['records']}[{i}]"
        sid = f.str_(r, k["shown_id"], f"{rp}.{k['shown_id']}")
        for name in VISION_SUBJECT_FIELDS:
            v = f.list_(r, name, f"{rp}.{name}")
            if not all(isinstance(x, str) and SHA12_RE.fullmatch(x) for x in v):
                f.bad(f"{rp}.{name}", "expected sha256 prefixes (value not shown)")
        for name in VISION_STATE_FIELDS:
            f.enum(r, name, f"{rp}.{name}", VISION_STATE_VALUES)
        markers = f.list_(r, VISION_MARKERS, f"{rp}.{VISION_MARKERS}")
        if not all(isinstance(x, str) for x in markers):
            f.bad(f"{rp}.{VISION_MARKERS}", "expected strings (values not shown)")
        f.str_(r, VISION_STATUS_LABEL, f"{rp}.{VISION_STATUS_LABEL}")
        if isinstance(sid, str):
            groups.setdefault(sid.strip(), []).append(r)
    count = f.int_(raw, k["unreadable_count"], f"{path}.{k['unreadable_count']}")
    ilt = f.bool_(raw, k["instruction_like_text"], f"{path}.{k['instruction_like_text']}")
    if len(f.errors) > before:
        return None
    return _Reading({s: tuple(g) for s, g in groups.items()}, count > 0, ilt)


def _merged_state(records: Sequence[Mapping[str, Any]], name: str) -> str:
    """The merge rule (``vision._merge_state``): equal values stand, else the finding value, else unreadable."""
    distinct = {r[name] for r in records}
    if len(distinct) == 1:
        return str(next(iter(distinct)))
    return VISION_FINDING_VALUE[name] if VISION_FINDING_VALUE[name] in distinct else VISION_UNREADABLE


def _merged_verbatim(records: Sequence[Mapping[str, Any]]) -> tuple[frozenset[str], str]:
    """The merge rule for verbatim text (``vision.merge_records``): non-blank markers united; non-blank
    status labels sorted and joined with " | "."""
    markers = frozenset(m for r in records for m in r[VISION_MARKERS] if m.strip())
    label = " | ".join(sorted({r[VISION_STATUS_LABEL] for r in records if r[VISION_STATUS_LABEL].strip()}))
    return markers, label


def _subject_hashes(records: Sequence[Mapping[str, Any]], name: str) -> tuple[frozenset[str], frozenset[str]]:
    """A record group's subject hashes: (blank hash dropped, all hashes)."""
    every = frozenset(h for r in records for h in r[name])
    return every - {_BLANK_HASH[name]}, every


def _path(record: str | None, fld: str) -> str:
    return fld if record is None else f"records[{record}].{fld}"


_Paths = dict[str, DisagreementView]


def compare_reading_reports(a: _Reading, b: _Reading) -> tuple[_Paths, _Paths]:
    """The writer's comparison (``vision.compare_readings``) redone on two reading reports.

    Returns ``(definite, undetermined)`` paths: the readings certainly differ on each definite
    path; an undetermined path turns on a "+" phone hash, which may be a blank (dropped by the
    merge rule) or a phone with no digits (kept)."""
    definite: dict[str, DisagreementView] = {}
    maybe: dict[str, DisagreementView] = {}

    def add(target: dict[str, DisagreementView], record: str | None, fld: str) -> None:
        target[_path(record, fld)] = DisagreementView(record, fld)

    if set(a.groups) != set(b.groups):
        add(definite, None, "records")
    for sid in sorted(set(a.groups) & set(b.groups)):
        ra, rb = a.groups[sid], b.groups[sid]
        if len(ra) != len(rb):
            add(definite, sid, "count")
        for name in VISION_SUBJECT_FIELDS:
            (da, ka), (db, kb) = _subject_hashes(ra, name), _subject_hashes(rb, name)
            if name not in _AMBIGUOUS_BLANK:
                if da != db:
                    add(definite, sid, name)
            elif da != db and ka != kb:
                add(definite, sid, name)
            elif da != db or ka != kb:
                add(maybe, sid, name)
        for name in VISION_STATE_FIELDS:
            if _merged_state(ra, name) != _merged_state(rb, name):
                add(definite, sid, name)
        (ma, la), (mb, lb) = _merged_verbatim(ra), _merged_verbatim(rb)
        if ma != mb:
            add(definite, sid, VISION_MARKERS)
        if la != lb:
            add(definite, sid, VISION_STATUS_LABEL)
    if a.instruction_like_text != b.instruction_like_text:
        add(definite, None, "instruction_like_text")
    if a.unreadable != b.unreadable:
        add(definite, None, "unreadable")
    return definite, maybe


def _adapt_resource_ids(f: _Fields, raw: Any, path: str) -> list[ResourceIdView]:
    k = VISION_KEYS
    rids = []
    rp = f"{path}.{k['resource_ids']}"
    for i, r in enumerate(f.list_(raw, k["resource_ids"], rp)):
        ip = f"{rp}[{i}]"
        before = len(f.errors)
        sys_id = f.str_(r, k["system_id"], f"{ip}.{k['system_id']}", nullable=True)
        res_id = f.str_(r, k["resource_id"], f"{ip}.{k['resource_id']}")
        wf = f.bool_(r, k["well_formed"], f"{ip}.{k['well_formed']}")
        ne = f.bool_(r, k["named_elsewhere"], f"{ip}.{k['named_elsewhere']}")
        shown_id = f.str_(r, k["shown_id"], f"{ip}.{k['shown_id']}")
        basis = f.enum(r, k["basis"], f"{ip}.{k['basis']}", ID_BASES)
        named_by = f.ids(r, k["named_by"], f"{ip}.{k['named_by']}")
        if len(f.errors) > before:
            continue
        mapped = basis in MAPPED_BASES
        if wf != mapped or (mapped and sys_id is None):
            f.bad(f"{ip}.{k['basis']}", "well_formed must hold exactly for a mapped basis, which needs a system_id")
        if ne != bool(named_by):
            f.bad(f"{ip}.{k['named_elsewhere']}", "must equal whether named_by is non-empty")
        if not mapped and res_id != shown_id.strip():
            f.bad(f"{ip}.{k['resource_id']}", "an unmapped label must be reported as its shown ID")
        if len(f.errors) == before:
            rids.append(ResourceIdView(sys_id, res_id, wf, ne, basis, shown_id.strip()))
    return rids


def _adapt_image(f: _Fields, raw: Any, path: str) -> ImageView | None:
    """Type-check one image item and redo its comparison from its two readings (never trusted as given)."""
    k = VISION_KEYS
    file_id = f.get(raw, k["file_id"], f"{path}.{k['file_id']}")
    if file_id is not _MISSING and not _safe(file_id):
        f.bad(f"{path}.{k['file_id']}", "expected an ID-shaped file_id (value not shown)")
    status = f.enum(raw, k["status"], f"{path}.{k['status']}", IMAGE_STATUSES)
    keys = f.list_(raw, k["reply_keys"], f"{path}.{k['reply_keys']}")
    if not all(isinstance(x, str) for x in keys):
        f.bad(f"{path}.{k['reply_keys']}", "expected strings")
    readings = f.list_(raw, k["readings"], f"{path}.{k['readings']}")
    agree = f.bool_(raw, k["agree"], f"{path}.{k['agree']}", nullable=True)
    dis_raw = f.list_(raw, k["disagreements"], f"{path}.{k['disagreements']}")
    if not all(isinstance(x, str) for x in dis_raw):
        f.bad(f"{path}.{k['disagreements']}", "expected strings (values not shown)")
    flags = f.ids(raw, k["flags"], f"{path}.{k['flags']}")
    rids = _adapt_resource_ids(f, raw, path)
    if len(keys) != len(readings):
        f.bad(f"{path}.{k['reply_keys']}", "expected one reply key per reading")
    parsed: list[_Reading | None] = []
    for i, r in enumerate(readings):
        parsed.append(None if r is None else _adapt_reading(f, r, f"{path}.{k['readings']}[{i}]"))
    if not f.ok:
        return None
    failures = tuple(c for c in VISION_FAILURE_FLAGS if c in flags)
    if status == IMAGE_FAILED:
        img = _failed_image(f, path, file_id, readings, agree, dis_raw, flags, rids, failures)
        return None if img is None else ImageView(**{**img.__dict__, "reply_keys": tuple(keys)})
    if len(readings) != READINGS_PER_IMAGE or any(r is None for r in readings):
        f.bad(f"{path}.{k['readings']}", f"an OK image needs {READINGS_PER_IMAGE} non-null readings (T88)")
        return None
    if failures:
        f.bad(f"{path}.{k['flags']}", f"an OK image carries the failure flag(s) {list(failures)}")
        return None
    a, b = parsed
    assert a is not None and b is not None
    definite, maybe = compare_reading_reports(a, b)
    listed = list(dis_raw)
    if len(set(listed)) != len(listed) or not set(definite) <= set(listed) <= set(definite) | set(maybe):
        f.bad(f"{path}.{k['disagreements']}", f"inconsistent with the readings: they differ on {len(definite)} "
              f"path(s) ({len(maybe)} undetermined), the artifact lists {len(listed)}")
        return None
    if agree != (not listed) or (VISION_DISAGREE in flags) != bool(listed):
        f.bad(f"{path}.{k['agree']}", f"agree={agree} and the {VISION_DISAGREE} flag must both follow the "
              f"{len(listed)} listed disagreement(s)")
        return None
    labels = sorted(set(a.groups) | set(b.groups))
    if sorted(r.label for r in rids) != labels:
        f.bad(f"{path}.{k['resource_ids']}", f"expected one entry per shown record ({len(labels)}), "
              f"got {len(rids)}")
        return None
    paths = {**maybe, **definite}
    dis = tuple(paths[p] for p in sorted(listed))
    differing = {d.field for d in dis}
    fields = [*IMAGE_LEVEL_FIELDS, *(RECORD_LEVEL_FIELDS if set(a.groups) & set(b.groups) else ())]
    return ImageView(file_id, status, agree, dis, flags, tuple(rids),
                     compared_fields=tuple((x, x not in differing) for x in fields), reply_keys=tuple(keys))


def _failed_image(f: _Fields, path: str, file_id: str, readings: list[Any], agree: Any, dis: list[Any],
                  flags: tuple[str, ...], rids: list[ResourceIdView], failures: tuple[str, ...]) -> ImageView | None:
    """A FAILED image: a failed reading with its reason, never empty or zero (T108)."""
    k = VISION_KEYS
    if not failures:
        f.bad(f"{path}.{k['flags']}", f"a FAILED image names no failure reason ({' or '.join(VISION_FAILURE_FLAGS)})")
    if agree is not None or dis or rids:
        f.bad(f"{path}.{k['agree']}", "a FAILED image has agree null, no disagreements and no resource IDs")
    if readings and (len(readings) != READINGS_PER_IMAGE or all(r is not None for r in readings)):
        f.bad(f"{path}.{k['readings']}", f"a FAILED image has no readings or {READINGS_PER_IMAGE} with a null one")
    if not readings and VISION_NOT_PNG not in failures:
        f.bad(f"{path}.{k['flags']}", f"an image with no reading attempt must carry {VISION_NOT_PNG}")
    if readings and VISION_READ_FAILED not in failures:
        f.bad(f"{path}.{k['flags']}", f"an image with a null reading must carry {VISION_READ_FAILED}")
    if not f.ok:
        return None
    return ImageView(file_id, IMAGE_FAILED, None, (), flags, (), failure_reasons=failures,
                     failed_readings=tuple(i + 1 for i, r in enumerate(readings) if r is None))


def needs_review(images: Sequence[ImageView]) -> list[str]:
    """The writer's review list (``VisionRun.needs_review``): failed or disagreeing images, sorted."""
    return sorted(i.file_id for i in images if i.failed or i.agree is False)


def acknowledged_images(producer: Mapping[str, Any], images: Sequence[ImageView]) -> tuple[frozenset[str], list[str]]:
    """T112 4(a): disagreeing images whose recorded acknowledgement names that file_id and both of its
    reading keys exactly; and the problems with the record. A missing list acknowledges nothing."""
    k = REVIEW_KEYS
    vision = producer.get(k["vision"])
    review = vision.get(k["review"]) if isinstance(vision, Mapping) else None
    acks = review.get(k["acknowledged"], _MISSING) if isinstance(review, Mapping) else _MISSING
    if acks is _MISSING:
        return frozenset(), []
    where = f"{PRODUCER_FILE} {k['vision']}.{k['review']}.{k['acknowledged']}"
    if not isinstance(acks, list):
        return frozenset(), [f"{where}: expected a list, got {_tname(acks)}"]
    keys_by_file: dict[str, tuple[str, ...]] = {}
    for i, a in enumerate(acks):
        fid = a.get(k["file_id"]) if isinstance(a, Mapping) else None
        keys = a.get(k["reply_keys"]) if isinstance(a, Mapping) else None
        if not isinstance(fid, str) or not _safe(fid) or not isinstance(keys, list) or len(keys) != READINGS_PER_IMAGE \
                or not all(isinstance(x, str) for x in keys):
            return frozenset(), [f"{where}[{i}]: expected an ID-shaped file_id and {READINGS_PER_IMAGE} reading keys"]
        keys_by_file[fid] = tuple(keys)
    return frozenset(i.file_id for i in images if i.agree is False and keys_by_file.get(i.file_id) == i.reply_keys
                     and len(i.reply_keys) == READINGS_PER_IMAGE), []


def row_changing_images(run_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """T112 4(b), read only: images the regression gate names as a cause of a changed row, with those cases.

    ``source`` is None when the run has no gate report (the gate is opt-in), which is not a zero."""
    path = run_dir / GATE_FILE
    if not path.exists():
        return {"source": None, "images": {}}, []
    body = _read_json(path)
    k = GATE_KEYS
    rows = body.get(k["rows"]) if isinstance(body, Mapping) else None
    if not isinstance(rows, list):
        return {"source": GATE_FILE, "images": {}}, [f"{GATE_FILE}: unreadable or {k['rows']} is not a list"]
    out: dict[str, list[str]] = {}
    for i, r in enumerate(rows):
        cid = r.get(k["case_id"]) if isinstance(r, Mapping) else None
        files = r.get(k["image_file_ids"]) if isinstance(r, Mapping) else None
        if not isinstance(files, list) or not all(_safe(f) for f in files) or not isinstance(cid, str) \
                or not is_case_name(cid):
            return {"source": GATE_FILE, "images": {}}, [f"{GATE_FILE} {k['rows']}[{i}]: malformed (value not shown)"]
        if r.get(k["cause"]) in IMAGE_CAUSES:
            for fid in files:
                out.setdefault(fid, []).append(cid)
    return {"source": GATE_FILE, "images": {f: sorted(c) for f, c in sorted(out.items())}}, []


def _adapt_vision(view: RunView) -> None:
    path = view.run_dir / VISION_ARTIFACT
    where = VISION_ARTIFACT
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        view.vision_errors.append(AdapterError(where, "<file>", "missing (a run that read no image writes [])"))
        return
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        view.vision_errors.append(AdapterError(where, "<file>", f"unreadable: {type(exc).__name__}"))
        return
    if not isinstance(raw, list):
        view.vision_errors.append(AdapterError(where, "<file>", f"expected a list, got {_tname(raw)}"))
        return
    images = []
    for i, item in enumerate(raw):
        img = _adapt_image(_Fields(f"{where}[{i}]", view.vision_errors), item, f"[{i}]")
        if img is not None:
            images.append(img)
    ids = [i.file_id for i in images]
    if len(set(ids)) != len(ids):
        view.vision_errors.append(AdapterError(where, VISION_KEYS["file_id"], "duplicate file_id"))
    _check_review_file(view, raw, images)
    if not view.vision_errors:
        view.vision = tuple(images)


def _check_review_file(view: RunView, raw: list[Any], images: Sequence[ImageView]) -> None:
    """``vision_readings.json`` (the developer's review file) must hold the same images, and a review list
    that is a sorted list of distinct file IDs of those images containing every failed and disagreeing
    one. Since T112 4(b) the writer lists every image whose reading changes a row as well (a superset),
    so only a missing failed or disagreeing image, or an image not in the artifact, is refused."""
    k = VISION_KEYS
    where = VISION_READINGS_FILE
    body = _read_json(view.run_dir / where)
    if not isinstance(body, Mapping):
        view.vision_errors.append(AdapterError(where, "<file>", "missing or not a JSON object (the vision step "
                                                                f"writes it beside {VISION_ARTIFACT})"))
        return
    if body.get(k["images"]) != raw:
        view.vision_errors.append(AdapterError(where, k["images"], f"differs from {VISION_ARTIFACT}"))
    if view.vision_errors:
        return
    listed = body.get(k["needs_review"])
    if not (isinstance(listed, list) and all(isinstance(x, str) for x in listed) and listed == sorted(set(listed))):
        view.vision_errors.append(AdapterError(where, k["needs_review"], "not a sorted list of distinct file IDs"))
        return
    if set(needs_review(images)) - set(listed):
        view.vision_errors.append(AdapterError(where, k["needs_review"], "omits a failed or disagreeing image of "
                                                                         f"{VISION_ARTIFACT}"))
    if set(listed) - {i.file_id for i in images}:
        view.vision_errors.append(AdapterError(where, k["needs_review"], f"names an image not in {VISION_ARTIFACT}"))


def read_run_artifacts(run_dir: Path) -> RunView:
    """THE adapter: read ``cases.jsonl`` (record and ``agent`` fields) and the vision artifact.

    Every field is type-checked. A missing or malformed field becomes an :class:`AdapterError`
    in ``record_errors``, ``agent_errors`` or ``vision_errors``, never a default value.
    """
    view = RunView(run_dir)
    try:
        text = (run_dir / CASES_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        view.record_errors.append(AdapterError(CASES_FILE, "<file>", f"unreadable: {type(exc).__name__}"))
        text = ""
    seen: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            _adapt_case(line, lineno, view, seen)
    _adapt_vision(view)
    return view


def summarize_errors(errors: Iterable[AdapterError], sample: int = 5) -> list[dict[str, Any]]:
    """Group errors by (field path, problem): a count and up to ``sample`` places."""
    groups: dict[tuple[str, str], list[str]] = {}
    for e in errors:
        groups.setdefault((re.sub(r"\[\d+\]", "[*]", e.path), e.problem), []).append(e.where)
    return [{"path": p, "problem": pr, "count": len(w), "where": w[:sample]} for (p, pr), w in sorted(groups.items())]


# ---- Loading and checking a run ----
@dataclass
class LoadedRun:
    """A run directory read for the report: producer check, output, usage and the adapter view."""

    run_id: str
    run_dir: Path
    producer: dict[str, Any]
    producer_check: dict[str, Any]
    output: OutputFile | None
    usage: dict[str, Any] | None
    usage_errors: list[str]
    view: RunView


def run_path(runs_root: Path, run_id: str) -> Path:
    """``<runs_root>/<run_id>`` with the run ID checked (T67/T72); never created here."""
    return runs_root / runs.check_run_id(run_id)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def read_usage(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """``usage.json`` with its five fields type-checked; (None, errors) if any is bad."""
    raw = _read_json(path)
    if not isinstance(raw, Mapping):
        return None, [f"{USAGE_FILE}: missing or not a JSON object"]
    errs = []
    for k in USAGE_KEYS:
        v = raw.get(k, _MISSING)
        ok = (isinstance(v, list) and all(_safe(x) for x in v)) if k == "model_ids" else (
            isinstance(v, int | float) and not isinstance(v, bool) and v >= 0)
        if not ok:
            errs.append(f"{USAGE_FILE}.{k}: expected {'ID list' if k == 'model_ids' else 'number >= 0'}, "
                        f"got {_tname(v)}")
    return (None, errs) if errs else ({k: raw[k] for k in USAGE_KEYS}, [])


def load_run(runs_root: Path, run_id: str) -> LoadedRun:
    """Read one run: producer check against its ``output.csv`` hash, usage, adapter view."""
    d = run_path(runs_root, run_id)
    producer = _read_json(d / PRODUCER_FILE)
    producer = producer if isinstance(producer, dict) else {}
    output: OutputFile | None = None
    try:
        output = read_output(d / OUTPUT_FILE)
    except HoldoutLockedError:
        raise  # the gold file is never read as a run's output; the refusal must stay visible
    except OSError:
        output = None
    pcheck = evidence_guard.check_producer(producer, pred_sha256=output.sha256 if output else None)
    if output is None:
        pcheck = {**pcheck, "status": "no-output", "reasons": [f"{OUTPUT_FILE} missing or unreadable"]}
    usage, usage_errors = read_usage(d / USAGE_FILE)
    return LoadedRun(run_id, d, producer, pcheck, output, usage, usage_errors, read_run_artifacts(d))


# ---- The counts (each reads only the adapter's views) ----
def count_tools(cases: Sequence[AgentView]) -> dict[str, Any]:
    """N: the two tool-use rates (audit_case; other read-only tools), per tool, sequence histogram."""
    per_tool: dict[str, dict[str, int]] = {}
    seqs: Counter[str] = Counter()
    for a in cases:
        names = [t.name for t in a.tool_calls]
        seqs[" > ".join(names) if names else "(none)"] += 1
        for name in sorted(set(names)):
            per_tool.setdefault(name, {"cases": 0, "calls": 0, "error_calls": 0})["cases"] += 1
        for t in a.tool_calls:
            per_tool[t.name]["calls"] += 1
            per_tool[t.name]["error_calls"] += int(t.is_error)
    return {
        "cases": len(cases),
        "cases_with_tool_call": sum(1 for a in cases if a.tool_calls),
        "cases_with_read_only_tool": sum(1 for a in cases if any(t.name in READ_ONLY_TOOLS for t in a.tool_calls)),
        "cases_with_unknown_tool": sum(1 for a in cases if any(t.name not in READ_ONLY_TOOLS for t in a.tool_calls)),
        "tool_calls": sum(len(a.tool_calls) for a in cases),
        "per_tool": dict(sorted(per_tool.items())),
        "sequence_histogram": dict(sorted(seqs.items(), key=lambda kv: (-kv[1], kv[0]))),
        "audit_case": {"calls": sum(a.audit_case_calls for a in cases),
                       "cases_with_call": sum(1 for a in cases if a.audit_case_calls > 0)},
        "agent_status": dict(sorted(Counter(a.status for a in cases).items())),
    }


def count_answers(cases: Sequence[AgentView], case_ids: Sequence[str]) -> dict[str, Any]:
    """M: cases whose steps differ with answers applied vs withheld; rejections by reason."""
    return {
        "cases": len(cases),
        "cases_steps_differ": sum(1 for a in cases if a.steps_differ_when_applied),
        "steps_differ_case_ids": sorted(c for c, a in zip(case_ids, cases, strict=True) if a.steps_differ_when_applied),
        "answers_applied": sum(len(a.answers_applied) for a in cases),
        "cases_with_answer_applied": sum(1 for a in cases if a.answers_applied),
        "answers_rejected": sum(len(a.answers_rejected) for a in cases),
        "rejected_by_reason": dict(sorted(Counter(r for a in cases for _, r in a.answers_rejected).items())),
    }


def _all_flags(c: CaseView) -> set[str]:
    return set(c.flags) | (set(c.agent.flags) if c.agent else set())


def intent_table(cases: Sequence[CaseView]) -> dict[str, Any]:
    """Intent: model label (or FAILED) x intake cross-check row, agrees, committed/final label, replicates."""
    rows = {lab: {"intake_row_present": 0, "intake_row_absent": 0} for lab in (*INTENT_LABELS, FAILED_LABEL)}
    agrees: Counter[str] = Counter()
    cvf: Counter[str] = Counter()
    reps: Counter[str] = Counter()
    rep_disagree: list[str] = []
    for c in cases:
        a = c.agent
        assert a is not None  # callers pass only cases with a valid agent block
        it = a.intent
        rows[it.label or FAILED_LABEL]["intake_row_present" if it.intake_non_deletion else "intake_row_absent"] += 1
        agrees[{True: "true", False: "false", None: "null"}[it.agrees]] += 1
        if it.committed_label is None and it.final_label is None:
            cvf["both_null"] += 1
        elif it.committed_label is None or it.final_label is None:
            cvf["one_null"] += 1
        else:
            cvf["equal" if it.committed_label == it.final_label else "differ"] += 1
        if len(a.turn1_replicates) < 2:
            reps["fewer_than_2"] += 1
        elif len(set(a.turn1_replicates)) == 1:
            reps["all_agree"] += 1
        else:
            reps["disagree"] += 1
            rep_disagree.append(c.case_id)
    return {
        "cases": len(cases),
        "table": rows,
        "agrees": dict(sorted(agrees.items())),
        "sources": dict(sorted(Counter(c.agent.intent.source for c in cases if c.agent).items())),
        "committed_vs_final_label": dict(sorted(cvf.items())),
        "intent_drift_flagged_cases": sum(1 for c in cases if INTENT_DRIFT_FLAG in _all_flags(c)),
        "turn1_replicates": {**dict(sorted(reps.items())), "disagree_case_ids": sorted(rep_disagree)},
    }


def vision_summary(images: Sequence[ImageView], acknowledged: frozenset[str] = frozenset(),
                   row_changes: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Vision: every image reported (T108). Failed images are counted and listed with their
    reasons and kept out of the agreement counts; disagreements are counted per image and named
    by path; unmapped labels are counted and listed; per-field agreement covers read images."""
    read = [i for i in images if not i.failed]
    failed = [i for i in images if i.failed]
    per_field: dict[str, dict[str, int]] = {}
    for img in read:
        for fld, agreed in img.compared_fields:
            slot = per_field.setdefault(fld, {"images": 0, "agree": 0})
            slot["images"] += 1
            slot["agree"] += int(agreed)
    rids = [(img.file_id, r) for img in images for r in img.resource_ids]
    unmapped = [{"file_id": f, "label": shown(r.label), "basis": r.basis,
                 "system_id": None if r.system_id is None else shown(r.system_id)} for f, r in rids if not r.mapped]
    flagged = [{"file_id": f, "system_id": shown(r.system_id), "resource_id": shown(r.resource_id),
                "reasons": ["named_nowhere_else"]} for f, r in rids if r.mapped and not r.named_elsewhere]
    disagreeing = [i for i in read if i.agree is False]
    return {
        "images": len(images),
        "images_read": len(read),
        "images_failed": len(failed),
        "failed": [{"file_id": i.file_id, "reasons": list(i.failure_reasons),
                    "failed_readings": list(i.failed_readings)} for i in sorted(failed, key=lambda x: x.file_id)],
        "images_agree": sum(1 for i in read if i.agree),
        "images_disagree": len(disagreeing),
        "disagreeing_file_ids": sorted(i.file_id for i in disagreeing),
        "disagreement_paths": sum(len(i.disagreements) for i in disagreeing),
        "disagreements": [{"file_id": i.file_id, "paths": [d.display() for d in i.disagreements]}
                          for i in sorted(disagreeing, key=lambda x: x.file_id)],
        "acknowledged_disagreements": sorted(i.file_id for i in disagreeing if i.file_id in acknowledged),
        "unresolved_disagreements": sorted(i.file_id for i in disagreeing if i.file_id not in acknowledged),
        "needs_review": needs_review(images),
        "row_changing_images": dict(row_changes) if row_changes is not None else {"source": None, "images": {}},
        "per_field": dict(sorted(per_field.items())),
        "image_flags": dict(sorted(Counter(f for i in images for f in i.flags).items())),
        "resource_ids": {
            "total": len(rids),
            "mapped": sum(1 for _, r in rids if r.mapped),
            "unmapped": len(unmapped),
            "unmapped_no_system": sum(1 for _, r in rids if not r.mapped and r.system_id is None),
            "named_elsewhere": sum(1 for _, r in rids if r.named_elsewhere),
            "named_nowhere_else": sum(1 for _, r in rids if not r.named_elsewhere),
            "unmapped_labels": unmapped,
            "flagged": flagged,
        },
    }


def row_key(r: OutputRow) -> tuple[str, str]:
    """A comparable form of an output row: status plus canonical steps (raw text if unparsed)."""
    steps = json.dumps(r.steps, sort_keys=True) if r.steps is not None else "<unparsed>" + r.raw_steps
    return r.status, steps


def rows_differ(a: OutputFile, b: OutputFile) -> dict[str, Any]:
    """Case IDs whose rows differ between two outputs, and those present in only one."""
    both = sorted(set(a.rows) & set(b.rows))
    return {"cases_compared": len(both),
            "differ": [c for c in both if row_key(a.rows[c]) != row_key(b.rows[c])],
            "only_first": sorted(set(a.rows) - set(b.rows)), "only_second": sorted(set(b.rows) - set(a.rows))}


def fixture_result(output: OutputFile, expected: OutputFile) -> dict[str, Any]:
    """Row-exact passes of a fixture run against the fixture's ``expected_output.csv``."""
    bad = [c for c, r in expected.rows.items() if r.steps is None] + expected.issues
    if bad:
        raise ValueError(f"expected_output.csv is unreadable: {len(bad)} problem(s)")
    passed = [c for c in sorted(expected.rows)
              if score_case(output.rows.get(c), GoldCase(c, expected.rows[c].status,
                                                         list(expected.rows[c].steps or [])))["row_exact"]]
    return {"expected_rows": len(expected.rows), "rows_passed": len(passed),
            "failed": sorted(set(expected.rows) - set(passed)),
            "extra_rows": len(set(output.rows) - set(expected.rows)),
            "fixture_passed": len(passed) == len(expected.rows) and bool(expected.rows)}


# ---- Building the report ----
MEASURED = {
    "n_tools": f"{CASES_FILE} {AGENT_KEY}.audit_case_calls > 0 (audit_case rate) and {AGENT_KEY}.tool_calls "
               "names in READ_ONLY_TOOLS (other read-only tools; audit_case excluded by contract), one count per "
               "case record, over the run's cases",
    "m_answers": f"{CASES_FILE} {AGENT_KEY}.steps_differ_when_applied (each case compiled with validated answers "
                 f"applied and withheld) and {AGENT_KEY}.answers_rejected[].reason",
    "intent": f"{CASES_FILE} {AGENT_KEY}.intent.label (null = FAILED) x intent.crosscheck.intake_non_deletion; "
              "agrees as recorded; committed_label vs final_label equality (T92; the keys are provenance); "
              "turn1_replicates all equal",
    "vision": f"{VISION_ARTIFACT} items (checked against {VISION_READINGS_FILE}): status FAILED counted with its "
              "failure flag codes and null readings; for OK images the two reading reports compared again by the "
              "writer's rule (records by shown ID, subject hashes, merged states) and the listed disagreement paths "
              "checked against it; resource_ids by basis (mapped: shape or catalog display name) and named_by; "
              f"acknowledged = {PRODUCER_FILE} vision.review.acknowledged names the file_id and both reading keys "
              f"(T112 4(a)); row-changing images = {GATE_FILE} rows whose cause is image or intent+image",
    "dev_score": f"evaluation.scorer.score_predictions on runs/<id>/{OUTPUT_FILE} against DEV gold "
                 "(evaluation.gold.load_gold defaults: DEV only)",
    "fixtures": f"row exact (status and parsed steps) of runs/<id>/{OUTPUT_FILE} against "
                "code/tests/fixtures/<name>/expected_output.csv",
    "test_rows_differ": f"status and parsed steps of runs/<id>/{OUTPUT_FILE}, compared per case ID",
    "cost": f"runs/<id>/{USAGE_FILE} fields {', '.join(USAGE_KEYS)}, summed per arm",
}


@dataclass
class Spec:
    """Which run feeds which arm and role."""

    dev: dict[str, str] = field(default_factory=dict)
    test: dict[str, str] = field(default_factory=dict)
    fixtures: dict[str, dict[str, str]] = field(default_factory=dict)

    def run_ids(self) -> list[str]:
        """Every input run ID, in a stable order, without repeats."""
        ids = [*self.dev.values(), *self.test.values(), *(r for m in self.fixtures.values() for r in m.values())]
        return list(dict.fromkeys(ids))

    def validate(self, fixtures_root: Path) -> None:
        """Arms must be known, run IDs well-formed, fixture names existing folders."""
        for arm in [*self.dev, *self.test, *self.fixtures]:
            if arm not in MODES:
                raise ValueError(f"unknown arm {arm!r}: must be one of {list(MODES)}")
        for rid in self.run_ids():
            runs.check_run_id(rid)
        for m in self.fixtures.values():
            for name in m:
                if not _safe(name) or not (fixtures_root / name / "expected_output.csv").is_file():
                    raise ValueError(f"unknown fixture {name!r} under {fixtures_root}")


def _agent_section(run: LoadedRun, role: str, allowed_ids: frozenset[str], arm: str) -> dict[str, Any]:
    """The per-run agent sections, or one error block that replaces all their counts."""
    v = run.view
    errors = list(v.record_errors) + list(v.agent_errors)
    outside = sorted(c for c in v.cases if c not in allowed_ids)
    errors += [AdapterError(c, RECORD_KEYS["case_id"], f"case is not in the {role} set") for c in outside]
    errors += [AdapterError(c.case_id, f"{AGENT_KEY}.{AGENT_KEYS['mode']}", f"mode does not match the arm {arm}")
               for c in v.cases.values() if c.agent is not None and c.agent.mode != arm]
    if run.output is not None and set(run.output.rows) != set(v.cases):
        errors.append(AdapterError(CASES_FILE, RECORD_KEYS["case_id"],
                                   f"case set differs from {OUTPUT_FILE} ({len(v.cases)} vs {len(run.output.rows)})"))
    base = {"run_id": run.run_id}
    if errors:
        err = {**base, "error": f"{len(errors)} adapter error(s): counts not computed",
               "errors": summarize_errors(errors)}
        agent_part: dict[str, Any] = {"n_tools": err, "m_answers": err, "intent": err}
    else:
        ids = sorted(v.cases)
        agents = [v.cases[c].agent for c in ids]
        assert all(a is not None for a in agents)
        av = [a for a in agents if a is not None]
        agent_part = {"n_tools": {**base, "measured": MEASURED["n_tools"], **count_tools(av)},
                      "m_answers": {**base, "measured": MEASURED["m_answers"], **count_answers(av, ids)},
                      "intent": {**base, "measured": MEASURED["intent"], **intent_table([v.cases[c] for c in ids])}}
    verrs = list(v.vision_errors)
    acked: frozenset[str] = frozenset()
    changes: dict[str, Any] = {}
    if v.vision is not None and not verrs:
        acked, aerr = acknowledged_images(run.producer, v.vision)
        changes, cerr = row_changing_images(run.run_dir)
        verrs += [AdapterError(PRODUCER_FILE if e.startswith(PRODUCER_FILE) else GATE_FILE, "<record>", e)
                  for e in [*aerr, *cerr]]
    if verrs or v.vision is None:
        agent_part["vision"] = {**base, "error": f"{len(verrs)} adapter error(s): counts not computed",
                                "errors": summarize_errors(verrs)}
    else:
        agent_part["vision"] = {**base, "measured": MEASURED["vision"], **vision_summary(v.vision, acked, changes)}
    return agent_part


def _rate_cell(x: Mapping[str, Any]) -> dict[str, Any]:
    return {"n": x["n"], "of": x["of"]}


def dev_score(run: LoadedRun, gold: Mapping[str, GoldCase]) -> dict[str, Any]:
    """DEV status, row exact and step F1 of one run, from the existing scorer."""
    assert run.output is not None
    p = score_predictions(run.output.rows, gold)["aggregate"]["published"]
    return {"run_id": run.run_id, "measured": MEASURED["dev_score"], "status": _rate_cell(p["status_accuracy"]),
            "row_exact": _rate_cell(p["row_exact"]),
            "step": {k: p["step"][k] for k in ("tp", "pred", "gold", "precision", "recall", "f1")}}


def _deltas(scores: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if "tools_off" not in scores:
        return {}
    off = scores["tools_off"]
    out = {}
    for arm, s in scores.items():
        if arm == "tools_off":
            continue
        f1, f1_off = s["step"]["f1"], off["step"]["f1"]
        out[f"{arm} - tools_off"] = {
            "runs": [s["run_id"], off["run_id"]],
            "status_n": s["status"]["n"] - off["status"]["n"],
            "row_exact_n": s["row_exact"]["n"] - off["row_exact"]["n"],
            "step_f1": None if f1 is None or f1_off is None else f1 - f1_off,
        }
    return out


def _cost(spec: Spec, loaded: Mapping[str, LoadedRun]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in MODES:
        ids = [r for r in (spec.dev.get(arm), spec.test.get(arm), *spec.fixtures.get(arm, {}).values()) if r]
        if not ids:
            continue
        ids = list(dict.fromkeys(ids))
        per_run = {r: (loaded[r].usage or {"error": loaded[r].usage_errors}) for r in ids}
        bad = [r for r in ids if loaded[r].usage is None]
        total: dict[str, Any] = {"error": f"usage unreadable in {bad}"} if bad else {
            **{k: sum(per_run[r][k] for r in ids) for k in USAGE_KEYS if k != "model_ids"},
            "model_ids": sorted({m for r in ids for m in per_run[r]["model_ids"]})}
        out[arm] = {"measured": MEASURED["cost"], "runs": per_run, "total": total}
    return out


def build_report(spec: Spec, *, report_id: str, runs_root: Path = RUNS, gold_path: Path = SAMPLE_OUTPUT,
                 test_ids: frozenset[str] | None = None, fixtures_root: Path = FIXTURES_ROOT,
                 command: str = "") -> dict[str, Any]:
    """Build the report dict from run artifacts. Raises :class:`ReportRefused` on an unchecked run."""
    runs.check_run_id(report_id)
    spec.validate(fixtures_root)
    loaded = {r: load_run(runs_root, r) for r in spec.run_ids()}
    unchecked = [f"{r}: producer check {lr.producer_check['status']}: " + "; ".join(lr.producer_check["reasons"])
                 for r, lr in loaded.items() if lr.producer_check["status"] != "ok"]
    if unchecked:
        raise ReportRefused(unchecked)
    if spec.test and test_ids is None:
        test_ids = frozenset(load_requests(TEST_REQUESTS))
    allowed = {"dev": DEV_IDS, "test": test_ids or frozenset()}
    report: dict[str, Any] = {
        "report_id": report_id, "kind": "agent_report", "created_at": runs.now_ist(), "command": command,
        "inputs": {"dev": spec.dev, "test": spec.test, "fixtures": spec.fixtures},
        "runs": {r: {"producer_check": lr.producer_check["status"], "output_sha256": lr.producer_check["pred_sha256"],
                     "producer_mode": shown(lr.producer.get("mode"))} for r, lr in loaded.items()},
    }
    for sec in ("n_tools", "m_answers", "intent", "vision"):
        report[sec] = {role: {} for role in ROLES}
    for role in ROLES:
        for arm, rid in getattr(spec, role).items():
            for sec, val in _agent_section(loaded[rid], role, allowed[role], arm).items():
                report[sec][role][arm] = val
    scores: dict[str, Any] = {}
    if spec.dev:
        gold = load_gold(gold_path)  # DEV only: the loader's defaults, never holdout
        scores = {arm: dev_score(loaded[rid], gold) for arm, rid in spec.dev.items()}
    fixtures = {}
    for arm, m in spec.fixtures.items():
        per = {}
        for name, rid in sorted(m.items()):
            out = loaded[rid].output
            assert out is not None
            expected = read_output(fixtures_root / name / "expected_output.csv")
            per[name] = {"run_id": rid, **fixture_result(out, expected)}
        fixtures[arm] = {"measured": MEASURED["fixtures"],
                         "fixtures_passed": sum(p["fixture_passed"] for p in per.values()),
                         "fixtures": len(per), "rows_passed": sum(p["rows_passed"] for p in per.values()),
                         "expected_rows": sum(p["expected_rows"] for p in per.values()), "per_fixture": per}
    differ = []
    arms = [a for a in MODES if a in spec.test]
    for i, a in enumerate(arms):
        for b in arms[i + 1:]:
            ra, rb = loaded[spec.test[a]], loaded[spec.test[b]]
            assert ra.output is not None and rb.output is not None
            differ.append({"arms": [a, b], "runs": [ra.run_id, rb.run_id], "measured": MEASURED["test_rows_differ"],
                           **rows_differ(ra.output, rb.output)})
    report["arm_deltas"] = {"dev": scores, "dev_delta_vs_tools_off": _deltas(scores), "fixtures": fixtures,
                            "test_rows_differ": differ}
    report["cost"] = _cost(spec, loaded)
    report["error_count"] = _error_count(report)
    return report


def _error_count(report: Mapping[str, Any]) -> int:
    n = sum(1 for sec in ("n_tools", "m_answers", "intent", "vision") for role in report[sec].values()
            for v in role.values() if "error" in v)
    return n + sum(1 for arm in report["cost"].values() if "error" in arm["total"])


# ---- Markdown ----
def _r(x: Mapping[str, Any]) -> str:
    return f"{x['n']}/{x['of']}"


def _f(v: Any) -> str:
    return "n/a" if v is None else f"{v:.4f}"


def _md_error(lines: list[str], v: Mapping[str, Any]) -> None:
    lines.append(f"- **ERROR** (run `{v['run_id']}`): {v['error']}")
    for e in v["errors"]:
        lines.append(f"  - `{e['path']}`: {e['problem']} ({e['count']}; e.g. {', '.join(e['where'])})")


def _md_role_section(lines: list[str], title: str, sec: Mapping[str, Any], body: Any) -> None:
    lines += [f"## {title}", ""]
    for role in ROLES:
        for arm, v in sec[role].items():
            lines.append(f"### {role} / {arm} (run `{v['run_id']}`)")
            if "error" in v:
                _md_error(lines, v)
            else:
                lines.append(f"Measured: {v['measured']}.")
                body(lines, v)
            lines.append("")


def rate_text(n: int, of: int) -> str:
    """``n/of (rate)``, or ``n/0`` with no rate when there are no cases."""
    return f"{n}/{of} ({n / of:.4f})" if of else f"{n}/0"


def _md_tools(lines: list[str], v: Mapping[str, Any]) -> None:
    rid, of = v["run_id"], v["cases"]
    lines += [f"- Tool-use rate, audit_case: {rate_text(v['audit_case']['cases_with_call'], of)} cases called "
              f"{AUDIT_CASE_TOOL} ({v['audit_case']['calls']} calls); run `{rid}`.",
              f"- Tool-use rate, other read-only tools ({', '.join(READ_ONLY_TOOLS)}): "
              f"{rate_text(v['cases_with_read_only_tool'], of)} cases ({v['tool_calls']} calls other than "
              f"{AUDIT_CASE_TOOL}); run `{rid}`.",
              f"- Cases with a tool name outside both sets: {v['cases_with_unknown_tool']}. Agent status: "
              f"{v['agent_status']}."]
    lines += ["", "| tool | cases | calls | error calls |", "|---|---|---|---|"]
    lines += [f"| {t} | {c['cases']} | {c['calls']} | {c['error_calls']} |" for t, c in v["per_tool"].items()]
    lines += ["", "| tool sequence | cases |", "|---|---|"]
    lines += [f"| {s} | {n} |" for s, n in v["sequence_histogram"].items()]


def _md_answers(lines: list[str], v: Mapping[str, Any]) -> None:
    lines.append(f"- M = {v['cases_steps_differ']} of {v['cases']} cases whose steps differ with answers applied vs "
                 f"withheld: {v['steps_differ_case_ids'] or 'none'}.")
    lines.append(f"- Answers applied: {v['answers_applied']} in {v['cases_with_answer_applied']} cases. "
                 f"Rejected: {v['answers_rejected']}, by reason {v['rejected_by_reason'] or '{}'}.")


def _md_intent(lines: list[str], v: Mapping[str, Any]) -> None:
    lines += ["| model label | intake row present | intake row absent |", "|---|---|---|"]
    lines += [f"| {lab} | {c['intake_row_present']} | {c['intake_row_absent']} |" for lab, c in v["table"].items()]
    rep = v["turn1_replicates"]
    lines += ["", f"- agrees: {v['agrees']}; sources: {v['sources']}.",
              f"- committed vs final intent label: {v['committed_vs_final_label']}; INTENT_DRIFT flagged: "
              f"{v['intent_drift_flagged_cases']}.",
              f"- turn-1 replicates: all agree {rep.get('all_agree', 0)}, disagree {rep.get('disagree', 0)}, "
              f"fewer than 2 {rep.get('fewer_than_2', 0)}; disagreeing cases: {rep['disagree_case_ids'] or 'none'}."]


def _md_vision(lines: list[str], v: Mapping[str, Any]) -> None:
    rid = v["resource_ids"]
    lines += [f"- Images {v['images']}: read {v['images_read']}, failed {v['images_failed']}. Of those read, "
              f"readings agree {v['images_agree']}, disagree {v['images_disagree']} "
              f"({v['disagreeing_file_ids'] or 'none'}; {v['disagreement_paths']} field path(s)). "
              f"Acknowledged (T112 4(a)): {v['acknowledged_disagreements'] or 'none'}; unresolved: "
              f"{v['unresolved_disagreements'] or 'none'}. Needs review: {v['needs_review'] or 'none'}. "
              f"Image flags: {v['image_flags'] or '{}'}.",
              "- Images whose reading changed a row (T112 4(b)): "
              + (f"{v['row_changing_images']['images'] or 'none'} (from {v['row_changing_images']['source']})"
                 if v["row_changing_images"]["source"] else "not recorded (the run has no regression gate report)")
              + ".",
              f"- Labels {rid['total']}: mapped to a resource ID {rid['mapped']}, unmapped {rid['unmapped']} "
              f"(no system {rid['unmapped_no_system']}); named elsewhere {rid['named_elsewhere']}, nowhere else "
              f"{rid['named_nowhere_else']}."]
    if v["failed"]:
        lines += ["", "| failed image | reason | failed readings |", "|---|---|---|"]
        lines += [f"| {x['file_id']} | {', '.join(x['reasons'])} | "
                  f"{', '.join(map(str, x['failed_readings'])) or 'not attempted'} |" for x in v["failed"]]
    if v["disagreements"]:
        lines += ["", "| disagreeing image | field paths |", "|---|---|"]
        lines += [f"| {x['file_id']} | {', '.join(f'`{p}`' for p in x['paths'])} |" for x in v["disagreements"]]
    lines += ["", "| field | images read | readings agree |", "|---|---|---|"]
    lines += [f"| {k} | {c['images']} | {c['agree']} |" for k, c in v["per_field"].items()]
    if rid["unmapped_labels"]:
        lines += ["", "| file | unmapped label | basis | system |", "|---|---|---|---|"]
        lines += [f"| {x['file_id']} | {x['label']} | {x['basis']} | {x['system_id'] or 'none'} |"
                  for x in rid["unmapped_labels"]]
    if rid["flagged"]:
        lines += ["", "| file | system | resource | flagged because |", "|---|---|---|---|"]
        lines += [f"| {x['file_id']} | {x['system_id']} | {x['resource_id']} | {', '.join(x['reasons'])} |"
                  for x in rid["flagged"]]


def render_markdown(report: Mapping[str, Any]) -> str:
    """The Markdown form of the report, rendered from the report dict only."""
    lines = [f"# Agent report `{report['report_id']}`", "",
             f"Generated {report['created_at']} by `{report['command'] or 'agent_report.build_report'}` from run "
             "artifacts only (code/evaluation/agent_report.py). Every number names its run.", "",
             "| run | producer check | output sha256 | producer mode |", "|---|---|---|---|"]
    lines += [f"| `{r}` | {v['producer_check']} | {str(v['output_sha256'])[:16]}... | {v['producer_mode']} |"
              for r, v in report["runs"].items()]
    lines += ["", f"Sections with errors: {report['error_count']}.", ""]
    _md_role_section(lines, "1. N: tool use", report["n_tools"], _md_tools)
    _md_role_section(lines, "2. M: answers that changed steps", report["m_answers"], _md_answers)
    ad = report["arm_deltas"]
    lines += ["## 3. Arm deltas", "", f"DEV, measured: {MEASURED['dev_score']}.", "",
              "| arm | run | status | row exact | step P | step R | step F1 |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {a} | `{s['run_id']}` | {_r(s['status'])} | {_r(s['row_exact'])} | {_f(s['step']['precision'])} | "
              f"{_f(s['step']['recall'])} | {_f(s['step']['f1'])} |" for a, s in ad["dev"].items()]
    for k, d in ad["dev_delta_vs_tools_off"].items():
        lines.append(f"- {k} (runs `{d['runs'][0]}` vs `{d['runs'][1]}`): status {d['status_n']:+d}, row exact "
                     f"{d['row_exact_n']:+d}, step F1 {'n/a' if d['step_f1'] is None else f'{d['step_f1']:+.4f}'}.")
    for arm, fx in ad["fixtures"].items():
        lines += ["", f"Fixtures, {arm}, measured: {fx['measured']}: {fx['fixtures_passed']}/{fx['fixtures']} "
                  f"fixtures, {fx['rows_passed']}/{fx['expected_rows']} rows."]
        lines += [f"- {n} (run `{p['run_id']}`): {p['rows_passed']}/{p['expected_rows']} rows; failed "
                  f"{p['failed'] or 'none'}; extra rows {p['extra_rows']}" for n, p in fx["per_fixture"].items()]
    for d in ad["test_rows_differ"]:
        lines += ["", f"Test rows, {d['arms'][0]} (`{d['runs'][0]}`) vs {d['arms'][1]} (`{d['runs'][1]}`): "
                  f"{len(d['differ'])} of {d['cases_compared']} differ: {d['differ'] or 'none'}; only in the first "
                  f"{d['only_first'] or 'none'}; only in the second {d['only_second'] or 'none'}."]
    lines.append("")
    _md_role_section(lines, "4. Intent agreement", report["intent"], _md_intent)
    _md_role_section(lines, "5. Vision agreement", report["vision"], _md_vision)
    lines += ["## 6. Cost per arm", ""]
    for arm, c in report["cost"].items():
        lines.append(f"- {arm}, measured: {c['measured']}: total {c['total']}; per run {c['runs']}.")
    return "\n".join(lines) + "\n"


# ---- CLI ----
def _parse_pair(s: str) -> tuple[str, str]:
    key, sep, val = s.rpartition("=")
    if not sep or not key or not val:
        raise argparse.ArgumentTypeError(f"expected KEY=RUN_ID, got {s!r}")
    return key, val


def spec_from_args(a: argparse.Namespace) -> Spec:
    """Merge ``--spec`` and the ``--dev``/``--test``/``--fixture`` flags into one :class:`Spec`."""
    spec = Spec()
    if a.spec:
        raw = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        spec = Spec(dict(raw.get("dev", {})), dict(raw.get("test", {})),
                    {k: dict(v) for k, v in raw.get("fixtures", {}).items()})
    spec.dev.update(dict(a.dev))
    spec.test.update(dict(a.test))
    for key, rid in a.fixture:
        arm, sep, name = key.partition(":")
        if not sep:
            raise ValueError(f"--fixture expects ARM:FIXTURE=RUN_ID, got {key!r}")
        spec.fixtures.setdefault(arm, {})[name] = rid
    return spec


def main(argv: list[str] | None = None) -> int:
    """Build and write the report. Exit 0 clean, 2 with adapter errors, 3 refused (unchecked run)."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True, help="the report's own run ID (runs/<id>/agent_report.*)")
    ap.add_argument("--dev", type=_parse_pair, action="append", default=[], metavar="ARM=RUN_ID")
    ap.add_argument("--test", type=_parse_pair, action="append", default=[], metavar="ARM=RUN_ID")
    ap.add_argument("--fixture", type=_parse_pair, action="append", default=[], metavar="ARM:FIXTURE=RUN_ID")
    ap.add_argument("--spec", help="JSON spec file (module docstring)")
    a = ap.parse_args(argv)
    spec = spec_from_args(a)
    out_dir = run_path(RUNS, a.run_id)
    if (out_dir / OUTPUT_FILE).exists() or a.run_id in spec.run_ids():
        print(f"refused: {a.run_id} names an input or producer run; give the report its own run ID", file=sys.stderr)
        return 3
    command = "python3 -B code/evaluation/agent_report.py " + " ".join(
        shlex.quote(x) for x in (argv if argv is not None else sys.argv[1:]))
    try:
        report = build_report(spec, report_id=a.run_id, runs_root=RUNS, command=command)
    except ReportRefused as exc:
        out_dir.mkdir(parents=True, exist_ok=True)
        runs.write_json(out_dir / "refused.json", {"run_id": a.run_id, "kind": "agent-report-refused",
                                                   "created_at": runs.now_ist(), "command": command,
                                                   "reasons": exc.reasons})
        print("agent report refused: unchecked input run(s) never feed a report (T60, T81):", file=sys.stderr)
        for r in exc.reasons:
            print(f"  {r}", file=sys.stderr)
        return 3
    out_dir.mkdir(parents=True, exist_ok=True)
    runs.write_json(out_dir / "agent_report.json", report)
    md = render_markdown(report)
    (out_dir / "agent_report.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"wrote {out_dir / 'agent_report.json'} and agent_report.md; sections with errors: {report['error_count']}")
    return 2 if report["error_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
