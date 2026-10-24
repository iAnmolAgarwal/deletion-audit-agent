"""Family ``pdf_text``: a PDF read from its text layer, one record per page.

A PDF with no text on any page raises NeedsModel.
"""
from __future__ import annotations

import io

from ..model import NeedsModel, ParseError, RawFile, RawRecord
from ._common import Content

NAME = "pdf_text"


def sniff(content: Content) -> bool:
    """Bytes start with the PDF signature."""
    return content.data.startswith(b"%PDF-")


def _page_texts(data: bytes) -> list[str]:
    """Text layer of every page."""
    import pdfplumber  # imported here so non-PDF parsing does not need the library loaded

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:  # pdfplumber raises several unrelated types on bad input
        raise ParseError(f"PDF could not be opened ({type(exc).__name__})") from None


def parse(content: Content) -> RawFile:
    """One RawRecord per page that has text."""
    texts = _page_texts(content.data)
    records = [
        RawRecord(locator_kind="pdf_page", ref=f"p{n}", fields={"page": str(n)},
                  record_time=None, trace_id=None, source_system=None, container=None,
                  event=None, text=text)
        for n, text in enumerate(texts, start=1) if text.strip()
    ]
    if not records:
        raise NeedsModel("PDF has no text layer")
    return RawFile(records=tuple(records))
