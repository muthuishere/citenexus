"""Dual-query RRF in the retrieval engine (RAG-Fusion, spec §10).

The engine can retrieve with the original query PLUS reformulations; every
(retriever x query) list feeds one RRF fusion, so an EU found by either query
surfaces. The reranker always sees the ORIGINAL query — the user's true intent.
"""

from __future__ import annotations

from collections.abc import Sequence

from citenexus.plugins.base import RetrieverPlugin
from citenexus.retrieve.engine import RetrievalEngine
from citenexus.retrieve.types import Candidate, RetrievalSignal


def _candidate(eu_id: str, score: float, text: str = "") -> Candidate:
    return Candidate(eu_id=eu_id, score=score, signal=RetrievalSignal.vector, text=text or eu_id)


class KeywordRetriever(RetrieverPlugin):
    """Returns a doc only when the query mentions its keyword — language-exact."""

    plugin_version = "kw-test-v1"

    def __init__(self, corpus: dict[str, str]) -> None:
        self._corpus = corpus  # keyword -> eu_id

    def retrieve(self, query: str, k: int) -> list[Candidate]:
        low = query.lower()
        return [
            _candidate(eu_id, 1.0) for keyword, eu_id in self._corpus.items() if keyword in low
        ][:k]


class RecordingReranker:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]:
        self.queries.append(query)
        return list(candidates)


def _engine(reranker: RecordingReranker | None = None) -> RetrievalEngine:
    # English-only corpus: "refund" is findable in English, not in French.
    retriever = KeywordRetriever({"refund": "policy::0", "leave": "hr::0"})
    return RetrievalEngine(retrievers=[retriever], reranker=reranker or RecordingReranker())


def test_single_query_misses_cross_lingual() -> None:
    hits = _engine().retrieve("Quel est le délai de remboursement?", 5)
    assert hits == []  # the baseline failure this feature fixes


def test_extra_query_recovers_the_miss() -> None:
    hits = _engine().retrieve(
        "Quel est le délai de remboursement?",
        5,
        extra_queries=["What is the refund deadline?"],
    )
    assert [h.eu_id for h in hits] == ["policy::0"]


def test_both_queries_fuse_not_duplicate() -> None:
    # A doc matched by BOTH queries appears once, ranked above single-query docs.
    hits = _engine().retrieve(
        "When can I get a refund?",
        5,
        extra_queries=["refund deadline policy", "leave accrual"],
    )
    eu_ids = [h.eu_id for h in hits]
    assert eu_ids[0] == "policy::0"  # two lists agree -> fused to the top
    assert eu_ids.count("policy::0") == 1
    assert "hr::0" in eu_ids


def test_reranker_sees_the_original_query() -> None:
    reranker = RecordingReranker()
    _engine(reranker).retrieve("Quel est le délai?", 5, extra_queries=["What is the deadline?"])
    assert reranker.queries == ["Quel est le délai?"]
