"""The deep-ask scripted loop, its budget, and the per-claim single-EU gate.

All offline with deterministic fakes: a scripted ``search`` tool, a
``FakeToolLLM`` driver, and generators that either echo the pool or return a
scripted answer to exercise the gate. Budgets bound cost; only the gate bounds
truth — so the assertions split cleanly between the two.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from citenexus.answer.agentic import AgenticAnswerFlow, LoopBudget
from citenexus.answer.decision import LoopDecision
from citenexus.answer.result import Decision, LoopStopReason
from citenexus.testing.fakes import FakeLLM, FakeToolLLM

Row = dict[str, Any]


def _row(eu_id: str, text: str, *, document_id: str | None = None, score: float = 1.0) -> Row:
    return {
        "eu_id": eu_id,
        "text": text,
        "document_id": document_id or eu_id,
        "page": None,
        "language": "en",
        "checksum": f"sum-{eu_id}",
        "signal": "vector",
        "score": score,
    }


def _tools(search: Any) -> list[dict[str, Any]]:
    return [{"name": "search_evidence", "handler": search}]


class _ScriptedGenerator:
    """Returns a fixed answer regardless of the passage — to drive the gate."""

    def __init__(self, answer: str) -> None:
        self._answer = answer

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return self._answer


def _flow(
    search: Any, decisions: Sequence[LoopDecision], *, budget: LoopBudget, generator: Any
) -> AgenticAnswerFlow:
    return AgenticAnswerFlow(
        generator=generator,
        decider=FakeToolLLM(decisions),
        tools=_tools(search),
        budget=budget,
    )


# --- Loop control / budget (cost bounds) -----------------------------------


def test_no_new_evidence_halts_deterministically() -> None:
    # Every hop returns the SAME row → the second hop adds nothing → halt.
    def search(query: str, k: int) -> list[Row]:
        return [_row("a", "the sky is blue")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=False, next_query="again")],
        budget=LoopBudget(max_hops=5),
        generator=FakeLLM(),
    )
    result = flow.ask("what color is the sky")
    assert result.evidence.loop is not None
    assert result.evidence.loop.stop_reason is LoopStopReason.no_new_evidence
    assert result.evidence.loop.hops == 2
    assert result.evidence.decision is Decision.answered


def test_pooling_across_hops_beats_single_passage() -> None:
    # A gather question: fact 1 in doc1, fact 2 in doc2, reached on hop 2.
    def search(query: str, k: int) -> list[Row]:
        if "second" in query:
            return [_row("b", "paris is the capital", document_id="doc2")]
        return [_row("a", "france is in europe", document_id="doc1")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=False, next_query="second fact"), LoopDecision(sufficient=True)],
        budget=LoopBudget(max_hops=4),
        generator=FakeLLM(),
    )
    result = flow.ask("tell me about france")
    assert result.evidence.loop is not None
    assert result.evidence.loop.stop_reason is LoopStopReason.sufficient
    assert result.evidence.loop.evidence_units == 2
    assert result.evidence.distinct_documents == 2
    # Both documents' facts made it into the grounded answer (pooling beats single).
    assert "france is in europe" in result.answer
    assert "paris is the capital" in result.answer


def test_max_evidence_units_cap_stops_on_budget() -> None:
    def search(query: str, k: int) -> list[Row]:
        return [_row("a", "one"), _row("b", "two"), _row("c", "three")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=False, next_query="more")],
        budget=LoopBudget(max_hops=5, max_evidence_units=2),
        generator=FakeLLM(),
    )
    result = flow.ask("q")
    assert result.evidence.loop is not None
    assert result.evidence.loop.stop_reason is LoopStopReason.budget
    assert result.evidence.loop.evidence_units == 2


def test_max_hops_cap_stops_on_budget() -> None:
    calls = {"n": 0}

    def search(query: str, k: int) -> list[Row]:
        calls["n"] += 1
        return [_row(f"e{calls['n']}", f"fact {calls['n']}")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=False, next_query="keep going")],
        budget=LoopBudget(max_hops=2),
        generator=FakeLLM(),
    )
    result = flow.ask("q")
    assert result.evidence.loop is not None
    assert result.evidence.loop.hops == 2
    assert result.evidence.loop.tool_calls == 2
    assert result.evidence.loop.stop_reason is LoopStopReason.budget


# --- Timeout (whole-loop wall clock) ---------------------------------------


def test_timeout_bounds_a_hung_generation_and_discards_partial() -> None:
    def search(query: str, k: int) -> list[Row]:
        return [_row("a", "some evidence text")]

    class _HungGenerator:
        def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
            time.sleep(5.0)
            return "this partial text must never be emitted"

    flow = _flow(
        search,
        [LoopDecision(sufficient=True)],
        budget=LoopBudget(max_hops=2, timeout_s=0.3),
        generator=_HungGenerator(),
    )
    start = time.monotonic()
    result = flow.ask("q")
    elapsed = time.monotonic() - start
    assert elapsed < 3.0  # did not wait for the 5s hang
    assert result.evidence.decision is Decision.refused
    assert result.evidence.loop is not None
    assert result.evidence.loop.stop_reason is LoopStopReason.timeout
    # The partial generation is discarded, never gated-and-emitted.
    assert "must never be emitted" not in result.answer


def test_timeout_bounds_a_hung_tool_call() -> None:
    def search(query: str, k: int) -> list[Row]:
        time.sleep(5.0)
        return [_row("a", "late")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=True)],
        budget=LoopBudget(max_hops=2, timeout_s=0.3),
        generator=FakeLLM(),
    )
    start = time.monotonic()
    result = flow.ask("q")
    elapsed = time.monotonic() - start
    assert elapsed < 3.0
    assert result.evidence.decision is Decision.refused
    assert result.evidence.loop is not None
    assert result.evidence.loop.stop_reason is LoopStopReason.timeout


# --- The per-claim single-EU gate (truth bound) ----------------------------


def test_single_eu_claim_is_cited() -> None:
    def search(query: str, k: int) -> list[Row]:
        return [
            _row("a", "alpha beta", document_id="d1"),
            _row("b", "gamma delta", document_id="d2"),
        ]

    flow = _flow(
        search,
        [LoopDecision(sufficient=True)],
        budget=LoopBudget(max_hops=1),
        generator=_ScriptedGenerator("alpha beta. gamma delta"),
    )
    result = flow.ask("q")
    assert result.evidence.decision is Decision.answered
    assert result.evidence.all_claims_verified is True
    assert len(result.claims) == 2
    assert len(result.sources) == 2


def test_cross_eu_stitched_claim_is_rejected() -> None:
    # 'alpha delta' takes tokens from TWO EUs that never co-occurred — the union
    # reading would pass it; the single-EU gate must reject it.
    def search(query: str, k: int) -> list[Row]:
        return [_row("a", "alpha beta"), _row("b", "gamma delta")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=True)],
        budget=LoopBudget(max_hops=1),
        generator=_ScriptedGenerator("alpha delta"),
    )
    result = flow.ask("q")
    assert result.evidence.decision is Decision.refused
    assert "single-EU" in result.missing_evidence[0]


def test_partial_drops_unsupported_claim() -> None:
    def search(query: str, k: int) -> list[Row]:
        return [_row("a", "alpha beta"), _row("b", "gamma delta")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=True)],
        budget=LoopBudget(max_hops=1),
        generator=_ScriptedGenerator("alpha beta. alpha delta"),
    )
    result = flow.ask("q")
    assert result.evidence.decision is Decision.partial
    assert result.evidence.unsupported_claims_removed == 1
    assert "alpha beta" in result.answer
    # The ungrounded stitched claim never reaches the emitted answer.
    assert "alpha delta" not in result.answer


# --- stop_reason distinguishes abstain causes ------------------------------


def test_no_evidence_abstain_carries_no_new_evidence() -> None:
    def search(query: str, k: int) -> list[Row]:
        return []

    flow = _flow(
        search,
        [LoopDecision(sufficient=True)],
        budget=LoopBudget(max_hops=3),
        generator=FakeLLM(),
    )
    result = flow.ask("q")
    assert result.evidence.decision is Decision.refused
    assert result.evidence.loop is not None
    assert result.evidence.loop.stop_reason is LoopStopReason.no_new_evidence


def test_budget_abstain_carries_budget_reason() -> None:
    # Cap forces a budget stop; a stitched answer then abstains — but the loop's
    # stop_reason still reads 'budget', distinguishing it from a no-evidence stop.
    def search(query: str, k: int) -> list[Row]:
        return [_row("a", "alpha beta"), _row("b", "gamma delta"), _row("c", "epsilon")]

    flow = _flow(
        search,
        [LoopDecision(sufficient=False, next_query="more")],
        budget=LoopBudget(max_hops=5, max_evidence_units=2),
        generator=_ScriptedGenerator("alpha delta"),
    )
    result = flow.ask("q")
    assert result.evidence.decision is Decision.refused
    assert result.evidence.loop is not None
    assert result.evidence.loop.stop_reason is LoopStopReason.budget
