"""G5 fix round 2 at the engine: T105 (R04 per-record own key, R11 reasons), T104 (a) and (b), T108.

Each test names the behaviour of the base engine (commit 4dcd719) it replaces. Every value is made up
(``example.test`` emails, ``user_9xxx`` IDs); the case IDs are built at run time (``engine_fixtures.case``).
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from deletion_audit.engine import audit_all, build_context
from deletion_audit.evidence.model import Identifier, Observation
from deletion_audit.record import CaseRecord

from ..engine_fixtures import Dataset, Person, bundle, case, kv_line, obs, temp_dir

ADA, BO, CY = "ada@example.test", "bo@example.test", "cy@example.test"
C1 = case(9501)
AUDIT_LINE = kv_line(
    "2026-05-02T10:30:00Z",
    level="INFO",
    service="security_service",
    trace_id="t9",
    event="audit_record_read_completed",
    resource_id="audit_record_1",
    rows="1",
    subject_reference="user_9001",
)


def people() -> Dataset:
    d = Dataset(people=[Person("user_9001", ADA), Person("user_9002", BO, phone="+1 555 0102")])
    d.add_request(C1, ADA)
    return d


def audit_one(
    d: Dataset,
    *,
    rules_without: str | None = None,
    vision_read: frozenset[str] = frozenset(),
    images: tuple[Observation, ...] = (),
) -> tuple[tempfile.TemporaryDirectory[str], CaseRecord]:
    tmp = temp_dir()
    root = d.write(Path(tmp.name))
    if rules_without is not None:
        rules = root / "deletion_rules.csv"
        lines = rules.read_text(encoding="utf-8").splitlines(keepends=True)
        rules.write_text("".join(x for x in lines if f",{rules_without}," not in x), encoding="utf-8")
    ctx = build_context(root, image_observations=images)
    ctx = replace(ctx, vision_read=vision_read)
    return tmp, audit_all(ctx, [C1])[C1]


def codes(r: CaseRecord) -> set[str]:
    return {f.code for f in r.flags}


class OwnKeyPerRecord(unittest.TestCase):
    """T105 (1), the R04 shape: a lookup-only line can no longer claim a record whose own key is someone else's."""

    def trace(self, own: dict[str, str]) -> str:
        """Ada's lookup on a "started" line; the "completed" line of the same trace carries ``own``."""
        return kv_line(
            "2026-05-02T10:10:00Z",
            level="DEBUG",
            service="account_service",
            trace_id="t2",
            event="profile_lookup_started",
            resource_id="account_2",
            lookup_key=ADA,
        ) + kv_line(
            "2026-05-02T10:10:00Z",
            level="INFO",
            service="account_service",
            trace_id="t2",
            event="profile_lookup_completed",
            resource_id="account_2",
            http_status="200",
            rows="1",
            **own,
        )

    def own_account(self) -> str:
        return kv_line(
            "2026-05-02T10:00:00Z",
            level="INFO",
            service="account_service",
            trace_id="t1",
            event="profile_lookup_completed",
            resource_id="account_1",
            http_status="404",
            lookup_key=ADA,
        )

    def test_namesakes_live_account_gets_no_step(self) -> None:
        """Before: account_2 (Bo's own customer_reference and email) was linked to Ada through the
        started line's lookup key, and Ada's row asked to delete it."""
        d = people()
        log = self.own_account() + self.trace({"customer_reference": "user_9002", "email": BO}) + AUDIT_LINE
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", log)
        tmp, r = audit_one(d)
        with tmp:
            self.assertNotIn("account_2", {s.resource_id for s in r.steps})
            self.assertNotIn("account_2", {x.key.resource_id for x in r.resources})
            self.assertIsNone(r.failed_closed)

    def test_lookalike_own_key_on_another_line_gets_no_step(self) -> None:
        """A look-alike own key belongs to no one, and still beats the requester's lookup key."""
        d = people()
        log = self.own_account() + self.trace({"email": "ada.jr@example.test"}) + AUDIT_LINE
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", log)
        tmp, r = audit_one(d)
        with tmp:
            self.assertNotIn("account_2", {s.resource_id for s in r.steps})

    def test_own_key_in_another_file_also_counts(self) -> None:
        """Per record, whatever the file: Bo's own key is in a second file, not on Ada's trace."""
        d = people()
        started = self.trace({}).splitlines(keepends=True)[0]
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", self.own_account() + started + AUDIT_LINE)
        other = kv_line(
            "2026-05-02T11:00:00Z",
            level="INFO",
            service="account_service",
            trace_id="t7",
            event="profile_lookup_completed",
            resource_id="account_2",
            http_status="200",
            customer_reference="user_9002",
        )
        d.add_file("ev_2", "logs/b.log", "2026-05-03T00:00:00Z", other)
        tmp, r = audit_one(d)
        with tmp:
            self.assertNotIn("account_2", {s.resource_id for s in r.steps})

    def test_own_keys_naming_two_people_fail_the_row_closed(self) -> None:
        """Own keys resolve the record to Ada and to Bo: flagged, FAILED_CLOSED(OWN_KEY_CONFLICT), and
        the validator's safety net refuses the step on it."""
        d = people()
        log = self.own_account() + self.trace({"customer_reference": "user_9002", "email": ADA}) + AUDIT_LINE
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", log)
        tmp, r = audit_one(d)
        with tmp:
            self.assertEqual(
                (r.failed_closed, r.status, r.row_state), ("OWN_KEY_CONFLICT", "INCOMPLETE", "FAILED_CLOSED")
            )
            self.assertIn("OWN_KEY_CONFLICT", codes(r))
            self.assertNotIn("user_9002", " ".join(f.detail for f in r.flags))  # a count, not the other person's ID
            hard = {c.rule for c in r.checks if c.severity == "hard" and not c.ok}
            self.assertIn("OWN_KEY_OTHER_PERSON", hard)

    def test_lookup_agreeing_with_the_own_key_still_links(self) -> None:
        """The R05 shape: the own key (Ada's) is only in a post-audit file; the pre-audit lookup line
        agrees with it, so the account stays in the case."""
        d = people()
        started = self.trace({}).splitlines(keepends=True)[0]
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", started + AUDIT_LINE)
        late = kv_line(
            "2026-05-05T00:00:00Z",
            level="INFO",
            service="account_service",
            trace_id="t8",
            event="profile_lookup_completed",
            resource_id="account_2",
            http_status="404",
            email=ADA,
        )
        d.add_file("ev_late", "logs/late.log", "2026-05-05T01:00:00Z", late)
        tmp, r = audit_one(d)
        with tmp:
            self.assertIn("account_2", {x.key.resource_id for x in r.resources})


