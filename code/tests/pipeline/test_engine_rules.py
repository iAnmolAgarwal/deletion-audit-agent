"""Engine-level rules, tested through ``engine.audit_all`` rather than through one predicate.

* T54 (G5 verifier finding 1): a SQL inventory's declared scope never rules out a record that has
  a replica copy. ``tests/state`` tests the ``is_replica_copy`` predicate; this file tests the
  engine's use of it, with a non-replica control so the omission rule itself is still exercised.
* T63: an unresolved request email is searched in the evidence by its exact raw value.

Every value is made up; the SQL text follows the shapes the GP parser reads (``sql_replica_topology``
and ``sql_inventory`` with a ``snapshot_scope`` table).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from deletion_audit.engine import audit_all, build_context
from deletion_audit.record import CaseRecord

from ..engine_fixtures import Dataset, Person, case, kv_line, temp_dir

ADA, CY = "ada@example.test", "cy@example.test"
C1 = case(9601)
ROW = (
    "INSERT INTO \"{table}\" VALUES('account_1','account_service','customer_profiles',"
    '\'{{"resource_id":"account_1","user_id":"user_9001","email":"ada@example.test",'
    '"account_status":"ACTIVE"}}\',\'2026-05-02T13:00:00Z\');\n'
)
COPY = (
    "-- Captured at: 2026-05-02T13:00:00Z\n"
    "-- Database topology: {topology}\n"
    "BEGIN TRANSACTION;\n"
    "CREATE TABLE {table} (resource_id TEXT PRIMARY KEY, origin_system TEXT NOT NULL, "
    "collection_name TEXT NOT NULL, record_json TEXT NOT NULL, updated_at TEXT NOT NULL);\n"
    "{row}COMMIT;\n"
)
PROFILE_ROW = (
    "INSERT INTO customer_profiles VALUES ('account_1', 'user_9001', 'Ada Test', 'ada@example.test', NULL, "
    "NULL, 'ACTIVE', '2026-05-02T13:00:00Z');\n"
)
INVENTORY = (
    "PRAGMA foreign_keys=ON;\n"
    "BEGIN TRANSACTION;\n"
    "CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);\n"
    "CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, "
    "email TEXT, phone TEXT, email_hash TEXT, account_status TEXT NOT NULL, updated_at TEXT NOT NULL);\n"
    "INSERT INTO snapshot_scope VALUES ('account_service', '{at}');\n"
    "{rows}COMMIT;\n"
    "-- snapshot_completed_at={at}\n"
)


def audit_with_files(files: list[tuple[str, str, str, str]], email: str = ADA) -> CaseRecord:
    """One request (by ``email``) against the given evidence files (file_id, path, captured_at, text)."""
    d = Dataset(people=[Person("user_9001", ADA)])
    d.add_request(C1, email)
    for f in files:
        d.add_file(*f)
    with temp_dir() as tmp:
        ctx = build_context(d.write(Path(tmp)))
        for fid, fp in ctx.index.files.items():
            assert fp.status == "OK", fid  # the synthetic SQL parses (a guard on the test itself)
        return audit_all(ctx, [C1])[C1]


LATER_SCOPE = (
    "ev_s",
    "databases/inventory_later.sql",
    "2026-05-03T09:00:00Z",
    INVENTORY.format(at="2026-05-03T09:00:00Z", rows=""),
)


class ReplicaCopyBlocksOmission(unittest.TestCase):
    """T54 through the engine: a replica copy keeps a record PRESENT against a later scope omission."""

    def test_replica_copy_is_never_ruled_out_by_a_later_scope(self) -> None:
        replica = COPY.format(
            topology="regional_replicas",
            table="customer_data_replica_eu",
            row=ROW.format(table="customer_data_replica_eu"),
        )
        r = audit_with_files([("ev_r", "databases/replica.sql", "2026-05-02T13:00:00Z", replica), LATER_SCOPE])
        account = [x for x in r.resources if x.key.resource_id == "account_1"]
        self.assertEqual([(x.state.value, x.state.basis) for x in account], [("PRESENT", "latest_observation")])
        self.assertEqual(r.status, "INCOMPLETE")
        self.assertEqual(
            [(s.phase, s.operation, s.evidence_id) for s in r.steps],
            [
                ("FINDING", "REPORT_REMAINING_RECORD", "ev_r"),
                ("REMEDIATION", "DELETE_RECORD", ""),
                ("VERIFICATION", "VERIFY_RECORD_ABSENT", ""),
            ],
        )

    def test_control_non_replica_record_is_ruled_out_by_a_later_scope(self) -> None:
        """The same record in a plain inventory snapshot: the later declared scope's omission wins (T54)."""
        earlier = (
            "ev_p",
            "databases/inventory_earlier.sql",
            "2026-05-02T13:00:00Z",
            INVENTORY.format(at="2026-05-02T13:00:00Z", rows=PROFILE_ROW),
        )
        r = audit_with_files([earlier, LATER_SCOPE])
        account = [x for x in r.resources if x.key.resource_id == "account_1"]
        self.assertEqual([(x.state.value, x.state.basis) for x in account], [("ABSENT", "omission_in_declared_scope")])
        self.assertEqual((r.status, [s.operation for s in r.steps]), ("COMPLETE", ["VERIFY_RECORD_ABSENT"]))


class UnresolvedIdentitySearch(unittest.TestCase):
    """T63: an email that resolves to no one is still searched by its exact raw value; the row is
    FAILED_CLOSED(IDENTITY_UNRESOLVED), never NOT_APPLICABLE."""

    def test_record_holding_the_raw_email_is_found(self) -> None:
        line = kv_line(
            "2026-05-02T10:40:00Z",
            level="INFO",
            service="search_service",
            trace_id="t6",
            event="index_query_completed",
            resource_id="search_1",
            result="hit",
            email=CY,
        )
        r = audit_with_files([("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", line)], email=CY)
        self.assertEqual(
            (r.identity.status, r.failed_closed, r.status), ("UNRESOLVED", "IDENTITY_UNRESOLVED", "INCOMPLETE")
        )
        self.assertEqual([(x.key.resource_id, x.link_basis) for x in r.resources], [("search_1", "identifier")])
        self.assertIn("REPORT_REMAINING_RECORD", [s.operation for s in r.steps])
        lookalike = line.replace(CY, "cy.jr@example.test")
        r2 = audit_with_files([("ev_1", "logs/a.log", "2026-05-03T00:00:00Z", lookalike)], email=CY)
        self.assertEqual(r2.resources, ())  # exact match only (T49)


if __name__ == "__main__":
    unittest.main()
