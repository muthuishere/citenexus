"""conformance/cases/chunker.json asserted as a BINDING contract."""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.evidence.chunker import chunk_text

from .fixtures import load_case

VECTORS: list[dict[str, Any]] = load_case("chunker.json")

EXPECTED_COUNT = 7


def test_vector_count() -> None:
    assert len(VECTORS) == EXPECTED_COUNT


@pytest.mark.parametrize(
    "case", [pytest.param(c, id=f"chunker-{i}") for i, c in enumerate(VECTORS)]
)
def test_chunker_vector(case: dict[str, Any]) -> None:
    chunks = chunk_text(
        case["text"], max_tokens=case["max_tokens"], overlap=case["overlap"]
    )
    assert chunks == case["chunks"], (
        f"max_tokens={case['max_tokens']} overlap={case['overlap']} text={case['text']!r}"
    )
