"""conformance/cases/model_wire.json asserted as a BINDING contract (§5).

The wire fixture is what makes ADR-0014's transport seam portable: swap the
function that moves bytes and the request the client shapes must not change.
Go pins it (``golang/models/models_test.go:69,136``) and JS pins it
(``js/src/models/models.test.ts:54``). Replayed here with an injected fake
transport — hermetic, no network, and no API key anywhere near a constructor.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from citenexus.answer.anthropic import AnthropicGenerator
from citenexus.answer.generator import OpenAICompatibleGenerator
from citenexus.embed.client import OpenAICompatibleEmbedding

from .fixtures import load_case

FIXTURE: dict[str, Any] = load_case("model_wire.json")
REQUESTS: list[dict[str, Any]] = FIXTURE["requests"]
RESPONSES: list[dict[str, Any]] = FIXTURE["responses"]

EXPECTED_COUNTS: dict[str, int] = {"requests": 4, "responses": 3}

_CANNED: dict[str, bytes] = {
    "openai_chat": b'{"choices":[{"message":{"content":"x"}}]}',
    "anthropic": b'{"content":[{"type":"text","text":"x"}]}',
    "openai_embed": b'{"data":[{"embedding":[0.1]},{"embedding":[0.2]}]}',
}


class _Capture:
    """Recording transport: stores the request, returns a canned response."""

    def __init__(self, response: bytes) -> None:
        self._response = response
        self.call: dict[str, Any] | None = None

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.call = {
            "method": "POST",
            "url": url,
            "headers": dict(headers),
            "body": json.loads(body.decode("utf-8")),
        }
        return self._response


def test_bucket_sizes() -> None:
    assert {"requests": len(REQUESTS), "responses": len(RESPONSES)} == EXPECTED_COUNTS


def test_every_client_shape_is_covered() -> None:
    assert {c["client"] for c in REQUESTS} == set(_CANNED)
    assert {c["client"] for c in RESPONSES} == set(_CANNED)


def _drive(client: str, config: dict[str, Any], inputs: dict[str, Any], transport: Any) -> object:
    if client == "openai_chat":
        chat = OpenAICompatibleGenerator(**config, transport=transport)
        return chat.answer(inputs["question"], inputs["passage"], inputs["answer_language"])
    if client == "anthropic":
        anth = AnthropicGenerator(**config, transport=transport)
        return anth.answer(inputs["question"], inputs["passage"], inputs["answer_language"])
    if client == "openai_embed":
        return OpenAICompatibleEmbedding(**config, transport=transport).embed(inputs["texts"])
    raise AssertionError(f"unknown client in fixture: {client}")


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in REQUESTS])
def test_request_wire_vector(case: dict[str, Any]) -> None:
    """The EXACT method, url, headers and JSON body the client must emit."""
    cap = _Capture(_CANNED[case["client"]])
    _drive(case["client"], case["config"], case["inputs"], cap)
    assert cap.call == case["expected_request"], case["name"]


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in RESPONSES])
def test_response_parse_vector(case: dict[str, Any]) -> None:
    body = json.dumps(case["response_body"]).encode("utf-8")

    def transport(_url: str, _body: bytes, _headers: dict[str, str]) -> bytes:
        return body

    got: object
    if case["client"] == "openai_embed":
        got = OpenAICompatibleEmbedding(
            base_url="https://x", model="m", transport=transport
        ).embed(["a", "b"])
    elif case["client"] == "openai_chat":
        got = OpenAICompatibleGenerator(
            base_url="https://x", model="m", transport=transport
        ).answer(
            "Can the employee disclose confidential information?",
            "The employee shall not disclose confidential information.",
            "en",
        )
    else:
        got = AnthropicGenerator(base_url="https://x", model="m", transport=transport).answer(
            "Can the employee disclose confidential information?",
            "The employee shall not disclose confidential information.",
            "en",
        )
    assert got == case["expected"], case["name"]


def test_no_authorization_header_on_the_wire() -> None:
    """Auth is the endpoint layer's job; a secret must never reach the fixture."""
    for case in REQUESTS:
        headers = {k.lower() for k in case["expected_request"]["headers"]}
        assert "authorization" not in headers, case["name"]
        assert "x-api-key" not in headers, case["name"]
