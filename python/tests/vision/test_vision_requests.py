"""Emit builder — the pinned, format-accurate `PendingVisionRequest` (§9).

The emitted payload is the cross-port contract a host POSTs verbatim, so its
``image_url`` MUST declare the image's *true* media type (sniffed from the magic
bytes), not a hardcoded guess — otherwise a port faithfully POSTing the payload
would mislabel a JPEG figure as PNG.
"""

from __future__ import annotations

from citenexus.vision.requests import build_pending_request, image_data_uri

_PNG = b"\x89PNG\r\n\x1a\n fake png figure"
_JPEG = b"\xff\xd8\xff\xe0 fake jpeg figure"
_GIF = b"GIF89a fake gif figure"
_WEBP = b"RIFF\x00\x00\x00\x00WEBP fake"
_UNKNOWN = b"\x00\x01\x02 not an image"


def test_data_uri_declares_true_format() -> None:
    assert image_data_uri(_PNG).startswith("data:image/png;base64,")
    assert image_data_uri(_JPEG).startswith("data:image/jpeg;base64,")
    assert image_data_uri(_GIF).startswith("data:image/gif;base64,")
    assert image_data_uri(_WEBP).startswith("data:image/webp;base64,")


def test_unrecognized_bytes_default_to_png() -> None:
    # Stable fallback for a blob with no recognized magic — matches the extractor.
    assert image_data_uri(_UNKNOWN).startswith("data:image/png;base64,")


def test_build_pending_request_uses_sniffed_mime() -> None:
    req = build_pending_request(
        document_id="doc",
        image_id="fig0",
        data=_JPEG,
        prompt="p",
        page=3,
        bbox=(1.0, 2.0, 3.0, 4.0),
        source_uri="raw/doc.pdf",
    )
    assert req.request_id == "doc::img::fig0"
    assert req.payload.image_url.startswith("data:image/jpeg;base64,")
    assert req.source_ref.page == 3
