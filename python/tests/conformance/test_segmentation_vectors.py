"""conformance/cases/segmentation.json asserted as a BINDING contract.

Atomic-claim splitting is what makes drop-not-fail possible: a wrong split means
a true sentence and a fabricated one are gated as a single unit. Go
(``golang/answer/segment_test.go:20``) and JS (``js/src/answer/segment.test.ts:16``)
both replay these vectors; the reference port did not until this module.
"""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.answer.segment import split_claims

from .fixtures import load_case

VECTORS: list[dict[str, Any]] = load_case("segmentation.json")

EXPECTED_COUNT = 12


def test_vector_count() -> None:
    assert len(VECTORS) == EXPECTED_COUNT


@pytest.mark.parametrize("case", [pytest.param(c, id=f"seg-{i}") for i, c in enumerate(VECTORS)])
def test_segmentation_vector(case: dict[str, Any]) -> None:
    assert split_claims(case["text"]) == case["claims"], f"text={case['text']!r}"
