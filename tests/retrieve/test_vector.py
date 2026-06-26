"""VectorRetriever — dense signal over the leaf store (spec §10)."""

from __future__ import annotations

from trustrag.retrieve.types import RetrievalSignal
from trustrag.retrieve.vector import VectorRetriever
from trustrag.storage.lance_store import LeafVectorStore
from trustrag.testing.fakes import FakeEmbedding


def test_hits_are_vector_signal_ranked_by_similarity(
    seeded_store: LeafVectorStore, embedder: FakeEmbedding
) -> None:
    retriever = VectorRetriever(seeded_store, embedder)
    out = retriever.retrieve("termination of employment", k=3)
    assert out
    assert all(c.signal is RetrievalSignal.vector for c in out)
    # The termination EU is the nearest; scores descend.
    assert out[0].eu_id == "doc1::0"
    assert [c.score for c in out] == sorted((c.score for c in out), reverse=True)


def test_candidate_carries_payload_and_page_none(
    seeded_store: LeafVectorStore, embedder: FakeEmbedding
) -> None:
    out = VectorRetriever(seeded_store, embedder).retrieve("salary", k=1)
    top = out[0]
    assert top.document_id == "doc1"
    assert top.text is not None
    assert top.language == "en"
    assert top.page is None  # the -1 ingest sentinel maps back to None


def test_empty_leaf_returns_empty(
    empty_store: LeafVectorStore, embedder: FakeEmbedding
) -> None:
    assert VectorRetriever(empty_store, embedder).retrieve("x", k=5) == []


def test_plugin_version_is_non_empty(
    seeded_store: LeafVectorStore, embedder: FakeEmbedding
) -> None:
    assert VectorRetriever(seeded_store, embedder).plugin_version
