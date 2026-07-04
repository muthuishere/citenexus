"""rag.tools() — agentic navigation as framework-neutral tool calls.

Karpathy's query loop is agentic: read the index, open pages, follow links,
then read the evidence. These tools let ANY tool-calling LLM do that loop over
a CiteNexus store — each tool is a plain {name, description, parameters,
handler} dict (exactly what toolnexus's define_tool / any OpenAI loop consumes).

NAVIGATE-NOT-CITE HOLDS: wiki/graph tools return navigation data; the only
tool that returns quotable text is evidence(eu_id)/search(), and that text is
the VERBATIM stored EU with provenance — never model-written wiki prose.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from citenexus import CiteNexus
from citenexus.testing import FakeEmbedding

_NDA = "Acme employees shall not disclose confidential information."
_HR = "Acme leave accrues monthly for employees."


def _rag(tmp_path: Path) -> CiteNexus:
    rag = CiteNexus(tmp_path, embedder=FakeEmbedding())
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_HR, document_id="hr")
    return rag


def _by_name(rag: CiteNexus) -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in rag.tools()}


def test_tools_are_named_described_schemad_callables(tmp_path: Path) -> None:
    tools = _rag(tmp_path).tools()
    assert {t["name"] for t in tools} == {
        "search_evidence",
        "wiki_index",
        "wiki_page",
        "graph_neighbors",
        "get_evidence",
    }
    for tool in tools:
        assert tool["description"]
        assert tool["parameters"]["type"] == "object"  # JSON-schema shaped
        assert callable(tool["handler"])
        json.dumps(tool["parameters"])  # schema must be pure JSON


def test_wiki_navigation_loop(tmp_path: Path) -> None:
    tools = _by_name(_rag(tmp_path))
    index = tools["wiki_index"]["handler"]()
    assert {e["page_id"] for e in index} == {"wiki:nda", "wiki:hr"}
    assert all("eu_refs" not in e for e in index)  # index stays light

    page = tools["wiki_page"]["handler"](page_id="wiki:nda")
    assert page is not None and page["eu_refs"]

    evidence = tools["get_evidence"]["handler"](eu_id=page["eu_refs"][0])
    assert evidence is not None
    assert evidence["text"] == _NDA  # VERBATIM stored text, never wiki prose
    assert evidence["checksum"]


def test_search_returns_cited_rows(tmp_path: Path) -> None:
    tools = _by_name(_rag(tmp_path))
    hits = tools["search_evidence"]["handler"](query="disclose confidential", k=3)
    assert hits and hits[0]["document_id"] == "nda"
    assert hits[0]["eu_id"] and "signal" in hits[0]


def test_graph_neighbors(tmp_path: Path) -> None:
    tools = _by_name(_rag(tmp_path))
    out = tools["graph_neighbors"]["handler"](entity="employees")
    assert out["node"] is not None
    assert out["node"]["eu_refs"]  # grounded — resolvable to evidence
    assert isinstance(out["neighbors"], list)


def test_unknown_ids_return_none_not_errors(tmp_path: Path) -> None:
    tools = _by_name(_rag(tmp_path))
    assert tools["wiki_page"]["handler"](page_id="wiki:nope") is None
    assert tools["get_evidence"]["handler"](eu_id="nope::0") is None
    assert tools["graph_neighbors"]["handler"](entity="zzz")["node"] is None
