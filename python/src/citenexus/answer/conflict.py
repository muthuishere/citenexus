"""Deterministic conflict detection and near-duplicate collapse (ADR-0007).

Two questions asked of the *same* post-fusion candidate set, by the same pairwise
comparison:

* **Do two grounded passages disagree?** — surfaced, never resolved. Resolution
  is a policy decision that belongs to the caller and to authority (ADR-0004); a
  library that silently picks a winner is today's bug with more machinery.
* **Are two grounded passages the same passage twice?** — collapsed, so
  ``distinct_documents`` stops counting mirrors as independent corroboration.

Both are pure, offline and model-free: set arithmetic plus one RE2-clean number
pattern. ADR-0010 tier 1 (native per port) over tier-2 tables in
``answer/tables.py``.

**The number that matters is the false-conflict rate, not recall.** In strict
mode a detected conflict abstains, so a false conflict is a false refusal, while
a missed conflict merely leaves today's behaviour in place. Every rule below is
built to decline rather than decide, and the guard that actually holds the rate
down is ``MAX_RESIDUAL``: see its comment.

Order is load-bearing. **Conflict is checked before duplication.** A one-word
change is a duplicate only when that word is neither a value nor a polarity
marker; getting this backwards would collapse a contradiction into a
corroboration, which is the worst outcome this change could produce.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from citenexus.answer.tables import (
    CONFLICT_ANTONYMS,
    CONFLICT_NEGATIONS,
    CONFLICT_REPORT_BIGRAMS,
    CONFLICT_SCOPE_MARKERS,
    MEASUREMENT_UNITS,
)
from citenexus.answer.verify import _STOPWORDS
from citenexus.tokenize import tokenize

__all__ = [
    "CONFLICT_TOP_K",
    "ConflictFinding",
    "ConflictPair",
    "collapse_near_duplicates",
    "describe_conflicts",
    "detect_conflict",
    "find_conflicts",
    "is_near_duplicate",
]

# ─────────────────────────────────────────────────────────────────────────────
# Pinned constants. None of these are exposed as caller parameters: a conformance
# vector cannot pin a value the caller controls, and every one of them trades
# directly against false abstention.
# ─────────────────────────────────────────────────────────────────────────────

#: Content-token overlap coefficient required before two passages are treated as
#: being about the same subject at all.
SUBJECT_OVERLAP = 0.60

#: Total content divergence allowed before the pair is simply unrelated.
MAX_SYMDIFF = 3

#: Content divergence allowed *after* removing the polarity signal itself.
#:
#: This one guard does nearly all the work. Two passages that genuinely disagree
#: are otherwise word-identical; two that merely look like they disagree differ
#: by exactly one further content word — the scope (adults/children), the route
#: (oral/intravenous), the environment (staging/production), the metric
#: (p50/p99) — and that word is what makes them complementary. The ADR-0007 spike
#: swept it:
#:
#:     residual  recall  false-conflict rate
#:       0        0.89   0.00
#:       1        0.89   0.00
#:       2        0.93   0.15   <- +4pp recall costs 15pp FALSE ABSTENTION
#:       3        0.93   0.19
#:
#: Relaxing it by one token is a 15-point mistake. It is a pinned constant.
MAX_RESIDUAL = 1

#: Passages with fewer content tokens than this are not comparable.
MIN_CONTENT = 3

#: Token-set Jaccard at which two same-polarity, same-valued passages are treated
#: as surface clones of each other.
DUPLICATE_JACCARD = 0.80

#: Length difference (in tokens) still allowed for a surface clone.
DUPLICATE_MAX_LENGTH_DELTA = 2

#: How many post-fusion candidates are compared pairwise. O(k²) on a small k.
CONFLICT_TOP_K = 6

# A digit-LEADING token ("500mg", "2019") is a measured value and belongs to the
# numeric rule. A letter-leading token containing digits ("p50", "ipv4", "sec4")
# is an IDENTIFIER and must stay in the content set — it is frequently the only
# thing distinguishing two otherwise-identical passages. Getting this backwards
# produced the spike's only false conflict ("The p50 latency budget is 200 ms" vs
# "The p99 latency budget is 900 ms"), because the digit filter ate the one word
# that told them apart.
_MEASUREMENT_RE = re.compile(r"^[0-9]+[a-z]*$")

# RE2-compatible: no lookaround, no backreferences, no backtracking. The
# letter-boundary check that RE2 would need lookbehind for is done in code below,
# precisely so this pattern ports unchanged.
_NUMBER_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*([a-z]+|%)?")

_ANTONYMS: frozenset[tuple[str, str]] = frozenset(
    pair for a, b in CONFLICT_ANTONYMS for pair in ((a, b), (b, a))
)


def _fold(token: str) -> str:
    """Fold a regular English plural / third-person -s onto its base form.

    The pinned SPEC-PORTS-v1 tokenizer does **not** stem, and this does not
    change it: folding happens inside the comparison only, and no other gate sees
    it. Without it, morphology alone defeats the residual guard on true
    contradictions that are otherwise word-identical — "requires"/"require",
    "conserves"/"conserve", "attract"/"attracts" — each counting as a divergence
    that is not a divergence.

    Deliberately one rule, not a stemmer: a single trailing ``s``, never on short
    tokens and never after ``s``/``u``/``i`` (``class``, ``status``, ``analysis``).
    A stemmer would merge genuinely different words and every such merge is a
    false conflict.
    """
    if len(token) >= 4 and token.endswith("s") and token[-2] not in "siu":
        return token[:-1]
    return token


def _fold_all(tokens: Iterable[str]) -> frozenset[str]:
    return frozenset(_fold(t) for t in tokens)


_FOLDED_ANTONYMS: frozenset[tuple[str, str]] = frozenset((_fold(a), _fold(b)) for a, b in _ANTONYMS)
_FOLDED_SCOPE: frozenset[str] = _fold_all(CONFLICT_SCOPE_MARKERS)


@dataclass(frozen=True)
class _Features:
    """Everything the pairwise rules need from one passage."""

    tokens: tuple[str, ...]
    content: frozenset[str]  # folded, meaning-bearing, non-numeric, non-polarity
    negations: int
    numbers: frozenset[str]
    units: frozenset[str]
    reported: bool  # carries a reported-speech bigram


@dataclass(frozen=True)
class ConflictFinding:
    """Why two passages were judged to disagree. Never says which one is right."""

    rule: str  # "antonym" | "negation" | "value"
    detail: str


@dataclass(frozen=True)
class ConflictPair:
    """A detected conflict between two candidates, by position in the sequence."""

    left: int
    right: int
    finding: ConflictFinding

    def describe(self, left_document: str, right_document: str) -> str:
        """The one-line form written to ``Result.conflicts``."""
        return f"{self.finding.rule}: {left_document} vs {right_document} ({self.finding.detail})"


def _normalize_number(raw: str) -> str:
    value = raw.replace(",", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


def _features(text: str) -> _Features:
    lowered = text.lower()
    tokens = tuple(tokenize(lowered))
    numbers: set[str] = set()
    units: set[str] = set()
    for match in _NUMBER_RE.finditer(lowered):
        start = match.start(1)
        if start > 0 and (lowered[start - 1].isalpha() or lowered[start - 1] == "_"):
            continue  # "p50", "ipv4": an identifier, not a measured value
        numbers.add(_normalize_number(match.group(1)))
        unit = match.group(2)
        if unit == "%":
            units.add("%")
        elif unit and unit in MEASUREMENT_UNITS:
            units.add(unit)
    # Stopwords and negations are matched on the RAW token, before folding: the
    # fold is a comparison aid, not a normalizer, and folding first would turn
    # "does" into "doe" and smuggle a stopword into the content set.
    content = {
        _fold(token)
        for token in tokens
        if token not in _STOPWORDS
        and token not in CONFLICT_NEGATIONS
        and not _MEASUREMENT_RE.match(token)
    }
    reported = any(
        (tokens[i], tokens[i + 1]) in CONFLICT_REPORT_BIGRAMS for i in range(len(tokens) - 1)
    )
    return _Features(
        tokens=tokens,
        content=frozenset(content),
        negations=sum(1 for t in tokens if t in CONFLICT_NEGATIONS),
        numbers=frozenset(numbers),
        units=frozenset(units),
        reported=reported,
    )


def detect_conflict(left: str, right: str) -> ConflictFinding | None:
    """Deterministic pairwise contradiction test. ``None`` means "no conflict".

    Pure and total: no model, no network, no I/O, no configuration.
    """
    a, b = _features(left), _features(right)
    if min(len(a.content), len(b.content)) < MIN_CONTENT:
        return None  # too short to compare honestly

    shared = a.content & b.content
    overlap = len(shared) / min(len(a.content), len(b.content))
    if overlap < SUBJECT_OVERLAP:
        return None  # not the same subject

    divergence = (a.content | b.content) - shared
    if len(divergence) > MAX_SYMDIFF:
        return None

    if divergence & _FOLDED_SCOPE:
        return None  # differently scoped -> complementary, not contradictory

    if a.reported or b.reported:
        return None  # a quoted negation belongs to a third party

    for x in sorted(a.content - b.content):
        for y in sorted(b.content - a.content):
            if (x, y) in _FOLDED_ANTONYMS and len(divergence - {x, y}) <= MAX_RESIDUAL:
                return ConflictFinding("antonym", f"{x} vs {y}")

    if (a.negations % 2) != (b.negations % 2) and len(divergence) <= MAX_RESIDUAL:
        return ConflictFinding("negation", f"{a.negations} vs {b.negations} negations")

    if a.numbers and b.numbers and a.numbers != b.numbers:
        elaboration = a.numbers <= b.numbers or b.numbers <= a.numbers
        if not elaboration and a.units == b.units and len(divergence) <= MAX_RESIDUAL:
            return ConflictFinding(
                "value",
                f"{', '.join(sorted(a.numbers))} vs {', '.join(sorted(b.numbers))}",
            )

    return None


def is_near_duplicate(left: str, right: str) -> str | None:
    """Collapse reason if the two are SURFACE CLONES, else ``None``.

    This claims one thing and not another. It detects the same passage appearing
    twice — identical token sequence, or a near-identical one of equal length,
    equal numbers and equal negation parity. It does **not** measure evidential
    independence, and cannot: "the same fact restated" and "the same source
    paraphrased" are both semantic equivalence with lexical divergence, so a
    textual detector sees one signal with two causes. What a caller actually
    wants from ``distinct_documents`` is a fact about *provenance*, not text —
    two independent auditors can write the same sentence, and one source can be
    quoted in twenty documents in twenty phrasings.

    So it is biased to UNDER-collapse. A word-order paraphrase is left standing.
    Under-collapsing leaves ``distinct_documents`` as inflated as it is today;
    over-collapsing would under-report real corroboration, a new wrong signal.
    """
    if detect_conflict(left, right) is not None:
        return None  # conflict first, always: a contradiction is never a clone
    left_tokens, right_tokens = tokenize(left), tokenize(right)
    if left_tokens == right_tokens:
        return "exact"  # covers whitespace, punctuation and case variants
    a, b = _features(left), _features(right)
    if a.numbers != b.numbers or a.negations % 2 != b.negations % 2:
        return None
    left_set, right_set = set(left_tokens), set(right_tokens)
    union = left_set | right_set
    if not union:
        return None
    jaccard = len(left_set & right_set) / len(union)
    if (
        jaccard >= DUPLICATE_JACCARD
        and abs(len(left_tokens) - len(right_tokens)) <= DUPLICATE_MAX_LENGTH_DELTA
    ):
        return f"near ({jaccard:.2f})"
    return None


def describe_conflicts(pairs: Sequence[ConflictPair], documents: Sequence[str]) -> tuple[str, ...]:
    """One line per conflict, naming both documents and neither as the winner."""
    return tuple(pair.describe(documents[pair.left], documents[pair.right]) for pair in pairs)


def find_conflicts(
    passages: Sequence[str], *, top_k: int = CONFLICT_TOP_K
) -> tuple[ConflictPair, ...]:
    """All conflicting pairs within the first ``top_k`` passages."""
    window = list(passages)[:top_k]
    pairs: list[ConflictPair] = []
    for i in range(len(window)):
        for j in range(i + 1, len(window)):
            finding = detect_conflict(window[i], window[j])
            if finding is not None:
                pairs.append(ConflictPair(left=i, right=j, finding=finding))
    return tuple(pairs)


def collapse_near_duplicates(passages: Sequence[str]) -> tuple[int, ...]:
    """Indices of the passages that survive surface-clone collapse, in order."""
    kept: list[int] = []
    for index, text in enumerate(passages):
        if any(is_near_duplicate(text, passages[k]) for k in kept):
            continue
        kept.append(index)
    return tuple(kept)
