"""conformance/cases/faithful_v2.json asserted as a BINDING contract (ADR-0009).

These 39 vectors are the ordered-containment + polarity gate — the check the
whole project exists to make trustworthy. Go asserts them
(``golang/gate/verify_v2_test.go:31,57,72``) and JS asserts them
(``js/src/gate/verify-v2.test.ts:25``); until this module, the reference port
did not. ``scripts/gen_conformance.py:1287`` *writes* the file from
``tests/answer/test_verify_v2.py``'s Python lists, which is the re-derivation
trap: the vectors and the assertions came from the same object, so the JSON
pinned nothing on the Python side.
"""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.answer.verify import is_supported, is_supported_v2

from .fixtures import load_case

VECTORS: dict[str, list[dict[str, Any]]] = load_case("faithful_v2.json")

EXPECTED_COUNTS: dict[str, int] = {"attacks": 9, "controls": 30}


def test_bucket_names_and_sizes() -> None:
    assert set(VECTORS) == set(EXPECTED_COUNTS)
    assert {k: len(v) for k, v in VECTORS.items()} == EXPECTED_COUNTS


@pytest.mark.parametrize(
    "case", [pytest.param(c, id=c["name"]) for c in VECTORS["attacks"]]
)
def test_attack_vector(case: dict[str, Any]) -> None:
    """Every attack answer is FALSE w.r.t. its passage; the v2 gate must reject it."""
    assert is_supported_v2(case["answer"], case["passage"]) is case["supported"], (
        f"{case['name']}\nanswer={case['answer']!r}\npassage={case['passage']!r}"
    )


@pytest.mark.parametrize(
    "case", [pytest.param(c, id=c["name"]) for c in VECTORS["controls"]]
)
def test_control_vector(case: dict[str, Any]) -> None:
    assert is_supported_v2(case["answer"], case["passage"]) is case["supported"], (
        f"{case['name']}\nanswer={case['answer']!r}\npassage={case['passage']!r}"
    )


def test_every_attack_is_rejected_by_v2() -> None:
    """The headline guarantee, stated as one assertion rather than 9 verdicts."""
    accepted = [c["name"] for c in VECTORS["attacks"] if c["supported"]]
    assert accepted == [], f"conformance file claims v2 ACCEPTS an attack: {accepted}"


def test_frozen_v1_gate_still_accepts_all_nine_attacks() -> None:
    """Why v2 exists, pinned rather than remembered.

    ``is_supported`` (frozen, SPEC-PORTS-v1 §4) accepted 9/9 of these false
    answers in all three ports while every suite was green. If this ever stops
    being true the v1 predicate has been quietly modified, which would break the
    frozen-forever contract the shipped conformance vectors rest on. Go pins the
    same fact at ``golang/gate/verify_v2_test.go:57``.
    """
    accepted = [c["name"] for c in VECTORS["attacks"] if is_supported(c["answer"], c["passage"])]
    assert len(accepted) == EXPECTED_COUNTS["attacks"], (
        f"v1 no longer accepts all attacks (accepted {len(accepted)}/9): {accepted}"
    )


def test_v2_is_narrower_than_v1() -> None:
    """ADR-0009: v2 is a TIGHTENING of v1, not a different predicate.

    Anything v2 accepts, frozen v1 already accepted. Pinned in Go at
    ``golang/gate/verify_v2_test.go``'s TestV2IsNarrowerThanV1; the reference
    port must hold the same property.
    """
    widened = [
        c["name"]
        for c in VECTORS["attacks"] + VECTORS["controls"]
        if is_supported_v2(c["answer"], c["passage"])
        and not is_supported(c["answer"], c["passage"])
    ]
    assert widened == [], f"v2 accepts what v1 rejects — it is no longer a tightening: {widened}"
