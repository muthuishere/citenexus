"""Fulfill phase — the reference host-side fulfiller (ADR-0005, §9).

The fulfiller runs each `PendingVisionRequest` through the injected plugin and
joins by ``request_id``. Two invariants: a request whose fulfillment raises is
dropped (per-request isolation, degrade-to-text), and the fulfiller only ever
receives credential-free requests — the key stays in the plugin's transport.
"""

from __future__ import annotations

import json
from typing import Any

from citenexus.domain.vision import PendingVisionRequest, VisionPayload, VisionSourceRef
from citenexus.vision.client import OpenAICompatibleVision
from citenexus.vision.describe import FakeVision
from citenexus.vision.fulfill import fulfill_vision_requests


def _request(request_id: str) -> PendingVisionRequest:
    return PendingVisionRequest(
        request_id=request_id,
        payload=VisionPayload(prompt="p", image_url="data:image/png;base64,QUJD"),
        source_ref=VisionSourceRef(document=request_id.split("::")[0]),
    )


class _FlakyVision(FakeVision):
    """FakeVision that raises for one image id and succeeds for the rest."""

    def __init__(self, fail_image_id: str) -> None:
        self._fail = fail_image_id

    def describe(self, image_region: Any) -> dict[str, Any]:
        if getattr(image_region, "image_id", "") == self._fail:
            raise RuntimeError("transport blew up")
        return super().describe(image_region)


def test_one_failed_request_is_isolated_others_succeed() -> None:
    good = _request("doc::img::good")
    bad = _request("doc::img::bad")
    fulfilled = fulfill_vision_requests([good, bad], _FlakyVision(fail_image_id="bad"))
    # The failed request is simply absent; the good one is present.
    assert "doc::img::good" in fulfilled
    assert "doc::img::bad" not in fulfilled


def test_fulfiller_joins_by_request_id() -> None:
    req = _request("doc::img::x")
    fulfilled = fulfill_vision_requests([req], FakeVision())
    assert set(fulfilled) == {"doc::img::x"}
    assert fulfilled["doc::img::x"].short_caption


def test_reference_fulfiller_posts_emitted_payload_verbatim() -> None:
    # A JPEG figure: emit declares data:image/jpeg. The reference fulfiller must
    # POST that exact data URI (no re-encode to png) so the wire matches the
    # pinned payload a port reproduces.
    calls: list[bytes] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        calls.append(body)
        content = json.dumps({"short_caption": "A jpeg figure"})
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")

    jpeg_uri = "data:image/jpeg;base64,/9j/EMBEDDED"
    req = PendingVisionRequest(
        request_id="doc::img::fig0",
        payload=VisionPayload(prompt="describe it", image_url=jpeg_uri),
        source_ref=VisionSourceRef(document="doc"),
    )
    client = OpenAICompatibleVision(base_url="http://vl.test/v1", model="m", transport=transport)

    fulfilled = fulfill_vision_requests([req], client)

    assert fulfilled["doc::img::fig0"].short_caption == "A jpeg figure"
    body = json.dumps(json.loads(calls[-1]))
    assert jpeg_uri in body  # exact emitted data URI, jpeg label intact
    assert "image/png" not in body  # not re-encoded to the client's default mime
    assert "describe it" in body  # the emitted prompt, not a re-derived one
