"""Which evidence file a case cites (research/15 R14, R15).

* **R14 one file per case**: F is the latest file (manifest ``captured_at``) captured at or before
  ``audit_at`` that holds a record linked to the person, at any line time, or a record of a
  resource a catalog row at or before ``audit_at`` ties to the person. Ties on ``captured_at``
  go to the later manifest row. Basis: DEV 22/22 cited file equal to gold (20 by this rule).
* **R14 fallback**: with no such file, the latest pre-audit file holding any ``account_service``
  record (2 hand-built DEV cases; DEV cannot separate this from its alternative forms, G2 U5).
* **Finding citation**: a finding cites F when F shows the violating state, else the latest
  pre-audit file that shows it, else F (research/15 R15; 29/29 DEV findings cite).
* Nothing captured after ``audit_at`` is ever cited (G1 F21; T42 "always wins").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .. import timeutil
from ..discovery.links import Link
from ..evidence.model import Observation
from .model import CitationPlan


def latest_file(
    file_ids: Iterable[str], file_captured: Mapping[str, str], manifest_pos: Mapping[str, int], audit_at: str
) -> str | None:
    """The latest file captured at or before ``audit_at``; a time tie goes to the later manifest row."""
    ok = [f for f in set(file_ids) if f in file_captured and timeutil.le(file_captured[f], audit_at)]
    if not ok:
        return None
    return max(ok, key=lambda f: (timeutil.parse(file_captured[f]), manifest_pos[f]))


def choose_citation(
    links: Sequence[Link],
    audit_at: str,
    *,
    file_captured: Mapping[str, str],
    manifest_pos: Mapping[str, int],
    owned_observations: Iterable[Observation],
    account_files: Iterable[str],
) -> CitationPlan:
    """F for one case (module docstring).

    ``owned_observations`` are records of resources catalog-linked to the person at or before
    ``audit_at``; ``account_files`` are files holding any ``account_service`` record.
    """
    files = {lk.file_id for lk in links if lk.file_id and lk.resource_id}
    files |= {o.file_id for o in owned_observations}
    f = latest_file(files, file_captured, manifest_pos, audit_at)
    if f is not None:
        return CitationPlan(f, "R14_linked")
    f = latest_file(account_files, file_captured, manifest_pos, audit_at)
    if f is not None:
        return CitationPlan(f, "R14_fallback_same_system")
    return CitationPlan(None, "none")


def finding_citation(
    case_file: str | None,
    violating_files: Iterable[str],
    file_captured: Mapping[str, str],
    manifest_pos: Mapping[str, int],
    audit_at: str,
) -> str:
    """The evidence a FINDING step cites (module docstring); ``""`` only when nothing is citable."""
    vf = [f for f in set(violating_files) if f in file_captured and timeutil.le(file_captured[f], audit_at)]
    if case_file is not None and case_file in vf:
        return case_file
    latest = latest_file(vf, file_captured, manifest_pos, audit_at)
    if latest is not None:
        return latest
    return case_file or ""
