"""Deterministic guards for model-admitted claims, and quote extraction.

Port of ``golang/answer/verify_guards.go`` (ADR-0016). A SupportChecker may
admit a claim the token gate could not verify (a translation, a paraphrase).
These guards run on every such admission and the model cannot override them:
numbers, negation and names are exactly where an entailment model is weakest
and a wrong answer is most expensive. Each guard can only REFUSE.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import (
    verify_conditions,
    verify_conjuncts,
    verify_definitions,
    verify_exclusions,
    verify_hedges,
    verify_parties,
    verify_qualifier_pairs,
    verify_relations,
    verify_roles,
    verify_subtypes,
    verify_verbpairs,
)
from citenexus.answer.numbers import NumberMatch, clock_times, dates_in, numbers_in, same_date
from citenexus.answer.tables import POLARITY_MARKERS
from citenexus.answer.verify import MAX_SINGLE_GAP, align
from citenexus.answer.verify_guards_model import (
    ORDINAL_WORDS,
    number_value,
    number_word_value,
    polarity_swap_guard,
    qualifier_guard,
    rat_key,
    scope_guard,
    soft_join,
    unit_guard,
    unit_of,
    unit_scan,
)
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.glossary import PreparedGlossary
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_definitions import Definition
    from citenexus.answer.verify_qualifier_pairs import QualifierPair
    from citenexus.answer.verify_roles import ActorLexicon
    from citenexus.answer.verify_subtypes import SubtypeHead
    from citenexus.answer.verify_verbpairs import VerbPair


def number_guard(
    claim: str, claim_language: str | None, passage: str, passage_language: str | None
) -> str:
    """Every number in the claim is a number in the passage (ADR-0015 keys)."""
    # Clock times first, compared as times; then blanked for the rest.
    claim_clocks, claim = clock_times(claim)
    passage_clocks, passage = clock_times(passage)
    # Dates next, compared as dates, then blanked.
    claim_dates, claim = dates_in(claim, claim_language)
    passage_dates, passage = dates_in(passage, passage_language)
    for cd in claim_dates:
        if not any(same_date(cd, pd) for pd in passage_dates):
            return f"number guard: {cd} is not in the passage"
    for k in sorted(claim_clocks):
        if k not in passage_clocks:
            return f"number guard: {k.removeprefix('clock:')} is not in the passage"
    have: set[str] = set()
    for m in numbers_in(passage, passage_language):
        have.add(cents_as_euros(m))
        if m.unit in ORDINAL_SUFFIXES and m.attached:
            have.add("ord:" + m.reading.key)
    for word in unit_scan(go.lower(passage)):
        value = number_word_value(word)
        if value is not None and word != "een":
            have.add(value)
        ordinal = ORDINAL_WORDS.get(word)
        if ordinal is not None:
            have.add("ord:" + ordinal)
    for m in numbers_in(claim, claim_language):
        key = cents_as_euros(m)
        if m.unit in ORDINAL_SUFFIXES and m.attached:
            key = "ord:" + key
        if key not in have:
            shown = key.removeprefix("ord:").removeprefix("?")
            return f"number guard: {shown} is not in the passage"
    return count_conflict(claim, passage, passage_language)


def count_conflict(claim: str, passage: str, passage_language: str | None) -> str:
    """A number word in the claim, followed by a noun, where the passage counts
    that same noun only with other values."""
    words = unit_scan(go.lower(claim))
    ptoks = unit_scan(go.lower(passage))
    for i, word in enumerate(words):
        value = number_word_value(word)
        if value is None or word in ("een", "one") or i + 1 >= len(words):
            continue
        noun = words[i + 1]
        if noun in COUNT_FUNCTION_WORDS:
            continue  # "één voor één", "two of the …": not a counted noun
        if unit_of(noun) is not None:
            continue
        if number_value(noun, passage_language) is not None:
            continue
        span = [noun]
        if noun.endswith("e") and i + 2 < len(words):
            span.append(words[i + 2])
        others: list[str] = []
        agrees = False
        k = 0
        while k + len(span) < len(ptoks):
            if ptoks[k + 1 : k + 1 + len(span)] != span or ptoks[k] in ("een", "one"):
                k += 1
                continue
            pv = number_value(ptoks[k], passage_language)
            if pv is not None:
                if pv == value:
                    agrees = True
                else:
                    others.append(ptoks[k])
            k += 1
        if not agrees and others:
            return f"number guard: {word} {noun}, the passage says {others[0]} {noun}"
    return ""


#: Follow a number without being what it counts.
COUNT_FUNCTION_WORDS = frozenset(
    {
        "voor",
        "na",
        "van",
        "op",
        "in",
        "of",
        "en",
        "per",
        "uit",
        "bij",
        "tot",
        "met",
        "aan",
        "keer",
        "for",
        "the",
        "and",
        "or",
        "to",
        "times",
        "at",
        "by",
    }
)

#: Follow a digit to make it an ordinal: 1st, 2nd, 3rd, 4th, 1e, 2de, 8ste.
ORDINAL_SUFFIXES = frozenset({"st", "nd", "rd", "th", "e", "de", "ste"})


def negation_guard(claim: str, passage: str) -> str:
    """A claim that carries a polarity marker needs a passage that carries one."""
    claim_tokens = tokenize_v2(claim)
    passage_tokens = tokenize_v2(passage)
    bounded = bound_marker_positions(claim_tokens, bound_directions(passage_tokens))
    claim_negated = any(
        tok in POLARITY_MARKERS and i not in bounded for i, tok in enumerate(claim_tokens)
    )
    if not claim_negated:
        return ""
    for tok in passage_tokens:
        if tok in POLARITY_MARKERS or tok in NEGATIVE_WORDS:
            return ""
    return "negation guard: the claim is negated and the passage is not"


_STRONG_MARKUP = re.compile(r"\*\*|__|`")

ORDINAL_TOKEN = re.compile(r"^[0-9]+(?:st|nd|rd|th|e|de|ste)\Z", re.ASCII)

#: A number joined to its unit or a fraction: "25-jarig", "40-hour", "1/12th".
NUMBER_WITH_UNIT = re.compile(
    r"^[0-9]+(?:[.,][0-9]+)?-?(?:jarig|jarige|urig|urige|daags|daagse|weeks|weekse|maands|maandse"
    r"|hour|hours|day|days|week|weeks|month|months|year|years)\Z"
    r"|^[0-9]+/[0-9]+(?:st|nd|rd|th|e|de|ste)?\Z"
    r"|^[0-9]{1,2}(?:[:.][0-5][0-9])?(?:am|pm)\Z",
    re.ASCII,
)

LIST_MARKER = re.compile(r"^(?:[-*•·\u2013\u2014]|#{1,6}|[0-9]{1,3}[.)]|[a-z][.)])\Z")


def is_list_marker(field_: str) -> bool:
    """A bullet, heading hash or list number standing alone."""
    return LIST_MARKER.match(field_) is not None


_OPEN_QUOTES = "\"“„«([{'‘"  # noqa: RUF001 — typographic quotes are the point
_NAME_TRIM = "\"“”„«»()[]{},;:.!?'‘’|"  # noqa: RUF001
_TERMINATOR_TRIM = "\"”»)]}'’"  # noqa: RUF001


def names(claim: str) -> list[str]:
    """The claim's capitalised words not in an INITIAL position, plus any word
    mixing letters and digits or written in capitals ("R-119", "CAO")."""
    out: list[str] = []
    plain = _STRONG_MARKUP.sub("", claim)
    initial = True
    for f in go.fields(plain):
        if is_list_marker(f):
            initial = True
            continue
        if f == "|":
            initial = True  # a table cell starts like a sentence
            continue
        opens_quote = f[0] in _OPEN_QUOTES
        word = f.strip(_NAME_TRIM)
        # Possessive: "Ploum's" names Ploum; the tokenizer would add an "s".
        word = word.removesuffix("'s").removesuffix("’s")  # noqa: RUF001
        if "-" in word and not capitalised_parts(word) and not go.contains_any(word, "0123456789"):
            initial = False
            continue
        low = go.lower(word)
        if low in CURRENCY_CODES:
            initial = False
            continue  # "EUR 2.40": a currency, read with its amount, not a name
        if ORDINAL_TOKEN.match(low) or NUMBER_WITH_UNIT.match(low):
            initial = False
            continue  # "1st", "25-jarig", "40-hour": a number, not a name
        if len(word) > 1:
            has_digit = has_letter = False
            all_upper = True
            for r in word:
                if go.is_digit(r):
                    has_digit = True
                elif go.is_letter(r):
                    has_letter = True
                    if not go.is_upper(r):
                        all_upper = False
            letters_and_digits = has_letter and has_digit
            capitals = has_letter and all_upper
            mid_sentence_capital = not initial and not opens_quote and go.is_upper(word[0])
            if letters_and_digits or capitals or mid_sentence_capital:
                out.append(word)
        # A terminator or colon ends a sentence or label; the next word is initial.
        trimmed = f.rstrip(_TERMINATOR_TRIM)
        initial = trimmed.endswith((".", "!", "?", ":", ";", "|"))
    return out


def name_guard(claim: str, passage: str) -> str:
    return name_guard_with(claim, passage, None)


def name_guard_with(claim: str, passage: str, aliases: Mapping[str, Sequence[str]] | None) -> str:
    name = absent_name(names(claim), passage, aliases)
    if name:
        return f"name guard: {go.quote(name)} is not in the passage"
    return ""


def absent_name(
    found: Sequence[str], passage: str, aliases: Mapping[str, Sequence[str]] | None
) -> str:
    """The first of ``found`` not present in ``passage`` ("" when all are)."""
    aliases = aliases or {}
    have: set[str] = set()
    for tok in tokenize_v2(passage):
        have.add(tok)
        folded = CALENDAR_FOLD.get(tok)
        if folded is not None:
            have.add(folded)

    def all_in_have(text: str) -> bool:
        words = tokenize_v2(text)
        return bool(words) and all(w in have for w in words)

    def present(tok: str) -> bool:
        if tok in have:
            return True
        folded = CALENDAR_FOLD.get(tok)
        if folded is not None and folded in have:
            return True
        # An alias counts only when EVERY one of its words is present.
        return any(all_in_have(alias) for alias in aliases.get(tok, ()))

    def all_present(text: str) -> bool:
        return all(present(tok) for tok in tokenize_v2(text))

    for name in found:
        # "Wwft-related": the whole word first, then only its capitalised parts.
        if "-" in name and not all_present(name) and not go.contains_any(name, "0123456789"):
            parts = capitalised_parts(name)
            if parts and all_present(" ".join(parts)):
                continue
        alts = aliases.get(go.lower(name))
        if alts is not None:
            found_alias = False
            for alt in alts:
                if all(at in have for at in tokenize_v2(alt)):
                    found_alias = True
                    break
            if found_alias:
                continue
        for tok in tokenize_v2(name):
            if not present(tok):
                return name
    return ""


def capitalised_parts(word: str) -> list[str]:
    """The hyphen-separated parts starting with a capital."""
    return [part for part in word.split("-") if part and go.is_upper(part[0])]


def _calendar_fold() -> dict[str, str]:
    pairs = (
        ("january", "januari"),
        ("february", "februari"),
        ("march", "maart"),
        ("april", "april"),
        ("may", "mei"),
        ("june", "juni"),
        ("july", "juli"),
        ("august", "augustus"),
        ("september", "september"),
        ("october", "oktober"),
        ("november", "november"),
        ("december", "december"),
        ("monday", "maandag"),
        ("tuesday", "dinsdag"),
        ("wednesday", "woensdag"),
        ("thursday", "donderdag"),
        ("friday", "vrijdag"),
        ("saturday", "zaterdag"),
        ("sunday", "zondag"),
    )
    out: dict[str, str] = {}
    for en, nl in pairs:
        out[en] = nl
        out[nl] = nl
    return out


#: English month and weekday names to Dutch, both directions, to ONE canonical
#: form (the Dutch). Closed on purpose.
CALENDAR_FOLD: dict[str, str] = _calendar_fold()


@dataclass(frozen=True)
class GuardConfig:
    """The caller's configuration the guards read."""

    actors: ActorLexicon
    aliases: Mapping[str, Sequence[str]] | None = None
    pairs: Sequence[QualifierPair] = ()
    verbs: Sequence[VerbPair] = ()
    #: The prepared glossary; None reads as empty.
    gloss: PreparedGlossary | None = None
    #: VerifyOptions.disable_definitions.
    no_definitions: bool = False
    #: Every explicit definition in the evidence, by document id.
    doc_defs: Mapping[str, list[Definition]] = field(default_factory=dict)
    subtypes: Sequence[SubtypeHead] = ()
    #: The text is a list lead-in checked on its own (union rule): it states no
    #: fact, so the hedge guard does not read it.
    fragment: bool = False
    #: VerifyOptions.conjunct_presence.
    conjunct_presence: bool = False

    def as_fragment(self) -> GuardConfig:
        return replace(self, fragment=True)


