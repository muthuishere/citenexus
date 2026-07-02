"""OpenAICompatibleGenerator — grounded answers over an injected transport (§4b).

Mirrors the embedding/rerank client contract: a hermetic ``transport`` seam, a
stdlib urllib default, and secrets that flow only through the Authorization
header. The generator is the answering LLM behind ``ask()`` — it MUST send
``temperature`` (default 0.0) on every call so answers are deterministic.
"""

from __future__ import annotations

import json
import socket
from urllib.parse import urlparse

import pytest

from citenexus.answer.generator import OpenAICompatibleGenerator


class RecordingTransport:
    """Hermetic fake transport: records the request, returns a canned completion."""

    def __init__(self, content: str = "grounded answer") -> None:
        self.content = content
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = {
            "choices": [{"message": {"content": self.content}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }
        return json.dumps(payload).encode("utf-8")

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.calls[-1][1])
        return body

    @property
    def last_headers(self) -> dict[str, str]:
        return self.calls[-1][2]


def _generator(
    transport: RecordingTransport,
    *,
    api_key_env: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> OpenAICompatibleGenerator:
    return OpenAICompatibleGenerator(
        base_url="http://llm.test/v1",
        model="qwen2.5",
        temperature=temperature,
        max_tokens=max_tokens,
        transport=transport,
    )


def test_plugin_version() -> None:
    assert OpenAICompatibleGenerator.plugin_version == "openai-generator-v1"


def test_answer_returns_completion_content() -> None:
    t = RecordingTransport(content="The employee shall not disclose.")
    answer = _generator(t).answer("Can they disclose?", "The employee shall not disclose.")
    assert answer == "The employee shall not disclose."


def test_posts_to_chat_completions_with_model() -> None:
    t = RecordingTransport()
    _generator(t).answer("q", "passage")
    url = t.calls[-1][0]
    assert urlparse(url).path == "/v1/chat/completions"
    assert t.last_body["model"] == "qwen2.5"


def test_temperature_zero_is_sent_by_default() -> None:
    t = RecordingTransport()
    _generator(t).answer("q", "passage")
    assert t.last_body["temperature"] == 0.0


def test_temperature_is_configurable_but_still_sent() -> None:
    t = RecordingTransport()
    _generator(t, temperature=0.3).answer("q", "passage")
    assert t.last_body["temperature"] == 0.3


def test_last_usage_exposes_token_counts() -> None:
    g = _generator(RecordingTransport())
    assert g.last_usage is None
    g.answer("q", "passage")
    assert g.last_usage is not None
    assert g.last_usage.input == 11
    assert g.last_usage.output == 7


def test_max_tokens_sent_only_when_configured() -> None:
    t = RecordingTransport()
    _generator(t).answer("q", "passage")
    assert "max_tokens" not in t.last_body

    t2 = RecordingTransport()
    _generator(t2, max_tokens=256).answer("q", "passage")
    assert t2.last_body["max_tokens"] == 256


def test_prompt_carries_question_passage_and_language() -> None:
    t = RecordingTransport()
    _generator(t).answer("Can they disclose?", "The NDA forbids disclosure.", "de")
    messages = t.last_body["messages"]
    assert isinstance(messages, list)
    blob = json.dumps(messages)
    assert "Can they disclose?" in blob
    assert "The NDA forbids disclosure." in blob
    # the required answer language is instructed to the model
    assert "de" in blob


def _real_endpoint_reachable(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:
        return False


@pytest.mark.integration
def test_real_llm_endpoint() -> None:
    import os

    base_url = os.environ.get("CITENEXUS_LLM_BASE_URL", "http://localhost:11434/v1")
    if not _real_endpoint_reachable(base_url):
        pytest.skip(f"LLM endpoint unreachable: {base_url}")
    generator = OpenAICompatibleGenerator(
        base_url=base_url,
        model=os.environ.get("CITENEXUS_LLM_MODEL", "qwen2.5"),
    )
    passage = "The employee shall not disclose confidential information."
    answer = generator.answer("Can the employee disclose information?", passage)
    assert isinstance(answer, str)
    assert answer.strip()
