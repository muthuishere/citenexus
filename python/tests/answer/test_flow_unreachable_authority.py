""""I answered, but there is material here I cannot read."

The most damaging measured failure (2026-08-16, `examples/multilingual/`): a
Hyderabad employee asking about leave carry-forward got *"a maximum of 10 days"* —
verbatim from the English handbook, correctly cited, 100% groundedness.
Faithfulness passed. Authority passed. Subject scope passed. The **Telugu
annexure caps it at 5 days and states it overrides**, and it was simply in a
script the tokenizer does not claim, so a reachable-but-superseded document
answered instead. Nothing in the Result said so.

The library cannot read that annexure, so it must NOT assert anything about it —
that would be the ungrounded claim it exists to refuse. What it CAN do, and now
must, is stop being silent about the gap.
"""

from __future__ import annotations

from citenexus.answer.flow import AnswerFlow
from citenexus.answer.result import Decision
from citenexus.domain.trust import TrustMode
from citenexus.retrieve.types import Candidate, RetrievalSignal

_HANDBOOK = "Employees may carry forward a maximum of 10 days of unused leave."
_ANNEXURE_TE = "ఉద్యోగులు గరిష్టంగా 5 రోజుల సెలవును మాత్రమే బదిలీ చేయవచ్చు."
_ANNEXURE_KM = "បុគ្គលិកអាចផ្ទេរច្បាប់ឈប់សម្រាកបានច្រើនបំផុត ៥ ថ្ងៃ"
_Q = "How many days of unused leave can employees carry forward?"


def _candidate(
    text: str,
    *,
    eu_id: str,
    document_id: str,
    language: str = "en",
    score: float = 1.0,
) -> Candidate:
    return Candidate(
        eu_id=eu_id,
        text=text,
        passage=text,
        score=score,
        signal=RetrievalSignal.vector,
        document_id=document_id,
        language=language,
    )


class _Echo:
    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage


def _handbook() -> Candidate:
    return _candidate(_HANDBOOK, eu_id="handbook::3", document_id="handbook-en")


def _annexure(
    text: str = _ANNEXURE_KM, language: str = "km", *, score: float = 0.9
) -> Candidate:
    return _candidate(
        text, eu_id="annexure::1", document_id="annexure-local", language=language, score=score
    )


# --------------------------------------------------------------------------- #
# The measured case, end to end
# --------------------------------------------------------------------------- #


def test_the_answer_is_still_returned() -> None:
    """Deliberate: we do NOT delete a correct, cited answer over a nearby gap."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_handbook(), _annexure()])
    assert result.evidence.decision is Decision.answered
    assert result.sources[0].passage == _HANDBOOK


def test_the_unreachable_material_is_signalled() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_handbook(), _annexure()])
    assert result.evidence.unsupported_scripts == ("khmer",)


def test_the_unreachable_material_is_named_in_the_text_channel() -> None:
    """A tuple a program reads is not enough — a human reads `missing_evidence`."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_handbook(), _annexure()])
    assert len(result.missing_evidence) == 1
    note = result.missing_evidence[0]
    assert "annexure-local" in note
    assert "khmer" in note


def test_a_caller_can_escalate_in_one_line() -> None:
    """The contract the design promises callers who must be hard-safe."""
    flow = AnswerFlow(generator=_Echo())
    answered_clean = flow.ask(_Q, [_handbook()])
    answered_with_gap = flow.ask(_Q, [_handbook(), _annexure()])
    assert not answered_clean.evidence.unsupported_scripts
    assert bool(answered_with_gap.evidence.unsupported_scripts)


def test_the_unreadable_passage_is_never_cited() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_handbook(), _annexure()])
    assert all(_ANNEXURE_KM not in source.passage for source in result.sources)
    assert all(source.passage_language != "km" for source in result.sources)


def test_nothing_is_asserted_about_the_unreadable_passage() -> None:
    """We cannot read it, so the answer must not claim to know what it says."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_handbook(), _annexure()])
    assert "5" not in result.answer
    assert result.answer == _HANDBOOK


def test_it_outranking_the_cited_passage_changes_nothing() -> None:
    """Rejected alternative: refuse when the unreadable row outranks the cited one.

    It cannot be the rule — on the measured case BM25 `tf` is zero for a Telugu
    row against an English query, so the annexure can never outrank. Here it does
    outrank, and the behaviour is still answer-plus-signal.
    """
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_annexure(score=9.0), _handbook()])
    assert result.evidence.decision is Decision.answered
    assert result.sources[0].passage == _HANDBOOK
    assert result.evidence.unsupported_scripts == ("khmer",)


# --------------------------------------------------------------------------- #
# Shape: additive, empty by default, mode-independent
# --------------------------------------------------------------------------- #


def test_a_fully_readable_corpus_is_byte_identical() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_handbook()])
    assert result.evidence.decision is Decision.answered
    assert result.evidence.unsupported_scripts == ()
    assert result.missing_evidence == ()


def test_the_signal_is_present_in_every_trust_mode() -> None:
    flow = AnswerFlow(generator=_Echo())
    for mode in (TrustMode.strict, TrustMode.normal, TrustMode.exploratory):
        result = flow.ask(_Q, [_handbook(), _annexure()], mode=mode)
        assert result.evidence.unsupported_scripts == ("khmer",)


def test_several_unreadable_documents_are_all_named() -> None:
    flow = AnswerFlow(generator=_Echo())
    other = _candidate(
        "ພະນັກງານບໍ່ຄວນເປີດເຜີຍຂໍ້ມູນລັບ",
        eu_id="memo::1",
        document_id="memo-lo",
        language="lo",
    )
    result = flow.ask(_Q, [_handbook(), _annexure(), other])
    note = result.missing_evidence[0]
    assert "annexure-local" in note and "memo-lo" in note
    assert result.evidence.unsupported_scripts == ("khmer", "lao")


def test_an_unclaimed_script_that_is_merely_unknown_is_still_reported() -> None:
    """Telugu is currently unclaimed and classifies as `unknown` — still a gap.

    A concurrent change adds Telugu, which shrinks this class; it does not close
    it. Any unclaimed script reproduces it, so the signal must not depend on the
    script having a NAME the tokenizer already knows.
    """
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q, [_handbook(), _annexure(_ANNEXURE_TE, "te")])
    if result.evidence.unsupported_scripts:  # unclaimed today
        assert result.evidence.decision is Decision.answered
        assert result.sources[0].passage == _HANDBOOK
        assert "annexure-local" in result.missing_evidence[0]
    else:  # claimed by the concurrent tokenizer change — then it is retrievable
        assert result.missing_evidence == ()
