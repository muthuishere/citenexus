"""The exclusion guard: a claim that asserts a fact for a group the unit
EXCLUDES from it.

Port of ``golang/answer/verify_exclusions.go`` (ADR-0016). A unit sentence
excludes a group with a marker (behalve, except, …), a negated sentence opened
by "voor G" / "for G", or an excluded predicate ("zijn uitgesloten", "are not
entitled"). The claim is refused when it names an excluded group — every
readable content word of one group — or speaks about everyone, unless it
restates the exclusion itself. A group with no readable word gives NO
VERDICT. Can only refuse.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_conditions, verify_parties
from citenexus.answer.verify_guards_model import number_value, soft_join, unit_of
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig

EXCLUSION_MARKERS: tuple[tuple[str, ...], ...] = (
    ("behalve",),
    ("uitgezonderd",),
    ("met", "uitzondering", "van"),
    ("niet", "voor"),
    ("niet", "van", "toepassing", "op"),
    ("except",),
    ("excluding",),
    ("other", "than"),
    ("with", "the", "exception", "of"),
    ("not", "applicable", "to"),
    ("not", "for"),
)

#: Follow an excluded group as its predicate.
EXCLUDED_PREDICATES: tuple[tuple[str, ...], ...] = (
    ("zijn", "uitgesloten"),
    ("is", "uitgesloten"),
    ("hebben", "geen", "recht"),
    ("heeft", "geen", "recht"),
    ("komen", "niet", "in", "aanmerking"),
    ("komt", "niet", "in", "aanmerking"),
    ("are", "excluded"),
    ("is", "excluded"),
    ("are", "not", "entitled"),
    ("is", "not", "entitled"),
    ("are", "not", "eligible"),
    ("is", "not", "eligible"),
    ("are", "not", "enrolled"),
    ("is", "not", "enrolled"),
)

UNIVERSAL_WORDS = frozenset(
    {"alle", "iedereen", "iedere", "elke", "ieder", "all", "every", "everyone", "everybody"}
)

GROUP_VERBS = frozenset(
    {
        "geldt",
        "gelden",
        "is",
        "zijn",
        "heeft",
        "hebben",
        "komt",
        "komen",
        "krijgt",
        "krijgen",
        "ontvangt",
        "ontvangen",
        "kan",
        "kunnen",
        "mag",
        "mogen",
        "applies",
        "apply",
        "are",
        "has",
        "have",
        "can",
        "may",
        "receive",
        "receives",
    }
)

#: Separates a group's head from its prepositional qualifier.
QUALIFIER_MARK = "|"

GROUP_PREPOSITIONS = frozenset(
    {"in", "met", "van", "vanaf", "op", "bij", "with", "from", "of", "on", "at"}
)


def split_groups(tokens: Sequence[str]) -> list[list[str]]:
    """A segment's groups, split at en/and/or/of, each as its content words."""
    out: list[list[str]] = []
    cur: list[str] = []

    def flush() -> None:
        nonlocal cur
        if cur:
            out.append(cur)
        cur = []

    for t in tokens:
        if t in ("en", "and", "or", "of"):
            flush()
            continue
        if t in ("die", "dat", "who", "that", "which", "waarvan"):
            # A relative clause describes the group; it is not another one.
            flush()
            return out
        if t in GROUP_PREPOSITIONS and cur and QUALIFIER_MARK not in cur:
            cur.append(QUALIFIER_MARK)
            continue
        if verify_conditions.condition_content(t):
            cur.append(t)
    flush()
    return out


def _until_verb(tokens: Sequence[str], k: int) -> int:
    while k < len(tokens) and tokens[k] not in GROUP_VERBS:
        k += 1
    return k


