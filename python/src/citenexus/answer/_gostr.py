"""Go string and RE2 semantics, for the VerifyAnswer port (ADR-0016).

``verify_answer`` and its guards are a byte-for-byte port of the Go reference
(``golang/answer/verify_*.go``). Python's defaults differ from Go's in small
ways that change verdicts on real text, so the port reads text through these
helpers instead of the Python builtins:

* ``\\s`` in RE2 is ASCII ``[\\t\\n\\f\\r ]`` — Python's is Unicode (and ASCII
  mode adds ``\\v``). Patterns use :data:`WS` / :data:`NOT_WS` explicitly.
* ``\\b`` in RE2 is an ASCII word boundary: every pattern here compiles with
  ``re.ASCII``.
* ``\\p{L}`` has no ``re`` spelling: :func:`letter_class` builds it (lazily, it
  costs ~80 ms once).
* ``strings.ToLower`` maps rune by rune with the simple case mapping (no final
  sigma, ``İ`` -> ``i``); ``str.lower`` does neither.
* ``unicode.IsUpper`` is ``Lu`` only; ``str.isupper`` also accepts
  ``Other_Uppercase``.
* ``strings.Fields`` / ``strings.TrimSpace`` split on Go's ``unicode.IsSpace``,
  which excludes U+001C..U+001F that ``str.split`` includes.
* ``regexp.Split`` of an empty string is an EMPTY list, not ``[""]``.
* ``len(string)`` in Go counts UTF-8 bytes: :func:`blen`.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache

#: RE2 ``\s``.
WS = r"[\t\n\f\r ]"
#: RE2 ``\S``.
NOT_WS = r"[^\t\n\f\r ]"

# Go's unicode.IsSpace.
_GO_SPACE = (
    "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
_FIELDS = re.compile("[" + re.escape(_GO_SPACE) + "]+")


def lower(text: str) -> str:
    """Go ``strings.ToLower``: the simple lowercase mapping, rune by rune."""
    if text.isascii():
        return text.lower()
    out = []
    for ch in text:
        low = ch.lower()
        if len(low) != 1:
            low = "i" if ch == "İ" else ch
        out.append(low)
    return "".join(out)


def is_upper(ch: str) -> bool:
    """Go ``unicode.IsUpper``: category Lu."""
    if ch.isascii():
        return "A" <= ch <= "Z"
    return unicodedata.category(ch) == "Lu"


def is_letter(ch: str) -> bool:
    """Go ``unicode.IsLetter``: category L*."""
    return ch.isalpha()


def is_digit(ch: str) -> bool:
    """Go ``unicode.IsDigit``: category Nd."""
    return ch.isdecimal()


def fields(text: str) -> list[str]:
    """Go ``strings.Fields``."""
    return [f for f in _FIELDS.split(text) if f]


def trim_space(text: str) -> str:
    """Go ``strings.TrimSpace``."""
    return text.strip(_GO_SPACE)


def blen(text: str) -> int:
    """Go ``len(string)``: the UTF-8 byte length."""
    return len(text) if text.isascii() else len(text.encode("utf-8"))


def split(pattern: re.Pattern[str], text: str) -> list[str]:
    """Go ``regexp.Split(text, -1)`` for a pattern that cannot match empty.

    The pattern must have no capturing groups (``re.split`` would return them).
    """
    if text == "":
        return []
    return pattern.split(text)


@cache
def letter_class() -> str:
    """The body of a character class for ``\\p{L}`` (no brackets)."""
    ranges: list[tuple[int, int]] = []
    start = -1
    for code in range(0x110000):
        if chr(code).isalpha():
            if start < 0:
                start = code
        elif start >= 0:
            ranges.append((start, code - 1))
            start = -1
    if start >= 0:
        ranges.append((start, 0x10FFFF))
    parts = []
    for a, b in ranges:
        parts.append(f"\\U{a:08x}" if a == b else f"\\U{a:08x}-\\U{b:08x}")
    return "".join(parts)


def compile_go(pattern: str, *, ignore_case: bool = False) -> re.Pattern[str]:
    """Compile an RE2 pattern already written with :data:`WS` for ``\\s``.

    ``\\p{L}`` in ``pattern`` is replaced by the letter class. ASCII ``\\b``.
    """
    if "\\p{L}" in pattern:
        pattern = pattern.replace("\\p{L}", "[" + letter_class() + "]")
    flags = re.ASCII
    if ignore_case:
        flags |= re.IGNORECASE
    return re.compile(pattern, flags)


class LazyPattern:
    """A pattern compiled on first use (``\\p{L}`` costs ~80 ms to build)."""

    def __init__(self, pattern: str, *, ignore_case: bool = False) -> None:
        self._source = pattern
        self._ignore_case = ignore_case
        self._compiled: re.Pattern[str] | None = None

    @property
    def re(self) -> re.Pattern[str]:
        if self._compiled is None:
            self._compiled = compile_go(self._source, ignore_case=self._ignore_case)
        return self._compiled


def contains_any(text: str, chars: str) -> bool:
    """Go ``strings.ContainsAny``."""
    return any(c in text for c in chars)


_GO_ESCAPES = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\v": "\\v"}


def quote(text: str) -> str:
    """Go's ``%q`` for the strings a reason names."""
    out = ['"']
    for ch in text:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch in _GO_ESCAPES:
            out.append(_GO_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\x{ord(ch):02x}")
        elif not ch.isprintable() and ch != " ":
            code = ord(ch)
            out.append(f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)
