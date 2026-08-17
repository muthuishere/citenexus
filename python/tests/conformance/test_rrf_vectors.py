"""conformance/cases/rrf.json asserted as a BINDING contract.

Until this module existed the only Python consumer of these vectors was
``tests/core/test_rust_rrf_parity.py``, which SKIPS unless the Rust dylib is
built — so on an ordinary `task check` the RRF vectors bound nothing in the
reference port at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.types import Candidate, RetrievalSignal

from .fixtures import load_case

VECTORS: list[dict[str, Any]] = load_case("rrf.json")

EXPECTED_COUNT = 5


def test_vector_count() -> None:
    assert len(VECTORS) == EXPECTED_COUNT


@pytest.mark.parametrize("case", [pytest.param(c, id=f"rrf-{i}") for i, c in enumerate(VECTORS)])
def test_rrf_vector(case: dict[str, Any]) -> None:
    candidate_lists = [
        [
            Candidate(eu_id=eu_id, score=1.0 / (rank + 1), signal=RetrievalSignal.vector)
            for rank, eu_id in enumerate(one_list)
        ]
        for one_list in case["lists"]
    ]
    fused = rrf_fuse(candidate_lists, k=case["k"])
    assert [c.eu_id for c in fused] == case["fused"], f"lists={case['lists']}"


def test_k_is_pinned_at_60() -> None:
    """Every vector fixes k=60; a port reading a different k is not conformant."""
    assert {c["k"] for c in VECTORS} == {60}
