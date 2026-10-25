"""The five tools: case-bound, cut off at audit_at, evidence IDs named, read-only and gold-free."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from typing import Any

from deletion_audit.agent.crosscheck import intake_crosscheck
from deletion_audit.agent.loop import FixedIntent
from deletion_audit.agent.tools import TOOL_NAMES, CaseTools, tool_definitions
from deletion_audit.engine import EngineBrief, audit_case
from deletion_audit.record import CaseRecord, CrossCheck, IntentDecision

from ._support import ADA, BO, C1, C2, dataset, world_of

TOOLS_SOURCE = Path(__file__).resolve().parents[2] / "deletion_audit" / "agent" / "tools.py"


def brief(record: CaseRecord) -> EngineBrief:
    """An engine brief with no open questions, built from one engine record."""
    return EngineBrief(record.case_id, record.resources, record.citation, (), record.flags)


def tools_for(case_id: str, intake_for_ada: bool = False) -> CaseTools:
    w = world_of(dataset(intake_for_ada=intake_for_ada))
    cc = intake_crosscheck(case_id, w)
    decided = IntentDecision("DELETION_REQUEST", "MODEL", None, None, cc, None)
    record = audit_case(case_id, w, FixedIntent(decided))

    def make() -> EngineBrief:
        return brief(record)

    return CaseTools(case_id, w, cc, {}, make)


def data(result_content: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(result_content)
    return value


class TestTools(unittest.TestCase):
    """G3 section 5 tool list; G7a brief item 5."""

    def test_definitions_are_the_five_tools_with_object_schemas(self) -> None:
        defs = tool_definitions()
        self.assertEqual([d["name"] for d in defs], list(TOOL_NAMES))
        self.assertEqual(TOOL_NAMES, ("audit_case", "get_request_context", "inspect_evidence", "lookup_identity",
                                      "list_activity"))
        for d in defs:
            self.assertEqual(d["input_schema"]["type"], "object")
            self.assertFalse(d["input_schema"]["additionalProperties"])

    def test_bad_arguments_and_unknown_tools_are_errors(self) -> None:
        t = tools_for(C1)
        self.assertTrue(t.run("inspect_evidence", {"file_id": "ev_1"}).is_error)
        self.assertTrue(t.run("inspect_evidence", {"file_id": "ev_1", "focus": "RECORDS"}).is_error)  # exact enum
        self.assertTrue(t.run("delete_record", {}).is_error)
        self.assertTrue(t.run("lookup_identity", {"value": "x"}).is_error)

    def test_inspect_evidence_refuses_a_file_after_audit_at(self) -> None:
        t = tools_for(C1)
        late = t.run("inspect_evidence", {"file_id": "ev_late", "focus": "records"})
        self.assertTrue(late.is_error)
        self.assertNotIn("account_900000001", late.content)
        ok = t.run("inspect_evidence", {"file_id": "ev_1", "focus": "state"})
        self.assertFalse(ok.is_error)
        self.assertEqual(ok.evidence_ids, ("ev_1",))
        records = data(ok.content)["data"]["records"]
        self.assertEqual([r["resource_id"] for r in records], ["account_900000001"])  # only the case's own records
        self.assertEqual(records[0]["state"], "PRESENT")

    def test_list_activity_cuts_off_at_audit_at_and_names_its_rows(self) -> None:
        t = tools_for(C1)
        result = t.run("list_activity", {"identifier_or_resource": "account_900000001"})
        rows = data(result.content)["data"]["rows"]
        self.assertNotIn("a_9", [r["activity_id"] for r in rows])  # after audit_at
        self.assertEqual(result.evidence_ids, tuple(r["activity_id"] for r in rows))

    def test_get_request_context_names_the_intake_rows(self) -> None:
        t = tools_for(C2)
        result = t.run("get_request_context", {})
        body = data(result.content)["data"]
        self.assertEqual([r["activity_id"] for r in body["intake_rows"]], ["a_2"])
        self.assertEqual(result.evidence_ids, ("a_2",))
        self.assertEqual(body["same_person_requests"], 1)
        self.assertNotIn(BO, result.content)  # the request's own email is never needed

    def test_lookup_identity_returns_the_person(self) -> None:
        t = tools_for(C1)
        result = t.run("lookup_identity", {"value": ADA.upper()})
        matches = data(result.content)["data"]["matches"]
        self.assertEqual([(m["user_id"], m["current"]) for m in matches], [("user_9001", True)])

    def test_audit_case_returns_the_read_only_brief_and_its_evidence(self) -> None:
        t = tools_for(C1)
        result = t.run("audit_case", {"intent": "DELETION_REQUEST", "request_kind": "full_deletion",
                                      "language": "en", "basis_quote": "delete", "instruction_like_text": False})
        body = data(result.content)
        self.assertTrue(body["data"]["read_only"])
        self.assertEqual([r["resource_id"] for r in body["data"]["records"]], ["account_900000001"])
        self.assertEqual(result.evidence_ids, ("ev_1",))

    def test_tools_never_open_files_or_write(self) -> None:
        """Read-only and gold-free: no open/write/unlink call and no gold file name in tools.py."""
        source = TOOLS_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for banned in ("open", "write_text", "write_bytes", "unlink", "mkdir", "read_text", "read_bytes", "system"):
            self.assertNotIn(banned, calls)
        self.assertNotIn("sample" + "_output", source)
        self.assertNotIn("load_gold", source)

    def test_crosscheck_type(self) -> None:
        self.assertIsInstance(tools_for(C2).crosscheck, CrossCheck)


if __name__ == "__main__":
    unittest.main()
