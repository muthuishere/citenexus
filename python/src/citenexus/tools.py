"""Agentic navigation tools — the corpus as tool calls (§10b, toolnexus-style).

Karpathy's query loop is agentic: read the index, open pages, follow links,
then read the evidence. ``CiteNexus.tools()`` exposes that loop to ANY
tool-calling LLM as framework-neutral specs — each a plain dict of
``{name, description, parameters (JSON schema), handler (callable)}``, which is
exactly what toolnexus's ``define_tool`` (or any OpenAI-style tool loop)
consumes.

NAVIGATE-NOT-CITE HOLDS ACROSS THE TOOLS: ``wiki_index``/``wiki_page``/
``graph_neighbors`` return navigation data (summaries, links, refs); the only
quotable text comes from ``search_evidence``/``get_evidence``, and that text is
the VERBATIM stored Evidence Unit with its provenance — never model-written
wiki prose. An agent can wander the wiki freely and still can't cite it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from citenexus.client import CiteNexus

ToolSpec = dict[str, Any]


def build_tools(rag: CiteNexus) -> list[ToolSpec]:
    """The navigation toolset over one client's partition."""

    def search_evidence(query: str, k: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "eu_id": c.eu_id,
                "text": c.text,
                "document_id": c.document_id,
                "page": c.page,
                "language": c.language,
                "checksum": c.checksum,
                "signal": c.signal.value,
                "score": c.score,
            }
            for c in rag.retrieve(query, k=k)
        ]

    def wiki_index() -> list[dict[str, Any]]:
        return rag._wiki_store.load_index()

    def wiki_page(page_id: str) -> dict[str, Any] | None:
        page = rag._wiki_store.load_page(page_id)
        return page.model_dump(mode="json") if page is not None else None

    def get_evidence(eu_id: str) -> dict[str, Any] | None:
        for row in rag._store.scan():
            if str(row.get("eu_id")) == eu_id:
                return {
                    "eu_id": eu_id,
                    "text": row.get("text"),
                    "document_id": row.get("document_id"),
                    "page": row.get("page"),
                    "language": row.get("language"),
                    "checksum": row.get("checksum"),
                    "raw_uri": row.get("raw_uri"),
                }
        return None

    def graph_neighbors(entity: str) -> dict[str, Any]:
        index = rag._graph_store.load()
        if index is None:
            return {"node": None, "neighbors": []}
        needle = entity.strip().lower()
        node = next((n for n in index.nodes if needle in n.label.lower()), None)
        if node is None:
            return {"node": None, "neighbors": []}
        neighbors = [
            {
                "node_id": e.target if e.source == node.node_id else e.source,
                "relation": e.relation,
                "weight": e.weight,
            }
            for e in index.edges
            if node.node_id in (e.source, e.target)
        ]
        return {"node": node.model_dump(mode="json"), "neighbors": neighbors}

    return [
        {
            "name": "search_evidence",
            "description": (
                "Hybrid search over the corpus (vector+BM25+structure+graph+wiki, "
                "RRF-fused). Returns VERBATIM evidence rows with provenance — the "
                "only quotable text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            "handler": search_evidence,
        },
        {
            "name": "wiki_index",
            "description": (
                "The wiki's light index: every page's id, title, summary, keywords "
                "and [[links]]. Navigation only — never cite wiki text."
            ),
            "parameters": {"type": "object", "properties": {}},
            "handler": wiki_index,
        },
        {
            "name": "wiki_page",
            "description": (
                "Open one wiki page by page_id: summary, links to related pages, and "
                "the eu_refs to fetch as evidence. Navigation only — cite via "
                "get_evidence, never the page text."
            ),
            "parameters": {
                "type": "object",
                "properties": {"page_id": {"type": "string"}},
                "required": ["page_id"],
            },
            "handler": wiki_page,
        },
        {
            "name": "graph_neighbors",
            "description": (
                "Look up an entity in the knowledge graph: its grounded eu_refs and "
                "its typed relations to neighboring entities."
            ),
            "parameters": {
                "type": "object",
                "properties": {"entity": {"type": "string"}},
                "required": ["entity"],
            },
            "handler": graph_neighbors,
        },
        {
            "name": "get_evidence",
            "description": (
                "Fetch one Evidence Unit by eu_id: the VERBATIM source text with "
                "page, checksum and raw object provenance. This is what you cite."
            ),
            "parameters": {
                "type": "object",
                "properties": {"eu_id": {"type": "string"}},
                "required": ["eu_id"],
            },
            "handler": get_evidence,
        },
    ]
