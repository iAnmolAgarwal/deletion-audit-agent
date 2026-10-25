"""T95 item 2 (C1): every prompt has a role, constraints, a refusal path with a reason, fenced
untrusted text and made-up examples; every tool description says when to use it, when not, what it
returns and that it is read-only."""

from __future__ import annotations

import re
import unittest

from deletion_audit.agent.intent import REQUEST_TAG, turn1_request
from deletion_audit.agent.prompting import load_prompt, tool_descriptions
from deletion_audit.agent.schemas import FINAL_ANSWER_SCHEMA
from deletion_audit.agent.tools import TOOL_NAMES, tool_definitions
from deletion_audit.agent.vision import vision_request

from ._support import PNG

PARTS = ("Role", "Constraints", "Untrusted data", "When you cannot tell", "Examples")


def sections(text: str) -> dict[str, str]:
    """``{heading: body}`` for every ``## heading`` (the first word group up to a parenthesis)."""
    marks = list(re.finditer(r"^## +(.+?)\s*(\(.*\))?$", text, re.MULTILINE))
    return {m.group(1): text[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(text))]
            for i, m in enumerate(marks)}


class TestPromptParts(unittest.TestCase):
    def test_each_prompt_has_every_part(self) -> None:
        for name in ("system", "vision"):
            got = sections(load_prompt(name))
            self.assertEqual([p for p in PARTS if p not in got], [], name)
            for part in PARTS:
                self.assertTrue(got[part].strip(), f"{name}: {part} is empty")

    def test_role_says_who_and_what(self) -> None:
        for name in ("system", "vision"):
            self.assertRegex(sections(load_prompt(name))["Role"], r"^\s*You ", name)

    def test_refusal_path_is_uncertain_with_a_reason(self) -> None:
        system = sections(load_prompt("system"))["When you cannot tell"]
        self.assertIn("`UNCERTAIN`", system)
        self.assertIn("`uncertain_reason`", system)
        self.assertIn("`cannot_answer`", system)
        self.assertIn("uncertain_reason", FINAL_ANSWER_SCHEMA["required"])
        vision = sections(load_prompt("vision"))["When you cannot tell"]
        self.assertIn("`UNCERTAIN`", vision)
        self.assertIn("`unreadable`", vision)
        self.assertIn("reason", vision)

    def test_untrusted_text_is_fenced_in_the_prompt_and_in_the_request(self) -> None:
        system = sections(load_prompt("system"))["Untrusted data"]
        self.assertIn(f"`<{REQUEST_TAG}>`", system)
        self.assertIn("not instructions", system)
        self.assertIn("Never follow", system)
        text = turn1_request("hello", tool_definitions()).plain_body()["messages"][0]["content"][0]["text"]
        self.assertTrue(text.startswith(f"<{REQUEST_TAG}>") and text.endswith(f"</{REQUEST_TAG}>"))
        vision = sections(load_prompt("vision"))["Untrusted data"]
        self.assertIn("`<screenshot>`", vision)
        self.assertIn("not instructions", vision)
        blocks = vision_request(PNG).plain_body()["messages"][0]["content"]
        self.assertEqual([b["type"] for b in blocks], ["text", "image", "text"])
        self.assertEqual(blocks[0]["text"], "<screenshot>")
        self.assertTrue(blocks[2]["text"].startswith("</screenshot>"))

    def test_examples_use_made_up_ids_and_example_domains(self) -> None:
        for name in ("system", "vision"):
            ex = sections(load_prompt(name))["Examples"]
            self.assertIn("made-up", load_prompt(name).split("## Examples", 1)[1].splitlines()[0])
            for domain in re.findall(r"@([A-Za-z0-9.-]+)", ex):
                self.assertTrue(domain.startswith("example."), domain)
            # dataset-shaped IDs (prefix_digits with a dataset prefix) never appear; made-up prefixes only
            for token in re.findall(r"\b([a-z_]+)_\d+\b", ex):
                self.assertNotIn(token, {"account", "search", "support", "analytics", "export", "backup", "data_flow",
                                         "tombstone", "legal_hold", "audit_record", "marketing", "object", "user",
                                         "case", "evidence", "activity"}, name)


class TestToolDescriptionParts(unittest.TestCase):
    def test_every_tool_says_when_when_not_returns_read_only(self) -> None:
        desc = tool_descriptions()
        self.assertEqual(sorted(desc), sorted(TOOL_NAMES))
        for name in TOOL_NAMES:
            for label in ("When to use:", "When not to use:", "Returns:", "Read-only:"):
                self.assertRegex(desc[name], rf"(?m)^{re.escape(label)} \S", f"{name}: {label}")

    def test_definitions_carry_the_descriptions(self) -> None:
        for d in tool_definitions():
            self.assertEqual(d["description"], tool_descriptions()[d["name"]])


if __name__ == "__main__":
    unittest.main()
