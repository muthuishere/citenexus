"""conformance/cases/bm25.json asserted as a BINDING contract."""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.storage.bm25 import Bm25TextSearch

from .fixtures import load_case

VECTORS: list[dict[str, Any]] = load_case("bm25.json")

EXPECTED_COUNT = 4


class _StubStore:
    """Minimal ``scan()``-capable store, exactly what Bm25TextSearch consumes."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def scan(self) -> list[dict[str, Any]]:
        return list(self._rows)


def test_vector_count() -> None:
    assert len(VECTORS) == EXPECTED_COUNT


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in VECTORS])
def test_bm25_vector(case: dict[str, Any]) -> None:
    """Ranked eu_ids AND scores (rounded 1e-6) must match the committed vector."""
    search = Bm25TextSearch(_StubStore(case["rows"]))  # type: ignore[arg-type]
    results = search.search_text(case["query"], limit=10)
    got = [{"eu_id": row["eu_id"], "score": round(row["_text_score"], 6)} for row in results]
    assert got == case["expected"], f"query={case['query']!r}"