def excluded_groups(tokens: Sequence[str]) -> list[list[str]]:
    """The groups a unit sentence excludes."""
    groups: list[list[str]] = []
    for i in range(len(tokens)):
        for m in EXCLUSION_MARKERS:
            if i + len(m) > len(tokens) or tuple(tokens[i : i + len(m)]) != m:
                continue
            j = i + len(m)
            groups.extend(split_groups(tokens[j : _until_verb(tokens, j)]))
    markers = sum(1 for t in tokens if t in ("niet", "not", "geen", "no"))
    # "Voor G … niet": a negated sentence opened by voor/for.
    if len(tokens) > 1 and tokens[0] in ("voor", "for") and markers > 0:
        groups.extend(split_groups(tokens[1 : _until_verb(tokens, 1)]))
    # "G zijn uitgesloten" / "G are not entitled": the subject before it.
    for i in range(len(tokens)):
        for p in EXCLUDED_PREDICATES:
            if i + len(p) <= len(tokens) and tuple(tokens[i : i + len(p)]) == p:
                groups.extend(split_groups(tokens[:i]))
    return groups


def exclusion_guard(claim: str, claim_language: str, eu: EvidenceUnit, cfg: GuardConfig) -> str:
    """See the module docstring."""
    cross = _va.cross_language(claim_language, eu.language)
    claim_tokens = tokenize_v2(claim)
    c = verify_conditions.Carrier(set(claim_tokens), cross, verify_conditions.gloss_idx(cfg.gloss))
    # A claim that restates an exclusion or is negated states no inclusion.
    if excluded_groups(claim_tokens) or bound_or_negation(claim_tokens):
        return ""
    universal = False
    for i, t in enumerate(claim_tokens):
        if t not in UNIVERSAL_WORDS:
            continue
        # "once every four years", "elke week": a frequency, not everyone.
        if i + 1 < len(claim_tokens):
            nxt = claim_tokens[i + 1]
            if number_value(nxt, claim_language) is not None or unit_of(nxt) is not None:
                continue
        universal = True

    def carried(w: str) -> tuple[bool, bool]:
        for terms in cfg.actors.actors.values():
            if w in terms:
                return any(x in c.claim for x in terms), True
        return c.carried(w)

    for s in go.split(verify_parties.SENTENCE_BREAK, soft_join(eu.text)):
        for g in excluded_groups(tokenize_v2(s)):
            if universal:
                return (
                    "exclusion guard: the claim speaks about everyone; the passage excludes "
                    f"{go.quote(' '.join(without_mark(g)))}"
                )
            all_carried, known, qualifier, qualifier_known = True, 0, False, 0
            qualifier_words, qualifier_number = 0, False
            head_role = False
            for w in g:
                if w == QUALIFIER_MARK:
                    break
                if verify_conditions.actor_term(w, cfg.actors):
                    head_role = True
            for w in g:
                if (
                    w != QUALIFIER_MARK
                    and not qualifier
                    and head_role
                    and not verify_conditions.actor_term(w, cfg.actors)
                ):
                    continue
                if w == QUALIFIER_MARK:
                    qualifier = True
                    continue
                if qualifier:
                    qualifier_words += 1
                    if go.contains_any(w, "0123456789"):
                        qualifier_number = True
                has, ok = carried(w)
                if not ok:
                    continue
                known += 1
                if qualifier:
                    qualifier_known += 1
                if not has:
                    all_carried = False
            if qualifier and (
                qualifier_known == 0 or (qualifier_known < qualifier_words and not qualifier_number)
            ):
                continue
            if known > 0 and all_carried:
                return (
                    f"exclusion guard: the passage excludes {go.quote(' '.join(without_mark(g)))}"
                )
    return ""


_BOUND_OR_NEGATION = frozenset(
    {
        "niet",
        "not",
        "geen",
        "no",
        "never",
        "nooit",
        "without",
        "zonder",
        "behalve",
        "except",
        "excluding",
    }
)


def bound_or_negation(tokens: Sequence[str]) -> bool:
    return any(t in _BOUND_OR_NEGATION for t in tokens)


def without_mark(g: Sequence[str]) -> list[str]:
    return [w for w in g if w != QUALIFIER_MARK]
