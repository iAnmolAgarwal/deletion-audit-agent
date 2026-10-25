"""The deterministic auditor: inputs -> one :class:`~deletion_audit.record.CaseRecord` per case.

T-numbers refer to the developer's rulings in code/docs/DECISIONS.md.

Stages: parse the evidence -> resolve each request's identity -> link records to people -> assign
primary accounts (one global pass over both request files) -> attach identifier-free analytics
records (global) -> per case: each record's state at ``audit_at``, its category and decision, the
citation, the steps -> pre-write validation.

The engine settles every fact. The model (``agent/``, wired in ``pipeline.run``) supplies the
request intent and the screenshot readings, and may answer typed open questions. A case with no
validated model intent takes the deletion path and is flagged, because an unread request must not
become NOT_APPLICABLE (T71 Q2 in code/docs/DECISIONS.md).

Fail-closed rules. A FAILED_CLOSED row is INCOMPLETE and keeps the steps the other inputs still
give; it is never COMPLETE. Each rule, then its reason:

* **An evidence file that did not parse is never read as "nothing found".** A file that failed
  for a structural reason (``ERROR``, ``EMPTY``, an unknown or ambiguous family, a non-PNG that
  needs a model) could concern anyone, so every case whose ``audit_at`` is at or after its capture
  time depends on it. A PNG still waiting for the vision step is a dependency only of a case with a
  record known solely through a catalog row and with no parsed state. The reason names the kind:
  MISSING_EVIDENCE_FILE, EVIDENCE_PARSE_ERROR, UNKNOWN_EVIDENCE_FAMILY, else UNPARSED_DEPENDENCY,
  with one FAILED_DEPENDENCY flag per file. Reason: an unread file may hold the very record the
  audit must report (T8, T86 item 1 and T105 in code/docs/DECISIONS.md).
* **A screenshot the vision step read is not unread.** A PNG in ``AuditContext.vision_read`` (both
  of its readings succeeded, so its records are in ``image_observations``) is neither pending nor
  a dependency. A PNG whose reading failed, or that was never read, stays a dependency as above.
* **A request row that could not be loaded** gives a FAILED_CLOSED row with no step when its case
  ID is readable, because nothing else in the row can be trusted (T86 item 2).
* **An unresolved identity** is searched by the raw request email and its hash only, and a
  deletion request's row is FAILED_CLOSED(IDENTITY_UNRESOLVED). A request the model reads as
  NOT_DELETION is NOT_APPLICABLE whatever the identity, since nothing is to be deleted (T63).
* **A record whose own keys name another known person** fails the row closed as
  OWN_KEY_CONFLICT, because deleting it could delete someone else's data (T105).
* **A FINDING held only by files captured after ``audit_at``** fails the row closed as
  POST_AUDIT_ONLY_FINDING: no citable file both contains it and was captured at or before
  ``audit_at``, so no valid step can be written for it (T101).
* **A state that no rule covers** is NO_CATEGORY_RULE, never a silently dropped record, because a
  dropped record could let a COMPLETE row hide it (T104 (a)). A legal-hold entry that names no
  resource is not a record here (records are keyed by resource ID), so it still gives no step (T69).
* **A record that waited on a screenshot** is IMAGE_OMITS_CATALOG_RECORD when the images were read
  and none mentions it, and IMAGE_STATE_NOT_SHOWN when a reading shows it with no visible state.
  An omission elsewhere never stands in for the screenshot the record waited on (T108, T112).
* **A record with evidence at or before ``audit_at`` from which no step follows** is
  UNINTERPRETED_RECORD, because evidence the engine cannot read is no proof of absence. A record
  with no observation at all still gets no step; only an account with no observation is read as
  absent by default.
* **A case with no FINDING or COMPLIANT record** is NOTHING_FOUND.

Two flags without a fail-closed reason: an image whose subject is not the person a catalog row
names keeps the record in scope and raises IMAGE_SUBJECT_CONFLICT (the catalog link wins, T71
Q11); a retained record whose state is not PRESENT keeps VERIFY_RECORD_PRESENT and raises
PRESENT_CLAIM_OVER_STATE (DEV sample answers do the same on 9 audit records, T104 (b)).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from . import timeutil
from .config import EngineConfig
from .discovery.accounts import AccountAssignment, Flag, assign_primary_accounts
from .discovery.analytics import AnalyticsClaim, attach_identifier_free_analytics
from .discovery.catalog import AliasEvidence, CatalogLink, alias_evidence, catalog_links
from .discovery.links import Link, LinkBasis, LinkIndex, Window, build_link_index, is_own_key, link_observations
from .discovery.obstime import at_or_before, in_window, observation_time
from .evidence import parse_all
from .evidence.interpret import system_from_prefix
from .evidence.manifest import load_manifest
from .evidence.model import EvidenceIndex, FileRef, Observation
from .identity.resolve import IdentifierSet, IdentityResolution, PeopleIndex, build_people, resolve_with
from .inputs import load_activity, load_audit_log, load_identities
from .inputs.model import ActivityRow, AuditLogRow, IdentityRow
from .inputs.requests import DeletionRequest, RequestIssue, load_requests_checked
from .policy.rules import RuleTable, attachment_documents, categorize, decide, load_rules, violating_states
from .record import CaseRecord, CrossCheck, FailedClosedReason, IntentDecision, ResourceFinding, fail_closed_intent
from .state.observe import observation_state
from .state.reconstruct import (
    ResourceKey,
    ScopeListing,
    StateObservation,
    is_replica_copy,
    omission_readings,
    record_readings,
    scope_listings,
    state_at,
)
from .steps.citation import choose_citation, finding_citation
from .steps.compile import compile_steps
from .steps.model import CitationPlan
from .validate.prewrite import ValidationContext, gate

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
OpenQuestionType = Literal[
    "INTENT_UNCERTAIN",
    "INTENT_CROSSCHECK",
    "IMAGE_FIELD_UNREADABLE",
    "IMAGE_SUBJECT_CONFLICT",
    "UNKNOWN_FORMAT",
]
STAGE_BASIS = {
    "S1_IDENTIFIER": "identifier",
    "S2_TIMED": "timed_account",
    "T26_HAND_BUILT": "timed_account",
    "S3_ONE_TO_ONE": "timed_account",
    "S4_FINGERPRINT": "fingerprint",
    "S4B_ONE_TO_ONE": "fingerprint",
    "S5_TIE_PICK": "tie_pick",
    "T27_LATER_LOOKUP": "t27",
}


@dataclass(frozen=True)
class OpenQuestion:
    """A question code cannot settle; a model answer may fill only its ``slot`` (closed list)."""

    oq_id: str
    type: OpenQuestionType
    subject: str
    allowed_choices: tuple[str, ...]
    slot: str | None


@dataclass(frozen=True)
class EngineBrief:
    """What the engine settled for one case (read-only to any model), plus its open questions."""

    case_id: str
    settled: tuple[ResourceFinding, ...]
    citation: CitationPlan
    open_questions: tuple[OpenQuestion, ...]
    flags: tuple[Flag, ...]

    def for_model(self) -> str:
        """Compact JSON of IDs and states only, marked read-only (no cell text, no identifiers)."""
        body = {
            "read_only": True,
            "case_id": self.case_id,
            "cites": self.citation.file_id,
            "records": [
                {
                    "system_id": r.key.system_id,
                    "resource_id": r.key.resource_id,
                    "state": r.state.value,
                    "category": r.category.category,
                    "outcome": r.decision.outcome,
                }
                for r in self.settled
            ],
            "open_questions": [
                {"oq_id": q.oq_id, "type": q.type, "subject": q.subject, "allowed_choices": list(q.allowed_choices)}
                for q in self.open_questions
            ],
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class FileFailure:
    """A manifest file that did not parse to OK."""

    file_id: str
    status: str
    captured_at: str
    png: bool  # NEEDS_MODEL and the bytes start with the PNG signature (T72)
    missing: bool = False  # the manifest names a file that is not on disk (T86 item 1)


@dataclass
class AuditContext:
    """Every input, parsed once, and the global facts derived from them."""

    dataset_dir: Path
    requests: tuple[DeletionRequest, ...]
    index: EvidenceIndex
    manifest: tuple[FileRef, ...]
    activity: tuple[ActivityRow, ...]
    identities: tuple[IdentityRow, ...]
    audit_log: tuple[AuditLogRow, ...]
    rules: RuleTable
    config: EngineConfig = field(default_factory=EngineConfig)
    image_observations: tuple[Observation, ...] = ()
    request_issues: tuple[RequestIssue, ...] = ()
    vision_read: frozenset[str] = frozenset()  # PNG file IDs whose two vision readings both succeeded


def build_context(
    dataset_dir: Path, *, config: EngineConfig | None = None, image_observations: Sequence[Observation] = ()
) -> AuditContext:
    """Load and parse every input once."""
    d = Path(dataset_dir)
    requests, issues = load_requests_checked(d)
    return AuditContext(
        dataset_dir=d,
        requests=requests,
        request_issues=issues,
        index=parse_all(d),
        manifest=load_manifest(d),
        activity=load_activity(d),
        identities=load_identities(d),
        audit_log=load_audit_log(d),
        rules=load_rules(d),
        config=config or EngineConfig(),
        image_observations=tuple(image_observations),
    )


@dataclass
class World:
    """Global facts computed once over all requests."""

    ctx: AuditContext
    people: PeopleIndex
    catalog: tuple[CatalogLink, ...]
    aliases: tuple[AliasEvidence, ...]
    links: LinkIndex
    resolutions: dict[str, IdentityResolution]
    case_links: dict[str, tuple[Link, ...]]
    assignments: Mapping[str, AccountAssignment]
    analytics: Mapping[str, tuple[AnalyticsClaim, ...]]
    obs_by_resource: dict[str, list[Observation]]
    activity_by_resource: dict[str, list[ActivityRow]]
    file_captured: dict[str, str]
    manifest_pos: dict[str, int]
    listings: tuple[ScopeListing, ...]
    account_files: frozenset[str]
    failures: tuple[FileFailure, ...]
    image_conflicts: dict[str, tuple[str, ...]]  # resource -> image file_ids whose subject differs
    validation: ValidationContext
    attachment_documents: frozenset[str]


def dataset_path(dataset_dir: Path, relative: str) -> Path | None:
    """The manifest path inside ``dataset_dir``, or None when it resolves outside it.

    This is the containment check the evidence parser applies before it reads a file: a manifest
    path is untrusted input, so the engine never opens or tests a file outside the dataset either.
    """
    root = Path(dataset_dir).resolve()
    path = (root / relative).resolve()
    return path if root in path.parents else None


def _starts_with_png_signature(path: Path | None) -> bool:
    """Whether the file at ``path`` begins with the PNG signature (False when unreadable or None)."""
    if path is None:
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
    except OSError:
        return False


def _failures(ctx: AuditContext, file_captured: Mapping[str, str]) -> tuple[FileFailure, ...]:
    """Manifest files that did not parse to OK, minus the PNGs the vision step read (module docstring).

    A file is ``missing`` when it failed with ``ERROR`` and its path, inside the dataset, is not a
    file. A path outside the dataset is never tested on disk, so it is not ``missing``: it keeps the
    parser's ``ERROR`` and is an EVIDENCE_PARSE_ERROR dependency.
    """
    out = []
    for ref in ctx.manifest:
        fp = ctx.index.files.get(ref.file_id)
        if fp is None or fp.ok:
            continue
        path = dataset_path(ctx.dataset_dir, ref.path)
        png = fp.status == "NEEDS_MODEL" and _starts_with_png_signature(path)
        if png and ref.file_id in ctx.vision_read:
            continue  # read by the vision step: its records are image observations, not a pending file
        missing = fp.status == "ERROR" and path is not None and not path.is_file()
        out.append(FileFailure(ref.file_id, fp.status, file_captured[ref.file_id], png, missing))
    return tuple(out)


def _unresolved_links(
    ident: IdentityResolution, ctx: AuditContext, window: Window, own_keyed: frozenset[str] = frozenset()
) -> tuple[Link, ...]:
    """T63: links of an unresolved request by its raw email and hash only (exact, own key first).

    T105, per record: a record that carries an own linkable key in any observation never links an
    unresolved request by a trace lookup (its own key did not match the raw email, so it names
    someone else or no one)."""
    ids: IdentifierSet = ident.identifiers
    out = []
    for o in list(ctx.index.observations()) + list(ctx.image_observations):
        own = [i for i in o.record_identifiers if is_own_key(i)]
        hit = next((i for i in o.record_identifiers if ids.matches(i)), None)
        basis: LinkBasis = "record_identifier"
        if hit is None and not own and o.resource_id and o.resource_id not in own_keyed:
            hit = next((i for i in o.lookup_identifiers if ids.matches(i)), None)
            basis = "trace_lookup"
        if hit is None:
            continue
        t = observation_time(o)
        out.append(
            Link(
                o,
                basis,
                hit,
                in_window(t, window.requested_at, window.audit_at),
                timeutil.le(o.captured_at, window.audit_at),
                o.resource_id,
                o.system_id,
                t,
            )
        )
    return tuple(out)


def _image_conflicts(
    ctx: AuditContext, catalog: Sequence[CatalogLink], people: PeopleIndex, names: Mapping[str, frozenset[str]]
) -> dict[str, tuple[str, ...]]:
    """T71 Q11: image records whose visible subject is not the person the catalog row names."""
    owners: dict[str, set[str]] = defaultdict(set)
    for c in catalog:
        owners[c.resource_id] |= set(c.persons)
    out: dict[str, set[str]] = defaultdict(set)
    for o in ctx.image_observations:
        if not o.resource_id or not owners.get(o.resource_id):
            continue
        subject = [i for i in o.record_identifiers if i.kind in ("email", "phone", "email_hash", "user_id", "name")]
        if not subject:
            continue
        mine = False
        for p in owners[o.resource_id]:
            ids = people.people.get(p)
            if any(
                (ids is not None and ids.matches(i)) or (i.kind == "name" and i.value in names.get(p, frozenset()))
                for i in subject
            ):
                mine = True
        if not mine:
            out[o.resource_id].add(o.file_id)
    return {k: tuple(sorted(v)) for k, v in out.items()}


def build_world(ctx: AuditContext) -> World:
    """Compute the global facts (identity, links, accounts, analytics, validation context)."""
    people = build_people(ctx.identities, ctx.audit_log)
    names: dict[str, set[str]] = defaultdict(set)
    for row in ctx.identities:
        if row.name:
            names[row.user_id].add(" ".join(row.name.split()).lower())
    catalog = catalog_links(ctx.activity, people)
    aliases = alias_evidence(catalog, ctx.index)
    conflicts = _image_conflicts(ctx, catalog, people, {k: frozenset(v) for k, v in names.items()})
    extra = tuple(o for o in ctx.image_observations if o.resource_id not in conflicts)
    lindex = build_link_index(ctx.index, people, catalog, extra=extra)
    resolutions = {r.case_id: resolve_with(r, people) for r in ctx.requests}
    case_links: dict[str, tuple[Link, ...]] = {}
    for r in ctx.requests:
        window = Window(r.requested_at, r.audit_at)
        ident = resolutions[r.case_id]
        case_links[r.case_id] = (
            link_observations(ident, lindex, window, aliases)
            if ident.person
            else _unresolved_links(ident, ctx, window, lindex.own_keyed)
        )
    owners = dict(lindex.resource_persons)
    assignments = assign_primary_accounts(
        ctx.requests, resolutions, ctx.activity, case_links, ctx.config.accounts, owners=owners
    )
    analytics = attach_identifier_free_analytics(
        assignments, ctx.requests, resolutions, ctx.activity, ctx.index, owners=owners, extra=ctx.image_observations
    )
    obs_by_resource: dict[str, list[Observation]] = defaultdict(list)
    for o in list(ctx.index.observations()) + list(ctx.image_observations):
        if o.resource_id:
            obs_by_resource[o.resource_id].append(o)
    act_by_res: dict[str, list[ActivityRow]] = defaultdict(list)
    for a in ctx.activity:
        if a.resource_id:
            act_by_res[a.resource_id].append(a)
    file_captured = {ref.file_id: ref.captured_at for ref in ctx.manifest}
    manifest_pos = {ref.file_id: i for i, ref in enumerate(ctx.manifest)}
    account_files = frozenset(o.file_id for o in ctx.index.observations() if o.system_id == "account_service")
    validation = build_validation_context(ctx, catalog, aliases, file_captured, own_persons=lindex.own_persons)
    return World(
        ctx,
        people,
        catalog,
        aliases,
        lindex,
        resolutions,
        case_links,
        assignments,
        analytics,
        obs_by_resource,
        act_by_res,
        file_captured,
        manifest_pos,
        scope_listings(ctx.index),
        account_files,
        _failures(ctx, file_captured),
        conflicts,
        validation,
        attachment_documents(ctx.index.observations()),
    )


def build_validation_context(
    ctx: AuditContext,
    catalog: Sequence[CatalogLink],
    aliases: Sequence[AliasEvidence],
    file_captured: Mapping[str, str],
    *,
    own_persons: Mapping[str, frozenset[str]] | None = None,
) -> ValidationContext:
    """The citable IDs with their times, what each file contains, declares and lists, and the
    persons each record's own keys name (T105's validator check)."""
    citable = dict(file_captured)
    citable.update({a.activity_id: a.event_time for a in ctx.activity})
    citable.update({a.audit_id: a.event_time for a in ctx.audit_log})
    res: dict[str, set[ResourceKey]] = defaultdict(set)
    listed: dict[str, set[str]] = defaultdict(set)
    for o in list(ctx.index.observations()) + list(ctx.image_observations):
        if o.resource_id:
            system = o.system_id or system_from_prefix(o.resource_id) or ""
            res[o.file_id].add(ResourceKey(system, o.resource_id))
            listed[o.file_id].add(system)
    scopes = {fid: frozenset(s for sc in fp.scopes for s in sc.systems) for fid, fp in ctx.index.files.items()}
    file_aliases: dict[str, set[str]] = defaultdict(set)
    res_aliases: dict[str, set[tuple[str, str]]] = defaultdict(set)
    alias_of = {c.activity_id: c.alias for c in catalog}
    for a in aliases:
        alias = alias_of.get(a.link_activity_id)
        if alias:
            file_aliases[a.file_id].add(alias)
            res_aliases[a.resource_id].add((alias, a.link_time))
    return ValidationContext(
        citable_time=citable,
        file_resources={k: frozenset(v) for k, v in res.items()},
        file_scope_systems=scopes,
        file_listed_systems={k: frozenset(v) for k, v in listed.items()},
        file_status={fid: fp.status for fid, fp in ctx.index.files.items()},
        file_aliases={k: frozenset(v) for k, v in file_aliases.items()},
        resource_aliases={k: tuple(sorted(v)) for k, v in res_aliases.items()},
        activity_resource={a.activity_id: a.resource_id for a in ctx.activity if a.resource_id},
        resource_own_persons=dict(own_persons or {}),
    )


def _resource_system(rid: str, w: World, hint: str | None) -> str:
    """The output ``system_id`` of a resource: the system its own evidence names most often, else
    the resource-type prefix, else the catalog/activity hint. The evidence wins over
    ``system_activity.target_system`` because it is what the system itself shows."""
    counts = Counter(o.system_id for o in w.obs_by_resource.get(rid, ()) if o.system_id)
    if counts:
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return system_from_prefix(rid) or hint or "unknown_system"


def crosscheck(req: DeletionRequest, w: World, account: str | None, links: Sequence[Link]) -> CrossCheck:
    """The intake cross-check (T71 Q10): CLASSIFY_REQUEST rows at or before ``audit_at`` on the person's own records."""
    own = {lk.resource_id for lk in links if lk.resource_id}
    if account:
        own.add(account)
    rows = sorted(
        a.activity_id
        for a in w.ctx.activity
        if a.event_type == "CLASSIFY_REQUEST" and a.resource_id in own and timeutil.le(a.event_time, req.audit_at)
    )
    return CrossCheck(bool(rows), tuple(rows))


