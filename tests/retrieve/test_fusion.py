"""rrf_fuse — Reciprocal Rank Fusion by eu_id (spec §10, RRF k=60)."""

from __future__ import annotations

from trustrag.retrieve.fusion import rrf_fuse
from trustrag.retrieve.types import Candidate, RetrievalSignal


def _c(eu_id: str, score: float, signal: RetrievalSignal) -> Candidate:
    return Candidate(eu_id=eu_id, score=score, signal=signal)


def test_two_signal_eu_outranks_single_signal_eu() -> None:
    # eu_shared appears in both lists; eu_solo only at rank 0 of one list.
    list_a = [
        _c("eu_solo", 9.0, RetrievalSignal.vector),
        _c("eu_shared", 1.0, RetrievalSignal.vector),
    ]
    list_b = [
        _c("eu_shared", 1.0, RetrievalSignal.lexical),
        _c("eu_other", 1.0, RetrievalSignal.lexical),
    ]
    fused = rrf_fuse([list_a, list_b])
    order = [c.eu_id for c in fused]
    assert order.index("eu_shared") < order.index("eu_solo")


def test_score_math_and_k_respected() -> None:
    list_a = [_c("a", 1.0, RetrievalSignal.vector), _c("b", 1.0, RetrievalSignal.vector)]
    list_b = [_c("b", 1.0, RetrievalSignal.lexical)]
    fused = {c.eu_id: c.score for c in rrf_fuse([list_a, list_b], k=10)}
    # a: rank 0 in list_a only → 1/(10+1)
    assert fused["a"] == 1.0 / 11
    # b: rank 1 in list_a + rank 0 in list_b → 1/(10+2) + 1/(10+1)
    assert fused["b"] == 1.0 / 12 + 1.0 / 11


def test_deterministic_order() -> None:
    lists = [
        [_c("x", 1.0, RetrievalSignal.vector), _c("y", 1.0, RetrievalSignal.vector)],
        [_c("y", 1.0, RetrievalSignal.lexical), _c("z", 1.0, RetrievalSignal.lexical)],
    ]
    first = [c.eu_id for c in rrf_fuse(lists)]
    second = [c.eu_id for c in rrf_fuse(lists)]
    assert first == second


def test_fused_candidate_keeps_best_payload() -> None:
    # The higher-scoring contributor's payload survives, with a fused score.
    list_a = [_c("e", 0.2, RetrievalSignal.vector)]
    list_b = [
        Candidate(
            eu_id="e",
            score=0.9,
            signal=RetrievalSignal.lexical,
            text="winner",
            document_id="d",
        )
    ]
    fused = rrf_fuse([list_a, list_b])
    assert len(fused) == 1
    assert fused[0].text == "winner"
    assert fused[0].score == 1.0 / 61 + 1.0 / 61  # rank 0 in both lists, k=60


def test_empty_input_is_empty() -> None:
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []
