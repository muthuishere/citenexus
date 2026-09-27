"""Guards for the MODEL path — port of ``golang/answer/verify_guards_model.go``.

Swaps an NLI model admits with P(entailment) ≈ 0.999 that no threshold stops.
Each guard is deterministic, table-driven, and can only refuse. They run inside
``guards()`` on every quote and model admission; a gate admission is verbatim
and never reaches them.
"""

from __future__ import annotations

from fractions import Fraction

from citenexus.answer import _gostr as go
from citenexus.answer.numbers import (
    VerbatimNumbers,
    clock_times,
    money_rates,
    read_with,
    verbatim_in,
)
from citenexus.answer.verify import align, is_stopword
from citenexus.tokenize import tokenize_v2

# ─── polarity-swap guard ─────────────────────────────────────────────────────

#: Single-word substitutions that flip a claim's polarity, both directions.
POLARITY_SWAPS: dict[str, tuple[str, ...]] = {
    "een": ("geen",),
    "geen": ("een",),
    "wel": ("niet",),
    "niet": ("wel",),
    "altijd": ("nooit",),
    "nooit": ("altijd",),
    "always": ("never",),
    "never": ("always",),
    "a": ("no",),
    "an": ("no",),
    "no": ("a", "an"),
    "toegestaan": ("verboden",),
    "verboden": ("toegestaan",),
    "allowed": ("forbidden", "prohibited"),
    "forbidden": ("allowed",),
    "prohibited": ("allowed",),
    "permitted": ("prohibited",),
    "verplicht": ("optioneel",),
    "optioneel": ("verplicht",),
    "required": ("optional",),
    "optional": ("required",),
}


def polarity_swap_guard(claim: str, passage: str) -> str:
    """Refuse a claim that is the passage with ONE polarity word swapped."""
    claim_tokens = tokenize_v2(claim)
    passage_tokens = tokenize_v2(passage)

    def aligns(tokens: list[str]) -> bool:
        return align(tokens, passage_tokens) is not None

    if not claim_tokens or aligns(claim_tokens):
        return ""
    for i, t in enumerate(claim_tokens):
        for swap in POLARITY_SWAPS.get(t, ()):
            variant = [*claim_tokens[:i], swap, *claim_tokens[i + 1 :]]
            if aligns(variant):
                return (
                    f"negation guard: the claim says {go.quote(t)} "
                    f"where the passage says {go.quote(swap)}"
                )
    return ""


# ─── unit guard ──────────────────────────────────────────────────────────────

#: A unit word (NL + EN, with abbreviations) to its class. Work days and
#: calendar days are different classes on purpose.
TIME_UNITS: dict[str, str] = {
    "day": "day",
    "days": "day",
    "dag": "day",
    "dagen": "day",
    "kalenderdag": "day",
    "kalenderdagen": "day",
    "werkdag": "workday",
    "werkdagen": "workday",
    "week": "week",
    "weeks": "week",
    "weken": "week",
    "wk": "week",
    "wkn": "week",
    "month": "month",
    "months": "month",
    "maand": "month",
    "maanden": "month",
    "mnd": "month",
    "year": "year",
    "years": "year",
    "jaar": "year",
    "jaren": "year",
    "jr": "year",
    "yr": "year",
    "yrs": "year",
    "hour": "hour",
    "hours": "hour",
    "uur": "hour",
    "uren": "hour",
    "hr": "hour",
    "hrs": "hour",
    "minute": "minute",
    "minutes": "minute",
    "minuut": "minute",
    "minuten": "minute",
    "min": "minute",
    # Adjective forms after a number: "25-jarig", "32-urige", "5-daagse".
    "jarig": "year",
    "jarige": "year",
    "urig": "hour",
    "urige": "hour",
    "daags": "day",
    "daagse": "day",
}

#: Precede "day(s)" in English and change its class.
UNIT_MODIFIERS: dict[str, str] = {"working": "workday", "business": "workday", "calendar": "day"}

