"""ADR-0004: the authority selection point over already-grounded candidates."""

from __future__ import annotations

from citenexus.answer.authority import select_by_authority
from citenexus.domain.authority import AuthorityPolicy, encode_authority_meta
from citenexus.domain.trust import TrustMode
from citenexus.retrieve.types import Candidate, RetrievalSignal

_ORDER = ("out-of-jurisdiction", "secondary-blog", "general-statute", "controlling-statute")


def _candidate(eu_id: str, tier: str | None = None) -> Candidate:
    return Candidate(
        eu_id=eu_id,
        score=1.0,
        signal=RetrievalSignal.vector,
        document_id=eu_id,
        text="text",
        passage="text",
        authority_meta=(
            encode_authority_meta({"authority_tier": tier}) if tier is not None else ""
        ),
    )


_FLORIDA = _candidate("06-florida", "out-of-jurisdiction")
_CALIFORNIA = _candidate("01-ca-civ", "controlling-statute")
_BLOG = _candidate("05-nolo", "secondary-blog")

_FLOORED = AuthorityPolicy.ordered(_ORDER, minimum_tier="general-statute")


class TestStrict:
    def test_below_floor_candidates_are_dropped(self) -> None:
        selection = select_by_authority(
            [_FLORIDA, _CALIFORNIA], policy=_FLOORED, mode=TrustMode.strict
        )
        assert [c.eu_id for c in selection.candidates] == ["01-ca-civ"]
        assert [c.eu_id for c in selection.excluded] == ["06-florida"]
        assert selection.floor_applied is True

    def test_all_below_floor_leaves_nothing(self) -> None:
        """No fallback to a lower tier — that fallback IS the defect."""
        selection = select_by_authority([_FLORIDA, _BLOG], policy=_FLOORED, mode=TrustMode.strict)
        assert selection.candidates == ()
        assert selection.floor_applied is True

    def test_unranked_candidate_never_passes_a_floor(self) -> None:
        selection = select_by_authority(
            [_candidate("unlabelled")], policy=_FLOORED, mode=TrustMode.strict
        )
        assert selection.candidates == ()


class TestNormal:
    def test_tie_break_only_nothing_dropped(self) -> None:
        selection = select_by_authority(
            [_FLORIDA, _CALIFORNIA], policy=_FLOORED, mode=TrustMode.normal
        )
        assert [c.eu_id for c in selection.candidates] == ["01-ca-civ", "06-florida"]
        assert selection.floor_applied is False


class TestExploratory:
    def test_authority_is_ignored(self) -> None:
        candidates = [_FLORIDA, _CALIFORNIA, _BLOG]
        selection = select_by_authority(candidates, policy=_FLOORED, mode=TrustMode.exploratory)
        assert list(selection.candidates) == candidates
        assert selection.floor_applied is False


class TestCompatibility:
    def test_default_policy_is_the_identity(self) -> None:
        candidates = [_FLORIDA, _CALIFORNIA, _BLOG, _candidate("plain")]
        for mode in TrustMode:
            selection = select_by_authority(
                candidates, policy=AuthorityPolicy.unranked(), mode=mode
            )
            assert list(selection.candidates) == candidates
            assert selection.floor_applied is False

    def test_equal_tiers_keep_fusion_order(self) -> None:
        same = [_candidate(f"eu-{i}", "controlling-statute") for i in range(5)]
        selection = select_by_authority(same, policy=_FLOORED, mode=TrustMode.strict)
        assert [c.eu_id for c in selection.candidates] == [c.eu_id for c in same]

    def test_authority_never_reads_passage_text(self) -> None:
        """Standing comes from metadata alone — jurisdiction is not in the prose."""
        rich = _candidate("blog-that-says-california", "secondary-blog").model_copy(
            update={"text": "California " * 50, "passage": "California " * 50}
        )
        selection = select_by_authority([rich], policy=_FLOORED, mode=TrustMode.strict)
        assert selection.candidates == ()
