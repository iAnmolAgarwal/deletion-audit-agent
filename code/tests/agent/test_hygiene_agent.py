"""Source hygiene for the agent package: docstrings, no case IDs, no .env, no gold, no stdlib shadowing,
no phrase tables, and no tests that read runs/ or a cache as their expected value."""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[2]
AGENT = CODE / "deletion_audit" / "agent"
TESTS = CODE / "tests" / "agent"
CASE_ID = re.compile(r"\bcase_\d+\b")


def sources() -> list[Path]:
    return sorted(AGENT.glob("*.py"))


class TestAgentHygiene(unittest.TestCase):
    def test_core_modules_have_docstrings(self) -> None:
        missing = []
        for p in sources():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            if not ast.get_docstring(tree):
                missing.append(f"{p.name}: module")
            for node in ast.walk(tree):
                if (isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_")
                        and not ast.get_docstring(node)):
                    missing.append(f"{p.name}: {node.name}")
        self.assertEqual(missing, [])

    def test_no_case_ids_env_or_gold_in_agent_source_prompts_or_tests(self) -> None:
        files = sources() + sorted((AGENT / "prompts").glob("*.md")) + sorted(TESTS.glob("*.py"))
        bad = []
        for p in files:
            text = p.read_text(encoding="utf-8")
            if p == Path(__file__).resolve():
                continue
            if CASE_ID.search(text) or re.search(r"""(^|["'/\s])\.env\b""", text) or "sample_output" in text:
                bad.append(p.name)
        self.assertEqual(bad, [])

    def test_no_stdlib_shadowing(self) -> None:
        names = {p.stem for p in AGENT.glob("*.py")} | {p.stem for p in TESTS.glob("*.py")}
        self.assertEqual(sorted((names - {"__init__"}) & set(sys.stdlib_module_names)), [])

    def test_no_transport_built_and_no_key_read_in_agent(self) -> None:
        """Every call goes through GM's client: the agent never builds a transport or reads a key."""
        for p in sources():
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("AnthropicTransport", text, p.name)
            self.assertNotIn("ANTHROPIC_API_KEY", text, p.name)
            self.assertNotIn("import anthropic", text, p.name)

    def test_no_intent_phrase_table(self) -> None:
        """T7: intent comes from the model; no module holds deletion keywords to match request text."""
        words = re.compile(r"""["'](delete|deletion|erase|remove|löschen|exclusão|삭제|削除)["']""", re.IGNORECASE)
        hits = [p.name for p in sources() if words.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])

    def test_no_test_reads_runs_or_cache_as_expected(self) -> None:
        pattern = re.compile(r"""["'](?:runs|cache)/|REPO_ROOT\s*/\s*["']runs""")
        hits = [p.name for p in sorted(TESTS.glob("test_*.py")) if pattern.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