def guards(claim: str, claim_language: str, eu: EvidenceUnit, cfg: GuardConfig) -> str:
    """Every deterministic guard; the first refusal, or ""."""
    reason = number_guard(claim, claim_language, eu.text, eu.language)
    if reason:
        return reason
    reason = unit_guard(claim, claim_language, eu.text, eu.language)
    if reason:
        return reason
    for g in (
        negation_guard,
        clause_negation_guard,
        polarity_swap_guard,
        qualifier_guard,
        scope_guard,
    ):
        reason = g(claim, eu.text)
        if reason:
            return reason
    checks: tuple[Callable[[], str], ...] = (
        lambda: verify_roles.role_guard(claim, claim_language, eu, cfg.actors),
        lambda: verify_relations.relation_guard(claim, claim_language, eu, cfg.actors),
        # A cut span of a unit sentence whose restriction follows (P1) is
        # refused on every path, not only after the gate.
        lambda: truncation_guard(claim, eu.text),
        lambda: verify_exclusions.exclusion_guard(claim, claim_language, eu, cfg),
        lambda: verify_hedges.hedge_guard(claim, claim_language, eu, cfg),
        lambda: verify_verbpairs.verb_pair_guard(claim, claim_language, eu, cfg.verbs, cfg),
        lambda: verify_definitions.definition_guard(claim, claim_language, eu, cfg),
        lambda: verify_subtypes.subtype_guard(claim, eu, cfg),
        lambda: verify_conditions.condition_guard(claim, claim_language, eu, cfg),
        lambda: verify_conjuncts.conjunct_token_guard(claim, claim_language, eu, cfg),
        lambda: verify_qualifier_pairs.qualifier_pair_guard(claim, claim_language, eu, cfg.pairs),
        lambda: verify_parties.party_swap_guard(claim, claim_language, eu, cfg.actors),
        lambda: verify_parties.subject_swap_guard(claim, claim_language, eu, cfg),
        lambda: verify_parties.value_row_guard(claim, claim_language, eu),
    )
    for check in checks:
        reason = check()
        if reason:
            return reason
    return name_guard_with(claim, eu.text + "\n" + eu.document_id, cfg.aliases)


