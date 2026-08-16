"""Python ↔ Rust code-extraction parity — the code extractor's conformance arbiter.

The Rust core (`rust/src/extract/code.rs`) and the Python reference
(`extract/code.py`) use the SAME tree-sitter grammar version (0.25) and the same
content-based language detection, so `citenexus_extract(bytes, "code", …)` MUST
produce the SAME ExtractedDoc as `CodeExtractor` for the same source. This test
loads the built cdylib via ctypes and compares field-for-field. Skips when the
dylib isn't built:

    task core:build   (or: cd rust && cargo build)
"""

from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path
from typing import Any

import pytest

from citenexus.extract.code import CodeExtractor
from citenexus.extract.types import SourceType, StructureType

_CORE = Path(__file__).resolve().parents[3] / "rust"
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


def blocks_of(doc: Any) -> list[dict[str, Any]]:
    """Comparable view of code blocks — includes the line range + structure_path."""
    out = []
    blocks = doc["blocks"] if isinstance(doc, dict) else (b.model_dump() for b in doc.blocks)
    for b in blocks:
        out.append(
            {
                "order": b["order"],
                "kind": str(b["kind"]),
                "text": b["text"],
                "level": b["level"],
                "start_line": b["start_line"],
                "end_line": b["end_line"],
                "structure_path": list(b["structure_path"]),
            }
        )
    return out


_PY = (
    "import os\n"
    "\n"
    "CONST = 3\n"
    "\n"
    "def tokenize(text):\n"
    "    return text.split()\n"
    "\n"
    "class Parser:\n"
    "    def parse(self, x):\n"
    "        return x\n"
)
_GO = (
    "package main\n"
    "\n"
    'import "fmt"\n'
    "\n"
    "func Tokenize(s string) []string {\n"
    "\treturn nil\n"
    "}\n"
    "\n"
    "type Parser struct {\n"
    "\tname string\n"
    "}\n"
    "\n"
    "func (p *Parser) Parse() {\n"
    "\tfmt.Println(p.name)\n"
    "}\n"
)


@pytest.mark.parametrize(("text",), [(_PY,), (_GO,)])
def test_rust_code_matches_python(core: ctypes.CDLL, text: str) -> None:
    python_doc = CodeExtractor(document_id="doc").extract(text)
    rust_doc = rust_extract(core, text.encode("utf-8"), "code")

    assert rust_doc["document_id"] == python_doc.document_id
    assert rust_doc["source_type"] == str(python_doc.source_type.value) == "code"
    assert rust_doc["structure_type"] == str(python_doc.structure_type.value) == "code_ast"
    assert blocks_of(rust_doc) == blocks_of(python_doc)


def test_function_becomes_citable_symbol_eu(core: ctypes.CDLL) -> None:
    """A top-level function's verbatim source + its line range travel across the ABI."""
    rust_doc = rust_extract(core, _GO.encode("utf-8"), "code")
    tokenize = next(b for b in rust_doc["blocks"] if b["text"].startswith("func Tokenize"))
    assert tokenize["kind"] == "code"
    assert tokenize["start_line"] == 5
    assert tokenize["end_line"] == 7  # file:L5-L7


def test_method_records_enclosing_class(core: ctypes.CDLL) -> None:
    rust_doc = rust_extract(core, _PY.encode("utf-8"), "code")
    method = next(b for b in rust_doc["blocks"] if b["text"].startswith("def parse"))
    assert method["structure_path"] == ["Parser"]
    assert method["level"] == 1


def test_preamble_is_preserved(core: ctypes.CDLL) -> None:
    rust_doc = rust_extract(core, _GO.encode("utf-8"), "code")
    preamble = rust_doc["blocks"][0]
    assert preamble["start_line"] == 1
    assert "package main" in preamble["text"]
    assert 'import "fmt"' in preamble["text"]


def test_unsupported_language_falls_back_to_plain(core: ctypes.CDLL) -> None:
    """A language the extractor can't parse degrades to plain text, never raises."""
    rust_source = "fn main() { println!(\"hi\"); }\n"  # Rust: not Python, not Go
    python_doc = CodeExtractor(document_id="doc").extract(rust_source)
    rust_doc = rust_extract(core, rust_source.encode("utf-8"), "code")

    assert python_doc.source_type is SourceType.plain
    assert python_doc.structure_type is StructureType.none
    assert rust_doc["source_type"] == "plain"
    assert rust_doc["structure_type"] == "none"
    assert blocks_of(rust_doc) == blocks_of(python_doc)
