"""Deterministic fakes for the injected endpoints (no network, no models).

- ``FakeEmbedding`` is a hashing vectorizer: text → a fixed-dim L2-normalized
  bag-of-tokens vector, so a query that shares words with a document retrieves it.
  Real similarity, fully deterministic — ideal for proving retrieval + the
  cite-or-abstain gate offline.
- ``FakeLLM`` is extractive: it answers with the cited passage verbatim, so the
  answer can never contain an ungrounded claim.
- ``FakeReranker`` is identity.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import TypeVar

from citenexus.answer.decision import LoopDecision
from citenexus.tokenize import tokenize

T = TypeVar("T")

__all__ = [
    "FakeCompletion",
    "FakeEmbedding",
    "FakeLLM",
    "FakeReranker",
    "FakeToolLLM",
    "tokenize",
]


class FakeEmbedding:
    """A deterministic hashing vectorizer."""

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in tokenize(text):
            idx = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class FakeLLM:
    """An extractive generator — answers with evidence text, never invents."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage


class FakeReranker:
    """Identity reranker — keeps the fused order."""

    def rerank(self, query: str, candidates: list[T]) -> list[T]:
        return list(candidates)


class FakeToolLLM:
    """A scripted ``DecisionModel`` for the deep-ask loop — canned, deterministic.

    Returns the queued ``LoopDecision``s in order (the last one repeats once the
    queue drains), so a test pins the exact hop-by-hop control flow with no model.
    """

    def __init__(self, decisions: Sequence[LoopDecision]) -> None:
        self._decisions = list(decisions) or [LoopDecision()]
        self._index = 0

    def decide(self, question: str, evidence: Sequence[str]) -> LoopDecision:
        decision = self._decisions[min(self._index, len(self._decisions) - 1)]
        self._index += 1
        return decision


class FakeCompletion:
    """A ``Completion`` seam that replays canned raw strings deterministically."""

    def __init__(self, replies: Sequence[str]) -> None:
        self._replies = list(replies) or [""]
        self._index = 0

    def complete(self, prompt: str) -> str:
        reply = self._replies[min(self._index, len(self._replies) - 1)]
        self._index += 1
        return reply
