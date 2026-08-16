"""SchemaSqlExtractor — one verbatim Evidence Unit per SQL ``CREATE TABLE``.

This is the byte-parity **reference** for the Rust core's ``extract/schema_sql.rs``
(the same family as ``code.py`` ↔ ``code.rs``): a deterministic, model-free DDL
scanner finds each ``CREATE TABLE`` statement and emits one ``code`` block whose
``text`` is the *verbatim* source span (byte-exact, including the trailing ``;``),
carrying the 1-based line range so the schema EU cites ``file:Lx-Ly``.
``structure_type = table_schema`` (reused — no new structure type).

The extractor emits **EUs only, no edges** — ``ExtractedDoc`` has no edge channel.
Foreign-key edges come from an *injected* schema distiller (see
``example/schema_graph/schema_distiller.py``), exactly like the code structural
distiller.

Scope: schema **artifacts** (a ``.sql`` dump), never a live database and never row
data. A source with no ``CREATE TABLE`` degrades to plain text — never raises
("no structure → plain, not failure").
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

# Quote/identifier delimiters recognised for a table name: ANSI double-quote,
# MySQL backtick, SQL-Server bracket. (Single-quote names are non-standard.)
_QUOTE_OPENERS = frozenset(b'"`[')
_WS = frozenset(b" \t\r\n\f")


def _is_word_byte(b: int) -> bool:
    return b in range(0x30, 0x3A) or b in range(0x41, 0x5B) or b in range(0x61, 0x7B) or b == 0x5F


def _eq_ci(data: bytes, i: int, kw: bytes) -> bool:
    """``data[i:i+len(kw)]`` equals the ASCII-lowercase ``kw``, case-insensitively."""
    if i + len(kw) > len(data):
        return False
    return data[i : i + len(kw)].lower() == kw


def _word_at(data: bytes, i: int, kw: bytes) -> bool:
    """``kw`` matches at ``i`` on ASCII word boundaries (a whole keyword)."""
    if not _eq_ci(data, i, kw):
        return False
    if i > 0 and _is_word_byte(data[i - 1]):
        return False
    end = i + len(kw)
    return end >= len(data) or not _is_word_byte(data[end])


def _line_at(data: bytes, offset: int) -> int:
    """1-based line number of byte ``offset`` (newlines before it, + 1)."""
    return 1 + data.count(b"\n", 0, offset)


def _skip_quoted(data: bytes, i: int) -> int:
    """Index just past a quoted run starting at ``data[i]`` (a quote/bracket)."""
    n = len(data)
    opener = data[i]
    close = 0x5D if opener == 0x5B else opener  # ']' for '['
    i += 1
    while i < n:
        c = data[i]
        if c == close:
            # A doubled delimiter (except brackets) is an escaped literal.
            if close != 0x5D and i + 1 < n and data[i + 1] == close:
                i += 2
                continue
            return i + 1
        i += 1
    return i


def _skip_ws_and_comments(data: bytes, i: int) -> int:
    """Skip whitespace, ``-- line`` comments, and ``/* block */`` comments."""
    n = len(data)
    while i < n:
        if data[i] in _WS:
            i += 1
        elif data[i] == 0x2D and i + 1 < n and data[i + 1] == 0x2D:  # --
            while i < n and data[i] != 0x0A:
                i += 1
        elif data[i] == 0x2F and i + 1 < n and data[i + 1] == 0x2A:  # /*
            i += 2
            while i + 1 < n and not (data[i] == 0x2A and data[i + 1] == 0x2F):
                i += 1
            i += 2
        else:
            break
    return i


def _read_name(data: bytes, i: int) -> tuple[str, int]:
    """Read a (possibly schema-qualified / quoted) table name; return its last
    segment plus the index just past it."""
    n = len(data)
    last = ""
    while i < n:
        if data[i] in _QUOTE_OPENERS:
            end = _skip_quoted(data, i)
            last = data[i + 1 : end - 1].decode("utf-8", "replace")
            i = end
        else:
            start = i
            while i < n and _is_word_byte(data[i]):
                i += 1
            if i == start:
                break
            last = data[start:i].decode("utf-8", "replace")
        if i < n and data[i] == 0x2E:  # '.'
            i += 1
            continue
        break
    return last, i


def _statement_end(data: bytes, i: int) -> int:
    """From just past the table name, return the index just past the terminating
    ``;`` (or end of input), balancing the column-definition parentheses and
    ignoring quotes/comments."""
    n = len(data)
    i = _skip_ws_and_comments(data, i)
    if i < n and data[i] == 0x28:  # '('
        depth = 0
        while i < n:
            c = data[i]
            if c in _QUOTE_OPENERS or c == 0x27:  # quotes incl. '
                i = _skip_quoted(data, i)
                continue
            if c == 0x2D and i + 1 < n and data[i + 1] == 0x2D:
                i = _skip_ws_and_comments(data, i)
                continue
            if c == 0x2F and i + 1 < n and data[i + 1] == 0x2A:
                i = _skip_ws_and_comments(data, i)
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    # Trailing table options up to the terminating semicolon.
    while i < n and data[i] != 0x3B:
        if data[i] in _QUOTE_OPENERS or data[i] == 0x27:
            i = _skip_quoted(data, i)
            continue
        i += 1
    if i < n and data[i] == 0x3B:
        i += 1
    return i


def find_tables(data: bytes) -> list[tuple[int, int, str]]:
    """Every ``CREATE TABLE`` statement as ``(start, end, table_name)`` in source
    order. ``start`` is the ``C`` of ``CREATE``; ``end`` is just past the ``;``."""
    n = len(data)
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < n:
        if _word_at(data, i, b"create"):
            j = _skip_ws_and_comments(data, i + 6)
            if _word_at(data, j, b"table"):
                k = _skip_ws_and_comments(data, j + 5)
                if _word_at(data, k, b"if"):  # optional IF NOT EXISTS
                    k = _skip_ws_and_comments(data, k + 2)
                    if _word_at(data, k, b"not"):
                        k = _skip_ws_and_comments(data, k + 3)
                        if _word_at(data, k, b"exists"):
                            k = _skip_ws_and_comments(data, k + 6)
                name, k = _read_name(data, k)
                end = _statement_end(data, k)
                out.append((i, end, name))
                i = end
                continue
        i += 1
    return out


class SchemaSqlExtractor(ExtractorPlugin):
    """Parse a SQL DDL file into one verbatim Evidence Unit per table."""

    plugin_version = "schema_sql/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        data = text.encode("utf-8")
        tables = find_tables(data)
        if not tables:
            return self._plain(text, doc_id, source_uri)

        blocks: list[ExtractedBlock] = []
        for order, (start, end, name) in enumerate(tables):
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
            source_type=SourceType.schema_sql,
            structure_type=StructureType.table_schema,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )

    @staticmethod
    def _plain(text: str, doc_id: str, source_uri: str | None) -> ExtractedDoc:
        doc = PlainExtractor(document_id=doc_id).extract(text)
        return doc.model_copy(update={"source_uri": source_uri})
