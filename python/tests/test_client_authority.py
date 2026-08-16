"""ADR-0004 end to end: metadata in at ingest, standing enforced at ask.

This is the whole-pipe version of the law-corpus defect — an out-of-jurisdiction
statute that is perfectly grounded and must still not be cited.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from citenexus import CiteNexus
from citenexus.answer.authority import INSUFFICIENT_AUTHORITY
from citenexus.answer.result import Decision
from citenexus.config.schema import AuthorityConfig, CiteNexusConfig, StorageConfig
from citenexus.domain.authority import AuthorityPolicy, decode_authority_meta
from citenexus.testing import FakeEmbedding, FakeLLM

_ORDER = ("out-of-jurisdiction", "secondary-blog", "general-statute", "controlling-statute")
_FLOORED = AuthorityPolicy.ordered(_ORDER, minimum_tier="general-statute")

_FLORIDA = "A tenancy may be terminated by giving not less than 15 days notice."
_CALIFORNIA = "A tenancy may be terminated by giving not less than 30 days notice."

_QUESTION = "What notice terminates a tenancy?"


def _rag(tmp_path: Path, *, authority: AuthorityPolicy | None = None) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        authority=authority,
    )


class TestMetadataIsCarried:
    def test_ingest_metadata_reaches_the_candidate(self, tmp_path: Path) -> None:
        rag = _rag(tmp_path)
        rag.ingest(
            text=_FLORIDA,
            document_id="06-florida",
            authority={"authority_tier": "out-of-jurisdiction", "jurisdiction": "FL"},
        )
        hits = rag.retrieve(_QUESTION)
        assert hits
        meta = decode_authority_meta(hits[0].authority_meta)
        assert meta == {"authority_tier": "out-of-jurisdiction", "jurisdiction": "FL"}

    def test_ingest_without_metadata_is_unranked(self, tmp_path: Path) -> None:
        rag = _rag(tmp_path)
        rag.ingest(text=_CALIFORNIA, document_id="01-ca")
        hits = rag.retrieve(_QUESTION)
        assert hits
        assert hits[0].authority_meta == ""
        assert decode_authority_meta(hits[0].authority_meta) == {}


class TestFloorEndToEnd:
    def test_only_out_of_jurisdiction_evidence_abstains(self, tmp_path: Path) -> None:
        rag = _rag(tmp_path, authority=_FLOORED)
        rag.ingest(
            text=_FLORIDA,
            document_id="06-florida",
            authority={"authority_tier": "out-of-jurisdiction"},
        )
        result = rag.ask(_QUESTION)
        assert result.evidence.decision is Decision.refused
        assert result.missing_evidence == (INSUFFICIENT_AUTHORITY,)
        assert result.evidence.authority_floor_applied is True
        assert result.sources == ()

    def test_the_authority_is_cited_over_the_trap(self, tmp_path: Path) -> None:
        rag = _rag(tmp_path, authority=_FLOORED)
        rag.ingest(
            text=_FLORIDA,
            document_id="06-florida",
            authority={"authority_tier": "out-of-jurisdiction"},
        )
        rag.ingest(
            text=_CALIFORNIA,
            document_id="01-ca",
            authority={"authority_tier": "controlling-statute"},
        )
        result = rag.ask(_QUESTION)
        assert result.evidence.decision is Decision.answered
        assert result.sources[0].document == "01-ca"
        assert result.evidence.authority_tier == "controlling-statute"

    def test_unconfigured_client_is_unchanged(self, tmp_path: Path) -> None:
        rag = _rag(tmp_path)
        rag.ingest(
            text=_FLORIDA,
            document_id="06-florida",
            authority={"authority_tier": "out-of-jurisdiction"},
        )
        result = rag.ask(_QUESTION)
        assert result.evidence.decision is Decision.answered
        assert result.evidence.authority_tier == ""
        assert result.evidence.authority_floor_applied is False


class TestConfigSection:
    def test_ordered_profile_from_config(self, tmp_path: Path) -> None:
        config = CiteNexusConfig(
            storage=StorageConfig(bucket=str(tmp_path)),
            authority=AuthorityConfig(
                profile="ordered.v1",
                tier_order=_ORDER,
                minimum_tier="general-statute",
            ),
        )
        rag = CiteNexus.from_config(config)
        rag.ingest(
            text=_FLORIDA,
            document_id="06-florida",
            authority={"authority_tier": "out-of-jurisdiction"},
        )
        hits = rag.retrieve(_QUESTION)
        assert decode_authority_meta(hits[0].authority_meta)["authority_tier"] == (
            "out-of-jurisdiction"
        )

    def test_unknown_profile_is_a_clear_error(self, tmp_path: Path) -> None:
        config = CiteNexusConfig(
            storage=StorageConfig(bucket=str(tmp_path)),
            authority=AuthorityConfig(profile="astrology.v1"),
        )
        with pytest.raises(ValueError, match="unknown authority profile"):
            CiteNexus.from_config(config)

    def test_default_config_section_is_unranked(self, tmp_path: Path) -> None:
        config = CiteNexusConfig(storage=StorageConfig(bucket=str(tmp_path)))
        assert config.authority.profile == "default.v1"
        assert config.authority.minimum_tier is None
        CiteNexus.from_config(config)  # builds without raising
