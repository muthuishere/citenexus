"""The §11a answer-language chain + code-mixing flag (spec §11a).

BREAKING, 2026-08-16 (`explicit-answer-language`): the chain is now
**explicit-first with a dumb default**, and the evidence-dominant rung is gone.

Measured on `examples/multilingual/`: deriving the answer language from the
retrieved evidence stamped 8 English questions `te` and 7 more `ta` out of 22.
§11 says the answer follows the QUERY, so the corpus no longer gets a vote.
"""

from __future__ import annotations

from citenexus.lang import (
    LanguageResult,
    flag_code_mixing,
    resolve_answer_language,
)

_RELIABLE_DE = LanguageResult(language="de", confidence=0.95, is_reliable=True)
_RELIABLE_TA = LanguageResult(language="ta", confidence=0.99, is_reliable=True)
_UNRELIABLE = LanguageResult(language="en", confidence=0.30, is_reliable=False)


# --------------------------------------------------------------------------- #
# Rung 1 — the caller's word outranks everything, classifier included
# --------------------------------------------------------------------------- #


def test_explicit_override_beats_a_reliable_detection() -> None:
    # BREAKING: this used to return "de". A caller who typed a language code has
    # stated an intent no classifier outranks.
    out = resolve_answer_language(
        detection=_RELIABLE_DE,
        answer_language="fr",
        conversation_language="es",
        languages_in_evidence=["ta", "ta"],
        default_answer_language="en",
    )
    assert out == "fr"


def test_explicit_override_beats_every_other_signal() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language="ta",
        conversation_language="es",
        languages_in_evidence=["te", "te", "te"],
        default_answer_language="hi",
    )
    assert out == "ta"


def test_an_empty_override_is_not_an_override() -> None:
    # "" is not a language code; it must not shadow the rest of the chain.
    out = resolve_answer_language(
        detection=_RELIABLE_DE,
        answer_language="",
        default_answer_language="en",
    )
    assert out == "de"


# --------------------------------------------------------------------------- #
# Rung 2 — a reliable detection, reached only when nothing is explicit
# --------------------------------------------------------------------------- #


def test_reliable_detection_used_when_nothing_is_explicit() -> None:
    out = resolve_answer_language(
        detection=_RELIABLE_TA,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=["en", "en"],
        default_answer_language="en",
    )
    assert out == "ta"


def test_reliable_detection_beats_the_conversation_language() -> None:
    out = resolve_answer_language(
        detection=_RELIABLE_DE,
        answer_language=None,
        conversation_language="es",
        default_answer_language="en",
    )
    assert out == "de"


def test_unreliable_detection_is_not_used() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language=None,
        conversation_language=None,
        default_answer_language="hi",
    )
    assert out == "hi"


# --------------------------------------------------------------------------- #
# Rung 3 — the established conversation language
# --------------------------------------------------------------------------- #


def test_no_override_and_no_detection_falls_to_conversation_language() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language=None,
        conversation_language="es",
        languages_in_evidence=["ta"],
        default_answer_language="en",
    )
    assert out == "es"


def test_missing_detection_falls_through_chain() -> None:
    out = resolve_answer_language(
        detection=None,
        answer_language=None,
        conversation_language="ja",
        default_answer_language="en",
    )
    assert out == "ja"


# --------------------------------------------------------------------------- #
# The removed rung — evidence is an observation, never an input
# --------------------------------------------------------------------------- #


def test_evidence_languages_are_ignored() -> None:
    # BREAKING: this used to return "ta".
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=["ta", "ta", "en"],
        default_answer_language="en",
    )
    assert out == "en"


def test_the_measured_defect_no_longer_reproduces() -> None:
    # The real case: an English question about leave carry-forward, answered off
    # a Telugu-dominant pool, came back stamped `te`.
    out = resolve_answer_language(
        detection=None,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=["te", "te", "te", "ta"],
        default_answer_language="en",
    )
    assert out == "en"


def test_an_evidence_tie_is_ignored_too() -> None:
    # BREAKING: this used to return "fr" (first-seen wins on a tie).
    out = resolve_answer_language(
        detection=None,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=["fr", "en", "fr", "en"],
        default_answer_language="en",
    )
    assert out == "en"


def test_evidence_cannot_override_the_conversation_language() -> None:
    out = resolve_answer_language(
        detection=None,
        answer_language=None,
        conversation_language="de",
        languages_in_evidence=["te"] * 20,
        default_answer_language="en",
    )
    assert out == "de"


def test_an_empty_evidence_list_and_a_full_one_agree() -> None:
    kwargs = {
        "detection": None,
        "answer_language": None,
        "conversation_language": None,
        "default_answer_language": "en",
    }
    assert resolve_answer_language(languages_in_evidence=[], **kwargs) == (  # type: ignore[arg-type]
        resolve_answer_language(languages_in_evidence=["ta", "te"], **kwargs)  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Rung 4 — the dumb default
# --------------------------------------------------------------------------- #


def test_nothing_else_falls_to_default() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=None,
        default_answer_language="en",
    )
    assert out == "en"


def test_the_default_is_configurable() -> None:
    out = resolve_answer_language(
        detection=None,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=None,
        default_answer_language="hi",
    )
    assert out == "hi"


# --------------------------------------------------------------------------- #
# The ingest call shape must keep working (ingest/pipeline.py::_detect_language)
# --------------------------------------------------------------------------- #


def test_ingest_call_shape_still_uses_a_reliable_detection() -> None:
    assert (
        resolve_answer_language(detection=_RELIABLE_TA, default_answer_language="en") == "ta"
    )


def test_ingest_call_shape_falls_to_default_on_an_unreliable_detection() -> None:
    assert resolve_answer_language(detection=_UNRELIABLE, default_answer_language="en") == "en"


# --------------------------------------------------------------------------- #
# Code-mixing flag (unchanged)
# --------------------------------------------------------------------------- #


def test_code_mixing_two_strong_candidates_flagged() -> None:
    assert flag_code_mixing([("en", 0.55), ("ta", 0.44)], strong=0.40) is True


def test_code_mixing_single_dominant_not_flagged() -> None:
    assert flag_code_mixing([("en", 0.95), ("fr", 0.03)], strong=0.40) is False


def test_code_mixing_unsorted_input_is_handled() -> None:
    # Order should not matter — the helper inspects the top two by probability.
    assert flag_code_mixing([("ta", 0.44), ("en", 0.55)], strong=0.40) is True


def test_code_mixing_single_candidate_not_flagged() -> None:
    assert flag_code_mixing([("en", 0.99)], strong=0.40) is False
