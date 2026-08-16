"""Faithfulness and relevance gates for grounded answers (spec §11, §12).

The v0.1 verifier is deliberately extractive: a generated claim is accepted only
when every content token appears in the cited passage. This is conservative, but
it proves the "no ungrounded claim" contract offline and gives later judge/model
plugins a stable seam to improve precision without weakening the guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass

from citenexus.answer.tables import POLARITY_MARKERS
from citenexus.tokenize import tokenize, tokenize_v2

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
    """True when question and passage share at least one content token.

    FROZEN alongside ``is_supported`` — pinned by the shipped conformance
    vectors. The answer path uses ``has_relevance_overlap_v2``.
    """
    return bool(content_tokens(question) & content_tokens(passage))


def content_tokens_v2(text: str) -> set[str]:
    """``content_tokens`` over the Unicode tokenizer (ADR-0011).

    The stopword table stays English-only and stays applied unconditionally: it
    is a fixed 44-word list of ASCII words, so it is a no-op on tokens from any
    other script and cannot silently strip meaning there.
    """
    return set(tokenize_v2(text)) - _STOPWORDS


def has_relevance_overlap_v2(question: str, passage: str) -> bool:
    """True when question and passage share at least one Unicode content token.

    Under v1 this returned ``False`` for every non-Latin script — both sides
    tokenized to the empty set — so the relevance gate abstained before the
    faithfulness gate ever ran. The abstention was over-determined; this is one
    of the two places it came from.
    """
    return bool(content_tokens_v2(question) & content_tokens_v2(passage))


def is_supported(answer: str, passage: str) -> bool:
    """Every answer token must appear in the cited passage.

    FROZEN (SPEC-PORTS-v1 §4). Kept byte-identical so the shipped conformance
    vectors and the Go/JS ports continue to pass unchanged. Known unsound — see
    ``is_supported_v2``, which supersedes it on the answer path.
    """
    answer_tokens = set(tokenize(answer))
    passage_tokens = set(tokenize(passage))
    return bool(answer_tokens) and answer_tokens <= passage_tokens


# ─────────────────────────────────────────────────────────────────────────────
# ADR-0009 — ordered containment with a polarity guard.
#
# ``is_supported`` is set containment, and set containment is closed under two
# meaning-changing operations: reordering (inverting the parties to an
# obligation is a token-set identity) and deletion (``not`` is a token, so
# dropping a negation yields a strict subset). Measured in
# spikes/library-stress/: nine false answers accepted 9/9, identically in
# Python, Go and JS.
#
# The replacement requires the claim's tokens to appear IN ORDER within a
# bounded interior gap, and requires any polarity marker inside the matched
# span to survive into the claim. It is strictly narrower than
# ``is_supported`` — anything it accepts, the frozen predicate accepted — so it
# can only reduce what passes.
# ─────────────────────────────────────────────────────────────────────────────

# Pinned, not configurable. A caller who widens the budget silently weakens the
# guarantee, and a conformance vector cannot pin a value the caller controls.
# The spike swept the budget and found the knee at (3, 6); (4, 8) leaves
# headroom for compressed answers. The attacks are insensitive to it — they
# fail on order, not on gap size.
MAX_SINGLE_GAP = 4
MAX_TOTAL_GAP = 8


@dataclass(frozen=True)
class Alignment:
    """Where a claim matched inside a passage, in token indices."""

    start: int  # index of the first matched passage token
    end: int  # index of the last matched passage token (inclusive)
    total_gap: int  # passage tokens skipped strictly inside the span
    max_gap: int  # the largest single skip inside the span


def align(
    claim_tokens: list[str],
    passage_tokens: list[str],
    *,
    max_single_gap: int = MAX_SINGLE_GAP,
    max_total_gap: int = MAX_TOTAL_GAP,
) -> Alignment | None:
    """Minimal-gap ordered alignment of ``claim_tokens`` into ``passage_tokens``.

    Returns the alignment minimising total interior gap, or ``None`` when the
    claim is not an order- and multiplicity-preserving subsequence of the
    passage within the gap budget.

    An O(len(claim) * len(passage)) integer dynamic programme. No regex, no
    recursion — it ports to Go (RE2) and JS unchanged.
    """
    if not claim_tokens or not passage_tokens:
        return None

    n, m = len(claim_tokens), len(passage_tokens)
    # state[j] = best (total_gap, max_gap, start) for a claim prefix ending at j
    state: list[tuple[int, int, int] | None] = [None] * m

    # The claim's first token may start anywhere it occurs.
    for j in range(m):
        if passage_tokens[j] == claim_tokens[0]:
            state[j] = (0, 0, j)

    for i in range(1, n):
        nxt: list[tuple[int, int, int] | None] = [None] * m
        best: tuple[int, int, int] | None = None  # running best over k < j
        best_k = -1
        for j in range(m):
            # fold position j-1 into the running best before using it for j
            prev = state[j - 1] if j > 0 else None
            if prev is not None and (best is None or prev[0] < best[0]):
                best, best_k = prev, j - 1
            if passage_tokens[j] != claim_tokens[i] or best is None:
                continue
            gap = j - best_k - 1
            if gap > max_single_gap:
                continue
            total = best[0] + gap
            if total > max_total_gap:
                continue
            nxt[j] = (total, max(best[1], gap), best[2])
        state = nxt
        if all(s is None for s in state):
            return None

    finals = [(s, j) for j, s in enumerate(state) if s is not None]
    if not finals:
        return None
    (total, mx, start), end = min(finals, key=lambda t: (t[0][0], t[1]))
    return Alignment(start=start, end=end, total_gap=total, max_gap=mx)


def _polarity_preserved(
    claim_tokens: list[str], passage_tokens: list[str], span: Alignment
) -> bool:
    """Every polarity marker inside the matched span survives into the claim.

    Multiplicity matters: dropping one of two negations flips the meaning just
    as completely as dropping the only one.
    """
    matched = passage_tokens[span.start : span.end + 1]
    for tok in set(matched) & POLARITY_MARKERS:
        if claim_tokens.count(tok) < matched.count(tok):
            return False
    return True


def is_supported_v2(answer: str, passage: str) -> bool:
    """Order- and multiplicity-aware containment, plus the polarity guard.

    Pure, deterministic, offline. Strictly narrower than ``is_supported``.
    """
    claim_tokens, passage_tokens = tokenize_v2(answer), tokenize_v2(passage)
    span = align(claim_tokens, passage_tokens)
    if span is None:
        return False
    return _polarity_preserved(claim_tokens, passage_tokens, span)
