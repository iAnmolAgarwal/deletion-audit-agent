"""The state one observation shows for its resource (raw fields -> a state value).

This is the port of the prep prototype's ``unit_state`` (research/15 R6, R9, R10, R17; DEV 22/22
status, 132/134 steps) onto the evidence layer's observations. Fields are read by their leaf
name (``record_json.email`` -> ``email``). The result is ``None`` when the record states nothing
about the resource (a ``*_started`` line, a preview failure).

State vocabulary (``notes/ARCHITECTURE_OPTIONS.md`` section 5): PRESENT, ABSENT, IDENTIFIABLE,
ANONYMIZED, REDACTED, EXPOSED_PII (a tombstone still holding a direct identifier), FLOW_ENABLED,
FLOW_DISABLED, RESTORABLE, RESTORE_BLOCKED.

**Image observations** (locator kind ``image``, built by ``agent/vision.py``) have their own rule,
:func:`image_state` (developer ruling T112 item 9, G7 verifier finding 1): only what is visibly on
screen sets a state. A visible state field (sync, restore, download, deleted) is read as the text
rules read it; a transcribed subject gives the system's "still holds the person" state (IDENTIFIABLE,
EXPOSED_PII or PRESENT); REDACTED or ANONYMIZED comes only from a visible marker of the kind the text
rules use (``[REDACTED]``, the support rule's literal, and its analytics counterpart ``[ANONYMIZED]``).
With nothing transcribed and no marker the image gives no state: the support (REDACTED), analytics
(ANONYMIZED) and tombstone (REDACTED) defaults below were written for text records and never apply
to an image, because an untranscribed subject is not evidence of redaction. The visible status
label is never read here (review only).

**Backup rule F for images** (developer ruling T114 item 13): a backup whose state comes from an
image reading is RESTORE_BLOCKED only on a visible cue (``restore_allowed`` shown ``no``, or a
verbatim restore-block marker: a marker whose text says blocked or denied); with no visible cue it
is RESTORABLE, an active restore path (REPORT_RESTORE_RISK, BLOCK_RESTORE, VERIFY_RESTORE_BLOCKED:
DEV gold's backup pattern, two DEV cases). Backups whose state comes from text keep the text rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from ..config import TEXT_ID_FIELDS
from ..evidence.interpret import leaf_name
from ..evidence.model import Observation
from ..identity.resolve import IdentifierSet

StateValue = Literal[
    "PRESENT",
    "ABSENT",
    "IDENTIFIABLE",
    "ANONYMIZED",
    "REDACTED",
    "EXPOSED_PII",
    "FLOW_ENABLED",
    "FLOW_DISABLED",
    "RESTORABLE",
    "RESTORE_BLOCKED",
    "RETAINED",
]

#: Values that state the absence of a value, as the prototype read them (research/15).
NULLS: frozenset[str] = frozenset({"", "null", "None", "NULL"})
#: Result column of check-result rows (handover, flat lists, lookup history): research/15 R6.
RESULT_STATE: Mapping[str, str] = {
    "FOUND": "PRESENT",
    "NOT_FOUND": "ABSENT",
    "IDENTIFIABLE": "IDENTIFIABLE",
    "ANONYMIZED": "ANONYMIZED",
    "REDACTED": "REDACTED",
    "ACTIVE": "ACTIVE",
    "DISABLED": "DISABLED",
    "BLOCKED": "BLOCKED",
}
NO_STATE_EVENTS: frozenset[str] = frozenset({"thumbnail_failed"})


def leaves(obs: Observation) -> dict[str, str]:
    """Field values by leaf name; the first occurrence (field order) wins."""
    out: dict[str, str] = {}
    for key, value in obs.attrs.items():
        out.setdefault(leaf_name(key), value)
    return out


def _true(value: str | None) -> bool:
    return (value or "").strip().lower() in ("true", "1")


def _set(value: str | None) -> bool:
    return value is not None and value.strip() not in NULLS


def _by_system(system: str, raw: str) -> str:
    """Map the generic ACTIVE / DISABLED / BLOCKED of a result column onto the system's vocabulary."""
    if system == "integration_service":
        return {"ACTIVE": "FLOW_ENABLED", "DISABLED": "FLOW_DISABLED"}.get(raw, raw)
    if system == "backup_service":
        return {"ACTIVE": "RESTORABLE", "BLOCKED": "RESTORE_BLOCKED"}.get(raw, raw)
    return raw


