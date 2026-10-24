"""Shared helpers for the evidence tests: fixture parsing and the cached real-data parse."""
from __future__ import annotations

import functools
import unittest
from pathlib import Path
from typing import Iterable

from deletion_audit.evidence import EvidenceIndex, FileParse, parse_all, parse_file
from deletion_audit.evidence.model import FileRef, Identifier, Observation

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET = REPO_ROOT / "dataset"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_CAPTURED_AT = "2026-06-01T00:00:00Z"


def fixture_ref(name: str, file_id: str = "fx_01") -> FileRef:
    """A FileRef for a file in the fixtures directory."""
    return FileRef(file_id=file_id, path=name, origin="fixture", captured_at=FIXTURE_CAPTURED_AT)


def parse_fixture(name: str) -> FileParse:
    """Parse one fixture file."""
    return parse_file(fixture_ref(name), FIXTURES)


@functools.lru_cache(maxsize=None)
def real_index() -> EvidenceIndex:
    """parse_all over the real dataset, computed once per test run."""
    return parse_all(DATASET)


def id_set(identifiers: Iterable[Identifier]) -> set[tuple[str, str, str]]:
    """Identifiers as comparable (kind, value, field) triples."""
    return {(i.kind, i.value, i.field) for i in identifiers}


def by_ref(fp: FileParse) -> dict[str, list[Observation]]:
    """Observations of one FileParse grouped by locator ref."""
    out: dict[str, list[Observation]] = {}
    for obs in fp.observations:
        out.setdefault(obs.locator.ref, []).append(obs)
    return out


def assert_real_family(case: unittest.TestCase, family: str, status: str = "OK") -> None:
    """Every real file of ``family`` parses with ``status``; OK files carry at least one
    observation or declared scope; at least one real file belongs to the family."""
    files = [fp for fp in real_index().files.values() if fp.family == family]
    case.assertTrue(files, f"no real file detected as {family}")
    for fp in files:
        with case.subTest(file_id=fp.file_id):
            case.assertEqual(fp.status, status, fp.detail)
            if status == "OK":
                case.assertTrue(fp.observations or fp.scopes)
