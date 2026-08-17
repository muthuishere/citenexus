"""conformance/cases/language.json asserted as a BINDING contract (§11a chain)."""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.lang.detect import LanguageResult
from citenexus.lang.fallback import resolve_answer_language

from .fixtures import load_case

VECTORS: list[dict[str, Any]] = load_case("language.json")

EXPECTED_COUNT = 6


def test_vector_count() -> None:
    assert len(VECTORS) == EXPECTED_COUNT


def test_every_rung_of_the_chain_is_covered() -> None:
    """The fixture is the §11a decision table; each named rung must be present."""
    names = [c["name"] for c in VECTORS]
    assert len(set(names)) == EXPECTED_COUNT, f"duplicate case names: {names}"


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in VECTORS])
def test_language_vector(case: dict[str, Any]) -> None:
    detection = LanguageResult(**case["detection"]) if case["detection"] is not None else None
    got = resolve_answer_language(
        detection=detection,
        answer_language=case["answer_language"],
        conversation_language=case["conversation_language"],
        languages_in_evidence=case["languages_in_evidence"],
        default_answer_language=case["default_answer_language"],
    )
    assert got == case["expected"], case["name"]
