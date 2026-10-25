"""Deletion-job timing: activity-row templates, the D17 fingerprint and the policy slots.

These rules have a data basis and no domain basis: they reproduce the generator's timing, which
the README states (T5, T53). Every band is in ``config.py`` with its measurement run.

* Template of a deletion-worker row, from its details text: "Policy action completed" ->
  ``policy``; the account submit wordings -> ``submit``; anything else -> ``after``
  (research/15 R19).
* D17 fit (T5): with the account phase ``A = offset(account row) mod 60``, a row fits when
  ``(offset(row) - A) mod 30`` is inside its template's band (``config.SIG_BANDS``).
* Policy slot (T53): the minute bin before ``reported_at`` a policy row falls in; a row fits a
  job when ``(offset(row) - offset(account row)) mod 60`` is inside its slot's band
  (``config.SLOT_BANDS``).
"""

from __future__ import annotations

from ..config import POLICY_PREFIX, POLICY_SLOTS, SIG_BANDS, SLOT_BANDS, SUBMIT_MARKERS, TEMPLATE_WINDOWS
from ..inputs.model import ActivityRow
from ..timeutil import offset_seconds

DELETION_WORKER = "deletion_worker"


def template(row: ActivityRow) -> str:
    """``policy``, ``submit`` or ``after`` (module docstring)."""
    if row.details.startswith(POLICY_PREFIX):
        return "policy"
    if any(m in row.details for m in SUBMIT_MARKERS):
        return "submit"
    return "after"


def offset_min(row: ActivityRow, reported_at: str) -> float:
    """Minutes from ``reported_at`` to the row (negative = before)."""
    return offset_seconds(row.event_time, reported_at) / 60.0


def in_template_window(row: ActivityRow, reported_at: str) -> bool:
    """The row sits inside its template's measured window (``config.TEMPLATE_WINDOWS``)."""
    lo, hi = TEMPLATE_WINDOWS[template(row)]
    return lo <= offset_min(row, reported_at) <= hi


def sig_match(row: ActivityRow, reported_at: str, phase_s: float) -> bool:
    """D17 fit of one row to an account phase ``phase_s`` (seconds mod 60); T5."""
    band = SIG_BANDS.get(template(row))
    if band is None:
        return False
    r = (offset_seconds(row.event_time, reported_at) - phase_s) % 30
    return band[0] <= r <= band[1]


def account_phase(account_row: ActivityRow, reported_at: str) -> float:
    """The account row's offset in seconds, mod 60 (the D17 phase)."""
    return offset_seconds(account_row.event_time, reported_at) % 60


def slot_of(offset_minutes: float) -> int | None:
    """The policy slot a row's offset falls in, or None (T53)."""
    for i, (lo, hi) in enumerate(POLICY_SLOTS):
        if lo <= offset_minutes < hi:
            return i
    return None


def slot_fit(row: ActivityRow, reported_at: str, account_offset_s: float) -> bool:
    """T53: the row is in a policy slot and its residual mod 60 is inside that slot's band."""
    o = offset_seconds(row.event_time, reported_at)
    s = slot_of(o / 60.0)
    if s is None or s not in SLOT_BANDS:
        return False
    lo, hi = SLOT_BANDS[s]
    return lo <= (o - account_offset_s) % 60 <= hi
