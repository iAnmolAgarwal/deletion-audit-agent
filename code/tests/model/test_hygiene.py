"""Source hygiene for the model package: docstrings, no case IDs, no stdlib shadowing, no run reads."""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[2]
MODEL_PKG = CODE / "deletion_audit" / "model"
TEST_PKG = CODE / "tests" / "model"
ENV_FILE = re.compile(r"""(^|["'/\s])\.env\b""", re.MULTILINE)
CASE_ID = re.compile(r"case[_-]?\d", re.IGNORECASE)


class TestHygiene(unittest.TestCase):
    """Static checks over the package and its tests."""

    def test_every_module_class_and_function_has_a_docstring(self) -> None:
        """Every module, class and function (private ones too) in model/ has a docstring."""
        missing = []
        for path in sorted(MODEL_PKG.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if ast.get_docstring(tree) is None:
                missing.append(f"{path.name}: module")
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if ast.get_docstring(node) is None:
                        missing.append(f"{path.name}: {node.name}")
        self.assertEqual(missing, [])

    def test_no_case_ids_in_source(self) -> None:
        """No case ID pattern appears in the package or its tests."""
        hits = [p.name for d in (MODEL_PKG, TEST_PKG) for p in sorted(d.glob("*.py"))
                if CASE_ID.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])

    def test_no_stdlib_shadowing(self) -> None:
        """No module name in model/ or its tests is a stdlib module name."""
        names = {p.stem for p in MODEL_PKG.glob("*.py")} | {p.stem for p in TEST_PKG.glob("*.py")}
        self.assertEqual(sorted(names & set(sys.stdlib_module_names)), [])

    def test_no_test_reads_runs_or_cache_as_expected(self) -> None:
        """No model test names the repo's runs/ or cache/ folders or the dataset."""
        pattern = re.compile(r"""["'](runs|cache|dataset)/""")
        hits = [p.name for p in sorted(TEST_PKG.glob("*.py")) if pattern.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])

    def test_no_env_file_read(self) -> None:
        """The package never names a .env file."""
        hits = [p.name for p in sorted(MODEL_PKG.glob("*.py")) if ENV_FILE.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
