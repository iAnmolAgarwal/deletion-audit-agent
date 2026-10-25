"""Policy: categories (R11, T55), the decision table, retain classes, backups and holds (T9, T42, T69)."""

from __future__ import annotations

import unittest
from pathlib import Path

from deletion_audit.policy import categorize, decide, load_rules
from deletion_audit.policy.rules import PolicyDecision
from deletion_audit.state import ResourceKey, ResourceState

from ..engine_fixtures import act, obs

RULES = load_rules(Path(__file__).resolve().parents[3] / "dataset")
AUDIT = "2026-05-04T12:00:00Z"
STATES = (
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
)


def st(key: ResourceKey, value: str | None) -> ResourceState:
    return ResourceState(key, value, "latest_observation", None, None)


class Categories(unittest.TestCase):
    """R11 and T55."""

    def test_support_category_cue_else_worker_action_flagged(self) -> None:
        key = ResourceKey("support_platform", "support_1")
        cue = obs("support_1", event="attachment_pii_scan")
        self.assertEqual(categorize(key, [cue], [], AUDIT).category, "SUPPORT_ATTACHMENT")
        late_cue = obs("support_1", event="attachment_pii_scan", time="2026-05-09T00:00:00Z")
        worker = [act("a1", "2026-05-02T00:00:00Z", "DELETE_RECORD", "support_1", target="support_platform")]
        got = categorize(key, [late_cue], worker, AUDIT)  # cue after audit_at is not visible
        self.assertEqual((got.category, got.basis), ("SUPPORT_ATTACHMENT", "worker_action"))
        self.assertEqual(got.flag.code if got.flag else None, "SUPPORT_CATEGORY_FROM_WORKER")
        redact = [act("a1", "2026-05-02T00:00:00Z", "REDACT_RECORD", "support_1", target="support_platform")]
        self.assertEqual(categorize(key, [], redact, AUDIT).category, "SUPPORT_MESSAGE")
        self.assertEqual(categorize(key, [], [], AUDIT).category, "SUPPORT_MESSAGE")

    def test_pdf_attachment_cue_is_document_level(self) -> None:
        key = ResourceKey("support_platform", "support_1")
        page = obs("support_1", kind="pdf_page", family="pdf_text", file_id="ev_pdf", time=None, text="request")
        self.assertEqual(
            categorize(key, [page], [], AUDIT, attachment_documents=frozenset({"ev_pdf"})).category,
            "SUPPORT_ATTACHMENT",
        )

    def test_analytics_contact_record_is_marketing(self) -> None:
        key = ResourceKey("analytics_platform", "analytics_1")
        self.assertEqual(
            categorize(key, [obs("analytics_1", event="contact_lookup_completed")], [], AUDIT).category,
            "MARKETING_PROFILE",
        )
        self.assertEqual(categorize(key, [obs("analytics_1")], [], AUDIT).category, "ANALYTICS_PROFILE")


class Decisions(unittest.TestCase):
    """The decision table and its safety rules."""

    def _decide(self, system: str, value: str | None) -> PolicyDecision:
        key = ResourceKey(system, "x_1")
        return decide(st(key, value), categorize(key, [], [], AUDIT), RULES)

    def test_delete_class(self) -> None:
        d = self._decide("account_service", "PRESENT")
        self.assertEqual(
            (d.outcome, d.finding_op, d.remediation_op, d.verification_op),
            ("FINDING", "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT"),
        )
        self.assertEqual(self._decide("account_service", "ABSENT").verification_op, "VERIFY_RECORD_ABSENT")

    def test_retain_class_never_gets_delete(self) -> None:
        for system in ("security_service", "legal_service", "backup_service"):
            for value in STATES:
                d = self._decide(system, value)
                with self.subTest(system=system, value=value):
                    self.assertNotIn(d.remediation_op, ("DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"))
                    self.assertNotEqual(d.finding_op, "REPORT_REMAINING_RECORD")

    def test_legal_hold_never_deleted(self) -> None:
        for value in STATES:
            d = self._decide("legal_service", value)
            self.assertEqual((d.outcome, d.verification_op), ("COMPLIANT", "VERIFY_RECORD_PRESENT"))

    def test_backup_follows_restore_path_not_present(self) -> None:
        d = self._decide("backup_service", "RESTORABLE")
        self.assertEqual(
            (d.finding_op, d.remediation_op, d.verification_op),
            ("REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED"),
        )
        for value in STATES:
            self.assertNotEqual(self._decide("backup_service", value).verification_op, "VERIFY_RECORD_PRESENT")

    def test_no_state_gives_no_step(self) -> None:
        self.assertEqual(self._decide("search_service", None).outcome, "NO_STEP")

    def test_hold_register_without_resource_gives_no_step(self) -> None:
        """T69, on real data: the hold register PDF names people but no resource, so it links nothing."""
        from deletion_audit.engine import build_context, build_world

        ctx = build_context(Path(__file__).resolve().parents[3] / "dataset")
        w = build_world(ctx)
        register_pages = {
            (o.file_id, o.locator.ref)
            for o in ctx.index.observations()
            if o.locator.kind == "pdf_page"
            and o.resource_id is None
            and sum(1 for i in o.record_identifiers if i.kind == "user_id") > 1
        }
        self.assertTrue(register_pages)
        self.assertTrue(register_pages <= w.links.blocked_pages)
        for links in w.case_links.values():
            for lk in links:
                self.assertNotIn((lk.file_id, lk.observation.locator.ref if lk.observation else None), register_pages)


if __name__ == "__main__":
    unittest.main()
