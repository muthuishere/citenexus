"""``AnswerFlow`` walks past a top passage whose answer fails the faithfulness gate.

Generating only from ``grounded[0]`` made the gate a coin flip on one passage's
phrasing: a jewellery shop with 122 earrings indexed refused "Do you have
earrings?" while answering the same question lowercased. The abstain guarantee is
what must NOT move -- an answer is still only returned when ``is_supported()``
holds for the passage it cites -- so the assertions split between "recovers when
a later passage supports it" and "still abstains when none do".
"""

from __future__ import annotations

from citenexus.answer.flow import AnswerFlow
from citenexus.answer.result import Decision
from citenexus.retrieve.types import Candidate, RetrievalSignal


def _candidate(eu_id: str, text: str, score: float = 1.0) -> Candidate:
    return Candidate(
        eu_id=eu_id,
        score=score,
        signal=RetrievalSignal.vector,
        document_id=eu_id,
        text=text,
        language="en",
        checksum=f"sum-{eu_id}",
    )


class _PerPassageGenerator:
    """Echoes a scripted answer chosen by the passage it is handed."""

    def __init__(self, by_passage: dict[str, str]) -> None:
        self._by_passage = by_passage
        self.calls: list[str] = []

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        self.calls.append(passage)
        return self._by_passage.get(passage, "unsupported invented answer")


def test_falls_through_to_a_later_passage_that_passes_the_gate() -> None:
    top = "earrings are listed here"
    second = "the earrings section lists 122 items"
    generator = _PerPassageGenerator(
        {
            # Fails: "catalogue" is not a token of the top passage.
            top: "earrings are listed in the catalogue",
            second: "the earrings section lists 122 items",
        }
    )
    flow = AnswerFlow(generator=generator)

    result = flow.ask("Do you have earrings?", [_candidate("a", top), _candidate("b", second)])

    assert result.evidence.decision is Decision.answered
    assert result.answer == "the earrings section lists 122 items"
    # It really did reject the first passage before settling on the second.
    assert generator.calls == [top, second]
    assert result.sources[0].passage == second


def test_still_abstains_when_no_passage_supports_the_answer() -> None:
    generator = _PerPassageGenerator({})  # every passage yields an unsupported answer
    flow = AnswerFlow(generator=generator)

    result = flow.ask(
        "Do you have earrings?",
        [_candidate("a", "earrings one"), _candidate("b", "earrings two")],
    )

    assert result.evidence.decision is Decision.refused
    assert result.missing_evidence == ("generated answer failed the faithfulness gate",)


def test_generation_attempts_are_bounded() -> None:
    generator = _PerPassageGenerator({})
    flow = AnswerFlow(generator=generator)

    flow.ask("Do you have earrings?", [_candidate(str(i), f"earrings {i}") for i in range(20)])

    assert len(generator.calls) == 5
