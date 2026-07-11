"""Magic-byte image MIME sniffing (§8, §9).

Shared by the image extractor (inline data-URI blocks) and the two-phase vision
emit phase (the `PendingVisionRequest` payload), so both label a data URI with
the image's *true* format instead of a hardcoded guess. Dependency-free and
byte-for-byte mirrored by the Rust twin (`rust/src/extract/image.rs`); the
recognized set (png/jpeg/gif/webp) is part of the cross-port contract.
"""

from __future__ import annotations


def sniff_image_subtype(data: bytes) -> str | None:
    """Recognize the image type from its magic bytes → the ``image/<subtype>``
    subtype (``png``/``jpeg``/``gif``/``webp``), or ``None`` if unrecognized."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None
