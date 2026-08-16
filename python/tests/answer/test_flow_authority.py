"""ADR-0004 in the strict flow: cite an authority, or abstain.

The regression these pin, measured 2026-08-16 on the live law corpus: "What is
the notice period to end a month-to-month tenancy in Texas?" was answered from a
FLORIDA statute — verbatim, correctly cited, every claim verified, groundedness
100%. The faithfulness gate was right; it simply has nothing to say about
standing.
"""

from __future__ import annotations

from citenexus.answer.authority import INSUFFICIENT_AUTHORITY
from citenexus.answer.flow import AnswerFlow
from citenexus.answer.result import Decision, Result
from citenexus.domain.authority import AuthorityPolicy, encode_authority_meta
from citenexus.domain.trust import TrustMode
from citenexus.retrieve.types import Candidate, RetrievalSignal

_ORDER = ("out-of-jurisdiction", "secondary-blog", "general-statute", "controlling-statute")
_FLOORED = AuthorityPolicy.ordered(_ORDER, minimum_tier="general-statute")

_NOTICE = "A tenancy may be terminated by giving not less than 30 days notice."


def _candidate(doc: str, tier: str | None, text: str = _NOTICE) -> Candidate:
    return Candidate(
        eu_id=f"{doc}::0",
        score=1.0,
        signal=RetrievalSignal.vector,
        document_id=doc,
        text=text,
        passage=text,
        language="en",
        authority_meta=(
            encode_authority_meta({"authority_tier": tier}) if tier is not None else ""
        ),
    )


class _Echo:
    """Faithful generator — quotes the passage verbatim, so the gate passes."""

    calls = 0

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        type(self).calls += 1
        return passage


def _ask(candidates: list[Candidate], *, mode: TrustMode = TrustMode.strict) -> Result:
    flow = AnswerFlow(generator=_Echo(), authority=_FLOORED)
    return flow.ask("What notice ends a month-to-month tenancy?", candidates, mode=mode)


class TestStrictFloor:
    def test_out_of_jurisdiction_only_abstains(self) -> None:
        result = _ask([_candidate("06-florida-83_57-statute", "out-of-jurisdiction")])
        assert result.evidence.decision is Decision.refused
        assert result.sources == ()

    def test_the_refusal_names_authority_not_missing_evidence(self) -> None:
        result = _ask([_candidate("06-florida-83_57-statute", "out-of-jurisdiction")])
        assert result.missing_evidence == (INSUFFICIENT_AUTHORITY,)
        assert result.evidence.authority_floor_applied is True

    def test_distinguishable_from_no_evidence_found(self) -> None:
        empty = AnswerFlow(generator=_Echo(), authority=_FLOORED).ask(
            "utterly unrelated interrogative", []
        )
        floored = _ask([_candidate("06-florida-83_57-statute", "out-of-jurisdiction")])
        assert empty.evidence.decision is floored.evidence.decision
        assert empty.missing_evidence != floored.missing_evidence
        assert empty.evidence.authority_floor_applied is False

    def test_no_generator_call_when_the_floor_empties_selection(self) -> None:
        _Echo.calls = 0
        _ask([_candidate("06-florida-83_57-statute", "out-of-jurisdiction")])
        assert _Echo.calls == 0

    def test_the_authority_answers_when_present(self) -> None:
        result = _ask(
            [
                _candidate("06-florida-83_57-statute", "out-of-jurisdiction"),
                _candidate("01-ca-civ-1946_1-statute", "controlling-statute"),
            ]
        )
        assert result.evidence.decision is Decision.answered
        assert result.sources[0].document == "01-ca-civ-1946_1-statute"
        assert result.evidence.authority_tier == "controlling-statute"


class TestModes:
    def test_normal_may_still_cite_a_low_tier_source(self) -> None:
        result = _ask(
            [_candidate("06-florida-83_57-statute", "out-of-jurisdiction")],
            mode=TrustMode.normal,
        )
        assert result.evidence.decision is Decision.answered
        assert result.evidence.authority_floor_applied is False

    def test_exploratory_ignores_authority(self) -> None:
        result = _ask(
            [_candidate("05-nolo-month-to-month-blog", "secondary-blog")],
            mode=TrustMode.exploratory,
        )
        assert result.evidence.decision is Decision.answered


class TestUnconfigured:
    def test_default_policy_changes_nothing(self) -> None:
        """No floor, no metadata: the pre-ADR-0004 flow, signals empty."""
        flow = AnswerFlow(generator=_Echo())
        result = flow.ask(
            "What notice ends a month-to-month tenancy?",
            [_candidate("06-florida-83_57-statute", None)],
        )
        assert result.evidence.decision is Decision.answered
        assert result.evidence.authority_tier == ""
        assert result.evidence.authority_floor_applied is False
