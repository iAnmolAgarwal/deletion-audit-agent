"""Developer ruling T86: missing files, malformed request rows, free-text PII, hashes, legal holds."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deletion_audit.engine import audit_all, build_context
from deletion_audit.inputs.requests import load_requests_checked
from deletion_audit.pipeline import run
from deletion_audit.record import CaseRecord

from ..engine_fixtures import Dataset, Person, bundle, case, kv_line, sha, temp_dir

C1 = case(9001)
C2 = case(9002)
C3 = case(9003)
ADA, BO = "ada@example.test", "bo@example.test"
HEADER = "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\n"
GOOD = "{c},{e},2026-05-01T08:00:00Z,COMPLETE,2026-05-02T12:00:00Z,2026-05-04T12:00:00Z,Please delete.\n"


def two_people() -> Dataset:
    d = Dataset(people=[Person("user_9001", ADA), Person("user_9002", BO)])
    d.add_request(C1, ADA)
    return d


def audit(d: Dataset, cases: list[str]) -> tuple[tempfile.TemporaryDirectory[str], dict[str, CaseRecord]]:
    tmp = temp_dir()
    ctx = build_context(d.write(Path(tmp.name)))
    return tmp, audit_all(ctx, cases)


class MissingFile(unittest.TestCase):
    """Item 1: a missing evidence file makes the row FAILED_CLOSED, INCOMPLETE, even with findings."""

    def test_missing_file_fails_closed_with_remaining_steps(self) -> None:
        d = two_people()
        d.add_file(
            "ev_1",
            "logs/a.log",
            "2026-05-03T00:00:00Z",
            kv_line(
                "2026-05-02T10:00:00Z",
                level="INFO",
                service="account_service",
                trace_id="t1",
                event="profile_lookup_completed",
                resource_id="account_1",
                http_status="200",
                correlation_key=ADA,
            ),
        )
        d.add_file("ev_gone", "logs/gone.log", "2026-05-02T00:00:00Z", "")
        tmp = temp_dir()
        root = d.write(Path(tmp.name))
        (root / "logs" / "gone.log").unlink()
        with tmp:
            r = audit_all(build_context(root), [C1])[C1]
            self.assertEqual((r.failed_closed, r.status), ("MISSING_EVIDENCE_FILE", "INCOMPLETE"))
            self.assertIn("REPORT_REMAINING_RECORD", [s.operation for s in r.steps])  # the steps still given
            self.assertIn("ev_gone", r.failed_dependencies)


class MalformedRequests(unittest.TestCase):
    """Item 2: bad request rows are isolated; valid rows next to them load normally."""

    def _write(self, body: str) -> tempfile.TemporaryDirectory[str]:
        tmp = temp_dir()
        two_people().write(Path(tmp.name))
        (Path(tmp.name) / "deletion_requests.csv").write_text(HEADER + body, encoding="utf-8")
        return tmp

    def test_bad_rows_isolated(self) -> None:
        body = (
            GOOD.format(c=C1, e=ADA)
            + f"{C2},bo@example.test,not-a-time,COMPLETE,2026-05-02T12:00:00Z,2026-05-04T12:00:00Z,x\n"
            + ",only,three\n"
            + GOOD.format(c=C3, e=BO)
        )
        with self._write(body) as tmp:
            reqs, issues = load_requests_checked(Path(tmp))
            self.assertEqual([r.case_id for r in reqs if r.source == "test"], [C1, C3])
            self.assertEqual([(i.line, i.case_id) for i in issues], [(3, C2), (4, None)])
            with temp_dir() as runs:
                s = run(Path(tmp), run_id="t86", cases="test", runs_dir=Path(runs))
                rows = (Path(runs) / "t86" / "output.csv").read_text().splitlines()[1:]
                self.assertEqual([x.split(",")[0] for x in rows], [C1, C2, C3])
                self.assertTrue(rows[1].startswith(f"{C2},INCOMPLETE,[]"))
                producer = json.loads((Path(runs) / "t86" / "producer.json").read_text())
                self.assertEqual(
                    [(i["line"], i["case_id"]) for i in producer["request_issues"]], [(3, C2), (4, None)]
                )
                self.assertEqual(s.metrics["failed_closed"]["by_reason"].get("MALFORMED_REQUEST"), 1)

    def test_duplicate_case_id_uses_neither_row(self) -> None:
        with self._write(GOOD.format(c=C1, e=ADA) + GOOD.format(c=C1, e=BO)) as tmp:
            reqs, issues = load_requests_checked(Path(tmp))
            self.assertEqual([r.case_id for r in reqs if r.source == "test"], [])
            self.assertEqual({i.reason for i in issues}, {"duplicate case_id"})


class FreeTextAndHashes(unittest.TestCase):
    """Items 3 and 4 (T49, T59)."""

    def _support(self, text: str) -> CaseRecord:
        d = two_people()
        d.add_file(
            "ev_b",
            "records/b.json",
            "2026-05-03T00:00:00Z",
            bundle(
                (
                    "2026-05-02T13:00:00Z",
                    "support_platform",
                    "support_conversations",
                    [{"resource_id": "support_1", "customer_reference": "user_9001", "message_text": text}],
                )
            ),
        )
        tmp, recs = audit(d, [C1])
        with tmp:
            return recs[C1]

    def test_exact_email_in_free_text_is_pii_lookalike_is_not(self) -> None:
        exact = self._support(f"Please reach me at {ADA} about the parcel.")
        self.assertIn("REPORT_EXPOSED_PII", [s.operation for s in exact.steps])
        lookalike = self._support("Please reach me at ada.jr@example.test about the parcel.")
        self.assertNotIn("REPORT_EXPOSED_PII", [s.operation for s in lookalike.steps])
        self.assertIn("VERIFY_RECORD_REDACTED", [s.operation for s in lookalike.steps])

    def test_record_holding_only_the_email_hash_is_the_persons(self) -> None:
        d = two_people()
        d.add_file(
            "ev_b",
            "records/b.json",
            "2026-05-03T00:00:00Z",
            bundle(
                (
                    "2026-05-02T13:00:00Z",
                    "analytics_platform",
                    "customer_analytics_reports",
                    [{"resource_id": "analytics_1", "email_hash": sha(ADA)}],
                )
            ),
        )
        tmp, recs = audit(d, [C1])
        with tmp:
            r = recs[C1]
            self.assertIn("analytics_1", [x.key.resource_id for x in r.resources])
            self.assertIn("REPORT_EXPOSED_PII", [s.operation for s in r.steps])


class LegalHold(unittest.TestCase):
    """Item 5: a hold's system comes from the line naming it; VERIFY_RECORD_PRESENT, cited only in COMPLETE."""

    def _hold(self, with_finding: bool) -> CaseRecord:
        d = two_people()
        lines = kv_line(
            "2026-05-02T10:00:00Z",
            level="INFO",
            service="legal_service",
            trace_id="t1",
            event="retained_order_loaded",
            resource_id="legal_hold_1",
            subject_ref="user_9001",
        )
        if with_finding:
            lines += kv_line(
                "2026-05-02T10:00:05Z",
                level="INFO",
                service="account_service",
                trace_id="t2",
                event="profile_lookup_completed",
                resource_id="account_1",
                http_status="200",
                correlation_key=ADA,
            )
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", lines)
        tmp, recs = audit(d, [C1])
        with tmp:
            return recs[C1]

    def test_hold_verified_present_empty_in_incomplete_cited_in_complete(self) -> None:
        for with_finding, status, cite in ((True, "INCOMPLETE", ""), (False, "COMPLETE", "ev_1")):
            r = self._hold(with_finding)
            hold = [s for s in r.steps if s.resource_id == "legal_hold_1"]
            self.assertEqual(r.status, status)
            self.assertEqual(
                [(s.system_id, s.operation, s.evidence_id) for s in hold],
                [("legal_service", "VERIFY_RECORD_PRESENT", cite)],
            )


if __name__ == "__main__":
    unittest.main()
