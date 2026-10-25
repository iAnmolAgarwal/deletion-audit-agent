"""Fixed model parameters and loop caps for the agent package (G7a), each with its basis.

* Model ``claude-sonnet-5-5``: ``../CLAUDE.md`` section 5 (the build's one model); priced in
  :mod:`deletion_audit.model.prices`.
* ``output_config.effort`` is fixed per call type so replies replay deterministically
  (``../CLAUDE.md`` section 5, "a fixed output_config.effort"). ``medium`` for routing, intent and
  loops is G3 section 8's default, to be confirmed by the 3-case probe; vision uses the same level.
* ``max_tokens``: 4,096 for turn 1 (intent) and 8,000 for loop turns and vision (G3 section 8);
  both under the 21,333 non-streaming limit that :class:`~deletion_audit.model.ModelRequest`
  enforces.
* No ``temperature`` and no forced ``tool_choice`` anywhere: the request builder refuses both
  (``../CLAUDE.md`` section 5; ``model/request.py``).
* Prompt caching (``cache_control``) is off: the T76 smoke call does not test it on SDK 1.13.0,
  and a request field nobody has checked live must not reach a paid run unannounced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["A+", "A", "tools_off"]
MODES: tuple[Mode, ...] = ("A+", "A", "tools_off")

MODEL = "claude-sonnet-5-5"
EFFORT_ROUTING = "medium"
EFFORT_VISION = "medium"
MAX_TOKENS_TURN1 = 4_096
MAX_TOKENS_LOOP = 8_000
MAX_TOKENS_VISION = 8_000


@dataclass(frozen=True)
class LoopCaps:
    """Bounds on one case's conversation (G3 section 5 ``LoopCaps``).

    * ``max_tool_calls``: at most 4 tool calls in total, ``audit_case`` included; then one final
      request with ``tool_choice: none`` (``../CLAUDE.md`` section 5, "at most 4 tool calls per case").
    * ``max_requests``: model requests per case before the final turn is forced (G3: 6).
    * ``max_wall_s``: wall-clock bound per case before the final turn is forced (G3: 180 s).
    * ``no_repeat``: an identical tool call (same name, same arguments) is refused, not run again.
    """

    max_tool_calls: int = 4
    max_requests: int = 6
    max_wall_s: float = 180.0
    no_repeat: bool = True

    def __post_init__(self) -> None:
        """Refuse caps that would let a loop run unbounded or never reach a final turn."""
        if self.max_tool_calls < 0 or self.max_requests < 2 or self.max_wall_s <= 0:
            raise ValueError("need max_tool_calls >= 0, max_requests >= 2 and max_wall_s > 0")
