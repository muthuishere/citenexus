"""Typed HTTP endpoints — config data + styled client + hooks, declared ONCE.

The application resolves its own secrets and passes the key VALUE (the library
reads NO environment); pydantic SecretStr keeps endpoints repr/log-safe.
Provider classes encode conventions (OpenAI Bearer, Anthropic x-api-key +
protocol); pre/post hooks run around every request.
"""

from __future__ import annotations

import json
from pathlib import Path

from citenexus import (
    AnthropicHttpEndpoint,
    CiteNexus,
    GeminiHttpEndpoint,
    OpenAIHttpEndpoint,
)
from citenexus.config.schema import (
    CiteNexusConfig,
    ContextModelConfig,
    LLMConfig,
    ReformulationConfig,
    StorageConfig,
)
from citenexus.lang.detect import HeuristicDetector


def _echo_llm(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    payload = json.loads(body)
    user = payload["messages"][-1]["content"]
    passage = user.split("Passage:\n", 1)[1].split("\n\nQuestion:", 1)[0]
    return json.dumps({"choices": [{"message": {"content": passage}}]}).encode()


def test_endpoint_is_repr_safe() -> None:
    ep = GeminiHttpEndpoint(api_key="super-secret-key")
    assert "super-secret-key" not in repr(ep)
    assert "super-secret-key" not in str(ep)


def test_provider_conventions() -> None:
    assert OpenAIHttpEndpoint().base_url == "https://api.openai.com/v1"
    anthropic = AnthropicHttpEndpoint(api_key="k")
    assert anthropic.protocol == "anthropic"
    assert anthropic.auth_header == "x-api-key"
    # jina is just an OpenAI-style endpoint with another base_url
    jina = OpenAIHttpEndpoint(base_url="https://api.jina.ai/v1", api_key="jk")
    assert jina.base_url == "https://api.jina.ai/v1"


def test_one_endpoint_reused_across_sections(tmp_path: Path) -> None:
    seen: list[dict[str, str]] = []

    def recorder(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.append(dict(headers))
        return _echo_llm(url, body, headers)

    gemini = GeminiHttpEndpoint(api_key="k-123", headers={"X-Team": "legal"})
    cfg = CiteNexusConfig(
        storage=StorageConfig(bucket=str(tmp_path)),
        llm=LLMConfig(endpoint=gemini, model="big"),
        reformulation=ReformulationConfig(enabled=True, endpoint=gemini, model="small"),
        context_model=ContextModelConfig(enabled=True, endpoint=gemini, model="small"),
    )
    rag = CiteNexus.from_config(
        cfg,
        detector=HeuristicDetector(),
        llm_transport=recorder,
        reformulate_transport=recorder,
        context_transport=recorder,
    )
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    rag.ask("What does termination require?")
    assert seen
    assert all(h.get("X-Team") == "legal" for h in seen)
    assert all(h.get("Authorization") == "Bearer k-123" for h in seen)


def test_anthropic_endpoint_picks_the_anthropic_wire_client(tmp_path: Path) -> None:
    seen: list[dict[str, str]] = []

    def anthropic_echo(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.append(dict(headers))
        payload = json.loads(body)
        user = payload["messages"][-1]["content"]
        passage = user.split("Passage:\n", 1)[1].split("\n\nQuestion:", 1)[0]
        return json.dumps({"content": [{"type": "text", "text": passage}]}).encode()

    cfg = CiteNexusConfig(
        storage=StorageConfig(bucket=str(tmp_path)),
        # NOTE: no provider switch needed — the endpoint type selects the client
        llm=LLMConfig(endpoint=AnthropicHttpEndpoint(api_key="sk-ant-x"), model="claude"),
    )
    rag = CiteNexus.from_config(cfg, detector=HeuristicDetector(), llm_transport=anthropic_echo)
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    assert rag.ask("What does termination require?").answer
    assert seen[0]["x-api-key"] == "sk-ant-x"
    assert "Authorization" not in seen[0]


def test_pre_and_post_hooks_run(tmp_path: Path) -> None:
    events: list[str] = []

    def pre(url: str, body: bytes, headers: dict[str, str]) -> tuple[str, bytes, dict[str, str]]:
        events.append("pre")
        return url, body, {**headers, "X-Signed": "yes"}

    def post(url: str, response: bytes) -> bytes | None:
        events.append("post")
        return None  # observe-only

    seen: list[dict[str, str]] = []

    def recorder(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.append(dict(headers))
        return _echo_llm(url, body, headers)

    ep = OpenAIHttpEndpoint(base_url="http://llm.test/v1", api_key="k", pre=pre, post=post)
    cfg = CiteNexusConfig(
        storage=StorageConfig(bucket=str(tmp_path)), llm=LLMConfig(endpoint=ep, model="m")
    )
    rag = CiteNexus.from_config(cfg, detector=HeuristicDetector(), llm_transport=recorder)
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    rag.ask("What does termination require?")
    assert events[:2] == ["pre", "post"]
    assert seen[0]["X-Signed"] == "yes"
