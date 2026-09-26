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
    "MONTH_NUMBER",
    "NUMBER_RE",
    "DateKey",
    "DateSpan",
    "NumberMatch",
    "NumberReading",
    "clock_times",
    "date_spans",
    "dates_in",
    "is_identifier_prefix",
    "join_spaced_thousands",
    "money_rates",
    "numbers_in",
    "read_number",
    "same_date",
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


# ─────────────────────────────────────────────────────────────────────────────
# Numbers in running text — the Go reference's numbers.go, used by conflict
# detection and by the VerifyAnswer guards (ADR-0015, ADR-0016).
# ─────────────────────────────────────────────────────────────────────────────

# The letter-boundary guard is LATIN-ONLY, deliberately (see conflict.py): the
# identifiers it protects ("p50", "ipv4") are ASCII by construction.
_IDENTIFIER_PREFIX = frozenset("abcdefghijklmnopqrstuvwxyz_")


def is_identifier_prefix(ch: str) -> bool:
    """A character that makes a following digit run an identifier ("p50")."""
    return ch in _IDENTIFIER_PREFIX


@dataclass(frozen=True)
class NumberMatch:
    """One number found in lowered text, with its unit (if any)."""

    raw: str  # the matched digits and separators, as written
    reading: NumberReading
    unit: str = ""
    # True when the unit follows the digits with no space ("1st", "2de") —
    # required to read it as an ordinal suffix: "4 de werkgever" is a 4 and an
    # article.
    attached: bool = False


# A money amount grouped by spaces — a plain, no-break or narrow no-break space
# — "€ 4 000" = "€ 4.000" = 4000, including between the sign and the amount.
# Only after a currency sign or code, and only with exact three-digit groups:
# elsewhere "4 000" may be two numbers. (RE2 ``\s`` is ASCII, spelled out.)
_SPACED_THOUSANDS = re.compile(
    "((?:€|\\beur\\b|\\$|£)[\\t\\n\\f\\r \u00a0\u202f]*)([1-9][0-9]*)[ \u00a0\u202f]([0-9]{3})\\b",
    re.ASCII,
)


def join_spaced_thousands(text: str) -> str:
    """Join space-grouped money amounts: "€ 1 250 000" -> "€ 1250000"."""
    for _ in range(4):  # one group per pass
        joined = _SPACED_THOUSANDS.sub(r"\1\2\3", text)
        if joined == text:
            break
        text = joined
    return text


def numbers_in(text: str, language: str | None = None) -> list[NumberMatch]:
    """Every measured number in ``text``, skipping identifiers ("p50", "ipv4")."""
    from citenexus.answer._gostr import lower

    lowered = join_spaced_thousands(lower(text))
    out: list[NumberMatch] = []
    for m in NUMBER_RE.finditer(lowered):
        start = m.start(1)
        if start > 0 and is_identifier_prefix(lowered[start - 1]):
            continue  # "p50", "ipv4": an identifier, not a measured value
        reading = read_number(m.group(1), dash=m.group(2) is not None, language=language)
        unit = m.group(3)
        if unit is None:
            out.append(NumberMatch(raw=m.group(1), reading=reading))
        else:
            out.append(
                NumberMatch(
                    raw=m.group(1), reading=reading, unit=unit, attached=m.start(3) == m.end(1)
                )
            )
    return out


# Clock times are times of day, never durations or amounts: "09:00" = "9:00" =
# "9.00 uur" = "9am".
_CLOCK_COLON = re.compile(r"\b([01]?[0-9]|2[0-3]):([0-5][0-9])\b", re.ASCII)
_CLOCK_DOT = re.compile(r"\b([01]?[0-9]|2[0-3])\.([0-5][0-9])([\t\n\f\r ]*(?:uur|u)\b)", re.ASCII)
_CLOCK_AMPM = re.compile(
    r"\b(1[0-2]|0?[1-9])(?:[:.]([0-5][0-9]))?[\t\n\f\r ]*(am|pm|a\.m\.|p\.m\.)", re.ASCII
)


def clock_times(text: str) -> tuple[set[str], str]:
    """Clock-time keys ("clock:9:00", 24-hour) and the text with them blanked.

    The text comes back LOWERED, so the number and unit guards never read
    "9.00 uur" as nine hours or "09:00" as the numbers 9 and 0.
    """
    from citenexus.answer._gostr import lower

    keys: set[str] = set()
    lowered = lower(text)
    blank = list(lowered)

    def mark(start: int, end: int, hour: str, minute: str) -> None:
        h = hour.lstrip("0") or "0"
        keys.add(f"clock:{h}:{minute or '00'}")
        for i in range(start, end):
            blank[i] = " "

    for m in _CLOCK_AMPM.finditer(lowered):
        h = int(m.group(1))
        pm = m.group(3).startswith("p")
        if pm and h < 12:
            h += 12
        elif not pm and h == 12:
            h = 0
        mark(m.start(), m.end(), str(h), m.group(2) or "")
    for pattern in (_CLOCK_COLON, _CLOCK_DOT):
        current = "".join(blank)
        for m in pattern.finditer(current):
            mark(m.start(), m.end(2), m.group(1), m.group(2))
    return keys, "".join(blank)


# Money is never a duration: "€ 150 per maand" is a price with a period.
_MONEY_BEFORE = re.compile(r"(?:€|\beur\b|\$|£)[\t\n\f\r ]*([0-9][0-9.,]*)(?:,-)?", re.ASCII)
_MONEY_AFTER = re.compile(r"\b([0-9][0-9.,]*)[\t\n\f\r ]*(?:euro|eur)\b", re.ASCII)


