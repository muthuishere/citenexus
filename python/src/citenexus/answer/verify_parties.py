"""Party swaps and value rows: two binding checks beyond the actor lexicon.

Port of ``golang/answer/verify_parties.go`` (ADR-0016).

* PARTY SWAP — a party is any content word the unit introduces with a
  determiner. The claim is refused when it does not align with any unit
  sentence as written but does once one of its parties is replaced by another
  party of the unit, or two are exchanged. A PAIR BINDS ITS VALUES: a claim
  stating a number is judged by which word the unit binds that number to.
* VALUE ROW — a number stated for one period moved to another.
* SUBJECT SWAP — across languages, through the glossary only.

All can only refuse.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_conditions, verify_qualifier_pairs, verify_roles
from citenexus.answer.numbers import clock_times, numbers_in
from citenexus.answer.verify import align, is_stopword
from citenexus.answer.verify_guards_model import (
    CONTEXT_STOP,
    quantities,
    same_quantity_in,
    soft_join,
)
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig
    from citenexus.answer.verify_roles import ActorLexicon

PARTY_DETERMINERS = frozenset(
    {"de", "het", "een", "the", "a", "an", "zijn", "haar", "hun", "his", "her", "their"}
)
ARTICLES = frozenset({"de", "het", "een", "the", "a", "an"})

SENTENCE_BREAK = re.compile(r"[.!?;]+(?:[\t\n\f\r ]|\Z)|\n")


def without_articles(tokens: Sequence[str]) -> list[str]:
    return [t for t in tokens if t not in ARTICLES]


def party_word(t: str) -> bool:
    if len(t) < 3 or go.contains_any(t, "0123456789") or is_stopword(t):
        return False
    return t not in CONTEXT_STOP


def unit_parties(sentences: Sequence[Sequence[str]]) -> list[list[str]]:
    """The determiner-introduced noun phrases of the unit: one word, or
    "X van Y" ("college van bestuur")."""
    seen: set[str] = set()
    out: list[list[str]] = []
    for toks in sentences:
        for i in range(len(toks) - 1):
            if toks[i] not in PARTY_DETERMINERS or not party_word(toks[i + 1]):
                continue
            phrases = [[toks[i + 1]]]
            if i + 3 < len(toks) and toks[i + 2] == "van" and party_word(toks[i + 3]):
                phrases.append([toks[i + 1], "van", toks[i + 3]])
            for p in phrases:
                k = " ".join(p)
                if k not in seen:
                    seen.add(k)
                    out.append(p)
    return out


@dataclass(frozen=True)
class Span:
    start: int
    end: int  # exclusive


def find_spans(tokens: Sequence[str], phrase: Sequence[str]) -> list[Span]:
    n = len(phrase)
    phrase = list(phrase)
    return [Span(i, i + n) for i in range(len(tokens) - n + 1) if list(tokens[i : i + n]) == phrase]


def replace_spans(tokens: Sequence[str], repl: dict[Span, list[str]]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        for s, r in repl.items():
            if s.start == i:
                out.extend(r)
                i = s.end
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def _sentences(text: str) -> list[list[str]]:
    out = []
    for s in go.split(SENTENCE_BREAK, soft_join(text)):
        toks = tokenize_v2(s)
        if toks:
            out.append(toks)
    return out


@dataclass(frozen=True)
class _Occurrence:
    at: Span
    party: list[str]
    pronoun: bool = False


def party_swap_guard(
    claim: str, claim_language: str, eu: EvidenceUnit, lexicon: ActorLexicon
) -> str:
    """See the module docstring."""
    sentences = _sentences(eu.text)
    bare = [without_articles(s) for s in sentences]
    claim_tokens = without_articles(tokenize_v2(claim))
    if not claim_tokens:
        return ""

    def aligns(tokens: list[str]) -> bool:
        return any(align(tokens, s) is not None for s in bare)

    parties = unit_parties(sentences)
    if aligns(claim_tokens):
        return pair_value_guard(claim, claim_language, eu)

    def class_of(p: Sequence[str]) -> str:
        if len(p) != 1:
            return ""
        for actor_id, terms in lexicon.actors.items():
            if p[0] in terms:
                return actor_id
        return ""

    in_claim: list[_Occurrence] = []
    for p in parties:
        for s in find_spans(claim_tokens, p):
            in_claim.append(_Occurrence(s, p))
    for t in lexicon.second_person_terms:
        for s in find_spans(claim_tokens, [t]):
            in_claim.append(_Occurrence(s, [t], pronoun=True))

    def same(a: list[str], b: list[str], a_pronoun: bool) -> bool:
        if a == b:
            return True
        ca, cb = class_of(a), class_of(b)
        if a_pronoun:
            ca = lexicon.second_person
        return ca != "" and ca == cb

    # One party replaced by another party of the unit (the reader's pronoun
    # only by a THIRD party — one the lexicon does not name).
    for o in in_claim:
        for p in parties:
            if same(o.party, p, o.pronoun) or (o.pronoun and class_of(p) != ""):
                continue
            if aligns(replace_spans(claim_tokens, {o.at: p})):
                b = bind_value(claim, claim_language, eu.text, eu.language, o.party, p)
                if b in (BIND_OWN, BIND_UNRESOLVED):
                    continue
                return (
                    f"role guard: {go.quote(' '.join(o.party))} "
                    f"where the passage says {go.quote(' '.join(p))}"
                )
    # Two parties of the claim exchanged.
    for i, a in enumerate(in_claim):
        for b_occ in in_claim[i + 1 :]:
            if a.at.end > b_occ.at.start and b_occ.at.end > a.at.start:
                continue
            if same(a.party, b_occ.party, a.pronoun):
                continue
            if aligns(replace_spans(claim_tokens, {a.at: b_occ.party, b_occ.at: a.party})):
                return (
                    f"role guard: {go.quote(' '.join(a.party))} and "
                    f"{go.quote(' '.join(b_occ.party))} are exchanged"
                )
    return ""


def pair_value_guard(claim: str, claim_language: str, eu: EvidenceUnit) -> str:
    """A number stated with one word of a pair the unit binds to the other."""
    sentences = _sentences(eu.text)
    claim_tokens = without_articles(tokenize_v2(claim))
    parties = unit_parties(sentences)
    for o in parties:
        if not find_spans(claim_tokens, o):
            continue
        for p in parties:
            if o == p or find_spans(claim_tokens, p) or not counterpart_of(o, p, sentences):
                continue
            if bind_value(claim, claim_language, eu.text, eu.language, o, p) == BIND_OTHER:
                return (
                    f"role guard: {go.quote(' '.join(o))} "
                    f"where the passage says {go.quote(' '.join(p))}"
                )
    return ""


BIND_NO_NUMBER = -1  # the claim states no number
BIND_UNRESOLVED = 0
BIND_OWN = 1  # some unit clause binds a claim number to the claim's word
BIND_OTHER = 2  # unit clauses bind the claim's numbers to the other word only


def bind_value(
    claim: str,
    claim_language: str,
    unit: str,
    unit_language: str,
    own: Sequence[str],
    other: Sequence[str],
) -> int:
    """Which of two words the unit binds each of the claim's numbers to."""
    claim_keys: list[list[str]] = []
    for c in verify_roles.role_clauses(claim):
        claim_keys.extend(verify_qualifier_pairs.number_word_keys(c, claim_language).values())
    if not claim_keys:
        return BIND_NO_NUMBER
    to_other = False
    for c in verify_roles.role_clauses(unit):
        words = [
            w.strip(verify_roles.ROLE_TRIM + ".,;:") for w in verify_qualifier_pairs.lower_words(c)
        ]

        def positions(phrase: Sequence[str], words: list[str] = words) -> list[int]:
            out = []
            for i in range(len(words)):
                k, j = 0, i
                while j < len(words) and k < len(phrase):
                    if words[j] == phrase[k]:
                        k += 1
                        j += 1
                        continue
                    if words[j] in ARTICLES and k > 0:
                        j += 1
                        continue
                    break
                if k == len(phrase):
                    out.append(i)
            return out

        po, pp = positions(own), positions(other)

        def governor(at: int, po: list[int] = po, pp: list[int] = pp) -> int:
            bo = max((x for x in po if x < at), default=-1)
            bp = max((x for x in pp if x < at), default=-1)
            if bo > bp:
                return BIND_OWN
            if bp > bo:
                return BIND_OTHER
            if bo >= 0:
                return BIND_UNRESOLVED
            ao = min((x for x in po if x > at), default=-1)
            ap = min((x for x in pp if x > at), default=-1)
            if ao >= 0 and (ap < 0 or ao < ap):
                return BIND_OWN
            if ap >= 0 and (ao < 0 or ap < ao):
                return BIND_OTHER
            return BIND_UNRESOLVED

        for at, ukeys in verify_qualifier_pairs.number_word_keys(c, unit_language).items():
            for keys in claim_keys:
                if not verify_qualifier_pairs.shares_key(keys, ukeys):
                    continue
                g = governor(at)
                if g == BIND_OWN:
                    return BIND_OWN
                if g == BIND_OTHER:
                    to_other = True
    return BIND_OTHER if to_other else BIND_UNRESOLVED


