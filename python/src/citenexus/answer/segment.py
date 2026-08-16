"""Guarded claim segmentation (ADR-0009, ADR-0010 tier 1).

An answer is decomposed into atomic claims so each can be verified against its
cited passage independently. Splitting on punctuation alone is not good enough:
the naive ``[.!?\\n]+`` splitter that ships at ``answer/agentic.py`` failed 54.2%
of the spike's six-language cases — abbreviations, decimals and CJK terminators
all break it.

This splitter is tier-1 scanning code over the tier-2 tables in ``tables.py``.
Adding ``。！？`` to the *table* fixed 100% of the Japanese failures with no
algorithm change, which is why claim segmentation stays native per port rather
than moving to the Rust core. The two residual failures the spike could not fix
(``"The U.S. Army"`` vs ``"…at 5 p.m. She left."``, and Thai) are cases UAX #29
does not resolve either — the standard calls the first a required tailoring and
defers the second to dictionary breaking.

Portability notes, both load-bearing for the Go and JS ports:

- ``re.escape`` emits ``\\!``, which is a **compile error** in Go's RE2. Character
  classes here are written literally, never escaped.
- ``\\s`` is Unicode-aware in Python but ASCII-only in RE2. Whitespace is spelled
  out explicitly so the ports cannot diverge.
"""

# The fullwidth terminators and the NBSP / ideographic space below are the
# subject of this module, not typos — ruff's ambiguous-character lint is noise here.
# ruff: noqa: RUF001, RUF002

from __future__ import annotations

from citenexus.answer.tables import ABBREVIATIONS, TERMINATORS

__all__ = ["split_claims"]

# Spelled out rather than `\s` — see the module docstring.
_WHITESPACE = " \t\n\r\f\v 　"

# Terminators that require whitespace (or end-of-text) after them to count as a
# break. CJK and Arabic/Indic terminators break unconditionally, because those
# scripts do not put a space after the mark.
_NEEDS_TRAILING_SPACE = ".!?"


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _preceding_word(buffer: list[str]) -> str:
    """The token immediately before the terminator run, lowercased."""
    text = "".join(buffer).rstrip(TERMINATORS)
    start = len(text)
    while start > 0 and text[start - 1] not in _WHITESPACE:
        start -= 1
    return text[start:].lower()


def split_claims(text: str) -> list[str]:
    """Split ``text`` into atomic claims on guarded sentence boundaries.

    Deterministic: the same text always yields the same claims.

    Rules, applied in order and all local to the break candidate:

    1. a run of terminators is one candidate boundary, not several;
    2. no break when the terminator sits between two digits (``500.00``);
    3. no break when the preceding token is a known abbreviation, or a single
       letter (initials — ``J. Smith``);
    4. no break for space-using scripts unless whitespace or end-of-text
       follows.
    """
    claims: list[str] = []
    buffer: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        buffer.append(ch)

        # A hard line break always ends a claim. Carried over from the splitter
        # this replaces: pooled evidence and list items are newline-joined, and
        # dropping this rule silently merged them into one unverifiable claim.
        if ch == "\n":
            claim = "".join(buffer).strip()
            if claim:
                claims.append(claim)
            buffer = []
            i += 1
            continue

        if ch in TERMINATORS:
            # rule 1 — consume the whole terminator run ("?!", "...")
            while i + 1 < n and text[i + 1] in TERMINATORS:
                i += 1
                buffer.append(text[i])

            following = text[i + 1] if i + 1 < n else ""
            preceding = text[i - 1] if i > 0 else ""

            # rule 2 — decimal, e.g. "500.00"
            if _is_digit(preceding) and _is_digit(following):
                i += 1
                continue

            # rule 3 — abbreviation or initial
            word = _preceding_word(buffer)
            if word in ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
                i += 1
                continue

            # rule 4 — space-using scripts need whitespace or end-of-text
            if following and following not in _WHITESPACE and ch in _NEEDS_TRAILING_SPACE:
                i += 1
                continue

            claim = "".join(buffer).strip()
            if claim:
                claims.append(claim)
            buffer = []

        i += 1

    tail = "".join(buffer).strip()
    if tail:
        claims.append(tail)
    return claims
