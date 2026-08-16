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

# (first, last, script) — must stay sorted by `first`; asserted at import.
_SCRIPT_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0041, 0x005A, "latin"),
    (0x0061, 0x007A, "latin"),
    (0x00AA, 0x00AA, "latin"),
    (0x00BA, 0x00BA, "latin"),
    (0x00C0, 0x02AF, "latin"),
    (0x0300, 0x036F, "common"),  # combining diacriticals — inherit their base
    (0x0370, 0x03FF, "greek"),
    (0x0400, 0x052F, "cyrillic"),
    (0x0531, 0x058F, "armenian"),
    (0x0591, 0x05F4, "hebrew"),
    (0x0600, 0x06FF, "arabic"),
    (0x0750, 0x077F, "arabic"),
    (0x0870, 0x08FF, "arabic"),
    (0x0900, 0x097F, "devanagari"),
    (0x0980, 0x09FF, "bengali"),
    (0x0B80, 0x0BFF, "tamil"),
    (0x0E00, 0x0E7F, "thai"),
    (0x0E80, 0x0EFF, "lao"),
    (0x1000, 0x109F, "myanmar"),
    (0x10A0, 0x10FF, "georgian"),
    (0x1100, 0x11FF, "hangul"),
    (0x1780, 0x17FF, "khmer"),
    (0x1E00, 0x1EFF, "latin"),
    (0x1F00, 0x1FFF, "greek"),
    (0x2C60, 0x2C7F, "latin"),
    (0x2DE0, 0x2DFF, "cyrillic"),
    (0x2E80, 0x2EFF, "han"),
    (0x3005, 0x3007, "han"),
    (0x3040, 0x309F, "hiragana"),
    (0x30A0, 0x30FF, "katakana"),
    (0x3130, 0x318F, "hangul"),
    (0x31F0, 0x31FF, "katakana"),
    (0x3400, 0x4DBF, "han"),
    (0x4E00, 0x9FFF, "han"),
    (0xA640, 0xA69F, "cyrillic"),
    (0xA720, 0xA7FF, "latin"),
    (0xA960, 0xA97F, "hangul"),
    (0xAC00, 0xD7A3, "hangul"),
    (0xF900, 0xFAFF, "han"),
    (0xFB1D, 0xFB4F, "hebrew"),
    (0xFB50, 0xFDFF, "arabic"),
    (0xFE70, 0xFEFF, "arabic"),
    (0xFF21, 0xFF3A, "latin"),
    (0xFF41, 0xFF5A, "latin"),
    (0x20000, 0x2A6DF, "han"),
)

# Scripts written without spaces between words. These are bigram-indexed;
# everything else is delimited by whitespace and punctuation. Korean is NOT
# here — Hangul writes spaces, so bigramming it would be a regression.
CONTINUOUS_SCRIPTS = frozenset({"han", "hiragana", "katakana", "thai", "lao", "khmer", "myanmar"})

# Scripts CiteNexus CLAIMS. ADR-0011: a script enters this set only when a golden
# fixture proves it end-to-end — tokens produced, a verbatim quote of its own
# source accepted by the gate, and unrelated text still rejected. See
# `tests/test_tokenize_v2.py::SAMPLES` and `conformance/cases/tokenize_v2.json`.
#
# Deliberately absent, with the bigram/word path implemented but no fixture:
# khmer, lao, myanmar, georgian, armenian, and every script outside the table
# above. They are reported by `unsupported_scripts`, not silently half-served.
SUPPORTED_SCRIPTS = frozenset(
    {
        "arabic",
        "bengali",
        "cyrillic",
        "devanagari",
        "greek",
        "han",
        "hangul",
        "hebrew",
        "hiragana",
        "katakana",
        "latin",
        "tamil",
        "thai",
    }
)


def script_of(ch: str) -> str:
    """The script of one character; ``"common"`` for script-neutral characters
    (digits, combining diacriticals) and ``"unknown"`` for anything the table
    does not cover.

    Binary search over a sorted range table — no regex, no property escapes.
    """
    cp = ord(ch)
    if "0" <= ch <= "9":
        return "common"
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
    return "unknown"


def _is_word_char(ch: str) -> bool:
    """Letters, numbers and marks are word-forming; everything else separates."""
    return unicodedata.category(ch)[0] in ("L", "N", "M")


def _emit(chars: list[str], script: str, out: list[str]) -> None:
    """Flush one same-script run into ``out``."""
    if not chars:
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
    run_script = "common"
    for ch in normalized:
        if not _is_word_char(ch):
            _emit(run, run_script, out)
            run, run_script = [], "common"
            continue
        script = script_of(ch)
        if run and script != "common" and run_script != "common" and script != run_script:
            # A script boundary inside a run of word characters ("東京tokyo").
            _emit(run, run_script, out)
            run, run_script = [], "common"
        run.append(ch)
        if run_script == "common":
            run_script = script
    _emit(run, run_script, out)
    return out


def scripts_in(text: str) -> tuple[str, ...]:
    """Every script present in ``text``'s word characters, sorted, without
    ``"common"`` — digits and punctuation carry no script claim."""
    found = {script_of(ch) for ch in text if _is_word_char(ch)}
    return tuple(sorted(found - {"common"}))


def unsupported_scripts(text: str) -> tuple[str, ...]:
    """The scripts in ``text`` that CiteNexus does not claim to support.

    A non-empty result is a **capability** signal, not an evidence judgement.
    Returning the evidence-absent refusal for a capability gap is the specific
    thing that let the ASCII-only tokenizer hide for as long as it did.
    """
    return tuple(s for s in scripts_in(text) if s not in SUPPORTED_SCRIPTS)


if __debug__:  # a mis-sorted table would silently mis-classify via binary search
    for _i in range(1, len(_SCRIPT_RANGES)):
        assert _SCRIPT_RANGES[_i - 1][1] < _SCRIPT_RANGES[_i][0], "script ranges must be sorted"
