"""The ADR-0007 conflict vectors, asserted as a BINDING contract.

``conformance/cases/conflict.json`` is the cross-port contract for conflict
surfacing (ADR-0010 tier 1: native in Python, Go and JS, byte-identical). Until
this file existed, nothing in the Python suite read those vectors: the only
consumers were ``scripts/gen_conformance.py`` (which *writes* them) and the
drift guard in ``tests/test_conformance_fixtures.py`` (which re-derives the
expected verdicts from ``detect_conflict`` itself, so it can catch a stale file
but never a wrong verdict). ``tests/answer/test_conflict.py`` asserts the same
fixtures from the Python-side lists, not from the committed JSON.

This module closes that hole from the other side: it reads the committed JSON as
opaque data and asserts every one of its 132 vectors — verdict *and* rule name —
against the shipped functions. A Go or JS port is held to exactly this file, so
Python must be held to it first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from citenexus.answer.conflict import detect_conflict, is_near_duplicate

_CASES = Path(__file__).resolve().parents[2].parent / "conformance" / "cases" / "conflict.json"

VECTORS: dict[str, list[dict[str, Any]]] = json.loads(_CASES.read_text(encoding="utf-8"))

#: Bucket sizes, pinned. A vector silently dropped from a bucket is a weakened
#: contract that no per-case assertion can see.
EXPECTED_COUNTS: dict[str, int] = {
    "true_conflicts": 27,
    "hard_negatives": 27,
    "unrelated": 22,
    "heldout_conflicts": 5,
    "heldout_negatives": 10,
    "non_latin": 30,
    "near_duplicates": 9,
    "identifier_tokenization": 2,
}

_PAIR_BUCKETS = (
    "true_conflicts",
    "hard_negatives",
    "unrelated",
    "heldout_conflicts",
    "heldout_negatives",
    # ADR-0011. Every non-Latin vector in this bucket scored "no conflict"
    # while conflict ran on the frozen, ASCII-only v1 tokenizer.
    "non_latin",
)


def _pairs(bucket: str) -> list[Any]:
    return [pytest.param(case, id=f"{bucket}-{i}") for i, case in enumerate(VECTORS[bucket])]


def test_bucket_names_and_sizes() -> None:
    assert set(VECTORS) == set(EXPECTED_COUNTS)
    assert {k: len(v) for k, v in VECTORS.items()} == EXPECTED_COUNTS
    assert sum(EXPECTED_COUNTS.values()) == 132


@pytest.mark.parametrize(
    "case",
    [p for bucket in _PAIR_BUCKETS for p in _pairs(bucket)],
)
def test_pairwise_vector(case: dict[str, Any]) -> None:
    """Verdict AND rule name must match the committed vector exactly."""
    finding = detect_conflict(case["left"], case["right"])
    assert (finding is not None) is case["conflict"], (
        f"{case['domain']}/{case['label']}: expected conflict={case['conflict']}\n"
        f"  left:  {case['left']}\n  right: {case['right']}\n"
        f"  got:   {finding}"
    )
    assert (finding.rule if finding else None) == case["rule"]


@pytest.mark.parametrize("case", _pairs("near_duplicates"))
def test_near_duplicate_vector(case: dict[str, Any]) -> None:
    collapsed = is_near_duplicate(case["left"], case["right"]) is not None
    assert collapsed is case["collapses"], (
        f"{case['label']}: expected collapses={case['collapses']}\n"
        f"  left:  {case['left']}\n  right: {case['right']}"
    )


@pytest.mark.parametrize("case", _pairs("identifier_tokenization"))
def test_identifier_tokenization_vector(case: dict[str, Any]) -> None:
    """A letter-leading token containing digits ("p50") is an identifier, not a value."""
    finding = detect_conflict(case["left"], case["right"])
    assert (finding is not None) is case["conflict"], (
        f"expected conflict={case['conflict']}\n"
        f"  left:  {case['left']}\n  right: {case['right']}\n  got: {finding}"
    )


def test_detection_is_symmetric() -> None:
    """Every pairwise vector must hold with the arguments swapped.

    A port that only reproduces one argument order has not reproduced the
    contract: post-fusion candidates are compared in an arbitrary order.
    """
    for bucket in _PAIR_BUCKETS:
        for case in VECTORS[bucket]:
            swapped = detect_conflict(case["right"], case["left"])
            assert (swapped is not None) is case["conflict"], (
                f"{bucket}/{case['label']}: asymmetric verdict\n"
                f"  left:  {case['left']}\n  right: {case['right']}"
            )
