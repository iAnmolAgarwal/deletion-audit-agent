"""The deterministic auditor: inputs -> one :class:`~deletion_audit.record.CaseRecord` per case.

Stages (``notes/ARCHITECTURE_OPTIONS.md`` section 1.0): parse evidence (GP) -> resolve identity
-> link records -> assign primary accounts (global, both request files, T32) -> attach
identifier-free analytics (global) -> per case: state at ``audit_at``, category, decision,
citation, steps -> pre-write validation.

The engine settles every fact. A model (G7, not built yet) may only answer typed open questions;
until then the pipeline gives every case the fail-closed intent of T71 Q2.

Fail-closed rules, each with its basis:

* **T8**: a non-OK evidence file is never read as "nothing found". A file that failed for a
  structural reason (``ERROR``, ``EMPTY``, unknown or ambiguous family, a non-PNG that needs a
  model) could concern anyone, so every case whose ``audit_at`` is at or after its capture time
  depends on it. A PNG that waits for the vision gate (``NEEDS_MODEL`` with the PNG signature,
  T72) is a dependency of a case only where a record is known solely through a catalog row and no
  parsed evidence gives its state. A case with a dependency is FAILED_CLOSED (INCOMPLETE with the
  steps the other inputs still give), never COMPLETE: T8 as restated by T86 item 1; a file the
  manifest names but the disk lacks gives the reason MISSING_EVIDENCE_FILE.
* **T86 item 2**: a request row that could not be loaded gives a FAILED_CLOSED row for its case
  (when the case ID is readable) with no step; every such row is listed in the run artifacts.
* **T63**: an unresolved identity is searched by the raw request email and its hash, and the row
  is FAILED_CLOSED(IDENTITY_UNRESOLVED), never NOT_APPLICABLE.
* **T71 Q11**: an image whose subject is not the person a catalog row names keeps the record in
  scope (the catalog link wins) and raises IMAGE_SUBJECT_CONFLICT.
* **UNINTERPRETED_RECORD** (``../CLAUDE.md`` section 3, "a failed read is never nothing found";
  developer approval 2026-10-25T06:08:27+05:30, G5 verifier finding 5): a record in the case's
  scope that has evidence at or before ``audit_at``, but from which the engine derives no step
  (no state can be read from it, or no rule covers its category, such as an unknown system), fails
  the row closed with its own reason and flag. R8's no-step rule stays for a record with no
  observation at all, and T69 is unchanged: a legal-hold register entry that names no resource is
  not a record here (records are keyed by resource ID), so it still gives no step. Real data
  (runs ``g5fix1-dev22-20261025T0650``, ``g5fix1-test-20261025T0650``): 0 such records; the only
  NO_STEP records are 3 catalog-only records with no observation, waiting for images, already
  FAILED_CLOSED(UNPARSED_DEPENDENCY).
* **A screenshot the vision step read is not unread** (G7a wiring proposal 5; T60: zero skips at
  freeze). A PNG named in ``AuditContext.vision_read`` (both of its readings succeeded, so its
  records are in ``image_observations``) is neither a pending image nor a skip. A PNG whose
  reading failed, or that was never read, stays a :class:`FileFailure` and an unparsed dependency
  exactly as T8 says.
* **POST_AUDIT_ONLY_FINDING** (developer ruling T101 on red-team fixture R06): a FINDING whose
  record is held only by files captured after ``audit_at`` fails its row closed with its own
  reason and a ``POST_AUDIT_ONLY_FINDING`` flag naming the resource. Such a finding can cite no
  file that both contains it and was captured at or before ``audit_at`` (T66 rule 1 and CD-F21
  cannot both hold), so the row is decided here, never left to the validator. Measured by main on
  real data: 0 such findings on DEV and on test.
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
    "INSTRUCTION_LIKE_TEXT",
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


def _failures(ctx: AuditContext, file_captured: Mapping[str, str]) -> tuple[FileFailure, ...]:
    """Manifest files that did not parse to OK, minus the PNGs the vision step read (module docstring)."""
    out = []
    for ref in ctx.manifest:
        fp = ctx.index.files.get(ref.file_id)
        if fp is None or fp.ok:
            continue
        png = False
        if fp.status == "NEEDS_MODEL":
            try:
                with (ctx.dataset_dir / ref.path).open("rb") as handle:
                    png = handle.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
            except OSError:
                png = False
        if png and ref.file_id in ctx.vision_read:
            continue  # read by the vision step: its records are image observations, not a pending file
        missing = fp.status == "ERROR" and not (ctx.dataset_dir / ref.path).is_file()
        out.append(FileFailure(ref.file_id, fp.status, file_captured[ref.file_id], png, missing))
    return tuple(out)


def _unresolved_links(ident: IdentityResolution, ctx: AuditContext, window: Window) -> tuple[Link, ...]:
    """T63: links of an unresolved request by its raw email and hash only (exact, own key first)."""
    ids: IdentifierSet = ident.identifiers
    out = []
    for o in list(ctx.index.observations()) + list(ctx.image_observations):
        own = [i for i in o.record_identifiers if is_own_key(i)]
        hit = next((i for i in o.record_identifiers if ids.matches(i)), None)
        basis: LinkBasis = "record_identifier"
        if hit is None and not own and o.resource_id:
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
            link_observations(ident, lindex, window, aliases) if ident.person else _unresolved_links(ident, ctx, window)
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
    validation = build_validation_context(ctx, catalog, aliases, file_captured)
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
) -> ValidationContext:
    """The citable IDs with their times, and what each file contains, declares and lists."""
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
    )


def _resource_system(rid: str, w: World, hint: str | None) -> str:
    """The output ``system_id`` of a resource: the system its own evidence names most often, else
    the resource-type prefix, else the catalog/activity hint (INTERFACES rule 6: from the evidence,
    never from ``system_activity.target_system`` when evidence names one)."""
    counts = Counter(o.system_id for o in w.obs_by_resource.get(rid, ()) if o.system_id)
    if counts:
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return system_from_prefix(rid) or hint or "unknown_system"


def crosscheck(req: DeletionRequest, w: World, account: str | None, links: Sequence[Link]) -> CrossCheck:
    """Q10: CLASSIFY_REQUEST intake rows at or before ``audit_at`` on the person's own records."""
    own = {lk.resource_id for lk in links if lk.resource_id}
    if account:
        own.add(account)
    rows = sorted(
        a.activity_id
        for a in w.ctx.activity
        if a.event_type == "CLASSIFY_REQUEST" and a.resource_id in own and timeutil.le(a.event_time, req.audit_at)
    )
    return CrossCheck(bool(rows), tuple(rows))


