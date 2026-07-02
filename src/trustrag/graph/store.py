"""Deterministic graph artifacts over indexed Evidence Units.

This is the v0.2 graph substrate: a rebuildable JSON cache under the graph layer.
It is intentionally model-free. Later entity extraction plugins can replace the
node/edge builder while keeping the storage and retriever contract stable.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from trustrag.answer.verify import content_tokens
from trustrag.domain.partition import PartitionPath
from trustrag.storage.backend import StorageBackend
from trustrag.storage.paths import Layer, layer_prefix
from trustrag.storage.protocols import VectorStore

_GRAPH_FILE = "graph.json"
_MIN_TOKEN_LEN = 4


class GraphNode(BaseModel):
    """One canonical graph node and the EUs mentioning it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str
    label: str
    eu_refs: tuple[str, ...]


class GraphEdge(BaseModel):
    """A co-mention edge between graph nodes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    weight: int


class GraphIndex(BaseModel):
    """The graph artifact for one leaf partition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]


class GraphStore:
    """Persist and load a partition graph artifact."""

    def __init__(self, backend: StorageBackend, partition: PartitionPath) -> None:
        self._backend = backend
        self._partition = partition

    @property
    def key(self) -> str:
        return f"{layer_prefix(Layer.graph, self._partition)}/{_GRAPH_FILE}"

    def build_from_store(self, store: VectorStore) -> GraphIndex:
        rows = store.scan()
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
            GraphNode(
                node_id=_node_id(label),
                label=label,
                eu_refs=tuple(sorted(eu_refs)),
            )
            for label, eu_refs in sorted(mentions.items())
        )
        edges = tuple(
            GraphEdge(source=_node_id(left), target=_node_id(right), weight=weight)
            for (left, right), weight in sorted(co_mentions.items())
            if weight > 0
        )
        index = GraphIndex(nodes=nodes, edges=edges)
        self.save(index)
        return index

    def save(self, index: GraphIndex) -> None:
        self._backend.put_json(self.key, index.model_dump(mode="json"))

    def load(self) -> GraphIndex | None:
        if not self._backend.exists(self.key):
            return None
        return GraphIndex.model_validate(self._backend.get_json(self.key))


def _graph_tokens(text: str) -> set[str]:
    return {token for token in content_tokens(text) if len(token) >= _MIN_TOKEN_LEN}


def _node_id(label: str) -> str:
    return f"node:{label}"
