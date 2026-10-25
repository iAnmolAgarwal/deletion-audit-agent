"""Linking: exact match, field role by line, own key beats trace lookup, PDF pages, catalog aliases."""

from __future__ import annotations

import unittest

from deletion_audit.discovery.catalog import alias_evidence, catalog_links
from deletion_audit.discovery.links import LinkIndex, Window, build_link_index, link_observation, link_observations
from deletion_audit.evidence.model import EvidenceIndex, FileParse, Identifier, Observation
from deletion_audit.identity import build_people, email_hash, resolve_with
from deletion_audit.identity.resolve import PeopleIndex
from deletion_audit.inputs.model import IdentityRow

from ..engine_fixtures import act, ident, obs, req

ADA = "ada@example.test"
BO = "bo@example.test"


def people(extra_old: str | None = None) -> PeopleIndex:
    rows = [
        IdentityRow(
            "user_9001",
            "Ada",
            ident("email", ADA),
            ident("phone", "+1 555 0101", "phone"),
            email_hash(ADA),
            "2026-01-01T00:00:00Z",
        ),
        IdentityRow(
            "user_9002",
            "Bo",
            ident("email", BO),
            ident("phone", "+1 555 0102", "phone"),
            email_hash(BO),
            "2026-01-01T00:00:00Z",
        ),
    ]
    audit = []
    if extra_old:
        from deletion_audit.inputs.model import AuditLogRow

        audit.append(
            AuditLogRow(
                "audit_1",
                "user_9001",
                "2026-01-02T00:00:00Z",
                "email",
                extra_old,
                ADA,
                ident("email", extra_old, "old_value"),
                ident("email", ADA, "new_value"),
            )
        )
    return build_people(rows, audit)


def index_of(*observations: Observation) -> EvidenceIndex:
    by_file: dict[str, list[Observation]] = {}
    for o in observations:
        by_file.setdefault(o.file_id, []).append(o)
    return EvidenceIndex({f: FileParse(f, f + ".log", "kv_log", "OK", tuple(v), (), None) for f, v in by_file.items()})


class Links(unittest.TestCase):
    """T49, T59, T68 and the window rule (R3/R4)."""

    def test_own_key_old_email_hash_links(self) -> None:
        p = people(extra_old="ada.before@example.test")
        o = obs("analytics_1", record=[ident("email_hash", email_hash("ada.before@example.test"), "email_hash")])
        self.assertEqual([(x.person, x.basis) for x in link_observation(o, p)], [("user_9001", "record_identifier")])

    def test_lookalike_never_links(self) -> None:
        """A decoy hit whose own key is a look-alike never links, even when its trace looked up the person."""
        p = people()
        decoy = obs(
            "search_1",
            record=[ident("email", "ada.jr@example.test", "correlation_key")],
            lookup=[ident("email", ADA, "lookup_key")],
        )
        self.assertEqual(link_observation(decoy, p), ())

    def test_trace_lookup_links_a_record_with_no_own_key(self) -> None:
        p = people()
        hit = obs("search_2", lookup=[ident("email", ADA, "lookup_key")])
        self.assertEqual([(x.person, x.basis) for x in link_observation(hit, p)], [("user_9001", "trace_lookup")])
        self.assertEqual(link_observation(obs(None, lookup=[ident("email", ADA, "lookup_key")]), p), ())

    def test_text_identifier_does_not_block_trace_lookup(self) -> None:
        p = people()
        o = obs(
            "support_1",
            record=[ident("email", "agent@example.test", "message_text")],
            lookup=[ident("email", ADA, "lookup_key")],
        )
        self.assertEqual([x.person for x in link_observation(o, p)], ["user_9001"])

    def test_multi_resource_multi_person_pdf_page_never_links(self) -> None:
        p = people()
        two_people = obs(
            "support_3",
            kind="pdf_page",
            ref="p1",
            family="pdf_text",
            file_id="ev_pdf",
            record=[ident("email", ADA, "pdf_text"), ident("email", BO, "pdf_text")],
        )
        two_res = [
            obs(
                r,
                kind="pdf_page",
                ref="p2",
                family="pdf_text",
                file_id="ev_pdf",
                record=[ident("email", ADA, "pdf_text")],
            )
            for r in ("support_4", "export_4")
        ]
        one = obs(
            "support_5",
            kind="pdf_page",
            ref="p3",
            family="pdf_text",
            file_id="ev_pdf",
            record=[ident("email", ADA, "pdf_text")],
        )
        li = build_link_index(index_of(two_people, *two_res, one), p, ())
        self.assertEqual(li.blocked_pages, {("ev_pdf", "p1"), ("ev_pdf", "p2")})
        self.assertEqual(sorted(o.resource_id for o, _ in li.by_person["user_9001"]), ["support_5"])

    def test_window_bounds_inclusive_and_post_audit_file_not_citable(self) -> None:
        p = people()
        r = req("c1", ADA, requested_at="2026-05-01T08:00:00Z", audit_at="2026-05-04T12:00:00Z")
        edge_lo = obs("account_1", time="2026-05-01T08:00:00Z", record=[ident("email", ADA)])
        edge_hi = obs(
            "account_2",
            time="2026-05-04T12:00:00Z",
            record=[ident("email", ADA)],
            file_id="ev_2",
            captured_at="2026-05-05T00:00:00Z",
        )
        before = obs("account_3", time="2026-05-01T07:59:59Z", record=[ident("email", ADA)], file_id="ev_3")
        li = build_link_index(index_of(edge_lo, edge_hi, before), p, ())
        got = {
            lk.resource_id: (lk.in_window, lk.citable)
            for lk in link_observations(resolve_with(r, p), li, Window(r.requested_at, r.audit_at))
        }
        self.assertEqual(got, {"account_1": (True, True), "account_2": (True, False), "account_3": (False, True)})


