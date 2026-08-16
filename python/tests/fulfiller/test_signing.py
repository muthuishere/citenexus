"""Auth scope + the host-side signing hook (spec §3).

The base protocol is ``${ENV}``-header auth. Query-param keys and request-signing
(AWS SigV4 / Bedrock) are a NAMED host-side capability: the core emits an unsigned
request tagged with the capability name; the host signer mutates it at the HTTP
boundary. The signing key never enters the core.
"""

from __future__ import annotations

import json
import os

import pytest

from citenexus.domain.model import GenerateRequest, ModelAuth, ModelRequest
from citenexus.fulfiller.host import ModelFulfiller, SignedRequest


def _query_param_signer(request: ModelRequest, headers: dict[str, str]) -> SignedRequest:
    # A host-side capability for a provider that wants the key as ?key=… — read
    # from the environment at the boundary, never from the core-built request.
    key = os.environ["CN_SIGNING_KEY"]
    signed_url = f"{request.url}?key={key}"
    # Declare the materialized secret so the fulfiller scrubs it from the response.
    return SignedRequest(url=signed_url, headers=headers, secrets=(key,))


def test_signing_provider_is_handled_host_side(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CN_SIGNING_KEY", "SIGKEY-do-not-leak-99")
    seen_url: list[str] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen_url.append(url)
        # A provider that reflects the whole request URL back in its error body.
        return json.dumps({"error": {"seen_url": url}}).encode("utf-8")

    req = GenerateRequest(
        request_id="g1",
        url="http://vl.test/v1/chat/completions",
        body={"model": "m"},
        auth=ModelAuth(sign="query-param"),  # named capability, no header creds
    )
    fulfiller = ModelFulfiller(transport=transport, signers={"query-param": _query_param_signer})
    resp = fulfiller.fulfill(req)

    # The host signed at the boundary: the wire URL carries ?key=…
    assert "?key=SIGKEY-do-not-leak-99" in seen_url[0]
    # The core-built request never held the signing key…
    assert "SIGKEY-do-not-leak-99" not in req.model_dump_json()
    # …and the reflected key is scrubbed from what the core parses back.
    assert "SIGKEY-do-not-leak-99" not in json.dumps(resp.body)


def test_unknown_signing_capability_is_a_hard_error() -> None:
    req = GenerateRequest(
        request_id="g1", url="http://x", body={}, auth=ModelAuth(sign="nonexistent")
    )
    with pytest.raises(KeyError):
        ModelFulfiller(transport=lambda _u, _b, _h: b"{}").fulfill(req)
