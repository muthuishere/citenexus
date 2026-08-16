"""End-to-end structural code graph + a topology-safety guardrail.

The code extractor (Rust core) makes symbols citable EUs; an *injected*
`StructuralDistiller` (example code, NOT core) turns a structural export into a
grounded graph with honest `GraphEdge.confidence`. These tests prove:

1. "who calls X" routes through the graph to VERBATIM, cited symbol EUs, and the
   in-corpus symbols ground ~100% (the fix for the spike's 73%);
2. TOPOLOGY is not silently corrupted: a name-collision (two `Tokenize`s) with a
   wrong `inferred` edge surfaces `confidence=inferred` — the signal is present,
   not swallowed (navigate-not-cite protects CONTENT, not topology).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from citenexus import CiteNexus
from citenexus.graph.store import EdgeConfidence
from citenexus.testing import FakeEmbedding

_DISTILLER_PATH = (
    Path(__file__).resolve().parents[2] / "example" / "code_graph" / "structural_distiller.py"
)


def _load_distiller_cls() -> Any:
    spec = importlib.util.spec_from_file_location("example_structural_distiller", _DISTILLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.StructuralDistiller


def test_who_calls_resolves_to_cited_symbol_eus(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tokenize.go").write_text(
        "package repo\n\nimport \"strings\"\n\n"
        "func Tokenize(s string) []string {\n\treturn strings.Fields(s)\n}\n"
    )
    (repo / "asker.go").write_text(
        "package repo\n\nfunc Ask(q string) string {\n\treturn Tokenize(q)[0]\n}\n"
    )
    export = {
        "nodes": [
            {"id": "ask", "label": "Ask", "source": "asker.go", "decl": "func Ask"},
            {"id": "tok", "label": "Tokenize", "source": "tokenize.go", "decl": "func Tokenize"},
        ],
        "edges": [
            {"source": "ask", "target": "tok", "relation": "calls", "confidence": "inferred"}
        ],
    }
    distiller = _load_distiller_cls()(export)
    rag = CiteNexus(
        tmp_path / "store",
        embedder=FakeEmbedding(),
        signals=["embedding", "graph"],
        graph_distiller=distiller,
    )
    rag.code.ingest_from(repo)

    index = rag._graph_store.load()
    assert index is not None
    # Both in-corpus symbols grounded — no drops (the spike's 73% is gone).
    assert distiller.last_stats.get("node_dropped_ungrounded", 0) == 0
    assert distiller.last_stats["node_grounded"] == 2

    by_id = {n.node_id: n for n in index.nodes}
    tok = by_id["node:tok"]
    callers = [by_id[e.source] for e in index.edges if e.target == tok.node_id]
    assert [c.label for c in callers] == ["Ask"]

    # The caller resolves down to a VERBATIM, citable Evidence Unit.
    rows = {str(r["eu_id"]): r for r in rag._store.scan()}
    ask_text = str(rows[callers[0].eu_refs[0]]["text"])
    assert ask_text.startswith("func Ask")
    assert "Tokenize(q)" in ask_text


def test_name_collision_wrong_inferred_edge_surfaces_confidence(tmp_path: Path) -> None:
    """Two `Tokenize`s; a wrong `inferred` calls-edge must NOT be silently swallowed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.go").write_text(
        "package a\n\n"
        "func Tokenize(s string) int {\n\treturn len(s)\n}\n\n"
        "func CallerA() int {\n\treturn Tokenize(\"x\")\n}\n"
    )
    (repo / "b.go").write_text(
        "package b\n\nfunc Tokenize(s string) bool {\n\treturn s == \"\"\n}\n"
    )
    export = {
        "nodes": [
            {"id": "tok_a", "label": "Tokenize", "source": "a.go", "decl": "func Tokenize"},
            {"id": "tok_b", "label": "Tokenize", "source": "b.go", "decl": "func Tokenize"},
            {"id": "caller", "label": "CallerA", "source": "a.go", "decl": "func CallerA"},
        ],
        # WRONG: CallerA actually calls a.go's Tokenize, but name-resolution guessed
        # b.go's — carried honestly as `inferred`, not dropped.
        "edges": [
            {"source": "caller", "target": "tok_b", "relation": "calls", "confidence": "inferred"}
        ],
    }
    distiller = _load_distiller_cls()(export)
    rag = CiteNexus(
        tmp_path / "store",
        embedder=FakeEmbedding(),
        signals=["embedding", "graph"],
        graph_distiller=distiller,
    )
    rag.code.ingest_from(repo)

    index = rag._graph_store.load()
    assert index is not None
    # The collision is preserved as two distinct nodes (not merged by label).
    tokenize_nodes = [n for n in index.nodes if n.label == "Tokenize"]
    assert len(tokenize_nodes) == 2

    calls_edges = [e for e in index.edges if e.relation == "calls"]
    assert len(calls_edges) == 1
    edge = calls_edges[0]
    # The honesty guarantee: the (mis-attributed) edge carries confidence=inferred,
    # surfaced for a downstream answer path to down-weight/abstain — NOT swallowed.
    assert edge.confidence is EdgeConfidence.inferred
    assert edge.target == "node:tok_b"