#: Double-quoted spans in the common typographic styles. Single quotes are not
#: quotes here: they collide with apostrophes.
QUOTE_PATTERN = re.compile(
    r'"([^"]+)"|\u201c([^\u201d]+)\u201d|„([^\u201d\u201c]+)[\u201d\u201c]|«([^»]+)»'
)

#: The shortest span that counts as a quote.
MIN_QUOTE_TOKENS = 3


def quotes(claim: str) -> list[str]:
    """The claim's quoted spans that are long enough to anchor it."""
    out: list[str] = []
    for m in QUOTE_PATTERN.finditer(claim):
        for g in m.groups():
            if g and len(tokenize_v2(g)) >= MIN_QUOTE_TOKENS:
                out.append(g)
    return out


#: Ends a clause: sentence punctuation followed by space or end, a comma
#: followed by space ("25,50" is not a break), a dash used as a clause separator
#: (em / en dash anywhere, "-" only between spaces), or a newline.
CLAUSE_BREAK = re.compile(
    r"[.!?;:]+(?:[\t\n\f\r ]|\Z)|,[\t\n\f\r ]|[\t\n\f\r ]*[\u2014\u2013][\t\n\f\r ]*"
    r"|[\t\n\f\r ]-[\t\n\f\r ]|\n"
)

