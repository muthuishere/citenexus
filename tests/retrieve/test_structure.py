"""StructureRetriever — node-label match → EUs under matching nodes (spec §10)."""

from __future__ import annotations

from trustrag.retrieve.structure import StructureRetriever
from trustrag.retrieve.types import RetrievalSignal
from trustrag.storage.backend import LocalFsBackend
from trustrag.storage.lance_store import LeafVectorStore

from .conftest import PARTITION


def test_heading_match_returns_eus_under_node(
    backend_with_structure: LocalFsBackend, seeded_store: LeafVectorStore
) -> None:
    retriever = StructureRetriever(backend_with_structure, PARTITION, seeded_store)
    out = retriever.retrieve("termination", k=5)
    eu_ids = {c.eu_id for c in out}
    assert "doc1::0" in eu_ids
    assert all(c.signal is RetrievalSignal.structure for c in out)
    # Payload is resolved from the store rows.
    top = next(c for c in out if c.eu_id == "doc1::0")
    assert top.text is not None
    assert top.document_id == "doc1"


def test_non_matching_query_returns_empty(
    backend_with_structure: LocalFsBackend, seeded_store: LeafVectorStore
) -> None:
    retriever = StructureRetriever(backend_with_structure, PARTITION, seeded_store)
    assert retriever.retrieve("salary", k=5) == []


def test_no_structure_index_returns_empty(
    empty_backend: LocalFsBackend, seeded_store: LeafVectorStore
) -> None:
    retriever = StructureRetriever(empty_backend, PARTITION, seeded_store)
    assert retriever.retrieve("termination", k=5) == []


def test_plugin_version_is_non_empty(
    empty_backend: LocalFsBackend, seeded_store: LeafVectorStore
) -> None:
    assert StructureRetriever(empty_backend, PARTITION, seeded_store).plugin_version
