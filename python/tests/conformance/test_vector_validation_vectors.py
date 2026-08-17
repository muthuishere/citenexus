"""``conformance/cases/vector_validation.json``, asserted as a BINDING contract.

This is the cross-port definition of **a valid embedding batch** (ADR-0010
tier 1: native in Python, Go and JS, no Rust, no native library). It exists
because the three ports did not agree:

* **Python validated nothing.** ``embed_texts`` returned whatever a provider
  handed back, so a batch that returned fewer vectors than texts shifted every
  subsequent text→vector pairing. Measured on the shipped
  ``OpenAICompatibleEmbedding`` + the shipped ``IngestPipeline``: three of four
  queries then retrieved the *wrong* passage, with no error, no warning, and a
  perfectly healthy-looking row count.
* **Go rejected** empty / dimension / all-zero.
* **JS rejected** those **plus non-finite** — so two ports pinned "byte-for-byte
  identical" disagreed about what a valid vector even is.

The vectors here are read as **opaque data**. Nothing in this module re-derives
an expectation by calling the code under test: a test that asks the
implementation what it does can only ever agree with it, and that is precisely
how this class of bug survived. ``valid`` and ``reason`` are the contract; the
shipped functions are held to them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from citenexus.contracts import check_batch_arity, check_vector

_CASES = (
    Path(__file__).resolve().parents[2].parent / "conformance" / "cases" / "vector_validation.json"
)

VECTORS: dict[str, Any] = json.loads(_CASES.read_text(encoding="utf-8"))

#: Case counts, pinned EXACTLY. A floor (``> 0``) lets a shrunken file pass
#: silently, which is the hole this suite exists to keep shut: every bucket is a
#: distinct failure mode, and one silently dropped is a weakened contract that no
#: per-case assertion can see.
EXPECTED_COUNTS: dict[str, int] = {
    "check_vector": 29,
    "non_vector": 10,
    "batch_arity": 9,
}

#: JSON has no NaN/Infinity literal, so the fixture spells them as these tokens.
_NON_FINITE = {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}


def _decode(component: Any) -> float:
    """Decode one fixture component — a number, or a pinned non-finite token."""
    if isinstance(component, str):
        return _NON_FINITE[component]
    return float(component)


def _classify(exc: Exception) -> str:
    """Map a raised error back to the contract's rejection vocabulary.

    This reads the *message the port produces*; it never asks the implementation
    for a verdict. A port whose message does not name the rule it applied cannot
    be held to the rejection ORDER, which is half of this contract.
    """
    message = str(exc)
    if "non-vector" in message:
        return "non_vector"
    if "empty vector" in message:
        return "empty"
    if "-dim vector" in message:
        return "dimension"
    if "non-finite" in message:
        return "non_finite"
    if "zero vector" in message:
        return "zero"
    if "vectors for" in message:
        return "cardinality"
    raise AssertionError(f"error message names no rejection rule: {message!r}")


def _params(bucket: str) -> list[Any]:
    return [pytest.param(case, id=f"{bucket}-{case['name']}") for case in VECTORS[bucket]]


def test_bucket_names_and_sizes() -> None:
    assert set(VECTORS) == {*EXPECTED_COUNTS, "reason_order", "non_finite_tokens"}
    assert {k: len(VECTORS[k]) for k in EXPECTED_COUNTS} == EXPECTED_COUNTS
    assert sum(EXPECTED_COUNTS.values()) == 48


def test_case_names_are_unique_within_a_bucket() -> None:
    for bucket in EXPECTED_COUNTS:
        names = [case["name"] for case in VECTORS[bucket]]
        assert len(set(names)) == len(names), f"duplicate case name in {bucket}"


def test_reason_order_is_pinned() -> None:
    """The order rejections are applied in — part of the contract, not incidental."""
    assert VECTORS["reason_order"] == [
        "non_vector",
        "empty",
        "dimension",
        "non_finite",
        "zero",
    ]
    assert VECTORS["non_finite_tokens"] == ["NaN", "Infinity", "-Infinity"]


def test_every_rejection_rule_is_exercised() -> None:
    """Coverage is asserted, not hoped for.

    A bucket can shrink to only its happy cases and every per-case assertion
    still passes. This makes that visible.
    """
    reasons = {case["reason"] for case in VECTORS["check_vector"] if not case["valid"]}
    assert reasons == {"empty", "dimension", "non_finite", "zero"}
    assert any(case["valid"] for case in VECTORS["check_vector"])
    assert any(not case["valid"] for case in VECTORS["batch_arity"])
    assert any(case["valid"] for case in VECTORS["batch_arity"])


@pytest.mark.parametrize("case", _params("check_vector"))
def test_check_vector_vectors(case: dict[str, Any]) -> None:
    vector = [_decode(c) for c in case["vector"]]
    if case["valid"]:
        assert case["reason"] is None
        assert check_vector(case["name"], vector, case["dim"]) == vector
        return
    with pytest.raises((TypeError, ValueError)) as excinfo:
        check_vector(case["name"], vector, case["dim"])
    assert _classify(excinfo.value) == case["reason"]
    # The rejection must name the offending unit, never just the run — a
    # corpus-wide "bad vector" tells an operator nothing about which EU to fix.
    assert case["name"] in str(excinfo.value)


@pytest.mark.parametrize("case", _params("non_vector"))
def test_non_vector_payloads(case: dict[str, Any]) -> None:
    """Payloads that are not numeric arrays at all.

    Kept in a bucket of their own because Go's ``[]float64`` makes them
    unrepresentable — its replay asserts the bucket's shape instead of executing
    it. Python and JS both take ``any`` from an untyped provider and must refuse.
    """
    assert case["valid"] is False
    assert case["reason"] == "non_vector"
    with pytest.raises(TypeError) as excinfo:
        check_vector(case["name"], case["vector"], case["dim"])
    assert _classify(excinfo.value) == "non_vector"


@pytest.mark.parametrize("case", _params("batch_arity"))
def test_batch_arity_vectors(case: dict[str, Any]) -> None:
    """One vector per input text, in input order — the rule Python missed.

    This is the most damaging of the five, because it is the only one whose
    failure leaves the index *plausibly* wrong: every downstream signal (row
    count, score distribution, citation coverage) still looks healthy.
    """
    if case["valid"]:
        assert case["reason"] is None
        check_batch_arity(case["texts"], case["vectors"])
        return
    with pytest.raises(ValueError) as excinfo:
        check_batch_arity(case["texts"], case["vectors"])
    assert _classify(excinfo.value) == case["reason"]
    assert str(case["texts"]) in str(excinfo.value)
    assert str(case["vectors"]) in str(excinfo.value)
