"""Primary-account assignment: T4 order, T26-T29, T32, T39, and the T5 fingerprint precision."""

from __future__ import annotations

import datetime as dt
import hashlib
import unittest
from collections.abc import Mapping

from deletion_audit.config import AccountConfig
from deletion_audit.discovery.accounts import AccountAssignment, assign_primary_accounts
from deletion_audit.discovery.links import Link
from deletion_audit.discovery.obstime import ObsTime
from deletion_audit.discovery.timing import sig_match
from deletion_audit.identity.resolve import IdentifierSet, IdentityResolution
from deletion_audit.inputs.model import ActivityRow
from deletion_audit.inputs.requests import DeletionRequest

from ..engine_fixtures import act, ident, obs, req

REP = "2026-05-02T12:00:00Z"


def at(minutes: float, seconds: int = 0) -> str:
    t = dt.datetime(2026, 5, 2, 12, 0, 0) + dt.timedelta(minutes=minutes, seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def person(uid: str | None, email: str = "x@example.test") -> IdentityResolution:
    ids = IdentifierSet(uid, frozenset({email}), frozenset(), frozenset())
    return IdentityResolution("CURRENT" if uid else "UNRESOLVED", ids, ())


EMAIL_KEY = ("email", "x@example.test", "email")


def account_link(
    rid: str, *, in_window: bool = True, log: bool = False, matched: tuple[str, str, str] = EMAIL_KEY
) -> Link:
    o = obs(rid, system="account_service", family="kv_log" if log else "snapshot_bundle")
    return Link(
        o,
        "trace_lookup" if log else "record_identifier",
        ident(*matched),
        in_window,
        True,
        rid,
        "account_service",
        ObsTime(o.record_time or "", "second", "record_time"),
    )


def delete_row(aid: str, rid: str, minutes: float, result: str = "SUCCESS", seconds: int = 0) -> ActivityRow:
    return act(
        aid,
        at(minutes, seconds),
        "DELETE_RECORD",
        rid,
        result=result,
        details=f"Deletion worker submitted primary profile {rid}.",
    )


def run(
    reqs: list[DeletionRequest],
    people: dict[str, IdentityResolution],
    activity: list[ActivityRow],
    links: Mapping[str, tuple[Link, ...]] | None = None,
    owners: Mapping[str, frozenset[str]] | None = None,
) -> Mapping[str, AccountAssignment]:
    return assign_primary_accounts(reqs, people, activity, links or {}, AccountConfig(), owners=owners or {})


class AccountOrder(unittest.TestCase):
    """test_account_order_s1_s2_t26_t27_t28 and its neighbours."""

    def test_account_order_s1_s2_t26_t27_t28(self) -> None:
        # one batch time per request (hours apart), so no two requests compete for a row
        reqs = [req(f"c{i}", f"p{i}@example.test", reported_at=at(i * 600)) for i in range(1, 6)]
        people = {r.case_id: person(f"user_90{i}") for i, r in enumerate(reqs, start=1)}
        activity = [
            delete_row("a1", "account_1", 600 - 60),
            delete_row("a2", "account_2", 1200 - 50),
            delete_row("a3", "account_3", 1800 + 4),
        ]
        links = {
            "c1": (account_link("account_1"),),  # S1
            "c4": (account_link("account_4", in_window=False, log=True),),
        }  # T27 (outside the window)
        got = run(
            reqs,
            people,
            activity,
            links,
            owners={"account_1": frozenset({"user_901"}), "account_4": frozenset({"user_904"})},
        )
        self.assertEqual(got["c1"].stage, "S1_IDENTIFIER")
        self.assertEqual((got["c2"].stage, got["c2"].resource_id), ("S2_TIMED", "account_2"))
        self.assertEqual((got["c3"].stage, got["c3"].resource_id), ("T26_HAND_BUILT", "account_3"))
        self.assertEqual((got["c4"].stage, got["c4"].resource_id), ("T27_LATER_LOOKUP", "account_4"))
        self.assertEqual((got["c5"].stage, got["c5"].resource_id), ("T28_NONE", None))
        self.assertIn("T28_NO_ACCOUNT", {f.code for f in got["c5"].flags})

    def test_timed_window_bounds_inclusive(self) -> None:
        for minutes, seconds, inside in ((-75, 0, True), (-44, 0, True), (-75, -1, False), (-44, 1, False)):
            with self.subTest(minutes=minutes, seconds=seconds):
                got = run(
                    [req("c1", "a@example.test", reported_at=REP)],
                    {"c1": person("user_901")},
                    [delete_row("a1", "account_1", minutes, seconds=seconds)],
                )
                self.assertEqual(got["c1"].stage == "S2_TIMED", inside)

    def test_t26_hand_built_window_bounds_inclusive(self) -> None:
        """T26: +-10 min of ``reported_at``, both ends inclusive; nothing beyond (DEV: 3 right, 0 wrong)."""
        bounds = ((10, 0, True), (-10, 0, True), (10, 1, False), (-10, -1, False), (12, 0, False))
        for minutes, seconds, inside in bounds:
            with self.subTest(minutes=minutes, seconds=seconds):
                got = run(
                    [req("c1", "a@example.test", reported_at=REP)],
                    {"c1": person("user_901")},
                    [delete_row("a1", "account_1", minutes, seconds=seconds)],
                )
                self.assertEqual(got["c1"].stage == "T26_HAND_BUILT", inside)
                self.assertEqual(got["c1"].resource_id, "account_1" if inside else None)

    def test_t27_only_the_persons_email_or_phone(self) -> None:
        """T27: a later log lookup counts only when its key is the person's email or phone, never
        another identifier kind (here a ``user_id`` lookup key)."""
        for matched, stage in (
            (EMAIL_KEY, "T27_LATER_LOOKUP"),
            (("phone", "+1 555 0100", "phone"), "T27_LATER_LOOKUP"),
            (("user_id", "user_901", "customer_reference"), "T28_NONE"),
        ):
            with self.subTest(kind=matched[0]):
                got = run(
                    [req("c1", "x@example.test", reported_at=REP)],
                    {"c1": person("user_901")},
                    [],
                    {"c1": (account_link("account_4", in_window=False, log=True, matched=matched),)},
                    owners={"account_4": frozenset({"user_901"})},
                )
                self.assertEqual(got["c1"].stage, stage)

    def test_result_match_required_no_mismatch_fallback(self) -> None:
        got = run(
            [req("c1", "a@example.test", reported_at=REP, reported_status="PARTIALLY_COMPLETE")],
            {"c1": person("user_901")},
            [delete_row("a1", "account_1", -60, result="SUCCESS"), delete_row("a2", "account_2", 3, result="SUCCESS")],
        )
        self.assertEqual((got["c1"].stage, got["c1"].resource_id), ("T28_NONE", None))

    def test_owner_filter_excludes_another_persons_account(self) -> None:
        got = run(
            [req("c1", "a@example.test", reported_at=REP)],
            {"c1": person("user_901")},
            [delete_row("a1", "account_1", -60)],
            owners={"account_1": frozenset({"user_999"})},
        )
        self.assertIsNone(got["c1"].resource_id)

    def test_one_owner_per_person_shared_account_allowed(self) -> None:
        reqs = [
            req("c1", "a@example.test", reported_at=REP),
            req("c2", "a@example.test", reported_at=REP),
            req("c3", "b@example.test", reported_at=REP),
        ]
        people = {"c1": person("user_901"), "c2": person("user_901"), "c3": person("user_902")}
        got = run(
            reqs,
            people,
            [delete_row("a1", "account_1", -60), delete_row("a2", "account_2", -50)],
            {"c1": (account_link("account_1"),)},
        )
        self.assertEqual(got["c1"].resource_id, "account_1")
        self.assertEqual(got["c2"].resource_id, "account_1")  # same person may share it (T29)
        self.assertEqual(got["c3"].resource_id, "account_2")  # another person may not take it

    def test_tie_pick_max_matching_sha256_user_id(self) -> None:
        reqs = [req("c1", "a@example.test", reported_at=REP), req("c2", "b@example.test", reported_at=REP)]
        uids = {"c1": "user_901", "c2": "user_902"}
        people = {c: person(u) for c, u in uids.items()}
        rows = [delete_row("a1", "account_1", -60), delete_row("a2", "account_2", -60, seconds=30)]
        got = run(reqs, people, rows)
        picks = {c: got[c].resource_id for c in uids}
        self.assertEqual(sorted(picks.values()), ["account_1", "account_2"])  # one-to-one, nobody left empty
        first = min(uids, key=lambda c: hashlib.sha256(uids[c].encode()).hexdigest())
        self.assertEqual(picks[first], "account_1")  # closest to -60 min goes first in sha256(user_id) order
        self.assertTrue(all(got[c].stage == "S5_TIE_PICK" for c in uids))
        self.assertTrue(all("D18_TIE_PICK" in {f.code for f in got[c].flags} for c in uids))
        swapped = run(list(reversed(reqs)), people, list(reversed(rows)))
        self.assertEqual({c: swapped[c].resource_id for c in uids}, picks)  # input order never decides

    def test_fingerprint_breaks_tie(self) -> None:
        r = req("c1", "a@example.test", reported_at=REP)
        own = act(
            "p1",
            at(-22, 10),
            "ANONYMIZE_RECORD",
            "analytics_1",
            target="analytics_platform",
            details="Policy action completed for analytics_1.",
        )
        rows = [delete_row("a1", "account_1", -60), delete_row("a2", "account_2", -60, seconds=15), own]
        link = Link(
            obs("analytics_1", system="analytics_platform"),
            "record_identifier",
            ident("email", "a@example.test"),
            True,
            True,
            "analytics_1",
            "analytics_platform",
            ObsTime("2026-05-02T10:00:00Z", "second", "record_time"),
        )
        got = run([r], {"c1": person("user_901")}, rows, {"c1": (link,)})
        self.assertEqual((got["c1"].stage, got["c1"].resource_id), ("S4_FINGERPRINT", "account_1"))


class FingerprintPrecision(unittest.TestCase):
    """T5: the D17 bands are exact to the second (+-1 s changes 33 test cases, G2 Q4)."""

    def test_fingerprint_precision_fixture_one_second(self) -> None:
        def policy(s: int) -> ActivityRow:
            return act("p", at(-22, s), "ANONYMIZE_RECORD", "x_1", details="Policy action completed.")

        def after(s: int) -> ActivityRow:
            return act("q", at(30, s), "DELETE_RECORD", "x_2", details="Final result recorded.")

        for s, ok in ((8, False), (9, True), (11, True), (12, False)):
            self.assertEqual(sig_match(policy(s), REP, 0.0), ok, s)
        for s, ok in ((19, False), (20, True), (22, True), (23, False)):
            self.assertEqual(sig_match(after(s), REP, 0.0), ok, s)


if __name__ == "__main__":
    unittest.main()
