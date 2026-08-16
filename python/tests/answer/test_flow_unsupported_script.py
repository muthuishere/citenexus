"""ADR-0011: `unsupported_script` is a real signal, distinct from "no evidence".

Where the tokenizer cannot process a script, the Result must SAY so. Silently
returning the evidence-absent refusal for a capability gap is the specific thing
that let the ASCII-only tokenizer hide for the whole of 0.x — from the outside
both look like an abstain, but only one of them is a statement about evidence.
"""

from __future__ import annotations

from citenexus.answer.flow import AnswerFlow
from citenexus.answer.result import Decision
from citenexus.domain.trust import TrustMode
from citenexus.retrieve.types import Candidate, RetrievalSignal

_KHMER = "បុគ្គលិកមិនត្រូវបង្ហាញព័ត៌មានសម្ងាត់"
_JAPANESE = "従業員は機密情報を開示してはならない。"
_ENGLISH = "The employee shall not disclose confidential information."


def _candidate(text: str, *, eu_id: str = "d::0", language: str = "en") -> Candidate:
    return Candidate(
        eu_id=eu_id,
        text=text,
        passage=text,
        score=1.0,
        signal=RetrievalSignal.vector,
        document_id="d",
        language=language,
    )


class _Echo:
    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage


def test_unsupported_script_refusal_names_the_capability_gap() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_KHMER, [_candidate(_KHMER, language="km")])
    assert result.evidence.decision is Decision.refused
    assert result.evidence.unsupported_scripts == ("khmer",)
    assert result.missing_evidence == ("unsupported script: khmer",)


def test_evidence_absent_refusal_is_still_about_the_evidence() -> None:
    """The two refusals must stay distinguishable."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask("What is the capital of France?", [_candidate(_ENGLISH)])
    assert result.evidence.decision is Decision.refused
    assert result.evidence.unsupported_scripts == ()
    assert result.missing_evidence == ("no sufficiently relevant evidence found",)


def test_a_supported_non_latin_script_answers_instead_of_abstaining() -> None:
    """The measured defect: every Japanese answer abstained. It no longer does."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_JAPANESE, [_candidate(_JAPANESE, language="ja")], mode=TrustMode.strict)
    assert result.evidence.decision is Decision.answered
    assert result.evidence.unsupported_scripts == ()
    assert result.sources[0].passage == _JAPANESE


def test_capability_gap_in_the_evidence_is_reported_on_an_answered_result() -> None:
    """A gap the caller can act on, surfaced even when the answer succeeds."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(
        "Can the employee disclose confidential information?",
        [_candidate(_ENGLISH), _candidate(_KHMER, eu_id="d::1", language="km")],
    )
    assert result.evidence.decision is Decision.answered
    assert result.evidence.unsupported_scripts == ("khmer",)
    # The unreadable passage is reported, never cited: the gate cannot verify a
    # segmentation no fixture has checked.
    assert result.sources[0].passage == _ENGLISH


def test_latin_results_carry_no_script_signal_at_all() -> None:
    """Empty on every Latin-script Result, so existing Results are unchanged."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask("Can the employee disclose confidential information?", [_candidate(_ENGLISH)])
    assert result.evidence.decision is Decision.answered
    assert result.evidence.unsupported_scripts == ()
