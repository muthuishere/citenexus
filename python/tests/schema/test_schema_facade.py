"""rag.schema.ingest_from — typed schema intake; fail-loud, artifact-only."""

from __future__ import annotations

from pathlib import Path

import pytest

from citenexus import CiteNexus
from citenexus.extract.types import SourceType
from citenexus.testing import FakeEmbedding

_DDL = (
    "CREATE TABLE accounts (\n"
    "    id INTEGER PRIMARY KEY,\n"
    "    name TEXT NOT NULL\n"
    ");\n"
    "\n"
    "CREATE TABLE orders (\n"
    "    id INTEGER PRIMARY KEY,\n"
    "    account_id INTEGER REFERENCES accounts(id)\n"
    ");\n"
)
_OPENAPI = (
    "{\n"
    '  "openapi": "3.0.0",\n'
    '  "paths": { "/orders": { "post": {} } },\n'
    '  "components": { "schemas": { "Order": { "type": "object" } } }\n'
    "}\n"
)


def _rag(tmp_path: Path, *, signals: list[str]) -> CiteNexus:
    return CiteNexus(tmp_path / "store", embedder=FakeEmbedding(), signals=signals)


def test_ddl_file_becomes_verbatim_schema_eus(tmp_path: Path) -> None:
    ddl = tmp_path / "schema.sql"
    ddl.write_text(_DDL)
    rag = _rag(tmp_path, signals=["embedding", "graph"])

    report = rag.schema.ingest_from(ddl)

    assert report.source_type is SourceType.schema_sql
    assert report.is_schema
    texts = [str(r["text"]) for r in rag._store.scan()]
    assert any(t.startswith("CREATE TABLE accounts") for t in texts)
    assert any(t.startswith("CREATE TABLE orders") for t in texts)


def test_openapi_doc_bytes_becomes_schema_eus(tmp_path: Path) -> None:
    rag = _rag(tmp_path, signals=["embedding", "graph"])

    report = rag.schema.ingest_from(_OPENAPI.encode("utf-8"), document_id="api")

    assert report.source_type is SourceType.schema_openapi
    texts = [str(r["text"]) for r in rag._store.scan()]
    assert any(t.startswith('"/orders"') for t in texts)
    assert any(t.startswith('"Order"') for t in texts)


def test_missing_graph_signal_fails_loud(tmp_path: Path) -> None:
    ddl = tmp_path / "schema.sql"
    ddl.write_text(_DDL)
    rag = _rag(tmp_path, signals=["embedding", "text"])  # no graph/community

    with pytest.raises(ValueError, match="graph"):
        rag.schema.ingest_from(ddl)

    assert list(rag._store.scan()) == []


def test_community_signal_also_satisfies_precondition(tmp_path: Path) -> None:
    ddl = tmp_path / "schema.sql"
    ddl.write_text(_DDL)
    rag = _rag(tmp_path, signals=["embedding", "community"])

    report = rag.schema.ingest_from(ddl)
    assert report.is_schema


def test_connection_url_is_not_treated_as_connector(tmp_path: Path) -> None:
    """A live connection URL is rejected fail-loud — never connected to."""
    rag = _rag(tmp_path, signals=["embedding", "graph"])

    with pytest.raises(ValueError, match=r"artifact|connector|connection"):
        rag.schema.ingest_from("postgres://user:pw@localhost:5432/db")

    # Nothing was ingested; nothing was connected.
    assert list(rag._store.scan()) == []


def test_unknown_source_degrades_to_plain(tmp_path: Path) -> None:
    """A source no schema extractor recognises ingests as plain — never raises."""
    note = tmp_path / "notes.txt"
    note.write_text("Just some prose about the database, no DDL here.\n")
    rag = _rag(tmp_path, signals=["embedding", "graph"])

    report = rag.schema.ingest_from(note)

    assert report.source_type is SourceType.plain
    assert not report.is_schema
    assert list(rag._store.scan())  # content is available as plain EUs
