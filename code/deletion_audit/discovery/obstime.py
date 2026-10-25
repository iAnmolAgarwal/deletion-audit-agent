"""The time of one observation, with its precision and where it came from (T68).

* A record that states its own time (a log line, a row's ``updated_at``, a snapshot time) uses
  it: ``record_time`` from the evidence layer, at second precision.
* A PDF page uses the page's stated production time ("generated", "issued" or "captured", then
  a date and optionally ``HH MM UTC``) at its stated precision, else the file's ``captured_at``.
  The observation records which one it used. Basis: developer ruling T68; the label list is in
  ``config.PDF_TIME_LABELS`` (times of events the page describes are content, not its time).
* Anything else uses the file's ``captured_at``.

Comparisons against a request time are made at the observation's precision: a page dated
"18 Jun 2026" is at or before an ``audit_at`` later that same day.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Literal

from .. import timeutil
from ..config import PDF_TIME_LABELS
from ..evidence.model import Observation

Precision = Literal["second", "minute", "day"]
TimeBasis = Literal["record_time", "pdf_stated", "captured_at"]

_MONTHS = {
    m: i
    for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)
}
_PDF_TIME = re.compile(
    r"\b(" + "|".join(PDF_TIME_LABELS) + r")\s+(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})(?: (\d{2})[ :](\d{2}) UTC)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ObsTime:
    """``value`` is the start of the stated interval, as a ``...Z`` string."""

    value: str
    precision: Precision
    basis: TimeBasis


def _truncate(value: str, precision: Precision) -> dt.datetime:
    t = timeutil.parse(value)
    if precision == "day":
        return t.replace(hour=0, minute=0, second=0, microsecond=0)
    if precision == "minute":
        return t.replace(second=0, microsecond=0)
    return t


def pdf_stated_time(text: str | None) -> tuple[str, Precision] | None:
    """The first production time a PDF page states, or None."""
    if not text:
        return None
    for m in _PDF_TIME.finditer(text):
        month = _MONTHS.get(m.group(3).lower())
        if month is None:
            continue
        try:
            day = dt.date(int(m.group(4)), month, int(m.group(2)))
        except ValueError:
            continue
        if m.group(5) is not None:
            moment = dt.datetime(day.year, day.month, day.day, int(m.group(5)), int(m.group(6)))
            return moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "minute"
        return day.strftime("%Y-%m-%dT00:00:00Z"), "day"
    return None


def observation_time(obs: Observation) -> ObsTime:
    """The time an observation describes (module docstring)."""
    if obs.locator.kind == "pdf_page":
        stated = pdf_stated_time(obs.text)
        if stated is not None:
            return ObsTime(stated[0], stated[1], "pdf_stated")
        return ObsTime(obs.captured_at, "second", "captured_at")
    if obs.record_time is not None:
        return ObsTime(obs.record_time, "second", "record_time")
    return ObsTime(obs.captured_at, "second", "captured_at")


def at_or_before(t: ObsTime, ref: str) -> bool:
    """``t <= ref`` at ``t``'s precision."""
    return timeutil.parse(t.value) <= _truncate(ref, t.precision)


def at_or_after(t: ObsTime, ref: str) -> bool:
    """``t >= ref`` at ``t``'s precision."""
    return timeutil.parse(t.value) >= _truncate(ref, t.precision)


def in_window(t: ObsTime, lo: str, hi: str) -> bool:
    """``lo <= t <= hi`` at ``t``'s precision (both ends inclusive)."""
    return at_or_after(t, lo) and at_or_before(t, hi)
