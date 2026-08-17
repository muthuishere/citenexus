"""Deterministic fakes for the injected endpoints (no network, no models).

- ``FakeEmbedding`` is a hashing vectorizer: text → a fixed-dim L2-normalized
  bag-of-tokens vector, so a query that shares words with a document retrieves it.
  Real similarity, fully deterministic — ideal for proving retrieval + the
  cite-or-abstain gate offline. It tokenizes with the **Unicode** tokenizer, so
  a multilingual test measures something rather than ranking zero vectors;
  ``is_zero_vector`` is the assertion that keeps that honest.
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
from citenexus.contracts import is_zero_vector as _is_zero_vector
from citenexus.tokenize import tokenize, tokenize_v2

T = TypeVar("T")

__all__ = [
    "FakeCompletion",
    "FakeEmbedding",
    "FakeLLM",
    "FakeReranker",
    "FakeToolLLM",
    "is_zero_vector",
    "tokenize",
]


#: Is ``vec`` the all-zeros vector — i.e. an embedding that carries no signal?
#:
#: An ALIAS of ``citenexus.contracts.is_zero_vector``, not a second definition.
#: This function used to live here, in ``testing/``, which is where a real
#: write-path guard sat misfiled as a test helper — and is a large part of why
#: the shipped Python write path had no vector guard at all while Go and JS both
#: did. It has been promoted to ``contracts``, beside ``check_vector``, so the
#: fakes, the write path and the ask path share ONE definition and the two
#: cannot drift apart. Kept importable from here: 0.x policy is
#: deprecated-not-removed for anything with a public appearance.
is_zero_vector = _is_zero_vector


class FakeEmbedding:
    """A deterministic hashing vectorizer.

    Tokenizes with **``tokenize_v2``** (the Unicode tokenizer, ADR-0011), not
    the frozen ASCII-only v1. With v1 every non-Latin script — Tamil, Telugu,
    Chinese, Arabic, … — produced zero tokens and therefore the **zero vector**,
    so every offline multilingual retrieval test built on these fakes was
    silently measuring nothing, and contradicted the library's own claim of 13
    supported scripts.

    Switching is safe for the pinned fixtures: v2 is a strict superset of v1 on
    pure-ASCII input, so ``conformance/cases/e2e_hermetic.json`` (an all-ASCII
    corpus) is byte-identical either way. ``ascii_only=True`` keeps the old v1
    hashing for anything that must pin the v1 behavior deliberately.
    """

    def __init__(self, dim: int = 64, *, ascii_only: bool = False) -> None:
        self.dim = dim
        self.ascii_only = ascii_only

    def _tokens(self, text: str) -> list[str]:
        return tokenize(text) if self.ascii_only else tokenize_v2(text)

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
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