def counterpart_of(o: Sequence[str], p: Sequence[str], sentences: Sequence[Sequence[str]]) -> bool:
    """Party p is the other word of a pair with o — the same head."""
    if len(o) != 1 or len(p) != 1:
        return False
    a, b = o[0], p[0]
    common = 0
    while common < len(a) and common < len(b) and a[len(a) - 1 - common] == b[len(b) - 1 - common]:
        common += 1
    if common >= 4 and len(a) > common and len(b) > common:
        return True

    def nxt(w: str) -> set[str]:
        out = set()
        for s in sentences:
            for i in range(len(s) - 1):
                if s[i] == w and party_word(s[i + 1]):
                    out.add(s[i + 1])
        return out

    return bool(nxt(a) & nxt(b))


def value_row_guard(claim: str, claim_language: str, eu: EvidenceUnit) -> str:
    """A number stated for one period moved to another."""

    def periods(clause: str, language: str, own: str) -> set[tuple[str, str]]:
        return {q for q in quantities(clause, language) if q[0] != own}

    # Sentences, not clauses: a period is often a fronted adverbial.
    _, unit_text = clock_times(eu.text)
    _, claim_text = clock_times(claim)
    unit_clauses = go.split(SENTENCE_BREAK, soft_join(unit_text))
    for c in go.split(SENTENCE_BREAK, soft_join(claim_text)):
        for m in numbers_in(c, claim_language):
            key = m.reading.key
            mine = periods(c, claim_language, key)
            if not mine:
                continue
            matched = agrees = False
            other: tuple[str, str] | None = None
            for uc in unit_clauses:
                if not any(um.reading.key == key for um in numbers_in(uc, eu.language)):
                    continue
                theirs = periods(uc, eu.language, key)
                if not theirs:
                    agrees = True  # the unit states the value without a period here
                    continue
                matched = True
                if any(same_quantity_in(q, theirs) for q in mine):
                    agrees = True
                if other is None:
                    other = _min_by_value(theirs)
            if matched and not agrees:
                claimed = _min_by_value(mine)
                assert other is not None
                return (
                    f"value guard: {key.removeprefix('?')} for {claimed[0]} {claimed[1]} "
                    f"where the passage says {other[0]} {other[1]}"
                )
    return ""


