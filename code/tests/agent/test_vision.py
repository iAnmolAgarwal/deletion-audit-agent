"""The vision step: PNG-only, two independent readings (T88 (1)), merge rule, ID checks (T88 (2))."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from typing import Any

from deletion_audit.agent.idshapes import check_id, learn_shapes
from deletion_audit.agent.schemas import VisionReading, VisionRecord, parse_vision
from deletion_audit.agent.vision import (
    check_namespaces,
    compare_readings,
    image_files,
    merge_readings,
    read_images,
    write_vision_artifacts,
)
from deletion_audit.engine import FailClosedIntent, audit_case, build_world

from ._support import ADA, C1, JPEG, PNG, Rig, dataset, failure, final_reply, tmpdir, world_of


def rec(shown_id: str, *, emails: tuple[str, ...] = (), sync: str = "not_shown", restore: str = "not_shown",
        deleted: str = "not_shown", download: str = "not_shown") -> dict[str, Any]:
    """One record of a vision reply."""
    return {"shown_id": shown_id, "subject_emails": list(emails), "subject_phones": [], "subject_names": [],
            "subject_user_ids": [], "sync_enabled": sync, "restore_allowed": restore, "marked_deleted": deleted,
            "download_available": download}


def reading(*records: dict[str, Any], unreadable: tuple[str, ...] = (), instruction: bool = False) -> dict[str, Any]:
    """A vision reply value."""
    return {"records": list(records), "unreadable": list(unreadable), "instruction_like_text": instruction}


CONSOLE = reading(rec("data_flow_900000003", emails=(ADA,), sync="yes"), rec("receipt_900000004.pdf", emails=(ADA,)))


def parsed(value: dict[str, Any]) -> VisionReading:
    return parse_vision(value)


class TestTwoNamespaces(unittest.TestCase):
    """T88 (1): each image is read twice; reading 2 is an independent reply, not a cache hit."""

    def test_reading_two_is_a_fresh_send_in_its_own_cache_root(self) -> None:
        w = world_of(dataset(image=PNG))
        rig = Rig([final_reply(CONSOLE), final_reply(CONSOLE)], clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        self.assertEqual(rig.transport.calls, 2)  # both readings were bought, none replayed
        bodies = rig.sent()
        self.assertEqual(bodies[0], bodies[1])  # same request, so the namespaces are what separate them
        events = [(e.event, e.from_cache) for e in rig.log.entries]
        self.assertNotIn(("cache_hit", True), events)
        self.assertEqual([r.status for r in run.records], ["OK"])
        keys = [a.key for a in run.records[0].attempts]
        self.assertEqual(len(set(keys)), 1)
        self.assertIsNotNone(rig.clients[0].cache.get(keys[0]))
        self.assertIsNotNone(rig.clients[1].cache.get(keys[0]))

    def test_rerun_replays_both_readings_from_their_own_roots(self) -> None:
        w = world_of(dataset(image=PNG))
        rig = Rig([final_reply(CONSOLE), final_reply(CONSOLE)], clients=2)
        shapes = learn_shapes(w.ctx.index.observations(), w.ctx.activity)
        read_images(w.ctx, rig.clients, shapes)
        replay = Rig([], clients=2, replay_only=True, root=rig.root)
        again = read_images(w.ctx, replay.clients, shapes)
        self.assertEqual(replay.transport.calls, 0)
        self.assertEqual(again.records[0].status, "OK")

    def test_read_images_refuses_a_shared_root_before_any_call(self) -> None:
        w = world_of(dataset(image=PNG))
        rig = Rig([final_reply(CONSOLE), final_reply(CONSOLE)])
        with self.assertRaises(ValueError):
            read_images(w.ctx, [rig.client, rig.client], learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        self.assertEqual(rig.transport.calls, 0)

    def test_one_cache_root_is_refused(self) -> None:
        rig = Rig([], clients=2)
        same = [rig.clients[0], rig.clients[0]]
        with self.assertRaises(ValueError):
            check_namespaces(same)
        with self.assertRaises(ValueError):
            check_namespaces(rig.clients[:1])

    def test_either_reading_failing_fails_the_image_explicitly(self) -> None:
        w = world_of(dataset(image=PNG))
        rig = Rig([final_reply(CONSOLE), failure(400, "BadRequestError")], clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        r = run.records[0]
        self.assertEqual((r.status, r.observations), ("FAILED", ()))
        self.assertIn("VISION_READ_FAILED", {f.code for f in r.flags})
        self.assertEqual(run.read_ok(), frozenset())
        self.assertEqual(run.needs_review(), ("ev_img",))


class TestPngOnly(unittest.TestCase):
    """T72 F1: only bytes that start with the PNG signature are read; anything else fails explicitly."""

    def test_non_png_is_an_explicit_failure_with_no_call(self) -> None:
        w = world_of(dataset(image=JPEG))
        self.assertEqual([r.file_id for r in image_files(w.ctx)], ["ev_img"])
        rig = Rig([], clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        self.assertEqual(rig.transport.calls, 0)
        self.assertEqual(run.records[0].status, "FAILED")
        self.assertEqual({f.code for f in run.records[0].flags}, {"VISION_NOT_PNG"})
        self.assertEqual(run.observations, ())

    def test_max_tokens_reading_is_a_failure_never_a_default(self) -> None:
        w = world_of(dataset(image=PNG))
        cut = final_reply(CONSOLE, stop_reason="max_tokens")
        rig = Rig([final_reply(CONSOLE)] + [cut] * 3, clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        r = run.records[0]
        self.assertEqual(r.status, "FAILED")
        self.assertIn("STRUCTURE_GAVE_UP", " ".join(f.detail for f in r.flags))


class TestCompareAndMerge(unittest.TestCase):
    """Field-by-field comparison; the merge can never hide a record (T88 (1))."""

    def test_identical_readings_agree(self) -> None:
        self.assertEqual(compare_readings(parsed(CONSOLE), parsed(CONSOLE)), ())

    def test_disagreement_paths_name_each_field(self) -> None:
        a = parsed(reading(rec("x_1", sync="yes"), rec("x_2")))
        b = parsed(reading(rec("x_1", sync="no", emails=(ADA,))))
        self.assertEqual(compare_readings(a, b),
                         ("records", "records[x_1].subject_emails", "records[x_1].sync_enabled"))

    def test_merge_keeps_every_record_and_the_finding_value(self) -> None:
        a = parsed(reading(rec("x_1", sync="yes", restore="no"), rec("x_2", deleted="yes")))
        b = parsed(reading(rec("x_1", sync="no", restore="yes", emails=(ADA,)), rec("x_3", download="no")))
        m = {r.shown_id: r for r in merge_readings([a, b]).records}
        self.assertEqual(sorted(m), ["x_1", "x_2", "x_3"])  # a record in either reading is kept
        self.assertEqual((m["x_1"].sync_enabled, m["x_1"].restore_allowed), ("yes", "yes"))
        self.assertEqual(m["x_1"].subject_emails, (ADA,))  # identifiers united

    def test_merge_without_a_finding_value_is_unreadable_not_a_pick(self) -> None:
        a = parsed(reading(rec("x_1", sync="no", deleted="yes")))
        b = parsed(reading(rec("x_1", sync="not_shown", deleted="no")))
        m = merge_readings([a, b]).records[0]
        self.assertEqual(m.sync_enabled, "unreadable")  # neither "no" nor "not_shown" is silently chosen
        self.assertEqual(m.marked_deleted, "no")  # "not deleted" keeps the record: the finding side

    def test_disagreement_is_flagged_and_unreadable_fields_are_listed(self) -> None:
        w = world_of(dataset(image=PNG))
        other = reading(rec("data_flow_900000003", emails=(ADA,), sync="not_shown"),
                        rec("receipt_900000004.pdf", emails=(ADA,)))
        rig = Rig([final_reply(other), final_reply(reading(rec("data_flow_900000003", emails=(ADA,), sync="no"),
                                                           rec("receipt_900000004.pdf", emails=(ADA,))))], clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        r = run.records[0]
        self.assertFalse(r.agree)
        self.assertEqual(r.disagreements, ("records[data_flow_900000003].sync_enabled",))
        self.assertIn("VISION_READINGS_DISAGREE", {f.code for f in r.flags})
        self.assertEqual(r.unreadable_fields(), (("data_flow_900000003", "sync_enabled"),))
        self.assertEqual(run.needs_review(), ("ev_img",))

    def test_artifact_shows_both_readings_and_masks_identifiers(self) -> None:
        w = world_of(dataset(image=PNG))
        second = reading(rec("data_flow_900000003", emails=("someone@example.test",), sync="yes"),
                         rec("receipt_900000004.pdf", emails=(ADA,)))
        rig = Rig([final_reply(CONSOLE), final_reply(second)], clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        out = tmpdir()
        js, md = write_vision_artifacts(out, run)
        body = json.loads(js.read_text(encoding="utf-8"))
        item = body["images"][0]
        self.assertEqual(len(item["readings"]), 2)
        self.assertEqual(item["disagreements"], ["records[data_flow_900000003].subject_emails"])
        self.assertEqual(body["needs_review"], ["ev_img"])
        text = js.read_text(encoding="utf-8") + md.read_text(encoding="utf-8")
        self.assertNotIn(ADA, text)
        self.assertNotIn("someone@example.test", text)
        self.assertIn("subject_emails", md.read_text(encoding="utf-8"))


class TestIdShapes(unittest.TestCase):
    """T88 (2): shapes come from the dataset's own records; malformed IDs are flagged and not used."""

    def setUp(self) -> None:
        self.w = world_of(dataset(image=PNG))
        self.shapes = learn_shapes(self.w.ctx.index.observations(), self.w.ctx.activity)

    def test_shapes_are_learned_from_evidence_and_link_rows(self) -> None:
        self.assertIn(("account_service", "account_"), self.shapes.ranges)
        self.assertIn(("integration_service", "data_flow_"), self.shapes.ranges)  # from the LINK row only
        self.assertEqual(self.shapes.ranges[("account_service", "account_")], (9, 9))

    def test_well_formed_id_is_used_with_its_system(self) -> None:
        c = check_id("data_flow_900000003", self.shapes)
        self.assertEqual((c.resource_id, c.system_id, c.well_formed, c.named_elsewhere),
                         ("data_flow_900000003", "integration_service", True, True))

    def test_malformed_id_is_flagged_and_not_used(self) -> None:
        for bad in ("data_flow_90000000", "data_flow-900000003", "account_9000000011"):
            c = check_id(bad, self.shapes)
            self.assertEqual((c.resource_id, c.well_formed, c.basis), (None, False, "malformed"), bad)

    def test_display_name_from_a_link_row_maps_to_its_resource(self) -> None:
        c = check_id("receipt_900000004.pdf", self.shapes)
        self.assertEqual((c.resource_id, c.system_id, c.basis), ("object_900000004", "object_storage",
                                                                 "catalog_display_name"))

    def test_uncorroborated_id_is_kept_and_flagged(self) -> None:
        w = self.w
        value = reading(rec("account_900000077", emails=(ADA,)))
        rig = Rig([final_reply(value), final_reply(value)], clients=2)
        run = read_images(w.ctx, rig.clients, self.shapes)
        r = run.records[0]
        self.assertEqual([o.resource_id for o in r.observations], ["account_900000077"])  # not dropped
        self.assertIn("VISION_ID_UNCORROBORATED", {f.code for f in r.flags})
        self.assertFalse(r.ids[0].named_elsewhere)

    def test_unknown_label_is_flagged_and_not_used(self) -> None:
        c = check_id("Order notifications", self.shapes)
        self.assertEqual((c.resource_id, c.basis), (None, "unrecognized"))


