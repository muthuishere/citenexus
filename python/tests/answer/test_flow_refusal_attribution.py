"""A refusal must name the cause that ACTUALLY applies.

Measured 2026-08-16 on `examples/multilingual/`: **11 of 14 refusals** reported
`unsupported script: unknown` — including for pure-English questions over an
English pool — because the flow computed a script gap over EVERY pooled candidate
and used it as the refusal reason before falling through to "no sufficiently
relevant evidence found". A caller debugging an English-only corpus was told
their script was unsupported.

That is ADR-0011's conflation running backwards: the capability channel swallowed
the evidence channel. The gap may be named only when it genuinely explains the
refusal.
"""

from __future__ import annotations

from citenexus.answer.flow import AnswerFlow
from citenexus.answer.result import Decision
from citenexus.retrieve.types import Candidate, RetrievalSignal

_ENGLISH = "The employee shall not disclose confidential information."
_UNRELATED_EN = "The office cafeteria serves lunch between noon and two."
_KHMER = "បុគ្គលិកមិនត្រូវបង្ហាញព័ត៌មានសម្ងាត់"
_LAO = "ພະນັກງານບໍ່ຄວນເປີດເຜີຍຂໍ້ມູນລັບ"

_Q_EN = "How many days of unused leave can I carry forward?"


def _candidate(
    text: str, *, eu_id: str = "d::0", document_id: str = "d", language: str = "en"
) -> Candidate:
    return Candidate(
        eu_id=eu_id,
        text=text,
        passage=text,
        score=1.0,
        signal=RetrievalSignal.vector,
        document_id=document_id,
        language=language,
    )


class _Echo:
    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage


class _Fabricator:
    """Always returns something no passage supports — a pure gate failure."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return "Quarterly revenue rose by fourteen percent in the Baltic region."


# --------------------------------------------------------------------------- #
# The measured defect
# --------------------------------------------------------------------------- #


def test_english_refusal_over_an_english_pool_blames_the_evidence() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q_EN, [_candidate(_UNRELATED_EN)])
    assert result.evidence.decision is Decision.refused
    assert result.missing_evidence == ("no sufficiently relevant evidence found",)


def test_one_unreadable_passage_does_not_rewrite_an_unrelated_refusal() -> None:
    """The exact measured shape: English question, English pool, one Khmer row."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(
        _Q_EN,
        [
            _candidate(_UNRELATED_EN),
            _candidate(_KHMER, eu_id="x::0", document_id="x", language="km"),
        ],
    )
    assert result.evidence.decision is Decision.refused
    # The PRIMARY reason is about the evidence, because the evidence is what
    # failed: we could read part of the pool and none of it was relevant.
    assert result.missing_evidence[0] == "no sufficiently relevant evidence found"
    # The gap is reported ADDITIVELY, after the real reason -- never instead of it.
    assert "khmer" in result.missing_evidence[1]
    assert result.evidence.unsupported_scripts == ("khmer",)


def test_many_unreadable_passages_still_do_not_rewrite_it() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(
        _Q_EN,
        [
            _candidate(_UNRELATED_EN),
            _candidate(_KHMER, eu_id="x::0", document_id="x", language="km"),
            _candidate(_LAO, eu_id="y::0", document_id="y", language="lo"),
        ],
    )
    assert result.missing_evidence[0] == "no sufficiently relevant evidence found"
    assert "khmer" in result.missing_evidence[1] and "lao" in result.missing_evidence[1]
    assert result.evidence.unsupported_scripts == ("khmer", "lao")


# --------------------------------------------------------------------------- #
# When the gap really is the cause, say so
# --------------------------------------------------------------------------- #


def test_an_all_unreadable_pool_names_the_script() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_Q_EN, [_candidate(_KHMER, document_id="x", language="km")])
    assert result.evidence.decision is Decision.refused
    reason = result.missing_evidence[0]
    assert "no readable evidence found" in reason
    assert "khmer" in reason
    assert result.evidence.unsupported_scripts == ("khmer",)


def test_an_all_unreadable_pool_names_every_script_it_could_not_read() -> None:
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(
        _Q_EN,
        [
            _candidate(_KHMER, eu_id="x::0", document_id="x", language="km"),
            _candidate(_LAO, eu_id="y::0", document_id="y", language="lo"),
        ],
    )
    reason = result.missing_evidence[0]
    assert "khmer" in reason and "lao" in reason


def test_an_unreadable_question_is_unchanged() -> None:
    """The one case where the gap really is the whole story."""
    flow = AnswerFlow(generator=_Echo())
    result = flow.ask(_KHMER, [_candidate(_KHMER, language="km")])
    assert result.missing_evidence == ("unsupported script: khmer",)


def test_the_two_unreadable_refusals_stay_distinguishable() -> None:
    """"I cannot read your question" is not "I cannot read the corpus"."""
    flow = AnswerFlow(generator=_Echo())
    question_gap = flow.ask(_KHMER, [_candidate(_KHMER, language="km")])
    corpus_gap = flow.ask(_Q_EN, [_candidate(_KHMER, language="km")])
    assert question_gap.missing_evidence != corpus_gap.missing_evidence


# --------------------------------------------------------------------------- #
# The gate refusal owns its own reason
# --------------------------------------------------------------------------- #


def test_a_gate_failure_is_blamed_on_the_gate() -> None:
    flow = AnswerFlow(generator=_Fabricator())
    result = flow.ask(
        "Can the employee disclose confidential information?", [_candidate(_ENGLISH)]
    )
    assert result.evidence.decision is Decision.refused
    assert result.missing_evidence == ("generated answer failed the faithfulness gate",)


def test_a_gate_failure_is_not_reattributed_by_an_unreadable_sibling() -> None:
    flow = AnswerFlow(generator=_Fabricator())
    result = flow.ask(
        "Can the employee disclose confidential information?",
        [
            _candidate(_ENGLISH),
            _candidate(_KHMER, eu_id="x::0", document_id="x", language="km"),
        ],
    )
    assert result.missing_evidence[0] == "generated answer failed the faithfulness gate"
    assert "khmer" in result.missing_evidence[1]
    assert result.evidence.unsupported_scripts == ("khmer",)


# --------------------------------------------------------------------------- #
# The clean corpus is untouched
# --------------------------------------------------------------------------- #


def test_a_readable_corpus_never_mentions_a_script() -> None:
    flow = AnswerFlow(generator=_Echo())
    for question in (_Q_EN, "What is the capital of France?", "unrelated words entirely"):
        result = flow.ask(question, [_candidate(_UNRELATED_EN)])
        assert result.evidence.unsupported_scripts == ()
        assert all("script" not in reason for reason in result.missing_evidence)
