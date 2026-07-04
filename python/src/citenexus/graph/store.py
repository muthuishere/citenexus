"""Deterministic graph artifacts over indexed Evidence Units.

This is the v0.2 graph substrate: a rebuildable JSON cache under the graph layer.
It is intentionally model-free. Later entity extraction plugins can replace the
node/edge builder while keeping the storage and retriever contract stable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from citenexus.answer.verify import content_tokens
from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import StorageBackend
from citenexus.storage.paths import Layer, layer_prefix

if True:  # TYPE_CHECKING-safe forward ref for the distiller protocol
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from citenexus.graph.distill import GraphDistiller
from citenexus.storage.protocols import VectorStore

_GRAPH_FILE = "graph.json"
_MIN_TOKEN_LEN = 4


class GraphNode(BaseModel):
    """One canonical graph node and the EUs mentioning it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str
    label: str
    eu_refs: tuple[str, ...]


class GraphEdge(BaseModel):
    """An edge between graph nodes — co-mention, or LLM-typed when distilled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    weight: int
    # The typed relation an LLM distiller extracted ("bound_by", "owns", ...).
    # None for deterministic co-mention edges; default keeps old graph.json loading.
    relation: str | None = None


class GraphIndex(BaseModel):
    """The graph artifact for one leaf partition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


class GraphStore:
    """Persist and load a partition graph artifact."""

    def __init__(
        self,
        backend: StorageBackend,
        partition: PartitionPath,
        *,
        distiller: GraphDistiller | None = None,
    ) -> None:
        self._backend = backend
        self._partition = partition
        self._distiller = distiller

    @property
    def key(self) -> str:
        return f"{layer_prefix(Layer.graph, self._partition)}/{_GRAPH_FILE}"

    def build_from_store(self, store: VectorStore) -> GraphIndex:
        rows = store.scan()
        # LLM distillation first (when injected) — enhancement-only; None
        # degrades to the deterministic co-mention graph below.
        if self._distiller is not None:
            by_doc: dict[str, list[tuple[str, str]]] = {}
            for row in rows:
                doc = str(row.get("document_id", row["eu_id"]))
                by_doc.setdefault(doc, []).append((str(row["eu_id"]), str(row.get("text", ""))))
            distilled = self._distiller.distill({d: tuple(u) for d, u in sorted(by_doc.items())})
            if distilled is not None:
                self.save(distilled)
                return distilled
        index = build_comention_graph(rows)
        self.save(index)
        return index

    def save(self, index: GraphIndex) -> None:
        self._backend.put_json(self.key, index.model_dump(mode="json"))

    def load(self) -> GraphIndex | None:
        if not self._backend.exists(self.key):
            return None
        return GraphIndex.model_validate(self._backend.get_json(self.key))


def build_comention_graph(rows: Iterable[Mapping[str, Any]]) -> GraphIndex:
    """The deterministic, model-free co-mention graph over EU rows (§10b).

    Pure function (no storage): each row is ``{eu_id, text}``. A node is a content
    token of length ≥ 4; an edge is a within-EU co-mention, weighted by count.
    Nodes sort by label, edges by (source-label, target-label) — so the artifact
    is byte-stable across languages. This is the arbiter for the Go/TS ports.
    """
    mentions: dict[str, set[str]] = {}
    co_mentions: Counter[tuple[str, str]] = Counter()
    for row in rows:
        eu_id = str(row["eu_id"])
        tokens = sorted(_graph_tokens(str(row.get("text", ""))))
        for token in tokens:
            mentions.setdefault(token, set()).add(eu_id)
        for left_idx, left in enumerate(tokens):
            for right in tokens[left_idx + 1 :]:
                co_mentions[(left, right)] += 1
    nodes = tuple(
        GraphNode(node_id=_node_id(label), label=label, eu_refs=tuple(sorted(eu_refs)))
        for label, eu_refs in sorted(mentions.items())
    )
    edges = tuple(
        GraphEdge(source=_node_id(left), target=_node_id(right), weight=weight)
        for (left, right), weight in sorted(co_mentions.items())
        if weight > 0
    )
    return GraphIndex(nodes=nodes, edges=edges)


def _graph_tokens(text: str) -> set[str]:
    return {token for token in content_tokens(text) if len(token) >= _MIN_TOKEN_LEN}


def _node_id(label: str) -> str:
    return f"node:{label}"