def is_attachment_listing(obs: Observation) -> bool:
    """A record listed under a ticket-attachment collection (bundle collection or replica table row)."""
    lv = leaves(obs)
    return obs.event == "ticket_attachments" or lv.get("collection_name") == "ticket_attachments"


def text_names_person(obs: Observation, person: IdentifierSet | None) -> bool:
    """T86 item 3 / T49: free text exposes the person only by an exact match of one of their
    identifiers (an email, phone or user ID found in the text); a look-alike never does."""
    if person is None:
        return False
    return any(person.matches(i) for i in obs.record_identifiers if leaf_name(i.field) in TEXT_ID_FIELDS)


def observation_state(obs: Observation, system: str | None, person: IdentifierSet | None = None) -> str | None:
    """The state ``obs`` shows for its resource, read as research/15's rules (module docstring).

    ``person`` is the case's identifier set: free-text PII counts only for them (T86 item 3).
    """
    if obs.locator.kind == "image":
        return image_state(obs, system)
    event = obs.event or ""
    if event.endswith("_started") or event in NO_STATE_EVENTS:
        return None
    a = leaves(obs)
    if "record_type" in a and "result" in a:  # check-result rows: handover, flat list, lookup history
        raw = RESULT_STATE.get((a.get("result") or "").upper())
        return _by_system(system or "", raw) if raw else None
    if obs.locator.kind == "pdf_page":
        return "PRESENT"
    if system in ("object_storage", "object_store", "marketing_platform"):
        return "PRESENT"
    if system == "account_service":
        if "status_code" in a:
            return "PRESENT" if a["status_code"].strip() == "200" else "ABSENT"
        if "http_status" in a:
            return "PRESENT" if a["http_status"].strip() == "200" else "ABSENT"
        return "ABSENT" if (a.get("account_status") or "").upper() == "DELETED" else "PRESENT"
    if system == "search_service":
        if event == "index_query_completed":
            return "PRESENT" if a.get("result") == "hit" else "ABSENT"
        if "total" in a and obs.family == "service_resource_export":
            try:
                return "PRESENT" if int(a["total"]) > 0 else "ABSENT"
            except ValueError:
                return None
        if obs.family == "service_resource_export" and event == "index_queries":
            return "ABSENT"
        return "PRESENT"
    if system == "analytics_platform":
        if event == "contact_lookup_completed":
            return "PRESENT" if a.get("rows") != "0" else "ABSENT"
        if "direct_identifiers" in a:
            return "IDENTIFIABLE" if a["direct_identifiers"] != "0" else "ANONYMIZED"
        if event == "analytics_identity_scan":
            return "IDENTIFIABLE"
        keys = ("email", "phone", "email_hash", "customer_reference", "user_id")
        return "IDENTIFIABLE" if any(_set(a.get(k)) for k in keys) else "ANONYMIZED"
    if system == "support_platform":
        if event in ("message_pii_scan", "attachment_pii_scan"):
            return "IDENTIFIABLE"
        if event == "deletion_marker_check":
            return "IDENTIFIABLE" if a.get("marker_found") == "false" else "REDACTED"
        if event == "contact_query_completed":
            return "IDENTIFIABLE" if a.get("rows") != "0" else "ABSENT"
        text = a.get("message_text") or ""
        if event == "message_read":
            return "REDACTED" if "[REDACTED]" in text else "IDENTIFIABLE"
        if is_attachment_listing(obs):
            return "IDENTIFIABLE"
        if text and "[REDACTED]" not in text and text_names_person(obs, person):
            return "IDENTIFIABLE"
        if any(_set(a.get(k)) for k in ("requester_email", "requester_name", "requester_phone")):
            return "IDENTIFIABLE"
        return "REDACTED"
    if system == "export_service":
        for k in ("available", "download_available"):
            if k in a:
                return "PRESENT" if _true(a[k]) else "ABSENT"
        return "PRESENT"
    if system == "integration_service":
        if "enabled" in a:
            return "FLOW_ENABLED" if _true(a["enabled"]) else "FLOW_DISABLED"
        return None
    if system == "backup_service":
        if "restore_allowed" in a:
            return "RESTORABLE" if _true(a["restore_allowed"]) else "RESTORE_BLOCKED"
        if event == "restore_candidate_evaluated":
            ok = (a.get("eligible") or "").lower() == "true" and (a.get("deletion_block") or "").lower() == "false"
            return "RESTORABLE" if ok else "RESTORE_BLOCKED"
        if event == "restore_authorization_completed":
            return "RESTORE_BLOCKED" if a.get("decision") == "deny" else "RESTORABLE"
        return None
    if system == "security_service":
        return "PRESENT"
    if system == "identity_service":
        pii = any(_set(a.get(k)) for k in ("name", "email", "phone", "email_hash"))
        return "EXPOSED_PII" if pii else "REDACTED"
    if system == "legal_service":
        return "PRESENT"
    return None


