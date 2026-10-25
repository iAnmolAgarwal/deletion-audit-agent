"""Identifier-free analytics by policy slot band (T53), following the job's account (T62), one owner (T29)."""

from __future__ import annotations

import unittest
from collections.abc import Mapping

from deletion_audit.config import AccountConfig
from deletion_audit.discovery.accounts import AccountAssignment, assign_primary_accounts
from deletion_audit.discovery.analytics import AnalyticsClaim, attach_identifier_free_analytics
from deletion_audit.evidence.model import EvidenceIndex, FileParse
from deletion_audit.identity.resolve import IdentityResolution
from deletion_audit.inputs.model import ActivityRow
from deletion_audit.inputs.requests import DeletionRequest

from ..engine_fixtures import act, obs, req
from .test_accounts import REP, at, delete_row, person


def index_with(*rids: str) -> EvidenceIndex:
    o = tuple(obs(r, system="analytics_platform", time="2026-05-02T09:00:00Z", ref=f"L{i}") for i, r in enumerate(rids))
    return EvidenceIndex({"ev_1": FileParse("ev_1", "x.log", "kv_log", "OK", o, (), None)})


def policy_row(aid: str, rid: str, seconds_from_rep: int) -> ActivityRow:
    return act(
        aid,
        at(0, seconds_from_rep),
        "ANONYMIZE_RECORD",
        rid,
        target="analytics_platform",
        details=f"Policy action completed for {rid}.",
    )


class SlotBand(unittest.TestCase):
    """test_slot_band_analytics_follow_job_account_flagged."""

    def _run(
        self,
        reqs: list[DeletionRequest],
        people: dict[str, IdentityResolution],
        activity: list[ActivityRow],
        index: EvidenceIndex,
    ) -> tuple[Mapping[str, AccountAssignment], Mapping[str, tuple[AnalyticsClaim, ...]]]:
        asg = assign_primary_accounts(reqs, people, activity, {}, AccountConfig(), owners={})
        return asg, attach_identifier_free_analytics(asg, reqs, people, activity, index, owners={})

    def test_slot_band_analytics_follow_job_account_flagged(self) -> None:
        # account row at -60:00 -> slot 0 band is residual 40..41 s; -1700 s is in slot 0 with residual 40
        reqs = [req("c1", "a@example.test", reported_at=REP)]
        acts = [
            delete_row("a1", "account_1", -60),
            policy_row("p1", "analytics_1", -1700),
            policy_row("p2", "analytics_2", -1698),
        ]  # residual 42: outside the band
        asg, claims = self._run(reqs, {"c1": person("user_901")}, acts, index_with("analytics_1", "analytics_2"))
        self.assertEqual([(c.resource_id, c.slot, c.residual_s) for c in claims["c1"]], [("analytics_1", 0, 40)])
        self.assertEqual(claims["c1"][0].flags, ())

    def test_follows_a_tie_pick_and_carries_its_flag(self) -> None:
        reqs = [req("c1", "a@example.test", reported_at=REP)]
        acts = [
            delete_row("a1", "account_1", -60),
            delete_row("a2", "account_2", -60, seconds=30),
            policy_row("p1", "analytics_1", -1700),
        ]
        asg, claims = self._run(reqs, {"c1": person("user_901")}, acts, index_with("analytics_1"))
        self.assertEqual(asg["c1"].stage, "S5_TIE_PICK")
        self.assertEqual(asg["c1"].resource_id, "account_1")
        self.assertEqual({f.code for c in claims["c1"] for f in c.flags}, {"ANALYTICS_ON_TIE_PICK"})

    def test_record_two_people_fit_is_kept_by_neither(self) -> None:
        reqs = [req("c1", "a@example.test", reported_at=REP), req("c2", "b@example.test", reported_at=REP)]
        people = {"c1": person("user_901"), "c2": person("user_902")}
        acts = [
            delete_row("a1", "account_1", -60),
            delete_row("a2", "account_2", -59),
            policy_row("p1", "analytics_1", -1700),
        ]
        asg, claims = self._run(reqs, people, acts, index_with("analytics_1"))
        self.assertEqual({asg["c1"].resource_id, asg["c2"].resource_id}, {"account_1", "account_2"})
        self.assertEqual(claims, {})

    def test_record_with_an_owner_or_no_evidence_is_never_claimed(self) -> None:
        reqs = [req("c1", "a@example.test", reported_at=REP)]
        acts = [delete_row("a1", "account_1", -60), policy_row("p1", "analytics_1", -1700)]
        asg = assign_primary_accounts(reqs, {"c1": person("user_901")}, acts, {}, AccountConfig(), owners={})
        owned = attach_identifier_free_analytics(
            asg,
            reqs,
            {"c1": person("user_901")},
            acts,
            index_with("analytics_1"),
            owners={"analytics_1": frozenset({"u"})},
        )
        no_ev = attach_identifier_free_analytics(asg, reqs, {"c1": person("user_901")}, acts, index_with(), owners={})
        self.assertEqual((owned, no_ev), ({}, {}))


if __name__ == "__main__":
    unittest.main()