#: Spelled-out values a policy writes before a unit.
NUMBER_WORDS: dict[str, str] = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "sixty": "60",
    "nul": "0",
    "een": "1",
    "één": "1",
    "twee": "2",
    "drie": "3",
    "vier": "4",
    "vijf": "5",
    "zes": "6",
    "zeven": "7",
    "acht": "8",
    "negen": "9",
    "tien": "10",
    "elf": "11",
    "twaalf": "12",
    "dertien": "13",
    "veertien": "14",
    "vijftien": "15",
    "zestien": "16",
    "zeventien": "17",
    "achttien": "18",
    "negentien": "19",
    "twintig": "20",
    "dertig": "30",
    "veertig": "40",
    "vijftig": "50",
    "zestig": "60",
}


def unit_scan(text: str) -> list[str]:
    """Go ``unitScan``: ``[0-9]+(?:[.,][0-9]+)*|½|\\p{L}+``, all matches."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if "0" <= ch <= "9":
            j = i + 1
            while j < n and "0" <= text[j] <= "9":
                j += 1
            while j + 1 < n and text[j] in ".," and "0" <= text[j + 1] <= "9":
                k = j + 1
                while k < n and "0" <= text[k] <= "9":
                    k += 1
                j = k
            out.append(text[i:j])
            i = j
        elif ch == "½":
            out.append(ch)
            i += 1
        elif ch.isalpha():
            j = i + 1
            while j < n and text[j].isalpha():
                j += 1
            out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


#: A time unit inside a Dutch compound ("vakantiedagen"), longest first.
UNIT_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("werkdagen", "workday"),
    ("werkdag", "workday"),
    ("maanden", "month"),
    ("dagen", "day"),
    ("weken", "week"),
    ("jaren", "year"),
    ("maand", "month"),
    ("jaar", "year"),
    ("uren", "hour"),
    ("dag", "day"),
    ("uur", "hour"),
)

WEEKDAYS = frozenset(
    {"maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"}
)


def unit_of(token: str) -> tuple[str, bool] | None:
    """A token's time-unit class and whether it is a Dutch compound, or None."""
    found = TIME_UNITS.get(token)
    if found is not None:
        return found, False
    if len(token) < 6 or token in WEEKDAYS:
        return None
    for suffix, cls in UNIT_SUFFIXES:
        if token.endswith(suffix) and token != suffix:
            return cls, True
    return None


#: May sit between a number and its unit when several numbers share one.
QUANTITY_LINKS = frozenset({"respectievelijk", "resp", "en", "of", "tot", "à", "and", "or", "to"})

#: May precede the second number of a range.
RANGE_BOUND_WORDS = frozenset(
    {"maximaal", "minimaal", "hooguit", "maximum", "minimum", "most", "least"}
)

#: ``^(?:\s+\p{L}+)?\s*(?:per|a|an|each|/)\s*(\p{L}+)`` — matched with
#: ``.match(text, pos)``, so the ``^`` is implicit.
RATE_PERIOD = go.LazyPattern(
    go.WS + r"*(?:" + go.WS + r"+\p{L}+)?" + go.WS + r"*(?:per|a|an|each|/)" + go.WS + r"*(\p{L}+)"
)


def number_value(
    token: str, language: str | None, verbatim: VerbatimNumbers | None = None
) -> str | None:
    """A token's value key: "½", digits (ADR-0015), or a number word."""
    if token == "½":
        return "0.5"
    if "0" <= token[0] <= "9":
        return read_with(token, language=language, verbatim=verbatim).key
    return number_word_value(token)


def _rat(value: str) -> Fraction | None:
    """Go ``big.Rat.SetString`` for the decimal keys this module builds."""
    if not value or value.startswith("?"):
        return None
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None


