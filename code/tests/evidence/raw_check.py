"""T13 raw-file comparison (notes/INTERFACES.md section 6), written to notes/parser_raw_check.md.

Run from the repo root: ``python3 code/tests/evidence/raw_check.py``.

Method:

* Families checked: the families ``research/16_test_coverage.md`` section 3.2 marks as never
  a DEV primary (selected by the file-name stem that table uses), plus every registry family
  the table does not name.
* A person's identifiers (test tooling only): the request email resolves to a ``user_id``
  through current emails in ``user_identities.csv`` and old or new emails in
  ``user_audit_log.csv``. The person is then searched by the ``user_id``, every email and
  phone that user has had in either file, the sha256 of each of those emails (the
  identities file's own ``email_hash`` formula, T59), and every resource ID that a
  ``system_activity.csv`` row links to the ``user_id`` (T68).
* Per family, the 3 test cases with the lowest ``sha256(case_id)`` among those whose person
  appears in a file of the family are selected.
* Raw units (lines, SQL ``INSERT`` rows, JSON records, PDF pages) are enumerated here with
  their own regular expressions, not with the parsers. Each unit that holds a person
  identifier, and each unit carrying a resource ID on the same trace, must map to an
  observation with the same locator, record time, resource ID and trace. Identifiers are
  compared as sets for **equality** (T68): the observation's own identifiers (record
  identifiers, plus lookups whose value is in the unit) must equal the identifier tokens
  of the raw unit (emails, known phones, user IDs, 64-hex hashes), and every lookup it
  borrowed must appear in a unit on the same trace in the same file.

The report names case IDs, locators and identifier kinds, never identifier values.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from deletion_audit.evidence import EvidenceIndex, parse_all  # noqa: E402
from deletion_audit.evidence.model import Observation  # noqa: E402
from deletion_audit.inputs import load_activity, load_audit_log, load_identities  # noqa: E402

DATASET = REPO_ROOT / "dataset"
REPORT = REPO_ROOT / "notes" / "parser_raw_check.md"
CASES_PER_FAMILY = 3

# research/16 section 3.2 family (file-name stem) -> registry family
RESEARCH_FAMILIES: dict[str, str] = {
    "service_resource_export": "service_resource_export",
    "customer_data_inventory": "sql_inventory",
    "resource_lookup_trace": "kv_log",
    "customer_data_read_replica": "sql_replica_topology",
    "customer_data_regional_replicas": "sql_replica_topology",
    "customer_data_reporting_replica": "sql_replica_topology",
    "search_index_diagnostic": "kv_log",
    "notification_delivery": "kv_log",
    "connector_configurations": "flat_record_list",
    "customer_export_manifest": "flat_record_list",
    "cloud_runtime_export": "cloud_runtime_log",
    "structured_service_events": "json_line_log",
    "syslog_archive": "syslog_log",
    "operations_stream": "pipe_log",
    "customer_data_snapshot_bundle": "snapshot_bundle",
    "customer_data_failover_replica": "sql_replica_topology",
    "customer_account_handover": "pipe_handover",
    "service_events": "kv_log",
    "security_audit_ledger": "flat_record_list",
}
UNSEEN_RESEARCH: tuple[str, ...] = (
    "customer_data_regional_replicas", "customer_data_reporting_replica",
    "search_index_diagnostic", "notification_delivery", "connector_configurations",
    "customer_export_manifest", "cloud_runtime_export", "structured_service_events",
    "syslog_archive", "operations_stream", "customer_data_failover_replica",
    "security_audit_ledger",
)

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\+?\d[\d ().-]{6,}\d")
TRACE = re.compile(r"\b(?:tr|rb)-[A-Za-z0-9-]+\b")
USER_ID = re.compile(r"\buser_\d+\b")
HASH64 = re.compile(r"\b[0-9a-fA-F]{64}\b")
SEAL = re.compile(r"integrity_seal\\?\"?\s*[:=]\s*\\?\"?(?:sha256:)?([0-9a-fA-F]{64})")
COMPARED_KINDS = ("email", "phone", "email_hash", "user_id")
RESOURCE = re.compile(r"\b(?:account|search|analytics|support|export|data_flow|backup|audit_record|"
                      r"tombstone|legal_hold)_\d+\b")
DECLARED_RESOURCE = re.compile(r"resource_id\\?\"?\s*[:=]\s*\\?\"?([a-z_]+_\d+)")
SQL_INSERT = re.compile(r"^INSERT INTO \"?(\w+)\"? VALUES\s*\('([^']*)'")
LOG_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ")
HANDOVER_TIME = re.compile(r"^- (\S+) \|")


# --------------------------------------------------------------------------- people
@dataclass
class Person:
    """Every identifier one user has had, each with its label, plus linked resource IDs."""

    user_id: str
    emails: dict[str, str] = field(default_factory=dict)   # lower-case email -> label
    phones: dict[str, str] = field(default_factory=dict)   # digits -> label
    hashes: dict[str, str] = field(default_factory=dict)   # lower-case sha256 hex -> label
    resources: dict[str, str] = field(default_factory=dict)  # resource ID -> label

# Every phone (digits) any user has had, and every known email hash: phone-shaped and
# 64-hex tokens outside these sets are not identifiers (dates and amounts match the phone
# pattern; integrity seals are 64-hex too). Filled by load_people() (T75).
KNOWN_PHONES: set[str] = set()
KNOWN_HASHES: set[str] = set()


def _digits(text: str) -> str:
    """Digits of a phone number."""
    return "".join(ch for ch in text if ch.isdigit())


def load_people() -> tuple[dict[str, Person], dict[str, str]]:
    """Return (user_id -> Person, email -> user_id) from the identity inputs."""
    people: dict[str, Person] = {}
    email_to_user: dict[str, str] = {}
    for row in load_identities(DATASET):
        person = people.setdefault(row.user_id, Person(row.user_id))
        if row.email:
            person.emails[row.email.value] = "email (current)"
            email_to_user[row.email.value] = row.user_id
        if row.phone:
            person.phones[_digits(row.phone.raw)] = "phone (current)"
    for audit_row in load_audit_log(DATASET):
        person = people.setdefault(audit_row.user_id, Person(audit_row.user_id))
        for ident in (audit_row.old_identifier, audit_row.new_identifier):
            if ident is None or ident.kind not in ("email", "phone"):
                continue
            if ident.kind == "email":
                person.emails.setdefault(ident.value, "email (old)")
                email_to_user.setdefault(ident.value, audit_row.user_id)
            else:
                person.phones.setdefault(_digits(ident.raw), "phone (old)")
    for person in people.values():
        for email, label in person.emails.items():
            person.hashes.setdefault(hashlib.sha256(email.encode("utf-8")).hexdigest(),
                                     label.replace("email", "email hash"))
        KNOWN_PHONES.update(person.phones)
    for row in load_identities(DATASET):
        if row.email_hash:
            people[row.user_id].hashes.setdefault(row.email_hash.strip().lower(), "email hash (current)")
    for person in people.values():
        KNOWN_HASHES.update(person.hashes)
    for act in load_activity(DATASET):
        if act.resource_id:
            for user in USER_ID.findall(act.details):
                if user in people:
                    people[user].resources.setdefault(act.resource_id, "linked resource")
    return people, email_to_user


def load_cases(email_to_user: dict[str, str]) -> dict[str, str]:
    """Test case_id -> user_id for every resolvable request in deletion_requests.csv."""
    out: dict[str, str] = {}
    with (DATASET / "deletion_requests.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            user = email_to_user.get(row["email"].strip().lower())
            if user:
                out[row["case_id"]] = user
    return out


# --------------------------------------------------------------------------- raw units
@dataclass
class Unit:
    """One raw line, SQL row, JSON record or PDF page."""

    kind: str
    ref: str
    text: str
    time: str | None = None                 # the unit's own time when it is unambiguous
    context_times: tuple[str, ...] = ()     # enclosing captured_at values (JSON)
    declared_resource: str | None = None

    @property
    def emails(self) -> set[str]:
        """Lower-cased emails in the unit."""
        return {m.lower() for m in EMAIL.findall(self.text)}

    @property
    def phones(self) -> set[str]:
        """Digit strings of phone-like tokens in the unit."""
        return {_digits(m) for m in PHONE.findall(self.text)}

    @property
    def tokens(self) -> set[str]:
        """Identifier tokens of the unit in comparable form: emails, known phones, user IDs, hashes."""
        return (self.emails | (self.phones & KNOWN_PHONES) | set(USER_ID.findall(self.text))
                | ({m.lower() for m in HASH64.findall(self.text)} & KNOWN_HASHES))

    @property
    def trace(self) -> str | None:
        """The first trace-like token in the unit."""
        match = TRACE.search(self.text)
        return match.group(0) if match else None


def _line_units(path: Path) -> Iterator[Unit]:
    """Lines of a log or text file."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        time = LOG_TIME.match(line) or HANDOVER_TIME.match(line)
        declared = DECLARED_RESOURCE.search(line)
        if path.suffix == ".txt" and line.startswith("- "):
            parts = [p.strip() for p in line[2:].split("|")]
            declared_id = parts[2] if len(parts) > 2 else None
        else:
            declared_id = declared.group(1) if declared else None
        yield Unit("line", f"L{number}", line, time.group(1) if time else None,
                   declared_resource=declared_id)


