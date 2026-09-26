"""The condition guard: a model-admitted claim that drops the unit's condition.

Port of ``golang/answer/verify_conditions.go`` (ADR-0016). It finds the unit
sentence the claim follows (the most shared content words, at least two) and
reads its restrictors — an opener and what follows it, a conditional sentence
opened by its verb, a scope qualifier before a shared word, a coordinated
requirement dropped from inside the claim's span. A restrictor whose content
words the claim lacks refuses the claim. Same language, or through the caller's
glossary; a glossary miss never turns into a refusal. Can only refuse.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import (
    verify_conjunct_presence,
    verify_exclusions,
    verify_guards,
    verify_hedges,
    verify_parties,
    verify_roles,
)
from citenexus.answer.numbers import date_spans, dates_in
from citenexus.answer.verify import is_stopword
from citenexus.answer.verify_guards_model import CONTEXT_STOP, soft_join
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.glossary import PreparedGlossary
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig
    from citenexus.answer.verify_roles import ActorLexicon

CONDITION_OPENERS = frozenset(
    {
        "mits",
        "indien",
        "tenzij",
        "voorwaarde",
        "alleen",
        "uitsluitend",
        "enkel",
        "slechts",
        "eerst",
        "pas",
        "zolang",
        "behalve",
        "uitgezonderd",
        "provided",
        "unless",
        "only",
        "solely",
        "first",
        "except",
        "once",
    }
)

#: Two-word openers.
CONDITION_PHRASES: tuple[tuple[str, str], ...] = (
    ("ten", "minste"),
    ("met", "toestemming"),
    ("at", "least"),
    ("with", "permission"),
)

#: Open a whole conditional clause.
SUBORDINATING_OPENERS = frozenset(
    {"mits", "indien", "tenzij", "zolang", "voorwaarde", "provided", "unless", "once"}
)

#: Hold a rule "even if": the opposite of a condition.
CONCESSIVES: tuple[tuple[str, ...], ...] = (
    ("even", "if"),
    ("even", "when"),
    ("even", "though"),
    ("regardless", "of", "whether"),
    ("zelfs", "als"),
    ("zelfs", "wanneer"),
    ("zelfs", "indien"),
    ("ook", "als"),
    ("ook", "wanneer"),
    ("ongeacht", "of"),
)

#: Make a rule conditional or excepted.
EXCEPTION_OPENERS: tuple[tuple[str, ...], ...] = (
    ("tenzij",),
    ("mits",),
    ("indien",),
    ("behalve",),
    ("uitgezonderd",),
    ("alleen", "als"),
    ("alleen", "wanneer"),
    ("unless",),
    ("provided",),
    ("except",),
    ("only", "if"),
    ("only", "when"),
)

#: Words by which a claim states a condition of its own.
CLAIM_CONDITION_MARKERS = frozenset(
    {"als", "wanneer", "zodra", "indien", "die", "wie", "if", "when", "who", "whoever"}
)

#: Open a restriction only right after a party.
PARTY_RESTRICTORS = frozenset({"met", "die", "with", "who"})

SCOPE_QUALIFIERS = frozenset(
    {
        "onbetaald",
        "onbetaalde",
        "betaald",
        "betaalde",
        "aanvullend",
        "aanvullende",
        "bijzonder",
        "bijzondere",
        "vast",
        "vaste",
        "tijdelijk",
        "tijdelijke",
        "variabel",
        "variabele",
        "gewoon",
        "gewone",
        "unpaid",
        "paid",
        "additional",
        "special",
        "fixed",
        "variable",
        "regular",
        "temporary",
        "permanent",
    }
)

CONDITIONAL_VERB_SUBJECTS = frozenset({"je", "jij", "u", "de", "het"})

EXCLUSION_OPENERS = frozenset({"behalve", "uitgezonderd", "except"})


def condition_content(t: str) -> bool:
    if is_stopword(t) or t in CONTEXT_STOP:
        return False
    # Short words are verbs and particles more than conditions; digits count.
    return len(t) >= 4 or go.contains_any(t, "0123456789")


def gloss_idx(gloss: PreparedGlossary | None) -> Mapping[str, list[list[str]]]:
    return gloss.index if gloss is not None else {}


@dataclass(frozen=True)
class Carrier:
    """Whether the claim carries unit word w: directly, or (other language)
    through a glossary translation."""

    claim: set[str]
    cross_lang: bool
    translations: Mapping[str, list[list[str]]]
    #: VerifyOptions.conjunct_presence only: the glossary may show a word
    #: carried, never missing (verify_conjunct_presence).
    satisfy_only: bool = False

    def carried(self, w: str) -> tuple[bool, bool]:
        """(has, known). known is False when w has no glossary entry and the
        claim is in another language."""
        if w in self.claim:
            return True, True
        # An inflection or a plural: one word is the other plus a short ending.
        if len(w) >= 6:
            for t in self.claim:
                if (
                    len(t) >= 6
                    and (t.startswith(w) or w.startswith(t))
                    and abs(len(t) - len(w)) <= 3
                ):
                    return True, True
        if not self.cross_lang:
            return False, True
        trs = self.translations.get(w)
        if trs is None:
            if go.contains_any(w, "0123456789"):
                return False, True  # a number reads the same in both languages
            return False, False
        for tr in trs:
            if all(t in self.claim for t in tr):
                return True, True
        if self.satisfy_only:
            return False, False
        return False, True


def glossary_index(glossary: Sequence[tuple[str, str]]) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for pair in glossary:
        for k in range(2):
            frm, to = tokenize_v2(pair[k]), tokenize_v2(pair[1 - k])
            if len(frm) == 1 and to:
                out.setdefault(frm[0], []).append(to)
    return out


def condition_guard(claim: str, claim_language: str, eu: EvidenceUnit, cfg: GuardConfig) -> str:
    """See the module docstring."""
    from citenexus.answer.glossary import is_empty

    cross = _va.cross_language(claim_language, eu.language)
    if cross and is_empty(cfg.gloss):
        return ""
    # Dates are compared as one token each.
    claim = canonical_dates(claim, claim_language)
    unit_text = canonical_dates(eu.text, eu.language)
    claim_tokens = tokenize_v2(claim)
    c = Carrier(set(claim_tokens), cross, gloss_idx(cfg.gloss))
    # ConjunctPresence: the no-verdict branch (verify_conjunct_presence).
    c = replace(
        c,
        satisfy_only=cfg.conjunct_presence
        and cross
        and verify_hedges.has_any(claim_tokens, verify_conjunct_presence.CROSS_CONDITION_MARKERS)
        != "",
    )
    claim_bounds = verify_guards.bound_directions(claim_tokens)

    def shared(t: str) -> bool:
        has, _ = c.carried(t)
        return condition_content(t) and has

    ties: list[str] = []
    previous: dict[str, str] = {}
    best_n = 0
    claim_hedges = verify_hedges.hedges_in(claim_tokens, claim)
    prev = ""
    for s in go.split(verify_parties.SENTENCE_BREAK, soft_join(unit_text)):
        previous[s] = prev
        prev = s
        n = 0
        seen: set[str] = set()
        for t in tokenize_v2(s):
            has, _ = c.carried(t)
            if not has and cross:
                if actor_term(t, cfg.actors) and claim_names_role(c.claim, t, cfg.actors):
                    has = True
                for cls in verify_hedges.hedges_in([t], t):
                    if cls in claim_hedges:
                        has = True
            if t not in seen and has and not is_stopword(t) and t not in CONTEXT_STOP:
                seen.add(t)
                n += 1
        if n > best_n:
            ties, best_n = [s], n
        elif n == best_n and n > 0:
            ties.append(s)
    if best_n < 2:
        return ""

    def lacks(words: Sequence[str], half: bool) -> tuple[bool, str]:
        content = known = missing = 0
        first = ""
        for w in words:
            if not condition_content(w):
                continue
            content += 1
            has, ok = c.carried(w)
            if not ok:
                continue
            known += 1
            if not has:
                missing += 1
                if first == "":
                    first = w
        if content == 0 or known == 0:
            return False, ""
        if c.cross_lang:
            return missing == known and 2 * known >= content, first
        if half:
            return 2 * missing >= content and missing > 0, first
        return missing == content, first

    claim_conditioned = False
    for i, t in enumerate(claim_tokens):
        if t in CLAIM_CONDITION_MARKERS:
            claim_conditioned = True
        if (
            t == "as"
            and i + 2 < len(claim_tokens)
            and claim_tokens[i + 1] == "long"
            and claim_tokens[i + 2] == "as"
        ):
            claim_conditioned = True
        if t in CONDITION_OPENERS and not (i > 0 and claim_tokens[i - 1] in ("niet", "not")):
            claim_conditioned = True

    def lacks_segment(words: Sequence[str]) -> tuple[bool, str]:
        ok, w = lacks(words, True)
        if not ok or c.cross_lang or not claim_conditioned:
            return ok, w
        content = missing = 0
        for x in words:
            if not condition_content(x):
                continue
            content += 1
            has, _ = c.carried(x)
            if not has:
                missing += 1
        return 2 * missing > content, w

    def refuse(kind: str, word: str) -> str:
        return (
            f"condition guard: the passage restricts it ({kind} {go.quote(word)}) "
            "and the claim drops it"
        )

    def clause_restrictors(toks: list[str], best: list[str]) -> tuple[str, str] | None:
        """The first restrictor of one clause the claim drops: (kind, word)."""
        # A restriction of a group the claim does not speak about, in SUBJECT
        # position, is out of the claim's scope, and so is every opener inside it.
        out_of_scope = [False] * len(toks)
        for i in range(1, len(toks)):
            subject = i - 1 == 0 or (i - 1 == 1 and verify_roles.is_article(toks[0]))
            if (
                toks[i] in PARTY_RESTRICTORS
                and subject
                and actor_term(toks[i - 1], cfg.actors)
                and not claim_names_actor(c.claim, toks[i - 1], cfg.actors)
            ):
                for k in range(i, len(toks)):
                    out_of_scope[k] = True
                break
        for i in range(len(toks)):
            if out_of_scope[i]:
                continue
            start = -1
            negated = i > 0 and toks[i - 1] in ("niet", "not")  # "niet alleen … maar ook"
            if toks[i] in CONDITION_OPENERS and not negated:
                start = i + 1
                # An exclusion the claim restates itself is the exclusion guard's.
                if toks[i] in EXCLUSION_OPENERS and verify_exclusions.bound_or_negation(
                    claim_tokens
                ):
                    start = -1
            for ph in CONDITION_PHRASES:
                if i + 1 < len(toks) and toks[i] == ph[0] and toks[i + 1] == ph[1]:
                    start = i + 1  # "toestemming", "minste" belong to the condition
                    if verify_guards.BOUND_LOWER in claim_bounds and ph[1] in ("minste", "least"):
                        start = -1
            # "Werknemers met …" / "… die …": a restricted group.
            if (
                toks[i] in PARTY_RESTRICTORS
                and i > 0
                and (actor_term(toks[i - 1], cfg.actors) or in_subject_of_role(toks, i, cfg.actors))
            ):
                start = i + 1
            if start < 0 or start >= len(toks):
                continue
            end = start
            while end < len(toks) and not shared(toks[end]):
                end += 1
            # A subordinating opener opens a whole clause: the condition runs to the
            # clause end — unless the claim states the condition itself.
            if toks[i] in SUBORDINATING_OPENERS:
                in_clause = sum(1 for t in toks[start:] if shared(t))
                in_sentence = sum(1 for t in best if shared(t))
                if in_sentence > in_clause:
                    end = len(toks)
            if toks[i] not in CONDITION_OPENERS and end == start:
                continue
            ok, w = lacks_segment(toks[start:end])
            if ok:
                return "condition", toks[i] + " … " + w
        # Scope qualifiers right before a shared word; "vaste en variabele
        # toeslagen" qualifies through the coordination.
        for i in range(len(toks) - 1):
            if toks[i] not in SCOPE_QUALIFIERS:
                continue
            j = i + 1
            while j + 1 < len(toks) and toks[j] in ("en", "and"):
                j += 2
            if j < len(toks) and shared(toks[j]):
                ok, w = lacks([toks[i]], False)
                if ok:
                    return "qualifier", w
        # A coordinated requirement dropped from inside the claim's span.
        for i in range(len(toks) - 3):
            if (
                shared(toks[i])
                and toks[i + 1] in ("en", "and")
                and condition_content(toks[i + 2])
                and shared(toks[i + 3])
            ):
                ok, w = lacks([toks[i + 2]], False)
                if ok:
                    return "requirement", w
        return None

    # ConjunctPresence: every conjunct positively present, or refused.
    if c.satisfy_only:
        strict = replace(c, satisfy_only=False)
        for best_text in ties:
            w, n = verify_conjunct_presence.dropped_conjunct(claim, best_text, eu.language, strict)
            if w != "":
                return (
                    f"condition guard: the passage attaches {n} conditions and the claim "
                    f"carries only part of them ({go.quote(w)} missing)"
                )
    claim_concedes = verify_hedges.has_any(claim_tokens, CONCESSIVES) != ""
    for best_text in ties:
        best = tokenize_v2(best_text)
        if claim_concedes and verify_hedges.has_any(best, CONCESSIVES) == "":
            w = verify_hedges.has_any(best, EXCEPTION_OPENERS)
            if w != "":
                return (
                    f"condition guard: the passage makes it conditional ({go.quote(w)}) and "
                    "the claim holds it regardless "
                    f"({go.quote(verify_hedges.has_any(claim_tokens, CONCESSIVES))})"
                )
        # A consequent sentence holds only under the sentence before it.
        if len(best) > 1 and (
            best[0] in ("dan", "then")
            or (len(best) > 2 and best[0] == "in" and best[1] == "dat" and best[2] == "geval")
            or (len(best) > 2 and best[0] == "in" and best[1] == "that" and best[2] == "case")
        ):
            cond = previous.get(best_text, "")
            if cond != "":
                ok, w = lacks(tokenize_v2(cond), True)
                if ok:
                    return refuse("condition", w)
        # A conditional sentence opened by its verb: "Kom je … niet uit, dan …".
        if (
            len(best) > 2
            and best[1] in CONDITIONAL_VERB_SUBJECTS
            and not is_stopword(best[0])
            and best[0] not in CONTEXT_STOP
        ):
            for i, t in enumerate(best):
                if t == "dan" and i > 2 and ", dan" in best_text:
                    ok, w = lacks(best[:i], False)
                    if ok:
                        return refuse("condition", w)
                    break
        for clause in go.split(verify_guards.CLAUSE_BREAK, soft_join(best_text)):
            toks = tokenize_v2(clause)
            reason = clause_restrictors(toks, best)
            if reason:
                return refuse(*reason)
    return ""


def actor_term(t: str, lexicon: ActorLexicon) -> bool:
    return any(t in terms for terms in lexicon.actors.values())


def claim_names_actor(claim: set[str], t: str, lexicon: ActorLexicon) -> bool:
    """The claim names the same actor as unit term t (any term of its class)."""
    for actor_id, terms in lexicon.actors.items():
        # The reader's pronoun names the second-person actor.
        if actor_id == lexicon.second_person:
            for x in lexicon.second_person_terms:
                if x in claim and t in terms:
                    return True
        if t not in terms:
            continue
        if any(x in claim for x in terms):
            return True
    return False


def claim_names_role(claim: set[str], t: str, lexicon: ActorLexicon) -> bool:
    """The claim names t's actor class by an explicit role term."""
    for terms in lexicon.actors.values():
        if t not in terms:
            continue
        if any(x in claim for x in terms):
            return True
    return False


def canonical_dates(text: str, language: str) -> str:
    """Each date replaced with one token, "d0106" (+ " y2026")."""
    dates, _ = dates_in(text, language)
    if not dates:
        return text
    lowered = go.lower(text)
    parts: list[str] = []
    last = 0
    for sp in date_spans(lowered, language):
        parts.append(lowered[last : sp.start])
        d = sp.key
        if d.ambiguous:
            parts.append(" " + d.ambiguous + " ")
        else:
            parts.append(f" d{d.day:02d}{d.month:02d} ")
            if d.year != 0:
                parts.append(f"y{d.year} ")
        last = sp.end
    parts.append(lowered[last:])
    return "".join(parts)


def in_subject_of_role(toks: Sequence[str], i: int, lexicon: ActorLexicon) -> bool:
    """Position i lies inside the subject of a clause that opens with a role."""
    start = 1 if len(toks) > 1 and verify_roles.is_article(toks[0]) else 0
    if start >= len(toks) or not actor_term(toks[start], lexicon):
        return False
    return all(toks[k] not in verify_exclusions.GROUP_VERBS for k in range(start + 1, i))