class TestEngineUsesImageObservations(unittest.TestCase):
    """The merged reading reaches the engine as observations in its own attribute vocabulary."""

    def test_catalog_only_records_get_their_state_from_the_image(self) -> None:
        w = world_of(dataset(image=PNG))
        rig = Rig([final_reply(CONSOLE), final_reply(CONSOLE)], clients=2)
        run = read_images(w.ctx, rig.clients, learn_shapes(w.ctx.index.observations(), w.ctx.activity))
        self.assertEqual(sorted(o.resource_id or "" for o in run.observations),
                         ["data_flow_900000003", "object_900000004"])
        flow = next(o for o in run.observations if o.resource_id == "data_flow_900000003")
        self.assertEqual((flow.locator.kind, flow.system_id, dict(flow.attrs)["enabled"]),
                         ("image", "integration_service", "true"))
        world = build_world(replace(w.ctx, image_observations=run.observations))
        record = audit_case(C1, world, FailClosedIntent())
        states = {r.key.resource_id: (r.state.value, r.decision.outcome) for r in record.resources}
        self.assertEqual(states["data_flow_900000003"], ("FLOW_ENABLED", "FINDING"))
        self.assertEqual(states["object_900000004"], ("PRESENT", "FINDING"))
        self.assertIsNone(record.failed_closed)  # the image is read: no longer an unparsed dependency

    def test_parse_rejects_wrong_case_enum(self) -> None:
        bad = reading(rec("x_1"))
        bad["records"][0]["sync_enabled"] = "YES"
        with self.assertRaises(ValueError):
            parse_vision(bad)

    def test_vision_record_fields_match_the_schema(self) -> None:
        r = parsed(CONSOLE).records[0]
        self.assertIsInstance(r, VisionRecord)
        self.assertEqual(r.sync_enabled, "yes")


if __name__ == "__main__":
    unittest.main()
