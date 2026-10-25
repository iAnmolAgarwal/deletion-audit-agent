"""Code hygiene: no case IDs outside the allowed files (T71 Q8), docstrings, no stdlib shadowing,
no expected values read from run or cache directories."""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[2]
PACKAGE = CODE / "deletion_audit"
G5_PACKAGES = ("identity", "discovery", "state", "policy", "steps", "validate")
G5_MODULES = (
    "config.py",
    "timeutil.py",
    "engine.py",
    "record.py",
    "artifacts.py",
    "pipeline.py",
    "__main__.py",
    "inputs/requests.py",
)
G5_TEST_DIRS = ("identity", "discovery", "state", "policy", "steps", "validate", "pipeline", "hygiene")
CASE_ID = re.compile(r"\bcase_\d+\b")
ALLOWED = (CODE / "evaluation" / "split.py",)


def g5_modules() -> list[Path]:
    files = [PACKAGE / m for m in G5_MODULES]
    for pkg in G5_PACKAGES:
        files += sorted((PACKAGE / pkg).glob("*.py"))
    return files


class Hygiene(unittest.TestCase):
    """T71 Q8 and the code-structure rules."""

    def test_no_case_ids_in_pipeline_source(self) -> None:
        """No case ID anywhere under code/ (comments, docstrings or data) except split.py and the evaluation tests."""
        bad = []
        for p in sorted(CODE.rglob("*.py")):
            if p in ALLOWED or (CODE / "evaluation" / "tests") in p.parents or p == Path(__file__).resolve():
                continue
            if CASE_ID.search(p.read_text(encoding="utf-8")):
                bad.append(str(p.relative_to(CODE)))
        self.assertEqual(bad, [])

    def test_core_modules_have_docstrings(self) -> None:
        missing = []
        for p in g5_modules() + sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            if not ast.get_docstring(tree):
                missing.append(f"{p.name}: module")
            if p in g5_modules():
                for node in tree.body:
                    if (
                        isinstance(node, (ast.FunctionDef, ast.ClassDef))
                        and not node.name.startswith("_")
                        and not ast.get_docstring(node)
                    ):
                        missing.append(f"{p.relative_to(PACKAGE)}: {node.name}")
        self.assertEqual(missing, [])

    def test_no_stdlib_shadowing(self) -> None:
        names = {p.stem for p in PACKAGE.rglob("*.py")} | {p.name for p in PACKAGE.rglob("*") if p.is_dir()}
        self.assertEqual(sorted((names - {"__init__", "__main__"}) & set(sys.stdlib_module_names)), [])

    def test_no_test_reads_runs_or_cache_as_expected(self) -> None:
        """No G5 test reads an expected value from runs/ or a cache directory (no snapshot tests)."""
        pattern = re.compile(r"""["'](?:runs|cache)/|/ ?["'](?:runs|cache)["']|REPO_ROOT\s*/\s*["']runs""")
        bad = []
        for d in G5_TEST_DIRS:
            for p in sorted((CODE / "tests" / d).glob("test_*.py")):
                if p == Path(__file__).resolve():
                    continue
                if pattern.search(p.read_text(encoding="utf-8")):
                    bad.append(p.name)
        self.assertEqual(bad, [])

    def test_engine_never_opens_gold(self) -> None:
        """No engine string literal names the gold file (T32: requests only); docstrings may say so."""
        bad = []
        for p in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            docs = {
                id(n.body[0].value)
                for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
                and n.body
                and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant)
            }
            for n in ast.walk(tree):
                if (
                    isinstance(n, ast.Constant)
                    and isinstance(n.value, str)
                    and id(n) not in docs
                    and "sample_output" in n.value
                ):
                    bad.append(str(p.relative_to(PACKAGE)))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
