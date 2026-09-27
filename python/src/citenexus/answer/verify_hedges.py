"""The hedge guard: a claim that states absolutely what the source hedges.

Port of ``golang/answer/verify_hedges.go`` (ADR-0016). Two readings with closed
NL/EN tables whose classes are language-independent:

* ABSOLUTE ADDED — the claim carries an absolutizer (altijd, always, at any
  time, …) and the unit carries none.
* HEDGE DROPPED — the unit sentence the claim follows attaches a hedge
  (permission/possibility, an upper bound, a softener) and the claim carries no
  hedge of that class.

Can only refuse.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_conditions, verify_guards, verify_parties
from citenexus.answer.numbers import numbers_in, verbatim_in
from citenexus.answer.tables import POLARITY_MARKERS
from citenexus.answer.verify_guards_model import soft_join
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig
    from citenexus.answer.verify_parties import Span

ABSOLUTIZERS: tuple[tuple[str, ...], ...] = (
    ("altijd",),
    ("always",),
    ("steeds",),
    ("te", "allen", "tijde"),
    ("at", "all", "times"),
    ("voortdurend",),
    ("at", "any", "time"),
    ("op", "elk", "moment"),
    ("whenever",),
    ("wanneer", "ze", "maar", "willen"),
    ("without", "restriction"),
    ("zonder", "beperking"),
    ("for", "any", "reason"),
    ("om", "welke", "reden", "dan", "ook"),
    ("ongeacht",),
    ("regardless",),
    ("in", "alle", "gevallen"),
    ("in", "all", "cases"),
    ("for", "as", "long", "as", "needed"),
    ("zo", "lang", "als", "nodig"),
    ("at", "all"),
    ("onbeperkt",),
    ("unlimited",),
)

HEDGE_PERMISSION = "permission"
HEDGE_UPPER = "upper bound"
HEDGE_SOFTENER = "softener"

HEDGE_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("mag",), HEDGE_PERMISSION),
    (("mogen",), HEDGE_PERMISSION),
    (("kan",), HEDGE_PERMISSION),
    (("kunnen",), HEDGE_PERMISSION),
    (("kun",), HEDGE_PERMISSION),
    (("kunt",), HEDGE_PERMISSION),
    (("may",), HEDGE_PERMISSION),
    (("can",), HEDGE_PERMISSION),
    (("might",), HEDGE_PERMISSION),
    (("maximaal",), HEDGE_UPPER),
    (("ten", "hoogste"), HEDGE_UPPER),
    (("hooguit",), HEDGE_UPPER),
    (("tot", "een", "maximum"), HEDGE_UPPER),
    (("maximum",), HEDGE_UPPER),
    (("up", "to"), HEDGE_UPPER),
    (("at", "most"), HEDGE_UPPER),
    (("no", "more", "than"), HEDGE_UPPER),
    (("capped",), HEDGE_UPPER),
    (("in", "beginsel"), HEDGE_SOFTENER),
    (("in", "principe"), HEDGE_SOFTENER),
    (("in", "de", "regel"), HEDGE_SOFTENER),
    (("zoveel", "mogelijk"), HEDGE_SOFTENER),
    (("in", "principle"), HEDGE_SOFTENER),
    (("as", "a", "rule"), HEDGE_SOFTENER),
    (("as", "far", "as", "possible"), HEDGE_SOFTENER),
    (("as", "much", "as", "possible"), HEDGE_SOFTENER),
)


def hedges_in(tokens: Sequence[str], text: str) -> dict[str, str]:
    """The hedge classes in tokens (class -> the phrase that carries it)."""
    out: dict[str, str] = {}
    tokens = list(tokens)
    # A purpose or result clause does not hedge the main fact.
    for i, t in enumerate(tokens):
        if (
            t in ("zodat", "opdat")
            or (t == "so" and i + 1 < len(tokens) and tokens[i + 1] == "that")
            or (
                t == "in"
                and i + 2 < len(tokens)
                and tokens[i + 1] == "order"
                and tokens[i + 2] == "to"
            )
        ):
            tokens = tokens[:i]
            break
    bound_marker: set[int] = set()
    for b in verify_guards.split_bounds(tokens):
        bound_marker.add(b.marker)
        if b.direction == verify_guards.BOUND_UPPER and HEDGE_UPPER not in out:
            out[HEDGE_UPPER] = tokens[b.marker] + " … " + "than"
    for words, cls in HEDGE_PHRASES:
        for sp in verify_parties.find_spans(tokens, words):
            # A negated modal is a PROHIBITION, not a hedge.
            if cls == HEDGE_PERMISSION:
                negated = False
                for k in range(sp.end, min(len(tokens), sp.end + 5)):
                    if tokens[k] in POLARITY_MARKERS and k not in bound_marker:
                        negated = True
                if negated:
                    continue
            if cls not in out:
                out[cls] = " ".join(words)
    if TOT_AMOUNT.search(go.lower(text)) and HEDGE_UPPER not in out:
        out[HEDGE_UPPER] = "tot"
    return out


_W = go.WS
CLAIM_RANGE = re.compile(
    r"\b[0-9][0-9.,]*" + _W + r"*(?:tot|to|t/m|-|–)" + _W + r"*[0-9]"  # noqa: RUF001
    r"|\b(?:tussen|between)" + _W + r"+[0-9][0-9.,]*" + _W + r"+(?:en|and)" + _W + r"+[0-9]",
    re.ASCII,
)
TO_SAME_AMOUNT = re.compile(r"\b(?:to|tot)" + _W + r"*(?:€|eur\b)?" + _W + r"*[0-9]", re.ASCII)
TOT_AMOUNT = re.compile(
    r"\btot" + _W + r"*(?:€|eur\b|[0-9][0-9.,]*" + _W + r"*(?:%|euro\b|procent\b))", re.ASCII
)

#: Hedge a CLAIM the way the tabled phrases do, in other constructions. Read on
#: the claim side only, so they can never make the guard refuse more.
HEDGE_EQUIVALENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("normaal", "gesproken"), HEDGE_SOFTENER),
    (("normaliter",), HEDGE_SOFTENER),
    (("gewoonlijk",), HEDGE_SOFTENER),
    (("doorgaans",), HEDGE_SOFTENER),
    (("meestal",), HEDGE_SOFTENER),
    (("in", "het", "algemeen"), HEDGE_SOFTENER),
    (("over", "het", "algemeen"), HEDGE_SOFTENER),
    (("als", "regel"), HEDGE_SOFTENER),
    (("in", "de", "meeste", "gevallen"), HEDGE_SOFTENER),
    (("in", "beginsel"), HEDGE_SOFTENER),
    (("normally",), HEDGE_SOFTENER),
    (("usually",), HEDGE_SOFTENER),
    (("generally",), HEDGE_SOFTENER),
    (("in", "general"), HEDGE_SOFTENER),
    (("typically",), HEDGE_SOFTENER),
    (("ordinarily",), HEDGE_SOFTENER),
    (("in", "most", "cases"), HEDGE_SOFTENER),
    (("as", "a", "general", "rule"), HEDGE_SOFTENER),
    (("toegestaan",), HEDGE_PERMISSION),
    (("mogelijk",), HEDGE_PERMISSION),
    (("mogelijkheid",), HEDGE_PERMISSION),
    (("allowed",), HEDGE_PERMISSION),
    (("permitted",), HEDGE_PERMISSION),
    (("possible",), HEDGE_PERMISSION),
    (("option",), HEDGE_PERMISSION),
    (("optional",), HEDGE_PERMISSION),
)


def claim_hedge_equivalents(tokens: Sequence[str]) -> set[str]:
    """The classes HEDGE_EQUIVALENTS give the claim; a negated one gives none."""
    out: set[str] = set()
    for words, cls in HEDGE_EQUIVALENTS:
        for sp in verify_parties.find_spans(tokens, words):
            # "zo snel mogelijk", "as soon as possible": a degree.
            if sp.start >= 1 and tokens[sp.start - 1] in ("zoveel", "zo"):
                continue
            if sp.start >= 2 and tokens[sp.start - 2] in ("zo", "as"):
                continue
            if cls == HEDGE_PERMISSION and not predicative(tokens, sp):
                continue
            negated = False
            for k in range(sp.start - 3, min(len(tokens), sp.end + 3)):
                if k < 0 or sp.start <= k < sp.end:
                    continue
                if tokens[k] in POLARITY_MARKERS:
                    negated = True
            if not negated:
                out.add(cls)
    return out


PERMISSION_COPULAS = frozenset(
    {
        "is",
        "are",
        "be",
        "was",
        "were",
        "been",
        "zijn",
        "wordt",
        "worden",
        "has",
        "have",
        "had",
        "heeft",
        "hebben",
        "biedt",
        "bieden",
    }
)
PERMISSION_COMPLEMENTS = frozenset({"to", "that", "for", "om", "dat", "te"})


def predicative(tokens: Sequence[str], sp: Span) -> bool:
    for k in range(sp.start - 3, sp.start):
        if k >= 0 and tokens[k] in PERMISSION_COPULAS:
            return True
    return sp.end < len(tokens) and tokens[sp.end] in PERMISSION_COMPLEMENTS


def has_any(tokens: Sequence[str], phrases: Sequence[Sequence[str]]) -> str:
    for p in phrases:
        if verify_parties.find_spans(tokens, p):
            return " ".join(p)
    return ""


def hedge_guard(claim: str, claim_language: str, eu: EvidenceUnit, cfg: GuardConfig) -> str:
    """See the module docstring."""
    if cfg.fragment:
        return ""  # a lead-in fragment states no fact of its own
    claim_tokens = tokenize_v2(claim)
    unit_tokens = tokenize_v2(eu.text)
    absolute = has_any(claim_tokens, ABSOLUTIZERS)
    if absolute and not has_any(unit_tokens, ABSOLUTIZERS):
        return (
            f"hedge guard: the claim says {go.quote(absolute)}; the source states no such absolute"
        )
    cross = _va.cross_language(claim_language, eu.language)
    c = verify_conditions.Carrier(set(claim_tokens), cross, verify_conditions.gloss_idx(cfg.gloss))
    claim_numbers = {
        m.reading.key for m in numbers_in(claim, claim_language, verbatim_in(eu.text, eu.language))
    }
    best, best_n, tie = "", 0, False
    for s in go.split(verify_parties.SENTENCE_BREAK, soft_join(eu.text)):
        n = 0
        seen: set[str] = set()
        for t in tokenize_v2(s):
            has, _ = c.carried(t)
            if t not in seen and has and verify_conditions.condition_content(t):
                seen.add(t)
                n += 1
        for m in numbers_in(s, eu.language):
            if m.reading.key in claim_numbers:
                n += 2  # a shared value anchors the sentence in any language
        if n > best_n:
            best, best_n, tie = s, n, False
        elif n == best_n and n > 0:
            tie = True
    if best_n < 2 or tie:
        return ""
    unit_hedges = hedges_in(tokenize_v2(best), best)
    claim_hedges = hedges_in(claim_tokens, claim)
    for cls in claim_hedge_equivalents(claim_tokens):
        claim_hedges[cls] = cls
    lowered_claim = go.lower(claim)
    for cls in (HEDGE_PERMISSION, HEDGE_UPPER, HEDGE_SOFTENER):
        word = unit_hedges.get(cls)
        if word is None or cls in claim_hedges:
            continue
        # A range in the claim states its own bounds.
        if cls == HEDGE_UPPER and CLAIM_RANGE.search(lowered_claim):
            continue
        # "aanvullen tot 70%" / "top up to 70%".
        if cls == HEDGE_UPPER and word == "tot" and TO_SAME_AMOUNT.search(lowered_claim):
            continue
        return (
            f"hedge guard: the source limits it ({cls} {go.quote(word)}) "
            "and the claim states it without"
        )
    return ""
