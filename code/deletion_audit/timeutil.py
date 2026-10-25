"""Time comparison helpers for the engine.

All times in the inputs are ISO-8601 UTC strings normalized by
``evidence.interpret.normalize_time`` (``...Z``, seconds and fractions kept as written). Plain
string comparison would misorder a fractional time (``...:00.5Z`` sorts before ``...:00Z``), so
every comparison goes through :func:`parse`.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache


@lru_cache(maxsize=65536)
def parse(value: str) -> dt.datetime:
    """Parse a normalized ``...Z`` time into an aware UTC datetime."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def le(a: str, b: str) -> bool:
    """``a <= b`` as times (equality allowed, as DEV shows for ``captured_at == audit_at``, G1 F21)."""
    return parse(a) <= parse(b)


def lt(a: str, b: str) -> bool:
    """``a < b`` as times."""
    return parse(a) < parse(b)


def within(t: str, lo: str, hi: str) -> bool:
    """``lo <= t <= hi`` as times (both ends inclusive)."""
    return parse(lo) <= parse(t) <= parse(hi)


def offset_seconds(t: str, ref: str) -> float:
    """Seconds from ``ref`` to ``t`` (negative when ``t`` is earlier)."""
    return (parse(t) - parse(ref)).total_seconds()


def sort_key(value: str) -> dt.datetime:
    """Key for sorting by time."""
    return parse(value)
