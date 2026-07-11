"""ImageExtractor — a standalone image file → one ``image`` block whose text is
a self-contained base64 ``data:`` URI (§8, §9).

The behavior reference for the Rust twin (``rust/src/extract/image.rs``); both
emit byte-identical ``ExtractedDoc`` JSON. At or below ``MAX_INLINE_BYTES`` the
bytes are inlined as ``![image](data:image/<mime>;base64,...)``; above the cap,
or for an unrecognized magic, the block text is empty — which the markdown
emitter renders as the ``![image]()`` placeholder. Standard base64 (RFC 4648,
``+/`` alphabet, ``=`` padding, no line breaks) keeps parity with Rust.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from citenexus.extract.mime import sniff_image_subtype
from citenexus.extract.plain import open_binary
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from citenexus.plugins.base import ExtractorPlugin

# Largest raw image inlined as a data-URI (256 KiB); larger → placeholder.
MAX_INLINE_BYTES = 256 * 1024


def _read_bytes(opened: Any) -> bytes:
    """Materialize ``open_binary``'s result (path string or stream) to bytes."""
    if isinstance(opened, str):
        return Path(opened).read_bytes()
    data = opened.read()
    return data if isinstance(data, bytes) else bytes(data)


class ImageExtractor(ExtractorPlugin):
    """A single image → one image block: a base64 data-URI, or an empty
    placeholder when the format is unrecognized or exceeds the inline cap."""

    plugin_version = "image/1"

    def __init__(self, document_id: str | None = None) -> None:
        self.document_id = document_id

    def extract(self, source: Any) -> ExtractedDoc:
        opened, doc_id, source_uri = open_binary(source, self.document_id)
        data = _read_bytes(opened)
        mime = sniff_image_subtype(data)
        if mime is not None and len(data) <= MAX_INLINE_BYTES:
            encoded = base64.b64encode(data).decode("ascii")
            text = f"![image](data:image/{mime};base64,{encoded})"
        else:
            text = ""
        block = ExtractedBlock(order=0, kind=BlockKind.image, text=text)
        return ExtractedDoc(
            document_id=doc_id,
            source_type=SourceType.image,
            structure_type=StructureType.none,
            source_uri=source_uri,
            blocks=(block,),
        )
