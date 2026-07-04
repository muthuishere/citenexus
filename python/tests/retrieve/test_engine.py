"""RetrievalEngine — run retrievers → RRF → rerank → ranked EUs (spec §10)."""

from __future__ import annotations

from collections.abc import Sequence

from citenexus.retrieve.engine import RetrievalEngine
from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.lexical import LexicalRetriever
from citenexus.retrieve.structure import StructureRetriever
from citenexus.retrieve.types import Candidate
from citenexus.retrieve.vector import VectorRetriever
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.lance_store import LanceVectorStore
from citenexus.testing.fakes import FakeEmbedding

from .conftest import PARTITION


class _SpyReranker:
    """Identity reranker that records that the seam was invoked."""

    plugin_version = "spy-rerank-v1"

    def __init__(self) -> None:
        self.called = False

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        self.called = True
        return list(candidates)


def _engine(
    store: LanceVectorStore,
    backend: LocalFsBackend,
    embedder: FakeEmbedding,
    reranker: _SpyReranker,
) -> RetrievalEngine:
    return RetrievalEngine(
        retrievers=[
            VectorRetriever(store, embedder),
            LexicalRetriever(store),
            StructureRetriever(backend, PARTITION, store),
        ],
        reranker=reranker,
    )


def test_end_to_end_fused_reranked_list(
    seeded_store: LanceVectorStore,
    backend_with_structure: LocalFsBackend,
    embedder: FakeEmbedding,
) -> None:
    spy = _SpyReranker()
    engine = _engine(seeded_store, backend_with_structure, embedder, spy)
    out = engine.retrieve("termination of employment", k=10)
    assert out
    assert spy.called  # the rerank seam was invoked
    # termination EU is surfaced by vector + lexical + structure → it leads.
    assert out[0].eu_id == "doc1::0"


def test_identity_reranker_preserves_fused_order(
    seeded_store: LanceVectorStore,
    backend_with_structure: LocalFsBackend,
    embedder: FakeEmbedding,
) -> None:
    spy = _SpyReranker()
    engine = _engine(seeded_store, backend_with_structure, embedder, spy)
    query = "confidentiality disclosure"
    got = [c.eu_id for c in engine.retrieve(query, k=10)]

    # Recompute the fused order directly; identity rerank must match it.
    lists = [
        VectorRetriever(seeded_store, embedder).retrieve(query, 10),
        LexicalRetriever(seeded_store).retrieve(query, 10),
        StructureRetriever(backend_with_structure, PARTITION, seeded_store).retrieve(query, 10),
    ]
    expected = [c.eu_id for c in rrf_fuse(lists)]
    assert got == expected


def test_k_caps_the_result(
    seeded_store: LanceVectorStore,
    backend_with_structure: LocalFsBackend,
    embedder: FakeEmbedding,
) -> None:
    engine = _engine(seeded_store, backend_with_structure, embedder, _SpyReranker())
    out = engine.retrieve("employment", k=1)
    assert len(out) == 1