#: Marker literal per system that lets an image show a cleaned record (module docstring).
IMAGE_MARKERS: Mapping[str, tuple[str, str]] = {
    "support_platform": ("[REDACTED]", "REDACTED"),
    "identity_service": ("[REDACTED]", "REDACTED"),
    "analytics_platform": ("[ANONYMIZED]", "ANONYMIZED"),
}
#: The state a transcribed subject gives, by system (the text rules' "still holds the person" state).
IMAGE_SUBJECT_STATE: Mapping[str, str] = {
    "analytics_platform": "IDENTIFIABLE",
    "support_platform": "IDENTIFIABLE",
    "identity_service": "EXPOSED_PII",
    "account_service": "PRESENT",
    "search_service": "PRESENT",
    "export_service": "PRESENT",
    "object_storage": "PRESENT",
    "object_store": "PRESENT",
    "marketing_platform": "PRESENT",
    "security_service": "PRESENT",
    "legal_service": "PRESENT",
}
_SUBJECT_KEYS = ("email", "phone", "name", "user_id", "requester_email", "requester_name", "requester_phone")


def image_state(obs: Observation, system: str | None) -> str | None:
    """The state an image observation shows: only what is visibly on screen (module docstring)."""
    a = leaves(obs)
    sysid = system or ""
    if sysid == "integration_service" and "enabled" in a:
        return "FLOW_ENABLED" if _true(a["enabled"]) else "FLOW_DISABLED"
    if sysid == "backup_service":
        if "restore_allowed" in a:
            return "RESTORABLE" if _true(a["restore_allowed"]) else "RESTORE_BLOCKED"
        return "RESTORE_BLOCKED" if restore_block_cue(a.get("visible_marker")) else "RESTORABLE"  # T114 rule F
    if sysid == "export_service" and "download_available" in a:
        return "PRESENT" if _true(a["download_available"]) else "ABSENT"
    if sysid == "account_service" and "account_status" in a:
        return "ABSENT" if a["account_status"].upper() == "DELETED" else "PRESENT"
    if bool(obs.record_identifiers) or any(_set(a.get(k)) for k in _SUBJECT_KEYS):
        return IMAGE_SUBJECT_STATE.get(sysid)
    marker = IMAGE_MARKERS.get(sysid)
    if marker is not None and marker[0] in (a.get("visible_marker") or ""):
        return marker[1]
    return None


#: Words that make a verbatim marker a restore-block cue on a backup image (T114 item 13).
RESTORE_BLOCK_WORDS: tuple[str, ...] = ("block", "denied")


def restore_block_cue(marker: str | None) -> bool:
    """A visible restore-block marker: its verbatim text says blocked or denied (case-insensitive)."""
    text = (marker or "").lower()
    return any(w in text for w in RESTORE_BLOCK_WORDS)
