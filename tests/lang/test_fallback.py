"""The §11a answer-language fallback chain + code-mixing flag (spec §11a)."""

from __future__ import annotations

from citenexus.lang import (
    LanguageResult,
    flag_code_mixing,
    resolve_answer_language,
)

_RELIABLE_DE = LanguageResult(language="de", confidence=0.95, is_reliable=True)
_UNRELIABLE = LanguageResult(language="en", confidence=0.30, is_reliable=False)


def test_reliable_detection_wins() -> None:
    # Even with every other signal present, a reliable detection short-circuits.
    out = resolve_answer_language(
        detection=_RELIABLE_DE,
        answer_language="fr",
        conversation_language="es",
        languages_in_evidence=["ta", "ta"],
        default_answer_language="en",
    )
    assert out == "de"


def test_unreliable_falls_to_explicit_override() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language="fr",
        conversation_language="es",
        languages_in_evidence=["ta"],
        default_answer_language="en",
    )
    assert out == "fr"


def test_no_override_falls_to_conversation_language() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language=None,
        conversation_language="es",
        languages_in_evidence=["ta"],
        default_answer_language="en",
    )
    assert out == "es"


def test_no_conversation_falls_to_evidence_dominant() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=["ta", "ta", "en"],
        default_answer_language="en",
    )
    assert out == "ta"


def test_nothing_else_falls_to_default() -> None:
    out = resolve_answer_language(
        detection=_UNRELIABLE,
        answer_language=None,
        conversation_language=None,
        languages_in_evidence=None,
        default_answer_language="en",
    )
    assert out == "en"


def test_missing_detection_falls_through_chain() -> None:
    # No detection at all behaves like an unreliable one.
    out = resolve_answer_language(
        detection=None,
        answer_language=None,
        conversation_language="ja",
        default_answer_language="en",
    )
    assert out == "ja"


def test_code_mixing_two_strong_candidates_flagged() -> None:
    assert flag_code_mixing([("en", 0.55), ("ta", 0.44)], strong=0.40) is True


def test_code_mixing_single_dominant_not_flagged() -> None:
    assert flag_code_mixing([("en", 0.95), ("fr", 0.03)], strong=0.40) is False


def test_code_mixing_unsorted_input_is_handled() -> None:
    # Order should not matter — the helper inspects the top two by probability.
    assert flag_code_mixing([("ta", 0.44), ("en", 0.55)], strong=0.40) is True


def test_code_mixing_single_candidate_not_flagged() -> None:
    assert flag_code_mixing([("en", 0.99)], strong=0.40) is False
