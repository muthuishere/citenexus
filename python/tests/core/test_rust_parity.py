"""Python ↔ Rust extraction parity — the core's conformance arbiter.

citenexus-core (core/) must produce the SAME ExtractedDoc as the Python
extractors for the same bytes (SPEC-PORTS-v1 §3.4: one parser implementation,
byte-identical output). This test loads the built cdylib via ctypes and
compares field-for-field. Skips when the dylib isn't built:

    task core:build   (or: cd core && cargo build)
"""

from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path
from typing import Any

import pytest

from citenexus.extract.csv import CsvExtractor
from citenexus.extract.html import HtmlExtractor
from citenexus.extract.markdown import to_markdown
from citenexus.extract.md import MdExtractor
from citenexus.extract.txt import TxtExtractor
from citenexus.extract.xlsx import XlsxExtractor

_CORE = Path(__file__).resolve().parents[3] / "rust"
_FIXTURES = Path(__file__).resolve().parents[3] / "conformance" / "fixtures"
_LIB_NAME = {
    "Darwin": "libcitenexus_core.dylib",
    "Linux": "libcitenexus_core.so",
    "Windows": "citenexus_core.dll",
}[platform.system()]


def _dylib() -> Path | None:
    for profile in ("debug", "release"):
        candidate = _CORE / "target" / profile / _LIB_NAME
        if candidate.exists():
            return candidate
    return None


@pytest.fixture(scope="module")
def core() -> ctypes.CDLL:
    path = _dylib()
    if path is None:
        pytest.skip("citenexus-core not built (run: task core:build)")
    lib = ctypes.CDLL(str(path))
    lib.citenexus_extract.restype = ctypes.c_void_p
    lib.citenexus_extract.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_char_p,
    ]
    lib.citenexus_to_markdown.restype = ctypes.c_void_p
    lib.citenexus_to_markdown.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
    ]
    lib.citenexus_free_string.argtypes = [ctypes.c_void_p]
    return lib


def rust_extract(lib: ctypes.CDLL, data: bytes, source_type: str) -> dict[str, Any]:
    raw = lib.citenexus_extract(data, len(data), source_type.encode(), b"doc")
    try:
        payload: dict[str, Any] = json.loads(ctypes.string_at(raw).decode("utf-8"))
    finally:
        lib.citenexus_free_string(raw)
    assert "error" not in payload, payload.get("error")
    return payload


def rust_markdown(lib: ctypes.CDLL, data: bytes, source_type: str) -> str:
    raw = lib.citenexus_to_markdown(data, len(data), source_type.encode())
    try:
        payload: dict[str, Any] = json.loads(ctypes.string_at(raw).decode("utf-8"))
    finally:
        lib.citenexus_free_string(raw)
    assert "error" not in payload, payload.get("error")
    markdown: str = payload["markdown"]
    return markdown


def blocks_of(doc: Any) -> list[dict[str, Any]]:
    """Comparable view of blocks: the fields both sides must agree on."""
    out = []
    for b in doc["blocks"] if isinstance(doc, dict) else (x.model_dump() for x in doc.blocks):
        out.append(
            {
                "order": b["order"],
                "kind": str(b["kind"]),
                "text": b["text"],
                "page": b["page"],
                "level": b["level"],
                "structure_path": list(b["structure_path"]),
                "cells": list(b["cells"]),
            }
        )
    return out


_TXT = "First paragraph.\n\nSecond one\nspans lines.\n\n"
_CSV = "name,age\nada,36\nalan,41\n"
_MD = "# Title\n\nIntro para.\n\n## Section\n\nBody para.\n"
_HTML = (
    "<html><body><h1>Policy</h1><script>var x=1;</script>"
    "<p>Employees accrue leave.</p><h2>Remote</h2><p>Needs approval.</p></body></html>"
)
_HTML_RICH = (
    "<html><body><h1>Guide</h1>"
    '<p>See <a href="https://x.test/leave">the policy</a> for details.</p>'
    "<ul><li>First point</li><li>Second <b>bold</b> point</li></ul>"
    '<ol><li>Step <a href="/a">one</a></li><li>Step two</li></ol>'
    "</body></html>"
)


@pytest.mark.parametrize(
    ("source_type", "text", "extractor"),
    [
        ("txt", _TXT, TxtExtractor),
        ("csv", _CSV, CsvExtractor),
        ("md", _MD, MdExtractor),
        ("html", _HTML, HtmlExtractor),
        ("html", _HTML_RICH, HtmlExtractor),
    ],
)
def test_rust_matches_python(
    core: ctypes.CDLL, source_type: str, text: str, extractor: type
) -> None:
    python_doc = extractor(document_id="doc").extract(text)
    rust_doc = rust_extract(core, text.encode("utf-8"), source_type)

    assert rust_doc["document_id"] == python_doc.document_id
    assert rust_doc["source_type"] == str(python_doc.source_type.value)
    assert rust_doc["structure_type"] == str(python_doc.structure_type.value)
    assert blocks_of(rust_doc) == blocks_of(python_doc)


@pytest.mark.parametrize(
    ("source_type", "text", "extractor"),
    [
        ("txt", _TXT, TxtExtractor),
        ("csv", _CSV, CsvExtractor),
        ("md", _MD, MdExtractor),
        ("html", _HTML, HtmlExtractor),
        ("html", _HTML_RICH, HtmlExtractor),
    ],
)
def test_markdown_parity_text_formats(
    core: ctypes.CDLL, source_type: str, text: str, extractor: type
) -> None:
    """to_markdown(extract(...)) in Python == citenexus_to_markdown, byte-identical."""
    python_md = to_markdown(extractor(document_id="doc").extract(text))
    rust_md = rust_markdown(core, text.encode("utf-8"), source_type)
    assert rust_md == python_md


def test_image_extract_and_markdown_parity(core: ctypes.CDLL) -> None:
    from citenexus.extract.image import ImageExtractor

    png = b"\x89PNG\r\n\x1a\n" + bytes(range(64)) * 4
    python_doc = ImageExtractor(document_id="doc").extract(png)
    rust_doc = rust_extract(core, png, "image")

    assert rust_doc["source_type"] == str(python_doc.source_type.value)
    assert blocks_of(rust_doc) == blocks_of(python_doc)
    assert rust_markdown(core, png, "image") == to_markdown(python_doc)


def test_xlsx_extract_and_markdown_parity(core: ctypes.CDLL) -> None:
    data = (_FIXTURES / "sample.xlsx").read_bytes()
    python_doc = XlsxExtractor(document_id="doc").extract(data)
    rust_doc = rust_extract(core, data, "xlsx")

    assert rust_doc["source_type"] == str(python_doc.source_type.value)
    assert rust_doc["structure_type"] == str(python_doc.structure_type.value)
    assert blocks_of(rust_doc) == blocks_of(python_doc)
    assert rust_markdown(core, data, "xlsx") == to_markdown(python_doc)