def _sql_units(path: Path) -> Iterator[Unit]:
    """INSERT rows of a SQL file, numbered per table (rowid order)."""
    counters: dict[str, int] = defaultdict(int)
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SQL_INSERT.match(line)
        if not match:
            continue
        table = match.group(1)
        counters[table] += 1
        if table == "snapshot_scope":
            continue
        yield Unit("sql_row", f"{table}#rowid={counters[table]}", line,
                   declared_resource=match.group(2))


def _json_units(node: Any, path: str, times: tuple[str, ...]) -> Iterator[Unit]:
    """The outermost objects holding a ``resource_id`` inside arrays."""
    if isinstance(node, dict):
        here = times + tuple(v for k, v in node.items() if k == "captured_at" and isinstance(v, str))
        for key, value in node.items():
            yield from _json_units(value, f"{path}.{key}", here)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if isinstance(item, dict) and "resource_id" in item:
                yield Unit("json_path", item_path, json.dumps(item, ensure_ascii=False),
                           context_times=times, declared_resource=item.get("resource_id"))
            else:
                yield from _json_units(item, item_path, times)


def _pdf_units(path: Path) -> Iterator[Unit]:
    """Pages of a PDF's text layer."""
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            yield Unit("pdf_page", f"p{number}", page.extract_text() or "")


