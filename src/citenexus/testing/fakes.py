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
import re
from typing import TypeVar

_TOKEN_RE = re.compile(r"[a-z0-9]+")
T = TypeVar("T")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


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