class Catalog(unittest.TestCase):
    """Catalog rows and their aliases (T71 Q3 data side)."""

    def test_alias_parsed_and_found_in_text(self) -> None:
        p = people()
        rows = [
            act(
                "activity_1",
                "2026-05-02T00:00:00Z",
                "LINK_RESOURCE_IDENTITY",
                "export_7",
                source="data_catalog",
                target="export_service",
                details=f"Data catalog linked export_7 (REF-0007-XY) to {ADA} and user_9001.",
            ),
            act(
                "activity_2",
                "2026-05-02T00:00:00Z",
                "LINK_RESOURCE_IDENTITY",
                "tombstone_7",
                source="data_catalog",
                target="identity_service",
                details=f"Data catalog linked tombstone_7 (user_9001) to {ADA} and user_9001.",
            ),
            act(
                "activity_3",
                "2026-05-02T00:00:00Z",
                "LINK_RESOURCE_IDENTITY",
                "export_8",
                source="data_catalog",
                target="export_service",
                details=f"Data catalog linked export_8 (export_8) to {ADA} and {BO}.",
            ),
        ]
        cat = catalog_links(rows, p)
        self.assertEqual(
            [(c.resource_id, c.alias, sorted(c.persons)) for c in cat],
            [("export_7", "REF-0007-XY", ["user_9001"]), ("tombstone_7", None, ["user_9001"]), ("export_8", None, [])],
        )  # two people named: links no one
        page = obs(None, kind="pdf_page", ref="p1", family="pdf_text", file_id="ev_doc", text="Statement REF-0007-XY")
        found = alias_evidence(cat, index_of(page))
        self.assertEqual([(a.resource_id, a.file_id) for a in found], [("export_7", "ev_doc")])


