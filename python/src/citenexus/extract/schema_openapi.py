"""SchemaOpenapiExtractor — one verbatim Evidence Unit per OpenAPI/JSON-Schema object.

Byte-parity **reference** for the Rust core's ``extract/schema_openapi.rs``. A
deterministic, span-preserving JSON scanner (no re-serialization) locates the
schema objects and emits one ``code`` block per object whose ``text`` is the
*verbatim* ``"key": value`` source span, carrying its 1-based line range so the
schema EU cites ``file:Lx-Ly``. ``structure_type = table_schema`` (reused).

Recognised objects (one EU each, in document order):

- ``paths."/orders"`` — one EU per **endpoint** (path item);
- ``components.schemas.X`` — one EU per **component** type;
- ``definitions.X`` / ``$defs.X`` — one EU per standalone JSON-Schema type.

The extractor emits **EUs only, no edges**. ``$ref`` / type-reference edges come
from an *injected* schema distiller. Non-JSON input (e.g. YAML) or a doc with no
recognised section degrades to plain text — never raises. (YAML OpenAPI parsing
is a follow-on; only JSON is span-extracted today.)
"""

from __future__ import annotations

from typing import Any

from citenexus.extract.plain import PlainExtractor, load_text
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from citenexus.plugins.base import ExtractorPlugin

_WS = frozenset(b" \t\r\n\f")


def _line_at(data: bytes, offset: int) -> int:
    return 1 + data.count(b"\n", 0, offset)


def _skip_ws(data: bytes, i: int) -> int:
    n = len(data)
    while i < n and data[i] in _WS:
        i += 1
    return i


def _parse_string(data: bytes, i: int) -> int:
    """``data[i]`` is ``"``; return the index just past the closing quote."""
    n = len(data)
    i += 1
    while i < n:
        c = data[i]
        if c == 0x5C:  # backslash escape
            i += 2
            continue
        if c == 0x22:  # closing quote
            return i + 1
        i += 1
    return i


def _skip_value(data: bytes, i: int) -> int:
    """Return the index just past the JSON value beginning at ``data[i]``."""
    n = len(data)
    i = _skip_ws(data, i)
    if i >= n:
        return i
    c = data[i]
    if c == 0x22:  # string
        return _parse_string(data, i)
    if c == 0x7B or c == 0x5B:  # object / array
        depth = 0
        while i < n:
            c = data[i]
            if c == 0x22:
                i = _parse_string(data, i)
                continue
            if c == 0x7B or c == 0x5B:
                depth += 1
            elif c == 0x7D or c == 0x5D:
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return i
    # primitive: number / true / false / null
    while i < n and data[i] not in (0x2C, 0x7D, 0x5D) and data[i] not in _WS:
        i += 1
    return i


def _members(data: bytes, obj_start: int) -> list[tuple[str, int, int, int]]:
    """Immediate members of the object at ``data[obj_start] == '{'`` as
    ``(key, entry_start, value_start, entry_end)`` in document order.

    ``entry_start`` is the key's opening quote; ``value_start`` is the first
    non-whitespace byte of the value; ``entry_end`` is just past the value."""
    n = len(data)
    out: list[tuple[str, int, int, int]] = []
    i = obj_start + 1
    while i < n:
        i = _skip_ws(data, i)
        if i >= n or data[i] == 0x7D:
            break
        if data[i] == 0x2C:  # comma
            i += 1
            continue
        if data[i] != 0x22:  # malformed
            break
        key_start = i
        key_end = _parse_string(data, i)
        key = data[key_start + 1 : key_end - 1].decode("utf-8", "replace")
        i = _skip_ws(data, key_end)
        if i >= n or data[i] != 0x3A:  # ':'
            break
        value_start = _skip_ws(data, i + 1)
        value_end = _skip_value(data, value_start)
        out.append((key, key_start, value_start, value_end))
        i = value_end
    return out


def find_objects(data: bytes) -> list[tuple[str, int, int]]:
    """Every recognised schema object as ``(name, entry_start, entry_end)`` in
    document order. Empty when the input is not a JSON object or has no section."""
    i = _skip_ws(data, 0)
    if i >= len(data) or data[i] != 0x7B:
        return []
    out: list[tuple[str, int, int]] = []
    for key, _kstart, vstart, _vend in _members(data, i):
        if data[vstart] != 0x7B:
            continue
        if key == "paths":
            for pk, ps, _pv, pe in _members(data, vstart):
                out.append((pk, ps, pe))
        elif key == "components":
            for ck, _cks, cvs, _cve in _members(data, vstart):
                if ck == "schemas" and data[cvs] == 0x7B:
                    for sk, ss, _sv, se in _members(data, cvs):
                        out.append((sk, ss, se))
        elif key in ("definitions", "$defs"):
            for dk, ds, _dv, de in _members(data, vstart):
                out.append((dk, ds, de))
    return out


class SchemaOpenapiExtractor(ExtractorPlugin):
    """Parse an OpenAPI / JSON-Schema document into one verbatim EU per object."""

    plugin_version = "schema_openapi/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        data = text.encode("utf-8")
        objects = find_objects(data)
        if not objects:
            return self._plain(text, doc_id, source_uri)

        blocks: list[ExtractedBlock] = []
        for order, (name, start, end) in enumerate(objects):
            blocks.append(
                ExtractedBlock(
                    order=order,
                    kind=BlockKind.code,
                    text=data[start:end].decode("utf-8", "replace"),
                    level=0,
                    start_line=_line_at(data, start),
                    end_line=_line_at(data, max(start, end - 1)),
                    structure_path=(name,) if name else (),
                )
            )
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.schema_openapi,
            structure_type=StructureType.table_schema,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )

    @staticmethod
    def _plain(text: str, doc_id: str, source_uri: str | None) -> ExtractedDoc:
        doc = PlainExtractor(document_id=doc_id).extract(text)
        return doc.model_copy(update={"source_uri": source_uri})