def raw_units(path: Path) -> list[Unit]:
    """Every raw unit of a file, by extension (test tooling)."""
    if path.suffix in (".log", ".txt"):
        return list(_line_units(path))
    if path.suffix == ".sql":
        return list(_sql_units(path))
    if path.suffix == ".json":
        return list(_json_units(json.loads(path.read_text(encoding="utf-8")), "$", ()))
    if path.suffix == ".pdf":
        return list(_pdf_units(path))
    return []


def hits(unit: Unit, person: Person) -> list[str]:
    """Labels of the person's identifiers found in the unit."""
    found = [person.emails[e] for e in unit.emails if e in person.emails]
    found += [person.phones[p] for p in unit.phones if p in person.phones]
    if person.user_id in USER_ID.findall(unit.text):
        found.append("user_id")
    found += [person.hashes[h] for h in {m.lower() for m in HASH64.findall(unit.text)} if h in person.hashes]
    found += [person.resources[r] for r in set(RESOURCE.findall(unit.text)) if r in person.resources]
    return found


def _ident_values(obs: Observation, lookup_only: bool = False) -> set[str]:
    """Comparable identifier values of an observation (emails lower, phones digits)."""
    idents = obs.lookup_identifiers if lookup_only else obs.record_identifiers | obs.lookup_identifiers
    return _comparable(idents)