def audit_case(case_id: str, w: World, intent_for: IntentProvider) -> CaseRecord:
    """Audit one case end to end (module docstring) and pass it through the pre-write gate."""
    ctx = w.ctx
    req = next(r for r in ctx.requests if r.case_id == case_id)
    ident = w.resolutions[case_id]
    links = w.case_links[case_id]
    asg = w.assignments.get(case_id)
    flags: list[Flag] = list(asg.flags if asg else ())
    audit_at = req.audit_at
    # --- which records belong to the case
    found: dict[str, tuple[str, str | None]] = {}  # rid -> (link basis, system hint)
    for lk in links:
        if lk.in_window and lk.resource_id:
            basis = {
                "record_identifier": "identifier",
                "trace_lookup": "trace",
                "link_row": "link_row",
                "alias": "alias",
                "image_extraction": "image",
            }[lk.basis]
            found.setdefault(lk.resource_id, (basis, lk.system_id))
    if asg is not None and asg.resource_id and asg.resource_id not in found:
        found[asg.resource_id] = (STAGE_BASIS.get(asg.stage, "account"), "account_service")
    for claim in w.analytics.get(case_id, ()):
        if claim.resource_id not in found:
            found[claim.resource_id] = ("slot_band", None)
            flags.extend(claim.flags)
    # --- unparsed dependencies (T8)
    structural = {f.file_id for f in w.failures if not f.png and timeutil.le(f.captured_at, audit_at)}
    pending_png = sorted(f.file_id for f in w.failures if f.png and timeutil.le(f.captured_at, audit_at))
    case = choose_citation(
        links,
        audit_at,
        file_captured=w.file_captured,
        manifest_pos=w.manifest_pos,
        owned_observations=_owned_observations(w, links, audit_at),
        account_files=w.account_files,
    )
    resources: list[ResourceFinding] = []
    deps: set[str] = set(structural)
    uninterpreted: list[str] = []
    post_audit_only: list[str] = []
    for rid in sorted(found):
        basis, hint = found[rid]
        system = _resource_system(rid, w, hint)
        key = ResourceKey(system, rid)
        obs = w.obs_by_resource.get(rid, [])
        cat = categorize(
            key, obs, w.activity_by_resource.get(rid, []), audit_at, attachment_documents=w.attachment_documents
        )
        readings = list(record_readings(key, obs, ident.identifiers))
        for a in w.aliases:
            if a.resource_id == rid and timeutil.le(a.link_time, audit_at):
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
        usable = [r for r in readings if at_or_before(r.time, audit_at)]
        replica = any(is_replica_copy(o) for o in obs if observation_state_ok(o, key, audit_at))
        if not replica:
            attachment = cat.category == "SUPPORT_ATTACHMENT"
            readings.extend(omission_readings(key, w.listings, w.file_captured, attachment))
        rflags: list[Flag] = []
        depends: frozenset[str] = frozenset()
        if not usable and basis == "link_row" and pending_png:
            depends = frozenset(pending_png)
            rflags.append(
                Flag("STATE_NEEDS_IMAGE", f"{rid}: known only by a catalog row; {len(pending_png)} image(s) unread")
            )
        state = state_at(
            key,
            readings,
            audit_at,
            violating=violating_states(cat.category, ctx.rules),
            default_absent=cat.category == "USER_PROFILE",
            depends_on=depends,
        )
        if state.value is None and depends and cat.category == "USER_PROFILE":
            state = state_at(
                key, readings, audit_at, violating=violating_states(cat.category, ctx.rules), default_absent=True
            )
            state = replace(state, depends_on=depends)
        deps |= set(state.depends_on)
        decision = decide(state, cat, ctx.rules)
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
        if decision.outcome == "NO_STEP" and seen:
            uninterpreted.append(rid)
            rflags.append(
                Flag(
                    "UNINTERPRETED_RECORD",
                    f"{rid}: {seen} reading(s) at or before audit_at give no step "
                    f"(state {state.value}, category {cat.category}, system {system})",
                )
            )
        if system_from_prefix(rid) and system_from_prefix(rid) != system:
            rflags.append(Flag("SYSTEM_DIFFERS_FROM_PREFIX", f"{rid}: {system}"))
        if decision.outcome == "FINDING" and _held_only_after(rid, obs, w, audit_at):
            post_audit_only.append(rid)
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
            cite = finding_citation(case.file_id, vfiles, w.file_captured, w.manifest_pos, audit_at)
        resources.append(ResourceFinding(key, basis, state, cat, decision, None, cite, tuple(rflags)))
        flags.extend(rflags)
    resources.sort(key=lambda r: (r.key.system_id, r.key.resource_id))
    failed: FailedClosedReason | None = None
    if ident.person is None:
        failed = "IDENTITY_UNRESOLVED"
    elif deps & {f.file_id for f in w.failures if f.missing}:
        failed = "MISSING_EVIDENCE_FILE"  # T86 item 1: FAILED_CLOSED even with findings
    elif deps:
        failed = "UNPARSED_DEPENDENCY"  # T8/T86 item 1: an unread dependency fails the row closed
    elif post_audit_only:
        failed = "POST_AUDIT_ONLY_FINDING"  # T101 (R06): decided here, not left to the validator
    elif uninterpreted:
        failed = "UNINTERPRETED_RECORD"  # module docstring: evidence the engine cannot read is no proof
    elif not any(r.decision.outcome in ("FINDING", "COMPLIANT") for r in resources):
        failed = "NOTHING_FOUND"
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
        failed_dependencies=frozenset(deps),
        steps=steps,
        checks=(),
        flags=tuple(sorted(set(flags), key=lambda f: (f.code, f.detail))),
        failed_closed=failed,
    )
    return gate(record, w.validation)


