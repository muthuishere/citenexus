"""conformance/cases/verify_answer.json and heading_check.json as a BINDING
contract (ADR-0016).

Mirrors ``golang/answer/verify_answer_conformance_test.go`` and
``golang/answer/heading_test.go`` case for case: the same fake checker (scores
by premise text, a unit id or "a+b" for a union premise, with per-claim
overrides), the same options, the same assertions and the same counts.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from citenexus.answer.glossary import GlossaryEntry
from citenexus.answer.heading import (
    HeadingRules,
    heading_name_unsupported,
    heading_needs_check,
    heading_needs_check_with,
)
from citenexus.answer.result import Decision, Result
from citenexus.answer.verify_answer import EvidenceUnit, VerifyOptions, verify_answer
from citenexus.answer.verify_roles import DEFAULT_ACTOR_LEXICON
from citenexus.answer.verify_union import union_premise

from .fixtures import load_case

VECTORS: list[dict[str, Any]] = load_case("verify_answer.json")["cases"]
HEADINGS: list[dict[str, Any]] = load_case("heading_check.json")["cases"]


class IdChecker:
    """Scores by passage (a unit's text, or a union premise), and by
    (claim, passage) where a vector pins one claim."""

    def __init__(self) -> None:
        self.by_passage: dict[str, tuple[float, float]] = {}
        self.by_claim: dict[tuple[str, str], tuple[float, float]] = {}
        self.calls = 0

    def check(self, claim: str, passage: str) -> tuple[float, float]:
        self.calls += 1
        pinned = self.by_claim.get((claim, passage))
        if pinned is not None:
            return pinned
        return self.by_passage.get(passage, (0.0, 0.0))


def _evidence(case: dict[str, Any]) -> list[EvidenceUnit]:
    return [
        EvidenceUnit(
            id=e.get("id", ""),
            document_id=e.get("document_id", ""),
            language=e.get("language", ""),
            text=e.get("text", ""),
        )
        for e in case.get("evidence") or []
    ]


def vector_options(case: dict[str, Any], *, eager: bool = False) -> tuple[VerifyOptions, IdChecker]:
    """The VerifyOptions and fake checker a vector drives (the Go loader)."""
    evidence = _evidence(case)
    by_id = {eu.id: eu for eu in evidence}

    def premise(key: str) -> str:
        a, plus, b = key.partition("+")
        if plus:
            return union_premise(by_id[a], by_id[b]).text
        return by_id[key].text if key in by_id else ""

    checker = IdChecker()
    for key, s in (case.get("checker") or {}).items():
        checker.by_passage[premise(key)] = (s[0], s[1])
    for key, claims in (case.get("checker_claims") or {}).items():
        for claim, s in claims.items():
            checker.by_claim[(claim, premise(key))] = (s[0], s[1])
    actors = None
    if case.get("actors"):
        actors = DEFAULT_ACTOR_LEXICON
        for actor_id, terms in case["actors"].items():
            actors = actors.with_terms(actor_id, *terms)
    entries = [
        GlossaryEntry(
            nl=e.get("nl", ""),
            en=e.get("en", ""),
            lemma_nl=e.get("lemma_nl", ""),
            lemma_en=e.get("lemma_en", ""),
            sep=e.get("sep", ""),
            class_=e.get("class", ""),
        )
        for e in case.get("glossary_entries") or []
    ]
    has_checker = bool(case.get("checker")) or bool(case.get("checker_claims"))
    opts = VerifyOptions(
        answer_language=case.get("answer_language", ""),
        admit_paraphrase=case.get("admit_paraphrase", False),
        name_aliases=case.get("name_aliases"),
        lead_in_frames=case.get("lead_in_frames"),
        glossary=[(g[0], g[1]) for g in case["glossary"]] if case.get("glossary") else None,
        glossary_entries=entries or None,
        conjunct_presence=case.get("conjunct_presence", False),
        actors=actors,
        checker=checker if has_checker else None,
        checker_name="fake" if has_checker else "",
        eager_scoring=eager,
    )
    return opts, checker


def run_vector(case: dict[str, Any], *, eager: bool = False) -> tuple[Result, IdChecker]:
    opts, checker = vector_options(case, eager=eager)
    return verify_answer(case["answer"], _evidence(case), opts), checker


def test_vector_counts() -> None:
    assert len(VECTORS) == 325
    assert sum(1 for c in VECTORS if c.get("must_refuse")) >= 5
    assert len(HEADINGS) == 14
    assert sum(1 for c in HEADINGS if c.get("must_refuse")) >= 3


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in VECTORS])
def test_verify_answer_vector(case: dict[str, Any]) -> None:
    res, _ = run_vector(case)
    expect = case["expect"]
    got = [(c.supported, c.reason) for c in res.claims]
    assert res.evidence.decision.value == expect["decision"], got
    if expect.get("conflicts_reported"):
        assert res.conflicts, "the conflict must still be REPORTED even when no claim is dropped"
    assert len(res.claims) == len(expect.get("claims") or []), got
    for i, want in enumerate(expect.get("claims") or []):
        claim = res.claims[i]
        assert claim.supported == want.get("supported", False), (i, got)
        assert claim.reason.startswith(want.get("reason", "")), (i, got)
    if case.get("must_refuse"):
        assert res.evidence.decision != Decision.answered, "must-refuse control was answered"


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in HEADINGS])
def test_heading_check_vector(case: dict[str, Any]) -> None:
    evidence = _evidence(case)
    expect = case["expect"]
    claim, reason = heading_needs_check(case["heading"], case.get("language", ""))
    assert claim == expect.get("needs_check", False), reason
    assert reason.startswith(expect.get("reason", ""))
    if expect.get("reason", "") == "":
        assert reason == ""
    name_reason = heading_name_unsupported(case["heading"], evidence, None)
    assert name_reason.startswith(expect.get("name_reason", ""))
    if expect.get("name_reason", "") == "":
        assert name_reason == ""
    answer = case["heading"]
    if case.get("cite"):
        answer += " [eu:" + case["cite"] + "]"
    res = verify_answer(
        answer,
        evidence,
        VerifyOptions(answer_language=case.get("language", ""), require_citations=True),
    )
    assert len(res.claims) == 1, res.claims
    if res.claims[0].supported:
        outcome = "admitted"
    elif claim or name_reason:
        outcome = "refused"
    else:
        outcome = "exempt"
    assert outcome == expect["outcome"], res.claims[0]
    if case.get("must_refuse"):
        assert outcome == "refused"


def test_heading_rules_are_injectable() -> None:
    rules = HeadingRules(modals={"nl": ("dient",)})
    assert heading_needs_check_with("Wat de werknemer dient te doen", "nl", rules)[0]
    # Host rules replace the defaults: "moet" is not in them.
    assert not heading_needs_check_with("De werknemer moet betalen", "nl", rules)[0]


def test_lazy_scoring_matches_eager() -> None:
    """Lazy scoring (the default) returns, for every vector with a checker, the
    same Result eager scoring returns — with no more checker calls."""
    eager_calls = lazy_calls = 0
    for case in VECTORS:
        if not case.get("checker") and not case.get("checker_claims"):
            continue
        eager, ec = run_vector(case, eager=True)
        lazy, lc = run_vector(case, eager=False)
        assert json.loads(eager.model_dump_json()) == json.loads(lazy.model_dump_json()), case[
            "name"
        ]
        eager_calls += ec.calls
        lazy_calls += lc.calls
    assert lazy_calls <= eager_calls
