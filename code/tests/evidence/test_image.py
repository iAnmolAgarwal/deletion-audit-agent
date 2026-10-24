"""Family image: images always return NEEDS_MODEL."""
from __future__ import annotations

import unittest

from ._support import assert_real_family, parse_fixture, real_index


class ImageFixture(unittest.TestCase):
    """A PNG fixture is detected by signature and needs a model read."""

    def test_fixture(self) -> None:
        fp = parse_fixture("image.png")
        self.assertEqual((fp.family, fp.status), ("image", "NEEDS_MODEL"))
        self.assertEqual((fp.observations, fp.scopes), ((), ()))
        self.assertFalse(fp.ok)


class ImageReal(unittest.TestCase):
    """Every real image is NEEDS_MODEL and is listed among the failures."""

    def test_real_files(self) -> None:
        assert_real_family(self, "image", status="NEEDS_MODEL")
        failures = {fp.file_id for fp in real_index().failures()}
        images = {fp.file_id for fp in real_index().files.values() if fp.family == "image"}
        self.assertLessEqual(images, failures)


if __name__ == "__main__":
    unittest.main()
