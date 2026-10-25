#!/usr/bin/env python3
"""Check log.txt against the entry format in ../CLAUDE.md section 1.

Developer decision T41 (turn 2026-10-25T02:35:05+05:30). Runs from the pre-commit hook,
next to scripts/secret_scan.sh, on the staged copy of log.txt.

Blocking checks, one code each:
  H1  header is "## [YYYY-MM-DDTHH:MM:SS+05:30] title"
  H2  title is at most 80 characters
  S1  the four sections are present, in order
  C1  Context has tool, model, agent_type, parent_agent, worktree, branch, repo_root
  C2  a subagent entry (parent_agent=main) has directed_by
  T1  timestamps never go backwards

Warning only (never blocks): an Agent Response Summary longer than 5 sentences, for
entries at or after SUMMARY_RULE_FROM.

log.txt is append-only, so a defect is never rewritten. A known defect is listed in
EXCEPTIONS with the correction note that covers it; an exception that no longer matches
anything is itself reported, so the list cannot go stale. A header-shaped line quoted
inside an entry is listed in QUOTED_HEADERS by the exact line text and the stamp of the
entry it sits in (T64); it is read as that entry's body text, so it neither splits the
entry nor takes part in the time-order check.

Usage: python3 scripts/check_log.py [--staged] [path]
Exit status: 0 = pass, 1 = a blocking check failed, 2 = the log could not be read.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "log.txt"

# A header line starts with "## " followed by a timestamp, with or without brackets.
# Lines such as "## Blocked on me" inside a verbatim prompt are not headers.
HEADER_ANY = re.compile(r"^## \[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2}|Z))\]? ?(.*)$")
HEADER_OK = re.compile(r"^## \[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30)\] (\S.*)$")
TITLE_MAX = 80

USER_PROMPT = "User Prompt (verbatim, secrets redacted):"
SUMMARY = "Agent Response Summary:"
ACTIONS = "Actions:"
CONTEXT = "Context:"
CONTEXT_KEYS = ("tool", "model", "agent_type", "parent_agent", "worktree", "branch", "repo_root")

SUMMARY_RULE_FROM = "2026-10-25T02:35:05+05:30"
SUMMARY_MAX_SENTENCES = 5
SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z(\"'*`\[]|\s*$)")

NOTE_0005 = "correction note in the 2026-10-25T00:05:00+05:30 entry"
NOTE_0132 = "correction note in the 2026-10-25T01:32:51+05:30 entry (T18, confirmed by T23)"
NOTE_0237 = "correction note in the 2026-10-25T02:37:47+05:30 entry"
NOTE_0244 = "correction note in the 2026-10-25T02:44:55+05:30 entry"
NOTE_0316 = "correction note in the 2026-10-25T03:16:49+05:30 entry"
NOTE_0553 = "correction note in the 2026-10-25T05:53:29+05:30 entry: written by a session-summary process"
NOTE_1205 = "correction note in the 2026-10-25T12:05:40+05:30 entry"

# A header stamped wrongly is ordered by the time its correction note gives, so one bad
# stamp does not make every later entry look out of order. stamp -> (effective time, note)
STAMP_OVERRIDES: dict[str, tuple[str, str]] = {
    "2026-10-25T00:20:00+05:30": ("2026-10-25T00:04:00+05:30",
                                  NOTE_0005 + ": header mis-stamped, written at about 00:04"),
}

# (stamp of the entry it sits in, exact line text) -> the correction note that covers it.
# The line is read as body text of that entry (T64).
QUOTED_HEADERS: dict[tuple[str, str], str] = {
    ("2026-10-25T03:16:15+05:30",
     "## [2026-10-25T03:40:00+05:30] G4 fix continued: no-resource-ID state, coherence messages"):
        NOTE_0316 + ": an example header quoted from main's brief",
}

# (check code, header timestamp as written) -> the correction note that covers it.
EXCEPTIONS: dict[tuple[str, str], str] = {
    ("H1", "2026-10-25T01:09:13+0530"): NOTE_0132,
    ("H1", "2026-10-25T01:47:03+05:30"): NOTE_0237,
    ("H1", "2026-10-25T02:43:14+05:30"): NOTE_0244,
    ("H1", "2026-10-25T00:14:32Z"): NOTE_0553,
    ("H1", "2026-10-25T05:44:36+0530"): NOTE_0553,
    ("H2", "2026-10-25T12:05:19+05:30"): NOTE_1205,
    **{("H2", stamp): NOTE_0237 for stamp in (
        "2026-10-25T00:13:30+05:30", "2026-10-25T00:14:42+05:30", "2026-10-25T01:37:06+05:30",
        "2026-10-25T01:41:22+05:30", "2026-10-25T01:49:56+05:30", "2026-10-25T01:55:30+05:30",
        "2026-10-25T02:03:51+05:30", "2026-10-25T02:17:45+05:30", "2026-10-25T02:21:36+05:30",
        "2026-10-25T02:32:14+05:30")},
}


@dataclass
class Entry:
    """One log entry: its header line number, raw timestamp, title and body lines, plus
    any listed quoted header lines read as body (line number, text)."""

    line_no: int
    stamp: str
    title: str
    header: str
    body: list[str]
    quoted: list[tuple[int, str]] = field(default_factory=list)


def read_log(staged: bool, path: Path) -> str:
    """Return the log text: the staged copy (git index) or the file on disk."""
    if staged:
        out = subprocess.run(["git", "-C", str(REPO), "show", ":log.txt"],
                             capture_output=True, text=True, check=False)
        if out.returncode == 0:
            return out.stdout
    return path.read_text(encoding="utf-8")


def split_entries(text: str) -> list[Entry]:
    """Split the log into entries at header lines (a timestamp right after '## '). A line
    listed in QUOTED_HEADERS for the entry it sits in stays in that entry's body."""
    entries: list[Entry] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = HEADER_ANY.match(line)
        if m and entries and (entries[-1].stamp, line) in QUOTED_HEADERS:
            entries[-1].body.append(line)
            entries[-1].quoted.append((i, line))
        elif m:
            entries.append(Entry(i, m.group(1), m.group(2), line, []))
        elif entries:
            entries[-1].body.append(line)
    return entries