_LINK_BASIS = {
    "record_identifier": "identifier",
    "trace_lookup": "trace",
    "link_row": "link_row",
    "alias": "alias",
    "image_extraction": "image",
}


def records_in_scope(
    case_id: str, w: World, asg: AccountAssignment | None, flags: list[Flag]
) -> dict[str, tuple[str, str | None]]:
    """The records that belong to a case: resource ID -> (link basis, system hint).

    In order: every record a link puts in the request window, then the primary account (basis from
    its assignment stage), then each identifier-free analytics claim (whose flags join ``flags``).
    The first basis found for a record is kept.
    """
    found: dict[str, tuple[str, str | None]] = {}
    for lk in w.case_links[case_id]:
        if lk.in_window and lk.resource_id:
            found.setdefault(lk.resource_id, (_LINK_BASIS[lk.basis], lk.system_id))
    if asg is not None and asg.resource_id and asg.resource_id not in found:
        found[asg.resource_id] = (STAGE_BASIS.get(asg.stage, "account"), "account_service")
    for claim in w.analytics.get(case_id, ()):
        if claim.resource_id not in found:
            found[claim.resource_id] = ("slot_band", None)
            flags.extend(claim.flags)
    return found


@dataclass(frozen=True)
class CaseView:
    """The per-case facts every record of the case is evaluated against."""

    audit_at: str
    identifiers: IdentifierSet
    person: str | None
    pending_png: tuple[str, ...]  # PNGs captured at or before audit_at still waiting for the vision step
    read_png: tuple[str, ...]  # PNGs captured at or before audit_at that the vision step read
    case_file: str | None  # the case's cited file


