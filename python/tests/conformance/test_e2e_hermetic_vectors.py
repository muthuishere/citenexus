"""conformance/cases/e2e_hermetic.json asserted as a BINDING contract.

This is the one that mattered most. ``scripts/gen_conformance.py:511`` computes
the expected outcomes with ``_hermetic_ask`` — a *reimplementation* that, by its
own docstring, "mirrors citenexus.smoke.SmokePipeline.ask". So the committed
vectors were derived from a mirror, and nothing in the Python suite ever ran the
REAL pipeline against them: Go did (``golang/answer/answer_test.go:37``) and JS
did (``js/src/answer/answer.test.ts:29``), while the reference port's own
cite-or-abstain flow was free to drift away from the contract two ports were
being held to.

Hermetic: LocalFs + local LanceDB + the pinned hash FakeEmbedding and extractive
FakeLLM. No network, no MinIO.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from citenexus.domain.partition import PartitionPath
from citenexus.smoke import SmokePipeline
from citenexus.storage.backend import LocalFsBackend
from citenexus.testing import FakeEmbedding, FakeLLM

from .fixtures import load_case

FIXTURE: dict[str, Any] = load_case("e2e_hermetic.json")
CORPUS: list[dict[str, str]] = FIXTURE["corpus"]
CASES: list[dict[str, Any]] = FIXTURE["cases"]

EXPECTED_COUNTS: dict[str, int] = {"corpus": 3, "cases": 4}
EXPECTED_TOP_K = 5


def test_fixture_shape_is_pinned() -> None:
    assert {"corpus": len(CORPUS), "cases": len(CASES)} == EXPECTED_COUNTS
    assert FIXTURE["top_k"] == EXPECTED_TOP_K


def test_both_outcomes_are_covered() -> None:
    """A cite-or-abstain fixture that never abstains proves only half the rule."""
    assert {c["expected"]["decision"] for c in CASES} == {"answered", "refused"}


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> SmokePipeline:
    tmp_path: Path = tmp_path_factory.mktemp("e2e_hermetic")
    p = SmokePipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PartitionPath.of(("workspace", "default")),
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        top_k=FIXTURE["top_k"],
    )
    for doc in CORPUS:
        p.ingest(doc["text"], doc["document_id"])
    return p


@pytest.mark.parametrize("case", [pytest.param(c, id=c["question"]) for c in CASES])
def test_e2e_vector(pipeline: SmokePipeline, case: dict[str, Any]) -> None:
    """Decision, answer, document, passage and eu_id — all five, no leniency."""
    expected = case["expected"]
    result = pipeline.ask(case["question"])

    assert result.evidence.decision.value == expected["decision"], case["question"]
    assert result.answer == expected["answer"], case["question"]

    got_document = result.sources[0].document if result.sources else None
    got_passage = result.sources[0].passage if result.sources else None
    got_eu_id = (
        result.claims[0].sources[0]
        if result.claims and result.claims[0].sources
        else None
    )

    assert got_document == expected["document"], case["question"]
    assert got_passage == expected["passage"], case["question"]
    assert got_eu_id == expected["eu_id"], case["question"]


def test_refusal_answer_is_the_pinned_string(pipeline: SmokePipeline) -> None:
    """Ports must abstain with the SAME sentence; a divergent refusal is a fork."""
    refused = [c for c in CASES if c["expected"]["decision"] == "refused"]
    assert refused, "fixture has no abstain case"
    for case in refused:
        assert case["expected"]["answer"] == FIXTURE["refusal_answer"]
        assert pipeline.ask(case["question"]).answer == FIXTURE["refusal_answer"]