def rat_key(r: Fraction) -> str:
    """Go ``ratKey``: an integer, or 6 decimals with trailing zeros trimmed."""
    if r.denominator == 1:
        return str(r.numerator)
    # big.Rat.FloatString(6): rounded to nearest, halves away from zero.
    negative = r < 0
    scaled = abs(r) * 10**6
    whole, rem = divmod(scaled.numerator, scaled.denominator)
    if rem * 2 >= scaled.denominator:
        whole += 1
    digits = str(whole).rjust(7, "0")
    s = ("-" if negative else "") + digits[:-6] + "." + digits[-6:]
    return s.rstrip("0").rstrip(".")


def quantities(
    text: str, language: str | None, verbatim: VerbatimNumbers | None = None
) -> set[tuple[str, str]]:
    """The (value key, unit class) pairs in ``text`` (see the Go comment)."""
    _, text = clock_times(text)  # "7.30 uur" is a time of day, not 7.3 hours
    _, text = money_rates(text, language, verbatim)  # "€ 150 per maand" is a price
    tokens = unit_scan(go.lower(text))
    out: set[tuple[str, str]] = set()
    n = len(tokens)
    for i in range(n):
        t = tokens[i]
        if t == "halfjaar":
            out.add(("6", "month"))
            continue
        if t == "half":
            j = i + 1
            if j < n and tokens[j] == "a":
                j += 1
            if j < n and tokens[j] in ("jaar", "year"):
                out.add(("6", "month"))
            continue
        ordinal = ORDINAL_WORDS.get(t)
        if ordinal is not None and i + 1 < n:
            unit = unit_of(tokens[i + 1])
            if unit is not None and unit[1] and unit[0] == "year":
                out.add((ordinal, "year"))
            continue
        value = number_value(t, language, verbatim)
        if value is None:
            continue
        j = i + 1
        if j < n and number_value(tokens[j], language, verbatim) == value:
            j += 1
        while j + 1 < n and j - i <= 6:
            if tokens[j] not in QUANTITY_LINKS:
                break
            skip = 0
            if tokens[j + 1] in RANGE_BOUND_WORDS and j + 2 < n:
                skip = 1
            linked = number_value(tokens[j + 1 + skip], language, verbatim)
            if linked is None:
                break
            j += 2 + skip
            if j < n and number_value(tokens[j], language, verbatim) == linked:
                j += 1  # "drie (3)" after the link
        if j >= n:
            continue
        unit = unit_of(tokens[j])
        cls, ok = (unit[0], True) if unit is not None else ("", False)
        mod = UNIT_MODIFIERS.get(tokens[j])
        if mod is not None and j + 1 < n:
            next_unit = unit_of(tokens[j + 1])
            if next_unit is not None and next_unit[0] == "day":
                cls, ok = mod, True
        if not ok and j + 1 < n and number_value(tokens[j], language, verbatim) is None:
            found = TIME_UNITS.get(tokens[j + 1])
            if found is not None:
                cls, ok = found, True
                # "een halve maand" is half a month, not one month.
                if tokens[j] in ("half", "halve"):
                    v = _rat(value)
                    if v is not None:
                        value = rat_key(v * Fraction(1, 2))
        if ok:
            out.add((value, cls))
    return out


def equivalent_quantity(q: tuple[str, str]) -> tuple[str, str] | None:
    """The same period in the other unit, when exact: v years <-> 12v months."""
    v = _rat(q[0])
    if v is None:
        return None
    if q[1] == "year":
        return rat_key(v * 12), "month"
    if q[1] == "month":
        return rat_key(v / 12), "year"
    return None