class OwnKeyPerRecord(unittest.TestCase):
    """T105 (R04): the own-key rule per record, across all its observations, whatever the file or trace."""

    def started(self, rid: str, file_id: str = "ev_1") -> Observation:
        return obs(rid, file_id=file_id, ref="L1", lookup=[ident("email", ADA, "lookup_key")])

    def completed(self, rid: str, *own: Identifier, file_id: str = "ev_1") -> Observation:
        return obs(rid, file_id=file_id, ref="L2", record=list(own))

    def linked(self, li: LinkIndex, person: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for o, ol in li.by_person.get(person, ()):
            out.setdefault(o.resource_id or "", set()).add(ol.basis)
        return out

    def test_namesakes_own_key_on_the_completed_line_beats_the_started_lines_lookup(self) -> None:
        """Before: the started line linked account_3 to Ada by trace lookup."""
        p = people()
        li = build_link_index(index_of(self.started("account_3"),
                                       self.completed("account_3",
                                                      ident("user_id", "user_9002", "customer_reference"))),
                              p, ())
        self.assertNotIn("account_3", self.linked(li, "user_9001"))
        self.assertEqual(self.linked(li, "user_9002"), {"account_3": {"record_identifier"}})
        self.assertEqual(li.own_persons["account_3"], frozenset({"user_9002"}))
        self.assertEqual(li.resource_persons["account_3"], frozenset({"user_9002"}))

    def test_lookalike_own_key_belongs_to_no_one_and_still_blocks_the_lookup(self) -> None:
        p = people()
        li = build_link_index(index_of(self.started("search_2"),
                                       self.completed("search_2",
                                                      ident("email", "ada.jr@example.test", "correlation_key"))),
                              p, ())
        self.assertNotIn("search_2", self.linked(li, "user_9001"))
        self.assertEqual(li.own_persons["search_2"], frozenset())
        self.assertIn("search_2", li.own_keyed)

    def test_own_key_in_another_file_blocks_the_lookup(self) -> None:
        p = people()
        li = build_link_index(index_of(self.started("account_3"),
                                       self.completed("account_3", ident("email", BO), file_id="ev_2")), p, ())
        self.assertNotIn("account_3", self.linked(li, "user_9001"))

    def test_lookup_agreeing_with_the_own_key_still_links(self) -> None:
        """R05 shape: the lookup line's person is the one the own key names, so the lookup link stays."""
        p = people()
        li = build_link_index(index_of(self.started("account_1"),
                                       self.completed("account_1", ident("email", ADA), file_id="ev_2")), p, ())
        self.assertEqual(self.linked(li, "user_9001"), {"account_1": {"trace_lookup", "record_identifier"}})

    def test_record_with_no_own_key_anywhere_still_links_by_lookup(self) -> None:
        p = people()
        li = build_link_index(index_of(self.started("search_9"), obs("search_9", ref="L2")), p, ())
        self.assertEqual(self.linked(li, "user_9001"), {"search_9": {"trace_lookup"}})
        self.assertNotIn("search_9", li.own_keyed)

    def test_link_observation_keyword_form(self) -> None:
        p = people()
        line = self.started("account_3")
        self.assertEqual(link_observation(line, p, record_owners=frozenset({"user_9002"})), ())
        self.assertEqual([x.basis for x in link_observation(line, p, record_owners=frozenset({"user_9001"}))],
                         ["trace_lookup"])
        self.assertEqual([x.basis for x in link_observation(line, p)], ["trace_lookup"])  # no own key anywhere

    def test_no_lookup_link_ever_contradicts_a_records_own_keys(self) -> None:
        """Seeded property test (Hypothesis is not installed): over random records spread across files
        and lines, a person gets a trace_lookup link to a record only when the record has no own key or
        its own keys name that person."""
        import random

        p = people()
        keys = [ident("email", ADA), ident("email", BO), ident("email", "ada.jr@example.test", "correlation_key"),
                ident("user_id", "user_9002", "customer_reference"), ident("email_hash", email_hash(ADA), "email_hash")]
        for seed in range(200):
            rng = random.Random(seed)
            observations = []
            for n in range(rng.randrange(2, 8)):
                rid = f"account_{rng.randrange(3)}"
                own = [rng.choice(keys)] if rng.random() < 0.4 else []
                look = [ident("email", rng.choice((ADA, BO)), "lookup_key")] if rng.random() < 0.6 else []
                observations.append(obs(rid, file_id=f"ev_{rng.randrange(2)}", ref=f"L{n}", record=own, lookup=look))
            li = build_link_index(index_of(*observations), p, ())
            for person, pairs in li.by_person.items():
                for o, ol in pairs:
                    if ol.basis == "trace_lookup" and o.resource_id in li.own_keyed:
                        self.assertIn(person, li.own_persons[o.resource_id], seed)


if __name__ == "__main__":
    unittest.main()
