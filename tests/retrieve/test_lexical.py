"""LexicalRetriever — BM25-lite sparse signal over scan() (spec §10)."""

from __future__ import annotations

from trustrag.retrieve.lexical import LexicalRetriever
from trustrag.retrieve.types import RetrievalSignal
from trustrag.storage.lance_store import LeafVectorStore


def test_term_matching_document_ranks_first(seeded_store: LeafVectorStore) -> None:
    out = LexicalRetriever(seeded_store).retrieve("termination clause", k=3)
    assert out
    assert all(c.signal is RetrievalSignal.lexical for c in out)
    assert out[0].eu_id == "doc1::0"  # the only row containing "termination"


def test_confidentiality_query_ranks_its_doc_first(
    seeded_store: LeafVectorStore,
) -> None:
    out = LexicalRetriever(seeded_store).retrieve("confidentiality disclosure", k=3)
    assert out[0].eu_id == "doc1::2"


def test_empty_corpus_returns_empty(empty_store: LeafVectorStore) -> None:
    assert LexicalRetriever(empty_store).retrieve("anything", k=5) == []


def test_no_term_match_returns_empty(seeded_store: LeafVectorStore) -> None:
    # A query whose tokens appear in no document scores nothing.
    assert LexicalRetriever(seeded_store).retrieve("zzz qqq", k=5) == []


def test_plugin_version_is_non_empty(seeded_store: LeafVectorStore) -> None:
    assert LexicalRetriever(seeded_store).plugin_version
