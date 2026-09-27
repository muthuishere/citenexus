"""The role guard: WHO pays, receives or must.

Port of ``golang/answer/verify_roles.go`` (ADR-0016). Actors are
language-independent ids ("employee", "employer", "intern") with terms in any
language (:class:`ActorLexicon`). A fact is a number (ADR-0015 key) or a slot
word — what the actor does with it: source (pays), recipient (receives), duty
(must), permission (may). The guard refuses a claim whose fact the unit states
for a different actor, and only then. Like every guard it can only refuse.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer.numbers import VerbatimNumbers, numbers_in, verbatim_in
from citenexus.answer.verify import is_stopword
from citenexus.answer.verify_guards_model import CONTEXT_STOP, soft_join
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit

SLOT_SOURCE = "source"
SLOT_RECIPIENT = "recipient"
SLOT_DUTY = "duty"
SLOT_PERMISSION = "permission"


@dataclass(frozen=True)
class ActorLexicon:
    """What the role guard reads. All terms are lowercase single words.

    ``actors`` maps an actor id to its terms in any language; ``second_person``
    is the actor the reader's own pronouns (``second_person_terms``) stand for
    ("" = pronouns bind nothing); ``slots`` maps a fact word to its slot;
    ``share_tails`` make a Dutch compound an actor's share
    ("werkgeversbijdrage").
    """

    actors: Mapping[str, Sequence[str]] = field(default_factory=dict)
    second_person: str = ""
    second_person_terms: Sequence[str] = ()
    slots: Mapping[str, str] = field(default_factory=dict)
    share_tails: Sequence[str] = ()

    def with_terms(self, actor_id: str, *terms: str) -> ActorLexicon:
        """A copy with extra terms for one actor id (a new id registers a new
        role) — Go's ``ActorLexicon.With``."""
        actors = {k: list(v) for k, v in self.actors.items()}
        for t in terms:
            actors.setdefault(actor_id, []).append(go.lower(go.trim_space(t)))
        return ActorLexicon(
            actors=actors,
            second_person=self.second_person,
            second_person_terms=self.second_person_terms,
            slots=self.slots,
            share_tails=self.share_tails,
        )

    def classify(
        self, clause: str, language: str | None, verbatim: VerbatimNumbers | None = None
    ) -> list[RoleWord]:
        terms: dict[str, str] = {}
        for actor_id, ts in self.actors.items():
            for t in ts:
                terms[t] = actor_id
        second = set(self.second_person_terms)
        words = _va.LIST_LEAD_TOKEN.findall(clause)
        out: list[RoleWord] = []
        for i, w in enumerate(words):
            norm = go.lower(w.strip(ROLE_TRIM))
            norm = norm.removesuffix("'s").removesuffix("’s")  # noqa: RUF001 — "employer's"
            rw = RoleWord(norm=norm, position=i)
            rw.numbers = [m.reading.key for m in numbers_in(w, language, verbatim)]
            if norm in terms:
                rw.actor = terms[norm]
            elif norm in second and self.second_person != "":
                rw.actor, rw.pronoun = self.second_person, True
            else:
                share = self.share(norm, terms)
                if share is not None:
                    rw.actor, rw.slot = share, SLOT_SOURCE
            slot = self.slots.get(norm)
            if slot is not None and rw.slot == "":
                rw.slot = slot
            if (
                rw.actor == ""
                and rw.slot == ""
                and not rw.numbers
                and len(norm) >= 4
                and not is_stopword(norm)
                and norm not in CONTEXT_STOP
            ):
                rw.content = True
            out.append(rw)
        return out

    def share(self, word: str, terms: Mapping[str, str]) -> str | None:
        """ "werkgeversdeel" as the employer's share: term + optional linking
        "s" + an exact share tail."""
        for tail in self.share_tails:
            if not word.endswith(tail):
                continue
            head = word[: len(word) - len(tail)]
            if head == "":
                continue
            if head in terms:
                return terms[head]
            if head.endswith("s") and head[:-1] in terms:
                return terms[head[:-1]]
        return None


