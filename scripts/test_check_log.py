"""Tests for scripts/check_log.py: each blocking check fires on a crafted entry.

Run: python3 -m unittest scripts/test_check_log.py
"""
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("check_log", Path(__file__).with_name("check_log.py"))
check_log = importlib.util.module_from_spec(_SPEC)
sys.modules["check_log"] = check_log  # dataclasses look their module up here
_SPEC.loader.exec_module(check_log)

CONTEXT_MAIN = """Context:
tool=Claude Code
model=claude-opus-5-5
agent_type=main
parent_agent=none
worktree=main
branch=main
repo_root=/repo
"""


def entry(header: str, context: str = CONTEXT_MAIN, summary: str = "One. Two.") -> str:
    """Build one log entry with the four sections."""
    return (f"{header}\n\nUser Prompt (verbatim, secrets redacted):\nhi\n\n"
            f"Agent Response Summary:\n{summary}\n\nActions:\n* x\n\n{context}\n")


class CheckLogTest(unittest.TestCase):
    """Each check code is exercised once; known-defect exceptions are switched off."""

    def run_on(self, text: str) -> tuple[int, str]:
        """Run main() on text written to a temp file, with no exceptions configured."""
        saved = (check_log.EXCEPTIONS, check_log.STAMP_OVERRIDES)
        check_log.EXCEPTIONS, check_log.STAMP_OVERRIDES = {}, {}
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "log.txt"
                p.write_text(text, encoding="utf-8")
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = check_log.main([str(p)])
            return code, buf.getvalue()
        finally:
            check_log.EXCEPTIONS, check_log.STAMP_OVERRIDES = saved

    def test_clean_log_passes(self) -> None:
        code, out = self.run_on(entry("## [2026-10-25T03:00:00+05:30] ok"))
        self.assertEqual(code, 0, out)

    def test_missing_brackets_fails_h1(self) -> None:
        code, out = self.run_on(entry("## 2026-10-25T03:00:00+05:30 no brackets"))
        self.assertEqual(code, 1)
        self.assertIn("H1", out)

    def test_compact_offset_fails_h1(self) -> None:
        code, out = self.run_on(entry("## [2026-10-25T03:00:00+0530] compact offset"))
        self.assertIn("H1", out)

    def test_long_title_fails_h2(self) -> None:
        code, out = self.run_on(entry("## [2026-10-25T03:00:00+05:30] " + "x" * 81))
        self.assertIn("H2", out)

    def test_missing_section_fails_s1(self) -> None:
        text = entry("## [2026-10-25T03:00:00+05:30] t").replace("Actions:\n", "")
        code, out = self.run_on(text)
        self.assertIn("S1", out)

    def test_missing_context_key_fails_c1(self) -> None:
        code, out = self.run_on(entry("## [2026-10-25T03:00:00+05:30] t",
                                      context=CONTEXT_MAIN.replace("branch=main\n", "")))
        self.assertIn("C1 Context missing branch", out)

    def test_subagent_without_directed_by_fails_c2(self) -> None:
        ctx = CONTEXT_MAIN.replace("agent_type=main", "agent_type=orch-x").replace(
            "parent_agent=none", "parent_agent=main")
        code, out = self.run_on(entry("## [2026-10-25T03:00:00+05:30] t", context=ctx))
        self.assertIn("C2", out)

    def test_backwards_timestamp_fails_t1(self) -> None:
        text = entry("## [2026-10-25T03:00:00+05:30] a") + "\n" + entry("## [2026-10-25T02:59:59+05:30] b")
        code, out = self.run_on(text)
        self.assertIn("T1", out)

    def test_quoted_markers_in_prompt_do_not_fool_s1(self) -> None:
        text = entry("## [2026-10-25T03:00:00+05:30] t").replace(
            "hi\n", "quoting Context:\nContext:\nActions:\n", 1)
        code, out = self.run_on(text)
        self.assertEqual(code, 0, out)

    def test_long_summary_warns_but_passes(self) -> None:
        code, out = self.run_on(entry("## [2026-10-25T03:00:00+05:30] t",
                                      summary="A. B. C. D. E. F. G."))
        self.assertEqual(code, 0, out)
        self.assertIn("warning", out)

    def test_stale_exception_fails(self) -> None:
        saved = check_log.EXCEPTIONS
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "log.txt"
                p.write_text(entry("## [2026-10-25T03:00:00+05:30] ok"), encoding="utf-8")
                check_log.EXCEPTIONS = {("H2", "2026-01-01T00:00:00+05:30"): "note"}
                buf = io.StringIO()
                with redirect_stdout(buf):
                    code = check_log.main([str(p)])
            self.assertEqual(code, 1)
            self.assertIn("stale exception", buf.getvalue())
        finally:
            check_log.EXCEPTIONS = saved


if __name__ == "__main__":
    unittest.main()
