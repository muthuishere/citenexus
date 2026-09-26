"""VerifyOptions.conjunct_presence: the cross-language condition reading.

Port of ``golang/answer/verify_conjunct_presence.go`` (ADR-0016). Off by
default. With it on, for a cross-language claim that states a condition of its
own, a glossary can SATISFY a condition word but never show it missing, and
that no-verdict branch must not pass a PARTIAL condition: when the claim's own
condition has fewer parts than the unit's, every conjunct must be positively
present.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_conditions
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_conditions import Carrier

CROSS_CONDITION_MARKERS: tuple[tuple[str, ...], ...] = (
    ("if",),
    ("when",),
    ("whenever",),
    ("once",),
    ("provided",),
    ("unless",),
    ("as", "long", "as"),
    ("who",),
    ("whose",),
    ("which",),
    ("that",),
    ("with",),
    ("without",),
    ("after",),
    ("before",),
    ("on",),
    ("only",),
    ("except",),
    ("subject", "to"),
    ("where",),
    ("in", "case"),
    ("als",),
    ("wanneer",),
    ("indien",),
    ("mits",),
    ("zodra",),
    ("zolang",),
    ("tenzij",),
    ("die",),
    ("dat",),
    ("met",),
    ("zonder",),
    ("na",),
    ("op",),
    ("alleen",),
    ("behalve",),
    ("bij",),
)

PRESENCE_OPENER = go.compile_go(
    r"\b(mits|indien|tenzij|zolang|wanneer|als|die|op voorwaarde dat|provided that|provided"
    r"|unless|if|when|once|who)\b",
    ignore_case=True,
)
PRESENCE_SPLIT = go.compile_go(r",|\b(?:zowel|both|as well as)\b|\b(?:en|and)\b", ignore_case=True)
PRESENCE_COORDINATOR = go.compile_go(r"\b(?:en|and|zowel|both|as well as)\b", ignore_case=True)
PRESENCE_TOT_EN_MET = go.compile_go(r"\btot en met\b", ignore_case=True)

#: Pronouns and have-auxiliaries of four letters or more are no part of a
#: conjunct.
PRESENCE_FUNCTION_WORDS = frozenset(
    {
        "they",
        "them",
        "their",
        "have",
        "been",
        "would",
        "could",
        "should",
        "hebben",
        "heeft",
        "zich",
        "deze",
        "werd",
        "werden",
        "zullen",
        "zouden",
    }
)


def dropped_conjunct(
    claim: str, sentence: str, sentence_language: str, c: Carrier
) -> tuple[str, int]:
    """A word of a conjunct the claim does not positively carry, and the
    conjunct count — when the claim's own condition has fewer conjuncts than
    the unit's. ("", 0) otherwise."""
    loc = PRESENCE_OPENER.search(sentence)
    if loc is None:
        return "", 0
    # "zowel … als" is a coordination, not a condition.
    if go.lower(loc.group(0)) == "als" and "zowel" in go.lower(sentence[: loc.start()]):
        return "", 0
    before = set(tokenize_v2(sentence[: loc.start()]))
    span = PRESENCE_TOT_EN_MET.sub("tot_en_met", sentence[loc.end() :])
    segs = span.split(",")
    while len(segs) > 1 and not PRESENCE_COORDINATOR.search(segs[-1]):
        segs = segs[:-1]
    conjuncts: list[list[str]] = []
    for p in go.split(PRESENCE_SPLIT, ",".join(segs)):
        ws = [
            t
            for t in tokenize_v2(p)
            if verify_conditions.condition_content(t)
            and t not in PRESENCE_FUNCTION_WORDS
            and t not in before
        ]
        if ws:
            conjuncts.append(ws)
    n = len(conjuncts)
    if n < 2:
        return "", 0
    # A Dutch subordinate clause ends in its verb, shared by the conjuncts.
    if _va.primary_language(sentence_language) == "nl":
        last = conjuncts[n - 1]
        if len(last) >= 2 and _is_word(last[-1]):
            conjuncts[n - 1] = last[:-1]
    absent = ""
    for ws in conjuncts:
        present = any(c.carried(w)[0] for w in ws)
        if not present and absent == "":
            absent = ws[0]
    if absent == "":
        return "", 0
    # The claim's own condition: from its first condition marker on.
    lc = go.lower(claim)
    cl = PRESENCE_OPENER.search(lc)
    cut = -1
    if cl is not None:
        cut = cl.end()
    else:
        for marker in (" with ", " met ", " after ", " na ", " on ", " op "):
            i = lc.find(marker)
            if i >= 0:
                cut = i + len(marker)
                break
    if cut < 0:
        return "", 0
    m = len(go.split(PRESENCE_SPLIT, PRESENCE_TOT_EN_MET.sub("tot_en_met", lc[cut:])))
    if m >= n:
        return "", 0  # as many conditions as the unit: may be all of them
    return absent, n


def _is_word(t: str) -> bool:
    return t != "" and all(ch.isalpha() for ch in t)