#: A small generic nl/en table. It names no organisation: hosts add theirs.
DEFAULT_ACTOR_LEXICON = ActorLexicon(
    actors={
        "employee": [
            "werknemer",
            "werknemers",
            "medewerker",
            "medewerkers",
            "employee",
            "employees",
        ],
        "employer": ["werkgever", "werkgevers", "employer", "employers"],
        "intern": ["stagiair", "stagiairs", "stagiaire", "stagiaires", "intern", "interns"],
        "agency": ["uitzendkracht", "uitzendkrachten", "agency"],
        "contractor": [
            "inhuur",
            "freelancer",
            "freelancers",
            "zzp'er",
            "zzp'ers",
            "contractor",
            "contractors",
        ],
        "manager": ["leidinggevende", "leidinggevenden", "manager", "managers"],
    },
    second_person="employee",
    second_person_terms=("je", "jij", "jou", "jouw", "u", "uw", "you", "your", "yours"),
    share_tails=("bijdrage", "bijdragen", "deel", "aandeel", "premie"),
    slots={
        "betaalt": SLOT_SOURCE,
        "betaal": SLOT_SOURCE,
        "betalen": SLOT_SOURCE,
        "betaald": SLOT_SOURCE,
        "draagt": SLOT_SOURCE,
        "dragen": SLOT_SOURCE,
        "vergoedt": SLOT_SOURCE,
        "vergoed": SLOT_SOURCE,
        "vergoeden": SLOT_SOURCE,
        "bijdrage": SLOT_SOURCE,
        "bijdragen": SLOT_SOURCE,
        "stort": SLOT_SOURCE,
        "verstrekt": SLOT_SOURCE,
        "biedt": SLOT_SOURCE,
        "geeft": SLOT_SOURCE,
        "pays": SLOT_SOURCE,
        "pay": SLOT_SOURCE,
        "paid": SLOT_SOURCE,
        "contributes": SLOT_SOURCE,
        "contribute": SLOT_SOURCE,
        "contribution": SLOT_SOURCE,
        "reimburses": SLOT_SOURCE,
        "reimburse": SLOT_SOURCE,
        "provides": SLOT_SOURCE,
        "share": SLOT_SOURCE,
        "offers": SLOT_SOURCE,
        "bears": SLOT_SOURCE,
        "ontvangt": SLOT_RECIPIENT,
        "ontvang": SLOT_RECIPIENT,
        "ontvangen": SLOT_RECIPIENT,
        "krijgt": SLOT_RECIPIENT,
        "krijg": SLOT_RECIPIENT,
        "krijgen": SLOT_RECIPIENT,
        "recht": SLOT_RECIPIENT,
        "receives": SLOT_RECIPIENT,
        "receive": SLOT_RECIPIENT,
        "gets": SLOT_RECIPIENT,
        "get": SLOT_RECIPIENT,
        "entitled": SLOT_RECIPIENT,
        "earns": SLOT_RECIPIENT,
        "moet": SLOT_DUTY,
        "moeten": SLOT_DUTY,
        "verplicht": SLOT_DUTY,
        "must": SLOT_DUTY,
        "mag": SLOT_PERMISSION,
        "mogen": SLOT_PERMISSION,
        "may": SLOT_PERMISSION,
    },
)


@dataclass
class RoleWord:
    """One word of a clause, classified."""

    norm: str
    position: int
    actor: str = ""  # actor id, or ""
    pronoun: bool = False  # the actor is the reader's pronoun, not a named role
    slot: str = ""
    numbers: list[str] = field(default_factory=list)
    content: bool = False  # a content word for fact matching


ROLE_TRIM = "\"'“”‘’()[]{}.,;:!?*_|€$£"  # noqa: RUF001 — typographic quotes are the point

ROLE_NUMBER_WINDOW = 5  # a number to its slot word, or to its actor without one
ROLE_ACTOR_WINDOW = 4  # a slot word to its actor

#: Precede a named actor that is not the one doing the slot.
NON_SUBJECT = frozenset(
    {
        "van",
        "voor",
        "aan",
        "bij",
        "met",
        "namens",
        "binnen",
        "in",
        "onder",
        "from",
        "for",
        "to",
        "with",
        "of",
        "on",
        "within",
        "at",
        "among",
    }
)


def nearest(ws: Sequence[RoleWord], i: int, limit: int, ok: Callable[[int], bool]) -> int:
    """The nearest index within ``limit`` words of i satisfying ok; the earlier
    on a tie; -1 when none."""
    d = 0
    while d <= limit and d < len(ws):
        j = i - d
        if j >= 0 and ok(j):
            return j
        j = i + d
        if j < len(ws) and ok(j):
            return j
        d += 1
    return -1


