"""EN dual-query reformulation — the researched fix for cross-lingual abstentions.

A non-English query over (mostly) English evidence often misses: embeddings
align imperfectly across languages and BM25 shares no tokens at all. The fix
(tRAG / RAG-Fusion): a SMALL model rewrites the query in English, retrieval runs
BOTH queries, and RRF fuses the lists. The original query is always kept — a
translation can damage exact tokens (names, clause numbers) that BM25 needs.

The reformulator caches by query (the shared reformulation cache) so ask(),
retrieve(), and evaluate() never pay the model twice for the same question.
Enhancement-only: any failure, or a reformulation identical to the original,
yields None and retrieval proceeds single-query.
"""

from __future__ import annotations

import json

from trustrag.retrieve.reformulate import QueryReformulator


class RecordingTransport:
    def __init__(self, reply: str = "What is the refund deadline?") -> None:
        self.reply = reply
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.calls.append((url, body, dict(headers)))
        payload = {"choices": [{"message": {"content": self.reply}}]}
        return json.dumps(payload).encode("utf-8")

    @property
    def last_body(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.calls[-1][1])
        return body


def _reformulator(t: RecordingTransport) -> QueryReformulator:
    return QueryReformulator(
        base_url="http://small.test/v1", model="gemini-2.5-flash-lite", transport=t
    )


def test_reformulates_to_english() -> None:
    t = RecordingTransport(reply="What is the refund deadline?")
    out = _reformulator(t).reformulate("Quel est le délai pour demander un remboursement?")
    assert out == "What is the refund deadline?"


def test_temperature_zero_and_query_in_prompt() -> None:
    t = RecordingTransport()
    _reformulator(t).reformulate("Quel est le délai?")
    assert t.last_body["temperature"] == 0.0
    assert "Quel est le délai?" in json.dumps(t.last_body["messages"], ensure_ascii=False)


def test_shared_cache_one_model_call_per_query() -> None:
    t = RecordingTransport()
    r = _reformulator(t)
    r.reformulate("Quel est le délai?")
    r.reformulate("Quel est le délai?")
    r.reformulate("Quel est le délai?")
    assert len(t.calls) == 1  # cache hit for repeats


def test_identical_reformulation_returns_none() -> None:
    t = RecordingTransport(reply="What is the deadline?")
    out = _reformulator(t).reformulate("What is the deadline?")
    assert out is None  # already English — no second query needed


def test_failure_returns_none_never_raises() -> None:
    def boom(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        raise RuntimeError("endpoint down")

    r = QueryReformulator(base_url="http://x/v1", model="m", transport=boom)
    assert r.reformulate("Quel est le délai?") is None
    # failures are cached too — no hammering a dead endpoint per ask()
    assert r.reformulate("Quel est le délai?") is None


def test_empty_reply_returns_none() -> None:
    t = RecordingTransport(reply="   ")
    assert _reformulator(t).reformulate("Quel est le délai?") is None
