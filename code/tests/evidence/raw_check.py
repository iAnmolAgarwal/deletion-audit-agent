"""T13 raw-file comparison (notes/INTERFACES.md section 6), written to notes/parser_raw_check.md.

Run from the repo root: ``python3 code/tests/evidence/raw_check.py``.

Method:

* Families checked: the families ``research/16_test_coverage.md`` section 3.2 marks as never
  a DEV primary (selected by the file-name stem that table uses), plus every registry family
  the table does not name.
* A person's identifiers (test tooling only): the request email resolves to a ``user_id``
  through current emails in ``user_identities.csv`` and old or new emails in
  ``user_audit_log.csv``; the person's identifiers are then every email and phone that user
  has had in either file.
* Per family, the 3 test cases with the lowest ``sha256(case_id)`` among those whose person
  appears in a file of the family are selected.
* Raw units (lines, SQL ``INSERT`` rows, JSON records, PDF pages) are enumerated here with
  their own regular expressions, not with the parsers. Each unit that holds a person
  identifier, and each unit carrying a resource ID on the same trace, must map to an
  observation with the same locator, record time, resource ID, identifiers and trace.

The report names case IDs, locators and identifier kinds, never identifier values.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from deletion_audit.evidence import EvidenceIndex, parse_all  # noqa: E402
from deletion_audit.evidence.model import Observation  # noqa: E402
from deletion_audit.inputs import load_audit_log, load_identities  # noqa: E402

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
RESOURCE = re.compile(r"\b(?:account|search|analytics|support|export|data_flow|backup|audit_record|"
                      r"tombstone|legal_hold)_\d+\b")
DECLARED_RESOURCE = re.compile(r"resource_id\\?\"?\s*[:=]\s*\\?\"?([a-z_]+_\d+)")
SQL_INSERT = re.compile(r"^INSERT INTO \"?(\w+)\"? VALUES\s*\('([^']*)'")
LOG_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ")
HANDOVER_TIME = re.compile(r"^- (\S+) \|")


# --------------------------------------------------------------------------- people
@dataclass
class Person:
    """Every email and phone one user has had, each with its label."""

    user_id: str
    emails: dict[str, str] = field(default_factory=dict)   # lower-case email -> label
    phones: dict[str, str] = field(default_factory=dict)   # digits -> label


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
    for row in load_audit_log(DATASET):
        person = people.setdefault(row.user_id, Person(row.user_id))
        for ident in (row.old_identifier, row.new_identifier):
            if ident is None or ident.kind not in ("email", "phone"):
                continue
            if ident.kind == "email":
                person.emails.setdefault(ident.value, "email (old)")
                email_to_user.setdefault(ident.value, row.user_id)
            else:
                person.phones.setdefault(_digits(ident.raw), "phone (old)")
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
    return found


def _ident_values(obs: Observation, lookup_only: bool = False) -> set[str]:
    """Comparable identifier values of an observation (emails lower, phones digits)."""
    idents = obs.lookup_identifiers if lookup_only else obs.record_identifiers | obs.lookup_identifiers
    return {_digits(i.value) if i.kind == "phone" else i.value for i in idents}


def _person_values(unit: Unit, person: Person) -> set[str]:
    """The person's identifier values present in a unit, in comparable form."""
    return {e for e in unit.emails if e in person.emails} | \
           {p for p in unit.phones if p in person.phones}


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
                companion: bool) -> list[str]:
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
        values = _ident_values(obs, lookup_only=companion)
        if companion and not (expected_ids & values):
            problems.append("lookup_identifiers")
        if not companion and not expected_ids <= values:
            problems.append("identifiers")
    return sorted(set(problems))


def compare_file(file_id: str, units: list[Unit], person: Person, index: EvidenceIndex,
                 result: CaseResult) -> None:
    """Compare every person unit and same-trace companion unit of one file."""
    by_locator: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for obs in index.files[file_id].observations:
        by_locator[(obs.locator.kind, obs.locator.ref)].append(obs)
    person_units = {u.ref: u for u in units if hits(u, person)}
    trace_ids: dict[str, set[str]] = defaultdict(set)
    for unit in person_units.values():
        result.labels.update(hits(unit, person))
        if unit.trace:
            trace_ids[unit.trace] |= _person_values(unit, person)
    for unit in units:
        companion = unit.ref not in person_units
        if companion and not (unit.trace in trace_ids and RESOURCE.search(unit.text)):
            continue
        expected = trace_ids[unit.trace] if companion else _person_values(unit, person)
        result.checked += 1
        observations = by_locator.get((unit.kind, unit.ref), [])
        if not observations:
            result.missed.append(f"{file_id} {unit.ref}")
            continue
        problems = _check_unit(unit, observations, expected, companion)
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
        "- Person identifiers: every email and phone the request's user has had, current and old, "
        "from `user_identities.csv` and `user_audit_log.csv`.",
        "- Cases: the 3 test cases with the lowest sha256(case_id) whose person appears in a file of the family.",
        "- A raw unit is checked when it holds a person identifier, or carries a resource ID on the same trace "
        "as such a unit (\"companion\"). It must map to an observation with the same locator, record time, "
        "resource ID, identifiers (companions: the trace's person identifier among `lookup_identifiers`) and trace.",
        "- Identifier values are not printed; only their kind and whether they are current or old.",
        "",
    ]
    total = [0, 0, 0, 0]
    out += ["## Summary", "",
            "| Family | Registry family | Files | Candidate cases | Selected | Units checked | Matched | Missed | Mismatched |",
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


def main() -> int:
    """Run the check and write the report; exit 1 when any unit is missed or mismatched."""
    index = parse_all(DATASET)
    people, email_to_user = load_people()
    cases = load_cases(email_to_user)
    rows = []
    for group in build_groups(index):
        if all(index.files[f].status == "NEEDS_MODEL" for f in group.files):
            rows.append((group, 0, []))
            continue
        candidates, results = run_group(group, index, people, cases)
        rows.append((group, candidates, results))
    REPORT.write_text(render(rows, index), encoding="utf-8")
    bad = sum(len(r.missed) + len(r.mismatched) for _, _, results in rows for r in results)
    print(f"wrote {REPORT}; problems: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
