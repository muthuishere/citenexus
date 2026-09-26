"""The union rule for a list item joined to a content lead-in.

Port of ``golang/answer/verify_union.go`` (ADR-0016). The writer often cites
the lead-in to the unit that NAMES a provision and the item to the unit that
STATES the fact; checked against either unit alone the joined claim fails. The
union rule admits it against both units together — but only the lead-in's
REFERENCES may come from the lead-in's unit A; everything else must hold in the
item's unit B (``lead_in_scope``), the guards run split by provenance, and the
checker must entail the joined claim from A+B (``union_premise``). Never on the
gate path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from citenexus.answer import _gostr as go
from citenexus.answer import verify_answer as _va
from citenexus.answer import verify_guards
from citenexus.answer.tables import POLARITY_MARKERS
from citenexus.answer.verify import is_stopword
from citenexus.answer.verify_guards_model import CONTEXT_STOP
from citenexus.tokenize import tokenize_v2

if TYPE_CHECKING:
    from citenexus.answer.verify_answer import EvidenceUnit
    from citenexus.answer.verify_guards import GuardConfig


def union_premise(a: EvidenceUnit, b: EvidenceUnit) -> EvidenceUnit:
    """The lead-in's unit, then the item's. Two languages that differ leave it
    undeclared, so a number either could read ambiguously matches only as
    spelled."""
    language = a.language
    if _va.primary_language(a.language) != _va.primary_language(b.language):
        language = ""
    return _va.EvidenceUnit(
        id=a.id + "\x00" + b.id,
        document_id=a.document_id + "\n" + b.document_id,
        text=a.text + "\n\n" + b.text,
        language=language,
    )


def union_refusal(
    claim: str,
    lead: str,
    item: str,
    claim_language: str,
    a: EvidenceUnit,
    b: EvidenceUnit,
    cfg: GuardConfig,
) -> str:
    """The deterministic part of the union rule for one pair; the first refusal."""
    reason = lead_in_scope(lead, b)
    if reason:
        return reason
    reason = verify_guards.guards(lead, claim_language, a, cfg.as_fragment())
    if reason:
        return reason
    reason = verify_guards.guards(item, claim_language, b, cfg)
    if reason:
        return reason
    return verify_guards.guards(claim, claim_language, union_premise(a, b), cfg)


#: Attribute a lead-in to a source and restrict nothing.
LEAD_IN_ATTRIBUTION = frozenset(
    {
        "volgens",
        "krachtens",
        "ingevolge",
        "conform",
        "onder",
        "geldt",
        "gelden",
        "bepaalt",
        "according",
        "pursuant",
        "under",
        "applies",
        "apply",
        "provides",
        "states",
    }
)

_REFERENCE_TRIM = ".,;:()[]\"'"


def lead_in_scope(lead: str, b: EvidenceUnit) -> str:
    """Every lead-in word that is not a reference must be in the item's unit."""
    have = set(tokenize_v2(b.text))
    named: set[str] = set()
    for name in verify_guards.names(lead):
        named.update(tokenize_v2(name))
    words = _va.LIST_LEAD_TOKEN.findall(lead)
    reference = [False] * len(words)
    for i, w in enumerate(words):
        if go.lower(w.strip(_REFERENCE_TRIM)) not in _va.LIST_REFERENCE_NOUNS:
            continue
        reference[i] = True
        if i + 1 < len(words) and go.contains_any(words[i + 1], "0123456789"):
            reference[i + 1] = True
    for i, w in enumerate(words):
        if reference[i]:
            continue
        for tok in tokenize_v2(w):
            if tok in have:
                continue
            if tok not in POLARITY_MARKERS and _free_lead_in_token(tok, named):
                continue
            return f"lead-in guard: {go.quote(tok)} is not in the item's evidence"
    return ""


def _free_lead_in_token(tok: str, named: set[str]) -> bool:
    return is_stopword(tok) or tok in CONTEXT_STOP or tok in LEAD_IN_ATTRIBUTION or tok in named