def unit_guard(
    claim: str, claim_language: str | None, passage: str, passage_language: str | None
) -> str:
    """Refuse a SWAP of a quantity (see the Go comment)."""
    _, claim = clock_times(claim)  # a clock time is never a duration
    _, passage = clock_times(passage)
    # A number the claim copies from the passage keeps the passage's reading
    # (ADR-0015 amendment).
    verbatim = verbatim_in(passage, passage_language)
    claim_rates, _ = money_rates(claim, claim_language, verbatim)
    passage_rates, _ = money_rates(passage, passage_language)
    for r in sorted(claim_rates):
        if r in passage_rates:
            continue
        for p in sorted(passage_rates):
            if p[0] == r[0] and p[1] != r[1] and not same_period_family(p[1], r[1]):
                return f"unit guard: {r[0]} per {r[1]} where the passage says {p[0]} per {p[1]}"
    have = quantities(passage, passage_language)
    for q in sorted(quantities(claim, claim_language, verbatim)):
        if q in have or same_quantity_in(q, have):
            continue
        same_value = sorted({p[1] for p in have if p[0] == q[0]})
        same_unit = sorted({p[0] for p in have if p[1] == q[1]})
        if same_value:
            return f"unit guard: {q[0]} {q[1]} where the passage says {q[0]} {'/'.join(same_value)}"
        if same_unit:
            return f"unit guard: {q[0]} {q[1]} where the passage says {'/'.join(same_unit)} {q[1]}"
    return ""


# ─── qualifier / role guard ──────────────────────────────────────────────────


class QualifierSide:
    """One side of a closed pair, with its forms per language."""

    __slots__ = ("en", "nl")

    def __init__(self, nl: tuple[str, ...], en: tuple[str, ...]) -> None:
        self.nl = nl
        self.en = en

    def forms_in(self, language: str) -> tuple[str, ...]:
        return self.nl if language == "nl" else self.en


#: Closed pairs whose swap flips legal meaning.
QUALIFIER_PAIRS: tuple[tuple[QualifierSide, QualifierSide], ...] = (
    (QualifierSide(("bruto",), ("gross",)), QualifierSide(("netto",), ("net",))),
    (QualifierSide(("werkgever",), ("employer",)), QualifierSide(("werknemer",), ("employee",))),
    (
        QualifierSide(("vóór", "voordat"), ("before",)),
        QualifierSide(("na", "ná", "nadat"), ("after",)),
    ),
    (QualifierSide(("eerder",), ("earlier",)), QualifierSide(("later",), ("later",))),
    (QualifierSide(("minimaal",), ("minimum",)), QualifierSide(("maximaal",), ("maximum",))),
    (
        QualifierSide(("schriftelijk", "schriftelijke"), ("written", "writing")),
        QualifierSide(("mondeling", "mondelinge"), ("oral", "orally", "verbally")),
    ),
)


def matches_form(token: str, form: str) -> bool:
    if len(form) >= 5:
        return form in token
    return token == form


def any_form(token: str, forms: tuple[str, ...] | list[str]) -> bool:
    return any(matches_form(token, form) for form in forms)


#: Function words that carry no locating signal, NL + EN.
CONTEXT_STOP = frozenset(
    {
        "de",
        "het",
        "een",
        "en",
        "van",
        "in",
        "op",
        "te",
        "dat",
        "die",
        "is",
        "zijn",
        "voor",
        "met",
        "aan",
        "bij",
        "of",
        "als",
        "ook",
        "om",
        "naar",
        "door",
        "over",
        "tot",
        "uit",
        "je",
        "jouw",
        "uw",
        "wordt",
        "worden",
    }
)

QUALIFIER_WINDOW = 5


def clause_tokens(text: str) -> list[list[str]]:
    """Tokens clause by clause, so a context window never crosses a sentence."""
    from citenexus.answer.verify_guards import CLAUSE_BREAK

    out = []
    for clause in go.split(CLAUSE_BREAK, soft_join(text)):
        tokens = tokenize_v2(clause)
        if tokens:
            out.append(tokens)
    return out


# A line break that does not end a sentence — a PDF wrap.
_SOFT_LINE_BREAK = go.compile_go(r"([^.!?:;\n])[ \t]*\n[ \t]*([^\n\-*•·0-9])")


def soft_join(text: str) -> str:
    return _SOFT_LINE_BREAK.sub(r"\1 \2", text)


def _window(tokens: list[str], i: int, pair: tuple[QualifierSide, QualifierSide]) -> set[str]:
    out = set()
    for k in range(i - QUALIFIER_WINDOW, i + QUALIFIER_WINDOW + 1):
        if k < 0 or k >= len(tokens) or k == i:
            continue
        t = tokens[k]
        if is_stopword(t) or _is_pair_form(t, pair) or t in CONTEXT_STOP:
            continue
        out.add(t)
    return out


