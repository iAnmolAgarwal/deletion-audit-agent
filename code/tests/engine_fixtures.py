"""Synthetic inputs for the engine tests: builders and a tiny dataset writer.

Every value here is made up (``example.test`` emails, ``user_9xxx`` IDs). No test reads an expected
value from ``runs/``, a cache or ``sample_output.csv``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from deletion_audit.evidence.interpret import make_identifier
from deletion_audit.evidence.model import Identifier, Locator, Observation
from deletion_audit.inputs.model import ActivityRow
from deletion_audit.inputs.requests import DeletionRequest, RequestSource

RULES_CSV = Path(__file__).resolve().parents[2] / "dataset" / "deletion_rules.csv"


def case(n: int) -> str:
    """A made-up case ID of the ruled shape ``case_<digits>`` (T87(5)). It is built at run time, so
    no case ID is written in the source (T71 Q8; ``tests/hygiene``)."""
    return f"case_{n}"


def ident(kind: str, raw: str, field_name: str = "email") -> Identifier:
    """An identifier built by the evidence layer's own normalizer."""
    return make_identifier(kind, raw, field_name)  # type: ignore[arg-type]


def obs(
    resource_id: str | None,
    *,
    file_id: str = "ev_1",
    system: str | None = None,
    time: str | None = "2026-05-02T10:00:00Z",
    captured_at: str = "2026-05-03T00:00:00Z",
    record: Iterable[Identifier] = (),
    lookup: Iterable[Identifier] = (),
    attrs: dict[str, str] | None = None,
    event: str | None = None,
    family: str = "kv_log",
    kind: str = "line",
    ref: str = "L1",
    text: str | None = None,
) -> Observation:
    """One observation with the given fields (defaults: a log line inside a test window)."""
    return Observation(
        file_id=file_id,
        family=family,
        locator=Locator(file_id, kind, ref),  # type: ignore[arg-type]
        captured_at=captured_at,
        record_time=time,
        system_id=system,
        resource_id=resource_id,
        record_identifiers=frozenset(record),
        lookup_identifiers=frozenset(lookup),
        trace_id=None,
        scope=None,
        event=event,
        attrs=MappingProxyType(dict(attrs or {})),
        text=text,
    )


def act(
    activity_id: str,
    event_time: str,
    event_type: str,
    resource_id: str | None,
    *,
    target: str = "account_service",
    source: str = "deletion_worker",
    result: str | None = "SUCCESS",
    details: str = "",
) -> ActivityRow:
    """One activity row."""
    return ActivityRow(activity_id, event_time, event_type, source, target, resource_id, result, details)


def req(
    case_id: str,
    email: str,
    *,
    requested_at: str = "2026-05-01T08:00:00Z",
    reported_status: str = "COMPLETE",
    reported_at: str = "2026-05-02T12:00:00Z",
    audit_at: str = "2026-05-04T12:00:00Z",
    text: str = "Please delete my account.",
    source: RequestSource = "test",
) -> DeletionRequest:
    """One request."""
    return DeletionRequest(
        case_id,
        ident("email", email),
        requested_at,
        reported_status,  # type: ignore[arg-type]
        reported_at,
        audit_at,
        text,
        source,
    )


def sha(email: str) -> str:
    """The identities file's hash formula."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


@dataclass
class Person:
    """A made-up person for ``user_identities.csv``."""

    user_id: str
    email: str
    phone: str = "+1 555 0100"
    name: str = "Test Person"


@dataclass
class Dataset:
    """A tiny dataset directory: requests, identities, activity, manifest and evidence files."""

    requests: list[dict[str, str]] = field(default_factory=list)
    sample_requests: list[dict[str, str]] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    audit_rows: list[dict[str, str]] = field(default_factory=list)
    activity: list[dict[str, str]] = field(default_factory=list)
    files: list[tuple[str, str, str, bytes]] = field(default_factory=list)  # (file_id, path, captured_at, bytes)

    def add_request(self, case_id: str, email: str, *, sample: bool = False, **kw: str) -> None:
        """Add one request row (test file unless ``sample``)."""
        row = {
            "case_id": case_id,
            "email": email,
            "requested_at": kw.get("requested_at", "2026-05-01T08:00:00Z"),
            "reported_status": kw.get("reported_status", "COMPLETE"),
            "reported_at": kw.get("reported_at", "2026-05-02T12:00:00Z"),
            "audit_at": kw.get("audit_at", "2026-05-04T12:00:00Z"),
            "request_text": kw.get("request_text", "Please delete my account."),
        }
        (self.sample_requests if sample else self.requests).append(row)

    def add_activity(
        self,
        activity_id: str,
        event_time: str,
        event_type: str,
        source: str,
        target: str,
        resource_id: str,
        result: str,
        details: str,
    ) -> None:
        """Add one activity row."""
        self.activity.append(
            dict(
                activity_id=activity_id,
                event_time=event_time,
                event_type=event_type,
                source_system=source,
                target_system=target,
                resource_id=resource_id,
                reported_result=result,
                details=details,
            )
        )

    def add_file(self, file_id: str, path: str, captured_at: str, content: str | bytes) -> None:
        """Add one evidence file."""
        self.files.append((file_id, path, captured_at, content.encode() if isinstance(content, str) else content))

    def write(self, root: Path) -> Path:
        """Write everything under ``root`` and return it."""

        def w(name: str, header: list[str], rows: Iterable[dict[str, Any]]) -> None:
            with (root / name).open("w", newline="", encoding="utf-8") as fh:
                wr = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
                wr.writeheader()
                for r in rows:
                    wr.writerow(r)

        req_h = ["case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"]
        w("deletion_requests.csv", req_h, self.requests)
        w("sample_deletion_requests.csv", req_h, self.sample_requests)
        w(
            "user_identities.csv",
            ["user_id", "name", "email", "phone", "email_hash", "updated_at"],
            [
                dict(
                    user_id=p.user_id,
                    name=p.name,
                    email=p.email,
                    phone=p.phone,
                    email_hash=sha(p.email),
                    updated_at="2026-01-01T00:00:00Z",
                )
                for p in self.people
            ],
        )
        w(
            "user_audit_log.csv",
            ["audit_id", "user_id", "event_time", "field_name", "old_value", "new_value"],
            self.audit_rows,
        )
        w(
            "system_activity.csv",
            [
                "activity_id",
                "event_time",
                "event_type",
                "source_system",
                "target_system",
                "resource_id",
                "reported_result",
                "details",
            ],
            self.activity,
        )
        w(
            "evidence_files.csv",
            ["file_id", "file_path", "origin", "captured_at"],
            [dict(file_id=f, file_path=p, origin="fixture", captured_at=c) for f, p, c, _ in self.files],
        )
        (root / "deletion_rules.csv").write_bytes(RULES_CSV.read_bytes())
        for _, p, _, data in self.files:
            path = root / p
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return root


def temp_dir() -> tempfile.TemporaryDirectory[str]:
    """A temporary directory (caller cleans up)."""
    return tempfile.TemporaryDirectory(prefix="g5-test-")


def kv_line(t: str, **kv: str) -> str:
    """One kv-log line."""
    return t + " " + " ".join(f"{k}={json.dumps(v) if ' ' in v else v}" for k, v in kv.items()) + "\n"


def bundle(*snapshots: tuple[str, str, str, list[dict[str, Any]]]) -> str:
    """A snapshot bundle: (captured_at, data_store, collection, records) per snapshot."""
    return json.dumps(
        {
            "snapshots": [
                {"captured_at": c, "data_store": s, "collection": col, "records": recs} for c, s, col, recs in snapshots
            ]
        }
    )
