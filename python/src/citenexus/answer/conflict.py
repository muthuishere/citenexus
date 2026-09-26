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
from fractions import Fraction

from citenexus.answer.numbers import numbers_in
from citenexus.answer.tables import (
    CONFLICT_ANTONYMS,
    CONFLICT_INCLUSION_PAIRS,
    CONFLICT_NEGATIONS,
    CONFLICT_REPORT_BIGRAMS,
    CONFLICT_SCOPE_MARKERS,
    MEASUREMENT_UNITS,
    VAT_MARKERS,
    VAT_RATES,
)
from citenexus.answer.verify import _STOPWORDS

# v2, not v1. The frozen v1 tokenizer is ASCII-only by contract
# (``tokenize.py:77``), so every non-Latin passage collapsed to its digits alone:
# a Tamil or Telugu contradiction produced fewer than ``MIN_CONTENT`` content
# tokens and ``detect_conflict`` returned "no conflict" before a single rule ran.
# A one-sided, confidently-cited answer over a corpus that contains both sides is
# the exact failure ADR-0007 exists to prevent, so conflict runs on the
# Unicode-aware tokenizer (ADR-0011). Every English vector committed before the
# swap is unchanged by it — measured over the whole suite, not assumed.
from citenexus.tokenize import tokenize_v2

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

# ...and the identifier exception is ASCII, for the same reason the letter
# boundary in ``_features`` is. ``tokenize_v2`` emits CHARACTER BIGRAMS for CJK, so
# 「通知期間は30日です。」 tokenizes as は3 / 30 / 日, and its 60-day counterpart as
# は6 / 60 / 日. ``_MEASUREMENT_RE`` correctly drops the bare 30 and 60, but は3
# and は6 are letter-leading-with-digit, so the identifier exception kept BOTH in
# the content set — a two-token divergence manufactured out of one number, which
# is above ``MAX_RESIDUAL`` and kills the value rule that the number itself would
# have fired. A mixed-script token carrying an ASCII digit is a tokenizer
# artifact, never an identifier: the identifiers the exception exists for
# ("p50", "ipv4") are ASCII by construction.
_ASCII_DIGITS = frozenset("0123456789")


def _is_tokenizer_digit_artifact(token: str) -> bool:
    """True for a digit-bearing token that is not pure ASCII (a CJK bigram)."""
    return any(c in _ASCII_DIGITS for c in token) and any(c > "\x7f" for c in token)


# RE2-compatible: no lookaround, no backreferences, no backtracking. The
# letter-boundary check that RE2 would need lookbehind for is done in code below,
# precisely so this pattern ports unchanged.

# The letter-boundary guard applied to those matches (``numbers.numbers_in``) is
# LATIN-ONLY, deliberately, and this is the one place the two facts have to be
# held together:
#
# * the identifiers it protects are ASCII by construction — "p50", "p99",
#   "ipv4", "ipv6", "sec4", "http2". The text is already lowercased where the
#   check runs, so ``a``-``z`` covers every ASCII letter that can reach it, and
#   the digits it guards are the ASCII ``[0-9]`` the pattern itself matched;
# * ``str.isalpha()`` / ``unicode.IsLetter`` / ``\p{L}`` are also TRUE for kana,
#   kanji and Han. Japanese and Chinese do not put spaces around numbers, so in
#   「通知期間は30日です。」 the kana は sits flush against the 3, the number was
#   discarded as an "identifier", ``numbers`` came back empty, and the value rule
#   never ran. The SAME sentence with a non-letter separator (「通知期間: 30日」)
#   did fire — measured. Two of the world's largest written languages were inert
#   for the one conflict rule that is otherwise script-independent, which is
#   exactly the one-sided-answer failure ADR-0007 exists to prevent.
#
# Narrowing to ASCII keeps every identifier case working (they are all ASCII)
# and lets CJK numbers parse. It also widens the value rule to any other script
# that writes a letter flush against a digit; that is the intended direction —
# the guard exists to protect ASCII identifiers, not to suppress non-Latin text.
# (``numbers.is_identifier_prefix``; shared with the VerifyAnswer guards.)

