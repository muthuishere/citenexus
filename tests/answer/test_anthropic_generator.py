"""AnthropicGenerator — grounded answers over the native Messages API (§4b).

Anthropic is not OpenAI-shaped: POST /v1/messages, `x-api-key` (not Bearer),
an `anthropic-version` header, `system` as a top-level field, a REQUIRED
`max_tokens`, and a `content[0].text` response. This client implements the same
`Generator` protocol as OpenAICompatibleGenerator, so it drops into AnswerFlow /
TrustRAG unchanged — and still sends temperature (default 0.0) + exposes tokens.
"""

from __future__ import annotations

import json

import pytest

from trustrag.answer.anthropic import AnthropicGenerator


class RecordingTransport:
    def __init__(self, text: str = "grounded answer") -> None:
        self.text = text
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = {
            "content": [{"type": "text", "text": self.text}],
            "usage": {"input_tokens": 13, "output_tokens": 5},
        }
        return json.dumps(payload).encode("utf-8")

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.calls[-1][1])
        return body

    @property
    def last_headers(self) -> dict[str, str]:
        return self.calls[-1][2]


def _gen(
    transport: RecordingTransport,
    *,
    api_key_env: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> AnthropicGenerator:
    return AnthropicGenerator(
        base_url="https://api.anthropic.test",
        model="claude-opus-4-8",
        api_key_env=api_key_env,
        temperature=temperature,
        max_tokens=max_tokens,
        transport=transport,
    )


def test_plugin_version() -> None:
    assert AnthropicGenerator.plugin_version == "anthropic-generator-v1"


def test_answer_reads_content_text() -> None:
    t = RecordingTransport(text="The NDA forbids disclosure.")
    assert _gen(t).answer("Can they disclose?", "The NDA forbids disclosure.") == (
        "The NDA forbids disclosure."
    )


def test_posts_to_messages_endpoint_with_model() -> None:
    t = RecordingTransport()
    _gen(t).answer("q", "passage")
    assert t.calls[-1][0] == "https://api.anthropic.test/v1/messages"
    assert t.last_body["model"] == "claude-opus-4-8"


def test_temperature_and_max_tokens_always_sent() -> None:
    t = RecordingTransport()
    _gen(t, temperature=0.0, max_tokens=256).answer("q", "passage")
    assert t.last_body["temperature"] == 0.0
    assert t.last_body["max_tokens"] == 256  # required by the Messages API


def test_system_is_top_level_and_passage_in_user_turn() -> None:
    t = RecordingTransport()
    _gen(t).answer("Can they disclose?", "The NDA forbids disclosure.", "de")
    assert isinstance(t.last_body["system"], str)
    messages = t.last_body["messages"]
    assert isinstance(messages, list)
    blob = json.dumps(messages)
    assert "Can they disclose?" in blob
    assert "The NDA forbids disclosure." in blob
    assert "de" in blob


def test_api_key_flows_only_through_x_api_key_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-ant-not-a-real-key"
    monkeypatch.setenv("TRUSTRAG_ANTHROPIC_KEY", secret)
    t = RecordingTransport()
    _gen(t, api_key_env="TRUSTRAG_ANTHROPIC_KEY").answer("q", "passage")
    headers = t.last_headers
    assert headers["x-api-key"] == secret
    assert headers["anthropic-version"]
    assert "Authorization" not in headers
    url, body, _ = t.calls[-1]
    assert secret not in url
    assert secret not in body.decode("utf-8")


def test_last_usage_exposes_tokens() -> None:
    g = _gen(RecordingTransport())
    assert g.last_usage is None
    g.answer("q", "passage")
    assert g.last_usage is not None
    assert g.last_usage.input == 13
    assert g.last_usage.output == 5
