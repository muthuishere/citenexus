"""OpenAICompatibleReranker — injected transport, no network (spec §10)."""

from __future__ import annotations

import json

from trustrag.retrieve.rerank import OpenAICompatibleReranker
from trustrag.retrieve.types import Candidate, RetrievalSignal


def _c(eu_id: str) -> Candidate:
    return Candidate(eu_id=eu_id, score=0.0, signal=RetrievalSignal.vector, text=eu_id)


def test_fake_transport_reorders_by_relevance() -> None:
    captured: dict[str, object] = {}

    def fake_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        captured["url"] = url
        captured["payload"] = json.loads(body)
        return json.dumps(
            {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ]
            }
        ).encode("utf-8")

    reranker = OpenAICompatibleReranker(
        base_url="http://localhost:9/v1", model="bge-reranker", transport=fake_transport
    )
    out = reranker.rerank("q", [_c("c0"), _c("c1")])
    assert [c.eu_id for c in out] == ["c1", "c0"]
    assert captured["url"] == "http://localhost:9/v1/rerank"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["query"] == "q"
    assert payload["documents"] == ["c0", "c1"]


def test_empty_candidates_short_circuit() -> None:
    def boom(url: str, body: bytes, headers: dict[str, str]) -> bytes:  # pragma: no cover
        raise AssertionError("transport must not be called for empty input")

    reranker = OpenAICompatibleReranker(
        base_url="http://x/v1", model="m", transport=boom
    )
    assert reranker.rerank("q", []) == []


def test_plugin_version_is_non_empty() -> None:
    reranker = OpenAICompatibleReranker(
        base_url="http://x/v1", model="m", transport=lambda u, b, h: b
    )
    assert reranker.plugin_version
