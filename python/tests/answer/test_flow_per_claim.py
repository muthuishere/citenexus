"""ADR-0009: per-claim verification with drop-not-fail in the strict flow.

Before this change `flow.py` emitted `claims=(claim,)` — one claim covering the
whole answer — so a partly-supported answer had no representable state and was
discarded whole. `Result.claims` and `unsupported_claims_removed` were shaped
for per-claim verdicts the flow could not produce.
"""

from __future__ import annotations

from citenexus.answer.flow import AnswerFlow, Generator
from citenexus.answer.result import Decision, Result
from citenexus.retrieve.types import Candidate, RetrievalSignal

_PASSAGE = "The contractor shall maintain liability insurance at all times."


def _candidate(text: str = _PASSAGE) -> Candidate:
    return Candidate(
        eu_id="msa::0",
        text=text,
        passage=text,
        score=1.0,
        signal=RetrievalSignal.vector,
        document_id="msa",
        language="en",
    )


class _Echo:
    """Faithful generator — returns the passage verbatim."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage


class _HalfTrue:
    """One supported claim plus one fabricated claim."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return f"{passage} This obligation expires after twelve months."


class _WhollyFalse:
    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return "The obligation expires after twelve months and cannot be renewed."


class _Inverting:
    """Reorders the parties — every token is present, the meaning is inverted."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return "The liability insurance shall maintain the contractor at all times."


def _ask(generator: Generator) -> Result:
    flow = AnswerFlow(generator=generator)
    return flow.ask("Must the contractor maintain liability insurance?", [_candidate()])


def test_fully_supported_answer_is_answered() -> None:
    result = _ask(_Echo())
    assert result.evidence.decision is Decision.answered
    assert result.evidence.unsupported_claims_removed == 0
    assert result.claims
    assert all(c.supported for c in result.claims)


def test_partly_supported_answer_degrades_to_its_supported_subset() -> None:
    result = _ask(_HalfTrue())

    assert result.evidence.decision is Decision.answered
    assert result.evidence.unsupported_claims_removed == 1
    # the fabricated sentence must not reach the caller's answer text
    assert "twelve months" not in result.answer
    assert "liability insurance" in result.answer
    # but the drop stays auditable
    assert [c.supported for c in result.claims] == [True, False]
    assert result.evidence.all_claims_verified is False


def test_wholly_unsupported_answer_is_refused() -> None:
    result = _ask(_WhollyFalse())
    assert result.evidence.decision is Decision.refused
    assert result.claims == ()
    assert "twelve months" not in result.answer


def test_reordered_answer_is_refused() -> None:
    """The attack class from spikes/library-stress/ — every token present, meaning inverted."""
    result = _ask(_Inverting())
    assert result.evidence.decision is Decision.refused


def test_surviving_claims_each_carry_provenance() -> None:
    result = _ask(_HalfTrue())
    supported = [c for c in result.claims if c.supported]
    assert len(result.provenance) == len(supported)
    for entry in result.provenance:
        assert entry.evidence_unit == "msa::0"
        assert entry.document_id == "msa"
