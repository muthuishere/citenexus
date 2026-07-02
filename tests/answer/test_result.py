"""Result, SourceRef, EvidenceSignals, provenance chain (spec §12, §16, §11)."""

import pytest
from pydantic import ValidationError

from citenexus.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    ProvenanceEntry,
    Result,
    SourceRef,
)
from citenexus.domain.trust import TrustMode


def _result(answer_language: str = "en", evidence_langs: tuple[str, ...] = ("en",)) -> Result:
    return Result(
        answer="No. The employee cannot disclose confidential information.",
        answer_language=answer_language,
        mode=TrustMode.strict,
        evidence=EvidenceSignals(
            supporting_sources=2,
            distinct_documents=1,
            retrieval_score_spread=0.39,
            all_claims_verified=True,
            languages_in_evidence=evidence_langs,
            decision=Decision.answered,
        ),
        claims=(
            Claim(
                claim="The employee cannot disclose confidential information.",
                supported=True,
                sources=("eu_001", "eu_002"),
            ),
        ),
        sources=(
            SourceRef(
                document="nda.pdf",
                page=12,
                passage="The employee shall not disclose confidential information...",
                passage_language="en",
                bbox=(120, 300, 510, 380),
                source_uri="s3://bucket/raw/client-a/nda.pdf",
            ),
        ),
        provenance=(
            ProvenanceEntry(
                claim="The employee cannot disclose confidential information.",
                evidence_unit="eu_001",
                page=12,
                bbox=(120, 300, 510, 380),
                document_id="nda_2026",
                s3_object="s3://bucket/raw/client-a/nda.pdf",
                checksum="sha256:abc",
                produced_by={"extractor": "docling@0.21", "embedding": "bge-m3"},
            ),
        ),
    )


def test_signals_capture_why_the_system_answered() -> None:
    s = EvidenceSignals(
        supporting_sources=3,
        distinct_documents=2,
        all_claims_verified=True,
        decision=Decision.answered,
    )
    assert s.supporting_sources == 3
    assert s.decision is Decision.answered


def test_no_scalar_confidence_field_exists() -> None:
    assert "confidence" not in EvidenceSignals.model_fields
    assert "confidence" not in Result.model_fields


def test_invalid_decision_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceSignals(decision="maybe")


def test_untranslated_source_keeps_verbatim_passage() -> None:
    sr = SourceRef(
        document="nda.pdf",
        passage="The employee shall not disclose...",
        passage_language="en",
    )
    assert sr.translation is None
    assert sr.passage == "The employee shall not disclose..."


def test_translation_is_additive_never_destructive() -> None:
    sr = SourceRef(
        document="contrat.pdf",
        passage="Le salarié ne doit pas divulguer...",
        passage_language="fr",
        translation="The employee shall not disclose...",
    )
    assert sr.passage == "Le salarié ne doit pas divulguer..."
    assert sr.translation == "The employee shall not disclose..."
    assert sr.passage != sr.translation


def test_answer_language_independent_of_evidence_languages() -> None:
    r = _result(answer_language="ta", evidence_langs=("en",))
    assert r.answer_language == "ta"
    assert r.evidence.languages_in_evidence == ("en",)


def test_provenance_entry_forms_full_chain() -> None:
    r = _result()
    pe = r.provenance[0]
    assert pe.evidence_unit == "eu_001"
    assert pe.page == 12
    assert pe.bbox == (120, 300, 510, 380)
    assert pe.document_id == "nda_2026"
    assert pe.s3_object.startswith("s3://")
    assert pe.checksum == "sha256:abc"
    assert pe.produced_by is not None
    assert pe.produced_by["embedding"] == "bge-m3"


def test_result_json_round_trip() -> None:
    r = _result()
    assert Result.model_validate_json(r.model_dump_json()) == r
