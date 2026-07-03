"""Dispatch — extension / explicit type / raw content → the right extractor (§8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from citenexus.extract.csv import CsvExtractor
from citenexus.extract.dispatch import extract, extractor_for
from citenexus.extract.docx import DocxExtractor
from citenexus.extract.html import HtmlExtractor
from citenexus.extract.md import MdExtractor
from citenexus.extract.pdf import PdfExtractor
from citenexus.extract.plain import PlainExtractor
from citenexus.extract.pptx import PptxExtractor
from citenexus.extract.txt import TxtExtractor
from citenexus.extract.types import ExtractedDoc, SourceType


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.txt", TxtExtractor),
        ("a.md", MdExtractor),
        ("a.markdown", MdExtractor),
        ("a.csv", CsvExtractor),
        ("a.html", HtmlExtractor),
        ("a.htm", HtmlExtractor),
        ("a.docx", DocxExtractor),
        ("a.pptx", PptxExtractor),
        ("a.pdf", PdfExtractor),
        ("a.xyz", PlainExtractor),
        ("a", PlainExtractor),
    ],
)
def test_extension_maps_to_extractor(name: str, expected: type) -> None:
    assert isinstance(extractor_for(Path(name)), expected)
    assert isinstance(extractor_for(name), expected)


def test_raw_string_falls_back_to_plain() -> None:
    assert isinstance(extractor_for("just some prose"), PlainExtractor)


def test_bytes_fall_back_to_plain() -> None:
    assert isinstance(extractor_for(b"raw bytes"), PlainExtractor)


def test_explicit_source_type_overrides_extension() -> None:
    assert isinstance(extractor_for("a.txt", source_type=SourceType.md), MdExtractor)
    assert isinstance(extractor_for("whatever", source_type=SourceType.csv), CsvExtractor)


def test_extract_convenience_returns_doc() -> None:
    doc = extract("hello world")
    assert isinstance(doc, ExtractedDoc)
    assert doc.source_type is SourceType.plain
    assert doc.blocks[0].text == "hello world"


def test_extract_passes_document_id() -> None:
    doc = extract("body text", document_id="forced-id")
    assert doc.document_id == "forced-id"