#: Start a NEW coordinated clause.
COORDINATORS = frozenset({"en", "maar", "of", "want", "dus", "and", "but", "or", "so"})


def clause_negation_guard(claim: str, passage: str) -> str:
    """Close the verb-final hole in the ADR-0009 predicate (see the Go comment)."""
    claim_tokens = tokenize_v2(claim)
    in_claim: dict[str, int] = {}
    for tok in claim_tokens:
        if tok in POLARITY_MARKERS:
            in_claim[tok] = in_claim.get(tok, 0) + 1
    for clause in go.split(CLAUSE_BREAK, passage):
        clause_tokens = tokenize_v2(clause)
        span = align(claim_tokens, clause_tokens)
        if span is None:
            continue
        matched = clause_tokens[span.start : span.end + 1]
        in_span: dict[str, int] = {}
        for tok in matched:
            if tok in POLARITY_MARKERS:
                in_span[tok] = in_span.get(tok, 0) + 1
        # In span order, so the reason names the same marker on every run.
        for tok in matched:
            n = in_span.get(tok)
            if n is not None and in_claim.get(tok, 0) < n:
                return f"negation guard: the claim drops {go.quote(tok)} from the matched words"
        tail = clause_tokens[span.end + 1 :][:MAX_SINGLE_GAP]
        for tok in tail:
            if tok in COORDINATORS:
                break
            if tok in POLARITY_MARKERS and in_claim.get(tok, 0) == 0:
                return (
                    f"negation guard: the passage clause carries {go.quote(tok)} "
                    "after the matched words"
                )
    return ""


