"""Linking: exact match, field role by line, own key beats trace lookup, PDF pages, catalog aliases."""

from __future__ import annotations

import unittest

from deletion_audit.discovery.catalog import alias_evidence, catalog_links
from deletion_audit.discovery.links import Window, build_link_index, link_observation, link_observations
from deletion_audit.evidence.model import EvidenceIndex, FileParse, Observation
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


if __name__ == "__main__":
    unittest.main()