@dataclass(frozen=True)
class ResourceEvaluation:
    """One record's finding, the unread files its state depends on, and the fail-closed reasons it raises."""

    finding: ResourceFinding
    depends_on: frozenset[str]
    reasons: frozenset[FailedClosedReason]


def _readings(key: ResourceKey, obs: Sequence[Observation], view: CaseView, w: World) -> list[StateObservation]:
    """The record's own readings plus a PRESENT reading per catalog alias linked at or before audit_at."""
    readings = list(record_readings(key, obs, view.identifiers))
    for a in w.aliases:
        if a.resource_id == key.resource_id and timeutil.le(a.link_time, view.audit_at):
            readings.append(
                StateObservation(
                    "PRESENT",
                    observation_time(a.observation),
                    a.file_id,
                    a.observation.captured_at,
                    a.observation.locator,
                    "alias",
                )
            )
    return readings


def evaluate_resource(rid: str, basis: str, hint: str | None, view: CaseView, w: World) -> ResourceEvaluation:
    """Evaluate one record of a case: its state at ``audit_at``, category, decision, citation and flags.

    The fail-closed reasons it can raise are those of the module docstring that concern one record:
    NO_CATEGORY_RULE, UNINTERPRETED_RECORD, IMAGE_STATE_NOT_SHOWN, IMAGE_OMITS_CATALOG_RECORD,
    OWN_KEY_CONFLICT and POST_AUDIT_ONLY_FINDING. :func:`fail_closed_reason` picks the row's one reason.
    """
    rules = w.ctx.rules
    audit_at = view.audit_at
    system = _resource_system(rid, w, hint)
    key = ResourceKey(system, rid)
    obs = w.obs_by_resource.get(rid, [])
    activity = w.activity_by_resource.get(rid, [])
    cat = categorize(key, obs, activity, audit_at, attachment_documents=w.attachment_documents)
    readings = _readings(key, obs, view, w)
    usable = [r for r in readings if at_or_before(r.time, audit_at)]
    replica = any(is_replica_copy(o) for o in obs if observation_state_ok(o, key, audit_at))
    if not replica:
        attachment = cat.category == "SUPPORT_ATTACHMENT"
        readings.extend(omission_readings(key, w.listings, w.file_captured, attachment))
    rflags: list[Flag] = []
    reasons: set[FailedClosedReason] = set()
    depends: frozenset[str] = frozenset()
    if not usable and basis == "link_row" and view.pending_png:
        depends = frozenset(view.pending_png)
        rflags.append(
            Flag("STATE_NEEDS_IMAGE", f"{rid}: known only by a catalog row; {len(view.pending_png)} image(s) unread")
        )
    violating = violating_states(cat.category, rules)
    state = state_at(
        key, readings, audit_at, violating=violating, default_absent=cat.category == "USER_PROFILE", depends_on=depends
    )
    if state.value is None and depends and cat.category == "USER_PROFILE":
        state = state_at(key, readings, audit_at, violating=violating, default_absent=True)
        state = replace(state, depends_on=depends)
    decision = decide(state, cat, rules)
    if cat.flag is not None:
        rflags.append(cat.flag)
    if state.basis == "default_absent":
        rflags.append(Flag("DEFAULT_ABSENT", f"{rid}: no observation at or before audit_at (R8)"))
    if state.time_basis == "pdf_stated":
        rflags.append(Flag("PDF_STATED_TIME", f"{rid}: page time used (T68)"))
    if rid in w.image_conflicts:
        rflags.append(
            Flag("IMAGE_SUBJECT_CONFLICT", f"{rid}: catalog link kept; images {','.join(w.image_conflicts[rid])}")
        )
    if state.value is None:
        rflags.append(Flag("NO_STATE", f"{rid}: no state at or before audit_at; no step"))
    seen = sum(1 for o in obs if at_or_before(observation_time(o), audit_at)) + sum(
        1 for r in usable if r.kind == "alias"
    )
    if decision.outcome == "NO_STEP" and state.value is not None:
        reasons.add("NO_CATEGORY_RULE")  # a state with no rule covering its category is never dropped silently
        rflags.append(
            Flag(
                "NO_CATEGORY_RULE",
                f"{rid}: state {state.value} but no rule covers category {cat.category} (system {system}); no step",
            )
        )
    elif decision.outcome == "NO_STEP" and seen:
        reasons.add("UNINTERPRETED_RECORD")
        rflags.append(
            Flag(
                "UNINTERPRETED_RECORD",
                f"{rid}: {seen} reading(s) at or before audit_at give no step "
                f"(state {state.value}, category {cat.category}, system {system})",
            )
        )
    shown_in_image = any(o.locator.kind == "image" for o in obs)
    waited_on_image = not usable and basis == "link_row" and bool(view.read_png) and not depends
    if waited_on_image and shown_in_image:
        # the record would wait on an image, a reading shows it, but nothing visible on screen gives it
        # a state; an omission elsewhere is no substitute for the screenshot it waited on
        reasons.add("IMAGE_STATE_NOT_SHOWN")
        rflags.append(
            Flag(
                "IMAGE_STATE_NOT_SHOWN",
                f"{rid}: waited on an image; the image(s) read show it with no visible state "
                f"(state {state.value}, {state.basis})",
            )
        )
    if waited_on_image and not shown_in_image:
        # the record would wait on an image (STATE_NEEDS_IMAGE), the images were read, and no reading mentions it
        reasons.add("IMAGE_OMITS_CATALOG_RECORD")
        rflags.append(
            Flag(
                "IMAGE_OMITS_CATALOG_RECORD",
                f"{rid}: waited on an image (no state at or before audit_at from other evidence); "
                f"{len(view.read_png)} image(s) read by the vision step do not show it",
            )
        )
    if decision.outcome == "COMPLIANT" and decision.verification_op == "VERIFY_RECORD_PRESENT" and (
        state.value != "PRESENT"
    ):
        rflags.append(  # the output step is kept (DEV sample answers do the same); the artifacts say so
            Flag(
                "PRESENT_CLAIM_OVER_STATE",
                f"{rid}: retained ({cat.category}) gets VERIFY_RECORD_PRESENT while the derived state is "
                f"{state.value} ({state.basis})",
            )
        )
    mine = {view.person} if view.person else set()
    others = w.links.own_persons.get(rid, frozenset()) - mine
    if others:
        reasons.add("OWN_KEY_CONFLICT")  # the record's own key belongs to another known person
        rflags.append(
            Flag(
                "OWN_KEY_CONFLICT",
                f"{rid}: its own keys name {len(others)} known person(s) other than the requester",
            )
        )
    if system_from_prefix(rid) and system_from_prefix(rid) != system:
        rflags.append(Flag("SYSTEM_DIFFERS_FROM_PREFIX", f"{rid}: {system}"))
    if decision.outcome == "FINDING" and _held_only_after(rid, obs, w, audit_at):
        reasons.add("POST_AUDIT_ONLY_FINDING")
        rflags.append(
            Flag(
                "POST_AUDIT_ONLY_FINDING",
                f"{rid}: only files captured after audit_at hold this record, so no citable file contains it "
                "(T101; T66 rule 1 and CD-F21)",
            )
        )
    cite = ""
    if decision.outcome == "FINDING":
        vfiles = [r.file_id for r in state.readings if r.value == state.value and r.kind != "omission"]
        cite = finding_citation(view.case_file, vfiles, w.file_captured, w.manifest_pos, audit_at)
    finding = ResourceFinding(key, basis, state, cat, decision, None, cite, tuple(rflags))
    return ResourceEvaluation(finding, frozenset(state.depends_on), frozenset(reasons))


