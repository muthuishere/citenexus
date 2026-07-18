"""SchemaDistiller — a structural (FK / $ref) GraphDistiller, injected NOT core.

The schema **extractor** (verbatim table / endpoint / type EUs) lives in the Rust
core, but the **edge producer** stays an *injected* plugin shipped as example code
— exactly like the code ``StructuralDistiller`` next door — because ``ExtractedDoc``
has no edge channel by design ([[citenexus-code-graph-direction]]).

It re-reads the same schema artifact (a SQL DDL string or an OpenAPI/JSON-Schema
JSON string), grounds each schema object against the corpus' real schema Evidence
Units (dropping any object that does not ground, like ``LLMGraphDistiller``), and
emits the structural relationships as edges:

- SQL foreign keys (``REFERENCES parent`` / ``FOREIGN KEY ... REFERENCES parent``);
- OpenAPI / JSON-Schema ``$ref`` type references.

Every such edge is authoritative — read directly from the schema, not guessed — so
it carries ``GraphEdge.confidence = extracted``. Every edge endpoint resolves to a
real schema EU (grounding drops dangling references), so a topology query routes to
verbatim, cited schema evidence.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

from citenexus.graph.store import EdgeConfidence, GraphEdge, GraphIndex, GraphNode

GraphInput = Mapping[str, Sequence[tuple[str, str]]]

# `CREATE TABLE [IF NOT EXISTS] <name> (` — the object anchor for a table.
_CREATE_TABLE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?([`\"\[]?[\w.]+[`\"\]]?)",
    re.IGNORECASE,
)
# Column / table FK targets: `REFERENCES <table>` (optionally schema-qualified).
_REFERENCES = re.compile(r"references\s+([`\"\[]?[\w.]+[`\"\]]?)", re.IGNORECASE)
# An OpenAPI/JSON-Schema `$ref` pointer's final path segment is the target name.
_REF = re.compile(r'"\$ref"\s*:\s*"([^"]+)"')


def _clean(name: str) -> str:
    """Bare object name: strip quoting and take the last dotted segment."""
    return name.strip("`\"[]").split(".")[-1]


class SchemaDistiller:
    """GraphDistiller over a schema artifact: deterministic, model-free, ``extracted``."""

    plugin_version = "schema-distiller/1"

    def __init__(self, source: str | bytes, *, kind: str) -> None:
        """``source`` is the DDL/OpenAPI text (or bytes); ``kind`` is ``"sql"`` or
        ``"openapi"``."""
        self._text = source.decode("utf-8", "replace") if isinstance(source, bytes) else source
        self._kind = kind

    def distill(self, graph_input: GraphInput) -> GraphIndex | None:
        return self._distill_sql(graph_input) if self._kind == "sql" else self._distill_ref(
            graph_input
        )

    # -- grounding ---------------------------------------------------------

    @staticmethod
    def _index(graph_input: GraphInput) -> list[tuple[str, str]]:
        """Flatten the corpus to ``(eu_id, text)`` in deterministic order."""
        units: list[tuple[str, str]] = []
        for _doc, doc_units in sorted(graph_input.items()):
            units.extend(doc_units)
        return units

    # -- SQL foreign keys --------------------------------------------------

    def _distill_sql(self, graph_input: GraphInput) -> GraphIndex | None:
        units = self._index(graph_input)
        stats: Counter[str] = Counter()
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        # Ground each object to the EU that OWNS it (its `CREATE TABLE <name>`),
        # never merely one that mentions the name (e.g. a REFERENCES clause).
        owners: dict[str, str] = {}
        for eu_id, text in units:
            match = _CREATE_TABLE.search(text)
            if match is not None:
                owners.setdefault(_clean(match.group(1)), eu_id)

        def node_for(name: str) -> str | None:
            node_id = f"node:table:{name}"
            if node_id in nodes:
                return node_id
            eu_id = owners.get(name)
            if eu_id is None:
                stats["node_dropped_ungrounded"] += 1
                return None
            nodes[node_id] = GraphNode(node_id=node_id, label=name, eu_refs=(eu_id,))
            stats["node_grounded"] += 1
            return node_id

        # One statement per table span in the extractor's EU text.
        for _eu_id, text in units:
            match = _CREATE_TABLE.search(text)
            if match is None:
                continue
            table = _clean(match.group(1))
            source = node_for(table)
            if source is None:
                continue
            for ref in _REFERENCES.finditer(text):
                target_name = _clean(ref.group(1))
                target = node_for(target_name)
                if target is None:
                    stats["edge_dropped_ungrounded_end"] += 1
                    continue
                edges.append(
                    GraphEdge(
                        source=source,
                        target=target,
                        weight=1,
                        relation="references",
                        confidence=EdgeConfidence.extracted,
                    )
                )
                stats["edge_extracted"] += 1

        self.last_stats = dict(stats)
        return GraphIndex(
            nodes=tuple(sorted(nodes.values(), key=lambda n: n.node_id)),
            edges=tuple(edges),
        )

    # -- OpenAPI / JSON-Schema $ref ---------------------------------------

    def _distill_ref(self, graph_input: GraphInput) -> GraphIndex | None:
        units = self._index(graph_input)
        stats: Counter[str] = Counter()
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        # Ground each type to the EU it OWNS (whose leading `"Name":` key it is),
        # never merely one whose `$ref` points at the name.
        owners: dict[str, str] = {}
        for eu_id, text in units:
            owner = self._owner_name(text)
            if owner is not None:
                owners.setdefault(owner, eu_id)

        def node_for(name: str) -> str | None:
            node_id = f"node:type:{name}"
            if node_id in nodes:
                return node_id
            eu_id = owners.get(name)
            if eu_id is None:
                stats["node_dropped_ungrounded"] += 1
                return None
            nodes[node_id] = GraphNode(node_id=node_id, label=name, eu_refs=(eu_id,))
            stats["node_grounded"] += 1
            return node_id

        # Each EU is one verbatim `"Name": { ... }` object; its owning name is the
        # object's leading key (the extractor's structure anchor).
        for _eu_id, text in units:
            owner = self._owner_name(text)
            if owner is None:
                continue
            source = node_for(owner)
            if source is None:
                continue
            for ref in _REF.finditer(text):
                target_name = ref.group(1).rstrip("/").split("/")[-1]
                target = node_for(target_name)
                if target is None:
                    stats["edge_dropped_ungrounded_end"] += 1
                    continue
                edges.append(
                    GraphEdge(
                        source=source,
                        target=target,
                        weight=1,
                        relation="ref",
                        confidence=EdgeConfidence.extracted,
                    )
                )
                stats["edge_extracted"] += 1

        self.last_stats = dict(stats)
        return GraphIndex(
            nodes=tuple(sorted(nodes.values(), key=lambda n: n.node_id)),
            edges=tuple(edges),
        )

    @staticmethod
    def _owner_name(text: str) -> str | None:
        """The leading ``"Name":`` key of a verbatim schema-object EU."""
        match = re.match(r'\s*"([^"]+)"\s*:', text)
        return match.group(1) if match else None
