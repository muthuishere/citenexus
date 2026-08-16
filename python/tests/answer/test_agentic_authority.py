"""ADR-0004 inside the deep-ask loop: cite an authority, or abstain.

The `authority-floor` change closed this on the strict flow and recorded the gap
(tasks 4.7): `strategy="deep"` never took the policy, so the exact wrong answer
the floor prevents by default — a FLORIDA statute answering a TEXAS question,
verbatim, every claim verified — was still one keyword away.

The loop is the *more* exposed path: its gate is single-EU, so ANY pooled unit is
on its own sufficient to carry a claim. The floor therefore runs at POOL
ADMISSION, not once at the end.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from citenexus.answer.agentic import AgenticAnswerFlow, LoopBudget
from citenexus.answer.authority import INSUFFICIENT_AUTHORITY
from citenexus.answer.decision import LoopDecision
from citenexus.answer.result import Decision, LoopStopReason, Result
from citenexus.domain.authority import AuthorityPolicy, encode_authority_meta
from citenexus.domain.trust import TrustMode
from citenexus.testing.fakes import FakeToolLLM

Row = dict[str, Any]

_ORDER = ("out-of-jurisdiction", "secondary-blog", "general-statute", "controlling-statute")
_FLOORED = AuthorityPolicy.ordered(_ORDER, minimum_tier="general-statute")

_NOTICE = "A tenancy may be terminated by giving not less than 30 days notice."
_QUESTION = "What notice ends a month-to-month tenancy in Texas?"


def _row(eu_id: str, text: str, tier: str | None, *, score: float = 1.0) -> Row:
    return {
        "eu_id": eu_id,
        "text": text,
        "document_id": eu_id,
        "page": None,
        "language": "en",
        "checksum": f"sum-{eu_id}",
        "signal": "vector",
        "score": score,
        "authority_meta": (
            encode_authority_meta({"authority_tier": tier}) if tier is not None else ""
        ),
    }


class _Echo:
    """Faithful generator — quotes the pooled passage, so the gate passes."""

    def __init__(self) -> None:
        self.calls = 0
        self.passages: list[str] = []

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        self.calls += 1
        self.passages.append(passage)
        return passage


class _RecordingDecider:
    """A scripted decider that remembers exactly what evidence it was shown."""

    def __init__(self, decisions: Sequence[LoopDecision]) -> None:
        self._inner = FakeToolLLM(decisions)
        self.seen: list[list[str]] = []

    def decide(self, question: str, evidence: Sequence[str]) -> LoopDecision:
        self.seen.append(list(evidence))
        return self._inner.decide(question, evidence)


def _flow(
    search: Any,
    decisions: Sequence[LoopDecision],
    *,
    generator: Any,
    policy: AuthorityPolicy = _FLOORED,
    budget: LoopBudget | None = None,
    decider: Any = None,
) -> AgenticAnswerFlow:
    return AgenticAnswerFlow(
        generator=generator,
        decider=decider or FakeToolLLM(decisions),
        tools=[{"name": "search_evidence", "handler": search}],
        budget=budget or LoopBudget(max_hops=3),
        authority=policy,
    )


def _ask(
    search: Any,
    *,
    generator: Any,
    decisions: Sequence[LoopDecision] = (LoopDecision(sufficient=True),),
    policy: AuthorityPolicy = _FLOORED,
    mode: TrustMode = TrustMode.strict,
    budget: LoopBudget | None = None,
    decider: Any = None,
) -> Result:
    flow = _flow(
        search, decisions, generator=generator, policy=policy, budget=budget, decider=decider
    )
    return flow.ask(_QUESTION, mode=mode)


class TestStrictFloor:
    def test_below_floor_only_abstains(self) -> None:
        generator = _Echo()
        result = _ask(
            lambda q, k: [_row("06-florida-83_57-statute", _NOTICE, "out-of-jurisdiction")],
            generator=generator,
        )
        assert result.evidence.decision is Decision.refused
        assert result.sources == ()

    def test_the_refusal_names_authority_not_missing_evidence(self) -> None:
        result = _ask(
            lambda q, k: [_row("06-florida-83_57-statute", _NOTICE, "out-of-jurisdiction")],
            generator=_Echo(),
        )
        assert result.missing_evidence == (INSUFFICIENT_AUTHORITY,)
        assert result.evidence.authority_floor_applied is True

    def test_distinguishable_from_no_evidence_found(self) -> None:
        floored = _ask(
            lambda q, k: [_row("06-florida-83_57-statute", _NOTICE, "out-of-jurisdiction")],
            generator=_Echo(),
        )
        empty = _ask(lambda q, k: [], generator=_Echo())
        assert empty.evidence.decision is floored.evidence.decision
        assert empty.missing_evidence != floored.missing_evidence
        assert empty.evidence.authority_floor_applied is False

    def test_no_generator_call_when_the_floor_empties_the_pool(self) -> None:
        generator = _Echo()
        _ask(
            lambda q, k: [_row("06-florida-83_57-statute", _NOTICE, "out-of-jurisdiction")],
            generator=generator,
        )
        assert generator.calls == 0

    def test_the_authority_answers_when_present(self) -> None:
        result = _ask(
            lambda q, k: [
                _row("06-florida-83_57-statute", _NOTICE, "out-of-jurisdiction"),
                _row("02-tx-prop-91_001-statute", _NOTICE, "controlling-statute"),
            ],
            generator=_Echo(),
        )
        assert result.evidence.decision is Decision.answered
        assert [s.document for s in result.sources] == ["02-tx-prop-91_001-statute"]
        assert result.evidence.authority_floor_applied is True


class TestPoolAdmission:
    """The floor runs BEFORE pooling — not once at the end."""

    def test_withheld_evidence_never_reaches_the_decision_model(self) -> None:
        decider = _RecordingDecider([LoopDecision(sufficient=False, next_query="again")])
        _ask(
            lambda q, k: [
                _row("florida", "Florida says something entirely else.", "out-of-jurisdiction"),
                _row("texas", _NOTICE, "controlling-statute"),
            ],
            generator=_Echo(),
            decider=decider,
        )
        shown = [text for call in decider.seen for text in call]
        assert all("Florida" not in text for text in shown)

    def test_withheld_evidence_consumes_no_budget(self) -> None:
        rows = [
            _row(f"junk-{i}", f"Irrelevant clause number {i}.", "out-of-jurisdiction")
            for i in range(3)
        ] + [_row("texas", _NOTICE, "controlling-statute")]
        result = _ask(
            lambda q, k: rows,
            generator=_Echo(),
            budget=LoopBudget(max_hops=2, max_evidence_units=2),
        )
        assert result.evidence.loop is not None
        # Only the one admissible unit is pooled; the three junk rows would have
        # blown the 2-unit cap and ended the loop with `budget`.
        assert result.evidence.loop.evidence_units == 1
        assert result.evidence.decision is Decision.answered

    def test_withheld_evidence_cannot_support_a_claim(self) -> None:
        # The generator is shown ONLY the admissible pool, and the single-EU gate
        # has only that pool to attribute against.
        generator = _Echo()
        result = _ask(
            lambda q, k: [
                _row("florida", "Florida requires fifteen days notice.", "out-of-jurisdiction"),
                _row("texas", _NOTICE, "controlling-statute"),
            ],
            generator=generator,
            decider=None,
        )
        assert all("Florida" not in passage for passage in generator.passages)
        assert all(claim.sources == ("texas::0",) or claim.sources for claim in result.claims)
        assert [s.document for s in result.sources] == ["texas"]


class TestWithheldIsNotExhausted:
    def test_a_withheld_only_hop_does_not_halt_the_loop(self) -> None:
        def search(query: str, k: int) -> list[Row]:
            if "texas" in query.lower():
                return [_row("texas", _NOTICE, "controlling-statute")]
            return [_row("florida", "Florida says otherwise.", "out-of-jurisdiction")]

        result = _ask(
            search,
            generator=_Echo(),
            decisions=[LoopDecision(sufficient=False, next_query="texas notice")],
        )
        assert result.evidence.decision is Decision.answered
        assert [s.document for s in result.sources] == ["texas"]

    def test_an_already_seen_only_hop_still_halts(self) -> None:
        result = _ask(
            lambda q, k: [_row("texas", _NOTICE, "controlling-statute")],
            generator=_Echo(),
            decisions=[LoopDecision(sufficient=False, next_query="again")],
        )
        assert result.evidence.loop is not None
        assert result.evidence.loop.stop_reason is LoopStopReason.no_new_evidence


class TestOrderingAndSignals:
    def test_a_claim_is_cited_to_the_most_authoritative_supporting_unit(self) -> None:
        result = _ask(
            lambda q, k: [
                _row("blog", _NOTICE, "secondary-blog"),
                _row("texas", _NOTICE, "controlling-statute"),
            ],
            generator=_Echo(),
            policy=AuthorityPolicy.ordered(_ORDER),
        )
        assert result.evidence.decision is Decision.answered
        assert [s.document for s in result.sources] == ["texas"]

    def test_authority_tier_reports_the_weakest_cited_tier(self) -> None:
        result = _ask(
            lambda q, k: [
                _row("texas", _NOTICE, "controlling-statute"),
                _row("general", "Landlords must maintain the premises.", "general-statute"),
            ],
            generator=_Echo(),
        )
        assert result.evidence.decision is Decision.answered
        assert len(result.sources) == 2
        assert result.evidence.authority_tier == "general-statute"

    def test_no_withholding_means_no_floor_applied(self) -> None:
        result = _ask(
            lambda q, k: [_row("texas", _NOTICE, "controlling-statute")],
            generator=_Echo(),
        )
        assert result.evidence.authority_floor_applied is False

    def test_unconfigured_authority_leaves_the_loop_unchanged(self) -> None:
        rows = [_row("a", _NOTICE, None), _row("b", "Landlords must give notice.", None)]
        floored = _ask(lambda q, k: rows, generator=_Echo(), policy=AuthorityPolicy.unranked())
        bare = AgenticAnswerFlow(
            generator=_Echo(),
            decider=FakeToolLLM([LoopDecision(sufficient=True)]),
            tools=[{"name": "search_evidence", "handler": lambda q, k: rows}],
            budget=LoopBudget(max_hops=3),
        ).ask(_QUESTION, mode=TrustMode.strict)
        assert floored == bare


class TestTrustModeCoupling:
    def _mixed(self) -> Any:
        return lambda q, k: [
            _row("florida", "Florida requires fifteen days notice.", "out-of-jurisdiction"),
            _row("texas", _NOTICE, "controlling-statute"),
        ]

    def test_normal_withholds_nothing_and_reorders(self) -> None:
        result = _ask(self._mixed(), generator=_Echo(), mode=TrustMode.normal)
        assert result.evidence.loop is not None
        assert result.evidence.loop.evidence_units == 2
        assert result.evidence.authority_floor_applied is False

    def test_exploratory_ignores_authority(self) -> None:
        generator = _Echo()
        result = _ask(self._mixed(), generator=generator, mode=TrustMode.exploratory)
        assert result.evidence.loop is not None
        assert result.evidence.loop.evidence_units == 2
        # Untouched order: the input order, floor ignored entirely.
        assert generator.passages[0].startswith("Florida requires")