#: The order in which a record-level reason decides a row, after IDENTITY_UNRESOLVED,
#: OWN_KEY_CONFLICT and the unread-dependency reasons (module docstring).
_RECORD_REASON_ORDER: tuple[FailedClosedReason, ...] = (
    "POST_AUDIT_ONLY_FINDING",
    "NO_CATEGORY_RULE",
    "IMAGE_OMITS_CATALOG_RECORD",
    "IMAGE_STATE_NOT_SHOWN",
    "UNINTERPRETED_RECORD",
)


def fail_closed_reason(
    resolved: bool,
    evaluations: Sequence[ResourceEvaluation],
    deps: frozenset[str],
    dep_kinds: Mapping[str, FailedClosedReason],
) -> FailedClosedReason | None:
    """The one reason a case's row fails closed, or None.

    The gravest reason wins, in this order: an unresolved identity; a record whose own keys name
    another person; an unread dependency (its gravest kind, :data:`_DEPENDENCY_REASONS`); then the
    record-level reasons in :data:`_RECORD_REASON_ORDER`; last, NOTHING_FOUND when no record is a
    FINDING or COMPLIANT. A request read as NOT_DELETION clears the reason later (in ``audit_case``).
    """
    raised = {r for e in evaluations for r in e.reasons}
    if not resolved:
        return "IDENTITY_UNRESOLVED"
    if "OWN_KEY_CONFLICT" in raised:
        return "OWN_KEY_CONFLICT"
    if deps:
        return next(k for k in _DEPENDENCY_REASONS if k in dep_kinds.values()) if dep_kinds else "UNPARSED_DEPENDENCY"
    for reason in _RECORD_REASON_ORDER:
        if reason in raised:
            return reason
    if not any(e.finding.decision.outcome in ("FINDING", "COMPLIANT") for e in evaluations):
        return "NOTHING_FOUND"
    return None


