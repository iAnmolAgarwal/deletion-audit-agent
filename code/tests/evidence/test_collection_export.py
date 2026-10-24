"""Family collection_export: fixture expectations and every real file."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, by_ref, id_set, parse_fixture, real_index


class CollectionExportFixture(unittest.TestCase):
    """One collection, no declared scope (T50), lists flattened by index."""

    def test_fixture(self) -> None:
        fp = parse_fixture("collection_export.json")
        self.assertEqual((fp.family, fp.status), ("collection_export", "OK"))
        self.assertEqual(fp.scopes, ())
        obs = by_ref(fp)["$.records[0]"][0]
        self.assertEqual(obs.record_time, "2026-05-10T09:45:00Z")
        self.assertEqual((obs.system_id, obs.resource_id), ("export_service", "export_8008"))
        self.assertIsNone(obs.scope)
        self.assertEqual(obs.attrs["download_available"], "true")
        self.assertEqual(obs.attrs["included_sections[1]"], "orders")
        self.assertEqual(id_set(obs.record_identifiers),
                         {("email", "grace.hopper@example.test", "owner_email")})


class CollectionExportReal(unittest.TestCase):
    """Every real collection_export file parses OK with content."""

    def test_real_files(self) -> None:
        assert_real_family(self, "collection_export")

    def test_real_files_declare_no_scope(self) -> None:
        """A plain export cannot prove absence: no real file of the family has a scope."""
        files = [fp for fp in real_index().files.values() if fp.family == "collection_export"]
        self.assertTrue(files)
        for fp in files:
            self.assertEqual(fp.scopes, (), fp.file_id)
            self.assertTrue(all(o.scope is None for o in fp.observations), fp.file_id)


if __name__ == "__main__":
    unittest.main()
