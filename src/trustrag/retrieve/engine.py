"""The retrieval engine — run signals → fuse → rerank → ranked EUs (spec §10).

``RetrievalEngine`` is the in-core orchestrator: it runs each injected retriever
for the query, fuses the lists with ``rrf_fuse``, reranks the fused top-N through
the injected reranker, and returns the ranked candidates. For the v0.1 signals
(vector, lexical, structure) every candidate is already an Evidence Unit, so the
navigate-not-cite resolve-down (§10b) is a no-op here; graph / community / wiki
add it later.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from trustrag.retrieve.fusion import rrf_fuse
from trustrag.retrieve.types import Candidate

if TYPE_CHECKING:
    from trustrag.plugins.base import RetrieverPlugin


class Reranker(Protocol):
    """The rerank seam — structural so ``FakeReranker`` also satisfies it."""

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]: ...


class RetrievalEngine:
    """Wire a set of retrievers + a reranker into one ``retrieve(query, k)``."""

    def __init__(
        self,
        retrievers: Sequence[RetrieverPlugin],
        reranker: Reranker,
        *,
        rrf_k: int = 60,
        rerank_top_n: int = 50,
    ) -> None:
        self._retrievers = list(retrievers)
        self._reranker = reranker
        self._rrf_k = rrf_k
        self._rerank_top_n = rerank_top_n

    def retrieve(
        self,
        query: str,
        k: int,
        *,
        extra_queries: Sequence[str] = (),
    ) -> list[Candidate]:
        """Retrieve for ``query`` (+ optional reformulations), fuse, rerank.

        Dual-query RRF (RAG-Fusion): every (retriever x query) list feeds one
        RRF fusion, so an EU found by either phrasing surfaces — the researched
        fix for cross-lingual misses. The reranker always scores against the
        ORIGINAL query (the user's true intent), never a reformulation.
        """
        queries = [query, *extra_queries]
        lists = [r.retrieve(q, k) for q in queries for r in self._retrievers]
        fused = rrf_fuse(lists, k=self._rrf_k)

        head = fused[: self._rerank_top_n]
        tail = fused[self._rerank_top_n :]
        reranked = list(self._reranker.rerank(query, head))

        return (reranked + tail)[:k]
