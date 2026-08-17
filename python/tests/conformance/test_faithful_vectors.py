"""conformance/cases/faithful.json asserted as a BINDING contract (frozen v1 gate).

``tests/cli/test_verify.py:154`` already parametrizes over the ``supported``
bucket, but through the CLI and with no count pin, and the ``relevance`` bucket
had no Python consumer at all. This holds both buckets directly against the
frozen predicates the ports reproduce.
"""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.answer.verify import has_relevance_overlap, is_supported

from .fixtures import load_case

VECTORS: dict[str, list[dict[str, Any]]] = load_case("faithful.json")

EXPECTED_COUNTS: dict[str, int] = {"supported": 7, "relevance": 5}


def test_bucket_names_and_sizes() -> None:
    assert set(VECTORS) == set(EXPECTED_COUNTS)
    assert {k: len(v) for k, v in VECTORS.items()} == EXPECTED_COUNTS


@pytest.mark.parametrize(
    "case", [pytest.param(c, id=f"supported-{i}") for i, c in enumerate(VECTORS["supported"])]
)
def test_supported_vector(case: dict[str, Any]) -> None:
    assert is_supported(case["answer"], case["passage"]) is case["supported"], (
        f"answer={case['answer']!r}\npassage={case['passage']!r}"
    )


@pytest.mark.parametrize(
    "case", [pytest.param(c, id=f"relevance-{i}") for i, c in enumerate(VECTORS["relevance"])]
)
def test_relevance_vector(case: dict[str, Any]) -> None:
    assert has_relevance_overlap(case["query"], case["passage"]) is case["relevant"], (
        f"query={case['query']!r}\npassage={case['passage']!r}"
    )
