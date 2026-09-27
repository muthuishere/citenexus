"""RetrievalEngine — run retrievers → RRF → rerank → ranked EUs (spec §10)."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from citenexus.plugins.base import RetrieverPlugin
from citenexus.retrieve.engine import RetrievalEngine
from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.lexical import LexicalRetriever
from citenexus.retrieve.structure import StructureRetriever
from citenexus.retrieve.types import Candidate, RetrievalSignal
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


class _ConcurrencyProbe:
    """Records the peak number of retrievals in flight at the same moment."""

    def __init__(self, parties: int) -> None:
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(parties)
        self.in_flight = 0
        self.peak = 0

    def enter(self) -> None:
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)

    def leave(self) -> None:
        with self.lock:
            self.in_flight -= 1


class _ProbeRetriever(RetrieverPlugin):
    """Blocks until every peer retrieval is ALSO in flight (ADR-0013 §Cost).

    A serial fan-out can never get more than one call in flight, so the barrier
    times out and the test fails; a concurrent one opens it immediately.
    """

    plugin_version = "probe-retriever-v1"

    def __init__(self, eu_id: str, probe: _ConcurrencyProbe) -> None:
        self._eu_id = eu_id
        self._probe = probe

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        self._probe.enter()
        try:
            self._probe.barrier.wait(timeout=2)
        finally:
            self._probe.leave()
        return [Candidate(eu_id=self._eu_id, score=1.0, signal=RetrievalSignal.vector, text=query)]


def test_fanout_runs_the_independent_retrievals_concurrently() -> None:
    """The N x R retrievals are independent → latency is ONE round, not N (ADR-0013)."""
    probe = _ConcurrencyProbe(parties=3)
    engine = RetrievalEngine(
        retrievers=[_ProbeRetriever(f"doc{i}::0", probe) for i in range(3)],
        reranker=_SpyReranker(),
    )

    out = engine.retrieve("termination", k=3)

    assert probe.peak == 3  # all three were in flight at once
    assert [c.eu_id for c in out] == ["doc0::0", "doc1::0", "doc2::0"]


class _QueryTaggedRetriever(RetrieverPlugin):
    """Returns the SAME ``eu_id`` for every query, tagged with the query text.

    ``rrf_fuse`` keeps the FIRST list's payload on an equal score, so the fused
    candidate's ``text`` reveals which list the engine treated as first.
    """

    plugin_version = "query-tagged-retriever-v1"

    def __init__(self, slow_query: str) -> None:
        self._slow_query = slow_query

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        if query == self._slow_query:
            time.sleep(0.05)  # finishes LAST: completion order ≠ declared order
        return [Candidate(eu_id="shared::0", score=1.0, signal=RetrievalSignal.vector, text=query)]


def test_fanout_reassembles_lists_in_declared_order() -> None:
    """Concurrency must not reorder the lists: RRF output is unchanged (ADR-0013)."""
    engine = RetrievalEngine(
        retrievers=[_QueryTaggedRetriever(slow_query="original question")],
        reranker=_SpyReranker(),
    )

    out = engine.retrieve("original question", k=5, extra_queries=["reformulation"])

    assert len(out) == 1
    # The original query's list is declared FIRST, so its payload wins the tie.
    assert out[0].text == "original question"
