"""The authority selection point — ADR-0004, applied strictly after grounding.

ONE function, used by both answer strategies. The strict flow
(:mod:`citenexus.answer.flow`) calls it between grounding and generation; the
deep-ask loop (:mod:`citenexus.answer.agentic`) calls it at pool admission and
again to order the pool. It may REORDER evidence and, in strict mode, DROP what
is below the caller's floor. It can never promote evidence the retrieval /
grounding stage rejected, so the only reachable behaviour change is more
abstention — it is structurally incapable of admitting an ungrounded claim.

It is deliberately generic over "anything carrying ``authority_meta``" rather
than duplicated per flow: two implementations of a min-bar guarantee are two
implementations that can drift apart, and the drifted one is the hole.

This module does not import the faithfulness predicate, and the predicate is
never given a tier. ADR-0004 explicitly rejected entangling the two invariants.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from citenexus.domain.authority import (
    AuthorityPolicy,
    AuthorityTier,
    decode_authority_meta,
)
from citenexus.domain.trust import TrustMode


class HasAuthorityMeta(Protocol):
    """Evidence carrying caller-supplied authority METADATA — and nothing else.

    This one-member protocol is the ADR-0004 seam made structural: selection can
    see the metadata and has no way to reach ``text`` / ``passage`` /
    ``citable_text``, so authority *cannot* become content-derived by accident.
    Read-only by design — nothing here mutates evidence.
    """

    @property
    def authority_meta(self) -> str: ...


E = TypeVar("E", bound=HasAuthorityMeta)

#: The refusal reason when the floor emptied the selection. Deliberately DISTINCT
#: from "no sufficiently relevant evidence found": conflating "I found nothing"
#: with "what I found has no standing" is how this defect stayed invisible.
INSUFFICIENT_AUTHORITY = "no evidence at or above the required authority tier"


@dataclass(frozen=True)
class AuthoritySelection(Generic[E]):
    """The selected candidates plus what authority did to get there."""

    candidates: tuple[E, ...]
    #: Candidates that were grounded but dropped for standing. Kept so a refusal
    #: can say what it declined to cite.
    excluded: tuple[E, ...] = ()

    @property
    def floor_applied(self) -> bool:
        """True when the floor actually WITHHELD grounded evidence.

        Deliberately not "a floor was configured": a signal that is true on every
        strict call tells the caller nothing. This one means "I had evidence and
        declined to cite it for lack of standing", which is the fact that
        distinguishes an authority abstain from an empty-handed one.
        """
        return bool(self.excluded)


def tier_of(candidate: HasAuthorityMeta, policy: AuthorityPolicy) -> AuthorityTier:
    """The candidate's tier — from its METADATA only, never its text."""
    return policy.tier_of(decode_authority_meta(candidate.authority_meta))


def select_by_authority(
    candidates: Sequence[E],
    *,
    policy: AuthorityPolicy,
    mode: TrustMode,
) -> AuthoritySelection[E]:
    """Reorder (and in strict mode, floor) already-grounded candidates.

    - ``exploratory`` ignores authority entirely — the input, untouched.
    - ``normal`` uses authority as a TIE-BREAK: a stable sort by descending
      tier, nothing dropped.
    - ``strict`` enforces the floor first (below-floor candidates are excluded
      outright, with no fallback), then the same stable sort.

    The sort is stable, so candidates of equal tier keep their fusion order. No
    secondary key is used: one would silently re-rank equal-authority evidence.
    """
    if mode is TrustMode.exploratory:
        return AuthoritySelection(candidates=tuple(candidates))

    ranked = [(candidate, tier_of(candidate, policy)) for candidate in candidates]

    excluded: tuple[E, ...] = ()
    if mode is TrustMode.strict and policy.has_floor:
        excluded = tuple(c for c, tier in ranked if not policy.meets_floor(tier))
        ranked = [(c, tier) for c, tier in ranked if policy.meets_floor(tier)]

    ordered = sorted(ranked, key=lambda pair: -pair[1].rank)
    return AuthoritySelection(
        candidates=tuple(candidate for candidate, _ in ordered),
        excluded=excluded,
    )
