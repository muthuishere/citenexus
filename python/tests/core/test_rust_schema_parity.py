"""Python ↔ Rust schema-extraction parity — the schema extractors' conformance arbiter.

The Rust core (`rust/src/extract/schema_sql.rs` / `schema_openapi.rs`) and the
Python references (`extract/schema_sql.py` / `schema_openapi.py`) use the SAME
deterministic byte scanners, so `citenexus_extract(bytes, "schema_sql"|"schema_openapi", …)`
MUST produce the SAME ExtractedDoc as the Python extractors for the same source.
This loads the built cdylib via ctypes and compares field-for-field. Skips when
the dylib isn't built:

    task core:build   (or: cd rust && cargo build)
"""

from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path
from typing import Any

import pytest

from citenexus.extract.schema_openapi import SchemaOpenapiExtractor
from citenexus.extract.schema_sql import SchemaSqlExtractor
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


_SQL = (
    "-- users schema\n"
    "CREATE TABLE accounts (\n"
    "    id INTEGER PRIMARY KEY,\n"
    "    name TEXT NOT NULL\n"
    ");\n"
    "\n"
    "CREATE TABLE IF NOT EXISTS orders (\n"
    "    id INTEGER PRIMARY KEY,\n"
    "    account_id INTEGER REFERENCES accounts(id),\n"
    "    total NUMERIC\n"
    ");\n"
)
_OPENAPI = (
    "{\n"
    '  "openapi": "3.0.0",\n'
    '  "paths": {\n'
    '    "/orders": {\n'
    '      "post": { "requestBody": { "content": {} } }\n'
    "    },\n"
    '    "/accounts/{id}": { "get": {} }\n'
    "  },\n"
    '  "components": {\n'
    '    "schemas": {\n'
    '      "Order": {\n'
    '        "type": "object",\n'
    '        "properties": { "account": { "$ref": "#/components/schemas/Account" } }\n'
    "      },\n"
    '      "Account": { "type": "object" }\n'
    "    }\n"
    "  }\n"
    "}\n"
)


def test_rust_sql_matches_python(core: ctypes.CDLL) -> None:
    python_doc = SchemaSqlExtractor(document_id="doc").extract(_SQL)
    rust_doc = rust_extract(core, _SQL.encode("utf-8"), "schema_sql")

    assert rust_doc["source_type"] == str(python_doc.source_type.value) == "schema_sql"
    assert rust_doc["structure_type"] == str(python_doc.structure_type.value) == "table_schema"
    assert blocks_of(rust_doc) == blocks_of(python_doc)


def test_rust_openapi_matches_python(core: ctypes.CDLL) -> None:
    python_doc = SchemaOpenapiExtractor(document_id="doc").extract(_OPENAPI)
    rust_doc = rust_extract(core, _OPENAPI.encode("utf-8"), "schema_openapi")

    assert rust_doc["source_type"] == str(python_doc.source_type.value) == "schema_openapi"
    assert rust_doc["structure_type"] == str(python_doc.structure_type.value) == "table_schema"
    assert blocks_of(rust_doc) == blocks_of(python_doc)


def test_table_becomes_citable_schema_eu_across_abi(core: ctypes.CDLL) -> None:
    """A table's verbatim DDL + its line range travel across the ABI, no edges."""
    rust_doc = rust_extract(core, _SQL.encode("utf-8"), "schema_sql")
    accounts = next(b for b in rust_doc["blocks"] if b["structure_path"] == ["accounts"])
    assert accounts["kind"] == "code"
    assert accounts["text"].startswith("CREATE TABLE accounts (")
    assert accounts["start_line"] == 2
    # The extractor emits EUs only — no edge channel exists on ExtractedDoc.
    assert "edges" not in rust_doc


def test_openapi_endpoint_is_verbatim_eu_across_abi(core: ctypes.CDLL) -> None:
    rust_doc = rust_extract(core, _OPENAPI.encode("utf-8"), "schema_openapi")
    endpoint = next(b for b in rust_doc["blocks"] if b["structure_path"] == ["/orders"])
    assert endpoint["text"].startswith('"/orders"')


def test_unrecognised_schema_falls_back_to_plain(core: ctypes.CDLL) -> None:
    """A source no schema extractor recognises degrades to plain — never raises."""
    src = "openapi: 3.0.0\npaths:\n  /x: {}\n"  # YAML, not JSON
    python_doc = SchemaOpenapiExtractor(document_id="doc").extract(src)
    rust_doc = rust_extract(core, src.encode("utf-8"), "schema_openapi")

    assert python_doc.source_type is SourceType.plain
    assert python_doc.structure_type is StructureType.none
    assert rust_doc["source_type"] == "plain"
    assert blocks_of(rust_doc) == blocks_of(python_doc)
