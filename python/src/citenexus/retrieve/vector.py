"""The dense vector retrieval signal (spec §10).

``VectorRetriever`` embeds the query with an injected embedder, asks the leaf
``LanceVectorStore`` for its nearest rows, and maps each hit to a citable
``Candidate`` carrying ``signal=vector``. LanceDB returns a ``_distance`` per hit
(smaller = more similar); we turn that into a score that *descends* as distance
grows, so the nearest EU ranks first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from citenexus.plugins.base import RetrieverPlugin
from citenexus.retrieve.types import Candidate, RetrievalSignal

if TYPE_CHECKING:
    from citenexus.storage.protocols import VectorStore


class QueryEmbedder(Protocol):
    """The single-text embedding seam (``FakeEmbedding`` satisfies it)."""

    def embed(self, text: str) -> list[float]: ...


def _score_from_distance(distance: float) -> float:
    """A strictly descending, bounded score from a non-negative distance."""
    return 1.0 / (1.0 + distance)


def _page(value: object) -> int | None:
    """Map the ingest ``page == -1`` sentinel back to ``None``."""
    if isinstance(value, int) and value >= 0:
        return value
    return None


class VectorRetriever(RetrieverPlugin):
    """Dense nearest-neighbour retrieval over one leaf vector store."""

    plugin_version = "vector-retriever-v1"

    def __init__(self, store: VectorStore, embedder: QueryEmbedder) -> None:
        self._store = store
        self._embedder = embedder

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        vector = self._embedder.embed(query)
        hits = self._store.search(vector, limit=k)
        candidates: list[Candidate] = []
        for hit in hits:
            distance = float(hit.get("_distance", 0.0))
            candidates.append(
                Candidate(
                    eu_id=str(hit["eu_id"]),
                    score=_score_from_distance(distance),
                    signal=RetrievalSignal.vector,
                    document_id=hit.get("document_id"),
                    text=hit.get("text"),
                    page=_page(hit.get("page")),
                    language=hit.get("language"),
                    checksum=hit.get("checksum"),
                    raw_uri=hit.get("raw_uri"),
                )
            )
        return candidates
