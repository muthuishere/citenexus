"""Python ↔ Rust extraction parity — the core's conformance arbiter.

trustrag-core (core/) must produce the SAME ExtractedDoc as the Python
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

from trustrag.extract.csv import CsvExtractor
from trustrag.extract.html import HtmlExtractor
from trustrag.extract.md import MdExtractor
from trustrag.extract.txt import TxtExtractor

_CORE = Path(__file__).resolve().parents[2] / "core"
_LIB_NAME = {
    "Darwin": "libtrustrag_core.dylib",
    "Linux": "libtrustrag_core.so",
    "Windows": "trustrag_core.dll",
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
        pytest.skip("trustrag-core not built (run: task core:build)")
    lib = ctypes.CDLL(str(path))
    lib.trustrag_extract.restype = ctypes.c_void_p
    lib.trustrag_extract.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_char_p,
    ]
    lib.trustrag_free_string.argtypes = [ctypes.c_void_p]
    return lib


def rust_extract(lib: ctypes.CDLL, data: bytes, source_type: str) -> dict[str, Any]:
    raw = lib.trustrag_extract(data, len(data), source_type.encode(), b"doc")
    try:
        payload: dict[str, Any] = json.loads(ctypes.string_at(raw).decode("utf-8"))
    finally:
        lib.trustrag_free_string(raw)
    assert "error" not in payload, payload.get("error")
    return payload


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


@pytest.mark.parametrize(
    ("source_type", "text", "extractor"),
    [
        ("txt", _TXT, TxtExtractor),
        ("csv", _CSV, CsvExtractor),
        ("md", _MD, MdExtractor),
        ("html", _HTML, HtmlExtractor),
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
