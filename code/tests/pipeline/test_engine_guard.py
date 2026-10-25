"""The engine's manifest-path containment check and its fail-closed reason order."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from deletion_audit.engine import (
    PNG_SIGNATURE,
    ResourceEvaluation,
    _failures,
    dataset_path,
    fail_closed_reason,
)
from deletion_audit.record import FailedClosedReason


def _ctx(root: Path, entries: list[tuple[str, str, str]]) -> Any:
    """A minimal context: manifest entries (file_id, path, parse status), none read by vision."""
    manifest = tuple(SimpleNamespace(file_id=f, path=p, captured_at="2026-05-01T00:00:00Z") for f, p, _ in entries)
    files = {f: SimpleNamespace(ok=False, status=s) for f, _, s in entries}
    return SimpleNamespace(
        dataset_dir=root, manifest=manifest, index=SimpleNamespace(files=files), vision_read=frozenset()
    )


def _evaluation(outcome: str, reasons: set[str]) -> ResourceEvaluation:
    finding = SimpleNamespace(decision=SimpleNamespace(outcome=outcome))
    return ResourceEvaluation(cast(Any, finding), frozenset(), cast(Any, frozenset(reasons)))


class TestDatasetPath(unittest.TestCase):
    """A manifest path is untrusted: the engine opens or tests only paths inside the dataset."""

    def test_inside_and_outside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            root.mkdir()
            self.assertEqual(dataset_path(root, "evidence/a.png"), (root / "evidence/a.png").resolve())
            self.assertIsNone(dataset_path(root, "../outside.png"))
            self.assertIsNone(dataset_path(root, "/etc/hosts"))
            self.assertIsNone(dataset_path(root, "."))

    def test_outside_png_is_neither_read_nor_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset"
            root.mkdir()
            (Path(tmp) / "outside.png").write_bytes(PNG_SIGNATURE + b"rest")
            (root / "inside.png").write_bytes(PNG_SIGNATURE + b"rest")
            ctx = _ctx(
                root,
                [
                    ("ev_out", "../outside.png", "NEEDS_MODEL"),
                    ("ev_in", "inside.png", "NEEDS_MODEL"),
                    ("ev_gone", "gone.csv", "ERROR"),
                    ("ev_escape", "../gone.csv", "ERROR"),
                ],
            )
            got = {f.file_id: f for f in _failures(ctx, {f: "2026-05-01T00:00:00Z" for f in ctx.index.files})}
            self.assertFalse(got["ev_out"].png)  # outside the dataset: its bytes are never read
            self.assertTrue(got["ev_in"].png)
            self.assertTrue(got["ev_gone"].missing)
            self.assertFalse(got["ev_escape"].missing)  # never tested on disk; stays a parse error


class TestFailClosedReason(unittest.TestCase):
    """The gravest reason decides the row (engine module docstring)."""

    def reason(self, evaluations: list[ResourceEvaluation], deps: frozenset[str] = frozenset(),
               kinds: dict[str, FailedClosedReason] | None = None, resolved: bool = True) -> str | None:
        return fail_closed_reason(resolved, evaluations, deps, kinds or {})

    def test_order(self) -> None:
        every = {"POST_AUDIT_ONLY_FINDING", "NO_CATEGORY_RULE", "IMAGE_OMITS_CATALOG_RECORD",
                 "IMAGE_STATE_NOT_SHOWN", "UNINTERPRETED_RECORD", "OWN_KEY_CONFLICT"}
        ev = [_evaluation("FINDING", every)]
        self.assertEqual(self.reason(ev, resolved=False), "IDENTITY_UNRESOLVED")
        self.assertEqual(self.reason(ev, frozenset({"f"}), {"f": "MISSING_EVIDENCE_FILE"}), "OWN_KEY_CONFLICT")
        every.discard("OWN_KEY_CONFLICT")
        ev = [_evaluation("FINDING", every)]
        kinds: dict[str, FailedClosedReason] = {"a": "UNPARSED_DEPENDENCY", "b": "EVIDENCE_PARSE_ERROR"}
        self.assertEqual(self.reason(ev, frozenset({"a", "b"}), kinds), "EVIDENCE_PARSE_ERROR")
        self.assertEqual(self.reason(ev, frozenset({"z"})), "UNPARSED_DEPENDENCY")
        for expected in ("POST_AUDIT_ONLY_FINDING", "NO_CATEGORY_RULE", "IMAGE_OMITS_CATALOG_RECORD",
                         "IMAGE_STATE_NOT_SHOWN", "UNINTERPRETED_RECORD"):
            self.assertEqual(self.reason([_evaluation("FINDING", every)]), expected)
            every.discard(expected)

    def test_nothing_found_and_clean(self) -> None:
        self.assertEqual(self.reason([]), "NOTHING_FOUND")
        self.assertEqual(self.reason([_evaluation("NO_STEP", set())]), "NOTHING_FOUND")
        self.assertIsNone(self.reason([_evaluation("COMPLIANT", set()), _evaluation("NO_STEP", set())]))


if __name__ == "__main__":
    unittest.main()
