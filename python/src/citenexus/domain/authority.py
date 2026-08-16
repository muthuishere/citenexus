"""Authority — the standing of a SOURCE, kept strictly apart from grounding.

The faithfulness gate proves an answer's words came from the passage it cites.
It does not — and structurally cannot — prove the passage had any standing to
answer the question. Measured on the live law corpus (2026-08-16): a **Florida**
statute answered a **Texas** question with 100% groundedness and every claim
verified. The gate was right; the source was not.

Authority closes that gap, and ADR-0004 pins how:

- **Metadata-derived, never content-derived.** A California statute's body text
  does not contain the word "California"; jurisdiction, precedential weight and
  publisher standing are properties asserted by whoever curated the corpus, not
  recoverable from the prose. Two content-derived attempts were measured and
  rejected (a query-term relevance floor: fixes 2, breaks 3; a token-coverage
  threshold: the bad answers score inside the good range). The seam here is
  therefore ``Mapping[str, str] -> AuthorityTier``: a profile is handed metadata
  and never a passage, so it *cannot* read content.
- **Applied strictly AFTER grounding**, as a separate selection / minimum-bar
  signal (see :mod:`citenexus.answer.authority`). Nothing in this module imports
  the faithfulness predicate, and the predicate never sees a tier.

``default.v1`` ranks every source equal, which is exactly today's behaviour: all
ranks equal ⇒ the stable sort is the identity ⇒ fusion order survives ⇒ existing
Results are unchanged. The feature is strictly opt-in.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: The row column (and the ingest keyword) carrying caller-supplied metadata.
AUTHORITY_META_COLUMN = "authority_meta"

#: The metadata key ``ordered.v1`` reads by default.
DEFAULT_TIER_KEY = "authority_tier"

#: Rank assigned to a tier the profile does not know. Below every named tier, so
#: an uncurated document can never sneak above a floor.
UNKNOWN_RANK = -1


@dataclass(frozen=True)
class AuthorityTier:
    """A totally-ordered standing. Higher ``rank`` = more authoritative.

    ``name`` is reporting-only and is deliberately EXCLUDED from comparison: two
    profiles that disagree on naming must still produce one total order, and
    comparing names would make authority depend on spelling.
    """

    rank: int
    name: str = ""

    def __lt__(self, other: AuthorityTier) -> bool:
        return self.rank < other.rank

    def __le__(self, other: AuthorityTier) -> bool:
        return self.rank <= other.rank

    def __gt__(self, other: AuthorityTier) -> bool:
        return self.rank > other.rank

    def __ge__(self, other: AuthorityTier) -> bool:
        return self.rank >= other.rank

    def outranks(self, other: AuthorityTier) -> bool:
        return self.rank > other.rank


#: The tier every source gets when nobody has said otherwise.
UNRANKED = AuthorityTier(rank=0, name="")


@runtime_checkable
class AuthorityProfile(Protocol):
    """Maps caller-supplied source METADATA to a tier. Never sees content."""

    profile_version: str

    def tier(self, meta: Mapping[str, str]) -> AuthorityTier: ...


class DefaultAuthorityProfile:
    """``default.v1`` — everything unranked; today's behaviour, exactly.

    This is the compatibility proof: every source compares equal, so the
    authority sort is the identity and no floor can ever exclude anything.
    """

    profile_version = "default.v1"

    def tier(self, meta: Mapping[str, str]) -> AuthorityTier:
        return UNRANKED


class OrderedTierProfile:
    """``ordered.v1`` — a caller-supplied ordering of tier NAMES.

    ``order`` is least-authoritative first, so a legal corpus reads naturally::

        OrderedTierProfile(("out-of-jurisdiction", "secondary-blog",
                            "general-statute", "statute",
                            "binding-appellate", "controlling-statute"))

    A tier name absent from ``order`` — including missing metadata entirely —
    ranks ``UNKNOWN_RANK``, below every named tier.
    """

    profile_version = "ordered.v1"

    def __init__(self, order: tuple[str, ...], *, key: str = DEFAULT_TIER_KEY) -> None:
        self._rank = {name: index for index, name in enumerate(order)}
        self._key = key

    def tier(self, meta: Mapping[str, str]) -> AuthorityTier:
        name = meta.get(self._key, "")
        return AuthorityTier(rank=self._rank.get(name, UNKNOWN_RANK), name=name)

    def tier_named(self, name: str) -> AuthorityTier:
        """The tier for a bare tier NAME — how a caller states a floor."""
        return self.tier({self._key: name})


@dataclass(frozen=True)
class AuthorityPolicy:
    """A profile plus an optional minimum tier (the strict-mode floor).

    ``minimum is None`` means no floor: selection is reorder-only in every trust
    mode, and with ``default.v1`` that reorder is itself the identity.
    """

    profile: AuthorityProfile = field(default_factory=DefaultAuthorityProfile)
    minimum: AuthorityTier | None = None

    @property
    def has_floor(self) -> bool:
        return self.minimum is not None

    def tier_of(self, meta: Mapping[str, str]) -> AuthorityTier:
        return self.profile.tier(meta)

    def meets_floor(self, tier: AuthorityTier) -> bool:
        return self.minimum is None or tier >= self.minimum

    @classmethod
    def unranked(cls) -> AuthorityPolicy:
        """The default policy — ``default.v1``, no floor, no behaviour change."""
        return cls()

    @classmethod
    def ordered(
        cls,
        order: tuple[str, ...],
        *,
        minimum_tier: str | None = None,
        key: str = DEFAULT_TIER_KEY,
    ) -> AuthorityPolicy:
        """Build an ``ordered.v1`` policy, optionally floored at a tier name."""
        profile = OrderedTierProfile(order, key=key)
        minimum = profile.tier_named(minimum_tier) if minimum_tier is not None else None
        return cls(profile=profile, minimum=minimum)


def encode_authority_meta(meta: Mapping[str, str] | None) -> str:
    """Canonical JSON for the additive ``authority_meta`` row column.

    Sorted keys so the column is byte-stable across re-ingests; ``""`` for absent
    metadata, which every reader decodes back to ``{}`` (unranked).
    """
    if not meta:
        return ""
    return json.dumps({str(k): str(v) for k, v in meta.items()}, sort_keys=True)


def decode_authority_meta(value: object) -> dict[str, str]:
    """Read the column back. Missing / blank / malformed ⇒ ``{}`` (unranked).

    Rows written before this column existed simply have no such key. That is a
    corpus predating the feature, not a broken one, so it reads as unranked
    rather than failing — the same "absence is not failure" posture the rest of
    the library takes with best-effort metadata.
    """
    if not isinstance(value, str) or not value:
        return {}
    try:
        decoded = json.loads(value)
    except ValueError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(k): str(v) for k, v in decoded.items()}
