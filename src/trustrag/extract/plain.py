"""PlainExtractor — raw text → one paragraph; also the unknown-type fallback (§8).

This module additionally hosts the small source-loading helpers shared by every
extractor: an extractor's ``source`` may be a filesystem path (``str``/``Path``),
raw ``str`` content, raw ``bytes``, or a binary file-like object. The helpers
normalise those forms and derive a ``document_id`` (the filename stem, or a
caller-supplied id, defaulting to ``"document"``).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from trustrag.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from trustrag.plugins.base import ExtractorPlugin


def resolve_path(source: Any) -> Path | None:
    """Return a ``Path`` iff ``source`` denotes an existing file, else ``None``.

    A ``Path`` is always treated as a filesystem path (read fails loudly if it is
    missing). A ``str`` is only treated as a path when it points at an existing
    file — otherwise it is raw content.
    """
    if isinstance(source, Path):
        return source
    if isinstance(source, str):
        try:
            candidate = Path(source)
            # exists() itself raises OSError for over-long raw content
            # (ENAMETOOLONG) — that is content, not a path.
            if candidate.exists() and candidate.is_file():
                return candidate
        except (ValueError, OSError):
            return None
    return None


def load_text(source: Any, document_id: str | None) -> tuple[str, str, str | None]:
    """Normalise ``source`` to ``(text, document_id, source_uri)``."""
    path = resolve_path(source)
    if path is not None:
        return path.read_text(encoding="utf-8"), document_id or path.stem, str(path)
    if isinstance(source, bytes):
        return source.decode("utf-8", errors="replace"), document_id or "document", None
    if isinstance(source, str):
        return source, document_id or "document", None
    raise TypeError(f"unsupported text source: {type(source)!r}")


def open_binary(source: Any, document_id: str | None) -> tuple[Any, str, str | None]:
    """Normalise ``source`` to ``(path_or_stream, document_id, source_uri)``.

    The first element is whatever the binary parsers accept directly (a path
    string or a seekable byte stream), kept loose so docx/pptx/pdf can pass it on.
    """
    path = resolve_path(source)
    if path is not None:
        return str(path), document_id or path.stem, str(path)
    if isinstance(source, bytes):
        return io.BytesIO(source), document_id or "document", None
    if hasattr(source, "read"):
        return source, document_id or "document", None
    raise TypeError(f"unsupported binary source: {type(source)!r}")


class PlainExtractor(ExtractorPlugin):
    """Treat any source as raw text and emit a single paragraph block."""

    plugin_version = "plain/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        text, doc_id, source_uri = load_text(source, self.document_id)
        block = ExtractedBlock(order=0, kind=BlockKind.paragraph, text=text)
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.plain,
            structure_type=StructureType.none,
            source_uri=source_uri,
            blocks=(block,),
        )