def audit_case(case_id: str, w: World, intent_for: IntentProvider) -> CaseRecord:
    """Audit one case end to end (module docstring) and pass it through the pre-write gate.

    The engine poses no open questions, so the record's ``open_questions``, ``answers`` and
    ``rejected`` are empty here; the agent loop poses questions and ``pipeline`` records them.
    """
    ctx = w.ctx
    req = next(r for r in ctx.requests if r.case_id == case_id)
    ident = w.resolutions[case_id]
    links = w.case_links[case_id]
    asg = w.assignments.get(case_id)
    flags: list[Flag] = list(asg.flags if asg else ())
    audit_at = req.audit_at
    found = records_in_scope(case_id, w, asg, flags)
    structural = {f.file_id for f in w.failures if not f.png and timeutil.le(f.captured_at, audit_at)}
    case = choose_citation(
        links,
        audit_at,
        file_captured=w.file_captured,
        manifest_pos=w.manifest_pos,
        owned_observations=_owned_observations(w, links, audit_at),
        account_files=w.account_files,
    )
    view = CaseView(
        audit_at=audit_at,
        identifiers=ident.identifiers,
        person=ident.person,
        pending_png=tuple(sorted(f.file_id for f in w.failures if f.png and timeutil.le(f.captured_at, audit_at))),
        read_png=tuple(
            sorted(
                fid for fid in ctx.vision_read if fid in w.file_captured and timeutil.le(w.file_captured[fid], audit_at)
            )
        ),
        case_file=case.file_id,
    )
    evaluations = [evaluate_resource(rid, *found[rid], view, w) for rid in sorted(found)]
    for e in evaluations:
        flags.extend(e.finding.flags)
    resources = sorted((e.finding for e in evaluations), key=lambda r: (r.key.system_id, r.key.resource_id))
    deps = frozenset(structural.union(*(e.depends_on for e in evaluations)))
    by_file = {f.file_id: f for f in w.failures}
    dep_kinds = {fid: _failure_kind(by_file[fid]) for fid in sorted(deps) if fid in by_file}
    for fid, kind in dep_kinds.items():
        flags.append(Flag("FAILED_DEPENDENCY", f"{fid}: {kind} (parse status {by_file[fid].status})"))
    failed = fail_closed_reason(ident.person is not None, evaluations, deps, dep_kinds)
    if deps:
        flags.append(Flag("UNPARSED_DEPENDENCY", f"{len(deps)} unparsed file(s) this case depends on"))
    cc = crosscheck(req, w, asg.resource_id if asg else None, links)
    intent = intent_for(req, cc)
    if intent.source in ("FAILED_CLOSED", "FAILED_BUDGET"):
        flags.append(Flag("INTENT_" + intent.source, "no validated model intent: engine deletion-path row (T71 Q2)"))
    if cc.intake_non_deletion:
        flags.append(
            Flag("INTAKE_NON_DELETION", f"{len(cc.activity_ids)} CLASSIFY_REQUEST row(s) on the person's records")
        )
    if intent.not_applicable:
        failed = None
    steps = compile_steps(intent, resources, case, failed_closed=failed is not None)
    record = CaseRecord(
        case_id=case_id,
        request=req,
        intent=intent,
        identity=ident,
        account=asg,
        resources=tuple(resources),
        citation=case,
        open_questions=(),
        answers=(),
        rejected=(),
        failed_dependencies=deps,
        steps=steps,
        checks=(),
        flags=tuple(sorted(set(flags), key=lambda f: (f.code, f.detail))),
        failed_closed=failed,
    )
    return gate(record, w.validation)


