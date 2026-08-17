"""Tokenizers. ``tokenize`` is v1 — frozen; ``tokenize_v2`` is the Unicode one.

**v1 (``tokenize``)** is the pinned SPEC-PORTS-v1 §4 tokenizer: lowercase,
``[a-z0-9]+`` splitting, no stemming. A frozen contract — every port (Go, TS,
Rust-bound) matches this exactly, and the shipped conformance vectors pin it
byte-for-byte. **Do not edit it.**

**v2 (``tokenize_v2``)** exists because v1 is ASCII-only, and that turned out to
be a false capability claim rather than a limitation (ADR-0011). Measured
2026-08-11: Japanese, Chinese, Arabic and Tamil each produced **zero** tokens, so
``is_supported`` rejected a verbatim quote of its own source and every answer in
those scripts abstained. BM25 and the structure retriever tokenize through the
same function, so lexical retrieval returned nothing either — the abstention was
over-determined.

v2 changes three things and nothing else:

1. Word characters are Unicode letter/number/mark classes rather than ASCII
   ranges, so ``Café`` is one token instead of the truncated stub ``caf``.
2. Case folding (``str.casefold``) rather than ``.lower()``, so ``Straße`` and
   ``STRASSE`` match. This is the one place the ports genuinely diverge — Go's
   ``strings.ToLower`` and JS's ``toLowerCase`` are not full case folding — which
   is why a conformance vector carries ``ß`` explicitly.
3. **Segmentation, not classification, for scripts that do not write spaces.**
   Whitespace-splitting Chinese, Japanese or Thai yields one token per sentence,
   which makes BM25 and any containment predicate degenerate. Those scripts are
   character-bigram indexed — the standard treatment, deterministic, no
   dictionary. Dictionary word-breaking is explicitly deferred (ADR-0011).

v2 is a strict superset of v1's behavior on pure-ASCII input: for any text whose
word characters are all ASCII, ``tokenize_v2(text) == tokenize(text)``. That is
asserted in ``tests/test_tokenize_v2.py`` and it is why moving BM25, the
structure retriever and the faithfulness gate onto v2 left every existing
conformance vector unchanged.

Implementation notes, both load-bearing for the Go and JS ports:

- **No regex.** This is a character scan over Unicode category and script tables,
  because Python ``re`` has no ``\\p{L}``, Go RE2 and JS RegExp disagree on
  Unicode property escapes, and the divergence would be invisible to any
  practical fixture set. Same reason ``answer/segment.py`` scans rather than
  matches.
- **Scripts are claimed, not detected-and-hoped.** ``SUPPORTED_SCRIPTS`` is an
  explicit allowlist, and per ADR-0011 no script may be added to it without a
  golden fixture. Everything else is reported by ``unsupported_scripts`` so the
  caller gets a capability signal instead of the evidence-absent refusal.
"""

from __future__ import annotations

import re
import unicodedata

from citenexus.lang.codes import Script

__all__ = [
    "CONTINUOUS_SCRIPTS",
    "SUPPORTED_SCRIPTS",
    "TOKENIZER_VERSION",
    "script_of",
    "scripts_in",
    "tokenize",
    "tokenize_v2",
    "unsupported_scripts",
]

# The version stamped on an index so a tokenizer/index mismatch is detectable
# rather than silent (ADR-0011). Bump it whenever tokenize_v2's output changes
# for any input: an index built under an older version must be rebuilt to
# benefit, and a caller must be able to see that it has not been.
TOKENIZER_VERSION = 2

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """v1 — FROZEN (SPEC-PORTS-v1 §4). ASCII only, by contract. Do not edit."""
    return _TOKEN_RE.findall(text.lower())


# --------------------------------------------------------------------------- #
# Script table (tier-2 shared data — one canonical definition, ports generated).
#
# Python's stdlib has no Script property, so the ranges are carried explicitly.
# The table is deliberately partial: it covers the scripts CiteNexus makes a
# claim about plus the near neighbours it must be able to NAME when refusing.
# Anything outside it is "unknown", which is unsupported, which is reported.
# --------------------------------------------------------------------------- #