class DependencyReasons(unittest.TestCase):
    """T105 (3), the R11 shape: a missing file, a parse error and an unknown family each have their own reason."""

    def base(self) -> Dataset:
        d = people()
        own = kv_line(
            "2026-05-02T10:00:00Z",
            level="INFO",
            service="account_service",
            trace_id="t1",
            event="profile_lookup_completed",
            resource_id="account_1",
            http_status="404",
            lookup_key=ADA,
        )
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", own + AUDIT_LINE)
        return d

    def test_parse_error_alone(self) -> None:
        """Before: UNPARSED_DEPENDENCY. A SQL file cut off mid-INSERT cannot run."""
        d = self.base()
        d.add_file(
            "ev_sql", "databases/cut.sql", "2026-05-03T00:00:00Z", "CREATE TABLE t (a TEXT);\nINSERT INTO t VALUES ('x'"
        )
        tmp, r = audit_one(d)
        with tmp:
            self.assertEqual(r.failed_closed, "EVIDENCE_PARSE_ERROR")
            self.assertIn(
                ("FAILED_DEPENDENCY", "ev_sql: EVIDENCE_PARSE_ERROR (parse status ERROR)"),
                {(f.code, f.detail) for f in r.flags},
            )

    def test_unknown_family_alone(self) -> None:
        """Before: UNPARSED_DEPENDENCY. No family sniffer matches a truncated JSON object."""
        d = self.base()
        d.add_file(
            "ev_json", "records/cut.json", "2026-05-03T00:00:00Z", '{"exported_at": "2026-05-03T00:00:00Z", "rec'
        )
        tmp, r = audit_one(d)
        with tmp:
            self.assertEqual(r.failed_closed, "UNKNOWN_EVIDENCE_FAMILY")
            self.assertIn("ev_json: UNKNOWN_EVIDENCE_FAMILY (parse status UNKNOWN_FAMILY)", {f.detail for f in r.flags})

    def test_all_three_each_named_with_the_gravest_as_the_row_reason(self) -> None:
        """Before: the row said MISSING_EVIDENCE_FILE and nothing named the other two files' failures."""
        d = self.base()
        d.add_file(
            "ev_sql", "databases/cut.sql", "2026-05-03T00:00:00Z", "CREATE TABLE t (a TEXT);\nINSERT INTO t VALUES ('x'"
        )
        d.add_file(
            "ev_json", "records/cut.json", "2026-05-03T00:00:00Z", '{"exported_at": "2026-05-03T00:00:00Z", "rec'
        )
        d.add_file("ev_gone", "records/gone.json", "2026-05-03T00:00:00Z", "{}")
        tmp = temp_dir()
        root = d.write(Path(tmp.name))
        (root / "records" / "gone.json").unlink()
        with tmp:
            r = audit_all(build_context(root), [C1])[C1]
            self.assertEqual((r.failed_closed, r.status), ("MISSING_EVIDENCE_FILE", "INCOMPLETE"))
            got = sorted(f.detail for f in r.flags if f.code == "FAILED_DEPENDENCY")
            self.assertEqual(
                got,
                [
                    "ev_gone: MISSING_EVIDENCE_FILE (parse status ERROR)",
                    "ev_json: UNKNOWN_EVIDENCE_FAMILY (parse status UNKNOWN_FAMILY)",
                    "ev_sql: EVIDENCE_PARSE_ERROR (parse status ERROR)",
                ],
            )


