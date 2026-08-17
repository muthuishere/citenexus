"""Flow-level conformance: the answer path bound to the COMMITTED vectors.

The Python twin of ``golang/answer/flow_conformance_test.go`` (2026-08-17). Each
suite reads its expectations from a committed fixture under ``conformance/cases/``
and pins the vector count EXACTLY — a ``> 0`` floor would let a shrunken file
pass, which is the hole these suites exist to close.

The fixtures are deliberately the ones that already pin the PRIMITIVES:

* ``language.json``    → the §11a chain (``lang/fallback.py``)
* ``tokenize_v2.json`` → ``tokenize.unsupported_scripts`` (ADR-0011)
* ``faithful_v2.json`` → ``answer.verify.is_supported_v2`` (ADR-0009)

Python already binds each primitive to ``AnswerFlow`` — unlike the ports, where
every one of these signals shipped as a constant wearing the primitive's name.
These suites hold the reference implementation to the same file the ports are
held to, from the FLOW side: binding the predicate alone is what let the 0.10.0
regression through.

Expectations are always read from the JSON; nothing here re-derives a verdict by
calling the code under test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from citenexus.answer.flow import AnswerFlow, Generator
from citenexus.answer.result import Decision, Result
from citenexus.retrieve.types import Candidate, RetrievalSignal

_CASES = Path(__file__).resolve().parents[2].parent / "conformance" / "cases"


def _load(name: str) -> Any:
    return json.loads((_CASES / name).read_text(encoding="utf-8"))


LANGUAGE_VECTORS: list[dict[str, Any]] = _load("language.json")
SCRIPT_VECTORS: dict[str, Any] = _load("tokenize_v2.json")
FAITHFUL_VECTORS: dict[str, Any] = _load("faithful_v2.json")

#: Bucket sizes, pinned. A vector silently dropped is a weakened contract that no
#: per-case assertion can see.
EXPECTED_LANGUAGE_VECTORS = 6
EXPECTED_CLAIMED_SCRIPT_VECTORS = 14
EXPECTED_UNCLAIMED_SCRIPT_VECTORS = 11
EXPECTED_FAITHFUL_ATTACKS = 9
EXPECTED_FAITHFUL_CONTROLS = 30

#: How many language vectors ``AnswerFlow.ask`` can EXPRESS. Python has both the
#: ``default_answer_language`` constructor argument and a detector, so more cases
#: are drivable here than in the Go port — but ``ask`` takes no
#: ``conversation_language``, so a case that turns on rung 3 alone is not
#: reproducible. The count is pinned so the subset cannot silently shrink.
EXPECTED_FLOW_DRIVABLE_LANGUAGE_VECTORS = 5

_PASSAGE = "The employee shall not disclose confidential information."


class _Echo:
    """A faithful generator — returns the cited passage verbatim."""

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return passage


class _Fixed:
    """A generator pinned to one string, whatever it is handed."""

    def __init__(self, out: str) -> None:
        self._out = out

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str:
        return self._out


def _candidate(
    text: str,
    *,
    eu_id: str = "d::0",
    document_id: str = "d",
    language: str | None = None,
) -> Candidate:
    return Candidate(
        eu_id=eu_id,
        document_id=document_id,
        text=text,
        passage=text,
        score=1.0,
        signal=RetrievalSignal.vector,
        language=language,
    )


def _ask(
    generator: Generator,
    question: str,
    candidates: list[Candidate],
    **kwargs: Any,
) -> Result:
    flow = AnswerFlow(
        generator=generator,
        default_answer_language=kwargs.pop("default_answer_language", "en"),
    )
    return flow.ask(question, candidates, **kwargs)


def _ids(vectors: list[dict[str, Any]], key: str) -> list[Any]:
    return [pytest.param(v, id=str(v[key])) for v in vectors]


# ---------------------------------------------------------------------------
# GAP 1 — the answer language comes from the chain; the evidence languages are
# an OBSERVATION, reported and never fed back in.
# ---------------------------------------------------------------------------


def _flow_drivable(vector: dict[str, Any]) -> bool:
    """Can ``AnswerFlow.ask`` reproduce this committed case?

    ``ask`` accepts the caller's ``answer_language`` and the flow's
    ``default_answer_language``, but not a ``conversation_language``. So rung 1
    is always drivable (it wins outright, and the rungs below cannot matter), and
    everything else is drivable only when rung 3 is not in play.
    """
    if vector["answer_language"]:
        return True
    return vector["conversation_language"] is None


def test_language_vector_count_is_pinned() -> None:
    assert len(LANGUAGE_VECTORS) == EXPECTED_LANGUAGE_VECTORS
    drivable = [v for v in LANGUAGE_VECTORS if _flow_drivable(v)]
    assert len(drivable) == EXPECTED_FLOW_DRIVABLE_LANGUAGE_VECTORS


@pytest.mark.parametrize("vector", _ids(LANGUAGE_VECTORS, "name"))
def test_flow_resolves_the_answer_language_through_the_chain(vector: dict[str, Any]) -> None:
    if not _flow_drivable(vector):
        pytest.skip("rung 3 only: AnswerFlow.ask takes no conversation_language")
    result = _ask(
        _Echo(),
        _PASSAGE,
        [_candidate(_PASSAGE)],
        answer_language=vector["answer_language"],
        default_answer_language=vector["default_answer_language"],
    )
    # The committed expectation, read from the fixture — never re-derived by
    # calling resolve_answer_language here.
    assert result.answer_language == vector["expected"], vector["name"]


@pytest.mark.parametrize("vector", _ids(LANGUAGE_VECTORS, "name"))
def test_flow_reports_observed_evidence_languages_not_the_answer_language(
    vector: dict[str, Any],
) -> None:
    """The evidence languages come back out; the passage language is the DOCUMENT's.

    Stamp the committed languages onto real candidates. They are an OBSERVATION
    to report, never an input to the chain — so whatever they are, they must come
    back on ``languages_in_evidence``, distinct and in pool order.
    """
    declared: list[str] = vector["languages_in_evidence"]
    candidates = [
        _candidate(
            _PASSAGE,
            eu_id=f"{chr(ord('a') + i)}::0",
            document_id=chr(ord("a") + i),
            language=language,
        )
        for i, language in enumerate(declared)
    ] or [_candidate(_PASSAGE)]

    result = _ask(_Echo(), _PASSAGE, candidates)

    assert result.evidence.decision is Decision.answered, vector["name"]
    assert result.evidence.languages_in_evidence == tuple(dict.fromkeys(declared)), vector["name"]
    # The cited passage reports the DOCUMENT's declared language, or the pinned
    # "und" — never the answer language. This is the assertion that fails if
    # anyone reintroduces a `passage_language = answer_language` shortcut.
    assert len(result.sources) == 1
    assert result.sources[0].passage_language == (declared[0] if declared else "und")


# ---------------------------------------------------------------------------
# GAP 2 — unsupported_scripts is populated from the tokenizer, so "I cannot read
# this script" stays distinguishable from "I have no evidence" (ADR-0011).
# ---------------------------------------------------------------------------


def test_script_vector_counts_are_pinned() -> None:
    assert len(SCRIPT_VECTORS["supported"]) == EXPECTED_CLAIMED_SCRIPT_VECTORS
    assert len(SCRIPT_VECTORS["unclaimed"]) == EXPECTED_UNCLAIMED_SCRIPT_VECTORS


@pytest.mark.parametrize("vector", _ids(SCRIPT_VECTORS["unclaimed"], "script"))
def test_flow_refuses_an_unreadable_question_as_a_capability_gap(vector: dict[str, Any]) -> None:
    result = _ask(_Echo(), vector["text"], [_candidate(vector["text"])])

    assert result.evidence.decision is Decision.refused, vector["script"]
    # The committed capability signal, read from the fixture.
    assert result.evidence.unsupported_scripts == tuple(vector["unsupported_scripts"])
    assert result.missing_evidence[0] == "unsupported script: " + ", ".join(
        vector["unsupported_scripts"]
    )


@pytest.mark.parametrize("vector", _ids(SCRIPT_VECTORS["supported"], "script"))
def test_flow_reports_no_script_gap_for_every_claimed_script(vector: dict[str, Any]) -> None:
    result = _ask(_Echo(), vector["text"], [_candidate(vector["text"])])

    assert result.evidence.unsupported_scripts == tuple(vector["unsupported_scripts"])
    assert result.evidence.decision is Decision.answered, vector["script"]


# ---------------------------------------------------------------------------
# GAP 3 — verification is per ATOMIC CLAIM with drop-not-fail (ADR-0009).
# ---------------------------------------------------------------------------


def test_faithful_vector_counts_are_pinned() -> None:
    assert len(FAITHFUL_VECTORS["attacks"]) == EXPECTED_FAITHFUL_ATTACKS
    assert len(FAITHFUL_VECTORS["controls"]) == EXPECTED_FAITHFUL_CONTROLS


@pytest.mark.parametrize("vector", _ids(FAITHFUL_VECTORS["attacks"], "name"))
def test_flow_drops_an_unsupported_claim_and_keeps_the_supported_one(
    vector: dict[str, Any],
) -> None:
    """The drop-not-fail contract, over the committed adversarial vectors.

    A generation that is one VERBATIM sentence followed by the committed FALSE
    one must return the verbatim half and drop the lie — with both verdicts
    recorded. Failing whole loses a true, cited sentence to its neighbour.
    """
    assert vector["supported"] is False, "attack vector is committed as supported"
    generated = vector["passage"] + " " + vector["answer"]
    result = _ask(_Fixed(generated), vector["passage"], [_candidate(vector["passage"])])

    assert result.evidence.decision is Decision.answered, vector["name"]
    assert result.answer == vector["passage"]
    assert result.evidence.all_claims_verified is False
    assert result.evidence.unsupported_claims_removed == 1
    assert [(c.claim, c.supported) for c in result.claims] == [
        (vector["passage"], True),
        (vector["answer"], False),
    ]
    # The dropped claim cites nothing: an unsupported claim must never carry an
    # evidence-unit id, or a caller could follow the citation and find the lie
    # "sourced".
    assert result.claims[1].sources == ()


@pytest.mark.parametrize("vector", _ids(FAITHFUL_VECTORS["attacks"], "name"))
def test_flow_refuses_when_no_claim_survives(vector: dict[str, Any]) -> None:
    """An answer with NO surviving claim is the GATE's refusal, not evidence-absent."""
    result = _ask(_Fixed(vector["answer"]), vector["passage"], [_candidate(vector["passage"])])

    assert result.evidence.decision is Decision.refused, vector["name"]
    assert result.missing_evidence[0] == "generated answer failed the faithfulness gate"


@pytest.mark.parametrize("vector", _ids(FAITHFUL_VECTORS["controls"], "name"))
def test_flow_keeps_every_control_answer_whole(vector: dict[str, Any]) -> None:
    assert vector["supported"] is True, "control vector is committed as unsupported"
    result = _ask(_Fixed(vector["answer"]), vector["passage"], [_candidate(vector["passage"])])

    assert result.evidence.decision is Decision.answered, vector["name"]
    assert result.evidence.all_claims_verified is True
    assert result.evidence.unsupported_claims_removed == 0
