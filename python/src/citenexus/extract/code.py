"""CodeExtractor — one verbatim Evidence Unit per top-level code symbol.

This is the byte-parity **reference** for the Rust core's ``extract/code.rs``:
both use the SAME tree-sitter grammars (0.25) and the SAME content-based language
detection, so ``tests/core/test_rust_code_parity.py`` can prove the core output
is byte-identical. It doubles as the Python runtime extractor (like every other
``extract/*.py``): one ``code`` block per function / method / class / type /
const declaration, ``text`` = the verbatim source span, carrying the 1-based line
range so the EU cites ``file:Lx-Ly``. File preamble (package/imports) is kept as
a leading block. Unknown/unsupported source falls back to plain — never raises.

tree-sitter is an optional dependency (``pip install citenexus[code]``); without
it a code file still ingests, as plain text.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def _detect_language(text: str) -> str | None:
    """Detect the source language from content — identical to the Rust core.

    Go always carries a ``package`` clause; Python never does.
    """
    lines = text.splitlines()
    for line in lines:
        if line.lstrip().startswith("package "):
            return "go"
    for line in lines:
        stripped = line.lstrip()
        if (
            stripped.startswith("def ")
            or stripped.startswith("class ")
            or stripped.startswith("async def ")
            or stripped.startswith("import ")
            or stripped.startswith("from ")
        ):
            return "python"
    return None


@dataclass
class _Symbol:
    start_byte: int
    end_byte: int
    start_row: int
    end_row: int
    path: tuple[str, ...]


def _field_name(node: Any, source: bytes) -> str | None:
    child = node.child_by_field_name("name")
    if child is None:
        return None
    return source[child.start_byte : child.end_byte].decode("utf-8")


def _collect_python(root: Any, source: bytes) -> list[_Symbol]:
    out: list[_Symbol] = []
    for child in root.named_children:
        if child.type in ("function_definition", "class_definition"):
            _push_python_definition(child, child, source, out)
        elif child.type == "decorated_definition":
            definition = child.child_by_field_name("definition")
            if definition is not None:
                _push_python_definition(child, definition, source, out)
    return out


def _push_python_definition(
    span_node: Any, def_node: Any, source: bytes, out: list[_Symbol]
) -> None:
    """``span_node`` supplies the byte/line range (decorators included);
    ``def_node`` is the underlying function/class for the name + body recursion."""
    out.append(_symbol(span_node, ()))
    if def_node.type == "class_definition":
        class_name = _field_name(def_node, source) or ""
        body = def_node.child_by_field_name("body")
        if body is not None:
            for member in body.named_children:
                if member.type == "function_definition":
                    out.append(_symbol(member, (class_name,)))
                elif member.type == "decorated_definition":
                    definition = member.child_by_field_name("definition")
                    if definition is not None and definition.type == "function_definition":
                        out.append(_symbol(member, (class_name,)))


def _collect_go(root: Any, source: bytes) -> list[_Symbol]:
    out: list[_Symbol] = []
    top = (
        "function_declaration",
        "method_declaration",
        "type_declaration",
        "const_declaration",
        "var_declaration",
    )
    for child in root.named_children:
        if child.type in top:
            out.append(_symbol(child, ()))
    return out


def _symbol(node: Any, path: tuple[str, ...]) -> _Symbol:
    return _Symbol(
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        start_row=node.start_point[0],
        end_row=node.end_point[0],
        path=path,
    )


def _load_parser(language: str) -> Any | None:
    try:
        from tree_sitter import Language, Parser

        if language == "python":
            import tree_sitter_python as grammar
        else:
            import tree_sitter_go as grammar  # type: ignore[no-redef]
        return Parser(Language(grammar.language()))
    except Exception:
        return None


class CodeExtractor(ExtractorPlugin):
    """Parse a source file into one Evidence Unit per top-level symbol."""

    plugin_version = "code/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        language = _detect_language(text)
        parser = _load_parser(language) if language is not None else None
        if language is None or parser is None:
            return self._plain(text, doc_id, source_uri)

        source_bytes = text.encode("utf-8")
        tree = parser.parse(source_bytes)
        root = tree.root_node
        symbols = (
            _collect_python(root, source_bytes)
            if language == "python"
            else _collect_go(root, source_bytes)
        )
        symbols.sort(key=lambda s: s.start_byte)

        blocks: list[ExtractedBlock] = []
        order = 0

        first_start = symbols[0].start_byte if symbols else len(source_bytes)
        preamble = source_bytes[:first_start].decode("utf-8").rstrip()
        if preamble:
            end_row = preamble.count("\n")
            blocks.append(_code_block(order, preamble, 0, 1, end_row + 1, ()))
            order += 1

        for sym in symbols:
            symbol_text = source_bytes[sym.start_byte : sym.end_byte].decode("utf-8")
            blocks.append(
                _code_block(
                    order,
                    symbol_text,
                    len(sym.path),
                    sym.start_row + 1,
                    sym.end_row + 1,
                    sym.path,
                )
            )
            order += 1

        if not blocks:
            return self._plain(text, doc_id, source_uri)

        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.code,
            structure_type=StructureType.code_ast,
            source_uri=source_uri,
            blocks=tuple(blocks),
        )

    @staticmethod
    def _plain(text: str, doc_id: str, source_uri: str | None) -> ExtractedDoc:
        doc = PlainExtractor(document_id=doc_id).extract(text)
        return doc.model_copy(update={"source_uri": source_uri})


def _code_block(
    order: int,
    text: str,
    level: int,
    start_line: int,
    end_line: int,
    path: tuple[str, ...],
) -> ExtractedBlock:
    return ExtractedBlock(
        order=order,
        kind=BlockKind.code,
        text=text,
        level=level,
        start_line=start_line,
        end_line=end_line,
        structure_path=path,
    )