class NoCategoryRule(unittest.TestCase):
    """T104 (a): a state that no rule covers fails the row closed; T69 stays exactly as it is."""

    def test_record_with_a_state_but_no_rule_fails_closed(self) -> None:
        """account_7 is known by a catalog row only, so its state is the R8 default ABSENT; this rules
        file has no USER_PROFILE row. Before: NO_STEP, silently, and the row was COMPLETE."""
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        d.add_activity(
            "a_1",
            "2026-05-02T09:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "account_service",
            "account_7",
            "SUCCESS",
            f"Data catalog linked account_7 (account_7) to {ADA} and user_9001.",
        )
        tmp, r = audit_one(d, rules_without="USER_PROFILE")
        with tmp:
            acc = [x for x in r.resources if x.key.resource_id == "account_7"]
            self.assertEqual([(x.state.value, x.decision.outcome) for x in acc], [("ABSENT", "NO_STEP")])
            self.assertIn("NO_CATEGORY_RULE", {f.code for f in acc[0].flags})
            self.assertEqual((r.failed_closed, r.status), ("NO_CATEGORY_RULE", "INCOMPLETE"))
            self.assertNotIn("account_7", {s.resource_id for s in r.steps})  # no invented step

    def test_same_dataset_with_the_full_rules_file_is_unchanged(self) -> None:
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        d.add_activity(
            "a_1",
            "2026-05-02T09:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "account_service",
            "account_7",
            "SUCCESS",
            f"Data catalog linked account_7 (account_7) to {ADA} and user_9001.",
        )
        tmp, r = audit_one(d)
        with tmp:
            self.assertNotIn("NO_CATEGORY_RULE", codes(r))
            self.assertIn(("account_7", "VERIFY_RECORD_ABSENT"), {(s.resource_id, s.operation) for s in r.steps})

    def test_t69_hold_naming_no_resource_still_gives_no_step(self) -> None:
        """T69 boundary: a legal-hold register line that names the person but no resource is not a
        record, so it gives no step, no NO_CATEGORY_RULE flag, and the row stays COMPLETE."""
        d = people()
        hold = kv_line(
            "2026-05-02T10:40:00Z",
            level="INFO",
            service="legal_service",
            trace_id="t4",
            event="retained_order_loaded",
            subject_ref="user_9001",
            order_number="ORD-9001",
            retain_until="2033-12-31T23:59:59Z",
        )
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE + hold)
        tmp, r = audit_one(d)
        with tmp:
            self.assertEqual((r.status, r.failed_closed), ("COMPLETE", None))
            self.assertNotIn("legal_service", {x.key.system_id for x in r.resources})
            self.assertFalse(codes(r) & {"NO_CATEGORY_RULE", "UNINTERPRETED_RECORD"})

    def test_hold_naming_a_resource_gets_verify_present(self) -> None:
        """The other side of T69: a hold that names a resource is a retained record (rule_13)."""
        d = people()
        hold = kv_line(
            "2026-05-02T10:40:00Z",
            level="INFO",
            service="legal_service",
            trace_id="t4",
            event="legal_hold_read_completed",
            resource_id="legal_hold_1",
            rows="1",
            subject_ref="user_9001",
        )
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE + hold)
        tmp, r = audit_one(d)
        with tmp:
            self.assertIn(("legal_hold_1", "VERIFY_RECORD_PRESENT"), {(s.resource_id, s.operation) for s in r.steps})
            self.assertNotIn("NO_CATEGORY_RULE", codes(r))


