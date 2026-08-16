"""The §11a answer-language chain + a code-mixing flag (spec §11, §11a).

The answer-language invariant (§11) returns the answer in the **query's**
language. Until 2026-08-16 the chain did not implement that: its fourth rung
derived the answer language from the retrieved **evidence**, which is a
corpus-shaped signal wearing §11's name. Measured on ``examples/multilingual/``,
that stamped 8 English questions ``te`` and 7 more ``ta`` — 15 of 22 — and
``search_languages`` fan-out (ADR-0013) was about to make it worse by design,
since a fan-out deliberately pulls foreign-language passages into the pool.

The rule is now **explicit, with a dumb default**:

1. an explicit ``answer_language`` — the caller's word outranks the classifier;
2. a **reliable** detection of the QUESTION — reached through the ``"auto"``
   sentinel (see `resolve_requested_answer_language`), or by a caller passing a
   ``detection`` directly, which is what ingest's document-language stamp does;
3. an established ``conversation_language``;
4. the configured ``default_answer_language``.

``languages_in_evidence`` is still accepted and is **ignored**. It stays in the
signature so the Go / JS / Rust ports and the conformance vectors keep an
identical argument list — the port diff is a verdict diff, not an API diff — and
so a vector can assert that a pool full of Telugu changes nothing. Evidence
languages remain REPORTED on ``EvidenceSignals.languages_in_evidence``: they are
an observation, never an input.

BREAKING: this is a pinned algorithm with conformance vectors in
``conformance/cases/language.json``.
"""

from __future__ import annotations

from collections.abc import Sequence

from citenexus.lang.detect import LanguageResult
from citenexus.plugins import LanguageDetectorPlugin

# The one value of ``answer_language`` that is not a language: "detect it from my
# question". It never reaches `resolve_answer_language` and is never returned.
AUTO_ANSWER_LANGUAGE = "auto"


def resolve_answer_language(
    *,
    detection: LanguageResult | None,
    answer_language: str | None = None,
    conversation_language: str | None = None,
    languages_in_evidence: Sequence[str] | None = None,
    default_answer_language: str = "en",
) -> str:
    """Pick the answer language by the §11a chain (question only).

    Order:
    1. explicit ``answer_language``;
    2. a reliable ``detection`` of the question;
    3. established ``conversation_language``;
    4. configured ``default_answer_language``.

    ``languages_in_evidence`` is accepted and ignored (see the module docstring).
    """
    del languages_in_evidence  # accepted for signature stability; never read.
    if answer_language and answer_language != AUTO_ANSWER_LANGUAGE:
        return answer_language
    if detection is not None and detection.is_reliable:
        return detection.language
    if conversation_language:
        return conversation_language
    return default_answer_language


def resolve_requested_answer_language(
    question: str,
    answer_language: str | None,
    *,
    detector: LanguageDetectorPlugin | None = None,
    conversation_language: str | None = None,
    default_answer_language: str = "en",
) -> str:
    """Resolve a caller's ``answer_language`` request, understanding ``"auto"``.

    This is the flow-facing half of the chain — the half that knows about the
    detector, and therefore the only place the sentinel is meaningful. Detection
    runs on the QUESTION and only when the caller asked for it: an unspecified
    ``answer_language`` is a fixed default, not a quiet inference.

    A detector that fails (the real one downloads ``lid.176`` on first use) falls
    through to the rest of the chain. A capability failure in the detector must
    not take the answer down with it, and the fallback is the same predictable
    default a caller would get with no detector at all.
    """
    detection: LanguageResult | None = None
    if answer_language == AUTO_ANSWER_LANGUAGE and detector is not None and question.strip():
        try:
            detection = detector.detect(question)
        except Exception:  # pragma: no cover - defensive; see docstring
            detection = None
    return resolve_answer_language(
        detection=detection,
        answer_language=answer_language,
        conversation_language=conversation_language,
        default_answer_language=default_answer_language,
    )


def flag_code_mixing(candidates: Sequence[tuple[str, float]], *, strong: float = 0.40) -> bool:
    """True when the top-2 language candidates are both strong (code-mixed).

    When two languages both clear ``strong`` there is no single reliable label, so
    the caller should fall through the §11a chain rather than trust the top-1.
    Input order is irrelevant — the top two are taken by probability.
    """
    if len(candidates) < 2:
        return False
    top_two = sorted(candidates, key=lambda c: c[1], reverse=True)[:2]
    return all(prob >= strong for _lang, prob in top_two)
