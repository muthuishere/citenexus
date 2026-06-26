"""Reciprocal Rank Fusion — the core, in-core merge of signal lists (spec §10).

Each retriever returns its own ranked list; ``rrf_fuse`` merges them by ``eu_id``
so an EU that several signals agree on rises above one a single signal ranked
high. The math is the standard RRF: a candidate at zero-based ``rank`` in a list
contributes ``1 / (k + rank + 1)`` to its ``eu_id``'s fused score (``k = 60`` by
default). The function is pure and deterministic — fusion lives in core so no
third-party retriever can bypass it (§4b).
"""

from __future__ import annotations

from collections.abc import Sequence

from trustrag.retrieve.types import Candidate


def rrf_fuse(lists: Sequence[list[Candidate]], k: int = 60) -> list[Candidate]:
    """Fuse ranked candidate lists by ``eu_id`` with Reciprocal Rank Fusion.

    The fused candidate keeps the best contributing payload (the input candidate
    with the highest individual ``score``; first occurrence breaks ties) with its
    score replaced by the fused score. The result is ordered by descending fused
    score, with ``eu_id`` as a deterministic tie-break.
    """
    fused_score: dict[str, float] = {}
    best_payload: dict[str, Candidate] = {}

    for candidates in lists:
        for rank, candidate in enumerate(candidates):
            eu_id = candidate.eu_id
            fused_score[eu_id] = fused_score.get(eu_id, 0.0) + 1.0 / (k + rank + 1)
            incumbent = best_payload.get(eu_id)
            if incumbent is None or candidate.score > incumbent.score:
                best_payload[eu_id] = candidate

    fused = [
        best_payload[eu_id].model_copy(update={"score": score})
        for eu_id, score in fused_score.items()
    ]
    fused.sort(key=lambda c: (-c.score, c.eu_id))
    return fused
