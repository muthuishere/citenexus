"""Locale-aware number reading for conflict detection (ADR-0015).

Two passages quoting the same amount must compare EQUAL, and two different
amounts must never compare equal. The second rule dominates: a false "equal"
hides a real conflict (fails open), while a false "different" only costs an
abstention (fails closed).

So a number is read to a single value only when its FORM, or the passage's
declared language, leaves one reading. Otherwise it stays AMBIGUOUS: its key is
its raw spelling, prefixed ``?``, and it is equal to nothing but the same
spelling. Ambiguity never guesses.

Forms (``.`` and ``,`` are the only separators read):

* ``1500`` — an integer.
* ``25,-`` — Dutch whole amount: 25.
* both separators — the LAST is the decimal mark, the other groups thousands in
  threes: ``1.500,50`` = ``1,500.50`` = 1500.5.
* one separator, repeated — thousands in threes: ``1.500.000`` = 1500000.
* one separator, once, NOT followed by exactly three digits — a decimal mark in
  every locale, because a thousands group always has three digits:
  ``25,50`` = ``25.50`` = 25.5, ``1,5`` = ``1.5`` = 1.5.
* one separator, once, where the whole part cannot lead a thousands group
  (``1234.567``, ``0.500``) — a decimal mark, likewise.
* one separator, once, followed by exactly three digits — ``1.500`` / ``1,500``
  is 1500 or 1.5 depending on the locale. Read only when the language is
  declared (``DECIMAL_COMMA_LANGUAGES`` / ``DECIMAL_POINT_LANGUAGES``);
  ambiguous otherwise.
* anything else (``1.50.000``, dates ``01.02.2024``) — unreadable, kept by
  spelling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from citenexus.answer.tables import DECIMAL_COMMA_LANGUAGES, DECIMAL_POINT_LANGUAGES

__all__ = [
    "DECIMAL_COMMA_LANGUAGES",
    "DECIMAL_POINT_LANGUAGES",
    "NUMBER_RE",
    "NumberReading",
    "read_number",
]

# Which languages fix the decimal mark — canonical in conformance/conflict.json
# (ADR-0010 tier 2). A language in neither set reads a "1.500" as ambiguous.

#: A number: digit groups joined by single ``.``/``,``, an optional Dutch
#: ``,-``, then an optional unit. Applied to LOWERED text.
NUMBER_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)*)(,-)?\s*([a-z]+|%)?")

_GROUP = re.compile(r"^[0-9]{3}$")
_LEAD = re.compile(r"^[1-9][0-9]{0,2}$")


@dataclass(frozen=True)
class NumberReading:
    """A number's comparison key and, when it has one reading, its value."""

    key: str
    value: Fraction | None  # None = ambiguous or unreadable


def _primary(language: str | None) -> str:
    if not language:
        return ""
    return re.split(r"[-_]", language.strip().lower(), maxsplit=1)[0]


def _canonical(value: Fraction) -> str:
    """Decimal string with no trailing zeros: 1500, 25.5, 0.05."""
    if value.denominator == 1:
        return str(value.numerator)
    scale = 0
    scaled = value
    while scaled.denominator != 1:
        scaled *= 10
        scale += 1
    digits = str(abs(scaled.numerator)).rjust(scale + 1, "0")
    sign = "-" if scaled.numerator < 0 else ""
    return f"{sign}{digits[:-scale]}.{digits[-scale:]}"


def _value(integer_groups: list[str], decimals: str) -> Fraction:
    whole = int("".join(integer_groups))
    if not decimals:
        return Fraction(whole)
    return Fraction(whole) + Fraction(int(decimals), 10 ** len(decimals))


def _known(value: Fraction) -> NumberReading:
    return NumberReading(key=_canonical(value), value=value)


def _unread(raw: str) -> NumberReading:
    return NumberReading(key="?" + raw, value=None)


def _thousands(groups: list[str]) -> bool:
    """A valid thousands grouping: 1-3 leading digits (no leading zero), then threes."""
    return bool(_LEAD.match(groups[0])) and all(_GROUP.match(g) for g in groups[1:])


def read_number(raw: str, *, dash: bool = False, language: str | None = None) -> NumberReading:
    """Read one matched number (``NUMBER_RE`` group 1) to its comparison key.

    ``dash`` is True when the Dutch ``,-`` suffix followed it.
    """
    if dash:
        if "," in raw:
            return _unread(raw + ",-")  # "25,50,-" is not a form
        groups = raw.split(".")
        if len(groups) > 1 and not _thousands(groups):
            return _unread(raw + ",-")
        return _known(_value(groups, ""))

    has_dot, has_comma = "." in raw, "," in raw
    if not has_dot and not has_comma:
        return _known(Fraction(int(raw)))

    if has_dot and has_comma:
        decimal_mark = "." if raw.rfind(".") > raw.rfind(",") else ","
        thousands_mark = "," if decimal_mark == "." else "."
        whole, _, decimals = raw.rpartition(decimal_mark)
        if decimal_mark in whole:
            return _unread(raw)
        groups = whole.split(thousands_mark)
        if not _thousands(groups):
            return _unread(raw)
        return _known(_value(groups, decimals))

    mark = "." if has_dot else ","
    parts = raw.split(mark)
    if len(parts) > 2:
        return _known(_value(parts, "")) if _thousands(parts) else _unread(raw)

    whole, tail = parts
    if len(tail) != 3 or not _thousands(parts):
        return _known(_value([whole], tail))  # a decimal mark in every locale

    language_code = _primary(language)
    if language_code in DECIMAL_COMMA_LANGUAGES:
        thousands = mark == "."
    elif language_code in DECIMAL_POINT_LANGUAGES:
        thousands = mark == ","
    else:
        return _unread(raw)  # 1.500 / 1,500 with no declared locale
    return _known(_value([whole, tail], "")) if thousands else _known(_value([whole], tail))
