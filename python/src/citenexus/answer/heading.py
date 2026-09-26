"""Headings a host must not exempt from verification.

Port of ``golang/answer/heading.go`` (ADR-0016). ``verify_answer`` itself
exempts nothing. Hosts that serve an answer with its layout exempt refused
lines that make no factual assertion (headings, lead-ins); a heading can assert
a rule, though, and an exempt heading is served UNCHECKED. A host asks two
questions before it exempts a heading::

    claim, _ = heading_needs_check(line, lang)
    if claim:
        ...  # keep verify_answer's verdict: the heading is a claim
    elif reason := heading_name_unsupported(line, evidence, aliases):
        ...  # refuse it with reason: it names something no unit mentions
    else:
        ...  # exempt: served unchecked

Both can only turn an exemption into a refusal; neither admits anything.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_guards
from citenexus.answer.verify import is_stopword
from citenexus.answer.verify_guards_model import CONTEXT_STOP, NUMBER_WORDS
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit

#: "Wat je krijgt bij ziekte" (5 words) stays a heading; a sixth word with a
#: verb makes it a sentence.
DEFAULT_HEADING_VERB_WORDS = 5


@dataclass(frozen=True)
class HeadingRules:
    """The closed word tables ``heading_needs_check_with`` reads, keyed by
    primary language subtag. A language with no entry reads every table."""

    #: Obligation / permission words and phrases ("moet", "recht op", "must").
    modals: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: Restrict to one case ("alleen", "only").
    exclusives: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: Finite verbs; one of them plus more than ``verb_words`` words.
    verbs: Mapping[str, Sequence[str]] = field(default_factory=dict)
    #: Zero means DEFAULT_HEADING_VERB_WORDS.
    verb_words: int = 0


DEFAULT_HEADING_RULES = HeadingRules(
    modals={
        "nl": ("mag", "mogen", "moet", "moeten", "verplicht", "verplichte", "recht op"),
        "en": ("must", "may", "shall", "entitled"),
    },
    exclusives={
        "nl": ("alleen", "uitsluitend", "enkel", "slechts"),
        "en": ("only", "solely", "exclusively"),
    },
    verbs={
        "nl": (
            "is",
            "zijn",
            "wordt",
            "worden",
            "heeft",
            "hebben",
            "krijgt",
            "krijg",
            "krijgen",
            "geldt",
            "gelden",
            "kan",
            "kun",
            "kunt",
            "kunnen",
            "betaalt",
            "betalen",
            "valt",
            "vallen",
            "blijft",
            "blijven",
            "gaat",
            "gaan",
            "loopt",
            "telt",
            "vervalt",
            "ontvang",
            "ontvangt",
            "bouw",
            "bouwt",
            "neem",
            "neemt",
        ),
        "en": (
            "is",
            "are",
            "has",
            "have",
            "can",
            "will",
            "get",
            "gets",
            "applies",
            "apply",
            "pays",
            "pay",
            "counts",
            "remains",
            "stays",
            "receive",
            "receives",
            "take",
            "takes",
            "need",
            "needs",
            "does",
            "do",
        ),
    },
)

_WORD_TRIM = "\"'“”‘’()[]{}.,;:!?"  # noqa: RUF001 — typographic quotes are the point


def heading_needs_check(heading: str, language: str = "") -> tuple[bool, str]:
    """Whether a line a host would exempt as a heading states a rule."""
    return heading_needs_check_with(heading, language, DEFAULT_HEADING_RULES)


def heading_needs_check_with(heading: str, language: str, rules: HeadingRules) -> tuple[bool, str]:
    """``heading_needs_check`` with the host's own tables (they replace the
    defaults entirely). Numbers are always read."""
    text = heading_text(heading)
    words = _va.LIST_LEAD_TOKEN.findall(text)
    tokens = tokenize_v2(text)
    capitalised: set[str] = set()  # tokens written ONLY capitalised
    lowered: set[str] = set()
    for w in words:
        for tok in tokenize_v2(w):
            bare = w.strip(_WORD_TRIM)
            if bare and go.is_upper(bare[0]):
                capitalised.add(tok)
            else:
                lowered.add(tok)
    lang = _va.primary_language(language)

    def calendar_capital(w: str) -> bool:
        return w in verify_guards.CALENDAR_FOLD and w in capitalised and w not in lowered

    found = _match_table(tokens, _table_for(rules.modals, lang), calendar_capital)
    if found is not None:
        return True, f"heading states a rule: modal {go.quote(found)}"
    found = _match_table(tokens, _table_for(rules.exclusives, lang), None)
    if found is not None:
        return True, f"heading states a rule: exclusive {go.quote(found)}"
    for tok in tokens:
        if go.contains_any(tok, "0123456789"):
            return True, f"heading states a rule: number {go.quote(tok)}"
        if tok in NUMBER_WORDS and tok not in ("een", "one"):
            return True, f"heading states a rule: number {go.quote(tok)}"
    limit = rules.verb_words or DEFAULT_HEADING_VERB_WORDS
    if len(tokens) > limit:
        found = _match_table(tokens, _table_for(rules.verbs, lang), None)
        if found is not None:
            return True, f"heading states a rule: verb {go.quote(found)} in {len(tokens)} words"
    return False, ""


def heading_name_unsupported(
    heading: str,
    evidence: Sequence[EvidenceUnit],
    aliases: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """A refusal reason when the heading names something that appears in NONE
    of the evidence units ("" when every name is somewhere in the evidence)."""
    text = heading_text(heading)
    found = verify_guards.names(text)
    if _title_case(text):
        found = [n for n in found if _strong(n)]
    if not found:
        return ""
    parts: list[str] = []
    for eu in evidence:
        parts.extend((eu.text, "\n", eu.document_id, "\n"))
    name = verify_guards.absent_name(found, "".join(parts), aliases)
    if name:
        return f"heading name guard: {go.quote(name)} is in no evidence unit"
    return ""


_HEADING_MARKER = re.compile(
    r"^[\t\n\f\r ]*(?:#{1,6}[\t\n\f\r ]+|>[\t\n\f\r ]*|(?:[-*•·]|[0-9]{1,3}[.)])[\t\n\f\r ]+)*"
)


def heading_text(heading: str) -> str:
    """The heading as a reader sees it: markup and a leading heading, quote or
    list marker removed."""
    return go.trim_space(_HEADING_MARKER.sub("", _va.strip_markup(heading), count=1))


def _table_for(table: Mapping[str, Sequence[str]], lang: str) -> list[str]:
    if lang in table:
        return list(table[lang])
    out: list[str] = []
    for entries in table.values():
        out.extend(entries)
    return out


def _match_table(
    tokens: Sequence[str], entries: Sequence[str], skip: Callable[[str], bool] | None
) -> str | None:
    """The first entry (a word or a phrase) found in tokens."""
    for entry in entries:
        et = tokenize_v2(entry)
        if not et:
            continue
        for i in range(len(tokens) - len(et) + 1):
            if list(tokens[i : i + len(et)]) != et:
                continue
            if len(et) == 1 and skip is not None and skip(et[0]):
                continue
            return entry
    return None


def _title_case(text: str) -> bool:
    """At least two words, and every non-function word starts with a capital."""
    capitals = 0
    for w in _va.LIST_LEAD_TOKEN.findall(text):
        bare = w.strip(_WORD_TRIM + "|")
        if not bare or not go.is_letter(bare[0]):
            continue
        if go.is_upper(bare[0]):
            capitals += 1
            continue
        low = go.lower(bare)
        if low in CONTEXT_STOP or is_stopword(low):
            continue
        return False
    return capitals >= 2


def _strong(name: str) -> bool:
    """A name by its form, not its case — an acronym or letters with digits."""
    has_digit = has_letter = False
    all_upper = True
    for r in name:
        if go.is_digit(r):
            has_digit = True
        elif go.is_letter(r):
            has_letter = True
            if not go.is_upper(r):
                all_upper = False
    return has_letter and (has_digit or all_upper)
