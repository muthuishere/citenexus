"""The two-phase vision-orchestration domain types (ADR-0005, §9).

`PendingVisionRequest` is the plain-data unit the core EMITS and the host
FULFILLS: a stable `request_id`, a model-ready `payload` (data URI + prompt),
and the `source_ref` (document + page + bbox) the figure is cited to. It is
frozen, rejects unknown fields, and — the load-bearing invariant — carries no
credential of any kind (the API key lives only in the host's fulfiller).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from citenexus.domain.vision import (
    PendingVisionRequest,
    VisionPayload,
    VisionSourceRef,
)


def _request() -> PendingVisionRequest:
    return PendingVisionRequest(
        request_id="doc::img::page4-img0",
        payload=VisionPayload(
            prompt="Describe this image.", image_url="data:image/png;base64,QUJD"
        ),
        source_ref=VisionSourceRef(
            document="doc", page=4, bbox=(10.0, 20.0, 110.0, 220.0), source_uri="raw/doc.pdf"
        ),
    )


def test_carries_request_id_payload_and_source_ref() -> None:
    req = _request()
    assert req.request_id == "doc::img::page4-img0"
    assert req.payload.prompt == "Describe this image."
    assert req.payload.image_url.startswith("data:image/png;base64,")
    assert req.source_ref.document == "doc"
    assert req.source_ref.page == 4
    assert req.source_ref.bbox == (10.0, 20.0, 110.0, 220.0)


def test_is_frozen() -> None:
    req = _request()
    with pytest.raises(ValidationError):
        req.request_id = "other"  # type: ignore[misc]


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PendingVisionRequest(
            request_id="d::img::x",
            payload=VisionPayload(prompt="p", image_url="data:image/png;base64,QUJD"),
            source_ref=VisionSourceRef(document="d"),
            api_key="sk-secret",  # type: ignore[call-arg]
        )


def test_carries_no_credential_field() -> None:
    # The payload and the request expose no key/token/secret/auth field — the
    # credential can only live in the host's transport, never crossing the seam.
    banned = ("key", "token", "secret", "auth", "password", "credential")
    for model in (PendingVisionRequest, VisionPayload, VisionSourceRef):
        for name in model.model_fields:
            assert not any(word in name.lower() for word in banned), (
                f"{model.__name__}.{name} looks like a credential field"
            )
    # And a serialized request never contains a credential-shaped value.
    dumped = _request().model_dump_json()
    assert "sk-" not in dumped
    assert "authorization" not in dumped.lower()
