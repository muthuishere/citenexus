"""ImageExtractor — standalone image → base64 data-URI block, or placeholder."""

from __future__ import annotations

import base64

from citenexus.extract.image import MAX_INLINE_BYTES, ImageExtractor
from citenexus.extract.markdown import to_markdown
from citenexus.extract.types import BlockKind, SourceType

_PNG = b"\x89PNG\r\n\x1a\n\x01\x02"


def test_png_inlines_as_data_uri() -> None:
    doc = ImageExtractor(document_id="doc").extract(_PNG)
    assert doc.source_type is SourceType.image
    assert len(doc.blocks) == 1
    assert doc.blocks[0].kind is BlockKind.image
    encoded = base64.b64encode(_PNG).decode("ascii")
    assert doc.blocks[0].text == f"![image](data:image/png;base64,{encoded})"
    assert to_markdown(doc) == f"![image](data:image/png;base64,{encoded})\n"


def test_unknown_magic_becomes_placeholder() -> None:
    doc = ImageExtractor(document_id="doc").extract(b"not an image")
    assert doc.blocks[0].text == ""
    assert to_markdown(doc) == "![image]()\n"


def test_oversize_image_becomes_placeholder() -> None:
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_INLINE_BYTES + 1)
    doc = ImageExtractor(document_id="doc").extract(big)
    assert doc.blocks[0].text == ""
