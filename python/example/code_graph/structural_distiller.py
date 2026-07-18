"""StructuralDistiller — a structural (call-graph) GraphDistiller, injected NOT core.

This is the folded, production-shaped form of the 2026-07-17 spike
(`spikes/structural-distiller/`): the code **extractor** (symbol EUs) lives in the
Rust core, but the **edge producer** — which includes guessed `calls` edges —
stays an *injected* plugin shipped as example code, consistent with "the
code-graph product is out" ([[citenexus-code-graph-direction]]).

It consumes a structural export (`nodes` + `edges`, the shape a tool like
`ctx-optimize export --format json` emits), grounds each node against the corpus'
real symbol Evidence Units (dropping any node that does not ground, exactly like
`LLMGraphDistiller`), and records each edge's provenance on
`GraphEdge.confidence`:

- `extracted` — deterministic from the parse (`contains` / `imports`);
- `inferred`  — name-resolved, MAY BE WRONG (a `calls` edge);
- `ambiguous` — multiple plausible resolutions.

Honesty note (navigate-not-cite protects CONTENT, not TOPOLOGY): a wrong
`inferred` edge is NOT silently swallowed — it is carried with
`confidence=inferred` so a downstream answer path can down-weight / attribute /
abstain. This distiller does not itself make `confidence` load-bearing in the
answer (that is a separate follow-on); it only guarantees the signal is present.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from citenexus.graph.store import EdgeConfidence, GraphEdge, GraphIndex, GraphNode

GraphInput = Mapping[str, Sequence[tuple[str, str]]]

_CONFIDENCE = {
    "extracted": EdgeConfidence.extracted,
    "inferred": EdgeConfidence.inferred,
    "ambiguous": EdgeConfidence.ambiguous,
}


class StructuralDistiller:
    """GraphDistiller over a structural export: deterministic, model-free."""

    plugin_version = "structural-distiller/1"

    def __init__(self, export: Mapping[str, object]) -> None:
        self._nodes = list(export.get("nodes", []))  # type: ignore[arg-type]
        self._edges = list(export.get("edges", []))  # type: ignore[arg-type]

    def distill(self, graph_input: GraphInput) -> GraphIndex | None:
        stats: Counter[str] = Counter()

        def ground(node: Mapping[str, str]) -> tuple[str, ...]:
            units = graph_input.get(node["source"], ())
            anchor = node.get("decl") or node["label"]
            return tuple(eu_id for eu_id, text in units if anchor and anchor in text)

        nodes: list[GraphNode] = []
        kept: dict[str, str] = {}  # export id -> node_id
        for raw in self._nodes:
            node = dict(raw)
            refs = ground(node)
            if not refs:
                stats["node_dropped_ungrounded"] += 1
                continue
            node_id = f"node:{node['id']}"
            kept[str(node["id"])] = node_id
            nodes.append(GraphNode(node_id=node_id, label=str(node["label"]), eu_refs=refs))
            stats["node_grounded"] += 1

        edges: list[GraphEdge] = []
        for raw in self._edges:
            edge = dict(raw)
            source = kept.get(str(edge["source"]))
            target = kept.get(str(edge["target"]))
            if source is None or target is None:
                stats["edge_dropped_ungrounded_end"] += 1
                continue
            confidence = _CONFIDENCE.get(str(edge.get("confidence", "")))
            edges.append(
                GraphEdge(
                    source=source,
                    target=target,
                    weight=int(edge.get("weight", 1)),
                    relation=str(edge["relation"]) if edge.get("relation") else None,
                    confidence=confidence,
                )
            )
            stats[f"edge_{confidence.value if confidence else 'plain'}"] += 1

        self.last_stats = dict(stats)
        return GraphIndex(
            nodes=tuple(sorted(nodes, key=lambda n: n.node_id)),
            edges=tuple(edges),
        )
