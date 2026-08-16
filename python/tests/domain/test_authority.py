"""ADR-0004: authority tiers and profiles — metadata in, total order out.

The invariant these tests exist to hold: a tier is a pure function of caller
metadata. A California statute's body text does not contain the word
"California", so anything content-derived is measurably wrong (a query-term
relevance floor fixed 2 of the law-corpus failures and broke 3). The profile seam
is therefore handed a ``Mapping[str, str]`` and never a passage.
"""

from __future__ import annotations

import pytest

from citenexus.domain.authority import (
    UNKNOWN_RANK,
    AuthorityPolicy,
    AuthorityProfile,
    AuthorityTier,
    DefaultAuthorityProfile,
    OrderedTierProfile,
    decode_authority_meta,
    encode_authority_meta,
)

_LEGAL_ORDER = (
    "out-of-jurisdiction",
    "secondary-blog",
    "general-statute",
    "statute",
    "binding-appellate",
    "controlling-statute",
)


class TestTierOrdering:
    def test_order_is_by_rank(self) -> None:
        assert AuthorityTier(1) < AuthorityTier(2)
        assert AuthorityTier(2) >= AuthorityTier(2)
        assert AuthorityTier(3).outranks(AuthorityTier(2))

    def test_name_is_never_compared(self) -> None:
        """Two profiles may disagree on naming and still share one total order."""
        assert not AuthorityTier(2, "zebra") > AuthorityTier(2, "aardvark")
        assert not AuthorityTier(2, "zebra") < AuthorityTier(2, "aardvark")
        assert AuthorityTier(2, "zebra") >= AuthorityTier(2, "aardvark")


class TestDefaultProfile:
    def test_everything_ranks_equal(self) -> None:
        profile = DefaultAuthorityProfile()
        a = profile.tier({"authority_tier": "controlling-statute"})
        b = profile.tier({"authority_tier": "secondary-blog"})
        c = profile.tier({})
        assert a.rank == b.rank == c.rank == 0

    def test_no_floor_can_exclude_anything(self) -> None:
        policy = AuthorityPolicy.unranked()
        assert policy.has_floor is False
        assert policy.meets_floor(AuthorityTier(-99))

    def test_satisfies_the_protocol(self) -> None:
        assert isinstance(DefaultAuthorityProfile(), AuthorityProfile)
        assert isinstance(OrderedTierProfile(()), AuthorityProfile)


class TestOrderedProfile:
    def test_caller_ordering_is_respected(self) -> None:
        profile = OrderedTierProfile(_LEGAL_ORDER)
        controlling = profile.tier({"authority_tier": "controlling-statute"})
        blog = profile.tier({"authority_tier": "secondary-blog"})
        assert controlling.outranks(blog)
        assert controlling.name == "controlling-statute"

    def test_unknown_tier_ranks_below_every_named_tier(self) -> None:
        profile = OrderedTierProfile(_LEGAL_ORDER)
        unknown = profile.tier({"authority_tier": "who-knows"})
        missing = profile.tier({})
        lowest = profile.tier({"authority_tier": "out-of-jurisdiction"})
        assert unknown.rank == missing.rank == UNKNOWN_RANK
        assert lowest.outranks(unknown)

    def test_metadata_key_is_configurable(self) -> None:
        profile = OrderedTierProfile(("low", "high"), key="standing")
        assert profile.tier({"standing": "high"}).rank == 1
        assert profile.tier({"authority_tier": "high"}).rank == UNKNOWN_RANK

    def test_is_deterministic(self) -> None:
        profile = OrderedTierProfile(_LEGAL_ORDER)
        meta = {"authority_tier": "statute"}
        assert profile.tier(meta) == profile.tier(dict(meta))


class TestPolicyFloor:
    def test_floor_admits_at_or_above(self) -> None:
        policy = AuthorityPolicy.ordered(_LEGAL_ORDER, minimum_tier="general-statute")
        assert policy.has_floor
        assert policy.meets_floor(policy.tier_of({"authority_tier": "general-statute"}))
        assert policy.meets_floor(policy.tier_of({"authority_tier": "controlling-statute"}))

    def test_floor_rejects_below_and_unknown(self) -> None:
        policy = AuthorityPolicy.ordered(_LEGAL_ORDER, minimum_tier="general-statute")
        assert not policy.meets_floor(policy.tier_of({"authority_tier": "secondary-blog"}))
        # The measured defect: a Florida statute answering a Texas question.
        assert not policy.meets_floor(policy.tier_of({"authority_tier": "out-of-jurisdiction"}))
        assert not policy.meets_floor(policy.tier_of({}))


class TestMetaRoundTrip:
    def test_round_trip_is_canonical(self) -> None:
        encoded = encode_authority_meta({"b": "2", "a": "1"})
        assert encoded == '{"a": "1", "b": "2"}'
        assert decode_authority_meta(encoded) == {"a": "1", "b": "2"}

    @pytest.mark.parametrize("value", [None, {}, "", "not json", "[]", 7])
    def test_absent_or_malformed_reads_as_unranked(self, value: object) -> None:
        """A corpus predating the column is un-migrated, not broken."""
        if isinstance(value, dict) or value is None:
            assert encode_authority_meta(value) == ""
        assert decode_authority_meta(value) == {}