def parse_stamp(stamp: str) -> datetime:
    """Parse a header timestamp, accepting the known '+0530' and UTC 'Z' defect forms."""
    if re.search(r"[+-]\d{4}$", stamp):
        stamp = stamp[:-2] + ":" + stamp[-2:]
    return datetime.fromisoformat(stamp)


def last_index(lines: list[str], marker: str, end: int) -> int:
    """Index of the last line equal to marker before end, or -1."""
    for i in range(end - 1, -1, -1):
        if lines[i].strip() == marker:
            return i
    return -1


def check_entry(e: Entry) -> tuple[list[str], list[str]]:
    """Return (failed check codes with detail, warnings) for one entry."""
    fails: list[str] = []
    warns: list[str] = []
    m = HEADER_OK.match(e.header)
    if not m:
        fails.append("H1 header is not '## [ISO +05:30] title'")
    if len(e.title) > TITLE_MAX:
        fails.append(f"H2 title is {len(e.title)} characters (max {TITLE_MAX})")

    # Section markers are taken from the end, so a verbatim prompt that quotes them cannot fool the check.
    b = e.body
    i_ctx = last_index(b, CONTEXT, len(b))
    i_act = last_index(b, ACTIONS, i_ctx) if i_ctx >= 0 else -1
    i_sum = last_index(b, SUMMARY, i_act) if i_act >= 0 else -1
    i_up = -1
    if i_sum >= 0:
        i_up = next((i for i in range(i_sum) if b[i].strip() == USER_PROMPT), -1)
    if min(i_ctx, i_act, i_sum, i_up) < 0:
        fails.append("S1 missing or out-of-order section(s)")
        return fails, warns

    ctx: dict[str, str] = {}
    for line in b[i_ctx + 1:]:
        if "=" in line and not line.startswith(" "):
            k, v = line.split("=", 1)
            ctx[k.strip()] = v.strip()
    missing = [k for k in CONTEXT_KEYS if not ctx.get(k)]
    if missing:
        fails.append("C1 Context missing " + ", ".join(missing))
    if ctx.get("parent_agent") == "main" and not ctx.get("directed_by"):
        fails.append("C2 subagent entry without directed_by")

    if m and parse_stamp(e.stamp) >= parse_stamp(SUMMARY_RULE_FROM):
        summary = " ".join(x.strip() for x in b[i_sum + 1:i_act] if x.strip())
        n = len(SENTENCE_END.findall(summary))
        if n > SUMMARY_MAX_SENTENCES:
            warns.append(f"summary has about {n} sentences (format: 2-{SUMMARY_MAX_SENTENCES})")
    return fails, warns


def main(argv: list[str]) -> int:
    """Run every check and print one line per finding; return the exit status."""
    staged = "--staged" in argv
    paths = [a for a in argv if not a.startswith("--")]
    path = Path(paths[0]) if paths else LOG
    try:
        entries = split_entries(read_log(staged, path))
    except OSError as exc:
        print(f"check-log: cannot read the log: {exc}")
        return 2

    blocking: list[str] = []
    excused: list[str] = []
    used: set[tuple[str, str]] = set()
    used_quoted: set[tuple[str, str]] = set()
    warnings: list[str] = []
    prev = None
    for e in entries:
        for n, line in e.quoted:
            used_quoted.add((e.stamp, line))
            excused.append(f"line {n} (inside [{e.stamp}]) quoted header read as body -> "
                           f"{QUOTED_HEADERS[(e.stamp, line)]}")
        fails, warns = check_entry(e)
        try:
            when = parse_stamp(e.stamp)
            if e.stamp in STAMP_OVERRIDES:
                effective, note = STAMP_OVERRIDES[e.stamp]
                when = parse_stamp(effective)
                excused.append(f"line {e.line_no} [{e.stamp}] T1 ordered as {effective} -> {note}")
            if prev is not None and when < prev:
                fails.append("T1 timestamp goes backwards")
            prev = when if prev is None or when > prev else prev
        except ValueError:
            fails.append("T1 unparseable timestamp")
        for f in fails:
            key = (f[:2], e.stamp)
            where = f"line {e.line_no} [{e.stamp}]"
            if key in EXCEPTIONS:
                used.add(key)
                excused.append(f"{where} {f} -> {EXCEPTIONS[key]}")
            else:
                blocking.append(f"{where} {f}")
        warnings.extend(f"line {e.line_no} [{e.stamp}] {w}" for w in warns)

    for key in sorted(set(EXCEPTIONS) - used):
        blocking.append(f"stale exception {key}: it matches no defect")
    for key in sorted(set(QUOTED_HEADERS) - used_quoted):
        blocking.append(f"stale quoted-header exception {key}: it matches no line")

    print(f"check-log: {len(entries)} entries, {len(blocking)} blocking, "
          f"{len(excused)} known defects (excused), {len(warnings)} warnings")
    for line in excused:
        print("  excused  " + line)
    for line in warnings:
        print("  warning  " + line)
    for line in blocking:
        print("  FAIL     " + line)
    print("check-log: " + ("PASS" if not blocking else "FAIL"))
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
