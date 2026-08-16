"""End-to-end structural schema graph — verbatim EUs + extracted FK / $ref edges.

The schema extractor (Rust core, Python reference) makes each table / endpoint /
type a verbatim, citable EU; an *injected* ``SchemaDistiller`` (example code, NOT
core) turns the same DDL/OpenAPI into a grounded graph whose FK / ``$ref`` edges
carry ``confidence=extracted`` (authoritative, not guessed). These tests prove:

1. a DDL foreign key becomes an ``extracted`` edge between the right table EUs;
2. an OpenAPI ``$ref`` becomes an ``extracted`` edge between component EUs;
3. every edge endpoint resolves to a real schema EU (grounding drops danglers).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from citenexus import CiteNexus
from citenexus.graph.store import EdgeConfidence
from citenexus.testing import FakeEmbedding

_DISTILLER_PATH = (
    Path(__file__).resolve().parents[2] / "example" / "schema_graph" / "schema_distiller.py"
)

_DDL = (
    "CREATE TABLE accounts (\n"
    "    id INTEGER PRIMARY KEY,\n"
    "    name TEXT NOT NULL\n"
    ");\n"
    "\n"
    "CREATE TABLE orders (\n"
    "    id INTEGER PRIMARY KEY,\n"
    "    account_id INTEGER REFERENCES accounts(id),\n"
    "    total NUMERIC\n"
    ");\n"
)
_OPENAPI = (
    "{\n"
    '  "openapi": "3.0.0",\n'
    '  "paths": { "/orders": { "post": {} } },\n'
    '  "components": {\n'
    '    "schemas": {\n'
    '      "Order": {\n'
    '        "type": "object",\n'
    '        "properties": { "account": { "$ref": "#/components/schemas/Account" } }\n'
    "      },\n"
    '      "Account": { "type": "object" }\n'
    "    }\n"
    "  }\n"
    "}\n"
)


def _load_distiller_cls() -> Any:
    spec = importlib.util.spec_from_file_location("example_schema_distiller", _DISTILLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SchemaDistiller


def test_foreign_key_is_an_extracted_edge_to_the_right_tables(tmp_path: Path) -> None:
    ddl = tmp_path / "schema.sql"
    ddl.write_text(_DDL)
    distiller = _load_distiller_cls()(_DDL, kind="sql")
    rag = CiteNexus(
        tmp_path / "store",
        embedder=FakeEmbedding(),
        signals=["embedding", "graph"],
        graph_distiller=distiller,
    )
    rag.schema.ingest_from(ddl)

    index = rag._graph_store.load()
    assert index is not None
    # Both tables grounded to real EUs — no drops.
    assert distiller.last_stats.get("node_dropped_ungrounded", 0) == 0
    assert distiller.last_stats["node_grounded"] == 2

    by_id = {n.node_id: n for n in index.nodes}
    fk = [e for e in index.edges if e.relation == "references"]
    assert len(fk) == 1
    edge = fk[0]
    assert edge.confidence is EdgeConfidence.extracted
    # orders.account_id -> accounts(id)
    assert by_id[edge.source].label == "orders"
    assert by_id[edge.target].label == "accounts"

    # The target resolves down to a VERBATIM, citable schema EU.
    rows = {str(r["eu_id"]): r for r in rag._store.scan()}
    accounts_eu = str(rows[by_id[edge.target].eu_refs[0]]["text"])
    assert accounts_eu.startswith("CREATE TABLE accounts")


def test_openapi_ref_is_an_extracted_edge(tmp_path: Path) -> None:
    api = tmp_path / "openapi.json"
    api.write_text(_OPENAPI)
    distiller = _load_distiller_cls()(_OPENAPI, kind="openapi")
    rag = CiteNexus(
        tmp_path / "store",
        embedder=FakeEmbedding(),
        signals=["embedding", "graph"],
        graph_distiller=distiller,
    )
    rag.schema.ingest_from(api)

    index = rag._graph_store.load()
    assert index is not None
    refs = [e for e in index.edges if e.relation == "ref"]
    assert len(refs) == 1
    edge = refs[0]
    assert edge.confidence is EdgeConfidence.extracted

    by_id = {n.node_id: n for n in index.nodes}
    # Order -> $ref Account
    assert by_id[edge.source].label == "Order"
    assert by_id[edge.target].label == "Account"
    # Every endpoint resolves to a verbatim, cited EU.
    rows = {str(r["eu_id"]): r for r in rag._store.scan()}
    account_eu = str(rows[by_id[edge.target].eu_refs[0]]["text"])
    assert account_eu.startswith('"Account"')
