"""The dense vector retrieval signal (spec §10).

``VectorRetriever`` embeds the query with an injected embedder, asks the leaf
``LanceVectorStore`` for its nearest rows, and maps each hit to a citable
``Candidate`` carrying ``signal=vector``. LanceDB returns a ``_distance`` per hit
(smaller = more similar); we turn that into a score that *descends* as distance
grows, so the nearest EU ranks first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from citenexus.contracts import EmbeddingProvider, SingleTextEmbedder, embed_one
from citenexus.plugins.base import RetrieverPlugin
from citenexus.retrieve.types import Candidate, RetrievalSignal

if TYPE_CHECKING:
    from citenexus.storage.protocols import VectorStore


#: The embedding seam the vector retriever accepts. ONE definition, published in
#: `citenexus.contracts` (ADR-0014): a batch `EmbeddingProvider` is preferred and
#: the query is sent as a batch of one; `SingleTextEmbedder` — the deprecated
#: shape ``FakeEmbedding`` uses — still works.
QueryEmbedder = SingleTextEmbedder


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

    def __init__(
        self, store: VectorStore, embedder: EmbeddingProvider | SingleTextEmbedder
    ) -> None:
        self._store = store
        self._embedder = embedder

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        # A single text is a batch of one — the contract has no second method.
        vector = embed_one(self._embedder, query)
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
                    passage=hit.get("passage"),
                    page=_page(hit.get("page")),
                    language=hit.get("language"),
                    checksum=hit.get("checksum"),
                    raw_uri=hit.get("raw_uri"),
                    authority_meta=str(hit.get("authority_meta") or ""),
                )
            )
        return candidates
