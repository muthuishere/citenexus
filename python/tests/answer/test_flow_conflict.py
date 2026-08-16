"""ADR-0007: conflict surfacing and duplicate collapse through the strict flow.

`EvidenceSignals.conflicts_detected` and `Result.conflicts` shipped as declared
fields with no producer, so every published Result asserted `conflicts_detected=0`
— not "we found none", but "we never looked". These tests pin the producer.
"""

from __future__ import annotations

from citenexus.answer.flow import AnswerFlow
from citenexus.answer.result import Decision
from citenexus.domain.trust import TrustMode
from citenexus.retrieve.types import Candidate, RetrievalSignal

_OLD = "The notice period is 30 days."
_NEW = "The notice period is 60 days."


def _candidate(text: str, *, eu_id: str, document_id: str, score: float = 1.0) -> Candidate:
    return Candidate(
        eu_id=eu_id,
        text=text,
        passage=text,
        score=score,
        signal=RetrievalSignal.vector,
        document_id=document_id,
        language="en",
    )


class _Echo:
    """Faithful generator — returns the offered passage verbatim."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage


def _conflicting() -> list[Candidate]:
    return [
        _candidate(_OLD, eu_id="a::0", document_id="policy-2019", score=1.0),
        _candidate(_NEW, eu_id="b::0", document_id="policy-2026", score=0.9),
    ]


def _flow() -> AnswerFlow:
    return AnswerFlow(generator=_Echo())


# ─────────────────────────────────────────────────────────────────────────────
# TrustMode coupling
# ─────────────────────────────────────────────────────────────────────────────


def test_strict_abstains_on_a_conflict_touching_the_answer() -> None:
    result = _flow().ask("What is the notice period?", _conflicting(), mode=TrustMode.strict)
    assert result.evidence.decision is Decision.refused
    assert result.evidence.conflicts_detected == 1
    assert len(result.conflicts) == 1
    assert result.missing_evidence


def test_strict_abstention_cites_both_sides_verbatim() -> None:
    """A refusal that hides the evidence is barely better than a confident pick."""
    result = _flow().ask("What is the notice period?", _conflicting(), mode=TrustMode.strict)
    passages = {source.passage for source in result.sources}
    documents = {source.document for source in result.sources}
    assert passages == {_OLD, _NEW}
    assert documents == {"policy-2019", "policy-2026"}


def test_strict_abstention_never_picks_a_winner() -> None:
    """Both documents appear; the answer text asserts nothing about either."""
    result = _flow().ask("What is the notice period?", _conflicting(), mode=TrustMode.strict)
    assert result.claims == ()
    assert "30" not in result.answer
    assert "60" not in result.answer


def test_normal_answers_and_surfaces_the_conflict() -> None:
    result = _flow().ask("What is the notice period?", _conflicting(), mode=TrustMode.normal)
    assert result.evidence.decision is Decision.answered
    assert result.evidence.conflicts_detected == 1
    assert len(result.conflicts) == 1
    assert "policy-2019" in result.conflicts[0]
    assert "policy-2026" in result.conflicts[0]


def test_exploratory_records_the_count_only() -> None:
    result = _flow().ask(
        "What is the notice period?", _conflicting(), mode=TrustMode.exploratory
    )
    assert result.evidence.decision is Decision.answered
    assert result.evidence.conflicts_detected == 1
    assert result.conflicts == ()


def test_conflict_elsewhere_in_the_pool_does_not_abstain_strict() -> None:
    """Only a conflict touching the answer's own claim blocks strict mode."""
    candidates = [
        _candidate(
            "The turbine is inspected every spring by the notice engineer.",
            eu_id="t::0",
            document_id="manual",
            score=1.0,
        ),
        _candidate(_OLD, eu_id="a::0", document_id="policy-2019", score=0.9),
        _candidate(_NEW, eu_id="b::0", document_id="policy-2026", score=0.8),
    ]
    result = _flow().ask(
        "Who inspects the turbine during the notice period?",
        candidates,
        mode=TrustMode.strict,
    )
    assert result.evidence.decision is Decision.answered
    assert result.evidence.conflicts_detected == 1
    assert result.conflicts == ()  # strict surfaces only what it abstains on


# ─────────────────────────────────────────────────────────────────────────────
# Corroboration signals
# ─────────────────────────────────────────────────────────────────────────────


def test_mirrors_are_not_counted_as_independent_corroboration() -> None:
    text = "The maintenance window opens at 02:00 UTC on Sunday."
    candidates = [
        _candidate(text, eu_id=f"m{i}::0", document_id=f"mirror-{i}", score=1.0 - i / 100)
        for i in range(5)
    ]
    result = _flow().ask("When does the maintenance window open?", candidates)
    assert result.evidence.decision is Decision.answered
    assert result.evidence.distinct_documents == 1
    assert result.evidence.supporting_sources == 1


def test_genuinely_distinct_evidence_is_still_counted() -> None:
    candidates = [
        _candidate(
            "The maintenance window opens at 02:00 UTC on Sunday.",
            eu_id="a::0",
            document_id="runbook",
            score=1.0,
        ),
        _candidate(
            "Operators are paged when the maintenance window opens.",
            eu_id="b::0",
            document_id="oncall",
            score=0.9,
        ),
    ]
    result = _flow().ask("When does the maintenance window open?", candidates)
    assert result.evidence.distinct_documents == 2
    assert result.evidence.supporting_sources == 2


# ─────────────────────────────────────────────────────────────────────────────
# No regression when nothing conflicts
# ─────────────────────────────────────────────────────────────────────────────


def test_agreeing_evidence_reports_zero_conflicts() -> None:
    candidates = [
        _candidate(_OLD, eu_id="a::0", document_id="policy-2019", score=1.0),
        _candidate(
            "Notices are delivered by registered post to the tenant address.",
            eu_id="b::0",
            document_id="annex",
            score=0.9,
        ),
    ]
    result = _flow().ask("What is the notice period?", candidates)
    assert result.evidence.decision is Decision.answered
    assert result.evidence.conflicts_detected == 0
    assert result.conflicts == ()