_DEPENDENCY_REASONS: tuple[FailedClosedReason, ...] = (
    "MISSING_EVIDENCE_FILE",
    "EVIDENCE_PARSE_ERROR",
    "UNKNOWN_EVIDENCE_FAMILY",
    "UNPARSED_DEPENDENCY",
)


def _failure_kind(f: FileFailure) -> FailedClosedReason:
    """Why a dependency is unread (T105): a file the manifest names but the disk lacks, a file
    on disk that failed to parse (``ERROR``, e.g. SQL that cannot run), a file no family sniffer
    matched, or anything else not OK (``EMPTY``, ``AMBIGUOUS_FAMILY``, an image waiting for a model)."""
    if f.missing:
        return "MISSING_EVIDENCE_FILE"
    if f.status == "ERROR":
        return "EVIDENCE_PARSE_ERROR"
    if f.status == "UNKNOWN_FAMILY":
        return "UNKNOWN_EVIDENCE_FAMILY"
    return "UNPARSED_DEPENDENCY"


def _held_only_after(rid: str, obs: Sequence[Observation], w: World, audit_at: str) -> bool:
    """T101: every file that holds ``rid`` (an observation of it, or a catalog alias of it) was
    captured after ``audit_at``. False when no manifest file holds it (no file evidence to judge)."""
    holders = {o.file_id for o in obs} | {a.file_id for a in w.aliases if a.resource_id == rid}
    known = [f for f in sorted(holders) if f in w.file_captured]
    return bool(known) and not any(timeutil.le(w.file_captured[f], audit_at) for f in known)