def money_rates(text: str, language: str | None = None) -> tuple[set[tuple[str, str]], str]:
    """The (amount key, period class) rates in ``text``, and the lowered text
    with every money amount blanked (so it is never read as a duration)."""
    from citenexus.answer._gostr import lower
    from citenexus.answer.verify_guards_model import RATE_PERIOD, unit_of

    rates: set[tuple[str, str]] = set()
    lowered = lower(text)
    blank = list(lowered)
    for pattern in (_MONEY_BEFORE, _MONEY_AFTER):
        for m in pattern.finditer(lowered):
            raw = m.group(1).rstrip(".,")
            if raw == "":
                continue
            key = read_number(raw, language=language).key
            period = RATE_PERIOD.re.match(lowered, m.end())
            if period is not None:
                unit = unit_of(period.group(1))
                if unit is not None:
                    rates.add((key, unit[0]))
            for i in range(m.start(1), m.end(1)):
                blank[i] = " "
    return rates, "".join(blank)


# Dates, numeric or written, are read as (day, month, year?) and compared as
# dates: "01-06-2026" = "1 juni 2026" = "June 1, 2026".
MONTH_NUMBER: dict[str, int] = {
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "october": 10,
}
_MONTHS = "|".join(sorted(MONTH_NUMBER, key=len, reverse=True))
_NUMERIC_DATE = re.compile(
    r"\b([0-3]?[0-9])[-/.]([01]?[0-9])(?:[-/.]((?:19|20)[0-9]{2}))?\b", re.ASCII
)
_DAY_MONTH = re.compile(
    r"\b([0-3]?[0-9])(?:st|nd|rd|th|e|ste|de)?[\t\n\f\r ]+("
    + _MONTHS
    + r")\b(?:[\t\n\f\r ]+((?:19|20)[0-9]{2}))?",
    re.ASCII,
)
_MONTH_DAY = re.compile(
    r"\b("
    + _MONTHS
    + r")[\t\n\f\r ]+([0-3]?[0-9])(?:st|nd|rd|th)?\b(?:,?[\t\n\f\r ]+((?:19|20)[0-9]{2}))?",
    re.ASCII,
)


@dataclass(frozen=True)
class DateKey:
    """A date: day, month, year (0 = not stated), or an ambiguous spelling."""

    day: int = 0
    month: int = 0
    year: int = 0
    ambiguous: str = ""

    def __str__(self) -> str:
        if self.ambiguous:
            return self.ambiguous
        if self.year == 0:
            return f"{self.day:02d}-{self.month:02d}"
        return f"{self.day:02d}-{self.month:02d}-{self.year}"


def same_date(a: DateKey, b: DateKey) -> bool:
    """Equal day and month, and equal years when both state one."""
    if a.ambiguous or b.ambiguous:
        return bool(a.ambiguous) and a.ambiguous == b.ambiguous
    return (
        a.day == b.day and a.month == b.month and (a.year == 0 or b.year == 0 or a.year == b.year)
    )


@dataclass(frozen=True)
class DateSpan:
    start: int
    end: int
    key: DateKey


def _valid_date(d: int, m: int) -> bool:
    return 1 <= d <= 31 and 1 <= m <= 12


def date_spans(lowered: str, language: str | None) -> list[DateSpan]:
    """The dates in LOWERED text, in text order."""
    blank = list(lowered)
    spans: list[DateSpan] = []

    def mark(start: int, end: int, key: DateKey) -> None:
        spans.append(DateSpan(start, end, key))
        for i in range(start, end):
            blank[i] = " "

    for m in _DAY_MONTH.finditer(lowered):
        d, mo = int(m.group(1)), MONTH_NUMBER[m.group(2)]
        if not _valid_date(d, mo):
            continue
        mark(m.start(), m.end(), DateKey(d, mo, int(m.group(3)) if m.group(3) else 0))
    for m in _MONTH_DAY.finditer("".join(blank)):
        mo, d = MONTH_NUMBER[m.group(1)], int(m.group(2))
        if not _valid_date(d, mo):
            continue
        mark(m.start(), m.end(), DateKey(d, mo, int(m.group(3)) if m.group(3) else 0))
    dutch = _primary(language) == "nl"
    for m in _NUMERIC_DATE.finditer("".join(blank)):
        raw = m.group(0)
        a, b = int(m.group(1)), int(m.group(2))
        year = 0
        if m.group(3):
            year = int(m.group(3))
        elif "-" not in raw:
            continue  # "1.5" or "3/4" without a year is a number or a fraction
        if dutch and _valid_date(a, b):
            key = DateKey(a, b, year)
        elif not dutch and _valid_date(a, b) and _valid_date(b, a) and a != b:
            key = DateKey(ambiguous="date?" + raw)
        elif _valid_date(a, b):
            key = DateKey(a, b, year)
        elif _valid_date(b, a):
            key = DateKey(b, a, year)  # month-first, unambiguous
        else:
            continue
        mark(m.start(), m.end(), key)
    spans.sort(key=lambda s: s.start)
    return spans


def dates_in(text: str, language: str | None) -> tuple[list[DateKey], str]:
    """The dates in ``text`` and the LOWERED text with them blanked."""
    from citenexus.answer._gostr import lower

    lowered = lower(text)
    blank = list(lowered)
    out: list[DateKey] = []
    for sp in date_spans(lowered, language):
        out.append(sp.key)
        for i in range(sp.start, sp.end):
            blank[i] = " "
    return out, "".join(blank)
