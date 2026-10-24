"""Family ``image``: PNG, JPEG, GIF or WebP bytes. Images are read by a model downstream,
so parsing raises NeedsModel."""
from __future__ import annotations

from ..model import NeedsModel, RawFile
from ._common import Content

NAME = "image"
_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")


def sniff(content: Content) -> bool:
    """Bytes start with an image signature."""
    data = content.data
    return data.startswith(_SIGNATURES) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def parse(content: Content) -> RawFile:
    """Always raises NeedsModel."""
    raise NeedsModel("image: needs a model read")