# A script that is ABSENT from this table classifies as "unknown", and an
# unknown-script run produces NO tokens at all (see `_emit`). That is the
# structural half of ADR-0011's rule: a script the table has never heard of
# cannot be segmented by a validated rule, and answering through an unvalidated
# segmentation is worse than refusing. Telugu (U+0C00-U+0C7F) was missing from
# this table entirely — it read as its neighbours plus "unknown" while still
# emitting six plausible-looking tokens, so BM25 ranked a script no fixture had
# ever validated and `answer/flow.py` then filtered every Telugu passage out of
# the grounding set. Measured 2026-08-16 on `examples/multilingual/`: 0/7 on
# Telugu-only questions, including a grounded, correctly-cited WRONG answer.
#
# Consequently there are three tiers here, not two:
#   - in the table AND in SUPPORTED_SCRIPTS  → claimed, fixture-backed, citable
#   - in the table, NOT in SUPPORTED_SCRIPTS → named, tokenized by a deliberate
#     segmentation choice, reported by `unsupported_scripts` (khmer, telugu's
#     Indic neighbours, …)
#   - not in the table                       → unknown: named as "unknown",
#     tokenizes to nothing, so nothing downstream can rank or cite it.
#
# (first, last, script) — must stay sorted by `first`; asserted at import.
_SCRIPT_RANGES: tuple[tuple[int, int, Script], ...] = (
    (0x0041, 0x005A, Script.LATIN),
    (0x0061, 0x007A, Script.LATIN),
    (0x00AA, 0x00AA, Script.LATIN),
    (0x00BA, 0x00BA, Script.LATIN),
    (0x00C0, 0x02AF, Script.LATIN),
    (0x0300, 0x036F, Script.COMMON),  # combining diacriticals — inherit their base
    (0x0370, 0x03FF, Script.GREEK),
    (0x0400, 0x052F, Script.CYRILLIC),
    (0x0531, 0x058F, Script.ARMENIAN),
    (0x0591, 0x05F4, Script.HEBREW),
    (0x0600, 0x06FF, Script.ARABIC),
    (0x0750, 0x077F, Script.ARABIC),
    (0x0870, 0x08FF, Script.ARABIC),
    (0x0900, 0x097F, Script.DEVANAGARI),
    (0x0980, 0x09FF, Script.BENGALI),
    (0x0A00, 0x0A7F, Script.GURMUKHI),
    (0x0A80, 0x0AFF, Script.GUJARATI),
    (0x0B00, 0x0B7F, Script.ORIYA),
    (0x0B80, 0x0BFF, Script.TAMIL),
    (0x0C00, 0x0C7F, Script.TELUGU),
    (0x0C80, 0x0CFF, Script.KANNADA),
    (0x0D00, 0x0D7F, Script.MALAYALAM),
    (0x0D80, 0x0DFF, Script.SINHALA),
    (0x0E00, 0x0E7F, Script.THAI),
    (0x0E80, 0x0EFF, Script.LAO),
    (0x1000, 0x109F, Script.MYANMAR),
    (0x10A0, 0x10FF, Script.GEORGIAN),
    (0x1100, 0x11FF, Script.HANGUL),
    (0x1780, 0x17FF, Script.KHMER),
    (0x1AB0, 0x1AFF, Script.COMMON),  # combining marks extended — Inherited
    (0x1C80, 0x1C8F, Script.CYRILLIC),
    (0x1C90, 0x1CBF, Script.GEORGIAN),  # Mtavruli
    (0x1D00, 0x1D25, Script.LATIN),
    (0x1D26, 0x1D2A, Script.GREEK),
    (0x1D2B, 0x1D2B, Script.CYRILLIC),
    (0x1D6B, 0x1D77, Script.LATIN),
    (0x1D78, 0x1D78, Script.CYRILLIC),
    (0x1D79, 0x1D9A, Script.LATIN),
    (0x1DC0, 0x1DFF, Script.COMMON),  # combining marks supplement — Inherited
    (0x1E00, 0x1EFF, Script.LATIN),
    (0x1F00, 0x1FFF, Script.GREEK),
    (0x20D0, 0x20F0, Script.COMMON),  # combining marks for symbols — Inherited
    (0x2184, 0x2184, Script.LATIN),
    (0x2C60, 0x2C7F, Script.LATIN),
    (0x2D00, 0x2D2F, Script.GEORGIAN),  # Khutsuri supplement
    (0x2DE0, 0x2DFF, Script.CYRILLIC),
    (0x2E80, 0x2EFF, Script.HAN),
    (0x3005, 0x3007, Script.HAN),
    (0x302E, 0x302F, Script.HANGUL),  # Hangul tone marks (Mn)
    (0x3040, 0x309F, Script.HIRAGANA),
    (0x30A0, 0x30FF, Script.KATAKANA),
    (0x3130, 0x318F, Script.HANGUL),
    (0x31F0, 0x31FF, Script.KATAKANA),
    (0x3400, 0x4DBF, Script.HAN),
    (0x4E00, 0x9FFF, Script.HAN),
    (0xA640, 0xA69F, Script.CYRILLIC),
    (0xA720, 0xA7FF, Script.LATIN),
    (0xA8E0, 0xA8FF, Script.DEVANAGARI),  # Devanagari Extended
    (0xA960, 0xA97F, Script.HANGUL),
    (0xA9E0, 0xA9FF, Script.MYANMAR),  # Myanmar Extended-B
    (0xAA60, 0xAA7F, Script.MYANMAR),  # Myanmar Extended-A
    (0xAB30, 0xAB64, Script.LATIN),
    (0xAB65, 0xAB65, Script.GREEK),
    (0xAB66, 0xAB68, Script.LATIN),
    (0xAC00, 0xD7A3, Script.HANGUL),
    (0xD7B0, 0xD7FF, Script.HANGUL),  # Hangul Jamo Extended-B
    (0xF900, 0xFAFF, Script.HAN),
    (0xFB1D, 0xFB4F, Script.HEBREW),
    (0xFB50, 0xFDFF, Script.ARABIC),
    (0xFE00, 0xFE0F, Script.COMMON),  # variation selectors — Inherited
    (0xFE20, 0xFE2F, Script.COMMON),  # combining half marks — Inherited
    (0xFE70, 0xFEFF, Script.ARABIC),
    (0xFF21, 0xFF3A, Script.LATIN),
    (0xFF41, 0xFF5A, Script.LATIN),
    (0x10140, 0x1018B, Script.GREEK),  # Ancient Greek Numbers
    (0x10EFD, 0x10EFF, Script.ARABIC),  # Arabic Extended-C marks
    (0x11FC0, 0x11FF1, Script.TAMIL),  # Tamil Supplement
    (0x1AFF0, 0x1B000, Script.KATAKANA),  # Kana Extended-B
    (0x1B001, 0x1B11F, Script.HIRAGANA),
    (0x1B120, 0x1B122, Script.KATAKANA),
    (0x1B132, 0x1B132, Script.HIRAGANA),
    (0x1B150, 0x1B152, Script.HIRAGANA),
    (0x1B155, 0x1B155, Script.KATAKANA),
    (0x1B164, 0x1B167, Script.KATAKANA),
    (0x1DF00, 0x1DF2A, Script.LATIN),  # Latin Extended-G
    (0x20000, 0x2A6DF, Script.HAN),
    (0x2A700, 0x2EBEF, Script.HAN),  # CJK ext C-I
    (0x30000, 0x323AF, Script.HAN),  # CJK ext G-H
)