_ANTONYMS: frozenset[tuple[str, str]] = frozenset(
    pair for a, b in CONFLICT_ANTONYMS for pair in ((a, b), (b, a))
)


def _fold(token: str) -> str:
    """Fold a regular English plural / third-person -s onto its base form.

    The pinned tokenizer (v2, ADR-0011) does **not** stem, and this does not
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

#: (inclusive, exclusive) marker pairs, folded, in BOTH orientations with the
#: inclusive word first in the value, so a hit also says which side is which.
_INCLUSION: dict[tuple[str, str], str] = {}
for _incl, _excl in CONFLICT_INCLUSION_PAIRS:
    _INCLUSION[(_fold(_incl), _fold(_excl))] = "left-inclusive"
    _INCLUSION[(_fold(_excl), _fold(_incl))] = "right-inclusive"

_VAT_MARKERS: frozenset[str] = frozenset(VAT_MARKERS)
_VAT_RATES: tuple[Fraction, ...] = tuple(Fraction(rate) for rate in VAT_RATES)
#: One cent: the rounding a VAT-inclusive price quoted to the cent can carry.
_VAT_TOLERANCE = Fraction(1, 100)


@dataclass(frozen=True)
class _Features:
    """Everything the pairwise rules need from one passage."""

    tokens: tuple[str, ...]
    content: frozenset[str]  # folded, meaning-bearing, non-numeric, non-polarity
    negations: int
    numbers: frozenset[str]  # comparison keys (numbers.read_number)
    values: dict[str, Fraction | None]  # key -> value, None when ambiguous
    units: frozenset[str]
    reported: bool  # carries a reported-speech bigram


@dataclass(frozen=True)
class ConflictFinding:
    """Why two passages were judged to disagree. Never says which one is right."""

    rule: str  # "inclusion" | "antonym" | "negation" | "value"
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


def _features(text: str, language: str | None = None) -> _Features:
    lowered = text.lower()
    tokens = tuple(tokenize_v2(lowered))
    values: dict[str, Fraction | None] = {}
    units: set[str] = set()
    # "p50", "ipv4" are identifiers, not measured values; "€ 4 000" is 4000.
    for match in numbers_in(lowered, language):
        values[match.reading.key] = match.reading.value
        unit = match.unit
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
        and not _is_tokenizer_digit_artifact(token)
    }
    reported = any(
        (tokens[i], tokens[i + 1]) in CONFLICT_REPORT_BIGRAMS for i in range(len(tokens) - 1)
    )
    return _Features(
        tokens=tokens,
        content=frozenset(content),
        negations=sum(1 for t in tokens if t in CONFLICT_NEGATIONS),
        numbers=frozenset(values),
        values=values,
        units=frozenset(units),
        reported=reported,
    )


def _vat_consistent(inclusive: _Features, exclusive: _Features) -> bool:
    """True when the two amounts are one price quoted excl. and incl. VAT.

    Exactly one amount differs on each side, both have a single reading, and
    ``exclusive * rate`` is within one cent of ``inclusive`` for a tabled rate.
    Anything else — several differing amounts, an ambiguous one, another rate —
    is NOT consistent, and the difference stays a conflict.
    """
    only_incl = inclusive.numbers - exclusive.numbers
    only_excl = exclusive.numbers - inclusive.numbers
    if len(only_incl) != 1 or len(only_excl) != 1 or inclusive.units != exclusive.units:
        return False
    incl_value = inclusive.values[next(iter(only_incl))]
    excl_value = exclusive.values[next(iter(only_excl))]
    if incl_value is None or excl_value is None:
        return False
    return any(abs(excl_value * rate - incl_value) <= _VAT_TOLERANCE for rate in _VAT_RATES)


def _inclusion_verdict(
    a: _Features, b: _Features, x: str, y: str, orientation: str
) -> ConflictFinding | None:
    """ADR-0015: one passage says incl, the other excl, on the same subject.

    * same amounts (or none) -> conflict: the price cannot be both;
    * different amounts, a VAT marker present, and consistent under a tabled
      VAT rate -> NOT a conflict: the same price quoted both ways;
    * any other difference -> conflict. There is no "numbers differ, so decline"
      branch: for a legal reader that would fail open.
    """
    inclusive, exclusive = (a, b) if orientation == "left-inclusive" else (b, a)
    if a.numbers == b.numbers:
        amounts = ", ".join(sorted(a.numbers))
        return ConflictFinding("inclusion", f"{x} vs {y}" + (f" on {amounts}" if amounts else ""))
    # The decline also requires equal negation parity: "€ 100 excl" vs "NOT
    # € 121 incl" is VAT-consistent in its amounts and still a disagreement. The
    # negation rule cannot catch it afterwards (the incl/excl words already use
    # up the residual), so declining here would fail open.
    vat = any(t in _VAT_MARKERS for t in a.tokens + b.tokens)
    same_polarity = a.negations % 2 == b.negations % 2
    if vat and same_polarity and _vat_consistent(inclusive, exclusive):
        return None
    return ConflictFinding("inclusion", f"{_side(x, a)} vs {_side(y, b)}")


def _side(word: str, features: _Features) -> str:
    """``inclusief 121`` — the marker plus its amounts, if it has any."""
    amounts = ", ".join(sorted(features.numbers))
    return f"{word} {amounts}" if amounts else word


def detect_conflict(
    left: str,
    right: str,
    *,
    left_language: str | None = None,
    right_language: str | None = None,
) -> ConflictFinding | None:
    """Deterministic pairwise contradiction test. ``None`` means "no conflict".

    Pure and total: no model, no network, no I/O, no configuration. The optional
    languages are the passages' DECLARED languages; they only decide how a
    locale-ambiguous number such as ``1.500`` is read (ADR-0015). Undeclared, it
    is ambiguous and equal to nothing but itself.
    """
    a, b = _features(left, left_language), _features(right, right_language)
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

    # Inclusion runs BEFORE the value rule and owns its verdict, including a
    # decline: a VAT-consistent excl/incl pair must not then be called a value
    # conflict for carrying two different amounts.
    for x in sorted(a.content - b.content):
        for y in sorted(b.content - a.content):
            orientation = _INCLUSION.get((x, y))
            if orientation is not None and len(divergence - {x, y}) <= MAX_RESIDUAL:
                return _inclusion_verdict(a, b, x, y, orientation)

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


def is_near_duplicate(
    left: str,
    right: str,
    *,
    left_language: str | None = None,
    right_language: str | None = None,
) -> str | None:
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
    if (
        detect_conflict(left, right, left_language=left_language, right_language=right_language)
        is not None
    ):
        return None  # conflict first, always: a contradiction is never a clone
    left_tokens, right_tokens = tokenize_v2(left), tokenize_v2(right)
    if left_tokens == right_tokens:
        return "exact"  # covers whitespace, punctuation and case variants
    a, b = _features(left, left_language), _features(right, right_language)
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


def _language_at(languages: Sequence[str | None] | None, index: int) -> str | None:
    if languages is None or index >= len(languages):
        return None
    return languages[index]


def find_conflicts(
    passages: Sequence[str],
    *,
    top_k: int = CONFLICT_TOP_K,
    languages: Sequence[str | None] | None = None,
) -> tuple[ConflictPair, ...]:
    """All conflicting pairs within the first ``top_k`` passages.

    ``languages`` are the passages' declared languages, index-aligned; they only
    decide how locale-ambiguous numbers are read (ADR-0015).
    """
    window = list(passages)[:top_k]
    pairs: list[ConflictPair] = []
    for i in range(len(window)):
        for j in range(i + 1, len(window)):
            finding = detect_conflict(
                window[i],
                window[j],
                left_language=_language_at(languages, i),
                right_language=_language_at(languages, j),
            )
            if finding is not None:
                pairs.append(ConflictPair(left=i, right=j, finding=finding))
    return tuple(pairs)


def collapse_near_duplicates(
    passages: Sequence[str], *, languages: Sequence[str | None] | None = None
) -> tuple[int, ...]:
    """Indices of the passages that survive surface-clone collapse, in order."""
    kept: list[int] = []
    for index, text in enumerate(passages):
        if any(
            is_near_duplicate(
                text,
                passages[k],
                left_language=_language_at(languages, index),
                right_language=_language_at(languages, k),
            )
            for k in kept
        ):
            continue
        kept.append(index)
    return tuple(kept)
