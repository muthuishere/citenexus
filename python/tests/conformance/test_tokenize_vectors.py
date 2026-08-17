"""conformance/cases/tokenize.json asserted as a BINDING contract (v1 tokenizer)."""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.testing.fakes import tokenize

from .fixtures import load_case

VECTORS: list[dict[str, Any]] = load_case("tokenize.json")

#: A vector silently dropped is a weakened contract no per-case assertion sees.
EXPECTED_COUNT = 11


def test_vector_count() -> None:
    assert len(VECTORS) == EXPECTED_COUNT


@pytest.mark.parametrize(
    "case", [pytest.param(c, id=f"tokenize-{i}") for i, c in enumerate(VECTORS)]
)
def test_tokenize_vector(case: dict[str, Any]) -> None:
    assert tokenize(case["input"]) == case["tokens"], f"input={case['input']!r}"
