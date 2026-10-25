"""Every tunable of the deterministic engine, with its basis.

Each value names where it comes from: a developer ruling (a T-number, a pointer to
``code/docs/DECISIONS.md``), a G2 forensics measurement on DEV cases (with its run ID) or domain
logic. Nothing here is keyed on a case ID, file name or row position.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

# ----------------------------------------------------------------------------- account assignment
#: Reported status -> the delete row result that matches it.
#: Basis: T4 step 2 ("reported_result matching the reported status"); G2 Q1 definitions.
RESULT_MAP: Mapping[str, str] = MappingProxyType(
    {
        "COMPLETE": "SUCCESS",
        "PARTIALLY_COMPLETE": "PARTIAL",
        "NOT_STARTED": "FAILED",
    }
)


@dataclass(frozen=True)
class AccountConfig:
    """Account-stage tunables (pinned by the G2 architecture choice; rulings T4, T26, T39, T57).

    * ``window_min``: T4 timed rule, -75..-44 min before ``reported_at``, inclusive. Basis: G2 Q3
      (234/236 identifier-linked offsets in -74.9..-44.0, ``g2-acct_stages-0137``; edges -76/-43 give
      the same DEV and test result).
    * ``hand_built_min``: T26 Option A, +-10 min, result-matched. Basis: G2 Q1 (DEV 3/3, test 0).
    * ``tie_order``: T39/T57, sha256 of the resolved person's ``user_id``.
    """

    window_min: tuple[int, int] = (-75, -44)
    hand_built_min: int = 10
    result_map: Mapping[str, str] = field(default_factory=lambda: RESULT_MAP)
    tie_order: str = "sha256_user_id"


# ----------------------------------------------------------------------------- job timing (T5, T53)
# The timing windows and bands below. Rule: a deletion job's rows sit at fixed offsets from the
# request's ``reported_at``, and its rows share one timing phase, so ``discovery/timing.py`` uses
# them to tie a row to a job when no identifier does (account tie-breaks in
# ``discovery/accounts.py``, identifier-free analytics in ``discovery/analytics.py``). Reason: the
# data logs no job ID, and this timing is the only job correlation in the inputs. It reproduces the
# generator's timing; it is not a rule of the domain (T5, T53 in code/docs/DECISIONS.md).
# Basis, measured on identifier-linked jobs from the inputs only (no sample answers), by run ID:
# * TEMPLATE_WINDOWS: the prototype's measured windows, carried over unchanged; run
#   ``g2f2-g2f2_h2_analytics-0242`` uses the policy and after windows. No run of ours records their
#   first measurement.
# * SIG_BANDS: policy rows at 9-11 s and after rows at 20-22 s, mod 30 s from the account phase;
#   the fingerprint is stable mod 30 s, not mod 60 s (``g2-q7_mod60-0137``). Widening the bands by
#   1 s changes 33 test cases and narrowing them changes 122 (``g2-q4_d17-0137``), so a fixture
#   test pins them.
# * POLICY_SLOTS and SLOT_BANDS: each minute slot before ``reported_at`` has its own band mod 60 s;
#   93 of 93 identifier-linked policy rows fall inside their slot's band
#   (``g2f2-g2f2_h2_analytics-0242``).

#: Deletion-worker row templates by their details text (read from the inputs).
POLICY_PREFIX = "Policy action completed"
SUBMIT_MARKERS: tuple[str, ...] = ("submitted primary profile", "reported the requested operation")

#: Per-template windows, in minutes from ``reported_at``, inclusive (basis above).
TEMPLATE_WINDOWS: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        "submit": (-76.0, 9.0),
        "policy": (-31.0, -2.0),
        "after": (5.0, 135.0),
    }
)

#: D17 fingerprint bands: residual (row offset - account phase) mod 30 s, inclusive (basis above).
SIG_BANDS: Mapping[str, tuple[int, int]] = MappingProxyType({"policy": (9, 11), "after": (20, 22)})

#: Policy slots: minute bins before ``reported_at`` (basis above).
POLICY_SLOTS: tuple[tuple[int, int], ...] = ((-29, -28), (-22, -21), (-15, -14), (-8, -7), (-3, -2))

#: Per-slot residual band: (row offset - account offset) mod 60 s, inclusive (basis above).
SLOT_BANDS: Mapping[int, tuple[int, int]] = MappingProxyType(
    {
        0: (40, 41),
        1: (10, 11),
        2: (39, 40),
        3: (9, 10),
        4: (39, 39),
    }
)

# ----------------------------------------------------------------------------- identity and linking
#: Identifier kinds that can link a record to a person (exact match only, T49/T59).
LINK_KINDS: frozenset[str] = frozenset({"email", "phone", "email_hash", "user_id"})
#: Fields whose identifiers are free-text content, not the record's own key (T49: a field's
#: role comes from its line; text is content).
TEXT_ID_FIELDS: frozenset[str] = frozenset({"message_text", "message_excerpt", "pdf_text"})

# ----------------------------------------------------------------------------- PDF pages (T68)
#: Words that state the page's own production time; times of events the page describes
#: (submitted, received, recorded, order date) are content, not the page's time. Basis: T68 and
#: domain logic (a document's time is when it was produced).
PDF_TIME_LABELS: tuple[str, ...] = ("generated", "issued", "captured")


@dataclass(frozen=True)
class EngineConfig:
    """Top-level engine configuration."""

    accounts: AccountConfig = field(default_factory=AccountConfig)


# ----------------------------------------------------------------------------- model wiring (G7)
#: Reply-cache namespaces under the cache directory: the case's own conversation (and vision
#: reading 1) in the first, the turn-1 replicate (and vision reading 2) in the second. Basis: G3
#: section 8 ("replicates ... use a separate cache root (``cache/replies-replica-k/``), not a key
#: change"); T88 (1) (two readings per image, in separate cache namespaces); T70 (two replicate runs).
REPLY_NAMESPACES: tuple[str, str] = ("replies", "replies-replica-1")