#: Open a clause-internal continuation that narrows what came before it.
RESTRICTIVE_TAIL = frozenset(
    {
        "met",
        "van",
        "voor",
        "tot",
        "boven",
        "onder",
        "bij",
        "aan",
        "zonder",
        "behalve",
        "uitgezonderd",
        "alleen",
        "uitsluitend",
        "mits",
        "tenzij",
        "indien",
        "als",
        "wanneer",
        "die",
        "dat",
        "waarvan",
        "with",
        "for",
        "above",
        "below",
        "over",
        "provided",
        "unless",
        "if",
        "when",
        "who",
        "that",
        "which",
        "without",
        "except",
        "only",
    }
)


def truncation_guard(claim: str, passage: str) -> str:
    """Refuse a claim that is a cut span of a unit sentence whose restriction
    follows (see the Go comment)."""
    claim_tokens = tokenize_v2(claim)
    restricted = ""
    for clause in go.split(CLAUSE_BREAK, soft_join(passage)):
        clause_tokens = tokenize_v2(clause)
        span = align(claim_tokens, clause_tokens)
        if span is None:
            continue
        tail = clause_tokens[span.end + 1 :]
        nxt = tail[0] if tail else ""
        narrows = nxt in RESTRICTIVE_TAIL
        if nxt == "up" and len(tail) > 1 and tail[1] == "to":
            narrows, nxt = True, "up to"
        if nxt == "in" and len(tail) > 2 and tail[1] == "so" and tail[2] == "far":
            narrows, nxt = True, "in so far as"
        if not narrows:
            return ""  # a clause that states the claim as it is
        if restricted == "":
            restricted = nxt
    if restricted == "":
        return ""
    return (
        "truncation guard: the claim omits a restriction the source attaches "
        f"({go.quote(restricted)})"
    )


BOUND_UPPER = "upper"
BOUND_LOWER = "lower"

BOUND_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("no", "later", "than"), BOUND_UPPER),
    (("not", "later", "than"), BOUND_UPPER),
    (("no", "more", "than"), BOUND_UPPER),
    (("not", "more", "than"), BOUND_UPPER),
    (("at", "most"), BOUND_UPPER),
    (("up", "to"), BOUND_UPPER),
    (("niet", "later", "dan"), BOUND_UPPER),
    (("niet", "meer", "dan"), BOUND_UPPER),
    (("uiterlijk",), BOUND_UPPER),
    (("maximaal",), BOUND_UPPER),
    (("hooguit",), BOUND_UPPER),
    (("ten", "hoogste"), BOUND_UPPER),
    (("maximum",), BOUND_UPPER),
    (("no", "earlier", "than"), BOUND_LOWER),
    (("not", "earlier", "than"), BOUND_LOWER),
    (("no", "less", "than"), BOUND_LOWER),
    (("not", "less", "than"), BOUND_LOWER),
    (("no", "fewer", "than"), BOUND_LOWER),
    (("at", "least"), BOUND_LOWER),
    (("niet", "eerder", "dan"), BOUND_LOWER),
    (("niet", "minder", "dan"), BOUND_LOWER),
    (("minimaal",), BOUND_LOWER),
    (("ten", "minste"), BOUND_LOWER),
    (("tenminste",), BOUND_LOWER),
    (("minimum",), BOUND_LOWER),
)

