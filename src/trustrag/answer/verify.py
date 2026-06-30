"""Faithfulness and relevance gates for grounded answers (spec §11, §12).

The v0.1 verifier is deliberately extractive: a generated claim is accepted only
when every content token appears in the cited passage. This is conservative, but
it proves the "no ungrounded claim" contract offline and gives later judge/model
plugins a stable seam to improve precision without weakening the guarantee.
"""

from __future__ import annotations

from trustrag.testing.fakes import tokenize

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "could",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "may",
        "much",
        "no",
        "not",
        "of",
        "on",
        "or",
        "shall",
        "should",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    }
)


def content_tokens(text: str) -> set[str]:
    """Meaning-bearing tokens used by relevance and faithfulness gates."""
    return set(tokenize(text)) - _STOPWORDS


def has_relevance_overlap(question: str, passage: str) -> bool:
    """True when question and passage share at least one content token."""
    return bool(content_tokens(question) & content_tokens(passage))


def is_supported(answer: str, passage: str) -> bool:
    """Every answer token must appear in the cited passage."""
    answer_tokens = set(tokenize(answer))
    passage_tokens = set(tokenize(passage))
    return bool(answer_tokens) and answer_tokens <= passage_tokens
