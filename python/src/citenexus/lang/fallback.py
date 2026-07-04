"""The §11a answer-language fallback chain + a code-mixing flag (spec §11, §11a).

The answer-language invariant (§11) returns the answer in the query's language.
That language is decided by `resolve_answer_language` over the **short query
only**: a reliable detection is used directly, and an unreliable one (the common
case for a 3-word query, where `lid.176` is least confident) drops through an
explicit ordered chain of fallback signals. Documents are never re-detected here;
their per-EU languages enter only as the evidence-dominant link.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from citenexus.lang.detect import LanguageResult


def resolve_answer_language(
    *,
    detection: LanguageResult | None,
    answer_language: str | None = None,
    conversation_language: str | None = None,
    languages_in_evidence: Sequence[str] | None = None,
    default_answer_language: str = "en",
) -> str:
    """Pick the answer language by the §11a chain (short query only).

    Order:
    1. reliable detection of the query language;
    2. explicit ``answer_language`` override;
    3. established ``conversation_language``;
    4. dominant language among ``languages_in_evidence``;
    5. configured ``default_answer_language``.
    """
    if detection is not None and detection.is_reliable:
        return detection.language
    if answer_language:
        return answer_language
    if conversation_language:
        return conversation_language
    if languages_in_evidence:
        # `Counter.most_common` is stable for equal counts (insertion order),
        # so ties resolve to the first-seen evidence language — deterministic.
        return Counter(languages_in_evidence).most_common(1)[0][0]
    return default_answer_language


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
