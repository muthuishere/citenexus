"""The deterministic fake fulfiller — emit → fulfill → parse runs offline.

``FakeModelFulfiller`` returns canned, deterministic JSON with no network and no
credential, so the whole two-phase protocol is exercisable in a hermetic unit test.
"""

from __future__ import annotations

from citenexus.domain.model import ModelResponse
from citenexus.fulfiller.fake import FakeModelFulfiller
from citenexus.fulfiller.requests import (
    build_embed_request,
    build_generate_request,
    build_rerank_request,
    build_vision_request,
)

_AUTH = {"Authorization": "Bearer ${CN_MODEL_KEY}"}


def test_emit_fulfill_parse_runs_offline_for_every_seam() -> None:
    fake = FakeModelFulfiller()
    embed = fake.fulfill(
        build_embed_request(
            request_id="e1",
            base_url="http://x/v1",
            model="m",
            inputs=["a", "b"],
            auth_headers=_AUTH,
        )
    )
    generate = fake.fulfill(
        build_generate_request(
            request_id="g1", base_url="http://x/v1", model="m", prompt="hi", auth_headers=_AUTH
        )
    )
    rerank = fake.fulfill(
        build_rerank_request(
            request_id="r1",
            base_url="http://x/v1",
            model="m",
            query="q",
            documents=["d0", "d1"],
            auth_headers=_AUTH,
        )
    )
    vision = fake.fulfill(
        build_vision_request(
            request_id="v1",
            base_url="http://x/v1",
            model="m",
            image_url="data:image/png;base64,QUJD",
            prompt="p",
            auth_headers=_AUTH,
        )
    )

    for resp in (embed, generate, rerank, vision):
        assert isinstance(resp, ModelResponse)
        assert resp.status == 200
    # Shapes are provider-canonical and sized to the inputs.
    assert len(embed.body["data"]) == 2
    assert generate.body["choices"][0]["message"]["content"]
    assert len(rerank.body["results"]) == 2
    assert vision.body["choices"][0]["message"]["content"]


def test_fake_is_deterministic() -> None:
    req = build_embed_request(
        request_id="e1",
        base_url="http://x/v1",
        model="m",
        inputs=["a", "b", "c"],
        auth_headers=_AUTH,
    )
    a = FakeModelFulfiller().fulfill(req)
    b = FakeModelFulfiller().fulfill(req)
    assert a.body == b.body


def test_fake_honors_scripted_responses() -> None:
    canned = {"choices": [{"message": {"content": "scripted"}}]}
    fake = FakeModelFulfiller(responses={"g1": canned})
    resp = fake.fulfill(
        build_generate_request(
            request_id="g1", base_url="http://x/v1", model="m", prompt="hi", auth_headers=_AUTH
        )
    )
    assert resp.body == canned