class PresentClaimOverState(unittest.TestCase):
    """T104 (b): a retained record whose derived state is not PRESENT keeps VERIFY_RECORD_PRESENT, flagged."""

    def test_absent_audit_record_is_flagged_and_its_step_kept(self) -> None:
        """Before: no flag, so the artifacts claimed presence over the engine's own ABSENT state. The DEV
        shape (9 audit records): a later declared scope of security_audit_events omits the record."""
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        d.add_file(
            "ev_b",
            "records/bundle.json",
            "2026-05-04T00:00:00Z",
            bundle(("2026-05-03T12:00:00Z", "security_service", "security_audit_events", [])),
        )
        tmp, r = audit_one(d)
        with tmp:
            rec = [x for x in r.resources if x.key.resource_id == "audit_record_1"]
            self.assertEqual([x.state.value for x in rec], ["ABSENT"])
            self.assertIn(("audit_record_1", "VERIFY_RECORD_PRESENT"), {(s.resource_id, s.operation) for s in r.steps})
            self.assertIn("PRESENT_CLAIM_OVER_STATE", {f.code for f in rec[0].flags})

    def test_present_audit_record_is_not_flagged(self) -> None:
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        tmp, r = audit_one(d)
        with tmp:
            self.assertNotIn("PRESENT_CLAIM_OVER_STATE", codes(r))


