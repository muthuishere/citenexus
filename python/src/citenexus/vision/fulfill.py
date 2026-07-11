"""Fulfill phase — the reference host-side fulfiller (ADR-0005, §9).

The two-phase seam has the host make every model call. This is the Python
reference fulfiller: given the core's `PendingVisionRequest`s and the injected
`VisionPlugin` (``OpenAICompatibleVision`` in production, ``FakeVision`` in
tests), it runs each request through the plugin — the plugin's own transport,
auth, and concurrency — and returns ``{request_id: VisionRecord}`` for the
assemble phase to join.

Two invariants live here:
- **Credential containment** — the fulfiller only ever sees `PendingVisionRequest`s
  (image content, no key); the API key stays inside the plugin's transport.
- **Per-request isolation** — a request whose fulfillment raises is dropped from
  the result (degrade-to-text), never failing the requests that succeeded.

A port in another language implements this same phase as a thin "POST payload →
return string" call; the Python reference reuses the existing `VisionPlugin`
seam by presenting each payload back as an image the plugin can describe.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any, cast

from citenexus.domain.vision import PendingVisionRequest
from citenexus.extract.types import ImageRef
from citenexus.plugins.base import VisionPlugin
from citenexus.vision.describe import (
    VisionRecord,
    _as_mapping,
    describe_image,
    record_from_mapping,
)


def _image_id(request: PendingVisionRequest) -> str:
    # The image's own id, parsed back out of the request_id
    # ``{document}::img::{image_id}`` — the assemble join keys on ``request_id``.
    return request.request_id.rsplit("::img::", 1)[-1]


class _PayloadImage:
    """Presents a request's payload back to a plain `VisionPlugin` (e.g. ``FakeVision``).

    Carries ``.image_id`` (record identity) and ``.data`` (the decoded bytes) for
    a plugin whose ``describe`` takes an image object rather than the payload."""

    def __init__(self, request: PendingVisionRequest) -> None:
        self.image_id = _image_id(request)
        _, _, b64 = request.payload.image_url.partition("base64,")
        self.data = base64.b64decode(b64) if b64 else b""


def fulfill_vision_requests(
    requests: Sequence[PendingVisionRequest], plugin: Any
) -> dict[str, VisionRecord]:
    """Run each pending request through the injected plugin; join by ``request_id``.

    A plugin that speaks the two-phase contract (``describe_payload``) is handed
    the emitted payload **verbatim**, so the reference host POSTs exactly what the
    core emitted; a plain ``describe``-only plugin gets a payload-backed image
    instead. A request whose fulfillment raises is skipped (per-request isolation),
    so a single failing image never fails the ingest of the rest.
    """
    describe_payload = getattr(plugin, "describe_payload", None)
    fulfilled: dict[str, VisionRecord] = {}
    for request in requests:
        try:
            if callable(describe_payload):
                mapping = _as_mapping(
                    describe_payload(request.payload.image_url, request.payload.prompt)
                )
                record = record_from_mapping(_image_id(request), mapping)
            else:
                record = describe_image(
                    cast("ImageRef", _PayloadImage(request)), cast("VisionPlugin", plugin)
                )
        except Exception:
            continue
        fulfilled[request.request_id] = record
    return fulfilled
