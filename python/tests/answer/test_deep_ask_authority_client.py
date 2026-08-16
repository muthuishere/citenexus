"""The hole this change closes, reached the way a user reaches it.

`authority-floor` shipped the floor on the strict flow and recorded the gap in
its own tasks (4.7): `strategy="deep"` never took the policy. So the Florida
statute the floor refuses by default was still citable one keyword away. These
tests are the public-API proof, so the guarantee cannot regress on one strategy
while holding on the other.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.authority import INSUFFICIENT_AUTHORITY
from citenexus.answer.decision import LoopDecision
from citenexus.answer.result import Decision
from citenexus.config.schema import AuthorityConfig, CiteNexusConfig, StorageConfig
from citenexus.domain.authority import AuthorityPolicy
from citenexus.testing import FakeEmbedding, FakeLLM
from citenexus.testing.fakes import FakeToolLLM

_ORDER = ("out-of-jurisdiction", "secondary-blog", "general-statute", "controlling-statute")
_FLOORED = AuthorityPolicy.ordered(_ORDER, minimum_tier="general-statute")

_FLORIDA = "A tenancy may be terminated by giving not less than 15 days notice."
_TEXAS = "A tenancy may be terminated by giving not less than 30 days notice."

_QUESTION = "What notice terminates a tenancy?"


def _rag(tmp_path: Path, *, authority: AuthorityPolicy | None = None) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        agentic_decider=FakeToolLLM([LoopDecision(sufficient=True)]),
        authority=authority,
    )


def test_deep_ask_abstains_on_a_below_floor_source(tmp_path: Path) -> None:
    rag = _rag(tmp_path, authority=_FLOORED)
    rag.ingest(
        text=_FLORIDA,
        document_id="06-florida",
        authority={"authority_tier": "out-of-jurisdiction"},
    )
    result = rag.ask(_QUESTION, strategy="deep")
    assert result.evidence.decision is Decision.refused
    assert result.missing_evidence == (INSUFFICIENT_AUTHORITY,)
    assert result.evidence.authority_floor_applied is True
    assert result.sources == ()


def test_deep_ask_cites_the_authority_over_the_trap(tmp_path: Path) -> None:
    rag = _rag(tmp_path, authority=_FLOORED)
    rag.ingest(
        text=_FLORIDA,
        document_id="06-florida",
        authority={"authority_tier": "out-of-jurisdiction"},
    )
    rag.ingest(
        text=_TEXAS,
        document_id="02-texas",
        authority={"authority_tier": "controlling-statute"},
    )
    result = rag.ask(_QUESTION, strategy="deep")
    assert result.evidence.decision is Decision.answered
    assert [s.document for s in result.sources] == ["02-texas"]


def test_strict_and_deep_agree_on_standing(tmp_path: Path) -> None:
    """The point of the change: the guarantee is strategy-independent."""
    rag = _rag(tmp_path, authority=_FLOORED)
    rag.ingest(
        text=_FLORIDA,
        document_id="06-florida",
        authority={"authority_tier": "out-of-jurisdiction"},
    )
    strict = rag.ask(_QUESTION, strategy="strict")
    deep = rag.ask(_QUESTION, strategy="deep")
    assert strict.evidence.decision is deep.evidence.decision is Decision.refused
    assert strict.missing_evidence == deep.missing_evidence == (INSUFFICIENT_AUTHORITY,)


def test_a_config_declared_floor_reaches_deep_ask(tmp_path: Path) -> None:
    """No deep-specific ceremony: the declarative section drives both strategies."""
    config = CiteNexusConfig(
        storage=StorageConfig(bucket=str(tmp_path)),
        authority=AuthorityConfig(
            profile="ordered.v1",
            tier_order=_ORDER,
            minimum_tier="general-statute",
        ),
    )
    configured = CiteNexus.from_config(config)
    rag = CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        agentic_decider=FakeToolLLM([LoopDecision(sufficient=True)]),
        authority=configured._authority,
    )
    rag.ingest(
        text=_FLORIDA,
        document_id="06-florida",
        authority={"authority_tier": "out-of-jurisdiction"},
    )
    result = rag.ask(_QUESTION, strategy="deep")
    assert result.evidence.decision is Decision.refused
    assert result.missing_evidence == (INSUFFICIENT_AUTHORITY,)


def test_unconfigured_client_deep_ask_is_unchanged(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(
        text=_FLORIDA,
        document_id="06-florida",
        authority={"authority_tier": "out-of-jurisdiction"},
    )
    result = rag.ask(_QUESTION, strategy="deep")
    assert result.evidence.decision is Decision.answered
    assert result.evidence.authority_tier == ""
    assert result.evidence.authority_floor_applied is False