class ImageOmitsCatalogRecord(unittest.TestCase):
    """T108: a catalog-only record whose screenshot was read OK and does not show it fails the row closed."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    def world_parts(self) -> Dataset:
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        d.add_file("ev_img", "images/console.png", "2026-05-02T11:00:00Z", self.PNG)
        d.add_activity(
            "a_4",
            "2026-05-02T11:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "search_service",
            "search_7",
            "SUCCESS",
            f"Data catalog linked search_7 (search_7) to {ADA} and user_9001.",
        )
        return d

    def other_record(self) -> tuple[Observation, ...]:
        """The image reading: it shows a different record, never search_7."""
        return (
            obs(
                "search_8",
                file_id="ev_img",
                system="search_service",
                captured_at="2026-05-02T11:00:00Z",
                family="image",
                kind="image",
                ref="img",
            ),
        )

    def test_read_image_without_the_record_fails_closed(self) -> None:
        """Before: no state, no step, no flag, and nothing failed closed (only the model-on gate saw it)."""
        tmp, r = audit_one(self.world_parts(), vision_read=frozenset({"ev_img"}), images=self.other_record())
        with tmp:
            self.assertEqual((r.failed_closed, r.status), ("IMAGE_OMITS_CATALOG_RECORD", "INCOMPLETE"))
            s7 = [x for x in r.resources if x.key.resource_id == "search_7"]
            self.assertEqual([x.decision.outcome for x in s7], ["NO_STEP"])
            self.assertIn("IMAGE_OMITS_CATALOG_RECORD", {f.code for f in s7[0].flags})
            self.assertEqual(r.failed_dependencies, frozenset())  # the image was read: not a dependency

    def test_unread_image_stays_an_unparsed_dependency(self) -> None:
        tmp, r = audit_one(self.world_parts())
        with tmp:
            self.assertEqual(r.failed_closed, "UNPARSED_DEPENDENCY")
            self.assertNotIn("IMAGE_OMITS_CATALOG_RECORD", codes(r))

    def test_no_image_at_all_keeps_the_r8_no_step_rule(self) -> None:
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        d.add_activity(
            "a_4",
            "2026-05-02T11:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "search_service",
            "search_7",
            "SUCCESS",
            f"Data catalog linked search_7 (search_7) to {ADA} and user_9001.",
        )
        tmp, r = audit_one(d)
        with tmp:
            self.assertEqual((r.status, r.failed_closed), ("COMPLETE", None))
            self.assertNotIn("IMAGE_OMITS_CATALOG_RECORD", codes(r))


def image_obs(
    rid: str, system: str, *, record: tuple[Identifier, ...] = (), attrs: dict[str, str] | None = None
) -> Observation:
    """An image observation as ``agent/vision.py`` builds it (locator kind ``image``)."""
    return obs(
        rid,
        file_id="ev_img",
        system=system,
        time=None,
        captured_at="2026-05-02T11:00:00Z",
        family="image",
        kind="image",
        ref=f"record:{rid}",
        record=record,
        attrs=attrs,
    )


class ImageStateRule(unittest.TestCase):
    """T112 item 9: an image sets a state only from what is visibly on screen."""

    def test_nothing_transcribed_gives_no_state(self) -> None:
        """Before: support defaulted to REDACTED, analytics to ANONYMIZED, a tombstone to REDACTED."""
        from deletion_audit.state.observe import observation_state

        for rid, system in (
            ("support_1", "support_platform"),
            ("analytics_1", "analytics_platform"),
            ("tombstone_1", "identity_service"),
            ("search_1", "search_service"),
        ):
            self.assertIsNone(observation_state(image_obs(rid, system), system), system)

    def test_status_label_maps_to_no_state(self) -> None:
        from deletion_audit.state.observe import observation_state

        o = image_obs("support_1", "support_platform", attrs={"status_label": "Redacted"})
        self.assertIsNone(observation_state(o, "support_platform"))

    def test_visible_marker_of_the_text_kind_gives_the_cleaned_state(self) -> None:
        from deletion_audit.state.observe import observation_state

        self.assertEqual(
            observation_state(
                image_obs("support_1", "support_platform", attrs={"visible_marker": "[REDACTED]"}), "support_platform"
            ),
            "REDACTED",
        )
        self.assertEqual(
            observation_state(
                image_obs("analytics_1", "analytics_platform", attrs={"visible_marker": "[ANONYMIZED]"}),
                "analytics_platform",
            ),
            "ANONYMIZED",
        )
        self.assertIsNone(
            observation_state(
                image_obs("analytics_1", "analytics_platform", attrs={"visible_marker": "[REDACTED]"}),
                "analytics_platform",
            )
        )

    def test_transcribed_subject_gives_the_holding_state(self) -> None:
        from deletion_audit.state.observe import observation_state

        from ..engine_fixtures import ident

        who = (ident("email", ADA),)
        got = {
            sysid: observation_state(image_obs("x_1", sysid, record=who, attrs={"email": ADA}), sysid)
            for sysid in ("support_platform", "analytics_platform", "identity_service", "search_service")
        }
        self.assertEqual(
            got,
            {
                "support_platform": "IDENTIFIABLE",
                "analytics_platform": "IDENTIFIABLE",
                "identity_service": "EXPOSED_PII",
                "search_service": "PRESENT",
            },
        )
        marked = image_obs(
            "support_1", "support_platform", record=who, attrs={"email": ADA, "visible_marker": "[REDACTED]"}
        )
        self.assertEqual(observation_state(marked, "support_platform"), "IDENTIFIABLE")  # a subject on screen wins

    def test_vision_record_markers_and_label_reach_the_observation_verbatim(self) -> None:
        from deletion_audit.agent.schemas import parse_vision
        from deletion_audit.agent.vision import merge_readings, record_attrs

        value = {
            "records": [
                {
                    "shown_id": "support_1",
                    "subject_emails": [],
                    "subject_phones": [],
                    "subject_names": [],
                    "subject_user_ids": [],
                    "sync_enabled": "not_shown",
                    "restore_allowed": "not_shown",
                    "marked_deleted": "not_shown",
                    "download_available": "not_shown",
                    "visible_markers": ["[REDACTED]"],
                    "status_label": "Closed",
                }
            ],
            "unreadable": [],
            "instruction_like_text": False,
        }
        rec = merge_readings([parse_vision(value), parse_vision(value)]).records[0]
        self.assertEqual(record_attrs(rec), {"visible_marker": "[REDACTED]", "status_label": "Closed"})

    def test_a_shown_support_record_with_nothing_transcribed_never_gives_complete(self) -> None:
        """The verifier's finding 1 shape, end to end in the engine: Ada's support record is known by a
        catalog row; the read screenshot shows its ID only. Before: REDACTED, COMPLIANT, COMPLETE."""
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        d.add_file("ev_img", "images/console.png", "2026-05-02T11:00:00Z", ImageOmitsCatalogRecord.PNG)
        d.add_activity(
            "a_4",
            "2026-05-02T11:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "support_platform",
            "support_7",
            "SUCCESS",
            f"Data catalog linked support_7 (support_7) to {ADA} and user_9001.",
        )
        tmp, r = audit_one(d, vision_read=frozenset({"ev_img"}), images=(image_obs("support_7", "support_platform"),))
        with tmp:
            self.assertNotEqual(r.status, "COMPLETE")
            self.assertIsNotNone(r.failed_closed)


class BackupRuleF(unittest.TestCase):
    """T114 item 13: a backup whose state comes from an image reading."""

    def backup_row(self, attrs: dict[str, str] | None) -> CaseRecord:
        d = people()
        d.add_file("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", AUDIT_LINE)
        d.add_file("ev_img", "images/console.png", "2026-05-02T11:00:00Z", ImageOmitsCatalogRecord.PNG)
        d.add_activity(
            "a_4",
            "2026-05-02T11:07:01Z",
            "LINK_RESOURCE_IDENTITY",
            "data_catalog",
            "backup_service",
            "backup_7",
            "SUCCESS",
            f"Data catalog linked backup_7 (backup_7) to {ADA} and user_9001.",
        )
        tmp, r = audit_one(
            d, vision_read=frozenset({"ev_img"}), images=(image_obs("backup_7", "backup_service", attrs=attrs),)
        )
        self.addCleanup(tmp.cleanup)
        return r

    def ops(self, r: CaseRecord) -> list[tuple[str, str]]:
        return [(s.phase, s.operation) for s in r.steps if s.resource_id == "backup_7"]

    def test_no_visible_cue_is_an_active_restore_path(self) -> None:
        """Before: no state from the image (no restore field), so the backup got no step."""
        r = self.backup_row(None)
        self.assertEqual(
            self.ops(r),
            [
                ("FINDING", "REPORT_RESTORE_RISK"),
                ("REMEDIATION", "BLOCK_RESTORE"),
                ("VERIFICATION", "VERIFY_RESTORE_BLOCKED"),
            ],
        )
        self.assertEqual(r.status, "INCOMPLETE")

    def test_visible_blocked_marker_gives_verify_only(self) -> None:
        r = self.backup_row({"visible_marker": "Restore blocked"})
        self.assertEqual(self.ops(r), [("VERIFICATION", "VERIFY_RESTORE_BLOCKED")])

    def test_text_backups_keep_their_rules(self) -> None:
        from deletion_audit.state.observe import observation_state

        text = obs("backup_7", system="backup_service", attrs={"backup_name": "nightly"})
        self.assertIsNone(observation_state(text, "backup_service"))  # unchanged: no restore field, no state


if __name__ == "__main__":
    unittest.main()