def _min_by_value(qs: set[tuple[str, str]]) -> tuple[str, str]:
    """The quantity with the smallest value string (Go's first-wins on a tie is
    map order; sorted order here)."""
    return min(sorted(qs), key=lambda q: q[0])


# ─── subject swap, through the glossary ─────────────────────────────────────

MODAL_WORDS = frozenset(
    {"must", "may", "can", "will", "shall", "should", "moet", "mag", "kan", "zal", "dient"}
)

#: Open a Dutch separable verb split around its object ("sluit … af").
SEPARABLE_PARTICLES = frozenset(
    {
        "af",
        "aan",
        "op",
        "in",
        "uit",
        "mee",
        "door",
        "over",
        "terug",
        "vast",
        "toe",
        "voor",
        "bij",
        "na",
    }
)

#: The reader's pronouns in subject form.
READER_SUBJECTS = frozenset({"you", "je", "jij", "u"})


def subject_swap_guard(claim: str, claim_language: str, eu: EvidenceUnit, cfg: GuardConfig) -> str:
    """Bind a claim's "party + verb" pair to the unit sentences with that verb
    (across languages, through the glossary only)."""
    from citenexus.answer.glossary import is_empty

    cross = _va.cross_language(claim_language, eu.language)
    if not cross or cfg.gloss is None or is_empty(cfg.gloss):
        return ""
    gloss = cfg.gloss.index
    sep_of = cfg.gloss.sep_of
    class_of = cfg.gloss.class_of
    sep_keys = cfg.gloss.sep_keys
    sentences = _sentences(eu.text)
    claim_tokens = tokenize_v2(claim)
    nl = _va.primary_language(eu.language) == "nl"

    def subject_of(toks: list[str], verb: int) -> list[str] | None:
        if len(toks) > 1:
            modal = toks[2 % len(toks)] in MODAL_WORDS
            if (
                toks[0] in PARTY_DETERMINERS
                and party_word(toks[1])
                and (verb == 2 or (verb == 3 and modal))
            ):
                return [toks[1]]
        if (
            nl
            and verb + 2 < len(toks)
            and toks[verb + 1] in PARTY_DETERMINERS
            and party_word(toks[verb + 2])
        ):
            return [toks[verb + 2]]
        return None

    subjects: set[str] = set()
    for toks in sentences:
        if len(toks) > 2 and toks[0] in PARTY_DETERMINERS and party_word(toks[1]):
            subjects.add(toks[1])
        for j in range(len(toks)):
            subj = subject_of(toks, j)
            if subj is not None and j > 0 and toks[j] in gloss:
                subjects.add(subj[0])
    parties: list[str] = []
    for p in sorted(subjects):
        c = class_of.get(p)
        if (
            c is not None
            and c not in ("party", "group")
            and not verify_conditions.actor_term(p, cfg.actors)
        ):
            continue
        parties.append(p)

    def verb_matches(toks: list[str], j: int, claim_verb: str) -> bool:
        t = toks[j]
        if is_stopword(t) or not party_word(t):
            return False
        particle = sep_of.get(t, "")
        if particle != "" and particle not in toks[j + 1 :]:
            return False
        for vf in gloss.get(t, ()):
            if len(vf) == 1 and vf[0] == claim_verb:
                return True
        for k in range(j + 1, len(toks)):
            if toks[k] not in SEPARABLE_PARTICLES:
                continue
            stem = t.removesuffix("t").removesuffix("en")
            for sk in sep_keys.get(toks[k], ()):
                if not sk.rest.startswith(stem) or go.blen(stem) < 3:
                    continue
                for vf in sk.trs:
                    if len(vf) == 1 and vf[0] == claim_verb:
                        return True
        return False

    def verb_after(start: int) -> str:
        v = start
        while v < len(claim_tokens) and claim_tokens[v] in MODAL_WORDS:
            v += 1
        return claim_tokens[v] if v < len(claim_tokens) else ""

    def check(party: str, reader: bool, claim_verb: str) -> str:
        agrees, other = False, ""
        for toks in sentences:
            for j in range(len(toks)):
                if not verb_matches(toks, j, claim_verb):
                    continue
                subj = subject_of(toks, j)
                if subj is None:
                    continue
                if (
                    (reader and verify_conditions.actor_term(subj[0], cfg.actors))
                    or (reader and not is_party(subj[0], cfg))
                    or (
                        not reader
                        and (subj[0] == party or same_actor_class(subj[0], party, cfg.actors))
                    )
                ):
                    agrees = True
                elif other == "":
                    other = subj[0]
        if not agrees and other != "":
            return (
                f"role guard: {go.quote(party)} {claim_verb} "
                f"where the passage says {go.quote(other)} does"
            )
        return ""

    for p in parties:
        for f in gloss.get(p, ()):
            for sp in find_spans(claim_tokens, f):
                claim_verb = verb_after(sp.end)
                if claim_verb != "":
                    reason = check(p, False, claim_verb)
                    if reason:
                        return reason
    # The reader as the claim's subject against a THIRD party.
    for i, t in enumerate(claim_tokens):
        if t not in READER_SUBJECTS:
            continue
        claim_verb = verb_after(i + 1)
        if claim_verb != "":
            reason = check(t, True, claim_verb)
            if reason:
                return reason
    return ""


def same_actor_class(a: str, b: str, lexicon: ActorLexicon) -> bool:
    return any(a in terms and b in terms for terms in lexicon.actors.values())


def is_party(noun: str, cfg: GuardConfig) -> bool:
    """The glossary classes the noun as a party or a group."""
    if cfg.gloss is None:
        return False
    return cfg.gloss.class_of.get(noun, "") in ("party", "group")
