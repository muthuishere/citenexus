"""Direction of a transfer: WHO informs, pays or gives WHOM.

Port of ``golang/answer/verify_relations.go`` (ADR-0016). A swap of sender and
recipient keeps every word and every number ("the employee must inform the
employer" over "… deelt de werkgever … mee aan de werknemer"). The guard binds
a communication/transfer verb to BOTH its parties and compares the direction
across languages through the actor lexicon's ids. Refused when a unit clause of
the same class has the parties the other way round and none has them the
claim's way. Unresolved means no verdict. Can only refuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_roles

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_roles import ActorLexicon

RELATION_VERBS: dict[str, str] = {
    "deelt": "inform",
    "delen": "inform",
    "meedelen": "inform",
    "mededelen": "inform",
    "informeert": "inform",
    "informeren": "inform",
    "informeer": "inform",
    "meldt": "inform",
    "melden": "inform",
    "inform": "inform",
    "informs": "inform",
    "informed": "inform",
    "notify": "inform",
    "notifies": "inform",
    "notified": "inform",
    "tell": "inform",
    "tells": "inform",
    "told": "inform",
    "betaalt": "pay",
    "betalen": "pay",
    "uitkeren": "pay",
    "keert": "pay",
    "pay": "pay",
    "pays": "pay",
    "paid": "pay",
    "verstrekt": "give",
    "verstrekken": "give",
    "overhandigt": "give",
    "overhandigen": "give",
    "provide": "give",
    "provides": "give",
    "provided": "give",
    "give": "give",
    "gives": "give",
    "gave": "give",
}

RECIPIENT_MARKERS = frozenset({"aan", "bij", "to"})


@dataclass(frozen=True)
class Direction:
    cls: str
    sender: str
    recipient: str


@dataclass(frozen=True)
class _Mention:
    at: int
    actor: str
    marked_recipient: bool


def directions_in(text: str, language: str | None, lexicon: ActorLexicon) -> list[Direction]:
    """The resolved transfers of a text, one per clause at most."""
    english = _va.primary_language(language) == "en"
    out: list[Direction] = []
    for clause in verify_roles.role_clauses(text):
        ws = lexicon.classify(clause, language)
        verb, cls = -1, ""
        for i, w in enumerate(ws):
            c = RELATION_VERBS.get(w.norm)
            if c is not None:
                if verb >= 0 and c != cls:
                    verb = -2  # two different transfers: unresolved
                    break
                verb, cls = i, c
        if verb < 0:
            continue
        ms: list[_Mention] = []
        ids: list[str] = []  # insertion-ordered set
        for i, w in enumerate(ws):
            if w.actor == "" or w.pronoun:
                continue
            marked = False
            k = i - 1
            while k >= 0 and k >= i - 2:
                if ws[k].norm in RECIPIENT_MARKERS:
                    marked = True
                    break
                if not verify_roles.is_article(ws[k].norm):
                    break
                k -= 1
            ms.append(_Mention(i, w.actor, marked))
            if w.actor not in ids:
                ids.append(w.actor)
        if len(ids) != 2:
            continue
        recipient, sender = "", ""
        for m in ms:
            if m.marked_recipient:
                recipient = m.actor
        if recipient == "" and english:
            for m in ms:
                if m.at > verb:
                    recipient = m.actor
                    break
        if recipient == "":
            # Dutch without "aan": the sender is the actor before the verb, or
            # the first after a verb-first clause; the recipient the other one.
            for m in ms:
                if m.at < verb:
                    sender = m.actor
            if sender == "":
                sender = ms[0].actor
            for actor in ids:
                if actor != sender:
                    recipient = actor
        else:
            for actor in ids:
                if actor != recipient:
                    sender = actor
        if sender == "" or recipient == "" or sender == recipient:
            continue
        out.append(Direction(cls, sender, recipient))
    return out


def relation_guard(
    claim: str, claim_language: str | None, eu: EvidenceUnit, lexicon: ActorLexicon
) -> str:
    """Refuse a swapped sender and recipient (see the module docstring)."""
    unit = directions_in(eu.text, eu.language, lexicon)
    if not unit:
        return ""
    for c in directions_in(claim, claim_language, lexicon):
        agrees = swapped = False
        for u in unit:
            if u.cls != c.cls:
                continue
            if u.sender == c.sender and u.recipient == c.recipient:
                agrees = True
            if u.sender == c.recipient and u.recipient == c.sender:
                swapped = True
        if swapped and not agrees:
            return (
                f"role guard: {c.sender} {c.cls}s {c.recipient} "
                f"where the passage says {c.recipient} {c.cls}s {c.sender}"
            )
    return ""