def observation_state_ok(o: Observation, key: ResourceKey, audit_at: str) -> bool:
    """The observation states something about the resource at or before ``audit_at``."""
    return observation_state(o, o.system_id or key.system_id) is not None and at_or_before(
        observation_time(o), audit_at
    )


def _owned_observations(w: World, links: Sequence[Link], audit_at: str) -> list[Observation]:
    """Records of resources a catalog row at or before ``audit_at`` ties to the person (citation candidates)."""
    owned = {
        lk.resource_id
        for lk in links
        if lk.basis == "link_row"
        and lk.resource_id
        and lk.activity_id
        and any(c.activity_id == lk.activity_id and timeutil.le(c.event_time, audit_at) for c in w.catalog)
    }
    return [o for rid in sorted(owned) for o in w.obs_by_resource.get(rid, ())]


class IntentProvider:
    """Gives a case its intent decision; the engine's own provider is :class:`FailClosedIntent` (T71 Q2)."""

    def __call__(self, req: DeletionRequest, crosscheck: CrossCheck) -> IntentDecision:  # pragma: no cover
        """The intent decision for one request."""
        raise NotImplementedError


class FailClosedIntent(IntentProvider):
    """No model intent: every case gets the engine's deletion-path row, flagged (T71 Q2)."""

    def __call__(self, req: DeletionRequest, crosscheck: CrossCheck) -> IntentDecision:
        """The fail-closed decision, whatever the request says."""
        return fail_closed_intent(crosscheck)


