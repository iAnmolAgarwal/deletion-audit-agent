"""The model client package (GM gate).

Public API:

* :class:`ModelRequest` (checked body; content-addressed key) and :class:`ModelReply`;
* :class:`ModelClient` (cache, budget, send with retries, cache.put, log);
* :class:`RetryPolicy`, the one place that decides retry, repair or give up;
* :class:`ReplyCache`, :class:`BudgetGuard`, the call logs;
* :class:`AnthropicTransport` (SDK 1.13.0, ``max_retries=0``) and :class:`FakeTransport`;
* :class:`ModelCallFailed`, :class:`RequestRejected`, :class:`CacheCorruptError`, :class:`PaidRunLocked`.
"""
from __future__ import annotations

from .budget import BudgetGuard, Reservation, usage_cost, worst_case_cost
from .cache import ReplyCache
from .calllog import CallLog, CallLogEntry, JsonlCallLog, MemoryCallLog
from .client import ModelClient
from .errors import FAIL_REASONS, CacheCorruptError, FailReason, ModelCallFailed, PaidRunLocked, RequestRejected
from .policy import Failure, GiveUp, Repair, Retry, RetryPolicy
from .reply import ModelReply, flatten_usage, reply_text, tool_uses
from .request import API_VERSION, ModelRequest, canonical_json
from .transport import AnthropicTransport, FakeTransport, Transport, TransportConfigError, TransportFailure

__all__ = [
    "API_VERSION", "FAIL_REASONS", "AnthropicTransport", "BudgetGuard", "CacheCorruptError", "CallLog",
    "CallLogEntry", "FailReason", "Failure", "FakeTransport", "GiveUp", "JsonlCallLog", "MemoryCallLog",
    "ModelCallFailed", "ModelClient", "ModelReply", "ModelRequest", "PaidRunLocked", "Repair", "ReplyCache",
    "RequestRejected", "Reservation", "Retry", "RetryPolicy", "Transport", "TransportConfigError",
    "TransportFailure", "canonical_json", "flatten_usage", "reply_text", "tool_uses", "usage_cost",
    "worst_case_cost",
]
