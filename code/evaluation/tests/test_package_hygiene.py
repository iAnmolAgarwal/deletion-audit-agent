"""No module in the evaluation package may share a name with a stdlib module.

Regression test for a G4 bug: ``evaluation/numbers.py`` shadowed the stdlib ``numbers``
when a script in this folder ran, which broke ``pdfplumber`` inside the prototype; the
prototype then skipped the one DEV PDF and produced a wrong case_07.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]


class TestNoStdlibShadowing(unittest.TestCase):
    def test_module_names(self) -> None:
        names = {p.stem for p in PKG.glob("*.py")} | {p.stem for p in (PKG / "tests").glob("*.py")}
        self.assertEqual(sorted(names & set(sys.stdlib_module_names)), [])


if __name__ == "__main__":
    unittest.main()