def _is_pair_form(t: str, pair: tuple[QualifierSide, QualifierSide]) -> bool:
    return any(any_form(t, side.nl) or any_form(t, side.en) for side in pair)


def qualifier_guard(claim: str, passage: str) -> str:
    """Refuse one side of a closed pair where the passage, at the matching
    place, carries the other (same language only)."""
    passage_clauses = clause_tokens(passage)
    for pair in QUALIFIER_PAIRS:
        for claim_tokens in clause_tokens(claim):
            for i, t in enumerate(claim_tokens):
                for s in range(2):
                    for lang in ("nl", "en"):
                        same, other = pair[s].forms_in(lang), pair[1 - s].forms_in(lang)
                        if not any_form(t, same) or any_form(t, other):
                            continue
                        if _names_both(claim_tokens, i, other):
                            continue
                        if pair[0].en[0] in ("before", "earlier"):
                            if _relational_swap(claim_tokens, i, passage_clauses, same, other):
                                return (
                                    f"qualifier guard: the claim says {go.quote(t)} "
                                    f"where the passage says {'/'.join(other)}"
                                )
                            continue
                        context = _window(claim_tokens, i, pair)
                        best_same, best_other, saw_same, saw_other = -1, -1, False, False
                        for passage_tokens in passage_clauses:
                            for j, p in enumerate(passage_tokens):
                                is_same, is_other = any_form(p, same), any_form(p, other)
                                if is_same == is_other:
                                    continue
                                score = sum(
                                    1 for w in _window(passage_tokens, j, pair) if w in context
                                )
                                if is_same:
                                    saw_same = True
                                    best_same = max(best_same, score)
                                else:
                                    saw_other = True
                                    best_other = max(best_other, score)
                        if saw_other and (not saw_same or best_other > best_same):
                            return (
                                f"qualifier guard: the claim says {go.quote(t)} "
                                f"where the passage says {'/'.join(other)}"
                            )
    return ""


def _names_both(tokens: list[str], i: int, other: tuple[str, ...]) -> bool:
    for k in range(i - QUALIFIER_WINDOW, i + QUALIFIER_WINDOW + 1):
        if 0 <= k < len(tokens) and k != i and any_form(tokens[k], other):
            return True
    return False


def next_content(tokens: list[str], i: int) -> str:
    """The first content token after index i, or ""."""
    for k in range(i + 1, len(tokens)):
        if is_stopword(tokens[k]) or tokens[k] in CONTEXT_STOP:
            continue
        return tokens[k]
    return ""


def _relational_swap(
    claim_tokens: list[str],
    i: int,
    passage_clauses: list[list[str]],
    same: tuple[str, ...],
    other: tuple[str, ...],
) -> bool:
    target = next_content(claim_tokens, i)
    if target == "":
        return False
    saw_other = False
    for tokens in passage_clauses:
        for j, p in enumerate(tokens):
            if next_content(tokens, j) != target:
                continue
            if any_form(p, same):
                return False
            if any_form(p, other):
                saw_other = True
    return saw_other


# ─── scope guard ─────────────────────────────────────────────────────────────

DURING_WORDS = frozenset({"during", "throughout", "tijdens", "gedurende"})
UNIVERSALS = frozenset({"any", "all", "every", "each", "alle", "elk", "elke", "ieder", "iedere"})


def during_scopes(text: str) -> tuple[bool, bool]:
    """(universal, specific): the temporal scopes in text."""
    tokens = tokenize_v2(text)
    universal = specific = False
    for i, t in enumerate(tokens):
        if t not in DURING_WORDS or i + 1 >= len(tokens):
            continue
        nxt = tokens[i + 1]
        if nxt in ("the", "de", "het") and i + 2 < len(tokens):
            nxt = tokens[i + 2]
        if nxt in UNIVERSALS:
            universal = True
        else:
            specific = True
    return universal, specific


