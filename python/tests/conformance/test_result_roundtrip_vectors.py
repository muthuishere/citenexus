"""conformance/cases/result_roundtrip.json asserted as a BINDING contract (§7).

Go and JS construct an equivalent Result and compare its serialization
(``golang/result/result_test.go:37``, ``js/src/result/result.test.ts:70``).
Python takes the stronger direction available to it: it VALIDATES the committed
JSON into the shipped model and asserts it re-emits byte-identically. That
catches a field the reference model would silently drop or rename — which a
construct-then-dump test cannot, because it never reads the fixture's keys.
"""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.answer.result import Decision, Result

from .fixtures import load_case

CASES: list[dict[str, Any]] = load_case("result_roundtrip.json")

EXPECTED_COUNT = 2


def test_vector_count() -> None:
    assert len(CASES) == EXPECTED_COUNT


def test_both_decisions_are_covered() -> None:
    """A wire contract that only pins the happy path pins half a contract."""
    decisions = {c["result"]["evidence"]["decision"] for c in CASES}
    assert decisions == {Decision.answered.value, Decision.refused.value}


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in CASES])
def test_result_roundtrips_byte_identically(case: dict[str, Any]) -> None:
    reparsed = Result.model_validate(case["result"]).model_dump(mode="json")
    assert reparsed == case["result"], case["name"]
