"""LLM graph distillation — real entities + typed relations (§10).

The deterministic graph is token co-mention: honest, model-free, coarse. The
distiller upgrades it the same way the wiki distiller upgrades pages: a SMALL
model reads the corpus's Evidence Units and extracts named ENTITIES (each
grounded in real ``eu_refs``) and typed RELATIONS between them.

GROUNDING INVARIANT: ``eu_refs`` returned by the model are sanitized against
the actual corpus; an entity whose grounding does not survive is dropped, and
relations touching dropped entities go with it. The graph can route retrieval,
but it can never invent evidence — every hit still resolves down to bbox-cited
EUs and the faithfulness gate still runs.

Distillation is an enhancement, never a hard dependency: any transport failure,
malformed reply, or empty entity set returns ``None`` and the store degrades to
its deterministic co-mention graph.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from citenexus.graph.store import GraphEdge, GraphIndex, GraphNode
from citenexus.http import DEFAULT_TRANSPORT, Transport

# The distiller input: document_id -> ordered (eu_id, text) pairs.
GraphInput = Mapping[str, Sequence[tuple[str, str]]]


@runtime_checkable
class GraphDistiller(Protocol):
    """The graph-distillation seam — structural, so test fakes satisfy it too."""

    def distill(self, graph_input: GraphInput) -> GraphIndex | None: ...


_PROMPT = (
    "You are building a knowledge graph over a document corpus. Below are the "
    "documents, each listing its Evidence Units as `eu_id: text`.\n"
    "Extract:\n"
    "- entities: named people/organizations/concepts/clauses, each with the "
    "eu_refs (ONLY Evidence Unit ids that appear below) where it is mentioned;\n"
    "- relations: typed edges between those entities (a short snake_case "
    "relation name and an integer weight for how strongly the corpus supports it).\n"
    "Reply with ONLY this JSON, nothing else:\n"
    '{{"entities": [{{"label": "...", "eu_refs": ["..."]}}], '
    '"relations": [{{"source": "...", "target": "...", "relation": "...", '
    '"weight": 1}}]}}\n\n'
    "{corpus}"
)
# Caps keep the small-model call cheap on a large corpus.
_MAX_EU_CHARS = 500
_MAX_CORPUS_CHARS = 24_000


class LLMGraphDistiller:
    """Distill corpus EUs into grounded entities + typed relations."""

    plugin_version = "llm-graph-distiller-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: Transport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._transport: Transport = transport or DEFAULT_TRANSPORT

    def _headers(self) -> dict[str, str]:
        # Auth + provider headers are the ENDPOINT layer's job (HttpEndpoint
        # transport); wire clients only speak JSON.
        return {"Content-Type": "application/json"}

    def distill(self, graph_input: GraphInput) -> GraphIndex | None:
        """A grounded, typed graph for the corpus — or ``None`` on any failure."""
        if not graph_input:
            return None
        prompt = _PROMPT.format(corpus=_corpus_block(graph_input))
        request = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }
        body = json.dumps(request).encode("utf-8")
        try:
            raw = self._transport(f"{self._base_url}/chat/completions", body, self._headers())
            content = json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            return None
        known_eus = {eu_id for units in graph_input.values() for eu_id, _text in units}
        return _parse_graph(str(content), known_eus)


def _corpus_block(graph_input: GraphInput) -> str:
    lines: list[str] = []
    total = 0
    for document_id in sorted(graph_input):
        lines.append(f"# Document: {document_id}")
        for eu_id, text in graph_input[document_id]:
            line = f"{eu_id}: {text[:_MAX_EU_CHARS]}"
            total += len(line)
            if total > _MAX_CORPUS_CHARS:
                lines.append("(corpus truncated)")
                return "\n".join(lines)
            lines.append(line)
    return "\n".join(lines)


def _node_id(label: str) -> str:
    return f"node:{label.strip().lower()}"


def _parse_graph(content: str, known_eus: set[str]) -> GraphIndex | None:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    nodes: list[GraphNode] = []
    labels: set[str] = set()
    for item in payload.get("entities", []):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        # GROUNDING: keep only eu_refs that exist; drop ungrounded entities.
        eu_refs = tuple(sorted({str(r) for r in item.get("eu_refs", []) if str(r) in known_eus}))
        if not label or not eu_refs:
            continue
        nodes.append(GraphNode(node_id=_node_id(label), label=label, eu_refs=eu_refs))
        labels.add(label)
    if not nodes:
        return None

    edges: list[GraphEdge] = []
    for item in payload.get("relations", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if source not in labels or target not in labels:
            continue  # a relation touching a dropped entity goes with it
        try:
            weight = int(item.get("weight", 1))
        except (TypeError, ValueError):
            weight = 1
        relation = str(item.get("relation", "")).strip() or None
        edges.append(
            GraphEdge(
                source=_node_id(source),
                target=_node_id(target),
                weight=max(weight, 1),
                relation=relation,
            )
        )
    return GraphIndex(nodes=tuple(sorted(nodes, key=lambda n: n.node_id)), edges=tuple(edges))
