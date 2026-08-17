"""conformance/cases/graph_comention.json asserted as a BINDING contract (§10b).

The co-mention graph is navigate-not-cite: it steers retrieval, so a port that
builds different edges steers to different evidence for the same question.
"""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.graph.store import build_comention_graph

from .fixtures import load_case

CASES: list[dict[str, Any]] = load_case("graph_comention.json")["cases"]

EXPECTED_COUNT = 3


def test_vector_count() -> None:
    assert len(CASES) == EXPECTED_COUNT


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in CASES])
def test_graph_vector(case: dict[str, Any]) -> None:
    index = build_comention_graph(case["rows"])
    assert index.model_dump(mode="json") == case["expected"], case["name"]
