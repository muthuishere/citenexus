"""Spike: a STRUCTURAL GraphDistiller — ctx-optimize's AST graph as CiteNexus's graph.

Proves Step A of the code-adapter idea with ZERO core changes:
  1. Ingest .go files as plain text (existing ingest door, FakeEmbedding, offline).
  2. Inject a `StructuralDistiller` through the EXISTING `graph_distiller=` seam.
     It converts a ctx-optimize `export --format json` dump into a GraphIndex,
     grounding every node in real eu_refs (nodes that don't ground are DROPPED,
     same invariant as LLMGraphDistiller).
  3. Demonstrate: graph_neighbors resolves a symbol to verbatim, cited EUs, and
     "who calls X" — unanswerable over co-mention — now routes through `calls`
     edges to real evidence. Navigate-not-cite holds throughout: edges route,
     only verbatim EU text is ever quotable.

Run:  cd python && uv run python ../spikes/structural-distiller/spike.py \
          <corpus_dir> <ctx-graph.json>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from citenexus import CiteNexus
from citenexus.graph.store import GraphEdge, GraphIndex, GraphNode
from citenexus.testing import FakeEmbedding


class StructuralDistiller:
    """GraphDistiller over a ctx-optimize export: structural, deterministic, model-free.

    GAP FOUND FOR STEP B: GraphEdge has `relation` but no `confidence` field, so
    EXTRACTED vs INFERRED provenance is carried here by relation suffix ("calls?"
    for inferred) — a real change should add `confidence` to GraphEdge.
    """

    plugin_version = "structural-distiller-spike-v0"

    def __init__(self, export_path: Path, corpus_dir: Path) -> None:
        self._export = json.loads(export_path.read_text())
        self._corpus = corpus_dir

    def distill(self, graph_input) -> GraphIndex | None:
        # graph_input: {document_id: [(eu_id, text), ...]} — the real corpus EUs.
        stats = Counter()

        def ground(node: dict) -> tuple[str, ...]:
            """Map a ctx node to the EU ids whose text contains its declaration."""
            doc = node.get("source", "")
            units = graph_input.get(doc, ())
            if not units:
                return ()
            # Anchor = the symbol's first declaration line (falls back to label).
            anchor = node.get("label", "")
            loc = node.get("location") or ""
            if loc.startswith("L"):
                try:
                    first_line = int(loc[1:].split("-")[0]) - 1
                    lines = (self._corpus / doc).read_text().splitlines()
                    anchor = lines[first_line].strip() or anchor
                except (ValueError, OSError, IndexError):
                    pass
            refs = tuple(eu_id for eu_id, text in units if anchor and anchor in text)
            if not refs and node.get("label"):
                refs = tuple(eu_id for eu_id, text in units if node["label"] in text)
            return refs

        nodes: list[GraphNode] = []
        kept: dict[str, str] = {}  # ctx id -> node_id
        for n in self._export["nodes"]:
            refs = ground(n)
            if not refs:
                stats["node_dropped_ungrounded"] += 1
                continue
            node_id = f"node:{n['id']}"
            kept[n["id"]] = node_id
            nodes.append(GraphNode(node_id=node_id, label=n["label"], eu_refs=refs))
            stats["node_grounded"] += 1

        edges: list[GraphEdge] = []
        for e in self._export["edges"]:
            src, tgt = kept.get(e["source"]), kept.get(e["target"])
            if not src or not tgt:
                stats["edge_dropped_ungrounded_end"] += 1
                continue
            rel = e.get("relation", "related")
            if e.get("confidence") == "INFERRED":
                rel += "?"  # spike-only provenance marker (see class docstring)
                stats["edge_inferred_kept_navigate_only"] += 1
            else:
                stats["edge_extracted"] += 1
            edges.append(
                GraphEdge(source=src, target=tgt, weight=int(e.get("weight", 1)), relation=rel)
            )

        print(f"[distill] {dict(stats)}")
        return GraphIndex(nodes=tuple(sorted(nodes, key=lambda n: n.node_id)), edges=tuple(edges))


def main() -> None:
    corpus_dir = Path(sys.argv[1]).resolve()
    export_path = Path(sys.argv[2]).resolve()
    store = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("../spikes/structural-distiller/store")

    rag = CiteNexus(
        store,
        embedder=FakeEmbedding(),
        graph_distiller=StructuralDistiller(export_path, corpus_dir),
    )

    go_files = sorted(corpus_dir.rglob("*.go"))
    print(f"[ingest] {len(go_files)} .go files as plain text")
    for f in go_files:
        rag.ingest(text=f.read_text(), document_id=str(f.relative_to(corpus_dir)))

    tools = {t["name"]: t for t in rag.tools()}

    # --- Demo 1: a symbol resolves to verbatim, cited evidence -------------
    out = tools["graph_neighbors"]["handler"](entity="Ask")
    node = out["node"]
    print(f"\n[demo1] graph_neighbors('Ask') -> node={node['label']!r} "
          f"eu_refs={len(node['eu_refs'])} neighbors={len(out['neighbors'])}")
    for nb in out["neighbors"][:6]:
        print(f"        {nb.get('relation')}  ->  {nb['node_id']}")
    ev = tools["get_evidence"]["handler"](eu_id=node["eu_refs"][0])
    print(f"[demo1] verbatim EU (first 160 chars): {ev['text'][:160]!r}")

    # --- Demo 2: 'who calls X' — impossible over co-mention ----------------
    # Walk reverse `calls?` edges by hand over the stored graph artifact.
    index = rag._graph_store.load()  # spike-only peek at the artifact
    by_id = {n.node_id: n for n in index.nodes}
    target = next(n for n in index.nodes if n.node_id.endswith("tokenize.go::Tokenize"))
    callers = [by_id[e.source] for e in index.edges
               if e.target == target.node_id and (e.relation or "").startswith("calls")]
    print(f"\n[demo2] who calls {target.node_id}?")
    for c in callers:
        print(f"        {c.node_id}  (grounded in {len(c.eu_refs)} EUs)")

    # --- Demo 3: retrieval + full cite-or-abstain ask over the code corpus --
    hits = tools["search_evidence"]["handler"](query="cite or abstain decision refused", k=3)
    print(f"\n[demo3] search_evidence -> top hit {hits[0]['document_id']} "
          f"signal={hits[0]['signal']}")
    print("\n[ok] structural graph is live inside CiteNexus — zero core changes.")


if __name__ == "__main__":
    main()
