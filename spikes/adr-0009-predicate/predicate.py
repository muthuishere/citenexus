"""ADR-0009 candidate predicates and claim segmenters (spike, throwaway).

Kept in its own module so the pytest shadow plugin can import it without
dragging in the report harness.

Everything here is pure, deterministic, offline, and uses only regex features
that RE2 (Go) and JS RegExp both support: literal alternation, character
classes, `+`, `*`. No lookaround, no backreferences, no possessive/atomic
groups, no named Unicode property escapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from citenexus.tokenize import tokenize

# ─────────────────────────────────────────────────────────────────────────────
# Tier-2 data: polarity markers. ADR-0010 says this is a canonical table in
# conformance/, generated into each port. This is the spike's stand-in.
# Deliberately small and closed: only tokens whose *deletion* flips a claim.
# ─────────────────────────────────────────────────────────────────────────────

POLARITY_MARKERS = frozenset(
    {
        # English
        "not", "no", "never", "without", "unless", "except", "neither", "nor",
        "cannot", "nothing", "none", "nobody", "fails", "failed", "absent",
        "prohibited", "forbidden", "denied", "excluding", "other",
        # Dutch
        "niet", "geen", "nooit", "zonder", "tenzij", "noch",
        # German
        "nicht", "kein", "keine", "keinen", "nie", "ohne", "weder",
        # French / Spanish (cheap wins, same shape)
        "ne", "pas", "aucun", "sans", "sauf", "sin", "ningun", "ninguna",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# The alignment core: order- and multiplicity-aware containment.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Alignment:
    start: int          # index of first matched passage token
    end: int            # index of last matched passage token (inclusive)
    total_gap: int      # passage tokens skipped strictly inside the span
    max_gap: int        # largest single skip inside the span


def align(
    claim_tokens: list[str],
    passage_tokens: list[str],
    *,
    max_single_gap: int,
    max_total_gap: int,
) -> Alignment | None:
    """Minimal-gap ordered alignment of `claim_tokens` into `passage_tokens`.

    Returns the alignment minimising total interior gap, or None if the claim
    is not an order- and multiplicity-preserving subsequence of the passage
    within the gap budget.

    O(len(claim) * len(passage)) dynamic programme; no regex, no recursion.
    Ports trivially to Go and JS.
    """
    if not claim_tokens or not passage_tokens:
        return None

    n, m = len(claim_tokens), len(passage_tokens)
    # state[j] = best (total_gap, max_gap, start) for a prefix ending at j.
    NEG = None
    state: list[tuple[int, int, int] | None] = [NEG] * m

    # i = 0: the claim's first token may start anywhere it occurs.
    for j in range(m):
        if passage_tokens[j] == claim_tokens[0]:
            state[j] = (0, 0, j)

    for i in range(1, n):
        nxt: list[tuple[int, int, int] | None] = [NEG] * m
        best: tuple[int, int, int] | None = None  # running best over k < j
        best_k = -1
        for j in range(m):
            # fold position j-1 into the running best before using it for j
            if j > 0 and state[j - 1] is not None:
                cand = state[j - 1]
                assert cand is not None
                if best is None or cand[0] < best[0]:
                    best, best_k = cand, j - 1
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
    """Every polarity marker inside the matched passage span must survive in
    the claim, with at least the same multiplicity."""
    for tok in set(passage_tokens[span.start : span.end + 1]) & POLARITY_MARKERS:
        need = passage_tokens[span.start : span.end + 1].count(tok)
        if claim_tokens.count(tok) < need:
            return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# The predicate variants under test.
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MAX_SINGLE_GAP = 4
DEFAULT_MAX_TOTAL_GAP = 8


def is_supported_v0(claim: str, passage: str) -> bool:
    """The shipped predicate: unordered set containment (answer/verify.py:73)."""
    a, p = set(tokenize(claim)), set(tokenize(passage))
    return bool(a) and a <= p


def is_supported_contiguous(claim: str, passage: str) -> bool:
    """Variant B: the claim must be a *contiguous* token run of the passage."""
    ct, pt = tokenize(claim), tokenize(passage)
    return align(ct, pt, max_single_gap=0, max_total_gap=0) is not None


def is_supported_ordered_only(claim: str, passage: str) -> bool:
    """Variant C: gapped ordered containment, NO polarity rule.

    Exists only to measure whether the polarity table is load-bearing.
    """
    ct, pt = tokenize(claim), tokenize(passage)
    return (
        align(
            ct, pt,
            max_single_gap=DEFAULT_MAX_SINGLE_GAP,
            max_total_gap=DEFAULT_MAX_TOTAL_GAP,
        )
        is not None
    )


def is_supported_v2(
    claim: str,
    passage: str,
    *,
    max_single_gap: int = DEFAULT_MAX_SINGLE_GAP,
    max_total_gap: int = DEFAULT_MAX_TOTAL_GAP,
) -> bool:
    """ADR-0009's proposal: order-and-multiplicity-aware containment plus a
    polarity-preservation rule over the matched span.

    Pure, deterministic, no model, no network, no regex beyond the pinned
    tokenizer. Strictly narrower than `is_supported`.
    """
    ct, pt = tokenize(claim), tokenize(passage)
    span = align(ct, pt, max_single_gap=max_single_gap, max_total_gap=max_total_gap)
    if span is None:
        return False
    return _polarity_preserved(ct, pt, span)


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 — claim segmentation.
# ─────────────────────────────────────────────────────────────────────────────

# The splitter that ships today (answer/agentic.py:53).
_SHIPPED_RE = re.compile(r"[.!?\n]+")


def split_shipped(text: str) -> list[str]:
    return [s.strip() for s in _SHIPPED_RE.split(text) if s.strip()]


# Tier-2 data for the improved splitter: terminators and abbreviations.
TERMINATORS = ".!?。！？؟۔।॥‼⁇⁈⁉"
_TERM_CLASS = "[" + re.escape(TERMINATORS) + "]"
_ABBREVIATIONS = frozenset(
    {
        # English / Dutch / German honorifics + legal citation forms
        "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "no", "vs", "etc",
        "e.g", "i.e", "eg", "ie", "cf", "al", "fig", "art", "sec", "para",
        "nr", "bv", "dhr", "mevr", "resp", "vgl", "bzw", "ggf", "usw", "zb",
        "abs", "ziff",
    }
)
# Digits either side of a terminator = a decimal, never a break. RE2-safe.
_DECIMAL = re.compile(r"[0-9]" + _TERM_CLASS + r"[0-9]")


def split_guarded(text: str) -> list[str]:
    """Deterministic, table-driven sentence splitter — tier 1 code + tier 2 data.

    Rules, in order, all local to the break candidate:
      1. break after a run of terminators;
      2. not if the terminator sits between two digits (decimals, "5.00");
      3. not if the token immediately before the terminator is a known
         abbreviation, or a single letter (initials: "J. Smith");
      4. a following space is NOT required (CJK writes "。" with no space).
    """
    out: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        buf.append(ch)
        if ch in TERMINATORS:
            # consume a run of terminators ("?!", "...")
            while i + 1 < n and text[i + 1] in TERMINATORS:
                i += 1
                buf.append(text[i])
            nxt = text[i + 1] if i + 1 < n else ""
            chunk = "".join(buf)
            # rule 2 — decimal
            if _DECIMAL.search(text[max(0, i - 1) : i + 2]):
                i += 1
                continue
            # rule 3 — abbreviation / initial
            # NOTE: explicit class, not `\s` — Go's RE2 `\s` is ASCII-only while
            # Python's is Unicode-aware. Spelling it out keeps the ports identical.
            word = re.split(r"[ \t\n\r\f\v 　]", chunk.rstrip(TERMINATORS))[-1].lower()
            if word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
                i += 1
                continue
            # rule 4 — a break needs whitespace-or-EOL after it for scripts that
            # use spaces; CJK/Arabic terminators break unconditionally.
            if nxt and nxt not in " \n\t　" and ch in ".!?":
                i += 1
                continue
            out.append(chunk.strip())
            buf = []
        i += 1
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return [s for s in out if s]
