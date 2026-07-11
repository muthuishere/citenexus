"""Pure builder for the emit phase's `PendingVisionRequest` (ADR-0005, §9).

The deterministic heart of the emit phase, factored out of the I/O-bound ingest
pipeline so the *exact* request bytes — the data URI encoding, the prompt, the
``request_id`` format — are computed in one place and pinned as conformance
fixtures. The pipeline layers the §9 gate and blob loading on top; this owns only
the plain-data shaping the ports must reproduce byte-for-byte.
"""

from __future__ import annotations

import base64

from citenexus.domain.vision import BBox, PendingVisionRequest, VisionPayload, VisionSourceRef
from citenexus.extract.mime import sniff_image_subtype

# Fallback subtype when the bytes carry no recognized magic — matches the
# extractor's and prior default so unrecognized blobs stay stable.
_DEFAULT_SUBTYPE = "png"


def image_data_uri(data: bytes) -> str:
    """Encode image bytes as an OpenAI-shaped base64 ``image_url`` data URI.

    The core owns the payload, so it declares the image's *true* format by
    sniffing the magic bytes (§9) — a JPEG figure emits ``data:image/jpeg`` — so
    a port that POSTs the pinned payload verbatim never mislabels the media type.
    """
    subtype = sniff_image_subtype(data) or _DEFAULT_SUBTYPE
    return f"data:image/{subtype};base64,{base64.b64encode(data).decode()}"


def build_pending_request(
    *,
    document_id: str,
    image_id: str,
    data: bytes,
    prompt: str,
    page: int | None = None,
    bbox: BBox | None = None,
    source_uri: str | None = None,
) -> PendingVisionRequest:
    """Shape one image + its bytes into a model-ready, credential-free request."""
    return PendingVisionRequest(
        request_id=f"{document_id}::img::{image_id}",
        payload=VisionPayload(prompt=prompt, image_url=image_data_uri(data)),
        source_ref=VisionSourceRef(
            document=document_id, page=page, bbox=bbox, source_uri=source_uri
        ),
    )
