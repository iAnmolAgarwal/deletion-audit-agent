"""Every tunable of the deterministic engine, with its basis (``../CLAUDE.md`` section 5, C5).

Each value names where it comes from: a developer ruling (T-number in ``notes/DECISIONS.md``),
a G2 forensics measurement (``notes/gold_forensics.md``, with its run ID) or domain logic.
Nothing here is keyed on a case ID, file name or row position.
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
    """Account-stage tunables (pinned in ``notes/ARCHITECTURE_OPTIONS.md`` section 5).

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
#: Deletion-worker row templates by their details text. Basis: research/15 R19 (inputs only).
POLICY_PREFIX = "Policy action completed"
SUBMIT_MARKERS: tuple[str, ...] = ("submitted primary profile", "reported the requested operation")

#: Per-template windows (minutes from ``reported_at``) measured on identifier-linked jobs.
#: Basis: research/15 section 3.5 item 2 (inputs only; DEV unchanged).
TEMPLATE_WINDOWS: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        "submit": (-76.0, 9.0),
        "policy": (-31.0, -2.0),
        "after": (5.0, 135.0),
    }
)

#: D17 fingerprint bands, residual (row offset - account phase) mod 30 s, inclusive.
#: Basis: T5; research/15 R19 (250 identifier-linked jobs: 9-11 and 20-22); +-1 s changes 33 test
#: cases (G2 Q4), so a fixture test pins them.
SIG_BANDS: Mapping[str, tuple[int, int]] = MappingProxyType({"policy": (9, 11), "after": (20, 22)})

#: Policy slots: minute bins before ``reported_at`` (T53; G2 follow-up 2 H2).
POLICY_SLOTS: tuple[tuple[int, int], ...] = ((-29, -28), (-22, -21), (-15, -14), (-8, -7), (-3, -2))

#: Per-slot residual band (row offset - account offset) mod 60 s, inclusive, measured on
#: identifier-linked policy rows of S1 jobs. Basis: T53/T62; ``g2f2-g2f2_h2_analytics-0242``
#: (93/93 identifier-linked policy rows inside their slot's band).
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

#: The record of the developer-approved outputs (T101 (1)), one per split (T117 B2); the regression
#: gate reads each approved file's path and sha256 from it at run time, relative to the repo root.
#: It and the files it names live under ``code/approved/``, inside the package tree that code.zip
#: ships, so a fresh unzip with ``dataset/`` beside ``code/`` finds them (``runs/`` is never shipped).
#: ``notes/approved_output.json`` (read by the freeze check) is kept byte-identical by a test.
APPROVED_OUTPUT_RECORD = "code/approved/approved_output.json"