def audit_all(
    ctx: AuditContext, cases: Sequence[str], intent_for: IntentProvider | None = None, world: World | None = None
) -> dict[str, CaseRecord]:
    """Audit the given cases (the global stages always see every request)."""
    w = world or build_world(ctx)
    provider = intent_for or FailClosedIntent()
    known = {r.case_id for r in ctx.requests}
    malformed = {i.case_id for i in ctx.request_issues if i.case_id}
    missing = sorted(set(cases) - known - malformed)
    if missing:
        raise KeyError(f"{len(missing)} requested case(s) are in no request file")
    out = {}
    for cid in sorted(set(cases)):
        out[cid] = audit_case(cid, w, provider) if cid in known else malformed_record(cid, w)
    return out


def malformed_record(case_id: str, w: World) -> CaseRecord:
    """T86 item 2: a request row that could not be loaded gives a FAILED_CLOSED row with no step
    (nothing about the request can be trusted), its reasons in the run artifacts."""
    reasons = sorted({i.reason for i in w.ctx.request_issues if i.case_id == case_id})
    ident = IdentityResolution("UNRESOLVED", IdentifierSet(None, frozenset(), frozenset(), frozenset()), ())
    record = CaseRecord(
        case_id=case_id,
        request=None,
        intent=fail_closed_intent(CrossCheck(False, ())),
        identity=ident,
        account=None,
        resources=(),
        citation=CitationPlan(None, "none"),
        open_questions=(),
        answers=(),
        rejected=(),
        failed_dependencies=frozenset(),
        steps=(),
        checks=(),
        flags=tuple(Flag("MALFORMED_REQUEST", r) for r in reasons),
        failed_closed="MALFORMED_REQUEST",
    )
    return gate(record, w.validation)
