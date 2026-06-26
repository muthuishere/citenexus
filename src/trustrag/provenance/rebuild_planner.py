"""Partial-rebuild planner — the §4c rebuild matrix as a pure function.

Given the *current* plugin/model set (:class:`ModelManifest`) and an artifact's
stamp (:class:`ProducedBy`), return the set of layers that have gone stale and
must be rebuilt, honouring the dependency DAG

    extract → OCR/vision → EU/chunk → {embedding, structure, graph} → community/summary

No I/O and no actual rebuilding: the worker (L2) and ingest/graph layers (L3+)
consume this stale set to decide what to recompute. The matrix rows in the spec
are exactly the downstream closures computed here:

- embedding swap  → seeds the leaf ``embedding`` (no downstream)            ⇒ {embedding}
- vision swap     → seeds ``vision``, closes vision → eu_chunk → …          ⇒ vision + dependents
- chunker swap    → seeds ``eu_chunk``, closes to everything downstream     ⇒ EUs + downstream
- graph swap      → seeds ``graph``, closes graph → community_summary       ⇒ {graph, comm.}
- reranker/LLM    → query-time only, seed no layer                          ⇒ ∅
- identical set   → no changed stage                                        ⇒ ∅
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from trustrag.provenance.stamp import ModelManifest, ProducedBy


class Layer(StrEnum):
    """A rebuildable artifact layer (the nodes of the dependency DAG)."""

    extract = "extract"
    ocr = "ocr"
    vision = "vision"
    eu_chunk = "eu_chunk"
    embedding = "embedding"
    structure = "structure"
    graph = "graph"
    community_summary = "community_summary"


# Dependency DAG: upstream layer → its *direct* downstream layers (§4c).
_ADJACENCY: dict[Layer, frozenset[Layer]] = {
    Layer.extract: frozenset({Layer.ocr, Layer.vision}),
    Layer.ocr: frozenset({Layer.eu_chunk}),
    Layer.vision: frozenset({Layer.eu_chunk}),
    Layer.eu_chunk: frozenset({Layer.embedding, Layer.structure, Layer.graph}),
    Layer.graph: frozenset({Layer.community_summary}),
    Layer.embedding: frozenset(),
    Layer.structure: frozenset(),
    Layer.community_summary: frozenset(),
}


def _downstream_closure(seeds: set[Layer]) -> set[Layer]:
    """Every seed plus all layers reachable downstream of it in the DAG."""
    result: set[Layer] = set()
    stack: list[Layer] = list(seeds)
    while stack:
        layer = stack.pop()
        if layer in result:
            continue
        result.add(layer)
        stack.extend(_ADJACENCY[layer])
    return result


def _changed_stages(current: ModelManifest, stamp: ProducedBy) -> set[Layer]:
    """Seed layers for each stage whose plugin/model differs from the stamp.

    Each artifact-producing stage seeds the one layer it directly produces.
    ``reranker``/``llm`` are query-time only — they produce no stored artifact,
    so they are deliberately not compared and seed no layer.
    """
    seeds: set[Layer] = set()
    if current.extractor != stamp.extractor:
        seeds.add(Layer.extract)
    if current.chunker != stamp.chunker:
        seeds.add(Layer.eu_chunk)
    if current.vision != stamp.vision:
        seeds.add(Layer.vision)
    if current.embedding != stamp.embedding:
        seeds.add(Layer.embedding)
    if current.graph_extractor != stamp.graph_extractor:
        seeds.add(Layer.graph)
    return seeds


def plan(current: ModelManifest, stamp: ProducedBy) -> set[Layer]:
    """Layers to rebuild for one artifact: diff → seed → downstream closure.

    Returns an empty set when ``current`` matches ``stamp`` on every
    artifact-producing stage (idempotent — no rebuild).
    """
    return _downstream_closure(_changed_stages(current, stamp))


def plan_all(current: ModelManifest, stamps: Iterable[ProducedBy]) -> set[Layer]:
    """Layers to rebuild across a set of artifacts — the union of each plan."""
    stale: set[Layer] = set()
    for stamp in stamps:
        stale |= plan(current, stamp)
    return stale
