"""Emit phase — the core builds credential-free, typed model requests.

The four seams (embed / generate / rerank / vision) each emit a typed
``ModelRequest`` carrying a fully-assembled, provider-shaped body and auth by
``${ENV}`` header NAME only. No secret value ever appears in an emitted request —
the load-bearing invariant of the request direction.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from citenexus.domain.model import (
    EmbedRequest,
    GenerateRequest,
    ModelAuth,
    RerankRequest,
    VisionRequest,
)
from citenexus.fulfiller.requests import (
    build_embed_request,
    build_generate_request,
    build_rerank_request,
    build_vision_request,
)

_AUTH = {"Authorization": "Bearer ${CN_MODEL_KEY}"}


def test_each_seam_builds_its_typed_request() -> None:
    embed = build_embed_request(
        request_id="e1",
        base_url="http://x/v1",
        model="bge-m3",
        inputs=["a", "b"],
        auth_headers=_AUTH,
    )
    generate = build_generate_request(
        request_id="g1", base_url="http://x/v1", model="qwen", prompt="hi", auth_headers=_AUTH
    )
    rerank = build_rerank_request(
        request_id="r1",
        base_url="http://x/v1",
        model="bge-rr",
        query="q",
        documents=["d"],
        auth_headers=_AUTH,
    )
    vision = build_vision_request(
        request_id="v1",
        base_url="http://x/v1",
        model="qwen-vl",
        image_url="data:image/png;base64,QUJD",
        prompt="describe",
        auth_headers=_AUTH,
    )
    assert isinstance(embed, EmbedRequest) and embed.kind == "embed"
    assert isinstance(generate, GenerateRequest) and generate.kind == "generate"
    assert isinstance(rerank, RerankRequest) and rerank.kind == "rerank"
    assert isinstance(vision, VisionRequest) and vision.kind == "vision"


def test_emitted_request_carries_env_names_never_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with the secret live in the environment, the emitted request must hold
    # only the ${ENV} template — the value expands nowhere in the core.
    monkeypatch.setenv("CN_MODEL_KEY", "sk-live-should-never-appear")
    req = build_embed_request(
        request_id="e1", base_url="http://x/v1", model="m", inputs=["hello"], auth_headers=_AUTH
    )
    wire = req.model_dump_json()
    assert "${CN_MODEL_KEY}" in wire
    assert "sk-live-should-never-appear" not in wire
    # The body is the provider-shaped payload — no auth field, no secret.
    assert "sk-live-should-never-appear" not in json.dumps(req.body)
    assert req.auth == ModelAuth(headers=_AUTH)


def test_requests_are_frozen_and_reject_unknown_fields() -> None:
    req = build_generate_request(
        request_id="g1", base_url="http://x/v1", model="m", prompt="hi", auth_headers=_AUTH
    )
    with pytest.raises(ValidationError):
        req.request_id = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        EmbedRequest(request_id="e", url="http://x", body={}, surprise=1)  # type: ignore[call-arg]


def test_kind_discriminator_is_fixed_per_subclass() -> None:
    # A subclass fixes its kind; you cannot mint an EmbedRequest labelled generate.
    with pytest.raises(ValidationError):
        EmbedRequest(request_id="e", kind="generate", url="http://x", body={})