def scope_guard(claim: str, passage: str) -> str:
    """Refuse widening a specific period in the passage to every period."""
    claim_universal, _ = during_scopes(claim)
    if not claim_universal:
        return ""
    passage_universal, passage_specific = during_scopes(passage)
    if passage_specific and not passage_universal:
        return "scope guard: the claim widens a specific period in the passage to every period"
    return ""


def same_quantity_in(q: tuple[str, str], have: set[tuple[str, str]]) -> bool:
    """q, or the same period in another unit, is in have."""
    if q in have:
        return True
    eq = equivalent_quantity(q)
    if eq is not None and eq in have:
        return True
    v = _rat(q[0])
    if v is None:
        return False
    if q[1] == "year":
        return (rat_key(v * 52), "week") in have
    if q[1] == "week":
        years = v / 52
        return (rat_key(years), "year") in have and years.denominator == 1
    return False


def same_period_family(a: str, b: str) -> bool:
    return a in ("day", "workday") and b in ("day", "workday")


# Dutch writes numbers as one word: "vijfentwintig" (25), "tweeduizend" (2000).
_DUTCH_UNITS = {
    "een": 1,
    "één": 1,
    "twee": 2,
    "drie": 3,
    "vier": 4,
    "vijf": 5,
    "zes": 6,
    "zeven": 7,
    "acht": 8,
    "negen": 9,
}
_DUTCH_TEENS = {
    "tien": 10,
    "elf": 11,
    "twaalf": 12,
    "dertien": 13,
    "veertien": 14,
    "vijftien": 15,
    "zestien": 16,
    "zeventien": 17,
    "achttien": 18,
    "negentien": 19,
}
_DUTCH_TENS = {
    "twintig": 20,
    "dertig": 30,
    "veertig": 40,
    "vijftig": 50,
    "zestig": 60,
    "zeventig": 70,
    "tachtig": 80,
    "negentig": 90,
}


def number_word_value(word: str) -> str | None:
    value = NUMBER_WORDS.get(word)
    if value is not None:
        return value
    n = _parse_dutch_number(word)
    if n is not None and n > 0:
        return str(n)
    return None


def _parse_dutch_number(w: str) -> int | None:
    if w == "":
        return None
    head, sep, tail = w.partition("duizend")
    if sep:
        mult = 1
        if head:
            m = _parse_dutch_number(head)
            if m is None:
                return None
            mult = m
        rest = 0
        if tail:
            r = _parse_dutch_number(tail)
            if r is None:
                return None
            rest = r
        return mult * 1000 + rest
    head, sep, tail = w.partition("honderd")
    if sep:
        mult = 1
        if head:
            unit = _DUTCH_UNITS.get(head)
            if unit is None:
                return None
            mult = unit
        rest = 0
        if tail:
            r = _parse_dutch_number(tail)
            if r is None or r >= 100:
                return None
            rest = r
        return mult * 100 + rest
    for table in (_DUTCH_UNITS, _DUTCH_TEENS, _DUTCH_TENS):
        if w in table:
            return table[w]
    for link in ("ën", "en"):
        for tens, tv in _DUTCH_TENS.items():
            if w.endswith(link + tens):
                uv = _DUTCH_UNITS.get(w[: -len(link + tens)])
                if uv is not None:
                    return uv + tv
    return None


#: Spelled-out ordinals, NL + EN, 1 to 12.
ORDINAL_WORDS: dict[str, str] = {
    "eerste": "1",
    "tweede": "2",
    "derde": "3",
    "vierde": "4",
    "vijfde": "5",
    "zesde": "6",
    "zevende": "7",
    "achtste": "8",
    "negende": "9",
    "tiende": "10",
    "elfde": "11",
    "twaalfde": "12",
    "first": "1",
    "second": "2",
    "third": "3",
    "fourth": "4",
    "fifth": "5",
    "sixth": "6",
    "seventh": "7",
    "eighth": "8",
    "ninth": "9",
    "tenth": "10",
    "eleventh": "11",
    "twelfth": "12",
}
