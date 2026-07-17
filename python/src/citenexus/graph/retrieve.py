"""Graph retrieval signal resolved down to citable Evidence Units."""

from __future__ import annotations

from typing import Any

from citenexus.answer.verify import content_tokens
from citenexus.graph.store import GraphStore
from citenexus.plugins.base import RetrieverPlugin
from citenexus.retrieve.types import Candidate, RetrievalSignal
from citenexus.storage.protocols import VectorStore


def _page(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


class GraphRetriever(RetrieverPlugin):
    """Match query terms to graph nodes and return their underlying EUs."""

    plugin_version = "graph-retriever-v1"

    def __init__(self, graph_store: GraphStore, leaf_store: VectorStore) -> None:
        self._graph_store = graph_store
        self._leaf_store = leaf_store

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        # Deferred rebuild: a single ingest only marks the graph dirty, so the read
        # path rebuilds lazily here before loading — the ask() always sees a graph
        # consistent with all committed ingests.
        self._graph_store.ensure_current(self._leaf_store)
        index = self._graph_store.load()
        if index is None:
            return []
        terms = content_tokens(query)
        if not terms:
            return []

        eu_scores: dict[str, float] = {}
        for node in index.nodes:
            if node.label not in terms:
                continue
            for eu_ref in node.eu_refs:
                eu_scores[eu_ref] = eu_scores.get(eu_ref, 0.0) + 1.0
        if not eu_scores:
            return []

        rows_by_id: dict[str, dict[str, Any]] = {
            str(row["eu_id"]): row for row in self._leaf_store.scan()
        }
        candidates: list[Candidate] = []
        for eu_id, score in sorted(eu_scores.items(), key=lambda item: (-item[1], item[0])):
            row = rows_by_id.get(eu_id)
            if row is None:
                continue
            candidates.append(
                Candidate(
                    eu_id=eu_id,
                    score=score,
                    signal=RetrievalSignal.graph,
                    document_id=row.get("document_id"),
                    text=row.get("text"),
                    page=_page(row.get("page")),
                    language=row.get("language"),
                    checksum=row.get("checksum"),
                    raw_uri=row.get("raw_uri"),
                )
            )
        return candidates[:k]