def _comparable(idents: Any) -> set[str]:
    """Comparable values of the compared identifier kinds (phones as digits, known phones only)."""
    out: set[str] = set()
    for i in idents:
        if i.kind not in COMPARED_KINDS:
            continue
        value = _digits(i.value) if i.kind == "phone" else i.value.lower()
        if i.kind == "phone" and value not in KNOWN_PHONES:
            continue
        if i.kind == "email_hash" and value not in KNOWN_HASHES:
            continue
        out.add(value)
    return out


def _person_values(unit: Unit, person: Person) -> set[str]:
    """The person's identifier values present in a unit, in comparable form."""
    return ({e for e in unit.emails if e in person.emails}
            | {p for p in unit.phones if p in person.phones}
            | ({person.user_id} & set(USER_ID.findall(unit.text)))
            | ({m.lower() for m in HASH64.findall(unit.text)} & set(person.hashes)))


# --------------------------------------------------------------------------- comparison
@dataclass
class CaseResult:
    """Comparison counts for one case in one family."""

    case_id: str
    files: list[str] = field(default_factory=list)
    checked: int = 0
    matched: int = 0
    missed: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    labels: set[str] = field(default_factory=set)


def _check_unit(unit: Unit, observations: list[Observation], expected_ids: set[str],
                companion: bool, peer_tokens: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Field mismatches between one raw unit and its observations ([] when they agree)."""
    problems: list[str] = []
    if unit.kind == "pdf_page":
        named = sorted(set(RESOURCE.findall(unit.text))) or [None]
        got = sorted({o.resource_id for o in observations}, key=str)
        if got != sorted(named, key=str):
            problems.append("resource_id")
    else:
        if len(observations) != 1:
            return [f"{len(observations)} observations"]
        if observations[0].resource_id != unit.declared_resource:
            problems.append("resource_id")
    for obs in observations:
        if unit.time is not None and obs.record_time != unit.time:
            problems.append("record_time")
        elif unit.time is None and obs.record_time is not None and \
                obs.record_time not in unit.text and obs.record_time not in unit.context_times:
            problems.append("record_time")
        if obs.trace_id != unit.trace and unit.kind == "line":
            problems.append("trace_id")
        tokens = unit.tokens
        record = _comparable(obs.record_identifiers)
        lookup = _comparable(obs.lookup_identifiers)
        if record | (lookup & tokens) != tokens:
            problems.append("identifiers")
        if (lookup - tokens) - peer_tokens:
            problems.append("lookup_identifiers (not on the trace)")
        if companion and not (expected_ids & lookup):
            problems.append("lookup_identifiers")
    return sorted(set(problems))


def compare_file(file_id: str, units: list[Unit], person: Person, index: EvidenceIndex,
                 result: CaseResult) -> None:
    """Compare every person unit and same-trace companion unit of one file."""
    by_locator: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for obs in index.files[file_id].observations:
        by_locator[(obs.locator.kind, obs.locator.ref)].append(obs)
    person_units = {u.ref: u for u in units if hits(u, person)}
    trace_units: dict[str, list[Unit]] = defaultdict(list)
    for unit in units:
        if unit.trace:
            trace_units[unit.trace].append(unit)
    trace_ids: dict[str, set[str]] = defaultdict(set)
    for unit in person_units.values():
        result.labels.update(hits(unit, person))
        if unit.trace:
            trace_ids[unit.trace] |= _person_values(unit, person)
    for unit in units:
        companion = unit.ref not in person_units
        if companion and not (unit.trace in trace_ids and RESOURCE.search(unit.text)):
            continue
        if companion:
            assert unit.trace is not None  # the `continue` above keeps only companions whose trace is known
            expected = trace_ids[unit.trace]
        else:
            expected = _person_values(unit, person)
        result.checked += 1
        observations = by_locator.get((unit.kind, unit.ref), [])
        if not observations:
            result.missed.append(f"{file_id} {unit.ref}")
            continue
        peers: set[str] = set()
        for other in trace_units.get(unit.trace or "", []):
            if other is not unit:
                peers |= other.tokens
        problems = _check_unit(unit, observations, expected, companion, peers)
        if problems:
            result.mismatched.append(f"{file_id} {unit.ref}: {', '.join(problems)}")
        else:
            result.matched += 1


# --------------------------------------------------------------------------- groups
@dataclass
class Group:
    """One family under check and its files."""

    name: str
    registry_family: str
    files: list[str]
    note: str = ""


def build_groups(index: EvidenceIndex) -> list[Group]:
    """Unseen research families plus registry families the research table does not name."""
    groups: list[Group] = []
    for name in UNSEEN_RESEARCH:
        files = [fp.file_id for fp in index.files.values()
                 if Path(fp.path).stem.startswith(name + "_") or Path(fp.path).stem == name]
        families = {index.files[f].family for f in files}
        note = "" if families == {RESEARCH_FAMILIES[name]} else f"registry families seen: {sorted(map(str, families))}"
        groups.append(Group(name, RESEARCH_FAMILIES[name], files, note))
    named = set(RESEARCH_FAMILIES.values())
    found = sorted({fp.family for fp in index.files.values() if fp.family})
    for family in found:
        if family not in named:
            files = [fp.file_id for fp in index.files.values() if fp.family == family]
            groups.append(Group(f"(registry) {family}", family, files))
    return groups


def sha(case_id: str) -> str:
    """sha256 hex digest of a case ID."""
    return hashlib.sha256(case_id.encode("utf-8")).hexdigest()


def run_group(group: Group, index: EvidenceIndex, people: dict[str, Person],
              cases: dict[str, str]) -> tuple[int, list[CaseResult]]:
    """Select up to 3 cases for a group and compare them; returns (candidates, results)."""
    units = {fid: raw_units(DATASET / index.files[fid].path) for fid in group.files}
    appears: dict[str, list[str]] = {}
    for case_id, user in cases.items():
        person = people[user]
        present = [fid for fid in group.files if any(hits(u, person) for u in units[fid])]
        if present:
            appears[case_id] = present
    chosen = sorted(appears, key=sha)[:CASES_PER_FAMILY]
    results = []
    for case_id in chosen:
        result = CaseResult(case_id, appears[case_id])
        for fid in appears[case_id]:
            compare_file(fid, units[fid], people[cases[case_id]], index, result)
        results.append(result)
    return len(appears), results


# --------------------------------------------------------------------------- report
def render(rows: list[tuple[Group, int, list[CaseResult]]], index: EvidenceIndex) -> str:
    """The markdown report."""
    out = [
        "# Parser raw-file check (T13, INTERFACES.md section 6)",
        "",
        "Generated by `code/tests/evidence/raw_check.py`; do not edit by hand.",
        "",
        "- Families: the never-DEV-primary families of `research/16_test_coverage.md` section 3.2 "
        "(files picked by that table's file-name stem), plus registry families the table does not name.",
        "- Person search: the request's `user_id`, every email and phone the user has had (current and old, "
        "from `user_identities.csv` and `user_audit_log.csv`), the sha256 of each of those emails, and the "
        "resource IDs a `system_activity.csv` row links to the `user_id` (T68).",
        "- Cases: the 3 test cases with the lowest sha256(case_id) whose person appears in a file of the family.",
        "- A raw unit is checked when it holds a person identifier, or carries a resource ID on the same trace "
        "as such a unit (\"companion\"). It must map to an observation with the same locator, record time, "
        "resource ID and trace. Identifiers are compared for equality (T68): the observation's record identifiers "
        "plus its lookups that appear in the unit must equal the unit's identifier tokens (emails, known phones, "
        "user IDs, 64-hex hashes); lookups borrowed from the trace must appear in another unit on the same trace; "
        "a companion must carry the trace's person identifier among `lookup_identifiers`.",
        "- Identifier values are not printed; only their kind and whether they are current or old.",
        "",
    ]
    total = [0, 0, 0, 0]
    out += ["## Summary", "",
            "| Family | Registry family | Files | Candidate cases | Selected | Units checked "
            "| Matched | Missed | Mismatched |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for group, candidates, results in rows:
        checked = sum(r.checked for r in results)
        matched = sum(r.matched for r in results)
        missed = sum(len(r.missed) for r in results)
        mism = sum(len(r.mismatched) for r in results)
        total = [total[0] + checked, total[1] + matched, total[2] + missed, total[3] + mism]
        out.append(f"| {group.name} | {group.registry_family} | {len(group.files)} | {candidates} | "
                   f"{len(results)} | {checked} | {matched} | {missed} | {mism} |")
    out += ["", f"**Total:** {total[0]} units checked, {total[1]} matched, {total[2]} missed, "
                f"{total[3]} mismatched.", ""]
    out += ["## Per case", ""]
    for group, candidates, results in rows:
        out.append(f"### {group.name} ({group.registry_family})")
        out.append("")
        if group.note:
            out.append(f"- Note: {group.note}")
        statuses = sorted({index.files[f].status for f in group.files})
        if statuses == ["NEEDS_MODEL"]:
            out += ["- Every file of this family is NEEDS_MODEL (no text to compare); "
                    "case search skipped, 0 cases.", ""]
            continue
        if not results:
            out += [f"- No test case's person appears in these files ({candidates} candidates).", ""]
            continue
        out += ["| Case | sha256 prefix | Files | Checked | Matched | Missed | Mismatched | Identifiers matched |",
                "|---|---|---|---:|---:|---:|---:|---|"]
        for r in results:
            out.append(f"| {r.case_id} | {sha(r.case_id)[:10]} | {', '.join(r.files)} | {r.checked} | "
                       f"{r.matched} | {len(r.missed)} | {len(r.mismatched)} | {', '.join(sorted(r.labels))} |")
        problems = [(r.case_id, p) for r in results for p in r.missed + r.mismatched]
        out.append("")
        if problems:
            out += [f"- {case}: {p}" for case, p in problems]
            out.append("")
    return "\n".join(out) + "\n"


def seal_collisions(index: EvidenceIndex) -> tuple[int, int]:
    """(integrity_seal values in the raw evidence, how many equal a known email hash)."""
    seals: list[str] = []
    for fp in index.files.values():
        path = DATASET / fp.path
        if path.suffix in (".log", ".txt", ".sql", ".json"):
            seals += [m.lower() for m in SEAL.findall(path.read_text(encoding="utf-8"))]
    return len(seals), sum(1 for v in seals if v in KNOWN_HASHES)


def main() -> int:
    """Run the check and write the report; exit 1 when any unit is missed or mismatched."""
    index = parse_all(DATASET)
    people, email_to_user = load_people()
    cases = load_cases(email_to_user)
    rows: list[tuple[Group, int, list[CaseResult]]] = []
    for group in build_groups(index):
        if all(index.files[f].status == "NEEDS_MODEL" for f in group.files):
            rows.append((group, 0, []))
            continue
        candidates, results = run_group(group, index, people, cases)
        rows.append((group, candidates, results))
    seals, collisions = seal_collisions(index)
    REPORT.write_text(render(rows, index) + f"\n## Integrity seals (T75)\n\n- {seals} `integrity_seal` "
                      f"values scanned; {collisions} equal a known email hash (must be 0, or the 64-hex "
                      f"restriction could hide a real link).\n", encoding="utf-8")
    bad = sum(len(r.missed) + len(r.mismatched) for _, _, results in rows for r in results) + collisions
    print(f"wrote {REPORT}; problems: {bad}; integrity seals scanned: {seals}, "
          f"equal to a known email hash: {collisions}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
