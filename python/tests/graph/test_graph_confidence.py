"""GraphEdge.confidence — provenance of a graph edge (structural-code-graph).

extracted (deterministic parse) | inferred (name-resolved, may be wrong) |
ambiguous (multiple resolutions). Optional, defaults absent/None so old graph.json
keeps loading; the serialized form omits the key when None (never `null`) so the
artifact is byte-stable across the Go/JS ports.
"""

from __future__ import annotations

from citenexus.graph.store import (
    EdgeConfidence,
    GraphEdge,
    GraphIndex,
    GraphNode,
    build_comention_graph,
)


def test_edge_confidence_enum_values() -> None:
    assert EdgeConfidence.extracted == "extracted"
    assert EdgeConfidence.inferred == "inferred"
    assert EdgeConfidence.ambiguous == "ambiguous"


def test_edge_confidence_defaults_to_none() -> None:
    edge = GraphEdge(source="node:a", target="node:b", weight=1)
    assert edge.confidence is None


def test_edge_carries_confidence() -> None:
    edge = GraphEdge(
        source="node:a", target="node:b", weight=1, confidence=EdgeConfidence.inferred
    )
    assert edge.confidence is EdgeConfidence.inferred


def test_comention_edges_have_no_confidence() -> None:
    rows = [{"eu_id": "e1", "text": "alpha bravo charlie"}]
    index = build_comention_graph(rows)
    assert index.edges  # sanity: some co-mention edges exist
    assert all(edge.confidence is None for edge in index.edges)


def test_unset_confidence_serializes_as_null_like_relation() -> None:
    # Cross-port contract: an unset nullable field is `null` (Go `*string` w/o
    # omitempty, JS `| null`), matching the existing `relation` convention.
    edge = GraphEdge(source="node:a", target="node:b", weight=1)
    index = GraphIndex(nodes=(), edges=(edge,))
    dumped = index.model_dump(mode="json")
    assert dumped["edges"][0]["confidence"] is None
    assert dumped["edges"][0]["relation"] is None


def test_set_confidence_round_trips_through_json() -> None:
    edge = GraphEdge(
        source="node:a", target="node:b", weight=2, confidence=EdgeConfidence.extracted
    )
    node = GraphNode(node_id="node:a", label="a", eu_refs=("e1",))
    index = GraphIndex(nodes=(node,), edges=(edge,))
    restored = GraphIndex.model_validate(index.model_dump(mode="json"))
    assert restored.edges[0].confidence is EdgeConfidence.extracted


def test_old_graph_json_without_confidence_loads() -> None:
    # An artifact written before this change has no `confidence` key at all.
    payload = {
        "nodes": [{"node_id": "node:a", "label": "a", "eu_refs": ["e1"]}],
        "edges": [{"source": "node:a", "target": "node:b", "weight": 1}],
    }
    index = GraphIndex.model_validate(payload)
    assert index.edges[0].confidence is None
