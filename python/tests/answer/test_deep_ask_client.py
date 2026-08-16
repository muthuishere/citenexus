"""The ``strategy=`` seam on ``client.ask()`` — strict default, deep opt-in.

Strict stays byte-identical to today; deep runs the agentic loop and ends in the
per-claim single-EU gate over verbatim EUs. All offline with fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from citenexus import CiteNexus
from citenexus.answer.agentic import LoopBudget
from citenexus.answer.decision import LoopDecision
from citenexus.answer.result import Decision
from citenexus.config.schema import CiteNexusConfig, GraphConfig, StorageConfig
from citenexus.testing import FakeEmbedding, FakeLLM
from citenexus.testing.fakes import FakeToolLLM


def _deep_rag(tmp_path: Path) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        agentic_decider=FakeToolLLM([LoopDecision(sufficient=True)]),
        agentic_budget=LoopBudget(max_hops=2),
        top_k=5,
    )


def test_default_strategy_is_strict_and_unchanged(tmp_path: Path) -> None:
    rag = _deep_rag(tmp_path)
    rag.ingest(text="Termination requires thirty days notice.", document_id="contract")
    q = "What does termination require?"
    default = rag.ask(q)
    explicit = rag.ask(q, strategy="strict")
    assert default == explicit
    # The strict flow carries no loop signal — Results are byte-identical to today.
    assert default.evidence.loop is None


def test_unknown_strategy_raises(tmp_path: Path) -> None:
    rag = _deep_rag(tmp_path)
    rag.ingest(text="anything", document_id="d")
    with pytest.raises(ValueError, match="unknown ask strategy"):
        rag.ask("q", strategy="galaxy-brain")


def test_deep_pools_multiple_passages_beating_strict(tmp_path: Path) -> None:
    rag = _deep_rag(tmp_path)
    rag.ingest(text="The capital of France is Paris.", document_id="capital")
    rag.ingest(text="France is located in Europe.", document_id="geo")

    q = "Where is France located and what is its capital?"
    strict = rag.ask(q, strategy="strict")
    deep = rag.ask(q, strategy="deep")

    assert deep.evidence.decision is Decision.answered
    assert deep.evidence.loop is not None
    # Deep pools both documents; the grounded answer carries both facts.
    assert "Paris" in deep.answer
    assert "Europe" in deep.answer
    assert deep.evidence.loop.evidence_units >= 2
    # Strict answers from a single passage — it cannot carry both facts.
    assert not ("Paris" in strict.answer and "Europe" in strict.answer)


def test_deep_without_generator_raises(tmp_path: Path) -> None:
    rag = CiteNexus(tmp_path, embedder=FakeEmbedding())  # no generator
    rag.ingest(text="something", document_id="d")
    with pytest.raises(ValueError, match="answering model"):
        rag.ask("q", strategy="deep")


def test_from_config_honors_graph_max_hops(tmp_path: Path) -> None:
    config = CiteNexusConfig(
        storage=StorageConfig(bucket=str(tmp_path)),
        graph=GraphConfig(max_hops=3),
    )
    rag = CiteNexus.from_config(config)
    assert rag._agentic_budget is not None
    assert rag._agentic_budget.max_hops == 3
