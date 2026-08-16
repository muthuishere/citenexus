"""Fulfill phase — the reference host fulfiller, both-direction key safety.

The host expands ``${ENV}`` only at the HTTP boundary (request direction) and
scrubs any reflected credential out of the response before it re-enters the core
(response direction). No secret value may appear in any core-visible value or log.
"""

from __future__ import annotations

import json
import logging

import pytest

from citenexus.domain.model import GenerateRequest, ModelAuth
from citenexus.fulfiller.host import ModelFulfiller
from citenexus.fulfiller.requests import build_generate_request

_SECRET = "sk-live-TOPSECRET-4242"
_AUTH = {"Authorization": "Bearer ${CN_MODEL_KEY}"}


def _request() -> GenerateRequest:
    return build_generate_request(
        request_id="g1", base_url="http://vl.test/v1", model="m", prompt="hi", auth_headers=_AUTH
    )


def test_host_expands_env_only_at_the_http_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CN_MODEL_KEY", _SECRET)
    seen: dict[str, str] = {}

    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.update(headers)
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    resp = ModelFulfiller(transport=transport).fulfill(_request())

    # The live value is materialized ONLY in the transport's headers.
    assert seen["Authorization"] == f"Bearer {_SECRET}"
    # The parsed response is clean and addressed back by request_id.
    assert resp.request_id == "g1"
    assert resp.body["choices"][0]["message"]["content"] == "ok"


def test_reflected_secret_in_response_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A provider 401 body that echoes the Authorization header AND a ?key= param —
    # the two ways real providers reflect a credential back.
    monkeypatch.setenv("CN_MODEL_KEY", _SECRET)

    def leaky_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        return json.dumps(
            {
                "error": {
                    "message": "invalid key",
                    "echoed_request": {
                        "headers": {"Authorization": f"Bearer {_SECRET}"},
                        "url": f"http://vl.test/v1?key={_SECRET}",
                    },
                }
            }
        ).encode("utf-8")

    resp = ModelFulfiller(transport=leaky_transport).fulfill(_request())

    dumped = json.dumps(resp.body)
    assert _SECRET not in dumped  # reflected secret scrubbed in EITHER echo shape
    assert "[REDACTED]" in dumped  # and visibly redacted, not silently dropped


def test_no_secret_in_any_core_value_or_log_either_direction(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CN_MODEL_KEY", _SECRET)

    def leaky_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        return json.dumps({"debug": {"auth": f"Bearer {_SECRET}"}}).encode("utf-8")

    req = _request()
    with caplog.at_level(logging.DEBUG):
        resp = ModelFulfiller(transport=leaky_transport).fulfill(req)

    # Request direction: the emitted request holds the template, never the value.
    assert _SECRET not in req.model_dump_json()
    # Response direction: nothing the core receives carries the value.
    assert _SECRET not in json.dumps(resp.body)
    # Logs, in either direction, are secret-free.
    assert _SECRET not in caplog.text


def test_emitted_request_with_a_leaked_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # A malformed emit where a secret VALUE (not a ${ENV} name) leaked into the
    # body must be refused before any HTTP — the emit-carries-names-only invariant
    # is enforced, not merely documented.
    monkeypatch.setenv("CN_MODEL_KEY", _SECRET)
    bad = GenerateRequest(
        request_id="g1",
        url="http://vl.test/v1/chat/completions",
        body={"model": "m", "leaked": _SECRET},
        auth=ModelAuth(headers=_AUTH),
    )
    with pytest.raises(ValueError, match="credential"):
        ModelFulfiller(transport=lambda _u, _b, _h: b"{}").fulfill(bad)


def test_missing_env_expands_to_empty_and_scrubs_nothing() -> None:
    # No secret in the environment: the ${ENV} expands to "" and there is nothing
    # to scrub — the reference must not over-redact or crash.
    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "fine"}}]}).encode("utf-8")

    resp = ModelFulfiller(transport=transport).fulfill(_request())
    assert resp.body["choices"][0]["message"]["content"] == "fine"
