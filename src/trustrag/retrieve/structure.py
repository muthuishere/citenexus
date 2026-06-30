"""The document-structure retrieval signal (spec §10, §7b).

``StructureRetriever`` reads the persisted structure indexes for a partition
(``knowledge/<P>/structure/<doc>.json``), matches tokenized query terms against
each node's ``label``, and returns the Evidence Units anchored under matching
nodes — the matched node plus its descendants, resolved by ``eu_ref`` against the
leaf rows. Structure is best-effort and optional: when no structure index exists
(the signal was never ingested, or every document degraded to zero nodes), the
retriever returns ``[]`` — a normal outcome, never an error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from trustrag.evidence.structure import StructureIndex, StructureNode
from trustrag.plugins.base import RetrieverPlugin
from trustrag.retrieve.types import Candidate, RetrievalSignal
from trustrag.storage.paths import Layer, layer_prefix
from trustrag.testing.fakes import tokenize

if TYPE_CHECKING:
    from trustrag.domain.partition import PartitionPath
    from trustrag.storage.backend import StorageBackend
    from trustrag.storage.lance_store import LeafVectorStore


def _page(value: object) -> int | None:
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _descendant_eu_refs(node: StructureNode, by_parent: dict[str, list[StructureNode]]) -> set[str]:
    """The ``eu_ref`` of ``node`` and every node beneath it."""
    refs = {node.eu_ref}
    for child in by_parent.get(node.node_id, []):
        refs |= _descendant_eu_refs(child, by_parent)
    return refs


class StructureRetriever(RetrieverPlugin):
    """Match query terms to structure node labels → EUs under those nodes."""

    plugin_version = "structure-retriever-v1"

    def __init__(
        self,
        backend: StorageBackend,
        partition: PartitionPath,
        store: LeafVectorStore,
    ) -> None:
        self._backend = backend
        self._partition = partition
        self._store = store

    def _load_indexes(self) -> list[StructureIndex]:
        prefix = f"{layer_prefix(Layer.knowledge, self._partition)}/structure"
        indexes: list[StructureIndex] = []
        for key in self._backend.list_prefix(prefix):
            if not key.endswith(".json"):
                continue
            indexes.append(StructureIndex.model_validate(self._backend.get_json(key)))
        return indexes

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        indexes = self._load_indexes()
        if not indexes:
            return []

        terms = set(tokenize(query))
        if not terms:
            return []

        # eu_ref → best (highest) number of matched query terms on a covering node.
        matched: dict[str, int] = {}
        for index in indexes:
            by_parent: dict[str, list[StructureNode]] = {}
            for node in index.nodes:
                if node.parent_id is not None:
                    by_parent.setdefault(node.parent_id, []).append(node)
            for node in index.nodes:
                hits = len(terms & set(tokenize(node.label)))
                if hits == 0:
                    continue
                for ref in _descendant_eu_refs(node, by_parent):
                    if matched.get(ref, 0) < hits:
                        matched[ref] = hits
        if not matched:
            return []

        rows_by_id: dict[str, dict[str, Any]] = {
            str(row["eu_id"]): row for row in self._store.scan()
        }

        candidates: list[Candidate] = []
        for ref, hits in matched.items():
            row = rows_by_id.get(ref)
            if row is None:
                continue
            candidates.append(
                Candidate(
                    eu_id=ref,
                    score=float(hits),
                    signal=RetrievalSignal.structure,
                    document_id=row.get("document_id"),
                    text=row.get("text"),
                    page=_page(row.get("page")),
                    language=row.get("language"),
                    checksum=row.get("checksum"),
                    raw_uri=row.get("raw_uri"),
                )
            )
        candidates.sort(key=lambda c: (-c.score, c.eu_id))
        return candidates[:k]