def _held_only_after(rid: str, obs: Sequence[Observation], w: World, audit_at: str) -> bool:
    """T101 (R06): every file that holds ``rid`` (an observation of it, or a catalog alias of it) was
    captured after ``audit_at``. False when no manifest file holds it (no file evidence to judge)."""
    holders = {o.file_id for o in obs} | {a.file_id for a in w.aliases if a.resource_id == rid}
    known = [f for f in sorted(holders) if f in w.file_captured]
    return bool(known) and not any(timeutil.le(w.file_captured[f], audit_at) for f in known)


def observation_state_ok(o: Observation, key: ResourceKey, audit_at: str) -> bool:
    """The observation states something about the resource at or before ``audit_at``."""
    from .state.observe import observation_state

    return observation_state(o, o.system_id or key.system_id) is not None and at_or_before(
        observation_time(o), audit_at
    )


def _owned_observations(w: World, links: Sequence[Link], audit_at: str) -> list[Observation]:
    """Records of resources a catalog row at or before ``audit_at`` ties to the person (R14)."""
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
    """Gives a case its intent decision. G5's provider is :class:`FailClosedIntent` (T71 Q2)."""

    def __call__(self, req: DeletionRequest, crosscheck: CrossCheck) -> IntentDecision:  # pragma: no cover
        """The intent decision for one request."""
        raise NotImplementedError


class FailClosedIntent(IntentProvider):
    """No model gate yet: every case gets the engine's deletion-path row, flagged (T71 Q2)."""

    def __call__(self, req: DeletionRequest, crosscheck: CrossCheck) -> IntentDecision:
        """The fail-closed decision, whatever the request says."""
        from .record import fail_closed_intent

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


def brief(record: CaseRecord) -> EngineBrief:
    """The engine's read-only brief for one case (the ``audit_case`` tool's backend, G7)."""
    return EngineBrief(record.case_id, record.resources, record.citation, (), record.flags)
