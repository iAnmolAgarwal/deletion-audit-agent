"""Developer ruling T49: correlation_key, subject_ref and subject_reference take their role
from the line. On a line that names a resource_id they are that resource's own key; on a
line with no resource_id they are a lookup key that reaches a resource only through its trace."""
from __future__ import annotations

import unittest

from ._support import by_ref, id_set, real_index
from .test_contract import _single

KV = "2026-01-01T00:00:0{s}Z level=INFO service={svc} trace_id={tr} {rest}\n"


class LineRoleFields(unittest.TestCase):
    """The same field name is a record key or a lookup key depending on the line."""

    def test_search_hit_correlation_key_is_the_hits_own_key(self) -> None:
        fp = _single({"t.log": KV.format(s=1, svc="search_service", tr="tr-1",
                                          rest="event=index_query_completed resource_id=search_1 "
                                               "correlation_key=Ada.Lovelace@example.test")})
        obs = by_ref(fp)["L1"][0]
        self.assertEqual(id_set(obs.record_identifiers),
                         {("email", "ada.lovelace@example.test", "correlation_key")})
        self.assertEqual(obs.lookup_identifiers, frozenset())

    def test_hit_key_does_not_spread_over_its_trace(self) -> None:
        """A decoy hit's own key stays on the hit; other lines of the trace never borrow it."""
        source = (KV.format(s=1, svc="search_service", tr="tr-1",
                            rest="event=index_query_completed resource_id=search_1 "
                                 "correlation_key=ada.jr@example.test")
                  + KV.format(s=2, svc="search_service", tr="tr-1",
                              rest="event=index_entry_read resource_id=search_2 rows=1"))
        rows = by_ref(_single({"t.log": source}))
        self.assertEqual(id_set(rows["L1"][0].record_identifiers),
                         {("email", "ada.jr@example.test", "correlation_key")})
        self.assertEqual(rows["L2"][0].record_identifiers, frozenset())
        self.assertEqual(rows["L2"][0].lookup_identifiers, frozenset())

    def test_subject_ref_with_resource_is_the_records_subject(self) -> None:
        fp = _single({"t.log": KV.format(s=1, svc="support_service", tr="tr-1",
                                          rest="event=message_read resource_id=support_1 "
                                               "subject_ref=user_9001")})
        obs = by_ref(fp)["L1"][0]
        self.assertEqual(id_set(obs.record_identifiers), {("user_id", "user_9001", "subject_ref")})
        self.assertEqual(obs.lookup_identifiers, frozenset())

    def test_subject_ref_without_resource_is_a_trace_lookup(self) -> None:
        source = (KV.format(s=1, svc="security_service", tr="tr-1",
                            rest="event=audit_record_query_started subject_ref=user_9001")
                  + KV.format(s=2, svc="security_service", tr="tr-1",
                              rest="event=audit_record_read_completed resource_id=audit_record_1")
                  + KV.format(s=3, svc="security_service", tr="tr-2",
                              rest="event=audit_record_read_completed resource_id=audit_record_2"))
        rows = by_ref(_single({"t.log": source}))
        self.assertEqual(id_set(rows["L1"][0].lookup_identifiers),
                         {("user_id", "user_9001", "subject_ref")})
        self.assertEqual(rows["L1"][0].record_identifiers, frozenset())
        self.assertEqual(id_set(rows["L2"][0].lookup_identifiers),
                         {("user_id", "user_9001", "subject_ref")})
        self.assertEqual(rows["L2"][0].record_identifiers, frozenset())
        self.assertEqual(rows["L3"][0].lookup_identifiers, frozenset())

    def test_hashed_old_email_as_own_key(self) -> None:
        """T59: a line's own key may be the sha256 of a person's old email. The parser keeps it
        as the record's own email_hash, normalized, so the linker (G5) can match it against
        the person's complete identifier set; the linking test itself belongs to G5."""
        import hashlib
        digest = hashlib.sha256(b"old.mail@example.test").hexdigest()
        fp = _single({"t.log": KV.format(s=1, svc="analytics_service", tr="tr-1",
                                          rest="event=contact_lookup_completed resource_id=analytics_1 "
                                               f"correlation_key={digest.upper()}")})
        obs = by_ref(fp)["L1"][0]
        self.assertEqual(id_set(obs.record_identifiers), {("email_hash", digest, "correlation_key")})
        self.assertEqual(obs.lookup_identifiers, frozenset())

    def test_real_files_follow_the_line_rule(self) -> None:
        """Across the dataset: a line-role field is a record key exactly when the line names a resource."""
        from deletion_audit.evidence.interpret import LINE_ROLE_ID_FIELDS, leaf_name
        seen = 0
        for obs in real_index().observations():
            own = {i.field for i in obs.record_identifiers if leaf_name(i.field) in LINE_ROLE_ID_FIELDS}
            for key in own:
                seen += 1
                self.assertIsNotNone(obs.resource_id, (obs.file_id, obs.locator.ref, key))
            if obs.resource_id is None:
                self.assertFalse(own, (obs.file_id, obs.locator.ref))
        self.assertGreater(seen, 0)


if __name__ == "__main__":
    unittest.main()