# Scripts written without spaces between words. These are bigram-indexed;
# everything else is delimited by whitespace and punctuation. Korean is NOT
# here — Hangul writes spaces, so bigramming it would be a regression.
CONTINUOUS_SCRIPTS: frozenset[Script] = frozenset(
    {
        Script.HAN,
        Script.HIRAGANA,
        Script.KATAKANA,
        Script.THAI,
        Script.LAO,
        Script.KHMER,
        Script.MYANMAR,
    }
)

# Scripts CiteNexus CLAIMS. ADR-0011: a script enters this set only when a golden
# fixture proves it end-to-end — tokens produced, a verbatim quote of its own
# source accepted by the gate, and unrelated text still rejected. See
# `tests/test_tokenize_v2.py::SAMPLES` and `conformance/cases/tokenize_v2.json`.
#
# Deliberately absent, NAMED by the table but carrying no fixture: khmer, lao,
# myanmar, georgian, armenian, and Telugu's Indic neighbours — gurmukhi,
# gujarati, oriya, kannada, malayalam, sinhala. They are reported by
# `unsupported_scripts`, not silently half-served. Any script outside the table
# is "unknown", which additionally produces no tokens at all.
SUPPORTED_SCRIPTS: frozenset[Script] = frozenset(
    {
        Script.ARABIC,
        Script.BENGALI,
        Script.CYRILLIC,
        Script.DEVANAGARI,
        Script.GREEK,
        Script.HAN,
        Script.HANGUL,
        Script.HEBREW,
        Script.HIRAGANA,
        Script.KATAKANA,
        Script.LATIN,
        Script.TAMIL,
        Script.TELUGU,
        Script.THAI,
    }
)


