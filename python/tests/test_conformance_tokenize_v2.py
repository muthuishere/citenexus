"""Python runs the per-script golden fixtures for the Unicode tokenizer.

ADR-0011: **no script may be claimed as supported without a golden fixture**, so
the claim (``SUPPORTED_SCRIPTS``) and the evidence for it
(``conformance/cases/tokenize_v2.json``) are checked against each other here.
This test loads the COMMITTED fixture and runs the real runtime functions — the
same contract the Go and JS ports must satisfy — so a regression in the
reference tokenizer is caught here, not only in the ports.
"""

from __future__ import annotations

import json
from pathlib import Path

from citenexus.answer.verify import is_supported_v2
from citenexus.tokenize import (
    CONTINUOUS_SCRIPTS,
    SUPPORTED_SCRIPTS,
    TOKENIZER_VERSION,
    tokenize,
    tokenize_v2,
    unsupported_scripts,
)

_FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "conformance" / "cases" / "tokenize_v2.json").read_text(
        encoding="utf-8"
    )
)


def test_fixture_pins_the_tokenizer_version() -> None:
    assert _FIXTURE["tokenizer_version"] == TOKENIZER_VERSION


def test_claimed_scripts_and_fixture_agree() -> None:
    """The claim and its evidence are the same artifact, or neither is trusted."""
    assert sorted(SUPPORTED_SCRIPTS) == _FIXTURE["supported_scripts"]
    assert sorted(CONTINUOUS_SCRIPTS) == _FIXTURE["continuous_scripts"]
    assert {case["script"] for case in _FIXTURE["supported"]} == SUPPORTED_SCRIPTS


def test_every_claimed_script_tokenizes() -> None:
    for case in _FIXTURE["supported"]:
        assert tokenize_v2(case["text"]) == case["tokens"], case["script"]
        assert case["tokens"], case["script"]


def test_v1_defect_stays_pinned() -> None:
    """v1 must not be 'fixed' — the ports and the shipped vectors depend on it."""
    for case in _FIXTURE["supported"]:
        assert tokenize(case["text"]) == case["v1_tokens"], case["script"]


def test_every_claimed_script_supports_a_verbatim_quote_of_its_own_source() -> None:
    for case in _FIXTURE["supported"]:
        assert case["self_supported"] is True, case["script"]
        assert is_supported_v2(case["text"], case["text"]) is True, case["script"]


def test_no_claimed_script_turns_the_gate_into_a_rubber_stamp() -> None:
    unrelated = _FIXTURE["unrelated_passage"]
    for case in _FIXTURE["supported"]:
        assert case["unrelated_supported"] is False, case["script"]
        assert is_supported_v2(case["text"], unrelated) is False, case["script"]


def test_claimed_scripts_report_no_capability_gap() -> None:
    for case in _FIXTURE["supported"]:
        assert unsupported_scripts(case["text"]) == (), case["script"]
        assert case["unsupported_scripts"] == []


def test_unclaimed_scripts_are_reported_as_a_capability_gap() -> None:
    assert _FIXTURE["unclaimed"], "the unclaimed half of the matrix must not be empty"
    for case in _FIXTURE["unclaimed"]:
        assert case["script"] not in SUPPORTED_SCRIPTS
        assert list(unsupported_scripts(case["text"])) == case["unsupported_scripts"]
        assert case["unsupported_scripts"] == [case["script"]]


def test_unicode_mechanics_vectors() -> None:
    for case in _FIXTURE["unicode"]:
        assert tokenize_v2(case["input"]) == case["tokens"], case["input"]
