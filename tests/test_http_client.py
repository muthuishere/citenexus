"""The shared HttpClient — one HTTP layer for every model API (§4b).

Providers differ in headers (Bearer vs x-api-key vs api-key, gateway headers
like HTTP-Referer), and in patience. HttpClient is the single default transport
behind every model client: default headers, per-client extra headers, a real
timeout, and the User-Agent — merged predictably (base < extras < per-call, so
auth set by the client always wins).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citenexus.http import HttpClient


def test_header_merge_order() -> None:
    client = HttpClient(headers={"HTTP-Referer": "https://citenexus.dev", "X-Title": "app"})
    merged = client.build_headers({"Authorization": "Bearer x", "Content-Type": "application/json"})
    assert merged["User-Agent"] == "citenexus"
    assert merged["HTTP-Referer"] == "https://citenexus.dev"
    assert merged["Authorization"] == "Bearer x"  # per-call (auth) wins


def test_per_call_headers_override_defaults() -> None:
    client = HttpClient(headers={"X-Env": "default"})
    assert client.build_headers({"X-Env": "call"})["X-Env"] == "call"


def test_timeout_is_carried() -> None:
    assert HttpClient(timeout_s=7.5).timeout_s == 7.5
    assert HttpClient().timeout_s == 60.0


def test_generator_extra_headers_reach_the_wire(tmp_path: Path) -> None:
    from citenexus.answer.generator import OpenAICompatibleGenerator

    seen: list[dict[str, str]] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.append(dict(headers))
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    gen = OpenAICompatibleGenerator(
        base_url="http://llm.test/v1",
        model="m",
        extra_headers={"HTTP-Referer": "https://citenexus.dev"},
        transport=transport,
    )
    gen.answer("q", "passage")
    assert seen[0]["HTTP-Referer"] == "https://citenexus.dev"


def test_anthropic_extra_headers_do_not_clobber_auth(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setenv("K", "secret-k")
    from citenexus.answer.anthropic import AnthropicGenerator

    seen: list[dict[str, str]] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.append(dict(headers))
        return json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()

    gen = AnthropicGenerator(
        base_url="https://api.anthropic.test",
        model="m",
        api_key_env="K",
        extra_headers={"anthropic-beta": "context-1m", "x-api-key": "attacker"},
        transport=transport,
    )
    gen.answer("q", "p")
    assert seen[0]["anthropic-beta"] == "context-1m"
    assert seen[0]["x-api-key"] == "secret-k"  # client auth always wins


def test_from_config_threads_headers(tmp_path: Path) -> None:
    from citenexus import CiteNexus
    from citenexus.config.schema import CiteNexusConfig, LLMConfig, StorageConfig
    from citenexus.lang.detect import HeuristicDetector

    seen: list[dict[str, str]] = []

    def llm_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        seen.append(dict(headers))
        payload = json.loads(body)
        user = payload["messages"][-1]["content"]
        passage = user.split("Passage:\n", 1)[1].split("\n\nQuestion:", 1)[0]
        return json.dumps({"choices": [{"message": {"content": passage}}]}).encode()

    cfg = CiteNexusConfig(
        storage=StorageConfig(bucket=str(tmp_path)),
        llm=LLMConfig(
            endpoint="http://llm.test/v1",
            headers={"HTTP-Referer": "https://citenexus.dev"},
        ),
    )
    rag = CiteNexus.from_config(cfg, detector=HeuristicDetector(), llm_transport=llm_transport)
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    rag.ask("What does termination require?")
    assert seen and seen[0]["HTTP-Referer"] == "https://citenexus.dev"