def script_of(ch: str) -> Script:
    """The script of one character; ``"common"`` for script-neutral characters
    (digits, combining diacriticals) and ``"unknown"`` for anything the table
    does not cover.

    Binary search over a sorted range table — no regex, no property escapes.
    """
    cp = ord(ch)
    if "0" <= ch <= "9":
        return Script.COMMON
    lo, hi = 0, len(_SCRIPT_RANGES) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        first, last, name = _SCRIPT_RANGES[mid]
        if cp < first:
            hi = mid - 1
        elif cp > last:
            lo = mid + 1
        else:
            return name
    return Script.UNKNOWN


def _is_word_char(ch: str) -> bool:
    """Letters, numbers and marks are word-forming; everything else separates."""
    return unicodedata.category(ch)[0] in ("L", "N", "M")


def _emit(chars: list[str], script: Script, out: list[str]) -> None:
    """Flush one same-script run into ``out``.

    A run whose script the table does not cover is DROPPED, not emitted. There is
    no validated segmentation rule for a script nobody put in the table — Telugu
    read as "unknown" and still produced six delimited tokens, which is exactly
    how BM25 came to rank an unvalidated script. Emitting nothing makes the
    failure loud: the gate refuses (``align`` returns ``None`` for an empty claim,
    so this can never rubber-stamp), lexical retrieval scores nothing, and
    ``unsupported_scripts`` reports ``"unknown"`` as the capability signal.
    Naming a script in ``_SCRIPT_RANGES`` — which is a deliberate choice of the
    delimited or the bigram path — is what turns tokenization back on.
    """
    if not chars:
        return
    if script is Script.UNKNOWN:
        return
    if script in CONTINUOUS_SCRIPTS and len(chars) > 1:
        # Character bigrams. Deterministic, dictionary-free, and adequate for
        # both lexical retrieval and ordered containment.
        out.extend("".join(chars[i : i + 2]) for i in range(len(chars) - 1))
    else:
        out.append("".join(chars))


def tokenize_v2(text: str) -> list[str]:
    """Unicode-aware tokenization with bigram segmentation for spaceless scripts.

    NFKC-normalized and case-folded, then scanned into maximal same-script runs
    of word characters. Runs in a continuous script become character bigrams; all
    others become one token each.
    """
    normalized = unicodedata.normalize("NFKC", text).casefold()
    # casefold can denormalize (ẞ → ss is fine, but some folds reorder marks),
    # so normalize once more. Idempotent for the overwhelming majority of input.
    normalized = unicodedata.normalize("NFKC", normalized)

    out: list[str] = []
    run: list[str] = []
    run_script = Script.COMMON
    for ch in normalized:
        if not _is_word_char(ch):
            _emit(run, run_script, out)
            run, run_script = [], Script.COMMON
            continue
        script = script_of(ch)
        boundary = (
            script is not Script.COMMON and run_script is not Script.COMMON and script != run_script
        )
        if run and boundary:
            # A script boundary inside a run of word characters ("東京tokyo").
            _emit(run, run_script, out)
            run, run_script = [], Script.COMMON
        run.append(ch)
        if run_script is Script.COMMON:
            run_script = script
    _emit(run, run_script, out)
    return out


def scripts_in(text: str) -> tuple[Script, ...]:
    """Every script present in ``text``'s word characters, sorted, without
    ``"common"`` — digits and punctuation carry no script claim."""
    found = {script_of(ch) for ch in text if _is_word_char(ch)}
    return tuple(sorted(found - {Script.COMMON}))


def unsupported_scripts(text: str) -> tuple[Script, ...]:
    """The scripts in ``text`` that CiteNexus does not claim to support.

    A non-empty result is a **capability** signal, not an evidence judgement.
    Returning the evidence-absent refusal for a capability gap is the specific
    thing that let the ASCII-only tokenizer hide for as long as it did.
    """
    return tuple(s for s in scripts_in(text) if s not in SUPPORTED_SCRIPTS)


if __debug__:  # a mis-sorted table would silently mis-classify via binary search
    for _i in range(1, len(_SCRIPT_RANGES)):
        assert _SCRIPT_RANGES[_i - 1][1] < _SCRIPT_RANGES[_i][0], "script ranges must be sorted"
