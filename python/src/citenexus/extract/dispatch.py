"""Dispatch — pick the extractor for a source by type / extension / content (§8).

Universal intake: a known explicit ``source_type`` wins; otherwise the file
extension of a path selects the extractor; an unknown extension, a raw string,
or raw bytes all fall back to the ``PlainExtractor``. This is the single place
that maps the world of inputs onto the one-extractor-per-type set.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Any, Protocol

from citenexus.extract.csv import CsvExtractor
from citenexus.extract.docx import DocxExtractor
from citenexus.extract.html import HtmlExtractor
from citenexus.extract.md import MdExtractor
from citenexus.extract.pdf import PdfExtractor
from citenexus.extract.plain import PlainExtractor
from citenexus.extract.pptx import PptxExtractor
from citenexus.extract.txt import TxtExtractor
from citenexus.extract.types import ExtractedDoc, SourceType
from citenexus.extract.xlsx import XlsxExtractor
from citenexus.plugins.base import ExtractorPlugin


class _ExtractorFactory(Protocol):
    """Every built-in extractor is constructed with an optional ``document_id``."""

    def __call__(self, document_id: str | None = ...) -> ExtractorPlugin: ...


# Maps a file extension (lower-case, with leading dot) to its extractor class.
_BY_EXTENSION: dict[str, _ExtractorFactory] = {
    ".txt": TxtExtractor,
    ".md": MdExtractor,
    ".markdown": MdExtractor,
    ".csv": CsvExtractor,
    ".html": HtmlExtractor,
    ".htm": HtmlExtractor,
    ".docx": DocxExtractor,
    ".pptx": PptxExtractor,
    ".xlsx": XlsxExtractor,
    ".pdf": PdfExtractor,
}

# Maps an explicit SourceType to its extractor class (types with no dedicated
# extractor in this capability — e.g. `image` — fall back to plain).
_BY_SOURCE_TYPE: dict[SourceType, _ExtractorFactory] = {
    SourceType.txt: TxtExtractor,
    SourceType.md: MdExtractor,
    SourceType.csv: CsvExtractor,
    SourceType.html: HtmlExtractor,
    SourceType.docx: DocxExtractor,
    SourceType.pptx: PptxExtractor,
    SourceType.xlsx: XlsxExtractor,
    SourceType.pdf: PdfExtractor,
    SourceType.plain: PlainExtractor,
}


def _extension_of(source: Any) -> str | None:
    """The lower-case file extension of a path-like source, else ``None``."""
    if isinstance(source, str | PurePath):
        suffix = PurePath(str(source)).suffix.lower()
        return suffix or None
    return None


def extractor_for(
    source: Any,
    *,
    source_type: SourceType | None = None,
    document_id: str | None = None,
) -> ExtractorPlugin:
    """Resolve ``source`` to a concrete extractor instance.

    An explicit ``source_type`` takes precedence; otherwise a recognised file
    extension selects the extractor; everything else falls back to plain text.
    """
    if source_type is not None:
        cls = _BY_SOURCE_TYPE.get(source_type, PlainExtractor)
        return cls(document_id=document_id)
    extension = _extension_of(source)
    cls = _BY_EXTENSION.get(extension, PlainExtractor) if extension else PlainExtractor
    return cls(document_id=document_id)


def extract(
    source: Any,
    *,
    source_type: SourceType | None = None,
    document_id: str | None = None,
) -> ExtractedDoc:
    """Convenience: resolve the right extractor and run it over ``source``."""
    doc: ExtractedDoc = extractor_for(
        source, source_type=source_type, document_id=document_id
    ).extract(source)
    return doc
