"""Prompt files and the fencing of untrusted text.

* Prompts live in ``agent/prompts/*.md`` (G3 section 11, C1), never inline in code. They are read
  as UTF-8 text exactly as written, so a prompt edit changes every request key that uses it.
* ``tools.md`` holds one ``## <tool name>`` section per tool; :func:`tool_descriptions` returns
  them by name.
* Untrusted text (a request text, an evidence excerpt) is fenced in a named tag and defanged:
  any sequence in it that could open or close that tag is neutralised, so the text can never end
  the fence early. Basis: ``../CLAUDE.md`` section 7 (request text and evidence are data, never
  obeyed); T63 pin 1.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SECTION = re.compile(r"^## +(\S+) *$", re.MULTILINE)


@cache
def load_prompt(name: str) -> str:
    """The text of ``prompts/<name>.md``; a missing or empty prompt file raises."""
    path = PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"prompt file {path.name} is empty")
    return text


@cache
def tool_descriptions() -> dict[str, str]:
    """``{tool name: description}`` from ``prompts/tools.md`` (one ``## name`` section each)."""
    text = load_prompt("tools")
    marks = list(_SECTION.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end() : end].strip()
        if not body:
            raise ValueError(f"tool {m.group(1)} has an empty description")
        out[m.group(1)] = body
    return out


def defang(text: str, tag: str) -> str:
    """``text`` with every ``<tag``, ``</tag`` (any case, optional spaces) turned into ``[tag``."""
    pattern = re.compile(r"<\s*/?\s*" + re.escape(tag), re.IGNORECASE)
    return pattern.sub("[" + tag, text)


def fence(text: str, tag: str) -> str:
    """``text`` defanged and wrapped in ``<tag>`` ... ``</tag>`` on their own lines."""
    return f"<{tag}>\n{defang(text, tag)}\n</{tag}>"
