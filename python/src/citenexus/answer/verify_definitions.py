"""The definition guard: a claim that uses the generic noun for a subtype the
unit DEFINES explicitly.

Port of ``golang/answer/verify_definitions.go`` (ADR-0016). Only EXPLICIT
definitions are read — "<qualifier> <noun> (hierna: het <Term>)",
"(hereinafter …)", "…, hierna 'Term'", "Onder <qualifier> <noun> wordt
verstaan …". A claim using the noun without the qualifier, and not writing the
defined Term itself mid-sentence, is refused. A definition governs every unit
of its document that uses the Term. Can only refuse.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_conditions, verify_parties
from citenexus.answer.verify_guards_model import soft_join
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig

_W = go.WS
DEFINED_AFTER = go.LazyPattern(
    r"(\p{L}+)"
    + _W
    + r"+(\p{L}+)"
    + _W
    + r"*\("
    + _W
    + r"*(?:hierna(?:"
    + _W
    + r"+te"
    + _W
    + r"+noemen)?|hereinafter(?:"
    + _W
    + r"+referred"
    + _W
    + r"+to"
    + _W
    + r"+as)?)"
    + _W
    + r"*[:,]?"
    + _W
    + r"*(?:het|de|the)?"
    + _W
    + r"*['\u2018\"\u201c]?(\p{L}+)['\u2019\"\u201d]?"
    + _W
    + r"*\)"
)
DEFINED_QUOTE = go.LazyPattern(
    r"(\p{L}+)"
    + _W
    + r"+(\p{L}+)"
    + _W
    + r"*,?"
    + _W
    + r"*hierna"
    + _W
    + r"+['\u2018\"\u201c](\p{L}+)['\u2019\"\u201d]"
)
DEFINED_UNDER = go.LazyPattern(
    r"\bonder" + _W + r"+(\p{L}+)" + _W + r"+(\p{L}+)" + _W + r"+wordt" + _W + r"+verstaan",
    ignore_case=True,
)


@dataclass(frozen=True)
class Definition:
    qualifier: str
    noun: str
    term: str


def definitions_in(text: str) -> list[Definition]:
    out: list[Definition] = []
    for pattern in (DEFINED_AFTER, DEFINED_QUOTE):
        for m in pattern.re.finditer(text):
            q, n, term = go.lower(m.group(1)), go.lower(m.group(2)), m.group(3)
            if go.lower(term) != n or not verify_parties.party_word(q):
                continue  # the Term names the noun it qualifies, or it is not read
            out.append(Definition(q, n, term))
    for m in DEFINED_UNDER.re.finditer(text):
        if verify_parties.party_word(go.lower(m.group(1))):
            out.append(Definition(go.lower(m.group(1)), go.lower(m.group(2)), ""))
    return out


_TERM_TRIM = ".,;:!?\"'()"


def definition_guard(claim: str, claim_language: str, eu: EvidenceUnit, cfg: GuardConfig) -> str:
    """See the module docstring."""
    from citenexus.answer.glossary import is_empty

    if cfg.no_definitions:
        return ""
    defs = definitions_in(eu.text)
    # A definition in another unit of the SAME document governs this one when
    # this unit uses the defined Term as written, or, for an "Onder … wordt
    # verstaan" definition, the defined noun.
    if eu.document_id != "":
        for d in cfg.doc_defs.get(eu.document_id, ()):
            if d in defs:
                continue
            if (d.term != "" and written_term(eu.text, d.term)) or (
                d.term == "" and (d.qualifier + " " + d.noun) in go.lower(eu.text)
            ):
                defs.append(d)
    if not defs:
        return ""
    cross = _va.cross_language(claim_language, eu.language)
    if cross and is_empty(cfg.gloss):
        return ""
    c = verify_conditions.Carrier(
        set(tokenize_v2(claim)), cross, verify_conditions.gloss_idx(cfg.gloss)
    )
    words = _va.LIST_LEAD_TOKEN.findall(claim)
    for d in defs:
        has_noun, noun_known = c.carried(d.noun)
        if not noun_known or not has_noun:
            continue
        has_qual, qual_known = c.carried(d.qualifier)
        if not qual_known or has_qual:
            continue
        # The defined Term written as such, not at the start of a sentence.
        if d.term != "" and any(
            i > 0 and w.strip(_TERM_TRIM) == d.term for i, w in enumerate(words)
        ):
            continue
        return (
            f"definition guard: the passage defines {go.quote(d.noun)} "
            f"as {go.quote(d.qualifier + ' ' + d.noun)}"
        )
    return ""


def written_term(text: str, term: str) -> bool:
    """The Term as written, not as the first word of a sentence."""
    for s in go.split(verify_parties.SENTENCE_BREAK, soft_join(text)):
        words = _va.LIST_LEAD_TOKEN.findall(s)
        if any(i > 0 and w.strip(_TERM_TRIM) == term for i, w in enumerate(words)):
            return True
    return False


def document_definitions(evidence: Sequence[EvidenceUnit]) -> Mapping[str, list[Definition]]:
    """The explicit definitions of every unit, by document."""
    out: dict[str, list[Definition]] = {}
    for eu in evidence:
        if eu.document_id == "":
            continue
        for d in definitions_in(eu.text):
            have = out.setdefault(eu.document_id, [])
            if d not in have:
                have.append(d)
    return out