def binding(ws: Sequence[RoleWord], i: int) -> tuple[str, str, bool] | None:
    """The (slot, actor, pronoun) the fact at index i binds to; None when
    either is unresolved."""
    s = i
    if ws[i].slot == "":
        s = nearest(ws, i, ROLE_NUMBER_WINDOW, lambda j: ws[j].slot != "")
    if s < 0:
        # No slot word in the whole clause: a number binds to its nearest actor.
        if not ws[i].numbers or nearest(ws, i, len(ws), lambda j: ws[j].slot != "") >= 0:
            return None
        a = nearest(ws, i, ROLE_NUMBER_WINDOW, lambda j: ws[j].actor != "")
        if a < 0:
            return None
        return "", ws[a].actor, ws[a].pronoun
    if ws[s].actor != "":  # a share compound: "werkgeversdeel"
        return ws[s].slot, ws[s].actor, ws[s].pronoun

    def actor_ok(j: int) -> bool:
        if ws[j].actor == "":
            return False
        if j > 0 and not ws[j].pronoun:
            if ws[j - 1].norm in NON_SUBJECT:
                return False
            if j > 1 and is_article(ws[j - 1].norm) and ws[j - 2].norm in NON_SUBJECT:
                return False
        return True

    a = nearest(ws, s, ROLE_ACTOR_WINDOW, actor_ok)
    if a < 0:
        return None
    return ws[s].slot, ws[a].actor, ws[a].pronoun


_ARTICLES = frozenset({"de", "het", "een", "the", "a", "an", "je", "jouw", "your", "uw"})


def is_article(w: str) -> bool:
    return w in _ARTICLES


#: clauseBreak without the colon: a label binds to its value.
ROLE_BREAK = re.compile(
    r"[.!?;]+(?:[\t\n\f\r ]|\Z)|,[\t\n\f\r ]|[\t\n\f\r ]*[\u2014\u2013][\t\n\f\r ]*"
    r"|[\t\n\f\r ]-[\t\n\f\r ]|\n"
)


def role_clauses(text: str) -> list[str]:
    return go.split(ROLE_BREAK, soft_join(text))


def role_guard(
    claim: str, claim_language: str | None, eu: EvidenceUnit, lexicon: ActorLexicon
) -> str:
    """Refuse a claim whose fact the unit states for a different actor."""
    if not lexicon.actors and lexicon.second_person == "":
        return ""
    unit = [lexicon.classify(c, eu.language) for c in role_clauses(eu.text)]
    for c in role_clauses(claim):
        ws = lexicon.classify(c, claim_language, verbatim_in(eu.text, eu.language))
        content: set[str] = set()
        for w in ws:
            if w.content:
                content.update(tokenize_v2(w.norm))
        for i, w in enumerate(ws):
            match: Callable[[RoleWord], bool]
            if w.numbers:
                keys = w.numbers

                def match(u: RoleWord, keys: list[str] = keys) -> bool:
                    return any(n in keys for n in u.numbers)

            elif w.slot != "" and not has_number(ws):
                slot_ = w.slot

                def match(u: RoleWord, slot_: str = slot_) -> bool:
                    return u.slot == slot_

            else:
                continue
            bound = binding(ws, i)
            if bound is None:
                continue
            slot, actor, pronoun = bound
            if not w.numbers and pronoun:
                continue
            agrees, other = False, ""
            for uc in unit:
                if not w.numbers and not shares_content(uc, content):
                    continue
                for j, u in enumerate(uc):
                    if not match(u):
                        continue
                    ub = binding(uc, j)
                    if ub is None or ub[0] != slot:
                        continue
                    if ub[1] == actor:
                        agrees = True
                    elif other == "":
                        other = ub[1]
            if not agrees and other != "":
                return f"role guard: {actor} where the passage says {other}"
    return ""


def has_number(ws: Sequence[RoleWord]) -> bool:
    return any(w.numbers for w in ws)


def shares_content(ws: Sequence[RoleWord], content: set[str]) -> bool:
    """The unit clause holds at least half of the claim clause's content words,
    and at least two."""
    have: set[str] = set()
    for w in ws:
        if w.content:
            have.update(tokenize_v2(w.norm))
    shared = sum(1 for tok in content if tok in have)
    return shared >= 2 and 2 * shared >= len(content)
