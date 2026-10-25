"""Tests of the CSV loaders: exact times, IDs copied, audit_id kept, malformed rows raise."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from deletion_audit.inputs import (
    InputFormatError,
    load_activity,
    load_audit_log,
    load_identities,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET = REPO_ROOT / "dataset"

ACTIVITY = (
    "activity_id,event_time,event_type,source_system,target_system,resource_id,reported_result,details\n"
    "activity_007,2026-01-04T14:56:59Z,DELETE_RECORD,privacy_workflow,archive_service,audit_record_0042,"
    "FAILED,\"Delete attempted, see ticket\"\n"
    "activity_008,2026-01-04T14:57:00+05:30,CLASSIFY_REQUEST,privacy_workflow,privacy_case_management,,,"
    "Request classified.\n"
)
IDENTITIES = (
    "user_id,name,email,phone,email_hash,updated_at\n"
    "user_07,Ada Lovelace,Ada.Lovelace@Example.Test,+1 (202) 555-0101,ABC123,2026-03-14T14:21:59Z\n"
    "user_08,,,,,2026-03-14T14:22:00Z\n"
)
AUDIT = (
    "audit_id,user_id,event_time,field_name,old_value,new_value\n"
    "audit_009,user_07,2025-01-04T00:11:24Z,email,Old.Ada@Example.Test,ada.lovelace@example.test\n"
    "audit_010,user_07,2025-01-05T00:11:25Z,phone,+44 20 7946 0001,+1 (202) 555-0101\n"
    "audit_011,user_07,2025-01-06T00:11:26Z,display_name,Ada,Ada L.\n"
)


class TempInputs:
    """A temporary dataset directory holding the three CSV inputs."""

    def __init__(self, activity: str = ACTIVITY, identities: str = IDENTITIES,
                 audit: str = AUDIT) -> None:
        """Write the three files."""
        self.dir = Path(tempfile.mkdtemp(prefix="gp_inputs_"))
        (self.dir / "system_activity.csv").write_text(activity, encoding="utf-8")
        (self.dir / "user_identities.csv").write_text(identities, encoding="utf-8")
        (self.dir / "user_audit_log.csv").write_text(audit, encoding="utf-8")

    def cleanup(self) -> None:
        """Remove the directory."""
        shutil.rmtree(self.dir, ignore_errors=True)


class LoaderFixtures(unittest.TestCase):
    """Typed rows from small fictional inputs."""

    def setUp(self) -> None:
        self.inputs = TempInputs()
        self.addCleanup(self.inputs.cleanup)

    def test_activity_rows(self) -> None:
        rows = load_activity(self.inputs.dir)
        self.assertEqual([r.activity_id for r in rows], ["activity_007", "activity_008"])
        first, second = rows
        self.assertEqual(first.event_time, "2026-01-04T14:56:59Z")
        self.assertEqual(first.resource_id, "audit_record_0042")
        self.assertEqual(first.target_system, "archive_service")
        self.assertEqual(first.details, "Delete attempted, see ticket")
        self.assertEqual(second.event_time, "2026-01-04T09:27:00Z")
        self.assertIsNone(second.resource_id)
        self.assertIsNone(second.reported_result)

    def test_identity_rows(self) -> None:
        first, second = load_identities(self.inputs.dir)
        assert first.email is not None and first.phone is not None
        self.assertEqual(first.user_id, "user_07")
        self.assertEqual(first.updated_at, "2026-03-14T14:21:59Z")
        self.assertEqual((first.email.kind, first.email.value, first.email.raw),
                         ("email", "ada.lovelace@example.test", "Ada.Lovelace@Example.Test"))
        self.assertEqual((first.phone.kind, first.phone.value, first.phone.raw),
                         ("phone", "+12025550101", "+1 (202) 555-0101"))
        self.assertEqual(first.email_hash, "ABC123")
        self.assertEqual((second.name, second.email, second.phone, second.email_hash),
                         (None, None, None, None))

    def test_audit_rows(self) -> None:
        rows = load_audit_log(self.inputs.dir)
        self.assertEqual([r.audit_id for r in rows], ["audit_009", "audit_010", "audit_011"])
        email, phone, other = rows
        assert email.old_identifier is not None
        assert phone.old_identifier is not None and phone.new_identifier is not None
        self.assertEqual(email.event_time, "2025-01-04T00:11:24Z")
        self.assertEqual(email.old_value, "Old.Ada@Example.Test")
        self.assertEqual((email.old_identifier.kind, email.old_identifier.value,
                          email.old_identifier.field),
                         ("email", "old.ada@example.test", "old_value"))
        self.assertEqual(phone.old_identifier.value, "+442079460001")
        self.assertEqual(phone.new_identifier.value, "+12025550101")
        self.assertIsNone(other.old_identifier)
        self.assertIsNone(other.new_identifier)
        self.assertEqual(other.new_value, "Ada L.")


class MalformedInputs(unittest.TestCase):
    """Every malformed row raises InputFormatError naming the file and line."""

    def _raises(self, loader: Callable[[Path], object], **files: str) -> InputFormatError:
        inputs = TempInputs(**files)
        self.addCleanup(inputs.cleanup)
        with self.assertRaises(InputFormatError) as caught:
            loader(inputs.dir)
        return caught.exception

    def test_wrong_field_count(self) -> None:
        exc = self._raises(load_activity, activity=ACTIVITY + "activity_009,2026-01-04T14:56:59Z,X\n")
        self.assertEqual((exc.file_name, exc.line), ("system_activity.csv", 4))
        self.assertIn("system_activity.csv line 4", str(exc))

    def test_empty_required_field(self) -> None:
        exc = self._raises(load_identities, identities=IDENTITIES + ",Nobody,,,,2026-03-14T14:22:00Z\n")
        self.assertEqual((exc.file_name, exc.line), ("user_identities.csv", 4))
        self.assertIn("user_id", exc.reason)

    def test_bad_time(self) -> None:
        exc = self._raises(load_audit_log,
                           audit=AUDIT + "audit_012,user_07,2025-01-06 00:11,email,a@x.test,b@x.test\n")
        self.assertEqual((exc.file_name, exc.line), ("user_audit_log.csv", 5))

    def test_time_without_zone_is_rejected(self) -> None:
        exc = self._raises(load_audit_log,
                           audit=AUDIT + "audit_012,user_07,2025-01-06T00:11:26,email,a@x.test,b@x.test\n")
        self.assertEqual(exc.line, 5)

    def test_bad_header(self) -> None:
        exc = self._raises(load_activity, activity="activity_id,event_time\nactivity_1,2026-01-01T00:00:00Z\n")
        self.assertEqual(exc.line, 1)


class RealInputs(unittest.TestCase):
    """The real inputs load completely, in file order, with exact-second times."""

    def test_counts_and_order(self) -> None:
        activity = load_activity(DATASET)
        identities = load_identities(DATASET)
        audit = load_audit_log(DATASET)
        self.assertEqual((len(activity), len(identities), len(audit)), (4011, 850, 306))
        self.assertEqual(activity[0].activity_id, "activity_01")
        self.assertEqual(activity[-1].activity_id, "activity_4011")
        self.assertEqual(audit[0].audit_id, "audit_01")

    def test_times_and_ids_copied_exactly(self) -> None:
        import csv
        with (DATASET / "user_audit_log.csv").open(newline="", encoding="utf-8") as handle:
            raw = list(csv.DictReader(handle))
        for row, typed in zip(raw, load_audit_log(DATASET), strict=False):
            self.assertEqual(typed.audit_id, row["audit_id"])
            self.assertEqual(typed.event_time, row["event_time"])
            self.assertEqual(typed.old_value, row["old_value"] or None)
        with (DATASET / "system_activity.csv").open(newline="", encoding="utf-8") as handle:
            raw_activity = list(csv.DictReader(handle))
        for row, typed_activity in zip(raw_activity, load_activity(DATASET), strict=False):
            self.assertEqual((typed_activity.activity_id, typed_activity.event_time, typed_activity.resource_id),
                             (row["activity_id"], row["event_time"], row["resource_id"] or None))


if __name__ == "__main__":
    unittest.main()
