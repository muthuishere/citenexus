"""The subtype guard: the bare head noun for a fact the unit states only of a
subtype.

Port of ``golang/answer/verify_subtypes.go`` (ADR-0016). For a small class of
head nouns whose subtypes are different facts (verlof/leave, toelage/allowance,
vergoeding/reimbursement, uitkering/benefit), a claim that uses the head BARE
over a unit where the head occurs only inside compounds or behind a known scope
qualifier, and never otherwise, is refused. Can only refuse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_conditions, verify_exclusions, verify_roles
from citenexus.answer.verify import is_stopword
from citenexus.answer.verify_guards_model import CONTEXT_STOP, number_value, unit_of
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig


@dataclass(frozen=True)
class SubtypeHead:
    """One head noun with its forms in any language (lowercase)."""

    forms: tuple[str, ...]


#: leave, allowance, reimbursement, benefit.
DEFAULT_SUBTYPE_HEADS: tuple[SubtypeHead, ...] = (
    SubtypeHead(("verlof", "leave")),
    SubtypeHead(("toelage", "toelagen", "allowance", "allowances")),
    SubtypeHead(("vergoeding", "vergoedingen", "reimbursement", "reimbursements")),
    SubtypeHead(("uitkering", "uitkeringen", "benefit", "benefits")),
)

_BARE_BEFORE = frozenset(
    {"tijdens", "during", "bij", "voor", "for", "zonder", "without", "geen", "no"}
)


def bare_use(tokens: Sequence[str], i: int) -> bool:
    """tokens[i] is a head form used without a modifier before it."""
    if i == 0:
        return True
    prev = tokens[i - 1]
    if is_stopword(prev) or prev in CONTEXT_STOP or verify_roles.is_article(prev):
        return True
    # A measure is not a subtype: "twee dagen verlof".
    if number_value(prev, "") is not None or unit_of(prev) is not None:
        return True
    return prev in verify_exclusions.GROUP_PREPOSITIONS or prev in _BARE_BEFORE


def subtype_guard(claim: str, eu: EvidenceUnit, cfg: GuardConfig) -> str:
    """See the module docstring."""
    claim_tokens = tokenize_v2(claim)
    unit_tokens = tokenize_v2(eu.text)
    for head in cfg.subtypes:
        claim_bare = ""
        for i, t in enumerate(claim_tokens):
            if t in head.forms and bare_use(claim_tokens, i):
                claim_bare = t
        if claim_bare == "":
            continue
        bare, qualified, example = False, False, ""
        for i, t in enumerate(unit_tokens):
            if t in head.forms:
                # A separate modifier counts only when it is a known scope
                # qualifier ("onbetaald verlof").
                if i > 0 and unit_tokens[i - 1] in verify_conditions.SCOPE_QUALIFIERS:
                    qualified = True
                    example = unit_tokens[i - 1] + " " + t
                    continue
                bare = True
                continue
            for f in head.forms:
                if go.blen(t) > go.blen(f) + 2 and t.endswith(f):
                    qualified = True
                    example = t
        if qualified and not bare:
            return (
                f"subtype guard: the claim says {go.quote(claim_bare)}; "
                f"the passage only speaks of {go.quote(example)}"
            )
    return ""