SPLIT_COMPARATIVES: dict[str, str] = {
    "meer": BOUND_UPPER,
    "more": BOUND_UPPER,
    "hoger": BOUND_UPPER,
    "higher": BOUND_UPPER,
    "langer": BOUND_UPPER,
    "longer": BOUND_UPPER,
    "later": BOUND_UPPER,
    "groter": BOUND_UPPER,
    "larger": BOUND_UPPER,
    "bigger": BOUND_UPPER,
    "zwaarder": BOUND_UPPER,
    "heavier": BOUND_UPPER,
    "minder": BOUND_LOWER,
    "less": BOUND_LOWER,
    "fewer": BOUND_LOWER,
    "lager": BOUND_LOWER,
    "lower": BOUND_LOWER,
    "korter": BOUND_LOWER,
    "shorter": BOUND_LOWER,
    "eerder": BOUND_LOWER,
    "earlier": BOUND_LOWER,
    "kleiner": BOUND_LOWER,
    "smaller": BOUND_LOWER,
}

EXCEED_VERBS = frozenset({"exceed", "exceeds", "overschrijden", "overschrijdt"})


@dataclass(frozen=True)
class SplitBound:
    marker: int  # the polarity marker's position
    direction: str


def split_bounds(tokens: Sequence[str]) -> list[SplitBound]:
    """The split bounds in tokens: "mag niet hoger zijn dan", "may not exceed"."""
    out: list[SplitBound] = []
    for i, t in enumerate(tokens):
        if t not in POLARITY_MARKERS:
            continue
        for j in range(i + 1, min(len(tokens), i + 5)):
            if tokens[j] in EXCEED_VERBS:
                out.append(SplitBound(i, BOUND_UPPER))
                break
            d = SPLIT_COMPARATIVES.get(tokens[j])
            if d is not None and j + 1 < len(tokens) and tokens[j + 1] in ("than", "dan"):
                out.append(SplitBound(i, d))
                break
    return out


def bound_directions(tokens: Sequence[str]) -> set[str]:
    """The bound directions present in tokens."""
    out: set[str] = set()
    for words, direction in BOUND_PHRASES:
        if verify_parties.find_spans(tokens, words):
            out.add(direction)
    for b in split_bounds(tokens):
        out.add(b.direction)
    return out


def bound_marker_positions(tokens: Sequence[str], passage: set[str]) -> set[int]:
    """Positions of bound phrases in the claim whose direction the passage also
    has — their markers are not negations."""
    out: set[int] = set()
    for words, direction in BOUND_PHRASES:
        if direction not in passage:
            continue
        for sp in verify_parties.find_spans(tokens, words):
            out.update(range(sp.start, sp.end))
    for b in split_bounds(tokens):
        if b.direction in passage:
            out.add(b.marker)
    return out


def cents_as_euros(m: NumberMatch) -> str:
    """A number's key, with an amount in cents read in euros."""
    if m.unit in ("cent", "cents", "ct", "eurocent", "eurocents") and m.reading.value is not None:
        return rat_key(Fraction(m.reading.value) / 100)
    return m.reading.key


#: ISO codes a claim writes for the euro sign ("EUR 2.40").
CURRENCY_CODES = frozenset({"eur", "usd", "gbp"})

#: Carry a negation in the word itself (passage side only; closed on purpose).
NEGATIVE_WORDS = frozenset(
    {
        "unused",
        "unpaid",
        "untaken",
        "unclaimed",
        "unspent",
        "ongebruikt",
        "ongebruikte",
        "onbetaald",
        "onbetaalde",
        "onopgenomen",
    }
)
