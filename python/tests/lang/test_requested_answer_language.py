"""The `"auto"` sentinel: detect from the QUESTION, never from the evidence.

`resolve_requested_answer_language` is the flow-facing half of the chain — it is
where the detector lives, so it is the only place `"auto"` is understood. The
pinned, conformance-vectored `resolve_answer_language` never sees the sentinel.
"""

from __future__ import annotations

from citenexus.lang import (
    AUTO_ANSWER_LANGUAGE,
    LanguageResult,
    resolve_requested_answer_language,
)
from citenexus.lang.detect import HeuristicDetector
from citenexus.plugins import LanguageDetectorPlugin

_JA = "従業員は機密情報を開示してはならない。"
# `HeuristicDetector` maps the dominant unicode script to a plausible ISO code,
# so a kanji-heavy Japanese sentence classifies as `zh` (both are HAN). Cyrillic
# is unambiguous, which is what a detector assertion needs.
_RU = "Сотрудник не должен раскрывать конфиденциальную информацию."
_EN = "Can the employee disclose confidential information?"


class _Fixed(LanguageDetectorPlugin):
    """A detector that always returns the same verdict."""

    def __init__(self, language: str, confidence: float) -> None:
        self.result = LanguageResult(
            language=language, confidence=confidence, is_reliable=confidence >= 0.5
        )
        self.calls: list[str] = []

    def detect(self, text: str) -> LanguageResult:
        self.calls.append(text)
        return self.result


class _Exploding(LanguageDetectorPlugin):
    def detect(self, text: str) -> LanguageResult:
        raise RuntimeError("model download failed")


def test_sentinel_is_the_literal_auto() -> None:
    assert AUTO_ANSWER_LANGUAGE == "auto"


def test_auto_detects_from_the_question() -> None:
    detector = _Fixed("ja", 0.99)
    out = resolve_requested_answer_language(
        _JA, AUTO_ANSWER_LANGUAGE, detector=detector, default_answer_language="en"
    )
    assert out == "ja"
    assert detector.calls == [_JA]


def test_auto_with_the_real_heuristic_detector() -> None:
    out = resolve_requested_answer_language(
        _RU, "auto", detector=HeuristicDetector(), default_answer_language="en"
    )
    assert out == "ru"


def test_the_real_detector_is_not_consulted_when_unspecified() -> None:
    out = resolve_requested_answer_language(
        _RU, None, detector=HeuristicDetector(), default_answer_language="en"
    )
    assert out == "en"


def test_auto_falls_to_the_default_when_detection_is_unreliable() -> None:
    out = resolve_requested_answer_language(
        _EN, "auto", detector=_Fixed("ta", 0.10), default_answer_language="en"
    )
    assert out == "en"


def test_auto_falls_to_the_default_without_a_detector() -> None:
    out = resolve_requested_answer_language(
        _JA, "auto", detector=None, default_answer_language="en"
    )
    assert out == "en"


def test_auto_falls_to_the_default_when_the_detector_raises() -> None:
    # A capability failure in the detector must not take the answer down with it:
    # the fallback is the dumb default, not an exception.
    out = resolve_requested_answer_language(
        _JA, "auto", detector=_Exploding(), default_answer_language="en"
    )
    assert out == "en"


def test_auto_is_never_returned_as_a_language() -> None:
    detectors: list[LanguageDetectorPlugin | None] = [None, _Fixed("ja", 0.99), _Fixed("ta", 0.1)]
    for detector in detectors:
        out = resolve_requested_answer_language(_EN, "auto", detector=detector)
        assert out != "auto"


def test_auto_prefers_the_conversation_language_over_the_default() -> None:
    out = resolve_requested_answer_language(
        _EN,
        "auto",
        detector=_Fixed("ta", 0.1),
        conversation_language="de",
        default_answer_language="en",
    )
    assert out == "de"


def test_unspecified_never_calls_the_detector() -> None:
    # The whole point: `None` is a fixed, predictable default — not an inference.
    detector = _Fixed("ja", 0.99)
    out = resolve_requested_answer_language(
        _JA, None, detector=detector, default_answer_language="en"
    )
    assert out == "en"
    assert detector.calls == []


def test_an_explicit_code_never_calls_the_detector() -> None:
    detector = _Fixed("ja", 0.99)
    out = resolve_requested_answer_language(
        _JA, "fr", detector=detector, default_answer_language="en"
    )
    assert out == "fr"
    assert detector.calls == []


def test_an_empty_question_under_auto_falls_to_the_default() -> None:
    detector = _Fixed("ja", 0.99)
    out = resolve_requested_answer_language(
        "   ", "auto", detector=detector, default_answer_language="en"
    )
    assert out == "en"
    assert detector.calls == []
