"""`answer_language` through the public client: explicit, or a dumb default.

BREAKING, 2026-08-16 (`explicit-answer-language`). Measured on
`examples/multilingual/`: 8 English questions came back stamped
`answer_language="te"` and 7 more `"ta"` — 15 of 22 — because the §11a chain
derived the answer language from the retrieved evidence. §11 says the answer
follows the QUERY, and the owner's ruling is that the caller states it:

    ask(q)                        -> the configured default. Predictable.
    ask(q, answer_language="auto") -> detected from the QUESTION.
    ask(q, answer_language="ta")   -> Tamil, unconditionally.

`search_languages` fan-out would have made the old behaviour worse, not better:
it deliberately pulls foreign-language passages into the pool.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.lang.detect import HeuristicDetector
from citenexus.plugins import LanguageDetectorPlugin
from citenexus.testing import FakeEmbedding, FakeLLM

_EN_DOC = "Employees may carry forward a maximum of 10 days of unused leave."
_TE_DOC = "ఉద్యోగులు గరిష్టంగా 5 రోజుల సెలవును మాత్రమే బదిలీ చేయవచ్చు."
_TA_DOC = "ஊழியர் ரகசியத் தகவலை மூன்றாம் தரப்பினருக்கு வெளியிடக் கூடாது."
# `HeuristicDetector` maps the dominant script to a plausible ISO code, so a
# kanji-heavy Japanese sentence classifies as `zh` (both are HAN). Cyrillic is
# unambiguous, which is what a detector assertion needs.
_RU_DOC = "Сотрудник может перенести не более десяти дней неиспользованного отпуска."

_Q_EN = "How many days of unused leave can employees carry forward?"
_Q_RU = "Сколько дней неиспользованного отпуска сотрудник может перенести?"


def _rag(
    tmp_path: Path,
    *,
    detector: LanguageDetectorPlugin | None = None,
    default: str = "en",
) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        detector=detector,
        default_answer_language=default,
    )


# --------------------------------------------------------------------------- #
# Unspecified: a fixed, predictable default — never an inference
# --------------------------------------------------------------------------- #


def test_unspecified_is_the_configured_default(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    assert rag.ask(_Q_EN).answer_language == "en"


def test_the_measured_defect_no_longer_reproduces(tmp_path: Path) -> None:
    """An English question over a Telugu-dominant corpus is no longer stamped `te`."""
    rag = _rag(tmp_path)
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    for i in range(3):
        rag.ingest(text=_TE_DOC, document_id=f"annexure-te-{i}")
    assert rag.ask(_Q_EN).answer_language == "en"


def test_unspecified_does_not_move_with_the_corpus(tmp_path: Path) -> None:
    """The whole point of a dumb default: ingest cannot change the answer language."""
    rag = _rag(tmp_path)
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    before = rag.ask(_Q_EN).answer_language
    rag.ingest(text=_TA_DOC, document_id="policy-ta")
    rag.ingest(text=_TE_DOC, document_id="annexure-te")
    assert rag.ask(_Q_EN).answer_language == before == "en"


def test_unspecified_ignores_a_detector_entirely(tmp_path: Path) -> None:
    """A configured detector is for `"auto"`; unspecified must not silently infer."""
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_RU_DOC, document_id="handbook-ru")
    assert rag.ask(_Q_RU).answer_language == "en"


def test_the_default_is_configurable(tmp_path: Path) -> None:
    rag = _rag(tmp_path, default="hi")
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    assert rag.ask(_Q_EN).answer_language == "hi"


# --------------------------------------------------------------------------- #
# "auto": detect from the QUESTION
# --------------------------------------------------------------------------- #


def test_auto_detects_the_question_language(tmp_path: Path) -> None:
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_RU_DOC, document_id="handbook-ru")
    assert rag.ask(_Q_RU, answer_language="auto").answer_language == "ru"


def test_auto_detects_the_question_not_the_evidence(tmp_path: Path) -> None:
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    for i in range(3):
        rag.ingest(text=_TE_DOC, document_id=f"annexure-te-{i}")
    assert rag.ask(_Q_EN, answer_language="auto").answer_language == "en"


def test_auto_without_a_detector_falls_to_the_default(tmp_path: Path) -> None:
    rag = _rag(tmp_path, default="hi")
    rag.ingest(text=_RU_DOC, document_id="handbook-ru")
    assert rag.ask(_Q_RU, answer_language="auto").answer_language == "hi"


def test_auto_is_not_treated_as_a_language_code(tmp_path: Path) -> None:
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    assert rag.ask(_Q_EN, answer_language="auto").answer_language != "auto"


def test_auto_and_unspecified_now_differ(tmp_path: Path) -> None:
    """They used to be aliases. `"auto"` now means something `None` does not."""
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_RU_DOC, document_id="handbook-ru")
    assert rag.ask(_Q_RU).answer_language == "en"
    assert rag.ask(_Q_RU, answer_language="auto").answer_language == "ru"


# --------------------------------------------------------------------------- #
# Explicit: unconditional
# --------------------------------------------------------------------------- #


def test_an_explicit_language_is_forced(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    assert rag.ask(_Q_EN, answer_language="fr").answer_language == "fr"


def test_an_explicit_language_beats_a_reliable_detection(tmp_path: Path) -> None:
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_RU_DOC, document_id="handbook-ru")
    assert rag.ask(_Q_RU, answer_language="fr").answer_language == "fr"


def test_an_explicit_language_beats_the_corpus(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_TE_DOC, document_id="annexure-te")
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    assert rag.ask(_Q_EN, answer_language="ta").answer_language == "ta"


def test_citations_stay_verbatim_whatever_the_answer_language(tmp_path: Path) -> None:
    """Unaffected by this change, and asserted so it stays that way."""
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_RU_DOC, document_id="handbook-ru")
    for language in (None, "auto", "fr", "en"):
        result = rag.ask(_Q_RU, answer_language=language)
        if result.evidence.decision is Decision.answered:
            assert result.sources[0].passage == _RU_DOC


# --------------------------------------------------------------------------- #
# The deep strategy must agree — a guarantee that holds on one strategy is none
# --------------------------------------------------------------------------- #


def test_deep_strategy_agrees_on_unspecified(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    rag.ingest(text=_TE_DOC, document_id="annexure-te")
    strict = rag.ask(_Q_EN)
    deep = rag.ask(_Q_EN, strategy="deep")
    assert strict.answer_language == deep.answer_language == "en"


def test_deep_strategy_agrees_on_explicit(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    assert rag.ask(_Q_EN, answer_language="fr", strategy="deep").answer_language == "fr"


def test_deep_strategy_agrees_on_auto(tmp_path: Path) -> None:
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_RU_DOC, document_id="handbook-ru")
    assert rag.ask(_Q_RU, answer_language="auto", strategy="deep").answer_language == "ru"


def test_deep_strategy_never_returns_the_sentinel(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    assert rag.ask(_Q_EN, answer_language="auto", strategy="deep").answer_language != "auto"


# --------------------------------------------------------------------------- #
# stream() rides the same rule
# --------------------------------------------------------------------------- #


def test_stream_uses_the_same_resolution(tmp_path: Path) -> None:
    rag = _rag(tmp_path, detector=HeuristicDetector())
    rag.ingest(text=_EN_DOC, document_id="handbook-en")
    rag.ingest(text=_TE_DOC, document_id="annexure-te")
    assert rag.stream(_Q_EN) == rag.stream(_Q_EN, answer_language=None)
