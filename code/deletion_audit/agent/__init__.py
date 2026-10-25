"""The agent package (G7a): intent, intake cross-check, vision, the tool loop and answer validation.

The model interprets (the request's intent, screenshots, open questions); code decides identity,
state, policy and ordering (``../CLAUDE.md`` section 5). Every model call goes through GM's
:class:`~deletion_audit.model.ModelClient` (cache, budget, retries); this package never builds a
transport.

Public API:

* :func:`audit_with_agent` (one case, end to end) and :func:`run_case` (the loop alone);
* :func:`read_images`, :func:`learn_shapes`, :func:`write_vision_artifacts` (the vision step);
* :func:`validate_answers`, :func:`resolve_intent`, :func:`compile_twice`;
* :func:`agent_case_report`, :func:`vision_run_report`, :func:`routing_table`;
* :class:`LoopCaps` and the mode names.
"""

from __future__ import annotations

from .answers import AnswerCheck, Compiled, Rejection, ValidatedAnswer, compile_twice, resolve_intent, validate_answers
from .harness import AgentCaseResult, audit_with_agent
from .idshapes import IdCheck, IdShapes, check_id, learn_shapes
from .loop import AgentOutcome, FixedIntent, ToolCallRecord, run_case
from .params import MODES, LoopCaps, Mode
from .report import agent_case_report, vision_run_report
from .routing import routing_table
from .vision import ImageReadRecord, VisionRun, read_images, write_vision_artifacts

__all__ = [
    "MODES", "AgentCaseResult", "AgentOutcome", "AnswerCheck", "Compiled", "FixedIntent", "IdCheck", "IdShapes",
    "ImageReadRecord", "LoopCaps", "Mode", "Rejection", "ToolCallRecord", "ValidatedAnswer", "VisionRun",
    "agent_case_report", "audit_with_agent", "check_id", "compile_twice", "learn_shapes", "read_images",
    "resolve_intent", "routing_table", "run_case", "validate_answers", "vision_run_report", "write_vision_artifacts",
]
